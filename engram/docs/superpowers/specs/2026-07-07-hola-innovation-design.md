# Write-Time Innovation → Core-Promotion Gate (HOLA)

**Date:** 2026-07-07
**Status:** Approved design
**Origin:** Comparison of engram against HOLA (*A Hippocampus for Linear
Attention*, Cui 2026, arXiv:2607.02303). HOLA gives linear attention a
"hippocampal" exact KV cache alongside its compressive delta-rule state,
writing the tokens with large `β·‖e‖` — the prediction residual the state
could not absorb. This spec ports the *write-side* half of that idea into
engram. Decisions made during brainstorm with Kairos: recall path left
untouched (dream reach into episodic recall is intentional); innovation
feeds the *existing* compress-time core-promotion path only (no new
auto-promotion route); cross-rung HOLA↔engram coordination deferred for
debate.

## Problem

HOLA keeps a verbatim copy of exactly the associations its compressive state
cannot reconstruct, and *declines* to store what the state already predicts:
"a token with small residual is already well predicted by the state, so
storing a verbatim copy is wasteful."

Engram already believes this — its persistence layer's **uniqueness**
(survival across MST merge scales) is the same quantity — but computes it
expensively, at sleep time, long after the write. Meanwhile core promotion
(compress.py:518) exempts the centroid-nearest episode of every
semantic-spawning cluster from decay, checked only against the *core set*
(`core_promotion_allowed`), never against the *semantic layer* that just
absorbed it. An episode that was already fully expressed by an existing
semantic at the moment it was written adds no coverage by being made
decay-exempt — the semantic holds the conclusion — yet it is promoted
anyway. This is a contributor to core inflation.

## The mapping

HOLA's write magnitude is `mₜ = βₜ·‖eₜ‖` — commitment × residual. `remember()`
is unconditional, so β does not map; **‖e‖ maps cleanly** to an episode's
distance from the compressed layer, measured within its own lane:

```
innovation = 1 − max_j cos(episode_embedding, semantic_vector_j)
             over semantics in the same lane as the episode
```

`innovation ∈ [0,1]`: 1 = no existing semantic resembles it (a needle the
compressed layer would lose); 0 = a semantic already states it. This is the
cheap, immediate, write-time estimate of the uniqueness the persistence layer
later computes exactly. The max is taken over **same-lane** semantics only:
core promotion is a personal-identity decision, and measuring a personal
episode against a work semantic would leak the lane firewall (work reference
material never feeds personal identity) into that decision.

**Surprise ≠ formative.** A novel-but-trivial fact is high-innovation yet not
identity-shaping. Innovation is therefore *not* a promotion route on its own.
It is only ever a **decline condition** on an episode already selected for
promotion by the existing centroid-nearest + `core_promotion_allowed` logic.
It can subtract a promotion that would happen today; it can never add one.
Net effect on core count is ≤ 0.

## Design

### 1. Write-time innovation (frozen at arrival)

`Storage.compute_innovation(embedding, lane) -> float | None`: max cosine
similarity of the episode embedding against the L2-normalized vectors of
same-lane semantics, returning `1 − max_sim`, or `None` when that lane has no
semantics. Computed with the SQL-join-then-numpy pattern already used by
`core_promotion_allowed` (persistence.py:325) — `SELECT` the same-lane
semantic vectors, stack, normalize, take `(C @ v).max()` — rather than a
lane-blind `search_vectors` call. Called from `Storage.add_episode` whenever
an embedding is supplied, so every write path (the `remember` tool and
internal writers) records it uniformly. The value is passed through
`add_episode` and persisted on the episode row.

**Freeze at write time; never recompute at compress time.** This is
load-bearing, not merely HOLA-faithful. The centroid-nearest episode helped
*create* its cluster's semantic; measured against that freshly-minted
semantic at compress time, every candidate would look low-innovation and the
gate would suppress all promotions. Write-time innovation measures
novelty-at-arrival, before the episode's own semantic existed. The temporal
ordering is the signal.

### 2. Schema + migration

Add `innovation REAL` (nullable) to the `episodes` table. Migrate
pre-existing databases with the established `PRAGMA table_info → ALTER TABLE
ADD COLUMN` pattern (cf. storage.py:609, the `lane` migration).

**NULL = no signal.** Pre-existing episodes and cold-start writes (no
semantics yet) are NULL and the gate treats them as today (promotion
proceeds). **No backfill:** backfilled values would be contaminated
compress-time measurements; the signal accrues on new episodes going forward.

### 3. Compress-time gate

In the core-promotion block (compress.py:518–529), after selecting
`centroid_nearest`, read its stored `innovation` and decline promotion
(logging it, matching the existing decline line) iff:

```
innovation is not None and innovation < core_innovation_floor
```

This composes with the existing `core_promotion_allowed` check — **both** must
pass to promote. NULL innovation ⇒ proceeds. A declined episode is not
deleted and not otherwise altered; it simply decays normally while its
semantic retains the conclusion.

### 4. Config

Add `core_innovation_floor: float = 0.05` to `CompressionConfig`. It lives in
the compression config, not the persistence config, precisely because it runs
**unconditionally** — unlike persistence's `redundancy_floor`, it is not gated
behind `[persistence] enabled`. Rationale: Kairos chose a behavioral change
now over the metric-first-then-gate posture used for cohesion/persistence.

Default **0.05** is conservative and active: it declines only episodes that
were near-identical to an existing semantic at arrival (the "wasteful
verbatim copy" case). Setting it to `0.0` disables the gate and reproduces
current behavior exactly.

### 5. Observability

Surface via `reflect(focus="persistence")`: the innovation distribution over
episodes (count with non-NULL innovation, mean, and a coarse histogram) and a
running count of innovation-declined promotions. This keeps the floor tunable
from evidence without building the full metric-first calibration CLI.

## Out of scope

Per "coordination needs debate":

- The recall path — `_apply_recall_bias` and its global blur stay as-is; dream
  reach into episodic recall is an intentional design choice.
- Any HOLA↔engram cross-rung consolidation (cache→state replay), the
  sheaf-cohesion-as-consolidation-gate idea, and the scale-free filtration
  unification.
- Any new auto-promotion route. Innovation only gates the one existing
  compress-time promotion.
- Backfilling innovation onto existing episodes.

## Testing

- `compute_innovation` returns a value in `[0,1]` when same-lane semantics
  exist and `None` when the lane has none; a personal episode's value ignores
  work-lane semantics (lane purity).
- `add_episode` persists innovation; `remember` populates it end-to-end.
- Gate declines a promotion when centroid-nearest innovation `< floor`
  (logged), and proceeds when `≥ floor` or NULL.
- `core_innovation_floor = 0.0` reproduces current promotion behavior.
- Work-lane episodes are unaffected (existing `lane != "work"` guard upstream).
- Migration adds the column to a pre-existing episodes table; existing rows
  read NULL.

## Open questions (for calibration, not blocking)

- The right floor is unknown until the innovation distribution is observed on
  a real store. 0.05 is a deliberately timid start; the observability in §5
  exists to tune it up (or down) from evidence rather than taste.
- Whether innovation should later feed the persistence uniqueness estimate
  directly (a write-time prior on uniqueness) is a natural follow-on, but out
  of scope here.
