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
    # Normalization is per-filtration (relative): in a homogeneous all-duplicate set, scores skew high and protection dominates — conservative by design.
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


def _anchored_episode_ids(conn) -> set[str]:
    """Episode ids held by active identity anchors.

    Mirrors Storage.get_active_anchors's filter: status != 'retired'
    (NOT status = 'active' — anchors can have pending/proposed states that
    are also non-retired and should still protect the memory).
    """
    rows = conn.execute(
        "SELECT expected FROM anchors WHERE type = 'identity'"
        " AND status != 'retired'").fetchall()
    return {r["expected"] for r in rows if r["expected"]}


def evaluate_prune(storage, cfg, threshold: float = 0.05) -> dict:
    """Pure preview of the two-key prune rule. Reads the score cache —
    callers wanting live decisions refresh via compute_scores first."""
    scores = storage.get_persistence_scores()
    anchored = _anchored_episode_ids(storage.conn)
    rows = storage.conn.execute(
        "SELECT id FROM episodes WHERE decay_strength < ?"
        " AND compressed = 1 AND core = 0 AND dormant = 0",
        (threshold,)).fetchall()
    evict, protected = [], []
    for r in rows:
        eid = r["id"]
        s = scores.get(eid)
        reasons = []
        if s is None:
            # No score row = no vector = no evidence; such episodes can never be evicted by this gate — deliberate (forgetting requires evidence).
            reasons.append("no-vector-no-evidence")
        else:
            if s["uniqueness"] >= cfg.protect_threshold:
                reasons.append("unique")
            if (cfg.generativity_threshold > 0
                    and s["generativity"] >= cfg.generativity_threshold):
                reasons.append("generative")
            if s["redundancy"] < cfg.redundancy_floor:
                reasons.append("not-redundant-enough")
        if eid in anchored:
            reasons.append("anchored")
        if reasons:
            protected.append({"id": eid, "reasons": reasons})
        else:
            evict.append(eid)
    return {"evict": evict, "protected": protected,
            "candidates": len(rows)}


def guarded_prune(storage, cfg, threshold: float = 0.05) -> int:
    """The two-key rule, acting: decayed AND redundant AND unprotected ->
    cold storage. Fails toward leaving the store unchanged."""
    try:
        compute_scores(storage, cfg)   # decisions never trust a stale cache
        verdict = evaluate_prune(storage, cfg, threshold)
        return storage.prune_episode_ids(verdict["evict"])
    except Exception:
        logger.warning("guarded prune aborted — store unchanged", exc_info=True)
        return 0


def core_promotion_allowed(storage, episode_id: str, cfg) -> bool:
    """Decline promotion when the candidate is redundant within the
    existing core set (adds no coverage). Permissive on any gap in
    evidence: disabled, no cores, or missing vectors -> allow."""
    if cfg is None or not getattr(cfg, "enabled", False):
        return True
    cand = storage.get_vector("episode", episode_id)
    if cand is None:
        return True
    rows = storage.conn.execute(
        "SELECT ev.embedding FROM episodes e"
        " JOIN episode_vectors ev ON ev.id = e.id"
        " WHERE e.core > 0 AND e.id != ?", (episode_id,)).fetchall()
    if not rows:
        return True
    C = np.stack([_unpack_embedding(r["embedding"]) for r in rows])
    C = C / (np.linalg.norm(C, axis=1, keepdims=True) + _EPS)
    v = np.asarray(cand, dtype=np.float64)
    v = v / (np.linalg.norm(v) + _EPS)
    redundancy_vs_cores = float(np.clip((C @ v).max(), 0.0, 1.0))
    return redundancy_vs_cores < cfg.redundancy_floor


def classify_hubs(storage, cfg, min_episodes: int = 10) -> list[dict]:
    """diffuse / multi-modal / looped, per provenance-heavy semantic.
    multi-modal: the best Fiedler split's band clears min_split_band.
    looped: persistent H1 exists (optional ripser; omitted otherwise)."""
    from sheaf import build_local_sheaf, cohesion_energy
    try:
        from ripser import ripser as _ripser
    except ImportError:
        _ripser = None
    sems = storage.conn.execute(
        "SELECT semantic_id, COUNT(*) AS n FROM semantic_sources"
        " GROUP BY semantic_id HAVING n >= ?", (min_episodes,)).fetchall()
    out = []
    for r in sems:
        rows = storage.conn.execute(
            "SELECT ss.episode_id, ev.embedding FROM semantic_sources ss"
            " JOIN episode_vectors ev ON ev.id = ss.episode_id"
            " WHERE ss.semantic_id = ?", (r["semantic_id"],)).fetchall()
        if len(rows) < min_episodes:
            continue
        ids = [x["episode_id"] for x in rows]
        X = np.stack([_unpack_embedding(x["embedding"]) for x in rows])
        ls = build_local_sheaf(r["semantic_id"], ids, X)
        res = cohesion_energy(ls)
        band = None
        if res["fiedler"]:
            f = np.array(res["fiedler"])
            a = [i for i, v in enumerate(f) if v > 0]
            b = [i for i, v in enumerate(f) if v <= 0]
            if len(a) >= 2 and len(b) >= 2:
                band = split_band(X, a, b)
        h1 = None
        if _ripser is not None:
            D = distance_matrix(X)
            dgm1 = _ripser(D, maxdim=1, distance_matrix=True)["dgms"][1]
            # inf deaths can't occur without thresh=, but guard anyway:
            # inf would leak invalid JSON through the MCP transport
            finite = dgm1[np.isfinite(dgm1[:, 1])] if len(dgm1) else dgm1
            if len(finite):
                f_full = build_filtration(X)
                denom = max(f_full.max_height, _EPS)
                h1 = float(np.max(finite[:, 1] - finite[:, 0]) / denom)
        if band is not None and band >= cfg.min_split_band:
            cls = "multi-modal"
        elif h1 is not None and h1 >= 0.10:
            cls = "looped"
        else:
            cls = "diffuse"
        sem = storage.get_semantic(r["semantic_id"])
        out.append({"semantic_id": r["semantic_id"],
                    "content": (sem or {}).get("content", "")[:100],
                    "n": len(ids), "band": band,
                    "h1": h1 if _ripser is not None else "ripser-not-installed",
                    "classification": cls})
    return out


def flag_redundant_cores(storage, cfg) -> list[dict]:
    """Cores redundant within the core set — demotion candidates, review only."""
    rows = storage.conn.execute(
        "SELECT e.id, ev.embedding FROM episodes e"
        " JOIN episode_vectors ev ON ev.id = e.id WHERE e.core > 0").fetchall()
    if len(rows) < 2:
        return []
    ids = [r["id"] for r in rows]
    X = np.stack([_unpack_embedding(r["embedding"]) for r in rows])
    f = build_filtration(X)
    red = redundancy(f)
    flagged = []
    for i, eid in enumerate(ids):
        if red[i] >= cfg.redundancy_floor:
            ep = storage.get_episode(eid) or {}
            flagged.append({"id": eid, "redundancy": round(float(red[i]), 3),
                            "content": ep.get("content", "")[:100]})
    return sorted(flagged, key=lambda d: -d["redundancy"])


if __name__ == "__main__":
    # Read-only calibration: python persistence.py /path/to/copy-of-graph.db
    # Acceptance (spec): read the forgetting preview and hub classification
    # BEFORE setting [persistence] enabled = true. Pre-registered questions:
    # (1) does the recorded Prism verdict's band pass the conjunct?
    # (2) are the mega-hubs diffuse or looped?
    import sqlite3
    import sys

    import sqlite_vec

    from config import PersistenceConfig

    conn = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row  # must be set before any cursor use

    class _RO:
        def __init__(self, conn):
            self.conn = conn

        def get_semantic(self, sid):
            row = self.conn.execute(
                "SELECT * FROM semantics WHERE id = ?", (sid,)).fetchone()
            return dict(row) if row else None

        def get_episode(self, eid):
            row = self.conn.execute(
                "SELECT * FROM episodes WHERE id = ?", (eid,)).fetchone()
            return dict(row) if row else None

        def get_persistence_scores(self):
            return {}

        def upsert_persistence_scores(self, scores):
            pass  # read-only: scores printed, not cached

    cfg = PersistenceConfig(enabled=True)  # evaluation only; nothing writes
    store = _RO(conn)

    print("== score distribution ==")
    gen = generativity_scores(conn)
    for lane in ("personal", "work"):
        ids, X = _episodes_with_vectors(conn, lane=lane)
        if not ids:
            continue
        f = build_filtration(X)
        red, uniq = redundancy(f), uniqueness(f)
        print(f"[{lane}] n={len(ids)} redundancy p50/p90:"
              f" {np.percentile(red, 50):.3f}/{np.percentile(red, 90):.3f}"
              f" uniqueness p50/p90:"
              f" {np.percentile(uniq, 50):.3f}/{np.percentile(uniq, 90):.3f}")
        prot = sum(1 for u in uniq if u >= cfg.protect_threshold)
        redd = sum(1 for x in red if x >= cfg.redundancy_floor)
        print(f"  would-protect(unique): {prot}  redundant-enough: {redd}"
              f"  generativity>0: {sum(1 for i in ids if gen.get(i, 0) > 0)}")

    print("\n== hub classification ==")
    for h in classify_hubs(store, cfg):
        print(f"  {h['classification']:>11}  n={h['n']:>4}"
              f" band={h['band'] if h['band'] is None else round(h['band'], 3)}"
              f" h1={h['h1']}  {h['content'][:60]}")

    print("\n== retroactive conjunct audit ==")
    for a in audit_unchecked_events(store, cfg):
        print(f"  {a}")
