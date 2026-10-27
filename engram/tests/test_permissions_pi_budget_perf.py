"""Tasks P1 to P4's timed budgets (perf-design.md section 8): runs only on the station's Raspberry Pi 5, with
ENGRAM_PI_BUDGET=1. Each later perf task adds its own."""
import os
import time

import pytest

from permissions import BulkUse, decide_bulk, eligible_set
from tests.permissions_support import AGENT, COPY, PLACE, T, derived_trails, generated_world, touches

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
