"""Embedding provider protocol and implementations.

Default: nomic-embed-text-v1.5 (768-dim, instruction-tuned, Matryoshka).
Supports task-specific prefixes for better clustering vs retrieval quality.
"""

from __future__ import annotations

import os
import threading
import time
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
# Seconds without an embed before an in-process model is dropped (ENGRAM_EMBED_IDLE_SECONDS; 0 keeps it for the life
# of the process). Loading it again costs about 2.6 s on the Pi; holding it costs about 850 MB (measured 2026-11-02: an
# Engram server at 241 MB at rest, 1.09 GB after the first embed).
_IDLE_DEFAULT = 300.0


def _idle_seconds_from_env() -> float:
    value = os.environ.get("ENGRAM_EMBED_IDLE_SECONDS", "").strip()
    if not value:
        return _IDLE_DEFAULT
    try:
        seconds = float(value)
    except ValueError:
        seconds = -1.0
    if not 0 <= seconds <= threading.TIMEOUT_MAX:  # also refuses nan and inf, which a timer can't wait out
        raise ValueError(f"ENGRAM_EMBED_IDLE_SECONDS must be a number of seconds from 0 to {threading.TIMEOUT_MAX:.0f}; "
                         f"got {value!r}")
    return seconds


def _return_freed_heap() -> None:
    """Hand freed heap pages back to the system (glibc keeps them otherwise; elsewhere a no-op)."""
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


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


def _embed_bounded(model, texts: list[str]) -> list:
    """Run model.embed over token-budget batches, returning vectors in input order."""
    results: list = [None] * len(texts)
    for batch in _token_budget_batches(texts):
        vectors = model.embed([texts[i] for i in batch], batch_size=len(batch))
        for index, vector in zip(batch, vectors):
            results[index] = vector
    return results


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

    def __init__(self, idle_seconds: float | None = None) -> None:
        # The model loads on the first embed, not here, and is dropped again after idle_seconds without one: a process
        # that rarely embeds (a session that only reads, a store with nothing to backfill) holds it only while it
        # uses it, about 850 MB on the Pi (Andy, 2026-11-02: "engram should be able to be run with very little
        # memory", "rarely accessed paths could be on disk").
        self._model = None
        self._loading = threading.Lock()
        self._busy = 0
        self._last_used = 0.0
        self._idle_seconds = _idle_seconds_from_env() if idle_seconds is None else idle_seconds
        self._unload_timer: threading.Timer | None = None

    def _loaded(self):
        with self._loading:  # one load, however many threads embed first at once
            return self._load_locked()

    def _load_locked(self):
        if self._model is None:
            from fastembed import TextEmbedding

            # Without the arena, ONNX Runtime returns each run's buffers instead of
            # keeping the largest batch's allocation for the life of the process.
            model = TextEmbedding(
                model_name=self.MODEL_NAME, cache_dir=_CACHE_DIR, enable_cpu_mem_arena=False,
            )
            # The tokenizer config allows 8192 tokens; past the trained context,
            # attention cost grows without improving the embedding.
            model.model.tokenizer.enable_truncation(max_length=_MAX_TOKENS)
            self._model = model
        return self._model

    def is_loaded(self) -> bool:
        return self._model is not None

    def _arm_unload_locked(self) -> None:
        if self._idle_seconds <= 0:
            return
        if self._unload_timer is not None:
            self._unload_timer.cancel()
        timer = threading.Timer(self._idle_seconds, self._unload_if_idle)
        timer.daemon = True  # never keeps a finished process alive
        self._unload_timer = timer
        timer.start()

    def _unload_if_idle(self) -> None:
        with self._loading:
            if self._busy or self._model is None:
                return
            left = self._idle_seconds - (time.monotonic() - self._last_used)
            if left > 0:
                if self._unload_timer is threading.current_thread():  # this timer fired early: wait out the rest
                    self._unload_timer = threading.Timer(left, self._unload_if_idle)
                    self._unload_timer.daemon = True
                    self._unload_timer.start()
                return  # otherwise a later embed armed its own timer
            self._model = None
            self._unload_timer = None
        import gc

        gc.collect()
        _return_freed_heap()

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

        if not texts:
            return []  # nothing to embed loads nothing
        prefixed = [f"{prefix}: {t}" for t in texts]
        with self._loading:
            model = self._load_locked()
            self._busy += 1
        try:
            embeddings = _embed_bounded(model, prefixed)
        finally:
            with self._loading:
                self._busy -= 1
                self._last_used = time.monotonic()
                self._arm_unload_locked()
        # Normalize to unit vectors for consistent cosine similarity via L2 distance
        results = []
        for e in embeddings:
            arr = np.array(e)
            norm = np.linalg.norm(arr)
            if norm > 0:
                arr = arr / norm
            results.append(arr.tolist())
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
        embeddings = _embed_bounded(self._model, texts)
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
