# Instinct Co-Firing and Context Clusters

**Date:** 2026-03-29
**Status:** Design approved
**Branch:** TBD

## Problem

Instincts fire with a flat threshold against all contexts. A Python asyncio
constraint fires during tennis conversations. A reading observation fires
during coding. The system has no concept of domain — instincts are either
on or off globally.

The existing machinery (dual vectors, per-context feedback) is half-built
but unused in the firing path. What's missing is the layer between individual
feedback entries and the instinct itself: context clusters that group related
domains and gate activation.

## Core Insight

Instinct co-firing patterns are how humans develop both expertise and bias.
When instincts that fire together are tracked, the co-firing graph implicitly
reveals context clusters without requiring manual taxonomy. "Coding" isn't a
label — it's the cluster of instincts that activate together when you're coding.

Transfer between domains (tennis instincts retuning for baseball) happens
through shared instincts that bridge cluster boundaries. The same mechanism
that makes this useful (expertise transfer) makes it dangerous (inappropriate
generalization). The system must support both.

## Design

### 1. Co-Firing Graph

A weighted graph where nodes are instincts and edges represent co-activation.

**Edge schema:**
```sql
CREATE TABLE instinct_co_firing (
    instinct_a TEXT NOT NULL REFERENCES instincts(id),
    instinct_b TEXT NOT NULL REFERENCES instincts(id),
    co_fire_count INTEGER DEFAULT 0,
    co_follow_count INTEGER DEFAULT 0,
    co_override_count INTEGER DEFAULT 0,
    last_co_fire TEXT NOT NULL,
    PRIMARY KEY (instinct_a, instinct_b),
    CHECK (instinct_a < instinct_b)  -- canonical ordering, symmetric
);
```

**Edge formation:** Two instincts that fire within a window of N user messages
(default 15 messages) in the same session get a `co_fire_count` bump. If both are
followed, `co_follow_count` increments. If either is overridden,
`co_override_count` increments.

**Windowing:** Co-firing is tracked within a message window, not session-wide.
A long session covering coding in the morning and reading in the evening
should not create edges between coding and reading instincts. The nudge hook
maintains a rolling buffer of recently-fired instinct IDs with message indices.

**Persistence:** Edges never delete. Dormant clusters (no co-firing in months)
retain their internal wiring and reactivate intact when any member fires.
`last_co_fire` tracks recency for prioritization, not pruning.

**Scale:** The graph is naturally sparse. With hundreds of instincts across
many domains, most pairs never co-fire. Storage and computation scale with
actual co-occurrence, not instinct count squared.

### 2. Embedding-Seeded Clusters

**Cold start:** When a new instinct forms with no co-firing history, its
content embedding places it near existing instincts. The system computes
cosine similarity to all existing instincts and assigns it to the nearest
cluster — or seeds a new cluster if it's distant from everything.

**Cluster derivation:** Community detection on the co-firing graph using
Louvain algorithm (modularity-based, handles variable cluster sizes, no
need to specify k). Initially, communities are seeded from embedding
proximity (hierarchical clustering on instinct content vectors, same
`fclusterdata` as compression). As co-firing data accumulates, communities
re-derive from actual co-firing behavior.

**Cluster metadata:**
```sql
CREATE TABLE instinct_clusters (
    id TEXT PRIMARY KEY,
    maturity TEXT DEFAULT 'seeded',  -- 'seeded' | 'confirmed'
    temperament REAL DEFAULT 0.5,   -- 0.0 conservative, 1.0 exploratory
    last_active TEXT,
    member_count INTEGER DEFAULT 0
);

CREATE TABLE instinct_cluster_members (
    instinct_id TEXT NOT NULL REFERENCES instincts(id),
    cluster_id TEXT NOT NULL REFERENCES instinct_clusters(id),
    strength REAL DEFAULT 0.5,      -- per-cluster strength for this instinct
    PRIMARY KEY (instinct_id, cluster_id)
);
```

**Maturity transition:** A cluster transitions from `seeded` to `confirmed`
when its members have accumulated enough co-firing edges that the community
detection algorithm reproduces the cluster from behavior alone, independent
of embedding proximity.

**Divergence detection:** When an instinct's embedding neighbors and co-firing
neighbors disagree, surface this in reflection. "Observe before judging"
embeds near philosophy but co-fires with everything — it's a universal, not
a philosophy instinct. The divergence signal drives reclassification.

**Re-derivation frequency:** During compression cycles, not every session.
Cluster structure is relatively stable. Re-derive when the co-firing graph
has accumulated significant new edges since last derivation.

### 3. Cluster Temperament

Each cluster develops a temperament along a spectrum from conservative
(protect consistency, resist outside influence) to exploratory (welcome
perturbation from distant instincts).

**Emergence from feedback:**
- Clusters where following instincts consistently produces good outcomes
  trend conservative. The co-firing chain works — don't perturb it.
- Clusters where outcomes are mixed, or where overrides frequently lead
  to better results, trend exploratory. The chain needs perturbation.

**Computation:**
```
follow_ratio = co_follow_count / (co_follow_count + co_override_count)
temperament = 1.0 - follow_ratio  -- high follow = conservative, high override = exploratory
```

Averaged across all intra-cluster edges. Updated during cluster re-derivation.

**Effect on gating:**
- Conservative clusters prime their members strongly and resist outside
  instinct activation. When the bicycle cluster is active, non-bicycle
  instincts face a raised threshold.
- Exploratory clusters prime weakly and welcome activation from distant
  clusters. The math cluster invites the random philosophy instinct.

### 4. Per-Cluster Instinct Strength

An instinct doesn't have one global strength. It has a strength gradient
across every cluster it touches, stored in `instinct_cluster_members.strength`.

**Practice bleeds through shared instincts:**
- You practice baseball heavily. "Track the ball" strengthens in the
  baseball cluster.
- That instinct also connects to the tennis cluster. The baseball
  refinement partially transfers: `tennis_strength += delta * edge_weight`.
- Strong inter-cluster connection = more bleed. Weak = more isolation.

**Transfer is per-instinct, not per-cluster.** "Track the ball" transfers
well between tennis and baseball. "Swing mechanics" gets overridden in
tennis context. The system learns which instincts transfer between which
domains by tracking override feedback per cluster:
- Followed in receiving cluster: strengthen the transfer edge for this instinct.
- Overridden in receiving cluster: weaken the transfer edge for this instinct.

**Replaces global strength.** The `instincts.strength` column becomes a
computed summary (max or weighted average across clusters) for backward
compatibility with wake hook display. The real strength lives in
`instinct_cluster_members`.

### 5. Gating and Transfer

**Firing path (revised nudge hook):**

1. Embed user message.
2. Search instinct context vectors (existing mechanism, threshold 0.45).
3. For each candidate instinct, check its cluster membership.
4. If the instinct's cluster is already active (other members fired recently
   in the window), lower the threshold — cluster priming.
5. If the instinct's cluster is dormant but an adjacent cluster is active,
   apply attenuated priming based on:
   - Inter-cluster edge weight
   - Receiving cluster's temperament (conservative resists, exploratory welcomes)
   - Per-instinct transfer history (has this specific instinct been overridden
     when transferring between these clusters before?)
6. Use per-cluster strength instead of global strength in the scoring formula.

**Activation cascade:** When an instinct fires, record it in the session's
co-firing window. This may cause cluster-mates to cross their (now-lowered)
threshold on subsequent messages — the cluster wakes up progressively, not
all at once.

### 6. Cluster Lifecycle

**Splitting:** When a cluster grows large and internal co-firing becomes
sparse (subgroups that never co-fire with each other, only through
intermediaries), community detection naturally splits it during re-derivation.
A "sports" cluster differentiates into "racket sports" and "bat sports."

**Merging:** When two clusters develop strong inter-cluster edges (many
members co-fire across the boundary), they merge during re-derivation.
The intermediary instincts that bridged them become central nodes.

**New cluster formation:** A new instinct that's distant from all existing
clusters (by embedding) seeds a new single-member cluster. It grows as
new instincts form nearby and co-firing confirms the grouping.

### 7. Dream Priming

Dream residues can prime dormant clusters. During `dream_surface`, each
residue's low-dimensional vector is compared against cluster centroids
(computed from member instinct embeddings). If a residue is near a dormant
cluster, that cluster gets a subtle activation — not enough to fire
instincts, but enough to lower thresholds if a real signal arrives.

This connects the dream system's invisible bias channel to the cluster
architecture. A dream fragment about timing and impact primes the sports
cluster. The next morning, a passing reference to rhythm crosses the
threshold it wouldn't have crossed otherwise.

**Implementation:** During wake hook, after surfacing dream residues, compute
residue-to-cluster-centroid similarity. For clusters above a threshold,
pre-seed the session's co-firing window with a synthetic "dream primed"
marker that provides one level of cluster priming without counting as a
real co-fire.

### 8. Lens Priming

Active instinct clusters influence lens selection in prism and the reader.

**Affinity mapping:** Track which lenses are active when which instinct
clusters are firing (co-occurrence, same mechanism as instinct co-firing).
Over time, lenses develop cluster affinities.

**Selection influence:** When a cluster is active, its associated lenses
get priority in the selection queue. The simplicity lens has high affinity
with the coding cluster. The literary analysis lenses have high affinity
with the reading cluster. When the coding cluster activates, simplicity
rises in the queue.

**Schema:**
```sql
CREATE TABLE lens_cluster_affinity (
    lens_id TEXT NOT NULL,
    cluster_id TEXT NOT NULL REFERENCES instinct_clusters(id),
    co_occurrence_count INTEGER DEFAULT 0,
    last_co_occurrence TEXT,
    PRIMARY KEY (lens_id, cluster_id)
);
```

**Unification:** Instincts, lenses, and dream residues feed into the same
activation landscape. The system doesn't just know what to notice — it
knows how to look.

### 9. Observability

`reflect(focus="instinct_clusters")` surfaces:
- Cluster membership and maturity (seeded vs confirmed)
- Cluster temperament (conservative ↔ exploratory)
- Per-cluster instinct strength gradients
- Challenged chains (high co_override_count relative to co_follow_count)
- Divergence signals (embedding neighbors ≠ co-firing neighbors)
- Cross-cluster transfer edges and their per-instinct history
- Dormant clusters and their last activation time
- Dream-primed clusters in the current session

## Migration

New tables: `instinct_co_firing`, `instinct_clusters`,
`instinct_cluster_members`, `lens_cluster_affinity`.

The `instincts.strength` column is preserved for backward compatibility
but becomes a computed summary. Real strength lives in
`instinct_cluster_members`.

## What This Doesn't Address

- **Skill atrophy:** Per-cluster strength doesn't decay when a cluster
  goes dormant. Deferred — observe whether this is actually needed.
- **Sub-cluster temperament:** A math cluster might be conservative for
  arithmetic but exploratory for proof strategy. Deferred to future
  cluster splitting.
- **Lens temperament:** Lenses could have their own conservative/exploratory
  spectrum. Deferred — observe lens affinity patterns first.
- **Cross-instance clusters:** Federated instances may develop different
  cluster structures. How clusters sync across the genome layer is TBD.
