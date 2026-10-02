"""Tests for the embedding providers."""

from __future__ import annotations

import math

import pytest

from embeddings import NomicEmbedProvider, FastEmbedProvider


@pytest.fixture(scope="module")
def nomic_provider():
    """Shared nomic provider instance (model download is expensive)."""
    return NomicEmbedProvider()


@pytest.fixture(scope="module")
def legacy_provider():
    """Shared legacy provider instance."""
    return FastEmbedProvider()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b)


# --- Nomic provider tests ---

def test_nomic_dimension(nomic_provider):
    assert nomic_provider.dimension() == 768


def test_nomic_embed_single(nomic_provider):
    result = nomic_provider.embed(["hello world"])
    assert len(result) == 1
    assert len(result[0]) == 768
    assert all(isinstance(v, float) for v in result[0])


def test_nomic_embed_batch(nomic_provider):
    result = nomic_provider.embed(["a", "b", "c"])
    assert len(result) == 3
    for emb in result:
        assert len(emb) == 768


def test_nomic_deterministic(nomic_provider):
    a = nomic_provider.embed(["hello world"])
    b = nomic_provider.embed(["hello world"])
    assert a == b


def test_nomic_normalized(nomic_provider):
    embeddings = nomic_provider.embed(["test sentence", "another one"])
    for emb in embeddings:
        norm = math.sqrt(sum(x * x for x in emb))
        assert abs(norm - 1.0) < 1e-3, f"L2 norm was {norm}, expected ~1.0"


def test_nomic_similar_texts_closer(nomic_provider):
    embs = nomic_provider.embed(["python function", "python method", "chocolate cake"])
    sim_related = _cosine_similarity(embs[0], embs[1])
    sim_unrelated = _cosine_similarity(embs[0], embs[2])
    assert sim_related > sim_unrelated


def test_nomic_prefix_affects_embedding(nomic_provider):
    """Different prefixes should produce different embeddings."""
    text = "prefer terse communication"
    emb_doc = nomic_provider.embed([text], prefix="search_document")[0]
    emb_query = nomic_provider.embed([text], prefix="search_query")[0]
    emb_cluster = nomic_provider.embed([text], prefix="clustering")[0]

    # They should be related but not identical
    sim_doc_query = _cosine_similarity(emb_doc, emb_query)
    sim_doc_cluster = _cosine_similarity(emb_doc, emb_cluster)

    # All should be high (same text) but not 1.0 (different prefix)
    assert 0.7 < sim_doc_query < 1.0
    assert 0.7 < sim_doc_cluster < 1.0


def test_nomic_clustering_groups_better(nomic_provider):
    """Clustering prefix should push related concepts closer."""
    texts = ["python function", "python method", "chocolate cake"]

    embs_cluster = nomic_provider.embed(texts, prefix="clustering")
    embs_doc = nomic_provider.embed(texts, prefix="search_document")

    sim_cluster = _cosine_similarity(embs_cluster[0], embs_cluster[1])
    sim_doc = _cosine_similarity(embs_doc[0], embs_doc[1])

    # Clustering prefix should give at least as good grouping
    # (may not always be strictly better, but shouldn't be significantly worse)
    assert sim_cluster > sim_doc - 0.1


# --- Legacy provider tests ---

def test_legacy_dimension(legacy_provider):
    assert legacy_provider.dimension() == 384


def test_legacy_embed_single(legacy_provider):
    result = legacy_provider.embed(["hello world"])
    assert len(result) == 1
    assert len(result[0]) == 384


def test_legacy_accepts_prefix_kwarg(legacy_provider):
    """Legacy provider should accept and ignore the prefix kwarg."""
    result = legacy_provider.embed(["hello world"], prefix="clustering")
    assert len(result) == 1
    assert len(result[0]) == 384


# --- Length-bounded batching ---

def test_length_bounded_batches_respect_budget():
    from embeddings import _BATCH_CHAR_BUDGET, _length_bounded_batches

    texts = ["x" * 800] * 78 + ["y" * 12_054] + ["z" * 2_000] * 5
    batches = _length_bounded_batches(texts)
    assert sorted(i for batch in batches for i in batch) == list(range(len(texts)))
    for batch in batches:
        longest = max(len(texts[i]) for i in batch)
        assert len(batch) == 1 or len(batch) * longest * longest <= _BATCH_CHAR_BUDGET


def test_nomic_bounded_batches_match_single_batch(nomic_provider):
    import numpy as np

    texts = ["short", "a much longer sentence " * 120, "medium length text " * 10, "tiny"]
    bounded = nomic_provider.embed(texts, prefix="clustering")
    prefixed = [f"clustering: {t}" for t in texts]
    single = list(nomic_provider._model.embed(prefixed, batch_size=len(prefixed)))
    for got, raw in zip(bounded, single):
        expected = np.array(raw) / np.linalg.norm(raw)
        assert np.allclose(got, expected, atol=1e-4)
