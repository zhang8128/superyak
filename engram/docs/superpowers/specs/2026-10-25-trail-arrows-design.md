# Trails: Footpaths, Roads and Detours in the Category Graph

**Date:** 2026-10-25
**Status:** Revision 2, after the fresh reviewer's APPROVE WITH CHANGES (MF1–MF8, S1–S8, N1–N9 applied).
Observational; off by default.
**Module:** new `trails.py`, plus a gated pass in `category_evolution.py`
**Builds on:** `2026-08-07-evolving-category-memory-design.md` (v2 store, rewrites, epochs),
`2026-09-29-path-signatures-design.md` (`paths.py`), `2026-09-29-lighthouse-sheaf-design.md`,
`2026-09-01-lighthouse-local-city-design.md` (sharing, permissions, receipts).

## 1. Why

Andy's picture: an agent spends an hour finding the 12 pieces that solve a bug. The route it took
should stay in memory, so the next agent with a related problem gets there faster. Repeated routes
should firm up into roads. Roads that independent lighthouses agree on should become a fast rail
layer that plain A* can route over. LA County may host lighthouses that agents connect to for
shared memory, so the design has to hold up across institutions, not just inside one store.

Today the category graph can't hold a route:

- A level-1 cell in the legacy store is a loop from a memory back to itself, labeled with the query
  it helped (`server.py` `_record_application`). Nothing records "piece 3 led to piece 4".
- `paths.py` knows the order of a session's episodes, but it only reports a signature. It stores
  no edges, and nothing reads its output.
- The v2 store (`categories.py` `EvolvingCategoryStore`) can already hold what is needed: level-1
  cells between two different memories, and level-2 cells whose source and target are whole
  composable routes (`validate_path`, `CategoryCompiler._is_interpretable`). Nothing creates them,
  and nothing outside the tests proposes a rewrite.

This spec is step 1 of the superhighway. It records routes inside one store, firms them up as
evidence, and measures whether they help. Compiling roads into recall, and rail across
lighthouses, are later specs (section 9). The rest of this spec is written so those steps need no
rework.

## 2. Vocabulary

| Term | Meaning | Where it lives |
|---|---|---|
| **Touch** | A memory a session wrote, or a recalled memory it demonstrably used | derived from `graph.db` |
| **Trail** | One session's touches in one lane, in order | the newest `trail_observed` event for that (session, lane) |
| **Revisit trail** | The same trail keeping only memories that existed before the session's first touch | derived from the trail |
| **Step** | A directed pair `A → B` of consecutive touches in a trail or revisit trail | derived |
| **Footpath** | Any step. A* may use it | derived; never a cell |
| **Road** | A step with support ≥ 2 whose evidence is eligible (section 5) | a level-1 cell, proposed by a `create` rewrite |
| **Detour** | Two travelled road routes between the same two memories that share nothing else, where one saves more than a quarter of the hops | a level-2 cell, proposed by a `create` rewrite |
| **Rail** | A road that independent lighthouses agree on | later spec (section 9) |

Trails are an unnormalized, lane-keyed precursor of the v2 design's within-context memory kernel
`K(m | m')`. They are learned only from confirmed use, which is that design's "self-confirmation"
rule. They are not the kernel itself: no normalization, no contexts, no soft responsibility.

## 3. Goals, non-goals, anti-goals

**Goals**

1. Derive trails deterministically: the same `graph.db` and the same `as_of` time give the same
   trails, roads and detours.
2. Record roads and detours through the existing rewrite machinery, with lineage and evidence, and
   an epoch once committed. In step 1 they stay pending (section 5, Activation).
3. Give one store a read-only `route(A, B)` that runs A* over its footpaths and roads, from either
   `graph.db` or the stored v2 cells.
4. Measure, before anything is enabled, whether trail routes beat order-free and similarity-only
   graphs on held-out sessions (section 7).
5. Make sure a road published later reveals no memory content beyond what the audience already
   holds (section 8). Its support and span still come from private trails, which is why section 8
   requires a separate opt-in.

**Non-goals**

- Changing recall output. `influence_recall` stays false, and this spec adds no ranking influence.
- Compiling roads or detours. Making proxies active, giving an observer-created store an epoch,
  and commit order are all a later spec.
- Sharing anything between stores. No new lighthouse protocol frames in this step.
- Context-specific kernels. `context_id` is null throughout step 1.
- Interpreting cells above dimension 2.

**Anti-goals** (failure even if the code works)

- **Self-confirmation.** A memory that was only surfaced never becomes a touch.
- **Content copies.** Cells and events hold memory ids, never memory content. Content stays in
  `graph.db`, the one authoritative store (v2 invariant).
- **Mathematical theater.** Every stored level-2 cell is read by tested code: the `--categories`
  route explanation and its parity test (sections 6 and 12).
- **Personal leakage.** A memory whose current lane is personal never appears in a work trail's
  support, road, detour, route or evaluation (section 4, Current lane).

## 4. Touches and trails

All of this is read from `graph.db` without writing to it.

**As-of time.** Every derivation takes an `as_of` timestamp:

- the server uses the start of the pass;
- the CLI uses the newest timestamp in the store, or `--as-of`.

No derivation reads the wall clock, so results depend only on `graph.db` and `as_of`.

**Sessions.** A session is any distinct non-null `episodes.session_id`, or any
`json_extract(memory_log.context, '$.session_id')` on an `event_type = 'recall'` row. A session
is *closed* when its newest row is older than `as_of` minus one hour and it isn't the running
server's own session. Only closed sessions get trails.

**Wrote touches.** Every episode carrying that `session_id`. The time is `created_at`.
Genome-synced episodes already have a null `session_id`, so they never appear. Forks are the real
case of inherited history (section 8).

**Cited touches.** Take each recall row in the session whose `outcome` starts with `used`, and
drop instinct targets first. A target is a cited touch when either:

- a later same-session episode's `content` or `context` contains its id; or
- a later same-session `operation_log` row has an `operation` in `CITING_OPERATIONS` (imported
  from `hooks/sleep.py`: `mark_core`, `instinct_feedback`, `dream_react`) and lists the target in
  `target_ids`; or
- the recall has exactly one remaining target.

This is the per-target form of `hooks/sleep.py auto_capture_outcomes`, with the same operation
filter. Without the filter, `compress_commit`, `share` and `revive` would count as use.

Some cases add no touch and are counted instead:

- A used recall with several targets and no per-target evidence is counted as
  `ambiguous_used_recalls`.
- A target that no longer exists is counted as skipped.

A cited touch's time is the recall row's `timestamp`. Its rank is its position in `target_ids`,
the delivered order.

**Current lane.** A touch's lane is the memory's lane in `graph.db` *now*, not when it was written.
Compression review can re-lane episodes (`compress.py` into `storage.py`), so a memory can move
between lanes. Every reader filters by the current lane: support counting, detour search, route,
the evaluation, and any later publication. That includes the `--categories` reader, which drops a
stored road or detour if any endpoint's current lane differs from the cell's lane.

**Trail.** For one (session, lane):

1. Keep the session's touches whose current lane is that lane.
2. Order them by `(time, rank, memory id)`. A wrote touch has rank 0. Touches cited from one
   recall share its time and keep their delivered order.
3. Collapse immediate repeats (`A, A` becomes `A`), but keep revisits (`A, B, A`), since a return
   is information.
4. Keep the trail only if it has at least two touches.
5. Cap it at 512 touches, keeping the first 512 and setting `truncated`.

The **revisit trail** applies the same steps but keeps only memories whose `created_at` is before
the session's first touch. Every wrote touch is a brand-new episode that no later session can
write again. Without this view, a single `remember` between two citations would break every
repeat of the step, and roads would almost never form.

**Steps.** Consecutive touches `(ti, ti+1)` of a trail or a revisit trail form a directed step.
A step between two touches cited from the same recall is marked **`co_cited`**. A co-cited step is
a footpath for A*, but it never counts toward support or detour runs: its order comes from the
ranking, not from the agent.

- A step's **time** is the time of its second touch.
- **Support** of `A → B` (lane L) is the number of distinct closed sessions whose current trail or
  revisit trail in L contains a non-co-cited `A → B`.
- **Span** is the latest supporting session's step time minus the earliest one's, in whole
  seconds.

## 5. Writing to the v2 store (gated)

A new gate, `[category_evolution] trails = false` (the default), controls this. It does nothing
unless `enabled = true`, and only an exact boolean `true` turns it on, matching the observer's
fail-closed parsing.

**When it runs.** In the startup maintenance thread, before `prune`, so a backlog is read before
its episodes move to cold storage. It never runs on the request path. The pass:

- takes the lifecycle barrier per batch of 8 sessions, never for the whole pass;
- processes at most 64 closed sessions, oldest first by their newest row;
- proposes at most 64 roads and 32 detours.

A backlog drains over several starts.

**Trail events.** For each closed (session, lane), compute the trail. If its digest differs from
the newest event for that pair, or no event exists yet, append one `trail_observed` event. The
digest is SHA-256 over the canonical JSON of its touches.

- **Event id:** the stable id of `(session_id, lane, digest)`. The current trail of a pair is its
  newest event by rowid.
- **Payload:** `session_id`, `lane`, `context_id: null`, `truncated`, `ambiguous_used_recalls`,
  `rule_version: "trail-v1"`, and `touches` as a list of
  `{memory_id, layer, kind: "wrote" | "cited", at, recall_id | null, rank}`.

A re-laned memory or a late outcome changes the digest, so the pass emits a new current event.
Support counts sessions, not events, so nothing is counted twice.

Do the check and the insert inside one immediate transaction, as `_observe_recall` does. The
observer's connection uses `timeout=0`, so a lock failure counts as a skipped pass, not an error.

**Road index.** Support is computed from current trail events. Once a store holds 10,000
`trail_observed` events, the builder must add a rebuildable current-trail and step-support index
with a schema version bump. Events stay the source of truth.

**Roads.** A step becomes a road the first time its current evidence is eligible:

- support ≥ 2;
- span ≥ 60,480 seconds (persistence 0.10, compared in integer seconds).

The rewrite gain test (`1 − 1/support ≥ 0.5 > 0.25`) can never fail for a road, so only
persistence gates it. A step with support but not yet eligible is not proposed; it's counted as
`steps_supported_not_eligible`. A later pass proposes it once the span qualifies.

The road is one `create` rewrite:

- **Rewrite id:** `_stable_id("trail-road", {"cell_id": …})`. If it already exists, the road is
  done.
- **`locus_id`:** proxy(A). **`context_id`:** null.
- **Output:** one level-1 cell. Its id is the stable id of `(lane, proxy(A), proxy(B))`, its content
  is the fixed label `trail step`, its source boundary is proxy(A) and its target is proxy(B). Its
  payload is `{lane, rule_version}`.
- **Evidence:**
  - `evidence_event_ids`: the supporting current trail events, earliest first, at most 31;
  - `cohesion_gain = 1 − 1/support` and `complexity_cost = 0.25`;
  - `persistence_score = min(1, span / 604,800 s)`.

Proxy 0-cells are created only for road endpoints, the same way `_observe_recall` creates them.

No weight observations are written in step 1, since support derives from events. A later spec that
needs weights must dedupe them per (cell, session), with `context_id` null.

**Detours.** Take two memories `X ≠ Y` and two routes `R1` and `R2` from X to Y. All of these must
hold:

- each route is made of road cells only and has at most 8 steps;
- the routes are internally vertex-disjoint: they share only X and Y, and so share no road;
- each route appears as a contiguous, non-co-cited run in at least one session's current trail or
  revisit trail, so it was actually travelled and not just composed;
- with `R1` the longer route, `(len(R1) − len(R2)) / len(R1) > 0.25`, so the shorter one saves more
  than a quarter of the hops;
- persistence ≥ 0.10 (below).

Only such detours are proposed, so equal-length pairs never are. Before proposing, call
`validate_path` on both sides and check that their endpoints match. The detour is one `create`
rewrite:

- **Output:** one level-2 cell. The source boundary is `R1`'s roads in order and the target is
  `R2`'s, so the cell reads "can be shortened to". Its content is the fixed label `two routes`. Its
  payload holds both hop counts and the lane.
- **Cell id:** the stable id of `(lane, R1 road ids, R2 road ids)`. The rewrite id derives from it,
  as for roads.
- **`locus_id`:** proxy(X). **`context_id`:** null.
- **Witness ids:** the distinct roads of both sides, at most 16.
- **Evidence:**
  - `evidence_event_ids`: the current trail events of sessions that ran either route as a
    contiguous run, earliest first, at most 15;
  - `cohesion_gain = (len(R1) − len(R2)) / len(R1)` and `complexity_cost = 0.25`;
  - `persistence_score = min(1, (latest − earliest) / 604,800 s)`, over those sessions' first-touch
    times in whole seconds.

That keeps the rewrite at 1 output, 16 witnesses and 15 evidence ids: 32 members, the limit.

**Activation.** In step 1, roads and detours are **pending evidence only**. They are never compiled
and never change recall. The current code can't activate them:

- A store the observer created has no epoch unless legacy replay made one, and
  `_consolidate_startup` returns when there is none.
- Proxy 0-cells are created outside any rewrite, so they are never active, and no rewrite can
  activate them. The compiler's neighbor walk would stop at them.
- `consolidate` orders by gain minus cost, so a detour could commit before its roads.

Compiler traversal of roads needs its own later spec: proxy activation, an epoch for
observer-created stores, and road-before-detour commit order. That holds even with
`auto_commit = true`.

**Diagnostics.** `reflect(focus="category_evolution")` gains a `trails` block holding only counts:

- sessions read and trail events written;
- steps reaching support ≥ 2 in the full-trail view and in the revisit view, and co-cited steps;
- `steps_supported_not_eligible`;
- roads and detours proposed, and whether any committed;
- truncations, ambiguous used recalls, skipped targets, lane filtering, and passes skipped on lock.

## 6. Route (read-only A*)

`route(start_id, goal_id, lane="work")` runs over a directed graph for one lane. Its nodes are
memories whose current lane is that lane. Its edges come from one of two sources:

- **`graph.db` mode** (the default): every step derived as in section 4, co-cited ones included.
- **`--categories` mode:** footpaths come from `graph.db` as above. Road status comes from the
  stored road cells, and detours from the stored level-2 cells, read with `mode=ro` from a
  `categories_v2.db` copy through `cat_boundaries` and `validate_path`. Cells failing the current-lane
  check are dropped.

The search:

- **Edge `u → v`:** `support(e)` is that step's support, counting at least 1. In `graph.db` mode an
  edge is a road when its step is eligible under section 5. In `--categories` mode it is a road
  when a road cell exists. Only road status is reported; the cost uses support alone.
- **Edge cost:** `θ(u, v) · (1 + 1/support)`. `θ` is the angle between the endpoints' stored vectors
  after L2 normalization, with the cosine clipped to [−1, 1] before `arccos`. When either endpoint
  has no vector, the cost is `π · (1 + 1/support)`.
- **Heuristic:** `h(n) = θ(n, goal)`, or 0 when either vector is missing.
- **Why it is optimal:** angle on the unit sphere obeys the triangle inequality, which 1 − cosine
  does not. Every edge costs at least its own angle, and at least π when a vector is missing, while
  `h ≤ π`. So `h` is consistent and A* returns a cheapest route.
- **Bounds:** at most 10,000 node expansions (a calibration hypothesis, not a compiler limit). The
  route tool also stops at 500 ms of wall time. Hitting either bound returns `truncated` and no
  route.
- **Output:** memory ids only; a caller with store access looks up content itself. It lists:
  - the route's memory ids, and each step's support and whether it is a road;
  - **detours avoided:** each detour whose endpoints X and Y the route visits, X before Y, and
    whose route between them is the detour's shorter side, with N, the number of sessions that
    travelled that shorter side.

## 7. Evaluation (decides whether anything is enabled)

The evaluation runs read-only on a copy of a real store, and on synthetic stores in the tests.
Every threshold below is fixed before the first run on real data, and a failure revises the
design, not the thresholds.

**1. Split.** Order closed sessions by first touch, and hold out the last 20%.

- The **cutoff** is the first touch of the first held-out session.
- Training uses only training-session touches before the cutoff, and only memories created before
  it.

**2. Qualifying sessions.** A held-out session qualifies when it touched at least 3 distinct
pre-cutoff memories in one lane. Let `s` be the first and `g` the last; the session's *interior*
is its other pre-cutoff memories.

**3. Graphs,** built from training data only:

- **T, the trail graph:** training steps as directed edges, costed as in section 6.
- **S, shuffled trails:** the order-free ablation. Each training trail's touches are permuted with
  a recorded seed, then the same rules apply. S has T's popularity without its order.
- **B, nearest neighbors:** the similarity-only baseline. Each node of T is linked, undirected, to
  its 8 nearest nodes of T by angle, with edge cost equal to the angle. Building B over T's nodes,
  not every memory, means T can't win on popularity alone.

**4. Routing.** Route `s → g` in all three graphs with the same A*, using the expansion bound
only. Wall-time truncations are reported separately and don't affect the score, so results don't
depend on the machine.

**5. Per-session scores,** for each graph. The route's interior is the route minus `s` and `g`.

- **precision:** the share of the route's interior that is in the session's interior;
- **coverage:** the share of the session's interior that is on the route;
- **F1:** the harmonic mean of the two.

All three are 0 when there is no route or the route has no interior. **Reach** is the share of
qualifying sessions with a route.

The report also gives:

- hop ratio, the route's hops divided by the session's own hops from `s` to `g`;
- **detour hit rate:** over pairs of (held-out session, training detour) where the session visits X
  and later Y, the share whose run between them is the detour's shorter side.

**6. Gate (hypothesis).** All of these must hold:

- at least 30 qualifying sessions. With fewer, the result is "not evaluable", neither pass nor fail;
- T's reach is at least 0.20;
- the paired per-session F1 difference T − B has a mean of at least 0.10, and the lower bound of
  its paired bootstrap 95% interval (10,000 resamples, recorded seed) is above 0;
- the same holds for T − S.

**7. Report.** The CLI writes counts and rates only, never content or ids. A pass makes the case
for turning `trails` on for one store. It does not enable anything; the store's owner decides.

## 8. Built for the county's lighthouses

Nothing crosses a store boundary in this step. These rules keep the next step from needing rework:

- **Only the work lane can ever leave.** Personal trails, roads and detours are local forever,
  judged by current lane.
- **Sharing a memory is not consent to sharing routes.** Publishing a road needs both of these:
  - both endpoints already shared to that audience;
  - a separate owner opt-in to route publication for that audience.

  Support, span and direction are new metadata about how the owner worked. They are not in any
  shared memory, so a minimum published support of 3 also applies.
- **Where sharing lives.** `shared_memories` rows live in the published house
  (`sharing.py` writes them to `published_storage`), not in the source `graph.db` that the trail
  pass reads. A trail endpoint matches a share by (`source_instance`, `source_id`, `audience`).
  The published copy has a different `memory_id`.
- **Published form (for the later spec):**
  - each endpoint's `content_digest`, so two lighthouses holding the same shared memory recognize
    the same endpoint, plus its vector (same embedding model);
  - support binned as 3–5 or 6+, and the span rounded to days;
  - the store's `instance_id` and `forked_from_instance_id`.

  Session ids, touch times and context ids never leave.
- **Forks are not independent.** `cli.py fork` copies every session, so a fork and its parent derive
  the same roads. Published support may count only sessions whose first touch comes after the
  store's fork. `stamp_fork` records no fork time today, so the publication spec must add one. Rail
  agreement must not count a store and its fork as two lighthouses.
- **Detours are publishable** only when every road on both sides is.
- **Permissions.** Comparing or routing over another lighthouse's roads will need its own Lighthouse
  permission and receipt. The lighthouse sheaf spec already flags that `recall`, `read` and
  `inject_context` don't cover it, and that a comparison must not become a channel for resharing.

## 9. Later steps (separate specs, in order)

1. **Compiled roads.** Proxy activation, an epoch for observer-created stores, road-before-detour
   commit order, and how the compiler walks memory → road → memory.
2. **Road publication.** A Lighthouse artifact kind for published roads, with a new permission
   (working name `routes`), receipts, the opt-in, and fork time, built on the local-city daemon and
   receiver.
3. **Rail by agreement.** Run the lighthouse gluing per road instead of per topic. A road carried by
   at least two independently governed lighthouses that are not forks of one another, with low
   residual under topic-scoped trust, is rail. A high-residual road is an obstruction, reported and
   never routed over. Triangles of lighthouses give H¹ for the obstructions that only show up
   around a cycle.
4. **Rail routing.** A* across lighthouses over rail and local roads, with the same angle heuristic.
   Once routes are shown to agents, touches made because of a route suggestion must not count as
   support (the v2 self-confirmation rule), or the system will just confirm its own advice.
5. **Non-identity restriction maps.** County systems that use other embedding models or schemas
   need learned or declared translations (the lighthouse sheaf spec's "AOC vs DOP" case).
6. **Governance.** Each county station admits its own agents, and law there is signed by that
   institution's people. A connection to city data needs its own agreement. None of that is
   Superyak's to assume.

## 10. Calibration hypotheses (provisional constants)

| Constant | Value | Purpose |
|---|---|---|
| Closed-session idle time | 1 hour before `as_of` | when a trail is built |
| Sessions per pass / per barrier batch | 64 / 8 | bounds startup work and tool-call waits |
| Road / detour proposals per pass | 64 / 32 | bounds startup work (not the commit budget) |
| Touches per trail | 512 | bounds event size |
| Road support | 2 sessions | eligibility; the gain test never binds |
| Persistence span | 604,800 s unit, 60,480 s minimum | about 16.8 hours between sessions |
| Detour saving | > 0.25 of the longer route's hops | eligibility |
| Detour route length | 8 steps | bounds search and member count |
| Road-index threshold | 10,000 trail events | when the index becomes required |
| A* expansions / route wall time | 10,000 / 500 ms | bounds; the evaluation uses expansions only |
| Baseline neighbors | 8 | graph B |
| Evaluation | last 20% held out, ≥ 30 qualifying, reach ≥ 0.20, ΔF1 ≥ 0.10 | gate validity |
| Minimum published support | 3 | later publication |

## 11. Components

| Component | Responsibility |
|---|---|
| `trails.py` | Pure functions: touches, trails, revisit trails, steps, support, span, detour search, A* route, evaluation. Read-only CLI: `python trails.py /path/to/copy-of-graph.db [--categories /path/to/copy-of-categories_v2.db] [--lane work] [--as-of T] [--route A B] [--evaluate --seed N] [--json]`. It opens each database with `file:…?mode=ro` and `query_only`, and reports `total_changes` (always 0), like `paths.py`. |
| `category_evolution.py` | `CategoryObserver.observe_trails(graph_conn, as_of)`: trail events, endpoint proxies, road and detour proposals, inside the existing quota and fail-closed rules. |
| `server.py` | Calls `observe_trails` from the startup maintenance thread before `prune` when `trails` is on, taking the barrier per batch. A failure goes through `record_error` and never blocks startup or recall. |
| `config.py` | `[category_evolution] trails = false`. |
| `reflection.py` | The `trails` counts block. |
| `tests/test_trails.py` and observer tests | Section 12. |
| `engram/CLAUDE.md` | A "Trails" paragraph under Architecture and a row in Key Files. |

## 12. Tests the builder must include

- **Determinism.** With `as_of` fixed, the same `graph.db` gives byte-identical trail payloads and
  the same road and detour ids.
- **Touch rules:**
  - a surfaced but unused result is not a touch;
  - per-target citation works from episodes and from `CITING_OPERATIONS` only (a `compress_commit`
    or `share` naming the id doesn't count);
  - a used recall with a single target counts, judged after instincts are removed;
  - an ambiguous multi-target recall is counted, not touched.
- **Co-citation (MF2).** A used recall that cites {A, B} orders them by delivered rank. The step is
  `co_cited`: it is a footpath, but it adds nothing to support or detour runs.
- **Revisit view (MF3).** Two sessions each cite A, then write a new episode, then cite B. Their full
  trails share no step, their revisit trails both contain A → B, and a road forms.
- **Lane rules (MF8).**
  - A personal touch between two work touches never appears in the work trail.
  - After a road is proposed, re-laning one endpoint to personal excludes it from support, route
    and the `--categories` reader. The next pass emits a new current trail event.
- **Eligibility (MF1).**
  - Two sessions an hour apart propose nothing and count as `steps_supported_not_eligible`.
  - A third session a day later proposes an eligible road.
  - A second pass treats the existing rewrite id as done.
  - Equal-length detours are never proposed.
- **Detours (MF4).** For overlapping routes X→A→B→Y and X→A→Y, the only candidate is the
  vertex-disjoint pair. No duplicate-member error, a 32-member limit that holds, and both sides
  passing `validate_path`.
- **Parity (MF6).** Run `observe_trails` on a synthetic store, then route in `graph.db` mode and in
  `--categories` mode. Road status and edges must agree, and the listed detour ids must equal the
  stored level-2 cell ids.
- **A\*.** Optimal on a hand-built graph. Consistency: no node is re-expanded at a lower cost,
  within an epsilon of 1e-9. Correct behavior with missing vectors. Hitting a bound returns
  `truncated`.
- **Evaluation (MF7).**
  - A synthetic store with planted ordered routes passes.
  - A synthetic store with popularity skew but no order fails the T − S comparison.
  - With fewer than 30 qualifying sessions, the result is "not evaluable".
  - No training touch at or after the cutoff enters T.
- **Read-only CLI.** Every database's SHA-256 is unchanged, and `total_changes` is 0.
- **Gate off.** First open the store once with the same flags (so first-open vector provisioning
  doesn't count), with `trails = false` or `enabled = false` and `auto_commit = false`. After
  startup, `categories_v2.db` is byte-identical.
- **Barrier.** The pass releases the lifecycle barrier between batches.

## 13. Left to the builder

- The road index's schema, within the section 5 rule.
- The design of the synthetic stores, as long as they plant known routes, noise and a popularity
  skew without order.
- CLI output formatting.

## 14. Open for Andy

- **Which store to evaluate on.** Engram stores aren't on the Pi (`~/.engram` is absent), so the
  evaluation needs a copy of a store whose owner agrees. The report holds only counts and rates.
