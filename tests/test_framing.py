"""Tests for LLM-based perceptual framing distillation."""

from __future__ import annotations

import json

from framing import IMPLICATION_MAX, NOTICE_MAX, FramingDistiller


class StubDistiller(FramingDistiller):
    """Distiller with a stubbed transport — no Ollama needed."""

    def __init__(self, response: str | None = None, available: bool = True):
        super().__init__()
        self._response = response
        self._stub_available = available

    def is_available(self) -> bool:
        return self._stub_available

    def _generate(self, prompt: str) -> str | None:
        return self._response


def test_distill_parses_json_response():
    response = json.dumps({
        "notice": "when reviewing a memory system's design",
        "implication": "Ask what it actually does, not whether it works like memory.",
    })
    distiller = StubDistiller(response=response)

    result = distiller.distill("The wing-flapping lesson: none of our flying machines flap their wings.", "preference")

    assert result == (
        "when reviewing a memory system's design",
        "Ask what it actually does, not whether it works like memory.",
    )


def test_distill_prefixes_when_if_missing():
    response = json.dumps({
        "notice": "reviewing a memory system's design",
        "implication": "Ask what it actually does.",
    })
    distiller = StubDistiller(response=response)

    notice, _ = distiller.distill("content", "preference")

    assert notice.startswith("when ")


def test_distill_strips_code_fences():
    inner = json.dumps({"notice": "when testing", "implication": "Local models love code fences."})
    response = f"```json\n{inner}\n```"
    distiller = StubDistiller(response=response)

    result = distiller.distill("content", "constraint")

    assert result == ("when testing", "Local models love code fences.")


def test_distill_caps_lengths_at_word_boundaries():
    response = json.dumps({
        "notice": "when " + "reviewing very long elaborate descriptions " * 4,
        "implication": "An implication that rambles on far past the cap " * 6,
    })
    distiller = StubDistiller(response=response)

    notice, implication = distiller.distill("content", "preference")

    assert len(notice) <= NOTICE_MAX
    assert len(implication) <= IMPLICATION_MAX
    assert not notice.endswith(" ")
    assert not implication.endswith(" ")


def test_distill_returns_none_on_garbage():
    distiller = StubDistiller(response="I think the notice should be about reviewing designs.")

    assert distiller.distill("content", "preference") is None


def test_distill_returns_none_on_empty_fields():
    response = json.dumps({"notice": "", "implication": ""})
    distiller = StubDistiller(response=response)

    assert distiller.distill("content", "preference") is None


def test_distill_returns_none_when_unavailable():
    response = json.dumps({"notice": "when testing", "implication": "Should never be returned."})
    distiller = StubDistiller(response=response, available=False)

    assert distiller.distill("content", "preference") is None


def test_distill_returns_none_when_transport_fails():
    distiller = StubDistiller(response=None)

    assert distiller.distill("content", "preference") is None


class FakeResponse:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_generate_disables_thinking(monkeypatch):
    import urllib.request

    bodies = []

    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data))
        return FakeResponse({"response": "ok", "done_reason": "stop"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    distiller = FramingDistiller()

    assert distiller._generate("prompt") == "ok"
    assert bodies[0]["think"] is False


def test_generate_returns_none_on_thinking_burn(monkeypatch):
    import urllib.request

    def fake_urlopen(req, timeout=None):
        return FakeResponse({"response": "", "done_reason": "length"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    distiller = FramingDistiller()

    assert distiller._generate("prompt") is None


def test_generate_retries_without_think_when_model_rejects_it(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    bodies = []
    responses = iter([
        urllib.error.HTTPError(
            url="http://localhost:11434/api/generate", code=400,
            msg="Bad Request", hdrs=None,
            fp=io.BytesIO(b'{"error":"model does not support thinking"}'),
        ),
        FakeResponse({"response": "ok", "done_reason": "stop"}),
    ])

    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data))
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    distiller = FramingDistiller()

    assert distiller._generate("prompt") == "ok"
    assert "think" in bodies[0]
    assert "think" not in bodies[1]
