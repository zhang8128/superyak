#!/usr/bin/env python3
"""Experiment E1 of the rail-mathematics plan (docs/superpowers/specs/2026-11-03-rail-mathematics.md, section 6), as
revised on 2026-11-03 after review: does the geometry of use carry information that the geometry of meaning doesn't?

The plan's first design was degenerate on chat. Each message is written once, in one session, so the trail graph over
messages is a disjoint union of paths (support always 1) and a held-out message is never a trained node. This script
measures those facts, then runs the revision. It quotients the sphere into P places (spherical k-means on training
messages only, P in {32, 64, 128}, 64 primary) and predicts the next message's place from the current one.

  (i)   meaning: places by angle from the current message to each centroid
  (ii)  use: places by training transition count from the current place, ties and backfill by centroid angle
  (iv)  room: places by angle from the room's latest message by another author (before the next one) to each centroid
  (v)   same-author kNN: the m nearest earlier messages by the same author vote for their places, backfilled by (i)
  (vi)  same-room kNN: the m nearest earlier messages in the same room vote for their places, backfilled by (i)
  (vii) popularity: places by how often training steps moved into them, ties by (i); the base rate (ii) also carries
  (ii+) use, online (secondary, outside the falsifier): (ii) with counts that also take held-out steps already done

On place-changing steps every arm's ranking drops the current place before hit@k is taken.

Bounds: the store opens read-only (mode=ro). Message bodies stay in memory and go only to the shared embedder's
socket. Only ids, vectors and counts go to a scratch SQLite under TMPDIR (default /var/tmp), deleted at the end. The
report holds numbers only: rooms by short id, authors by kind. RLIMIT_DATA is capped at 512 MiB and peak RSS is
reported.

Run: /home/andy/superyak/engram/.venv/bin/python -I scripts/rail_e1.py
"""

from __future__ import annotations

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # before numpy: one BLAS thread, bounded buffers

import argparse
import resource
import sqlite3
import sys
import tempfile
import time
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engram"))  # -I drops the script's directory; engram's modules live here

STORE = Path.home() / ".local/share/superyak/lighthouse/peer.sqlite3"
SOCKET = "/run/user/1000/superyak/embedder.sock"
REPORT = ROOT / "docs/reports/2026-11-03-rail-e1.md"
SCRATCH_DIR = os.environ.get("TMPDIR") or "/var/tmp"
MEMORY_CAP = 512 * 1024 * 1024

BATCH = 16  # texts per embed request (at most 64); small, so other agents' requests interleave on the one-at-a-time service
GAP = 30 * 60  # a session continues while gaps are under 30 minutes
SPLIT_PERCENTILE = 80
PLACES = (32, 64, 128)  # P, the number of places
PRIMARY = ("deduplicated", 64)
HITS = (1, 5, 10)  # k in hit@k
FALSIFIER_HIT = 10
NEIGHBOURS = 10  # m, the neighbour count of (v) and (vi)
DEDUP_THETA = 0.05  # radians: a post this close to an earlier one by the same author is a templated repeat
RESAMPLES = 1000
SEED = 20261103
RESTARTS = 4
ITERATIONS = 100

ARMS = ("i", "ii", "iv", "v", "vi", "vii", "ii+")
OTHERS = ("i", "iv", "v", "vi", "vii")  # the arms (ii) must beat
FOUR = ("i", "iv", "v", "vi")  # the coordinator's four, reported beside the five
ARM_NAMES = {
    "i": "(i) meaning",
    "ii": "(ii) use",
    "iv": "(iv) room, other author",
    "v": "(v) author kNN",
    "vi": "(vi) room kNN",
    "vii": "(vii) popularity",
    "ii+": "(ii+) use, online",
}

# Fixed before any E1 number was computed, and printed in the report ahead of the numbers.
PREREGISTRATION = """\
**Pre-registered falsifier.** I fixed it on 2026-11-03 before any E1 number was computed. I revised it three times that
day, each before any number from the station's vectors existed:

- twice on the coordinator's refinements, which name the place count `P` with 64 primary, take (iv) from another
  author, and restrict the test to place-changing steps with the current place dropped;
- once on a smoke run with random vectors and the real sessions. There (ii) beat (i), (iv), (v) and (vi) with no
  sequence information at all, through the base rate of places, which ranking by transition count carries and those
  four arms don't. So the popularity arm (vii) joins the max. The coordinator's rule is "C1 holds only if (ii) beats
  max(i, iv, v, vi)", and this adds a necessary condition without removing one.

- **Population.** Held-out **place-changing, non-reply steps**: session steps `a → b` where `place(b) ≠ place(a)` and
  `b` does not answer `a`.
- **Rankings.** Each arm's ranking of places, with the current place `place(a)` removed. Then hit@10.
- **Statistic.** `D = hit@10(ii) − max(hit@10(i), hit@10(iv), hit@10(v), hit@10(vi), hit@10(vii))`. Each hit@10 is
  the mean over the population. The max is taken over the five arms inside every bootstrap resample, so choosing the
  strongest baseline is part of the statistic. `D4`, the same without (vii), is reported beside it.
- **Interval.** A paired bootstrap clustered by held-out session. Each resample draws sessions with replacement and
  keeps all their steps, with one draw for every arm. 1,000 resamples, 95% percentile interval.
- **Primary.** The deduplicated corpus at `P = 64`. **C1 fails if the primary 95% interval includes 0 or lies below
  it.**
- **Secondary**, reported but not deciding: `P = 32` and `P = 128`, the corpus with its duplicates, hit@1 and hit@5,
  all steps including self-steps, `D4`, and the online arm (ii+). A primary pass that doesn't hold at `P = 32` and
  `P = 128` on the deduplicated corpus is reported as fragile, not as a pass."""


@dataclass
class Corpus:
    ids: list[str]
    room: np.ndarray  # room code per message
    room_short: list[str]  # short id per room code
    author: np.ndarray  # author code per message
    kind: np.ndarray  # 'person', 'ship' or 'system' per message
    created: np.ndarray
    reply_to: np.ndarray  # index of the message answered, or -1
    bodies: list[str] | None  # memory only; dropped once embedded


def limit_memory() -> None:
    soft, hard = resource.getrlimit(resource.RLIMIT_DATA)
    cap = MEMORY_CAP if hard == resource.RLIM_INFINITY else min(MEMORY_CAP, hard)
    resource.setrlimit(resource.RLIMIT_DATA, (cap, hard))


def peak_rss_mib() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KiB on Linux


def angle_from_dot(dots: np.ndarray) -> np.ndarray:
    """θ = 2·atan2(‖â−b̂‖, ‖â+b̂‖) for unit vectors, with ‖â∓b̂‖² = 2 ∓ 2⟨â,b̂⟩ in float64 (exact for unit vectors,
    and well-conditioned near 0 and π, where arccos is not)."""
    d = np.clip(np.asarray(dots, np.float64), -1.0, 1.0)
    return 2.0 * np.arctan2(np.sqrt(2.0 - 2.0 * d), np.sqrt(2.0 + 2.0 * d))


def angle_between(X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Row-wise θ = 2·atan2(‖x̂−ŷ‖, ‖x̂+ŷ‖) from the vectors themselves."""
    return 2.0 * np.arctan2(np.linalg.norm(X - Y, axis=1), np.linalg.norm(X + Y, axis=1))


def load_corpus(store: Path) -> Corpus:
    db = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    try:
        rows = db.execute(
            "SELECT m.id, m.room_id, m.author_id, u.kind, m.created, m.body FROM messages m "
            "JOIN users u ON u.id = m.author_id ORDER BY m.created, m.id").fetchall()
        replies = db.execute("SELECT message_id, reply_to FROM message_replies").fetchall()
    finally:
        db.close()
    ids = [r[0] for r in rows]
    rooms = sorted({r[1] for r in rows})
    authors = sorted({r[2] for r in rows})
    room_code = {r: i for i, r in enumerate(rooms)}
    author_code = {a: i for i, a in enumerate(authors)}
    shorts = [r[:6] for r in rooms]
    if len(set(shorts)) != len(shorts):
        raise SystemExit("two rooms share a short id; widen it")
    index = {m: i for i, m in enumerate(ids)}
    reply_to = np.full(len(ids), -1, np.int64)
    for message, answered in replies:
        if message in index and answered in index:
            reply_to[index[message]] = index[answered]
    return Corpus(
        ids=ids,
        room=np.array([room_code[r[1]] for r in rows], np.int64),
        room_short=shorts,
        author=np.array([author_code[r[2]] for r in rows], np.int64),
        kind=np.array([r[3] for r in rows]),
        created=np.array([r[4] for r in rows], np.float64),
        reply_to=reply_to,
        bodies=[r[5] for r in rows],
    )


def embed(corpus: Corpus, scratch: Path) -> tuple[np.ndarray, dict]:
    """Unit vectors for every message, from the shared embedder only; cached by id in the scratch file, with the
    cumulative embedding time and count (numbers only) so a run that reuses the cache still reports them."""
    import embeddings

    os.environ.setdefault("ENGRAM_EMBEDDER_SOCKET", SOCKET)
    provider = embeddings.create_embedding_provider()
    if not isinstance(provider, embeddings.RemoteEmbedProvider):
        raise SystemExit("refusing to embed without the shared embedder")
    db = sqlite3.connect(scratch)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS vectors(id TEXT PRIMARY KEY, v BLOB NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS counts(key TEXT PRIMARY KEY, value REAL NOT NULL)")
        cached = dict(db.execute("SELECT id, v FROM vectors"))
        todo = [i for i, m in enumerate(corpus.ids) if m not in cached]
        for start in range(0, len(todo), BATCH):
            batch = todo[start:start + BATCH]
            began = time.monotonic()
            # The service's model truncates each text at 2048 tokens (embeddings._MAX_TOKENS), as it does for Engram.
            vectors = provider.embed([corpus.bodies[i] for i in batch], prefix="search_document")
            rows = [(corpus.ids[i], np.asarray(v, np.float32).tobytes()) for i, v in zip(batch, vectors)]
            db.executemany("INSERT INTO vectors(id, v) VALUES (?, ?)", rows)
            for key, add in (("embed_seconds", time.monotonic() - began), ("embedded", len(rows))):
                db.execute("INSERT INTO counts(key, value) VALUES (?, ?) "
                           "ON CONFLICT(key) DO UPDATE SET value = value + excluded.value", (key, add))
            db.commit()
            cached.update(rows)
            print(f"embedded {min(start + BATCH, len(todo))}/{len(todo)}", file=sys.stderr, flush=True)
        totals = dict(db.execute("SELECT key, value FROM counts"))
    finally:
        db.close()
    V = np.stack([np.frombuffer(cached[m], np.float32) for m in corpus.ids]).astype(np.float64)
    V /= np.linalg.norm(V, axis=1, keepdims=True)
    return V, {"this_run": len(todo), "seconds": totals.get("embed_seconds", 0.0),
               "total": int(totals.get("embedded", 0))}


def duplicates(corpus: Corpus, V: np.ndarray) -> np.ndarray:
    """True for a message within DEDUP_THETA of an earlier message by the same author (corpus is in time order)."""
    dup = np.zeros(len(corpus.ids), bool)
    for a in np.unique(corpus.author):
        idx = np.flatnonzero(corpus.author == a)
        theta = angle_from_dot(V[idx] @ V[idx].T)
        earlier = np.tril(np.ones((len(idx), len(idx)), bool), -1)
        dup[idx] = ((theta < DEDUP_THETA) & earlier).any(axis=1)
    return dup


def sessions_of(corpus: Corpus, keep: np.ndarray) -> list[np.ndarray]:
    runs: dict[tuple[int, int], list[list[int]]] = {}
    for i in np.flatnonzero(keep):  # time order
        key = (int(corpus.room[i]), int(corpus.author[i]))
        group = runs.setdefault(key, [])
        if group and corpus.created[i] - corpus.created[group[-1][-1]] < GAP:
            group[-1].append(int(i))
        else:
            group.append([int(i)])
    sessions = [np.array(s) for group in runs.values() for s in group]
    sessions.sort(key=lambda s: (corpus.created[s[0]], s[0]))
    return sessions


def split(corpus: Corpus, sessions: list[np.ndarray]) -> float:
    starts = np.array([corpus.created[s[0]] for s in sessions])
    return float(np.percentile(starts, SPLIT_PERCENTILE))


def spherical_kmeans(X: np.ndarray, P: int, seed: int) -> np.ndarray:
    best, best_objective = None, -np.inf
    for restart in range(RESTARTS):
        rng = np.random.default_rng(seed + restart)
        C = np.empty((P, X.shape[1]))
        C[0] = X[rng.integers(len(X))]
        distance = np.maximum(1 - X @ C[0], 0)
        for c in range(1, P):  # k-means++ seeding on 1 - cos
            weights = distance ** 2
            total = weights.sum()
            C[c] = X[rng.choice(len(X), p=weights / total) if total > 0 else rng.integers(len(X))]
            distance = np.minimum(distance, np.maximum(1 - X @ C[c], 0))
        labels = None
        for _ in range(ITERATIONS):
            sims = X @ C.T
            new = sims.argmax(axis=1)
            if labels is not None and np.array_equal(new, labels):
                break
            labels = new
            sums = np.zeros_like(C)
            np.add.at(sums, labels, X)
            empty = np.flatnonzero(np.bincount(labels, minlength=P) == 0)
            if len(empty):  # reseed an empty place at the worst-fitted points
                worst = np.argsort(sims[np.arange(len(X)), labels])[: len(empty)]
                sums[empty] = X[worst]
            C = sums / np.linalg.norm(sums, axis=1, keepdims=True)
        objective = (X @ C.T).max(axis=1).sum()
        if objective > best_objective:
            best, best_objective = C, objective
    return best


def evaluate(corpus: Corpus, V: np.ndarray, keep: np.ndarray, P: int) -> dict:
    sessions = sessions_of(corpus, keep)
    cutoff = split(corpus, sessions)
    train = [s for s in sessions if corpus.created[s[0]] < cutoff]
    held = [(sid, s) for sid, s in enumerate(sessions) if corpus.created[s[0]] >= cutoff]
    train_msgs = np.concatenate(train)
    held_msgs = np.concatenate([s for _, s in held]) if held else np.array([], np.int64)

    C = spherical_kmeans(V[train_msgs], P, SEED + P)
    place = (V @ C.T).argmax(axis=1)
    theta_cc = angle_from_dot(C @ C.T)
    counts = np.zeros((P, P), np.int64)
    support = np.zeros((P, P), np.int64)  # distinct training sessions with the step
    train_steps = train_self = train_steps_after_cutoff = 0
    for s in train:
        seen = set()
        for a, b in zip(s[:-1], s[1:]):
            edge = (place[a], place[b])
            counts[edge] += 1
            seen.add(edge)
            train_steps += 1
            train_self += edge[0] == edge[1]
            train_steps_after_cutoff += corpus.created[b] >= cutoff
        for edge in seen:
            support[edge] += 1

    moved_in = counts.sum(axis=0) - np.diag(counts)  # training steps that moved into each place
    kept = np.flatnonzero(keep)  # time order
    room_index = {r: kept[corpus.room[kept] == r] for r in np.unique(corpus.room[kept])}
    room_times = {r: corpus.created[idx] for r, idx in room_index.items()}

    steps = [(a, b, sid) for sid, s in held for a, b in zip(s[:-1], s[1:])]
    steps.sort(key=lambda t: (corpus.created[t[1]], t[1]))
    n = len(steps)
    full = {arm: np.zeros(n, np.int64) for arm in ARMS}  # rank of place(b) among all places
    dropped = {arm: np.zeros(n, np.int64) for arm in ARMS}  # rank with place(a) removed; 0 on a self-step
    meta = {name: [] for name in ("sid", "kind", "room", "reply", "interjected", "move", "no_other", "support",
                                  "degree")}
    online = counts.copy()
    folded = 0  # steps, in order of b's time, already folded into the online counts
    arange = np.arange(P)

    def record(arm: str, j: int, order: np.ndarray, target: int, current: int) -> None:
        position = np.empty(P, np.int64)
        position[order] = arange
        full[arm][j] = position[target] + 1
        dropped[arm][j] = 0 if target == current else position[target] + 1 - (position[current] < position[target])

    def vote_order(pool: np.ndarray, a: int, position_i: np.ndarray) -> np.ndarray:
        votes = np.zeros(P, np.int64)
        nearest = np.full(P, np.inf)
        if len(pool):
            theta = angle_from_dot(V[pool] @ V[a])
            m = min(NEIGHBOURS, len(pool))
            top = np.argpartition(theta, m - 1)[:m]
            np.add.at(votes, place[pool[top]], 1)
            np.minimum.at(nearest, place[pool[top]], theta[top])
        return np.lexsort((position_i, nearest, -votes))

    for j, (a, b, sid) in enumerate(steps):
        tb = corpus.created[b]
        while folded < j and corpus.created[steps[folded][1]] < tb:
            fa, fb, _ = steps[folded]
            online[place[fa], place[fb]] += 1
            folded += 1
        target, s, r = place[b], place[a], corpus.room[a]

        order_i = np.lexsort((arange, angle_from_dot(C @ V[a])))
        position_i = np.empty(P, np.int64)
        position_i[order_i] = arange
        record("i", j, order_i, target, s)
        order_ii = np.lexsort((arange, theta_cc[s], -counts[s]))
        record("ii", j, order_ii, target, s)
        record("ii+", j, np.lexsort((arange, theta_cc[s], -online[s])), target, s)
        record("vii", j, np.lexsort((position_i, -moved_in)), target, s)

        before = room_index[r][: bisect_left(room_times[r], tb)]
        other = before[corpus.author[before] != corpus.author[a]]
        latest = other[-1] if len(other) else None
        record("iv", j, order_i if latest is None else np.lexsort((arange, angle_from_dot(C @ V[latest]))), target, s)

        earlier = keep & (corpus.created < tb)
        earlier[a] = False
        record("v", j, vote_order(np.flatnonzero(earlier & (corpus.author == corpus.author[a])), a, position_i),
               target, s)
        record("vi", j, vote_order(np.flatnonzero(earlier & (corpus.room == r)), a, position_i), target, s)

        answered = corpus.reply_to[b]
        top_move = next(t for t in order_ii if t != s)  # (ii)'s first choice once the current place is dropped
        meta["sid"].append(sid)
        meta["kind"].append(corpus.kind[a])
        meta["room"].append(corpus.room_short[r])
        meta["reply"].append("to-a" if answered == a else ("other" if answered >= 0 else "none"))
        meta["interjected"].append(latest is not None and corpus.created[latest] > corpus.created[a])
        meta["no_other"].append(latest is None)
        meta["move"].append(target != s)
        meta["support"].append(int(support[s, top_move]))
        meta["degree"].append(int((counts[s] > 0).sum() - (counts[s, s] > 0)))
    meta = {key: np.array(value) for key, value in meta.items()}

    # Drift: where training and held-out messages fall among the places.
    p_counts = np.bincount(place[train_msgs], minlength=P)
    q_counts = np.bincount(place[held_msgs], minlength=P) if len(held_msgs) else np.zeros(P, np.int64)
    p, q = p_counts / p_counts.sum(), q_counts / max(q_counts.sum(), 1)
    mid = (p + q) / 2

    def kl(x, y):
        nz = x > 0
        return float((x[nz] * np.log2(x[nz] / y[nz])).sum())

    def fit(msgs):
        return float(np.degrees(angle_between(V[msgs], C[place[msgs]])).mean()) if len(msgs) else float("nan")

    moves = meta["move"].astype(bool) if n else np.zeros(0, bool)
    drift = {
        "tv": 0.5 * float(np.abs(p - q).sum()),
        "js": 0.5 * kl(p, mid) + 0.5 * kl(q, mid),
        "thin": float(q[p_counts < 5].sum()),
        "train_places_used": int((p_counts > 0).sum()),
        "held_places_used": int((q_counts > 0).sum()),
        "fit_train": fit(train_msgs),
        "fit_held": fit(held_msgs),
        "stay_train": train_self / max(train_steps, 1),
        "stay_held": float(1 - moves.mean()) if n else float("nan"),
    }
    counts_out = {
        "messages": int(keep.sum()),
        "sessions": len(sessions),
        "train_sessions": len(train),
        "held_sessions": len(held),
        "train_steps": train_steps,
        "train_steps_after_cutoff": train_steps_after_cutoff,
        "held_steps": n,
        "cutoff": cutoff,
        "max_support": int(support.max()),
        "max_support_move": int((support * (1 - np.eye(P, dtype=np.int64))).max()),
    }
    return {"full": full, "dropped": dropped, "meta": meta, "drift": drift, "split": counts_out}


def message_level_facts(corpus: Corpus, keep: np.ndarray) -> dict:
    """The plan's first design, a trail graph over messages: support per edge, and held-out steps on trained nodes."""
    sessions = sessions_of(corpus, keep)
    cutoff = split(corpus, sessions)
    support: dict[tuple[int, int], int] = {}
    nodes = set()
    for s in sessions:
        if corpus.created[s[0]] < cutoff:
            for a, b in zip(s[:-1], s[1:]):
                support[(int(a), int(b))] = support.get((int(a), int(b)), 0) + 1
                nodes.update((int(a), int(b)))
    held = [(int(a), int(b)) for s in sessions if corpus.created[s[0]] >= cutoff for a, b in zip(s[:-1], s[1:])]
    out_degree: dict[int, int] = {}
    for a, _ in support:
        out_degree[a] = out_degree.get(a, 0) + 1
    return {
        "edges": len(support),
        "max_support": max(support.values(), default=0),
        "max_out_degree": max(out_degree.values(), default=0),
        "held_steps": len(held),
        "held_targets_trained": sum(b in nodes for _, b in held),
        "held_sources_trained": sum(a in nodes for a, _ in held),
    }


# Populations: (label, which ranking, mask builder). "full" ranks every place; "dropped" removes the current place.
POPULATIONS = {
    "moves-non-reply": ("place-changing, non-reply (falsifier)", "dropped", lambda m: m["move"] & m["nonreply"]),
    "moves": ("place-changing, all", "dropped", lambda m: m["move"]),
    "moves-reply-to-a": ("place-changing, b answers a", "dropped", lambda m: m["move"] & ~m["nonreply"]),
    "moves-answers-nothing": ("place-changing, b answers nothing", "dropped",
                              lambda m: m["move"] & (m["reply"] == "none")),
    "moves-ship": ("place-changing, non-reply, ship authors", "dropped",
                   lambda m: m["move"] & m["nonreply"] & (m["kind"] == "ship")),
    "moves-person": ("place-changing, non-reply, person authors", "dropped",
                     lambda m: m["move"] & m["nonreply"] & (m["kind"] == "person")),
    "moves-interjected": ("place-changing, non-reply, another author spoke between a and b", "dropped",
                          lambda m: m["move"] & m["nonreply"] & m["interjected"]),
    "all": ("all steps, self-steps included", "full", lambda m: np.ones(len(m["move"]), bool)),
    "non-reply": ("non-reply, self-steps included", "full", lambda m: m["nonreply"]),
}
BOOTSTRAPPED = ("moves-non-reply", "moves", "moves-answers-nothing", "moves-ship", "non-reply", "all")


def populations(result: dict) -> dict:
    m = dict(result["meta"])
    if not len(m["move"]):
        return {key: np.zeros(0, bool) for key in POPULATIONS}
    m["move"] = m["move"].astype(bool)
    m["interjected"] = m["interjected"].astype(bool)
    m["nonreply"] = m["reply"] != "to-a"
    return {key: build(m) for key, (_, _, build) in POPULATIONS.items()}


def bootstrap(ranks: dict, mask: np.ndarray, sid: np.ndarray, seed: int) -> dict | None:
    """Paired bootstrap clustered by session: one draw of sessions shared by every arm and every k."""
    if not mask.any():
        return None
    _, inv = np.unique(sid[mask], return_inverse=True)
    S = int(inv.max()) + 1
    rng = np.random.default_rng(seed)
    W = np.stack([np.bincount(d, minlength=S) for d in rng.integers(0, S, size=(RESAMPLES, S))]).astype(np.float64)
    denominator = W @ np.bincount(inv, minlength=S).astype(np.float64)
    out = {"sessions": S, "n": int(mask.sum())}
    for k in HITS:
        point, draws = {}, {}
        for arm in ARMS:
            hit = (ranks[arm][mask] <= k).astype(np.float64)
            point[arm] = float(hit.mean())
            draws[arm] = (W @ np.bincount(inv, weights=hit, minlength=S)) / denominator
        point_others = np.array([point[o] for o in OTHERS])
        point_four = np.array([point[o] for o in FOUR])
        d = draws["ii"] - np.stack([draws[o] for o in OTHERS], axis=1).max(axis=1)
        d4 = draws["ii"] - np.stack([draws[o] for o in FOUR], axis=1).max(axis=1)
        out[k] = {
            "hit": point,
            "D": float(point["ii"] - point_others.max()),
            "D_ci": tuple(float(x) for x in np.percentile(d, [2.5, 97.5])),
            "best_other": OTHERS[int(point_others.argmax())],
            "D4": float(point["ii"] - point_four.max()),
            "D4_ci": tuple(float(x) for x in np.percentile(d4, [2.5, 97.5])),
            "pairs": {o: (point["ii"] - point[o],
                          tuple(float(x) for x in np.percentile(draws["ii"] - draws[o], [2.5, 97.5])))
                      for o in OTHERS + ("ii+",)},
        }
    return out


def fmt(x: float) -> str:
    return "n/a" if x != x else f"{x:.3f}"


def signed(x: float) -> str:
    return f"{x:+.3f}"


def ci(pair: tuple[float, float]) -> str:
    return f"[{pair[0]:+.3f}, {pair[1]:+.3f}]"


def verdict(stats: dict | None) -> str:
    if stats is None:
        return "no steps"
    lo, hi = stats[FALSIFIER_HIT]["D_ci"]
    if lo > 0:
        return "(ii) beats all five"
    if hi < 0:
        return "(ii) loses"
    return "CI includes 0"


def hit_rows(rows: list[tuple[str, dict, np.ndarray]], k: int) -> list[str]:
    lines = ["| population | n | " + " | ".join(ARM_NAMES[a] for a in ARMS) + " |", "|---|---|" + "---|" * len(ARMS)]
    for label, ranks, mask in rows:
        n = int(mask.sum())
        lines.append(f"| {label} | {n} | " + " | ".join(
            fmt(float((ranks[a][mask] <= k).mean())) if n else "n/a" for a in ARMS) + " |")
    return lines


def report(path: Path, corpus: Corpus, dup: np.ndarray, facts: dict, results: dict, timing: dict) -> None:
    kinds = ("person", "ship", "system")
    L = ["# Experiment E1: does use carry information that meaning doesn't?", ""]
    L += ["2026-11-03. Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md` (sections 5 and 6), "
          "as revised after review. Script: `scripts/rail_e1.py`. Numbers only: rooms appear by short id and "
          "authors by kind (person, ship or system). No message text and no name appears here.", ""]

    L += ["## Why the plan's first design was not run", ""]
    L += ["Each message is written once, in one session, so the plan's trail graph over messages is a disjoint union "
          "of paths. Measured on this corpus, with duplicates and the same split:", ""]
    L += [f"- trained edges: {facts['edges']}; the largest support of any edge: {facts['max_support']}; the largest "
          f"out-degree of any message: {facts['max_out_degree']};",
          f"- held-out steps: {facts['held_steps']}; held-out next messages that are trained nodes: "
          f"{facts['held_targets_trained']}; held-out current messages that are trained nodes: "
          f"{facts['held_sources_trained']}.", ""]
    L += ["So arm (ii) as first written could never rank the true next message, and C2 had a single bucket. The "
          "revision quotients the sphere into places, so places recur and support grows past 1.", ""]

    L += ["## Pre-registration", "", PREREGISTRATION, ""]

    L += ["## Method", ""]
    L += [
        f"- **Corpus.** The station store's `messages` table, opened with `mode=ro`: {len(corpus.ids)} messages in "
        f"{len(corpus.room_short)} rooms by {len(np.unique(corpus.author))} authors (by kind: "
        + ", ".join(f"{k} {int((corpus.kind == k).sum())}" for k in kinds) + "). "
        f"`message_replies` links {int((corpus.reply_to >= 0).sum())} messages to the message each answers.",
        "- **Embedding.** The shared embedder only (`RemoteEmbedProvider` over its socket), with the "
        f"`search_document:` prefix and batches of {BATCH}. The service's model truncates at 2048 tokens. Vectors are "
        "L2-normalized. The angle is `θ = 2·atan2(‖â−b̂‖, ‖â+b̂‖)`, in float64.",
        f"- **Duplicates.** A message within `θ < {DEDUP_THETA}` rad of an earlier message by the same author is a "
        f"templated repeat. There are {int(dup.sum())} (by kind: " + ", ".join(
            f"{k} {int((dup & (corpus.kind == k)).sum())}" for k in kinds) + "). Both versions run: *with "
        "duplicates*, and *deduplicated*, where repeats are removed before sessions are cut.",
        "- **Sessions and split.** A session is a maximal run of one author's messages in one room with gaps under "
        "30 minutes. Steps join consecutive messages. Sessions starting before the 80th percentile of session start "
        "times train, and the rest are held out.",
        "- **Places.** Spherical k-means (k-means++ seeding, 4 restarts, the best objective kept) on the training "
        "messages only, for `P` in {32, 64, 128}. A message's place is its nearest centroid. Counts and support come "
        "from training steps only. Support is the number of distinct training sessions with that place-to-place "
        "step.",
        "- **Arms.** Each arm ranks all `P` places. hit@k asks whether `place(b)` is among the first `k`.",
        "  - (i) ranks places by θ from `a` to each centroid.",
        "  - (ii) ranks places by training transition count from `place(a)`, with ties and backfill by θ between "
        "centroids.",
        "  - (iv) ranks places by θ from the room's latest message by another author before `b`, falling back to (i) "
        "when there is none.",
        f"  - (v) and (vi) take the `m = {NEIGHBOURS}` nearest earlier messages to `a` (before `b`, `a` excluded), "
        "by the same author for (v) and in the same room for (vi). They vote for their places, with ties broken by "
        "the nearest member, then backfill in (i)'s order.",
        "  - (vii) ranks places by how often training steps moved into them from another place, with ties in (i)'s "
        "order. It is the base rate that (ii) carries too, and it doesn't depend on `a`.",
        "  - (ii+) is (ii) with counts that also take held-out steps finished before `b`. It is secondary and "
        "outside the falsifier.",
        "  - The plan's A* arm measures reachability toward the true next vector, not prediction, so it was dropped.",
        "- **Steps.**",
        "  - A *self-step* stays in its place, and every arm gets it nearly free, since (i) ranks the current place "
        "first.",
        "  - On *place-changing* steps every ranking drops the current place before hit@k is taken.",
        "  - *Non-reply* means `b` does not answer `a`.",
        "- **Intervals.** As pre-registered: paired, clustered by held-out session, 1,000 resamples, percentile 95%.",
        "",
    ]

    L += ["## The falsifier, every version and P", ""]
    L += ["`D@k = hit@k(ii) − max over (i), (iv), (v), (vi), (vii) of hit@k`, on place-changing, non-reply held-out "
          "steps, with the current place dropped. `D4@10` leaves out (vii). The best other arm is named at the point "
          "estimate.", ""]
    L += ["| version | P | steps | sessions | D@1 [95% CI] | D@5 [95% CI] | D@10 [95% CI] | D4@10 [95% CI] | "
          "best other @10 | verdict @10 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for (version, P), res in results.items():
        st = res["stats"]["moves-non-reply"]
        mark = " (primary)" if (version, P) == PRIMARY else ""
        if st is None:
            L.append(f"| {version}{mark} | {P} | 0 | 0 | | | | | | no steps |")
            continue
        L.append(f"| {version}{mark} | {P} | {st['n']} | {st['sessions']} | "
                 + " | ".join(f"{signed(st[k]['D'])} {ci(st[k]['D_ci'])}" for k in HITS)
                 + f" | {signed(st[FALSIFIER_HIT]['D4'])} {ci(st[FALSIFIER_HIT]['D4_ci'])}"
                 + f" | {ARM_NAMES[st[FALSIFIER_HIT]['best_other']]} | {verdict(st)} |")
    L.append("")

    L += ["## hit@10 for every version and P", ""]
    L += ["Place-changing, non-reply steps, with the current place dropped:", ""]
    L += hit_rows([(f"{v}, P={P}", r["dropped"], r["masks"]["moves-non-reply"]) for (v, P), r in results.items()],
                  FALSIFIER_HIT)
    L += ["", "All held-out steps, self-steps included, with full rankings:", ""]
    L += hit_rows([(f"{v}, P={P}", r["full"], r["masks"]["all"]) for (v, P), r in results.items()], FALSIFIER_HIT)
    L.append("")

    prim = results[PRIMARY]
    L += [f"## The primary cell in detail ({PRIMARY[0]}, P = {PRIMARY[1]})", ""]
    for k in HITS:
        L += [f"hit@{k}:", ""]
        L += hit_rows([(label, prim[ranking], prim["masks"][key]) for key, (label, ranking, _) in POPULATIONS.items()],
                      k)
        L.append("")

    st = prim["stats"]["moves-non-reply"]
    if st:
        L += ["### (ii) against each arm on the falsifier's population", ""]
        L += ["| k | " + " | ".join(f"(ii) − {ARM_NAMES[o]} [95% CI]" for o in OTHERS + ("ii+",)) + " |",
              "|---|" + "---|" * (len(OTHERS) + 1)]
        for k in HITS:
            L.append(f"| {k} | " + " | ".join(f"{signed(st[k]['pairs'][o][0])} {ci(st[k]['pairs'][o][1])}"
                                              for o in OTHERS + ("ii+",)) + " |")
        L.append("")
    L += ["### D@10 on other populations", ""]
    L += ["| population | n | sessions | D@10 [95% CI] | D4@10 [95% CI] | best other @10 |", "|---|---|---|---|---|---|"]
    for key in BOOTSTRAPPED:
        s2 = prim["stats"].get(key)
        if s2:
            L.append(f"| {POPULATIONS[key][0]} | {s2['n']} | {s2['sessions']} | {signed(s2[10]['D'])} "
                     f"{ci(s2[10]['D_ci'])} | {signed(s2[10]['D4'])} {ci(s2[10]['D4_ci'])} | "
                     f"{ARM_NAMES[s2[10]['best_other']]} |")
    L.append("")

    L += ["### By room, on the falsifier's population", ""]
    L += ["| room | n | sessions | " + " | ".join(f"{ARM_NAMES[a]} @10" for a in ARMS) + " | D@10 |",
          "|---|---|---|" + "---|" * (len(ARMS) + 1)]
    for room in sorted(set(prim["meta"]["room"])):
        mask = prim["masks"]["moves-non-reply"] & (prim["meta"]["room"] == room)
        if not mask.any():
            continue
        h = {a: float((prim["dropped"][a][mask] <= 10).mean()) for a in ARMS}
        L.append(f"| {room} | {int(mask.sum())} | {len(np.unique(prim['meta']['sid'][mask]))} | "
                 + " | ".join(fmt(h[a]) for a in ARMS) + f" | {signed(h['ii'] - max(h[o] for o in OTHERS))} |")
    L.append("")

    L += ["### C2: (ii)'s hit rate by the support of its top edge, on the falsifier's population", ""]
    L += ["`t*` is (ii)'s first choice once the current place is dropped. Support is the number of distinct training "
          "sessions with the step `place(a) → t*`, and 0 means `place(a)` has no trained step to another place, so "
          "(ii) falls back to centroid angle. Out-degree is the number of distinct other places `place(a)` stepped "
          "to in training.", ""]
    mask = prim["masks"]["moves-non-reply"]
    sup, deg = prim["meta"]["support"], prim["meta"]["degree"]
    support_labels = ("0", "1", "2", "3-4", "5-9", "10+")
    sup_label = np.array(["0" if v == 0 else "1" if v == 1 else "2" if v == 2 else "3-4" if v <= 4 else
                          "5-9" if v <= 9 else "10+" for v in sup])
    if mask.any():  # out-degree in tertiles of the population, so the columns hold similar counts
        lo, hi = (int(x) for x in np.quantile(deg[mask], [1 / 3, 2 / 3]))
    else:
        lo, hi = 0, 0
    degree_labels = (f"≤{lo}", f"{lo + 1}-{hi}", f"≥{hi + 1}")
    deg_label = np.array([degree_labels[0] if v <= lo else degree_labels[1] if v <= hi else degree_labels[2]
                          for v in deg])
    L += ["| top-edge support | n | (ii) @1 | (i) @1 | (vii) @1 | (ii) @10 | (i) @10 | (vii) @10 |",
          "|---|---|---|---|---|---|---|---|"]
    for label in support_labels:
        m2 = mask & (sup_label == label)
        if m2.any():
            L.append(f"| {label} | {int(m2.sum())} | " + " | ".join(
                fmt(float((prim["dropped"][a][m2] <= k).mean())) for k in (1, 10) for a in ("ii", "i", "vii")) + " |")
    L += ["", "(ii) @1, rows by top-edge support and columns by out-degree (tertiles of this population), with n:", ""]
    L += ["| support \\ out-degree | " + " | ".join(degree_labels) + " |", "|---|---|---|---|"]
    for s_label in support_labels:
        row = []
        for d_label in degree_labels:
            m2 = mask & (sup_label == s_label) & (deg_label == d_label)
            row.append(f"{fmt(float((prim['dropped']['ii'][m2] <= 1).mean()))} (n={int(m2.sum())})" if m2.any()
                       else "")
        if any(row):
            L.append(f"| {s_label} | " + " | ".join(row) + " |")
    L.append("")

    L += ["## Split and drift, every version and P", ""]
    L += ["Drift compares where training and held-out messages fall among the places.",
          "",
          "- *TV* is the total variation distance between the two occupancy distributions.",
          "- *JS* is the Jensen-Shannon divergence in bits.",
          "- *thin* is the share of held-out messages in places that hold fewer than 5 training messages.",
          "- *fit* is the mean angle in degrees from a message to its centroid.",
          "- *stay* is the share of steps that stay in their place.",
          "- *max support* is over all steps, and over place-changing steps only.",
          ""]
    L += ["| version | P | messages | sessions train/held | steps train/held | train steps after cutoff | max support "
          "all/moving | places used train/held | TV | JS | thin | fit train/held | stay train/held |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (version, P), res in results.items():
        sp, dr = res["split"], res["drift"]
        L.append(f"| {version} | {P} | {sp['messages']} | {sp['train_sessions']}/{sp['held_sessions']} | "
                 f"{sp['train_steps']}/{sp['held_steps']} | {sp['train_steps_after_cutoff']} | "
                 f"{sp['max_support']}/{sp['max_support_move']} | "
                 f"{dr['train_places_used']}/{dr['held_places_used']} | {fmt(dr['tv'])} | {fmt(dr['js'])} | "
                 f"{fmt(dr['thin'])} | {dr['fit_train']:.1f}/{dr['fit_held']:.1f} | "
                 f"{fmt(dr['stay_train'])}/{fmt(dr['stay_held'])} |")
    L.append("")
    cutoffs = sorted({datetime.fromtimestamp(r["split"]["cutoff"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                      for r in results.values()})
    pm, meta = prim["masks"], prim["meta"]
    L += [f"Split cutoffs (80th percentile of session starts): {', '.join(cutoffs)}.", "",
          "Held-out steps in the primary cell:", "",
          f"- {int(pm['all'].sum())} in all, of which {int(pm['moves'].sum())} change place;",
          f"- among the place-changing steps: {int(pm['moves-non-reply'].sum())} non-reply, "
          f"{int(pm['moves-reply-to-a'].sum())} where `b` answers `a`, and {int(pm['moves-answers-nothing'].sum())} "
          "where `b` answers nothing;",
          f"- {int(meta['no_other'].sum()) if len(meta['no_other']) else 0} steps where (iv) had no other author's "
          "message in the room before `b`, so it fell back to (i).", ""]

    L += ["## Resources", ""]
    L += [f"- Peak RSS of the analysis run: {timing['rss']:.1f} MiB (cap 512 MiB; `RLIMIT_DATA` set to 512 MiB "
          "in the process).",
          f"- Wall time of the analysis run: {timing['wall']:.0f} s.",
          f"- Embedding: {timing['embed']['total']} texts through the shared embedder in "
          f"{timing['embed']['seconds']:.0f} s of request time ({timing['embed']['this_run']} of them in this run; "
          "the rest came from the run's scratch cache, which an earlier `--embed-only` run filled with the same "
          f"embed function and bounds, at a peak RSS of {timing['embed_rss']}).",
          "- Scratch: ids, vectors and counts in a SQLite file under /var/tmp, deleted at the end of the run.", ""]

    L += ["## Reading", "", "<!-- reading -->", ""]
    path.write_text("\n".join(L))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--scratch", type=Path, help="use this scratch file (it is deleted at the end unless --keep)")
    parser.add_argument("--keep", action="store_true", help="keep the scratch file (only for --embed-only)")
    parser.add_argument("--embed-only", action="store_true", help="fill the scratch file's vectors and stop")
    parser.add_argument("--embed-rss", default="not measured", help="peak RSS the embed-only run printed")
    args = parser.parse_args(argv)
    if args.keep and not args.embed_only:
        parser.error("--keep is only for --embed-only: an analysis run deletes its scratch")

    started = time.monotonic()
    limit_memory()
    if args.scratch:
        scratch = args.scratch
    else:
        handle, name = tempfile.mkstemp(prefix="rail-e1-", suffix=".sqlite3", dir=SCRATCH_DIR)
        os.close(handle)
        scratch = Path(name)
    try:
        corpus = load_corpus(args.store)
        V, embedded = embed(corpus, scratch)
        corpus.bodies = None  # the words are not needed past this point
        if args.embed_only:
            print(f"vectors: {len(V)}; peak RSS {peak_rss_mib():.1f} MiB", file=sys.stderr)
            return 0

        dup = duplicates(corpus, V)
        everything = np.ones(len(corpus.ids), bool)
        facts = message_level_facts(corpus, everything)
        results = {}
        for version, keep in (("deduplicated", ~dup), ("with duplicates", everything)):
            for P in PLACES:
                res = evaluate(corpus, V, keep, P)
                res["masks"] = populations(res)
                res["stats"] = {key: bootstrap(res[POPULATIONS[key][1]], res["masks"][key], res["meta"]["sid"], SEED)
                                for key in BOOTSTRAPPED}
                results[(version, P)] = res
                print(f"{version} P={P}: done", file=sys.stderr, flush=True)
        timing = {"rss": peak_rss_mib(), "wall": time.monotonic() - started, "embed": embedded,
                  "embed_rss": args.embed_rss}
        report(args.report, corpus, dup, facts, results, timing)
        print(f"report: {args.report}; peak RSS {timing['rss']:.1f} MiB; wall {timing['wall']:.0f} s",
              file=sys.stderr)
    finally:
        if not args.keep:
            for suffix in ("", "-journal", "-wal", "-shm"):
                Path(f"{scratch}{suffix}").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
