"""Task P1's timed budget (perf-design.md section 8): runs only on the station's Raspberry Pi 5, with
ENGRAM_PI_BUDGET=1. Each later perf task adds its own."""
import os
import time

import pytest

from permissions import eligible_set
from tests.permissions_support import AGENT, PLACE, T, generated_world

pytestmark = pytest.mark.skipif(os.environ.get("ENGRAM_PI_BUDGET") != "1",
                                reason="the perf budgets run on the station's Raspberry Pi 5 with ENGRAM_PI_BUDGET=1")

P1_ELIGIBLE_1000_S = 15.0          # 1.5x the prototype's 9.9 s after change A (base: 27.6 s)


def test_p1_eligible_set_of_1000_within_15_seconds():
    s, placements = generated_world(placements=1_000, layers=43, records_per_layer=256)
    start = time.perf_counter()
    got = eligible_set(s, placements, requester=AGENT, place=PLACE, purpose="care-coordination", action="recall",
                       at=T("2026-11-02"))
    took = time.perf_counter() - start
    assert len(got.memory_ids) == 1_000
    assert took <= P1_ELIGIBLE_1000_S, f"{took:.1f} s for 1,000 placements"
