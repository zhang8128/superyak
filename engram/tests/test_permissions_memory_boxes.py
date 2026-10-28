"""The gluing check's sets share, and stop at a bound (SH-9; P 8, 15)."""
import gc
import tracemalloc

import pytest

import permissions
from permissions import FULL, FSet, disagreement_words, gluing, layer_boxes, stewards
from tests.permissions_support import HOME, World

MB = 1 << 20
COLL = "collection:andy/big"


def test_a_meet_with_everything_shares_the_set():
    s = frozenset(f"mem:S/episode/m{i}" for i in range(10))
    assert (FULL & FSet(s)).items is s
    assert (FSet(s) & FULL).items is s
    assert (FULL & FULL).items == frozenset() and (FULL & FULL).co


def test_one_record_on_a_large_collection_makes_one_set():
    w = World()
    w.collect(COLL, [f"mem:S/episode/m{i}" for i in range(100_000)])
    agents = [w.agent(f"a{i}", "person:andy", at=HOME) for i in range(32)]
    gids = []
    for i in range(32):
        gid = f"group:g{i}"
        w.group(f"g{i}", "person:andy", [agents[i]])
        gids.append(gid)
    w.allow(HOME, audience=gids, collections=[COLL], actions=["recall"])
    state = w.state()
    gc.collect()
    tracemalloc.start()
    try:
        boxes = layer_boxes(state, HOME)
        gc.collect()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(boxes) == 32
    assert len({id(b.memory.items) for b in boxes}) == 1
    assert peak < 12 * MB, f"layer_boxes peaked at {peak / MB:.1f} MB"


def _joint_world(members=2000):
    w = World()
    w.person("st")
    w.place("place:big", stewards=["st"], name="Big")
    w.place("place:big/left", stewards=["st"], name="Left")
    w.place("place:big/right", stewards=["st"], name="Right")
    joint = "place:big/both"
    w.place(joint, parents=["place:big/left", "place:big/right"], stewards=["st"], name="Both")
    w.agent("worker", joint, at=joint)
    w.collect(COLL, [f"mem:S/episode/m{i}" for i in range(members)])
    w.allow("place:big", audience=["commons"], actions=["recall"])      # a silent county layer would end the meet
    for parent in ("place:big/left", "place:big/right"):
        w.allow(parent, audience=["commons"], collections=[COLL], actions=["recall"])
    w.allow(joint, audience=["commons"], memories=["mem:S/episode/m1"], actions=["recall", "read"])
    return w.state(), joint


def test_a_check_past_its_refs_reports_could_not_check(monkeypatch):
    s, joint = _joint_world()
    assert not gluing(s, joint).too_complex
    s, joint = _joint_world()
    monkeypatch.setattr(permissions, "BOX_REFS", 1_000)
    r = gluing(s, joint)
    assert r.too_complex and r.notify
    assert disagreement_words(s, r).startswith("could not check: too complex")
    assert r.notify == stewards(s, joint, "place:big/left", "place:big/right")


def test_later_checks_dont_pay_for_freed_sets(monkeypatch):
    def passes(n):
        s, joint = _joint_world()
        monkeypatch.setattr(permissions, "BOX_REFS", n)
        return not gluing(s, joint).too_complex

    lo, hi = 0, 1_000_000
    assert passes(hi) and not passes(lo)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (lo, mid) if passes(mid) else (mid, hi)
    total = hi                       # the least bound the first run passes: what kept + check reached
    s, joint = _joint_world()
    monkeypatch.setattr(permissions, "BOX_REFS", total)
    assert not gluing(s, joint).too_complex
    assert not gluing(s, joint).too_complex      # layers' boxes come from the memo; check starts at 0 again
