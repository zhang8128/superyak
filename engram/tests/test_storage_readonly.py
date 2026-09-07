from __future__ import annotations

import hashlib
import sqlite3
import uuid
from pathlib import Path

import pytest

from storage import ReadOnlyStorageError, Storage


def unit(seed: int, dim: int = 768) -> list[float]:
    vec = [0.0] * dim
    vec[seed % dim] = 1.0
    return vec


def build_store(path: Path) -> None:
    store = Storage(str(path))
    store.add_episode(
        str(uuid.uuid4()),
        "s",
        "work fact about rivers",
        embedding=unit(1),
        lane="work",
    )
    store.add_episode(
        str(uuid.uuid4()),
        "s",
        "personal fact about rivers",
        embedding=unit(2),
        lane="personal",
    )
    store.close()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_open_read_only_serves_vector_search_without_changes(tmp_path):
    """Hash graph.db only; read-only access may touch WAL side files."""
    db = tmp_path / "graph.db"
    build_store(db)
    before = sha(db)

    ro = Storage.open_read_only(db)
    hits = ro.search_vectors("episode", unit(1), k=2)

    assert ro.read_only is True
    assert len(hits) == 2
    assert ro.conn.total_changes == 0
    assert sha(db) == before
    ro.close()


def test_open_read_only_refuses_mutation(tmp_path):
    db = tmp_path / "graph.db"
    build_store(db)
    ro = Storage.open_read_only(db)

    with pytest.raises(ReadOnlyStorageError):
        with ro.transaction():
            pass
    with pytest.raises((ReadOnlyStorageError, sqlite3.OperationalError)):
        ro.add_log_entry(str(uuid.uuid4()), "recall", "all", [], context={})
    ro.close()


def test_open_read_only_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Storage.open_read_only(tmp_path / "absent.db")


def test_open_read_only_works_when_wal_side_files_are_absent(tmp_path):
    """Python sqlite3 can read a closed WAL store without side files."""
    db = tmp_path / "graph.db"
    build_store(db)
    for suffix in ("-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)

    ro = Storage.open_read_only(db)
    assert ro.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert ro.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 2
    assert len(ro.search_vectors("episode", unit(1), k=2)) == 2
    ro.close()


def test_normal_storage_is_not_read_only(tmp_path):
    store = Storage(str(tmp_path / "graph.db"))
    assert store.read_only is False
    store.close()
