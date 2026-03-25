"""Tests for the Graphiti knowledge graph bridge."""

import asyncio
import tempfile
from pathlib import Path

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
