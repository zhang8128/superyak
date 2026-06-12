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
