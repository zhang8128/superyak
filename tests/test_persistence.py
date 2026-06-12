"""Tests for the persistence layer — schema, math, scores."""

import json


class TestMigration021:
    def test_table_exists(self, tmp_db):
        names = {r[0] for r in tmp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "persistence_scores" in names


class TestScoreCache:
    def test_upsert_and_get(self, tmp_db):
        tmp_db.upsert_persistence_scores([
            {"episode_id": "e1", "redundancy": 0.9, "uniqueness": 0.1,
             "generativity": 0.0},
            {"episode_id": "e2", "redundancy": 0.2, "uniqueness": 0.8,
             "generativity": 1.5},
        ])
        scores = tmp_db.get_persistence_scores()
        assert scores["e1"]["redundancy"] == 0.9
        assert scores["e2"]["generativity"] == 1.5
        # upsert replaces
        tmp_db.upsert_persistence_scores([
            {"episode_id": "e1", "redundancy": 0.5, "uniqueness": 0.5,
             "generativity": 0.5}])
        assert tmp_db.get_persistence_scores()["e1"]["redundancy"] == 0.5
