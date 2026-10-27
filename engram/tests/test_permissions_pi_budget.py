"""U24, the Pi budget (Task 31; P 6.4, 12.2, 15): the two timed decisions, and each operation's peak resident memory
in a fresh process of its own. Runs only on the station's Raspberry Pi 5, with ENGRAM_PI_BUDGET=1."""
import os
import time

import pytest

from permissions import BulkUse, decide_bulk, eligible_set
from tests.permissions_support import (AGENT, BULK_BUDGET_S, COPY, PLACE, REBUILD_BUDGET_S, T, derived_trails,
                                       generated_world, touches)

pytestmark = pytest.mark.skipif(os.environ.get("ENGRAM_PI_BUDGET") != "1",
                                reason="U24 runs on the station's Raspberry Pi 5 with ENGRAM_PI_BUDGET=1")


def test_u24_one_eligible_set_rebuild_within_2_seconds():
    s, placements = generated_world(placements=20_000, layers=43, records_per_layer=256)
    start = time.perf_counter()
    got = eligible_set(s, placements, requester=AGENT, place=PLACE, purpose="care-coordination", action="recall",
                       at=T("2026-11-02"))
    took = time.perf_counter() - start
    assert len(got.memory_ids) == 20_000        # every placement is allowed, so none stops early
    assert took <= REBUILD_BUDGET_S


def test_u24_explain_on_the_largest_bulk_imprint_within_40_seconds():
    s = generated_world(placements=0, layers=43, records_per_layer=256, universe=100_000, trails=100_000)[0]
    bulk = BulkUse(requester=AGENT, place=PLACE, objects=derived_trails(100_000), copy=COPY, action="imprint",
                   purpose="trail-evaluation", at=T("2026-11-02"), named=False,
                   names=lambda trail: touches(trail, 512, universe=100_000))   # 51.2 million reads (XN3)
    start = time.perf_counter()
    d = decide_bulk(s, bulk, group=False)                                     # objects that don't group (R22)
    took = time.perf_counter() - start
    assert d.allowed, d.refusal                 # a refusal at the first trail would time nothing
    assert took <= BULK_BUDGET_S
