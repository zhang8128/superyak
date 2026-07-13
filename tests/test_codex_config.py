"""Contract tests for the live Codex MCP configuration."""

from pathlib import Path
import shlex
import tomllib


CONFIG_PATH = Path("/Users/kairos/.codex/config.toml")
PROJECT = "/Users/kairos/Projects/engram"
SERVER = f"{PROJECT}/server.py"


def test_engram_launcher_preserves_caller_cwd_and_contract():
    config = tomllib.loads(CONFIG_PATH.read_text())
    engram = config["mcp_servers"]["engram"]

    assert engram["command"] == "sh"
    argv = shlex.split(engram["args"][1])
    assert argv[:3] == ["ENGRAM_RUN_KEY=codex:$PPID", "exec", "uv"]
    assert "--project" in argv
    assert argv[argv.index("--project") + 1] == PROJECT
    assert "--directory" not in argv
    assert argv[-2:] == ["python", SERVER]
    assert engram["env"] == {
        "ENGRAM_HOME": PROJECT,
        "ENGRAM_HARNESS": "codex",
    }
    assert engram["startup_timeout_sec"] == 30


def test_engram_tool_approvals_are_unchanged():
    config = tomllib.loads(CONFIG_PATH.read_text())
    tools = config["mcp_servers"]["engram"]["tools"]
    assert {name: spec["approval_mode"] for name, spec in tools.items()} == {
        "task_focus": "approve",
        "status": "approve",
        "remember": "approve",
        "task_update": "approve",
    }
