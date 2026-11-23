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
try:
    from session_bindings import valid_codex_run_key
except ImportError:
    import re
    def valid_codex_run_key(value):
        return value if isinstance(value, str) and re.fullmatch(r"^codex:[0-9]+$", value) else None


_INSTANCE_NAME = None


def instance_name(*candidates):
    """The first candidate that is a plain instance name, or None. A hook reads the name from the config of the
    folder the session starts in and from the environment; either could hold a path, and a path can leave the Engram
    home. The pattern is config.INSTANCE_NAME."""
    global _INSTANCE_NAME
    if _INSTANCE_NAME is None:
        import re
        _INSTANCE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
    for candidate in candidates:
        if isinstance(candidate, str) and _INSTANCE_NAME.fullmatch(candidate):
            return candidate
    return None


PASSED_OVER = ("this folder's Engram config names an instance that is not a plain name (1 to 64 letters, digits, - "
               "or _), so it was passed over")


def default_instance():
    """ENGRAM_DEFAULT_INSTANCE when it is a plain name, with the spaces around it removed as the server removes them.
    One that is set and is not a plain name is passed over, and stderr says so."""
    raw = (os.environ.get("ENGRAM_DEFAULT_INSTANCE") or "").strip()
    name = instance_name(raw)
    if raw and name is None:
        print("# engram: ENGRAM_DEFAULT_INSTANCE is not a plain name, so it was passed over", file=sys.stderr)
    return name


def binding(project_value, default):
    """The instance a hook uses: the project's binding when it is a plain name, else ``default``. With it, a sentence
    when the project's binding was passed over, else None, and stderr gets that sentence too. It never repeats what
    the folder wrote. A session that quietly used another store than its folder asked for would keep doing so, so
    the hooks say it (the fix's reader, finding 1)."""
    name = instance_name(project_value)
    if name is not None:
        return name, None
    if not project_value:
        return default, None
    print(f"# engram: {PASSED_OVER}", file=sys.stderr)
    return default, PASSED_OVER


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
    run_key = valid_codex_run_key(ctx.get("run_key"))
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
    run_key = valid_codex_run_key(ctx.get("run_key"))
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
