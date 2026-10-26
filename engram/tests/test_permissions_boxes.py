"""Task 8: boxes, the gluing check and ineffective parts (P 8, U15)."""
import pytest

from permissions import (BOX_CAP, REGISTRY, STAR, Box, FSet, GluingReport, TimeSet, TooComplex, affected_joints,
                         box_and, box_contains, box_empty, box_minus, box_subset, disagreement_words, gluing,
                         ineffective, layer_boxes, stewards)
from tests.permissions_support import (HOME, MEDICAL, M1, M2, M3, M4, T, World, cap_breaking_joint, cap_world,
                                       e1_county_rules, e1_world)

SW = "place:la-county/summer-wellness"
PH = "place:la-county/public-health"
PR = "place:la-county/parks-and-rec"
CLINIC = "place:la-county/public-health/clinic-3"


def test_u15_summer_wellness_disagreement_and_who_sees_it():
    s = e1_county_rules()
    r = gluing(s, SW)
    assert not r.too_complex and r.delta and not r.ineffective
    assert r.notify == stewards(s, SW, PH)          # P 8: J and the parent whose chain refuses part of Delta
    assert stewards(s, PR) and stewards(s, PR).isdisjoint(r.notify)      # the allowing parent is not told
    assert disagreement_words(s, r) == ("Parks and Recreation allows read in Summer Wellness for program-operations; "
        "Public Health does not. Until one of you changes your rules, Summer Wellness may only recall.")


def test_u15_ineffective_part_at_a_single_parent_place_goes_to_its_stewards():
    s = e1_county_rules(extra=(CLINIC, "imprint"))
    r = ineffective(s, CLINIC)
    assert r.ineffective and r.notify == stewards(s, CLINIC)


def test_u15_box_cap_reports_could_not_check():
    s, joint = cap_breaking_joint()
    r = gluing(s, joint)
    assert r.too_complex and r.notify and disagreement_words(s, r).startswith("could not check: too complex")
    assert r.notify == stewards(s, joint, "place:big/left", "place:big/right")


def test_the_cap_is_past_4096_boxes():
    s, joint = cap_world(BOX_CAP)
    assert len(layer_boxes(s, joint, at_place=joint)) == BOX_CAP
    s, joint = cap_world(BOX_CAP + 1)
    with pytest.raises(TooComplex):
        layer_boxes(s, joint, at_place=joint)


def test_a_county_with_nothing_to_report_reports_nothing():
    s = e1_county_rules()
    for place in (PH, PR, CLINIC, "place:la-county"):
        r = gluing(s, place)
        assert not r.delta and not r.too_complex and r.notify == frozenset()
        assert disagreement_words(s, r) == ""
    assert not ineffective(s, CLINIC).ineffective


def test_ineffective_words_name_the_place_and_the_part():
    s = e1_county_rules(extra=(CLINIC, "imprint"))
    words = disagreement_words(s, ineffective(s, CLINIC))
    assert words == ("clinic-3 asks for imprint in clinic-3 for care-coordination that the places above it do not "
                     "allow, so that part has no effect.")


def test_a_joint_places_ineffective_part_is_what_no_parent_allows():
    s = e1_county_rules(extra=(SW, "route"))     # H2 and K2 lack route; K1 has it but names parks, not summer-wellness
    r = gluing(s, SW)
    assert r.ineffective and r.delta and r.notify >= stewards(s, SW)
    assert any(box_contains(b, (SW, "agent:sw-helper", "memory", "S", "episode", "none", M1, "route",
                                "care-coordination", T("2026-11-02"))) for b in r.ineffective)


def test_layer_boxes_follow_grant_backed_members_and_their_expiry():
    w, ids = e1_world(7)
    s = w.state()
    boxes = layer_boxes(s, HOME, at_place=CLINIC)

    def allowed(obj, at):
        pt = (CLINIC, "agent:ph-coordinator", "memory", "S", "episode", "none", obj, "recall", "care-coordination", at)
        return any(box_contains(b, pt) for b in boxes)
    assert allowed(M1, T("2026-11-02")) and allowed(M4, T("2026-11-10"))
    assert not allowed(M4, T("2026-12-01"))          # G1 expired on 2026-11-30
    assert allowed(M1, T("2026-12-01"))              # R1 itself is person-backed
    assert not allowed(M3 + "x", T("2026-11-02"))    # not in the collection
    assert not allowed(M1, T("2027-02-01"))          # R1 ended 2027-01-31


def test_a_deny_takes_its_box_away_from_the_layer():
    w, ids = e1_world(9)
    s = w.state()
    boxes = layer_boxes(s, HOME, at_place=CLINIC)
    pt = lambda obj, at: (CLINIC, "agent:ph-coordinator", "memory", "S", "episode", "none", obj, "recall",
                          "care-coordination", at)
    assert any(box_contains(b, pt(M2, T("2026-11-20"))) for b in boxes)
    assert not any(box_contains(b, pt(M2, T("2026-12-02"))) for b in boxes)       # D1 from 2026-12-01
    assert any(box_contains(b, pt(M1, T("2026-12-02"))) for b in boxes)


def test_affected_joints_are_the_joints_at_or_below_a_changed_layer_in_id_order():
    s = e1_county_rules()
    assert affected_joints(s, [SW]) == (SW,)
    assert affected_joints(s, [PH]) == (SW,)
    assert affected_joints(s, ["place:la-county"]) == (SW,)
    assert affected_joints(s, [CLINIC]) == ()
    assert affected_joints(s, [HOME]) == ()
    assert affected_joints(s, [REGISTRY]) == (SW,)
    assert affected_joints(s, []) == ()


def test_registry_change_names_every_joint_in_id_order():
    w = World()
    w.person("st")
    for p in ("place:z", "place:y", "place:a"):
        w.place(p, stewards=["st"])
    for j, (p, q) in {"place:z/j2": ("place:z", "place:y"), "place:a/j1": ("place:a", "place:z")}.items():
        w.place(j, parents=[p, q], stewards=["st"])
    s = w.state()
    assert affected_joints(s, [REGISTRY]) == ("place:a/j1", "place:z/j2")
    assert affected_joints(s, ["place:y"]) == ("place:z/j2",)


def test_box_algebra_by_hand():
    full = Box.full()
    a = Box.full().but(action=FSet(frozenset({"read", "recall"}), False), time=TimeSet(((0, 10),)))
    b = Box.full().but(action=FSet(frozenset({"read"}), False), time=TimeSet(((5, None),)))
    both = box_and(a, b)
    assert both.action == FSet(frozenset({"read"}), False) and both.time == TimeSet(((5, 10),))
    assert box_and(a, Box.full().but(action=FSet(frozenset({"route"}), False))) is None
    pieces = box_minus(full, b)
    assert 1 <= len(pieces) <= 10 and all(not box_empty(p) for p in pieces)
    assert box_subset(both, a) and not box_subset(a, b)
    assert box_empty(Box.full().but(time=TimeSet(())))
    assert STAR == "*"


def _pt(obj, at, place=CLINIC, agent="agent:ph-coordinator"):
    return (place, agent, "memory", "S", "episode", "none", obj, "recall", "care-coordination", at)


def test_a_replacement_lies_within_its_original_by_time():
    w, ids = e1_world(8)                    # R1' shortens R1 to 2026-12-15
    boxes = layer_boxes(w.state(), HOME, at_place=CLINIC)
    assert any(box_contains(b, _pt(M1, T("2026-12-10"))) for b in boxes)
    assert not any(box_contains(b, _pt(M1, T("2026-12-20"))) for b in boxes)


def test_a_removed_membership_is_never_counted_for_an_allow():
    w, ids = e1_world(1)
    w.now = T("2026-11-03")
    w.uncollect(MEDICAL, M2)
    boxes = layer_boxes(w.state(), HOME, at_place=CLINIC)
    assert any(box_contains(b, _pt(M1, T("2026-11-02"))) for b in boxes)
    assert not any(box_contains(b, _pt(M2, T("2026-11-02"))) for b in boxes)   # not even before its removal

