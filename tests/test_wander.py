"""Tests for memory traversal (wander)."""

import uuid
import pytest
from storage import Storage


@pytest.fixture
def db(tmp_path):
    return Storage(str(tmp_path / "test.db"))


@pytest.fixture
def fake_embedding():
    import random
    def _make():
        return [random.random() for _ in range(768)]
    return _make


class TestGetNeighbors:
    """Test Storage.get_neighbors() — resonance + provenance axes."""

    def test_resonance_neighbors(self, db, fake_embedding):
        """Memories linked by resonances appear as neighbors."""
        emb_a, emb_b = fake_embedding(), fake_embedding()
        db.add_episode("ep-1", "sess-1", "first memory", embedding=emb_a)
        db.add_episode("ep-2", "sess-1", "second memory", embedding=emb_b)
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.8, weight=0.6)

        neighbors = db.get_neighbors("ep-1")
        resonance_ids = [n["id"] for n in neighbors if n["connection_type"] == "resonance"]
        assert "ep-2" in resonance_ids

    def test_resonance_neighbors_reverse(self, db, fake_embedding):
        """Resonances are bidirectional — canonical ordering doesn't matter for lookup."""
        emb_a, emb_b = fake_embedding(), fake_embedding()
        db.add_episode("aaa", "sess-1", "first", embedding=emb_a)
        db.add_episode("zzz", "sess-1", "second", embedding=emb_b)
        db.add_resonance("aaa", "episode", "zzz", "episode", similarity=0.8, weight=0.6)

        neighbors = db.get_neighbors("zzz")
        resonance_ids = [n["id"] for n in neighbors if n["connection_type"] == "resonance"]
        assert "aaa" in resonance_ids

    def test_provenance_children(self, db, fake_embedding):
        """An episode's children (semantics built from it) appear as neighbors."""
        emb = fake_embedding()
        db.add_episode("ep-1", "sess-1", "raw experience", embedding=emb)
        db.add_semantic("sem-1", "distilled fact", "fact", 0.8, emb, source_episode_ids=["ep-1"])

        neighbors = db.get_neighbors("ep-1")
        prov = [n for n in neighbors if n["connection_type"] == "provenance"]
        assert any(n["id"] == "sem-1" for n in prov)

    def test_provenance_parents(self, db, fake_embedding):
        """A semantic's parents (source episodes) appear as neighbors."""
        emb = fake_embedding()
        db.add_episode("ep-1", "sess-1", "raw experience", embedding=emb)
        db.add_semantic("sem-1", "distilled fact", "fact", 0.8, emb, source_episode_ids=["ep-1"])

        neighbors = db.get_neighbors("sem-1")
        prov = [n for n in neighbors if n["connection_type"] == "provenance"]
        assert any(n["id"] == "ep-1" for n in prov)

    def test_instinct_provenance(self, db, fake_embedding):
        """An instinct's source semantics appear as neighbors."""
        emb = fake_embedding()
        db.add_episode("ep-1", "sess-1", "experience", embedding=emb)
        db.add_semantic("sem-1", "pattern", "fact", 0.8, emb, source_episode_ids=["ep-1"])
        db.add_instinct("ins-1", "trigger", "action", source_semantic_ids=["sem-1"],
                        embedding=emb, notice="notice this", implication="implies that")

        neighbors = db.get_neighbors("ins-1")
        prov = [n for n in neighbors if n["connection_type"] == "provenance"]
        assert any(n["id"] == "sem-1" for n in prov)

    def test_no_connections(self, db, fake_embedding):
        """Orphan memory returns empty list."""
        db.add_episode("ep-1", "sess-1", "alone", embedding=fake_embedding())
        neighbors = db.get_neighbors("ep-1")
        assert neighbors == []

    def test_neighbor_fields(self, db, fake_embedding):
        """Each neighbor has required fields."""
        emb_a, emb_b = fake_embedding(), fake_embedding()
        db.add_episode("ep-1", "sess-1", "first", embedding=emb_a)
        db.add_episode("ep-2", "sess-1", "second", embedding=emb_b)
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.85, weight=0.6)

        neighbors = db.get_neighbors("ep-1")
        n = neighbors[0]
        assert "id" in n
        assert "content" in n
        assert "layer" in n
        assert "connection_type" in n
        assert "connection_strength" in n
