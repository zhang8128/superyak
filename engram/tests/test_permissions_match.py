"""Task 4: audiences and matching with history (P 5.2, 5.3)."""
import random

from permissions import ACTIONS, parse_object_ref, record_candidate, record_matches
from tests.permissions_support import M1, SEED, T, county_world, home_use, use

M4 = "mem:S/episode/m4"


def test_u20_place_audience_needs_the_acts_for_place_within_the_domain():
    w = county_world()
    r1 = w.allow("place:home/andy", audience=["place:la-county/public-health"],
                 collections=["collection:andy/medical-history"], actions=["recall", "read", "inject_context"],
                 purposes=["care-coordination"], valid_from=T("2026-11-01"), valid_until=T("2027-01-31"))
    s, rec = w.state(), w.record(r1)
    ok = use("agent:ph-coordinator", "place:la-county/public-health/clinic-3", M1, at=T("2026-11-02"))
    assert record_matches(s, rec, ok, "recall")
    assert not record_matches(s, rec, use("agent:parks-planner", "place:la-county/parks-and-rec", M1,
                                          at=T("2026-11-02")), "recall")
    assert not record_matches(s, rec, use("agent:sw-helper", "place:la-county/summer-wellness", M1,
                                          at=T("2026-11-02")), "recall")


def test_u20_self_and_own_group_allows_do_not_match_outside_the_home():
    w = county_world()
    w.group("group:andys", "person:andy", ["agent:rio-grande"])
    for entry in ["self", "group:andys"]:
        rid = w.allow("place:home/andy", audience=[entry], actions=["recall"])
        assert not record_matches(w.state(), w.record(rid),
                                  use("agent:rio-grande", "place:la-county", M1, at=T("2026-11-02")), "recall")
        # the same record matches at the home, so the refusal above is the audience rule (PF21)
        assert record_matches(w.state(), w.record(rid), home_use(M1, T("2026-11-02")), "recall")


def test_u6_lanes_after_a_move():
    w = county_world(); w.lane(M1, "personal", T("2026-10-01"))
    work_allow = w.allow("place:home/andy", audience=["self"], lanes=["work"], actions=["recall"])
    w.lane(M1, "pending", T("2026-11-03")); w.lane(M1, "work", T("2026-11-03"))
    assert not record_matches(w.state(), w.record(work_allow), home_use(M1, T("2026-11-04")), "recall")
    personal_deny = w.deny("place:home/andy", audience=["self"], lanes=["personal"], actions=["recall"],
                           anchor=T("2026-10-15"))
    assert record_matches(w.state(), w.record(personal_deny), home_use(M1, T("2026-11-04")), "recall")
    # one moved from work to personal stops being covered by the work-lane allow
    w2 = county_world(); w2.lane(M1, "work", T("2026-10-01"))
    allow2 = w2.allow("place:home/andy", audience=["self"], lanes=["work"], actions=["recall"])
    assert record_matches(w2.state(), w2.record(allow2), home_use(M1, T("2026-11-02")), "recall")
    w2.lane(M1, "pending", T("2026-11-03")); w2.lane(M1, "personal", T("2026-11-03"))
    assert not record_matches(w2.state(), w2.record(allow2), home_use(M1, T("2026-11-04")), "recall")


def test_u25_pending_reads_as_neither_lane_for_an_allow_and_both_for_a_deny():
    w = county_world(); w.lane(M1, "personal", T("2026-10-01")); w.lane(M1, "pending", T("2026-11-03"))
    allows = [w.allow("place:home/andy", audience=["self"], lanes=[lane], actions=["recall"])
              for lane in ("personal", "work")]
    denies = [w.deny("place:home/andy", audience=["self"], lanes=[lane], actions=["recall"], anchor=T("2026-10-15"))
              for lane in ("personal", "work")]
    any_lane = w.allow("place:home/andy", audience=["self"], lanes="*", actions=["recall"])
    s, u = w.state(), home_use(M1, T("2026-11-04"))
    assert not any(record_matches(s, w.record(r), u, "recall") for r in allows)
    assert all(record_matches(s, w.record(r), u, "recall") for r in denies)
    assert record_matches(s, w.record(any_lane), u, "recall")


def test_u25_a_memory_with_no_note_matches_no_lane_limited_allow():
    w = county_world()
    allows = [w.allow("place:home/andy", audience=["self"], lanes=[lane], actions=["recall"])
              for lane in ("personal", "work")]
    denies = [w.deny("place:home/andy", audience=["self"], lanes=[lane], actions=["recall"], anchor=T("2026-10-15"))
              for lane in ("personal", "work")]
    s, u = w.state(), home_use(M1, T("2026-11-04"))
    assert not any(record_matches(s, w.record(r), u, "recall") for r in allows)
    assert all(record_matches(s, w.record(r), u, "recall") for r in denies)


def _under_g1():
    """m4 collected under a grant G1 whose envelope is R1's; the grantee is Rio Grande."""
    from tests.permissions_support import R1_ENVELOPE
    w = county_world()
    g1 = w.put_grant(w.grant_draft(issuer="person:andy", grantee="agent:rio-grande", layer="place:home/andy",
                                   ops={"collect", "share"}, envelope=R1_ENVELOPE, max_days=30, depth=0,
                                   hours=24 * 29))
    w.tick(86400)
    w.collect("collection:andy/medical-history", [M4], backing=f"grant:{g1.id}")
    return w, g1


def test_grant_backed_membership_counts_only_while_its_chain_is_valid_and_within_its_envelopes():
    w, g1 = _under_g1()
    allow = w.allow("place:home/andy", audience=["place:la-county/public-health"],
                    collections=["collection:andy/medical-history"], memories=[M4],
                    actions=["recall", "read", "inject_context"], purposes=["care-coordination"],
                    valid_until=None)
    deny = w.deny("place:home/andy", audience=["place:la-county/public-health"],
                  collections=["collection:andy/medical-history"], anchor=w.now)
    clinic = "place:la-county/public-health/clinic-3"

    def at(day, purpose="care-coordination"):
        return use("agent:ph-coordinator", clinic, M4, at=T(day), purpose=purpose)

    s = w.state()
    a, d = w.record(allow), w.record(deny)
    assert record_matches(s, a, at("2026-11-05"), "recall")           # G1 valid, inside its envelope
    assert not record_matches(s, a, at("2026-11-05", "research"), "recall")   # outside the envelope
    assert record_matches(s, d, at("2026-11-05", "research"), "recall")
    assert not record_matches(s, a, at("2026-12-01"), "recall")   # at G1's expiry
    assert record_matches(s, d, at("2026-12-01"), "recall")
    assert record_candidate(s, a, at("2026-12-01"), "recall")        # a candidate ignores validity
    w.revoke_grant(g1.id)
    s2 = w.state()
    assert not record_matches(s2, w.record(allow), at("2026-11-20"), "recall")
    assert record_matches(s2, w.record(deny), at("2026-11-20"), "recall")
    # a candidate ignores the grant's validity, but not the envelope
    assert record_candidate(s2, w.record(allow), at("2026-11-20"), "recall")
    assert not record_candidate(s2, w.record(allow), at("2026-11-20", "research"), "recall")


def test_removed_membership_still_counts_for_a_deny_since_its_anchor():
    coll = "collection:andy/medical-history"
    w = county_world()
    w.tick(86400 * 2)                                              # 2026-11-03
    deny = w.deny("place:home/andy", audience=["self"], collections=[coll], actions=["recall"],
                  anchor=T("2026-11-01"))
    allow = w.allow("place:home/andy", audience=["self"], collections=[coll], actions=["recall"])
    w.tick(86400 * 2)
    w.uncollect(coll, M1)                                          # removed 2026-11-05, after the anchor
    s, u = w.state(), home_use(M1, T("2026-11-10"))
    assert record_matches(s, w.record(deny), u, "recall")
    assert not record_matches(s, w.record(allow), u, "recall")
    assert not record_candidate(s, w.record(allow), u, "recall")   # a removed membership is never counted
    # nor for an allow at a time before its removal: a removed membership is never counted, at any t (Task 5B, D1)
    assert not record_matches(s, w.record(allow), home_use(M1, T("2026-11-04")), "recall")
    assert record_matches(w.state_at(17), w.record(allow), home_use(M1, T("2026-11-04")), "recall")   # before it
    # removed before the deny's anchor: it does not count
    late = w.deny("place:home/andy", audience=["self"], collections=[coll], actions=["recall"],
                  anchor=T("2026-11-08"))
    assert not record_matches(w.state(), w.record(late), u, "recall")


# ---- PT6: an independent reading of P 5.3 rules 1 to 3 (PF26), allow readings only

def _dom(state, p):
    out, parents = {p}, [r.parent for r in state.place_parents.get(p, ())]
    if parents:
        out |= set.intersection(*(_dom(state, q) for q in parents))
    return out


def _times(state, added, removed):
    lo = state.seq_at[added]
    hi = state.seq_at[removed] if removed is not None and removed <= state.seq else float("inf")
    return lo, hi


def _lane_ok(state, ref, lanes, anchor, t):
    notes = sorted(state.lane_notes.get(ref, ()), key=lambda n: (n.at, n.seq))
    if not notes:
        return False
    start = max(anchor, notes[0].at)
    if start > t:
        return False
    instants = [start] + [n.at for n in notes if start < n.at <= t]

    def lane_at(i):
        return [n for n in notes if n.at <= i][-1].lane
    return any(all(lane_at(i) == lane for i in instants) for lane in lanes)


def selector_and_interval_match(state, rec, u, x):
    """Rules 1 (the interval only), 2 and 3 of P 5.3 for a person-backed allow."""
    sel, t = rec.selector, u.at
    if t < rec.valid_from or (rec.valid_until is not None and t >= rec.valid_until):
        return False
    if sel.requesters != "*" and u.requester not in sel.requesters:
        return False
    if sel.actions != "*" and x not in sel.actions:
        return False
    if sel.purposes != "*" and u.purpose not in sel.purposes:
        return False
    agent = state.agents.get(u.requester)
    if agent is None:
        return False
    act = agent.acts_for

    def aud(v):
        if v == "commons":
            return True
        if v == "self":
            return act == rec.layer and rec.layer in _dom(state, u.place)
        if v.startswith("group:"):
            mine = [g for g in state.group_members.get(v, ()) if g.agent == u.requester]
            on = any(lo <= t < hi for lo, hi in (_times(state, g.added_seq, g.removed_seq) for g in mine))
            owner = state.groups[v].owner
            return on and state.persons[owner].home in _dom(state, u.place)
        return v in _dom(state, u.place) and v in _dom(state, act)
    if not any(aud(v) for v in sel.audience):
        return False
    ref = parse_object_ref(u.obj)
    if sel.kinds != "*" and ref.kind not in sel.kinds:
        return False
    if sel.stores != "*" and ref.instance_id not in sel.stores:
        return False
    if sel.layers != "*" and ref.layer not in sel.layers:
        return False
    if sel.memories != "*" and u.obj not in sel.memories:
        return False
    if sel.lanes != "*" and not _lane_ok(state, u.obj, sel.lanes, rec.anchor, t):
        return False
    if sel.collections != "*":
        mine = state.member_of.get(u.obj, ())
        if not any(m.collection in sel.collections
                   and _times(state, m.added_seq, m.removed_seq)[0] <= t < _times(state, m.added_seq, m.removed_seq)[1]
                   for m in mine):
            return False
    return True


def test_pt6_a_replacement_never_matches_what_its_chain_does_not():
    from tests.permissions_support import (apply_random_registry_changes, random_replacement_chain,
                                           sample_uses)
    matched = 0
    for case in range(500):
        rng = random.Random(f"{SEED}-pt6-{case}")
        w, chain = random_replacement_chain(rng)
        apply_random_registry_changes(rng, w)
        s = w.state()
        for u in sample_uses(rng, w, 40):
            for x in ACTIONS:
                if record_matches(s, w.record(chain[-1]), u, x):
                    matched += 1
                    assert all(selector_and_interval_match(s, w.record(r), u, x) for r in chain), (SEED, case)
    assert matched > 0, (SEED, "PT6 never saw a match")
