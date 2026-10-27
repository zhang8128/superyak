"""The leak checks L1 to L4 on a finished package (store-copy spec I 6.4, D34, D42).

Each check returns a list of failure lines; an empty list is a pass. A line names the table, the column or the slot
and never a value. Every check streams: L1 reads one row at a time, L2 compares two cursors, L3 reads one chunk at
a time and L4 reads 1 MiB at a time, so no store is held in memory.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Container, Mapping
from pathlib import Path

UUID_TOKEN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", re.IGNORECASE)
_UUID_BYTES = re.compile(UUID_TOKEN.pattern.encode(), re.IGNORECASE)

RAW_CHUNK = 2**20           # L4 reads this many bytes at a time
RAW_OVERLAP = 35            # a UUID is 36 bytes, so a token cut by a chunk edge has at most 35 on one side
MAX_LINES = 20              # a check stops listing a kind of failure after this many lines


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _tables(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return [(r[0], r[1] or "") for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")]


def _scan(text: str, x_star: Container[str]) -> bool:
    return any(m.group(0).lower() in x_star for m in UUID_TOKEN.finditer(text))


def l1_values(conn: sqlite3.Connection, x_star: Container[str]) -> list[str]:
    """Every value of every ordinary table (shadow tables, ``sqlite_sequence`` and ``meta`` included), one row at a
    time: TEXT as it is, BLOB as Latin-1. A UUID token in ``x_star`` is a failure naming the table and column."""
    failures: list[str] = []
    for table, sql in _tables(conn):
        if sql.lstrip().upper().startswith("CREATE VIRTUAL"):
            continue            # read through its shadow tables
        hit: set[str] = set()
        cursor = conn.execute(f"SELECT * FROM {_q(table)}")
        columns = [d[0] for d in cursor.description]
        for row in cursor:
            for column, value in zip(columns, row):
                if column in hit:
                    continue
                if isinstance(value, bytes):
                    value = value.decode("latin-1")
                if isinstance(value, str) and _scan(value, x_star):
                    hit.add(column)
        failures.extend(f"L1 {table}.{column}: a value holds the key of a row that stayed home" for column in sorted(hit))
    return failures


def _split_args(text: str) -> list[str]:
    out, depth, quote, cur = [], 0, "", []
    for ch in text:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    out.append("".join(cur).strip())
    return [a for a in out if a]


def _fts_tables(conn: sqlite3.Connection) -> list[tuple[str, list[str]]]:
    found = []
    for name, sql in _tables(conn):
        m = re.match(r"\s*CREATE\s+VIRTUAL\s+TABLE\s+\S+\s+USING\s+fts5\s*\((.*)\)\s*$", sql, re.I | re.S)
        if m:
            found.append((name, _split_args(m.group(1))))
    return found


def _lockstep(a, b):
    """Rows of two cursors side by side; the shorter one is padded with ``None``."""
    sentinel = object()
    ia, ib = iter(a), iter(b)
    while True:
        ra, rb = next(ia, sentinel), next(ib, sentinel)
        if ra is sentinel and rb is sentinel:
            return
        yield (None if ra is sentinel else tuple(ra)), (None if rb is sentinel else tuple(rb))


def _l2_one(conn: sqlite3.Connection, name: str, args: list[str], scratch: Path) -> list[str]:
    from imprint import _batched

    content = rowid_col = None
    kept = []
    for arg in args:
        low = arg.lower().replace(" ", "")
        if low.startswith("content="):
            content = arg.split("=", 1)[1].strip().strip("'\"")
        elif low.startswith("content_rowid="):
            rowid_col = arg.split("=", 1)[1].strip().strip("'\"")
        else:
            kept.append(arg)
    if content is None:
        return [f"L2 {name}: no content table to rebuild the index from"]
    rowid_col = rowid_col or "rowid"
    columns = [r[1] for r in conn.execute(f"PRAGMA table_info({_q(name)})")]
    file = scratch / f"l2-{name}.db"
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(file) + suffix).unlink(missing_ok=True)
    side = sqlite3.connect(str(file))
    vocab = f"l2_vocab_{name}"
    failures: list[str] = []
    try:
        side.execute("PRAGMA temp_store = FILE")
        side.execute(f"CREATE VIRTUAL TABLE rebuilt USING fts5({', '.join(kept)})")
        side.commit()
        select = f"SELECT {_q(rowid_col)}, {', '.join(_q(c) for c in columns)} FROM {_q(content)} ORDER BY {_q(rowid_col)}"
        insert = (f"INSERT INTO rebuilt(rowid, {', '.join(_q(c) for c in columns)}) "
                  f"VALUES ({', '.join('?' * (len(columns) + 1))})")
        for batch in _batched(conn.execute(select)):
            side.executemany(insert, batch)
            side.commit()
        side.execute("CREATE VIRTUAL TABLE rebuilt_vocab USING fts5vocab(rebuilt, 'instance')")
        conn.execute(f"CREATE VIRTUAL TABLE temp.{_q(vocab)} USING fts5vocab(main, {_q(name)}, 'instance')")
        try:
            have = conn.execute(f"SELECT term, doc, col, offset FROM temp.{_q(vocab)}")
            want = side.execute("SELECT term, doc, col, offset FROM rebuilt_vocab")
            for n, (x, y) in enumerate(_lockstep(have, want)):
                if x != y:
                    failures.append(f"L2 {name}: the index differs from one rebuilt from {content} (first at entry {n})")
                    break
        finally:
            conn.execute(f"DROP TABLE temp.{_q(vocab)}")
        try:
            ids = conn.execute(f"SELECT id FROM {_q(name + '_docsize')} ORDER BY id")
            rows = conn.execute(f"SELECT {_q(rowid_col)} FROM {_q(content)} ORDER BY {_q(rowid_col)}")
            if any(x != y for x, y in _lockstep(ids, rows)):
                failures.append(f"L2 {name}: {name}_docsize ids differ from the rowids of {content}")
        except sqlite3.OperationalError:
            failures.append(f"L2 {name}: {name}_docsize cannot be read")
    finally:
        side.close()
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(str(file) + suffix).unlink(missing_ok=True)
    return failures


def l2_fts(conn: sqlite3.Connection, scratch: Path) -> list[str]:
    """Per FTS5 table, an index rebuilt in a scratch file from its content table (same columns and tokenizer, no
    ``content=``), compared entry by entry through ``fts5vocab`` ``instance`` rows, and ``_docsize`` ids against the
    content table's rowids. FTS5's own integrity-check passes an entry with no content row; this does not."""
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    failures: list[str] = []
    for name, args in _fts_tables(conn):
        failures.extend(_l2_one(conn, name, args, scratch))
    return failures


def _vec0_tables(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    found = []
    for name, sql in _tables(conn):
        m = re.search(r"USING\s+vec0\s*\(.*float\[(\d+)\]", sql, re.I | re.S) if sql else None
        if m:
            found.append((name, int(m.group(1))))
    return found


def _base_of(conn: sqlite3.Connection, vec_table: str) -> str | None:
    stem = vec_table[:-len("_vectors")] if vec_table.endswith("_vectors") else vec_table
    names = {n for n, _ in _tables(conn)}
    for guess in (stem + "s", (stem[:-1] + "ies") if stem.endswith("y") else None):
        if guess in names:
            return guess
    return None


def l3_vec0(conn: sqlite3.Connection, expected: Mapping[str, Mapping[str, str]] | None) -> list[str]:
    """Each vec0 table's shadow tables, laid out as sqlite-vec 0.1.7 writes them (I 6.4): valid slots name their
    ``_rowids`` row, invalid slots are zero, every id is a shipped row's, and, with ``expected``, a valid slot's
    SHA-256 is the expected one. One chunk at a time."""
    failures: list[str] = []
    for table, dim in _vec0_tables(conn):
        base = _base_of(conn, table)
        want = None if expected is None else expected.get(table, {})
        mine: list[str] = []

        def fail(text: str) -> None:
            if len(mine) < MAX_LINES:
                mine.append(f"L3 {table}: {text}")

        rows = valid_total = 0
        for rowid, id, chunk_id, offset in conn.execute(f"SELECT rowid, id, chunk_id, chunk_offset FROM {_q(table + '_rowids')}"):
            rows += 1
            if want is not None and id not in want:
                fail("an id is not one the package ships a vector for")
            if base is None or conn.execute(f"SELECT 1 FROM {_q(base)} WHERE id = ?", (id,)).fetchone() is None:
                fail("an id is not a shipped row")
        if want is not None and rows != len(want):
            fail(f"{rows} ids where {len(want)} were expected")
        slot_bytes = 4 * dim
        for chunk_id, size, validity, rowids in conn.execute(
                f"SELECT chunk_id, size, validity, rowids FROM {_q(table + '_chunks')} ORDER BY chunk_id"):
            if size % 8 or len(validity) != size // 8 or len(rowids) != 8 * size:
                fail(f"chunk {chunk_id} has a malformed layout")
                continue
            got = conn.execute(f"SELECT vectors FROM {_q(table + '_vector_chunks00')} WHERE rowid = ?", (chunk_id,)).fetchone()
            if got is None or len(got[0]) != slot_bytes * size:
                fail(f"chunk {chunk_id} has no vector bytes of the right length")
                continue
            vectors = got[0]
            for i in range(size):
                held = int.from_bytes(rowids[8 * i:8 * i + 8], "little", signed=True)
                slot = vectors[slot_bytes * i:slot_bytes * (i + 1)]
                if not validity[i // 8] >> (i % 8) & 1:
                    if held != 0 or slot.count(0) != slot_bytes:
                        fail(f"chunk {chunk_id} slot {i} is invalid and not empty")
                    continue
                valid_total += 1
                named = conn.execute(f"SELECT id, chunk_id, chunk_offset FROM {_q(table + '_rowids')} WHERE rowid = ?", (held,)).fetchone()
                if named is None or named[1] != chunk_id or named[2] != i:
                    fail(f"chunk {chunk_id} slot {i} is valid and no row names it")
                elif want is not None and hashlib.sha256(slot).hexdigest() != want.get(named[0]):
                    fail(f"chunk {chunk_id} slot {i} holds bytes other than the expected embedding")
        if valid_total != rows:
            fail(f"{valid_total} valid slots for {rows} ids")
        failures.extend(mine)
    return failures


def l4_raw(path: Path, x_star: Container[str]) -> list[str]:
    """The file in 1 MiB chunks overlapping by 35 bytes, scanned for UUID tokens in ``x_star`` (an extra check; it
    also reads free space)."""
    failures: list[str] = []
    tail = b""
    offset = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(RAW_CHUNK)
            if not chunk:
                break
            buf = tail + chunk
            base = offset - len(tail)
            for m in _UUID_BYTES.finditer(buf):
                if m.group(0).decode("ascii").lower() in x_star and len(failures) < MAX_LINES:
                    failures.append(f"L4 {Path(path).name}: a key of a row that stayed home is in the bytes at offset {base + m.start()}")
            tail = buf[-RAW_OVERLAP:]
            offset += len(chunk)
    return sorted(set(failures))
