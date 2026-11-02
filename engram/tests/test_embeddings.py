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


def test_token_budget_batches_cover_each_index_once():
    from embeddings import _token_budget_batches, _BATCH_TOKEN_BUDGET, _MAX_TOKENS
    texts = ["x" * n for n in (5, 40000, 300, 12, 9000, 300, 2, 600)]
    batches = _token_budget_batches(texts)
    assert sorted(i for b in batches for i in b) == list(range(len(texts)))
    for b in batches:
        padded = max(min(len(texts[i]) // 3 + 8, _MAX_TOKENS) for i in b)
        assert len(b) == 1 or len(b) * padded <= _BATCH_TOKEN_BUDGET


def test_nomic_mixed_lengths_keep_input_order(nomic_provider):
    """Length-sorted batching must return vectors in the caller's order."""
    texts = ["chocolate cake " * 400, "python function", "a", "python method " * 30]
    together = nomic_provider.embed(texts)
    for text, emb in zip(texts, together):
        alone = nomic_provider.embed([text])[0]
        assert _cosine_similarity(alone, emb) > 0.999


def test_nomic_bounded_batches_match_single_batch(nomic_provider):
    import numpy as np

    texts = ["short", "a much longer sentence " * 120, "medium length text " * 10, "tiny"]
    bounded = nomic_provider.embed(texts, prefix="clustering")
    prefixed = [f"clustering: {t}" for t in texts]
    single = list(nomic_provider._loaded().embed(prefixed, batch_size=len(prefixed)))
    for got, raw in zip(bounded, single):
        expected = np.array(raw) / np.linalg.norm(raw)
        assert np.allclose(got, expected, atol=1e-4)


# --- Load on first embed, drop when idle (Andy, 2026-11-02: "engram should be able to be run with very little memory") ---

class _FakeTextEmbedding:
    loads = 0
    entered = None  # threading.Event: set when an embed starts
    release = None  # threading.Event: the embed waits for it

    def __init__(self, **_kwargs):
        type(self).loads += 1
        truncation = lambda max_length: None  # noqa: E731
        self.model = type("M", (), {"tokenizer": type("T", (), {"enable_truncation": staticmethod(truncation)})()})()

    def embed(self, texts, batch_size=None):
        cls = type(self)
        if cls.entered is not None:
            cls.entered.set()
            assert cls.release.wait(5)
        return [[3.0, 4.0] for _ in texts]


@pytest.fixture
def fake_fastembed(monkeypatch):
    import fastembed

    _FakeTextEmbedding.loads = 0
    _FakeTextEmbedding.entered = _FakeTextEmbedding.release = None
    monkeypatch.setattr(fastembed, "TextEmbedding", _FakeTextEmbedding)
    return _FakeTextEmbedding


def test_nomic_loads_nothing_until_the_first_embed(fake_fastembed):
    provider = NomicEmbedProvider(idle_seconds=0)
    assert not provider.is_loaded() and fake_fastembed.loads == 0
    assert provider.embed(["a", "b"]) == [[0.6, 0.8], [0.6, 0.8]]
    provider.embed(["c"])
    assert provider.is_loaded() and fake_fastembed.loads == 1


def test_nomic_drops_the_model_when_idle_and_loads_it_again(fake_fastembed):
    import time

    provider = NomicEmbedProvider(idle_seconds=0.2)
    provider.embed(["a"])
    assert provider.is_loaded()
    deadline = time.monotonic() + 5
    while provider.is_loaded() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not provider.is_loaded()
    assert provider.embed(["b"]) == [[0.6, 0.8]]
    assert fake_fastembed.loads == 2


def test_nomic_keeps_the_model_while_an_embed_runs(fake_fastembed):
    import threading

    provider = NomicEmbedProvider(idle_seconds=0.01)
    fake_fastembed.entered, fake_fastembed.release = threading.Event(), threading.Event()
    worker = threading.Thread(target=provider.embed, args=(["a"],))
    worker.start()
    try:
        assert fake_fastembed.entered.wait(5)
        provider._unload_if_idle()  # idle by the clock, but an embed is running
        assert provider.is_loaded()
    finally:
        fake_fastembed.release.set()
        worker.join(5)
    provider._unload_timer.cancel()
    provider._last_used = 0.0  # long idle, nothing running
    provider._unload_if_idle()
    assert not provider.is_loaded()


def test_nomic_an_empty_embed_loads_nothing(fake_fastembed):
    provider = NomicEmbedProvider(idle_seconds=0)
    assert provider.embed([]) == [] and not provider.is_loaded()


def test_nomic_a_timer_that_fires_early_waits_out_the_rest(fake_fastembed):
    import time

    provider = NomicEmbedProvider(idle_seconds=60)
    provider.embed(["a"])
    provider._unload_timer.cancel()
    provider._idle_seconds = 0.3
    provider._last_used = time.monotonic()
    provider._unload_timer = early = __import__("threading").Timer(0, provider._unload_if_idle)
    early.daemon = True
    early.start()  # fires at once, before the idle time is up
    early.join(5)
    assert provider.is_loaded() and provider._unload_timer is not early
    deadline = time.monotonic() + 5
    while provider.is_loaded() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not provider.is_loaded()


@pytest.mark.parametrize("value", ["soon", "-1", "nan"])
def test_nomic_a_bad_idle_setting_names_the_variable(monkeypatch, value):
    monkeypatch.setenv("ENGRAM_EMBED_IDLE_SECONDS", value)
    with pytest.raises(ValueError, match="ENGRAM_EMBED_IDLE_SECONDS"):
        NomicEmbedProvider()


def test_nomic_idle_zero_keeps_the_model(fake_fastembed):
    import time

    provider = NomicEmbedProvider(idle_seconds=0)
    provider.embed(["a"])
    time.sleep(0.1)
    assert provider.is_loaded() and provider._unload_timer is None
