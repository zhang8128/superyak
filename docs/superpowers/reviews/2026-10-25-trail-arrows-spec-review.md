# Trails spec: fresh reviewer verdicts (station law section 3)

Spec: `engram/docs/superpowers/specs/2026-10-25-trail-arrows-design.md`. Reviewer: a fresh agent on the Pi that took no part in writing the spec.

## First review (revision 1, uncommitted draft)

VERDICT: APPROVE WITH CHANGES

Spec: `engram/docs/superpowers/specs/2026-10-25-trail-arrows-design.md` (branch `trail-arrows-spec`, uncommitted).
Approval holds only once MF1–MF8 are applied as written below. Apply the S items in the same revision.
File:line references are relative to `/home/andy/superyak/.worktrees/trail-arrows/engram/`.

Claims I checked and found true: legacy level-1 cells are self-loops (server.py `_record_application`, `source_id=target_id=memory_id`). v2 2-cells take composable multi-cell routes as boundaries (`is_interpretable`, `validate_path`, `_path_endpoints`). A `create` cannot output an existing cell (category_evolution.py:378-379). The compiler walks only active cells (category_compile.py:1253-1268). Recall rows carry `session_id` in `context` (server.py:2102, 2181, 2376). Outcomes are set per recall, not per target (storage.py `update_log_outcome`). `is_eligible` is gain > cost and persistence ≥ 0.10 (category_evolution.py:243-250). 0.10 × 7 d = 16.8 h. Nothing outside the tests proposes a rewrite. `~/.engram` is absent on the Pi. The A* heuristic is consistent, including every missing-vector case: an edge costs at least θ and at least π when a vector is missing, while h ≤ π, and h = 0 whenever the node or the goal lacks a vector.

## Must-fix

**MF1. §5 Roads/Detours, §12 "Road gate": an early ineligible proposal blocks the road forever.**
A road is proposed once, "when a step's support first reaches 2", with its evidence frozen at that moment. If those two sessions are less than 16.8 h apart, the proposal is ineligible and nothing can repair it. The output id is the stable (lane, proxy(A), proxy(B)) id, and `_validate_proposal` refuses both an existing output cell (category_evolution.py:378-379) and an existing rewrite id (:341-342). `commit` re-checks only the frozen evidence (:555) and appends `rewrite_rejected`. Every later supporting session is ignored. Detours have the same problem. Equal-length detours have gain 0 and can never be eligible, yet they are still proposed.
*Fix:* Propose a road the first time its *current* evidence is eligible: support ≥ 2 and span ≥ 0.7 d. Propose a detour only when gain > 0.25 and persistence ≥ 0.10, and drop the equal-length ordering rule. Report steps that have support but are not yet eligible as a count. Give each rewrite a stable id (e.g. `_stable_id("trail-road", {"cell_id": …})`) and treat "already exists" as done. Change the §12 test to: "two sessions an hour apart propose nothing; a third session a day later proposes an eligible road".

**MF2. §4 Trail, step 1: touches cited from the same recall create false steps.**
A cited touch takes the recall row's timestamp, so all targets cited from one recall share a time and fall back to memory-id order. A used recall that returns {A, B}, each with per-target evidence, creates the step min(A,B) → max(A,B). That is UUID order, not a route. Similar queries return similar sets, so these artifacts are the steps most likely to repeat across sessions and become roads.
*Fix:* Order the touches from one recall by their position in `target_ids` (the delivered rank). Mark steps between two touches of the same recall `co_cited`. They stay footpaths for A*, but they never count toward road support or detour runs. Add a test.

**MF3. §4 Steps / §5 Roads: every write breaks a road, so roads and detours stay close to empty.**
Every wrote touch is a fresh uuid4 episode that exists only in its own session (server.py:1866). In any later session that memory can appear only as a cited touch. A step A → B therefore recurs only when A and B are cited back-to-back with no same-lane write or other touch between them. One `remember` between the two citations breaks it. After MF2, few roads will form on a real store. Few roads means fewer detours still, since detours are road-only runs. The evaluation would then measure footpaths alone, and the level-2 machinery would be theater.
*Fix:* Count support over two views of each (session, lane):
- the full trail, which gives footpaths as now;
- the *revisit trail*, which keeps only the touches of memories that existed before the session's first touch.

support(A → B) = the number of distinct sessions whose full trail or revisit trail contains A → B. Revisit steps are A* edges too. Report, in `reflect` and the CLI, how many steps reach support ≥ 2 in each view, so calibration shows whether roads exist at all. Add a test in which writes are interleaved between citations.

**MF4. §5 Detours: the definition fails at runtime and multiplies redundant cells.**
- (a) Two routes may share roads (X→A→B→Y and X→A→Y). Their witness list ("the routes' road cells") then contains duplicates, and `_validate_proposal` raises "rewrite member roles cannot contain duplicates" (category_evolution.py:352-353).
- (b) Every shortcut also spawns a cell for each contiguous extension of the pair (P,X,A…Y,Q). That spends the 32-per-pass cap on redundant 2-cells.
- (c) The member limit is 32 in total (:350-351). One output plus ≤ 16 witnesses leaves ≤ 15 evidence ids, but the spec never says what detour evidence is.
- (d) "Span over both routes' supporting sessions" is undefined.
- (e) The material for the detour cell id is not given, although §12 tests that the id is stable.

*Fix:*
- Require R1 and R2 to be internally vertex-disjoint: they share only X and Y. This also rules out shared roads.
- Witnesses are the distinct roads of both sides (≤ 16).
- `evidence_event_ids` are the current trail events of sessions that ran either route as a contiguous run, earliest first, at most 15.
- persistence = min(1, (latest − earliest first-touch time over those sessions) / 7 d).
- Cell id = stable id of (lane, source road ids, target road ids). Derive the rewrite id from it.

**MF5. §5 Activation (and Goal 2): the claim that roads are "already traversable by CategoryCompiler … with no compiler change" is false.**
- (a) A live `categories_v2.db` has no epoch unless it came from legacy replay. Rows enter `cat_epochs` only through commit, `create_root_epoch` and replay (category_evolution.py:519, :664, :2234), and `create_root_epoch` has no production caller. `_consolidate_startup` returns when there is no epoch (:1431-1433), so `auto_commit = true` commits nothing.
- (b) Committing a road activates only its outputs (:491). Proxy 0-cells, whether made by `_observe_recall` or by this pass, are created outside any rewrite (:1150-1161), so they are never active. `_neighbors` joins the active table on both sides (category_compile.py:1253-1268), so the walk memory → road → memory stops at an inactive proxy. Inactive seeds translate only through rewrite inputs (category_compile.py:1164-1190).
- (c) An existing proxy cannot be activated by any rewrite. A `create` cannot output it, and every other kind needs active inputs.
- (d) `consolidate` sorts by gain − cost (category_evolution.py:856), so detours would commit before the roads they are built on.
- (e) Goal 2's "every cell has … an epoch" is false while `auto_commit = false`.

*Fix:* Rewrite the Activation paragraph. In step 1, roads and detours are pending evidence only and are never compiled. Compiler traversal is a later spec: it covers proxy activation, an epoch for stores the observer created, and commit order. Reword Goal 2 to "lineage and evidence, and an epoch once committed".

**MF6. §3 anti-goal "Mathematical theater", §6: nothing reads the stored level-2 cells.**
The route CLI rebuilds its graph from `graph.db`, which holds no v2 cells. The evaluation also runs on a `graph.db` copy. No tool or server path calls `route` over trail events. The road and detour cells that `observe_trails` writes could be read only by the compiler, and MF5 shows the compiler never reaches them. The anti-goal is violated as written.
*Fix:* Give `trails.py` a read-only v2 mode: `--categories /path/to/copy-of-categories_v2.db`, opened `mode=ro`. In that mode `route()` takes each step's road status from road cells and its detour explanations from dimension-2 cells (through `cat_boundaries` and `validate_path`). Add a parity test: run `observe_trails` on a synthetic store, then check that the v2-mode route and the `graph.db`-mode route agree on edges, and that the explained detour ids equal the stored 2-cell ids. If you don't want this, cut detour cells from step 1.

**MF7. §7 Evaluation: as written, the gate cannot tell "routes help" from artifacts.**
- (a) *Cutoff and leakage.* Sessions are split by first touch, but a training session that runs past the first held-out session's start adds later touches and post-cutoff memories to T. *Fix:* cutoff = the first touch of the first held-out session. T uses only training touches before the cutoff, and only memories created before it.
- (b) *Empty qualifiers.* A qualifying session whose only pre-cutoff touches are s and g has precision 0 in both graphs by construction: every interior node is some other pre-cutoff memory, and the session touched none. Such sessions still count toward the 30. *Fix:* a session qualifies only with ≥ 3 distinct pre-cutoff touches in the lane.
- (c) *Unpaired comparison.* Precision is taken "over routes with an interior", so T and B are compared on different sets of sessions, and T can pass with tiny reach. The bootstrap is not stated to be paired. *Fix:* for each qualifying session, precision = 0 when a graph finds no route or a route with no interior. Gate on the per-session paired difference with a paired bootstrap, and record the seed. Require T's reach to clear a preregistered floor (e.g. 0.20).
- (d) *Node-set confound.* B spans every pre-cutoff memory, while T spans only memories touched in training, so T can win on popularity alone (the v2 spec's "popularity collapse"). *Fix:* build B over T's node set. Add an order-free ablation: each training session's touches as an undirected clique, or its trail shuffled. T must beat both. The synthetic "no route structure" store must include a popularity skew with no order, and it must not pass.
- (e) *Wall-time bound.* The 500 ms limit makes the result depend on the machine (Pi vs Mac). *Fix:* the evaluation uses only the expansion bound and reports wall-time truncations separately.

**MF8. §3 "Personal leakage", §4, §8: re-laning breaks lane purity in an immutable store.**
A memory's lane can change after it is written: compression review re-lanes source episodes (compress.py:510 → storage.py:598-609). A work trail event, road or detour recorded before a work → personal re-lane keeps a personal memory id forever, and nothing checks again.
*Fix:* Every reader filters touches by the memory's *current* lane in `graph.db` and drops roads and detours that have an endpoint outside the lane. That covers support counting, detour search, route, the evaluation, and any later publication. The pass also re-emits (supersedes) any (session, lane) trail whose touch set, filtered by current lane, has changed. Test: re-lane a touch after its road is proposed, then check that route and support exclude it.

## Should-fix

**S1. §4 Cited touches: the `operation_log` rule drops the filter it claims to copy.**
`auto_capture_outcomes` counts only `mark_core`, `instinct_feedback` and `dream_react` (hooks/sleep.py:44, :107-113). `_record_operation` stores every `id`, `*_id` and `*_ids` value from a call's arguments and result (server.py:66-83). Without the filter, `compress_commit` (via a reinforced `semantic_id`), `share(memory_id)`, `revive` and similar calls would turn system or publication acts into "use". *Fix:* restrict the rule to `CITING_OPERATIONS` and import the tuple from hooks/sleep.py.

**S2. Goal 1, §4, §5: the output is not a function of `graph.db` alone.**
Whether a session is "closed" depends on the wall clock and on which server is running. `context_id` comes from the process-local tracker, which at startup has seen none of the past sessions. *Fix:* judge closedness against an `as_of` time. For the server that is the start of the pass; for the CLI it is the newest timestamp in the store, overridable with `--as-of`. Set `context_id` to null in step 1. The determinism test fixes `as_of`.

**S3. §5 Trail-event identity and weight observations.**
An event id built from (session, lane, touch count) is ambiguous when the touches change but the count does not, for example when one memory is pruned and a late "used" outcome adds another. "Supersedes" has no rule. Weight observations get uuid4 ids (categories.py:1756), so a later pass, or a grown session's new event, adds the same session again. Their `context_id` must be NULL for the compiler to read them (category_evolution.py:1280-1285 passes None; categories.py:1796 matches with `context_id IS ?`). In step 1 nothing reads them anyway (MF5). *Fix:* id = stable id of (session_id, lane, digest of touches), and the current trail is the newest event by rowid. Cut road weight observations from step 1, since support can be derived from events. If you keep them, dedupe them per (cell, session) with `context_id` NULL.

**S4. §5 Work done while the lifecycle barrier is held.**
On every start, detecting grown sessions and recomputing support scan every session and every trail event, and no index covers the payload's `session_id`. Road proposals per pass are unbounded: 64 sessions × up to 511 steps. All of this runs inside `_maintenance_step_scope`, which holds the barrier that tool calls wait on (server.py:1097-1112). *Fix:*
- Take the barrier per batch of sessions.
- Cap road proposals per pass (e.g. 64).
- Require, rather than merely allow (§13), a rebuildable current-trail/step-support table once trail events pass a stated size.
- Process sessions oldest-first by their last row.
- Run the step before `prune`, so a backlog is read before its episodes move to cold storage.

**S5. §6 and §7 ambiguities that change what gets built.**
- (a) Say that T's edges are directed; B's are undirected.
- (b) In the route graph, "road" means support ≥ 2 whatever the span. State that, or tie it to eligibility.
- (c) A step's time, used for span, is the time of its second touch.
- (d) Define "detour cells whose longer side the route avoided": the route visits X and later Y, and its sub-route between them is the shorter side. N is the number of sessions that travelled the shorter side.
- (e) Detour hit rate: among (held-out session, training detour) pairs where the session visits X and later Y, the share whose run between them is the shorter side.
- (f) The detour payload's route gap has no basis. `different_routes` requires one shared basis (paths.py:303-307). Fit it on the two routes' touches, or cut it, since nothing reads it.
- (g) Count "exactly one target" after instincts are removed.

**S6. §8 Publication rules.**
- (a) `shared_memories` rows live in the published house and are written to `published_storage` (sharing.py:147-170), not to the source `graph.db` that the trail pass reads. A trail endpoint matches by (`source_instance`, `source_id`, `audience`), and the published copy has a different `memory_id`. Say so.
- (b) "Both endpoints shared" bounds content, not behavior. Support, span and direction are new behavioral metadata that the audience does not hold: how often, and in what order, the owner worked through those memories. With support 2 and a day-rounded span, a road can point at a specific piece of work. Sharing a memory is not consent to that.

*Fix:* Publication needs a separate owner opt-in per audience and a minimum support (e.g. ≥ 3). Reword Goal 5: "computable from shared memories alone" is false, because support and span come from private trails. Say instead that a published road "reveals no content beyond what the audience holds".

**S7. §8 and §9 forward compatibility: forks.**
`cli.py fork` copies the whole store with SQLite backup, including episodes with their session ids and `memory_log` (cli.py:39-49). A fork and its parent therefore derive identical roads, with identical support, from the same sessions. The "rail by agreement of independently governed lighthouses" step would count that as agreement. The published form deliberately drops session ids, so the later step cannot detect the shared origin. *Fix:* the published form carries `instance_id` and `forked_from_instance_id`, and published support counts only sessions whose first touch is after the store's fork time. State this now.

**S8. §12 Tests to add.**
- Co-citation ordering (MF2).
- Roads still form with writes interleaved (MF3).
- Overlapping routes yield one minimal detour and no duplicate-member error (MF4).
- Re-laned touches are excluded (MF8).
- Proposals happen only when eligible (MF1).
- The evaluation does not pass on a synthetic store with popularity but no order (MF7).
- In the gate-off test, `auto_commit = false`, and the store has already been opened once with the same flags, so first-open vector provisioning doesn't confound the byte comparison.

## Nits

- **N1 §10.** "10,000 expansions … matches the compiler" is wrong. The compiler's limits are depth 4, 64 neighbors, 50,000 candidates and 500 ms (category_evolution.py:887-891); 10,000 is the v2 design's state-node bound. Likewise "32 detours matches the rewrite budget": that budget counts commits per consolidation, not proposals.
- **N2 §2.** "This is the v2 … kernel K(m|m')" overstates it. K is a normalized, context-conditioned kernel learned with soft responsibility; trails are unnormalized counts keyed by lane. Say "an unnormalized, lane-keyed precursor of".
- **N3 §5.** For roads the gain test can never fail (1 − 1/s ≥ 0.5 > 0.25 for s ≥ 2); only persistence gates them. Say so, so calibration doesn't tune a constant that does nothing.
- **N4 §4.** Genome-synced episodes already have `session_id` NULL (federation.py:197-199), so "skip inherited" never fires. The real inherited-history case is forks (S7).
- **N5 §5 and §12.** Compare persistence in integer seconds (span ≥ 60,480 s) to avoid the float boundary at 16.8 h. Clip the cosine to [−1, 1] and give the A* consistency test an epsilon.
- **N6 §5.** Specify `locus_id` (proxy(A) for roads, proxy(X) for detours) and `context_id` (null) for the proposals.
- **N7 §5.** Create proxies only for road endpoints, not for every touch.
- **N8 §5.** The observer opens its connection with `timeout=0` (category_evolution.py:960), so two servers starting together will race. Do check-then-insert inside one immediate transaction, as `_observe_recall` does, and count a lock failure as a skipped pass, not an error.
- **N9 §9.** Once route output is shown to agents, followed suggestions will flow back into trails. The later spec needs a rule that excludes touches caused by a route suggestion (the v2 self-confirmation rule).


## Re-check (revision 2, ee90bff)

RE-CHECK: APPROVE WITH CHANGES

Revision 2 at `ee90bff` (branch `trail-arrows-spec`), checked against my first verdict. Every earlier MF, S and N item is resolved except where the table notes otherwise. Three new must-fixes (RMF1–RMF3) remain, each a sentence or two. Once they are applied the spec is approved and needs no further review. File:line references are relative to `/home/andy/superyak/.worktrees/trail-arrows/engram/`.

## Rulings on the two choices

**(1) Interior F1, 0 when there is no route or no interior, with a paired bootstrap and reach ≥ 0.20: accepted.**
- F1 is stricter than precision alone. Precision rewards a short route that happens to hit one interior node; coverage alone rewards long routes. F1 penalizes both.
- Every qualifying session now has a non-empty interior (≥ 3 pre-cutoff touches), so scoring a direct s→g route as 0 is correct, not a penalty on a good answer.
- Scoring no-route as 0 makes T pay for low reach inside the paired difference, and the separate reach floor guards the same thing again. No change needed.

**(2) Shuffled trails (graph S) instead of cliques, with T required to beat both B and S: accepted on one condition (RMF2).**
- My first verdict offered either option, and shuffling keeps each session's touch set and the nodes' popularity, which is what the ablation needs.
- The condition: shuffling single touches also destroys the co-cited edges, whose order comes from search ranking, not from the agent. T keeps those edges. T − S would then credit T for co-retrieval structure, and the gate's claim "order helps" would not follow. Cliques did not have this problem, because a clique keeps every co-cited pair.

## Status of first-verdict items

| Item | Status |
|---|---|
| MF1 eligible-only proposals | Resolved (§5 Roads and Detours, §12 Eligibility). |
| MF2 co-citation | Resolved (§4 Trail step 2, Steps, `co_cited`). For the evaluation, see RMF2. |
| MF3 revisit view | Resolved (§4 revisit trail, support over both views, diagnostics, §12 test). |
| MF4 detours | Resolved (vertex-disjoint routes, ≤ 16 distinct witnesses, ≤ 15 evidence ids, persistence and ids defined). See S-b on evidence. |
| MF5 activation | Mostly resolved. The new text says proxies are "never active, and no rewrite can activate them", which is false on a replayed store. See RMF3. |
| MF6 reader | Resolved (`--categories` mode, parity test, anti-goal reworded). |
| MF7 gate | Resolved (cutoff, ≥ 3 pre-cutoff touches, zeros, paired bootstrap, reach floor, B over T's nodes, S, expansions only, leakage test). The condition on S is RMF2. |
| MF8 current lane | Resolved for readers. Re-emitting a changed trail depends on how the pass selects sessions (S-a). |
| S1 `CITING_OPERATIONS` | Resolved. |
| S2 `as_of`, null `context_id` | Resolved. See N-a. |
| S3 ids and weights | Weights resolved (cut from step 1). The digest-based event id breaks on a repeated digest (RMF1). |
| S4 cost | Resolved (batches of 8 sessions per barrier hold, caps, index required at 10,000 events, before `prune`). The selection rule is ambiguous (S-a). |
| S5 ambiguities | Resolved: (a)–(g). |
| S6 publication | Resolved. |
| S7 forks | Resolved. `stamp_fork` indeed writes no time (store_identity.py:143-160). `instances.json` already keeps `forked_at` (federation.py:133); the publication spec can take the fork time from there. |
| S8 tests | Resolved. |
| N1–N9 | Resolved. |

## New must-fix

**RMF1 (§5 Trail events): a repeated digest breaks the event id.**
- The event id is the stable id of (session_id, lane, digest), and the pass appends whenever the digest differs from the newest event's.
- A trail can return to an earlier digest. An episode can be pruned to cold storage and later restored by `revive` with the same id and `created_at` (storage.py:905-920). A memory can be re-laned and later re-laned back (compress.py:510).
- In both cases the pass appends an id that already exists, and `cat_events.id` is the primary key. One of two things follows:
  - an `IntegrityError` that repeats on every pass, and processing oldest-first means it can stall every session queued after it;
  - or, if the builder skips existing ids, the "newest by rowid" event is wrong forever.
- *Fix:* include the superseded event in the id: stable id of (session_id, lane, digest, id of the newest prior event or null). Add a test: prune then revive a touched episode, and check that a third current event is written.

**RMF2 (§7 step 3, graph S): the shuffle must keep co-cited groups.**
- *Fix:* permute each training trail in blocks. All touches cited from one recall form one block and keep their delivered order inside it. Wrote touches and single-target cited touches are blocks of one.
- An equivalent alternative: leave co-cited steps out of T and S in the evaluation only.
- Add to the §12 popularity test: a store whose only structure is co-retrieval does not pass T − S.

**RMF3 (§5 Activation): "can't activate them" is false on a replayed store.**
- Legacy replay puts every legacy proxy into the root epoch's membership (`_plan_cells` drafts at category_evolution.py:1680-1684, memberships written at :2221-2246). A trail road between two memories that already have legacy proxies reuses those proxies, because `get_cell` finds them.
- With `auto_commit = true` on such a store, `_consolidate_startup` commits the trail proposals. They are eligible by construction now, at 32 per start. The compiler then walks memory → road → memory: the walk runs on every recall whenever `enabled` is on (server.py:553-555), and it changes delivery when `shadow = false` and `influence_recall = true`.
- *Fix:* make the pass fail closed. `observe_trails` runs only when `auto_commit` is exactly `false`; otherwise it writes nothing and counts a skipped pass. Correct the sentence to say this. Add the case to the §12 gate-off test.

## New should-fix

**S-a (§5 "When it runs"): say which sessions count toward the 64.**
Read literally, "processes at most 64 closed sessions, oldest first by their newest row" picks the same oldest 64 sessions every pass, so newer sessions never get trails and re-laned sessions are never re-emitted. Intended reading: every pass recomputes the digest of every closed (session, lane) pair, read-only and in barrier batches. It then writes events for at most 64 sessions that have no event or a changed digest, oldest first. State that, and say that the global phase (support recount, road and detour proposals) runs in its own bounded barrier steps. Alternatively, it can read `graph.db` through a separate read-only connection (`Storage.open_read_only`), so that phase needs no barrier.

**S-b (§5 evidence caps): the evidence list can omit the session that sets the span.**
Roads list "earliest first, at most 31" and detours "at most 15", but persistence is measured from the earliest to the latest session. When the cap binds, the latest session is missing from the evidence, so persistence cannot be replayed from the evidence (the v2 replay rule). *Fix:* always include the earliest and the latest sessions, then fill earliest-first.

**S-c (§7 graph S): one seed is one random graph.**
Every held-out session routes over the same shuffled graph. The per-session bootstrap therefore doesn't capture graph-level variance, and a lucky seed can pass or fail the T − S comparison by chance. *Fix:* build K = 10 shuffled graphs from seeds derived from the recorded seed, and take each session's S score as the mean over them.

**S-d (§4 Cited touches): "exactly one remaining target" can credit the wrong memory.**
If recall [A, B] was marked used and B was later pruned, A becomes a touch even though the "used" judgment may have been about B. *Fix:* count "exactly one" after removing instincts only. A target that no longer exists still counts toward the number of targets.

## Nits

- **N-a (§4):** say that rows newer than `as_of` are ignored. Otherwise `--as-of` set in the past builds trails that include later touches. Also name the tables whose rows set a session's newest row: episodes and recall rows.
- **N-b (§6 `--categories`):** say which road cells count. Suggested: any road cell that is not rejected.
- **N-c (§12 Parity):** parity holds only when no per-pass cap was hit and no trail changed after the pass. State this in the test.
- **N-d (§7 B):** a node with no vector has no nearest neighbors in B, so B scores 0 whenever s or g lacks one. Report how many qualifying sessions had a missing vector, or exclude them.


Revision 3 applies RMF1-RMF3, S-a-S-d and N-a-N-d; per the re-check, that completes approval.
