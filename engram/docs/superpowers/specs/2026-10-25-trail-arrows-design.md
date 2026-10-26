# Trails: Footpaths, Roads and Detours in the Category Graph

**Date:** 2026-10-25
**Status:** Revision 7, the consolidation pass across the three city-rail specs
(`docs/superpowers/reviews/2026-10-25-city-rail-consolidation.md`, which logs each change). Revision 6 was approved on
its final check (`docs/superpowers/reviews/2026-10-25-trail-arrows-rev4-spec-review.md`, "Final check of
2026-10-25"). The imprint spec's revision 4 provides I2, I3 and I6, and revision 7 marks them provided in section
11, after checking each against what that spec provides. The check found one gap, in I6's test: its one `as_of` must
be at or after the plan's end t₁, which the imprint spec's revision 5 now says. Section 7 now says that admission's
calibration on an imprint reads no session path (the imprint spec's `no_paths`), and cites the permissions spec's 7.6
for "this narrows mistakes, not malice". No rule of this spec changes, and nothing more leaves a machine.
Revision 3 was approved: the first verdict (MF1–MF8, S1–S8, N1–N9) and the re-check (RMF1–RMF3, S-a–S-d, N-a–N-d)
are both applied. Revision 4 kept every approved decision except the ones it lists under "Changes to approved
decisions". Its fresh review (`docs/superpowers/reviews/2026-10-25-trail-arrows-rev4-spec-review.md`) approved it
with changes. Revision 5 applies MF1–MF3, S1–S11 and N1–N16; that file's "Response" section lists each. An
interface pass across the three city-rail specs then changed R13, R17, sections 4, 6.5, 7, 8, 9, 10, 11, 12 and 14
(`docs/superpowers/reviews/2026-10-25-city-rail-interfaces.md`). Above all it declines I4, the cut flag, for privacy,
and records the cost in section 7. A second fresh reviewer re-checked revision 5 in the same review file and approved
it with changes (RMF1–RMF2, RS1–RS4, RN1–RN11). Revision 6 applies them; that file's "Re-check response" lists each.
Some of them needed the imprint spec to change too (section 11). I5 is in that spec's revision 3, written in
parallel, and I2's and I3's new parts and I6 are in its revision 4.
Observational; every part is off by default.
**Contract:** [the city rail vision](../../../../docs/city-rail-vision.md), "The traveler's view" and "Permissions by
place". Rio Grande wrote the vision from Andy's words. Where it goes past a quote, it is Rio Grande's call carried by
the contract, and this spec says so.
**Module:** new `trails.py`; a gated pass in `category_evolution.py`; three gated read-only MCP tools in `server.py`.
**Builds on:** `2026-08-07-evolving-category-memory-design.md` (v2 store, rewrites, epochs),
`2026-09-29-path-signatures-design.md` (`paths.py`), `2026-09-29-lighthouse-sheaf-design.md`,
`2026-09-01-lighthouse-local-city-design.md` (sharing, permissions, receipts),
[permissions by place](../../../../docs/superpowers/specs/2026-10-25-permissions-by-place-design.md) (revision 5;
its sections 4.1, 5.2, 6.3–6.5, 7.6, 9.1, 11 and 14) and [imprints](2026-10-25-store-imprint-design.md) (revision 5;
its sections 5.3, 6.2, 10, 11 and 12). The last two were written in parallel. This spec cites them by path and
section, and section 11 lists what it needs from each.

## Revision history

| Revision | Commit | What changed |
|---|---|---|
| 1 | uncommitted draft | Footpaths, roads, detours, a read-only A*, the evaluation. Verdict: approve with changes (MF1–MF8, S1–S8, N1–N9). |
| 2 | `ee90bff` | Applied the first verdict. Re-check: approve with changes (RMF1–RMF3, S-a–S-d, N-a–N-d). |
| 3 | `3539102` | Applied the re-check. Approved. |
| 4 | uncommitted draft | The vision's traveler's view: locate from context (6.2), route to a goal in words (6.3), forward lookup (6.4), short answers (6.5), three read-only tools (6.6), suggested touches (4), a goal-in-words measure (7, steps 8 and 9), the evaluation on an imprint (7), per-audience permissions in place of the work-lane rule (8), and a Raspberry Pi budget for every pass (10). Verdict: approve with changes (MF1–MF3, S1–S11, N1–N16). |
| 5 | uncommitted draft | Applied that verdict. Measure W embeds text the way the tools do (MF1). Imprinted recall rows keep their shipped targets (I4, MF2; declined in the interface pass, below). `at_goal` means A* popped an entry (MF3; corrected in revision 6). Every route node is rechecked, and a route has at most 64 stops (S1). A gate pass licenses one lane (S2). The answer bound is 6,000 bytes (S5). The allow-file check, the Pi budget, the evaluation's limits and the anchor patterns are tightened (S4, S9–S11). |
| 5, interface pass | uncommitted draft | I4 declined for privacy, and its cost recorded (R17, section 7). The imprint check reads the imprint spec's state directory, tombstone and `valid_until` (I2). One `route` use per road (section 8). Lineage reads `independent` (section 8). The evaluation unit and `--lane` follow the imprint spec. `laid_by` on an imprint names the source's owner (6.5). |
| 6 | `53c132a` | Applied the re-check. `at_goal` means the popped goal has no predecessor (RMF1). Without `route`, an imprint ships no session ids, so it holds no trail of any kind (R18, I5; RMF2). The evaluation stays offline, and its unit gets the shared embedder's socket from the station's `runtime.json` (R19, I3; RS2). One use id gives one run, and a finished use retires its allow file (R13, I2; RS3). A changed allow file ends the run as `allow changed`, and only a tombstone is recorded as a withdrawal (I2; RS4). The imprint spec's recall-row test is asked to change (I6; RS1). Nits RN1–RN11. Approved on its final check. |
| 7 | this file | The consolidation pass. I2, I3 and I6 are provided by the imprint spec's revision 4, each checked against it (section 11); I6's one `as_of` must be at or after t₁, now in the imprint spec's revision 5. Admission's calibration on an imprint reads no session path, so section 7's "Calibration reads exactly that" now says it of a plain copy only (the imprint spec's `no_paths`). The known limit cites the permissions spec's 7.6. Step 10 names the use's `TimeoutStopSec=60`. No rule changes. |

## Decisions in revisions 4 and 5

"Andy" means his own words, quoted exactly as the vision gives them. Every other line is Rio Grande's call.

| # | Decision | Source |
|---|---|---|
| A1 | Agents travel this system, so the design starts from the agent's side. | Andy: "Take a step back. this is a system you will be traveling." |
| A2 | Where the agent is comes from its context. | Andy: "The context gives the graph positions which surfaces sheaves as paths." |
| A3 | Routes are plain A*. | Andy: "The lighthouses are shared sheaf graph systems that with the cohomologies form a railway layer that act as high speed rail you can just simple a* pathfinding algorithms for." |
| A4 | Permissions are per audience and place, not per lane. | Andy: "I may share my medical history with the public health office but not the parks and rec." |
| A5 | Stores from other computers come here as imprints, with permission. (That the evaluation of someone else's store runs only on an imprint is R13, Rio Grande's call built on these words.) | Andy: "We should make it easy to port engram stores with permission from other computers. to imprint it here." |
| A6 | Free, open source, mathematics as the connector, a Raspberry Pi. | Andy: "I'm seeing this as free, open source, uses universal mathmatical principles as connector standards and runs on a raspberry pi." |
| V1 | A* runs to the goal set {n : θ(n, q) ≤ r} with h(n) = max(0, θ(n, q) − r). | The vision's traveler's view (Rio Grande's call carried by the contract) |
| V2 | Forward lookup, and short routes whose items carry who laid them, the rule and the receipt. (The vision calls the items "steps"; this spec calls them stops, 6.5.) | The vision's traveler's view (Rio Grande's call carried by the contract) |
| R1 | Entry stations come from ids the agent holds, then anchor words, then nearest by angle; at most 6. | Rio Grande's call |
| R2 | Entering at a station costs 2·θ(c, e), the cost of an untrodden footpath; 0 for an id the agent holds. | Rio Grande's call |
| R3 | The goal radius is r = min(θ_min + 0.10, arccos 0.60), set for query-to-document angles: the context and goal are embedded with `search_query`, and the nodes' stored vectors were embedded with `search_document`. Nodes without vectors are never goals. | Rio Grande's call |
| R4 | Angles use Kahan's form, 2·atan2(‖â − b̂‖, ‖â + b̂‖). | Rio Grande's call |
| R5 | Forward lookup reads full trails and ranks by sessions, then recency, then id. | Rio Grande's call |
| R6 | Every answer is at most 6,000 bytes of compact JSON, which `estimate_tokens` counts as 1,500 tokens, and every stop names a source holding who laid it, the rule and the receipt. | Rio Grande's call |
| R7 | Three tools, `trail_locate`, `trail_route` and `trail_next`, registered only when `[trails] tools` is exactly `true`. | Rio Grande's call |
| R8 | An answer's only write is one `route_shown` receipt row in `memory_log`. | Rio Grande's call |
| R9 | A touch a tool suggested is marked, and a step with a suggested end adds no support and no detour run. A given id that an answer names counts too, which only removes support. | Rio Grande's call |
| R10 | The tools read a graph built once per server process, from a read-only connection, within fixed bounds. | Rio Grande's call |
| R11 | Before answering, a tool rechecks the current lane and existence of every node of the computed route, every entry and every other memory it would name. A route has at most 64 stops. | Rio Grande's call |
| R12 | Measure W embeds the text of the session's first known memory and of its last written episode with `search_query`, through the tools' own functions, and routes to that goal set, against nearest to the goal (N) and similarity routing (B). The tools need both gates. | Rio Grande's call |
| R13 | A store that isn't the runner's own is evaluated only through an imprint's `trail-evaluation` use, and `trails.py` refuses an imprint without a valid allow file in that imprint's state directory (imprint spec section 12). One use id gives one run: `trails.py` refuses a use id whose use directory already holds a report or result, and the use retires its allow file when it finishes. An owner running it on a copy of their own store is their own use. | Rio Grande's call |
| R14 | In step 1 the tools cite "own store" as the rule that allowed them. | Rio Grande's call, from the permissions spec's non-goal (its section 14) |
| R15 | `rule_version` stays `trail-v1`. | Rio Grande's call: nothing is built, so no event of an older form exists |
| R16 | The tools answer only the lanes in `[trails] lanes` (default `["work"]`), and a gate pass licenses only the lane it evaluated. | Rio Grande's call |
| R17 | On an imprint, a recall row ships whole or not at all, with no `cut` flag: a flag would tell that something the recall matched stayed home (imprint spec D7, D21). Privacy wins over trail quality, and section 7 records what it costs. This replaces revision 5's I4 request. | Rio Grande's call, from the interface pass |
| R18 | Trail material leaves a machine in an imprint only when the owner chose `route`, and that includes the order in which each session wrote its episodes. Without `route`, the imprint ships `episodes.session_id` as null (I5), so it holds no trail of any kind. | Rio Grande's call, by the interface pass's rule that privacy wins |
| R19 | The evaluation never downloads a model. The in-process model loads only from the local cache (`local_files_only=True`). The shared service is reached only through `ENGRAM_EMBEDDER_SOCKET`, which the use's unit gets from the station's `runtime.json` (section 7, step 8.2; I3). | Rio Grande's call |

**Changes to approved decisions.** C1 and C5 are required by the vision. C2, C3 and C4 are Rio Grande's calls, made
to serve it; the vision doesn't require them word for word.

| # | Revision 3 said | Revisions 4 and 5 say | Why |
|---|---|---|---|
| C1 | "Only the work lane can ever leave." (section 8) | Roads, detours and trails leave a store only by a `route` permission for an audience (section 8). | Required by the vision's "Change to the trail spec" |
| C2 | Excluding touches caused by route suggestions is a later spec (section 9, step 4). | It applies now (section 4), because the tools show routes to agents now. | Rio Grande's call, from the self-confirmation anti-goal (section 3), once the traveler's view shows routes to agents |
| C3 | Every pass recomputes the digest of every closed (session, lane) pair (S-a). | A pass scans at most the 16,384 pairs with the newest rows (section 5). | Rio Grande's call: the number 16,384 is a calibration hypothesis, chosen to serve vision principle 4, "bounded passes" |
| C4 | A session's newest row is the latest of its episodes and recall rows. | Its `route_shown` rows count too (section 4). An agent reading routes for an hour is still at work. | Rio Grande's call, once the tools exist |
| C5 | "The evaluation runs read-only on a copy of a real store, and on synthetic stores in the tests." (`3539102`, its section 7) | Someone else's store is evaluated only through an imprint's `trail-evaluation` use, and the first evaluation runs on an imprint (section 7). An owner may still run it on a copy of their own store. | Required by the vision's "How the work runs", step 3: "Then the trail evaluation on an imprinted store whose owner agrees." |

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

**The traveler.** Andy: "Take a step back. this is a system you will be traveling." The agent that rides these
trails starts every session with no memory, rarely knows its destination, pays for every result in context window,
makes mistakes, and lays track for the next agent (vision, the traveler's view). Revision 3 recorded routes but gave
the agent no way to use them. Revision 4 adds that way: find where the agent is from its context, route it to a goal
it can state only in words, tell it what other sessions did next, and keep every answer short and accountable.

This spec is step 1 of the superhighway. It records routes inside one store, firms them up as
evidence, measures whether they help, and offers them to the store's own agent once they do. Compiling roads into
recall, and rail across lighthouses, are later specs (section 9). The rest of this spec is written so those steps
need no rework.

## 2. Vocabulary

| Term | Meaning | Where it lives |
|---|---|---|
| **Touch** | A memory a session wrote, or a recalled memory it demonstrably used | derived from `graph.db` |
| **Trail** | One session's touches in one lane, in order | the newest `trail_observed` event for that (session, lane) |
| **Revisit trail** | The same trail keeping only memories that existed before the session's first touch | derived from the trail |
| **Step** | A directed pair `A → B` of consecutive touches in a trail or revisit trail | derived |
| **Stop** | One memory on a route an answer shows. A route of k stops has k − 1 steps (6.5) | derived per call |
| **Footpath** | Any step. A* may use it | derived; never a cell |
| **Road** | A step with support ≥ 2 whose evidence is eligible (section 5) | a level-1 cell, proposed by a `create` rewrite |
| **Detour** | Two travelled road routes between the same two memories that share nothing else, where one saves more than a quarter of the hops | a level-2 cell, proposed by a `create` rewrite |
| **Rail** | A road that independent lighthouses agree on | later spec (section 9) |
| **Suggested touch** | A cited touch of a memory that a tool answer named earlier in the same session (section 4) | derived from `memory_log` |
| **Entry station** | A memory on the trails where a search starts, found from the agent's context (6.2) | derived per call |
| **Goal set** | The memories on the trails within angle `r` of the goal words' vector (6.3) | derived per call |
| **Forward lookup** | What sessions that passed an entry station touched next, and where their trails ended (6.4) | derived per call |
| **Tool graph** | The trails, steps and vectors the tools read, built once per server process (6.6) | server memory |
| **Receipt** | The `route_shown` row a tool answer writes (6.6) | `memory_log` |

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
   requires its own `route` permission.
6. Locate an agent from its context: turn the task, file paths, error text or memory ids in front of it into entry
   stations (6.2).
7. Route an agent to a goal given in words, with an A* heuristic proved never to overestimate (6.3).
8. Answer "what did others do next from here", and where their trails ended (6.4).
9. Answer in at most 6,000 bytes of compact JSON (`estimate_tokens` counts that as 1,500 tokens), with every stop
   carrying who laid it, the rule that allowed it and the receipt for this use (6.5).
10. Offer 6.2–6.4 as read-only MCP tools, off by default, and turned on for a store only by its owner after both
    gates pass on it, for the lane that passed (6.6, section 7).
11. Keep every pass within a Raspberry Pi's means: SQLite, Python with numpy, no GPU, bounded work (section 10).

**Non-goals**

- Changing recall output. `influence_recall` stays false, and this spec adds no ranking influence.
- Compiling roads or detours. Making proxies active, giving an observer-created store an epoch,
  and commit order are all a later spec.
- Sharing anything between stores. No new lighthouse protocol frames in this step.
- Context-specific kernels. `context_id` is null throughout step 1.
- Interpreting cells above dimension 2.
- Routing over other stores or imprints from the tools. In step 1 the tools read the server's own store.
- Detours in tool answers. The tools report roads and footpaths. Detours stay in the CLI and the stored cells.
- Reading a memory in full through the tools. An answer carries one-line summaries, and the agent recalls a stop to
  read it.

**Anti-goals** (failure even if the code works)

- **Self-confirmation.** A memory that was only surfaced never becomes a touch. A touch made after a tool named
  that memory never adds support (section 4).
- **Content copies.** Cells and events hold memory ids, never memory content. Content stays in
  `graph.db`, the one authoritative store (v2 invariant).
- **Mathematical theater.** Every stored level-2 cell is read by tested code: the `--categories`
  route explanation and its parity test (sections 6 and 12).
- **Personal leakage.** A memory whose current lane is personal never appears in a work trail's
  support, road, detour, route, tool answer or evaluation (section 4, Current lane; 6.6). That includes the stops a
  long route hides in `{"skipped": k}`.
- **Context flood.** A tool answer over 6,000 bytes of compact JSON (6.5).
- **Widening.** A tool answer names a memory outside the lane asked for, or one that no longer exists (6.6). In later
  steps, an answer names anything a permission refuses (section 8).

## 4. Touches and trails

All of this is read from `graph.db` without writing to it.

**As-of time.** Every derivation takes an `as_of` timestamp:

- the server uses the start of the pass;
- the CLI uses the newest timestamp in the store, or `--as-of`.

No derivation reads the wall clock, so results depend only on `graph.db` and `as_of`. Rows newer
than `as_of` are ignored.

**Sessions.** A session is any distinct non-null `episodes.session_id`, or any
`json_extract(memory_log.context, '$.session_id')` on an `event_type = 'recall'` row. Its
*newest row* is the latest of those episodes and recall rows, and of the session's `route_shown` rows (6.6; change
C4). A `route_shown` row never makes a session by itself. A session is *closed* when its
newest row is older than `as_of` minus one hour and it isn't the running server's own session.
Only closed sessions get trails.

**Wrote touches.** Every episode carrying that `session_id`. The time is `created_at`.
Genome-synced episodes already have a null `session_id`, so they never appear. Forks are the real
case of inherited history (section 8).

**Cited touches.** Take each recall row in the session whose `outcome` starts with `used`, and
drop instinct targets first. A target is a cited touch when either:

- a later same-session episode's `content` or `context` contains its id; or
- a later same-session `operation_log` row has an `operation` in `CITING_OPERATIONS` (imported
  from `hooks/sleep.py`: `mark_core`, `instinct_feedback`, `dream_react`) and lists the target in
  `target_ids`; or
- the recall has exactly one target once instincts are removed. A target that no longer exists
  still counts toward that number, so if B is pruned from a used recall [A, B], A is not credited
  by this rule. An imprint ships a recall row only when every target that isn't an instinct ships, and it removes
  only instinct ids (imprint spec D7 and 6.2). This rule removes instincts first too, so on a row an imprint keeps it
  counts exactly what it counts on the source.

This is the per-target form of `hooks/sleep.py auto_capture_outcomes`, with the same operation
filter. Without the filter, `compress_commit`, `share` and `revive` would count as use.

Some cases add no touch and are counted instead:

- A used recall with several targets and no per-target evidence is counted as
  `ambiguous_used_recalls`.
- A target that no longer exists is counted as skipped.

A cited touch's time is the recall row's `timestamp`. Its rank is its position in `target_ids`,
the delivered order.

**Suggested touches.** A tool answer names memories, and its receipt row lists them (6.6). A cited touch of memory
m in session S at time t is **suggested** when a `route_shown` row of S with a timestamp at or before t lists m in
its `target_ids`. A wrote touch is never suggested: no answer can name an episode before it exists. This is the v2
self-confirmation rule applied to routes. The agent went there because the system pointed there, so going there is
no evidence that the route is good (change C2).

An answer names the given ids it uses as entry stations (6.2), so they are in its receipt too. If the agent recalls
one of them again later in the session, that touch counts as suggested, even though the agent brought the id. This is
conservative: it can only remove support, never add it. Rio Grande's call (R9).

**Current lane.** A touch's lane is the memory's lane in `graph.db` *now*, not when it was written.
Compression review can re-lane episodes (`compress.py` into `storage.py`), so a memory can move
between lanes. Every reader filters by the current lane: support counting, detour search, route,
the tools, the evaluation, and any later publication. That includes the `--categories` reader, which drops a
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
A step between two touches cited from the same recall is marked **`co_cited`**. A step whose first or second touch
is suggested is marked **`suggested`**. Either kind is a footpath for A*, but it never counts toward support or
detour runs: a co-cited step's order comes from the ranking, and a suggested step's from a tool, not from the agent.

- A step's **time** is the time of its second touch.
- **Support** of `A → B` (lane L) is the number of distinct closed sessions whose current trail or
  revisit trail in L contains an `A → B` that is neither co-cited nor suggested.
- **Span** is the latest supporting session's step time minus the earliest one's, in whole
  seconds.

## 5. Writing to the v2 store (gated)

A new gate, `[category_evolution] trails = false` (the default), controls this. It does nothing
unless `enabled = true`, and only an exact boolean `true` turns it on, matching the observer's
fail-closed parsing.

**When it runs.** In the startup maintenance thread, before `prune`, so a backlog is read before
its episodes move to cold storage. It never runs on the request path.

It runs only when `auto_commit` is exactly `false`. With any other value it writes nothing and
counts a skipped pass. Otherwise, on a replayed store, startup consolidation would commit trail
proposals and the compiler would start walking them (section 5, Activation).

The pass reads `graph.db` through its own `Storage.open_read_only` connection. It takes the
lifecycle barrier only per batch, as a yield point for tool calls: per 8 sessions while it writes
trail events, and per 16 proposals while it proposes. Each pass:

1. recomputes the trail digest of every closed (session, lane) pair, up to the 16,384 pairs with the newest rows
   (change C3). Older pairs keep their current events and are counted as `pairs_not_scanned`. Readers still filter
   by current lane (section 4), so an unscanned old event can never put a re-laned memory into a work answer. It can
   only leave that event's support out of date;
2. writes events for at most 64 sessions that have no event or a changed digest, oldest first by
   newest row;
3. recounts support from current trail events and proposes at most 64 roads and 32 detours.

New sessions and re-laned ones therefore get events within a few starts, and a backlog drains
over several.

**Trail events.** For each (session, lane) picked above, append one `trail_observed` event. The
digest is SHA-256 over the canonical JSON of its touches.

- **Event id:** the stable id of `(session_id, lane, digest, superseded event id or null)`. A trail
  can return to an earlier digest, for example when an episode is pruned and later revived with the
  same id, or re-laned and re-laned back. Including the superseded event keeps every id new. The
  current trail of a pair is its newest event by rowid.
- **Payload:** `session_id`, `lane`, `context_id: null`, `truncated`, `ambiguous_used_recalls`,
  `rule_version: "trail-v1"`, and `touches` as a list of
  `{memory_id, layer, kind: "wrote" | "cited", at, recall_id | null, rank, suggested}`. `suggested` is a boolean
  (section 4). The rule version stays `trail-v1`: nothing has been built, so no event of an older form exists (R15).

A re-laned memory, a late outcome or a new `route_shown` row before a touch changes the digest, so the pass emits a
new current event. Support counts sessions, not events, so nothing is counted twice.

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
  - `evidence_event_ids`: the supporting current trail events, at most 31. Always include the
    earliest and latest supporting sessions' events, so the span can be replayed from the evidence,
    then fill earliest first;
  - `cohesion_gain = 1 − 1/support` and `complexity_cost = 0.25`;
  - `persistence_score = min(1, span / 604,800 s)`.

Proxy 0-cells are created only for road endpoints, the same way `_observe_recall` creates them.

No weight observations are written in step 1, since support derives from events. A later spec that
needs weights must dedupe them per (cell, session), with `context_id` null.

**Detours.** Take two memories `X ≠ Y` and two routes `R1` and `R2` from X to Y. All of these must
hold:

- each route is made of road cells only and has at most 8 steps;
- the routes are internally vertex-disjoint: they share only X and Y, and so share no road;
- each route appears as a contiguous run of steps that are neither co-cited nor suggested, in at least one session's
  current trail or revisit trail, so it was actually travelled and not just composed or suggested;
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
    contiguous run, at most 15. Always include the earliest and latest, then fill earliest first;
  - `cohesion_gain = (len(R1) − len(R2)) / len(R1)` and `complexity_cost = 0.25`;
  - `persistence_score = min(1, (latest − earliest) / 604,800 s)`, over those sessions' first-touch
    times in whole seconds.

That keeps the rewrite at 1 output, 16 witnesses and 15 evidence ids: 32 members, the limit.

**Activation.** In step 1, roads and detours are **pending evidence only**. They are never compiled
and never change recall. That is enforced, not just expected:

- The pass refuses to run unless `auto_commit` is exactly `false`, so no startup consolidation can
  commit its proposals.
- A store the observer created has no epoch, and `_consolidate_startup` returns when there is none.
  Its proxy 0-cells are created outside any rewrite, so they are never active.
- A store built by legacy replay is different. Replay puts every legacy proxy into the root epoch,
  and trail roads reuse those proxies. With `auto_commit = true`, consolidation there would commit
  trail roads, and the compiler would walk memory → road → memory on every recall. That is why the
  pass needs `auto_commit = false`.
- `consolidate` orders by gain minus cost, so a detour could commit before its roads.

Compiler traversal of roads needs its own later spec: proxy activation, an epoch for
observer-created stores, road-before-detour commit order, and how the pass and `auto_commit`
coexist.

**Diagnostics.** `reflect(focus="category_evolution")` gains a `trails` block holding only counts:

- sessions read and trail events written;
- steps reaching support ≥ 2 in the full-trail view and in the revisit view, co-cited steps and suggested steps;
- `steps_supported_not_eligible`;
- roads and detours proposed, and whether any committed;
- truncations, ambiguous used recalls, skipped targets, lane filtering, `pairs_not_scanned`, and passes skipped on
  lock.

## 6. Route, locate and forward lookup (read-only)

6.1 is revision 3's route between two memories. 6.2 to 6.6 are revision 4's traveler's view.

### 6.1 Between two memories

`route(start_id, goal_id, lane="work")` runs over a directed graph for one lane. Its nodes are
memories whose current lane is that lane. Its edges come from one of two sources:

- **`graph.db` mode** (the default): every step derived as in section 4, co-cited and suggested ones included.
- **`--categories` mode:** footpaths come from `graph.db` as above. Road status comes from the
  stored road cells, and detours from the stored level-2 cells, read with `mode=ro` from a
  `categories_v2.db` copy through `cat_boundaries` and `validate_path`. A cell counts unless its
  rewrite's latest disposition is `rejected`. Cells failing the current-lane check are dropped.

The search:

- **Edge `u → v`:** `support(e)` is that step's support, counting at least 1. In `graph.db` mode an
  edge is a road when its step is eligible under section 5. In `--categories` mode it is a road
  when a road cell exists. Only road status is reported; the cost uses support alone.
- **Angle:** `θ(a, b) = 2·atan2(‖â − b̂‖, ‖â + b̂‖)`, where `â = a / ‖a‖`, for two stored vectors. It is the angle
  between them, in `[0, π]`, and in exact arithmetic it equals revision 3's `arccos` of the clipped cosine. Unlike
  `arccos`, it keeps full precision near 0 and π, where near-duplicate memories sit and where `arccos` loses about
  half its digits (R4). The consistency test's tolerance needs that (section 12).
- **Edge cost:** `θ(u, v) · (1 + 1/support)`. When either endpoint has no vector, the cost is `π · (1 + 1/support)`.
- **Heuristic:** `h(n) = θ(n, goal)`, or 0 when either vector is missing.
- **Why it is optimal:** angle on the unit sphere obeys the triangle inequality, which 1 − cosine
  does not. Every edge costs at least its own angle, and at least π when a vector is missing, while
  `h ≤ π`. So `h` is consistent and A* returns a cheapest route. 6.3 proves the general case.
- **Order:** the open list is ordered by `(f, h, memory id)`, so ties resolve the same way every run.
- **Bounds:** at most 10,000 node expansions (a calibration hypothesis, not a compiler limit). The
  route tool also stops at 500 ms of wall time. Hitting either bound returns `truncated` and no
  route. In the tools, a cheapest route of more than 64 stops is `truncated` too (6.5).
- **Output:** memory ids only; a caller with store access looks up content itself (the tools of 6.6 are such a
  caller). It lists:
  - the route's memory ids, and each step's support and whether it is a road;
  - **detours avoided:** each detour whose endpoints X and Y the route visits, X before Y, and
    whose route between them is the detour's shorter side, with N, the number of sessions that
    travelled that shorter side.

### 6.2 Locate from context

Andy: "The context gives the graph positions which surfaces sheaves as paths." The vision: "'Where am I' comes from
what is in front of the agent: the bug, the files, the error. The nearest memories are the entry stations."

The search runs over one lane's tool graph `G_L` (6.6), whose node set is `V_L`: every memory in a current trail of
lane L. Each node n may have a stored unit vector `v(n)`.

**Inputs.** Context text `x` (may be empty), memory ids `H` the agent holds (at most 6, may be empty), and the lane.
At least one of `x` and `H` must be non-empty. When `x` is non-empty, it is cut to 4,000 characters and embedded the
way recall embeds a query, `embed([x], prefix="search_query")` (`server.py:2186`). Its unit vector is `c`. The
nodes' stored vectors were embedded from their content with `search_document` (`remember`, `server.py:1867`), so
every `θ(c, n)` is a query-to-document angle. `c` is undefined when `x` is empty or the embedder fails.

**Three sources, in this order** (R1):

1. **Given.** Each id in `H` that is a node of `V_L`, in the caller's order. `why: "given"`.
2. **Words.** Anchors are matches in `x` of these patterns (Python `re`), each 3 to 128 characters long:
   - a path with a slash, `(?:[\w.-]+/)+[\w.-]+`, or a file name, `[\w-]{2,}\.[A-Za-z][A-Za-z0-9]{0,4}\b`;
   - an error name, `\b[A-Z][A-Za-z0-9]*(?:Error|Exception|Warning)\b`;
   - a snake_case identifier, `\b_*[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b`, or a camelCase one,
     `\b[a-z]+[A-Z][A-Za-z0-9]+\b`. The leading `_*` is needed: `_` is a word character, so without it `\b` can't
     sit before the first letter of `_record_application`, and nothing would match it.

   Overlaps: run every pattern over `x` with `finditer`, and drop each match whose span lies inside the span of a
   longer match. Order what is left by start position, keep the first match of each distinct text, and take the
   first 8. So `engram/server.py` yields `engram/server.py` and not also `server.py`, and `sqlite3.OperationalError`
   yields `OperationalError`.

   Each anchor is searched as one quoted phrase in `episode_fts` and `semantic_fts`, at most 64 ids per anchor per
   table. Hits that are nodes of `V_L` and not already chosen are ordered by `θ(c, ·)` (nodes without a vector
   last), then id, or by id alone when `c` is undefined, and the first 2 are taken. `why: "words"`. Words need no
   embedder.
   Why anchors and not the whole text: engram's FTS search quotes every token and joins them with an implicit AND
   (`storage.py:64-74`, `:1062-1071`), so a whole error message almost never matches. A file path or an error name
   does.
3. **Near.** Nodes of `V_L` with a vector and `θ(c, n) ≤ r_max` (6.3), by `θ` and then id, until there are 6
   stations. None when `c` is undefined. `why: "near"`.

The **entry stations** `E` are what these give, at most 6. If `E` is empty, the answer says "nothing on the trails
is near this context" and names nothing.

**Entry cost** `w(e)` (R2):

- 0 for a given id: the agent says it is there;
- `2·θ(c, e)` for words and near: the cost of an untrodden footpath, since `1 + 1/1 = 2` (6.1). Walking to a station
  should cost no less than walking an unwalked step;
- `2π` when `c` is undefined or `e` has no vector.

Each station reports `θ(c, e)` (null without `c` or a vector) and `through`, the number of sessions in the tool
graph whose full trail touches it.

### 6.3 Route to a goal given in words

The vision: "If the agent knew which memory held the answer, it would recall it." So the goal is given in words,
and A* runs to every memory close enough to them.

**Definitions.**

- Goal words `y`, cut to 4,000 characters, give the unit vector `q`, embedded as in 6.2. `trail_route` embeds `x`
  (when non-empty) and `y` in one batch, `embed([x, y], prefix="search_query")`.
- `θ_min = min θ(v(n), q)` over the nodes of `V_L` that have a vector.
- The radius is `r = min(θ_min + δ, r_max)` with `δ = 0.10` and `r_max = arccos(0.60) ≈ 0.9273` (R3, below).
- The **goal set** is `Γ = {n ∈ V_L : n has a vector and θ(v(n), q) ≤ r}`. It is empty exactly when no node has a
  vector or `θ_min > r_max`.
- The heuristic is `h(n) = max(0, θ(v(n), q) − r)` when n has a vector, and `h(n) = 0` when it has none.

**The search.** A* starts from every entry at once: each `e ∈ E` enters the open list with `g(e) = w(e)` and no
predecessor (6.2). Edges and their costs are those of 6.1. Relaxing an edge `u → v` replaces `g(v)` and makes u the
predecessor of v only when the new cost is strictly lower, so ties keep what was there. A node is a goal when it is in
`Γ`. The search stops when it pops a goal,
and returns the route from that goal back to its entry. The route's **cost** is `g` of the popped goal: its entry's
`w(e)` plus the route's edge costs, the quantity Claim 3 minimizes. The open list is ordered by `(f, h, memory id)`.
The bounds are 6.1's.

**Lemma 1 (angle is a metric).** For unit vectors a, b and c: `θ(a, b) ≥ 0`, `θ(a, a) = 0`, `θ(a, b) = θ(b, a)`,
and `θ(a, c) ≤ θ(a, b) + θ(b, c)`. This is the great-circle distance on the unit sphere. Every vector here, `q` and
`c` included, lies on the same sphere, so the inequality holds whichever prefix embedded it.

**Lemma 2 (every edge costs at least its angle).** For every edge `u → v`, `c(u → v) ≥ θ(u, v)` when both ends
have vectors, and `c(u → v) ≥ π` when either lacks one. *Proof.* `support ≥ 1`, so `1 + 1/support ≥ 1`, and the
cost is that factor times `θ ≥ 0` or times `π`. ∎

**Claim 1 (h is consistent).** For every edge `u → v`, `h(u) ≤ c(u → v) + h(v)`. And `h(n) = 0` for every n in `Γ`.

*Proof.* Three cases.

- u has no vector. Then `h(u) = 0`, and `c ≥ 0`, `h(v) ≥ 0`.
- u has a vector and v has none. Then `h(u) ≤ θ(u, q) ≤ π ≤ c(u → v)` by Lemma 2, and `h(v) = 0`.
- Both have vectors. By Lemma 1, `θ(u, q) − r ≤ θ(u, v) + (θ(v, q) − r) ≤ θ(u, v) + h(v)`. Also
  `0 ≤ θ(u, v) + h(v)`. So `h(u) = max(0, θ(u, q) − r) ≤ θ(u, v) + h(v) ≤ c(u → v) + h(v)` by Lemma 2.

For n in `Γ`, `θ(n, q) ≤ r`, so `h(n) = 0`. ∎

**Claim 2 (h never overestimates).** For every node n from which some goal is reachable, `h(n) ≤ h*(n)`, the cost
of the cheapest path from n to any node of `Γ`.

*Proof.* Take a cheapest such path `n = n_0 → n_1 → … → n_k`, with `n_k ∈ Γ`. Add Claim 1 along it:
`h(n_0) − h(n_k) ≤ Σ c(n_i → n_{i+1}) = h*(n)`. Since `h(n_k) = 0`, `h(n) ≤ h*(n)`. ∎

**Claim 3 (the route is cheapest).** Among all entries e and all goals, the route returned minimizes
`w(e) + cost(path)`.

*Proof.* Define reduced costs `c′(u → v) = c(u → v) − h(u) + h(v)`, which are `≥ 0` by Claim 1. A* with keys
`f = g + h` is Dijkstra's algorithm on `c′` with start keys `w(e) + h(e)`. Along any path from e to a goal t, the
reduced costs add up to `cost − h(e) + h(t) = cost − h(e)`, so t's key is `w(e) + cost`. Dijkstra pops keys in
non-decreasing order, so the first goal popped has the least `w(e) + cost`. Equivalently: add a source with an edge of
cost `w(e)` to each entry, and a sink with a zero-cost edge from each goal and `h = 0`. Claim 1 still holds on the
new edges, and A* on that graph is the textbook case. ∎

The proofs hold for every `q`, because `r` is fixed before the search starts. They are in exact arithmetic. Kahan's
angle (6.1) keeps the floating-point error far below the test tolerance of 1e-9 (section 12).

**Nodes without vectors.** A node without a vector is never a goal: closeness to words can't be judged without one.
Its `h` is 0. It can be an entry (given, or found by words) and an interior node of a route, through edges that cost
at least π.

**Why this r** (Rio Grande's call, R3).

- *A set, not a node.* Words name a goal less sharply than an id. Several memories sit about equally close to them,
  and the trail should reach whichever it can. `δ = 0.10` rad is about 5.7°. Near `θ = 0.8` (cosine 0.70) that is a
  band of about 0.07 in cosine.
- *A ceiling.* Past `r_max`, nothing on the trails is about the goal, and recall is the right tool. Engram links two
  memories at cosine 0.70 (`reinforce_threshold`, `config.py:44`; `suggest_edges`, `graph.py:461`), which is a
  document-to-document measure (`vec0_distance_to_similarity`, `storage.py:23-28`). Goal words are embedded as a
  query, and query-to-document cosines run lower, so the ceiling sits 0.10 below, at cosine 0.60.
- *The regime.* So `r`, `δ` and `r_max` are set for query-to-document angles: `q` and `c` embedded with
  `search_query`, the nodes' vectors stored with `search_document` (6.2). Anything that calibrates them must measure
  that regime.
- *Both are calibration hypotheses* (section 10). Measure W embeds its context and goal the way the tools do (section
  7, step 8), and reports how often `Γ` was empty and the spread of `θ_min`. That is the evidence a later revision
  would need. W's stored-vector diagnostic is document-to-document, so it is not evidence for `r`.

**What the answer says** (`end`, 6.5):

- `goal`: a route ending in `Γ`;
- `at_goal`: the goal A* popped has no predecessor. Only an entry can lack one, since every other node enters the
  open list through an edge. So A* reached it at its own entry cost: its `g` is its `w(e)`, and the route is one stop
  with no steps. Recall it. Being an entry in `Γ` is not enough. If another entry reaches some goal more cheaply, A*
  pops that goal first (Claim 3). If a route through another entry reaches this one for less than its `w(e)`, A*
  lowers its `g` and gives it a predecessor. Either way the answer is `goal`, with that route and its cost. At an
  exact tie the entry keeps no predecessor, and the answer is `at_goal` at the same cost. Claim 3 decides these
  cases; only the wording is Rio Grande's call;
- `no_goal`: `Γ` is empty. The answer names the nearest node that has a vector, and its angle, so the agent can recall
  it instead. When no node of `V_L` has a vector, there is no nearest node, and the answer names none;
- `no_route`: the open list ran empty with no goal popped, before any bound was hit. The answer names the goal-set
  node nearest to `q`;
- `truncated`: a bound was hit before a goal was popped, or the route found has more than 64 stops (6.5);
- `stale`: the output-time check failed twice (6.6).

*Example of `at_goal` against `goal`.* Entry e1 is in `Γ`, found near the context, with `w(e1) = 2θ(c, e1) = 1.0`.
Entry e2 is a given id, not in `Γ`, with `w(e2) = 0`, and an edge `e2 → t` costing 0.3 leads to `t ∈ Γ`. A* pops e2,
then t with key 0.3, before e1 with key 1.0. The answer is `goal`, route e2 → t, cost 0.3, as Claim 3 and the
brute-force test in section 12 require.

*Example of an entry reached through another entry* (the re-check's case, run in Python by the re-check and again for
revision 6). Entry e1 is in `Γ`, with `w(e1) = 1.0`. Entry e2 is a given id, not in `Γ`, with `w(e2) = 0`, and an edge
`e2 → e1` costs 0.3. A* pops e2, lowers `g(e1)` from 1.0 to 0.3 with predecessor e2, then pops e1. The popped goal is
an entry, but A* reached it through e2. So the answer is `goal`, route e2 → e1, cost 0.3. Calling it `at_goal` would
show one stop at cost 0.3, which is no entry's cost. With `w(e1) = 0.3` instead, the route through e2 ties, e1 keeps
no predecessor, and the answer is `at_goal`, one stop, cost 0.3.

### 6.4 Forward lookup

The vision: "Answer 'what did others do next from here'. Forward lookup along the trails that passed through the
entry stations, and where they ended."

For an entry e in lane L, take the current **full** trails of L in the tool graph that contain e: at most the 256
sessions with the newest rows. For each such trail τ, let i be the position of the first occurrence of e.

- **Next.** For every occurrence of e at a position j with a following touch, the successor is `x = τ[j+1]`. For
  each x, `sessions(e → x)` is the number of distinct sessions with an `e → x` step that is neither co-cited nor
  suggested, and `last(e → x)` is the latest such step's time. Successors are ranked by sessions, then by `last`,
  newest first, then by id (R5). A successor whose steps are all co-cited or suggested comes after the rest, with
  sessions 0 and its flag. The answer keeps the first 2. Each carries `kind`, `wrote` or `cited`, from the touch.
- **Ends.** Each session's end is its trail's last touch, `τ[−1]`, reached `|τ| − 1 − i` hops after e. A session
  whose trail ends at e counts toward `ended_here`. The other ends are ranked by distinct sessions, then by the
  latest end time, then by id. The answer keeps the first 2, each with its sessions and median hops (the lower median
  for an even count). A trail cut at 512 touches (`truncated`, section 4) didn't end at its last kept touch, so it
  gives no end. It still gives next items, and it is counted in `ends_unknown`.

**Why full trails.** A full trail includes what the session wrote. "What others did next" is often "they wrote down
the fix", a brand-new episode that the revisit view drops (section 4).

The tool applies this to the first 3 entry stations.

### 6.5 Short answers

The vision: "Return short routes. A list of steps with one-line summaries, each with who laid it, under which rules,
and the receipt for this use."

In this section an answer's list items are **stops**: memories, not the directed pairs that section 2 calls steps. A
route of k stops has k − 1 steps.

**Summary.** A memory's summary is the first non-empty line of its content, with whitespace collapsed to single
spaces and control characters removed. It is cut to the longest prefix of whole characters whose compact JSON form
is at most 160 bytes, with `…` appended (and counted) when cut. The tool reads it from `graph.db` when it answers,
never from the cache.

**Sources.** Every answer has a `sources` map, and every item it names points to one by key in `src` (R6). A source
has three fields:

- `laid_by`: who laid the track. `"<person> (<instance>)"` when the permissions ledger registers this store
  (permissions spec section 5.5, its `stores` table), else `"this store (<instance>)"`. The person is `stores.owner`
  for the row whose `instance_id` is this store's `meta.instance_id`. That column holds a person ref,
  `person:<handle>` (permissions spec 4.1; the imprint spec's 5.1 compares it to `person:<owner>`). `laid_by` shows the
  handle alone, without `person:`, as the permissions spec's annotation does (`andy (engram)`, its section 11). The
  tool graph build reads it once, from
  `ENGRAM_HOME/.engram/permissions.db` opened with `mode=ro` and `query_only` (the ledger's path, permissions spec
  5.5). A missing or unreadable ledger gives `"this store (<instance>)"`. The instance is the server's instance name,
  or `default` (`server.py:1976`). This fills the permissions spec's `laid_by` for roads and trails (its section 11).
  When the tools later read an imprint (section 9, step 7), the person is the owner of the imprint's source,
  `forked_from_instance_id`, not of the imprint: an imprint keeps its source's refs, and its own store's owner is never
  their subject (permissions spec 7.4; imprint spec section 11).
- `allowed_by`: the rule. In step 1 every answer reads the server's own store for its own agent, which the
  permissions spec does not check ("Checking a store's own sessions recalling their own store. That is the person's
  own memory in their own home", its section 14). So the rule is `"own store"` (R14). Later steps fill the cited
  records, as the permissions spec's annotation does (its section 11).
- `receipt`: the short id of this answer's receipt (6.6).

In step 1 there is one source, `h`. In later steps, stops from another store carry that store's source.

**Per-stop provenance.** Each stop also carries `via` and, after the first, `walked`. Both describe the step that
reaches the stop. The first stop's `via` is its entry kind, one of `entry:given`, `entry:words` or `entry:near`. A
later stop's `via` is `road` or `footpath`, and `walked` is `"<support> sessions, last <YYYY-MM-DD>"` (`session`
when the support is 1), where the date is the latest supporting session's step time. When that step has support 0,
`walked` says `"footpath (co-cited)"`, `"footpath (suggested)"` or both.

**Example.** A `trail_route` answer, with ids shortened here:

```json
{"tool":"trail_route","lane":"work","as_of":"2026-10-25T18:00:00Z",
 "sources":{"h":{"laid_by":"andy (default)","allowed_by":"own store","receipt":"#5e21a9c0"}},
 "goal":{"radius":0.6213,"nearest":0.5213,"size":3},
 "route":[
  {"id":"8c1d…","layer":"episode","summary":"recall() logs target_ids before uninvited results are added","via":"entry:near","angle":0.4102,"src":"h"},
  {"id":"2b77…","layer":"semantic","summary":"a lane-filtered recall rewrites target_ids afterwards","via":"road","walked":"3 sessions, last 2026-10-20","src":"h"},
  {"id":"f03a…","layer":"episode","summary":"fix: count exactly one target after instincts are removed","via":"footpath","walked":"1 session, last 2026-10-22","to_goal":0.5590,"src":"h"}],
 "end":"goal","hops":2,"cost":1.9381}
```

`cost` includes the entry cost (6.3): here `w = 2 × 0.4102 = 0.8204`, and the two steps cost the other 1.1177.

**Size.** Every answer is at most **6,000 bytes** of UTF-8 compact JSON (`separators=(",", ":")`,
`ensure_ascii=False`). `category_compile.estimate_tokens` (`category_compile.py:195-197`: UTF-8 bytes plus 3, divided
by 4) counts that as 1,500 tokens, which is how revision 4 stated it. It is a byte bound, not a token bound. A
36-character UUID and CJK text cost more real tokens than a quarter of their bytes, so an answer can cost noticeably
more than 1,500 tokens of an agent's context. The builder measures the largest test answers with the tokenizer of
the model the agents use and records the ratio in the plan's results (section 12). If the largest answer comes to
more than 2,000 real tokens, the next revision lowers the byte bound. Rio Grande's call (R6).

These caps make the bound hold by construction:

- a route has at most 64 stops; a cheapest route with more is answered `truncated` (6.3). It shows at most 12 stops.
  A longer one shows its first 6 and last 6 around one `{"skipped": k}`, where k counts the stops left out;
- `trail_locate` names at most 6 stations, and `trail_next` at most 3 stations with 2 next and 2 ends each;
- summaries are at most 160 bytes, angles have 4 decimals, and there are no scores, session ids, or echoes of the
  context or goal text.

With 36-character ids, an item is at most about 340 bytes (the reviewer built a worst case of 338), so the largest
answer, `trail_next`'s 15 items, comes to about 5,300 bytes with its header and sources. If an answer still exceeds
the bound (for example, with ids longer than a UUID), the tool drops, in order: the summaries of items that are
neither entries nor the last stop; then every summary; then every stop but the first 3 and last 3. A recall, by
comparison, returns up to 20 matched memories with their full content (`server.py:2068`, `:2281-2286`), plus
uninvited and resonant ones.

### 6.6 The tools

**Gate.** `[trails] tools = false` is the default, and only an exact boolean `true` turns the tools on, checked with
`is True` as the observer's gates are (`server.py:2650`). When it is not exactly `true`, the tools are not
registered at all, so agents see no tool definitions and pay no tokens for them (R7). Registration happens in
`_initialize_pre_serving`, after `_init` has loaded the config and before `mcp.run()` (`server.py:4023-4038`),
through `_server_tool()` (`server.py:690-697`), so every call holds the lifecycle barrier as every tool call does.

The tools need nothing from `[category_evolution]`. They read `graph.db` only, so they do not depend on the v2
observer, whose acceptance is false ("Evolving-category v2" in `engram/CLAUDE.md`). Rio Grande's call.

**Lanes** (R16). `[trails] lanes` lists the lanes the tools answer. It defaults to `["work"]` when absent. A value
that is not a list of distinct strings, each `work` or `personal`, enables no lane: every call answers
`{"error": "lane not enabled"}`, and the build builds nothing and records `lanes_invalid`. A call for a valid lane
that isn't listed answers `{"error": "lane not enabled: <lane>"}` and names nothing. The build builds only the
listed lanes. `lanes = []` is valid and lists no lane: with `tools = true` the tools are registered, every call
answers `{"error": "lane not enabled: <lane>"}`, and the build builds nothing. The bounds below are split among the
listed lanes, so with none there is nothing to split and no division. A gate pass licenses the lane it evaluated (section 7, step 9), so an owner lists a lane only after
that lane passes. Rio Grande's call.

**The surface.**

| Tool | Arguments | Answer |
|---|---|---|
| `trail_locate` | `context: str = ""`, `memory_ids: list[str] \| None = None`, `lane: str = "work"` | the entry stations (6.2) |
| `trail_route` | `goal: str`, `context: str = ""`, `memory_ids: list[str] \| None = None`, `lane: str = "work"` | a route to the goal set (6.3) |
| `trail_next` | `context: str = ""`, `memory_ids: list[str] \| None = None`, `lane: str = "work"` | the forward lookup (6.4) |

- `lane` is `work` or `personal`, and anything else is an error, as in recall (`server.py:2089-2090`). The default
  is `work`, as revision 3's `route` has it. A lane not in `[trails] lanes` is refused (above).
- `memory_ids` holds at most 6 strings. More is an error. Ids that are not nodes of the lane are ignored and counted
  as `ignored`.
- `context` and `goal` are cut to 4,000 characters, and the answer says so when it cuts.
- At least one of `context` and `memory_ids` must be non-empty. `trail_route` also needs a non-empty `goal`.
- If the embedder fails, `trail_route` returns `{"error": "embedder unavailable"}`, since `q` needs it.
  `trail_locate` and `trail_next` fall back to given ids and words, which need no embedder (6.2): word stations are
  ordered by id and cost `2π`, there are no near stations, and the answer reports `degraded: ["embedding"]`.

The descriptions agents see:

- `trail_locate`: "Where am I on the trails? Give the task, file paths or error text, or memory ids you hold. Returns
  up to 6 memories other sessions walked through."
- `trail_route`: "Route along trails other sessions walked, from your context to a goal in words. Returns a short
  list of stops. Recall a stop's id to read it in full."
- `trail_next`: "What did other sessions do next from here, and where did they end? Give your context or memory ids."

**The tool graph** (R10). It is built once per server process, as the last step of the deferred maintenance pass,
after `persistence-score-refresh` and before the report is saved (`server.py:1279-1290`), and only when the tools
are registered. It reads `graph.db` through its own `Storage.open_read_only` connection (`storage.py:127-161`),
which never writes and needs no barrier, and takes the lifecycle barrier only to swap the finished graph in. Its
`as_of` is the build's start. For each listed lane it holds:

- the full and revisit trails of the 4,096 closed sessions with the newest rows, derived as in section 4;
- the nodes, and each step's support, road status (section 5's eligibility), latest time and flags;
- each step's angle `θ(u, v)`, computed once at build time (262,144 × 8 B ≈ 2 MB), so A* never takes a 768-term dot
  product per expansion; a step with a vectorless end stores none and costs `π · (1 + 1/support)` (6.1);
- for each node, the sessions whose full trails touch it (`through`, and the postings that 6.4 reads);
- the unit vectors of the nodes, read from `episode_vectors` and `semantic_vectors` and held as float32, the form
  they are stored in (`storage._pack_embedding`, `storage.py:59-61`; `paths._unpack_embedding`, `paths.py:43-44`).
  Holding them as float32 loses nothing: each 4,096-row block is converted to float64 when a call uses it, which
  gives the same numbers as converting all at once. At the bound that is 20,000 × 768 × 4 B ≈ 61 MB, not 123 MB.

In all it holds at most 20,000 nodes and 262,144 distinct steps. The bounds are split equally among the listed lanes:
one lane gets all of it, two lanes get half each, so one lane can't starve the other. If a lane's newest sessions
would pass its share, the build stops that lane at the first session that would, keeps what it has, and records
`truncated` for that lane. Until the graph is ready, a tool answers `{"note": "trail graph not ready"}` and names
nothing. Building after `prune` is right here: the tools must not name memories that have moved to cold storage.

The build registers its read-only connection with the server's cleanup coordinator,
`_register_server_cleanup(conn, conn.close, "trail graph build")` (`server.py:835-838`), as the maintenance thread
itself is registered (`server.py:4018`). Shutdown then closes it, and a forked child quarantines it with the rest of
the generation's resources (`_before_server_fork` and `_after_server_fork_child`, `server.py:252-256`, `:374-379`).
Between batches of 64 sessions the build asks the generation for admission, as each maintenance step does
(`_admit_server_operation`, `server.py:809-819`, used by `_maintenance_step_scope`, `:1096-1112`). When it is
refused because the generation is shutting down, the build stops and discards what it has.

**One graph per process.** Claude Code runs one engram server per session, and each builds its own graph. With k
sessions open, a machine holds k graphs: at most k × 256 MB at the bounds, on top of the roughly 320 MB that each
server already peaks at with the shared embedder (`engram/CLAUDE.md`, measured 2026-10-02). For 4 sessions that is
up to about 2.3 GB. Sharing one graph per machine is a later optimization, not step 1. Rio Grande's call.

The build enforces the counts: 4,096 sessions per lane, 20,000 nodes and 262,144 steps. It doesn't measure bytes.
256 MB per process is a target, and the Pi measurement checks the build's peak against it (section 12). If the peak is
over, the builder uses more compact structures within the same counts, or the next revision lowers the counts. Rio
Grande's call.

**Output-time check** (R11). Before it answers, a tool reads the current lane and existence of every node of the
computed route (at most 64), every entry station it used (at most 6), and every other memory it would name, from the
server's store: at most 70 rows. That includes the stops hidden in `{"skipped": k}`. A memory now in another lane, or
gone, is removed from the cached graph with its edges, and the tool computes once more. If the second answer would
also hold one, it returns `{"end": "stale"}` and names nothing. So a re-lane after the build never puts a personal
memory anywhere in a work route, shown or skipped, and never shows a route the agent can't follow.

**Receipts** (R8). Each answer that names at least one memory appends one `memory_log` row through
`Storage.add_log_entry` (`storage.py:1656-1680`):

- `event_type = 'route_shown'`, `layer = 'trail'`, `outcome` null;
- `target_ids`: every memory id the answer names, in order;
- `context`: `{receipt_id, session_id, tool, lane, as_of, graph_digest, rule_version}`.

`receipt_id` is the row's id, a uuid4. Its short form is `#` and its first 8 hex characters. 4 hex characters would
give even odds of a repeat at about 300 receipts (the birthday bound over 65,536 values), and the short form is the
agent's only handle on its receipt. 8 give even odds only near 77,000. The permissions spec shows its receipts the
same way, `#` and 8 hex (its section 4.1); only its records, grants and proposals keep 4 hex for display. Rio
Grande's call. The row holds no context text, goal text or summary, since a receipt never
holds content or query text (permissions spec section 9.1). `graph_digest` is the SHA-256 of the canonical JSON of
the graph's `as_of`, its rule version and its sorted current trail digests. A reader can rebuild the graph from
`graph.db` and `as_of`, and check against it that every id the receipt names is a node of the lane and every shown
step an edge. A reader can't rebuild the answer itself: it also depends on `c` and `q`, which come from text the
receipt deliberately doesn't hold, on FTS hits, and on any memories the output-time check removed from the cached
graph after the digest was taken. A non-recall row in `memory_log` has precedents (`proximity_suggestion`,
`graph.py:502-512`), and the per-session counters ignore event types they don't know (`storage.py:1765-1789`).

**Read-only, precisely.** The receipt row is the tools' only write. They never:

- change a memory, lane, vector, cell or event;
- increment access counts, as recall does (`server.py:2389-2391`), since showing a route is not use, and access
  feeds decay;
- log an operation: they are not wrapped in `_mutation_logged` (`server.py:38-64`);
- apply the dream bias (`_apply_recall_bias`, `server.py:1499`), so they have no dream-tilted scores to hide;
- change recall output.

They write the receipt for two reasons. Vision principle 5: "Every use of a memory leaves a receipt that its owner
and the place's people can read." And section 4 needs it to mark suggested touches.

**Diagnostics.** `reflect(focus="trails")` (dispatched beside the other focuses, `reflection.py:732-775`) returns
counts only: the graph's `as_of`, sessions, nodes, steps, roads, `truncated` and `lanes_invalid`, build seconds and
bytes; calls per tool; answers ending `no_goal`, `no_route`, `truncated` or `stale`; answers shrunk by 6.5's
fallback; receipts written; and, from `graph.db`, `route_shown` rows and suggested touches in closed sessions.

Where the counts live: the graph and the per-call counters are server memory, held in `server.py` beside the graph,
and they start from zero in each process. The `Reflector` holds only storage and a few paths and configs
(`reflection.py:53-66`), so it gets them the way it gets the category diagnostics: through a callable passed to its
constructor, a new `trails_reporter` beside `category_reporter` (`reflection.py:60`, `:69-77`; `server.py:1418-1430`).
Without one it answers `{"available": false}`, as `analyze_category_evolution` does. The `graph.db` counts it reads
through its own storage.

## 7. Evaluation (decides whether anything is enabled)

**Where it runs** (R13). A store that isn't the runner's own is evaluated only on an imprint whose owner agreed: an
imprint admitted under the imprint spec whose permission lists the action `route` and the purpose `trail-evaluation`
(imprint spec section 5.3 and its D10). The first evaluation is such a run (the vision's "How the work runs", step 3;
change C5). It runs through that spec's `trail-evaluation` use (its section 12), which checks the permission, writes
the use receipts, and runs `trails.py <imprint dir>/imprint.db --evaluate --lane <lane> --seed N --deadline 1740
--json --imprint-use <use id>`, with one lane of the imprint's scope (step 9). The use always passes `--lane`. When
`LANE` is left out because the scope holds one lane, the use fills in that lane (I2). On an imprint, `trails.py`
refuses to run without an explicit `--lane`, so a personal-only imprint never runs on `work` by default. Rio Grande's
call. That use's `read` covers reading
memory text inside the run to find cited touches, to embed W's texts and to find their anchors. Only counts and rates
leave the run (imprint spec section 8, "The decision").
It also runs on synthetic stores in the tests. Every threshold below is fixed before the first run on real data, and
a failure revises the design, not the thresholds.

An owner may also run `trails.py --evaluate` on a plain copy of their own store. That is the person's own memory in
their own home, the permissions spec's non-goal (its section 14), and it needs no imprint. `trails.py` doesn't check
who owns a plain copy; it can't. A pass on the owner's own copy counts for that store as a pass on an imprint of it
does (step 9).

**The imprint check.** `trails.py` treats a file whose `meta.instance_id_origin` is `imprint` as an imprint. Let
`<imprint dir>` be the directory holding the opened `imprint.db`, `<id>` its name, and `<root>` its parent, as the
imprint spec lays them out: `~/.engram/imprints/<imprint id>/`, its state directory `<imprint id>.state/` beside it,
and tombstones in `tombstones/` (its sections 10 and 12). `trails.py`:

1. refuses unless `<id>` equals the file's `meta.instance_id`;
2. takes `--imprint-use <use id>`, a use id of at most 64 characters from `[A-Za-z0-9-]`, never a path, and reads
   the allow file only at `<root>/<id>.state/uses/<use id>.allow.json`, where the imprint spec's use step writes it
   (its section 12; the imprint directory itself is 0555 after admission). A symlink at any part of that path is
   refused. The imprint spec names the form of a use id, a lowercase uuid4 of 36 characters, which fits (its D41;
   I2);
3. refuses when the tombstone `<root>/tombstones/<id>.json` exists, which is how that spec marks a withdrawal or a
   deletion (its section 12), or when the state directory is gone, since a withdrawal removes it;
4. refuses unless the allow file names this file's `meta.instance_id`, the action `route`, the purpose
   `trail-evaluation`, and a `valid_until` later than now. The imprint spec writes there the effective end, the
   earliest of the records' `valid_until` and every shortening, and rewrites the file atomically when the end is
   shortened (its section 12; I2);
5. refuses when the use's directory `<root>/<id>.state/uses/<use id>/` already holds a `report.json` or a
   `result.json` (the names the imprint spec's use step writes, its section 12 and D41; I2). One use id gives one
   run. A use that has finished also has no allow file any more, because finishing retires it (I2), so check 2
   refuses it too. So rerunning an old command from shell history can't make a use without a receipt (vision
   principle 5). Rio Grande's call;
6. opens the file `mode=ro&immutable=1`, as `store_reader.connect(path, immutable=True)` does
   (`store_reader.py:43-54`), and keeps the allow file's SHA-256;
7. checks again when the run ends: the allow file is still there with the same SHA-256, no tombstone exists,
   `imprint.db` is still at its path, and `valid_until` has not passed. If any check fails, `trails.py` discards the
   report, prints nothing to standard output, and exits with status 3, named `allow changed`. It doesn't say why. A
   withdrawal, a shortening and an end reached all change what it checks. The use then writes no `use-finished`
   receipt with a report. It records the run's end from the station's side: `withdrawn` only when the tombstone
   exists, `ended` when the effective end has passed, and `allow changed` otherwise, for example after a shortening
   whose new end is still ahead (I2). The imprint spec adds two ends this list doesn't name: `deleted` for a station
   deletion during the run, which writes a tombstone but is no withdrawal, and `failed` for a run that ended with no
   report for another reason (its section 12 and D41). Discarding the run only narrows. Rio Grande's call.

**Known limit.** The allow file is unsigned. Any process running as the station's Unix user can write one. Like the
permissions spec's terminal yes ("this narrows mistakes, not malice", its section 7.6), this check narrows mistakes,
not malice: it keeps an evaluation from running on an imprint by accident, against the wrong imprint, after a
withdrawal, or a second time under one use id. Rio Grande's call.

**What an imprint changes.** The imprint keeps episodes and semantics whole, with one exception: an episode's
`session_id` ships only when the owner chose `route` (R18, I5).

A trail is one session's touches in one lane, in order (section 2), and a wrote touch is every episode carrying that
session's id (section 4). So episodes with their session ids already hold the order in which each session wrote: a
trail with no log row at all. Calibration on a plain copy reads exactly that. `paths.report` (`paths.py:418-426`)
calls `session_paths`, which groups episodes by `session_id` in `(created_at, id)` order (`paths.py:348-354`), and
calibration calls it (`calibrate.py:295-296`). Revision 5 missed this. An imprint without `route` would have kept the
owner's wrote-touch trails with no record covering them and nothing in the dry run saying so, against section 8's
"sharing a memory is still not consent to sharing routes" and the vision's "Count its own trails as the person's".
So, Rio Grande's call (I5, option (a) of the re-check):

- **Without `route`,** every episode ships with `session_id` null, and no log row ships. No trail of any kind is on
  the imprint. `trails.py` refuses it anyway, since no allow file can name `route` (checks 2 and 4). The cost falls
  on calibration: on such a file `paths.report` would find no session (`paths.py:349`, `:423`), and `store_reader`'s
  survey counts no sessions and no log rows (`store_reader.py:111-121`, `:126-131`). The imprint spec's admission
  report notes why, "because route was not chosen" (its 5.2 and 10). Privacy wins, by the interface pass's rule.
- **With `route`,** episodes of sessions closed at t₁ keep `session_id`, so their wrote-touch trails are on the
  imprint. A session still open at t₁ keeps neither its session ids nor its log rows (imprint spec 5.2). Cited touches
  come from the log rows; only they depend on log rows. The owner's yes to `route` covers both, and the dry run and
  confirm view say both leave (I5).

**At admission, calibration reads no session path, with or without `route`** (the imprint spec's revision 4, its
sections 8 and 10). With `route`, the shipped session ids are trail material, and the owner's record for roads and
trails names only the purpose `trail-evaluation`. So admission runs calibration with `no_paths`, and the report's
`paths` section says only "not measured at admission". Without `route` there would be no session to measure. This
spec reads nothing from calibration's `paths` section, so no rule here changes.

Episode write times stay in every imprint: the imprint spec's time window and plan digest read `created_at` (its 5.2
and 5.4). Someone could guess sessions from the gaps between write times. No record says which episodes one session
wrote, and nothing in step 1 guesses. That is a known limit. Rio Grande's call.

With `route`, the imprint keeps log rows only from sessions closed at the plan's end t₁ and inside the plan's dates
(imprint spec D7 and 5.2). Of those rows it keeps:

- recall rows whose targets all ship once instinct ids are removed, with `context` cut to `recall_id` and
  `session_id`, and the outcome normalized;
- `route_shown` rows with their targets cut to what ships, dropped when nothing is left (its D35);
- citing operations whose targets all ship (its section 6.2, D6 and D7).

Cold storage never ships in step 1 (imprint spec section 6.3, and section 17, step 5).

That removes much more than the memories left at home. A recall without a lane filters nothing: the lane filter
runs only when a lane is given (`server.py:2332-2333`), and the row then logs all of up to 20 delivered ids
(`max_results`, `server.py:2068`; logged at `:2380-2386`) from both lanes. So:

- a work-lane imprint keeps a default recall only when every one of its up to 20 matches shipped, so it drops
  nearly every recall that matched even one personal memory;
- any imprint drops every recall with a target since pruned to cold storage;
- each dropped row takes with it the cited touches of the memories that did ship.

Revisit trails are made of cited touches only (section 4), so roads, detours and both gates thin out, and on a first
imprint they may well come out "not evaluable". Revision 4 said "an imprint's trails are the source's trails without
the memories left at home". That was wrong.

**The cost, chosen for privacy** (R17). Revision 5 asked the imprint spec to keep a used recall row with its shipped
targets and a `cut` flag (I4, section 11). The interface pass declined it. A cut row says that something the recall
matched stayed home, and the imprint spec's rule is that nothing in a package tells about what stayed home (its D21).
Where privacy and trail quality conflict, privacy wins. Rio Grande's call. What it costs this evaluation:

- Every used recall that matched a memory left at home, or one since pruned to cold, is gone. The cited touches of
  the memories that did ship go with it.
- Revisit trails are cited touches only, so revisit trails, roads, detours and both gates thin out. A first imprint
  will likely come out "not evaluable", and a pass on an imprint is evidence about a sample biased toward sessions
  whose recalls stayed inside what shipped.
- A `route_shown` row whose every target stayed home is dropped too (imprint spec D35). A session that a tool steered
  only toward such memories looks unsteered on the imprint, so it can qualify for the gates though a tool pointed its
  way. No suggested touch is lost, since none of those memories is on the imprint.
- Even on the rows that ship, an imprint's trails differ from the source's restricted to what shipped: a cited touch
  whose only evidence (a later episode or citing operation) stayed home is lost; a session's first touch, and so its
  revisit view, starts at its first shipped touch; and which of the newest sessions count as closed can differ,
  because the CLI's `as_of` is the newest timestamp in the copy (section 4). Touches that drop out join their
  neighbors into one step, as lane filtering already does (section 4).

The cost can fall without telling more, on the source side. A recall made with a lane, `recall(query, lane="work")`,
logs only that lane's memories: the lane filter runs before truncation and reads a memory with no lane, an instinct
included, as personal (`server.py:2332-2333`). So a work-lane imprint keeps far more of an owner's lane-filtered
recalls than of their default ones. The synthetic-imprint test (section 12) measures the loss.

The imprint spec's revision 3 had a test "A trail derived from the package equals the trail derived from the source
restricted to M" (its section 16, "Recall rows"). It asserted more than holds: on a fixture with one mixed-lane recall
it fails, for the reasons above. I6 asked that spec to assert what does hold, and to point to this spec's
synthetic-imprint test for what is lost. Its revision 4 does (section 11, I6).

The imprint carries no query text, so measure W can't replay what the agent typed. It embeds the stored text of
memories instead (step 8).

**1. Split.** Order closed sessions by first touch, and hold out the last 20%.

- The **cutoff** is the first touch of the first held-out session.
- Training uses only training-session touches before the cutoff, and only memories created before
  it.

**2. Qualifying sessions.** A held-out session qualifies when it touched at least 3 distinct
pre-cutoff memories in the evaluated lane (the CLI's `--lane`; revision 3 wrote "one lane"). Let `s` be the first
and `g` the last; the session's *interior*
is its other pre-cutoff memories. A held-out session with any `route_shown` row qualifies for neither measure, and
is counted as `steered`: a tool pointed its way.

**3. Graphs,** built from training data only. In the evaluation, suggested steps are left out of T and S, and B is
built over T's nodes, so no graph learns from the tools' own advice.

- **T, the trail graph:** training steps as directed edges, costed as in section 6.
- **S, shuffled trails:** the order-free ablation. Each training trail is shuffled in blocks: all
  touches cited from one recall form one block and keep their delivered order, and every other touch
  is a block of one. Then the same rules apply. S has T's popularity and co-retrieval without the
  agent's order. Each session's S score is the mean over K = 10 shuffles, with seeds derived from
  the recorded seed, so one lucky shuffle can't decide the gate.
- **B, nearest neighbors:** the similarity-only baseline. Each node of T is linked, undirected, to
  its 8 nearest nodes of T by angle, with edge cost equal to the angle. Building B over T's nodes,
  not every memory, means T can't win on popularity alone. A node without a vector has no
  neighbors in B, so sessions whose `s` or `g` lacks a vector are left out of the gate and counted.

**Seeds.** Every random stream derives from the recorded seed: the stream for purpose p uses
`int.from_bytes(sha256(f"{seed}:{p}".encode()).digest()[:8], "big")` as a `numpy.random.default_rng` seed. The
purposes are `shuffle:0` to `shuffle:9`, `bootstrap:route:T-B`, `bootstrap:route:T-S`, `bootstrap:goal:T-N` and
`bootstrap:goal:T-B`. Rio Grande's call: revision 3 said only "derived", and the report's hash (step 7) needs one
rule.

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
  and later Y, the share whose run between them is the detour's shorter side;
- **next hit** (reported, not gating): with the entry stations of step 8.3 over T's nodes, the share of qualifying
  sessions whose next distinct pre-cutoff touch after `s` is among the forward lookup's next items (6.4) in T, and
  the same in S, averaged over the K shuffles. When the embedder check of step 8.2 fails, the entries are the near
  stations of the stored vector `v(s)` instead, and the report says which regime it used.

**6. The route gate (hypothesis).** All of these must hold:

- at least 30 qualifying sessions. With fewer, the result is "not evaluable", neither pass nor fail;
- T's reach is at least 0.20;
- the paired per-session F1 difference T − B has a mean of at least 0.10, and the lower bound of
  its paired bootstrap 95% interval (10,000 resamples, recorded seed) is above 0;
- the same holds for T − S.

**7. Report.** The CLI writes counts and rates only, never content or ids, for both gates. The report names the
evaluated lane, since a pass licenses only that lane (step 9) and the use's receipt binds the report's hash. It also
names the embedder W used, `{"provider": "shared" | "in-process", "model": "nomic-ai/nomic-embed-text-v1.5"}`, or
null when W had none. The report is canonical JSON (sorted keys, no spaces) with every float rounded to 4 places. So
the same imprint, seed and lane, with the same embedder provider, give the same bytes when no deadline is hit (step
10), and anyone can check the report's SHA-256 in the imprint's `use-finished` receipt (imprint spec section 12) by
running it again. The provider matters: the shared service and the in-process model, or different batch shapes, can
differ in the last bits of a vector and flip a `θ ≤ r` test. A pass makes the case for turning something on for one store (step
9). It does not enable anything; the store's owner decides.

**8. The goal gate: routing to a goal given in words (measure W).** Rio Grande's call (R12). It asks the vision's
question: does routing along trails to a goal in words find the pieces a session used better than recalling the
goal words, and better than routing by similarity alone?

1. *Qualifying.* A held-out session qualifies for W when it qualifies in step 2, is not steered, and wrote at least
   one episode in the evaluated lane at or after its touch of `g`. Let `w` be the last such episode by
   `(created_at, id)`. It is the session's own words about where it ended. `w` is created after the cutoff, so it is
   in neither T nor B, and no training data holds it.
2. *Text and the embedder* (Rio Grande's call, MF1). The tools embed the context and goal as queries (6.2, 6.3), and
   `r` is set for that regime (R3). So W does the same. The context text is `x = content(s)` and the goal text is
   `y = content(w)`, each cut to 4,000 characters, embedded in one batch with `prefix="search_query"` through the
   same function the tools call. `c` and `q` are their unit vectors. With `route`, which this run needs, the imprint
   ships episodes and semantics whole (imprint spec section 6.2; R18), so the text is on the Pi. The run reads it only to embed it and to find its anchors.
   Nothing from it reaches the report. A session whose `x` or `y` is empty after 6.5's whitespace rule is left out
   and counted as `empty_text`.
   - *The embedder.* The run needs the store's embedding model: `nomic-ai/nomic-embed-text-v1.5`, 768 dimensions
     (`embeddings.py:70-71`). It uses the provider `embeddings.create_embedding_provider()` returns
     (`embeddings.py:200-207`): the shared embedder service when `ENGRAM_EMBEDDER_SOCKET` is set, whose model sits
     outside the run's 4 GB cap and which refuses a different model (`embeddings.py:171-177`), or else the in-process
     model, inside the cap (`engram/CLAUDE.md` measures about 1.8 GB for a server that loads its own).
   - *Offline* (R19, Rio Grande's call). The run never downloads a model. Without the socket variable, `trails.py`
     builds the in-process provider with `local_files_only=True`, a new keyword that `NomicEmbedProvider` passes to
     fastembed's `TextEmbedding` (`embeddings.py:78-80`; section 11). fastembed 0.7.4 defaults it to `False`
     (`fastembed/common/model_management.py:139`, `:399`), and then fetches a missing model from the network. With
     `True`, it reads only the cache, `~/.kairos/models/fastembed` (`embeddings.py:12`), and raises `ValueError` when
     the model isn't there (`fastembed/text/text_embedding_base.py:19`; `model_management.py:403-413`, `:463-473`;
     read in the `pr6-update` venv on the Pi). With the socket variable set, a service that doesn't answer raises
     `EmbedderUnavailableError` (`embeddings.py:133-134`, `:191-194`), and the client never loads a local copy
     instead. Either failure, or a missing `fastembed`, makes W "not evaluable: no embedder".
   - *How the unit gets the socket* (Rio Grande's call). A use runs as a detached `systemd-run --user` unit, and such
     a unit starts "in a clean and detached execution environment", not the caller's shell (systemd-run(1), systemd
     252 on the Pi). So the use passes `--setenv=ENGRAM_EMBEDDER_SOCKET=<path>` when the station's
     `~/.config/superyak/runtime.json` names an `embedder_socket`. That is the file and key `superyak-runtime` reads
     to set the same variable for every engram process (`scripts/runtime.py:84-89`, `:597`, `:653-655`). Otherwise
     it passes nothing, and the run takes the in-process path (I3).
   - *Checked against the store's own.* The store records no model name, so the run checks the vectors instead.
     Before scoring, it embeds with `search_document` the content of the 32 earliest episodes, by
     `(created_at, id)`, in the evaluated lane that have stored vectors, as `remember` embeds them
     (`server.py:1867`). The median cosine with their stored vectors must be at least 0.99, or W is "not evaluable:
     embedder mismatch". Rio Grande's call; 0.99 is a calibration hypothesis.
   - The route gate needs no embedder and runs either way.
3. *Entries.* 6.2's locate over T's nodes with `x`, and no given ids, since an imprint carries no ids the agent held:
   at most 2 stations from words, found by FTS in the imprint's own `episode_fts` and `semantic_fts` and kept only
   when they are nodes of T, and the rest near, at most 6 in all, with 6.2's entry costs.
4. *Goal set.* `Γ` over T's nodes by 6.3's rule with `q`.
5. *Methods,* through the same functions the tools call:
   - **T:** 6.3's A* over T from the entries to `Γ`;
   - **B:** the same A* over B from the same entries to the same `Γ`;
   - **N, nearest to the goal:** the n nodes of T outside the entries that are nearest to `q`, by angle and then id,
     where n is the number of nodes T's route names outside the entries, or 4 when that number is 0 (T has no route,
     or answers `at_goal`, where the tool tells the agent to recall). N spends the same context as T. It is not
     engram's recall: it has no FTS, no recency, and no memories outside T. The report calls it "nearest to the
     goal".

   A T or B route of more than 64 stops counts as no route, as the tool would answer `truncated` (6.5).
6. *Scores.* For each method, R is the set of nodes it names outside the entries. The truth U is the session's
   distinct pre-cutoff touches in the lane, minus `s`, minus the entries. Precision is `|R ∩ U| / |R|`, coverage is
   `|R ∩ U| / |U|`, and F1 their harmonic mean. All are 0 when R is empty or there is no route. A session whose U is
   empty is left out and counted as `truth_inside_entries`. T's **goal reach** is the share of W-qualifying sessions
   where `Γ` is not empty and T returns a route ending in it.
7. *Gate (hypothesis).* All of these must hold:
   - at least 30 W-qualifying sessions with a non-empty U. With fewer, W is "not evaluable";
   - T's goal reach is at least 0.20;
   - the paired per-session F1 difference T − N has a mean of at least 0.10, and the lower bound of its paired
     bootstrap 95% interval (10,000 resamples) is above 0;
   - the same holds for T − B.
8. *Also reported:* the regime (`query-to-document`); how often `Γ` was empty; `θ_min` at p10, p50 and p90; the mean
   size of `Γ`; how often `g` was in `Γ`; how often T answered `at_goal`; how often the entries met `{s} ∪ U`; the
   mean hops of T's routes; and the embedder check's median cosine.
9. *Diagnostic, never gating.* The same steps with the stored document vectors, `c = v(s)` and `q = v(w)`, for
   sessions where both exist (the others are counted as `no_stored_vector`). The report gives its goal reach, F1
   means, `Γ`-empty rate and `θ_min` spread beside W's, labelled `document-to-document`. It shows how far the regimes
   differ. It is not evidence for `r` (6.3), and it runs even when W is not evaluable.

Why N: the vision's premise is "If the agent knew which memory held the answer, it would recall it." The trails earn
their place only if a route finds the session's pieces better than recalling the goal does, at the same cost. N,
nearest to the goal over T's nodes, stands in for that recall inside the same graph. Why
B: T must beat a route that ignores what agents did. S is not needed here, because the route gate already tests
order against S.

`w` is a hindsight summary: the session wrote it after it had found its pieces. That helps N and T alike, since both
use the same `q`, so the T − N comparison stays fair. But it is an easier goal than a real agent's words before the
work, so W's goal reach and F1 are likely higher than the tools will see in use.

**9. What a pass enables.** Rio Grande's call.

- A pass of the route gate (step 6) makes the case for `[category_evolution] trails`, the observer pass, on that
  store, as revision 3 said.
- The tools need both: the route gate and the goal gate pass on that store, or on an imprint of it.
- A pass licenses only the lane it evaluated (`--lane`), and an imprint may hold only one lane. So it makes the case
  for listing that lane in `[trails] lanes` (6.6, R16), and no other. Rio Grande's call.
- Neither gate tests `trail_next`. Only the reported next hit (step 5) does, and it gates nothing. Turning the tools
  on covers `trail_next` on the strength of that report alone. Rio Grande's call.
- Nothing here turns anything on. The store's owner decides, and for Andy's stores that is Andy.

**10. At the limits.** The run on an imprint is bounded by the imprint's calibration limits: a detached user unit
with `-p MemoryMax=4G -p MemorySwapMax=0 -p RuntimeMaxSec=1800`, so 4 GB and 30 minutes (imprint spec sections 10 and
12, its D29). The use's unit also passes `-p TimeoutStopSec=60`, so it is killed within 60 s of that limit (imprint
spec section 12, from its revision 5). The worst case, per qualifying session, is:

- 12 A* searches for the route gate: T, B, and the 10 shuffles of S;
- 2 for W (T and B) and 2 for its stored-vector diagnostic (step 8.9);
- each search up to 10,000 expansions, so up to 160,000 expansions per session;
- 11 forward lookups for the next hit, in T and in each of the 10 shuffles. A lookup expands nothing. It reads at
  most 3 stations × 256 trails of at most 512 touches;
- one embedding batch of two texts, for W.

On top of that come the 32 embeddings of the embedder check and 4 × 10,000 bootstrap resamples. `trails.py` takes
`--deadline SECONDS` (the use passes 1,740, which is 29 minutes) and checks it between sessions. When it passes, the
report says `"not evaluable: limit"` for both gates, and never a pass. So a report that decides a gate never depends
on the machine's speed. A run killed by the memory cap or the use's 30-minute limit writes no report, and the use
records it as "not evaluable: limit" (I2). Rio Grande's call. The Pi measurement (section 12) records expansions per
second, so the worst case can be set against the limit before the first real run.

## 8. Built for the county's lighthouses

Nothing crosses a store boundary in this step. These rules keep the next steps from needing rework.

Revision 3's first rule here was "Only the work lane can ever leave." Revision 4 replaces it with per-audience
permissions from the permissions spec (change C1). Andy: "I may share my medical history with the public health
office but not the parks and rec." His medical history is personal, and he shares it on purpose with one office, so
a lane can't be the rule.

- **Roads leave by permission, not by lane.** A road, detour or trail leaves its store only for an audience the
  permissions spec allows. Using a road as an edge is the `route` action on object kind `road`, named
  `road:<instance_id>/<cell id>` (permissions spec sections 4.1, 5.2 and 6.4). `route` needs `recall` on every
  memory the road names, so both endpoints must already be recallable by that audience. The `route` record is the
  separate opt-in revision 3 required: sharing a memory is still not consent to sharing routes. The decision is the
  meet of every required layer, and deny wins (permissions spec sections 6.3 and 6.5). An agent can share only inside
  the envelope of a grant, never past what a person signed (its section 7, and its L4).
- **One `route` use per road.** Each road a cross-store answer walks is one `route` use, with its own decision and
  receipt, naming the road's two endpoints (permissions spec 6.4, "One use per edge"). A route of at most 64 stops
  (6.5) walks at most 63 edges, so every decision fits that spec's bound of 32 memories per road or trail. A trail
  names its touches, so a trail of more than 32 touches can't be used as one edge across a boundary (`BOUND`). Trails
  cross a boundary through the roads they support, which is also the published form below.
- **Summaries across a boundary need `read` and `inject_context`.** A stop's summary is up to 160 bytes of the
  memory's content (6.5). `route` needs `recall` on the memories a road names, and `read` and `inject_context` on
  every memory whose content the answer shows (permissions spec section 6.4). So a stop from another store shows its
  summary only when both are allowed on that memory. Otherwise the stop names the id alone, and the use needs only
  `recall` there.
- **A road is about the people its endpoints are about, and about its store's owner.** The permissions spec's P24
  gives a derived object the union of its sources' subjects plus its store's owner. That is the vision's "Count its
  own trails as the person's": an agent's sessions are about the person it worked for, so sharing them is that
  person's decision.
- **Lanes stay inside.** Lanes still partition trails, roads and detours within a store, and every reader still
  filters by the current lane (section 4). A permission may name a lane, and the permissions spec reads lanes so that
  a re-lane never widens what is allowed (its section 5.3).
- **Minimum published support of 3.** It stays in this spec (permissions spec section 6.4 leaves it here). Support,
  span and direction are new metadata about how the owner worked. They are not in any shared memory.
- **Where sharing lives.** `shared_memories` rows live in the published house (`sharing.py` writes them to
  `published_storage`, `sharing.py:167-172`), not in the source `graph.db` that the trail pass reads. A trail
  endpoint matches its placement by (`source_instance_id`, `source_id`) once the permissions spec's migration 029
  fills that column (its section 12.1), and until then by (`source_instance`, `source_id`, `audience`). The
  published copy has a different `memory_id` (`sharing.py:143-147`). A placement is not a permission (permissions
  spec section 2).
- **Published form (for the later spec):**
  - each endpoint's `content_digest`, so two lighthouses holding the same shared memory recognize
    the same endpoint, plus its vector (same embedding model);
  - support binned as 3–5 or 6+, and the span rounded to days;
  - the store's `instance_id` and `forked_from_instance_id`.

  Session ids, touch times and context ids never leave.
- **Forks and imprints are not independent.** `cli.py fork` copies every session (`cli.py:38-49`), so a fork and its
  parent derive the same roads. Published support may count only sessions whose first touch comes after the store's
  fork. `stamp_fork` records no fork time in the store (`store_identity.py:143-160`), but `instances.json` already
  records `forked_at` (`federation.py:127-142`), and the publication spec can take it from there. An imprint gets a
  new `instance_id` with `forked_from_instance_id` set to its source. Two stores are independent only when the imprint
  spec's `independent` is true: their lineages don't meet and both ancestries are complete. `unknown` never counts,
  and siblings forked from one genome are never independent (imprint spec section 11). An imprint has no sessions
  after its creation, so it adds no support. Rail agreement must not count a store and its fork, or a store and its
  imprint, as two lighthouses.
- **Detours are publishable** only when every road on both sides is allowed `route` for that audience.
- **Receipts.** Each road used across a store boundary writes one receipt (permissions spec section 9.1). The
  answer's source (6.5) then carries that receipt and the cited records in place of `"own store"`.
- **Worked example.** Andy's record R1 lets public health recall, read and inject his medical-history collection
  (permissions spec section 13). Suppose he also says yes to R2: allow, in `place:home/andy`, audience
  `place:la-county/public-health`, object kind `road`, stores `[his store's instance_id]`, every other object
  dimension `"*"`, action `route`, purpose `care-coordination`, ending with R1. A road m1 → m2 between two memories of
  the collection, with published support of at least 3, then has Andy's yes for public health: R2 allows `route` on
  the road, and R1 allows `recall` on m1 and m2. Public health's agents can route over it in the later publication
  step only once public health's own rules also allow `route`. In the permissions spec's example they don't: its
  records H1 and L1 list only recall, read and inject_context, and a place may refuse what a person allowed (its
  section 7.5). A road through m3 ("Jenn drove me to the clinic") also needs Jenn's yes, because the road is about
  Jenn too. Parks and Recreation can route over none of them: neither record reaches parks-and-rec, and no agent can
  widen them.

## 9. Later steps (separate specs, in order)

1. **Compiled roads.** Proxy activation, an epoch for observer-created stores, road-before-detour
   commit order, and how the compiler walks memory → road → memory.
2. **Road publication.** A Lighthouse artifact kind for published roads, decided by the permissions spec's `route`
   action, with its receipts, the minimum support of 3 and fork time, built on the local-city daemon and receiver.
3. **Rail by agreement.** Run the lighthouse gluing per road instead of per topic. A road carried by
   at least two independently governed lighthouses whose `independent` is true (imprint spec section 11), with low
   residual under topic-scoped trust, is rail. Support from a genome-synced episode whose `origin_instance_id` is in
   the other lighthouse's lineage is a copy, not agreement (the same section). A high-residual road is an obstruction, reported
   and never routed over. Triangles of lighthouses give H¹ for the obstructions that only show up around a cycle.
   Agreement needs lighthouses to hold copies of roads. The permissions spec's `imprint` action ("Keeps a copy as
   part of another store", its section 6.4) may be what that needs, rather than `route`. The rail spec decides.
4. **Rail routing.** A* across lighthouses over rail and local roads, with the same angle heuristic and 6.3's goal
   sets. The tools of 6.6 extend to remote roads: each remote stop carries its own source, with its cited records
   and receipt (6.5). Each remote road walked is one `route` use (section 8). A remote stop shows its summary only
   when `read` and `inject_context` are allowed on that memory, and otherwise names the id alone (section 8). Suggested touches (section 4) already keep the system from confirming
   its own advice.
5. **Non-identity restriction maps.** County systems that use other embedding models or schemas
   need learned or declared translations (the lighthouse sheaf spec's "AOC vs DOP" case).
6. **Governance.** Each county station admits its own agents, and law there is signed by that
   institution's people. A connection to city data needs its own agreement. None of that is
   Superyak's to assume.
7. **Tools over an imprint.** Once the imprint spec serves imprints through the lighthouse receiver (its section 17,
   step 1), the tools can route over an imprint under `route` decisions and receipts.

## 10. Calibration hypotheses (provisional constants)

| Constant | Value | Purpose |
|---|---|---|
| Closed-session idle time | 1 hour before `as_of` | when a trail is built |
| Sessions per pass / per barrier batch | 64 / 8 | bounds startup work and tool-call waits |
| Pairs scanned per pass | the 16,384 with the newest rows | bounds the digest scan (C3) |
| Road / detour proposals per pass | 64 / 32 | bounds startup work (not the commit budget) |
| Touches per trail | 512 | bounds event size |
| Road support | 2 sessions | eligibility; the gain test never binds |
| Persistence span | 604,800 s unit, 60,480 s minimum | about 16.8 hours between sessions |
| Detour saving | > 0.25 of the longer route's hops | eligibility |
| Detour route length | 8 steps | bounds search and member count |
| Road-index threshold | 10,000 trail events | when the index becomes required |
| A* expansions / route wall time | 10,000 / 500 ms | bounds; the evaluation uses expansions only |
| Baseline neighbors | 8 | graph B |
| Route gate | last 20% held out, ≥ 30 qualifying, reach ≥ 0.20, ΔF1 ≥ 0.10 against B and S | gate validity |
| Entry stations | 6: given ids first, at most 2 from words, the rest near | 6.2 |
| Word anchors | 8 per context, 3 to 128 characters, 64 hits per anchor per table | 6.2 |
| Context and goal text | 4,000 characters | bounds the embedding call |
| Entry cost | 0 given; 2·θ(c, e); 2π without a vector | 6.2 |
| Goal band δ / ceiling r_max | 0.10 rad / arccos 0.60 ≈ 0.9273 rad | 6.3; r_max also bounds near entries |
| Forward lookup | 3 stations; 2 next and 2 ends each; 256 newest sessions per station | 6.4 |
| Route length | 64 stops; past that, `truncated` | 6.5, 6.6 |
| Stops shown | 12, as the first 6 and last 6 of a longer route | 6.5 |
| Summary | 160 bytes of compact JSON | 6.5 |
| Answer size | 6,000 bytes of compact JSON (1,500 by `estimate_tokens`); measured against a real tokenizer | 6.5 |
| Memory ids per call | 6 | 6.6 |
| Rows rechecked per answer | 70: 64 route nodes and 6 entries | 6.6 |
| Receipt short id | `#` and 8 hex characters | 6.6 |
| Tool graph | 4,096 newest closed sessions per lane; 20,000 nodes and 262,144 steps, split equally among the listed lanes | 6.6 |
| Tool graph memory | 256 MB per server process, a target that the Pi measurement checks; the build enforces only the counts above | 6.6 |
| Goal gate (W) | ≥ 30 qualifying, goal reach ≥ 0.20, ΔF1 ≥ 0.10 against N and B; N takes 4 when T names nothing outside the entries | section 7, step 8 |
| Embedder check | median cosine ≥ 0.99 over the 32 earliest episodes with vectors in the lane | section 7, step 8.2 |
| Evaluation deadline | 1,740 s inside the use's 30-minute limit | section 7, step 10 |
| Minimum published support | 3 | later publication |

**The Raspberry Pi budget, per pass.** Vision principle 4: "SQLite, Python with numpy, no GPU, bounded passes." No
pass needs a GPU. Two things embed text. A tool call embeds one batch of at most two texts (context and goal),
through the server's existing provider on the agent's machine. The evaluation embeds two texts per W-qualifying
session, plus 32 for its check, on the Pi (section 7, step 8.2).

| Pass | Where it runs | What it reads | Bound | Memory | Needs |
|---|---|---|---|---|---|
| Observer pass (5) | startup thread | `graph.db` read-only; `categories_v2.db` | 16,384 pairs scanned; 64 sessions written, barrier per 8; 64 roads and 32 detours, barrier per 16; 512 touches per trail | digests and current events; the road index past 10,000 events | Python, `sqlite3`; no vectors |
| Tool graph build (6.6) | last maintenance step | `graph.db` read-only; the permissions ledger's `stores` row, read-only, once (6.5) | 4,096 sessions per lane; 20,000 nodes; 262,144 steps; shutdown checked per 64 sessions | vectors as float32, 20,000 × 768 × 4 B ≈ 61 MB; step angles ≈ 2 MB; a target of 256 MB per server process, so k × 256 MB for k sessions, checked by the Pi measurement, while the build enforces the counts (6.6) | Python, numpy, `sqlite3` with sqlite-vec |
| A tool call (6.2–6.6) | MCP request, under the barrier | the tool graph; at most 16 FTS lookups of 64 rows; at most 70 rows rechecked | one embedding batch of ≤ 2 texts; one angle pass over ≤ 20,000 nodes in blocks of 4,096 for `h` and `θ(c, ·)`; step angles precomputed; A* ≤ 10,000 expansions or 500 ms; one row written | a 4,096-row float64 block, about 25 MB | numpy |
| CLI route, `--route-goal`, `--next` (6.1–6.4) | offline, on a copy | the copy, read-only | as a tool call, over the CLI's own derivation | as the tool graph | Python, numpy, sqlite-vec |
| Evaluation (7) | the Pi, through the imprint's use | `imprint.db`, immutable | T ≤ 20,000 nodes, or "not evaluable: too large"; B's neighbors in blocks of 1,024 rows; S built one shuffle at a time; per qualifying session at most 16 A* searches of 10,000 expansions, 11 forward lookups and one embedding batch of 2 texts; 32 check embeddings; 4 × 10,000 bootstrap resamples; a 1,740 s deadline, past which both gates are "not evaluable: limit" (section 7, step 10) | a detached user unit with `MemoryMax=4G`, `MemorySwapMax=0` and `RuntimeMaxSec=1800`, as the imprint's calibration runs (imprint spec sections 10 and 12); an in-process model counts inside the cap, the shared embedder service doesn't | Python, numpy, sqlite-vec; the store's embedding model, through the shared embedder service (its socket passed to the unit from `runtime.json`) or in process from the local cache only (R19, I3). Never the network. Without it, W is "not evaluable: no embedder" and the route gate still runs |

**The newest-rows ranking.** The observer pass (C3) and the tool graph build both rank sessions by their newest row
(section 4). Each time, that reads every `memory_log` row of event type `recall` or `route_shown`, which
`idx_memory_log_event_type` selects (`migrations/002_v3_layers.sql:62`), with one `json_extract(context,
'$.session_id')` per row, since no index covers it. It also reads every episode with a session id, and
`episodes.session_id` has no index either (`migrations/001_initial.sql:46-52`). So both passes cost time in
proportion to the whole log, not to the bound. The builder measures this on the Pi at the bounds (section 12). If it
is too slow, the road index of section 5 is where a per-session newest row belongs.

Time is a calibration hypothesis too: at most 20 s for the tool graph build and 1 s for a tool call at the bounds on
a Raspberry Pi 5, **not counting embedding**. Embedding up to 2 × 4,000 characters on the Pi's CPU is measured
separately and is likely the largest cost of a call. A recall already pays one such embedding (`server.py:2186`).
The builder measures all of them on the Pi (section 12).

## 11. Components

| Component | Responsibility |
|---|---|
| `trails.py` | Pure functions: touches, suggested touches, trails, revisit trails, steps, support, span, detour search, Kahan angles, anchors, entry stations from vectors, words hits and ids, the A* of 6.1 and 6.3, forward lookup, the short-answer builder (it takes summaries through a callback and the receipt id as an argument, so it stays pure), and both gates. Read-only CLI: `python trails.py /path/to/copy-of-graph.db [--categories /path/to/copy-of-categories_v2.db] [--lane work] [--as-of T] [--route A B] [--route-goal A G] [--next A] [--evaluate --seed N] [--imprint-use USE_ID] [--deadline SECONDS] [--json]`. `--route-goal A G` routes from A to the goal set of G's stored vector, and `--next A` runs the forward lookup from A; both print ids and counts only. It opens each database with `file:…?mode=ro` and `query_only`, loads sqlite-vec as `paths.connect_ro` does (`paths.py:397-409`), and reports `total_changes` (always 0), like `paths.py`. It runs the imprint check of section 7 on a file whose `meta.instance_id_origin` is `imprint`: the directory name equal to `meta.instance_id`, the allow file only at `<root>/<id>.state/uses/<use id>.allow.json`, a refusal when the tombstone `<root>/tombstones/<id>.json` exists or the state directory is gone, the allow file's `valid_until`, a refusal when the use's directory already holds `report.json` or `result.json`, a refusal without an explicit `--lane`, and the same checks again at the end of the run, discarding the report and exiting with status 3, `allow changed`, on a failure. With a valid one, the file opens with `mode=ro&immutable=1`, as `store_reader.connect(path, immutable=True)` does (`store_reader.py:43-54`). `--evaluate` embeds W's texts through `embeddings.create_embedding_provider(local_files_only=True)` (`embeddings.py:200-207`), so it never downloads a model (section 7, step 8.2), and its report names the lane and the provider. |
| `embeddings.py` | A `local_files_only: bool = False` keyword on `NomicEmbedProvider`, passed to fastembed's `TextEmbedding` (`embeddings.py:78-80`), and on `create_embedding_provider`, which passes it to the in-process provider only, since the shared client loads no model files (`embeddings.py:200-207`). Servers and the embedder service keep today's default. |
| `category_evolution.py` | `CategoryObserver.observe_trails(graph_conn, as_of)`: trail events with suggested touches, endpoint proxies, road and detour proposals, inside the existing quota and fail-closed rules, and the 16,384-pair scan. |
| `server.py` | Calls `observe_trails` from the startup maintenance thread before `prune` when `trails` is on, taking the barrier per batch. Builds the tool graph, for the listed lanes only, as the last maintenance step when the tools are registered, with its connection registered through `_register_server_cleanup` and a shutdown check per 64 sessions (6.6). Reads `stores.owner` from the permissions ledger read-only, once per build (6.5). Registers `trail_locate`, `trail_route` and `trail_next` in `_initialize_pre_serving` only when `[trails] tools` is exactly `true`. The tools refuse lanes not in `[trails] lanes`, and do the embedding, anchors and FTS of 6.2, the output-time check, and the receipt row. Holds the per-call counters and passes `trails_reporter` to the `Reflector`. A failure goes through `record_error` and never blocks startup or recall. |
| `storage.py` | `search_fts_ids(table, phrase, limit)`: one anchor phrase in `episode_fts` or `semantic_fts`, at most `limit` ids. Recall's own FTS calls stay as they are. |
| `config.py` | `[category_evolution] trails = false`, and a new `[trails]` section with `tools = false` and `lanes = ["work"]`, parsed fail-closed (6.6). |
| `reflection.py` | The `trails` counts block under `category_evolution`, and `reflect(focus="trails")` for the tools, through a new `trails_reporter` callable beside `category_reporter`. |
| `tests/test_trails.py`, `tests/test_trail_tools.py` and observer tests | Section 12. |
| `engram/CLAUDE.md` | A "Trails" paragraph under Architecture, a row in Key Files, and rows for the three tools under MCP Tools, marked off by default. |

**Interfaces with the parallel specs.** These are for Rio Grande to reconcile, not for Andy. The interface pass
(`docs/superpowers/reviews/2026-10-25-city-rail-interfaces.md`) settled I1–I4, as the items below say. The re-check
of revision 5 added I5 and I6 and extended I2 and I3. I5 is applied in the imprint spec's revision 3, and I2's and
I3's new parts and I6 in its revision 4. Revision 7 checked each against what that spec provides (as of its
revision 5), and marks them provided below. All six are settled: five provided and I4 declined.

- **Permissions spec.** This spec uses its object kinds `road` and `trail` and their names (its sections 4.1 and
  5.2), the `route`, `inject_context` and `imprint` actions and their `need` (6.4), L4, P24, its annotation's
  `laid_by` for roads (11), which 6.5 fills, and its non-goal for a store's own use (14), which 6.5 cites as
  `"own store"`. Step 1 reads one thing from it: `stores.owner` in the ledger, read-only, once per build (its 5.5),
  for `laid_by`. Its annotation now shows a receipt as `#` and 8 hex, as this spec's receipts do (its 4.1; 6.6 here).
  Its records, grants and proposals keep 4 hex for display, with full ids or unique prefixes in commands. Its `route`
  decision is per road or trail, at most 32 memories each (its 6.4), which section 8 fits.
- **Imprint spec.** This spec uses its `route` action and `trail-evaluation` purpose (its section 5.3 and D10), its
  `trail-evaluation` use (12), what its filter keeps (6.2), its calibration limits (10), and lineage (11). This spec
  asks it for six things:
  - **I1.** Its `memory_log` rule kept only `recall` rows. This spec asked it to keep the `route_shown` rows of kept
    sessions too, with `target_ids` cut to the shipped memories and `context` cut to
    `{receipt_id, session_id, tool, lane}`. Without them, a session the tools steered looks unsteered on the imprint,
    and its suggested touches count as support. *Applied* as the imprint spec's D35, 6.2 and check 11, with one
    change for privacy: a row whose cut list is empty is dropped, since it would say that everything a tool named
    stayed home (its D21). Section 7 records the cost: such a session looks unsteered, and no suggested touch is
    lost. The first evaluation is unaffected, because the tools wait for its pass.
  - **I2.** The use's allow file (its section 12) names the imprint's `instance_id`, the actions, the purpose and the
    effective end as `valid_until`, so `trails.py --imprint-use` can check them. *Applied, with this spec following
    the imprint spec's layout:* the allow file lives in the state directory, `<imprint id>.state/uses/<use id>.allow.json`,
    because the imprint directory is 0555 after admission, and withdrawal is the tombstone
    `tombstones/<imprint id>.json` (section 7, "The imprint check"). A shortening during a use rewrites the allow
    file atomically, since `trails.py` can't read receipts. When `trails.py` exits with status 3, `allow changed`, or
    writes no report, the use writes no `use-finished` receipt with a report's SHA-256. *Asked in revision 6,
    provided in the imprint spec's revision 4* (the re-check's RS3, RS4, RN8 and RN10; Rio Grande's call; its D41
    and section 12). Revision 7 checked each ask against that spec:
    - `use-finished` records the run's end as `withdrawn` only when the tombstone exists, `ended` when the effective
      end has passed, `allow changed` otherwise, and "not evaluable: limit" for a run a cap killed. *Provided*, as
      rules 2, 3, 5 and 6 of its "Finishing a use". Its rule 2 is narrower: `withdrawn` also needs a `withdrawn`
      receipt by the run's end. It adds `deleted`, for a station deletion, which writes a tombstone but is no
      withdrawal, and `failed`, for any other run with no report, so no run is recorded as a withdrawal or a limit
      it wasn't (section 7, check 7). Its revision 5 makes `failed` reachable for an error in `imprint.py use` too;
    - finishing a use retires its allow file. *Provided*: `station-imprint-sync` deletes
      `<id>.state/uses/<use id>.allow.json`, then writes `use-finished`, once. The use's unit runs the begin, the use
      and the sync, so every run has its `use-started` receipt, and one imprint runs one use at a time;
    - `imprint.py use` writes the report as `uses/<use id>/report.json`, only when `trails.py` exits 0, and the run's
      end as `uses/<use id>/result.json`. *Provided*, with the names section 7's check 5 reads. Its revision 5 writes
      `report.json` first;
    - a use id is a lowercase uuid4. *Provided*: `station-imprint-use-begin` makes one of 36 characters, which fits
      `[A-Za-z0-9-]{1,64}` (section 7, check 2), and `imprint.py use` refuses any other form;
    - the use always passes `--lane`, filling in the scope's one lane when `LANE` is left out (interface row 27).
      *Provided*: `imprint.py use` fills it in, and refuses a scope of two lanes without `LANE`. `trails.py` refuses
      an imprint without it.
  - **I3.** `trails.py` reads vectors through sqlite-vec, so the Pi's admission environment (its section 18) must
    include sqlite-vec, as its calibration already does. Measure W also needs the store's embedding model on the Pi
    (section 7, step 8.2): either the shared embedder service, reachable from the run, or `fastembed` and the model
    files in the admission environment, present before the run, with the model loaded inside the 4 GB cap. And the
    `trail-evaluation` use must cover reading memory text inside the run to embed it and find its anchors, with
    nothing but counts and rates leaving the run. *Applied:* the imprint spec's `Need(trail-evaluation)` names that
    `read` (its section 8), and its section 18 makes the embedder a gate before the first use. *Asked in revision 6,
    provided in the imprint spec's revision 4* (the re-check's RS2; Rio Grande's call; its D29 and sections 12, 16
    and 18): the use's detached unit gets `--setenv=ENGRAM_EMBEDDER_SOCKET=<path>` when the station's
    `~/.config/superyak/runtime.json` names an `embedder_socket`, and nothing otherwise (section 7, step 8.2). Its
    section 18's "The run never downloads a model" then rests on step 8.2's `local_files_only=True`. Without the
    service, the model files must be in the station user's `~/.kairos/models/fastembed` before the first use.
    Revision 7 checked each part. The unit's command carries the `--setenv` exactly then, read by
    `superyak-runtime`'s rule (`scripts/runtime.py:84-88`): no file, no key or `null` passes nothing, and a value that
    isn't an absolute path stops the use. Its revision 5 reads only the default path and adds a deploy gate that the
    user manager's environment, which the unit inherits, holds no `ENGRAM_` variable. Its section 18 rests "never
    downloads" on `local_files_only=True` and names the cache. It also keeps sqlite-vec in the admission environment
    (its section 18).
  - **I4. Declined by the interface pass, for privacy** (R17). The imprint spec keeps its whole-row rule, and section
    7, "The cost, chosen for privacy", records what that costs. The request, kept for the record: its whole-row rule
    for recall rows (6.2, D6, D7) removes far more than the memories left at home
    (section 7, "What an imprint changes"). This spec asked, as Rio Grande's call: keep a recall row whose outcome
    normalizes to `used` or `used: auto: cited` when at least one of its targets ships, with `target_ids` cut to the
    shipped targets in delivered order, and with `context.cut = true` when any non-instinct target stayed home. Other
    recall rows keep the whole-row rule, and so do citing operations, each of which acts on one memory id
    (`mark_core`, `instinct_feedback`, `dream_react`: `server.py:3037`, `:2729`, `:3620`). This is an exception to D6
    and D7, and check 11 must allow the `cut` key. It also touches D21 ("The manifest says nothing about what stayed
    home"): a cut row says one bit, that something it matched stayed home. That one bit is why it was declined: the
    imprint spec is the source of truth for what leaves a machine, and its rule is that nothing tells about what
    stayed home.
  - **I5. Session ids leave only with `route`** (the re-check's RMF2; R18; Rio Grande's call, its option (a)).
    Episodes carry `session_id`, and this spec makes sessions and wrote-touch trails from it alone (sections 2 and
    4). Revision 2 of the imprint spec copied `episodes` with every column except `rowid`, so every imprint carried
    the owner's wrote-touch trails, with or without `route`, and no record covered them. This spec asks the imprint
    spec to ship `episodes.session_id` as null without `route`, to cover the trails session ids make in
    `Need(admission)` with `route`, and to say so in the dry run and confirm view. *Applied in the imprint spec's
    revision 3*, written in parallel and read at the end of this pass: its D6, D7 and D10, 5.2 ("Log rows and session
    ids"), the 5.4 dry run and row key (`session_id as kept`), the 6.2 `episodes` row, section 8's R(I), "from its
    episodes' session ids and its log rows", check 12 (every `episodes.session_id` null without `route`), section
    10's example, and its log-rows test. It goes one step narrower: with `route`, a session still open at t₁ keeps
    no session id either. Its revision 4 goes one more: admission's calibration never measures session paths, with
    or without `route` (`no_paths`). So section 10's example counts "57 sessions" in the survey, there because it
    chose `route`, with "paths not measured at admission". Its log-rows test compares calibration's reports with and
    without `route` in the sections that must agree, and both `paths` sections say only "not measured at admission"
    (section 7, "At admission"). Option (b), keeping session ids under a record of their own, was not taken: by the
    interface pass's rule, privacy wins, and (a) lets less leave.
  - **I6. The imprint spec's recall-row test** (the re-check's RS1; for Rio Grande). Its section 16, "Recall rows",
    asserts "A trail derived from the package equals the trail derived from the source restricted to M". Section 7
    here says why that fails on any fixture with a mixed-lane recall. This spec is the source of truth for trails, so
    it asks the imprint spec to assert instead what holds, as a test can check it:
    - every touch derived from the package is a touch derived from the source, of the same memory, kind and time,
      in the same order within its recall, and suggested only if the source's is (section 4);
    - on every recall row the package keeps, section 4's "exactly one target" rule gives the source's answer;
    - and for what an imprint loses, a pointer to this spec's synthetic-imprint test (section 12).
    *Provided in the imprint spec's revision 4* (its section 16, "Recall rows"). Revision 7 checked it. Both
    assertions are there, on a fixture with `route` and a mixed-lane recall, and so is the pointer. That spec no
    longer asserts that the trails are equal. It adds one condition: derive both files' touches with one `as_of`,
    since the CLI's default `as_of` is each file's newest timestamp (section 4) and differs between them (section 7).
    Revision 7's check found that `as_of` must also be at or after the plan's end t₁. An earlier one could count a
    session closed in the package, whose later rows stayed home, and open in the source (section 4, "Sessions"), and
    then the package would have touches the source lacks. The imprint spec's revision 5 says so. With such an
    `as_of`, every session of the package is closed in the source too, and the package's rows are a subset of the
    source's, filtered the same way, so both assertions hold as section 4 derives touches.

## 12. Tests the builder must include

- **Determinism.** With `as_of` fixed, the same `graph.db` gives byte-identical trail payloads and
  the same road and detour ids. With the same tool graph, the same `c` and `q`, and the receipt id injected (the
  answer builder takes it as an argument, section 11), the tools' answers are byte-identical whenever no wall-time
  bound is hit. Every answer carries a fresh uuid4 receipt id, and the 500 ms bound depends on the machine, so the
  test pins the first and stays clear of the second.
- **Touch rules:**
  - a surfaced but unused result is not a touch;
  - per-target citation works from episodes and from `CITING_OPERATIONS` only (a `compress_commit`
    or `share` naming the id doesn't count);
  - a used recall with a single target counts, judged after instincts are removed;
  - an ambiguous multi-target recall is counted, not touched.
- **Co-citation (MF2).** A used recall that cites {A, B} orders them by delivered rank. The step is
  `co_cited`: it is a footpath, but it adds nothing to support or detour runs.
- **Suggested touches (R9).**
  - A session gets a `route_shown` row naming B, then recalls and uses B. Its steps into and out of B are
    `suggested`: footpaths that add no support and no detour run.
  - A `route_shown` row after the touch doesn't mark it, and one from another session doesn't either.
  - A wrote touch is never suggested.
  - A given id that an answer named, recalled and used later in the same session, is a suggested touch (R9).
  - Adding a `route_shown` row before a touch changes the trail's digest, and the next pass emits a new current event.
  - A `route_shown` row alone makes no session, but it moves a session's newest row (C4).
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
  - Evidence always contains the earliest and latest supporting sessions, even past the cap.
- **Event ids (RMF1).** Prune a touched episode, then revive it. The session's trail returns to an
  earlier digest, the pass appends a new event with a new id and no key error, and it becomes the
  current trail.
- **Session picking (S-a).** With more than 64 sessions pending, later passes reach the newer ones,
  and a re-laned old session is re-emitted.
- **Bounded scan (C3).** A store with more than 16,384 closed pairs scans the newest 16,384 and counts the rest as
  `pairs_not_scanned`. A re-laned memory in an unscanned old trail still never reaches a work route or answer.
- **Detours (MF4).** For overlapping routes X→A→B→Y and X→A→Y, the only candidate is the
  vertex-disjoint pair. No duplicate-member error, a 32-member limit that holds, and both sides
  passing `validate_path`.
- **Parity (MF6).** Run `observe_trails` on a synthetic store, then route in `graph.db` mode and in
  `--categories` mode. Road status and edges must agree, and the listed detour ids must equal the
  stored level-2 cell ids. Parity is required only when no per-pass cap was hit and no trail
  changed after the pass, and the test sets things up that way.
- **A\*.** Optimal on a hand-built graph. Consistency: no node is re-expanded at a lower cost,
  within an epsilon of 1e-9. Correct behavior with missing vectors. Hitting a bound returns
  `truncated`.
- **Angles (R4).** On 10,000 seeded random triples of unit vectors in 768 dimensions, including near-duplicates
  (`θ < 1e-6`) and near-antipodes, Kahan's θ is symmetric, 0 on identical vectors, within `[0, π]`, and satisfies the
  triangle inequality within 1e-12.
- **Goal sets (6.3).**
  - On 500 seeded random graphs of up to 40 nodes with unit vectors in 8 dimensions, some nodes without vectors,
    random supports, random entries with random entry costs, and random `q`: Claim 1 holds on every edge within
    1e-12, `h` is 0 on `Γ`, and A*'s cost equals a brute-force Dijkstra from a super-source to `Γ` within 1e-9.
  - The radius is `min(θ_min + 0.10, r_max)`, and `Γ` is empty exactly when `θ_min > r_max`.
  - A node without a vector is never in `Γ`. When the goal A* pops has no predecessor, the answer is `at_goal`, one
    stop and no steps, at cost `w(e)`. An empty `Γ` gives `no_goal` with the nearest node that has a vector, and with
    no node named when no node has a vector. An open list that runs empty gives `no_route`, and a bound gives
    `truncated`.
  - The planted cases of 6.3, each checked against the brute-force Dijkstra:
    - e1 ∈ `Γ` with `w(e1) = 1.0`; e2 ∉ `Γ` given, `w(e2) = 0`; an edge `e2 → t` costing 0.3 with `t ∈ Γ`. The
      answer is `goal`, route e2 → t, cost 0.3, not `at_goal`;
    - the re-check's case: the same e1 and e2, and an edge `e2 → e1` costing 0.3. The popped goal is the entry e1,
      but A* reached it through e2. The answer is `goal`, route e2 → e1, cost 0.3, not `at_goal`;
    - the tie: as before, but `w(e1) = 0.3`. The answer is `at_goal`, route e1, cost 0.3.
  - On the 500 random graphs, which include entries in `Γ` with random entry costs: the answer is `at_goal` exactly
    when the popped goal has no predecessor, an `at_goal` answer has one stop, and every answer's `cost` equals the
    popped goal's `g`, entry cost included.
- **Locate (6.2).** Given ids come first, in the caller's order; at most 2 stations come from words; near stations
  fill to 6 within `r_max`; ties break by id. Anchors, from these examples alone and from one text holding all of
  them: `engram/server.py` gives `engram/server.py` (and not `server.py`), `paths.py` gives `paths.py`,
  `sqlite3.OperationalError` gives `OperationalError`, `KeyError` gives `KeyError`, `_record_application` gives
  `_record_application`, `observeTrails` gives `observeTrails`; at most 8 are kept, each text once. A whole error
  message as one FTS query matches nothing that its anchors match. A personal memory is never a work station. With
  the embedder failing, `trail_locate` still returns given stations at cost 0 and word stations ordered by id at
  cost `2π`, no near stations, and `degraded: ["embedding"]`.
- **Forward lookup (6.4).** On synthetic trails: next items rank by sessions, then newest, then id; co-cited and
  suggested successors count 0 and come last; a write after the station appears as `kind: "wrote"`; ends exclude
  the station and count `ended_here`; a trail cut at 512 touches gives next items but no end, and counts in
  `ends_unknown`; median hops are right for odd and even counts; at most 256 sessions are read.
- **Short answers (6.5).** On adversarial content (quotes, backslashes, control characters, four-byte characters,
  CJK text, one-line contents of 100 KB) and a route of 64 stops, every answer is at most 6,000 bytes of compact
  JSON. Summaries are at most 160 bytes of compact JSON. A 20-stop route shows 6, `{"skipped": 8}` and 6. A route of
  65 stops answers `truncated`. Every named item has a `src` whose source holds `laid_by`, `allowed_by` and
  `receipt`, and the receipt's short form has 8 hex characters. No answer contains the context or goal text. The
  builder counts the largest answers' real tokens with the tokenizer of the model the agents use, and records the
  ratio to `estimate_tokens` in the plan's results (6.5).
- **`laid_by` (6.5).** With a ledger whose `stores` row names this store, `laid_by` is `"<owner> (<instance>)"`. With
  no ledger, or no row, it is `"this store (<instance>)"`. The ledger file's SHA-256 is unchanged.
- **Tools (6.6).**
  - With `[trails] tools` missing, `false`, `"true"` or `1`, no trail tool is registered, and `memory_log` gains no
    `route_shown` row.
  - With it `true`, each answer that names memories writes exactly one `route_shown` row listing every id it named,
    with no text from the call. An answer naming nothing writes none.
  - Apart from that row, `graph.db` is unchanged: every other table's row count and every access count stay the
    same, and `operation_log` gains nothing. `categories_v2.db` is byte-identical. With `uninvited=0` and no active
    dream residue, recall answers are the same with the tools on and off.
  - The tool graph is built through a read-only connection, the barrier is held only for the swap, and before it is
    ready the tools answer "not ready".
  - Above 4,096 sessions, 20,000 nodes or 262,144 steps, the build keeps the newest and records `truncated`. With
    both lanes listed, each lane gets half the node and step bounds, and a lane with many sessions doesn't starve the
    other.
  - The vectors are held as float32, and every angle equals the one computed from a float64 copy.
  - Re-laning a route node to personal after the build: the tool drops it and answers again. A second failure
    answers `stale` and names nothing. The same holds for a node in the middle of a 20-stop route, one that the
    answer hides in `{"skipped": 8}`, and for a node pruned to cold storage after the build.
  - `[trails] lanes` missing gives `["work"]`. A call for `personal` then answers "lane not enabled: personal" and
    writes no receipt. A malformed value (`"work"`, `["work", "work"]`, `["other"]`, `1`) enables no lane and records
    `lanes_invalid`. `[]` records nothing invalid, builds nothing without error, and every call answers "lane not
    enabled: <lane>" and writes no receipt.
  - Shutting the server generation down during a build stops the build, and the build's connection is closed. A
    forked child quarantines the connection with the other resources.
  - `reflect(focus="trails")` reports the per-call counts, and `{"available": false}` when the tools are off.
  - Invalid lane, more than 6 ids, empty inputs, and an embedder failure each give the answer 6.6 states.
- **Evaluation (MF7).**
  - A synthetic store with planted ordered routes passes.
  - A synthetic store with popularity skew but no order fails the T − S comparison.
  - A synthetic store whose only structure is co-retrieval (RMF2) fails the T − S comparison.
  - With fewer than 30 qualifying sessions, the result is "not evaluable".
  - No training touch at or after the cutoff enters T.
  - Steered sessions qualify for neither gate, and suggested steps are in none of T, S and B.
- **Goal gate (W).**
  - A synthetic store whose sessions walk planted routes and end by writing a summary near their last memory passes.
  - A store where the goal words sit next to every piece the session used (so nearest to the goal finds them) fails
    T − N.
  - With fewer than 30 W-qualifying sessions, W is "not evaluable".
  - `w` is never a node of T or B, N's size matches T's route (4 when T names nothing outside the entries), and
    sessions with empty U are counted, not scored.
  - W embeds `content(s)` and `content(w)`, cut to 4,000 characters, with `search_query`, through the same function
    the tools call: a fake provider records exactly those texts and that prefix, and W's numbers change when the
    provider returns different query vectors while the stored vectors stay the same.
  - With no provider, W is "not evaluable: no embedder" and the route gate is still decided. With a provider whose
    vectors don't match the stored ones (median cosine below 0.99), W is "not evaluable: embedder mismatch".
  - Offline (R19). Without `ENGRAM_EMBEDDER_SOCKET` and with an empty model cache, `--evaluate` builds the provider
    with `local_files_only=True`, W is "not evaluable: no embedder", nothing is written to the cache directory, and
    the run opens no network socket (the test fails any non-Unix socket connect). With the variable naming a socket
    nobody serves, W is "not evaluable: no embedder" and no local model is loaded.
  - The use's unit command carries `--setenv=ENGRAM_EMBEDDER_SOCKET=<path>` exactly when the fixture's
    `runtime.json` names an `embedder_socket` (I3).
  - The stored-vector diagnostic is reported, labelled `document-to-document`, and changing it never changes W's
    verdict.
- **Synthetic imprint (MF2, R17, R18).** Build a synthetic source store whose sessions write episodes in both lanes,
  make recalls without a lane, each delivering memories of both lanes, and recalls with `lane="work"`; cite work
  memories from both; and prune one target to cold storage. Then build its work-lane imprint, with `route` in the
  terms, using the imprint spec's builder (imprints are built before trail step 1, the vision's "How the work runs",
  step 3):
  - the imprint's work trails lose the cited touches of shipped memories from every recall that matched a memory left
    at home or pruned to cold, and the test records how many, against the source's work trails. This is the cost that
    section 7 records;
  - the lane-filtered recalls whose targets all shipped keep their cited touches, and on every recall row the imprint
    kept, the "exactly one target" rule gives the source's answer;
  - no kept row carries a `cut` key, and a `route_shown` row whose targets all stayed home is absent;
  - the work episodes of sessions closed at t₁ keep their `session_id`, and the imprint's work trails hold their
    wrote touches, as the source's do;
  - built without `route` (R18, I5), the imprint holds no log rows and every episode's `session_id` is null. The
    derivation of section 4, called on it directly as a library function, finds no session and no trail, and
    `trails.py` refuses the imprint for want of an allow file that names `route`. The source's sessions that wrote two
    or more work episodes would each have given a trail without this rule, and the test counts them.
- **Report.** The same store, seed and lane, with the same embedder provider, give byte-identical report JSON and the
  same SHA-256, when no deadline is hit. The report names the evaluated lane and the provider, and two runs that
  differ only in `--lane` give different hashes.
- **Limits (section 7, step 10).** A run whose `--deadline` passes reports "not evaluable: limit" for both gates and
  no pass. A run killed by the memory cap writes no report.
- **Imprints (R13).** On a fixture laid out as the imprint spec lays out `~/.engram/imprints/`, `trails.py` refuses an
  imprint without `--imprint-use`; with a use id holding `/` or `..`; whose directory name isn't its
  `meta.instance_id`; with an allow file anywhere but `<root>/<id>.state/uses/<use id>.allow.json`, or one reached
  through a symlink; with an allow file for another imprint, another action, another purpose, or a `valid_until` that
  has passed; when the tombstone `<root>/tombstones/<id>.json` exists; when the state directory is gone; without an
  explicit `--lane`; and when `<root>/<id>.state/uses/<use id>/` already holds a `report.json` or a `result.json`.
  With a valid one, it opens the file immutable, and the file's SHA-256 is unchanged. If the test writes the
  tombstone, removes the allow file, rewrites it with an end now past, or rewrites it with a shorter end still ahead,
  while the run is going, the run prints no report and exits with status 3, `allow changed`, in all four cases.
- **Use ends (I2).** On the imprint spec's fixture of a use: a finished use's allow file is gone, and rerunning
  `trails.py --imprint-use <that id>` is refused with no report; a shortening during a run is recorded as
  `allow changed`, not `withdrawn`; a withdrawal during a run is recorded as `withdrawn`. These run when the imprint
  spec's use step exists, since that spec owns the receipts. Its section 16, "Use ends", tests the same, and its
  `deleted` and `failed` ends.
- **Read-only CLI.** Every database's SHA-256 is unchanged, and `total_changes` is 0.
- **Gate off.** First open the store once with the same flags (so first-open vector provisioning
  doesn't count). After startup, `categories_v2.db` must be byte-identical in each of these cases:
  - `trails = false` with `auto_commit = false`;
  - `enabled = false`;
  - `trails = true` with `auto_commit = true` (RMF3), on a store built by legacy replay. This case
    also records a skipped pass.
- **Barrier.** The pass releases the lifecycle barrier between batches.
- **Pi measurements.** On a Raspberry Pi 5, on a synthetic store at the tool graph's bounds: the build's time and
  peak memory, the peak checked against the 256 MB target (6.6), and within it the newest-rows ranking's time over a `memory_log` of realistic size; a tool call's time
  without embedding; the time to embed 2 × 4,000 characters on the Pi's CPU, through the shared service and in
  process; A* expansions per second; and an evaluation at 20,000 nodes under `MemoryMax=4G`, with its embedding
  included. The builder records them in the plan's results and compares them with section 10.

## 13. Left to the builder

- The road index's schema, within the section 5 rule.
- The design of the synthetic stores, as long as they plant known routes, noise and a popularity
  skew without order, and, for W, sessions that end by writing a summary.
- CLI output formatting.
- The tool graph's data structures, within 6.6's bounds.
- The anchor patterns' exact form, as long as section 12's examples still pass.
- The tool descriptions' wording, within the sense 6.6 gives.

## 14. Open for Andy

- **Which store to imprint first, and its owner's yes.** The first evaluation runs on an imprint whose owner agreed
  (section 7; imprint spec section 20). Engram stores aren't on the Pi (`~/.engram` is absent), and the first imprint
  creates one. The report holds only counts and rates, and it reaches no room unless the owner allows it (imprint
  spec section 12).
- **Memories that mention other people** (the imprint spec's section 20 asks it; the permissions spec's section 19
  lists it). The first evaluation reads the text of every memory the imprint holds, on the Pi, and reports only
  counts and rates. Until Andy answers, the imprint spec's default holds: no memory with a recorded co-subject ships,
  and the owner confirms the rest. This spec changes nothing about it.
- **His act after a pass, not a question now.** If both gates pass on an imprint of one of his stores, setting
  `[trails] tools = true` for that store, with the evaluated lane in `[trails] lanes`, is his decision as its owner.
  This spec turns nothing on.
- **The license** (vision principle 3). `trails.py` adds standard-library and numpy code to engram, which has no
  license yet.
