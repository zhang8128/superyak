"""Nudge/sleep harness integration: session_id sourcing + output contract."""
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_HOOKS = Path(__file__).resolve().parent.parent / "hooks"
MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _HOOKS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_sleep(project_dir: str, extra_env: dict | None = None,
               stdin: str = "") -> subprocess.CompletedProcess:
    """Run sleep.py as a subprocess, mirroring test_wake.py's
    `_run_wake_raw` pattern: env vars go through `extra_env`, stdin is
    always passed explicitly so the harness's stdin read never blocks."""
    env = {**os.environ, "ENGRAM_HOME": project_dir}
    env.pop("CLAUDE_SESSION_ID", None)  # never inherit from the outer shell
    env.pop("ENGRAM_HARNESS", None)  # never inherit from the outer shell
    env.pop("ENGRAM_WAKE", None)  # never inherit from the outer shell
    env.pop("CODEX_PAIR_SESSION_ID", None)  # never inherit from the outer shell
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(_HOOKS / "sleep.py")],
        capture_output=True, text=True, env=env, input=stdin, timeout=10,
    )


def _seed_episodes(tmp_path, n=5) -> Path:
    """Build a migrated graph.db under tmp_path/.engram with `n` episodes
    carrying embeddings (episodes + episode_vectors), so sleep.py has
    vectors to dream from. Mirrors test_wake.py's `_seed_db` helper, plus
    the episode/embedding seeding `Storage.add_episode` already does for
    the compression/cluster test suites."""
    from storage import Storage
    db_dir = tmp_path / ".engram"
    db_dir.mkdir()
    db_path = db_dir / "graph.db"
    store = Storage(str(db_path), migrations_dir=MIGRATIONS_DIR)
    for i in range(n):
        store.add_episode(
            id=f"ep-{i}", session_id=None,
            content=f"some episode content number {i} with a few words",
            embedding=[0.1] * 768,
        )
    store.close()
    return db_path


def test_nudge_codex_skips_for_pair_child(tmp_path, monkeypatch, capsys):
    # Isolate from the real (live) engram store — even before the fix
    # lands, ENGRAM_HOME pointed at an empty tmp_path means nudge()'s
    # `if not db_path.exists(): return` guard fires safely if the skip
    # check itself isn't reached yet.
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    monkeypatch.setenv("ENGRAM_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("CODEX_PAIR_SESSION_ID", "parent")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "session_id": "cx1", "hook_event_name": "UserPromptSubmit",
        "prompt": "anything at all",
    })))
    nudge = _load("nudge")
    nudge.nudge()
    assert capsys.readouterr().out == ""


def test_sleep_codex_uses_payload_session_id(tmp_path):
    # Arrange a minimal graph.db via Storage so sleep can dream from it,
    # then verify residues carry the codex session_id, not CLAUDE env.
    db_path = _seed_episodes(tmp_path)

    stdin = json.dumps({
        "session_id": "codex-sleep-sess", "hook_event_name": "Stop",
    })
    result = _run_sleep(
        str(tmp_path),
        extra_env={
            "ENGRAM_HARNESS": "codex",
            "CLAUDE_SESSION_ID": "decoy-claude-sess",
        },
        stdin=stdin,
    )
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT session_id FROM residue ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row[0] == "codex-sleep-sess"


def test_sleep_extension_load_failure_closes_connection(
    tmp_path, monkeypatch, capsys,
):
    import types

    sleep = _load("sleep")
    db_path = tmp_path / ".engram" / "graph.db"
    db_path.parent.mkdir()
    db_path.touch()
    monkeypatch.setattr(sleep, "ENGRAM_HOME", tmp_path)
    monkeypatch.setattr(sleep, "DB_PATH", db_path)
    monkeypatch.setattr(sleep, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:42")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "session_id": "codex-hook-session", "hook_event_name": "Stop",
    })))

    class FakeConnection:
        def __init__(self):
            self.closed = False
            self.row_factory = None

        def execute(self, *_args, **_kwargs):
            return self

        def enable_load_extension(self, _enabled):
            pass

        def commit(self):
            pass

        def close(self):
            self.closed = True

    conn = FakeConnection()
    monkeypatch.setattr(sleep.sqlite3, "connect", lambda _path: conn)
    monkeypatch.setitem(sys.modules, "sqlite_vec", types.SimpleNamespace(
        load=lambda _conn: (_ for _ in ()).throw(RuntimeError("load failed"))
    ))

    sleep.sleep()

    assert conn.closed is True
    assert capsys.readouterr().out == ""


def test_sleep_clears_runtime_binding(tmp_path):
    db_path = _seed_episodes(tmp_path)
    from storage import Storage

    store = Storage(str(db_path), migrations_dir=MIGRATIONS_DIR)
    store.bind_session("codex:42", "codex-sleep-sess")
    store.close()

    result = _run_sleep(
        str(tmp_path),
        extra_env={
            "ENGRAM_HARNESS": "codex",
            "ENGRAM_RUN_KEY": "codex:42",
        },
        stdin=json.dumps({
            "session_id": "codex-sleep-sess", "hook_event_name": "Stop",
        }),
    )
    assert result.returncode == 0, result.stderr
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT session_id FROM session_bindings WHERE run_key = 'codex:42'"
    ).fetchone()
    conn.close()
    assert row is None
