"""Unified memory graph — virtual view over engram's relationship types."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage import Storage

from storage import vec0_distance_to_similarity

logger = logging.getLogger("engram.graph")


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

    def __init__(self, storage: Storage):
        self._storage = storage

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
        if rows:
            source_layer = self._detect_layer(node_id)
            for row in rows:
                if row[0] == node_id:
                    peer_id, peer_layer = row[2], row[3]
                else:
                    peer_id, peer_layer = row[0], row[1]
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
            global_max = self._storage.conn.execute(
                "SELECT MAX(co_fire_count) FROM instinct_co_firing"
            ).fetchone()[0] or 1
            for row in cofire_rows:
                peer = row[1] if row[0] == node_id else row[0]
                edges.append(Edge(
                    source=node_id, source_layer="instinct",
                    target=peer, target_layer="instinct",
                    edge_type="co_firing",
                    weight=row[2] / global_max,
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
        content = self._storage.get_memory_content(memory_id, layer)
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
        dead: set[str] = set()

        for _ in range(depth):
            next_frontier: set[str] = set()
            for nid in frontier:
                edges = self.neighbors(nid)
                for edge in edges:
                    peer = edge.target if edge.source == nid else edge.source
                    peer_layer = edge.target_layer if edge.source == nid else edge.source_layer
                    if peer in dead:
                        continue
                    if peer not in visited_nodes and self._detect_layer(peer) is None:
                        dead.add(peer)
                        continue
                    all_edges.append(edge)
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
        for row in self._storage.conn.execute("SELECT id FROM semantics").fetchall():
            nodes.append((row[0], "semantic"))
        for row in self._storage.conn.execute("SELECT id FROM instincts").fetchall():
            nodes.append((row[0], "instinct"))
        return nodes

    def _build_adjacency(self) -> tuple[dict[str, set[str]], dict[str, list[Edge]]]:
        """Build symmetric adjacency dict and per-node edge lists.

        Adjacency is always undirected (for component analysis).
        Edge lists are preserved for stats/analysis reuse.
        """
        all_nodes = self._all_node_ids()
        adj: dict[str, set[str]] = {nid: set() for nid, _ in all_nodes}
        edge_map: dict[str, list[Edge]] = {}

        for nid, _ in all_nodes:
            edges = self.neighbors(nid)
            edge_map[nid] = edges
            for edge in edges:
                peer = edge.target if edge.source == nid else edge.source
                if peer in adj:
                    adj[nid].add(peer)
                    adj[peer].add(nid)
        return adj, edge_map

    def _connected_components(self, adj: dict[str, set[str]]) -> list[set[str]]:
        """Find connected components via BFS (undirected)."""
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
                for neighbor in adj[current]:
                    if neighbor not in visited:
                        queue.append(neighbor)
            components.append(component)
        return components

    def _full_scan(self) -> tuple[list[tuple[str, str]], dict[str, set[str]], dict[str, list[Edge]]]:
        """Single traversal that stats() and analyze() both use."""
        all_nodes = self._all_node_ids()
        if not all_nodes:
            return all_nodes, {}, {}
        adj, edge_map = self._build_adjacency()
        return all_nodes, adj, edge_map

    def stats(self) -> dict:
        """Connectivity summary: nodes, edges by type, components, isolated."""
        all_nodes, adj, edge_map = self._full_scan()
        if not all_nodes:
            return {
                "total_nodes": 0, "total_edges": 0,
                "edges_by_type": {}, "components": 0,
                "isolated_nodes": 0, "largest_component": 0,
            }

        edge_counts: dict[str, int] = {}
        for nid, edges in edge_map.items():
            for edge in edges:
                edge_counts[edge.edge_type] = edge_counts.get(edge.edge_type, 0) + 1
        for etype in edge_counts:
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
        all_nodes, adj, edge_map = self._full_scan()
        if not all_nodes:
            return {"hubs": [], "avg_degree": 0.0, "layer_distribution": {}}

        degrees = {nid: len(edges) for nid, edges in edge_map.items()}

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

    def _collect_graph(self, center: str | None, depth: int) -> tuple[list[Node], list[Edge]]:
        """Collect nodes and deduplicated edges for export."""
        if center:
            nodes, edges = self.neighborhood(center, depth)
        else:
            all_node_ids = self._all_node_ids()
            node_id_set = {nid for nid, _ in all_node_ids}
            nodes = [self._make_node(nid, layer) for nid, layer in all_node_ids]
            edges = []
            for nid, _ in all_node_ids:
                for edge in self.neighbors(nid):
                    peer = edge.target if edge.source == nid else edge.source
                    if peer in node_id_set:
                        edges.append(edge)

        seen: set[tuple[str, str, str]] = set()
        unique_edges = []
        for edge in edges:
            key = (edge.source, edge.target, edge.edge_type)
            rev_key = (edge.target, edge.source, edge.edge_type)
            if key in seen or (not edge.directed and rev_key in seen):
                continue
            seen.add(key)
            unique_edges.append(edge)

        return nodes, unique_edges

    def to_dot(self, center: str | None = None, depth: int = 1) -> str:
        """Graphviz DOT export."""
        nodes, edges = self._collect_graph(center, depth)

        lines = ["digraph memory {", '  rankdir=LR;', '  node [shape=box, style=filled];']

        for node in nodes:
            color = self._LAYER_COLORS.get(node.layer, "#FFFFFF")
            safe_preview = node.preview[:40].replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            label = f"{node.layer}\\n{node.id[:8]}\\n{safe_preview}"
            lines.append(f'  "{node.id[:8]}" [label="{label}", fillcolor="{color}"];')

        for edge in edges:
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
        nodes, edges = self._collect_graph(center, depth)

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
                for e in edges
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

        node_vec = self._storage.get_vector(node_layer, node_id)
        if node_vec is None:
            return []

        node_edges = self.neighbors(node_id)
        existing_neighbors = set()
        for e in node_edges:
            existing_neighbors.add(e.target)
            existing_neighbors.add(e.source)
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

    def log_suggestion(self, source_id: str, target_id: str, similarity: float) -> None:
        """Persist a proximity suggestion to memory_log for multi-session tracking."""
        import uuid as _uuid
        canonical = sorted([source_id, target_id])
        self._storage.add_log_entry(
            id=str(_uuid.uuid4()),
            event_type="proximity_suggestion",
            layer="graph",
            target_ids=canonical,
            context={"similarity": similarity},
        )

    def promote_suggestions(self, min_prior_sessions: int = 2) -> int:
        """Promote proximity suggestions to resonances during sleep.

        A suggestion is promoted if:
        1. It has appeared in >= min_prior_sessions prior log entries, AND
        2. The two nodes share at least one neighbor (coherence check)

        Returns count of promotions.
        """
        import json as _json
        import random

        rows = self._storage.get_log_entries(
            event_type="proximity_suggestion", limit=1000
        )

        pair_counts: dict[tuple[str, str], int] = {}
        for row in rows:
            tids = _json.loads(row["target_ids"]) if isinstance(row["target_ids"], str) else row["target_ids"]
            if len(tids) != 2:
                continue
            pair = (tids[0], tids[1])
            pair_counts[pair] = pair_counts.get(pair, 0) + 1

        promoted = 0
        for (id_a, id_b), count in pair_counts.items():
            if count < min_prior_sessions:
                continue

            existing = self._storage.conn.execute(
                "SELECT 1 FROM resonances WHERE "
                "(memory_a = ? AND memory_b = ?) OR (memory_a = ? AND memory_b = ?)",
                (id_a, id_b, id_b, id_a),
            ).fetchone()
            if existing:
                continue

            layer_a = self._detect_layer(id_a)
            layer_b = self._detect_layer(id_b)
            if layer_a is None or layer_b is None:
                continue

            neighbors_a = {e.target for e in self.neighbors(id_a)}
            neighbors_b = {e.target for e in self.neighbors(id_b)}
            shared = neighbors_a & neighbors_b
            if not shared:
                continue

            self._storage.add_resonance(
                id_a=id_a, layer_a=layer_a,
                id_b=id_b, layer_b=layer_b,
                similarity=0.0,
                weight=max(0.1, min(0.9, random.gauss(0.3, 0.1))),
            )
            promoted += 1

        if promoted:
            logger.info("Promoted %d proximity suggestions to resonances", promoted)
        return promoted
