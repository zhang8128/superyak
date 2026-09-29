from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

import numpy as np
import pytest

import paths
from storage import Storage

ENGRAM = Path(__file__).resolve().parents[1]
rng = np.random.default_rng(7)


def close(a, b, tol=1e-10):
    return all(np.allclose(x, y, atol=tol) for x, y in zip(a, b))


def random_path(n=6, d=3, seed=0):
    return np.random.default_rng(seed).normal(size=(n, d))


# ── mathematical properties ──────────────────────────────────────────────

def test_level_one_is_total_increment():
    P = random_path()
    sig = paths.signature(P)
    assert np.allclose(paths.increment(sig), P[-1] - P[0])
    assert [s.shape for s in sig] == [(3,), (3, 3), (3, 3, 3)]


def test_segment_signature_is_tensor_exponential():
    h = np.array([0.3, -1.2])
    s = paths.signature(np.stack([np.zeros(2), h]))
    assert np.allclose(s[1], np.outer(h, h) / 2)
    assert np.allclose(s[2], np.einsum("i,j,k->ijk", h, h, h) / 6)


def test_chens_identity():
    P = random_path(8, 3, seed=1)
    a, b = P[:5], P[4:]  # b starts where a ends
    assert close(paths.signature(P),
                 paths.tensor_product(paths.signature(a), paths.signature(b)))


def test_level_two_matches_iterated_integral_brute_force():
    """S2_ij = ∫∫_{s<t} dx_i dx_j, approximated on a fine subdivision."""
    P = random_path(4, 2, seed=2)
    fine = np.concatenate([np.linspace(P[i], P[i + 1], 400, endpoint=False)
                           for i in range(len(P) - 1)] + [P[-1:]])
    dx = np.diff(fine, axis=0)
    x = fine[:-1] - fine[0]
    brute = x.T @ dx + 0.5 * dx.T @ dx  # exact for the linear interpolation
    assert np.allclose(paths.signature(P)[1], brute, atol=1e-8)


def test_reversal_is_inverse():
    P = random_path(7, 3, seed=3)
    s, r = paths.signature(P), paths.signature(P[::-1])
    ident = paths.identity(3)
    assert close(paths.tensor_product(s, r), ident)
    assert close(paths.tensor_product(r, s), ident)
    assert close(paths.inverse(s), r)


def test_levy_area_and_increment_flip_on_reversal():
    P = random_path(5, 3, seed=4)
    s, r = paths.signature(P), paths.signature(P[::-1])
    assert np.allclose(paths.increment(r), -paths.increment(s))
    assert np.allclose(paths.levy_area(r), -paths.levy_area(s))
    assert np.abs(paths.levy_area(s)).max() > 1e-3


def test_reparametrization_invariance():
    P = random_path(5, 3, seed=5)
    base = paths.signature(P)
    duplicated = np.insert(P, 2, P[2], axis=0)
    midpoint = np.insert(P, 3, (P[2] + P[3]) / 2, axis=0)
    thirds = np.insert(P, 1, [P[0] + (P[1] - P[0]) / 3, P[0] + 2 * (P[1] - P[0]) / 3], axis=0)
    for Q in (duplicated, midpoint, thirds):
        assert close(paths.signature(Q), base)


def test_translation_invariance():
    P = random_path(5, 3, seed=6)
    assert close(paths.signature(P), paths.signature(P + 10.0))


def test_triangle_loop_zero_increment_nonzero_area():
    loop = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])  # counter-clockwise
    s = paths.signature(loop)
    assert np.allclose(paths.increment(s), 0.0)
    A = paths.levy_area(s)
    assert A[0, 1] == pytest.approx(0.5)
    assert A[1, 0] == pytest.approx(-0.5)
    assert paths.levy_area(paths.signature(loop[::-1]))[0, 1] == pytest.approx(-0.5)
    t = paths.trajectory_from_points("loop", loop)
    assert t.tortuosity == float("inf")


def test_tortuosity_straight_and_detour():
    straight = paths.trajectory_from_points("s", [[0, 0], [1, 0], [2, 0]])
    detour = paths.trajectory_from_points("d", [[0, 0], [1, 1], [2, 0]])
    assert straight.tortuosity == pytest.approx(1.0)
    assert detour.tortuosity == pytest.approx(np.sqrt(2))


def test_back_and_forth_is_invisible_without_time_but_seen_with_it():
    A, B = np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
    basis = paths.Basis(np.zeros(3), np.eye(3), 1.0, 3)
    there_and_back = np.stack([A, B, A])
    stay = np.stack([A, A, A])
    flat = [paths.signature_of_vectors(v, basis, time_augment=False)
            for v in (there_and_back, stay)]
    timed = [paths.signature_of_vectors(v, basis, time_augment=True)
             for v in (there_and_back, stay)]
    assert paths.signature_distance(*flat) < 1e-10
    assert paths.signature_distance(*timed) > 1e-2


def test_basepoint_makes_signature_see_start():
    basis = paths.Basis(np.zeros(2), np.eye(2), 1.0, 2)
    a = np.array([[1.0, 0.0], [0.0, 1.0]])
    b = np.array([[0.0, -1.0], [-1.0, 0.0]])  # unit vectors: same increment, different start
    sa = paths.signature_of_vectors(a, basis, time_augment=False, basepoint=True)
    assert np.allclose(paths.increment(sa), basis.project(a)[-1])
    flat = [paths.signature_of_vectors(v, basis, time_augment=False) for v in (a, b)]
    assert np.allclose(paths.increment(flat[0]), paths.increment(flat[1]))
    sb = paths.signature_of_vectors(b, basis, time_augment=False, basepoint=True)
    assert paths.signature_distance(sa, sb) > 0.1


def test_fit_basis_is_centered_orthonormal_and_shared_check():
    X = rng.normal(size=(40, 20))
    b = paths.fit_basis(X, d=6)
    assert b.dim == 6
    assert np.allclose(b.components @ b.components.T, np.eye(6))
    assert np.allclose(b.project(X).mean(axis=0), 0.0, atol=1e-10)
    other = paths.fit_basis(rng.normal(size=(40, 20)), d=6)
    t1 = paths.build_trajectory("a", list("abc"), X[:3], b)
    t2 = paths.build_trajectory("b", list("abc"), X[3:6], other)
    with pytest.raises(ValueError):
        paths.signature_distance(t1, t2)
    with pytest.raises(ValueError):
        paths.different_routes([t1, t2])


def test_signature_distance_invariant_to_basis_rotation():
    P, Q = random_path(5, 3, seed=8), random_path(5, 3, seed=9)
    R, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    d0 = paths.signature_distance(paths.signature(P), paths.signature(Q))
    d1 = paths.signature_distance(paths.signature(P @ R.T), paths.signature(Q @ R.T))
    assert d0 == pytest.approx(d1)


def test_different_routes_same_endpoints():
    upper = paths.trajectory_from_points("upper", [[0, 0], [0, 1], [1, 1]])
    lower = paths.trajectory_from_points("lower", [[0, 0], [1, 0], [1, 1]])
    lower_again = paths.trajectory_from_points("lower-again", [[0, 0], [0.5, 0], [1, 0], [1, 1]])
    elsewhere = paths.trajectory_from_points("elsewhere", [[0, 0], [3, 0], [3, 3]])
    found = paths.different_routes([upper, lower, lower_again, elsewhere])
    pairs = {frozenset((f["a"], f["b"])) for f in found}
    assert frozenset(("upper", "lower")) in pairs
    assert frozenset(("upper", "lower-again")) in pairs
    assert frozenset(("lower", "lower-again")) not in pairs  # same route, resampled
    assert not any("elsewhere" in p for p in pairs)
    hit = next(f for f in found if {f["a"], f["b"]} == {"upper", "lower"})
    assert hit["endpoint_gap"] == pytest.approx(0.0)
    assert np.allclose(paths.increment(upper.signature), paths.increment(lower.signature))


def test_different_routes_ignores_identical():
    a = paths.trajectory_from_points("a", [[0, 0], [1, 2], [2, 0]])
    b = paths.trajectory_from_points("b", [[0, 0], [1, 2], [2, 0]])
    assert paths.different_routes([a, b]) == []


# ── store integration ────────────────────────────────────────────────────

def _vec(seed: int) -> list[float]:
    v = np.random.default_rng(seed).normal(size=768)
    return (v / np.linalg.norm(v)).tolist()


def build_store(path: Path) -> dict:
    store = Storage(str(path))
    ids = {}
    # (session, label, day, has_vector) — inserted out of order on purpose
    plan = [("s1", "c", 3, True), ("s1", "a", 1, True), ("s1", "nv", 2, False),
            ("s1", "b", 2, True), ("s1", "d", 4, True),
            ("s2", "y", 6, True), ("s2", "x", 5, True), ("s2", "z", 7, True),
            ("s3", "p", 8, True), ("s3", "q", 9, True)]
    for i, (session, label, day, has_vec) in enumerate(plan):
        eid = str(uuid.uuid4())
        ids[label] = eid
        store.add_episode(eid, session, f"thought {label}",
                          embedding=_vec(i) if has_vec else None)
        store.conn.execute("UPDATE episodes SET created_at = ? WHERE id = ?",
                           (f"2026-01-{day:02d}T00:00:00", eid))
    store.conn.commit()
    ids["sem"] = str(uuid.uuid4())
    store.add_semantic(ids["sem"], "a conclusion", "fact", 0.9, _vec(99),
                       [ids["d"], ids["x"], ids["a"], ids["nv"]])
    store.close()
    return ids


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_session_paths_and_semantic_journey(tmp_path):
    db = tmp_path / "graph.db"
    ids = build_store(db)
    conn = paths.connect_ro(db)
    try:
        sp = paths.session_paths(conn)
        assert set(sp) == {"s1", "s2"}  # s3 has only two vectorized episodes
        assert sp["s1"].ids == [ids[k] for k in "abcd"]  # time order, unvectorized skipped
        assert sp["s2"].ids == [ids[k] for k in "xyz"]
        assert sp["s1"].basis is sp["s2"].basis
        assert sp["s1"].basis.n_fit == 7
        assert sp["s1"].stream.shape == (4, 7)  # d=6 + time
        assert np.allclose(sp["s1"].stream[:, -1], [0, 1 / 3, 2 / 3, 1])
        assert paths.signature_distance(sp["s1"], sp["s2"]) > 0

        j = paths.semantic_journey(conn, ids["sem"])
        assert j.ids == [ids["a"], ids["d"], ids["x"]]
        shared = paths.semantic_journey(conn, ids["sem"], basis=sp["s1"].basis)
        assert shared.basis is sp["s1"].basis
        assert paths.semantic_journey(conn, "missing") is None

        # the pure function agrees with the store path
        vecs = [_vec(1), _vec(3), _vec(0), _vec(4)]
        assert close(paths.signature_of_vectors(vecs, sp["s1"].basis), sp["s1"].signature, 1e-5)
        assert conn.total_changes == 0
    finally:
        conn.close()


def test_cli_is_read_only(tmp_path):
    db = tmp_path / "graph.db"
    build_store(db)
    before = sha(db)
    out = subprocess.run([sys.executable, "paths.py", str(db), "--json"],
                         cwd=ENGRAM, capture_output=True, text=True, check=True)
    r = json.loads(out.stdout)
    assert r["sessions_with_paths"] == 2
    assert r["sessions_total"] == 3
    assert r["changes"] == 0
    assert len(r["most_tortuous"]) == 2
    text = subprocess.run([sys.executable, "paths.py", str(db)],
                          cwd=ENGRAM, capture_output=True, text=True, check=True)
    assert "most tortuous" in text.stdout
    assert sha(db) == before


def test_cli_refuses_missing_file(tmp_path, capsys):
    missing = tmp_path / "absent.db"
    assert paths.main([str(missing)]) == 1
    assert not missing.exists()
