"""Local Graphiti embedding and reranking adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Protocol

import numpy as np
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.embedder.client import EmbedderClient


class EmbeddingProvider(Protocol):
    def dimension(self) -> int: ...

    def embed(
        self, texts: list[str], *, prefix: str = "search_document"
    ) -> list[list[float]]: ...


class GraphitiEmbedder(EmbedderClient):
    """Adapt Engram's synchronous embedding provider to Graphiti."""

    def __init__(self, embedding_provider: EmbeddingProvider):
        self._provider = embedding_provider

    async def create(
        self,
        input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]],
    ) -> list[float]:
        texts = [input_data] if isinstance(input_data, str) else list(input_data)
        embeddings = await asyncio.to_thread(
            self._provider.embed, texts, prefix="search_document"
        )
        return embeddings[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(
            self._provider.embed, input_data_list, prefix="search_document"
        )


class GraphitiReranker(CrossEncoderClient):
    """Rank Graphiti passages locally using embedding cosine similarity."""

    def __init__(self, embedding_provider: EmbeddingProvider):
        self._provider = embedding_provider

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        if not passages:
            return []

        query_vectors, passage_vectors = await asyncio.gather(
            asyncio.to_thread(
                self._provider.embed, [query], prefix="search_query"
            ),
            asyncio.to_thread(
                self._provider.embed, passages, prefix="search_document"
            ),
        )
        query_vector = np.asarray(query_vectors[0], dtype=float)
        passage_matrix = np.asarray(passage_vectors, dtype=float)
        denominators = np.linalg.norm(passage_matrix, axis=1) * np.linalg.norm(
            query_vector
        )
        scores = np.divide(
            passage_matrix @ query_vector,
            denominators,
            out=np.zeros(len(passages), dtype=float),
            where=denominators != 0,
        )
        return sorted(
            zip(passages, (float(score) for score in scores)),
            key=lambda item: item[1],
            reverse=True,
        )
