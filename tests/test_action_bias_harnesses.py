from pathlib import Path

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
    assert "--no-session-persistence" in cmd
    assert "--strict-mcp-config" in cmd
    assert "--append-system-prompt" in cmd
    assert "seed text" in cmd
    assert "model-x" in cmd
    assert str(tmp_path / "fixture") not in joined  # cwd is supplied to subprocess, not prompt


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
