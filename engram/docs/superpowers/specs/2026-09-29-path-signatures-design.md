# Path signatures (Layer 5 — Dynamics)

**Status:** testable prototype, observational, gates nothing.
**Module:** `paths.py` · **Tests:** `tests/test_paths.py`
**Framework:** `2026-06-12-mathematical-substrate-framework.md`, §5 Dynamics.

## Problem

The store keeps saying "I inherit the conclusions without the journey." Every
existing layer treats a set of episodes as a bag. Clustering, cohesion,
persistence and recall all ignore order. A session is a path, and so is the
sequence of episodes behind a semantic. Two agents can cover the same region by
different routes. A bag cannot tell them apart. A path signature can.

We use the rough-path signature because it is the standard, well-understood
tool for this: it is a universal, order-aware and reparametrization-invariant
summary of a path. We build on that existing mathematics rather than inventing
a trajectory measure.

## What is computed

- **Truncated signature**, levels 1–3 (default 3), is exact for piecewise-linear
  paths. A segment with increment `h` has signature `exp(h) = (h, h⊗h/2!,
  h⊗h⊗h/3!)`. Segments concatenate by the truncated tensor product (Chen's
  identity). Levels are arrays of shape `(d,)`, `(d,d)` and `(d,d,d)`. Level 0
  is implicit.
- **Derived quantities:**
  - The increment (level 1, meaning end minus start).
  - The Lévy area, which is the antisymmetric part of level 2 (the signed area,
    or which way the path turned).
  - The signature distance, which is the Frobenius distance over chosen levels.
  - The tortuosity, which is path length divided by displacement. A value of 1
    means straight. A value of `inf` means the path returned home.
  - The truncated inverse, which equals the signature of the reversed path.
- **Path construction:**
  1. L2-normalize the 768-d embeddings.
  2. Project them into a **centered** PCA basis (default `d=6`).
  3. Optionally time-augment by appending the step index scaled to [0,1]. This
     is on by default.
  4. Optionally add a basepoint by prepending the origin. This is off by
     default.
- **Store readers:**
  - `session_paths(conn)` builds one path per session from the vectorized
    episodes in `(created_at, id)` order. Sessions with fewer than
    `min_points` (3) vectorized episodes are skipped, and so are episodes with
    no session.
  - `semantic_journey(conn, semantic_id)` builds a path from a semantic's
    vectorized source episodes (`semantic_sources`) in the same order. This
    gives the semantic its journey as well as its conclusion.
- **`different_routes(paths)`** finds pairs with the same destination but
  different routes. With `L` as the pair's mean stream length:
  - `endpoint_gap = max(‖Δstart‖, ‖Δend‖)/L`. This also forces level 1 to be
    close.
  - `route_gap = √(‖ΔS₂‖²/L⁴ + ‖ΔS₃‖²/L⁶)`.

  A pair is reported when `endpoint_gap ≤ 0.25` and `route_gap ≥ 0.05`. The
  score is scale-free because level k scales as Lᵏ. Identical or resampled
  routes have a `route_gap` of 0.
- **`signature_of_vectors(vectors, basis)`** is a pure function. `reader.db`
  can use it once its passages have vectors.
- **Read-only CLI:** `python paths.py /path/to/copy-of-graph.db [--json]`. It
  reports:
  - the number of qualifying sessions
  - the tortuosity distribution
  - the most tortuous sessions
  - the top different-route pairs

  It opens the store with `file:…?mode=ro` plus `query_only`, loads sqlite_vec,
  and reports `total_changes` (always 0).

## Design choices

- **Shared basis.** A PCA fit chooses its own axes, so signatures drawn in two
  separately fitted bases are in different coordinate systems. Their distance
  is meaningless. `session_paths` fits one basis over all qualifying episodes
  and shares it across every session. `signature_distance` and
  `different_routes` raise an error when trajectories carry different bases.
  `semantic_journey` uses its own terms unless a basis is passed.
- **Centered basis, unlike sheaf.py.** Signatures without a basepoint are
  translation-invariant, so the common mean direction of the embeddings carries
  no route information. An uncentered SVD would spend its first axis on that
  direction. Component signs are fixed so results are reproducible. Distances
  do not depend on them anyway, because level k transforms by the orthogonal
  map Q^{⊗k}.
- **Time augmentation on by default.** Without it, a tree-like excursion
  (A→B→A) has the same signature as standing still. The whole point of this
  layer is to see a detour that came back. The time coordinate is the step
  index, not wall-clock time: pace between episodes is not modelled.
- **Tortuosity is spatial.** It is measured on the projected coordinates. Time
  and the basepoint are excluded.
- **Deliberately observational.** Nothing reads these numbers to decide
  anything, just as the margins layer gates nothing. There is no oracle for a
  "good" journey yet.

## Deferred

- **Log-signatures.** They give a minimal, non-redundant coordinate system,
  which would be better for learning or clustering on signatures.
- **Embedding reader.db.** It has no vectors, and this module does not embed.
  `signature_of_vectors` is ready for it once vectors exist.
- **Using journeys in recall or compression.** For example, a semantic could
  carry its journey signature, or recall could surface "the route to this
  conclusion". This waits on calibration against a real store copy.
- **Attractor and identity-basin modelling.** This is the other half of §5:
  cohesion as a stable basin and drift as a bifurcation.
- **Wall-clock time and level ≥ 4.** Only if levels 1–3 prove insufficient.
