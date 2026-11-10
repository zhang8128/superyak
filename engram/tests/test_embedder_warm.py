"""The shared embedder loads its model at start when it keeps it, says whether it is loaded, and logs that on a drop."""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

from embedder_service import EmbedderServer, WARM_TEXT, recv_message, send_message
from embeddings import RemoteEmbedProvider


class LazyProvider:
    MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
    DIMENSION = 768

    def __init__(self, idle_seconds, fail=False):
        self._idle_seconds = idle_seconds
        self.fail = fail
        self.loaded = False
        self.calls = []

    def is_loaded(self):
        return self.loaded

    def dimension(self):
        return self.DIMENSION

    def embed(self, texts, *, prefix="search_document"):
        self.calls.append((list(texts), prefix))
        if self.fail:
            raise RuntimeError("no model")
        self.loaded = True
        return [[0.0] * self.DIMENSION for _ in texts]


@pytest.fixture
def server_for():
    made = []

    def make(provider):
        d = Path(tempfile.mkdtemp(prefix="emb-", dir="/tmp"))
        server = EmbedderServer(d / "e.sock", provider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        made.append((server, d))
        return server, d / "e.sock"

    yield make
    for server, d in made:
        server.shutdown()
        server.server_close()
        shutil.rmtree(d, ignore_errors=True)


def _call(sock_path, request):
    import socket

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(sock_path))
        send_message(s, request)
        return recv_message(s)


def test_kept_model_loads_at_start(server_for):
    provider = LazyProvider(0)
    server, _ = server_for(provider)
    thread = server.warm_in_background()
    thread.join(5)
    assert provider.loaded and provider.calls == [([WARM_TEXT], "search_query")]


def test_other_idle_settings_do_not_warm(server_for):
    provider = LazyProvider(300.0)
    server, _ = server_for(provider)
    assert server.warm_in_background() is None
    assert not provider.loaded and provider.calls == []


def test_warm_failure_is_logged_and_the_service_lives(server_for, caplog):
    provider = LazyProvider(0, fail=True)
    server, sock = server_for(provider)
    with caplog.at_level(logging.INFO, logger="engram.embedder"):
        server.warm_in_background().join(5)
    assert "warming the model failed" in caplog.text
    assert _call(sock, {"op": "info"})["ok"] is True
    provider.fail = False
    assert _call(sock, {"op": "embed", "texts": ["x"]})["ok"] is True


def test_info_says_whether_loaded(server_for):
    provider = LazyProvider(0)
    _, sock = server_for(provider)
    assert _call(sock, {"op": "info"})["loaded"] is False
    provider.embed(["x"])
    assert _call(sock, {"op": "info"})["loaded"] is True


def test_info_omits_loaded_for_a_provider_that_cannot_say(server_for):
    provider = LazyProvider(0)
    provider.is_loaded = None
    _, sock = server_for(provider)
    assert "loaded" not in _call(sock, {"op": "info"})


def test_client_check_model_ignores_loaded(server_for):
    _, sock = server_for(LazyProvider(0))
    remote = RemoteEmbedProvider(str(sock))
    remote._check_model(_call(sock, {"op": "info"}))
    assert len(remote.embed(["x"])) == 1


@pytest.mark.parametrize("loaded, words", [(True, "model loaded when it arrived"), (False, "model not loaded when it arrived")])
def test_expiry_log_says_whether_loaded(server_for, caplog, loaded, words):
    provider = LazyProvider(0)
    provider.loaded = loaded
    _, sock = server_for(provider)
    with caplog.at_level(logging.INFO, logger="engram.embedder"):
        assert _call(sock, {"op": "embed", "texts": ["x"], "remaining_ms": 0})["error"] == "expired"
    lines = [r.getMessage() for r in caplog.records if "dropped an expired" in r.getMessage()]
    assert len(lines) == 1 and words in lines[0]
