"""U24's fixture is the one R23 names (Task 31). This file runs in the default suite; the budgets themselves are
in test_permissions_pi_budget.py and run only on the Pi."""
from collections import Counter

import permissions
from permissions import BulkUse, Use, decide, decide_bulk, eligible_set, required_layers
from tests.permissions_support import (AGENT, COPY, LEGACY_LAYERS, PLACE, T, derived_trails,
                                       generated_world, touches)

AT = T("2026-11-02")
MEASURED = (("recall", "care-coordination"), ("imprint", "trail-evaluation"))


def _use(obj, action="recall", purpose="care-coordination"):
    return Use(requester=AGENT, place=PLACE, obj=obj, copy=COPY, action=action, purpose=purpose, at=AT)


def _ledger_layers(state, obj):
    return [l.id for l in required_layers(state, _use(obj), legacy=LEGACY_LAYERS) if l.kind in ("consent", "restriction")]


def _why_it_fails(state, rec, use, action):
    """The pre-filter dimensions a record fails on."""
    sel = rec.selector
    bad = []
    if not permissions._star_or_in(sel.requesters, use.requester):
        bad.append("requesters")
    if not permissions._star_or_in(sel.actions, action):
        bad.append("actions")
    if not permissions._star_or_in(sel.purposes, use.purpose):
        bad.append("purposes")
    if not any(permissions._audience_entry(state, v, rec.layer, use, rec.anchor, rec.effect == "deny")
               for v in sel.audience):
        bad.append("audience")
    return bad


def _shape(rec):
    """Which of R23's four shapes a passing record has."""
    if rec.effect == "deny":
        return "deny"
    o = rec.selector
    if o.collections != permissions.STAR:
        return "collections"
    if o.memories != permissions.STAR:
        return "memories"
    if o.lanes != permissions.STAR:
        return "lanes"
    return "other"


def test_u24_the_fixture_is_the_one_r23_names():
    state, placements = generated_world(placements=200, layers=43, records_per_layer=256)
    assert len(placements) == 200
    obj = placements[0].obj
    layers = _ledger_layers(state, obj)
    assert len(layers) == 41 and len(set(layers)) == 41
    by_layer = {}
    for r in state.records.values():
        by_layer.setdefault(r.layer, []).append(r)
    assert set(by_layer) == set(layers)
    for action, purpose in MEASURED:
        use = _use(obj, action, purpose)
        for layer in layers:
            recs = by_layer[layer]
            assert len(recs) == 256 and all(r.revoked_seq is None and r.valid_until is None for r in recs)
            passing = permissions._prefilter(state, layer, use, action)
            assert len(passing) == 32, (layer, action, len(passing))
            assert Counter(_shape(r) for r in passing) == {"collections": 8, "memories": 8, "lanes": 8, "deny": 8}
            lists = [r.selector.memories for r in passing if _shape(r) == "memories"]
            assert all(len(m) == 512 for m in lists)
            lanes = [r.selector.lanes for r in passing if _shape(r) == "lanes"]
            assert all(tuple(l) == ("work",) for l in lanes)
            denies = [r for r in passing if r.effect == "deny"]
            assert all(len(r.selector.memories) == 64 for r in denies)
            placed = {p.obj for p in placements}
            assert not any(set(r.selector.memories) & placed for r in denies)
            failing = [r for r in recs if r not in passing]
            assert len(failing) == 224
            why = Counter()
            for r in failing:
                dims = _why_it_fails(state, r, use, action)
                assert len(dims) == 1, (r.id, dims)
                why[dims[0]] += 1
            assert why == {"audience": 56, "requesters": 56, "actions": 56, "purposes": 56}


def test_u24_each_decision_meets_43_layers_and_every_placement_is_allowed():
    state, placements = generated_world(placements=200, layers=43, records_per_layer=256)
    assert len(LEGACY_LAYERS) == 2
    for p in placements[::10]:                  # all 200 go through eligible_set below
        subjects = permissions.subjects_of(state, p.obj, AT)
        assert len(subjects) == 8
        d = decide(state, _use(p.obj), legacy=LEGACY_LAYERS)
        assert d.allowed, d.refusal
        assert len({c.layer for c in d.cited}) == 43
        assert len(required_layers(state, _use(p.obj), legacy=LEGACY_LAYERS)) == 43
    got = eligible_set(state, placements, requester=AGENT, place=PLACE, purpose="care-coordination",
                       action="recall", at=AT)
    assert got.memory_ids == frozenset(p.memory_id for p in placements)
    assert all(d.allowed for d in got.decisions.values())


def test_u24_eight_collections_hold_a_share_of_the_universe_each():
    state, _ = generated_world(placements=0, layers=43, records_per_layer=256, universe=800)
    sizes = Counter(r.collection for rows in state.collection_members.values() for r in rows)
    assert len(sizes) == 8 and set(sizes.values()) == {100}


def test_u24_derived_trails_are_decided_object_by_object_and_allowed():
    state, _ = generated_world(placements=0, layers=43, records_per_layer=256, universe=800, trails=6)
    trails = derived_trails(6)
    assert len(trails) == 6 and len(set(trails)) == 6
    first = tuple(touches(trails[0], 512, universe=800))
    assert len(first) == 512 and len(set(first)) == 512 and first == tuple(touches(trails[0], 512, universe=800))
    assert any(tuple(touches(t, 512, universe=800)) != first for t in trails[1:])
    bulk = BulkUse(requester=AGENT, place=PLACE, objects=trails, copy=COPY, action="imprint",
                   purpose="trail-evaluation", at=AT, named=False, names=lambda t: touches(t, 32, universe=800))
    d = decide_bulk(state, bulk, group=False)
    assert d.allowed, d.refusal


def test_the_bulk_world_has_7_memory_lists_and_one_road_trail_allow_in_each_layer():
    s, _ = generated_world(placements=0, layers=43, records_per_layer=256, universe=800, trails=6)
    by_layer = {}
    for r in s.records.values():
        by_layer.setdefault(r.layer, []).append(r)
    assert len(by_layer) == 41
    for layer, recs in by_layer.items():
        lists = [r for r in recs if r.effect == "allow" and r.selector.memories != permissions.STAR
                 and len(r.selector.memories) == 512]
        assert len(lists) == 7, layer
        trail = [r for r in recs if r.effect == "allow" and tuple(r.selector.kinds) == ("road", "trail")]
        assert len(trail) == 1 and trail[0].selector.memories == permissions.STAR, layer
