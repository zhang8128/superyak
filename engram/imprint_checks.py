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
from collections.abc import Container, Iterable, Mapping, Sequence
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
    10: "A reference in the package does not resolve inside it, or a co-subject row is not a valid one.",
    11: "A log row holds something a copy never carries.",
    12: "The package holds something outside the scope and terms the owner allowed.",
    13: "The package's row counts, or the digest of its rows, differ from the manifest's.",
    14: "The package has free pages.",
    15: "A memory table's rowids, or an index's document sizes, are not 1 to n.",
    16: "A full-text index does not equal the one its content table builds.",
    17: "A vector slot is not laid out as the vectors it ships.",
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


# ---- Checks 10 to 17 -----------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class AdmissionTerms:
    """What the signed permission says about the copy (I 8): whether it carries ``route``, whether it stays in the
    owner's home, and who the owner is. The default is the strictest reading: no route, not at home, no owner named."""
    route: bool = False
    at_home: bool = False
    owner: str | None = None


NO_TERMS = AdmissionTerms()
_AT_HOME = "others-copied-at-home-v1"


def terms_of(permission: Mapping) -> AdmissionTerms:
    """The terms of a verified ``permission.json``: the station writes ``owner`` as ``person:<handle>``, the
    attestation from the audience and owner, and r_T (an ``actions`` list with ``route``) exactly with ``route``."""
    record = permission["record"]
    owner = record["owner"]
    return AdmissionTerms(
        route=any("route" in r["selector"]["actions"] for r in record["records"]),
        at_home=record["attestation"] == _AT_HOME,
        owner=owner[len("person:"):] if isinstance(owner, str) and owner.startswith("person:") else owner)


_MEMORY_TABLES = {"episode": "episodes", "semantic": "semantics"}
_NOT_IN_PACKAGE = ("NOT EXISTS (SELECT 1 FROM episodes WHERE id = {v}) AND "
                   "NOT EXISTS (SELECT 1 FROM semantics WHERE id = {v})")


def _none(conn: sqlite3.Connection, sql: str, *args) -> bool:
    """Whether a query that selects the offenders returns no row."""
    return conn.execute(sql, args).fetchone() is None


def _references_resolve(conn: sqlite3.Connection) -> bool:
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        return False
    out_e, out_s = (f"NOT EXISTS (SELECT 1 FROM {t} WHERE id = {{v}})" for t in ("episodes", "semantics"))
    queries = [
        # a vector row is a row of its base table (the vec0 table's _rowids shadow holds its ids)
        f"SELECT 1 FROM episode_vectors_rowids r WHERE {out_e.format(v='r.id')}",
        f"SELECT 1 FROM semantic_vectors_rowids r WHERE {out_s.format(v='r.id')}",
        f"SELECT 1 FROM semantic_peers p WHERE {out_s.format(v='p.peer_id')} OR {out_s.format(v='p.parent_id')}",
        f"SELECT 1 FROM subdivision_events e WHERE {out_s.format(v='e.parent_id')}",
        f"SELECT 1 FROM subdivision_events e, json_each(e.peer_ids) j WHERE {out_s.format(v='j.value')}",
        # a resonance's two ends: the memory under its layer
        "SELECT 1 FROM resonances r WHERE r.layer_a NOT IN ('episode', 'semantic') OR r.layer_b NOT IN ('episode', 'semantic')",
        f"SELECT 1 FROM resonances r WHERE (r.layer_a = 'episode' AND {out_e.format(v='r.memory_a')}) "
        f"OR (r.layer_a = 'semantic' AND {out_s.format(v='r.memory_a')})",
        f"SELECT 1 FROM resonances r WHERE (r.layer_b = 'episode' AND {out_e.format(v='r.memory_b')}) "
        f"OR (r.layer_b = 'semantic' AND {out_s.format(v='r.memory_b')})",
        # the log rows' targets, an instinct's id among them
        f"SELECT 1 FROM memory_log l, json_each(l.target_ids) j WHERE {_NOT_IN_PACKAGE.format(v='j.value')}",
        f"SELECT 1 FROM operation_log l, json_each(l.target_ids) j WHERE {_NOT_IN_PACKAGE.format(v='j.value')}",
        # a co-subject row names a memory of the package in its layer
        "SELECT 1 FROM imprint_subjects s WHERE s.layer NOT IN ('episode', 'semantic')",
        f"SELECT 1 FROM imprint_subjects s WHERE (s.layer = 'episode' AND {out_e.format(v='s.memory_id')}) "
        f"OR (s.layer = 'semantic' AND {out_s.format(v='s.memory_id')})",
    ]
    return all(_none(conn, q) for q in queries)


def _subject_ok(subject: str, owner: str | None) -> bool:
    from permissions import RuleError, check_id

    if not isinstance(subject, str) or (owner is not None and subject == f"person:{owner}"):
        return False
    try:
        check_id("person" if subject.startswith("person:") else "place", subject)
    except RuleError:
        return False
    return subject.startswith(("person:", "place:"))


def check_10(conn: sqlite3.Connection, manifest: dict, terms: AdmissionTerms = NO_TERMS) -> str | None:
    """References resolve inside the package, and every ``imprint_subjects`` row is a valid co-subject (I 10, 10)."""
    ok = _references_resolve(conn) and all(
        _subject_ok(subject, terms.owner) for (subject,) in conn.execute("SELECT subject FROM imprint_subjects"))
    return None if ok else CHECK_MESSAGES[10]


_RECALL_KEYS = frozenset({"recall_id", "session_id"})
_ROUTE_KEYS = frozenset({"receipt_id", "session_id", "tool", "lane"})
_RECALL_OUTCOMES = (None, "used", "not_used", "used: auto: cited")


_OUTSIDE_SQL = ("SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM episodes WHERE id = ?1) AND "
                "NOT EXISTS (SELECT 1 FROM semantics WHERE id = ?1)")


def _targets_ok(conn: sqlite3.Connection, text) -> bool:
    try:
        targets = json.loads(text)
    except (TypeError, ValueError):
        return False
    if not (isinstance(targets, list) and targets and all(isinstance(t, str) for t in targets)):
        return False
    return all(conn.execute(_OUTSIDE_SQL, (t,)).fetchone() is None for t in targets)


def _log_row_ok(conn: sqlite3.Connection, lanes: Container[str], event, target_ids, context, outcome) -> bool:
    try:
        keys = json.loads(context)
    except (TypeError, ValueError):
        return False
    if not isinstance(keys, dict) or not _targets_ok(conn, target_ids):
        return False
    if event == "recall":
        return set(keys) <= _RECALL_KEYS and outcome in _RECALL_OUTCOMES
    if event == "route_shown":
        return set(keys) <= _ROUTE_KEYS and keys.get("lane") in lanes and outcome is None
    return False


def check_11(conn: sqlite3.Connection, manifest: dict) -> str | None:
    """The scrubs of I 6.2 hold for ``memory_log`` and ``operation_log`` (I 10, 11)."""
    from imprint_filter import CITING_OPERATIONS

    lanes = frozenset(manifest["scope"]["lanes"])
    for event, target_ids, context, outcome in conn.execute(
            "SELECT event_type, target_ids, context, outcome FROM memory_log"):
        if not _log_row_ok(conn, lanes, event, target_ids, context, outcome):
            return CHECK_MESSAGES[11]
    for operation, harness, model, repo, details, target_ids in conn.execute(
            "SELECT operation, harness, model, repo, details, target_ids FROM operation_log"):
        if (operation not in CITING_OPERATIONS or harness is not None or model is not None or repo is not None
                or details != "{}" or not _targets_ok(conn, target_ids)):
            return CHECK_MESSAGES[11]
    return None


def _inside(at, t0, t1) -> bool:
    from imprint_filter import parse_instant

    when = parse_instant(at)
    return when is not None and (t0 is None or when >= t0) and when < t1


def check_12(conn: sqlite3.Connection, manifest: dict, terms: AdmissionTerms = NO_TERMS) -> str | None:
    """Scope holds (I 10, 12): lanes, times, the layers chosen, D7's rule without ``route``, and no co-subject row
    when the copy is not in the owner's home."""
    from imprint_filter import parse_instant

    scope = manifest["scope"]
    lanes, layers = frozenset(scope["lanes"]), frozenset(scope["layers"])
    t0 = None if scope["since"] is None else parse_instant(scope["since"])
    t1 = parse_instant(scope["until"])
    if t1 is None or (scope["since"] is not None and t0 is None):
        return CHECK_MESSAGES[12]
    empty = ["instincts", "instinct_vectors", "instinct_context_vectors"]
    for layer, table in _MEMORY_TABLES.items():
        if layer not in layers:
            empty += [table, f"{layer}_vectors", "semantic_sources"]
    if "semantic" not in layers:
        empty += ["semantic_peers", "subdivision_events"]
    if not terms.route:
        empty += ["memory_log", "operation_log"]
    if not terms.at_home:
        empty.append("imprint_subjects")
    if not all(_none(conn, f"SELECT 1 FROM {_q(t)} LIMIT 1") for t in empty):
        return CHECK_MESSAGES[12]
    if not terms.route and not _none(conn, "SELECT 1 FROM episodes WHERE session_id IS NOT NULL LIMIT 1"):
        return CHECK_MESSAGES[12]
    for layer in set(_MEMORY_TABLES) - layers:
        if not _none(conn, "SELECT 1 FROM resonances WHERE layer_a = ?1 OR layer_b = ?1 LIMIT 1", layer):
            return CHECK_MESSAGES[12]
    if not _none(conn, "SELECT 1 FROM imprint_subjects WHERE layer NOT IN (SELECT value FROM json_each(?)) LIMIT 1",
                 json.dumps(sorted(layers))):
        return CHECK_MESSAGES[12]
    for table in _MEMORY_TABLES.values():
        for lane, created_at in conn.execute(f"SELECT lane, created_at FROM {table}"):
            if lane not in lanes or not _inside(created_at, t0, t1):
                return CHECK_MESSAGES[12]
    for table, column in (("memory_log", "timestamp"), ("operation_log", "timestamp"), ("resonances", "created_at")):
        for (at,) in conn.execute(f"SELECT {column} FROM {table}"):
            if not _inside(at, t0, t1):
                return CHECK_MESSAGES[12]
    return None


def _package_rows(conn: sqlite3.Connection, vectors: dict | None = None) -> Mapping[str, Iterable[dict]]:
    """The eleven digest tables as the package holds them, each read from a new cursor when asked. With ``vectors``
    (``{table: ScratchMap}``), each vector row's SHA-256 is written into its map as the row streams past."""
    from imprint_filter import DIGEST_TABLES, RowSource

    def rows(table: str):
        def make():
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM {_q(table)}")
            names = [d[0] for d in cur.description]
            for values in cur:
                row = dict(zip(names, values))
                if vectors is not None and table in vectors:
                    vectors[table][row["id"]] = hashlib.sha256(row["embedding"]).hexdigest()
                yield row
        return make

    return RowSource({t: rows(t) for t in DIGEST_TABLES})


def check_13(conn: sqlite3.Connection, manifest: dict, *, scratch=None, vectors: dict | None = None) -> str | None:
    """Counts equal ``manifest.contents`` and ``manifest.others``, and the plan digest recomputed from the package's
    rows (I 5.4, with ``scratch`` a ``Scratch`` for its sort) equals ``manifest.plan_digest`` (I 10, 13). With
    ``vectors`` (``{"episode_vectors": ScratchMap, "semantic_vectors": ScratchMap}``) the vector keys are kept for
    check 17 while the digest reads them."""
    from imprint_filter import DIGEST_TABLES, plan_digest

    rows = _package_rows(conn, vectors)
    counts = {}
    for table in DIGEST_TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {_q(table)}").fetchone()[0]
        if n:
            counts[table] = n
    memories, people = conn.execute(
        "SELECT (SELECT COUNT(*) FROM (SELECT DISTINCT memory_id, layer FROM imprint_subjects)), "
        "(SELECT COUNT(DISTINCT subject) FROM imprint_subjects)").fetchone()
    if counts != manifest["contents"] or {"memories": memories, "people": people} != manifest["others"]:
        return CHECK_MESSAGES[13]
    if plan_digest(manifest["scope"], rows, scratch=scratch) != manifest["plan_digest"]:
        return CHECK_MESSAGES[13]
    return None


def check_14(conn: sqlite3.Connection, manifest: dict) -> str | None:
    return None if conn.execute("PRAGMA freelist_count").fetchone()[0] == 0 else CHECK_MESSAGES[14]


def check_15(conn: sqlite3.Connection, manifest: dict) -> str | None:
    """Each memory table's rowids, and each FTS table's ``_docsize`` ids, are exactly 1..n (D33), by count, min and
    max (a rowid is unique, so those three say it)."""
    tables = [(t, "rowid") for t in _MEMORY_TABLES.values()] + [(f"{n}_docsize", "id") for n, _ in _fts_tables(conn)]
    for table, column in tables:
        n, low, high = conn.execute(f"SELECT COUNT(*), MIN({column}), MAX({column}) FROM {_q(table)}").fetchone()
        if n and (low != 1 or high != n):
            return CHECK_MESSAGES[15]
    return None


def check_16(conn: sqlite3.Connection, manifest: dict, scratch: Path) -> str | None:
    """FTS index equality, L2 (I 6.4). L2 makes one temporary ``fts5vocab`` table in the connection's temp schema,
    which ``query_only`` forbids; the file itself stays ``mode=ro&immutable=1``, so it is lifted for this check
    alone, with temp files on disk."""
    conn.execute("PRAGMA temp_store = FILE")
    conn.execute("PRAGMA query_only = OFF")
    try:
        failures = l2_fts(conn, scratch)
    finally:
        conn.execute("PRAGMA query_only = ON")
    return None if not failures else CHECK_MESSAGES[16]


def check_17(conn: sqlite3.Connection, manifest: dict, vectors: Mapping[str, Mapping[str, str]] | None = None) -> str | None:
    """vec0 slots, L3 (I 6.4), against the plan digest's vector keys when ``check_13`` kept them."""
    return None if not l3_vec0(conn, vectors) else CHECK_MESSAGES[17]


def verify(imprint_dir: Path, *, verify_cmd: Sequence[str], migrations_dir: Path, scratch: Path) -> CheckFailure | None:
    """I 10's 17 checks in order, stopping at the first failure. ``imprint.db`` is opened ``mode=ro&immutable=1``
    with sqlite-vec loaded, and every check reads rows from cursors. ``scratch`` is ``<id>.state/scratch/`` in
    admission: check 7's reference file, check 13's sort and vector keys, and check 16's side files go there and are
    removed before this returns. A file that cannot be read as the check expects counts as that check's failure."""
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
        terms = terms_of(_load_json(folder / "permission.json"))
    except (OSError, ValueError, KeyError, TypeError):
        return _fail(3)
    try:
        if not _check_4(db):
            return _fail(4)
    except OSError:
        return _fail(4)
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    from imprint_filter import Scratch, ScratchMap

    conn = store_reader.connect(db, immutable=True, vec=True)
    digest_file, vector_file = scratch / "digest.db", scratch / "vectors.db"
    sorter = keys = None
    try:
        sorter, keys = Scratch(digest_file), Scratch(vector_file)
        vectors = {t: ScratchMap(keys) for t in ("episode_vectors", "semantic_vectors")}
        for step, run in (
                (5, lambda: _check_5(conn)), (6, lambda: _check_6(conn, manifest)),
                (7, lambda: _check_7(conn, manifest, migrations_dir, scratch)),
                (8, lambda: _check_8(conn, manifest)), (9, lambda: _check_9(conn)),
                (10, lambda: check_10(conn, manifest, terms) is None), (11, lambda: check_11(conn, manifest) is None),
                (12, lambda: check_12(conn, manifest, terms) is None),
                (13, lambda: check_13(conn, manifest, scratch=sorter, vectors=vectors) is None),
                (14, lambda: check_14(conn, manifest) is None), (15, lambda: check_15(conn, manifest) is None),
                (16, lambda: check_16(conn, manifest, scratch / "l2") is None),
                (17, lambda: check_17(conn, manifest, vectors) is None)):
            try:
                if not run():
                    return _fail(step)
            except (sqlite3.DatabaseError, KeyError, TypeError, ValueError):
                return _fail(step)
        return None
    finally:
        conn.close()
        for scratch_file, handle in ((digest_file, sorter), (vector_file, keys)):
            if handle is not None:
                handle.close()
            for suffix in ("", "-journal", "-wal", "-shm"):
                Path(str(scratch_file) + suffix).unlink(missing_ok=True)
        shutil.rmtree(scratch / "l2", ignore_errors=True)
