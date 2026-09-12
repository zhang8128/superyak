"""Source-support assessments, separate from scientific review status."""

import hashlib
import json
from pathlib import Path

from .automation import ResearchInbox, _directory, _now, _read, _save


REVIEW_REVISION = "source-support-v1"


class SourceReviewError(ValueError):
    """An invalid model review retained separately from a scientific verdict."""

    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string", "enum": ["supported", "unsupported", "uncertain"]},
        "reason": {"type": "string"},
        "evidence": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"passage_id": {"type": "string"}},
            "required": ["passage_id"],
        }},
    },
    "required": ["verdict", "reason", "evidence"],
}


def validate_review(result, document):
    assessment = result.get("analysis", {})
    if (not isinstance(assessment, dict) or set(assessment) != {"verdict", "reason", "evidence"}
            or not isinstance(assessment["verdict"], str)
            or assessment["verdict"] not in {"supported", "unsupported", "uncertain"}):
        raise ValueError("Invalid source review verdict or fields")
    if not isinstance(assessment["reason"], str) or not 1 <= len(assessment["reason"].strip()) <= 4000:
        raise ValueError("Source review requires a bounded reason")
    evidence = assessment["evidence"]
    if (not isinstance(evidence, list) or len(evidence) > 4
            or (assessment["verdict"] != "uncertain" and not evidence)):
        raise ValueError("Source review requires source evidence for a decisive verdict")
    manifest = result.get("context_manifest", {})
    if manifest.get("selected_record_ids") != []:
        raise ValueError("Source review must not contain prior graph records")
    selected = manifest.get("selected_passage_ids", [])
    passages = {p["id"]: p["text"] for p in document["passages"] if p["id"] in selected}
    if not passages:
        raise ValueError("Source review requires supplied source passages")
    for entry in evidence:
        if not isinstance(entry, dict) or set(entry) != {"passage_id"}:
            raise ValueError("Invalid source review evidence")
        identifier = entry["passage_id"]
        if not isinstance(identifier, str) or identifier not in passages:
            raise ValueError("Source review must cite a supplied passage")
    if not isinstance(result.get("model"), str) or not result["model"].strip():
        raise ValueError("Source review must identify the actual model")
    return assessment


def review_input_digest(model, question, document, candidate):
    # Hash actual content, not the document's declared hash or the job's identity.
    payload = {"revision": REVIEW_REVISION, "reviewer": model, "question": question,
               "document": document, "candidate": candidate}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def assess(model, question, document, candidate, previous=None):
    identifier = review_input_digest(model.model, question, document, candidate)
    if (isinstance(previous, dict) and previous.get("revision") == REVIEW_REVISION
            and previous.get("input_digest") == identifier):
        validate_review(previous["result"], document)
        return previous
    if not callable(getattr(model, "review", None)):
        raise RuntimeError("The configured model has no source-support reviewer")
    result = model.review(question, document, candidate)
    validate_review(result, document)
    return {"version": 1, "revision": REVIEW_REVISION, "input_digest": identifier,
            "reviewer": model.model,
            "checked_at": _now(), "result": result,
            "assessment": "Automated source-support assessment; not independent scientific review."}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def assert_same_draft(actual, expected):
    """Bind every submitted field except the separate automated-review annotations."""
    annotations = {"assessment", "source_support", "source_review_revision", "source_review_model",
                   "source_review_reason", "source_review_input_digest"}

    def material(draft):
        return draft | {"context": {k: v for k, v in draft["context"].items() if k not in annotations}}

    if material(actual) != material(expected):
        raise ValueError("Saved draft differs from the derived source-review candidate or evidence")


def assert_original_relations(snapshot, record_id, draft):
    """Verify the exact version-one draft edges; later edges have their own reviews."""
    from .validation import normalize_relation

    relations = {relation["id"]: relation for relation in snapshot["bundle"]["relations"]}
    for index, link in enumerate(draft["links"]):
        identifier = f"{record_id}:link:{index}"
        expected = normalize_relation({
            "id": identifier, "subject": record_id, "predicate": link["predicate"],
            "object": link["target"], "status": "proposed", "rationale": link["rationale"],
            "context": draft["context"], "evidence": draft["evidence"],
        })
        if relations.get(identifier) != expected:
            raise ValueError(f"Original relation changed or is missing: {identifier}")


class ReviewLedger:
    """Append-only automated assessments; original drafts and statuses stay intact."""

    def __init__(self, project):
        self.project = Path(project).resolve(strict=True)
        self.root = self.project / ".atlas/research/reviews"
        for path in (self.project / ".atlas", self.root.parent, self.root):
            if path.is_symlink():
                raise ValueError("Source review state cannot be a symlink")

    def current(self, snapshot, model=None):
        records = {r["id"]: r for r in snapshot["bundle"]["items"]}
        result = {}
        for path in sorted(self.root.glob("*.json")):
            entry = _read(path)
            record = records.get(entry["record_id"])
            if (record is not None and entry["record_digest"] == _digest(record)
                    and (model is None or (entry["reviewer"] == model
                                           and entry["review"]["revision"] == REVIEW_REVISION))):
                previous = result.get(record["id"])
                if previous is None or entry["review"]["checked_at"] > previous["review"]["checked_at"]:
                    result[record["id"]] = entry
        return result

    def store(self, record, model, review):
        entry = {"version": 1, "record_id": record["id"], "record_digest": _digest(record),
                 "reviewer": model, "review": review}
        # A fresh assessment of revisited inputs is a new immutable observation.
        identifier = _digest(entry)
        for path in (self.project / ".atlas", self.root.parent, self.root):
            _directory(path)
        path = self.root / (identifier + ".json")
        if path.exists():
            return _read(path)
        _save(path, entry)
        return entry

    def excluded(self, snapshot):
        # Changing the writer or prompt must not resurrect a rejected claim.
        excluded = {identifier for identifier, entry in self.current(snapshot).items()
                    if entry["review"]["result"]["analysis"]["verdict"] != "supported"}
        records = {r["id"]: r for r in snapshot["bundle"]["items"]}
        changed = True
        while changed:
            changed = False
            for record in records.values():
                if record["id"] in excluded or record.get("context", {}).get("worker_role") != "connect":
                    continue
                try:
                    parents = json.loads(record["context"].get("derived_from", "null"))
                    invalid = (not isinstance(parents, list) or len(parents) != 2
                               or any(not isinstance(p, str) or p not in records or p in excluded
                                      or records[p]["status"] == "withdrawn" for p in parents))
                except (ValueError, TypeError):
                    invalid = True
                if invalid:
                    excluded.add(record["id"])
                    changed = True
        return excluded


def bound_candidate(snapshot, job, record):
    """Recover an extraction only when its saved record, source and links still match."""
    from .research_runner import prepare_draft, validate_analysis
    records = {r["id"]: r for r in snapshot["bundle"]["items"]}
    identifier = record["id"]
    question = records[job["question_id"]]
    candidate, document = job["extraction"]["analysis"], job["document"]
    extracted = validate_analysis(job["extraction"], document)
    if extracted is None:
        raise ValueError("Saved job has no relevant source extraction")
    expected_draft = prepare_draft(job, question, snapshot, extracted)
    # Historical grouping belongs to the saved draft. A question can
    # acquire new facets/views without changing this claim's evidence.
    expected_draft.update(facets=job["draft"]["facets"], views=job["draft"]["views"])
    assert_same_draft(job["draft"], expected_draft)
    saved_draft = job["draft"] | {key: record[key] for key in
                                 ("kind", "title", "summary", "context", "facets", "evidence")}
    assert_same_draft(saved_draft, expected_draft)
    sources = {s["id"]: s for s in snapshot["bundle"]["sources"]}
    if any(sources.get(source["id"]) != source for source in expected_draft["sources"]):
        raise ValueError("Saved source attribution differs from the review candidate")
    assert_original_relations(snapshot, identifier, job["draft"])
    return question, document, candidate


def review_backlog(project, model, *, limit=10, record_ids=None, progress=None, should_stop=lambda: False,
                   skip_inputs=()):
    """Review saved bot claims against their cached sources without rewriting them."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Review limit must be between 1 and 1000")
    inbox = ResearchInbox(project)
    snapshot = inbox.snapshot()
    ledger = ReviewLedger(project)
    existing = ledger.current(snapshot, model.model)
    records = {r["id"]: r for r in snapshot["bundle"]["items"]}
    jobs = {}
    for directory in ("jobs", "connections"):
        for path in (inbox.project / ".atlas/research" / directory).glob("*.json"):
            job = _read(path)
            identifier = job.get("receipt", {}).get("record_id")
            if job.get("status") == "recorded" and identifier in records:
                jobs[identifier] = job
    selected = set(record_ids or jobs)
    if selected - jobs.keys():
        raise ValueError("Requested record lacks a recorded bot job with cached source passages")

    def priority(identifier):
        job = jobs[identifier]
        candidate = job.get("extraction", {}).get("analysis", {})
        prior_ids = job.get("extraction", {}).get("context_manifest", {}).get("selected_record_ids", [])
        copied = any(records.get(prior, {}).get("summary") == candidate.get("summary") for prior in prior_ids)
        return (not copied, job.get("created_at", ""), identifier)

    result = {"reviewed": 0, "cached": 0, "exhausted": 0, "verdicts": {}, "records": [], "errors": [],
              "ledger": str(ledger.root), "assessment": "Automated source support; original statuses unchanged."}
    attempted = 0
    for identifier in sorted(selected, key=priority):
        if should_stop() or attempted >= limit:
            break
        job, record = jobs[identifier], records[identifier]
        comparison_revision = None
        if "packet" in job:
            from .research_connections import CONNECTION_REVISION
            comparison_revision = CONNECTION_REVISION
        binding = _digest({"job": job, "record": record, "question": records.get(job.get("question_id",
                          job.get("question", {}).get("id"))), "model": model.model, "revision": REVIEW_REVISION,
                          "comparison_revision": comparison_revision})
        if binding in skip_inputs:
            result["exhausted"] += 1
            continue
        started = False
        try:
            comparison = "packet" in job
            if comparison:
                from .research_connections import bound_connection, connection_digest, assess_connection, validate_connection_review
                question, document, candidate = bound_connection(snapshot, job, record)
                digest_input, run_assessment, validate = connection_digest, assess_connection, validate_connection_review
            else:
                question, document, candidate = bound_candidate(snapshot, job, record)
                digest_input, run_assessment, validate = review_input_digest, assess, validate_review
            previous = existing.get(identifier, {}).get("review")
            expected = digest_input(model.model, question, document, candidate)
            if previous and previous["input_digest"] == expected:
                validate(previous["result"], document)
                result["cached"] += 1
                continue
            attempted += 1
            started = True
            if progress:
                progress(phase="reviewing_connection" if comparison else "reviewing", paper=record["title"])
            review = run_assessment(model, question, document, candidate)
            ledger.store(record, model.model, review)
            verdict = review["result"]["analysis"]["verdict"]
            result["reviewed"] += 1
            result["verdicts"][verdict] = result["verdicts"].get(verdict, 0) + 1
            result["records"].append({"record_id": identifier, "verdict": verdict,
                                      "reason": review["result"]["analysis"]["reason"]})
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
            if not started:
                attempted += 1
            result["errors"].append({"record_id": identifier, "error": str(error), "input_digest": binding,
                                     "kind": "invalid_review" if isinstance(error, SourceReviewError) else
                                     "invalid_input" if isinstance(error, (ValueError, KeyError, TypeError)) else "operational"})
    return result
