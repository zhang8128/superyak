"""The sheaf kernel (sheaf_kernel.c) against the numpy code it came from, against sheaves whose answers are known,
and against input it must refuse. The numpy code in sheaf.py and lighthouse_sheaf.py is the oracle."""
from __future__ import annotations

import itertools
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

import lighthouse_sheaf as ls
import native_build
import sheaf as sh
import sheaf_native as sn

ENGRAM = Path(__file__).resolve().parents[1]


def test_the_kernel_loads_here():
    # Every other test here needs it. Without a C compiler they fail, and this one says why.
    assert sn.available(), sn.why_not()


# --- eigenvalues ------------------------------------------------------------

def symmetric(n: int, seed: int) -> np.ndarray:
    a = np.random.default_rng(seed).standard_normal((n, n))
    return (a + a.T) / 2


def check_decomposition(a: np.ndarray):
    n = len(a)
    w, v = sn.sym_eig(a)
    scale = max(1.0, float(np.abs(a).max()))
    assert np.all(np.diff(w) >= 0)
    assert np.allclose(w, np.linalg.eigvalsh(a), rtol=0, atol=1e-11 * n * scale)
    assert np.allclose(v @ np.diag(w) @ v.T, a, rtol=0, atol=1e-11 * n * scale)
    assert np.allclose(v.T @ v, np.eye(n), rtol=0, atol=1e-11 * n)


@pytest.mark.parametrize("n", [1, 2, 3, 5, 17, 64, 200])
def test_sym_eig_matches_numpy(n):
    check_decomposition(symmetric(n, n))


@pytest.mark.parametrize("name,a", [
    ("zero", np.zeros((6, 6))),
    ("identity", np.eye(7)),
    ("repeated", np.diag([3.0, 3.0, 3.0, -1.0, -1.0, 0.0])),
    ("rank one", np.outer(np.arange(1.0, 9), np.arange(1.0, 9))),
    ("complete graph", 8 * np.eye(8) - np.ones((8, 8))),
    ("tridiagonal", np.diag(np.full(9, 2.0)) - np.diag(np.ones(8), 1) - np.diag(np.ones(8), -1)),
    ("tiny", symmetric(12, 1) * 1e-120),
    ("huge", symmetric(12, 2) * 1e120),
])
def test_sym_eig_on_awkward_matrices(name, a):
    check_decomposition(a)


def test_sym_eig_uses_the_symmetric_part():
    a = np.random.default_rng(3).standard_normal((9, 9))
    w, _ = sn.sym_eig(a)
    assert np.allclose(w, np.linalg.eigvalsh((a + a.T) / 2), atol=1e-11)


# --- principal directions -----------------------------------------------------

def with_spectrum(n: int, d: int, seed: int) -> np.ndarray:
    """An n by d matrix whose singular values fall by 0.6 each time, so every cut between them is a clear one."""
    rng = np.random.default_rng(seed)
    r = min(n, d)
    u, _ = np.linalg.qr(rng.standard_normal((n, r)))
    v, _ = np.linalg.qr(rng.standard_normal((d, r)))
    return u @ np.diag(0.6 ** np.arange(r)) @ v.T


def numpy_k(s: np.ndarray, threshold: float, max_dim: int) -> int:
    var = (s ** 2) / max(float((s ** 2).sum()), 1e-12)
    k = int(np.searchsorted(np.cumsum(var), threshold)) + 1
    return max(min(2, len(s)), min(k, max_dim, len(s)))


@pytest.mark.parametrize("n,d", [(1, 5), (2, 7), (6, 40), (30, 768), (50, 12), (120, 30)])
@pytest.mark.parametrize("threshold", [0.5, 0.9, 0.999])
def test_basis_is_numpys_top_subspace(n, d, threshold):
    x = with_spectrum(n, d, n * 1000 + d)
    rows, sing = sn.basis(x, threshold, 2, 8)
    _, s, vt = np.linalg.svd(x, full_matrices=False)
    k = numpy_k(s, threshold, 8)
    assert len(rows) == k
    assert np.allclose(sing, s, rtol=0, atol=1e-7 * s[0])
    assert np.allclose(rows @ rows.T, np.eye(k), atol=1e-9)
    assert np.allclose(rows.T @ rows, vt[:k].T @ vt[:k], atol=1e-6)  # the same subspace, whatever the signs
    for row in rows:
        assert row[np.argmax(np.abs(row))] > 0  # one sign on every machine


def test_basis_completes_directions_the_data_does_not_have():
    line = np.tile(np.arange(1.0, 8), (5, 1))  # rank one: the second direction is anyone's choice
    rows, sing = sn.basis(line, 0.9, 2, 8)
    assert len(rows) == 2 and sing[1] < 1e-6
    assert np.allclose(rows @ rows.T, np.eye(2), atol=1e-12)
    assert np.allclose(np.abs(rows[0]), np.arange(1.0, 8) / np.linalg.norm(np.arange(1.0, 8)), atol=1e-9)
    nothing, sing = sn.basis(np.zeros((4, 6)), 0.9, 2, 8)
    assert len(nothing) == numpy_k(np.zeros(4), 0.9, 8) == 4  # no prefix reaches the threshold, as in numpy
    assert np.allclose(nothing @ nothing.T, np.eye(4), atol=1e-12) and not sing.any()


# --- cohesion against sheaf.py --------------------------------------------------

def clustered(seed: int):
    rng = np.random.default_rng(seed)
    n, d = int(rng.integers(3, 60)), int(rng.choice([16, 64, 768]))
    centres = rng.standard_normal((3, d))
    label = rng.integers(0, int(rng.integers(1, 4)), n)
    return (centres[label] * rng.uniform(0.5, 3) + rng.standard_normal((n, d)) * rng.uniform(0.2, 1.5)
            + rng.standard_normal(d) * rng.uniform(0, 2))


def oracle_cohesion(x, threshold=0.90, max_dim=8) -> dict:
    return sh.cohesion_energy(sh.build_local_sheaf("s", list(range(len(x))), x, threshold, max_dim))


@pytest.mark.parametrize("seed", range(40))
def test_cohesion_matches_the_numpy_oracle(seed):
    x = clustered(seed)
    got, want = sn.cohesion(x), oracle_cohesion(x)
    assert got["energy"] == pytest.approx(want["energy"], abs=1e-9)
    assert got["lambda2"] == pytest.approx(want["lambda2"], abs=1e-9)
    f, f0 = np.array(got["fiedler"]), np.array(want["fiedler"])
    assert min(np.abs(f - f0).max(), np.abs(f + f0).max()) < 1e-6
    assert f[np.argmax(np.abs(f))] > 0
    assert [r for _, _, r in got["worst"]] == pytest.approx([r for _, _, r in want["worst_edges"]], abs=1e-9)
    # Pairs with equal residuals may come in either order, so each pair is checked against the oracle's own residual.
    local = sh.build_local_sheaf("s", list(range(len(x))), x)
    y = local.coords / (np.linalg.norm(local.coords, axis=1, keepdims=True) + 1e-12)
    w = np.clip(y @ y.T, 0.0, None)
    assert len({(i, j) for i, j, _ in got["worst"]}) == len(got["worst"])
    for i, j, r in got["worst"]:
        assert i < j and r == pytest.approx(w[i, j] * (f0[i] - f0[j]) ** 2, abs=1e-9)


@pytest.mark.parametrize("threshold,max_dim", [(0.5, 8), (0.99, 8), (0.9, 1), (0.9, 2), (0.9, 3), (0.9, 64)])
def test_cohesion_matches_at_other_settings(threshold, max_dim):
    for seed in range(8):
        x = clustered(100 + seed)
        got, want = sn.cohesion(x, threshold, max_dim), oracle_cohesion(x, threshold, max_dim)
        assert got["energy"] == pytest.approx(want["energy"], abs=1e-9)
        assert got["lambda2"] == pytest.approx(want["lambda2"], abs=1e-9)


@pytest.mark.parametrize("n", [1, 2])
def test_cohesion_under_three_episodes_is_trivial(n):
    got = sn.cohesion(np.random.default_rng(n).standard_normal((n, 16)))
    assert got["energy"] == 0.0 and got["lambda2"] is None and got["fiedler"] == [] and got["worst"] == []
    assert sh.measure(np.random.default_rng(n).standard_normal((n, 16)), backend="native")["energy"] == 0.0


def test_an_isolated_episode_is_the_same_answer_as_numpys():
    x = np.zeros((5, 4))
    x[:, 0] = [1, 1, 1, -1, 1]  # the fourth points the other way: no similarity to anyone
    got, want = sn.cohesion(x), oracle_cohesion(x)
    assert (got["energy"], got["lambda2"], got["worst"]) == (1.0, 0.0, [])
    assert (want["energy"], want["lambda2"], want["worst_edges"]) == (1.0, 0.0, [])
    assert got["fiedler"] == want["fiedler"] == [-1.0, -1.0, -1.0, 1.0, -1.0]
    assert sh.measure(x, backend="native") == sh.measure(x, backend="numpy")


def two_topics(seed: int, n: int = 14, d: int = 64, apart: float = 1.0):
    """Two groups of episodes with a common part, as real embeddings have. `apart` 0 makes them one group."""
    rng = np.random.default_rng(seed)
    common, a, b = rng.standard_normal(d), rng.standard_normal(d), rng.standard_normal(d)
    rows = [common + apart * (a if i < n // 2 else b) + 0.15 * rng.standard_normal(d) for i in range(n)]
    return [f"e{i}" for i in range(n)], np.array(rows)


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("apart", [0.0, 0.4, 1.0, 3.0])
def test_the_gate_gives_one_verdict_on_both_backends(seed, apart):
    ids, x = two_topics(seed, apart=apart)
    a = sh.subdivision_test("s", ids, x, dl_cost=0.02, backend="native")
    b = sh.subdivision_test("s", ids, x, dl_cost=0.02, backend="numpy")
    assert a.split == b.split and a.parts == b.parts and a.ambiguous == b.ambiguous
    assert a.energy_before == pytest.approx(b.energy_before, abs=1e-9)
    assert a.gain == pytest.approx(b.gain, abs=1e-9)
    assert a.part_energies == pytest.approx(b.part_energies, abs=1e-9)


def test_the_gate_splits_two_topics_along_their_line_and_leaves_one_alone():
    # A presence control for the measure itself: it must fire on a real conflation, or a pass means nothing.
    ids, x = two_topics(7, apart=3.0)
    verdict = sh.subdivision_test("s", ids, x, dl_cost=0.02, backend="native")
    assert verdict.split
    assert sorted(map(sorted, verdict.parts)) == sorted([sorted(ids[:7]), sorted(ids[7:])])
    ids, x = two_topics(7, apart=0.0)
    assert not sh.subdivision_test("s", ids, x, dl_cost=0.02, backend="native").split


def test_measure_falls_back_to_numpy_when_the_kernel_declines(monkeypatch, caplog):
    x = clustered(5)

    def declined(*args, **kwargs):
        raise sn.SheafKernelError(-9)

    monkeypatch.setattr(sn, "cohesion", declined)
    with caplog.at_level("INFO"):
        assert sh.measure(x)["energy"] == pytest.approx(oracle_cohesion(x)["energy"], abs=1e-12)
    assert "numpy takes this one" in caplog.text
    with pytest.raises(sn.SheafKernelError):
        sh.measure(x, backend="native")  # asked for by name: the refusal is the caller's to see


def test_the_backend_can_be_named_in_the_environment(monkeypatch):
    monkeypatch.setenv("ENGRAM_SHEAF_BACKEND", "numpy")
    assert not sn.chosen()
    monkeypatch.setenv("ENGRAM_SHEAF_BACKEND", "native")
    assert sn.chosen() and sn.insisted()
    monkeypatch.setenv("ENGRAM_SHEAF_BACKEND", "fortran")
    with pytest.raises(ValueError):
        sn.chosen()


# --- the sheaf itself: known answers -------------------------------------------------

def constant_sheaf(edges, n: int, d: int) -> sn.Sheaf:
    s = sn.Sheaf([d] * n)
    for u, v in edges:
        s.add_edge(u, v)
    return s


@pytest.mark.parametrize("name,n,edges,parts", [
    ("path", 5, [(0, 1), (1, 2), (2, 3), (3, 4)], 1),
    ("tree", 6, [(0, 1), (0, 2), (2, 3), (2, 4), (4, 5)], 1),
    ("cycle", 5, [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)], 1),
    ("complete", 4, list(itertools.combinations(range(4), 2)), 1),
    ("two pieces", 6, [(0, 1), (1, 2), (3, 4), (4, 5), (5, 3)], 2),
    ("no edges", 3, [], 3),
])
@pytest.mark.parametrize("d", [1, 3])
def test_a_constant_sheaf_counts_the_graph(name, n, edges, parts, d):
    # H^0 is one copy of the stalk for each piece of the graph, and H^1 one for each independent loop.
    with constant_sheaf(edges, n, d) as s:
        got = s.sections()
    assert got == {"h0": parts * d, "h1": (len(edges) - n + parts) * d}


@pytest.mark.parametrize("n", [3, 4, 7])
def test_a_twist_on_a_cycle_leaves_no_global_section(n):
    with sn.Sheaf([2] * n) as s:
        for i in range(n):
            s.add_edge(i, (i + 1) % n, map_v=-np.eye(2) if i == n - 1 else None)
        assert s.sections() == {"h0": 0, "h1": 0}


def test_an_edge_can_see_part_of_a_stalk():
    # Two vertices with R^2 that only have to agree on the first coordinate: three free numbers are left.
    with sn.Sheaf([2, 2]) as s:
        s.add_edge(0, 1, map_u=[[1.0, 0.0]], map_v=[[1.0, 0.0]])
        assert s.sections() == {"h0": 3, "h1": 0}
        energy, residual = s.energy([5.0, 1.0, 5.0, -9.0])
        assert energy == 0.0 and residual.tolist() == [0.0]
        energy, residual = s.energy([5.0, 1.0, 2.0, -9.0])
        assert energy == 9.0 and residual.tolist() == [9.0]


def test_an_edge_of_no_weight_is_out_of_the_cover_but_still_measured():
    with sn.Sheaf([1, 1, 1]) as s:
        s.add_edge(0, 1, weight=1.0)
        s.add_edge(1, 2, weight=0.0)
        assert s.sections() == {"h0": 2, "h1": 0}  # vertex 2 is free of the others
        energy, residual = s.energy([1.0, 1.0, 4.0])
        assert energy == 0.0 and residual.tolist() == [0.0, 9.0]


def random_sheaf(seed: int):
    """A random sheaf, and its coboundary and weights built separately in numpy."""
    rng = np.random.default_rng(seed)
    nv = int(rng.integers(2, 9))
    dims = [int(v) for v in rng.integers(1, 5, nv)]
    off = np.concatenate([[0], np.cumsum(dims)])
    s, blocks, weights = sn.Sheaf(dims), [], []
    for _ in range(int(rng.integers(1, 16))):
        u, v = (int(t) for t in rng.choice(nv, 2, replace=False))
        dim = int(rng.integers(1, 4))
        mu = None if dim == dims[u] and rng.random() < 0.3 else rng.standard_normal((dim, dims[u]))
        mv = None if dim == dims[v] and rng.random() < 0.3 else rng.standard_normal((dim, dims[v]))
        w = 0.0 if rng.random() < 0.2 else float(rng.uniform(0.1, 2))
        s.add_edge(u, v, map_u=mu, map_v=mv, weight=w, dim=dim)
        block = np.zeros((dim, off[-1]))
        block[:, off[u]:off[u + 1]] = -(np.eye(dim) if mu is None else mu)
        block[:, off[v]:off[v + 1]] = np.eye(dim) if mv is None else mv
        blocks.append(block)
        weights.append(w)
    return s, blocks, weights, rng.standard_normal(off[-1])


@pytest.mark.parametrize("seed", range(40))
def test_a_random_sheaf_matches_numpy(seed):
    s, blocks, weights, x = random_sheaf(seed)
    delta = np.vstack(blocks)
    big_w = np.concatenate([np.full(len(b), w) for b, w in zip(blocks, weights)])
    L = delta.T @ (big_w[:, None] * delta)
    with s:
        assert np.allclose(s.coboundary(x), delta @ x, atol=1e-12)
        assert np.allclose(s.laplacian(), L, atol=1e-12)
        energy, residual = s.energy(x)
        assert energy == pytest.approx(float(x @ L @ x), abs=1e-9)
        assert np.allclose(residual, [float((b @ x) @ (b @ x)) for b in blocks], atol=1e-10)
        got = s.sections(x)
    evals, evecs = np.linalg.eigh(L)
    kernel = evecs[:, evals <= 1e-9 * max(1.0, float(np.abs(evals).max()))]
    in_cover = sum(len(b) for b, w in zip(blocks, weights) if w > 0)
    assert got["h0"] == kernel.shape[1]
    assert got["h1"] == in_cover - (len(x) - kernel.shape[1])
    nearest = kernel @ (kernel.T @ x)
    assert np.allclose(got["section"], nearest, atol=1e-8)
    assert got["harmonic"] == pytest.approx(float(((x - nearest) ** 2).sum() / (x @ x)), abs=1e-8)


# --- glue against lighthouse_sheaf.py -------------------------------------------------

def stores(seed: int):
    rng = np.random.default_rng(seed)
    m, d = int(rng.integers(1, 7)), int(rng.choice([16, 64, 768]))
    topic = rng.standard_normal(d)
    hits, scores, trust = {}, {}, {}
    for i in range(m):
        n = int(rng.integers(1, 9))
        x = topic + rng.standard_normal(d) * rng.uniform(0, 1.5) + rng.standard_normal((n, d)) * 0.2
        hits[f"s{i}"] = x / np.linalg.norm(x, axis=1, keepdims=True)
        scores[f"s{i}"] = rng.uniform(-0.1, 1, n)
        trust[f"s{i}"] = float(rng.choice([0.0, 1.0, rng.uniform(0, 1)], p=[0.1, 0.2, 0.7]))
    return hits, scores, trust


def same_result(a: ls.LighthouseSheafResult, b: ls.LighthouseSheafResult):
    assert (a.covered, a.uncovered, a.k, a.n_hits, a.trust) == (b.covered, b.uncovered, b.k, b.n_hits, b.trust)
    assert (a.kernel_dim, a.glued_dim, a.glued, a.edge_weighting) == (b.kernel_dim, b.glued_dim, b.glued, b.edge_weighting)
    assert a.notes == b.notes
    for field in ("energy", "energy_unweighted", "harmonic_fraction"):
        assert getattr(a, field) == pytest.approx(getattr(b, field), abs=1e-9)
    for field in ("off_basis", "deviations"):
        assert getattr(a, field) == pytest.approx(getattr(b, field), abs=1e-9)
    by_pair = lambda r: {(e["a"], e["b"]): (e["residual"], e["weight"], e["weighted_residual"]) for e in r.edges}
    assert by_pair(a).keys() == by_pair(b).keys()
    for pair, values in by_pair(a).items():
        assert values == pytest.approx(by_pair(b)[pair], abs=1e-9)
    if a.covered:  # the stalks themselves depend on the basis chosen inside the subspace; their inner products don't
        xa, xb = np.array([a.stalks[n] for n in a.covered]), np.array([b.stalks[n] for n in b.covered])
        assert np.allclose(xa @ xa.T, xb @ xb.T, atol=1e-8)
        assert np.linalg.norm(a.consensus) == pytest.approx(np.linalg.norm(b.consensus), abs=1e-8)


@pytest.mark.parametrize("seed", range(60))
def test_glue_matches_the_numpy_oracle(seed):
    hits, scores, trust = stores(seed)
    weighting = "min" if seed % 2 else "product"
    kwargs = dict(scores=scores if seed % 3 else None, trust=trust if seed % 4 else None, edge_weighting=weighting,
                  min_score=0.05 if seed % 5 == 0 else None)
    same_result(ls.glue(hits, backend="native", **kwargs), ls.glue(hits, backend="numpy", **kwargs))


def unit(d: int, *weights: tuple[int, float]) -> np.ndarray:
    v = np.zeros(d)
    for axis, w in weights:
        v[axis] = w
    return v / np.linalg.norm(v)


@pytest.mark.parametrize("name,hits,trust", [
    ("identical", {n: np.tile(unit(32, (0, 1.0), (1, 0.3)), (3, 1)) for n in "abc"}, None),
    ("one store", {"a": np.tile(unit(32, (0, 1.0)), (4, 1))}, None),
    ("one hit each", {"a": unit(32, (0, 1.0))[None], "b": unit(32, (1, 1.0))[None]}, None),
    ("no trust at all", {"a": unit(8, (0, 1.0))[None], "b": unit(8, (1, 1.0))[None]}, {"a": 0.0, "b": 0.0}),
    ("one without trust", {"a": unit(8, (0, 1.0))[None], "b": unit(8, (1, 1.0))[None], "c": unit(8, (2, 1.0))[None]},
     {"a": 0.0}),
    ("a section that cancels", {"a": np.array([unit(8, (0, 1.0)), -unit(8, (0, 1.0))]), "b": unit(8, (1, 1.0))[None]},
     None),
    ("opposite", {"a": unit(8, (0, 1.0))[None], "b": -unit(8, (0, 1.0))[None]}, None),
    ("an uncovered store", {"a": unit(8, (0, 1.0))[None], "b": np.zeros((0, 8)), "c": unit(8, (0, 1.0), (1, 1.0))[None]},
     None),
])
def test_glue_matches_on_edge_cases(name, hits, trust):
    same_result(ls.glue(hits, trust=trust, backend="native"), ls.glue(hits, trust=trust, backend="numpy"))


def test_glue_falls_back_to_numpy_when_the_kernel_declines(monkeypatch):
    hits, scores, trust = stores(3)

    def declined(*args, **kwargs):
        raise sn.SheafKernelError(-9)

    want = ls.glue(hits, scores=scores, trust=trust, backend="numpy")
    monkeypatch.setattr(sn, "glue", declined)
    same_result(ls.glue(hits, scores=scores, trust=trust), want)
    with pytest.raises(sn.SheafKernelError):
        ls.glue(hits, scores=scores, trust=trust, backend="native")


# --- input it must refuse -------------------------------------------------------------

BAD_VALUES = [np.nan, np.inf, -np.inf, 1e200, -1e200]


@pytest.mark.parametrize("bad", BAD_VALUES)
def test_values_that_are_not_finite_or_are_too_far_are_refused(bad):
    a = symmetric(4, 1)
    a[1, 2] = a[2, 1] = bad
    x = np.random.default_rng(2).standard_normal((5, 6))
    x[3, 4] = bad
    for call in (lambda: sn.sym_eig(a), lambda: sn.basis(x), lambda: sn.cohesion(x),
                 lambda: sn.glue([x, x[:2]]), lambda: sn.glue([np.eye(3)], weights=[[1.0, bad, 1.0]])):
        with pytest.raises(sn.SheafKernelError) as refused:
            call()
        assert refused.value.code == -7
    with sn.Sheaf([2, 2]) as s:
        for call in (lambda: s.add_edge(0, 1, weight=bad), lambda: s.add_edge(0, 1, map_u=[[1.0, bad], [0.0, 1.0]]),
                     lambda: s.energy([1.0, bad, 0.0, 0.0]), lambda: s.coboundary([1.0, bad, 0.0, 0.0]),
                     lambda: s.sections([1.0, bad, 0.0, 0.0])):
            with pytest.raises(sn.SheafKernelError):
                call()
        assert s.edges == 0 and s.n1 == 0  # a refused edge leaves nothing behind


def test_sizes_past_the_limits_are_refused_before_any_work():
    with pytest.raises(sn.SheafKernelError) as refused:
        sn.sym_eig(np.zeros((sn.MAX_N + 1, sn.MAX_N + 1)))
    assert refused.value.code == -9
    with pytest.raises(sn.SheafKernelError):
        sn.cohesion(np.ones((sn.MAX_N + 1, 3)))
    with pytest.raises(sn.SheafKernelError):
        sn.basis(np.zeros((2, sn.MAX_COLS + 1)))
    with pytest.raises(sn.SheafKernelError):
        sn.basis(np.zeros((sn.MAX_N + 1, sn.MAX_N + 1)))  # neither side is small enough to decompose
    with pytest.raises(sn.SheafKernelError):
        sn.Sheaf([sn.MAX_STALK] * 9)  # C^0 would pass the limit
    with pytest.raises(ValueError):
        sn.Sheaf([sn.MAX_STALK + 1])


@pytest.mark.parametrize("call", [
    lambda: sn.sym_eig(np.zeros((2, 3))), lambda: sn.sym_eig(np.zeros(4)), lambda: sn.sym_eig(np.zeros((0, 0))),
    lambda: sn.sym_eig([["a", "b"], ["c", "d"]]),
    lambda: sn.basis(np.zeros((0, 4))), lambda: sn.basis(np.eye(3), max_dim=0), lambda: sn.basis(np.eye(3), min_dim=True),
    lambda: sn.basis(np.eye(3), max_dim=2.0), lambda: sn.cohesion(np.eye(3), max_worst=-1),
    lambda: sn.cohesion(np.eye(3), max_dim=sn.MAX_STALK + 1),
    lambda: sn.glue([]), lambda: sn.glue([np.eye(3), np.eye(4)]), lambda: sn.glue([np.eye(3)], weights=[[1.0, 1.0]]),
    lambda: sn.glue([np.eye(3)], trust=[1.0, 1.0]), lambda: sn.glue([np.eye(3)], edge_weighting="sum"),
    lambda: sn.Sheaf([]), lambda: sn.Sheaf([0]), lambda: sn.Sheaf([2.5]),
])
def test_arguments_of_the_wrong_shape_or_kind_never_reach_the_kernel(call):
    with pytest.raises((ValueError, TypeError)):
        call()


def test_trust_outside_zero_to_one_is_refused():
    for trust in ([1.5, 1.0], [-0.1, 1.0], [np.nan, 1.0]):
        with pytest.raises(sn.SheafKernelError):
            sn.glue([np.eye(3), np.eye(3)], trust=trust)


def test_a_sheaf_refuses_what_is_not_an_edge_and_what_comes_after_closing():
    s = sn.Sheaf([2, 3])
    for call in (lambda: s.add_edge(0, 0), lambda: s.add_edge(0, 2), lambda: s.add_edge(-1, 1),
                 lambda: s.add_edge(0, 1),  # an identity between R^2 and R^3
                 lambda: s.add_edge(0, 1, map_u=np.ones((2, 3))),  # a map with the wrong number of columns
                 lambda: s.add_edge(0, 1, map_u=np.ones((1, 2)), map_v=np.ones((2, 3))),  # two different edge stalks
                 lambda: s.energy([1.0, 2.0])):
        with pytest.raises(ValueError):
            call()
    assert s.add_edge(0, 1, map_u=np.ones((1, 2)), map_v=np.ones((1, 3))) == 0
    s.close()
    s.close()
    with pytest.raises(ValueError):
        s.sections()


# --- the same kernel under the sanitizers --------------------------------------------

def test_the_kernel_checks_itself_under_the_sanitizers(tmp_path):
    """Builds tests/sheaf_kernel_check.c, which includes the kernel, with the address and undefined-behaviour
    sanitizers, and runs it. A compiler that can't build with them skips this; a run that reports anything fails."""
    cc = native_build.compiler()
    out = tmp_path / "sheaf_kernel_check"
    flags = ["-std=c11", "-g", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=undefined",
             "-fno-omit-frame-pointer", "-ffp-contract=off", "-Wall", "-Wextra", "-Werror"]
    plain = subprocess.run([cc, "-std=c11", "-O1", "-ffp-contract=off", "-Wall", "-Wextra", "-Werror",
                            str(ENGRAM / "tests" / "sheaf_kernel_check.c"), "-o", str(out), "-lm"],
                           capture_output=True, text=True, env=native_build.BUILD_ENV)
    assert plain.returncode == 0, plain.stderr  # it builds cleanly with no sanitizer, so a failure below is the sanitizers'
    built = subprocess.run([cc, *flags, str(ENGRAM / "tests" / "sheaf_kernel_check.c"), "-o", str(out), "-lm"],
                           capture_output=True, text=True, env=native_build.BUILD_ENV)
    if built.returncode != 0:
        pytest.skip(f"{cc} can't build with the sanitizers here: {built.stderr.strip()[-300:]}")
    ran = subprocess.run([str(out)], capture_output=True, text=True, timeout=300, env={"PATH": "/usr/bin:/bin"})
    assert ran.returncode == 0 and ran.stdout.startswith("ok: "), ran.stdout + ran.stderr
    assert "runtime error" not in ran.stderr and "AddressSanitizer" not in ran.stderr


def test_the_test_only_library_must_be_this_users_own(tmp_path, monkeypatch):
    loose = tmp_path / "loose.so"
    loose.write_bytes(b"")
    loose.chmod(0o777)
    with pytest.raises(RuntimeError, match="writable by nobody else"):
        native_build.private(loose, "library", "sheaf")
    link = tmp_path / "link.so"
    os.symlink(loose, link)
    with pytest.raises(RuntimeError):
        native_build.private(link, "library", "sheaf")
