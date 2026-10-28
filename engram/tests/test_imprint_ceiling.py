"""Task 28: the station's per-copy check (peer ``decide_use``) agrees with the permissions spec's meet.

``ceiling_world`` builds P 5.5's tables from the fixture Task 27 wrote, and the ceiling is I 8's items 1 to 5 written
in ``imprint_support``; ``decide_bulk`` gets it as the layer kept outside a ledger for ``place:home/andy`` (P 6.1;
XM1). A case where the two packages disagree is a defect in Task 27 or its fixture, never fixed in
``permissions.py``.
"""
import json
from pathlib import Path

import pytest

from permissions import decide_bulk
from tests.imprint_support import bulk_uses_of, ceiling_world, evaluation_route_bulk, status_ok

REPO = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((REPO / "peer" / "tests" / "fixtures" / "imprints" / "ceiling_agreement.json").read_text())


@pytest.mark.parametrize("case", FIXTURE["uses"], ids=lambda c: c["name"])
def test_p_meet_over_req_gives_the_fixtures_answer(case):
    state, ceiling = ceiling_world(FIXTURE)
    bulks = bulk_uses_of(FIXTURE, case)        # Need(kind) as P's bulk uses: memories in batches of 512, R(I) counted
    allowed = status_ok(FIXTURE, case) and all(
        decide_bulk(state, b, outside={"place:home/andy": ceiling}).allowed for b in bulks)
    assert allowed is case["expected"]


def test_a_trail_of_40_touches_is_no_bound_refusal():
    state, ceiling = ceiling_world(FIXTURE)
    bulk = evaluation_route_bulk(FIXTURE, "sam-c0a8", touches=40)
    assert len(set(bulk.names(bulk.objects[0]))) == 40
    assert decide_bulk(state, bulk, outside={"place:home/andy": ceiling}).allowed
