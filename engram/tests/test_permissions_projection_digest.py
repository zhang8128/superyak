"""The permission ledger's projection digest (docs/superpowers/plans/2026-11-03-projection-digest.md): each test names
its task and the decision it pins."""
import dataclasses
import hashlib
import json
import multiprocessing
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import permission_ledger
from lighthouse_protocol import canonical_json
from permission_cli import main as cli_main
from permission_ledger import (SCHEMA_VERSION, Gate, Ledger, LedgerUnreadable, effective_gate, houses, ledger_path,
                               projection_now)
from permissions import _COLUMNS, RuleError
from tests.permissions_support import (  # noqa: F401
    ANDY, M2, M3, MEDICAL, T, cli_home, cli_home_with_house, do, e1_county_ledger, fake_tty, make_house, raise_gate,
    raised_ledger)
from tests.permissions_memory_support import digest_shape, digest_timings
from tests.test_permissions_premerge_fixes import _tear_index


# ---------------------------------------------------------------- Task 0b: what this Python gives the key read

def test_0b_the_key_read_has_pread_and_cloexec_and_needs_no_sqlite_dbpage(tmp_path):
    """D4: the change counter and the journal bytes are read with `os.pread` on a descriptor opened `O_RDONLY |
    O_CLOEXEC`, never with `open()`. This runs wherever the suite runs (Tardis, the Pi, the Mac), so each machine's
    Engram Python says it has both. `sqlite_dbpage` is not relied on: it is missing from the Engram venv's SQLite on
    Tardis (3.53.1), though the system Python's 3.46.1 has it."""
    assert hasattr(os, "pread") and hasattr(os, "O_CLOEXEC")
    Ledger._blank(tmp_path, "ledger-0b").close()
    fd = os.open(ledger_path(tmp_path), os.O_RDONLY | os.O_CLOEXEC)
    try:
        header = os.pread(fd, 100, 0)
        assert header[:16] == b"SQLite format 3\x00"
        assert header[18:20] == b"\x01\x01"                # a rollback journal: the file format bytes D4 pins
        assert os.get_inheritable(fd) is False
    finally:
        os.close(fd)


# ---------------------------------------------------------------- Task 1: the row encoding and hash (D2)

# (table, values, the encoding D2 names, BLAKE2b-256 of that encoding computed apart from the code)
_KNOWN = [
    ("persons", ("person:andy", "place:home/andy", 1, -5, None),
     b"t7:persons" b"s11:person:andy" b"s15:place:home/andy" b"i1:1" b"i2:-5" b"n",
     "fe21add4b031afc4b8922942bc4ce2615471abee04d597cecdf3592a9dc2ad30"),
    ("places", ("place:x", 1, 2, None, b"\x00\xff"),
     b"t6:places" b"s7:place:x" b"i1:1" b"i1:2" b"n" b"b2:\x00\xff",
     "57f85e570d04881b3992e363915034d7395e50351b283e0cd9eb5e2f57a3cf70"),
    ("lane_notes", ("mem:S/episode/m1", "café", 1.5, 3),        # a REAL, and a length in UTF-8 bytes
     b"t10:lane_notes" b"s16:mem:S/episode/m1" b"s5:caf\xc3\xa9" b"r3:1.5" b"i1:3",
     "ec654e4944683f557abcc0ab58f280ec121e6f0248629a280b79be65175c4760"),
]


def test_1_known_rows_hash_to_fixed_values_with_every_tag_and_a_real():
    """D2: `t<len>:<table>`, then per value `n`, or `i`, `s`, `b` or `r` with a length in bytes and the bytes."""
    for table, values, encoded, digest in _KNOWN:
        assert permission_ledger._row_bytes(table, values) == encoded
        assert permission_ledger._row_hash(table, values) == int(digest, 16)
    # framing: a value can't run into the next one, nor the table name into the first value
    assert permission_ledger._row_hash("groups", ("ab", "c", 1)) != permission_ledger._row_hash("groups", ("a", "bc", 1))
    assert permission_ledger._row_hash("copies", ("1", "x", 1)) != permission_ledger._row_hash("copies", (1, "x", 1))


_MEMBERS = [("collection:andy/medical", f"mem:S/episode/m{i}", "person", i + 1, "person:andy", None, None)
            for i in range(6)]


def test_1_a_part_ignores_insert_order_and_a_row_taken_out_and_put_back():
    forward, backward = permission_ledger._new_parts(), permission_ledger._new_parts()
    for row in _MEMBERS:
        permission_ledger._fold(forward, "collection_members", row)
    for row in reversed(_MEMBERS):
        permission_ledger._fold(backward, "collection_members", row)
    assert forward == backward and forward["collection_members"][0] == len(_MEMBERS)
    assert permission_ledger._parts_digest(forward) == permission_ledger._parts_digest(backward)
    permission_ledger._fold(backward, "collection_members", _MEMBERS[2], -1)          # an update's subtraction
    assert backward != forward and backward["collection_members"][0] == len(_MEMBERS) - 1
    permission_ledger._fold(backward, "collection_members", _MEMBERS[2])
    assert backward == forward


def test_1_the_whole_is_blake2b_of_the_parts_canonical_json_in_a_fixed_order():
    parts = permission_ledger._new_parts()
    assert tuple(parts) == permission_ledger._PARTS == ("meta", *_COLUMNS) and len(parts) == 18
    for row in _MEMBERS:
        permission_ledger._fold(parts, "collection_members", row)
    text = permission_ledger._parts_text(parts)
    assert text == canonical_json({p: [n, f"{s:064x}"] for p, (n, s) in parts.items()})
    assert list(json.loads(text)) == sorted(permission_ledger._PARTS)
    assert permission_ledger._parts_digest(parts) == hashlib.blake2b(text.encode(), digest_size=32).hexdigest()
    assert permission_ledger._read_parts(text) == parts


def test_1_the_meta_part_excludes_head_and_the_projection_keys_and_covers_gate_admins_and_owner():
    kept = [("ledger_id", "l-1"), ("schema_version", "2"), ("owner", "person:andy"), ("admins", "person:andy"),
            ("gate", "shadow")]
    plain, with_followers = permission_ledger._new_parts(), permission_ledger._new_parts()
    for kv in kept:
        permission_ledger._fold(plain, "meta", kv)
    for kv in kept + [("head", "3:ab"), ("projection", "3:cd"), ("projection_parts", "{}")]:
        permission_ledger._fold(with_followers, "meta", kv)
    assert plain == with_followers and plain["meta"][0] == len(kept)
    for gone in ("gate", "admins", "owner"):
        other = permission_ledger._new_parts()
        for kv in kept:
            if kv[0] != gone:
                permission_ledger._fold(other, "meta", kv)
        assert other["meta"] != plain["meta"], gone


# ---------------------------------------------------------------- Task 2: projection_now and the full check (D2, D4)

# BLAKE2b-256 of every part's [0, 64 zeros] in canonical JSON, computed apart from the code
EMPTY = "417b1c2804721d7ffedd7efb55ae7db07644ac70329df7a573a74400d27ca01f"


def _sql(home, *statements):
    con = sqlite3.connect(ledger_path(home))
    try:
        for s in statements:
            con.execute(s)
        con.commit()
    finally:
        con.close()


def _stamp_by_hand(home):
    """meta.projection and projection_parts set to the tables as they are, by SQL: what a writer keeps."""
    con = sqlite3.connect(ledger_path(home))
    try:
        whole, parts = projection_now(con)
        top = con.execute("SELECT COALESCE(MAX(seq), 0) FROM ledger_log").fetchone()[0]
        con.executemany("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        [("projection", f"{top}:{whole}"), ("projection_parts", permission_ledger._parts_text(parts))])
        con.commit()
    finally:
        con.close()


def _full_check(home):
    con = sqlite3.connect(f"file:{ledger_path(home)}?mode=ro", uri=True, isolation_level=None)
    try:
        con.execute("BEGIN")
        permission_ledger._full_check(con)
        con.execute("COMMIT")
    finally:
        con.close()


def test_2_an_empty_ledgers_digest_is_fixed(tmp_path):
    con = sqlite3.connect(tmp_path / "bare.db")
    con.executescript(permission_ledger._SCHEMA)          # every table, and no meta row
    assert projection_now(con) == (EMPTY, permission_ledger._new_parts())
    con.close()
    Ledger._blank(tmp_path, "ledger-fixed").close()
    expected = permission_ledger._new_parts()
    for kv in (("ledger_id", "ledger-fixed"), ("schema_version", SCHEMA_VERSION)):
        permission_ledger._fold(expected, "meta", kv)
    con = sqlite3.connect(ledger_path(tmp_path))
    assert projection_now(con) == (permission_ledger._parts_digest(expected), expected)
    con.close()


def _uncollected(home):
    """E1's county; Andy uncollects m2 and m3 in one act (the acceptance test's ledger). Returns the act's seq."""
    led = e1_county_ledger(home)
    seq = do(led, ANDY, "uncollect", collection=MEDICAL, objects=[M2, M3], now="2026-11-02").seq
    led.close()
    return seq


def test_2_the_full_check_passes_on_a_whole_ledger_and_a_mismatch_names_its_part(tmp_path):
    seq = _uncollected(tmp_path)
    _stamp_by_hand(tmp_path)
    _full_check(tmp_path)                                                     # the control: whole, it passes
    _sql(tmp_path, "UPDATE collection_members SET removed_seq = NULL, removed_by = NULL "
                   f"WHERE removed_seq = {seq} AND object = '{M2}'")
    with pytest.raises(LedgerUnreadable, match="the projection digest: collection_members differs"):
        _full_check(tmp_path)
    _stamp_by_hand(tmp_path)
    _sql(tmp_path, "UPDATE meta SET value = 'person:jenn' WHERE key = 'admins'")
    with pytest.raises(LedgerUnreadable, match="the projection digest: meta differs"):
        _full_check(tmp_path)


def test_2_a_missing_log_middle_row_is_caught_by_the_count(tmp_path):
    """The log is in no part: a middle row lost leaves every part and the top seq as they were."""
    seq = _uncollected(tmp_path)
    _stamp_by_hand(tmp_path)
    _sql(tmp_path, f"DELETE FROM ledger_log WHERE seq = {seq // 2}")
    with pytest.raises(LedgerUnreadable, match=f"the projection digest: the log holds {seq - 1} rows, but its last "
                                               f"seq is {seq}"):
        _full_check(tmp_path)


def test_2_a_projection_behind_head_names_both_seqs_and_any_sqlite_error_reads_unreadable(tmp_path):
    seq = _uncollected(tmp_path)
    _stamp_by_hand(tmp_path)
    _sql(tmp_path, f"UPDATE meta SET value = '{seq - 1}:' || substr(value, instr(value, ':') + 1) "
                   "WHERE key = 'projection'")
    with pytest.raises(LedgerUnreadable, match=f"the projection digest: projection seq {seq - 1} behind head {seq}"):
        _full_check(tmp_path)
    _stamp_by_hand(tmp_path)
    _sql(tmp_path, "DROP TABLE copies")
    with pytest.raises(LedgerUnreadable, match="the projection digest could not be checked: no such table: copies"):
        _full_check(tmp_path)


# ---------------------------------------------------------------- Task 3: the incremental writer (D3)

@pytest.fixture
def own_asserts(monkeypatch):
    """The suite-wide check after each append (tests/conftest.py) off, so a test's own assert is the one that fails."""
    monkeypatch.setenv("ENGRAM_PROJECTION_CHECK", "off")


def _follows(led) -> bool:
    """Whether meta.projection and projection_parts are the tables recomputed now, read in one transaction."""
    led.conn.execute("BEGIN")
    try:
        meta, top = led.meta(), led.seq()
        whole, parts = projection_now(led.conn)
    finally:
        led.conn.execute("COMMIT")
    return meta["projection"] == f"{top}:{whole}" and permission_ledger._read_parts(meta["projection_parts"]) == parts


def test_3_a_new_ledger_is_stamped_with_its_projection_at_seq_0(tmp_path):
    led = Ledger._blank(tmp_path, "ledger-fixed")
    expected = permission_ledger._new_parts()
    for kv in (("ledger_id", "ledger-fixed"), ("schema_version", SCHEMA_VERSION)):
        permission_ledger._fold(expected, "meta", kv)
    meta = led.meta()
    assert meta["projection"] == "0:" + permission_ledger._parts_digest(expected)
    assert meta["projection_parts"] == permission_ledger._parts_text(expected)
    led.close()


# (what, a body, a read of the value it left, the value SQLite holds): affinity converts a bound value, so `_project`
# hashes the row it reads back, never the values it bound
_HAND_MADE = [
    ("an int into TEXT", {"insert": [{"table": "groups", "row": {"id": "group:g1", "owner": 5, "created_seq": "@seq"}}]},
     "SELECT owner FROM groups", "5"),
    ('"5" into INTEGER', {"insert": [{"table": "persons", "row": {
        "id": "person:p5", "home": "place:home/p5", "is_admin": "5", "created_seq": "@seq"}}]},
     "SELECT is_admin FROM persons WHERE id = 'person:p5'", 5),
    ("1.5 into INTEGER", {"insert": [{"table": "lane_notes", "row": {
        "object": "mem:S/episode/m1", "lane": "work", "at": 1.5, "seq": "@seq"}}]}, "SELECT at FROM lane_notes", 1.5),
    ("2.0 into INTEGER", {"insert": [{"table": "lane_notes", "row": {
        "object": "mem:S/episode/m1", "lane": "work", "at": 2.0, "seq": "@seq"}}]}, "SELECT at FROM lane_notes", 2),
    ("a bool", {"insert": [{"table": "persons", "row": {
        "id": "person:pb", "home": "place:home/pb", "is_admin": True, "created_seq": "@seq"}}]},
     "SELECT is_admin FROM persons WHERE id = 'person:pb'", 1),
    ("a dict", {"insert": [{"table": "groups", "row": {"id": "group:g2", "owner": {"b": 1, "a": [2]},
                                                       "created_seq": "@seq"}}]},
     "SELECT owner FROM groups", '{"a":[2],"b":1}'),
    ("the salt", {"insert": [{"table": "places", "row": {"id": "place:x", "is_root": 1, "created_seq": "@seq",
                                                          "pseudonym_salt": "00ff" * 8}}]},
     "SELECT pseudonym_salt FROM places WHERE id = 'place:x'", bytes.fromhex("00ff" * 8)),
]


@pytest.mark.parametrize("what, body, read, held", _HAND_MADE, ids=[h[0] for h in _HAND_MADE])
def test_3_hand_made_bodies_hash_the_value_sqlite_holds(tmp_path, own_asserts, what, body, read, held):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    led._append("hand-made", "x", ANDY, "terminal", body, at=T("2026-11-02"))
    got = led.conn.execute(read).fetchone()[0]
    assert (got, type(got)) == (held, type(held))
    assert _follows(led), what
    led.close()


def test_3_an_update_that_changes_its_own_where_column(tmp_path, own_asserts):
    """The rowids are read before the update and the rows re-read by them after: re-run, the where (removed_seq IS
    NULL) would match none of the rows it changed."""
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    led._append("group", "group:g", ANDY, "terminal", {"insert": [
        {"table": "groups", "row": {"id": "group:g", "owner": ANDY, "created_seq": "@seq"}},
        *({"table": "group_members", "row": {"group_id": "group:g", "agent": a, "added_seq": "@seq"}}
          for a in ("agent:a", "agent:b"))]}, at=T("2026-11-02"))
    seq = led._append("ungroup", "group:g", ANDY, "terminal", {"update": [
        {"table": "group_members", "where": {"group_id": "group:g", "removed_seq": None},
         "set": {"removed_seq": "@seq"}}]}, at=T("2026-11-03"))
    assert [r[0] for r in led.conn.execute("SELECT removed_seq FROM group_members")] == [seq, seq]
    assert _follows(led)
    led.close()


def test_3_meta_set_by_a_body_is_re_read_and_its_old_row_taken_out(tmp_path, own_asserts):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    for admins in ("person:andy,person:jenn", "person:andy"):
        led._append("admins", "meta", ANDY, "terminal", {"meta": {"admins": admins}}, at=T("2026-11-02"))
        assert _follows(led)
    led.close()


def test_3_a_body_never_sets_the_projection_keys(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    before = led.seq()
    for key in ("projection", "projection_parts"):
        with pytest.raises(RuleError, match=f"meta.{key} follows the tables and is never set by a log body"):
            led._append("x", "meta", ANDY, "terminal", {"meta": {key: "1:00"}}, at=T("2026-11-02"))
    assert led.seq() == before
    led.close()


def test_3_the_authorizer_refuses_a_delete_on_a_projection_table(tmp_path):
    """S8: rows are only inserted, or updated to set later columns, so no writing connection deletes one."""
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    for table in ("collection_members", "places", "meta"):
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            led.conn.execute(f"DELETE FROM {table}")
    led.close()
    led = Ledger.open(tmp_path)
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        led.conn.execute("DELETE FROM persons WHERE id = ?", (ANDY,))
    assert led.state().persons[ANDY].home == "place:home/andy"
    led.close()


def test_3_the_suite_checks_the_projection_after_every_append(tmp_path, monkeypatch):
    """S8's suite-wide check (tests/conftest.py), in place of a random-act generator: a writer that folds a row other
    than the one SQLite holds fails its append's check, unless the check is off. (A row written by raw SQL is caught
    before that, by the next writer's check of its base, Task 4.)"""
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    real = Ledger._rows_at
    monkeypatch.setattr(Ledger, "_rows_at", lambda self, table, rowids: [r[::-1] for r in real(self, table, rowids)])
    group = {"insert": [{"table": "groups", "row": {"id": "group:g", "owner": ANDY, "created_seq": "@seq"}}]}
    with pytest.raises(AssertionError, match="meta.projection is not the tables"):
        led._append("x", "a", ANDY, "terminal", group, at=T("2026-11-02"))
    monkeypatch.setenv("ENGRAM_PROJECTION_CHECK", "off")
    led._append("x", "b", ANDY, "terminal", {}, at=T("2026-11-03"))
    led.close()



# ---------------------------------------------------------------- Task 4: the reader, the key and the marker (D4)

ENGRAM_DIR = str(Path(permission_ledger.__file__).resolve().parent)


def _marker(home) -> Path:
    return ledger_path(home).with_name("permissions.verified")


def _state(home):
    led = Ledger.open_read_only(home)
    try:
        return led.state()
    finally:
        led.close()


def _key_now(home):
    """The ledger's key as a reader reads it now, inside a read transaction."""
    led = Ledger.open_read_only(home)
    try:
        led.conn.execute("BEGIN")
        try:
            key, _pinned = led._read_key()
        finally:
            led.conn.execute("COMMIT")
    finally:
        led.close()
    return key


def _tear_m2(home, seq):
    """The acceptance test's tear: m2's removal by the uncollect at `seq` lost, m3's kept."""
    _sql(home, "UPDATE collection_members SET removed_seq = NULL, removed_by = NULL "
               f"WHERE removed_seq = {seq} AND object = '{M2}'")


def _created(home):
    Ledger.create(home, "andy", now=T("2026-11-01")).close()


def _checks():
    return permission_ledger.full_checks


def test_4_the_writer_marks_and_memos_the_key_it_committed(tmp_path):
    seq = _uncollected(tmp_path)
    marked = json.loads(_marker(tmp_path).read_text())
    key = _key_now(tmp_path)
    assert marked == dataclasses.asdict(key) and key.head.startswith(f"{seq}:")
    before = _checks()
    assert _state(tmp_path).seq == seq                     # a memo match
    permission_ledger._forget_verified()
    assert _state(tmp_path).seq == seq                     # a marker match, as a new process reads it
    assert _checks() == before


def test_4_a_torn_index_page_is_caught(tmp_path):
    """D4's full check runs SQLite's integrity check: a torn page of an index no table read sees (records_layer)."""
    _uncollected(tmp_path)
    con = sqlite3.connect(ledger_path(tmp_path))
    (layer,) = con.execute("SELECT layer FROM records ORDER BY rowid LIMIT 1").fetchone()
    con.close()
    _tear_index(tmp_path, "records_layer", f"layer != '{layer}'")
    with pytest.raises(LedgerUnreadable, match="the projection digest: SQLite's integrity check of the file: .*"
                                               "records_layer"):
        _state(tmp_path)


def test_4_the_key_holds_ctime(tmp_path):
    """M4a, ctime alone: a tampered copy written over the ledger as `cp -p` writes it (the same inode and size), its
    change counter poked back to the marker's, so only ctime tells the two files apart."""
    seq = _uncollected(tmp_path)
    marked = json.loads(_marker(tmp_path).read_text())
    side = tmp_path / "side.db"
    shutil.copy2(ledger_path(tmp_path), side)
    con = sqlite3.connect(side)
    con.execute(f"UPDATE collection_members SET removed_seq = NULL, removed_by = NULL WHERE removed_seq = {seq} "
                f"AND object = '{M2}'")
    con.commit()
    con.close()
    torn = bytearray(side.read_bytes())
    torn[24:28] = marked["counter"].to_bytes(4, "big")
    side.write_bytes(torn)
    time.sleep(0.02)
    shutil.copyfile(side, ledger_path(tmp_path))            # cp -p: into the same file, then its times
    shutil.copystat(side, ledger_path(tmp_path))
    now = dataclasses.asdict(_key_now(tmp_path))
    assert {f for f in now if now[f] != marked[f]} == {"ctime_ns"}
    with pytest.raises(LedgerUnreadable, match="the projection digest: collection_members differs"):
        _state(tmp_path)


def test_4_the_key_holds_the_change_counter(tmp_path, monkeypatch):
    """M4a, the counter alone: on a filesystem whose ctime is coarse (the key's stat answers one tick throughout), an
    in-place tamper leaves inode, size, ctime and head as the marker holds them."""
    real = os.stat
    monkeypatch.setattr(permission_ledger, "_stat", lambda path: SimpleNamespace(
        **{f: getattr(real(path), f) for f in ("st_dev", "st_ino", "st_size")}, st_ctime_ns=0))
    seq = _uncollected(tmp_path)
    marked = json.loads(_marker(tmp_path).read_text())
    _tear_m2(tmp_path, seq)
    now = dataclasses.asdict(_key_now(tmp_path))
    assert {f for f in now if now[f] != marked[f]} == {"counter"}
    with pytest.raises(LedgerUnreadable, match="the projection digest: collection_members differs"):
        _state(tmp_path)


@pytest.mark.parametrize("field", ["head", "ino"])
def test_4_the_key_holds_head_and_inode(tmp_path, field):
    """M4a and the re-check's M4: a marker forged with every field of the tampered file's key but one. A file renamed
    over the ledger changes ctime too, so the inode is tested by a forged marker, as head is."""
    seq = _uncollected(tmp_path)
    _tear_m2(tmp_path, seq)
    now = dataclasses.asdict(_key_now(tmp_path))
    forged = {**now, field: f"{seq}:{'0' * 64}" if field == "head" else now["ino"] + 1}
    _marker(tmp_path).write_text(json.dumps(forged))
    permission_ledger._forget_verified()
    with pytest.raises(LedgerUnreadable, match="the projection digest: collection_members differs"):
        _state(tmp_path)
    _marker(tmp_path).write_text(json.dumps(now))      # the control: the whole key forged is served
    assert _state(tmp_path).seq == seq


def test_4_a_raw_write_between_a_writers_commit_and_its_key_read_leaves_no_marker(tmp_path, monkeypatch, own_asserts):
    """M1, writers racing, with a raw writer as B (Rio Grande): A commits, B's raw UPDATE lands before A's post-commit
    read, which sees the counter at c+2, so A marks nothing and the next reader runs the full check."""
    seq = _uncollected(tmp_path)
    marked = _marker(tmp_path).read_text()
    real = Ledger._mark_after_commit

    def raced(self, *args, **kwargs):
        _tear_m2(tmp_path, seq)                                  # B
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Ledger, "_mark_after_commit", raced)
    led = Ledger.open(tmp_path)
    led._append("note", "a", ANDY, "terminal", {}, at=T("2026-11-03"))     # A
    led.close()
    monkeypatch.setattr(Ledger, "_mark_after_commit", real)
    assert _marker(tmp_path).read_text() == marked
    before = _checks()
    with pytest.raises(LedgerUnreadable, match="the projection digest: collection_members differs"):
        _state(tmp_path)
    assert _checks() == before + 1


_TRY_TO_WRITE = ("import sqlite3, sys\n"
                 "c = sqlite3.connect(sys.argv[1], isolation_level=None, timeout=0)\n"
                 "try:\n"
                 "    c.execute('BEGIN IMMEDIATE')\n"
                 "    c.execute(\"INSERT INTO meta VALUES('lock-probe', '1')\")\n"
                 "    c.execute('COMMIT')\n"
                 "    print('wrote')\n"
                 "except sqlite3.OperationalError as e:\n"
                 "    print(e)\n")


def _another_process_writes(home) -> str:
    return subprocess.run([sys.executable, "-I", "-c", _TRY_TO_WRITE, str(ledger_path(home))], capture_output=True,
                          text=True, check=True).stdout.strip()


def test_4_the_key_read_keeps_sqlites_locks(tmp_path):
    """M2: closing any descriptor on the file drops every POSIX lock the process holds on it, SQLite's too. The key
    read is a pread on a descriptor kept open, so another process still finds the ledger locked, under BEGIN
    IMMEDIATE and inside a read transaction."""
    _created(tmp_path)
    led = Ledger.open(tmp_path)
    try:
        for begin in ("BEGIN IMMEDIATE", "BEGIN"):
            led.conn.execute(begin)
            led.conn.execute("SELECT COUNT(*) FROM meta").fetchone()
            led._read_key()
            assert _another_process_writes(tmp_path) == "database is locked", begin
            led.conn.execute("ROLLBACK")
    finally:
        led.close()
    assert _another_process_writes(tmp_path) == "wrote"          # the control: with no lock held, it writes


def _header(home) -> bytes:
    return ledger_path(home).read_bytes()[:28]


def test_4_out_of_the_rollback_journal_every_read_runs_the_full_check(tmp_path):
    """M3: under WAL a commit moves neither the counter, the size nor ctime, so no key is trusted and every state()
    runs the full check, as it does beside a non-empty -wal. A writing open puts the rollback journal back."""
    _created(tmp_path)
    _sql(tmp_path, "PRAGMA journal_mode=WAL")
    assert _header(tmp_path)[18:20] == b"\x02\x02"
    for _ in range(2):
        before = _checks()
        _state(tmp_path)
        assert _checks() == before + 1
    Ledger.open(tmp_path).close()
    assert _header(tmp_path)[18:20] == b"\x01\x01"
    _state(tmp_path)
    before = _checks()
    _state(tmp_path)
    assert _checks() == before                                     # pinned again: the memo serves
    ledger_path(tmp_path).with_name("permissions.db-wal").write_bytes(b"\x00" * 64)
    for _ in range(2):
        before = _checks()
        _state(tmp_path)
        assert _checks() == before + 1


def test_4_a_writing_open_carries_on_when_the_journal_cannot_be_switched_back(tmp_path):
    """The re-check's nit: switching WAL back needs every other connection gone, so a writing open tries it and goes
    on, and the WAL pin keeps forcing the full check until it succeeds."""
    _created(tmp_path)
    _sql(tmp_path, "PRAGMA journal_mode=WAL")
    reader = sqlite3.connect(ledger_path(tmp_path), isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM meta").fetchone()
    try:
        start = time.monotonic()
        Ledger.open(tmp_path).close()
        assert time.monotonic() - start < 2
        assert _header(tmp_path)[18:20] == b"\x02\x02"
    finally:
        reader.execute("COMMIT")
        reader.close()


def test_4_two_concurrent_frames_run_one_full_check(tmp_path, monkeypatch):
    """N8: the check passed is kept in this process's memo behind a lock, so the second frame (FRAMES_AT_ONCE=2) waits
    and is served by it."""
    _created(tmp_path)
    _marker(tmp_path).unlink()
    permission_ledger._forget_verified()
    real = permission_ledger._full_check
    monkeypatch.setattr(permission_ledger, "_full_check", lambda conn: (time.sleep(0.3), real(conn))[1])
    gate, errors, before = threading.Barrier(2), [], _checks()

    def frame():
        led = Ledger.open_read_only(tmp_path)
        try:
            gate.wait()
            led.state()
        except Exception as e:  # noqa: BLE001 - reported below
            errors.append(e)
        finally:
            led.close()

    threads = [threading.Thread(target=frame) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and _checks() == before + 1


_KILLED = ("import os, sys\n"
           "sys.path.insert(0, sys.argv[2])\n"
           "from permission_ledger import Ledger\n"
           "Ledger._mark_after_commit = lambda self, *args, **kwargs: os._exit(0)\n"
           "Ledger.open(sys.argv[1])._append('note', 'killed', 'person:andy', 'terminal', {}, at=1_800_000_000)\n")


def test_4_a_writer_killed_between_its_commit_and_its_marker_leads_to_one_full_check(tmp_path):
    _created(tmp_path)
    marked = _marker(tmp_path).read_text()
    subprocess.run([sys.executable, "-c", _KILLED, str(tmp_path), ENGRAM_DIR], check=True)
    assert _marker(tmp_path).read_text() == marked
    permission_ledger._forget_verified()
    before = _checks()
    assert _state(tmp_path).seq == 2 and _state(tmp_path).seq == 2
    assert _checks() == before + 1


def test_4_readers_write_nothing_even_after_a_full_check(tmp_path, monkeypatch, capsys):
    """S5: a reader keeps a check it passed only in its own memo, so `verify`, `check` and test_u9 stay true."""
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    _created(tmp_path)
    _marker(tmp_path).unlink()
    permission_ledger._forget_verified()
    before = _checks()
    assert cli_main(["verify"]) == 0
    _state(tmp_path)
    assert _checks() > before
    assert sorted(p.name for p in (tmp_path / ".engram").iterdir()) == ["permissions.db"]


def _between_the_check_and_the_late_connections(monkeypatch, change):
    real, done = Ledger._late, []

    def late(self, checked):
        if not done:
            done.append(change())
        return real(self, checked)

    monkeypatch.setattr(Ledger, "_late", late)


def test_4_a_late_connection_refuses_a_file_replaced_after_the_check(tmp_path, monkeypatch):
    """S7: StateRows and LogTimes connect after the check, so each must open the file the check read."""
    _created(tmp_path)
    copy = tmp_path / "copy.db"
    shutil.copyfile(ledger_path(tmp_path), copy)
    _between_the_check_and_the_late_connections(monkeypatch, lambda: os.replace(copy, ledger_path(tmp_path)))
    with pytest.raises(LedgerUnreadable, match="the ledger changed during this read; retry"):
        _state(tmp_path)


def test_4_a_late_connection_refuses_an_unverified_change(tmp_path, monkeypatch):
    _created(tmp_path)
    _between_the_check_and_the_late_connections(monkeypatch, lambda: _sql(tmp_path, "UPDATE persons SET is_admin = 0"))
    with pytest.raises(LedgerUnreadable, match="the ledger changed during this read; retry"):
        _state(tmp_path)


def test_4_a_late_connection_accepts_a_verified_write_that_landed_after_the_check(tmp_path, monkeypatch):
    """The re-check's Must-fix 2: an ordinary append landing mid-build is verified (its marker, and this process's
    memo), as today's lazy reads allow by design: the rows up to the State's seq read the same later."""
    _created(tmp_path)

    def write():
        led = Ledger.open(tmp_path)
        led._append("note", "late", ANDY, "terminal", {}, at=T("2026-11-02"))
        led.close()

    _between_the_check_and_the_late_connections(monkeypatch, write)
    state = _state(tmp_path)
    assert state.seq == 1 and len(state.subjects) == 0 and len(state.seq_at) == 1


_MANY = ("import resource, sys\n"
         "from pathlib import Path\n"
         "sys.path.insert(0, sys.argv[2])\n"
         "import permission_ledger\n"
         "from permission_ledger import Ledger\n"
         "permission_ledger._RECHECK_S = 0\n"
         "resource.setrlimit(resource.RLIMIT_NOFILE, (256, resource.getrlimit(resource.RLIMIT_NOFILE)[1]))\n"
         "for i in range(2000):\n"
         "    home = Path(sys.argv[1]) / f'h{i}'\n"
         "    led = Ledger.open_read_only(home) if i % 10 else Ledger.open(home)\n"
         "    st = led.state()\n"
         "    assert len(st.subjects) == 0 and len(st.seq_at) == 1\n"
         "    del st\n"
         "    led.close()\n"
         "print('held', len(permission_ledger._HELD))\n")


def test_4_2000_ledgers_in_one_process_under_256_descriptors(tmp_path):
    """The re-check's Must-fix 1: the key read's descriptor is closed when this process's last connection on its file
    closes, so a process that reads many ledgers holds no descriptor per ledger it ever read."""
    _created(tmp_path / "h0")
    for i in range(1, 2000):
        (tmp_path / f"h{i}" / ".engram").mkdir(parents=True)
        shutil.copyfile(ledger_path(tmp_path / "h0"), ledger_path(tmp_path / f"h{i}"))
    done = subprocess.run([sys.executable, "-c", _MANY, str(tmp_path), ENGRAM_DIR], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.split() == ["held", "0"]


def test_4_the_marker_re_read_after_50_ms_spares_a_full_check_for_a_reader_and_a_writer(tmp_path, monkeypatch):
    """S2 and the re-check's should-fix: a read or a write that lands between another writer's COMMIT and its marker
    waits 50 ms and reads the marker once more before it runs the full check."""
    _created(tmp_path)
    written = _marker(tmp_path).read_text()
    _marker(tmp_path).unlink()
    permission_ledger._forget_verified()
    monkeypatch.setattr(permission_ledger, "_pause", lambda: _marker(tmp_path).write_text(written))
    before = _checks()
    _state(tmp_path)
    assert _checks() == before
    _marker(tmp_path).unlink()
    permission_ledger._forget_verified()
    led = Ledger.open(tmp_path)
    led._append("note", "x", ANDY, "terminal", {}, at=T("2026-11-02"))
    led.close()
    assert _checks() == before


CONTENDED = 150


def _contend(args):
    """One of two writers in contention (spawned): CONTENDED appends, each counted by its tries under the write lock,
    and the full checks run while the lock is held. Returns (tries per append, LedgerBusy count, those checks)."""
    home, who = args
    import permission_ledger as pl
    held, under_lock, tries = [False], [0], []
    real_on, real_check = pl.Ledger._append_on, pl._full_check

    def on(self, *a, **k):
        tries[-1] += 1
        held[0] = True
        try:
            return real_on(self, *a, **k)
        finally:
            held[0] = False

    def check(conn):
        under_lock[0] += held[0]
        return real_check(conn)

    pl.Ledger._append_on, pl._full_check = on, check
    led, busy = pl.Ledger.open(home), 0
    for i in range(CONTENDED):
        tries.append(0)
        try:
            led._append("register-agent", f"agent:{who}{i}", ANDY, "terminal", {"insert": [{"table": "agents", "row": {
                "id": f"agent:{who}{i}", "acts_for": ANDY, "created_seq": "@seq"}}]}, at=T("2026-12-01") + i)
        except pl.LedgerBusy:
            busy += 1
    led.close()
    return tries, busy, under_lock[0]


def test_4_two_writers_in_contention_take_each_other_s_verified_writes_under_the_lock(tmp_path):
    """The builder's finding on step 2 (the plan's decided items): a key changed under the write lock is taken when
    this process's memo or the marker holds it as verified, after one 50 ms re-read while holding RESERVED, as
    StateRows takes a verified change (Must-fix 2). Rolling back on every changed key, as first approved, sent about
    one contended append in fifty back, some three times or more (LedgerBusy: test_rf5 failed 3 runs in 10)."""
    _created(tmp_path)
    with multiprocessing.get_context("spawn").Pool(2) as pool:
        got = pool.map(_contend, [(tmp_path, "x"), (tmp_path, "y")])
    tries = [t for per, _busy, _checks in got for t in per]
    assert sum(busy for _per, busy, _checks in got) == 0
    assert sum(checks for _per, _busy, checks in got) == 0             # no full check ever runs under the lock
    assert max(tries) == 1, f"appends sent back: {sorted(t for t in tries if t > 1)}"
    led = Ledger.open_read_only(tmp_path)
    assert led.seq() == 1 + 2 * CONTENDED and led.verify() is None and len(led.state().agents) == 2 * CONTENDED
    led.close()


def test_4_a_writer_sent_back_three_times_raises_ledger_busy_and_writes_nothing(tmp_path, monkeypatch):
    """D4's writers, step 2, and the re-check's nit: a key changed under the write lock that neither the memo nor the
    marker holds as verified sends the writer back to verify again, at most three times; then LedgerBusy, which no
    caller reads as a torn ledger."""
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    real, tries = Ledger._base_key, []
    monkeypatch.setattr(Ledger, "_verified_under_lock", lambda self, key, pinned: False)

    def stale(self):
        tries.append(1)
        return dataclasses.replace(real(self), counter=-1)

    monkeypatch.setattr(Ledger, "_base_key", stale)
    with pytest.raises(permission_ledger.LedgerBusy):
        led._append("note", "x", ANDY, "terminal", {}, at=T("2026-11-02"))
    assert len(tries) == 3 and led.seq() == 1 and not issubclass(permission_ledger.LedgerBusy, LedgerUnreadable)
    led.close()


def test_4_an_append_waits_12_seconds_for_the_lock_and_gives_the_connection_its_own_back(tmp_path, monkeypatch):
    """The re-check's S1: a full check holds SHARED for its whole length, about 3.8 s on a loaded Pi, so an append
    waits up to 12 s against BUSY_MS's 5 s elsewhere."""
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    seen, real = [], Ledger._project
    monkeypatch.setattr(Ledger, "_project", lambda self, *a, **k: (
        seen.append(self.conn.execute("PRAGMA busy_timeout").fetchone()[0]), real(self, *a, **k))[1])
    led._append("note", "x", ANDY, "terminal", {}, at=T("2026-11-02"))
    assert seen == [12000] and led.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    led.close()


# ---------------------------------------------------------------- Task 5: old ledgers, the gate, verify, rebuild, skew (D5-D8)

def _unstamp(home):
    """The ledger under `home` as code before the digest left one: version 1, no projection keys, no marker."""
    _sql(home, "UPDATE meta SET value = '1' WHERE key = 'schema_version'",
         "DELETE FROM meta WHERE key IN ('projection', 'projection_parts')")
    _marker(home).unlink(missing_ok=True)


def _live(state):
    return {r.object for r in state.collection_members.get(MEDICAL) if r.removed_seq is None}


def test_5_a_new_ledger_is_version_2_which_code_before_the_digest_refuses(tmp_path, monkeypatch):
    """D8: an Engram process still on old code refuses a stamped ledger instead of writing it and leaving the
    projection behind head. New code opens both versions."""
    _created(tmp_path)
    led = Ledger.open_read_only(tmp_path)
    assert led.meta()["schema_version"] == permission_ledger.SCHEMA_VERSION == "2"
    led.close()
    assert permission_ledger.SCHEMA_VERSIONS == ("1", "2")
    monkeypatch.setattr(permission_ledger, "SCHEMA_VERSIONS", ("1",))         # old code's one version
    with pytest.raises(LedgerUnreadable, match="not a version 1 permission ledger"):
        Ledger.open(tmp_path)


def test_5_an_unstamped_ledger_reads_and_writes_as_before_and_keeps_no_digest(tmp_path):
    """D5: a ledger made before the digest is never stamped by a writing open, which would bless a tear it holds;
    under off and shadow it works as today, and an append keeps no digest and marks nothing (N8)."""
    _created(tmp_path)
    _unstamp(tmp_path)
    led = Ledger.open(tmp_path)
    seq = led._append("group", "group:g", ANDY, "terminal", {"insert": [
        {"table": "groups", "row": {"id": "group:g", "owner": ANDY, "created_seq": "@seq"}}]}, at=T("2026-11-02"))
    meta = led.meta()
    assert meta["schema_version"] == "1" and "projection" not in meta and "projection_parts" not in meta
    assert led.state().seq == seq and "group:g" in led.state().groups
    led.close()
    assert not _marker(tmp_path).exists()


def test_5_a_version_2_ledger_that_lost_its_digest_reads_unreadable(tmp_path):
    """Stamped is the version, not the keys: a ledger of version 2 whose projection keys are gone is not read as one
    made before the digest."""
    _created(tmp_path)
    _sql(tmp_path, "DELETE FROM meta WHERE key IN ('projection', 'projection_parts')")
    with pytest.raises(LedgerUnreadable, match="the projection digest: meta holds none"):
        _state(tmp_path)


UNSTAMPED = "no projection digest; run `engram-permissions rebuild`, then the move step it prints"


def test_5_under_enforce_an_unstamped_ledger_reads_closed_and_enforce_is_refused_on_it(tmp_path):
    """D5 and D6: enforce requires the digest. The rule is in `_prep_gate`, where the State is, because
    `check_gate_mode` sees no ledger; off and shadow are as before."""
    led = raised_ledger(tmp_path, mode="enforce")
    led.close()
    assert effective_gate(tmp_path, houses(tmp_path)) == Gate("enforce", None)
    _unstamp(tmp_path)
    assert effective_gate(tmp_path, houses(tmp_path)) == Gate("closed", UNSTAMPED)
    led = Ledger.open(tmp_path)
    try:
        before = led.seq()
        with pytest.raises(RuleError, match="enforce needs the ledger's projection digest"):
            raise_gate(led, "enforce", now="2026-11-03")
        assert led.seq() == before
        raise_gate(led, "shadow", now="2026-11-03")
        assert effective_gate(tmp_path, houses(tmp_path)) == Gate("shadow", None)
    finally:
        led.close()


def test_5_gate_enforce_on_an_unstamped_ledger_is_refused_before_the_yes(cli_home_with_house, fake_tty, capsys):
    _unstamp(cli_home_with_house)
    shown = fake_tty.shown()
    assert cli_main(["gate", "enforce"]) == 1
    assert "enforce needs the ledger's projection digest" in capsys.readouterr().err
    assert fake_tty.shown() == shown                                          # no yes was asked
    fake_tty.answer_the_printed_code()
    assert cli_main(["gate", "shadow"]) == 0


def test_5_a_projection_behind_head_names_both_seqs(tmp_path):
    """D8: an append by code that keeps no digest (a server not restarted) leaves the projection behind head, and
    every reader names the cause."""
    _created(tmp_path)
    con = sqlite3.connect(ledger_path(tmp_path))
    prev = con.execute("SELECT digest FROM ledger_log WHERE seq = 1").fetchone()[0]
    entry = {"seq": 2, "at": T("2026-11-02"), "kind": "note", "ref": "x", "actor": ANDY, "channel": "terminal",
             "under_grant": None, "proposal_id": None, "body": "{}"}
    digest = permission_ledger._digest(prev, entry)
    con.execute("INSERT INTO ledger_log VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (2, entry["at"], "note", "x", ANDY, "terminal", None, None, "{}", prev, digest))
    con.execute("UPDATE meta SET value = ? WHERE key = 'head'", (f"2:{digest}",))
    con.commit()
    con.close()
    with pytest.raises(LedgerUnreadable, match="the projection digest: projection seq 1 behind head 2"):
        _state(tmp_path)


def test_5_rebuild_stamps_reports_a_mismatch_without_refusing_and_marks_once_after_the_replace(tmp_path, monkeypatch):
    """D7 and the re-check's S4: rebuild is the recovery path, so it reports whether the old tables matched and never
    refuses; it builds its file with no key, memo or marker per append, checks it whole once at the end, and marks
    it after the replace."""
    seq = _uncollected(tmp_path)
    _tear_m2(tmp_path, seq)
    marks, checks, real = [], _checks(), permission_ledger._write_marker
    monkeypatch.setattr(permission_ledger, "_write_marker", lambda path, key: (marks.append(path), real(path, key)))
    led = Ledger.open_read_only(tmp_path)
    try:
        dest = led.rebuild(tmp_path / "copy")
        assert led.rebuilt_differs == ["collection_members"]
    finally:
        led.close()
    assert marks == [ledger_path(dest)] and _checks() == checks + 1
    meta = Ledger.open_read_only(dest).meta()
    assert meta["schema_version"] == "2" and meta["projection"].startswith(f"{seq}:")
    permission_ledger._forget_verified()
    assert M2 not in _live(_state(dest)) and _checks() == checks + 1       # the replay's removal, served by the marker


def test_5_rebuild_of_a_whole_or_an_unstamped_ledger_reports_a_match_and_stamps_it(tmp_path):
    _uncollected(tmp_path)
    led = Ledger.open_read_only(tmp_path)
    try:
        led.rebuild(tmp_path / "copy")
        assert led.rebuilt_differs == []
    finally:
        led.close()
    _unstamp(tmp_path)
    led = Ledger.open_read_only(tmp_path)
    try:
        dest = led.rebuild(tmp_path / "copy2")
        assert led.rebuilt_differs == []                       # the version is the one difference, and expected
    finally:
        led.close()
    assert Ledger.open_read_only(dest).meta()["schema_version"] == "2"


def test_5_the_rebuild_command_reports_the_match_and_prints_the_move_step(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    seq = _uncollected(tmp_path)
    assert cli_main(["rebuild", "--out", str(tmp_path / "copy")]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "The old tables matched the replay." in out
    assert f"stop every Engram process, then move {ledger_path(tmp_path / 'copy')} to {ledger_path(tmp_path)}" in out
    _tear_m2(tmp_path, seq)
    assert cli_main(["rebuild", "--out", str(tmp_path / "copy2")]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "The old tables differ from the replay in collection_members" in out


def test_5_verify_reports_the_parts_and_names_a_torn_part(tmp_path, monkeypatch, capsys):
    """D7: verify stays read-only and reports the parts."""
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    seq = _uncollected(tmp_path)
    con = sqlite3.connect(ledger_path(tmp_path))
    _whole, parts = projection_now(con)
    con.close()
    assert cli_main(["verify"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert f"collection_members {parts['collection_members'][0]}" in out and f"at seq {seq}" in out
    # the review's S1: not every read checks the digest (the gate's own read, the imprint filter's direct reads)
    assert "every reader checks" not in out and "the imprint filter's" in out and "before it serves a State" in out
    _tear_m2(tmp_path, seq)
    assert cli_main(["verify"]) == 1
    assert "the projection digest: collection_members differs" in capsys.readouterr().out
    assert sorted(p.name for p in (tmp_path / ".engram").iterdir()) == ["permissions.db", "permissions.verified"]


def test_5_verify_says_an_unstamped_ledger_keeps_no_digest(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    _created(tmp_path)
    _unstamp(tmp_path)
    assert cli_main(["verify"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "keeps no projection digest" in out and "under enforce it reads closed" in out


def test_5_unstamp_is_the_way_back_and_asks_the_persons_yes(tmp_path, monkeypatch, fake_tty, capsys):
    """The re-check's should-fix: if this branch is ever reverted, scripts/unstamp_ledger.py sets the version to 1 and
    deletes the projection keys and the marker, a writing act on the ledger that the person says yes to."""
    sys.path.insert(0, str(Path(ENGRAM_DIR) / "scripts"))
    try:
        import unstamp_ledger
    finally:
        sys.path.remove(str(Path(ENGRAM_DIR) / "scripts"))
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    _created(tmp_path)
    before = ledger_path(tmp_path).read_bytes()
    fake_tty.answer("not the code")
    assert unstamp_ledger.main([]) == 3
    assert ledger_path(tmp_path).read_bytes() == before and _marker(tmp_path).exists()
    shown = " ".join(fake_tty.shown().split())
    assert "set schema_version to 1" in shown and "delete meta.projection and meta.projection_parts" in shown
    assert "a gate at enforce then reads closed" in shown              # the review's nit
    fake_tty.answer_the_printed_code()
    assert unstamp_ledger.main([]) == 0
    led = Ledger.open_read_only(tmp_path)
    meta = led.meta()
    led.close()
    assert meta["schema_version"] == "1" and not {"projection", "projection_parts"} & set(meta)
    assert not _marker(tmp_path).exists()
    monkeypatch.setattr(permission_ledger, "SCHEMA_VERSIONS", ("1",))         # old code reads it again
    assert _state(tmp_path).seq == 1


# ---------------------------------------------------------------- Task 6: the budgets and the loop (D9, S2)

X86 = platform.machine() in ("x86_64", "AMD64")


@pytest.fixture(scope="module")
def d9_ledger(tmp_path_factory):
    home = tmp_path_factory.mktemp("d9") / "home"
    digest_shape(home)
    return home


@pytest.mark.skipif(not X86, reason="D9's x86 line (Tardis); the Pi's is in the U24 file, with ENGRAM_PI_BUDGET=1")
def test_6_the_budgets_at_d9s_shape_on_x86(d9_ledger, monkeypatch):
    """D9 on x86, at Task 0's shape (236,389 rows): state() with the full check, the rare path, within 2.5 s; a memo
    match spends at most 2 ms in the key protocol; an append costs at most 2 ms more than one that keeps no digest."""
    monkeypatch.setenv("ENGRAM_PROJECTION_CHECK", "off")
    got = digest_timings(d9_ledger)
    print(f"D9 on {platform.node()}: {got}")
    assert got["rare"] <= 2.5, got
    assert got["match"] <= 0.002, got
    assert got["append"] <= 0.002, got


LOOP_S = 60


def _loop_writer(args):
    """A writer for the loop test (spawned): appends until `until`. Returns (appends, LedgerBusy count)."""
    home, who, until = args
    import permission_ledger as pl
    led, n, busy = pl.Ledger.open(home), 0, 0
    while time.time() < until:
        try:
            led._append("note", f"{who}{n}", ANDY, "terminal", {"insert": [{"table": "lane_notes", "row": {
                "object": f"mem:S/episode/{who}{n}", "lane": "work", "at": T("2026-12-01") + n, "seq": "@seq"}}]},
                at=T("2026-12-01") + n)
        except pl.LedgerBusy:
            busy += 1
        n += 1
    led.close()
    return n, busy


def _loop_reader(args):
    """A reader for the loop test (spawned): one State per open, as a daemon frame reads, until `until`. Returns
    (reads, the full checks it ran, the reads refused, the first refusal)."""
    home, until = args
    import permission_ledger as pl
    reads, refused, first = 0, 0, None
    while time.time() < until:
        led = pl.Ledger.open_read_only(home)
        try:
            led.state()
        except pl.LedgerUnreadable as e:
            refused += 1
            first = first or str(e)[-160:]
        finally:
            led.close()
        reads += 1
    return reads, pl.full_checks, refused, first


def test_6_two_writers_and_a_reader_for_60_s_check_whole_at_most_1_percent_of_reads(tmp_path):
    """S2: a read that lands between a writer's COMMIT and its marker waits 50 ms and reads the marker again, so a
    full check stays rare under steady writes."""
    _created(tmp_path)
    until = time.time() + LOOP_S + 5                          # each process starts within the 5 s
    with multiprocessing.get_context("spawn").Pool(3) as pool:
        writers = pool.map_async(_loop_writer, [(tmp_path, "x", until), (tmp_path, "y", until)])
        reader = pool.apply_async(_loop_reader, ((tmp_path, until),))
        (wrote, reads) = writers.get(LOOP_S + 120), reader.get(LOOP_S + 120)
    print(f"loop: writers {wrote}, reader {reads}")
    assert all(busy == 0 and n > 100 for n, busy in wrote), wrote
    n_reads, checks, refused, first = reads
    assert refused == 0, f"{refused} of {n_reads} reads refused under steady writes, the first: {first}"
    assert n_reads > 100 and checks <= n_reads / 100, reads


# ---------------------------------------------------------------- Task 0c: an append's cost in a rebuild

def test_0c_an_append_spends_no_canonical_json_on_the_parts(tmp_path, monkeypatch, own_asserts):
    """Task 0c: canonical_json on the parts, twice an append, with reading them back, nearly tripled a rebuild of U24's
    reference ledger (158.7 s to 450.3 s on Tardis). The parts text is built directly (Task 1's test holds it to
    canonical_json's) and read back with a compiled check, so an append calls canonical_json for its body and its log
    entry only."""
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    calls, real = [], permission_ledger.canonical_json
    monkeypatch.setattr(permission_ledger, "canonical_json", lambda value: (calls.append(1), real(value))[1])
    led._append("note", "x", ANDY, "terminal", {}, at=T("2026-11-02"))
    assert len(calls) == 2
    assert _follows(led)
    led.close()


# ---------------------------------------------------------------- the section 2 review (the fresh Pi reviewer)

def _page_at(path, number):
    """(offset, size) of page `number` of the SQLite file at `path`."""
    con = sqlite3.connect(path)
    try:
        size = con.execute("PRAGMA page_size").fetchone()[0]
    finally:
        con.close()
    return (number - 1) * size, size


def _rootpage(path, name):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT rootpage FROM sqlite_master WHERE name = ?", (name,)).fetchone()[0]
    finally:
        con.close()


def test_m1_a_torn_meta_index_page_never_reads_a_gate_at_enforce_as_off(tmp_path):
    """The review's M1 (its probe_meta_index.py). The first raise of the gate inserts `gate` and `gate_raised`; the root
    page of meta's autoindex written back as it was before the raise hides both from a read through the index, so the
    gate read `off` on a ledger at enforce, and under `off` nothing calls state(), which refuses it. meta is read past
    its index, as the projection digest reads it."""
    _created(tmp_path)
    make_house(tmp_path, "lighthouse")
    path = ledger_path(tmp_path)
    offset, size = _page_at(path, _rootpage(path, "sqlite_autoindex_meta_1"))
    before = path.read_bytes()[offset:offset + size]
    led = Ledger.open(tmp_path)
    raise_gate(led, "enforce")
    led.close()
    with open(path, "r+b") as f:                     # the tear: no connection is open on the file here
        f.seek(offset)
        f.write(before)
    con = sqlite3.connect(path)
    try:                                             # the tear is real: through the index the two keys are gone
        assert {k for (k,) in con.execute("SELECT key FROM meta ORDER BY key")} & {"gate", "gate_raised"} == set()
        assert {k for (k,) in con.execute("SELECT key FROM meta NOT INDEXED")} >= {"gate", "gate_raised"}
    finally:
        con.close()
    assert effective_gate(tmp_path, houses(tmp_path)) == Gate("enforce", None)
    led = Ledger.open_read_only(tmp_path)
    try:
        assert led.meta()["gate"] == "enforce"
    finally:
        led.close()
    with pytest.raises(LedgerUnreadable, match="SQLite's integrity check of the file"):
        _state(tmp_path)


def test_m2_rebuild_replays_a_whole_log_when_a_table_page_is_malformed(tmp_path, monkeypatch, capsys):
    """The review's M2 (its probe_rebuild_malformed.py): the log is whole, one table's root page is not. Rebuild is the
    recovery path (D7), so it says the old tables could not be read, with SQLite's words, and replays the log anyway;
    the command prints it."""
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    _uncollected(tmp_path)
    path = ledger_path(tmp_path)
    offset, size = _page_at(path, _rootpage(path, "collection_members"))
    with open(path, "r+b") as f:
        f.seek(offset)
        f.write(b"\xff" * size)
    led = Ledger.open_read_only(tmp_path)
    try:
        assert led.verify() is None                                       # the chain is whole
        dest = led.rebuild(tmp_path / "copy")
        assert isinstance(led.rebuilt_differs, str)
        assert led.rebuilt_differs.startswith("the old tables could not be read") and "malformed" in led.rebuilt_differs
    finally:
        led.close()
    assert M2 not in _live(_state(dest)) and M3 not in _live(_state(dest))     # the replay holds the uncollect
    assert cli_main(["rebuild", "--out", str(tmp_path / "copy2")]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "The old tables could not be read (database disk image is malformed)" in out
    assert f"move {ledger_path(tmp_path / 'copy2')} to {ledger_path(tmp_path)}" in out


def test_s4_an_append_waits_longer_for_the_lock_on_a_larger_ledger(tmp_path, monkeypatch):
    """The review's S4: on a loaded Pi the full check at U24's reference shape (274 MB) took 19-22 s, past a fixed
    12 s, so a writer behind a rare check failed at COMMIT with nothing written. The wait scales with the file's size,
    read by stat: max(12 s, 0.35 s per MB). The re-check's S1: the check's cost follows projected rows (about 8 us a
    row at load 8), and at 0.16 s per MB a dense ledger had no margin past about 75 MB."""
    assert permission_ledger._append_busy_ms(274_000_000) >= 95_000
    assert permission_ledger._append_busy_ms(75_000_000) >= 26_000
    assert permission_ledger._append_busy_ms(28_700_000) == 12_000          # Task 0's shape: the floor
    assert permission_ledger._append_busy_ms(4096) == 12_000
    real = os.stat
    monkeypatch.setattr(permission_ledger, "_stat", lambda path: SimpleNamespace(
        **{f: getattr(real(path), f) for f in ("st_dev", "st_ino", "st_ctime_ns")}, st_size=274_000_000))
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    seen, project = [], Ledger._project
    monkeypatch.setattr(Ledger, "_project", lambda self, *a, **k: (
        seen.append(self.conn.execute("PRAGMA busy_timeout").fetchone()[0]), project(self, *a, **k))[1])
    led._append("note", "x", ANDY, "terminal", {}, at=T("2026-11-02"))
    assert seen == [permission_ledger._append_busy_ms(274_000_000)] and seen[0] >= 40_000
    assert led.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    led.close()


def test_s5_d9s_append_timing_takes_the_two_ledgers_appends_in_turn(tmp_path, monkeypatch):
    """The review's S5: the append bound flaked once in six runs on the Pi, as a difference of two medians taken one
    ledger after the other. The appends now alternate between the stamped ledger and its unstamped copy, and the
    bound is on the median of the paired differences."""
    _created(tmp_path / "home")
    order, real = [], Ledger._append
    monkeypatch.setattr(Ledger, "_append", lambda self, *a, **k: (order.append(self.path.parent.parent.name),
                                                                  real(self, *a, **k))[1])
    got = digest_timings(tmp_path / "home", runs=1, appends=6)
    assert order == ["home", "home-unstamped"] * 6
    assert set(got) == {"rare", "match", "append"}


def test_nit_a_moved_file_is_marked_only_at_the_size_it_was_checked_at(tmp_path):
    """The review's nit on `_mark_moved`: the inode, counter and head, and the size too."""
    _created(tmp_path)
    _marker(tmp_path).unlink()
    key = _key_now(tmp_path)
    permission_ledger._mark_moved(ledger_path(tmp_path), dataclasses.replace(key, size=key.size + 4096))
    assert not _marker(tmp_path).exists()
    permission_ledger._mark_moved(ledger_path(tmp_path), key)                   # the control
    assert json.loads(_marker(tmp_path).read_text())["size"] == key.size


def test_nit_a_close_that_fails_keeps_the_connections_count(tmp_path):
    """The review's nit on `_Conn.close`: a connection still open after a close that raised (here, from another
    thread) keeps its count, so its file's descriptor stays open under its locks."""
    _created(tmp_path)
    led = Ledger.open_read_only(tmp_path)
    errors = []
    other = threading.Thread(target=lambda: errors.append(_raises(led.conn.close)))
    other.start()
    other.join()
    assert errors and isinstance(errors[0], sqlite3.ProgrammingError)
    assert led.conn._key in permission_ledger._HELD
    led.close()
    assert led.conn._key not in permission_ledger._HELD


def _raises(call):
    try:
        call()
    except Exception as e:  # noqa: BLE001 - returned for the test to look at
        return e
    return None


def test_s6_a_fresh_file_carries_its_parts_in_memory_and_writes_its_digest_once(tmp_path, monkeypatch):
    """The review's S6: rebuild and migrate own a fresh file, so its appends carry the parts in memory and write
    meta.projection and projection_parts once, at `_finish_fresh`, just before its one full check; no append writes
    them. The copy's digest is the old ledger's, whose tables it replays."""
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    for i in range(5):
        led._append("register-agent", f"agent:a{i}", ANDY, "terminal", {"insert": [{"table": "agents", "row": {
            "id": f"agent:a{i}", "acts_for": ANDY, "created_seq": "@seq"}}]}, at=T("2026-11-02") + i)
    seen, finish = [], Ledger._finish_fresh

    def finishing(self):
        seen.append(self.conn.execute("SELECT value FROM meta WHERE key = 'projection'").fetchone()[0])
        return finish(self)

    monkeypatch.setattr(Ledger, "_finish_fresh", finishing)
    dest = led.rebuild(tmp_path / "copy")
    assert len(seen) == 1 and seen[0].startswith("0:")                   # the stamp _blank wrote, as it was
    copy = Ledger.open_read_only(dest)
    try:
        assert copy.meta()["projection"] == led.meta()["projection"] and copy.meta()["projection"].startswith("6:")
        assert _follows(copy)
    finally:
        copy.close()
        led.close()
