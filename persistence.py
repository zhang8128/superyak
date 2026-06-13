"""Persistence (Layer 4) — H0 persistence over similarity filtrations.

Single-linkage filtration computed exactly via MST. One tree yields merge
heights, per-point redundancy (nearest-neighbor coverage), per-point
uniqueness (lineage survival across scales), and split persistence bands
for the subdivision gate's middle conjunct.

Spec: docs/superpowers/specs/2026-06-13-persistence-design.md
"""

import json
import logging
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import minimum_spanning_tree

logger = logging.getLogger(__name__)

_EPS = 1e-12
_MST_FLOOR = 1e-9  # scipy MST treats 0 as "no edge"; duplicates have d=0


def _unpack_embedding(blob: bytes) -> np.ndarray:
    return np.array(struct.unpack(f"<{len(blob) // 4}f", blob), dtype=np.float64)


def distance_matrix(X) -> np.ndarray:
    X = np.asarray(X, dtype=np.float64)
    Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + _EPS)
    D = 1.0 - Xn @ Xn.T
    np.fill_diagonal(D, 0.0)
    return np.maximum(D, 0.0)


def _mst_edges(D: np.ndarray) -> list[tuple[float, int, int]]:
    floored = np.maximum(D, _MST_FLOOR)
    np.fill_diagonal(floored, 0.0)
    t = minimum_spanning_tree(csr_matrix(floored)).tocoo()
    edges = sorted(zip(t.data.tolist(), t.row.tolist(), t.col.tolist()))
    return [(float(h), int(i), int(j)) for h, i, j in edges]


@dataclass
class Filtration:
    n: int
    nn_dist: np.ndarray   # per-point nearest-neighbor distance
    death: np.ndarray     # per-point lineage death height (inf = survivor)
    max_height: float     # final merge height of the whole set


def build_filtration(X) -> Filtration:
    n = len(X)
    if n == 0:
        return Filtration(0, np.zeros(0), np.zeros(0), 0.0)
    if n == 1:
        return Filtration(1, np.array([1.0]), np.array([np.inf]), 0.0)
    D = distance_matrix(X)
    off = D + np.diag(np.full(n, np.inf))
    nn = off.min(axis=1)
    edges = _mst_edges(D)
    death = np.full(n, np.inf)
    parent = list(range(n))
    size = [1] * n
    carrier = list(range(n))  # the point whose lineage the component carries

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for h, i, j in edges:
        ri, rj = find(i), find(j)
        if ri == rj:
            continue
        if size[ri] < size[rj]:
            ri, rj = rj, ri
        death[carrier[rj]] = h  # smaller component's lineage dies
        parent[rj] = ri
        size[ri] += size[rj]
    max_height = edges[-1][0] if edges else 0.0
    return Filtration(n, nn, death, max_height)


def redundancy(f: Filtration) -> np.ndarray:
    """1 - nn_distance, clipped to [0,1]: how completely neighbors cover it."""
    if f.n == 0:
        return np.zeros(0)
    if f.n == 1:
        return np.zeros(1)
    return np.clip(1.0 - f.nn_dist, 0.0, 1.0)


def uniqueness(f: Filtration) -> np.ndarray:
    """Normalized lineage persistence: how long it resists merging."""
    if f.n == 0:
        return np.zeros(0)
    if f.n == 1 or f.max_height <= _MST_FLOOR:
        return np.ones(f.n)
    return np.clip(np.minimum(f.death, f.max_height) / f.max_height, 0.0, 1.0)


def split_band(X, part_a: list[int], part_b: list[int]) -> float:
    """Persistence band of a proposed two-part split, normalized by the
    neighborhood's total merge range. <=0 means the parts interleave."""
    D = distance_matrix(X)
    h_cross = float(D[np.ix_(part_a, part_b)].min())

    def coalescence(idx):
        if len(idx) < 2:
            return 0.0
        edges = _mst_edges(D[np.ix_(idx, idx)])
        return edges[-1][0] if edges else 0.0

    h_int = max(coalescence(part_a), coalescence(part_b))
    full = _mst_edges(D)
    h_max = full[-1][0] if full else _EPS
    return float((h_cross - h_int) / max(h_max, _EPS))


def _episodes_with_vectors(conn, lane: str | None = None):
    sql = ("SELECT e.id, e.lane, ev.embedding FROM episodes e"
           " JOIN episode_vectors ev ON ev.id = e.id")
    args: tuple = ()
    if lane is not None:
        sql += " WHERE COALESCE(e.lane, 'personal') = ?"
        args = (lane,)
    rows = conn.execute(sql, args).fetchall()
    ids = [r["id"] for r in rows]
    X = np.stack([_unpack_embedding(r["embedding"]) for r in rows]) if rows else None
    return ids, X


_LAYER_VEC_TABLE = {
    "episode": "episode_vectors",
    "semantic": "semantic_vectors",
    "instinct": "instinct_vectors",
}


def _fetch_embedding(conn, layer: str, memory_id: str) -> np.ndarray | None:
    """Return the L2-normalised embedding for a memory, or None if missing."""
    table = _LAYER_VEC_TABLE.get(layer)
    if table is None:
        return None
    row = conn.execute(
        f"SELECT embedding FROM {table} WHERE id = ?", (memory_id,)
    ).fetchone()
    if row is None:
        return None
    v = _unpack_embedding(row[0])
    norm = np.linalg.norm(v)
    return v / (norm + _EPS)


def generativity_scores(conn) -> dict[str, float]:
    """Geometric distance computed from embeddings — the similarity column
    stores PMI, not cosine (review finding 2026-06-13).

    For each resonance edge: fetch endpoint embeddings, compute
    d = 1 − cos(a, b) clipped to [0, 1], then w = co_occurrences × d.
    Episode endpoints receive the credit; edges where either endpoint
    lacks a vector are skipped (no evidence, no credit).
    """
    rows = conn.execute(
        "SELECT memory_a, layer_a, memory_b, layer_b,"
        " co_occurrences FROM resonances").fetchall()
    g: dict[str, float] = {}
    for r in rows:
        va = _fetch_embedding(conn, r["layer_a"], r["memory_a"])
        vb = _fetch_embedding(conn, r["layer_b"], r["memory_b"])
        if va is None or vb is None:
            continue
        cos_sim = float(np.dot(va, vb))
        d = min(max(1.0 - cos_sim, 0.0), 1.0)
        w = (r["co_occurrences"] or 1) * d
        for mid, lay in ((r["memory_a"], r["layer_a"]),
                         (r["memory_b"], r["layer_b"])):
            if lay == "episode":
                g[mid] = g.get(mid, 0.0) + w
    return g


def compute_scores(storage, cfg) -> dict[str, dict]:
    """Per-episode redundancy/uniqueness (lane-pure filtrations) +
    generativity overlay. Refreshes the persistence_scores cache."""
    # cfg unused; kept for signature parity with the persistence API
    gen = generativity_scores(storage.conn)
    out: dict[str, dict] = {}
    # O(n^2) per lane (dense distance matrix); fine to ~2k episodes/lane.
    # If the store grows past that, cap with most-recent-N sampling here.
    for lane in ("personal", "work"):
        ids, X = _episodes_with_vectors(storage.conn, lane=lane)
        if not ids:
            continue
        f = build_filtration(X)
        red, uniq = redundancy(f), uniqueness(f)
        for i, eid in enumerate(ids):
            out[eid] = {"episode_id": eid,
                        "redundancy": float(red[i]),
                        "uniqueness": float(uniq[i]),
                        "generativity": float(gen.get(eid, 0.0))}
    if out:
        storage.upsert_persistence_scores(list(out.values()))
    return out


def audit_unchecked_events(storage, cfg) -> list[dict]:
    """Re-run the band check on subdivision events recorded before the
    conjunct existed (persistence_checked=0). Best-effort: uses the peers'
    CURRENT provenance; events whose peers lack >=1 vectored episode on
    both sides are skipped with a reason."""
    events = storage.conn.execute(
        "SELECT * FROM subdivision_events WHERE persistence_checked = 0"
    ).fetchall()
    report = []
    for ev in events:
        peer_ids = json.loads(ev["peer_ids"])
        parts: list[list[str]] = []
        for pid in peer_ids:
            rows = storage.conn.execute(
                "SELECT ss.episode_id FROM semantic_sources ss"
                " JOIN episode_vectors ev ON ev.id = ss.episode_id"
                " WHERE ss.semantic_id = ?", (pid,)).fetchall()
            parts.append([r["episode_id"] for r in rows])
        usable = [p for p in parts if p]
        if len(usable) < 2:
            report.append({"event_id": ev["id"], "parent_id": ev["parent_id"],
                           "band": None, "would_pass": None,
                           "skipped": "insufficient surviving provenance"})
            continue
        all_ids = [e for p in usable[:2] for e in p]
        X = np.stack([
            _unpack_embedding(storage.conn.execute(
                "SELECT embedding FROM episode_vectors WHERE id = ?",
                (e,)).fetchone()[0]) for e in all_ids])
        na = len(usable[0])
        band = split_band(X, list(range(na)), list(range(na, len(all_ids))))
        report.append({"event_id": ev["id"], "parent_id": ev["parent_id"],
                       "band": round(band, 4),
                       "would_pass": band >= cfg.min_split_band})
    return report
