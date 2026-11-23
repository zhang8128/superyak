"""P 12.3, "Before the raise, no house carries the id" (2026-11-19; R50 revised; Serenity's yes, all hands fdbb4496;
fresh review docs/superpowers/reviews/2026-11-19-gate-restore-reads-closed-review.md). A served house that carries
this ledger's id while the gate was never raised reads closed, and a never-raised `gate off` removes every house's
mark. These fail on the code before the change: there a restored older ledger read `off`."""
import shutil
import sqlite3

import pytest

from permission_ledger import Ledger, LedgerBusy, effective_gate, ledger_path
from permissions import RuleError
from tests.permissions_support import ANDY, T, do, house_meta, make_house

CAUSE = "carries this ledger's id but this ledger was never raised"


def _mark(house, value):
    con = sqlite3.connect(house)
    con.execute("INSERT INTO meta VALUES ('permissions_ledger_id', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (value,))
    con.commit()
    con.close()


def _restored_from_before_the_raise(tmp_path):
    """A ledger raised to `shadow` with its published house marked, then put back in place from a copy taken before
    the raise (path 1): the house carries the id, the ledger never raised."""
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    house = make_house(tmp_path, "lighthouse")
    led.close()
    before = ledger_path(tmp_path).read_bytes()
    led = Ledger.open(tmp_path)
    do(led, ANDY, "gate", now="2026-11-02", mode="shadow")
    assert house_meta(house)["permissions_ledger_id"] == led.meta()["ledger_id"]
    led.close()
    ledger_path(tmp_path).write_bytes(before)                    # restored: no connection holds the file here
    ledger_path(tmp_path).with_name("permissions.verified").unlink(missing_ok=True)
    return house


def test_a_ledger_restored_from_before_the_raise_reads_closed(tmp_path):
    house = _restored_from_before_the_raise(tmp_path)
    gate = effective_gate(tmp_path, [house])
    assert gate.mode == "closed" and CAUSE in gate.cause and "engram-permissions gate" in gate.cause
    assert gate.cause.count(". ") == 0                              # one sentence (R7; test_permissions_gate's rule)


@pytest.mark.parametrize("mark", ["unreadable", "an-earlier-ledger", "this-ledger"])
def test_gate_off_on_a_never_raised_ledger_removes_each_mark(tmp_path, mark):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    house = make_house(tmp_path, "lighthouse")
    _mark(house, led.meta()["ledger_id"] if mark == "this-ledger" else mark)
    assert effective_gate(tmp_path, [house]).mode == "closed"
    out = do(led, ANDY, "gate", now="2026-11-02", mode="off")
    assert "permissions_ledger_id" not in house_meta(house)
    assert effective_gate(tmp_path, [house]).mode == "off" and "gate_raised" not in led.meta()
    body = led.conn.execute("SELECT body FROM ledger_log WHERE seq = ?", (out.seq,)).fetchone()[0]
    assert '".engram/instances/lighthouse/graph.db"' in body       # `houses`: the house whose mark it changed
    led.close()


def test_a_restored_ledger_recovers_by_gate_off_or_a_new_raise(tmp_path):
    house = _restored_from_before_the_raise(tmp_path)
    copy = tmp_path / "copy"
    shutil.copytree(tmp_path / ".engram", copy / ".engram")
    led = Ledger.open(tmp_path)
    do(led, ANDY, "gate", now="2026-11-03", mode="off")
    led.close()
    assert effective_gate(tmp_path, [house]).mode == "off" and "permissions_ledger_id" not in house_meta(house)
    other = copy / ".engram" / "instances" / "lighthouse" / "graph.db"
    led = Ledger.open(copy)
    do(led, ANDY, "gate", now="2026-11-03", mode="shadow")
    led.close()
    assert effective_gate(copy, [other]).mode == "shadow"


def test_a_first_raise_cut_short_reads_closed_and_says_the_houses_changed(tmp_path, monkeypatch):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    house = make_house(tmp_path, "lighthouse")

    def busy(self, kind, *args, **kwargs):
        raise LedgerBusy(f"{self.path}: the ledger changed under this write 3 times running; nothing was written, "
                         "so try again")
    monkeypatch.setattr(Ledger, "_append", busy)
    with pytest.raises(LedgerBusy) as e:
        do(led, ANDY, "gate", now="2026-11-02", mode="shadow")
    monkeypatch.undo()
    assert "nothing was written" not in str(e.value)
    assert "houses lighthouse" in str(e.value) and "closed" in str(e.value)
    assert house_meta(house)["permissions_ledger_id"] == led.meta()["ledger_id"] and "gate_raised" not in led.meta()
    gate = effective_gate(tmp_path, [house])
    assert gate.mode == "closed" and CAUSE in gate.cause
    do(led, ANDY, "gate", now="2026-11-03", mode="shadow")         # raise again: the move for a raise cut short
    assert effective_gate(tmp_path, [house]).mode == "shadow"
    led.close()


def test_a_marking_that_fails_at_a_later_house_names_the_houses_it_changed(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    first = make_house(tmp_path, "lighthouse")
    second = make_house(tmp_path, "zzz")
    second.chmod(0o400)
    try:
        with pytest.raises(RuleError) as e:
            do(led, ANDY, "gate", now="2026-11-02", mode="shadow")
    finally:
        second.chmod(0o600)
    text = str(e.value)
    assert "house zzz could not be marked" in text and "lighthouse" in text
    assert "nothing was recorded, run the gate again" not in text
    assert effective_gate(tmp_path, [first]).mode == "closed"
    led.close()


def test_the_gate_plan_sets_apart_a_house_that_carries_this_ledgers_id_before_the_raise(tmp_path):
    from permission_cli import gate_plan_lines

    _restored_from_before_the_raise(tmp_path)
    led = Ledger.open_read_only(tmp_path)
    try:
        plan = led.gate_plan()
    finally:
        led.close()
    assert [p.name for p in plan["this_id"]] == ["graph.db"]
    text = "\n".join(gate_plan_lines(plan, marking=False))
    assert "the yes removes the mark of each that carries one" in text
    assert "carry this ledger's id though it was never raised" in text and "revoked" in text
    raise_text = "\n".join(gate_plan_lines(plan, marking=True))
    assert "carry this ledger's id though it was never raised" in raise_text


def test_a_raw_sqlite_error_at_the_log_write_still_says_the_houses_changed(tmp_path, monkeypatch):
    """The reader's A on 4c6efb53 (all hands 0b392987): a never-raised `gate off` removes the marks, then its log row
    meets a raw SQLite error (a disk error, a commit that fails), not LedgerBusy or LedgerUnreadable. The refusal
    still says which houses changed and what the gate reads now."""
    house = _restored_from_before_the_raise(tmp_path)
    led = Ledger.open(tmp_path)

    def disk(self, kind, *args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(Ledger, "_append", disk)
    with pytest.raises(sqlite3.OperationalError) as e:
        do(led, ANDY, "gate", now="2026-11-03", mode="off")
    monkeypatch.undo()
    text = str(e.value)
    assert "disk I/O error" in text and "houses lighthouse" in text and "the gate reads off now" in text
    assert "permissions_ledger_id" not in house_meta(house) and effective_gate(tmp_path, [house]).mode == "off"
    led.close()


def test_a_read_only_marked_house_refuses_gate_off_and_takes_gate_shadow(tmp_path):
    """The reader's B on 4c6efb53: after a restore, a house that carries this ledger's id and can't be written
    refuses `gate off`, which must remove its mark, and still reads closed; `gate shadow` passes it over, since its
    mark is already this ledger's, and raises the gate."""
    house = _restored_from_before_the_raise(tmp_path)
    led = Ledger.open(tmp_path)
    house.chmod(0o400)
    try:
        with pytest.raises(RuleError) as e:
            do(led, ANDY, "gate", now="2026-11-03", mode="off")
        assert "lighthouse" in str(e.value)
        assert effective_gate(tmp_path, [house]).mode == "closed" and "gate_raised" not in led.meta()
        do(led, ANDY, "gate", now="2026-11-03", mode="shadow")
    finally:
        house.chmod(0o600)
    assert effective_gate(tmp_path, [house]).mode == "shadow"
    led.close()
