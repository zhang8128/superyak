"""The permission ledger file (P 5.5, 5.6): ENGRAM_HOME/.engram/permissions.db.

An append-only, hash-chained log (`ledger_log`) is the source of truth. Every table is a projection of it,
written in the same `BEGIN IMMEDIATE` as the log row, by the one projection code `rebuild` replays.

A log row's `body` is canonical JSON with these optional parts (the `kind` is a label; all kinds share this):

    {"insert": [{"table": T, "row": {...}}],         # rows added to table T
     "update": [{"table": T, "where": {...}, "set": {...}}],   # columns set on the rows matching `where`
     "meta":   {key: value},                         # meta keys set
     "name":   "Public Health",                      # a register-place's display name (R4)
     "houses": [".engram/graph.db"]}                 # a gate act's record of the houses it marked (not projected)

In a row or a `set`, the string "@seq" stands for the log row's own seq and "@at" for its time; a dict or list
value is stored as canonical JSON text; a places row's `pseudonym_salt` is hex."""
from __future__ import annotations

import hashlib
import json
import dataclasses
import os
import sqlite3
import threading
import uuid
import weakref
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable, Iterator, Mapping, Sequence

import permissions

from lighthouse_protocol import artifact_digest, canonical_json
from permissions import (
    CHANNELS, GATE_HOUSES, GRANT_OPS, JOINTS_PER_CHANGE, LANES, MAX_COPY_CHAIN, MAX_PLACES, MAX_REPLACES, MAX_SUBJECTS,
    PROPOSAL_DAYS, REASON_CHARS, REGISTRY, Act, Authority, Grant, Record, Selector, State, RuleError,
    affected_joints, authorize, check_child_grant, check_id, check_new_members, check_new_parent,
    check_new_place, check_new_subject, check_record, check_root_grant, gluing, grant_chain, home_of,
    parse_copy_ref, parse_object_ref, parse_selector, person_of_home, proposal_words, selector_json, subjects_of,
    _COLUMNS, _NULLABLE, _acts_for_person, _date, _is_steward, _live, _layer_steward, _own_subjects, _principals)

SCHEMA_VERSION = "1"
ZERO = "0" * 64
_RULE = "5.5 storage"
BUSY_MS = 5000

_SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE ledger_log(seq INTEGER PRIMARY KEY, at INTEGER NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL,
  actor TEXT NOT NULL, channel TEXT NOT NULL, under_grant TEXT, proposal_id TEXT, body TEXT NOT NULL,
  prev_digest TEXT NOT NULL, digest TEXT NOT NULL);
CREATE TABLE persons(id TEXT PRIMARY KEY, home TEXT NOT NULL UNIQUE, is_admin INTEGER NOT NULL, created_seq INTEGER NOT NULL,
  retired_seq INTEGER);
CREATE TABLE places(id TEXT PRIMARY KEY, is_root INTEGER NOT NULL, created_seq INTEGER NOT NULL, retired_seq INTEGER,
  pseudonym_salt BLOB NOT NULL);
CREATE TABLE place_parents(place TEXT NOT NULL, parent TEXT NOT NULL, added_seq INTEGER NOT NULL, PRIMARY KEY(place, parent));
CREATE TABLE place_stewards(place TEXT NOT NULL, person TEXT NOT NULL, added_seq INTEGER NOT NULL, removed_seq INTEGER);
CREATE TABLE agents(id TEXT PRIMARY KEY, acts_for TEXT NOT NULL, created_seq INTEGER NOT NULL, retired_seq INTEGER);
CREATE TABLE agent_places(agent TEXT NOT NULL, place TEXT NOT NULL, added_seq INTEGER NOT NULL, removed_seq INTEGER);
CREATE UNIQUE INDEX agent_places_one ON agent_places(agent) WHERE removed_seq IS NULL;  -- P31
CREATE TABLE stores(instance_id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, place TEXT NOT NULL,
  imprint_of TEXT, created_seq INTEGER NOT NULL);
CREATE TABLE groups(id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_seq INTEGER NOT NULL);
CREATE TABLE group_members(group_id TEXT NOT NULL, agent TEXT NOT NULL, added_seq INTEGER NOT NULL, removed_seq INTEGER);
CREATE TABLE collections(id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_seq INTEGER NOT NULL);
CREATE TABLE collection_members(collection TEXT NOT NULL, object TEXT NOT NULL, backing TEXT NOT NULL,
  added_seq INTEGER NOT NULL, added_by TEXT NOT NULL, removed_seq INTEGER, removed_by TEXT);
CREATE TABLE subjects(object TEXT NOT NULL, subject TEXT NOT NULL, added_seq INTEGER NOT NULL, added_by TEXT NOT NULL,
  self_claimed INTEGER NOT NULL, removed_seq INTEGER, removed_by TEXT);
CREATE TABLE copies(object TEXT PRIMARY KEY, source TEXT NOT NULL, added_seq INTEGER NOT NULL);  -- P25
CREATE TABLE lane_notes(object TEXT NOT NULL, lane TEXT NOT NULL, at INTEGER NOT NULL, seq INTEGER NOT NULL);
  -- lane is 'personal', 'work' or 'pending'
CREATE TABLE records(id TEXT PRIMARY KEY, layer TEXT NOT NULL, effect TEXT NOT NULL, selector TEXT NOT NULL,
  valid_from INTEGER NOT NULL, valid_until INTEGER, anchor INTEGER NOT NULL, backing TEXT NOT NULL, set_by TEXT NOT NULL,
  channel TEXT NOT NULL, under_grant TEXT, proposal_id TEXT, replaces TEXT, reason TEXT NOT NULL,
  created INTEGER NOT NULL, created_seq INTEGER NOT NULL, revoked INTEGER, revoked_by TEXT, revoke_reason TEXT,
  revoked_seq INTEGER);
CREATE TABLE permission_grants(id TEXT PRIMARY KEY, issuer TEXT NOT NULL, grantee TEXT NOT NULL, layer TEXT NOT NULL,
  parent_id TEXT, ops TEXT NOT NULL, envelope TEXT NOT NULL, max_days INTEGER NOT NULL, depth INTEGER NOT NULL,
  expires INTEGER NOT NULL, created INTEGER NOT NULL, created_seq INTEGER NOT NULL, revoked INTEGER, revoked_by TEXT,
  revoke_reason TEXT, revoked_seq INTEGER);
CREATE TABLE proposals(id TEXT PRIMARY KEY, by_agent TEXT NOT NULL, for_person TEXT NOT NULL, kind TEXT NOT NULL,
  body TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL, status TEXT NOT NULL,
  decided_seq INTEGER);
CREATE INDEX records_layer ON records(layer);
CREATE INDEX grants_layer ON permission_grants(layer);
CREATE INDEX place_stewards_place ON place_stewards(place);
CREATE INDEX collection_members_object ON collection_members(object);
CREATE INDEX collection_members_collection ON collection_members(collection);
CREATE INDEX subjects_object ON subjects(object);
CREATE INDEX lane_notes_object ON lane_notes(object);
CREATE INDEX group_members_group ON group_members(group_id);
CREATE INDEX subjects_removed ON subjects(removed_seq) WHERE removed_seq IS NOT NULL;
CREATE INDEX collection_members_removed ON collection_members(removed_seq) WHERE removed_seq IS NOT NULL;
CREATE INDEX proposals_decided ON proposals(decided_seq) WHERE decided_seq IS NOT NULL;
"""
# the indexes a writing open adds to a ledger made before they were in the schema
_LATER_INDEXES = (
    "CREATE INDEX IF NOT EXISTS collection_members_collection ON collection_members(collection)",
    "CREATE INDEX IF NOT EXISTS subjects_removed ON subjects(removed_seq) WHERE removed_seq IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS collection_members_removed ON collection_members(removed_seq) "
    "WHERE removed_seq IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS proposals_decided ON proposals(decided_seq) WHERE decided_seq IS NOT NULL",
)

# the tables a State reads per object, through StateRows, and not whole
_PER_OBJECT = frozenset({"subjects", "lane_notes", "collection_members", "copies"})
# the tables a State reads a row of when asked, and never holds: no decision reads them (ProposalMap)
_ON_DEMAND = frozenset({"proposals"})
# table order for tables(): the order of the schema
_TABLES = tuple(_COLUMNS)
_LOG_COLUMNS = ("seq", "at", "kind", "ref", "actor", "channel", "under_grant", "proposal_id", "body",
                "prev_digest", "digest")
_HOT = ("This ledger has a hot journal from a writer that stopped mid-commit, which a read-only reader cannot "
        "roll back. Every reader reads `closed` until a writing open clears it: run any writing command, "
        "such as `engram-permissions sweep`.")
# Every column that holds the seq of the log row that wrote it (P 5.6). A file copy taken mid-commit without its
# journal (a torn restore) can keep a log row's projection and lose the row: that seq is then past the log's last.
# Or it can keep the row and lose its projection: a column the last row sets then does not hold the row's seq.
_SEQ_COLUMNS = {t: cs for t, cs in ((t, tuple(c for c in cols if c == "seq" or c.endswith("_seq")))
                                    for t, cols in _COLUMNS.items()) if cs}
# the seq columns an update sets on an older row; every other one is set only when its row is inserted
_SET_LATER = frozenset({"retired_seq", "removed_seq", "revoked_seq", "decided_seq"})
_CUT = ("The log's tail was cut, as by a copy or restore of the file taken mid-write without its journal, so the "
        "tables may hold a change, such as a revocation, that the log has lost, or lack one the log holds. Every "
        "reader refuses the ledger until it verifies (P 5.6): `engram-permissions verify` reports it. Restore the "
        "file together with its journal, or replay the log that is left with `engram-permissions rebuild --out "
        "<dir>` and make the lost acts again.")


class LedgerUnreadable(Exception):
    pass


class LogTimes(Mapping):
    """The time of each log row up to `seq`, read from the ledger when a decision asks (P 5.6, 15). A read-only
    `Mapping` of seq to `at` over `ledger_log`: it answers only for 1 <= seq <= the State's seq, keeps at most
    `permissions.STATE_LOG_TIMES` times (the least recently used leave first) and iterates in seq order,
    streaming. The log is append-only, so a row at or below the State's seq reads the same whenever it is read.
    A failed read raises `LedgerUnreadable`; a caller treats that as a failed `state()`. The reader connection
    is shared between threads under a lock and closed when this object is collected."""
    _CHUNK = 1024

    def __init__(self, conn: sqlite3.Connection, seq: int):
        self._conn, self._seq = conn, seq
        self._lock = threading.Lock()
        self._cache: OrderedDict = OrderedDict()
        weakref.finalize(self, conn.close)

    def _query(self, sql: str, args: tuple) -> list:
        try:
            with self._lock:
                return self._conn.execute(sql, args).fetchall()
        except sqlite3.Error as e:
            raise LedgerUnreadable(f"the permission ledger's log could not be read: {e}") from e

    def _fetch(self, seq: int) -> int | None:
        rows = self._query("SELECT at FROM ledger_log WHERE seq = ?", (seq,))
        return rows[0][0] if rows else None

    def __getitem__(self, seq: int) -> int:
        if not isinstance(seq, int) or isinstance(seq, bool) or not 1 <= seq <= self._seq:
            raise KeyError(seq)
        with self._lock:
            hit = self._cache.get(seq)
            if hit is not None:
                self._cache.move_to_end(seq)
                return hit
        at = self._fetch(seq)
        if at is None:
            raise KeyError(seq)
        with self._lock:
            self._cache[seq] = at
            self._cache.move_to_end(seq)
            while len(self._cache) > permissions.STATE_LOG_TIMES:
                self._cache.popitem(last=False)
        return at

    def prefetch(self, seqs) -> None:
        """Read the times of these seqs (those within 1..the State's seq) in queries of 512, into the cache; any
        other value is ignored. The cache keeps its cap."""
        with self._lock:
            want = sorted({s for s in seqs if isinstance(s, int) and not isinstance(s, bool)
                           and 1 <= s <= self._seq and s not in self._cache})
        for i in range(0, len(want), 512):
            chunk = want[i:i + 512]
            rows = self._query(f"SELECT seq, at FROM ledger_log WHERE seq IN ({','.join('?' * len(chunk))})",
                               tuple(chunk))
            with self._lock:
                for s, at in rows:
                    self._cache[s] = at
                    self._cache.move_to_end(s)
                while len(self._cache) > permissions.STATE_LOG_TIMES:
                    self._cache.popitem(last=False)

    def __iter__(self) -> Iterator[int]:
        last = 0
        while True:
            rows = self._query("SELECT seq FROM ledger_log WHERE seq > ? AND seq <= ? ORDER BY seq LIMIT ?",
                               (last, self._seq, self._CHUNK))
            if not rows:
                return
            for (s,) in rows:
                yield s
            last = rows[-1][0]

    def __len__(self) -> int:
        return self._query("SELECT COUNT(*) FROM ledger_log WHERE seq <= ?", (self._seq,))[0][0]

class _Spec:
    """How one per-object table is read: its key column, the column that says when a row was added, the rows'
    order within a key, the columns that go back to null while their seq is in the future (`permissions._UNDONE`)
    and the columns whose strings repeat, which a State pools."""
    def __init__(self, table: str, key: str, order: str, pooled: Sequence[str]):
        self.table, self.key, self.order = table, key, order
        cols = permissions._COLUMNS[table]
        self.cols = ", ".join(cols)
        self.added = permissions._ADDED[table]
        self.make = permissions._ROW[table]
        self.key_at = cols.index(key)
        self.pooled = tuple(cols.index(c) for c in pooled)
        undone = permissions._UNDONE.get(table)
        self.seq_at = cols.index(undone[0]) if undone else None
        self.clear = tuple(cols.index(c) for c in undone[1]) if undone else ()


_SPECS = {
    "subjects": _Spec("subjects", "object", "rowid", ("subject", "added_by", "removed_by")),
    "member_of": _Spec("collection_members", "object", "rowid", ("collection", "backing", "added_by", "removed_by")),
    "collection_members": _Spec("collection_members", "collection", "rowid",
                                ("collection", "backing", "added_by", "removed_by")),
    "lane_notes": _Spec("lane_notes", "object", "at, seq, rowid", ("lane",)),
    "copies": _Spec("copies", "object", "rowid", ()),
}


class StateRows:
    """The per-object rows of one State, read from the ledger when a decision asks (P 5.6, 15). One bounded cache
    serves every `RowMap` of the State: at most `permissions.STATE_ROWS` rows (an empty key counts as one), the
    least recently used keys leaving first. A key whose rows alone pass the bound is returned and not kept.
    Strings that repeat come from a pool of this State's. A row is read as `State.from_tables` reads it at the
    State's seq: one added past it is left out, and the `_UNDONE` columns are cleared when their seq is past it.
    The reader connection is shared between threads under a lock and closed when this object is collected."""
    BATCH = 512

    def __init__(self, conn: sqlite3.Connection, seq: int):
        conn.row_factory = None
        self.conn, self.seq = conn, seq
        self._db_lock = threading.Lock()
        self._lock = threading.Lock()
        self._cache: OrderedDict = OrderedDict()
        self._held = 0
        self._pool: dict = {}
        weakref.finalize(self, conn.close)

    def cached_rows(self) -> int:
        return self._held

    def _query(self, sql: str, args: tuple) -> list:
        try:
            with self._db_lock:
                return self.conn.execute(sql, args).fetchall()
        except sqlite3.Error as e:
            raise LedgerUnreadable(f"the permission ledger's rows could not be read: {e}") from e

    def _build(self, spec: _Spec, vals: tuple):
        if spec.seq_at is not None:
            v = vals[spec.seq_at]
            if v is not None and v > self.seq:
                vals = list(vals)
                for i in spec.clear:
                    vals[i] = None
        if spec.pooled:
            vals = list(vals)
            pool = self._pool
            for i in spec.pooled:
                v = vals[i]
                if v is not None:
                    vals[i] = pool.setdefault(v, v)
        return spec.make(*vals)

    def load(self, name: str, keys: Sequence[str]) -> dict:
        """The rows of each key (an empty tuple for a key with none), read now and not cached."""
        spec = _SPECS[name]
        out: dict = {k: [] for k in keys}
        marks = ", ".join("?" * len(keys))
        rows = self._query(f"SELECT {spec.cols} FROM {spec.table} WHERE {spec.key} IN ({marks}) "
                           f"AND {spec.added} <= ? ORDER BY {spec.order}", (*keys, self.seq))
        for vals in rows:
            out[vals[spec.key_at]].append(self._build(spec, vals))
        return {k: tuple(v) for k, v in out.items()}

    def _keep(self, name: str, key: str, rows: tuple) -> None:
        cost = max(1, len(rows))
        if cost > permissions.STATE_ROWS:
            return
        with self._lock:
            old = self._cache.pop((name, key), None)
            if old is not None:
                self._held -= max(1, len(old))
            self._cache[(name, key)] = rows
            self._held += cost
            while self._held > permissions.STATE_ROWS:
                _, gone = self._cache.popitem(last=False)
                self._held -= max(1, len(gone))

    def rows(self, name: str, key) -> tuple:
        if not isinstance(key, str):
            return ()
        with self._lock:
            hit = self._cache.get((name, key))
            if hit is not None:
                self._cache.move_to_end((name, key))
                return hit
        rows = self.load(name, (key,))[key]
        self._keep(name, key, rows)
        return rows

    def prefetch(self, refs: Sequence[str]) -> set:
        """Load the rows of up to 512 refs a query. Returns the seqs the subjects and membership rows read were
        added and removed at, which the State's log times read in batches too."""
        wanted = list(dict.fromkeys(r for r in refs if isinstance(r, str)))
        seqs: set = set()
        for i in range(0, len(wanted), self.BATCH):
            chunk = wanted[i:i + self.BATCH]
            for name in ("subjects", "member_of", "lane_notes", "copies"):
                with self._lock:
                    need = [k for k in chunk if (name, k) not in self._cache]
                if need:
                    for k, rows in self.load(name, need).items():
                        self._keep(name, k, rows)
                        if name in ("subjects", "member_of"):
                            for r in rows:
                                seqs.add(r.added_seq)
                                if r.removed_seq is not None:
                                    seqs.add(r.removed_seq)
        return seqs

    def count(self, name: str) -> int:
        spec = _SPECS[name]
        return self._query(f"SELECT COUNT(DISTINCT {spec.key}) FROM {spec.table} WHERE {spec.added} <= ?",
                           (self.seq,))[0][0]

    def keys(self, name: str) -> Iterator[str]:
        spec, last = _SPECS[name], None
        while True:
            after = "" if last is None else f"{spec.key} > ? AND "
            args = (self.seq,) if last is None else (last, self.seq)
            rows = self._query(f"SELECT DISTINCT {spec.key} FROM {spec.table} WHERE {after}{spec.added} <= ? "
                               f"ORDER BY {spec.key} LIMIT {self.BATCH}", args)
            if not rows:
                return
            for (k,) in rows:
                yield k
            last = rows[-1][0]

    def batches(self, name: str) -> Iterator[dict]:
        """Every key's rows, in batches of 512 keys, read and not cached."""
        batch: list = []
        for k in self.keys(name):
            batch.append(k)
            if len(batch) == self.BATCH:
                yield self.load(name, batch)
                batch = []
        if batch:
            yield self.load(name, batch)


class RowMap(Mapping):
    """A read-only `Mapping` over one per-object table at the State's seq, as `State.from_tables` makes it: the
    rows of a key as a tuple (or, for `copies` and `copy_seqs`, the source or the seq). A key with no rows is
    absent. `len` counts the keys at seq, and iteration and `items()` stream in batches of 512 keys."""
    def __init__(self, reader: StateRows, name: str, project: Callable | None = None):
        self._reader, self._name, self._project = reader, name, project

    def _out(self, rows: tuple):
        return rows if self._project is None else self._project(rows[0])

    def __getitem__(self, key):
        rows = self._reader.rows(self._name, key)
        if not rows:
            raise KeyError(key)
        return self._out(rows)

    def get(self, key, default=None):
        rows = self._reader.rows(self._name, key)
        return self._out(rows) if rows else default

    def __contains__(self, key) -> bool:
        return bool(self._reader.rows(self._name, key))

    def __len__(self) -> int:
        return self._reader.count(self._name)

    def __iter__(self) -> Iterator[str]:
        return self._reader.keys(self._name)

    def items(self):
        for batch in self._reader.batches(self._name):
            for k, rows in batch.items():
                if rows:
                    yield k, self._out(rows)

    def values(self):
        for _k, v in self.items():
            yield v


class ProposalMap(Mapping):
    """The State's `proposals`, read from the ledger when asked and never held (P 15, P37; the final review's I1):
    no decision reads a proposal, and an agent can file up to `MAX_OPEN_PROPOSALS` of them, each holding a whole
    act, besides every decided and expired one. A row reads as `State.from_tables` reads it at the State's seq:
    one decided past the seq is pending. Iteration and `values()` stream in batches of 512 rows, by rowid."""
    _COLS = ", ".join(permissions._COLUMNS["proposals"])

    def __init__(self, reader: StateRows):
        self._reader = reader

    def _row(self, vals: tuple):
        r = permissions._ROW["proposals"](*vals)
        if r.decided_seq is not None and r.decided_seq > self._reader.seq:
            r = r._replace(status="pending", decided_seq=None)
        return r

    def __getitem__(self, pid):
        rows = self._reader._query(f"SELECT {self._COLS} FROM proposals WHERE id = ?", (pid,)) \
            if isinstance(pid, str) else []
        if not rows:
            raise KeyError(pid)
        return self._row(rows[0])

    def __contains__(self, pid) -> bool:
        return isinstance(pid, str) and bool(
            self._reader._query("SELECT 1 FROM proposals WHERE id = ?", (pid,)))

    def __len__(self) -> int:
        return self._reader._query("SELECT COUNT(*) FROM proposals", ())[0][0]

    def _batches(self, cols: str) -> Iterator[list]:
        last = 0
        while True:
            rows = self._reader._query(f"SELECT rowid, {cols} FROM proposals WHERE rowid > ? ORDER BY rowid "
                                       f"LIMIT {StateRows.BATCH}", (last,))
            if not rows:
                return
            yield [r[1:] for r in rows]
            last = rows[-1][0]

    def __iter__(self) -> Iterator[str]:
        for batch in self._batches("id"):
            for (pid,) in batch:
                yield pid

    def items(self):
        for batch in self._batches(self._COLS):
            for vals in batch:
                yield vals[0], self._row(vals)

    def values(self):
        for _pid, row in self.items():
            yield row

    def open_ids(self, now: int) -> list[str]:
        """The ids of the open proposals (pending at the State's seq, not expired at `now`), oldest first."""
        return [pid for (pid,) in self._reader._query(
            "SELECT id FROM proposals WHERE (status = 'pending' OR decided_seq > ?) AND expires > ? "
            "ORDER BY created, id", (self._reader.seq, now))]


@dataclass(frozen=True)
class Outcome:
    """What `Ledger.perform` did: `done`, or `proposal` (a proposal was filed, or one signature was added).
    `ref` is the thing written (or the proposal's id) and `seq` the log row. `reports` are the gluing reports of
    up to JOINTS_PER_CHANGE joint places after a registry change (R5); `pending_checks` names the rest.
    `lacking_029` is set by a gate act."""
    status: str
    ref: str
    seq: int
    reports: tuple = ()
    pending_checks: tuple = ()
    lacking_029: tuple = ()       # a gate act: the houses without migration 029 (R27), for the CLI to print


def ledger_path(engram_home: Path) -> Path:
    return Path(engram_home) / ".engram" / "permissions.db"


def make_private(path: Path) -> None:
    """Create `path` empty with mode 0600 unless it exists: the ledger, the receipts file and the migrate plan name
    people and their uses (Serenity's section 2, nits). SQLite fills an empty file as a new database, and makes
    its journal with the database's mode."""
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError:
        pass


def new_id(prefix: str) -> str:
    return prefix + os.urandom(16).hex()


def _digest(prev: str, entry: Mapping) -> str:
    return hashlib.sha256((prev + "\n" + canonical_json(dict(entry))).encode("utf-8")).hexdigest()


def _entry(row) -> dict:
    return {"seq": row["seq"], "at": row["at"], "kind": row["kind"], "ref": row["ref"], "actor": row["actor"],
            "channel": row["channel"], "under_grant": row["under_grant"], "proposal_id": row["proposal_id"],
            "body": row["body"]}


def _bad(why: str) -> RuleError:
    return RuleError(_RULE, why)


class Ledger:
    def __init__(self, conn: sqlite3.Connection, path: Path, read_only: bool):
        self.conn, self.path, self.read_only = conn, path, read_only

    # ---------------------------------------------------------------- opening
    @staticmethod
    def _connect(path: Path, *, read_only: bool, busy_ms: int = BUSY_MS, shared: bool = False) -> sqlite3.Connection:
        try:
            if read_only:
                conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None,
                                       timeout=busy_ms / 1000, check_same_thread=not shared)
                conn.execute("PRAGMA query_only=ON")
            else:
                conn = sqlite3.connect(path, isolation_level=None, timeout=busy_ms / 1000)
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout={busy_ms}")
            return conn
        except sqlite3.Error as e:
            raise LedgerUnreadable(f"{path}: {e}") from e

    @classmethod
    def _open(cls, engram_home: Path, read_only: bool, busy_ms: int = BUSY_MS) -> "Ledger":
        path = ledger_path(engram_home)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        conn = cls._connect(path, read_only=read_only, busy_ms=busy_ms)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None or row["value"] != SCHEMA_VERSION:
                conn.close()
                raise LedgerUnreadable(f"{path}: not a version {SCHEMA_VERSION} permission ledger")
        except sqlite3.Error as e:
            conn.close()
            hot = path.with_name(path.name + "-journal").exists()
            raise LedgerUnreadable(f"{path}: {e}. {_HOT if hot else ''}".strip()) from e
        if not read_only:
            try:            # a ledger made before these indexes were in the schema reads by them
                for sql in _LATER_INDEXES:
                    conn.execute(sql)
            except sqlite3.Error as e:
                conn.close()
                raise LedgerUnreadable(f"{path}: {e}") from e
        return cls(conn, path, read_only)

    @classmethod
    def open(cls, engram_home: Path) -> "Ledger":
        return cls._open(engram_home, False)

    @classmethod
    def open_read_only(cls, engram_home: Path, busy_ms: int = BUSY_MS) -> "Ledger":
        return cls._open(engram_home, True, busy_ms)

    @classmethod
    def _blank(cls, engram_home: Path, ledger_id: str, path: Path | None = None) -> "Ledger":
        path = ledger_path(engram_home) if path is None else path
        if path.exists():
            raise FileExistsError(str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        make_private(path)
        conn = cls._connect(path, read_only=False)
        conn.executescript(_SCHEMA)
        conn.executemany("INSERT INTO meta VALUES(?,?)",
                         [("ledger_id", ledger_id), ("schema_version", SCHEMA_VERSION)])
        return cls(conn, path, False)

    @classmethod
    def create(cls, engram_home: Path, owner_handle: str, *, now: int, channel: str = "terminal",
               path: Path | None = None) -> "Ledger":
        """A new ledger owned by person:<owner_handle>, at `ledger_path(engram_home)` or at `path`, a file beside it
        that the caller renames into place (`migrate`, Tardis's T8)."""
        owner = check_id("person", "person:" + owner_handle)
        home = "place:home/" + owner_handle
        check_id("place", home)
        led = cls._blank(engram_home, str(uuid.uuid4()), path=path)
        led._append("register-person", owner, owner, channel, {
            "meta": {"owner": owner, "admins": owner},
            "insert": [
                {"table": "persons", "row": {"id": owner, "home": home, "is_admin": 1, "created_seq": "@seq"}},
                {"table": "places", "row": {"id": home, "is_root": 1, "created_seq": "@seq",
                                            "pseudonym_salt": os.urandom(16).hex()}},
                {"table": "place_stewards", "row": {"place": home, "person": owner, "added_seq": "@seq"}}]},
            at=now)
        return led

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- reading
    def seq(self) -> int:
        return self.conn.execute("SELECT COALESCE(MAX(seq), 0) FROM ledger_log").fetchone()[0]

    def meta(self) -> dict:
        return {r["key"]: r["value"] for r in self.conn.execute("SELECT key, value FROM meta ORDER BY key")}

    def tables(self) -> dict:
        out = {"meta": [dict(r) for r in self.conn.execute("SELECT key, value FROM meta ORDER BY key")],
               "ledger_log": [dict(r) for r in self.conn.execute("SELECT * FROM ledger_log ORDER BY seq")]}
        for t in _TABLES:
            cols = ", ".join(_COLUMNS[t])
            out[t] = [dict(r) for r in self.conn.execute(f"SELECT {cols} FROM {t} ORDER BY rowid")]
        return out

    def state(self, seq: int | None = None) -> State:
        # One read transaction: the log, the tables and meta all come from the same committed seq (P 5.6).
        self.conn.execute("BEGIN")
        try:
            top = self.seq()
            seq = top if seq is None else seq
            if not 0 <= seq <= top:
                raise ValueError(f"seq {seq} is outside the log (0 to {top})")
            n_records = self.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            if n_records > permissions.MAX_RECORDS:
                raise LedgerUnreadable(
                    f"{self.path}: the ledger holds {n_records:,} records, more than the {permissions.MAX_RECORDS:,} "
                    f"a State holds whole (P 5.4, 15); it reads as unreadable (P 5.6) until the records are read "
                    f"per layer")
            tables = {t: [dict(r) for r in self.conn.execute(
                f"SELECT {', '.join(_COLUMNS[t])} FROM {t} ORDER BY rowid")] for t in _TABLES
                if t not in _PER_OBJECT and t not in _ON_DEMAND}
            meta = self.meta()
            cut = self._tail_problems(top, meta, tables)
            if cut:
                raise LedgerUnreadable(f"{self.path}: {cut[0]}. {_CUT}")
            # the only log bodies a State reads: place names. Log times are read when a decision asks.
            names = {}
            for r in self.conn.execute(
                    "SELECT ref, body FROM ledger_log WHERE kind = 'register-place' AND seq <= ? ORDER BY seq",
                    (seq,)):
                name = json.loads(r["body"]).get("name")
                if name:
                    names[r["ref"]] = name
            claims = tuple(self._self_claims(seq))
        finally:
            self.conn.execute("COMMIT")
        # second read-only connections: the log is append-only and the per-object rows carry the seqs that say
        # what they were, so rows up to `seq` read the same later
        reader = StateRows(self._connect(self.path, read_only=True, shared=True), seq)
        state = State.from_tables(tables, seq=seq, seq_at=LogTimes(self._connect(self.path, read_only=True,
                                                                                  shared=True), seq),
                                  meta=meta, names=names)
        return dataclasses.replace(
            state, subjects=RowMap(reader, "subjects"), lane_notes=RowMap(reader, "lane_notes"),
            member_of=RowMap(reader, "member_of"), collection_members=RowMap(reader, "collection_members"),
            copies=RowMap(reader, "copies", lambda r: r.source),
            copy_seqs=RowMap(reader, "copies", lambda r: r.added_seq), proposals=ProposalMap(reader),
            self_claims=claims, _loader=reader)

    def _self_claims(self, seq: int) -> Iterator:
        """The live self-claimed subject rows at `seq`, objects in the order of their first row (7.4)."""
        cols = ", ".join("s." + c for c in _COLUMNS["subjects"])
        for r in self.conn.execute(
                f"SELECT {cols} FROM subjects s WHERE s.self_claimed != 0 AND s.added_seq <= ? "
                f"AND (s.removed_seq IS NULL OR s.removed_seq > ?) "
                f"ORDER BY (SELECT MIN(f.rowid) FROM subjects f WHERE f.object = s.object AND f.added_seq <= ?), "
                f"s.rowid", (seq, seq, seq)).fetchall():
            row = permissions._ROW["subjects"](*r)
            yield row._replace(removed_seq=None, removed_by=None)

    def pending_lane_notes(self) -> Iterator[str]:
        """The objects whose latest lane note at the ledger's seq is `pending`, streamed (P 5.3)."""
        seq = self.seq()
        for (obj,) in self.conn.execute(
                "SELECT n.object FROM lane_notes n WHERE n.lane = 'pending' AND n.seq <= ? AND NOT EXISTS ("
                "SELECT 1 FROM lane_notes m WHERE m.object = n.object AND m.seq <= ? AND "
                "(m.at, m.seq, m.rowid) > (n.at, n.seq, n.rowid)) ORDER BY n.object", (seq, seq)):
            yield obj

    def verify(self) -> int | None:
        prev, expect = ZERO, 1
        for row in self.conn.execute("SELECT * FROM ledger_log ORDER BY seq"):
            if row["seq"] != expect or row["prev_digest"] != prev or row["digest"] != _digest(prev, _entry(row)):
                return expect
            prev, expect = row["digest"], expect + 1
        return None

    def _head(self, top: int) -> str | None:
        """`<seq>:<digest>` of the log's last row, the value `meta.head` holds; None for an empty log."""
        row = self.conn.execute("SELECT seq, digest FROM ledger_log WHERE seq = ?", (top,)).fetchone()
        return None if row is None else f"{row[0]}:{row[1]}"

    def _head_problem(self, top: int, meta: Mapping) -> str | None:
        """How `meta.head`, when the ledger keeps one, is not the log's last row, in words; None when it is."""
        head, last = meta.get("head"), self._head(top)
        if head is None or head == last:
            return None
        return f"meta.head names seq {head.split(':', 1)[0]} ({head}), but the log's last row is {last or 'none'}"

    def _max_seq(self, table: str, column: str, loaded: Mapping | None):
        """The highest value of a seq column. A table the State read whole is read from `loaded`. Otherwise, with
        `loaded` given (a State, or `_append` with {}, which must stay cheap), a column an update sets is read
        through its partial index, or whole in a table a State reads whole (they are small), and one set only at
        insert from the table's newest row: rows are only ever inserted, in seq order, and never deleted, so the
        newest carries the highest. With `loaded` None (`integrity`), every row is read."""
        if loaded is not None and table in loaded:
            return max((r[column] for r in loaded[table] if r[column] is not None), default=None)
        if loaded is None or column in _SET_LATER:
            sql = f"SELECT MAX({column}) FROM {table} WHERE {column} IS NOT NULL"
        else:
            sql = f"SELECT {column} FROM {table} ORDER BY rowid DESC LIMIT 1"
        row = self.conn.execute(sql).fetchone()
        return None if row is None else row[0]

    def _last_sets(self, top: int) -> tuple[set, str | None]:
        """The seq columns, as (table, column), that the log's last row sets to its own seq ("@seq"), and why its
        body cannot be read, if it cannot."""
        row = self.conn.execute("SELECT body FROM ledger_log WHERE seq = ?", (top,)).fetchone()
        if row is None:
            return set(), None
        try:
            body = json.loads(row[0])
            sets = [(i["table"], i["row"]) for i in body.get("insert", ())]
            sets += [(i["table"], i["set"]) for i in body.get("update", ())]
            return {(t, c) for t, values in sets for c, v in values.items()
                    if v == "@seq" and c in _SEQ_COLUMNS.get(t, ())}, None
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            return set(), f"the body of the log's last row, seq {top}, cannot be read ({e!r})"

    def _tail_problems(self, top: int, meta: Mapping, loaded: Mapping | None = None) -> list[str]:
        """P 5.6: the tables are the log's projection, so no seq column names a seq past the log's last row,
        `meta.head`, when the ledger keeps one, is that row, and each seq column that row sets to its own seq holds
        that seq (a tear can keep the row and its head and lose the page that held its change). Each way this
        fails, in words; none for a whole tail. Read inside the caller's read transaction."""
        out = []
        cut = self._head_problem(top, meta)
        if cut:
            out.append(cut)
        last, unread = self._last_sets(top)
        if unread:
            out.append(unread)
        for table, columns in _SEQ_COLUMNS.items():
            for column in columns:
                v = self._max_seq(table, column, loaded)
                if v is not None and v > top:
                    out.append(f"{table}.{column} names seq {v}, past the log's last row {top}")
                elif (table, column) in last and v != top:
                    out.append(f"the log's last row, seq {top}, sets {table}.{column}, but the highest seq that "
                               f"column holds is {'none' if v is None else v}: the row's change is not in the table")
        return out

    def integrity(self) -> tuple[int, list[str]]:
        """What `engram-permissions verify` reports, read in one transaction: (the log's last seq, each problem
        in words). The hash chain from the first row, `meta.head`, and every seq column of every row."""
        self.conn.execute("BEGIN")
        try:
            top = self.seq()
            broken = self.verify()
            problems = [] if broken is None else [f"the log's hash chain breaks at seq {broken}"]
            problems += self._tail_problems(top, self.meta())
        finally:
            self.conn.execute("COMMIT")
        return top, problems

    # ---------------------------------------------------------------- writing
    def _append(self, kind: str, ref: str, actor: str, channel: str, body: Mapping, *,
                under_grant: str | None = None, proposal_id: str | None = None, at: int) -> int:
        """One log row and its projection, in one BEGIN IMMEDIATE. Returns the row's seq."""
        text = canonical_json(dict(body))
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            added = sum(1 for item in body.get("insert", ()) if item["table"] == "records")
            if added:             # P 5.4, 15: counted here, under the write lock, so two writers can't both pass
                held = self.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
                if held + added > permissions.MAX_RECORDS:
                    raise RuleError("5.4 validity rules",
                                    f"a ledger holds at most {permissions.MAX_RECORDS:,} records, revoked and "
                                    f"replaced ones included: it holds {held:,}, and this change adds {added:,}")
            self._check_open_bounds(body, at)
            last = self.conn.execute("SELECT seq, digest FROM ledger_log ORDER BY seq DESC LIMIT 1").fetchone()
            seq, prev = (last["seq"] + 1, last["digest"]) if last else (1, ZERO)
            head = self.conn.execute("SELECT value FROM meta WHERE key = 'head'").fetchone()
            # a cut tail (P 5.6), checked here for every writer, a State read first or not: a row written now would
            # take the seq of the one the log lost, or, written over a last row whose change was lost, hide the tear.
            # The cheap reads a State makes, with no table loaded.
            cut = self._tail_problems(seq - 1, {} if head is None else {"head": head[0]}, loaded={})
            if cut:
                raise LedgerUnreadable(f"{self.path}: a row written now would take seq {seq}, but {cut[0]}. {_CUT}")
            entry = {"seq": seq, "at": at, "kind": kind, "ref": ref, "actor": actor, "channel": channel,
                     "under_grant": under_grant, "proposal_id": proposal_id, "body": text}
            digest = _digest(prev, entry)
            self.conn.execute(
                "INSERT INTO ledger_log VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (seq, at, kind, ref, actor, channel, under_grant, proposal_id, text, prev, digest))
            self._project(json.loads(text), seq, at)
            self.conn.execute("INSERT INTO meta VALUES('head', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                              (f"{seq}:{digest}",))
            self.conn.execute("COMMIT")
        except BaseException as e:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            if isinstance(e, sqlite3.IntegrityError):
                raise _bad(f"the change collides with an existing row ({e})") from e
            raise
        return seq

    def _check_open_bounds(self, body: Mapping, at: int) -> None:
        """Proposals and child grants an agent can add without a yes, bounded inside the write's BEGIN IMMEDIATE as
        the records are (P 15, P37; the final review's I1): open (pending, unexpired) proposals per filer and per
        ledger, and live (not revoked, not expired) child grants per parent grant."""
        for item in body.get("insert", ()):
            row = item["row"]
            if item["table"] == "proposals":
                by = row["by_agent"]
                mine, held = self.conn.execute(
                    "SELECT COALESCE(SUM(by_agent = ?), 0), COUNT(*) FROM proposals "
                    "WHERE status = 'pending' AND expires > ?", (by, at)).fetchone()
                if mine >= permissions.MAX_OPEN_PROPOSALS_PER_AGENT:
                    raise RuleError("7.7 proposals",
                                    f"{by} holds at most {permissions.MAX_OPEN_PROPOSALS_PER_AGENT} open proposals, "
                                    f"and holds {mine}: the owner signs or declines them, or each expires "
                                    f"{PROPOSAL_DAYS} days after it was filed")
                if held >= permissions.MAX_OPEN_PROPOSALS:
                    raise RuleError("7.7 proposals",
                                    f"a ledger holds at most {permissions.MAX_OPEN_PROPOSALS:,} open proposals, "
                                    f"and holds {held:,}: the owner signs or declines them, or each expires "
                                    f"{PROPOSAL_DAYS} days after it was filed")
            elif item["table"] == "permission_grants" and row.get("parent_id") is not None:
                live = self.conn.execute(
                    "SELECT COUNT(*) FROM permission_grants WHERE parent_id = ? AND revoked_seq IS NULL "
                    "AND expires > ?", (row["parent_id"], at)).fetchone()[0]
                if live >= permissions.MAX_CHILD_GRANTS:
                    raise RuleError("7.2 grants",
                                    f"a grant has at most {permissions.MAX_CHILD_GRANTS} live child grants, and "
                                    f"{row['parent_id']} has {live}: end one, or wait for one to expire")

    _ALREADY = {"revoked_seq": "is already revoked", "retired_seq": "is already retired"}

    def _unmatched(self, table: str, where: Mapping) -> str:
        """Why an update matched no row, in words. An update that names its row by id and guards it (unrevoked,
        unretired, still pending: P 5.1, a row is changed once) finds that row already changed when another writer
        changed it after this write's checks read the ledger: the act is refused for that reason (the re-review's
        Minor 6). Anything else is the raw where clause."""
        rid = where.get("id")
        guards = [c for c in where if c in ("revoked_seq", "retired_seq", "status")]
        if rid is not None and guards:
            row = self.conn.execute(f"SELECT {', '.join(guards)} FROM {table} WHERE id IS ?", (rid,)).fetchone()
            if row is not None:
                for c in guards:
                    if row[c] == where[c]:
                        continue
                    if c == "status":
                        return f"{rid} is already {row[c]} (by another write)"
                    if table == "permission_grants":
                        return f"{rid} has already ended (by another write)"
                    return f"{rid} {self._ALREADY[c]} (by another write)"
        return f"{table} update matched no row: {where}"

    def _project(self, body: dict, seq: int, at: int) -> None:
        def fill(v):
            if v == "@seq":
                return seq
            if v == "@at":
                return at
            if isinstance(v, (dict, list)):
                return canonical_json(v)
            return v

        for key in body:
            if key not in ("insert", "update", "meta", "name", "houses"):
                raise _bad(f"unknown part of a log body: {key}")
        if "head" in body.get("meta", {}):
            raise _bad("meta.head follows the log and is never set by a log body")
        for item in body.get("insert", ()):
            table, row = item["table"], dict(item["row"])
            self._check_table(table)
            unknown = set(row) - set(_COLUMNS[table])
            missing = [c for c in _COLUMNS[table] if c not in row and c not in _NULLABLE]
            if unknown or missing:
                raise _bad(f"{table} row: unknown columns {sorted(unknown)}, missing {missing}")
            if table == "places" and isinstance(row["pseudonym_salt"], str):
                row["pseudonym_salt"] = bytes.fromhex(row["pseudonym_salt"])
            cols = list(row)
            self.conn.execute(f"INSERT INTO {table}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                              [row[c] if isinstance(row[c], bytes) else fill(row[c]) for c in cols])
        for item in body.get("update", ()):
            table, where, sets = item["table"], dict(item["where"]), dict(item["set"])
            self._check_table(table)
            if not where or not sets or (set(where) | set(sets)) - set(_COLUMNS[table]):
                raise _bad(f"{table} update: columns must be real and where/set not empty")
            clause = " AND ".join(f"{c} IS ?" for c in where)
            cur = self.conn.execute(
                f"UPDATE {table} SET {', '.join(c + '=?' for c in sets)} WHERE {clause}",
                [fill(v) for v in sets.values()] + [fill(v) for v in where.values()])
            if cur.rowcount < 1:
                raise _bad(self._unmatched(table, where))
        for k, v in body.get("meta", {}).items():
            self.conn.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                              (k, str(v)))

    @staticmethod
    def _check_table(table: str) -> None:
        if table not in _COLUMNS:
            raise _bad(f"unknown table {table!r}")

    # ---------------------------------------------------------------- acts (R3)
    def perform(self, act: Act, *, actor: str, channel: str, now: int) -> Outcome:
        """The one path for every act: authorize with the pure model, then write one log row and its projection.
        A refused act raises RuleError and writes nothing. An act that needs more yeses is filed as a proposal."""
        if self.read_only:
            raise _bad("this ledger is open read-only")
        if act.kind in ("sign", "decline"):
            return self._on_proposal(act, actor, channel, now)
        spec = _ACTS.get(act.kind)
        if spec is None:
            raise RuleError(_ACT, f"unknown act kind {act.kind!r}")
        state = self.state()
        args = spec.prepare(state, actor, dict(act.args))
        act = Act(act.kind, args)
        if spec.check is not None:
            spec.check(state, actor, args, now)
        auth = spec.authority(state, actor, act, channel, now)
        if auth.outcome == "proposal":
            return self._file(state, spec, act, actor, channel, now)
        ref, body = self._make(spec, state, actor, args, auth, now)
        body = _stamp(body, channel, None)
        seq = self._append(act.kind, ref, actor, channel, body, under_grant=auth.under_grant, at=now)
        del state                 # P 5.6: no frame holds a State while the check builds the next
        return self._outcome("done", ref, seq, act.kind, args)

    def _make(self, spec: "_Act", state: State, actor: str, args: Mapping, auth: Authority, now: int):
        """`spec.make`; an act that touches files (the gate) is also told the root of this ledger's engram home."""
        if spec.rooted:
            return spec.make(state, actor, args, auth, now, root=self.root)
        return spec.make(state, actor, args, auth, now)

    @property
    def root(self) -> Path:
        """The engram home this ledger was created or opened with: its file is `<root>/.engram/permissions.db`."""
        return self.path.parent.parent

    def _outcome(self, status: str, ref: str, seq: int, kind: str, args: Mapping = ()) -> Outcome:
        """After a registry change, or a rule written in a place's layer, the gluing reports of up to
        JOINTS_PER_CHANGE joint places (R5)."""
        if kind == "gate":
            return Outcome(status, ref, seq, lacking_029=tuple(self.gate_plan()["lacking_029"]))
        if kind in _GLUED:
            changed = {REGISTRY}
        elif kind in _RECORD_ACTS:
            layer = None
            if "record" in args:
                row = self.conn.execute("SELECT layer FROM records WHERE id = ?", (args["record"],)).fetchone()
                layer = row["layer"] if row is not None else None
            changed = {layer if layer is not None else args.get("layer")}
        else:
            return Outcome(status, ref, seq)
        state = self.state()
        joints = affected_joints(state, changed)
        return Outcome(status, ref, seq, tuple(gluing(state, j) for j in joints[:JOINTS_PER_CHANGE]),
                       tuple(joints[JOINTS_PER_CHANGE:]))

    def _file(self, state: State, spec: "_Act", act: Act, actor: str, channel: str, now: int) -> Outcome:
        pid = new_id("p-")
        body: dict = {"act": {"kind": act.kind, "args": dict(act.args)}}
        kind, for_person = _words_kind(state, act), state.meta["owner"]
        if not actor.startswith("agent:") and channel != "tool":
            # a person's act that waits for the other stewards (P 4.4): each needs a signature (R6)
            body["needs"] = _needs(act)
            kind, for_person = ("joint-place" if act.kind == "register-place" else act.kind), actor
        elif actor != for_person:
            # the owner signs it alone, so the owner must be able to make it alone (P 7.6)
            if spec.authority(state, for_person, act, "terminal", now).outcome != "do":
                raise RuleError(_ACT, f"{for_person} could not make this change alone, so there is nothing to sign")
        row = {"id": pid, "by_agent": actor, "for_person": for_person, "kind": kind, "body": body, "created": now,
               "expires": now + PROPOSAL_DAYS * 86400, "status": "pending"}
        seq = self._append("propose", pid, actor, channel, {"insert": [{"table": "proposals", "row": row}]},
                           proposal_id=pid, at=now)
        return Outcome("proposal", pid, seq)

    def _signers(self, pid: str) -> list[str]:
        return [r["actor"] for r in self.conn.execute(
            "SELECT actor FROM ledger_log WHERE kind='proposal-sign' AND proposal_id=? ORDER BY seq", (pid,))]

    def _on_proposal(self, act: Act, actor: str, channel: str, now: int) -> Outcome:
        state = self.state()
        if channel not in CHANNELS:
            raise RuleError(_ACT, f"channel must be one of {', '.join(CHANNELS)}")
        row = state.persons.get(actor)
        if not actor.startswith("person:") or row is None or row.retired_seq is not None:
            raise RuleError(_ACT, f"only a registered person can {act.kind} a proposal, not {actor}")
        pid = check_id("proposal", act.args.get("proposal"))
        p = state.proposals.get(pid)
        if p is None:
            raise RuleError(_ACT, f"{pid} is not a proposal")
        if p.status != "pending":
            raise RuleError(_ACT, f"{pid} is not pending: it is {p.status}")
        if now >= p.expires:
            raise RuleError(_ACT, f"{pid} expired on {_date(p.expires)}: a proposal lasts {PROPOSAL_DAYS} days")
        body = json.loads(p.body)
        needs = body.get("needs")
        had = {p.by_agent, *self._signers(pid)}
        if act.kind == "decline":
            if actor not in had and actor != p.for_person and not (needs and _covers(state, needs, {actor})):
                raise RuleError(_ACT, f"{actor} has no say in {pid}")
            seq = self._append("proposal-decline", pid, actor, channel, {"update": [{      # decided once (P 5.1)
                "table": "proposals", "where": {"id": pid, "status": "pending"},
                "set": {"status": "declined", "decided_seq": "@seq"}}]},
                proposal_id=pid, at=now)
            return Outcome("done", pid, seq)
        if channel == "tool":
            raise RuleError("7.6 the person's yes", "a signature needs the terminal; the tools can give no yes")
        if needs is None:
            done = self._sign_alone(state, p, body, actor, channel, now)
            del state
            return self._outcome("done", *done)
        spec_act = body["act"]
        now_covered = _covers(state, needs, had | {actor})
        if now_covered == _covers(state, needs, had):
            raise RuleError(_ACT, f"{actor} adds no signature {pid} still needs")
        if now_covered != frozenset(range(len(needs))):
            seq = self._append("proposal-sign", pid, actor, channel, {}, proposal_id=pid, at=now)
            return Outcome("proposal", pid, seq)
        spec = _ACTS[spec_act["kind"]]
        args = spec.prepare(state, p.by_agent, dict(spec_act["args"]))
        ref, mbody = self._make(spec, state, p.by_agent, args, Authority("do", "person", None), now)
        mbody = _signed(_stamp(mbody, channel, pid), pid)
        seq = self._append(spec_act["kind"], ref, actor, channel, mbody, proposal_id=pid, at=now)
        del state
        return self._outcome("done", ref, seq, spec_act["kind"], args)

    def _sign_alone(self, state: State, p, body: Mapping, actor: str, channel: str, now: int) -> tuple:
        """The owner's yes to an agent's proposal: run its Act as the owner on the terminal (R26). Everything the
        act checks, it checks again against the ledger as it is now; a refusal leaves the proposal open."""
        if actor != p.for_person:
            raise RuleError("7.6 the person's yes", f"{p.id} is signed by {p.for_person}, not by {actor}")
        if channel != "terminal":
            raise RuleError("7.6 the person's yes", "a signature needs the terminal")
        kind, spec = body["act"]["kind"], _ACTS[body["act"]["kind"]]
        args = spec.prepare(state, actor, dict(body["act"]["args"]))
        act = Act(kind, args)
        if spec.check is not None:
            spec.check(state, actor, args, now)
        auth = spec.authority(state, actor, act, "terminal", now)
        if auth.outcome != "do":
            raise RuleError(_ACT, f"{actor} cannot make this change alone")
        ref, mbody = self._make(spec, state, actor, args, auth, now)
        mbody = _signed(_stamp(mbody, "terminal", p.id), p.id)
        seq = self._append(kind, ref, actor, channel, mbody, under_grant=auth.under_grant, proposal_id=p.id, at=now)
        return ref, seq, kind, args       # the caller drops its State, then `_outcome` builds the next

    def proposals(self, *, now: int) -> list[dict]:
        """The open proposals (pending and not yet expired), oldest first. `words` come from the body by one
        template per kind (P 7.7); the agent's `reason` is kept apart and is never in them."""
        state = self.state()
        out = []
        for pid in state.proposals.open_ids(now):         # at most MAX_OPEN_PROPOSALS, each read when listed
            p = state.proposals[pid]
            body = json.loads(p.body)
            act = body["act"]
            kind = "register-place" if p.kind == "joint-place" else p.kind
            try:
                words = proposal_words(state, kind, act["args"])
            except (RuleError, KeyError, TypeError, ValueError) as e:
                words = f"(this proposal cannot be put into words now: {e})"
            out.append({"id": p.id, "by_agent": p.by_agent, "for_person": p.for_person, "kind": p.kind,
                        "act": act, "needs": body.get("needs"), "signatures": self._signers(p.id), "words": words,
                        "reason": act["args"].get("reason"), "created": p.created, "expires": p.expires})
        return out

    # ---------------------------------------------------------------- kept copies and read accessors (P 7.4)
    def record_copy(self, copy_ref: str, source_ref: str, *, now: int, also: Sequence[str] = ()) -> None:
        """The `copies` row and the source's subjects as co-subjects of the copy (`added_by` copy:<source>), in one
        transaction, before the store write. Refused past MAX_COPY_CHAIN links or MAX_SUBJECTS subjects. `also`
        names other objects the kept content matched (the `remember` guard, P25): their subjects at `now` are
        carried too, each row `added_by` copy:<that object>, while `copies` keeps the one source (the final
        review's M4)."""
        if self.read_only:
            raise _bad("this ledger is open read-only")
        rule = "7.4 kept copies"
        parse_object_ref(copy_ref)
        parse_object_ref(source_ref)
        also = [o for o in dict.fromkeys(also) if o != source_ref]
        for o in also:
            parse_object_ref(o)
            if o == copy_ref:
                raise RuleError(rule, "a memory is not a copy of itself")
        state = self.state()
        if copy_ref == source_ref:
            raise RuleError(rule, "a memory is not a copy of itself")
        if parse_object_ref(copy_ref).instance_id not in state.stores:
            # it would have no subject (P32), so its source's would never be read (Tardis's T6)
            raise RuleError(rule, f"{copy_ref} names no registered store; the person registers it first "
                                  "(engram-permissions store add)")
        if copy_ref in state.copies:
            raise RuleError(rule, f"{copy_ref} is already recorded as a copy")
        links, cur, seen = 1, source_ref, {copy_ref}
        while cur in state.copies:
            cur = state.copies[cur]
            links += 1
            if cur in seen:
                raise RuleError(rule, f"{copy_ref} would make a cycle of copies")
            seen.add(cur)
        if links > MAX_COPY_CHAIN:
            raise RuleError(rule, f"a copy chain is at most {MAX_COPY_CHAIN} links")
        own = _own_subjects(state, copy_ref)
        came_from: dict[str, str] = {}             # each carried subject and the first object it came from
        for src in (source_ref, *also):
            for s in subjects_of(state, src, now):
                if s not in own:
                    came_from.setdefault(s, src)
        carried = sorted(came_from)
        if len(own) + len(carried) > MAX_SUBJECTS:
            raise RuleError(rule, f"a copy has at most {MAX_SUBJECTS} subjects, with its source's")
        by = "copy:" + source_ref
        insert = [{"table": "copies", "row": {"object": copy_ref, "source": source_ref, "added_seq": "@seq"}}]
        insert += [{"table": "subjects", "row": {"object": copy_ref, "subject": s, "added_seq": "@seq",
                                                 "added_by": "copy:" + came_from[s], "self_claimed": 0}}
                   for s in carried]
        self._append("record-copy", copy_ref, by, "tool", {"insert": insert}, at=now)

    def note_lanes(self, phase: str, rows: Sequence[Mapping], target: str, *, store_id: str, now: int) -> None:
        """The lane notes around a re-lane (P 5.3). `rows` are the memories' `{id, lane, created_at}` read just
        before the UPDATE. `before`: a first note at each memory's `created_at` (its current lane) for a ref with
        none, then `pending` at now. `after`: the target lane. `failed`: each row's old lane. One log row."""
        if self.read_only:
            raise _bad("this ledger is open read-only")
        if phase not in ("before", "after", "failed"):
            raise _bad(f"unknown lane note phase {phase!r}")
        if target not in LANES:
            raise _bad(f"unknown lane {target!r}")
        state = self.state() if phase == "before" else None
        insert, refs = [], []
        for row in rows:
            o = f"mem:{store_id}/episode/{row['id']}"
            parse_object_ref(o)
            refs.append(o)
            if phase == "before":
                if not state.lane_notes.get(o):
                    insert.append(_ins("lane_notes", object=o, lane=row["lane"] or "personal",
                                       at=_seconds(row["created_at"]), seq="@seq"))
                insert.append(_ins("lane_notes", object=o, lane="pending", at=now, seq="@seq"))
            elif phase == "after":
                insert.append(_ins("lane_notes", object=o, lane=target, at=now, seq="@seq"))
            else:
                insert.append(_ins("lane_notes", object=o, lane=row["lane"] or "personal", at=now, seq="@seq"))
        if insert:
            self._append("lane-note-" + phase, refs[0], "store:" + store_id, "tool", {"insert": insert}, at=now)

    def note_first_lane(self, ref: str, lane: str, created_at, *, store_id: str, now: int) -> bool:
        """P 5.3: a first note for a memory that has none, dated at its `created_at`, as `share` writes it when it
        places a copy. Returns whether a note was written."""
        if self.read_only:
            raise _bad("this ledger is open read-only")
        if lane not in LANES:
            raise _bad(f"unknown lane {lane!r}")
        parse_object_ref(ref)
        if self.conn.execute("SELECT 1 FROM lane_notes WHERE object=? LIMIT 1", (ref,)).fetchone():
            return False
        self._append("lane-note-first", ref, "store:" + store_id, "tool",
                     {"insert": [_ins("lane_notes", object=ref, lane=lane, at=_seconds(created_at), seq="@seq")]},
                     at=now)
        return True

    def latest_lane_note(self, ref: str) -> str | None:
        """The lane of the newest note on ref (by `at`, then seq), or None when it has none."""
        r = self.conn.execute("SELECT lane FROM lane_notes WHERE object=? ORDER BY at DESC, seq DESC, rowid DESC LIMIT 1",
                              (ref,)).fetchone()
        return None if r is None else r["lane"]

    def store_row(self, instance_id: str) -> dict | None:
        r = self.conn.execute("SELECT instance_id, name, owner, place, imprint_of, created_seq FROM stores "
                              "WHERE instance_id=?", (instance_id,)).fetchone()
        return None if r is None else dict(r)

    def cosubjects(self, ref: str, at: int | None = None) -> frozenset[str]:
        """The co-subjects of ref: `subjects_of` (its own and, through `copies`, its sources' up to MAX_COPY_CHAIN
        links, so a source's later subjects too; P 7.4, 19), less its default subject, its store's owner. `at`
        None reads every subject row not removed; a time reads those in force then. The imprints plan's
        `cosubjects(m)` (the final review's M6)."""
        state = self.state()
        out = set(subjects_of(state, ref, at))
        store = state.stores.get(parse_object_ref(ref).instance_id)
        if store is not None and store.imprint_of is None:
            out.discard(store.owner)
        return frozenset(out)

    # ---------------------------------------------------------------- the gate's plan and PlaceRules (P 9.4, 12.3)
    def gate_plan(self) -> dict:
        """What a `gate` act would use if applied now: the published house, every house on disk, and those among
        them that lack migration 029 (R27). The act computes the same at the yes, never from a caller."""
        found = houses(self.root)
        return {"published_house": self.root / PUBLISHED_HOUSE, "houses": found,
                "lacking_029": [h for h in found if _lacks_029(h)]}

    def place_rules(self, place: str, *, now: int) -> dict:
        """P 9.4: the `PlaceRules` artifact for a place at the ledger's present seq. A home is not published. Its
        records are those in force at `now`: not revoked and not past their `valid_until` (Tardis's T14); one that
        starts later is published, so a reader sees a dated deny before it starts."""
        check_id("place", place)
        if place == "place:home" or place.startswith("place:home/"):
            raise RuleError("9.4 how a place publishes its rules",
                            "home places are not published: their rules are readable only by the person and "
                            "their agents")
        state = self.state()
        if place not in state.places:
            raise RuleError("9.4 how a place publishes its rules", f"{place} is not a registered place")
        seq = state.seq
        last = self.conn.execute("SELECT digest FROM ledger_log WHERE seq=?", (seq,)).fetchone()
        records = []
        for r in sorted(state.records.values(), key=lambda r: (r.created_seq, r.id)):
            if r.layer == place and r.revoked_seq is None and (r.valid_until is None or now < r.valid_until):
                row = r._asdict()
                row["selector"] = json.loads(selector_json(r.selector))
                records.append(row)
        ledger_id = state.meta["ledger_id"]
        art = {
            "protocolVersion": "0.1", "kind": "PlaceRules",
            "id": f"urn:engram:{ledger_id}:place-rules:{place}:{seq}",
            "issuedAt": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "issuer": f"urn:engram:{ledger_id}",
            "payloadMediaType": "application/vnd.engram.place-rules+json",
            "payload": {
                "place": place,
                "parents": sorted(r.parent for r in state.place_parents.get(place, ())),
                "stewards": sorted(r.person for r in state.place_stewards.get(place, ()) if r.removed_seq is None),
                "retired": state.places[place].retired_seq is not None,
                "ledgerSeq": seq, "logDigest": last["digest"] if last else ZERO, "records": records}}
        art["digest"] = artifact_digest(art)
        return art

    # ---------------------------------------------------------------- rebuild
    def rebuild(self, dest: Path) -> Path:
        """Replay the log into a fresh ledger whose engram home is `dest`; the same tables. Returns `dest`.

        The old chain must verify first, each replayed digest must equal the stored one, and the new file is built
        beside its final name and renamed into place only when the whole replay succeeded (P 5.6)."""
        final = ledger_path(dest)
        if final.exists():
            raise FileExistsError(str(final))
        broken = self.verify()
        if broken is not None:
            raise _bad(f"the log does not verify from seq {broken}; it cannot be rebuilt")
        made_dir = not final.parent.exists()
        tmp = final.with_name(final.name + ".rebuilding")
        for stale in (tmp, tmp.with_name(tmp.name + "-journal")):
            stale.unlink(missing_ok=True)
        new = None
        try:
            new = Ledger._blank(dest, self.meta()["ledger_id"], path=tmp)
            for r in self.conn.execute("SELECT * FROM ledger_log ORDER BY seq"):
                got = new._append(r["kind"], r["ref"], r["actor"], r["channel"], json.loads(r["body"]),
                                  under_grant=r["under_grant"], proposal_id=r["proposal_id"], at=r["at"])
                again = new.conn.execute("SELECT digest FROM ledger_log WHERE seq=?", (got,)).fetchone()[0]
                if got != r["seq"] or again != r["digest"]:
                    raise _bad(f"the replay does not match the log at seq {r['seq']}; it cannot be rebuilt")
            new.close()
            new = None
            os.replace(tmp, final)
        except BaseException:
            if new is not None:
                new.close()
            for stale in (tmp, tmp.with_name(tmp.name + "-journal")):
                stale.unlink(missing_ok=True)
            if made_dir:
                for d in (final.parent, Path(dest)):
                    try:
                        d.rmdir()
                    except OSError:
                        pass
            raise
        return Path(dest)


# ---------------------------------------------------------------- the registry acts (P 4.4, 7.4)

_ACT = "7.1 who may set what"
_REG = "4.4 who registers places and people"


@dataclass(frozen=True)
class _Act:
    prepare: Callable      # (state, actor, args) -> args: shape, defaults and state rules; raises RuleError
    make: Callable         # (state, actor, args, authority, now) -> (ref, log body)
    authority: Callable = None   # (state, actor, act, channel, now) -> Authority; default: the pure model's
    check: Callable = None       # (state, actor, args, now) -> None: the write-time rules (P 5.4, 7.1, 7.2); raises
    rooted: bool = False         # make also takes root=<engram home>: the act reads or writes files on disk


def _seconds(created_at) -> int:
    """An episode's `created_at` (ISO text, naive meaning UTC, or already seconds) as UTC seconds."""
    if isinstance(created_at, int) and not isinstance(created_at, bool):
        return created_at
    when = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return int(when.timestamp())


def _text(args: Mapping, key: str) -> str:
    v = args.get(key)
    if not isinstance(v, str) or not v:
        raise RuleError(_ACT, f"the act needs {key}")
    return v


def _texts(args: Mapping, key: str, *, at_least: int = 0) -> list[str]:
    v = args.get(key)
    if v is None:
        v = []
    if isinstance(v, (str, bytes)) or not isinstance(v, (list, tuple)) or not all(isinstance(x, str) for x in v):
        raise RuleError(_ACT, f"{key} must be a list of strings")
    out = list(dict.fromkeys(v))
    if len(out) < at_least:
        raise RuleError(_ACT, f"the act needs at least {at_least} in {key}")
    return out


def _live_person(state: State, person: str, what: str) -> str:
    check_id("person", person)
    row = state.persons.get(person)
    if row is None or row.retired_seq is not None:
        raise RuleError(_REG, f"{what} {person} is not a registered, unretired person")
    return person


def _live_agent(state: State, agent: str) -> str:
    check_id("agent", agent)
    row = state.agents.get(agent)
    if row is None or row.retired_seq is not None:
        raise RuleError(_REG, f"{agent} is not a registered, unretired agent")
    return agent


def _ins(table: str, **row) -> dict:
    return {"table": table, "row": row}


def _upd(table: str, where: Mapping, **sets) -> dict:
    return {"table": table, "where": dict(where), "set": sets}


def _salt() -> str:
    return os.urandom(16).hex()


# -- people

def _prep_register_person(state, actor, args):
    person = check_id("person", _text(args, "person"))
    if person in state.persons or home_of(person) in state.places:
        raise RuleError(_REG, f"{person} is already registered")
    if len(state.places) >= MAX_PLACES:
        raise RuleError(_REG, f"at most {MAX_PLACES:,} places per ledger")
    return {"person": person}


def _make_register_person(state, actor, args, auth, now):
    person, home = args["person"], home_of(args["person"])
    return person, {"insert": [
        _ins("persons", id=person, home=home, is_admin=0, created_seq="@seq"),
        _ins("places", id=home, is_root=1, created_seq="@seq", pseudonym_salt=_salt()),
        _ins("place_stewards", place=home, person=person, added_seq="@seq")]}


def _prep_retire_person(state, actor, args):
    return {"person": _live_person(state, _text(args, "person"), "")}


def _make_retire_person(state, actor, args, auth, now):
    person = args["person"]                     # a second retirement matches no row (P 5.1)
    return person, {"update": [_upd("persons", {"id": person, "retired_seq": None}, retired_seq="@seq"),
                               _upd("places", {"id": state.persons[person].home, "retired_seq": None},
                                    retired_seq="@seq")]}


# -- places

def _prep_register_place(state, actor, args):
    place = check_id("place", _text(args, "place"))
    parents = check_new_place(state, place, _texts(args, "parents"))
    stewards = _texts(args, "stewards")
    if "stewards" not in args and actor.startswith("person:"):
        stewards = [actor]                       # the registering steward, unless the act names others
    if not stewards:
        raise RuleError(_REG, "a place keeps at least one steward: the act needs stewards")
    for s in stewards:
        _live_person(state, s, "steward")
    out = {"place": place, "parents": list(parents), "stewards": stewards}
    name = args.get("name")
    if name is not None:
        if not isinstance(name, str) or not name.strip() or len(name) > 255:
            raise RuleError(_REG, "a place's name is a non-empty text of at most 255 characters")
        if not name.strip().isprintable():       # every later yes that names the place prints it (final review M5)
            raise RuleError(_REG, "a place's name is one line of text that prints: no control, format or "
                                  "line-break character")
        out["name"] = name.strip()
    return out


def _make_register_place(state, actor, args, auth, now):
    place, parents = args["place"], args["parents"]
    body = {"insert": [_ins("places", id=place, is_root=int(not parents), created_seq="@seq",
                            pseudonym_salt=_salt())]}
    body["insert"] += [_ins("place_parents", place=place, parent=q, added_seq="@seq") for q in parents]
    body["insert"] += [_ins("place_stewards", place=place, person=s, added_seq="@seq") for s in args["stewards"]]
    if "name" in args:
        body["name"] = args["name"]
    return place, body


def _prep_add_parent(state, actor, args):
    place, parent = _text(args, "place"), _text(args, "parent")
    check_new_parent(state, place, parent)
    return {"place": place, "parent": parent}


def _make_add_parent(state, actor, args, auth, now):
    return args["place"], {"insert": [_ins("place_parents", place=args["place"], parent=args["parent"],
                                           added_seq="@seq")]}


def _steward_args(state, args, *, adding):
    place, person = check_id("place", _text(args, "place")), check_id("person", _text(args, "person"))
    if person_of_home(place) is not None:
        raise RuleError(_REG, "a home's only steward is its person, never changed")
    if place not in state.places:
        raise RuleError(_REG, f"{place} is not a registered place")
    if adding:
        _live(state, place, "place")
        _live_person(state, person, "steward")
        if _is_steward(state, place, person):
            raise RuleError(_REG, f"{person} is already a steward of {place}")
    elif not _is_steward(state, place, person):
        raise RuleError(_REG, f"{person} is not a steward of {place}")
    return {"place": place, "person": person}


def _prep_add_steward(state, actor, args):
    return _steward_args(state, args, adding=True)


def _prep_remove_steward(state, actor, args):
    return _steward_args(state, args, adding=False)


def _make_add_steward(state, actor, args, auth, now):
    return args["place"], {"insert": [_ins("place_stewards", place=args["place"], person=args["person"],
                                           added_seq="@seq")]}


def _make_remove_steward(state, actor, args, auth, now):
    return args["place"], {"update": [_upd("place_stewards", {"place": args["place"], "person": args["person"],
                                                              "removed_seq": None}, removed_seq="@seq")]}


def _prep_retire_place(state, actor, args):
    place = check_id("place", _text(args, "place"))
    if place not in state.places:
        raise RuleError(_REG, f"{place} is not a registered place")
    if person_of_home(place) is not None:
        raise RuleError(_REG, f"{place} is a home: retire its person instead")
    if state.places[place].retired_seq is not None:
        raise RuleError(_REG, f"{place} is already retired")
    return {"place": place}


def _make_retire_place(state, actor, args, auth, now):
    return args["place"], {"update": [_upd("places", {"id": args["place"], "retired_seq": None},  # once (P 5.1)
                                           retired_seq="@seq")]}


# -- agents

def _prep_register_agent(state, actor, args):
    agent, place = check_id("agent", _text(args, "agent")), check_id("place", _text(args, "acts_for"))
    if agent in state.agents:
        raise RuleError(_REG, f"{agent} is already registered")
    _live(state, place, "the place it acts for,")
    return {"agent": agent, "acts_for": place}


def _make_register_agent(state, actor, args, auth, now):
    return args["agent"], {"insert": [_ins("agents", id=args["agent"], acts_for=args["acts_for"],
                                           created_seq="@seq")]}


def _prep_put_agent(state, actor, args):
    agent, place = _live_agent(state, _text(args, "agent")), check_id("place", _text(args, "place"))
    _live(state, place, "the place")
    where = [r.place for r in state.agent_places.get(agent, ()) if r.removed_seq is None]
    if where:
        raise RuleError("P31", f"{agent} is in {where[0]}: an agent is in one place until it is removed from it")
    return {"agent": agent, "place": place}


def _make_put_agent(state, actor, args, auth, now):
    return args["agent"], {"insert": [_ins("agent_places", agent=args["agent"], place=args["place"],
                                           added_seq="@seq")]}


def _prep_remove_agent(state, actor, args):
    agent, place = _live_agent(state, _text(args, "agent")), check_id("place", _text(args, "place"))
    if not any(r.place == place and r.removed_seq is None for r in state.agent_places.get(agent, ())):
        raise RuleError(_REG, f"{agent} is not in {place}")
    return {"agent": agent, "place": place}


def _make_remove_agent(state, actor, args, auth, now):
    return args["agent"], {"update": [_upd("agent_places", {"agent": args["agent"], "place": args["place"],
                                                            "removed_seq": None}, removed_seq="@seq")]}


# -- stores, groups, collections

def _prep_register_store(state, actor, args):
    iid = _text(args, "instance_id")
    parse_copy_ref("store:" + iid)
    if iid in state.stores:
        raise RuleError(_REG, f"store {iid} is already registered")
    place = check_id("place", _text(args, "place"))
    _live(state, place, "the store's place")
    imprint_of = args.get("imprint_of")
    if imprint_of is not None:
        parse_copy_ref("store:" + imprint_of)
    name = args.get("name") or iid
    if not isinstance(name, str):
        raise RuleError(_REG, "a store's name is text")
    return {"instance_id": iid, "name": name, "owner": _live_person(state, _text(args, "owner"), "owner"),
            "place": place, "imprint_of": imprint_of}


def _make_register_store(state, actor, args, auth, now):
    return args["instance_id"], {"insert": [_ins("stores", created_seq="@seq", **args)]}


def _prep_group(state, actor, args):
    gid = check_id("group", _text(args, "group"))
    row = state.groups.get(gid)
    owner = row.owner if row is not None else args.get("owner") or (actor if actor.startswith("person:") else None)
    if owner is None:
        raise RuleError(_ACT, "the act needs owner")
    members = [_live_agent(state, m) for m in _texts(args, "members")]
    held = {r.agent for r in state.group_members.get(gid, ()) if r.removed_seq is None}
    if row is not None and held == set(members):
        raise RuleError(_ACT, f"{gid} already has these members")
    return {"group": gid, "owner": _live_person(state, owner, "owner"), "members": members}


def _make_group(state, actor, args, auth, now):
    gid = args["group"]
    held = {r.agent for r in state.group_members.get(gid, ()) if r.removed_seq is None}
    want = set(args["members"])
    body: dict = {"insert": [], "update": []}
    if gid not in state.groups:
        body["insert"].append(_ins("groups", id=gid, owner=args["owner"], created_seq="@seq"))
    body["insert"] += [_ins("group_members", group_id=gid, agent=a, added_seq="@seq") for a in sorted(want - held)]
    body["update"] += [_upd("group_members", {"group_id": gid, "agent": a, "removed_seq": None}, removed_seq="@seq")
                       for a in sorted(held - want)]
    return gid, {k: v for k, v in body.items() if v}


def _prep_make_collection(state, actor, args):
    cid = check_id("collection", _text(args, "collection"))
    if cid in state.collections:
        raise RuleError(_ACT, f"{cid} already exists")
    return {"collection": cid, "owner": _live_person(state, "person:" + cid.split(":", 1)[1].split("/")[0],
                                                     "the collection's owner")}


def _make_make_collection(state, actor, args, auth, now):
    return args["collection"], {"insert": [_ins("collections", id=args["collection"], owner=args["owner"],
                                                created_seq="@seq")]}


def _members(state, cid):
    return {r.object for r in state.collection_members.get(cid, ()) if r.removed_seq is None}


def _bound_objects(objects: list) -> None:
    if len(objects) > permissions.MAX_ACT_OBJECTS:
        raise RuleError(_ACT, f"one act names at most {permissions.MAX_ACT_OBJECTS:,} objects, not "
                              f"{len(objects):,} (P 15); the command line splits a larger set into acts")


def _prep_collect(state, actor, args):
    cid = _text(args, "collection")
    if cid not in state.collections:
        raise RuleError(_ACT, f"{cid} is not a collection")
    objects = _texts(args, "refs" if "refs" in args else "objects", at_least=1)
    _bound_objects(objects)
    for o in objects:
        parse_object_ref(o)
    held = _members(state, cid)
    new = [o for o in objects if o not in held]
    if not new:
        raise RuleError(_ACT, f"every one is already in {cid}")
    check_new_members(state, cid, len(new))
    given = args.get("lanes") or {}
    if isinstance(given, (list, tuple)):
        if len(given) != len(objects):
            raise RuleError(_ACT, "lanes must have one entry for each ref")
        given = dict(zip(objects, given))
    lanes = {}
    for o in objects:
        entry = given.get(o)
        if entry is not None:
            if (not isinstance(entry, Mapping) or entry.get("lane") not in LANES
                    or not isinstance(entry.get("created_at"), int) or isinstance(entry.get("created_at"), bool)):
                raise RuleError(_ACT, f"the lane of {o} is {{lane: personal or work, created_at: seconds}} or null")
            entry = {"lane": entry["lane"], "created_at": entry["created_at"]}
        lanes[o] = entry
    out = {"collection": cid, "objects": objects, "lanes": lanes}
    if args.get("grant") is not None:
        out["grant"] = args["grant"]
    return out


def _make_collect(state, actor, args, auth, now):
    cid = args["collection"]
    held = _members(state, cid)
    insert = []
    for o in args["objects"]:
        if o in held:
            continue
        insert.append(_ins("collection_members", collection=cid, object=o, backing=auth.backing,
                           added_seq="@seq", added_by=actor))
        entry = args["lanes"].get(o)
        if entry is not None and not state.lane_notes.get(o):          # P 5.3: a first note, only for a memory with none
            insert.append(_ins("lane_notes", object=o, lane=entry["lane"], at=entry["created_at"], seq="@seq"))
    return cid, {"insert": insert}


def _prep_uncollect(state, actor, args):
    cid = _text(args, "collection")
    if cid not in state.collections:
        raise RuleError(_ACT, f"{cid} is not a collection")
    objects = _texts(args, "refs" if "refs" in args else "objects", at_least=1)
    _bound_objects(objects)
    held = _members(state, cid)
    for o in objects:
        if o not in held:
            raise RuleError(_ACT, f"{o} is not in {cid}")
    out = {"collection": cid, "objects": objects}
    if args.get("grant") is not None:
        out["grant"] = args["grant"]
    return out


def _make_uncollect(state, actor, args, auth, now):
    cid = args["collection"]
    return cid, {"update": [_upd("collection_members", {"collection": cid, "object": o, "removed_seq": None},
                                 removed_seq="@seq", removed_by=actor) for o in args["objects"]]}


# -- subjects

def _prep_add_subject(state, actor, args):
    obj, subject = _text(args, "object"), check_id("person", _text(args, "subject"))
    parse_object_ref(obj)
    if subject in _own_subjects(state, obj):
        raise RuleError(_ACT, f"{subject} is already a subject of {obj}")
    check_new_subject(state, obj, subject)
    return {"object": obj, "subject": subject}


def _make_add_subject(state, actor, args, auth, now):
    obj, subject = args["object"], args["subject"]
    return obj, {"insert": [_ins("subjects", object=obj, subject=subject, added_seq="@seq", added_by=actor,
                                 self_claimed=int(actor == subject))]}


def _prep_remove_subject(state, actor, args):
    return {"object": _text(args, "object"), "subject": _text(args, "subject")}


def _make_remove_subject(state, actor, args, auth, now):
    return args["object"], {"update": [_upd("subjects", {"object": args["object"], "subject": args["subject"],
                                                         "removed_seq": None}, removed_seq="@seq",
                                            removed_by=actor)]}


# -- authority for the acts the pure model has no row for

def _pure(state, actor, act, channel, now) -> Authority:
    return authorize(state, actor, act, channel=channel, at=now)


def _local(rule):
    """A narrowing act with its own rule: refuse unless rule(state, actor, args) says so."""
    def authority(state, actor, act, channel, now):
        authorize_actor = state.agents.get(actor) if actor.startswith("agent:") else state.persons.get(actor)
        if channel not in CHANNELS:
            raise RuleError(_ACT, f"channel must be one of {', '.join(CHANNELS)}")
        if authorize_actor is None or authorize_actor.retired_seq is not None:
            raise RuleError(_ACT, f"{actor} is not a registered, unretired {'agent' if actor.startswith('agent:') else 'person'}")
        rule(state, actor, act.args)
        return Authority("do", "person", None)
    return authority


def check_retire_person(state, person: str) -> None:
    """Retiring the ledger owner, or its last unretired admin, would leave nobody who can write the ledger again:
    every later act, a revoke or `gate off` included, would be refused (Tardis's T10). Refused, saying so."""
    if person == state.meta.get("owner"):
        raise RuleError(_ACT, f"{person} owns this ledger and is never retired: every act after it, a revoke or "
                              "`gate off` included, would be refused, and nothing could write the ledger again")
    admins = [p for p, row in state.persons.items() if row.is_admin and row.retired_seq is None]
    if admins == [person]:
        raise RuleError(_ACT, f"{person} is this ledger's last admin and is never retired: nobody could retire "
                              "anyone after it")


def _may_retire_person(state, actor, args):
    if actor.startswith("agent:") or not (actor == args["person"] or state.persons[actor].is_admin):
        raise RuleError(_ACT, "a person is retired by themself or by a ledger admin")
    check_retire_person(state, args["person"])


def _may_retire_place(state, actor, args):
    if actor.startswith("agent:") or not _is_steward(state, args["place"], actor):
        raise RuleError(_ACT, f"{actor} is not a steward of {args['place']}")


def _may_make_collection(state, actor, args):
    owner = args["owner"]
    if actor != owner and not (actor.startswith("agent:") and _acts_for_person(state, actor, owner)):
        raise RuleError(_ACT, f"only {owner}, or an agent acting for them, makes their collection")


# -- records and grants (P 5.4, 7.1 to 7.3)

_RECORD_ACTS = frozenset({"allow", "deny", "revoke", "shorten", "narrow"})
_RECORD_COLUMNS = _COLUMNS["records"]


def _stamp(body: Mapping, channel: str, proposal_id: str | None) -> dict:
    """The channel and the proposal a record row was written through. `make` leaves both to its caller."""
    out = dict(body)
    out["insert"] = [{"table": i["table"], "row": {**i["row"], "channel": channel, "proposal_id": proposal_id}}
                     if i["table"] == "records" else i for i in body.get("insert", ())]
    return {k: v for k, v in out.items() if v != []}


def _signed(body: Mapping, pid: str) -> dict:
    """`body` and the proposal marked signed. A proposal another writer decided first matches no row, so its act
    is not run twice (P 5.1)."""
    return {**body, "update": [*body.get("update", ()), _upd("proposals", {"id": pid, "status": "pending"},
                                                             status="signed", decided_seq="@seq")]}


# a record edit names its kind by the record's effect: P 7.1's rows for an allow and for a deny
_EDIT_KIND = {("revoke", "allow"): "withdraw", ("shorten", "allow"): "shorten", ("narrow", "allow"): "narrow",
              ("revoke", "deny"): "revoke-deny", ("shorten", "deny"): "shorten-deny", ("narrow", "deny"): "narrow-deny"}


def _words_kind(state: State, act: Act) -> str:
    """The kind of a proposal: the act's, except that a deny's revoke, shorten and narrow have their own templates."""
    rec = state.records.get(act.args.get("record")) if act.kind in ("revoke", "shorten", "narrow") else None
    return _EDIT_KIND[(act.kind, rec.effect)] if rec is not None else act.kind


def _whole(args: Mapping, key: str, *, null_ok: bool = False):
    v = args.get(key)
    if v is None and null_ok and key in args:
        return None
    if not isinstance(v, int) or isinstance(v, bool):
        raise RuleError(_ACT, f"{key} must be whole seconds{' or null' if null_ok else ''}")
    return v


def _reason(args: Mapping) -> str:
    r = args.get("reason", "")
    if not isinstance(r, str) or "\n" in r or "\r" in r or len(r) > REASON_CHARS:
        raise RuleError(_ACT, f"a reason is one line of at most {REASON_CHARS} characters")
    return r


def _selector_arg(args: Mapping, key: str = "selector") -> str:
    v = args.get(key)
    if v is None:
        raise RuleError(_ACT, f"the act needs {key}")
    return selector_json(v if isinstance(v, Selector) else parse_selector(v))


def _record_of(state: State, args: Mapping) -> Record:
    rec = state.records.get(_text(args, "record"))
    if rec is None:
        raise RuleError(_ACT, f"{args['record']} is not a record")
    return rec


def _grant_arg(out: dict, args: Mapping) -> dict:
    if args.get("grant") is not None:
        out["grant"] = args["grant"]
    return out


def _prep_record(effect: str):
    def prepare(state, actor, args):
        layer = _text(args, "layer")
        if layer.startswith("agent:"):
            check_id("agent", layer)
            if effect != "deny":
                raise RuleError(_ACT, "a restriction layer holds only denies")
        else:
            check_id("place", layer)
        return _grant_arg({"layer": layer, "selector": _selector_arg(args), "valid_from": _whole(args, "valid_from"),
                           "valid_until": _whole(args, "valid_until", null_ok=True), "reason": _reason(args)}, args)
    return prepare


def _draft(state: State, **fields) -> Record:
    base = dict(id="r-" + "0" * 32, anchor=fields.get("valid_from"), backing="person", set_by="", channel="tool",
                under_grant=None, proposal_id=None, replaces=None, reason="", created=0, created_seq=state.seq + 1,
                revoked=None, revoked_by=None, revoke_reason=None, revoked_seq=None)
    base.update(fields)
    base["selector"] = parse_selector(base["selector"]) if isinstance(base["selector"], str) else base["selector"]
    return Record(**base)


def _check_new_record(effect: str):
    def check(state, actor, args, now):
        check_record(state, _draft(state, layer=args["layer"], effect=effect, selector=args["selector"],
                                   valid_from=args["valid_from"], valid_until=args["valid_until"], created=now))
    return check


def _make_new_record(effect: str):
    def make(state, actor, args, auth, now):
        rid = new_id("r-")
        return rid, {"insert": [_ins(
            "records", id=rid, layer=args["layer"], effect=effect, selector=args["selector"],
            valid_from=args["valid_from"], valid_until=args["valid_until"], anchor=now, backing=auth.backing,
            set_by=actor, under_grant=auth.under_grant, replaces=None, reason=args["reason"], created=now,
            created_seq="@seq")]}
    return make


def _edit_authority(op: str):
    def authority(state, actor, act, channel, now):
        rec = _record_of(state, act.args)
        return authorize(state, actor, Act(_EDIT_KIND[(op, rec.effect)], act.args), channel=channel, at=now)
    return authority


def _prep_revoke(state, actor, args):
    return _grant_arg({"record": _record_of(state, args).id, "reason": _reason(args)}, args)


def _make_revoke(state, actor, args, auth, now):
    return args["record"], {"update": [_upd(            # a second revocation matches no row (P 5.1)
        "records", {"id": args["record"], "revoked_seq": None}, revoked="@at", revoked_by=actor,
        revoke_reason=args["reason"], revoked_seq="@seq")]}


def _prep_shorten(state, actor, args):
    out = {"record": _record_of(state, args).id, "valid_until": _whole(args, "valid_until", null_ok=True),
           "reason": _reason(args)}
    if "valid_until" not in args:
        raise RuleError(_ACT, "the act needs valid_until")
    return _grant_arg(out, args)


def _prep_narrow(state, actor, args):
    out = {"record": _record_of(state, args).id, "selector": _selector_arg(args), "reason": _reason(args)}
    if "valid_until" in args:
        out["valid_until"] = _whole(args, "valid_until", null_ok=True)
    return _grant_arg(out, args)


def _replacement(state: State, args: Mapping, now: int, rid: str = "r-" + "0" * 32) -> tuple[Record, Record]:
    """(old, new): the record and the one that narrows it. The pure model's `_replacement` rules (P 7.1)."""
    old = _record_of(state, args)
    new = old._replace(id=rid, replaces=old.id, created=now, created_seq=state.seq + 1, revoked=None,
                       revoked_by=None, revoke_reason=None, revoked_seq=None, proposal_id=None,
                       reason=args["reason"])
    if "selector" in args:
        new = new._replace(selector=parse_selector(args["selector"]))
    if "valid_until" in args:
        new = new._replace(valid_until=args["valid_until"])
    return old, new


def _check_replacement(state, actor, args, now):
    old, new = _replacement(state, args, now)
    check_record(state, new)
    links, cur = 1, old
    while cur is not None:
        links += 1
        cur = state.records.get(cur.replaces) if cur.replaces else None
    if links > MAX_REPLACES:
        raise RuleError("5.1 fields", f"a chain of replacements is at most {MAX_REPLACES} long")


def _make_replacement(state, actor, args, auth, now):
    """R is revoked and R' written, with `replaces` R, R's anchor and R's backing, in one transaction (P 7.3)."""
    rid = new_id("r-")
    old, new = _replacement(state, args, now, rid)
    return rid, {
        "insert": [_ins("records", id=rid, layer=old.layer, effect=old.effect, selector=selector_json(new.selector),
                        valid_from=old.valid_from, valid_until=new.valid_until, anchor=old.anchor,
                        backing=auth.backing, set_by=actor, under_grant=auth.under_grant, replaces=old.id,
                        reason=args["reason"], created=now, created_seq="@seq")],
        "update": [_upd("records", {"id": old.id, "revoked_seq": None}, revoked="@at", revoked_by=actor,
                        revoke_reason=f"replaced by {rid}", revoked_seq="@seq")]}


# -- grants

def _prep_grant(state, actor, args):
    parent = args.get("parent")
    row = None
    if parent is not None:
        row = state.grants.get(check_id("grant", parent))
        if row is None:
            raise RuleError("7.2 grants", f"{parent} is not a grant")
    layer = args.get("layer") or (row.layer if row is not None else None)
    if not isinstance(layer, str) or not layer:
        raise RuleError(_ACT, "the act needs layer")
    ops = _texts(args, "ops", at_least=1)
    if not set(ops) <= set(GRANT_OPS):
        raise RuleError("7.2 grants", f"ops must be a non-empty subset of {', '.join(GRANT_OPS)}")
    out = {"layer": check_id("place", layer), "grantee": check_id("agent", _text(args, "grantee")),
           "ops": sorted(ops), "envelope": _selector_arg(args, "envelope"), "max_days": _whole(args, "max_days"),
           "depth": _whole({"depth": args.get("depth", 0)}, "depth"),
           "hours": _whole({"hours": args.get("hours", 24)}, "hours")}
    if parent is not None:
        out["parent"] = parent
    return out


def _grant_draft(state: State, actor: str, args: Mapping, now: int, gid: str = "g-" + "0" * 32) -> Grant:
    """The Grant these arguments make if `actor` signs: a root grant is issued by a person (the ledger owner,
    when an agent is only asking), a child by the holder of its parent."""
    parent = args.get("parent")
    issuer = actor if parent is not None or not actor.startswith("agent:") else state.meta["owner"]
    return Grant(id=gid, issuer=issuer, grantee=args["grantee"], layer=args["layer"], parent_id=parent,
                 ops=frozenset(args["ops"]), envelope=parse_selector(args["envelope"]), max_days=args["max_days"],
                 depth=args["depth"], expires=now + args["hours"] * 3600, created=now, created_seq=state.seq + 1)


def _check_grant(state, actor, args, now):
    g = _grant_draft(state, actor, args, now)
    if g.parent_id is None:
        check_root_grant(state, g)
    else:
        check_child_grant(state, grant_chain(state, g.parent_id)[-1], g)


def _make_grant(state, actor, args, auth, now):
    gid = new_id("g-")
    g = _grant_draft(state, actor, args, now, gid)
    return gid, {"insert": [_ins(
        "permission_grants", id=gid, issuer=g.issuer, grantee=g.grantee, layer=g.layer, parent_id=g.parent_id,
        ops=sorted(g.ops), envelope=args["envelope"], max_days=g.max_days, depth=g.depth, expires=g.expires,
        created=now, created_seq="@seq")]}


def _prep_end_grant(state, actor, args):
    gid = check_id("grant", _text(args, "grant"))
    row = state.grants.get(gid)
    if row is None:
        raise RuleError("7.2 grants", f"{gid} is not a grant")
    if row.revoked_seq is not None:
        raise RuleError("7.2 grants", f"{gid} is already revoked: a revoked grant is never valid again")
    return {"grant": gid, "reason": _reason(args)}


def _make_end_grant(state, actor, args, auth, now):
    return args["grant"], {"update": [_upd(             # a second end matches no row (P 5.1)
        "permission_grants", {"id": args["grant"], "revoked_seq": None}, revoked="@at", revoked_by=actor,
        revoke_reason=args["reason"], revoked_seq="@seq")]}


# ---------------------------------------------------------------- the gate and the houses (P 12.3, R17, R26, R27, R32)

_GATE = "12.3 the gate"
GATE_MODES = ("off", "shadow", "enforce")
PUBLISHED_HOUSE = Path(".engram") / "instances" / "lighthouse" / "graph.db"


@dataclass(frozen=True)
class Gate:
    """The effective gate: `off`, `shadow`, `enforce` or `closed`. `cause` says why when it is `closed`."""
    mode: str
    cause: str | None = None


def houses(engram_home: Path) -> list[Path]:
    """Every engram store under the home: `.engram/graph.db` and each `.engram/instances/<name>/graph.db` that
    exists, sorted."""
    base = Path(engram_home) / ".engram"
    found = [base / "graph.db"] if (base / "graph.db").is_file() else []
    if (base / "instances").is_dir():
        found += [d / "graph.db" for d in (base / "instances").iterdir() if (d / "graph.db").is_file()]
    return sorted(found)


def _house_name(db_path: Path) -> str:
    return "default" if db_path.parent.name == ".engram" else db_path.parent.name


def _house_id(db_path: Path) -> str | None:
    """The `permissions_ledger_id` a house carries, read with `mode=ro`. A store with no `meta` table carries none;
    any other failure raises sqlite3.Error."""
    con = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True, timeout=BUSY_MS / 1000)
    try:
        row = con.execute("SELECT value FROM meta WHERE key='permissions_ledger_id'").fetchone()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return None
        raise
    finally:
        con.close()
    return row[0] if row and row[0] else None


def _lacks_029(db_path: Path) -> bool:
    """R27: `shared_memories` lacks `source_instance_id` or `record_id`, or there is no `shared_memories_changes`."""
    try:
        con = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True, timeout=BUSY_MS / 1000)
        try:
            columns = {r[1] for r in con.execute("PRAGMA table_info(shared_memories)")}
            changes = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shared_memories_changes'"
                                  ).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return True
    return not {"source_instance_id", "record_id"} <= columns or changes is None


def _closed(cause: str) -> Gate:
    return Gate("closed", cause)


def effective_gate(engram_home: Path, served: Sequence[Path], *, busy_ms: int = BUSY_MS) -> Gate:
    """P 12.3, rules 1 to 3, for a reader serving `served` (a path that is not a file is no house and is left out,
    R32). Reads at most GATE_HOUSES houses' `meta` to decide `off`, and is `closed` past that. The ledger is opened
    read-only with `busy_ms` as its busy timeout."""
    root = Path(engram_home)
    served = [Path(p) for p in dict.fromkeys(served) if Path(p).is_file()]
    if not ledger_path(root).is_file():
        every = sorted(set(houses(root)) | set(served))
        if len(every) > GATE_HOUSES:
            return _closed(f"no ledger and more than {GATE_HOUSES} houses, so it cannot be told whether one "
                           "carries a ledger id")
        for house in every:
            try:
                mark = _house_id(house)
            except sqlite3.Error as e:
                return _closed(f"no ledger and house {_house_name(house)} cannot be read ({e})")
            if mark:
                return _closed(f"ledger missing but house {_house_name(house)} carries its id")
        return Gate("off", None)
    try:
        led = Ledger.open_read_only(root, busy_ms)
    except (LedgerUnreadable, FileNotFoundError) as e:
        hot = ledger_path(root).with_name("permissions.db-journal").exists() and "locked" not in str(e)
        if hot:
            return _closed("ledger has a hot journal; any writing open clears it, such as engram-permissions sweep")
        return _closed(f"ledger cannot be read: {e}")
    try:
        # meta and the log's last row in one read: a gate act writes `gate` and `head` in one commit, so a meta page
        # torn apart from the log names an older head, and the gate it holds is not the ledger's (P 5.6)
        led.conn.execute("BEGIN")
        try:
            meta = led.meta()
            cut = led._head_problem(led.seq(), meta)
        finally:
            led.conn.execute("COMMIT")
    except sqlite3.Error as e:
        return _closed(f"ledger cannot be read: {e}")
    finally:
        led.close()
    if cut:
        return _closed(f"{cut}: the log's tail was cut, so the gate it holds may be an older one; "
                       "engram-permissions verify reports it")
    ledger_id, mode, raised = meta.get("ledger_id"), meta.get("gate"), bool(meta.get("gate_raised"))
    for house in served:
        try:
            mark = _house_id(house)
        except sqlite3.Error as e:
            return _closed(f"house {_house_name(house)} cannot be read ({e})")
        if mark is None and raised:
            return _closed(f"house {_house_name(house)} carries no ledger id but the gate was raised; run "
                           "engram-permissions gate <current mode> to mark it")
        if mark is not None and mark != ledger_id:
            return _closed(f"house {_house_name(house)} carries ledger id {mark}, not this ledger's")
    if mode is None:
        return _closed("gate_raised is set but the gate is missing") if raised else Gate("off", None)
    if mode not in GATE_MODES:
        return _closed(f"the gate holds {mode!r}, which is not one of {', '.join(GATE_MODES)}")
    return Gate(mode, None)


def ledger_for_house(db_path: Path) -> Path | None:
    """The ledger file of the engram home a house sits in (`.engram/graph.db` or `.engram/instances/<n>/graph.db`),
    or None when the path is no house of that shape or the ledger file does not exist."""
    db_path = Path(db_path)
    if db_path.name != "graph.db":
        return None
    parent = db_path.parent
    if parent.name == ".engram":
        base = parent
    elif parent.parent.name == "instances" and parent.parent.parent.name == ".engram":
        base = parent.parent.parent
    else:
        return None
    ledger = base / "permissions.db"
    return ledger if ledger.is_file() else None


def house_mark(db_path: Path) -> str | None:
    """The id to write into a house created now (P 12.3, 'A house made later'): the ledger's id when its gate is
    raised, 'unreadable' when the ledger exists but cannot be read, None when no raised ledger exists."""
    ledger = ledger_for_house(db_path)
    if ledger is None:
        return None
    try:
        led = Ledger.open_read_only(ledger.parent.parent)
    except (LedgerUnreadable, FileNotFoundError):
        return "unreadable"
    try:
        meta = led.meta()
    except sqlite3.Error:
        return "unreadable"
    finally:
        led.close()
    return meta.get("ledger_id") if meta.get("gate_raised") else None


def _prep_gate(state, actor, args):
    if set(args) - {"mode"}:
        raise RuleError(_GATE, "the gate act takes only mode: the houses are those on disk at the yes")
    mode = args.get("mode")
    if mode not in GATE_MODES:
        raise RuleError(_GATE, f"the gate is one of {', '.join(GATE_MODES)}")
    return {"mode": mode}


def _mark_house(db_path: Path, ledger_id: str) -> None:
    """R17: plain sqlite3, one BEGIN IMMEDIATE per house."""
    try:
        con = sqlite3.connect(db_path, isolation_level=None, timeout=BUSY_MS / 1000)
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute("INSERT INTO meta(key, value) VALUES('permissions_ledger_id', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (ledger_id,))
            con.execute("COMMIT")
        finally:
            con.close()
    except sqlite3.Error as e:
        raise RuleError(_GATE, f"house {_house_name(db_path)} could not be marked ({e}); nothing was recorded, "
                               "run the gate again") from e


def _make_gate(state, actor, args, auth, now, *, root: Path):
    mode, raised = args["mode"], bool(state.meta.get("gate_raised"))
    if mode != "off" and not raised and not (root / PUBLISHED_HOUSE).is_file():
        raise RuleError(_GATE, f"the published house {root / PUBLISHED_HOUSE} does not exist, so there is nothing "
                               "to serve or share from")
    body: dict = {"meta": {"gate": mode}, "houses": []}
    marking = mode != "off" or raised
    if marking:
        body["meta"]["gate_raised"] = "1"
    ledger_id = state.meta["ledger_id"]
    for house in houses(root):
        try:
            mark = _house_id(house)
        except sqlite3.Error:
            if not marking:
                continue        # never raised: a house whose mark cannot be read is left as it is
            mark = None
        # Under every mode a house marked `unreadable`, or with an earlier ledger's id, is marked with this one's,
        # so `gate off` opens it (Serenity's section 2, item 6); an unmarked house is marked once the gate is raised.
        if mark != ledger_id and (marking or mark is not None):
            _mark_house(house, ledger_id)
            body["houses"].append(house.relative_to(root).as_posix())
    return "gate:" + mode, body


_ACTS = {
    "register-person": _Act(_prep_register_person, _make_register_person, _pure),
    "retire-person": _Act(_prep_retire_person, _make_retire_person, _local(_may_retire_person)),
    "register-place": _Act(_prep_register_place, _make_register_place, _pure),
    "add-parent": _Act(_prep_add_parent, _make_add_parent, _pure),
    "add-steward": _Act(_prep_add_steward, _make_add_steward, _pure),
    "remove-steward": _Act(_prep_remove_steward, _make_remove_steward, _pure),
    "retire-place": _Act(_prep_retire_place, _make_retire_place, _local(_may_retire_place)),
    "register-agent": _Act(_prep_register_agent, _make_register_agent, _pure),
    "put-agent": _Act(_prep_put_agent, _make_put_agent, _pure),
    "remove-agent": _Act(_prep_remove_agent, _make_remove_agent, _pure),
    "register-store": _Act(_prep_register_store, _make_register_store, _pure),
    "group": _Act(_prep_group, _make_group, _pure),
    "make-collection": _Act(_prep_make_collection, _make_make_collection, _local(_may_make_collection)),
    "collect": _Act(_prep_collect, _make_collect, _pure),
    "uncollect": _Act(_prep_uncollect, _make_uncollect, _pure),
    "add-subject": _Act(_prep_add_subject, _make_add_subject, _pure),
    "remove-subject": _Act(_prep_remove_subject, _make_remove_subject, _pure),
    "allow": _Act(_prep_record("allow"), _make_new_record("allow"), _pure, _check_new_record("allow")),
    "deny": _Act(_prep_record("deny"), _make_new_record("deny"), _pure, _check_new_record("deny")),
    "revoke": _Act(_prep_revoke, _make_revoke, _edit_authority("revoke")),
    "shorten": _Act(_prep_shorten, _make_replacement, _edit_authority("shorten"), _check_replacement),
    "narrow": _Act(_prep_narrow, _make_replacement, _edit_authority("narrow"), _check_replacement),
    "grant": _Act(_prep_grant, _make_grant, _pure, _check_grant),
    "revoke-grant": _Act(_prep_end_grant, _make_end_grant, _pure),
    "give-up-grant": _Act(_prep_end_grant, _make_end_grant, _pure),
    "gate": _Act(_prep_gate, _make_gate, _pure, rooted=True),
}
# the acts after which the gluing check reruns (R5): the registry of places, parents, agents, groups,
# collections and stewards
_GLUED = frozenset({"register-place", "add-parent", "add-steward", "remove-steward", "retire-place",
                    "retire-person", "register-agent", "put-agent", "remove-agent", "group", "make-collection",
                    "collect", "uncollect"})


# -- proposals that wait for other stewards (R6): what each signature must cover

def _needs(act: Act) -> list[dict]:
    a = act.args
    if act.kind == "register-place":
        return [{"role": "steward", "of": q} for q in a["parents"]]
    if act.kind == "add-parent":
        return [{"role": "steward", "of": a["place"]}, {"role": "steward", "of": a["parent"]}]
    if act.kind == "put-agent":
        return [{"role": "steward", "of": a["place"]}, {"role": "principal", "of": a["agent"]}]
    raise RuleError(_ACT, f"{act.kind} has no joint signatures")


def _covers(state: State, needs: list[dict], persons) -> frozenset[int]:
    """The indexes of `needs` that some person of `persons` can sign for now."""
    def can(need, person):
        if not person.startswith("person:"):
            return False
        if need["role"] == "steward":
            return _layer_steward(state, person, need["of"])
        return person in _principals(state, need["of"])
    return frozenset(i for i, n in enumerate(needs) if any(can(n, p) for p in persons))
