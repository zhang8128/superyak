"""Embedding provider protocol and implementations.

Default: nomic-embed-text-v1.5 (768-dim, instruction-tuned, Matryoshka).
Supports task-specific prefixes for better clustering vs retrieval quality.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

_CACHE_DIR = str(Path.home() / ".kairos" / "models" / "fastembed")

# Attention memory grows with batch_size * padded_length**2, and every text in a
# batch is padded to the longest one. One 159-text batch whose longest member
# was ~12k chars drove the server past 200 GB. Batches are therefore built in
# ascending length order and capped at this many chars**2 (~250 MB of
# activations); a single over-budget text still runs alone. Padding is masked,
# so the vectors are the same as one big batch.
_BATCH_CHAR_BUDGET = 16_000_000


def _length_bounded_batches(texts: list[str]) -> list[list[int]]:
    """Group text indices into batches whose len(batch) * longest**2 fits the budget."""
    batches: list[list[int]] = []
    current: list[int] = []
    for index in sorted(range(len(texts)), key=lambda i: len(texts[i])):
        longest = max(len(texts[index]), 1)
        if current and (len(current) + 1) * longest * longest > _BATCH_CHAR_BUDGET:
            batches.append(current)
            current = []
        current.append(index)
    if current:
        batches.append(current)
    return batches


def _embed_bounded(model, texts: list[str]) -> list:
    """Run model.embed over length-bounded batches, returning vectors in input order."""
    results: list = [None] * len(texts)
    for batch in _length_bounded_batches(texts):
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

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=self.MODEL_NAME, cache_dir=_CACHE_DIR)

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
        embeddings = _embed_bounded(self._model, prefixed)
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
