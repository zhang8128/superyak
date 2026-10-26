"""Task 13: the gate, the houses and PlaceRules (P 9.4, 12.3; U8, U16, R17, R26, R27, R32, RS2)."""
import json
import sqlite3
import time

import pytest

from lighthouse_protocol import verify_artifact_digest
from permission_ledger import (Gate, Ledger, LedgerUnreadable, effective_gate, house_mark, houses,
                               ledger_for_house, ledger_path)
from permissions import Act, RuleError
from tests.permissions_support import (
    ANDY, T, delete_gate_key, delete_ledger, do, e1_county_ledger, fresh_raised, house_meta, make_house,
    make_house_with_029, make_ledger_unreadable, proposal_act, raise_gate, raised_ledger,
    register_default_agent_at_home, set_unknown_gate_value, swap_in_another_ledger)


def test_u16_off_with_no_ledger_and_no_marked_house(tmp_path):
    make_house(tmp_path, "lighthouse")
    assert effective_gate(tmp_path, houses(tmp_path)) == Gate("off", None)


def test_u16_a_raise_with_no_published_house_is_refused(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    with pytest.raises(RuleError, match="published house"):
        raise_gate(led, "shadow")


def test_u16_the_raise_marks_every_house(tmp_path):
    led = raised_ledger(tmp_path, houses=("lighthouse", "why"))
    for house in houses(tmp_path):
        assert house_meta(house)["permissions_ledger_id"] == led.meta()["ledger_id"]
    assert effective_gate(tmp_path, houses(tmp_path)).mode == "shadow"
    absent = tmp_path / ".engram" / "instances" / "pending" / "graph.db"        # configured, not yet made (R32)
    assert effective_gate(tmp_path, houses(tmp_path) + [absent]).mode == "shadow"


def test_rs2_a_gate_proposal_holds_only_its_mode_and_sign_marks_the_houses_on_disk_at_the_yes(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    make_house(tmp_path, "lighthouse"); register_default_agent_at_home(led)    # agent:default acts for Andy
    with pytest.raises(RuleError, match="only mode"):
        led.perform(Act("gate", {"mode": "shadow", "houses": []}), actor="agent:default", channel="tool",
                    now=T("2026-11-02"))
    out = led.perform(Act("gate", {"mode": "shadow"}), actor="agent:default", channel="tool", now=T("2026-11-02"))
    assert out.status == "proposal" and proposal_act(led, out.ref) == Act("gate", {"mode": "shadow"})
    make_house(tmp_path, "late")                       # made after the agent asked; no raised ledger yet, so no mark
    assert led.gate_plan()["houses"] == houses(tmp_path)
    led.perform(Act("sign", {"proposal": out.ref}), actor="person:andy", channel="terminal", now=T("2026-11-02"))
    late = tmp_path / ".engram" / "instances" / "late" / "graph.db"
    assert house_meta(late)["permissions_ledger_id"] == led.meta()["ledger_id"]
    assert effective_gate(tmp_path, houses(tmp_path)).mode == "shadow"


def test_u16_after_the_raise_each_of_these_fails_closed(tmp_path):
    for damage in (delete_ledger, make_ledger_unreadable, swap_in_another_ledger, set_unknown_gate_value,
                   delete_gate_key):
        root = fresh_raised(tmp_path / damage.__name__)
        damage(root)
        assert effective_gate(root, houses(root)).mode == "closed", damage.__name__


def test_u16_a_deleted_ledger_reads_closed_for_every_reader(tmp_path):
    root = fresh_raised(tmp_path); delete_ledger(root); make_house(root, "late")   # made after the deletion
    assert effective_gate(root, [root / ".engram/instances/late/graph.db"]).mode == "closed"


def test_u16_with_no_ledger_and_more_than_64_houses_a_reader_reads_closed(tmp_path):
    for i in range(65):
        make_house(tmp_path, f"h{i}")
    assert effective_gate(tmp_path, houses(tmp_path)[:1]).mode == "closed"


def test_u8_home_rules_are_not_exported(tmp_path):
    led = e1_county_ledger(tmp_path)
    with pytest.raises(RuleError, match="9.4"):
        led.place_rules("place:home/andy", now=T("2026-11-02"))
    art = led.place_rules("place:la-county/public-health", now=T("2026-11-02"))
    assert art["kind"] == "PlaceRules" and verify_artifact_digest(art) and art["payload"]["ledgerSeq"] == led.seq()


# ---------------------------------------------------------------- beyond the brief's eight

def test_every_cause_is_a_short_sentence_and_a_good_gate_has_none(tmp_path):
    root = fresh_raised(tmp_path / "good")
    assert effective_gate(root, houses(root)) == Gate("shadow", None)
    delete_ledger(root)
    gate = effective_gate(root, houses(root))
    assert gate.mode == "closed" and "ledger missing" in gate.cause and "carries its id" in gate.cause


def test_houses_are_the_default_store_and_every_instance_that_exists_sorted(tmp_path):
    assert houses(tmp_path) == []
    make_house(tmp_path, "why"); make_house(tmp_path, "lighthouse"); make_house(tmp_path, None)
    (tmp_path / ".engram" / "instances" / "empty").mkdir()           # a directory with no graph.db is no house
    base = tmp_path / ".engram"
    assert houses(tmp_path) == sorted([base / "graph.db", base / "instances" / "lighthouse" / "graph.db",
                                       base / "instances" / "why" / "graph.db"])


def test_a_house_made_again_after_the_raise_with_no_id_reads_closed_and_running_the_gate_again_marks_it(tmp_path):
    led = raised_ledger(tmp_path, houses=("lighthouse",))
    late = make_house(tmp_path, "late")
    gate = effective_gate(tmp_path, houses(tmp_path))
    assert gate.mode == "closed" and "late" in gate.cause
    out = raise_gate(led, "shadow", now="2026-11-03")
    assert house_meta(late)["permissions_ledger_id"] == led.meta()["ledger_id"]
    assert effective_gate(tmp_path, houses(tmp_path)).mode == "shadow"
    body = json.loads(led.conn.execute("SELECT body FROM ledger_log WHERE seq=?", (out.seq,)).fetchone()[0])
    assert body["houses"] == [".engram/instances/late/graph.db"]      # only the house this run marked


def test_a_house_carrying_another_ledgers_id_or_unreadable_reads_closed(tmp_path):
    raised_ledger(tmp_path, houses=("lighthouse", "why"))
    why = tmp_path / ".engram" / "instances" / "why" / "graph.db"
    for value in ("some-other-ledger", "unreadable"):
        con = sqlite3.connect(why)
        con.execute("UPDATE meta SET value=? WHERE key='permissions_ledger_id'", (value,)); con.commit(); con.close()
        gate = effective_gate(tmp_path, houses(tmp_path))
        assert gate.mode == "closed" and "why" in gate.cause, value


def test_the_log_body_of_the_first_raise_records_the_mode_and_the_houses_it_marked(tmp_path):
    led = raised_ledger(tmp_path, houses=("lighthouse", "why"))
    body = json.loads(led.conn.execute("SELECT body FROM ledger_log WHERE kind='gate'").fetchone()[0])
    assert body["meta"] == {"gate": "shadow", "gate_raised": "1"}
    assert body["houses"] == [".engram/instances/lighthouse/graph.db", ".engram/instances/why/graph.db"]
    assert led.meta()["gate"] == "shadow" and led.meta()["gate_raised"] == "1"
    assert led.verify() is None


def test_off_before_any_raise_marks_nothing_and_needs_no_house(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    make_house(tmp_path, "why")
    raise_gate(led, "off")
    assert "gate_raised" not in led.meta() and "permissions_ledger_id" not in house_meta(houses(tmp_path)[0])
    assert effective_gate(tmp_path, houses(tmp_path)) == Gate("off", None)


def test_lowering_the_gate_after_a_raise_works_without_the_published_house(tmp_path):
    led = raised_ledger(tmp_path, houses=("lighthouse",))
    (tmp_path / ".engram" / "instances" / "lighthouse" / "graph.db").unlink()
    raise_gate(led, "off", now="2026-11-03")
    assert effective_gate(tmp_path, []).mode == "off"


@pytest.mark.parametrize("args", [{}, {"mode": "loud"}, {"mode": "shadow", "houses": []}, {"mode": 1}])
def test_the_gate_act_takes_a_known_mode_and_nothing_else(tmp_path, args):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01")); make_house(tmp_path, "lighthouse")
    with pytest.raises(RuleError):
        led.perform(Act("gate", args), actor=ANDY, channel="terminal", now=T("2026-11-02"))
    assert led.seq() == 1


def test_only_the_owner_makes_the_gate_act(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01")); make_house(tmp_path, "lighthouse")
    do(led, ANDY, "register-person", person="person:jenn")
    with pytest.raises(RuleError, match="owner"):
        led.perform(Act("gate", {"mode": "shadow"}), actor="person:jenn", channel="terminal", now=T("2026-11-02"))


def test_gate_plan_and_the_outcome_list_the_houses_that_lack_migration_029(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    old = make_house(tmp_path, "lighthouse"); new = make_house_with_029(tmp_path, "why")
    plan = led.gate_plan()
    assert plan["published_house"] == old and plan["houses"] == houses(tmp_path)
    assert plan["lacking_029"] == [old]
    assert raise_gate(led, "shadow").lacking_029 == (old,)


def test_the_gate_plan_names_the_published_house_even_when_it_does_not_exist(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    plan = led.gate_plan()
    assert plan["published_house"] == tmp_path / ".engram" / "instances" / "lighthouse" / "graph.db"
    assert plan["houses"] == [] and plan["lacking_029"] == []


def test_the_effective_gate_opens_the_ledger_with_the_busy_timeout_it_is_given(tmp_path):
    root = fresh_raised(tmp_path)
    blocker = sqlite3.connect(ledger_path(root), isolation_level=None)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        started = time.monotonic()
        gate = effective_gate(root, houses(root), busy_ms=50)
        assert time.monotonic() - started < 2
        assert gate.mode == "closed" and gate.cause
    finally:
        blocker.execute("ROLLBACK"); blocker.close()


def test_a_hot_journal_reads_closed_and_names_the_command_that_clears_it(tmp_path, monkeypatch):
    root = fresh_raised(tmp_path)
    ledger_path(root).with_name("permissions.db-journal").write_bytes(b"x" * 512)

    def refuse(*a, **k):
        raise LedgerUnreadable("attempt to write a readonly database")
    monkeypatch.setattr(Ledger, "open_read_only", staticmethod(refuse))
    gate = effective_gate(root, houses(root))
    assert gate.mode == "closed" and "hot journal" in gate.cause and "engram-permissions sweep" in gate.cause


def test_a_served_path_that_is_not_a_file_is_no_house_even_when_a_directory(tmp_path):
    root = fresh_raised(tmp_path)
    adir = root / ".engram" / "instances" / "dir" / "graph.db"
    adir.mkdir(parents=True)
    assert effective_gate(root, houses(root) + [adir]).mode == "shadow"


def test_house_mark_and_ledger_for_house(tmp_path):
    new_house = tmp_path / ".engram" / "instances" / "fresh" / "graph.db"
    assert ledger_for_house(new_house) is None and house_mark(new_house) is None      # no ledger at all
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    assert ledger_for_house(new_house) == ledger_path(tmp_path)
    assert ledger_for_house(tmp_path / ".engram" / "graph.db") == ledger_path(tmp_path)
    assert ledger_for_house(tmp_path / "elsewhere" / "graph.db") is None
    assert house_mark(new_house) is None                                              # not raised yet
    make_house(tmp_path, "lighthouse"); raise_gate(led, "shadow")
    assert house_mark(new_house) == led.meta()["ledger_id"]
    make_ledger_unreadable(tmp_path)
    assert house_mark(new_house) == "unreadable"


def test_place_rules_carries_the_place_its_parents_stewards_and_every_effective_record(tmp_path):
    led = e1_county_ledger(tmp_path)
    sw = "place:la-county/summer-wellness"
    art = led.place_rules(sw, now=T("2026-11-02"))
    p = art["payload"]
    assert art["protocolVersion"] == "0.1" and art["issuer"] == "urn:engram:" + led.meta()["ledger_id"]
    assert art["payloadMediaType"] == "application/vnd.engram.place-rules+json"
    assert art["issuedAt"] == "2026-11-02T00:00:00Z" and art["id"].startswith("urn:engram:")
    assert p["place"] == sw and p["parents"] == ["place:la-county/parks-and-rec", "place:la-county/public-health"]
    assert p["stewards"] == ["person:sw-steward"] and p["retired"] is False
    assert p["logDigest"] == led.conn.execute("SELECT digest FROM ledger_log ORDER BY seq DESC LIMIT 1").fetchone()[0]
    ids = {r["id"] for r in p["records"]}
    assert ids == {led.ids.W1}              # the records written in this layer; H2 and K2 name it only as audience
    w1 = next(r for r in p["records"] if r["id"] == led.ids.W1)
    assert w1["selector"]["audience"] == [sw] and w1["effect"] == "allow" and w1["set_by"] == "person:sw-steward"
    assert set(w1) >= {"layer", "valid_from", "valid_until", "anchor", "backing", "channel", "reason", "created",
                       "created_seq", "replaces", "under_grant", "proposal_id"}
    assert "revoked_seq" not in w1 or w1["revoked_seq"] is None
    assert art == led.place_rules(sw, now=T("2026-11-02"))              # deterministic


def test_place_rules_leaves_out_revoked_records_and_refuses_unknown_places(tmp_path):
    led = e1_county_ledger(tmp_path)
    do(led, "person:sw-steward", "revoke", record=led.ids.W1, reason="done")
    art = led.place_rules("place:la-county/summer-wellness", now=T("2026-11-02"))
    assert led.ids.W1 not in {r["id"] for r in art["payload"]["records"]}
    with pytest.raises(RuleError):
        led.place_rules("place:la-county/nowhere", now=T("2026-11-02"))
