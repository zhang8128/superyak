"""Independent assessments and dependency eligibility for later graph additions."""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re

from .automation import _directory, _now, _read, _save
from .research_graph import graph_digest


def _validate_entry(entry, path):
    fields = {"version", "record_id", "record_digest", "checked_at", "model", "stage", "verdict", "reason", "result"}
    if (not isinstance(entry, dict) or set(entry) != fields
            or type(entry["version"]) is not int or entry["version"] != 1
            or any(not isinstance(entry[key], str) or not entry[key].strip()
                   for key in ("record_id", "record_digest", "checked_at", "model", "stage", "verdict", "reason"))
            or entry["stage"] not in {"initial", "audit"}
            or entry["verdict"] not in {"supported", "unsupported", "uncertain"}
            or not re.fullmatch(r"[0-9a-f]{64}", entry["record_digest"])
            or not isinstance(entry["result"], dict)):
        raise ValueError("Invalid graph review entry schema")
    try:
        checked_at = datetime.fromisoformat(entry["checked_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Invalid graph review timestamp") from error
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("Graph review timestamp requires a timezone")
    if path.name != graph_digest(entry) + ".json":
        raise ValueError("Graph review filename does not match its immutable content")
    return checked_at


class GraphReviewLedger:
    def __init__(self, project):
        self.project = Path(project).resolve(strict=True)
        if not self.project.is_dir():
            raise ValueError("Graph review project must be a directory")
        self.root = self.project / ".atlas/research/graph-reviews"
        self._check_paths()

    def _check_paths(self):
        for path in (self.project / ".atlas", self.root.parent, self.root):
            if path.is_symlink():
                raise ValueError("Graph review state cannot be a symlink")
            if path.exists() and not path.is_dir():
                raise ValueError(f"Graph review state requires a directory: {path}")

    def current(self, snapshot):
        self._check_paths()
        records = {r["id"]: r for kind in ("items", "relations") for r in snapshot["bundle"][kind]}
        current, times = {}, {}
        for path in sorted(self.root.glob("*.json")):
            entry = _read(path)
            checked_at = _validate_entry(entry, path)
            record = records.get(entry["record_id"])
            if record is None or graph_digest(record) != entry["record_digest"]:
                continue
            if record["id"] not in current or checked_at > times[record["id"]]:
                current[record["id"]] = entry
                times[record["id"]] = checked_at
        return current

    def store(self, record, result, *, model, stage="audit", verdict=None, reason=None):
        self._check_paths()
        if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"].strip():
            raise ValueError("Graph review requires a record with a nonblank ID")
        if not isinstance(result, dict):
            raise ValueError("Graph review result must be an object")
        decision = result.get("analysis", result)
        if not isinstance(decision, dict):
            raise ValueError("Graph review decision must be an object")
        verdict = decision.get("verdict") if verdict is None else verdict
        if verdict == "useful":
            verdict = "supported"
        entry = {"version": 1, "record_id": record["id"], "record_digest": graph_digest(record),
                 "checked_at": _now(), "model": model, "stage": stage, "verdict": verdict,
                 "reason": decision.get("reason", "") if reason is None else reason, "result": deepcopy(result)}
        destination = self.root / (graph_digest(entry) + ".json")
        _validate_entry(entry, destination)
        for path in (self.project / ".atlas", self.root.parent, self.root):
            _directory(path)
        if destination.exists() or destination.is_symlink():
            existing = _read(destination)
            _validate_entry(existing, destination)
            if existing != entry:
                raise ValueError("Graph review entry already contains different immutable content")
            return existing
        _save(destination, entry)
        return entry


def exclusions(project, snapshot):
    """Keep a bad later edge separate from its otherwise valid original finding."""
    from .research_review import ReviewLedger
    excluded = ReviewLedger(project).excluded(snapshot)
    records = {r["id"]: r for r in snapshot["bundle"]["items"]}
    sources = {s["id"]: s for s in snapshot["bundle"]["sources"]}
    relations = snapshot["bundle"]["relations"]
    current = GraphReviewLedger(project).current(snapshot)
    excluded.update(identifier for identifier, review in current.items() if review["verdict"] != "supported")
    changed = True
    while changed:
        before = set(excluded)
        for record in records.values():
            context = record.get("context", {})
            if context.get("worker_role") != "question":
                continue
            try:
                premises = json.loads(context.get("derived_from", "null"))
                invalid = (not isinstance(premises, list) or not premises or
                           any(not isinstance(p, str) or p not in records or p in excluded
                               or records[p]["status"] == "withdrawn" for p in premises))
            except (ValueError, TypeError):
                invalid = True
            if invalid:
                excluded.add(record["id"])
        for relation in relations:
            context = relation.get("context", {})
            if context.get("capture") != "graph_draft":
                continue
            endpoints = (relation["subject"], relation["object"])
            invalid = any(p not in records or p in excluded or records[p]["status"] == "withdrawn" for p in endpoints)
            try:
                bound = json.loads(context["input_digests"])
                source_bound = json.loads(context["source_digests"])
                if any(not isinstance(mapping, dict) or any(
                        not isinstance(key, str) or not key.strip() or not isinstance(value, str)
                        or not re.fullmatch(r"[0-9a-f]{64}", value) for key, value in mapping.items())
                       for mapping in (bound, source_bound)):
                    raise ValueError("Graph relation digest bindings must be SHA-256 maps")
                invalid |= any(p in bound and graph_digest(records[p]) != bound[p] for p in endpoints if p in records)
                invalid |= any(e["source_id"] not in sources or source_bound.get(e["source_id"]) != graph_digest(sources[e["source_id"]])
                               for e in relation["evidence"])
            except (ValueError, TypeError, KeyError):
                invalid = True
            if invalid:
                excluded.add(relation["id"])
        # A failed initial evidence link requires reassessing its generated question.
        for relation in relations:
            target = records.get(relation["object"], {})
            if (relation["id"] in excluded and relation["predicate"] in {"informs", "raises_question"}
                    and target.get("context", {}).get("worker_role") == "question"
                    and relation["context"].get("graph_job_id") == target["context"].get("graph_job_id")):
                excluded.add(target["id"])
        changed = before != excluded
    return excluded
