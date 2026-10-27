"""The daemon shares citations, bounds its cache in bytes and decides two frames at once (SH-4; P 12.2, 15)."""
import copy as _copy
import gc
import threading
import time
import tracemalloc

import lighthouse_daemon
import permissions
from permissions import Placement, eligible_set
from tests.permissions_support import (HOME, M1, Rig, andy_world, do, raised_daemon, ANDY, T)

MB = 1 << 20
N, LAYERS = 2000, 10


def _ten_layer_world():
    """Andy's world with a chain of places under one root, an allow on each, and an agent at the bottom: a
    decision of `recall` cites ten layers, all of them allowing."""
    w = andy_world()
    w.allow(HOME, audience=["commons"], kinds=["memory"], actions=["recall"])
    w.place("place:chain", stewards=["andy"])
    w.allow("place:chain", audience=["commons"], kinds=["memory"], actions=["recall"])
    prev = "place:chain"
    for i in range(LAYERS - 3):
        p = f"place:chain/c{i}"
        w.place(p, parents=[prev], stewards=["andy"])
        w.allow(p, audience=["commons"], kinds=["memory"], actions=["recall"])
        prev = p
    w.allow("agent:deep", audience=["commons"], kinds=["memory"], actions=["recall"])
    w.agent("deep", HOME, at=prev)
    return w, prev


def _placements(n=N):
    return [Placement(f"id{i}", f"mem:S/episode/m{i}", "store:house") for i in range(n)]


def _deep_size(root):
    """Bytes of everything reachable from `root`, each object once (sys.getsizeof)."""
    import sys
    seen, stack, total = set(), [root], 0
    while stack:
        o = stack.pop()
        if id(o) in seen:
            continue
        seen.add(id(o))
        total += sys.getsizeof(o)
        if isinstance(o, dict):
            stack.extend(o.keys()); stack.extend(o.values())
        elif isinstance(o, (tuple, list, set, frozenset)):
            stack.extend(o)
        elif hasattr(o, "__dict__"):
            stack.extend(vars(o).values())
        elif hasattr(o, "__dataclass_fields__"):
            stack.extend(getattr(o, f) for f in o.__dataclass_fields__)
    return total


def _build(w, prev, n=N):
    state = w.state()
    kw = dict(requester="agent:deep", place=prev, purpose="care-coordination", action="recall", at=w.start + 10)
    eligible_set(state, _placements(n), **kw)           # warms the State's own caches
    return state, kw


def _traced_set(w, prev, n=N):
    state, kw = _build(w, prev, n)
    gc.collect()
    tracemalloc.start()
    try:
        placements = _placements(n)             # made here, as the daemon makes them: the set keeps the strings
        got = eligible_set(state, placements, **kw)
        del placements
        gc.collect()
        current, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return got, current


def test_an_eligible_set_shares_equal_citations():
    w, prev = _ten_layer_world()
    got, current = _traced_set(w, prev)
    ds = list(got.decisions.values())
    assert len(ds) == N and all(d.allowed and len(d.cited) == LAYERS for d in ds)
    assert current / N < 1000, f"{current / N:.0f} B per decision"
    first = ds[0]
    assert all(d.cited is first.cited or d.cited == first.cited for d in ds)
    assert len({id(d.cited) for d in ds}) == 1 and len({id(d.versions) for d in ds}) == 1
    assert len({id(c) for d in ds for c in d.cited}) == LAYERS


def test_the_estimate_is_near_the_measure():
    w, prev = _ten_layer_world()
    got, current = _traced_set(w, prev)
    est = lighthouse_daemon._CacheEntry(1, "l", 0, "store:house", got).estimate()
    assert 1.0 <= est / current <= 1.6, f"estimate {est}, traced {current}, ratio {est / current:.2f}"


def test_the_estimate_counts_a_decision_shared_by_objects_that_read_alike_once():
    import dataclasses
    w, prev = _ten_layer_world()
    got, _ = _traced_set(w, prev)
    keys = list(got.decisions)
    one = got.decisions[keys[0]]
    n = len(keys)
    shared = dataclasses.replace(got, decisions={k: one for k in keys})
    apart = dataclasses.replace(got, decisions={k: dataclasses.replace(one) for k in keys})
    e_shared = lighthouse_daemon._CacheEntry(1, "l", 0, "store:house", shared).estimate()
    e_apart = lighthouse_daemon._CacheEntry(1, "l", 0, "store:house", apart).estimate()
    assert n > 10 and e_apart - e_shared == (n - 1) * 169, (n, e_apart, e_shared)


def _five_agents(tmp_path, n_placements=N):
    daemon, name = raised_daemon(tmp_path, placements=n_placements)
    from permission_ledger import Ledger
    led = Ledger.open(tmp_path)
    try:
        for i in range(5):
            do(led, ANDY, "register-agent", agent=f"agent:a{i}", acts_for=HOME)
            do(led, ANDY, "put-agent", agent=f"agent:a{i}", place=HOME)
    finally:
        led.close()
    pub = daemon.publishers[name]
    return daemon, pub


def _side_for(daemon, pub, agent):
    """A real side for a recall frame, made as the daemon makes it, then asked as `agent`."""
    from lighthouse_protocol import recall_frame
    from tests.permissions_support import _daemon_frame_kwargs
    from tests.test_lighthouse_daemon import NOW
    assert pub.open()
    frame = recall_frame(**_daemon_frame_kwargs(pub.name), query="q", k=5, at=NOW)
    side, nothing = daemon._ledger_side(pub, frame, daemon._gate(), None)
    assert side is not None and not nothing
    side.agent = agent
    return side


def test_the_cache_keeps_to_its_bytes(tmp_path, monkeypatch):
    daemon, pub = _five_agents(tmp_path)
    side = _side_for(daemon, pub, "agent:a0")          # one entry's size, so the bound holds two and a half
    try:
        one = lighthouse_daemon._CacheEntry(1, "l", 0, "store:house", daemon._eligible(side)).estimate()
    finally:
        side.close()
    daemon._cache.clear()
    daemon.rebuilds = 0
    monkeypatch.setattr(lighthouse_daemon, "CACHE_BYTES", int(2.5 * one))
    for i in range(5):
        side = _side_for(daemon, pub, f"agent:a{i}")
        try:
            daemon._eligible(side)
        finally:
            side.close()
    assert daemon.rebuilds == 5
    assert 1 <= len(daemon._cache)
    total = sum(e.estimate() for e in daemon._cache.values())
    assert total <= lighthouse_daemon.CACHE_BYTES, f"{total / MB:.2f} MB kept"
    assert len(daemon._cache) < 5                            # the bound bit
    # an entry over the bound alone serves its frame and is not kept
    monkeypatch.setattr(lighthouse_daemon, "CACHE_BYTES", int(0.5 * one))
    daemon._cache.clear()
    side = _side_for(daemon, pub, "agent:a0")
    try:
        got = daemon._eligible(side)
        assert len(got.memory_ids) > 0 and not daemon._cache
        built = daemon.rebuilds
        daemon._eligible(side)
    finally:
        side.close()
    assert daemon.rebuilds == built + 1 and not daemon._cache


class _PerThreadStorage:
    """The house's read-only store, one connection per thread: the frames here run in six threads at once, and
    one sqlite connection shared by them races on its own (not what this task is about)."""

    def __init__(self, path):
        self._path, self._local = path, threading.local()

    def __getattr__(self, name):
        from storage import Storage
        if not hasattr(self._local, "s"):
            self._local.s = Storage.open_read_only(self._path)
        return getattr(self._local.s, name)


def test_at_most_two_frames_decide_at_once(tmp_path, monkeypatch):
    import permission_ledger
    daemon, name = raised_daemon(tmp_path)
    pub = daemon.publishers[name]
    assert pub.open()
    pub.storage = _PerThreadStorage(pub.db_path)
    rig = Rig(daemon, tmp_path)
    real_state, real_close = permission_ledger.Ledger.state, lighthouse_daemon._LedgerSide.close
    lock = threading.Lock()
    holding, peak = [0], [0]

    def state(self, *a, **k):
        with lock:
            holding[0] += 1
            peak[0] = max(peak[0], holding[0])
        time.sleep(0.2)
        return real_state(self, *a, **k)

    def close(self):
        if getattr(self, "_counted", True):
            self._counted = False
            with lock:
                holding[0] -= 1
        return real_close(self)

    monkeypatch.setattr(permission_ledger.Ledger, "state", state)
    monkeypatch.setattr(lighthouse_daemon._LedgerSide, "close", close)
    replies, errors = [], []

    def one():
        try:
            replies.append(rig.recall())
        except Exception as e:                                 # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=one) for _ in range(6)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert not errors and len(replies) == 6
    assert all(r.get("candidates") for r in replies), replies[0]
    assert 1 <= peak[0] <= 2, peak[0]
    assert lighthouse_daemon.FRAMES_AT_ONCE == 2 == permissions.FRAMES_AT_ONCE
