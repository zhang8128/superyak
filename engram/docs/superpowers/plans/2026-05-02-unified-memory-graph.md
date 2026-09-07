# Unified Memory Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a virtual unified graph layer over engram's six existing relationship types, with topology analysis and embedding proximity suggestions promoted during sleep.

**Architecture:** New `graph.py` module wraps `Storage` and `KnowledgeGraph`, presenting all edge types through a single `MemoryGraph` class. No new tables or migrations — edges read from existing tables, proximity suggestions persisted as `memory_log` entries. Sleep consolidation in `server.py:_init()` gains a proximity promotion phase.

**Tech Stack:** Python, SQLite (existing), numpy (existing), scipy (existing for clustering)

---

### Task 1: Edge and Node dataclasses

**Files:**
- Create: `graph.py`
- Test: `tests/test_graph.py`

- [ ] **Step 1: Write failing test for Edge and Node**

```python
# tests/test_graph.py
"""Tests for unified memory graph."""

from graph import Edge, Node


class TestDataclasses:
    def test_edge_creation(self):
        e = Edge(
            source="ep-001", source_layer="episode",
            target="sem-001", target_layer="semantic",
            edge_type="provenance", weight=0.8, directed=True,
        )
        assert e.source == "ep-001"
        assert e.edge_type == "provenance"
        assert e.directed is True

    def test_node_creation(self):
        n = Node(id="ep-001", layer="episode", preview="First 100 chars...")
        assert n.id == "ep-001"
        assert n.layer == "episode"

    def test_edge_weight_clamped(self):
        e = Edge(
            source="a", source_layer="episode",
            target="b", target_layer="episode",
            edge_type="resonance", weight=1.5, directed=False,
        )
        assert e.weight == 1.0

    def test_edge_weight_floor(self):
        e = Edge(
            source="a", source_layer="episode",
            target="b", target_layer="episode",
            edge_type="resonance", weight=-0.5, directed=False,
        )
        assert e.weight == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestDataclasses -v`
Expected: FAIL — `graph` module not found

- [ ] **Step 3: Implement dataclasses**

```python
# graph.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestDataclasses -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add graph.py tests/test_graph.py
git commit -m "feat(graph): add Edge and Node dataclasses for unified memory graph"
```

---

### Task 2: MemoryGraph edge loading from storage

**Files:**
- Modify: `graph.py`
- Test: `tests/test_graph.py`

- [ ] **Step 1: Write failing test for edge loading**

```python
# tests/test_graph.py — add to file

import uuid
from conftest import MIGRATIONS_DIR
from storage import Storage
from graph import MemoryGraph, Edge, Node


def _make_storage(tmp_path):
    """Create a storage with known edges for testing."""
    db_path = str(tmp_path / "test_graph.db")
    store = Storage(db_path, migrations_dir=MIGRATIONS_DIR)
    return store


def _fake_emb(dim=768):
    import random
    return [random.uniform(-1, 1) for _ in range(dim)]


class TestEdgeLoading:
    def test_provenance_episode_to_semantic(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, "test episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "test semantic", kind="fact",
                          source_episode_ids=[ep_id], embedding=_fake_emb())

        g = MemoryGraph(store)
        edges = g.neighbors(ep_id)
        prov = [e for e in edges if e.edge_type == "provenance"]
        assert len(prov) == 1
        assert prov[0].target == sem_id
        assert prov[0].directed is True
        store.close()

    def test_provenance_semantic_to_episode(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, "test episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "test semantic", kind="fact",
                          source_episode_ids=[ep_id], embedding=_fake_emb())

        g = MemoryGraph(store)
        edges = g.neighbors(sem_id)
        prov = [e for e in edges if e.edge_type == "provenance"]
        assert len(prov) == 1
        assert prov[0].target == ep_id
        assert prov[0].directed is True
        store.close()

    def test_resonance_edges(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_a = str(uuid.uuid4())
        ep_b = str(uuid.uuid4())
        store.add_episode(ep_a, "episode alpha", embedding=_fake_emb())
        store.add_episode(ep_b, "episode beta", embedding=_fake_emb())
        store.add_resonance(str(uuid.uuid4()), ep_a, "episode", ep_b, "episode",
                           similarity=0.8, weight=0.6, strength=0.5)

        g = MemoryGraph(store)
        edges = g.neighbors(ep_a)
        res = [e for e in edges if e.edge_type == "resonance"]
        assert len(res) == 1
        assert res[0].target == ep_b
        assert res[0].directed is False

        edges_b = g.neighbors(ep_b)
        res_b = [e for e in edges_b if e.edge_type == "resonance"]
        assert len(res_b) == 1
        assert res_b[0].target == ep_a
        store.close()

    def test_no_edges_for_isolated_node(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        store.add_episode(ep_id, "lonely episode", embedding=_fake_emb())

        g = MemoryGraph(store)
        edges = g.neighbors(ep_id)
        assert edges == []
        store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestEdgeLoading -v`
Expected: FAIL — `MemoryGraph` not found

- [ ] **Step 3: Implement MemoryGraph with neighbors()**

```python
# graph.py — add after dataclasses

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestEdgeLoading -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add graph.py tests/test_graph.py
git commit -m "feat(graph): MemoryGraph with neighbors() loading all edge types"
```

---

### Task 3: Neighborhood BFS traversal

**Files:**
- Modify: `graph.py`
- Test: `tests/test_graph.py`

- [ ] **Step 1: Write failing test for neighborhood()**

```python
# tests/test_graph.py — add to file

class TestNeighborhood:
    def test_depth_one_returns_immediate(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, "test episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "test semantic", kind="fact",
                          source_episode_ids=[ep_id], embedding=_fake_emb())

        g = MemoryGraph(store)
        nodes, edges = g.neighborhood(ep_id, depth=1)
        node_ids = {n.id for n in nodes}
        assert ep_id in node_ids
        assert sem_id in node_ids
        assert len(edges) >= 1
        store.close()

    def test_depth_two_reaches_transitive(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        ins_id = str(uuid.uuid4())
        store.add_episode(ep_id, "test episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "test semantic", kind="preference",
                          source_episode_ids=[ep_id], embedding=_fake_emb(),
                          confidence=0.8)
        store.add_instinct(ins_id, "test instinct", trigger="preference",
                          source_semantic_ids=[sem_id], embedding=_fake_emb(),
                          notice="when testing", implication="test well")

        g = MemoryGraph(store)
        nodes, edges = g.neighborhood(ep_id, depth=2)
        node_ids = {n.id for n in nodes}
        assert ep_id in node_ids
        assert sem_id in node_ids
        assert ins_id in node_ids
        store.close()

    def test_depth_zero_returns_only_center(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        store.add_episode(ep_id, "solo", embedding=_fake_emb())

        g = MemoryGraph(store)
        nodes, edges = g.neighborhood(ep_id, depth=0)
        assert len(nodes) == 1
        assert nodes[0].id == ep_id
        assert edges == []
        store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestNeighborhood -v`
Expected: FAIL — `neighborhood` not found

- [ ] **Step 3: Implement neighborhood()**

```python
# graph.py — add to MemoryGraph class

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestNeighborhood -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add graph.py tests/test_graph.py
git commit -m "feat(graph): BFS neighborhood traversal"
```

---

### Task 4: Graph stats and analysis

**Files:**
- Modify: `graph.py`
- Test: `tests/test_graph.py`

- [ ] **Step 1: Write failing test for stats()**

```python
# tests/test_graph.py — add to file

class TestStats:
    def test_stats_empty_db(self, tmp_path):
        store = _make_storage(tmp_path)
        g = MemoryGraph(store)
        s = g.stats()
        assert s["total_nodes"] == 0
        assert s["total_edges"] == 0
        assert s["components"] == 0
        assert s["isolated_nodes"] == 0
        store.close()

    def test_stats_counts_nodes_and_edges(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, "episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "semantic", kind="fact",
                          source_episode_ids=[ep_id], embedding=_fake_emb())

        g = MemoryGraph(store)
        s = g.stats()
        assert s["total_nodes"] == 2
        assert s["total_edges"] >= 1
        assert s["components"] == 1
        assert s["isolated_nodes"] == 0
        store.close()

    def test_stats_detects_isolated(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_a = str(uuid.uuid4())
        ep_b = str(uuid.uuid4())
        store.add_episode(ep_a, "episode a", embedding=_fake_emb())
        store.add_episode(ep_b, "episode b", embedding=_fake_emb())

        g = MemoryGraph(store)
        s = g.stats()
        assert s["total_nodes"] == 2
        assert s["isolated_nodes"] == 2
        assert s["components"] == 2
        store.close()


class TestAnalyze:
    def test_analyze_returns_hubs(self, tmp_path):
        store = _make_storage(tmp_path)
        sem_id = str(uuid.uuid4())
        ep_ids = []
        for i in range(5):
            ep_id = str(uuid.uuid4())
            store.add_episode(ep_id, f"episode {i}", embedding=_fake_emb())
            ep_ids.append(ep_id)
        store.add_semantic(sem_id, "hub semantic", kind="fact",
                          source_episode_ids=ep_ids, embedding=_fake_emb())

        g = MemoryGraph(store)
        a = g.analyze()
        assert len(a["hubs"]) > 0
        assert a["hubs"][0]["id"] == sem_id
        assert a["hubs"][0]["degree"] == 5
        store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestStats -v && .venv/bin/python -m pytest tests/test_graph.py::TestAnalyze -v`
Expected: FAIL — `stats` and `analyze` not found

- [ ] **Step 3: Implement stats() and analyze()**

```python
# graph.py — add to MemoryGraph class

    def _all_node_ids(self) -> list[tuple[str, str]]:
        """Return (id, layer) for every memory in storage."""
        nodes = []
        for row in self._storage.conn.execute("SELECT id FROM episodes").fetchall():
            nodes.append((row[0], "episode"))
        for row in self._storage.conn.execute("SELECT id FROM semantics WHERE contradicted_by IS NULL").fetchall():
            nodes.append((row[0], "semantic"))
        for row in self._storage.conn.execute("SELECT id FROM instincts WHERE retired = 0").fetchall():
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestStats tests/test_graph.py::TestAnalyze -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add graph.py tests/test_graph.py
git commit -m "feat(graph): stats() and analyze() for topology diagnostics"
```

---

### Task 5: DOT and JSON export

**Files:**
- Modify: `graph.py`
- Test: `tests/test_graph.py`

- [ ] **Step 1: Write failing test for exports**

```python
# tests/test_graph.py — add to file

class TestExport:
    def test_to_dot_produces_valid_output(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, "test episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "test semantic", kind="fact",
                          source_episode_ids=[ep_id], embedding=_fake_emb())

        g = MemoryGraph(store)
        dot = g.to_dot(center=ep_id, depth=1)
        assert "digraph" in dot
        assert ep_id[:8] in dot
        assert sem_id[:8] in dot
        store.close()

    def test_to_json_structure(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, "test episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "test semantic", kind="fact",
                          source_episode_ids=[ep_id], embedding=_fake_emb())

        g = MemoryGraph(store)
        j = g.to_json(center=ep_id, depth=1)
        assert "nodes" in j
        assert "edges" in j
        assert len(j["nodes"]) == 2
        store.close()

    def test_to_dot_global_without_center(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        store.add_episode(ep_id, "solo", embedding=_fake_emb())

        g = MemoryGraph(store)
        dot = g.to_dot()
        assert "digraph" in dot
        store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestExport -v`
Expected: FAIL — `to_dot` not found

- [ ] **Step 3: Implement to_dot() and to_json()**

```python
# graph.py — add to MemoryGraph class

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestExport -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add graph.py tests/test_graph.py
git commit -m "feat(graph): DOT and JSON export for visualization"
```

---

### Task 6: Embedding proximity suggestions

**Files:**
- Modify: `graph.py`
- Test: `tests/test_graph.py`

- [ ] **Step 1: Write failing test for suggest_edges()**

```python
# tests/test_graph.py — add to file

import numpy as np


class TestSuggestEdges:
    def test_suggests_nearby_unconnected(self, tmp_path):
        store = _make_storage(tmp_path)
        base_emb = [0.0] * 768
        base_emb[0] = 1.0
        near_emb = [0.0] * 768
        near_emb[0] = 0.99
        near_emb[1] = 0.01
        far_emb = [0.0] * 768
        far_emb[100] = 1.0

        ep_a = str(uuid.uuid4())
        ep_b = str(uuid.uuid4())
        ep_c = str(uuid.uuid4())
        store.add_episode(ep_a, "base episode", embedding=base_emb)
        store.add_episode(ep_b, "near episode", embedding=near_emb)
        store.add_episode(ep_c, "far episode", embedding=far_emb)

        g = MemoryGraph(store)
        suggestions = g.suggest_edges(ep_a, k=5, threshold=0.5)
        suggested_targets = {e.target for e in suggestions}
        assert ep_b in suggested_targets
        assert all(e.edge_type == "suggested" for e in suggestions)
        store.close()

    def test_excludes_already_connected(self, tmp_path):
        store = _make_storage(tmp_path)
        emb = [0.0] * 768
        emb[0] = 1.0
        ep_a = str(uuid.uuid4())
        sem_a = str(uuid.uuid4())
        store.add_episode(ep_a, "connected episode", embedding=emb)
        store.add_semantic(sem_a, "connected semantic", kind="fact",
                          source_episode_ids=[ep_a], embedding=emb)

        g = MemoryGraph(store)
        suggestions = g.suggest_edges(ep_a, k=5, threshold=0.0)
        suggested_targets = {e.target for e in suggestions}
        assert sem_a not in suggested_targets
        store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestSuggestEdges -v`
Expected: FAIL — `suggest_edges` not found

- [ ] **Step 3: Implement suggest_edges()**

```python
# graph.py — add to MemoryGraph class

    from storage import vec0_distance_to_similarity as _v2s

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestSuggestEdges -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add graph.py tests/test_graph.py
git commit -m "feat(graph): embedding proximity suggestions"
```

---

### Task 7: Sleep integration — promote suggestions to resonances

**Files:**
- Modify: `graph.py` (add `promote_suggestions` method)
- Modify: `server.py` (add promotion phase to `_init()`)
- Test: `tests/test_graph.py`

- [ ] **Step 1: Write failing test for promotion logic**

```python
# tests/test_graph.py — add to file

class TestSleepPromotion:
    def test_promote_skips_without_prior_suggestions(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_a = str(uuid.uuid4())
        ep_b = str(uuid.uuid4())
        emb = [0.0] * 768
        emb[0] = 1.0
        store.add_episode(ep_a, "alpha", embedding=emb)
        store.add_episode(ep_b, "beta", embedding=emb)

        g = MemoryGraph(store)
        promoted = g.promote_suggestions(min_prior_sessions=2)
        assert promoted == 0
        store.close()

    def test_promote_with_shared_neighbor(self, tmp_path):
        store = _make_storage(tmp_path)
        emb = [0.0] * 768
        emb[0] = 1.0
        ep_a = str(uuid.uuid4())
        ep_b = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_a, "alpha", embedding=emb)
        store.add_episode(ep_b, "beta", embedding=emb)
        store.add_semantic(sem_id, "shared", kind="fact",
                          source_episode_ids=[ep_a, ep_b], embedding=emb)

        # Log suggestions from 2 prior sessions
        for _ in range(2):
            store.add_log_entry(
                id=str(uuid.uuid4()), event_type="proximity_suggestion",
                layer="episode", target_ids=[ep_a, ep_b],
                context={"similarity": 0.85},
            )

        g = MemoryGraph(store)
        promoted = g.promote_suggestions(min_prior_sessions=2)
        assert promoted >= 1

        # Verify resonance was created
        edges = g.neighbors(ep_a)
        res = [e for e in edges if e.edge_type == "resonance" and e.target == ep_b]
        assert len(res) == 1
        store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestSleepPromotion -v`
Expected: FAIL — `promote_suggestions` not found

- [ ] **Step 3: Implement promote_suggestions()**

```python
# graph.py — add to MemoryGraph class

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
        import uuid as _uuid

        rows = self._storage.get_log_entries(
            event_type="proximity_suggestion", limit=1000
        )

        pair_counts: dict[tuple[str, str], float] = {}
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

            neighbors_a = {e.target for e in self.neighbors(id_a)}
            neighbors_b = {e.target for e in self.neighbors(id_b)}
            shared = neighbors_a & neighbors_b
            if not shared:
                continue

            layer_a = self._detect_layer(id_a) or "episode"
            layer_b = self._detect_layer(id_b) or "episode"
            canonical_a, canonical_b = (id_a, id_b) if id_a < id_b else (id_b, id_a)
            layer_ca = layer_a if canonical_a == id_a else layer_b
            layer_cb = layer_b if canonical_b == id_b else layer_a

            self._storage.add_resonance(
                id=str(_uuid.uuid4()),
                memory_a=canonical_a, layer_a=layer_ca,
                memory_b=canonical_b, layer_b=layer_cb,
                similarity=0.0,
                weight=max(0.1, min(0.9, random.gauss(0.3, 0.1))),
                strength=0.3,
            )
            promoted += 1

        if promoted:
            logger.info("Promoted %d proximity suggestions to resonances", promoted)
        return promoted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestSleepPromotion -v`
Expected: PASS

- [ ] **Step 5: Wire into server.py _init() consolidation**

Add after the instinct backfill (around line 378, after `_backfill_instinct_perceptual`):

```python
# server.py — inside _init(), add to the sleep-time maintenance try block

        # 7. Promote proximity suggestions to resonances (graph consolidation)
        try:
            from graph import MemoryGraph
            _memory_graph = MemoryGraph(_storage, _knowledge_graph)
            promoted = _memory_graph.promote_suggestions(min_prior_sessions=2)
            if promoted:
                logger.info("Sleep: promoted %d proximity suggestions", promoted)
        except Exception:
            logger.debug("Graph promotion skipped", exc_info=True)
```

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest tests/test_graph.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add graph.py server.py tests/test_graph.py
git commit -m "feat(graph): sleep-time promotion of proximity suggestions to resonances"
```

---

### Task 8: graph_view MCP tool

**Files:**
- Modify: `server.py`
- Test: `tests/test_graph.py`

- [ ] **Step 1: Write failing test for graph_view tool**

```python
# tests/test_graph.py — add to file

class TestGraphViewTool:
    def test_global_stats(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        store.add_episode(ep_id, "test", embedding=_fake_emb())

        g = MemoryGraph(store)
        result = g.stats()
        assert "total_nodes" in result
        assert result["total_nodes"] == 1
        store.close()

    def test_neighborhood_view(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, "test episode", embedding=_fake_emb())
        store.add_semantic(sem_id, "test semantic", kind="fact",
                          source_episode_ids=[ep_id], embedding=_fake_emb())

        g = MemoryGraph(store)
        j = g.to_json(center=ep_id, depth=1)
        assert len(j["nodes"]) == 2
        assert len(j["edges"]) >= 1
        store.close()
```

- [ ] **Step 2: Run test to verify it passes** (these use already-implemented methods)

Run: `.venv/bin/python -m pytest tests/test_graph.py::TestGraphViewTool -v`
Expected: PASS

- [ ] **Step 3: Add graph_view MCP tool to server.py**

Add near the end of server.py, after the `wander` tool:

```python
# server.py — add after wander tool

@mcp.tool()
def graph_view(center: str | None = None, depth: int = 1) -> dict:
    """View the unified memory graph topology.

    Without center: returns global stats and analysis.
    With center: returns neighborhood around that node to given depth,
    including suggested edges from embedding proximity.

    Args:
        center: Memory ID to center the view on. None for global stats.
        depth: BFS depth for neighborhood view (default 1).
    """
    _init()
    from graph import MemoryGraph
    g = MemoryGraph(_storage, _knowledge_graph)

    if center is None:
        stats = g.stats()
        analysis = g.analyze()
        return {"mode": "global", "stats": stats, "analysis": analysis}

    json_view = g.to_json(center=center, depth=depth)
    suggestions = g.suggest_edges(center, k=5, threshold=0.7)
    json_view["suggested_edges"] = [
        {"source": e.source, "target": e.target,
         "weight": e.weight, "target_layer": e.target_layer}
        for e in suggestions
    ]

    # Log suggestions for future sleep promotion
    for e in suggestions:
        g.log_suggestion(e.source, e.target, e.weight)

    return {"mode": "neighborhood", **json_view}
```

- [ ] **Step 4: Run full test suite to verify no regressions**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All existing tests still pass

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_graph.py
git commit -m "feat(graph): graph_view MCP tool for topology inspection"
```

---

### Task 9: Run against live data and observe

**Files:** None modified — diagnostic only

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All tests pass (existing + new)

- [ ] **Step 2: Run graph analysis against live database**

Create a one-shot script to inspect the real topology:

```python
# (run interactively, don't commit)
import sys
sys.path.insert(0, ".")
from storage import Storage
from graph import MemoryGraph

store = Storage(".engram/graph.db")
g = MemoryGraph(store)

print("=== STATS ===")
import json
print(json.dumps(g.stats(), indent=2))

print("\n=== ANALYSIS ===")
print(json.dumps(g.analyze(), indent=2))

store.close()
```

Run: `.venv/bin/python -c "$(cat <<'PYEOF'
import sys, json
sys.path.insert(0, ".")
from storage import Storage
from graph import MemoryGraph
store = Storage(".engram/graph.db")
g = MemoryGraph(store)
print("=== STATS ===")
print(json.dumps(g.stats(), indent=2))
print("\n=== ANALYSIS ===")
print(json.dumps(g.analyze(), indent=2))
store.close()
PYEOF
)"`

Expected: Output showing component counts, hub nodes, connectivity. This tells us whether the topology is rich enough for the next step (sheaf layer).

- [ ] **Step 3: Review output and decide next steps**

If the graph is mostly disconnected islands → we need richer edge formation before sheaves make sense.
If there's one large connected component → the topology is ready for resolution layers.
Share the results with the user.
