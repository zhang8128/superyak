"""Reusable, source-checked primary evidence and current question membership."""

from .automation import _read
from .research_review import ReviewLedger, bound_candidate, review_input_digest, validate_review
from .validation import CLAIM_QUESTION_PREDICATES


def eligible_inputs(research, snapshot):
    """Keep original source bindings; the search question is provenance, not ownership."""
    records = {r["id"]: r for r in snapshot["bundle"]["items"]}
    ledger = ReviewLedger(research.project)
    current, excluded = ledger.current(snapshot), ledger.excluded(snapshot)
    result = {}
    for path in sorted((research.root / "jobs").glob("*.json")):
        job = _read(path)
        identifier = job.get("receipt", {}).get("record_id")
        record = records.get(identifier)
        if (job.get("status") != "recorded" or record is None or record["status"] == "withdrawn"
                or identifier in excluded):
            continue
        entry = current.get(identifier)
        review = entry["review"] if entry else job.get("source_review")
        if not review or review["result"]["analysis"]["verdict"] != "supported":
            continue
        try:
            question, document, candidate = bound_candidate(snapshot, job, record)
            reviewers = [entry["reviewer"]] if entry else [review.get("reviewer"), research.model.model,
                                                           review["result"]["model"]]
            if not any(review["input_digest"] == review_input_digest(name, question, document, candidate)
                       for name in reviewers if isinstance(name, str)):
                continue
            validate_review(review["result"], document)
            anchors = {candidate["passage_id"], *(e["passage_id"] for e in review["result"]["analysis"]["evidence"])}
            result[identifier] = {"record": record, "document": document, "anchors": sorted(anchors),
                                  "question_id": question["id"], "source": job["draft"]["sources"][0]}
        except (ValueError, KeyError, TypeError):
            # Audit diagnoses malformed history; it cannot become new source evidence.
            continue
    return result


def make_packet(inputs):
    """Attribute one or more records to complete required excerpts, without truncation."""
    inputs = list(inputs)
    if not inputs:
        raise ValueError("An evidence packet requires at least one input")
    records, passages, sources = [], [], []
    for index, item in enumerate(inputs):
        record, document, source = item["record"], item["document"], item["source"]
        anchors = set(item["anchors"])
        available = {p["id"] for p in document["passages"]}
        if not anchors or anchors - available:
            raise ValueError("An evidence packet is missing a required original source passage")
        records.append({key: record[key] for key in ("id", "title", "summary", "status")} | {
            "context": {key: record["context"].get(key, "") for key in ("scope", "limitations")}})
        ids = []
        for passage in document["passages"]:
            if passage["id"] in anchors:
                identifier = f"s{index + 1}:{passage['id']}"
                ids.append(identifier)
                passages.append(passage | {"id": identifier, "source_id": source["id"]})
        sources.append(source | {"passage_ids": ids, "record_id": record["id"], "coverage": document["coverage"]})
    title = "Comparison of two attributed source excerpts" if len(inputs) == 2 else "Attributed source excerpts"
    return {"records": records, "sources": sources,
            "document": {"source": {"title": title}, "coverage": "cached_source_excerpts", "passages": passages}}


def question_links(snapshot, record_id, *, excluded_relations=()):
    """Return current question neighbors; independent edge assessments may exclude IDs."""
    questions = {r["id"] for r in snapshot["bundle"]["items"]
                 if r["kind"] == "question" and r["status"] != "withdrawn"}
    excluded = set(excluded_relations)
    return {r["object"] for r in snapshot["bundle"]["relations"]
            if r["subject"] == record_id and r["predicate"] in CLAIM_QUESTION_PREDICATES
            and r["status"] != "withdrawn" and r["object"] in questions and r["id"] not in excluded}
