import dataclasses

import pytest
from permissions import (RuleError, check_child_grant, check_root_grant, grant_chain, grant_validity,
                         selector_within)
from tests.permissions_support import (R1_ENVELOPE, T, child_draft, county_world, three_link_chain,
                                       widen_audience)


def test_root_grant_bounds():
    w = county_world()
    g = w.grant_draft(issuer="person:andy", grantee="agent:rio-grande", layer="place:home/andy",
                      ops={"share", "withdraw"}, envelope=R1_ENVELOPE, max_days=120, depth=2, hours=720)
    check_root_grant(w.state(), g)
    for change in [{"depth": 3}, {"expires": g.created + 721 * 3600}, {"ops": frozenset({"share", "sign"})},
                   {"grantee": "agent:parks-planner"}]:      # parks-planner does not act for Andy
        with pytest.raises(RuleError):
            check_root_grant(w.state(), dataclasses.replace(g, **change))


def test_root_grant_needs_a_steward_issuer_and_no_parent():
    w = county_world()
    g = w.grant_draft(issuer="person:andy", grantee="agent:rio-grande", layer="place:home/andy",
                      ops={"share"}, envelope=R1_ENVELOPE, max_days=30, depth=0, hours=24)
    for change in [{"issuer": "person:jenn"}, {"layer": "place:la-county"}, {"parent_id": "g-" + "0" * 32}]:
        with pytest.raises(RuleError):
            check_root_grant(w.state(), dataclasses.replace(g, **change))


def test_child_is_a_subset_in_every_field_and_a_fourth_link_is_refused():
    w, root, child, grandchild = three_link_chain()          # root depth 2, child 1, grandchild 0
    check_child_grant(w.state(), root, child)
    for wider in [{"ops": root.ops | {"deny"}}, {"max_days": root.max_days + 1}, {"expires": root.expires + 1},
                  {"depth": root.depth}, {"envelope": widen_audience(root.envelope, "place:la-county")}]:
        with pytest.raises(RuleError):
            check_child_grant(w.state(), root, dataclasses.replace(child, **wider))
    with pytest.raises(RuleError, match="3 links"):
        check_child_grant(w.state(), grandchild, child_draft(grandchild))


def test_child_goes_from_the_grantee_to_another_agent_of_the_same_person():
    w, root, child, _ = three_link_chain()
    for change in [{"issuer": "person:andy"}, {"grantee": root.grantee}, {"grantee": "agent:parks-planner"},
                   {"layer": "place:la-county"}, {"parent_id": None}]:
        with pytest.raises(RuleError):
            check_child_grant(w.state(), root, dataclasses.replace(child, **change))


def test_grant_chain_is_root_first():
    w, root, child, grandchild = three_link_chain()
    assert [g.id for g in grant_chain(w.state(), grandchild.id)] == [root.id, child.id, grandchild.id]
    assert grant_chain(w.state(), root.id)[0].envelope == R1_ENVELOPE


def test_validity_walks_to_the_root_at_each_check():
    w, root, child, _ = three_link_chain()
    assert grant_validity(w.state(), child.id, T("2026-11-05")) == (True, None)
    w.revoke_grant(root.id)
    assert grant_validity(w.state(), child.id, T("2026-11-05")) == (False, "revoked")
    w2, root2, child2, _ = three_link_chain()
    assert grant_validity(w2.state(), child2.id, root2.expires) == (False, "expired")
    w3, _, child3, _ = three_link_chain(); w3.remove_steward("place:home/andy", "person:andy")
    assert grant_validity(w3.state(), child3.id, T("2026-11-05"))[1] == "not-steward"


def test_a_revocation_counts_in_every_state_at_its_seq_or_later():
    w, root, child, _ = three_link_chain()
    before = w.state()
    w.revoke_grant(child.id)
    assert grant_validity(w.state(), child.id, T("2026-11-05")) == (False, "revoked")
    assert grant_validity(w.state(), root.id, T("2026-11-05")) == (True, None)       # nothing cascades down
    assert grant_validity(before, child.id, T("2026-11-05")) == (True, None)


def test_a_chain_of_four_links_is_too_long():
    w, root, child, grandchild = three_link_chain()
    fourth = dataclasses.replace(child_draft(grandchild), id="g-" + "f" * 32, depth=0)
    w.put_grant(fourth)
    assert grant_validity(w.state(), fourth.id, T("2026-11-05")) == (False, "too-long")


def test_selector_within_audience_entries():
    s = county_world().state()
    pub = R1_ENVELOPE
    assert selector_within(s, pub, pub)
    for outer_aud, ok in [("place:la-county", True), ("commons", True), ("place:la-county/public-health", True),
                          ("place:la-county/parks-and-rec", False), ("self", False)]:
        outer = dataclasses.replace(pub, audience=(outer_aud,))
        assert selector_within(s, pub, outer) is ok
    star = dataclasses.replace(pub, purposes="*")
    assert selector_within(s, pub, star) and not selector_within(s, star, pub)
    assert selector_within(s, star, star)
    narrower = dataclasses.replace(pub, actions=("recall",))
    assert selector_within(s, narrower, pub) and not selector_within(s, pub, narrower)
