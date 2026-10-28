"""Serenity's pre-merge items on permissions-core 6f7344a: each test names its item."""
import sqlite3

from permission_ledger import Ledger, ledger_path
from tests.test_permissions_serenity_fixes import _revoked_r1, _sql


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
