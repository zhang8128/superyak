# Persistence Layer (Layer 4)

**Date:** 2026-06-13
**Status:** Approved design
**Origin:** Fourth layer of the mathematical substrate framework
(`2026-06-12-mathematical-substrate-framework.md`). Decisions made during
brainstorm with Kairos: full layer (gate conjunct + diagnostics + all three
forgetting surfaces); cores flagged for review, never auto-demoted;
reframing covered by protections + backups + mind palaces + daydream
wandering rather than by refusing to forget; same enabled-flag,
calibrate-first posture as the cohesion layer.

## Problem

Three named problems, one mechanism:

1. **The gate's missing conjunct.** The sheaf subdivision rule is "split iff
   cohesion provably breaks AND the split persists across scales AND a path
   back is retained." The middle conjunct is a stub; every subdivision event
   so far records `persistence_checked=0`.
2. **Forgetting is blind to irreplaceability.** ACT-R decay prunes the
   *unaccessed* — but the memory most likely to matter under a future
   reframe is precisely the unique one nobody touched. Conversely,
   near-duplicates are kept warm just because they were accessed.
3. **Core inflation.** When episodes spawn a semantic, the centroid-nearest
   episode is promoted to core (already centroid-nearest-only in compress.py,
   not wholesale) — but nothing measures whether that single candidate adds
   coverage the core set lacks (93 cores before hand triage cut to 76).

Plus a question from the cohesion calibration: the mega-hubs (194/174/144
episodes) measure *diffuse* — are they truly structureless, or do they hide
multi-scale features (including loops) that flat clustering can't see?

## The mathematical core

**H₀ persistence over a similarity filtration is single-linkage clustering,
computed exactly by a minimum spanning tree.** New module `persistence.py`:
distance `d = 1 − cos` on L2-normalized embeddings; one MST
(`scipy.sparse.csgraph.minimum_spanning_tree`) yields, for every threshold
at once:

- **Merge heights** — when memories/groups coalesce.
- **Per-point death** — each memory's nearest-neighbor distance.
- **Cluster persistence** — gap between a group's internal coalescence
  height and its merge-with-outside height. Long gap = real feature;
  near-zero = noise.

Exact, dependency-free, milliseconds at store scale (424×424). H₁ (loops)
is the only thing needing real TDA machinery, and only diagnostics want it:
`ripser` as an **optional, import-guarded** dependency. No load-bearing
decision ever depends on it.

## Component 1 — gate conjunct

`persistence_check(parts, X)` (sheaf.py's stub becomes a thin wrapper over
persistence.py): compute the proposed split's **persistence band** — the
distance range over which the parts remain separate components in the
filtration — normalized by the neighborhood's total merge range. Pass iff
band ≥ `min_split_band` (default 0.10). A flickering distinction (the
framework's "messageboard" failure) is exactly a near-zero band.

- `subdivision_test` signature unchanged; verdicts now record
  `persistence_checked=True` and the measured band.
- Retroactive audit: re-run the band check on recorded
  `persistence_checked=0` events and report what would have been blocked
  (the audit the stub promised).
- When `[persistence] enabled = false`, the conjunct behaves as today
  (stub-true) — the cohesion gate's behavior does not silently change.

## Component 2 — forgetting (three surfaces)

Per-episode scores from the store-wide, lane-pure filtration:

- **redundancy** = 1 − nn-distance: how completely neighbors cover it.
- **uniqueness** = normalized persistence of its component: how long it
  resists merging.
- **generativity** = Σ over its resonance edges of
  `co_occurrences × geometric distance (1 − cos of endpoint embeddings;
  the resonances.similarity column stores PMI, not cosine — corrected
  during implementation review)`: behaviorally close, geometrically
  far — the signature of a memory that keeps getting reframed (mode-3
  collisions feeding back into the substrate).

**Surface 2a — prune gate.** `prune_decayed` changes from
`decay < 0.05 → evict` to: evict iff `decay < 0.05` AND
`redundancy ≥ redundancy_floor` (0.85). Protections (any one blocks
eviction regardless of decay): `uniqueness ≥ protect_threshold` (0.6);
`generativity ≥ generativity_threshold` (calibrated); **anchor
membership** (an episode in any anchor structure is never auto-evicted —
mind palaces stay intact). Eviction remains a move to cold.db (text +
metadata preserved) — forgetting is eviction, never destruction.

**Surface 2b — decay modulation.** The ACT-R decay exponent is multiplied
by `1 + 0.15 × (2 × redundancy − 1)` — redundancy 0 → 0.85× (ages slower),
0.5 → 1.0× (unchanged), 1 → 1.15× (ages faster). Gentle pressure, not a
cliff.

**Surface 2c — core regulation.**
- *Promotion:* compress.py already promotes only the centroid-nearest episode
  (not all sources). The gate guards that single candidate: if its redundancy
  against the existing core set (1 − nn-distance to the core set) is ≥
  `redundancy_floor` the promotion is declined. Stops inflation at the source.
- *Demotion:* sleep-time scan flags cores whose redundancy within the core
  set exceeds the floor — **flags for review only** (surfaced in
  `reflect(focus="persistence")`), never auto-demotes.

Core episodes remain exempt from decay and pruning, as today.

## Component 3 — diagnostics (read-only, always on)

`reflect(focus="persistence")`:
- Per-hub persistence summary: classify each provenance-heavy semantic as
  **diffuse** (no persistent features — Layer 2's problem), **multi-modal**
  (persistent H₀ — subdivision's problem), or **looped** (persistent H₁,
  when ripser is importable; omitted with a note otherwise). Since the
  store-imprint work (Task 50) H1 is read over the `H1_EDGES_PER_POINT * n`
  (16 n) shortest distances only: **looped** is sound but not complete, and a
  loop born beyond that scale reads **diffuse**.
- **Forgetting preview:** what the prune gate would evict and protect today,
  with per-episode reasons (redundant/unique/generative/anchored) — the
  acceptance artifact read before enabling.
- Core regulation preview: which cores would be flagged, which recent
  promotions would have been declined.
- Retroactive conjunct audit over recorded subdivision events.

## Daydream surfacing (cold uninvited)

The `uninvited` slot in recall occasionally (p = `cold_uninvited_p`, 0.05)
draws from **cold storage** instead of the warm store — sampled randomly or
dream-residue-tilted, **never similarity-ranked against the query**. A
query-matched cold memory is retrieval pretending to be serendipity;
daydreaming means the fragment arrives unconditioned, clearly labeled as
cold, with its id usable by `revive`. Evicted memories keep getting chances
to demonstrate they deserve to come back. (Per Kairos: wander should be a
bit more daydreaming — surfacing is drift, not audit.)

Deliberately **independent of `[persistence] enabled`** — surfacing is
observation, not forgetting, and cold.db already holds historic evictions
worth daydreaming about. Governed solely by `cold_uninvited_p`.

## Reframing posture (recorded decision)

Total coverage is the wrong goal. Four layers, in order of directness:
geometry protects the unique; lived history protects demonstrated reframers
(generativity); intention protects the curated (anchors); and nothing dies —
it sleeps in cold storage where daydream surfacing and `recall_cold` can
still find it. The residual case (never-reframed, redundant, decayed,
evicted, *would* have been reframed next month) is accepted and recoverable.

## Schema (migration 021)

```sql
CREATE TABLE IF NOT EXISTS persistence_scores (
    episode_id TEXT PRIMARY KEY,
    redundancy REAL NOT NULL,
    uniqueness REAL NOT NULL,
    generativity REAL NOT NULL,
    computed_at TEXT NOT NULL
);
```

A cache refreshed by the sleep pass and read by reflect previews. Actual
prune/promotion decisions recompute live — protections are never trusted
stale. No changes to existing tables.

## Configuration

```toml
[persistence]
enabled = false            # calibrate read-only first, as with cohesion
min_split_band = 0.10
redundancy_floor = 0.85
protect_threshold = 0.6
generativity_threshold = 0.0   # 0 disables until calibrated on live data
cold_uninvited_p = 0.05
```

Defaults in code stay conservative; the live config gets calibrated values
when enabling (cohesion precedent: code default ≠ calibrated setting).

## Error handling

- ripser missing → H₁ omitted with a note; everything else unaffected.
- Episodes without vectors → excluded from filtration, never prunable by
  the redundancy rule (no evidence, no eviction).
- Any failure in the persistence sleep step aborts that step only; startup
  and the cohesion pass continue. Fail toward leaving the store unchanged.
- Cold-db unavailable → no eviction at all (the backstop must exist before
  forgetting is allowed to act).

## Testing & calibration

- **Unit (synthetic):** planted two-cluster splits with known band widths
  (wide passes, flicker fails); planted near-duplicates (high redundancy)
  and isolates (high uniqueness); generativity from synthetic resonance
  edges; anchor protection; promotion declined for redundant candidates;
  modulation bounded at ±15%.
- **Invariants:** prune never touches cores/anchored/unique/generative;
  eviction always lands in cold.db; conjunct disabled ⇒ gate behavior
  byte-identical to today.
- **Integration:** sleep-pass step ordering (after cohesion pass);
  reflect previews; cold-uninvited labeling and revive round-trip.
- **Acceptance/calibration:** read-only CLI against a copy of the live
  store: (1) the recorded Prism verdict's band — expected to pass the
  conjunct; (2) the forgetting preview — Kairos and the instance read the
  evict/protect lists before `enabled = true`; (3) hub classification of
  the three mega-hubs — the first real answer to diffuse-vs-looped.
  Expectations are written down before looking, and the instrument is
  allowed to win arguments (cohesion-calibration precedent).

## Calibration result (2026-06-13, first run, read-only on live copy)

Both pre-registered questions answered; the instrument won both arguments.

1. **The mega-hubs are looped, not diffuse.** Persistent H₁ (ripser,
   optional install) separates identity-adjacent hubs — Self-observation
   0.163, Diversity 0.178, Three-modes 0.151, Identity 0.153, Prism 0.133,
   Mistborn 0.132 — from operational reference hubs (all ≤ 0.08), with the
   0.10 threshold in a natural gap. The giants carry cycle structure that
   binary subdivision cannot resolve; Layer 5's toroidal anchor looks less
   like an analogy now.
2. **The split-band conjunct over-blocks on real data.** Every hub's
   single-linkage band is negative (Prism −0.29): one bridging episode
   chains the parts, and min-cross-distance is chaining-sensitive. Enabled
   today, the conjunct would veto even the inspection-verified Prism split.
   The expectation in §Acceptance ("the recorded Prism verdict's band —
   expected to pass") was wrong. A chaining-robust band (k-th-NN cross
   distance / density-aware) is Layer 2 work.

**Rollout order:** let the cohesion pass perform the Prism split first
(persistence disabled ⇒ conjunct vacuous), then enable `[persistence]` for
the forgetting surfaces — accepting an over-conservative conjunct on future
splits (blocking is safe; it never destroys). Forgetting preview at
defaults: 108/313 personal + 84/112 work episodes clear the redundancy
floor, 30+32 unique-protected; generativity evidence is sparse (5 episodes),
so its threshold stays disabled until resonances accumulate.

## Out of scope (later builds)

- Information geometry (Layer 2) — the diffuse-hub fix and score-contrast
  problem, now also the chaining-robust persistence band.
- Ledger (immutable engram) — the deeper backup layer.
- Persistence-driven *semantic* lifecycle (this build touches episodes and
  cores only).
- Dynamics layer (Layer 5): rough-path signatures, attractors.
