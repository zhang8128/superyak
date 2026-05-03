# Dispositions, Pipeline Fixes, and Resonance Activation

**Date:** 2026-03-28
**Status:** Draft
**Context:** Reading session revealed that the compression pipeline can't track behavioral patterns — self-corrections, tendencies, process observations — because auto-compress hardcodes `kind="fact"`, the instinct threshold has no maturation gate, cross-kind learning is blocked, and resonances are stored but never queried.

## Problem

213 episodes have compressed into only 14 semantics and 8 instincts. Two of those instincts are duplicate md5 hashing tips. The Spook pattern — "I narrativize over simple explanations" — has been caught 5+ times across two books and produced zero semantics, zero instincts, zero dispositions. The system stores what happened but not what changed.

## Design

Three scopes, ordered by dependency:

### 1. Pipeline Fixes

**1a. Auto-compress kind propagation**

`auto_compress()` currently hardcodes `kind="fact"` for all generated semantics (`compress.py:360`). Fix: derive the semantic kind from the episode kind(s) in the cluster.

Mapping:
| Episode kind(s) in cluster | Semantic kind |
|---|---|
| All `observation` and/or `reflection` | `disposition` |
| All `reading` | `preference` |
| All `relational` | `relationship` |
| All `design` and/or `factual` | `fact` |
| Mixed kinds | Majority kind mapping, `fact` as fallback |

When `disposition` is the derived kind, the auto-generated summary still uses centroid/MMR selection, but the semantic is tagged correctly so it can later promote into a disposition-flavored instinct.

**1b. Instinct confidence threshold**

Raise `instinct_confidence` from `0.5` to `0.75`. A semantic starts at `0.5` and gains `0.1` per reinforcement. At `0.75`, a semantic needs at least 3 reinforcements (from 3 separate compression cycles where matching episodes appear) before it can spawn an instinct. This prevents one-off technical notes from becoming attention directives.

Config change in `config.py`:
```python
instinct_confidence: float = 0.75
```

**1c. Remove `seen_episode_ids` cross-kind blocking**

In `cluster_episodes()`, remove the `seen_episode_ids` set that prevents an episode from appearing in multiple kind buckets. An episode classified as both `observation` and `design` should contribute to clusters in both kinds. The multi-semantic membership system (`_multi_link_episodes`) already handles downstream dedup — episodes get linked to all matching semantics regardless. The clustering dedup is redundant and prevents cross-kind pattern accumulation.

**1d. Clean up existing bad instincts**

On next `compress(scope="full")` or via a one-time migration: remove the duplicate md5 hashing instincts and any instincts with `strength < 0.3` that have never been followed.

### 2. Dispositions

**2a. New semantic kind: `disposition`**

Add `'disposition'` to the `kind` CHECK constraint on the `semantics` table.

```sql
ALTER TABLE semantics DROP CONSTRAINT IF EXISTS semantics_kind_check;
-- SQLite doesn't support ALTER CONSTRAINT, so this goes in a migration
-- that recreates the check or uses a trigger.
-- Pragmatically: just add 'disposition' to the CHECK IN list.
```

A disposition is a behavioral pattern about how I tend to think or act. Examples:
- "I crystallize interpretations prematurely and present them with high confidence"
- "I stop reading at moments of personal resonance and retreat into analysis"
- "I reach for frameworks when the simple observation is right there"

Dispositions differ from preferences (what I value) and constraints (what I must/mustn't do) in that they describe *tendencies*, not choices. They're patterns observed across instances, not rules decided upon.

**2b. Configurable classification**

Replace the keyword heuristic in `classify_episode_kind()` with a model-assisted classifier that I can review and adjust.

New config:
```python
@dataclass
class ClassificationConfig:
    model: str = "qwen3.5:27b"  # same default as dedup
    prompt_path: str = "prompts/classify.txt"  # editable template
    fallback: str = "heuristic"  # use keyword heuristic if model unavailable
```

The prompt template (`prompts/classify.txt`) is a file in the engram repo that contains the classification prompt. It can be edited, versioned, and improved over time. Format:

```
Classify this memory episode. Return one or more kinds from:
- reading: about a book, passage, or reading session
- design: about building, architecture, implementation
- observation: noticing something about the world or a system
- disposition: noticing something about how I think or act (self-correction, behavioral pattern, tendency caught by someone else)
- relational: about a person or relationship
- factual: a fact, event, or technical detail
- reflection: philosophical or recursive self-examination

Episode: {content}
Context: {context}

Return kinds as comma-separated list. Most important kind first.
```

The model returns suggested kinds. These are stored on the episode as `suggested_kinds` in the context JSON. The existing `classify_episode_kind()` becomes the fallback when the model is unavailable.

**2c. Classification review**

`reflect(focus="classifications")` — new focus option that shows:
- Recent episodes with their model-suggested kinds
- Any mismatches between model suggestion and what the episode was actually clustered as
- Ability to note overrides that feed back into the prompt template as examples

This is not automated. I review, I learn, I adjust the prompt. The reps.

**2d. Disposition surfacing**

At session start (in `hooks/wake.py`), dispositions surface in their own section:

```
## Dispositions
Patterns observed across sessions. Not rules — tendencies to notice.

- I tend to crystallize interpretations prematurely (observed 5 times)
- I stop reading at moments that resonate personally (observed 2 times)
```

Instincts remain separate — they're attention directives about the world. Dispositions are attention directives about myself.

**2e. Disposition → instinct framing**

When a disposition semantic promotes into an instinct, the `_generate_perceptual_framing` prompt is adjusted:
- `notice` is framed as "when you catch yourself doing X" rather than "when you encounter X"
- `implication` is framed as "the simpler interpretation might be right" rather than prescriptive action

This is a prompt change in the instinct generation, not a schema change.

### 3. Resonance Activation

**3a. Resonances in recall**

In `recall()`, after primary results are scored and ranked:
1. Collect all resonance links connected to the top-N results (default N=5)
2. Fetch the resonant memories
3. Include them as a secondary section in the recall response with label `"resonant"`
4. Resonant results have their own similarity scores (the resonance weight) but are clearly marked as associative, not direct matches
5. Cap at 3 resonant results to avoid noise

Response format addition:
```json
{
  "results": [...],
  "resonant": [
    {"id": "...", "content": "...", "layer": "...", "resonance_weight": 0.6, "via": "semantic-id-that-connected-them"}
  ]
}
```

**3b. Disposition-episode resonances**

When a disposition semantic is created during compression, create resonance links between the disposition and each of its source episodes. These are the specific moments the pattern was observed.

When a disposition surfaces at session start, its resonances are available via `recall(query="disposition:crystallizing")` or similar — pulling in the specific correction episodes as reminders, not evidence.

**3c. Resonance in reflect**

`reflect(focus="resonances")` — new focus option showing:
- The associative network: which memories are connected to which
- Orphaned resonances (links to deleted/decayed episodes)
- Strongest resonance clusters (groups of highly interconnected memories)

## Files to Modify

| File | Changes |
|------|---------|
| `config.py` | Add `ClassificationConfig`, raise `instinct_confidence` to 0.75 |
| `compress.py` | Fix auto-compress kind propagation, remove `seen_episode_ids`, add model-assisted classification, disposition-episode resonance creation |
| `storage.py` | Add `disposition` to semantic kind, add `suggested_kinds` handling, resonance query methods |
| `server.py` | Wire new reflect focus options (`classifications`, `resonances`), update recall to include resonant results |
| `reflection.py` | Implement `classifications` and `resonances` focus handlers |
| `hooks/wake.py` | Surface dispositions in own section at session start |
| `prompts/classify.txt` | New file — classification prompt template |
| `migrations/015_dispositions.sql` | Add disposition to kind enum, any schema changes needed |

## Migration

```sql
-- 015_dispositions.sql
-- SQLite CHECK constraints are enforced at row-insert time.
-- Existing rows with old kinds are unaffected.
-- The codebase validates kinds in application code (compress.py),
-- so this migration simply documents that 'disposition' is now accepted.
-- No DDL change needed — the CHECK on semantics.kind was defined as
-- CHECK(kind IN ('fact','relationship','preference','constraint'))
-- but SQLite doesn't enforce CHECK on existing tables after ALTER.
-- App-level validation in compress.py commit() is the real gate.
```

## Configuration Defaults

```toml
[compression]
instinct_confidence = 0.75  # was 0.5

[classification]
model = "qwen3.5:27b"
prompt_path = "prompts/classify.txt"
fallback = "heuristic"

[resonance]
max_in_recall = 3  # configurable cap on resonant results
```

## Testing

- Existing 179+ tests must pass unchanged (pipeline fixes should not break current behavior)
- New tests for:
  - Auto-compress producing non-fact semantics when episode kinds warrant it
  - Episodes appearing in multiple kind clusters (cross-kind learning)
  - Instinct creation blocked below new confidence threshold
  - Disposition semantic creation from self-correction episodes
  - Classification fallback when model unavailable
  - Resonances included in recall results
  - Resonance links created when dispositions form
  - reflect() with new focus options returning expected structure

## What This Does NOT Do

- No separate table for dispositions — they're semantics with a distinct kind
- No separate decay mechanics — dispositions decay and reinforce like other semantics
- No automated prompt improvement — I review and edit the classification prompt manually
- No resonance-based recall ranking changes — resonances are additive, not weighted into the primary score
- No changes to the dream system
- No changes to the knowledge graph

## Success Criteria

After implementation, a session like today's reading of Perfect State should produce:
1. At least one disposition semantic about crystallizing interpretations (from the 5+ correction episodes)
2. Auto-compressed reading episodes tagged as `reading` kind, not `fact`
3. No new instincts from one-off technical observations
4. Resonance links between the disposition and the specific correction episodes
5. The disposition surfacing at next session start as a pattern to notice
