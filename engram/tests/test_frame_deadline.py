"""A recall frame says how long its asker waits (spec docs/superpowers/specs/2026-11-10-a-recall-frame-says-how-long-
its-asker-waits-design.md): an optional `remainingMs` on recall frames, set by the clients that talk to a daemon,
passed by the publisher to its embed and clamped there to the publisher's own timeout. The peer's half is in
peer/tests/test_crossing_route.py."""

from __future__ import annotations

import json
import logging
import shutil
import socket
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import pytest

from embedder_service import EmbedderServer, recv_message, send_message
from embeddings import EmbedderExpired, EmbedderUnavailableError, RemoteEmbedProvider
from lighthouse_client import LighthouseClient, NeighborUnavailable
from lighthouse_daemon import PublisherDaemon
from lighthouse_protocol import FrameError, recall_frame, read_frame, validate_frame

from tests.test_embedder_lane import UnitProvider
from tests.test_lighthouse_daemon import CONTEXT, NOW, FakeEmbeddings, build_publisher

MODEL = {"ok": True, "model": RemoteEmbedProvider.MODEL_NAME, "dimension": RemoteEmbedProvider.DIMENSION}


@pytest.fixture
def socket_dir():
    path = Path(tempfile.mkdtemp(prefix="frame-deadline-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _recall(**extra):
    return {**recall_frame(receiver="engram", publisher="why", context=CONTEXT, purpose="session-recall",
                           query="shared: rivers need bridges", k=5, at=NOW), **extra}


class Recorder:
    """A shared embedder that records each request, answers each at once, and serves connections in parallel."""

    def __init__(self, path, answer=True):
        self.requests, self.accepted, self._answer = [], 0, answer
        self._lock = threading.Lock()
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(str(path))
        self._listener.listen(16)
        self._listener.settimeout(0.1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except (TimeoutError, OSError):
                continue
            with self._lock:
                self.accepted += 1
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn):
        with conn:
            request = recv_message(conn)
            with self._lock:
                self.requests.append(request)
            if not self._answer:
                self._stop.wait(10)
                return
            if request.get("op") == "embed" and request.get("texts", [""])[0].startswith("slow"):
                time.sleep(0.2)  # so two concurrent embeds overlap
            send_message(conn, {**MODEL, "vectors": [[0.0] * MODEL["dimension"] for _ in request.get("texts", [])]})

    def embeds(self):
        return [r for r in self.requests if r.get("op") == "embed"]

    def close(self):
        self._stop.set()
        self._thread.join(5)
        self._listener.close()


# Section 2: the field and its validator.

@pytest.mark.parametrize("value", [0, 5, 2.5, 10**300, 1e300])
def test_a_recall_takes_a_finite_non_negative_number(value):
    validate_frame(_recall(remainingMs=value))


@pytest.mark.parametrize("value", [-1, -0.5, float("nan"), float("inf"), "5", True, False, None, [5], 10**400])
def test_anything_else_is_malformed(value):
    with pytest.raises(FrameError) as error:
        validate_frame(_recall(remainingMs=value))
    assert error.value.code == "MALFORMED_FRAME"


def test_a_read_ignores_the_field():
    frame = read_frame(receiver="engram", publisher="why", context=CONTEXT, purpose="session-recall",
                       turn_id="turn-1", memory_ids=["m1"])
    validate_frame({**frame, "remainingMs": "anything"})


# Section 3: the local client sets it.

@pytest.mark.parametrize("value", [-1, float("nan"), 10**400, True])
def test_the_client_refuses_its_callers_bad_value_before_connecting(socket_dir, value):
    with pytest.raises(NeighborUnavailable) as error:
        LighthouseClient(socket_dir / "absent.sock").call(_recall(remainingMs=value))
    assert error.value.code == "MALFORMED_FRAME"  # not UNAVAILABLE: it never tried the socket


def _sent_by_client(socket_dir, frame, **call):
    path, seen = socket_dir / "lh.sock", []
    path.unlink(missing_ok=True)  # each call binds afresh
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)

    def serve():
        with listener.accept()[0] as conn:
            data = bytearray()
            while not data.endswith(b"\n"):
                data += conn.recv(65536)
            seen.append(json.loads(data))

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    with pytest.raises(NeighborUnavailable):  # nobody answers; only the request is looked at
        LighthouseClient(path, timeout_s=0.5).call(frame, **call)
    thread.join(5)
    listener.close()
    return seen[0]


def test_the_client_never_sends_more_than_its_deadline_or_its_callers_value(socket_dir):
    soon = _sent_by_client(socket_dir, _recall(), deadline=time.monotonic() + 0.2)
    assert type(soon["remainingMs"]) is int and 0 < soon["remainingMs"] <= 200
    smaller = _sent_by_client(socket_dir, _recall(remainingMs=50))
    assert smaller["remainingMs"] == 50


# Section 4: the clamp, per call, in the embedder client.

@pytest.mark.parametrize("given, sent", [(150, 150), (1e9, 900_000), (1e300, 900_000), (None, 900_000)])
def test_the_asker_can_shorten_the_embed_never_lengthen_it(socket_dir, given, sent):
    recorder = Recorder(socket_dir / "e.sock")
    try:
        RemoteEmbedProvider(str(socket_dir / "e.sock")).embed(["x"], prefix="search_query", remaining_ms=given)
    finally:
        recorder.close()
    [embed] = recorder.embeds()
    assert 0 < embed["remaining_ms"] <= sent and embed["remaining_ms"] > sent - 100  # less only by the info call


@pytest.mark.parametrize("left", [0, -5, float("nan")])  # NaN: no wait can come from it, and a socket refuses it
def test_nothing_left_raises_without_connecting(socket_dir, left):
    recorder = Recorder(socket_dir / "e.sock")
    try:
        with pytest.raises(EmbedderExpired, match="before the shared embedder was asked"):
            RemoteEmbedProvider(str(socket_dir / "e.sock")).embed(["x"], remaining_ms=left)
    finally:
        recorder.close()
    assert recorder.accepted == 0


def test_two_concurrent_embeds_keep_their_own_deadlines(socket_dir):
    recorder = Recorder(socket_dir / "e.sock")
    provider = RemoteEmbedProvider(str(socket_dir / "e.sock"))
    provider.embed(["warm"])  # the model check, once
    try:
        threads = [threading.Thread(target=provider.embed, args=([f"slow {ms}"],), kwargs={"remaining_ms": ms})
                   for ms in (3_000, 60_000)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
    finally:
        recorder.close()
    sent = {r["texts"][0]: r["remaining_ms"] for r in recorder.embeds() if r["texts"][0].startswith("slow")}
    assert 2_900 < sent["slow 3000"] <= 3_000 and 59_900 < sent["slow 60000"] <= 60_000
    assert provider._response_timeout == RemoteEmbedProvider.RESPONSE_TIMEOUT  # nothing was written to the instance


def test_a_timeout_is_an_expiry_only_when_the_askers_time_set_it(socket_dir):
    recorder = Recorder(socket_dir / "e.sock", answer=False)  # never answers
    try:
        with pytest.raises(EmbedderExpired):
            RemoteEmbedProvider(str(socket_dir / "e.sock"), response_timeout=5).embed(["x"], remaining_ms=200)
        with pytest.raises(EmbedderUnavailableError) as own:
            RemoteEmbedProvider(str(socket_dir / "e.sock"), response_timeout=0.2).embed(["x"], remaining_ms=5_000)
        assert not isinstance(own.value, EmbedderExpired)  # the publisher's own timeout: today's plain failure
    finally:
        recorder.close()


# Sections 4 and 6: the publisher, end to end.

def test_an_expired_recall_costs_the_lane_nothing_and_writes_no_disclosure(tmp_path, socket_dir, caplog, monkeypatch):
    """A batch holds the embedder's lane on a gate; a recall with 200 ms left queues behind it. Its deadline passes,
    so it is answered PUBLISHER_UNAVAILABLE "the asker's deadline passed", logged at info with no traceback; it writes
    no disclosure and its ledger side closes. When the lane frees, the service drops its query without embedding it,
    and a live request still runs."""
    provider = UnitProvider(unit_size=1)
    provider.gate = threading.Event()
    path = socket_dir / "e.sock"
    server = EmbedderServer(path, provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    caplog.set_level(logging.INFO)
    pub = build_publisher(tmp_path)
    daemon = PublisherDaemon({"why": pub}, tmp_path / "s.sock", RemoteEmbedProvider(str(path)))
    closed = []

    class Side:  # stands in for the ledger side, which holds a _frames slot until it closes
        def recall_set(self):
            return None

        def close(self):
            closed.append(True)

    monkeypatch.setattr(daemon, "_ledger_side", lambda *args: (Side(), False))
    try:
        batch = threading.Thread(target=lambda: RemoteEmbedProvider(str(path)).embed(["a", "b"]), daemon=True)
        batch.start()
        assert provider.entered.wait(30)  # the batch's first unit holds the lane
        daemon.embeddings._verified = True  # its model check would wait behind nothing; keep the test about the embed

        answer = daemon.handle_frame(_recall(remainingMs=200))
        assert answer["kind"] == "error"
        assert (answer["code"], answer["detail"]) == ("PUBLISHER_UNAVAILABLE", "the asker's deadline passed")
        assert closed == [True]
        assert not pub.disclosures_path.exists() or sqlite3.connect(pub.disclosures_path).execute(
            "SELECT COUNT(*) FROM disclosures").fetchone()[0] == 0
        expiry = [r for r in caplog.records if r.getMessage().startswith("dropped an expired recall")]
        assert len(expiry) == 1 and expiry[0].levelno == logging.INFO and expiry[0].exc_info is None

        time.sleep(0.1)  # by the service's own clock too
        provider.gate.set()
        batch.join(30)
        assert RemoteEmbedProvider(str(path)).embed(["after"])
        embedded = [text for texts, _prefix in provider.calls for text in texts]
        assert "shared: rivers need bridges" not in embedded and "after" in embedded
        assert any(r.getMessage().startswith("dropped an expired query request") for r in caplog.records)
    finally:
        provider.gate.set()
        server.shutdown()
        server.server_close()


def test_a_publisher_with_its_model_in_process_serves_the_field_as_before(tmp_path):
    """FakeEmbeddings.embed takes no remaining_ms: a keyword passed to it would fail the frame."""
    pub = build_publisher(tmp_path)
    daemon = PublisherDaemon({"why": pub}, tmp_path / "s.sock", FakeEmbeddings())
    out = daemon.handle_frame(_recall(remainingMs=5))
    assert out["decision"]["effect"] == "allow" and len(out["candidates"]) == 1
