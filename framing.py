"""LLM-based perceptual framing for instincts.

The heuristic in compress.py slices strings to produce notice/implication
fields; this asks a local Ollama model to actually distill them: when does
this apply (notice), and what follows (implication)?

Returns None on any failure so the caller can fall back to the heuristic.
Only called during compression, not on every recall.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger("engram.framing")

OLLAMA_URL = "http://localhost:11434/api/generate"

NOTICE_MAX = 60
IMPLICATION_MAX = 120

_PROMPT_TEMPLATE = """This {kind} was distilled from memory and is becoming a perceptual instinct — an attention directive, not a behavioral rule.

{content}

Produce two fields:
- "notice": the situation in which this applies, as a short cue starting with "when" (under {notice_max} characters)
- "implication": what to attend to or what follows, one sentence (under {implication_max} characters)

Answer with ONLY a JSON object: {{"notice": "...", "implication": "..."}}"""


def _truncate_at_word(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip()


@dataclass
class FramingConfig:
    """Configuration for the framing distiller."""

    model: str = "gemma4:31b"
    ollama_url: str = OLLAMA_URL
    timeout: int = 60


class FramingDistiller:
    """Distills notice/implication framing from semantic content via a local LLM."""

    def __init__(self, config: FramingConfig | None = None):
        self._config = config or FramingConfig()
        self._available: bool | None = None  # lazy-checked

    def is_available(self) -> bool:
        """Check if Ollama is reachable and the model is loaded.

        Retries on each call if previously unavailable — Ollama may
        come online mid-session.
        """
        if self._available is True:
            return True
        try:
            req = urllib.request.Request(
                self._config.ollama_url.replace("/api/generate", "/api/tags"),
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                models = [m["name"] for m in data.get("models", [])]
                self._available = any(
                    self._config.model in m for m in models
                )
        except Exception:
            self._available = False
            logger.debug("Ollama not available for framing", exc_info=True)
        return self._available

    def _generate(self, prompt: str) -> str | None:
        """Raw transport: send prompt to Ollama, return response text."""
        body = {
            "model": self._config.model,
            "prompt": prompt,
            "stream": False,
            # Thinking models (e.g. gemma4) burn the whole num_predict budget
            # on hidden reasoning and return "" unless thinking is disabled.
            "think": False,
            "options": {"temperature": 0.0, "num_predict": 200},
        }
        try:
            result = self._post(body)
            response = result.get("response", "")
            if not response and result.get("done_reason") == "length":
                logger.warning(
                    "Framing response empty with done_reason=length — model "
                    "spent the token budget thinking; falling back to heuristic"
                )
                return None
            return response
        except Exception:
            logger.warning("Framing LLM call failed", exc_info=True)
            return None

    def _post(self, body: dict) -> dict:
        """POST to Ollama; retry once without `think` if the model rejects it."""
        try:
            return self._post_once(body)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            if "think" in detail.lower() and "think" in body:
                retry = {k: v for k, v in body.items() if k != "think"}
                return self._post_once(retry)
            raise

    def _post_once(self, body: dict) -> dict:
        req = urllib.request.Request(
            self._config.ollama_url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self._config.timeout) as resp:
            return json.loads(resp.read())

    def distill(self, content: str, kind: str) -> tuple[str, str] | None:
        """Distill (notice, implication) from semantic content.

        Returns None if Ollama is unavailable or the response doesn't
        validate — the caller falls back to its heuristic.
        """
        if not content or not self.is_available():
            return None

        prompt = _PROMPT_TEMPLATE.format(
            kind=kind,
            content=content,
            notice_max=NOTICE_MAX,
            implication_max=IMPLICATION_MAX,
        )
        response = self._generate(prompt)
        if response is None:
            return None
        return self._parse(response)

    def _parse(self, response: str) -> tuple[str, str] | None:
        text = response.strip()
        if text.startswith("```"):
            # Strip a markdown code fence (with optional language tag)
            text = text.split("\n", 1)[-1]
            text = text.rsplit("```", 1)[0].strip()
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            logger.debug("Framing response was not valid JSON: %r", response[:200])
            return None
        if not isinstance(data, dict):
            return None

        notice = str(data.get("notice") or "").strip()
        implication = str(data.get("implication") or "").strip()
        if not notice or not implication:
            return None

        if not notice.lower().startswith("when"):
            notice = f"when {notice}"
        notice = _truncate_at_word(notice, NOTICE_MAX)
        implication = _truncate_at_word(implication, IMPLICATION_MAX)
        return (notice, implication)
