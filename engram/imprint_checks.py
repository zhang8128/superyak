"""The leak checks L1 to L4 on a finished package (store-copy spec I 6.4, D34, D42), and the station's admission
checks 1 to 9 (I 10; ``verify``).

Each check returns a list of failure lines; an empty list is a pass. A line names the table, the column or the slot
and never a value. Every check streams: L1 reads one row at a time, L2 compares two cursors, L3 reads one chunk at
a time and L4 reads 1 MiB at a time, so no store is held in memory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
from collections.abc import Container, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import store_identity
import store_reader

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


# ---- Admission checks (I 10) ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class CheckFailure:
    """The first check that failed: its number (R11) and a fixed sentence that names no value."""
    step: int | str
    message: str


CHECK_MESSAGES: dict[int, str] = {
    1: "The imprint folder does not hold exactly the four files, or one of them is not a plain file.",
    2: "The package's size or SHA-256 differs from the manifest's.",
    3: "The permission does not verify, or it does not agree with the manifest.",
    4: "The package file is not a SQLite database in rollback-journal mode.",
    5: "The package fails SQLite's integrity check.",
    6: "The package's applied migrations are not the manifest's, or include one this engram does not know.",
    7: "The package's schema differs from the one this engram builds. Put the engram code and sqlite-vec on the two "
       "machines on one commit.",
    8: "The package's identity is not the one the manifest describes.",
    9: "A table that never leaves the source holds rows.",
}

PACKAGE_FILES = ("approved.json", "imprint.db", "manifest.json", "permission.json")
_SQLITE_MAGIC = b"SQLite format 3\x00"
VERIFY_SECONDS = 120


def _fail(step: int) -> CheckFailure:
    return CheckFailure(step, CHECK_MESSAGES[step])


def _load_json(path: Path):
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def _check_1(folder: Path) -> bool:
    try:
        names = sorted(os.listdir(folder))
        return names == list(PACKAGE_FILES) and all(stat.S_ISREG(os.lstat(folder / n).st_mode) for n in names)
    except OSError:
        return False


def _check_2(folder: Path, manifest: dict) -> bool:
    package = manifest["package"]
    path = folder / "imprint.db"
    return path.stat().st_size == package["bytes"] and store_reader.sha256_file(path) == package["sha256"]


def _check_3(folder: Path, manifest: dict, verify_cmd: Sequence[str]) -> bool:
    permission = folder / "permission.json"
    try:
        done = subprocess.run([*verify_cmd, "--permission", str(permission)], capture_output=True,
                              timeout=VERIFY_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    if done.returncode != 0:
        return False
    record = _load_json(permission)["record"]
    return (record["request_sha256"] == manifest["request_sha256"] and record["plan_digest"] == manifest["plan_digest"]
            and record["imprint_id"] == manifest["imprint_id"]
            and record["source_instance_id"] == manifest["source"]["instance_id"])


def _check_4(path: Path) -> bool:
    with open(path, "rb") as f:
        head = f.read(100)
    return len(head) == 100 and head[:16] == _SQLITE_MAGIC and head[18] == 1 and head[19] == 1


def _check_5(conn: sqlite3.Connection) -> bool:
    rows = conn.execute("PRAGMA integrity_check(1)")
    first = next(rows, None)
    return first is not None and first[0] == "ok" and next(rows, None) is None


def _check_6(conn: sqlite3.Connection, manifest: dict) -> bool:
    schema = store_reader._schema(conn, store_reader._tables(conn))
    return schema["applied"] == sorted(manifest["schema"]["applied"]) and not schema["unknown"]


def _master(conn: sqlite3.Connection):
    return conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name, tbl_name")


def _reference(scratch: Path, migrations_dir: Path, applied: Sequence[int]) -> Path:
    """The file ``Storage`` builds from an empty one with exactly the applied migrations, plus ``imprint_subjects``."""
    from imprint_filter import IMPRINT_SUBJECTS_DDL
    from storage import Storage

    mine = scratch / "reference-migrations"
    shutil.rmtree(mine, ignore_errors=True)
    mine.mkdir()
    for f in sorted(Path(migrations_dir).iterdir()):
        m = store_reader._MIGRATION.match(f.name)
        if m and int(m.group(1)) in set(applied):
            shutil.copyfile(f, mine / f.name)
    path = scratch / "reference.db"
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    store = Storage(str(path), migrations_dir=str(mine))
    try:
        store.conn.execute(IMPRINT_SUBJECTS_DDL)
        store.conn.commit()
    finally:
        store.close()
    return path


def _check_7(conn: sqlite3.Connection, manifest: dict, migrations_dir: Path, scratch: Path) -> bool:
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    ref_path = _reference(scratch, migrations_dir, manifest["schema"]["applied"])
    ref = store_reader.connect(ref_path, vec=True)
    try:
        if any(x != y for x, y in _lockstep(_master(conn), _master(ref))):
            return False
        for table, _ in _vec0_tables(ref):
            info = f"SELECT key, value FROM {_q(table + '_info')} ORDER BY key"
            if any(x != y for x, y in _lockstep(conn.execute(info), ref.execute(info))):
                return False
        return True
    finally:
        ref.close()
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(str(ref_path) + suffix).unlink(missing_ok=True)
        shutil.rmtree(scratch / "reference-migrations", ignore_errors=True)


def _check_8(conn: sqlite3.Connection, manifest: dict) -> bool:
    """The identity ``stamp_imprint`` derives from ``manifest.source``, stamped into an empty database, equals the
    package's ``meta`` row for row."""
    source = manifest["source"]
    want = sqlite3.connect(":memory:")
    try:
        store_identity.stamp_imprint(want, source["instance_id"], list(source["ancestry"]),
                                     bool(source["ancestry_complete"]), manifest["imprint_id"])
        expected = {k: v for k, v in want.execute("SELECT key, value FROM meta")}
    finally:
        want.close()
    got = {k: v for k, v in conn.execute("SELECT key, value FROM meta")}
    return got == expected


def _check_9(conn: sqlite3.Connection) -> bool:
    from imprint_filter import TABLE_RULES

    present = {name for name, _ in _tables(conn)}
    return all(conn.execute(f"SELECT 1 FROM {_q(t)} LIMIT 1").fetchone() is None
               for t, rule in TABLE_RULES.items() if rule == "dropped" and t in present)


def verify(imprint_dir: Path, *, verify_cmd: Sequence[str], migrations_dir: Path, scratch: Path) -> CheckFailure | None:
    """I 10's checks in order, stopping at the first failure; this is 1 to 9. ``imprint.db`` is opened
    ``mode=ro&immutable=1`` with sqlite-vec loaded, and every check reads rows from cursors. ``scratch`` is
    ``<id>.state/scratch/`` in admission. A file that cannot be read as the check expects counts as that check's
    failure."""
    folder = Path(imprint_dir)
    db = folder / "imprint.db"
    if not _check_1(folder):
        return _fail(1)
    try:
        manifest = _load_json(folder / "manifest.json")
        if not _check_2(folder, manifest):
            return _fail(2)
    except (OSError, ValueError, KeyError, TypeError):
        return _fail(2)
    try:
        if not _check_3(folder, manifest, verify_cmd):
            return _fail(3)
    except (OSError, ValueError, KeyError, TypeError):
        return _fail(3)
    try:
        if not _check_4(db):
            return _fail(4)
    except OSError:
        return _fail(4)
    conn = store_reader.connect(db, immutable=True, vec=True)
    try:
        for step, run in ((5, lambda: _check_5(conn)), (6, lambda: _check_6(conn, manifest)),
                          (7, lambda: _check_7(conn, manifest, migrations_dir, scratch)),
                          (8, lambda: _check_8(conn, manifest)), (9, lambda: _check_9(conn))):
            try:
                if not run():
                    return _fail(step)
            except (sqlite3.DatabaseError, KeyError, TypeError, ValueError):
                return _fail(step)
        return None
    finally:
        conn.close()
