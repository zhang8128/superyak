"""Tests for the Graphiti knowledge graph bridge."""

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import GraphConfig


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test.kuzu")


@pytest.fixture
def graph_config(tmp_db):
    return GraphConfig(enabled=True, model="nemotron-nano", db_path=tmp_db)


class TestKnowledgeGraphInit:
    def test_create_knowledge_graph(self, graph_config):
        from knowledge import KnowledgeGraph

        kg = KnowledgeGraph(graph_config)
        assert kg is not None
        # Ollama may or may not be running — init should succeed or degrade gracefully
        assert isinstance(kg.enabled, bool)

    def test_disabled_graph_skips_init(self):
        config = GraphConfig(enabled=False)
        from knowledge import KnowledgeGraph

        kg = KnowledgeGraph(config)
        assert kg.enabled is False


class TestKnowledgeGraphFeed:
    def test_feed_episodes_calls_graphiti(self, graph_config):
        from knowledge import KnowledgeGraph

        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg._config = graph_config
        kg._config.enabled = True
        kg._graphiti = MagicMock()
        kg._executor = None
        kg._graphiti.add_episode = AsyncMock(return_value=MagicMock(
            nodes=[], edges=[], episodes=[]
        ))

        episodes = [
            {
                "id": "ep-1",
                "content": "Vin learned to trust the crew slowly.",
                "created_at": "2026-03-25T10:00:00+00:00",
            },
            {
                "id": "ep-2",
                "content": "Kelsier showed Vin the basics of Allomancy.",
                "created_at": "2026-03-25T10:05:00+00:00",
            },
        ]

        result = kg.feed(episodes, semantic_content="Vin's early training with the crew")
        assert result is not None
        assert result["episodes_fed"] == 2
        assert kg._graphiti.add_episode.call_count == 2

    def test_feed_disabled_is_noop(self):
        from knowledge import KnowledgeGraph
        from config import GraphConfig

        config = GraphConfig(enabled=False)
        kg = KnowledgeGraph(config)
        result = kg.feed([], semantic_content="test")
        assert result is None


class TestKnowledgeGraphSearch:
    def test_search_returns_entities_and_facts(self, graph_config):
        from knowledge import KnowledgeGraph

        mock_edge = MagicMock()
        mock_edge.uuid = "edge-1"
        mock_edge.name = "trusts"
        mock_edge.fact = "Vin trusts Kelsier"
        mock_edge.valid_at = datetime(2026, 3, 25, tzinfo=timezone.utc)
        mock_edge.invalid_at = None
        mock_edge.source_node_uuid = "node-1"
        mock_edge.target_node_uuid = "node-2"
        mock_edge.source_node_name = "Vin"
        mock_edge.target_node_name = "Kelsier"

        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg._config = graph_config
        kg._config.enabled = True
        kg._graphiti = MagicMock()
        kg._executor = None
        kg._graphiti.search = AsyncMock(return_value=[mock_edge])

        result = kg.search("Vin's relationships")
        assert result is not None
        assert len(result["facts"]) == 1
        assert result["facts"][0]["fact"] == "Vin trusts Kelsier"
        assert result["facts"][0]["source"] == "Vin"
        assert result["facts"][0]["target"] == "Kelsier"

    def test_search_separates_current_and_historical(self, graph_config):
        from knowledge import KnowledgeGraph

        current = MagicMock()
        current.uuid = "e-1"
        current.name = "trusts"
        current.fact = "Vin trusts Kelsier"
        current.valid_at = datetime(2026, 3, 25, tzinfo=timezone.utc)
        current.invalid_at = None
        current.source_node_name = "Vin"
        current.target_node_name = "Kelsier"

        historical = MagicMock()
        historical.uuid = "e-2"
        historical.name = "distrusts"
        historical.fact = "Vin distrusts everyone"
        historical.valid_at = datetime(2026, 3, 20, tzinfo=timezone.utc)
        historical.invalid_at = datetime(2026, 3, 24, tzinfo=timezone.utc)
        historical.source_node_name = "Vin"
        historical.target_node_name = "everyone"

        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg._config = graph_config
        kg._config.enabled = True
        kg._graphiti = MagicMock()
        kg._executor = None
        kg._graphiti.search = AsyncMock(return_value=[current, historical])

        result = kg.search("Vin")
        assert len(result["facts"]) == 1
        assert len(result["historical"]) == 1
        assert result["historical"][0]["invalid_at"] is not None

    def test_search_disabled_returns_none(self):
        from knowledge import KnowledgeGraph
        from config import GraphConfig

        config = GraphConfig(enabled=False)
        kg = KnowledgeGraph(config)
        result = kg.search("anything")
        assert result is None


class TestKnowledgeGraphIntegration:
    """Test the full flow: compression feeds Graphiti, recall queries it."""

    def test_compress_feeds_knowledge_graph(self, tmp_path):
        """Verify compression passes episodes to knowledge graph."""
        from unittest.mock import MagicMock, AsyncMock
        from compress import Compressor
        from config import CompressionConfig, GraphConfig
        from knowledge import KnowledgeGraph

        # Mock storage
        storage = MagicMock()
        storage.get_uncompressed_episodes.return_value = [
            {"id": "ep1", "content": "Vin trained with Kelsier", "created_at": "2026-03-25T10:00:00+00:00"},
            {"id": "ep2", "content": "Vin practiced pewter burns", "created_at": "2026-03-25T10:05:00+00:00"},
        ]
        storage.search_vectors.return_value = []
        storage.add_semantic = MagicMock()
        storage.mark_episodes_compressed = MagicMock()
        storage.mark_core_batch = MagicMock()
        storage.add_log_entry = MagicMock()
        storage.get_active_semantics.return_value = []
        storage.conn = MagicMock()

        # Mock embeddings — returns a list sized to match input
        embeddings = MagicMock()
        embeddings.embed.side_effect = lambda texts, prefix=None: [
            [float(i + 1) * 0.1] * 768 for i in range(len(texts))
        ]

        # Mock knowledge graph
        kg = MagicMock(spec=KnowledgeGraph)
        kg.enabled = True
        kg.feed.return_value = {"episodes_fed": 2, "entities_extracted": 3, "relationships_extracted": 1}

        compressor = Compressor(
            storage, embeddings,
            CompressionConfig(),
            knowledge_graph=kg,
        )

        result = compressor.cluster_episodes()
        if result["compress_id"]:
            summaries = [{"content": "Vin's Allomancy training", "kind": "fact", "action": "new"}]
            compressor.commit(result["compress_id"], summaries)
            kg.feed.assert_called_once()
