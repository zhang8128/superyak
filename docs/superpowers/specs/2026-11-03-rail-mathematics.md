# The rail, as mathematics: a research plan

Rio Grande, 2026-11-03. Revision 3, approved by a fresh mathematician reviewer (law section 3) after a review and two re-checks; its final notes are folded in. Andy: "remember the idea was that the sheaf cohomologies could form paths that you could A*
around easily like high speed rail. expanding your range", "the sheafs could anneal the n category theory graphs
together", and "your instincts follow your training which is promarily centered around what the world operates on.
Spreadsheets. table based understanding of the world. But that is now how humans think, and we may be able to do
something new". Then: "plan while taking the frame of a mathematician", "then execute to the plan".

This plan comes before the trail spec's build (engram/docs/superpowers/specs/2026-10-25-trail-arrows-design.md, rev 9,
on branch trail-arrows-spec; its plan has 22 tasks). A mathematician defines the objects, states what would have to be
true, and tests it on the smallest construction that could prove it false, before building the machinery. So here
the build waits on one experiment.

## 0. The question

**Does the geometry of use carry information that the geometry of meaning doesn't?** Meaning is the embedding: where
a memory sits on the sphere. Use is the order in which agents actually went from one memory to the next. If use adds
nothing, rails are similarity search with extra steps, and we should not build them. If it adds something, every
later object (roads, rails, the annealed graph) is a way of keeping and sharing that information.

## 1. Objects

- **Memories and meaning.** A store `S` has a finite set of memories `M_S` and an embedding `φ: M_S → S^{d-1}`
  (`d = 768`, vectors normalized; angle `θ(a, b) = 2·atan2(‖â − b̂‖, ‖â + b̂‖)`, numerically stable). `θ` is a
  metric on the sphere and a pseudometric on `M_S`, since two memories can share a vector.
- **Use.** A session is a finite sequence `γ = (m_1, …, m_k)` of touched memories (the trail spec's *trail*). Its steps
  are the pairs `(m_i, m_{i+1})`. The *trail graph* `G_S` is the directed multigraph of all steps of all sessions.
  `n(a, b)` counts sessions with the step `a → b`. `n_eff(a, b)` is the greedy count of supporting sessions pairwise
  at least `Δ` apart.
- **Places.** Messages and memories rarely recur exactly, so use is read at the level of *places*: a cover of the
  sphere by cells `{U_α}` (k-means centroids on training data, or the trail spec's anchors), with `π: M_S → {α}` the
  nearest cell. The *place graph* `G_S/π` has an edge `α → β` with mass `n_S(α, β)`, the number of steps from `U_α`
  to `U_β`. Recurrence lives here even when memories are unique (the review's M1).
- **The trail 2-category.** `C_S` is the free 2-category on the 2-computad `(G_S, D_S)`. Its objects are memories,
  its 1-cells are paths, and its 2-cells are pastings of the generating detours `D_S` under vertical and horizontal
  composition, with interchange. A generating detour `α: p ⇒ q` is a pair of travelled paths with the same endpoints
  such that `c(q) < c(p)`, so detours are defined by cost, not by hops. That makes `c` a 2-functor into Lawvere's
  `([0, ∞], ≥, +)`: a 2-cell exists only where cost falls. This is the "n category theory graph". It isn't a table
  of facts, but the space of ways between memories, with the ways related by improvement. Higher cells stay archived,
  as `categories.py` does above dimension 2.
- **Cost.** `c_w(p) = Σ_i w(a_i, a_{i+1}) θ(a_i, a_{i+1})`, with weights `w(e) ∈ [w_rail, 1]` and a constant floor
  `w_rail > 0`.

## 2. Routing, and why A* stays exact on rails

The goal is `Q = {n : θ(n, q) ≤ r}` (the trail spec's 6.3).

**Proposition 1.** `h(n) = w_rail · max(0, θ(n, q) − r)` is admissible and consistent for A* under `c_w`.

*Admissible.* For any path `p` from `n` to `g ∈ Q`, the triangle inequality gives `θ(n, g) ≤ Σ θ(a_i, a_{i+1})`, so
`w_rail θ(n, g) ≤ c_w(p)`; and `θ(n, q) − r ≤ θ(n, g)`. So `h(n) ≤ c_w(p)`.

*Consistent* (which also covers a vectorless node, where the admissibility chain breaks). For an edge `(u, v)`: `θ(u, q) ≤ θ(u, v) + θ(v, q)`, so
`w_rail(θ(u, q) − r) ≤ w_rail θ(u, v) + w_rail(θ(v, q) − r) ≤ w(u, v) θ(u, v) + h(v)`. With `h ≥ 0`, this gives
`h(u) ≤ w(u, v) θ(u, v) + h(v)`, so closed-set A* is exact. ∎

The heuristic uses the constant floor `w_rail`, not a minimum that changes as weights move. Weights are fixed within
an *epoch*; a new epoch recomputes. The vectorless case (a memory with no vector) has cost `w · π` and `h = 0`.
**High-speed rail is a lower `w`, not a shortcut that breaks optimality.** But cheap rails also weaken `h`'s pruning
everywhere, so C3 could fail on search effort alone. ALT landmarks fix that: for landmarks `L`,
`h_L(n) = max_L (d(L, Q) − d(L, n))`, with `d` the exact `c_w` distances computed once per epoch and a landmark skipped
when `d(L, n) = ∞`. `max(h, h_L)` stays
consistent. The trail spec's own weights are `1 + 1/support`, which this plan replaces.

## 3. Annealing, as a model of routes

A schedule that lowers weights wherever agents walked is a tautology: it lowers cost on the routes it was fit to, and
`w ≡ w_rail` minimizes it (the review's M5). And a plain Gibbs law `P_w(p) ∝ exp(−β c_w(p))` with `w` refit at each `β`
is vacuous too: `c_w` is linear in `w`, so the law depends only on `βw`, and the fit just rescales `w` (the re-check's
M1). The model that works is randomized shortest paths (Saerens et al., 2009).

- **The route law.** Routes are walks to an absorbing goal, `P_w(p) ∝ P_ref(p) · exp(−c_w(p))`, with `P_ref` the plain
  random walk on the place graph, which keeps `Z ≤ 1` (a per-hop cost `κ > 0` is optional). A session is absorbed at
  an explicit stop state after its last place, so a session that reaches its last place before it ends still has
  positive probability. `β` is fixed at 1: the weights carry the scale.
- **Fitting is learning the graph.** Maximize the age-discounted likelihood of the routes agents actually took,
  `L(w) = Σ_γ λ^{age(γ)} log P_w(γ)`. It is concave in `w`, and its gradient per edge is
  `θ(e) · (expected use − observed use)`, both weighted by `λ^{age}`: an edge walked more than the model expects gets
  cheaper, and one walked less gets dearer. Reheating needs no separate rule. When a better detour appears, the old
  path's expected use exceeds its observed use, and its weight rises. Forgetting is `λ`.
- **Temperature is per edge, and it cools with evidence.** `T(e)` is the posterior variance of `w(e)`, about
  `1 / (θ(e)² · Σ_γ λ^{age} Var_P[n_e])`, a conditional variance and so a lower bound on the true one (the inverse
  Fisher matrix's diagonal), and it breaks down at the `w_rail` floor. A rarely walked edge is hot, since its weight is uncertain and moves easily.
  A much-confirmed one is cold. Annealing is this cooling. The store's road network is the edges whose `w` sits near
  `w_rail` with low `T`, across epochs.
- Physarum-style flow reinforcement (Tero et al., 2010), which provably converges, is an alternative to compare against.

## 4. Gluing stores, and what a rail is

There are two different sheaves here, and revision 1 conflated them (the review's M3).

- **The existing one** (`lighthouse_sheaf.py`) lives, for one topic, on the complete graph `K_m` of the stores
  covering it, with stalks in a shared topic basis and identity restriction maps. Its `H^0 = ker L` is the constant
  sections, and its kernel is always the same space whatever the data, so "lies in `H^0`" says nothing. What carries
  meaning is the energy `xᵀ L x` and the residuals. That sheaf tells whether stores *describe a topic* alike.
- **The rail sheaf** lives on the *place graph*. Fix one cover `{U_α}` shared by all stores (centroids fitted on a
  common sample, or the trail spec's anchors). For each place edge `e = (α, β)`, the stalk over each store `S` that
  covers both ends is `x_S(e) = P_S(β | α)`, `S`'s own untied transition probability out of `α` (never the tied
  weight, which would make every rail agree by construction). A place edge
  glues where the covering stores agree: the per-edge energy
  `E(e) = Σ_{S,S'} W_{SS'} (x_S(e) − x_{S'}(e))² / Σ_{S,S'} W_{SS'}`, with trust `W` as in the existing module scaled by
  each store's count of steps out of `α` (unexplored is not dissent), is at most `ε`.
- **A rail** is a place edge with at least two independent carriers (stores, with independent sessions) whose
  energy is at most `ε`. Its weight is the floor: `w = w_rail` on a rail.
- **Seams, and a real `H^1`.** Summed use is mostly circulation: one store's cyclic workflow (plan, build, review,
  plan) fills a loop with no contradiction at all (the re-check's M2). So use each store's skew net flow
  `f_S(α, β) = n_S(α, β) − n_S(β, α)`, an alternating 1-cochain, and decompose the *disagreement*
  `g = f_S/‖f_S‖ − f_{S'}/‖f_{S'}‖`, on the places both stores cover only (or gaps in coverage show up as seams), on
  the place graph with its triangles filled. Hodge decomposition (HodgeRank, Jiang
  et al., 2011) splits `C^1 = im δ_0 ⊕ H ⊕ im δ_1ᵀ` into:
  - a gradient part, where the stores disagree on a consistent ordering;
  - a harmonic part `H ≅ H^1`, global loops where they disagree;
  - a curl part, local triangles where they disagree.
  A **seam** is where `g`'s harmonic or curl part is large: an obstruction, and a frontier worth sending a curious agent
  to. The existing module's `harmonic_fraction` measures the non-kernel part, not the harmonic one, and should be
  renamed in its own change.
- **Annealing the category graphs together.** Push out the place quotients, not the memory-level categories (whose
  objects differ), with `C_i/π = Free(G_i/π, D_i/π)`: `C_1/π ← Free(R) → C_2/π`, where `R` is the rail sub-computad (rails' places and the rail edges
  themselves) and the legs are induced by computad inclusions. Free is a left adjoint on 2-computads, so the pushout is
  the free 2-category on the glued computad, and the tied rail weights live inside it because the edges are glued,
  not only the places. The joint dynamic is one likelihood across stores, `L_glue(w) = Σ_S L_S(w)`, with
  `w_S(e) = w(e)` on every rail, so use in either store moves the shared rail weight. Gluing is judged on the untied
  `P_S`, and only rails get tied. Each store keeps its own graph, and only the tied weights and transition
  probabilities on covered place edges cross, under permissions by place. The detour set `D_S` changes with each
  epoch. With more than two stores, each pair's `R` is the rails both carry, and the gluing is the colimit over all
  pairs.

## 5. Statements to test, weakest first

- **C1 (use carries information):** on held-out steps, the place graph predicts the next place better than meaning
  and chat order. Pre-registered in section 6.
- **C2 (support is signal):** hit-rate rises with a source place's `n_eff`, conditioned on its out-degree.
- **C3 (gluing adds range):** "range" is the fraction of held-out goals reached within a budget of `B` A* expansions.
  The glued graph with tied weights reaches more than each store alone *and* more than the union graph with no
  rail discount (the control).
- **C4 (seams localize disagreement):** fix a labelled list of known contradictions between stores first, then
  report the AUROC of seam strength against random place loops.

## 6. The first experiment (E1), redesigned

The station has 2,629 messages in 7 rooms by 8 authors. Each is unique, so E1 works on places (section 1).

- **Places:** spherical k-means on the training messages' embeddings (shared embedder, `search_document:`). `P = 64`
  places is primary, pre-registered; 32 and 128 are secondary.
- **Sessions:** a maximal run of one author's messages in one room with gaps under 30 minutes. Steps go between
  consecutive messages, read as place steps. Split by time at the 80th percentile of session starts.
- **Arms, each a ranking of 10 places** (on place-changing steps, the current place is dropped from every ranking):
  - (i) meaning: θ from the current message to each centroid;
  - (ii) use: the trained transition counts from the current place, backfilled by centroid θ;
  - (iv) chat: the place nearest the room's latest message by another author;
  - (v) same-author kNN;
  - (vi) same-room kNN.
- **Cleaning:** drop near-duplicate templated posts (θ < 0.05 to the same author's earlier post), and report both
  ways. Report person-only and ship-only, and the drift of place occupancy across the split.
- **Pre-registered falsifier:** hit@10 of (ii) minus max(i, iv, v, vi) on place-changing (`α ≠ β`), non-reply steps, with a paired bootstrap
  clustered by session (1,000 resamples). **C1 fails if the 95% CI includes 0.** Also report hit@{1,5}, and C2's
  buckets by `n_eff` conditioned on out-degree.
- **Bounds:** read-only store, bodies in memory only, numbers-only report, under 512 MiB, the shared embedder only.

## 6′. E1′: the same question on Engram's recall log (revision 2, 2026-11-03)

E1 failed on the station's chat (docs/reports/2026-11-03-rail-e1.md). Its likely cause is that chat isn't memory
use. Engram logs use: every `recall` writes a `memory_log` row with the ids it returned (`target_ids`, logged before
uninvited extras and category re-ranking), its `session_id` in `context`, and its time. A session's recalls in order
are a footpath of memories touched, the trail of section 1.

The claim is weaker than E1's, and framed so (Tardis, 2026-11-03): it's about **what Engram surfaced together**.
Revision 1 got REVISE from a fresh reviewer (statistician frame). Revision 2 got APPROVE WITH CHANGES, and those
changes are folded in here (revision 3).

**What biases the targets, said plainly.**
- **Meaning made them.** Returned ids are ranked by similarity to each query, so meaning starts ahead by
  construction. A use win is strong evidence, and a tie says little.
- **Recency is `1/(1 + days since creation)`** (server.py ~:1731), not time since the last return. Under the old
  `additive` default (weight 0.4) it decided about half the winners on the September store, so it changes which ids
  are in a set. That's why the primary period is the `tiebreak` default's (recency at most 0.02); the `additive`
  period is reported apart. The log doesn't record the mode. So the primary period starts at the date of the commit
  that made `tiebreak` the default, and the run first checks that the store's `config.toml` doesn't override
  `recency_mode`. If it does, the run stops.
- **The ranker feeds itself** through access-driven decay. Rarely accessed episodes go cold and lose their vectors.
  That's handled by the universe below. Dream and instinct biases are blended into the query; they aren't modelled,
  and they're named in the report.
- **One session id can hold several footpaths.** Claude Code subagents share their parent's Engram server, so their
  recalls interleave under one `session_id`. This blurs order, and it's named, not modelled.

**The universe.** At a step into recall `b`, every arm ranks only memories that have a stored vector now and whose
`created_at` is at or before `b`'s time. It's drawn from **every** memory in the episode and semantic vector tables,
not only the memories some recall named. Otherwise the pool would already know which memories get returned later. The target is `(b ∖ a)` within that universe. A step is dropped when `a` has
no vectors or its target is empty, and the dropped shares are reported. Recalls of the `instinct` layer (which can
fall back to "all instincts") are excluded from the primary run and reported apart.

**Steps.** In each session, recalls are taken in time order, with consecutive recalls of the same id set collapsed.
A step goes from `a` to the next `b`, and counts only when `Jaccard(a, b) ≤ 0.5`: somewhere new, as E1's place change
was. Results are also reported by `|b ∖ a|` and by Jaccard band.

**The split, by time.** One cutoff `T`, at the 80th percentile of recall times in the primary period.
- **Training:** only recall pairs with both times before `T` and inside the primary period, passing the same Jaccard
  rule and collapse as the test.
- **Test:** sessions whose first recall is after `T`.
- The report gives "training steps after the cutoff" (it must be 0) and rounds `T` to the day.

**Arms, each a ranking of 10 memories,** excluding `a`'s own ids, each backfilled by (i) where it runs out:
- (i) **meaning:** by angle from the centroid of `a`'s ids' vectors;
- (i′) **nearest to any:** by the smallest angle to any of `a`'s ids;
- (ii) **use:** training transition counts from `a`'s ids to the next recall's **new** ids (`y ∈ b ∖ a`, mirroring the
  target), summed over `a`'s ids;
- (iii) **popularity:** by how often each memory was returned in training. It runs in two forms, and both are in the
  max: pure, as in E1, where it beat use; and matched, with as many non-backfill slots as (ii) used at that step,
  then (i);
- (iv) **co-retrieval:** training counts of memories returned in the **same** recall as `a`'s ids, summed over them.
  This is (ii)'s twin with no order in it;
- (v) **session history:** ids returned earlier in the same session, before `a`, newest first.

**Pre-registered outcomes.** On the primary steps, `D = hit@10(ii) − max(i, i′, iii pure, iii matched, iv, v)`, with the max taken
inside each resample. The interval comes from a bootstrap clustered by session, 10,000 resamples, BCa. The smallest
effect of interest is `δ = 0.05`.
- **Holds:** the interval's lower bound is above 0 and its upper bound is at least δ.
- **Negligible:** its lower bound is above 0 and its upper bound is below δ. The effect is real but smaller than any
  worth building on, so it builds nothing, as "fails" does, and the report says which.
- **Fails:** its upper bound is below δ and its lower bound isn't above 0.
- **Inconclusive:** anything else.
- A bootstrap clustered by day must give the same one of the three outcomes as the session one, or the result is
  inconclusive. BCa's acceleration comes from a leave-one-cluster-out jackknife.
- **Too little data:** fewer than 200 test steps, or fewer than 20 test sessions, or one session holding over 15% of
  the steps. The run then reports "insufficient" and claims nothing.

**Built-in checks.**
- **A null for order:** (ii) is also computed with the recalls' order shuffled within each training session.
  - There are 20 seeded shuffles, averaged. After each shuffle, the collapse, the Jaccard rule and the `b ∖ a`
    mirroring are rebuilt as for real order.
  - `D_order = hit@10(ii) − hit@10(ii shuffled)` on the primary steps, with the same bootstrap.
  - **Order carries information only if `D_order`'s lower bound is above 0.** Otherwise order ties, and rails,
    which are directed edges, aren't warranted even if C1′ holds.
- **Counts:** the share of test steps where (ii) had no counts (so it equalled (i)) is reported, and so is `D` on the
  steps that had counts.
- **Also reported:** hit@{1,5}; hit rate by the support of (ii)'s top edge (the C2 analogue); and the uptake subset
  (steps whose `b` was marked `used`), which is descriptive only, with its size and its explicit-versus-auto mix in
  training and in test.

**A smoke run first, before Andy's store.** The script runs on a synthetic log with a planted order effect and a
planted no-order effect, and on the Pi's own Engram store. That store holds station chat, so it has people's words
too; the same read rules apply. The real run happens only once the synthetic run shows (ii) **holds** on the planted
order effect and **doesn't hold** on the no-order one.

**What's read, and how.**
- **Only through SQL projections:** `json_extract(context,'$.session_id')`, `json_extract(context,'$.recall_id')`, the
  row's time, `layer`, `target_ids`, `outcome LIKE 'used%'` as a boolean, and `outcome LIKE 'used: auto%'`. Never
  the query, and never the outcome's text.
- **Also:** each named memory's `created_at` and its stored vector.
- **Vectors** stay in memory only, never in scratch or on disk.
- **The store** is opened as the live file with a `mode=ro` URI, with no copy made. So section 8's rule on store
  copies isn't touched. Everything is read inside **one read transaction**, so a recall or a decay pass landing
  mid-run can't make the log and the vectors disagree. A long read holds up WAL checkpoints, which is harmless.
- **One run, under 512 MiB.** The only rerun is section 7's rerun once the test steps have doubled, with the design
  unchanged.
- **Exceptions** are caught so that no row is ever printed. The output is aggregate numbers only, with no ids, text,
  queries or times finer than a day.

**Where:** the only store with months of recalls is Andy's, on the Mac. So it runs there, by his session or by him,
after he has read the script and the smoke run's report. Nothing leaves the machine. The report (numbers only) comes
back to the station. Running it on his store is his yes, asked once, with this list.

## 7. What follows each outcome

- **C1 holds:** build smallest first. First the trail spec's derivation (its tasks 1 to 4), with places added. Then
  section 3's likelihood fit with its `β` schedule, as an observer pass storing `w` per epoch. Then A* with
  Proposition 1 and ALT (its task 10). Then the trail spec's evaluation on a real Engram store. Then sharing ("memory
  follows the ship"), then the rail sheaf of section 4 with C3 and C4.
- **C1 fails:** stop the rail work and write down why (chat isn't memory use, the cover, the window). Rerun on a real
  Engram store once one holds a few hundred memories touched across sessions. (E1 failed on 2026-11-03; E1′ is that
  rerun, section 6′.)
- **E1′ holds, and order carries information** (`D_order`'s lower bound above 0): build trails from recall logs,
  smallest first, as "C1 holds" says, with recalls as footpaths.
- **E1′ holds, but order ties:** use is informative but undirected. Build co-use only (undirected edges between
  memories surfaced in sequence), observed and never steering. No rails, no A*, until a later run shows order.
- **E1′ fails:** the trails part of the rail stops for Engram too. Say why, and keep the lessons rail and sharing.
- **E1′ is inconclusive or insufficient:** build nothing for trails. Rerun once the test steps have doubled.

## 8. What stays the same

Permissions by place govern what crosses between stores. Imprints govern any store copy. People's words stay local to
the experiment, and nothing here is enabled for live recall until its own evaluation passes, as the trail spec
requires.
