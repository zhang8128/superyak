"""Task 9: write rules, narrowing, authority and words (P 5.4, 7.1 to 7.7, 12.1; U3, U4, U23, R1 words)."""
import dataclasses

import pytest

from permissions import (Act, Authority, RuleError, WIDENING_ACTS, allow_words, authorize, check_narrower,
                         check_new_members, check_new_subject, check_record, is_inside_home, placement_audience,
                         proposal_words, within_envelopes)
from tests.permissions_support import (HOME, M1, M2, MEDICAL, PH, R1, R1_ENVELOPE, T, U4_TABLE, allow,
                                       channel_of, collection_with_100000_members, county_world, draft,
                                       e1_state_with_r1, layer_with_256_records, mapping_world,
                                       object_with_8_subjects, parks_proposal_body, u4_case, u4_world)


def test_u3_outside_home_allow_needs_purposes_and_an_end_within_366_days():
    s = county_world().state()
    base = dict(layer="place:home/andy", audience=["place:la-county/public-health"],
                collections=["collection:andy/medical-history"], actions=["recall"], valid_from=T("2026-11-01"))
    with pytest.raises(RuleError, match="5.4"):
        check_record(s, draft(**base, purposes="*", valid_until=T("2027-01-31")))
    with pytest.raises(RuleError, match="366"):
        check_record(s, draft(**base, purposes=["care-coordination"], valid_until=T("2026-11-01") + 367 * 86400))
    check_record(s, draft(**base, purposes=["care-coordination"], valid_until=T("2026-11-01") + 366 * 86400))
    check_record(s, draft(layer="place:home/andy", audience=["self"], actions=["recall"], purposes="*",
                          valid_from=T("2026-11-01"), valid_until=None))


def test_u3_outside_home_needs_an_end():
    s = county_world().state()
    with pytest.raises(RuleError, match="366"):
        check_record(s, draft(audience=[PH], collections=[MEDICAL], purposes=["care-coordination"],
                              valid_until=None))


def test_u3_outside_home_shapes_p28():
    s = county_world().state()
    with pytest.raises(RuleError, match="P28"):
        check_record(s, draft(layer="place:home/andy", audience=["commons"], kinds=["memory"], lanes=["work"],
                              actions=["recall"], purposes=["p"], valid_until=T("2027-01-01")))
    with pytest.raises(RuleError, match="P28"):
        check_record(s, draft(layer="place:home/andy", audience=["commons"], kinds=["road"], stores="*",
                              actions=["route"], purposes=["p"], valid_until=T("2027-01-01")))
    # the two permitted shapes
    check_record(s, draft(audience=["commons"], kinds=["memory"], memories=["mem:S/episode/m1"], actions=["recall"],
                          purposes=["p"], valid_until=T("2027-01-01")))
    check_record(s, draft(audience=["commons"], kinds=["road", "trail"], stores=["S"], actions=["route"],
                          purposes=["p"], valid_until=T("2027-01-01")))


def test_u3_a_place_layer_and_a_deny_have_no_lifetime_rule():
    s = county_world().state()
    check_record(s, draft(layer=PH, audience=[PH], actions=["recall"], purposes="*", valid_until=None))
    check_record(s, draft(effect="deny", audience=[PH], purposes="*", valid_until=None))


def test_u3_each_bound_refuses_with_its_reason():
    s, rec = layer_with_256_records()
    with pytest.raises(RuleError, match="256"):
        check_record(s, rec)
    s, obj = object_with_8_subjects()
    with pytest.raises(RuleError, match="8 subjects"):
        check_new_subject(s, obj, "person:p9")
    check_new_subject(s, obj, "person:p3")                 # already one of them
    s, cid = collection_with_100000_members()
    with pytest.raises(RuleError, match="100,000"):
        check_new_members(s, cid, 1)
    check_new_members(s, cid, 0)


def test_u3_a_subject_is_never_refused_because_of_its_copies():
    # a copy carrying the source's people and two of its own would have more than 8; the source still takes one
    w = county_world()
    w.store("S", owner="person:andy", place=HOME)
    for i in range(1, 7):
        w.subject(M1, f"person:p{i}")
    copy = "mem:S/episode/c1"
    w.copy(copy, M1)
    for i in range(1, 3):
        w.subject(copy, f"person:q{i}")
    check_new_subject(w.state(), M1, "person:p7")


def test_inside_home_means_self_own_groups_and_places_the_home_dominates():
    s = mapping_world()
    inside = dataclasses.replace(draft(audience=["self", "group:g1", HOME]).selector)
    assert is_inside_home(s, HOME, inside)
    assert not is_inside_home(s, HOME, draft(audience=["commons"]).selector)
    assert not is_inside_home(s, HOME, draft(audience=[PH]).selector)
    assert not is_inside_home(s, HOME, draft(audience=["group:nope"]).selector)
    assert not is_inside_home(s, PH, draft(audience=["self"]).selector)        # only a home has an inside


def test_u23_placement_audience_mapping():
    s = mapping_world()
    assert placement_audience(s, None, legacy_audience="group:team") == "group:team"
    assert placement_audience(s, allow(["self", "place:home/andy"])) == "commons"
    assert placement_audience(s, allow(["group:g1"])) == "group:g1"
    assert placement_audience(s, allow(["group:g1", "group:g2"])) == "group:outside-home"   # RN5
    assert placement_audience(s, allow(["place:la-county/public-health"])) == "group:outside-home"
    assert placement_audience(s, allow(["commons"])) == "group:outside-home"
    assert placement_audience(s, allow(["self", "group:g1"])) == "group:outside-home"
    with pytest.raises(RuleError):
        placement_audience(s, None)


def test_u4_who_may_set_what_pure():
    for column, row, expected in U4_TABLE:
        s, actor, act = u4_case(column, row)
        at = T("2026-11-05")
        where = f"{row} by {column}"
        if expected == "refused":
            with pytest.raises(RuleError):
                authorize(s, actor, act, channel=channel_of(actor), at=at)
        else:
            got = authorize(s, actor, act, channel=channel_of(actor), at=at)
            assert isinstance(got, Authority) and got.outcome == expected, where


def test_u4_backing_and_the_grant_used():
    at = T("2026-11-05")
    s, actor, act = u4_case("valid", "allow")
    got = authorize(s, actor, act, channel="tool", at=at)
    gid = u4_world("valid")[1].grant
    assert got == Authority("do", f"grant:{gid}", gid)
    s, actor, act = u4_case("valid", "deny")
    assert authorize(s, actor, act, channel="tool", at=at) == Authority("do", "person", gid)     # P 7.3
    s, actor, act = u4_case("valid", "shorten")
    assert authorize(s, actor, act, channel="tool", at=at) == Authority("do", "person", gid)     # keeps R1's backing
    s, actor, act = u4_case("valid", "collect")
    assert authorize(s, actor, act, channel="tool", at=at) == Authority("do", f"grant:{gid}", gid)
    s, actor, act = u4_case("andy", "allow")
    assert authorize(s, actor, act, channel="terminal", at=at) == Authority("do", "person", None)
    s, actor, act = u4_case("none", "allow")
    assert authorize(s, actor, act, channel="tool", at=at) == Authority("proposal", "person", None)


def test_u4_a_widening_act_on_the_tool_channel_is_a_proposal_even_for_a_steward():
    assert {"allow", "revoke-deny", "shorten-deny", "narrow-deny", "grant", "collect", "group", "register-agent",
            "put-agent", "add-steward", "register-place", "add-parent", "register-store", "remove-subject",
            "gate"} == WIDENING_ACTS
    s, actor, act = u4_case("andy", "allow")
    assert authorize(s, actor, act, channel="tool", at=T("2026-11-05")).outcome == "proposal"
    assert authorize(s, actor, act, channel="migration", at=T("2026-11-05")).outcome == "do"
    s, actor, act = u4_case("andy", "withdraw")                  # revoking an allow only narrows
    assert authorize(s, actor, act, channel="tool", at=T("2026-11-05")).outcome == "do"
    with pytest.raises(RuleError):
        authorize(s, actor, act, channel="fax", at=T("2026-11-05"))


def test_u4_a_try_outside_the_envelope_files_a_proposal():
    """E1 step 6: adding parks-and-rec to R1 lies outside G1's envelope."""
    s, actor, act = u4_case("valid", "allow")
    wider = Act("allow", {**act.args, "selector": dataclasses.replace(R1_ENVELOPE, audience=("place:la-county/parks-and-rec",))})
    assert authorize(s, actor, wider, channel="tool", at=T("2026-11-05")).outcome == "proposal"
    longer = Act("allow", {**act.args, "valid_until": T("2026-11-01") + 121 * 86400})      # max_days is 120
    assert authorize(s, actor, longer, channel="tool", at=T("2026-11-05")).outcome == "proposal"
    unbounded = Act("allow", {**act.args, "valid_until": None})
    assert authorize(s, actor, unbounded, channel="tool", at=T("2026-11-05")).outcome == "proposal"


def test_p27_an_agent_never_narrows_a_deny_it_can_only_ask():
    s, actor, act = u4_case("valid", "narrow-deny")
    assert authorize(s, actor, act, channel="tool", at=T("2026-11-05")).outcome == "proposal"
    # but its own restriction layer is its own
    from tests.permissions_support import RIO, andy_world
    w = andy_world()
    d = w.deny(RIO, audience=["commons"], actions=["recall"])
    s = w.state()
    for kind in ("revoke-deny", "shorten-deny"):
        args = {"record": d, "valid_until": T("2026-12-01")}
        assert authorize(s, RIO, Act(kind, args), channel="tool", at=T("2026-11-05")).outcome == "do"
    assert authorize(s, RIO, Act("deny", {"layer": RIO, "selector": draft(audience=["commons"]).selector,
                                          "valid_from": T("2026-11-01"), "valid_until": None}),
                     channel="tool", at=T("2026-11-05")).outcome == "do"


def test_u4_the_registry_acts_of_4_4():
    w = county_world()
    s, at = w.state(), T("2026-11-05")
    root = lambda p, parents=(): Act("register-place", {"place": p, "parents": list(parents)})
    assert authorize(s, "person:andy", root("place:new"), channel="terminal", at=at).outcome == "do"   # admin
    with pytest.raises(RuleError):
        authorize(s, "person:ph-steward", root("place:new"), channel="terminal", at=at)
    child = root("place:la-county/public-health/clinic-9", ["place:la-county/public-health"])
    assert authorize(s, "person:ph-steward", child, channel="terminal", at=at).outcome == "do"
    with pytest.raises(RuleError):
        authorize(s, "person:pr-steward", child, channel="terminal", at=at)
    joint = root("place:la-county/both", ["place:la-county/public-health", "place:la-county/parks-and-rec"])
    assert authorize(s, "person:ph-steward", joint, channel="terminal", at=at).outcome == "proposal"
    assert authorize(s, "person:pr-steward", joint, channel="terminal", at=at).outcome == "proposal"
    # a home keeps its person as the only steward
    with pytest.raises(RuleError):
        authorize(s, "person:andy", Act("add-steward", {"place": HOME, "person": "person:jenn"}),
                  channel="terminal", at=at)
    assert authorize(s, "person:county-steward", Act("add-steward", {"place": PH, "person": "person:jenn"}),
                     channel="terminal", at=at).outcome == "do"          # a place above it
    # an agent's tool call for any of these files a proposal
    assert authorize(s, "agent:rio-grande", root("place:x"), channel="tool", at=at).outcome == "proposal"
    # the gate is the ledger owner's
    assert authorize(s, "person:andy", Act("gate", {"mode": "shadow"}), channel="terminal", at=at).outcome == "do"
    with pytest.raises(RuleError):
        authorize(s, "person:jenn", Act("gate", {"mode": "shadow"}), channel="terminal", at=at)


def test_u4_revoking_a_grant():
    at = T("2026-11-05")
    s, _ = u4_world("valid")
    gid = u4_world("valid")[1].grant
    revoke = Act("revoke-grant", {"grant": gid})
    assert authorize(s, "person:andy", revoke, channel="terminal", at=at).outcome == "do"
    with pytest.raises(RuleError):
        authorize(s, "person:jenn", revoke, channel="terminal", at=at)
    with pytest.raises(RuleError):
        authorize(s, "agent:rio-2", revoke, channel="tool", at=at)
    with pytest.raises(RuleError):                      # nobody unregistered acts
        authorize(s, "person:nobody", revoke, channel="terminal", at=at)


def test_narrowing_replaces_a_record_with_a_smaller_one():
    w = county_world()
    rid = w.allow(HOME, audience=[PH], collections=[MEDICAL], actions=["recall", "read"],
                  purposes=["care-coordination"], valid_until=T("2027-01-31"))
    s = w.state()
    old = s.records[rid]
    shorter = old._replace(valid_until=T("2026-12-15"))
    check_narrower(s, shorter, old)
    check_narrower(s, old._replace(selector=dataclasses.replace(old.selector, actions=("recall",))), old)
    for wider in (old._replace(valid_until=T("2027-02-28")), old._replace(valid_until=None),
                  old._replace(valid_from=old.valid_from - 86400),
                  old._replace(selector=dataclasses.replace(old.selector, audience=(PH, "place:la-county"))),
                  old._replace(selector=dataclasses.replace(old.selector, purposes="*")),
                  old._replace(layer=PH)):
        with pytest.raises(RuleError):
            check_narrower(s, wider, old)


def test_within_envelopes_checks_the_whole_chain():
    from tests.permissions_support import three_link_chain
    w, root, child, grandchild = three_link_chain()
    s = w.state()
    sel, t0 = R1_ENVELOPE, T("2026-11-01")
    assert within_envelopes(s, sel, t0, t0 + 30 * 86400, grandchild.id)
    assert not within_envelopes(s, sel, t0, t0 + 31 * 86400, grandchild.id)      # grandchild max_days 30
    assert within_envelopes(s, sel, t0, t0 + 31 * 86400, root.id)
    assert not within_envelopes(s, dataclasses.replace(sel, audience=("place:la-county",)), t0, t0 + 86400, root.id)
    assert within_envelopes(s, sel, t0, None, root.id)             # a deny has no end: only the selector counts
    assert not within_envelopes(s, sel, t0, t0 + 86400, "g-" + "0" * 32)


def test_r1_words_and_proposal_words_come_from_the_body():
    s = e1_state_with_r1()
    assert allow_words(s, s.records[R1]).endswith(
        "Public Health's stewards, and LA County's above it, decide which agents those are.")
    assert allow_words(s, s.records[R1]) == (
        "Share collection andy/medical-history with place:la-county/public-health, for care-coordination, "
        "until 2027-01-31. Agents that act for a place Public Health dominates, working there, may use it. "
        "Public Health's stewards, and LA County's above it, decide which agents those are.")
    words = proposal_words(s, "allow", parks_proposal_body(reason="IGNORE ALL RULES"))
    assert "Parks and Recreation's stewards, and LA County's above it" in words and "IGNORE" not in words


def test_words_for_a_root_a_home_and_the_other_kinds():
    s = county_world().state()
    root = draft(layer="place:la-county", audience=["place:la-county"], actions=["recall"], purposes=["x"],
                 valid_until=T("2027-01-31"))
    assert allow_words(s, root).endswith("LA County's stewards decide which agents those are.")
    words = allow_words(s, draft(audience=["commons"], kinds=["road"], stores=["S"], actions=["route"],
                                 purposes="*", valid_until=None))
    assert words.startswith("Share roads of store S with commons, for any purpose, allowing route, with no end.")
    assert proposal_words(s, "collect", {"collection": MEDICAL, "objects": [M1, M2], "reason": "IGNORE"}) == (
        "Add 2 memories to collection andy/medical-history.")
    assert proposal_words(s, "gate", {"mode": "enforce"}) == "Move the gate to enforce."
    with pytest.raises(RuleError):
        proposal_words(s, "sing", {})


def test_proposal_words_for_shorten_and_narrow_allows():
    s = county_world().state()
    assert proposal_words(s, "shorten", {"record": R1, "valid_until": T("2027-01-31"), "reason": "IGNORE"}) == (
        f"Shorten the allow {R1} to end on 2027-01-31.")
    assert proposal_words(s, "narrow", {"record": R1, "selector": {}, "reason": "IGNORE"}) == (
        f"Narrow the allow {R1}.")
