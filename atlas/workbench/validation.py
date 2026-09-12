"""Portable bundle validation and normalization."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlparse


SCHEMA_VERSION = 1
STATUSES = frozenset({"proposed", "source_reported", "reviewed", "withdrawn"})
ITEM_KINDS = frozenset({"question", "approach", "claim", "experiment"})
EXPLICIT_QUESTION_PREDICATES = frozenset({"answers", "partially_answers", "raises_question"})
CLAIM_QUESTION_PREDICATES = frozenset({"informs"}) | EXPLICIT_QUESTION_PREDICATES
PREDICATES = frozenset({
    "addresses", "supports", "challenges", "informs", "tests", "uses_method",
    "part_of", "requires", "enables",
}) | EXPLICIT_QUESTION_PREDICATES
BUNDLE_FIELDS = frozenset({"schema_version", "title", "sources", "items", "relations", "history"})
SOURCE_FIELDS = frozenset({"id", "title", "url", "year", "citation"})
ITEM_FIELDS = frozenset({
    "id", "kind", "title", "summary", "status", "context", "facets", "evidence",
    "provenance", "reviewed_by", "reviewed_at",
})
RELATION_FIELDS = frozenset({
    "id", "subject", "predicate", "object", "status", "rationale", "context",
    "evidence", "reviewed_by", "reviewed_at",
})
EVIDENCE_FIELDS = frozenset({"source_id", "locator", "note"})


class WorkbenchError(Exception):
    """A user-correctable workbench data or state error."""


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise WorkbenchError(f"{label} must be an object")
    return value


def _only_fields(record: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(record) - allowed)
    if unknown:
        raise WorkbenchError(f"{label} has unknown field(s): {', '.join(unknown)}")


def _require_fields(record: Mapping[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required - set(record))
    if missing:
        raise WorkbenchError(f"{label} is missing field(s): {', '.join(missing)}")


def _string(value: Any, label: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str):
        raise WorkbenchError(f"{label} must be a string")
    if nonempty and not value.strip():
        raise WorkbenchError(f"{label} must not be blank")
    return value


def _string_map(value: Any, label: str) -> dict[str, str]:
    mapping = _mapping(value, label)
    result = {}
    for key, item in mapping.items():
        result[_string(key, f"{label} key", nonempty=True)] = _string(item, f"{label}.{key}")
    return result


def _facets(value: Any, label: str) -> dict[str, list[str]]:
    mapping = _mapping(value, label)
    result = {}
    for axis, values in mapping.items():
        axis = _string(axis, f"{label} key", nonempty=True)
        if not isinstance(values, list):
            raise WorkbenchError(f"{label}.{axis} must be a list of strings")
        result[axis] = [
            _string(entry, f"{label}.{axis} entry", nonempty=True) for entry in values
        ]
    return result


def _evidence(value: Any, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise WorkbenchError(f"{label} must be a list")
    result = []
    for index, raw_entry in enumerate(value):
        entry_label = f"{label}[{index}]"
        entry = _mapping(raw_entry, entry_label)
        _only_fields(entry, EVIDENCE_FIELDS, entry_label)
        _require_fields(entry, set(EVIDENCE_FIELDS), entry_label)
        result.append({
            "source_id": _string(entry["source_id"], f"{entry_label}.source_id", nonempty=True),
            "locator": _string(entry["locator"], f"{entry_label}.locator", nonempty=True),
            "note": _string(entry["note"], f"{entry_label}.note"),
        })
    return result


def _validate_timestamp(value: str, label: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkbenchError(f"{label} must be an ISO 8601 timestamp") from exc


def normalize_source(raw: Any, label: str = "source") -> dict[str, Any]:
    source = _mapping(raw, label)
    _only_fields(source, SOURCE_FIELDS, label)
    _require_fields(source, set(SOURCE_FIELDS), label)
    year = source["year"]
    if isinstance(year, bool) or not isinstance(year, int):
        raise WorkbenchError(f"{label}.year must be an integer")
    url = _string(source["url"], f"{label}.url", nonempty=True)
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise WorkbenchError(f"{label}.url is malformed: {exc}") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WorkbenchError(f"{label}.url must use http or https")
    return {
        "id": _string(source["id"], f"{label}.id", nonempty=True),
        "title": _string(source["title"], f"{label}.title", nonempty=True),
        "url": url,
        "year": year,
        "citation": _string(source["citation"], f"{label}.citation"),
    }


def normalize_item(raw: Any, label: str = "item") -> dict[str, Any]:
    item = _mapping(raw, label)
    _only_fields(item, ITEM_FIELDS, label)
    _require_fields(item, {"id", "kind", "title", "summary"}, label)
    kind = _string(item["kind"], f"{label}.kind", nonempty=True)
    if kind not in ITEM_KINDS:
        raise WorkbenchError(f"{label}.kind is not allowed: {kind}")
    status = _string(item.get("status", "proposed"), f"{label}.status", nonempty=True)
    if status not in STATUSES:
        raise WorkbenchError(f"{label}.status is not allowed: {status}")
    normalized = {
        "id": _string(item["id"], f"{label}.id", nonempty=True),
        "kind": kind,
        "title": _string(item["title"], f"{label}.title", nonempty=True),
        "summary": _string(item["summary"], f"{label}.summary"),
        "status": status,
        "context": _string_map(item.get("context", {}), f"{label}.context"),
        "facets": _facets(item.get("facets", {}), f"{label}.facets"),
        "evidence": _evidence(item.get("evidence", []), f"{label}.evidence"),
        "provenance": _string_map(item.get("provenance", {}), f"{label}.provenance"),
        "reviewed_by": _string(item.get("reviewed_by", ""), f"{label}.reviewed_by"),
        "reviewed_at": _string(item.get("reviewed_at", ""), f"{label}.reviewed_at"),
    }
    _validate_status_invariants(normalized, label, relation=False)
    return normalized


def normalize_relation(raw: Any, label: str = "relation") -> dict[str, Any]:
    relation = _mapping(raw, label)
    _only_fields(relation, RELATION_FIELDS, label)
    _require_fields(relation, {"id", "subject", "predicate", "object"}, label)
    predicate = _string(relation["predicate"], f"{label}.predicate", nonempty=True)
    if predicate not in PREDICATES:
        raise WorkbenchError(f"{label}.predicate is not allowed: {predicate}")
    status = _string(relation.get("status", "proposed"), f"{label}.status", nonempty=True)
    if status not in STATUSES:
        raise WorkbenchError(f"{label}.status is not allowed: {status}")
    normalized = {
        "id": _string(relation["id"], f"{label}.id", nonempty=True),
        "subject": _string(relation["subject"], f"{label}.subject", nonempty=True),
        "predicate": predicate,
        "object": _string(relation["object"], f"{label}.object", nonempty=True),
        "status": status,
        "rationale": _string(relation.get("rationale", ""), f"{label}.rationale"),
        "context": _string_map(relation.get("context", {}), f"{label}.context"),
        "evidence": _evidence(relation.get("evidence", []), f"{label}.evidence"),
        "reviewed_by": _string(relation.get("reviewed_by", ""), f"{label}.reviewed_by"),
        "reviewed_at": _string(relation.get("reviewed_at", ""), f"{label}.reviewed_at"),
    }
    _validate_status_invariants(normalized, label, relation=True)
    return normalized


def _validate_status_invariants(record: Mapping[str, Any], label: str, *, relation: bool) -> None:
    if record["status"] == "reviewed":
        _string(record["reviewed_by"], f"{label}.reviewed_by", nonempty=True)
        reviewed_at = _string(record["reviewed_at"], f"{label}.reviewed_at", nonempty=True)
        _validate_timestamp(reviewed_at, f"{label}.reviewed_at")
    needs_evidence = relation and record["status"] == "reviewed"
    needs_evidence = needs_evidence or (
        not relation
        and record["kind"] == "claim"
        and record["status"] in {"source_reported", "reviewed"}
    )
    if needs_evidence and not record["evidence"]:
        raise WorkbenchError(f"{label} requires source evidence for status {record['status']}")
    if relation and record["status"] == "reviewed" and record["predicate"] in {"requires", "enables"}:
        if not record["rationale"].strip():
            raise WorkbenchError(f"{label}.rationale must not be blank for a reviewed dependency")
        if not record["context"] or not any(value.strip() for value in record["context"].values()):
            raise WorkbenchError(f"{label}.context must not be blank for a reviewed dependency")


def _unique(records: list[dict[str, Any]], label: str) -> None:
    seen = set()
    for record in records:
        if record["id"] in seen:
            raise WorkbenchError(f"duplicate {label} ID in bundle: {record['id']}")
        seen.add(record["id"])


def _validate_evidence_sources(records: list[dict[str, Any]], source_ids: set[str]) -> None:
    for record in records:
        for entry in record["evidence"]:
            if entry["source_id"] not in source_ids:
                raise WorkbenchError(
                    f"record {record['id']} evidence references unknown source: {entry['source_id']}"
                )


def validate_relation_endpoints(relation: Mapping[str, Any], item_kinds: Mapping[str, str]) -> None:
    subject = relation["subject"]
    object_id = relation["object"]
    if subject not in item_kinds:
        raise WorkbenchError(f"relation {relation['id']} has unknown subject: {subject}")
    if object_id not in item_kinds:
        raise WorkbenchError(f"relation {relation['id']} has unknown object: {object_id}")
    subject_kind = item_kinds[subject]
    object_kind = item_kinds[object_id]
    predicate = relation["predicate"]
    valid = {
        "addresses": subject_kind == "approach" and object_kind == "question",
        "supports": subject_kind == "claim" and object_kind in {"claim", "approach"},
        "challenges": subject_kind == "claim" and object_kind in {"claim", "approach"},
        **{predicate: subject_kind == "claim" and object_kind == "question"
           for predicate in CLAIM_QUESTION_PREDICATES},
        "tests": subject_kind == "experiment" and object_kind in {"claim", "approach", "question"},
        "uses_method": subject_kind in {"approach", "experiment"} and object_kind == "approach",
        "part_of": subject_kind == "question" and object_kind == "question",
        "requires": subject_kind != "claim" and object_kind != "claim",
        "enables": subject_kind != "claim" and object_kind != "claim",
    }[predicate]
    if not valid:
        raise WorkbenchError(
            f"relation {relation['id']} has invalid endpoint types for {predicate}: "
            f"{subject_kind}->{object_kind}"
        )
    if predicate in {"requires", "enables"} and subject == object_id:
        raise WorkbenchError(f"relation {relation['id']} is a self-dependency")


def normalize_bundle(
    raw: Any,
    *,
    existing_source_ids: set[str] | None = None,
    existing_item_kinds: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    data = _mapping(raw, "bundle")
    _only_fields(data, BUNDLE_FIELDS, "bundle")
    _require_fields(data, {"schema_version", "title", "sources", "items", "relations"}, "bundle")
    if data["schema_version"] != SCHEMA_VERSION or isinstance(data["schema_version"], bool):
        raise WorkbenchError(f"unsupported schema_version: {data['schema_version']!r}")
    if "history" in data and not isinstance(data["history"], list):
        raise WorkbenchError("bundle.history must be a list when supplied; import ignores its events")
    for collection in ("sources", "items", "relations"):
        if not isinstance(data[collection], list):
            raise WorkbenchError(f"bundle.{collection} must be a list")
    sources = [normalize_source(value, f"sources[{index}]") for index, value in enumerate(data["sources"])]
    items = [normalize_item(value, f"items[{index}]") for index, value in enumerate(data["items"])]
    relations = [normalize_relation(value, f"relations[{index}]") for index, value in enumerate(data["relations"])]
    _unique(sources, "source")
    _unique(items, "item")
    _unique(relations, "relation")
    overlap = {record["id"] for record in items} & {record["id"] for record in relations}
    if overlap:
        raise WorkbenchError(f"item and relation IDs must be globally unique: {sorted(overlap)[0]}")
    source_ids = set(existing_source_ids or ()) | {record["id"] for record in sources}
    item_kinds = dict(existing_item_kinds or {})
    item_kinds.update({record["id"]: record["kind"] for record in items})
    _validate_evidence_sources(items + relations, source_ids)
    for relation in relations:
        validate_relation_endpoints(relation, item_kinds)
    return {
        "schema_version": SCHEMA_VERSION,
        "title": _string(data["title"], "bundle.title"),
        "sources": sources,
        "items": items,
        "relations": relations,
    }


def validate_record_references(
    record: Mapping[str, Any], *, source_ids: set[str], item_kinds: Mapping[str, str]
) -> None:
    _validate_evidence_sources([dict(record)], source_ids)
    if "predicate" in record:
        validate_relation_endpoints(record, item_kinds)
