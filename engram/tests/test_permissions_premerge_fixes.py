"""Serenity's pre-merge items on permissions-core 6f7344a: each test names its item."""
import shutil
import sqlite3
from collections import OrderedDict

import pytest

from permission_cli import main as cli_main
from permission_ledger import ENFORCE_WAITS as SHIPPED_ENFORCE_WAITS
from permission_ledger import Ledger, LedgerUnreadable, ledger_path
from permissions import RuleError
from tests.permissions_support import (  # noqa: F401
    ANDY, M2, M3, MEDICAL, cli_home, cli_home_with_house, do, e1_county_ledger, fake_tty, make_house, raise_gate,
    raised_ledger)
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


# ---------------------------------------------------------------- the claims: a tear of one row per column

def test_claims_verify_says_its_tail_checks_catch_a_tear_of_one_row_per_column(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    _revoked_r1(tmp_path)
    assert cli_main(["verify"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "catch a tear of one row per column" in out and "a tear across several rows of one column" in out
    assert "projection digest" in out and "that row's change is in the tables" not in out


@pytest.mark.xfail(strict=True, raises=pytest.fail.Exception,
                   reason="N1: a tear across several rows of one column reads whole until the projection digest")
def test_claims_a_tear_across_two_rows_of_one_column_still_reads_whole(tmp_path):
    """Andy uncollects m2 and m3 in one act; a tear keeps m3's removal and loses m2's. The column's highest is still
    the act's seq, so the tail checks pass and m2 reads as a member again. Once the projection digest refuses it,
    this passes and its xfail mark goes."""
    led = e1_county_ledger(tmp_path)
    seq = do(led, ANDY, "uncollect", collection=MEDICAL, objects=[M2, M3], now="2026-11-02").seq
    led.close()
    _sql(tmp_path, "UPDATE collection_members SET removed_seq = NULL, removed_by = NULL "
                   f"WHERE removed_seq = {seq} AND object = '{M2}'")
    try:
        state = _state(tmp_path)
    except LedgerUnreadable:
        return
    assert M2 in {r.object for r in state.collection_members.get(MEDICAL) if r.removed_seq is None}
    pytest.fail("a tear across two rows of one column read whole: m2 is a member again")


# ---------------------------------------------------------------- item 5: `gate enforce` waits for the digest

@pytest.fixture
def enforce_waits(monkeypatch):
    """The refusal as shipped, read when this module was imported (tests/conftest.py lifts it for each test)."""
    import permission_ledger
    assert SHIPPED_ENFORCE_WAITS and "projection digest" in SHIPPED_ENFORCE_WAITS
    monkeypatch.setattr(permission_ledger, "ENFORCE_WAITS", SHIPPED_ENFORCE_WAITS)
    return SHIPPED_ENFORCE_WAITS


def test_item5_the_gate_act_refuses_enforce_until_the_digest_with_the_reason(tmp_path, enforce_waits):
    led = raised_ledger(tmp_path, mode="shadow")
    try:
        before = led.seq()
        with pytest.raises(RuleError, match="projection digest") as e:
            raise_gate(led, "enforce", now="2026-11-03")
        assert enforce_waits in str(e.value) and led.seq() == before          # nothing written
        assert led.meta()["gate"] == "shadow"
        for mode in ("off", "shadow"):                                         # unchanged
            raise_gate(led, mode, now="2026-11-04")
            assert led.meta()["gate"] == mode
    finally:
        led.close()


def test_item5_gate_enforce_refuses_before_it_asks_for_a_yes(cli_home_with_house, fake_tty, capsys, enforce_waits):
    shown = fake_tty.shown()
    assert cli_main(["gate", "enforce"]) == 1
    assert "refused: 12.3 the gate: enforce waits for the ledger's projection digest" in capsys.readouterr().err
    assert fake_tty.shown() == shown                                           # no yes was asked
    fake_tty.answer_the_printed_code()
    assert cli_main(["gate", "shadow"]) == 0                                   # shadow is as before


def test_item5_a_gate_already_at_enforce_reads_as_it_is_and_can_be_lowered(tmp_path, monkeypatch):
    import permission_ledger
    from permission_ledger import Gate, effective_gate, houses
    led = raised_ledger(tmp_path, mode="enforce")                 # raised before the refusal (conftest lifts it)
    monkeypatch.setattr(permission_ledger, "ENFORCE_WAITS", SHIPPED_ENFORCE_WAITS)
    try:
        assert effective_gate(tmp_path, houses(tmp_path)) == Gate("enforce", None)
        with pytest.raises(RuleError, match="projection digest"):
            raise_gate(led, "enforce", now="2026-11-03")
        raise_gate(led, "shadow", now="2026-11-03")
        assert effective_gate(tmp_path, houses(tmp_path)) == Gate("shadow", None)
    finally:
        led.close()
