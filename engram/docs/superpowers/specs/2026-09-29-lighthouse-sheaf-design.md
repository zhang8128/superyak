# Lighthouse Sheaf: Cohesion Across Governed Stores

**Date:** 2026-09-29
**Status:** Testable prototype, observational. It gates nothing and never writes.
**Origin:** Layer 3 of the mathematical substrate framework
(`2026-06-12-mathematical-substrate-framework.md`), taken from one store
(`2026-06-13-sheaf-cohesion-design.md`, `sheaf.py`) to many independently
governed stores ("lighthouses", `lighthouse/README.md`).

## Problem

"Overlapping shared memory… You could trust the French cheese institute for
just cheese, or have it constantly compared with the Italian one." Two
things follow from that sentence:

- **Trust is scoped by domain.** A trust weight belongs to a topic, not to a
  lighthouse as a whole.
- **Where lighthouses overlap, their disagreement is computed, not resolved.**
  No lighthouse wins. The output says how much they disagree and between
  which pairs.

Also: **unexplored is not false.** A lighthouse with no section over a topic
is uncovered. It is reported and left out, and it never counts as dissent.

## Mapping

| Sheaf concept | Lighthouse reading |
|---|---|
| Open set | A topic, given as a query vector. A lighthouse *covers* it iff it has at least one hit at or above the coverage threshold. |
| Section over the open set | A covered lighthouse's top-k hits for the topic (default: `work` lane episodes, the shareable reference material). |
| Restriction map | Projection into a shared topic basis: the top-k principal directions of the union of covered hits, with no mean-centering (as in `sheaf.py`). Each lighthouse gets equal total mass (rows scaled by `1/sqrt(n_i)`), so one large store cannot define the basis by itself. |
| Stalk value `x_i` | The unit vector of the similarity-weighted mean of the lighthouse's L2-normalized hits, projected into the basis. Unit length bounds every residual in [0, 4]. `off_basis` reports how much of the section's mass the restriction discarded. |
| Cellular sheaf | The complete graph on covered lighthouses. Vertex and edge stalks are R^k, and the restriction maps are identities, because every stalk already lives in the shared basis. |
| Coboundary, Laplacian | `(δx)_e = x_j − x_i` and `L = δᵀ W δ`, where W holds each edge's trust weight (product of the endpoints' topic trust, or min). |
| H⁰ / consensus | The trust-weighted mean, which is the global (constant) section nearest the data in the trust-weighted norm. Each lighthouse's deviation from it is reported. |
| Obstruction | The harmonic (non-kernel) part of `x` (`harmonic_fraction`), plus per-edge residuals `‖x_i − x_j‖²` ranked to show which pairs disagree most. |

**Energy:** `xᵀLx / (4 Σ w_e)`, which lies in [0, 1]. The value is 0 iff
every stalk is equal, and 1 iff the stalks are antipodal. `energy_unweighted`
uses the same edges with every weight set to 1. Lowering trust moves the
consensus and the weighted energy, but it never hides the disagreement.

**Kernel check:** with identity maps and positive weights, `dim ker L = k`
(the constant sections). If zero-trust edges disconnect the graph, the
dimension is `k × components`. The dimension that depends on the data is
`glued_dim = k − rank{x_j − x_i}`: the number of basis directions on which
every pair agrees. The family is glued iff `glued_dim = k`, which holds iff
`x ∈ ker L`, which holds iff all stalks are equal. With m lighthouses,
`glued_dim ≥ k − (m − 1)`.

**Degenerate cases:**

- No covered lighthouse, or a single one: the family is trivially consistent,
  with energy 0 and no edges.
- Mismatched embedding dimensions are refused, because comparing them needs a
  non-identity restriction map (see Deferred).
- All-zero trust gives a weighted energy of 0 and an unweighted consensus,
  and both are noted in the output.

## Surfaces

- `glue(hits, scores=None, trust=None, min_score=None, edge_weighting="product")`
  is the pure core over in-memory arrays.
- `compare_stores(stores, query, k, lane, layer, ...)` is the disk adapter.
  It opens each `graph.db` with `Storage.open_read_only`. Because the lane
  filter is applied after the KNN, it overfetches until it has k matching
  hits, and it skips dormant episodes.
- CLI: `python lighthouse_sheaf.py --store a=/p/a.db --store b=/p/b.db
  --semantic a:ID [--episode a:ID] [--trust b=0.8] [--k 10]
  [--lane work|personal|any] [--layer episode|semantic] [--min-score S]
  [--edge-weight product|min] [--json]`. The topic is an existing memory's
  stored vector, so no embedding model is needed. When the query memory is
  in the searched layer, it is left out of its own store's section.

SQLite may create empty `-wal`/`-shm` side files when a read-only reader
opens a WAL store. The database bytes are unchanged, and the tests check
this with SHA-256 digests.

## Deferred

- **Non-identity restriction maps.** Real lighthouses have different schemas,
  ontologies, or embedding models. The "AOC vs DOP" problem is an example:
  French and Italian protected-origin categories do not line up one-to-one.
  Handling this needs edge stalks and restriction maps `F_{i→e} ≠ I`, learned
  or declared translations, and the Laplacian built from them. The coboundary
  here is already written in block form, ready for them.
- **Lighthouse publications instead of raw stores.** Compare what a
  lighthouse *publishes* (sealed Lighthouse artifacts, policy-scoped),
  not its private `graph.db`.
- **Receipts and permissions.** In Lighthouse, `recall` permission is not
  `inject_context` or `reshare` permission. A comparison needs its own
  permission and receipt, and computing a disagreement must not become a
  channel for resharing content.
- **2-cells.** Triangles comparing translations (`F_{j→k} ∘ F_{i→j}`
  against `F_{i→k}`) test whether the translations themselves are
  coherent. That becomes H¹ of the translation sheaf.
- **Gating.** Nothing consumes the result yet. Any use in recall ranking or
  trust updates needs its own calibration first.
