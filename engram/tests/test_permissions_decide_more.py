"""Task 5, beyond the eight named tests: need, subjects, the layer order, E1's uses and the decision's shape."""
import json

import pytest

from permissions import (ACTIONS, MAX_COPY_CHAIN, Cited, Layer, LegacyLayer, Need, Refusal, RuleError, decide, layer_verdict,
                         needs, required_layers, subjects_of)
from tests.permissions_support import (
    CLINIC_3, HOME, M1, M2, M3, M4, T, andy_world, e1_after_use_9, e1_use_1, e1_world, home_use, use)

ROAD, TRAIL = "road:S/r1", "trail:S/t1"


def test_need_closure_per_action_in_need_order():
    table = {"recall": ("recall",), "read": ("recall", "read"), "inject_context": ("recall", "read", "inject_context"),
             "route": ("route",), "imprint": ("recall", "read", "imprint")}
    for action, expected in table.items():
        assert needs(home_use(M1, 0, action=action)) == (Need(M1, expected),)
        assert tuple(a for a in ACTIONS if a in expected) == expected


def test_need_on_a_road_names_each_memory_in_ref_order_and_shows_read_and_inject_only_for_shown_ones():
    u = home_use(ROAD, 0, action="route", names=[M3, M1, M3], shows=[M3])
    assert needs(u) == (Need(ROAD, ("route",)), Need(M1, ("recall",)), Need(M3, ("recall", "read", "inject_context")))
    u = home_use(TRAIL, 0, action="imprint", names=[M2])
    assert needs(u) == (Need(TRAIL, ("recall", "read", "imprint")), Need(M2, ("recall",)))
    assert needs(home_use(M1, 0, action="read", names=[M2])) == (Need(M1, ("recall", "read")),)   # a memory names none


def test_a_shown_memory_that_is_not_named_is_still_needed():
    assert needs(home_use(ROAD, 0, action="read", names=[M1], shows=[M2]))[1:] == (
        Need(M1, ("recall",)), Need(M2, ("recall", "read", "inject_context")))


def test_subjects_are_the_owner_and_the_co_subjects_in_force_sorted():
    w = andy_world()
    w.now = T("2026-11-05")
    w.subject(M1, "person:jenn")
    w.now = T("2026-11-09")
    w.subject(M1, "place:la-county")
    s = w.state()
    assert subjects_of(s, M1, T("2026-11-02")) == ("person:andy",)
    assert subjects_of(s, M1, T("2026-11-06")) == ("person:andy", "person:jenn")
    assert subjects_of(s, M1, T("2026-11-10")) == ("person:andy", "person:jenn", "place:la-county")
    assert subjects_of(s, "mem:Z/episode/m5", T("2026-11-10")) == ()
    assert subjects_of(s, "mem:/episode/m5", T("2026-11-10")) == ()


def test_a_removed_co_subject_is_out_from_its_removal():
    w = andy_world()
    w.subject(M1, "person:jenn")
    w.now = T("2026-11-05")
    w._find("subjects", object=M1, subject="person:jenn")["removed_seq"] = w._bump()
    s = w.state()
    assert subjects_of(s, M1, T("2026-11-04")) == ("person:andy", "person:jenn")
    assert subjects_of(s, M1, T("2026-11-06")) == ("person:andy",)


def test_a_kept_copy_carries_its_sources_subjects_through_up_to_four_links():
    w = andy_world()
    for name in "TUVWX":
        w.person(name.lower())
        w.store(name, owner=f"person:{name.lower()}", place=f"place:home/{name.lower()}")
    chain = [M1] + [f"mem:{n}/episode/m1" for n in "TUVWX"]
    for copy, source in zip(chain[1:], chain):
        w.copy(copy, source)
    w.subject(M1, "person:jenn")                       # recorded on the source after the copies
    s = w.state()
    assert subjects_of(s, chain[1], T("2026-11-02")) == ("person:andy", "person:jenn", "person:t")
    four = subjects_of(s, chain[MAX_COPY_CHAIN], T("2026-11-02"))
    assert four == ("person:andy", "person:jenn", "person:t", "person:u", "person:v", "person:w")
    # a fifth link is not followed: x's chain stops at t, so Andy's and Jenn's rows on the source do not reach it
    assert subjects_of(s, chain[5], T("2026-11-02")) == ("person:t", "person:u", "person:v", "person:w", "person:x")


def test_a_road_has_its_stores_owner_and_its_named_memories_subjects():
    w = andy_world()
    w.subject(M3, "person:jenn")
    s = w.state()
    assert subjects_of(s, ROAD, T("2026-11-02")) == ("person:andy",)
    assert subjects_of(s, ROAD, T("2026-11-02"), [M1, M3]) == ("person:andy", "person:jenn")
    assert subjects_of(s, "road:Z/r1", T("2026-11-02"), [M3]) == ("person:andy", "person:jenn")   # no store: names only
    assert subjects_of(s, "road:Z/r1", T("2026-11-02")) == ()


def test_required_layers_come_in_step_2s_order_each_once():
    w, _ = e1_world(1)
    w.subject(M1, "person:jenn")
    s = w.state()
    u = use("agent:ph-coordinator", CLINIC_3, M1, at=T("2026-11-02"))
    legacy = [LegacyLayer("publisher", lambda *_: True), LegacyLayer("receiver", lambda *_: True)]
    assert required_layers(s, u, legacy=legacy) == (
        Layer("place:home/andy", "consent"), Layer("place:home/jenn", "consent"), Layer("place:la-county", "consent"),
        Layer("place:la-county/public-health", "consent"), Layer(CLINIC_3, "consent"),
        Layer("publisher", "legacy"), Layer("receiver", "legacy"), Layer("agent:ph-coordinator", "restriction"))
    out = required_layers(s, u, outside={"place:home/andy": lambda *_: "allow"})
    assert out[0] == Layer("place:home/andy", "outside") and [l.id for l in out].count("place:home/andy") == 1


def test_a_holding_place_with_no_row_is_a_layer_that_does_not_exist():
    w = andy_world()
    u = home_use(M1, T("2026-11-02"), copy="store:ghost")
    assert Layer("store:ghost", "consent") in required_layers(w.state(), u)
    assert layer_verdict(w.state(), Layer("store:ghost", "consent"), u, "recall") == "missing"


def test_e1_use_1_is_allowed_and_cites_each_layer_and_action():
    d = decide(*e1_use_1())
    assert d.allowed and d.refusal is None and d.until is None and d.horizon is None
    consent = [c for c in d.cited if c.kind == "consent"]
    layers = ["place:home/andy", "place:la-county", "place:la-county/public-health", CLINIC_3]
    assert [(c.layer, c.action) for c in consent] == [(l, a) for l in layers for a in ACTIONS[:3]]
    ids = e1_world(1)[1]
    assert {c.layer: c.records for c in consent if c.action == "read"} == {
        "place:home/andy": (ids.R1,), "place:la-county": (ids.C1,), "place:la-county/public-health": (ids.H1,),
        CLINIC_3: (ids.L1,)}
    assert [c for c in d.cited if c.kind == "restriction"] == [
        Cited("agent:ph-coordinator", "restriction", a, "silent", ()) for a in ACTIONS[:3]]
    assert set(d.versions) == set(layers) | {"agent:ph-coordinator"} and d.ledger_seq == e1_use_1()[0].seq


def test_e1_uses_2_to_4_and_12():
    s, _ = e1_use_1()
    ph = lambda obj, **kw: use("agent:ph-coordinator", CLINIC_3, obj, at=T("2026-11-02"), **kw)
    assert decide(s, ph(M3, action="read")).refusal.layer == "place:home/jenn"           # use 2
    for agent, place in [("parks-planner", "place:la-county/parks-and-rec"),
                         ("sw-helper", "place:la-county/summer-wellness")]:             # uses 3 and 4
        u = use(f"agent:{agent}", place, M1, purpose="program-operations", at=T("2026-11-02"))
        assert decide(s, u).refusal == Refusal("NO_ALLOW", "place:home/andy", "recall")
    assert decide(s, ph(M1, action="imprint")).refusal.layer == "place:home/andy"        # use 12
    assert decide(s, ph(M1, action="imprint")).refusal.action == "imprint"


def test_e1_uses_11_and_13():
    s, u = e1_after_use_9()
    assert decide(s, u(M2, T("2026-12-01"))).refusal.code == "DENIED"
    assert decide(s, u(M1, T("2026-12-01"))).allowed
    assert decide(s, u(M1, T("2026-12-15"))).refusal.code == "EXPIRED"                   # R1' ended, R1 is revoked


def test_a_road_is_decided_for_itself_then_each_named_memory_in_ref_order():
    w = andy_world()
    w.allow(HOME, audience=["self"], kinds=["memory", "road", "trail"], actions=["route"])
    s = w.state()
    u = home_use(ROAD, T("2026-11-02"), action="route", names=[M2, M1])
    d = decide(s, u)
    assert d.refusal.action == "recall"             # the road's route is allowed; the first memory's recall is not
    assert [(c.action, c.verdict) for c in d.cited if c.layer == HOME] == [("recall", "silent"), ("route", "allow")]
    w.allow(HOME, audience=["self"], actions=["recall"], memories=[M2])
    d = decide(w.state(), u)
    assert not d.allowed and [(c.action, c.verdict) for c in d.cited if c.layer == HOME][0] == ("recall", "silent")
    assert d.refusal.action == "recall"                               # m1 still fails after m2 passes
    w.allow(HOME, audience=["self"], actions=["recall"], memories=[M1])
    d = decide(w.state(), u)
    assert d.allowed
    layers = [c.layer for c in d.cited]
    assert layers == sorted(layers, key=layers.index)               # layer-major: a layer's entries are contiguous
    assert json.loads(json.dumps(d.to_json()))["cited"][0]["records"] is not None   # R8: `records` on a road


def test_a_road_whose_subjects_pass_eight_is_bound():
    w = andy_world()
    for i in range(8):
        w.person(f"p{i}")
        w.subject(M2, f"person:p{i}")
    assert decide(w.state(), home_use(ROAD, T("2026-11-02"), action="route", names=[M2])).refusal.code == "BOUND"


def test_to_json_has_the_decision_cited_refusal_and_versions():
    w = andy_world()
    rid = w.allow(HOME, audience=["self"], actions=["recall"])
    j = decide(w.state(), home_use(M1, T("2026-11-02"))).to_json()
    assert set(j) == {"allowed", "at", "ledger_seq", "action", "cited", "refusal", "until", "horizon"}
    assert j["cited"][0] == {"layer": HOME, "kind": "consent", "action": "recall", "verdict": "allow",
                             "record": rid, "version": w._find("records", id=rid)["created_seq"]}
    refused = decide(w.state(), home_use(M1, T("2026-11-02"), action="read")).to_json()
    assert refused["refusal"] == {"code": "NO_ALLOW", "layer": HOME, "action": "read"} and "mem:" not in json.dumps(
        refused["refusal"])


def test_restriction_layer_denies_but_silence_passes():
    w = andy_world()
    w.allow(HOME, audience=["self"], actions=["recall"])
    w.deny("agent:rio-grande", audience=["self"], actions=["recall"])
    assert decide(w.state(), home_use(M1, T("2026-11-02"))).refusal == Refusal("DENIED", "agent:rio-grande", "recall")


def test_a_legacy_layer_is_asked_once_per_action_and_its_verdict_is_cited():
    w = andy_world()
    w.allow(HOME, audience=["self"], actions=["recall", "read"])
    asked = []
    legacy = [LegacyLayer("publisher", lambda u, x: asked.append(x) or x == "recall")]
    d = decide(w.state(), home_use(M1, T("2026-11-02"), action="read"), legacy=legacy)
    assert asked == ["recall", "read"] and d.refusal.code == "LEGACY_DENY" and d.refusal.action == "read"
    assert [c for c in d.cited if c.kind == "legacy"] == [Cited("publisher", "legacy", "recall", "allow", ()),
                                                          Cited("publisher", "legacy", "read", "deny", ())]


def test_an_unknown_action_is_refused_as_a_rule_error():
    with pytest.raises(RuleError):
        needs(home_use(M1, 0, action="delete"))


def test_the_cited_record_has_the_latest_effective_end_then_the_smallest_id():
    w = andy_world()
    soon = w.allow(HOME, audience=["self"], actions=["recall"], valid_until=T("2026-12-01"))
    later = w.allow(HOME, audience=["self"], actions=["recall"], valid_until=T("2027-01-01"))
    u = home_use(M1, T("2026-11-02"))
    assert decide(w.state(), u).cited[0].records == (later,)
    open_ended = w.allow(HOME, audience=["self"], actions=["recall"])
    assert decide(w.state(), u).cited[0].records == (open_ended,)
    twin = w.allow(HOME, audience=["self"], actions=["recall"])
    assert decide(w.state(), u).cited[0].records == (min(open_ended, twin),)
    assert soon not in decide(w.state(), u).cited[0].records


def test_every_ancestor_of_the_holding_place_is_a_required_layer():
    w = andy_world()
    w.store("clinic-house", owner="person:ph-steward", place=CLINIC_3)
    w.allow(HOME, audience=["self"], actions=["recall"])
    for place in (CLINIC_3, "place:la-county/public-health"):
        w.allow(place, audience=["commons"], actions=["recall"])
    u = home_use(M1, T("2026-11-02"), copy="store:clinic-house")
    assert decide(w.state(), u).refusal == Refusal("NO_ALLOW", "place:la-county", "recall")   # the county's ceiling
    w.allow("place:la-county", audience=["commons"], actions=["recall"])
    assert decide(w.state(), u).allowed
