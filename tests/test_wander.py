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

    def test_content_truncation(self, db, fake_embedding):
        """Long content is truncated to 300 chars in neighbors."""
        long_content = "x" * 500
        db.add_episode("ep-1", "sess-1", "start", embedding=fake_embedding())
        db.add_episode("ep-2", "sess-1", long_content, embedding=fake_embedding())
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.8, weight=0.6)

        neighbors = db.get_neighbors("ep-1")
        assert len(neighbors[0]["content"]) <= 300


class TestEntityNeighbors:
    """Test entity neighbor injection into get_neighbors()."""

    def test_entity_neighbors_appear_with_correct_connection_type(self, db, fake_embedding):
        """Entity neighbors passed to get_neighbors appear with connection_type='entity'."""
        db.add_episode("ep-1", "sess-1", "base memory", embedding=fake_embedding())

        entity_neighbors = [
            {
                "id": "node-uuid-1",
                "content": "Alice is a software engineer",
                "layer": "entity",
                "entity_name": "Alice",
            }
        ]

        neighbors = db.get_neighbors("ep-1", entity_neighbors=entity_neighbors)
        entity_ns = [n for n in neighbors if n["connection_type"] == "entity"]
        assert len(entity_ns) == 1
        assert entity_ns[0]["id"] == "node-uuid-1"

    def test_entity_neighbors_include_entity_name(self, db, fake_embedding):
        """Entity neighbors include the entity_name field."""
        db.add_episode("ep-1", "sess-1", "base memory", embedding=fake_embedding())

        entity_neighbors = [
            {
                "id": "node-uuid-2",
                "content": "Bob works at ACME",
                "layer": "entity",
                "entity_name": "Bob",
            }
        ]

        neighbors = db.get_neighbors("ep-1", entity_neighbors=entity_neighbors)
        entity_ns = [n for n in neighbors if n["connection_type"] == "entity"]
        assert len(entity_ns) == 1
        assert entity_ns[0]["entity_name"] == "Bob"

    def test_entity_neighbors_combined_with_resonances(self, db, fake_embedding):
        """Entity neighbors coexist with resonance and provenance neighbors."""
        emb_a, emb_b = fake_embedding(), fake_embedding()
        db.add_episode("ep-1", "sess-1", "first memory", embedding=emb_a)
        db.add_episode("ep-2", "sess-1", "second memory", embedding=emb_b)
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.8, weight=0.6)

        entity_neighbors = [
            {
                "id": "node-uuid-3",
                "content": "Carol is a researcher",
                "layer": "entity",
                "entity_name": "Carol",
            }
        ]

        neighbors = db.get_neighbors("ep-1", entity_neighbors=entity_neighbors)
        types = {n["connection_type"] for n in neighbors}
        assert "resonance" in types
        assert "entity" in types

    def test_none_entity_neighbors_leaves_results_unchanged(self, db, fake_embedding):
        """Passing entity_neighbors=None (default) doesn't change behavior."""
        emb_a, emb_b = fake_embedding(), fake_embedding()
        db.add_episode("ep-1", "sess-1", "first", embedding=emb_a)
        db.add_episode("ep-2", "sess-1", "second", embedding=emb_b)
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.8, weight=0.6)

        neighbors_default = db.get_neighbors("ep-1")
        neighbors_explicit_none = db.get_neighbors("ep-1", entity_neighbors=None)
        assert neighbors_default == neighbors_explicit_none

    def test_entity_neighbor_content_truncated(self, db, fake_embedding):
        """Entity neighbor content is truncated to 300 chars."""
        db.add_episode("ep-1", "sess-1", "base", embedding=fake_embedding())

        long_content = "y" * 500
        entity_neighbors = [
            {
                "id": "node-uuid-4",
                "content": long_content,
                "layer": "entity",
                "entity_name": "LongEntity",
            }
        ]

        neighbors = db.get_neighbors("ep-1", entity_neighbors=entity_neighbors)
        entity_ns = [n for n in neighbors if n["connection_type"] == "entity"]
        assert len(entity_ns[0]["content"]) <= 300


class TestAutoWalk:

    def test_single_step_returns_neighbors(self, db, fake_embedding):
        """max_steps=1 returns direct neighbors only."""
        emb_a, emb_b, emb_c = fake_embedding(), fake_embedding(), fake_embedding()
        db.add_episode("ep-1", "sess-1", "start", embedding=emb_a)
        db.add_episode("ep-2", "sess-1", "middle", embedding=emb_b)
        db.add_episode("ep-3", "sess-1", "end", embedding=emb_c)
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.8, weight=0.6)
        db.add_resonance("ep-2", "episode", "ep-3", "episode", similarity=0.7, weight=0.5)

        neighbors = db.get_neighbors("ep-1")
        ids = [n["id"] for n in neighbors]
        assert "ep-2" in ids
        assert "ep-3" not in ids

    def test_no_duplicate_nodes_in_trail(self, db, fake_embedding):
        """Auto-walk never visits the same node twice."""
        from server import _auto_walk
        embs = [fake_embedding() for _ in range(4)]
        db.add_episode("ep-1", "sess-1", "a", embedding=embs[0])
        db.add_episode("ep-2", "sess-1", "b", embedding=embs[1])
        db.add_episode("ep-3", "sess-1", "c", embedding=embs[2])
        db.add_episode("ep-4", "sess-1", "d", embedding=embs[3])
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.9, weight=0.7)
        db.add_resonance("ep-2", "episode", "ep-3", "episode", similarity=0.8, weight=0.6)
        db.add_resonance("ep-1", "episode", "ep-3", "episode", similarity=0.7, weight=0.5)
        db.add_resonance("ep-3", "episode", "ep-4", "episode", similarity=0.6, weight=0.4)

        trail = _auto_walk(db, "ep-1", max_steps=10, density_threshold=20,
                           knowledge_graph=None, visit_counts={})
        trail_ids = [step["id"] for step in trail]
        assert len(trail_ids) == len(set(trail_ids))

    def test_density_stops_walk(self, db, fake_embedding):
        """Walk stops when a node has neighbors >= density_threshold."""
        embs = [fake_embedding() for _ in range(7)]
        db.add_episode("ep-sparse", "sess-1", "sparse node", embedding=embs[0])
        db.add_episode("ep-dense", "sess-1", "dense node", embedding=embs[1])
        db.add_resonance("ep-sparse", "episode", "ep-dense", "episode",
                         similarity=0.8, weight=0.7)
        for i in range(2, 7):
            db.add_episode(f"ep-{i}", "sess-1", f"neighbor {i}", embedding=embs[i])
            db.add_resonance("ep-dense", "episode", f"ep-{i}", "episode",
                             similarity=0.7, weight=0.5)

        from server import _auto_walk
        trail = _auto_walk(db, "ep-sparse", max_steps=10, density_threshold=5,
                           knowledge_graph=None, visit_counts={})
        assert trail[-1]["id"] == "ep-dense"

    def test_auto_walk_dead_end(self, db, fake_embedding):
        """Auto-walk from an orphan returns empty trail."""
        from server import _auto_walk
        db.add_episode("ep-alone", "sess-1", "isolated", embedding=fake_embedding())
        trail = _auto_walk(db, "ep-alone", max_steps=5, density_threshold=5,
                           knowledge_graph=None, visit_counts={})
        assert trail == []


class TestWanderEdgeCases:

    def test_nonexistent_start_id(self, db):
        """Starting from a nonexistent ID returns empty neighbors."""
        neighbors = db.get_neighbors("does-not-exist")
        assert neighbors == []

    def test_mixed_layer_neighbors(self, db, fake_embedding):
        """A memory can have neighbors from different layers."""
        emb = fake_embedding()
        db.add_episode("ep-1", "sess-1", "experience", embedding=emb)
        db.add_episode("ep-2", "sess-1", "related experience", embedding=emb)
        db.add_semantic("sem-1", "distilled from ep-1", "fact", 0.8, emb,
                        source_episode_ids=["ep-1"])
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.8, weight=0.6)

        neighbors = db.get_neighbors("ep-1")
        layers = {n["layer"] for n in neighbors}
        assert "episode" in layers  # resonance to ep-2
        assert "semantic" in layers  # provenance to sem-1
