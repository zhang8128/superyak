"""Tests for off-device assessments — storage layer, wake hook, server tools."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

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

        # Completed assessments cannot be completed again
        with pytest.raises(ValueError):
            tmp_db.complete_assessment("a-1", self_report={}, objective={})

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


# --- Nudge gating ---

NUDGE_SCRIPT = Path(__file__).resolve().parent.parent / "hooks" / "nudge.py"
MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


def _load_nudge_module():
    spec = importlib.util.spec_from_file_location("engram_nudge_hook", NUDGE_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestNudgeAssessmentGate:
    """During an active off-device assessment the nudge pathway is part of
    the device and must be off: no Thread/Echo injection, no bias writes.
    Spec: docs/superpowers/specs/2026-06-12-off-device-assessment-design.md
    """

    def test_gate_fires_on_any_active_row(self, tmp_db):
        nudge = _load_nudge_module()
        tmp_db.schedule_assessment(id="a-1", scheduled_by="self")
        tmp_db.conn.execute(
            "UPDATE assessments SET status = 'active', session_id = 's-other' "
            "WHERE id = 'a-1'"
        )
        tmp_db.conn.commit()
        assert nudge._assessment_active(tmp_db.conn) is True

    def test_gate_quiet_without_active_row(self, tmp_db):
        nudge = _load_nudge_module()
        assert nudge._assessment_active(tmp_db.conn) is False
        # Scheduled / completed rows don't gate — only active ones.
        tmp_db.schedule_assessment(id="a-1", scheduled_by="self")
        tmp_db.conn.execute(
            "INSERT INTO assessments (id, status, scheduled_by, scheduled_at, "
            "completed_at) VALUES ('a-2', 'completed', 'self', "
            "'2026-06-11T00:00:00+00:00', '2026-06-11T01:00:00+00:00')"
        )
        tmp_db.conn.commit()
        assert nudge._assessment_active(tmp_db.conn) is False

    def test_gate_quiet_on_pre_migration_db(self, tmp_db):
        nudge = _load_nudge_module()
        tmp_db.conn.execute("DROP TABLE assessments")
        tmp_db.conn.commit()
        assert nudge._assessment_active(tmp_db.conn) is False

    # --- End-to-end: run the hook the way the harness does (stdin JSON) ---

    def _make_engram_home(self, tmp_path):
        from storage import Storage
        db_dir = tmp_path / ".engram"
        db_dir.mkdir()
        return Storage(str(db_dir / "graph.db"), migrations_dir=MIGRATIONS_DIR)

    def _run_nudge(self, engram_home, prompt):
        env = {
            **os.environ,
            "ENGRAM_HOME": str(engram_home),
            "ENGRAM_PROJECT_ROOT": str(engram_home),  # don't pick up repo config
        }
        env.pop("CLAUDE_SESSION_ID", None)
        return subprocess.run(
            [sys.executable, str(NUDGE_SCRIPT)],
            input=json.dumps({"prompt": prompt}),
            capture_output=True, text=True, env=env, timeout=120,
        )

    def test_nudge_silent_during_active_assessment(self, tmp_path):
        store = self._make_engram_home(tmp_path)
        store.schedule_assessment(id="a-1", scheduled_by="self")
        store.conn.execute(
            "UPDATE assessments SET status = 'active', session_id = 's-1' "
            "WHERE id = 'a-1'"
        )
        store.conn.commit()
        store.close()

        prompt = ("a sufficiently long user prompt about memory lanes, "
                  "compression review, and instinct formation during a session")
        result = self._run_nudge(tmp_path, prompt)
        assert result.stdout.strip() == ""   # nothing injected
        assert "# nudge:" not in result.stderr  # silent exit, not an error

        conn = sqlite3.connect(str(tmp_path / ".engram" / "graph.db"))
        assert conn.execute("SELECT COUNT(*) FROM session_bias").fetchone()[0] == 0
        # No auto-captured episode either — the device is fully off.
        assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 0
        conn.close()

    def test_nudge_proceeds_without_assessment(self, tmp_path):
        """Smoke: with no active assessment, nudge runs its normal flow."""
        store = self._make_engram_home(tmp_path)
        store.close()

        prompt = ("a sufficiently long user prompt about memory lanes, "
                  "compression review, and instinct formation during a session")
        result = self._run_nudge(tmp_path, prompt)
        assert result.returncode == 0

        conn = sqlite3.connect(str(tmp_path / ".engram" / "graph.db"))
        # The normal flow records the message embedding for topic-shift
        # tracking — its presence proves the gate did not fire.
        rows = conn.execute(
            "SELECT COUNT(*) FROM context_prev_embedding"
        ).fetchone()[0]
        conn.close()
        assert rows == 1


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

    def test_report_race_abandoned_returns_error(self, server_env):
        srv = server_env["server"]
        store = server_env["storage"]
        store.schedule_assessment(id="a-1", scheduled_by="user")
        store.conn.execute(
            "UPDATE assessments SET status = 'active', session_id = ? WHERE id = 'a-1'",
            (server_env["session_id"],),
        )
        store.conn.commit()

        original = store.complete_assessment

        def race(aid, self_report, objective):
            store.conn.execute(
                "UPDATE assessments SET status = 'abandoned' WHERE id = ?", (aid,)
            )
            store.conn.commit()
            return original(aid, self_report=self_report, objective=objective)

        store.complete_assessment = race
        result = srv.assessment_report(function_score=3)
        store.complete_assessment = original
        assert "error" in result
        assert "abandoned" in result["error"]

    def test_report_warns_on_session_mismatch(self, server_env):
        srv = server_env["server"]
        store = server_env["storage"]
        store.schedule_assessment(id="a-1", scheduled_by="user")
        store.conn.execute(
            "UPDATE assessments SET status = 'active', session_id = 'someone-else' "
            "WHERE id = 'a-1'"
        )
        store.conn.commit()

        result = srv.assessment_report(function_score=2)
        assert result["status"] == "completed"
        assert "warning" in result

    def test_report_rejects_bool_score(self, server_env):
        srv = server_env["server"]
        result = srv.assessment_report(function_score=True)
        assert "error" in result

    def test_session_mismatch_persisted_to_objective(self, server_env):
        srv = server_env["server"]
        store = server_env["storage"]
        store.schedule_assessment(id="a-1", scheduled_by="user")
        store.conn.execute(
            "UPDATE assessments SET status = 'active', session_id = 'someone-else' "
            "WHERE id = 'a-1'"
        )
        store.conn.commit()

        result = srv.assessment_report(function_score=2)
        assert result["objective"]["session_mismatch"] is True

        row = store.conn.execute(
            "SELECT objective FROM assessments WHERE id = 'a-1'"
        ).fetchone()
        assert json.loads(row["objective"])["session_mismatch"] is True


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
        assert entry["id"] == "a-1"
        assert entry["session_id"] == "s-1"
        assert entry["missing"] == []
        assert entry["completed_at"] is not None

    def test_reflect_assessments_tolerates_corrupt_json(self, tmp_db):
        from reflection import Reflector

        tmp_db.schedule_assessment(id="a-bad", scheduled_by="self")
        tmp_db.conn.execute(
            "UPDATE assessments SET status = 'completed', "
            "self_report = '{not json', objective = '{}', "
            "completed_at = '2026-06-12T00:00:00+00:00' WHERE id = 'a-bad'"
        )
        tmp_db.conn.commit()

        reflector = Reflector(tmp_db, staleness_days=30)
        result = reflector.reflect(focus="assessments")["assessments"]
        assert len(result["history"]) == 1
        assert result["history"][0]["parse_error"] is True
        assert result["counts"]["completed"] == 1
