"""Different research roles share one model and take durable, bounded turns."""

import time
import uuid
from collections import Counter

from .automation import _directory, _now, _read, _save


ROLES = ("research", "audit", "question", "overlap", "connect")


class WorkerRotation:
    def __init__(self, research, *, roles):
        if not isinstance(roles, list) or not roles or any(role not in ROLES for role in roles):
            raise ValueError("Choose worker roles from " + ", ".join(ROLES))
        self.research, self.roles = research, list(roles)
        self.root = research.root
        self.state_file = self.root / "rotation.json"
        self.turns = self.root / "turns"
        _directory(self.turns)
        self.state = _read(self.state_file) if self.state_file.exists() else {"version": 1, "next_turn": 0}

    def _perform(self, role):
        if role == "research":
            return self.research.cycle()
        if role == "audit":
            from .research_review import review_backlog
            from .research_graph_audit import audit_graph
            audit_turns = sum(_read(path)["worker_role"] == "audit" for path in self.turns.glob("*.json"))
            if audit_turns % 2:
                graph = audit_graph(self.research, limit=1)
                if graph["reviewed"] or graph["errors"]:
                    return graph
            failures = Counter(error["input_digest"] for path in self.turns.glob("*.json")
                               for turn in [_read(path)] if turn["worker_role"] == "audit"
                               for error in turn.get("errors", [])
                               if error.get("kind") in {"invalid_review", "invalid_input"} and error.get("input_digest"))
            result = review_backlog(self.research.project, self.research.model, limit=1,
                                    progress=self.research.progress, should_stop=self.research.should_stop,
                                    skip_inputs={key for key, count in failures.items() if count >= 3})
            if not result["reviewed"] and not result["errors"]:
                graph = audit_graph(self.research, limit=1)
                if graph["reviewed"] or graph["errors"]:
                    return graph
            return result | {"saved": 0, "record_ids": [], "held": result["verdicts"].get("unsupported", 0)
                             + result["verdicts"].get("uncertain", 0)}
        if role == "question":
            from .research_questions import QuestionWorker
            return QuestionWorker(self.research).cycle()
        if role == "overlap":
            from .research_overlap import OverlapWorker
            return OverlapWorker(self.research).cycle()
        from .research_connections import ConnectionWorker
        return ConnectionWorker(self.research).cycle()

    def cycle(self):
        role = self.roles[self.state["next_turn"] % len(self.roles)]
        started = time.monotonic()
        self.research.progress(worker_role=role, phase="working", paper=None, question=None)
        try:
            result = self._perform(role)
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
            result = {"errors": [{"error": str(error)}]}
        result = {"saved": 0, "links_added": 0, "reviewed": 0, "held": 0, "skipped": 0, "record_ids": [],
                  **result, "worker_role": role, "seconds": round(time.monotonic() - started, 2)}
        from .research_graph_work import agenda_status
        result["question_agenda"] = agenda_status(self.research, self.research.inbox.snapshot())
        _save(self.turns / (uuid.uuid4().hex + ".json"), result | {"completed_at": _now(),
              "model": self.research.model.model})
        self.state["next_turn"] += 1
        _save(self.state_file, self.state, replace=True)
        return result

    def metrics(self):
        result = {}
        for path in self.turns.glob("*.json"):
            turn = _read(path)
            totals = result.setdefault(turn["worker_role"], {"turns": 0, "saved": 0, "reviewed": 0,
                                                            "links_added": 0, "held": 0, "skipped": 0, "errors": 0, "seconds": 0})
            totals["turns"] += 1
            for key in ("saved", "links_added", "reviewed", "held", "skipped", "seconds"):
                totals[key] += turn.get(key, 0)
            totals["errors"] += len(turn.get("errors", []))
        return result
