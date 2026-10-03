"""Lighthouse sheaf — Layer 3 cohesion across independently governed stores.

``sheaf.py`` asks whether one semantic's source episodes glue in the
semantic's own terms. This module asks the same question across several
stores ("lighthouses") that cover one topic: where they overlap, how much do
they disagree, and between which pairs? Disagreement is computed, never
resolved by picking a winner. Trust is scoped to the topic being compared,
not global, and it weights the consensus without hiding the disagreement.

Mapping (see docs/superpowers/specs/2026-09-29-lighthouse-sheaf-design.md):

- open set: the topic; a lighthouse *covers* it iff it has at least one hit
  above the coverage threshold. An uncovered lighthouse is reported and
  excluded: unexplored is not false, so it never counts as dissent.
- section: a covered lighthouse's hits for the topic.
- restriction map: projection into a shared topic basis, the top principal
  directions (no mean-centering, as in ``sheaf.py``) of the union of covered
  hits, each lighthouse contributing equal total mass so a large store
  cannot define the basis alone.
- stalk value: the unit vector of the similarity-weighted mean of the
  lighthouse's L2-normalized hits, projected into the basis. Unit length
  bounds every edge residual ``||x_i - x_j||^2`` in [0, 4].
- sheaf: the complete graph on covered lighthouses, vertex and edge stalks
  R^k, identity restriction maps (all stalks already live in the shared
  basis), edge weight = product (or min) of the endpoints' topic trust.
  Coboundary ``(dx)_e = x_j - x_i``; Laplacian ``L = d^T W d``.
- H^0 / consensus: the trust-weighted mean, the global (constant) section
  nearest to the data in the trust-weighted norm.
- obstruction: the harmonic (non-kernel) part of the stalk family and the
  per-edge residuals localizing it.

Observational only: it gates nothing and never writes. The disk adapter
opens each store with ``Storage.open_read_only``; no embedding model is
needed because the CLI takes an existing memory's stored vector as the
topic query.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_EPS = 1e-12
_KERNEL_TOL = 1e-9
_LANES = ("work", "personal", "any")
_LAYERS = ("episode", "semantic")


@dataclass
class LighthouseSheafResult:
    """Everything the gluing computation observed for one topic."""

    covered: list[str]
    uncovered: list[str]
    k: int
    basis: np.ndarray  # k x D shared topic basis (rows orthonormal)
    stalks: dict[str, list[float]]  # unit section per covered lighthouse, R^k
    n_hits: dict[str, int]  # hits kept per lighthouse (all, incl. uncovered)
    trust: dict[str, float]
    off_basis: dict[str, float]  # section mass lost by the restriction
    energy: float  # trust-weighted, normalized to [0, 1]
    energy_unweighted: float  # same edges, every weight 1
    edges: list[dict]  # ranked by raw residual, largest first
    consensus: list[float]
    deviations: dict[str, float]  # ||x_i - c||^2 / 4, in [0, 1]
    kernel_dim: int  # dim ker L (H^0 of the sheaf structure)
    glued_dim: int  # basis directions on which every edge agrees
    harmonic_fraction: float  # ||x - P_ker x||^2 / ||x||^2
    glued: bool
    edge_weighting: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "covered": self.covered,
            "uncovered": self.uncovered,
            "k": self.k,
            "stalks": self.stalks,
            "n_hits": self.n_hits,
            "trust": self.trust,
            "off_basis": self.off_basis,
            "energy": self.energy,
            "energy_unweighted": self.energy_unweighted,
            "edges": self.edges,
            "consensus": self.consensus,
            "deviations": self.deviations,
            "kernel_dim": self.kernel_dim,
            "glued_dim": self.glued_dim,
            "harmonic_fraction": self.harmonic_fraction,
            "glued": self.glued,
            "edge_weighting": self.edge_weighting,
            "notes": self.notes,
        }


def _as_matrix(name: str, value) -> np.ndarray:
    X = np.asarray(value, dtype=np.float64)
    if X.ndim == 1:
        X = X.reshape(0, 0) if X.size == 0 else X.reshape(1, -1)
    if X.ndim != 2:
        raise ValueError(f"hits for {name!r} must be an (n, D) array")
    return X


def _trust_for(names: list[str], trust: dict[str, float] | None) -> dict[str, float]:
    out = {}
    for name in names:
        w = 1.0 if trust is None or name not in trust else float(trust[name])
        if not (0.0 <= w <= 1.0) or not np.isfinite(w):
            raise ValueError(f"trust for {name!r} must be in [0, 1], got {w}")
        out[name] = w
    return out


def _shared_basis(sections: dict[str, np.ndarray], variance_threshold: float,
                  max_dim: int) -> np.ndarray:
    """PCA (no mean-centering) of the union, one unit of mass per lighthouse."""
    rows = [X / np.sqrt(len(X)) for X in sections.values()]
    _, s, Vt = np.linalg.svd(np.vstack(rows), full_matrices=False)
    var = (s ** 2) / max(float((s ** 2).sum()), _EPS)
    k = int(np.searchsorted(np.cumsum(var), variance_threshold)) + 1
    k = max(min(2, len(s)), min(k, max_dim, len(s)))
    return Vt[:k]


def _kernel_projection(L: np.ndarray, x: np.ndarray) -> tuple[int, np.ndarray]:
    evals, evecs = np.linalg.eigh(L)
    scale = max(1.0, float(np.abs(evals).max(initial=0.0)))
    K = evecs[:, evals <= _KERNEL_TOL * scale]
    return K.shape[1], K @ (K.T @ x)


def glue(hits: dict[str, np.ndarray],
         scores: dict[str, np.ndarray] | None = None,
         trust: dict[str, float] | None = None,
         min_score: float | None = None,
         edge_weighting: str = "product",
         variance_threshold: float = 0.90,
         max_dim: int = 8) -> LighthouseSheafResult:
    """Glue per-lighthouse topic hits into one cellular sheaf.

    ``hits[name]`` is that lighthouse's (n_i, D) hit matrix for the topic;
    ``scores[name]`` optionally holds each hit's similarity to the topic.
    With ``min_score``, hits scoring below it are dropped; a lighthouse left
    with no usable hit is uncovered. ``trust`` holds topic-scoped weights in
    [0, 1] (default 1). Every lighthouse must share one embedding space.
    """
    if edge_weighting not in ("product", "min"):
        raise ValueError("edge_weighting must be 'product' or 'min'")
    names = list(hits)
    trust_w = _trust_for(names, trust)
    sections: dict[str, np.ndarray] = {}
    weights: dict[str, np.ndarray] = {}
    n_hits: dict[str, int] = {}
    dim = None
    for name in names:
        X = _as_matrix(name, hits[name])
        sc = None
        if scores is not None and name in scores:
            sc = np.asarray(scores[name], dtype=np.float64).reshape(-1)
            if len(sc) != len(X):
                raise ValueError(f"scores for {name!r} do not match its hits")
        keep = np.isfinite(X).all(axis=1) if len(X) else np.zeros(0, bool)
        if len(X):
            keep &= np.linalg.norm(X, axis=1) > _EPS
        if sc is not None and min_score is not None:
            keep &= sc >= min_score
        X = X[keep]
        n_hits[name] = len(X)
        if not len(X):
            continue
        if dim is None:
            dim = X.shape[1]
        elif X.shape[1] != dim:
            raise ValueError(
                "lighthouses use different embedding dimensions; comparing "
                "them needs a non-identity restriction map (not built)")
        sections[name] = X / np.linalg.norm(X, axis=1, keepdims=True)
        w = np.ones(len(X)) if sc is None else np.clip(sc[keep], 0.0, None)
        weights[name] = w if w.sum() > _EPS else np.ones(len(X))

    covered = [n for n in names if n in sections]
    uncovered = [n for n in names if n not in sections]
    notes: list[str] = []
    if not covered:
        return LighthouseSheafResult(
            covered, uncovered, 0, np.zeros((0, 0)), {}, n_hits, trust_w, {},
            0.0, 0.0, [], [], {}, 0, 0, 0.0, True, edge_weighting,
            ["no lighthouse covers this topic"])

    V = _shared_basis(sections, variance_threshold, max_dim)
    k = V.shape[0]
    stalks: dict[str, np.ndarray] = {}
    off_basis: dict[str, float] = {}
    for name in covered:
        mean = weights[name] @ sections[name] / weights[name].sum()
        p = V @ mean
        full, kept = float(mean @ mean), float(p @ p)
        off_basis[name] = 0.0 if full <= _EPS else float(np.clip(1 - kept / full, 0, 1))
        norm = np.sqrt(kept)
        if norm <= _EPS:
            notes.append(f"{name}: section cancels to zero in the basis")
            stalks[name] = np.zeros(k)
        else:
            stalks[name] = p / norm

    m = len(covered)
    X = np.array([stalks[n] for n in covered])  # m x k
    t = np.array([trust_w[n] for n in covered])
    pairs = list(itertools.combinations(range(m), 2))
    combine = np.multiply if edge_weighting == "product" else np.minimum
    w_e = np.array([combine(t[i], t[j]) for i, j in pairs], dtype=np.float64)

    # Coboundary d: C^0 = R^{mk} -> C^1 = R^{|E|k}, (dx)_e = x_j - x_i.
    delta = np.zeros((len(pairs) * k, m * k))
    eye = np.eye(k)
    for e, (i, j) in enumerate(pairs):
        delta[e * k:(e + 1) * k, i * k:(i + 1) * k] = -eye
        delta[e * k:(e + 1) * k, j * k:(j + 1) * k] = eye
    L = delta.T @ np.kron(np.diag(w_e), eye) @ delta if pairs else np.zeros((m * k, m * k))

    x = X.reshape(-1)
    residual = np.array([float(((X[j] - X[i]) ** 2).sum()) for i, j in pairs])
    energy = (float(x @ L @ x) / (4.0 * w_e.sum())) if w_e.sum() > _EPS else 0.0
    energy_unweighted = float(residual.mean() / 4.0) if pairs else 0.0
    if pairs and w_e.sum() <= _EPS:
        notes.append("every edge has zero trust; weighted energy reported as 0")

    order = np.argsort(-residual, kind="stable")
    edges = [{"a": covered[pairs[e][0]], "b": covered[pairs[e][1]],
              "residual": float(residual[e]), "weight": float(w_e[e]),
              "weighted_residual": float(w_e[e] * residual[e])} for e in order]

    if t.sum() > _EPS:
        consensus = t @ X / t.sum()
    else:
        consensus = X.mean(axis=0)
        notes.append("every covered lighthouse has zero trust; consensus unweighted")
    deviations = {n: float(((X[i] - consensus) ** 2).sum() / 4.0)
                  for i, n in enumerate(covered)}

    kernel_dim, x_ker = _kernel_projection(L, x)
    D = (np.array([X[j] - X[i] for i, j in pairs]) if pairs else np.zeros((0, k)))
    rank = int(np.linalg.matrix_rank(D, tol=1e-6)) if len(D) else 0
    xx = float(x @ x)
    harmonic = float(((x - x_ker) ** 2).sum() / xx) if xx > _EPS else 0.0
    return LighthouseSheafResult(
        covered=covered, uncovered=uncovered, k=k, basis=V,
        stalks={n: stalks[n].tolist() for n in covered}, n_hits=n_hits,
        trust=trust_w, off_basis=off_basis,
        energy=float(np.clip(energy, 0.0, 1.0)),
        energy_unweighted=float(np.clip(energy_unweighted, 0.0, 1.0)),
        edges=edges, consensus=consensus.tolist(), deviations=deviations,
        kernel_dim=kernel_dim, glued_dim=k - rank,
        harmonic_fraction=float(np.clip(harmonic, 0.0, 1.0)),
        glued=rank == 0, edge_weighting=edge_weighting, notes=notes)


# --- Disk adapter (read-only) ---------------------------------------------

def _open(path):
    from storage import Storage
    return Storage.open_read_only(path)


def _columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def query_vector(path, layer: str, memory_id: str) -> np.ndarray:
    """A stored memory's vector, used as the topic query."""
    if layer not in _LAYERS:
        raise ValueError(f"layer must be one of {_LAYERS}")
    store = _open(path)
    try:
        vec = store.get_vector(layer, memory_id)
    finally:
        store.close()
    if vec is None:
        raise LookupError(f"no {layer} vector {memory_id!r} in {path}")
    return np.asarray(vec, dtype=np.float64)


def store_hits(path, query, k: int = 10, lane: str = "work",
               layer: str = "episode", exclude_ids=()) -> dict:
    """Top-k ``layer`` hits for ``query`` in one store, opened read-only.

    Lane filtering happens after the KNN, so the search overfetches until it
    has ``k`` lane-matching hits or has seen every vector. Dormant episodes
    are skipped, as in normal recall.
    """
    from storage import vec0_distance_to_similarity
    if lane not in _LANES:
        raise ValueError(f"lane must be one of {_LANES}")
    if layer not in _LAYERS:
        raise ValueError(f"layer must be one of {_LAYERS}")
    table = "episodes" if layer == "episode" else "semantics"
    exclude = set(exclude_ids)
    q = [float(v) for v in query]
    store = _open(path)
    try:
        cols = _columns(store.conn, table)
        total = store.conn.execute(
            f"SELECT COUNT(*) FROM {layer}_vectors").fetchone()[0]
        fetch = min(total, max(4 * k, 32))
        while True:
            raw = store.search_vectors(layer, q, k=fetch) if fetch else []
            kept = []
            for mid, dist in raw:
                if mid in exclude:
                    continue
                row = store.conn.execute(
                    f"SELECT * FROM {table} WHERE id = ?", (mid,)).fetchone()
                if row is None:
                    continue
                row = dict(row)
                if lane != "any" and "lane" in cols and row.get("lane") != lane:
                    continue
                if row.get("dormant"):
                    continue
                kept.append((mid, dist, row))
                if len(kept) == k:
                    break
            if len(kept) >= k or fetch >= total:
                break
            fetch = min(total, fetch * 4)
        ids, vecs, sims, contents = [], [], [], []
        for mid, dist, row in kept:
            vec = store.get_vector(layer, mid)
            if vec is None:
                continue
            ids.append(mid)
            vecs.append(vec)
            sims.append(vec0_distance_to_similarity(dist))
            contents.append(str(row.get("content") or ""))
    finally:
        store.close()
    dim = len(q)
    return {"ids": ids, "scores": np.asarray(sims, dtype=np.float64),
            "vectors": np.asarray(vecs, dtype=np.float64).reshape(len(vecs), dim),
            "contents": contents}


def compare_stores(stores: dict[str, str | Path], query, k: int = 10,
                   lane: str = "work", layer: str = "episode",
                   trust: dict[str, float] | None = None,
                   min_score: float | None = None,
                   edge_weighting: str = "product",
                   exclude: dict[str, set[str]] | None = None) -> dict:
    """Collect each store's topic hits read-only and glue them."""
    collected = {name: store_hits(path, query, k=k, lane=lane, layer=layer,
                                  exclude_ids=(exclude or {}).get(name, ()))
                 for name, path in stores.items()}
    result = glue({n: c["vectors"] for n, c in collected.items()},
                  scores={n: c["scores"] for n, c in collected.items()},
                  trust=trust, min_score=min_score,
                  edge_weighting=edge_weighting)
    out = result.to_dict()
    out["hits"] = {n: [{"id": i, "score": float(s), "content": c[:160]}
                       for i, s, c in zip(v["ids"], v["scores"], v["contents"])]
                   for n, v in collected.items()}
    out["query"] = {"k": k, "lane": lane, "layer": layer, "min_score": min_score}
    return out


# --- CLI --------------------------------------------------------------------

def _pair(text: str, sep: str, what: str) -> tuple[str, str]:
    name, found, value = text.partition(sep)
    if not found or not name or not value:
        raise argparse.ArgumentTypeError(f"{what} must look like NAME{sep}VALUE")
    return name, value


def _format(out: dict) -> str:
    lines = [f"covered:   {', '.join(out['covered']) or '-'}",
             f"uncovered: {', '.join(out['uncovered']) or '-'}"
             "  (no section over this topic; not counted as dissent)"]
    if not out["covered"]:
        return "\n".join(lines)
    lines += [
        f"basis k={out['k']}  energy={out['energy']:.4f}"
        f"  (unweighted {out['energy_unweighted']:.4f})",
        f"ker L dim={out['kernel_dim']}  glued dims={out['glued_dim']}/{out['k']}"
        f"  harmonic={out['harmonic_fraction']:.4f}  glued={out['glued']}",
        "", f"{'deviation':>9}  {'trust':>5}  {'hits':>4}  {'off-basis':>9}  lighthouse"]
    for name in sorted(out["covered"], key=lambda n: -out["deviations"][n]):
        lines.append(f"{out['deviations'][name]:9.4f}  {out['trust'][name]:5.2f}"
                     f"  {out['n_hits'][name]:4d}  {out['off_basis'][name]:9.4f}  {name}")
    if out["edges"]:
        lines += ["", f"{'residual':>8}  {'weight':>6}  edge"]
        for e in out["edges"][:10]:
            lines.append(f"{e['residual']:8.4f}  {e['weight']:6.2f}  {e['a']} -- {e['b']}")
    for note in out["notes"]:
        lines.append(f"note: {note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read-only cross-lighthouse sheaf cohesion for one topic.")
    ap.add_argument("--store", action="append", required=True, metavar="NAME=PATH",
                    type=lambda s: _pair(s, "=", "--store"))
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--semantic", metavar="NAME:ID",
                     type=lambda s: _pair(s, ":", "--semantic"))
    src.add_argument("--episode", metavar="NAME:ID",
                     type=lambda s: _pair(s, ":", "--episode"))
    ap.add_argument("--trust", action="append", default=[], metavar="NAME=W",
                    type=lambda s: _pair(s, "=", "--trust"))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--lane", choices=_LANES, default="work")
    ap.add_argument("--layer", choices=_LAYERS, default="episode",
                    help="which layer's hits form each section")
    ap.add_argument("--min-score", type=float, default=None,
                    help="coverage threshold on hit similarity")
    ap.add_argument("--edge-weight", choices=("product", "min"), default="product")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    stores = dict(args.store)
    if len(stores) != len(args.store):
        ap.error("store names must be unique")
    q_layer = "semantic" if args.semantic else "episode"
    q_name, q_id = args.semantic or args.episode
    if q_name not in stores:
        ap.error(f"query store {q_name!r} is not one of the --store names")
    try:
        trust = {n: float(w) for n, w in args.trust}
    except ValueError:
        ap.error("--trust weights must be numbers")
    query = query_vector(stores[q_name], q_layer, q_id)
    # The query memory would match itself; leave it out of its own section.
    exclude = {q_name: {q_id}} if q_layer == args.layer else None
    out = compare_stores(stores, query, k=args.k, lane=args.lane,
                         layer=args.layer, trust=trust, min_score=args.min_score,
                         edge_weighting=args.edge_weight, exclude=exclude)
    out["query"].update({"store": q_name, "source_layer": q_layer, "id": q_id})
    print(json.dumps(out, indent=2) if args.json else _format(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
