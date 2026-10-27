"""Task 11: registry acts through Ledger.perform, kept copies and the read accessors (P 4.4, 7.4)."""
import pytest

from permission_ledger import Outcome
from permissions import Act, Refusal, RuleError, agent_place_at, decide
from tests.permissions_support import (
    ANDY, CLINIC_3, COPY_OF_M3, COUNTY, HOME, M1, M2, M3, M4, M5, M6, MEDICAL, PH, PR, SW, T, add_subject,
    copies_ledger, county_ledger, do, e1_county_ledger, e1_ledger_through_andys_side, read_by_ph, read_copy,
    remove_subject, source_with_copy_at_8_subjects)


# ---------------------------------------------------------------- the brief's six tests

def test_u2_a_joint_place_waits_for_every_parents_steward(tmp_path):
    led = county_ledger(tmp_path)             # stewards ph-steward and pr-steward, written through perform
    out = led.perform(Act("register-place", {"place": SW, "parents": [PH, PR], "name": "Summer Wellness"}),
                      actor="person:ph-steward", channel="terminal", now=T("2026-11-01"))
    assert out.status == "proposal" and SW not in led.state().places
    led.perform(Act("sign", {"proposal": out.ref}), actor="person:pr-steward", channel="terminal",
                now=T("2026-11-01"))
    assert SW in led.state().places


def test_u2_one_place_per_agent_and_retiring_a_person(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)   # ph-steward stewards public-health and clinic-3, so it is both
    with pytest.raises(RuleError, match="P31"):  # the target's steward and ph-coordinator's principal
        led.perform(Act("put-agent", {"agent": "agent:ph-coordinator", "place": PH}),
                    actor="person:ph-steward", channel="terminal", now=T("2026-11-01"))
    led.perform(Act("retire-person", {"person": "person:jenn"}), actor="person:andy", channel="terminal",
                now=T("2026-11-01"))
    assert decide(led.state(), read_by_ph(M3, T("2026-11-02"))).refusal.code == "RETIRED"


def test_u20_putting_an_agent_in_a_place_needs_its_principal(tmp_path):
    led = county_ledger(tmp_path)              # agent:parks-intern acts for parks-and-rec and is in no place yet
    out = led.perform(Act("put-agent", {"agent": "agent:parks-intern", "place": PH}),
                      actor="person:ph-steward", channel="terminal", now=T("2026-11-01"))
    assert out.status == "proposal"            # waits for a parks-and-rec steward, the principal
    led.perform(Act("sign", {"proposal": out.ref}), actor="person:pr-steward", channel="terminal",
                now=T("2026-11-01"))
    assert agent_place_at(led.state(), "agent:parks-intern", T("2026-11-02")) == PH


def test_u5_co_subjects(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)   # m3 has Jenn as co-subject; Jenn's home layer is empty
    assert decide(led.state(), read_by_ph(M3, T("2026-11-02"))).refusal == Refusal("NO_ALLOW", "place:home/jenn",
                                                                                      "recall")
    add_subject(led, M5, "person:amy", actor="agent:rio-grande", channel="tool")
    remove_subject(led, M5, "person:amy", actor="person:andy")           # his agent added it: allowed
    add_subject(led, M6, "person:jenn", actor="person:jenn", self_claimed=True)   # an API fixture (P 7.4)
    led.record_copy(COPY_OF_M3, M3, now=T("2026-11-03"))                  # the copy carries Jenn
    for ref in (M6, COPY_OF_M3):
        with pytest.raises(RuleError, match="7.4"):
            remove_subject(led, ref, "person:jenn", actor="person:andy")
    src, copy = source_with_copy_at_8_subjects(led)                        # the copy's union holds 8
    add_subject(led, src, "person:p9", actor="person:andy")                # written: never refused for its copies
    assert decide(led.state(), read_copy(copy)).refusal.code == "BOUND"


def test_pt7_a_copy_chain_deeper_than_4_is_refused_when_made(tmp_path):
    led = copies_ledger(tmp_path, chain=4)
    with pytest.raises(RuleError, match="4 links"):
        led.record_copy("mem:K5/episode/c5", "mem:K4/episode/c4", now=T("2026-11-02"))


def test_u15_the_check_reruns_after_a_registry_change(tmp_path):
    led = e1_county_ledger(tmp_path)
    out = led.perform(Act("add-steward", {"place": "place:la-county/summer-wellness", "person": "person:sw2"}),
                      actor="person:sw-steward", channel="terminal", now=T("2026-11-02"))
    assert "place:la-county/summer-wellness" in {r.place for r in out.reports}


# ---------------------------------------------------------------- what the brief leaves to the builder

def only_proposal_rows_changed(before, after):
    """The log, the head that follows it in `meta`, and the proposals changed; nothing else."""
    def kept(t, rows):
        return [r for r in rows if r.get("key") != "head"] if t == "meta" else rows
    keys = {t for t in after if t not in ("ledger_log", "proposals")}
    return all(kept(t, before[t]) == kept(t, after[t]) for t in keys) and after["proposals"] != before["proposals"]


def test_a_refused_act_writes_nothing(tmp_path):
    led = county_ledger(tmp_path)
    before, seq = led.tables(), led.seq()
    for actor, act in (("person:jenn", Act("register-person", {"person": "person:zed"})),
                       ("person:ph-steward", Act("register-place", {"place": "place:la-county/x",
                                                                    "stewards": ["person:jenn"]})),
                       ("person:andy", Act("register-person", {"person": "person:amy"})),
                       ("person:andy", Act("allow", {"layer": HOME}))):
        with pytest.raises(RuleError):
            led.perform(act, actor=actor, channel="terminal", now=T("2026-11-02"))
    assert led.seq() == seq and led.tables() == before and led.verify() is None


def test_an_act_kind_this_task_does_not_know_is_refused_by_name(tmp_path):
    led = county_ledger(tmp_path)
    with pytest.raises(RuleError, match="unknown act kind 'frobnicate'"):
        led.perform(Act("frobnicate", {}), actor=ANDY, channel="terminal", now=T("2026-11-02"))


def test_registering_a_person_makes_a_home_with_an_empty_layer(tmp_path):
    led = county_ledger(tmp_path)
    s = led.state()
    home = "place:home/amy"
    assert s.persons["person:amy"].home == home and s.persons["person:amy"].is_admin == 0
    assert s.places[home].is_root == 1 and len(s.places[home].pseudonym_salt) == 16
    assert [r.person for r in s.place_stewards[home]] == ["person:amy"]
    assert not [r for r in s.records.values() if r.layer == home]
    with pytest.raises(RuleError, match="already"):
        do(led, ANDY, "register-person", person="person:amy")


def test_a_place_gets_its_name_parents_stewards_and_a_16_byte_salt(tmp_path):
    led = county_ledger(tmp_path)
    s = led.state()
    assert s.names[PH] == "Public Health" and s.names[CLINIC_3] == "clinic-3"
    assert [r.parent for r in s.place_parents[PH]] == [COUNTY] and s.places[COUNTY].is_root == 1
    assert s.places[PH].is_root == 0 and len(s.places[PH].pseudonym_salt) == 16
    assert s.places[PH].pseudonym_salt != s.places[PR].pseudonym_salt
    assert {r.person for r in s.place_stewards[CLINIC_3]} == {"person:ph-steward"}   # the filer, by default


def test_a_place_needs_a_registered_steward_and_a_steward_of_its_parent(tmp_path):
    led = county_ledger(tmp_path)
    place = "place:la-county/public-health/clinic-9"
    with pytest.raises(RuleError, match="steward"):                     # parks' steward has no say in public health
        do(led, "person:pr-steward", "register-place", place=place, stewards=["person:pr-steward"])
    with pytest.raises(RuleError, match="registered"):
        do(led, "person:ph-steward", "register-place", place=place, stewards=["person:nobody"])
    with pytest.raises(RuleError):
        do(led, "person:ph-steward", "register-place", place=place, stewards=[])
    with pytest.raises(RuleError, match="admin"):                       # a root place is an admin's
        do(led, "person:ph-steward", "register-place", place="place:state", stewards=["person:ph-steward"])


def test_add_and_remove_steward_keep_at_least_one(tmp_path):
    led = county_ledger(tmp_path)
    do(led, "person:ph-steward", "add-steward", place=PH, person="person:sw2")
    do(led, "person:county-steward", "remove-steward", place=PH, person="person:ph-steward")  # a dominator may
    assert {r.person for r in led.state().place_stewards[PH] if r.removed_seq is None} == {"person:sw2"}
    with pytest.raises(RuleError, match="at least one steward"):
        do(led, "person:sw2", "remove-steward", place=PH, person="person:sw2")
    with pytest.raises(RuleError, match="never changed"):
        do(led, ANDY, "add-steward", place=HOME, person="person:jenn")
    with pytest.raises(RuleError, match="not a steward"):
        do(led, "person:county-steward", "remove-steward", place=PH, person="person:jenn")


def test_add_parent_wants_both_stewards_and_retire_place_ends_a_place(tmp_path):
    led = county_ledger(tmp_path)
    do(led, "person:ph-steward", "register-place", place="place:la-county/public-health/lab",
       stewards=["person:ph-steward"])
    out = do(led, "person:ph-steward", "add-parent", place="place:la-county/public-health/lab", parent=PR)
    assert out.status == "proposal"                                      # waits for a parks-and-rec steward
    done = do(led, "person:pr-steward", "sign", proposal=out.ref)
    assert done.status == "done"
    assert {r.parent for r in led.state().place_parents["place:la-county/public-health/lab"]} == {PH, PR}
    with pytest.raises(RuleError):
        do(led, "person:pr-steward", "retire-place", place=CLINIC_3)     # not its steward
    do(led, "person:ph-steward", "retire-place", place=CLINIC_3)
    assert led.state().places[CLINIC_3].retired_seq is not None
    with pytest.raises(RuleError, match="retired"):
        do(led, "person:ph-steward", "retire-place", place=CLINIC_3)


def test_agents_are_registered_for_a_place_and_put_in_one_at_a_time(tmp_path):
    led = county_ledger(tmp_path)
    with pytest.raises(RuleError, match="already"):
        do(led, ANDY, "register-agent", agent="agent:rio-grande", acts_for=HOME)
    with pytest.raises(RuleError):                                       # Andy is not parks-and-rec's steward
        do(led, ANDY, "register-agent", agent="agent:spy", acts_for=PR)
    do(led, "person:pr-steward", "remove-agent", agent="agent:parks-planner", place=PR)
    assert agent_place_at(led.state(), "agent:parks-planner", T("2026-11-02")) is None
    with pytest.raises(RuleError, match="not in"):
        do(led, "person:pr-steward", "remove-agent", agent="agent:parks-planner", place=PR)
    done = do(led, "person:pr-steward", "put-agent", agent="agent:parks-planner", place=PR)
    assert done.status == "done"


def test_stores_are_registered_by_their_owner_and_read_back(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    row = led.store_row("S")
    assert row["owner"] == ANDY and row["place"] == HOME and row["imprint_of"] is None and row["name"] == "engram"
    assert led.store_row("nope") is None
    with pytest.raises(RuleError, match="already"):
        do(led, ANDY, "register-store", instance_id="S", name="x", owner=ANDY, place=HOME)
    with pytest.raises(RuleError):                                       # Jenn is neither owner nor steward
        do(led, "person:jenn", "register-store", instance_id="J", name="x", owner=ANDY, place=HOME)
    do(led, ANDY, "register-store", instance_id="IMP", name="imprint", owner=ANDY, place=HOME, imprint_of="S")
    assert led.store_row("IMP")["imprint_of"] == "S"


def test_groups_collections_and_lane_notes(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    s = led.state()
    members = {r.object for r in s.collection_members[MEDICAL] if r.removed_seq is None}
    assert members == {M1, M2, M3} and all(r.backing == "person" for r in s.collection_members[MEDICAL])
    assert [(n.lane, n.at) for n in s.lane_notes[M1]] == [("personal", T("2026-10-01"))]
    do(led, ANDY, "collect", collection=MEDICAL, refs=[M1, M4, M5],                  # M1 has a note, M5 no lane
       lanes={M1: {"lane": "work", "created_at": T("2026-10-02")}, M4: {"lane": "work", "created_at": 5}, M5: None})
    s = led.state()
    assert [n.lane for n in s.lane_notes[M1]] == ["personal"] and [(n.lane, n.at) for n in s.lane_notes[M4]] == [
        ("work", 5)]
    assert M5 not in s.lane_notes
    do(led, ANDY, "uncollect", collection=MEDICAL, refs=[M4])
    assert M4 not in {r.object for r in led.state().collection_members[MEDICAL] if r.removed_seq is None}
    with pytest.raises(RuleError, match="not in"):
        do(led, ANDY, "uncollect", collection=MEDICAL, refs=[M4])
    with pytest.raises(RuleError):                                       # Jenn does not own Andy's collection
        do(led, "person:jenn", "collect", collection=MEDICAL, refs=[M4], lanes={})
    do(led, ANDY, "group", group="group:care", members=["agent:rio-grande", "agent:ph-coordinator"])
    do(led, ANDY, "group", group="group:care", members=["agent:rio-grande"])
    s = led.state()
    assert s.groups["group:care"].owner == ANDY
    assert [r.agent for r in s.group_members["group:care"] if r.removed_seq is None] == ["agent:rio-grande"]
    with pytest.raises(RuleError):
        do(led, "person:jenn", "group", group="group:care", members=[])


def test_an_agents_widening_registry_act_is_filed_with_its_full_change(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    before = led.tables()
    out = led.perform(Act("register-agent", {"agent": "agent:new", "acts_for": HOME}), actor="agent:rio-grande",
                      channel="tool", now=T("2026-11-03"))
    assert out.status == "proposal" and out.reports == () and out.seq == led.seq()
    assert only_proposal_rows_changed(before, led.tables())
    [row] = [r for r in led.tables()["proposals"] if r["id"] == out.ref]
    assert (row["by_agent"], row["for_person"], row["kind"], row["status"]) == (
        "agent:rio-grande", ANDY, "register-agent", "pending")
    assert row["expires"] == T("2026-11-03") + 7 * 86400 and "agent:new" in row["body"]
    assert "agent:new" not in led.state().agents


def test_signing_a_joint_place_takes_a_steward_who_covers_a_parent_and_declining_ends_it(tmp_path):
    led = county_ledger(tmp_path)
    out = do(led, "person:ph-steward", "register-place", place=SW, parents=[PH, PR], stewards=["person:sw-steward"])
    for who in ("person:jenn", "person:ph-steward"):       # not a steward of parks; the filer already covers public health
        with pytest.raises(RuleError):
            do(led, who, "sign", proposal=out.ref)
    with pytest.raises(RuleError):
        do(led, "agent:rio-grande", "sign", proposal=out.ref)
    with pytest.raises(RuleError, match="terminal"):
        do(led, "person:pr-steward", "sign", channel="tool", proposal=out.ref)
    before = led.tables()
    declined = do(led, "person:pr-steward", "decline", proposal=out.ref)
    assert declined.status == "done" and SW not in led.state().places
    assert only_proposal_rows_changed(before, led.tables())
    with pytest.raises(RuleError, match="pending"):
        do(led, "person:pr-steward", "sign", proposal=out.ref)


def test_a_joint_place_signed_by_both_parents_keeps_its_name_and_steward(tmp_path):
    led = e1_county_ledger(tmp_path)
    s = led.state()
    assert s.names[SW] == "Summer Wellness" and {r.parent for r in s.place_parents[SW]} == {PH, PR}
    assert {r.person for r in s.place_stewards[SW]} == {"person:sw-steward"}
    assert [p.status for p in s.proposals.values()] == ["signed"]
    assert led.verify() is None


def test_perform_returns_an_outcome_with_the_row_it_wrote(tmp_path):
    led = county_ledger(tmp_path)
    out = do(led, ANDY, "register-person", person="person:zed")
    assert out == Outcome("done", "person:zed", led.seq(), out.reports, ())
    assert led.tables()["ledger_log"][-1]["kind"] == "register-person" and out.status == "done"


def test_record_copy_carries_subjects_and_refuses_past_8(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    led.record_copy(COPY_OF_M3, M3, now=T("2026-11-03"))
    s = led.state()
    assert s.copies[COPY_OF_M3] == M3
    assert led.cosubjects(COPY_OF_M3) == frozenset({"person:jenn"}) and led.cosubjects(M3) == frozenset({"person:jenn"})
    [row] = [r for r in s.subjects[COPY_OF_M3]]
    assert row.added_by == f"copy:{M3}" and not row.self_claimed
    with pytest.raises(RuleError, match="already"):
        led.record_copy(COPY_OF_M3, M3, now=T("2026-11-03"))
    for i in range(1, 8):                                  # m7 gets Andy and 7 co-subjects, 8 in all
        add_subject(led, "mem:S/episode/m7", f"person:p{i}", actor=ANDY)
    do(led, "person:sw2", "register-store", instance_id="K9", name="k", owner="person:sw2", place="place:home/sw2")
    before = led.tables()
    with pytest.raises(RuleError, match="8 subjects"):     # sw2 and the source's 8 make 9
        led.record_copy("mem:K9/episode/c7", "mem:S/episode/m7", now=T("2026-11-03"))
    assert led.tables()["copies"] == before["copies"]


def test_cosubjects_are_the_effective_ones_only(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    assert led.cosubjects(M5) == frozenset()
    add_subject(led, M5, "person:amy", actor=ANDY)
    assert led.cosubjects(M5) == frozenset({"person:amy"})
    remove_subject(led, M5, "person:amy", actor=ANDY)
    assert led.cosubjects(M5) == frozenset()
