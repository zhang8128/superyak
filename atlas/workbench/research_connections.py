"""Compare two source-checked claims without treating the graph as source text."""

from itertools import combinations
import json

from .automation import MAX_DRAFTS, _directory, _now, _read, _save
from .research_context import _terms
from .research_evidence import eligible_inputs, make_packet, question_links
from .research_review import (REVIEW_REVISION, SourceReviewError, _digest,
                              assert_same_draft, assert_original_relations,
                              review_input_digest, validate_review)
from .research_runner import ERRORS
from .research_model import AnalysisValidationError


CONNECTION_REVISION = "two-source-comparison-v2"
PAIR_INPUT_LIMIT = 12
CONNECTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "relevant": {"type": "boolean"},
        **{key: {"type": "string"} for key in ("title", "summary", "scope", "limitations", "rationale")},
        "links": {"type": "array", "maxItems": 2, "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"target": {"type": "string"}, "predicate": {"enum": ["supports", "challenges"]},
                           "rationale": {"type": "string"}}, "required": ["target", "predicate", "rationale"]}},
        "evidence": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"passage_id": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["passage_id", "quote"]}},
    },
    "required": ["relevant", "title", "summary", "scope", "limitations", "rationale", "links", "evidence"],
}


def validate_connection(candidate, packet):
    if not isinstance(candidate, dict) or set(candidate) != set(CONNECTION_SCHEMA["required"]):
        raise ValueError("Invalid connection fields")
    if type(candidate["relevant"]) is not bool:
        raise ValueError("Connection relevance must be boolean")
    if not candidate["relevant"]:
        return False
    for key in ("title", "summary", "scope", "limitations", "rationale"):
        if not isinstance(candidate[key], str) or not 1 <= len(candidate[key].strip()) <= 2000:
            raise ValueError(f"Connection requires bounded {key}")
    targets = {r["id"] for r in packet["records"]}
    links = candidate["links"]
    if not isinstance(links, list) or len(links) != 2:
        raise ValueError("A connection must assess both supplied claims")
    seen = set()
    for link in links:
        if (not isinstance(link, dict) or set(link) != {"target", "predicate", "rationale"}
                or not isinstance(link["target"], str) or link["target"] not in targets
                or not isinstance(link["predicate"], str) or link["predicate"] not in {"supports", "challenges"}
                or not isinstance(link["rationale"], str) or not 1 <= len(link["rationale"].strip()) <= 1500):
            raise ValueError("Connection must justify links to supplied claims only")
        seen.add(link["target"])
    if seen != targets:
        raise ValueError("Connection must link both distinct claims")
    evidence = candidate["evidence"]
    if not isinstance(evidence, list) or not 2 <= len(evidence) <= 4:
        raise ValueError("Connection requires evidence from two distinct sources")
    passages = {p["id"]: p for p in packet["document"]["passages"]}
    cited = set()
    for entry in evidence:
        if not isinstance(entry, dict) or set(entry) != {"passage_id", "quote"}:
            raise ValueError("Invalid connection evidence")
        identifier, quote = entry["passage_id"], entry["quote"]
        if (not isinstance(identifier, str) or identifier not in passages or not isinstance(quote, str)
                or quote not in passages[identifier]["text"] or not 4 <= len(quote.split()) <= 25):
            raise ValueError("Connection quotation must exactly match 4–25 supplied source words")
        cited.add(passages[identifier]["source_id"])
    if len(cited) != 2:
        raise ValueError("Connection requires evidence from two distinct sources")
    return True


def validate_connection_review(result, packet):
    decision = validate_review(result, packet["document"])
    if decision["verdict"] == "supported":
        passages = {p["id"]: p["source_id"] for p in packet["document"]["passages"]}
        if len({passages[e["passage_id"]] for e in decision["evidence"]}) != 2:
            raise ValueError("A supported comparison requires reviewer evidence from both sources")
    return decision


def connection_digest(model, question, packet, candidate):
    return review_input_digest(model, question, packet, {"revision": CONNECTION_REVISION, "candidate": candidate})


def assess_connection(model, question, packet, candidate, previous=None):
    identifier = connection_digest(model.model, question, packet, candidate)
    if previous and previous.get("input_digest") == identifier and previous.get("revision") == REVIEW_REVISION:
        validate_connection_review(previous["result"], packet)
        return previous
    result = model.review_connection(question, packet, candidate)
    validate_connection_review(result, packet)
    return {"version": 1, "revision": REVIEW_REVISION, "input_digest": identifier,
            "reviewer": model.model, "result": result, "checked_at": _now(),
            "assessment": "Automated comparison review; not independent scientific review."}


def prepare_connection(job, snapshot):
    candidate, packet, question = job["candidate"]["analysis"], job["packet"], job["question"]
    passages = {p["id"]: p for p in packet["document"]["passages"]}
    return {"idempotency_key": "connection-job:" + job["id"], "kind": "claim",
            "title": candidate["title"], "summary": candidate["summary"], "facets": question["facets"],
            "views": sorted(name for name, ids in snapshot["views"].items() if question["id"] in ids),
            "context": {"worker_role": "connect", "scope": candidate["scope"], "limitations": candidate["limitations"],
                        "derived_from": json.dumps([r["id"] for r in packet["records"]]),
                        "model": job["candidate"]["model"], "worker_revision": job["revision"],
                        "source_support": "supported", "source_review_model": job["source_review"]["result"]["model"],
                        "source_review_reason": job["source_review"]["result"]["analysis"]["reason"],
                        "assessment": "Automated comparison of source excerpts; proposed, not independent scientific review."},
            "evidence": [{"source_id": passages[e["passage_id"]]["source_id"],
                          "locator": passages[e["passage_id"]]["locator"],
                          "note": f"Retrieved passage: “{e['quote']}”. {candidate['rationale']}"}
                         for e in candidate["evidence"]],
            "links": candidate["links"] + [{"predicate": "informs", "target": question["id"],
                                            "rationale": candidate["rationale"]}]}


def bound_connection(snapshot, job, record):
    expected = prepare_connection(job, snapshot)
    expected.update(views=job["draft"]["views"], facets=job["draft"]["facets"])
    assert_same_draft(job["draft"], expected)
    actual = job["draft"] | {key: record[key] for key in ("kind", "title", "summary", "context", "facets", "evidence")}
    assert_same_draft(actual, expected)
    assert_original_relations(snapshot, record["id"], job["draft"])
    sources = {s["id"]: s for s in snapshot["bundle"]["sources"]}
    records = {r["id"]: r for r in snapshot["bundle"]["items"]}
    for source in job["packet"]["sources"]:
        if {k: source[k] for k in ("id", "title", "url", "year", "citation")} != sources.get(source["id"]):
            raise ValueError("Saved comparison source attribution changed")
    for premise in job["packet"]["records"]:
        current = records[premise["id"]]
        if (any(current[k] != premise[k] for k in ("id", "title", "summary", "status"))
                or any(current["context"].get(k, "") != v for k, v in premise["context"].items())):
            raise ValueError("Comparison premise changed since the candidate was generated")
    validate_connection(job["candidate"]["analysis"], job["packet"])
    return records[job["question"]["id"]], job["packet"], job["candidate"]["analysis"]


class ConnectionWorker:
    def __init__(self, research):
        self.research = research
        self.root = research.root / "connections"
        _directory(self.root)

    def _questions(self, snapshot):
        try:
            return self.research._questions(snapshot)
        except ValueError as error:
            if str(error) != "no active questions in the configured research views":
                raise
            return []

    @staticmethod
    def _shortlist(items, question, limit, offset):
        wanted = _terms(question)
        ranked = sorted(items, key=lambda item: (
            -len(wanted & _terms({k: item["record"][k] for k in ("title", "summary", "context")})),
            item["record"]["id"]))
        if len(ranked) <= limit:
            return ranked
        # Retain nearest evidence while giving the remaining records a durable turn.
        rest = ranked[limit - 1:]
        return ranked[:limit - 1] + [rest[offset % len(rest)]]

    def _select(self, snapshot, eligible):
        from .research_graph_review import exclusions

        pending = sorted((_read(p) for p in self.root.glob("*.json")), key=lambda j: j["created_at"])
        for job in pending:
            if job["status"] in {"pending", "retry"}:
                return job
        done = {job["id"] for job in pending}
        excluded = exclusions(self.research.project, snapshot)
        questions = [q for q in self._questions(snapshot) if q["id"] not in excluded]
        if not questions:
            return None
        eligible = {identifier: item for identifier, item in eligible.items() if identifier not in excluded}
        cursor_path = self.research.root / "connection-selection.json"
        cursor = _read(cursor_path) if cursor_path.exists() else {"version": 1, "next_offset": len(pending)}
        if cursor.get("version") != 1 or type(cursor.get("next_offset")) is not int or cursor["next_offset"] < 0:
            raise ValueError("Invalid connection selection cursor")
        offset = cursor["next_offset"]
        _save(cursor_path, cursor | {"next_offset": offset + 1}, replace=cursor_path.exists())
        start, sample = offset % len(questions), offset // len(questions)
        memberships = {identifier: question_links(snapshot, identifier, excluded_relations=excluded) - excluded
                       for identifier in eligible}
        for question in questions[start:] + questions[:start]:
            local = [item for identifier, item in eligible.items() if question["id"] in memberships[identifier]]
            if not local:
                continue
            distant = [item for identifier, item in eligible.items()
                       if memberships[identifier] and question["id"] not in memberships[identifier]]
            candidates = self._shortlist(local, question, PAIR_INPUT_LIMIT // 2 if distant else PAIR_INPUT_LIMIT, sample)
            candidates += self._shortlist(distant, question, PAIR_INPUT_LIMIT - len(candidates), sample)
            pairs = []
            for first, second in combinations(sorted(candidates, key=lambda item: item["record"]["id"]), 2):
                if first["source"]["id"] == second["source"]["id"]:
                    continue
                local_count = sum(question["id"] in memberships[item["record"]["id"]] for item in (first, second))
                if not local_count:
                    continue
                words = [_terms({k: item["record"][k] for k in ("title", "summary")}) for item in (first, second)]
                score = len(words[0] & words[1]) / max(1, len(words[0] | words[1]))
                packet = make_packet([first, second])
                identifier = _digest({"question": question, "packet": packet, "model": self.research.model.model,
                                      "revision": CONNECTION_REVISION})
                if identifier not in done:
                    pairs.append(((local_count == 1) != bool(sample % 2), -score, identifier, packet))
            if pairs:
                _, _, identifier, packet = min(pairs, key=lambda row: row[:3])
                return {"id": identifier, "version": 1, "revision": CONNECTION_REVISION,
                        "question": question, "packet": packet, "status": "pending", "attempts": 0,
                        "created_at": _now(), "model": self.research.model.model}
        return None

    def _still_current(self, job):
        from .research_graph_review import exclusions

        snapshot = self.research.inbox.snapshot()
        excluded = exclusions(self.research.project, snapshot)
        if job["question"]["id"] in excluded:
            return False
        questions = {q["id"]: q for q in self._questions(snapshot)}
        eligible = eligible_inputs(self.research, snapshot)
        ids = [r["id"] for r in job["packet"]["records"]]
        return (questions.get(job["question"]["id"]) == job["question"]
                and all(r in eligible and r not in excluded for r in ids)
                and any(job["question"]["id"] in question_links(snapshot, identifier, excluded_relations=excluded)
                        for identifier in ids)
                and make_packet([eligible[r] for r in ids]) == job["packet"])

    def _draft(self, job):
        return prepare_connection(job, self.research.inbox.snapshot())

    def cycle(self):
        result = {"saved": 0, "replayed": 0, "held": 0, "skipped": 0, "errors": [], "record_ids": []}
        if self.research.should_stop():
            return result
        snapshot = self.research.inbox.snapshot()
        job = self._select(snapshot, eligible_inputs(self.research, snapshot))
        if job is None:
            return result | {"skipped": 1, "reason": "No unprocessed pair of distinct, source-checked claims is available"}
        path = self.root / (job["id"] + ".json")
        _save(path, job, replace=path.exists())
        capturing = False
        try:
            inbox, model = self.research.inbox, self.research.model
            captured = "draft" in job and (inbox.state / "drafts" /
                       (inbox._identifier(self.research.session_id, job["draft"]["idempotency_key"]) + ".json")).exists()
            if not captured:
                if not self._still_current(job):
                    job.update(status="held", reason="Input claims changed or lost source-support eligibility")
                    result["held"] = 1
                    return result
                if sum(r["provenance"].get("capture") == "session_draft" for r in snapshot["bundle"]["items"]) >= MAX_DRAFTS:
                    raise RuntimeError("Research inbox is at capacity")
                self.research.progress(phase="connecting", question=job["question"]["title"])
                if "candidate" not in job:
                    job["candidate"] = model.connect(job["question"], job["packet"])
                    _save(path, job, replace=True)
                if not validate_connection(job["candidate"]["analysis"], job["packet"]):
                    job.update(status="skipped", reason="Model found no justified connection")
                    result["skipped"] = 1
                    return result
                if self.research.should_stop():
                    return result
                self.research.progress(phase="reviewing_connection", question=job["question"]["title"])
                job["source_review"] = assess_connection(model, job["question"], job["packet"],
                                                         job["candidate"]["analysis"], job.get("source_review"))
                _save(path, job, replace=True)
                verdict = job["source_review"]["result"]["analysis"]["verdict"]
                if verdict != "supported" or not self._still_current(job):
                    job.update(status="held", reason="Comparison or its inputs did not retain source support")
                    result["held"] = 1
                    return result
                if "draft" not in job:
                    job["draft"] = self._draft(job)
                    _save(path, job, replace=True)
                else:
                    assert_same_draft(job["draft"], self._draft(job))
            if self.research.should_stop():
                return result
            self.research.progress(phase="recording", paper=job["draft"]["title"])
            capturing = True
            receipt = inbox.record(job["draft"], self.research.session_id)
            job.update(status="recorded", receipt=receipt, completed_at=_now())
            result["replayed" if receipt["duplicate"] else "saved"] = 1
            result["record_ids"] = [receipt["record_id"]]
            result["publication_status"] = receipt["publication_status"]
            if receipt["publication_status"] != "current":
                result["errors"].append({"error": receipt["error"], "recorded": True})
            if not self.research.should_stop():
                self.research._publish_browser()
        except ERRORS as error:
            job["attempts"] += 1
            invalid = isinstance(error, ValueError) and not capturing
            job.update(status="failed" if invalid else "retry", last_error=str(error))
            if isinstance(error, SourceReviewError):
                job["rejected_review"] = error.result
            if isinstance(error, AnalysisValidationError):
                job["rejected_candidate"] = error.result
            result["errors"].append({"job": job["id"], "error": str(error),
                                     "kind": "invalid_connection" if invalid else "operational"})
        finally:
            _save(path, job, replace=True)
        return result
