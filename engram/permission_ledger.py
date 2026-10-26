"""The permission ledger file (P 5.5, 5.6): ENGRAM_HOME/.engram/permissions.db.

An append-only, hash-chained log (`ledger_log`) is the source of truth. Every table is a projection of it,
written in the same `BEGIN IMMEDIATE` as the log row, by the one projection code `rebuild` replays.

A log row's `body` is canonical JSON with these optional parts (the `kind` is a label; all kinds share this):

    {"insert": [{"table": T, "row": {...}}],         # rows added to table T
     "update": [{"table": T, "where": {...}, "set": {...}}],   # columns set on the rows matching `where`
     "meta":   {key: value},                         # meta keys set
     "name":   "Public Health"}                      # a register-place's display name (R4)

In a row or a `set`, the string "@seq" stands for the log row's own seq and "@at" for its time; a dict or list
value is stored as canonical JSON text; a places row's `pseudonym_salt` is hex."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Mapping

from lighthouse_protocol import canonical_json
from permissions import State, RuleError, check_id, _COLUMNS, _NULLABLE

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
CREATE INDEX subjects_object ON subjects(object);
CREATE INDEX lane_notes_object ON lane_notes(object);
CREATE INDEX group_members_group ON group_members(group_id);
"""

# table order for tables(): the order of the schema
_TABLES = tuple(_COLUMNS)
_LOG_COLUMNS = ("seq", "at", "kind", "ref", "actor", "channel", "under_grant", "proposal_id", "body",
                "prev_digest", "digest")
_HOT = ("This ledger has a hot journal from a writer that stopped mid-commit, which a read-only reader cannot "
        "roll back. Every reader reads `closed` until a writing open clears it: run any writing command, "
        "such as `engram-permissions sweep`.")


class LedgerUnreadable(Exception):
    pass


def ledger_path(engram_home: Path) -> Path:
    return Path(engram_home) / ".engram" / "permissions.db"


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
    def _connect(path: Path, *, read_only: bool) -> sqlite3.Connection:
        try:
            if read_only:
                conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None,
                                       timeout=BUSY_MS / 1000)
                conn.execute("PRAGMA query_only=ON")
            else:
                conn = sqlite3.connect(path, isolation_level=None, timeout=BUSY_MS / 1000)
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout={BUSY_MS}")
            return conn
        except sqlite3.Error as e:
            raise LedgerUnreadable(f"{path}: {e}") from e

    @classmethod
    def _open(cls, engram_home: Path, read_only: bool) -> "Ledger":
        path = ledger_path(engram_home)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        conn = cls._connect(path, read_only=read_only)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None or row["value"] != SCHEMA_VERSION:
                conn.close()
                raise LedgerUnreadable(f"{path}: not a version {SCHEMA_VERSION} permission ledger")
        except sqlite3.Error as e:
            conn.close()
            hot = path.with_name(path.name + "-journal").exists()
            raise LedgerUnreadable(f"{path}: {e}. {_HOT if hot else ''}".strip()) from e
        return cls(conn, path, read_only)

    @classmethod
    def open(cls, engram_home: Path) -> "Ledger":
        return cls._open(engram_home, False)

    @classmethod
    def open_read_only(cls, engram_home: Path) -> "Ledger":
        return cls._open(engram_home, True)

    @classmethod
    def _blank(cls, engram_home: Path, ledger_id: str) -> "Ledger":
        path = ledger_path(engram_home)
        if path.exists():
            raise FileExistsError(str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = cls._connect(path, read_only=False)
        conn.executescript(_SCHEMA)
        conn.executemany("INSERT INTO meta VALUES(?,?)",
                         [("ledger_id", ledger_id), ("schema_version", SCHEMA_VERSION)])
        return cls(conn, path, False)

    @classmethod
    def create(cls, engram_home: Path, owner_handle: str, *, now: int) -> "Ledger":
        owner = check_id("person", "person:" + owner_handle)
        home = "place:home/" + owner_handle
        check_id("place", home)
        led = cls._blank(engram_home, str(uuid.uuid4()))
        led._append("register-person", owner, owner, "terminal", {
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
        top = self.seq()
        seq = top if seq is None else seq
        if not 0 <= seq <= top:
            raise ValueError(f"seq {seq} is outside the log (0 to {top})")
        log = [dict(r) for r in self.conn.execute("SELECT seq, at, kind, ref, body FROM ledger_log ORDER BY seq")]
        tables = {t: [dict(r) for r in self.conn.execute(
            f"SELECT {', '.join(_COLUMNS[t])} FROM {t} ORDER BY rowid")] for t in _TABLES}
        names = {}
        for r in log:
            if r["seq"] <= seq and r["kind"] == "register-place":
                name = json.loads(r["body"]).get("name")
                if name:
                    names[r["ref"]] = name
        return State.from_tables(tables, seq=seq, seq_at={r["seq"]: r["at"] for r in log}, meta=self.meta(),
                                 names=names)

    def verify(self) -> int | None:
        prev, expect = ZERO, 1
        for row in self.conn.execute("SELECT * FROM ledger_log ORDER BY seq"):
            if row["seq"] != expect or row["prev_digest"] != prev or row["digest"] != _digest(prev, _entry(row)):
                return expect
            prev, expect = row["digest"], expect + 1
        return None

    # ---------------------------------------------------------------- writing
    def _append(self, kind: str, ref: str, actor: str, channel: str, body: Mapping, *,
                under_grant: str | None = None, proposal_id: str | None = None, at: int) -> int:
        """One log row and its projection, in one BEGIN IMMEDIATE. Returns the row's seq."""
        text = canonical_json(dict(body))
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            last = self.conn.execute("SELECT seq, digest FROM ledger_log ORDER BY seq DESC LIMIT 1").fetchone()
            seq, prev = (last["seq"] + 1, last["digest"]) if last else (1, ZERO)
            entry = {"seq": seq, "at": at, "kind": kind, "ref": ref, "actor": actor, "channel": channel,
                     "under_grant": under_grant, "proposal_id": proposal_id, "body": text}
            self.conn.execute(
                "INSERT INTO ledger_log VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (seq, at, kind, ref, actor, channel, under_grant, proposal_id, text, prev, _digest(prev, entry)))
            self._project(json.loads(text), seq, at)
            self.conn.execute("COMMIT")
        except BaseException as e:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            if isinstance(e, sqlite3.IntegrityError):
                raise _bad(f"the change collides with an existing row ({e})") from e
            raise
        return seq

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
            if key not in ("insert", "update", "meta", "name"):
                raise _bad(f"unknown part of a log body: {key}")
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
                raise _bad(f"{table} update matched no row: {where}")
        for k, v in body.get("meta", {}).items():
            self.conn.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                              (k, str(v)))

    @staticmethod
    def _check_table(table: str) -> None:
        if table not in _COLUMNS:
            raise _bad(f"unknown table {table!r}")

    # ---------------------------------------------------------------- rebuild
    def rebuild(self, dest: Path) -> Path:
        """Replay the log into a fresh ledger whose engram home is `dest`; the same tables. Returns `dest`."""
        meta = self.meta()
        new = Ledger._blank(dest, meta["ledger_id"])
        try:
            for r in self.conn.execute("SELECT * FROM ledger_log ORDER BY seq").fetchall():
                got = new._append(r["kind"], r["ref"], r["actor"], r["channel"], json.loads(r["body"]),
                                  under_grant=r["under_grant"], proposal_id=r["proposal_id"], at=r["at"])
                if got != r["seq"]:
                    raise _bad(f"the log has a gap before seq {r['seq']}")
        finally:
            new.close()
        return Path(dest)
