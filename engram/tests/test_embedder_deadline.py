"""A request can say how long its caller will still wait (`remaining_ms`). The
service stamps its arrival on its own monotonic clock and, before each unit,
drops a request whose time has run out, so a caller that gave up no longer
holds the lane (the Pi, 2026-11-09: 74 s for a short text after a backlog of
abandoned requests; a crossing's receiver gives up at 1 s while the
publisher's embed waited up to 900 s)."""

from __future__ import annotations

import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

import embedder_service
from embedder_service import EmbedderServer, recv_message, send_message

from tests.test_embedder_lane import UnitProvider, _vector


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(embedder_service, "monotonic", fake)
    return fake


@pytest.fixture
def socket_dir():
    path = Path(tempfile.mkdtemp(prefix="deadline-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _serve(path, provider):
    server = EmbedderServer(path, provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _ask(path, request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(10)
        client.connect(str(path))
        send_message(client, request)
        return recv_message(client)


def _wait_for(condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert condition()


def test_a_request_with_no_deadline_runs_to_the_end_as_before(socket_dir, clock):
    provider = UnitProvider(unit_size=1)
    server = _serve(socket_dir / "e.sock", provider)
    try:
        clock.now += 10_000  # however long it takes, a request with no deadline never expires
        answer = _ask(socket_dir / "e.sock", {"op": "embed", "texts": ["a", "b"]})
        assert answer["ok"] is True and answer["vectors"] == [_vector("a"), _vector("b")]
    finally:
        server.shutdown()
        server.server_close()


def test_a_request_with_time_left_runs_to_the_end(socket_dir, clock):
    provider = UnitProvider(unit_size=1)
    server = _serve(socket_dir / "e.sock", provider)
    try:
        answer = _ask(socket_dir / "e.sock", {"op": "embed", "texts": ["a", "b", "c"], "remaining_ms": 60_000})
        assert answer["ok"] is True and answer["vectors"] == [_vector(t) for t in "abc"]
        assert [texts for texts, _ in provider.calls] == [["a"], ["b"], ["c"]]
    finally:
        server.shutdown()
        server.server_close()


def test_a_query_whose_time_ran_out_in_line_is_dropped_at_its_turn_and_runs_nothing(socket_dir, clock):
    provider = UnitProvider(unit_size=1)
    provider.gate = threading.Event()
    path = socket_dir / "e.sock"
    server = _serve(path, provider)
    try:
        batch_answer = []
        batch = threading.Thread(
            target=lambda: batch_answer.append(_ask(path, {"op": "embed", "texts": ["a", "b", "c"]})), daemon=True)
        batch.start()
        assert provider.entered.wait(5)  # the batch's first unit holds the lane
        query_answer = []
        query = threading.Thread(target=lambda: query_answer.append(_ask(path, {
            "op": "embed", "texts": ["q?"], "prefix": "search_query", "remaining_ms": 1_000})), daemon=True)
        query.start()
        _wait_for(lambda: server.lane.queries_waiting == 1)
        clock.now += 1.0  # exactly its time: gone when its turn comes
        provider.gate.set()
        query.join(5)
        batch.join(5)
        assert query_answer == [{"ok": False, "error": "expired"}]
        assert ["q?"] not in [texts for texts, _ in provider.calls]
        assert batch_answer[0]["ok"] is True and batch_answer[0]["vectors"] == [_vector(t) for t in "abc"]
    finally:
        provider.gate.set()
        server.shutdown()
        server.server_close()


def test_a_batch_whose_time_runs_out_between_units_stops_and_frees_the_lane(socket_dir, clock):
    provider = UnitProvider(unit_size=1)
    provider.gate = threading.Event()
    path = socket_dir / "e.sock"
    server = _serve(path, provider)
    try:
        answer = []
        batch = threading.Thread(target=lambda: answer.append(_ask(path, {
            "op": "embed", "texts": ["a", "b", "c"], "remaining_ms": 500})), daemon=True)
        batch.start()
        assert provider.entered.wait(5)  # its first unit runs: it had time
        clock.now += 0.6
        provider.gate.set()
        batch.join(5)
        assert answer == [{"ok": False, "error": "expired"}]
        assert [texts for texts, _ in provider.calls] == [["a"]]
        after = _ask(path, {"op": "embed", "texts": ["d"]})  # the lane is free for the next request
        assert after["ok"] is True and after["vectors"] == [_vector("d")]
    finally:
        provider.gate.set()
        server.shutdown()
        server.server_close()


def test_a_request_that_arrives_with_no_time_left_runs_nothing(socket_dir, clock):
    provider = UnitProvider(unit_size=1)
    server = _serve(socket_dir / "e.sock", provider)
    try:
        answer = _ask(socket_dir / "e.sock", {"op": "embed", "texts": ["a"], "remaining_ms": 0})
        assert answer == {"ok": False, "error": "expired"} and provider.calls == []
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("value", [-1, "500", True, float("nan"), float("inf"), [500], {"ms": 500}])
def test_a_deadline_that_isnt_a_finite_non_negative_number_is_refused(value):
    server = EmbedderServer.__new__(EmbedderServer)  # respond() needs only a provider and a lane
    server.provider, server.model_name, server.lane = UnitProvider(), UnitProvider.MODEL_NAME, embedder_service._Lane()
    answer = server.respond({"op": "embed", "texts": ["a"], "remaining_ms": value})
    assert answer == {"ok": False, "error": "remaining_ms must be a finite, non-negative number of milliseconds"}
    assert server.provider.calls == []


def test_a_null_deadline_reads_as_none_given():
    server = EmbedderServer.__new__(EmbedderServer)
    server.provider, server.model_name, server.lane = UnitProvider(), UnitProvider.MODEL_NAME, embedder_service._Lane()
    answer = server.respond({"op": "embed", "texts": ["a"], "remaining_ms": None})
    assert answer["ok"] is True and answer["vectors"] == [_vector("a")]
