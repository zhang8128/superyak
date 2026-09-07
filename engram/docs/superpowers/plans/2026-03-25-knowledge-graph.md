# Knowledge Graph Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Graphiti (with Kuzu embedded backend) alongside engram for entity/relationship/temporal fact tracking, integrated at compression and recall.

**Architecture:** Two systems with clear boundary — engram owns identity (episodes → semantics → instincts), Graphiti owns applied knowledge (entities, relationships, temporal facts). Compression feeds episodes to Graphiti for extraction. Recall queries both and merges results.

**Tech Stack:** graphiti-core, kuzu, Ollama (nemotron-nano default) via OpenAI-compatible generic client, engram's existing FastEmbed for embeddings.

**Spec:** `docs/superpowers/specs/2026-03-25-knowledge-graph-design.md`

---

### Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add graphiti-core and kuzu to dependencies**

```toml
dependencies = [
    "mcp>=1.9",
    "sqlite-vec>=0.1.6",
    "onnxruntime>=1.18",
    "fastembed>=0.7",
    "tree-sitter>=0.24",
    "tree-sitter-python>=0.23",
    "tree-sitter-javascript>=0.23",
    "tree-sitter-typescript>=0.23",
    "watchfiles>=1.0",
    "scipy>=1.14",
    "graphiti-core[kuzu]>=0.5",
]
```

- [ ] **Step 2: Install dependencies**

Run: `cd /Users/kairos/Projects/engram && uv sync`
Expected: Dependencies install successfully, including graphiti-core and kuzu.

- [ ] **Step 3: Verify imports work**

Run: `.venv/bin/python -c "from graphiti_core import Graphiti; from graphiti_core.driver.kuzu_driver import KuzuDriver; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add graphiti-core[kuzu] for knowledge graph"
```

---

### Task 2: Create the Graphiti bridge module

**Files:**
- Create: `knowledge.py`
- Modify: `config.py`
- Test: `tests/test_knowledge.py`

This module owns all Graphiti interaction — initialization, episode feeding, search, and result formatting. The rest of engram only imports this module.

- [ ] **Step 1: Add GraphConfig to config.py**

Add after `SignalsConfig`:

```python
@dataclass
class GraphConfig:
    enabled: bool = True
    model: str = "nemotron-nano"
    ollama_url: str = "http://localhost:11434"
    db_path: str = ""  # set at runtime based on ENGRAM_HOME
```

Add to `EngramConfig`:

```python
graph: GraphConfig = field(default_factory=GraphConfig)
```

Add to `_DEFAULT_TOML`:

```toml
[graph]
enabled = true
model = "nemotron-nano"
ollama_url = "http://localhost:11434"
```

Add to `load_config()`:

```python
graph=GraphConfig(**raw.get("graph", {})),
```

- [ ] **Step 2: Write failing test for KnowledgeGraph init**

```python
# tests/test_knowledge.py
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
        assert kg.enabled is True

    def test_disabled_graph_skips_init(self):
        config = GraphConfig(enabled=False)
        from knowledge import KnowledgeGraph

        kg = KnowledgeGraph(config)
        assert kg.enabled is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'knowledge'`

- [ ] **Step 4: Write minimal KnowledgeGraph class**

```python
# knowledge.py
"""Graphiti knowledge graph bridge.

Owns all interaction with Graphiti — init, episode feeding, search.
Engram's identity layers (episodes, semantics, instincts, dreams)
are unchanged. This module adds applied knowledge: entities,
relationships, and temporal facts.

Graphiti uses Kuzu (embedded) for storage and Ollama for extraction.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import GraphConfig

logger = logging.getLogger("engram.knowledge")


class KnowledgeGraph:
    """Bridge between engram and Graphiti.

    Two integration points:
    - feed(): called during compression to send episodes for extraction
    - search(): called during recall to get entities and facts
    """

    def __init__(self, config: GraphConfig):
        self._config = config
        self._graphiti = None
        self._loop = None

        if not config.enabled:
            logger.info("Knowledge graph disabled")
            return

        try:
            self._init_graphiti()
        except Exception:
            logger.warning("Knowledge graph init failed — continuing without", exc_info=True)
            self._config.enabled = False

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def _init_graphiti(self):
        """Initialize Graphiti with Kuzu backend and Ollama LLM."""
        from graphiti_core import Graphiti
        from graphiti_core.driver.kuzu_driver import KuzuDriver
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
        from graphiti_core.llm_client.config import LLMConfig

        db_path = self._config.db_path
        if not db_path:
            home = Path(os.environ.get("ENGRAM_HOME", Path.home() / "Projects" / "engram"))
            db_path = str(home / ".engram" / "knowledge.kuzu")

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        driver = KuzuDriver(db=db_path)

        # Ollama exposes an OpenAI-compatible API
        model = os.environ.get("ENGRAM_GRAPH_MODEL", self._config.model)
        ollama_url = self._config.ollama_url

        llm_client = OpenAIGenericClient(
            base_url=f"{ollama_url}/v1",
            api_key="ollama",  # Ollama doesn't need a real key
            config=LLMConfig(model=model, small_model=model),
        )

        # Use Graphiti's default embedder config — we only need it for
        # Graphiti's internal entity/relationship vectors, not for engram's
        # memory vectors (which use FastEmbed separately).
        self._graphiti = Graphiti(
            graph_driver=driver,
            llm_client=llm_client,
        )

        # Build indices
        self._run_async(self._graphiti.build_indices_and_constraints())
        logger.info("Knowledge graph initialized (kuzu: %s, model: %s)", db_path, model)

    def _run_async(self, coro):
        """Run an async coroutine synchronously.

        Graphiti's API is async. Engram's MCP tools are sync.
        This bridges the gap.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're inside an existing event loop — use a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return asyncio.run(coro)

    def close(self):
        """Clean up Graphiti resources."""
        if self._graphiti is not None:
            try:
                self._run_async(self._graphiti.close())
            except Exception:
                logger.debug("Knowledge graph close failed", exc_info=True)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py::TestKnowledgeGraphInit -v`
Expected: PASS (disabled test passes; init test may warn if Ollama isn't running but should still create the object)

- [ ] **Step 6: Commit**

```bash
git add knowledge.py config.py tests/test_knowledge.py
git commit -m "feat: knowledge graph bridge module with Graphiti + Kuzu init"
```

---

### Task 3: Episode feeding during compression

**Files:**
- Modify: `knowledge.py`
- Modify: `compress.py`
- Test: `tests/test_knowledge.py`

When `compress()` creates a semantic from an episode cluster, the cluster's episodes are also fed to Graphiti.

- [ ] **Step 1: Write failing test for feed()**

Add to `tests/test_knowledge.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


class TestKnowledgeGraphFeed:
    def test_feed_episodes_calls_graphiti(self, graph_config):
        from knowledge import KnowledgeGraph

        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg._config = graph_config
        kg._config.enabled = True
        kg._graphiti = MagicMock()
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
        assert kg._graphiti.add_episode.call_count == 2

    def test_feed_disabled_is_noop(self):
        from knowledge import KnowledgeGraph

        config = GraphConfig(enabled=False)
        kg = KnowledgeGraph(config)
        result = kg.feed([], semantic_content="test")
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py::TestKnowledgeGraphFeed -v`
Expected: FAIL — `AttributeError: 'KnowledgeGraph' object has no attribute 'feed'`

- [ ] **Step 3: Implement feed() in knowledge.py**

Add to `KnowledgeGraph` class:

```python
    def feed(
        self,
        episodes: list[dict],
        semantic_content: str = "",
    ) -> dict | None:
        """Feed episode cluster to Graphiti for entity/relationship extraction.

        Called during compression after a semantic is created.
        Each episode becomes a Graphiti episode with extraction.

        Args:
            episodes: List of engram episode dicts (id, content, created_at).
            semantic_content: The semantic summary, used as source_description.

        Returns:
            Summary of extracted entities/relationships, or None if disabled.
        """
        if not self.enabled or not self._graphiti or not episodes:
            return None

        from graphiti_core.nodes import EpisodeType

        total_nodes = 0
        total_edges = 0

        for ep in episodes:
            created_at = ep.get("created_at", "")
            try:
                ref_time = datetime.fromisoformat(created_at)
                if ref_time.tzinfo is None:
                    ref_time = ref_time.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                ref_time = datetime.now(timezone.utc)

            try:
                result = self._run_async(
                    self._graphiti.add_episode(
                        name=f"engram-{ep['id']}",
                        episode_body=ep.get("content", ""),
                        source_description=semantic_content or "engram compression",
                        reference_time=ref_time,
                        source=EpisodeType.text,
                    )
                )
                total_nodes += len(result.nodes)
                total_edges += len(result.edges)
            except Exception:
                logger.warning("Failed to feed episode %s to knowledge graph", ep["id"], exc_info=True)

        logger.info(
            "Fed %d episodes to knowledge graph: %d entities, %d relationships",
            len(episodes), total_nodes, total_edges,
        )

        return {
            "episodes_fed": len(episodes),
            "entities_extracted": total_nodes,
            "relationships_extracted": total_edges,
        }
```

Add imports at the top of `knowledge.py`:

```python
from datetime import datetime, timezone
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py::TestKnowledgeGraphFeed -v`
Expected: PASS

- [ ] **Step 5: Wire feed() into compress.py commit()**

In `compress.py`, modify `__init__` to accept an optional `knowledge_graph` parameter:

```python
    def __init__(
        self,
        storage: Storage,
        embedding_provider,
        config: CompressionConfig | None = None,
        deduplicator: Deduplicator | None = None,
        knowledge_graph=None,
    ):
        self._storage = storage
        self._embeddings = embedding_provider
        self._config = config
        self._dedup = deduplicator
        self._knowledge_graph = knowledge_graph
        self._pending: dict[str, dict] = {}
```

In `commit()`, after the semantic is created (after `semantics_created += 1` and before `self._storage.mark_episodes_compressed`), add:

```python
                # Feed episode cluster to knowledge graph for entity extraction
                if self._knowledge_graph is not None:
                    try:
                        self._knowledge_graph.feed(
                            cluster["episodes"],
                            semantic_content=semantic_content,
                        )
                    except Exception:
                        logger.warning("Knowledge graph feed failed", exc_info=True)
```

- [ ] **Step 6: Run existing tests to verify no breakage**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All existing tests pass (knowledge_graph defaults to None)

- [ ] **Step 7: Commit**

```bash
git add knowledge.py compress.py tests/test_knowledge.py
git commit -m "feat: feed episode clusters to Graphiti during compression"
```

---

### Task 4: Knowledge search during recall

**Files:**
- Modify: `knowledge.py`
- Test: `tests/test_knowledge.py`

- [ ] **Step 1: Write failing test for search()**

Add to `tests/test_knowledge.py`:

```python
class TestKnowledgeGraphSearch:
    def test_search_returns_entities_and_facts(self, graph_config):
        from knowledge import KnowledgeGraph

        # Mock a search result
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
        current.source_node_uuid = "n-1"
        current.target_node_uuid = "n-2"
        current.source_node_name = "Vin"
        current.target_node_name = "Kelsier"

        historical = MagicMock()
        historical.uuid = "e-2"
        historical.name = "distrusts"
        historical.fact = "Vin distrusts everyone"
        historical.valid_at = datetime(2026, 3, 20, tzinfo=timezone.utc)
        historical.invalid_at = datetime(2026, 3, 24, tzinfo=timezone.utc)
        historical.source_node_uuid = "n-1"
        historical.target_node_uuid = "n-3"
        historical.source_node_name = "Vin"
        historical.target_node_name = "everyone"

        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg._config = graph_config
        kg._config.enabled = True
        kg._graphiti = MagicMock()
        kg._graphiti.search = AsyncMock(return_value=[current, historical])

        result = kg.search("Vin")
        assert len(result["facts"]) == 1
        assert len(result["historical"]) == 1
        assert result["historical"][0]["invalid_at"] is not None

    def test_search_disabled_returns_none(self):
        from knowledge import KnowledgeGraph

        config = GraphConfig(enabled=False)
        kg = KnowledgeGraph(config)
        result = kg.search("anything")
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py::TestKnowledgeGraphSearch -v`
Expected: FAIL — `AttributeError: 'KnowledgeGraph' object has no attribute 'search'`

- [ ] **Step 3: Implement search() in knowledge.py**

Add to `KnowledgeGraph` class:

```python
    def search(self, query: str, num_results: int = 10) -> dict | None:
        """Search the knowledge graph for entities and facts.

        Called during recall to enrich memory results with structured knowledge.

        Args:
            query: Search query string.
            num_results: Max results to return.

        Returns:
            Dict with 'facts' (current) and 'historical' (invalidated), or None if disabled.
        """
        if not self.enabled or not self._graphiti:
            return None

        try:
            edges = self._run_async(
                self._graphiti.search(query=query, num_results=num_results)
            )
        except Exception:
            logger.warning("Knowledge graph search failed", exc_info=True)
            return {"facts": [], "historical": []}

        facts = []
        historical = []

        for edge in edges:
            entry = {
                "id": str(getattr(edge, "uuid", "")),
                "relationship": getattr(edge, "name", ""),
                "fact": getattr(edge, "fact", ""),
                "source": getattr(edge, "source_node_name", ""),
                "target": getattr(edge, "target_node_name", ""),
                "valid_at": _fmt_dt(getattr(edge, "valid_at", None)),
            }

            invalid_at = getattr(edge, "invalid_at", None)
            if invalid_at is not None:
                entry["invalid_at"] = _fmt_dt(invalid_at)
                historical.append(entry)
            else:
                facts.append(entry)

        return {"facts": facts, "historical": historical}
```

Add module-level helper:

```python
def _fmt_dt(dt) -> str | None:
    """Format a datetime to ISO string, or None."""
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py::TestKnowledgeGraphSearch -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add knowledge.py tests/test_knowledge.py
git commit -m "feat: knowledge graph search with current/historical fact separation"
```

---

### Task 5: Wire knowledge graph into server.py

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Add knowledge graph initialization to _init()**

In `server.py`, add a global:

```python
_knowledge_graph = None
```

In `_init()`, after the compressor is created (after line ~173), add:

```python
    # Knowledge graph (Graphiti + Kuzu)
    graph_model = os.environ.get("ENGRAM_GRAPH_MODEL")
    if _config and _config.graph.enabled:
        from knowledge import KnowledgeGraph
        graph_config = _config.graph
        if graph_model:
            graph_config.model = graph_model
        # Set DB path based on engram home
        if not graph_config.db_path:
            graph_config.db_path = str(db_path.parent / "knowledge.kuzu")
        _knowledge_graph = KnowledgeGraph(graph_config)
    else:
        _knowledge_graph = None
```

Pass it to the compressor:

```python
    _compressor = Compressor(
        _storage, _embeddings,
        _config.compression if _config else None,
        deduplicator=_dedup,
        knowledge_graph=_knowledge_graph,
    )
```

Add `_knowledge_graph` to the global declaration at the top of `_init()`.

Add cleanup in the atexit handlers:

```python
    atexit.register(lambda: _knowledge_graph.close() if _knowledge_graph else None)
```

- [ ] **Step 2: Add knowledge results to recall()**

In the `recall()` function, after the resonance surfacing and before the final return, add knowledge graph results:

```python
    # Knowledge graph: entities and temporal facts
    knowledge = None
    if _knowledge_graph is not None and _knowledge_graph.enabled:
        try:
            knowledge = _knowledge_graph.search(query)
        except Exception:
            logger.warning("Knowledge graph search failed during recall", exc_info=True)
```

In the return dict, add the knowledge field:

```python
    response = {"results": results, "recall_id": recall_id}
    if dreaming:
        response["dreaming"] = True
        response["note"] = "Scores hidden — some memories may be dream-pulled. Use dream_verify(recall_id) after engaging."
    if knowledge:
        response["knowledge"] = knowledge
    return response
```

- [ ] **Step 3: Run existing tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All existing tests pass. Knowledge graph init may fail gracefully (Ollama not running / missing model) but server still works — the enabled flag gets set to False on failure.

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "feat: wire knowledge graph into server init and recall"
```

---

### Task 6: Integration test

**Files:**
- Test: `tests/test_knowledge.py`

- [ ] **Step 1: Write integration test with mocked Graphiti**

Add to `tests/test_knowledge.py`:

```python
class TestKnowledgeGraphIntegration:
    """Test the full flow: compression feeds Graphiti, recall queries it."""

    def test_compress_feeds_knowledge_graph(self, tmp_path):
        """Verify compression passes episodes to knowledge graph."""
        from unittest.mock import MagicMock, AsyncMock, patch
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

        # Mock embeddings
        embeddings = MagicMock()
        embeddings.embed.return_value = [[0.1] * 768, [0.2] * 768]

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
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py::TestKnowledgeGraphIntegration -v`
Expected: PASS

- [ ] **Step 3: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_knowledge.py
git commit -m "test: integration test for compression → knowledge graph flow"
```

---

### Task 7: Update pyproject.toml module list and CLAUDE.md

**Files:**
- Modify: `pyproject.toml`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add knowledge to py-modules**

In `pyproject.toml`, add `"knowledge"` to the `py-modules` list:

```toml
py-modules = ["server", "storage", "embeddings", "compress", "reflection", "indexer", "config", "logging_config", "watcher", "dedup", "knowledge"]
```

- [ ] **Step 2: Update CLAUDE.md key files table**

Add to the Key Files table:

```markdown
| `knowledge.py` | Graphiti bridge — entity extraction and temporal facts |
```

Add to the MCP Tools table or Architecture section, a note about the knowledge graph:

```markdown
**Knowledge graph:** Graphiti (Kuzu embedded) runs alongside engram for applied
knowledge — entities, relationships, temporal facts. Fed during compression,
queried during recall. Config: `ENGRAM_GRAPH_MODEL` env var (default: nemotron-nano).
Separate from identity layers.
```

- [ ] **Step 3: Run all tests one final time**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml CLAUDE.md
git commit -m "docs: add knowledge graph to module list and CLAUDE.md"
```
