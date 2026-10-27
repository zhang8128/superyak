"""Task P1 (perf-design.md 2.A): what does not depend on the object is made once per State, not once per
decision. Counts the work an eligible set of 200 does on the generated world; the decisions themselves are
guarded by the all-fields reference test."""
import sys

import permissions
from permissions import eligible_set
from tests.permissions_support import AGENT, PLACE, T, generated_world

LEDGER_LAYERS = 41
RECORDS_PER_LAYER = 256


def _eligible_200():
    s, placements = generated_world(placements=200, layers=43, records_per_layer=RECORDS_PER_LAYER)
    return s, eligible_set(s, placements, requester=AGENT, place=PLACE, purpose="care-coordination",
                           action="recall", at=T("2026-11-02"))


def test_layer_versions_are_read_once_per_layer_not_once_per_decision(monkeypatch):
    real, calls = permissions._layer_version, []
    monkeypatch.setattr(permissions, "_layer_version", lambda state, layer_id: calls.append(layer_id) or real(state, layer_id))
    _, got = _eligible_200()
    assert len(got.memory_ids) == 200
    assert len(calls) == LEDGER_LAYERS, f"{len(calls)} reads of a layer's version, not {LEDGER_LAYERS}"


def test_the_horizons_layer_part_visits_each_record_once_per_t_and_layers(monkeypatch):
    real, visited = permissions._revoked, []

    def counting(state, record):
        if "_horizon" in sys._getframe(1).f_code.co_qualname:
            visited.append(record.id)
        return real(state, record)
    monkeypatch.setattr(permissions, "_revoked", counting)
    _, got = _eligible_200()
    assert len(got.memory_ids) == 200
    assert 0 < len(visited) <= LEDGER_LAYERS * RECORDS_PER_LAYER + 64, f"{len(visited)} records visited"
