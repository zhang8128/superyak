"""Semantic deduplication via LLM reasoning.

Embeddings detect surface similarity; dedup detects pragmatic equivalence.
Uses a local Ollama model to answer: "do these two statements express the
same behavioral preference or constraint?"

Only called during compression, not on every recall.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger("engram.dedup")

OLLAMA_URL = "http://localhost:11434/api/generate"

_PROMPT_TEMPLATE = """Do these two instructions express the same behavioral preference or constraint? Consider the underlying intent, not the surface wording.

Instruction A: {a}
Instruction B: {b}

Answer with ONLY "same" or "different" (one word)."""


@dataclass
class DedupConfig:
    """Configuration for the dedup module."""

    model: str = "gemma4:31b"
    ollama_url: str = OLLAMA_URL
    timeout: int = 60


class Deduplicator:
    """Pairwise pragmatic equivalence checker using a local LLM."""

    def __init__(self, config: DedupConfig | None = None):
        self._config = config or DedupConfig()
        self._available: bool | None = None  # lazy-checked

    def is_available(self) -> bool:
        """Check if Ollama is reachable and the model is loaded.

        Retries on each call if previously unavailable — Ollama may
        come online mid-session.
        """
        # Only cache positive results; retry if previously unavailable
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
            logger.debug("Ollama not available for dedup", exc_info=True)
        return self._available

    def is_equivalent(self, a: str, b: str) -> bool:
        """Check if two statements express the same preference/constraint.

        Returns False if Ollama is unavailable (fails open — no dedup
        is safer than wrong dedup).
        """
        if not self.is_available():
            return False

        prompt = _PROMPT_TEMPLATE.format(a=a, b=b)
        body = {
            "model": self._config.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 20},
        }

        try:
            req = urllib.request.Request(
                self._config.ollama_url,
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self._config.timeout) as resp:
                result = json.loads(resp.read())

            answer = result.get("response", "").strip().lower()
            is_same = answer.startswith("same")
            logger.debug(
                "Dedup: %r vs %r → %s (%s)",
                a[:50], b[:50], "same" if is_same else "different", answer,
            )
            return is_same
        except Exception:
            logger.warning("Dedup LLM call failed, treating as different", exc_info=True)
            return False

    def find_duplicates(self, items: list[dict], key: str = "content") -> list[tuple[int, int]]:
        """Find all duplicate pairs in a list of items.

        Returns list of (i, j) index pairs where items[i] and items[j]
        are pragmatically equivalent.
        """
        pairs = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if self.is_equivalent(items[i][key], items[j][key]):
                    pairs.append((i, j))
        return pairs
