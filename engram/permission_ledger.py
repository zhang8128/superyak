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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from lighthouse_protocol import canonical_json
from permissions import (
    CHANNELS, GRANT_OPS, JOINTS_PER_CHANGE, LANES, MAX_COPY_CHAIN, MAX_PLACES, MAX_REPLACES, MAX_SUBJECTS,
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


@dataclass(frozen=True)
class Outcome:
    """What `Ledger.perform` did: `done`, or `proposal` (a proposal was filed, or one signature was added).
    `ref` is the thing written (or the proposal's id) and `seq` the log row. `reports` are the gluing reports of
    up to JOINTS_PER_CHANGE joint places after a registry change (R5); `pending_checks` names the rest."""
    status: str
    ref: str
    seq: int
    reports: tuple = ()
    pending_checks: tuple = ()


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
        ref, body = spec.make(state, actor, args, auth, now)
        body = _stamp(body, channel, None)
        seq = self._append(act.kind, ref, actor, channel, body, under_grant=auth.under_grant, at=now)
        return self._outcome("done", ref, seq, act.kind, args)

    def _outcome(self, status: str, ref: str, seq: int, kind: str, args: Mapping = ()) -> Outcome:
        """After a registry change, or a rule written in a place's layer, the gluing reports of up to
        JOINTS_PER_CHANGE joint places (R5)."""
        if kind in _GLUED:
            changed = {REGISTRY}
        elif kind in _RECORD_ACTS:
            state = self.state()
            rec = state.records.get(args.get("record")) if "record" in args else None
            changed = {rec.layer if rec is not None else args.get("layer")}
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
            seq = self._append("proposal-decline", pid, actor, channel, {"update": [{
                "table": "proposals", "where": {"id": pid}, "set": {"status": "declined", "decided_seq": "@seq"}}]},
                proposal_id=pid, at=now)
            return Outcome("done", pid, seq)
        if channel == "tool":
            raise RuleError("7.6 the person's yes", "a signature needs the terminal; the tools can give no yes")
        if needs is None:
            return self._sign_alone(state, p, body, actor, channel, now)
        spec_act = body["act"]
        now_covered = _covers(state, needs, had | {actor})
        if now_covered == _covers(state, needs, had):
            raise RuleError(_ACT, f"{actor} adds no signature {pid} still needs")
        if now_covered != frozenset(range(len(needs))):
            seq = self._append("proposal-sign", pid, actor, channel, {}, proposal_id=pid, at=now)
            return Outcome("proposal", pid, seq)
        spec = _ACTS[spec_act["kind"]]
        args = spec.prepare(state, p.by_agent, dict(spec_act["args"]))
        ref, mbody = spec.make(state, p.by_agent, args, Authority("do", "person", None), now)
        mbody = _signed(_stamp(mbody, channel, pid), pid)
        seq = self._append(spec_act["kind"], ref, actor, channel, mbody, proposal_id=pid, at=now)
        return self._outcome("done", ref, seq, spec_act["kind"], args)

    def _sign_alone(self, state: State, p, body: Mapping, actor: str, channel: str, now: int) -> Outcome:
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
        ref, mbody = spec.make(state, actor, args, auth, now)
        mbody = _signed(_stamp(mbody, "terminal", p.id), p.id)
        seq = self._append(kind, ref, actor, channel, mbody, under_grant=auth.under_grant, proposal_id=p.id, at=now)
        return self._outcome("done", ref, seq, kind, args)

    def proposals(self, *, now: int) -> list[dict]:
        """The open proposals (pending and not yet expired), oldest first. `words` come from the body by one
        template per kind (P 7.7); the agent's `reason` is kept apart and is never in them."""
        state = self.state()
        out = []
        for p in sorted(state.proposals.values(), key=lambda r: (r.created, r.id)):
            if p.status != "pending" or p.expires <= now:
                continue
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
    def record_copy(self, copy_ref: str, source_ref: str, *, now: int) -> None:
        """The `copies` row and the source's subjects as co-subjects of the copy (`added_by` copy:<source>), in one
        transaction, before the store write. Refused past MAX_COPY_CHAIN links or MAX_SUBJECTS subjects."""
        if self.read_only:
            raise _bad("this ledger is open read-only")
        rule = "7.4 kept copies"
        parse_object_ref(copy_ref)
        parse_object_ref(source_ref)
        state = self.state()
        if copy_ref == source_ref:
            raise RuleError(rule, "a memory is not a copy of itself")
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
        carried = sorted(set(subjects_of(state, source_ref, now)) - own)
        if len(own) + len(carried) > MAX_SUBJECTS:
            raise RuleError(rule, f"a copy has at most {MAX_SUBJECTS} subjects, with its source's")
        by = "copy:" + source_ref
        insert = [{"table": "copies", "row": {"object": copy_ref, "source": source_ref, "added_seq": "@seq"}}]
        insert += [{"table": "subjects", "row": {"object": copy_ref, "subject": s, "added_seq": "@seq",
                                                 "added_by": by, "self_claimed": 0}} for s in carried]
        self._append("record-copy", copy_ref, by, "tool", {"insert": insert}, at=now)

    def store_row(self, instance_id: str) -> dict | None:
        r = self.conn.execute("SELECT instance_id, name, owner, place, imprint_of, created_seq FROM stores "
                              "WHERE instance_id=?", (instance_id,)).fetchone()
        return None if r is None else dict(r)

    def cosubjects(self, ref: str) -> frozenset[str]:
        """The effective co-subjects of ref, other than the default subject (its store's owner)."""
        return frozenset(r["subject"] for r in self.conn.execute(
            "SELECT subject FROM subjects WHERE object=? AND removed_seq IS NULL", (ref,)))

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


# ---------------------------------------------------------------- the registry acts (P 4.4, 7.4)

_ACT = "7.1 who may set what"
_REG = "4.4 who registers places and people"


@dataclass(frozen=True)
class _Act:
    prepare: Callable      # (state, actor, args) -> args: shape, defaults and state rules; raises RuleError
    make: Callable         # (state, actor, args, authority, now) -> (ref, log body)
    authority: Callable = None   # (state, actor, act, channel, now) -> Authority; default: the pure model's
    check: Callable = None       # (state, actor, args, now) -> None: the write-time rules (P 5.4, 7.1, 7.2); raises


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
    person = args["person"]
    return person, {"update": [_upd("persons", {"id": person}, retired_seq="@seq"),
                               _upd("places", {"id": state.persons[person].home}, retired_seq="@seq")]}


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
    return args["place"], {"update": [_upd("places", {"id": args["place"]}, retired_seq="@seq")]}


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


def _prep_collect(state, actor, args):
    cid = _text(args, "collection")
    if cid not in state.collections:
        raise RuleError(_ACT, f"{cid} is not a collection")
    objects = _texts(args, "refs" if "refs" in args else "objects", at_least=1)
    for o in objects:
        parse_object_ref(o)
    new = [o for o in objects if o not in _members(state, cid)]
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
    for o in objects:
        if o not in _members(state, cid):
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


def _may_retire_person(state, actor, args):
    if actor.startswith("agent:") or not (actor == args["person"] or state.persons[actor].is_admin):
        raise RuleError(_ACT, "a person is retired by themself or by a ledger admin")


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
    return {**body, "update": [*body.get("update", ()), _upd("proposals", {"id": pid}, status="signed",
                                                             decided_seq="@seq")]}


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
    return args["record"], {"update": [_upd(
        "records", {"id": args["record"]}, revoked="@at", revoked_by=actor, revoke_reason=args["reason"],
        revoked_seq="@seq")]}


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
        "update": [_upd("records", {"id": old.id}, revoked="@at", revoked_by=actor,
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
    return args["grant"], {"update": [_upd(
        "permission_grants", {"id": args["grant"]}, revoked="@at", revoked_by=actor,
        revoke_reason=args["reason"], revoked_seq="@seq")]}


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
