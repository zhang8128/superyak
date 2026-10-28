import copy
import json
from pathlib import Path

import pytest

from superyak_peer.imprints import CEILING, UseDecision, decide_use, effective_end, need, owner_layer

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "imprints" / "ceiling_agreement.json").read_text())
PAIRS = [(i["permission"], i["receipts"]) for i in FIXTURE["imprints"].values()]


def owner_records_for(fixture, imp):
    return owner_layer([(i["permission"], i["receipts"]) for i in fixture["imprints"].values()],
                       owner_id=imp["permission"]["owner_id"])


@pytest.mark.parametrize("case", FIXTURE["uses"], ids=lambda c: c["name"])
def test_the_station_check_gives_the_fixtures_answer(case):
    imp = FIXTURE["imprints"][case["imprint"]]
    d = decide_use(imp["permission"], imp["receipts"], owner_records_for(FIXTURE, imp),
                   status=case.get("status", imp["status"]), kind=case["kind"], t=case["t"],
                   operator=FIXTURE["operator"])
    assert (d.allowed, d.term) == (case["expected"], case["expected_term"])
    assert d.code == {None: None, "valid_from": "NOT_YET", "end": "EXPIRED"}.get(case["expected_term"], "NO_ALLOW")
    assert d.valid_until == effective_end(imp["permission"], imp["receipts"])
    assert bool(d.records) == d.allowed


def one_fault_each():
    base = FIXTURE["imprints"]["andy-b2"]
    perm, t = base["permission"], base["permission"]["created"] + 3600

    def args(permission=perm, receipts=(), layer=None, **over):
        records = permission["records"] if layer is None else layer
        return {"permission": permission, "receipts": list(receipts), "owner_records": records, "status": "approved",
                "kind": "admission", "t": t, "operator": "andy", **over}

    def with_sel(**sel):
        p = copy.deepcopy(perm)
        for r in p["records"]:
            r["selector"].update(sel)
        return p

    with_extra = copy.deepcopy(perm)
    for r in with_extra["records"]:
        r["selector"]["purposes"] = sorted(r["selector"]["purposes"] + ["research"])
    only_r = [[("memory", "recall", "research")]]
    yield "status", args(status="admitted")
    yield "valid_from", args(t=perm["created"] - 1)
    yield "end", args(t=effective_end(perm, []))
    yield "withdrawal", args(receipts=[{"event": "withdrawn", "actor_id": "s-andy", "at": t, "detail": {}}])
    yield "audience", args(permission=with_sel(audience=["place:home/sam"]))
    yield "requester", args(permission=with_sel(requesters=["agent:other"]))
    yield "action", args(permission=with_sel(actions=["read", "recall"]))
    yield "purpose", args(permission=with_sel(purposes=["trail-evaluation"]))
    yield "ceiling", args(permission=with_extra, uses=only_r[0])


def test_each_term_alone_refuses_with_that_term_in_order():
    for term, broken in one_fault_each():
        d = decide_use(**broken)
        assert (d.allowed, d.term) == (False, term)
        assert d.code == {"valid_from": "NOT_YET", "end": "EXPIRED"}.get(term, "NO_ALLOW")


def test_the_first_failing_term_wins():
    # status fails together with everything after it
    terms = dict(one_fault_each())
    broken = dict(terms["audience"], status="admitted", t=terms["audience"]["t"] - 10**7)
    assert decide_use(**broken).term == "status"


def test_one_ceiling_per_copy():
    copy1, copy2 = FIXTURE["imprints"]["sam-copy-1"], FIXTURE["imprints"]["sam-copy-2"]
    layer = owner_records_for(FIXTURE, copy2)
    d = decide_use(copy2["permission"], copy2["receipts"], layer, status="admitted", kind="trail-evaluation",
                   t=FIXTURE["now"], operator="andy")
    assert (d.allowed, d.term) == (False, "ceiling")
    after_end = effective_end(copy2["permission"], copy2["receipts"]) + 1
    assert after_end < effective_end(copy1["permission"], copy1["receipts"])
    late = decide_use(copy2["permission"], copy2["receipts"], layer, status="approved", kind="admission",
                      t=after_end, operator="andy")
    assert (late.allowed, late.term) == (False, "end")


def shortenings_of(imp):
    end = effective_end(imp["permission"], imp["receipts"])
    for actor in (imp["permission"]["ship_id"], imp["permission"]["owner_id"]):
        for at in (end - 10**6, end - 10, end + 10):
            for to in (end - 1000, end, end + 10**6):
                extra = {"event": "shortened", "actor_id": actor, "at": at, "detail": {"valid_until": to}}
                yield imp["receipts"] + [extra]


def test_shortening_only_narrows():
    imp = FIXTURE["imprints"]["sam-c0a8"]
    seen = 0
    for receipts in shortenings_of(imp):
        seen += 1
        assert effective_end(imp["permission"], receipts) <= effective_end(imp["permission"], imp["receipts"])
    assert seen == 18
    assert effective_end(imp["permission"], imp["receipts"]) == imp["permission"]["created"] + 300000


def test_effective_end_is_the_earliest_of_records_and_shortenings():
    perm = FIXTURE["imprints"]["andy-a1"]["permission"]
    ends = min(r["valid_until"] for r in perm["records"])
    assert effective_end(perm, []) == ends
    cut = [{"event": "shortened", "actor_id": "s-andy", "at": 1, "detail": {"valid_until": ends - 5}}]
    assert effective_end(perm, cut) == ends - 5


def test_owner_layer_drops_owner_withdrawals_and_cuts_by_owner_shortenings():
    layer = owner_layer(PAIRS, owner_id="u-andy")
    ids = {r["id"] for r in layer}
    for name in ("andy-a1", "andy-b2"):
        assert {r["id"] for r in FIXTURE["imprints"][name]["permission"]["records"]} <= ids
    assert not ids & {r["id"] for r in FIXTURE["imprints"]["andy-gone"]["permission"]["records"]}
    assert not ids & {r["id"] for r in FIXTURE["imprints"]["sam-copy-1"]["permission"]["records"]}
    sam = owner_layer(PAIRS, owner_id="u-sam")
    by_id = {r["id"]: r for r in sam}
    c0a8 = FIXTURE["imprints"]["sam-c0a8"]
    for r in c0a8["permission"]["records"]:
        assert by_id[r["id"]]["valid_until"] == r["created"] + 300000
    # the ship's withdrawal revokes nothing of the owner's; a ship's shortening is not the owner's
    for r in FIXTURE["imprints"]["sam-copy-1"]["permission"]["records"]:
        assert by_id[r["id"]]["valid_until"] == r["valid_until"]
    # the fixture's own records are untouched
    assert c0a8["permission"]["records"][0]["valid_until"] == c0a8["permission"]["created"] + 7 * 86400


def test_need_per_use_kind():
    m = "memory"
    assert need("admission", route=False) == {(m, a, "calibration") for a in ("recall", "read", "imprint")}
    with_route = need("admission", route=True)
    assert with_route == need("admission", route=False) | {
        ("road-or-trail", a, "trail-evaluation") for a in ("recall", "read", "imprint")} | {
        (m, a, "trail-evaluation") for a in ("recall", "read")}
    assert need("trail-evaluation", route=True) == {(m, "recall", "trail-evaluation"), (m, "read", "trail-evaluation"),
                                                     ("road-or-trail", "route", "trail-evaluation")}
    for pairs in (with_route, need("trail-evaluation", route=True)):
        assert {(a, p) for _, a, p in pairs} <= CEILING
    with pytest.raises(ValueError):
        need("walk", route=False)


def test_ceiling_is_exactly_the_seven_pairs():
    assert len(CEILING) == 7 and ("route", "calibration") not in CEILING and ("route", "trail-evaluation") in CEILING


def test_the_decision_names_the_copys_own_records():
    imp = FIXTURE["imprints"]["andy-b2"]
    d = decide_use(imp["permission"], imp["receipts"], owner_records_for(FIXTURE, imp), status="approved",
                   kind="admission", t=imp["permission"]["created"] + 5, operator="andy")
    assert isinstance(d, UseDecision) and d.allowed
    assert d.records == tuple(r["id"] for r in imp["permission"]["records"])
    imp = FIXTURE["imprints"]["andy-a1"]
    d = decide_use(imp["permission"], imp["receipts"], owner_records_for(FIXTURE, imp), status="approved",
                   kind="admission", t=imp["permission"]["created"] + 5, operator="andy")
    assert d.records == (imp["permission"]["records"][0]["id"],)


def test_the_ceiling_does_not_borrow_other_operators_or_other_copies_records():
    imp = FIXTURE["imprints"]["andy-a1"]
    d = decide_use(imp["permission"], imp["receipts"], owner_records_for(FIXTURE, imp), status="approved",
                   kind="admission", t=imp["permission"]["created"] + 5, operator="sam")
    assert (d.allowed, d.term) == (False, "audience")
