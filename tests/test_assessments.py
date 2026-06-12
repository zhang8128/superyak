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
