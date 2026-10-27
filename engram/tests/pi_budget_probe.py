"""One operation of U24's memory checks, run in a process of its own (Task 31; spec 15).

    python -m tests.pi_budget_probe OP HOME [--placements N] [--trails N] [--universe N] [--tail N] ...

Prints one JSON line: the operation, its seconds and the process's peak resident memory, `VmHWM` in
/proc/self/status, in kB, with `VmSwap` beside it: VmHWM counts only resident pages, so a run whose pages went to
swap could understate its peak (the final review's M10). It imports nothing from pytest, so the peak is the code
under test and its data.
The operations: state, eligible, bulk, perform-allow, perform-collect, rebuild, check, uses-owner, uses-place,
fold, daemon, migrate."""
import argparse
import collections
import contextlib
import io
import json
import os
import sys
import threading
import time
from pathlib import Path

from tests.permissions_budget_core import (AGENT, ALL, COPY, HOME, LEFT, OWNER, PLACE, budget_refs, derived_trails,
                                           touches)

NOW = 1_793_577_600            # 2026-11-02, the day the budget decisions are made
OPS = ("state", "eligible", "bulk", "perform-allow", "perform-collect", "rebuild", "check", "uses-owner",
       "uses-place", "fold", "daemon", "migrate")
CONTEXT = {"id": "memory/technical", "path": ["memory", "technical"]}
PURPOSES = ("session-recall", "care-coordination", "trail-evaluation")


def _status_kb(key: str) -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(key + ":"):
            return int(line.split()[1])
    raise RuntimeError(f"no {key} in /proc/self/status")


def peak_kb() -> int:
    return _status_kb("VmHWM")


def swap_kb() -> int:
    """The process's memory in swap, in kB, read at exit, once the operation is done, not at the moment of the
    peak: what was in swap then may have come back in or gone further out since. So `peak_kb + swap_kb`, which
    the gated peak check counts, is a proxy for the most the run held, not a measure of it (the re-review's
    Minor 5)."""
    return _status_kb("VmSwap")


def _state(home):
    from permission_ledger import Ledger
    led = Ledger.open_read_only(Path(home))
    return led, led.state()


def op_state(home, a):
    led, state = _state(home)
    return {"seq": state.seq, "records": len(state.records)}


def op_eligible(home, a):
    from permissions import Placement, eligible_set
    led, state = _state(home)
    refs = budget_refs(a.universe)
    placements = [Placement(f"id{i}", refs[i], COPY) for i in range(a.placements)]
    got = eligible_set(state, placements, requester=AGENT, place=PLACE, purpose="care-coordination", action="recall",
                       at=NOW)
    return {"placements": a.placements, "eligible": len(got.memory_ids)}


def op_bulk(home, a):
    from permissions import BulkUse, decide_bulk
    led, state = _state(home)
    bulk = BulkUse(requester=AGENT, place=PLACE, objects=derived_trails(a.trails), copy=COPY, action="imprint",
                   purpose="trail-evaluation", at=NOW, named=False,
                   names=lambda trail: touches(trail, a.touches, universe=a.universe))
    d = decide_bulk(state, bulk, group=False)
    return {"trails": a.trails, "touches": a.touches, "allowed": d.allowed,
            "refusal": None if d.refusal is None else d.refusal.to_json()}


def op_perform_allow(home, a):
    from permission_ledger import Ledger
    from permissions import Act
    sel = json.dumps({"audience": ["commons"], "requesters": "*", "actions": ["read"], "purposes": "*",
                      "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
                                  "collections": [ALL], "memories": "*"}})
    led = Ledger.open(Path(home))
    out = led.perform(Act("allow", {"layer": LEFT, "selector": sel, "valid_from": NOW, "valid_until": None,
                                    "reason": "budget"}), actor=OWNER, channel="terminal", now=NOW)
    led.close()
    return {"status": out.status, "seq": out.seq}


def op_perform_collect(home, a):
    from permission_ledger import Ledger
    from permissions import Act
    refs = budget_refs(a.universe)[a.universe - a.tail:]
    led = Ledger.open(Path(home))
    out = led.perform(Act("collect", {"collection": ALL, "objects": refs}), actor=OWNER, channel="terminal",
                      now=NOW)
    led.close()
    return {"status": out.status, "members": len(refs)}


def _cli(argv):
    import permission_cli
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = permission_cli.main(argv)
    return {"exit": code, "lines": out.getvalue().count("\n")}


def op_rebuild(home, a):
    from permission_ledger import Ledger
    led = Ledger.open_read_only(Path(home))
    dest = Path(home).parent / ("rebuilt-" + Path(home).name)
    led.rebuild(dest)
    led.close()
    return {"rebuilt": str(dest)}


def op_check(home, a):
    return _cli(["check"])


def op_uses_owner(home, a):
    return _cli(["uses", "--json"])


def op_uses_place(home, a):
    return _cli(["uses", "--place", PLACE, "--json"])


def op_fold(home, a):
    from permission_uses import Uses
    uses = Uses.open(Path(home))
    n = uses.fold(now=int(time.time()), ledger_id="reference-ledger")     # the receipts' (permissions_budget_ledger)
    uses.close()
    return {"folded": n}


class _PerThreadStorage:
    """The house's read-only store, one connection per thread (what the frames of three threads need)."""

    def __init__(self, path):
        self._path, self._local = path, threading.local()

    def __getattr__(self, name):
        from storage import Storage
        if not hasattr(self._local, "s"):
            self._local.s = Storage.open_read_only(self._path)
        return getattr(self._local.s, name)


class _WatchedCache(collections.OrderedDict):
    """The daemon's cache, counting the estimate of every entry put in it and every entry it drops."""
    added_bytes = 0
    evicted = 0

    def __setitem__(self, key, entry):
        self.added_bytes += entry.estimate()
        super().__setitem__(key, entry)

    def popitem(self, last=True):
        self.evicted += 1
        return super().popitem(last)


class _Embeddings:
    def embed(self, texts, prefix=None):
        out = []
        for text in texts:
            vec = [0.0] * 768
            vec[sum(map(ord, text)) % 768] = 1.0
            out.append(vec)
        return out


def op_daemon(home, a):
    import uuid
    from datetime import datetime, timezone
    import lighthouse_daemon
    from lighthouse_daemon import PublisherDaemon, PublisherStore
    from lighthouse_protocol import read_frame, recall_frame
    root = Path(home)
    inst = root / ".engram" / "instances" / "why"
    pub = PublisherStore(name="why", db_path=inst / "graph.db", policy_path=inst / "lighthouse-policy.json",
                         disclosures_path=inst / "lighthouse-disclosures.db")
    daemon = PublisherDaemon({"why": pub}, root / "s.sock", _Embeddings(), engram_home=root,
                             clock=lambda: datetime.fromtimestamp(NOW, tz=timezone.utc))
    assert pub.open()
    daemon._cache = _WatchedCache()
    pub.storage = _PerThreadStorage(pub.db_path)
    keys = [(f"rcv{k}", p) for k in range(a.receivers) for p in PURPOSES]
    turns = iter(keys)
    lock = threading.Lock()
    served, errors = [0], []
    when = datetime(2026, 9, 1, tzinfo=timezone.utc).isoformat()

    def worker():
        while True:
            with lock:
                key = next(turns, None)
            if key is None:
                return
            receiver, purpose = key
            kw = dict(receiver=receiver, publisher="why", context=CONTEXT, purpose=purpose)
            try:
                r = daemon.handle_frame(recall_frame(**kw, query="m1: shared: a note", k=5, at=when))
                ids = [c["memoryId"] for c in r.get("candidates", [])]
                if r.get("kind") == "error" or "candidates" not in r:
                    errors.append(str(r)[:200])
                if ids:
                    daemon.handle_frame(read_frame(**kw, turn_id="turn-1", memory_ids=ids[:1]))
                with lock:
                    served[0] += 1
            except Exception as e:                                          # pragma: no cover
                errors.append(repr(e))

    threads = [threading.Thread(target=worker) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    held = sum(e.estimate() for e in daemon._cache.values())
    return {"frames": served[0], "rebuilds": daemon.rebuilds, "cached_entries": len(daemon._cache),
            "cache_bytes": held, "added_bytes": daemon._cache.added_bytes, "evicted": daemon._cache.evicted, "cache_limit": lighthouse_daemon.CACHE_BYTES, "errors": errors[:3]}


def op_migrate(home, a):
    import permission_cli
    os.environ["ENGRAM_HOME"] = str(home)
    permission_cli._login_name = lambda: "andy"
    permission_cli.confirm = lambda words, change: True
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = permission_cli.main(["migrate"])
    return {"exit": code, "said": out.getvalue().strip().splitlines()[-2][:120] if out.getvalue() else ""}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("op", choices=OPS)
    p.add_argument("home")
    p.add_argument("--placements", type=int, default=20_000)
    p.add_argument("--trails", type=int, default=100_000)
    p.add_argument("--touches", type=int, default=512)
    p.add_argument("--universe", type=int, default=100_000)
    p.add_argument("--tail", type=int, default=10_000)
    p.add_argument("--receivers", type=int, default=8)
    a = p.parse_args(argv)
    os.environ["ENGRAM_HOME"] = a.home
    start = time.perf_counter()
    detail = globals()["op_" + a.op.replace("-", "_")](a.home, a)
    print(json.dumps({"op": a.op, "seconds": round(time.perf_counter() - start, 2), "peak_kb": peak_kb(),
                      "swap_kb": swap_kb(), "detail": detail}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
