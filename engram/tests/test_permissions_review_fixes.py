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
