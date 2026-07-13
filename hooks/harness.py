#!/usr/bin/env python3
"""Harness adapter — one orientation logic, two harness I/O contracts.

Claude Code and Codex CLI both deliver hook payloads as JSON on stdin in
the SAME format (Codex cloned Claude Code's hooks API — probe-verified
2026-07-11). Because the shapes are indistinguishable, the shim is
selected EXPLICITLY via ENGRAM_HARNESS in the registered command line,
never sniffed.

Output contracts differ:
- claude-code: JSON envelope (systemMessage + hookSpecificOutput).
- codex: plain stdout. NEVER JSON — Codex parses JSON stdout as control
  flow ({"continue": false} kills the session).

Spec: docs/superpowers/specs/2026-07-11-engram-codex-hooks-design.md
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

CLAUDE = "claude-code"
CODEX = "codex"


def read_context() -> dict:
    """Parse harness selection + hook payload into one dict.

    Never raises: a malformed payload degrades to empty provenance fields.
    Orientation must still happen — provenance is optional, wake is not.
    """
    harness = os.environ.get("ENGRAM_HARNESS", CLAUDE)

    raw = ""
    try:
        if not sys.stdin.isatty():  # manual runs keep working
            raw = sys.stdin.read()
    except Exception:
        pass
    try:
        payload = json.loads(raw) if raw and raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except ValueError:
        payload = {}

    if harness == CODEX:
        # Never read CLAUDE_* env here: a codex child spawned from a
        # Claude session inherits them (probe-observed leak).
        session_id = payload.get("session_id") or ""
    else:
        session_id = os.environ.get("CLAUDE_SESSION_ID") or payload.get("session_id") or ""

    skip = os.environ.get("ENGRAM_WAKE", "").lower() == "skip"
    if harness == CODEX and os.environ.get("CODEX_PAIR_SESSION_ID"):
        # codex-pair review child — reviews stay lean (spec decision 4).
        skip = True

    return {
        "harness": harness,
        "session_id": session_id,
        "run_key": os.environ.get("ENGRAM_RUN_KEY") if harness == CODEX else None,
        "model": payload.get("model"),
        "cwd": payload.get("cwd") or os.getcwd(),
        "prompt": payload.get("prompt"),
        "event": payload.get("hook_event_name"),
        "skip": skip,
    }


def emit(harness: str, event: str, text: str) -> None:
    """Write hook output to stdout in the harness's contract."""
    if not text:
        return
    if harness == CODEX:
        sys.stdout.write(text)
        return
    json.dump(
        {
            "systemMessage": text,
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": text,
            },
        },
        sys.stdout,
    )


def stamp_registry(conn, ctx: dict) -> None:
    """Upsert silent provenance (raw-sqlite twin of
    Storage.stamp_session_registry). COALESCE-merge; started_at is kept
    from the first stamp. No-op without a session_id or before migration
    023 — provenance is never a gate."""
    if not ctx.get("session_id"):
        return
    try:
        conn.execute(
            "INSERT INTO session_registry (session_id, harness, model, repo, started_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "harness = COALESCE(session_registry.harness, excluded.harness), "
            "model = COALESCE(session_registry.model, excluded.model), "
            "repo = COALESCE(session_registry.repo, excluded.repo)",
            (ctx["session_id"], ctx.get("harness"), ctx.get("model"),
             ctx.get("cwd"), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except sqlite3.Error:
        # Not just OperationalError: bad payloads raise InterfaceError/
        # ProgrammingError and must not gate either ("provenance is never a gate").
        pass


def bind_session(conn, ctx: dict) -> None:
    run_key = ctx.get("run_key")
    session_id = ctx.get("session_id")
    if not run_key or not session_id:
        return
    try:
        conn.execute(
            "INSERT INTO session_bindings (run_key, session_id, bound_at) "
            "VALUES (?, ?, ?) ON CONFLICT(run_key) DO UPDATE SET "
            "session_id = excluded.session_id, bound_at = excluded.bound_at",
            (run_key, session_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except sqlite3.Error:
        pass


def clear_session_binding(conn, ctx: dict) -> None:
    run_key = ctx.get("run_key")
    session_id = ctx.get("session_id")
    if not run_key:
        return
    try:
        conn.execute(
            "DELETE FROM session_bindings WHERE run_key = ? AND session_id = ?",
            (run_key, session_id),
        )
        conn.commit()
    except sqlite3.Error:
        pass
