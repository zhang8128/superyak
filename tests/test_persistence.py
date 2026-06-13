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


from config import load_config


class TestPersistenceConfig:
    def test_defaults(self, tmp_path):
        cfg = load_config(tmp_path)
        p = cfg.persistence
        assert p.enabled is False
        assert p.min_split_band == 0.10
        assert p.redundancy_floor == 0.85
        assert p.protect_threshold == 0.6
        assert p.generativity_threshold == 0.0
        assert p.cold_uninvited_p == 0.05

    def test_toml_override(self, tmp_path):
        (tmp_path / ".engram").mkdir()
        (tmp_path / ".engram" / "config.toml").write_text(
            "[persistence]\nenabled = true\nredundancy_floor = 0.7\n")
        cfg = load_config(tmp_path)
        assert cfg.persistence.enabled is True
        assert cfg.persistence.redundancy_floor == 0.7
