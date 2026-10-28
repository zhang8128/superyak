# Review: the imprints step 1 plan

Date: 2026-10-25. Reviewer: a fresh agent on the Pi (`smart`). I took no part in writing the plan or its spec.

Plan: `engram/docs/superpowers/plans/2026-10-25-store-imprint.md` (3,958 lines, uncommitted on `trail-arrows-spec`).
Spec: `engram/docs/superpowers/specs/2026-10-25-store-imprint-design.md`, revision 6 ("I").
Also read: the consolidation log, the interface table, the permissions plan and the trails plan, and the code the
plan cites. I edited no plan or spec, changed no code, ran no test suite, and committed, deployed and posted nothing.

## Verdict: APPROVE WITH CHANGES

One must-fix (M1). Once it is fixed, nothing blocks the build. The plan covers every step-1 component of I 15 and
every test group of I 16. Its names match the spec and the other two plans. The build order holds. Every carried
item for this spec is a task or a gate. Nothing in it touches the live station, and nothing lets more leave a
machine or widens a permission. The should-fix items are real but local. Most are a test that can't pass as
written, or a case no task handles.

## What I checked

- **Coverage.** Every row of I 15 maps to a task or a gate (the lighthouse unit is G4). Every test group of I 16 has
  a task. The plan's own self-review table is correct, but some tests are narrower than the spec's (S11).
- **Carried items.** YS1 (Tasks 15, 25, 47; G15), YN1 (Task 35 docstring, Task 48), YN2 (Task 45), YN3 (R14),
  YN4 (R11), YN5 (G12), YN6 (R13), YN7 (Task 21's fixture; the trails plan's), XN2 (R15), CN7's second half
  (Task 39), CN8 (G16), XN6 (G17). XS1 to XS3, XM1, XN1, CS1, CS2 and CN1 to CN6 are in the tasks the plan names.
- **Test counts.** Each task's "N passed" matches the tests it lists, file by file.
- **Code claims, true.** `store_identity.py` `KEYS` (:43-49), `stamp_fork` (:143-160), `describe`, `effective_id`;
  `Storage.__init__`'s order: connect, load vec, `_restore_pragmas`, `_run_migrations` (`storage.py:84-118`);
  `open_read_only` bypasses `__init__`; `calibrate.py:251` (`exist_ok=False`), `:268`, `:244-310`; the survey's
  `episodes.sessions` and `row_counts` (`store_reader.py`); `store_reader.connect` (:44-55) and `_schema`;
  `persistence.classify_hubs` (:342) and `flag_redundant_cores` (:399); `lighthouse_sheaf._open` (:267-269),
  `query_vector`, `compare_stores` (:350), `_format` (:381); `sharing.share` (:99); `federation.sync_genome`
  (:155-175); `cli.fork_instance` (:15-49); `config.resolve_db_path` and `ENGRAM_DEFAULT_INSTANCE`;
  `NomicEmbedProvider.MODEL_NAME`; `hooks/sleep.py:44`; `lighthouse_protocol.py:113-120`; peer `identity.canonical`
  (:20-23), `RECORD_KEYS` (:76-83), `_record_shape_ok`, `sign_record`, `verify_record` (:189-200),
  `PeerIdentity.load_or_create`; `db.py:113` (`BEGIN IMMEDIATE`); `signatures.py:140-144`; `auth.py`'s login and
  its 8/40 limits; `app.py:19`, `:44-51`, `member`, `ship_member`, `create_app`, the lifespan; `door.create_door`;
  `ships.py:33`, `:133`, `:191-199`, `:279-302`, `:380-393`; `__main__.py:49-64`, `:322-327`, `--as`;
  `peer_routes.py:10-25`; `scripts/runtime.py:84-88`, `:595-597`; `Makefile:8`, `:25-42`, `station-units`;
  `peer/systemd/superyak-backup.service`'s form; `peer/tests/test_station_units.py:89-112`, `INSTALLED`,
  `EXPECTED`, `test_units_say_what_the_spec_says`; `peer/tests/test_ship_agent.py:10-13`; `test_presence.docked`;
  `agent/superyak_agent/station.py` (`StationClient.request`, `write_private`, `read_json`).
- **Other plans.** The permissions plan exports what this plan uses: `Ledger.open_read_only`, `store_row`,
  `cosubjects`, `latest_lane_note`, `Uses.open`, `UseRow`, `append_imported`, `owner_list`, `parse_copy_ref`,
  `decide_bulk(state, bulk, *, legacy=(), outside=None, group=True)`, `BulkUse`, `State.from_tables`, `World`, and
  migration 029. Its `outside` maps a place to a layer kept outside a ledger, so Task 28's call gives XM1's reading.
  The trails plan's `roads_and_trails(conn, *, lane, as_of)` has the shape of R10's `derive` seam.
- **On this Pi.** `/tmp` is on disk (no separate mount). 16 GB. systemd 252. uv 0.12.23. Playwright's Chromium is in
  `~/.cache/ms-playwright`. No engram `.venv` exists in this checkout, but another worktree's runs uv's Python
  3.14.8, so the engram commands work. The peer's `.venv` is Python 3.11.2.
- **Live station.** No task deploys, restarts, installs a unit or posts. Tests shim `systemd-run` and `systemctl` and
  put `HOME` under `tmp_path`. The routes are off without `--imprints-dir` (R8). Deploys are gates G1 to G17.
- **Placeholders.** None. One fixture value holds an ellipsis (N5).

## Must-fix

**M1. An admission killed by its memory cap or its time limit never fails** (Tasks 34, 36, 40; Review Focus 1).

- I 10 says: "A calibration that fails as a whole (exception, memory limit, timeout, source changed) fails
  admission". D16 says: "Any failure deletes the package."
- The plan handles only an exception and a changed source (Task 34, step 3). A unit that hits `MemoryMax=4G` or
  `RuntimeMaxSec=1800` writes no `result.json`. The sync's rules (Task 36) then match nothing. The row stays
  `approved`, with the imprint's bytes on the Pi, until its end date (up to 365 days). The owner sees `approved` and
  no failure.
- Review Focus 1 makes such a run resumable. `station-imprint-admit` with no ID restarts every `approved` row with no
  result, and Task 40 runs it at every `station-approve`. So a store that hits the cap is calibrated again, for up
  to 30 minutes and 4 GB, each time anything is approved.
- **Fix.** Pick one rule and test it. For example: the sync treats an `approved` row as failed when
  `admission.json`'s `decided_at` is more than 1,890 s old (`RuntimeMaxSec` plus systemd's default 90 s stop timeout,
  or give the admission unit `-p TimeoutStopSec=60` as the use's unit has) and no `result.json` exists. It writes
  `failed` (step `calibration`, a fixed message such as "admission stopped at its limit") and deletes with reason
  `failed`. `--awaiting-admission` then lists only rows with no `admission.json`. Add a Task 36 test: begun, no
  result, the clock past that bound, one sync: `failed` then `deleted`. Say how RF1's resume and this rule fit
  together (for example, resume only within the bound). Failing closed narrows; the owner sends again.

## Should-fix

**S1. `station-approve` starts admission for every waiting imprint, not the one approved** (Task 40, lines
3174-3177; its test at 3215-3220).

- Approving imprint B while A's admission runs makes `systemd-run` refuse A's unit name, since it is still loaded.
  `make` then fails after a good approval, and B's unit may never start, depending on the loop's order. The peer
  command has already printed "Admitting in the background".
- Approving a docking also starts any waiting admission. The plan says "a docking approval finds nothing and runs no
  engram command". That is true only when no imprint waits. I 10 says "Approving a docking never touches the engram
  environment".
- **Fix.** Start only the approved item's unit. For example, `station-approve` prints the full imprint id of an
  imprint it hands off on a line the Makefile reads. Leave the start-everything loop to `make station-imprint-admit`
  with no ID, and let it skip a unit that is already loaded. Change the test to match.

**S2. Two dense sets are not bounded at 7,500** (Task 5; I 3 "every dense set bounded at 7,500 episodes", D31).

- `cohesion_report` calls `sheaf.measure_all` (`engram/sheaf.py:266-282`). For every semantic it builds `W`, `L`,
  `eigh`'s vectors and `residuals`, each n × n over the semantic's sources (`sheaf.py:61-87`). That is the same set
  `classify_hubs` bounds, measured again with no bound.
- `persistence.audit_unchecked_events` (`persistence.py:215-253`) calls `split_band`, which builds
  `distance_matrix(X)` and two MST passes over two peers' sources (`:110-125`).
- I's list of three sets missed both. Task 5's test spies only `build_filtration`, which neither one calls.
- **Fix.** Pass the bound to `measure_all` (per semantic) and to `audit_unchecked_events` (per event), record their
  skips as `hub:` or a new `event:` set, and spy on `distance_matrix` and the sheaf's matrix too. Note it for the
  spec's next revision (G15).

**S3. A test that can't pass: the instinct id fails check 10, not 11** (Task 33, line 2633).

- Check 10 requires that "log rows' `target_ids`" resolve inside the package (I 10). An instinct id never resolves,
  since the instincts table is empty (check 9). So `verify` stops at 10, and `("instinct_id_in_recall", 11)` fails.
- A builder could make it pass only by weakening check 10.
- **Fix.** Expect step 10. Or keep 11 and state that check 10 reads only the link tables and check 11 owns the log
  rows' targets.

**S4. Receipt `detail` keys contradict each other** (Tasks 23, 29, 34, 36).

- Task 23 builds `DETAIL_KEYS` from I 12's table and refuses any other key. That table gives `denied` no detail and
  `failed` "check number and fixed message".
- Task 29 writes `denied` with `{"term": …}`. Task 36 writes `failed` with `{"term": …}` at a run's start, and with
  `(step, message)` from a result. Task 23's own test writes `failed` with `{"check": 2, "message": …}`. Task 45
  reads `term`.
- **Fix.** List the keys once: `denied`: `term` (optional); `failed`: `step` or `term`, and `message`. Use one name,
  `step` (R11) or `check`, everywhere.

**S5. `GET /api/imprints/{id}` is used before any task builds it** (Task 26's test, line 2130).

- `test_parts` reads `held` from `GET /api/imprints/{id}`. Task 24 builds `POST` and `GET /api/imprints`. Only Task
  41 describes the `{id}` route.
- **Fix.** Task 26 adds `GET /api/imprints/{id}` (status, held), and Task 41 extends it.

**S6. The plan has no source for `operator`** (R7, Task 7's `parse_terms`, Task 15).

- `parse_terms(..., operator)` needs the station operator's handle. R7's context holds only `ship`, `owner` and
  `station` (the peer id). So `imprint.py plan` can only echo the `--audience` handle, and the dry run's "acting for
  andy" restates what the owner typed.
- **Fix.** Add `operator` (the super admin's username, which `check_request` already reads) to R7's answer and to
  `Context`, and test that a plan with another home is refused before anything is sent.

**S7. The lost-key guard ignores imprint signatures** (Tasks 23, 25, 41).

- `signatures.refuse_a_lost_identity` refuses a new key while the station holds signed records, through
  `SIGNED_RECORDS` (`peer/superyak_peer/signatures.py:24-35`). The plan adds signed permissions and receipts but no
  entry there.
- After a lost `identity.json`, the lighthouse would make a new key. Then `sign_record` refuses every pending receipt,
  since its `station` names the old peer id. The signing loop would raise every 60 s, and every owner's
  `imprint-verify` would warn.
- **Fix.** Add `imprint_requests.permission_signature` and `imprint_receipts.signature` to `SIGNED_RECORDS` in
  Task 23 or 25, with a test like the existing G4b ones. Have the signing loop log and continue on an error.

**S8. "Ended during admission" lacks its sync rule and test** (Tasks 34, 36).

- I 10 says: "On 'ended', the sync writes the `failed` receipt (term: the effective end) and deletes the imprint with
  reason `ended`." Task 36's text says only that such a row "is deleted with reason `ended`". Task 34 tests that
  `admit` exits 5. No test checks the receipts the sync then writes, which YN2's import depends on.
- **Fix.** State the `failed` receipt in Task 36. Add a test: begun, `admit` exits 5 with no result, one sync:
  `failed` `{term: "end"}` then `deleted` `{reason: "ended"}`.

**S9. The retention test can't tell 30 days from 400** (Task 42, lines 3364-3367).

- It moves the clock 400 days and expects every row gone. A declined row kept for 400 days, or a deleted imprint's
  row removed at 30, would pass. D32 is a promise to the owner, in the confirm view's words.
- **Fix.** Check at 30 days + 1: the declined and expired rows are gone, and the deleted imprint's row, receipts and
  tombstone remain. Then check at 400 days + 1: those are gone too.

**S10. Packaging misses the new units and test files** (Global Constraints "Packaging", Task 42).

- `peer/pyproject.toml`'s sdist list names each systemd unit. Task 42 adds two units but no list entry. The bundle
  ships `tests/test_station_units.py`, whose edited `INSTALLED` would then fail there.
- `peer/tests/imprint_support.py` and `peer/tests/fixtures/imprints/ceiling_agreement.json` are not test files, so
  the rule as written leaves them out too.
- `test_imprint_docs.py` reads the repository's `CLAUDE.md` and `engram/CLAUDE.md`. `test_imprint_units.py` runs the
  repository Makefile. Both need the skip that `test_station_units.py` and `test_ship_agent.py` use in the
  standalone bundle.
- **Fix.** Add the units and support files to the sdist list, and add the two skips.

**S11. Some tests are narrower than I 16 asks** (Tasks 7, 13, 26, 34, 35).

- "Selection": `--shared-with` "matched by instance name, layer, audience and digest". Task 7 varies only audience
  and digest. Add a share of another instance (or another `source_instance_id`) and of another layer.
- "Manifest before parts": "a manifest that differs from the request in any shared field". Task 26 changes only
  `plan_digest`. Parametrize over the shared fields of I 7.2.
- "Routes": "the right ship". No upload test uses another ship. Add one: another ship's manifest, part and
  `complete` get 404.
- "Identity and ancestry": "`forked_from` = the stored or derived source id". Task 13 builds from a fork only. Add a
  source that predates identity.
- "The count of R(I)": "No receipt names a road, a trail or a session". No task asserts it.
- YN4: calibration's failure name has no test. Add one where `calibrate_fn` raises: step `calibration`.

## Nits

- **N1. Line numbers in `calibrate.py`** (Tasks 4 and 5). `persistence_scores` is at :146-162, `cohesion_report` at
  :165-180, `persistence_preview` at :183-212 and `render_markdown` at :313-393. The plan cites :128-145, :163-176,
  :191-213 and :308-381.
- **N2. Python.** "Python 3.13" (line 17). On this Pi engram runs on uv's 3.14.8, since `uv.lock` requires 3.12 or
  newer, and the peer's `.venv` is 3.11.2. Peer and agent code must run on 3.11.
- **N3. Task 27, `test_one_ceiling_per_copy`.** Its second assertion asks `kind="admission"` with
  `status="admitted"`, so it is refused by status, whatever the end check does. Use a status of `approved`, or a
  trail evaluation on a copy with `route`.
- **N4. Task 37, `("withdrawn", "withdrawal")`.** A real withdrawal sets the status to `deleting` and then `deleted`,
  so the first failing term is `status`. Say that the fixture plants a `withdrawn` receipt with the status left at
  `admitted`, or expect `status`.
- **N5. Task 18's fixture.** `ancestry=["3f2a9c1e-…"]` is not a UUID. Use a real one.
- **N6. Order.** Task 29's test calls `ship_shortens` before Task 31 builds shortening. Say that the helper appends a
  `shortened` receipt through Task 23. Task 40's admission command names `verify-imprint` before Task 44 builds it.
  Its tests are dry runs, so they pass, but say so.
- **N7. RF5 locks the send, not the build.** Two `make imprint-send` runs of one plan both run
  `imprint.py build --if-needed` before any lock, so two packages with two imprint ids are built. D20 at the station
  refuses the second request (409), so nothing is sent twice. Still, take the lock on the plan before the build.
- **N8. Task 2's `resolve_db_path` test passes before the change.** It guards; it does not drive. Say so, as Task 20
  does.
- **N9. Task 1's test** uses `genome_with_parent`, `iid_of` and `GENOME_PARENT`, which its Interfaces don't list.
- **N10. A resumed admission after registration.** If a run dies after writing `imprint.json`, check 1 fails on the
  extra file and the imprint is deleted. That fails closed. Note it beside RF1.
- **N11. A refused hand-off after `approved` commits** (Task 29). The row is `approved` with no directories until the
  sweep marks it `missing`. Check for existing directories and a tombstone before the transaction.
- **N12. `make imprint-plan` runs in `engram/`** (Task 46). `cd engram` makes the current directory the engram
  checkout, so without `--store` the default store is resolved from there, not from where the owner ran `make`.
  Pass `ENGRAM_PROJECT_ROOT ?= $(CURDIR)`, or say that `--store` is the way.
- **N13. `l3_vec0(conn, expected)`** takes embedding bytes at the build and SHA-256s on the Pi (Tasks 14 and 33).
  Give the two forms two parameters, or one form.
- **N14. Size.** Task 42 (sweep, retention, restore, units, Makefile and the one existing test) and Task 43 (five
  agent commands) are large. Split each in two.
- **N15. `permission_cli` imports `imprint`** (Task 45) for `copies_held`, which pulls in calibrate and numpy. A
  small module of its own would keep the CLI light.
- **N16. The trails plan cites this plan's task numbers wrongly.** It names Task 34 for `count_roads_and_trails`
  (here Task 35), Task 37 for `imprint.use` (here 38) and Task 39 for R15 (here 40). It also calls the plan step
  `imprint.plan`, where this plan has `make_plan`. That is the trails plan's to fix. Noted here so the two agree.

## Privacy and permissions

Nothing more leaves a machine. Where the plan settles what the spec leaves open, it takes the narrower choice: R8
(routes off), R14 (`until` required), R15 (`UnsetEnvironment`), R22 (withdrawing a request is a decline), and YS1's
truer words to the owner. The decision is the per-copy ceiling. Its fixture is checked by the station's code and by
the permissions plan's `decide_bulk`, with the operator's home as a layer kept outside a ledger (XM1). M1 and S1 are
about failing and starting admissions, not about what is allowed. I found nothing about a person that moves without
their yes. Whether memories that mention other people may move at all is still Andy's (G14).

## Response

Date: 2026-10-26. By the plan's author, in the same worktree. I edited only the plan and this file, with targeted
edits. No code, spec, commit, deploy or post. Every must-fix and should-fix is applied. Every nit is applied but N16,
which is not this plan's.

### Must-fix

- **M1. Applied, as new ruling R24, "a begun admission runs once".** The admission unit gets `-p
  TimeoutStopSec=60`. `ADMISSION_BOUND = 1860` (Constants, Task 36). The sync's admission part is now six ordered
  rules (Task 36). Rule 5 fails an `approved` row that has `admission.json`, no `result.json` and a `decided_at` more
  than 1,860 s old: `failed` `{step: "calibration", message: ADMISSION_STOPPED}`, then the deletion, reason `failed`.
  A killed unit runs no sync, so the first sync after the bound applies it, which the hourly sweep runs. New Task 36
  test: `test_a_begun_admission_with_no_result_fails_once_its_bound_passes` (still `approved` at the bound, failed
  and deleted one second later).
- **How RF1 fits.** I chose "a begun admission is never resumed" over "resume within the bound". With resumes, each
  run would reset or stretch the bound, a resumed unit could outlive it, and the sync could delete under a live run.
  Instead: `station-imprint-admit-begin` refuses a row whose `admission.json` exists, writing nothing.
  `--awaiting-admission` lists only rows with neither `admission.json` nor `result.json`. The Makefile runs `imprint.py
  admit` only when begin exits 0. So the spec's resume (D39, "maybe days on") keeps the case its own test uses: an
  admission that never began. A crash mid-run fails closed at the bound, and the owner sends again. RF1 is rewritten.
  `imprint.py admit` that finds a dead run's `calibration/` now fails with step `calibration` and `RERUN_REFUSED`. It
  no longer clears the directory and calibrates again (`test_rf1_a_dead_runs_calibration_fails_the_rerun`). A
  shortening's rewrite of `admission.json` keeps `decided_at`, and Task 31's test now checks that. G15 carries R24 to
  the spec.

### Should-fix

- **S1. Applied** (Tasks 29, 40). For an approved imprint, `describe_decision` ends with `ADMIT: <full imprint id>`.
  `station-approve` starts that one unit and no other. A docking prints no such line, so it starts nothing (I 10).
  With no ID, `make station-imprint-admit` skips a unit that reports `loaded`. New tests: the approve test (only the
  approved unit, with `TimeoutStopSec=60`; a docking runs nothing), `test_the_no_id_resume_skips_a_loaded_unit`,
  `test_admit_runs_only_when_begin_allows`, and Task 29's `test_an_approval_names_the_full_imprint_id_for_the_makefile`.
- **S2. Applied** (Task 5). `sheaf.measure_all` (via `cohesion_report`) and `persistence.audit_unchecked_events` (via
  `persistence_preview`) take the bound. Their skips are recorded as `cohesion:<semantic id>` and `event:<event id>`.
  The test spies on `persistence.distance_matrix` and `sheaf.build_local_sheaf`, which see every dense matrix. I
  checked the code: `classify_hubs` also calls `distance_matrix`, and `evaluate_prune` builds none. `engram/sheaf.py`
  joins File Structure. Flagged for G15.
- **S3. Applied** (Task 33). `("instinct_id_in_recall", 10)`. Check 10's text now says it covers the log rows'
  `target_ids`.
- **S4. Applied, as new ruling R25** (Task 23). `DETAIL_KEYS` is now each event's allowed key sets, listed once.
  `failed` is `{step, message}` or `{term}`, and `denied` is `{}` or `{term}`. `step` is used everywhere, never
  `check`. Task 23's test writes `step`, and its refusal test now refuses `check` and a mixed `{step, term}`. Tasks
  36 and 45 cite the list. Verification step 9 checks against it.
- **S5. Applied.** Task 26 adds `GET /api/imprints/{id}` (`{status, held}`, the owner or the requesting ship, else
  404). Task 41 extends it.
- **S6. Applied** (R7, Tasks 15, 24, 43a). `operator` is in the `GET /api/imprints` answer and in `Context`.
  `parse_terms` gets `operator=context.operator`. New Task 15 test: a plan naming `place:home/jenn` is refused and no
  plan file is written, and the dry run says "acting for andy" from the station's answer.
- **S7. Applied** (Tasks 23, 41). `SIGNED_RECORDS` gains `imprint_requests.permission_signature` and
  `imprint_receipts.signature`, with a G4b-style test per column. The signing loop logs the error's class and goes
  on, and a read answers with its receipts unsigned (`test_a_signing_error_is_logged_and_the_loop_goes_on`). One
  correction to the review: on `main`, `SIGNED_RECORDS` is at `signatures.py:14-19`, not `:24-35`. The plan cites
  `:14-19`.
- **S8. Applied** (Task 36, rule 4; Task 42a). An approved row past its effective end gets `failed` `{term: "end"}`,
  then `deleted` `{reason: "ended"}`. The sweep's end step now skips `approved` rows, so its sync gives the same
  receipts. New test: `test_ended_during_admission_writes_failed_then_deleted`.
- **S9. Applied** (Task 42a). The retention test checks at 30 days + 1: the declined and expired rows are gone, and
  the deleted imprint's row, permission, receipts and tombstone remain. Then it checks at 400 days + 1: all are gone.
- **S10. Applied** (Global Constraints "Packaging", Tasks 23, 27, 40, 42b, 48). The sdist list gains the two units,
  `tests/imprint_support.py` and the fixture. `test_imprint_units.py` and `test_imprint_docs.py` get the standalone
  skips.
- **S11. Applied.** Task 7 adds a share under another `source_instance_id` and one under another layer. Task 26 adds
  a test parametrized over I 7.2's ten shared fields, and a test where another ship gets 404 on the manifest, part,
  `complete` and `{id}` routes. Task 13 adds a source that predates identity (derived `forked_from`, ancestry
  incomplete). Task 39 adds `test_no_receipt_names_a_road_a_trail_or_a_session`. Task 34 adds
  `test_a_calibration_that_raises_fails_with_step_calibration` (a fixed message, never the exception's text). The
  test counts are updated.

### Nits

- **N1. Applied** (Tasks 4, 5): `:146-162`, `:165-180`, `:183-212`, `:313-393`, and `calibrate` at `:244-310`.
- **N2. Applied** (Tech Stack). Engram runs on uv's 3.14.8 (3.12 or newer). The peer and agent run on 3.11, and
  their code must too.
- **N3. Applied** (Task 27). The second assertion uses status `approved` and expects term `end`.
- **N4. Applied** (Task 37). A note says the fixture plants a `withdrawn` receipt with the status left at `admitted`.
- **N5. Applied** (Task 18). A real uuid4.
- **N6. Applied.** Task 29's `ship_shortens` appends a `shortened` receipt through `_append_imprint_receipt`. Task 40
  says its tests are dry runs and shims, so they pass before Task 44.
- **N7. Applied** (Task 19, RF5). `build` holds a lock on the plan from before it reads the plan file until it
  records `imprint_id`. A second build exits 4. New test: `test_rf5_a_second_build_of_one_plan_refuses`. I used
  `fcntl` in engram, not `flock(1)` in the Makefile, because the owner's machine may be a Mac.
- **N8. Applied** (Task 2). Step 2 says the `resolve_db_path` test guards and passes before the change.
- **N9. Applied** (Task 1). `GENOME_PARENT`, `genome_with_parent` and `iid_of` are in Interfaces.
- **N10. Applied** beside RF1. R24 makes that case end like any begun run with no result.
- **N11. Applied** (Task 29). The directories and tombstone are checked before the transaction. The test now asserts
  the row stays `received` with no new receipt.
- **N12. Applied** (Tasks 15, 46). `imprint.py plan --project-root`, else `$ENGRAM_PROJECT_ROOT`, else the current
  directory. The Makefile passes `--project-root "$(ENGRAM_PROJECT_ROOT)"` with `ENGRAM_PROJECT_ROOT ?= $(CURDIR)`.
- **N13. Applied** (Tasks 14, 19, 33). `l3_vec0` takes SHA-256 hex on both machines.
- **N14. Applied.** Task 42 is now 42a (the sweep, retention, restore) and 42b (the units, the Makefile, the one
  existing test). Task 43 is now 43a (`context`, `send`) and 43b (`status`, `withdraw`, `shorten`). I used letters,
  not new numbers, so Tasks 44 to 49 keep the numbers the other plans cite. Every cross-reference was updated.
- **N15. Applied** (Task 45, R1). `copies_held` moves to a new `engram/imprint_copies.py`, standard library only. A
  test checks that importing it loads neither numpy nor `imprint`.
- **N16. Declined here: not this file's.** I checked the trails plan as it now stands. It already cites Tasks 35, 37,
  38, 39 and 40 correctly and calls the plan step `imprint.make_plan`. Nothing is left to align.

### One addition the review did not ask for

- Task 35 now says `_trail_derive` passes `as_of * 10**6`, since the trails plan's TR22 has the trail functions take
  microseconds and names this adapter as the converter. It changes no seconds value this plan holds.

## Re-check

Date: 2026-10-26. Reviewer: a fresh agent on the Pi (`smart`), re-checking in Andy's place. I took no part in
writing, reviewing or revising the plan or its spec. I read the plan as committed at `85595ed` (4,304 lines), the
spec (revision 6), the review and response above, the interface table, the other two plans where they connect, and
the code the revision cites. I edited no plan or spec, changed no code, ran no suite, and committed, deployed and
posted nothing.

### Verdict: APPROVE

No must-fix remains. M1 is resolved. Each should-fix and nit the response claims is in the plan text, and the ones
that cite code agree with the code. I found no new privacy defect: nothing more leaves a machine, and every new rule
fails closed. Five should-fix items remain. Two are tests that can't pass as written (RS1 came in with the S1 fix;
RS2 was there before). The other three are edges of R24 and of the import. Each is local to the tasks named.

### M1, and RF1 as revised

- **Resolved.** The admission unit gets `-p TimeoutStopSec=60` (Task 40, with a test). `ADMISSION_BOUND = 1860` is
  in Global Constraints and Task 36. Rule 5 fails a begun row with no result once the bound has passed, and
  `test_a_begun_admission_with_no_result_fails_once_its_bound_passes` checks both sides of it: still `approved` at
  the bound, `failed` then `deleted` one second later. `--awaiting-admission` lists only never-begun rows. Begin
  refuses a begun row and writes nothing (`test_only_an_admission_never_begun_awaits_and_a_begun_one_never_begins_again`).
  The Makefile runs `imprint.py admit` only when begin exits 0 (`test_admit_runs_only_when_begin_allows`).
- **The bound is sound.** `RuntimeMaxSec` counts from the unit's start. Begin writes `decided_at` inside the unit,
  after that start. So at `decided_at` + 1,860 s the unit has used its 1,800 s and its 60 s stop timeout, and is
  gone. A shortening keeps `decided_at` (Task 31's test checks it), so no shortening stretches the bound.
- **The rule order holds.** Results come first, then a begin's refusal, then the end, then the bound. A begin refused
  on the end writes one `failed` receipt, since rule 3 comes before rule 4. A run killed after its end gets term
  `end` and reason `ended`. The sweep's end step skips `approved` rows, so every admission's end leaves the same two
  receipts.
- **Does "a begun admission is never resumed" meet the spec?** It meets I 10's failure rule ("exception, memory
  limit, timeout, source changed ... fails admission"), D16 ("Any failure deletes the package") and D39 (every run
  is decided at its start and checks the end and withdrawal before each write). A begun admission is decided once,
  for its one run. I 16's "Admission after the end" test still holds, since it stops the unit before begin runs.
  The rule departs from four sentences of the spec, each in the narrowing direction (it fails closed, and the owner
  sends again):
  1. I 10, hand-off step 4: "`make station-imprint-admit` with no ID starts one unit for each approved imprint
     without a result, after a crash."
  2. I 10, "Admission is decided again": "after a crash, `make station-imprint-admit` resumes, maybe days on."
  3. I 10: "Each step is idempotent."
  4. I 13: "`make station-imprint-admit  # resume an interrupted admission`".

  Also, I 10's unit command has no `-p TimeoutStopSec=60`, I 14 has no bound, and I 12's `failed` row says "check
  number".
- **I confirm R24.** The reviser's reason is right. A resume inside the bound would need a second unit, which could
  outlive the bound and be deleted while it runs. It would give the owner nothing they don't get by sending again.
  The cost is a resend, and a new yes, after the Pi restarts during an admission. That is rare, and the owner sees
  it as `failed` with `ADMISSION_STOPPED`.
- **What the spec must say instead.** G15 names R24 but not the words. I propose:
  - I 10, step 4: the unit also gets `-p TimeoutStopSec=60`. "`make station-imprint-admit` with no ID starts one
    unit for each approved imprint whose admission never began (no `admission.json`): the unit did not start, or
    stopped before its first step."
  - I 10, "Admission is decided again": "A run may start much later, if the first never began. A begun admission
    runs once. `station-imprint-admit-begin` refuses a row whose `admission.json` exists and writes nothing, and
    nothing runs `imprint.py admit` for it again. If a begun admission leaves no `result.json`, the first sync more
    than 1,860 s after `admission.json`'s `decided_at` fails it. That is `RuntimeMaxSec=1800` plus
    `TimeoutStopSec=60`, so the unit has stopped: its memory cap or its time limit was reached, or the station
    stopped. The sync writes a `failed` receipt with step `calibration` and a fixed message, then deletes the
    imprint with reason `failed`. A shortening's rewrite of `admission.json` keeps `decided_at`."
  - I 10: "Each step is idempotent" becomes "Each step can be rerun: begin refuses a begun admission without
    writing, and the sync records each result once."
  - I 13: `make station-imprint-admit  # start an admission that never began; decided again first (D39)`.
  - I 14: a row "A begun admission with no result | failed 1,860 s after `decided_at`".
  - I 16, "Calibration": "A begun admission with no `result.json` is still `approved` at `decided_at` + 1,860 s, and
    is `failed`, then `deleted` (reason `failed`), one second later. A second begin of a begun admission writes
    nothing."
  - I 12, the `failed` row: R25's keys.

### Should-fix

**RS1. Task 29's new test calls `describe_decision` with two arguments.** It was added by the S1 fix.

- `peer/superyak_peer/__main__.py:67` is `describe_decision(item, result, person, approve)`, and `:325-327` calls it
  with four. Task 29 does not say it changes the signature. So
  `test_an_approval_names_the_full_imprint_id_for_the_makefile` raises `TypeError` as written.
- **Fix.** Pass `"andy", True`, or give the two parameters defaults and say so in Task 29's Interfaces. Also assert
  that an approval the decision refuses (`test_a_refusal_at_approval_is_a_denial_naming_the_term`) prints no
  `ADMIT:` line. Otherwise the Makefile would start a unit for a deleted imprint, and its begin would append a
  receipt after `deleted` (RN3).

**RS2. `make_plan` can't be called the way the tests and the trails plan call it.** This was there before the
revision. The first review missed it.

- Task 15's interface is `make_plan(store, sel, terms, ctx, context, *, home, now)`. Tasks 15, 16 and 18 to 21 call
  `make_plan(*plan_args(...))`. The trails plan's Task 26 (`build_imprint`, its D-I1) does the same. Unpacking a
  tuple can't fill the keyword-only `home` and `now`, so every such call raises `TypeError`.
- **Fix.** Drop the `*`, so `home` and `now` are positional-or-keyword, in that order. List `plan_args`, `HOME` and
  `CONTEXT` in Task 15's Produces, since the trails plan names them as this plan's builders.

**RS3. "A begun admission runs once" holds only for runs that units start** (R24; Tasks 34, 36, 40, 48).

- `make station-imprint-admit ID=<id>` is the unit's command, but anyone can also run it in a shell (I 10 names
  it). Run by hand, it runs begin and then calibration outside the unit's `MemoryMax`, `MemorySwapMax` and
  `RuntimeMaxSec`. Under R24 that is the admission's only run.
  - Claude's Bash tool stops at 10 minutes, as I 10 notes. If Claude runs it on the Pi, it is killed during
    calibration, and the sync fails the imprint at the bound. The owner must send again and give a new yes.
  - A hand run longer than 1,860 s is deleted while it runs.
- Begin's "only when none exists" is not stated as an exclusive create. A hand run and a unit can both pass the check,
  and both run `imprint.py admit`.
- `imprint.py admit` detects a second run only by `<id>.state/calibration/`. A run that died during verification
  leaves nothing to detect.
- **Fix.**
  - Give the unit its own target, `station-imprint-admit-run ID=…`, as uses have `station-imprint-use-run`. Make
    `station-imprint-admit ID=…` start the unit, as the no-ID form does.
  - Begin creates `admission.json` with `O_CREAT | O_EXCL`.
  - `imprint.py admit` claims its run with an exclusive marker in the state directory (say `admit.started`) before
    verification, and refuses with `RERUN_REFUSED` when it exists.
  - Task 48's CLAUDE.md lines say agents never run `imprint.py admit` by hand.
  - The unit's command is named in I 10, so G15 notes the new target name.

**RS4. An admission that never began waits silently until its end** (Tasks 36, 40).

- M1 bounded a begun admission. A unit can also fail before begin runs, for example when the `uv` environment won't
  sync after a pull. Then the row has no `admission.json`. Rules 4 and 5 don't apply until the effective end, up to
  365 days away, and nothing tells Andy. `station-approve` has already printed "Admitting in the background".
- This stays within the owner's yes, since the record allows keeping the copy until its end, so it is not a
  must-fix. But the owner sees `approved` with no progress.
- **Fix.** Once an `approved` row has had no `admission.json` for more than 10 minutes after its approval,
  `station-imprints` marks it "admission has not started; run make station-imprint-admit", and Odo's notice says the
  same, naming no one. Or give the unit an `OnFailure=` to the alert unit. Test whichever is chosen.

**RS5. A failed admission never reaches the owner's use list** (Task 45; I 12).

- Task 45 imports `admitted`, and imports `failed` or `denied` only when they name a term, as I 12 says.
- A `failed` with a `step` (rule 2, or R24's rule 5) records an admission that the decision allowed. That admission
  read the memories, for verification and for up to 30 minutes of calibration. `engram-permissions uses --object`
  then finds no use of those memories, though P 9.1 records allowed uses. R24 adds one more such case.
- **Fix.** Import a `failed` with `step` as an allowed admission use: the memory rows as for `admitted`, and, with
  `route`, the null rows on roads and trails (there is no N). Add it to Task 45's test and to G15 (I 12's list). If
  Rio Grande prefers the spec's list as it stands, say so in R25 and G15 instead.

### Nits

- **RN1.** The bounds use different comparisons: admission fails at more than 1,860 s, and a use is finished at 1,860
  s or more (Task 39's test). Both are safe. One rule reads better.
- **RN2.** Suppose begin refused a row but its sync has not yet deleted it. The row has no `admission.json`, so
  `--awaiting-admission` lists it. A resume then decides it again and writes a second `failed {term}` receipt. Skip
  rows that hold a `failed` receipt.
- **RN3.** Begin on a row that is not `approved`, such as a hand run on a deleted imprint, appends `failed {term:
  "status"}` after `deleted`, and Task 45 would import it as a refused admission. Refuse such a row and write no
  receipt.
- **RN4.** The units run `make` with the Makefile's default `APPROVER=andy`, not the approver's. G7 makes them the
  same person. Pass `APPROVER=$(APPROVER)` in the unit's command to keep it that way.
- **RN5.** Task 36 says each station command takes `--as`. The sweep runs the sync with no person, and the trails
  plan's Task 27 calls `station-imprint-sync --imprints-dir R` with none. Say that the sync takes no `--as`.
- **RN6.** The trails plan's D-I6 needs `admitted(tmp_path, route=True, ...)` to accept a directory that
  `imprint.build` made. No task lists that builder. Add it to Task 37's Interfaces with that keyword.
- **RN7.** `station-approve`'s recipe now captures the peer command's output. Say that it keeps that command's exit
  status, so a refused approval still fails `make`, since the recipe runs under `/bin/sh` (dash on the Pi).
- **RN8.** `calibrate._run` records an analysis error as `f"{type(e).__name__}: {e}"` with a traceback
  (`engram/calibrate.py:236-241`), and `no_content` strips only `content` keys. I 16 asks for no text value from
  the imprint in `report.json`. With `no_content`, keep the class name alone. This was there before the revision.
- **RN9.** Task 1's import line omits `genome_with_parent`, `iid_of`, `GENOME_PARENT` and `fork_instance`, which its
  last test uses. N9 fixed only the Interfaces.

### Rulings

All confirmed. None is vetoed.

- **R1 to R6, R9, R12, R16 to R18, R20, R21, R23** are choices I 19 leaves to the builder, or the spec doesn't fix,
  and none widens anything.
- **R7** sends only the ship key, and returns the operator's username, which the ship's owner already meets as the
  audience. Confirmed with S6's test.
- **R8, R14, R15, R22** narrow.
- **R10** fails closed until the trails plan's functions are on the Pi (G13).
- **R11, R13 and R25** rename or split, and change no verdict. G15 carries them.
- **R19** reuses the login path's limits.
- **R24** is confirmed above, with the spec text it needs.
- **Additions outside the table, also confirmed:**
  - the sweep's end step skips `approved` rows, following I 10's "On 'ended'";
  - `limits` in every `deleted` receipt (I 12, "Known limits, stated in every `deleted` receipt");
  - the `cohesion:` and `event:` skip sets (S2; G15);
  - step `calibration` for `ADMISSION_STOPPED`, since the station can't tell a cap from a crash;
  - `RERUN_REFUSED`, with RS3;
  - `_trail_derive`'s `as_of * 10**6`, which matches the trails plan's TR22.

### Names and task numbers across the plans

- **The trails plan** cites this plan correctly:
  - Task 15 for `make_plan` and 19 for `build`;
  - 30 and 31 for `withdraw_imprint` and `shorten_imprint`;
  - 32 for `store_reader.connect(vec=True)`;
  - 35 for `count_roads_and_trails`;
  - 37, 38 and 39 for begin, `use` and the sync;
  - 40 for the Makefile;
  - R7, R15 and R20.

  `imprint.use(imprint_id, use_id, *, root, lane, trails_cmd, now)` matches Task 38. Its
  `roads_and_trails(conn, *, lane, as_of)` matches R10's seam, with seconds times 10⁶ (TR22, Task 35). N16 is
  settled. The exceptions are RS2, RN5 and RN6.
- **The permissions plan's** Tasks 1, 2, 7, 10, 11, 14, 15, 16, 17 and 27 and its R2 are named correctly.
  - `decide_bulk(state, bulk, *, legacy=(), outside=None, group=True)` takes, in `outside`, callables that return
    `allow`, `deny` or `silent` (its R7 and Task 5). That is the callable `ceiling_world` returns.
  - `owner_list(state, *, ..., obj=...)` matches Task 45's call.

### Tests

- Every "N passed" matches the tests the task lists, file by file. Tasks 19, 33, 35, 39, 41 and 46 count their
  file's earlier tests correctly.
- There is no placeholder. The one `pass` is Task 41's lifespan block, and real assertions follow it.
- Two tests can't pass as written: RS1 and RS2.

### Code claims checked

All hold, except the one under RS1:

- **`peer/superyak_peer/signatures.py`.** `SIGNED_RECORDS` is at `:16-19`, with its comment from `:14`.
  `holds_signed_records` and `refuse_a_lost_identity` read it, and `LOST_IDENTITY` names `identity.json` and
  `station-new-identity`, so Task 23's regex matches.
- **`engram/sheaf.py` and `engram/persistence.py`.**
  - `sheaf.measure_all` (`:266-282`) calls `build_local_sheaf` by its module name.
  - `persistence.build_filtration`, `split_band` and `classify_hubs` call `distance_matrix` by its module name.
    So Task 5's spies see every dense matrix.
  - `evaluate_prune` and `generativity_scores` build none.
- **`engram/calibrate.py`.** `:251` creates its directory with `exist_ok=False`. `persistence_scores` is at
  `:146-162`, `cohesion_report` at `:165-180` and `persistence_preview` at `:183-212`.
- **`engram/store_identity.py`.** `KEYS` and `stamp_fork` (`:143-160`) are as Tasks 1 and 13 read them.
- **`peer/superyak_peer/ships.py`.**
  - `station_pending` is at `:191-199`.
  - `station_decide` is at `:279-302`. It checks only that the name is a person (`_operator`), so Task 29's case
    with `jenn` reaches the audience check.
  - Notices are `{id, text}` (`:380-393`).
- **`peer/superyak_peer/__main__.py`.** `describe_decision` is at `:67` (RS1). `:322-327` opens
  `Store(signing=False)`.
- **Others:**
  - `peer/superyak_peer/db.py`: `BEGIN IMMEDIATE`, and the signing gate in `__init__`;
  - `peer/superyak_peer/peer_routes.py:10-25`: the lifespan;
  - `peer/superyak_peer/auth.py:80-100`: the 8 and 40 limits;
  - `scripts/runtime.py:84-88` and `:592-597`;
  - `engram/server.py:163`;
  - `peer/pyproject.toml`: the sdist's `systemd/` entries at `:45-50`, its tests to `:137`, and the wheel's list
    from `:141`;
  - `peer/tests/test_station_units.py:88` and `peer/tests/test_ship_agent.py:10-13`.

### Privacy and permissions

- Nothing more leaves a machine.
- R24 and R25 narrow or rename.
- RS5 would make the owner's list show more, while nothing more leaves.
- No defect I found lets a use happen outside I 8's check.
- Whether memories that mention other people may move at all is still Andy's question (G14).
