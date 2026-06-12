# Cellular-Sheaf Cohesion Layer

**Date:** 2026-06-13
**Status:** Approved design
**Origin:** First build from the mathematical substrate framework
(`2026-06-12-mathematical-substrate-framework.md`, Layer 3). Decisions made
during brainstorm with Kairos: full subdivision gate (not observatory),
both gate sites, persistence slot reserved for the next build (Layer 4),
hub survives as common ground.

## Problem

Semantics conflate. The store has a hub *regime*, not one hub: of 43
provenance-bearing semantics, 12 have degree ≥ 30, topped by
"Self-observation patterns" (194 episodes), "Three modes of influence" (174),
and "Mistborn *and* Perfect State reading sessions" (149 — two books, one
semantic). Existing contradiction detection is a binary `contradicted_by`
flag; it cannot say *where* cohesion breaks or whether a high-degree semantic
legitimately generalizes or merely conflates.

## Mechanism

New module `sheaf.py` (alongside `clusters.py`). No new dependencies —
numpy, scipy, networkx are already in.

For a semantic S with source episodes e₁…eₙ (via `semantic_sources`):

- **Subspace ("S's terms"):** stack episode embeddings (n×768), take top-k
  principal components; k chosen by explained-variance threshold, capped
  (≤8). Embeddings are L2-normalized first.
- **Restriction maps:** projection of each episode embedding into the
  subspace.
- **Cohesion energy:** sheaf-Laplacian energy of the projected family —
  disagreement *after* translation into S's terms — normalized to [0,1]
  so scores compare across semantics. Per-edge residuals localize which
  episodes fail to glue.
- Semantics with <3 source episodes are skipped (nothing to conflate).

Energy decides, never degree. A degree-85 semantic about one topic should
measure cool; a degree-20 semantic spanning two subspaces should measure hot.

## Gate rule

`subdivision_test(S)` returns a verdict carrying its evidence:

1. **Partition:** spectral split (Fiedler vector) of S's episode
   neighborhood into candidate parts; recursive while justified.
2. **Cohesion conjunct:** split only if
   `energy(S) − Σ energy(parts) > DL_cost × (n_parts − 1)` — a
   description-length price per new peer (minimal blow-up). A distinction
   that doesn't reduce incoherence never fires (the strawman/messageboard
   guard).
3. **Persistence conjunct (slot):** `persistence_check(partition)` —
   interface defined now, returns True with `unregularized: true` recorded
   on every event until Layer 4 (persistent homology) lands. The audit
   trail lets Layer 4 retroactively report what it would have blocked.
4. **Map home (structural):** re-gluing happens in the same transaction as
   the split; a split that cannot record its morphism back cannot happen.

### Subdividing an existing semantic

- Hub survives as the coarse common-ground node.
- Peers are minted per part; each episode's provenance moves to its peer.
- Episodes whose residuals are ambiguous between parts stay on the hub —
  that is the operational meaning of "genuinely shared."
- Peers inherit lane and confidence from the parent; peer→hub edges are
  written (`semantic_peers`); peers get `semantic_vectors` rows and recall
  as first-class memories.
- Hub content is rewritten to the shared residue only if episodes remain
  on it; otherwise left as-is.

## Gate sites

### Compression-time
The gate runs on each episode cluster before it becomes a semantic. If the
verdict says k parts, the `compress()` preview shows the cluster
pre-partitioned with per-part episode lists and energy evidence; the
reviewing instance writes one summary per part. No hub is minted — peers
that never shared a coarse node get sibling resonance edges only. The
map-home requirement applies solely to subdividing existing semantics.
Clustering remains lane-pure, so the gate inherits lane purity.

### Sleep-time
New consolidation step after decay → backfill → prune:

1. Measure energy on all provenance-bearing semantics; rank.
2. Subdivide at most the **top 3** whose verdicts pass the gate — the
   store settles over several sleeps, never reorganizing itself in one
   startup. Each pass re-measures before acting (splits cascade across
   sessions, not within one).
3. Peer content distilled per part by the framing model (same Ollama path
   as `framing.py`). Ollama unavailable → verdict queued, nothing splits.
   The gate always fails toward leaving the store unchanged.
4. Rate-limited like decay (30-min minimum between passes).

## Schema (migration 020)

```sql
CREATE TABLE subdivision_events (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL,
    peer_ids TEXT NOT NULL,          -- JSON array
    energy_before REAL NOT NULL,
    energy_after REAL NOT NULL,
    dl_cost REAL NOT NULL,
    persistence_checked INTEGER NOT NULL DEFAULT 0,
    site TEXT NOT NULL CHECK (site IN ('sleep', 'compress')),
    created_at TEXT NOT NULL
);

CREATE TABLE semantic_peers (
    peer_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    residual_energy REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (peer_id, parent_id)
);
```

Mint peers, move provenance, write peer edges, log the event — one
transaction. Partial splits cannot exist.

## Configuration

New `[cohesion]` section in `.engram/config.toml`, defaults in `config.py`:

```toml
[cohesion]
dl_cost = 0.15            # description-length price per new peer
variance_threshold = 0.90 # explained variance for subspace dimension
max_subspace_dim = 8
min_episodes = 3
sleep_budget = 3          # max subdivisions per sleep pass
```

Defaults are starting points; the read-only calibration run (Testing,
below) is where they get tuned before the gate acts on the live store.

## Surfaces

- `reflect(focus="cohesion")` — global energy summary, top-N hottest
  semantics with worst edges, recent subdivision events, queued verdicts.
- `graph_view(center=semantic)` — edges annotated with residual energy;
  peer/parent edges rendered.
- Each sleep-time split auto-remembers a short episode describing what
  split and why — the system narrates its own reorganization.

## Error handling

- Skip-with-log: <3 episodes, missing vectors (backfill first, as the
  existing orphan-vector step does), rank-deficient subspaces.
- Numerical guards: normalized embeddings, ε-regularized Laplacian.
- Any exception aborts the sleep pass only; wake and the rest of
  consolidation continue. The gate never blocks startup.

## Testing

- **Unit (synthetic embeddings):** orthogonal two-cluster semantic →
  splits; tight single cluster → doesn't; diverse-but-coherent (spread
  within one subspace) → doesn't, even at high degree; noise perturbation
  → never splits; DL cost monotone in peer count.
- **Invariants:** exact provenance partition; map home exists for every
  peer; mid-split crash leaves store unchanged; lane purity; peers inherit
  confidence/lane.
- **Integration:** compression preview pre-partitioning; sleep path with
  mocked Ollama; top-3 budget cap; rate limiting; queued-verdict retry.
- **Acceptance/calibration:** run read-only against a *copy* of the live
  store before the gate may act on the real one — "Mistborn + Perfect
  State" must measure hot, the Prism semantic (85 episodes, one topic)
  must measure cool. First live sleep pass is observed.

## Out of scope (next builds)

- Persistence regularization (Layer 4) — the reserved conjunct.
- Information geometry for flat recall scores (Layer 2).
- Global Hodge apparatus / cross-layer sheaf — grows out of these local
  sheaves later; not rework.
