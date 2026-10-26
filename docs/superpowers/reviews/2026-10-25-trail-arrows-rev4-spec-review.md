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
