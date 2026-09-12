"""Propose distinct, scoped questions from currently eligible original evidence."""

import json

from .automation import _read, _save
from .research_agenda import QuestionAgenda
from .research_context import _terms
from .research_graph_model import REVISION, validate_question, validate_question_review
from .research_graph_work import (GraphWork, agenda_status, bounded_packet, evidence, graph_inputs, nearby_questions,
                                  question_catalog, scoped_questions)


def _reviewed_relations(candidate, decision, packet, *, premise_predicate="raises_question", legacy=False):
    if legacy and "relations" not in decision:
        owners = {pid: source["record_id"] for source in packet["sources"] for pid in source["passage_ids"]}
        context = {"review_verdict": decision["verdict"], "review_reason": decision["reason"]}
        return [{"subject": "$question" if kind == "parent" else identifier, "predicate": predicate,
                 "object": identifier if kind == "parent" else "$question", "rationale": candidate["motivation"],
                 "context": dict(context), "evidence": evidence([
                     entry for entry in candidate["evidence"] if kind == "parent" or owners[entry["passage_id"]] == identifier], packet)}
                for kind, field, predicate in (("parent", "parents", "part_of"), ("premise", "premises", premise_predicate))
                for identifier in candidate[field]]
    decisions = {(r["kind"], r["record_id"]): r for r in decision["relations"]}
    passages = {p["id"]: p for p in packet["document"]["passages"]}
    relations = []
    for kind, field, predicate in (("parent", "parents", "part_of"), ("premise", "premises", premise_predicate)):
        for identifier in candidate[field]:
            review = decisions[(kind, identifier)]
            located = [{"source_id": passages[e["passage_id"]]["source_id"],
                        "locator": passages[e["passage_id"]]["locator"],
                        "note": "Relation assessment from the original source passage: " + review["reason"]}
                       for e in review["evidence"]]
            relations.append({"subject": "$question" if kind == "parent" else identifier,
                              "predicate": predicate, "object": identifier if kind == "parent" else "$question",
                              "rationale": review["reason"], "evidence": located,
                              "context": {"review_kind": kind, "review_record_id": identifier,
                                          "review_verdict": review["verdict"], "review_reason": review["reason"],
                                          **({"answer_scope": "", "remaining": candidate["title"]}
                                             if predicate == "raises_question" else {})}})
    return relations


class QuestionWorker(GraphWork):
    def __init__(self, research):
        super().__init__(research, "question")

    def select(self):
        pending = self.pending()
        if pending:
            return pending
        snapshot = self.research.inbox.snapshot()
        agenda = agenda_status(self.research, snapshot)
        questions = [q for q in scoped_questions(self.research, snapshot) if agenda[q["id"]]["can_generate_children"]]
        inputs = graph_inputs(self.research, snapshot)
        inputs = {key: item for key, item in inputs.items() if item["record"]["kind"] == "claim"}
        if not questions or not inputs:
            return None
        path = self.research.root / "question-selection.json"
        state = _read(path) if path.exists() else {"version": 1, "next_question": 0, "next_record": 0}
        if state.get("version") != 1 or type(state.get("next_question")) is not int or type(state.get("next_record")) is not int:
            raise ValueError("Invalid question selection state")
        offset = state["next_question"] % len(questions)
        questions = questions[offset:] + questions[:offset]
        done = {j["id"] for j in self.jobs()}
        for question in questions:
            wanted = _terms({k: question[k] for k in ("title", "summary")})
            ranked = sorted(inputs.values(), key=lambda item: (-len(wanted & _terms({k:item["record"][k] for k in ("title", "summary")})), item["record"]["id"]))
            sample = ranked[state["next_record"] % len(ranked)]
            selected = ranked[:2] + ([sample] if sample not in ranked[:2] else ranked[2:3])
            packet = bounded_packet(selected)
            state["next_question"] += 1
            state["next_record"] += 1
            _save(path, state, replace=True)
            if packet is None:
                continue
            nearby = nearby_questions(self.research, snapshot, question)
            views = sorted(snapshot["views"])
            job = self.new_job(question, packet, questions=nearby, views=views, question_catalog=question_catalog(snapshot))
            if job["id"] not in done:
                return job
        return None

    def generate(self, job):
        return self.research.model.propose_question(job["question"], job["packet"], job["questions"], job["views"])

    def valid(self, job):
        candidate = job["candidate"]["analysis"]
        # Duplicate comparison is ranked anew around the actual proposed wording.
        snapshot = self.research.inbox.snapshot()
        comparison = nearby_questions(self.research, snapshot, candidate)
        merged = {q["id"]: q for q in [*comparison, *job["questions"]]}
        job["questions"] = list(merged.values())
        return validate_question(candidate, job["packet"], job["questions"], job["views"])

    def review(self, job):
        options = {"premise_predicate": "informs"} if job.get("revision") != REVISION else {}
        return self.research.model.review_question(job["question"], job["packet"], job["candidate"]["analysis"],
                                                   job["questions"], job["views"], **options)

    def prepare(self, job, result):
        candidate = job["candidate"]["analysis"]
        legacy = job.get("revision") != REVISION
        decision = validate_question_review(job["review"], job["packet"], candidate, job["questions"], legacy=legacy)
        if decision["verdict"] != "useful":
            result["skipped" if decision["verdict"] == "duplicate" else "held"] = 1
            job["reason"] = decision["reason"]
            if decision["duplicate_of"]:
                job["duplicate_of"] = decision["duplicate_of"]
            return None
        rejected = [relation for relation in decision.get("relations", []) if relation["verdict"] != "supported"]
        if rejected:
            result["held"] = 1
            job["reason"] = "; ".join(relation["reason"] for relation in rejected)
            return None
        context = {"worker_role": "question", "derived_from": json.dumps(candidate["premises"]),
                   **{key: candidate[key] for key in ("scope", "limitations", "motivation", "advance")}}
        question = {"title": candidate["title"], "summary": candidate["summary"], "views": candidate["views"],
                    "context": context, "facets": job["question"]["facets"], "evidence": evidence(candidate["evidence"], job["packet"])}
        relations = _reviewed_relations(candidate, decision, job["packet"], legacy=legacy,
                                        premise_predicate="informs" if legacy else "raises_question")
        return self.proposal(job, self.research.inbox.snapshot(), question=question, relations=relations)

    def cycle(self):
        return self.run(self.select())
