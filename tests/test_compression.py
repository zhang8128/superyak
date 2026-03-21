"""Tests for the compression module — clustering, centroid selection, MMR, dedup, instincts."""

from __future__ import annotations

import hashlib
import uuid

import pytest

from compress import Compressor


class FakeEmbeddingProvider:
    """Returns deterministic embeddings: same text = same embedding.

    Supports override_map for tests that need precise control over embeddings.
    Accepts and ignores the prefix kwarg (used by NomicEmbedProvider).
    """

    def __init__(self):
        self.override_map: dict[str, list[float]] = {}

    def embed(self, texts: list[str], **_kwargs) -> list[list[float]]:
        results = []
        for text in texts:
            if text in self.override_map:
                results.append(self.override_map[text])
            else:
                h = hashlib.md5(text.encode()).digest()
                emb = [float(b) / 255.0 for b in h] * 48  # 768 dims
                results.append(emb)
        return results

    def dimension(self) -> int:
        return 768


def _make_similar_embedding(base_text: str, noise: float = 0.001) -> list[float]:
    """Create an embedding very similar to what FakeEmbeddingProvider would produce."""
    h = hashlib.md5(base_text.encode()).digest()
    emb = [float(b) / 255.0 + noise for b in h] * 48
    return emb


class FakeDeduplicator:
    """Test dedup that uses a configurable equivalence map."""

    def __init__(self, equivalences: list[tuple[str, str]] | None = None):
        self._equivalences = equivalences or []

    def is_available(self) -> bool:
        return True

    def is_equivalent(self, a: str, b: str) -> bool:
        for x, y in self._equivalences:
            if (a == x and b == y) or (a == y and b == x):
                return True
        return False


@pytest.fixture
def embedder():
    return FakeEmbeddingProvider()


@pytest.fixture
def compressor(tmp_db, embedder):
    return Compressor(tmp_db, embedder, config=None)


def _add_episode(storage, content: str, embedding: list[float] | None = None) -> str:
    """Helper to add an episode with optional embedding."""
    eid = str(uuid.uuid4())
    storage.add_episode(id=eid, session_id="test-session", content=content, embedding=embedding)
    return eid


def test_cluster_similar_episodes(tmp_db, compressor, embedder):
    """2 episodes with identical embeddings cluster together, 2 orthogonal ones separate."""
    dim = 768
    vec_a = [0.0] * dim
    vec_a[0] = 1.0
    vec_b = [0.0] * dim
    vec_b[1] = 1.0
    vec_c = [0.0] * dim
    vec_c[2] = 1.0

    embedder.override_map["pair-1"] = vec_a
    embedder.override_map["pair-2"] = vec_a
    embedder.override_map["different-B"] = vec_b
    embedder.override_map["different-C"] = vec_c

    _add_episode(tmp_db, "pair-1", embedder.embed(["pair-1"])[0])
    _add_episode(tmp_db, "pair-2", embedder.embed(["pair-2"])[0])
    _add_episode(tmp_db, "different-B", embedder.embed(["different-B"])[0])
    _add_episode(tmp_db, "different-C", embedder.embed(["different-C"])[0])

    result = compressor.cluster_episodes()
    clusters = result["clusters"]

    assert len(clusters) >= 2
    assert result["compress_id"] is not None

    sizes = sorted([len(c["episodes"]) for c in clusters], reverse=True)
    assert sizes[0] == 2


def test_cluster_detects_reinforcement(tmp_db, compressor, embedder):
    """An episode matching an existing semantic should be marked for reinforcement."""
    text = "user prefers dark mode"
    emb = embedder.embed([text])[0]

    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content="prefers dark mode", kind="preference",
        confidence=0.6, embedding=emb, source_episode_ids=[],
    )

    _add_episode(tmp_db, text, emb)

    result = compressor.cluster_episodes()
    clusters = result["clusters"]
    assert len(clusters) == 1

    cluster = clusters[0]
    assert cluster["action"] == "reinforce"
    assert cluster["match"]["id"] == sem_id


def test_commit_creates_semantic(tmp_db, compressor, embedder):
    """Commit with action=new should create a semantic and mark episodes compressed."""
    text = "learned about Python decorators"
    emb = embedder.embed([text])[0]
    ep_id = _add_episode(tmp_db, text, emb)

    result = compressor.cluster_episodes()
    compress_id = result["compress_id"]

    summaries = [{"content": "Python decorators knowledge", "kind": "fact", "action": "new"}]
    stats = compressor.commit(compress_id, summaries)

    assert stats["episodes_processed"] == 1
    assert stats["semantics_created"] == 1
    assert stats["semantics_reinforced"] == 0

    uncompressed = tmp_db.get_uncompressed_episodes()
    assert all(ep["id"] != ep_id for ep in uncompressed)


def test_commit_reinforces_existing(tmp_db, compressor, embedder):
    """Reinforcement should increment confidence of existing semantic."""
    text = "user prefers dark mode"
    emb = embedder.embed([text])[0]

    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content="prefers dark mode", kind="preference",
        confidence=0.6, embedding=emb, source_episode_ids=[],
    )

    _add_episode(tmp_db, text, emb)

    result = compressor.cluster_episodes()
    compress_id = result["compress_id"]

    summaries = [{"content": "prefers dark mode", "kind": "preference",
                   "action": "reinforce", "semantic_id": sem_id}]
    stats = compressor.commit(compress_id, summaries)

    assert stats["semantics_reinforced"] == 1

    sem = tmp_db.get_semantic(sem_id)
    assert sem["confidence"] == pytest.approx(0.7, abs=0.01)


def test_commit_creates_instinct_from_high_confidence(tmp_db, compressor, embedder):
    """A high-confidence preference semantic should trigger instinct creation."""
    text = "always use type hints"
    emb = embedder.embed([text])[0]

    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content="always use type hints", kind="preference",
        confidence=0.85, embedding=emb, source_episode_ids=[],
    )

    _add_episode(tmp_db, "some other topic", embedder.embed(["some other topic"])[0])

    result = compressor.cluster_episodes()
    compress_id = result["compress_id"]

    summaries = [{"content": "other topic", "kind": "fact", "action": "new"}]
    stats = compressor.commit(compress_id, summaries)

    assert stats["instincts_created"] == 1

    instincts = tmp_db.get_all_instincts()
    assert len(instincts) == 1
    assert instincts[0]["trigger"] == "preference"
    assert instincts[0]["action"] == "always use type hints"


def test_low_confidence_semantic_does_not_create_instinct(tmp_db, compressor, embedder):
    """A single episode yields confidence 0.5, which should not create an instinct."""
    text = "maybe use tabs"
    emb = embedder.embed([text])[0]
    _add_episode(tmp_db, text, emb)

    result = compressor.cluster_episodes()
    compress_id = result["compress_id"]

    summaries = [{"content": "maybe use tabs", "kind": "preference", "action": "new"}]
    stats = compressor.commit(compress_id, summaries)

    assert stats["instincts_created"] == 0
    assert tmp_db.get_all_instincts() == []


def test_auto_compress_uses_centroid_selection(tmp_db, compressor, embedder):
    """auto_compress should pick centroid-nearest episode, not concatenate."""
    embs = embedder.embed(["episode one", "episode two"])
    _add_episode(tmp_db, "episode one", embs[0])
    _add_episode(tmp_db, "episode two", embs[1])

    stats = compressor.auto_compress()

    assert stats["episodes_processed"] == 2
    assert stats["semantics_created"] >= 1

    # All episodes should be compressed now
    assert len(tmp_db.get_uncompressed_episodes()) == 0

    # Auto-generated semantics should not contain " --- " for small clusters
    semantics = tmp_db.get_active_semantics()
    for sem in semantics:
        full = tmp_db.get_semantic(sem["id"])
        assert full["auto_generated"] == 1


def test_auto_compress_single_episode(tmp_db, compressor, embedder):
    """Single episode should become its own semantic verbatim."""
    emb = embedder.embed(["the only episode"])[0]
    _add_episode(tmp_db, "the only episode", emb)

    stats = compressor.auto_compress()

    assert stats["episodes_processed"] == 1
    assert stats["semantics_created"] == 1

    semantics = tmp_db.get_active_semantics()
    assert semantics[0]["content"] == "the only episode"


def test_auto_compress_large_cluster_uses_mmr(tmp_db, compressor, embedder):
    """Cluster with 4+ episodes should use MMR to pick diverse representatives."""
    dim = 768
    # 5 episodes with very similar embeddings (will cluster together)
    base = [0.5] * dim
    for i in range(5):
        vec = list(base)
        vec[i] = 1.0  # slight variation
        text = f"similar-episode-{i}"
        embedder.override_map[text] = vec
        _add_episode(tmp_db, text, vec)

    stats = compressor.auto_compress()

    assert stats["episodes_processed"] == 5
    # Should have created semantic(s) with MMR-selected representatives
    semantics = tmp_db.get_active_semantics()
    assert len(semantics) >= 1


def test_cluster_single_episode(tmp_db, compressor, embedder):
    """A single episode should form exactly one cluster."""
    emb = embedder.embed(["only episode"])[0]
    _add_episode(tmp_db, "only episode", emb)

    result = compressor.cluster_episodes()
    assert len(result["clusters"]) == 1
    assert len(result["clusters"][0]["episodes"]) == 1


def test_empty_episodes_returns_no_clusters(tmp_db, compressor):
    """No uncompressed episodes should return empty clusters."""
    result = compressor.cluster_episodes()
    assert result["clusters"] == []
    assert result["compress_id"] is None


def test_reset_all_cascades_to_instincts(tmp_db, compressor, embedder):
    """scope=full should delete instincts along with semantics."""
    text = "always test thoroughly"
    emb = embedder.embed([text])[0]

    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content=text, kind="preference",
        confidence=0.85, embedding=emb, source_episode_ids=[],
    )
    tmp_db.add_instinct(
        id="inst-reset", trigger="preference", action=text,
        source_semantic_ids=[sem_id],
    )
    assert len(tmp_db.get_all_instincts()) == 1

    compressor.cluster_episodes("full")
    assert len(tmp_db.get_all_instincts()) == 0
    assert tmp_db.get_table_count("semantics") == 0
    assert tmp_db.get_table_count("instinct_sources") == 0


def test_auto_compress_marks_auto_generated(tmp_db, compressor, embedder):
    """auto_compress should flag created semantics as auto_generated."""
    emb = embedder.embed(["auto episode"])[0]
    _add_episode(tmp_db, "auto episode", emb)

    compressor.auto_compress()

    semantics = tmp_db.get_active_semantics()
    assert len(semantics) >= 1
    for sem in semantics:
        full = tmp_db.get_semantic(sem["id"])
        assert full["auto_generated"] == 1


def test_llm_dedup_prevents_duplicate_instincts(tmp_db, embedder):
    """LLM dedup should prevent creating an instinct that duplicates an existing one."""
    dedup = FakeDeduplicator(equivalences=[
        ("prefer terse communication", "don't add trailing summaries"),
    ])
    compressor = Compressor(tmp_db, embedder, config=None, deduplicator=dedup)

    # Create existing instinct
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content="prefer terse communication", kind="preference",
        confidence=0.85, embedding=embedder.embed(["prefer terse communication"])[0],
        source_episode_ids=[],
    )
    tmp_db.add_instinct(
        id="existing-inst", trigger="preference",
        action="prefer terse communication",
        source_semantic_ids=[sem_id],
    )

    # Create a new high-confidence semantic that says the same thing differently
    new_sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=new_sem_id, content="don't add trailing summaries", kind="preference",
        confidence=0.85, embedding=embedder.embed(["don't add trailing summaries"])[0],
        source_episode_ids=[],
    )

    # Trigger instinct creation — should detect duplicate via LLM dedup
    _add_episode(tmp_db, "unrelated filler", embedder.embed(["unrelated filler"])[0])
    result = compressor.cluster_episodes()
    summaries = [{"content": "filler", "kind": "fact", "action": "new"}]
    stats = compressor.commit(result["compress_id"], summaries)

    # Should NOT have created a new instinct
    assert stats["instincts_created"] == 0
    assert len(tmp_db.get_all_instincts()) == 1


def test_dedup_unavailable_falls_back_to_embeddings(tmp_db, embedder):
    """When dedup LLM is unavailable, falls back to embedding similarity."""
    compressor = Compressor(tmp_db, embedder, config=None, deduplicator=None)

    text = "always use type hints"
    emb = embedder.embed([text])[0]

    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content=text, kind="preference",
        confidence=0.85, embedding=emb, source_episode_ids=[],
    )

    # Without dedup, instinct should be created normally
    _add_episode(tmp_db, "filler", embedder.embed(["filler"])[0])
    result = compressor.cluster_episodes()
    summaries = [{"content": "filler", "kind": "fact", "action": "new"}]
    stats = compressor.commit(result["compress_id"], summaries)

    assert stats["instincts_created"] == 1
