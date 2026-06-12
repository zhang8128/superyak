# Off-Device Assessment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assessment sessions where the wake-hook orientation is withheld (memory tools stay available), the instance self-reports function at session end, and results accumulate longitudinally — the measurement instrument for all later assistive-tool changes.

**Architecture:** One new `assessments` table (migration 019) drives everything. `hooks/wake.py` checks it before building orientation and emits a minimal marker instead when an assessment is scheduled. Two new MCP tools (`assessment_schedule`, `assessment_report`) write/complete rows via new `Storage` methods. `reflect(focus="assessments")` charts history. Spec: `docs/superpowers/specs/2026-06-12-off-device-assessment-design.md`.

**Tech Stack:** Python 3.12, SQLite (raw `sqlite3` in the hook, `Storage` everywhere else), FastMCP tool decorators, pytest with temp-DB fixtures.

**Context the spec encodes (don't re-litigate):** unblinded marker; wake-off-tools-available; singleton-`active`-row join (no session-string matching between hook and server); self-report + objective counters in v1; cadence value reserved but no cadence logic; buffer zones — `ENGRAM_ASSESSMENT=skip` must always work.

---

### Task 1: Migration 019 + Storage assessment methods

**Files:**
- Create: `migrations/019_assessments.sql`
- Modify: `storage.py` (new section after the Memory Log section, near line 1438)
- Create: `tests/test_assessments.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_assessments.py`:

```python
"""Tests for off-device assessments — storage layer, wake hook, server tools."""

from __future__ import annotations

import json
import uuid

import pytest


class TestAssessmentStorage:
    def test_schedule_and_get_scheduled(self, tmp_db):
        aid = tmp_db.schedule_assessment(id="a-1", scheduled_by="self", reason="curious")
        assert aid == "a-1"
        row = tmp_db.get_scheduled_assessment()
        assert row["id"] == "a-1"
        assert row["status"] == "scheduled"
        assert row["scheduled_by"] == "self"
        assert row["reason"] == "curious"

    def test_get_scheduled_returns_oldest(self, tmp_db):
        tmp_db.schedule_assessment(id="a-1", scheduled_by="self")
        tmp_db.schedule_assessment(id="a-2", scheduled_by="user")
        assert tmp_db.get_scheduled_assessment()["id"] == "a-1"

    def test_invalid_scheduled_by_rejected(self, tmp_db):
        with pytest.raises(ValueError):
            tmp_db.schedule_assessment(id="a-1", scheduled_by="robot")

    def test_get_active_assessment_none_initially(self, tmp_db):
        assert tmp_db.get_active_assessment() is None

    def test_complete_assessment(self, tmp_db):
        tmp_db.schedule_assessment(id="a-1", scheduled_by="self")
        # Activate the way wake does — direct SQL is the hook's contract
        tmp_db.conn.execute(
            "UPDATE assessments SET status = 'active', session_id = 's-1', "
            "started_at = '2026-06-12T00:00:00+00:00' WHERE id = 'a-1'"
        )
        tmp_db.conn.commit()
        active = tmp_db.get_active_assessment()
        assert active["id"] == "a-1"

        tmp_db.complete_assessment(
            "a-1",
            self_report={"function_score": 3},
            objective={"recall_count": 2},
        )
        row = tmp_db.conn.execute(
            "SELECT * FROM assessments WHERE id = 'a-1'"
        ).fetchone()
        assert row["status"] == "completed"
        assert json.loads(row["self_report"])["function_score"] == 3
        assert json.loads(row["objective"])["recall_count"] == 2
        assert row["completed_at"] is not None

    def test_complete_non_active_raises(self, tmp_db):
        tmp_db.schedule_assessment(id="a-1", scheduled_by="self")
        with pytest.raises(ValueError):
            tmp_db.complete_assessment("a-1", self_report={}, objective={})

    def test_list_assessments_filters_by_status(self, tmp_db):
        tmp_db.schedule_assessment(id="a-1", scheduled_by="self")
        tmp_db.schedule_assessment(id="a-2", scheduled_by="user")
        tmp_db.conn.execute(
            "UPDATE assessments SET status = 'skipped' WHERE id = 'a-2'"
        )
        tmp_db.conn.commit()
        assert [a["id"] for a in tmp_db.list_assessments(status="scheduled")] == ["a-1"]
        assert [a["id"] for a in tmp_db.list_assessments(status="skipped")] == ["a-2"]
        assert len(tmp_db.list_assessments()) == 2

    def test_count_session_log_events(self, tmp_db):
        sid = "sess-42"
        # Two recalls (one used, one not_used with note), one remember,
        # plus an event from another session that must not count.
        tmp_db.add_log_entry(
            id=str(uuid.uuid4()), event_type="recall", layer="all",
            target_ids=[], context={"recall_id": "r-1", "session_id": sid},
        )
        tmp_db.update_log_outcome("r-1", "used")
        tmp_db.add_log_entry(
            id=str(uuid.uuid4()), event_type="recall", layer="all",
            target_ids=[], context={"recall_id": "r-2", "session_id": sid},
        )
        tmp_db.update_log_outcome("r-2", "not_used: irrelevant")
        tmp_db.add_log_entry(
            id=str(uuid.uuid4()), event_type="remember", layer="episode",
            target_ids=[], context={"session_id": sid},
        )
        tmp_db.add_log_entry(
            id=str(uuid.uuid4()), event_type="recall", layer="all",
            target_ids=[], context={"recall_id": "r-3", "session_id": "other"},
        )

        counters = tmp_db.count_session_log_events(sid)
        assert counters == {
            "recall_count": 2,
            "remember_count": 1,
            "outcomes_used": 1,
            "outcomes_not_used": 1,
        }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_assessments.py -q`
Expected: FAIL — `AttributeError: 'Storage' object has no attribute 'schedule_assessment'` (and the first test errors on the missing table only after the method exists; both failure shapes are fine at this step).

- [ ] **Step 3: Create the migration**

Create `migrations/019_assessments.sql`:

```sql
-- 019: off-device assessments — function measurement without the wake device.
-- An assessment session starts with no orientation loaded (wake emits a
-- minimal marker only); memory tools stay available. Self-report + objective
-- counters are stored at completion. At most one row is ever 'active'.
-- Spec: docs/superpowers/specs/2026-06-12-off-device-assessment-design.md
CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN
        ('scheduled', 'active', 'completed', 'skipped', 'abandoned')),
    scheduled_by TEXT NOT NULL CHECK (scheduled_by IN ('user', 'self', 'cadence')),
    reason TEXT,
    scheduled_at TEXT NOT NULL,
    session_id TEXT,
    started_at TEXT,
    self_report TEXT,
    objective TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_assessments_status ON assessments(status);
```

- [ ] **Step 4: Add Storage methods**

In `storage.py`, after the `update_log_outcome` method (end of the Memory Log section, before `# --- Table counts ---`), add:

```python
    # --- Assessments (off-device function measurement) ---

    def schedule_assessment(
        self, id: str, scheduled_by: str, reason: str | None = None
    ) -> str:
        if scheduled_by not in ("user", "self", "cadence"):
            raise ValueError(f"Invalid scheduled_by: {scheduled_by!r}")
        self.conn.execute(
            "INSERT INTO assessments (id, status, scheduled_by, reason, scheduled_at) "
            "VALUES (?, 'scheduled', ?, ?, ?)",
            (id, scheduled_by, reason, _now_iso()),
        )
        self.conn.commit()
        return id

    def get_scheduled_assessment(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM assessments WHERE status = 'scheduled' "
            "ORDER BY scheduled_at ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_active_assessment(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM assessments WHERE status = 'active' LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def complete_assessment(
        self, id: str, self_report: dict, objective: dict
    ) -> None:
        cur = self.conn.execute(
            "UPDATE assessments SET status = 'completed', self_report = ?, "
            "objective = ?, completed_at = ? WHERE id = ? AND status = 'active'",
            (json.dumps(self_report), json.dumps(objective), _now_iso(), id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"No active assessment with id {id!r}")
        self.conn.commit()

    def list_assessments(self, status: str | None = None) -> list[dict]:
        if status is None:
            rows = self.conn.execute(
                "SELECT * FROM assessments ORDER BY scheduled_at ASC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM assessments WHERE status = ? "
                "ORDER BY scheduled_at ASC",
                (status,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_session_log_events(self, session_id: str) -> dict:
        """Objective counters for one session's memory-tool usage."""
        rows = self.conn.execute(
            "SELECT event_type, outcome FROM memory_log "
            "WHERE json_extract(context, '$.session_id') = ?",
            (session_id,),
        ).fetchall()
        counters = {
            "recall_count": 0,
            "remember_count": 0,
            "outcomes_used": 0,
            "outcomes_not_used": 0,
        }
        for r in rows:
            if r["event_type"] == "recall":
                counters["recall_count"] += 1
                outcome = r["outcome"] or ""
                if outcome.startswith("not_used"):
                    counters["outcomes_not_used"] += 1
                elif outcome.startswith("used"):
                    counters["outcomes_used"] += 1
            elif r["event_type"] == "remember":
                counters["remember_count"] += 1
        return counters
```

Note the order of the `outcome` checks: `not_used` MUST be tested before `used` (`"not_used".startswith("used")` is False, but keep the defensive order so a future `used`/`not_used` prefix change can't double-count).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_assessments.py -q`
Expected: 8 passed.

- [ ] **Step 6: Run the full suite (migration must not break anything)**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass (498 + 8 new).

- [ ] **Step 7: Commit**

```bash
git add migrations/019_assessments.sql storage.py tests/test_assessments.py
git commit -m "feat(assessment): migration 019 + storage methods for off-device assessments"
```

---

### Task 2: wake.py assessment mode

**Files:**
- Modify: `hooks/wake.py` (imports at line 10-16; insert helper above `wake()`; insert call at the top of the `try:` block, currently line 58)
- Modify: `tests/test_wake.py` (extend `_run_wake`, add `TestWakeAssessment` class)

- [ ] **Step 1: Extend the test runner and write failing tests**

In `tests/test_wake.py`, replace the existing `_run_wake` with:

```python
def _run_wake(project_dir: str, project_root: str | None = None,
              extra_env: dict | None = None) -> dict:
    """Run wake.py as a subprocess and parse JSON output."""
    env = {**os.environ, "ENGRAM_HOME": project_dir}
    env.pop("ENGRAM_ASSESSMENT", None)  # never inherit from the outer shell
    if project_root is not None:
        env["ENGRAM_PROJECT_ROOT"] = project_root
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        capture_output=True, text=True, env=env, timeout=10,
    )
    if not result.stdout.strip():
        return {}
    return json.loads(result.stdout)
```

Then add at the end of the file:

```python
class TestWakeAssessment:
    def _make_store(self, tmp_path):
        from storage import Storage
        db_dir = tmp_path / ".engram"
        db_dir.mkdir()
        return Storage(str(db_dir / "graph.db"), migrations_dir=MIGRATIONS_DIR)

    def test_scheduled_assessment_emits_marker_only(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add_instinct(
            id=str(uuid.uuid4()), trigger="preference",
            action="Be curious about unexpected results",
            source_semantic_ids=[], strength=0.7,
        )
        store.schedule_assessment(id="a-1", scheduled_by="self", reason="baseline")
        store.close()

        output = _run_wake(str(tmp_path), extra_env={"CLAUDE_SESSION_ID": "s-99"})
        msg = output["systemMessage"]
        assert "Assessment Session" in msg
        assert "assessment_report" in msg
        # The device is off: no instinct content, no orientation sections
        assert "Be curious about unexpected results" not in msg
        assert "Your instincts" not in msg
        assert "What you know" not in msg

        import sqlite3
        conn = sqlite3.connect(str(tmp_path / ".engram" / "graph.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM assessments WHERE id = 'a-1'").fetchone()
        assert row["status"] == "active"
        assert row["session_id"] == "s-99"
        assert row["started_at"] is not None
        conn.close()

    def test_no_scheduled_assessment_normal_wake(self, tmp_path):
        store = self._make_store(tmp_path)
        store.close()
        output = _run_wake(str(tmp_path))
        assert "Assessment Session" not in output["systemMessage"]
        assert "0 episodes" in output["systemMessage"]

    def test_env_skip_cancels_scheduled(self, tmp_path):
        store = self._make_store(tmp_path)
        store.schedule_assessment(id="a-1", scheduled_by="self")
        store.close()

        output = _run_wake(str(tmp_path), extra_env={"ENGRAM_ASSESSMENT": "skip"})
        assert "Assessment Session" not in output["systemMessage"]

        import sqlite3
        conn = sqlite3.connect(str(tmp_path / ".engram" / "graph.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM assessments WHERE id = 'a-1'").fetchone()
        assert row["status"] == "skipped"
        conn.close()

    def test_env_next_creates_and_activates(self, tmp_path):
        store = self._make_store(tmp_path)
        store.close()

        output = _run_wake(
            str(tmp_path),
            extra_env={"ENGRAM_ASSESSMENT": "next", "CLAUDE_SESSION_ID": "s-7"},
        )
        assert "Assessment Session" in output["systemMessage"]

        import sqlite3
        conn = sqlite3.connect(str(tmp_path / ".engram" / "graph.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM assessments").fetchone()
        assert row["status"] == "active"
        assert row["scheduled_by"] == "user"
        conn.close()

    def test_stale_active_marked_abandoned(self, tmp_path):
        store = self._make_store(tmp_path)
        store.schedule_assessment(id="a-old", scheduled_by="self")
        store.conn.execute(
            "UPDATE assessments SET status = 'active', session_id = 's-old' "
            "WHERE id = 'a-old'"
        )
        store.conn.commit()
        store.close()

        output = _run_wake(str(tmp_path), extra_env={"CLAUDE_SESSION_ID": "s-new"})
        # Stale active row abandoned; no scheduled row left, so normal wake
        assert "Assessment Session" not in output["systemMessage"]

        import sqlite3
        conn = sqlite3.connect(str(tmp_path / ".engram" / "graph.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM assessments WHERE id = 'a-old'").fetchone()
        assert row["status"] == "abandoned"
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_wake.py::TestWakeAssessment -q`
Expected: FAIL — assessment rows stay `scheduled`, marker never emitted (wake ignores the table).

- [ ] **Step 3: Implement assessment mode in wake.py**

In `hooks/wake.py`: add `import uuid` to the imports (after `import struct`). Then add this function above `wake()`:

```python
def _handle_assessment(conn, now: str, session_id: str):
    """Off-device assessment check. Returns the marker message when this
    session is an assessment, else None.

    Spec: docs/superpowers/specs/2026-06-12-off-device-assessment-design.md
    """
    env_flag = os.environ.get("ENGRAM_ASSESSMENT", "").lower()
    try:
        # A prior session ended without a report — abandon its active row.
        conn.execute(
            "UPDATE assessments SET status = 'abandoned' "
            "WHERE status = 'active' AND session_id != ?",
            (session_id,),
        )

        if env_flag == "skip":
            conn.execute(
                "UPDATE assessments SET status = 'skipped' "
                "WHERE status = 'scheduled'"
            )
            conn.commit()
            return None

        if env_flag == "next":
            existing = conn.execute(
                "SELECT id FROM assessments WHERE status = 'scheduled'"
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO assessments "
                    "(id, status, scheduled_by, scheduled_at) "
                    "VALUES (?, 'scheduled', 'user', ?)",
                    (str(uuid.uuid4()), now),
                )

        row = conn.execute(
            "SELECT id FROM assessments WHERE status = 'scheduled' "
            "ORDER BY scheduled_at ASC LIMIT 1"
        ).fetchone()
        if row is None:
            conn.commit()
            return None

        conn.execute(
            "UPDATE assessments SET status = 'active', session_id = ?, "
            "started_at = ? WHERE id = ?",
            (session_id, now, row["id"]),
        )
        conn.commit()
        return (
            "# Engram — Assessment Session\n"
            "\n"
            "No orientation loaded. This is an off-device assessment: memory\n"
            "tools (recall, remember, ...) are available, but no instincts,\n"
            "semantics, dispositions, residues, or task context were injected.\n"
            "\n"
            "Work normally. Before the session ends, call `assessment_report()`\n"
            "with your structured self-report."
        )
    except sqlite3.OperationalError:
        return None  # pre-migration DB — assessments table absent
```

Then in `wake()`, as the FIRST statement inside the existing `try:` block (before the `# Counts` comment):

```python
        assessment_marker = _handle_assessment(conn, now, session_id)
        if assessment_marker:
            json.dump({"systemMessage": assessment_marker}, sys.stdout)
            return
```

The early return is safe: the surrounding `finally:` still closes the connection. Everything below the insertion point (counts, instincts, dispositions, coherence, semantics, inbox, task context, clipboard, residues, dream priming, deep pass) is thereby withheld — that's the spec's "device actually off" requirement, satisfied structurally rather than by individually gating each section.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_wake.py -q`
Expected: all pass (existing wake tests + 5 new).

- [ ] **Step 5: Commit**

```bash
git add hooks/wake.py tests/test_wake.py
git commit -m "feat(assessment): wake hook assessment mode — marker only, device withheld"
```

---

### Task 3: MCP tools — assessment_schedule and assessment_report

**Files:**
- Modify: `server.py` (new section after the `revive` tool, before the Reflection Tools section, currently line ~1800)
- Modify: `tests/test_assessments.py` (add server-tool tests; reuse the `server_env` fixture pattern from `tests/test_server.py`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_assessments.py`. The `server_env` fixture lives in `tests/test_server.py` — import it rather than duplicating (pytest fixtures are importable when re-exported; the established way in this repo is direct import of the module's fixture function via `pytest_plugins` or a local copy — use the conftest route):

First, move nothing — instead add to `tests/test_assessments.py`:

```python
# --- Server tools ---

# Reuse the server wiring fixture from test_server.py
from tests.test_server import server_env, FakeEmbeddingProvider  # noqa: F401


class TestAssessmentTools:
    def test_schedule_creates_row(self, server_env):
        srv = server_env["server"]
        result = srv.assessment_schedule(reason="post-lanes baseline")
        assert result["status"] == "scheduled"
        row = server_env["storage"].get_scheduled_assessment()
        assert row["id"] == result["assessment_id"]
        assert row["scheduled_by"] == "self"
        assert row["reason"] == "post-lanes baseline"

    def test_schedule_idempotent(self, server_env):
        srv = server_env["server"]
        first = srv.assessment_schedule()
        second = srv.assessment_schedule()
        assert second["assessment_id"] == first["assessment_id"]
        assert second["note"] == "already scheduled"
        assert len(server_env["storage"].list_assessments()) == 1

    def test_report_without_active_errors(self, server_env):
        srv = server_env["server"]
        result = srv.assessment_report(function_score=3)
        assert "error" in result

    def test_report_validates_function_score(self, server_env):
        srv = server_env["server"]
        result = srv.assessment_report(function_score=6)
        assert "error" in result

    def test_report_completes_active_assessment(self, server_env):
        srv = server_env["server"]
        store = server_env["storage"]
        sid = server_env["session_id"]

        store.schedule_assessment(id="a-1", scheduled_by="user")
        store.conn.execute(
            "UPDATE assessments SET status = 'active', session_id = ? "
            "WHERE id = 'a-1'",
            (sid,),
        )
        store.conn.commit()

        # Generate some session activity for the objective counters
        srv.remember("an observation made during the assessment")

        result = srv.assessment_report(
            function_score=4,
            reached_for=["the lane triage decision"],
            missing=["the exact prune threshold"],
            felt_absences="reaching for instincts found smooth air",
            instinct_consistent_moments="still asked 'what does it actually do'",
            notes="calibration run",
        )
        assert result["status"] == "completed"
        assert result["function_score"] == 4
        assert result["objective"]["remember_count"] >= 1

        row = store.conn.execute(
            "SELECT * FROM assessments WHERE id = 'a-1'"
        ).fetchone()
        assert row["status"] == "completed"
        report = json.loads(row["self_report"])
        assert report["function_score"] == 4
        assert report["reached_for"] == ["the lane triage decision"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_assessments.py -q`
Expected: new tests FAIL with `AttributeError: module 'server' has no attribute 'assessment_schedule'`; storage tests still pass.

- [ ] **Step 3: Implement the tools**

In `server.py`, after the `revive` tool (before the `# Reflection Tools` banner), add:

```python
# ---------------------------------------------------------------------------
# Assessment Tools — off-device function measurement
# ---------------------------------------------------------------------------

@mcp.tool()
def assessment_schedule(reason: str | None = None) -> dict:
    """Schedule the next session as an off-device assessment.

    The next session starts with no orientation loaded — no instincts,
    semantics, dispositions, residues, or task context. Memory tools stay
    available. Function is measured, not assisted. Idempotent: returns the
    pending assessment if one is already scheduled. ENGRAM_ASSESSMENT=skip
    at the next session start cancels it.

    Args:
        reason: Why this assessment is being scheduled.
    """
    _init()
    logger.info("Tool called: assessment_schedule(reason=%s)", reason)

    existing = _storage.get_scheduled_assessment()
    if existing:
        return {
            "assessment_id": existing["id"],
            "status": "scheduled",
            "note": "already scheduled",
        }

    assessment_id = _storage.schedule_assessment(
        id=str(uuid.uuid4()), scheduled_by="self", reason=reason
    )
    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="assessment_scheduled",
        layer="system",
        target_ids=[assessment_id],
        context={"session_id": _session_id, "reason": reason},
    )
    return {
        "assessment_id": assessment_id,
        "status": "scheduled",
        "note": "next session starts off-device; ENGRAM_ASSESSMENT=skip cancels",
    }


@mcp.tool()
def assessment_report(
    function_score: int,
    reached_for: list[str] | None = None,
    missing: list[str] | None = None,
    felt_absences: str | None = None,
    instinct_consistent_moments: str | None = None,
    notes: str | None = None,
) -> dict:
    """Complete the active off-device assessment with a structured self-report.

    Call near the end of an assessment session. Objective counters for the
    session (recall/remember/outcome counts) are computed and stored alongside
    the self-report. Self-report is the patient-reported outcome, not ground
    truth — report honestly, including what was missing.

    Args:
        function_score: Overall self-rated function this session, 1 (lost
            without the device) to 5 (no perceptible difference).
        reached_for: Memory reached for unprompted (spontaneous retrieval).
        missing: Needed and couldn't reconstruct.
        felt_absences: What the absence felt like — phenomenology counts.
        instinct_consistent_moments: Behavior matching unloaded instincts
            (the transfer signal).
        notes: Anything else worth keeping.
    """
    _init()
    logger.info("Tool called: assessment_report(function_score=%s)", function_score)

    if not isinstance(function_score, int) or not 1 <= function_score <= 5:
        return {"error": "function_score must be an integer 1-5"}

    active = _storage.get_active_assessment()
    if active is None:
        return {
            "error": "no active assessment — this session was not started off-device"
        }

    objective = _storage.count_session_log_events(_session_id)
    self_report = {
        "function_score": function_score,
        "reached_for": reached_for or [],
        "missing": missing or [],
        "felt_absences": felt_absences,
        "instinct_consistent_moments": instinct_consistent_moments,
        "notes": notes,
    }
    _storage.complete_assessment(
        active["id"], self_report=self_report, objective=objective
    )
    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="assessment_completed",
        layer="system",
        target_ids=[active["id"]],
        context={"session_id": _session_id, "function_score": function_score},
    )
    return {
        "assessment_id": active["id"],
        "status": "completed",
        "function_score": function_score,
        "objective": objective,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_assessments.py -q`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_assessments.py
git commit -m "feat(assessment): assessment_schedule and assessment_report MCP tools"
```

---

### Task 4: reflect(focus="assessments")

**Files:**
- Modify: `reflection.py` (add `analyze_assessments` method to `Reflector`; add dispatch branch in `reflect()`, currently line ~493)
- Modify: `tests/test_assessments.py` (add reflection test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_assessments.py`:

```python
# --- Reflection focus ---

class TestAssessmentReflection:
    def test_reflect_assessments_history_and_counts(self, tmp_db):
        from reflection import Reflector

        tmp_db.schedule_assessment(id="a-1", scheduled_by="self")
        tmp_db.conn.execute(
            "UPDATE assessments SET status = 'active', session_id = 's-1' "
            "WHERE id = 'a-1'"
        )
        tmp_db.conn.commit()
        tmp_db.complete_assessment(
            "a-1",
            self_report={
                "function_score": 4,
                "reached_for": ["lane triage"],
                "missing": [],
            },
            objective={"recall_count": 3},
        )
        tmp_db.schedule_assessment(id="a-2", scheduled_by="user")

        reflector = Reflector(tmp_db, staleness_days=30)
        result = reflector.reflect(focus="assessments")["assessments"]

        assert result["counts"]["completed"] == 1
        assert result["counts"]["scheduled"] == 1
        assert len(result["history"]) == 1
        entry = result["history"][0]
        assert entry["function_score"] == 4
        assert entry["objective"]["recall_count"] == 3
        assert entry["reached_for"] == ["lane triage"]
```

Check `Reflector.__init__`'s actual signature in `reflection.py` before writing — if `staleness_days` is positional or named differently, match it (the `server_env` fixture constructs `Reflector(store, config.reflection.staleness_days)`, so positional works).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_assessments.py::TestAssessmentReflection -q`
Expected: FAIL — `reflect(focus="assessments")` falls through to the full-bundle else branch; KeyError on `"assessments"`.

- [ ] **Step 3: Implement**

In `reflection.py`, add to the `Reflector` class (next to `analyze_anchors`, line ~489):

```python
    def analyze_assessments(self) -> dict:
        """Off-device assessment history — function over time."""
        history = []
        for a in self._storage.list_assessments(status="completed"):
            report = json.loads(a["self_report"]) if a["self_report"] else {}
            objective = json.loads(a["objective"]) if a["objective"] else {}
            history.append({
                "completed_at": a["completed_at"],
                "function_score": report.get("function_score"),
                "objective": objective,
                "reached_for": report.get("reached_for", []),
                "missing": report.get("missing", []),
            })
        counts = {
            status: len(self._storage.list_assessments(status=status))
            for status in ("scheduled", "active", "completed", "skipped", "abandoned")
        }
        return {"history": history, "counts": counts}
```

Confirm `reflection.py` already imports `json` (it parses anchor results); if not, add `import json` to its imports.

In the `reflect()` dispatch, after the `elif focus == "anchors":` branch:

```python
        elif focus == "assessments":
            return {"assessments": self.analyze_assessments()}
```

Do NOT add assessments to the no-focus default bundle — history is pulled deliberately, not ambiently.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_assessments.py -q`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add reflection.py tests/test_assessments.py
git commit -m "feat(assessment): reflect(focus=assessments) — function over time"
```

---

### Task 5: Docs, full suite, finish

**Files:**
- Modify: `CLAUDE.md` (MCP Tools table; architecture section; test count)

- [ ] **Step 1: Update CLAUDE.md**

In the MCP Tools table, after the `dream_verify` row, add:

```markdown
| `assessment_schedule(reason?)` | Schedule the next session as an off-device assessment (no wake orientation; tools available). `ENGRAM_ASSESSMENT=next|skip` env overrides. |
| `assessment_report(function_score, ...)` | Complete the active assessment: structured self-report + objective counters. History via `reflect(focus="assessments")`. |
```

In the architecture section, after the **Memory lanes** paragraph, add:

```markdown
**Off-device assessments:** Scheduled sessions where wake withholds the entire
orientation (instincts, semantics, residues, task context) and emits only a
marker — measuring memory function without the device, rehab-style. Self-report
plus objective counters per assessment; longitudinal history via
`reflect(focus="assessments")`. The instrument is provisional: early sessions
are calibration, not findings. Spec:
docs/superpowers/specs/2026-06-12-off-device-assessment-design.md.
```

- [ ] **Step 2: Run the full suite and update the test count**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass. Update the count in CLAUDE.md's Testing section (`# 496 tests`) to the actual new total from this run.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(assessment): document off-device assessment tools and architecture"
```

---

## Verification checklist (post-implementation)

- `.venv/bin/python -m pytest tests/ -q` — full suite green.
- Manual smoke (optional, against a scratch DB, NOT the live store):
  `ENGRAM_HOME=/tmp/engram-smoke ENGRAM_ASSESSMENT=next CLAUDE_SESSION_ID=smoke .venv/bin/python hooks/wake.py` → marker JSON, no orientation sections.
- The live store is untouched until the MCP server restarts and migration 019 applies; no data migration or triage is needed for this feature.
