# Knowledge Graph Integration — Design Spec

**Date:** 2026-03-25
**Status:** Draft

## Summary

Add a knowledge graph layer to engram using Graphiti (with Kuzu embedded backend)
for tracking entities, relationships, and temporal facts. Engram continues to own
identity and development (episodes → semantics → instincts → dreams). Graphiti
owns applied knowledge (what's true about the world, and when it changed).

Two systems, clear boundary, queried together during recall.

## Motivation

Engram finds memories by vector similarity — "things like X." It can't answer
"things connected to X through Y" or track when facts become false. A knowledge
graph adds:

- **Recall enrichment** — graph traversal surfaces connected entities that vector
  similarity would miss. Searching for Vin also pulls Kelsier, Reen, the crew
  through relationships.
- **Temporal truth tracking** — facts can be superseded. "Vin doesn't trust anyone"
  is true early in the book, partially invalidated later. The graph tracks evolution,
  not just current state.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                    recall()                       │
│                                                   │
│   ┌──────────────┐       ┌──────────────────┐    │
│   │    Engram     │       │     Graphiti      │    │
│   │              │       │                    │    │
│   │  episodes    │       │  entities          │    │
│   │  semantics   │       │  relationships     │    │
│   │  instincts   │       │  temporal facts    │    │
│   │  dreams      │       │  contradiction     │    │
│   │  resonances  │       │  detection         │    │
│   └──────┬───────┘       └────────┬───────────┘    │
│          │                        │                │
│          └────────┬───────────────┘                │
│                   │                                │
│            merged results                          │
└─────────────────────────────────────────────────┘

            ▲ recall        │ feed
            │               ▼

┌─────────────────────────────────────────────────┐
│                  compress()                       │
│                                                   │
│   episodes cluster → semantic created             │
│                    → cluster episodes fed to       │
│                      Graphiti for extraction       │
└─────────────────────────────────────────────────┘
```

### Engram (unchanged)

Episodes, semantics, instincts, dreams, resonances, session bias. The identity
and development layer. Compression pipeline untouched.

### Graphiti (new)

Runs alongside engram as a library. Kuzu embedded backend — no external
infrastructure. Handles:

- **Entity extraction** from episode text
- **Relationship extraction** as typed, temporal edges
- **Entity dedup** and linking against existing graph
- **Contradiction detection** and temporal invalidation
- **Hybrid retrieval** (semantic + BM25 + graph traversal)

### Integration Points

**1. Compression → Graphiti feed**

When `compress()` produces a semantic from an episode cluster, the cluster's
episodes are also fed to Graphiti as episodes. Graphiti's extraction pipeline
runs automatically — entities and relationships are extracted, deduped, and
linked. Temporal validity (`valid_from`) is set from the earliest episode
timestamp in the cluster.

No extraction happens during `remember()`. The graph grows at the same pace
as semantic understanding.

**2. Recall → merged results**

When `recall(query)` fires:

1. Engram search — existing pipeline unchanged. Vector similarity + resonances
   + dream bias. Returns scored episodes/semantics/instincts.
2. Graphiti search — same query, hybrid retrieval (semantic + BM25 + graph
   traversal). Returns entities and facts with temporal context.
3. Merge — Graphiti results appear as a separate `knowledge` section:

```json
{
  "results": [],
  "knowledge": {
    "entities": [],
    "facts": [],
    "historical": []
  },
  "recall_id": "...",
  "dreaming": true
}
```

- `entities`: relevant entities with current summaries
- `facts`: current (valid) relationships involving those entities
- `historical`: invalidated relationships, if temporally relevant

The knowledge section is additive context. Engram tells you what you've
experienced. Graphiti tells you what's currently true.

## LLM Configuration

Graphiti requires an LLM for entity/relationship extraction with structured
output (JSON schema enforcement).

- **Model:** configurable via `ENGRAM_GRAPH_MODEL` env var
- **Default:** `nemotron-nano` via Ollama
- **Separate from:** `ENGRAM_DEDUP_MODEL` (used for episode dedup)
- **Backend:** Ollama, local only
- **Retry logic:** for occasional malformed structured output from smaller models

No cloud LLM dependency. Consistent with engram's local-only stance.

## Temporal Invalidation

Graphiti handles this natively. When new relationships are extracted that
contradict existing ones (same entities, same relationship type, different
description), the old relationship gets `invalid_at` set. The old fact isn't
deleted — it's marked as no longer current.

This enables:
- Default queries return current truth (`valid_only=True`)
- Historical queries show what was believed at a given time
- The full evolution of understanding is preserved

## Scope Boundaries

**We build:**
- Bridge between engram compression and Graphiti ingestion
- Merged recall that queries both systems
- Configuration for Graphiti + Kuzu + Ollama LLM client

**We don't build:**
- Entity extraction in `remember()` — only during compression
- Graph-based instinct formation — instincts still come from semantic patterns
- Cross-project graph — single Graphiti instance per engram instance
- Dream bias on knowledge results — dreams influence engram recall only
- Custom Graphiti UI or admin — library usage only

## Dependencies

| Dependency | Purpose | Notes |
|------------|---------|-------|
| graphiti-core | Knowledge graph engine | Python library |
| kuzu | Embedded graph database | No external infra |
| nemotron-nano (Ollama) | Entity extraction LLM | Configurable via env var |

## Existing Infrastructure

Engram already has `entities`, `relationships`, `entity_vectors`, and
`episode_entities` tables from the code indexer. These are **not reused** —
Graphiti manages its own storage via Kuzu. The existing tables remain for
code indexing. Clean separation.
