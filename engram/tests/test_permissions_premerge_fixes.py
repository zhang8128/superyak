"""Serenity's pre-merge items on permissions-core 6f7344a: each test names its item."""
import shutil
import sqlite3
from collections import OrderedDict

import pytest

from permission_cli import main as cli_main
from permission_ledger import Ledger, LedgerUnreadable, ledger_path
from tests.permissions_support import ANDY, do, e1_county_ledger, make_house, raise_gate
from tests.test_permissions_recheck_fixes import _cut_last_row_and_head
from tests.test_permissions_serenity_fixes import _revoked_r1, _sql, _state


def _indexes(home) -> set:
    con = sqlite3.connect(ledger_path(home))
    try:
        return {(t, n) for n, t in con.execute("SELECT name, tbl_name FROM sqlite_master WHERE type = 'index'")}
    finally:
        con.close()


# ---------------------------------------------------------------- N4: a writer's max of revoked_seq reads an index

_REVOKED = {("records", "records_revoked"), ("permission_grants", "grants_revoked")}


def _writers_max_plan(led, table, column) -> str:
    """The query plan of the read `_append` makes for the highest table.column, caught as it runs."""
    sql = []
    led.conn.set_trace_callback(sql.append)
    try:
        led._max_seq(table, column, {})
    finally:
        led.conn.set_trace_callback(None)
    (query,) = sql
    return "; ".join(r[3] for r in led.conn.execute("EXPLAIN QUERY PLAN " + query))


def test_n4_a_writer_reads_the_highest_revoked_seq_through_a_partial_index(tmp_path):
    """At the records bound a scan of every record took each append from 0.34 ms to 3.25 ms and rebuild from 6.5 s
    to 24.4 s; the max reads the partial index instead."""
    _revoked_r1(tmp_path)
    assert _REVOKED <= _indexes(tmp_path)
    led = Ledger.open_read_only(tmp_path)
    try:
        for table, index in sorted(_REVOKED):
            plan = _writers_max_plan(led, table, "revoked_seq")
            assert f"USING COVERING INDEX {index}" in plan, plan
    finally:
        led.close()


def test_n4_a_writing_open_adds_the_indexes_to_an_older_ledger(tmp_path):
    _revoked_r1(tmp_path)
    _sql(tmp_path, "DROP INDEX records_revoked", "DROP INDEX grants_revoked")
    Ledger.open_read_only(tmp_path).close()
    assert not _REVOKED & _indexes(tmp_path)             # a read-only open writes nothing
    Ledger.open(tmp_path).close()
    assert _REVOKED <= _indexes(tmp_path)


# ---------------------------------------------------------------- N2: verify reads past the indexes

def _tear_index(home, name, keep):
    """Index `name` as a torn index page leaves it: its b-tree holds only the rows the SQL condition `keep` admits,
    while the schema still names the whole index. Built under that condition, then renamed in the schema."""
    con = sqlite3.connect(ledger_path(home))
    try:
        (sql,) = con.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)).fetchone()
        con.execute(f"DROP INDEX {name}")
        con.execute(sql + (" AND " if " WHERE " in sql else " WHERE ") + keep)
        con.commit()
        con.execute("PRAGMA writable_schema = ON")
        con.execute("UPDATE sqlite_master SET sql = ? WHERE type = 'index' AND name = ?", (sql, name))
        con.commit()
    finally:
        con.close()


def test_n2_verify_reads_the_revocation_a_torn_index_hides(tmp_path, monkeypatch, capsys):
    """The revoke's log row lost and the meta page old, so only R1's revoked_seq says the tail is cut, and the
    index page that holds it torn old too: the writer's index read misses it, verify's read of the table does not,
    and SQLite's check names the index."""
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    _, seq = _revoked_r1(tmp_path)
    _cut_last_row_and_head(tmp_path, seq)
    _tear_index(tmp_path, "records_revoked", f"revoked_seq < {seq}")
    led = Ledger.open_read_only(tmp_path)
    try:
        assert (led._max_seq("records", "revoked_seq", {}) or 0) < seq       # the index hides the revocation
        top, problems = led.integrity()
    finally:
        led.close()
    assert top == seq - 1
    assert f"records.revoked_seq names seq {seq}, past the log's last row {seq - 1}" in problems
    assert [p for p in problems if p.startswith("SQLite's integrity check of the file: ") and "records_revoked" in p]
    assert cli_main(["verify"]) == 1
    out = capsys.readouterr().out
    assert "does not verify" in out and f"records.revoked_seq names seq {seq}, past the log's last row" in out


def test_n2_verify_fails_on_any_answer_of_sqlites_check_but_ok(tmp_path, monkeypatch, capsys):
    """A torn page of an index no tail check reads (records_layer): the tables and the log are whole, so only
    SQLite's check finds it, and verify fails."""
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    _revoked_r1(tmp_path)
    con = sqlite3.connect(ledger_path(tmp_path))
    (layer,) = con.execute("SELECT layer FROM records ORDER BY rowid LIMIT 1").fetchone()
    con.close()
    _tear_index(tmp_path, "records_layer", f"layer != '{layer}'")
    led = Ledger.open_read_only(tmp_path)
    try:
        top, problems = led.integrity()
        assert led.state().seq == top                          # a reader still reads it: it reads records whole
    finally:
        led.close()
    assert problems and all(p.startswith("SQLite's integrity check of the file: ") for p in problems), problems
    assert any("records_layer" in p for p in problems)
    assert cli_main(["verify"]) == 1
    out = capsys.readouterr().out
    assert "does not verify" in out and "records_layer" in out and "No reader runs SQLite's integrity check" in out


# ---------------------------------------------------------------- N5: the last row's parse is kept by its head

def _counting_parses(monkeypatch):
    """A fresh `_LAST_SETS` and a list of each body `_seq_sets` parses."""
    import permission_ledger
    parsed, real = [], permission_ledger._seq_sets
    monkeypatch.setattr(permission_ledger, "_LAST_SETS", OrderedDict())
    monkeypatch.setattr(permission_ledger, "_seq_sets", lambda text: parsed.append(text) or real(text))
    return parsed


def _head_of(home) -> str:
    led = Ledger.open_read_only(home)
    try:
        return led.meta()["head"]
    finally:
        led.close()


def test_n5_a_read_whose_head_is_unchanged_parses_nothing(tmp_path, monkeypatch):
    _revoked_r1(tmp_path)
    parsed = _counting_parses(monkeypatch)
    led = Ledger.open_read_only(tmp_path)
    try:
        led.state()
        led.state()
        assert led.integrity()[1] == []
    finally:
        led.close()
    for _ in range(2):                        # a fresh open of the same ledger, as each daemon frame makes
        _state(tmp_path)
    assert len(parsed) == 1


def test_n5_a_changed_head_is_never_served_the_old_parse(tmp_path, monkeypatch):
    """Two copies of one ledger whose last rows share a seq: a gate act, which sets no seq column, and R1's revoke,
    whose change a tear then loses from `records`. Read after the gate act's, the revoke's head parses its own body
    and refuses; served the gate act's parse, it would read whole and R1's allow would come back."""
    base, gated, revoked = tmp_path / "base", tmp_path / "gated", tmp_path / "revoked"
    led = e1_county_ledger(base)
    r1 = led.ids.R1
    led.close()
    for home in (gated, revoked):
        (home / ".engram").mkdir(parents=True)
        shutil.copy(ledger_path(base), ledger_path(home))
    make_house(gated, "lighthouse")
    led = Ledger.open(gated)
    raise_gate(led, "shadow")
    led.close()
    led = Ledger.open(revoked)
    seq = do(led, ANDY, "revoke", now="2026-11-02", record=r1, reason="no longer").seq
    led.close()
    assert _head_of(gated).split(":")[0] == _head_of(revoked).split(":")[0] == str(seq)
    assert _head_of(gated) != _head_of(revoked)
    parsed = _counting_parses(monkeypatch)
    assert _state(gated).seq == seq and len(parsed) == 1
    _sql(revoked, "UPDATE records SET revoked = NULL, revoked_by = NULL, revoke_reason = NULL, revoked_seq = NULL "
                  f"WHERE revoked_seq = {seq}")
    with pytest.raises(LedgerUnreadable, match=f"the log's last row, seq {seq}, sets records.revoked_seq"):
        _state(revoked)
    assert len(parsed) == 2
    assert _state(gated).seq == seq and len(parsed) == 2            # the gate act's parse is still kept
