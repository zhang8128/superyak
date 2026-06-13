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


import numpy as np

import persistence


def _cluster(axis: int, n: int, noise: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    c = np.zeros(768); c[axis] = 1.0
    return c + noise * rng.standard_normal((n, 768))


class TestFiltration:
    def test_duplicate_pair_one_redundant_one_carrier(self):
        base = _cluster(0, 1, 0.0, 1)[0]
        far = np.zeros(768); far[1] = 1.0
        X = np.vstack([base, base + 1e-6, far, far + 0.3 * _cluster(1, 1, 1.0, 2)[0] * 0])
        # points 0,1 are near-duplicates; 2,3 give the filtration room
        f = persistence.build_filtration(X)
        red = persistence.redundancy(f)
        uniq = persistence.uniqueness(f)
        assert red[0] > 0.99 and red[1] > 0.99      # both covered by the other
        assert min(uniq[0], uniq[1]) < 0.05          # one lineage dies instantly
        assert max(uniq[0], uniq[1]) > 0.5           # the carrier persists

    def test_isolated_point_is_unique_not_redundant(self):
        X = np.vstack([_cluster(0, 8, 0.03, 3), _cluster(5, 1, 0.0, 4)])
        f = persistence.build_filtration(X)
        red = persistence.redundancy(f)
        uniq = persistence.uniqueness(f)
        assert red[8] < 0.3
        assert uniq[8] > 0.9

    def test_tiny_inputs(self):
        f0 = persistence.build_filtration(np.zeros((0, 768)))
        assert f0.n == 0
        f1 = persistence.build_filtration(_cluster(0, 1, 0.0, 5))
        assert persistence.uniqueness(f1)[0] == 1.0
        assert persistence.redundancy(f1)[0] == 0.0   # nothing covers it


class TestSplitBand:
    def test_separated_parts_have_wide_band(self):
        a = _cluster(0, 8, 0.03, 6)
        b = _cluster(1, 8, 0.03, 7)
        X = np.vstack([a, b])
        band = persistence.split_band(X, list(range(8)), list(range(8, 16)))
        assert band > 0.3

    def test_arbitrary_cut_of_one_cluster_has_no_band(self):
        X = _cluster(0, 16, 0.05, 8)
        band = persistence.split_band(X, list(range(8)), list(range(8, 16)))
        assert band < 0.05
