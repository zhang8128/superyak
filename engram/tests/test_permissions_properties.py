"""Task 5A: the brute-force oracle against Task 5's hand-written cases, and the decision's property tests
(P 17: PT1, PT3, PT4, PT5, PT7, PT8; L1 to L8 of P 6.6). Every property test loops 500 cases of `random_world`
and also asserts that `decide` and the oracle agree on each sampled use."""
import random
from collections import Counter

from permissions import (ACTIONS, LegacyLayer, State, ancestors, decide, dominators, subjects_of)
from tests.permissions_oracle import (
    oracle_allowed, oracle_env, oracle_layer_allows, oracle_needs, oracle_record_matches, oracle_sig_minus,
    oracle_sig_plus)
from tests.permissions_support import (
    HOME, M1, M2, M3, M4, REQUIRED_FEATURES, SEED, Bulk, T, World, andy_world, co_subject_world,
    copy_in_unregistered_house, dated_deny_use, e1_after_use_7, e1_after_use_9, e1_after_use_10, e1_use_1,
    deny_naming_collection_before_its_anchor, ended_allow_use, features, future_allow_use, legacy_json, legacy_refusal_use, nine_subjects_use,
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
        d, o = self.decide(u), self.oracle(u)
        assert d is o, f"{ctx}: decide says {d}, the oracle says {o}, for {u}"
        return d


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
            got = oracle_allowed(s.to_tables(), dict(s.seq_at), use_json(u), legacy_json(legacy, u))
            assert got is decide(s, u, legacy=legacy).allowed, build.__name__
            allowed, refused = allowed + got, refused + (not got)
    assert allowed >= 5 and refused >= 20, (allowed, refused)       # the cases cover both answers


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
