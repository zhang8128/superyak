#!/usr/bin/env python3
"""Experiment E1′ of the rail-mathematics plan (docs/superpowers/specs/2026-11-03-rail-mathematics.md, section 6′,
revision 3 at e2ba0a3e). On Engram's recall log: does use, meaning what a session recalled next, rank the next
recall's new memories better than meaning, popularity, co-retrieval and session history do? And does the order of
recalls carry that information, beyond which recalls share a session?

A session's recalls in time order are a footpath. Consecutive recalls of the same id set collapse into one, and a step
`a → b` counts when Jaccard(a, b) ≤ 0.5. The target is `b ∖ a` within the universe: memories with a vector now whose
`created_at` is at or before `b`. Each arm ranks 10 memories, leaving out `a`'s own ids, and is backfilled by (i):

  (i)     meaning: angle from the centroid of a's vectors
  (i′)    nearest to any: the smallest angle to any of a's vectors
  (ii)    use: training counts c(x, y) for x in a and y in the next recall's new ids, summed over a's ids
  (iii)   popularity, pure: how often each memory was returned in training
  (iii-m) popularity, matched: as many popularity slots as (ii) had counted candidates, then (i)
  (iv)    co-retrieval: training counts of memories returned in the same recall as a's ids, summed over them
  (v)     session history: ids returned earlier in the session, before a, newest first
  (ii-s)  (ii) trained on each training session's recalls in shuffled order; 20 seeded shuffles, averaged

D = hit@10(ii) − max(i, i′, iii, iii-m, iv, v), with the max inside each resample, and D_order = hit@10(ii) −
hit@10(ii-s). Intervals are BCa from a bootstrap clustered by session (10,000 resamples), checked against one clustered
by day.

Bounds. The store opens as the live file with a `mode=ro` URI and `query_only`, and every read happens inside one read
transaction, through the projections the plan lists: the session and recall ids from `context`, the row's time, its
layer, `target_ids`, and whether its outcome starts `used` or `used: auto`; and each memory's vector and `created_at`.
No query text and no outcome text is read. Vectors stay in memory. Ids become integer codes as they are read. The
output is aggregate numbers only, with times no finer than a day, and an exception prints its type and line only.
RLIMIT_DATA is capped at 512 MiB, and peak RSS is checked against the same cap.

`--synthetic order|noorder|realistic-order|realistic-noorder` builds a planted log in a shared-cache in-memory SQLite
database (nothing on disk) with Engram's table names and reads it through the same code. Every run first checks the
outcome classifier at each boundary; `--self-check` runs only that check.

Run:
  /home/andy/superyak/engram/.venv/bin/python -I scripts/rail_e1_prime.py --synthetic order --report PATH
  /home/andy/superyak/engram/.venv/bin/python -I scripts/rail_e1_prime.py --store ~/.engram/instances/NAME/graph.db \\
      --config PROJECT/.engram/config.toml --report PATH
"""

from __future__ import annotations

import os

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_name, "1")  # before numpy: one BLAS thread, bounded buffers

import argparse
import hashlib
import json
import resource
import sqlite3
import sys
import time
import tomllib
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import numpy as np

MEMORY_CAP = 512 * 1024 * 1024
DAY = 86400.0

# engram commit 548c97dd ("feat: score recall with recency as a tiebreak", 2026-09-01T20:08:04-07:00) made
# `recency_mode = "tiebreak"` the default. Recalls from that instant on form the primary period.
TIEBREAK_COMMIT = "548c97dd"
PRIMARY_START = datetime(2026, 9, 2, 3, 8, 4, tzinfo=timezone.utc).timestamp()

SPLIT_PERCENTILE = 80
JACCARD_MAX = 0.5
TOP = 10
HITS = (1, 5, 10)
RESAMPLES = 10_000
CHUNK = 500  # resamples per block, so the weight matrix stays small
SHUFFLES = 20
DELTA = 0.05
DELTA_ORDER = 0.02  # section 6′ (amended): order needs D_order's lower bound above this margin
MIN_STEPS, MIN_SESSIONS, MAX_SESSION_SHARE = 200, 20, 0.15
SEED = 20261103

ARMS = ("i", "i'", "ii", "iii", "iii-m", "iv", "v")
OTHERS = ("i", "i'", "iii", "iii-m", "iv", "v")  # the arms (ii) must beat
COL = {arm: j for j, arm in enumerate(ARMS)}
ARM_NAMES = {
    "i": "(i) meaning",
    "i'": "(i′) nearest",
    "ii": "(ii) use",
    "iii": "(iii) popularity",
    "iii-m": "(iii-m) popularity, matched",
    "iv": "(iv) co-retrieval",
    "v": "(v) history",
    "ii-s": "(ii-s) use, shuffled",
}

CHOICES = [
    "**Primary period.** It starts at the commit time of engram `548c97dd` (2026-09-02 03:08 UTC), the commit that "
    "made `tiebreak` the default. Recalls at or after it are primary; earlier ones form the additive period.",
    "**Config check.** It looks at `config.toml` in the store's directory, in every `.engram` directory above the "
    "store, and in each `--config` file. The run stops if any sets `[memory] recency_mode` to anything but "
    "`tiebreak`, or can't be read. Engram's server reads the config of the session's project root, which the script "
    "can't find by itself, so a real run names each project's `.engram/config.toml` with `--config`.",
    "**Left out and counted.** Recalls with no session id (or a `context` that isn't valid JSON), and rows whose time "
    "or `target_ids` can't be parsed.",
    "**Instinct recalls.** They're removed before footpaths are built, so they don't split a session's sequence, and "
    "counted apart. No arm can rank them: instincts have no vectors in the universe.",
    "**Order and collapse.** Recalls are ordered by time, then by recall id for equal times. Consecutive recalls with "
    "the same id set (as a set) merge into one run, which takes its first recall's time. The run counts as used if any "
    "member was used, and as explicit if any member was used without `auto`.",
    "**Jaccard.** Jaccard and collapse use the logged id sets, instinct ids included. Jaccard(∅, ∅) = 1.",
    "**Cutoff.** `T` is numpy's linearly interpolated 80th percentile of the times of the period's analysed recalls "
    "(not instinct, with a session id), taken before collapse.",
    "**Training and test.** A session's training sequence is its recalls before `T`, collapsed. A test session's "
    "first recall is strictly after `T`. A session that spans `T` gives training pairs before `T` and no test steps.",
    "**Training pairs.** They follow the Jaccard rule but not the test's vector and target rules. A pair with nothing "
    "new in `b` adds no counts.",
    "**Popularity and co-retrieval.** Both count the collapsed training recalls, each run once.",
    "**Which ids count.** (ii) and (iv) sum counts over all of `a`'s logged ids, with or without a vector. The meaning "
    "arms use `a`'s ids that are in the universe at `b`'s time.",
    "**hit@k.** A step hits when any target id is among the arm's first k.",
    "**Ties.** Count arms order by count, then by (i)'s order (dot with `a`'s centroid), then by code (`created_at` "
    "order). (i) and (i′) break exact ties by code.",
    "**History (v).** It walks back through the session's collapsed recalls before `a`, newest first, taking ids in "
    "each recall's logged order and skipping `a`'s ids and ids outside the universe.",
    "**Matched popularity.** Slots = min(10, the number of candidates with a positive (ii) score). The slots fill by "
    "popularity, then the rest by (i).",
    "**Shuffles.** As section 6′ now says, each training session's pre-`T` recalls are collapsed once, from real "
    "order. Each shuffle permutes those runs with a seeded generator, then forms consecutive pairs and applies the "
    "Jaccard rule and the `b ∖ a` mirroring. It never re-collapses. Per-step hit@10 is averaged over the 20 shuffles.",
    "**Day clusters.** The UTC day of the session's first recall, so each session sits in one day.",
    "**BCa.** 10,000 multinomial cluster resamples, seeded. `z0` comes from the share of resamples below the estimate, "
    "with ties counting half, clipped to [0.5/B, 1 − 0.5/B]. The acceleration comes from the leave-one-cluster-out "
    "jackknife.",
    "**Null of the null.** Shuffle set A uses seed streams (seed, period, j) and set B uses (seed, period, 1, j), for j "
    "= 0 to 19. D_null = hit@10(set B) − hit@10(set A). Its bootstraps use the very resample draws of D_order's.",
    "**Order.** δ_order = max(0.02, the 95th percentile of D_null's session bootstrap distribution, which is the raw "
    "distribution, not BCa). \"Order carries information\" needs D_order's session BCa lower bound above δ_order and "
    "its day BCa lower bound above the same δ_order. With one cluster there's no null distribution, and order can't "
    "be claimed.",
    "**Insufficient.** Test sessions are those with at least one primary step. When the data are insufficient, no "
    "interval is computed: only counts and point hit rates appear.",
    "**Additive period.** It runs the same pipeline on its own: its own `T`, with training inside it. It's secondary "
    "and decides nothing.",
    "**Universe.** A vector with no `created_at` row, or a zero norm, is left out and counted. An id in both vector "
    "tables is kept once.",
    "**C2 analogue.** `y*` is (ii)'s top memory and `x*` the id in `a` with the largest c(x, y*). Support is the number "
    "of distinct training sessions with a pair carrying x* → y*.",
]


class Stop(Exception):
    """A stop whose message the script wrote itself, so it holds no row."""


# --------------------------------------------------------------------------------------------------- resources


def limit_memory() -> bool:
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_DATA)
        cap = MEMORY_CAP if hard == resource.RLIM_INFINITY else min(MEMORY_CAP, hard)
        resource.setrlimit(resource.RLIMIT_DATA, (cap, hard))
        return True
    except (ValueError, OSError):
        return False


def peak_rss_mib() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024  # bytes on macOS, KiB on Linux


def guard(stage: str) -> None:
    if peak_rss_mib() > MEMORY_CAP / (1024 * 1024):
        raise Stop(f"peak RSS passed 512 MiB during {stage}")


# --------------------------------------------------------------------------------------------------- reading


@dataclass
class Log:
    t: np.ndarray  # recall time, epoch seconds; rows in (time, recall id) order
    session: np.ndarray  # session code, -1 when the row has none
    instinct: np.ndarray  # layer 'instinct'
    ids: list[np.ndarray]  # memory codes per recall, logged order, deduplicated
    sets: list[frozenset]
    used: np.ndarray  # outcome LIKE 'used%'
    auto: np.ndarray  # outcome LIKE 'used: auto%'
    unparsed: int = 0
    no_context: int = 0


@dataclass
class Universe:
    V: np.ndarray  # float32 unit vectors, rows in created_at order; a memory's code is its row
    created: np.ndarray  # epoch seconds, ascending
    tables: dict = field(default_factory=dict)  # vectors kept per table
    no_created: int = 0
    zero: int = 0
    bad_size: int = 0
    both_tables: int = 0
    n_codes: int = 0  # universe codes plus codes for logged ids with no vector


def parse_time(value) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def open_reader(uri: str) -> sqlite3.Connection:
    import sqlite_vec

    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


VECTOR_TABLES = (("episode", "episode_vectors", "episodes"), ("semantic", "semantic_vectors", "semantics"))
RECALL_SQL = (
    "SELECT CASE WHEN json_valid(context) THEN json_extract(context, '$.session_id') END, "
    "CASE WHEN json_valid(context) THEN json_extract(context, '$.recall_id') END, "
    "timestamp, layer, target_ids, coalesce(outcome LIKE 'used%', 0), coalesce(outcome LIKE 'used: auto%', 0) "
    "FROM memory_log WHERE event_type = 'recall'")


def read_store(conn: sqlite3.Connection) -> tuple[Log, Universe]:
    """Everything inside one read transaction, so the log and the vectors are one snapshot."""
    conn.execute("BEGIN")
    try:
        uni, code_of = read_vectors(conn)
        log = read_log(conn, code_of, uni)
    finally:
        conn.execute("COMMIT")
    return log, uni


def read_vectors(conn: sqlite3.Connection) -> tuple[Universe, dict]:
    total = sum(conn.execute(f"SELECT count(*) FROM {vt}").fetchone()[0] for _, vt, _ in VECTOR_TABLES)
    uni = Universe(V=np.empty((0, 0), np.float32), created=np.empty(0))
    V, created, row_of, n, dim = None, np.empty(total), {}, 0, None
    for layer, vt, mt in VECTOR_TABLES:
        kept = 0
        cursor = conn.execute(f"SELECT v.id, v.embedding, (SELECT m.created_at FROM {mt} m WHERE m.id = v.id) "
                              f"FROM {vt} v")
        for memory, blob, created_at in cursor:
            if memory in row_of:
                uni.both_tables += 1
                continue
            if not isinstance(blob, bytes) or not blob or len(blob) % 4:
                uni.bad_size += 1
                continue
            if dim is None:
                dim = len(blob) // 4
                if total * dim * 4 > MEMORY_CAP // 2:
                    raise Stop("the vectors alone would take over half the memory cap")
                V = np.empty((total, dim), np.float32)
            if len(blob) != 4 * dim:
                uni.bad_size += 1
                continue
            moment = parse_time(created_at)
            if moment is None:
                uni.no_created += 1
                continue
            v = np.frombuffer(blob, np.float32).astype(np.float64)
            norm = float(np.linalg.norm(v))
            if not np.isfinite(norm) or norm == 0.0:
                uni.zero += 1
                continue
            V[n] = v / norm
            created[n] = moment
            row_of[memory] = n
            n += 1
            kept += 1
        uni.tables[layer] = kept
    if V is None:
        V, dim = np.empty((0, 0), np.float32), 0
    order = np.argsort(created[:n], kind="stable")
    rank = np.empty(n, np.int64)
    rank[order] = np.arange(n)
    uni.V = V[:n][order]
    del V
    uni.created = created[:n][order]
    code_of = {memory: int(rank[row]) for memory, row in row_of.items()}
    uni.n_codes = n
    return uni, code_of


def read_log(conn: sqlite3.Connection, code_of: dict, uni: Universe) -> Log:
    session_code: dict = {}
    extra: dict = {}  # logged ids with no vector get codes above the universe
    rows = []
    unparsed = no_context = 0
    for session, recall, stamp, layer, targets, used, auto in conn.execute(RECALL_SQL):
        moment = parse_time(stamp)
        try:
            listed = json.loads(targets) if targets else []
        except (TypeError, ValueError):
            listed = None
        if moment is None or not isinstance(listed, list):
            unparsed += 1
            continue
        codes = []
        for memory in listed:
            if not isinstance(memory, str):
                continue
            code = code_of.get(memory)
            if code is None:
                code = extra.setdefault(memory, uni.n_codes + len(extra))
            codes.append(code)
        codes = list(dict.fromkeys(codes))  # dedupe, keeping logged order
        if isinstance(session, str) and session:
            s = session_code.setdefault(session, len(session_code))
        else:
            s = -1
            no_context += 1
        rows.append((moment, recall if isinstance(recall, str) else "", s, layer == "instinct", codes, bool(used),
                     bool(auto)))
    rows.sort(key=lambda r: (r[0], r[1]))
    uni.n_codes += len(extra)
    return Log(
        t=np.array([r[0] for r in rows], np.float64),
        session=np.array([r[2] for r in rows], np.int64),
        instinct=np.array([r[3] for r in rows], bool),
        ids=[np.array(r[4], np.int64) for r in rows],
        sets=[frozenset(r[4]) for r in rows],
        used=np.array([r[5] for r in rows], bool),
        auto=np.array([r[6] for r in rows], bool),
        unparsed=unparsed,
        no_context=no_context,
    )


def check_config(store: Path, named: list[Path]) -> dict:
    candidates = [store.parent / "config.toml"]
    candidates += [parent / "config.toml" for parent in store.resolve().parents if parent.name == ".engram"]
    for path in named:
        if not path.expanduser().is_file():
            raise Stop("a --config file does not exist")
        candidates.append(path.expanduser())
    seen, modes = set(), []
    for path in candidates:
        key = path.resolve()
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        try:
            raw = tomllib.loads(path.read_text())
        except (OSError, ValueError):
            raise Stop("a config.toml could not be read, so recency_mode can't be checked") from None
        mode = raw.get("memory", {}).get("recency_mode") if isinstance(raw.get("memory"), dict) else None
        if mode is not None and mode != "tiebreak":
            raise Stop("a config.toml sets [memory] recency_mode to something other than tiebreak; the plan stops here")
        modes.append("tiebreak" if mode else "unset (default tiebreak)")
    return {"looked": len({p.resolve() for p in candidates}), "found": len(modes), "modes": modes,
            "named": len(named)}


# --------------------------------------------------------------------------------------------------- synthetic


SYNTHETIC_KINDS = ("order", "noorder", "realistic-order", "realistic-noorder")
DEFAULT_SESSIONS = {"order": 160, "noorder": 160, "realistic-order": 120, "realistic-noorder": 120}
# The realistic plant's order effect: after a topic, the footpath jumps to that topic's fixed next set with this
# probability on a jump (else to a random topic). Chosen so that D@10 sits near 0.10 to 0.15.
P_FOLLOW = 0.6


def unit(x: np.ndarray) -> np.ndarray:
    return x / np.linalg.norm(x, axis=-1, keepdims=True)


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def midnight(y: int, mo: int, d: int) -> float:
    return datetime(y, mo, d, tzinfo=timezone.utc).timestamp()


LOG_START, LOG_END = midnight(2026, 9, 10), midnight(2026, 10, 30)


def synthetic(kind: str, sessions: int | None = None) -> tuple[sqlite3.Connection, str, dict]:
    """A planted log in a shared-cache in-memory database, with Engram's tables and row shapes. See plant_simple and
    plant_realistic for what is planted. Every log also carries 40 instinct recalls, 20 recalls with no session id and
    50 non-recall rows, so each filter is exercised."""
    import sqlite_vec

    rng = np.random.default_rng((SEED, SYNTHETIC_KINDS.index(kind) + 1))
    uri = f"file:rail-e1-prime-{kind}-{os.getpid()}?mode=memory&cache=shared"
    db = sqlite3.connect(uri, uri=True)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    dim = 768
    db.executescript(f"""
        CREATE TABLE memory_log (id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, event_type TEXT NOT NULL,
            layer TEXT NOT NULL, target_ids JSON, context JSON, outcome TEXT);
        CREATE TABLE episodes (id TEXT PRIMARY KEY, content TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE semantics (id TEXT PRIMARY KEY, content TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE VIRTUAL TABLE episode_vectors USING vec0(id TEXT PRIMARY KEY, embedding float[{dim}]);
        CREATE VIRTUAL TABLE semantic_vectors USING vec0(id TEXT PRIMARY KEY, embedding float[{dim}]);
    """)

    def memory(name: str, vector: np.ndarray | None, created: float, semantic: bool = False,
               row: bool = True) -> None:
        table = "semantic" if semantic else "episode"
        if row:
            db.execute(f"INSERT INTO {table}s (id, content, created_at) VALUES (?, '', ?)", (name, iso(created)))
        if vector is not None:
            db.execute(f"INSERT INTO {table}_vectors (id, embedding) VALUES (?, ?)",
                       (name, np.asarray(vector, np.float32).tobytes()))

    rows: list[tuple] = []
    counter = [0]

    def recall(t: float, session: str | None, ids: list[str], layer: str = "all") -> None:
        counter[0] += 1
        context = {"recall_id": f"syn-recall-{counter[0]}", "query": "synthetic"}
        if session is not None:
            context["session_id"] = session
        outcome = rng.choice([None, "used", "used: auto: cited", "not_used"], p=[0.7, 0.15, 0.1, 0.05])
        rows.append((f"syn-log-{counter[0]}", iso(t), "recall", layer, json.dumps(ids), json.dumps(context), outcome))

    n_sessions = sessions or DEFAULT_SESSIONS[kind]
    plant = plant_simple if kind in ("order", "noorder") else plant_realistic
    planted, names = plant(kind, rng, n_sessions, dim, memory, recall)
    for j in range(40):
        recall(rng.uniform(LOG_START, LOG_END), f"syn-session-{rng.integers(n_sessions)}", [f"syn-instinct-{j % 7}"],
               layer="instinct")
    for _ in range(20):
        start = int(rng.integers(len(names) - 6))
        recall(rng.uniform(LOG_START, LOG_END), None, names[start:start + 6])
    for _ in range(50):
        counter[0] += 1
        rows.append((f"syn-log-{counter[0]}", iso(rng.uniform(LOG_START, LOG_END)), "remember", "episode", "[]",
                     "{}", None))
    db.executemany("INSERT INTO memory_log (id, timestamp, event_type, layer, target_ids, context, outcome) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    db.commit()
    planted.update(kind=kind, dim=dim, sessions=n_sessions, recall_rows=sum(r[2] == "recall" for r in rows))
    return db, uri, planted


def plant_simple(kind, rng, n_sessions, dim, memory, recall) -> tuple[dict, list[str]]:
    """Memories sit in groups that are tight in meaning (members ~31° from their centre; random vectors are ~90°
    apart). A recall returns 6 random members of one group, in random order.

    order: 120 regular groups and 8 hub groups. Each regular group G has a fixed hub f(G), 15 groups per hub. A
      session takes one regular group per hub, in random order, and recalls G1, f(G1), G2, f(G2), ... (16 recalls).
      So a memory is followed by a specific next set. Every hub is in every session, so sharing a session says
      nothing about which hub follows: only order does.
    noorder: 150 groups. A session takes 2 groups and makes 12 recalls, each from one of its two groups at random.
      Recalls are co-retrieved within a group, and the order within a session is exchangeable.

    Both add 300 never-recalled distractors created during the log, 10 vectors with no created_at row, a 5% chance
    of an immediate repeat of a recall (collapsed), a 2% chance of an empty recall, and 12 additive-period sessions."""
    size, m = 12, 6
    n_groups = 128 if kind == "order" else 150
    centres = unit(rng.standard_normal((n_groups, dim)))
    members = unit(centres[:, None, :] + 0.6 * unit(rng.standard_normal((n_groups, size, dim))))
    names = [[f"syn-{g:03d}-{j:02d}" for j in range(size)] for g in range(n_groups)]
    for g in range(n_groups):
        for j in range(size):
            memory(names[g][j], members[g, j], rng.uniform(midnight(2026, 7, 1), midnight(2026, 8, 15)),
                   semantic=g % 4 == 3)
    for j in range(300):
        memory(f"syn-late-{j:03d}", unit(rng.standard_normal(dim)), rng.uniform(LOG_START, LOG_END))
    for j in range(10):
        memory(f"syn-orphan-{j}", unit(rng.standard_normal(dim)), 0.0, row=False)

    if kind == "order":
        hubs, regular = 8, 120
        hub_of = rng.permutation(regular) % hubs
        by_hub = [np.flatnonzero(hub_of == h) for h in range(hubs)]

        def footpath() -> list[int]:
            picks = [int(rng.choice(by_hub[h])) for h in range(hubs)]
            rng.shuffle(picks)
            return [g for p in picks for g in (p, regular + int(hub_of[p]))]
    else:
        def footpath() -> list[int]:
            pair = rng.choice(n_groups, 2, replace=False)
            return [int(pair[rng.integers(2)]) for _ in range(12)]

    def session_rows(s: int, start: float) -> None:
        t = start
        for g in footpath():
            ids = [names[g][j] for j in rng.choice(size, m, replace=False)]
            recall(t, f"syn-session-{s}", ids)
            if rng.random() < 0.05:  # an immediate repeat of the same set, in another order
                t += 10
                recall(t, f"syn-session-{s}", list(rng.permutation(ids)))
            if rng.random() < 0.02:
                t += 10
                recall(t, f"syn-session-{s}", [])
            t += rng.uniform(30, 300)

    for s in range(n_sessions):
        session_rows(s, rng.uniform(LOG_START, LOG_END))
    for s in range(n_sessions, n_sessions + 12):  # the additive period
        session_rows(s, rng.uniform(midnight(2026, 8, 20), midnight(2026, 9, 1)))
    planted = {"groups": n_groups, "group_size": size, "recall_size": m, "hubs": 8 if kind == "order" else 0,
               "additive_sessions": 12}
    return planted, [n for group in names for n in group]


REALISTIC = {
    "topics": 80, "per_topic": 40, "rank": 4, "spread": 0.9, "jitter": 0.3, "p_stay": 0.35, "p_shift": 0.15,
    "interleaved": 0.30, "decayed": 0.10, "late": 0.10, "recall_size": (15, 20),
}


def plant_realistic(kind, rng, n_sessions, dim, memory, recall) -> tuple[dict, list[str]]:
    """A log shaped like Engram's. 80 topics of 40 memories each. A topic's members vary along a 4-dimensional subspace
    of their own around the topic's centre, so similarity within a topic is graded (dot ~0.1 to 1), as in real
    embeddings, whose intrinsic dimension is low; in 768-d, isotropic offsets would make every member equally near
    every point of its topic. A recall returns the 15 to 20 memories nearest its query, among those created by then,
    in rank order, so meaning makes every set. A footpath keeps an anchor in a topic and queries near it (jitter 0.3
    within the topic's subspace). After each recall it:
    - stays at the anchor with p = 0.25 (a re-query: large overlap, mostly Jaccard above 0.5);
    - shifts to a new anchor in the same topic with p = 0.40 (partial overlap);
    - jumps with p = 0.35: with p = P_FOLLOW to its topic's fixed next set (a fixed anchor in a fixed other topic,
      the planted order effect), else to a random point in a random other topic.
    A session is one footpath of 12 to 24 recalls, or, with p = 0.30, two footpaths of 8 to 14 recalls interleaved
    by time under one session id, as subagents do. 10% of memories are created during the log, and 10% have no
    vector now (decay). The two realistic logs share one structure generator, so they hold the same sessions,
    queries and times. realistic-noorder then permutes each session's queries over its times, which keeps
    co-retrieval and who-shares-a-session and removes order. There is no additive period."""
    p = REALISTIC
    structure = np.random.default_rng((SEED, 30))  # the same for both realistic kinds
    topics, per = p["topics"], p["per_topic"]
    centres = unit(structure.standard_normal((topics, dim)))
    bases = np.stack([np.linalg.qr(structure.standard_normal((dim, p["rank"])))[0] for _ in range(topics)])

    def place(topic: int, z: np.ndarray) -> np.ndarray:
        """The point of a topic at subspace coordinates z: its centre plus spread along the topic's own subspace."""
        return unit(centres[topic] + p["spread"] * unit(bases[topic] @ z))

    X = np.stack([place(k // per, structure.standard_normal(p["rank"])) for k in range(topics * per)])
    X = X.astype(np.float32)
    names = [f"syn-t{k // per:02d}-{k % per:02d}" for k in range(len(X))]
    late = structure.random(len(X)) < p["late"]
    created = np.where(late, structure.uniform(LOG_START, LOG_END, len(X)),
                       structure.uniform(midnight(2026, 7, 1), midnight(2026, 8, 31), len(X)))
    decayed = structure.random(len(X)) < p["decayed"]
    for k in range(len(X)):
        memory(names[k], None if decayed[k] else X[k], float(created[k]), semantic=(k // per) % 4 == 3)
    succ = structure.permutation(topics)
    while (succ == np.arange(topics)).any():
        succ = structure.permutation(topics)
    next_set = [unit(structure.standard_normal(p["rank"])) for _ in range(topics)]  # in topic succ[t]'s subspace

    def point() -> np.ndarray:
        return unit(structure.standard_normal(p["rank"]))

    def footpath(length: int) -> list[tuple[np.ndarray, int]]:
        topic = int(structure.integers(topics))
        anchor, out = point(), []
        for _ in range(length):
            z = anchor + p["jitter"] * structure.standard_normal(p["rank"]) / np.sqrt(p["rank"])
            query = place(topic, z)
            out.append((query, int(structure.integers(p["recall_size"][0], p["recall_size"][1] + 1))))
            u = structure.random()
            if u < p["p_stay"]:
                continue
            if u < p["p_stay"] + p["p_shift"]:
                anchor = point()
            elif structure.random() < P_FOLLOW:
                anchor, topic = next_set[topic], int(succ[topic])
            else:
                topic = int((topic + 1 + structure.integers(topics - 1)) % topics)
                anchor = point()
        return out

    shuffle = np.random.default_rng((SEED, 31))
    interleaved = 0
    for s in range(n_sessions):
        start = structure.uniform(LOG_START, LOG_END)
        if structure.random() < p["interleaved"]:
            interleaved += 1
            paths = [footpath(int(structure.integers(8, 15))), footpath(int(structure.integers(8, 15)))]
            offsets = [0.0, structure.uniform(60, 600)]
        else:
            paths, offsets = [footpath(int(structure.integers(12, 25)))], [0.0]
        items = []
        for path, offset in zip(paths, offsets):
            t = start + offset
            for query in path:
                items.append((t, query))
                t += structure.uniform(30, 300)
        items.sort(key=lambda item: item[0])
        if kind == "realistic-noorder":
            order = shuffle.permutation(len(items))
            items = [(items[j][0], items[order[j]][1]) for j in range(len(items))]
        for t, (query, m) in items:
            scores = X @ query.astype(np.float32)
            scores[created > t] = -np.inf
            top = np.argsort(-scores, kind="stable")[:m]
            recall(t, f"syn-session-{s}", [names[k] for k in top])
    planted = {"topics": topics, "per_topic": per, "interleaved_sessions": interleaved, "p_follow": P_FOLLOW,
               "decayed_memories": int(decayed.sum()), "late_memories": int(late.sum()), "additive_sessions": 0}
    planted.update({k: v for k, v in p.items() if k not in ("topics", "per_topic")})
    return planted, names


# --------------------------------------------------------------------------------------------------- counting


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def collapse(seq, log: Log) -> list[tuple[int, bool, bool]]:
    """Consecutive recalls of one id set become one run: (its first recall, any used, any used explicitly)."""
    runs: list[tuple[int, bool, bool]] = []
    for r in seq:
        used, explicit = bool(log.used[r]), bool(log.used[r] and not log.auto[r])
        if runs and log.sets[r] == log.sets[runs[-1][0]]:
            first, u, e = runs[-1]
            runs[-1] = (first, u or used, e or explicit)
        else:
            runs.append((int(r), used, explicit))
    return runs


class Table:
    """Counts c(x, y) over memory codes, sorted by (x, y), with row pointers by x; optionally the number of distinct
    sessions carrying each (x, y)."""

    def __init__(self, xs: list, ys: list, n_codes: int, sessions: list | None = None):
        x = np.concatenate(xs) if xs else np.empty(0, np.int64)
        y = np.concatenate(ys) if ys else np.empty(0, np.int64)
        key = x * n_codes + y
        keys, counts = np.unique(key, return_counts=True)
        self.support = None
        if sessions is not None:
            s = np.concatenate(sessions) if sessions else np.empty(0, np.int64)
            n_s = int(s.max()) + 1 if len(s) else 1
            _, support = np.unique(np.unique(key * n_s + s) // n_s, return_counts=True)
            self.support = support
        del key, x, y
        self.y = keys % n_codes
        self.ptr = np.searchsorted(keys // n_codes, np.arange(n_codes + 1))
        self.c = counts
        self.pairs = len(keys)

    def scores(self, sources: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        parts = [(self.ptr[x], self.ptr[x + 1]) for x in sources.tolist() if self.ptr[x + 1] > self.ptr[x]]
        if not parts:
            return np.empty(0, np.int64), np.empty(0, np.int64)
        ys = np.concatenate([self.y[lo:hi] for lo, hi in parts])
        cs = np.concatenate([self.c[lo:hi] for lo, hi in parts])
        u, inv = np.unique(ys, return_inverse=True)
        return u, np.bincount(inv, weights=cs).astype(np.int64)

    def edge(self, x: int, y: int) -> tuple[int, int]:
        lo, hi = int(self.ptr[x]), int(self.ptr[x + 1])
        j = lo + int(np.searchsorted(self.y[lo:hi], y))
        if j < hi and self.y[j] == y:
            return int(self.c[j]), int(self.support[j]) if self.support is not None else 0
        return 0, 0


def transitions(seqs: list, log: Log, n_codes: int, support: bool = False, cutoff: float | None = None):
    """(ii)'s table from sequences of runs that were collapsed once, from real order (section 6′: the shuffled arm
    permutes those runs and never re-collapses). For each consecutive pair a → b with Jaccard ≤ 0.5, c(x, y) += 1 for
    x in a and y in b ∖ a."""
    xs, ys, ss = [], [], []
    pairs = after = 0
    for s, runs in enumerate(seqs):
        for a, b in zip(runs, runs[1:]):
            A, B = log.sets[a], log.sets[b]
            if jaccard(A, B) > JACCARD_MAX:
                continue
            pairs += 1
            if cutoff is not None and log.t[b] >= cutoff:
                after += 1
            new = np.array(sorted(B - A), np.int64)
            src = log.ids[a]
            if not len(new) or not len(src):
                continue
            xs.append(np.repeat(src, len(new)))
            ys.append(np.tile(new, len(src)))
            if support:
                ss.append(np.full(len(src) * len(new), s, np.int64))
    return Table(xs, ys, n_codes, ss if support else None), pairs, after


def co_retrieval(reps: list[int], log: Log, n_codes: int) -> Table:
    xs, ys = [], []
    for r in reps:
        ids = log.ids[r]
        if len(ids) < 2:
            continue
        x, y = np.repeat(ids, len(ids)), np.tile(ids, len(ids))
        keep = x != y
        xs.append(x[keep])
        ys.append(y[keep])
    return Table(xs, ys, n_codes)


# --------------------------------------------------------------------------------------------------- ranking


@dataclass
class StepCache:
    a: np.ndarray  # a's logged codes
    n_u: int  # the universe at b's time is codes [0, n_u)
    c: np.ndarray  # float32 centroid of a's vectors
    i_top: np.ndarray  # (i)'s first 2·TOP, for backfill
    target: frozenset


def top_by(scores: np.ndarray, k: int) -> np.ndarray:
    """Indices of the k largest finite scores, by score then index; exact ties at the cut are resolved by index."""
    k = min(k, int(np.isfinite(scores).sum()))
    if k <= 0:
        return np.empty(0, np.int64)
    if len(scores) > k:
        kth = np.partition(scores, len(scores) - k)[len(scores) - k]
        idx = np.flatnonzero(scores >= kth)
    else:
        idx = np.flatnonzero(np.isfinite(scores))
    return idx[np.lexsort((idx, -scores[idx]))][:k]


def fill(top: np.ndarray, i_top: np.ndarray) -> np.ndarray:
    if len(top) >= TOP:
        return top[:TOP]
    have = set(top.tolist())
    extra = [z for z in i_top.tolist() if z not in have][: TOP - len(top)]
    return np.concatenate([top, np.array(extra, np.int64)])


def count_arm(V: np.ndarray, ys: np.ndarray, sc: np.ndarray, cache: StepCache, slots: int = TOP):
    """A count arm's first 10: candidates with a positive count, by count, then (i)'s order, then code; then (i)."""
    ok = (ys < cache.n_u) & ~np.isin(ys, cache.a) & (sc > 0)
    ys, sc = ys[ok], sc[ok]
    positive = len(ys)
    if slots <= 0 or not positive:
        return fill(np.empty(0, np.int64), cache.i_top), positive
    if positive > slots:
        kth = np.partition(sc, positive - slots)[positive - slots]
        keep = sc >= kth
        ys, sc = ys[keep], sc[keep]
    d = V[ys] @ cache.c
    top = ys[np.lexsort((ys, -d, -sc))][:slots]
    return fill(top, cache.i_top), positive


def first_hit(top: np.ndarray, target: frozenset) -> int:
    for position, z in enumerate(top.tolist(), 1):
        if z in target:
            return position
    return TOP + 1


# --------------------------------------------------------------------------------------------------- evaluation


def evaluate(log: Log, uni: Universe, recalls: np.ndarray, tag: int) -> dict:
    out: dict = {"recalls": len(recalls)}
    if not len(recalls):
        out["empty"] = True
        return out
    cutoff = float(np.percentile(log.t[recalls], SPLIT_PERCENTILE))
    sessions: dict[int, list[int]] = {}
    for r in recalls.tolist():
        sessions.setdefault(int(log.session[r]), []).append(r)
    train_seqs = [[r for r in seq if log.t[r] < cutoff] for seq in sessions.values()]
    train_seqs = [seq for seq in train_seqs if seq]
    test = [(code, seq) for code, seq in sessions.items() if log.t[seq[0]] > cutoff]
    out.update(cutoff=cutoff, sessions=len(sessions), train_sessions=len(train_seqs),
               train_recalls=sum(len(s) for s in train_seqs), test_sessions_all=len(test),
               spanning=sum(1 for seq in sessions.values() if log.t[seq[0]] < cutoff <= log.t[seq[-1]]),
               test_recalls=sum(len(seq) for _, seq in test),
               test_recalls_in_training=sum(1 for _, seq in test for r in seq if log.t[r] < cutoff))

    train_runs = [[run[0] for run in collapse(seq, log)] for seq in train_seqs]  # collapsed once, from real order
    use, pairs, after = transitions(train_runs, log, uni.n_codes, support=True, cutoff=cutoff)
    reps = [r for runs in train_runs for r in runs]
    popularity = np.bincount(np.concatenate([log.ids[r] for r in reps] or [np.empty(0, np.int64)]),
                             minlength=uni.n_codes)
    co = co_retrieval(reps, log, uni.n_codes)
    pop_codes = np.flatnonzero(popularity)
    out.update(train_pairs=pairs, train_after=after, train_runs=len(reps), use_edges=use.pairs, co_edges=co.pairs)
    train_raw = np.array([r for seq in train_seqs for r in seq], np.int64)
    test_raw = np.array([r for _, seq in test for r in seq], np.int64)
    out["uptake_mix"] = {
        name: {"recalls": len(idx), "used": int(log.used[idx].sum()) if len(idx) else 0,
               "auto": int((log.used[idx] & log.auto[idx]).sum()) if len(idx) else 0}
        for name, idx in (("training", train_raw), ("test", test_raw))}
    guard("training")

    V = uni.V
    first = {arm: [] for arm in ARMS}
    meta = {key: [] for key in ("sid", "day", "jaccard", "size", "positive", "support", "used", "explicit")}
    caches: list[StepCache] = []
    drops = {"candidates": 0, "collapsed": 0, ("low", "novec"): 0, ("low", "empty"): 0, ("high", "novec"): 0,
             ("high", "empty"): 0, ("low", "kept"): 0, ("high", "kept"): 0}
    for sid, seq in test:
        runs = collapse(seq, log)
        drops["collapsed"] += len(seq) - len(runs)
        day = int(log.t[seq[0]] // DAY)
        for j in range(1, len(runs)):
            a, b = runs[j - 1][0], runs[j][0]
            A, B = log.sets[a], log.sets[b]
            drops["candidates"] += 1
            J = jaccard(A, B)
            band = "low" if J <= JACCARD_MAX else "high"
            n_u = int(np.searchsorted(uni.created, log.t[b], side="right"))
            a_codes = log.ids[a]
            a_in = a_codes[a_codes < n_u]
            target = frozenset(y for y in B - A if y < n_u)
            if not len(a_in):
                drops[(band, "novec")] += 1
                continue
            if not target:
                drops[(band, "empty")] += 1
                continue
            drops[(band, "kept")] += 1

            c = V[a_in].astype(np.float64).mean(axis=0)
            norm = float(np.linalg.norm(c))
            c = (c / norm if norm > 1e-12 else V[a_in[0]].astype(np.float64)).astype(np.float32)
            Vu = V[:n_u]
            dots = Vu @ c
            dots[a_in] = -np.inf
            i_top = top_by(dots, 2 * TOP)
            near = (Vu @ V[a_in].T).max(axis=1)
            near[a_in] = -np.inf
            cache = StepCache(a=a_codes, n_u=n_u, c=c, i_top=i_top, target=target)
            caches.append(cache)

            tops = {"i": i_top[:TOP], "i'": top_by(near, TOP)}
            ys, sc = use.scores(a_codes)
            tops["ii"], positive = count_arm(V, ys, sc, cache)
            pool = pop_codes[(pop_codes < n_u) & ~np.isin(pop_codes, a_codes)]
            tops["iii"], _ = count_arm(V, pool, popularity[pool], cache)
            tops["iii-m"], _ = count_arm(V, pool, popularity[pool], cache, slots=min(TOP, positive))
            ys, sc = co.scores(a_codes)
            tops["iv"], _ = count_arm(V, ys, sc, cache)
            seen, history = set(a_codes.tolist()), []
            for run in reversed(runs[: j - 1]):
                for z in log.ids[run[0]].tolist():
                    if z < n_u and z not in seen:
                        seen.add(z)
                        history.append(z)
                if len(history) >= TOP:
                    break
            tops["v"] = fill(np.array(history[:TOP], np.int64), i_top)
            for arm in ARMS:
                first[arm].append(first_hit(tops[arm], target))

            support = 0
            if positive:
                best = int(tops["ii"][0])
                strongest = max(a_codes.tolist(), key=lambda x: use.edge(x, best)[0])
                support = use.edge(strongest, best)[1]
            meta["sid"].append(sid)
            meta["day"].append(day)
            meta["jaccard"].append(J)
            meta["size"].append(len(target))
            meta["positive"].append(positive)
            meta["support"].append(support)
            meta["used"].append(runs[j][1])
            meta["explicit"].append(runs[j][2])
    guard("test steps")
    out["drops"] = drops
    out["first"] = {arm: np.array(v, np.int64) for arm, v in first.items()}
    out["meta"] = {key: np.array(v) for key, v in meta.items()}
    n = len(caches)

    # Two independent sets of SHUFFLES shuffles from different seed streams: set A gives D_order, and set B against
    # set A gives the null of the null (descriptive).
    for name, stream in (("shuffled", (SEED, tag)), ("shuffled_b", (SEED, tag, 1))):
        hits = np.zeros(n)
        for j in range(SHUFFLES):
            rng = np.random.default_rng(stream + (j,))
            table, _, _ = transitions([[runs[i] for i in rng.permutation(len(runs))] for runs in train_runs], log,
                                      uni.n_codes)
            for step, cache in enumerate(caches):
                ys, sc = table.scores(cache.a)
                top, _ = count_arm(V, ys, sc, cache)
                hits[step] += first_hit(top, cache.target) <= TOP
            del table
            guard("shuffles")
        out[name] = hits / SHUFFLES
    del caches

    primary = out["meta"]["jaccard"] <= JACCARD_MAX if n else np.zeros(0, bool)
    out["primary"] = primary
    sids = out["meta"]["sid"][primary] if n else np.zeros(0, np.int64)
    _, per_session = np.unique(sids, return_counts=True)
    n_steps, n_sessions = int(primary.sum()), len(per_session)
    share = float(per_session.max() / n_steps) if n_steps else 0.0
    reasons = []
    if n_steps < MIN_STEPS:
        reasons.append(f"{n_steps} test steps (needs {MIN_STEPS})")
    if n_sessions < MIN_SESSIONS:
        reasons.append(f"{n_sessions} test sessions (needs {MIN_SESSIONS})")
    if share > MAX_SESSION_SHARE:
        reasons.append(f"one session holds {share:.0%} of the steps (at most {MAX_SESSION_SHARE:.0%})")
    out.update(steps=n_steps, step_sessions=n_sessions, max_share=share, insufficient=reasons,
               days=len(np.unique(out["meta"]["day"][primary])) if n_steps else 0)
    if not reasons:
        out["stats"] = statistics(out, primary)
    return out


# --------------------------------------------------------------------------------------------------- bootstrap

NORMAL = NormalDist()


def bca(H: np.ndarray, clusters: np.ndarray, stat, seed, keep: bool = False) -> dict:
    """BCa interval for stat(column means of H), resampling clusters with replacement (multinomial weights)."""
    _, inv = np.unique(clusters, return_inverse=True)
    C = int(inv.max()) + 1
    S = np.zeros((C, H.shape[1]))
    np.add.at(S, inv, H)
    n = np.bincount(inv, minlength=C).astype(np.float64)
    theta = float(stat(S.sum(axis=0) / n.sum()))
    out = {"point": theta, "lo": float("nan"), "hi": float("nan"), "clusters": C}
    if C < 2:
        return out
    rng = np.random.default_rng(seed)
    boot = np.empty(RESAMPLES)
    p = np.full(C, 1.0 / C)
    for start in range(0, RESAMPLES, CHUNK):
        W = rng.multinomial(C, p, size=min(CHUNK, RESAMPLES - start)).astype(np.float64)
        boot[start:start + len(W)] = stat((W @ S) / (W @ n)[:, None])
    below = float(np.mean(boot < theta - 1e-12) + 0.5 * np.mean(np.abs(boot - theta) <= 1e-12))
    z0 = NORMAL.inv_cdf(min(max(below, 0.5 / RESAMPLES), 1 - 0.5 / RESAMPLES))
    jack = stat((S.sum(axis=0) - S) / (n.sum() - n)[:, None])
    d = jack.mean() - jack
    denominator = 6.0 * float((d ** 2).sum()) ** 1.5
    accel = float((d ** 3).sum()) / denominator if denominator > 0 else 0.0
    levels = []
    for alpha in (0.025, 0.975):
        w = z0 + NORMAL.inv_cdf(alpha)
        shrink = 1.0 - accel * w
        levels.append(NORMAL.cdf(z0 + w / shrink) if shrink > 0 else (0.0 if alpha < 0.5 else 1.0))
    lo, hi = np.quantile(boot, levels)
    out.update(lo=float(lo), hi=float(hi), z0=z0, accel=accel)
    if keep:
        out["boot"] = boot
    return out


def d_stat(m: np.ndarray) -> np.ndarray:
    return m[..., COL["ii"]] - m[..., [COL[o] for o in OTHERS]].max(axis=-1)


def statistics(res: dict, mask: np.ndarray) -> dict:
    first, meta = res["first"], res["meta"]
    sid, day = meta["sid"][mask], meta["day"][mask]
    stats: dict = {}
    for k in HITS:
        H = np.stack([(first[arm][mask] <= k).astype(np.float64) for arm in ARMS], axis=1)
        stats[("D", k)] = {"session": bca(H, sid, d_stat, (SEED, k, 1)), "day": bca(H, day, d_stat, (SEED, k, 2))}
    H10 = np.stack([(first[arm][mask] <= 10).astype(np.float64) for arm in ARMS], axis=1)
    for other in OTHERS:
        j = COL[other]
        stats[("pair", other)] = bca(H10, sid, lambda m, j=j: m[..., COL["ii"]] - m[..., j], (SEED, 3, j))
    order = np.stack([H10[:, COL["ii"]], res["shuffled"][mask]], axis=1)
    stats["order"] = {"session": bca(order, sid, lambda m: m[..., 0] - m[..., 1], (SEED, 4, 1)),
                      "day": bca(order, day, lambda m: m[..., 0] - m[..., 1], (SEED, 4, 2))}
    null = np.stack([res["shuffled_b"][mask], res["shuffled"][mask]], axis=1)
    stats["null"] = {"session": bca(null, sid, lambda m: m[..., 0] - m[..., 1], (SEED, 4, 1), keep=True),
                     "day": bca(null, day, lambda m: m[..., 0] - m[..., 1], (SEED, 4, 2))}
    boot = stats["null"]["session"].pop("boot", None)
    q95 = float(np.quantile(boot, 0.95)) if boot is not None else float("nan")
    stats["delta_order"] = {"value": calibrate_delta_order(q95), "q95": q95}
    counted = meta["positive"][mask] > 0
    if counted.any():
        stats["counted"] = bca(H10[counted], sid[counted], d_stat, (SEED, 5, 1))
    return stats


def outcome(interval: dict) -> str:
    """Section 6′'s four outcomes (as amended 2026-11-03): holds, negligible, fails, inconclusive."""
    lo, hi = interval["lo"], interval["hi"]
    if not (lo == lo and hi == hi):
        return "inconclusive"
    if lo > 0:
        return "holds" if hi >= DELTA else "negligible"
    if hi < DELTA:
        return "fails"
    return "inconclusive"


def combine(by_session: str, by_day: str) -> str:
    """The day bootstrap must give the same outcome as the session one, or the result is inconclusive."""
    return by_session if by_session == by_day else "inconclusive"


def calibrate_delta_order(q95: float) -> float:
    """δ_order = max(0.02, the 95th percentile of the null of the null's session bootstrap distribution). With no
    such distribution (one cluster), it's NaN, and order can't be claimed."""
    return max(DELTA_ORDER, q95) if q95 == q95 else float("nan")


def order_verdict(session: dict, day: dict, delta: float) -> str:
    """Order carries information only if D_order's lower bound is above δ_order by session, and by day too."""
    lo_s, lo_d = session["lo"], day["lo"]
    return "carries information" if lo_s > delta and lo_d > delta else "ties"


def check_classifier() -> int:
    """The classifier at each boundary of section 6′'s outcomes. Runs before any store is read."""
    tiny = 1e-9
    cases = [
        ((0.01, 0.20), "holds"),
        ((tiny, DELTA), "holds"),  # upper bound exactly δ: at least δ
        ((tiny, DELTA - tiny), "negligible"),
        ((0.01, 0.04), "negligible"),
        ((0.0, DELTA - tiny), "fails"),  # lower bound exactly 0 isn't above 0
        ((-0.10, DELTA - tiny), "fails"),
        ((-0.30, -0.10), "fails"),
        ((0.0, DELTA), "inconclusive"),
        ((-0.10, DELTA), "inconclusive"),
        ((0.0, 0.20), "inconclusive"),
        ((-0.10, 0.20), "inconclusive"),
        ((float("nan"), 0.20), "inconclusive"),
        ((0.01, float("nan")), "inconclusive"),
    ]
    for (lo, hi), expected in cases:
        got = outcome({"lo": lo, "hi": hi})
        if got != expected:
            raise Stop(f"classifier check: [{lo}, {hi}] gave {got}, expected {expected}")
    pairs = [(("holds", "holds"), "holds"), (("negligible", "negligible"), "negligible"),
             (("fails", "fails"), "fails"), (("holds", "negligible"), "inconclusive"),
             (("negligible", "fails"), "inconclusive"), (("holds", "inconclusive"), "inconclusive")]
    for (s, d), expected in pairs:
        if combine(s, d) != expected:
            raise Stop(f"classifier check: session {s} with day {d} gave {combine(s, d)}, expected {expected}")
    calibrations = [(0.0, DELTA_ORDER), (0.01, DELTA_ORDER), (DELTA_ORDER, DELTA_ORDER), (0.035, 0.035)]
    for q95, expected in calibrations:
        if calibrate_delta_order(q95) != expected:
            raise Stop(f"classifier check: δ_order from q95 {q95} gave {calibrate_delta_order(q95)}, expected {expected}")
    if calibrate_delta_order(float("nan")) == calibrate_delta_order(float("nan")):
        raise Stop("classifier check: δ_order from no null distribution should be NaN")
    orders = []
    for delta in (DELTA_ORDER, 0.035):  # the floor, and a calibrated value above it
        orders += [
            ((delta + tiny, delta + tiny, delta), "carries information"),
            ((0.10, 0.10, delta), "carries information"),
            ((delta, delta + tiny, delta), "ties"),  # exactly δ_order isn't above it
            ((delta + tiny, delta, delta), "ties"),  # the day bootstrap must agree
            ((delta - tiny, 0.10, delta), "ties"),
            ((0.01, 0.01, delta), "ties"),  # above 0 but inside the margin
            ((0.0, 0.0, delta), "ties"),
            ((float("nan"), 0.10, delta), "ties"),
        ]
    orders.append(((0.10, 0.10, float("nan")), "ties"))  # no calibrated δ_order: no claim
    for (lo_s, lo_d, delta), expected in orders:
        got = order_verdict({"lo": lo_s}, {"lo": lo_d}, delta)
        if got != expected:
            raise Stop(f"classifier check: D_order lower bounds {lo_s} (session), {lo_d} (day) at δ_order {delta} "
                       f"gave {got}, expected {expected}")
    return len(cases) + len(pairs) + len(calibrations) + 1 + len(orders)


def verdict(res: dict) -> dict:
    if res.get("empty"):
        return {"c1": "insufficient", "order": "not computed", "note": "no recalls in this period"}
    if res["insufficient"]:
        return {"c1": "insufficient", "order": "not computed", "note": "; ".join(res["insufficient"])}
    st = res["stats"]
    by_session, by_day = outcome(st[("D", 10)]["session"]), outcome(st[("D", 10)]["day"])
    c1 = combine(by_session, by_day)
    notes = []
    if by_session != by_day:
        notes.append(f"the session bootstrap says {by_session} and the day bootstrap says {by_day}")
    o = st["order"]
    order = order_verdict(o["session"], o["day"], st["delta_order"]["value"])
    return {"c1": c1, "order": order, "note": "; ".join(notes)}


def branch(v: dict) -> str:
    if v["c1"] == "holds":
        return ("E1′ holds, and order carries information: build trails from recall logs, smallest first"
                if v["order"] == "carries information" else
                "E1′ holds, but order ties: build co-use only (undirected), observed and never steering")
    if v["c1"] == "negligible":
        return "E1′ is negligible: the effect is real but below δ, so it builds nothing, as fails does"
    if v["c1"] == "fails":
        return "E1′ fails: the trails part of the rail stops for Engram too"
    return "E1′ is inconclusive or insufficient: build nothing for trails; rerun once the test steps have doubled"


# --------------------------------------------------------------------------------------------------- report


def fmt(x: float) -> str:
    return "n/a" if x != x else f"{x:.3f}"


def signed(x: float) -> str:
    return "n/a" if x != x else f"{x:+.3f}"


def interval(b: dict) -> str:
    return f"{signed(b['point'])} [{signed(b['lo'])}, {signed(b['hi'])}]"


def many(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def day_of(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


def hit_table(res: dict, rows: list[tuple[str, np.ndarray]], k: int, shuffled: bool = False) -> list[str]:
    arms = list(ARMS) + (["ii-s"] if shuffled else [])
    lines = ["| population | n | " + " | ".join(ARM_NAMES[a] for a in arms) + " | D |",
             "|---|---|" + "---|" * (len(arms) + 1)]
    for label, mask in rows:
        n = int(mask.sum())
        if not n:
            lines.append(f"| {label} | 0 |" + " |" * (len(arms) + 1))
            continue
        h = {a: float((res["first"][a][mask] <= k).mean()) for a in ARMS}
        if shuffled:
            h["ii-s"] = float(res["shuffled"][mask].mean())
        lines.append(f"| {label} | {n} | " + " | ".join(fmt(h[a]) for a in arms)
                     + f" | {signed(h['ii'] - max(h[o] for o in OTHERS))} |")
    return lines


def period_section(name: str, res: dict, v: dict, primary_period: bool) -> list[str]:
    L = []
    if res.get("empty"):
        return [f"No analysed recalls in the {name}.", ""]
    d = res["drops"]
    L += [
        f"- **Recalls analysed:** {res['recalls']} in {many(res['sessions'], 'session')}.",
        f"- **Split:** `T` falls on {day_of(res['cutoff'])} (80th percentile of recall times, rounded to the day).",
        f"- **Training:** {many(res['train_sessions'], 'session')} with recalls before `T`, {res['train_recalls']} recalls, "
        f"{res['train_runs']} after collapse, and {res['train_pairs']} pairs passing the Jaccard rule. (ii) has "
        f"{res['use_edges']} distinct edges and (iv) has {res['co_edges']}.",
        f"- **Training steps after the cutoff:** {res['train_after']} (must be 0). Test-session recalls before `T`: "
        f"{res['test_recalls_in_training']} (must be 0).",
        f"- **Sessions spanning `T`:** {res['spanning']}. They give training pairs before `T` and no test steps.",
        f"- **Test:** sessions starting after `T`: {res['test_sessions_all']}, with {res['test_recalls']} recalls; "
        f"collapse merged {d['collapsed']} of them. That leaves {d['candidates']} candidate steps.",
        "",
        "| Jaccard | candidate steps | a has no vectors | target empty | kept |",
        "|---|---|---|---|---|",
    ]
    for band, label in (("low", "≤ 0.5 (primary)"), ("high", "> 0.5 (excluded; descriptive)")):
        total = d[(band, "novec")] + d[(band, "empty")] + d[(band, "kept")]
        share = (lambda x: f"{x} ({x / total:.1%})") if total else (lambda x: str(x))
        L.append(f"| {label} | {total} | {share(d[(band, 'novec')])} | {share(d[(band, 'empty')])} | "
                 f"{share(d[(band, 'kept')])} |")
    L += ["", f"- **Primary steps:** {res['steps']} in {many(res['step_sessions'], 'session')} over {many(res['days'], 'day')}. The "
              f"largest session holds {res['max_share']:.1%} of them.", ""]
    mix = res["uptake_mix"]
    L += [f"- **Uptake marks** (descriptive): training recalls {mix['training']['recalls']}, of which "
          f"{mix['training']['used']} were marked used ({mix['training']['auto']} by `auto`). Test recalls "
          f"{mix['test']['recalls']}, of which {mix['test']['used']} were marked used ({mix['test']['auto']} by "
          "`auto`).", ""]

    heading = "Outcome" if primary_period else "Outcome (secondary, decides nothing)"
    L += [f"### {heading}", ""]
    if res["insufficient"]:
        L += [f"**Insufficient:** {'; '.join(res['insufficient'])}. The run claims nothing and computes no interval.",
              ""]
    else:
        st = res["stats"]
        L += [f"- **C1′ {v['c1']}.** D@10 = {interval(st[('D', 10)]['session'])} by session "
              f"({st[('D', 10)]['session']['clusters']} clusters), {interval(st[('D', 10)]['day'])} by day "
              f"({st[('D', 10)]['day']['clusters']} clusters). δ = {DELTA}.",
              f"- **Order {v['order']}.** D_order = {interval(st['order']['session'])} by session, "
              f"{interval(st['order']['day'])} by day.",
              f"- **δ_order = {fmt(st['delta_order']['value'])}**, the larger of the floor {DELTA_ORDER} and the 95th "
              f"percentile of D_null's session bootstrap distribution ({signed(st['delta_order']['q95'])}).",
              f"- **Null of the null:** D_null = hit@10(shuffle set B) − hit@10(shuffle set A) = "
              f"{interval(st['null']['session'])} by session, {interval(st['null']['day'])} by day.",
              ]
        if v["note"]:
            L.append(f"- **Note:** {v['note']}.")
        if primary_period:
            L.append(f"- **Section 7:** {branch(v)}.")
        L.append("")
    mask = res["primary"]
    if not mask.any():
        return L + ["No primary steps, so no hit rates.", ""]

    L += ["### Hit rates on the primary steps", ""]
    for k in HITS:
        L += [f"hit@{k}" + (" (the shuffled arm is reported at 10 only):" if k == 10 else ":"), ""]
        L += hit_table(res, [("primary", mask)], k, shuffled=(k == 10)) + [""]
    if not res["insufficient"]:
        st = res["stats"]
        L += ["### D at every k, and (ii) against each arm", "",
              "| k | D by session [BCa 95%] | D by day [BCa 95%] |", "|---|---|---|"]
        L += [f"| {k} | {interval(st[('D', k)]['session'])} | {interval(st[('D', k)]['day'])} |" for k in HITS]
        L += ["", "| (ii) − arm at @10 | by session [BCa 95%] |", "|---|---|"]
        L += [f"| {ARM_NAMES[o]} | {interval(st[('pair', o)])} |" for o in OTHERS]
        L.append("")
    meta = res["meta"]
    counted = mask & (meta["positive"] > 0)
    L += ["### Steps where (ii) had counts", "",
          f"(ii) had no counted candidate on {int((mask & (meta['positive'] == 0)).sum())} of {int(mask.sum())} "
          f"primary steps ({float((meta['positive'][mask] == 0).mean()):.1%}); there it equals (i)."]
    if not res["insufficient"] and "counted" in res["stats"]:
        L.append(f"On the {int(counted.sum())} steps with counts, D@10 = {interval(res['stats']['counted'])} by "
                 "session.")
    L.append("")
    L += hit_table(res, [("with counts", counted), ("without counts", mask & (meta["positive"] == 0))], 10) + [""]

    L += ["### By |b ∖ a| and by Jaccard band (hit@10, descriptive)", ""]
    size = meta["size"]
    size_rows = [(f"|b ∖ a| = {lab}", mask & cond) for lab, cond in
                 (("1", size == 1), ("2–3", (size >= 2) & (size <= 3)), ("4–7", (size >= 4) & (size <= 7)),
                  ("8+", size >= 8))]
    J = meta["jaccard"]
    kept = np.ones(len(J), bool)
    band_rows = [(f"Jaccard {lab}", kept & cond) for lab, cond in
                 (("0", J == 0), ("(0, 0.25]", (J > 0) & (J <= 0.25)), ("(0.25, 0.5]", (J > 0.25) & (J <= 0.5)),
                  ("> 0.5 (not primary)", J > 0.5))]
    L += hit_table(res, size_rows + band_rows, 10) + [""]

    L += ["### C2 analogue: (ii)'s hit rate by the support of its top edge", "",
          "Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s "
          "top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.", "",
          "| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |",
          "|---|---|---|---|---|---|---|---|---|"]
    sup = meta["support"]
    for lab, cond in (("0", sup == 0), ("1", sup == 1), ("2", sup == 2), ("3–4", (sup >= 3) & (sup <= 4)),
                      ("5–9", (sup >= 5) & (sup <= 9)), ("10+", sup >= 10)):
        m2 = mask & cond
        if m2.any():
            L.append(f"| {lab} | {int(m2.sum())} | {int(np.median(meta['positive'][m2]))} | " + " | ".join(
                fmt(float((res['first'][a][m2] <= k).mean())) for k in (1, 10) for a in ("ii", "i", "iii")) + " |")
    L.append("")

    used = mask & meta["used"].astype(bool)
    L += ["### Uptake subset (descriptive only)", "",
          f"Primary steps whose `b` was marked used: {int(used.sum())}, of which "
          f"{int((used & meta['explicit'].astype(bool)).sum())} explicit and "
          f"{int((used & ~meta['explicit'].astype(bool)).sum())} by `auto` only.", ""]
    L += hit_table(res, [("b marked used", used)], 10) + [""]
    return L


def report(path: Path, label: str, source: dict, log: Log, uni: Universe, counts: dict, results: dict,
           verdicts: dict, timing: dict) -> None:
    L = [f"# E1′ run: {label}", ""]
    L += [f"Run on {timing['day']} (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ "
          f"(revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `{timing['sha']}`. Numbers only: no "
          "memory text, query, id or outcome text appears here, and no time finer than a day.", ""]
    v = verdicts["primary"]
    L += ["## Result", ""]
    if v["c1"] == "insufficient":
        L += [f"**Insufficient: {v['note']}.** The run claims nothing.", ""]
    else:
        st = results["primary"]["stats"]
        L += [f"**C1′ {v['c1']}; order {v['order']}.** D@10 = {interval(st[('D', 10)]['session'])} (session BCa), "
              f"D_order = {interval(st['order']['session'])}. Section 7: {branch(v)}.", ""]

    if source.get("planted"):
        p = source["planted"]
        L += ["## Planted structure", ""]
        if p["kind"] == "order":
            L += [f"{p['groups']} groups of {p['group_size']} memories ({p['dim']}-d, each group tight in meaning). "
                  f"There are 120 regular groups and {p['hubs']} hub groups, and each regular group has a fixed hub. "
                  "A session takes one regular group per hub, in random order, and recalls each group and then its "
                  f"hub, 16 recalls of {p['recall_size']} random members each. A memory is followed by a specific "
                  "next set, and every hub sits in every session, so only order says which hub follows."]
        elif p["kind"] == "noorder":
            L += [f"{p['groups']} groups of {p['group_size']} memories ({p['dim']}-d, each group tight in meaning). "
                  "A session takes 2 groups and makes 12 recalls, each drawing "
                  f"{p['recall_size']} random members from one of the two at random. Memories are co-retrieved "
                  "within a group, and order within a session is exchangeable."]
        else:
            lo_m, hi_m = p["recall_size"]
            L += [f"A log shaped like Engram's: {p['topics']} topics of {p['per_topic']} memories ({p['dim']}-d). "
                  f"Each topic's members vary along a {p['rank']}-dimensional subspace of their own, so similarity "
                  "within a topic is graded, as in real embeddings. A recall returns the {lo_m} to {hi_m} memories nearest its query among those created by then, "
                  "in rank order, so meaning makes every set. A footpath queries near an anchor point and then:",
                  "",
                  f"- stays at the anchor (p = {p['p_stay']}), a re-query with large overlap, mostly Jaccard above 0.5;",
                  f"- shifts to a new anchor in the same topic (p = {p['p_shift']}), with partial overlap;",
                  f"- jumps (p = {1 - p['p_stay'] - p['p_shift']:.2f}). With p = {p['p_follow']} it goes to its "
                  "topic's fixed next set, a fixed anchor in a fixed other topic: the planted order effect. "
                  "Otherwise it goes to a random point in a random other topic.",
                  "",
                  f"A session is one footpath of 12 to 24 recalls, or two footpaths of 8 to 14 recalls interleaved by "
                  f"time under one session id, as subagents do ({p['interleaved_sessions']} of {p['sessions']} "
                  f"sessions). {p['late_memories']} memories are created during the log, and {p['decayed_memories']} "
                  "have no vector now (decay, about 10%)."]
            if p["kind"] == "realistic-noorder":
                L += ["", "This log holds the same sessions, queries and times as realistic-order. Each session's "
                      "queries are then permuted over its times. That keeps co-retrieval and who shares a session, "
                      "and removes order."]
        wants_order = not p["kind"].endswith("noorder")
        required_text = ("C1′ holds, and D_order's lower bound is above δ_order" if wants_order
                         else "C1′ does not hold, and D_order ties")
        L += ["", f"**Required:** {required_text}.", ""]
        if p["kind"] in ("order", "noorder"):
            L += [f"Both simple logs also carry {p['sessions']} primary-period sessions, {p['additive_sessions']} "
                  "additive-period sessions, 300 never-recalled distractor memories created during the log, 10 "
                  "vectors with no `created_at` row, immediate repeats (5%), and empty recalls (2%)."]
        L += ["Every synthetic log also carries 40 instinct recalls, 20 recalls with no session id, and non-recall log "
              "rows. These exercise each filter.", ""]
        required = (v["c1"] == "holds" and v["order"] == "carries information") if wants_order else \
            (v["c1"] != "holds" and v["order"] == "ties")
        L += [f"**Smoke check: {'passed' if required else 'not met'}** (C1′ {v['c1']}, order {v['order']}).", ""]

    L += ["## Pre-registered rules (section 6′, implemented as written)", "",
          "- **Steps:** recalls in time order per session, with consecutive repeats of an id set collapsed. A step "
          "`a → b` counts when Jaccard(a, b) ≤ 0.5. The target is `b ∖ a` within the universe (a vector now, "
          "`created_at` ≤ `b`'s time). A step is dropped when `a` has no vectors or its target is empty.",
          "- **Period and split:** the primary period starts at the `tiebreak` default's commit. `T` is the 80th "
          "percentile of recall times in the period. Training is pairs wholly before `T` inside the period, and test "
          "is sessions whose first recall is after `T`. Instinct recalls are excluded.",
          "- **Arms:** (i), (i′), (ii), (iii) pure, (iii) matched, (iv) and (v), each a ranking of 10 memories "
          "excluding `a`'s ids, each backfilled by (i).",
          f"- **Outcome:** D = hit@10(ii) − max(i, i′, iii, iii-m, iv, v), with the max inside each resample, and a "
          f"bootstrap clustered by session ({RESAMPLES:,} resamples, BCa, jackknife acceleration), δ = {DELTA}. "
          "**Holds:** the lower bound is above 0 and the upper bound is at least δ. **Negligible:** the lower bound "
          "is above 0 and the upper bound is below δ (real, but it builds nothing). **Fails:** the upper bound is "
          "below δ and the lower bound isn't above 0. **Inconclusive:** anything else, or when the day-clustered "
          "bootstrap's outcome differs. The classifier is checked at each boundary before every run.",
          f"- **Insufficient:** fewer than {MIN_STEPS} test steps, fewer than {MIN_SESSIONS} test sessions, or one "
          f"session above {MAX_SESSION_SHARE:.0%} of the steps.",
          f"- **Order:** (ii) retrained on each training session in shuffled order ({SHUFFLES} seeded shuffles, "
          "averaged). The training sequence is collapsed once, from real order. The shuffles permute those runs, "
          "and pairs then follow the Jaccard rule and the mirroring, with no re-collapse. Evaluation steps are the same "
          "in every arm. D_order = hit@10(ii) − hit@10(ii-s). A second, independent set of 20 shuffles against the "
          "first gives the null of the null, D_null. Order carries information only if D_order's lower bound is "
          f"above δ_order = max({DELTA_ORDER}, the 95th percentile of D_null's bootstrap distribution), and the day "
          "bootstrap agrees.", ""]

    L += ["## Choices this script made where the plan leaves one", ""]
    L += [f"{j}. {c}" for j, c in enumerate(CHOICES, 1)] + [""]

    L += ["## The store as read", ""]
    if source.get("planted"):
        L.append("- **Source:** a synthetic log in a shared-cache in-memory SQLite database (no file), read through "
                 "the same reader (an in-memory URI in place of `mode=ro`, with `query_only`), in one read transaction.")
    else:
        cfg = source["config"]
        L += ["- **Source:** the live store file, opened with a `mode=ro` URI and `query_only`, and read in one read "
              "transaction. No copy was made.",
              f"- **Config check:** {cfg['looked']} places looked at ({cfg['named']} named with `--config`). "
              f"{cfg['found']} `config.toml` found, with recency_mode: "
              + (", ".join(cfg["modes"]) if cfg["modes"] else "none found") + ". Nothing overrides `tiebreak`."]
    L.append(f"- **Classifier:** {source['classifier_checks']} boundary checks of the four outcomes passed before "
             "the store was read.")
    L += [f"- **Universe:** {len(uni.created)} memories with a vector ("
          + ", ".join(f"{k} {n}" for k, n in uni.tables.items()) + f"), dimension {uni.V.shape[1] if uni.V.size else 0}. "
          f"Left out: {uni.no_created} with no `created_at` row, {uni.zero} with zero norm, {uni.bad_size} of the "
          f"wrong size, {uni.both_tables} already seen in the other table.",
          f"- **Logged ids with no vector now:** {uni.n_codes - len(uni.created)} distinct ids.",
          f"- **Recall rows:** {counts['rows']}. Unparseable: {log.unparsed}. With no session id: {log.no_context}. "
          f"Instinct layer: {counts['instinct_primary']} in the primary period and {counts['instinct_additive']} "
          f"before it (left out and reported apart). Analysed: {counts['primary']} in the primary period (from "
          f"{day_of(PRIMARY_START)}, engram {TIEBREAK_COMMIT}) and {counts['additive']} in the additive period before "
          "it.",
          f"- **Recall days:** the analysed recalls span {many(counts['span_days'], 'day')}.", ""]

    L += ["## The primary period", ""]
    L += period_section("primary period", results["primary"], verdicts["primary"], True)
    L += ["## The additive period (reported apart)", ""]
    L += period_section("additive period", results["additive"], verdicts["additive"], False)

    L += ["## Named, not modelled", "",
          "- **Meaning made the targets.** Returned ids are ranked by similarity to each query, so meaning starts "
          "ahead by construction. A use win is strong evidence, and a tie says little.",
          "- **Dream and instinct biases** are blended into the query vector, and aren't modelled.",
          "- **Interleaved footpaths.** Claude Code subagents share their parent's Engram server, so their recalls "
          "interleave under one session id. This blurs order.",
          "- **Access-driven decay** removes rarely used episodes' vectors. The universe uses vectors present now.",
          "- **The config check sees today's files.** It can't show what a config said in the past.", ""]

    L += ["## Resources", "",
          f"- **Peak RSS:** {timing['rss']:.1f} MiB. The cap is 512 MiB: RLIMIT_DATA was "
          f"{'set' if timing['cap'] else 'not settable here'}, and peak RSS was checked after each stage.",
          f"- **Wall time:** {timing['wall']:.0f} s.",
          "- **Scratch:** none. Vectors stayed in memory.", ""]
    path.write_text("\n".join(L))


# --------------------------------------------------------------------------------------------------- main


def run(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--store", type=Path, help="an Engram graph.db, read in place with mode=ro")
    source.add_argument("--synthetic", choices=SYNTHETIC_KINDS, help="a planted log, in memory")
    source.add_argument("--self-check", action="store_true", help="check the outcome classifier and stop")
    parser.add_argument("--config", type=Path, action="append", default=[],
                        help="a project's .engram/config.toml to check for recency_mode (repeatable)")
    parser.add_argument("--sessions", type=int, help="synthetic only: how many sessions to plant")
    parser.add_argument("--report", type=Path, help="write the markdown report here")
    args = parser.parse_args(argv)
    if args.sessions is not None and not args.synthetic:
        parser.error("--sessions is for --synthetic only")

    checks = check_classifier()  # before anything is read
    if args.self_check:
        print(f"classifier: {checks} boundary checks passed", file=sys.stderr)
        return 0
    started = time.monotonic()
    cap = limit_memory()
    writer = None
    info: dict = {"classifier_checks": checks}
    if args.synthetic:
        writer, uri, planted = synthetic(args.synthetic, args.sessions)
        info["planted"] = planted
        label = f"synthetic {args.synthetic}"
    else:
        store = args.store.expanduser()
        if not store.is_file():
            raise Stop("the store file does not exist")
        info["config"] = check_config(store, args.config)
        uri = store.resolve().as_uri() + "?mode=ro"
        label = "an Engram store"
    try:
        conn = open_reader(uri)
        try:
            log, uni = read_store(conn)
        finally:
            conn.close()
    finally:
        if writer is not None:
            writer.close()
    guard("reading")

    ok = (log.session >= 0) & ~log.instinct
    primary_idx = np.flatnonzero(ok & (log.t >= PRIMARY_START))
    additive_idx = np.flatnonzero(ok & (log.t < PRIMARY_START))
    analysed = np.flatnonzero(ok)
    counts = {
        "rows": len(log.t) + log.unparsed,
        "instinct_primary": int((log.instinct & (log.t >= PRIMARY_START)).sum()),
        "instinct_additive": int((log.instinct & (log.t < PRIMARY_START)).sum()),
        "primary": len(primary_idx), "additive": len(additive_idx),
        "span_days": int(np.ceil((log.t[analysed].max() - log.t[analysed].min()) / DAY)) if len(analysed) else 0,
    }
    results = {"primary": evaluate(log, uni, primary_idx, 1), "additive": evaluate(log, uni, additive_idx, 2)}
    verdicts = {name: verdict(res) for name, res in results.items()}
    timing = {"rss": peak_rss_mib(), "wall": time.monotonic() - started, "cap": cap,
              "day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
              "sha": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]}
    guard("the run")
    if args.report:
        report(args.report, label, info, log, uni, counts, results, verdicts, timing)

    res, v = results["primary"], verdicts["primary"]
    line = f"E1′ {label}: C1′ {v['c1']}"
    if v["c1"] != "insufficient":
        st = res["stats"]
        line += (f"; D@10 {interval(st[('D', 10)]['session'])} session, {interval(st[('D', 10)]['day'])} day; "
                 f"order {v['order']}: D_order {interval(st['order']['session'])} session, "
                 f"{interval(st['order']['day'])} day; δ_order {fmt(st['delta_order']['value'])}; "
                 f"D_null {interval(st['null']['session'])} session")
    else:
        line += f" ({v['note']})"
    print(line, file=sys.stderr)
    print(f"primary steps {res.get('steps', 0)} in {res.get('step_sessions', 0)} sessions; peak RSS "
          f"{timing['rss']:.1f} MiB; wall {timing['wall']:.0f} s", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except SystemExit:
        raise
    except Stop as stop:
        print(f"stopped: {stop}", file=sys.stderr)
        return 2
    except BaseException as error:  # the message could quote a row, so only its type and place are printed
        frames = traceback.extract_tb(error.__traceback__)
        here = [f for f in frames if os.path.abspath(f.filename) == os.path.abspath(__file__)] or frames[-1:]
        where = f"{here[-1].name}:{here[-1].lineno}" if here else "?"
        print(f"stopped: {type(error).__name__} in {where} (message withheld)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
