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

# Fixed namespace for retroactive ids. Changing it would change every
# retroactive identity, so it is part of the on-disk contract.
RETROACTIVE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "engram:store-identity:retroactive:v1")

ORIGIN_CREATION = "creation"
ORIGIN_RETROACTIVE = "retroactive"
ORIGIN_FORK = "fork"
BASIS_RANDOM = "random"
BASIS_EARLIEST_EPISODE = "earliest_episode"

KEYS = (
    "instance_id",
    "instance_id_origin",
    "instance_id_basis",
    "instance_id_basis_episode",
    "forked_from_instance_id",
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


def stamp_fork(conn: sqlite3.Connection, forked_from_instance_id: str | None) -> str:
    """Replace a freshly copied store's identity with a new one of its own.

    Does not commit. ``forked_from_instance_id`` may be ``None`` when the
    source had no identity and none could be derived (an empty old store).
    """
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        f"DELETE FROM meta WHERE key IN ({', '.join('?' * len(KEYS))})", KEYS
    )
    new_id = str(uuid.uuid4())
    _write(conn, {
        "instance_id": new_id,
        "instance_id_origin": ORIGIN_FORK,
        "instance_id_basis": BASIS_RANDOM,
        "forked_from_instance_id": forked_from_instance_id,
    })
    return new_id
