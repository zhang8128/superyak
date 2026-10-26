"""Task 25: the `remember` guard and kept copies (P 7.4, 10; U17, R10, R11, P25)."""
import json
import logging

import pytest

import federation
import server
from permission_ledger import Ledger, ledger_path
from permission_uses import Uses
from permissions import GUARD_RECEIPTS, GUARD_SECONDS, Act, Refusal, decide, subjects_of
from tests.permissions_support import (
    ANDY, KEEP_LATER, KEEP_NOW, KEPT_USE, M1, M1_TEXT, T, deliver_item_with_content, deliver_m1_through,
    deliver_other_items, fails_the_test, genome_world, keep_world, keep_world_with_imprint_allowed,  # noqa: F401
    make_uses_file_unreadable, raise_gate, receipt_rows, write_delivery_receipt)
from tests.test_recall_margins import engram_server_env  # noqa: F401

REFUSED = {"error": "keeping this content is not allowed", "layer": "rejected"}


def now() -> int:
    return KEEP_NOW


def ledger_state():
    led = Ledger.open_read_only(server.ENGRAM_HOME)
    try:
        return led.state()
    finally:
        led.close()


def add_subject(ref, subject):
    led = Ledger.open(server.ENGRAM_HOME)
    try:
        led.perform(Act("add-subject", {"object": ref, "subject": subject}), actor=ANDY, channel="terminal",
                    now=KEEP_LATER)
    finally:
        led.close()


def set_gate(world, mode):
    led = Ledger.open(world.root)
    try:
        led.perform(Act("gate", {"mode": mode}), actor=ANDY, channel="terminal", now=T("2026-11-02"))
    finally:
        led.close()


@pytest.mark.parametrize("path", ["neighbors", "context_runtime"])
def test_u17_verbatim_delivered_content_is_refused_unless_imprint_is_allowed(keep_world, path):
    deliver_m1_through(keep_world, "neighbors")
    out = server.remember(content=M1_TEXT)
    assert out == REFUSED


def test_u17_a_refused_keep_writes_one_imprint_receipt_and_no_episode(keep_world):
    deliver_m1_through(keep_world, "neighbors")
    before = server._storage.conn.execute("SELECT count(*) FROM episodes").fetchone()[0]
    assert server.remember(content=M1_TEXT) == REFUSED
    [row] = receipt_rows(keep_world.root, "imprint")
    assert row["allowed"] == 0 and row["object"] == M1 and row["agent"] == "agent:ph-coordinator"
    assert server._storage.conn.execute("SELECT count(*) FROM episodes").fetchone()[0] == before


def test_u17_when_allowed_the_kept_memory_carries_its_source_subjects(keep_world_with_imprint_allowed):
    deliver_m1_through(keep_world_with_imprint_allowed, "neighbors")
    out = server.remember(content=M1_TEXT)
    kept = f"mem:{keep_world_with_imprint_allowed.ids.PHC_STORE}/episode/{out['episode_id']}"
    assert "would_refuse" not in out
    assert ledger_state().copies[kept] == M1 and "person:andy" in subjects_of(ledger_state(), kept, now())
    [row] = receipt_rows(keep_world_with_imprint_allowed.root, "imprint")
    assert row["allowed"] == 1


def test_u17_a_co_subject_added_to_the_source_afterwards_refuses_the_kept_copys_next_use(
        keep_world_with_imprint_allowed):
    deliver_m1_through(keep_world_with_imprint_allowed, "neighbors")
    out = server.remember(content=M1_TEXT)
    kept = f"mem:{keep_world_with_imprint_allowed.ids.PHC_STORE}/episode/{out['episode_id']}"
    use = KEPT_USE(kept, at=now())
    assert decide(ledger_state(), use).allowed
    add_subject(M1, "person:amy")
    assert "person:amy" in subjects_of(ledger_state(), kept, now())
    assert decide(ledger_state(), use).refusal == Refusal("NO_ALLOW", "place:home/amy", "recall")


def test_u17_an_amy_co_subject_names_no_code_layer_or_action_to_the_agent(keep_world):
    deliver_m1_through(keep_world, "neighbors")
    add_subject(M1, "person:amy")
    out = server.remember(content=M1_TEXT)
    assert "amy" not in json.dumps(out) and set(out) == {"error", "layer"}
    view = Uses.open(server.ENGRAM_HOME).agent_view("agent:ph-coordinator")
    assert all(set(r) <= {"object", "at", "outcome", "count", "sha256", "permission"} for r in view)
    assert "amy" not in json.dumps(view)


def test_an_agent_acting_for_the_owner_is_told_the_refusals_code_layer_and_action(keep_world, monkeypatch):
    monkeypatch.setattr(server, "_agent_ref", lambda: "agent:rio-grande")
    write_delivery_receipt(keep_world.root, content=M1_TEXT, agent="agent:rio-grande")
    out = server.remember(content=M1_TEXT)
    assert out["error"] == REFUSED["error"] and out["layer"] == "rejected"
    assert set(out["refusal"]) == {"code", "layer", "action"} and out["refusal"]["action"] in ("imprint", "recall",
                                                                                               "read")


def test_the_guard_reads_only_the_last_24_hours_and_200_receipts(keep_world):
    t0 = deliver_m1_through(keep_world, "neighbors")
    agent = "agent:ph-coordinator"
    assert server._keep_check(M1_TEXT, agent=agent, now=t0 + GUARD_SECONDS - 1) is not None
    assert server._keep_check(M1_TEXT, agent=agent, now=t0 + GUARD_SECONDS) is None
    deliver_other_items(keep_world, GUARD_RECEIPTS, at=t0 + 1)
    assert len(Uses.open(server.ENGRAM_HOME).deliveries(agent, now=t0 + 60)) == GUARD_RECEIPTS
    assert server._keep_check(M1_TEXT, agent=agent, now=t0 + 60) is None


def test_the_guard_catches_a_verbatim_copy_with_surrounding_whitespace(keep_world):
    deliver_item_with_content(keep_world, "  " + M1_TEXT + "\n")
    out = server.remember(content="  " + M1_TEXT + "\n")
    assert out == REFUSED


def test_the_guard_catches_content_delivered_stripped_and_kept_with_whitespace(keep_world):
    deliver_m1_through(keep_world, "neighbors")
    assert server.remember(content="  " + M1_TEXT + "\n") == REFUSED


def test_content_that_was_never_delivered_is_kept(keep_world):
    deliver_m1_through(keep_world, "neighbors")
    out = server.remember(content="a note that was never delivered")
    assert out.get("episode_id") and "would_refuse" not in out
    assert ledger_state().copies == {}


def test_shadow_keeps_a_refused_verbatim_copy_and_says_it_would_have_refused(keep_world):
    deliver_m1_through(keep_world, "neighbors")
    set_gate(keep_world, "shadow")
    out = server.remember(content=M1_TEXT)
    assert out.get("episode_id") and out["would_refuse"] is True
    [row] = receipt_rows(keep_world.root, "imprint")
    assert row["shadow"] == 1 and row["allowed"] == 0


def test_closed_refuses_a_delivered_content_and_keeps_anything_else(keep_world):
    from tests.permissions_support import make_ledger_unreadable
    deliver_m1_through(keep_world, "neighbors")
    make_ledger_unreadable(keep_world.root)
    assert server.remember(content=M1_TEXT) == REFUSED
    assert server.remember(content="a note that was never delivered").get("episode_id")


def test_genome_sync_records_kept_copy_subjects_under_shadow(tmp_path, monkeypatch):
    led, genome_path, instance, ids = genome_world(tmp_path, mode="shadow")
    monkeypatch.setattr(federation, "time", type("Clock", (), {"time": staticmethod(lambda: T("2026-11-01"))}))
    assert federation.sync_genome(str(genome_path), instance, ledger=led) == 1
    [local] = [r["id"] for r in instance.conn.execute("SELECT id FROM episodes WHERE episode_type = 'genome_sync'")]
    copy, source = f"mem:{ids.I}/episode/{local}", f"mem:{ids.G}/episode/{ids.g1}"
    s = led.state()
    assert s.copies[copy] == source
    assert subjects_of(s, copy, T("2026-11-02")) == ("person:andy", "person:jenn")
    assert {(r["subject"], r["added_by"]) for r in led.tables()["subjects"] if r["object"] == copy} == {
        ("person:jenn", f"copy:{source}")}
    assert federation.sync_genome(str(genome_path), instance, ledger=led) == 0 and led.state().copies == s.copies
    plain = genome_world(tmp_path / "no-ledger", mode=None)
    assert federation.sync_genome(str(plain[1]), plain[2]) == 1 and not ledger_path(tmp_path / "no-ledger").exists()


def test_r11_an_unreadable_receipts_file_refuses_every_remember_under_enforce(keep_world, caplog):
    make_uses_file_unreadable(keep_world.root)
    with caplog.at_level(logging.WARNING):
        out = server.remember(content="a note that was never delivered")
    assert out == REFUSED
    assert "permission-uses.db" in caplog.text


def test_r11_an_unreadable_receipts_file_lets_shadow_go_on_with_would_refuse(keep_world, caplog):
    set_gate(keep_world, "shadow")
    make_uses_file_unreadable(keep_world.root)
    with caplog.at_level(logging.WARNING):
        out = server.remember(content="a note that was never delivered")
    assert out.get("episode_id") and out["would_refuse"] is True
    assert "permission-uses.db" in caplog.text


def test_off_has_no_guard(engram_server_env, tmp_path, monkeypatch):
    server._init()
    write_delivery_receipt(tmp_path, content=M1_TEXT, agent="agent:default")
    monkeypatch.setattr(Uses, "open_read_only", fails_the_test)
    out = server.remember(content=M1_TEXT)
    assert out.get("episode_id") and "would_refuse" not in out and not ledger_path(tmp_path).exists()
