"""Tests for the shared embedding service and its client."""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
import threading
from pathlib import Path

import pytest

import embeddings
from embedder_service import EmbedderServer, recv_message, send_message
from embeddings import EmbedderUnavailableError, RemoteEmbedProvider, create_embedding_provider


class FakeProvider:
    MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
    DIMENSION = 768

    def __init__(self):
        self.calls = []

    def dimension(self):
        return self.DIMENSION

    def embed(self, texts, *, prefix="search_document"):
        self.calls.append((list(texts), prefix))
        return [[float(len(t)), 0.1 + i] + [0.0] * (self.DIMENSION - 2) for i, t in enumerate(texts)]


@pytest.fixture
def socket_dir():
    # AF_UNIX paths are limited to ~108 bytes; pytest's tmp_path can exceed that.
    path = Path(tempfile.mkdtemp(prefix="emb-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _serve(socket_path: Path, provider) -> EmbedderServer:
    server = EmbedderServer(socket_path, provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_remote_round_trip_matches_provider_output(socket_dir):
    provider = FakeProvider()
    server = _serve(socket_dir / "e.sock", provider)
    try:
        remote = RemoteEmbedProvider(str(socket_dir / "e.sock"))
        vectors = remote.embed(["ab", "abcd"], prefix="clustering")
        assert vectors == provider.embed(["ab", "abcd"])
        assert provider.calls[0] == (["ab", "abcd"], "clustering")
        assert remote.dimension() == 768
        assert remote.embed([]) == []
    finally:
        server.shutdown()
        server.server_close()


def test_socket_is_private_to_the_user(socket_dir):
    server = _serve(socket_dir / "e.sock", FakeProvider())
    try:
        assert (socket_dir / "e.sock").stat().st_mode & 0o077 == 0
    finally:
        server.shutdown()
        server.server_close()


def test_model_mismatch_is_refused(socket_dir):
    class OtherModel(FakeProvider):
        MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

    server = _serve(socket_dir / "e.sock", OtherModel())
    try:
        with pytest.raises(EmbedderUnavailableError, match="expected"):
            RemoteEmbedProvider(str(socket_dir / "e.sock")).embed(["x"])
    finally:
        server.shutdown()
        server.server_close()


def test_unavailable_service_fails_loudly(socket_dir):
    with pytest.raises(EmbedderUnavailableError, match="unavailable"):
        RemoteEmbedProvider(str(socket_dir / "missing.sock")).embed(["x"])


def test_malformed_requests_get_errors_not_crashes(socket_dir):
    server = _serve(socket_dir / "e.sock", FakeProvider())
    try:
        for request in ({"op": "nope"}, {"op": "embed", "texts": "x"}, {"op": "embed", "texts": ["x"] * 5000}):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.connect(str(socket_dir / "e.sock"))
                send_message(sock, request)
                assert recv_message(sock)["ok"] is False
        # Still serving after the bad requests.
        assert RemoteEmbedProvider(str(socket_dir / "e.sock")).embed(["ok"])
    finally:
        server.shutdown()
        server.server_close()


def test_factory_selects_remote_only_when_socket_configured(monkeypatch):
    monkeypatch.setenv("ENGRAM_EMBEDDER_SOCKET", "/tmp/somewhere.sock")
    assert isinstance(create_embedding_provider(), RemoteEmbedProvider)
    monkeypatch.delenv("ENGRAM_EMBEDDER_SOCKET")
    monkeypatch.setattr(embeddings, "NomicEmbedProvider", FakeProvider)
    assert isinstance(create_embedding_provider(), FakeProvider)
