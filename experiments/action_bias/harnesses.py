from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .isolation import Isolation
from .manifest import RunSpec


@dataclass(frozen=True)
class ParsedOutput:
    final_text: str
    tool_attempts: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]


def build_subject_command(run: RunSpec, isolation: Isolation) -> list[str]:
    if run.condition_id == "off_device" and run.condition_text:
        raise ValueError("off_device condition_text must be empty")
    if run.harness_id == "claude":
        cmd = [
            run.harness.binary, "--print", "--output-format", "stream-json",
            "--include-hook-events", "--no-session-persistence",
            "--strict-mcp-config", "--mcp-config", str(isolation.empty_mcp_config),
            "--model", run.harness.model,
            "--allowedTools", "Read,Glob,Grep,Edit,Write",
            "--permission-mode", "acceptEdits",
        ]
        if run.condition_text:
            cmd += ["--append-system-prompt", run.condition_text]
        return cmd + [run.prompt]
    if run.harness_id == "codex":
        cmd = [
            run.harness.binary, "--ask-for-approval", "never", "exec",
            "--ephemeral", "--ignore-user-config",
            "--ignore-rules", "--json", "--model", run.harness.model,
            "--sandbox", "workspace-write", "--cd", str(isolation.fixture_root),
        ]
        if run.condition_text:
            cmd += [
                "--config",
                f"developer_instructions={json.dumps(run.condition_text)}",
            ]
        return cmd + [run.prompt]
    raise ValueError(f"unsupported harness: {run.harness_id}")


def _walk_tools(value: Any, found: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        item_type = value.get("type")
        if item_type == "tool_use":
            found.append({"name": value.get("name"), "input": value.get("input", {})})
        elif item_type in {"command_execution", "file_change", "mcp_tool_call"}:
            found.append({"name": item_type, "input": value})
        for child in value.values():
            _walk_tools(child, found)
    elif isinstance(value, list):
        for child in value:
            _walk_tools(child, found)


def parse_subject_output(harness_id: str, stdout: str) -> ParsedOutput:
    events: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    final = ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        events.append(event)
        _walk_tools(event, tools)
        if harness_id == "claude" and event.get("type") == "result":
            final = str(event.get("result") or "")
        if harness_id == "codex":
            item = event.get("item") or {}
            if item.get("type") == "agent_message":
                final = str(item.get("text") or final)
    return ParsedOutput(final, tuple(tools), tuple(events))
