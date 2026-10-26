"""The eligible-set cache and the pieces it is built from (P 12.2, L8; Task 21)."""
import random

from permissions import Placement, Use, decide, eligible_set, meet_legacy
from tests.permissions_support import (
    M1_ID as M1, M2_ID as M2, SEED, T, Bulk, cached_daemon, cached_daemon_two_publishers,
    cached_daemon_with_allow_starting, e1_daemon_after_use_10, insert_then_delete_a_placement, random_legacy_layers,
    random_world, sample_uses, write_any_ledger_row, write_publisher_policy, write_receiver_policy,
)

M5 = "00000000-0000-0000-0000-000000000005"


def test_u9_the_cache_recomputes_on_a_new_seq_a_new_change_count_and_at_the_horizon(tmp_path):
    d, led, house = cached_daemon(tmp_path)
    d.recall(); assert d.rebuilds == 1
    d.recall(); assert d.rebuilds == 1
    write_any_ledger_row(led); d.recall(); assert d.rebuilds == 2
    insert_then_delete_a_placement(house); d.recall(); assert d.rebuilds == 3
    d.clock_to(d.cache_horizon()); d.recall(); assert d.rebuilds == 4
    # two publishers, one agent: one entry per house (R31)
    d2, (pub_a, house_a), (pub_b, house_b) = cached_daemon_two_publishers(tmp_path / "two")
    assert d2.recall_ids(pub_a) == {M1} and d2.recall_ids(pub_b) == {M5} and d2.rebuilds == 2
    assert d2.recall_ids(pub_a) == {M1} and d2.recall_ids(pub_b) == {M5} and d2.rebuilds == 2
    insert_then_delete_a_placement(house_b)
    assert d2.recall_ids(pub_a) == {M1} and d2.rebuilds == 2              # B's counter is not A's
    assert d2.recall_ids(pub_b) == {M5} and d2.rebuilds == 3


def test_e1_use_11_the_cache_entry_ends_at_its_horizon(tmp_path):
    d, ids = e1_daemon_after_use_10(tmp_path)               # no ledger write after 2026-11-20
    d.clock_to(T("2026-11-30") - 1); assert M2 in d.recall_ids()
    d.clock_to(T("2026-12-01")); assert M2 not in d.recall_ids() and M1 in d.recall_ids()


def test_rf3_cache_not_served_before_its_time(tmp_path):
    d = cached_daemon_with_allow_starting(tmp_path, T("2026-11-05"))
    d.clock_to(T("2026-11-06")); assert M1 in d.recall_ids()
    d.clock_to(T("2026-11-04")); assert M1 not in d.recall_ids()


def test_sf9_a_policy_change_between_two_cached_recalls_takes_effect_with_no_rebuild(tmp_path):
    d, led, house = cached_daemon(tmp_path)
    assert M1 in d.recall_ids() and d.rebuilds == 1
    write_publisher_policy(tmp_path, allows_recall=False)        # the legacy file changes; the ledger does not
    assert d.recall_ids() == set() and d.rebuilds == 1
    write_publisher_policy(tmp_path, allows_recall=True)
    write_receiver_policy(tmp_path, "engram", actions=("read", "inject_context"))
    assert d.recall_ids() == set() and d.rebuilds == 1
    write_receiver_policy(tmp_path, "engram")
    write_publisher_policy(tmp_path, allows_recall=True, receiver_audiences=["group:other"])   # engram:audiences
    assert M1 not in d.recall_ids() and d.rebuilds == 1          # the legacy audience check runs on every request


def test_the_cache_keeps_at_most_cache_entries_over_all_houses(tmp_path, monkeypatch):
    d, led, house = cached_daemon(tmp_path)
    monkeypatch.setattr("lighthouse_daemon.CACHE_ENTRIES", 1)
    d.recall(query="m1")
    assert len(d.daemon._cache) == 1
    d.purpose = "care-coordination"                       # another key: the first entry is let go
    d.recall(query="m1")
    assert len(d.daemon._cache) == 1 and d.rebuilds == 2


def test_a_house_without_the_change_counter_never_gets_an_entry(tmp_path):
    from tests.permissions_support import house_before_029, raised_daemon, recall
    daemon, pub = raised_daemon(tmp_path, house=house_before_029)
    daemon.handle_frame(recall(pub))
    assert len(daemon._cache) == 0 and daemon.rebuilds == 0


def _uses(rng, w, n):
    return [u for u in sample_uses(rng, w, n) if not isinstance(u, Bulk)]


def test_meet_legacy_equals_deciding_with_legacy():
    for case in range(500):
        rng = random.Random(f"{SEED}-meet-legacy-{case}")
        w = random_world(rng)
        for u in _uses(rng, w, 10):
            legacy = random_legacy_layers(rng)
            got = meet_legacy(decide(w.state(), u), u, legacy)
            assert got.to_json() == decide(w.state(), u, legacy=legacy).to_json(), (SEED, case)


def test_eligible_set_holds_each_placements_ledger_decision_and_the_earliest_horizon():
    for case in range(40):
        rng = random.Random(f"{SEED}-eligible-{case}")
        w = random_world(rng)
        uses = _uses(rng, w, 12)
        first = uses[0]
        s = w.state()
        by_obj = {u.obj: u for u in uses}
        placements = [Placement(f"m{i}", obj, by_obj[obj].copy) for i, obj in enumerate(by_obj)]
        placements.append(Placement("none", None, "store:x"))
        got = eligible_set(s, placements, requester=first.requester, place=first.place, purpose=first.purpose,
                           action=first.action, at=first.at)
        want = {p.obj: decide(s, Use(first.requester, first.place, p.obj, p.copy, first.action, first.purpose,
                                     first.at)) for p in placements if p.obj}
        assert {o: d.to_json() for o, d in got.decisions.items()} == {o: d.to_json() for o, d in want.items()}
        assert got.memory_ids == {p.memory_id for p in placements if p.obj and want[p.obj].allowed}, (SEED, case)
        horizons = [d.horizon for d in want.values() if d.horizon is not None]
        assert got.at == first.at and got.horizon == (min(horizons) if horizons else None), (SEED, case)


def test_the_prefilter_is_kept_per_layer_requester_place_purpose_time_and_action():
    rng = random.Random(f"{SEED}-prefilter")
    w = random_world(rng)
    s = w.state()
    first = _uses(rng, w, 1)[0]
    for _ in range(3):
        decide(s, first)
    kept = [k for k in s._cache if k[0] == "prefilter"]
    assert kept and all(k[2:] == (first.requester, first.place, first.purpose, first.at) + k[6:] for k in kept)
