"""Exercise native coding hosting over the actual bounded stdio transport."""

import json
import os
from pathlib import Path
import sys
import time

import pytest

from context_provider import ProviderError


FIXTURE = Path(__file__).parent / "fixtures" / "context_coding_server.py"


def request():
    return {"model": "gpt-6-astra", "instructions": "Respect source attribution.",
            "input": [{"role": "user", "content": "Create addition.py and check it."}],
            "tools": [], "store": False, "truncation": "disabled", "max_output_tokens": 2048}


def provider(tmp_path, scenario="success", **kwargs):
    from context_coding_provider import CodingProvider
    kwargs.setdefault("timeout", 3)
    return CodingProvider(cwd=tmp_path, command=[sys.executable, str(FIXTURE), scenario,
                                                str(tmp_path / "peer.jsonl")], **kwargs)


def recorded(tmp_path):
    return [json.loads(line) for line in (tmp_path / "peer.jsonl").read_text().splitlines()]


def assert_reaped(tmp_path):
    for entry in recorded(tmp_path):
        if "pid" in entry:
            with pytest.raises(ProcessLookupError):
                os.kill(entry["pid"], 0)


@pytest.mark.parametrize("scenario", ["success", "early_events", "final_in_turn", "wrong_turn"])
def test_native_file_and_command_events_yield_valid_checkpoint(tmp_path, monkeypatch, scenario):
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-inherit")
    adapter = provider(tmp_path, scenario)
    events = []
    result = adapter.episode(request(), events.append)
    assert result["status"] == "completed"
    assert result["checkpoint"] == {"status": "complete", "summary": "Created addition.py and checked its result.",
                                    "decisions": [], "next_steps": [], "checks": ["addition.py returned 4"]}
    assert result["usage"]["total_tokens"] == 99
    assert result["reason"] is None
    assert (tmp_path / "addition.py").read_text() == "print(2 + 2)\n"
    assert any(e["method"] == "item/commandExecution/outputDelta" and e["params"]["delta"] == "4\n" for e in events)
    assert any(e.get("params", {}).get("item", {}).get("type") == "fileChange" for e in events)
    assert all(e.get("params", {}).get("turnId", "turn-1") != "other" for e in events)
    assert recorded(tmp_path)[0]["api_keys_present"] is False
    assert_reaped(tmp_path)
    adapter.close()


def test_coding_configuration_isolated_with_native_tools_and_schema(tmp_path):
    adapter = provider(tmp_path)
    adapter.episode(request(), lambda event: None)
    messages = recorded(tmp_path)
    start = next(e["params"] for e in messages if e.get("method") == "thread/start")
    turn = next(e["params"] for e in messages if e.get("method") == "turn/start")
    assert start["ephemeral"] is True
    assert start["model"] == "gpt-6-astra"
    assert start["modelProvider"] == "openai"
    assert start["sandbox"] == "workspace-write"
    assert start["approvalPolicy"] == "on-request"
    assert start["approvalsReviewer"] == "user"
    assert start["config"]["mcp_servers"] == {"fixture_mcp": {"enabled": False}}
    assert start["config"]["web_search"] == "disabled"
    for feature in ("apps", "plugins", "hooks", "memories", "multi_agent", "multi_agent_v2", "browser_use", "computer_use", "image_generation"):
        assert start["config"]["features"][feature] is False
    assert start["config"]["features"]["shell_tool"] is True
    assert start["config"]["features"]["unified_exec"] is True
    assert "baseInstructions" not in start  # Keep native instructions and repository AGENTS.
    assert turn["sandboxPolicy"]["type"] == "workspaceWrite"
    assert turn["sandboxPolicy"]["networkAccess"] is False
    schema = turn["outputSchema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["status"]["enum"] == ["complete", "continue", "needs_input"]
    assert schema["properties"]["summary"]["maxLength"] <= 6000
    assert adapter.capabilities == {"strict": False, "budget_scope": "episode", "count_kind": "estimate", "billing": "subscription"}
    assert adapter.count(request()) > 0
    adapter.close()


def test_latest_input_usage_steers_once_and_keeps_original_usage(tmp_path):
    adapter = provider(tmp_path, "soft", soft_tokens=100, hard_tokens=200)
    events = []
    result = adapter.episode(request(), events.append)
    assert result["status"] == "completed"
    methods = [e.get("method") for e in recorded(tmp_path)]
    assert methods.count("turn/steer") == 1
    assert "turn/interrupt" not in methods
    assert result["usage"]["codex"]["last"]["inputTokens"] == 110
    assert any(e["method"] == "engram/episodeLimit" and e["params"]["action"] == "steer" for e in events)
    adapter.close()


@pytest.mark.parametrize("scenario", ["hard", "steer_race"])
def test_hard_usage_interrupts_without_waiting_for_steer_or_restarting(tmp_path, scenario):
    adapter = provider(tmp_path, scenario, soft_tokens=100, hard_tokens=200)
    result = adapter.episode(request(), lambda event: None)
    assert result["status"] == "interrupted"
    assert result["checkpoint"] is None
    assert "usage" in result["reason"]
    methods = [e.get("method") for e in recorded(tmp_path)]
    assert methods.count("turn/start") == methods.count("turn/steer") == methods.count("turn/interrupt") == 1
    assert_reaped(tmp_path)
    adapter.close()


def test_step_limit_counts_each_completed_command_once(tmp_path):
    adapter = provider(tmp_path, "steps", max_steps=3)
    events = []
    result = adapter.episode(request(), events.append)
    assert result["status"] == "interrupted"
    assert "step" in result["reason"]
    limits = [e["params"] for e in events if e["method"] == "engram/episodeLimit"]
    assert [e["action"] for e in limits] == ["steer", "interrupt"]
    assert limits[-1]["completed_steps"] == 3
    adapter.close()


@pytest.mark.parametrize("scenario", ["approval", "file_approval", "permissions_approval"])
@pytest.mark.parametrize("accepted", [False, True])
def test_native_escalation_requires_explicit_matching_terminal_decision(tmp_path, scenario, accepted):
    requests, events = [], []
    def approve(value):
        requests.append(value)
        return accepted
    adapter = provider(tmp_path, scenario, approve=approve if accepted else None)
    result = adapter.episode(request(), events.append)
    assert result["status"] == "completed"
    assert (tmp_path / "approved.txt").exists() is accepted
    assert len(requests) == int(accepted)
    decisions = [e for e in events if e["method"] == "engram/approval"]
    assert decisions[-1]["params"]["decision"] == ("accept" if accepted else "decline")
    answer = next(e["result"] for e in recorded(tmp_path) if e.get("id") == "approval-1")
    if scenario == "permissions_approval":
        assert answer["scope"] == "turn"
    else:
        assert answer["decision"] in {"accept", "decline"}
    adapter.close()


@pytest.mark.parametrize("scenario", ["wrong_approval", "external_request"])
def test_external_or_unrelated_requests_cannot_gain_approval(tmp_path, scenario):
    requests = []
    adapter = provider(tmp_path, scenario, approve=lambda value: requests.append(value) or True)
    result = adapter.episode(request(), lambda event: None)
    assert result["status"] == "completed"
    assert requests == []
    assert not (tmp_path / "approved.txt").exists()
    adapter.close()


@pytest.mark.parametrize("scenario,match", [
    ("api_account", "ChatGPT"), ("missing_model", "unavailable"),
    ("changed_model", "model"), ("unsafe_sandbox", "sandbox"),
    ("unsafe_roots", "sandbox"), ("auto_review", "approval"), ("unsafe_cwd", "directory"),
    ("bad_json", "checkpoint"), ("bad_checkpoint", "checkpoint"),
    ("large_checkpoint", "checkpoint"), ("large_list", "checkpoint"),
    ("large_entry", "checkpoint"), ("checkpoint_bytes", "checkpoint"),
    ("extra_checkpoint", "checkpoint"), ("bad_usage", "usage"),
    ("failed_turn", "failed"), ("malformed", "Malformed"),
    ("exit", "closed"), ("stdout_flood", "byte limit"),
    ("stderr_flood", "byte limit"), ("timeout", "timeout"),
])
def test_failures_reap_process_and_never_replay(tmp_path, scenario, match):
    adapter = provider(tmp_path, scenario, timeout=0.3 if scenario == "timeout" else 3)
    with pytest.raises(ProviderError, match=match) as caught:
        adapter.episode(request(), lambda event: None)
    assert "private failure" not in str(caught.value)
    assert_reaped(tmp_path)
    assert sum(e.get("method") == "turn/start" for e in recorded(tmp_path)) <= 1
    adapter.close()


def test_cumulative_usage_does_not_trigger_context_pressure(tmp_path):
    adapter = provider(tmp_path, "cumulative_usage", soft_tokens=100, hard_tokens=200)
    result = adapter.episode(request(), lambda event: None)
    assert result["status"] == "completed"
    assert result["usage"]["input_tokens"] == 900000
    assert result["usage"]["codex"]["last"]["inputTokens"] == 89
    assert not any(e.get("method") in {"turn/steer", "turn/interrupt"} for e in recorded(tmp_path))
    adapter.close()


def archive_request():
    from context_runtime import TOOLS
    return request() | {"tools": TOOLS}


def test_dynamic_archive_read_returns_bounded_evidence_to_native_agent(tmp_path):
    adapter = provider(tmp_path, "tool_success")
    calls, events = [], []
    def read(name, arguments):
        calls.append((name, arguments))
        return {"content": "Earlier check failed because addition.py did not exist."}
    assert adapter.count(archive_request()) > adapter.count(request())
    result = adapter.episode(archive_request(), events.append, tool_handler=read)
    assert result["checkpoint"]["summary"] == "Archive retrieved"
    assert calls == [("archive_read", {"id": "event-old", "offset": 0, "limit": 100})]
    start = next(e["params"] for e in recorded(tmp_path) if e.get("method") == "thread/start")
    assert {t["name"] for t in start["dynamicTools"]} == {"archive_read", "archive_search"}
    assert all(t["type"] == "function" and t["inputSchema"]["type"] == "object" for t in start["dynamicTools"])
    response = next(e["result"] for e in recorded(tmp_path) if e.get("id") == "tool-1")
    assert response == {"contentItems": [{"type": "inputText", "text": '{"content":"Earlier check failed because addition.py did not exist."}'}], "success": True}
    assert any(e["method"] == "item/tool/call" for e in events)
    adapter.close()


@pytest.mark.parametrize("scenario", ["tool_wrong_thread", "tool_wrong_turn", "tool_unknown", "tool_bad_args"])
def test_unrelated_or_malformed_archive_requests_are_not_dispatched(tmp_path, scenario):
    calls = []
    adapter = provider(tmp_path, scenario)
    result = adapter.episode(archive_request(), lambda event: None,
                             tool_handler=lambda *args: calls.append(args) or {})
    assert result["checkpoint"]["summary"] == "Archive request declined"
    assert calls == []
    adapter.close()


@pytest.mark.parametrize("handler", [None, lambda *_: {"content": "x" * 65537},
                                    lambda *_: {"error": "Archive limit must be between 1 and 4096"}])
def test_missing_handler_or_excessive_archive_result_is_declined(tmp_path, handler):
    adapter = provider(tmp_path, "tool_success")
    result = adapter.episode(archive_request(), lambda event: None, tool_handler=handler)
    assert result["checkpoint"]["summary"] == "Archive request declined"
    adapter.close()


def test_archive_tool_steps_trigger_limit_without_waiting_for_completion_event(tmp_path):
    adapter = provider(tmp_path, "tool_step", max_steps=1)
    result = adapter.episode(archive_request(), lambda event: None, tool_handler=lambda *_: {"content": "done"})
    assert result["status"] == "interrupted"
    assert "step" in result["reason"]
    adapter.close()


@pytest.mark.parametrize("kwargs", [{"soft_tokens": 0}, {"hard_tokens": 0}, {"soft_tokens": 5, "hard_tokens": 5},
                                   {"max_steps": 0}, {"max_steps": True}, {"soft_tokens": float("inf")},
                                   {"approve": "yes"}])
def test_invalid_limits_and_callback_rejected_before_process_start(tmp_path, kwargs):
    with pytest.raises(ProviderError):
        provider(tmp_path, **kwargs)
    assert not (tmp_path / "peer.jsonl").exists()


def test_unsupported_dynamic_tool_rejected_before_process_start(tmp_path):
    adapter = provider(tmp_path)
    with pytest.raises(ProviderError, match="tool"):
        adapter.episode(request() | {"tools": [{"type": "function", "name": "shell", "parameters": {"type": "object"}}]}, lambda event: None)
    assert not (tmp_path / "peer.jsonl").exists()
    adapter.close()


def test_keyboard_interrupt_in_callback_cleans_up_without_replay(tmp_path):
    adapter = provider(tmp_path)
    def interrupted(event):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        adapter.episode(request(), interrupted)
    assert_reaped(tmp_path)
    adapter.close()


def test_early_archive_request_declined_until_turn_id_is_confirmed(tmp_path):
    adapter = provider(tmp_path, "tool_early_ack")
    calls = []
    result = adapter.episode(archive_request(), lambda event: None,
                             tool_handler=lambda *args: calls.append(args) or {})
    assert result["checkpoint"]["summary"] == "Archive request declined"
    assert calls == []
    adapter.close()


@pytest.mark.parametrize("scenario,match", [("steer_wrong_id", "turn id"), ("steer_error", "request failed"),
                                          ("hard_invalid_status", "terminal")])
def test_invalid_control_protocol_pauses_with_error_and_cleanup(tmp_path, scenario, match):
    adapter = provider(tmp_path, scenario, soft_tokens=100, hard_tokens=200)
    with pytest.raises(ProviderError, match=match):
        adapter.episode(request(), lambda event: None)
    assert_reaped(tmp_path)
    adapter.close()


def test_event_observer_cannot_mutate_validated_checkpoint_or_usage(tmp_path):
    adapter = provider(tmp_path)
    def render(event):
        event["params"].clear()
    result = adapter.episode(request(), render)
    assert result["checkpoint"]["status"] == "complete"
    assert result["usage"]["total_tokens"] == 99
    adapter.close()


def test_native_workspace_temporary_directories_preserve_writable_repo(tmp_path):
    adapter = provider(tmp_path, "native_temp_sandbox")
    result = adapter.episode(request(), lambda event: None)
    assert result["status"] == "completed"
    assert (tmp_path / "addition.py").exists()
    turn = next(e["params"] for e in recorded(tmp_path) if e.get("method") == "turn/start")
    assert turn["sandboxPolicy"]["excludeTmpdirEnvVar"] is False
    assert turn["sandboxPolicy"]["excludeSlashTmp"] is False
    adapter.close()


def test_default_local_environment_keeps_native_shell_and_edit_tools_available(tmp_path):
    adapter = provider(tmp_path, "native_environment")
    events = []
    adapter.episode(request(), events.append)
    assert (tmp_path / "addition.py").exists()
    assert any(e["method"] == "item/commandExecution/outputDelta" for e in events)
    adapter.close()


@pytest.mark.parametrize("scenario", ["early_exit", "early_malformed"])
def test_tool_events_archived_before_acknowledgment_or_later_protocol_failure(tmp_path, scenario):
    adapter = provider(tmp_path, scenario)
    events = []
    with pytest.raises(ProviderError):
        adapter.episode(request(), events.append)
    assert (tmp_path / "addition.py").exists()
    assert any(e["method"] == "item/commandExecution/outputDelta" and e["params"]["delta"] == "4\n" for e in events)
    assert_reaped(tmp_path)
    adapter.close()


def test_early_notifications_are_archived_once(tmp_path):
    adapter = provider(tmp_path, "early_events")
    events = []
    adapter.episode(request(), events.append)
    assert sum(e["method"] == "item/commandExecution/outputDelta" for e in events) == 1
    adapter.close()


def test_shutdown_allows_appserver_to_handle_eof_before_forcing_termination(tmp_path):
    adapter = provider(tmp_path, "graceful_close")
    adapter.episode(request(), lambda event: None)
    assert {"graceful_shutdown": True} in recorded(tmp_path)
    adapter.close()


def test_timeout_stops_native_children_in_separate_process_groups(tmp_path):
    adapter = provider(tmp_path, "detached_timeout", timeout=0.25)
    with pytest.raises(ProviderError, match="timeout"):
        adapter.episode(request(), lambda event: None)
    assert_reaped(tmp_path)
    time.sleep(1.1)
    assert not (tmp_path / "after_close.txt").exists()
    adapter.close()
