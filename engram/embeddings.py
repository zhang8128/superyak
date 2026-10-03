"""Embedding provider protocol and implementations.

Default: nomic-embed-text-v1.5 (768-dim, instruction-tuned, Matryoshka).
Supports task-specific prefixes for better clustering vs retrieval quality.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

_CACHE_DIR = str(Path.home() / ".kairos" / "models" / "fastembed")

# Memory bounds for local ONNX inference. fastembed pads every text in a batch
# to the longest one, and its default batch is 256 texts, so a single long
# episode made a whole batch pay for attention at its length: embedding 72
# pending episodes peaked at 4.6 GB, and startup maintenance reached 16 GB
# and was OOM-killed (2026-10-01). Measured on the laptop store (592
# episodes): these settings peak at 1.75 GB and return to the loaded size.
_MAX_TOKENS = 2048  # nomic-embed-text-v1.5's trained context
_BATCH_TOKEN_BUDGET = 4096  # padded tokens per ONNX run
_CHARS_PER_TOKEN = 3  # conservative estimate for English prose and code


def _token_budget_batches(texts: list[str]) -> list[list[int]]:
    """Group text indices into batches of similar length under a token budget."""
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    batches: list[list[int]] = []
    current: list[int] = []
    for i in order:
        # Sorted ascending, so this text sets the batch's padded length.
        padded = min(len(texts[i]) // _CHARS_PER_TOKEN + 8, _MAX_TOKENS)
        if current and (len(current) + 1) * padded > _BATCH_TOKEN_BUDGET:
            batches.append(current)
            current = []
        current.append(i)
    if current:
        batches.append(current)
    return batches


class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def dimension(self) -> int: ...


class NomicEmbedProvider:
    """Nomic embed-text v1.5 via FastEmbed.

    768-dim, 137M params, instruction-tuned with task prefixes:
    - search_query: / search_document: for retrieval
    - clustering: for grouping similar concepts
    - classification: for categorization

    Matryoshka: can truncate to 256/128/64 dims without retraining.
    """

    MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
    DIMENSION = 768

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        # Without the arena, ONNX Runtime returns each run's buffers instead of
        # keeping the largest batch's allocation for the life of the process.
        self._model = TextEmbedding(
            model_name=self.MODEL_NAME, cache_dir=_CACHE_DIR, enable_cpu_mem_arena=False,
        )
        # The tokenizer config allows 8192 tokens; past the trained context,
        # attention cost grows without improving the embedding.
        self._model.model.tokenizer.enable_truncation(max_length=_MAX_TOKENS)

    def dimension(self) -> int:
        return self.DIMENSION

    def embed(self, texts: list[str], *, prefix: str = "search_document") -> list[list[float]]:
        """Embed texts with a task prefix. Returns L2-normalized vectors.

        Prefixes shift the embedding space for different tasks:
        - "search_document" — default, for storing memories
        - "search_query" — for recall queries
        - "clustering" — for compression/dedup (pushes same-concept texts closer)
        """
        import numpy as np

        prefixed = [f"{prefix}: {t}" for t in texts]
        results: list[list[float]] = [[] for _ in prefixed]
        for batch in _token_budget_batches(prefixed):
            embeddings = self._model.embed([prefixed[i] for i in batch], batch_size=len(batch))
            for i, e in zip(batch, embeddings):
                # Normalize to unit vectors for consistent cosine similarity via L2 distance
                arr = np.array(e)
                norm = np.linalg.norm(arr)
                if norm > 0:
                    arr = arr / norm
                results[i] = arr.tolist()
        return results


class FastEmbedProvider:
    """Legacy provider using all-MiniLM-L6-v2 (384-dim).

    Kept for backwards compatibility. Prefer NomicEmbedProvider.
    """

    MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
    DIMENSION = 384

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=self.MODEL_NAME, cache_dir=_CACHE_DIR)

    def dimension(self) -> int:
        return self.DIMENSION

    def embed(self, texts: list[str], **_kwargs) -> list[list[float]]:
        embeddings = list(self._model.embed(texts))
        return [e.tolist() for e in embeddings]


class EmbedderUnavailableError(RuntimeError):
    """ENGRAM_EMBEDDER_SOCKET is set but the shared embedder did not answer."""


class RemoteEmbedProvider:
    """nomic-embed-text-v1.5 served by embedder_service.py over a Unix socket.

    Fails loudly instead of loading a local model when the service is down:
    a silent fallback in every agent is how one outage becomes N model copies
    and an OOM.
    """

    MODEL_NAME = NomicEmbedProvider.MODEL_NAME
    DIMENSION = NomicEmbedProvider.DIMENSION
    CONNECT_TIMEOUT = 5.0
    # Requests queue behind other agents' batches; maintenance can take minutes.
    RESPONSE_TIMEOUT = 900.0

    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path
        self._verified = False

    def dimension(self) -> int:
        return self.DIMENSION

    def embed(self, texts: list[str], *, prefix: str = "search_document") -> list[list[float]]:
        if not texts:
            return []
        if not self._verified:
            self._check_model(self._call({"op": "info"}))
            self._verified = True
        response = self._call({"op": "embed", "texts": list(texts), "prefix": prefix})
        self._check_model(response)
        vectors = response.get("vectors")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbedderUnavailableError("shared embedder returned a malformed response")
        return vectors

    def _check_model(self, response: dict) -> None:
        # Vectors from a different model would silently corrupt recall.
        if response.get("model") != self.MODEL_NAME or response.get("dimension") != self.DIMENSION:
            raise EmbedderUnavailableError(
                f"shared embedder serves {response.get('model')!r} "
                f"({response.get('dimension')} dims), expected {self.MODEL_NAME!r}"
            )

    def _call(self, request: dict) -> dict:
        import socket

        from embedder_service import recv_message, send_message

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.CONNECT_TIMEOUT)
                sock.connect(self._socket_path)
                sock.settimeout(self.RESPONSE_TIMEOUT)
                send_message(sock, request)
                response = recv_message(sock)
        except (OSError, ValueError) as e:
            raise EmbedderUnavailableError(
                f"shared embedder at {self._socket_path} is unavailable: {type(e).__name__}: {e}"
            ) from e
        if not response.get("ok"):
            raise EmbedderUnavailableError(f"shared embedder error: {response.get('error')}")
        return response


def create_embedding_provider():
    """The process's embedding provider: shared service if configured, else local."""
    import os

    socket_path = os.environ.get("ENGRAM_EMBEDDER_SOCKET")
    if socket_path:
        return RemoteEmbedProvider(socket_path)
    return NomicEmbedProvider()
