"""Fixtures for the store-copy (imprint) tests.

Nothing here opens a stamped file with ``Storage(path)``: writers use
``sqlite3`` with ``sqlite_vec`` and readers use ``store_reader.connect`` or
``Storage.open_read_only`` (an imprint refuses a writable open).
"""
import sqlite3
import uuid
from pathlib import Path

import store_identity
import store_reader
from storage import Storage
from tests.permissions_support import T  # noqa: F401  (re-exported)
from tests.test_store_identity import build_schema27_store

GENOME_PARENT = "3f2b8c1e-5a4d-4e6f-9b7a-1c2d3e4f5a6b"


def _path(tmp_path: Path, name: str) -> Path:
    return tmp_path / f"{name}.db"


def new_store(tmp_path: Path, name: str) -> Storage:
    return Storage(str(_path(tmp_path, name)))


def retro_store(tmp_path: Path, name: str, first: tuple[str, str]) -> Storage:
    """A store older than identity: a schema-27 file with one episode, then migrated."""
    path = _path(tmp_path, name)
    (tmp_path / f"{name}-mig").mkdir()
    build_schema27_store(path, tmp_path / f"{name}-mig", [first])
    return Storage(str(path))


def unidentified_store(tmp_path: Path, name: str) -> sqlite3.Connection:
    """A read-only connection to a store holding no identity keys."""
    path = _path(tmp_path, name)
    s = Storage(str(path))
    s.conn.execute(
        f"DELETE FROM meta WHERE key IN ({', '.join('?' * len(store_identity.KEYS))})",
        store_identity.KEYS)
    s.conn.commit()
    s.close()
    return store_reader.connect(path)


def _writable(path: Path) -> sqlite3.Connection:
    import sqlite_vec

    conn = sqlite3.connect(str(path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _backup(store: Storage, path: Path) -> sqlite3.Connection:
    store.conn.commit()
    dst = _writable(path)
    store.conn.backup(dst)
    return dst


def fork_of(tmp_path: Path, parent: Storage, name: str) -> Storage:
    path = _path(tmp_path, name)
    dst = _backup(parent, path)
    try:
        store_identity.stamp_fork(dst, store_identity.effective_id(parent.conn),
                                  *store_identity.ancestry(parent.conn))
        dst.commit()
    finally:
        dst.close()
    return Storage(str(path))


def old_fork_of(tmp_path: Path, parent: Storage, name: str) -> Storage:
    """A fork made before ancestry existed: the two ancestry keys are gone."""
    path = _path(tmp_path, name)
    dst = _backup(parent, path)
    try:
        store_identity.stamp_fork(dst, store_identity.effective_id(parent.conn))
        dst.execute("DELETE FROM meta WHERE key IN ('ancestry', 'ancestry_complete')")
        dst.commit()
    finally:
        dst.close()
    return Storage(str(path))


def imprint_of(tmp_path: Path, parent: Storage, name: str) -> Storage:
    path = _path(tmp_path, name)
    dst = _backup(parent, path)
    try:
        store_identity.stamp_imprint(
            dst, store_identity.effective_id(parent.conn),
            *store_identity.ancestry(parent.conn), str(uuid.uuid4()))
        dst.commit()
        dst.execute("PRAGMA journal_mode=DELETE")
    finally:
        dst.close()
    return Storage.open_read_only(path)


def file_copy(tmp_path: Path, store: Storage, name: str) -> Storage:
    """A copy of the file: same identity, same bytes' meaning (backup API, so WAL pages come too)."""
    path = _path(tmp_path, name)
    _backup(store, path).close()
    return Storage(str(path))


def iid(store: Storage) -> str:
    return store_identity.read(store.conn)["instance_id"]


def iid_of(path: Path) -> str:
    conn = store_reader.connect(path)
    try:
        return store_identity.read(conn)["instance_id"]
    finally:
        conn.close()


def genome_with_parent(tmp_path: Path) -> Path:
    """An engram dir whose genome was forked (by stamp_fork) from a store with id GENOME_PARENT."""
    engram_dir = tmp_path / "engram"
    (engram_dir / "genome").mkdir(parents=True)
    genome = Storage(str(engram_dir / "genome" / "graph.db"))
    try:
        store_identity.stamp_fork(genome.conn, GENOME_PARENT)
        genome.conn.commit()
    finally:
        genome.close()
    return engram_dir
