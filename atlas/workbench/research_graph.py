"""Bounded, immutable proposals for questions and additional question relations.

Expected input digests are checked only for a new submission. Stored entries
retain their original input bindings when later research changes those inputs.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import hashlib
import re

from .lighthouse_wire import canonical_json
from .validation import CLAIM_QUESTION_PREDICATES, normalize_item, normalize_relation, validate_record_references


MAX_GRAPH_DRAFT_BYTES = 64 * 1024
MAX_GRAPH_DRAFTS = 1000
MAX_GRAPH_RELATIONS = 8
MAX_OVERLAP_RELATIONS = 3
GRAPH_VERSION = 1
CAPTURE_FIELDS = frozenset({"capture", "graph_draft_id", "session_id", "recorded_at",
                            "idempotency_key", "input_digests", "source_digests"})


def graph_digest(value):
    """Bind JSON, including finite local model timings; preserve wire record hashes."""
    active = set()
    def encode(item):
        if type(item) is float:
            return json.dumps(item, allow_nan=False)
        if type(item) not in (dict, list):
            return canonical_json(item)
        if id(item) in active:
            raise ValueError("Circular graph JSON")
        active.add(id(item))
        try:
            if type(item) is list:
                return "[" + ",".join(encode(v) for v in item) + "]"
            if any(type(key) is not str for key in item):
                raise ValueError("Graph JSON keys must be strings")
            keys = sorted(item, key=lambda key: key.encode("utf-16-be", "surrogatepass"))
            return "{" + ",".join(canonical_json(k) + ":" + encode(item[k]) for k in keys) + "}"
        finally:
            active.remove(id(item))
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def graph_identifier(session_id, key):
    return "graph-" + graph_digest({"session_id": session_id, "key": key})


def _text(value, label, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be nonblank text of at most {maximum} characters")
    return value


def _context(value):
    if not isinstance(value, dict) or any(not isinstance(k, str) or not k.strip()
                                          or not isinstance(v, str) for k, v in value.items()):
        raise ValueError("Graph context must be a string map")
    if CAPTURE_FIELDS & value.keys():
        raise ValueError("Graph capture attribution is recorder-owned")
    return deepcopy(value)


def normalize_proposal(raw, view_names):
    required = {"idempotency_key", "question", "relations", "expected"}
    if not isinstance(raw, dict) or required - raw.keys() or raw.keys() - required - {"context"}:
        raise ValueError("Graph proposal requires idempotency_key, question, relations, expected; unknown fields are refused")
    if len(json.dumps(raw, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_GRAPH_DRAFT_BYTES:
        raise ValueError("Graph proposal exceeds 64 KiB")
    key = _text(raw["idempotency_key"], "idempotency_key", 200)
    question = raw["question"]
    if question is not None:
        fields = {"title", "summary", "views"}
        if (not isinstance(question, dict) or fields - question.keys()
                or question.keys() - fields - {"context", "facets", "evidence"}):
            raise ValueError("Question requires title, summary, views and optional context, facets, evidence")
        views = question["views"]
        if (not isinstance(views, list) or not views or any(not isinstance(v, str) for v in views)
                or len(set(views)) != len(views) or set(views) - set(view_names)):
            raise ValueError("Choose distinct configured views explicitly")
        item = normalize_item({"id": "$question", "kind": "question",
                               **{k: v for k, v in question.items() if k != "views"}})
        _context(item["context"])
        if not item["evidence"]:
            raise ValueError("A generated question requires source evidence")
        question = {k: item[k] for k in ("title", "summary", "context", "facets", "evidence")}
        question["views"] = sorted(views)
    relations = raw["relations"]
    maximum = MAX_GRAPH_RELATIONS if question is not None else MAX_OVERLAP_RELATIONS
    if not isinstance(relations, list) or not 1 <= len(relations) <= maximum:
        raise ValueError(f"Graph proposal requires between one and {maximum} relations")
    normalized_relations = []
    for index, relation in enumerate(relations):
        required_relation = {"subject", "predicate", "object", "rationale"}
        if (not isinstance(relation, dict) or required_relation - relation.keys()
                or relation.keys() - required_relation - {"context", "evidence"}):
            raise ValueError("Graph relations require subject, predicate, object, rationale and optional context, evidence")
        normalized = normalize_relation({"id": f"validation:{index}", **relation})
        _text(normalized["rationale"], "relation.rationale")
        _context(normalized["context"])
        if normalized["predicate"] not in CLAIM_QUESTION_PREDICATES | {"addresses", "tests", "part_of"}:
            raise ValueError("Graph proposals support question relations only")
        if not normalized["evidence"]:
            raise ValueError("A graph relation requires source evidence")
        endpoints = {normalized["subject"], normalized["object"]}
        if question is None and "$question" in endpoints:
            raise ValueError("$question requires a new question in this proposal")
        if question is not None and "$question" not in endpoints:
            raise ValueError("Every relation in a question proposal must reference $question")
        normalized_relations.append({k: normalized[k] for k in
                                     ("subject", "predicate", "object", "rationale", "context", "evidence")})
    expected = raw["expected"]
    if (not isinstance(expected, dict) or any(not isinstance(k, str) or not k.strip()
                                             or not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
                                             for k, v in expected.items())):
        raise ValueError("Expected input bindings must map existing IDs to graph_digest values")
    result = {"idempotency_key": key, "question": question, "relations": normalized_relations,
              "expected": deepcopy(expected), "context": _context(raw.get("context", {}))}
    graph_digest(result)
    return result


def validate_entry(entry, path, view_names):
    fields = {"version", "id", "session_id", "recorded_at", "request_digest", "proposal",
              "source_digests", "views", "capture_digest"}
    if not isinstance(entry, dict) or set(entry) != fields:
        raise ValueError("Malformed stored graph draft entry")
    if type(entry["version"]) is not int or entry["version"] != GRAPH_VERSION:
        raise ValueError("Unsupported stored graph draft version")
    if entry["capture_digest"] != graph_digest({k: v for k, v in entry.items() if k != "capture_digest"}):
        raise ValueError("Stored graph capture integrity mismatch")
    _text(entry["session_id"], "stored session_id", 200)
    if datetime.fromisoformat(entry["recorded_at"]).tzinfo is None:
        raise ValueError("Stored graph capture time requires a timezone")
    normalized = normalize_proposal(entry["proposal"], view_names)
    identifier = graph_identifier(entry["session_id"], normalized["idempotency_key"])
    if (entry["id"] != identifier or path.name != identifier + ".json"
            or entry["request_digest"] != graph_digest(normalized) or normalized != entry["proposal"]):
        raise ValueError("Stored graph draft integrity mismatch")
    if (not isinstance(entry["source_digests"], dict)
            or any(not isinstance(k, str) or not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
                   for k, v in entry["source_digests"].items())):
        raise ValueError("Malformed stored graph source digests")
    views = entry["views"]
    if (not isinstance(views, list) or any(not isinstance(v, str) for v in views)
            or views != sorted(set(views)) or set(views) - set(view_names)):
        raise ValueError("Malformed stored graph views")
    return entry


def journal_counts(entries):
    graph_entries = [entry for entry in entries if "proposal" in entry]
    return {"draft_count": len(entries) - len(graph_entries), "graph_draft_count": len(graph_entries),
            "graph_record_count": sum(entry["proposal"]["question"] is not None for entry in graph_entries),
            "graph_relation_count": sum(len(entry["proposal"]["relations"]) for entry in graph_entries)}


def validate_expected(proposal, snapshot):
    bundle = snapshot["bundle"]
    records = {r["id"]: r for name in ("items", "sources", "relations") for r in bundle[name]}
    endpoints = {r[k] for r in proposal["relations"] for k in ("subject", "object")} - {"$question"}
    if endpoints - proposal["expected"].keys():
        raise ValueError("Expected input bindings are required for every existing endpoint")
    for identifier, expected in proposal["expected"].items():
        if identifier not in records or graph_digest(records[identifier]) != expected:
            raise ValueError(f"Stale graph input: {identifier}; reassess before submitting a new proposal")


def capture_metadata(proposal, snapshot):
    """Freeze consulted source identities and affected existing publication views."""
    source_ids = {e["source_id"] for r in proposal["relations"] for e in r["evidence"]}
    if proposal["question"] is not None:
        source_ids.update(e["source_id"] for e in proposal["question"]["evidence"])
    sources = {s["id"]: s for s in snapshot["bundle"]["sources"]}
    if source_ids - sources.keys():
        raise ValueError("Graph evidence references an unknown source")
    if proposal["question"] is not None:
        views = proposal["question"]["views"]
    else:
        views = [name for name, identifiers in snapshot["views"].items()
                 if any(r["subject"] in identifiers and r["object"] in identifiers
                        for r in proposal["relations"])]
    return {identifier: graph_digest(sources[identifier]) for identifier in sorted(source_ids)}, sorted(views)


def compose_graph(bundle, configurations, entries):
    """Compose captured facts without treating old expected digests as current."""
    relations = []
    for entry in entries:
        proposal = entry["proposal"]
        question_id = entry["id"] + ":question"
        provenance = {"capture": "graph_draft", "graph_draft_id": entry["id"],
                      "session_id": entry["session_id"], "recorded_at": entry["recorded_at"],
                      "idempotency_key": proposal["idempotency_key"]}
        attribution = provenance | {
            "input_digests": json.dumps(proposal["expected"], sort_keys=True, separators=(",", ":")),
            "source_digests": json.dumps(entry["source_digests"], sort_keys=True, separators=(",", ":")),
        }
        if proposal["question"] is not None:
            question = proposal["question"]
            item = {k: deepcopy(v) for k, v in question.items() if k != "views"}
            item["context"] = deepcopy(proposal["context"]) | item["context"]
            item.update(id=question_id, kind="question", status="proposed", provenance=provenance)
            bundle["items"].append(item)
            for name in question["views"]:
                configurations[name]["item_ids"].append(question_id)
        for index, proposed in enumerate(proposal["relations"]):
            relation = deepcopy(proposed)
            for field in ("subject", "object"):
                if relation[field] == "$question":
                    relation[field] = question_id
            relation.update(id=f"{entry['id']}:link:{index}", status="proposed")
            relation["context"] = deepcopy(proposal["context"]) | relation["context"] | attribution
            relations.append(relation)
    kinds = {item["id"]: item["kind"] for item in bundle["items"]}
    sources = {source["id"] for source in bundle["sources"]}
    edges = {(r["subject"], r["predicate"], r["object"]) for r in bundle["relations"]}
    parents = {}
    for relation in bundle["relations"]:
        if relation["predicate"] == "part_of":
            parents.setdefault(relation["subject"], set()).add(relation["object"])
    for relation in relations:
        validate_record_references(relation, source_ids=sources, item_kinds=kinds)
        if kinds[relation["object"]] != "question":
            raise ValueError("Graph proposals must target questions")
        edge = (relation["subject"], relation["predicate"], relation["object"])
        if edge in edges:
            raise ValueError(f"Duplicate graph relation: {edge}; retain the existing relationship")
        edges.add(edge)
        if relation["predicate"] == "part_of":
            subject, target = relation["subject"], relation["object"]
            pending, seen = [target], set()
            while pending:
                ancestor = pending.pop()
                if ancestor == subject:
                    raise ValueError("part_of cycle or self-link is not allowed")
                if ancestor not in seen:
                    seen.add(ancestor)
                    pending.extend(parents.get(ancestor, ()))
            parents.setdefault(subject, set()).add(target)
    bundle["relations"].extend(relations)
