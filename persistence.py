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
