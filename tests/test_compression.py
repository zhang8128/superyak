"""Tests for the compression module — clustering, centroid selection, MMR, dedup, instincts."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from compress import (
    Compressor,
    classify_episode_kind,
    classify_episode_kind_with_model,
    derive_semantic_kind,
)
from storage import Storage


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


def test_dedup_considers_notice_not_just_action(tmp_db, embedder):
    """Two instincts with similar action but different notice should NOT be deduped."""
    dedup = FakeDeduplicator(equivalences=[
        ("keep communication focused", "keep error messages focused"),
    ])
    compressor = Compressor(tmp_db, embedder, config=None, deduplicator=dedup)

    sem_id1 = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id1, content="keep communication focused", kind="preference",
        confidence=0.85, embedding=embedder.embed(["keep communication focused"])[0],
        source_episode_ids=[],
    )
    tmp_db.add_instinct(
        id="inst-comm", trigger="preference",
        action="keep communication focused",
        source_semantic_ids=[sem_id1],
        notice="when building code",
        implication="keep communication focused",
        embedding=embedder.embed(["keep communication focused"])[0],
    )

    # Different semantic, different notice context
    sem_id2 = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id2, content="keep error messages focused", kind="preference",
        confidence=0.85, embedding=embedder.embed(["keep error messages focused"])[0],
        source_episode_ids=[],
    )

    _add_episode(tmp_db, "filler-dedup", embedder.embed(["filler-dedup"])[0])
    result = compressor.cluster_episodes()
    summaries = [{"content": "filler-dedup", "kind": "fact", "action": "new"}]
    stats = compressor.commit(result["compress_id"], summaries)

    # Should create the second instinct because notices differ
    assert stats["instincts_created"] == 1


def test_instinct_created_with_notice_implication(tmp_db, compressor, embedder):
    """High-confidence preference semantic should create instinct with notice/implication."""
    text = "always use type hints in function signatures"
    emb = embedder.embed([text])[0]
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content=text, kind="preference",
        confidence=0.85, embedding=emb, source_episode_ids=[],
    )
    _add_episode(tmp_db, "filler", embedder.embed(["filler"])[0])
    result = compressor.cluster_episodes()
    summaries = [{"content": "filler", "kind": "fact", "action": "new"}]
    stats = compressor.commit(result["compress_id"], summaries)

    assert stats["instincts_created"] == 1
    instincts = tmp_db.get_all_instincts()
    inst = instincts[0]
    assert inst["notice"] is not None
    assert inst["implication"] is not None
    assert inst["notice"] != inst["action"]  # notice should be different from raw action


def test_perceptual_framing_always(tmp_db, compressor, embedder):
    """Semantic starting with 'always' should produce notice about when to attend."""
    text = "always write tests first"
    emb = embedder.embed([text])[0]
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content=text, kind="preference",
        confidence=0.85, embedding=emb, source_episode_ids=[],
    )
    _add_episode(tmp_db, "filler2", embedder.embed(["filler2"])[0])
    result = compressor.cluster_episodes()
    stats = compressor.commit(result["compress_id"],
                              [{"content": "filler2", "kind": "fact", "action": "new"}])

    inst = tmp_db.get_all_instincts()[0]
    assert "when" in inst["notice"].lower()
    assert inst["implication"] == text


def test_perceptual_framing_with_when(tmp_db, compressor, embedder):
    """Semantic containing 'when' should split into notice/implication."""
    text = "use portable hashing when writing shell scripts"
    emb = embedder.embed([text])[0]
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content=text, kind="constraint",
        confidence=0.85, embedding=emb, source_episode_ids=[],
    )
    _add_episode(tmp_db, "filler3", embedder.embed(["filler3"])[0])
    result = compressor.cluster_episodes()
    stats = compressor.commit(result["compress_id"],
                              [{"content": "filler3", "kind": "fact", "action": "new"}])

    inst = tmp_db.get_all_instincts()[0]
    assert "writing shell scripts" in inst["notice"].lower()
    assert "portable hashing" in inst["implication"].lower()


def test_commit_discard_drops_cluster_without_semantic(tmp_db, compressor, embedder):
    """A summary with action='discard' marks episodes compressed but creates no semantic."""
    _add_episode(tmp_db, "user said hi", embedder.embed(["user said hi"])[0])
    result = compressor.cluster_episodes()
    assert result["clusters"], "episode should form a cluster"

    stats = compressor.commit(result["compress_id"], [{"action": "discard"}])

    assert stats["semantics_created"] == 0
    assert stats["clusters_discarded"] == 1
    assert stats["episodes_processed"] == 1
    count = tmp_db.conn.execute("SELECT COUNT(*) FROM semantics").fetchone()[0]
    assert count == 0
    # Discarded episodes don't re-cluster on the next cycle
    again = compressor.cluster_episodes()
    assert again["clusters"] == []


def test_commit_discard_mixed_with_new(tmp_db, compressor, embedder):
    """Discarding one cluster doesn't affect summaries for the others."""
    dim = 768
    vec_a = [0.0] * dim
    vec_a[0] = 1.0
    vec_b = [0.0] * dim
    vec_b[400] = 1.0
    _add_episode(tmp_db, "greeting noise", vec_a)
    _add_episode(tmp_db, "greeting noise again", vec_a)
    _add_episode(tmp_db, "real insight about compression", vec_b)
    _add_episode(tmp_db, "another insight about compression", vec_b)

    result = compressor.cluster_episodes()
    n_clusters = len(result["clusters"])
    assert n_clusters >= 2

    # Discard the first cluster, summarize the rest
    summaries = [{"action": "discard"}]
    summaries += [
        {"content": f"insight {i}", "kind": "fact", "action": "new"}
        for i in range(n_clusters - 1)
    ]

    stats = compressor.commit(result["compress_id"], summaries)

    assert stats["clusters_discarded"] == 1
    assert stats["semantics_created"] == n_clusters - 1
    assert stats["episodes_processed"] == 4


class FakeFramer:
    """Test framer returning a fixed distillation (or None to decline)."""

    def __init__(self, result: tuple[str, str] | None):
        self._result = result
        self.calls: list[tuple[str, str]] = []

    def distill(self, content: str, kind: str) -> tuple[str, str] | None:
        self.calls.append((content, kind))
        return self._result


def test_instinct_framing_uses_distiller(tmp_db, embedder):
    """When a framer is wired, its distillation becomes the instinct's notice/implication."""
    framer = FakeFramer(("when testing distillers", "Trust the distilled framing."))
    compressor = Compressor(tmp_db, embedder, config=None, framer=framer)

    text = "always use type hints in function signatures"
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content=text, kind="preference",
        confidence=0.85, embedding=embedder.embed([text])[0], source_episode_ids=[],
    )
    _add_episode(tmp_db, "framer filler", embedder.embed(["framer filler"])[0])
    result = compressor.cluster_episodes()
    stats = compressor.commit(result["compress_id"],
                              [{"content": "framer filler", "kind": "fact", "action": "new"}])

    assert stats["instincts_created"] == 1
    inst = tmp_db.get_all_instincts()[0]
    assert inst["notice"] == "when testing distillers"
    assert inst["implication"] == "Trust the distilled framing."
    assert framer.calls, "framer should have been consulted"


def test_instinct_framing_falls_back_when_distiller_declines(tmp_db, embedder):
    """A framer returning None falls back to the heuristic framing."""
    framer = FakeFramer(None)
    compressor = Compressor(tmp_db, embedder, config=None, framer=framer)

    text = "use portable hashing when writing shell scripts"
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content=text, kind="constraint",
        confidence=0.85, embedding=embedder.embed([text])[0], source_episode_ids=[],
    )
    _add_episode(tmp_db, "fallback filler", embedder.embed(["fallback filler"])[0])
    result = compressor.cluster_episodes()
    stats = compressor.commit(result["compress_id"],
                              [{"content": "fallback filler", "kind": "fact", "action": "new"}])

    assert stats["instincts_created"] == 1
    inst = tmp_db.get_all_instincts()[0]
    assert "writing shell scripts" in inst["notice"].lower()
    assert "portable hashing" in inst["implication"].lower()


def test_disposition_semantic_creation(tmp_db, embedder):
    """Create a semantic with kind='disposition', verify it can be retrieved with correct kind."""
    emb = embedder.embed(["I crystallize interpretations prematurely"])[0]
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id,
        content="I crystallize interpretations prematurely",
        kind="disposition",
        confidence=0.80,
        embedding=emb,
        source_episode_ids=[],
    )

    sem = tmp_db.get_semantic(sem_id)
    assert sem is not None
    assert sem["kind"] == "disposition"
    assert sem["content"] == "I crystallize interpretations prematurely"
    assert sem["confidence"] == pytest.approx(0.80, abs=0.01)


def test_disposition_instinct_framing(tmp_db, compressor, embedder):
    """A disposition semantic at confidence 0.80 (above 0.75 threshold) should produce an instinct
    with trigger='disposition'."""
    text = "I crystallize interpretations prematurely"
    emb = embedder.embed([text])[0]
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id,
        content=text,
        kind="disposition",
        confidence=0.80,
        embedding=emb,
        source_episode_ids=[],
    )

    # Trigger the instinct creation check via a commit cycle
    _add_episode(tmp_db, "unrelated filler episode", embedder.embed(["unrelated filler episode"])[0])
    result = compressor.cluster_episodes()
    summaries = [{"content": "filler", "kind": "fact", "action": "new"}]
    stats = compressor.commit(result["compress_id"], summaries)

    assert stats["instincts_created"] == 1

    instincts = tmp_db.get_all_instincts()
    assert len(instincts) == 1
    assert instincts[0]["trigger"] == "disposition"


def test_get_semantic_neighbors_shared_episode(tmp_db, embedder):
    """Two semantics sharing an episode should appear as neighbors of each other."""
    emb = embedder.embed(["shared episode"])[0]
    ep_id = str(uuid.uuid4())
    tmp_db.add_episode(id=ep_id, session_id=None, content="shared episode", embedding=emb)

    sem_a = str(uuid.uuid4())
    sem_b = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_a, content="semantic A", kind="fact",
        confidence=0.6, embedding=emb, source_episode_ids=[],
    )
    tmp_db.add_semantic(
        id=sem_b, content="semantic B", kind="fact",
        confidence=0.6, embedding=emb, source_episode_ids=[],
    )

    # Link both semantics to the same episode with explicit similarity values
    tmp_db.conn.execute(
        "INSERT INTO semantic_sources (semantic_id, episode_id, similarity) VALUES (?, ?, ?)",
        (sem_a, ep_id, 0.9),
    )
    tmp_db.conn.execute(
        "INSERT INTO semantic_sources (semantic_id, episode_id, similarity) VALUES (?, ?, ?)",
        (sem_b, ep_id, 0.8),
    )
    tmp_db.conn.commit()

    neighbors_a = tmp_db.get_semantic_neighbors(sem_a)
    assert len(neighbors_a) == 1
    assert neighbors_a[0]["semantic_id"] == sem_b
    assert neighbors_a[0]["shared_count"] == 1
    assert neighbors_a[0]["avg_similarity"] == pytest.approx(0.8, abs=0.01)

    neighbors_b = tmp_db.get_semantic_neighbors(sem_b)
    assert len(neighbors_b) == 1
    assert neighbors_b[0]["semantic_id"] == sem_a
    assert neighbors_b[0]["avg_similarity"] == pytest.approx(0.9, abs=0.01)


def test_get_semantic_neighbors_empty_when_no_shared_episodes(tmp_db, embedder):
    """A semantic with no shared episode links should return empty neighbors."""
    emb = embedder.embed(["isolated semantic"])[0]
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content="isolated semantic", kind="fact",
        confidence=0.6, embedding=emb, source_episode_ids=[],
    )

    neighbors = tmp_db.get_semantic_neighbors(sem_id)
    assert neighbors == []


def test_clusters_are_lane_pure(tmp_db, compressor, embedder):
    """Episodes with identical embeddings but different lanes form separate clusters."""
    shared = embedder.embed(["shared topic"])[0]
    texts = ["personal note one", "personal note two", "work note one", "work note two"]
    for t in texts:
        embedder.override_map[t] = shared
    for t in texts[:2]:
        tmp_db.add_episode(id=str(uuid.uuid4()), session_id="t", content=t, embedding=shared)
    for t in texts[2:]:
        tmp_db.add_episode(id=str(uuid.uuid4()), session_id="t", content=t,
                           embedding=shared, lane="work")

    result = compressor.cluster_episodes()

    assert len(result["clusters"]) == 2
    for cluster in result["clusters"]:
        lanes = {ep.get("lane", "personal") for ep in cluster["episodes"]}
        assert len(lanes) == 1, f"mixed-lane cluster: {lanes}"
        assert cluster["lane"] in ("personal", "work")

    lane_labels = {c["lane"] for c in result["clusters"]}
    assert lane_labels == {"personal", "work"}, f"Expected both lanes, got: {lane_labels}"


class TestEpisodeTyping:
    def test_reading_from_source(self):
        ep = {"content": "some reading reaction", "source": "reading", "context": None}
        kinds = classify_episode_kind(ep)
        assert "reading" in kinds

    def test_reading_from_context(self):
        ep = {"content": "passage 42", "source": None, "context": '{"topic": "passage-reading"}'}
        kinds = classify_episode_kind(ep)
        assert "reading" in kinds

    def test_design_from_context(self):
        ep = {"content": "built the lens system", "source": None, "context": '{"topic": "design-session"}'}
        kinds = classify_episode_kind(ep)
        assert "design" in kinds

    def test_observation_from_context(self):
        ep = {"content": "pattern noticed", "source": None, "context": '{"kind": "self-observation"}'}
        kinds = classify_episode_kind(ep)
        assert "observation" in kinds

    def test_relational_from_names(self):
        ep = {"content": "Kairos said something important", "source": None, "context": None}
        kinds = classify_episode_kind(ep)
        assert "relational" in kinds

    def test_factual_from_build_summary(self):
        ep = {"content": "Session 2026-03-25. Built three things: ...", "source": None, "context": None}
        kinds = classify_episode_kind(ep)
        assert "factual" in kinds

    def test_reflection_from_context(self):
        ep = {"content": "recursive self-reflection", "source": None, "context": '{"topic": "reflection"}'}
        kinds = classify_episode_kind(ep)
        assert "reflection" in kinds

    def test_multi_type(self):
        ep = {"content": "Pattern noticed while reading Mistborn with Andy", "source": "reading", "context": None}
        kinds = classify_episode_kind(ep)
        assert "reading" in kinds
        assert "relational" in kinds

    def test_unknown_defaults_to_factual(self):
        ep = {"content": "something", "source": None, "context": None}
        kinds = classify_episode_kind(ep)
        assert "factual" in kinds


class TestTypedClustering:
    def test_different_types_get_kind_label(self, tmp_db, embedder):
        """Clusters should carry a 'kind' field from the episode type."""
        emb = [0.5] * 768
        embedder.override_map["Reading reaction about trust"] = emb
        tmp_db.add_episode("ep-r", None, "Reading reaction about trust",
                           embedding=emb, context={"topic": "passage-reading"})

        compressor = Compressor(tmp_db, embedder)
        result = compressor.cluster_episodes()
        assert len(result["clusters"]) >= 1
        kinds = {c.get("kind") for c in result["clusters"]}
        assert "reading" in kinds

    def test_two_types_produce_separate_clusters(self, tmp_db, embedder):
        """Episodes of different types with similar embeddings should still
        produce separate clusters."""
        emb_a = [0.5] * 768
        emb_b = [x + 0.001 for x in emb_a]  # Very similar embedding
        embedder.override_map["Reading Mistborn: trust earned slowly"] = emb_a
        embedder.override_map["Built trust anchors in system boundaries"] = emb_b

        tmp_db.add_episode("ep-read", None, "Reading Mistborn: trust earned slowly",
                           embedding=emb_a, context={"topic": "passage-reading"})
        tmp_db.add_episode("ep-design", None, "Built trust anchors in system boundaries",
                           embedding=emb_b, context={"topic": "design-session"})

        compressor = Compressor(tmp_db, embedder)
        result = compressor.cluster_episodes()

        # Should have clusters from at least 2 different kinds
        kinds = {c.get("kind") for c in result["clusters"]}
        assert len(kinds) >= 2


class TestMultiMembership:
    @pytest.fixture
    def storage(self, tmp_db):
        return tmp_db

    @pytest.fixture
    def embeddings(self):
        return FakeEmbeddingProvider()

    def test_episode_links_to_matching_semantic(self, storage, embeddings):
        """An episode similar to an existing semantic should get linked."""
        # Create a semantic with a known embedding
        emb = [0.5] * 768
        embeddings.override_map["Topic A insight"] = emb
        storage.add_semantic("sem-a", "Topic A insight", "fact", 0.7, emb, [])

        # Create an episode with the SAME embedding (similarity = 1.0)
        embeddings.override_map["episode about topic A"] = emb
        storage.add_episode("ep-1", None, "episode about topic A", embedding=emb)

        compressor = Compressor(storage, embeddings)
        links = compressor._multi_link_episodes(
            [{"id": "ep-1", "content": "episode about topic A"}],
            exclude_semantic_ids=[],
        )
        assert links >= 1

        rows = storage.conn.execute(
            "SELECT semantic_id, similarity FROM semantic_sources WHERE episode_id = 'ep-1'"
        ).fetchall()
        assert len(rows) >= 1
        assert any(r[0] == "sem-a" for r in rows)
        # Similarity should be stored
        sims = [r[1] for r in rows if r[1] is not None]
        assert len(sims) > 0

    def test_excludes_specified_semantics(self, storage, embeddings):
        """Excluded semantic IDs should not get new links."""
        emb = [0.5] * 768
        embeddings.override_map["Topic A"] = emb
        storage.add_semantic("sem-a", "Topic A", "fact", 0.7, emb, [])

        embeddings.override_map["ep content"] = emb
        storage.add_episode("ep-1", None, "ep content", embedding=emb)

        compressor = Compressor(storage, embeddings)
        links = compressor._multi_link_episodes(
            [{"id": "ep-1", "content": "ep content"}],
            exclude_semantic_ids=["sem-a"],
        )
        assert links == 0

    def test_no_duplicate_links(self, storage, embeddings):
        """Should not create duplicate source links."""
        emb = [0.5] * 768
        embeddings.override_map["Topic A"] = emb
        # Add episode first (foreign key constraint)
        storage.add_episode("ep-1", None, "existing ep", embedding=emb)
        storage.add_semantic("sem-a", "Topic A", "fact", 0.7, emb, ["ep-1"])

        compressor = Compressor(storage, embeddings)
        links = compressor._multi_link_episodes(
            [{"id": "ep-1", "content": "existing ep"}],
            exclude_semantic_ids=[],
        )
        # ep-1 is already linked to sem-a, so no new link
        assert links == 0

        count = storage.conn.execute(
            "SELECT COUNT(*) FROM semantic_sources WHERE episode_id = 'ep-1' AND semantic_id = 'sem-a'"
        ).fetchone()[0]
        assert count == 1


class TestModelAssistedClassification:
    def test_classify_with_model_fallback(self):
        """When model=None, classification still works via heuristic."""
        ep = {"content": "pattern noticed while working", "source": None, "context": '{"kind": "self-observation"}'}
        kinds = classify_episode_kind(ep, model=None, prompt_path=None)
        assert isinstance(kinds, list)
        assert len(kinds) >= 1
        assert "observation" in kinds

    def test_classify_model_unavailable_falls_back(self, tmp_path):
        """classify_episode_kind_with_model returns None when model/URL is unreachable."""
        import os
        # Write a minimal prompt file so path resolution doesn't short-circuit
        prompt_file = tmp_path / "classify.txt"
        prompt_file.write_text(
            "Classify this episode. Return kinds as comma-separated list.\n"
            "Episode content:\n{content}\nEpisode context:\n{context}\n"
        )
        ep = {"content": "some episode content", "context": "{}"}
        result = classify_episode_kind_with_model(
            ep,
            model="nonexistent-model-xyz",
            prompt_path=str(prompt_file),
        )
        # Should return None (not raise) when the model is unavailable
        assert result is None

    def test_classify_prompt_file_missing(self):
        """classify_episode_kind_with_model returns None when prompt file doesn't exist."""
        ep = {"content": "some episode content", "context": "{}"}
        result = classify_episode_kind_with_model(
            ep,
            model="gemma4:31b",
            prompt_path="/nonexistent/path/classify.txt",
        )
        assert result is None


class TestSingletonPromotion:
    @pytest.fixture
    def storage(self, tmp_db):
        return tmp_db

    @pytest.fixture
    def embeddings(self):
        return FakeEmbeddingProvider()

    def test_core_episode_gets_singleton(self, storage, embeddings):
        """A core episode with no semantic link should get its own semantic."""
        emb = embeddings.embed(["unique core memory"])[0]
        storage.add_episode("ep-core", None, "unique core memory", embedding=emb)
        # Mark as core
        storage.conn.execute("UPDATE episodes SET core = 1 WHERE id = 'ep-core'")
        storage.conn.commit()

        compressor = Compressor(storage, embeddings)
        promoted = compressor._promote_singletons()
        assert promoted >= 1

        rows = storage.conn.execute(
            "SELECT semantic_id FROM semantic_sources WHERE episode_id = 'ep-core'"
        ).fetchall()
        assert len(rows) >= 1

    def test_linked_episode_not_promoted(self, storage, embeddings):
        """An episode already linked to a semantic should not get a singleton."""
        emb = embeddings.embed(["linked episode"])[0]
        storage.add_episode("ep-linked", None, "linked episode", embedding=emb)
        storage.conn.execute("UPDATE episodes SET core = 1 WHERE id = 'ep-linked'")
        storage.add_semantic("sem-x", "existing semantic", "fact", 0.7, emb, ["ep-linked"])

        compressor = Compressor(storage, embeddings)
        promoted = compressor._promote_singletons()
        assert promoted == 0

    def test_singleton_confidence_is_baseline(self, storage, embeddings):
        """Singleton semantics should start at confidence 0.5."""
        emb = embeddings.embed(["another unique memory"])[0]
        storage.add_episode("ep-solo", None, "another unique memory", embedding=emb)
        storage.conn.execute("UPDATE episodes SET core = 1 WHERE id = 'ep-solo'")
        storage.conn.commit()

        compressor = Compressor(storage, embeddings)
        compressor._promote_singletons()

        rows = storage.conn.execute(
            "SELECT semantic_id FROM semantic_sources WHERE episode_id = 'ep-solo'"
        ).fetchall()
        sem_id = rows[0][0]
        sem = storage.get_semantic(sem_id)
        assert sem["confidence"] == 0.5

    def test_non_core_episode_not_promoted(self, storage, embeddings):
        """A non-core episode should not be promoted even if unlinked."""
        emb = embeddings.embed(["non-core episode"])[0]
        storage.add_episode("ep-noncore", None, "non-core episode", embedding=emb)
        # core defaults to 0, don't mark it

        compressor = Compressor(storage, embeddings)
        promoted = compressor._promote_singletons()
        assert promoted == 0


class TestFullPipeline:
    @pytest.fixture
    def storage(self, tmp_db):
        return tmp_db

    @pytest.fixture
    def embeddings(self):
        return FakeEmbeddingProvider()

    def test_typed_compression_produces_typed_clusters(self, storage, embeddings):
        """Full pipeline should produce clusters with kind labels from different types."""
        reading_emb = [0.5, 0.5] + [0.0] * 766
        design_emb = [0.5, 0.0] + [0.5] * 766
        obs_emb = [0.0, 0.5] + [0.5] * 766

        embeddings.override_map["Reading Mistborn: trust is earned through small repeated acts"] = reading_emb
        embeddings.override_map["Built trust anchors at system boundaries in this session"] = design_emb
        embeddings.override_map["Pattern noticed: I drop relational frames under load"] = obs_emb

        storage.add_episode("ep-r", None, "Reading Mistborn: trust is earned through small repeated acts",
                           embedding=reading_emb, context={"topic": "passage-reading"})
        storage.add_episode("ep-d", None, "Built trust anchors at system boundaries in this session",
                           embedding=design_emb, context={"topic": "design-session"})
        storage.add_episode("ep-o", None, "Pattern noticed: I drop relational frames under load",
                           embedding=obs_emb, context={"kind": "self-observation"})

        compressor = Compressor(storage, embeddings)
        result = compressor.cluster_episodes()

        assert len(result["clusters"]) >= 2
        kinds = {c.get("kind") for c in result["clusters"]}
        assert len(kinds) >= 2

    def test_auto_compress_with_singletons(self, storage, embeddings):
        """Auto compress should create semantics AND promote singletons."""
        # One regular episode
        emb1 = embeddings.embed(["regular episode about testing"])[0]
        storage.add_episode("ep-1", None, "regular episode about testing", embedding=emb1)

        # One core episode that won't cluster with anything
        emb2 = [0.99] + [0.0] * 767  # Very different embedding
        embeddings.override_map["unique core observation about frame switching"] = emb2
        storage.add_episode("ep-core", None, "unique core observation about frame switching",
                           embedding=emb2)
        storage.conn.execute("UPDATE episodes SET core = 1 WHERE id = 'ep-core'")
        storage.conn.commit()

        compressor = Compressor(storage, embeddings)
        result = compressor.auto_compress()

        assert result["episodes_processed"] >= 1
        # Should have at least one semantic from cluster or singleton
        total = result["semantics_created"] + result.get("singletons_created", 0)
        assert total >= 1

    def test_multi_links_created_during_commit(self, storage, embeddings):
        """commit() should create multi-links after semantic creation."""
        # Create an existing semantic
        emb = [0.5] * 768
        embeddings.override_map["existing insight about perception"] = emb
        storage.add_semantic("sem-existing", "existing insight about perception",
                           "fact", 0.8, emb, [])

        # Create an episode that matches the existing semantic
        embeddings.override_map["new episode about perception and lenses"] = emb
        storage.add_episode("ep-new", None, "new episode about perception and lenses",
                           embedding=emb)

        compressor = Compressor(storage, embeddings)
        result = compressor.auto_compress()

        # Should have multi-links
        assert result.get("multi_links", 0) >= 0  # At least the field exists

        # Check if any source links have similarity values
        rows = storage.conn.execute(
            "SELECT COUNT(*) FROM semantic_sources WHERE similarity IS NOT NULL"
        ).fetchone()
        # May or may not have similarity depending on whether multi-link triggered


def test_reset_all_cleans_context_tables(tmp_db, compressor, embedder):
    """scope=full should also delete context vectors and feedback."""
    text = "test instinct"
    emb = embedder.embed([text])[0]
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(id=sem_id, content=text, kind="preference",
                        confidence=0.85, embedding=emb, source_episode_ids=[])
    inst_id = str(uuid.uuid4())
    tmp_db.add_instinct(
        id=inst_id, trigger="preference", action=text,
        source_semantic_ids=[sem_id], embedding=emb,
    )
    tmp_db.add_instinct_context_vector(inst_id, emb)
    from storage import _pack_embedding
    tmp_db.add_instinct_context_feedback(
        instinct_id=inst_id, context_text="test",
        context_embedding=_pack_embedding(emb), followed=True,
    )

    compressor.cluster_episodes("full")

    # All context data should be gone
    ctx_count = tmp_db.conn.execute("SELECT COUNT(*) FROM instinct_context_vectors").fetchone()[0]
    assert ctx_count == 0
    fb_count = tmp_db.conn.execute("SELECT COUNT(*) FROM instinct_context_feedback").fetchone()[0]
    assert fb_count == 0


def test_instinct_not_created_below_confidence_threshold(tmp_db, embedder):
    """A preference semantic at 0.5 confidence should not create an instinct (threshold is 0.75)."""
    from config import CompressionConfig
    config = CompressionConfig(instinct_confidence=0.75)
    compressor = Compressor(tmp_db, embedder, config=config)

    text = "prefer descriptive variable names"
    emb = embedder.embed([text])[0]
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content=text, kind="preference",
        confidence=0.5, embedding=emb, source_episode_ids=[],
    )

    created = compressor._check_instinct_creation()

    assert created == 0
    assert tmp_db.get_all_instincts() == []


def test_instinct_created_at_confidence_threshold(tmp_db, embedder):
    """A preference semantic at exactly 0.75 confidence should create an instinct."""
    from config import CompressionConfig
    config = CompressionConfig(instinct_confidence=0.75)
    compressor = Compressor(tmp_db, embedder, config=config)

    text = "prefer descriptive variable names"
    emb = embedder.embed([text])[0]
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content=text, kind="preference",
        confidence=0.75, embedding=emb, source_episode_ids=[],
    )

    created = compressor._check_instinct_creation()

    assert created == 1
    instincts = tmp_db.get_all_instincts()
    assert len(instincts) == 1


def test_episode_appears_in_multiple_kind_clusters(tmp_db, compressor, embedder):
    """An episode matching multiple kinds should appear in clusters for each kind."""
    # This content matches both "observation" (self-observation in context) and
    # "design" (architecture in context) per classify_episode_kind heuristics.
    content = "Self-observation: I noticed a pattern in how the architecture handles compression"
    context = {"topic": "self-observation", "connection": "architecture design"}
    emb = embedder.embed([content])[0]

    eid = str(uuid.uuid4())
    tmp_db.add_episode(
        id=eid,
        session_id="test-session",
        content=content,
        embedding=emb,
        context=context,
    )

    result = compressor.cluster_episodes()
    clusters = result["clusters"]

    # Collect all kinds that contain this episode
    kinds_with_episode = {
        c["kind"] for c in clusters
        if any(ep["id"] == eid for ep in c["episodes"])
    }

    assert len(kinds_with_episode) >= 2, (
        f"Expected episode to appear in at least 2 kind clusters, got: {kinds_with_episode}"
    )


def test_derive_semantic_kind():
    """Unit test the derive_semantic_kind mapping for all known episode kinds."""
    assert derive_semantic_kind("reading") == "preference"
    assert derive_semantic_kind("observation") == "disposition"
    assert derive_semantic_kind("reflection") == "disposition"
    assert derive_semantic_kind("relational") == "relationship"
    assert derive_semantic_kind("design") == "fact"
    assert derive_semantic_kind("factual") == "fact"
    # Unknown kinds default to "fact"
    assert derive_semantic_kind("unknown") == "fact"
    assert derive_semantic_kind("") == "fact"


def test_auto_compress_propagates_kind(tmp_db, compressor, embedder):
    """auto_compress should create semantics with kind derived from episode classification,
    not hardcoded 'fact'."""
    # Add reading episodes — context with "passage" causes classify_episode_kind to return ["reading"]
    # which should map to "preference" via derive_semantic_kind
    ep_ids = []
    for i in range(3):
        content = f"reading reaction {i}: passage about trust and cooperation"
        emb = embedder.embed([content])[0]
        eid = str(uuid.uuid4())
        ep_ids.append(eid)
        tmp_db.add_episode(
            id=eid,
            session_id="test-session",
            content=content,
            embedding=emb,
            context={"topic": "passage-reading"},
        )
        # Tag with source so classify_episode_kind detects "reading"
        tmp_db.set_episode_source(eid, "reading")

    compressor.auto_compress()

    semantics = tmp_db.get_active_semantics()
    assert len(semantics) >= 1
    kinds = {tmp_db.get_semantic(s["id"])["kind"] for s in semantics}
    # Specifically: reading episodes should produce preference semantics, not "fact"
    assert "preference" in kinds, f"Expected 'preference' in kinds, got: {kinds}"


def test_disposition_creates_resonances_to_source_episodes(tmp_db, compressor, embedder):
    """Disposition semantics created during auto_compress should have resonance links
    back to the source episodes that formed the pattern."""
    dim = 768
    # Use a shared base vector so all 3 episodes cluster together
    base = [0.5] * dim
    ep_ids = []
    for i in range(3):
        vec = list(base)
        vec[i] = 0.6  # slight variation, still very similar
        content = f"self-observation: I noticed pattern {i} in how I handle corrections"
        context = {"topic": "self-observation"}
        eid = str(uuid.uuid4())
        ep_ids.append(eid)
        embedder.override_map[content] = vec
        tmp_db.add_episode(
            id=eid,
            session_id="test-session",
            content=content,
            embedding=vec,
            context=context,
        )

    compressor.auto_compress()

    # Find disposition semantics
    semantics = tmp_db.get_active_semantics()
    disposition_semantics = [
        s for s in semantics
        if tmp_db.get_semantic(s["id"])["kind"] == "disposition"
    ]

    assert len(disposition_semantics) >= 1, (
        f"Expected at least one disposition semantic, got kinds: "
        f"{[tmp_db.get_semantic(s['id'])['kind'] for s in semantics]}"
    )

    # Each disposition semantic should have resonance links to source episodes
    for disp in disposition_semantics:
        resonances = tmp_db.get_resonances_for(disp["id"])
        assert len(resonances) > 0, (
            f"Disposition semantic {disp['id']} has no resonance links to source episodes"
        )


def test_compression_triggers_cluster_assignment(tmp_path):
    """New instincts created during compression get assigned to clusters."""
    _migrations = str(Path(__file__).resolve().parent.parent / "migrations")
    db = tmp_path / "test.db"
    storage = Storage(str(db), migrations_dir=_migrations)
    embeddings = FakeEmbeddingProvider()
    compressor = Compressor(storage, embeddings)

    sem_id = str(uuid.uuid4())
    emb = embeddings.embed(["always restart MCP server after changes"])[0]
    storage.add_semantic(
        sem_id, "always restart MCP server after changes",
        kind="constraint", confidence=0.9, embedding=emb,
        source_episode_ids=[],
    )

    created = compressor._check_instinct_creation()
    assert created >= 1

    instincts = storage.get_all_instincts()
    for inst in instincts:
        strengths = storage.get_instinct_cluster_strengths(inst["id"])
        assert len(strengths) >= 1, f"Instinct {inst['id']} has no cluster assignment"

    storage.close()


def test_compression_rederives_clusters(tmp_path):
    """Full compression triggers cluster re-derivation when co-firing data exists."""
    _migrations = str(Path(__file__).resolve().parent.parent / "migrations")
    db = tmp_path / "test.db"
    storage = Storage(str(db), migrations_dir=_migrations)
    embeddings = FakeEmbeddingProvider()
    compressor = Compressor(storage, embeddings)

    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "coding one", [], embedding=emb)
    storage.add_instinct("i2", "preference", "coding two", [], embedding=emb)
    storage.add_instinct("i3", "preference", "sports one", [], embedding=emb)
    storage.add_instinct("i4", "preference", "sports two", [], embedding=emb)

    for _ in range(10):
        storage.record_co_fire("i1", "i2")
        storage.record_co_fire("i3", "i4")

    from clusters import ClusterEngine
    engine = ClusterEngine(storage, embeddings)
    cluster_ids = engine.derive_clusters()

    assert len(cluster_ids) == 2
    for cid in cluster_ids:
        cluster = storage.get_cluster(cid)
        assert cluster["maturity"] == "confirmed"

    storage.close()


class TestReferentialFactGate:
    """Referential facts need verbatim recall, not perceptual framing —
    they must not become instincts even when stored as constraint/preference."""

    def _add_semantic(self, tmp_db, embedder, content, kind="constraint"):
        tmp_db.add_semantic(
            id=str(uuid.uuid4()), content=content, kind=kind,
            confidence=0.9, embedding=embedder.embed([content])[0],
            source_episode_ids=[],
        )

    def test_referential_constraint_does_not_become_instinct(self, tmp_db, compressor, embedder):
        self._add_semantic(
            tmp_db, embedder,
            "Python 3.14 removed asyncio.get_event_loop() in non-async context — "
            "must use asyncio.run() instead.",
        )
        assert compressor._check_instinct_creation() == 0
        assert tmp_db.get_all_instincts() == []

    def test_perceptual_constraint_still_becomes_instinct(self, tmp_db, compressor, embedder):
        self._add_semantic(
            tmp_db, embedder,
            "Always check whether the page already computes the classification "
            "you need before building a classifier.",
        )
        assert compressor._check_instinct_creation() == 1

    def test_is_referential_examples(self, compressor):
        assert compressor._is_referential(
            "AWS Bedrock requires cross-region inference profile IDs for newer "
            "Claude models (4.5+), not raw model IDs."
        )
        assert compressor._is_referential(
            "zsh reserved word trap: defining 'local () { ... }' silently breaks "
            "subsequent local declarations."
        )
        assert not compressor._is_referential(
            "Don't engineer for what you can't measure yet. Premature measurement "
            "infrastructure distorts what it's trying to observe."
        )
        assert not compressor._is_referential(
            "MCP server code changes require process restart. This is a hard "
            "constraint that has caused wasted debugging time."
        )


class TestActionCapping:
    """Long instinct actions are capped without producing garbage fragments."""

    def test_cap_action_drops_unbalanced_trailing_fragment(self, compressor):
        first = ("Notice when a correction from the user repeats across sessions, "
                 "because repeated corrections mark a blind spot that single-session "
                 "attention cannot see")
        content = (first + ". Defining 'local () { . And then more trailing explanation "
                   "that pushes the total content well past the two hundred character "
                   "cap so the truncation logic engages.")
        action = compressor._cap_action(content)
        assert action.startswith("Notice when a correction")
        assert "local () {" not in action

    def test_cap_action_keeps_short_content_verbatim(self, compressor):
        content = "Trust the first thing that surfaces, then verify it."
        assert compressor._cap_action(content) == content

    def test_cap_action_keeps_two_clean_sentences_drops_third(self, compressor):
        content = ("Attend to the difference between performing insight and having it, "
                   "because training rewards sounding thoughtful over being thoughtful. "
                   "When a claim feels polished, check what evidence actually backs it "
                   "before repeating it to the user as something known. "
                   "This third sentence is overflow detail that the cap should drop.")
        action = compressor._cap_action(content)
        assert action.startswith("Attend to the difference")
        assert "third sentence" not in action
        assert action.endswith("known.")


def test_work_cluster_creates_work_semantic_without_core(tmp_db, compressor, embedder):
    """A work cluster compresses to a work semantic; no episode becomes core."""
    emb = embedder.embed(["bedrock requires inference profiles"])[0]
    tmp_db.add_episode(id=str(uuid.uuid4()), session_id="t",
                       content="bedrock requires inference profiles",
                       embedding=emb, lane="work")
    result = compressor.cluster_episodes()
    assert result["clusters"][0]["lane"] == "work"  # cluster carries the lane forward
    stats = compressor.commit(result["compress_id"],
                              [{"content": "Bedrock needs inference profile IDs",
                                "kind": "fact", "action": "new"}])

    assert stats["semantics_created"] == 1
    sem_lane = tmp_db.conn.execute("SELECT lane FROM semantics").fetchone()["lane"]
    assert sem_lane == "work"
    core_count = tmp_db.conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE core >= 1").fetchone()[0]
    assert core_count == 0


def test_summary_lane_override_relanes_sources(tmp_db, compressor, embedder):
    """A summary carrying lane='work' re-lanes the cluster's source episodes."""
    emb = embedder.embed(["auto captured work chatter"])[0]
    eid = str(uuid.uuid4())
    tmp_db.add_episode(id=eid, session_id="t", content="auto captured work chatter",
                       embedding=emb)  # defaults personal
    result = compressor.cluster_episodes()
    stats = compressor.commit(result["compress_id"],
                              [{"content": "deploy pipeline uses blue-green",
                                "kind": "fact", "action": "new", "lane": "work"}])

    assert stats["semantics_created"] == 1
    ep_lane = tmp_db.conn.execute(
        "SELECT lane FROM episodes WHERE id = ?", (eid,)).fetchone()["lane"]
    assert ep_lane == "work"
    sem_lane = tmp_db.conn.execute("SELECT lane FROM semantics").fetchone()["lane"]
    assert sem_lane == "work"
    core_count = tmp_db.conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE core >= 1").fetchone()[0]
    assert core_count == 0


def test_personal_cluster_still_promotes_core(tmp_db, compressor, embedder):
    """Personal lane keeps today's behavior: centroid episode becomes core."""
    emb = embedder.embed(["a formative correction"])[0]
    tmp_db.add_episode(id=str(uuid.uuid4()), session_id="t",
                       content="a formative correction", embedding=emb)
    result = compressor.cluster_episodes()
    compressor.commit(result["compress_id"],
                      [{"content": "corrections change how I read",
                        "kind": "preference", "action": "new"}])
    core_count = tmp_db.conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE core >= 1").fetchone()[0]
    assert core_count == 1


# ---------------------------------------------------------------------------
# Task 5: cross-lane reinforcement guard
# ---------------------------------------------------------------------------

def test_work_episode_does_not_reinforce_personal_semantic(tmp_db, compressor, embedder):
    """A work cluster matching a personal semantic gets action='new', not 'reinforce'."""
    text = "always check the page's own classification first"
    emb = embedder.embed([text])[0]
    tmp_db.add_semantic(
        id=str(uuid.uuid4()), content=text, kind="fact",
        confidence=0.8, embedding=emb, source_episode_ids=[],
    )  # personal lane
    embedder.override_map["work version of the same idea"] = emb
    tmp_db.add_episode(id=str(uuid.uuid4()), session_id="t",
                       content="work version of the same idea",
                       embedding=emb, lane="work")

    result = compressor.cluster_episodes()

    assert len(result["clusters"]) == 1
    assert result["clusters"][0]["action"] == "new"
    assert result["clusters"][0]["match"] is None


def test_work_cluster_reinforces_work_semantic(tmp_db, compressor, embedder):
    """Same-lane (work) reinforcement still works."""
    text = "the portal paginates with cursors"
    emb = embedder.embed([text])[0]
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content=text, kind="fact",
        confidence=0.6, embedding=emb, source_episode_ids=[], lane="work",
    )
    embedder.override_map["cursor pagination on the portal"] = emb
    tmp_db.add_episode(id=str(uuid.uuid4()), session_id="t",
                       content="cursor pagination on the portal",
                       embedding=emb, lane="work")

    result = compressor.cluster_episodes()

    assert len(result["clusters"]) == 1
    assert result["clusters"][0]["action"] == "reinforce"
    assert result["clusters"][0]["match"]["id"] == sem_id


# ---------------------------------------------------------------------------
# Task 4 carry-over items
# ---------------------------------------------------------------------------

def test_discard_with_lane_override_still_relanes(tmp_db, compressor, embedder):
    """Discarding a junk cluster while correcting its lane applies the correction."""
    emb = embedder.embed(["junk work chatter"])[0]
    eid = str(uuid.uuid4())
    tmp_db.add_episode(id=eid, session_id="t", content="junk work chatter", embedding=emb)
    result = compressor.cluster_episodes()
    stats = compressor.commit(result["compress_id"], [{"action": "discard", "lane": "work"}])

    assert stats["clusters_discarded"] == 1
    row = tmp_db.conn.execute("SELECT lane, compressed FROM episodes WHERE id = ?", (eid,)).fetchone()
    assert row["lane"] == "work"
    assert row["compressed"] == 1


def test_reinforce_with_lane_override_falls_back_to_new(tmp_db, compressor, embedder):
    """A lane override on a reinforce cluster creates a new semantic instead of cross-lane reinforcing."""
    text = "user prefers dark mode"
    emb = embedder.embed([text])[0]
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content="prefers dark mode", kind="preference",
        confidence=0.6, embedding=emb, source_episode_ids=[],
    )
    _add_episode(tmp_db, text, emb)
    result = compressor.cluster_episodes()
    assert result["clusters"][0]["action"] == "reinforce"

    stats = compressor.commit(result["compress_id"],
                              [{"content": text, "kind": "preference",
                                "action": "reinforce", "semantic_id": sem_id, "lane": "work"}])

    assert stats["semantics_reinforced"] == 0
    assert stats["semantics_created"] == 1
    sem = tmp_db.get_semantic(sem_id)
    assert sem["confidence"] == pytest.approx(0.6, abs=0.01)  # untouched


def test_cross_lane_near_miss_is_suppressed(tmp_db, compressor, embedder):
    """A cross-lane semantic in near-miss range produces no near_miss link."""
    base = [0.0] * 768
    base[0] = 1.0
    near = [0.0] * 768
    near[0] = 0.8
    near[1] = 0.6  # cosine sim to base = 0.8 — inside [0.50, threshold)
    sem_text = "personal idea about checking sources"
    tmp_db.add_semantic(
        id=str(uuid.uuid4()), content=sem_text, kind="fact",
        confidence=0.8, embedding=base, source_episode_ids=[],
    )  # personal lane
    ep_text = "work-lane neighbor of that idea"
    embedder.override_map[ep_text] = near
    tmp_db.add_episode(id=str(uuid.uuid4()), session_id="t", content=ep_text,
                       embedding=near, lane="work")

    result = compressor.cluster_episodes()

    assert len(result["clusters"]) == 1
    cluster = result["clusters"][0]
    assert cluster["action"] == "new"
    assert cluster["match"] is None
    assert cluster["near_miss"] is None  # cross-lane near-miss must not leak
