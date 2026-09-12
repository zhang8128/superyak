"""A durable research queue whose operational states never change scientific status."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .automation import _directory, _read, _save


STATES = {"queued", "active", "parked", "needs_reassessment"}
DEFAULT_ACTIVE_LIMIT = 12


def _ids(values, label):
    if not isinstance(values, (list, tuple, set, frozenset)) or any(
            not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{label} must contain nonblank question IDs")
    return sorted(set(values))


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


class QuestionAgenda:
    """One worker writes the agenda; rendering can inspect it without creating files.

    An omitted active_limit uses the saved setting, or 12 for a new agenda.
    An explicit limit is persisted with the next scheduling or event operation.
    Research callers take eligible(...)[0], then mark the completed research turn.
    """

    def __init__(self, project, *, active_limit=None):
        self.project = Path(project).resolve(strict=True)
        if not self.project.is_dir():
            raise ValueError("Question agenda project must be a directory")
        if active_limit is not None and not _integer(active_limit, 1):
            raise ValueError("active_limit must be a positive integer")
        self.root = self.project / ".atlas/research"
        self.state_file = self.root / "agenda.json"
        self._limit_override = active_limit
        self.active_limit = self._load()["active_limit"]

    def _check_paths(self):
        for directory in (self.project / ".atlas", self.root):
            if directory.is_symlink():
                raise ValueError(f"Question agenda directory cannot be a symlink: {directory}")
            if directory.exists() and not directory.is_dir():
                raise ValueError(f"Question agenda requires a directory: {directory}")
        if self.state_file.is_symlink():
            raise ValueError(f"Question agenda file cannot be a symlink: {self.state_file}")
        if self.state_file.exists() and not self.state_file.is_file():
            raise ValueError(f"Question agenda requires a regular file: {self.state_file}")

    def _load(self):
        self._check_paths()
        state = _read(self.state_file) if self.state_file.exists() else {
            "version": 1, "active_limit": DEFAULT_ACTIVE_LIMIT, "sequence": 0,
            "selection": None, "excluded_ids": [], "questions": {}}
        if (not isinstance(state, dict) or set(state) != {
                "version", "active_limit", "sequence", "selection", "excluded_ids", "questions"}
                or type(state["version"]) is not int or state["version"] != 1
                or not _integer(state["active_limit"], 1) or not _integer(state["sequence"])
                or not isinstance(state["questions"], dict)):
            raise ValueError("Invalid question agenda schema or version")
        if state["selection"] is not None:
            _ids(state["selection"], "Saved agenda selection")
        _ids(state["excluded_ids"], "Saved agenda exclusions")
        for identifier, entry in state["questions"].items():
            if (not isinstance(identifier, str) or not identifier.strip() or not isinstance(entry, dict)
                    or set(entry) != {"state", "pinned", "created", "last_researched", "research_count", "overlap_count"}
                    or not isinstance(entry["state"], str) or entry["state"] not in STATES
                    or type(entry["pinned"]) is not bool
                    or not _integer(entry["created"], 1) or entry["created"] > state["sequence"]
                    or not _integer(entry["research_count"]) or not _integer(entry["overlap_count"])
                    or entry["research_count"] + entry["overlap_count"] > state["sequence"] - entry["created"]
                    or (entry["last_researched"] is not None and (
                        not _integer(entry["last_researched"], 1)
                        or not entry["created"] <= entry["last_researched"] <= state["sequence"]))
                    or (entry["research_count"] == 0) != (entry["last_researched"] is None)):
                raise ValueError("Invalid saved question agenda entry")
        state = deepcopy(state)
        if self._limit_override is not None:
            state["active_limit"] = self._limit_override
        self.active_limit = state["active_limit"]
        return state

    def _save(self, state):
        self._check_paths()
        for directory in (self.project / ".atlas", self.root):
            _directory(directory)
        _save(self.state_file, state, replace=True)

    @staticmethod
    def _questions(snapshot):
        if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("bundle"), dict)
                or not isinstance(snapshot["bundle"].get("items"), list)
                or not isinstance(snapshot.get("views"), dict)):
            raise ValueError("Question agenda requires a research snapshot with configured views")
        membership = set()
        for ids in snapshot["views"].values():
            membership.update(_ids(ids, "Configured agenda view"))
        records = {}
        for item in snapshot["bundle"]["items"]:
            if not isinstance(item, dict):
                raise ValueError("Question agenda snapshot records must be objects")
            if item.get("kind") != "question":
                continue
            identifier = item.get("id")
            if (not isinstance(identifier, str) or not identifier.strip() or identifier in records
                    or not isinstance(item.get("status"), str)
                    or not isinstance(item.get("context", {}), dict)):
                raise ValueError("Invalid question record in agenda snapshot")
            records[identifier] = item
        scoped = {identifier for identifier, item in records.items()
                  if identifier in membership and item["status"] != "withdrawn"}
        return records, scoped

    @staticmethod
    def _entry(state, identifier):
        if identifier not in state["questions"]:
            state["sequence"] += 1
            state["questions"][identifier] = {
                "state": "queued", "pinned": False, "created": state["sequence"],
                "last_researched": None, "research_count": 0, "overlap_count": 0}
        return state["questions"][identifier]

    @staticmethod
    def _age_order(state, identifier):
        entry = state["questions"][identifier]
        return (entry["created"] if entry["last_researched"] is None else entry["last_researched"],
                entry["created"], identifier)

    def _reconcile(self, state, records, scoped):
        for identifier in sorted(records):
            entry = self._entry(state, identifier)
            entry["pinned"] = records[identifier].get("context", {}).get("worker_role") != "question"
        selection = None if state["selection"] is None else set(state["selection"])
        excluded = set(state["excluded_ids"])
        available, reasons = [], {}
        for identifier, entry in state["questions"].items():
            if identifier not in scoped:
                entry["state"] = "parked"
                reasons[identifier] = "Not a current, nonwithdrawn question in a configured view."
            elif identifier in excluded:
                entry["state"] = "needs_reassessment"
                reasons[identifier] = "Research is suspended pending reassessment of its supporting evidence."
            elif selection is not None and identifier not in selection:
                entry["state"] = "parked"
                reasons[identifier] = "Outside the operator's selected questions."
            elif not entry["pinned"] and not entry["overlap_count"]:
                entry["state"] = "queued"
                reasons[identifier] = "Waiting for an overlap attempt before new research."
            else:
                available.append(identifier)
        pinned = [identifier for identifier in available if state["questions"][identifier]["pinned"]]
        if len(pinned) > state["active_limit"]:
            raise ValueError("active_limit must be at least the number of eligible pinned questions")
        generated = sorted((identifier for identifier in available if identifier not in pinned),
                           key=lambda identifier: self._age_order(state, identifier))
        active = set(pinned + generated[:state["active_limit"] - len(pinned)])
        for identifier in available:
            entry = state["questions"][identifier]
            entry["state"] = "active" if identifier in active else "queued"
            reasons[identifier] = ("Pinned question, ready for research." if entry["pinned"] else
                                   "Ready for a research turn." if identifier in active else
                                   "Waiting for an active slot; older research turns rotate first.")
        return reasons

    def eligible(self, snapshot, question_ids=None, *, excluded_ids=()):
        """Persist the operational queue and return active questions in fair turn order."""
        state = self._load()
        records, scoped = self._questions(snapshot)
        selection = None if question_ids is None else _ids(question_ids, "Requested agenda selection")
        if selection and not set(selection) <= scoped:
            raise ValueError("requested question must be active and selected in a configured view")
        state["selection"] = selection or None
        state["excluded_ids"] = _ids(excluded_ids, "Agenda exclusions")
        self._reconcile(state, records, scoped)
        self._save(state)
        eligible = sorted((identifier for identifier in records if state["questions"][identifier]["state"] == "active"),
                          key=lambda identifier: self._age_order(state, identifier))
        if not eligible:
            raise ValueError("no active questions in the configured research views")
        return [records[identifier] for identifier in eligible]

    def _event(self, question_id, *, research):
        _ids([question_id], "Agenda event")
        state = self._load()
        entry = self._entry(state, question_id)
        state["sequence"] += 1
        if research:
            entry["research_count"] += 1
            entry["last_researched"] = state["sequence"]
        else:
            entry["overlap_count"] += 1
        self._save(state)
        return deepcopy(entry)

    def researched(self, question_id):
        """Count one completed research attempt, including attempts with no new finding."""
        return self._event(question_id, research=True)

    def overlapped(self, question_id):
        """Count a completed overlap attempt; finding no suitable link still qualifies."""
        return self._event(question_id, research=False)

    def status(self, snapshot):
        """Return per-question scheduling state and counts without writing any files."""
        state = self._load()
        records, scoped = self._questions(snapshot)
        reasons = self._reconcile(state, records, scoped)
        return {identifier: {
            "state": entry["state"], "reason": reasons[identifier], "pinned": entry["pinned"],
            "research_count": entry["research_count"], "overlap_count": entry["overlap_count"],
            "overlap_attempted": bool(entry["overlap_count"]),
            "can_generate_children": entry["state"] not in {"parked", "needs_reassessment"}
                and (entry["pinned"] or entry["research_count"] > 0),
            "last_researched": entry["last_researched"],
        } for identifier, entry in sorted(state["questions"].items())}
