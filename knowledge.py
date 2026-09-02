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
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import GraphConfig

logger = logging.getLogger("engram.knowledge")


def _fmt_dt(dt) -> str | None:
    """Format a datetime to ISO string, or None."""
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


class KnowledgeGraph:
    """Bridge between engram and Graphiti.

    Two integration points:
    - feed(): called during compression to send episodes for extraction
    - search(): called during recall to get entities and facts
    """

    def __init__(self, config: GraphConfig, embedding_provider=None):
        self._config = config
        self._embedding_provider = embedding_provider
        self._graphiti = None
        self._executor = None

        if not config.enabled:
            logger.info("Knowledge graph disabled")
            return

        try:
            self._init_graphiti()
        except Exception as exc:
            self._shutdown_executor()
            logger.warning(
                "Knowledge graph init failed — continuing without: %s", exc
            )
            self._graphiti = None
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
        from graphiti_local import GraphitiEmbedder, GraphitiReranker

        if self._embedding_provider is None:
            raise ValueError("Knowledge graph requires an embedding provider")

        db_path = self._config.db_path
        if not db_path:
            home = Path(os.environ.get("ENGRAM_HOME") or Path(__file__).resolve().parent)
            db_path = str(home / ".engram" / "knowledge.kuzu")

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        driver = None
        graphiti = None
        try:
            driver = KuzuDriver(db=db_path)

            # Ollama exposes an OpenAI-compatible API
            model = os.environ.get("ENGRAM_GRAPH_MODEL", self._config.model)
            ollama_url = self._config.ollama_url

            llm_client = OpenAIGenericClient(
                config=LLMConfig(
                    base_url=f"{ollama_url}/v1",
                    api_key="ollama",
                    model=model,
                    small_model=model,
                ),
            )

            graphiti = Graphiti(
                graph_driver=driver,
                llm_client=llm_client,
                embedder=GraphitiEmbedder(self._embedding_provider),
                cross_encoder=GraphitiReranker(self._embedding_provider),
            )

            self._run_async(graphiti.build_indices_and_constraints())
            self._ensure_kuzu_fulltext_indices(driver)
        except Exception:
            resource = graphiti if graphiti is not None else driver
            try:
                if resource is not None:
                    self._run_async(resource.close())
            except Exception:
                pass
            raise

        self._graphiti = graphiti
        logger.info("Knowledge graph initialized (kuzu: %s, model: %s)", db_path, model)

    @staticmethod
    def _ensure_kuzu_fulltext_indices(driver) -> int:
        """Create the full-text indices Graphiti's Kuzu search ops query.

        graphiti-core 0.28.2: `KuzuDriver.build_indices_and_constraints` is a
        no-op (its comment says the schema creates the indices; it does not),
        while `driver/kuzu/operations/search_ops.py` queries
        `node_name_and_summary` and three siblings with QUERY_FTS_INDEX. The
        statements exist in `graph_queries.get_fulltext_indices(KUZU)`; only
        the Neo4j and FalkorDB drivers run them. Until they exist every feed
        fails with "Table Entity doesn't have an index with name
        node_name_and_summary". CREATE_FTS_INDEX is not idempotent, so check
        SHOW_INDEXES first. Returns how many indices were created.
        """
        import re

        import kuzu
        from graphiti_core.driver.driver import GraphProvider
        from graphiti_core.graph_queries import get_fulltext_indices

        database = getattr(driver, "db", None)
        if not isinstance(database, kuzu.Database):
            return 0  # not a live Kuzu store (other provider, or a test double)

        conn = kuzu.Connection(database)
        try:
            existing = set()
            result = conn.execute("CALL SHOW_INDEXES() RETURN *")
            while result.has_next():
                row = result.get_next()
                existing.add((row[0], row[1]))
            created = 0
            for statement in get_fulltext_indices(GraphProvider.KUZU):
                match = re.search(r"CREATE_FTS_INDEX\('(\w+)', '(\w+)'", statement)
                if match and (match.group(1), match.group(2)) in existing:
                    continue
                conn.execute(statement)
                created += 1
            if created:
                logger.info("Created %d Kuzu full-text indices for Graphiti search", created)
            return created
        finally:
            conn.close()

    def _run_async(self, coro):
        """Run an async coroutine synchronously.

        Graphiti's API is async. Engram's MCP tools are sync.
        This bridges the gap.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        import concurrent.futures
        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        if loop and loop.is_running():
            return self._executor.submit(asyncio.run, coro).result(timeout=900)
        else:
            return asyncio.run(coro)

    def _shutdown_executor(self):
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

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
        fed = 0
        failed = 0

        for ep in episodes:
            ep_id = ep.get("id", "unknown")
            created_at = ep.get("created_at", "")
            try:
                ref_time = datetime.fromisoformat(created_at)
                if ref_time.tzinfo is None:
                    # Engram stores UTC; treat naive timestamps as UTC
                    ref_time = ref_time.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                ref_time = datetime.now(timezone.utc)

            try:
                result = self._run_async(
                    self._graphiti.add_episode(
                        name=f"engram-{ep_id}",
                        episode_body=ep.get("content", ""),
                        source_description=semantic_content or "engram compression",
                        reference_time=ref_time,
                        source=EpisodeType.text,
                    )
                )
                total_nodes += len(result.nodes)
                total_edges += len(result.edges)
                fed += 1
            except Exception:
                failed += 1
                logger.warning("Failed to feed episode %s to knowledge graph", ep_id, exc_info=True)

        logger.info(
            "Knowledge graph feed: %d/%d succeeded, %d entities, %d relationships",
            fed, len(episodes), total_nodes, total_edges,
        )

        return {
            "episodes_fed": fed,
            "episodes_failed": failed,
            "entities_extracted": total_nodes,
            "relationships_extracted": total_edges,
        }

    def search(self, query: str, num_results: int = 10) -> dict | None:
        """Search the knowledge graph for entities and facts.

        Called during recall to enrich memory results with structured knowledge.

        Args:
            query: Search query string.
            num_results: Max results to return.

        Returns:
            Dict with 'facts' (current) and 'historical' (invalidated),
            or None if disabled/unavailable/failed.
        """
        if not self.enabled or not self._graphiti:
            return None

        try:
            edges = self._run_async(
                self._graphiti.search(query=query, num_results=num_results)
            )
        except Exception:
            logger.warning("Knowledge graph search failed", exc_info=True)
            return None

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

    def get_entity_neighbors(self, memory_content: str, exclude_id: str, num_results: int = 10) -> list[dict]:
        """Find memories that share entities with the given content.

        Searches the knowledge graph for edges whose source or target nodes
        relate to the given content. Returns lightweight dicts suitable for
        passing as entity_neighbors to Storage.get_neighbors().

        Returns empty list if knowledge graph is disabled or errors.
        """
        if not self.enabled or not self._graphiti:
            return []
        try:
            edges = self._run_async(
                self._graphiti.search(query=memory_content, num_results=num_results)
            )
            neighbors = []
            seen: set[str] = set()
            for edge in (edges or []):
                edge_id = str(getattr(edge, "uuid", ""))
                if edge_id and edge_id != exclude_id and edge_id not in seen:
                    seen.add(edge_id)
                    source = getattr(edge, "source_node_name", "") or ""
                    target = getattr(edge, "target_node_name", "") or ""
                    fact = getattr(edge, "fact", "") or ""
                    relationship = getattr(edge, "name", "") or ""
                    # Build a readable content string from the edge fact
                    content = fact or f"{source} {relationship} {target}"
                    entity_name = source or target or relationship
                    neighbors.append({
                        "id": edge_id,
                        "content": content,
                        "layer": "entity",
                        "entity_name": entity_name,
                    })
            return neighbors[:num_results]
        except Exception:
            logger.debug("get_entity_neighbors failed", exc_info=True)
            return []

    def close(self):
        """Clean up Graphiti resources."""
        first_error = None
        if self._graphiti is not None:
            try:
                self._run_async(self._graphiti.close())
            except Exception as exc:
                first_error = exc
            else:
                self._graphiti = None
        try:
            self._shutdown_executor()
        except Exception as exc:
            if first_error is None:
                first_error = exc
        if first_error is not None:
            raise first_error
