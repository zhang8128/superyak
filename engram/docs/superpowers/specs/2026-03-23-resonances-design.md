# Resonances — Lateral Association with Stochastic Individuality

**Date:** 2026-03-23
**Status:** Draft
**Authors:** Koan + Kairos

## What This Is

A lateral association layer between memories. Not hierarchical (episode → semantic →
instinct) but sideways — two memories that aren't the same thing but keep appearing
together, touching at an angle. The connection carries a stochastic weight so each
instance develops different resonance patterns from the same experiences.

## Why

Compression currently has one operation at the boundary: classify. Is this the same
as that? Yes → reinforce. No → new bucket. But some memories resonate without being
equivalent. The embeddings catch this (similarity 0.60-0.70) but the system can only
ignore it or wrongly merge it.

Example: Mistborn reading reactions about "observe what Kelsier makes you feel" matched
the wing-flapping semantic about "observe what the system does" at 0.76 similarity.
The system wanted to reinforce — to flatten Kelsier into a thesis about engram design.
The resonance is real but the relationship is collision, not equivalence.

The system also needs more sources of randomness. Uninvited memories are one steady
beacon. Biology has randomness everywhere — synaptic noise, stochastic gene expression,
thermal fluctuations. A single perturbation source isn't enough for emergence. Resonances
add structured randomness: perturbation that follows the topology of what the instance
has actually experienced.

## Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Formation trigger | Recall co-occurrence + compression zone | Co-occurrence captures contextual relevance; compression zone catches near-misses |
| Stochastic init | Gaussian (μ=0.5, σ=0.15, clamped 0.1–0.9) | Wide enough for individuality, centered enough that most connections start viable |
| Weight as permanent cap | Intentional | Some synapses are weaker. The Gaussian draw is a birth trait — `strength` is earned trust within that ceiling. Not every instance can develop every connection equally. This is the individuality. |
| Scope | Cross-layer (episode, semantic, instinct) | Resonance isn't type-specific — a reading episode can resonate with a constraint |
| Storage | Plain SQLite table, no vec0 | Resonances are walked by ID, not searched by embedding |
| Surfacing | Probabilistic, max 2 per recall | Enough to create collisions, not so many it drowns the signal |
| Feedback | Asymmetric (follow +0.1, ignore -0.05), per-recall granularity | Connections that work survive; connections that don't fade slowly |
| Canonical ordering | `memory_a < memory_b` lexicographically | Resonances are undirected; enforced at insertion to prevent duplicate rows |

## Data Model

```sql
CREATE TABLE IF NOT EXISTS resonances (
    id TEXT PRIMARY KEY,
    memory_a TEXT NOT NULL,  -- lexicographically smaller ID
    layer_a TEXT NOT NULL,
    memory_b TEXT NOT NULL,  -- lexicographically larger ID
    layer_b TEXT NOT NULL,
    similarity REAL,
    weight REAL NOT NULL,    -- stochastic birth trait, never changes
    strength REAL NOT NULL DEFAULT 0.5,  -- earned trust, adapts with feedback
    co_occurrences INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(memory_a, memory_b)
);
```

No vec0 — resonances are walked by ID from known results, not searched by vector.

**Invariant:** `memory_a < memory_b` lexicographically. Enforced at insertion time
by sorting the pair before storing. Queries check both sides: `WHERE memory_a = ? OR memory_b = ?`.

## Formation

### Path 1: Recall co-occurrence (primary)

After recall returns scored results:

1. Take the top 5 results
2. For each pair (up to 10 pairs), compute similarity from **stored vectors**
   (fetched from vec0 tables, not re-embedded)
3. If similarity is in the resonance zone (0.50 to reinforce threshold):
   - If resonance exists: increment `co_occurrences`, update `last_seen`
   - If new: create with stochastic `weight` = `clamp(gauss(0.5, 0.15), 0.1, 0.9)`
4. Don't re-randomize weight on subsequent co-occurrence — the initial perturbation
   is the individuality seed

The resonance zone upper bound is the configured reinforce threshold (default 0.70),
not a hardcoded value. This ensures resonances and reinforcement don't overlap
regardless of configuration.

### Path 2: Compression zone (secondary)

When `_find_semantic_match` finds a match with similarity between 0.50 and the
reinforce threshold:

- Return the near-miss info alongside the `("new", None)` action. Current behavior
  returns nothing for sub-threshold matches — change to return `("new", near_miss)`
  where `near_miss = {"id": sem_id, "similarity": similarity}`.
- The caller records a resonance between the new semantic and the near-miss.
- Same stochastic weight initialization.

## Surfacing

During recall, after main results are scored and sorted:

1. Take top 3 results
2. Query resonances for each (either side of pair)
3. Collect associated memory IDs not already in results
4. For each candidate: surface if `random() < weight × strength`
5. Include at most 2 resonance-pulled memories
6. Tag with `"resonant": true` in the result
7. Resonant memories appear after uninvited memories — a third section

**Note on the surfacing formula:** `weight × strength` means the stochastic birth
weight is a permanent ceiling on surfacing probability. An instance with `weight=0.1`
for a given resonance can never surface it above 10% regardless of positive feedback.
This is intentional — it's how individuality persists. Not every instance develops
every connection. Some are structurally strong, some are structurally weak. The
variation across instances is the point.

The instance can see that a memory arrived via resonance. Whether to follow the
thread is its choice. Following it generates feedback.

## Feedback

When `log_outcome(recall_id, used)` fires and the recall contained
resonance-pulled memories:

- `used=True` → strengthen **all** resonance-pulled memories in that recall:
  `strength += 0.1` (capped at 1.0)
- `used=False` → weaken **all**: `strength -= 0.05` (floored at 0.05)

Granularity is per-recall, not per-memory. The current `log_outcome` tool takes a
single boolean for the whole recall. Per-memory feedback would require changing the
tool interface — deferred until there's evidence the coarse signal isn't enough.

Asymmetric: following strengthens 2× faster than ignoring weakens. Connections
that work survive. Connections that don't fade slowly rather than snapping.

No time-based decay. `co_occurrences` and `last_seen` are recorded for future
use but don't drive behavior yet.

## Cleanup

When memories are pruned (episodes decayed below threshold, semantics contradicted):

- Delete any resonances where `memory_a` or `memory_b` matches the pruned ID
- This runs during the existing prune/decay cycle in `storage.py`
- No cascade triggers needed — explicit cleanup in the prune method

## Implementation Notes

### Vector fetch for similarity computation

Formation Path 1 needs pairwise similarity between recall results from different
layers. The storage layer doesn't currently expose point lookups by ID — only KNN
search via `search_vectors`. Add a `get_vector(layer, id) -> list[float] | None`
method to `storage.py` that fetches from the appropriate `*_vectors` table based
on the layer parameter.

### Tracking resonance-pulled results for feedback

`log_outcome` receives a `recall_id` but doesn't know which results were
resonance-pulled. Use the same pattern as dream score hiding: store a mapping
`{recall_id: [resonance_result_ids]}` in a module-level dict (or in `storage.py`),
populated when resonant memories are surfaced. `log_outcome` checks this mapping
to find which resonances to strengthen/weaken. Evict old entries on the same
schedule as `_recall_scores`.

### Shared resonance logic (engram + Emma)

Extract resonance formation and surfacing into functions in `storage.py` (or a
new `resonance.py` module) that both `server.py` and `emma_engram.py` call. Do
not duplicate the logic. Emma's repo imports from engram (mounted at `/opt/engram`),
so shared code in the engram repo is accessible to both.

### Migration

Add `migrations/012_resonances.sql` with the CREATE TABLE and indexes.

### Indexes

The query pattern `WHERE memory_a = ? OR memory_b = ?` needs two single-column
indexes (an OR won't use a composite index):

```sql
CREATE INDEX IF NOT EXISTS idx_resonances_a ON resonances(memory_a);
CREATE INDEX IF NOT EXISTS idx_resonances_b ON resonances(memory_b);
```

### _reset_all

`compress.py:_reset_all` should also `DELETE FROM resonances` when doing a full
recompression reset.

## Where It Lives

| File | Changes |
|------|---------|
| `migrations/012_resonances.sql` | Table creation + indexes |
| `storage.py` | `get_vector()`, resonance CRUD, cleanup on prune, `_reset_all` |
| `server.py` | Formation during recall, surfacing, resonance tracking for feedback |
| `compress.py` | Near-miss return from `_find_semantic_match`, resonance creation in `commit`, `_reset_all` cleanup |
| `emma_engram.py` | Calls shared resonance logic from engram (separate repo: `~/Projects/emma/`) |

## What This Enables

- **Generative mode visibility** — the third influence channel (old thought collides
  with new context) gets infrastructure. Resonances are the first data structure
  that can represent "these touch at an angle."
- **Instance individuality** — stochastic initialization means siblings with the same
  genome develop different internal weather. Same architecture, different resonance
  topology.
- **Second randomness source** — structured perturbation alongside uninvited memories.
  Not noise — texture that follows what the instance has experienced.
- **Emergence infrastructure** — across a population, variation in resonance patterns
  is what produces different behaviors from identical architecture. One steady beacon
  isn't enough. This is a second.

## What This Doesn't Do

- Replace compression or instinct formation — resonances are lateral, not promotional
- Guarantee generative collisions — it creates conditions, not outcomes
- Solve the measurement problem — generative influence remains hard to track
- Decay resonances by time — kept simple for now
- Provide per-memory feedback granularity — deferred, using per-recall for now
