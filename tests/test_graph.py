"""Tests for unified memory graph."""

from graph import Edge, Node


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
