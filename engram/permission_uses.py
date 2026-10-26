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
import json
import os
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from lighthouse_protocol import canonical_json
from permissions import BulkUse, Decision, RETENTION_DAYS, Use

ZERO = "0" * 64
BUSY_MS = 5000

_SCHEMA = (
    """CREATE TABLE uses(seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, at INTEGER NOT NULL, ledger_id TEXT NOT NULL,
  ledger_seq INTEGER NOT NULL, agent TEXT NOT NULL, place TEXT NOT NULL, acting_for TEXT NOT NULL, session_label TEXT,
  action TEXT NOT NULL, purpose TEXT NOT NULL, object TEXT, copy TEXT, allowed INTEGER NOT NULL, cited TEXT NOT NULL,
  refusal TEXT, until INTEGER, horizon INTEGER, returned TEXT, filtered INTEGER, content_digest TEXT,
  shadow INTEGER NOT NULL DEFAULT 0, prev_digest TEXT NOT NULL, digest TEXT NOT NULL)""",
    """CREATE TABLE use_subjects(use_seq INTEGER NOT NULL, subject TEXT NOT NULL, object TEXT NOT NULL)""",
    """CREATE TABLE uses_anchor(through_seq INTEGER PRIMARY KEY, digest TEXT NOT NULL)""",
    """CREATE TABLE uses_monthly(month TEXT NOT NULL, subject TEXT NOT NULL, place TEXT NOT NULL, action TEXT NOT NULL,
  purpose TEXT NOT NULL, outcome TEXT NOT NULL, n INTEGER NOT NULL,
  PRIMARY KEY(month, subject, place, action, purpose, outcome))""",
)


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


def _entry(row) -> dict:
    return {"seq": row["seq"], **{c: row[c] for c in _COLUMNS}}


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
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        except sqlite3.Error as e:
            conn.close()
            raise UsesUnreadable(f"{path}: {e}") from e
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
        rid = row.id or "u-" + os.urandom(16).hex()
        values = {c: getattr(row, c) for c in _COLUMNS}
        values["id"] = rid
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            top, prev = self._tail()
            seq = top + 1
            digest = _digest(prev, {"seq": seq, **values})
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
            if row["seq"] != expect or row["prev_digest"] != prev or row["digest"] != _digest(prev, _entry(row)):
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
        subject rows, and write one anchor holding the last folded seq and digest. Returns how many. A span
        whose chain does not verify is not folded (it would launder the break): ValueError."""
        cutoff = now - RETENTION_DAYS * 86400
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            through, digest = self._anchor()
            old = []
            for row in self.conn.execute("SELECT * FROM uses WHERE seq > ? ORDER BY seq", (through,)):
                if row["at"] >= cutoff:
                    break
                old.append(row)
            if not old:
                self.conn.execute("COMMIT")
                return 0
            broken = self._check(old, digest, through + 1)
            if broken is not None:
                raise ValueError(f"the receipts chain breaks at seq {broken}; nothing was folded")
            last = old[-1]
            for row in old:
                month = datetime.fromtimestamp(row["at"], timezone.utc).strftime("%Y-%m")
                outcome = "allowed" if row["allowed"] else "refused"
                subjects = {s[0] for s in self.conn.execute(
                    "SELECT subject FROM use_subjects WHERE use_seq=?", (row["seq"],))}
                for subject in sorted(subjects):
                    self.conn.execute(
                        "INSERT INTO uses_monthly VALUES(?,?,?,?,?,?,1) ON CONFLICT(month, subject, place, action, "
                        "purpose, outcome) DO UPDATE SET n = n + 1",
                        (month, subject, row["place"], row["action"], row["purpose"], outcome))
            self.conn.execute("DELETE FROM use_subjects WHERE use_seq <= ?", (last["seq"],))
            self.conn.execute("DELETE FROM uses WHERE seq <= ?", (last["seq"],))
            self.conn.execute("INSERT INTO uses_anchor VALUES(?,?)", (last["seq"], last["digest"]))
            self.conn.execute("COMMIT")
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise
        return len(old)
