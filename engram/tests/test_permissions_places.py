import random

import pytest
from permissions import (MAX_PLACES, RuleError, State, ancestors, check_new_parent, check_new_place,
                         dominators, place_retired)
from tests.permissions_support import SEED, T, World, random_dag_and_new_edge


def county():
    w = World()
    w.place("place:la-county", name="LA County")
    w.place("place:la-county/public-health", name="Public Health")
    w.place("place:la-county/parks-and-rec", name="Parks and Recreation")
    w.place("place:la-county/public-health/clinic-3")
    w.place("place:la-county/summer-wellness", parents=["place:la-county/public-health",
                                                       "place:la-county/parks-and-rec"])
    return w


def test_t_converts_to_utc_seconds():
    assert T("1970-01-02") == 86400
    assert T("2026-12-15T00:00:00Z") - T("2026-12-14") == 86400


def test_u2_joint_place_dominance():
    s = county().state()
    assert dominators(s, "place:la-county/summer-wellness") == {"place:la-county/summer-wellness", "place:la-county"}
    assert "place:la-county/parks-and-rec" in ancestors(s, "place:la-county/summer-wellness")
    assert dominators(s, "place:home/andy") == {"place:home/andy"}
    assert dominators(s, "place:la-county/public-health/clinic-3") == {
        "place:la-county/public-health/clinic-3", "place:la-county/public-health", "place:la-county"}


def test_u2_name_rule_cycles_roots_and_bounds():
    s = county().state()
    with pytest.raises(RuleError, match="4.2"):
        check_new_place(s, "place:la-county/x/y", [])            # prefix not registered
    with pytest.raises(RuleError, match="P26"):
        check_new_parent(s, "place:home/andy", "place:la-county")               # a root stays a root
    with pytest.raises(RuleError, match="cycle"):
        check_new_parent(s, "place:la-county/public-health", "place:la-county/public-health/clinic-3")
    w = county()
    for i in range(5):
        w.place(f"place:la-county/p{i}")
    with pytest.raises(RuleError, match="4 parents"):
        check_new_place(w.state(), "place:la-county/j", [f"place:la-county/p{i}" for i in range(5)])
    # depth: at most 16 ancestors, the place itself included (P 4.2)
    w = county()
    for i in range(12):
        w.place(f"place:la-county/p{i:02d}")
    for j, parents in enumerate([(0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 11), (8, 9, 10)]):
        w.place(f"place:la-county/j{j}", parents=[f"place:la-county/p{i:02d}" for i in parents])
    s = w.state()
    assert len(ancestors(s, "place:la-county/j0")) == 6                   # j0, p00 to p03, la-county
    k16 = ["place:la-county/j0", "place:la-county/j1", "place:la-county/j3"]   # 1 + 3 + 8 + 3 + 1 = 16
    assert check_new_place(s, "place:la-county/k16", k16) == tuple(k16)
    with pytest.raises(RuleError, match="16 ancestors"):                  # 1 + 3 + 12 + 1 = 17
        check_new_place(s, "place:la-county/k17", ["place:la-county/j0", "place:la-county/j1", "place:la-county/j2"])
    w.place("place:la-county/k16", parents=k16)
    with pytest.raises(RuleError, match="16 ancestors"):                  # k16, below j3, would reach 17
        check_new_parent(w.state(), "place:la-county/j3", "place:la-county/p11")
    # count: at most 1,024 places per ledger, homes included (P 4.4)
    w = county()
    while len(w.places()) < MAX_PLACES - 1:
        w.place(f"place:la-county/q{len(w.places()):04d}")
    check_new_place(w.state(), "place:la-county/the-1024th", [])
    w.place("place:la-county/the-1024th")
    assert len(w.places()) == MAX_PLACES
    with pytest.raises(RuleError, match="1,024 places"):
        check_new_place(w.state(), "place:la-county/the-1025th", [])


def test_u2_default_parent_is_the_prefix_and_refusals():
    s = county().state()
    assert check_new_place(s, "place:la-county/public-health/clinic-9", []) == ("place:la-county/public-health",)
    assert check_new_place(s, "place:other", []) == ()
    with pytest.raises(RuleError, match="already registered"):
        check_new_place(s, "place:la-county", [])
    with pytest.raises(RuleError, match="P26"):
        check_new_place(s, "place:other", ["place:la-county"])
    with pytest.raises(RuleError, match="4.2"):                           # unregistered parent
        check_new_place(s, "place:la-county/z", ["place:la-county/nope"])
    with pytest.raises(RuleError, match="4.2"):                           # prefix must dominate
        check_new_place(s, "place:la-county/public-health/z", ["place:la-county/parks-and-rec"])
    w = county(); w.retire_place("place:la-county/public-health")
    with pytest.raises(RuleError, match="retired"):
        check_new_place(w.state(), "place:la-county/public-health/clinic-9", [])
    with pytest.raises(RuleError, match="already a parent"):
        check_new_parent(s, "place:la-county/summer-wellness", "place:la-county/parks-and-rec")
    check_new_parent(s, "place:la-county/public-health/clinic-3", "place:la-county/parks-and-rec")


def test_u2_home_reserved():
    s = county().state()
    for bad in ["place:home/bob", "place:home/andy", "place:home/andy/den", "place:home"]:
        with pytest.raises(RuleError):
            check_new_place(s, bad, [])
    with pytest.raises(RuleError, match="P26"):
        check_new_place(s, "place:home/bob", ["place:la-county"])
    # a person's home, with the person registered and the home not yet, is allowed
    t = s.to_tables()
    t["persons"].append(dict(id="person:bob", home="place:home/bob", is_admin=0, created_seq=1))
    s2 = State.from_tables(t, seq=s.seq, seq_at=s.seq_at, meta=s.meta)
    assert check_new_place(s2, "place:home/bob", []) == ()


def test_u2_retiring_a_place_stops_its_sub_places():
    w = county(); w.retire_place("place:la-county/public-health")
    assert place_retired(w.state(), "place:la-county/public-health/clinic-3")
    assert not place_retired(w.state(), "place:la-county/parks-and-rec")


def test_pt4_dominance_never_grows():
    for case in range(500):   # random DAGs of up to 12 places
        rng = random.Random(f"{SEED}-pt4d-{case}")
        w, place, parent = random_dag_and_new_edge(rng)
        s0 = w.state()
        w.add_parent(place, parent)
        s1 = w.state()
        for p in w.places():
            assert dominators(s1, p) <= dominators(s0, p), (SEED, case, p)
            assert ancestors(s1, p) >= ancestors(s0, p), (SEED, case, p)


def test_state_tables_round_trip():
    w = county()
    w.person("jenn")
    w.agent("rio-grande", "person:andy", at="place:home/andy")
    w.store("S", place="place:home/andy")
    w.group("g", "person:andy", ["agent:rio-grande"])
    w.collect("collection:andy/medical-history", ["mem:S/episode/m1"])
    w.subject("mem:S/episode/m1", "person:jenn")
    w.copy("mem:T/episode/m1", "mem:S/episode/m1")
    w.lane("mem:S/episode/m1", "work", T("2026-11-01"))
    rid = w.allow("place:home/andy", lanes=["work"], actions=["recall"])
    w.deny("place:home/andy")
    w.revoke(rid)
    w.grant("person:andy", "agent:rio-grande", "place:home/andy")
    s = w.state()
    s2 = State.from_tables(s.to_tables(), seq=s.seq, seq_at=s.seq_at, meta=s.meta, names=s.names)
    assert s2 == s
    assert s.names["place:la-county/public-health"] == "Public Health"
    assert s.names["place:la-county/summer-wellness"] == "summer-wellness"
    assert isinstance(s.places["place:home/andy"].pseudonym_salt, bytes)
    assert s.records[rid].revoked_seq is not None and s.records[rid].selector.lanes == ("work",)
    assert s.copies == {"mem:T/episode/m1": "mem:S/episode/m1"}
    # hex salts are accepted
    t = s.to_tables()
    t["places"][0]["pseudonym_salt"] = t["places"][0]["pseudonym_salt"].hex()
    assert State.from_tables(t, seq=s.seq, seq_at=s.seq_at, meta=s.meta, names=s.names) == s


def test_state_reads_rows_against_its_seq():
    w = World()
    w.place("place:la-county")
    seq0 = w.seq
    rid = w.allow("place:home/andy")
    w.tick(60)
    w.revoke(rid)
    w.remove_steward("place:home/andy", "andy")
    w.place("place:la-county/late")
    t, at = w.state().to_tables(), dict(w.seq_at)
    early = State.from_tables(t, seq=seq0, seq_at=at, meta=w.meta)
    assert "place:la-county/late" not in early.places and rid not in early.records
    mid = State.from_tables(t, seq=seq0 + 1, seq_at=at, meta=w.meta)
    assert mid.records[rid].revoked is None and mid.records[rid].revoked_seq is None
    assert mid.place_stewards["place:home/andy"][0].removed_seq is None
    full = w.state()
    assert full.records[rid].revoked_seq is not None
    assert full.seq_at[full.records[rid].revoked_seq] == w.start + 60
    # equal states stay equal whatever the cache holds
    a, b = w.state(), w.state()
    dominators(a, "place:la-county/late")
    assert a == b


def test_world_fills_what_the_ledger_fills():
    w = county()
    s = w.state()
    assert s.places["place:la-county"].is_root == 1
    assert [r.parent for r in s.place_parents["place:la-county/public-health"]] == ["place:la-county"]
    assert [r.person for r in s.place_stewards["place:home/andy"]] == ["person:andy"]
    assert s.persons["person:andy"].home == "place:home/andy"
    assert s.places["place:la-county"].pseudonym_salt == county().state().places["place:la-county"].pseudonym_salt
