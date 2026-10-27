"""H1 of a hub's sources is read over a bounded number of edges (Task 50: ripser reached 14.3 GiB at n = 1,024)."""
import numpy as np
import pytest
from ripser import ripser

import persistence
from persistence import H1_EDGES_PER_POINT, distance_matrix, h1_persistence


def _ring(n, dim=16):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    X = np.zeros((n, dim))
    X[:, 0], X[:, 1] = np.cos(t), np.sin(t)
    return X + 0.5 * np.eye(dim)[2]


def test_a_ring_is_still_looped_when_the_edges_are_bounded():
    X = _ring(120)                       # 7,140 pairs against 16 x 120 = 1,920 edges: the bound applies
    assert 120 * 119 // 2 > H1_EDGES_PER_POINT * 120
    assert h1_persistence(X) >= 0.10


def test_a_small_set_is_read_whole_and_equals_ripser():
    rng = np.random.default_rng(3)
    X = rng.standard_normal((30, 8))     # 435 pairs <= 16 x 30: no threshold
    dgm = ripser(distance_matrix(X), maxdim=1, distance_matrix=True)["dgms"][1]
    finite = dgm[np.isfinite(dgm[:, 1])]
    denom = persistence.build_filtration(X).max_height
    assert h1_persistence(X) == pytest.approx(float(np.max(finite[:, 1] - finite[:, 0])) / denom)


def test_ripser_is_given_at_most_the_bounded_number_of_edges(monkeypatch):
    rng = np.random.default_rng(4)
    n = 300
    X = rng.standard_normal((n, 64))
    seen = {}

    def spy(D, **kw):
        seen["thresh"] = kw.get("thresh")
        seen["edges"] = int((D[np.triu_indices(n, 1)] <= kw["thresh"]).sum())
        return ripser(D, **kw)

    h1_persistence(X, spy)
    assert seen["thresh"] is not None and seen["edges"] <= H1_EDGES_PER_POINT * n


def test_a_bar_alive_at_the_scale_counts_to_it_and_is_finite():
    rng = np.random.default_rng(5)
    h1 = h1_persistence(rng.standard_normal((200, 32)))
    assert h1 is None or np.isfinite(h1)
