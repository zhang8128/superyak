"""Path signatures (Layer 5, Dynamics) — a session as a path, not a bag.

The store keeps saying "I inherit the conclusions without the journey". A
bag of episodes forgets order; a path does not. The truncated signature of
a path (iterated integrals, levels 1..3) is an order-aware summary: level 1
is the net displacement, level 2 carries the signed (Lévy) area — which way
the path turned — and level 3 the finer shape. Two sessions that end in the
same place by different routes share level 1 and differ above it.

Computed exactly for piecewise-linear paths by Chen's identity: a linear
segment with increment h has signature exp(h) = (h, h⊗h/2!, h⊗h⊗h/3!), and
concatenation is the truncated tensor product. Levels are a list of arrays
of shape (d,), (d, d), (d, d, d); level 0 (the scalar 1) is implicit.

Embeddings (768-d) become paths in a low-dimensional PCA basis. Comparison
is only meaningful on a shared basis: each fit picks its own axes, so two
paths projected separately live in different coordinate systems.

Observational only: nothing here writes or gates anything. Read-only CLI:
``python paths.py /path/to/copy-of-graph.db [--json]``.

Spec: docs/superpowers/specs/2026-09-29-path-signatures-design.md
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_EPS = 1e-12
DEFAULT_DEPTH = 3
DEFAULT_DIM = 6


def _unpack_embedding(blob: bytes) -> np.ndarray:
    return np.array(struct.unpack(f"<{len(blob) // 4}f", blob), dtype=np.float64)


# ── tensor algebra (truncated) ───────────────────────────────────────────

def identity(d: int, depth: int = DEFAULT_DEPTH) -> list[np.ndarray]:
    """Signature of a constant path: every level zero."""
    return [np.zeros((d,) * k) for k in range(1, depth + 1)]


def segment_signature(h, depth: int = DEFAULT_DEPTH) -> list[np.ndarray]:
    """Tensor exponential of an increment: level k is h^{⊗k} / k!."""
    h = np.asarray(h, dtype=np.float64)
    out, term = [], np.ones(())
    for k in range(1, depth + 1):
        term = np.multiply.outer(term, h)
        out.append(term / math.factorial(k))
    return out


def tensor_product(a: list[np.ndarray], b: list[np.ndarray]) -> list[np.ndarray]:
    """Truncated product of two group-like elements (level 0 = 1 on both).

    (a⊗b)_k = a_k + b_k + Σ_{0<i<k} a_i ⊗ b_{k-i}  — Chen's identity when a
    and b are the signatures of consecutive pieces of one path.
    """
    if len(a) != len(b):
        raise ValueError("signatures truncated at different depths")
    out = []
    for k in range(1, len(a) + 1):
        t = a[k - 1] + b[k - 1]
        for i in range(1, k):
            t = t + np.multiply.outer(a[i - 1], b[k - i - 1])
        out.append(t)
    return out


def inverse(sig: list[np.ndarray]) -> list[np.ndarray]:
    """Truncated inverse: y_k = -Σ_{1≤i≤k} x_i ⊗ y_{k-i}, y_0 = 1.

    For a signature this equals the signature of the reversed path.
    """
    y: list[np.ndarray] = []
    for k in range(1, len(sig) + 1):
        t = -sig[k - 1]
        for i in range(1, k):
            t = t - np.multiply.outer(sig[i - 1], y[k - i - 1])
        y.append(t)
    return y


def signature(points, depth: int = DEFAULT_DEPTH) -> list[np.ndarray]:
    """Exact truncated signature of the piecewise-linear path through points.

    Invariant to reparametrization: repeated points (zero increments) and
    subdivided segments leave it unchanged. Translation-invariant.
    """
    P = np.asarray(points, dtype=np.float64)
    if P.ndim != 2:
        raise ValueError("points must be an (n, d) array")
    sig = identity(P.shape[1], depth)
    for h in np.diff(P, axis=0):
        if not h.any():
            continue  # exp(0) is the identity
        sig = tensor_product(sig, segment_signature(h, depth))
    return sig


def increment(sig: list[np.ndarray]) -> np.ndarray:
    """Level 1: the total increment (end - start)."""
    return sig[0]


def levy_area(sig: list[np.ndarray]) -> np.ndarray:
    """Antisymmetric part of level 2: A_ij = ½∫(x_i dx_j − x_j dx_i).

    For a closed planar loop A_01 is the signed enclosed area (positive
    counter-clockwise). The symmetric part of level 2 is ½ h⊗h, determined
    by level 1, so the area is all level 2 adds.
    """
    S2 = sig[1]
    return 0.5 * (S2 - S2.T)


# ── embeddings → paths ───────────────────────────────────────────────────

@dataclass
class Basis:
    """Centered PCA basis over L2-normalized embeddings.

    Centered, unlike sheaf.py's uncentered subspace: signatures are
    translation-invariant, so the common mean direction carries no route
    information, and an uncentered SVD would spend its first axis on it.
    Component signs are fixed (largest-magnitude entry positive) for
    reproducibility; signature distances are invariant to that choice anyway
    (level k transforms by Q^{⊗k}, which is orthogonal).
    """
    mean: np.ndarray            # (D,)
    components: np.ndarray      # (k, D), orthonormal rows
    explained: float            # fraction of centered variance captured
    n_fit: int

    @property
    def dim(self) -> int:
        return int(self.components.shape[0])

    def project(self, vectors) -> np.ndarray:
        X = np.asarray(vectors, dtype=np.float64)
        if X.ndim == 1:
            X = X[None, :]
        Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + _EPS)
        return (Xn - self.mean) @ self.components.T


def fit_basis(vectors, d: int = DEFAULT_DIM, center: bool = True) -> Basis:
    X = np.asarray(vectors, dtype=np.float64)
    if X.ndim != 2 or len(X) < 2:
        raise ValueError("a basis needs at least two vectors")
    Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + _EPS)
    mean = Xn.mean(axis=0) if center else np.zeros(Xn.shape[1])
    _, s, Vt = np.linalg.svd(Xn - mean, full_matrices=False)
    rank = int((s > s[0] * 1e-10).sum()) if len(s) and s[0] > _EPS else 0
    k = max(1, min(d, rank))
    comps = Vt[:k].copy()
    idx = np.argmax(np.abs(comps), axis=1)
    comps *= np.sign(comps[np.arange(k), idx])[:, None]
    total = float((s ** 2).sum())
    explained = float((s[:k] ** 2).sum() / total) if total > _EPS else 1.0
    return Basis(mean, comps, explained, len(X))


def _same_basis(a: Basis, b: Basis) -> bool:
    if a is b:
        return True
    return (a.components.shape == b.components.shape
            and np.allclose(a.components, b.components)
            and np.allclose(a.mean, b.mean))


def _stream(coords: np.ndarray, time_augment: bool, basepoint: bool) -> np.ndarray:
    """Coordinates → the stream whose signature is taken."""
    n = len(coords)
    S = coords
    if time_augment:
        t = np.linspace(0.0, 1.0, n) if n > 1 else np.zeros(1)
        S = np.hstack([S, t[:, None]])
    if basepoint:
        S = np.vstack([np.zeros((1, S.shape[1])), S])
    return S


def signature_of_vectors(vectors, basis: Basis, depth: int = DEFAULT_DEPTH,
                         time_augment: bool = True,
                         basepoint: bool = False) -> list[np.ndarray]:
    """Pure: ordered embeddings → signature in ``basis``.

    Time augmentation appends the step index normalized to [0, 1] so an
    excursion that returns (A→B→A) is not erased as tree-like; a basepoint
    prepends the origin so the signature also sees where the path starts.
    """
    coords = basis.project(vectors)
    return signature(_stream(coords, time_augment, basepoint), depth)


def _path_length(P: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum()) if len(P) > 1 else 0.0


@dataclass
class Trajectory:
    """An ordered path: spatial coordinates, the augmented stream, its signature."""
    key: str
    ids: list[str]
    coords: np.ndarray               # (n, k) projected points, no augmentation
    stream: np.ndarray               # what the signature is taken of
    signature: list[np.ndarray]
    basis: Basis | None = None
    meta: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.coords)

    @property
    def length(self) -> float:
        return _path_length(self.coords)

    @property
    def displacement(self) -> float:
        if self.n < 2:
            return 0.0
        return float(np.linalg.norm(self.coords[-1] - self.coords[0]))

    @property
    def tortuosity(self) -> float:
        """Path length / displacement: 1 = straight, inf = returned home."""
        disp = self.displacement
        if disp <= _EPS:
            return math.inf if self.length > _EPS else 1.0
        return self.length / disp

    def area(self) -> float:
        """Lévy-area magnitude, normalized by squared stream length (scale-free)."""
        L = _path_length(self.stream)
        if L <= _EPS:
            return 0.0
        return float(np.linalg.norm(levy_area(self.signature)) / L ** 2)


def trajectory_from_points(key: str, points, depth: int = DEFAULT_DEPTH,
                           ids: list[str] | None = None,
                           basis: Basis | None = None) -> Trajectory:
    """A trajectory over explicit coordinates (no projection, no augmentation)."""
    P = np.asarray(points, dtype=np.float64)
    return Trajectory(key, ids or [str(i) for i in range(len(P))], P, P,
                      signature(P, depth), basis)


def build_trajectory(key: str, ids: list[str], vectors, basis: Basis,
                     depth: int = DEFAULT_DEPTH, time_augment: bool = True,
                     basepoint: bool = False, meta: dict | None = None) -> Trajectory:
    coords = basis.project(vectors)
    stream = _stream(coords, time_augment, basepoint)
    return Trajectory(key, list(ids), coords, stream, signature(stream, depth),
                      basis, meta or {})


def signature_distance(a, b, levels: list[int] | None = None) -> float:
    """√Σ_k ‖a_k − b_k‖²_F over ``levels`` (1-indexed; default all).

    Accepts two Trajectories (whose bases must be shared) or two level lists
    (whose caller is responsible for a shared basis).
    """
    if isinstance(a, Trajectory) and isinstance(b, Trajectory):
        if a.basis is not None and b.basis is not None and not _same_basis(a.basis, b.basis):
            raise ValueError("trajectories projected into different bases; "
                             "signatures are not comparable")
        a, b = a.signature, b.signature
    if len(a) != len(b) or any(x.shape != y.shape for x, y in zip(a, b)):
        raise ValueError("signatures differ in depth or dimension")
    ks = levels or list(range(1, len(a) + 1))
    return float(math.sqrt(sum(float(np.sum((a[k - 1] - b[k - 1]) ** 2)) for k in ks)))


# ── same destination, different route ───────────────────────────────────

def different_routes(paths, endpoint_tol: float = 0.25, min_route: float = 0.05,
                     top: int = 10) -> list[dict]:
    """Pairs that start and end close together but travel differently.

    Per pair, with L the mean stream length (so the test is scale-free):
      endpoint_gap = max(‖Δstart‖, ‖Δend‖) / L      (hence level 1 close)
      route_gap    = √(‖ΔS₂‖²/L⁴ + ‖ΔS₃‖²/L⁶)       (levels above 1)
    A pair is reported when endpoint_gap ≤ endpoint_tol and route_gap ≥
    min_route, most different route first. Identical routes have route_gap 0.
    """
    paths = list(paths.values()) if isinstance(paths, dict) else list(paths)
    if len(paths) < 2:
        return []
    ref = paths[0]
    for p in paths[1:]:
        if (p.basis is None) != (ref.basis is None) or (
                p.basis is not None and not _same_basis(p.basis, ref.basis)):
            raise ValueError("different_routes needs every path on one shared basis")
        if p.stream.shape[1] != ref.stream.shape[1] or len(p.signature) != len(ref.signature):
            raise ValueError("paths differ in dimension or depth")
    depth = len(ref.signature)
    starts = np.stack([p.stream[0] for p in paths])
    ends = np.stack([p.stream[-1] for p in paths])
    lengths = np.array([_path_length(p.stream) for p in paths])
    higher = [np.stack([p.signature[k].ravel() for p in paths]) for k in range(1, depth)]
    found = []
    for i in range(len(paths) - 1):
        j = np.arange(i + 1, len(paths))
        L = 0.5 * (lengths[i] + lengths[j])
        ok = L > _EPS
        Ls = np.where(ok, L, 1.0)
        gap = np.maximum(np.linalg.norm(starts[j] - starts[i], axis=1),
                         np.linalg.norm(ends[j] - ends[i], axis=1)) / Ls
        route_sq = np.zeros(len(j))
        for k, H in enumerate(higher, start=2):
            route_sq += np.sum((H[j] - H[i]) ** 2, axis=1) / Ls ** (2 * k)
        route = np.sqrt(route_sq)
        hit = ok & (gap <= endpoint_tol) & (route >= min_route)
        for jj, g, r in zip(j[hit], gap[hit], route[hit]):
            found.append({"a": paths[i].key, "b": paths[jj].key,
                          "endpoint_gap": float(g), "route_gap": float(r),
                          "levy_area_a": paths[i].area(), "levy_area_b": paths[jj].area()})
    found.sort(key=lambda x: (-x["route_gap"], x["endpoint_gap"]))
    return found[:top] if top else found


# ── store readers ────────────────────────────────────────────────────────

def session_paths(conn: sqlite3.Connection, basis: Basis | None = None,
                  d: int = DEFAULT_DIM, depth: int = DEFAULT_DEPTH,
                  min_points: int = 3, time_augment: bool = True,
                  basepoint: bool = False, lane: str | None = None) -> dict[str, Trajectory]:
    """Each session's vectorized episodes in (created_at, id) order → path.

    Sessions with fewer than ``min_points`` vectorized episodes, and episodes
    with no session, are skipped. Without ``basis``, one centered PCA basis is
    fitted over every episode of the qualifying sessions and shared by all.
    """
    sql = ("SELECT e.id, e.session_id, e.created_at, ev.embedding FROM episodes e"
           " JOIN episode_vectors ev ON ev.id = e.id WHERE e.session_id IS NOT NULL")
    args: tuple = ()
    if lane is not None:
        sql += " AND COALESCE(e.lane, 'personal') = ?"
        args = (lane,)
    sql += " ORDER BY e.session_id, e.created_at, e.id"
    groups: dict[str, list] = {}
    for r in conn.execute(sql, args):
        groups.setdefault(r[1], []).append((r[0], r[2], _unpack_embedding(r[3])))
    groups = {s: rows for s, rows in groups.items() if len(rows) >= min_points}
    if not groups:
        return {}
    if basis is None:
        basis = fit_basis(np.stack([v for rows in groups.values() for _, _, v in rows]), d)
    out = {}
    for sid, rows in groups.items():
        out[sid] = build_trajectory(
            sid, [r[0] for r in rows], np.stack([r[2] for r in rows]), basis,
            depth, time_augment, basepoint,
            meta={"first": rows[0][1], "last": rows[-1][1]})
    return out


def semantic_journey(conn: sqlite3.Connection, semantic_id: str,
                     basis: Basis | None = None, d: int = DEFAULT_DIM,
                     depth: int = DEFAULT_DEPTH, time_augment: bool = True,
                     basepoint: bool = False) -> Trajectory | None:
    """The route to a conclusion: a semantic's vectorized source episodes in
    (created_at, id) order. None if fewer than two have vectors.

    Without ``basis`` the path is drawn in the journey's own terms; pass a
    shared basis to compare journeys with each other or with sessions.
    """
    rows = conn.execute(
        "SELECT e.id, e.created_at, ev.embedding FROM semantic_sources ss"
        " JOIN episodes e ON e.id = ss.episode_id"
        " JOIN episode_vectors ev ON ev.id = e.id"
        " WHERE ss.semantic_id = ? ORDER BY e.created_at, e.id", (semantic_id,)).fetchall()
    if len(rows) < 2:
        return None
    X = np.stack([_unpack_embedding(r[2]) for r in rows])
    if basis is None:
        basis = fit_basis(X, d)
    return build_trajectory(semantic_id, [r[0] for r in rows], X, basis, depth,
                            time_augment, basepoint,
                            meta={"first": rows[0][1], "last": rows[-1][1]})


def connect_ro(path: str | Path) -> sqlite3.Connection:
    """Open a graph.db read-only with sqlite_vec loaded; never creates a file."""
    import sqlite_vec

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    conn = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA query_only=ON")
    return conn


# ── read-only CLI ────────────────────────────────────────────────────────

def _finite(x: float) -> float | None:
    return None if not math.isfinite(x) else round(x, 4)


def report(conn: sqlite3.Connection, d: int = DEFAULT_DIM, depth: int = DEFAULT_DEPTH,
           min_points: int = 3, time_augment: bool = True, basepoint: bool = False,
           lane: str | None = None, top: int = 10, endpoint_tol: float = 0.25,
           min_route: float = 0.05) -> dict:
    total = conn.execute(
        "SELECT COUNT(DISTINCT session_id) FROM episodes WHERE session_id IS NOT NULL"
    ).fetchone()[0]
    paths = session_paths(conn, d=d, depth=depth, min_points=min_points,
                          time_augment=time_augment, basepoint=basepoint, lane=lane)
    out: dict = {"sessions_total": total, "sessions_with_paths": len(paths),
                 "min_points": min_points, "depth": depth,
                 "time_augment": time_augment, "basepoint": basepoint, "lane": lane}
    if not paths:
        out.update(basis=None, tortuosity=None, most_tortuous=[], different_routes=[],
                   changes=conn.total_changes)
        return out
    basis = next(iter(paths.values())).basis
    out["basis"] = {"dim": basis.dim, "centered": True, "fit_on": basis.n_fit,
                    "explained_variance": round(basis.explained, 4)}
    tort = np.array([p.tortuosity for p in paths.values()])
    fin = tort[np.isfinite(tort)]
    out["tortuosity"] = {
        "count": len(tort), "returned_home": int((~np.isfinite(tort)).sum()),
        **({f"p{q}": round(float(np.percentile(fin, q)), 3) for q in (10, 50, 90)}
           if len(fin) else {}),
        "max": round(float(fin.max()), 3) if len(fin) else None,
    }
    ranked = sorted(paths.values(), key=lambda p: -p.tortuosity)
    out["most_tortuous"] = [
        {"session": p.key, "n": p.n, "tortuosity": _finite(p.tortuosity),
         "length": round(p.length, 4), "displacement": round(p.displacement, 4),
         "area": round(p.area(), 4), "first": p.meta.get("first")}
        for p in ranked[:top]]
    out["different_routes"] = [
        {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
        for r in different_routes(paths, endpoint_tol, min_route, top)]
    out["endpoint_tol"], out["min_route"] = endpoint_tol, min_route
    out["changes"] = conn.total_changes
    return out


def _print_report(db: str, r: dict) -> None:
    print(f"== path signatures (read-only) — {db} ==")
    print(f"sessions with ≥{r['min_points']} vectorized episodes:"
          f" {r['sessions_with_paths']} of {r['sessions_total']}")
    if not r["sessions_with_paths"]:
        return
    b = r["basis"]
    print(f"shared basis: centered PCA d={b['dim']} over {b['fit_on']} episodes,"
          f" explained variance {b['explained_variance']:.3f};"
          f" depth {r['depth']}, time-augmented={r['time_augment']},"
          f" basepoint={r['basepoint']}")
    t = r["tortuosity"]
    if "p50" in t:
        print(f"\n== tortuosity (length / displacement) ==\n"
              f"p10/p50/p90/max: {t['p10']}/{t['p50']}/{t['p90']}/{t['max']}"
              f"  returned home (displacement≈0): {t['returned_home']}")
    print(f"\n== most tortuous ==\n{'tort':>8} {'n':>4} {'area':>7}  first                 session")
    for p in r["most_tortuous"]:
        tort = "inf" if p["tortuosity"] is None else f"{p['tortuosity']:.2f}"
        print(f"{tort:>8} {p['n']:>4} {p['area']:7.3f}  {str(p['first'])[:20]:<20}  {p['session']}")
    print(f"\n== same destination, different route =="
          f" (endpoint gap ≤ {r['endpoint_tol']}, route gap ≥ {r['min_route']}) ==")
    if not r["different_routes"]:
        print("  none")
    for p in r["different_routes"]:
        print(f"  route {p['route_gap']:.3f}  endpoints {p['endpoint_gap']:.3f}"
              f"  {p['a']}  ~  {p['b']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paths", description=__doc__.splitlines()[0])
    ap.add_argument("db", help="path to a COPY of graph.db (opened mode=ro)")
    ap.add_argument("--dim", type=int, default=DEFAULT_DIM)
    ap.add_argument("--depth", type=int, default=DEFAULT_DEPTH, choices=(1, 2, 3))
    ap.add_argument("--min-points", type=int, default=3)
    ap.add_argument("--no-time", action="store_true", help="no time augmentation")
    ap.add_argument("--basepoint", action="store_true")
    ap.add_argument("--lane", choices=("personal", "work"))
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--endpoint-tol", type=float, default=0.25)
    ap.add_argument("--min-route", type=float, default=0.05)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        conn = connect_ro(args.db)
        try:
            r = report(conn, args.dim, args.depth, args.min_points, not args.no_time,
                       args.basepoint, args.lane, args.top, args.endpoint_tol,
                       args.min_route)
        finally:
            conn.close()
    except (FileNotFoundError, sqlite3.Error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(r, indent=2))
    else:
        _print_report(args.db, r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
