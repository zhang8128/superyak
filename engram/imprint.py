"""Store imprints: copy part of a store, with its owner's permission (store-copy spec I 6, 13).

This module holds the package writer (Task 13). It imports no numpy: ``calibrate`` is imported inside the
functions that need it (P35).
"""
from __future__ import annotations

import itertools
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

import store_identity
from imprint_filter import DIGEST_TABLES, IMPRINT_SUBJECTS_DDL, PackageRows, check_package_tables

BATCH_ROWS = 1000                   # rows per insert batch (D42, I 14)
BATCH_BYTES = 8 * 2**20             # bytes per insert batch; a row alone over it is a batch of one


def _connect(path: Path | str, *, read_only: bool, immutable: bool = False, vec: bool = False) -> sqlite3.Connection:
    """The one place this module opens SQLite (P30). Every connection keeps its temp files on disk."""
    if read_only:
        uri = f"file:{Path(path).resolve()}?mode=ro" + ("&immutable=1" if immutable else "")
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(path))
    if vec:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    conn.execute("PRAGMA temp_store = FILE")
    return conn


def _size(values: tuple) -> int:
    return 16 + sum(len(v) if isinstance(v, (str, bytes)) else 8 for v in values)


def _batched(rows: Iterable[tuple]) -> Iterator[list[tuple]]:
    """Batches of at most ``BATCH_ROWS`` rows or ``BATCH_BYTES`` bytes; a row over the bytes alone is a batch."""
    batch: list[tuple] = []
    size = 0
    for row in rows:
        batch.append(row)
        size += _size(row)
        if len(batch) >= BATCH_ROWS or size >= BATCH_BYTES:
            yield batch
            batch, size = [], 0
    if batch:
        yield batch


def _insert_table(conn: sqlite3.Connection, table: str, rows: Iterable[dict]) -> None:
    """Stream ``rows`` into ``table`` with an explicit column list that never names ``rowid`` (D33), committing
    after each batch."""
    it = iter(rows)
    first = next(it, None)
    if first is None:
        return
    columns = list(first)
    known = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
    extra = [c for c in columns if c not in known or c == "rowid"]
    if extra:
        raise ValueError(f"{table}: no such column(s) in the package: {', '.join(extra)}")
    sql = (f'INSERT INTO "{table}" ({", ".join(chr(34) + c + chr(34) for c in columns)}) '
           f'VALUES ({", ".join("?" * len(columns))})')
    tuples = (tuple(r[c] for c in columns) for r in itertools.chain([first], it))
    for batch in _batched(tuples):
        conn.executemany(sql, batch)
        conn.commit()


def write_package(rows: PackageRows, dest: Path, *, source_id: str, source_ancestry: list[str],
                  source_complete: bool, imprint_id: str) -> None:
    """I 6.1 steps 4 to 7: a fresh file with every migration, the imprint's identity and ``imprint_subjects``;
    the rows of ``rows`` inserted table by table in memory order; then the checks, ``journal_mode=DELETE`` and
    ``VACUUM``. It never writes over an existing file."""
    from storage import Storage

    dest = Path(dest)
    if dest.exists():
        raise FileExistsError(f"{dest} exists; a package is never written over a file")
    store = None
    try:
        store = Storage(str(dest))
        conn = store.conn
        store_identity.stamp_imprint(conn, source_id, source_ancestry, source_complete, imprint_id)
        conn.execute(IMPRINT_SUBJECTS_DDL)
        conn.commit()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("PRAGMA temp_store = FILE")
        source: Mapping = rows.rows
        for table in DIGEST_TABLES:
            _insert_table(conn, table, source[table])
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("the package breaks a foreign key")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("the package fails its integrity check")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("VACUUM")
        if conn.execute("PRAGMA freelist_count").fetchone()[0] != 0:
            raise RuntimeError("the package has free pages after VACUUM")
        store.close()
        store = None
        check = _connect(dest, read_only=True)
        try:
            check_package_tables(check)
        finally:
            check.close()
    except BaseException:
        if store is not None:
            store.close()
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(dest) + suffix).unlink(missing_ok=True)
        raise
