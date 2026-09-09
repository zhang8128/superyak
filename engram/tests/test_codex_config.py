"""Opt-in contract tests for a developer's live Codex MCP configuration."""

import os
from pathlib import Path
import json
import shlex
import subprocess
import tomllib

import pytest


CONFIG = os.environ.get("ENGRAM_LIVE_CODEX_CONFIG")
PROJECT = os.environ.get("ENGRAM_LIVE_CODEX_PROJECT")
pytestmark = pytest.mark.skipif(
    not CONFIG and not PROJECT,
    reason="set ENGRAM_LIVE_CODEX_CONFIG and ENGRAM_LIVE_CODEX_PROJECT for live host checks",
)
CONFIG_PATH = Path(CONFIG) if CONFIG else None
RUNTIME_CONFIG_PATH = Path(
    os.environ.get(
        "SUPERYAK_RUNTIME_CONFIG",
        Path.home() / ".config" / "superyak" / "runtime.json",
    )
)
RUNTIME_WRAPPER = Path.home() / ".local" / "bin" / "superyak-runtime"


def live_config():
    assert CONFIG and PROJECT, "Live host checks require both config and project paths"
    return tomllib.loads(CONFIG_PATH.read_text())


def test_engram_launcher_preserves_caller_cwd_and_contract():
    config = live_config()
    engram = config["mcp_servers"]["engram"]

    assert engram["command"] == "sh"
    argv = shlex.split(engram["args"][1])
    assert argv == [
        "ENGRAM_RUN_KEY=codex:$PPID",
        "exec",
        "$HOME/.local/bin/superyak-runtime",
        "mcp",
    ]
    assert engram["env"] == {"ENGRAM_HARNESS": "codex"}
    assert engram["startup_timeout_sec"] == 30

    runtime_config = json.loads(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
    memory_home = Path(runtime_config["memory_home"])
    assert memory_home.is_absolute() and memory_home.is_dir()
    assert runtime_config["default_instance"] == "engram"
    assert RUNTIME_WRAPPER.is_file() and os.access(RUNTIME_WRAPPER, os.X_OK)

    status_result = subprocess.run(
        [str(RUNTIME_WRAPPER), "--config", str(RUNTIME_CONFIG_PATH), "status"],
        cwd=PROJECT,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert status_result.returncode == 0, status_result.stdout + status_result.stderr
    status = json.loads(status_result.stdout)
    assert status["source"]["path"] == str(Path(PROJECT).parent)
    assert status["memory_home"]["path"] == str(memory_home)
    assert status["instance"]["project_root"] == str(Path(PROJECT))


def test_engram_tool_approvals_are_unchanged():
    config = live_config()
    tools = config["mcp_servers"]["engram"]["tools"]
    assert {name: spec["approval_mode"] for name, spec in tools.items()} == {
        "task_focus": "approve",
        "status": "approve",
        "remember": "approve",
        "task_update": "approve",
    }
