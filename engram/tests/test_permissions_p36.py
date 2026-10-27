"""SH-12: P36, the owner's own copies (P 6.3; U29). Inside the owner's home, his `imprint` and every bulk use that
shows nothing to any agent read each co-subject's layer as a restriction layer, for objects in stores he owns.

Every case is also put to the oracle, which reads P36 from the spec on its own (section 17's opening)."""
import dataclasses
from types import SimpleNamespace

import pytest

import server
from permission_ledger import Ledger
from permissions import BulkUse, Refusal, State, Use, decide, decide_bulk
from tests.permissions_oracle import oracle_decide
from tests.permissions_support import (
    ALL_KINDS, ANDY, COUNTY, HOME, CLINIC_3, M3, RIO, T, andy_world, bulk_use, county_ledger, do, use, use_json,
    _doc_of)
from permissions import parse_selector

JENN_HOME = "place:home/jenn"
Q = "place:la-county/parks-and-rec"               # a place outside Andy's home, where Rio Grande also works
B = "agent:lee-helper"                            # acts for Lee, works inside Andy's home
MJ = "mem:J/episode/mj"                           # Jenn's memory, with Lee recorded on it
C3 = "mem:K/episode/c3"                           # a copy of m3 kept in Andy's store K
TRAIL = "trail:S/t1"
ANSWER = ["recall", "read", "inject_context"]
FIVE = ANSWER + ["imprint", "route"]
PURPOSE = "care-coordination"
END = T("2027-01-01")


def p36_world(jenn="empty", extra=()) -> "World":
    """m3 is about Andy and Jenn. Andy's layer allows his own agents all five actions inside his home, and holds
    the outside-home allows (commons, narrowed by requesters, with purposes and an end date) that let Rio Grande at
    Q and the agent b at his home pass his layer too, so every refusal below falls at Jenn's home."""
    w = andy_world()
    w.person("lee")
    w.agent("lee-helper", "place:home/lee", at=HOME)
    w._add("agent_places", agent=RIO, place=Q, added_seq=w._bump())
    w.store("J", owner="person:jenn", place=JENN_HOME)
    w.store("K", owner=ANDY, place=HOME)
    w.store("OUT", owner=ANDY, place=Q)
    w.subject(M3, "person:jenn")
    w.subject(MJ, "person:lee")
    w.allow(HOME, audience=["self"], kinds=ALL_KINDS, actions=FIVE)
    for who in (RIO, B):
        w.allow(HOME, audience=["commons"], requesters=[who], memories=[M3, C3, MJ], actions=ANSWER + ["imprint"],
                purposes=[PURPOSE], valid_until=END)
        w.allow(HOME, audience=["commons"], requesters=[who], kinds=["road", "trail"], stores=["S"],
                actions=["route"], purposes=[PURPOSE], valid_until=END)
    if jenn == "unregistered":
        for table, key in (("persons", "id"), ("places", "id"), ("place_stewards", "place")):
            w.rows[table] = [r for r in w.rows[table] if JENN_HOME not in (r.get("home"), r[key]) and
                             r.get("id") != "person:jenn"]
    for step in extra:
        step(w)
    return w


def _tuple(d):
    return None if d.refusal is None else (d.refusal.code, d.refusal.layer, d.refusal.action)


def judged(state: State, u):
    """decide's (or decide_bulk's) decision, after the oracle has agreed on its refusal."""
    if isinstance(u, BulkUse):
        d = decide_bulk(state, u)
        uses = [Use(requester=u.requester, place=u.place, obj=o, copy=u.copy, action=u.action, purpose=u.purpose,
                    at=u.at, names=tuple(u.names(o))) for o in u.objects]
        want = oracle_decide(state.to_tables(), dict(state.seq_at), {"bulk": [use_json(x) for x in uses],
                                                                     "named": u.named}, seq=state.seq)
    else:
        d = decide(state, u)
        want = oracle_decide(state.to_tables(), dict(state.seq_at), {**use_json(u), "keeps": u.keeps}
                             if hasattr(u, "keeps") else use_json(u), seq=state.seq)
    assert _tuple(d) == want, f"decide says {_tuple(d)}, the oracle says {want}"
    return d


def andy_allows(d):
    """His layer allows the use, so that a refusal at Jenn's home is not his layer's."""
    mine = [c for c in d.cited if c.layer == HOME]
    assert mine and all(c.verdict == "allow" for c in mine), mine


def jenn_cited(d):
    return [c for c in d.cited if c.layer == JENN_HOME]


def read_of(objs=(M3,), **kw):
    return bulk_use(objs, action="read", named=True, **kw)


def route_of(**kw):
    return bulk_use([TRAIL], action="route", named=False, names=lambda o: (M3,), **kw)


# ---------------------------------------------------------------- the qualifying uses are allowed

@pytest.mark.parametrize("jenn, verdict", [("empty", "silent"), ("unregistered", "missing")])
@pytest.mark.parametrize("make", [read_of, route_of], ids=["named-read", "counted-route"])
def test_a_qualifying_bulk_use_is_allowed_and_shows_jennas_layer_as_a_co_subject(jenn, verdict, make):
    s = p36_world(jenn).state()
    d = judged(s, make())
    assert d.allowed, d.refusal
    andy_allows(d)
    cited = jenn_cited(d)
    assert cited and all((c.kind, c.verdict, c.records) == ("co-subject", verdict, ()) for c in cited)
    assert d.versions[JENN_HOME] == (s.places[JENN_HOME].created_seq if jenn == "empty" else 0)


# ---------------------------------------------------------------- with any one condition false, as before

def _refusals(jenn):
    """(case, state, use, action it fails at): each is a use that Andy's layer allows."""
    s = p36_world(jenn).state()
    out = [("agent is b", read_of(requester=B), "recall"),
           ("P is Q", read_of(place=Q), "recall"),
           ("H outside", read_of(copy="store:OUT"), "recall"),
           ("recall", use(RIO, HOME, M3, copy="store:house", action="recall"), "recall"),
           ("read", use(RIO, HOME, M3, copy="store:house", action="read"), "recall"),
           ("inject_context", use(RIO, HOME, M3, copy="store:house", action="inject_context"), "recall"),
           ("route answer", use(RIO, HOME, TRAIL, copy="store:house", action="route", names=(M3,)), "route")]
    return [(case, s, u, x) for case, u, x in out]


@pytest.mark.parametrize("jenn, code", [("empty", "NO_ALLOW"), ("unregistered", "NO_LAYER")])
@pytest.mark.parametrize("n", range(7))
def test_with_one_condition_false_jenns_layer_is_a_consent_layer_as_before(jenn, code, n):
    case, s, u, action = _refusals(jenn)[n]
    d = judged(s, u)
    andy_allows(d)
    assert d.refusal == Refusal(code, JENN_HOME, action), case
    assert all(c.kind != "co-subject" for c in d.cited), case


@pytest.mark.parametrize("jenn, code", [("empty", "NO_ALLOW"), ("unregistered", "NO_LAYER")])
def test_a_memory_of_another_persons_store_on_his_trail_keeps_its_subjects_as_consent(jenn, code):
    s = p36_world(jenn).state()
    d = judged(s, bulk_use([TRAIL], action="route", names=lambda o: (M3, MJ)))
    andy_allows(d)
    assert d.refusal == Refusal(code, JENN_HOME, "recall")
    # the trail's own decision qualifies: the trail alone, naming only m3, is allowed
    assert judged(s, route_of()).allowed


# ---------------------------------------------------------------- the remember guard's kept store

def _imprint(keeps, copy="store:house", place=HOME):
    return Use(requester=RIO, place=place, obj=M3, copy=copy, action="imprint", purpose=PURPOSE, at=T("2026-11-02"),
               keeps=keeps)


@pytest.mark.parametrize("keeps, ok", [("store:OUT", False), ("store:K", True), ("store:NOSTORE", False), ("", False)],
                         ids=["outside-home", "at-home", "no-stores-row", "no-keeps"])
def test_the_guards_imprint_qualifies_only_when_it_keeps_inside_his_home(keeps, ok):
    s = p36_world().state()
    d = judged(s, _imprint(keeps))
    andy_allows(d)
    if ok:
        assert d.allowed and all(c.kind == "co-subject" for c in jenn_cited(d))
    else:
        assert d.refusal == Refusal("NO_ALLOW", JENN_HOME, "recall")


def test_the_guards_imprint_with_its_delivery_held_outside_his_home_is_refused():
    s = p36_world().state()
    d = judged(s, _imprint("store:K", copy="store:OUT"))
    andy_allows(d)
    assert d.refusal == Refusal("NO_ALLOW", JENN_HOME, "recall")


# ---------------------------------------------------------------- a place co-subject in anc(P)

def test_a_place_co_subject_that_is_also_in_anc_of_p_keeps_its_consent_layer():
    den = "place:home/andy/den"

    def add(w):
        w.place(den, parents=[HOME])
        w._add("agent_places", agent=RIO, place=den, added_seq=w._bump())
        w.subject(M3, den)
    s = p36_world(extra=[add]).state()
    d = judged(s, read_of(place=den))
    andy_allows(d)
    assert d.refusal == Refusal("NO_ALLOW", den, "recall")
    assert [c.kind for c in d.cited if c.layer == den] and all(c.kind == "consent" for c in d.cited if c.layer == den)


# ---------------------------------------------------------------- a deny refuses

def _deny(**kw):
    return lambda w: w.deny(JENN_HOME, audience=["commons"], kinds=ALL_KINDS, actions=FIVE, **kw)


@pytest.mark.parametrize("make, action", [(read_of, "recall"), (route_of, "route")], ids=["read", "route"])
def test_a_matching_deny_in_jenns_layer_refuses_every_qualifying_use(make, action):
    s = p36_world(extra=[_deny(valid_from=T("2026-11-01"))]).state()
    d = judged(s, make())
    andy_allows(d)
    assert d.refusal == Refusal("DENIED", JENN_HOME, action)
    assert [(c.kind, c.verdict) for c in jenn_cited(d) if c.action == action] == [("co-subject", "deny")]


def test_a_deny_that_starts_later_sets_until_and_the_horizon():
    start = T("2026-11-10")
    s = p36_world(extra=[_deny(valid_from=start)]).state()
    d = judged(s, read_of())
    assert d.allowed and d.until == start and d.horizon == start


def test_a_deny_for_other_actions_or_that_has_ended_does_not_refuse():
    s = p36_world(extra=[lambda w: w.deny(JENN_HOME, audience=["commons"], actions=["route"],
                                          valid_from=T("2026-11-01"))]).state()
    assert judged(s, read_of()).allowed


# ---------------------------------------------------------------- who is a co-subject

def test_a_self_claimed_co_subject_is_read_the_same_way():
    s = p36_world(extra=[lambda w: (w.person("amy"), w.subject(M3, "person:amy", self_claimed=True))]).state()
    d = judged(s, read_of())
    assert d.allowed and [(c.kind, c.verdict) for c in d.cited if c.layer == "place:home/amy"] == [
        ("co-subject", "silent")] * len([c for c in d.cited if c.layer == "place:home/amy"])


def _carried(w):
    w.copy(C3, M3)
    w._add("subjects", object=C3, subject="person:jenn", added_seq=w._bump(), added_by=f"copy:{M3}", self_claimed=0)


def test_a_co_subject_a_kept_copy_carries_is_read_the_same_way_and_the_copy_carries_her_after():
    s = p36_world(extra=[_carried]).state()
    d = judged(s, read_of((C3,)))
    assert d.allowed and all(c.kind == "co-subject" for c in jenn_cited(d)) and jenn_cited(d)
    # a later answer use of the copy at home, and any use of it outside the home, is refused at her home
    later = judged(s, use(RIO, HOME, C3, copy="store:K", action="recall"))
    assert later.refusal == Refusal("NO_ALLOW", JENN_HOME, "recall")
    outside = judged(s, read_of((C3,), place=Q))
    assert outside.refusal == Refusal("NO_ALLOW", JENN_HOME, "recall")


# ---------------------------------------------------------------- step 1 is unchanged

def test_a_retired_co_subjects_home_still_refuses_with_retired():
    s = p36_world(extra=[lambda w: w.retire_person("jenn")]).state()
    assert judged(s, read_of()).refusal == Refusal("RETIRED")


def test_a_ninth_subject_still_refuses_with_bound():
    def add(w):
        for i in range(8):
            w.subject(M3, f"person:p{i}")
    s = p36_world(extra=[add]).state()
    assert judged(s, read_of()).refusal == Refusal("BOUND")


# ---------------------------------------------------------------- the guard end to end

@pytest.fixture
def guard_ledger(tmp_path, monkeypatch):
    """Andy's ledger with his stores S, HOUSE and K at his home, OUT placed at clinic-3, Jenn on m3, and his own
    allows for Rio Grande to recall, read and imprint m3 inside his home. Jenn's home layer is empty."""
    from tests.permissions_support import e1_ledger_through_andys_side
    led = e1_ledger_through_andys_side(tmp_path)
    try:
        do(led, ANDY, "register-store", instance_id="OUT", name="outside", owner=ANDY, place=CLINIC_3,
           imprint_of=None)
        sel = parse_selector(_doc_of(["self"], actions=["recall", "read", "imprint"], kinds=["memory"]))
        do(led, ANDY, "allow", layer=HOME, selector=sel, valid_from=T("2026-11-01"), valid_until=T("2027-10-01"),
           reason="own copies")
    finally:
        led.close()
    monkeypatch.setattr(server, "ENGRAM_HOME", tmp_path)
    monkeypatch.setattr(server, "_agent_ref", lambda: "agent:rio-grande")
    return tmp_path


def _guard(store_id, monkeypatch):
    monkeypatch.setattr(server, "_store_id", lambda: store_id)
    delivery = SimpleNamespace(object=M3, copy="store:HOUSE", purpose=PURPOSE)
    return server._decide_keep([delivery], agent="agent:rio-grande", now=T("2026-11-02") + 3600, shadow=False)


@pytest.mark.parametrize("store_id, kept", [("OUT", False), ("K", True), (None, False), ("UNREGISTERED", False)],
                         ids=["outside-home", "at-home", "no-id", "no-stores-row"])
def test_the_remember_guard_passes_the_store_it_keeps_into(guard_ledger, monkeypatch, store_id, kept):
    out = _guard(store_id, monkeypatch)
    if kept:
        assert out.reply is None and out.source == M3
    else:
        assert out.reply is not None and out.reply["error"] == "keeping this content is not allowed"
