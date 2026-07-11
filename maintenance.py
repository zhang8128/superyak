"""Sleep-maintenance pain channel.

Startup consolidation runs a dozen steps that historically failed into an
unread stderr stream — the store stayed safe but nobody learned anything
was wrong (the cohesion sleep pass sat dead for 18 days behind a crashed
auto-compress). This module records what ran, what failed, and what got
skipped, persists the report to memory_log, and lets status() and the wake
hook surface failures where they will actually be seen.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

logger = logging.getLogger("engram.maintenance")

EVENT_TYPE = "maintenance_report"


class MaintenanceReport:
    """Collects per-step outcomes of one sleep-maintenance run."""

    def __init__(self) -> None:
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.steps: list[dict] = []

    @contextmanager
    def step(self, name: str):
        """Run one maintenance step; record success or swallow-and-record
        its failure so later steps still run (the pre-existing contract)."""
        rec: dict = {"name": name, "ok": True}
        self.steps.append(rec)
        try:
            yield rec
        except Exception as e:
            rec["ok"] = False
            rec["error"] = f"{type(e).__name__}: {e}"
            logger.warning("maintenance step %r failed", name, exc_info=True)

    def note(self, name: str, **info) -> None:
        """Attach counts/details to the most recent step with this name."""
        for rec in reversed(self.steps):
            if rec["name"] == name:
                rec.update(info)
                return

    @property
    def failures(self) -> list[dict]:
        return [s for s in self.steps if not s["ok"]]

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "ok": self.ok,
            "steps": self.steps,
            "failures": self.failures,
        }

    def save(self, conn) -> None:
        """Persist to memory_log (same table/columns the sleep passes use)."""
        try:
            conn.execute(
                "INSERT INTO memory_log"
                " (id, timestamp, event_type, layer, target_ids, context, outcome)"
                " VALUES (?, ?, ?, 'system', '[]', ?, ?)",
                (
                    str(uuid.uuid4()),
                    datetime.now(timezone.utc).isoformat(),
                    EVENT_TYPE,
                    json.dumps(self.to_dict()),
                    "ok" if self.ok else f"failed:{len(self.failures)}",
                ),
            )
            conn.commit()
        except Exception:
            logger.warning("could not persist maintenance report", exc_info=True)

    @staticmethod
    def load_last(conn) -> dict | None:
        """Return the most recent report as a dict (with 'at'), or None."""
        try:
            row = conn.execute(
                "SELECT timestamp, context FROM memory_log"
                " WHERE event_type = ? ORDER BY timestamp DESC, rowid DESC LIMIT 1",
                (EVENT_TYPE,),
            ).fetchone()
        except Exception:
            logger.warning("could not load maintenance report", exc_info=True)
            return None
        if not row or not row[1]:
            return None
        try:
            report = json.loads(row[1])
        except (ValueError, TypeError):
            return None
        report["at"] = row[0]
        return report
