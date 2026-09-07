"""Tests for Task 6: time visible in working surfaces — recall `when` field.

Everything engram stores already carries created_at; this makes it visible
on recall hits. Uses the same real-`_init()` fixture pattern as
tests/test_server_registry.py (`engram_server_env`) rather than the
lighter `server_env` stub in tests/test_server.py, so an episode written
and recalled in the same test round-trips through the real storage layer.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

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

    Mirrors tests/test_server_registry.py's fixture of the same name.
    """
    db_path = tmp_path / ".engram" / "graph.db"

    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("ENGRAM_HARNESS", raising=False)

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

    yield server

    if server._storage is not None:
        server._storage.close()


def test_recall_results_carry_when(engram_server_env):
    # Store an episode, recall it, expect a compact date on the hit.
    server.remember(content="the sky over Barima-Waini")
    out = server.recall(query="sky Barima", uninvited=0)
    hits = [r for r in out["results"] if "sky over Barima" in r["content"]]
    assert hits and hits[0]["when"] == datetime.now(timezone.utc).isoformat()[:10]
