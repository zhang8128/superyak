"""Cellular-sheaf cohesion — local sheaves over semantic provenance neighborhoods.

A semantic's source episodes are translated into "its terms" (a low-dim PCA
subspace = the restriction maps); the cohesion energy is the spectral gap of
the similarity graph in those terms. The harmonic (Fiedler) part localizes
which edges fail to glue and proposes the partition.

Spec: docs/superpowers/specs/2026-06-13-sheaf-cohesion-design.md
"""

import json
import logging
import struct
import uuid
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

_EPS = 1e-12


def _unpack_embedding(blob: bytes) -> np.ndarray:
    return np.array(struct.unpack(f"<{len(blob) // 4}f", blob), dtype=np.float64)


@dataclass
class LocalSheaf:
    semantic_id: str
    episode_ids: list[str]
    coords: np.ndarray  # n×k coordinates in the semantic's subspace
    k: int


def build_local_sheaf(semantic_id: str, episode_ids: list[str], X: np.ndarray,
                      variance_threshold: float = 0.90, max_dim: int = 8) -> LocalSheaf:
    """Build the local sheaf for a semantic and its source episodes.

    The restriction maps are realized by projecting L2-normalized embeddings
    into the k principal directions of the full embedding matrix (no mean-center).
    Skipping mean-centering preserves the cluster structure: a tight cluster
    has all points near its dominant direction, so cos-sims stay high; two
    orthogonal clusters land in distinct half-spaces, so cross-cluster cos-sims
    are clipped to zero by the W_ij = max(0, ·) gate in cohesion_energy.
    """
    n = len(episode_ids)
    if n == 0:
        return LocalSheaf(semantic_id, [], np.zeros((0, 2)), 2)
    Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + _EPS)
    _, s, Vt = np.linalg.svd(Xn, full_matrices=False)
    var = (s ** 2) / max(float((s ** 2).sum()), _EPS)
    k = int(np.searchsorted(np.cumsum(var), variance_threshold)) + 1
    k = max(2, min(k, max_dim, len(s)))
    coords = Xn @ Vt[:k].T
    return LocalSheaf(semantic_id, episode_ids, coords, k)


def cohesion_energy(sheaf: LocalSheaf) -> dict:
    """Energy in [0,1]: 0 = globally consistent, 1 = provably conflated."""
    n = len(sheaf.episode_ids)
    trivial = {"energy": 0.0, "lambda2": None, "fiedler": [], "worst_edges": [], "n": n}
    if n < 3:
        return trivial
    Y = sheaf.coords / (np.linalg.norm(sheaf.coords, axis=1, keepdims=True) + _EPS)
    W = np.clip(Y @ Y.T, 0.0, None)
    np.fill_diagonal(W, 0.0)
    d = W.sum(axis=1)
    if (d <= _EPS).any():
        # an isolated episode is already a disconnection — maximally incoherent
        fiedler = [1.0 if dd <= _EPS else -1.0 for dd in d]
        return {"energy": 1.0, "lambda2": 0.0, "fiedler": fiedler,
                "worst_edges": [], "n": n}
    d_isqrt = 1.0 / np.sqrt(d)
    L = np.eye(n) - (W * d_isqrt[:, None]) * d_isqrt[None, :]
    evals, evecs = np.linalg.eigh(L)
    lam2 = float(evals[1])
    fiedler = (d_isqrt * evecs[:, 1])
    residuals = W * (fiedler[:, None] - fiedler[None, :]) ** 2
    iu = np.triu_indices(n, k=1)
    order = np.argsort(residuals[iu])[::-1][:10]
    worst = [(sheaf.episode_ids[iu[0][o]], sheaf.episode_ids[iu[1][o]],
              float(residuals[iu][o])) for o in order]
    return {"energy": float(np.clip(1.0 - lam2, 0.0, 1.0)), "lambda2": lam2,
            "fiedler": fiedler.tolist(), "worst_edges": worst, "n": n}
