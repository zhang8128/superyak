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
        self._executor = None

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
            import concurrent.futures
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            return self._executor.submit(asyncio.run, coro).result()
        else:
            return asyncio.run(coro)

    def close(self):
        """Clean up Graphiti resources."""
        if self._graphiti is not None:
            try:
                self._run_async(self._graphiti.close())
            except Exception:
                logger.debug("Knowledge graph close failed", exc_info=True)
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
