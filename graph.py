"""Unified memory graph — virtual view over engram's relationship types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage import Storage

@dataclass
class Edge:
    source: str
    source_layer: str
    target: str
    target_layer: str
    edge_type: str
    weight: float
    directed: bool

    def __post_init__(self):
        self.weight = max(0.0, min(1.0, self.weight))

@dataclass
class Node:
    id: str
    layer: str
    preview: str


import logging

logger = logging.getLogger("engram.graph")


class MemoryGraph:
    """Virtual unified view over engram's memory relationships.

    Reads from existing tables — no new storage. Presents all edge types
    through a single interface.
    """

    def __init__(self, storage: Storage, knowledge_graph=None):
        self._storage = storage
        self._kg = knowledge_graph

    def neighbors(self, node_id: str) -> list[Edge]:
        """All edges touching a node, across all relationship types."""
        edges: list[Edge] = []

        # --- Resonances (bidirectional) ---
        rows = self._storage.conn.execute(
            """SELECT r.memory_a, r.layer_a, r.memory_b, r.layer_b,
                      r.weight, r.strength
               FROM resonances r
               WHERE r.memory_a = ? OR r.memory_b = ?""",
            (node_id, node_id),
        ).fetchall()
        for row in rows:
            if row[0] == node_id:
                peer_id, peer_layer = row[2], row[3]
            else:
                peer_id, peer_layer = row[0], row[1]
            source_layer = self._detect_layer(node_id)
            if source_layer:
                edges.append(Edge(
                    source=node_id, source_layer=source_layer,
                    target=peer_id, target_layer=peer_layer,
                    edge_type="resonance",
                    weight=row[4] * row[5],
                    directed=False,
                ))

        # --- Provenance: episode → semantics built from it ---
        sem_children = self._storage.conn.execute(
            "SELECT semantic_id, similarity FROM semantic_sources WHERE episode_id = ?",
            (node_id,),
        ).fetchall()
        for row in sem_children:
            edges.append(Edge(
                source=node_id, source_layer="episode",
                target=row[0], target_layer="semantic",
                edge_type="provenance",
                weight=row[1] if row[1] is not None else 1.0,
                directed=True,
            ))

        # --- Provenance: semantic → source episodes ---
        ep_parents = self._storage.conn.execute(
            "SELECT episode_id, similarity FROM semantic_sources WHERE semantic_id = ?",
            (node_id,),
        ).fetchall()
        for row in ep_parents:
            edges.append(Edge(
                source=node_id, source_layer="semantic",
                target=row[0], target_layer="episode",
                edge_type="provenance",
                weight=row[1] if row[1] is not None else 1.0,
                directed=True,
            ))

        # --- Provenance: semantic → instincts derived from it ---
        ins_children = self._storage.conn.execute(
            "SELECT instinct_id FROM instinct_sources WHERE semantic_id = ?",
            (node_id,),
        ).fetchall()
        for (ins_id,) in ins_children:
            edges.append(Edge(
                source=node_id, source_layer="semantic",
                target=ins_id, target_layer="instinct",
                edge_type="provenance", weight=1.0, directed=True,
            ))

        # --- Provenance: instinct → source semantics ---
        sem_parents = self._storage.conn.execute(
            "SELECT semantic_id FROM instinct_sources WHERE instinct_id = ?",
            (node_id,),
        ).fetchall()
        for (sem_id,) in sem_parents:
            edges.append(Edge(
                source=node_id, source_layer="instinct",
                target=sem_id, target_layer="semantic",
                edge_type="provenance", weight=1.0, directed=True,
            ))

        # --- Co-firing: instinct ↔ instinct ---
        cofire_rows = self._storage.conn.execute(
            """SELECT instinct_a, instinct_b, co_fire_count
               FROM instinct_co_firing
               WHERE instinct_a = ? OR instinct_b = ?""",
            (node_id, node_id),
        ).fetchall()
        if cofire_rows:
            max_cofire = max(r[2] for r in cofire_rows) or 1
            for row in cofire_rows:
                peer = row[1] if row[0] == node_id else row[0]
                edges.append(Edge(
                    source=node_id, source_layer="instinct",
                    target=peer, target_layer="instinct",
                    edge_type="co_firing",
                    weight=row[2] / max_cofire,
                    directed=False,
                ))

        # --- Contradiction: semantic → semantic ---
        contra = self._storage.conn.execute(
            "SELECT id FROM semantics WHERE contradicted_by = ?",
            (node_id,),
        ).fetchall()
        for (old_id,) in contra:
            edges.append(Edge(
                source=old_id, source_layer="semantic",
                target=node_id, target_layer="semantic",
                edge_type="contradiction", weight=1.0, directed=True,
            ))
        own_contra = self._storage.conn.execute(
            "SELECT contradicted_by FROM semantics WHERE id = ? AND contradicted_by IS NOT NULL",
            (node_id,),
        ).fetchall()
        for (new_id,) in own_contra:
            edges.append(Edge(
                source=node_id, source_layer="semantic",
                target=new_id, target_layer="semantic",
                edge_type="contradiction", weight=1.0, directed=True,
            ))

        return edges

    def _detect_layer(self, memory_id: str) -> str | None:
        if self._storage.get_episode(memory_id) is not None:
            return "episode"
        if self._storage.get_semantic(memory_id) is not None:
            return "semantic"
        if self._storage.get_instinct(memory_id) is not None:
            return "instinct"
        return None
