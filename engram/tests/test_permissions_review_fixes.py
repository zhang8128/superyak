"""The final whole-branch review's fixes (final-review.md, 2026-10-27): each test names its finding."""
import pytest

from permission_ledger import Ledger
from permissions import RuleError
from tests.permissions_support import ANDY, T, do, e1_ledger_through_andys_side, selector_of


# ---------------------------------------------------------------- M1: a row is revoked once (P 5.1)

def _another_writer_goes_first(led, first):
    """`led`'s next write runs `first()` on another connection just before it: both acts passed their checks
    against a State made before either wrote, as a CLI command and an agent's `withdraw` can."""
    original = led._append

    def append(*args, **kw):
        led._append = original
        first()
        return original(*args, **kw)
    led._append = append


SECOND = {"revoke": {}, "shorten": {"valid_until": T("2027-01-01")},
          "narrow": {"selector": selector_of(purposes=frozenset({"care-coordination"}),
                                             actions=frozenset({"recall"}))}}


@pytest.mark.parametrize("kind", ["revoke", "shorten", "narrow"])
def test_m1_a_record_one_writer_revoked_is_not_revoked_again_by_another(tmp_path, kind):
    led = e1_ledger_through_andys_side(tmp_path)
    rid, before = led.ids.R1, len(led.state().records)
    other = Ledger.open(tmp_path)
    _another_writer_goes_first(led, lambda: do(other, ANDY, "revoke", now="2026-11-05", record=rid, reason="first"))
    with pytest.raises(RuleError, match="matched no row"):
        do(led, ANDY, kind, now="2026-11-06", record=rid, reason="second", **SECOND[kind])
    s = Ledger.open(tmp_path).state()
    assert (s.records[rid].revoke_reason, s.records[rid].revoked) == ("first", T("2026-11-05"))
    assert len(s.records) == before                       # no second, live replacement
    assert Ledger.open(tmp_path).verify() is None


@pytest.mark.parametrize("kind", ["revoke-grant", "give-up-grant"])
def test_m1_a_grant_one_writer_ended_is_not_ended_again_by_another(tmp_path, kind):
    led = e1_ledger_through_andys_side(tmp_path)
    gid = led.ids.G1
    other = Ledger.open(tmp_path)
    _another_writer_goes_first(led, lambda: do(other, ANDY, "revoke-grant", now="2026-11-05", grant=gid,
                                               reason="first"))
    actor, channel = (ANDY, "terminal") if kind == "revoke-grant" else ("agent:rio-grande", "tool")
    with pytest.raises(RuleError, match="matched no row"):
        do(led, actor, kind, now="2026-11-06", channel=channel, grant=gid, reason="second")
    g = Ledger.open(tmp_path).state().grants[gid]
    assert (g.revoke_reason, g.revoked, g.revoked_by) == ("first", T("2026-11-05"), ANDY)


# ---------------------------------------------------------------- I1: proposals and child grants are bounded (15, P37)

import time
import tracemalloc

from permissions import Act, selector_json
from tests.permissions_support import HOME, R1_ENVELOPE, RIO, memories

WHEN = "2026-12-05"          # G1 expired on 11-30, so an agent's allow on the tool channel is a proposal
PER_AGENT, IN_LEDGER, CHILDREN = 64, 1024, 64


def _big_allow(i):
    """An allow whose selector lists 512 memories: the largest body an agent's proposal holds."""
    import dataclasses
    sel = dataclasses.replace(R1_ENVELOPE, collections="*", memories=frozenset(memories(512, start=i * 512)))
    return Act("allow", {"layer": HOME, "selector": selector_json(sel), "valid_from": T(WHEN),
                         "valid_until": T("2027-01-31"), "reason": f"ask {i}"})


def _propose(led, agent, i, when=WHEN):
    out = led.perform(_big_allow(i), actor=agent, channel="tool", now=T(when))
    assert out.status == "proposal"
    return out.ref


def test_i1_an_agent_holds_at_most_64_open_proposals(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    filed = [_propose(led, RIO, i) for i in range(PER_AGENT)]
    with pytest.raises(RuleError, match=f"at most {PER_AGENT} open proposals"):
        _propose(led, RIO, PER_AGENT)
    assert len(led.proposals(now=T(WHEN))) == PER_AGENT
    do(led, ANDY, "decline", now=WHEN, proposal=filed[0])        # a decided proposal is no longer open
    _propose(led, RIO, PER_AGENT)
    later = "2026-12-13"                                         # every one of them has expired: none is open
    assert led.proposals(now=T(later)) == []
    _propose(led, RIO, PER_AGENT + 1, when=later)


def test_i1_a_ledger_holds_at_most_1024_open_proposals_and_a_state_holds_none_of_them(tmp_path):
    """The probe that holds the bound (U24's way, without ENGRAM_PI_BUDGET): 1,024 open proposals of 512 refs
    each, the most a ledger holds, and the State a frame or a `perform` builds is no larger for them."""
    led = e1_ledger_through_andys_side(tmp_path)
    agents = [f"agent:asker-{k}" for k in range(IN_LEDGER // PER_AGENT + 1)]
    for a in agents:
        do(led, ANDY, "register-agent", agent=a, acts_for=HOME)
        do(led, ANDY, "put-agent", agent=a, place=HOME)

    def traced_state():
        tracemalloc.start()
        try:
            base = tracemalloc.get_traced_memory()[0]
            s = led.state()
            held = tracemalloc.get_traced_memory()[0] - base
        finally:
            tracemalloc.stop()
        return s, held

    _s, before = traced_state()
    del _s
    start = time.perf_counter()
    for k, a in enumerate(agents[:-1]):
        for i in range(PER_AGENT):
            _propose(led, a, k * PER_AGENT + i)
    took = time.perf_counter() - start
    with pytest.raises(RuleError, match=f"at most {IN_LEDGER:,} open proposals"):
        _propose(led, agents[-1], IN_LEDGER)
    s, after = traced_state()
    assert after - before < 512 * 1024, f"a State grew by {after - before:,} B for {IN_LEDGER} proposals"
    some = led.proposals(now=T(WHEN))
    assert len(some) == IN_LEDGER and len(s.proposals) == IN_LEDGER
    p = s.proposals[some[-1]["id"]]                              # read on demand, whole
    assert p.status == "pending" and f'"reason":"{some[-1]["reason"]}"' in p.body
    print(f"I1 probe: {IN_LEDGER} proposals filed in {took:.1f} s; a State grew by {after - before:,} B")


def test_i1_a_parent_grant_has_at_most_64_live_children(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    do(led, ANDY, "register-agent", now="2026-11-02", agent="agent:rio-2", acts_for=HOME)
    root = do(led, ANDY, "grant", now="2026-11-02", layer=HOME, grantee=RIO, ops=["share", "narrow"],
              envelope=R1_ENVELOPE, max_days=90, depth=1, hours=240).ref

    def child(now="2026-11-03", hours=24):
        return do(led, RIO, "grant", now=now, channel="tool", parent=root, grantee="agent:rio-2", ops=["share"],
                  envelope=R1_ENVELOPE, max_days=30, depth=0, hours=hours).ref

    kids = [child() for _ in range(CHILDREN)]
    with pytest.raises(RuleError, match=f"at most {CHILDREN} live child grants"):
        child()
    do(led, RIO, "revoke-grant", now="2026-11-03", channel="tool", grant=kids[0], reason="done")
    child()                                                      # a revoked child is not live
    with pytest.raises(RuleError, match=f"at most {CHILDREN} live child grants"):
        child()
    child(now="2026-11-04T01:00:00Z")                              # the first 64 expired after 24 hours
