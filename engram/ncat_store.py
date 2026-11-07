"""The n-category store: a ship's memory use, kept as cells. Spec: docs/superpowers/specs/2026-11-07-ncat-store.md.

A 0-cell is a memory that some session used, by its id. A road, a 1-generator, is one ordered use after another in a
session, once per ordered pair however often it's walked. A session is the composite of its roads. The file is derived
and disposable: each run rebuilds it whole from Engram's recall log, read-only and by ids only, and renames it into
place. Observational: nothing in recall reads it.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ncat import NCat, NCatError

BUDGET_WORDS = 1 << 22  # counted words; the kernel's resident memory runs about 5.7 times this, by its reviewer's measure
MEMORY_TABLES = ("episodes", "semantics", "instincts")
USED = "coalesce(outcome LIKE 'used%', 0)"

SCHEMA = """
CREATE TABLE generator (id INTEGER PRIMARY KEY, dim INTEGER NOT NULL, source TEXT, target TEXT,
                        kind TEXT NOT NULL, ref TEXT NOT NULL, key TEXT NOT NULL UNIQUE);
CREATE TABLE composite (key TEXT PRIMARY KEY, dim INTEGER NOT NULL, recipe TEXT NOT NULL);
CREATE TABLE session (session_id TEXT PRIMARY KEY, key TEXT NOT NULL, used INTEGER NOT NULL);
CREATE TABLE road_use (road INTEGER NOT NULL, session_id TEXT NOT NULL, step INTEGER NOT NULL);
CREATE TABLE ingest (read_at TEXT NOT NULL, rows_read INTEGER NOT NULL, rows_skipped INTEGER NOT NULL,
                     skip_reasons TEXT NOT NULL, engram_store TEXT NOT NULL, kernel TEXT NOT NULL);
"""


class IntegrityError(RuntimeError):
    """A stored key doesn't match what its recipe builds: the kernel or the file changed under it. Rebuild."""


class Busy(RuntimeError):
    """Another rebuild holds the lock."""


def _parse_time(text):
    """UTC seconds, and whether it had no timezone (taken as UTC, as Engram writes them). None if unparsable."""
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    naive = moment.tzinfo is None
    return (moment.replace(tzinfo=timezone.utc) if naive else moment).timestamp(), naive


def read_engram(engram):
    """Sessions as ordered lists of used memory ids, and what was skipped. Reads ids only, in one read transaction."""
    conn = sqlite3.connect(Path(engram).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        known = set()
        for table in MEMORY_TABLES:
            if table in tables:
                known.update(row[0] for row in conn.execute(f"SELECT id FROM {table}"))
        rows = conn.execute(f"SELECT id, timestamp, target_ids, context FROM memory_log "
                            f"WHERE event_type = 'recall' AND {USED}").fetchall()
        unused = conn.execute(f"SELECT count(*) FROM memory_log WHERE event_type = 'recall' AND NOT {USED}").fetchone()[0]
        conn.execute("COMMIT")
    finally:
        conn.close()
    skipped, naive, kept = Counter(), 0, []
    for row_id, timestamp, targets, context in rows:
        try:
            context = json.loads(context)
        except (TypeError, ValueError):
            context = None
        if not isinstance(context, dict):
            skipped["bad_context"] += 1
            continue
        session = context.get("session_id")
        if not isinstance(session, str) or not session:
            skipped["no_session"] += 1
            continue
        moment = _parse_time(timestamp)
        if moment is None:
            skipped["bad_time"] += 1
            continue
        try:
            targets = json.loads(targets)
        except (TypeError, ValueError):
            targets = None
        if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
            skipped["bad_targets"] += 1
            continue
        naive += moment[1]
        kept.append((session, moment[0], str(row_id), list(dict.fromkeys(targets))))
    kept.sort()  # by session, then parsed time, then the log's id: never the raw string, never row order
    sessions = {}
    for session, _, _, targets in kept:
        for memory in targets:
            if memory not in known:
                skipped["not_a_memory"] += 1
                continue
            sessions.setdefault(session, []).append(memory)
    return sessions, {"rows_read": len(rows) + unused, "unused_rows": unused, "naive_time": naive,
                      "skipped": dict(sorted(skipped.items()))}


def _compose(parts, k):
    """Composites in a balanced tree, not a left fold: the same cell by associativity, and canonicalising stays near
    n log n instead of n squared, since each step's cost grows with its parts."""
    while len(parts) > 1:
        parts = [parts[i].then(parts[i + 1], k) if i + 1 < len(parts) else parts[i] for i in range(0, len(parts), 2)]
    return parts[0]


def _kernel_digest():
    return hashlib.sha256(Path(__file__).with_name("ncat_kernel.c").read_bytes()).hexdigest()[:16]


def _write(path, engram, sessions, report):
    """Every cell through the kernel first, so the file holds only what the kernel accepted, in one transaction."""
    cat = NCat(budget_words=BUDGET_WORDS)
    memories = sorted({m for walk in sessions.values() for m in walk})
    walks = {sid: list(zip(walk, walk[1:])) for sid, walk in sessions.items()}
    uses = Counter(road for roads in walks.values() for road in roads)
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode = DELETE")  # a rollback journal: no -wal or -shm follows the renamed file
        db.executescript(SCHEMA)
        with db:
            objects, roads, generator_id = {}, {}, 0
            for memory in memories:  # generator ids are deterministic, since keys depend on creation order
                cell = objects[memory] = cat.object()
                generator_id += 1
                db.execute("INSERT INTO generator VALUES (?, 0, NULL, NULL, 'object', ?, ?)", (generator_id, memory, cell.key()))
            road_ids = {}
            for a, b in sorted(uses):
                cell = roads[a, b] = cat.generator(objects[a], objects[b])
                generator_id += 1
                road_ids[a, b] = generator_id
                db.execute("INSERT INTO generator VALUES (?, 1, ?, ?, 'road', ?, ?)",
                           (generator_id, objects[a].key(), objects[b].key(), json.dumps([a, b]), cell.key()))
            for sid in sorted(sessions):
                walk = walks[sid]
                if walk:
                    cell = _compose([roads[road] for road in walk], 0)
                    recipe = ["then", 0, [roads[road].key() for road in walk]]
                else:
                    cell, recipe = objects[sessions[sid][0]].identity(), ["id", objects[sessions[sid][0]].key()]
                db.execute("INSERT OR IGNORE INTO composite VALUES (?, ?, ?)", (cell.key(), cell.dim, json.dumps(recipe)))
                db.execute("INSERT INTO session VALUES (?, ?, ?)", (sid, cell.key(), len(sessions[sid])))
                db.executemany("INSERT INTO road_use VALUES (?, ?, ?)",
                               [(road_ids[road], sid, step) for step, road in enumerate(walk)])
            db.execute("INSERT INTO ingest VALUES (?, ?, ?, ?, ?, ?)",
                       (datetime.now(timezone.utc).isoformat(), report["rows_read"], sum(report["skipped"].values()),
                        json.dumps(report["skipped"]), str(Path(engram).resolve()), _kernel_digest()))
    finally:
        db.close()
    return {"sessions": len(sessions), "memories": len(memories), "roads": len(uses)}


def _replace(temporary, store):
    os.replace(temporary, store)


def _fsync(path, flags=os.O_RDONLY):
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def rebuild(engram, store=None):
    """Rebuild the store whole from Engram's log, then rename it into place. One run at a time, by flock."""
    store = Path(store) if store else Path(engram).with_name("ncat.db")
    lock = os.open(f"{store}.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy(f"another rebuild of {store} is running") from None
        for stray in store.parent.glob(f"{store.name}.tmp-*"):
            stray.unlink()
        sessions, report = read_engram(engram)
        temporary = store.with_name(f"{store.name}.tmp-{os.getpid()}")
        os.close(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))  # 0600 from the start
        report.update(_write(temporary, engram, sessions, report))
        _fsync(temporary)
        _replace(temporary, store)
        _fsync(store.parent)
        return report
    finally:
        os.close(lock)  # the system releases the flock with it, and if the process dies


class Store:
    """An opened store: its generators replayed in id order through a fresh kernel, composites rebuilt when asked."""

    def __init__(self, path):
        self._db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        self.cat = NCat(budget_words=BUDGET_WORDS)
        self._by_key, self._memories, self._cells = {}, {}, {}
        for _, dim, source, target, kind, ref, key in self._db.execute("SELECT * FROM generator ORDER BY id"):
            try:
                cell = self.cat.object() if kind == "object" else self.cat.generator(self._by_key[source], self._by_key[target])
            except (KeyError, NCatError) as error:
                raise IntegrityError(f"generator {ref} can't be replayed ({error}); rebuild the store") from None
            if cell.key() != key:
                raise IntegrityError(f"generator {ref} replays to another key; rebuild the store")
            self._by_key[key] = cell
            if kind == "object":
                self._memories[ref] = cell

    def close(self):
        self._db.close()

    def cell(self, key):
        if key in self._cells:
            return self._cells[key]
        row = self._db.execute("SELECT recipe FROM composite WHERE key = ?", (key,)).fetchone()
        if row is None:
            raise IntegrityError(f"no composite with key {key}; rebuild the store")
        try:
            recipe = json.loads(row[0])
            if recipe[0] == "id":
                cell = self._by_key[recipe[1]].identity()
            else:
                cell = _compose([self._by_key[part] for part in recipe[2]], recipe[1])
        except (KeyError, IndexError, TypeError, ValueError, NCatError) as error:
            raise IntegrityError(f"composite {key} can't be rebuilt ({error}); rebuild the store") from None
        if cell.key() != key:
            raise IntegrityError(f"composite {key} rebuilds to another key; rebuild the store")
        self._cells[key] = cell
        return cell

    def session(self, session_id):
        row = self._db.execute("SELECT key FROM session WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return self.cell(row[0])

    def session_ids(self):
        return [row[0] for row in self._db.execute("SELECT session_id FROM session ORDER BY session_id")]

    def memory(self, memory_id):
        return self._memories[memory_id]

    def memory_ids(self):
        return sorted(self._memories)

    def roads(self):
        """Each road, as (from, to), with how many times sessions walked it."""
        return {tuple(json.loads(ref)): count for ref, count in self._db.execute(
            "SELECT g.ref, count(u.road) FROM generator g JOIN road_use u ON u.road = g.id "
            "WHERE g.kind = 'road' GROUP BY g.id ORDER BY g.id")}

    def check(self):
        """Rebuild every composite and session, raising IntegrityError at the first that doesn't match."""
        for (key,) in self._db.execute("SELECT key FROM composite ORDER BY key").fetchall():
            self.cell(key)
        for session_id in self.session_ids():
            self.session(session_id)
        return len(self._cells)


@contextlib.contextmanager
def open_store(path):
    store = Store(path)
    try:
        yield store
    finally:
        store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ncat_store", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("rebuild", help="rebuild the store from an Engram store, read-only")
    build.add_argument("--engram", required=True)
    build.add_argument("--store")
    check = commands.add_parser("check", help="rebuild every cell and check its key")
    check.add_argument("--store", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "rebuild":
            report = rebuild(args.engram, args.store)
            sessions = report["sessions"]
            print(f"{sessions} session{'' if sessions == 1 else 's'}, {report['memories']} memories, {report['roads']} roads; "
                  f"{report['rows_read']} recall rows read, {report['unused_rows']} not used, skipped {report['skipped']}")
        else:
            with open_store(args.store) as store:
                print(f"{store.check()} cells checked")
    except IntegrityError as error:
        print(f"ncat_store: {error}", file=sys.stderr)
        return 2
    except Busy as error:
        print(f"ncat_store: {error}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
