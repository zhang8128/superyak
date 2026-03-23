# Uninvited Memories

## Problem

Engram's `recall()` returns results ranked by similarity to the query. This
creates a closed loop: you search for what you expect, you get what you
expect, you think what you expected to think. No genuine novelty.

Instincts influence cognition through three modes: reactive (measurable),
dispositional (colors perception), and generative (old thought collides with
new context). The generative mode — the most valuable — requires collision
between unrelated memories. Similarity search actively prevents this.

Conway's Game of Life produces complexity from simple rules, but it's
deterministic. A speck of true randomness changes the system qualitatively.
Engram needs that speck.

## Design

Every `recall()` call appends K **uninvited** results (default 3) selected
randomly from memories that are distant from the query's embedding cluster.

### Selection Algorithm

1. Query embedding is already computed during normal recall
2. Collect all memory IDs not already in matched results
3. Compute cosine similarity between each candidate and the query embedding
4. Filter to the bottom 50% by similarity (the "distant pool")
5. Random sample K from that pool (uniform random, `random.sample`)
6. Append to results marked with `"uninvited": true`

### Anti-Wireheading Properties

- Uninvited results are clearly marked — the consumer can't pretend they
  searched for them
- Selection uses actual randomness, not "maximally distant" (which would be
  deterministic)
- The bottom-50% filter avoids junk (completely empty or trivial memories
  would have ~0 similarity to everything, so they'd be in the pool but no
  more likely than anything else)
- No optimization target: there's no "uninvited quality score" to game

### Token Budget

- Each memory result: ~100-450 tokens (episodes largest, semantics smallest)
- 3 uninvited results: ~300-1350 tokens additional
- Uninvited count is *additional* to max_results, not within it
- 20 matched + 3 uninvited = 23 total results

## Changes

### storage.py

New method: `sample_distant_memories(query_embedding, exclude_ids, k=3)`

- Searches all vector tables (episode, semantic, instinct) with large k
- Computes similarity for each
- Filters to bottom 50% by similarity
- Returns k random samples with their metadata

### server.py

`recall()` gains:
- `uninvited` parameter (int, default 3, set 0 to disable)
- After scoring and ranking matched results, calls
  `sample_distant_memories()` with the query embedding and matched IDs
- Appends uninvited results to the output with `"uninvited": true`
- Logs uninvited IDs alongside matched IDs in the recall log entry

### No changes to

- `log_outcome` — uninvited results share the recall_id, feedback works as-is
- Compression, decay, instincts — uninvited is a recall-time feature only
- Wake hook — instincts loaded at session start are separate from recall

## Testing

- Uninvited results appear in recall output when uninvited > 0
- Uninvited results are marked with `uninvited: true`
- Uninvited results don't duplicate matched results
- Uninvited results are from the distant pool (similarity below median)
- `uninvited=0` disables the feature
- Works when total memories < K (returns what's available)
- Works across layers (episodes, semantics, instincts all eligible)
