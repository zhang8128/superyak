"""Tests for LLM-based pragmatic deduplication — Ollama transport contract.

gemma4:31b is a thinking model: without think=false it spends the whole
num_predict budget on hidden reasoning and returns an empty response, which
silently reads as a "different" verdict. These tests pin the transport
contract that prevents that failure mode.
"""

from __future__ import annotations

import io
import json
import logging
import urllib.error
import urllib.request

import pytest

from dedup import Deduplicator


class FakeResponse:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def dedup(monkeypatch) -> Deduplicator:
    d = Deduplicator()
    monkeypatch.setattr(d, "is_available", lambda: True)
    return d


def capture_requests(monkeypatch, responses):
    """Patch urlopen to return canned responses, recording request bodies."""
    bodies = []
    it = iter(responses)

    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data))
        result = next(it)
        if isinstance(result, Exception):
            raise result
        return FakeResponse(result)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return bodies


def test_request_disables_thinking(dedup, monkeypatch):
    bodies = capture_requests(
        monkeypatch, [{"response": "same", "done_reason": "stop"}])

    assert dedup.is_equivalent("prefers dark roast", "likes dark roast") is True
    assert bodies[0]["think"] is False


def test_thinking_burn_is_logged_not_silent(dedup, monkeypatch, caplog):
    capture_requests(
        monkeypatch, [{"response": "", "done_reason": "length"}])

    with caplog.at_level(logging.WARNING, logger="engram.dedup"):
        assert dedup.is_equivalent("a", "b") is False

    assert any("thinking" in r.message.lower() or "empty" in r.message.lower()
               for r in caplog.records)


def test_retries_without_think_when_model_rejects_it(dedup, monkeypatch):
    rejection = urllib.error.HTTPError(
        url="http://localhost:11434/api/generate", code=400,
        msg="Bad Request", hdrs=None,
        fp=io.BytesIO(b'{"error":"\\"gemma4:31b\\" does not support thinking"}'),
    )
    bodies = capture_requests(
        monkeypatch, [rejection, {"response": "same", "done_reason": "stop"}])

    assert dedup.is_equivalent("a", "b") is True
    assert "think" in bodies[0]
    assert "think" not in bodies[1]


def test_different_verdict_unchanged(dedup, monkeypatch):
    capture_requests(
        monkeypatch, [{"response": "different", "done_reason": "stop"}])

    assert dedup.is_equivalent("dark roast", "python asyncio") is False
