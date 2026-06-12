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
