"""Shadow receipts record the audience refusal directly (Task 30C; P 9.1, 12.3)."""
import json

from permission_cli import main
from tests.permissions_support import cli_home, cli_home_with_house, fake_tty  # noqa: F401
from tests.permissions_support import HOME, M1_ITEM, receipt_rows, shadow_daemon, write_publisher_policy
from tests.test_permissions_cli_read import (  # noqa: F401  (the fixture and its helpers)
    add_receipt, cli_shadow_world, deny_cited)

LEGACY_DENY = {"code": "LEGACY_DENY", "layer": "publisher", "action": "inject_context"}
LEDGER_DENY = {"code": "DENIED", "layer": HOME, "action": "inject_context"}


def test_shadow_receipt_records_the_audience_refusal_when_the_ledger_refuses_too(tmp_path):
    d = shadow_daemon(tmp_path, legacy_allows=True, ledger_allows=False)
    write_publisher_policy(tmp_path, receiver_audiences=["group:other"])
    assert d.read(M1_ITEM)["content"] is None
    row = receipt_rows(tmp_path, action="inject_context")[-1]
    assert row["shadow"] == 1 and row["allowed"] == 0 and row["content_digest"] is None
    assert json.loads(row["refusal"])["code"] != "LEGACY_DENY"      # the ledger's own code (final review M8)
    assert {"layer": "publisher", "kind": "audience", "action": "inject_context", "verdict": "deny",
            "record": None, "version": None} in json.loads(row["cited"])


def test_shadow_receipt_of_a_ledger_only_refusal_is_not_marked_as_an_audience_refusal(tmp_path):
    d = shadow_daemon(tmp_path, legacy_allows=True, ledger_allows=False)
    assert d.read(M1_ITEM)["content"]
    row = receipt_rows(tmp_path, action="inject_context")[-1]
    assert row["allowed"] == 0 and json.loads(row["refusal"]).get("code") != "LEGACY_DENY"


def _receipt(home, at, *, allowed, refusal, digest):
    return add_receipt(home, place=HOME, at=at, allowed=allowed, action="inject_context", shadow=1,
                       cited=[deny_cited(HOME)] if not allowed else [], refusal=refusal, content_digest=digest)


def test_report_shadow_reads_the_recorded_refusal_not_the_digest(cli_shadow_world, capsys):
    home = cli_shadow_world.home
    both = _receipt(home, "2026-11-06", allowed=False, digest=None, refusal=LEGACY_DENY)
    no_object_digest = _receipt(home, "2026-11-07", allowed=False, digest=None, refusal=LEDGER_DENY)
    only_ledger = _receipt(home, "2026-11-08", allowed=False, digest="d" * 64, refusal=LEDGER_DENY)
    only_audience = _receipt(home, "2026-11-09", allowed=True, digest=None, refusal=LEGACY_DENY)
    assert main(["report", "shadow", "--json"]) == 0
    got = [r["id"] for r in json.loads(capsys.readouterr().out)["disagreements"]]
    assert both not in got
    assert got == [cli_shadow_world.refused_receipt, no_object_digest, only_ledger, only_audience]
