"""Tests for server.py's own silent session_registry stamp (Task 5).

Unlike tests/test_server.py's `server_env` fixture — which stubs module
globals directly and sets `_initialized = True` so `_init()` is a no-op —
this drives the real `server._init()` body against a temp ENGRAM_HOME, the
way tests/test_wake.py exercises the hook-side stamp. Heavy dependencies
(embeddings) are faked; everything else (Storage, Compressor, Reflector,
maintenance passes) runs for real against an empty temp DB.
"""

from __future__ import annotations

import math

import pytest

import server


class FakeEmbeddingProvider:
    """Deterministic, no model download — mirrors tests/test_server.py."""

    def __init__(self, dim: int = 768):
        self._dim = dim

    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str], **_kwargs) -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        import hashlib
        import random as _random

        h = hashlib.sha256(text.encode()).digest()
        rng = _random.Random(int.from_bytes(h[:8], "little"))
        vec = [rng.gauss(0, 1) for _ in range(self._dim)]
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec]


@pytest.fixture
def engram_server_env(tmp_path, monkeypatch):
    """Drive the real server._init() against a temp ENGRAM_HOME.

    Points ENGRAM_HOME/DB_PATH/PROJECT_ROOT at tmp_path, fakes the embedding
    provider (no model download), resets all module globals _init() writes
    to so it actually runs its full body (not skipped via `_initialized`),
    and never inherits harness/session env from the outer shell.
    """
    db_path = tmp_path / ".engram" / "graph.db"

    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("ENGRAM_HARNESS", raising=False)
    monkeypatch.delenv("ENGRAM_RUN_KEY", raising=False)

    monkeypatch.setattr(server, "ENGRAM_HOME", tmp_path)
    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("embeddings.NomicEmbedProvider", FakeEmbeddingProvider)

    monkeypatch.setattr(server, "_initialized", False)
    monkeypatch.setattr(server, "_storage", None)
    monkeypatch.setattr(server, "_embeddings", None)
    monkeypatch.setattr(server, "_config", None)
    monkeypatch.setattr(server, "_compressor", None)
    monkeypatch.setattr(server, "_reflector", None)
    monkeypatch.setattr(server, "_watcher", None)
    monkeypatch.setattr(server, "_session_id", None)
    monkeypatch.setattr(server, "_instance_name", None)
    monkeypatch.setattr(server, "_genome_db_path", None)
    monkeypatch.setattr(server, "_signals_db_path", None)
    monkeypatch.setattr(server, "_knowledge_graph", None)
    monkeypatch.setattr(server, "_category_store", None)
    monkeypatch.setattr(server, "_category_observer", None)
    monkeypatch.setattr(server, "_category_status", None)
    monkeypatch.setattr(server, "_category_atexit_callback", None)

    yield server

    if server._category_observer is not None:
        server._category_observer.close()
    if server._category_store is not None:
        server._category_store._conn.close()
    if server._storage is not None:
        server._storage.close()


def test_init_stamps_server_session(engram_server_env, monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    server._init()
    row = server._storage.conn.execute(
        "SELECT harness, model, repo FROM session_registry WHERE session_id = ?",
        (server._session_id,),
    ).fetchone()
    assert row is not None
    assert row["harness"] == "codex"
    assert row["model"] is None
    assert row["repo"]  # cwd recorded


def test_init_stamps_server_session_default_harness(engram_server_env):
    """Without ENGRAM_HARNESS set, the stamp defaults to claude-code."""
    server._init()
    row = server._storage.conn.execute(
        "SELECT harness, model, repo FROM session_registry WHERE session_id = ?",
        (server._session_id,),
    ).fetchone()
    assert row is not None
    assert row["harness"] == "claude-code"
    assert row["model"] is None
    assert row["repo"]


def _seed_bound_hook_row(server_module, run_key="codex:42", session_id="hook-session"):
    from storage import Storage

    db_path = server_module.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = Storage(str(db_path))
    store.stamp_session_registry(
        session_id, harness="codex", model="gpt-5.6-sol", repo=str(server_module.PROJECT_ROOT)
    )
    store.bind_session(run_key, session_id)
    store.close()


def test_codex_init_adopts_bound_hook_session(engram_server_env, monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:42")
    _seed_bound_hook_row(engram_server_env)
    engram_server_env._init()
    assert engram_server_env._session_id == "hook-session"
    row = engram_server_env._storage.conn.execute(
        "SELECT harness, model, repo FROM session_registry WHERE session_id = ?",
        (engram_server_env._session_id,),
    ).fetchone()
    assert tuple(row) == ("codex", "gpt-5.6-sol", str(engram_server_env.PROJECT_ROOT))

    result = engram_server_env.remember(
        "Bound Codex session provenance probe", work=True
    )
    episode = engram_server_env._storage.get_episode(result["episode_id"])
    assert episode["session_id"] == "hook-session"


def test_codex_init_without_binding_generates_uuid(engram_server_env, monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:missing")
    engram_server_env._init()
    assert engram_server_env._session_id != ""
    assert engram_server_env._session_id != "hook-session"

def test_codex_ignores_decoy_claude_session_id(engram_server_env, monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "decoy-claude")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:42")
    _seed_bound_hook_row(engram_server_env)
    engram_server_env._init()
    assert engram_server_env._session_id == "hook-session"


def test_claude_session_id_wins_over_inherited_run_key(engram_server_env, monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "claude-code")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:42")
    _seed_bound_hook_row(engram_server_env)
    engram_server_env._init()
    assert engram_server_env._session_id == "claude-session"
