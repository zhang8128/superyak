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
    "daemon": lambda d: d["frames"] == 4 and not d["errors"] and d["rebuilds"] >= 4,
    "migrate": lambda d: d["exit"] == 0,
}


@pytest.mark.parametrize("op", sorted(EXPECT))
def test_each_probe_runs_and_reports_its_peak(base, op):
    home, extra = prepare(base, op, **SMALL, trails=20, touches=16)
    got = run_probe(op, home, extra, scope=False)
    assert got["op"] == op and got["peak_kb"] > 10_000, got
    assert EXPECT[op](got["detail"]), got
