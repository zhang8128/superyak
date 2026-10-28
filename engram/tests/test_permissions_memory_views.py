"""SH-8: the receipt views read only the rows and subjects they show (P 9.2, 9.3, 15)."""
import gc
import hashlib
import json
import tracemalloc

from permission_uses import UseRow, Uses
from permissions import USE_LIST_ROWS
from tests.permissions_support import CLINIC_3, HOME, T, andy_world

MB = 1 << 20
LEDGER = "ledger-test"
AGENT = "agent:ph-coordinator"


def _row(at, **kw):
    fields = dict(at=at, ledger_id=LEDGER, ledger_seq=1, agent=AGENT, place=CLINIC_3, acting_for=HOME,
                  action="recall", purpose="care-coordination", allowed=1, cited="[]", copy="store:house")
    return UseRow(**{**fields, **kw})


def _peak(fn):
    gc.collect()
    tracemalloc.start()
    try:
        out = fn()
        gc.collect()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return out, peak


def test_agent_view_stops_at_its_rows(tmp_path):
    uses = Uses.open(tmp_path)
    at = T("2026-11-02")
    refs = json.dumps([f"mem:S/episode/m{i}" for i in range(5000)])
    for n in range(20):
        uses.append(_row(at + n, returned=refs, filtered=0), [])
    out, peak = _peak(lambda: uses.agent_view(AGENT))
    assert len(out) == USE_LIST_ROWS
    assert peak < 4 * MB, f"peak {peak / MB:.1f} MB"


def test_views_read_only_the_subjects_they_show(tmp_path):
    uses = Uses.open(tmp_path)
    w = andy_world()
    w.place(CLINIC_3)
    state = w.state()
    at = T("2026-11-02")
    objects = [f"mem:S/episode/m{i}" for i in range(512)]
    returned = json.dumps({"count": 512, "sha256": hashlib.sha256("\n".join(objects).encode()).hexdigest()})
    pairs = [(f"person:p{s}", o) for o in objects for s in range(8)]
    for n in range(200):
        uses.append(_row(at + n, action="route", returned=returned), pairs)
    assert uses.conn.execute("SELECT COUNT(*) FROM use_subjects").fetchone()[0] == 819_200
    owner, peak = _peak(lambda: uses.owner_list(state))
    assert len(owner.rows) == USE_LIST_ROWS and peak < 24 * MB, f"owner {peak / MB:.1f} MB"
    view, peak = _peak(lambda: uses.place_view(state, CLINIC_3))
    assert len(view.rows) == USE_LIST_ROWS and peak < 24 * MB, f"place {peak / MB:.1f} MB"
