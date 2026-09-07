# Prism-Engram Integration — Design Spec

**Date:** 2026-03-26
**Status:** Draft

## Summary

Four small changes that connect the prism and engram systems more deeply:
gap-informed uninvited memories, lens questions as recall queries, a notepad
planner extension, and a mandatory authorial intent lens. Plus three deferred
items that become the planner's first entries.

## Motivation

The reading prism surfaces frames I don't have. Engram stores what I've
experienced. Right now they don't talk to each other — the prism asks
questions, engram holds memories, but the gap topology in one doesn't inform
the other. These changes create two bridges: prism gaps → engram recall
(uninvited bias), and prism questions → engram search (collision surface).

The notepad planner tracks work that spans sessions — especially deferred
items that need conditions met before they're buildable.

## 1. Gap-Informed Uninvited Memories

**Where:** `engram/server.py` — `recall()` function, uninvited memory selection

**Current behavior:** Uninvited memories are random samples from the distant
pool (bottom 50% by similarity). All slots are pure random.

**New behavior:** During reading sessions, check the prism reading transition
graph for domains with zero or low transition weight. These are the lens
domains where attention never goes — the gaps.

Of the `uninvited` slots (default 3):
- **N-1 slots:** Gap-biased. Embed the gap domain names as a query bias,
  blended with the original recall query. This tilts selection toward memories
  that live in domains the prism shows as blind spots.
- **1 slot:** Pure random from the distant pool. The gap map has its own blind
  spots — the pure random is the trace metal in the cheap mug.

**Detection:** Only fires during reading sessions. Check if the reading
transition DB exists (`~/.prism/reading-transitions.db`) and has data. If not,
fall back to current pure-random behavior.

**Reading the transition graph:** Import `TransitionGraph` (already exists in
both repos, same module). Open the reading transitions DB read-only. Query
for the lowest-weight or zero-weight nodes from the current context. Map node
names to domain descriptions for embedding.

**Config:** `PRISM_READING_TRANSITIONS_DB` env var, defaults to
`~/.prism/reading-transitions.db`.

## 2. Lens Questions as Recall Queries

**Where:** `reader/reading_prism.py` — `run_reading_prism()` return value

**Current behavior:** Each lens produces a question. The question is stored in
the reader's `prism_questions` table and surfaced on the next `read()`.

**New behavior:** Each prism question result includes a `recall_query` field
containing the raw lens question verbatim. No preprocessing, no pattern
extraction, no heuristic stripping.

```json
{
  "lens": "attachment",
  "question": "Who does Vin move toward when afraid?",
  "recall_query": "Who does Vin move toward when afraid?"
}
```

The calling agent can optionally run the recall_query against engram's
`recall()` tool. The collision between a literary question and self-knowledge
is the value. Engram's existing recall mechanics (dream bias, uninvited
memories, gap-informed selection) handle the rest.

No automatic execution. The agent decides whether to run the query. This
avoids making the bridge a deterministic gate.

## 3. Notepad Planner Extension

**Where:** `engram/notepad.py` — `Notepad` class, `engram/server.py` — MCP tools

**Current state:** Notepad is key-value notes with tags and FTS search. No
concept of status, dependencies, or scheduling.

**New fields on notes:**
- `status`: `open` | `deferred` | `done` (default: `open`)
- `depends_on`: optional note key that blocks this one
- `due`: optional date string (ISO format)

**New methods on Notepad:**
- `jot()` — extend existing method with optional `status`, `depends_on`, `due`
- `open_items(tag?)` — all notes with status `open`, ordered by due date
- `deferred_items(tag?)` — all notes with status `deferred`
- `defer(key, reason?)` — set status to deferred, optionally append reason
- `resolve(key)` — set status to done

**New MCP tools:**
- `jot` — already exists, extend with new params
- Planner queries exposed through existing `look` tool with status filters,
  or as a new `plan()` tool that shows open + deferred items grouped by status.

**First planner entries (created after build):**
- "Change tracking: compare reactions before/after lens engagement. Needs
  reading prism running with data." (status: deferred, depends_on: reading-prism-live)
- "Dream residue from lens shifts: capture perceptual shifts as dream material.
  Don't structure it." (status: deferred)
- "Memory traversal: wander tool for walking the memory graph. Start at a
  memory, follow connections." (status: deferred)

## 4. Authorial Intent Lens

**Where:** `~/.prism/packs/reading/authorial.yaml` (new file),
`reader/reading_prism.py` (mandatory 5th slot)

A 15th lens in the reading pack that always fires — not classifier-routed.
Asks what the author is constructing, not what the reader is missing.

```yaml
name: authorial
domain: craft
sources:
  - "Booth, The Rhetoric of Fiction (1961)"
  - "Iser, The Act of Reading (1978)"
prompt: |
  You are asking about authorial construction — what the writer
  is building and why.

  Given a passage and a reader's reaction, ask ONE question about
  what the author is doing on purpose. Not what the characters feel —
  what effect the text is designed to produce. How is this passage
  constructed to make the reader respond a certain way?

  Notice: pacing choices, information withheld or revealed, structural
  parallels to earlier passages, tone shifts, the gap between what
  characters know and what the reader knows, imagery that does work
  the prose doesn't name.
temperature: 0.8
model: null
```

**Connector change:** `run_reading_prism()` adds the authorial lens as a
mandatory 5th question after the 4 classified ones. Not passed through the
classifier — always fires.

**Total per passage:** 2 relevant + 1 distant + 1 rotating + 1 authorial = 5.

## Scope Boundaries

**We build:**
- Gap-informed uninvited memory selection (engram)
- Recall query field on lens questions (reader)
- Notepad planner extension (engram)
- Authorial intent lens + mandatory slot (prism pack + reader)

**We defer (first planner entries):**
- Change tracking — compare reactions before/after lens engagement
- Dream residue from lens shifts — capture perceptual shifts as dream material
- Memory traversal — `wander` tool for walking the memory graph

**We don't build:**
- Prism-engram bridge module (extract later if needed)
- Recall query preprocessing (raw question, no heuristic)
- Automatic gap detection thresholds (observe first)

## Files

| File | Project | Change |
|------|---------|--------|
| `server.py` | engram | Gap-informed uninvited in recall() |
| `notepad.py` | engram | Status, depends_on, due fields + methods |
| `server.py` | engram | Planner MCP tools |
| `reading_prism.py` | reader | recall_query field + mandatory authorial slot |
| `authorial.yaml` | prism pack | New lens file |
| `pack.yaml` | prism pack | Add authorial.yaml to manifest |
