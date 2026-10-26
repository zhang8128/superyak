# Trails, step 1: review of the plan

Date: 2026-10-25. Reviewer: a fresh agent on the Pi (`smart`). I took no part in writing the plan or its spec.

- Plan: `engram/docs/superpowers/plans/2026-10-25-trail-arrows.md` (untracked, 2,849 lines, read whole).
- Spec: `engram/docs/superpowers/specs/2026-10-25-trail-arrows-design.md`, revision 8 at `e737e02` (read whole).
- Also read: the consolidation log (the trails section, the cross-check, its fixes and the check of the fixes), the
  trails spec review's final check (FS1, FS2, FN1 to FN3), and the parts of the permissions and imprints plans that
  this plan uses or feeds.

I edited no file but this one. I changed no code. I ran no engram tests. I committed, pushed, merged, deployed and
posted nothing.

## Verdict

**Approve with changes.** It is not approved as written. Four must-fix items remain (MF1 to MF4). Each is local to
one or two tasks. Once they are fixed, nothing I found blocks the build.

What holds:

- **Coverage.** Every step-1 component of T 11 maps to a task. Every test group of T 12 maps to a task, as the
  plan's self-review table says. I checked each bullet of T 12 against the tests written in the tasks.
- **Order.** Permissions core, then imprints, then Part A, then Part B. Within Part B, no task uses a name a later
  task builds. Task 22's stub `evaluate` until Task 23 is said out loud.
- **Carried items.** XS2, YN1, YN5, YN7, YS1, XS3, XS1 with I6, XN2, FS1 and FN1 to FN3 each have a task or a gate.
  The "not this spec's" list matches the log.
- **Nothing live.** No task deploys, restarts a service or posts. Tests run under `tmp_path`. The Pi's user services
  are the five the plan names, and none runs engram (checked today).
- **Pi commands.** `uv` 0.12.23, `systemd-run` (systemd 252), Node 18.20.4 and no pnpm, and `/tmp` and `/var/tmp` on
  the NVMe root are all as the plan says. The test files the steps name all exist.
- **Code claims.** Nearly all are true (list at the end). The exceptions are below.

## Must-fix

**MF1. The observer pass would deadlock with recall once it is turned on** (Task 6 step 3, Task 7 step 3, Task 9).

- **What the plan says.** `observe_trails` runs "Under `self._lock`, as `observe_recall` is", and inside it calls
  `batch_scope()` once per 8 sessions and per 16 proposals. In the server, `batch_scope` is
  `_maintenance_step_scope(True)`, which takes `_server_lifecycle_lock` (`engram/server.py:1097-1112`).
- **Why it breaks.** Every tool call holds `_server_lifecycle_lock` for the whole call (`_server_operation`,
  `engram/server.py:653-683`). `recall` then calls `_category_observer.observe_recall`, which takes the observer's
  `self._lock` (`engram/category_evolution.py:1052-1053`). So recall takes lifecycle, then observer. The pass would
  take observer, then lifecycle. With a recall arriving between two batches, each thread waits on the other's lock.
  `log_outcome` (`observe_outcome`) and `reflect` (`report`) take the same order as recall.
- **Why no test catches it.** Task 9's server tests run maintenance inline (`guarded` false), where
  `_maintenance_step_scope` takes no lock. The deadlock appears only in the served process, the real case, once G4
  turns the pass on.
- **Fix.** Fix the lock order: enter `batch_scope()` first, then `self._lock` inside it, for each batch. Hold neither
  across a batch boundary. Derive and recount from `graph.db` outside both locks. Read `_current_trail_events()`
  inside a batch too, since it uses the observer's shared connection. Add a test with a real lock as `batch_scope`,
  held by a second thread that calls `observe_recall` during the pass. Both must finish within a timeout.

**MF2. The evaluation's test stores are too small for its own gates** (Tasks 23, 24, 25).

- **Why.** T 7 step 1 holds out the last 20% of closed sessions. Steps 2 and 6 score only held-out sessions, and a
  gate needs at least 30 of them. TR19 makes the held-out share `ceil(0.20 · n)`. So `sessions=80` gives at most 16
  qualifying sessions, and every gate on such a store is "not evaluable".
- **The tests that can't pass as written.**
  - `test_mf7_planted_ordered_routes_pass` expects `pass` on 80 sessions.
  - `test_mf7_popularity_without_order_fails_t_minus_s` expects `fail` on 80.
  - `test_w_planted_routes_ending_in_a_summary_pass` expects W to pass on 80.
  - `test_w_without_an_embedder_or_with_a_mismatched_one` expects the route gate to pass on 80.
  - `test_w_embeds_content_of_s_and_w_with_search_query_through_the_tools_function` uses 40 sessions. Both runs are
    "not evaluable", so W's numbers may not be in the report to differ.
  - `test_rmf2_co_retrieval_alone_fails_t_minus_s` and `test_w_goal_words_next_to_every_piece_fail_t_minus_n` would
    pass trivially, for the wrong reason.
- **The risk.** A builder working test-first, told to make these pass, may change the code instead: score every
  session, or drop the hold-out. That would void both gates.
- **Fix.** Use at least 150 sessions, for example 200, for every test that expects `pass` or `fail`, or reported
  numbers. Use 100 (20 held out) for the "fewer than 30" tests. "Days apart" over 200 sessions runs past October, so
  these stores need their own clock, not `at(day, …)`. Name in `planted_routes_store`'s line that `sessions` counts
  all closed sessions, of which 20% are scored.

**MF3. The "a quarter saving or equal length" detour test walks memories that don't exist** (Task 8,
`test_equal_length_or_a_quarter_saving_is_never_proposed`).

- **Why.** `detour_store` creates memories only on the long walk (`create=True`). The short walks `["x", "d", "e",
  "y"]` and `["p", "t", "r"]` name `d`, `e` and `t`, which nothing creates. By T 4 a single-target recall of a missing
  memory adds no touch and counts as skipped. So the short trails are `x → y` and `p → r`.
- **Failure.** `x → y` and `p → r` become roads (3 sessions, 4 days). Then `x a b c y` against `x y` saves 0.75, and
  `p q r` against `p r` saves 0.5. Both detours are proposed, and the test that expects none fails against a correct
  implementation.
- **Fix.** Pass `create=True` on the short walk too. Existing memories are reused, so the MF4 detour test is
  unchanged.

**MF4. `as_of` units disagree at the seam with the imprints plan** (TR1, TR20, Task 4, "Notes for the other
plans"; also Tasks 22 and 26).

- **Why.** TR1 makes every derivation's `as_of` integer microseconds. The imprints plan holds every time in integer
  UTC seconds (its "Times" rule and R2). Its admission calls `derive(conn, lane=lane, as_of=as_of)` with `as_of` the
  scope's `until`, in seconds. Its `test_count_matches_the_trail_functions` compares counts at `T1` and
  `T1 + 86_400`, in seconds. The trails plan says Task 4's `roads_and_trails` "has exactly that seam's shape". The
  notes tell the imprints plan to bind it directly. Neither names the unit.
- **Failure.** Bound directly, `as_of` = t₁ in seconds reads as about 30 minutes after 1970. Every row is newer than
  `as_of`, so there are no sessions, and N = 0 for every imprint. That 0 goes into `result.json`, `admitted`,
  `use-started`, `use-finished` and P 9.1's counted rows. The cross-plan test still passes, since 0 = 0 = 0. That is
  a silent wrong count in the owner's receipts.
- **The same gap in two more places.**
  - Task 22's `check_imprint(..., now)` compares `now` with the allow file's `valid_until`, which is UTC seconds
    (I 12's example, `1800727950`). The plan doesn't say `now` is seconds.
  - Task 26's `build_imprint` gives the imprints builder an `until`, also in seconds, while the test derives at
    `T1 + 2 * HOUR` in the trails support's units.
- **Fix** (Rio Grande's call).
  - Name the unit at the seam. Either `roads_and_trails` takes UTC seconds (`as_of_s`) and converts, or the notes
    say `_trail_derive` multiplies by 10⁶.
  - Make a wrong unit fail loudly. Every derivation raises `ValueError` for an `as_of` below 10¹⁴ µs (1973), and a
    Task 4 test passes a seconds value and expects the error.
  - Say that Task 22's `now` and `valid_until` are UTC seconds. Say that Task 26 converts t₁ for `until`.

## Should-fix

**SF1. `open_embedder` can't see an unreachable shared embedder** (Task 24).

- `RemoteEmbedProvider.__init__` only stores the socket path (`engram/embeddings.py:151-153`). It first connects on
  `embed`. So `create_embedding_provider()` succeeds with a socket nobody serves, and `open_embedder` returns it with
  `{"provider": "shared"}`. The `EmbedderUnavailableError` comes later, from the embedder check's first `embed`.
- `test_r19_a_socket_nobody_serves_loads_no_local_model` expects "not evaluable: no embedder". The plan's interface
  catches the error only at creation.
- **Fix.** Treat `EmbedderUnavailableError` from any embed in W, the check included, as "not evaluable: no embedder".
  Set the report's `embedder` to null then, as T 7 step 7 says for "W had none". Or have `open_embedder` probe once.

**SF2. Review Focus 1's test can't count to 2, and a malformed `context` would crash the read** (Tasks 1 and 2).

- `RecallRow` holds `t: int` and `target_ids: tuple[str, ...]`, so `read_sessions` must parse both. The two bad rows
  of `test_rf1_malformed_rows_are_skipped_and_counted` are dropped there. The test's `touches` helper passes no
  `counts` to `read_sessions`, so `session_touches` counts 0, not 2.
- Task 1 step 3 reads `json_extract(context, '$.session_id')` in SQL. On text that isn't JSON, SQLite raises
  "malformed JSON" and aborts the whole query (checked today on SQLite 3.40.1). Review Focus 1 says such a row is
  skipped and counted. No test has one.
- **Fix.** Pass one `Counter` to both calls in the helper. Guard the query with `CASE WHEN json_valid(context) …`, or
  parse in Python. Add a row with a malformed `context` to the test.

**SF3. A detour may name a road that has no stored cell yet** (Task 8 step 3).

- `find_detours(trail_set, lane, roads)` takes the roads eligible in `graph.db` mode. The pass proposes at most 64
  roads, so with a backlog some eligible roads have no cell yet.
- A detour over such a road fails: `validate_path` needs dimension-1 cells (`engram/categories.py:1724-1745`), and
  `propose` refuses a witness that doesn't exist (`engram/category_evolution.py:369-371`).
- **Fix.** Say that the pass searches detours over roads whose cells exist, proposed this pass or earlier.

**SF4. Task 9's order test patches the wrong `Storage`** (`test_the_pass_runs_before_prune_on_its_own_read_only_connection`).

- `env.store` seeds the store before `env.start()` runs `_init`, so it is the helper's own `Storage`. The server prunes
  through `server._storage`, a different object. Patching `env.store.storage.prune_decayed` records nothing, and
  `order.index("prune")` raises.
- **Fix.** Patch `storage.Storage.prune_decayed` on the class, or `server._storage` after init. The same applies to
  `spy(monkeypatch, "storage.Storage.open_read_only")`: the spy must stay a classmethod.

**SF5. The two cross-plan fixtures are only named** (Tasks 26 and 27).

- `build_imprint` must run the imprints plan's `plan` and `build`. Those need a permissions ledger, the owner's
  records and a scope.
- `imprint_fixture.run_use(during=…)` must run begin, `imprint.py use` with the real `trails.py`, and sync. It must
  shorten or withdraw while `trails.py` runs.
- Neither is sketched. These are the fixtures most likely to drift from the imprints plan.
- **Fix.** Give each fixture a few lines:
  - which imprints-plan functions it calls, in what order, and on which fixture root;
  - how `during` gets in, for example a `trails_cmd` wrapper that mutates and then execs `trails.py`;
  - that every time it hands the imprints code is in UTC seconds (MF4).

**SF6. The immutable imprint connection must load sqlite-vec** (Task 22).

- The plan opens an imprint "`mode=ro&immutable=1`, as `store_reader.connect(path, immutable=True)` does".
  `store_reader.connect` loads no extension (`engram/store_reader.py:44-55`). `--evaluate` reads `episode_vectors`
  and `semantic_vectors`, which are `vec0` tables, and would fail with "no such module: vec0".
- **Fix.** Load sqlite-vec on that connection as `paths.connect_ro` does, or use the imprints plan's
  `store_reader.connect(vec=True)` (its Task 32).

## Nits

- **N1. Cross-plan task numbers.** In the imprints plan, `count_roads_and_trails` is Task 35, not 34.
  `imprint.py use` is Task 38, not 37. XN2's `UnsetEnvironment` is Task 40, not 39 (plan lines 156, 228-231).
- **N2.** Task 13's `-k` filter doesn't select `test_one_text_with_every_example_keeps_at_most_8_each_once`.
- **N3.** `lane_filtered` is never defined. `test_mf8_…` pins it at 1, where counting per (touch, lane) gives 3.
- **N4.** Review Focus 4 lists a repeated id. `test_rf4_bad_memory_ids_are_ignored_not_fatal` has none.
- **N5.** T 6.6 says `receipt_id` is the row's id. Task 18's receipt test doesn't assert `rows[0]["id"] ==
  ctx["receipt_id"]`.
- **N6.** Task 10's angle test seeds one stream with 20261025, not `20261025 + case` as Global Constraints say.
- **N7. Commit commands.** They use paths relative to the worktree root, while the steps before them `cd` into
  `engram/`. Use `git -C <worktree>`. The shown messages also lack the attribution line Global Constraints require.
- **N8. Task 28 step 3.** `ant` is not installed on this Pi, so `ant auth status && …` exits 127 and the step is
  skipped, as intended. Say "missing or reports no credential". The call in TR21 matches the SDK's
  `messages.count_tokens(...).input_tokens`. The SDK reads `ANTHROPIC_API_KEY` and `ant auth login` profiles.
- **N9.** In `test_c3_a_re_laned_memory_in_an_unscanned_old_trail_never_reaches_a_work_route`, the patch of
  `MAX_PAIRS_SCANNED` does nothing, since no pass runs after it. Run a pass with the patch, then check the route.
- **N10.** TR13's patching works only if `category_evolution.py` reads `trails.MAX_PAIRS_SCANNED` at call time. A
  `from trails import …` would bind it once. Say so in Task 6.
- **N11.** In Task 17, `all(free_inside)` passes vacuously if the store has fewer than 64 sessions. Assert that the
  list is non-empty. `_server_lifecycle_lock` is an `RLock`, so `lock_is_free` must test from another thread.
- **N12.** `recall_with_tools` should use two identical stores. A first recall on a shared store changes access
  counts, and that can shift the second recall.
- **N13.** G6 should name T 14's open question, memories that mention other people, beside the owner's yes.
- **N14.** A report that must be byte-identical can't hold a wall-time-dependent count. Say that the evaluation's A*
  runs with `wall_s=None` and reports no wall-time truncations, or that their count is left out of the hashed report.
- **N15.** Task 9's gate-off cases pass `auto_commit = true` only. The observer turns any non-`True` value into
  false (`engram/category_evolution.py:905`). Only the server's `is not False` check enforces T 5's "exactly
  false". Add `auto_commit = 1` and `"false"`.
- **N16.** No test checks that `trail_next` reads only the first 3 stations (T 6.4), or that an answer says when it
  cut its text (`cut`, T 6.6). No observer-level test checks that two sessions an hour apart propose nothing (T 12,
  "Eligibility").

## Code and system claims checked today

True as written:

- `engram/storage.py:127-161` (`open_read_only`: `mode=ro`, `query_only`, sqlite-vec), `:59-61`, `:64-74`,
  `:1062-1071`, `:1656-1680` (`add_log_entry`, wall-clock timestamp).
- `engram/store_reader.py:44-55`. `engram/paths.py:397-409`, `:43-44`, `:348-354`.
- `engram/category_evolution.py`:
  - `:870-1470` (`CategoryObserver`; `timeout=0` at `:959-961`; `auto_commit is True` at `:905`;
    `allow_startup_consolidation` in the constructor);
  - `:1028-1031` (`_stable_id`), `:1043-1065`, `:1145-1157`, `:1508-1509`, `:2276`;
  - `:281`, `:408`, `:424` (`propose`, `latest_disposition`, `lineage`, with roles `input`, `output`, `witness`,
    `evidence`).
- `engram/categories.py:249-266`, `:1432` (nested transactions use savepoints), `:1522`, `:1664-1745`.
- `engram/server.py`:
  - `:38`, `:160-161`, `:171-207`, `:252-379` (fork hooks; `_fork_quarantined_resources`);
  - `:505-512`, `:653-697`, `:809-838`, `:1006-1025` (the observer gets explicit keywords, so a new `trails` field
    is harmless);
  - `:1097-1112`, `:1144-1290` (decay, then prune, then the rest, then `persistence-score-refresh`, then the save);
  - `:1418-1430`, `:2065-2090`, `:2186`, `:2376-2391`, `:3360-3367` (`reflect`), `:4002-4038`.
- `engram/reflection.py:53-77`, `:732-775`. `engram/config.py:146-189`, `:301-358` (an empty `config.toml` loads
  defaults). `engram/maintenance.py:24-80` (`note` merges into the step).
- `engram/embeddings.py:12` (read at call time), `:73-84`, `:200-207`.
- fastembed 0.7.4 in the `pr6-update` venv: `text/text_embedding_base.py:19`, `text/text_embedding.py:114-123` and
  `text/onnx_embedding.py:254` (FN2's call path).
- `engram/hooks/sleep.py:28-29` (inserts its directory into `sys.path`, imports `harness`) and `:44`
  (`CITING_OPERATIONS`). `engram/resources.py:13-30`. `engram/pyproject.toml:125`.
- `engram/tests/test_packaging.py:134-136` (every top-level `*.py` must be in the wheel), `:206-214`, `:225`
  (43 tools).
- `engram/tests/test_category_server.py:222-260`, `:240`.
- `engram/store_identity.py:113`. `engram/category_compile.py:195-197`.
- `engram/migrations/018_memory_lanes.sql:4-7` (lane is `NOT NULL`). `025_operation_log.sql` (columns
  `session_id`, `operation`, `target_ids`).
- Locked versions: numpy 2.4.3, sqlite-vec 0.1.7, fastembed 0.7.4, mcp 1.26.0 (`ToolManager._tools`,
  `list_tools`), anthropic 0.86.0 in the `llm` extra.
- The permissions plan's `ledger_path`, `Ledger.create/open_read_only/close/store_row/perform`, `Act`,
  `register-store` and `LedgerUnreadable`, with times in UTC seconds.
- The imprints plan's `Built`, `build`, R10, R15, R20, G13, `ORIGIN_IMPRINT` and the allow-file keys.

Not as the plan uses them: the lock order (MF1), the unit at the seam (MF4), the lazy remote provider (SF1),
`json_extract` on malformed JSON (SF2), and `store_reader.connect` without sqlite-vec (SF6).

## Response

Date: 2026-10-26. By the plan's writer, answering this review. I edited only the plan
(`engram/docs/superpowers/plans/2026-10-25-trail-arrows.md`) and this section, with targeted edits. I changed no
code, ran no test, and committed, pushed, merged, deployed and posted nothing. I checked again today the lines this
review cites for MF1, SF1, SF4 and SF6 (`server.py:653-683`, `:1097-1112`, `category_evolution.py:1043-1065`,
`:905`, `:1010-1020`, `embeddings.py:151-153`, `store_reader.py:44-55`, `storage.py:1656-1680`), and the imprints
plan's Tasks 7, 8, 15, 19, 21, 30, 31 and 35 to 40.

Every must-fix is applied. Every should-fix and nit is applied. Three are applied in part, for the reasons given.

### Must-fix

- **MF1, applied.** TR9 now fixes the lock order: each batch enters `batch_scope()` first, then `self._lock`, and
  neither is held across a batch boundary. Task 6 step 3 is rewritten. The derivation reads `graph.db` outside both
  locks. `_current_trail_events()` is read only inside a batch: the first batch reads it, picks the sessions and
  writes its first 8, so `test_the_pass_releases_the_barrier_between_batches` still sees `[8, 8, 4]`. An exception
  from `batch_scope()` ends the pass. Task 7 step 3 reads the events again in one batch, recounts outside the locks,
  and proposes in batches in the same order. Task 8 does the same for detours. New Task 6 test,
  `test_lock_order_a_recall_between_batches_never_deadlocks`: a real `RLock` is the barrier. After the first batch,
  the scope waits until a second thread holds the barrier inside a call to `observe_recall`. So the old order
  deadlocks every time, and the test fails on a 30 s join instead of hanging. Task 9 says its inline tests don't
  cover the served case and names this test. Task 6 now expects 8 tests.
- **MF2, applied.** Tasks 23 to 25 use 200 sessions for every test that expects `pass` or `fail` or compares
  numbers, and 100 for both "fewer than 30" tests. The co-retrieval and T − N tests now also assert verdict `fail`,
  so they can't pass because nothing was decided. Task 23 has a note on store sizes: `sessions` counts all closed
  sessions, `ceil(0.20 · sessions)` are scored, and session i walks at `on_day(i, 10)`, a clock that runs past
  October, with `END = T(on_day(400))`. Applied in part. Five tests keep their size, and none of them asserts a
  verdict that depends on the count:
  - the two r19 tests (40). Task 24 now fixes W's order: no embedder, then mismatch, then the count. So "no embedder"
    doesn't depend on the count;
  - `test_no_training_touch_at_or_after_the_cutoff_enters_t` and `test_steered_…` (80). They check the split, the
    graphs and the `steered` count, and assert no verdict;
  - `test_a_run_killed_by_the_memory_cap_writes_no_report` (40). It replaces `evaluate`.
- **MF4, applied.** I chose the review's second option: trails keeps one unit, microseconds, and the imprints plan's
  `_trail_derive` passes `as_of * 10**6`. New ruling TR22: `check_as_of` runs first in `read_sessions`, so every
  reader of a store refuses a `bool`, a non-`int`, or a value below `MIN_AS_OF_US = 10**14` (1973) with a
  `ValueError` that names microseconds. `TrailGraph.build` takes `as_of` as a label and checks nothing, so Task 10's
  `as_of = 0` stays valid. New Task 4 test, `test_an_as_of_in_seconds_fails_loudly`, covers `read_sessions`,
  `derive_trails`, `roads_and_trails` and `count_roads_and_trails`. The other places now name the unit:
  - the intro, Global Constraints (a new "Units at the seams" bullet), the XS2 row, "What this plan uses", "Notes for
    the other plans" (with `_trail_derive`'s one line and `roads_and_trails_by_hand`) and G12;
  - Task 22: `now`, `valid_until` and `still_valid`'s `now` are UTC seconds, and `main` passes `int(time.time())`;
  - Task 26: `until = T1 // 10**6`, and `T1` is a whole second.
  New Task 26 test, `test_xs2_the_admission_count_at_t1_is_the_trail_count_and_is_not_zero`. It calls the imprints
  plan's real `count_roads_and_trails` with `derive=None` at t₁ in seconds. It asserts that the result equals trails'
  count at `T1` in microseconds and is above 0. So a seconds bind fails here as well as in the imprints plan. Rio
  Grande can still choose the first option, seconds at the seam. That would change TR22 and Task 4 only.
- **MF3, applied.** `detour_store` passes `create=True` on the short walk too. The MF4 detour test is unchanged.

### Should-fix

- **SF1, applied.** Task 24 says the remote provider connects only on its first `embed`. `EmbedderUnavailableError`
  from any W embed, the embedder check's included, makes W "not evaluable: no embedder", and the report's `embedder`
  is then null. Both r19 tests and the no-embedder test assert `embedder is None`. I chose this over a probe in
  `open_embedder`, since the check's first embed already is one.
- **SF2, applied.** The `touches` helper passes one `Counter` to both calls. Task 1 step 3 reads the session id with
  `CASE WHEN json_valid(context) THEN json_extract(...) END` and counts a non-NULL context that isn't JSON. The rf1
  test adds a row with a malformed context and expects 3.
- **SF3, applied.** Task 8 step 3: `roads` is the set of road steps whose `trail step` cell is stored, read after the
  road proposals. A detour over a road with no cell waits for a later pass. New test
  `test_sf3_a_detour_waits_for_the_cells_of_its_roads`, which allows 1 road per pass. Task 8 now expects 18 tests.
- **SF4, applied.** The order test patches `storage.Storage.prune_decayed` on the class. The helper note says why,
  that `GATE_ON` leaves persistence off, and that `spy` keeps a classmethod a classmethod (`inspect.getattr_static`).
- **SF5, applied in part.** `build_imprint` is now sketched: the imprints plan's `plan_args` and `HOME` (its ledger,
  station context and scope), then `make_plan`, then `build`, on one root, all in seconds. D-I1 now names
  `make_plan`, not `imprint.plan`. `imprint_fixture` is sketched: build, then the peer's `admitted(...)`; per use,
  `station-imprint-use-begin`, then `imprint.use(..., trails_cmd=…, now=time.time)`, then `station-imprint-sync`.
  The end comes from the `use-finished` receipt. I did not follow the example "a wrapper that mutates and then execs
  `trails.py`". The start check would then read the changed allow file, and the run would end 0, not 3. Instead the
  wrapper imports `trails`, wraps `trails.evaluate` so the change lands between the start and end checks (as Task
  22's `mutate_then_report` does), and calls `trails.main`. Shortening and withdrawal call the peer's
  `shorten_imprint` and `withdraw_imprint`. One gap is new and named: admitting a real engram-built imprint without a
  browser needs the imprints plan's peer builder `admitted(...)` to take a built directory (D-I6). If it can't, that
  plan's owner adds the keyword. It is a test-only change there.
- **SF6, applied.** Task 22 and Global Constraints open an imprint with `store_reader.connect(path, immutable=True,
  vec=True)` (the imprints plan's Task 32), and say why. The cited lines are now `:44-55`.

### Nits

- **N1, applied.** Task 35, Task 38 and Task 40, in the carried items and "What this plan uses".
- **N2, applied.** Task 13's `-k` adds `every_example`.
- **N3, applied.** New ruling TR23 defines `lane_filtered`: touches of another lane removed from inside a lane's
  trail, with touches of that lane on both sides. MF8's test reads 1 under it. Counting per (touch, lane) would count
  every touch once for each other lane, and say nothing.
- **N4, applied.** The rf4 test repeats `"nope"` (5 ignored) and gives a real id twice (one station, 1 ignored). TR15
  and Review Focus 4 say a repeat is ignored and counted.
- **N5, applied.** Task 18 asserts `rows[0]["id"] == ctx["receipt_id"]`, and step 3 passes the receipt id as
  `add_log_entry`'s `id`.
- **N6, applied.** The angle test seeds each case with `20261025 + case` and names the seed in each failure.
- **N7, applied.** All 29 commit blocks use `git -C <worktree>`: `trail-derivation` for Tasks 1 to 4, `trail-step-1`
  after. Each commit carries the attribution as a `--trailer` (git 2.39.5 on the Pi). Global Constraints say a builder
  whose session gives a different attribution line uses that one.
- **N8, applied.** Task 28 step 3: "missing (exit 127, as on this Pi) or reports no credential".
- **N9, applied.** The c3 test runs a pass with `MAX_PAIRS_SCANNED = 0` and asserts it wrote nothing and counted
  unscanned pairs, before it checks the route.
- **N10, applied.** Task 6 step 3: `import trails`, and every constant read as `trails.NAME` when it runs.
- **N11, applied.** Task 17 seeds 130 sessions and asserts at least two checkpoints. `lock_is_free` tests from a
  fresh thread.
- **N12, applied.** `recall_with_tools` seeds a fresh store for each side from the same seed.
- **N13, applied.** G6 names T 14's question about memories that mention other people, and the default that holds
  until Andy answers.
- **N14, applied.** Task 23 step 3: every evaluation search passes `wall_s=None`, so the hashed report holds no count
  that depends on wall time. Task 25's byte-identical test now uses 200 sessions per lane, asserts the route gate
  passed, and spies `astar` to check `wall_s is None`.
- **N15, applied.** Task 9's gate-off cases add `auto_commit = 1` and `auto_commit = "false"`, each expecting the
  `skipped: auto_commit` note.
- **N16, applied.** Task 7 adds `test_mf1_two_sessions_an_hour_apart_propose_nothing` (now 14 tests). Task 18 adds
  `test_n16_next_reads_3_stations_and_an_answer_says_what_it_cut`, and its `-k` adds `n16`. Step 3 says which answers
  carry `cut`.

### Counts that changed

Task 6: 8 passed. Task 7: 14. Task 8: 18. Task 26: 7. Task 2's count is unchanged, since the rf1 test only changed.

## Re-check

Date: 2026-10-26. Reviewer: a fresh agent on the Pi (`smart`), re-checking in Andy's place. I took no part in
writing, reviewing or revising the plan or its spec.

- Plan: `engram/docs/superpowers/plans/2026-10-25-trail-arrows.md` as committed at `85595ed` (3,075 lines, read
  whole).
- Spec: revision 8 at `e737e02`. I read sections 4, 5, 6.4 to 6.6, 7 steps 7 and 8, 11, 12 and 13 closely, and the
  rest for context.
- Also read: this review and its response, the interface table, and the vision. From the imprints plan: Tasks 15,
  19, 30 to 32, 35, 37 to 40 and 49, and its R10, R15 and R20. From the permissions plan: Tasks 9 to 11 and its
  "Kept stable" list.

I edited no file but this one. I changed no code and ran no engram test. I committed, pushed, merged, deployed and
posted nothing. I ran one SQLite check in memory (N22).

### Verdict

**Approve.** No must-fix remains.

- MF1 to MF4 are resolved, and on both sides of each seam.
- I found three new should-fix items (RS1 to RS3), all in Tasks 26 and 27. Each makes a test fail loudly against a
  correct implementation, or makes a task wait on another plan. None can let a wrong number pass a test.
- Apply them before Task 26 starts. Nothing before Task 26 depends on them.

### The four must-fix items

**MF1, resolved.**

- **The order.** TR9 and Task 6 step 3 now enter `batch_scope()` first and `self._lock` inside it, per batch. They
  read `graph.db` outside both. Tool calls take the locks in the same order: `_server_operation` holds
  `_server_lifecycle_lock` for the whole call (`engram/server.py:653-683`). Then `observe_recall` takes the
  observer's `RLock` (`engram/category_evolution.py:909`, `:1052-1053`). `_current_trail_events()` is read only
  inside a batch. Tasks 7 and 8 keep the same order.
- **The new test.** I traced `test_lock_order_a_recall_between_batches_never_deadlocks` both ways.
  - With the old order, the observer lock is held for the whole pass. The pass waits on the barrier for batch 2, and
    the recall thread holds the barrier while it waits on the observer lock. Both threads are still alive after the
    30 s joins, so the assertion fails. The test doesn't hang.
  - With the new order, the recall runs between batches and both threads finish.
- **Threads.** The observer's connection has `check_same_thread=False` (`:959-961`). The test opens `s.ro()` inside
  the pass's own thread. So both threads use their connections legally.
- **The barrier test.** It still sees `[8, 8, 4]`, since the first batch writes 8.

**MF2, resolved.** I judge the five tests left small under "The items applied in part".

- Every test that expects `pass` or `fail`, or compares numbers, now uses 200 sessions, so 40 are scored.
- The two "fewer than 30" tests use 100, so 20 are scored.
- The co-retrieval and T − N tests now assert `fail`, so they can't pass because nothing was decided.
- `on_day` and `END = T(on_day(400))` give the large stores their own clock.

**MF3, resolved.** `detour_store` now passes `create=True` on both walks.

- With `d`, `e` and `t` created, the short trails are `x d e y` and `p t r`. The first saving is exactly 0.25, and the
  second pair has equal lengths, so nothing is proposed.
- The MF4 test's short walk creates no new memory.

**MF4, resolved, and both plans agree.**

- TR22's `check_as_of` runs first in `read_sessions`. So every reader refuses a `bool`, a non-`int`, or a value below
  10¹⁴ µs. The new Task 4 test passes three bad values to four readers.
- The imprints plan's Task 35 step 3 already says that `_trail_derive` passes `as_of * 10**6`.
- Task 26's new test calls the real `count_roads_and_trails` at t₁ in seconds. It asserts that the result equals
  trails' own count in microseconds and is above 0. So 0 = 0 = 0 can no longer pass.
- Task 16's ledger `now`, Task 22's `now` and Task 27's shortened `valid_until` are all seconds.

### The items applied in part

The response says three items are applied in part, but labels only two, MF2 and SF5. I read the third as MF4. There
the reviser chose the unit at the seam, which the review had left to Rio Grande.

**MF2's five small tests: enough.** None of them asserts anything that depends on how many sessions qualify.

- The two r19 tests assert "not evaluable: no embedder" and a null `embedder`. Task 24 now decides that before the
  count. W's order is: no embedder, then mismatch, then fewer than 30.
- `test_no_training_touch_…` checks the split and T's nodes.
- `test_steered_…` asserts `steered == 5`, a count over the 16 held-out sessions of 80, and the graphs' flags.
- The memory-cap test replaces `evaluate`.
- One thing to know, with nothing to fix: a CLI run takes `as_of` as the newest timestamp, so the last session is
  still open. That leaves 199 of 200 sessions closed, which still scores 40.

**SF5's `during` mechanism: enough, and better than the review's example.**

- Mutating and then exec'ing `trails.py` would let the start check read the changed allow file. A shortening still
  ahead would then end 0.
- Wrapping `trails.evaluate` puts the change between the start check and the end check, as Task 22's
  `mutate_then_report` does.
- The calls match the imprints plan: `imprint.use(..., now: Callable)` (its Task 38),
  `shorten_imprint(principal, request_id, valid_until, *, root)` (Task 31),
  `withdraw_imprint(principal, request_id, *, root)` (Task 30), and
  `station-imprint-use-begin --id --use --as --imprints-dir` (Task 37).

**SF5's D-I6 gap: not enough as written.** See RS2.

**MF4's choice of unit: enough.**

- Trails keeps microseconds inside, and every seam uses seconds. That is one rule, and the imprints plan already
  holds its side.
- A wrong bind fails loudly in two places: at admission, and in Task 26.
- Rio Grande can still choose the other option. As the response says, that changes only TR22 and Task 4.

### Should-fix (new)

**RS1. Task 27's socket test can't pass against a correct implementation**
(`test_unit_the_use_carries_the_socket_exactly_when_runtime_json_names_one`).

- `unit_command` "splits it as the shell would", so it returns a list.
- `superyak-peer station-imprint-unit-env` prints `-p UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET`. The imprints plan's
  own Task 40 test expects the split form, `["-p", "UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET"]`.
- `"-p UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET" in cmd` asks whether one list item equals a string with a space in it.
  The answer is always False, so the three cases without a socket fail.
- **Fix.** Assert the pair, for example
  `any(cmd[i:i + 2] == ["-p", "UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET"] for i in range(len(cmd)))`. Keep the
  `--setenv=…` check, which is one token.

**RS2. Task 27 can stall on D-I6, and this plan's own rules keep its builder from unblocking it.**

- Task 27 needs the imprints plan's peer builder `admitted(...)` to take an engram-built directory. If it can't, the
  plan says Task 27 "asks that plan's owner".
- But Part B may change only the files in "File Structure", and verification step 2 checks that. So the trails
  builder can't add the keyword to `peer/tests/imprint_support.py`, and Task 27 waits on another branch.
- One path needs no new keyword. The imprints plan's Task 49 admits a real engram-built imprint from start to end:
  `station_decide`, `station_imprint_admit_begin`, `imprint.py admit` with its `PEER_VERIFY`, then
  `station_imprint_sync`. Its one browser step is a test helper.
- **Fix.** Name that path as Task 27's fallback. Or have Rio Grande add the keyword to the imprints plan's Task 37
  tests before Part B starts.
- **Also.** Give `build_imprint` its own `dest`, such as `tmp_path / "built"`, not the station root `R`. As written,
  `HOME(R)` puts the owner's side, `home/imprints/<id>/`, inside the station's imprints directory.

**RS3. Task 26's fixture must keep every source row more than an hour before t₁.**

- The imprints spec decides "closed at t₁" from rows before t₁. It reads more row kinds than T does: every
  `memory_log` event type, and `operation_log` (interface row 16).
- Even with `route`, a session still open at t₁ ships with no session id and no log rows.
- The fixture's note says only "no source row at or after t₁" (XS1). Take a session whose newest row, of any kind,
  falls in [t₁ − 1 h, t₁). It is open at t₁ for the imprint, but closed at `T1 + 2 * HOUR` for the source.
- Two tests would then fail against a correct implementation: `test_closed_sessions_keep_session_ids_and_wrote_touches`
  and `test_lane_filtered_recalls_keep_their_touches_…`. The subset test still passes.
- **Fix.** Say that `synthetic_source` writes every row, of every kind, before t₁ − 1 h, and assert it in the fixture.
  Or compare only the sessions that are closed at t₁ by the imprints spec's rule.

### Rulings

I confirm all 23 rulings and four additions the plan makes without a number. I veto none. Reasons are given only where
a ruling changed, is new, or needs a word.

**Confirmed as the first review found:** TR1 to TR8, TR10 to TR14, TR16 to TR19 and TR21. TR1's parse holds:
engram writes `datetime.now(timezone.utc).isoformat()` (`engram/storage.py:55-56`), so every stored time carries
its offset.

**Changed or new:**

- **TR9 (changed): confirmed.** It matches the code's lock order (MF1 above).
- **TR15 (extended by N4): confirmed.** Ignoring a repeat is what lets a repeated real id give one station, and it
  only narrows.
- **TR20: confirmed.** It counts full trails once per session and roads by T 5's eligibility, and counts no detours.
  That matches the permissions spec's kinds and the imprints plan's `derive` seam.
- **TR22 (new): confirmed.** T fixes no unit. Refusing a seconds value turns MF4's silent zero into a `ValueError` at
  admission. Two edges are nits (N18).
- **TR23 (new): confirmed.** It counts what the filter changed, and it pins MF8's test at 1. No touch is counted
  twice: `revisit_trail` is built from the filtered full trail and takes no `counts`.

**Unnumbered additions, confirmed:**

- **W's verdict order (Task 24):** no embedder, then mismatch, then fewer than 30. T 7 step 8.2 settles the embedder
  before any scoring, and the r19 tests need this order. Give it a number (N19).
- **The imprint connection loads sqlite-vec:** `store_reader.connect(path, immutable=True, vec=True)` (Global
  Constraints, Task 22). T 11 says "as `store_reader.connect(path, immutable=True)` does", but that call loads no
  extension (`engram/store_reader.py:44-55`), and `--evaluate` reads `vec0` tables. The plan keeps the spec's intent.
  Carry the words to T's next revision (N27).
- **Which answers carry `cut` (Task 18):** every answer except errors, the not-ready note and `stale`. T 6.6: "the
  answer says so when it cuts".
- **The receipt's row id is the receipt id:** it is passed as `add_log_entry`'s `id`, the method's first parameter
  (`engram/storage.py:1656-1680`). T 6.6: "`receipt_id` is the row's id".

### Names and task numbers across the plans

I checked them against both other plans as they stand today.

- **Imprints plan.** These match:
  - `make_plan` (Task 15) and `build(plan_id, *, home, now) -> Built` (Task 19);
  - `withdraw_imprint` (Task 30), `shorten_imprint` (Task 31) and `store_reader.connect(..., vec=True)` (Task 32);
  - `count_roads_and_trails(conn, *, lanes, as_of, derive=None)` and `_trail_derive` (Task 35);
  - `station-imprint-use-begin` (Task 37), `imprint.use` (Task 38) and the sync (Task 39);
  - `station-imprint-use-run` and `station-imprint-unit-env` (Task 40, R20), and XN2 (R15).

  One thing does not match: the unit-env output form against Task 27's assertion (RS1).
- **Permissions plan.** These match, and that plan's "Kept stable" list names each one for this plan:
  - `ledger_path`, `Ledger.create(engram_home, owner_handle, *, now)`, `open_read_only` (raising
    `FileNotFoundError` or `LedgerUnreadable`) and `close` (Task 10);
  - `perform(act, *, actor, channel, now)`, `register-store` with `instance_id`, `name`, `owner`, `place` and
    `imprint_of`, and `store_row` (Task 11);
  - `Act(kind, args)` (Task 9), and the `permit` and `permissions` tools (Task 23).
- **Test counts.** Every stated count agrees with the tests written: 6, 7 and 5 for Tasks 1 to 3; 8, 14 and 18 for
  Tasks 6 to 8; 5, 6 and 3 for Tasks 10 to 12; 6, 6 and 5 for Tasks 14 to 16; 5 for Task 21; 8 for Task 23; and 7 for
  Task 26.
- **`-k` filters.** Each selects its task's tests. Task 7 step 2's `mf1` also selects Task 6's `test_rmf1_…`, which
  does no harm.

### Tests: real assertions

Every new or changed test asserts a value that a wrong implementation would miss:

- the lock-order test: no deadlock, and 20 events;
- the hour-apart test: 2 events, no rewrite, no proxy, and 1 step not eligible;
- the SF3 test: after one pass, no detour and no error; after four passes, four roads and one detour;
- the seconds test: three bad values for each of four readers, then the right value gives 4;
- the admission-count test: the two counts are equal and above 0;
- the receipt-id test;
- the N16 test: 3 stations, and `cut` names what was cut;
- the rf4 test: 5 ignored, and a repeat counts once.

No assertion is a placeholder. The one that can't pass at all is RS1's.

### Nits

- **N17.** The response says three items are applied in part, but labels only two.
- **N18.** `count_roads_and_trails(conn, as_of, lanes=())` sums nothing and never reaches `read_sessions`, so it
  takes a seconds value without complaint. Call `check_as_of` at the top of each public reader. Optionally, an upper
  bound such as 10¹⁷ µs would also catch nanoseconds.
- **N19.** W's verdict order is a choice T leaves open. Give it a ruling number (TR24).
- **N20.** TR1's `rows_unparsed` is counted, but it isn't in Task 7's report block, so it never reaches `reflect`.
  Review Focus 1 calls it counted. Add it to the block, or say where it shows.
- **N21.** `test_sf3_…` patches `MAX_ROADS_PER_PASS` under a "TR13" comment, but doesn't first assert the constant's
  value, as TR13 asks.
- **N22.** On this Pi's SQLite 3.40.1, `json_valid(NULL)` returns 0, not NULL (checked today in memory). Task 1 step
  3 already counts only "a context that is not NULL and not valid JSON". Say in the step that the code must test
  `context IS NOT NULL` explicitly.
- **N23.** In Task 27, a withdrawal removes the state directory, so the write of `result.json` in `imprint.use`'s
  `finally` raises. `run_use` must catch that to report `trails_exit = None`.
- **N24.** `build_imprint` passes `until=t1_s` but not the plan's `now`.
  - Say that the plan's `now` is also t₁ in seconds, so `until` is never after `now`.
  - The imprints plan's `make_plan` takes `home` and `now` as keyword-only arguments, so that plan's own
    `make_plan(*plan_args(…))` can't pass them either. That is the imprints plan's to fix.
  - The imprints plan never defines `roads_and_trails_by_hand`, which "Notes for the other plans" asks to convert.
    A helper that doesn't convert fails loudly, so this is only a note for that plan.
- **N25.** Task 28 commits this plan's own file, which "File Structure" doesn't list, so verification step 2 would
  flag it. List it there.
- **N26.** The pass's read-only connection isn't registered with `_register_server_cleanup`, while the build's is
  (Task 17). T 5 doesn't require it, but the risk is now plainer:
  - The derivation runs outside the barrier, and `_before_server_fork` takes only the barrier
    (`engram/server.py:250-254`).
  - So a fork can come in the middle of a derivation, and the child won't quarantine that connection.
  - Registering it as Task 17 does costs one line.
- **N27.** Add to G9 for T's next revision: T 11's "as `store_reader.connect(path, immutable=True)` does" needs
  `vec=True`.

### Code and system claims checked today

True as the revised plan uses them:

- **`engram/server.py`:**
  - `:250-254` (`_before_server_fork` takes the lifecycle lock), `:653-683`, `:1097-1112`;
  - `:1175-1185` (with persistence off, prune calls `_storage.prune_decayed`);
  - `:1299` (`from storage import Storage`, so patching the class reaches `server._storage`);
  - `:2089-2090`, `:4023-4033`.
- **`engram/category_evolution.py`:**
  - `:905` (`auto_commit is True`), `:909` (the observer's lock is an `RLock`), `:959-961`;
  - `:1010-1020`, `:1043-1065`, `:369-371`;
  - `:1145-1157` (proxy cells hold `external_id`, so `road_set(obs)` can map cells back to memory ids);
  - `:1338-1408` (`report()` has `last_error`).
- **`engram/categories.py:1724-1745`** (`validate_path` needs dimension-1 cells).
- **`engram/embeddings.py`:**
  - `:12`;
  - `:73-84` (the in-process model loads in `__init__`);
  - `:151-153` (the remote client stores only the path);
  - `:179-196` (`_call` turns `OSError` into `EmbedderUnavailableError`);
  - `:200-207`.
- **fastembed 0.7.4.** With `local_files_only` and an empty cache it raises `ValueError` ("Could not load model … from
  any source", `common/model_management.py:473`). So `open_embedder`'s `ValueError` catch is the offline path.
- **`engram/store_reader.py:44-55`**, and **`engram/storage.py`** `:55-56`, `:127-128` and `:1656-1680`.
- **`engram/config.py:301-358`.** The loader doesn't coerce types, so `auto_commit = 1` and `"false"` reach the server
  as written, and the observer reads both as false.
- **SQLite 3.40.1.** `CASE WHEN json_valid(x) THEN json_extract(x, …) END` on malformed text returns NULL and doesn't
  abort the query.

Not as the plan uses them: nothing in engram's code. The two mismatches are with the imprints plan: the unit-env
output form (RS1) and `make_plan`'s keyword-only arguments (N24).
