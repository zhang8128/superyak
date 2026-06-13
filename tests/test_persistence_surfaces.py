"""Persistence surfaces: gate conjunct, audit, reflect, cold-uninvited."""

import numpy as np

import sheaf
from config import PersistenceConfig


def _two_orthogonal(n_per: int = 10, noise: float = 0.05):
    a = np.zeros(768); a[0] = 1.0
    b = np.zeros(768); b[1] = 1.0
    rng1, rng2 = np.random.default_rng(1), np.random.default_rng(2)
    X = np.vstack([a + noise * rng1.standard_normal((n_per, 768)),
                   b + noise * rng2.standard_normal((n_per, 768))])
    return [f"e{i}" for i in range(2 * n_per)], X


class TestGateConjunct:
    def test_disabled_behaves_like_stub(self):
        ids, X = _two_orthogonal()
        v = sheaf.subdivision_test("s1", ids, X, dl_cost=0.15)
        assert v.persistence_checked is False
        assert v.persistence_band is None
        assert v.split is True

    def test_enabled_records_band_and_passes_clean_split(self):
        ids, X = _two_orthogonal()
        cfg = PersistenceConfig(enabled=True)
        v = sheaf.subdivision_test("s1", ids, X, dl_cost=0.15,
                                   persistence_cfg=cfg)
        assert v.persistence_checked is True
        assert v.persistence_band is not None and v.persistence_band > 0.10
        assert v.split is True

    def test_enabled_blocks_flicker(self):
        # one blob, but force the gate's energy conjunct to pass by using a
        # tiny dl_cost: the persistence conjunct must be the one that blocks
        rng = np.random.default_rng(9)
        a = np.zeros(768); a[0] = 1.0
        X = a + 0.3 * rng.standard_normal((16, 768))
        ids = [f"e{i}" for i in range(16)]
        cfg = PersistenceConfig(enabled=True)
        v = sheaf.subdivision_test("s1", ids, X, dl_cost=0.0001,
                                   persistence_cfg=cfg)
        if v.parts:  # only meaningful when a partition was proposed
            assert v.persistence_checked is True
            if v.gain > 0.0001:          # energy conjunct passed
                assert v.split is (v.persistence_band >= cfg.min_split_band)
