# Trails, Step 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One engram store records the routes its own sessions walked as trails, firms repeated steps into pending
roads and detours, measures whether trail routes beat order-free and similarity-only routing, and, only after both
gates pass and the owner says so, offers three read-only tools that locate an agent, route it to a goal in words and
tell it what other sessions did next. Every part is off by default.

**Architecture:** `engram/trails.py` holds the pure parts: touches, trails, steps, support, roads, detours, Kahan
angles, the A* of 6.1 and 6.3, locate, forward lookup, the short-answer builder, the tool graph, both gates, the
imprint check and a read-only CLI. It reads a `sqlite3` connection it is given and writes nothing. The v2 observer
(`category_evolution.py`) gains a gated pass that writes trail events and pending road and detour rewrites. The
server (`server.py`) runs that pass before `prune`, builds the tool graph as the last maintenance step, and registers
the three tools only when `[trails] tools` is exactly `true`. Small hooks go into `storage.py`, `config.py`,
`embeddings.py` and `reflection.py`.

**Tech Stack:** Python (the interpreter `uv run --locked` picks from engram's `uv.lock`), standard library, numpy
2.4.3, `sqlite3` with sqlite-vec 0.1.7 for vectors, fastembed 0.7.4 for the in-process model, pytest, uv. Built and
tested on the station's Raspberry Pi 5 (`smart`).

**Spec:** `engram/docs/superpowers/specs/2026-10-25-trail-arrows-design.md`, revision 8, at `e737e02`, cited below as
"T" with its section numbers. Also read: the contract `docs/city-rail-vision.md`; the interface table
`docs/superpowers/reviews/2026-10-25-city-rail-interfaces.md` ("row N"); the consolidation log
`docs/superpowers/reviews/2026-10-25-city-rail-consolidation.md`; the permissions plan
`docs/superpowers/plans/2026-10-25-permissions-by-place.md` ("P plan", its tasks by number); the imprints spec
`engram/docs/superpowers/specs/2026-10-25-store-imprint-design.md`, revision 6 ("I").

**Scope.** T's step 1 only: sections 4 to 7, with 10 to 12. Sections 8 and 9 are later specs; nothing here crosses a
store boundary. Every gate stays off. Nothing touches the station: no deploy, no service restart, no post.

**Two parts, two branches.**

- **Part A, the shared derivation** (Tasks 1 to 4): sessions, touches, trails, steps, support, roads, and
  `roads_and_trails`, which the imprints plan's admission calls to count R(I) (I 10, "Counting R(I)"; the
  cross-check's XS2). Part A depends on nothing in the other two plans. Worktree
  `/home/andy/superyak/.worktrees/trail-derivation`, branch `trail-derivation`, made from `main` once imprints has
  merged (or earlier, under Gate G2). It merges on its own, so the imprints plan's real-function test can run.
- **Part B, the rest of step 1** (Tasks 5 to 29). Worktree `/home/andy/superyak/.worktrees/trail-step-1`, branch
  `trail-step-1`, made from `main` once permissions core, imprints and Part A have merged.

The build order holds: permissions core, then imprints, then trails step 1 (Part A, then Part B). I 10 derives R(I)
"with the trail spec's own functions"; the imprints plan reaches them through a seam, `derive(conn, lane=lane,
as_of=as_of)` (its R10), and fails closed until `trails` can be imported, so no imprint with `route` is admitted before
Part A is on the Pi (its gate G13). Task 4's `trails.roads_and_trails` has that seam's shape, but not its unit: the
imprints code holds UTC seconds, and every trails derivation takes microseconds. So the imprints plan's one adapter,
`_trail_derive`, multiplies `as_of` by 10⁶, and a derivation given seconds raises `ValueError` (TR22). Building Part A
earlier, so that such imprints can be admitted sooner, is Rio Grande's option (Gate G2), not a need.

## Global Constraints

- **Off by default.** `[category_evolution] trails = false`, `[trails] tools = false`, `[trails] lanes = ["work"]`.
  Only an exact boolean `true` turns a gate on, tested with `is True` (T 5, 6.6). The pass also needs
  `[category_evolution] enabled is True` and `auto_commit is False` exactly (T 5). The tools need nothing from
  `[category_evolution]` (T 6.6).
- **Nothing live.** No step deploys, restarts a service, posts to the station, reads a real `~/.engram`, or runs
  against a real store. Every test sets `ENGRAM_HOME` and paths under `tmp_path`. Deploy and live acts are gates.
- **Read-only.** Every reader of a `graph.db` opens it with `Storage.open_read_only` (`engram/storage.py:127-161`) or
  `file:…?mode=ro` with `PRAGMA query_only=ON`. An imprint opens with `mode=ro&immutable=1` and sqlite-vec loaded,
  through the imprints plan's `store_reader.connect(path, immutable=True, vec=True)` (its Task 32). Without `vec=True`
  it loads no extension (`engram/store_reader.py:44-55`), and `--evaluate` reads `vec0` tables. The tools' one write
  is the `route_shown` row (T 6.6, R8). The observer pass writes only to `categories_v2.db`.
- **No wall clock in a derivation.** Every derivation takes `as_of` as integer microseconds since the epoch, UTC
  (Ruling TR1), and refuses a value in seconds (TR22). The clocks that exist: the route tool's 500 ms bound, the
  evaluation's `--deadline`, and the imprint check's `now` (UTC seconds), each passed in (`clock=`, `now=`) so tests
  inject them.
- **Units at the seams.** Inside `trails.py`, times are microseconds. Every time handed to or taken from the
  imprints and permissions code is integer UTC seconds, as those plans hold them (TR22).
- **Names, verbatim from T.** Module `engram/trails.py`; method `CategoryObserver.observe_trails(graph_conn, as_of)`;
  tools `trail_locate`, `trail_route`, `trail_next`; `Storage.search_fts_ids(table, phrase, limit)`;
  `NomicEmbedProvider(local_files_only=...)` and `create_embedding_provider(local_files_only=...)`; the `Reflector`
  keyword `trails_reporter`; config `[category_evolution] trails`, `[trails] tools`, `[trails] lanes`; event kind
  `trail_observed`; `rule_version` `"trail-v1"`; payload keys `session_id`, `lane`, `context_id`, `truncated`,
  `ambiguous_used_recalls`, `rule_version`, `touches`, and per touch `memory_id`, `layer`, `kind` (`wrote` |
  `cited`), `at`, `recall_id`, `rank`, `suggested`; rewrite id kind `trail-road`; cell contents `trail step` and
  `two routes`; receipt `event_type = 'route_shown'`, `layer = 'trail'`, context keys `receipt_id`, `session_id`,
  `tool`, `lane`, `as_of`, `graph_digest`, `rule_version`; ends `goal`, `at_goal`, `no_goal`, `no_route`,
  `truncated`, `stale`; `why` values `given`, `words`, `near`; `via` values `entry:given`, `entry:words`,
  `entry:near`, `road`, `footpath`; source keys `laid_by`, `allowed_by` (`"own store"` in step 1), `receipt`;
  answers `{"error": "lane not enabled"}`, `{"error": "lane not enabled: <lane>"}`,
  `{"error": "embedder unavailable"}`, `{"note": "trail graph not ready"}`, `{"end": "stale"}`,
  `degraded: ["embedding"]`, `{"skipped": k}`; counts `ambiguous_used_recalls`, `steps_supported_not_eligible`,
  `pairs_not_scanned`, `lanes_invalid`, `ignored`, `ended_here`, `ends_unknown`, `steered`, `empty_text`,
  `truth_inside_entries`, `no_stored_vector`; verdicts `"not evaluable"`, `"not evaluable: no embedder"`,
  `"not evaluable: embedder mismatch"`, `"not evaluable: limit"`, `"not evaluable: too large"`; exit status 3,
  `allow changed`; the CLI flags of T 11 exactly.
- **Constants (T 10), as `trails.py` module constants:** `CLOSED_IDLE_US = 3_600_000_000`;
  `SESSIONS_PER_PASS = 64`; `SESSIONS_PER_BATCH = 8`; `PROPOSALS_PER_BATCH = 16`; `MAX_PAIRS_SCANNED = 16_384`;
  `MAX_ROADS_PER_PASS = 64`; `MAX_DETOURS_PER_PASS = 32`; `MAX_TOUCHES = 512`; `ROAD_SUPPORT = 2`;
  `PERSISTENCE_UNIT_S = 604_800`; `PERSISTENCE_MIN_S = 60_480`; `DETOUR_SAVING = 0.25`; `DETOUR_MAX_STEPS = 8`;
  `ROAD_EVIDENCE = 31`; `DETOUR_EVIDENCE = 15`; `DETOUR_WITNESSES = 16`; `ROAD_INDEX_EVENTS = 10_000`;
  `MAX_EXPANSIONS = 10_000`; `ROUTE_WALL_S = 0.5`; `BASELINE_NEIGHBORS = 8`; `HOLDOUT = 0.20`;
  `MIN_QUALIFYING = 30`; `MIN_REACH = 0.20`; `MIN_DELTA_F1 = 0.10`; `SHUFFLES = 10`; `BOOTSTRAP = 10_000`;
  `MAX_ENTRIES = 6`; `MAX_WORD_STATIONS = 2`; `MAX_ANCHORS = 8`; `ANCHOR_CHARS = (3, 128)`; `FTS_HITS = 64`;
  `MAX_TEXT = 4_000`; `GOAL_DELTA = 0.10`; `R_MAX = math.acos(0.60)`; `FORWARD_STATIONS = 3`; `FORWARD_KEEP = 2`;
  `FORWARD_SESSIONS = 256`; `MAX_STOPS = 64`; `SHOWN_EACH_END = 6`; `SUMMARY_BYTES = 160`; `ANSWER_BYTES = 6_000`;
  `MAX_IDS = 6`; `RECHECK_ROWS = 70`; `RECEIPT_HEX = 8`; `TOOL_SESSIONS = 4_096`; `TOOL_NODES = 20_000`;
  `TOOL_STEPS = 262_144`; `TOOL_MEMORY_TARGET_MB = 256`; `BUILD_BATCH = 64`; `VECTOR_BLOCK = 4_096`;
  `B_BLOCK = 1_024`; `N_EMPTY_SIZE = 4`; `EMBED_CHECK_N = 32`; `EMBED_CHECK_MIN = 0.99`; `DEADLINE_S = 1_740`;
  `EVAL_MAX_NODES = 20_000`; `EMBED_MODEL = "nomic-ai/nomic-embed-text-v1.5"`.
- **No test loads the real model or reaches the network.** This Pi holds the model in `~/.kairos/models/fastembed`.
  Every test module that runs `--evaluate` or `open_embedder` uses the fixture `trails_support.no_real_model`
  (`pytestmark = pytest.mark.usefixtures("no_real_model")`), which points `embeddings._CACHE_DIR` at an empty
  `tmp_path` directory and unsets `ENGRAM_EMBEDDER_SOCKET`. Server tests use a fake provider, as
  `tests/test_category_server.py:240` does. Only Task 28's Pi measurements load the model, on purpose.
- **Test command on this Pi** (`smart`, Raspberry Pi 5, 16 GB, 4 cores; `/tmp` and `/var/tmp` are on disk, checked
  2026-10-25), from the task's worktree's `engram/` directory, written out in full in every task:
  `PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider <tests>`.
  The first run creates the git-ignored `engram/.venv` from `uv.lock`.
- **Packaging.** `trails` joins `[tool.setuptools] py-modules` in `engram/pyproject.toml` in Task 1:
  `tests/test_packaging.py::test_wheel_contains_runtime_modules_and_assets` requires every `engram/*.py`.
- **Existing tests stay unchanged.** No task edits an existing test file. New tests go in new files.
  `tests/test_packaging.py` asserts 43 tools after `server._init()` (`:225`); this plan keeps that, since the trail
  tools register only in `_initialize_pre_serving`.
- **Tests first.** Each test is named, written first and seen failing first. Random tests seed
  `numpy.random.default_rng(20261025 + case)` and name the seed and case in every failure message.
- **Commits.** One per task, on that part's branch only, ending with the session's attribution line. No push, merge
  or deploy inside any task. The test steps `cd` into `engram/`, so every commit command names its worktree with
  `git -C <worktree>` and the paths stay relative to the worktree root. The commands below show this plan's writer's
  attribution line as a `--trailer`. A builder whose session gives a different attribution line uses that one.

## Rulings

Choices T leaves to the builder (its section 13) or does not fix. A reviewer checks each; Andy can veto any.

| # | Ruling | Why |
|---|---|---|
| TR1 | Every stored timestamp is parsed with `datetime.fromisoformat` into integer microseconds UTC (`parse_time`). A row whose time doesn't parse, or whose `target_ids` or `context` isn't the JSON its column needs, is skipped and counted as `rows_unparsed`. "Whole seconds" is the microsecond difference floored to seconds. | Engram writes `isoformat()`, which drops `.000000` at a whole second, so string order is fragile; T 4 needs arithmetic on `as_of − 1 h`. |
| TR2 | `trails.CITING_OPERATIONS` is read from `resource_path("hooks/sleep.py")` with `ast`: the literal tuple assigned to `CITING_OPERATIONS`. The hook is never executed. | T 4 says "imported from `hooks/sleep.py`". `hooks/` is no package, executing the hook inserts its directory into `sys.path` and imports `harness`, and in a wheel it lives in `share/engram/hooks` (`engram/pyproject.toml:125`), which `resource_path` finds (`engram/resources.py:13-30`). |
| TR3 | An instinct target is an id present in `instincts` now. A target in none of `episodes`, `semantics` and `instincts` "no longer exists". `skipped_targets` counts each such non-instinct target of a used recall once. | T 4 drops instincts first and counts missing targets; a recall row records no per-target layer (`engram/server.py:2380-2386`). |
| TR4 | A cited touch's `layer` is `episode` or `semantic`, by which table holds the id now. A wrote touch is `episode`. A touch's `at` is the source row's timestamp text, unchanged. Its `rank` is its index in the row's stored `target_ids`, instincts included. | T 4: "Its rank is its position in `target_ids`, the delivered order." |
| TR5 | For span (T 4) each supporting session contributes the time of its earliest qualifying `A → B` across its full and revisit trails. | T says "the latest supporting session's step time minus the earliest one's", and a session can hold the step twice. |
| TR6 | `canonical(value)` is `json.dumps(value, sort_keys=True, separators=(",", ":"))`, the form `category_evolution._canonical_json` uses (`engram/category_evolution.py:1508-1509`). A trail digest is the SHA-256 hex of `canonical(touches)`. `graph_digest` is the SHA-256 hex of `canonical({"as_of": …, "rule_version": "trail-v1", "digests": sorted(current trail digests)})`. | T 5 and 6.6 name SHA-256 over canonical JSON. |
| TR7 | Stable ids use `CategoryObserver._stable_id(kind, material)` (`engram/category_evolution.py:1028-1031`): event `("trail", {"session_id", "lane", "digest", "supersedes"})`; road cell `("trail-road-cell", {"lane", "source", "target"})`; road rewrite `("trail-road", {"cell_id"})`, as T fixes; detour cell `("trail-detour-cell", {"lane", "long", "short"})`; detour rewrite `("trail-detour", {"cell_id"})`. | T 5 fixes the road rewrite's form and the material of the others. |
| TR8 | A pair whose old event exists but whose trail has gone (fewer than two touches now) gets a new event with `touches: []`, so recounting sees it gone. | T 5 recounts support from current events. |
| TR9 | `observe_trails(graph_conn, as_of, *, batch_scope=contextlib.nullcontext, own_session_id=None)`. The server passes `batch_scope=lambda: _maintenance_step_scope(guarded)`. The keyword-only arguments keep T's two positional ones. Lock order: each batch enters `batch_scope()` first and the observer's `self._lock` inside it, the order every tool call takes them. Neither is held across a batch boundary, and `graph.db` is read outside both. | T 5: the barrier is taken "only per batch, as a yield point"; T 4 excludes the running server's own session. A tool call holds the lifecycle barrier for the whole call (`engram/server.py:653-683`), then `recall`, `log_outcome` and `reflect` take `self._lock` (`engram/category_evolution.py:1052-1053`). The reverse order in the pass would deadlock a recall that arrives between batches (the plan review's MF1). |
| TR10 | The pass's counts live in the observer's memory for its last pass and appear in `report()["trails"]`, with `trail_events` (the stored total) so the 10,000-event index rule is visible. | T 5 "Diagnostics": counts only. |
| TR11 | Detour search enumerates candidate routes from travelled runs only: every contiguous run of 1 to 8 road steps, none co-cited or suggested, with no repeated memory, in each current full or revisit trail, keyed by its endpoints. Pairs under one key are tried in order of `(lane, X, Y, R1 ids, R2 ids)`. The algorithm is in Task 8. | T 5 asks that both routes were travelled; enumerating from trails bounds the search by what sessions did. |
| TR12 | The pass and the build rank sessions by newest row, then session id; pairs inherit their session's rank. | T 4 and 5 rank "by newest row" and need a total order for determinism. |
| TR13 | The bounded-count tests (16,384 pairs; 4,096 sessions, 20,000 nodes, 262,144 steps) assert each constant's value, then run with the module constant patched small. Task 28 exercises the real bounds on the Pi. | A 16,385-pair store per test run would take minutes on the Pi, and T 12's Pi measurement already builds one at the bounds. |
| TR14 | Tool registration is `_register_trail_tools()` in `_initialize_pre_serving`, after `_init` and before `_start_deferred_sleep_maintenance()`, through `_server_tool(name=…, description=…)`. | T 6.6: after config loads and before `mcp.run()`; the build step must see the registration. |
| TR15 | Argument errors read `{"error": "at most 6 memory ids"}`, `{"error": "give context or memory ids"}`, `{"error": "give a goal"}`, and for a bad lane `{"error": "Invalid lane: '<lane>'"}`, as recall words it (`engram/server.py:2089-2090`). A `memory_ids` item that is not a non-empty string of at most 64 characters is ignored and counted in `ignored`. So is a repeat of an earlier item, and then an id that is no node of the lane's graph. | T 6.6 says "an error" and "ignored" without fixing words. |
| TR16 | An answer that names nothing carries no `sources` and writes no receipt. `truncated` and `stale` name nothing. `no_goal` names only `nearest` and `no_route` only `nearest_goal`, when there is one. With no entry station, every tool answers `{"tool", "lane", "as_of", "stations": [], "note": "nothing on the trails is near this context"}` (6.2). | T 6.6: "An answer naming nothing writes none." |
| TR17 | Answer keys beyond T's example: `trail_locate` gives `stations` of `{id, layer, summary, why, angle, through, src}`; `trail_next` gives `stations` of `{id, layer, summary, why, angle, src, next, ends, ended_here, ends_unknown}`, with next items `{id, layer, summary, kind, sessions, last, src}` plus `flag` (`co-cited`, `suggested` or `co-cited, suggested`) when sessions is 0, and ends `{id, layer, summary, sessions, median_hops, src}`; `trail_route` adds `nearest` for `no_goal` and `nearest_goal` for `no_route`. Optional keys: `cut` (`["context"]`, `["goal"]` or both), `ignored`, `degraded`. Dates are `YYYY-MM-DD`; `as_of` is `YYYY-MM-DDTHH:MM:SSZ`. | T 6.5 fixes `trail_route`'s shape by example only. |
| TR18 | A summary's "compact JSON form" is the JSON string literal, quotes included. Control characters are Unicode category `Cc`, removed after whitespace is collapsed with `str.split`. Lines split with `str.splitlines`. | T 6.5. |
| TR19 | The held-out share is the last `ceil(0.20 · n)` closed sessions by first touch in the lane, ties by session id. A session's own hops from `s` to `g` is the index of its last `g` minus the index of its first `s` in its lane trail. The bootstrap interval is `numpy.quantile(means, [0.025, 0.975])`, default method. | T 7 steps 1, 5 and 6 leave these open. |
| TR20 | `roads_and_trails(conn, *, lane, as_of)` is, for one lane, the number of current full trails, one per session with at least two touches in that lane, plus the number of distinct steps of that lane that are roads under T 5's eligibility in `graph.db` mode. `count_roads_and_trails(conn, as_of, *, lanes=LANES)` sums it over `lanes`. Detours are not counted, since the permissions spec's kinds are memory, road and trail. | XS2 needs one number N for the imprints plan (I 10), whose seam sums `derive(conn, lane=lane, as_of=as_of)` over the scope's lanes (its R10). T is the source of truth for trails. |
| TR21 | The token ratio of T 6.5 is measured with `anthropic.Anthropic().messages.count_tokens(model="claude-opus-5-5", messages=[{"role": "user", "content": answer}]).input_tokens`, minus the same call's count for a one-character message. It runs only where a credential exists (`ant auth status`). | T 6.5 and 12 ask for "the tokenizer of the model the agents use". This session's agents run Claude Opus 5.5. |
| TR22 | Units. Every reader of a store takes `as_of` as an integer in microseconds: `read_sessions`, and through it `derive_trails`, `roads_and_trails`, `count_roads_and_trails`, `build_tool_graph` and `evaluate`. `check_as_of(as_of)` raises `ValueError("as_of must be integer microseconds since the epoch, UTC")` for a `bool`, a non-`int`, or a value below `MIN_AS_OF_US = 10**14` (1973-03-03). A seconds value (about 1.8·10⁹ today) fails. `TrailGraph.build` takes `as_of` as a label and checks nothing. Every time handed to or from the imprints and permissions code is integer UTC seconds: the imprints plan's `_trail_derive` passes `as_of * 10**6`; Task 16's ledger `now`, Task 22's `now` and `valid_until`, Task 26's `until`, and Task 27's `now` and shortened `valid_until` are seconds. | The plan review's MF4. Bound directly, a seconds `as_of` reads as 1970. Every row is then newer than it, N is 0 for every imprint, and the imprints plan's cross-plan test passes as 0 = 0 = 0. |
| TR23 | `lane_filtered` counts, for each lane's trail, the touches removed from inside it: a touch of another lane, or of a memory with no current lane, that has touches of this lane both before and after it in the session. Removing it joins its neighbours into one step. A touch outside every kept run is not counted, so deriving both lanes doesn't count every touch once per other lane. | T 5's "lane filtering" names a count without a rule. This one counts what the filter changed. Per (touch, lane), MF8's test would read 3, which says nothing. |

## Carried items

Items from the consolidation log, and the reviews it answers, that belong to this spec. Each is a task or a gate.

| Item | What it asks | Where |
|---|---|---|
| XS2, T's side | Admission derives R(I) with T's functions at `as_of` = t₁ and keeps only N. | Task 4 builds `roads_and_trails` in the shape of the imprints plan's `derive` seam (TR20), in microseconds, refusing seconds (TR22). Task 26 checks the imprints count at t₁ against it and that it isn't 0. Until Part A is on the Pi, that plan refuses `route` imprints (its G13). Gate G2 only if Rio Grande wants Part A sooner. |
| YN5 | T doesn't say admission derives trails; keep the imprint check out of the shared functions. | Task 4 (the derivation takes a connection and `as_of`, opens no file and checks no allow file, tested on an imprint-origin copy with none); Task 22 (the check lives in `main` only); Task 26 (a library call on an imprint finds what the CLI refuses). Gate G9 for T 7's sentence. |
| YN1 | N can exceed what an evaluation derives; or pass `--as-of` = t₁ to the use. | Task 22: `--as-of` composes with `--imprint-use` and moves which sessions are closed. Whether the use passes it is the imprints plan's call (dependency D-I5). |
| YN7 | "At most an hour", not "less than an hour". | Task 1, `test_yn7_closed_means_older_than_as_of_minus_one_hour`. Gate G9 for T 11's wording. |
| YS1 | The owner's words on resonances misstate them; fix before the first live imprint. | Gate G8 (T 7 and I 5.4, 9). Task 26 pins that trails read none of `accessed_count`, `last_accessed` or resonances. |
| XS3 | Recall times leave with the memories; T reads none of them. | Applied in the specs. Task 26's test above. |
| XS1 and I6 | The recall-row comparison's `as_of` and source rows. | Task 26's fixture: its source holds no row at or after t₁, and both files are derived at one `as_of` ≥ t₁. |
| XN2 | `-p UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET` without `--setenv`, never with it. | Taken by the imprints plan (its R15, Task 40). Task 27 asserts it from this side. |
| FS1 | The offline test can't assert "nothing written to the cache directory": fastembed 0.7.4 makes `tmp/` there. | Task 24: no file is created under the cache and no model is fetched; empty directories are allowed. |
| FN1 to FN3 | Wording, citations, wrap width in T. | Gate G9. FN2's call path is in Task 20's note. |
| Not this spec's | YN2, YN3, YN4, YN6, XM1, XN1, XN3 to XN6, I's CN7 (second half) and CN8. | The imprints and permissions plans. Listed so a reviewer can see none was dropped here. |

## Review Focus

Inputs and failures T implies that no test in its section 12 exercises, most likely first. Each has a test in the
task named.

1. **Malformed log rows.** A recall row whose `target_ids` or `context` isn't JSON, or a row whose timestamp doesn't
   parse, is skipped and counted; the pass, the build and the CLI go on. Task 2,
   `test_rf1_malformed_rows_are_skipped_and_counted`.
2. **Adversarial context text.** 4,000 characters of word characters, dots and slashes give anchors well inside the
   1 s call budget. Task 13, `test_rf2_anchors_are_fast_on_adversarial_text`.
3. **The server's own long session.** The running server's own session is never closed, even idle for two hours, so
   it never forms a trail mid-session. Task 1, `test_rf3_own_session_is_never_closed`.
4. **Bad `memory_ids` items.** A number, an empty string, a 65-character string or a repeated id is ignored and
   counted, never a crash, and writes no receipt when nothing else is named. A repeated real id gives one station.
   Task 18, `test_rf4_bad_memory_ids_are_ignored_not_fatal`.
5. **An empty or young store.** No closed session, or no vector anywhere: the tools answer that nothing on the
   trails is near, or `no_goal` naming nothing, and write no receipt; `--evaluate` reports "not evaluable". Task 18,
   `test_rf5_empty_store_names_nothing`; Task 23, `test_rf5_empty_store_is_not_evaluable`.

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `engram/trails.py` (new) | The pure parts, the tool graph, both gates, the imprint check, the read-only CLI (T 11 row 1). | 1–4, 8, 10–16, 21–25 |
| `engram/category_evolution.py` | `CategoryObserver.observe_trails`: events, proxies, road and detour proposals, the `trails` report block. | 6–8 |
| `engram/server.py` | The pass before `prune`; the tool graph as the last maintenance step; the three tools; receipts; counters; `trails_reporter`. | 9, 17–19 |
| `engram/storage.py` | `search_fts_ids(table, phrase, limit)`. | 13 |
| `engram/config.py` | `CategoryEvolutionConfig.trails`; `TrailsConfig` with `tools` and `lanes`. | 5 |
| `engram/embeddings.py` | `local_files_only` on `NomicEmbedProvider` and `create_embedding_provider`. | 20 |
| `engram/reflection.py` | `trails_reporter`; `reflect(focus="trails")`. | 19 |
| `engram/pyproject.toml` | `"trails"` in `py-modules`. | 1 |
| `engram/CLAUDE.md` | A "Trails" paragraph, a Key Files row, three MCP Tools rows marked off by default. | 29 |
| `engram/tests/trails_support.py` (new) | Synthetic stores, ids, times, vectors, a fake provider, server fixtures, imprint layouts. | 1, grown by later tasks |
| `engram/tests/test_trails.py` (new) | Derivation, routing, locate, forward lookup, answers. | 1–4, 10–15 |
| `engram/tests/test_trail_observer.py` (new) | The observer pass, gate off, barrier. | 6–9 |
| `engram/tests/test_trail_tools.py` (new) | Config, tool graph, registration, the tools, receipts, reflection. | 5, 16–19 |
| `engram/tests/test_trails_embeddings.py` (new) | `local_files_only`. | 20 |
| `engram/tests/test_trails_cli.py` (new) | The CLI and the imprint check. | 21, 22 |
| `engram/tests/test_trails_eval.py` (new) | Both gates, the report, limits, offline. | 23–25 |
| `engram/tests/test_trails_imprint.py` (new) | The synthetic imprint and the use's ends, with the imprints plan's code. | 26, 27 |
| `engram/tests/test_trails_pi.py` (new) | Pi measurements, run only with `ENGRAM_TRAILS_PI=1`. | 28 |
| `engram/scripts/trails_token_ratio.py` (new) | Counts real tokens of the largest answers (TR21). | 28 |

## What this plan uses from the other plans

- **Permissions plan** (merged before Part B):
  - Task 10: `permission_ledger.ledger_path(engram_home)`, `Ledger.open_read_only(engram_home)` (raises
    `FileNotFoundError` or `LedgerUnreadable`), `Ledger.close()`, `Ledger.create(engram_home, owner_handle, *, now)`
    for fixtures.
  - Task 11: `Ledger.store_row(instance_id) -> dict | None` and `Ledger.perform(Act("register-store",
    {"instance_id", "name", "owner", "place", "imprint_of"}), actor=…, channel="terminal", now=…)` for fixtures;
    `Act` is the permissions plan's Task 9.
  - The `stores` table is exactly P 5.5's, `owner` holding `person:<handle>`.
- **Imprints plan** (`engram/docs/superpowers/plans/2026-10-25-store-imprint.md`, written in parallel and read at
  the end of this one; merged before Part B), by the names in I and that plan:
  - D-I1: `imprint.make_plan(...)` (that plan's Task 15) then `imprint.build(plan_id, *, home, now) -> Built` (its
    Task 19) on a source store, with that plan's own engram test builders `imprint_support.plan_args` and `HOME`
    (its Tasks 7, 8 and 15), for Task 26's synthetic imprint; `Built.dir` holds `imprint.db`. Every time is UTC
    seconds.
  - D-I2: the layout `<root>/<imprint id>/imprint.db`, `<root>/<imprint id>.state/uses/<use id>.allow.json`,
    `<root>/<imprint id>.state/uses/<use id>/report.json` and `result.json`, `<root>/tombstones/<imprint id>.json`,
    and `meta.instance_id_origin = 'imprint'` (`store_identity.ORIGIN_IMPRINT`), for Task 22's fixtures.
  - D-I3: `imprint.use(imprint_id, use_id, *, root, lane, trails_cmd, now)` (its Task 38), the peer's
    `station-imprint-use-begin` (its Task 37) and `station-imprint-sync` (its Task 39), and the peer's
    `shorten_imprint` and `withdraw_imprint` (its Tasks 31 and 30), for Task 27's use ends.
  - D-I6: the imprints plan's peer test builder `admitted(tmp_path, route=True, ...)` (its Task 37's tests), able to
    take a directory that engram's `imprint.build` made, so Task 27 can admit a real imprint without a browser. If
    it can't, Task 27 asks that plan's owner to add the keyword. It is a test-only change there, not one this plan
    makes.
  - D-I4: the use unit's socket arguments, `--setenv=ENGRAM_EMBEDDER_SOCKET=<path>` or
    `-p UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET`, printed by that plan's `superyak-peer station-imprint-unit-env`
    (its R15, R20), for Task 27.
  - D-I5: whether `imprint.py use` passes `--as-of` = t₁ (YN1). That plan keeps I 12's command, without it (its YN1
    row), so N may exceed one evaluation's count, as its docstring says.
  - The other direction: that plan's `imprint.count_roads_and_trails(conn, *, lanes, as_of, derive=None)` sums
    `derive(conn, lane=lane, as_of=as_of)` over the scope's lanes (its R10, Task 35), with `as_of` in UTC seconds.
    Its `derive=None` should reach this plan's `trails.roads_and_trails` (Task 4) through its `_trail_derive`,
    which passes `as_of * 10**6` (TR22). Its real-function test, `test_count_matches_the_trail_functions`, runs once
    Part A merges. That plan's `imprint.use(..., trails_cmd=None)` runs `trails.py` with T 7's flags (its Task 38),
    which Tasks 21 and 22 build.

---

## Part A: the shared derivation

Worktree `/home/andy/superyak/.worktrees/trail-derivation`, branch `trail-derivation`, from `main`.

### Task 1: Times, sessions and the citing operations

**Files:**
- Create: `engram/trails.py`, `engram/tests/trails_support.py`
- Modify: `engram/pyproject.toml` (`py-modules` gains `"trails"`)
- Test: `engram/tests/test_trails.py`

**Interfaces:**
- Consumes: `resources.resource_path`.
- Produces:
  - the constants of Global Constraints; `LANES = ("personal", "work")`; `RULE_VERSION = "trail-v1"`;
  - `CITING_OPERATIONS: tuple[str, ...]` (TR2);
  - `parse_time(text: str) -> int` (microseconds UTC; raises `ValueError`); `iso_z(us: int) -> str`;
    `canonical(value) -> str` (TR6);
  - frozen dataclasses `EpisodeRow(id, created_at: str, t: int, content: str, context: str)`,
    `RecallRow(id, timestamp: str, t: int, target_ids: tuple[str, ...], outcome: str | None, recall_id: str | None)`,
    `ShownRow(timestamp: str, t: int, target_ids: tuple[str, ...])`, `OpRow(t: int, operation: str,
    target_ids: tuple[str, ...])`, and `SessionRows(session_id: str, episodes, recalls, shown, operations,
    newest: int, closed: bool)`;
  - `read_sessions(conn, as_of: int, *, own_session_id: str | None = None, counts: collections.Counter | None = None)
    -> dict[str, SessionRows]`. It reads rows by index, sets no pragma, changes no row factory and needs no
    sqlite-vec, so the imprints plan can pass any read-only connection.
  - `tests/trails_support.py`: `T(text) -> int`; `at(day: int, hh: int, mm: int = 0, ss: float = 0) -> str`
    (`2026-10-<day>` UTC ISO); `minute(i: int) -> str` (2026-10-01T00:00 UTC plus i minutes); `class Store` over
    `Storage(path, migrations_dir=MIGRATIONS_DIR)` with `ids(names) -> list[str]` (uuid5 per name),
    `episode(name, session, at, *, lane="work", content=None, context=None, vector=None) -> str` (`session=None`
    seeds a memory that belongs to no session, so seeding never makes a trail), `semantic(name, at, *, lane="work", content=None, vector=None) -> str`,
    `instinct(name="i") -> str`, `recall(session, at, targets, outcome="used") -> str` (the `recall_id`),
    `route_shown(session, at, targets) -> str`, `operation(session, at, op, targets)`, `relane(id, lane)`,
    `prune(id)` (`Storage.prune_episode_ids`), `revive(id)` (`Storage.revive_episode`), `walk(session, names, start,
    *, minutes=5, lane="work") -> list[str]` (one used single-target recall per memory, in order), `ro() ->
    sqlite3.Connection` (`paths.connect_ro`), `path`; `load_hook(name)` (importlib from `engram/hooks/<name>.py`).
    Rows are written through `Storage` and then their time set with one `UPDATE`, or inserted directly with the given
    timestamp.

- [ ] **Step 1: Write the failing tests**

```python
import subprocess, sys
import trails
from tests.trails_support import Store, T, at, load_hook

def test_sessions_come_from_episodes_and_recall_rows_only(tmp_path):
    s = Store(tmp_path); (a,) = s.ids("a")
    s.episode("a", "S1", at(1, 10))
    s.recall("S2", at(1, 10, 5), [a])
    s.route_shown("S3", at(1, 10, 6), [a])            # a route_shown row alone makes no session (C4)
    s.route_shown("S1", at(1, 13), [a])               # but it moves S1's newest row
    got = trails.read_sessions(s.ro(), T(at(1, 13, 30)))
    assert sorted(got) == ["S1", "S2"]
    assert got["S1"].newest == T(at(1, 13)) and got["S1"].closed is False
    assert got["S2"].closed is True

def test_yn7_closed_means_older_than_as_of_minus_one_hour(tmp_path):
    s = Store(tmp_path); s.episode("a", "S1", at(1, 10))
    assert trails.read_sessions(s.ro(), T(at(1, 11)))["S1"].closed is False          # exactly an hour: open
    assert trails.read_sessions(s.ro(), T(at(1, 11)) + 1)["S1"].closed is True       # 1 µs more: closed

def test_rows_newer_than_as_of_are_ignored(tmp_path):
    s = Store(tmp_path); s.episode("a", "S1", at(1, 10)); s.episode("b", "S1", at(1, 12))
    got = trails.read_sessions(s.ro(), T(at(1, 12)) - 1)["S1"]
    assert [e.id for e in got.episodes] == s.ids("a") and got.newest == T(at(1, 10))
    assert len(trails.read_sessions(s.ro(), T(at(1, 12)))["S1"].episodes) == 2      # a row at as_of counts

def test_rf3_own_session_is_never_closed(tmp_path):
    s = Store(tmp_path); s.episode("a", "S1", at(1, 10))
    assert trails.read_sessions(s.ro(), T(at(1, 12)), own_session_id="S1")["S1"].closed is False

def test_citing_operations_come_from_the_sleep_hook():
    assert trails.CITING_OPERATIONS == load_hook("sleep").CITING_OPERATIONS
    assert trails.CITING_OPERATIONS == ("mark_core", "instinct_feedback", "dream_react")

def test_importing_trails_runs_no_hook_code():
    code = "import sys; p = list(sys.path); import trails; assert sys.path == p; assert 'harness' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-derivation/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'trails'`.

- [ ] **Step 3: Implement the constants, times and `read_sessions` in `engram/trails.py`**

`read_sessions` reads non-null `episodes.session_id`, `memory_log` rows with `event_type IN ('recall',
'route_shown')` and their session id, and `operation_log` rows by `session_id`, ignoring rows with `t > as_of`
(TR1). It reads the session id as `CASE WHEN json_valid(context) THEN json_extract(context, '$.session_id') END`,
with `json_valid(context)` beside it. A bare `json_extract` on text that isn't JSON raises "malformed JSON" and aborts
the whole query (SQLite 3.40.1 on the Pi). A row whose `context` is not NULL and not valid JSON, whose time doesn't
parse, or whose `target_ids` isn't a JSON list of strings is skipped and counted as `rows_unparsed` in `counts` when
given (Task 2's `test_rf1_…` covers all three). A session exists only through an episode or a recall row. `closed`
is `newest < as_of − CLOSED_IDLE_US` and `session_id != own_session_id`. Add `"trails"` to `py-modules`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/andy/superyak/.worktrees/trail-derivation/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails.py`
Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-derivation add engram/trails.py engram/pyproject.toml engram/tests/trails_support.py engram/tests/test_trails.py
git -C /home/andy/superyak/.worktrees/trail-derivation commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: times, sessions and the citing operations (T 4)"
```

### Task 2: Touches, citations and suggested touches

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trails.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `Touch`, a `NamedTuple` `(memory_id: str, layer: str, kind: str, at: str, recall_id: str | None, rank: int,
    suggested: bool)`, with `payload() -> dict` holding exactly those seven keys;
  - `class MemoryLookup(conn)` with `lane(id) -> str | None`, `layer(id) -> str | None`, `created_at(id) -> int |
    None`, `exists(id) -> bool`, `is_instinct(id) -> bool`, batched 500 ids a query and cached;
  - `session_touches(rows: SessionRows, lookup: MemoryLookup, counts: collections.Counter) -> list[Touch]`, sorted by
    `(parse_time(at), rank, memory_id)`, before any lane filter. Counters: `ambiguous_used_recalls`,
    `skipped_targets`, `rows_unparsed`.

- [ ] **Step 1: Write the failing tests**

```python
def touches(s, session, as_of=None):
    counts = collections.Counter()                     # one Counter: rows_unparsed is counted by read_sessions
    rows = trails.read_sessions(s.ro(), as_of or T(at(9, 0)), counts=counts)[session]
    return trails.session_touches(rows, trails.MemoryLookup(s.ro()), counts), counts

def test_a_surfaced_result_is_not_a_touch(tmp_path):
    s = Store(tmp_path); a, b = s.ids("a b"); s.episode("a", None, at(1, 9)); s.episode("b", None, at(1, 9))
    s.recall("S1", at(1, 10), [a, b], outcome=None); s.recall("S1", at(1, 11), [a], outcome="not_used")
    assert [t for t in touches(s, "S1")[0] if t.kind == "cited"] == []

def test_per_target_citation_counts_episodes_and_citing_operations_only(tmp_path):
    s = Store(tmp_path); a, b, c = s.ids("a b c")
    for n in "abc": s.episode(n, None, at(1, 9))
    r = s.recall("S1", at(1, 10), [a, b, c], outcome="used")
    s.episode(None, "S1", at(1, 10, 1), content=f"the fix is in {a}")
    s.operation("S1", at(1, 10, 2), "mark_core", [b])
    s.operation("S1", at(1, 10, 3), "compress_commit", [c]); s.operation("S1", at(1, 10, 4), "share", [c])
    cited = [(t.memory_id, t.recall_id, t.rank) for t in touches(s, "S1")[0] if t.kind == "cited"]
    assert cited == [(a, r, 0), (b, r, 1)]

def test_one_target_is_judged_after_instincts_are_removed(tmp_path):
    s = Store(tmp_path); a, d = s.ids("a d"); i = s.instinct()
    s.episode("a", None, at(1, 9)); s.episode("d", None, at(1, 9))
    r = s.recall("S1", at(1, 10), [i, a], outcome="used")
    s.recall("S2", at(1, 10), [a, d], outcome="used"); s.prune(d)      # a pruned target still counts
    assert [(t.memory_id, t.rank) for t in touches(s, "S1")[0]] == [(a, 1)]
    got, counts = touches(s, "S2")
    assert got == [] and counts["ambiguous_used_recalls"] == 1 and counts["skipped_targets"] == 1

def test_an_ambiguous_multi_target_recall_is_counted_not_touched(tmp_path):
    s = Store(tmp_path); a, b = s.ids("a b"); s.episode("a", None, at(1, 9)); s.episode("b", None, at(1, 9))
    s.recall("S1", at(1, 10), [a, b], outcome="used: auto: cited")
    got, counts = touches(s, "S1")
    assert got == [] and counts["ambiguous_used_recalls"] == 1

def test_r9_suggested_touches(tmp_path):
    s = Store(tmp_path); a, b, c, w = s.ids("a b c w")
    for n in "abc": s.episode(n, None, at(1, 9))
    s.route_shown("S2", at(1, 9, 30), [a])              # another session: doesn't mark a
    s.route_shown("S1", at(1, 10), [b, w])              # names w before it exists
    s.walk("S1", ["a", "b", "c"], at(1, 10, 1))
    s.route_shown("S1", at(1, 11), [c])                 # after c's touch: doesn't mark it
    s.episode("w", "S1", at(1, 11, 5))                  # a wrote touch is never suggested
    got = [(t.memory_id, t.kind, t.suggested) for t in touches(s, "S1")[0]]
    assert got == [(a, "cited", False), (b, "cited", True), (c, "cited", False), (w, "wrote", False)]

def test_r9_a_given_id_named_by_an_answer_and_recalled_later_is_suggested(tmp_path):
    s = Store(tmp_path); (a,) = s.ids("a"); s.episode("a", None, at(1, 9))
    s.route_shown("S1", at(1, 10), [a])                 # the agent gave a; the answer named it as an entry
    s.walk("S1", ["a"], at(1, 10, 5))
    assert [t.suggested for t in touches(s, "S1")[0]] == [True]

def test_rf1_malformed_rows_are_skipped_and_counted(tmp_path):
    s = Store(tmp_path); (a,) = s.ids("a"); s.episode("a", None, at(1, 9))
    s.raw_log("recall", "yesterday", '["x"]', '{"session_id": "S1"}', "used")
    s.raw_log("recall", at(1, 10), "not json", '{"session_id": "S1"}', "used")
    s.raw_log("recall", at(1, 10, 30), '["x"]', '{"session_id": ', "used")    # a bare json_extract would abort
    s.walk("S1", ["a"], at(1, 11))
    got, counts = touches(s, "S1")
    assert [t.memory_id for t in got] == [a] and counts["rows_unparsed"] == 3
```

`Store.raw_log(event_type, timestamp, target_ids, context, outcome)` inserts one `memory_log` row as given; add it to
`trails_support.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-derivation/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails.py -k "touch or citation or instinct or ambiguous or suggested or malformed"`
Expected: FAIL, `AttributeError: module 'trails' has no attribute 'session_touches'`.

- [ ] **Step 3: Implement `MemoryLookup` and `session_touches`**

Wrote touches are the session's episodes. For each recall row with `outcome` starting with `used`: drop instinct
targets (TR3); a target is cited when a later same-session episode's `content` or `context` contains it, or a later
same-session `operation_log` row with an operation in `CITING_OPERATIONS` lists it, or the row has exactly one
non-instinct target (missing ones counted). A cited touch is suggested when a `route_shown` row of the session with
`t <=` the recall's `t` lists it. A row that fails to parse is skipped (TR1).

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-derivation add engram/trails.py engram/tests/trails_support.py engram/tests/test_trails.py
git -C /home/andy/superyak/.worktrees/trail-derivation commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: wrote, cited and suggested touches (T 4)"
```

### Task 3: Trails, revisit trails, steps and digests

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trails.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces:
  - `Step`, a `NamedTuple` `(src: str, dst: str, t: int, co_cited: bool, suggested: bool)`;
  - `Trail`, a frozen dataclass `(session_id: str, lane: str, touches: tuple[Touch, ...], truncated: bool,
    ambiguous_used_recalls: int)`, with `digest() -> str` (TR6) and `payload() -> dict` (T 5's payload, with
    `context_id: None` and `rule_version: "trail-v1"`);
  - `build_trail(session_id, lane, touches, lookup, counts) -> Trail | None` (T 4 "Trail", steps 1 to 5; counts
    `lane_filtered` by TR23, and `truncations`);
  - `revisit_trail(trail: Trail, lookup) -> Trail | None` (memories created before the session's first touch);
  - `trail_steps(trail: Trail) -> list[Step]` (co-cited: both touches from one recall; suggested: either touch);
  - `TrailSet`, a dataclass `(as_of: int, sessions: dict[str, SessionRows], full: dict[tuple[str, str], Trail],
    revisit: dict[tuple[str, str], Trail], counts: Counter)`;
  - `newest_first(sessions: Mapping[str, SessionRows]) -> list[SessionRows]` (closed only, TR12);
  - `derive_trails(conn, as_of: int, *, lanes: Sequence[str] = LANES, own_session_id: str | None = None,
    max_pairs: int | None = None) -> TrailSet`. With `max_pairs` it derives sessions newest first until that many
    pairs, and counts the rest as `pairs_not_scanned`. It opens no file and runs no imprint check (YN5).

- [ ] **Step 1: Write the failing tests**

```python
def test_determinism_same_store_and_as_of_give_byte_identical_payloads(tmp_path):
    s = planted(tmp_path, sessions=6)                 # trails_support: six sessions over shared memories
    one, two = (trails.derive_trails(s.ro(), T(at(20, 0))) for _ in range(2))
    assert {k: trails.canonical(v.payload()) for k, v in one.full.items()} == \
           {k: trails.canonical(v.payload()) for k, v in two.full.items()}
    t = next(iter(one.full.values()))
    assert t.digest() == hashlib.sha256(trails.canonical([x.payload() for x in t.touches]).encode()).hexdigest()
    assert set(t.payload()) == {"session_id", "lane", "context_id", "truncated", "ambiguous_used_recalls",
                                "rule_version", "touches"}

def test_mf8_a_personal_touch_between_two_work_touches_never_appears(tmp_path):
    s = Store(tmp_path); a, p, c = s.ids("a p c")
    s.episode("a", None, at(1, 9)); s.episode("p", None, at(1, 9), lane="personal"); s.episode("c", None, at(1, 9))
    s.walk("S1", ["a", "p", "c"], at(1, 10))
    ts = trails.derive_trails(s.ro(), T(at(2, 0)))
    assert [x.memory_id for x in ts.full[("S1", "work")].touches] == [a, c]
    assert ("S1", "personal") not in ts.full and ts.counts["lane_filtered"] == 1

def test_repeats_collapse_returns_stay_short_trails_drop_long_ones_truncate(tmp_path):
    s = Store(tmp_path); a, b = s.ids("a b"); s.episode("a", None, at(1, 9)); s.episode("b", None, at(1, 9))
    s.walk("S1", ["a", "a", "b", "a"], at(1, 10)); s.walk("S2", ["a"], at(1, 10))
    s.walk("S3", [f"m{i}" for i in range(513)], at(1, 10), minutes=0.01, create=True)
    ts = trails.derive_trails(s.ro(), T(at(3, 0)))
    assert [x.memory_id for x in ts.full[("S1", "work")].touches] == [a, b, a]
    assert ("S2", "work") not in ts.full
    long = ts.full[("S3", "work")]; assert len(long.touches) == 512 and long.truncated is True

def test_mf2_co_cited_steps_keep_delivered_rank(tmp_path):
    s = Store(tmp_path); a, b = s.ids("a b"); s.episode("a", None, at(1, 9)); s.episode("b", None, at(1, 9))
    s.recall("S1", at(1, 10), [b, a], outcome="used")
    s.episode(None, "S1", at(1, 10, 1), content=f"{a} and {b}")
    (st,) = [x for x in trails.trail_steps(trails.derive_trails(s.ro(), T(at(2, 0))).full[("S1", "work")])
             if x.src == b]
    assert (st.src, st.dst, st.co_cited) == (b, a, True)

def test_mf3_revisit_trails_skip_what_the_session_wrote(tmp_path):
    s = Store(tmp_path); a, b = s.ids("a b"); s.episode("a", None, at(1, 9)); s.episode("b", None, at(1, 9))
    for i, day in enumerate((2, 4)):
        s.walk(f"S{i}", ["a"], at(day, 10)); s.episode(None, f"S{i}", at(day, 10, 7)); s.walk(f"S{i}", ["b"], at(day, 10, 9))
    ts = trails.derive_trails(s.ro(), T(at(6, 0)))
    full = [{(x.src, x.dst) for x in trails.trail_steps(ts.full[(f"S{i}", "work")])} for i in (0, 1)]
    assert not (full[0] & full[1])
    assert all((a, b) in {(x.src, x.dst) for x in trails.trail_steps(ts.revisit[(f"S{i}", "work")])} for i in (0, 1))
```

`planted(tmp_path, sessions)` and `Store.walk(..., create=True)` join `trails_support.py`. With `create=True`, a walk
first creates each named memory that doesn't exist yet, with no session, one second before the walk starts, in the
walk's lane; a memory that exists is reused.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-derivation/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails.py -k "determinism or mf8 or repeats or mf2 or mf3"`
Expected: FAIL, `AttributeError: module 'trails' has no attribute 'derive_trails'`.

- [ ] **Step 3: Implement `build_trail`, `revisit_trail`, `trail_steps`, `newest_first` and `derive_trails`**

The revisit trail applies the same steps to the memories whose `created_at` is before the session's first touch.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-derivation add engram/trails.py engram/tests/trails_support.py engram/tests/test_trails.py
git -C /home/andy/superyak/.worktrees/trail-derivation commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: trails, revisit trails, steps and digests (T 4, 5)"
```

### Task 4: Support, span, roads and the count of roads and trails

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trails.py`

**Interfaces:**
- Consumes: Task 3.
- Produces:
  - `StepStats`, a dataclass `(sessions: dict[str, int], co_cited: bool, suggested: bool)` with `support -> int`,
    `span_s -> int`, `latest -> int | None` (TR5);
  - `step_support(trail_set: TrailSet, lane: str) -> dict[tuple[str, str], StepStats]` over full and revisit
    trails; a step that is co-cited or suggested in a session adds no session but sets the flag;
  - `is_road(stats: StepStats) -> bool` (`support >= ROAD_SUPPORT and span_s >= PERSISTENCE_MIN_S`);
  - `road_summary(stats_by_step) -> dict` with `roads`, `steps_supported_not_eligible`, `steps_support_2`;
  - `roads_and_trails(conn, *, lane: str, as_of: int) -> int` (TR20), the imprints plan's `derive` seam, and
    `count_roads_and_trails(conn, as_of: int, *, lanes: Sequence[str] = LANES) -> int`, their sum. Both take `as_of`
    in microseconds; the imprints plan's `_trail_derive` converts its seconds (TR22);
  - `MIN_AS_OF_US = 10**14` and `check_as_of(as_of: object) -> int` (TR22), which `read_sessions` calls first, so
    every reader of a store refuses a seconds value.

- [ ] **Step 1: Write the failing tests**

```python
def two_walks(s, days_hours):                          # sessions citing a then b at the given (day, hour)s
    a, b = s.ids("a b"); s.episode("a", None, at(1, 1)); s.episode("b", None, at(1, 1))
    for i, (d, h) in enumerate(days_hours): s.walk(f"S{i}", ["a", "b"], at(d, h))
    return a, b

def test_mf1_two_sessions_an_hour_apart_are_not_yet_a_road(tmp_path):
    s = Store(tmp_path); a, b = two_walks(s, [(2, 10), (2, 11)])
    stats = trails.step_support(trails.derive_trails(s.ro(), T(at(9, 0))), "work")
    assert stats[(a, b)].support == 2 and stats[(a, b)].span_s == 3600 and not trails.is_road(stats[(a, b)])
    assert trails.road_summary(stats)["steps_supported_not_eligible"] == 1

def test_mf1_a_third_session_a_day_later_makes_it_a_road(tmp_path):
    s = Store(tmp_path); a, b = two_walks(s, [(2, 10), (2, 11), (3, 11)])
    stats = trails.step_support(trails.derive_trails(s.ro(), T(at(9, 0))), "work")
    assert stats[(a, b)].span_s == 90_000 >= trails.PERSISTENCE_MIN_S and trails.is_road(stats[(a, b)])

def test_mf3_the_revisit_view_forms_a_road(tmp_path):
    s = Store(tmp_path); a, b = s.ids("a b"); s.episode("a", None, at(1, 9)); s.episode("b", None, at(1, 9))
    for i, day in enumerate((2, 4)):
        s.walk(f"S{i}", ["a"], at(day, 10)); s.episode(None, f"S{i}", at(day, 10, 7)); s.walk(f"S{i}", ["b"], at(day, 10, 9))
    assert trails.is_road(trails.step_support(trails.derive_trails(s.ro(), T(at(6, 0))), "work")[(a, b)])

def test_co_cited_and_suggested_steps_add_no_support(tmp_path):
    s = Store(tmp_path); a, b = s.ids("a b"); s.episode("a", None, at(1, 9)); s.episode("b", None, at(1, 9))
    for i, day in enumerate((2, 4)):                   # co-cited both times
        s.recall(f"C{i}", at(day, 10), [a, b]); s.episode(None, f"C{i}", at(day, 10, 1), content=f"{a} {b}")
    for i, day in enumerate((2, 4)):                   # suggested both times
        s.route_shown(f"G{i}", at(day, 12), [b]); s.walk(f"G{i}", ["a", "b"], at(day, 12, 1))
    st = trails.step_support(trails.derive_trails(s.ro(), T(at(6, 0))), "work")[(a, b)]
    assert st.support == 0 and st.co_cited and st.suggested and not trails.is_road(st)

def test_xs2_count_roads_and_trails_on_a_plain_or_imprint_copy(tmp_path):
    s = Store(tmp_path / "src"); two_walks(s, [(2, 10), (2, 11), (3, 11)])
    assert trails.roads_and_trails(s.ro(), lane="work", as_of=T(at(9, 0))) == 3 + 1   # three trails, one road
    assert trails.roads_and_trails(s.ro(), lane="personal", as_of=T(at(9, 0))) == 0
    assert trails.count_roads_and_trails(s.ro(), T(at(9, 0))) == 4
    copy = imprint_origin_copy(s.path, tmp_path / "imp" / "imprint.db")   # meta.instance_id_origin = 'imprint'
    ro = sqlite3.connect(f"file:{copy}?mode=ro&immutable=1", uri=True)     # no allow file exists anywhere
    assert trails.count_roads_and_trails(ro, T(at(9, 0)), lanes=("work",)) == 4   # YN5: the library checks nothing

def test_an_as_of_in_seconds_fails_loudly(tmp_path):         # TR22: never a silent N = 0 at the imprints seam
    s = Store(tmp_path); two_walks(s, [(2, 10), (2, 11), (3, 11)])
    seconds = T(at(9, 0)) // 10**6
    for call in (lambda v: trails.read_sessions(s.ro(), v), lambda v: trails.derive_trails(s.ro(), v),
                 lambda v: trails.roads_and_trails(s.ro(), lane="work", as_of=v),
                 lambda v: trails.count_roads_and_trails(s.ro(), v)):
        for bad in (seconds, float(T(at(9, 0))), True):
            with pytest.raises(ValueError, match="microseconds"): call(bad)
    assert trails.roads_and_trails(s.ro(), lane="work", as_of=seconds * 10**6) == 4
```

`imprint_origin_copy(src, dest)` copies the store with the `sqlite3` backup API (a plain file copy would miss rows
still in the WAL) and sets `meta.instance_id_origin` to `imprint`; add it to `trails_support.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-derivation/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails.py -k "mf1 or mf3_the or co_cited_and or xs2 or in_seconds"`
Expected: FAIL, `AttributeError: module 'trails' has no attribute 'step_support'`.

- [ ] **Step 3: Implement `StepStats`, `step_support`, `is_road`, `road_summary`, `roads_and_trails`, `count_roads_and_trails` and `check_as_of`**

`check_as_of` runs first in `read_sessions`, before any query, so no reader of a store can take seconds (TR22). The
docstring of `roads_and_trails` says `as_of` is integer microseconds, UTC, and that the imprints plan's
`_trail_derive` multiplies its seconds by 10⁶.

- [ ] **Step 4: Run Part A's tests and the packaging test**

Run: `cd /home/andy/superyak/.worktrees/trail-derivation/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails.py tests/test_packaging.py`
Expected: PASS. Report the counts.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-derivation add engram/trails.py engram/tests/trails_support.py engram/tests/test_trails.py
git -C /home/andy/superyak/.worktrees/trail-derivation commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: support, span, roads and the count of roads and trails (T 4, 5; XS2)"
```

Part A then goes through "Verification before merge", items 1 to 3, 5 and 6, as its own merge (Gate G1).

---

## Part B: the rest of step 1

Worktree `/home/andy/superyak/.worktrees/trail-step-1`, branch `trail-step-1`, from `main` after permissions core,
Part A and imprints have merged.

### Task 5: The config gates

**Files:**
- Modify: `engram/config.py` (`CategoryEvolutionConfig`, `:147-167`; `EngramConfig`, `:170-189`; `load_config`,
  `:301-358`), `engram/trails.py`
- Test: `engram/tests/test_trail_tools.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `CategoryEvolutionConfig.trails: object = False`; `@dataclass class TrailsConfig: tools: object = False;
  lanes: object = field(default_factory=lambda: ["work"])`; `EngramConfig.trails: TrailsConfig`, loaded through
  `load_section("trails", TrailsConfig)`; `trails.enabled_lanes(value: object) -> tuple[str, ...] | None` (`None`
  means invalid). `_DEFAULT_TOML` is unchanged, so existing config files and their tests are untouched.

- [ ] **Step 1: Write the failing tests**

```python
def write_config(tmp_path, text):
    (tmp_path / ".engram").mkdir(exist_ok=True); (tmp_path / ".engram" / "config.toml").write_text(text)
    return config.load_config(tmp_path)

def test_defaults_are_off_with_the_work_lane(tmp_path):
    c = write_config(tmp_path, "")
    assert c.category_evolution.trails is False and c.trails.tools is False and c.trails.lanes == ["work"]
    assert trails.enabled_lanes(c.trails.lanes) == ("work",)

@pytest.mark.parametrize("raw", ['"true"', "1", '"yes"'])
def test_only_an_exact_true_is_true(tmp_path, raw):
    c = write_config(tmp_path, f"[trails]\ntools = {raw}\n[category_evolution]\ntrails = {raw}\n")
    assert c.trails.tools is not True and c.category_evolution.trails is not True

@pytest.mark.parametrize("raw, want", [('"work"', None), ('["work", "work"]', None), ('["other"]', None),
                                       ("1", None), ("[]", ()), ('["personal", "work"]', ("personal", "work"))])
def test_lanes_are_parsed_fail_closed(tmp_path, raw, want):
    assert trails.enabled_lanes(write_config(tmp_path, f"[trails]\nlanes = {raw}\n").trails.lanes) == want
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_tools.py`
Expected: FAIL, `AttributeError: 'EngramConfig' object has no attribute 'trails'`.

- [ ] **Step 3: Implement `TrailsConfig`, the `trails` key and `enabled_lanes`**

`enabled_lanes` returns the given order when the value is a `list` of distinct strings, each `work` or `personal`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2, adding `tests/test_config.py tests/test_config_routing.py`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/config.py engram/trails.py engram/tests/test_trail_tools.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: [category_evolution] trails and [trails] tools and lanes, off by default (T 5, 6.6)"
```

### Task 6: The observer pass, trail events

**Files:**
- Modify: `engram/category_evolution.py` (`CategoryObserver`, `:870-1470`)
- Test: `engram/tests/test_trail_observer.py`

**Interfaces:**
- Consumes: `trails.derive_trails`, `trails.newest_first`, `Trail.digest`, `Trail.payload`; the store's
  `transaction(immediate=True)` and `append_event(kind, payload, *, event_id)` (`engram/categories.py:1432`, `:1522`).
- Produces:
  - `CategoryObserver.observe_trails(graph_conn, as_of: int, *, batch_scope=contextlib.nullcontext,
    own_session_id: str | None = None) -> dict` (TR9), returning the pass's counts;
  - `CategoryObserver._current_trail_events() -> dict[tuple[str, str], tuple[str, dict]]` (newest
    `trail_observed` event by rowid per (session, lane));
  - counters `sessions_read`, `events_written`, `pairs_not_scanned`, `passes_skipped_lock`,
    `passes_skipped_auto_commit`, `truncations`, `ambiguous_used_recalls`, `skipped_targets`, `lane_filtered`.
  - `trails_support.observer(tmp_path, *, db=None, **flags) -> CategoryObserver` on `db` or
    `tmp_path / "categories_v2.db"`, with `shadow=True` and `auto_commit=False` unless `flags` say otherwise.

- [ ] **Step 1: Write the failing tests**

```python
def test_rmf1_prune_then_revive_returns_to_an_earlier_digest_with_a_new_event(tmp_path):
    s = Store(tmp_path); a, b, c = s.walk("S1", ["a", "b", "c"], at(1, 10), create=True)
    obs = observer(tmp_path); as_of = T(at(3, 0))
    obs.observe_trails(s.ro(), as_of); e1, p1 = obs._current_trail_events()[("S1", "work")]
    s.prune(b); obs.observe_trails(s.ro(), as_of)
    s.revive(b); obs.observe_trails(s.ro(), as_of)
    e3, p3 = obs._current_trail_events()[("S1", "work")]
    assert p3["touches"] == p1["touches"] and e3 != e1                        # same digest, new id, no key error

def test_sa_more_than_64_pending_sessions_drain_over_passes(tmp_path):
    s = Store(tmp_path)
    for i in range(100): s.walk(f"S{i:03d}", ["a", "b"], minute(i), create=(i == 0))
    obs = observer(tmp_path); as_of = T(at(3, 0))
    assert obs.observe_trails(s.ro(), as_of)["events_written"] == 64
    assert obs.observe_trails(s.ro(), as_of)["events_written"] == 36
    s.relane(s.ids("b")[0], "personal")                                        # re-lanes every old trail
    assert obs.observe_trails(s.ro(), as_of)["events_written"] == 64           # re-emitted, oldest first

def test_c3_the_scan_reads_the_newest_pairs_and_counts_the_rest(tmp_path, monkeypatch):
    assert trails.MAX_PAIRS_SCANNED == 16_384
    monkeypatch.setattr(trails, "MAX_PAIRS_SCANNED", 10)                       # TR13
    s = Store(tmp_path)
    for i in range(15): s.walk(f"S{i:02d}", ["a", "b"], minute(i), create=(i == 0))
    got = observer(tmp_path).observe_trails(s.ro(), T(at(3, 0)))
    assert got["pairs_not_scanned"] == 5 and got["events_written"] == 10

def test_a_route_shown_row_before_a_touch_changes_the_digest(tmp_path):
    s = Store(tmp_path); a, b = s.walk("S1", ["a", "b"], at(1, 10), create=True)
    obs = observer(tmp_path); obs.observe_trails(s.ro(), T(at(3, 0)))
    s.route_shown("S1", at(1, 10, 2), [b])
    assert obs.observe_trails(s.ro(), T(at(3, 0)))["events_written"] == 1
    assert [t["suggested"] for t in obs._current_trail_events()[("S1", "work")][1]["touches"]] == [False, True]

def test_the_pass_releases_the_barrier_between_batches(tmp_path):
    s = Store(tmp_path)
    for i in range(20): s.walk(f"S{i:02d}", ["a", "b"], minute(i), create=(i == 0))
    obs, written = observer(tmp_path), []
    @contextlib.contextmanager
    def scope():
        before = count_events(obs); yield; written.append(count_events(obs) - before)
    obs.observe_trails(s.ro(), T(at(3, 0)), batch_scope=scope)
    assert written[:3] == [8, 8, 4]

def test_lock_order_a_recall_between_batches_never_deadlocks(tmp_path):
    s = Store(tmp_path)
    for i in range(20): s.walk(f"S{i:02d}", ["a", "b"], minute(i), create=(i == 0))
    obs, barrier, finished = observer(tmp_path), threading.RLock(), []
    between, entered = threading.Event(), threading.Event()
    @contextlib.contextmanager
    def scope():                                       # the server's batch_scope: the lifecycle barrier itself
        with barrier: yield
        between.set(); entered.wait(5)                 # after the first batch, wait until the recall holds the barrier
    def recall():                                      # a tool call: the barrier for the whole call, then the observer
        between.wait(10)
        with barrier:
            entered.set()
            obs.observe_recall("q", s.ids("a b"), source="test", observed_at=datetime.now(timezone.utc))
        finished.append("recall")
    def run_pass():                                    # s.ro() opens in this thread
        obs.observe_trails(s.ro(), T(at(3, 0)), batch_scope=scope); finished.append("pass")
    threads = [threading.Thread(target=f, daemon=True) for f in (recall, run_pass)]
    for t in threads: t.start()
    for t in threads: t.join(30)
    assert not any(t.is_alive() for t in threads), "deadlock: the pass and a recall wait on each other's lock"
    assert sorted(finished) == ["pass", "recall"] and count_events(obs) == 20

def test_a_lock_failure_is_a_skipped_pass_not_an_error(tmp_path):
    s = Store(tmp_path); s.walk("S1", ["a", "b"], at(1, 10), create=True)
    obs = observer(tmp_path); holder = sqlite3.connect(tmp_path / "categories_v2.db")
    holder.execute("BEGIN IMMEDIATE")
    got = obs.observe_trails(s.ro(), T(at(3, 0)))
    assert got["passes_skipped_lock"] == 1 and got["events_written"] == 0

def test_the_pass_refuses_unless_auto_commit_is_false(tmp_path):
    s = Store(tmp_path); s.walk("S1", ["a", "b"], at(1, 10), create=True)
    got = observer(tmp_path, auto_commit=True, allow_startup_consolidation=False).observe_trails(s.ro(), T(at(3, 0)))
    assert got["passes_skipped_auto_commit"] == 1 and count_events(observer(tmp_path)) == 0
```

`count_events(obs)` counts `trail_observed` rows; it joins `trails_support.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_observer.py`
Expected: FAIL, `AttributeError: 'CategoryObserver' object has no attribute 'observe_trails'`.

- [ ] **Step 3: Implement `observe_trails`'s event half**

Lock order (TR9). A tool call holds the server's lifecycle barrier for the whole call (`_server_operation`,
`engram/server.py:653-683`). Then `recall` takes the observer's `self._lock` in `observe_recall`
(`engram/category_evolution.py:1052-1053`), and `log_outcome` and `reflect` do the same. So the pass takes them in
that order too. Every batch is `with batch_scope():` and, inside it, `self._prepare_public_lock()`, `with
self._lock:` and `self._ensure_process()`, as `observe_recall` does (`:1043-1065`). The pass holds neither lock
across a batch boundary, and it reads `graph.db` outside both.

1. If `self.auto_commit` is true, count a skipped pass and return.
2. Outside both locks, derive from `graph_conn` with `max_pairs=trails.MAX_PAIRS_SCANNED`.
3. The first batch reads `_current_trail_events()`. It uses the observer's own connection, so it runs only inside a
   batch. The batch picks the pairs whose current event is missing, differs, or whose trail has gone (TR8). It takes
   at most `SESSIONS_PER_PASS` sessions, oldest first by newest row (TR12), and writes the first
   `SESSIONS_PER_BATCH` of them. Each later batch writes the next `SESSIONS_PER_BATCH`. Every batch re-checks its
   pairs' current events and appends inside one `transaction(immediate=True)`, with the stable id of TR7.
4. `sqlite3.OperationalError` on the lock (the connection's `timeout=0`) counts `passes_skipped_lock` and ends the
   pass. `CategoryQuotaExceeded` ends the pass through `_record_error`. An exception from `batch_scope()` itself (a
   coordinator that is shutting down) ends the pass and propagates.

`category_evolution.py` does `import trails` and reads every constant as `trails.NAME` when it runs, never through
`from trails import …`, so TR13's patches reach the pass.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/category_evolution.py engram/tests/trails_support.py engram/tests/test_trail_observer.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Category observer: gated trail events with bounded scan, batches and fail-closed locks (T 5)"
```

### Task 7: The observer pass, roads and diagnostics

**Files:**
- Modify: `engram/category_evolution.py`
- Test: `engram/tests/test_trail_observer.py`

**Interfaces:**
- Consumes: Task 6; `trails.step_support`, `trails.is_road`; `EvolutionEngine.propose`, `latest_disposition`,
  `lineage` (`engram/category_evolution.py:281`, `:408`, `:424`); `CellDraft`, `Boundary`
  (`engram/categories.py:249-266`); `CategoryObserver.proxy_id`.
- Produces: `CategoryObserver._propose_trail_roads(trail_set, events, batch_scope, counts) -> int`; the
  `report()["trails"]` block with exactly `sessions_read`, `events_written`, `trail_events`,
  `steps_support_2_full`, `steps_support_2_revisit`, `co_cited_steps`, `suggested_steps`,
  `steps_supported_not_eligible`, `roads_proposed`, `detours_proposed`, `any_committed`, `truncations`,
  `ambiguous_used_recalls`, `skipped_targets`, `lane_filtered`, `pairs_not_scanned`, `passes_skipped_lock`,
  `passes_skipped_auto_commit` (TR10).

- [ ] **Step 1: Write the failing tests**

```python
def road_store(tmp_path, days=(2, 2, 3), hours=(10, 11, 11)):
    s = Store(tmp_path); a, b = s.ids("a b"); s.episode("a", None, at(1, 1)); s.episode("b", None, at(1, 1))
    for i, (d, h) in enumerate(zip(days, hours)): s.walk(f"S{i}", ["a", "b"], at(d, h))
    return s, a, b

def test_mf1_an_eligible_road_is_one_pending_create_rewrite(tmp_path):
    s, a, b = road_store(tmp_path); obs = observer(tmp_path); obs.observe_trails(s.ro(), T(at(9, 0)))
    cell_id = obs._stable_id("trail-road-cell", {"lane": "work", "source": obs.proxy_id(a), "target": obs.proxy_id(b)})
    rid = obs._stable_id("trail-road", {"cell_id": cell_id})
    cell = obs.store.get_cell(cell_id)
    assert cell["dimension"] == 1 and cell["content"] == "trail step"
    assert cell["payload"] == {"lane": "work", "rule_version": "trail-v1"}
    assert [x.cell_id for x in obs.store.get_boundaries(cell_id)] == [obs.proxy_id(a), obs.proxy_id(b)]
    ev = json.loads(obs.store.connection.execute("SELECT payload_json FROM cat_rewrites WHERE id=?", (rid,)).fetchone()[0])
    assert ev["locus_id"] == obs.proxy_id(a) and ev["context_id"] is None
    assert ev["evidence"]["cohesion_gain"] == pytest.approx(1 - 1 / 3)
    assert ev["evidence"]["complexity_cost"] == 0.25
    assert ev["evidence"]["persistence_score"] == pytest.approx(min(1, 90_000 / 604_800))
    assert obs.engine.latest_disposition(rid) == "proposed" and obs._current_epoch() is None
    assert zero_cells(obs) == {obs.proxy_id(a), obs.proxy_id(b)}             # proxies for road endpoints only

def test_mf1_two_sessions_an_hour_apart_propose_nothing(tmp_path):
    s, a, b = road_store(tmp_path, days=(2, 2), hours=(10, 11)); obs = observer(tmp_path)
    got = obs.observe_trails(s.ro(), T(at(9, 0)))
    assert got["events_written"] == 2 and trail_rewrites(obs) == [] and zero_cells(obs) == set()
    assert obs.report()["trails"]["steps_supported_not_eligible"] == 1

def test_mf1_a_second_pass_treats_the_rewrite_id_as_done(tmp_path):
    s, a, b = road_store(tmp_path); obs = observer(tmp_path)
    obs.observe_trails(s.ro(), T(at(9, 0)))
    assert obs.observe_trails(s.ro(), T(at(9, 0)))["roads_proposed"] == 0

def test_mf1_evidence_keeps_the_earliest_and_latest_past_the_cap(tmp_path):
    s, a, b = road_store(tmp_path, days=[2 + i // 12 for i in range(40)], hours=[i % 12 for i in range(40)])
    obs = observer(tmp_path); obs.observe_trails(s.ro(), T(at(9, 0)))       # 40 sessions fit one pass of 64
    (rid,) = trail_rewrites(obs)
    ev = obs.engine.lineage(rid)["evidence"]
    assert len(ev) == 31 and event_of(obs, "S0") in ev and event_of(obs, "S39") in ev

def test_determinism_road_ids_repeat_on_a_fresh_v2_store(tmp_path):
    s, a, b = road_store(tmp_path)
    ids = []
    for name in ("one", "two"):
        obs = observer(tmp_path, db=tmp_path / f"{name}.db"); obs.observe_trails(s.ro(), T(at(9, 0)))
        ids.append(sorted(trail_rewrites(obs)))
    assert ids[0] == ids[1]

def test_diagnostics_hold_only_counts(tmp_path):
    s, a, b = road_store(tmp_path); obs = observer(tmp_path); obs.observe_trails(s.ro(), T(at(9, 0)))
    block = obs.report()["trails"]
    assert set(block) == TRAIL_REPORT_KEYS and all(type(v) in (int, bool) for v in block.values())
    assert block["roads_proposed"] == 1 and block["any_committed"] is False
```

`trail_rewrites(obs)`, `event_of(obs, session)`, `zero_cells(obs)` and `TRAIL_REPORT_KEYS` join
`trails_support.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_observer.py -k "mf1 or road_ids or diagnostics"`
Expected: FAIL, `TypeError: 'NoneType' object is not subscriptable` (no road cell).

- [ ] **Step 3: Implement road proposals and the report block**

Every batch keeps Task 6's lock order. After the events, one batch reads the current events again and copies them
out. Outside both locks, the pass recounts support from that copy (current lane filtered, revisit view from
`MemoryLookup` over `graph_conn`). It then proposes at most `MAX_ROADS_PER_PASS` eligible roads not yet proposed,
`PROPOSALS_PER_BATCH` per batch. Each batch re-checks `latest_disposition` of its rewrite ids inside its transaction.
Create proxy 0-cells for both endpoints inside the same transaction when missing, as `_observe_recall` does
(`engram/category_evolution.py:1145-1157`), with `context_id=None` and `created_event_id` the newest supporting
event. Evidence: the earliest and latest supporting sessions' events, then the rest earliest first, at most
`ROAD_EVIDENCE`. No weight observation is written.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_observer.py`
Expected: PASS, 14 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/category_evolution.py engram/tests/trails_support.py engram/tests/test_trail_observer.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Category observer: pending trail roads with replayable evidence and a counts-only report (T 5)"
```

### Task 8: Detours

**Files:**
- Modify: `engram/trails.py`, `engram/category_evolution.py`
- Test: `engram/tests/test_trail_observer.py`

**Interfaces:**
- Consumes: Tasks 3, 4 and 7.
- Produces:
  - `Detour`, a frozen dataclass `(lane: str, x: str, y: str, long: tuple[tuple[str, str], ...], short:
    tuple[tuple[str, str], ...], sessions: tuple[str, ...], first_touch: tuple[int, ...])` with `saving -> float`
    and `persistence -> float`;
  - `trails.find_detours(trail_set: TrailSet, lane: str, roads: frozenset[tuple[str, str]]) -> list[Detour]`;
  - `CategoryObserver._propose_trail_detours(detours, batch_scope, counts) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
def detour_store(tmp_path, long_names, short_names, days=(2, 4, 6)):
    s = Store(tmp_path)
    for d in days:                                     # every road travelled in three sessions, days apart
        s.walk(f"L{d}", long_names, at(d, 10), create=True)
        s.walk(f"T{d}", short_names, at(d, 12), create=True)    # the short side may name memories of its own
    return s

def test_mf4_overlapping_routes_give_only_the_vertex_disjoint_pair(tmp_path):
    s = detour_store(tmp_path, ["x", "a", "b", "y"], ["x", "a", "y"])
    obs = observer(tmp_path); obs.observe_trails(s.ro(), T(at(9, 0)))
    (d,) = trails.find_detours(trails.derive_trails(s.ro(), T(at(9, 0))), "work", road_set(obs))
    x, a, b, y = s.ids("x a b y")
    assert (d.x, d.y, d.long, d.short) == (a, y, ((a, b), (b, y)), ((a, y),))
    (rid,) = detour_rewrites(obs); members = obs.engine.lineage(rid)
    assert sum(len(v) for v in members.values()) <= 32
    cell = obs.store.get_cell(members["output"][0])
    assert cell["content"] == "two routes" and cell["payload"] == {"lane": "work", "long_hops": 2,
                                                                   "short_hops": 1, "rule_version": "trail-v1"}
    src = [b.cell_id for b in obs.store.get_boundaries(cell["id"], "source")]
    tgt = [b.cell_id for b in obs.store.get_boundaries(cell["id"], "target")]
    assert obs.store.validate_path(src) == obs.store.validate_path(tgt)
    again = observer(tmp_path, db=tmp_path / "again.db"); again.observe_trails(s.ro(), T(at(9, 0)))
    assert detour_rewrites(again) == detour_rewrites(obs)                    # determinism: the same detour ids

def test_equal_length_or_a_quarter_saving_is_never_proposed(tmp_path):
    s = detour_store(tmp_path, ["x", "a", "b", "c", "y"], ["x", "d", "e", "y"])      # (4 − 3) / 4 = 0.25
    detour_store(tmp_path, ["p", "q", "r"], ["p", "t", "r"], days=(3, 5, 7))          # equal length
    obs = observer(tmp_path); obs.observe_trails(s.ro(), T(at(9, 0)))
    assert detour_rewrites(obs) == []

def test_detour_evidence_and_witnesses_stay_inside_their_caps(tmp_path):
    s = detour_store(tmp_path, ["x", "a", "y"], ["x", "y"], days=tuple(range(2, 22)))
    obs = observer(tmp_path)
    for _ in range(3): obs.observe_trails(s.ro(), T(at(28, 0)))
    (rid,) = detour_rewrites(obs); members = obs.engine.lineage(rid)
    assert len(members["evidence"]) == 15 and len(members["witness"]) == 3
    assert {event_of(obs, "L2"), event_of(obs, "T21")} <= set(members["evidence"])

def test_sf3_a_detour_waits_for_the_cells_of_its_roads(tmp_path, monkeypatch):
    monkeypatch.setattr(trails, "MAX_ROADS_PER_PASS", 1)                # TR13: one road cell per pass
    s = detour_store(tmp_path, ["x", "a", "b", "y"], ["x", "a", "y"])     # four roads; the detour needs three
    obs = observer(tmp_path); obs.observe_trails(s.ro(), T(at(9, 0)))
    assert detour_rewrites(obs) == [] and obs.report()["last_error"] is None
    for _ in range(3): obs.observe_trails(s.ro(), T(at(9, 0)))
    assert len(road_set(obs)) == 4 and len(detour_rewrites(obs)) == 1 and obs.report()["last_error"] is None
```

`road_set(obs)` and `detour_rewrites(obs)` join `trails_support.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_observer.py -k "mf4 or quarter or detour"`
Expected: FAIL, `AttributeError: module 'trails' has no attribute 'find_detours'`.

- [ ] **Step 3: Implement `find_detours` and detour proposals**

The search (TR11), which the tests do not fully determine:

```python
runs = {}                                    # (x, y) -> {route: [(session, first touch time)]}
for (sid, lane_), trail in sorted(chain(ts.full.items(), ts.revisit.items())):
    if lane_ != lane: continue
    st = trail_steps(trail)
    for i in range(len(st)):
        seen = {st[i].src}
        for j in range(i, min(i + DETOUR_MAX_STEPS, len(st))):
            e = st[j]
            if e.co_cited or e.suggested or (e.src, e.dst) not in roads or e.dst in seen: break
            seen.add(e.dst)
            route = tuple((k.src, k.dst) for k in st[i:j + 1])
            runs.setdefault((route[0][0], e.dst), {}).setdefault(route, set()).add((sid, first_touch(trail)))
for (x, y), routes in sorted(runs.items()):
    for r1, r2 in combinations(sorted(routes, key=lambda r: (-len(r), r)), 2):
        inner1, inner2 = {v for _, v in r1[:-1]}, {v for _, v in r2[:-1]}
        if len(r1) == len(r2) or inner1 & inner2: continue
        if (len(r1) - len(r2)) / len(r1) <= DETOUR_SAVING: continue
        yield Detour(...)                    # kept when persistence >= 0.10
```

`roads` is the set of road steps of the lane whose `trail step` cell is stored in the v2 store, proposed this pass
or earlier, read in one batch after the road proposals. It is not every road eligible in `graph.db` mode. With the
cap of 64 roads a pass, an eligible road may have no cell yet, and a detour over it would fail `validate_path`
(`engram/categories.py:1724-1745`) and `propose`'s witness check (`engram/category_evolution.py:369-371`). Such a
detour waits for a later pass. The search itself runs outside both locks; proposals go `PROPOSALS_PER_BATCH` per
batch, in Task 6's lock order.

Before proposing, call `validate_path` on both sides and check their endpoints match. Cell and rewrite ids per TR7;
`locus_id` proxy(X); witnesses the distinct roads of both sides, at most `DETOUR_WITNESSES`; evidence the earliest
and latest, then earliest first, at most `DETOUR_EVIDENCE`; `cohesion_gain` the saving, `complexity_cost` 0.25,
`persistence_score = min(1, (latest − earliest) // 10**6 / PERSISTENCE_UNIT_S)` over first-touch times. At most
`MAX_DETOURS_PER_PASS`, after the roads.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_observer.py`
Expected: PASS, 18 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/trails.py engram/category_evolution.py engram/tests/trails_support.py engram/tests/test_trail_observer.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: travelled, vertex-disjoint detours proposed as pending level-2 cells (T 5)"
```

### Task 9: The server runs the pass before `prune`, and stays off by default

**Files:**
- Modify: `engram/server.py` (`_run_sleep_maintenance`, `:1144-1290`: a step `trail-observe` between `decay` and
  `prune`)
- Test: `engram/tests/test_trail_observer.py`

**Interfaces:**
- Consumes: `CategoryObserver.observe_trails`; `Storage.open_read_only`; `_maintenance_step_scope`
  (`engram/server.py:1096-1112`); `_remember_category_error` (`:505-512`).
- Produces: `server._run_trail_observer(maint, guarded: bool) -> None`. It runs when `category_evolution.enabled is
  True` and `trails is True` and an observer exists; when `auto_commit is not False` it writes nothing and notes
  `maint.note("trail-observe", skipped="auto_commit")`. It opens `Storage.open_read_only(DB_PATH)`, closes it in a
  `finally`, and passes `batch_scope=lambda: _maintenance_step_scope(guarded)` and `own_session_id=_session_id`.
  `trails_support.trail_init_env(tmp_path, monkeypatch, toml)` drives the real initializer, as
  `tests/test_category_server.py:222-260` does, with graph and watcher off and a fake embedder. It exposes
  `server`, `store`, `v2_path`, `start()` (initialize and run maintenance inline), `stop()` (run the generation's
  cleanup), `v2_bytes()` (`None` when the file is absent), `maintenance_report()` and `observer()`.

- [ ] **Step 1: Write the failing tests**

```python
GATE_OFF = {
    "trails_off": "[category_evolution]\nenabled = true\ntrails = false\nauto_commit = false\n",
    "observer_off": "[category_evolution]\nenabled = false\ntrails = true\nauto_commit = false\n",
    "auto_commit_on": "[category_evolution]\nenabled = true\ntrails = true\nauto_commit = true\n",
    "auto_commit_one": "[category_evolution]\nenabled = true\ntrails = true\nauto_commit = 1\n",
    "auto_commit_text": '[category_evolution]\nenabled = true\ntrails = true\nauto_commit = "false"\n',
}                                                          # the observer reads 1 and "false" as false (:905); only
                                                           # the server's `is not False` refuses them (T 5)

@pytest.mark.parametrize("case", sorted(GATE_OFF))
def test_gate_off_leaves_categories_v2_byte_identical(tmp_path, monkeypatch, case):
    env = trail_init_env(tmp_path, monkeypatch, GATE_OFF[case])
    seed_road_sessions(env.store)                          # sessions that would propose a road
    if case == "auto_commit_on": legacy_replay(env.v2_path, env.store.ids("a b"))   # import_legacy_category
    env.start(); env.stop()                                # first open with the same flags
    before = env.v2_bytes(); env.start()
    report = env.maintenance_report(); env.stop()
    assert env.v2_bytes() == before
    if case.startswith("auto_commit"):
        assert {"name": "trail-observe", "skipped": "auto_commit"}.items() <= step(report, "trail-observe").items()

def test_the_pass_runs_before_prune_on_its_own_read_only_connection(tmp_path, monkeypatch):
    env = trail_init_env(tmp_path, monkeypatch, GATE_ON); seed_road_sessions(env.store)
    order, opened = [], spy(monkeypatch, "storage.Storage.open_read_only")      # stays a classmethod
    monkeypatch.setattr(env.server, "_run_trail_observer", recording(env.server._run_trail_observer, order, "trails"))
    monkeypatch.setattr(storage.Storage, "prune_decayed", recording(storage.Storage.prune_decayed, order, "prune"))
    env.start()                                            # prunes through server._storage, not env.store's Storage
    assert order.index("trails") < order.index("prune") and opened and trail_rewrites(env.observer())

def test_a_failing_pass_is_recorded_and_never_blocks_startup_or_recall(tmp_path, monkeypatch):
    env = trail_init_env(tmp_path, monkeypatch, GATE_ON)
    monkeypatch.setattr("category_evolution.CategoryObserver.observe_trails", raises(RuntimeError("boom")))
    env.start()
    assert env.server._category_observer.report()["last_error"] == "RuntimeError"
    assert "results" in env.server.recall("anything", uninvited=0)
```

`GATE_ON`, `seed_road_sessions`, `legacy_replay` (through `category_evolution.import_legacy_category`,
`engram/category_evolution.py:2276`), `spy`, `recording`, `raises` and `step` join `trails_support.py`. `GATE_ON`
leaves `[persistence]` off, so the prune step calls `Storage.prune_decayed`. `env.store` seeds the store before
`_init` runs, so it is the helper's own `Storage`, not `server._storage`; the order test patches the class.
`spy(monkeypatch, "mod.Class.attr")` reads the attribute with `inspect.getattr_static` and wraps a classmethod's
function back in `classmethod`, so `Storage.open_read_only(path)` still gets `cls`. `recording(fn, order, name)`
appends `name` and calls `fn`; set on a class, it receives `self` as its first argument.

These tests run maintenance inline (`guarded` false), where `_maintenance_step_scope` takes no lock. The served
case, a real barrier with a recall between batches, is Task 6's
`test_lock_order_a_recall_between_batches_never_deadlocks`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_observer.py -k "gate_off or before_prune or failing_pass"`
Expected: FAIL, `AttributeError: module 'server' has no attribute '_run_trail_observer'`.

- [ ] **Step 3: Implement `_run_trail_observer` and its step**

The step is not wrapped in `_maintenance_step_scope` as a whole: the pass takes the barrier per batch. `as_of` is
the pass's start in microseconds. Any exception goes through `_remember_category_error` and the step's error
record; maintenance goes on.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_observer.py tests/test_startup_maintenance.py tests/test_category_server.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/server.py engram/tests/trails_support.py engram/tests/test_trail_observer.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Server: the gated trail pass before prune, byte-identical when off (T 5, 12)"
```

### Task 10: Kahan angles and the A* of 6.1

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trails.py`

**Interfaces:**
- Consumes: Task 4.
- Produces:
  - `angle(a: np.ndarray, b: np.ndarray) -> float`, `2·atan2(‖â − b̂‖, ‖â + b̂‖)` in float64;
  - `Edge`, a `NamedTuple` `(dst: int, cost: float, support: int, road: bool, latest: int | None, co_cited: bool,
    suggested: bool)`;
  - `TrailGraph`, a dataclass `(lane, as_of, nodes: tuple[str, ...], index: dict[str, int], vectors: np.ndarray
    (float32, n × d), has_vec: np.ndarray (bool), out: list[list[Edge]], layers: tuple[str, ...], trails:
    dict[str, TrailRef], through: list[tuple[str, ...]], digest: str)` with `remove(ids: Iterable[str]) -> None`;
    `TrailRef` is `(nodes: tuple[int, ...], kinds: tuple[str, ...], times: tuple[int, ...], truncated: bool,
    newest: int, flags: tuple[tuple[bool, bool], ...])`;
  - `TrailGraph.build(lane, as_of, nodes, vectors: Mapping[str, np.ndarray | None], steps: Iterable[tuple[str, str,
    int, bool, int | None, bool, bool]], *, layers=None, trails=None) -> TrailGraph`, costing each edge
    `θ(u, v)·(1 + 1/max(1, support))`, or `π·(1 + 1/max(1, support))` when a vector is missing;
  - `TrailGraph.from_trails(trail_set, lane, vectors) -> TrailGraph` (`graph.db` mode, road = `is_road`);
  - `vectors_for(conn, ids) -> dict[str, np.ndarray]` from `episode_vectors` and `semantic_vectors`, float32;
  - `Search`, a `NamedTuple` `(end: str, path: tuple[int, ...], cost: float | None, expansions: int, pred: int |
    None)`, `end` one of `goal`, `no_route`, `truncated`;
  - `astar(graph, starts: Mapping[int, float], goals: frozenset[int], h: Callable[[int], float], *,
    max_expansions: int = MAX_EXPANSIONS, wall_s: float | None = None, clock=time.monotonic, trace: list | None =
    None) -> Search`, open list keyed `(f, h, memory id)`, a relaxation only when strictly lower;
  - `route(graph, start_id, goal_id, *, wall_s=None, clock=time.monotonic) -> dict`: `{"route": [ids],
    "steps": [{"support", "road"}], "end", "detours_avoided": []}`, ids only.

- [ ] **Step 1: Write the failing tests**

```python
def test_r4_kahan_angles_are_a_metric_on_random_768d_triples():
    for case in range(10_000):
        seed = 20261025 + case; rng = np.random.default_rng(seed)          # Global Constraints' seed rule
        a, b, c = (u(rng) for _ in range(3))
        if case % 3 == 1: b = u(a + 1e-8 * rng.normal(size=768))          # near-duplicates
        if case % 3 == 2: b = u(-a + 1e-8 * rng.normal(size=768))         # near-antipodes
        ab, ba, bc, ac = (trails.angle(*p) for p in ((a, b), (b, a), (b, c), (a, c)))
        assert ab == ba and 0 <= ab <= math.pi and trails.angle(a, a) == 0, (case, seed)
        assert ac <= ab + bc + 1e-12, (case, seed)
    assert trails.angle(a, u(a + 1e-9 * rng.normal(size=768))) < 1e-6

def test_astar_is_optimal_and_consistent_on_a_hand_built_graph():
    g = hand_graph()                         # six nodes with vectors; cheapest s → t is s, m2, m3, t
    trace = []
    got = trails.astar(g, {g.index["s"]: 0.0}, frozenset({g.index["t"]}),
                       lambda n: trails.angle(g.vectors[n], g.vectors[g.index["t"]]), trace=trace)
    assert [g.nodes[n] for n in got.path] == ["s", "m2", "m3", "t"] and got.cost == pytest.approx(HAND_COST, abs=1e-9)
    best = {}
    for n, cost in trace:
        assert n not in best or cost >= best[n] - 1e-9; best[n] = cost

def test_missing_vectors_cost_pi_and_have_no_heuristic():
    g = trails.TrailGraph.build("work", 0, ["a", "b"], {"a": None, "b": u(np.ones(4))}, [("a", "b", 1, False, 0, False, False)])
    assert g.out[0][0].cost == pytest.approx(2 * math.pi)
    assert trails.route(g, "a", "b")["route"] == ["a", "b"]

def test_a_bound_returns_truncated_and_no_route():
    g = chain_graph(50)
    got = trails.astar(g, {0: 0.0}, frozenset({49}), lambda n: 0.0, max_expansions=3)
    assert got.end == "truncated" and got.path == ()
    late = iter([0.0, 0.6]).__next__
    assert trails.astar(g, {0: 0.0}, frozenset({49}), lambda n: 0.0, wall_s=0.5, clock=late).end == "truncated"

def test_route_names_ids_with_each_steps_support_and_road_status():
    out = trails.route(hand_graph(), "s", "t")
    assert out["route"] == ["s", "m2", "m3", "t"] and [x["road"] for x in out["steps"]] == [True, False, True]
    assert all(isinstance(x["support"], int) for x in out["steps"])
```

`u(x)` (unit vector), `hand_graph()`, `HAND_COST` and `chain_graph(n)` join `trails_support.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails.py -k "r4 or astar or missing_vectors or bound or route_names"`
Expected: FAIL, `AttributeError: module 'trails' has no attribute 'angle'`.

- [ ] **Step 3: Implement `angle`, `TrailGraph`, `vectors_for`, `astar` and `route`**

`route` uses `h(n) = θ(n, goal)`, or 0 when either vector is missing (T 6.1), `heapq` with the `(f, h, id)` key, and
`MAX_EXPANSIONS`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/trails.py engram/tests/trails_support.py engram/tests/test_trails.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: Kahan angles, the trail graph and a bounded, deterministic A* (T 6.1)"
```

### Task 11: Goal sets and the route to a goal in words

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trails.py`

**Interfaces:**
- Consumes: Task 10.
- Produces:
  - `angles_to(graph, q: np.ndarray) -> np.ndarray` (float64, NaN without a vector, rows converted in blocks of
    `VECTOR_BLOCK`);
  - `GoalSet`, a `NamedTuple` `(radius: float, theta_min: float | None, members: frozenset[int], nearest: int |
    None, h: np.ndarray)`; `goal_set(graph, q) -> GoalSet`;
  - `Station`, a `NamedTuple` `(node: int, why: str, cost: float, angle: float | None, through: int)`;
  - `RouteToGoal`, a `NamedTuple` `(end: str, path: tuple[int, ...], cost: float | None, goal: GoalSet,
    expansions: int)`, `end` one of `goal`, `at_goal`, `no_goal`, `no_route`, `truncated`;
  - `route_to_goal(graph, stations: Sequence[Station], q, *, wall_s=None, clock=time.monotonic,
    max_expansions=MAX_EXPANSIONS) -> RouteToGoal` (`at_goal` when the popped goal has no predecessor; a path of
    more than `MAX_STOPS` stops is `truncated`).

- [ ] **Step 1: Write the failing tests**

```python
def test_goal_sets_on_500_random_graphs_match_brute_force():
    for case in range(500):
        rng = np.random.default_rng(20261025 + case)
        g, stations, q = random_goal_graph(rng, max_nodes=40, dim=8)       # some vectorless nodes, random supports
        gs = trails.goal_set(g, q); got = trails.route_to_goal(g, stations, q)
        for u_, edges in enumerate(g.out):
            for e in edges: assert gs.h[u_] <= e.cost + gs.h[e.dst] + 1e-12, (case, u_, e)
        assert all(gs.h[n] == 0 for n in gs.members), case
        best = brute_dijkstra(g, {s.node: s.cost for s in stations}, gs.members)
        if best is None: assert got.end in ("no_goal", "no_route"), case
        else: assert got.cost == pytest.approx(best, abs=1e-9), case
        if got.end in ("goal", "at_goal"):
            assert (got.end == "at_goal") == (len(got.path) == 1 and got.path[0] in {s.node for s in stations}
                                              and got.cost == pytest.approx(entry_cost(stations, got.path[0]))), case

def test_radius_and_empty_goal_sets():
    g = fan_graph(thetas=[0.3, 0.35, 1.2])                                  # angles to q of three nodes
    assert trails.goal_set(g, Q).radius == pytest.approx(min(0.3 + 0.10, math.acos(0.60)))
    far = fan_graph(thetas=[1.0, 1.1])
    assert trails.goal_set(far, Q).members == frozenset() and trails.goal_set(far, Q).theta_min > trails.R_MAX

def test_vectorless_nodes_are_never_goals_and_the_ends_read_right():
    g = fan_graph(thetas=[None, 0.2]); gs = trails.goal_set(g, Q)
    assert g.index["n0"] not in gs.members
    at = trails.route_to_goal(g, [st(g, "n1", 0.4)], Q)
    assert (at.end, len(at.path), at.cost) == ("at_goal", 1, 0.4)
    none = fan_graph(thetas=[None, None])
    got = trails.route_to_goal(none, [st(none, "n0", 0.0)], Q)
    assert got.end == "no_goal" and got.goal.nearest is None
    cut = island_graph()                                                   # the goal is unreachable
    assert trails.route_to_goal(cut, [st(cut, "s", 0.0)], Q).end == "no_route"
    long = chain_to_goal(70)                                               # the only goal is 70 stops away
    assert trails.route_to_goal(long, [st(long, "c0", 0.0)], Q).end == "truncated"

@pytest.mark.parametrize("w_e1, edge, want", [
    (1.0, ("e2", "t"), ("goal", ["e2", "t"], 0.3)),
    (1.0, ("e2", "e1"), ("goal", ["e2", "e1"], 0.3)),       # the re-check's case
    (0.3, ("e2", "e1"), ("at_goal", ["e1"], 0.3)),          # the tie keeps no predecessor
])
def test_the_planted_cases_of_6_3(w_e1, edge, want):
    g = planted_6_3(edge)                                    # e1, t in Γ; e2 not; the edge costs exactly 0.3
    got = trails.route_to_goal(g, [st(g, "e1", w_e1, "near"), st(g, "e2", 0.0, "given")], Q)
    assert (got.end, [g.nodes[n] for n in got.path]) == want[:2] and got.cost == pytest.approx(want[2], abs=1e-12)
    assert got.cost == pytest.approx(brute_dijkstra(g, {g.index["e1"]: w_e1, g.index["e2"]: 0.0}, got.goal.members))
```

`random_goal_graph`, `brute_dijkstra` (a Dijkstra from a super-source, written in the test support from T 6.3 alone,
importing nothing from `trails` but `TrailGraph`), `fan_graph`, `Q`, `st`, `island_graph`, `chain_to_goal`,
`planted_6_3` and `entry_cost` join `trails_support.py`. `planted_6_3` builds edges with `TrailGraph.build` and then
sets the named edge's `cost` to exactly 0.3.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails.py -k "goal or radius or planted"`
Expected: FAIL, `AttributeError: module 'trails' has no attribute 'goal_set'`.

- [ ] **Step 3: Implement `angles_to`, `goal_set` and `route_to_goal`**

`r = min(θ_min + GOAL_DELTA, R_MAX)`; `h(n) = max(0, θ(n, q) − r)`, 0 without a vector; every station enters the
open list with `g = cost` and no predecessor.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/trails.py engram/tests/trails_support.py engram/tests/test_trails.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: goal sets and an admissible A* to a goal in words (T 6.3)"
```

### Task 12: The `--categories` reader, detours avoided, parity and current lanes

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trails.py`

**Interfaces:**
- Consumes: Tasks 7, 8, 10.
- Produces:
  - `open_categories_ro(path) -> sqlite3.Connection` (`file:…?mode=ro`, `query_only`);
  - `TrailGraph.from_categories(trail_set, lane, vectors, categories_conn, lookup) -> TrailGraph`: footpaths from
    `graph.db`, road status from stored road cells and detours from level-2 cells, read through `cat_boundaries`
    and the store's `validate_path`, keeping a cell unless its rewrite's latest disposition is `rejected` and
    dropping a cell whose endpoint's current lane differs from its payload's lane;
  - `TrailGraph.detours`: `list[Detour | StoredDetour]`; `route()` now fills `detours_avoided` with
    `{"x", "y", "detour", "sessions"}` for each detour whose X and Y the route visits, X first, by its short side.

- [ ] **Step 1: Write the failing tests**

```python
def test_mf6_parity_between_graph_db_and_categories_modes(tmp_path):
    s = detour_store(tmp_path, ["x", "a", "b", "y"], ["x", "a", "y"])
    obs = observer(tmp_path); as_of = T(at(9, 0)); obs.observe_trails(s.ro(), as_of); obs.close()
    ts = trails.derive_trails(s.ro(), as_of); vec = trails.vectors_for(s.ro(), all_ids(ts))
    db = trails.TrailGraph.from_trails(ts, "work", vec)
    cat = trails.TrailGraph.from_categories(ts, "work", vec, trails.open_categories_ro(tmp_path / "categories_v2.db"),
                                            trails.MemoryLookup(s.ro()))
    assert edges(db) == edges(cat)                                       # (src, dst, support, road)
    x, y = s.ids("x y")
    assert trails.route(db, x, y)["detours_avoided"] == trails.route(cat, x, y)["detours_avoided"]
    assert {d["detour"] for d in trails.route(cat, x, y)["detours_avoided"]} == stored_level_2_ids(tmp_path)

def test_mf8_re_laning_a_road_endpoint_excludes_it_everywhere(tmp_path):
    s, a, b = road_store(tmp_path); obs = observer(tmp_path); as_of = T(at(9, 0))
    obs.observe_trails(s.ro(), as_of); before = obs._current_trail_events()
    s.relane(b, "personal")
    ts = trails.derive_trails(s.ro(), as_of); vec = trails.vectors_for(s.ro(), all_ids(ts))
    assert (a, b) not in trails.step_support(ts, "work")
    assert b not in trails.TrailGraph.from_trails(ts, "work", vec).index
    cat = trails.TrailGraph.from_categories(ts, "work", vec, trails.open_categories_ro(tmp_path / "categories_v2.db"),
                                            trails.MemoryLookup(s.ro()))
    assert b not in cat.index and not any(e.road for es in cat.out for e in es)
    assert obs.observe_trails(s.ro(), as_of)["events_written"] >= 1
    assert obs._current_trail_events() != before

def test_c3_a_re_laned_memory_in_an_unscanned_old_trail_never_reaches_a_work_route(tmp_path, monkeypatch):
    s, a, b = road_store(tmp_path); obs = observer(tmp_path); as_of = T(at(9, 0))
    obs.observe_trails(s.ro(), as_of)
    s.relane(b, "personal")
    monkeypatch.setattr(trails, "MAX_PAIRS_SCANNED", 0)                   # TR13: the next pass rescans nothing
    got = obs.observe_trails(s.ro(), as_of)
    assert got["events_written"] == 0 and got["pairs_not_scanned"] > 0     # the old events and road cell stay
    ts = trails.derive_trails(s.ro(), as_of)
    cat = trails.TrailGraph.from_categories(ts, "work", {}, trails.open_categories_ro(tmp_path / "categories_v2.db"),
                                            trails.MemoryLookup(s.ro()))
    assert b not in cat.index and not any(e.road for es in cat.out for e in es)
```

`all_ids(trail_set)`, `edges(graph)` (sorted `(src, dst, support, road)`) and `stored_level_2_ids(tmp_path)` join
`trails_support.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails.py -k "mf6 or mf8_re or c3_a"`
Expected: FAIL, `AttributeError: type object 'TrailGraph' has no attribute 'from_categories'`.

- [ ] **Step 3: Implement `open_categories_ro`, `from_categories` and `detours_avoided`**

`from_categories` wraps the read-only connection in an `EvolvingCategoryStore` only if that opens it without
writing; otherwise it reads `cat_cells`, `cat_boundaries` and the disposition events with the same queries
`validate_path` and `latest_disposition` use (`engram/categories.py:1674-1745`;
`engram/category_evolution.py:408-421`). A sessions count N for a stored detour comes from the travelled runs of
`find_detours` on the same trail set.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 3 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/trails.py engram/tests/trails_support.py engram/tests/test_trails.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: the --categories reader, detours avoided, and parity with graph.db mode (T 6.1, 12)"
```

### Task 13: Anchors, word hits and locate

**Files:**
- Modify: `engram/trails.py`, `engram/storage.py` (beside `search_episode_fts`, `:1062-1071`)
- Test: `engram/tests/test_trails.py`

**Interfaces:**
- Consumes: Tasks 10, 11.
- Produces:
  - `Storage.search_fts_ids(table: str, phrase: str, limit: int) -> list[str]`: `table` is `episode_fts` or
    `semantic_fts`, else `ValueError`; the phrase is one quoted FTS5 phrase, `'"' + phrase.replace('"', '""') +
    '"'`; ids by rowid join, at most `limit`. Recall's own FTS calls are unchanged.
  - `anchors(text: str) -> list[str]` with T 6.2's patterns, compiled once:
    `(?:[\w.-]+/)+[\w.-]+`, `[\w-]{2,}\.[A-Za-z][A-Za-z0-9]{0,4}\b`, `\b[A-Z][A-Za-z0-9]*(?:Error|Exception|Warning)\b`,
    `\b_*[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b`, `\b[a-z]+[A-Z][A-Za-z0-9]+\b`; matches inside a longer match's span
    dropped; ordered by start; each text once; 3 to 128 characters; the first `MAX_ANCHORS`;
  - `fts_hits(search: Callable[[str, str, int], list[str]], anchor_list) -> list[str]` (each anchor in both tables,
    `FTS_HITS` each, first occurrence kept);
  - `embed_queries(provider, texts: Sequence[str]) -> list[np.ndarray]` (cut to `MAX_TEXT`, one batch,
    `prefix="search_query"`, unit vectors), the one function the tools and measure W call;
  - `Located`, a `NamedTuple` `(stations: list[Station], ignored: int)`; `locate(graph, *, c: np.ndarray | None,
    given: Sequence[str], hits: Sequence[str]) -> Located` with entry costs 0, `2·θ(c, e)` or `2π`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("text, want", [
    ("engram/server.py", ["engram/server.py"]), ("paths.py", ["paths.py"]),
    ("sqlite3.OperationalError", ["OperationalError"]), ("KeyError", ["KeyError"]),
    ("_record_application", ["_record_application"]), ("observeTrails", ["observeTrails"])])
def test_anchor_examples(text, want):
    assert trails.anchors(text) == want

def test_one_text_with_every_example_keeps_at_most_8_each_once():
    text = ("in engram/server.py and paths.py: sqlite3.OperationalError then KeyError in _record_application, "
            "observeTrails, KeyError again, a/b/c.txt x_y z_w q.md")
    got = trails.anchors(text)
    assert got[:6] == ["engram/server.py", "paths.py", "OperationalError", "KeyError", "_record_application",
                       "observeTrails"] and len(got) == 8 and len(set(got)) == 8 and "server.py" not in got

def test_a_whole_error_message_matches_nothing_its_anchors_match(tmp_path):
    s = Store(tmp_path); e = s.episode("e", None, at(1, 9), content="sqlite3.OperationalError: database is locked")
    message = "Traceback: sqlite3.OperationalError: database is locked while writing engram/server.py line 12"
    assert s.storage.search_episode_fts(message) == []
    assert s.storage.search_fts_ids("episode_fts", "OperationalError", 64) == [e]
    with pytest.raises(ValueError): s.storage.search_fts_ids("episodes", "x", 1)

def test_locate_orders_given_then_words_then_near():
    g = locate_graph()        # nodes g1 g2 w1 w2 w3 n1..n6, angles to C known, p1 personal (not in the work graph)
    got = trails.locate(g, c=C, given=["g2", "nope", "g1"], hits=["w3", "w1", "w2", "p1"])
    names = [(g.nodes[s.node], s.why) for s in got.stations]
    assert names == [("g2", "given"), ("g1", "given"), ("w1", "words"), ("w3", "words"), ("n1", "near"), ("n2", "near")]
    assert got.ignored == 1 and [s.cost for s in got.stations[:2]] == [0, 0]
    assert got.stations[2].cost == pytest.approx(2 * got.stations[2].angle)
    assert all(s.angle <= trails.R_MAX for s in got.stations if s.why == "near")

def test_locate_without_c_orders_words_by_id_at_two_pi_and_has_no_near():
    g = locate_graph(); got = trails.locate(g, c=None, given=["g1"], hits=["w3", "w1"])
    assert [(g.nodes[s.node], s.cost) for s in got.stations] == [("g1", 0), ("w1", 2 * math.pi), ("w3", 2 * math.pi)]

def test_rf2_anchors_are_fast_on_adversarial_text():
    for text in ("a" * 4000, "a/" * 2000, "a." * 2000, "_a" * 2000, ("aB" * 1999) + "!"):
        t0 = time.perf_counter(); trails.anchors(text)
        assert time.perf_counter() - t0 < 0.2, text[:8]

def test_embed_queries_cuts_and_uses_search_query():
    p = FakeProvider(); trails.embed_queries(p, ["x" * 5000, "goal"])
    assert p.calls == [(["x" * 4000, "goal"], "search_query")]
```

`locate_graph`, `C` and `FakeProvider` (records `(texts, prefix)`, returns seeded or mapped vectors, raises
`self.fail` when set) join `trails_support.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails.py -k "anchor or every_example or error_message or locate or rf2 or embed_queries"`
Expected: FAIL, `AttributeError: module 'trails' has no attribute 'anchors'`.

- [ ] **Step 3: Implement `search_fts_ids`, `anchors`, `fts_hits`, `embed_queries` and `locate`**

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2, adding `tests/test_storage.py`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/trails.py engram/storage.py engram/tests/trails_support.py engram/tests/test_trails.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: anchors, one-phrase FTS lookups and entry stations from context (T 6.2)"
```

### Task 14: Forward lookup

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trails.py`

**Interfaces:**
- Consumes: Task 10's `TrailGraph.trails` and `through`.
- Produces: `NextItem`, a `NamedTuple` `(node: int, kind: str, sessions: int, last: int | None, flag: str | None)`;
  `EndItem` `(node: int, sessions: int, median_hops: int)`; `Forward` `(entry: int, next: list[NextItem], ends:
  list[EndItem], ended_here: int, ends_unknown: int)`; `forward(graph, entry: int, *, max_sessions=FORWARD_SESSIONS,
  keep: int = FORWARD_KEEP) -> Forward`, keeping `keep` next items and `keep` ends.

- [ ] **Step 1: Write the failing tests**

```python
def test_next_items_rank_by_sessions_then_newest_then_id():
    g = forward_graph([("S1", "e x1 z"), ("S2", "e x1 y"), ("S3", "e x2"), ("S4", "e x2"), ("S5", "e x3")],
                      newest={"S3": 5, "S4": 6})
    assert [(g.nodes[n.node], n.sessions) for n in trails.forward(g, g.index["e"]).next] == [("x2", 2), ("x1", 2)]

def test_co_cited_and_suggested_successors_count_zero_and_come_last():
    g = forward_graph([("S1", "e c"), ("S2", "e s"), ("S3", "e w")], flags={("S1", 0): (True, False),
                                                                           ("S2", 0): (False, True)})
    got = trails.forward(g, g.index["e"], keep=3).next
    assert [(g.nodes[n.node], n.sessions, n.flag) for n in got] == [("w", 1, None), ("c", 0, "co-cited"),
                                                                     ("s", 0, "suggested")]

def test_a_write_after_the_station_reads_wrote():
    g = forward_graph([("S1", "e +fix")])                     # + marks a wrote touch
    assert trails.forward(g, g.index["e"]).next[0].kind == "wrote"

def test_ends_exclude_the_station_and_count_ended_here_and_truncated_trails():
    g = forward_graph([("S1", "e a z"), ("S2", "e b z"), ("S3", "a e"), ("S4", "e q")], truncated={"S4"})
    f = trails.forward(g, g.index["e"])
    assert (g.nodes[f.ends[0].node], f.ends[0].sessions) == ("z", 2) and f.ended_here == 1 and f.ends_unknown == 1
    assert "q" in [g.nodes[n.node] for n in trails.forward(g, g.index["e"], keep=4).next]

def test_median_hops_take_the_lower_median():
    odd = forward_graph([("S1", "e z"), ("S2", "e a b z"), ("S3", "e a z")])
    even = forward_graph([("S1", "e z"), ("S2", "e a b z")])
    assert trails.forward(odd, odd.index["e"]).ends[0].median_hops == 2
    assert trails.forward(even, even.index["e"]).ends[0].median_hops == 1

def test_at_most_256_sessions_are_read():
    g = forward_graph([(f"S{i:03d}", "e z") for i in range(300)])
    assert trails.forward(g, g.index["e"]).ends[0].sessions == 256
```

`forward_graph(specs, *, newest=None, flags=None, truncated=())` joins `trails_support.py`. Each spec is a session
and its full trail in order; `+name` marks a wrote touch; `flags[(session, i)]` is step i's `(co_cited,
suggested)`; a touch's time is its session's `newest` (default: the session's index in the list).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails.py -k "next_items or successors or write_after or ends_exclude or median or 256"`
Expected: FAIL, `AttributeError: module 'trails' has no attribute 'forward'`.

- [ ] **Step 3: Implement `forward`**

Full trails only. Sessions through the entry, newest first, at most `max_sessions`. Ends from `τ[−1]`, hops
`|τ| − 1 − i` with i the first occurrence; a truncated trail gives next items and counts in `ends_unknown`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/trails.py engram/tests/trails_support.py engram/tests/test_trails.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: forward lookup, what other sessions did next and where they ended (T 6.4)"
```

### Task 15: Short answers

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trails.py`

**Interfaces:**
- Consumes: Tasks 11, 13, 14.
- Produces:
  - `summary(content: str) -> str` (TR18, at most `SUMMARY_BYTES` in compact JSON, `…` counted when cut);
  - `compact(obj) -> str` (`separators=(",", ":")`, `ensure_ascii=False`); `receipt_short(receipt_id: str) -> str`
    (`"#"` + the first 8 hex characters of the uuid4);
  - `Sources(laid_by: str, receipt_id: str)`; answer builders that each return a `dict`, keys per T 6.5 and TR17:
    `answer_locate(graph, located, *, summary_of, sources, cut=(), degraded=())`,
    `answer_route(graph, result: RouteToGoal, stations, *, q, summary_of, sources, cut=(), degraded=())`,
    `answer_next(graph, stations, forwards, *, summary_of, sources, cut=(), degraded=())`;
    `summary_of: Callable[[str], str | None]` returns a memory's content, read when the answer is built;
  - `fit(answer: dict) -> tuple[dict, bool]`: at most `ANSWER_BYTES` of UTF-8 compact JSON, dropping in T 6.5's
    order, `True` when it shrank;
  - `named_ids(answer: dict) -> list[str]`, every id the answer names, in order;
  - `hidden_ids(graph, result) -> list[str]`, the stops a `{"skipped": k}` hides.

- [ ] **Step 1: Write the failing tests**

```python
ADVERSARIAL = ['say "hi"\\n', "tab\there\x07\x1b[31mred", "🦀" * 400, "汉字" * 3000, "x" * 100_000,
               "\n\n  first   line  \nsecond"]

def test_summaries_are_short_clean_first_lines():
    assert trails.summary("\n\n  first   line  \nsecond") == "first line"
    for text in ADVERSARIAL:
        s = trails.summary(text)
        assert len(json.dumps(s, ensure_ascii=False, separators=(",", ":")).encode()) <= 160
        assert not any(unicodedata.category(ch) == "Cc" for ch in s)

def test_every_answer_fits_6000_bytes_on_adversarial_content():
    for text in ADVERSARIAL:
        g, result, stations = route_of_stops(64, content=text)          # the longest route answered
        for answer in all_answers(g, result, stations, content=text):  # locate, route and next answers
            body, _ = trails.fit(answer)
            assert len(trails.compact(body).encode()) <= 6000
            assert "context words" not in trails.compact(body) and "goal words" not in trails.compact(body)

def test_a_20_stop_route_shows_6_skipped_8_and_6():
    g, result, stations = route_of_stops(20)
    route = build_route(g, result, stations)["route"]
    assert len(route) == 13 and route[6] == {"skipped": 8}
    assert set(trails.hidden_ids(g, result)) == {g.nodes[n] for n in result.path[6:14]}

def test_a_65_stop_route_is_truncated():
    g, stations = chain_with_goal(65)
    assert trails.route_to_goal(g, stations, Q).end == "truncated"

def test_sources_and_receipts():
    g, result, stations = route_of_stops(5)
    a = build_route(g, result, stations, receipt_id="5e21a9c0-1111-4222-8333-444455556666")
    assert a["sources"] == {"h": {"laid_by": "andy (default)", "allowed_by": "own store", "receipt": "#5e21a9c0"}}
    assert all(stop["src"] == "h" for stop in a["route"] if "id" in stop)
    assert a["route"][0]["via"].startswith("entry:") and a["route"][1]["walked"].endswith(tuple("0123456789"))

def test_determinism_answers_repeat_with_the_same_graph_vectors_and_receipt_id():
    one, two = (trails.compact(build_route(*route_of_stops(9), receipt_id=RID)) for _ in range(2))
    assert one == two
```

`route_of_stops(n, content=…)`, `all_answers`, `build_route` (calls `answer_route` with `laid_by="andy (default)"`),
`chain_with_goal` and `RID` join `trails_support.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails.py -k "summaries or 6000 or 20_stop or 65_stop or sources_and or answers_repeat"`
Expected: FAIL, `AttributeError: module 'trails' has no attribute 'summary'`.

- [ ] **Step 3: Implement the summary, the builders, `fit`, `named_ids` and `hidden_ids`**

A route of more than 12 stops shows its first 6 and last 6 around one `{"skipped": k}`. `walked` reads
`"<support> sessions, last <YYYY-MM-DD>"` (`session` when 1), or `"footpath (co-cited)"`, `"footpath
(suggested)"` or both when the step's support is 0. Angles have 4 decimals; no scores, session ids, context or
goal text.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/trails.py engram/tests/trails_support.py engram/tests/test_trails.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: short, sourced answers bounded at 6,000 bytes (T 6.5)"
```

### Task 16: The tool graph and `laid_by`

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trail_tools.py`

**Interfaces:**
- Consumes: Tasks 3, 4, 10; `store_identity.effective_id` (`engram/store_identity.py:113`); the permissions plan's
  `permission_ledger.Ledger.open_read_only` and `Ledger.store_row` (P plan Tasks 10 and 11).
- Produces:
  - `laid_by(engram_home: Path, instance_id: str | None, instance: str) -> str`: `"<handle> (<instance>)"` from
    `stores.owner` with `person:` dropped, else `"this store (<instance>)"`; it reads the ledger once, read-only, and
    a missing or unreadable ledger is the fallback;
  - `ToolGraph`, a dataclass `(as_of: int, lanes: dict[str, TrailGraph], digest: str, truncated: dict[str, bool],
    lanes_invalid: bool, sessions: dict[str, int], build_seconds: float, nbytes: int, laid_by: str)`;
  - `build_tool_graph(conn, as_of: int, lanes: tuple[str, ...] | None, *, own_session_id: str | None, laid_by:
    str, between_batches: Callable[[], None] = lambda: None, clock=time.monotonic) -> ToolGraph | None`. `None`
    lanes (invalid) builds nothing and sets `lanes_invalid`. Each lane gets `TOOL_SESSIONS` sessions and an equal
    share of `TOOL_NODES` and `TOOL_STEPS`, stopping a lane at the first session that would pass its share and
    marking it `truncated`. It calls `between_batches()` every `BUILD_BATCH` sessions; an exception from it
    propagates and the partial graph is dropped. Vectors are float32; each step's angle is computed once.

- [ ] **Step 1: Write the failing tests**

```python
def test_laid_by_names_the_ledger_owner_or_this_store(tmp_path):
    s = Store(tmp_path / "store"); iid = store_identity.effective_id(s.ro())
    home = tmp_path / "home"
    assert trails.laid_by(home, iid, "default") == "this store (default)"           # no ledger
    led = Ledger.create(home, "andy", now=T(at(1, 0)) // 10**6)
    assert trails.laid_by(home, iid, "default") == "this store (default)"           # no row
    led.perform(Act("register-store", {"instance_id": iid, "name": "default", "owner": "person:andy",
                                       "place": "place:home/andy", "imprint_of": None}),
                actor="person:andy", channel="terminal", now=T(at(1, 0)) // 10**6)
    led.close(); before = sha256(ledger_path(home))
    assert trails.laid_by(home, iid, "default") == "andy (default)" and sha256(ledger_path(home)) == before
    ledger_path(home).write_bytes(b"not a database")
    assert trails.laid_by(home, iid, "default") == "this store (default)"           # unreadable

def test_bounds_keep_the_newest_and_split_between_lanes(tmp_path, monkeypatch):
    assert (trails.TOOL_SESSIONS, trails.TOOL_NODES, trails.TOOL_STEPS) == (4096, 20_000, 262_144)
    monkeypatch.setattr(trails, "TOOL_SESSIONS", 10); monkeypatch.setattr(trails, "TOOL_NODES", 40)
    s = Store(tmp_path)
    for i in range(30): s.walk(f"W{i:02d}", [f"w{i}a", f"w{i}b"], minute(i), create=True)
    for i in range(3): s.walk(f"P{i}", [f"p{i}a", f"p{i}b"], at(1, 1, i), lane="personal", create=True)
    one = trails.build_tool_graph(s.ro(), T(at(3, 0)), ("work",), own_session_id=None, laid_by="x")
    assert one.sessions["work"] == 10 and one.truncated["work"] and newest_ten(s) == sessions_in(one, "work")
    two = trails.build_tool_graph(s.ro(), T(at(3, 0)), ("personal", "work"), own_session_id=None, laid_by="x")
    assert len(two.lanes["work"].nodes) <= 20 and two.sessions["personal"] == 3       # each lane gets half
    monkeypatch.setattr(trails, "TOOL_STEPS", 6)                          # one distinct step per session
    three = trails.build_tool_graph(s.ro(), T(at(3, 0)), ("work",), own_session_id=None, laid_by="x")
    assert three.sessions["work"] == 6 and three.truncated["work"]

def test_vectors_are_float32_and_angles_match_float64(tmp_path):
    s = vector_store(tmp_path)                                    # walks over memories with random vectors
    tg = trails.build_tool_graph(s.ro(), T(at(3, 0)), ("work",), own_session_id=None, laid_by="x").lanes["work"]
    assert tg.vectors.dtype == np.float32
    for u_, edges in enumerate(tg.out):
        for e in edges:
            want = trails.angle(tg.vectors[u_].astype(np.float64), tg.vectors[e.dst].astype(np.float64))
            assert e.cost == want * (1 + 1 / max(1, e.support))

def test_invalid_lanes_build_nothing_and_an_empty_list_builds_nothing_valid(tmp_path):
    s = vector_store(tmp_path)
    bad = trails.build_tool_graph(s.ro(), T(at(3, 0)), None, own_session_id=None, laid_by="x")
    assert bad.lanes_invalid and bad.lanes == {}
    empty = trails.build_tool_graph(s.ro(), T(at(3, 0)), (), own_session_id=None, laid_by="x")
    assert not empty.lanes_invalid and empty.lanes == {}

def test_a_refused_checkpoint_stops_the_build(tmp_path):
    s = Store(tmp_path)
    for i in range(70): s.walk(f"S{i:02d}", ["a", "b"], minute(i), create=(i == 0))
    with pytest.raises(RuntimeError, match="shutting down"):
        trails.build_tool_graph(s.ro(), T(at(3, 0)), ("work",), own_session_id=None, laid_by="x",
                                between_batches=raises(RuntimeError("server generation is shutting down")))
```

`Ledger`, `ledger_path` and `Act` come from the permissions plan's modules; `vector_store`, `newest_ten`,
`sessions_in` and `sha256` join `trails_support.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_tools.py -k "laid_by or bounds or float32 or invalid_lanes or checkpoint"`
Expected: FAIL, `AttributeError: module 'trails' has no attribute 'laid_by'`.

- [ ] **Step 3: Implement `laid_by`, `ToolGraph` and `build_tool_graph`**

`laid_by` imports `permission_ledger` inside the function, catches `FileNotFoundError`, `LedgerUnreadable` and
`sqlite3.Error`, and closes the ledger in a `finally`. The digest is TR6's `graph_digest`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/trails.py engram/tests/trails_support.py engram/tests/test_trail_tools.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: the bounded tool graph and laid_by from the permissions ledger (T 6.5, 6.6)"
```

### Task 17: The server builds the graph and registers the tools only when on

**Files:**
- Modify: `engram/server.py` (`_run_sleep_maintenance`, after `persistence-score-refresh`, `:1279-1283`, before the
  report is saved, `:1289-1290`; `_initialize_pre_serving`, `:4023-4033`)
- Test: `engram/tests/test_trail_tools.py`

**Interfaces:**
- Consumes: Task 16; `_server_tool` (`:690-697`); `_register_server_cleanup` (`:835-838`); `_admit_server_operation`
  (`:809-819`); `_maintenance_step_scope`.
- Produces: globals `_trail_tools_registered: bool`, `_trail_graph: ToolGraph | None`, `_trail_counters:
  collections.Counter`; `_register_trail_tools() -> bool` (TR14), registering `trail_locate`, `trail_route` and
  `trail_next` with T 6.6's descriptions only when `_config.trails.tools is True`; `_build_trail_graph(maint,
  guarded: bool) -> None`, the step `trail-graph`; `_trail_checkpoint() -> None` (admission then
  `finish_operation()`). `trails_support.trail_tools_env(tmp_path, monkeypatch, toml)` builds on `trail_init_env`
  and adds `pre_serve(hold_maintenance=False)` (`_initialize_pre_serving`, optionally holding the maintenance thread
  at its first step), `release_maintenance()`, `wait_maintenance()`, `count(sql)`, `shutdown_then_check()` (start the
  coordinator's cleanup, then call the real checkpoint), `start_build_and_pause()` (returns the build's read-only
  `Storage`, paused at its first checkpoint) and `fake_child_pid()`. At teardown it removes the three names from
  `server.mcp._tool_manager._tools`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("raw", [None, "false", '"true"', "1"])
def test_without_an_exact_true_no_trail_tool_is_registered(tmp_path, monkeypatch, raw):
    env = trail_tools_env(tmp_path, monkeypatch, "" if raw is None else f"[trails]\ntools = {raw}\n")
    env.pre_serve(); env.wait_maintenance()
    assert not {"trail_locate", "trail_route", "trail_next"} & tool_names(env.server)
    assert env.count("SELECT COUNT(*) FROM memory_log WHERE event_type = 'route_shown'") == 0

def test_with_true_the_three_tools_register_with_their_descriptions(tmp_path, monkeypatch):
    env = trail_tools_env(tmp_path, monkeypatch, "[trails]\ntools = true\n"); env.pre_serve()
    tools = {t.name: t.description for t in env.server.mcp._tool_manager.list_tools()}
    assert tools["trail_locate"].startswith("Where am I on the trails?")
    assert tools["trail_route"].startswith("Route along trails other sessions walked")
    assert tools["trail_next"].startswith("What did other sessions do next from here")

def test_the_graph_is_built_read_only_and_answers_not_ready_before(tmp_path, monkeypatch):
    env = trail_tools_env(tmp_path, monkeypatch, TOOLS_ON); seed_tool_store(env.store, sessions=130)
    opened, free_inside = spy(monkeypatch, "storage.Storage.open_read_only"), []
    monkeypatch.setattr(env.server, "_trail_checkpoint",
                        lambda: free_inside.append(lock_is_free(env.server._server_lifecycle_lock)))
    env.pre_serve(hold_maintenance=True)
    assert env.server.trail_locate(memory_ids=env.store.ids("a")) == {"note": "trail graph not ready"}
    env.release_maintenance(); env.wait_maintenance()
    assert opened and len(free_inside) >= 2 and all(free_inside) and env.server._trail_graph is not None

def test_shutdown_during_the_build_stops_it_and_closes_its_connection(tmp_path, monkeypatch):
    env = trail_tools_env(tmp_path, monkeypatch, TOOLS_ON); seed_tool_store(env.store, sessions=130)
    conns = capture(monkeypatch, "storage.Storage.open_read_only")
    monkeypatch.setattr(env.server, "_trail_checkpoint", env.shutdown_then_check)   # coordinator refuses
    env.pre_serve(); env.wait_maintenance()
    assert env.server._trail_graph is None
    with pytest.raises(sqlite3.ProgrammingError): conns[-1].conn.execute("SELECT 1")

def test_a_forked_child_quarantines_the_build_connection(tmp_path, monkeypatch):
    env = trail_tools_env(tmp_path, monkeypatch, TOOLS_ON); seed_tool_store(env.store)
    conn = env.start_build_and_pause()                            # paused at its first checkpoint
    env.server._before_server_fork(); env.fake_child_pid(); env.server._after_server_fork_child()
    assert conn in env.server._fork_quarantined_resources
```

`TOOLS_ON`, `seed_tool_store`, `tool_names`, `lock_is_free`, `capture` and the env helpers join
`trails_support.py`. 130 sessions give two checkpoints (one per `BUILD_BATCH` of 64), so `all(free_inside)` can't
pass on an empty list. `_server_lifecycle_lock` is an `RLock`, which its owner thread can always take again. So
`lock_is_free(lock)` tries `lock.acquire(blocking=False)` from a fresh thread, releases it there, and joins.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_tools.py -k "registered or descriptions or not_ready or shutdown or forked"`
Expected: FAIL, `AttributeError: module 'server' has no attribute '_register_trail_tools'`.

- [ ] **Step 3: Implement registration, the build step and the checkpoint**

The build opens `Storage.open_read_only(DB_PATH)`, registers it with `_register_server_cleanup(conn, conn.close,
"trail graph build")`, reads `laid_by` once (`trails.laid_by(ENGRAM_HOME, store_identity.effective_id(conn.conn),
_instance_name or "default")`), builds with `between_batches=_trail_checkpoint` and the lanes of
`trails.enabled_lanes(_config.trails.lanes)`, closes the connection in a `finally`, and swaps the graph in under
`_maintenance_step_scope(guarded)`. A failure is logged by type, recorded in the step, and leaves the tools answering
"not ready"; it never blocks startup or recall. It runs only when `_trail_tools_registered`. Until
then, each tool answers `{"note": "trail graph not ready"}`; Task 18 fills in the tools' bodies.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_tools.py tests/test_server_registry.py tests/test_startup_maintenance.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/server.py engram/tests/trails_support.py engram/tests/test_trail_tools.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Server: build the trail graph last and register the trail tools only when exactly on (T 6.6)"
```

### Task 18: The three tools, the output-time check and the receipt

**Files:**
- Modify: `engram/server.py`
- Test: `engram/tests/test_trail_tools.py`

**Interfaces:**
- Consumes: Tasks 13 to 17; `_storage.add_log_entry` (`engram/storage.py:1656-1680`); `_storage.search_fts_ids`.
- Produces: `trail_locate(context: str = "", memory_ids: list[str] | None = None, lane: str = "work") -> dict`;
  `trail_route(goal: str, context: str = "", memory_ids: list[str] | None = None, lane: str = "work") -> dict`;
  `trail_next(context: str = "", memory_ids: list[str] | None = None, lane: str = "work") -> dict`; helpers
  `_trail_recheck(ids: list[str], lane: str) -> set[str]` (lane and existence from `_storage`, at most
  `RECHECK_ROWS` ids), `_trail_receipt(answer: dict, tool: str, lane: str) -> None`. Counters: calls per tool;
  ends `no_goal`, `no_route`, `truncated`, `stale`; `shrunk`; `receipts_written`.

- [ ] **Step 1: Write the failing tests**

```python
def test_each_answer_that_names_memories_writes_exactly_one_receipt(tools_env):
    env, ids = tools_env; before = route_rows(env)
    a = env.server.trail_route(goal="the fix for the instinct count", context="KeyError in engram/server.py")
    rows = route_rows(env)[len(before):]
    assert len(rows) == 1 and json.loads(rows[0]["target_ids"]) == trails.named_ids(a)
    ctx = json.loads(rows[0]["context"])
    assert set(ctx) == {"receipt_id", "session_id", "tool", "lane", "as_of", "graph_digest", "rule_version"}
    assert rows[0]["id"] == ctx["receipt_id"]                           # T 6.6: the receipt id is the row's id
    assert rows[0]["layer"] == "trail" and rows[0]["outcome"] is None
    assert "KeyError" not in json.dumps(dict(rows[0])) and "instinct count" not in json.dumps(dict(rows[0]))
    assert a["sources"]["h"]["receipt"] == "#" + ctx["receipt_id"].replace("-", "")[:8]
    none = env.server.trail_locate(memory_ids=["not-a-node"])          # an answer naming nothing
    assert none["stations"] == [] and none["ignored"] == 1 and len(route_rows(env)) == len(before) + 1

def test_apart_from_the_receipt_nothing_changes(tools_env):
    env, ids = tools_env; snap = env.snapshot()        # every table's rows, access counts, operation_log, v2 bytes
    for _ in range(3):
        env.server.trail_route(goal="fix", memory_ids=ids[:1]); env.server.trail_next(memory_ids=ids[:2])
        env.server.trail_locate(context="engram/server.py")
    assert env.snapshot().without("memory_log") == snap.without("memory_log")
    assert env.snapshot().log_rows_except("route_shown") == snap.log_rows_except("route_shown")

def test_recall_is_the_same_with_the_tools_on_and_off(tmp_path, monkeypatch):
    on, off = recall_with_tools(tmp_path, monkeypatch, True), recall_with_tools(tmp_path, monkeypatch, False)
    assert on == off                                 # uninvited=0, no residue: ids and contents

def test_a_re_laned_or_pruned_route_node_is_dropped_then_stale(tools_env):
    env, ids = tools_env
    route = env.server.trail_route(goal=GOAL_NEAR_LAST, memory_ids=[ids[0]])["route"]
    env.store.relane(route[1]["id"], "personal")
    again = env.server.trail_route(goal=GOAL_NEAR_LAST, memory_ids=[ids[0]])
    assert route[1]["id"] not in json.dumps(again)
    env.relane_on_every_recheck()                    # the second computation fails its check too
    assert env.server.trail_route(goal=GOAL_NEAR_LAST, memory_ids=[ids[0]]) == {"end": "stale"}

def test_a_hidden_middle_node_of_a_20_stop_route_is_checked_too(long_route_env):
    env, ids, hidden = long_route_env               # a 20-stop cheapest route; hidden[3] sits in {"skipped": 8}
    env.store.relane(hidden[3], "personal")
    assert hidden[3] not in json.dumps(env.server.trail_route(goal=GOAL_AT_END, memory_ids=[ids[0]]))
    env.store.prune(hidden[4])
    assert hidden[4] not in json.dumps(env.server.trail_route(goal=GOAL_AT_END, memory_ids=[ids[0]]))

def test_lanes(tmp_path, monkeypatch):
    env = tools_env_with(tmp_path / "default", monkeypatch, "")       # lanes missing: work
    assert env.server.trail_locate(memory_ids=["x"], lane="personal") == {"error": "lane not enabled: personal"}
    assert route_rows(env) == []
    for i, raw in enumerate(['"work"', '["work", "work"]', '["other"]', "1"]):
        bad = tools_env_with(tmp_path / f"bad{i}", monkeypatch, f"lanes = {raw}")
        assert bad.server.trail_locate(memory_ids=["x"]) == {"error": "lane not enabled"}
        assert bad.server._trail_graph.lanes_invalid
    empty = tools_env_with(tmp_path / "empty", monkeypatch, "lanes = []")
    assert empty.server.trail_locate(memory_ids=["x"]) == {"error": "lane not enabled: work"}
    assert not empty.server._trail_graph.lanes_invalid and empty.server._trail_graph.lanes == {}
    assert route_rows(empty) == []

def test_arguments_and_the_embedder(tools_env):
    env, ids = tools_env; srv = env.server
    assert srv.trail_locate(memory_ids=["x"], lane="other") == {"error": "Invalid lane: 'other'"}
    assert srv.trail_locate(memory_ids=ids[:7]) == {"error": "at most 6 memory ids"}
    assert srv.trail_next() == {"error": "give context or memory ids"}
    assert srv.trail_route(goal="", memory_ids=ids[:1]) == {"error": "give a goal"}
    env.embedder.fail = RuntimeError("down")
    assert srv.trail_route(goal="g", memory_ids=ids[:1]) == {"error": "embedder unavailable"}
    loc = srv.trail_locate(context="see engram/server.py", memory_ids=ids[:1])
    assert loc["degraded"] == ["embedding"] and {s["why"] for s in loc["stations"]} <= {"given", "words"}
    assert loc["stations"][0]["why"] == "given"

def test_rf4_bad_memory_ids_are_ignored_not_fatal(tools_env):
    env, ids = tools_env; before = len(route_rows(env))
    got = env.server.trail_locate(memory_ids=[3, "", "x" * 65, "nope", "nope"])     # the second "nope" repeats
    assert got["stations"] == [] and got["ignored"] == 5 and len(route_rows(env)) == before
    twice = env.server.trail_locate(memory_ids=[ids[0], ids[0]])                     # TR15: a repeat counts once
    assert [s["id"] for s in twice["stations"] if s["why"] == "given"] == [ids[0]] and twice["ignored"] == 1

def test_n16_next_reads_3_stations_and_an_answer_says_what_it_cut(tools_env):
    env, ids = tools_env
    got = env.server.trail_next(memory_ids=ids[:6])                   # six given stations; T 6.4 reads 3
    assert [s["id"] for s in got["stations"]] == ids[:3] and "cut" not in got
    long = env.server.trail_route(goal="g" * 4_001, context="engram/server.py " + "x" * 4_000)
    assert long["cut"] == ["context", "goal"]
    assert env.server.trail_locate(context="engram/server.py " + "x" * 4_000)["cut"] == ["context"]

def test_rf5_empty_store_names_nothing(tmp_path, monkeypatch):
    empty = tools_env_with(tmp_path / "empty", monkeypatch, "", seed=None)            # no session at all
    got = empty.server.trail_route(goal="anything", context="engram/server.py")
    assert got["note"] == "nothing on the trails is near this context" and trails.named_ids(got) == []
    bare = tools_env_with(tmp_path / "bare", monkeypatch, "", seed="no_vectors")     # trails, no vector anywhere
    got = bare.server.trail_route(goal="anything", memory_ids=bare.ids[:1])
    assert got["end"] == "no_goal" and "nearest" not in got
    assert route_rows(empty) == [] and route_rows(bare) == []
```

`tools_env`, `long_route_env`, `tools_env_with`, `recall_with_tools`, `route_rows`, `GOAL_NEAR_LAST`, `GOAL_AT_END`
and the snapshot helpers join `trails_support.py`, built on Task 17's env with a `FakeProvider` whose vectors are
chosen so the goal words sit near a route's last stop. `tools_env`'s `ids` begin with at least six work-lane nodes
of the graph. `tools_env_with(path, monkeypatch, trails_lines, *, seed="routes")` writes `[trails]\ntools = true\n`
plus the given lines, seeds closed sessions with vectors (`"routes"`), without vectors (`"no_vectors"`) or nothing
(`None`), waits for the build, and exposes `ids`. `recall_with_tools(tmp_path, monkeypatch, on)` seeds a fresh
store under `tmp_path / ("on" if on else "off")` from the same seed and recalls once. A first recall on a shared
store would change access counts, and they can shift the second recall.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_tools.py -k "receipt or nothing_changes or recall_is or stale or hidden or lanes or arguments or rf4 or rf5 or n16"`
Expected: FAIL, the tools still answer `{"note": "trail graph not ready"}` or lack their bodies.

- [ ] **Step 3: Implement the three tools**

Order: validate the lane (recall's words), then `[trails] lanes` (`lane not enabled`), the graph's readiness, the
ids (TR15), the inputs. Embed `[x, y]` (or `[y]`, or `[x]`) once with `trails.embed_queries`. Anchors and
`fts_hits` over `_storage.search_fts_ids`. Locate, then route or forward lookup; `wall_s=ROUTE_WALL_S` for the
route. Recheck every node of the computed route, every station and every other named memory, hidden stops included;
on a failure remove those memories from the cached graph and compute once more, and on a second failure answer
`{"end": "stale"}`. Summaries are read from `_storage` when the answer is built. `fit` the answer, then write one
receipt when it names a memory, with `receipt_id = str(uuid.uuid4())` passed as `add_log_entry`'s `id`, so the row's
id is the receipt id (T 6.6). `trail_next` runs the forward lookup from the first `FORWARD_STATIONS` stations only
(T 6.4). When the context or goal was longer than `MAX_TEXT` characters, the answer carries `cut` (TR17), unless it
is an error, the not-ready note or `{"end": "stale"}`. No access
count, no `_mutation_logged`, no `_apply_recall_bias`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_tools.py tests/test_server.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/server.py engram/tests/trails_support.py engram/tests/test_trail_tools.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Server: trail_locate, trail_route and trail_next, rechecked, sourced and receipted (T 6.6)"
```

### Task 19: Reflection

**Files:**
- Modify: `engram/reflection.py` (`Reflector.__init__`, `:53-67`; `reflect`, `:732-775`), `engram/server.py`
  (`Reflector(...)`, `:1418-1430`)
- Test: `engram/tests/test_trail_tools.py`

**Interfaces:**
- Consumes: Task 18's counters; Task 7's report block.
- Produces: `Reflector(..., trails_reporter: Callable[[], dict] | None = None)`; `Reflector.analyze_trails() ->
  dict` (`{"available": False}` without a reporter); `reflect(focus="trails")`; `server._trail_tools_report() ->
  dict`, `{"available": False}` when the tools aren't registered, else the graph's `as_of`, `sessions`, `nodes`,
  `steps`, `roads`, `truncated`, `lanes_invalid`, `build_seconds`, `bytes`, `calls`, `ends`, `shrunk`,
  `receipts_written`. `analyze_trails` adds, through its own storage, `route_shown_rows` and `suggested_touches`
  (suggested touches in closed sessions at the graph's `as_of`).

- [ ] **Step 1: Write the failing tests**

```python
def test_reflect_trails_reports_per_call_counts(tools_env):
    env, ids = tools_env
    env.server.trail_route(goal="fix", memory_ids=ids[:1]); env.server.trail_next(memory_ids=ids[:1])
    got = env.server.reflect(focus="trails")["trails"]
    assert got["calls"] == {"trail_locate": 0, "trail_route": 1, "trail_next": 1}
    assert got["receipts_written"] == 2 and got["route_shown_rows"] == 2 and "suggested_touches" in got

def test_reflect_trails_is_unavailable_when_off(tmp_path, monkeypatch):
    env = trail_tools_env(tmp_path, monkeypatch, ""); env.pre_serve(); env.wait_maintenance()
    assert env.server.reflect(focus="trails") == {"trails": {"available": False}}
    assert Reflector(env.store.storage).reflect(focus="trails") == {"trails": {"available": False}}

def test_reflect_category_evolution_carries_the_trails_block(tmp_path, monkeypatch):
    env = trail_init_env(tmp_path, monkeypatch, GATE_ON); seed_road_sessions(env.store); env.start()
    assert set(env.server.reflect(focus="category_evolution")["category_evolution"]["trails"]) == TRAIL_REPORT_KEYS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trail_tools.py -k reflect`
Expected: FAIL, `KeyError: 'trails'`.

- [ ] **Step 3: Implement `trails_reporter`, `analyze_trails` and the server's reporter**

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2, adding `tests/test_reflection.py`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/reflection.py engram/server.py engram/tests/test_trail_tools.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Reflection: reflect(focus='trails') through a trails_reporter (T 6.6)"
```

### Task 20: The in-process model loads from the local cache only when asked

**Files:**
- Modify: `engram/embeddings.py` (`NomicEmbedProvider.__init__`, `:73-84`; `create_embedding_provider`,
  `:200-207`)
- Test: `engram/tests/test_trails_embeddings.py`

**Interfaces:**
- Produces: `NomicEmbedProvider(local_files_only: bool = False)`, passing the keyword to fastembed's `TextEmbedding`;
  `create_embedding_provider(local_files_only: bool = False)`, passing it only to the in-process provider. Servers
  and `embedder_service.py` keep calling without it. fastembed pops the keyword in
  `text/text_embedding_base.py:19`; it reaches the loader through `**kwargs` at `text/text_embedding.py:114-123` and
  is used at `text/onnx_embedding.py:254` (the final check's FN2).

- [ ] **Step 1: Write the failing tests**

```python
def test_the_keyword_reaches_text_embedding(monkeypatch):
    seen = []
    monkeypatch.setattr("fastembed.TextEmbedding", recorder(seen))
    embeddings.NomicEmbedProvider(local_files_only=True); embeddings.NomicEmbedProvider()
    assert [kw["local_files_only"] for kw in seen] == [True, False]

def test_create_passes_it_only_to_the_in_process_provider(monkeypatch):
    seen = []; monkeypatch.setattr("fastembed.TextEmbedding", recorder(seen))
    monkeypatch.delenv("ENGRAM_EMBEDDER_SOCKET", raising=False)
    assert isinstance(embeddings.create_embedding_provider(local_files_only=True), embeddings.NomicEmbedProvider)
    assert seen[-1]["local_files_only"] is True
    monkeypatch.setenv("ENGRAM_EMBEDDER_SOCKET", "/nonexistent.sock")
    assert isinstance(embeddings.create_embedding_provider(local_files_only=True), embeddings.RemoteEmbedProvider)
```

`recorder(seen)` returns a stand-in class whose `__init__` records its keywords and whose `model.tokenizer` accepts
`enable_truncation`; it joins `trails_support.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails_embeddings.py`
Expected: FAIL, `TypeError: NomicEmbedProvider.__init__() got an unexpected keyword argument 'local_files_only'`.

- [ ] **Step 3: Add the keyword to both**

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2, adding `tests/test_embeddings.py tests/test_embedder_service.py`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/embeddings.py engram/tests/trails_support.py engram/tests/test_trails_embeddings.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Embeddings: local_files_only for the in-process model, default unchanged (T 7 step 8.2, R19)"
```

### Task 21: The read-only CLI

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trails_cli.py`

**Interfaces:**
- Consumes: Tasks 10 to 14; `paths.connect_ro` (`engram/paths.py:397-409`).
- Produces: `main(argv: list[str] | None = None) -> int` with T 11's flags exactly: a positional path,
  `--categories PATH`, `--lane LANE` (default `work` on a plain copy), `--as-of T` (ISO, default the newest
  timestamp in the store), `--route A B`, `--route-goal A G`, `--next A`, `--evaluate`, `--seed N`,
  `--imprint-use USE_ID`, `--deadline SECONDS`, `--json`; `newest_timestamp(conn) -> int`. Output holds ids,
  counts and `total_changes` (always 0), never content. The report is built whole in memory and printed in one
  write at the end.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("args", [["--route", "A", "B"], ["--route-goal", "A", "G"], ["--next", "A"],
                                  ["--categories", "V2", "--route", "A", "B"]])
def test_the_cli_changes_no_byte_and_prints_ids_and_counts_only(tmp_path, capsys, args):
    s, v2, names = cli_store(tmp_path)                    # a road store, its v2 copy, ids by name
    before = {p: sha256(p) for p in (s.path, v2)}
    argv = [str(s.path), "--json", *[str(v2) if a == "V2" else names.get(a, a) for a in args]]
    assert trails.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["total_changes"] == 0 and {p: sha256(p) for p in before} == before
    assert not any(c in json.dumps(out) for c in s.contents())

def test_as_of_defaults_to_the_newest_timestamp(tmp_path):
    s, _, _ = cli_store(tmp_path)
    assert trails.newest_timestamp(s.ro()) == max(T(r) for r in s.all_timestamps())
```

`cli_store(tmp_path)` builds a road store, runs the observer pass into a `categories_v2.db`, closes both writers so
the files are quiescent before their SHA-256 is taken, and returns the store, the v2 path and the ids by name (`A`,
`B`, `G`). `Store.contents()` and `Store.all_timestamps()` join `trails_support.py`. The module uses
`no_real_model`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails_cli.py`
Expected: FAIL, `AttributeError: module 'trails' has no attribute 'main'`.

- [ ] **Step 3: Implement `main` and `newest_timestamp`**

`--route-goal A G` routes from A to the goal set of G's stored vector; `--next A` runs the forward lookup from A.
Each database opens `mode=ro` with `query_only`; sqlite-vec loads as `paths.connect_ro` does. Add
`if __name__ == "__main__": raise SystemExit(main())`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/trails.py engram/tests/trails_support.py engram/tests/test_trails_cli.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: the read-only CLI for routes, goal routes and forward lookups (T 11)"
```

### Task 22: The imprint check

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trails_cli.py`

**Interfaces:**
- Consumes: Task 21; the imprints plan's layout and `meta.instance_id_origin = 'imprint'` (D-I2).
- Produces: `class ImprintRefused(Exception)`; `ImprintUse`, a dataclass `(db: Path, root: Path, imprint_id: str,
  allow: Path, allow_sha256: str, valid_until: int)` with `still_valid(now: int) -> bool`; `check_imprint(db: Path,
  use_id: str | None, lane: str | None, *, now: int) -> ImprintUse`; `ALLOW_CHANGED = 3`. `now`, `valid_until` and
  `still_valid`'s `now` are integer UTC seconds, as the allow file holds them (I 12's example, `1800727950`); `main`
  passes `int(time.time())` (TR22). `main` runs the check on a file whose origin is `imprint`, opens it with
  `store_reader.connect(path, immutable=True, vec=True)` (`mode=ro&immutable=1` with sqlite-vec, the imprints plan's
  Task 32), and at the end runs `still_valid`; on a failure it prints nothing to standard output and returns 3. A
  refusal prints one line to standard error and returns 2. The check lives only in `main`'s path, never in the
  derivation (YN5). `--as-of` stays ISO and becomes microseconds.

- [ ] **Step 1: Write the failing tests**

```python
REFUSALS = {
    "no_use": dict(use=None), "slash": dict(use="a/b"), "dots": dict(use=".."),
    "dir_name": dict(rename_dir=True), "elsewhere": dict(allow_at="imprint_dir"), "symlink": dict(symlink=True),
    "other_imprint": dict(allow={"instance_id": "other"}), "other_action": dict(allow={"actions": ["read", "recall"]}),
    "other_purpose": dict(allow={"purpose": "calibration"}), "ended": dict(allow={"valid_until": PAST}),
    "tombstone": dict(tombstone=True), "state_gone": dict(remove_state=True), "no_lane": dict(lane=None),
    "report_exists": dict(use_file="report.json"), "result_exists": dict(use_file="result.json")}

@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_r13_the_imprint_check_refuses(tmp_path, capsys, case):
    imp = imprint_layout(tmp_path, **REFUSALS[case])          # ~/.engram/imprints/ as I 10 and 12 lay it out
    assert trails.main(imp.argv) == 2 and capsys.readouterr().out == ""

def test_r13_a_valid_use_opens_the_file_immutable_and_changes_no_byte(tmp_path, capsys, monkeypatch):
    imp = imprint_layout(tmp_path); before = sha256(imp.db); opened = spy(monkeypatch, "sqlite3.connect")
    assert trails.main(imp.argv) == 0
    assert any("immutable=1" in str(c.args[0]) for c in opened) and sha256(imp.db) == before

@pytest.mark.parametrize("change", ["tombstone", "remove_allow", "end_passed", "shortened_ahead"])
def test_r13_a_change_during_the_run_discards_the_report(tmp_path, capsys, monkeypatch, change):
    imp = imprint_layout(tmp_path)
    monkeypatch.setattr(trails, "evaluate", mutate_then_report(imp, change))
    assert trails.main(imp.argv) == 3 and capsys.readouterr().out == ""

def test_yn1_as_of_composes_with_the_imprint_use(tmp_path, capsys):
    imp = imprint_layout(tmp_path, last_hour_session=True)    # one session wrote in the copy's last hour
    trails.main(imp.argv); default = json.loads(capsys.readouterr().out)
    trails.main(imp.argv + ["--as-of", imp.t1_plus_two_hours]); later = json.loads(capsys.readouterr().out)
    assert later["counts"]["closed_sessions"] == default["counts"]["closed_sessions"] + 1
```

`imprint_layout(tmp_path, **options)` builds the root, the 0555 imprint directory, `<id>.state/uses/` with a
0400 allow file holding I 12's keys, and returns `db`, `argv` (`[db, "--evaluate", "--lane", "work", "--seed",
"7", "--deadline", "1740", "--json", "--imprint-use", <uuid4>]`), `PAST`, and `t1_plus_two_hours`;
`mutate_then_report` joins too. Both go in `trails_support.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails_cli.py -k "r13 or yn1"`
Expected: FAIL, `AttributeError: module 'trails' has no attribute 'check_imprint'` or wrong exit codes.

- [ ] **Step 3: Implement `check_imprint`, `ImprintUse` and the end check**

T 7's checks 1 to 7 in order: the directory name equals `meta.instance_id`; the use id matches
`[A-Za-z0-9-]{1,64}` and the allow file is read only at `<root>/<id>.state/uses/<use id>.allow.json`, no symlink
on any part of the path (`os.lstat` each component); no tombstone and the state directory exists; the allow file
names this `instance_id`, the action `route`, the purpose `trail-evaluation`, and `valid_until > now`; the use's
directory holds neither `report.json` nor `result.json`; an explicit `--lane`. Until Task 23, `evaluate` returns the
derivation's counts, `counts.closed_sessions` among them; the report keeps that count from then on. The test module
uses `no_real_model` (Global Constraints). The imprint connection must load sqlite-vec: `--evaluate` reads
`episode_vectors` and `semantic_vectors`, which are `vec0` tables, and `store_reader.connect` without `vec=True` loads
no extension (`engram/store_reader.py:44-55`), so they would fail with "no such module: vec0". Task 27 runs the real
`--evaluate` on a real imprint and catches that.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails_cli.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/trails.py engram/tests/trails_support.py engram/tests/test_trails_cli.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: the imprint check, one run per use and exit 3 on a changed allow file (T 7, R13)"
```

### Task 23: The evaluation's split, graphs and route gate

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trails_eval.py`

**Interfaces:**
- Consumes: Tasks 3 to 4, 8, 10, 13, 14.
- Produces:
  - `stream_seed(seed: int, purpose: str) -> int` (`int.from_bytes(sha256(f"{seed}:{purpose}".encode()).digest()[:8],
    "big")`), purposes `shuffle:0` to `shuffle:9`, `bootstrap:route:T-B`, `bootstrap:route:T-S`,
    `bootstrap:goal:T-N`, `bootstrap:goal:T-B`;
  - `Split`, a dataclass `(cutoff: int, training: list[str], held_out: list[str])`; `split_sessions(trail_set, lane)
    -> Split` (TR19);
  - `Qualified`, a dataclass `(session: str, s: str, g: str, interior: frozenset[str], touches: tuple[str, ...])`;
    `qualify(trail_set, split, lane, lookup, counts) -> list[Qualified]` (`steered` counted);
  - `graph_T(trail_set, split, lane, lookup, vectors) -> TrailGraph`, `graph_S(trail_set, split, lane, lookup,
    vectors, rng) -> TrailGraph`, `graph_B(T: TrailGraph) -> TrailGraph` (8 nearest by angle, undirected, cost the
    angle, rows in blocks of `B_BLOCK`);
  - `scores(route_interior: Sequence[str], truth: frozenset[str]) -> tuple[float, float, float]`;
  - `paired_bootstrap(diffs: np.ndarray, rng) -> tuple[float, float]` (mean, lower bound);
  - `route_gate(qualified, T, S_list, B, seed) -> dict`;
  - `evaluate(conn, *, lane: str, seed: int, as_of: int, embedder=None, deadline_s: float | None = None,
    clock=time.monotonic) -> dict`, the report's body. A route of more than 64 stops counts as no route.

- [ ] **Step 1: Write the failing tests**

```python
def test_mf7_planted_ordered_routes_pass(tmp_path):            # 200 closed sessions: 40 held out and scored
    rep = trails.evaluate(planted_routes_store(tmp_path, sessions=200).ro(), lane="work", seed=7, as_of=END)
    assert rep["route_gate"]["verdict"] == "pass"

def test_mf7_popularity_without_order_fails_t_minus_s(tmp_path):
    rep = trails.evaluate(popularity_store(tmp_path, sessions=200).ro(), lane="work", seed=7, as_of=END)
    assert rep["route_gate"]["verdict"] == "fail" and not rep["route_gate"]["T-S"]["passed"]

def test_rmf2_co_retrieval_alone_fails_t_minus_s(tmp_path):
    rep = trails.evaluate(co_retrieval_store(tmp_path, sessions=200).ro(), lane="work", seed=7, as_of=END)
    assert rep["route_gate"]["verdict"] == "fail" and not rep["route_gate"]["T-S"]["passed"]   # decided, not skipped

def test_fewer_than_30_qualifying_is_not_evaluable(tmp_path):    # 100 closed sessions: 20 held out
    rep = trails.evaluate(planted_routes_store(tmp_path, sessions=100).ro(), lane="work", seed=7, as_of=END)
    assert rep["route_gate"]["verdict"] == "not evaluable"

def test_no_training_touch_at_or_after_the_cutoff_enters_t(tmp_path):
    s = planted_routes_store(tmp_path, sessions=80); ts = trails.derive_trails(s.ro(), END)
    split = trails.split_sessions(ts, "work")
    T_ = trails.graph_T(ts, split, "work", trails.MemoryLookup(s.ro()), {})
    late = {m for m in s.memory_ids() if s.created_at(m) >= split.cutoff}
    assert not late & set(T_.nodes) and all(e.latest is None or e.latest < split.cutoff for es in T_.out for e in es)

def test_steered_sessions_qualify_for_neither_gate_and_suggested_steps_are_in_no_graph(tmp_path):
    s = planted_routes_store(tmp_path, sessions=80, steer_held_out=5, suggest_training=True)
    rep = trails.evaluate(s.ro(), lane="work", seed=7, as_of=END)
    assert rep["counts"]["steered"] == 5
    ts = trails.derive_trails(s.ro(), END); split = trails.split_sessions(ts, "work")
    lookup = trails.MemoryLookup(s.ro())
    for g in (trails.graph_T(ts, split, "work", lookup, {}),
              trails.graph_S(ts, split, "work", lookup, {}, np.random.default_rng(1))):
        assert not any(e.suggested for es in g.out for e in es)

def test_rf5_empty_store_is_not_evaluable(tmp_path):
    rep = trails.evaluate(Store(tmp_path).ro(), lane="work", seed=7, as_of=END)
    assert rep["route_gate"]["verdict"] == "not evaluable" and rep["goal_gate"]["verdict"].startswith("not evaluable")

def test_seeds_derive_one_stream_per_purpose():
    assert trails.stream_seed(7, "shuffle:0") == int.from_bytes(hashlib.sha256(b"7:shuffle:0").digest()[:8], "big")
```

`planted_routes_store` (several fixed routes of six memories with random vectors, each session walking one route in
order, days apart), `popularity_store` (the same popular memories touched in random order), `co_retrieval_store`
(memories only ever cited together from one recall), the `steer_held_out` and `suggest_training` options,
`Store.memory_ids()`, `Store.created_at(id)`, `on_day` and `END` join `trails_support.py` (T 13 leaves their design
to the builder). The module uses `no_real_model`.

In every one of these stores, `sessions` counts all closed sessions in the lane, and only the held-out
`ceil(0.20 · sessions)` are scored (TR19). A gate needs 30 qualifying sessions, so a test that expects `pass`,
`fail` or reported numbers uses 200 sessions (40 held out), and a "fewer than 30" test uses 100 (20 held out). Days
apart, 200 sessions run past October, so these stores keep their own clock: session i walks at `on_day(i, 10)`,
where `on_day(i, hh=0, mm=0) -> str` is 2026-10-01T00:00Z plus i days, hh hours and mm minutes. `END =
T(on_day(400))` follows every planted session. `at(day, …)` stays for the small stores of other tasks.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails_eval.py`
Expected: FAIL, `KeyError: 'route_gate'`.

- [ ] **Step 3: Implement the split, qualification, the three graphs, scores, the bootstrap and the route gate**

Routing uses A* with the expansion bound only: every search passes `wall_s=None`, so no route is cut by wall time and
the hashed report holds no count that depends on the machine (T 7 steps 4 and 7). The deadline of step 10 is the
evaluation's only wall clock, and a run that hits it reports `limit`. The report also gives reach, hop ratio, the
detour hit rate over training detours (`find_detours` on training trails) and the next hit (Task 24 supplies the
entries). Counts and rates only, never content or ids.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/trails.py engram/tests/trails_support.py engram/tests/test_trails_eval.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: the route gate against shuffled trails and nearest neighbours (T 7 steps 1-7)"
```

### Task 24: The goal gate, the embedder and offline

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trails_eval.py`

**Interfaces:**
- Consumes: Tasks 13, 20, 23; `embeddings.create_embedding_provider(local_files_only=True)`,
  `EmbedderUnavailableError`.
- Produces: `open_embedder() -> tuple[object | None, dict | None]` (the provider and `{"provider": "shared" |
  "in-process", "model": EMBED_MODEL}`, or `(None, None)` on `ImportError`, `ValueError` or
  `EmbedderUnavailableError`). `RemoteEmbedProvider.__init__` only stores the socket path and first connects on
  `embed` (`engram/embeddings.py:151-153`), so a socket nobody serves passes `open_embedder`. W therefore treats
  `EmbedderUnavailableError` from any embed, the embedder check's first one included, as "not evaluable: no
  embedder", and the report's `embedder` is then null (T 7 step 7: "null when W had none"). W's verdict is decided
  in T 7 step 8's order: no embedder, then embedder mismatch, then fewer than 30.
  `embedder_check(conn, lane, provider) -> float | None` (median cosine over the
  `EMBED_CHECK_N` earliest episodes with vectors, by `(created_at, id)`, embedded with `search_document`);
  `goal_gate(conn, qualified, T, B, provider, seed, lookup, counts) -> dict`; the stored-vector diagnostic,
  labelled `document-to-document`, which reads its vectors through `_diagnostic_vectors(conn, qualified) ->
  dict[str, tuple[np.ndarray, np.ndarray]]` (`v(s)` and `v(w)` per session) and feeds nothing into W's verdict.
  `main --evaluate` calls `open_embedder()`; tests pass `embedder=`.

- [ ] **Step 1: Write the failing tests**

```python
def test_w_planted_routes_ending_in_a_summary_pass(tmp_path):
    s = planted_routes_store(tmp_path, sessions=200, end_with_summary=True)
    rep = trails.evaluate(s.ro(), lane="work", seed=7, as_of=END, embedder=DocumentEchoProvider(s))
    assert rep["goal_gate"]["verdict"] == "pass" and rep["goal_gate"]["regime"] == "query-to-document"

def test_w_goal_words_next_to_every_piece_fail_t_minus_n(tmp_path):
    s = planted_routes_store(tmp_path, sessions=200, end_with_summary=True, pieces_near_goal=True)
    rep = trails.evaluate(s.ro(), lane="work", seed=7, as_of=END, embedder=DocumentEchoProvider(s))
    assert rep["goal_gate"]["verdict"] == "fail" and not rep["goal_gate"]["T-N"]["passed"]   # decided, not skipped

def test_w_fewer_than_30_is_not_evaluable(tmp_path):
    s = planted_routes_store(tmp_path, sessions=100, end_with_summary=True)
    assert trails.evaluate(s.ro(), lane="work", seed=7, as_of=END,
                           embedder=DocumentEchoProvider(s))["goal_gate"]["verdict"] == "not evaluable"

def test_w_never_sees_w_sizes_n_by_t_and_counts_empty_truth(tmp_path):
    s = planted_routes_store(tmp_path, sessions=200, end_with_summary=True, truth_inside_entries=3)
    trace = []
    rep = trails.evaluate(s.ro(), lane="work", seed=7, as_of=END, embedder=DocumentEchoProvider(s), trace=trace)
    assert all(t["w"] not in t["T_nodes"] and t["w"] not in t["B_nodes"] for t in trace)
    assert all(t["n_size"] == (t["t_named"] or 4) for t in trace)
    assert rep["counts"]["truth_inside_entries"] == 3

def test_w_embeds_content_of_s_and_w_with_search_query_through_the_tools_function(tmp_path, monkeypatch):
    s = planted_routes_store(tmp_path, sessions=200, end_with_summary=True, long_contents=True)
    p = DocumentEchoProvider(s); calls = spy(monkeypatch, "trails.embed_queries")
    one = trails.evaluate(s.ro(), lane="work", seed=7, as_of=END, embedder=p)
    query_calls = [c for c in p.calls if c[1] == "search_query"]
    assert calls and all(len(t) <= 4000 for texts, _ in query_calls for t in texts)
    assert query_calls[0][0] == [s.content(first_s(s))[:4000], s.content(first_w(s))[:4000]]
    p.rotate_queries = True                                   # different query vectors, same stored ones
    assert trails.evaluate(s.ro(), lane="work", seed=7, as_of=END, embedder=p)["goal_gate"] != one["goal_gate"]

def test_w_without_an_embedder_or_with_a_mismatched_one(tmp_path):
    s = planted_routes_store(tmp_path, sessions=200, end_with_summary=True)
    none = trails.evaluate(s.ro(), lane="work", seed=7, as_of=END, embedder=None)
    assert none["goal_gate"]["verdict"] == "not evaluable: no embedder" and none["route_gate"]["verdict"] == "pass"
    assert none["embedder"] is None
    off = trails.evaluate(s.ro(), lane="work", seed=7, as_of=END, embedder=RandomProvider())
    assert off["goal_gate"]["verdict"] == "not evaluable: embedder mismatch"

def test_r19_offline_with_an_empty_cache_and_no_socket(tmp_path, monkeypatch, capsys):
    s = planted_routes_store(tmp_path / "s", sessions=40, end_with_summary=True)
    cache = tmp_path / "cache"; cache.mkdir(); monkeypatch.setattr("embeddings._CACHE_DIR", str(cache))
    monkeypatch.delenv("ENGRAM_EMBEDDER_SOCKET", raising=False)
    kw = spy(monkeypatch, "embeddings.create_embedding_provider"); forbid_non_unix_connect(monkeypatch)
    assert trails.main([str(s.path), "--evaluate", "--seed", "7", "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert kw[0].kwargs == {"local_files_only": True}
    assert rep["goal_gate"]["verdict"] == "not evaluable: no embedder" and rep["embedder"] is None
    assert [p for p in cache.rglob("*") if p.is_file()] == []          # FS1: empty directories are allowed

def test_r19_a_socket_nobody_serves_loads_no_local_model(tmp_path, monkeypatch, capsys):
    s = planted_routes_store(tmp_path / "s", sessions=40, end_with_summary=True)
    monkeypatch.setenv("ENGRAM_EMBEDDER_SOCKET", str(tmp_path / "nobody.sock"))
    monkeypatch.setattr("embeddings.NomicEmbedProvider.__init__", raises(AssertionError("loaded a local model")))
    assert trails.main([str(s.path), "--evaluate", "--seed", "7", "--json"]) == 0   # open_embedder succeeds; the
    rep = json.loads(capsys.readouterr().out)                                          # first embed raises (SF1)
    assert rep["goal_gate"]["verdict"] == "not evaluable: no embedder" and rep["embedder"] is None

def test_the_stored_vector_diagnostic_never_changes_ws_verdict(tmp_path, monkeypatch):
    s = planted_routes_store(tmp_path, sessions=200, end_with_summary=True)
    one = trails.evaluate(s.ro(), lane="work", seed=7, as_of=END, embedder=DocumentEchoProvider(s))
    assert one["goal_gate"]["diagnostic"]["regime"] == "document-to-document"
    monkeypatch.setattr(trails, "_diagnostic_vectors", lambda *a, **k: scrambled())
    two = trails.evaluate(s.ro(), lane="work", seed=7, as_of=END, embedder=DocumentEchoProvider(s))
    assert two["goal_gate"]["verdict"] == one["goal_gate"]["verdict"] == "pass"
```

The two r19 tests keep 40 sessions: "no embedder" is decided before the count, so their verdict doesn't depend on
how many sessions qualify. Every other test here that expects a verdict or compares numbers uses 200 (Task 23's
note on store sizes).

`DocumentEchoProvider(s)` returns each text's stored vector for `search_document` (so the embedder check passes) and
a fixed small rotation of it for `search_query`, or a different rotation once `rotate_queries` is set, `RandomProvider`, `forbid_non_unix_connect` (patches
`socket.socket.connect` to fail any family but `AF_UNIX`), `first_s`, `first_w`, `scrambled` and the store options
join `trails_support.py`. `evaluate` takes `trace: list | None = None` for tests.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails_eval.py -k "w_ or r19 or diagnostic"`
Expected: FAIL, `KeyError: 'goal_gate'`.

- [ ] **Step 3: Implement measure W**

Steps 8.1 to 8.9 of T 7: qualification (not steered; an episode in the lane at or after the touch of `g`; `w` the
last by `(created_at, id)`); `x = content(s)`, `y = content(w)` through `embed_queries` in one batch; `empty_text`;
the embedder check before scoring (`≥ EMBED_CHECK_MIN`; an `EmbedderUnavailableError` from it or any later W embed
makes W "not evaluable: no embedder" with `embedder` null); entries by `locate` over T with words from the imprint's
own `episode_fts` and `semantic_fts` kept only when nodes of T; `Γ` over T; methods T, B and N (N's size from T,
`N_EMPTY_SIZE` when T names nothing outside the entries); scores; the gate; the also-reported values; the
diagnostic for sessions with both stored vectors, `no_stored_vector` for the rest. The next hit (step 5) uses these
entries, or the near stations of `v(s)` when the check fails, and the report names its regime.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails_eval.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/trails.py engram/tests/trails_support.py engram/tests/test_trails_eval.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: the goal gate against nearest-to-goal and similarity routing, offline only (T 7 step 8)"
```

### Task 25: The report, the deadline and the size limit

**Files:**
- Modify: `engram/trails.py`
- Test: `engram/tests/test_trails_eval.py`

**Interfaces:**
- Consumes: Tasks 21 to 24.
- Produces: `report_bytes(report: dict) -> bytes` (canonical JSON, sorted keys, no spaces, every float rounded to 4
  places, NaN as null); the report names `lane` and `embedder`; `--deadline` checked between sessions, past which
  both gates read `"not evaluable: limit"`; T over `EVAL_MAX_NODES` nodes gives `"not evaluable: too large"` for
  both.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_report_is_byte_identical_for_the_same_store_seed_lane_and_provider(tmp_path, capsys, monkeypatch):
    s = planted_routes_store(tmp_path, sessions=200, both_lanes=True)         # 200 in each lane: the gates run
    monkeypatch.setattr(trails, "open_embedder",
                        lambda: (DocumentEchoProvider(s), {"provider": "in-process", "model": trails.EMBED_MODEL}))
    searches = spy(monkeypatch, "trails.astar")
    runs = []
    for lane in ("work", "work", "personal"):
        trails.main([str(s.path), "--evaluate", "--lane", lane, "--seed", "7", "--json"])
        runs.append(capsys.readouterr().out.encode())
    assert runs[0] == runs[1] and hashlib.sha256(runs[0]).digest() != hashlib.sha256(runs[2]).digest()
    rep = json.loads(runs[0]); assert rep["lane"] == "work" and "embedder" in rep
    assert rep["route_gate"]["verdict"] == "pass"                               # shuffles and bootstrap really ran
    assert searches and all(c.kwargs.get("wall_s") is None for c in searches)   # no wall-time count is hashed

def test_a_passed_deadline_reports_limit_for_both_gates(tmp_path):
    s = planted_routes_store(tmp_path, sessions=200, end_with_summary=True)
    rep = trails.evaluate(s.ro(), lane="work", seed=7, as_of=END, embedder=DocumentEchoProvider(s),
                          deadline_s=1.0, clock=iter([0.0, 0.5, 2.0, 2.0, 2.0] + [3.0] * 10_000).__next__)
    assert rep["route_gate"]["verdict"] == rep["goal_gate"]["verdict"] == "not evaluable: limit"

def test_a_run_killed_by_the_memory_cap_writes_no_report(tmp_path, capsys, monkeypatch):
    s = planted_routes_store(tmp_path, sessions=40)
    monkeypatch.setattr(trails, "evaluate", raises(MemoryError()))
    with pytest.raises(MemoryError): trails.main([str(s.path), "--evaluate", "--seed", "7", "--json"])
    assert capsys.readouterr().out == ""

def test_a_graph_over_20000_nodes_is_too_large(tmp_path, monkeypatch):
    assert trails.EVAL_MAX_NODES == 20_000
    monkeypatch.setattr(trails, "EVAL_MAX_NODES", 10)                         # TR13
    rep = trails.evaluate(planted_routes_store(tmp_path, sessions=200).ro(), lane="work", seed=7, as_of=END)
    assert rep["route_gate"]["verdict"] == rep["goal_gate"]["verdict"] == "not evaluable: too large"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails_eval.py -k "byte_identical or deadline or memory_cap or too_large"`
Expected: FAIL.

- [ ] **Step 3: Implement `report_bytes`, the deadline and the size limit**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails_eval.py tests/test_trails_cli.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/trails.py engram/tests/test_trails_eval.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: a canonical, hashable report and fixed limits that never decide a pass (T 7 steps 7, 10)"
```

### Task 26: The synthetic imprint

**Files:**
- Test: `engram/tests/test_trails_imprint.py`

**Interfaces:**
- Consumes: Tasks 3, 4, 22; the imprints plan's `imprint.make_plan` and `imprint.build` (D-I1) and its
  `imprint.count_roads_and_trails` (its Task 35).
- Produces: `trails_support.synthetic_source(tmp_path) -> Store` and `trails_support.build_imprint(source, dest, *,
  route: bool) -> Path`, the second calling the imprints plan's builder with a work-lane scope whose `until` is t₁.
  `T1` is in the trails support's microseconds and a whole second; `HOUR = 3_600_000_000`.

`build_imprint` is the imprints plan's own path, in this order, on one fixture root, `dest`:

```python
def build_imprint(source, dest, *, route):
    from tests.imprint_support import HOME, plan_args     # that plan's builders: ledger, station context, scope
    import imprint
    t1_s = T1 // 10**6                                    # TR22: the imprints code takes UTC seconds
    args = plan_args(dest, store=lambda _: source.storage, route=route, until=t1_s)
    plan = imprint.make_plan(*args)                       # as that plan's Task 21 test calls it
    return imprint.build(plan.id, home=HOME(dest), now=t1_s).dir / "imprint.db"
```

`plan_args` lays out what `make_plan` needs under `dest`: the permissions ledger with the source registered to
`person:andy` (that plan's Task 8 `ledger`), the station context `read_context` reads (its R7), and a work-lane
selection and terms; `route` adds the action `route` and the purpose `trail-evaluation` (its Task 7). The source
holds no row at or after t₁ (XS1), and `now` is t₁ in seconds.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.fixture
def pair(tmp_path):                                # sessions in both lanes; recalls with and without a lane;
    src = synthetic_source(tmp_path / "src")         # cites of work memories; one target pruned to cold;
    return src, build_imprint(src, tmp_path / "imp", route=True)    # no source row at or after t1 (XS1)

def test_the_imprint_loses_cited_touches_of_mixed_recalls_and_says_how_many(pair, record_property):
    src, imp = pair; as_of = T1 + 2 * HOUR
    s_tr = trails.derive_trails(src.ro(), as_of, lanes=("work",))
    i_tr = trails.derive_trails(ro(imp), as_of, lanes=("work",))
    assert cited(i_tr) <= cited(s_tr)                                          # nothing the source lacks (I6)
    lost = cited(s_tr) - cited(i_tr)
    assert cited_from(src, mixed_or_cold_recalls(src)) <= lost and lost      # those recalls' touches are gone
    record_property("cited_touches_lost", len(lost))

def test_lane_filtered_recalls_keep_their_touches_and_the_one_target_rule_agrees(pair):
    src, imp = pair; as_of = T1 + 2 * HOUR
    assert cited_from(src, lane_filtered_recalls(src)) <= cited(trails.derive_trails(ro(imp), as_of))
    for row in kept_recall_rows(imp):
        assert one_target_answer(src, row) == one_target_answer(ro(imp), row)

def test_no_kept_row_is_cut_and_an_all_home_route_shown_row_is_gone(pair):
    src, imp = pair
    assert all("cut" not in json.loads(r["context"] or "{}") for r in log_rows(imp))
    assert all_home_route_shown_id(src) not in {r["id"] for r in log_rows(imp)}

def test_closed_sessions_keep_session_ids_and_wrote_touches(pair):
    src, imp = pair; as_of = T1 + 2 * HOUR
    assert wrote(trails.derive_trails(ro(imp), as_of)) == wrote(trails.derive_trails(src.ro(), as_of), lane="work")

def test_without_route_no_trail_of_any_kind(tmp_path, capsys):
    src = synthetic_source(tmp_path / "src"); imp = build_imprint(src, tmp_path / "imp", route=False)
    assert count(imp, "SELECT COUNT(*) FROM memory_log") == 0
    assert count(imp, "SELECT COUNT(*) FROM episodes WHERE session_id IS NOT NULL") == 0
    got = trails.derive_trails(ro(imp), T1 + 2 * HOUR)                         # a library call (YN5)
    assert got.sessions == {} and got.full == {}
    layout = imprint_layout_for(imp, allow_actions=["read", "recall"])         # no allow file can name route
    assert trails.main(layout.argv) == 2
    assert sessions_with_two_work_episodes(src) > 0

def test_trails_read_no_recall_times_or_resonances(pair):
    src, imp = pair; before = trails.derive_trails(ro(imp), T1 + 2 * HOUR)
    changed = writable_copy(imp)                    # bump accessed_count and last_accessed, rewrite resonances
    after = trails.derive_trails(ro(changed), T1 + 2 * HOUR)
    assert {k: v.digest() for k, v in after.full.items()} == {k: v.digest() for k, v in before.full.items()}

def test_xs2_the_admission_count_at_t1_is_the_trail_count_and_is_not_zero(pair):
    src, imp = pair; import imprint                 # derive=None: through the imprints plan's _trail_derive
    with contextlib.closing(store_reader.connect(imp, immutable=True)) as conn:
        n = imprint.count_roads_and_trails(conn, lanes=("work",), as_of=T1 // 10**6)     # UTC seconds (TR22)
        assert n == trails.count_roads_and_trails(conn, T1, lanes=("work",)) and n > 0   # never 0 = 0 = 0
```

The helpers (`T1`, `HOUR`, `ro`, `cited`, `cited_from`, `mixed_or_cold_recalls`, `lane_filtered_recalls`,
`kept_recall_rows`, `one_target_answer`, `log_rows`, `all_home_route_shown_id`, `wrote`, `count`,
`imprint_layout_for`, `sessions_with_two_work_episodes`, `writable_copy`) join `trails_support.py`. The lost count
is recorded in the plan's Results (T 12: "the test records how many"). The module uses `no_real_model`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails_imprint.py -k "not use_ and not unit"`
Expected: FAIL until the helpers exist; then each assertion is checked against the imprints plan's builder.

- [ ] **Step 3: Write the helpers in `trails_support.py`**

No change to `trails.py` should be needed. If one is, it is a bug in Part A or Task 22, fixed there with its own
test first.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 7 passed. Record `cited_touches_lost`. If
`test_xs2_…` raises `ValueError` about microseconds, the imprints plan's `_trail_derive` binds `roads_and_trails`
without converting (TR22): raise it with that plan's owner, and change nothing here.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/tests/trails_support.py engram/tests/test_trails_imprint.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: what a work-lane imprint keeps and loses of the owner's trails (T 7, 12; R17, R18)"
```

### Task 27: With the imprints plan's use step: ends and the unit's socket

**Files:**
- Test: `engram/tests/test_trails_imprint.py`

**Interfaces:**
- Consumes: Task 22; the imprints plan's `imprint.py use`, `station-imprint-use-begin`, `station-imprint-sync`
  (D-I3) and `superyak-peer station-imprint-unit-env` (D-I4), each run against a fixture root under `tmp_path`.
- Produces: tests only.

- [ ] **Step 1: Write the failing tests**

```python
def test_use_a_finished_use_has_no_allow_file_and_its_rerun_is_refused(imprint_fixture, capsys):
    use = imprint_fixture.run_use(lane="work")                 # begin, imprint.py use, sync
    assert not use.allow_path.exists()
    assert trails.main(use.trails_argv) == 2 and capsys.readouterr().out == ""

def test_use_a_shortening_during_the_run_is_allow_changed_and_a_withdrawal_withdrawn(imprint_fixture):
    short = imprint_fixture.run_use(lane="work", during=imprint_fixture.shorten_ahead)
    assert short.trails_exit == 3 and short.finished_end == "allow changed"
    gone = imprint_fixture.run_use(lane="work", during=imprint_fixture.withdraw)
    assert gone.finished_end == "withdrawn"

@pytest.mark.parametrize("runtime, setenv", [(None, False), ({}, False), ({"embedder_socket": None}, False),
                                             ({"embedder_socket": "/run/user/1000/embedder.sock"}, True)])
def test_unit_the_use_carries_the_socket_exactly_when_runtime_json_names_one(tmp_path, runtime, setenv):
    cmd = unit_command(tmp_path, runtime)       # `superyak-peer station-imprint-unit-env` with HOME=tmp_path
    assert ("--setenv=ENGRAM_EMBEDDER_SOCKET=/run/user/1000/embedder.sock" in cmd) is setenv
    assert ("-p UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET" in cmd) is (not setenv)        # XN2, never both
```

`imprint_fixture` and `unit_command` join `trails_support.py`. `unit_command` runs the imprints plan's
`superyak-peer station-imprint-unit-env` (its R15 and R20), whose output its Makefile `eval`s, and splits it as the
shell would.

`imprint_fixture` works on one fixture root, `R = tmp_path / "imprints"`, with `HOME`, `ENGRAM_HOME` and
`STATION_DATA` under `tmp_path`. Station commands run in peer's environment, `uv run --locked --project <repo>/peer
python -m superyak_peer …`, as that plan's Task 40 targets run them. Every time it hands either side is integer UTC
seconds (TR22).

1. **Once:** `build_imprint(synthetic_source(...), R, route=True)` (Task 26). Then the imprints plan's peer builder
   `admitted(...)` brings that imprint to `admitted` in the station's records over `R` (D-I6).
2. **`run_use(lane, during=None)`**, in the order of that plan's `station-imprint-use-run` (its Task 40):
   - `station-imprint-use-begin --id <id> --use trail-evaluation --as andy --imprints-dir R` prints the use id (its
     Task 37);
   - in process, `imprint.use(imprint_id, use_id, root=R, lane=lane, trails_cmd=cmd, now=time.time)` (its Task 38),
     which appends T 7's flags to `cmd` and writes `report.json` and `result.json`;
   - `station-imprint-sync --imprints-dir R` (its Task 39) writes `use-finished`. `finished_end` is that receipt's
     `detail.end`, read with the same builder's `receipts`. `trails_exit` is `result.json`'s `exit`, or `None` when
     a withdrawal removed the state directory.
3. **How `during` gets in.** Without it, `cmd = [sys.executable, <engram>/trails.py]`. With it, `cmd =
   [sys.executable, <tmp>/during.py, <change>, "--"]`, a script the fixture writes. The script imports `trails`,
   wraps `trails.evaluate` so the change happens first, and runs `raise SystemExit(trails.main(rest))` on the
   arguments after `--`. The change must land after `trails.py`'s start check has read the allow file and before its
   end check, as Task 22's `mutate_then_report` does. Mutating and then exec'ing `trails.py` would let the start
   check read the changed file, and the run would end 0.
   - `shorten_ahead` runs the peer's `shorten_imprint(owner, request_id, int(time.time()) + 600, root=R)` (its Task
     31), which rewrites the allow file with a `valid_until` still ahead. `trails.py` sees a changed file and exits 3.
   - `withdraw` runs the peer's `withdraw_imprint(owner, request_id, root=R)` (its Task 30), which leaves a
     tombstone, so the sync records `withdrawn`.
   Each runs in peer's environment through one `uv run --locked --project <repo>/peer python -c …` with the
   fixture's station data. These run the imprints plan's own code; I 16's "Use
ends" tests the station's side in full, `deleted` and `failed` included. `imprint_fixture` runs every subprocess with
`HOME` set to a `tmp_path` directory and without `ENGRAM_EMBEDDER_SOCKET`, so no run it starts can load the Pi's
real model (`embeddings._CACHE_DIR` derives from `Path.home()`, `engram/embeddings.py:12`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails_imprint.py -k "use_ or unit"`
Expected: FAIL until the fixtures exist.

- [ ] **Step 3: Write the fixtures**

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/tests/trails_support.py engram/tests/test_trails_imprint.py
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: one run per use, recorded ends and the unit's socket, with the imprints code (T 12; I2, I3)"
```

### Task 28: Pi measurements and the token ratio

**Files:**
- Create: `engram/tests/test_trails_pi.py`, `engram/scripts/trails_token_ratio.py`
- Modify: this plan's "Results" section (the numbers only)

**Interfaces:**
- Consumes: Tasks 15, 16, 18, 23 to 25.
- Produces: `test_trails_pi.py`, skipped unless `ENGRAM_TRAILS_PI=1`, writing `results.json` into
  `ENGRAM_TRAILS_PI_OUT` (default `/var/tmp/trails-pi`); `scripts/trails_token_ratio.py ANSWERS.json` printing,
  per answer, its bytes, `estimate_tokens` (`category_compile.estimate_tokens`, `engram/category_compile.py:195-197`)
  and real tokens (TR21).

- [ ] **Step 1: Write the measurements**

```python
pytestmark = pytest.mark.skipif(os.environ.get("ENGRAM_TRAILS_PI") != "1", reason="Pi measurement (T 12)")

def test_pi_build_at_the_bounds(bounds_store, results):     # 4,096 sessions, 20,000 nodes, 262,144 steps, one lane
    peak, seconds, ranking = measure_build_in_subprocess(bounds_store)   # ru_maxrss of a fresh process
    results.update(build_seconds=seconds, build_peak_mb=peak, ranking_seconds=ranking,
                   build_over_target=peak > 256)
    assert graph_counts(bounds_store) == (4096, 20_000, 262_144)

def test_pi_tool_call_without_embedding_and_astar_rate(bounds_store, results):
    results.update(call_seconds=time_calls(bounds_store, n=50), expansions_per_second=astar_rate(bounds_store))

def test_pi_embedding_two_texts_of_4000_characters(results):
    results.update(embed_in_process_s=time_embed(local=True),
                   embed_shared_s=time_embed(local=False) if os.environ.get("ENGRAM_EMBEDDER_SOCKET") else None)

def test_pi_evaluation_at_20000_nodes_under_4g(bounds_store, results):
    results.update(evaluation=run_evaluation_capped(bounds_store, memory="4G"))   # systemd-run --user --scope

def test_pi_largest_answers_for_the_token_ratio(bounds_store, results):
    write_largest_answers(bounds_store, results.out / "answers.json")            # the 3 largest of each tool
```

`bounds_store` (a synthetic store at the tool graph's bounds with a `memory_log` of 200,000 recall rows) and the
measuring helpers go in the same file.

- [ ] **Step 2: Run them on this Pi**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && ENGRAM_TRAILS_PI=1 PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope --quiet -p MemoryMax=6G -p MemorySwapMax=0 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider -s tests/test_trails_pi.py`
Expected: 5 passed; `/var/tmp/trails-pi/results.json` and `answers.json` written. The evaluation's own run is
capped at 4 GB inside; the outer 6 GB cap leaves room for the build's subprocess beside it.

- [ ] **Step 3: Count real tokens, only where a credential exists**

Run: `ant auth status && cd /home/andy/superyak/.worktrees/trail-step-1/engram && uv run --locked --extra llm python scripts/trails_token_ratio.py /var/tmp/trails-pi/answers.json`
Expected: one line per answer with bytes, `estimate_tokens` and real tokens. If `ant` is missing (exit 127, as on
this Pi on 2026-10-25) or reports no credential, skip this step and record Gate G10 as open. It sends synthetic
answers only, never a real store's text.

- [ ] **Step 4: Record the results**

Write the numbers into "Results" below, each beside its T 10 hypothesis: build time against 20 s, peak against
256 MB, tool call against 1 s, the newest-rows ranking's time, both embedding times, expansions per second, the
evaluation's time and peak against 1,740 s and 4 GB, the largest answer's real tokens against 2,000, and
`cited_touches_lost` from Task 26. Overruns change nothing here: they go to T's next revision (Gate G11).

- [ ] **Step 5: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/tests/test_trails_pi.py engram/scripts/trails_token_ratio.py \
        engram/docs/superpowers/plans/2026-10-25-trail-arrows.md
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Trails: Pi measurements at the bounds and the real-token ratio, recorded (T 10, 12)"
```

### Task 29: `engram/CLAUDE.md` and the whole suite

**Files:**
- Modify: `engram/CLAUDE.md` (a "Trails" paragraph under "## Architecture", after "Path signatures"; a Key Files
  row for `trails.py`; three MCP Tools rows)

- [ ] **Step 1: Write the paragraph and the rows**

In plain words: what a trail, a road and a detour are; that the observer pass and the tools are off by default and
gated separately (`[category_evolution] trails`, `[trails] tools` and `lanes`); that roads and detours stay pending
and never change recall; that the tools write one `route_shown` receipt and nothing else; that a pass licenses one
lane and turning the tools on is the store owner's act after both gates pass; the read-only CLI line `python
trails.py /path/to/copy-of-graph.db [--json]`; and the spec's path. The MCP Tools rows read "(off by default)".

- [ ] **Step 2: Check the rows are there**

Run: `grep -c "trail_locate\|trail_route\|trail_next" /home/andy/superyak/.worktrees/trail-step-1/engram/CLAUDE.md`
Expected: at least 3.

- [ ] **Step 3: Run every new test file and the suites they touch**

Run: `cd /home/andy/superyak/.worktrees/trail-step-1/engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_trails.py tests/test_trail_observer.py tests/test_trail_tools.py tests/test_trails_embeddings.py tests/test_trails_cli.py tests/test_trails_eval.py tests/test_trails_imprint.py tests/test_trails_pi.py tests/test_packaging.py tests/test_category_server.py tests/test_category_evolution.py`
Expected: PASS, with `test_trails_pi.py`'s five tests skipped. Report the counts.

- [ ] **Step 4: Commit**

```bash
git -C /home/andy/superyak/.worktrees/trail-step-1 add engram/CLAUDE.md
git -C /home/andy/superyak/.worktrees/trail-step-1 commit --trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "engram/CLAUDE.md: trails, their gates, the CLI and the three tools, off by default"
```

---

## Gates (for later)

None of these is run by this plan. Each waits for the person named.

| # | Gate | Why it waits |
|---|---|---|
| G1 | Each merge, Part A and Part B, under section 2 (above). | Station law. |
| G2 | Optionally, Part A before imprints, so imprints with `route` can be admitted as soon as imprints merges. | Rio Grande's call. Not needed: the imprints plan fails closed without `trails` (its R10 and G13), and the stated order stands. |
| G3 | Engram servers in running sessions load the new code only at their next start. Nothing restarts them. | Nothing live here, and with every gate off they behave as today. |
| G4 | `[category_evolution] trails = true` on a store, with `enabled = true` and `auto_commit = false`. | T 7 step 9: a route-gate pass on that store, then its owner's decision. For Andy's stores, Andy. |
| G5 | `[trails] tools = true` with a lane in `[trails] lanes`. | T 7 step 9 and 14: both gates pass on that store, or an imprint of it, for that lane; then the owner's act. |
| G6 | The first evaluation on an imprint: which store, its owner's yes, T 14's open question on memories that mention other people (until Andy answers, the imprint spec's default holds: no memory with a recorded co-subject ships, and the owner confirms the rest), and I 18's deploy gates (sqlite-vec and the embedder in the admission environment, the user manager's environment holding no `ENGRAM_` variable). | T 14 and I 18, 20: Andy's, and the owner's. |
| G7 | Compiled roads, publication, rail, rail routing, translations, governance, tools over an imprint. | T 9: each a later spec. |
| G8 | YS1's wording in T 7 and I 5.4 and 9, and the builder's note that `last_accessed` also moves when an episode leaves core. | Before the first live imprint. Specs, not code; this plan edits no spec. |
| G9 | T's next revision: YN5's sentence in T 7, YN7's "at most an hour" in T 11's I6, FN1 to FN3. | This plan edits no spec. No rule changes. |
| G10 | The real-token ratio, if no credential exists on the Pi, measured where one does. If the largest answer exceeds 2,000 real tokens, the next revision lowers the byte bound. | T 6.5 and 12; Task 28 step 3. |
| G11 | Pi measurements over a T 10 hypothesis (20 s build, 256 MB, 1 s call, the evaluation's 1,740 s). | T 6.6 and 10: the next revision lowers the counts or the builder compacts structures within them, in a branch of its own. |
| G12 | The imprints plan's gate G13: imprints with `route` are refused until `trails` imports on the Pi; then its `test_count_matches_the_trail_functions` must pass against Part A's `roads_and_trails`, through a `_trail_derive` that passes `as_of * 10**6` (TR22), with N above 0 on its trail-rich store. | Cross-plan: Part A merged and deployed with engram on the Pi, which is a deploy act for later. |
| G13 | The road index, once any store holds 10,000 `trail_observed` events (`report()["trails"]["trail_events"]`), and a per-session newest row there if Task 28 finds the ranking too slow. | T 5 and 10: required then, with a schema version bump. |
| G14 | The license. | T 14: Andy's. Engram has none yet. |

## Results (filled by the builder in Task 28)

| Measurement | T 10 hypothesis | Measured on the Pi |
|---|---|---|
| Tool graph build at the bounds | 20 s | |
| Build peak memory | 256 MB per process | |
| Newest-rows ranking, 200,000 log rows | none; measure | |
| Tool call, without embedding | 1 s | |
| Embedding 2 × 4,000 characters, in process / shared | none; measure | |
| A* expansions per second | none; measure | |
| Evaluation at 20,000 nodes, time and peak | 1,740 s, 4 GB | |
| Largest answer, bytes / `estimate_tokens` / real tokens | 6,000 / 1,500 / at most 2,000 | |
| `cited_touches_lost` (Task 26) | none; record | |

## Self-review: every component and test to its task

| T item | Task |
|---|---|
| Component `trails.py` (pure functions, CLI, imprint check, `--evaluate`) | 1–4, 8, 10–16, 21–25 |
| Component `embeddings.py` | 20 |
| Component `category_evolution.py` | 6–8 |
| Component `server.py` | 9, 17–19 |
| Component `storage.py` | 13 |
| Component `config.py` | 5 |
| Component `reflection.py` | 19 (the `category_evolution` block: 7) |
| Component tests | 1–28 |
| Component `engram/CLAUDE.md` | 29 |
| Determinism | 3 (payloads), 7 (road ids), 15 (answers) |
| Touch rules | 2 |
| Co-citation (MF2) | 3 (order and flag), 4 (no support) |
| Suggested touches (R9) | 2 (four bullets), 6 (digest and new event), 1 (no session, newest row) |
| Revisit view (MF3) | 3 (trails), 4 (the road) |
| Lane rules (MF8) | 3 (personal between work), 12 (re-lane after a road) |
| Eligibility (MF1) | 4 (hour apart, a day later), 7 (an hour apart proposes nothing, rewrite id done, evidence ends), 8 (equal length; a detour waits for its road cells) |
| Event ids (RMF1) | 6 |
| Session picking (S-a) | 6 |
| Bounded scan (C3) | 6 (counts), 12 (unscanned re-lane) |
| Detours (MF4) | 8 |
| Parity (MF6) | 12 |
| A* | 10 |
| Angles (R4) | 10 |
| Goal sets (6.3) | 11 |
| Locate (6.2) | 13 (the tool's degraded answer: 18) |
| Forward lookup (6.4) | 14 |
| Short answers (6.5) | 15 (real tokens: 28) |
| `laid_by` (6.5) | 16 |
| Tools (6.6), each bullet | 17 (registration, read-only build, not ready, shutdown, fork), 18 (receipts and their row id, nothing else, recall, stale, lanes, arguments, `trail_next`'s 3 stations, `cut`), 16 (bounds, float32), 19 (reflect) |
| Evaluation (MF7) | 23 |
| Goal gate (W) | 24 (the unit's socket: 27) |
| Synthetic imprint | 26 |
| Report | 25 |
| Limits | 25 |
| Imprints (R13) | 22 |
| Use ends (I2) | 27 |
| Read-only CLI | 21 |
| Gate off | 9 |
| Barrier | 6 (per batch, and the lock order against a recall between batches) |
| Units at the seams (the plan review's MF4) | 4 (seconds refused), 22 (`now` in seconds), 26 (the admission count at t₁) |
| Pi measurements | 28 |
| Review Focus 1 to 5 | 2, 13, 1, 18, 18 and 23 |
| Carried XS2, YN5, YN1, YN7, YS1, XS3, XS1/I6, XN2, FS1, FN1–FN3 | 4, 4/22/26, 22, 1, G8/26, 26, 26, 27, 24, G9 |

## Notes for the other plans

- **Imprints plan.** Its `derive` seam (R10) should reach `trails.roads_and_trails(conn, *, lane, as_of)` (Task 4,
  TR20) through its `_trail_derive`, called at t₁ for each lane of the scope. **The units differ at this seam.** The
  imprints code holds UTC seconds, and every trails derivation takes integer microseconds (TR1, TR22). So
  `_trail_derive(conn, *, lane, as_of)` returns `trails.roads_and_trails(conn, lane=lane, as_of=as_of * 10**6)`, and
  its test helper `roads_and_trails_by_hand` converts the same way. Bound directly, a seconds value raises
  `ValueError`, so the mistake fails admission loudly instead of counting N = 0. The function needs no sqlite-vec,
  sets no pragma and changes no row factory, so it takes `store_reader.connect(path, immutable=True)` as it is. It
  checks no allow file: admission decides that use itself (YN5). For Task 27 this plan also asks for D-I6, a peer
  test builder that admits an imprint engram built.
- **Permissions plan.** `tests/test_packaging.py:225` asserts 43 MCP tools after `server._init()`. This plan adds
  none there. The permissions plan's `permit` and `permissions` tools (its Task 23), if registered at import, would
  make that 45, against its rule that no existing test changes; that plan should check it.

## Verification before merge (station law section 2)

Section 2 merges a branch only when a fresh reviewer has approved it in the room and its test suites pass on the Pi.
The reviewer is a fresh agent started on the Pi that took no part in writing the branch. It runs these from the
branch's worktree (`/home/andy/superyak/.worktrees/trail-derivation` for Part A,
`/home/andy/superyak/.worktrees/trail-step-1` for Part B), and posts its verdict whole in the room ("Superyak: city
of AI", 39fd79, or the room that replaced it), with the branch head and every result below. It never @mentions a
ship.

1. **Up to date with main, by a merge, never a rebase.**
   `git merge-base --is-ancestor main HEAD || git merge --no-ff main -m "Merge main into <branch>"`
2. **The diff is what the plan says.** `git diff --stat main...HEAD` lists only files in "File Structure" (Part A:
   `engram/trails.py`, `engram/pyproject.toml`, `engram/tests/trails_support.py`, `engram/tests/test_trails.py`).
   `git diff --name-only --diff-filter=MDR main...HEAD -- engram/tests/` prints nothing: no existing test file
   changed. `git diff --check main...HEAD` prints nothing.
3. **The engram suite on the Pi, capped** (engram's CLAUDE.md, "Testing"):
   `cd engram && LIGHTHOUSE_REPO="$(cd .. && pwd)/lighthouse" PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked --extra dev python -m pytest -q -ra --tb=short -p no:cacheprovider`
   Expected: every test passes except any that also fail on `main` at the merge base. Run the same command on a
   checkout of the merge base first, and report both counts and the names of any failures. The trail tests are in
   it; `test_trails_pi.py` skips without `ENGRAM_TRAILS_PI=1`.
4. **Part B only: the Pi measurements.** Task 28, step 2's command. Expected: 5 passed. The reviewer compares the
   new `results.json` with the plan's "Results" and reports any number more than 20% worse.
5. **The peer suite** (unchanged by this branch; section 2 names the suites):
   `cd peer && PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider`
   Expected: as on `main`.
6. **Off by default, checked by hand** (Part B; for Part A, only that importing `trails` creates no file). In a fresh
   directory with the knowledge graph and the watcher off, as `tests/test_packaging.py:206-214` sets them:
   `cd engram && D=$(mktemp -d /var/tmp/trails-off.XXXX) && mkdir -p "$D/.engram" && printf '[watcher]\nenabled = false\n\n[graph]\nenabled = false\n' > "$D/.engram/config.toml" && ENGRAM_HOME="$D" ENGRAM_PROJECT_ROOT="$D" ENGRAM_HARNESS=codex uv run --locked --extra dev python -c "import server; server._initialize_pre_serving(); t = server._sleep_maintenance_thread; t and t.join(300); names = {x.name for x in server.mcp._tool_manager.list_tools()}; print(sorted(names & {'trail_locate', 'trail_route', 'trail_next'}), server._config.category_evolution.trails, server._config.trails.tools)"`
   Expected: `[] False False`, and `ls "$D/.engram"` shows no `categories_v2.db`. Then `rm -r "$D"`. This loads the
   in-process model once (about 1.8 GB, `engram/CLAUDE.md`), as the packaging test's start does.
7. **Read the safety-critical code against the spec**, at least: the closed-session rule and `as_of` (T 4), the
   cited-touch rules and suggested touches (T 4), the current-lane filter in every reader (T 4, 6.6), the pass's
   `auto_commit` refusal and its one-transaction check (T 5), that nothing commits a trail rewrite (T 5,
   Activation), the output-time check and its hidden stops (T 6.6), the receipt's fields and the absence of text
   (T 6.6), the imprint check's seven steps and exit 3 (T 7), `local_files_only` on every evaluation path (T 7 step
   8.2), and that `count_roads_and_trails` and `derive_trails` open no file.
8. **Not a Pi suite.** `make check-integration` needs Node.js 24 and pnpm 11.20.0; the Pi has Node 18.20.4 and no pnpm
   (checked 2026-10-25). It must pass in CI or on the Mac before the merge, and its result is posted with the verdict.

The merging ship then merges as section 2 says. This branch changes only engram. On 2026-10-25 the Pi's user
services are `superyak-door`, `superyak-lighthouse`, `superyak-odo`, `superyak-ship` and `superyak-wormhole`, and
none of them runs engram, so no Pi service restarts. If the imprints plan has since made a unit run `trails.py`, that
unit starts fresh at each use, and section 2's restart and check apply to any service that changed.
