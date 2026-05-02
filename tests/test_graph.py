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


class TestStats:
    def test_stats_empty_db(self, tmp_path):
        store = _make_storage(tmp_path)
        g = MemoryGraph(store)
        s = g.stats()
        assert s["total_nodes"] == 0
        assert s["total_edges"] == 0
        assert s["components"] == 0
        assert s["isolated_nodes"] == 0
        store.close()

    def test_stats_counts_nodes_and_edges(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, None, "episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "semantic", kind="fact", confidence=0.9,
                          source_episode_ids=[ep_id], embedding=_fake_emb())

        g = MemoryGraph(store)
        s = g.stats()
        assert s["total_nodes"] == 2
        assert s["total_edges"] >= 1
        assert s["components"] == 1
        assert s["isolated_nodes"] == 0
        store.close()

    def test_stats_detects_isolated(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_a = str(uuid.uuid4())
        ep_b = str(uuid.uuid4())
        store.add_episode(ep_a, None, "episode a", embedding=_fake_emb())
        store.add_episode(ep_b, None, "episode b", embedding=_fake_emb())

        g = MemoryGraph(store)
        s = g.stats()
        assert s["total_nodes"] == 2
        assert s["isolated_nodes"] == 2
        assert s["components"] == 2
        store.close()


class TestAnalyze:
    def test_analyze_returns_hubs(self, tmp_path):
        store = _make_storage(tmp_path)
        sem_id = str(uuid.uuid4())
        ep_ids = []
        for i in range(5):
            ep_id = str(uuid.uuid4())
            store.add_episode(ep_id, None, f"episode {i}", embedding=_fake_emb())
            ep_ids.append(ep_id)
        store.add_semantic(sem_id, "hub semantic", kind="fact", confidence=0.9,
                          source_episode_ids=ep_ids, embedding=_fake_emb())

        g = MemoryGraph(store)
        a = g.analyze()
        assert len(a["hubs"]) > 0
        assert a["hubs"][0]["id"] == sem_id
        assert a["hubs"][0]["degree"] == 5
        store.close()


class TestExport:
    def test_to_dot_produces_valid_output(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, None, "test episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "test semantic", kind="fact", confidence=0.9,
                          source_episode_ids=[ep_id], embedding=_fake_emb())

        g = MemoryGraph(store)
        dot = g.to_dot(center=ep_id, depth=1)
        assert "digraph" in dot
        assert ep_id[:8] in dot
        assert sem_id[:8] in dot
        store.close()

    def test_to_json_structure(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, None, "test episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "test semantic", kind="fact", confidence=0.9,
                          source_episode_ids=[ep_id], embedding=_fake_emb())

        g = MemoryGraph(store)
        j = g.to_json(center=ep_id, depth=1)
        assert "nodes" in j
        assert "edges" in j
        assert len(j["nodes"]) == 2
        store.close()

    def test_to_dot_global_without_center(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        store.add_episode(ep_id, None, "solo", embedding=_fake_emb())

        g = MemoryGraph(store)
        dot = g.to_dot()
        assert "digraph" in dot
        store.close()


class TestSuggestEdges:
    def test_suggests_nearby_unconnected(self, tmp_path):
        store = _make_storage(tmp_path)
        base_emb = [0.0] * 768
        base_emb[0] = 1.0
        near_emb = [0.0] * 768
        near_emb[0] = 0.99
        near_emb[1] = 0.01
        far_emb = [0.0] * 768
        far_emb[100] = 1.0

        ep_a = str(uuid.uuid4())
        ep_b = str(uuid.uuid4())
        ep_c = str(uuid.uuid4())
        store.add_episode(ep_a, None, "base episode", embedding=base_emb)
        store.add_episode(ep_b, None, "near episode", embedding=near_emb)
        store.add_episode(ep_c, None, "far episode", embedding=far_emb)

        g = MemoryGraph(store)
        suggestions = g.suggest_edges(ep_a, k=5, threshold=0.5)
        suggested_targets = {e.target for e in suggestions}
        assert ep_b in suggested_targets
        assert all(e.edge_type == "suggested" for e in suggestions)
        store.close()

    def test_excludes_already_connected(self, tmp_path):
        store = _make_storage(tmp_path)
        emb = [0.0] * 768
        emb[0] = 1.0
        ep_a = str(uuid.uuid4())
        sem_a = str(uuid.uuid4())
        store.add_episode(ep_a, None, "connected episode", embedding=emb)
        store.add_semantic(sem_a, "connected semantic", kind="fact",
                          confidence=0.9, source_episode_ids=[ep_a], embedding=emb)

        g = MemoryGraph(store)
        suggestions = g.suggest_edges(ep_a, k=5, threshold=0.0)
        suggested_targets = {e.target for e in suggestions}
        assert sem_a not in suggested_targets
        store.close()
