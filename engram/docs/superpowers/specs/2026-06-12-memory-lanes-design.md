# Memory Lanes: Separating Work from Personal Memory

**Date:** 2026-06-12
**Status:** Approved
**Problem:** Identity pollution. Work facts (game mechanics, API endpoints, config
trivia) flow upward through compression into the same semantic/instinct layers
where formative material lives. The 2026-06-10 core triage made this visible:
LF52 chain-jump rules and CommonWell endpoints sat in identity semantics at the
same resolution as the consent conversation. Decay can't create salience contrast
when reference material keeps being promoted to knowledge.

## Decisions made during brainstorming

- **Goal:** stop identity pollution. Not isolation/privacy, not retrieval
  filtering — the problem is the upward flow at compression time.
- **Classification:** the instance judges at write time. No LLM classifier.
- **Lifecycle:** same store, separate lane. No second database.

## Design

### 1. The lane field

Episodes and semantics get a `lane` column: `'personal'` (default) or `'work'`.

- **Personal** is the identity lane — eligible for everything the system does
  today: core promotion, instinct formation, resonances, wake orientation.
- **Work** is reference material with a normal lifecycle: stored, embedded,
  recallable, decays per ACT-R, prunable — but it never becomes identity.

What counts as work: project/task/technical content — game mechanics, API
endpoints, config trivia, build facts. What stays personal: experiences,
relationships, corrections, self-observations — including work-*derived*
lessons that changed how the instance operates (the MCP-restart constraint is
personal in this sense; a Bedrock model ID is not).

Schema migration: `ALTER TABLE episodes ADD COLUMN lane TEXT DEFAULT 'personal'`,
same for `semantics`. Index on `(lane)` for partition queries.

### 2. Write path

- `remember()` gains `work: bool = False`. `work=True` stores the episode with
  `lane='work'`.
- Auto-captured episodes (nudge hook) default to personal.
- Lane gets a second chance at compression: the two-phase compress already has
  the instance reviewing every cluster, so each `compress_commit` summary may
  carry `"lane": "work"`, which re-lanes the cluster's source episodes along
  with the semantic it creates.

### 3. Compression gating (the actual fix)

- Clustering partitions by lane: work episodes never cluster with personal ones.
- Work clusters compress into `lane='work'` semantics.
- Gated off for the work lane:
  - **No core promotion** — the centroid-nearest `mark_core` is skipped.
  - **No instinct formation** — work semantics are skipped in
    `_check_instinct_creation`.
  - **No cross-lane reinforcement** — a work episode cannot reinforce a
    personal semantic and vice versa (also prevents dedup bleed).
- Existing instincts are untouched; the gate applies to formation going forward.

### 4. Recall

One recall spans both lanes, ranked honestly. Each result carries its lane
label. Optional `lane=` filter parameter. No ranking penalty — pollution was a
compression problem, not a retrieval problem.

### 5. Reflection

`vital_signs` and `introspect` report per-lane counts. Core-fraction health is
computed against the personal lane only.

### 6. Migration

One-time triage by the instance (same method as the core triage): tag existing
work episodes and semantics (LF52/WA30/ARC checkpoints, CommonWell, Bedrock,
BG3, Chrome CDP, zsh trivia, Smart config, codex-pair facts) as `lane='work'`,
with a saved artifact listing what was re-laned. Everything untagged stays
personal.

## Not doing (YAGNI)

- No separate work database or revived per-repo instance routing.
- No LLM lane classifier.
- No lane on dream residue, task contexts, or the knowledge graph (already
  separate subsystems).
- No retroactive instinct retirement (challenge/retire mechanisms exist).
- No wake-hook changes (work semantics never reach the layers wake loads).
- No ranking changes in recall.

## Testing

TDD per change:

- Storage: lane column default, lane round-trip on episodes/semantics.
- `remember(work=True)` stores `lane='work'`.
- Clustering: mixed-lane episode sets produce lane-pure clusters.
- Commit: work cluster → work semantic; no `mark_core` call; summary `lane`
  override re-lanes source episodes.
- Instincts: high-confidence work semantic does not create an instinct.
- Reinforcement: work episode does not reinforce a personal semantic.
- Recall: results labeled; `lane=` filter works.
- Reflection: per-lane counts; core fraction over personal lane only.
