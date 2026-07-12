"""Harness adapter: explicit shim selection, payload parsing, output contracts.

Codex clones Claude Code's hook payload format field-for-field (probe
2026-07-11), so selection is env-explicit — never sniffed from shape.
"""
import importlib.util
import io
import json
import sqlite3
from pathlib import Path

import pytest

_HOOKS = Path(__file__).resolve().parent.parent / "hooks"
_spec = importlib.util.spec_from_file_location("harness", _HOOKS / "harness.py")
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)

CODEX_PAYLOAD = {
    "session_id": "019f53e8-2d7b-7e40-b8bd-e24534d56bdb",
    "transcript_path": "/tmp/rollout.jsonl",
    "cwd": "/tmp/somerepo",
    "hook_event_name": "SessionStart",
    "model": "gpt-5.6-sol",
    "permission_mode": "bypassPermissions",
    "source": "startup",
}


def _fake_stdin(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload) if payload else ""))


def test_default_harness_is_claude(monkeypatch):
    monkeypatch.delenv("ENGRAM_HARNESS", raising=False)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-sess-1")
    _fake_stdin(monkeypatch, {})
    ctx = harness.read_context()
    assert ctx["harness"] == harness.CLAUDE
    assert ctx["session_id"] == "claude-sess-1"
    assert ctx["skip"] is False


def test_codex_reads_payload_not_claude_env(monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    # CLAUDE_* env leaks into codex children — must be ignored:
    monkeypatch.setenv("CLAUDE_SESSION_ID", "leaked-claude-sess")
    monkeypatch.delenv("CODEX_PAIR_SESSION_ID", raising=False)
    _fake_stdin(monkeypatch, CODEX_PAYLOAD)
    ctx = harness.read_context()
    assert ctx["harness"] == harness.CODEX
    assert ctx["session_id"] == CODEX_PAYLOAD["session_id"]
    assert ctx["model"] == "gpt-5.6-sol"
    assert ctx["cwd"] == "/tmp/somerepo"
    assert ctx["event"] == "SessionStart"


def test_codex_pair_child_skips(monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("CODEX_PAIR_SESSION_ID", "some-claude-session")
    _fake_stdin(monkeypatch, CODEX_PAYLOAD)
    assert harness.read_context()["skip"] is True


def test_engram_wake_skip_any_harness(monkeypatch):
    monkeypatch.delenv("ENGRAM_HARNESS", raising=False)
    monkeypatch.setenv("ENGRAM_WAKE", "skip")
    _fake_stdin(monkeypatch, {})
    assert harness.read_context()["skip"] is True


def test_claude_pair_env_does_not_skip_claude(monkeypatch):
    # CODEX_PAIR_SESSION_ID is set in the *Claude* session too — must only
    # gate the codex shim, or Claude wake dies whenever codex-pair is loaded.
    monkeypatch.delenv("ENGRAM_HARNESS", raising=False)
    monkeypatch.delenv("ENGRAM_WAKE", raising=False)
    monkeypatch.setenv("CODEX_PAIR_SESSION_ID", "some-claude-session")
    _fake_stdin(monkeypatch, {})
    assert harness.read_context()["skip"] is False


def test_malformed_stdin_degrades(monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.delenv("CODEX_PAIR_SESSION_ID", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json {"))
    ctx = harness.read_context()
    assert ctx["session_id"] == ""
    assert ctx["skip"] is False  # provenance degrades; wake still happens


def test_emit_claude_is_envelope(monkeypatch, capsys):
    harness.emit(harness.CLAUDE, "SessionStart", "hello")
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "hello"
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert out["hookSpecificOutput"]["additionalContext"] == "hello"


def test_emit_codex_is_plain_text_never_json(capsys):
    harness.emit(harness.CODEX, "SessionStart", "orientation text")
    out = capsys.readouterr().out
    assert out == "orientation text"
    with pytest.raises(ValueError):
        json.loads(out)  # MUST not parse as JSON — Codex treats JSON as control flow


def test_emit_empty_writes_nothing(capsys):
    harness.emit(harness.CODEX, "SessionStart", "")
    assert capsys.readouterr().out == ""


def test_stamp_registry_upserts_and_tolerates_missing_table(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    ctx = {"session_id": "s1", "harness": "codex", "model": "gpt-5.6-sol", "cwd": "/r"}
    harness.stamp_registry(conn, ctx)  # no table yet — must not raise
    conn.execute(
        "CREATE TABLE session_registry (session_id TEXT PRIMARY KEY, harness TEXT,"
        " model TEXT, repo TEXT, started_at TEXT NOT NULL)"
    )
    harness.stamp_registry(conn, ctx)
    harness.stamp_registry(conn, {"session_id": "s1", "harness": "codex", "model": None, "cwd": "/other"})
    row = conn.execute("SELECT model, repo FROM session_registry WHERE session_id='s1'").fetchone()
    assert row == ("gpt-5.6-sol", "/r")  # merge never clobbers
    harness.stamp_registry(conn, {"session_id": "", "harness": "codex", "model": None, "cwd": None})
    assert conn.execute("SELECT COUNT(*) FROM session_registry").fetchone()[0] == 1
