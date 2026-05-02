"""Tests for unified memory graph."""

import uuid
from pathlib import Path
from storage import Storage
from graph import Edge, Node, MemoryGraph

MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


class TestDataclasses:
    def test_edge_creation(self):
        e = Edge(
            source="ep-001", source_layer="episode",
            target="sem-001", target_layer="semantic",
            edge_type="provenance", weight=0.8, directed=True,
        )
        assert e.source == "ep-001"
        assert e.edge_type == "provenance"
        assert e.directed is True

    def test_node_creation(self):
        n = Node(id="ep-001", layer="episode", preview="First 100 chars...")
        assert n.id == "ep-001"
        assert n.layer == "episode"

    def test_edge_weight_clamped(self):
        e = Edge(
            source="a", source_layer="episode",
            target="b", target_layer="episode",
            edge_type="resonance", weight=1.5, directed=False,
        )
        assert e.weight == 1.0

    def test_edge_weight_floor(self):
        e = Edge(
            source="a", source_layer="episode",
            target="b", target_layer="episode",
            edge_type="resonance", weight=-0.5, directed=False,
        )
        assert e.weight == 0.0


def _make_storage(tmp_path):
    """Create a storage with known edges for testing."""
    db_path = str(tmp_path / "test_graph.db")
    store = Storage(db_path, migrations_dir=MIGRATIONS_DIR)
    return store


def _fake_emb(dim=768):
    import random
    return [random.uniform(-1, 1) for _ in range(dim)]


class TestEdgeLoading:
    def test_provenance_episode_to_semantic(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, None, "test episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "test semantic", kind="fact", confidence=0.9,
                          embedding=_fake_emb(), source_episode_ids=[ep_id])

        g = MemoryGraph(store)
        edges = g.neighbors(ep_id)
        prov = [e for e in edges if e.edge_type == "provenance"]
        assert len(prov) == 1
        assert prov[0].target == sem_id
        assert prov[0].directed is True
        store.close()

    def test_provenance_semantic_to_episode(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, None, "test episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "test semantic", kind="fact", confidence=0.9,
                          embedding=_fake_emb(), source_episode_ids=[ep_id])

        g = MemoryGraph(store)
        edges = g.neighbors(sem_id)
        prov = [e for e in edges if e.edge_type == "provenance"]
        assert len(prov) == 1
        assert prov[0].target == ep_id
        assert prov[0].directed is True
        store.close()

    def test_resonance_edges(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_a = str(uuid.uuid4())
        ep_b = str(uuid.uuid4())
        store.add_episode(ep_a, None, "episode alpha", embedding=_fake_emb())
        store.add_episode(ep_b, None, "episode beta", embedding=_fake_emb())
        store.add_resonance(ep_a, "episode", ep_b, "episode",
                           similarity=0.8, weight=0.6)

        g = MemoryGraph(store)
        edges = g.neighbors(ep_a)
        res = [e for e in edges if e.edge_type == "resonance"]
        assert len(res) == 1
        assert res[0].target == ep_b
        assert res[0].directed is False

        edges_b = g.neighbors(ep_b)
        res_b = [e for e in edges_b if e.edge_type == "resonance"]
        assert len(res_b) == 1
        assert res_b[0].target == ep_a
        store.close()

    def test_no_edges_for_isolated_node(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        store.add_episode(ep_id, None, "lonely episode", embedding=_fake_emb())

        g = MemoryGraph(store)
        edges = g.neighbors(ep_id)
        assert edges == []
        store.close()


class TestNeighborhood:
    def test_depth_one_returns_immediate(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, None, "test episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "test semantic", kind="fact",
                          confidence=0.9, embedding=_fake_emb(),
                          source_episode_ids=[ep_id])

        g = MemoryGraph(store)
        nodes, edges = g.neighborhood(ep_id, depth=1)
        node_ids = {n.id for n in nodes}
        assert ep_id in node_ids
        assert sem_id in node_ids
        assert len(edges) >= 1
        store.close()

    def test_depth_two_reaches_transitive(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        ins_id = str(uuid.uuid4())
        store.add_episode(ep_id, None, "test episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "test semantic", kind="preference",
                          confidence=0.8, embedding=_fake_emb(),
                          source_episode_ids=[ep_id])
        store.add_instinct(ins_id, trigger="preference", action="test instinct",
                          source_semantic_ids=[sem_id], embedding=_fake_emb(),
                          notice="when testing", implication="test well")

        g = MemoryGraph(store)
        nodes, edges = g.neighborhood(ep_id, depth=2)
        node_ids = {n.id for n in nodes}
        assert ep_id in node_ids
        assert sem_id in node_ids
        assert ins_id in node_ids
        store.close()

    def test_depth_zero_returns_only_center(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        store.add_episode(ep_id, None, "solo", embedding=_fake_emb())

        g = MemoryGraph(store)
        nodes, edges = g.neighborhood(ep_id, depth=0)
        assert len(nodes) == 1
        assert nodes[0].id == ep_id
        assert edges == []
        store.close()
