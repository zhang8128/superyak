"""The shared embedder's client says how long it will wait (`remaining_ms`), so a request it has given up on is dropped
at the lane instead of embedded for nobody. The service side landed with train-1110 (test_embedder_deadline.py); this
is its client half (the Pi, 2026-11-09: a short text took 74 s behind abandoned requests)."""

from __future__ import annotations

import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from embedder_service import EmbedderServer, recv_message, send_message
from embeddings import EmbedderUnavailableError, RemoteEmbedProvider

from tests.test_embedder_lane import UnitProvider

MODEL = {"ok": True, "model": RemoteEmbedProvider.MODEL_NAME, "dimension": RemoteEmbedProvider.DIMENSION}


@pytest.fixture
def socket_dir():
    path = Path(tempfile.mkdtemp(prefix="client-deadline-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _recording_server(path, requests):
    """Answers `info`, then one `embed`, recording each request as it arrived."""
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen()

    def serve():
        with listener:
            for _ in range(2):
                conn, _ = listener.accept()
                with conn:
                    request = recv_message(conn)
                    requests.append(request)
                    texts = request.get("texts", [])
                    send_message(conn, {**MODEL, "vectors": [[0.0] * MODEL["dimension"] for _ in texts]})

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


@pytest.mark.parametrize("timeout, sent", [(None, 900_000), (10.0, 10_000), (0.25, 250)])
def test_the_embed_request_says_how_long_the_client_waits(socket_dir, timeout, sent):
    requests = []
    thread = _recording_server(socket_dir / "e.sock", requests)
    RemoteEmbedProvider(str(socket_dir / "e.sock"), response_timeout=timeout).embed(["x"])
    thread.join(5)
    info, embed = requests
    assert "remaining_ms" not in info  # info takes no lane
    assert embed["remaining_ms"] == pytest.approx(sent)


def test_a_client_that_gave_up_costs_the_lane_nothing(socket_dir):
    """A batch holds the lane; a client with a short timeout queues behind it and gives up. When the lane frees, the
    service drops that request without embedding it, and the next request runs."""
    provider = UnitProvider(unit_size=1)
    provider.gate = threading.Event()
    path = socket_dir / "e.sock"
    server = EmbedderServer(path, provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        first = []
        batch = threading.Thread(target=lambda: first.append(RemoteEmbedProvider(str(path)).embed(["a", "b"])),
                                 daemon=True)
        batch.start()
        assert provider.entered.wait(5)  # the batch's first unit holds the lane

        with pytest.raises(EmbedderUnavailableError, match="timed out"):
            RemoteEmbedProvider(str(path), response_timeout=0.2).embed(["abandoned"])
        time.sleep(0.3)  # past its deadline by the service's own clock too, whatever its arrival stamp
        after = []
        follow = threading.Thread(target=lambda: after.append(RemoteEmbedProvider(str(path)).embed(["after"])),
                                  daemon=True)
        follow.start()

        provider.gate.set()
        batch.join(10)
        follow.join(10)
        assert first and after  # both live requests were answered
        embedded = [text for texts, _prefix in provider.calls for text in texts]
        assert "abandoned" not in embedded
        assert "after" in embedded
    finally:
        provider.gate.set()
        server.shutdown()
        server.server_close()
