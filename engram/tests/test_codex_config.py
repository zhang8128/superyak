"""Opt-in contract tests for a developer's live Codex MCP configuration."""

import os
from pathlib import Path
import shlex
import tomllib

import pytest


CONFIG = os.environ.get("ENGRAM_LIVE_CODEX_CONFIG")
PROJECT = os.environ.get("ENGRAM_LIVE_CODEX_PROJECT")
pytestmark = pytest.mark.skipif(
    not CONFIG and not PROJECT,
    reason="set ENGRAM_LIVE_CODEX_CONFIG and ENGRAM_LIVE_CODEX_PROJECT for live host checks",
)
CONFIG_PATH = Path(CONFIG) if CONFIG else None
SERVER = f"{PROJECT}/server.py"


def live_config():
    assert CONFIG and PROJECT, "Live host checks require both config and project paths"
    return tomllib.loads(CONFIG_PATH.read_text())


def test_engram_launcher_preserves_caller_cwd_and_contract():
    config = live_config()
    engram = config["mcp_servers"]["engram"]

    assert engram["command"] == "sh"
    argv = shlex.split(engram["args"][1])
    assert argv[:3] == ["ENGRAM_RUN_KEY=codex:$PPID", "exec", "uv"]
    assert "--project" in argv
    assert argv[argv.index("--project") + 1] == PROJECT
    assert "--directory" not in argv
    assert argv[-2:] == ["python", SERVER]
    assert engram["env"] == {
        "ENGRAM_DEFAULT_INSTANCE": "engram",
        "ENGRAM_HOME": PROJECT,
        "ENGRAM_HARNESS": "codex",
    }
    assert engram["startup_timeout_sec"] == 30


def test_engram_tool_approvals_are_unchanged():
    config = live_config()
    tools = config["mcp_servers"]["engram"]["tools"]
    assert {name: spec["approval_mode"] for name, spec in tools.items()} == {
        "task_focus": "approve",
        "status": "approve",
        "remember": "approve",
        "task_update": "approve",
    }
