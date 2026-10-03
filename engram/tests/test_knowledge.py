"""Tests for the Graphiti knowledge graph bridge."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import GraphConfig
from graphiti_local import GraphitiEmbedder, GraphitiReranker


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

    def test_explicit_local_clients_avoid_graphiti_openai_defaults(
        self, graph_config, monkeypatch
    ):
        import graphiti_core
        import graphiti_core.graphiti as graphiti_module
        from graphiti_core.driver.driver import GraphDriver
        from graphiti_local import GraphitiEmbedder, GraphitiReranker
        from knowledge import KnowledgeGraph

        class FakeDriver(GraphDriver):
            def __init__(self, *, db):
                self.db = db

            def execute_query(self, cypher_query_, **kwargs):
                raise NotImplementedError

            def session(self, database=None):
                raise NotImplementedError

            async def close(self):
                pass

            def delete_all_indexes(self):
                raise NotImplementedError

            async def build_indices_and_constraints(self, delete_existing=False):
                pass

        async def build_indices(_self):
            pass

        def openai_default_was_used(*_args, **_kwargs):
            raise AssertionError("Graphiti OpenAI embedding/reranking default was used")

        monkeypatch.setattr(
            "knowledge._bounded_kuzu_driver", lambda db_path, _mb: FakeDriver(db=db_path)
        )
        monkeypatch.setattr(
            graphiti_module, "OpenAIEmbedder", openai_default_was_used
        )
        monkeypatch.setattr(
            graphiti_module, "OpenAIRerankerClient", openai_default_was_used
        )
        monkeypatch.setattr(
            graphiti_core.Graphiti, "build_indices_and_constraints", build_indices
        )
        monkeypatch.setattr(
            graphiti_core.Graphiti,
            "_capture_initialization_telemetry",
            lambda _self: None,
        )

        provider = FakeGraphEmbeddingProvider()
        kg = KnowledgeGraph(graph_config, embedding_provider=provider)
        try:
            assert kg.enabled is True
            assert isinstance(kg._graphiti.embedder, GraphitiEmbedder)
            assert isinstance(kg._graphiti.cross_encoder, GraphitiReranker)
        finally:
            kg.close()

    def test_constructor_failure_closes_partial_driver_once(
        self, graph_config, monkeypatch, caplog
    ):
        import graphiti_core
        from knowledge import KnowledgeGraph

        closed = []

        class FakeDriver:
            def __init__(self, *, db):
                self.db = db

            async def close(self):
                closed.append(self)

        class FailingGraphiti:
            def __init__(self, **_kwargs):
                raise RuntimeError("injected constructor failure")

        monkeypatch.setattr(
            "knowledge._bounded_kuzu_driver", lambda db_path, _mb: FakeDriver(db=db_path)
        )
        monkeypatch.setattr(graphiti_core, "Graphiti", FailingGraphiti)

        with caplog.at_level("WARNING", logger="engram.knowledge"):
            kg = KnowledgeGraph(
                graph_config, embedding_provider=FakeGraphEmbeddingProvider()
            )

        assert kg.enabled is False
        assert len(closed) == 1
        assert kg._executor is None
        warnings = [
            record for record in caplog.records
            if record.name == "engram.knowledge" and record.levelname == "WARNING"
        ]
        assert len(warnings) == 1
        assert warnings[0].exc_info is None

    def test_index_failure_closes_graphiti_once(
        self, graph_config, monkeypatch
    ):
        import graphiti_core
        from knowledge import KnowledgeGraph

        graph_closes = []
        driver_closes = []

        class FakeDriver:
            def __init__(self, *, db):
                self.db = db

            async def close(self):
                driver_closes.append(self)

        class FailingGraphiti:
            def __init__(self, **_kwargs):
                pass

            async def build_indices_and_constraints(self):
                raise RuntimeError("injected index failure")

            async def close(self):
                graph_closes.append(self)

        monkeypatch.setattr(
            "knowledge._bounded_kuzu_driver", lambda db_path, _mb: FakeDriver(db=db_path)
        )
        monkeypatch.setattr(graphiti_core, "Graphiti", FailingGraphiti)

        kg = KnowledgeGraph(
            graph_config, embedding_provider=FakeGraphEmbeddingProvider()
        )

        assert kg.enabled is False
        assert len(graph_closes) == 1
        assert driver_closes == []
        assert kg._executor is None

    def test_close_attempts_independent_owners_and_retries_only_failures(
        self, graph_config
    ):
        """Graph and executor failures retain only their exact failed handles."""
        from knowledge import KnowledgeGraph

        class GraphHandle:
            def __init__(self):
                self.attempts = 0

            def close(self):
                self.attempts += 1
                return self

        class ExecutorHandle:
            def __init__(self):
                self.attempts = 0

            def shutdown(self, *, wait):
                assert wait is False
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("private executor close detail")

        graph = GraphHandle()
        executor = ExecutorHandle()
        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg._config = graph_config
        kg._graphiti = graph
        kg._executor = executor

        def fail_graph_once(handle):
            assert handle is graph
            if graph.attempts == 1:
                raise RuntimeError("private graph close detail")

        kg._run_async = fail_graph_once

        with pytest.raises(RuntimeError, match="private graph close detail"):
            kg.close()

        assert graph.attempts == 1
        assert executor.attempts == 1
        assert kg._graphiti is graph
        assert kg._executor is executor

        kg.close()
        kg.close()

        assert graph.attempts == 2
        assert executor.attempts == 2
        assert kg._graphiti is None
        assert kg._executor is None


class FakeGraphEmbeddingProvider:
    def __init__(self):
        self.calls = []

    def dimension(self):
        return 2

    def embed(self, texts, *, prefix="search_document"):
        self.calls.append((list(texts), prefix))
        vectors = {
            "query": [1.0, 0.0],
            "related": [0.8, 0.6],
            "unrelated": [0.0, 1.0],
        }
        return [vectors[text] for text in texts]


@pytest.mark.anyio
async def test_graphiti_local_clients_use_engram_embeddings():
    provider = FakeGraphEmbeddingProvider()
    embedder = GraphitiEmbedder(provider)
    reranker = GraphitiReranker(provider)

    assert await embedder.create("query") == [1.0, 0.0]
    assert await embedder.create_batch(["related", "unrelated"]) == [
        [0.8, 0.6],
        [0.0, 1.0],
    ]
    assert await reranker.rank("query", ["unrelated", "related"]) == [
        ("related", pytest.approx(0.8)),
        ("unrelated", pytest.approx(0.0)),
    ]
    assert provider.calls[:2] == [
        (["query"], "search_document"),
        (["related", "unrelated"], "search_document"),
    ]
    assert sorted(provider.calls[2:]) == sorted([
        (["query"], "search_query"),
        (["unrelated", "related"], "search_document"),
    ])


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

    def test_feed_tracks_partial_failure(self, graph_config):
        from knowledge import KnowledgeGraph

        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg._config = graph_config
        kg._config.enabled = True
        kg._graphiti = MagicMock()
        kg._executor = None

        # First episode succeeds, second fails
        success = MagicMock(nodes=[MagicMock()], edges=[MagicMock(), MagicMock()])
        kg._graphiti.add_episode = AsyncMock(side_effect=[success, Exception("LLM timeout")])

        episodes = [
            {"id": "ep-1", "content": "First", "created_at": "2026-03-25T10:00:00+00:00"},
            {"id": "ep-2", "content": "Second", "created_at": "2026-03-25T10:05:00+00:00"},
        ]

        result = kg.feed(episodes)
        assert result["episodes_fed"] == 1  # not 2
        assert result["episodes_failed"] == 1
        assert result["entities_extracted"] == 1
        assert result["relationships_extracted"] == 2

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


class TestKnowledgeGraphRoundTrip:
    """Test that what goes into feed() can come back from search()."""

    def test_feed_then_search_returns_extracted_facts(self, graph_config):
        """Feed episodes, then search — verify the data path is connected."""
        from knowledge import KnowledgeGraph

        # Mock edge that Graphiti would return after extraction
        mock_edge = MagicMock()
        mock_edge.uuid = "edge-1"
        mock_edge.name = "trained_with"
        mock_edge.fact = "Vin trained with Kelsier"
        mock_edge.valid_at = datetime(2026, 3, 25, tzinfo=timezone.utc)
        mock_edge.invalid_at = None
        mock_edge.source_node_name = "Vin"
        mock_edge.target_node_name = "Kelsier"

        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg._config = graph_config
        kg._config.enabled = True
        kg._executor = None
        kg._graphiti = MagicMock()
        kg._graphiti.add_episode = AsyncMock(return_value=MagicMock(
            nodes=[MagicMock()], edges=[mock_edge]
        ))
        kg._graphiti.search = AsyncMock(return_value=[mock_edge])

        # Feed
        episodes = [{"id": "ep-1", "content": "Vin trained with Kelsier", "created_at": "2026-03-25T10:00:00+00:00"}]
        feed_result = kg.feed(episodes, semantic_content="Allomancy training")
        assert feed_result["episodes_fed"] == 1
        assert feed_result["entities_extracted"] == 1
        assert feed_result["relationships_extracted"] == 1

        # Search — should find what was fed
        search_result = kg.search("Vin training")
        assert len(search_result["facts"]) == 1
        assert search_result["facts"][0]["fact"] == "Vin trained with Kelsier"
        assert search_result["facts"][0]["source"] == "Vin"
        assert search_result["facts"][0]["target"] == "Kelsier"

        # Verify Graphiti was actually called for both operations
        kg._graphiti.add_episode.assert_called_once()
        kg._graphiti.search.assert_called_once()


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
        storage.get_episode.return_value = None
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

    def test_compression_feeds_graph_only_after_local_commit(self, tmp_path):
        from compress import Compressor
        from storage import Storage

        storage = Storage(str(tmp_path / "graph-order.db"))
        embeddings = MagicMock()
        embeddings.embed.side_effect = lambda texts, prefix=None: [
            [float(i + 1) * 0.1] * 768 for i in range(len(texts))
        ]

        class TransactionCheckingGraph:
            def __init__(self):
                self.transaction_states = []

            def feed(self, episodes, semantic_content=None):
                self.transaction_states.append(storage.conn.in_transaction)

        graph = TransactionCheckingGraph()
        compressor = Compressor(storage, embeddings, knowledge_graph=graph)
        episode_id = str(uuid.uuid4())
        storage.add_episode(
            id=episode_id,
            session_id="graph-order",
            content="graph ordering episode",
            embedding=[0.1] * 768,
        )
        compress_id = str(uuid.uuid4())
        compressor._pending[compress_id] = {"clusters": [{
            "episodes": [storage.get_episode(episode_id)],
            "centroid": [0.1] * 768,
            "action": "new",
            "match": None,
            "lane": "personal",
        }]}

        try:
            compressor.commit(compress_id, [
                {"content": "graph ordering summary", "kind": "fact", "action": "new"}
            ])
            assert graph.transaction_states == [False]
        finally:
            storage.close()

    def test_compression_skips_graph_feed_when_local_commit_fails(
        self, tmp_path, monkeypatch,
    ):
        from compress import Compressor
        from storage import Storage

        storage = Storage(str(tmp_path / "graph-failure.db"))
        embeddings = MagicMock()
        embeddings.embed.side_effect = lambda texts, prefix=None: [
            [float(i + 1) * 0.1] * 768 for i in range(len(texts))
        ]
        graph = MagicMock()
        compressor = Compressor(storage, embeddings, knowledge_graph=graph)
        episode_id = str(uuid.uuid4())
        storage.add_episode(
            id=episode_id,
            session_id="graph-failure",
            content="graph failure episode",
            embedding=[0.1] * 768,
        )
        compress_id = str(uuid.uuid4())
        compressor._pending[compress_id] = {"clusters": [{
            "episodes": [storage.get_episode(episode_id)],
            "centroid": [0.1] * 768,
            "action": "new",
            "match": None,
            "lane": "personal",
        }]}

        def fail_after_local_writes(**_kwargs):
            raise RuntimeError("injected local failure")

        monkeypatch.setattr(storage, "add_log_entry", fail_after_local_writes)
        try:
            with pytest.raises(RuntimeError, match="injected local failure"):
                compressor.commit(compress_id, [
                    {"content": "graph failure summary", "kind": "fact", "action": "new"}
                ])
            graph.feed.assert_not_called()
            assert compress_id in compressor._pending
        finally:
            storage.close()


class _StubEmbeddings:
    """Enough of an embedding provider for KnowledgeGraph init; never called."""

    def embed(self, texts, prefix=None):
        return [[0.0] * 768 for _ in texts]


class TestKuzuFulltextIndices:
    """graphiti-core 0.28.2's Kuzu driver never creates the full-text indices its
    own search ops query (`build_indices_and_constraints` is a no-op and the
    schema has none), so every feed failed with "Table Entity doesn't have an
    index with name node_name_and_summary". engram creates them at init."""

    EXPECTED = {
        ("Episodic", "episode_content"),
        ("Entity", "node_name_and_summary"),
        ("Community", "community_name"),
        ("RelatesToNode_", "edge_name_and_fact"),
    }

    @staticmethod
    def _indexes(kg):
        import kuzu

        conn = kuzu.Connection(kg._graphiti.driver.db)
        try:
            result = conn.execute("CALL SHOW_INDEXES() RETURN *")
            rows = set()
            while result.has_next():
                row = result.get_next()
                rows.add((row[0], row[1]))
            return rows
        finally:
            conn.close()

    def test_init_creates_the_fulltext_indices_kuzu_search_queries(self, graph_config):
        from knowledge import KnowledgeGraph

        kg = KnowledgeGraph(graph_config, embedding_provider=_StubEmbeddings())
        assert kg.enabled is True
        try:
            assert self.EXPECTED <= self._indexes(kg)
        finally:
            kg.close()

    def test_reinit_on_an_existing_store_is_idempotent(self, graph_config):
        import gc

        from knowledge import KnowledgeGraph

        for _ in range(2):
            kg = KnowledgeGraph(graph_config, embedding_provider=_StubEmbeddings())
            assert kg.enabled is True, "second init on the same store must not degrade"
            assert self.EXPECTED <= self._indexes(kg)
            kg.close()
            del kg
            gc.collect()


class TestBoundedKuzuDriver:
    """Kuzu's default buffer pool is 80% of system RAM in every process that
    opens a graph; engram bounds it (GraphConfig.buffer_pool_mb)."""

    def test_database_opens_with_configured_buffer_pool(self, graph_config, monkeypatch):
        import kuzu

        from knowledge import KnowledgeGraph

        opened = []
        real_database = kuzu.Database

        class RecordingDatabase(real_database):
            def __init__(self, *args, **kwargs):
                opened.append(kwargs.get("buffer_pool_size"))
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(kuzu, "Database", RecordingDatabase)
        graph_config.buffer_pool_mb = 64
        kg = KnowledgeGraph(graph_config, embedding_provider=_StubEmbeddings())
        try:
            assert kg.enabled is True
            assert opened == [64 << 20]
        finally:
            kg.close()

    def test_matches_upstream_driver_state(self, tmp_path):
        """The copied constructor must set everything graphiti's KuzuDriver sets."""
        from graphiti_core.driver.kuzu_driver import KuzuDriver

        from knowledge import _bounded_kuzu_driver

        bounded = _bounded_kuzu_driver(str(tmp_path / "bounded.kuzu"), 64)
        stock = KuzuDriver(db=str(tmp_path / "stock.kuzu"))
        try:
            assert isinstance(bounded, KuzuDriver)
            assert set(vars(bounded)) == set(vars(stock))
            for name, value in vars(stock).items():
                assert type(getattr(bounded, name)) is type(value), name
        finally:
            bounded.db.close()
            stock.db.close()


def _bare_graph(graph_config):
    """A KnowledgeGraph with a mocked Graphiti and no loop thread yet."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from knowledge import KnowledgeGraph

    kg = KnowledgeGraph.__new__(KnowledgeGraph)
    kg._config = graph_config
    kg._config.enabled = True
    kg._executor = None
    kg._background_feeds = set()
    kg._graphiti = MagicMock()
    kg._graphiti.close = AsyncMock()
    return kg, asyncio


_EPISODE = {"id": "ep-bg", "content": "Vin trained with Kelsier", "created_at": "2026-03-25T10:00:00+00:00"}


class TestBackgroundFeeds:
    """compress_commit must return while extraction runs; recall must not wait
    behind it. Both need every Graphiti coroutine on one persistent loop."""

    def test_run_async_reuses_one_loop_thread_off_the_caller(self, graph_config):
        import threading

        kg, asyncio = _bare_graph(graph_config)
        seen = []

        async def probe():
            seen.append((id(asyncio.get_running_loop()), threading.get_ident()))
            return 1

        assert kg._run_async(probe()) == 1
        assert kg._run_async(probe()) == 1
        try:
            assert seen[0] == seen[1]
            assert seen[0][1] != threading.get_ident()
        finally:
            kg.close()

    def test_feed_background_returns_before_extraction_finishes(self, graph_config):
        from unittest.mock import AsyncMock, MagicMock

        kg, asyncio = _bare_graph(graph_config)

        async def slow_add(**_kwargs):
            await asyncio.sleep(0.4)
            return MagicMock(nodes=[MagicMock()], edges=[])

        kg._graphiti.add_episode = AsyncMock(side_effect=slow_add)
        try:
            future = kg.feed_background([_EPISODE], semantic_content="training")
            assert future.done() is False
            assert kg.pending_background_feeds == 1
            result = future.result(timeout=5)
            assert result["episodes_fed"] == 1
            assert kg.pending_background_feeds == 0
        finally:
            kg.close()

    def test_search_is_not_blocked_by_a_background_feed(self, graph_config):
        import time
        from unittest.mock import AsyncMock, MagicMock

        kg, asyncio = _bare_graph(graph_config)

        async def slow_add(**_kwargs):
            await asyncio.sleep(1.0)
            return MagicMock(nodes=[], edges=[])

        kg._graphiti.add_episode = AsyncMock(side_effect=slow_add)
        kg._graphiti.search = AsyncMock(return_value=[])
        try:
            future = kg.feed_background([_EPISODE], semantic_content="training")
            t0 = time.monotonic()
            assert kg.search("Kelsier") == {"facts": [], "historical": []}
            assert time.monotonic() - t0 < 0.5, "search waited behind the feed"
            assert future.done() is False
            future.result(timeout=5)
        finally:
            kg.close()

    def test_close_cancels_pending_background_feeds(self, graph_config):
        import time
        from unittest.mock import AsyncMock, MagicMock

        kg, asyncio = _bare_graph(graph_config)

        async def very_slow_add(**_kwargs):
            await asyncio.sleep(30)
            return MagicMock(nodes=[], edges=[])

        kg._graphiti.add_episode = AsyncMock(side_effect=very_slow_add)
        future = kg.feed_background([_EPISODE], semantic_content="training")
        t0 = time.monotonic()
        kg.close()
        assert time.monotonic() - t0 < 5
        assert future.cancelled() or future.done()
        assert kg._graphiti is None
        assert kg._executor is None

    def test_disabled_graph_feed_background_is_none(self):
        from config import GraphConfig
        from knowledge import KnowledgeGraph

        kg = KnowledgeGraph(GraphConfig(enabled=False))
        assert kg.feed_background([_EPISODE]) is None


class TestCompressorBackgroundFeeds:
    def test_background_mode_queues_instead_of_blocking(self, tmp_path):
        from unittest.mock import MagicMock

        from compress import Compressor
        from storage import Storage

        store = Storage(str(tmp_path / "c.db"))
        try:
            graph = MagicMock()
            compressor = Compressor(store, MagicMock(), None, knowledge_graph=graph)
            feeds = [([_EPISODE], "sem-a"), ([_EPISODE], "sem-b")]

            assert compressor._feed_knowledge_graph(feeds) == 2
            assert graph.feed.call_count == 2
            graph.feed_background.assert_not_called()

            compressor.background_knowledge_feeds = True
            assert compressor._feed_knowledge_graph(feeds) == 2
            assert graph.feed_background.call_count == 2
            assert graph.feed.call_count == 2
        finally:
            store.close()
