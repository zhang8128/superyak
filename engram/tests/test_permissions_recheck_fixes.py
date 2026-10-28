"""The section 2 re-check of permissions-core 914113d (for Serenity): each test names its item."""
import sqlite3

import pytest

from permission_cli import main as cli_main
from permission_ledger import Gate, Ledger, LedgerUnreadable, effective_gate, houses, ledger_path
from permissions import decide
from tests.permissions_support import (  # noqa: F401
    ANDY, M1, M1_TEXT, M3, T, add_subject, cli_home, cli_home_with_house, deliver_m1_through, do, fake_tty,
    keep_world, keep_world_with_imprint_allowed, raise_gate, raised_ledger, receipt_rows, remove_subject)
from tests.test_permissions_serenity_fixes import _revoked_r1
from tests.test_permissions_p36 import guard_ledger  # noqa: F401
from tests.test_recall_margins import engram_server_env  # noqa: F401


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


# ---------------------------------------------------------------- should-fix 4: a failed kept copy leaves no allowed receipt

@pytest.mark.parametrize("how", ["raises", "no_store_id"])
def test_should_fix_4_an_unrecordable_kept_copy_under_enforce_leaves_no_imprint_receipt(
        keep_world_with_imprint_allowed, monkeypatch, how):
    """As a refused genome keep (Serenity's item 3): the keep is refused, so no receipt says it was allowed. Once the
    copy can be recorded, the keep that happens has its one allowed receipt."""
    import permission_ledger
    import server
    from tests.test_permissions_keep import REFUSED, _break_copy_record
    world = keep_world_with_imprint_allowed
    real_copy, real_store_id = permission_ledger.Ledger.record_copy, server._store_id
    deliver_m1_through(world, "neighbors")
    _break_copy_record(monkeypatch, how)
    assert server.remember(content=M1_TEXT) == REFUSED
    assert receipt_rows(world.root, "imprint") == []
    monkeypatch.setattr(permission_ledger.Ledger, "record_copy", real_copy)
    monkeypatch.setattr(server, "_store_id", real_store_id)
    out = server.remember(content=M1_TEXT)
    assert "episode_id" in out
    assert [(r["action"], r["allowed"]) for r in receipt_rows(world.root, "imprint")] == [("imprint", 1)]
    assert f"mem:{world.ids.PHC_STORE}/episode/{out['episode_id']}" in _state(world.root).copies


# ---------------------------------------------------------------- nits

@pytest.mark.parametrize("mode", ["off", "enforce"])
def test_nit_the_gate_plan_says_which_houses_the_yes_marks(cli_home_with_house, fake_tty, capsys, mode):
    """Under `off` on a ledger never raised, only a house marked `unreadable` or with another ledger's id is marked
    (R50), so the plan does not say every house is."""
    fake_tty.answer("wrong1"); assert cli_main(["gate", mode]) == 3
    out = capsys.readouterr().out
    assert "every house it will mark" not in out and out.index("instances/lighthouse/graph.db") < out.index("code:")
    if mode == "off":
        assert "the yes marks only each that carries `unreadable` or another ledger's id" in out
    else:
        assert "the yes marks each that does not carry this ledger's id" in out


def test_should_fix_4_held_receipts_that_cannot_be_written_refuse_the_keep_under_enforce(
        keep_world_with_imprint_allowed, monkeypatch):
    """The receipts are written after the copy now; when they cannot be, the keep is still refused, as before."""
    import permission_uses
    import server
    from tests.test_permissions_keep import REFUSED
    world = keep_world_with_imprint_allowed
    deliver_m1_through(world, "neighbors")
    before = server._storage.conn.execute("SELECT count(*) FROM episodes").fetchone()[0]

    def boom(self, row, subjects):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(permission_uses.Uses, "append", boom)
    assert server.remember(content=M1_TEXT) == REFUSED
    assert server._storage.conn.execute("SELECT count(*) FROM episodes").fetchone()[0] == before
    assert receipt_rows(world.root, "imprint") == []


def test_should_fix_4_the_guard_holds_an_allowed_keeps_receipt_and_the_owners_agent_is_told_why_it_failed(
        guard_ledger, monkeypatch):
    """Under `enforce` the guard writes no receipt for an allowed keep: it holds it for `record_copy`, with the reply
    the owner's agent gets, the cause included, if it cannot be written."""
    from permission_uses import uses_path
    from tests.test_permissions_keep import REFUSED
    from tests.test_permissions_p36 import _guard
    out = _guard("K", monkeypatch)
    assert out.reply is None and out.source == M3
    assert [(row.action, row.allowed) for row, _ in out.receipts] == [("imprint", 1)]
    assert out.unwritten == {**REFUSED, "cause": "the receipt could not be written"}
    assert not uses_path(guard_ledger).exists() or receipt_rows(guard_ledger, "imprint") == []


# ---------------------------------------------------------------- item 6 (Serenity's change to R55): memberships
# that all fail are read once per decision, not once per path

NOWHERE = ["collection:andy/nowhere"]


def _counted_membership_counts(monkeypatch):
    import permissions
    calls, real = [0], permissions._membership_counts

    def counted(*a, **k):
        calls[0] += 1
        return real(*a, **k)
    monkeypatch.setattr(permissions, "_membership_counts", counted)
    return calls


@pytest.mark.parametrize("levels,width", [(5, 4), (5, 6)])
def test_item6_nested_memberships_that_all_fail_are_refused_in_about_a_millisecond(monkeypatch, levels, width):
    """Every level's memberships are backed by grants whose envelopes name the next level, and the last level's name
    a collection m1 is not in, so no membership counts. The `any` over them read every path, width^levels of them
    (5 levels of 6: 18,660 calls and 0.18 s on the Pi)."""
    import time
    from permissions import Refusal
    from tests.permissions_support import HOME, home_use
    from tests.test_permissions_serenity_fixes import _nested_levels
    state, use = _nested_levels(levels, width, bottom=NOWHERE), home_use(M1, T("2026-11-02"))
    calls = _counted_membership_counts(monkeypatch)
    start = time.perf_counter()
    d = decide(state, use)
    took = time.perf_counter() - start
    assert d.refusal == Refusal("NO_ALLOW", HOME, "recall")
    # the allow is read twice, matched and as a candidate (PF23); each read reads a row once a route to its level
    assert calls[0] <= 2 * levels * width * (width + 1), calls[0]
    assert took < 0.05, f"decide took {took:.4f} s"


def test_item6_past_the_step_budget_the_use_is_refused_never_decided_on_a_part(monkeypatch):
    import permissions
    from permissions import RuleError
    from tests.permissions_support import home_use
    from tests.test_permissions_serenity_fixes import _nested_levels
    state, use = _nested_levels(3, 2, bottom=NOWHERE), home_use(M1, T("2026-11-02"))
    assert decide(state, use).refusal.code == "NO_ALLOW"
    monkeypatch.setattr(permissions, "MEMBERSHIP_STEPS", 2)
    with pytest.raises(RuleError, match="memberships to read"):
        decide(state, use)


def _decisions(state, uses):
    return [decide(state, u).to_json() for u in uses]


def test_item6_the_memo_changes_no_decision(monkeypatch):
    """Random nested worlds, and nests that fail, succeed, or cycle back to their first level: every decision is
    the same with the memo as with every lookup missing."""
    import random
    import permissions
    from tests.permissions_support import Bulk, home_use, random_world, sample_uses
    from tests.test_permissions_serenity_fixes import _nested_levels
    cases = []
    for seed in range(12):
        rng = random.Random(f"item6-{seed}")
        w = random_world(rng)
        uses = [x for u in sample_uses(rng, w, 20) for x in (u.uses if isinstance(u, Bulk) else (u,))]
        cases.append((w.state(), uses))
    at = [T("2026-11-02"), T("2026-11-30") - 3 * 3600, T("2026-12-01")]
    for bottom in (NOWHERE, "*", [f"collection:andy/c0-{j}" for j in range(3)]):
        cases.append((_nested_levels(3, 3, bottom=bottom), [home_use(M1, t) for t in at]))
    with_memo = [_decisions(s, uses) for s, uses in cases]
    monkeypatch.setattr(permissions._MembershipMemo, "get", lambda self, key: None)
    assert [_decisions(s, uses) for s, uses in cases] == with_memo
    assert sum(len(d) for d in with_memo) > 200
