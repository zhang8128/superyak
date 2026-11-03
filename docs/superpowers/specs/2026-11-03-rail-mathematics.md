# The rail, as mathematics: a research plan

Rio Grande, 2026-11-03. Andy: "remember the idea was that the sheaf cohomologies could form paths that you could A*
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

- **Memories and meaning.** A store `S` has a finite set of memories `M_S` and an embedding `φ: M_S → S^{d-1}`, the
  unit sphere in `R^d` (`d = 768`, nomic-embed-text-v1.5). The angle `θ(a, b) = arccos⟨φ(a), φ(b)⟩` is a metric on
  the sphere (the great-circle distance), so it satisfies the triangle inequality.
- **Use.** A session is a finite sequence `γ = (m_1, …, m_k)` of memories it touched, in order (the trail spec's
  *trail*). Its steps are the pairs `(m_i, m_{i+1})`.
- **The trail graph.** `G_S = (M_S, E_S)` is the directed multigraph whose edges are all steps of all sessions, each
  edge labelled by its session and time. Its *support* `n(a, b)` counts distinct sessions with the step `a → b`.
- **The trail category.** `C_S` is the free category on `G_S`: objects are memories, morphisms are paths, composition
  is concatenation. A *detour* is a 2-cell `α: p ⇒ q` between two travelled paths with the same endpoints (the trail
  spec's level-2 cell). With detours, `C_S` is a 2-category. Its higher cells (detours between detours) are what
  `categories.py` archives as opaque above dimension 2. This is the "n category theory graph": it isn't a table of
  facts, but the space of ways to get from one memory to another, with the ways themselves related.
- **Cost.** A path `p = (a_0, …, a_k)` costs `c(p) = Σ_i w(a_i, a_{i+1}) θ(a_i, a_{i+1})`, where the weight
  `w(e) ∈ (0, 1]` is how cheap that step has become. A footpath has `w = 1`. Annealing (section 3) lowers `w` on
  edges that use keeps confirming.

## 2. Routing, and why A* stays exact on rails

The goal is a set `Q = {n : θ(n, q) ≤ r}` around a query vector `q` (the trail spec's 6.3). Let `w_min = min_e w(e)`
over the graph (the cheapest rail).

**Proposition 1.** `h(n) = w_min · max(0, θ(n, q) − r)` is admissible for A* under the cost `c`.

*Proof.* Take any path from `n` to a goal `g ∈ Q`, so `θ(g, q) ≤ r`. By the triangle inequality along the path,
`θ(n, g) ≤ Σ_i θ(a_i, a_{i+1})`, so `w_min · θ(n, g) ≤ c(p)`. And `θ(n, q) ≤ θ(n, g) + θ(g, q) ≤ θ(n, g) + r`, so
`θ(n, q) − r ≤ θ(n, g)`. Then `h(n) ≤ w_min θ(n, g) ≤ c(p)`. ∎

So plain A* finds the cheapest route however cheap the rails get, as long as the heuristic carries the cheapest
rail's factor. **High-speed rail is a lower `w`, not a shortcut that breaks optimality.** The trail spec uses
`w ≡ 1` (hops priced by angle), where `h` is its 6.3 heuristic exactly.

## 3. Annealing within one store

An edge's weight is a state that use moves. Let the evidence for `e = (a, b)` be its sessions at times `t_1 < … < t_n`.

- **Temperature.** `T(e) = 1 / (1 + n_eff(e))`, where `n_eff` counts supporting sessions at least `Δ` apart (the trail
  spec's road rule uses `n_eff ≥ 2` with `Δ ≈ 17 h`). A footpath is hot (`T = 1/2` at one session), and every
  independent confirmation cools it.
- **Weight.** `w(e) = w_rail + (1 − w_rail) · T(e) / T_0`, clipped to `(0, 1]`, with `T_0 = 1/2` the temperature of a
  single trip. One trip leaves `w = 1`, and confirmations lower it toward `w_rail`.
- **Reheating.** A detour `α: p ⇒ q` that saves hops over a well-used `p` raises `T` on `p`'s edges in proportion to
  `q`'s support. A better way found heats the old one, so the graph keeps moving where agents are still learning.
- **Forgetting.** Support decays with time since last use, by ACT-R's power law as episodes do (engram's decay), so a
  rail nobody takes warms back into a footpath.

This is annealing in the literal sense: the energy `U = Σ_sessions c(γ)` of the routes agents actually take falls as
weights fall where they travel. Temperature keeps unconfirmed structure soft. The cooled skeleton (`T` low, `w` near
`w_rail`) is the store's road network.

## 4. Gluing stores: the sheaf, and what a rail is

The cover is a set of lighthouses `{S_1, …, S_m}`. The open sets are topics (`lighthouse_sheaf.py`): a topic is a ball
on the sphere, and a store covers it if it has hits above the coverage threshold. That module already defines the
sheaf on the complete graph of covering stores:
- stalks in a shared topic basis `R^k`;
- coboundary `(δx)_{ij} = x_j − x_i`;
- Laplacian `L = δᵀ W δ`, where `W` is the topic-scoped trust;
- energy in `[0, 1]`;
- `H^0` as the trust-weighted consensus, and the per-edge residuals locating the obstruction.

**A rail** is a road `(a, b)` of one store such that every covering store's section agrees at both endpoints' topics.
Here "agrees" means the sheaf energy at `topic(a)` and at `topic(b)` is below `ε`, and at least one other store also
has a road between memories in those two topics. The agreement is the gluing condition. A rail is a 1-cell of `C_S`
whose endpoints lift to a global section, so it lies in `H^0` over its endpoints and is confirmed by another store's
use. A rail's weight is lower still: `w(e) ← w(e) · (1 − agree(e))`, floored at `w_rail`, where
`agree = 1 − energy`.

**A seam** is where a store has a road but the energy at its endpoints is high, an `H^1` obstruction. A seam isn't an
error. It's where two lighthouses see a topic differently: worth routing a curious agent to, and never routed through
as a rail.

**Annealing the category graphs together** (Andy's phrase), as one dynamic. Each store anneals its own `C_S`
(section 3). The sheaf energy over shared topics is an extra term `U_glue = Σ_topics energy(topic)`. A step that
lowers `U_glue` is a rail confirmed somewhere else. Rails cool everywhere they glue, seams stay hot, and the global
road network is the low-energy part of the glued 2-category. Nothing is copied: each store keeps its own graph and
shares only what crosses a topic's restriction, under the owner's permissions (the permissions-by-place spec).

## 5. Statements to test, weakest first

- **C1 (use carries information).** On held-out sessions, the trail graph predicts a session's next touch better than
  meaning alone: hit@k of the true next memory among A*'s first `k` expansions (or among out-neighbours by support)
  beats hit@k among the `k` nearest memories by `θ`, at matched `k`.
- **C2 (cooling is signal).** Edges with lower `T` (more independent support) predict held-out steps better than hot
  ones: hit-rate rises with `n_eff`.
- **C3 (gluing adds range).** Across two stores, routes using rails reach a held-out goal in fewer expansions than
  either store's roads alone.
- **C4 (seams localize disagreement).** High-energy topics coincide with known contradictions between stores, as in
  the 2026-10-15 test: the brief rule, the watcher's rulings.

C1 is the gate. If it fails on real data, stop, and say so plainly.

## 6. The first experiment (E1), on data we have

Stores are nearly empty today: Rio Grande's Engram has 7 memories, which is too few. But the station has 2,629
messages in 7 rooms by 8 authors, and each author's run of messages in a room is a real path through meaning. So E1
uses the station as its corpus.

- **Memories:** messages. `φ` is the shared embedder (nomic, `search_document:` prefix), through its socket, so no
  second model loads on the Pi.
- **Sessions:** a maximal run of one author's messages in one room with gaps under 30 minutes. Steps go between
  consecutive messages of that run. A reply step (a message to the message it answers, when known) is a second edge
  type, reported separately.
- **Split:** by time. The trail graph is built from the first 80% of sessions, and the evaluation runs on the last 20%.
- **Baselines:** (i) k-nearest by `θ` over all earlier messages; (ii) the trail graph's out-neighbours ranked by
  support, then by `θ`; (iii) A* from the current message with the goal set around the true next message's vector at
  radius `r` (route length and expansions).
- **Measures:** hit@k for k in {1, 5, 10, 20} for (i) against (ii); mean expansions to the goal for (iii), against a
  similarity-only graph (each node linked to its 10 nearest); C2's hit-rate by `n_eff`.
- **Bounds:** read-only (`mode=ro` on the store). Bodies are read in batches and never written anywhere: only ids,
  vectors and counts go to a scratch SQLite file under `TMPDIR`, deleted at the end. Under 512 MiB resident. The
  report holds numbers only, no message text, because the rooms hold people's words.
- **Honesty:** report the null result if (ii) doesn't beat (i). Also report where it helps and where it doesn't (by
  room, by author kind: person or ship). Messages in a room are partly a conversation, so (ii) has an unfair
  advantage on reply chains. The reply-edge split separates that out.

## 7. What follows each outcome

- **C1 holds:** build the trail spec's step 1, but in this order, smallest first:
  1. the derivation (its tasks 1 to 4);
  2. the weights `w` and temperatures `T` of section 3, as stored state that its observer pass updates (a change to its
     tasks 6 and 7: they store roads as cells; here they also store `T`);
  3. A* with Proposition 1's heuristic (its task 10);
  4. the evaluation (its section 7, which is this plan's C1 on a real Engram store).
  Then sharing between two lighthouses ("memory follows the ship"). Then the rail spec: section 4 here, using
  `lighthouse_sheaf.py`, with C3 and C4 as its evaluation.
- **C1 fails:** stop the rail work. Write down why: is it the data (chat isn't memory use), the window or the embedding?
  Rerun E1 on a real Engram store once one has a few hundred memories, and only then decide.

## 8. What stays the same

Permissions by place govern what crosses a restriction map. Imprints govern any store copy. People's words stay
local to the experiment, and nothing here is enabled for live recall until its own evaluation passes, as the trail
spec requires.
