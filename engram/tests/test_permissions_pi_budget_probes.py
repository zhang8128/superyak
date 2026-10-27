"""The probes of U24's memory checks run, on a small reference ledger, in the default suite (Task 31). The budgets
themselves, at full size and under systemd-run, are in test_permissions_pi_budget.py."""
import json
import os
import subprocess
import sys

import pytest

from tests.permissions_budget_core import ALL
from tests.permissions_budget_ledger import prepare, run_probe

SMALL = dict(universe=800, log_rows=3000, tail=80, placements=60, receivers=2, receipts=40, bulk=2, shares=30)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    from tests.permissions_budget_ledger import ensure_reference
    root = tmp_path_factory.mktemp("budget")
    ensure_reference(root, **SMALL)
    return root


def test_the_reference_ledger_is_a_real_ledger(base):
    from permission_ledger import Ledger
    led = Ledger.open_read_only(base / "ref")
    try:
        assert led.verify() is None and led.seq() >= 3000
        assert led.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 41 * 256 + 2          # the two allows of the joint place
        state = led.state()
        assert len(state.collection_members.get(ALL)) == 800
    finally:
        led.close()
    assert (base / "receipts" / ".engram" / "permission-uses.db").is_file()


EXPECT = {
    "state": lambda d: d["records"] == 41 * 256 + 2,
    "eligible": lambda d: d["eligible"] == d["placements"] == 60,
    "bulk": lambda d: d["allowed"] is True and d["trails"] == 20,
    "perform-allow": lambda d: d["status"] == "done",
    "perform-collect": lambda d: d["status"] == "done" and d["members"] == 80,
    "rebuild": lambda d: "rebuilt" in d,
    "check": lambda d: d["exit"] == 0,
    "uses-owner": lambda d: d["exit"] == 0 and d["lines"] >= 1,
    "uses-place": lambda d: d["exit"] == 0,
    "fold": lambda d: d["folded"] == 40,
    "daemon": lambda d: d["frames"] == 6 and not d["errors"] and d["rebuilds"] >= 6 and d["added_bytes"] > 0,
    "migrate": lambda d: d["exit"] == 0,
}


@pytest.mark.parametrize("op", sorted(EXPECT))
def test_each_probe_runs_and_reports_its_peak(base, op):
    home, extra = prepare(base, op, **SMALL, trails=20, touches=16)
    got = run_probe(op, home, extra, scope=False)
    assert got["op"] == op and got["peak_kb"] > 10_000, got
    assert EXPECT[op](got["detail"]), got


def test_the_budgets_are_those_of_revision_8():
    """Section 15's figures, in the module and in the tests' shared core: 2 s, 30 s, 6 s and 300 s."""
    import permissions
    from tests import permissions_budget_core as core
    for mod in (permissions, core):
        assert (mod.REBUILD_BUDGET_S, mod.REBUILD_WORST_S, mod.REBUILD_LEDGER_S, mod.BULK_BUDGET_S) == (2, 30, 6, 300)


def test_the_daemon_probe_serves_eight_receivers_by_three_purposes():
    import inspect
    from tests.permissions_budget_ledger import RECEIVERS, ensure_reference
    from tests.pi_budget_probe import PURPOSES
    assert len(RECEIVERS) == 8 and len(PURPOSES) == 3          # 24 keys, at least the 19 that pass 96 MB (12.2)
    for fn in (ensure_reference, prepare):
        assert inspect.signature(fn).parameters["receivers"].default == 8
