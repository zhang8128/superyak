"""Unified memory graph — virtual view over engram's relationship types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage import Storage

from storage import vec0_distance_to_similarity

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

    _LAYER_COLORS = {
        "episode": "#4A90D9",
        "semantic": "#7BC67E",
        "instinct": "#D94A4A",
        "entity": "#AAAAAA",
    }

    _EDGE_STYLES = {
        "provenance": "solid",
        "resonance": "dashed",
        "co_firing": "dotted",
        "entity_link": "dotted",
        "contradiction": "bold",
        "suggested": "dashed",
    }

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

    def _make_node(self, memory_id: str, layer: str) -> Node:
        content = self._storage._get_memory_content(memory_id, layer)
        preview = (content or "")[:100]
        return Node(id=memory_id, layer=layer, preview=preview)

    def neighborhood(self, node_id: str, depth: int = 1) -> tuple[list[Node], list[Edge]]:
        """BFS to given depth. Returns (nodes, edges) in the subgraph."""
        start_layer = self._detect_layer(node_id)
        if start_layer is None:
            return [], []

        visited_nodes: dict[str, Node] = {node_id: self._make_node(node_id, start_layer)}
        all_edges: list[Edge] = []
        frontier = {node_id}

        for _ in range(depth):
            next_frontier: set[str] = set()
            for nid in frontier:
                edges = self.neighbors(nid)
                for edge in edges:
                    all_edges.append(edge)
                    peer = edge.target if edge.source == nid else edge.source
                    peer_layer = edge.target_layer if edge.source == nid else edge.source_layer
                    if peer not in visited_nodes:
                        visited_nodes[peer] = self._make_node(peer, peer_layer)
                        next_frontier.add(peer)
            frontier = next_frontier

        return list(visited_nodes.values()), all_edges

    def _all_node_ids(self) -> list[tuple[str, str]]:
        """Return (id, layer) for every memory in storage."""
        nodes = []
        for row in self._storage.conn.execute("SELECT id FROM episodes").fetchall():
            nodes.append((row[0], "episode"))
        for row in self._storage.conn.execute("SELECT id FROM semantics WHERE contradicted_by IS NULL").fetchall():
            nodes.append((row[0], "semantic"))
        for row in self._storage.conn.execute("SELECT id FROM instincts").fetchall():
            nodes.append((row[0], "instinct"))
        return nodes

    def _build_adjacency(self) -> dict[str, set[str]]:
        """Build full adjacency dict from all edges."""
        all_nodes = self._all_node_ids()
        adj: dict[str, set[str]] = {nid: set() for nid, _ in all_nodes}

        for nid, _ in all_nodes:
            for edge in self.neighbors(nid):
                peer = edge.target if edge.source == nid else edge.source
                if peer in adj:
                    adj[nid].add(peer)
                    if not edge.directed:
                        adj[peer].add(nid)
                    else:
                        adj.setdefault(peer, set())
        return adj

    def _connected_components(self, adj: dict[str, set[str]]) -> list[set[str]]:
        """Find connected components via BFS (undirected — ignores edge direction)."""
        visited: set[str] = set()
        components: list[set[str]] = []
        for node in adj:
            if node in visited:
                continue
            component: set[str] = set()
            queue = [node]
            while queue:
                current = queue.pop()
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                for neighbor in adj.get(current, set()):
                    if neighbor not in visited:
                        queue.append(neighbor)
                # Also check reverse direction for directed edges
                for other, peers in adj.items():
                    if current in peers and other not in visited:
                        queue.append(other)
            components.append(component)
        return components

    def stats(self) -> dict:
        """Connectivity summary: nodes, edges by type, components, isolated."""
        all_nodes = self._all_node_ids()
        if not all_nodes:
            return {
                "total_nodes": 0, "total_edges": 0,
                "edges_by_type": {}, "components": 0,
                "isolated_nodes": 0, "largest_component": 0,
            }

        adj = self._build_adjacency()
        edge_counts: dict[str, int] = {}
        total_edges = 0
        for nid, _ in all_nodes:
            for edge in self.neighbors(nid):
                edge_counts[edge.edge_type] = edge_counts.get(edge.edge_type, 0) + 1
                total_edges += 1
        # Undirected edges counted twice (once from each side)
        for etype in edge_counts:
            if etype in ("resonance", "co_firing"):
                edge_counts[etype] //= 2
        total_edges = sum(edge_counts.values())

        components = self._connected_components(adj)
        isolated = sum(1 for c in components if len(c) == 1)
        largest = max(len(c) for c in components) if components else 0

        return {
            "total_nodes": len(all_nodes),
            "total_edges": total_edges,
            "edges_by_type": edge_counts,
            "components": len(components),
            "isolated_nodes": isolated,
            "largest_component": largest,
        }

    def analyze(self) -> dict:
        """Extended analysis: hubs, average degree, layer distribution."""
        all_nodes = self._all_node_ids()
        if not all_nodes:
            return {"hubs": [], "avg_degree": 0.0, "layer_distribution": {}}

        degrees: dict[str, int] = {}
        for nid, _ in all_nodes:
            edges = self.neighbors(nid)
            degrees[nid] = len(edges)

        sorted_by_degree = sorted(degrees.items(), key=lambda x: x[1], reverse=True)
        hubs = [{"id": nid, "degree": deg} for nid, deg in sorted_by_degree[:10] if deg > 0]

        avg_degree = sum(degrees.values()) / len(degrees) if degrees else 0.0

        layer_dist: dict[str, int] = {}
        for _, layer in all_nodes:
            layer_dist[layer] = layer_dist.get(layer, 0) + 1

        return {
            "hubs": hubs,
            "avg_degree": round(avg_degree, 2),
            "layer_distribution": layer_dist,
        }

    def to_dot(self, center: str | None = None, depth: int = 1) -> str:
        """Graphviz DOT export."""
        if center:
            nodes, edges = self.neighborhood(center, depth)
        else:
            all_node_ids = self._all_node_ids()
            nodes = [self._make_node(nid, layer) for nid, layer in all_node_ids]
            edges = []
            for nid, _ in all_node_ids:
                edges.extend(self.neighbors(nid))

        seen_edges: set[tuple[str, str, str]] = set()
        lines = ["digraph memory {", '  rankdir=LR;', '  node [shape=box, style=filled];']

        for node in nodes:
            color = self._LAYER_COLORS.get(node.layer, "#FFFFFF")
            label = f"{node.layer}\\n{node.id[:8]}\\n{node.preview[:40]}"
            lines.append(f'  "{node.id[:8]}" [label="{label}", fillcolor="{color}"];')

        for edge in edges:
            key = (edge.source, edge.target, edge.edge_type)
            rev_key = (edge.target, edge.source, edge.edge_type)
            if key in seen_edges or (not edge.directed and rev_key in seen_edges):
                continue
            seen_edges.add(key)
            style = self._EDGE_STYLES.get(edge.edge_type, "solid")
            arrow = "forward" if edge.directed else "none"
            lines.append(
                f'  "{edge.source[:8]}" -> "{edge.target[:8]}" '
                f'[style={style}, dir={arrow}, label="{edge.edge_type}"];'
            )

        lines.append("}")
        return "\n".join(lines)

    def to_json(self, center: str | None = None, depth: int = 1) -> dict:
        """JSON export for browser rendering."""
        if center:
            nodes, edges = self.neighborhood(center, depth)
        else:
            all_node_ids = self._all_node_ids()
            nodes = [self._make_node(nid, layer) for nid, layer in all_node_ids]
            edges = []
            for nid, _ in all_node_ids:
                edges.extend(self.neighbors(nid))

        seen_edges: set[tuple[str, str, str]] = set()
        unique_edges = []
        for edge in edges:
            key = (edge.source, edge.target, edge.edge_type)
            rev_key = (edge.target, edge.source, edge.edge_type)
            if key in seen_edges or (not edge.directed and rev_key in seen_edges):
                continue
            seen_edges.add(key)
            unique_edges.append(edge)

        return {
            "nodes": [
                {"id": n.id, "layer": n.layer, "preview": n.preview}
                for n in nodes
            ],
            "edges": [
                {
                    "source": e.source, "target": e.target,
                    "edge_type": e.edge_type, "weight": e.weight,
                    "directed": e.directed,
                }
                for e in unique_edges
            ],
        }

    def suggest_edges(self, node_id: str, k: int = 5, threshold: float = 0.7) -> list[Edge]:
        """Find embedding-proximity neighbors not already connected.

        Returns Edge objects with edge_type="suggested". These are proposals,
        not structural relationships.
        """
        node_layer = self._detect_layer(node_id)
        if node_layer is None:
            return []

        vec_table = {"episode": "episode", "semantic": "semantic", "instinct": "instinct"}.get(node_layer)
        if vec_table is None:
            return []

        node_vec = self._storage.get_vector(node_layer, node_id)
        if node_vec is None:
            return []

        existing_neighbors = {e.target for e in self.neighbors(node_id)}
        existing_neighbors.add(node_id)

        candidates: list[Edge] = []
        for search_layer in ("episode", "semantic", "instinct"):
            try:
                results = self._storage.search_vectors(search_layer, node_vec, k=k * 2)
                for rid, distance in results:
                    if rid in existing_neighbors:
                        continue
                    sim = vec0_distance_to_similarity(distance)
                    if sim >= threshold:
                        candidates.append(Edge(
                            source=node_id, source_layer=node_layer,
                            target=rid, target_layer=search_layer,
                            edge_type="suggested", weight=sim, directed=False,
                        ))
            except Exception:
                logger.debug("suggest_edges: %s vector search failed", search_layer)

        candidates.sort(key=lambda e: e.weight, reverse=True)
        return candidates[:k]
