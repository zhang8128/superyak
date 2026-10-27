"""Tardis's advisory review of permissions-core (reviews/2026-10-27-tardis-permissions-core-advisory.md): each
test names its finding."""
from dataclasses import replace

from permissions import Placement, Refusal, decide, eligible_set, parse_selector, selector_json
from tests.permissions_support import HOME, M1, T, andy_world, home_use


# ---------------------------------------------------------------- T1: a grant behind a grant's envelope (P 6.5, L8)

C1, C2 = "collection:andy/c1", "collection:andy/c2"


def _envelope(collections):
    return selector_json(parse_selector({
        "audience": ["self"], "requesters": "*", "actions": "*", "purposes": "*",
        "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*", "collections": collections,
                    "memories": "*"}}))


def _nested(*, revoke_inner=False):
    """An allow at Andy's home names c1. m1 is in c1 only under G1, whose envelope names c2 and which expires
    2026-11-30; and in c2 only under G2, which expires 2026-11-05. So the allow holds only while G2 does."""
    w = andy_world()
    w.agent("helper", HOME, at=HOME)
    g1 = w.grant("person:andy", "agent:helper", HOME, ops=("collect",), envelope=_envelope([C2]),
                 expires=T("2026-11-30"))
    g2 = w.grant("person:andy", "agent:helper", HOME, ops=("collect",), envelope=_envelope("*"),
                 expires=T("2026-11-05"))
    w.collect(C1, [M1], backing="grant:" + g1)
    w.collect(C2, [M1], backing="grant:" + g2)
    w.allow(HOME, audience=["self"], collections=[C1], actions=["recall"])
    if revoke_inner:
        w.revoke_grant(g2)
    return w.state()


def test_t1_until_and_horizon_stop_at_the_expiry_of_the_grant_the_envelope_relies_on():
    s = _nested()
    d = decide(s, home_use(M1, T("2026-11-02")))
    assert d.allowed
    assert d.until == d.horizon == T("2026-11-05")
    assert not decide(s, home_use(M1, T("2026-11-05"))).allowed        # L8: it flips at the horizon, not after


def test_t1_a_use_after_the_inner_grant_expires_is_refused_with_expired():
    d = decide(_nested(), home_use(M1, T("2026-11-05")))
    assert d.refusal == Refusal("EXPIRED", HOME, "recall")


def test_t1_a_use_after_the_inner_grant_is_revoked_is_refused_with_grant_invalid():
    d = decide(_nested(revoke_inner=True), home_use(M1, T("2026-11-02")))
    assert d.refusal == Refusal("GRANT_INVALID", HOME, "recall")


def test_t1_an_eligible_set_ends_at_the_inner_grants_expiry():
    s = _nested()
    es = eligible_set(s, [Placement("p1", M1, "store:house")], requester="agent:rio-grande", place=HOME,
                      purpose="care-coordination", action="recall", at=T("2026-11-02"))
    assert es.memory_ids == {"p1"} and es.horizon == T("2026-11-05")
    later = replace(home_use(M1, T("2026-11-02")), copy="store:house")
    assert not decide(s, replace(later, at=es.horizon)).allowed
