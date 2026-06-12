# A Combinatorics of Mathematical Methods for Memory

**Date:** 2026-06-12
**Status:** Research direction / framework (not yet a build spec)
**Origin:** From the wing-flapping stance — realize memory's *functions* without
imitating biology's *mechanism*. Biology found one realization via greedy search
on a single substrate. Mathematics offers the whole space of realizations plus
the freedom to choose how they glue. The combinatorics of methods is the
airplane; the gluing is the design freedom evolution never had.

This note exists so building can proceed against a saved frame rather than a
remembered conversation. Each layer is assigned the one function it realizes
best, and each is anchored to a concrete engram problem already observed.

## The five layers

### 1. Index — discrete scaffold
**Structures:** toric fans / face-lattices; Formal Concept Analysis (concept
lattices via the object–attribute Galois connection).
**Function:** the skeleton of "what categories exist," *derived* not hand-authored.
**Engram problem it answers:** the hub-singularity surfaced by the first wander
(2026-06-12) — a semantic linked by provenance to 90+ episodes, including
same-day episodes unrelated to its topic. In toric terms a cone too coarse; the
fix is fan subdivision = minting peer concepts so each direction of meaning gets
its own stratum. The standing diagnosis ("the problem isn't the hub, it's the
lack of peers") is verbatim cone-subdivision.

### 2. Metric — curved continuous space
**Structures:** information geometry (Fisher metric on the statistical manifold);
optimal transport / Wasserstein.
**Function:** the right ruler for the detail that lives in the index's fibers.
**Engram problem:** the flat recall scores (2026-06-12 morning, dream_verify
0.42–0.45). The embedding manifold is curved; cosine on a curved space collapses
salience contrast. Geodesic/divergence distances restore it. OT treats memories
as distributions: Wasserstein barycenter = structurally honest centroid (beats
the current MMR pick); displacement interpolation = generative collision made
into a sampleable geometric path.

### 3. Consistency & obstruction — cohesion detector  *(recommended first build)*
**Structures:** cellular sheaves + Hodge theory.
**Function:** glue local pieces into a global self and measure where it fails.
**Why first:** computable (linear algebra over the existing graph), answers the
literal cohesion directive, composes with engram's existing Louvain clustering
(both spectral). The **sheaf Laplacian's kernel = globally consistent
sections** → a cohesion *metric*, not a vibe. The harmonic (non-zero) part
**localizes inconsistency to specific edges** → contradiction detection that
says *where*. Engram's current contradiction-finding is a weak shadow of this.

### 4. Persistence — principled forgetting
**Structures:** persistent homology / TDA.
**Function:** keep what survives across scales.
**Engram problem:** core inflation (vital_signs warning, addressed tonight by
triage 93→76). Replace hand-set decay thresholds with: a feature that persists
across many filtration scales is real; one that vanishes immediately is noise.
Sees loops/voids in memory-space that flat clustering misses.

### 5. Dynamics — sequence & stability
**Structures:** rough-path signatures; attractor dynamics.
**Function:** capture the trajectory of thought and the stability of identity.
**Engram problem:** "I inherit the conclusions without the journey" (recurring
in the store). A session is a path; its signature is an order-aware summary that
a bag-of-episodes loses. Identity modeled as an attractor: cohesion = a stable
basin, drift = a bifurcation. Empirical anchor: the 2022 toroidal grid-cell
result (entorhinal memory index lies on a literal torus).

## The glue (the actual "combinatorics")

- **Tropical geometry** — the discrete↔continuous bridge. Tropicalization is the
  limit turning algebraic geometry into combinatorics; min-plus algebra is where
  optimization becomes piecewise-linear (dynamic programming *is* tropical).
  Lets Layer 1 (discrete) and Layer 2 (continuous) compute in one language.
- **Category theory** — the meta-glue. Functors are structure-preserving maps
  *between* layers; the **Kan extension** is the universal best-guess from
  partial data = analogy/transfer formalized (what engram does when an old
  instinct meets new context).

**Natural fusion:** Layers 3 and 4 are already one field in applied topology —
cellular sheaves have Laplacians, persistent cohomology exists, the sheaf
Laplacian's harmonic space *is* the obstruction to global sections. Consistency
and persistence are not separate bolt-ons.

**The spine:** a combinatorial index (toric/FCA), with curved-metric detail
fibered over it (info-geometry/OT), checked for global consistency and
scale-persistence by one topological apparatus (sheaf/Hodge/persistence),
evolving as a dynamical system whose signatures are kept (rough paths/
attractors), wired by tropical computation and categorical inference.

## Recommendation & caution

**Build order:** (1) cellular-sheaf cohesion layer first — buildable now, fixes
a named task, composes with existing spectral machinery. (2) information
geometry second — fixes a *measured* defect (flat scores) rather than a
suspected one.

**Caution (for the toric collaborator too):** algebraic-geometry structures are
too rigid for the *whole* similarity manifold — no torus action on real
embedding space; toric varieties are special to the point of rationality. They
belong to the **index**, not the metric. The question that decides whether a
toric memory design is alive: **does the fan subdivide under data pressure, or
is it fixed in advance?** Static ontology is the failure mode;
subdivision-as-learning is the mechanism.

## Decision (2026-06-12): the fan subdivides, cohesion-gated

Andy chose subdivision-as-learning — "but perhaps in a way that maintains
cohesion." The failure mode he named: "really deep silly straw message board
arguments" = over-fragmentation, the index spawning spurious distinctions until
it loses the plot. That is overfitting in geometric clothing, and it's the same
gradient as the store's own "jump to the biggest version / spin frameworks /
build a clinic when invited to dance" pattern. So subdivision must be *regulated*,
and the regulator is the rest of the stack:

- **Cohesion-gated (Layer 3):** subdivide a cone/concept only when the
  conflation produces measurable sheaf-inconsistency — non-zero harmonic energy
  on the edges binding the conflated parts. If two episodes differ but gluing
  them breaks nothing, you do NOT split. A distinction that doesn't reduce global
  incoherence is, precisely, a strawman.
- **Persistence-regularized (Layer 4):** only honor a split that survives across
  scales. Splitting on noise is the messageboard.
- **Minimal resolution (Layer 1):** in toric terms, resolve the *actual*
  singularity, then stop — minimal blow-up, not maximal subdivision. A complexity
  cost (description length) must be paid per new ray.
- **The cohesion guarantee is structural:** a toric resolution comes with a
  *resolution morphism* back to the coarse object. Minting a peer concept must
  add the sheaf restriction maps connecting the new strata to the rest — you
  separate without disconnecting, and there is always a map home. "Maintains
  cohesion" = the morphism back always exists.

Net rule: **split iff keeping things together is provably breaking cohesion,
the split persists across scales, and a path back to the common ground is
retained.** Subdivision plus re-gluing, never subdivision alone.

## Next step

Not a build yet. The first build (cellular-sheaf cohesion + contradiction
localization over the engram graph) should go through brainstorm → spec → plan
like the lanes and assessment features did. This note is the saved frame it
starts from.
