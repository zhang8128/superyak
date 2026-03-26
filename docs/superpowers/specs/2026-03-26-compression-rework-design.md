# Compression Rework: Typed Episodes, Multi-Membership, Singleton Promotion

**Date:** 2026-03-26
**Status:** Design

## Problem

179 episodes have produced only 14 semantics. One semantic (the core thesis
about engram and cognition) has 122 of 174 source links (70%). This isn't
because the semantic is wrong — it's the foundational insight and genuinely
connects to most episodes. The problem is that it has no peers. The graph
has one hub and 13 orphans.

The compression pipeline clusters by embedding similarity across all episodes.
This groups reading reactions with design decisions with self-observations
when they share a topic. The resulting clusters are too broad, producing
catch-all semantics or reinforcing existing ones. Themes that deserve their
own semantics never form clusters because they're absorbed into the mega-node.

## Solution

Three changes to the compression pipeline:

1. **Episode typing** — classify episodes before clustering, cluster within types
2. **Multi-semantic membership** — episodes link to all matching semantics, not just one
3. **Singleton promotion** — high-value episodes can become semantics without a cluster

## Episode Typing

New column `kind` on the episodes table. Assigned during compression, before
clustering.

**Types:**
| Kind | Signal |
|------|--------|
| `reading` | source="reading", context contains "passage" or "chapter" |
| `design` | context contains "design", "architecture", "built", "commit" |
| `observation` | context contains "self-observation", "pattern", "noticed" |
| `relational` | content mentions people by name (Andy, Kairos, Vaughn, Emma, Koan) |
| `factual` | content starts with session summaries, build logs, status reports |
| `reflection` | context contains "reflection", "recursive", "philosophical" |

Classification is heuristic — check `context` JSON tags first, `source` field
second, keyword scan on content as fallback. Multiple types can match; the
episode goes into each matching type's clustering pool (an episode can be both
`reading` and `observation`).

No LLM call needed. The existing metadata is sufficient.

**Clustering happens within each type.** A reading reaction about trust and a
design decision about trust produce separate clusters, separate semantics.
Cross-type similarity still exists but is captured by multi-membership, not
by clustering.

## Multi-Semantic Membership

After clustering and semantic creation/reinforcement, each episode in a
cluster gets compared against ALL existing semantics. If similarity exceeds
the reinforce threshold (0.85), a source link is added.

An episode about "reading Mistborn and noticing frame-switching" could link to:
- Its cluster's semantic (reading/perception)
- The core thesis semantic (cognition as retrieval)
- An observation semantic (self-observation patterns)

### Source Link Weights

The `semantic_sources` table gets a `similarity` column (REAL, 0.0-1.0).
This is the cosine similarity between the episode embedding and the semantic
embedding at link time.

### Semantic Neighbors

A new query derives the semantic-to-semantic graph from shared episodes:

```sql
SELECT s2.semantic_id, COUNT(*) as shared_count, AVG(s2.similarity) as avg_sim
FROM semantic_sources s1
JOIN semantic_sources s2 ON s1.episode_id = s2.episode_id
WHERE s1.semantic_id = ? AND s2.semantic_id != s1.semantic_id
GROUP BY s2.semantic_id
ORDER BY shared_count DESC
```

Two semantics that share many episodes are strongly connected. This gives
wander real edges to walk instead of provenance-only paths that collapse
into the hub.

### Transition Graph Integration

The semantic neighbor weights are Markov transition probabilities. Same
TransitionGraph primitive used for instinct transitions and prism frame
transitions. The multi-membership graph is the third instantiation of the
same pattern: weighted sequential attention across different populations.

## Singleton Promotion

Currently compression needs a cluster to create a semantic. Some episodes
deserve promotion alone:

**Candidates:**
- Core episodes with context tags
- Episodes that spawned dream captures
- Episodes marked core at remember-time

**Process:** After multi-link (step 4), any qualifying episode with no
semantic link above 0.85 gets its own semantic at confidence 0.5. It enters
the graph immediately.

If later episodes cluster near a singleton semantic, normal reinforcement
raises its confidence. Singletons that never get reinforced stay at 0.5
and naturally sort lower in recall results.

## Pipeline

```
episodes
  → type (classify by kind)
  → cluster (within each type, existing fclusterdata)
  → create/reinforce semantics (existing logic)
  → multi-link (compare each episode against ALL semantics, add links above 0.85)
  → singleton promotion (core episodes with no links get own semantic)
```

## Files Changed

| File | Change |
|------|--------|
| `compress.py` | Type classification step, per-type clustering loop, multi-link step after commit, singleton promotion step |
| `storage.py` | `similarity` column on `semantic_sources`, `get_semantic_neighbors()` query, `classify_episode_kind()` helper |
| `migrations/` | New migration: add `kind` to episodes, add `similarity` to semantic_sources |

## Files Unchanged

`server.py`, `reflection.py`, `dreaming.py`, `embeddings.py`, `dedup.py`,
`indexer.py`, `watcher.py`, `config.py`.

## Testing

1. Run compression on existing 179 episodes with new pipeline
2. Count semantics produced — target: 25-40 (up from 14)
3. Check graph topology — no single semantic should have >40% of source links
4. Run wander from multiple starting points — should find real paths, not
   collapse into hub within 1 step
5. Check multi-membership: episodes should average 2-3 semantic links
   (up from ~1)

## What This Enables

- Wander has real graph topology to explore
- Recall returns more specific results (semantics are typed, not catch-all)
- The core thesis keeps its centrality but has peers to route through
- Instinct creation has a richer semantic pool to draw from
- The TransitionGraph pattern applies at the semantic layer
- Future: people as semantic anchors (natural extension of multi-membership)
