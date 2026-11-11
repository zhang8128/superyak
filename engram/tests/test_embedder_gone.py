"""A request whose asker has closed its connection is dropped at its next unit's
turn, whatever its deadline says. No answer can reach a closed connection, and
this makes the drop the service's own guarantee, not each client's duty to send
remaining_ms (the Pi, 2026-11-10: after train 1115's sitting, 47 lessons embeds
whose hooks had given up held the embedder at 390% CPU, because the peer's
lessons client sent no deadline)."""

from __future__ import annotations

import logging
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

import embedder_service
from embedder_service import EmbedderServer, asker_gone, recv_message, send_message

from tests.test_embedder_lane import UnitProvider, _vector


@pytest.fixture
def socket_dir():
    path = Path(tempfile.mkdtemp(prefix="gone-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def served(socket_dir):
    provider = UnitProvider(unit_size=1)
    provider.gate = threading.Event()
    path = socket_dir / "e.sock"
    server = EmbedderServer(path, provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, provider, path
    provider.gate.set()
    server.shutdown()
    server.server_close()


def _ask(path, request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(10)
        client.connect(str(path))
        send_message(client, request)
        return recv_message(client)


def _send_and_hold(path, request):
    """Send a request and keep the connection open, as an asker that's still waiting."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(10)
    client.connect(str(path))
    send_message(client, request)
    return client


def _wait_for(condition):
    deadline = time.monotonic() + 30  # a loaded Pi
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert condition()


def _dropped(caplog):
    return [record.getMessage() for record in caplog.records if "whose asker had gone" in record.getMessage()]


def _start_batch(path, texts):
    """A batch with no deadline holding the lane on its first unit; returns its thread and answer."""
    answer = []
    thread = threading.Thread(target=lambda: answer.append(_ask(path, {"op": "embed", "texts": texts})), daemon=True)
    thread.start()
    return thread, answer


def test_a_batch_whose_asker_left_while_in_line_runs_nothing(served, caplog):
    server, provider, path = served
    caplog.set_level(logging.INFO, logger="engram.embedder")
    holder, holder_answer = _start_batch(path, ["a"])
    assert provider.entered.wait(10)  # "a" holds the lane
    left = _send_and_hold(path, {"op": "embed", "texts": ["b"]})  # no remaining_ms, as the lessons client sent
    _wait_for(lambda: server.lane.batches_waiting == 1)
    left.close()  # its hook gave up
    provider.gate.set()
    holder.join(10)
    _wait_for(lambda: _dropped(caplog))
    assert ["b"] not in [texts for texts, _ in provider.calls]
    assert len(_dropped(caplog)) == 1 and "batch request whose asker had gone: 0 of 1" in _dropped(caplog)[0]
    assert holder_answer[0]["ok"] is True and holder_answer[0]["vectors"] == [_vector("a")]
    after = _ask(path, {"op": "embed", "texts": ["c"]})  # the lane is free for the next asker
    assert after["ok"] is True and after["vectors"] == [_vector("c")]


def test_a_query_whose_asker_left_while_in_line_runs_nothing(served, caplog):
    server, provider, path = served
    caplog.set_level(logging.INFO, logger="engram.embedder")
    holder, _ = _start_batch(path, ["a"])
    assert provider.entered.wait(10)
    left = _send_and_hold(path, {"op": "embed", "texts": ["q?"], "prefix": "search_query"})
    _wait_for(lambda: server.lane.queries_waiting == 1)
    left.close()
    provider.gate.set()
    holder.join(10)
    _wait_for(lambda: _dropped(caplog))
    assert ["q?"] not in [texts for texts, _ in provider.calls]
    assert "query request whose asker had gone: 0 of 1" in _dropped(caplog)[0]


def test_a_batch_whose_asker_leaves_between_units_stops_after_the_one_running(served, caplog):
    server, provider, path = served
    caplog.set_level(logging.INFO, logger="engram.embedder")
    left = _send_and_hold(path, {"op": "embed", "texts": ["a", "b", "c"]})
    assert provider.entered.wait(10)  # its first unit runs: a unit already embedding finishes
    left.close()
    provider.gate.set()
    _wait_for(lambda: _dropped(caplog))
    assert [texts for texts, _ in provider.calls] == [["a"]]
    assert "batch request whose asker had gone: 1 of 3" in _dropped(caplog)[0]


def test_an_asker_still_waiting_gets_its_whole_answer(served, caplog):
    server, provider, path = served
    caplog.set_level(logging.INFO, logger="engram.embedder")
    waiting = _send_and_hold(path, {"op": "embed", "texts": ["a", "b"]})
    try:
        assert provider.entered.wait(10)
        provider.gate.set()
        answer = recv_message(waiting)
    finally:
        waiting.close()
    assert answer["ok"] is True and answer["vectors"] == [_vector("a"), _vector("b")]
    assert _dropped(caplog) == []


def test_asker_gone_reads_only_a_closed_end_as_gone():
    ours, theirs = socket.socketpair()
    try:
        assert asker_gone(ours) is False  # quiet: still waiting
        theirs.sendall(b"x")  # bytes past the request break the protocol, but nobody has gone
        assert asker_gone(ours) is False
        ours.settimeout(1)
        assert ours.recv(1) == b"x"  # the peek took nothing
        ours.settimeout(5)  # a timeout never makes the check wait
        started = time.monotonic()
        assert asker_gone(ours) is False
        assert time.monotonic() - started < 1
        theirs.close()
        assert asker_gone(ours) is True
    finally:
        ours.close()
        theirs.close()


def test_asker_gone_reads_a_reset_as_gone():
    ours, theirs = socket.socketpair()
    try:
        ours.sendall(b"y")  # unread by its asker when it closes: Linux resets the connection, other systems end it
        theirs.close()
        assert asker_gone(ours) is True
    finally:
        ours.close()


def test_respond_with_no_gone_check_runs_as_before():
    server = EmbedderServer.__new__(EmbedderServer)  # respond() needs only a provider and a lane
    server.provider, server.model_name, server.lane = UnitProvider(), UnitProvider.MODEL_NAME, embedder_service._Lane()
    answer = server.respond({"op": "embed", "texts": ["a"]})
    assert answer["ok"] is True and answer["vectors"] == [_vector("a")]


class _RecvFails:
    """A socket whose poll reads readable (bytes are waiting) but whose peek raises: an error that isn't a lost asker."""

    def __init__(self, sock, error):
        self._sock, self._error = sock, error

    def fileno(self):
        return self._sock.fileno()

    def recv(self, *args):
        raise self._error


def test_asker_gone_reads_only_a_connection_error_as_gone():
    ours, theirs = socket.socketpair()
    try:
        theirs.sendall(b"x")  # readable, so the peek runs
        assert asker_gone(_RecvFails(ours, TimeoutError("timed out"))) is False
        assert asker_gone(_RecvFails(ours, OSError(22, "Invalid argument"))) is False
        assert asker_gone(_RecvFails(ours, ConnectionResetError(104, "reset"))) is True
    finally:
        ours.close()
        theirs.close()


def test_a_half_close_reads_as_gone_which_is_why_the_protocol_forbids_it():
    ours, theirs = socket.socketpair()
    try:
        theirs.shutdown(socket.SHUT_WR)
        assert asker_gone(ours) is True
        assert "never half-closes" in embedder_service.__doc__ and '"error": "gone"' in embedder_service.__doc__
    finally:
        ours.close()
        theirs.close()


class _CountsUnits(UnitProvider):
    def __init__(self):
        super().__init__(unit_size=1)
        self.unit_calls = 0

    def embed_units(self, texts, *, prefix):
        self.unit_calls += 1
        return super().embed_units(texts, prefix=prefix)


def test_a_request_whose_asker_has_gone_before_its_units_tokenizes_nothing(caplog):
    caplog.set_level(logging.INFO, logger="engram.embedder")
    server = EmbedderServer.__new__(EmbedderServer)
    server.provider, server.model_name, server.lane = _CountsUnits(), UnitProvider.MODEL_NAME, embedder_service._Lane()
    answer = server.respond({"op": "embed", "texts": ["a", "b", "c"]}, gone=lambda: True)
    assert answer == {"ok": False, "error": "gone"}
    assert server.provider.unit_calls == 0 and server.provider.calls == []
    assert "batch request whose asker had gone: 0 of 3" in _dropped(caplog)[0]


def test_a_burst_of_askers_all_get_in_before_the_server_accepts_one(socket_dir):
    provider = UnitProvider(unit_size=1)
    path = socket_dir / "e.sock"
    server = EmbedderServer(path, provider)  # listening, but nothing accepts yet: a burst outruns the accept loop
    clients, serving = [], False
    try:
        for _ in range(47):
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(5)  # as RemoteEmbedProvider and lessons.py do, so a full backlog fails at once
            clients.append(client)
            client.connect(str(path))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        serving = True
        send_message(clients[-1], {"op": "info"})
        assert recv_message(clients[-1])["ok"] is True
    finally:
        for client in clients:
            client.close()
        if serving:  # shutdown() waits for a serve_forever that never started
            server.shutdown()
        server.server_close()
