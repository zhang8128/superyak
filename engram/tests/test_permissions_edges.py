"""Task 18: config, the policy generator and the share argument (P 12.1, 12.3; U16, U23)."""
import logging

import pytest

import server
from config import load_config
from permission_ledger import Ledger, effective_gate, houses
from policy_gen import load_groups
from storage import Storage
from tests.permissions_support import T, raise_gate
from tests.test_recall_margins import engram_server_env, seed  # noqa: F401
from tests.test_share_tools import _published_house


def write_config(tmp_path, text):
    (tmp_path / ".engram").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".engram" / "config.toml").write_text(text)


def raised_ledger(tmp_path, houses=("lighthouse",), mode="shadow"):
    for name in houses:
        path = tmp_path / ".engram" / "instances" / name / "graph.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        Storage(str(path)).close()
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    raise_gate(led, mode)
    return led


def test_u16_a_permissions_section_logs_one_warning_and_changes_no_mode(tmp_path, caplog):
    write_config(tmp_path, "[permissions]\ngate = \"off\"\n")
    raised_ledger(tmp_path, houses=("lighthouse",), mode="enforce")
    with caplog.at_level(logging.WARNING, logger="engram.config"):
        load_config(tmp_path)
    warnings = [r for r in caplog.records if "permissions" in r.getMessage()]
    assert len(warnings) == 1 and "engram-permissions gate" in warnings[0].getMessage()
    assert effective_gate(tmp_path, houses(tmp_path)).mode == "enforce"


def test_u23_policy_gen_refuses_a_group_named_outside_home(tmp_path):
    (tmp_path / "groups.toml").write_text('[groups.outside-home]\nmembers = ["why"]\n')
    with pytest.raises(ValueError, match="outside-home"):
        load_groups(tmp_path / "groups.toml")


def test_u23_share_refuses_group_outside_home_as_an_argument(engram_server_env, tmp_path):
    _published_house(tmp_path); seed()
    ep = server.remember(content="a thing worth sharing")
    out = server.share(memory_id=ep["episode_id"], audience="group:outside-home", reason="r")
    assert "error" in out and "reserved" in out["error"]
