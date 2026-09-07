"""Run the adapter against a real, scripted stdio subprocess."""

import json
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import time

import pytest


FIXTURE = Path(__file__).parent / "fixtures" / "context_codex_server.py"


def request():
    return {"model": "gpt-6-astra", "instructions": "Respect source attribution.",
            "input": [{"role": "assistant", "content": "Earlier answer"}, {"role": "user", "content": "Hello 🦊"}],
            "tools": [], "store": False, "truncation": "disabled", "max_output_tokens": 64}


def provider(tmp_path, scenario="success", timeout=3):
    from context_codex import CodexProvider
    return CodexProvider(cwd=tmp_path, timeout=timeout,
                         command=[sys.executable, str(FIXTURE), scenario, str(tmp_path / "peer.jsonl")])


def recorded(tmp_path):
    return [json.loads(line) for line in (tmp_path / "peer.jsonl").read_text().splitlines()]


def assert_reaped(tmp_path):
    pid = recorded(tmp_path)[0]["pid"]
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_subscription_episode_uses_selected_model_and_preserves_final_only(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-inherit")
    adapter = provider(tmp_path)
    result = adapter.generate(request())
    assert result["status"] == "completed"
    assert result["output"] == [{"id": "answer-1", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "Answer 🦊", "annotations": []}]}]
    assert result["usage"]["input_tokens"] == 90
    assert result["usage"]["output_tokens"] == 9
    assert result["usage"]["codex"]["total"]["reasoningOutputTokens"] == 4
    assert adapter.capabilities == {"strict": False, "budget_scope": "episode", "count_kind": "estimate", "billing": "subscription"}
    messages = recorded(tmp_path)
    assert messages[0]["api_key_present"] is False
    assert messages[0]["cwd"] == str(tmp_path)
    starts = [m["params"] for m in messages if m.get("method") == "thread/start"]
    assert len(starts) == 1
    thread = starts[0]
    assert thread["model"] == "gpt-6-astra"
    assert thread["modelProvider"] == "openai"
    assert thread["sandbox"] == "read-only"
    assert thread["ephemeral"] is True
    assert thread["approvalPolicy"] == "never"
    assert thread["config"]["mcp_servers"]["fixture_mcp"]["enabled"] is False
    assert thread["config"]["features"]["hooks"] is False
    assert thread["config"]["features"]["apps"] is False
    turn = next(m["params"] for m in messages if m.get("method") == "turn/start")
    assert turn["model"] == "gpt-6-astra"
    transcript = json.loads(turn["input"][0]["text"])
    assert transcript == request()["input"]
    assert_reaped(tmp_path)
    adapter.close()


def test_count_is_local_estimate_includes_instruction_and_input_bytes(tmp_path):
    adapter = provider(tmp_path)
    short = adapter.count(request())
    long = adapter.count(request() | {"instructions": "🦊" * 1000})
    assert long > short > 0
    assert not (tmp_path / "peer.jsonl").exists()
    adapter.close()


def test_redacted_configuration_readback_is_not_reused_as_executable_config(tmp_path):
    adapter = provider(tmp_path, "redacted_config")
    assert adapter.generate(request())["status"] == "completed"
    assert_reaped(tmp_path)
    adapter.close()


@pytest.mark.parametrize("scenario,match", [
    ("api_account", "ChatGPT"), ("missing_model", "model"),
    ("changed_model", "model"), ("unsafe_sandbox", "sandbox"),
    ("malformed", "JSON"), ("exit", "closed"),
])
def test_fails_closed_before_turn_for_account_protocol_or_sandbox_error(tmp_path, scenario, match):
    from context_provider import ProviderError
    adapter = provider(tmp_path, scenario)
    with pytest.raises(ProviderError, match=match):
        adapter.generate(request())
    assert not any(m.get("method") == "turn/start" for m in recorded(tmp_path))
    assert_reaped(tmp_path)
    adapter.close()


@pytest.mark.parametrize("scenario", ["timeout", "stdout_flood", "stderr_flood"])
def test_process_time_and_both_output_streams_are_bounded_and_reaped(tmp_path, scenario, monkeypatch):
    import context_codex
    from context_provider import ProviderError
    monkeypatch.setattr(context_codex, "MAX_PROTOCOL_BYTES", 4096)
    monkeypatch.setattr(context_codex, "MAX_STDERR_BYTES", 4096)
    adapter = provider(tmp_path, scenario, timeout=0.4)
    started = time.monotonic()
    with pytest.raises(ProviderError, match="timeout|limit"):
        adapter.generate(request())
    assert time.monotonic() - started < 3
    assert_reaped(tmp_path)
    adapter.close()


@pytest.mark.parametrize("scenario", ["final_in_turn", "wrong_turn", "early_events"])
def test_final_event_collection_uses_active_turn_and_handles_embedded_items(tmp_path, scenario):
    adapter = provider(tmp_path, scenario)
    assert adapter.generate(request())["output"][0]["content"][0]["text"] == "Answer 🦊"
    assert_reaped(tmp_path)
    adapter.close()


def test_approval_is_declined_without_reexecuting_internal_call(tmp_path):
    adapter = provider(tmp_path, "approval")
    assert adapter.generate(request())["output"][0]["content"][0]["text"] == "Denied"
    assert any(m.get("id") == "approval-1" and m.get("result") == {"decision": "decline"} for m in recorded(tmp_path))
    assert_reaped(tmp_path)
    adapter.close()


def test_failed_turn_is_not_published_as_a_success(tmp_path):
    from context_provider import ProviderError
    adapter = provider(tmp_path, "failed_turn")
    with pytest.raises(ProviderError, match="failed") as caught:
        adapter.generate(request())
    assert "private error" not in str(caught.value)
    assert_reaped(tmp_path)
    adapter.close()


def test_dynamic_runtime_tools_are_rejected_before_starting_codex(tmp_path):
    from context_provider import ProviderError
    adapter = provider(tmp_path)
    with pytest.raises(ProviderError, match="tools"):
        adapter.generate(request() | {"tools": [{"type": "function", "name": "runtime_tool"}]})
    assert not (tmp_path / "peer.jsonl").exists()
    adapter.close()


def test_blocked_stdin_write_obeys_episode_deadline(tmp_path):
    from context_provider import ProviderError
    adapter = provider(tmp_path, "blocked_input", timeout=0.4)
    started = time.monotonic()
    with pytest.raises(ProviderError, match="timeout"):
        adapter.generate(request() | {"input": "x" * 500000})
    assert time.monotonic() - started < 3
    assert_reaped(tmp_path)
    adapter.close()


def test_codex_timeout_views_do_not_mutate_concurrent_episode_limits(tmp_path):
    from context_provider import ProviderError
    original = provider(tmp_path, "delayed", timeout=2)
    short, long = original.with_timeout(0.1), original.with_timeout(1)
    with ThreadPoolExecutor(2) as pool:
        short_job = pool.submit(short.generate, request())
        long_job = pool.submit(long.generate, request())
        with pytest.raises(ProviderError, match="timeout"):
            short_job.result()
        assert long_job.result()["status"] == "completed"
    assert original.timeout == 2
    assert short.with_timeout(10).timeout == 0.1
    for entry in recorded(tmp_path):
        if "pid" in entry:
            with pytest.raises(ProcessLookupError):
                os.kill(entry["pid"], 0)
    short.close()
    long.close()
    original.close()
