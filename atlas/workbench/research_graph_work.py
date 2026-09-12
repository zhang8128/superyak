"""Shared evidence selection and durable execution for the two graph workers."""

import json

from .automation import _directory, _now, _read, _save
from .research_context import _terms
from .research_evidence import eligible_inputs, make_packet
from .research_graph import graph_digest
from .research_graph_model import REVISION
from .research_graph_review import exclusions, GraphReviewLedger


def scoped_questions(research, snapshot):
    membership = {identifier for ids in snapshot["views"].values() for identifier in ids}
    excluded = exclusions(research.project, snapshot)
    return sorted((r for r in snapshot["bundle"]["items"] if r["kind"] == "question"
                   and r["status"] != "withdrawn" and r["id"] in membership and r["id"] not in excluded
                   and (not research.question_ids or r["id"] in research.question_ids)), key=lambda r: r["id"])


def agenda_status(research, snapshot):
    from .research_agenda import QuestionAgenda
    agenda = QuestionAgenda(research.project)
    try:
        agenda.eligible(snapshot, research.question_ids, excluded_ids=exclusions(research.project, snapshot))
    except ValueError as error:
        if str(error) not in {"no active questions in the configured research views",
                              "requested question must be active and selected in a configured view"}:
            raise
    return agenda.status(snapshot)


def graph_inputs(research, snapshot):
    primary = eligible_inputs(research, snapshot)
    rejected = exclusions(research.project, snapshot)
    result = {key: value for key, value in primary.items() if key not in rejected}
    # Methods/experiments need original cached passages too. Their relevance is
    # assessed afresh; a graph description alone never serves as source text.
    for record in snapshot["bundle"]["items"]:
        if record["kind"] not in {"approach", "experiment"} or record["status"] == "withdrawn" or record["id"] in rejected:
            continue
        for source in primary.values():
            evidence = [e for e in record["evidence"] if e["source_id"] == source["source"]["id"]]
            if not evidence:
                continue
            anchors = [p["id"] for p in source["document"]["passages"] if any(
                e["locator"].casefold() in p["locator"].casefold() or p["locator"].casefold() in e["locator"].casefold()
                for e in evidence)]
            if anchors:
                result[record["id"]] = source | {"record": record, "anchors": anchors}
                break
    return result


def bounded_packet(inputs, *, maximum=3):
    selected = []
    for item in inputs:
        trial = make_packet([*selected, item])
        if len(json.dumps(trial, ensure_ascii=False).encode()) <= 11000:
            selected.append(item)
        if len(selected) == maximum:
            break
    return make_packet(selected) if selected else None


def evidence(entries, packet):
    passages = {p["id"]: p for p in packet["document"]["passages"]}
    return [{"source_id": passages[e["passage_id"]]["source_id"],
             "locator": passages[e["passage_id"]]["locator"],
             "note": f"Retrieved passage: “{e['quote']}”."} for e in entries]


def question_catalog(snapshot):
    return graph_digest([r for r in snapshot["bundle"]["items"] if r["kind"] == "question"])


def nearby_questions(research, snapshot, query, *, maximum=12):
    agenda = agenda_status(research, snapshot)
    wanted = _terms(query)
    questions = scoped_questions(research, snapshot)
    # Include queued records in duplicate comparisons, even while they await research.
    all_questions = [r for r in snapshot["bundle"]["items"] if r["kind"] == "question" and r["status"] != "withdrawn"]
    ranked = sorted(all_questions, key=lambda r: (-len(wanted & _terms({k:r[k] for k in ("title", "summary")})), r["id"]))
    parents = {q["id"] for q in questions if agenda[q["id"]]["can_generate_children"]}
    return [{"id": r["id"], "title": r["title"], "summary": r["summary"],
             "scope": r["context"].get("scope", ""), "eligible_parent": r["id"] in parents}
            for r in ranked[:maximum]]


class GraphWork:
    def __init__(self, research, role):
        self.research, self.role = research, role
        self.root = research.root / "graph-jobs"
        _directory(self.root)

    def jobs(self):
        return [_read(path) for path in sorted(self.root.glob("*.json"))]

    def pending(self):
        jobs = [job for job in self.jobs() if job["role"] == self.role and job["status"] in {"pending", "retry"}]
        return min(jobs, key=lambda j: j["created_at"]) if jobs else None

    def new_job(self, question, packet, **extra):
        identity = {"role": self.role, "revision": REVISION, "model": self.research.model.model,
                    "question": question, "packet": packet, **extra}
        return identity | {"id": graph_digest(identity), "version": 1, "status": "pending",
                           "attempts": 0, "created_at": _now()}

    def save(self, job):
        _save(self.root / (job["id"] + ".json"), job, replace=True)

    def guard(self, job, snapshot):
        inputs = graph_inputs(self.research, snapshot)
        ids = [r["id"] for r in job["packet"]["records"]]
        questions = {q["id"]: q for q in scoped_questions(self.research, snapshot)}
        if (questions.get(job["question"]["id"]) != job["question"] or any(i not in inputs for i in ids)
                or make_packet([inputs[i] for i in ids]) != job["packet"]):
            raise ValueError("Graph inputs changed or lost source-support eligibility")
        if "record_kinds" in job and job["record_kinds"] != {i: inputs[i]["record"]["kind"] for i in ids}:
            raise ValueError("Graph record kinds changed since proposal selection")
        if self.role == "question" and question_catalog(snapshot) != job["question_catalog"]:
            raise ValueError("Questions changed since duplicate review; reassess the candidate")
        if self.role == "question" and "candidate" in job:
            agenda = agenda_status(self.research, snapshot)
            parents = job["candidate"]["analysis"].get("parents", [])
            if any(p not in questions or not agenda[p]["can_generate_children"] for p in parents):
                raise ValueError("Question parent lost current eligibility for generation")

    def proposal(self, job, snapshot, *, question, relations):
        context = {"worker_role": self.role, "worker_revision": job["revision"], "model": job["candidate"]["model"],
                   "graph_job_id": job["id"], "review_digest": graph_digest(job["review"]),
                   "candidate_digest": graph_digest(job["candidate"]), "packet_digest": graph_digest(job["packet"]),
                   "anchor_digest": graph_digest(job["question"]), "questions_digest": graph_digest(job.get("questions", [])),
                   "views_digest": graph_digest(job.get("views", []))}
        if "record_kinds" in job:
            context["record_kinds_digest"] = graph_digest(job["record_kinds"])
        referenced = {r[endpoint] for r in relations for endpoint in ("subject", "object")} - {"$question"}
        referenced.update(r["id"] for r in job["packet"]["records"])
        referenced.add(job["question"]["id"])
        referenced.update(e["source_id"] for r in relations for e in r["evidence"])
        originals = {r["id"]: r for kind in ("items", "sources") for r in snapshot["bundle"][kind]}
        return {"idempotency_key": "graph-job:" + job["id"], "question": question, "relations": relations,
                "expected": {key: graph_digest(originals[key]) for key in sorted(referenced)}, "context": context}

    def submit(self, job, result):
        research = self.research
        research.progress(phase="recording_graph", question=job["question"]["title"])
        receipt = research.inbox.record_graph(job["proposal"], research.session_id,
                                              guard=lambda snapshot: self.guard(job, snapshot))
        job.update(receipt=receipt, status="recorded" if receipt["publication_status"] == "current" else "retry", completed_at=_now())
        self.save(job)
        result["record_ids"] = receipt["record_ids"]
        result["relation_ids"] = receipt["relation_ids"]
        result["replayed"] = int(receipt["duplicate"])
        result["saved"] = 0 if receipt["duplicate"] else len(receipt["record_ids"])
        result["links_added"] = 0 if receipt["duplicate"] else len(receipt["relation_ids"])
        result["publication_status"] = receipt["publication_status"]
        if receipt["publication_status"] != "current":
            result["errors"].append({"recorded": True, "error": receipt.get("error", "Publication pending")})
        snapshot = research.inbox.snapshot()
        ledger = GraphReviewLedger(research.project)
        current = ledger.current(snapshot)
        ids = set(receipt["record_ids"] + receipt["relation_ids"])
        for record in [*snapshot["bundle"]["items"], *snapshot["bundle"]["relations"]]:
            if record["id"] in ids and record["id"] not in current:
                ledger.store(record, job["review"], model=research.model.model, stage="initial",
                             verdict="supported", reason=record.get("context", {}).get("review_reason")
                             or job["review"].get("analysis", {}).get("reason")
                             or "Fresh source-grounded proposal review accepted this addition.")

    def run(self, job):
        result = {"saved": 0, "replayed": 0, "links_added": 0, "reviewed": 0, "held": 0, "skipped": 0,
                  "record_ids": [], "relation_ids": [], "errors": []}
        if job is None or self.research.should_stop():
            return result | {"skipped": 1, "reason": "No new eligible evidence packet"}
        self.save(job)
        try:
            if "proposal" not in job:
                self.guard(job, self.research.inbox.snapshot())
                if "candidate" not in job:
                    self.research.progress(phase="proposing_" + self.role, question=job["question"]["title"])
                    job["candidate"] = self.generate(job)
                    self.save(job)
                if not self.valid(job):
                    job.update(status="skipped", reason="No distinct useful proposal")
                    return result | {"skipped": 1}
                if self.research.should_stop():
                    return result
                if "review" not in job:
                    self.research.progress(phase="reviewing_" + self.role, question=job["question"]["title"])
                    job["review"] = self.review(job)
                    self.save(job)
                result["reviewed"] = 1
                proposal = self.prepare(job, result)
                if proposal is None:
                    job["status"] = "skipped" if result["skipped"] else "held"
                    return result
                self.guard(job, self.research.inbox.snapshot())
                job["proposal"] = proposal
                self.save(job)
            if not self.research.should_stop():
                self.submit(job, result)
        except (ValueError, RuntimeError, OSError, TypeError, KeyError) as error:
            job["attempts"] += 1
            invalid = isinstance(error, ValueError)
            terminal = invalid and any(text in str(error) for text in
                ("changed", "eligibility", "Duplicate graph relation", "Stale graph input:"))
            job.update(status="held" if terminal else "failed" if invalid and "proposal" not in job and job["attempts"] >= 3 else "retry", last_error=str(error))
            result["held"] += int(terminal)
            if hasattr(self.research.model, "last_response"):
                job["last_response"] = self.research.model.last_response
            result["errors"].append({"job": job["id"], "error": str(error),
                                     **({"kind": "invalid_graph"} if invalid else {})})
        finally:
            self.save(job)
        return result
