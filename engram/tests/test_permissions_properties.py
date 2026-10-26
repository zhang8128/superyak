"""Task 5A: the brute-force oracle against Task 5's hand-written cases, and the decision's property tests
(P 17: PT1, PT3, PT4, PT5, PT7, PT8; L1 to L8 of P 6.6). Every property test loops 500 cases of `random_world`
and also asserts that `decide` and the oracle agree on each sampled use."""
import random
from dataclasses import replace
from collections import Counter

from permissions import (ACTIONS, BulkUse, LegacyLayer, State, ancestors, decide, decide_bulk, dominators, subjects_of)
from tests.permissions_oracle import (
    oracle_allowed, oracle_decide, oracle_env, oracle_layer_allows, oracle_needs, oracle_record_matches, oracle_sig_minus,
    oracle_sig_plus)
from tests.permissions_support import (
    HOME, M1, M2, M3, M4, REQUIRED_FEATURES, SEED, Bulk, T, World, andy_world, co_subject_world,
    copy_in_unregistered_house, dated_deny_use, e1_after_use_7, e1_after_use_9, e1_after_use_10, e1_use_1,
    deny_naming_collection_before_its_anchor, ended_allow_use, features, future_allow_use, legacy_json, legacy_refusal_use, bulk_use, home_use, nine_subjects_use,
    no_subject_use, object_in_unregistered_store, one_grant_backed_record,
    one_ref_two_houses, placement_without_source_instance_id, random_world, retired_subject_home_use,
    revoked_grant_use, sample_uses, silent_layer_use, two_owner_imprint_use, unregistered_agent_use, use,
    use_json)

N = 500
DAY = 86400


# ---------------------------------------------------------------- the judge: decide and the oracle together

def _flat(u):
    return u.uses if isinstance(u, Bulk) else (u,)


class Judge:
    """One state, read by `decide` and by the oracle. `both` asserts they agree and returns the answer."""

    def __init__(self, state: State, legacy=()):
        self.s, self.legacy = state, tuple(legacy)
        self.tables, self.seq_at = state.to_tables(), dict(state.seq_at)

    def decide(self, u) -> bool:
        return all(decide(self.s, x, legacy=self.legacy).allowed for x in _flat(u))

    def oracle(self, u) -> bool:
        return all(oracle_allowed(self.tables, self.seq_at, use_json(x), legacy_json(self.legacy, x),
                                  seq=self.s.seq) for x in _flat(u))

    def both(self, u, ctx="") -> bool:
        """decide and the oracle agree on `allowed`, and on the refusal (code, layer, action) of each use."""
        for x in _flat(u):
            d = decide(self.s, x, legacy=self.legacy)
            got = None if d.refusal is None else (d.refusal.code, d.refusal.layer, d.refusal.action)
            want = oracle_decide(self.tables, self.seq_at, use_json(x), legacy_json(self.legacy, x),
                                 seq=self.s.seq)
            assert got == want, f"{ctx}: decide says {got}, the oracle says {want}, for {x}"
        return self.decide(u)


def _rng(name, case):
    return random.Random(f"{SEED}-{name}-{case}")


# ---------------------------------------------------------------- the oracle against Task 5's cases

def _triple(build):
    def one():
        s, u, legacy = build()
        return [(s, u, legacy)]
    one.__name__ = build.__name__
    return one


def _pair(build):
    def one():
        s, u = build()
        return [(s, u, ())]
    one.__name__ = build.__name__
    return one


def _world_pair(build):
    def one():
        w, u = build()
        return [(w.state(), u, ())]
    one.__name__ = build.__name__
    return one


def _timed(build, times, **kw):
    """A builder returning (state, u) with u(at) or u(obj, at): one triple per time."""
    def one():
        s, u = build()
        return [(s, u(at, **kw) if not isinstance(at, tuple) else u(*at, **kw), ()) for at in times]
    one.__name__ = build.__name__
    return one


def _amy(register):
    def one():
        s, u = co_subject_world(register)
        return [(s, u, ())]
    one.__name__ = f"co_subject_world_{register}"
    return one


def _two_houses():
    s, at_home, at_clinic = one_ref_two_houses()
    return [(s, at_home, ()), (s, at_clinic, ())]


def _grant_backed():
    out = []
    for kw, times in (({}, ("2026-11-02", "2026-12-20", "2027-01-05")),
                      ({"revoked_grant": True}, ("2026-11-10",)),
                      ({"valid_from": T("2026-11-05"), "valid_until": T("2026-11-20")},
                       ("2026-11-01", "2026-11-10", "2026-11-21"))):
        s, u = one_grant_backed_record(**kw)
        out += [(s, u(T(t)), ()) for t in times]
    return out


def _e1_ph(build, objs, times):
    def one():
        s, u = build()
        return [(s, u(o, T(t)), ()) for o in objs for t in times]
    one.__name__ = build.__name__
    return one


def _e1_10():
    s, read_m4 = e1_after_use_10()
    return [(s, read_m4(T(t)), ()) for t in ("2026-11-19", "2026-11-21", "2026-11-30", "2026-12-05")]


def _e1_1():
    s, u = e1_use_1()
    return [(s, u, ())]


_E1_TIMES = ("2026-11-02", "2026-11-06", "2026-11-13", "2026-12-02", "2026-12-16")
HAND_WRITTEN_CASES = [
    _triple(unregistered_agent_use), _triple(retired_subject_home_use), _triple(no_subject_use),
    _triple(nine_subjects_use), _triple(dated_deny_use), _triple(ended_allow_use), _triple(revoked_grant_use),
    _triple(future_allow_use), _triple(silent_layer_use), _triple(legacy_refusal_use),
    deny_naming_collection_before_its_anchor, _pair(object_in_unregistered_store), _pair(placement_without_source_instance_id),
    _pair(copy_in_unregistered_house), _amy(True), _amy(False), _world_pair(two_owner_imprint_use),
    _two_houses, _grant_backed, _e1_ph(e1_after_use_7, (M1, M2, M3, M4), _E1_TIMES),
    _e1_ph(e1_after_use_9, (M1, M2, M3, M4), _E1_TIMES), _e1_10, _e1_1,
]


def test_the_oracle_agrees_with_task_5s_hand_written_cases():
    allowed = refused = 0
    for build in HAND_WRITTEN_CASES:
        triples = build()
        assert triples, build.__name__
        for s, u, legacy in triples:
            d = decide(s, u, legacy=legacy)
            want = oracle_decide(s.to_tables(), dict(s.seq_at), use_json(u), legacy_json(legacy, u))
            got = None if d.refusal is None else (d.refusal.code, d.refusal.layer, d.refusal.action)
            assert got == want, build.__name__
            allowed, refused = allowed + (want is None), refused + (want is not None)
    assert allowed >= 5 and refused >= 20, (allowed, refused)       # the cases cover both answers


# ---------------------------------------------------------------- Task 5B: the oracle's findings D1 to D5, pinned

def _both_sides(s, u, legacy=(), seq=None):
    """(decide's decision, the oracle's boolean) for one use at the state s (decided as of seq)."""
    seq = s.seq if seq is None else seq
    got = oracle_allowed(s.to_tables(), dict(s.seq_at), use_json(u), legacy_json(legacy, u), seq=seq)
    return decide(s, u, legacy=legacy), got


def _d1():
    w = andy_world()
    c = "collection:andy/fresh"
    w.collect(c, [M1])
    w.allow(HOME, audience=["self"], actions=["recall"], collections=[c])
    w.now = T("2026-11-10")
    w.uncollect(c, M1)
    return w.state(), home_use(M1, T("2026-11-05"))


def _d2_deny():
    w = andy_world()
    w.allow(HOME, audience=["self"], actions=["recall"])
    w.lane(M1, "personal", T("2026-10-01"))
    w.lane(M1, "pending", T("2026-11-05"))
    w.lane(M1, "work", T("2026-11-05"))
    w.now = T("2026-11-05")
    w.deny(HOME, audience=["self"], actions=["recall"], lanes=["personal"])
    return w.state(), home_use(M1, T("2026-11-06"))


def _d2_allow():
    w = andy_world()
    w.now = T("2026-09-10")             # the allow's anchor lies before the pending note
    w.allow(HOME, audience=["self"], actions=["recall"], lanes=["work"])
    w.lane(M1, "work", T("2026-09-01"))
    w.lane(M1, "pending", T("2026-10-05"))
    w.lane(M1, "work", T("2026-10-05"))
    return w.state(), home_use(M1, T("2026-11-02"))


def _d3():
    from permissions import LegacyLayer
    w = andy_world()
    w.allow(HOME, audience=["self"], kinds=["memory", "road"], actions=["recall"])
    legacy = (LegacyLayer("publisher", lambda u, x: not u.obj.startswith("mem:")),)
    return w.state(), home_use("road:S/r1", T("2026-11-02"), names=[M1]), legacy


def _d4_state():
    w = andy_world()
    w.allow(HOME, audience=["self"], kinds=["memory", "road", "trail"], actions=["recall", "read", "imprint", "route"])
    return w.state()


def _mems(n):
    return [f"mem:S/episode/m{i}" for i in range(n)]


def test_d1_decide_refuses_a_removed_membership_for_an_allow_at_any_t():
    s, u = _d1()
    d = decide(s, u)
    assert (d.allowed, d.refusal.code) == (False, "NO_ALLOW")


def test_d1_the_oracle_refuses_a_removed_membership_for_an_allow_at_any_t():
    s, u = _d1()
    assert _both_sides(s, u)[1] is False


def test_d2_decide_keeps_a_pending_note_at_the_second_of_its_settling_note():
    d = decide(*_d2_deny())
    assert (d.allowed, d.refusal.code) == (False, "DENIED")
    d = decide(*_d2_allow())
    assert (d.allowed, d.refusal.code) == (False, "NO_ALLOW")


def test_d2_the_oracle_keeps_a_pending_note_at_the_second_of_its_settling_note():
    assert _both_sides(*_d2_deny())[1] is False
    assert _both_sides(*_d2_allow())[1] is False


def test_d3_decide_judges_a_roads_named_memories_with_their_own_legacy_actions():
    s, u, legacy = _d3()
    d = decide(s, u, legacy=legacy)
    assert (d.allowed, d.refusal.code) == (False, "LEGACY_DENY")


def test_d3_the_oracle_judges_a_roads_named_memories_with_their_own_legacy_actions():
    s, u, legacy = _d3()
    assert _both_sides(s, u, legacy)[1] is False


def test_d4_decide_bulk_waives_the_32_bound_and_applies_the_size_bounds():
    s = _d4_state()
    road = home_use("road:S/r1", T("2026-11-02"), names=_mems(33))
    assert decide_bulk(s, bulk_use(["road:S/r1"], action="route", names=lambda o: _mems(33), named=True)).allowed
    assert decide(s, road).refusal.code == "BOUND"
    imprints = [f"mem:S/episode/n{i}" for i in range(513)]
    assert decide_bulk(s, bulk_use(imprints, action="imprint", named=True)).refusal.code == "BOUND"
    assert decide_bulk(s, bulk_use(imprints, action="imprint", named=False)).allowed


def test_d4_the_oracle_waives_the_32_bound_and_applies_the_size_bounds():
    s = _d4_state()
    t, seq_at = s.to_tables(), dict(s.seq_at)
    one = use_json(home_use("road:S/r1", T("2026-11-02"), action="route", names=_mems(33)))
    assert oracle_allowed(t, seq_at, {"bulk": [one], "named": True}) is True
    assert oracle_allowed(t, seq_at, one) is False
    many = [use_json(home_use(f"mem:S/episode/n{i}", T("2026-11-02"), action="imprint")) for i in range(513)]
    assert oracle_allowed(t, seq_at, {"bulk": many, "named": True}) is False
    assert oracle_allowed(t, seq_at, {"bulk": many, "named": False}) is True


def _d5():
    w = andy_world()
    w.store("H2", owner="person:andy", place=HOME)
    w.subject(M1, "person:jenn")           # Jenn is not registered: M1 has a subject whose layer does not exist
    w.allow(HOME, audience=["self"], actions=["recall"])
    s0 = w.seq
    w.copy("mem:H2/episode/c1", M1)
    return w, s0, home_use("mem:H2/episode/c1", T("2026-11-02"))


def test_d5_decide_reads_copies_at_the_decision_seq():
    w, s0, u = _d5()
    assert decide(w.state_at(s0), u).allowed
    assert not decide(w.state(), u).allowed


def test_d5_the_oracle_cuts_copies_rows_at_the_decision_seq():
    w, s0, u = _d5()
    s = w.state()
    t, seq_at = s.to_tables(), dict(s.seq_at)
    assert [r["added_seq"] for r in t["copies"]] == [s0 + 1]     # to_tables writes the copy's own seq
    assert oracle_allowed(t, seq_at, use_json(u), seq=s0) is True
    assert oracle_allowed(t, seq_at, use_json(u), seq=s.seq) is False


def test_a_use_naming_33_allowed_memories_is_refused_with_bound():
    s = _d4_state()
    for obj, action in (("road:S/r1", "route"), ("trail:S/t1", "recall")):
        d = decide(s, home_use(obj, T("2026-11-02"), action=action, names=_mems(33)))
        assert (d.allowed, d.refusal.code) == (False, "BOUND"), obj
        assert decide(s, home_use(obj, T("2026-11-02"), action=action, names=_mems(32))).allowed or action == "route"


def test_random_world_roads_name_up_to_40_memories_and_the_bound_is_exercised():
    longest, bound_refusals = 0, Counter()
    for case in range(60):
        rng = _rng("roads40", case)
        w = random_world(rng)
        longest = max(longest, max(len(v) for v in w.cfg.roads.values()))
        j = Judge(w.state())
        for u in sample_uses(rng, w, 12):
            for x in _flat(u):
                d = decide(j.s, x)
                j.both(x, f"{case}")
                if d.refusal and d.refusal.code == "BOUND" and len(set(x.names) | set(x.shows)) > 32:
                    bound_refusals[x.obj] += 1
    assert longest == 40, longest
    assert sum(bound_refusals.values()) >= 5, bound_refusals


def test_the_agreement_tests_see_every_refusal_code_of_p_6_5():
    codes = Counter()
    for case in range(120):
        rng = _rng("codes", case)
        w = random_world(rng)
        j = Judge(w.state(), (LegacyLayer("publisher", lambda u, a: a != "imprint"),))
        for u in sample_uses(rng, w, 12):
            for x in _flat(u):
                d = decide(j.s, x, legacy=j.legacy)
                j.both(x, f"{case}")
                codes[d.refusal.code if d.refusal else "allowed"] += 1
    assert set(codes) >= {"allowed", "UNKNOWN_REQUESTER", "RETIRED", "NO_LAYER", "BOUND", "DENIED", "NO_ALLOW",
                          "LEGACY_DENY"}, codes


def test_self_in_a_restriction_layer_matches_the_agent_itself():
    w = andy_world()
    w.allow(HOME, audience=["self"], actions=["recall", "read"])
    w.deny("agent:rio-grande", audience=["self"], actions=["read"])
    s = w.state()
    j = Judge(s)
    assert j.both(home_use(M1, T("2026-11-02")))                                    # recall passes
    assert not j.both(home_use(M1, T("2026-11-02"), action="read"))
    d = decide(s, home_use(M1, T("2026-11-02"), action="read"))
    assert (d.refusal.code, d.refusal.layer, d.refusal.action) == ("DENIED", "agent:rio-grande", "read")


def _same_second(first, second, *, allow, anchor="2026-09-10"):
    """A memory whose lane is `work`, then notes `first` and `second` in the same second, in that order. An allow
    wants the lane `work` throughout; a deny refuses the lane `personal`."""
    w = andy_world()
    w.now = T(anchor)
    if allow:
        w.allow(HOME, audience=["self"], actions=["recall"], lanes=["work"])
    else:
        w.allow(HOME, audience=["self"], actions=["recall"])
        w.deny(HOME, audience=["self"], actions=["recall"], lanes=["personal"])
    w.lane(M1, "work", T("2026-09-01"))
    w.lane(M1, first, T("2026-10-05"))
    w.lane(M1, second, T("2026-10-05"))
    return w.state(), home_use(M1, T("2026-11-02"))


def test_lane_notes_of_one_second_are_all_in_force_that_second_and_a_pending_note_is_kept():
    # an allow wants `work` throughout and no pending move; a deny matches `personal` or a pending move at any time
    for first, second in (("pending", "work"), ("pending", "personal"), ("work", "pending"), ("work", "personal"),
                          ("personal", "work"), ("work", "work")):
        for allow in (True, False):
            s, u = _same_second(first, second, allow=allow)
            got = Judge(s).both(u, f"{allow} {first} {second}")
            assert got is ((first, second) == ("work", "work")), (allow, first, second)
    # an allow written in the very second of the notes: its first instant has the pending note too
    s, u = _same_second("pending", "work", allow=True, anchor="2026-10-05")
    assert Judge(s).both(u, "anchor second") is False


def _bulk_sides(j, b, named):
    """decide_bulk's and the oracle's refusal for a Bulk, read as a bulk use: roads and trails name their memories,
    and no answer is shown (a bulk use is not an answer)."""
    first = b.uses[0]
    names = {x.obj: tuple(x.names) for x in b.uses}
    bulk = BulkUse(requester=first.requester, place=first.place, objects=tuple(x.obj for x in b.uses),
                   copy=first.copy, action=first.action, purpose=first.purpose, at=first.at, named=named,
                   names=lambda o: names[o])
    d = decide_bulk(j.s, bulk, legacy=j.legacy)
    plain = [replace(x, shows=frozenset()) for x in b.uses]
    legacy = [(layer.name, {}) for layer in j.legacy]
    for x in plain:
        for (name, table), (_, one) in zip(legacy, legacy_json(j.legacy, x)):
            table.update(one)
    want = oracle_decide(j.tables, j.seq_at, {"bulk": [use_json(x) for x in plain], "named": named}, legacy,
                         seq=j.s.seq)
    return (None if d.refusal is None else (d.refusal.code, d.refusal.layer, d.refusal.action)), want


def test_decide_bulk_and_the_oracle_agree_on_bulk_uses_and_their_refusals():
    seen = Counter()
    for case in range(150):
        rng = _rng("bulk", case)
        w = random_world(rng)
        legacy = (LegacyLayer("publisher", lambda u, a: a != "imprint"),) if case % 3 == 0 else ()
        j = Judge(w.state(), legacy)
        for u in sample_uses(rng, w, 20):
            if isinstance(u, Bulk):
                got, want = _bulk_sides(j, u, named=True)
                assert got == want, f"{case}: decide_bulk says {got}, the oracle says {want}, for {u}"
                seen[got[0] if got else "allowed"] += 1
    assert seen["allowed"] > 5 and len(seen) >= 4, seen


def test_random_world_reaches_every_op_and_membership_kind():
    seen = set()
    for case in range(N):
        seen |= features(random_world(_rng("reach", case)))
    assert seen >= REQUIRED_FEATURES, REQUIRED_FEATURES - seen


# ---------------------------------------------------------------- PT1

def _restriction_deny(rng, w, agent):
    w.deny(agent, audience=["commons"], kinds=["memory"], actions=rng.sample(list(ACTIONS), rng.randint(1, 3)),
           valid_from=w.start - 30 * DAY)


def test_pt1_meet():
    flips = Counter()
    seen_allowed = 0
    for case in range(N):
        rng = _rng("pt1", case)
        w = random_world(rng)
        uses = sample_uses(rng, w, 10)
        before = Judge(w.state())
        kind = ("subject", "place", "legacy", "restriction")[case % 4]
        w2, legacy = w.fork(), ()
        if kind == "subject":
            for ref in w.cfg.subjectable:
                if rng.random() < 0.5:
                    w2.subject(ref, rng.choice(w.cfg.subject_pool))
        elif kind == "place":
            x = rng.choice(w.cfg.parented)
            w2.add_parent(x, rng.choice(w.cfg.earlier[x]))
        elif kind == "legacy":
            banned = frozenset(rng.sample(list(ACTIONS), rng.randint(1, 3)))
            legacy = (LegacyLayer("publisher", lambda u, a, b=banned: a not in b),)
        else:
            for agent in rng.sample(w.cfg.agents, rng.randint(1, 3)):
                _restriction_deny(rng, w2, agent)
        after = Judge(w2.state(), legacy)
        for u in uses:
            was = before.both(u, f"{case} before")
            now = after.both(u, f"{case} after {kind}")
            assert was or not now, (case, kind, u)
            seen_allowed += was
            flips[kind] += was and not now
    assert seen_allowed > 500, seen_allowed
    assert all(flips[k] > 0 for k in ("subject", "legacy", "restriction")), flips
    assert sum(flips.values()) > 50, flips


# ---------------------------------------------------------------- PT4

def test_pt4_nesting_allows():
    inside = around = flips = anc_checked = 0
    for case in range(N):
        rng = _rng("pt4", case)
        w = random_world(rng)
        uses = sample_uses(rng, w, 12)
        s = w.state()
        j = Judge(s)
        allow_places = [r for r in w.rows["records"] if r["effect"] == "allow"
                        and all(a.startswith("place:") for a in r["selector"].audience)]
        for u in uses:
            allowed = j.both(u, f"{case}")
            for x in _flat(u):
                uj = use_json(x)
                if allowed:       # what is allowed at P is within each ancestor's layer at P
                    for z in ancestors(s, x.place):
                        for obj, actions in oracle_needs(uj):
                            for y in actions:
                                assert oracle_layer_allows(j.tables, j.seq_at, uj, z, y, obj=obj, seq=s.seq), \
                                    (case, z, y, x)
                                anc_checked += 1
                for r in allow_places:      # an allow to place:Z reaches only where Z dominates P and act(a)
                    for y in ACTIONS:
                        if oracle_record_matches(j.tables, j.seq_at, r["id"], uj, y, seq=s.seq):
                            acts = s.agents[x.requester].acts_for
                            assert any(z in dominators(s, x.place) and z in dominators(s, acts)
                                       for z in r["selector"].audience), (case, r["id"], x)
                            inside += 1
                        elif any(z not in dominators(s, x.place) for z in r["selector"].audience):
                            around += 1
        x = rng.choice(w.cfg.parented)       # adding a parent edge to a place that has one
        w2 = w.fork()
        w2.add_parent(x, rng.choice(w.cfg.earlier[x]))
        j2 = Judge(w2.state())
        for u in sample_uses(rng, w, 10) + uses:
            was, now = j.both(u, f"{case} edge before"), j2.both(u, f"{case} edge after")
            assert was or not now, (case, x, u)
            flips += was and not now
    assert inside > 100 and around > 1000 and anc_checked > 1000 and flips > 0, (inside, around, anc_checked, flips)


# ---------------------------------------------------------------- PT5

def _unchecked_changes(rng, w):
    """Lane moves, pending notes and removals from collections, groups and places, each dated now."""
    for _ in range(rng.randint(1, 5)):
        w.tick(rng.randint(1, 6) * DAY + rng.randint(0, 3600))
        kind = rng.choice(("lane", "pending", "uncollect", "group", "leave"))
        if kind in ("lane", "pending"):
            laned = sorted({n["object"] for n in w.rows.get("lane_notes", [])})    # a first note comes before a move
            if laned:
                w.lane(rng.choice(laned), rng.choice(("personal", "work")) if kind == "lane" else "pending",
                       w.now)
        elif kind == "uncollect":
            live = [r for r in w.rows.get("collection_members", []) if r.get("removed_seq") is None]
            if live:
                w.uncollect(*(lambda r: (r["collection"], r["object"]))(rng.choice(live)))
        elif kind == "group":
            live = [r for r in w.rows.get("group_members", []) if r.get("removed_seq") is None]
            if live:
                live_row = rng.choice(live)
                live_row["removed_seq"] = w._bump()
        else:
            live = [r for r in w.rows.get("agent_places", []) if r.get("removed_seq") is None]
            if live:
                w.leave(rng.choice(live)["agent"])


def test_pt5_unchecked_changes():
    flips = 0
    for case in range(N):
        rng = _rng("pt5", case)
        w = random_world(rng)
        uses = sample_uses(rng, w, 14)
        before = Judge(w.state())
        w2 = w.fork()
        _unchecked_changes(rng, w2)
        after = Judge(w2.state())
        for u in uses:
            was, now = before.both(u, f"{case} before"), after.both(u, f"{case} after")
            assert was or not now, (case, u)
            flips += was and not now
    assert flips > 20, flips


# ---------------------------------------------------------------- PT7

def _copy_world(links: int, *, source_owner_allows: bool, late: bool = False):
    """A chain of `links` kept copies of Andy's m0 in a keeper's store; every layer but (maybe) Andy's home
    allows everything. Returns (world, [copy refs], source ref, the keeper's use of a copy)."""
    w = World()
    for handle in ("keeper", "late"):
        w.person(handle)
    clinic = "place:county/clinic"
    w.place("place:county")
    w.place(clinic, parents=["place:county"])
    w.agent("kept", clinic, at=clinic)
    w.store("S", owner="person:andy", place=HOME)
    w.store("K", owner="person:keeper", place=clinic)
    src = "mem:S/episode/m0"
    refs, prev = [], src
    for i in range(1, links + 1):
        ref = f"mem:K/episode/c{i}"
        w.copy(ref, prev)
        w.subject(ref, "person:andy")                     # carried when the copy was made (P25)
        refs.append(ref)
        prev = ref
    layers = [clinic, "place:county", "place:home/keeper"] + \
        ([HOME] if source_owner_allows else [])
    for layer in layers:
        w.allow(layer, audience=["commons"], kinds=["memory"])
        w.allow(layer, audience=["commons"], kinds=["memory"], actions=list(ACTIONS))
    w.now = T("2026-11-03")
    return w, refs, src, lambda ref, at: use("agent:kept", clinic, ref, copy="store:K", at=at)


def test_pt7_subjects():
    added = flips = 0
    for case in range(N):
        rng = _rng("pt7", case)
        w = random_world(rng)
        uses = sample_uses(rng, w, 10)
        s, before = w.state(), Judge(w.state())
        # (a) adding subjects never adds an allowed use
        w2 = w.fork()
        for ref in w.cfg.subjectable:
            if rng.random() < 0.4:
                w2.subject(ref, rng.choice(w.cfg.subject_pool))
        after = Judge(w2.state())
        for u in uses:
            was, now = before.both(u, f"{case} before"), after.both(u, f"{case} after")
            assert was or not now, (case, u)
            flips += was and not now
        # (b) a road's subjects include its endpoints'
        for road, names in w.cfg.roads.items():
            for t in (T("2026-11-02"), T("2026-12-01")):
                have = set(subjects_of(s, road, t, names))
                assert have >= set().union(*(set(subjects_of(s, m, t)) for m in names)), (case, road)
        for u in uses:
            if not isinstance(u, Bulk) and u.obj in w.cfg.roads and before.both(u):
                w3 = w.fork()
                w3.now = u.at - DAY                  # recorded before the use, so it is in force at its time
                w3.subject(rng.choice(sorted(u.names)), "person:ghost")       # no ledger layer: NO_LAYER
                assert not Judge(w3.state()).both(u, f"{case} endpoint subject"), (case, u)
                added += 1
        # (c) a kept copy carries its source's subjects
        chain = w.cfg.copy_chain
        for upper, lower in zip(chain, chain[1:]):
            for t in (T("2026-11-02"), T("2026-12-01")):
                assert set(subjects_of(s, upper, t)) >= set(subjects_of(s, lower, t)), (case, upper)
    # (c) an allow at the keeper's place alone never lets a copy out; (d) a subject added to the source later
    # refuses the copy's next use, through chains of up to 4 copies
    for links in (1, 2, 3, 4):
        w, refs, src, make = _copy_world(links, source_owner_allows=False)
        j = Judge(w.state())
        for ref in refs:
            assert not j.both(make(ref, T("2026-11-04")), f"keeper alone, {links} links"), (links, ref)
        w, refs, src, make = _copy_world(links, source_owner_allows=True)
        j = Judge(w.state())
        assert all(j.both(make(ref, T("2026-11-04"))) for ref in refs), links
        w.subject(src, "person:late")                      # the source's only; the copies are untouched
        after = Judge(w.state())
        for ref in refs:
            assert not after.both(make(ref, T("2026-11-04")), f"late subject, {links} links"), (links, ref)
    assert flips > 20 and added > 5, (flips, added)


# ---------------------------------------------------------------- PT8

def _cited_ids(s, u, legacy=()):
    out = set()
    for x in _flat(u):
        for c in decide(s, x, legacy=legacy).cited:
            out |= set(c.records)
    return out


def _end(w, r):
    """The earliest valid_until across a record and its replaces chain (None: never)."""
    by_id = {x["id"]: x for x in w.rows["records"]}
    ends, cur = [], r
    while cur is not None:
        if cur.get("valid_until") is not None:
            ends.append(cur["valid_until"])
        cur = by_id.get(cur.get("replaces"))
    return min(ends) if ends else None


def test_pt8_revocation_and_expiry():
    cited_before = cited_after = expired_checked = 0
    for case in range(N):
        rng = _rng("pt8", case)
        w = random_world(rng)
        uses = sample_uses(rng, w, 8)
        # a record revoked at seq s is never cited at s or later; it may be cited just before
        revoked = [r for r in w.rows["records"] if r.get("revoked_seq") is not None]
        for r in rng.sample(revoked, min(3, len(revoked))):
            s_rev = r["revoked_seq"]
            states = {k: w.state_at(k) for k in (s_rev - 1, s_rev, w.seq)}
            judges = {k: Judge(st) for k, st in states.items()}
            for u in uses:
                if r["id"] in _cited_ids(states[s_rev - 1], u):
                    cited_before += 1
                for k in (s_rev, w.seq):
                    assert r["id"] not in _cited_ids(states[k], u), (case, r["id"], k, u)
                    cited_after += 1
                    judges[k].both(u, f"{case} at seq {k}")
        # no use at or after valid_until is allowed by a record (nor by one it replaces, on the chain)
        s = w.state()
        j = Judge(s)
        for r in rng.sample(w.rows["records"], min(5, len(w.rows["records"]))):
            end = _end(w, r)
            if end is None:
                continue
            for u in uses:
                x = u.uses[0] if isinstance(u, Bulk) else u
                late = use(x.requester, x.place, x.obj, copy=x.copy, action=x.action, purpose=x.purpose,
                           at=max(w.cfg.t0, end + rng.randint(0, 3) * DAY), names=x.names, shows=x.shows)
                assert r["id"] not in _cited_ids(s, late), (case, r["id"], late)
                for y in ACTIONS:
                    assert not oracle_record_matches(j.tables, j.seq_at, r["id"], use_json(late), y, seq=s.seq)
                expired_checked += 1
                j.both(late, f"{case} late")
    assert cited_before > 5 and cited_after > 100 and expired_checked > 500, (cited_before, cited_after,
                                                                               expired_checked)


# ---------------------------------------------------------------- PT3

def test_pt3_delegation():
    chains = backed = member_backed = checked = 0
    for case in range(N):
        rng = _rng("pt3", case)
        w = random_world(rng)
        uses = sample_uses(rng, w, 8)
        s = w.state()
        j = Judge(s)
        chains += max(len(c) for c in w.cfg.grant_chains) if w.cfg.grant_chains else 0
        assert all(1 <= len(c) <= 3 for c in w.cfg.grant_chains), (case, w.cfg.grant_chains)
        for person in ("person:andy", "person:jenn"):
            home = w.state().persons[person].home
            for u in uses:
                for x in _flat(u):
                    uj = use_json(x)
                    for obj, actions in oracle_needs(uj):
                        for y in actions:
                            for r in w.rows["records"]:
                                if r["layer"] != home or r["effect"] != "allow" or r.get("revoked_seq") is not None:
                                    continue
                                if not oracle_record_matches(j.tables, j.seq_at, r["id"], uj, y, obj=obj,
                                                             seq=s.seq):
                                    continue
                                checked += 1
                                backed += r["backing"].startswith("grant:")
                                kw = dict(obj=obj, seq=s.seq)
                                in_sig = oracle_sig_plus(j.tables, j.seq_at, uj, y, person, **kw)
                                in_env = oracle_env(j.tables, j.seq_at, uj, y, person, anchor=r["anchor"], **kw)
                                assert in_sig or in_env, (case, r["id"], person, y, x)
                                assert not oracle_sig_minus(j.tables, j.seq_at, uj, y, person, **kw) or \
                                    not oracle_layer_allows(j.tables, j.seq_at, uj, home, y, **kw), \
                                    (case, r["id"], person, y, x)
                                member_backed += not in_sig and in_env
            for u in uses:
                j.both(u, f"{case}")
    assert chains > 400 and backed > 50 and checked > 500, (chains, backed, checked, member_backed)


# ---------------------------------------------------------------- PT12 and PT10 (Task 6)

def _shape(d):
    """What a decision says, apart from the time it was asked at and the bounds it reports."""
    return (d.allowed, d.refusal, d.cited)


def test_pt12_horizon():
    """L8: with σ fixed, decide is the same at every t' in [t, horizon); and horizon <= until."""
    bounded = unbounded = both = sampled = 0
    for case in range(N):
        rng = _rng("pt12", case)
        w = random_world(rng)
        s = w.state()
        now = s.seq_at[s.seq]       # L8 holds for a use asked after the ledger's last write
        for x in (y for u in sample_uses(rng, w, 8) for y in _flat(u)):
            x = replace(x, at=max(x.at, now))
            d = decide(s, x)
            assert d.horizon is None or d.horizon > x.at, (case, x, d.horizon)
            if d.horizon is not None and d.until is not None:
                both += 1
                assert d.horizon <= d.until, (case, x, d.horizon, d.until)
            if d.horizon is None:
                unbounded += 1
                span = [x.at, x.at + rng.randint(1, 400) * DAY]
            else:
                bounded += 1
                span = [x.at, d.horizon - 1]
            times = {span[0], span[1]} | {rng.randint(span[0], span[1]) for _ in range(8)}
            for t2 in sorted(times):
                sampled += 1
                assert _shape(decide(s, replace(x, at=t2))) == _shape(d), (case, x, t2, d.horizon)
    assert bounded > 500 and unbounded > 100 and both > 100 and sampled > 5000, (bounded, unbounded, both, sampled)


def test_pt10_determinism_by_insertion_order():
    """The same decision, cited records, until and horizon whatever order the rows were inserted in."""
    checked = 0
    for case in range(N // 5):
        rng = _rng("pt10", case)
        w = random_world(rng)
        s = w.state()
        shuffled = {t: [dict(r) for r in rs] for t, rs in w.rows.items()}
        for rows in shuffled.values():
            rng.shuffle(rows)
        s2 = State.from_tables(shuffled, seq=w.seq, seq_at=w.seq_at, meta=w.meta, names=w.names)
        for x in (y for u in sample_uses(rng, w, 8) for y in _flat(u)):
            assert decide(s, x) == decide(s2, x), (case, x)
            checked += 1
    assert checked > 300


# ---------------------------------------------------------------- Task 8: boxes and the gluing check (PT9, PT11)

import itertools

from permissions import (stewards as stewards_of, Box, FSet, TimeSet, box_and, box_contains, box_empty, box_minus, box_subset, gluing,
                         ineffective, parse_object_ref, TooComplex)
from tests.permissions_oracle import oracle_delta, oracle_ineffective
from tests.permissions_support import _COLLECTIONS, _RW_PURPOSES, e1_county_rules

_DIMS = ("place", "agent", "kind", "store", "layer", "lane", "memory", "action", "purpose")


def _random_box(rng, universe) -> Box:
    kw = {}
    for dim in _DIMS:
        values = [v for v in universe[dim] if v != "zz"]
        items = frozenset(rng.sample(values, rng.randint(0, len(values))))
        kw[dim] = FSet(items, rng.random() < 0.4)
    cuts = sorted(rng.sample(range(0, 4), rng.randint(0, 3)))
    intervals = []
    for lo, hi in zip(cuts[::2], cuts[1::2] + [None]):
        intervals.append((lo, hi))
    kw["time"] = TimeSet.of(intervals if rng.random() < 0.8 else [(0, None)])
    return Box(**kw)


def _points(universe):
    return itertools.product(*(universe[d] for d in _DIMS), universe["time"])


def test_pt9_boxes():
    rng = random.Random(SEED + 9)
    for _ in range(N):
        universe = {d: ["a", "b"][:rng.randint(0, 2)] + ["zz"] for d in _DIMS}      # "zz": no set names it
        universe["time"] = [0, 1, 2, 3]
        a, b = _random_box(rng, universe), _random_box(rng, universe)
        pts = list(_points(universe))
        in_a = {p for p in pts if box_contains(a, p)}
        in_b = {p for p in pts if box_contains(b, p)}
        both = box_and(a, b)
        assert {p for p in pts if both is not None and box_contains(both, p)} == in_a & in_b
        assert (both is None) == (not (in_a & in_b))
        pieces = box_minus(a, b)
        assert len(pieces) <= 10 and not any(box_empty(x) for x in pieces)
        seen = [{p for p in pts if box_contains(x, p)} for x in pieces]
        assert set().union(*seen) == in_a - in_b
        assert sum(len(x) for x in seen) == len(in_a - in_b)                  # disjoint
        assert box_empty(a) == (not in_a)
        assert box_subset(a, b) == (in_a <= in_b)


def _glue_points(rng, state, w, place, n):
    c = w.cfg
    objs = list(c.objects) + list(c.roads) + ["mem:W/semantic/w9"]
    agents = list(c.agents) + ["agent:zz"]
    purposes = list(_RW_PURPOSES) + ["zz-purpose"]
    stamps = {0, 1}
    for r in state.records.values():
        stamps.update(x for x in (r.valid_from, r.valid_until, r.anchor) if x is not None)
    for g in state.grants.values():
        stamps.add(g.expires)
    stamps.update(state.seq_at.values())
    times = sorted(stamps | {x - 1 for x in stamps if x > 0} | {max(stamps) + 10 ** 6})
    out = []
    for _ in range(n):
        obj = rng.choice(objs)
        ref = parse_object_ref(obj)
        notes = state.lane_notes.get(obj)
        lane = notes[-1].lane if notes else "none"
        out.append((place, rng.choice(agents), ref.kind, ref.instance_id, ref.layer or "", lane, obj,
                    rng.choice(ACTIONS), rng.choice(purposes), rng.choice(times)))
    return out


def _guided(rng, boxes, base, n):
    """Points built to lie inside a box, kept when the whole point is in it."""
    out = []
    for box in boxes:
        for pt in rng.sample(base, min(n, len(base))):
            pt = list(pt)
            for i, dim in enumerate(_DIMS):
                got = getattr(box, dim)
                if not got.co and got.items and dim in ("agent", "action", "purpose") and rng.random() < 0.8:
                    pt[i] = rng.choice(sorted(got.items))
            for lo, hi in box.time.intervals[:1]:
                if rng.random() < 0.8:
                    pt[9] = lo
            if box_contains(box, tuple(pt)):
                out.append(tuple(pt))
    return out


def test_pt11_gluing():
    rng = random.Random(SEED + 11)
    checked = {"delta": 0, "ineffective": 0, "skipped": 0}
    for _ in range(40):
        w = random_world(rng)
        state = w.state()
        tables, seq_at = state.to_tables(), state.seq_at
        for place in sorted(state.place_parents):
            glue = gluing(state, place)
            if glue.too_complex:
                checked["skipped"] += 1
                continue
            base = _glue_points(rng, state, w, place, 150)
            pts = base + _guided(rng, glue.delta[:6] + glue.ineffective[:6], base, 3)
            want_delta = oracle_delta(tables, seq_at, place, pts, seq=state.seq)
            got_delta = {p for p in pts if any(box_contains(b, p) for b in glue.delta)}
            assert got_delta == want_delta, (place, sorted(got_delta ^ want_delta)[:3])
            want_ineff = oracle_ineffective(tables, seq_at, place, pts, seq=state.seq)
            got_ineff = {p for p in pts if any(box_contains(b, p) for b in glue.ineffective)}
            assert got_ineff == want_ineff, (place, sorted(got_ineff ^ want_ineff)[:3])
            checked["delta"] += bool(want_delta)
            checked["ineffective"] += bool(want_ineff)
            alone = ineffective(state, place)
            assert alone.ineffective == glue.ineffective and alone.delta == ()
    assert checked["delta"] >= 5 and checked["ineffective"] >= 5, checked


def test_pt11_collection_fixture():
    w = World()
    w.person("st")
    for p in ("place:a", "place:b"):
        w.place(p, stewards=["st"])
    w.place("place:j", parents=["place:a", "place:b"], stewards=["st"])
    w.agent("x", "place:j", at="place:j")
    m = "mem:S/episode/m1"
    w.collect("collection:andy/c1", [m])
    w.collect("collection:andy/c2", [m])
    w.collect("collection:andy/c3", ["mem:S/episode/m9"])
    w.allow("place:j", audience=["commons"], collections=["collection:andy/c1"])
    w.allow("place:a", audience=["commons"], collections=["collection:andy/c2"])
    w.allow("place:b", audience=["commons"], collections=["collection:andy/c3"])
    s = w.state()
    r = gluing(s, "place:j")
    assert r.delta and not r.too_complex
    at = w.start + 10
    pt = ("place:j", "agent:x", "memory", "S", "episode", "none", m, "recall", "any", at)
    assert any(box_contains(b, pt) for b in r.delta)
    other = pt[:6] + ("mem:S/episode/m9",) + pt[7:]
    assert not any(box_contains(b, other) for b in r.delta)
    assert r.notify == stewards_of(s, "place:j", "place:b")


def test_9b_a_copy_keeps_its_added_seq_through_the_tables():
    w, s0, u = _d5()
    s = w.state()
    assert s.to_tables()["copies"] == [{"object": "mem:H2/episode/c1", "source": M1, "added_seq": s0 + 1}]
    again = State.from_tables(s.to_tables(), seq=s.seq, seq_at=s.seq_at, meta=s.meta, names=s.names)
    assert again == s
    earlier = State.from_tables(s.to_tables(), seq=s0, seq_at=s.seq_at, meta=s.meta, names=s.names)
    assert earlier.copies == {} and decide(earlier, u).allowed


def test_9b_a_removed_group_membership_never_counts_for_an_allow_in_decide_and_the_oracle():
    w = andy_world()
    w.group("group:g9", "person:andy", ["agent:rio-grande"])
    w.allow(HOME, audience=["group:g9"], actions=["recall"])
    w.tick(DAY)
    u = home_use(M1, w.now)
    s_before = w.state()
    w.tick(DAY)
    w._find("group_members", group_id="group:g9", agent="agent:rio-grande", removed_seq=None)["removed_seq"] = w._bump()
    for s, want in ((s_before, True), (w.state(), False)):
        j = Judge(s)
        assert j.both(u) is want


# ---------------------------------------------------------------- Task 10: the ledger file

_IDENTITY = {"persons": ("id",), "places": ("id",), "agents": ("id",), "records": ("id",),
             "permission_grants": ("id",), "place_stewards": ("place", "person", "added_seq"),
             "agent_places": ("agent", "place", "added_seq"), "group_members": ("group_id", "agent", "added_seq"),
             "collection_members": ("collection", "object", "added_seq"),
             "subjects": ("object", "subject", "added_seq")}


def _world_into_ledger(home, w):
    """Write a World's rows through Ledger._append, one log row per World seq; seq 1 is `create`'s."""
    import json
    from permission_ledger import Ledger
    from permissions import _ADDED, _UNDONE, selector_json
    led = Ledger.create(home, "andy", now=w.seq_at[1])
    ops = {s: {"insert": [], "update": []} for s in range(2, w.seq + 1)}
    for table, rows in w.rows.items():
        assert table != "proposals"
        for r in rows:
            d = dict(r)
            if table == "records":
                d["selector"] = json.loads(selector_json(d["selector"]))
            if table == "places":
                d["pseudonym_salt"] = bytes(d["pseudonym_salt"]).hex()
            added = d[_ADDED[table]]
            if added == 1:
                continue
            if table in _UNDONE:
                seq_col, clear = _UNDONE[table]
                undone = {c: d.pop(c) for c in clear if d.get(c) is not None}
                if undone:
                    where = {c: d[c] for c in _IDENTITY[table]}
                    ops[undone[seq_col]]["update"].append({"table": table, "where": where, "set": undone})
            ops[added]["insert"].append({"table": table, "row": d})
    for s in range(2, w.seq + 1):
        led._append("world", f"s{s}", "person:andy", "terminal", {k: v for k, v in ops[s].items() if v},
                    at=w.seq_at[s])
    return led


def test_pt10_determinism_after_replay(tmp_path):
    from permission_ledger import Ledger
    checked = 0
    for case in range(25):
        rng = _rng("pt10", case)
        w = random_world(rng)
        home = tmp_path / f"c{case}"
        led = _world_into_ledger(home, w)
        assert led.seq() == w.seq and led.verify() is None
        rebuilt = Ledger.open(led.rebuild(tmp_path / f"r{case}"))
        uses = sample_uses(rng, w, 6)
        for s in sorted({w.seq, *(rng.randint(1, w.seq) for _ in range(4))}):
            a, b, c = led.state(s), rebuilt.state(s), w.state_at(s)
            for u in uses:
                for x in _flat(u):
                    da, db, dc = decide(a, x), decide(b, x), decide(c, x)
                    assert da == db, (case, s, x)
                    assert da.allowed == dc.allowed, (case, s, x)
                    checked += 1
    assert checked > 500
