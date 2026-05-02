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
