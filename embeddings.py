"""Embedding provider protocol and implementations.

Default: nomic-embed-text-v1.5 (768-dim, instruction-tuned, Matryoshka).
Supports task-specific prefixes for better clustering vs retrieval quality.
"""

from __future__ import annotations

from typing import Protocol


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

        self._model = TextEmbedding(model_name=self.MODEL_NAME)

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
        embeddings = list(self._model.embed(prefixed))
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

        self._model = TextEmbedding(model_name=self.MODEL_NAME)

    def dimension(self) -> int:
        return self.DIMENSION

    def embed(self, texts: list[str], **_kwargs) -> list[list[float]]:
        embeddings = list(self._model.embed(texts))
        return [e.tolist() for e in embeddings]
