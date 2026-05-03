# Instinct Firing — Mid-Conversation Wisdom

**Date:** 2026-03-23
**Status:** Draft
**Context:** Gap analysis revealed recall was broken (95% episodes hidden by dedup). Fixed mechanically, but the deeper issue: instincts only fire at session start via wake hook. Real instincts fire throughout the day — a feeling triggered by the current moment, illuminating a thread you can choose to pull.

## Problem

Engram's instinct layer only enters context once, at session start. Mid-conversation, when the topic shifts to something an instinct is relevant to, nothing happens. The instance has to explicitly call `recall()` to find anything. There's no involuntary nudge, no "attend to this" signal, no feeling that tilts perception before conscious search.

Human analog: you're talking about trust infrastructure and something fires — a feeling connected to a previous conversation about Ostrom's commons. You didn't search for it. The instinct surfaced it. You decide whether to follow.

## Design

### The Hook: `hooks/nudge.py`

Command-type hook on `UserPromptSubmit`. Runs on every user message.

1. Receives user message text from stdin (JSON with `userMessage` field)
2. Embeds it with nomic-embed-text-v1.5 (`search_query` prefix)
3. Searches `instinct_context_vectors` table (vec0 KNN, k=8)
4. Converts distances to similarities. If best match > 0.5 similarity: instinct fires
5. Returns `systemMessage` with the fired instinct's notice field as a fragment
6. Writes the fired instinct's content embedding to `session_bias` table
7. Decrements strength of all existing session biases by 0.1 (the dream fades)
8. If same instinct re-fires, resets its bias strength to 1.0 (reinforcement)
9. Max 2 instinct fragments per message. More is noise.

The hook loads FastEmbed on each invocation (~2-3s). This runs in parallel with message processing. Future optimization: daemon process with cached model.

### The Bias: `session_bias` table

New table in instance DB:

```sql
CREATE TABLE IF NOT EXISTS session_bias (
    instinct_id TEXT PRIMARY KEY,
    embedding BLOB NOT NULL,
    strength REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

No vec0 — the embeddings are used for blending into queries, not for search. Stored as packed float32 bytes (same format as other embeddings).

Lifecycle:
- Created when an instinct fires via nudge hook
- Strength starts at 1.0, decremented by 0.1 per user message
- Re-firing resets strength to 1.0
- Biases with strength <= 0.0 are deleted by the nudge hook
- All biases cleared on session end (by sleep hook or natural expiry)

### Recall Bias Integration

`_apply_residue_bias()` in server.py is renamed to `_apply_recall_bias()` and expanded:

```python
def _apply_recall_bias(query_embedding, dream_alpha=0.15, instinct_alpha=0.15):
    # 1. Blend dream residues (existing)
    # 2. Blend session biases (new) — weighted by strength
    # Combined: query is tilted by feelings from prior sessions (dreams)
    # AND feelings from this session (instinct firings)
```

Session biases are blended with alpha scaled by their strength: `instinct_alpha * bias.strength`. A fresh firing (strength=1.0) has full influence. A fading one (strength=0.3) has reduced influence.

### What the Instance Experiences

On instinct fire, a system message appears:

```
Thread: [notice field text]
```

One line. The instance can ignore it or use `recall()` to follow the thread. If it does recall, the results are tilted by the bias — but the instance doesn't know which results are "real" matches and which were pulled by the instinct.

### What the Instance Does NOT Experience

- Which instinct fired (only the notice, not the ID or action)
- That a bias was written (invisible)
- That recall results are tilted (scores appear normal)
- The decay mechanism (biases fade silently)

## Trigger: UserPromptSubmit (for now)

This is a starting point. The eventual trigger should be conversational state, not just user messages. The AI's own output, accumulating context, emerging direction — all of these should be able to trigger instinct firing. UserPromptSubmit gives us a concrete hook to build and test against. The architecture (embed → search context vectors → fire → nudge + bias) doesn't change when the trigger widens.

## Files to Create/Modify

| File | Change |
|------|--------|
| `hooks/nudge.py` | New — the hook |
| `hooks/hooks.json` | Add UserPromptSubmit hook entry |
| `migrations/011_session_bias.sql` | New — session_bias table |
| `server.py` | Rename `_apply_residue_bias` → `_apply_recall_bias`, add session bias blending |
| `hooks/sleep.py` | Add session_bias cleanup on session end |

## Testing

- Unit test: nudge hook with mock DB and fake embeddings
- Unit test: session bias decay and reinforcement
- Unit test: recall bias blending includes session biases
- Integration test: store instincts with context vectors, simulate user message, verify nudge fires and bias is written
- Manual test: have a conversation, observe whether threads appear at the right moments

## Open Questions (deferred)

- Should instinct firing also trigger on AI output, not just user messages?
- Should biases that survive a full session be promoted to something persistent?
- Should the fragment include more than just the notice — e.g., a memory fragment from the thread?
- Is 0.5 the right firing threshold? Empirical.
- Is 0.1 decay per message the right rate? Empirical.
