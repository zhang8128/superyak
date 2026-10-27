"""Tasks P1 to P4's timed budgets (perf-design.md section 8): runs only on the station's Raspberry Pi 5, with
ENGRAM_PI_BUDGET=1. Each later perf task adds its own."""
import os
import time

import pytest

from permissions import BulkUse, decide_bulk, eligible_set
from tests.permissions_support import AGENT, COPY, PLACE, T, derived_trails, generated_world, step1_world, touches

pytestmark = pytest.mark.skipif(os.environ.get("ENGRAM_PI_BUDGET") != "1",
                                reason="the perf budgets run on the station's Raspberry Pi 5 with ENGRAM_PI_BUDGET=1")

P1_ELIGIBLE_1000_S = 15.0          # 1.5x the prototype's 9.9 s after change A (base: 27.6 s)

P2_ELIGIBLE_1000_S = 3.5           # 1.5x the prototype's 2.33 s after the candidate index (B: 1.77 ms a placement)
P2_BULK_300X8_S = 4.5              # the prototype's 2.9 s, 1.5x (base: 21.3 s)

P3_ELIGIBLE_1000_S = 2.0           # 1.5x the prototype's 1.34 s with programs
P3_BULK_1000X8_S = 7.5             # the prototype's 5.0 s, 1.5x (base: 6.6 s after B)

P4_BULK_1000X512_S = 8.0           # bulk 1,000 trails x 512 touches, universe 4,096 (the full U24 bulk: 300 s)


def test_p1_eligible_set_of_1000_within_15_seconds():
    s, placements = generated_world(placements=1_000, layers=43, records_per_layer=256)
    start = time.perf_counter()
    got = eligible_set(s, placements, requester=AGENT, place=PLACE, purpose="care-coordination", action="recall",
                       at=T("2026-11-02"))
    took = time.perf_counter() - start
    assert len(got.memory_ids) == 1_000
    assert took <= P1_ELIGIBLE_1000_S, f"{took:.1f} s for 1,000 placements"


def test_p2_eligible_set_of_1000_within_3_5_seconds():
    s, placements = generated_world(placements=1_000, layers=43, records_per_layer=256)
    start = time.perf_counter()
    got = eligible_set(s, placements, requester=AGENT, place=PLACE, purpose="care-coordination", action="recall",
                       at=T("2026-11-02"))
    took = time.perf_counter() - start
    assert len(got.memory_ids) == 1_000
    assert took <= P2_ELIGIBLE_1000_S, f"{took:.1f} s for 1,000 placements"


def test_p2_bulk_300_trails_of_8_touches_within_4_5_seconds():
    s = generated_world(placements=0, layers=43, records_per_layer=256, universe=4_096, trails=300)[0]
    bulk = BulkUse(requester=AGENT, place=PLACE, objects=derived_trails(300), copy=COPY, action="imprint",
                   purpose="trail-evaluation", at=T("2026-11-02"), named=False,
                   names=lambda trail: touches(trail, 8, universe=4_096))
    start = time.perf_counter()
    d = decide_bulk(s, bulk, group=False)
    took = time.perf_counter() - start
    assert d.allowed, d.refusal
    assert took <= P2_BULK_300X8_S, f"{took:.1f} s for 300 trails"


def test_p3_eligible_set_of_1000_within_2_seconds():
    s, placements = generated_world(placements=1_000, layers=43, records_per_layer=256)
    start = time.perf_counter()
    got = eligible_set(s, placements, requester=AGENT, place=PLACE, purpose="care-coordination", action="recall",
                       at=T("2026-11-02"))
    took = time.perf_counter() - start
    assert len(got.memory_ids) == 1_000
    assert took <= P3_ELIGIBLE_1000_S, f"{took:.1f} s for 1,000 placements"


def test_p3_bulk_1000_trails_of_8_touches_within_7_5_seconds():
    s = generated_world(placements=0, layers=43, records_per_layer=256, universe=4_096, trails=1_000)[0]
    bulk = BulkUse(requester=AGENT, place=PLACE, objects=derived_trails(1_000), copy=COPY, action="imprint",
                   purpose="trail-evaluation", at=T("2026-11-02"), named=False,
                   names=lambda trail: touches(trail, 8, universe=4_096))
    start = time.perf_counter()
    d = decide_bulk(s, bulk, group=False)
    took = time.perf_counter() - start
    assert d.allowed, d.refusal
    assert took <= P3_BULK_1000X8_S, f"{took:.1f} s for 1,000 trails"


def test_p4_bulk_1000_trails_of_512_touches_within_8_seconds():
    s = generated_world(placements=0, layers=43, records_per_layer=256, universe=4_096, trails=1_000)[0]
    bulk = BulkUse(requester=AGENT, place=PLACE, objects=derived_trails(1_000), copy=COPY, action="imprint",
                   purpose="trail-evaluation", at=T("2026-11-02"), named=False,
                   names=lambda trail: touches(trail, 512, universe=4_096))
    start = time.perf_counter()
    d = decide_bulk(s, bulk, group=False)
    took = time.perf_counter() - start
    assert d.allowed, d.refusal
    assert took <= P4_BULK_1000X512_S, f"{took:.1f} s for 1,000 trails of 512 touches"


# ---------------------------------------------------------------- P6: Andy's step-1 world

P6_STEP1_REBUILD_S = 3.0           # 1.5x the prototype's 2.0 s a rebuild of 20,000 placements (base: 2.5 s)


def test_p6_andy_step_1_rebuilds_20000_placements_within_3_seconds():
    from permissions import Placement
    w, _, placed = step1_world(memories=30_000, placements=20_000)
    state = w.state()
    placements = [Placement(f"id{i}", r, "store:HOUSE") for i, r in enumerate(placed)]
    kw = dict(requester="agent:rcv0", place="place:home/andy", purpose="session-recall", action="recall",
              at=T("2026-11-02"))
    eligible_set(state, placements, **kw)               # warms the State's own caches, as the daemon's first build does
    start = time.perf_counter()
    got = eligible_set(state, placements, **kw)
    took = time.perf_counter() - start
    assert len(got.memory_ids) > 0
    assert took <= P6_STEP1_REBUILD_S, f"{took:.1f} s for 20,000 placements"


# ---------------------------------------------------------------- P5: the lazy State, on the reference ledger

P5_BULK_2000_S = 140.0             # reference-ledger probe, bulk 2,000 trails x 512 touches, State read lazily
P5_ELIGIBLE_20000_S = 32.0         # reference-ledger probe, eligible set 20,000 (sharing off: none exists yet)


@pytest.fixture(scope="module")
def reference(tmp_path_factory):
    from pathlib import Path

    from tests.permissions_budget_ledger import ensure_reference
    given = os.environ.get("ENGRAM_PI_BUDGET_DIR")
    base = Path(given) if given else tmp_path_factory.mktemp("pi-budget-p5")
    base.mkdir(parents=True, exist_ok=True)
    return ensure_reference(base)


def test_p5_probe_bulk_2000_trails_within_140_seconds(reference):
    from tests.permissions_budget_ledger import prepare, run_probe
    home, extra = prepare(reference, "bulk", trails=2_000)
    got = run_probe("bulk", home, extra)
    assert got["detail"]["allowed"], got["detail"]["refusal"]
    assert got["seconds"] <= P5_BULK_2000_S, f"{got['seconds']} s for 2,000 trails"


def test_p5_probe_eligible_set_of_20000_within_32_seconds(reference):
    from tests.permissions_budget_ledger import prepare, run_probe
    home, extra = prepare(reference, "eligible")
    got = run_probe("eligible", home, extra)
    assert got["detail"]["eligible"] == got["detail"]["placements"] == 20_000
    assert got["seconds"] <= P5_ELIGIBLE_20000_S, f"{got['seconds']} s for 20,000 placements"
