"""Task P7 (perf-design.md 2.H; spec 6.4, 6.5 "How it is computed", 12.2): an eligible set decides once for objects
that read alike, and its decisions equal deciding each object alone."""
import dataclasses
import random

import pytest

import permissions
from permissions import Placement, RuleError, Use, decide, eligible_set, parse_selector
from tests.permissions_support import (HOME, M1, M2, T, World, andy_world, home_use, random_world, sample_uses)

COPY = "store:house"
AT = T("2026-11-02")
ANCHOR = T("2026-11-01") + 3600


def _key(state, obj, t=AT):
    return permissions._share_key(state, obj, t)


def _set(state, objs, at=AT, copy=COPY):
    return eligible_set(state, [Placement(f"id{i}", o, copy) for i, o in enumerate(objs)], requester="agent:rio-grande",
                        place=HOME, purpose="care-coordination", action="recall", at=at)


def _alone(state, obj, at=AT, copy=COPY):
    try:
        return decide(state, home_use(obj, at, copy=copy))
    except RuleError:
        return None


def _same(a, b):
    if a is None or b is None:
        return a is b
    return (a.to_json(), dict(a.versions), a.processed, a.failed_need) == (
        b.to_json(), dict(b.versions), b.processed, b.failed_need)


# -- (a) the A/B case of 2.H: a place among the times of interest is not just an order

def test_notes_exactly_at_an_anchor_refuse_one_second_before_allow_and_their_keys_differ():
    w = andy_world()
    a, b = "mem:S/episode/a", "mem:S/episode/b"
    w.now = ANCHOR
    w.allow(HOME, audience=["self"], lanes=["work"], actions=["recall"])
    for obj, at in ((a, ANCHOR), (b, ANCHOR - 1)):
        w.lane(obj, "personal", at)
        w.lane(obj, "work", at)
    s = w.state()
    got = _set(s, [a, b])
    assert not got.decisions[a].allowed and got.decisions[b].allowed
    assert _same(got.decisions[a], _alone(s, a)) and _same(got.decisions[b], _alone(s, b))
    assert _key(s, a) is not None and _key(s, a) != _key(s, b)


def test_objects_that_read_alike_share_one_decision():
    w = andy_world()
    w.allow(HOME, audience=["self"], actions=["recall"])
    objs = [f"mem:S/episode/x{i}" for i in range(5)]
    for o in objs:
        w.lane(o, "work", T("2026-10-20") + 7)
    s = w.state()
    assert len({_key(s, o) for o in objs}) == 1
    got = _set(s, objs)
    assert len({id(got.decisions[o]) for o in objs}) == 1
    assert all(_same(got.decisions[o], _alone(s, o)) for o in objs)


# -- (b) the two worlds of fuzz_share.py: every eligible-set decision equals deciding the object alone

def _check(s, uses, objs, copy_of=lambda u: u.copy):
    checked = 0
    for u in uses:
        es = eligible_set(s, [Placement(f"id{k}", o, copy_of(u)) for k, o in enumerate(objs)],
                          requester=u.requester, place=u.place, purpose=u.purpose, action=u.action, at=u.at)
        for o in objs:
            try:
                alone = decide(s, dataclasses.replace(u, obj=o, names=(), shows=frozenset()))
            except RuleError:
                alone = None
            assert _same(alone, es.decisions.get(o)), (o, u)
            checked += 1
    return checked


@pytest.mark.parametrize("case", range(20))
def test_a_random_world_with_listing_records_decides_each_object_as_alone(case):
    rng = random.Random(f"fuzz-share-{case}")
    w = random_world(rng)
    recs = w.rows.get("records", [])
    times = sorted({r["anchor"] for r in recs} | {r["valid_from"] for r in recs})
    uses = [u for u in sample_uses(random.Random(f"fuzz-share-uses-{case}"), w, 12) if isinstance(u, Use)]
    times += [u.at for u in uses]
    near = sorted({x + d for x in times for d in (-1, 0, 1)})
    colls = [r["id"] for r in w.rows.get("collections", [])]
    persons = [r["id"] for r in w.rows.get("persons", [])]
    stores = [r["instance_id"] for r in w.rows.get("stores", [])] or ["S"]
    objs = []
    for k in range(60):
        ref = f"mem:{rng.choice(stores)}/{rng.choice(['episode', 'semantic'])}/fz{case}x{k}"
        objs.append(ref)
        for _ in range(rng.choice([0, 1, 1, 2, 3])):
            w.lane(ref, rng.choice(["work", "personal", "pending"]), rng.choice(near))
        if colls and rng.random() < 0.7:
            for c in rng.sample(colls, rng.choice([1, 1, 2])):
                save, w.now = w.now, rng.choice(near)
                w.collect(c, [ref])
                if rng.random() < 0.3:
                    w.now = rng.choice(near)
                    w.uncollect(c, ref)
                w.now = save
        if rng.random() < 0.3:
            w.subject(ref, rng.choice(persons))
    for k in range(5):
        w.copy(objs[k], objs[k + 5])
    layers = list(getattr(w.cfg, "places", [])) + [f"place:home/{h}" for h in ("andy", "jenn")]
    made = []
    for k in range(14):
        save, w.now = w.now, rng.choice(near)
        kw = dict(audience=[rng.choice(["commons", "self"])], memories=rng.sample(objs, rng.choice([3, 10, 30])))
        if rng.random() < 0.3:
            kw["lanes"] = [rng.choice(["work", "personal"])]
        layer = rng.choice(layers)
        if made and rng.random() < 0.4:
            old_rid, old_layer = rng.choice(made)
            kw["replaces"], layer = old_rid, old_layer
            rid = (w.allow if rng.random() < 0.8 else w.deny)(layer, **kw)
            try:
                w.revoke(old_rid)
            except KeyError:
                pass
        else:
            rid = (w.allow if rng.random() < 0.7 else w.deny)(layer, **kw)
        if rng.random() < 0.15:
            w.revoke(rid)
        made.append((rid, layer))
        w.now = save
    s = w.state()
    assert _check(s, uses, objs) == len(uses) * len(objs)


@pytest.mark.parametrize("case", range(20))
def test_a_world_decided_by_lanes_and_collections_at_close_anchors_decides_each_object_as_alone(case):
    rng = random.Random(f"focused-{case}")
    w = World(start=T("2026-10-01"))
    w.agent("a0", HOME, at=HOME)
    w.store("S", owner="person:andy", place=HOME)
    w.store("H", owner="person:andy", place=HOME)
    colls = ("collection:andy/c1", "collection:andy/c2")
    for c in colls:
        w._add("collections", id=c, owner="person:andy", created_seq=w._bump())
    base = T("2026-10-10")
    near = [base + d for d in range(40)]
    objs = [f"mem:S/episode/f{case}x{k}" for k in range(80)]
    for o in objs:
        for _ in range(rng.choice([0, 1, 2, 3])):
            w.lane(o, rng.choice(["work", "personal", "pending"]), rng.choice(near))
        for c in colls:
            if rng.random() < 0.5:
                save, w.now = w.now, rng.choice(near)
                w.collect(c, [o])
                if rng.random() < 0.4:
                    w.now = rng.choice(near)
                    w.uncollect(c, o)
                w.now = save
    for _ in range(rng.choice([3, 5, 8])):
        save, w.now = w.now, rng.choice(near)
        kw = dict(audience=["commons"])
        pick = rng.random()
        if pick < 0.4:
            kw["lanes"] = [rng.choice(["work", "personal"])]
        elif pick < 0.8:
            kw["collections"] = [rng.choice(colls)]
        else:
            kw["lanes"], kw["collections"] = [rng.choice(["work", "personal"])], [rng.choice(colls)]
        if rng.random() < 0.3:
            kw["valid_from"] = rng.choice(near)
        (w.deny if rng.random() < 0.35 else w.allow)(HOME, **kw)
        w.now = save
    s = w.state()
    uses = [Use(requester="agent:a0", place=HOME, obj=objs[0], copy="store:H", action="recall", purpose="p", at=t)
            for t in rng.sample(near, 6)]
    assert _check(s, uses, objs) == len(uses) * len(objs)


# -- (c) what is decided alone

def test_roads_trails_and_malformed_refs_get_no_key():
    s = andy_world().state()
    for ref in ("road:S/r1", "trail:S/t1", "mem:", "not a ref", "mem:S/episode", "", 7, None):
        assert _key(s, ref) is None, ref


def test_a_memory_with_a_grant_backed_membership_gets_no_key():
    w = andy_world()
    envelope = parse_selector({"audience": ["self"], "requesters": "*",
                               "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
                                           "collections": "*", "memories": "*"},
                               "actions": ["recall"], "purposes": "*"})
    g = w.put_grant(w.grant_draft(issuer="person:andy", grantee="agent:rio-grande", layer=HOME, ops={"share"},
                                  envelope=envelope, max_days=30, depth=0, hours=720))
    w.collect("collection:andy/g", [M1], backing=f"grant:{g.id}")
    w.collect("collection:andy/p", [M2])
    s = w.state()
    assert _key(s, M1) is None
    assert _key(s, M2) is not None


def test_a_ledger_whose_grant_envelope_lists_memories_shares_nothing_and_never_widens_an_allow():
    """The ruling of the spec revision 8 check (M1): G's envelope lists m1 only, m1 and m2 are collected under G, and
    an allow backed by G names the collection: m1 is allowed, m2 refused, and neither is shared."""
    w = andy_world()
    envelope = parse_selector({"audience": ["self"], "requesters": "*",
                               "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
                                           "collections": "*", "memories": [M1]},
                               "actions": ["recall"], "purposes": "*"})
    g = w.put_grant(w.grant_draft(issuer="person:andy", grantee="agent:rio-grande", layer=HOME, ops={"share"},
                                  envelope=envelope, max_days=30, depth=0, hours=720))
    w.collect("collection:andy/g", [M1, M2], backing=f"grant:{g.id}")
    w.allow(HOME, audience=["self"], collections=["collection:andy/g"], actions=["recall"], backing=f"grant:{g.id}")
    plain = [f"mem:S/episode/p{i}" for i in range(3)]
    s = w.state()
    assert permissions._envelopes_list_memories(s)
    assert all(_key(s, o) is None for o in (M1, M2, *plain))
    got = _set(s, [M1, M2])
    assert got.decisions[M1].allowed and not got.decisions[M2].allowed
    assert _same(got.decisions[M1], _alone(s, M1)) and _same(got.decisions[M2], _alone(s, M2))
    assert got.decisions[M1] is not got.decisions[M2]


def test_a_grant_whose_envelope_lists_no_memories_leaves_sharing_on():
    w = andy_world()
    envelope = parse_selector({"audience": ["self"], "requesters": "*",
                               "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
                                           "collections": "*", "memories": "*"},
                               "actions": ["recall"], "purposes": "*"})
    w.put_grant(w.grant_draft(issuer="person:andy", grantee="agent:rio-grande", layer=HOME, ops={"share"},
                              envelope=envelope, max_days=30, depth=0, hours=720))
    s = w.state()
    assert not permissions._envelopes_list_memories(s)
    assert _key(s, M1) is not None


def test_a_road_in_an_eligible_set_is_decided_alone_and_equals_deciding_it_alone():
    w = andy_world()
    w.allow(HOME, audience=["self"], kinds=["memory", "road"], actions=["recall"])
    s = w.state()
    objs = ["road:S/r1", "road:S/r2", M1, M2]
    got = _set(s, objs)
    for o in objs:
        assert _same(got.decisions.get(o), _alone(s, o)), o
    assert got.decisions["road:S/r1"] is not got.decisions["road:S/r2"]


# -- (d) at most 4,096 keys are kept

def test_the_shared_decisions_kept_are_bounded_at_4096():
    assert permissions.SHARED_DECISIONS == 4096


def _pairs_world(n):
    """n distinct readings, each held by two objects: records at n distinct anchors make n places among Θ."""
    w = andy_world()
    base = T("2026-10-20")
    for i in range(n):
        w.now = base + 100 * i
        w.allow(HOME, audience=["self"], actions=["recall"], lanes=["work"])
    objs = []
    for i in range(n):
        for tag in "ab":
            o = f"mem:S/episode/{tag}{i}"
            w.lane(o, "work", base + 100 * i)
            objs.append(o)
    return w.state(), objs


def test_no_more_keys_are_kept_than_the_bound(monkeypatch):
    s, objs = _pairs_world(10)
    calls = []
    real = permissions.decide
    monkeypatch.setattr(permissions, "decide", lambda *a, **k: calls.append(a[1].obj) or real(*a, **k))
    got = _set(s, objs)
    assert len(calls) == 10                                    # one decision for each pair
    calls.clear()
    monkeypatch.setattr(permissions, "SHARED_DECISIONS", 3)
    capped = _set(s, objs)
    assert len(calls) == 3 + 2 * 7                             # three pairs shared; seven pairs decided twice
    monkeypatch.setattr(permissions, "SHARED_DECISIONS", 0)
    calls.clear()
    none = _set(s, objs)
    assert len(calls) == 20
    for o in objs:
        assert _same(got.decisions[o], capped.decisions[o]) and _same(got.decisions[o], none.decisions[o])
