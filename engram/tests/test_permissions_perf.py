"""Tasks P1 and P2 (perf-design.md 2.A, 2.B). P1 (2.A): what does not depend on the object is made once per State, not once per
decision. Counts the work an eligible set of 200 does on the generated world; the decisions themselves are
guarded by the all-fields reference test."""
import sys
from array import array

import pytest

import permissions
import tests.permissions_reference as ref
from permissions import Use, decide, eligible_set
from tests.permissions_support import (AGENT, COPY, LEGACY_LAYERS, M1, PLACE, T, World, andy_world, generated_world,
                                       home_use, _self_allow)

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


# -- Task P2 (perf-design.md 2.B, 2.E): a decision matches only the records that can match its object


def _use(obj, at="2026-11-02", **kw):
    return Use(requester=AGENT, place=PLACE, obj=obj, copy=COPY, action="recall", purpose="care-coordination",
               at=T(at), **kw)


def _count_full_tests(monkeypatch):
    calls = []
    for name in ("record_matches", "_matches_prefiltered"):
        real = getattr(permissions, name, None)
        if real is not None:
            monkeypatch.setattr(permissions, name, lambda *a, _r=real, **k: calls.append(1) or _r(*a, **k))
    return calls


def test_a_decision_runs_at_most_12_full_record_tests_a_layer(monkeypatch):
    s, placements = generated_world(placements=8, layers=43, records_per_layer=RECORDS_PER_LAYER)
    calls = _count_full_tests(monkeypatch)
    d = decide(s, _use(placements[0].obj), legacy=LEGACY_LAYERS)
    assert d.allowed, d.refusal
    assert len(calls) <= LEDGER_LAYERS * 12, f"{len(calls)} full record tests, not about 400 (1,288 before)"


@pytest.mark.parametrize("obj", ["garbage", "mem:S", "road:", 7, None, "mem:S/episode/ghost0-0x"])
def test_a_malformed_object_raises_or_is_refused_as_before(obj):
    s, _ = generated_world(placements=2, layers=43, records_per_layer=RECORDS_PER_LAYER)

    def run(fn):
        try:
            d = fn(s, _use(obj), legacy=LEGACY_LAYERS)
            return d.to_json(), dict(d.versions), d.processed, d.failed_need
        except Exception as e:
            return type(e).__name__, str(e)
    assert run(decide) == run(ref.decide)


@pytest.mark.parametrize("obj", ["garbage", 7, None, "mem:S"])
@pytest.mark.parametrize("silent", [False, True])
def test_a_malformed_object_is_tested_against_every_record_of_a_layer_as_before(obj, silent, monkeypatch):
    """The layer verdict and the silent code, called as `decide` calls them once a layer is reached: the index
    keeps every record for an object it cannot parse, so the same record tests run and the same one raises."""
    s, _ = generated_world(placements=2, layers=43, records_per_layer=RECORDS_PER_LAYER)
    layer = permissions.Layer(next(iter(s.places)), "consent")
    calls, ref_calls = _count_full_tests(monkeypatch), []
    real_ref = ref.record_matches
    monkeypatch.setattr(ref, "record_matches", lambda *a, **k: ref_calls.append(1) or real_ref(*a, **k))
    live_fn, old_fn = ((permissions._silent_code, ref._silent_code) if silent
                       else (permissions._ledger_verdict, ref._ledger_verdict))
    out = []
    for fn, seen in ((live_fn, calls), (old_fn, ref_calls)):
        try:
            got = fn(s, layer, _use(obj), "recall")
        except Exception as e:
            got = (type(e).__name__, str(e))
        out.append((got, len(seen) if not silent else 0))
    assert out[0] == out[1], out
    if not silent:
        assert out[0][1] >= 1


def _dated_world():
    w = andy_world()
    revoked = _self_allow(w)
    w.revoke(revoked)
    ended = _self_allow(w, valid_until=T("2026-11-10"))
    future = _self_allow(w, valid_from=T("2026-12-01"))
    return w, revoked, ended, future


def test_a_revoked_record_and_one_outside_its_interval_never_match_but_the_codes_still_see_them():
    w, revoked, ended, future = _dated_world()
    s = w.state()
    u = home_use(M1, T("2026-11-20"))
    for rid in (revoked, ended, future):
        assert not permissions._matches_prefiltered(s, s.records[rid], u, "recall")
    got = decide(s, u)
    assert not got.allowed and got.refusal.code == "EXPIRED"
    assert got.to_json() == ref.decide(s, u).to_json()


def test_not_yet_and_no_allow_codes_with_dead_records_only():
    w = andy_world()
    _self_allow(w, valid_from=T("2026-12-01"))
    s = w.state()
    assert decide(s, home_use(M1, T("2026-11-20"))).refusal.code == "NOT_YET"
    w = andy_world()
    w.revoke(_self_allow(w))
    s = w.state()
    assert decide(s, home_use(M1, T("2026-11-20"))).refusal.code == "NO_ALLOW"


def test_the_memory_index_lists_every_ref_record_pair_revoked_ones_included_sorted():
    w = andy_world()
    a = _self_allow(w, memories=["mem:S/episode/b", "mem:S/episode/a"])
    b = _self_allow(w, memories=["mem:S/episode/c", "mem:S/episode/a"])
    w.revoke(b)
    w.allow("place:home/andy", audience=["self"], collections=["collection:andy/medical-history"])
    s = w.state()
    refs, positions, listing = permissions._memory_index(s)
    assert isinstance(refs, list) and isinstance(positions, array) and positions.typecode == "I"
    assert list(refs) == sorted(refs)
    pairs = sorted((refs[i], listing[positions[i]].id) for i in range(len(refs)))
    assert pairs == sorted([("mem:S/episode/a", a), ("mem:S/episode/b", a), ("mem:S/episode/a", b),
                            ("mem:S/episode/c", b)])
    assert permissions._listing(s, "mem:S/episode/a") == {"place:home/andy": {a, b}}
    assert permissions._listing(s, "mem:S/episode/zzz") == {}


def test_the_listing_is_kept_for_the_last_object_only():
    w = andy_world()
    _self_allow(w, memories=["mem:S/episode/a", "mem:S/episode/b"])
    s = w.state()
    permissions._listing(s, "mem:S/episode/a")
    permissions._listing(s, "mem:S/episode/b")
    assert [k for k in s._cache if k[0] == "listing"] == [("listing",)]
    assert s._cache[("listing",)][0] == "mem:S/episode/b"
