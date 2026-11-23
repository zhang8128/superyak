"""North-star test 6, the n-category half (docs/north-star.md row 6; #2's stop test): what the store holds, checked.

The claim, written before this ran: the store built from a recall log holds exactly each session's ordered walk of
used memories and nothing more. No generator above dimension 1 is built. Its roads, counted, are the walks' bigram
counts, and each session's walk can be read back. So a ranker reading the store can read nothing a ranker reading
the log can't, and #2's comparison "against counts" tests whether order helps, not categorical structure.

300 random logs from seed 20261128, each read here independently of `read_engram`, from the rows as written.
"""
from __future__ import annotations

import json
import random
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

import ncat_store

SEED, INSTANCES = 20261128, 300
MEMORIES = [f"m{i}" for i in range(7)]


def _log(rng):
    """A random log's rows as written: (id, timestamp text, targets JSON, context JSON, outcome)."""
    base = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    rows = []
    for n in range(rng.randint(0, 40)):
        moment = base + timedelta(seconds=rng.randint(0, 3600))
        zone = rng.choice([None, timezone.utc, timezone(timedelta(hours=-5)), timezone(timedelta(hours=2))])
        stamp = moment.replace(tzinfo=None).isoformat() if zone is None else moment.astimezone(zone).isoformat()
        if rng.random() < 0.03:
            stamp = "not a time"
        targets = [rng.choice(MEMORIES + ["gone"]) for _ in range(rng.randint(0, 4))]
        target_text = json.dumps(targets) if rng.random() > 0.03 else "{not json"
        session = rng.choice(["s0", "s1", "s2", "s3"])
        context = json.dumps({"session_id": session}) if rng.random() > 0.05 else rng.choice(
            ["[]", "{broken", json.dumps({"session_id": 7}), json.dumps({})])
        outcome = rng.choice(["used: helped", "used: partly", None, "ignored"])
        rows.append((f"row-{n:03d}", stamp, target_text, context, outcome))
    return rows


def _engram(path, rows):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE episodes (id TEXT PRIMARY KEY, content TEXT);
        CREATE TABLE semantics (id TEXT PRIMARY KEY, content TEXT);
        CREATE TABLE instincts (id TEXT PRIMARY KEY, content TEXT);
        CREATE TABLE memory_log (id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, event_type TEXT NOT NULL,
                                 layer TEXT NOT NULL, target_ids JSON, context JSON, outcome TEXT);
    """)
    db.executemany("INSERT INTO episodes VALUES (?, 'private')", [(m,) for m in MEMORIES])
    db.executemany("INSERT INTO memory_log VALUES (?, ?, 'recall', 'episode', ?, ?, ?)", rows)
    db.commit()
    db.close()
    return path


def _walks(rows):
    """Each session's walk, read from the rows as written, without the store's reader."""
    kept = []
    for row_id, stamp, target_text, context, outcome in rows:
        if not (outcome or "").startswith("used"):
            continue
        try:
            ctx, targets = json.loads(context), json.loads(target_text)
            moment = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if not isinstance(ctx, dict) or not isinstance(ctx.get("session_id"), str) or not ctx["session_id"]:
            continue
        if not isinstance(targets, list):
            continue
        moment = moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment
        kept.append((ctx["session_id"], moment.timestamp(), row_id, list(dict.fromkeys(targets))))
    walks = {}
    for session, _, _, targets in sorted(kept):
        walks.setdefault(session, []).extend(t for t in targets if t in MEMORIES)
    return {s: w for s, w in walks.items() if w}


def _read_back(store_path):
    """The store's dimensions, roads with counts, and each session's walk read back from its roads in step order."""
    db = sqlite3.connect(f"file:{store_path}?mode=ro", uri=True)
    dims = {row[0] for row in db.execute("SELECT DISTINCT dim FROM generator")}
    ends = {gid: json.loads(ref) for gid, ref in db.execute("SELECT id, ref FROM generator WHERE kind = 'road'")}
    walks = {}
    for session, road in db.execute("SELECT session_id, road FROM road_use ORDER BY session_id, step"):
        walk = walks.setdefault(session, [ends[road][0]])
        assert walk[-1] == ends[road][0], "a session's roads don't chain"
        walk.append(ends[road][1])
    sessions = {row[0] for row in db.execute("SELECT session_id FROM session")}
    db.close()
    return dims, walks, sessions


def test_the_store_holds_each_sessions_walk_and_nothing_more(tmp_path):
    rng = random.Random(SEED)
    tallies = Counter()
    for k in range(INSTANCES):
        rows = _log(rng)
        engram = _engram(tmp_path / f"engram-{k}.db", rows)
        store_path = tmp_path / f"ncat-{k}.db"
        ncat_store.rebuild(engram, store_path)
        truth = _walks(rows)
        bigrams = Counter((a, b) for walk in truth.values() for a, b in zip(walk, walk[1:]))
        dims, walks, sessions = _read_back(store_path)
        with ncat_store.open_store(store_path) as store:
            assert store.roads() == dict(bigrams), k                       # roads, counted, are the bigram counts
        assert dims <= {0, 1}, k                                             # no 2-cell, no cost, nothing above
        assert sessions == set(truth), k                                     # every session with a used memory
        assert walks == {s: w for s, w in truth.items() if len(w) > 1}, k    # each walk reads back exactly
        tallies["instances"] += 1
        tallies["sessions"] += len(truth)
        tallies["roads walked"] += sum(bigrams.values())
        tallies["single-memory sessions"] += sum(len(w) == 1 for w in truth.values())
    print(dict(tallies))
