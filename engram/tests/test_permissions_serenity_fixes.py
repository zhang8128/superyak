"""Serenity's section 2 verdict on permissions-core 503fd97: each test names its item."""
import shutil
import sqlite3
from pathlib import Path

import pytest

from permission_cli import main as cli_main
from permission_ledger import _SEQ_COLUMNS, Ledger, LedgerUnreadable, ledger_path
from permissions import decide
from tests.permissions_support import (  # noqa: F401
    ANDY, HOME, M1, M1_TEXT, M3, T, deliver_m1_through, do, e1_county_ledger, keep_world,
    keep_world_with_imprint_allowed, read_by_ph, receipt_rows)
from tests.test_recall_margins import engram_server_env  # noqa: F401


# ---------------------------------------------------------------- item 1: a cut log tail reads as unreadable (P 5.6)

def _revoked_r1(home):
    """E1's county and Andy's side, then Andy revokes R1, so ph-coordinator's read of m1 is refused. Returns the
    use and the revoke's seq."""
    led = e1_county_ledger(home)
    use = read_by_ph(M1, T("2026-11-03"))
    assert decide(led.state(), use).allowed
    seq = do(led, ANDY, "revoke", now="2026-11-02", record=led.ids.R1, reason="no longer").seq
    assert not decide(led.state(), use).allowed
    led.close()
    return use, seq


def _sql(home, *statements):
    con = sqlite3.connect(ledger_path(home))
    try:
        for s in statements:
            con.execute(s)
        con.commit()
    finally:
        con.close()


def _cut_last_log_row(home):
    """A torn copy (taken mid-commit, without its journal): the last log row is lost, its projection kept."""
    _sql(home, "DELETE FROM ledger_log WHERE seq = (SELECT MAX(seq) FROM ledger_log)")


def _state(home):
    led = Ledger.open_read_only(home)
    try:
        return led.state()
    finally:
        led.close()


def test_item1_a_cut_log_tail_never_brings_back_a_revoked_allow(tmp_path):
    _revoked_r1(tmp_path)
    _cut_last_log_row(tmp_path)
    with pytest.raises(LedgerUnreadable, match="The log's tail was cut"):
        _state(tmp_path)


def test_item1_a_cut_tail_whose_head_was_lost_too_is_caught_by_the_projected_seq(tmp_path):
    """The meta page old as well: only the revoked_seq the records still hold says the tail is cut."""
    _, seq = _revoked_r1(tmp_path)
    led = Ledger.open_read_only(tmp_path)
    digest = led.conn.execute("SELECT digest FROM ledger_log WHERE seq = ?", (seq - 1,)).fetchone()[0]
    led.close()
    _cut_last_log_row(tmp_path)
    _sql(tmp_path, f"UPDATE meta SET value = '{seq - 1}:{digest}' WHERE key = 'head'")
    with pytest.raises(LedgerUnreadable, match=f"records.revoked_seq names seq {seq}"):
        _state(tmp_path)


def test_item1_a_log_row_whose_projection_was_lost_is_caught_by_the_head(tmp_path):
    """The converse tear: the log row is there, the revocation in `records` and the head in `meta` are not."""
    _, seq = _revoked_r1(tmp_path)
    led = Ledger.open_read_only(tmp_path)
    digest = led.conn.execute("SELECT digest FROM ledger_log WHERE seq = ?", (seq - 1,)).fetchone()[0]
    led.close()
    _sql(tmp_path, f"UPDATE records SET revoked = NULL, revoked_by = NULL, revoke_reason = NULL, revoked_seq = NULL "
                   f"WHERE revoked_seq = {seq}",
         f"UPDATE meta SET value = '{seq - 1}:{digest}' WHERE key = 'head'")
    with pytest.raises(LedgerUnreadable, match="head"):
        _state(tmp_path)


def test_item1_a_writer_refuses_to_append_onto_a_cut_tail(tmp_path):
    _revoked_r1(tmp_path)
    _cut_last_log_row(tmp_path)
    led = Ledger.open(tmp_path)
    try:
        with pytest.raises(LedgerUnreadable):
            led.note_first_lane("mem:S/episode/m9", "personal", "2026-10-01T00:00:00+00:00", store_id="S",
                                now=T("2026-11-04"))
        with pytest.raises(LedgerUnreadable):
            do(led, ANDY, "register-person", now="2026-11-04", person="person:late")
    finally:
        led.close()


@pytest.fixture(scope="module")
def every_table_ledger(tmp_path_factory):
    """E1's ledger with a row in every projected table: R1 revoked, a group, a kept copy, a lane note."""
    home = tmp_path_factory.mktemp("every-table")
    _revoked_r1(home)
    led = Ledger.open(home)
    do(led, ANDY, "group", now="2026-11-03", group="group:helpers", owner=ANDY, members=["agent:rio-grande"])
    led.record_copy("mem:K/episode/c1", M3, now=T("2026-11-03"))
    led.note_first_lane("mem:S/episode/m9", "personal", "2026-10-01T00:00:00+00:00", store_id="S",
                        now=T("2026-11-03"))
    tables = led.tables()
    led.close()
    assert all(tables[t] for t in _SEQ_COLUMNS), [t for t in _SEQ_COLUMNS if not tables[t]]
    return home


@pytest.mark.parametrize("table,column", [(t, c) for t, cs in _SEQ_COLUMNS.items() for c in cs])
def test_item1_any_projected_seq_past_the_log_reads_as_unreadable(every_table_ledger, tmp_path, table, column):
    """The newest row of each table names a seq past the log, as the projection of a lost last row would."""
    home = tmp_path / "home"
    (home / ".engram").mkdir(parents=True)
    shutil.copy(ledger_path(every_table_ledger), ledger_path(home))
    assert _state(home).seq > 0
    _sql(home, f"UPDATE {table} SET {column} = (SELECT MAX(seq) + 1 FROM ledger_log) "
               f"WHERE rowid = (SELECT MAX(rowid) FROM {table})")
    with pytest.raises(LedgerUnreadable, match=f"{table}.{column} names seq"):
        _state(home)


def test_item1_verify_reports_a_whole_ledger_and_a_cut_tail(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    _, seq = _revoked_r1(tmp_path)
    assert cli_main(["verify"]) == 0
    out = capsys.readouterr().out
    assert f"{seq} log rows" in out and "verifies" in out
    _cut_last_log_row(tmp_path)
    assert cli_main(["verify"]) == 1
    out = capsys.readouterr().out
    assert "does not verify" in out and f"meta.head names seq {seq}" in out
    assert f"records.revoked_seq names seq {seq}, past the log's last row {seq - 1}" in out


def test_item1_verify_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    _revoked_r1(tmp_path)
    _cut_last_log_row(tmp_path)
    before = ledger_path(tmp_path).read_bytes()
    assert cli_main(["verify"]) == 1
    assert ledger_path(tmp_path).read_bytes() == before
