"""Cellular-sheaf cohesion — local sheaves over semantic provenance neighborhoods.

A semantic's source episodes are translated into "its terms" (a low-dim PCA
subspace = the restriction maps); the cohesion energy is the spectral gap of
the similarity graph in those terms. The harmonic (Fiedler) part localizes
which edges fail to glue and proposes the partition.

Spec: docs/superpowers/specs/2026-06-13-sheaf-cohesion-design.md
"""

import hashlib
import json
import logging
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

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
    return LocalSheaf(semantic_id, episode_ids, coords, coords.shape[1])


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


@dataclass
class Verdict:
    semantic_id: str
    split: bool
    parts: list[list[str]]
    ambiguous: list[str]
    energy_before: float
    part_energies: list[float]
    gain: float
    dl_cost: float
    persistence_checked: bool
    worst_edges: list

    def to_dict(self) -> dict:
        return {
            "semantic_id": self.semantic_id, "split": self.split,
            "parts": self.parts, "ambiguous": self.ambiguous,
            "energy_before": self.energy_before,
            "part_energies": self.part_energies, "gain": self.gain,
            "dl_cost": self.dl_cost,
            "persistence_checked": self.persistence_checked,
        }


def persistence_check(parts: list[list[str]]) -> bool:
    """Layer 4 slot — persistence regularization (survives-across-scales).

    Returns True until persistent homology lands; every event records
    persistence_checked=False so Layer 4 can audit what it would have blocked.
    """
    return True


def subdivision_test(semantic_id: str, episode_ids: list[str], X: np.ndarray,
                     dl_cost: float = 0.15, variance_threshold: float = 0.90,
                     max_dim: int = 8, min_part: int = 2) -> Verdict:
    ls = build_local_sheaf(semantic_id, episode_ids, X, variance_threshold, max_dim)
    res = cohesion_energy(ls)
    no_split = Verdict(semantic_id, False, [], [], res["energy"], [], 0.0,
                       dl_cost, False, res["worst_edges"])
    if res["energy"] == 0.0 or not res["fiedler"]:
        return no_split
    f = np.array(res["fiedler"])
    # A single dominant outlier inflates max|f| until the band absorbs the
    # majority — the verdict collapses to no-split by design: a lone episode
    # is not a peer, and outlier eviction is not this gate's job.
    eps = 0.1 * float(np.abs(f).max())
    idx = {"a": [], "b": [], "amb": []}
    for i, fi in enumerate(f):
        key = "amb" if abs(fi) < eps else ("a" if fi > 0 else "b")
        idx[key].append(i)
    if len(idx["a"]) < min_part or len(idx["b"]) < min_part:
        return no_split
    parts_idx = [idx["a"], idx["b"]]
    part_energies = []
    for pi in parts_idx:
        sub = build_local_sheaf(semantic_id, [episode_ids[i] for i in pi],
                                X[pi], variance_threshold, max_dim)
        part_energies.append(cohesion_energy(sub)["energy"])
    n_assigned = sum(len(pi) for pi in parts_idx)
    weighted_after = sum((len(pi) / n_assigned) * e
                         for pi, e in zip(parts_idx, part_energies))
    gain = res["energy"] - weighted_after
    split = gain > dl_cost * (len(parts_idx) - 1) and persistence_check(
        [[episode_ids[i] for i in pi] for pi in parts_idx])
    return Verdict(
        semantic_id, split,
        [[episode_ids[i] for i in pi] for pi in parts_idx],
        [episode_ids[i] for i in idx["amb"]],
        res["energy"], part_energies, gain, dl_cost,
        False,  # persistence slot not yet built — recorded on every event
        res["worst_edges"],
    )


def apply_subdivision(storage, verdict: Verdict, peer_contents: list[str],
                      hub_content: str | None, embed_fn, site: str) -> dict:
    """Mint peers under the surviving hub. One transaction; partial splits
    cannot exist. embed_fn: str -> list[float] (the recall-side embedding
    used for new semantics)."""
    if len(peer_contents) != len(verdict.parts):
        raise ValueError(
            f"{len(verdict.parts)} parts but {len(peer_contents)} peer contents")
    if len(verdict.part_energies) != len(verdict.parts):
        raise ValueError(
            f"{len(verdict.parts)} parts but"
            f" {len(verdict.part_energies)} part_energies")
    parent = storage.get_semantic(verdict.semantic_id)
    if parent is None:
        raise ValueError(f"unknown semantic {verdict.semantic_id}")
    now = datetime.now(timezone.utc).isoformat()
    conn = storage.conn
    peer_ids = [str(uuid.uuid4()) for _ in verdict.parts]
    # Embed outside any partial writes so an embedder failure aborts cleanly
    peer_vecs = [embed_fn(c) for c in peer_contents]
    try:
        # Raw SQL throughout: the Storage helpers (add_semantic_peer,
        # log_subdivision_event, ...) each commit, which would break this
        # function's single-transaction guarantee.
        for pid, content, vec, part, p_energy in zip(
                peer_ids, peer_contents, peer_vecs, verdict.parts,
                verdict.part_energies):
            conn.execute(
                "INSERT INTO semantics (id, content, content_hash, kind,"
                " confidence, created_at, lane, auto_generated)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (pid, content, hashlib.sha256(content.encode()).hexdigest(),
                 parent["kind"], parent["confidence"], now, parent["lane"]),
            )
            conn.execute(
                "INSERT INTO semantic_vectors (id, embedding) VALUES (?, ?)",
                (pid, struct.pack(f"<{len(vec)}f", *vec)),
            )
            for eid in part:
                conn.execute(
                    "DELETE FROM semantic_sources WHERE semantic_id = ?"
                    " AND episode_id = ?", (verdict.semantic_id, eid))
                conn.execute(
                    "INSERT INTO semantic_sources (semantic_id, episode_id)"
                    " VALUES (?, ?)", (pid, eid))
            conn.execute(
                "INSERT INTO semantic_peers (peer_id, parent_id,"
                " residual_energy, created_at) VALUES (?, ?, ?, ?)",
                (pid, verdict.semantic_id, p_energy, now))
        if verdict.ambiguous and hub_content:
            conn.execute(
                "UPDATE semantics SET content = ?, content_hash = ? WHERE id = ?",
                (hub_content, hashlib.sha256(hub_content.encode()).hexdigest(),
                 verdict.semantic_id))
            # The old vector embeds the pre-split conflated text. Drop it so
            # the startup orphan-vector backfill (which keys on missing rows
            # only) re-embeds the new common-ground content; FTS stays correct
            # via the semantics update trigger meanwhile.
            conn.execute(
                "DELETE FROM semantic_vectors WHERE id = ?",
                (verdict.semantic_id,))
        n_assigned = sum(len(p) for p in verdict.parts)
        energy_after = sum(
            (len(p) / n_assigned) * e
            for p, e in zip(verdict.parts, verdict.part_energies)
        ) if n_assigned else 0.0
        conn.execute(
            "INSERT INTO subdivision_events (id, parent_id, peer_ids,"
            " energy_before, energy_after, dl_cost, persistence_checked,"
            " site, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), verdict.semantic_id, json.dumps(peer_ids),
             verdict.energy_before,
             energy_after,  # size-weighted to match the gate's decision quantity
             verdict.dl_cost, int(verdict.persistence_checked), site, now))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"peer_ids": peer_ids, "parent_id": verdict.semantic_id}


def _ollama_generate(prompt: str, framing_cfg) -> str | None:
    """Same transport as framing.py — model/url/timeout from FramingConfig."""
    import urllib.request
    model = getattr(framing_cfg, "model", "gemma4:31b")
    url = getattr(framing_cfg, "ollama_url", "http://localhost:11434/api/generate")
    timeout = getattr(framing_cfg, "timeout", 60)
    body = {"model": model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.0, "num_predict": 400}}
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("response", "")
    except Exception:
        logger.warning("subdivision distill LLM call failed", exc_info=True)
        return None


def distill_subdivision(parent_content: str,
                        part_episode_contents: list[list[str]],
                        has_ambiguous: bool, framing_cfg) -> tuple | None:
    """Write peer contents (one per part) and optionally the hub residue.

    Returns (peer_contents, hub_content_or_None) or None on any failure —
    the caller queues the verdict and nothing splits.
    """
    sections = []
    for i, part in enumerate(part_episode_contents):
        sample = "\n".join(f"  - {c[:200]}" for c in part[:8])
        sections.append(f"PART {i + 1}:\n{sample}")
    hub_clause = (
        '"hub": a 1-2 sentence summary of only what ALL parts genuinely share'
        if has_ambiguous else '"hub": null')
    prompt = (
        "A memory summary conflates distinct groups of experiences.\n"
        f"CURRENT SUMMARY: {parent_content[:400]}\n\n"
        + "\n\n".join(sections)
        + "\n\nReply with ONLY a JSON object: {\"peers\": [one 1-3 sentence"
        " summary per PART, in order], " + hub_clause + "}."
    )
    raw = _ollama_generate(prompt, framing_cfg)
    if not raw:
        return None
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        data = json.loads(raw[start:end])
        peers = data.get("peers")
        if (not isinstance(peers, list)
                or len(peers) != len(part_episode_contents)
                or not all(isinstance(p, str) and p.strip() for p in peers)):
            return None
        hub = data.get("hub")
        return ([p.strip() for p in peers],
                hub.strip() if isinstance(hub, str) and hub.strip() else None)
    except (ValueError, json.JSONDecodeError):
        logger.warning("subdivision distill returned unparseable output")
        return None
