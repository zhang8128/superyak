# Generic Evolving-Category Memory — Design Specification

**Date:** 2026-08-07

**Status:** Approved implementation direction; shadow acceptance pending

**Scope:** First falsifiable implementation in `engram`

## Purpose

Build a generic memory substrate whose categorical organization can change over
time. Context does not merely select among fixed graphs. Experience may propose
new distinctions, relations, equivalences, mergers, and retirements; periodic
consolidation commits justified structural changes while retaining the complete
history.

The first implementation must point toward an evolving higher-category system
without attempting an unbounded higher-category runtime. It must be safe to run
beside the existing memory system, measurable before it influences recall, and
bounded in RAM even when its disk archive grows very large.

## Existing System and Baseline

Engram already has several compatible pieces:

- `categories.py` stores cells and vector embeddings in `categories.db`.
- Useful recalls create level-1 application cells.
- Similar applications compose into level-2 cross-domain-transfer cells.
- `graph.py` supplies a unified view over existing memory relationships.
- `sheaf.py` detects local cohesion failures and performs gated subdivision.
- `persistence.py` distinguishes persistent structure from noise.
- The memory ledger, provenance links, cold storage, task contexts, and
  consolidation cycle already provide evidence and lifecycle machinery.

The active instance currently contains 1,460 legacy category cells: 171 at
level 1 and 1,289 at level 2. It has no stored level-0 cells. The 171 level-1
cells point directly at external memory IDs, so their missing category-cell
references are intentional under the legacy representation.

The current category store is useful experimental evidence, but it does not yet
model categorical evolution:

- `level` conflates categorical dimension with composition depth;
- cells lack explicit types, epochs, typed weights, lifecycle, and rewrite
  provenance;
- composition always raises the level, although categorical composition of two
  1-morphisms normally remains a 1-morphism;
- source and target boundaries are not validated;
- the category is appended to, but changes to the category itself are not
  represented;
- retrieval is an unweighted vector search over level-2 cells.

This implementation extends that experiment rather than replacing the unified
memory graph, sheaf, persistence, or Graphiti layers.

## Design Decision

Implement an **event-sourced, context-weighted weak 2-category in shadow mode**.

- Interpret dimensions 0, 1, and 2.
- Permit higher-dimensional records in the disk format but treat them as opaque.
- Represent every structural change as an immutable rewrite from input cells to
  output cells.
- Preserve forks rather than forcing a single current ontology.
- Compile a small context-dependent working category from disk; never load the
  archive as an in-memory graph.
- Keep arbitrary computation in separately budgeted operators. Category cells
  may describe executable rules, but they do not grant execution authority.
- Treat a clean process boundary as the only supported runtime upgrade path.
  In-process `importlib.reload(server)` is unsupported: the supervisor stops the
  old process, exact-owned resources close in dependency order, and a fresh
  process constructs the next generation from disk.

The infinity-category is an extension direction, not a claim about the first
runtime.

## Generic Kernel

No domain concept such as book, repository, conversation, or task is built into
the substrate. The kernel contains only:

1. **Cell** — an immutable object of dimension `n >= 0` with content and
   provenance.
2. **Boundary** — an ordered source or target boundary of a cell.
3. **Context** — an immutable sparse feature map identifying a local situation.
4. **Weight observation** — a typed assessment of a cell in a context.
5. **Rewrite** — an immutable proposal or committed mapping from input cells to
   output cells.
6. **Epoch** — a committed categorical version with one or more parents.
7. **Snapshot** — a regenerable materialization of an epoch for fast reads.

Types and composition rules are represented by cells and relations rather than
hard-coded domain enums. The implementation may use internal storage labels, but
those labels have no domain semantics.

### Interpreted dimensions

- **0-cells:** entities, memories, concepts, contexts, conventions, types, or
  rules.
- **1-cells:** directed typed relationships between 0-cells.
- **2-cells:** witnesses that two paths agree, conflict, refine one another, or
  participate in a structural rewrite.
- **3+-cells:** stored and returned as opaque records; v1 does not validate their
  categorical meaning or use them for online traversal.

An ordered boundary list lets a 2-cell relate paths rather than only individual
arrows. Dimension and composition depth remain separate fields.

## Temporal Morphogenesis

Let `C_e` be the category visible at epoch `e`. Evolution is a DAG rather than a
single mutable chain:

```text
C0 ──rewrite──> C1 ──rewrite──> C2
 └──────alternative──────────> C2b
```

A rewrite contains input cells, output cells, witnesses, evidence event IDs,
the proposing context, and its disposition:

- `proposed`
- `committed`
- `rejected`
- `superseded`

The primitive operation is a general input-to-output rewrite. Create, retire,
retype, split, and merge are conventions over that primitive:

- create: no inputs, one or more outputs;
- retire: inputs, no active outputs;
- retype: old cell to replacement cell plus a lineage witness;
- split: one input to multiple outputs plus maps home;
- merge: multiple inputs to one output plus provenance maps.

Cells and committed rewrites are never updated in place. Corrections append new
cells and rewrites. A snapshot identifies what is active at an epoch but remains
reconstructable from the event history.

### Two-stage structural learning

Experiences may create proposals immediately. Only periodic consolidation may
commit structural rewrites.

A proposal is eligible to commit when:

- all referenced evidence and boundaries exist;
- dimensional boundary rules hold for dimensions 0–2;
- it reduces a measured cohesion failure or has explicit correction evidence;
- its distinction survives the configured persistence/noise check;
- every split or merge records lineage back to its inputs;
- the description-length gain exceeds its complexity cost;
- it fits the per-pass structural budget.

An explicit user correction may supply sufficient evidence by itself, but it
still passes integrity and transaction checks. An LLM may propose content; it
cannot directly commit a rewrite.

Consolidation runs at session sleep and may also run after a configurable number
of new events. It never runs inside latency-sensitive recall.

## Generic Context and Boundaries

A context is a sparse weighted feature map. Conventional feature namespaces are
allowed but optional:

- goal or intent;
- active entities;
- participants or agents;
- tools and resources;
- source or environment;
- temporal horizon;
- attention state.

There is no `book_id`, `repo_id`, or other domain-specific field in the kernel.
Applications express those facts as ordinary features.

The v1 boundary detector uses only generic signals:

```text
boundary_score =
    0.40 * goal_divergence
  + 0.20 * entity_turnover
  + 0.15 * participant_tool_turnover
  + 0.15 * source_change
  + 0.10 * temporal_discontinuity
```

An explicit boundary event always creates a hard boundary. An inferred hard
boundary requires a score of at least `0.65` on two consecutive observations.
A score of `0.35` begins a soft transition: the new context gains weight while
the old one decays gradually. These defaults are calibration hypotheses and stay
shadow-only until evaluated.

Contexts may overlap and nest. A boundary changes activation; it does not retire
cells or erase the prior context.

## Typed Weights and Surfacing

Each weight observation preserves seven independent channels:

| Channel | Range | Meaning |
|---|---:|---|
| relevance | 0..1 | fit to the active context |
| evidence | 0..1 | support and provenance quality |
| recency | 0..1 | current temporal availability |
| affect | -1..1 | signed valence; magnitude contributes salience |
| adoption | 0..1 | scoped agreement or convention uptake |
| novelty | 0..1 | distance from already active material |
| cost | 0..1 | estimated retrieval/rendering expense |

The vector remains stored intact. A versioned valuation policy produces a
surfacing score at query time. Every compiled result records the policy version
and component contributions, so a retrieval decision can be explained and
replayed. Truth, agreement, emotion, and relevance are never collapsed in
persistent storage.

## Working-Category Compiler

For context `c`, epoch `e`, and budget `B`, the compiler produces a bounded view:

```text
W(e, c, B) = compile(history, epoch=e, context=c, budget=B)
```

The compiler:

1. Seeds candidates from direct semantic/vector matches and explicit context
   membership.
2. Traverses relevant 1- and 2-cells from disk indexes.
3. Translates historical cells through committed rewrite lineage.
4. Scores candidates with the versioned context valuation.
5. Applies diversity selection so one dense category cannot consume the view.
6. Packs provenance-linked capsules to the requested token and cell budgets.

V1 hard limits:

- maximum interpreted dimension: 2;
- maximum traversal depth: 4;
- maximum expanded neighbors per cell: 64;
- maximum candidate cells per compile: 50,000;
- normal rendered target: 36,000 tokens;
- forced rotation watermark: 40,000 tokens;
- absolute logical ceiling: 65,536 tokens;
- maximum committed rewrites per consolidation pass: 32;
- maximum inputs or outputs per rewrite: 32 each;
- maximum active alternative branches at one structural locus: 4.

All additional proposals and opaque higher cells remain on disk. Limits affect
interpretation and activation, not archival retention.

The existing local-model governor remains authoritative for the 112 GB process
ceiling. Engram supplies budgeted capsules; it does not estimate MLX allocation
from first principles.

## Persistence and Disk Budget

The v2 experiment uses a separate `categories_v2.db`. It does not alter
`categories.db` during shadow evaluation.

Persist:

- raw category events;
- cells and ordered boundaries;
- contexts and weight observations;
- proposals and committed rewrites;
- epoch-parent relationships;
- lineage and provenance;
- periodic snapshots and indexes.

Snapshots, embeddings, and secondary indexes are derived and may be rebuilt.
Raw events, cells, committed rewrites, and provenance are immutable.

The archive receives a configurable hard quota. The recommended default for the
available 4 TB volume is the lower of 3 TB or 75% of the assigned filesystem.
At the high-water mark, the system stops producing derived snapshots and vector
duplicates first. If the hard quota is reached, category writes fail closed and
the existing engram recall path continues without category evolution. The
system never fills the volume or silently deletes immutable history.

## Storage Schema

The shadow database uses prefixed tables so schema intent remains explicit:

- `cat_schema_version`
- `cat_events`
- `cat_cells`
- `cat_boundaries`
- `cat_contexts`
- `cat_weight_observations`
- `cat_rewrites`
- `cat_rewrite_members`
- `cat_epochs`
- `cat_epoch_parents`
- `cat_snapshots`
- `cat_vectors`

Foreign keys are enabled. Committing a rewrite, creating its epoch, attaching
members, and recording epoch membership occurs in one transaction. Cell rows
remain immutable; active membership is derived from the selected epoch and its
rewrite history.

The legacy importer creates proxy 0-cells for external memory IDs, imports
level-1 cells as 1-cells, and imports level-2 transfers as 2-cells. Import is
idempotent and content-addressed. It emits a validation report before writing
and never modifies the legacy database.

## Components

Follow the repository's flat-module organization:

| Component | Responsibility |
|---|---|
| `categories.py` | Preserve `CategoryStore`; add immutable v2 cell and storage primitives |
| `category_evolution.py` | Proposals, validation, consolidation, epochs, replay |
| `category_context.py` | Sparse contexts, divergence, soft/hard boundaries |
| `category_compile.py` | Indexed traversal, valuation, diversity, budget packing |
| `config.py` | Shadow-mode, quotas, thresholds, and structural budgets |
| `reflection.py` | `reflect(focus="category_evolution")` diagnostics |
| `server.py` | Non-fatal initialization, shadow observation wiring, and exact process-lifetime cleanup |
| `tests/test_categories_v2.py` | Cell, boundary, transaction, and replay invariants |
| `tests/test_category_context.py` | Domain-neutral boundary fixtures |
| `tests/test_category_evolution.py` | Proposal, rewrite, fork, and consolidation behavior |
| `tests/test_category_compile.py` | Ranking, traversal, lineage, and budget enforcement |

No new MCP mutation tool is required for v1. Existing events and recall outcomes
feed proposals internally. Diagnostics are exposed through reflection and a
read-only replay/calibration CLI.

## Configuration and Rollout

```toml
[category_evolution]
enabled = false
shadow = true
influence_recall = false
auto_commit = false
db_path = ""
archive_quota_bytes = 3000000000000
archive_high_watermark_ratio = 0.90
interpreted_max_dimension = 2
max_traversal_depth = 4
max_neighbors = 64
max_candidates = 50000
compile_wall_time_ms = 500
consolidation_event_interval = 250
consolidation_rewrite_budget = 32
max_rewrite_members = 32
max_active_branches = 4
soft_boundary_threshold = 0.35
hard_boundary_threshold = 0.65
hard_boundary_confirmations = 2
```

`enabled` starts the v2 observer. `shadow` prevents its results from altering
existing behavior. `influence_recall` independently permits ranking influence,
and `auto_commit` independently permits consolidation to commit eligible
proposals. The shipped combination disables the observer; the first calibration
explicitly sets only `enabled = true` while leaving the other safety gates as
shown.

Rollout stages:

1. **Unit-only:** isolated temporary databases and deterministic fixtures.
2. **Legacy replay:** import the 1,460-cell active archive into a disposable v2
   database and compare counts, lineage, and retrieval.
3. **Shadow observation:** record contexts, proposals, and compiled views without
   changing recall output.
4. **Read-only A/B:** compare baseline retrieval with shadow compiled retrieval.
5. **Quiet influence:** only after acceptance, allow the compiled view to adjust
   ranking without injecting visible commentary.
6. **Structural commits:** enable automatic periodic consolidation last, with
   bounded batches and rollback by epoch selection.

Each stage requires explicit configuration. Shipping the code does not enable
live structural mutation.

## Error Handling and Recovery

- Invalid dimensional boundaries reject the proposal; they never partially
  create cells.
- A failed rewrite transaction creates no epoch and changes no active lifetime.
- Missing vectors exclude cells from vector seeding but not exact traversal.
- Corrupt snapshots are deleted and rebuilt from immutable events.
- An unavailable shadow database disables category evolution only; normal recall
  remains available.
- Disk pressure disables derived writes and then category writes before the
  filesystem fills.
- Every compile has wall-time, cell-count, traversal, and token limits.
- Epoch selection provides logical rollback without deleting later history.
- Code upgrades use coordinated process replacement, never live module reload.
  Shutdown stops and joins the watcher while storage remains open, drains
  admitted work, closes dependent native resources, then closes storage. A
  replacement process starts only after the old process exits; immutable disk
  state and process-local reset provide the handoff.
- No runtime code adopts classes, callbacks, SQLite connections, compiler
  leases, or native handles created by an older module generation. Failed
  shutdown remains an old-process failure for the supervisor to surface; it
  cannot publish a mixed-generation server inside the process.

## Test Strategy

### Mathematical and storage invariants

- Dimension-1 boundaries reference dimension-0 cells.
- Dimension-2 boundaries are ordered paths of dimension-1 cells.
- Path endpoints compose where v1 claims a valid path.
- Cells and committed events are immutable.
- Every active cell is reachable from the selected epoch.
- Every split and merge retains maps to its inputs.
- Epoch parents form an acyclic graph.
- A failed commit leaves the logical database state unchanged; WAL and journal
  bytes are not part of this invariant.
- Replaying the same event log produces the same canonical snapshot hash.
- Importing the legacy archive twice produces no duplicates.

### Generic-context fixtures

Use four scenario families—conversation, coding, reading/media, and planning—
with equivalent structural transitions but different vocabulary. The same
boundary algorithm and storage API must pass all four; production code may not
branch on scenario family.

Fixtures cover:

- gradual topic drift;
- explicit hard boundaries;
- returning to a prior context;
- overlapping contexts;
- a source change without a goal change;
- a goal change without a source change;
- forked interpretations followed by optional reconciliation.

### Evolution fixtures

- repeated evidence creates a proposal but not an immediate rewrite;
- consolidation commits a supported split;
- noise and one-off novelty do not split;
- merge, retire, and retype preserve lineage;
- explicit correction can commit with one evidence event;
- consolidation respects the 32-rewrite budget;
- no more than four alternatives become active at one locus;
- dimensions above 2 round-trip opaquely and never enter online traversal.

### Compiler fixtures

- direct relevance beats unrelated popularity;
- strong evidence does not masquerade as current relevance;
- affect changes salience without changing evidence;
- adopted conventions surface within their scope;
- a useful distant association can occupy a diversity slot;
- historical cells translate through rewrite lineage;
- output is deterministic under stable inputs and tie-breaking;
- 36k target, 40k rotation watermark, and 64k ceiling are enforced exactly.

### Acceptance experiments

Before live influence:

1. Legacy replay has zero unexplained cell loss and a stable snapshot hash over
   three independent replays.
2. Hand-labeled boundary fixtures reach at least `0.80` F1, reported separately
   for explicit, abrupt, and gradual boundaries.
3. Shadow compiled retrieval improves cross-context mean reciprocal rank by at
   least 15% over the current category search on the evaluation fixtures.
4. Direct same-context retrieval regresses by no more than 5%.
5. False cross-context transfers remain at or below 10% under blinded review.
6. A one-million-cell synthetic archive compiles without loading the archive and
   adds less than 1 GB peak RSS to the process.
7. Every compile remains inside its configured candidate, traversal, wall-time,
   and token budgets.

These thresholds are gates, not claims. Failed experiments produce evidence for
revision; they do not get tuned away after looking at the holdout results.

## Out of Scope for V1

- Interpreting dimensions above 2.
- Automatically inventing executable operators or granting them authority.
- A global consensus that erases contextual forks.
- Domain-specific storage or boundary rules.
- Replacing Graphiti, the unified memory graph, sheaf cohesion, or persistence.
- Automatically enabling recall influence or structural commits.
- Proving that the runtime implements an infinity-category.

## Success Criterion

The v1 succeeds when the same generic substrate can replay and evolve categorical
structure across several domains, reconstruct every change from disk, compile a
useful bounded working category, and measurably improve cross-context retrieval
without destabilizing direct recall or exceeding RAM and context budgets.
