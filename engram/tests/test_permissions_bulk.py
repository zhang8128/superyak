"""Task 7 (U22): roads, trails and bulk uses."""
import collections
import json

from permissions import LegacyLayer, Refusal, decide, decide_bulk
from tests.permissions_support import (
    HOME, M1, M2, M3, ROAD, T, TRAIL, andy_world, bulk_use, home_use, memories, road_world, route,
    trail_use, trail_world, trails_of)

A, B, C = M1, M2, M3


def test_u22_a_route_answer_needs_read_and_inject_on_what_it_shows_and_recall_on_what_it_names():
    s = road_world()                 # road r names a and b; inject_context is not allowed on b
    assert decide(s, route(ROAD, names=(A, B), shows={A})).allowed
    assert decide(s, route(ROAD, names=(A, B), shows={A, B})).refusal.action == "inject_context"


def test_u22_every_action_on_a_trail_needs_recall_on_every_memory_it_names():
    s = trail_world(blocked=C)       # C may not be recalled by this audience
    for x in ("recall", "read", "imprint"):
        assert not decide(s, trail_use(TRAIL, x, names=(A, B, C))).allowed
    s = trail_world()
    for x in ("recall", "read", "imprint"):
        assert decide(s, trail_use(TRAIL, x, names=(A, B, C))).allowed


def test_u22_answer_uses_name_at_most_32():
    s = trail_world()
    t33, t32 = "trail:S/t33", "trail:S/t32"
    assert decide(s, trail_use(t33, "route", names=memories(33))).refusal.code == "BOUND"
    assert decide(s, trail_use(t32, "route", names=memories(32))).allowed
    # a shown memory is a named one; 32 named and one more shown is 33
    assert decide(s, route(t32, names=memories(32), shows=memories(1, 32))).refusal.code == "BOUND"
    # the bound is that of a name count, whatever the memories are allowed
    assert decide(s, trail_use(t33, "recall", names=memories(33))).refusal.code == "BOUND"


def test_u22_a_bulk_route_over_three_trails_of_40_touches_is_allowed():
    s = trail_world()
    trails, names = trails_of(3, 40)
    bulk = bulk_use(trails, names=names, named=False)
    assert decide_bulk(s, bulk).allowed
    assert all(decide(s, trail_use(t, "route", names=names(t))).refusal.code == "BOUND" for t in bulk.objects)


def _denied_world():
    """Three memories; the home layer allows recall on each, m1 and m3 until a date, a deny on m2, and a dated
    deny that starts on m3 later."""
    w = andy_world()
    w.allow(HOME, audience=["self"], memories=[M1], actions=["recall"], valid_until=T("2026-12-01"))
    w.allow(HOME, audience=["self"], memories=[M3], actions=["recall"], valid_until=T("2026-12-15"))
    w.allow(HOME, audience=["self"], memories=[M2], actions=["recall"])
    w.deny(HOME, audience=["self"], memories=[M2], actions=["recall"])
    w.deny(HOME, audience=["self"], memories=[M3], actions=["recall"], valid_from=T("2026-11-20"))
    return w.state(), bulk_use([M1, M2, M3], action="recall", named=True)


def test_u22_one_failing_object_refuses_the_bulk_use_without_naming_it():
    s, bulk = _denied_world()
    d = decide_bulk(s, bulk)
    assert d.refusal == Refusal("DENIED", "place:home/andy", "recall") and "mem:" not in json.dumps(d.to_json())
    per_object = [decide(s, home_use(o, bulk.at, action="recall")) for o in bulk.objects]
    assert d.until == min(x.until for x in per_object if x.until is not None) == T("2026-11-20")
    assert d.horizon == min(x.horizon for x in per_object if x.horizon is not None)
    assert d.multi and all(c.records == tuple(sorted(c.records)) for c in d.cited)
    home_recall = [c for c in d.cited if (c.layer, c.action) == (HOME, "recall")]
    assert len(home_recall) == 1 and len(home_recall[0].records) == 2       # one per allowed object, aggregated
    assert d.to_json()["cited"][0]["records"] == list(d.cited[0].records)


def test_u22_the_first_failing_object_in_ref_order_gives_the_refusal():
    w = andy_world()
    w.allow(HOME, audience=["self"], actions=["recall"])
    w.deny(HOME, audience=["self"], memories=[M3], actions=["recall"])
    s = w.state()
    assert decide_bulk(s, bulk_use([M3, M1], action="recall")).refusal == Refusal("DENIED", HOME, "recall")
    w = andy_world()                 # a refusal at a later layer comes with its own code
    w.allow(HOME, audience=["self"], actions=["recall"], memories=[M1])
    assert decide_bulk(w.state(), bulk_use([M2, M1], action="recall")).refusal.code == "NO_ALLOW"


def test_u22_size_bounds_come_before_any_object():
    s = trail_world()
    objs = tuple(f"mem:S/episode/m{i}" for i in range(100_001))
    assert decide_bulk(s, bulk_use(objs, action="recall")).refusal == Refusal("BOUND")
    assert decide_bulk(s, bulk_use(memories(513), action="recall", named=True)).refusal == Refusal("BOUND")
    assert decide_bulk(s, bulk_use(memories(512), action="recall", named=True)).allowed
    assert decide_bulk(s, bulk_use(objs, action="recall", requester="agent:nobody")).refusal.code == \
        "UNKNOWN_REQUESTER"
    assert decide_bulk(s, bulk_use(memories(513), action="recall", named=True,
                                   requester="agent:nobody")).refusal.code == "UNKNOWN_REQUESTER"
    w = andy_world()
    w.allow(HOME, audience=["self"], actions=["recall"])
    w.retire_place("place:home/andy")
    assert decide_bulk(w.state(), bulk_use(objs, action="recall")).refusal.code == "RETIRED"


def test_u22_named_memories_bound_and_split():
    s = trail_world()
    per = 512
    total = 100_001
    refs = tuple(f"trail:S/t{i}" for i in range((total + per - 1) // per))

    def slice_of(o):
        i = int(o.rpartition("/t")[2])
        return memories(min(per, total - i * per), i * per)
    big = bulk_use(refs, names=slice_of)
    assert decide_bulk(s, big).refusal == Refusal("BOUND")
    cut = 195                         # 195 trails name 99,840 memories, the last 161 more
    first = bulk_use(refs[:cut], names=slice_of)
    second = bulk_use(refs[cut:], names=slice_of)
    assert decide_bulk(s, first).allowed and decide_bulk(s, second).allowed


def test_u22_a_memory_named_by_many_trails_counts_once_toward_the_bound():
    s = trail_world()
    trails, names = trails_of(250, 512, same_memories=True)         # 128,000 touches, 512 distinct memories
    assert decide_bulk(s, bulk_use(trails, names=names)).allowed


def _bulk_world():
    w = andy_world()
    w.allow(HOME, audience=["self"], actions=["recall"], memories=[M1, M3, "mem:S/episode/m9"])
    for i in range(8):
        w.person(f"p{i}")
        w.subject(M3, f"person:p{i}")
        w.allow(f"place:home/p{i}", audience=[HOME], actions=["recall"])
    w.deny(HOME, audience=["self"], memories=[M1], actions=["recall"])
    return w.state()


def test_u22_no_subject_and_nine_subjects_unless_an_earlier_object_fails():
    s = _bulk_world()
    no_subject, nine = "mem:Z/episode/m5", M3
    assert decide_bulk(s, bulk_use([no_subject], action="recall")).refusal.code == "NO_LAYER"
    assert decide_bulk(s, bulk_use([nine], action="recall")).refusal.code == "BOUND"
    assert decide_bulk(s, bulk_use([M1, nine], action="recall")).refusal.code == "DENIED"      # m1 is first
    assert decide_bulk(s, bulk_use([nine, M1], action="recall")).refusal.code == "DENIED"      # sorted: m1 first
    assert decide_bulk(s, bulk_use([no_subject, nine], action="recall")).refusal.code == "BOUND"   # m3 < Z
    assert decide_bulk(s, bulk_use([M1, no_subject], action="recall")).refusal.code == "DENIED"


def test_u22_a_road_or_trail_of_nine_subjects_is_bound_even_in_a_bulk_use():
    w = andy_world()
    w.allow(HOME, audience=["self"], kinds=["memory", "road", "trail"], actions=["recall", "route"])
    for i in range(8):
        w.person(f"p{i}")
        w.subject("mem:S/episode/m50", f"person:p{i}")
    s = w.state()
    assert decide_bulk(s, bulk_use(["trail:S/t1"], names=lambda o: ("mem:S/episode/m50",))).refusal.code == "BOUND"


def test_u22_a_memory_named_by_many_objects_is_decided_once_per_action():
    s, calls = trail_world(), collections.Counter()
    counting = [LegacyLayer("count", lambda u, x: calls.update([(u.obj, x)]) is None)]   # allows, and counts
    trails, names = trails_of(3, 40, same_memories=True)                                 # each names m0..m39
    bulk = bulk_use(trails, names=names)
    assert decide_bulk(s, bulk, legacy=counting, group=False).allowed
    assert {calls[(m, "recall")] for m in memories(40)} == {1}
    assert all(calls[(t, "route")] == 1 for t in trails)


def test_u22_grouping_changes_no_decision():
    w = andy_world()
    w.allow(HOME, audience=["self"], actions=["recall", "read"], memories=[M1, M2])
    w.allow(HOME, audience=["self"], actions=["recall"], lanes=["work"])
    w.lane(M3, "work", T("2026-11-01"))
    w.deny(HOME, audience=["self"], memories=[M2], actions=["read"], valid_from=T("2026-11-20"))
    w.collect("collection:andy/medical-history", [M2])
    s = w.state()
    objs = memories(6) + (M1, M2, M3)
    for action in ("recall", "read"):
        bulk = bulk_use(objs, action=action, named=True)
        a, b = decide_bulk(s, bulk), decide_bulk(s, bulk, group=False)
        assert a == b, action


def test_u22_decide_bulk_agrees_with_per_object_decide_on_what_it_allows():
    s = trail_world(blocked=C)
    for objs in ([A, B], [A, C], [B, A]):
        bulk = bulk_use(objs, action="recall", named=True)
        assert decide_bulk(s, bulk).allowed == all(decide(s, home_use(o, bulk.at, action="recall")).allowed
                                                   for o in objs)


# ---------------------------------------------------------------- the imprints spec (I 8, XM1)

AGENT = "agent:station-imprints"
PEER = "imprint:peer-1/"
CALIB, TRAILEV = "calibration", "trail-evaluation"
CEILING_C = {("recall", CALIB), ("read", CALIB), ("imprint", CALIB), ("recall", TRAILEV), ("read", TRAILEV),
             ("imprint", TRAILEV), ("route", TRAILEV)}


def imprint_fixture(owners=("sam", "andy"), operator="andy"):
    """Two imprints with route, sam's c0a8 and Andy's own d1e2 (Andy is the operator), and a sam imprint e3f4 of the
    same store without route. The ceiling is I 8's five items, written out from the spec."""
    assert operator == "andy"
    w = andy_world()
    w.person("sam")
    w.store("SAM", owner="person:sam", place="place:home/sam")
    w.store("ANDY", owner="person:andy", place=HOME)
    for imprint, source in (("c0a8", "SAM"), ("d1e2", "ANDY"), ("e3f4", "SAM")):
        w.store(imprint, owner="person:andy", place=HOME, imprint_of=source)
    w.agent("station-imprints", HOME, at=HOME)
    end = T("2026-12-31")
    imprints = {
        # copy: objects(I), R(I) with the memories each names, r_M's and r_T's (actions, purposes), end, withdrawn
        "c0a8": dict(owner="sam", objects=tuple(f"mem:SAM/episode/m{i}" for i in (1, 2, 3)),
                     derived={"road:SAM/r1": ("mem:SAM/episode/m1", "mem:SAM/episode/m2"),
                              "trail:SAM/t1": tuple(f"mem:SAM/episode/m{i}" for i in (1, 2, 3))},
                     r_M=(("recall", "read", "imprint"), (CALIB, TRAILEV)),
                     r_T=(("recall", "read", "imprint", "route"), (TRAILEV,)), end=end, withdrawn=None),
        "d1e2": dict(owner="andy", objects=("mem:ANDY/episode/m1", "mem:ANDY/episode/m2"), derived={},
                     r_M=(("recall", "read", "imprint"), (CALIB, TRAILEV)), r_T=None, end=end,
                     withdrawn=T("2026-11-10")),
        "e3f4": dict(owner="sam", objects=("mem:SAM/episode/m1", "mem:SAM/episode/m2"), derived={},
                     r_M=(("recall", "read", "imprint"), (CALIB, TRAILEV)), r_T=None, end=end, withdrawn=None),
    }
    # sam's records (the owner's home layer at the station): copy c0a8's r_M and r_T; Andy's records add nothing
    w.collect("collection:sam/imprint-c0a8", imprints["c0a8"]["objects"])
    for rt, (kinds, coll) in {"r_M": (["memory"], ["collection:sam/imprint-c0a8"]),
                              "r_T": (["road", "trail"], "*")}.items():
        actions, purposes = imprints["c0a8"][rt]
        w.allow("place:home/sam", audience=[HOME], requesters=[AGENT], stores=["SAM"], kinds=kinds,
                collections=coll, actions=list(actions), purposes=list(purposes), valid_until=end)

    def ceiling(sub, action) -> str:
        """I 8, items 1 to 5, for the uses of every copy at the station."""
        imp = imprints.get(sub.copy.rpartition("/")[2])
        if sub.requester != AGENT or sub.place != HOME or imp is None:                          # item 1
            return "silent"
        x, p, t = action, sub.purpose, sub.at
        in_m = sub.obj in imp["objects"] and imp["r_M"] and x in imp["r_M"][0] and p in imp["r_M"][1]
        in_t = (sub.obj in imp["derived"] and imp["r_T"] and x in imp["r_T"][0] and p in imp["r_T"][1])
        if not (in_m or in_t):                                                                  # item 2
            return "silent"
        if (x, p) not in CEILING_C:                                                             # item 3
            return "silent"
        if not (T("2026-11-01") <= t < imp["end"]):                                              # item 4
            return "silent"
        if imp["withdrawn"] is not None and t >= imp["withdrawn"]:                              # item 5
            return "silent"
        return "allow"

    def bulk(copy, objs, action, purpose, *, named, at="2026-11-02", names=lambda o: ()):
        return bulk_use(objs, action=action, purpose=purpose, copy=PEER + copy, named=named, at=T(at),
                        requester=AGENT, place=HOME, names=names)

    c, d, e = imprints["c0a8"], imprints["d1e2"], imprints["e3f4"]
    derived = tuple(c["derived"])
    dnames = c["derived"].__getitem__
    uses = [
        # Need(admission) for c0a8 with route
        (bulk("c0a8", c["objects"], "imprint", CALIB, named=True), True),
        (bulk("c0a8", derived, "imprint", TRAILEV, named=False, names=dnames), True),
        (bulk("c0a8", c["objects"], "read", TRAILEV, named=True), True),
        # Need(trail-evaluation)
        (bulk("c0a8", derived, "route", TRAILEV, named=False, names=dnames), True),
        # outside r_M's, r_T's or the ceiling's terms
        (bulk("c0a8", c["objects"], "route", TRAILEV, named=True), False),              # r_M lists no route
        (bulk("c0a8", derived, "imprint", CALIB, named=False, names=dnames), False),    # r_T has no calibration
        (bulk("c0a8", derived, "read", CALIB, named=False, names=dnames), False),
        (bulk("c0a8", ("mem:SAM/episode/m9",), "recall", CALIB, named=True), False),    # not in objects(I)
        (bulk("c0a8", c["objects"], "imprint", "research", named=True), False),         # not in C
        # the same store's later copy without route: R(I) is empty, so the ceiling refuses (RS2)
        (bulk("e3f4", derived, "route", TRAILEV, named=False, names=dnames), False),
        (bulk("e3f4", e["objects"], "imprint", CALIB, named=True), True),
        # the dates (items 4 and 5)
        (bulk("c0a8", c["objects"], "imprint", CALIB, named=True, at="2026-10-31"), False),
        (bulk("c0a8", c["objects"], "imprint", CALIB, named=True, at="2026-12-31"), False),
        (bulk("c0a8", c["objects"], "imprint", CALIB, named=True, at="2026-12-30"), True),
        # Andy's own imprint: the operator's home is the ceiling itself and his records add nothing
        (bulk("d1e2", d["objects"], "imprint", CALIB, named=True), True),
        (bulk("d1e2", d["objects"], "read", TRAILEV, named=True), True),
        (bulk("d1e2", d["objects"], "route", TRAILEV, named=True), False),
        (bulk("d1e2", d["objects"], "imprint", CALIB, named=True, at="2026-11-12"), False),   # withdrawn
        # a copy the station does not hold
        (bulk("zzzz", c["objects"], "imprint", CALIB, named=True), False),
    ]
    return w.state(), ceiling, uses


def test_u22_imprints_spec_need_agrees():
    # I 8's Need(trail-evaluation) and Need(admission), with h = imprint:<peer>/<id>, requester
    # agent:station-imprints acting for the operator in place:home/andy. Two owners: sam's imprint c0a8 and Andy's
    # own (Andy is the operator, XM1). The operator's home layer is passed as `outside`, the ceiling ⟦c⟧ of I 8,
    # written in the test from I 8's items 1 to 5.
    s, ceiling, uses_and_expected = imprint_fixture(owners=("sam", "andy"), operator="andy")
    for bulk, expected in uses_and_expected:
        assert decide_bulk(s, bulk, outside={"place:home/andy": ceiling}).allowed is expected, bulk


def test_u22_a_memory_that_is_both_an_object_and_named_is_decided_once():
    s, calls = trail_world(), collections.Counter()
    counting = [LegacyLayer("count", lambda u, x: calls.update([(u.obj, x)]) is None)]
    m0, m1 = memories(2)
    bulk = bulk_use([m0, "trail:S/t1", m1], action="read", names=lambda o: (m0, m1) if o.startswith("trail") else (),
                    named=True)
    assert decide_bulk(s, bulk, legacy=counting).allowed
    assert calls[(m0, "recall")] == calls[(m1, "recall")] == calls[(m0, "read")] == 1


def test_a_bulk_use_is_decided_on_a_ledger_that_holds_grants():
    from tests.permissions_support import one_grant_backed_record
    s, u = one_grant_backed_record()
    assert decide_bulk(s, bulk_use([u(T("2026-11-02")).obj], action="recall", named=True)).allowed
