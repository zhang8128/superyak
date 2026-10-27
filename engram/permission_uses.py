"""The permission receipts file (P 9.1): ENGRAM_HOME/.engram/permission-uses.db.

A file of its own, so the daemon's read-only ledger stays read-only (P15). Both the daemon and the engram servers
append to it, each write in one `BEGIN IMMEDIATE` that reads the last digest inside the transaction. Receipts are
hash-chained as the ledger's log is (P 5.6): digest = sha256(prev_digest + "\\n" + canonical_json(entry)), the entry
being the row without `prev_digest` and `digest`, the first `prev_digest` 64 zeros. A receipt never holds content
or query text. The file keeps SQLite's rollback journal (R1).

Encodings (R15): `cited` is a JSON list of {"layer", "kind", "action", "verdict", "record" | "records",
"version"}; `refusal` is {"code", "layer", "action"}; `returned` is a sorted list of refs (a recall, or the
memories a road or trail named), {"count", "sha256"} (a named bulk use), {"count"} (a counted one), or null
(an imported counted row refused before the station counted)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from lighthouse_protocol import canonical_json
from permissions import (BulkUse, Decision, FOLD_BATCH, GUARD_RECEIPTS, GUARD_SECONDS, RETENTION_DAYS, USE_LIST_ROWS, State,
                         Use, dominators, holding_place, person_of_home)

ZERO = "0" * 64
# The digest form (PRAGMA user_version): 2 puts a receipt's use_subjects rows in its digest. A file of an earlier
# form (0, from before Task 16B) is refused, not misread.
DIGEST_FORM = 2
BUSY_MS = 5000

_SCHEMA = (
    """CREATE TABLE uses(seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, at INTEGER NOT NULL, ledger_id TEXT NOT NULL,
  ledger_seq INTEGER NOT NULL, agent TEXT NOT NULL, place TEXT NOT NULL, acting_for TEXT NOT NULL, session_label TEXT,
  action TEXT NOT NULL, purpose TEXT NOT NULL, object TEXT, copy TEXT, allowed INTEGER NOT NULL, cited TEXT NOT NULL,
  refusal TEXT, until INTEGER, horizon INTEGER, returned TEXT, filtered INTEGER, content_digest TEXT,
  shadow INTEGER NOT NULL DEFAULT 0, prev_digest TEXT NOT NULL, digest TEXT NOT NULL)""",
    """CREATE TABLE use_subjects(use_seq INTEGER NOT NULL, subject TEXT NOT NULL, object TEXT NOT NULL)""",
    """CREATE INDEX use_subjects_use ON use_subjects(use_seq)""",
    """CREATE TABLE uses_anchor(through_seq INTEGER PRIMARY KEY, digest TEXT NOT NULL)""",
    """CREATE TABLE uses_monthly(month TEXT NOT NULL, subject TEXT NOT NULL, place TEXT NOT NULL, action TEXT NOT NULL,
  purpose TEXT NOT NULL, outcome TEXT NOT NULL, n INTEGER NOT NULL,
  PRIMARY KEY(month, subject, place, action, purpose, outcome))""",
)


def pseudonym(salt: bytes, subject: str) -> str:
    """P 9.2: the first 16 hex of HMAC-SHA256(a place's salt, a subject id). A display convention, not a protection."""
    return hmac.new(bytes(salt), subject.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


@dataclass
class UseList:
    """Counts first (`total`, `local`, `imported`, and in a place view `filtered`), then at most USE_LIST_ROWS rows."""
    counts: dict
    rows: list


class UsesUnreadable(Exception):
    pass


def uses_path(engram_home) -> Path:
    return Path(engram_home) / ".engram" / "permission-uses.db"


@dataclass(frozen=True)
class UseRow:
    """The columns of `uses` other than seq, prev_digest and digest. `id` None means `append` makes one
    (u- and 32 hex); an imported row carries the id the imprints spec derives."""
    at: int
    ledger_id: str
    ledger_seq: int
    agent: str
    place: str
    acting_for: str
    action: str
    purpose: str
    allowed: int
    cited: str
    id: str | None = None
    session_label: str | None = None
    object: str | None = None
    copy: str | None = None
    refusal: str | None = None
    until: int | None = None
    horizon: int | None = None
    returned: str | None = None
    filtered: int | None = None
    content_digest: str | None = None
    shadow: int = 0


_COLUMNS = ("id", "at", "ledger_id", "ledger_seq", "agent", "place", "acting_for", "session_label", "action",
            "purpose", "object", "copy", "allowed", "cited", "refusal", "until", "horizon", "returned", "filtered",
            "content_digest", "shadow")
assert set(_COLUMNS) == {f.name for f in fields(UseRow)}


def _digest(prev: str, entry: dict) -> str:
    return hashlib.sha256((prev + "\n" + canonical_json(entry)).encode("utf-8")).hexdigest()


def _pairs(subjects: Iterable[tuple[str, str]]) -> list[list[str]]:
    """A receipt's (subject, object) rows in the canonical order the digest covers."""
    return sorted([subject, obj] for subject, obj in subjects)


def _entry(row, subjects: Iterable[tuple[str, str]]) -> dict:
    return {"seq": row["seq"], **{c: row[c] for c in _COLUMNS}, "subjects": _pairs(subjects)}


# ---------------------------------------------------------------- rows from decisions

def _is_answer(obj: str) -> bool:
    return obj.startswith(("road:", "trail:"))


def _refusal(d: Decision) -> str | None:
    return None if d.refusal is None else canonical_json(d.refusal.to_json())


def _bulk_returned(bulk: BulkUse) -> str:
    objects = sorted(set(bulk.objects))
    if bulk.named:
        return canonical_json({"count": len(objects), "sha256": hashlib.sha256("\n".join(objects).encode()).hexdigest()})
    return canonical_json({"count": len(objects)})


def row_for_decision(d: Decision, use: Use, *, acting_for: str, content_digest: str | None = None,
                     shadow: bool = False, ledger_id: str = "") -> UseRow:
    """One read or delivery item, or one answer use on a road or trail (`returned`: the memories it named, R15)."""
    returned = canonical_json(sorted(set(use.names))) if _is_answer(use.obj) else None
    return UseRow(at=d.at, ledger_id=ledger_id, ledger_seq=d.ledger_seq, agent=use.requester, place=use.place,
                  acting_for=acting_for, action=use.action, purpose=use.purpose, object=use.obj, copy=use.copy,
                  allowed=int(d.allowed), cited=canonical_json(d.to_json()["cited"]), refusal=_refusal(d),
                  until=d.until, horizon=d.horizon, returned=returned, content_digest=content_digest,
                  shadow=int(shadow))


def row_for_recall(decisions: Sequence[Decision], use: Use, *, acting_for: str, returned: Sequence[str],
                   filtered: int, shadow: bool = False, ledger_id: str = "") -> UseRow:
    """One receipt for a recall (R8): every distinct record cited per (layer, action) over the decisions, and the
    earliest `until` and `horizon` over what it returned. No object; filtered copies get no ids."""
    merged: dict = {}
    versions: dict = {}
    for d in decisions:
        for c in d.cited:
            merged.setdefault((c.layer, c.kind, c.action, c.verdict), set()).update(c.records)
            if c.layer in d.versions:
                versions[c.layer] = max(versions.get(c.layer, 0), d.versions[c.layer])
    cited = [{"layer": layer, "kind": kind, "action": action, "verdict": verdict, "records": sorted(recs),
              "version": versions.get(layer)} for (layer, kind, action, verdict), recs in sorted(merged.items())]

    def earliest(values):
        values = [v for v in values if v is not None]
        return min(values) if values else None

    return UseRow(at=use.at, ledger_id=ledger_id, ledger_seq=max((d.ledger_seq for d in decisions), default=0),
                  agent=use.requester, place=use.place, acting_for=acting_for, action=use.action,
                  purpose=use.purpose, copy=use.copy, allowed=int(all(d.allowed for d in decisions)),
                  cited=canonical_json(cited), until=earliest(d.until for d in decisions),
                  horizon=earliest(d.horizon for d in decisions), returned=canonical_json(sorted(returned)),
                  filtered=filtered, shadow=int(shadow))


def row_for_bulk(d: Decision, bulk: BulkUse, *, acting_for: str, ledger_id: str = "") -> UseRow:
    """One receipt for a bulk use (R15): `object` null, `copy` = h; named, the count and the SHA-256 of the
    sorted objects; counted, the count."""
    return UseRow(at=d.at, ledger_id=ledger_id, ledger_seq=d.ledger_seq, agent=bulk.requester, place=bulk.place,
                  acting_for=acting_for, action=bulk.action, purpose=bulk.purpose, copy=bulk.copy,
                  allowed=int(d.allowed), cited=canonical_json(d.to_json()["cited"]), refusal=_refusal(d),
                  until=d.until, horizon=d.horizon, returned=_bulk_returned(bulk))


# ---------------------------------------------------------------- the file

class Uses:
    def __init__(self, conn: sqlite3.Connection, path: Path, read_only: bool):
        self.conn, self.path, self.read_only = conn, path, read_only

    @staticmethod
    def _connect(path: Path, read_only: bool) -> sqlite3.Connection:
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
            raise UsesUnreadable(f"{path}: {e}") from e

    @staticmethod
    def _refuse_old_form(conn: sqlite3.Connection, path: Path) -> None:
        if conn.execute("PRAGMA user_version").fetchone()[0] != DIGEST_FORM:
            conn.close()
            raise UsesUnreadable(f"{path}: the receipts file is of an earlier digest form (its subject rows are not "
                                 f"in the chain); this version will not read it")

    @classmethod
    def open(cls, engram_home) -> "Uses":
        """Open for writing, creating the file and its four tables when there are none."""
        path = uses_path(engram_home)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = cls._connect(path, False)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='uses'").fetchone() is None:
                    for statement in _SCHEMA:
                        conn.execute(statement)
                    conn.execute(f"PRAGMA user_version={DIGEST_FORM}")
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        except sqlite3.Error as e:
            conn.close()
            raise UsesUnreadable(f"{path}: {e}") from e
        cls._refuse_old_form(conn, path)
        return cls(conn, path, False)

    @classmethod
    def open_read_only(cls, engram_home) -> "Uses":
        path = uses_path(engram_home)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        conn = cls._connect(path, True)
        try:
            conn.execute("SELECT 1 FROM uses LIMIT 1")
        except sqlite3.Error as e:
            conn.close()
            raise UsesUnreadable(f"{path}: {e}") from e
        cls._refuse_old_form(conn, path)
        return cls(conn, path, True)

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- writing
    def _tail(self) -> tuple[int, str]:
        """(the last seq, its digest): the last row's, else the latest anchor's, else (0, ZERO)."""
        last = self.conn.execute("SELECT seq, digest FROM uses ORDER BY seq DESC LIMIT 1").fetchone()
        if last is None:
            last = self.conn.execute(
                "SELECT through_seq AS seq, digest FROM uses_anchor ORDER BY through_seq DESC LIMIT 1").fetchone()
        return (last["seq"], last["digest"]) if last else (0, ZERO)

    def append(self, row: UseRow, subjects: Iterable[tuple[str, str]]) -> str:
        """One receipt and its (subject, object) rows in one BEGIN IMMEDIATE. Returns the receipt's id."""
        if not row.ledger_id:
            raise ValueError("receipt: ledger_id is empty (a receipt carries the ledger id of the station that wrote it)")
        rid = row.id or "u-" + os.urandom(16).hex()
        subjects = list(subjects)
        values = {c: getattr(row, c) for c in _COLUMNS}
        values["id"] = rid
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            top, prev = self._tail()
            seq = top + 1
            digest = _digest(prev, {"seq": seq, **values, "subjects": _pairs(subjects)})
            self.conn.execute(
                f"INSERT INTO uses(seq, {', '.join(_COLUMNS)}, prev_digest, digest) "
                f"VALUES({', '.join('?' * (len(_COLUMNS) + 3))})",
                (seq, *values.values(), prev, digest))
            self.conn.executemany("INSERT INTO use_subjects VALUES(?,?,?)",
                                  [(seq, subject, obj) for subject, obj in subjects])
            self.conn.execute("COMMIT")
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise
        return rid

    def append_imported(self, row: UseRow, subjects: Iterable[tuple[str, str]]) -> str:
        """An imported station receipt (P 9.1, the four differences): `object` null, `copy` an imprint ref,
        `cited` the record ids alone, no horizon, and `returned` null only for a use refused before the station
        counted. The id is the one the imprints spec derives."""
        def bad(why):
            return ValueError(f"imported receipt: {why}")

        if not row.id:
            raise bad("it carries the id the imprints spec derives")
        if row.object is not None:
            raise bad("object is null")
        if not (row.copy or "").startswith("imprint:"):
            raise bad("copy is an imprint: ref")
        if row.horizon is not None:
            raise bad("horizon is null (a station without a ledger has no layer versions)")
        try:
            cited = json.loads(row.cited)
        except ValueError:
            cited = None
        if not isinstance(cited, list) or not all(isinstance(c, str) for c in cited):
            raise bad("cited holds record ids alone")
        if row.returned is None:
            if row.allowed:
                raise bad("returned is null only for a use refused before it was counted")
        else:
            returned = json.loads(row.returned)
            if not isinstance(returned, dict) or not isinstance(returned.get("count"), int):
                raise bad("returned holds a count")
        return self.append(row, subjects)

    # ---------------------------------------------------------------- the chain
    def _check(self, rows, prev: str, expect: int) -> int | None:
        for row in rows:
            subjects = [(s["subject"], s["object"]) for s in self.conn.execute(
                "SELECT subject, object FROM use_subjects WHERE use_seq=?", (row["seq"],))]
            if (row["seq"] != expect or row["prev_digest"] != prev
                    or row["digest"] != _digest(prev, _entry(row, subjects))):
                return expect
            prev, expect = row["digest"], expect + 1
        return None

    def _anchor(self) -> tuple[int, str]:
        a = self.conn.execute("SELECT through_seq, digest FROM uses_anchor ORDER BY through_seq DESC LIMIT 1").fetchone()
        return (a["through_seq"], a["digest"]) if a else (0, ZERO)

    def verify(self) -> int | None:
        """None when the chain verifies from the latest anchor, else the first seq that fails."""
        through, digest = self._anchor()
        return self._check(self.conn.execute("SELECT * FROM uses WHERE seq > ? ORDER BY seq", (through,)),
                           digest, through + 1)

    # ---------------------------------------------------------------- retention
    def fold(self, *, now: int) -> int:
        """Fold the leading receipts older than RETENTION_DAYS into `uses_monthly`, delete them and their
        subject rows, and write an anchor holding the last folded seq and digest. Returns how many. The fold
        works in batches of FOLD_BATCH, each its own transaction and anchor, and holds one receipt at a time.
        A span whose chain does not verify is not folded (it would launder the break): ValueError, after the
        batches before the break's batch have committed."""
        cutoff = now - RETENTION_DAYS * 86400
        total = 0
        while True:
            n = self._fold_batch(cutoff)
            total += n
            if n < FOLD_BATCH:
                return total

    def _fold_batch(self, cutoff: int) -> int:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            through, digest = self._anchor()
            expect, count = through + 1, 0
            cursor = self.conn.execute("SELECT * FROM uses WHERE seq > ? ORDER BY seq", (through,))
            try:
                for row in cursor:
                    if row["at"] >= cutoff or count >= FOLD_BATCH:
                        break
                    if self._check((row,), digest, expect) is not None:
                        raise ValueError(f"the receipts chain breaks at seq {expect}; nothing was folded")
                    month = datetime.fromtimestamp(row["at"], timezone.utc).strftime("%Y-%m")
                    outcome = "allowed" if row["allowed"] else "refused"
                    subjects = {s[0] for s in self.conn.execute(
                        "SELECT subject FROM use_subjects WHERE use_seq=?", (row["seq"],))}
                    for subject in sorted(subjects) or ["(none)"]:
                        self.conn.execute(
                            "INSERT INTO uses_monthly VALUES(?,?,?,?,?,?,1) ON CONFLICT(month, subject, place, "
                            "action, purpose, outcome) DO UPDATE SET n = n + 1",
                            (month, subject, row["place"], row["action"], row["purpose"], outcome))
                    digest, expect, count = row["digest"], expect + 1, count + 1
            finally:
                cursor.close()
            if count:
                last = expect - 1
                self.conn.execute("DELETE FROM use_subjects WHERE use_seq <= ?", (last,))
                self.conn.execute("DELETE FROM uses WHERE seq <= ?", (last,))
                self.conn.execute("INSERT INTO uses_anchor VALUES(?,?)", (last, digest))
            self.conn.execute("COMMIT")
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise
        return count

    # ---------------------------------------------------------------- views (P 9.2, 9.3)
    def _query(self, where: str, params: Sequence, limit: int | None = USE_LIST_ROWS) -> list:
        sql = f"SELECT * FROM uses WHERE {where} ORDER BY at DESC, seq DESC"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return self.conn.execute(sql, tuple(params)).fetchall()

    def _filters(self, state: State, *, scope=None, since=None, until=None, action=None, purpose=None,
                 collection=None, obj=None, refused=False) -> tuple[list, list]:
        """The WHERE terms the owner's list and a place view share. `scope` is (places, copies) a place view covers."""
        terms, params = [], []
        if since is not None:
            terms.append("at >= ?")
            params.append(since)
        if until is not None:
            terms.append("at < ?")
            params.append(until)
        for column, value in (("action", action), ("purpose", purpose)):
            if value is not None:
                terms.append(f"{column} = ?")
                params.append(value)
        if refused:
            terms.append("allowed = 0")
        if obj is not None:
            terms.append("(object = ? OR EXISTS(SELECT 1 FROM use_subjects s WHERE s.use_seq = uses.seq "
                         "AND s.object = ?))")
            params += [obj, obj]
        if collection is not None:
            members = {r.object for r in state.collection_members.get(collection, ())}
            self.conn.create_function("in_collection", 1, lambda o: o in members, deterministic=True)
            terms.append("(in_collection(object) OR EXISTS(SELECT 1 FROM use_subjects s WHERE "
                         "s.use_seq = uses.seq AND in_collection(s.object)))")
        if scope is not None:
            places, copies = scope
            self.conn.create_function("in_places", 1, lambda p: p in places, deterministic=True)
            self.conn.create_function("in_copies", 1, lambda c: c in copies, deterministic=True)
            terms.append("(in_places(place) OR in_copies(copy))")
        return terms, params

    def _count(self, where: str, params: Sequence, ledger_id: str) -> dict:
        total, imported, filtered = self.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(ledger_id != ?), 0), COALESCE(SUM(filtered), 0) FROM uses "
            f"WHERE {where}", (ledger_id, *params)).fetchone()
        return {"total": total, "local": total - imported, "imported": imported, "filtered": filtered}

    def _subjects_of_rows(self, rows) -> dict:
        out: dict[int, list] = {r["seq"]: [] for r in rows}
        for r in rows:
            out[r["seq"]] = [(s["subject"], s["object"]) for s in self.conn.execute(
                "SELECT subject, object FROM use_subjects WHERE use_seq = ? ORDER BY rowid", (r["seq"],))]
        return out

    def owner_list(self, state: State, *, since=None, until=None, place=None, action=None, purpose=None,
                   collection=None, obj=None, refused=False) -> UseList:
        """P 9.3: the ledger owner's uses, counts first, then at most USE_LIST_ROWS rows, newest first. A recall that
        returned nothing is no use of any memory (9.1), so it is not listed. Rows from another ledger are imported
        station receipts (R14): marked with their station and counted apart."""
        ledger_id = state.meta.get("ledger_id", "")
        terms, params = self._filters(state, scope=_scope(self, state, place) if place else None, since=since,
                                      until=until, action=action, purpose=purpose, collection=collection, obj=obj,
                                      refused=refused)
        terms.append("NOT (object IS NULL AND COALESCE(returned, '') = '[]')")
        where = " AND ".join(terms)
        counts = self._count(where, params, ledger_id)
        del counts["filtered"]
        rows = self._query(where, params)
        subjects = self._subjects_of_rows(rows)
        claims = _self_claims(state)
        return UseList(counts, [_owner_row(state, r, subjects[r["seq"]], claims, ledger_id) for r in rows])

    def place_view(self, state: State, place: str, *, since=None, until=None, action=None, purpose=None,
                   collection=None, obj=None, refused=False) -> UseList:
        """P 9.2's stewards row: uses at the place and at every place it dominates, and uses of copies they hold.
        Every pseudonym is this place's (R33)."""
        row = state.places.get(place)
        if row is None:
            raise ValueError(f"{place} is not a registered place")
        ledger_id = state.meta.get("ledger_id", "")
        terms, params = self._filters(state, scope=_scope(self, state, place), since=since, until=until,
                                      action=action, purpose=purpose, collection=collection, obj=obj,
                                      refused=refused)
        terms.append("shadow = 0")
        where = " AND ".join(terms)
        counts = self._count(where, params, ledger_id)
        rows = self._query(where, params)
        subjects = self._subjects_of_rows(rows)
        return UseList(counts, [_steward_row(r, subjects[r["seq"]], row.pseudonym_salt, ledger_id) for r in rows])

    def agent_view(self, agent: str) -> list[dict]:
        """P 9.2's agents row: the agent's own receipts. A refusal is only the id (or the count of a bulk one) and
        "not allowed". No filtered counts, which would tell it that refused memories exist (P23)."""
        out: list[dict] = []
        for r in self._query("agent = ? AND shadow = 0", (agent,)):
            returned = _json(r["returned"])
            outcome = "allowed" if r["allowed"] else "not allowed"
            if r["object"] is not None:
                out.append({"object": r["object"], "at": r["at"], "outcome": outcome})
                continue
            if isinstance(returned, list):          # a recall: one allowed item per memory it returned
                out += [{"object": m, "at": r["at"], "outcome": outcome} for m in returned]
                continue
            row = {"at": r["at"], "outcome": outcome}
            if isinstance(returned, dict):
                row["count"] = returned["count"]
                if "sha256" in returned:
                    row["sha256"] = returned["sha256"]
            out.append(row)
        return out[:USE_LIST_ROWS]

    def subject_view(self, subject: str) -> list[dict]:
        """P 9.2's subject row: every receipt whose `use_subjects` named the subject when it was written."""
        out = []
        for r in self.conn.execute(
                "SELECT * FROM uses WHERE shadow = 0 AND EXISTS(SELECT 1 FROM use_subjects s WHERE s.use_seq = "
                "uses.seq AND s.subject = ?) ORDER BY at DESC, seq DESC LIMIT ?", (subject, USE_LIST_ROWS)):
            row = {"id": r["id"], "requester": r["agent"], "place": r["place"], "action": r["action"],
                   "purpose": r["purpose"], "records": sorted({rec for c in _cited(r) for rec in c["records"]}),
                   "at": r["at"], "outcome": "allowed" if r["allowed"] else "refused"}
            if r["object"] is not None:
                row["object"] = r["object"]
            else:
                row["objects"] = sorted({o for (o,) in self.conn.execute(
                    "SELECT object FROM use_subjects WHERE use_seq = ? AND subject = ?", (r["seq"], subject))})[:32]
            out.append(row)
        return out

    def deliveries(self, agent: str, *, now: int) -> list[UseRow]:
        """The agent's allowed `inject_context` receipts with now - GUARD_SECONDS < at <= now, at most
        GUARD_RECEIPTS, newest first (the `remember` guard, section 10)."""
        rows = self._query("agent = ? AND action = 'inject_context' AND allowed = 1 AND at > ? AND at <= ?",
                           (agent, now - GUARD_SECONDS, now), limit=GUARD_RECEIPTS)
        return [UseRow(**{c: r[c] for c in _COLUMNS}) for r in rows]


# ---------------------------------------------------------------- view helpers

def _json(text):
    return None if text is None else json.loads(text)


def _cited(r) -> list[dict]:
    """A receipt's `cited` as layer dicts with a `records` list (the imported form holds record ids alone)."""
    cited = _json(r["cited"]) or []
    out = []
    for c in cited:
        if isinstance(c, str):
            out.append({"layer": None, "kind": None, "action": r["action"], "verdict": None, "records": [c]})
        else:
            records = list(c["records"]) if "records" in c else ([c["record"]] if c.get("record") else [])
            out.append({"layer": c["layer"], "kind": c["kind"], "action": c["action"], "verdict": c["verdict"],
                        "records": records})
    return out


def _scope(uses: Uses, state: State, place: str) -> tuple[frozenset, frozenset]:
    """The places P dominates (P itself always), and the copies those places hold."""
    places = frozenset({place} | {q for q in state.places if place in dominators(state, q)})
    copies = frozenset(c for (c,) in uses.conn.execute("SELECT DISTINCT copy FROM uses WHERE copy IS NOT NULL")
                       if holding_place(state, c) in places)
    return places, copies


def _name(person: str) -> str:
    handle = person.split(":", 1)[-1]
    return handle[:1].upper() + handle[1:]


def _short(obj: str | None) -> str:
    return obj.rsplit("/", 1)[-1] if obj else ""


def _kind(r, returned) -> str:
    if r["ledger_id"] and r["copy"] and r["copy"].startswith("imprint:") and r["object"] is None:
        return "memories" if isinstance(returned, dict) and "sha256" in returned else "roads-and-trails"
    obj = r["object"]
    if obj is None:
        return "recall" if isinstance(returned, list) else "bulk"
    return obj.split(":", 1)[0]


def _count_of(r, returned):
    if returned is None:
        return "not counted" if r["object"] is None and r["copy"] and r["copy"].startswith("imprint:") else None
    return len(returned) if isinstance(returned, list) else returned["count"]


def _label(state: State, layer: str) -> str:
    person = person_of_home(layer)
    if person is not None:
        return _name(person)
    return state.names.get(layer, layer)


def _refusal_note(state: State, r, refusal) -> str | None:
    layer, action = refusal.get("layer"), r["action"]
    if layer is None:
        return None
    head = f"{_short(r['object'])}: " if r["object"] else ""
    person = person_of_home(layer)
    if person is not None and person != state.meta.get("owner") and refusal.get("code") == "NO_ALLOW":
        return f"{head}needs {_name(person)}'s yes"
    return f"{head}{_label(state, layer)} does not allow {action}"


def _self_claims(state: State) -> list:
    """(object, "Jenn claimed m3 on 2026-11-03", the time of the claim) for each live self-claimed co-subject."""
    out = []
    for s in state.self_claims:
        if s.added_seq in state.seq_at:
            at, obj = state.seq_at[s.added_seq], s.object
            day = datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%d")
            out.append((obj, f"{_name(s.subject)} claimed {_short(obj)} on {day}", at))
    return out


def _owner_row(state: State, r, subjects, claims, ledger_id: str) -> dict:
    returned = _json(r["returned"])
    refusal = _json(r["refusal"])
    imported = r["ledger_id"] != ledger_id
    notes = []
    if not r["allowed"] and refusal:
        note = _refusal_note(state, r, refusal)
        if note:
            notes.append(note)
    named = {r["object"], *(o for _, o in subjects)} | (set(returned) if isinstance(returned, list) else set())
    notes += [text for obj, text, at in claims if obj in named and r["at"] >= at]
    row = {"id": r["id"], "at": r["at"], "agent": r["agent"], "place": r["place"], "acting_for": r["acting_for"],
           "action": r["action"], "purpose": r["purpose"], "object": r["object"], "copy": r["copy"],
           "allowed": bool(r["allowed"]), "outcome": "allowed" if r["allowed"] else "refused",
           "cited": _cited(r), "refusal": refusal, "until": r["until"], "horizon": r["horizon"],
           "kind": _kind(r, returned), "count": _count_of(r, returned), "imported": imported,
           "shadow": bool(r["shadow"]), "notes": notes}
    if imported:
        row["station"] = r["ledger_id"]
    return row


def _steward_row(r, subjects, salt: bytes, ledger_id: str) -> dict:
    def shield(layer, kind=None):
        if layer is None:
            return None
        if kind in ("legacy", "restriction"):
            return kind
        person = person_of_home(layer)
        return pseudonym(salt, person) if person is not None else layer

    cited = _cited(r)
    kinds = {c["layer"]: c["kind"] for c in cited}
    refusal = _json(r["refusal"])
    if refusal:
        layer = refusal.get("layer")
        kind = kinds.get(layer) or ("restriction" if layer and layer.startswith("agent:")
                                    else "legacy" if layer and ":" not in layer else None)
        refusal = {"code": refusal["code"], "layer": shield(layer, kind), "action": refusal["action"]}
    returned = _json(r["returned"])
    row = {"id": r["id"], "at": r["at"], "requester": r["agent"], "place": shield(r["place"]),
           "action": r["action"], "purpose": r["purpose"], "allowed": bool(r["allowed"]),
           "outcome": "allowed" if r["allowed"] else "refused",
           "cited": [{"layer": shield(c["layer"], c["kind"]), "action": c["action"], "verdict": c["verdict"],
                      "records": c["records"] if (c["layer"] or "").startswith("place:")
                      and person_of_home(c["layer"]) is None else []} for c in cited],
           "refusal": refusal, "subjects": sorted({pseudonym(salt, s) for s, _ in subjects if s.startswith("person:")}),
           "count": _count_of(r, returned), "imported": r["ledger_id"] != ledger_id}
    if row["imported"]:
        row["station"] = r["ledger_id"]
    if r["filtered"] is not None:
        row["filtered"] = r["filtered"]
    return row
