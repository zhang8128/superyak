"""Tests for the sheaf cohesion layer — config, math, gate."""

import numpy as np

import sheaf

from config import load_config


class TestCohesionConfig:
    def test_defaults(self, tmp_path):
        cfg = load_config(tmp_path)
        assert cfg.cohesion.dl_cost == 0.15
        assert cfg.cohesion.variance_threshold == 0.90
        assert cfg.cohesion.max_subspace_dim == 8
        assert cfg.cohesion.min_episodes == 3
        assert cfg.cohesion.sleep_budget == 3

    def test_toml_override(self, tmp_path):
        (tmp_path / ".engram").mkdir()
        (tmp_path / ".engram" / "config.toml").write_text(
            "[cohesion]\ndl_cost = 0.3\nsleep_budget = 1\n")
        cfg = load_config(tmp_path)
        assert cfg.cohesion.dl_cost == 0.3
        assert cfg.cohesion.sleep_budget == 1


def _cluster(center: np.ndarray, n: int, noise: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    pts = center + noise * rng.standard_normal((n, center.shape[0]))
    return pts


def _two_orthogonal(n_per: int = 10, noise: float = 0.05):
    a = np.zeros(768); a[0] = 1.0
    b = np.zeros(768); b[1] = 1.0
    X = np.vstack([_cluster(a, n_per, noise, 1), _cluster(b, n_per, noise, 2)])
    ids = [f"e{i}" for i in range(2 * n_per)]
    return ids, X


class TestLocalSheaf:
    def test_subspace_dimension_bounded(self):
        ids, X = _two_orthogonal()
        ls = sheaf.build_local_sheaf("s1", ids, X, variance_threshold=0.90, max_dim=8)
        assert 2 <= ls.k <= 8
        assert ls.coords.shape == (len(ids), ls.k)


class TestCohesionEnergy:
    def test_conflated_semantic_is_hot(self):
        ids, X = _two_orthogonal()
        ls = sheaf.build_local_sheaf("s1", ids, X)
        res = sheaf.cohesion_energy(ls)
        assert res["energy"] > 0.8

    def test_tight_cluster_is_cool(self):
        a = np.zeros(768); a[0] = 1.0
        X = _cluster(a, 12, 0.05, 3)
        ids = [f"e{i}" for i in range(12)]
        res = sheaf.cohesion_energy(sheaf.build_local_sheaf("s1", ids, X))
        assert res["energy"] < 0.3

    def test_diverse_but_coherent_is_cool_despite_spread(self):
        a = np.zeros(768); a[0] = 1.0
        X = _cluster(a, 30, 0.35, 4)  # high degree, high spread, one mode
        ids = [f"e{i}" for i in range(30)]
        res = sheaf.cohesion_energy(sheaf.build_local_sheaf("s1", ids, X))
        assert res["energy"] < 0.5

    def test_too_few_episodes_trivial(self):
        a = np.zeros(768); a[0] = 1.0
        X = _cluster(a, 2, 0.05, 5)
        res = sheaf.cohesion_energy(sheaf.build_local_sheaf("s1", ["e0", "e1"], X))
        assert res["energy"] == 0.0

    def test_worst_edges_cross_the_conflation(self):
        ids, X = _two_orthogonal()
        res = sheaf.cohesion_energy(sheaf.build_local_sheaf("s1", ids, X))
        # localization: the hottest edges connect the two groups
        for ea, eb, _r in res["worst_edges"][:3]:
            ia, ib = int(ea[1:]), int(eb[1:])
            assert (ia < 10) != (ib < 10)
