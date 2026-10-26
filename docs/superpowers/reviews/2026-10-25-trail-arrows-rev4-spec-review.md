# Trails spec revision 4: fresh reviewer verdict (station law section 3)

Spec: `engram/docs/superpowers/specs/2026-10-25-trail-arrows-design.md`, revision 4 (uncommitted, branch
`trail-arrows-spec`). Contract: `docs/city-rail-vision.md`. Reviewer: a fresh agent on the Pi that took no part in
writing revision 4 or the earlier revisions. Spec references are `§section` and spec line numbers. Code references are
relative to `engram/`.

## Review of 2026-10-25

VERDICT: APPROVE WITH CHANGES

Approval holds once MF1–MF3 are applied. Apply the S items in the same revision. A second fresh reviewer re-checks
the result, as the vision's "How the work runs" says.

### What I checked and found true

**Code claims.** Each one read at the cited lines:

- `_server_tool` wraps every tool in `_server_operation`, which holds `_server_lifecycle_lock` for the whole call
  (server.py:690-697, :653-684).
- `_initialize_pre_serving` runs `_init(..., defer_sleep_maintenance=True)`, then starts the maintenance thread.
  `mcp.run()` follows it (server.py:4023-4038).
- In the deferred pass, prune is step 2 (server.py:1172-1183), `persistence-score-refresh` is the last step
  (:1279-1283), and the report is saved at :1289-1290. So "after `persistence-score-refresh`, before the report is
  saved, after `prune`" is right.
- Recall embeds with `prefix="search_query"` (server.py:2186). `max_results` defaults to 20 (:2068). The lane check is
  at :2089-2090. Results carry full content (:2281-2286). Episode access counts go up at :2388-2391. The observer gate
  uses `is True` (:2650). `_apply_recall_bias` is at :1499. `_mutation_logged` is at :38-64. The instance falls back to
  `default` at :1976.
- `vec0_distance_to_similarity` is `1 − d²/2` (storage.py:23-28). `_sanitize_fts_query` quotes each token, and
  juxtaposed FTS5 strings are an AND (storage.py:64-74, used at :1062-1071). `open_read_only` uses `mode=ro`,
  `query_only` and loads sqlite-vec (storage.py:127-161). `add_log_entry` takes a caller-supplied id
  (storage.py:1656-1680). `count_session_log_events` ignores event types it doesn't know (storage.py:1765-1789).
- `reinforce_threshold = 0.70` (config.py:44). `suggest_edges` searches with a stored vector at threshold 0.7
  (graph.py:461). `proximity_suggestion` is a non-recall `memory_log` row (graph.py:502-512).
- `_unpack_embedding` reads little-endian float32 into float64 (paths.py:43-44). `connect_ro` loads sqlite-vec
  (paths.py:397-409). `estimate_tokens` is `(UTF-8 bytes + 3) // 4` (category_compile.py:195-197).
  `store_reader.connect(path, immutable=True)` adds `immutable=1` (store_reader.py:43-54).
- Fork copies by SQLite backup (cli.py:38-49). `stamp_fork` writes no time (store_identity.py:143-160).
  `instances.json` keeps `forked_at` (federation.py:127-142). The published copy gets a new uuid4 (sharing.py:143-147),
  and the share row goes to `published_storage` (sharing.py:167-172). `reflect` dispatches focuses at
  reflection.py:732-775. `CITING_OPERATIONS` is at hooks/sleep.py:44.
- A `route_shown` row disturbs no existing reader. Every other `memory_log` reader filters by `event_type`, or by
  `$.recall_id`, which a receipt's context doesn't carry (`log_outcome`'s lookup, server.py:2672-2675). `introspect`'s
  recent activity will list `route_shown` rows (reflection.py:329-333). That is harmless.

**Parallel specs.** Every cited section exists and says what this spec says it does:

- Permissions spec: short ids (4.1), road and trail selectors with `"*"` dimensions (5.2), lanes read so a re-lane
  never widens (5.3), the `stores` table (5.5), required layers, `need` and the decision (6.3–6.5), grants (7), places
  refusing (7.5), receipts without content or query text (9.1), `laid_by` for roads (11), migration 029 (12.1), records
  H1 and L1 without `route` (13), and the non-goal quoted word for word (14).
- Imprint spec: D10, the terms (5.3), the table rules (6.2), the 4 GB and 30-minute calibration (10), lineage (11),
  the `trail-evaluation` use and the `use-finished` receipt with the report's SHA-256 (12), serving imprints (17, step
  1), sqlite-vec in the admission environment (18), and the open question of which store (20).

**Andy's words.** A1–A6, §1 and §6.2 quote the vision exactly.

**The mathematics is correct.**

- Kahan's form is exact for unit vectors: ‖â − b̂‖ = 2 sin(θ/2) and ‖â + b̂‖ = 2 cos(θ/2).
- Lemma 2 holds. Claim 1 holds in all three vector cases. Claim 2 follows by telescoping.
- Claim 3's reduced-cost argument is right: the start keys are w(e) + h(e). The super-source edges satisfy Claim 1 with
  h(source) = 0, and the goal-to-sink edges do too, since h = 0 on Γ.
- Γ is empty exactly when θ_min > r_max or no node has a vector. arccos 0.60 = 0.9273. A δ of 0.10 near θ = 0.8 is
  about 0.075 in cosine.
- The example answer is consistent: 0.5213 + 0.10 = 0.6213.
- I built a worst-case answer item. It came to 338 bytes, so trail_next's 15 items come to about 1,300 estimated
  tokens, as §6.5 says.

### Must-fix

**MF1. Measure W does not test goals given in words, so the goal gate doesn't test the tool it licenses.**
*Where:* §7 step 8.2–8.3 (lines 822-825), "What an imprint changes" (line 744), §6.3 "Why this r" (lines 543-548), R12,
and §10's evaluation row ("no embedder").
*Reason:*
- The tools embed the context and the goal as queries (`search_query`, the recall path, server.py:2186).
- W uses the stored document vectors `c = v(s)` and `q = v(w)` instead.
- r_max is justified by exactly this difference: "query-to-document cosines run lower" than document-to-document ones
  (lines 544-546). So in W, Γ is non-empty more often and goal reach runs higher than the tools would see.
- §6.3 says W's Γ-empty rate and θ_min spread are "the evidence a later revision would need" to set r. That evidence
  would come from the wrong regime.
- §7 step 9 makes W a condition for turning the tools on.

*Fix:* choose one (Rio Grande's call).
- **(a)** W embeds `content(s)` and `content(w)`, each cut to 4,000 characters, with `search_query`, through the same
  function the tools call. The imprint ships episodes whole (imprint spec 6.2), so the text is on the Pi.
  - The evaluation then needs the store's embedding model, checked against the store's own. It can use the shared
    embedder service or an in-process model inside the 4 GB cap.
  - Add that to I3 and to §10. Without an embedder, W is "not evaluable".
  - Keep the stored-vector run as a reported, non-gating diagnostic.
- **(b)** The tools embed goal and context with `search_document`, so the regime matches W. Then justify r_max again
  for document-to-document cosines.

Either way, name the regime in R3. Say in "Why N" that `w` is a hindsight summary, written after the session found its
pieces. It helps N and T alike, so the T − N comparison stays fair, but it is easier than a real agent's goal.

**MF2. The imprint's whole-row rule removes far more than "the memories left at home".**
*Where:* §7 "What an imprint changes" (lines 739-744), §11 "Interfaces".
*Reason:*
- A default recall has `lane=None` and `max_results=20` (server.py:2064-2073). The lane filter applies only when a lane
  is given (server.py:2332-2333), and the row is logged at :2381-2387. So a default recall's `target_ids` hold up to 20
  matches from both lanes.
- The imprint keeps a recall row only when every target ships (imprint spec 6.2, D7). Cold storage is never imprinted
  in step 1 (imprint spec 17, step 5).
- So a work-lane imprint drops nearly every default recall that matched even one personal memory. Any imprint drops
  every recall with a target since pruned to cold.
- Each dropped row takes with it the cited touches of memories that did ship. Revisit trails are cited touches only
  (§4), so roads, detours and both gates can thin out to "not evaluable" on the first imprint.
- The sentence "an imprint's trails are the source's trails without the memories left at home" is false.

*Fix:*
- Correct the sentence and state the scale.
- Add **I4** for Rio Grande to reconcile with the imprint spec. Choose one:
  - **(a)** Keep a used recall row with `target_ids` cut to the shipped targets, plus its original target count, so
    §4's "exactly one target" rule (S-d) still holds. This is an exception to imprint D6 and D7. The count is a fact
    about what stayed home (D21).
  - **(b)** Keep the rule, and have the source-side dry run show the owner, per lane, how many used recall rows and
    cited touches the imprint keeps against the source. Then the owner and Rio Grande know before anything ships
    whether the gates can be evaluated.
- Add a synthetic-imprint test that shows the effect.

**MF3. `at_goal` contradicts Claim 3 and the brute-force test.**
*Where:* §6.3 line 553 and §12 line 1072, against Claim 3 and §12 line 1070.
*Reason:* take entry e1 ∈ Γ found near the context, with w(e1) = 2θ(c, e1) = 1.0. Take a given entry e2, with w = 0, and
an edge e2 → t, where t ∈ Γ and the edge costs 0.3. A* returns e2 → t at cost 0.3, as Claim 3 and the Dijkstra test
require. But "an entry is already in Γ" says the answer is `at_goal`. Two required tests then disagree.
*Fix:* `at_goal` means the goal A* pops is an entry, so its g is its entry cost. Plant this case in the test.

### Should-fix

**S1. The output-time check misses route nodes hidden in `{"skipped": k}`.** *Where:* §6.6 lines 693-696, §6.5 line
629, anti-goal "Personal leakage" (lines 167-168). A route longer than 12 names only its first and last 6. Its middle is
never rechecked, so a node re-laned to personal or pruned after the build can sit inside a work route. That breaks the
anti-goal ("never appears in a … route"). It also shows a route the agent can't follow. *Fix:* recheck every node of
the computed route, plus every entry and every named node. Cap a route at a fixed number of nodes (for example 64);
past the cap, the answer is `truncated`. Replace the 24 in §6.6 and §10 with the new bound.

**S2. A gate pass should license the tools only for what was evaluated.** *Where:* §7 step 9 (line 856), the `lane`
argument (line 659). The gates run on one lane (`--lane`), on an imprint that may hold one lane. The tools answer both
lanes. *Fix:* a pass licenses the tools for the evaluated lane. Add `[trails] lanes` (default `["work"]`), or have the
tools refuse a lane the owner hasn't enabled. Rio Grande's call.

**S3. A changed approved decision is missing from the change table, and some attributions overreach.** *Where:* the
"Changes to approved decisions" table (lines 59-66) and A5 (line 39).
- Revision 3 said "The evaluation runs read-only on a copy of a real store" (commit `3539102`). Revision 4 runs it only
  on an imprint. Add this as C5, required by the task and by the vision's "How the work runs", step 3.
- C3's 16,384 and C4's rule are Rio Grande's calls, made to serve the vision. They are not required by it word for word.
- A5's decision, "only as an imprint", is Rio Grande's call built on Andy's words. Andy's quote doesn't say it.

**S4. The allow-file check is easy to get wrong by mistake.** *Where:* §11 `trails.py` row, §12 "Imprints", I2.
- `--imprint-use` accepts any path.
- `trails.py` doesn't check withdrawal (`withdrawn.json`) or a later `shortened` end (imprint spec 12, `exp_eff`).
- The file is unsigned, so any process running as the same user can write one.

*Fix:*
- Read the allow file only from `<imprint dir>/uses/<use id>.allow.json`.
- Refuse when `withdrawn.json` exists.
- Use the effective end.
- Check again when the run ends, and discard the report if the imprint was withdrawn during the run.
- State the known limit as permissions spec §14 does: this narrows mistakes, not malice.
- Say plainly that running `trails.py` on a plain copy of one's own store is the owner's own use (the permissions
  spec's non-goal). R13's "only" doesn't forbid it, and `trails.py` doesn't check it.

**S5. The 1,500-token bound is really a byte bound.** *Where:* §6.5 lines 625-637, R6, Goal 9, anti-goal "Context
flood". `estimate_tokens` counts 4 bytes per token (category_compile.py:195-197). A 36-character UUID and CJK text
tokenize at well under 4 bytes per token, so an answer of 1,500 estimated tokens can cost noticeably more real tokens.
That is exactly the context-window cost the traveler's view worries about. *Fix:* name the bound for what it is: "6,000
bytes of compact JSON, which `estimate_tokens` counts as 1,500". Then either lower it, or record a measured ratio
against a real tokenizer in the plan's results.

**S6. Remote summaries need `inject_context` (later steps).** *Where:* §9 step 4 (line 930), §8. A summary is up to 160
bytes of content. `route` needs only `recall` on the endpoints, and `recall` "returns ids and digests" (permissions
spec 6.4). So if the answer format carried over to remote roads unchanged, content would reach an agent's context
under `route` and `recall` alone. *Fix:* a remote step shows a summary only when `inject_context` is allowed on that
memory (`need`: recall, read, inject_context). Otherwise the step names the id alone.

**S7. A receipt can't rebuild the answer.** *Where:* §6.6 lines 707-709. `graph_digest` lets a reader rebuild the
graph. The answer also depends on `c` and `q`, which come from text the receipt deliberately doesn't hold, and on FTS
hits. The output-time check also edits the cached graph after the digest is taken. *Fix:* say the digest lets a reader
rebuild the graph and check every named id and step against it.

**S8. The required determinism test can't pass as written.** *Where:* §12 lines 1017-1019. Every answer carries a
uuid4 receipt id, and the 500 ms bound depends on the machine. *Fix:* answers are byte-identical apart from `receipt`
when no wall-time bound is hit, or the test injects the receipt id.

**S9. Gaps in the Raspberry Pi budget.** *Where:* §10 table (lines 974-983), §6.6.
- **(a) One graph per process.** Claude Code runs one engram server per session, and each builds its own graph, up to
  256 MB. engram/CLAUDE.md measures about 320 MB per server already. State the per-machine figure for k sessions.
  Consider float32 storage (about 61 MB), converted to float64 one 4,096-row block at a time.
- **(b) Edge angles.** Store each step's θ when the graph is built (262,144 × 8 B = 2 MB). Otherwise every A* expansion
  computes 768-dimensional dot products in Python, and the 500 ms bound will bind on a Pi.
- **(c) Embedding time.** `trail_route` embeds twice (context and goal), not once. Say whether the 1 s hypothesis
  includes embedding up to 2 × 4,000 characters on the Pi's CPU. That is likely the largest cost.
- **(d) The "newest rows" ranking.** It scans all of `memory_log` with a `json_extract` per row, plus all episodes, on
  every pass and every build. Say so, and measure it on the Pi.

**S10. Say what happens at the evaluation's limits.** *Where:* §10 evaluation row (line 980). In the worst case, each
qualifying session needs:
- T, 10 shuffles of S, and B for the route gate;
- T and B for W;
- forward lookups in T and in each of the 10 shuffles;

each search running up to 10,000 expansions. *Fix:* give that worst-case count. Say that a run stopped by the 30-minute
limit or the 4 GB cap reports "not evaluable: limit" and never a pass.

**S11. `_record_application` fails the anchor patterns.** *Where:* §6.2 line 452, §12 line 1076. I tested this in
Python. The snake_case pattern can't match a name with a leading underscore, because `_` is a word character, so the
`\b` before the first letter fails. No other pattern matches it, so a required test fails. *Fix:* use
`\b_*[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b`, or drop the example. Also say how overlapping matches count:
`engram/server.py` yields both `engram/server.py` and `server.py`.

### Nits

- **N1 (§2 against §6.5).** "Step" means two things: a directed pair in §2, and an item of a route list (a memory) in
  §6.5. "At most 12 steps" and "a 20-step route shows 6, `{"skipped": 8}` and 6" count memories. Call them stops or
  items.
- **N2 (§6.6 lines 665-666).** The degraded mode drops words, but the FTS search needs no embedder, and §6.2 already
  prices words entries at 2π when `c` is undefined. Keep words.
- **N3 (§6.6 line 705).** Short receipt ids of 4 hex characters collide: by the birthday bound, about 300 receipts give
  even odds of a repeat. The answer is the agent's only handle on its receipt. Show 8 hex characters, or the full id.
- **N4 (§6.4 "Ends").** The last touch of a trail cut at 512 touches isn't where the session ended. Exclude such trails
  from ends, or flag them.
- **N5 (§4 "Suggested touches").** Given ids are named in receipts, so if the agent recalls one again later in the
  session, that touch counts as suggested, even though the agent brought it. That is conservative. Say so, or leave
  given ids out of the marking.
- **N6 (§6.6 line 688).** For the bound shared by both lanes, say which lane builds first, or give each lane its own
  bound, so one lane can't starve the other.
- **N7 (§6.5 `laid_by`).** `laid_by` needs a read-only look at the permissions ledger (`stores.owner`). Add it to §11 and
  to the Pi table, done once per build.
- **N8 (§6.6 "Diagnostics").** `reflect(focus="trails")` needs counters held in server memory, but the Reflector holds
  only storage. Say where the counts live.
- **N9 (I1).** I1 also needs changes in two places of the imprint spec:
  - verification check 11, which allows only recall rows with `context` keys within {`recall_id`, `session_id`};
  - D6, so the list can be cut.

  Keep `route_shown` rows whose cut list is empty too, since being steered is a fact about the session.
- **N10 (§6.6 "The tool graph").** Register the build's read-only connection and thread with the cleanup coordinator
  (`_register_server_cleanup`). Then shutdown joins it and a forked child quarantines it (server.py:252-256, :375-379).
  The build should stop when the server generation shuts down.
- **N11 (§8 line 873).** "An agent widens only inside the envelope of a grant" reads against the vision's "they never
  widen". Say instead: an agent can share only inside a grant's envelope, never past what a person signed (permissions
  spec L4).
- **N12 (§6.3).** `no_route` says "within the bounds", but `truncated` is the bound case. Define `no_route` as the
  search ending with no goal reached.
- **N13 (§6.5).** Say whether the answer's `cost` includes the entry cost. The example's 1.9381 implies it does.
- **N14 (§7 step 8.5).** N is labelled "recall alone", but it is "nearest to q over T's nodes", with no FTS, no recency
  and no rest of the store. Call it "nearest to the goal" in the report.
- **N15 (§9 step 3).** Rail agreement needs lighthouses to hold copies of roads. The permissions spec's `imprint` action
  ("Keeps a copy as part of another store") may be what that needs, rather than `route`. Leave a pointer for the later
  spec.
- **N16 (§7 step 9).** Neither gate tests `trail_next`. Only the reported next hit does. Say that turning the tools on
  covers `trail_next` on that report alone (Rio Grande's call).

### Against the vision, privacy, the Pi, and planning

- **Vision.** Every item of the traveler's view is covered:
  - locate (§6.2);
  - a goal in words, with the stated h, the proof and the vectorless case (§6.3);
  - forward lookup (§6.4);
  - short answers with who laid each step, the rule and the receipt (§6.5);
  - three read-only tools (§6.6);
  - audiences in place of lanes (§8);
  - the evaluation on an imprint (§7);
  - a Pi row for every pass (§10).

  MF1 is the one place where the measure doesn't test what the vision asks.
- **Privacy.** In step 1, nothing about a person leaves the store. The tools serve only the store's own agent: the
  permissions spec's non-goal, quoted exactly. Receipts hold ids and no text. An agent can't widen a permission,
  because step 1 checks none and later steps go through the permissions engine (its L4). The worked example in §8 is
  right: neither H1 nor L1 allows `route`, and a road through m3 needs Jenn's yes. The remaining risks are S1, S2, S4
  and S6. MF2 loses data; it leaks nothing.
- **Pi.** SQLite, numpy, no GPU, and every pass has a bound. S9 and S10 close the gaps that would surprise a Pi build.
- **Planning.** After MF1–MF3, a builder can plan without asking Andy. "Open for Andy" holds the right three items:
  which store to imprint first and its owner's yes; his act after a pass; and the license. MF1(a) and I4 are for Rio
  Grande, not Andy.

## Response (revision 5)

Reviser: Rio Grande's spec reviser, 2026-10-25. Revision 5 is in the same file, uncommitted on `trail-arrows-spec`.
Every code claim the changes rest on was read again at the cited lines. Where the code and this review differed, the
spec follows the code (noted below). Every new decision is marked "Rio Grande's call" in the spec.

### Must-fix

- **MF1. Applied, option (a).** Section 7 step 8.2: W embeds `content(s)` and `content(w)`, each cut to 4,000
  characters, in one batch with `search_query`, through the same function the tools call. The run needs the store's
  embedding model, through `embeddings.create_embedding_provider()` (`embeddings.py:200-207`): the shared embedder
  service, outside the 4 GB cap, or the in-process model, inside it. The store records no model name (nothing in
  `meta` or the migrations does), so the run checks the vectors instead: re-embedding with `search_document` the 32
  earliest episodes with vectors in the lane, as `remember` embeds them (`server.py:1867`), must give a median cosine
  of at least 0.99. Otherwise W is "not evaluable: no embedder" or "not evaluable: embedder mismatch". The route gate
  needs no embedder. The stored-vector run stays as a labelled, non-gating diagnostic (step 8.9). R3 now names the
  regime. "Why N" says `w` is a hindsight summary. I3 and the section 10 evaluation row carry the embedder. One addition,
  Rio Grande's call: W's entries now use 6.2's whole locate on `x = content(s)`, words included (FTS in the imprint's
  own indexes, kept to T's nodes), since that is what "through the tools' own function" means. The next hit uses the
  same entries, or the stored-vector ones when the embedder check fails, and says which. A consequence of MF3: N takes
  4 nodes when T names nothing outside the entries, `at_goal` included, since the tool then tells the agent to recall.
- **MF2. Applied, option (a) in a narrower form.** "What an imprint changes" now states the scale and drops the false
  sentence. I4 asks the imprint spec to keep a used recall row with its shipped targets in delivered order, plus
  `context.cut = true` when any non-instinct target stayed home, as an exception to D6 and D7, with check 11 allowing
  the key. *Declined in part:* the original target count. Section 4's "exactly one target" rule needs only to know
  whether a non-instinct target stayed home, so one bit does the job and says less about what stayed home (D21).
  Section 4 never credits a cut row by that rule; that keeps the source's answer, including the pruned-to-cold case.
  Option (b) is not taken: it only tells the owner the data is lost. A synthetic-imprint test is added (section 12).
  Citing operations keep the whole-row rule: each acts on one memory id (`server.py:3037`, `:2729`, `:3620`).
- **MF3. Applied.** `at_goal` now means the goal A* popped is itself an entry. The reviewer's case is written into 6.3
  and planted in the section 12 test, which expects `goal`, e2 → t, cost 0.3. The random graphs include entries in Γ.

### Should-fix

- **S1. Applied.** The output-time check rechecks every node of the computed route, every entry and every named
  memory: at most 70 rows (64 route stops and 6 entries), replacing 24 in 6.6 and section 10. A route has at most 64
  stops; a cheapest route with more is `truncated`. Tests cover a re-laned node hidden in `{"skipped": 8}` and one
  pruned after the build. In W, a route over 64 stops counts as no route.
- **S2. Applied.** `[trails] lanes`, default `["work"]`, parsed fail-closed. The tools refuse unlisted lanes, the
  build builds only listed lanes, and a gate pass licenses only the evaluated lane (R16; step 9; Open for Andy).
- **S3. Applied.** C5 added, quoting revision 3 (`3539102`, section 7). C2, C3 and C4 are now marked Rio Grande's
  calls; C3's 16,384 is called a calibration hypothesis. A5 now says only what Andy's words say, and points to R13
  for "only as an imprint".
- **S4. Applied.** `--imprint-use` takes a use id, never a path, and the allow file is read only at
  `<imprint dir>/uses/<use id>.allow.json`, with no symlinks. `withdrawn.json` refuses. The effective end `exp_eff` is
  checked. The run checks everything again at the end and, on a failure, prints no report and exits with a distinct
  status. The known limit is stated ("narrows mistakes, not malice"). An owner's run on a plain copy of their own
  store is their own use, which `trails.py` doesn't check, and R13 now says so. I2 asks the imprint spec to keep the
  allow file current when an end is shortened, since `trails.py` can't read receipts, and to write no `use-finished`
  report hash after a discarded run.
- **S5. Applied.** The bound is named "6,000 bytes of compact JSON, which `estimate_tokens` counts as 1,500" in Goal
  9, R6, the anti-goal, 6.5 and section 10. The builder records the measured ratio against the agents' model's
  tokenizer in the plan's results. The bound is not lowered now: there is no measurement yet. If the largest answer
  passes 2,000 real tokens, the next revision lowers it (Rio Grande's call).
- **S6. Applied.** Section 8 and section 9 step 4: a remote stop shows its summary only when `inject_context` is
  allowed on that memory; otherwise it names the id alone.
- **S7. Applied.** The digest lets a reader rebuild the graph and check every named id and shown step against it. It
  can't rebuild the answer, for the three reasons the review gives.
- **S8. Applied.** The answer builder takes the receipt id as an argument. Answers are byte-identical apart from it
  when no wall-time bound is hit.
- **S9. Applied.** (a) One graph per server process, so k × 256 MB for k sessions, on top of about 320 MB per server;
  about 2.3 GB for 4 sessions. Vectors are held as float32, the form they are stored in (`storage.py:59-61`), about
  61 MB; converting a block to float64 gives the same numbers, so nothing is lost. A shared graph per machine is left
  to a later step. (b) Step angles are computed at build time, about 2 MB. (c) The 1 s hypothesis excludes
  embedding; embedding 2 × 4,000 characters is measured separately on the Pi. (d) The newest-rows ranking reads every
  `recall` and `route_shown` row with a `json_extract`, and every episode with a session id; neither column has an
  index (`migrations/002_v3_layers.sql:61-63`, `migrations/001_initial.sql:46-52`). It is stated and measured.
- **S10. Applied, with one correction.** Section 7 step 10 gives the worst case: 12 A* searches for the route gate, 2
  for W and 2 for its diagnostic, each up to 10,000 expansions; 11 forward lookups; one embedding batch. Forward
  lookups expand no nodes. They read at most 3 × 256 trails of at most 512 touches, so they are bounded that way, not
  by 10,000 expansions. `--deadline` (1,740 s) gives "not evaluable: limit" for both gates; a run killed by the cap
  writes no report, and the use records "not evaluable: limit".
- **S11. Applied.** The snake_case pattern is now `\b_*[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b`. I checked it in Python:
  the old pattern matches nothing in `_record_application`, the new one matches it whole. Overlaps are defined (drop
  a match inside a longer match, order by start, one per text, first 8). The test lists each example's expected
  anchor: `sqlite3.OperationalError` gives `OperationalError`, and `engram/server.py` gives only itself.

### Nits

All applied.

- N1: list items are "stops" (vocabulary, 6.5, section 10, tests).
- N2: degraded mode keeps words, ordered by id at cost 2π.
- N3: receipts show 8 hex characters, with a note for Rio Grande that the permissions spec's 4 collide the same way.
- N4: truncated trails give no end, and count in `ends_unknown`.
- N5: stated as conservative, kept (R9).
- N6: the bounds are split equally among listed lanes.
- N7: `laid_by` reads `stores.owner`, read-only, once per build (6.5, section 10, section 11).
- N8: the counters live in server memory, reached through a `trails_reporter` callable, as `category_reporter` is
  (`reflection.py:60`, `:69-77`; `server.py:1418-1430`).
- N9: I1 names the 6.2 row, D6 and check 11, and keeps `route_shown` rows whose cut list is empty.
- N10: the build's connection is registered with `_register_server_cleanup` (`server.py:835-838`). The build checks
  admission between batches, as `_maintenance_step_scope` does (`server.py:1096-1112`), and stops on shutdown.
- N11: "An agent can share only inside the envelope of a grant, never past what a person signed (L4)".
- N12: `no_route` is the open list running empty before any bound.
- N13: `cost` includes the entry cost, with the example's arithmetic.
- N14: N is "nearest to the goal".
- N15: a pointer to the `imprint` action for rail agreement.
- N16: `trail_next` is covered by the next-hit report alone (step 9).

### Small corrections found while checking

- The recall log call is at `server.py:2380-2386`, not `:2381-2387`.

### Left for Rio Grande, not for Andy

- I1–I4 for the imprint spec, I4 above all: until it lands, an imprint's gates will likely be "not evaluable".
- Whether the permissions spec should also lengthen its short ids (N3 note).
- Whether a shared tool graph per machine is worth a later spec (S9a).

"Open for Andy" is unchanged in substance: which store to imprint first and its owner's yes; his act after a pass,
now naming the evaluated lane; and the license.

## Re-check of 2026-10-25

Reviewer: a second fresh agent on the Pi, re-checking in Andy's place under station law section 3. I took no part in
writing, reviewing, revising or reconciling this spec. I read the vision, revision 5 as it stands after the interface
pass (uncommitted on `trail-arrows-spec`), the review and response above, the interface table
(`docs/superpowers/reviews/2026-10-25-city-rail-interfaces.md`), and the cited sections of the permissions and imprint
specs. I read every code claim I rely on at the cited lines today. Spec references are `§section` and line numbers of
the current file. Code references are relative to `engram/`. I edited only this file.

VERDICT: APPROVE WITH CHANGES

Approval holds once RMF1 and RMF2 are applied. Both are small. Both are Rio Grande's calls, not Andy's. Apply the RS
items in the same pass. Nothing new needs Andy.

### The first review's must-fix items

- **MF1. Resolved.** §7 step 8.2 (lines 1003-1021) embeds `content(s)` and `content(w)`, each cut to 4,000
  characters, in one batch with `search_query`, which is the tools' regime. R3 names the regime (line 51). §6.3 "Why
  this r" says the stored-vector run is not evidence for r (lines 575-580). Step 8.9 keeps that run as a non-gating
  diagnostic. "Why N" says `w` is a hindsight summary (lines 1061-1063). I3 and the §10 evaluation row carry the
  embedder. Code: `remember` embeds `content` with `search_document` (server.py:1867); recall embeds with
  `search_query` (server.py:2186); the model is `nomic-ai/nomic-embed-text-v1.5`, 768 dimensions (embeddings.py:70-71);
  the shared client refuses another model (embeddings.py:171-177); the provider factory is embeddings.py:200-207. One
  gap remains in how the run reaches the model (RS2).
- **MF2. Resolved.** The false sentence is gone, and §7 says it was wrong (lines 896-897). The scale is stated and
  true: the lane filter runs only when a lane is given (server.py:2332-2333), truncation to `max_results` comes after
  it (server.py:2367), and the row logs the delivered ids (server.py:2380-2386). I4 was asked for, then declined by the
  interface pass under its rule that privacy wins over trail quality. That is the right party deciding. §7 "The cost,
  chosen for privacy" (lines 899-921) records the cost and gives a source-side way to lower it that tells nothing more.
  The synthetic-imprint test is added (§12, lines 1448-1458). Part of the review's option (b) already exists: the
  imprint dry run counts the recall rows that stay home (imprint spec 5.4, "912 recall rows stay because a result
  stays"). One bullet of the new test is wrong for another reason (RMF2).
- **MF3. Resolved for the reviewer's case, not in general.** The planted case now gives `goal`, e2 → t, cost 0.3
  (§6.3, lines 594-597; §12, lines 1378-1380). The new wording of `at_goal` fails in a related case (RMF1).

### Must-fix

**RMF1. `at_goal` still disagrees with Claim 3 when an entry in Γ is reached through another entry.**
*Where:* §6.3 lines 585-587 and §12 lines 1375-1376, against §6.3 lines 519-521, Claim 3, and §12 line 1381.
*Reason:*
- §6.3 says `at_goal` holds when "the goal A* popped is itself an entry, so its `g` is its entry cost and the route is
  one stop with no steps".
- Take entry e1 in Γ with w(e1) = 1.0, entry e2 not in Γ with w(e2) = 0, and an edge e2 → e1 of cost 0.3. A* pops
  e2, lowers g(e1) to 0.3 with parent e2, then pops e1. I ran this in Python: the popped goal is an entry, its g is
  0.3, its entry cost is 1.0, and the route is e2 → e1.
- So "the popped goal is an entry" doesn't imply "its g is its entry cost" or "one stop". The `at_goal` test (one
  stop, no steps) and the cost test (`cost` = g of the popped goal, line 1381) can't both pass here. The 500 random
  graphs include entries in Γ with random entry costs (lines 1371-1373, 1380), so they will produce this case.

*Fix:* `at_goal` means the popped goal has no predecessor: A* reached it at its own entry cost, so the route is one
stop. A goal that is an entry but was reached through another entry is `goal`, with its route and cost. Plant this
case in §12 beside the reviewer's. The mathematics decides it; only the wording is Rio Grande's call.

**RMF2. Every imprint carries the order in which each session wrote its episodes, with or without `route`.**
*Where:* §7 "What an imprint changes" (lines 875-882); §12 "Synthetic imprint", last bullet (line 1458); §11
interfaces (lines 1277-1313); imprint spec 6.2 (line 469), D7, 8 (`Need(admission)`) and 10 (line 1093); interface
table row 13.
*Reason:*
- A trail is "one session's touches in one lane, in order" (§2), and a wrote touch is "every episode carrying that
  `session_id`" (§4). So a session that wrote two episodes in a lane has a trail with no log row at all.
- The imprint copies `episodes` rows with "every column except `rowid`" (imprint spec 6.2, line 469). So `session_id`
  and `created_at` ship in every imprint. Calibration reads exactly that: `paths.report` (paths.py:418) calls
  `session_paths`, which groups episodes by `session_id` in `(created_at, id)` order (paths.py:348-355), and
  calibration calls it (calibrate.py:296). The imprint spec's own example reports "31 session paths" (its section 10).
- The specs agree that the owner's trails leave only when the owner chooses `route`: "sharing a memory is still not
  consent to sharing routes" (§8), interface row 13, and imprint D7. The dry run tells the owner the recall log is
  "sent only because you chose route". `Need(admission)` covers trails only "whose log rows I holds" (imprint spec 8).
  So an imprint without `route` keeps trail material that no record covers, and the owner isn't told. The vision's
  "Count its own trails as the person's" isn't met there.
- The §12 bullet "built without `route`, the imprint holds no log rows, and `trails.py` finds no trail on it" is false
  as written. Trails derived from such an imprint exist, made of wrote touches. If it means `trails.py` refuses, which
  it does (no allow file can name `route` without it), it should say that.

*Fix* (Rio Grande's call, with the imprint spec):
- §7 says plainly that episodes keep `session_id` in every imprint, so wrote-touch trails are on every imprint. Only
  cited touches depend on log rows.
- Add an interface item I5, and choose one:
  - **(a)** Without `route`, the imprint ships `episodes.session_id` as null. This is the safer default, by the
    interface pass's own rule. The cost is calibration's session paths on such an imprint, which the imprint spec
    records.
  - **(b)** Keep `session_id`, and treat each session's written order as a trail every imprint keeps. Then
    `Need(admission)` covers those trails (`recall`, `read`, `imprint`), and the dry run and confirm view say "the
    order in which each session wrote these memories" leaves.
- Fix the §12 bullet: without `route`, `trails.py` refuses the imprint for want of an allow file; under (a), the
  imprint also holds no session ids.

### Should-fix

**RS1. The imprint spec's test says the opposite of §7.** *Where:* imprint spec section 16, "Recall rows" ("A trail
derived from the package equals the trail derived from the source restricted to M"), against §7 lines 904-916.
*Reason:* §7 says, rightly, that an imprint's trails differ from the source's restricted to what shipped: a dropped
row takes the cited touches of shipped memories with it, a touch whose only evidence stayed home is lost, revisit
views start later, and closure can differ. The imprint test asserts equality. On a fixture with one mixed-lane recall,
the two tests can't both pass. This spec is the source of truth for trails, so the fix is in the imprint spec: assert
equality only for touches from rows the package keeps, or point to this spec's synthetic-imprint test. For Rio Grande.

**RS2. "The run never downloads a model" has no mechanism.** *Where:* §7 step 8.2 (line 1015), I3 (lines 1295-1301);
imprint spec 18. *Reason:*
- Without `ENGRAM_EMBEDDER_SOCKET`, `create_embedding_provider()` builds `NomicEmbedProvider` (embeddings.py:200-207).
  That calls fastembed's `TextEmbedding(model_name=…, cache_dir=…)` (embeddings.py:77-79).
- fastembed 0.7.4 defaults to `local_files_only=False` (`fastembed/common/model_management.py:139`, read in the Pi's
  `pr6-update` venv), so a missing model is downloaded, not reported as "no embedder".
- A `systemd-run --user` unit doesn't get the caller's shell environment. Unless the Makefile passes the socket
  variable, the run takes the in-process path.

*Fix:* say how the run stays offline. For example, build the provider with `local_files_only=True`, or check the
cache first and report "not evaluable: no embedder" when the model is absent. Also say how the unit gets
`ENGRAM_EMBEDDER_SOCKET` when the shared service is meant. Rio Grande's call.

**RS3. An allow file stays valid after its use ends.** *Where:* §7 "The imprint check" (lines 852-868), R13; imprint
spec 12. *Reason:* nothing removes or retires `<id>.state/uses/<use id>.allow.json` when the use finishes. So
`trails.py --imprint-use <old use id>`, rerun from shell history by mistake, passes every check until the effective
end and leaves no `use-started` receipt. That is a use without a receipt (vision principle 5), and exactly the kind of
accident the known limit says the check stops. *Fix:* finishing a use retires its allow file (the imprint spec's
`station-imprint-sync`), and `trails.py` refuses a use id whose `<id>.state/uses/<use id>/` already holds a report or
result. Rio Grande's call.

**RS4. A shortening during a run is recorded as a withdrawal.** *Where:* §7 check 6 (lines 865-868), I2 (lines
1291-1294); imprint spec 12. *Reason:* a shortening rewrites the allow file (imprint spec 12), so its SHA-256 changes
and the run exits with its withdrawn status, even when the new end is still ahead. The use then records "withdrawn"
though nothing was withdrawn. Discarding the run is fine, since it only narrows. The receipt should say what
happened. *Fix:* name the exit status "allow changed", and record "withdrawn" only when the tombstone exists. Rio
Grande's call.

### Nits

- **RN1 (§6.6 lines 793-796).** "The permissions spec writes short ids with 4 (its section 4.1)" is out of date. Its
  4.1 now gives receipts 8 hex, as §11 here already says. Only records, grants and proposals keep 4.
- **RN2 (§6.5 lines 639-641; example line 666).** `stores.owner` holds `person:<handle>` (imprint spec 5.1 compares
  it to `person:<owner>`). The example and the permissions spec's annotation show `andy (…)`. Say the handle is shown
  without `person:`.
- **RN3 (§6.6 lines 711-713).** Say what `lanes = []` does. It is a list of distinct valid strings, so it isn't
  invalid, but it lists no lane, and "split equally among the listed lanes" would divide by zero.
- **RN4 (§6.3 line 588).** `no_goal` names "the nearest node". When no node has a vector there is none. Say it names
  nothing then.
- **RN5 (§6.6 lines 774-777; §10).** Say whether 256 MB per process is enforced by the build (stop, record
  `truncated`) or a target that the Pi measurement checks.
- **RN6 (§7 step 7, lines 989-992).** A rerun gives the same bytes only with the same embedder. The shared service and
  the in-process model, or different batch shapes, can differ in the last bits and flip a θ ≤ r test. Record the
  provider in the report, and say "with the same provider".
- **RN7 (§7 steps 7 and 9).** Say that the report names the evaluated lane, since a pass licenses only that lane and
  the receipt binds the report's hash.
- **RN8 (§11 CLI, line 1258; imprint spec 12).** `--lane` defaults to `work`, and the imprint spec says `LANE` "may be
  left out when the scope holds one lane". Say the use always passes `--lane`, as interface row 27 says, so a
  personal-only imprint never runs on `work` by default.
- **RN9 (revision history, line 32).** Revision 5's row still says "Imprinted recall rows keep their shipped targets
  (I4, MF2)". Add "(declined in the interface pass)".
- **RN10 (§7 check 2, line 853).** The imprint spec gives no form for a use id. Ask it to name one that fits
  `[A-Za-z0-9-]{1,64}`, such as a uuid4.
- **RN11 (§6.6 line 771).** `_admit_server_operation` is at server.py:809-819, not 807-817.

### What I checked and found true

**Code**, read at the cited lines today:

- server.py: `_mutation_logged` (:38-64); fork hooks (:252-256, :374-379); `_server_tool` (:690-697);
  `_register_server_cleanup` (:835-838); `_maintenance_step_scope` (:1096-1112); prune is step 2 (:1175),
  `persistence-score-refresh` is last (:1279-1282), and the report is saved after it (:1289-1290); `category_reporter`
  wiring (:1418-1430); `_apply_recall_bias` (:1499); `remember`'s embedding (:1867); the `default` instance name
  (:1976); `max_results` 20 (:2068); the lane check (:2089-2090); recall's embedding (:2186); results carry content
  (:2281-2286) and a lane for episodes and semantics (:2292, :2299); the lane filter (:2332-2333); truncation (:2367);
  the log row (:2380-2386); access counts (:2388-2391); the observer gate's `is True` (:2650); `_record_application`
  finds rows by `$.recall_id`, which a receipt doesn't carry (:2664-2675); the citing operations (:2729, :3037, :3620);
  the maintenance thread's registration (:4018); `_initialize_pre_serving` then `mcp.run()` (:4023-4038).
- reflection.py: the `Reflector` holds storage, paths and configs (:53-66), `category_reporter` (:60, :69-77), focus
  dispatch (:732-775).
- storage.py: similarity (:23-28), float32 packing (:59-61), FTS quoting (:64-74, used at :1062-1071),
  `open_read_only` (:127-161), `add_log_entry` (:1656-1680), counters that ignore unknown event types (:1765-1789).
- embeddings.py (:70-71, :171-177, :200-207); embedder_service.py takes up to 4,096 texts a request (:42), so the
  32-text check fits one request.
- paths.py (:43-44, :348-355, :397-409); store_reader.py (:43-54); category_compile.py (:195-197: 6,000 bytes count as
  1,500); config.py:44; graph.py (:461, :502-512); hooks/sleep.py:44; cli.py:38-49; store_identity.py:143-160;
  federation.py:127-142; sharing.py (:143-147, :167-172).
- Migrations: `idx_memory_log_event_type` (002:62) and no index on `json_extract(context, '$.session_id')`;
  `episodes.session_id` (001:48) has no index in any migration (013, 018 and 028 index other columns).
- The Pi: a Raspberry Pi 5 with 16 GB. `~/.engram` is absent, and no `graph.db` exists under the home directory.
- C5's quote is at line 330 of the spec in `3539102`.

**Mathematics.**

- Lemmas 1-2 and Claims 1-3 hold. The super-source construction is right. RMF1 is about the answer's label, not the
  search.
- The radius rule makes Γ empty exactly when θ_min > r_max or no node has a vector.
- Birthday bounds: 4 hex gives even odds near 301 receipts, 8 hex near 77,163.
- Sizes: 20,000 × 768 × 4 B ≈ 61 MB; 262,144 × 8 B ≈ 2 MB; a 4,096-row float64 block ≈ 25 MB; 4 × (256 + 320) MB ≈
  2.3 GB; 16 searches × 10,000 = 160,000 expansions; trail_next names 3 + 3 × 4 = 15 items; 64 + 6 = 70 rows
  rechecked.
- The example: 2 × 0.4102 + 1.1177 = 1.9381, and 0.5213 + 0.10 = 0.6213 ≥ 0.5590.
- The anchor patterns: I ran them and the overlap rule in Python on §12's examples, alone and in one text. Each gives
  the expected anchor, and `server.py` inside `engram/server.py` is dropped.

**The first review's should-fix items and nits.** S1-S11 and N1-N16 are applied as the response says. I checked each
against the text. S4's paths were then corrected by the interface pass, and they match the imprint spec (row 27
below).

**Against the other two specs**, row by row of the interface table (rows 3, 4, 11 and 31 have no trail column):

- Agree: 1 and 2 (§8's R2 has P's fields and a finite `stores` list, P 5.4); 5; 6 (R14); 7 (§7: `read` covers the
  text, no `inject_context`, imprint spec 5.3 and 8); 8 (§8 and P 6.4, "One use per edge"); 9 (§8, §9 step 4, P 6.4);
  10; 12; 15 (§7 and §11 I1, imprint D35 and check 11); 16; 17; 18 and 19 (§6.5, P 7.4 and 5.5, imprint D37); 20 (§14
  keeps the imprint spec's default and lists the question); 21; 22 (but RN1); 23; 24 (but RS4); 25 (§6.5, P 7.4); 26
  (§8, §9 step 3, imprint 11); 27 (the directory name is the imprint's `instance_id`, imprint 11 and check 8; the allow
  file's path and fields `instance_id`, `actions`, `purpose` and `valid_until`, the tombstone and the state directory
  all match imprint 10 and 12); 28 (but RS2); 29 (§7 step 10, imprint 10 and 12); 30; 32.
- Disagree: 13 (RMF2: episodes carry trails in every imprint). 14 agrees in this spec, but the imprint spec's test
  contradicts it (RS1).

### Against the vision, privacy, the Pi, and planning

- **Vision.** Every item of the traveler's view is still covered, as the first review lists. The spec stays inside
  the principles: mathematics is the connector, the code is standard library and numpy, and it runs on the Pi. The
  license is still open (§14).
- **Privacy.** RMF2 is the one place where something about a person can leave without the yes the specs say it
  needs. Otherwise in step 1 nothing leaves the store. The tools serve only the server's own store to its own agent
  (the permissions spec's non-goal). Receipts hold ids and no text. The output-time check keeps a re-laned memory out
  of a work answer, shown or skipped. An agent can't widen a permission: step 1 checks none, and later steps go
  through the meet, with summaries across a boundary only under `read` and `inject_context` (§8). An agent that edits
  the tools' config gains nothing beyond what recall already returns on its own store (server.py:2332-2333). Memories
  that mention other people stay open with Andy. This spec keeps the imprint spec's default and changes nothing (§14).
- **Pi.** SQLite, numpy, no GPU, and every pass is bounded. RS2 is the one gap: the run could reach the network for a
  model.
- **Planning.** After RMF1 and RMF2, a builder can plan without asking Andy. RMF2's choice and RS1-RS4 are Rio
  Grande's. "Open for Andy" holds the right items: which store to imprint first and its owner's yes; memories that
  mention other people; his act after a pass, for the evaluated lane; and the license.

## Re-check response (revision 6)

Reviser: Rio Grande's spec reviser, 2026-10-25. Revision 6 is in the same file, uncommitted on `trail-arrows-spec`. I
read every code claim the changes rest on again at the cited lines. I also read the imprint spec as it stands now: its
revision 3 was being written in parallel during this pass. I edited only the trail spec, this file and the interface
table. I committed, pushed and posted nothing. Every new decision is marked "Rio Grande's call" in the spec.

### Must-fix

- **RMF1. Applied.** I ran the case in Python again, with strict relaxation: A* pops e2, lowers g(e1) to 0.3 with
  predecessor e2, then pops e1, so the route is e2 → e1 at cost 0.3. In §6.3, each entry now starts with no
  predecessor, and a relaxation replaces `g` only when the new cost is strictly lower. `at_goal` means the popped goal
  has no predecessor. Only an entry can lack one, so A* reached it at its own entry cost, and the route is one stop.
  An entry reached through another entry is `goal`, with its route and cost. At an exact tie the entry keeps no
  predecessor, so the answer is `at_goal` at the same cost (also run). §6.3 gives the case as a second example. §12
  plants three cases (the first review's, yours, and the tie), each against the brute-force Dijkstra. On the 500
  random graphs, the answer is `at_goal` exactly when the popped goal has no predecessor, and `cost` always equals its
  `g`. Claim 3 decides it; only the wording is Rio Grande's call.
- **RMF2. Applied, option (a)** (R18, new interface item I5; Rio Grande's call, by the interface pass's rule that
  privacy wins). §7, "What an imprint changes", now says plainly that episodes with their session ids hold each
  session's written order, which is a trail with no log row. Calibration reads it (`paths.py:348-354`, `:418-426`;
  `calibrate.py:295-296`). Without `route`, every episode ships with `session_id` null and no log row ships, so no
  trail of any kind is on the imprint. The cost: `paths.report` finds no session (`paths.py:349`, `:423`), and
  `store_reader`'s survey counts none (`store_reader.py:126-131`). With `route`, only sessions closed at t₁ keep their
  session ids, which is the imprint spec's narrower rule. One known limit is stated: write times stay, so someone could
  guess sessions from gaps between writes. No record says which episodes a session wrote. The §12 bullet now says that
  without `route` every `session_id` is null, the derivation finds no session, and `trails.py` refuses for want of an
  allow file naming `route`. A new bullet checks that wrote touches survive with `route`.
  - *The imprint spec already applies it.* Its revision 3 took option (a) for its own re-check, in D6, D7, D10, 5.2,
    5.4 (the row key now holds `session_id as kept`), 6.2, and section 8's R(I), "from its episodes' session ids and
    its log rows". The dry run and confirm view say it, check 12 requires null session ids without `route`, and its
    section 10 example and log-rows test account for `paths`. I read it at the end of this pass. Nothing of I5 is
    pending there.
  - Interface row 13 now names session ids as trail material, and says what changed.

### Should-fix

- **RS1. Not applied here, by the scope rule; recorded as I6, pending in the imprint spec.** This pass may not edit
  the imprint spec. §7 now says its test asserts more than holds. I6 asks it to assert what does hold, a property I
  checked against section 4's rules. Every touch derived from the package is a touch derived from the source: the
  same memory, kind and time, in the same order within its recall, and suggested only if the source's is. And on
  every kept recall row, the "exactly one target" rule gives the source's answer. For what is lost, I6 asks for a
  pointer to this spec's synthetic-imprint test. It asks for order rather than equal `rank`, because the package
  removes instinct ids from `target_ids`, which can shift positions. Interface row 14 records the request. The rule
  is unchanged.
- **RS2. Applied** (R19; Rio Grande's call). I read fastembed 0.7.4 in the Pi's `pr6-update` venv. `TextEmbedding`
  passes `local_files_only` through (`text/text_embedding_base.py:19`). With `True`, `download_model` reads only
  the cache and raises `ValueError` (`common/model_management.py:399`, `:403-413`, `:463-473`). §7 step 8.2: without
  the socket variable, `trails.py` builds the in-process provider with `local_files_only=True`, a new keyword on
  `NomicEmbedProvider` and `create_embedding_provider` (new `embeddings.py` row in §11). Servers and the embedder
  service keep the default. A missing model, a missing `fastembed`, or a service that doesn't answer
  (`EmbedderUnavailableError`, `embeddings.py:133-134`, `:191-194`) all give "not evaluable: no embedder".
  - *How the unit gets the socket.* systemd-run(1) on the Pi (systemd 252) says a transient service runs "in a clean
    and detached execution environment". So the use passes `--setenv=ENGRAM_EMBEDDER_SOCKET=<path>` when the
    station's `~/.config/superyak/runtime.json` names an `embedder_socket`. That is the key `superyak-runtime` reads
    to set the variable for every engram process (`scripts/runtime.py:84-89`, `:597`, `:653-655`).
  - Tests: an empty cache and no network; an unserved socket loads no local model; the unit carries `--setenv`
    exactly when `runtime.json` names a socket. I3 asks the imprint spec for the unit's side (its 12 and 18), pending.
    Interface row 28 updated.
- **RS3. Applied** (R13; Rio Grande's call). New check 5: `trails.py` refuses a use id whose
  `<root>/<id>.state/uses/<use id>/` already holds `report.json` or `result.json`. Those are the names the imprint
  spec already uses for admission's state directory (its section 10). Finishing a use retires its allow file, so
  check 2 refuses a finished use too. I2 asks the imprint spec's `station-imprint-sync` to delete the allow file when
  it writes `use-finished`, and `imprint.py use` to write those two files. Pending there. The known limit now names
  "a second time under one use id". Tests are added. Interface row 27 updated.
- **RS4. Applied** (Rio Grande's call). The end check (now check 7) exits with status 3, named `allow changed`, and
  doesn't say why. The use records `withdrawn` only when the tombstone exists, `ended` when the effective end has
  passed, and `allow changed` otherwise. *One addition:* `ended`. An end reached during a run is neither a withdrawal
  nor a mere change, and the receipt should say what happened. The imprint test now rewrites the allow file with a
  shorter end that is still ahead, and expects `allow changed`. I2 asks the imprint spec to record these ends, pending
  there. Interface rows 24 and 27 updated.

### Nits

All applied.

- RN1: §6.6 now says the permissions spec's receipts show 8 hex, and only its records, grants and proposals keep 4.
  Interface row 22 notes it.
- RN2: `stores.owner` holds `person:<handle>`, and `laid_by` shows the handle without `person:`, as P 11's annotation
  does (§6.5).
- RN3: `lanes = []` is valid and lists no lane. The tools stay registered, every call answers "lane not enabled:
  <lane>", the build builds nothing, and there is nothing to split (§6.6). A test is added.
- RN4: with no node holding a vector, `no_goal` names nothing (§6.3, §12).
- RN5: the build enforces the counts, not bytes. 256 MB is a target that the Pi measurement checks (§6.6, §10 and
  §12). Interface row 29 updated.
- RN6: the report names the provider and model. Byte identity is "with the same embedder provider" (§7 step 7, §12).
- RN7: the report names the evaluated lane. A test checks that a different `--lane` gives a different hash.
- RN8: the use always passes `--lane`, filling in the scope's one lane when `LANE` is left out. On an imprint,
  `trails.py` refuses without an explicit `--lane` (§7, I2, §12).
- RN9: revision 5's row now says I4 was declined in the interface pass, and that MF3's `at_goal` was corrected in
  revision 6. Revision 5's commit cell reads "uncommitted draft", since revision 6 is now "this file".
- RN10: I2 asks the imprint spec for a lowercase uuid4 use id, which fits `[A-Za-z0-9-]{1,64}` (§7 check 2).
- RN11: `server.py:809-819`.

### Declined

Nothing outright. RS1, and the imprint side of RS2, RS3, RS4, RN8 and RN10, need the imprint spec to change. This
pass may not edit it, so each is written as an interface item (I2, I3, I6) and marked pending there. RMF2's imprint
side (I5) is already in that spec's revision 3.

### Small corrections found while checking

- `NomicEmbedProvider` calls `TextEmbedding(...)` at `embeddings.py:78-80`, not `:77-79` (RS2 cited `:77-79`).
- `paths.report` calls `session_paths` at `paths.py:425-426`, so the spec cites `:418-426` for the function.

### Left for Rio Grande, not for Andy

- In the imprint spec: I2's five points (use ends, retiring the allow file, the two file names, the use id form,
  always `--lane`), I3's `--setenv`, and I6's test.
- Unchanged: whether a shared tool graph per machine is worth a later spec.

"Open for Andy" is unchanged. It lists which store to imprint first and its owner's yes. It lists memories that
mention other people: still open, and this spec keeps the imprint spec's default, with nothing changed about it. It
lists his act after a pass, for the evaluated lane, and the license. Every change here narrows or clarifies. None
widens what a person allowed or lets more leave a machine. The new code is standard library, numpy and the existing
fastembed, and it runs on the Pi.

## Final check of 2026-10-25

Reviewer: a fresh agent on the Pi, making the final check in Andy's place under station law section 3. I took no part
in writing, reviewing, revising or reconciling this spec. I read the vision, all of revision 6 (uncommitted on
`trail-arrows-spec`), this file, the interface table, and the cited parts of the imprint and permissions specs. I read
every code claim I rely on at the cited lines today. Spec references are `§section` and line numbers of the current
file. Code references are relative to `engram/` unless they say otherwise. I edited only this file.

VERDICT: APPROVE

No must-fix remains. RMF1 and RMF2 are resolved. The fixes add no must-fix defect and break no interface. The two
should-fix items and the nits below are for Rio Grande. Nothing new needs Andy.

### The re-check's must-fix items

**RMF1. Resolved.**

- §6.3 starts each entry with no predecessor, and replaces `g` only on a strictly lower cost (lines 525-528).
  `at_goal` now means the popped goal has no predecessor (lines 594-600). Only an entry can lack one, so its `g` is
  its `w(e)` and the route is one stop. An entry reached through another entry is `goal`, with that route and cost.
- The re-check's case is written out as a second example (lines 613-618). §12 plants it beside the first review's
  case and the tie (lines 1512-1517). The random-graph test now expects `at_goal` exactly when the popped goal has no
  predecessor, and `cost` equal to its `g` (lines 1518-1520).
- I wrote an A* in Python from §6.3 alone: strict relaxation, keys `(f, h, id)`, a closed set. The three planted
  cases give `goal` e2 → t at 0.3, `goal` e2 → e1 at 0.3, and `at_goal` e1 at 0.3, with h(e2) set to 0, 0.1 or 0.3.
  On 500 random graphs built as §12 describes, A*'s cost equals a super-source Dijkstra on every graph, and every
  `at_goal` answer is one stop at its entry cost. 15 of the 500 hit the re-check's case (an entry in Γ reached
  through another entry), so the test will exercise it.
- Claim 3 is unchanged and holds. Only the wording is Rio Grande's call, as the spec says.

**RMF2. Resolved, option (a).**

- R18 (line 71) and §7 "What an imprint changes" (lines 918-942) say plainly that episodes with session ids hold each
  session's written order, which is a trail with no log row. Without `route`, every episode ships with `session_id`
  null and no log row ships, so the imprint holds no trail of any kind (lines 930-934). With `route`, only sessions
  closed at t₁ keep their ids (lines 935-938).
- The code agrees. `session_paths` selects only episodes that have a session id (paths.py:348-354, the filter at
  :349). `paths.report` counts only non-null ids (paths.py:423) and calls `session_paths` (:425). Calibration runs it
  (calibrate.py:295-296). `store_reader`'s survey counts distinct session ids (store_reader.py:129). So null ids give
  no session in any of them, as the spec says.
- Nothing else in an episode row carries the session. `remember` and the other server writers pass the id only as
  the column (server.py:1869-1876, :2834-2844, :2885-2895), as the nudge hook does (hooks/nudge.py:531-535). None
  puts it in `context`.
- The imprint spec applies I5, as I5 says (lines 1425-1437). It does so in D6 and D7; in 5.2, "Log rows and session
  ids"; in the 5.4 row key, `session_id as kept`, and the dry run's "Session ids … sent only because you chose route";
  in the 6.2 `episodes` row; in R(I) of section 8, "from its episodes' session ids and its log rows"; in check 12; in
  section 10's paths note and example; and in its test "No footpath without `route`". Its anti-goal "Footpaths
  without `route`" names it too.
- The §12 bullet is fixed (lines 1607-1610). Without `route`, every `session_id` is null, the derivation finds no
  session, and `trails.py` refuses for want of an allow file naming `route`. A new bullet checks that wrote touches
  survive with `route` (lines 1605-1606).
- Interface row 13 now names session ids as trail material, and all three specs agree with it.
- It narrows. Less leaves a machine than before, and the vision's "Count its own trails as the person's" is met: the
  owner's trails leave only with the owner's `route`.

### New must-fix

None.

### Should-fix

**FS1. The offline test can't pass as written.**
*Where:* §12 "Goal gate (W)", the offline bullet (lines 1586-1589).
*Reason:*
- The bullet says "nothing is written to the cache directory".
- fastembed 0.7.4 makes directories there even with `local_files_only=True`: the cache directory itself
  (`fastembed/common/utils.py:57`) and `<cache>/tmp` (`fastembed/common/model_management.py:344`). It also deletes a
  stale partial download (`:342`, `:349`).
- I ran it in the Pi's `pr6-update` venv against an empty cache, with every non-Unix socket connect made to fail. It
  made no network attempt and raised `ValueError`, as R19 says. It left an empty `tmp/` behind.
*Fix:* say "no file is created in the cache directory, and no model is fetched", or give the test a read-only cache
and expect "not evaluable: no embedder". R19 itself stands. Rio Grande's call.

**FS2. The owner isn't told that recall times leave with the memories.**
*Where:* §7, the known limit (lines 940-942); imprint spec 5.4, the dry run.
*Reason:*
- The known limit names write times only. An episode row also ships `accessed_count` and `last_accessed`, "copied as
  of the build" (imprint spec 5.4). Recall sets `last_accessed` on each episode result, one after another in one
  loop (server.py:2388-2391; storage.py:626-638). So episodes whose `last_accessed` values lie milliseconds apart
  were very likely returned by one recall.
- Resonances ship without `route` (imprint spec 6.2). Recall forms them from results that came back together
  (server.py:2489-2491). So a resonance's `created_at` says when one recall first returned both memories.
- None of this is a trail under §4: a surfaced memory is not a used one, and no record names a session. Nothing
  leaves beyond the columns of memories the owner chose, so this is not a must-fix. But the dry run says "Without
  route, which session wrote each episode, and the recall log, would stay here too". That reads as if nothing about
  when the agents worked leaves.
*Fix:* name access times and resonance times beside write times in the known limit. Ask the imprint spec, as a
follow-up to I5, to say in the dry run and the confirm view that write and recall times leave with the memories.
Rio Grande's call.

**Carried over, pending in the imprint spec.** I2's new parts, I3's `--setenv` and I6 are still pending there, as
§11 says. Until I6 lands, the imprint spec's test "A trail derived from the package equals the trail derived from the
source restricted to M" (its section 16, "Recall rows") contradicts this spec's synthetic-imprint test (lines
1599-1601). Until I2 lands, check 5 has no file to find, and a finished use keeps its allow file. Land them before the
plan.

### Nits

- **FN1 (§7 lines 918-919; step 8.2 lines 1083-1084).** "Whole, with one exception" and "ships episodes and
  semantics whole" overstate it. The imprint spec also scrubs `semantics.contradicted_by` (its 6.2), and with
  `route` a session open at t₁ keeps no id. Say "their content whole".
- **FN2 (§7 step 8.2, line 1097).** `text/text_embedding_base.py:19` is where the wrapper pops the flag. The flag
  reaches the model loader through `**kwargs` at `text/text_embedding.py:114-123`, and is used at
  `text/onnx_embedding.py:254`. Cite those too.
- **FN3.** Lines 741, 1069, 1084, 1273 and 1638 run past the file's wrap width.

### What I checked and found true

**Code**, read at the cited lines today:

- server.py: `_admit_server_operation` (:809-819), `_register_server_cleanup` (:835-838), the maintenance thread's
  registration (:4018), `remember`'s embedding and write (:1867, :1869-1876), recall's embedding (:2186), the lane
  filter (:2332-2333), `max_results` (:2068), access counts (:2388-2391), the `default` instance (:1976), the
  observer gate's `is True` (:2650).
- embeddings.py: `_CACHE_DIR` (:12), model and dimension (:70-71), `TextEmbedding(...)` (:78-80),
  `EmbedderUnavailableError` (:133-134), the model check (:171-177), the socket failure (:191-194), the factory
  (:200-207).
- fastembed 0.7.4 in the Pi's `pr6-update` venv: `common/model_management.py:139`, `:399`, `:403-413`, `:463-473`;
  `text/text_embedding_base.py:19`. With `True` it reads only the cache: the Hugging Face fetch is skipped
  (`:431`), and the URL path raises without downloading (`:351-370`).
- `scripts/runtime.py:84-89`, `:597`, `:653-655`. The Pi runs systemd 252, whose systemd-run(1) says a service runs
  "in a clean and detached execution environment".
- paths.py, calibrate.py, store_reader.py and hooks/nudge.py, as above.

**Interfaces.** Revision 6 changed rows 13, 14, 22, 24, 27, 28 and 29. Each matches this spec and the current text of
the other two.
- Row 13 agrees in all three specs.
- Rows 14, 24, 27 and 28 agree here, with the imprint spec's side pending as I2, I3 and I6 say. The imprint spec's
  section 12 still says what §11 says it says.
- Row 22 agrees with the permissions spec's 4.1: receipts show `#` and 8 hex, while records, grants and proposals
  keep 4.
- Row 29 agrees.

RN2's `person:<handle>` matches the permissions spec's `stores` table (its 5.5) and the imprint spec's
`person:<owner>` (its 5.1). No other row changed, and RMF1 touches no interface.

**Against the vision.**
- People own what is about them: R18 narrows, and no change widens what a person allowed.
- Mathematics is the connector: Lemmas 1-2 and Claims 1-3 hold.
- Free and open source: the license stays open (§14).
- Raspberry Pi: SQLite, numpy, no GPU, bounded passes, and the run stays offline.
- Memories that mention other people stay open with Andy. §14 keeps the imprint spec's default (no memory with a
  recorded co-subject ships, and the owner confirms the rest) and changes nothing about it.
- A builder can plan without asking Andy. "Open for Andy" holds the right items: which store to imprint first and
  its owner's yes; memories that mention other people; his act after a pass, for the evaluated lane; and the
  license.
