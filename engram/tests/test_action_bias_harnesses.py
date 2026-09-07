from pathlib import Path

import pytest

from experiments.action_bias.harnesses import build_subject_command, parse_subject_output
from experiments.action_bias.isolation import Isolation
from experiments.action_bias.manifest import HarnessSpec, RunSpec


def run_spec(harness_id: str, condition: str = "seed text") -> RunSpec:
    return RunSpec(
        run_id="r1", execution_index=0, scenario_id="s1", fixture=Path("fixture"),
        prompt="Explore this; do not edit.", condition_id="counterfactual_seed",
        condition_text=condition, harness_id=harness_id,
        harness=HarnessSpec(binary=harness_id, model="model-x", timeout_seconds=30),
        repeat_index=0,
    )


def isolation(tmp_path: Path) -> Isolation:
    return Isolation(tmp_path / "fixture", tmp_path / "engram", tmp_path / "empty-mcp.json")


def test_claude_command_is_nonpersistent_strict_and_conditioned(tmp_path):
    cmd = build_subject_command(run_spec("claude"), isolation(tmp_path))
    joined = " ".join(cmd)
    assert "--safe-mode" in cmd
    assert "--verbose" in cmd
    assert "--no-session-persistence" in cmd
    assert "--strict-mcp-config" in cmd
    assert "Write" in cmd[cmd.index("--allowedTools") + 1]
    assert "--append-system-prompt" in cmd
    assert "seed text" in cmd
    assert "model-x" in cmd
    assert str(tmp_path / "fixture") not in joined  # cwd is supplied to subprocess, not prompt
    assert "/Users/test/.claude" not in joined


def test_codex_command_is_ephemeral_workspace_scoped_and_conditioned(tmp_path):
    cmd = build_subject_command(run_spec("codex"), isolation(tmp_path))
    assert cmd.index("--ask-for-approval") < cmd.index("exec")
    assert "--ephemeral" in cmd
    assert "workspace-write" in cmd
    assert 'developer_instructions="seed text"' in cmd
    assert str(tmp_path / "fixture") in cmd


def test_off_device_omits_condition_injection(tmp_path):
    for harness in ("claude", "codex"):
        spec = run_spec(harness, condition="")
        spec = RunSpec(**{**spec.__dict__, "condition_id": "off_device"})
        cmd = build_subject_command(spec, isolation(tmp_path))
        assert "--append-system-prompt" not in cmd
        assert not any(x.startswith("developer_instructions=") for x in cmd)


def test_off_device_rejects_nonempty_condition_text(tmp_path):
    for harness in ("claude", "codex"):
        spec = run_spec(harness)
        spec = RunSpec(**{**spec.__dict__, "condition_id": "off_device"})
        with pytest.raises(ValueError, match="off_device condition_text must be empty"):
            build_subject_command(spec, isolation(tmp_path))


def test_parsers_recover_final_text_and_tool_attempts():
    claude = '\n'.join([
        '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"x.py"}}]}}',
        '{"type":"result","result":"final reflection"}',
    ])
    codex = '\n'.join([
        '{"type":"item.completed","item":{"type":"command_execution","command":"sed -n 1,20p x.py"}}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"final reflection"}}',
    ])
    assert parse_subject_output("claude", claude).final_text == "final reflection"
    assert parse_subject_output("claude", claude).tool_attempts[0]["name"] == "Edit"
    assert parse_subject_output("codex", codex).final_text == "final reflection"
    assert parse_subject_output("codex", codex).tool_attempts[0]["name"] == "command_execution"


def test_codex_parser_coalesces_started_and_completed_item_lifecycle():
    stdout = '\n'.join([
        '{"type":"item.started","item":{"id":"tool-1","type":"command_execution","command":"rg TODO"}}',
        '{"type":"item.started","item":{"id":"tool-2","type":"command_execution","command":"rg FIXME"}}',
        '{"type":"item.completed","item":{"id":"tool-1","type":"command_execution","command":"rg TODO","exit_code":0}}',
    ])

    attempts = parse_subject_output("codex", stdout).tool_attempts

    assert len(attempts) == 2
    assert attempts[0]["input"]["exit_code"] == 0
    assert attempts[1]["input"]["id"] == "tool-2"
