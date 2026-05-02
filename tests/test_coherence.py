"""Tests for the coherence layer — anchors, drift detection, unchallenged instincts."""

import uuid
from pathlib import Path

from storage import Storage

MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


def _make_storage(tmp_path):
    db_path = str(tmp_path / "test_coherence.db")
    return Storage(db_path, migrations_dir=MIGRATIONS_DIR)


def _fake_emb(dim=768, seed=42):
    import random
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(dim)]


class TestMigration:
    def test_anchors_table_exists(self, tmp_path):
        store = _make_storage(tmp_path)
        row = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='anchors'"
        ).fetchone()
        assert row is not None
        store.close()

    def test_drift_reports_table_exists(self, tmp_path):
        store = _make_storage(tmp_path)
        row = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='drift_reports'"
        ).fetchone()
        assert row is not None
        store.close()


class TestAnchorCRUD:
    def test_add_anchor(self, tmp_path):
        store = _make_storage(tmp_path)
        aid = store.add_anchor(
            type="identity",
            content="Who is Kairos?",
            expected="ep-core-001",
            baseline_score=0.92,
        )
        assert aid is not None
        anchor = store.get_anchor(aid)
        assert anchor["type"] == "identity"
        assert anchor["content"] == "Who is Kairos?"
        assert anchor["expected"] == "ep-core-001"
        assert anchor["baseline_score"] == 0.92
        assert anchor["status"] == "active"
        store.close()

    def test_get_active_anchors(self, tmp_path):
        store = _make_storage(tmp_path)
        store.add_anchor(type="identity", content="q1", expected="e1", baseline_score=0.9)
        store.add_anchor(type="value", content="q2", expected="rubric1")
        store.add_anchor(type="capability", content="q3", expected="rubric2")
        active = store.get_active_anchors()
        assert len(active) == 3
        assert {a["type"] for a in active} == {"identity", "value", "capability"}
        store.close()

    def test_get_anchors_by_type(self, tmp_path):
        store = _make_storage(tmp_path)
        store.add_anchor(type="identity", content="q1", expected="e1", baseline_score=0.9)
        store.add_anchor(type="identity", content="q2", expected="e2", baseline_score=0.8)
        store.add_anchor(type="value", content="q3", expected="rubric")
        identity_anchors = store.get_active_anchors(anchor_type="identity")
        assert len(identity_anchors) == 2
        store.close()

    def test_update_anchor_result(self, tmp_path):
        store = _make_storage(tmp_path)
        aid = store.add_anchor(type="identity", content="q1", expected="e1", baseline_score=0.9)
        store.update_anchor_result(aid, '{"status": "pass", "score": 0.88}')
        anchor = store.get_anchor(aid)
        assert anchor["last_result"] == '{"status": "pass", "score": 0.88}'
        assert anchor["last_checked"] is not None
        store.close()

    def test_propose_retirement(self, tmp_path):
        store = _make_storage(tmp_path)
        aid = store.add_anchor(type="identity", content="q1", expected="e1", baseline_score=0.9)
        store.propose_anchor_retirement(aid)
        anchor = store.get_anchor(aid)
        assert anchor["status"] == "proposed_retirement"
        assert anchor["retirement_sessions"] == 1
        store.close()

    def test_retirement_after_two_sessions(self, tmp_path):
        store = _make_storage(tmp_path)
        aid = store.add_anchor(type="identity", content="q1", expected="e1", baseline_score=0.9)
        store.propose_anchor_retirement(aid)
        store.propose_anchor_retirement(aid)
        anchor = store.get_anchor(aid)
        assert anchor["status"] == "retired"
        store.close()

    def test_retired_anchors_not_in_active(self, tmp_path):
        store = _make_storage(tmp_path)
        aid = store.add_anchor(type="identity", content="q1", expected="e1", baseline_score=0.9)
        store.propose_anchor_retirement(aid)
        store.propose_anchor_retirement(aid)
        active = store.get_active_anchors()
        assert len(active) == 0
        store.close()
