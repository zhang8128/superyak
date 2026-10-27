"""Store identity: which store is this, independent of its path or name.

Every store carries ``meta.instance_id`` plus ``meta.instance_id_origin``:

- ``creation``: minted at random when the store was created.
- ``retroactive``: assigned when a store that predates identity was migrated
  (migration 028). With episodes, the id is derived deterministically from the
  earliest episode's ``(id, created_at)``, so two copies of the same old store
  (a pristine snapshot and a working copy) agree without coordinating. An
  empty old store has nothing to derive from and gets a random id.
- ``fork``: minted at random by ``cli.py fork``, which also records
  ``forked_from_instance_id``: a fork is a different store from the moment
  it exists.

``meta.instance_id_basis`` says whether an id is ``random`` or derived from
the ``earliest_episode``; a derived id also keeps ``instance_id_basis_episode``
(JSON ``{"id", "created_at"}``), so it stays verifiable after that episode is
pruned to cold storage.

Everything here takes a plain ``sqlite3`` connection. The read functions never
write, so read-only paths (``store_reader``, ``calibrate`` on SOURCE) can report
what a store is, or would become, without touching it. Only ``assign`` and
``stamp_fork`` write, and only the migration runner and ``cli.py fork`` call
them.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import NamedTuple

# Fixed namespace for retroactive ids. Changing it would change every
# retroactive identity, so it is part of the on-disk contract.
RETROACTIVE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "engram:store-identity:retroactive:v1")

ORIGIN_CREATION = "creation"
ORIGIN_RETROACTIVE = "retroactive"
ORIGIN_FORK = "fork"
ORIGIN_IMPRINT = "imprint"
MAX_ANCESTRY = 64
BASIS_RANDOM = "random"
BASIS_EARLIEST_EPISODE = "earliest_episode"

KEYS = (
    "instance_id",
    "instance_id_origin",
    "instance_id_basis",
    "instance_id_basis_episode",
    "forked_from_instance_id",
    "ancestry",
    "ancestry_complete",
)


def derive_retroactive_id(episode_id: str, created_at: str) -> str:
    """The deterministic id of an old store whose earliest episode is given."""
    return str(uuid.uuid5(RETROACTIVE_NAMESPACE, f"{episode_id}\x1f{created_at}"))


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def earliest_episode(conn: sqlite3.Connection) -> tuple[str, str] | None:
    """``(id, created_at)`` of the first episode in reading order, if any."""
    if not _has_table(conn, "episodes"):
        return None
    row = conn.execute(
        "SELECT id, created_at FROM episodes ORDER BY created_at, id LIMIT 1"
    ).fetchone()
    return (row[0], row[1]) if row is not None else None


def read(conn: sqlite3.Connection) -> dict:
    """The identity keys stored in ``meta`` (empty when there are none)."""
    if not _has_table(conn, "meta"):
        return {}
    placeholders = ", ".join("?" * len(KEYS))
    rows = conn.execute(
        f"SELECT key, value FROM meta WHERE key IN ({placeholders})", KEYS
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def plan(conn: sqlite3.Connection, fresh: bool = False) -> dict:
    """The identity a store would be given now, without writing anything.

    ``instance_id`` is ``None`` when the id would be random, since a random id
    cannot be predicted.
    """
    if fresh:
        return {"instance_id": None, "instance_id_origin": ORIGIN_CREATION,
                "instance_id_basis": BASIS_RANDOM}
    first = earliest_episode(conn)
    if first is None:
        return {"instance_id": None, "instance_id_origin": ORIGIN_RETROACTIVE,
                "instance_id_basis": BASIS_RANDOM}
    return {
        "instance_id": derive_retroactive_id(*first),
        "instance_id_origin": ORIGIN_RETROACTIVE,
        "instance_id_basis": BASIS_EARLIEST_EPISODE,
        "instance_id_basis_episode": json.dumps({"id": first[0], "created_at": first[1]}),
    }


def describe(conn: sqlite3.Connection) -> dict:
    """Read-only report: the stored identity, or the one migration would assign."""
    stored = read(conn)
    if stored.get("instance_id"):
        return {"status": "present", **stored}
    return {"status": "absent", "would_assign": plan(conn)}


def effective_id(conn: sqlite3.Connection) -> str | None:
    """The stored id, else the deterministic one migration will assign, else None."""
    stored = read(conn).get("instance_id")
    return stored or plan(conn)["instance_id"]


def _write(conn: sqlite3.Connection, values: dict) -> None:
    conn.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [(k, v) for k, v in values.items() if v is not None],
    )


def assign(conn: sqlite3.Connection, fresh: bool) -> dict:
    """Give the store an identity if it has none; never replace an existing one.

    Runs inside the migration's transaction and does not commit. ``fresh``
    means the store was created by this open (no migration had been applied).
    """
    stored = read(conn)
    if stored.get("instance_id"):
        return stored
    values = plan(conn, fresh=fresh)
    if values["instance_id"] is None:
        values["instance_id"] = str(uuid.uuid4())
    _write(conn, values)
    return values


class ImprintRefused(RuntimeError):
    """An imprint is read-only evidence: it is never opened for writing."""


def is_imprint(conn: sqlite3.Connection) -> bool:
    return read(conn).get("instance_id_origin") == ORIGIN_IMPRINT


def ancestry(conn: sqlite3.Connection) -> tuple[list[str], bool]:
    """``(ids nearest first, complete)``. Reads only; a malformed value is incomplete."""
    stored = read(conn)
    raw = stored.get("ancestry")
    if raw is not None:
        try:
            ids = json.loads(raw)
        except (TypeError, ValueError):
            return [], False
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            return [], False
        return [i.lower() for i in ids], stored.get("ancestry_complete") == "true"
    parent = stored.get("forked_from_instance_id")
    if parent:
        return [parent.lower()], False
    if stored.get("instance_id_origin") == ORIGIN_CREATION:
        return [], True
    return [], False


class Lineage(NamedTuple):
    ids: frozenset[str]
    complete: bool


def lineage(conn: sqlite3.Connection) -> Lineage:
    own = effective_id(conn)
    ids, complete = ancestry(conn)
    members = {i.lower() for i in ids}
    if own:
        members.add(own.lower())
    return Lineage(frozenset(members), bool(complete and own))


def independent(a: Lineage, b: Lineage) -> bool | None:
    """False when the two share an id, True when disjoint and both complete, else None."""
    if a.ids & b.ids:
        return False
    return True if a.complete and b.complete else None


def _child_ancestry(parent: str | None, source_ancestry: list[str] | None,
                    source_complete: bool) -> tuple[list[str], bool]:
    chain = ([parent] if parent else []) + list(source_ancestry or [])
    ids: list[str] = []
    for i in chain:
        i = i.lower()
        if i not in ids:
            ids.append(i)
    cut = len(ids) > MAX_ANCESTRY
    return ids[:MAX_ANCESTRY], bool(source_complete and parent and not cut)


def _stamp(conn: sqlite3.Connection, origin: str, new_id: str, parent: str | None,
           source_ancestry: list[str] | None, source_complete: bool) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(f"DELETE FROM meta WHERE key IN ({', '.join('?' * len(KEYS))})", KEYS)
    ids, complete = _child_ancestry(parent, source_ancestry, source_complete)
    _write(conn, {
        "instance_id": new_id,
        "instance_id_origin": origin,
        "instance_id_basis": BASIS_RANDOM,
        "forked_from_instance_id": parent,
        "ancestry": json.dumps(ids, separators=(",", ":")),
        "ancestry_complete": "true" if complete else "false",
    })


def stamp_fork(conn: sqlite3.Connection, forked_from_instance_id: str | None,
               source_ancestry: list[str] | None = None, source_complete: bool = False) -> str:
    """Replace a freshly copied store's identity with a new one of its own.

    Does not commit. ``forked_from_instance_id`` may be ``None`` when the
    source had no identity and none could be derived (an empty old store).
    """
    new_id = str(uuid.uuid4())
    _stamp(conn, ORIGIN_FORK, new_id, forked_from_instance_id, source_ancestry, source_complete)
    return new_id


def stamp_imprint(conn: sqlite3.Connection, source_instance_id: str, source_ancestry: list[str],
                  source_complete: bool, imprint_id: str) -> None:
    """Give a freshly copied store the identity of an imprint of the source. Does not commit."""
    if not source_instance_id:
        raise ValueError("an imprint needs the source's instance id")
    _stamp(conn, ORIGIN_IMPRINT, imprint_id, source_instance_id, source_ancestry, source_complete)
