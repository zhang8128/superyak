# Unified Memory Graph — Design Spec

**Date:** 2026-05-02
**Status:** Draft
**Context:** First step toward sheaf-based memory architecture. Build the base topology before adding resolution layers.

## Problem

Engram has six relationship types stored across separate tables and mechanisms: semantic_sources, instinct_sources, resonances, instinct_co_firing, instinct_cluster_members, and knowledge graph entity links. No unified view exists. Graph traversal (`wander`, `get_neighbors`) is ad hoc — it queries each source independently and merges results. This makes it impossible to reason about the topology as a whole: connectivity, components, hubs, isolated nodes.

Before building sheaf-like resolution over the graph, we need to know what the graph looks like.

## Decision Record

- **B vs C:** Explicit graph (B) as skeleton. Emergent embedding proximity (C) as sensory layer that proposes edges but doesn't restructure topology directly.
- **Materialized vs virtual:** Virtual view layer first (Approach 3). No new tables. Materialize later only if traversal performance demands it.
- **Proximity suggestions:** Automatic but gated behind sleep. Candidates accumulate during sessions, promoted to resonances during consolidation with coherence checks.

## Design

### Core Abstractions

```python
@dataclass
class Edge:
    source: str        # memory ID
    source_layer: str   # episode | semantic | instinct | entity
    target: str
    target_layer: str
    edge_type: str     # provenance | resonance | co_firing | entity_link | contradiction
    weight: float      # normalized 0-1
    directed: bool

@dataclass
class Node:
    id: str
    layer: str
    preview: str       # first 100 chars of content
    # Full content loaded on demand — proto-resolution concept
```

### Edge Type Mapping

| Source table | edge_type | directed | weight derivation |
|---|---|---|---|
| semantic_sources | provenance | yes (episode→semantic) | similarity column, or 1.0 if null |
| instinct_sources | provenance | yes (semantic→instinct) | 1.0 |
| resonances | resonance | no | weight × strength |
| instinct_co_firing | co_firing | no | co_fire_count / max(co_fire_count) |
| contradicted_by | contradiction | yes (old→new) | 1.0 |
| episode_entities + Kuzu | entity_link | no | relationship weight from Kuzu |

### MemoryGraph Class

**File:** `graph.py` (new file)

**Constructor:** Takes `Storage` and optional `KnowledgeGraph`. Builds edge list lazily on first query.

**Methods:**

- `neighbors(node_id) → list[Edge]` — All edges touching a node, all types.
- `neighborhood(node_id, depth=1) → tuple[list[Node], list[Edge]]` — BFS to given depth.
- `stats() → dict` — Total nodes, edges by type, connected components count, isolated node count, largest component size.
- `analyze() → dict` — Extended stats: hub nodes (top 10 by degree), average degree, diameter of largest component, layer distribution.
- `suggest_edges(node_id, k=5, threshold=0.7) → list[Edge]` — Embedding proximity neighbors not already connected. Returned with `edge_type="suggested"`.
- `to_dot(center?, depth?) → str` — Graphviz DOT export. Nodes colored by layer, edges styled by type.
- `to_json(center?, depth?) → dict` — JSON export for browser rendering.

### Embedding Proximity Suggestions

`suggest_edges()` works by:
1. Get the node's embedding from the appropriate vec0 table
2. KNN search across all vec0 tables (episode_vectors, semantic_vectors, instinct_vectors) with k candidates
3. Filter out nodes already connected via any existing edge
4. Return remaining candidates above similarity threshold as suggested edges

### Sleep Integration

During sleep (session start consolidation), a new phase after existing decay/prune/backfill:

1. For each node that participated in recall this session, run `suggest_edges()`
2. Filter candidates: keep only those that appeared as suggestions in 2+ prior sessions, OR where the two nodes share at least one neighbor already (coherence check)
3. Promote surviving candidates to resonances via existing `add_resonance()` with low initial strength (0.3) and stochastic weight
4. Log promotions for observability

Candidate persistence between sessions: store suggestions in `memory_log` with event_type="proximity_suggestion" so the multi-session filter works without new tables.

### MCP Tool

```python
@mcp.tool()
def graph_view(center: str | None = None, depth: int = 1) -> dict:
    """View the memory graph topology.

    Without center: returns global stats and analysis.
    With center: returns neighborhood around that node to given depth.
    """
```

### What This Step Does NOT Include

- No sheaf layer, resolution budget, or thread-pulling (future step, contingent on topology analysis)
- No changes to recall, compress, wander, or any existing tool behavior
- No new database tables or migrations
- No modification of existing edge creation mechanisms
- Existing flows remain untouched — this is purely additive

### Testing

- Graph construction from known storage state (mock storage with known edges)
- `neighbors()` returns correct edges for each type
- `neighborhood()` BFS respects depth limit
- `stats()` and `analyze()` compute correct component counts, degrees, hubs
- `suggest_edges()` excludes already-connected nodes, respects threshold
- Sleep integration: candidates promoted only when coherence check passes
- `to_dot()` produces valid DOT output
- Edge cases: isolated nodes, single-node graph, fully connected subgraph

### Files

| File | Change |
|---|---|
| `graph.py` | New — MemoryGraph class, Edge/Node dataclasses |
| `server.py` | Add `graph_view` MCP tool |
| `server.py` | Add proximity promotion phase to `_init()` consolidation block |
| `tests/test_graph.py` | New — graph construction, traversal, analysis, suggestions |

### Future Steps (Not This Spec)

After building this and analyzing the resulting topology:
1. Assess: is the graph connected enough to support sheaf operations?
2. If yes: design sheaf layer with resolution budget over this topology
3. If no: identify what's missing and whether materialized edges or new link types are needed
