"""The section 2 re-check of permissions-core 914113d (for Serenity): each test names its item."""
import sqlite3

import pytest

from permission_cli import main as cli_main
from permission_ledger import Gate, Ledger, LedgerUnreadable, effective_gate, houses, ledger_path
from permissions import decide
from tests.permissions_support import (
    ANDY, M1, M3, T, add_subject, do, raise_gate, raised_ledger, remove_subject)
from tests.test_permissions_serenity_fixes import _revoked_r1


def _meta(home) -> dict:
    con = sqlite3.connect(ledger_path(home))
    try:
        return dict(con.execute("SELECT key, value FROM meta").fetchall())
    finally:
        con.close()


def _put_meta(home, meta: dict) -> None:
    """The `meta` page as it was: every key set back to `meta`'s value, and no other key."""
    con = sqlite3.connect(ledger_path(home))
    try:
        con.execute("DELETE FROM meta")
        con.executemany("INSERT INTO meta VALUES(?, ?)", meta.items())
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------- must-fix 1: the gate checks the log's tail

def test_must_fix_1_a_gate_whose_meta_page_tore_old_reads_closed_never_the_older_mode(tmp_path):
    """The ledger raised to `shadow`, then to `enforce`. A copy taken mid-commit keeps the `enforce` act's log row
    but not its `meta` page: the gate reads `shadow` and the head is one row back. Under shadow an unreadable ledger
    sends the frame to the legacy path, which serves what enforce refuses, so the gate must read closed."""
    led = raised_ledger(tmp_path, mode="shadow")
    before = _meta(tmp_path)
    raise_gate(led, "enforce", now="2026-11-03")
    top = led.seq()
    led.close()
    assert effective_gate(tmp_path, houses(tmp_path)) == Gate("enforce", None)
    _put_meta(tmp_path, before)
    assert before["gate"] == "shadow" and before["head"].startswith(f"{top - 1}:")
    gate = effective_gate(tmp_path, houses(tmp_path))
    assert gate.mode == "closed" and f"meta.head names seq {top - 1}" in gate.cause
    assert "verify" in gate.cause


def test_must_fix_1_a_ledger_with_no_head_yet_reads_its_gate_as_before(tmp_path):
    """A ledger made before R48 has no head until its next write: its gate reads as it did."""
    raised_ledger(tmp_path, mode="shadow").close()
    meta = _meta(tmp_path)
    del meta["head"]
    _put_meta(tmp_path, meta)
    assert effective_gate(tmp_path, houses(tmp_path)) == Gate("shadow", None)
    led = Ledger.open_read_only(tmp_path)
    try:
        assert led.state().meta["gate"] == "shadow"
    finally:
        led.close()


# ---------------------------------------------------------------- must-fix 2: the last log row's change is in the tables

def _sql(home, *statements):
    con = sqlite3.connect(ledger_path(home))
    try:
        for s in statements:
            con.execute(s)
        con.commit()
    finally:
        con.close()


def _last_row_kept_its_change_lost(home, how):
    """A ledger whose last log row and head are whole while the page that held the row's change in one table is
    old. `how` names the read path of the column: a table a State reads whole (`records.revoked_seq`, set by an
    update), a per-object table's newest row (`lane_notes.seq`, an insert) and a partial index
    (`subjects.removed_seq`, an update). Returns (the use the change refused or would refuse, its seq, the column)."""
    use, seq = _revoked_r1(home)
    if how == "revoked":
        _sql(home, "UPDATE records SET revoked = NULL, revoked_by = NULL, revoke_reason = NULL, revoked_seq = NULL "
                   f"WHERE revoked_seq = {seq}")
        return use, seq, "records.revoked_seq"
    led = Ledger.open(home)
    try:
        if how == "lane-note":
            led.note_first_lane("mem:S/episode/m9", "personal", "2026-10-01T00:00:00+00:00", store_id="S",
                                now=T("2026-11-04"))
            seq = led.seq()
            _sql(home, f"DELETE FROM lane_notes WHERE seq = {seq}")
            return None, seq, "lane_notes.seq"
        add_subject(led, M1, "person:jenn", actor=ANDY, now="2026-11-04")
        remove_subject(led, M1, "person:jenn", actor=ANDY, now="2026-11-05")
        seq = led.seq()
        _sql(home, f"UPDATE subjects SET removed_seq = NULL, removed_by = NULL WHERE removed_seq = {seq}")
        return None, seq, "subjects.removed_seq"
    finally:
        led.close()


def _state(home):
    led = Ledger.open_read_only(home)
    try:
        return led.state()
    finally:
        led.close()


def _integrity(home):
    led = Ledger.open_read_only(home)
    try:
        return led.integrity()
    finally:
        led.close()


@pytest.mark.parametrize("how", ["revoked", "lane-note", "removed-subject"])
def test_must_fix_2_a_last_row_whose_change_was_lost_reads_as_unreadable(tmp_path, how):
    use, seq, column = _last_row_kept_its_change_lost(tmp_path, how)
    led = Ledger.open_read_only(tmp_path)
    try:
        assert led.meta()["head"].startswith(f"{seq}:") and led.verify() is None       # log and head are whole
    finally:
        led.close()
    with pytest.raises(LedgerUnreadable, match=f"the log's last row, seq {seq}, sets {column}"):
        _state(tmp_path)
    top, problems = _integrity(tmp_path)
    assert top == seq and [p for p in problems if column in p]


def test_must_fix_2_the_revoked_allow_stays_refused_and_verify_reports_the_tear(tmp_path, monkeypatch, capsys):
    """The re-check's probe: the revocation's log row and the head kept, the records page old."""
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    use, seq, _ = _last_row_kept_its_change_lost(tmp_path, "revoked")
    with pytest.raises(LedgerUnreadable, match="The log's tail was cut"):
        decide(_state(tmp_path), use)
    assert cli_main(["verify"]) == 1
    out = capsys.readouterr().out
    assert "does not verify" in out and f"the log's last row, seq {seq}, sets records.revoked_seq" in out


def test_must_fix_2_a_whole_ledger_after_each_kind_of_last_row_reads_and_verifies(tmp_path):
    """Whatever the last row set, a whole ledger passes the check: after a revoke, a lane note, a subject removed,
    a group, a kept copy and a gate act."""
    _revoked_r1(tmp_path)
    led = Ledger.open(tmp_path)
    try:
        steps = [
            lambda: led.note_first_lane("mem:S/episode/m9", "personal", "2026-10-01T00:00:00+00:00", store_id="S",
                                        now=T("2026-11-04")),
            lambda: add_subject(led, M1, "person:jenn", actor=ANDY, now="2026-11-04"),
            lambda: remove_subject(led, M1, "person:jenn", actor=ANDY, now="2026-11-05"),
            lambda: do(led, ANDY, "group", now="2026-11-05", group="group:helpers", owner=ANDY,
                       members=["agent:rio-grande"]),
            lambda: led.record_copy("mem:K/episode/c1", M3, now=T("2026-11-05"))]
        for step in [lambda: None] + steps:
            step()
            assert led.state().seq == led.seq() and led.integrity() == (led.seq(), [])
    finally:
        led.close()


# ---------------------------------------------------------------- should-fix 3: a writer never takes a lost row's seq

def _cut_last_row_and_head(home, seq):
    """The re-check's probe: the last log row (seq `seq`) lost and the meta page old too, so the head names seq - 1;
    the row's projection (R1's revocation) is kept."""
    led = Ledger.open_read_only(home)
    try:
        digest = led.conn.execute("SELECT digest FROM ledger_log WHERE seq = ?", (seq - 1,)).fetchone()[0]
    finally:
        led.close()
    _sql(home, f"DELETE FROM ledger_log WHERE seq = {seq}", f"UPDATE meta SET value = '{seq - 1}:{digest}' "
                                                            "WHERE key = 'head'")


def _log(home) -> list:
    con = sqlite3.connect(ledger_path(home))
    try:
        return con.execute("SELECT seq, kind, digest FROM ledger_log ORDER BY seq").fetchall()
    finally:
        con.close()


def test_should_fix_3_a_writer_with_no_state_refuses_the_seq_a_table_already_names(tmp_path):
    use, seq = _revoked_r1(tmp_path)
    _cut_last_row_and_head(tmp_path, seq)
    before = _log(tmp_path)
    led = Ledger.open(tmp_path)
    try:
        with pytest.raises(LedgerUnreadable, match=f"records.revoked_seq names seq {seq}, past the log's last row"):
            led.note_first_lane("mem:S/episode/m9", "personal", "2026-10-01T00:00:00+00:00", store_id="S",
                                now=T("2026-11-04"))
        with pytest.raises(LedgerUnreadable, match="The log's tail was cut"):
            led._append("lane-note-first", "mem:S/episode/m9", "tool:engram", "tool",
                        {"insert": [{"table": "lane_notes", "row": {"object": "mem:S/episode/m9", "lane": "personal",
                                                                    "at": T("2026-10-01"), "seq": "@seq"}}]},
                        at=T("2026-11-04"))
    finally:
        led.close()
    assert _log(tmp_path) == before and before[-1][0] == seq - 1        # nothing written at the lost seq
    with pytest.raises(LedgerUnreadable):
        decide(_state(tmp_path), use)


def test_should_fix_3_a_writer_with_no_state_never_covers_a_last_row_whose_change_was_lost(tmp_path):
    """Written over, the torn row would no longer be the last, and the tear would read as whole."""
    use, seq, _ = _last_row_kept_its_change_lost(tmp_path, "revoked")
    led = Ledger.open(tmp_path)
    try:
        with pytest.raises(LedgerUnreadable, match=f"the log's last row, seq {seq}, sets records.revoked_seq"):
            led.note_first_lane("mem:S/episode/m9", "personal", "2026-10-01T00:00:00+00:00", store_id="S",
                                now=T("2026-11-04"))
    finally:
        led.close()
    assert _log(tmp_path)[-1][0] == seq
    with pytest.raises(LedgerUnreadable):
        decide(_state(tmp_path), use)
