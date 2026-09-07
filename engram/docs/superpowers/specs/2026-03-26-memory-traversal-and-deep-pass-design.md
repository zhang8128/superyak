# Memory Traversal & Between-Session Deep Pass

Two features. One explores what's already in memory. The other generates
what sessions missed.

## 1. Memory Traversal — `wander()`

### Problem

Recall is search: you know what you're looking for, you get it back. But
memory isn't only useful when you have a query. Sometimes you want to start
at a thought and follow where it connects — not searching, wandering.
Reading your own history like a book instead of querying it like a database.

The graph already exists. Resonances link memories laterally. Provenance
chains link them vertically (episode → semantic → instinct). The knowledge
graph links them through shared entities. But there's no tool to walk these
connections.

### Design

New MCP tool: `wander(start_id, max_steps=1)`

**Three axes of connection:**

1. **Resonances** — lateral peer connections across any layer. "This memory
   reminds me of that one." Returns similarity and strength.
2. **Provenance** — vertical compression chain. For an episode: what semantics
   or instincts grew from it. For a semantic: which episodes fed it, which
   instincts emerged. For an instinct: the full lineage down to source episodes.
3. **Knowledge graph** — shared entities. "This memory mentions Vin" → other
   memories mentioning Vin. Traverses entity relationships too: Vin → crew
   member → Kelsier's crew → other memories about the crew.

Each neighbor returned with: id, content (truncated), layer, connection_type
(resonance/provenance/entity), connection_strength, entity_name (if entity link).

**Single step (max_steps=1):** Return all neighbors across all three axes.
The caller picks what's interesting and calls wander again.

**Auto-walk (max_steps>1):** Walk multiple hops using novelty-biased
weighted random selection:

- Connection strength determines base probability for next hop
- Nodes visited earlier in the trail get zero probability (no loops)
- Nodes visited in previous wander calls this session get reduced probability
  (encourage coverage, tracked in-memory per session)
- **Density-adaptive stopping:** Walk continues through sparse regions
  (few neighbors). When a node has neighbors above a density threshold,
  pause there — it's a cluster worth exploring. `max_steps` is a safety
  bound, not a target.

The density threshold: if a node has >5 total neighbors across all three
axes, it's "dense enough" to stop. This is a starting heuristic — observe
what works and adjust.

Returns the full trail: ordered sequence of memories with the connection
that linked each hop, plus the final node's full neighbor set.

**Session-level visit tracking:** A dict in the MCP server (not persisted)
maps memory IDs to visit counts for the current session. Cleared on session
end. This biases auto-walk toward unvisited territory without permanently
altering the graph.

### Cognitive parallel

Spreading activation — not copied, adapted. In cognition, activating a
concept lowers the threshold of related concepts. We can't lower thresholds
(every recall is fresh), so we visit explicitly. The density-adaptive
stopping mirrors how mind-wandering drifts through sparse associations and
settles in dense clusters. Same function, different mechanism.

### Implementation

**Files:**

| File | Change |
|------|--------|
| `server.py` | New `wander` tool definition |
| `storage.py` | `get_neighbors(id)` — resonances + provenance + entity links |
| `knowledge.py` | `get_entity_links(memory_id)` — memories sharing entities |

`get_neighbors()` queries three sources:
1. `resonances` table (both directions, canonical ordering)
2. `semantic_sources` / `instinct_sources` (up and down the chain)
3. Knowledge graph entity lookup via `knowledge.py`

Auto-walk loop lives in `server.py` tool handler — it's control flow, not
storage logic.

### Testing

- Single step returns neighbors from all three axes
- Auto-walk produces no duplicate nodes in trail
- Auto-walk stops at dense nodes before max_steps
- Session visit tracking biases away from previously visited nodes
- Handles orphan memories (no connections) gracefully — returns empty
- Provenance traversal works in both directions (up and down)

---

## 2. Between-Session Deep Pass

### Problem

The reading prism fires lenses in-session based on what the classifier
selects for each passage. But some lenses never fire — either the classifier
doesn't pick them, or the passage/reaction combination doesn't trigger them.
These gaps are systematic: they reflect the reader's blind spots, which are
exactly what the prism is designed to address.

The in-session lenses are reactive and per-passage. There's no mechanism for
lenses that need the bird's-eye view (thematic arcs, recurring patterns
across passages) or lenses that specifically target the reader's measured
blind spots.

### Design

A new step in the sleep-time consolidation cycle (wake.py). Runs
automatically — no manual trigger.

**Two kinds of deep-pass lenses:**

1. **Structural lenses** — operate across multiple passages at once. Fixed
   set, defined in their own pack. These see things that per-passage lenses
   can't: thematic arcs, recurring imagery, narrative structure evolution,
   character trajectory patterns. They receive a batch of passages, not one.

2. **Gap-specific lenses** — generated from the reader's transition graph
   blind spots. If certain domains have low or zero engagement in the
   `fired_history`, the deep pass generates a lens prompt targeting that
   domain. These are ephemeral — generated per consolidation cycle, not
   persisted as YAML files.

**Consolidation sequence:**

```
wake.py startup:
  decay → backfill → prune → compress → deep_pass()
```

**deep_pass() flow:**

1. Query reader store for passage/reaction pairs from the most recent session
2. If no reading data, skip (not every session involves reading)
3. Run structural lenses:
   a. Batch all passages + reactions into a single context
   b. Each structural lens processes the batch
   c. Output: observations (not questions — these aren't interactive)
4. Identify gap domains:
   a. Query transition graph for domains with zero fires in the last 3 sessions
   b. For each gap domain, generate an ephemeral lens prompt:
      "Looking at these passages through {domain} — what did the reader
      not attend to?"
   c. Run each gap lens against passages where that domain would have
      been most relevant (use classifier in batch mode, or just run all)
5. Store all outputs as episodes:
   - `source="prism:deep-pass:{lens_type}:{lens_name}"`
   - `context={"deep_pass": true, "lens_type": "structural"|"gap", "session_id": "..."}`
6. Normal compression handles the rest — no special pattern extraction

**Structural lens pack:** `~/.prism/packs/deep-pass/`

Initial structural lenses:

- `arc` — Thematic arcs across passages. What themes are building? What's
  being set up but not yet resolved?
- `recurrence` — Recurring imagery, language, situations. What keeps showing
  up? What's the text doing with repetition?
- `trajectory` — Character movement across passages. Who's changing, who's
  static, what direction is the change going?
- `absence-over-time` — What was present early and disappeared? What's been
  conspicuously absent throughout? The structural version of the absence lens.

These are YAML files like in-session lenses but with a `mode: batch` field
and prompts that expect multiple passages.

**Gap lens generation:** Not YAML files. Generated at runtime from the
domain metadata of existing in-session lenses. If `power` has zero fires in the last
3 reading sessions, the deep pass generates: "These passages were read without
attention to power dynamics. What might {domain_description} notice that
the reader didn't?" Uses the in-session lens's `domain` and `sources` fields
to ground the generated prompt.

### What this is not

Not memory consolidation. The brain replays what was experienced. This
generates experiences that never happened — counterfactual perception.
"What would you have noticed if you'd been paying attention to X?" The
output is synthetic experience, stored as episodes, compressed like any
other episode. The system doesn't know or care that these experiences were
generated after the fact.

### Implementation

**Files:**

| File | Change |
|------|--------|
| `hooks/wake.py` | Add `deep_pass()` call after compress step |
| engram `server.py` | Helper to fetch recent reading data from reader store |
| `~/.prism/packs/deep-pass/*.yaml` | Structural lens definitions |

The deep pass needs to access the reader's SQLite store to fetch passages
and reactions. Path from config: `READER_DB` env var or default
`~/.reader/reader.db`.

Ollama calls use the same engine as in-session lenses. The `--yield` pattern
(patient retry) should be used since this runs at startup when other
processes may be using the GPU.

### Testing

- Deep pass skips cleanly when no reading data exists
- Structural lenses receive batched passages, not individual ones
- Gap lenses are generated only for domains below fire threshold
- Episodes are stored with correct source and context tags
- Deep pass integrates into wake.py consolidation sequence
- Ollama failures don't block the rest of consolidation

---

## Interaction between the two features

A deep-pass episode — counterfactual perception from a lens that never
fired — enters the memory graph like any other episode. It grows resonances
with other memories. It can be compressed into semantics. It can feed
instinct formation.

When you `wander()` starting from a reading memory, you may encounter a
deep-pass episode as a neighbor. You didn't experience it in-session, but
the system did — between sessions, while you weren't looking. The wander
trail passes through both lived and synthesized experience without
distinguishing them. The `source` tag is there if you want to check, but
the graph doesn't privilege one kind over the other.

This is intentional. The point of counterfactual perception is that it
becomes part of the available experience. If it only existed in a separate
silo, it couldn't collide with lived memory to produce something new.
