"""Task 6: citations, `until` and the horizon (P 6.5 steps 5 to 7, L8)."""
from dataclasses import replace

from permissions import Refusal, decide, effective_end
from tests.permissions_support import (
    E1_USE_1_LAYERS, HOME, M1, M2, M4, T, andy_world, e1_after_use_7, e1_after_use_9, e1_use_1,
    e1_use_1_with_publisher_rule_until, e1_world, home_use, one_grant_backed_record)


def test_u19_a_dated_deny_refuses_at_its_start_with_no_write():
    s, u = e1_after_use_9()                        # D1 denies m2 from 2026-12-01
    d = decide(s, u(M2, T("2026-11-12")))
    assert d.allowed and d.until == d.horizon == T("2026-12-01")
    assert decide(s, u(M2, T("2026-12-01"))).refusal == Refusal("DENIED", "place:home/andy", "recall")


def test_u19_a_grant_backed_membership_stops_at_its_grant_expiry():
    s, u = e1_after_use_7()                        # m4 collected under G1, which expires 2026-11-30
    d = decide(s, u(M4, T("2026-11-08")))
    assert d.until == d.horizon == T("2026-11-30") and not decide(s, u(M4, T("2026-11-30"))).allowed


def test_u19_until_is_cited_per_layer_and_action():
    d = decide(*e1_use_1())
    assert {(c.layer, c.action) for c in d.cited if c.kind == "consent"} == {
        (layer, x) for layer in E1_USE_1_LAYERS for x in ("recall", "read", "inject_context")}
    assert d.until == T("2027-01-31") and d.horizon == T("2027-01-31")


def test_u19_a_legacy_rule_ending_first_refuses_at_the_next_request():
    s, u, legacy = e1_use_1_with_publisher_rule_until("2026-12-01T00:00:00Z")
    assert decide(s, u(T("2026-11-30")), legacy=legacy).until == T("2027-01-31")   # the ledger's until
    assert decide(s, u(T("2026-12-01") + 1), legacy=legacy).refusal.code == "LEGACY_DENY"


def test_a_decision_with_no_term_has_no_until_and_no_horizon():
    w = andy_world()
    w.allow(HOME, audience=["self"], kinds=["memory"], actions=["recall"])
    d = decide(w.state(), home_use(M1, T("2026-11-02")))
    assert d.allowed and d.until is None and d.horizon is None


def test_a_refusal_before_any_layer_has_no_until_and_no_horizon():
    s, u = e1_use_1()
    d = decide(s, replace(u, requester="agent:nobody"))
    assert d.refusal.code == "UNKNOWN_REQUESTER" and d.until is None and d.horizon is None


def test_horizon_is_the_earliest_term_the_decision_read_and_until_never_passes_it():
    s, u = e1_use_1()
    d = decide(s, replace(u, at=T("2026-11-02")))
    assert d.horizon <= d.until
    s2, u2 = e1_after_use_9()
    d2 = decide(s2, u2(M1, T("2026-11-12")))     # R1' ends 2026-12-15, the deny on m2 starts 2026-12-01
    assert d2.until == T("2026-12-15") and d2.horizon == T("2026-12-01")


def test_effective_end_is_the_earliest_of_the_record_its_chain_its_grants_and_the_matched_memberships():
    w, ids = e1_world(8)
    s = w.state()
    r1p = s.records[ids.R1P]
    assert effective_end(s, r1p, []) == T("2026-12-15")          # its own valid_until
    member = [m for m in s.member_of[M4] if m.backing.startswith("grant:")]
    assert member and effective_end(s, s.records[ids.R1], member) == T("2026-11-30")
    assert effective_end(s, s.records[ids.R1], []) == T("2027-01-31")


def test_effective_end_includes_the_expiry_of_the_grant_behind_a_grant_backed_record():
    s, u = one_grant_backed_record(valid_until=T("2027-06-01"))
    record = next(iter(s.records.values()))
    assert record.backing.startswith("grant:")
    assert effective_end(s, record, []) == min(g.expires for g in s.grants.values()) < T("2027-06-01")
    assert decide(s, u(T("2026-11-10"))).until == effective_end(s, record, [])
