"""Add grounded question links to existing findings, methods, and experiments."""

from .automation import _read, _save
from .research_agenda import QuestionAgenda
from .research_context import _terms
from .research_graph import graph_digest
from .research_graph_model import REVISION, LEGACY_PREDICATES, normalize_overlap_candidate, validate_overlap, validate_overlap_review
from .research_graph_work import GraphWork, agenda_status, bounded_packet, evidence, graph_inputs, scoped_questions
from .validation import EXPLICIT_QUESTION_PREDICATES


PREDICATES = LEGACY_PREDICATES


class OverlapWorker(GraphWork):
    def __init__(self, research):
        super().__init__(research, "overlap")
        self.agenda = QuestionAgenda(research.project)

    def new_job(self, question, packet, **extra):
        records = {r["id"]: r for r in self.research.inbox.snapshot()["bundle"]["items"]}
        extra.setdefault("record_kinds", {r["id"]: records[r["id"]]["kind"] for r in packet["records"]})
        return super().new_job(question, packet, **extra)

    def _record_kinds(self, job, snapshot=None):
        if "record_kinds" in job:
            return job["record_kinds"]
        records = {r["id"]: r for r in (snapshot or self.research.inbox.snapshot())["bundle"]["items"]}
        return {r["id"]: records[r["id"]]["kind"] for r in job["packet"]["records"]}

    def select(self):
        pending = self.pending()
        if pending:
            return pending
        snapshot = self.research.inbox.snapshot()
        inputs = graph_inputs(self.research, snapshot)
        questions = scoped_questions(self.research, snapshot)
        if not questions:
            return None
        state_path = self.research.root / "overlap-selection.json"
        state = _read(state_path) if state_path.exists() else {"version": 1, "next_question": 0, "next_record": 0}
        if state.get("version") != 1 or type(state.get("next_question")) is not int or type(state.get("next_record")) is not int:
            raise ValueError("Invalid overlap selection state")
        offset = state["next_question"] % len(questions)
        questions = questions[offset:] + questions[:offset]
        agenda = agenda_status(self.research, snapshot)
        existing = {(r["subject"], r["predicate"], r["object"]) for r in snapshot["bundle"]["relations"] if r["status"] != "withdrawn"}
        classified = {(subject, object_) for subject, predicate, object_ in existing if predicate in EXPLICIT_QUESTION_PREDICATES}
        questions.sort(key=lambda q: (
            q["context"].get("worker_role") != "question" or agenda[q["id"]]["overlap_attempted"],
            not any((identifier, q["id"]) not in classified and
                    (identifier, PREDICATES.get(item["record"]["kind"]), q["id"]) not in existing
                    for identifier, item in inputs.items())))
        done = {key for job in self.jobs() if job["role"] == self.role and job["status"] in {"recorded", "held", "failed", "skipped"}
                for key in job.get("pair_keys", [])}
        for question in questions:
            candidates = []
            for identifier, item in inputs.items():
                predicate = PREDICATES.get(item["record"]["kind"])
                if (predicate is None or (identifier, question["id"]) in classified or
                        (predicate != "informs" and (identifier, predicate, question["id"]) in existing)):
                    continue
                key = graph_digest({"revision": REVISION, "model": self.research.model.model,
                                    "question": question, "input": item})
                if key not in done:
                    candidates.append((key, item))
            if not candidates:
                self.agenda.overlapped(question["id"])
                continue
            wanted = _terms({k: question[k] for k in ("title", "summary")})
            candidates.sort(key=lambda row: (-len(wanted & _terms({k: row[1]["record"][k] for k in ("title", "summary")})), row[1]["record"]["id"]))
            # One rotating candidate keeps a large near-neighbor cluster from hiding the rest.
            sample = candidates[state["next_record"] % len(candidates)]
            selected = candidates[:2] + ([sample] if sample not in candidates[:2] else candidates[2:3])
            packet = bounded_packet([item for _, item in selected])
            state["next_question"] += 1
            state["next_record"] += 1
            _save(state_path, state, replace=True)
            if packet is None:
                self.agenda.overlapped(question["id"])
                continue
            ids = {r["id"] for r in packet["records"]}
            return self.new_job(question, packet, pair_keys=[key for key, item in selected if item["record"]["id"] in ids])
        state["next_question"] += 1
        _save(state_path, state, replace=True)
        return None

    def generate(self, job):
        return self.research.model.overlap(job["question"], job["packet"], record_kinds=self._record_kinds(job))

    def valid(self, job):
        return validate_overlap(job["candidate"]["analysis"], job["packet"],
                                legacy=job.get("revision") != REVISION, record_kinds=self._record_kinds(job))

    def review(self, job):
        candidate = normalize_overlap_candidate(job["candidate"]["analysis"], self._record_kinds(job))
        return self.research.model.review_overlap(job["question"], job["packet"], candidate)

    def prepare(self, job, result):
        snapshot = self.research.inbox.snapshot()
        kinds = self._record_kinds(job, snapshot)
        decisions = validate_overlap_review(job["review"], job["packet"], job["candidate"]["analysis"],
                                            legacy=job.get("revision") != REVISION, record_kinds=kinds)
        accepted = {d["record_id"]: d for d in decisions if d["verdict"] == "supported"}
        result["held"] = len(decisions) - len(accepted)
        if not accepted:
            return None
        existing = {(r["subject"], r["predicate"], r["object"]) for r in snapshot["bundle"]["relations"] if r["status"] != "withdrawn"}
        normalized = normalize_overlap_candidate(job["candidate"]["analysis"], kinds)
        originals = {link["record_id"]: link for link in job["candidate"]["analysis"]["links"]}
        relations = []
        for link in normalized["links"]:
            identifier = link["record_id"]
            if identifier not in accepted:
                continue
            decision = accepted[identifier]
            if (identifier, link["predicate"], job["question"]["id"]) in existing:
                result["skipped"] = result.get("skipped", 0) + 1
                continue
            relations.append({"subject": identifier, "predicate": link["predicate"],
                              "object": job["question"]["id"], "rationale": link["rationale"],
                              "context": {"review_verdict": decision["verdict"], "review_reason": decision["reason"],
                                          **({"answer_scope": link["answer_scope"], "remaining": link["remaining"]}
                                             if "predicate" in originals[identifier] else {})},
                              "evidence": evidence(link["evidence"], job["packet"])})
        if not relations:
            return None
        return self.proposal(job, snapshot, question=None, relations=relations)

    def cycle(self):
        job = self.select()
        result = self.run(job)
        if job is not None and job["status"] in {"recorded", "held", "failed", "skipped"}:
            self.agenda.overlapped(job["question"]["id"])
        return result
