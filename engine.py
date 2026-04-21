"""EngineCore — shared memory engine for recall, remember, and queries.

Used by local_agent.py, mirror.py, divergence.py, and anything else that
needs engram's memories without the full MCP server. server.py has its own
richer recall (dream bias, resonance, uninvited memories, provenance) that
builds on Storage directly.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from embeddings import NomicEmbedProvider
from storage import Storage, vec0_distance_to_similarity, _pack_embedding

logger = logging.getLogger(__name__)


class EngineCore:
    """Lightweight memory engine owning Storage + Embeddings."""

    def __init__(self, db_path: str | Path):
        self.storage = Storage(str(db_path))
        self.embeddings = NomicEmbedProvider()

    def recall(
        self,
        query: str,
        max_results: int = 10,
        layer: str | None = None,
    ) -> list[dict]:
        """Vector search across all memory layers.

        Returns sorted results with id, content, layer, score, and
        layer-specific fields (core/source for episodes, kind/confidence
        for semantics, trigger/strength for instincts).
        """
        query_embedding = self.embeddings.embed([query], prefix="search_query")[0]
        packed = _pack_embedding(query_embedding)
        results = []

        layer_specs = [
            ("episode", "episodes", "episode_vectors",
             "e.id, e.content, e.core, e.source, v.distance"),
            ("semantic", "semantics", "semantic_vectors",
             "s.id, s.content, s.kind, s.confidence, v.distance"),
            ("instinct", "instincts", "instinct_vectors",
             "i.id, i.action, i.trigger, i.strength, v.distance"),
        ]

        for lname, table, vec_table, cols in layer_specs:
            if layer is not None and layer != lname:
                continue
            alias = table[0]
            try:
                rows = self.storage.conn.execute(
                    f"SELECT {cols} "
                    f"FROM {vec_table} v "
                    f"JOIN {table} {alias} ON {alias}.id = v.id "
                    f"WHERE v.embedding MATCH ? AND k = ?",
                    (packed, max_results),
                ).fetchall()
            except Exception as e:
                logger.debug("Vector search failed for %s: %s", lname, e)
                continue

            for r in rows:
                entry = {
                    "id": r[0],
                    "content": r[1],
                    "layer": lname,
                    "score": vec0_distance_to_similarity(r[-1]),
                }
                if lname == "episode":
                    entry["core"] = bool(r[2])
                    entry["source"] = r[3]
                elif lname == "semantic":
                    entry["kind"] = r[2]
                    entry["confidence"] = r[3]
                elif lname == "instinct":
                    entry["trigger"] = r[2]
                    entry["strength"] = r[3]
                results.append(entry)

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:max_results]

    def remember(
        self,
        content: str,
        session_id: str | None = None,
        core: bool = False,
        source: str | None = None,
    ) -> str:
        """Store an episode. Returns the episode ID."""
        episode_id = str(uuid.uuid4())
        embedding = self.embeddings.embed([content], prefix="search_document")[0]
        self.storage.add_episode(
            id=episode_id,
            session_id=session_id,
            content=content,
            embedding=embedding,
        )
        if core:
            self.storage.mark_core(episode_id)
        if source:
            self.storage.set_episode_source(episode_id, source)
        return episode_id

    def get_instincts(self) -> list[dict]:
        rows = self.storage.conn.execute(
            "SELECT trigger, action, strength FROM instincts ORDER BY strength DESC"
        ).fetchall()
        return [{"trigger": r[0], "action": r[1], "strength": r[2]} for r in rows]

    def get_core_episodes(self) -> list[dict]:
        rows = self.storage.conn.execute(
            "SELECT content, source FROM episodes WHERE core = 1 ORDER BY created_at"
        ).fetchall()
        return [{"content": r[0], "source": r[1]} for r in rows]

    def close(self):
        self.storage.close()
