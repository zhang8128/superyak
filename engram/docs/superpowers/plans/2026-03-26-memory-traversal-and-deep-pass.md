# Memory Traversal & Between-Session Deep Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `wander()` tool for graph-walking memory traversal, and a between-session deep pass that runs unfired reading lenses during consolidation.

**Architecture:** `wander()` queries three connection axes (resonances, provenance, knowledge graph) and optionally auto-walks with density-adaptive stopping. Deep pass adds a step to wake.py that runs structural and gap-specific lenses against missed passages via Ollama, storing results as episodes.

**Tech Stack:** Python, SQLite (vec0), FastMCP, Ollama, existing engram Storage class

---

## File Structure

| File | Responsibility |
|------|----------------|
| `storage.py` | `get_neighbors()` — resonances + provenance queries |
| `knowledge.py` | `get_entity_neighbors()` — memories sharing entities |
| `server.py` | `wander()` tool, session visit tracking, auto-walk loop |
| `hooks/wake.py` | `deep_pass()` integration into consolidation |
| `deep_pass.py` | Deep pass logic — structural lenses, gap detection, Ollama calls |
| `tests/test_wander.py` | Wander tool tests |
| `tests/test_deep_pass.py` | Deep pass tests |

---

### Task 1: Storage — get_neighbors() for resonances and provenance

**Files:**
- Modify: `storage.py` (after `get_resonances_for` at ~line 1288)
- Test: `tests/test_wander.py` (create)

- [ ] **Step 1: Write failing tests for get_neighbors**

Create `tests/test_wander.py`:

```python
"""Tests for memory traversal (wander)."""

import uuid
import pytest
from storage import Storage


@pytest.fixture
def db(tmp_path):
    return Storage(str(tmp_path / "test.db"))


@pytest.fixture
def fake_embedding():
    import random
    def _make():
        return [random.random() for _ in range(768)]
    return _make


class TestGetNeighbors:
    """Test Storage.get_neighbors() — resonance + provenance axes."""

    def test_resonance_neighbors(self, db, fake_embedding):
        """Memories linked by resonances appear as neighbors."""
        emb_a, emb_b = fake_embedding(), fake_embedding()
        db.add_episode("ep-1", "sess-1", "first memory", embedding=emb_a)
        db.add_episode("ep-2", "sess-1", "second memory", embedding=emb_b)
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.8, weight=0.6)

        neighbors = db.get_neighbors("ep-1")
        resonance_ids = [n["id"] for n in neighbors if n["connection_type"] == "resonance"]
        assert "ep-2" in resonance_ids

    def test_resonance_neighbors_reverse(self, db, fake_embedding):
        """Resonances are bidirectional — canonical ordering doesn't matter for lookup."""
        emb_a, emb_b = fake_embedding(), fake_embedding()
        db.add_episode("aaa", "sess-1", "first", embedding=emb_a)
        db.add_episode("zzz", "sess-1", "second", embedding=emb_b)
        # Canonical ordering puts "aaa" as memory_a
        db.add_resonance("aaa", "episode", "zzz", "episode", similarity=0.8, weight=0.6)

        # Query from the "b" side
        neighbors = db.get_neighbors("zzz")
        resonance_ids = [n["id"] for n in neighbors if n["connection_type"] == "resonance"]
        assert "aaa" in resonance_ids

    def test_provenance_children(self, db, fake_embedding):
        """An episode's children (semantics built from it) appear as neighbors."""
        emb = fake_embedding()
        db.add_episode("ep-1", "sess-1", "raw experience", embedding=emb)
        db.add_semantic("sem-1", "distilled fact", "fact", 0.8, emb, source_episode_ids=["ep-1"])

        neighbors = db.get_neighbors("ep-1")
        prov = [n for n in neighbors if n["connection_type"] == "provenance"]
        assert any(n["id"] == "sem-1" for n in prov)

    def test_provenance_parents(self, db, fake_embedding):
        """A semantic's parents (source episodes) appear as neighbors."""
        emb = fake_embedding()
        db.add_episode("ep-1", "sess-1", "raw experience", embedding=emb)
        db.add_semantic("sem-1", "distilled fact", "fact", 0.8, emb, source_episode_ids=["ep-1"])

        neighbors = db.get_neighbors("sem-1")
        prov = [n for n in neighbors if n["connection_type"] == "provenance"]
        assert any(n["id"] == "ep-1" for n in prov)

    def test_instinct_provenance(self, db, fake_embedding):
        """An instinct's source semantics appear as neighbors."""
        emb = fake_embedding()
        db.add_episode("ep-1", "sess-1", "experience", embedding=emb)
        db.add_semantic("sem-1", "pattern", "fact", 0.8, emb, source_episode_ids=["ep-1"])
        db.add_instinct("ins-1", "trigger", "action", source_semantic_ids=["sem-1"],
                        embedding=emb, notice="notice this", implication="implies that")

        neighbors = db.get_neighbors("ins-1")
        prov = [n for n in neighbors if n["connection_type"] == "provenance"]
        assert any(n["id"] == "sem-1" for n in prov)

    def test_no_connections(self, db, fake_embedding):
        """Orphan memory returns empty list."""
        db.add_episode("ep-1", "sess-1", "alone", embedding=fake_embedding())
        neighbors = db.get_neighbors("ep-1")
        assert neighbors == []

    def test_neighbor_fields(self, db, fake_embedding):
        """Each neighbor has required fields."""
        emb_a, emb_b = fake_embedding(), fake_embedding()
        db.add_episode("ep-1", "sess-1", "first", embedding=emb_a)
        db.add_episode("ep-2", "sess-1", "second", embedding=emb_b)
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.85, weight=0.6)

        neighbors = db.get_neighbors("ep-1")
        n = neighbors[0]
        assert "id" in n
        assert "content" in n
        assert "layer" in n
        assert "connection_type" in n
        assert "connection_strength" in n
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_wander.py -v`
Expected: FAIL — `AttributeError: 'Storage' object has no attribute 'get_neighbors'`

- [ ] **Step 3: Implement get_neighbors in storage.py**

Add after `get_resonances_for` (~line 1288) in `storage.py`:

```python
def get_neighbors(self, memory_id: str) -> list[dict]:
    """Return all neighbors of a memory across resonance and provenance axes.

    Each neighbor: {id, content, layer, connection_type, connection_strength}
    """
    neighbors = []

    # --- Resonances (bidirectional) ---
    rows = self.db.execute(
        """
        SELECT r.memory_a, r.layer_a, r.memory_b, r.layer_b,
               r.similarity, r.strength
        FROM resonances r
        WHERE r.memory_a = ? OR r.memory_b = ?
        """,
        (memory_id, memory_id),
    ).fetchall()
    for row in rows:
        if row[0] == memory_id:
            peer_id, peer_layer = row[2], row[3]
        else:
            peer_id, peer_layer = row[0], row[1]
        content = self._get_memory_content(peer_id, peer_layer)
        if content is not None:
            neighbors.append({
                "id": peer_id,
                "content": content[:300],
                "layer": peer_layer,
                "connection_type": "resonance",
                "connection_strength": row[5],  # strength
            })

    # --- Provenance: episode -> semantics built from it ---
    sem_children = self.db.execute(
        "SELECT semantic_id FROM semantic_sources WHERE episode_id = ?",
        (memory_id,),
    ).fetchall()
    for (sem_id,) in sem_children:
        sem = self.get_semantic(sem_id)
        if sem:
            neighbors.append({
                "id": sem_id,
                "content": sem["content"][:300],
                "layer": "semantic",
                "connection_type": "provenance",
                "connection_strength": sem.get("confidence", 0.5),
            })

    # --- Provenance: semantic -> source episodes ---
    ep_parents = self.db.execute(
        "SELECT episode_id FROM semantic_sources WHERE semantic_id = ?",
        (memory_id,),
    ).fetchall()
    for (ep_id,) in ep_parents:
        ep = self.get_episode(ep_id)
        if ep:
            neighbors.append({
                "id": ep_id,
                "content": ep["content"][:300],
                "layer": "episode",
                "connection_type": "provenance",
                "connection_strength": ep.get("decay_strength", 0.5),
            })

    # --- Provenance: semantic -> instincts built from it ---
    ins_children = self.db.execute(
        "SELECT instinct_id FROM instinct_sources WHERE semantic_id = ?",
        (memory_id,),
    ).fetchall()
    for (ins_id,) in ins_children:
        ins = self.get_instinct(ins_id)
        if ins:
            neighbors.append({
                "id": ins_id,
                "content": f"[{ins.get('notice', '')}] {ins.get('implication', '')}",
                "layer": "instinct",
                "connection_type": "provenance",
                "connection_strength": ins.get("strength", 0.5),
            })

    # --- Provenance: instinct -> source semantics ---
    sem_parents = self.db.execute(
        "SELECT semantic_id FROM instinct_sources WHERE instinct_id = ?",
        (memory_id,),
    ).fetchall()
    for (sem_id,) in sem_parents:
        sem = self.get_semantic(sem_id)
        if sem:
            neighbors.append({
                "id": sem_id,
                "content": sem["content"][:300],
                "layer": "semantic",
                "connection_type": "provenance",
                "connection_strength": sem.get("confidence", 0.5),
            })

    return neighbors

def _get_memory_content(self, memory_id: str, layer: str) -> str | None:
    """Fetch content string for a memory by layer."""
    if layer == "episode":
        ep = self.get_episode(memory_id)
        return ep["content"] if ep else None
    elif layer == "semantic":
        sem = self.get_semantic(memory_id)
        return sem["content"] if sem else None
    elif layer == "instinct":
        ins = self.get_instinct(memory_id)
        if ins:
            return f"[{ins.get('notice', '')}] {ins.get('implication', '')}"
        return None
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_wander.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_wander.py
git commit -m "feat: get_neighbors() — resonance and provenance axes for wander"
```

---

### Task 2: Knowledge graph neighbors

**Files:**
- Modify: `knowledge.py` (~line 237, after `search`)
- Modify: `storage.py` (extend `get_neighbors` to call knowledge graph)
- Test: `tests/test_wander.py` (add tests)

- [ ] **Step 1: Write failing test for entity neighbors**

Add to `tests/test_wander.py`:

```python
class TestEntityNeighbors:
    """Test knowledge graph entity links in get_neighbors."""

    def test_get_neighbors_includes_entity_links(self, db, fake_embedding):
        """When knowledge graph returns entity matches, they appear as neighbors."""
        emb = fake_embedding()
        db.add_episode("ep-1", "sess-1", "Vin joined the crew", embedding=emb)
        db.add_episode("ep-2", "sess-1", "Vin trained with Kelsier", embedding=emb)

        # Simulate entity links by providing a knowledge_graph that returns results
        # We test via the server-level wander, not storage directly,
        # since entity links come from the knowledge graph not SQLite.
        # For storage.get_neighbors, entity links are passed in.
        neighbors = db.get_neighbors("ep-1", entity_neighbors=[
            {"id": "ep-2", "content": "Vin trained with Kelsier",
             "layer": "episode", "entity_name": "Vin"}
        ])
        entity_links = [n for n in neighbors if n["connection_type"] == "entity"]
        assert len(entity_links) == 1
        assert entity_links[0]["id"] == "ep-2"
        assert entity_links[0]["entity_name"] == "Vin"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_wander.py::TestEntityNeighbors -v`
Expected: FAIL — `get_neighbors() got an unexpected keyword argument 'entity_neighbors'`

- [ ] **Step 3: Extend get_neighbors to accept entity_neighbors**

In `storage.py`, update `get_neighbors` signature and add entity handling:

```python
def get_neighbors(self, memory_id: str, entity_neighbors: list[dict] | None = None) -> list[dict]:
    """Return all neighbors of a memory across resonance, provenance, and entity axes.

    Entity neighbors are passed in from the knowledge graph (not stored in SQLite).
    Each neighbor: {id, content, layer, connection_type, connection_strength, entity_name?}
    """
    neighbors = []

    # ... existing resonance and provenance code ...

    # --- Entity links (from knowledge graph) ---
    for en in (entity_neighbors or []):
        neighbors.append({
            "id": en["id"],
            "content": en["content"][:300],
            "layer": en["layer"],
            "connection_type": "entity",
            "connection_strength": 1.0,
            "entity_name": en.get("entity_name"),
        })

    return neighbors
```

- [ ] **Step 4: Add get_entity_neighbors to knowledge.py**

Add after `search()` in `knowledge.py`:

```python
async def get_entity_neighbors(self, memory_content: str, exclude_id: str, num_results: int = 10) -> list[dict]:
    """Find memories that share entities with the given content.

    Returns list of {id, content, layer, entity_name} dicts.
    """
    if not self.enabled:
        return []
    try:
        results = await self._graphiti.search(memory_content, num_results=num_results)
        neighbors = []
        seen = set()
        for edge in results.edges if hasattr(results, 'edges') else []:
            for node in [edge.source_node, edge.target_node]:
                if hasattr(node, 'name') and node.uuid not in seen and node.uuid != exclude_id:
                    seen.add(node.uuid)
                    neighbors.append({
                        "id": node.uuid,
                        "content": node.name,
                        "layer": "entity",
                        "entity_name": node.name,
                    })
        return neighbors[:num_results]
    except Exception:
        return []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_wander.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add storage.py knowledge.py tests/test_wander.py
git commit -m "feat: entity neighbors via knowledge graph for wander"
```

---

### Task 3: Wander MCP tool with auto-walk

**Files:**
- Modify: `server.py` (add `wander` tool after existing tools, add session visit tracking)
- Test: `tests/test_wander.py` (add tool-level tests)

- [ ] **Step 1: Write failing tests for wander tool**

Add to `tests/test_wander.py`:

```python
class TestAutoWalk:
    """Test the auto-walk algorithm."""

    def test_single_step_returns_neighbors(self, db, fake_embedding):
        """max_steps=1 returns direct neighbors only."""
        emb_a, emb_b, emb_c = fake_embedding(), fake_embedding(), fake_embedding()
        db.add_episode("ep-1", "sess-1", "start", embedding=emb_a)
        db.add_episode("ep-2", "sess-1", "middle", embedding=emb_b)
        db.add_episode("ep-3", "sess-1", "end", embedding=emb_c)
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.8, weight=0.6)
        db.add_resonance("ep-2", "episode", "ep-3", "episode", similarity=0.7, weight=0.5)

        # Single step from ep-1 should only see ep-2
        neighbors = db.get_neighbors("ep-1")
        ids = [n["id"] for n in neighbors]
        assert "ep-2" in ids
        assert "ep-3" not in ids

    def test_no_duplicate_nodes_in_trail(self, db, fake_embedding):
        """Auto-walk never visits the same node twice."""
        from server import _auto_walk
        embs = [fake_embedding() for _ in range(4)]
        db.add_episode("ep-1", "sess-1", "a", embedding=embs[0])
        db.add_episode("ep-2", "sess-1", "b", embedding=embs[1])
        db.add_episode("ep-3", "sess-1", "c", embedding=embs[2])
        db.add_episode("ep-4", "sess-1", "d", embedding=embs[3])
        # Create a cycle: 1-2, 2-3, 3-1, 3-4
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.9, weight=0.7)
        db.add_resonance("ep-2", "episode", "ep-3", "episode", similarity=0.8, weight=0.6)
        db.add_resonance("ep-1", "episode", "ep-3", "episode", similarity=0.7, weight=0.5)
        db.add_resonance("ep-3", "episode", "ep-4", "episode", similarity=0.6, weight=0.4)

        trail = _auto_walk(db, "ep-1", max_steps=10, density_threshold=20,
                           knowledge_graph=None, visit_counts={})
        trail_ids = [step["id"] for step in trail]
        assert len(trail_ids) == len(set(trail_ids)), "Duplicate nodes in trail"

    def test_density_stops_walk(self, db, fake_embedding):
        """Walk stops when a node has neighbors >= density_threshold."""
        embs = [fake_embedding() for _ in range(6)]
        db.add_episode("ep-sparse", "sess-1", "sparse node", embedding=embs[0])
        db.add_episode("ep-dense", "sess-1", "dense node", embedding=embs[1])
        # sparse -> dense
        db.add_resonance("ep-sparse", "episode", "ep-dense", "episode",
                         similarity=0.8, weight=0.7)
        # dense has 5 more neighbors
        for i in range(2, 6):
            db.add_episode(f"ep-{i}", "sess-1", f"neighbor {i}", embedding=embs[i])
            db.add_resonance("ep-dense", "episode", f"ep-{i}", "episode",
                             similarity=0.7, weight=0.5)

        from server import _auto_walk
        trail = _auto_walk(db, "ep-sparse", max_steps=10, density_threshold=5,
                           knowledge_graph=None, visit_counts={})
        # Should stop at ep-dense (6 neighbors >= threshold 5)
        assert trail[-1]["id"] == "ep-dense"

    def test_visit_counts_bias(self, db, fake_embedding):
        """Previously visited nodes get reduced probability."""
        embs = [fake_embedding() for _ in range(3)]
        db.add_episode("ep-1", "sess-1", "start", embedding=embs[0])
        db.add_episode("ep-2", "sess-1", "visited before", embedding=embs[1])
        db.add_episode("ep-3", "sess-1", "fresh", embedding=embs[2])
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.9, weight=0.9)
        db.add_resonance("ep-1", "episode", "ep-3", "episode", similarity=0.5, weight=0.3)

        from server import _auto_walk
        # With ep-2 heavily visited, should favor ep-3
        visit_counts = {"ep-2": 10}
        # Run multiple times to check statistical bias
        choices = []
        for _ in range(50):
            trail = _auto_walk(db, "ep-1", max_steps=2, density_threshold=20,
                               knowledge_graph=None, visit_counts=dict(visit_counts))
            if trail:
                choices.append(trail[0]["id"])
        # ep-3 should appear more than if purely strength-based
        ep3_count = choices.count("ep-3")
        assert ep3_count > 5, f"ep-3 only chosen {ep3_count}/50 times despite visit bias"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_wander.py::TestAutoWalk -v`
Expected: FAIL — `ImportError: cannot import name '_auto_walk' from 'server'`

- [ ] **Step 3: Implement _auto_walk and wander tool in server.py**

Add session visit tracking near other module-level state (~line 111):

```python
_wander_visits: dict[str, int] = {}  # memory_id -> visit count this session
```

Add the auto-walk function and wander tool (after existing tools):

```python
def _auto_walk(
    storage: Storage,
    start_id: str,
    max_steps: int,
    density_threshold: int,
    knowledge_graph,
    visit_counts: dict[str, int],
) -> list[dict]:
    """Walk the memory graph with novelty-biased weighted random selection.

    Returns trail: list of {id, content, layer, connection_type, connection_strength, ...}
    Stops at dense nodes (>= density_threshold neighbors) or after max_steps.
    """
    import random

    trail = []
    visited_in_trail = {start_id}
    current_id = start_id

    for _ in range(max_steps):
        # Get entity neighbors from knowledge graph if available
        entity_neighbors = None
        if knowledge_graph and knowledge_graph.enabled:
            # Get content for entity search
            content = storage._get_memory_content(
                current_id,
                _detect_layer(storage, current_id),
            )
            if content:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        entity_neighbors = None  # Can't await in sync context
                    else:
                        entity_neighbors = loop.run_until_complete(
                            knowledge_graph.get_entity_neighbors(content, current_id)
                        )
                except RuntimeError:
                    entity_neighbors = None

        neighbors = storage.get_neighbors(current_id, entity_neighbors=entity_neighbors)

        # Filter out already-visited nodes in this trail
        candidates = [n for n in neighbors if n["id"] not in visited_in_trail]

        if not candidates:
            break

        # Check density — if current node is dense enough, stop here
        if len(neighbors) >= density_threshold and trail:
            break

        # Weighted random selection with visit penalty
        weights = []
        for c in candidates:
            w = c["connection_strength"]
            prior_visits = visit_counts.get(c["id"], 0)
            if prior_visits > 0:
                w *= 1.0 / (1.0 + prior_visits)
            weights.append(max(w, 0.01))

        total = sum(weights)
        probs = [w / total for w in weights]
        chosen = random.choices(candidates, weights=probs, k=1)[0]

        trail.append(chosen)
        visited_in_trail.add(chosen["id"])
        current_id = chosen["id"]

    return trail


def _detect_layer(storage: Storage, memory_id: str) -> str:
    """Detect which layer a memory belongs to."""
    if storage.get_episode(memory_id):
        return "episode"
    if storage.get_semantic(memory_id):
        return "semantic"
    if storage.get_instinct(memory_id):
        return "instinct"
    return "episode"


@mcp.tool()
def wander(
    start_id: str,
    max_steps: int = 1,
) -> dict:
    """Walk the memory graph from a starting point.

    Instead of searching, follow connections: resonances (lateral),
    provenance (vertical), and shared entities (knowledge graph).

    max_steps=1: return direct neighbors.
    max_steps>1: auto-walk with density-adaptive stopping.
    Walks through sparse regions, pauses at dense clusters.

    Args:
        start_id: Memory ID to start from (episode, semantic, or instinct).
        max_steps: Maximum hops. 1 for single step, >1 for auto-walk.
    """
    global _wander_visits

    density_threshold = 5

    if max_steps <= 1:
        # Single step — return all neighbors
        entity_neighbors = None
        if _knowledge_graph and _knowledge_graph.enabled:
            content = _storage._get_memory_content(start_id, _detect_layer(_storage, start_id))
            if content:
                import asyncio
                try:
                    entity_neighbors = asyncio.get_event_loop().run_until_complete(
                        _knowledge_graph.get_entity_neighbors(content, start_id)
                    )
                except Exception:
                    entity_neighbors = None

        neighbors = _storage.get_neighbors(start_id, entity_neighbors=entity_neighbors)
        _wander_visits[start_id] = _wander_visits.get(start_id, 0) + 1
        return {
            "start": start_id,
            "neighbors": neighbors,
            "count": len(neighbors),
        }
    else:
        # Auto-walk
        trail = _auto_walk(
            _storage, start_id, max_steps, density_threshold,
            _knowledge_graph, _wander_visits,
        )
        # Update visit counts
        _wander_visits[start_id] = _wander_visits.get(start_id, 0) + 1
        for step in trail:
            _wander_visits[step["id"]] = _wander_visits.get(step["id"], 0) + 1

        # Get neighbors of final node for exploration
        final_id = trail[-1]["id"] if trail else start_id
        entity_neighbors = None
        if _knowledge_graph and _knowledge_graph.enabled:
            content = _storage._get_memory_content(final_id, _detect_layer(_storage, final_id))
            if content:
                import asyncio
                try:
                    entity_neighbors = asyncio.get_event_loop().run_until_complete(
                        _knowledge_graph.get_entity_neighbors(content, final_id)
                    )
                except Exception:
                    entity_neighbors = None
        final_neighbors = _storage.get_neighbors(final_id, entity_neighbors=entity_neighbors)

        return {
            "start": start_id,
            "trail": trail,
            "steps": len(trail),
            "stopped_at": final_id,
            "stopped_reason": "dense_cluster" if len(final_neighbors) >= density_threshold else
                             "max_steps" if len(trail) >= max_steps else "dead_end",
            "final_neighbors": final_neighbors,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_wander.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_wander.py
git commit -m "feat: wander() MCP tool — graph traversal with density-adaptive auto-walk"
```

---

### Task 4: Deep pass — structural lenses

**Files:**
- Create: `deep_pass.py`
- Create: `tests/test_deep_pass.py`

- [ ] **Step 1: Write failing tests for structural lens runner**

Create `tests/test_deep_pass.py`:

```python
"""Tests for between-session deep pass."""

import pytest
from unittest.mock import patch, MagicMock
from deep_pass import run_structural_lenses, find_gap_domains, run_gap_lenses, deep_pass


@pytest.fixture
def sample_passages():
    return [
        {"passage": "Vin takes three baywraps", "reaction": "scarcity is in her"},
        {"passage": "Kelsier laughs at the noblemen", "reaction": "defiance as performance"},
        {"passage": "Sazed records another religion", "reaction": "preservation against loss"},
    ]


@pytest.fixture
def structural_lenses():
    return [
        {
            "name": "arc",
            "mode": "batch",
            "prompt": "You trace thematic arcs across a sequence of passages. "
                      "What themes are building? What's being set up but not resolved? "
                      "Given these passages and the reader's reactions, identify arcs.",
        },
        {
            "name": "recurrence",
            "mode": "batch",
            "prompt": "You notice recurring imagery, language, and situations across passages. "
                      "What keeps showing up? What is the text doing with repetition? "
                      "Given these passages and reactions, identify recurrences.",
        },
    ]


class TestStructuralLenses:

    def test_run_structural_lenses_calls_ollama(self, sample_passages, structural_lenses):
        """Each structural lens gets called with all passages batched."""
        with patch("deep_pass._call_ollama") as mock_ollama:
            mock_ollama.return_value = "Themes of scarcity and preservation build across passages."
            results = run_structural_lenses(sample_passages, structural_lenses)

        assert len(results) == 2  # one per lens
        assert mock_ollama.call_count == 2
        # Each call should include all passages
        for call in mock_ollama.call_args_list:
            assert "Vin takes three baywraps" in call[1]["user_prompt"]
            assert "Kelsier laughs" in call[1]["user_prompt"]

    def test_structural_lens_result_format(self, sample_passages, structural_lenses):
        """Results include lens name and observation text."""
        with patch("deep_pass._call_ollama") as mock_ollama:
            mock_ollama.return_value = "Arc observation."
            results = run_structural_lenses(sample_passages, structural_lenses)

        assert results[0]["lens_name"] == "arc"
        assert results[0]["lens_type"] == "structural"
        assert results[0]["observation"] == "Arc observation."

    def test_ollama_failure_skips_lens(self, sample_passages, structural_lenses):
        """If Ollama fails for one lens, skip it and continue."""
        with patch("deep_pass._call_ollama") as mock_ollama:
            mock_ollama.side_effect = [Exception("GPU busy"), "Recurrence found."]
            results = run_structural_lenses(sample_passages, structural_lenses)

        assert len(results) == 1
        assert results[0]["lens_name"] == "recurrence"

    def test_empty_passages_returns_empty(self, structural_lenses):
        """No passages means no work."""
        results = run_structural_lenses([], structural_lenses)
        assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_deep_pass.py::TestStructuralLenses -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'deep_pass'`

- [ ] **Step 3: Implement deep_pass.py with structural lenses**

Create `deep_pass.py`:

```python
"""Between-session deep pass — counterfactual perception.

Runs structural and gap-specific lenses against passages that sessions
missed. Stores results as episodes. Called during sleep-time consolidation.
"""

import json
import logging
import os
import uuid
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEEP_PASS_MODEL = os.environ.get("ENGRAM_DEEP_PASS_MODEL", "qwen3:8b")
READER_DB = os.environ.get("READER_DB", str(Path.home() / ".reader" / "reader.db"))
STRUCTURAL_LENS_DIR = Path.home() / ".prism" / "packs" / "deep-pass"


def _call_ollama(system_prompt: str, user_prompt: str, timeout: int = 120) -> str:
    """Call Ollama with patient retry for shared GPU."""
    import time

    for attempt in range(3):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": DEEP_PASS_MODEL,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": False,
                    "options": {"temperature": 0.7},
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()["response"]
        except (requests.ConnectionError, requests.Timeout):
            if attempt < 2:
                logger.info("Ollama busy, waiting 30s (attempt %d/3)", attempt + 1)
                time.sleep(30)
            else:
                raise


def _format_passages_batch(passages: list[dict]) -> str:
    """Format multiple passages + reactions for a batch lens."""
    parts = []
    for i, p in enumerate(passages, 1):
        parts.append(f"--- Passage {i} ---\n{p['passage']}\n\nReader's reaction: {p['reaction']}")
    return "\n\n".join(parts)


def run_structural_lenses(
    passages: list[dict],
    lenses: list[dict],
) -> list[dict]:
    """Run structural (batch) lenses across all passages.

    Returns list of {lens_name, lens_type, observation}.
    """
    if not passages:
        return []

    batch_text = _format_passages_batch(passages)
    results = []

    for lens in lenses:
        try:
            observation = _call_ollama(
                system_prompt=lens["prompt"],
                user_prompt=batch_text,
            )
            results.append({
                "lens_name": lens["name"],
                "lens_type": "structural",
                "observation": observation,
            })
        except Exception as e:
            logger.warning("Structural lens '%s' failed: %s", lens["name"], e)
            continue

    return results


def find_gap_domains(
    fired_history: dict[str, int],
    available_lenses: list[dict],
    session_threshold: int = 3,
) -> list[dict]:
    """Find lens domains with zero fires in the last N sessions.

    Args:
        fired_history: {lens_name: fire_count_in_recent_sessions}
        available_lenses: List of lens dicts with name, domain, prompt, sources
        session_threshold: How many sessions of zero fires to count as a gap

    Returns list of lens dicts that qualify as gaps.
    """
    gaps = []
    for lens in available_lenses:
        if fired_history.get(lens["name"], 0) == 0:
            gaps.append(lens)
    return gaps


def run_gap_lenses(
    passages: list[dict],
    gap_lenses: list[dict],
) -> list[dict]:
    """Run gap-specific lenses — generated prompts for blind spot domains.

    Each gap lens runs against all passages with a prompt tailored to
    its domain. These are ephemeral — generated per consolidation, not
    persisted as YAML.

    Returns list of {lens_name, lens_type, observation}.
    """
    if not passages or not gap_lenses:
        return []

    batch_text = _format_passages_batch(passages)
    results = []

    for lens in gap_lenses:
        domain = lens.get("domain", lens["name"])
        sources = lens.get("sources", [])
        source_text = f" Drawing on: {', '.join(sources)}." if sources else ""

        prompt = (
            f"These passages were read without attention to {domain}.{source_text} "
            f"What might this perspective notice that the reader didn't? "
            f"Don't summarize the passages. Identify what was missed — "
            f"the patterns, dynamics, or tensions that this lens would see."
        )

        try:
            observation = _call_ollama(
                system_prompt=prompt,
                user_prompt=batch_text,
            )
            results.append({
                "lens_name": lens["name"],
                "lens_type": "gap",
                "observation": observation,
            })
        except Exception as e:
            logger.warning("Gap lens '%s' failed: %s", lens["name"], e)
            continue

    return results


def load_structural_lenses() -> list[dict]:
    """Load structural lens definitions from YAML pack."""
    import yaml

    lenses = []
    if not STRUCTURAL_LENS_DIR.exists():
        return lenses

    for path in sorted(STRUCTURAL_LENS_DIR.glob("*.yaml")):
        try:
            with open(path) as f:
                lens = yaml.safe_load(f)
            if lens and lens.get("mode") == "batch":
                lenses.append(lens)
        except Exception as e:
            logger.warning("Failed to load structural lens %s: %s", path, e)

    return lenses


def load_reading_lenses() -> list[dict]:
    """Load in-session reading lens definitions for gap detection."""
    import yaml

    lens_dir = Path.home() / ".prism" / "packs" / "reading"
    lenses = []
    if not lens_dir.exists():
        return lenses

    for path in sorted(lens_dir.glob("*.yaml")):
        try:
            with open(path) as f:
                lens = yaml.safe_load(f)
            if lens:
                lenses.append(lens)
        except Exception as e:
            logger.warning("Failed to load reading lens %s: %s", path, e)

    return lenses


def get_recent_passages() -> list[dict]:
    """Fetch passage/reaction pairs from the reader's most recent session."""
    import sqlite3

    if not Path(READER_DB).exists():
        return []

    try:
        conn = sqlite3.connect(READER_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT passage, reaction FROM reactions
            WHERE session_id = (
                SELECT session_id FROM reactions ORDER BY created_at DESC LIMIT 1
            )
            ORDER BY position
            """
        ).fetchall()
        conn.close()
        return [{"passage": r["passage"], "reaction": r["reaction"]} for r in rows]
    except Exception as e:
        logger.warning("Failed to read passages from reader DB: %s", e)
        return []


def get_fired_history() -> dict[str, int]:
    """Get lens fire counts from the prism transition graph."""
    import sqlite3

    transitions_db = Path.home() / ".prism" / "reading-transitions.db"
    if not transitions_db.exists():
        return {}

    try:
        conn = sqlite3.connect(str(transitions_db))
        rows = conn.execute(
            "SELECT name, fired FROM nodes WHERE fired > 0"
        ).fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    except Exception as e:
        logger.warning("Failed to read fired history: %s", e)
        return {}


def deep_pass(storage, embeddings, session_id: str | None = None) -> dict:
    """Run the between-session deep pass.

    Called during sleep-time consolidation. Runs structural and gap lenses
    against missed passages, stores results as episodes.

    Returns summary: {structural_count, gap_count, skipped_reason?}
    """
    passages = get_recent_passages()
    if not passages:
        return {"structural_count": 0, "gap_count": 0, "skipped_reason": "no reading data"}

    structural_lenses = load_structural_lenses()
    structural_results = run_structural_lenses(passages, structural_lenses)

    fired = get_fired_history()
    reading_lenses = load_reading_lenses()
    gap_domains = find_gap_domains(fired, reading_lenses)
    gap_results = run_gap_lenses(passages, gap_domains)

    # Store all results as episodes
    all_results = structural_results + gap_results
    for result in all_results:
        episode_id = str(uuid.uuid4())
        content = (
            f"[Deep pass — {result['lens_type']}:{result['lens_name']}] "
            f"{result['observation']}"
        )
        context = {
            "deep_pass": True,
            "lens_type": result["lens_type"],
            "lens_name": result["lens_name"],
        }
        embedding = embeddings.embed([content], prefix="search_document")[0]
        storage.add_episode(
            episode_id,
            session_id,
            content,
            embedding=embedding,
            context=context,
        )
        storage.set_episode_source(
            episode_id,
            f"prism:deep-pass:{result['lens_type']}:{result['lens_name']}",
        )

    return {
        "structural_count": len(structural_results),
        "gap_count": len(gap_results),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_deep_pass.py::TestStructuralLenses -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add deep_pass.py tests/test_deep_pass.py
git commit -m "feat: deep pass — structural and gap lenses for counterfactual perception"
```

---

### Task 5: Deep pass — gap lens tests and integration

**Files:**
- Modify: `tests/test_deep_pass.py` (add gap lens and integration tests)

- [ ] **Step 1: Write tests for gap detection and gap lenses**

Add to `tests/test_deep_pass.py`:

```python
class TestGapDetection:

    def test_finds_unfired_domains(self):
        """Lenses with zero fires are gaps."""
        fired = {"attachment": 5, "power": 3}
        available = [
            {"name": "attachment", "domain": "early-childhood"},
            {"name": "power", "domain": "critical-theory"},
            {"name": "formalist", "domain": "literary-theory"},
            {"name": "neuroscience", "domain": "affective-neuroscience"},
        ]
        gaps = find_gap_domains(fired, available)
        gap_names = [g["name"] for g in gaps]
        assert "formalist" in gap_names
        assert "neuroscience" in gap_names
        assert "attachment" not in gap_names
        assert "power" not in gap_names

    def test_empty_history_all_are_gaps(self):
        """No history means everything is a gap."""
        available = [
            {"name": "attachment", "domain": "early-childhood"},
            {"name": "formalist", "domain": "literary-theory"},
        ]
        gaps = find_gap_domains({}, available)
        assert len(gaps) == 2


class TestGapLenses:

    def test_run_gap_lenses(self, sample_passages):
        """Gap lenses generate prompts from domain metadata."""
        gap_lenses = [
            {"name": "formalist", "domain": "literary formalism",
             "sources": ["Shklovsky, Art as Technique (1917)"]},
        ]
        with patch("deep_pass._call_ollama") as mock_ollama:
            mock_ollama.return_value = "The defamiliarization in Vin's hoarding..."
            results = run_gap_lenses(sample_passages, gap_lenses)

        assert len(results) == 1
        assert results[0]["lens_type"] == "gap"
        assert results[0]["lens_name"] == "formalist"
        # Check the prompt included domain info
        call_args = mock_ollama.call_args
        assert "literary formalism" in call_args[1]["system_prompt"]
        assert "Shklovsky" in call_args[1]["system_prompt"]

    def test_empty_gaps_returns_empty(self, sample_passages):
        """No gap lenses means no work."""
        results = run_gap_lenses(sample_passages, [])
        assert results == []


class TestDeepPassIntegration:

    def test_deep_pass_stores_episodes(self, sample_passages):
        """Full deep pass stores structural + gap results as episodes."""
        mock_storage = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.embed.return_value = [[0.1] * 768]

        with patch("deep_pass.get_recent_passages", return_value=sample_passages), \
             patch("deep_pass.load_structural_lenses", return_value=[
                 {"name": "arc", "mode": "batch", "prompt": "Find arcs."},
             ]), \
             patch("deep_pass.get_fired_history", return_value={"attachment": 5}), \
             patch("deep_pass.load_reading_lenses", return_value=[
                 {"name": "attachment", "domain": "early-childhood"},
                 {"name": "formalist", "domain": "literary-theory"},
             ]), \
             patch("deep_pass._call_ollama", return_value="Observation."):
            result = deep_pass(mock_storage, mock_embeddings, session_id="test-sess")

        assert result["structural_count"] == 1
        assert result["gap_count"] == 1
        assert mock_storage.add_episode.call_count == 2
        assert mock_storage.set_episode_source.call_count == 2
        # Check source tags
        sources = [call[0][1] for call in mock_storage.set_episode_source.call_args_list]
        assert any("structural" in s for s in sources)
        assert any("gap" in s for s in sources)

    def test_deep_pass_skips_no_reading_data(self):
        """No passages means skip entirely."""
        mock_storage = MagicMock()
        mock_embeddings = MagicMock()

        with patch("deep_pass.get_recent_passages", return_value=[]):
            result = deep_pass(mock_storage, mock_embeddings)

        assert result["skipped_reason"] == "no reading data"
        mock_storage.add_episode.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_deep_pass.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_deep_pass.py
git commit -m "test: gap lens detection and deep pass integration"
```

---

### Task 6: Wire deep pass into wake.py consolidation

**Files:**
- Modify: `hooks/wake.py` (add deep_pass call)

- [ ] **Step 1: Read current wake.py to confirm insertion point**

Read `hooks/wake.py` and identify where the consolidation output is built (before the final `systemMessage` output).

- [ ] **Step 2: Add deep pass call to wake.py**

At the end of the consolidation sequence in `wake()`, before building the system message output, add:

```python
# --- Between-session deep pass ---
try:
    from deep_pass import deep_pass as run_deep_pass
    from embeddings import Embeddings
    from config import get_config

    cfg = get_config()
    emb = Embeddings()
    dp_result = run_deep_pass(storage, emb, session_id=None)
    if dp_result.get("structural_count", 0) + dp_result.get("gap_count", 0) > 0:
        parts.append(
            f"\n**Deep pass:** {dp_result['structural_count']} structural, "
            f"{dp_result['gap_count']} gap observations stored."
        )
except Exception as e:
    # Deep pass failure must not block session startup
    import logging
    logging.getLogger(__name__).warning("Deep pass failed: %s", e)
```

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All tests pass (deep pass import is in a try/except so it won't break wake if dependencies are missing)

- [ ] **Step 4: Commit**

```bash
git add hooks/wake.py
git commit -m "feat: wire deep pass into sleep-time consolidation cycle"
```

---

### Task 7: Structural lens YAML files

**Files:**
- Create: `~/.prism/packs/deep-pass/arc.yaml`
- Create: `~/.prism/packs/deep-pass/recurrence.yaml`
- Create: `~/.prism/packs/deep-pass/trajectory.yaml`
- Create: `~/.prism/packs/deep-pass/absence-over-time.yaml`

- [ ] **Step 1: Create the deep-pass pack directory**

```bash
mkdir -p ~/.prism/packs/deep-pass
```

- [ ] **Step 2: Create arc.yaml**

```yaml
name: arc
mode: batch
domain: thematic-structure
prompt: |
  You trace thematic arcs across a sequence of passages and a reader's
  reactions to them. You are not summarizing — you are identifying what
  is building.

  What themes are accumulating force? What is being set up but not yet
  resolved? What tensions are tightening? Where is the text creating
  expectations that it hasn't fulfilled?

  Look at the reader's reactions too — what arcs is the reader tracking
  versus what arcs they seem unaware of?

  Be specific. Name the passages where you see arc movement. Don't
  list themes abstractly — show where they appear and how they develop.
```

- [ ] **Step 3: Create recurrence.yaml**

```yaml
name: recurrence
mode: batch
domain: pattern-repetition
prompt: |
  You notice recurring imagery, language, situations, and structural
  patterns across a sequence of passages.

  What keeps showing up? Not just repeated words — repeated shapes.
  Similar situations with different characters. Echoed language across
  different contexts. Structural parallels the reader may not have
  registered.

  What is the text doing with this repetition? Is it reinforcing,
  subverting, evolving a pattern? Does the reader's reaction track
  the recurrence or miss it?

  Be specific. Quote or reference the passages where you see echoes.
```

- [ ] **Step 4: Create trajectory.yaml**

```yaml
name: trajectory
mode: batch
domain: character-movement
prompt: |
  You track character movement across a sequence of passages — not
  physical movement, but psychological, relational, and moral
  trajectories.

  Who is changing? Who is static? What direction is the change going?
  Are characters converging or diverging? Where does a character's
  trajectory in the text diverge from the reader's interpretation
  of that trajectory?

  Look at what the reader noticed about character change versus what
  the passages actually show. Where is the reader's model of a
  character ahead of, behind, or sideways from the text's evidence?

  Be specific. Reference passages that show trajectory shifts.
```

- [ ] **Step 5: Create absence-over-time.yaml**

```yaml
name: absence-over-time
mode: batch
domain: structural-absence
prompt: |
  You attend to what disappears, what was never there, and what the
  text avoids across a sequence of passages.

  What was present early and has faded? What topics, characters, or
  dynamics have been conspicuously absent throughout? What does the
  text seem to be avoiding? What is the reader not asking about?

  This is the structural version of noticing absence — not within a
  single passage but across the arc of a reading session. A single
  absence might be incidental. A sustained absence is a choice —
  by the author, by the reader, or both.

  Be specific. Name what's missing and where you'd expect to find it.
```

- [ ] **Step 6: Commit**

```bash
git add -f ~/.prism/packs/deep-pass/*.yaml 2>/dev/null || true
# These are user-config files, not in the repo. Just verify they exist:
ls ~/.prism/packs/deep-pass/
```

Note: These YAML files live in `~/.prism/` (user config), not in the engram repo. No git commit needed for these — they're runtime configuration.

---

### Task 8: Final integration test and cleanup

**Files:**
- Modify: `tests/test_wander.py` (add edge case tests)

- [ ] **Step 1: Add edge case tests**

Add to `tests/test_wander.py`:

```python
class TestWanderEdgeCases:

    def test_nonexistent_start_id(self, db):
        """Starting from a nonexistent ID returns empty neighbors."""
        neighbors = db.get_neighbors("does-not-exist")
        assert neighbors == []

    def test_mixed_layer_neighbors(self, db, fake_embedding):
        """A memory can have neighbors from different layers."""
        emb = fake_embedding()
        db.add_episode("ep-1", "sess-1", "experience", embedding=emb)
        db.add_episode("ep-2", "sess-1", "related experience", embedding=emb)
        db.add_semantic("sem-1", "distilled from ep-1", "fact", 0.8, emb,
                        source_episode_ids=["ep-1"])
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.8, weight=0.6)

        neighbors = db.get_neighbors("ep-1")
        layers = {n["layer"] for n in neighbors}
        assert "episode" in layers  # resonance to ep-2
        assert "semantic" in layers  # provenance to sem-1

    def test_auto_walk_dead_end(self, db, fake_embedding):
        """Auto-walk from an orphan returns empty trail."""
        from server import _auto_walk
        db.add_episode("ep-alone", "sess-1", "isolated", embedding=fake_embedding())
        trail = _auto_walk(db, "ep-alone", max_steps=5, density_threshold=5,
                           knowledge_graph=None, visit_counts={})
        assert trail == []

    def test_content_truncation(self, db, fake_embedding):
        """Long content is truncated to 300 chars in neighbors."""
        long_content = "x" * 500
        db.add_episode("ep-1", "sess-1", "start", embedding=fake_embedding())
        db.add_episode("ep-2", "sess-1", long_content, embedding=fake_embedding())
        db.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.8, weight=0.6)

        neighbors = db.get_neighbors("ep-1")
        assert len(neighbors[0]["content"]) <= 300
```

- [ ] **Step 2: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_wander.py
git commit -m "test: wander edge cases — orphans, mixed layers, truncation"
```

- [ ] **Step 4: Run final verification**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests pass, no warnings beyond the existing Pydantic deprecation
