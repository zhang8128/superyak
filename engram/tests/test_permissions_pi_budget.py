"""U24, the Pi budget (Task 31, revision 8; P 6.4, 12.2, 15): the five timed budgets, and each operation's peak
resident memory in a fresh process of its own. Runs only on the station's Raspberry Pi 5, with ENGRAM_PI_BUDGET=1."""
import os
import time

import pytest

from permissions import BulkUse, decide_bulk, eligible_set
from tests.permissions_support import (AGENT, BULK_BUDGET_S, COPY, PLACE, REBUILD_BUDGET_S, REBUILD_LEDGER_S,
                                       REBUILD_WORST_S, T, derived_trails, generated_world, touches)

pytestmark = pytest.mark.skipif(os.environ.get("ENGRAM_PI_BUDGET") != "1",
                                reason="U24 runs on the station's Raspberry Pi 5 with ENGRAM_PI_BUDGET=1")


def test_u24_one_eligible_set_rebuild_within_2_seconds():
    s, placements = generated_world(placements=20_000, layers=43, records_per_layer=256)
    start = time.perf_counter()
    got = eligible_set(s, placements, requester=AGENT, place=PLACE, purpose="care-coordination", action="recall",
                       at=T("2026-11-02"))
    took = time.perf_counter() - start
    assert len(got.memory_ids) == 20_000        # every placement is allowed, so none stops early
    assert took <= REBUILD_BUDGET_S, f"{took:.1f} s for 20,000 placements"


def test_u24_one_eligible_set_rebuild_with_sharing_off_within_30_seconds(monkeypatch):
    """No two objects read alike (`SHARED_DECISIONS = 0`, 6.4): 820,000 layer verdicts."""
    import permissions
    monkeypatch.setattr(permissions, "SHARED_DECISIONS", 0)
    s, placements = generated_world(placements=20_000, layers=43, records_per_layer=256)
    start = time.perf_counter()
    got = eligible_set(s, placements, requester=AGENT, place=PLACE, purpose="care-coordination", action="recall",
                       at=T("2026-11-02"))
    took = time.perf_counter() - start
    assert len(got.memory_ids) == 20_000
    assert took <= REBUILD_WORST_S, f"{took:.1f} s for 20,000 placements with no sharing"


def test_u24_explain_on_the_largest_bulk_imprint_within_300_seconds():
    s = generated_world(placements=0, layers=43, records_per_layer=256, universe=100_000, trails=100_000)[0]
    bulk = BulkUse(requester=AGENT, place=PLACE, objects=derived_trails(100_000), copy=COPY, action="imprint",
                   purpose="trail-evaluation", at=T("2026-11-02"), named=False,
                   names=lambda trail: touches(trail, 512, universe=100_000))   # 51.2 million reads (XN3)
    start = time.perf_counter()
    d = decide_bulk(s, bulk, group=False)                                     # objects that don't group (R22)
    took = time.perf_counter() - start
    assert d.allowed, d.refusal                 # a refusal at the first trail would time nothing
    assert took <= BULK_BUDGET_S, f"{took:.1f} s"


# ---------------------------------------------------------------- memory: each operation in a process of its own

import json
import shutil
from pathlib import Path

from permissions import MAX_RECORDS
from tests.permissions_budget_core import PEAK_LIMIT_KB
from tests.permissions_budget_ledger import ensure_reference, prepare, run_probe

# Spec 15's budget for each, in MB at the reference ledger and at the bounds (the table's last two columns).
BUDGET_MB = {"state": (131.8, 171.2), "eligible": (126.8, 150.0), "bulk": (164.1, 187.3), "perform-allow": (190.2, 213.4),
             "perform-collect": (190.2, 213.4), "rebuild": (69.9, 69.9), "check": (183.0, 206.2),
             "uses-owner": (118.6, 141.8), "uses-place": (118.6, 141.8), "fold": (38.2, 38.2),
             "daemon": (409.1, 471.7), "daemon-at-the-bounds": (409.1, 471.7), "migrate": (None, None)}


@pytest.fixture(scope="session")
def reference(tmp_path_factory):
    """The reference ledger and its files, in ENGRAM_PI_BUDGET_DIR when that is set (kept between runs), else
    under pytest's base directory."""
    given = os.environ.get("ENGRAM_PI_BUDGET_DIR")
    base = Path(given) if given else tmp_path_factory.mktemp("pi-budget")
    base.mkdir(parents=True, exist_ok=True)
    return ensure_reference(base)


def record_peak(base, name, got):
    line = {"op": name, "peak_kb": got["peak_kb"], "seconds": got["seconds"], "detail": got["detail"],
            "spec_mb": BUDGET_MB.get(name)}
    with open(Path(base) / "peaks.jsonl", "a") as f:
        f.write(json.dumps(line, sort_keys=True) + "\n")
    print(f"U24 peak {name}: {got['peak_kb'] / 1024:.1f} MB (spec {BUDGET_MB.get(name)}) in {got['seconds']} s")


def measure(reference, op, name=None, **given):
    home, extra = prepare(reference, op, **given)
    try:
        got = run_probe(op, home, extra)
    finally:
        if home.parent.name == "work":
            shutil.rmtree(home, ignore_errors=True)
    record_peak(reference, name or op, got)
    assert got["peak_kb"] < PEAK_LIMIT_KB, f"{name or op} peaked at {got['peak_kb']} kB, over {PEAK_LIMIT_KB}"
    return got


@pytest.mark.parametrize("op", ["state", "eligible", "bulk", "perform-allow", "perform-collect", "rebuild", "check",
                                "uses-owner", "uses-place", "fold", "migrate"])
def test_u24_peak_memory_stays_under_512_mb(reference, op):
    got = measure(reference, op)
    d = got["detail"]
    if op == "eligible":       # timed from opening the ledger, its State and the imports included (15)
        assert d["eligible"] == d["placements"]
        assert got["seconds"] <= REBUILD_LEDGER_S, f"{got['seconds']} s on the reference ledger"
    if op == "bulk":
        assert d["allowed"], d["refusal"]
        assert got["seconds"] <= BULK_BUDGET_S, f"{got['seconds']} s on the reference ledger"
    if op.startswith("perform"):
        assert d["status"] == "done"
    if op == "fold":
        assert d["folded"] == 100_000
    if op == "migrate":
        assert d["exit"] == 0


@pytest.mark.parametrize("revoked", [0, MAX_RECORDS - 10_498])
def test_u24_the_daemon_peaks_under_512_mb(reference, revoked):
    """Three threads serve recall and read frames for a house of 20,000 of the ledger's memories from 24 keys
    (8 receivers x 3 purposes), builds in the background; the entries added pass 96 MB in all and the cache evicts,
    so it ran at its bound. Once on the reference ledger, once with revoked records up to the records bound."""
    got = measure(reference, "daemon", "daemon-at-the-bounds" if revoked else "daemon", revoked=revoked)
    d = got["detail"]
    assert not d["errors"] and d["frames"] == 24
    assert d["cache_bytes"] > 0.8 * d["cache_limit"], d
    assert d["added_bytes"] > d["cache_limit"] and d["evicted"] > 0, d
