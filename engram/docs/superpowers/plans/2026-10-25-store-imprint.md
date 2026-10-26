# Imprints, Step 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An owner can choose part of an Engram store, see exactly what would leave, filter it on their own machine,
send it to the station only after their browser yes, and have Andy admit it there as its own read-only store, with a
signed, content-free receipt for every event and deletion at once on withdrawal or at the end date.

**Architecture:** On the source machine, `engram/imprint_filter.py` computes the selection, the rows that would leave
and the plan digest, `engram/imprint_checks.py` holds the leak checks and the 17 admission checks, and
`engram/imprint.py` is the command (`plan`, `read`, `build`, `admit`, `use`, `list`, `import-receipts`). On the
station, `peer/superyak_peer/imprints.py` holds requests, the confirm, uploads, the signed permission, the per-copy
ceiling, receipts and their chain, withdrawal, the sweep and the sync. `agent/superyak_agent/imprint.py` carries the
package over the tailnet with the ship key. The Makefile runs admission and uses as detached user units.

**Tech Stack:** Python. Engram runs on uv's interpreter (3.14.8 on the Pi; `engram/pyproject.toml` needs 3.12 or
newer). The peer and the agent run on 3.11 (their `.venv`s on the Pi are 3.11.2; both need 3.11 or newer), so peer and
agent code uses nothing newer than 3.11. Engram: its `uv.lock` (numpy, scipy, sqlite-vec), pytest. Peer: standard
library, FastAPI and `cryptography` as today. Agent: standard library only. uv. Run on the station's Raspberry Pi 5
(`smart`).

**Spec:** `engram/docs/superpowers/specs/2026-10-25-store-imprint-design.md`, revision 6, at `e737e02`, cited below as
"I" with its section numbers and decisions (D1–D41). Also read: the contract `docs/city-rail-vision.md` ("Imprints:
porting a store here"); the interface table `docs/superpowers/reviews/2026-10-25-city-rail-interfaces.md` (rows cited
as "row N"); the consolidation log `docs/superpowers/reviews/2026-10-25-city-rail-consolidation.md`; the permissions
spec `docs/superpowers/specs/2026-10-25-permissions-by-place-design.md` ("P"), the source of truth for what a
permission means; the trail spec `engram/docs/superpowers/specs/2026-10-25-trail-arrows-design.md` ("T").

**Scope.** I's step 1 only: every section from 5 to 16. I 17's later steps are not built. Build order across the
three plans: permissions core (`docs/superpowers/plans/2026-10-25-permissions-by-place.md`, "the permissions plan"),
then this plan, then trails step 1. This plan uses the permissions plan's files as listed in "What this plan uses
from the other plans", and two seams that the trails plan fills.

**Build branch.** A new worktree `/home/andy/superyak/.worktrees/imprints` on branch `imprints`, made from `main` once
the permissions plan's branch `permissions-core` has merged there (its gate G6). Every path below is relative to that
worktree. Each task's commands start from the worktree root.

## Global Constraints

- **Off by default, nothing live.** Nothing runs unless a person runs a command. On `superyak-peer serve`, the imprint
  routes answer 404 unless `--imprints-dir` is given (ruling R8), so the lighthouse serves none until its unit is
  changed, which is a gate. No task deploys, restarts a service, installs a unit, posts to the station, or touches
  `~/.engram/imprints`, `~/.superyak` or `~/.local/share/superyak`. Every test sets `HOME`, `ENGRAM_HOME`,
  `STATION_DATA`, `IMPRINTS` and every `--imprints-dir` under `tmp_path`, and shims `systemd-run` and `systemctl` on
  `PATH` as `peer/tests/test_station_units.py:89-112` does. Deploy and live checks are gates, never steps.
- **Nothing more leaves, nothing widens.** No task lets a byte leave a machine that I lets stay, or allows a use that
  I 8 refuses. Where this plan settles something the spec leaves open, it takes the narrower choice.
- **No new dependency.** Peer: its standard library and `cryptography`. Agent: the standard library only. Engram: what
  it already uses. No engram module imports `cryptography` (ruling R9).
- **Names, verbatim from the spec.** New modules `engram/imprint.py` and `peer/superyak_peer/imprints.py`, plus the
  builder's split of I 19 (ruling R1). Record kinds `imprint-permission` and `imprint-receipt`; file kinds
  `engram-imprint-request` and `engram-imprint-manifest` (version 1), `imprint-admission-allow`, `imprint-use-allow`,
  `imprint-use-result`; filter `imprint-filter-v1`; attestation `no-unconsented-others-v1`; requester
  `agent:station-imprints`; audience `place:home/<operator>`; copy `imprint:<station peer id>/<imprint id>`;
  collection `collection:<owner handle>/imprint-<imprint_id>`; origin `imprint` (`ORIGIN_IMPRINT`); meta keys
  `ancestry` and `ancestry_complete`; purposes `calibration` and `trail-evaluation`; statuses `requested`, `allowed`,
  `received`, `approved`, `admitted`, `deleting`, `deleted`, `declined`, `expired`; receipt events `received`,
  `approved`, `denied`, `admitted`, `failed`, `use-started`, `use-finished`, `refused`, `shortened`, `withdrawn`,
  `ended`, `deleted`, `delete-failed`; deletion reasons `denied`, `failed`, `withdrawn`, `ended`, `upload-expired`,
  `review-expired`, `station`, `missing`, `restore`; use ends `report`, `withdrawn`, `ended`, `deleted`,
  `allow changed`, `not evaluable: limit`, `failed`; units `superyak-imprint-admit-<imprint id>`,
  `superyak-imprint-use-<imprint id>`, `superyak-imprint-sweep.service` and `.timer`; the flag `--imprints-dir`; the
  Make variable `IMPRINTS ?= $(HOME)/.engram/imprints`; every file name of I 9, 10 and 12.
- **Constants (I 14), as module constants where code uses them:** part size `PART_BYTES = 4_194_304`; largest package
  2 GiB; largest request body 64 KiB; largest manifest 256 KiB; live imprint bytes per station 16 GiB; free-space floor
  4 GiB after reserving 3 × package bytes; 4 open requests per ship; 1 live imprint per source store per station;
  confirm code life 10 minutes; upload and review windows 7 days each; longest permission 365 days; 120 part uploads
  per ship per minute; sweep hourly; receipt signing at start, every 60 s and before an imprint read; closed session
  `CLOSED_SECONDS = 3600`; `MAX_ANCESTRY = 64`; `MAX_MEMORIES = 100_000`; calibration `MemoryMax=4G`,
  `MemorySwapMax=0`, `RuntimeMaxSec=1800`, `MAX_LANE_EPISODES = 7500`; 400 days after `deleted`; 30 days after a
  decline or an expiry; agent wait 9 minutes per run; use id a lowercase uuid4 of 36 characters; unfinished use at
  1,860 s; the use's unit `TimeoutStopSec=60`; a begun admission with no result fails 1,860 s after its `decided_at`
  (`ADMISSION_BOUND`, R24), and the admission's unit also gets `TimeoutStopSec=60`.
- **Times.** Requests, manifests, records, receipts and allow files hold integer UTC seconds. Stored engram times are
  read with ISO-8601 rules; a time with no zone is UTC (I 5.2).
- **Canonical JSON** is the peer's (`peer/superyak_peer/identity.py:20-23`): keys sorted, `,` and `:` with no spaces,
  UTF-8, no NaN, and no floats anywhere in a hashed value. Engram reproduces it in `imprint_filter.canonical`, never
  with `lighthouse_protocol.canonical_json`, which orders keys by UTF-16 units (`engram/lighthouse_protocol.py:113-120`).
- **What receipts and manifests hold.** No memory content, query text, memory ids, paths of left-out rows, or anything
  about what stayed home (I 3, D21). An error is named by its class, never its message.
- **Test commands on this Pi** (`smart`, Raspberry Pi 5, 16 GB, `/tmp` on disk; checked 2026-10-25):
  - engram: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider <tests>`
  - peer: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider <tests>`
  - agent: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider <tests>`
  Each task writes its command out in full.
- **Packaging.** A new engram module joins `[tool.setuptools] py-modules` in `engram/pyproject.toml` in the task that
  creates it. A new peer module joins both lists in `peer/pyproject.toml` (the sdist list at `:51-90` and the wheel's
  `only-include` at `:141-180`), and each new peer test file joins the sdist list's tests (`:95-137`). So does each
  new file the peer tests read: `tests/imprint_support.py` (Task 23) and
  `tests/fixtures/imprints/ceiling_agreement.json` (Task 27). Each new systemd unit joins the sdist list's `systemd/`
  entries (`:45-50`; Task 42b), since the bundle ships `tests/test_station_units.py`, which lists them. A new peer test
  that reads the repository outside `peer/` skips in the standalone bundle, as `tests/test_station_units.py:88` and
  `tests/test_ship_agent.py:10-13` do: `test_imprint_units.py` (the Makefile), `test_imprint_docs.py` (`CLAUDE.md`,
  `engram/CLAUDE.md`) and `test_imprint_end_to_end.py` (`engram/`, `agent/`). A new agent module joins
  `agent/pyproject.toml`'s `only-include`.
- **Existing tests stay unchanged,** with one exception: Task 42b updates `peer/tests/test_station_units.py`'s expected
  unit list and `systemctl` calls, because I 15 adds the sweep's units to `make station-units`. New tests go in new
  files.
- **Commits.** One per task, on `imprints` only, ending with the session's attribution line. No push, merge or deploy.

## Rulings

Choices the spec leaves to the builder (I 19) or does not fix. A reviewer checks each; Andy can veto any.

| # | Ruling | Why |
|---|---|---|
| R1 | `imprint.py` is split by responsibility: `engram/imprint_filter.py` (5.2, 5.4, 6.2: selection, rows, digest), `engram/imprint_checks.py` (6.4's L1–L4 and section 10's 17 checks), `engram/imprint.py` (the command and its steps), and `engram/imprint_copies.py` (`copies_held`, standard library only, so the owner's `uses` command loads no numpy; Task 45). The peer side stays one module, `imprints.py`, as I 15 names it. The agent's is `agent/superyak_agent/imprint.py`. | I 19: "how `imprint.py` is split into modules" is the builder's. Each file then has one job. |
| R2 | Two peer tables, `imprint_requests` and `imprint_receipts`, DDL in Task 23. Every time column is integer UTC seconds. | I 19 leaves the DDL; I 15 lists the fields. |
| R3 | `store_identity.independent` returns `True`, `False` or `None`, and `None` is printed `unknown`. Callers test `is True`. | A string `"unknown"` is truthy, so `if independent(...)` would count it. Only `true` counts (I 11). |
| R4 | `stamp_fork` called without ancestry writes `[parent]`, incomplete. | Conservative for any caller that predates this plan; I 11's rule for an old fork. |
| R5 | `imprint_filter.canonical(value) -> bytes` is the peer's canonical JSON and refuses floats. | I 5.4 names the peer's form. Engram's own differs for keys outside the BMP. |
| R6 | A plan id is a uuid4 hex; it is shown by its first 4 characters, and commands take a unique prefix of at least 4. | As station items' short ids (`ships.py:279-287`). |
| R7 | With a ship key, `GET /api/imprints` also returns `{"ship", "owner", "operator", "station"}`: `operator` is the super admin's username, which `check_request` reads for the audience (Task 24), and `station` is the station's peer id. `agent imprint context` writes it to `~/.superyak/imprints/context.json` (0600), and `imprint.py plan` reads it for D37, the dry run's "Station" line, the plan's owner, and `parse_terms`' `operator`, so a plan naming another home is refused on the owner's machine. | The plan must know the requesting ship's owner (D37) and the operator whose home the audience names (I 5.3) before anything is sent. This sends only the ship key. |
| R8 | `superyak-peer serve` registers the imprint routes only when `--imprints-dir` is given; without it they answer 404, as on the door. Station commands keep the default `$HOME/.engram/imprints` (I 10). | Off by default. The deploy gate that adds the flag to the lighthouse's unit is the switch. |
| R9 | Check 3's signature part runs the peer's `verify-imprint --permission FILE` in the peer environment. `imprint.py admit` takes that command as `verify_cmd`; the Makefile passes it. | `verify_station_record` lives in the peer (I 15). Engram gains no dependency. |
| R10 | Two seams to the trails plan. `imprint.count_roads_and_trails(conn, *, lanes, as_of, derive=None)` calls T's pure functions through `derive`; when `trails` can't be imported, admission with `route` fails with check `count` and the message "roads and trails can't be counted: trails.py is not installed". `imprint.use(..., trails_cmd=None)` runs `[sys.executable, <engram>/trails.py, ...]` by default. Tests pass stubs. | Build order puts trails after imprints. Failing closed narrows; no imprint with `route` is admitted until trails step 1 is on the Pi (gate G13). |
| R11 | An admission failure names its step: a check number 1–17, `calibration` or `count`. `imprint.py admit` exits 0 admitted, 1 failed (with `result.json`), 4 withdrawn during admission, 5 ended during admission. | YN4: the count and calibration had no name. Exit codes let the sync and the unit tell the cases apart. |
| R12 | The evaluation's `--seed` is `int(use_id[:8], 16)`. | I 12 says `--seed N` without fixing N; this makes a run repeatable from its receipt. |
| R13 | An imported row's id is `u-` + the first 32 hex of SHA-256 of `receipt id + action + purpose + batch number` (batch from 0). | YN6 makes rows per action **and** purpose; I 12's formula without the purpose would give two rows one id. |
| R14 | `POST /api/imprints` refuses a null `until`. The plan always writes one (t₁ defaults to the plan's time, I 5.2). | YN3: the count reads `as_of` = `until`. Narrower than I 14's "null or". |
| R15 | The use's unit gets `-p UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET` exactly when it gets no `--setenv=ENGRAM_EMBEDDER_SOCKET=…`, never both. | XN2: D29 then holds whatever the user manager's environment later holds. `UnsetEnvironment=` is applied last (systemd.exec(5), systemd 252 on the Pi). |
| R16 | Pi measurements run only with `ENGRAM_PI_BUDGET=1`, as the permissions plan's R21. | The default suite stays fast; the reviewer runs them on the Pi. |
| R17 | The ceiling's agreement fixture is `peer/tests/fixtures/imprints/ceiling_agreement.json`. The peer test checks the station's check against it; the engram test checks P's `decide_bulk` against the same file. | I 16 "One ceiling per copy" compares two packages' code; a shared fixture lets each suite run its own side. |
| R18 | The records' `reason` names the station by `STATION_NAME = "Deep Space 9"` in `imprints.py`. | I 8's example text. |
| R19 | The confirm checks the password with `Auth.check_password_attempt(username, password, source) -> bool`, the login path of `peer/superyak_peer/auth.py:80-100` without making a session, with its limits (8 per user, 40 per source, 5 minutes). | I 8: "checked as `/api/login` checks it, and attempts count against the same limits". |
| R20 | `superyak-peer station-imprint-unit-env` prints, shell-quoted, the use unit's `--setenv=…` or `-p UnsetEnvironment=…`, reading only `$HOME/.config/superyak/runtime.json` by `scripts/runtime.py:84-88`'s rule, and exits 2 on any other value. The Makefile `eval`s its output. | I 12's socket rule, testable in Python rather than in Make. |
| R21 | `verify-imprint --dir DIR` writes `DIR/verified.json` (the station key and the ids of receipts whose chain and signature verify, in chain order). `import-receipts` imports only those. | I 12 imports "each verified receipt"; engram can't verify Ed25519 itself (R9). |
| R22 | Withdrawing a `requested` item (no yes yet) is a decline: the staging directory goes, the row turns `declined` and stays content-free, and no receipt is written. | Goal 6: no permission, no receipt. |
| R23 | A use's unit runs `station-imprint-use-begin`, which prints the use id on its only stdout line; the Makefile passes it to `imprint.py use`. | I 12: the begin step makes the use id. |
| R24 | A begun admission runs once. `station-imprint-admit-begin` writes `admission.json` only when none exists, and refuses a row that has one, writing nothing. `make station-imprint-admit` with no ID resumes only `approved` rows with no `admission.json` (decided again first, D39, maybe days on). The sync fails an `approved` row that has `admission.json`, no `result.json`, and a `decided_at` more than `ADMISSION_BOUND = 1860` s ago (the unit's `RuntimeMaxSec=1800` plus its `TimeoutStopSec=60`, so the unit is gone): `failed` with step `calibration` and the fixed message `ADMISSION_STOPPED`, then the deletion, reason `failed`. A shortening's rewrite of `admission.json` keeps `decided_at`. | I 10: a memory limit or a timeout fails admission, and D16: any failure deletes the package. A unit killed at its cap writes no `result.json`, so without a bound the row would stay `approved`, with its bytes on the Pi, until its end, and every resume would calibrate it again. The files can't tell a cap from a crash, so both fail closed and the owner sends again. The spec's resume (D39) keeps its case: an admission that never began. I 10 counts a memory limit and a timeout as calibration's failures, hence the step name. |
| R25 | Receipt `detail` keys are listed once, in Task 23's `DETAIL_KEYS`, and every task writes and reads those names. A failure names its step under `step` (R11), never `check`. `denied` may carry `term` (the decision refused at approval). `failed` carries `{step, message}` when admission ran and failed, or `{term}` alone when the decision refused at a run's start or the run ended during admission. | I 12's table gives `denied` no detail and `failed` a check number and a message, but I 10 and Task 29 record the term the decision refused on, and YN2's import reads it. One name everywhere. Gate G15. |

## Carried items

Items from the consolidation log, and the checks it records, that belong to this spec. Each is a task or a gate.

| Item | What it asks | Where |
|---|---|---|
| YS1 | The owner's words misstate how recall updates resonances: each recall updates every resonance with one of its results in it, so `last_seen` is when either was last recalled. | Tasks 15 (dry run), 25 (confirm data) and 47 (the view) use YS1's words: "Resonances, pairs of memories recalls returned together, keep when they formed and when either was last recalled." A builder's note in `imprint_filter.TIMES_WORDS` says `last_accessed` also moves when an episode leaves core (`engram/storage.py:987-1012`). Gate G15: the spec's 5.4 and 9 take the same words. |
| YN1 | N, admission's count at t₁, can exceed what one evaluation derives (it runs one lane, with no `--as-of`). | Task 35: `roads_and_trails` is documented as R(I) as `Need` names it, at `as_of` = t₁, over the scope's lanes; Task 48 says so in `peer/API.md`. The use's command stays as I 12 has it. Gate G15. |
| YN2 | "Ended during admission" writes a `failed` receipt that may come after the count; every imported receipt with no N needs the null row. | Task 45: one row per action on roads and trails with `returned` null for **every** imported receipt of a `route` imprint that carries no `roads_and_trails`. Its test names a `denied` receipt "naming a failing term". |
| YN3 | `until` may be null in the request, but the count reads `as_of` = `until`. | R14; Tasks 15 and 24. |
| YN4 | The count, and calibration, have no failure name of their own. | R11; Tasks 34 and 35. |
| YN5 | T must not put its imprint check into the pure functions admission calls. | A dependency on the trails plan (see "What this plan uses"), gate G12. Task 35 calls only pure functions. |
| YN6 | Imported rows are per action and purpose. | R13; Task 45's test counts rows per (action, purpose). |
| YN7 | A boundary word in T 11. | Not this spec's: the trails plan. Task 21's fixture keeps no source row at exactly t₁ either way. |
| XN2 | `UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET` when there is no `--setenv`. | R15; Task 40. |
| CN7, second half | No test that no use is finished while the imprint is `deleting`. | Task 39, `test_no_use_is_finished_while_deleting`. |
| CN8 | A withdrawal or station delete could also stop the use's unit. | Gate G16: not built in step 1. The run's own end checks, and rules 2 to 4 of I 12, already record it. It only narrows. |
| XS1, XS2, XM1, XN1, XS3, CS1, CS2, CN1–CN6 | Applied in the spec. | Tasks 21 (XS1), 34 and 35 (XS2, CS1), 27 and 28 (XM1's two owners), 38 and 39 (XN1, CS2, CN1, CN4, CN6), 40 (CN1, CN2, CN5), 15 and 25 (XS3). |
| XN6 | Which item of P's `Req` holds the ceiling in a step-2 ledger. | Gate G17: P 14 step 2's to say. Not built. |
| Not this spec's | XN3, XN4, XN5, BS1–BS3, BN1–BN4, T's FS1 and FN1–FN3. | The permissions and trails plans. Listed so none is dropped. |

## Review Focus

Inputs and failures the spec implies that no test in I 16 exercises, most likely first. Each has a test in the task
named.

1. **An admission that died before it wrote a result.** A run killed at `MemoryMax=4G`, at `RuntimeMaxSec=1800` or
   by a crash writes no `result.json`. A begun admission runs once (R24): `station-imprint-admit-begin` refuses a row
   whose `admission.json` exists, and `make station-imprint-admit` with no ID resumes only rows with none. So no run
   ever finds a dead run's `<id>.state/calibration/`. If one does (only `imprint.py admit` run twice by hand could),
   it fails with step `calibration` before calibrating, rather than clearing it (`calibrate` creates its directory
   with `exist_ok=False`, `engram/calibrate.py:251`). The sync fails the row once `decided_at` + 1,860 s has passed:
   `failed` (step `calibration`, `ADMISSION_STOPPED`), then the deletion, reason `failed`. A run that died after
   writing `imprint.json` ends the same way, so a half-registered imprint is never admitted. Failing closed narrows;
   the owner sends again. Tasks 34 (`test_rf1_a_dead_runs_calibration_fails_the_rerun`) and 36
   (`test_a_begun_admission_with_no_result_fails_once_its_bound_passes`).
2. **A disk that fills while `complete` joins the parts.** No partial `imprint.db` is left, the status stays `allowed`,
   the parts stay, and a later `complete` succeeds. Task 26, `test_rf2_failed_join_leaves_no_partial_file`.
3. **An honest package with non-ASCII text.** Emoji, accents, CJK text and very long tokens in chosen memories must
   pass L1–L4 and checks 16 and 17, so the owner is never refused for writing in their language. Task 14,
   `test_rf3_honest_unicode_package_passes_every_leak_check`.
4. **A `--store` path through a symlink or `..`.** A path that resolves to the published house, or into an imprints
   root, is refused like the plain path. Task 8, `test_rf4_store_paths_resolve_before_refusals`.
5. **Two `make imprint-send` runs of one plan at once.** `imprint.py build` holds a lock on the plan for its whole run,
   so one plan makes one package and one imprint id; the agent's `send` holds a lock on the imprint, so parts are never
   sent twice under two requests and `send.json` is never torn. The second run refuses (exit 4). Tasks 19
   (`test_rf5_a_second_build_of_one_plan_refuses`) and 43a (`test_rf5_two_sends_of_one_plan_never_interleave`).

## File Structure

| File | Responsibility |
|---|---|
| `engram/store_identity.py` | `ORIGIN_IMPRINT`, `ImprintRefused`, `is_imprint`, ancestry, lineage, `independent`, `stamp_imprint`, ancestry in `stamp_fork`. Task 1. |
| `engram/storage.py`, `sharing.py`, `federation.py`, `cli.py`, `lighthouse_sheaf.py` | The guards of I 11; `fork` passes ancestry. Tasks 1 to 3. |
| `engram/calibrate.py`, `engram/persistence.py`, `engram/sheaf.py` | `no_content`, `no_paths`, `notes`, `create_parents`, the working-copy flag, the dense-set bound (`sheaf.measure_all` and `persistence.audit_unchecked_events` included). Tasks 2, 4, 5. |
| `engram/store_reader.py` | `connect(..., vec=True)`. Task 32. |
| `engram/imprint_filter.py` (new) | Table rules, selection, terms, rows that leave, sessions, log rows, digest, the owner's words, cross-references. Tasks 6 to 12, 15, 17. |
| `engram/imprint_checks.py` (new) | L1–L4 and the 17 checks. Tasks 14, 32, 33. |
| `engram/imprint.py` (new) | The command: `plan`, `read`, `build`, `admit`, `use`, `list`, `import-receipts`; the package writer; the count. Tasks 13, 15 to 19, 34, 35, 38, 45. |
| `engram/imprint_copies.py` (new) | `copies_held`, standard library only, for the owner's use list. Task 45. |
| `engram/permission_uses.py`, `engram/permission_cli.py` | The owner's use list shows each copy held (P 10: "The imprints spec builds this"). Task 45. |
| `engram/pyproject.toml` | `py-modules` gains `imprint_filter`, `imprint`, `imprint_checks`, `imprint_copies`. Tasks 6, 13, 14, 45. |
| `engram/tests/imprint_support.py` (new) | Engram test builders. Task 1, grown by later tasks. |
| `engram/tests/test_imprint_*.py` (new) | I 16's filter, admission and lineage tests. |
| `peer/superyak_peer/identity.py` | `RECORD_KEYS` for the two kinds; `verify_station_record`. Task 22. |
| `peer/superyak_peer/imprints.py` (new) | Everything of I 15's `imprints.py` row. Tasks 23 to 27, 29 to 31, 36, 37, 39, 41, 42a, 44. |
| `peer/superyak_peer/db.py` | The `Imprints` mixin and `IMPRINT_SCHEMA` in `Store`. Task 23. |
| `peer/superyak_peer/signatures.py` | `SIGNED_RECORDS` names the imprint permission's and the receipts' signatures (G4b). Task 23. |
| `peer/superyak_peer/auth.py` | `check_password_attempt` (R19). Task 25. |
| `peer/superyak_peer/app.py`, `peer_routes.py` | The routes of I 9; the signing task in the lifespan. Tasks 24 to 26, 30, 31, 41. |
| `peer/superyak_peer/ships.py`, `__main__.py` | Pending, decide, notices and describe learn `imprint`; the new station commands; `--imprints-dir`. Tasks 24, 26, 29, 30, 36, 37, 40, 42a, 44. |
| `peer/superyak_peer/static/app.js`, `app.css` | The confirm view and Accounts → Imprints. Task 47. |
| `peer/systemd/superyak-imprint-sweep.service`, `.timer` (new) | The hourly sweep. Task 42b. |
| `peer/pyproject.toml` | `superyak_peer/imprints.py` in both lists; each new test file, `tests/imprint_support.py`, the fixture and the two sweep units in the sdist list. Tasks 22 to 49. |
| `peer/API.md`, `engram/CLAUDE.md`, `CLAUDE.md` | Routes, records, the signing contract; the Imprints paragraph; the approving rule. Task 48. |
| `peer/tests/imprint_support.py`, `peer/tests/test_imprint_*.py`, `peer/tests/fixtures/imprints/` (new) | I 16's station tests, the Makefile tests and the end-to-end test. |
| `peer/tests/test_station_units.py` | The sweep's two units in its expected lists (the one existing test changed). Task 42b. |
| `agent/superyak_agent/imprint.py` (new), `__main__.py`, `station.py`, `agent/pyproject.toml` | `imprint context`, `send`, `status`, `withdraw`, `shorten`; a raw `PUT` body. Tasks 43a, 43b. |
| `agent/tests/test_imprint_agent.py` (new) | The agent's tests. Tasks 43a, 43b. |
| `Makefile` | The targets of I 13, the units and `station-units`. Tasks 40, 42b, 46. |

## What this plan uses from the other plans

**From the permissions plan** (merged first; its "What the other plans use"):

- `permission_ledger.Ledger.open_read_only(engram_home)`, raising `FileNotFoundError` or `LedgerUnreadable` (its
  Task 10); `Ledger.store_row(instance_id) -> dict | None` and `Ledger.cosubjects(ref) -> frozenset[str]` (its Task
  11); `Ledger.latest_lane_note(ref) -> str | None` (its Task 17). Task 8 here.
- `permission_uses.Uses.open(engram_home)`, `UseRow`, `Uses.append_imported(row, subjects)` (its Task 14) and
  `Uses.owner_list(state, ...)` (its Task 15), which Task 45 here extends with a `copies` keyword; the `uses` command
  of `permission_cli.py` (its Task 27). Task 45 here.
- `permissions.parse_copy_ref` (its Task 1), `permissions.decide_bulk`, `BulkUse` (its Task 7), `State.from_tables`
  (its R2) and `engram/tests/permissions_support.py`'s `World` (its Task 2). Tasks 28 and 35 here.
- Migration `029_share_identity.sql` with `shared_memories.source_instance_id` (its Task 16), which `shared(m, A)`
  matches on (I 5.2). Task 7 here.

**From the trails plan** (built after this one; its names are T's until that plan fixes them):

- T 11's pure functions for touches, trails and support (T 4 and 5), called by `count_roads_and_trails` through the
  `derive` seam (R10). They take a connection and `as_of`, read no clock, and do not run the imprint check (YN5): the
  check stays in the `trails.py` CLI (gate G12). Task 35's real-function test, `test_count_matches_the_trail_functions`,
  runs once they exist (gate G13).
- `trails.py`'s CLI with `--evaluate --lane --seed --deadline --json --imprint-use` and exit status 3 for
  `allow changed` (T 7, 11), run by `imprint.py use` through the `trails_cmd` seam. Task 38.
- `embeddings.create_embedding_provider(local_files_only=True)` (T 11). Gate G11.
- Nothing in the trails plan may change this plan's file layout, allow file or `result.json` names; T 7 and 11 read
  them as I 12 writes them (interface row 27).

---

### Task 1: Ancestry, lineage and `stamp_imprint`

**Files:**
- Modify: `engram/store_identity.py` (`KEYS` at `:43-49`, `stamp_fork` at `:143-160`)
- Modify: `engram/cli.py:38-49` (`fork_instance` reads the parent's ancestry and passes it)
- Create: `engram/tests/imprint_support.py`
- Test: `engram/tests/test_imprint_lineage.py`

**Interfaces:**
- Consumes: `store_identity.effective_id`, `read`, `_write`.
- Produces:
  - `ORIGIN_IMPRINT = "imprint"`; `MAX_ANCESTRY = 64`; `KEYS` gains `"ancestry"` and `"ancestry_complete"`;
  - `class ImprintRefused(RuntimeError)`; `is_imprint(conn) -> bool` (stored origin is `imprint`);
  - `ancestry(conn) -> tuple[list[str], bool]`, by I 11's six rules, read only;
  - `class Lineage(NamedTuple): ids: frozenset[str]; complete: bool`; `lineage(conn) -> Lineage`;
  - `independent(a: Lineage, b: Lineage) -> bool | None` (R3);
  - `stamp_fork(conn, forked_from_instance_id, source_ancestry: list[str] | None = None, source_complete: bool = False) -> str` (R4);
  - `stamp_imprint(conn, source_instance_id: str, source_ancestry: list[str], source_complete: bool, imprint_id: str) -> None`, mirroring `stamp_fork`, no commit;
  - `imprint_support`: `T(iso: str) -> int`; `new_store(tmp_path, name) -> Storage`; `retro_store(tmp_path, name, first: tuple[str, str]) -> Storage`; `unidentified_store(tmp_path, name) -> sqlite3.Connection`; `fork_of(tmp_path, parent, name) -> Storage` (backup copy plus `stamp_fork`, as `cli.py:38-49`); `old_fork_of(...)` (the same, then the two ancestry keys deleted); `imprint_of(tmp_path, parent, name) -> Storage`; `file_copy(tmp_path, store, name) -> Storage`; `iid(store) -> str`; `GENOME_PARENT`, a fixed lowercase uuid4; `genome_with_parent(tmp_path) -> Path` (an engram dir whose `genome/graph.db` was forked, by `stamp_fork`, from a store with id `GENOME_PARENT`); `iid_of(path: Path) -> str` (the stored `instance_id` of the store at `path`, read-only).

- [ ] **Step 1: Write the failing tests**

```python
from store_identity import ancestry, independent, lineage, stamp_imprint, MAX_ANCESTRY, ORIGIN_IMPRINT
from tests.imprint_support import (fork_of, file_copy, iid, imprint_of, new_store, old_fork_of, retro_store,
                                   unidentified_store)

def test_lineage_pairs_from_the_spec(tmp_path):
    g = new_store(tmp_path, "g"); y = fork_of(tmp_path, g, "y"); x = fork_of(tmp_path, y, "x")
    z = fork_of(tmp_path, g, "z"); i = imprint_of(tmp_path, x, "i"); i2 = imprint_of(tmp_path, x, "i2")
    L = lambda s: lineage(s.conn)
    for p, q in [(x, g), (x, z), (y, z), (i, g), (i, x), (i, i2), (i, fork_of(tmp_path, x, "f")),
                 (file_copy(tmp_path, g, "c"), g), (imprint_of(tmp_path, fork_of(tmp_path, y, "x2"), "i3"), g)]:
        assert independent(L(p), L(q)) is False
    assert L(i) == ({iid(i), iid(x), iid(y), iid(g)}, True)
    assert independent(L(new_store(tmp_path, "a")), L(new_store(tmp_path, "b"))) is True
    assert independent(L(old_fork_of(tmp_path, g, "w")), L(new_store(tmp_path, "u"))) is None

def test_stores_older_than_identity_are_never_complete(tmp_path):
    r = retro_store(tmp_path, "r", first=("e0", "2025-01-01T00:00:00+00:00"))
    r2 = retro_store(tmp_path, "r2", first=("e1", "2025-01-02T00:00:00+00:00"))   # its copy pruned e0 first
    assert ancestry(r.conn) == ([], False) and iid(r) != iid(r2)
    assert independent(lineage(r.conn), lineage(r2.conn)) is None
    assert lineage(imprint_of(tmp_path, r, "ir").conn).complete is False
    assert ancestry(unidentified_store(tmp_path, "n")) == ([], False)

def test_a_chain_longer_than_64_is_cut_and_incomplete(tmp_path):
    p = new_store(tmp_path, "p")
    p.conn.execute("INSERT OR REPLACE INTO meta VALUES ('ancestry', ?), ('ancestry_complete', 'true')",
                   (json.dumps([str(uuid.uuid4()) for _ in range(MAX_ANCESTRY)]),)); p.conn.commit()
    child = fork_of(tmp_path, p, "c")
    got, complete = ancestry(child.conn)
    assert len(got) == MAX_ANCESTRY and got[0] == iid(p) and complete is False

def test_stamp_imprint_writes_exactly_the_identity_keys_and_does_not_commit(tmp_path):
    src = fork_of(tmp_path, new_store(tmp_path, "g"), "src"); dst = new_store(tmp_path, "dst")
    stamp_imprint(dst.conn, iid(src), *ancestry(src.conn), "c0a8f5e2-0000-4000-8000-000000000000")
    assert dst.conn.in_transaction
    meta = dict(dst.conn.execute("SELECT key, value FROM meta"))
    assert meta["instance_id"] == "c0a8f5e2-0000-4000-8000-000000000000" and meta["instance_id_origin"] == ORIGIN_IMPRINT
    assert meta["forked_from_instance_id"] == iid(src) and json.loads(meta["ancestry"])[0] == iid(src)

def test_cli_fork_passes_the_parents_ancestry(tmp_path):
    engram_dir = genome_with_parent(tmp_path)          # genome forked from a recorded store
    fork_instance("w", engram_dir=engram_dir)
    conn = sqlite3.connect(engram_dir / "instances" / "w" / "graph.db")
    assert ancestry(conn)[0][:2] == [iid_of(engram_dir / "genome" / "graph.db"), GENOME_PARENT]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_lineage.py`
Expected: FAIL, `ImportError: cannot import name 'ancestry' from 'store_identity'`.

- [ ] **Step 3: Implement ancestry, lineage and the stamps in `engram/store_identity.py`**

`meta.ancestry` is canonical JSON of distinct lowercase ids, nearest first; `meta.ancestry_complete` is `true` or
`false`. The child of parent P is `[P's id] + ancestry(P)`, cut to `MAX_ANCESTRY`, complete when P is complete, P's id
is not null and nothing was cut. Without the keys: origin `creation` and no `forked_from_instance_id` gives `([], True)`;
origin `retroactive` or no stored identity gives `([], False)`; a `forked_from_instance_id` gives `([it], False)`; a
fork with none gives `([], False)`. `lineage` is `{effective_id} ∪ ancestry` (no id: the ancestry alone, incomplete).
`cli.fork_instance` calls `ancestry(src)` on the read-only source connection and passes it to `stamp_fork`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/store_identity.py engram/cli.py engram/tests/imprint_support.py engram/tests/test_imprint_lineage.py
git commit -m "Imprints: ancestry, lineage, independent and stamp_imprint (I 11, D13)"
```

### Task 2: Opening guards

**Files:**
- Modify: `engram/storage.py:84-118` (`Storage.__init__`)
- Modify: `engram/sharing.py:99-110` (`share`), `engram/federation.py:155-175` (`sync_genome`), `engram/cli.py:15-30` (`fork_instance`)
- Modify: `engram/calibrate.py:268` (the working copy's `Storage(str(working), imprint_working_copy=True)`)
- Modify: `engram/tests/imprint_support.py` (`imprint_file`)
- Test: `engram/tests/test_imprint_guards.py`

**Interfaces:**
- Consumes: Task 1's `is_imprint`, `ImprintRefused`.
- Produces: `Storage(db_path, migrations_dir=None, *, check_same_thread=True, imprint_working_copy=False)`, raising
  `ImprintRefused` after connecting and before `_restore_pragmas()` and `_run_migrations()`; `share`, `sync_genome`
  and `fork_instance` refuse an imprint source; `imprint_support.imprint_file(tmp_path, name="imprint.db") -> Path`
  (a rollback-journal file stamped `imprint`, with its newest `schema_version` row removed so a migration is pending).

- [ ] **Step 1: Write the failing tests**

```python
def test_storage_refuses_an_imprint_before_any_pragma_or_migration(tmp_path):
    path = imprint_file(tmp_path); before = path.read_bytes()
    with pytest.raises(ImprintRefused):
        Storage(str(path))
    assert path.read_bytes() == before and not Path(f"{path}-wal").exists() and not Path(f"{path}-shm").exists()
    Storage.open_read_only(path).close()
    copy = tmp_path / "working.db"; shutil.copyfile(path, copy)
    Storage(str(copy), imprint_working_copy=True).close()

def test_share_sync_genome_and_fork_refuse_an_imprint(tmp_path):
    imp, pub = Storage.open_read_only(imprint_file(tmp_path)), new_store(tmp_path, "pub")
    with pytest.raises(ImprintRefused):
        share(source_storage=imp, published_storage=pub, source_id="e1", layer="episode", audience="group:ph",
              reason="r", source_instance="default")
    with pytest.raises(ImprintRefused):
        sync_genome(str(imprint_file(tmp_path, "genome.db")), new_store(tmp_path, "inst"))
    engram_dir = engram_dir_with_imprint_instance(tmp_path, "imp")   # instances/imp/graph.db stamped imprint
    with pytest.raises(SystemExit):
        fork_instance("x", engram_dir=engram_dir, from_source="imp")
    assert not (engram_dir / "instances" / "x" / "graph.db").exists()

def test_resolve_db_path_never_returns_an_imprint(tmp_path, monkeypatch):
    home = tmp_path / "engram"; imprint_dir = home / ".engram" / "imprints" / "c0a8"
    imprint_dir.mkdir(parents=True); shutil.copyfile(imprint_file(tmp_path), imprint_dir / "imprint.db")
    for name in ("../imprints/c0a8", "imprints/c0a8", "c0a8"):
        monkeypatch.setenv("ENGRAM_DEFAULT_INSTANCE", name)
        assert resolve_db_path(home, tmp_path / "project") == home / ".engram" / "graph.db"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_guards.py`
Expected: FAIL, `Failed: DID NOT RAISE <class 'store_identity.ImprintRefused'>`, in the first two tests.
`test_resolve_db_path_never_returns_an_imprint` passes already: it guards today's rule (step 3 leaves
`resolve_db_path` unchanged), as Task 20's canary test guards Tasks 13 to 19.

- [ ] **Step 3: Implement the guards**

`Storage.__init__` reads `SELECT value FROM meta WHERE key='instance_id_origin'` (when `meta` exists in
`sqlite_master`) right after `sqlite3.connect`, closes the connection and raises `ImprintRefused` unless
`imprint_working_copy`. `share` checks `is_imprint(source_storage.conn)`; `sync_genome` checks the raw genome
connection it already opens (`federation.py:168-172`); `fork_instance` opens the source read-only, checks, and exits
1 with "the source is an imprint; imprints are never forked" before copying. `resolve_db_path` is unchanged: imprints
live under `imprints/`, never at `instances/<name>/graph.db`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 3 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/storage.py engram/sharing.py engram/federation.py engram/cli.py engram/calibrate.py engram/tests/imprint_support.py engram/tests/test_imprint_guards.py
git commit -m "Imprints: Storage, share, sync_genome and fork refuse an imprint (I 11, D12)"
```

### Task 3: `lighthouse_sheaf` refuses imprints and reports independence

**Files:**
- Modify: `engram/lighthouse_sheaf.py:267-269` (`_open`), `:350-372` (`compare_stores`), `:381-404` (`_format`)
- Modify: `engram/tests/imprint_support.py` (`ep`, `vec`)
- Test: `engram/tests/test_imprint_guards.py`

**Interfaces:**
- Consumes: Task 1's `lineage`, `independent`, `is_imprint`.
- Produces: `_open(path)` raises `ImprintRefused` for an imprint; `independence(stores: dict[str, str | Path]) ->
  list[dict]`, one `{"a", "b", "independent": true | false | "unknown", "evidence": "independent" | "not independent
  evidence"}` per pair in name order; `compare_stores(...)` output gains `"independence"`; `_format` prints one line
  per pair that is not `independent`. `imprint_support.ep(store, id, *, lane="work", at=..., session=None,
  content=None, core=0)` and `vec(store, layer, id, seed)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_lighthouse_sheaf_refuses_an_imprint(tmp_path):
    with pytest.raises(ImprintRefused):
        lighthouse_sheaf.query_vector(imprint_file(tmp_path), "episode", "e1")

def test_sibling_stores_are_flagged_and_unrelated_ones_are_not(tmp_path):
    g = new_store(tmp_path, "g"); a, b = fork_of(tmp_path, g, "a"), fork_of(tmp_path, g, "b")
    c = new_store(tmp_path, "c")
    got = {(p["a"], p["b"]): p for p in lighthouse_sheaf.independence({"a": a.db_path, "b": b.db_path, "c": c.db_path})}
    assert got[("a", "b")] == {"a": "a", "b": "b", "independent": False, "evidence": "not independent evidence"}
    assert got[("a", "c")]["independent"] is True and got[("a", "c")]["evidence"] == "independent"
    for s in (a, b): vec(s, "episode", ep(s, "e1"), seed=1)
    out = lighthouse_sheaf.compare_stores({"a": a.db_path, "b": b.db_path}, query=np.ones(768), k=1)
    assert out["independence"][0]["evidence"] == "not independent evidence"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_guards.py`
Expected: FAIL, `AttributeError: module 'lighthouse_sheaf' has no attribute 'independence'`.

- [ ] **Step 3: Implement the refusal and the report**

`_open` opens read-only, then raises `ImprintRefused` when `is_imprint(store.conn)`, closing first. `independence`
opens each path with `store_reader.connect` and compares `lineage`s; `None` is written `"unknown"` (R3). The sheaf's
numbers are unchanged: pairs are flagged, never dropped (I 11's table).

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/lighthouse_sheaf.py engram/tests/imprint_support.py engram/tests/test_imprint_guards.py
git commit -m "Imprints: lighthouse_sheaf refuses imprints and flags pairs that are not independent (I 11)"
```

### Task 4: Calibration's admission flags

**Files:**
- Modify: `engram/calibrate.py:244-310` (`calibrate`), `:165-180` (`cohesion_report`), `:313-393` (`render_markdown`)
- Test: `engram/tests/test_imprint_calibrate.py`

**Interfaces:**
- Consumes: today's `calibrate`.
- Produces:
  - `calibrate(source, out, migrate=True, now=None, *, no_content=False, no_paths=False, notes: Mapping[str, str] | None = None, max_lane_episodes: int | None = None, create_parents=True) -> dict` (`max_lane_episodes` is wired in Task 5);
  - `PATHS_NOT_MEASURED = "not measured at admission; trails are used only by the trail evaluation"`;
  - `strip_content(value)`: a copy with every `content` key removed at any depth;
  - `notes` keys name top-level report sections (`"snapshot"`); each sentence is stored as `report["notes"][name]`
    and printed as `- Note: <sentence>` under that section's heading in `report.md`, before either file is written.

- [ ] **Step 1: Write the failing tests**

```python
NOW = datetime(2026, 10, 25, 19, 0, tzinfo=timezone.utc)

def test_no_content_leaves_no_content_key_and_no_memory_text(tmp_path):
    src = calibration_source(tmp_path)          # 12 work episodes with vectors, one semantic over 10 of them, two cores
    report = calibrate(src, tmp_path / "out", no_content=True, now=NOW)
    files = [(tmp_path / "out" / n).read_text() for n in ("report.json", "report.md")]
    assert not has_key(report, "content") and '"content"' not in files[0]
    for text in memory_texts(src):
        assert all(text[:24] not in f for f in files)
    assert report["source_unchanged"] is True and report["source_side_files_created"] == []

def test_no_paths_writes_only_the_fixed_sentence(tmp_path):
    report = calibrate(calibration_source(tmp_path), tmp_path / "out", no_paths=True, now=NOW)
    assert report["analyses"]["paths"] == PATHS_NOT_MEASURED
    assert PATHS_NOT_MEASURED in (tmp_path / "out" / "report.md").read_text()

def test_notes_sit_beside_their_section_in_both_reports(tmp_path):
    note = "0 sessions and 0 log rows, because route was not chosen"
    report = calibrate(calibration_source(tmp_path), tmp_path / "out", notes={"snapshot": note}, now=NOW)
    md = (tmp_path / "out" / "report.md").read_text()
    assert report["notes"] == {"snapshot": note} and md.index("## Snapshot") < md.index(f"- Note: {note}") < md.index("## Store identity")

def test_create_parents_false_never_recreates_a_removed_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        calibrate(calibration_source(tmp_path), tmp_path / "gone" / "calibration", create_parents=False, now=NOW)
    assert not (tmp_path / "gone").exists()

def test_defaults_keep_todays_report(tmp_path):
    report = calibrate(calibration_source(tmp_path), tmp_path / "out", now=NOW)
    assert "sessions_total" in report["analyses"]["paths"] and has_key(report, "content")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_calibrate.py`
Expected: FAIL, `TypeError: calibrate() got an unexpected keyword argument 'no_content'`.

- [ ] **Step 3: Implement the flags in `engram/calibrate.py`**

`out.mkdir(parents=create_parents, exist_ok=False)`. With `no_paths`, `paths.report` is not called and the section is
the sentence. With `no_content`, `strip_content` runs on the whole report before `report.json` and `report.md` are
written, and `render_markdown` prints no excerpt (the hub and cohesion lines lose their text column). The working copy
open passes `imprint_working_copy=True` (Task 2).

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/calibrate.py engram/tests/imprint_support.py engram/tests/test_imprint_calibrate.py
git commit -m "Calibrate: no_content, no_paths, notes and create_parents for admission (I 10)"
```

### Task 5: Every dense set bounded at 7,500

**Files:**
- Modify: `engram/calibrate.py:146-162` (`persistence_scores`), `:165-180` (`cohesion_report`), `:183-212` (`persistence_preview`), `calibrate`
- Modify: `engram/persistence.py:215-253` (`audit_unchecked_events`), `:342-417` (`classify_hubs`, `flag_redundant_cores`)
- Modify: `engram/sheaf.py:266-282` (`measure_all`)
- Test: `engram/tests/test_imprint_calibrate.py`

**Interfaces:**
- Consumes: Task 4.
- Produces: `persistence.classify_hubs(storage, cfg, min_episodes=10, *, max_episodes: int | None = None, skips: list | None = None)`;
  `persistence.flag_redundant_cores(storage, cfg, *, max_episodes=None, skips=None)`;
  `persistence.audit_unchecked_events(storage, cfg, *, max_episodes=None, skips=None)` (per event, the two peers'
  vectored sources that `split_band`'s `distance_matrix` and MSTs span, `persistence.py:110-125`);
  `sheaf.measure_all(storage, cfg, *, max_episodes=None, skips=None)` (per semantic, the sources whose n × n `W`, `L`,
  eigenvectors and residuals `cohesion_energy` builds, `sheaf.py:61-87`);
  `calibrate.persistence_scores(conn, *, max_episodes=None, skips=None)`, `calibrate.cohesion_report(store, *,
  max_episodes=None, skips=None)` and `calibrate.persistence_preview(store, *, max_episodes=None, skips=None)`, which
  pass the bound on. A set is counted with `COUNT(*)` before any vector is read; over the bound it is skipped, never
  sampled, and `{"set": "lane:<lane>" | "core" | "hub:<semantic id>" | "cohesion:<semantic id>" | "event:<subdivision
  event id>", "n": n, "bound": b}` is appended. `calibrate` writes the list as
  `report["analyses"]["skipped_dense_sets"]`. `MAX_LANE_EPISODES = 7500` in `calibrate.py`. I 10 lists three dense
  sets; `measure_all` and `audit_unchecked_events` are two more that calibration reaches (gate G15).

- [ ] **Step 1: Write the failing tests**

```python
def test_every_dense_set_over_the_bound_records_a_skip(tmp_path, monkeypatch):
    src = dense_source(tmp_path, lane_n=13, cores=13, hub_sources=13, event_sources=13)   # an unchecked subdivision event
    built = []                                       # whose two peers hold 13 vectored sources together
    monkeypatch.setattr(persistence, "distance_matrix", spy(persistence.distance_matrix, built, size=len))
    monkeypatch.setattr(sheaf, "build_local_sheaf", spy(sheaf.build_local_sheaf, built, size=lambda sid, ids, *a: len(ids)))
    report = calibrate(src, tmp_path / "out", max_lane_episodes=12, now=NOW)
    sets = {s["set"].split(":")[0] for s in report["analyses"]["skipped_dense_sets"]}
    assert sets == {"lane", "core", "hub", "cohesion", "event"} and max(built, default=0) <= 12

def test_the_real_bound_is_7500(tmp_path, monkeypatch):
    src = dense_source(tmp_path, lane_n=7501, cores=0, hub_sources=0)
    monkeypatch.setattr(persistence, "build_filtration", refuse_over(7500))
    report = calibrate(src, tmp_path / "out", max_lane_episodes=MAX_LANE_EPISODES, now=NOW)
    assert {"set": "lane:work", "n": 7501, "bound": 7500} in report["analyses"]["skipped_dense_sets"]

@pytest.mark.skipif(os.environ.get("ENGRAM_PI_BUDGET") != "1", reason="Pi measurement (R16)")
def test_pi_budget_a_7500_episode_lane_fits_in_4g(tmp_path):
    src = dense_source(tmp_path, lane_n=7500, cores=0, hub_sources=0, dim=768)   # random unit vectors
    peak = child_peak_rss("calibrate.persistence_scores(Storage.open_read_only(SRC).conn)", src=src)
    assert peak < 4 * 1024**3 - 512 * 1024**2
```

The child's peak resident size comes from `resource.getrusage(RUSAGE_CHILDREN).ru_maxrss` after it exits. The
reviewer also runs this test under `systemd-run --user --scope -p MemoryMax=4G -p MemorySwapMax=0` (see
"Verification before merge").

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_calibrate.py`
Expected: FAIL, `KeyError: 'skipped_dense_sets'`.

- [ ] **Step 3: Implement the bound**

`calibrate(max_lane_episodes=…)` passes the bound to `persistence_scores` (each lane, `calibrate.py:146-162`'s set);
through `persistence_preview` to `flag_redundant_cores` (the core set, which has no lane bound today),
`classify_hubs` (each semantic's sources) and `audit_unchecked_events` (each event's two peers); and through
`cohesion_report` to `sheaf.measure_all` (each semantic's sources, whose count its `GROUP BY` already reads). The spies
on `distance_matrix` (which `build_filtration`, `split_band` and `classify_hubs` call) and `build_local_sheaf` (which
precedes every `cohesion_energy`) see every dense matrix calibration builds. `None` keeps today's behaviour. I 10's
"Why 7,500": n_max = ⌊√((4 GiB − 512 MiB) / (7.5 × 8 B))⌋ = 7,914; step 1 uses 7,500.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 7 passed, 1 skipped (the Pi measurement, without `ENGRAM_PI_BUDGET=1`).

- [ ] **Step 5: Commit**

```bash
git add engram/calibrate.py engram/persistence.py engram/sheaf.py engram/tests/imprint_support.py engram/tests/test_imprint_calibrate.py
git commit -m "Calibrate: every dense set bounded at 7,500 episodes, skipped never sampled (I 10, D31)"
```

### Task 6: Every table has a rule

**Files:**
- Create: `engram/imprint_filter.py`
- Modify: `engram/pyproject.toml` (`py-modules` gains `"imprint_filter"`)
- Modify: `engram/tests/imprint_support.py` (`add_hook_tables`, `hook_ddl_names`)
- Test: `engram/tests/test_imprint_tables.py`

**Interfaces:**
- Produces:
  - `TABLE_RULES: dict[str, str]`, every table of I 6.2 in its order, valued `filtered`, `dropped`, `rebuilt` or
    `never` (`sqlite_stat1`–`4`);
  - `HOOK_TABLES = ("context_threads", "context_prev_embedding", "nudge_co_fire_window", "nudge_surfaced")` (absent
    from a package); `session_bias` is a migration table (`011_session_bias.sql`) and `dropped`;
  - `DIGEST_TABLES`, the ten tables of I 5.4 in its order; `CITING_OPERATIONS = ("mark_core", "instinct_feedback", "dream_react")`;
  - `is_shadow(name: str, virtual: Iterable[str]) -> bool` (a virtual table's name plus `_`);
  - `SourceTables(copied: tuple[str, ...], dropped: tuple[str, ...], unnamed: tuple[str, ...])`;
    `classify_source(conn) -> SourceTables`;
  - `class UnclassifiedTable(RuntimeError)`; `check_package_tables(conn) -> None` (D4: a package table with no rule
    stops the build).

- [ ] **Step 1: Write the failing tests**

```python
def test_every_table_classified(tmp_path):
    store = new_store(tmp_path, "all"); add_hook_tables(store.conn)    # DDL read from hooks/nudge.py and hooks/wake.py
    virtual = virtual_tables(store.conn)
    for name in table_names(store.conn):
        assert name in TABLE_RULES or is_shadow(name, virtual), name
    assert hook_ddl_names() <= set(TABLE_RULES)      # every CREATE TABLE in the hooks, session_bias included

def test_a_source_only_table_is_not_copied_and_is_named(tmp_path):
    store = new_store(tmp_path, "s"); store.conn.execute("CREATE TABLE my_notes(id TEXT PRIMARY KEY)")
    assert classify_source(store.conn).unnamed == ("my_notes",)

def test_a_package_table_without_a_rule_stops_the_build(tmp_path, monkeypatch):
    monkeypatch.delitem(TABLE_RULES, "anchors")
    with pytest.raises(UnclassifiedTable, match="anchors"):
        check_package_tables(new_store(tmp_path, "p").conn)

def test_citing_operations_match_the_stop_hook():
    tree = ast.parse((ENGRAM / "hooks" / "sleep.py").read_text())
    assert CITING_OPERATIONS == literal_assigned(tree, "CITING_OPERATIONS")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_tables.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'imprint_filter'`.

- [ ] **Step 3: Implement the rules in `engram/imprint_filter.py`**

Copy I 6.2's table into `TABLE_RULES` in order, with the "why" as a comment on each line. `CITING_OPERATIONS` is a
copy, checked against `hooks/sleep.py:44` by the test, so no hook module is imported. Add `"imprint_filter"` to
`py-modules`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 4 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint_filter.py engram/pyproject.toml engram/tests/imprint_support.py engram/tests/test_imprint_tables.py
git commit -m "Imprints: every table classified, deny by default (I 6.2, D4)"
```

### Task 7: The selection and the terms

**Files:**
- Modify: `engram/imprint_filter.py`
- Modify: `engram/tests/imprint_support.py` (`selection`, `terms`, `ctx`, `published_house`, `share_as`)
- Test: `engram/tests/test_imprint_selection.py`

**Interfaces:**
- Consumes: `sharing.validate_audience`, `sharing.audiences_for`, `lighthouse_protocol`'s `content_digest` as
  `sharing._verify_reused_copy` uses it (`sharing.py:77-96`); migration 029's `shared_memories.source_instance_id`.
- Produces:
  - `class PlanRefused(ValueError)`;
  - `imprint_support.share_as(store, published, id, audience, *, layer="episode", source_instance_id=None)` records a
    share as `sharing.share` does, with the store's own id unless another is given;
  - `Selection` (frozen): `lanes: frozenset[str]`, `layers: frozenset[str]`, `since: int | None`, `until: int`,
    `shared_with: str | None`, `exclude: frozenset[str]`, `unsourced: bool`;
    `parse_selection(*, lanes, layers, since, until, shared_with, exclude_file, unsourced, now: int) -> Selection`
    (no default for lanes or layers; `until` defaults to `now`; dates with no zone are UTC);
  - `Terms` (frozen): `audience: str`, `actions: frozenset[str]`, `purposes: frozenset[str]`, `days: int`, with
    `route: bool`; `parse_terms(*, audience, actions, purposes, days, operator: str) -> Terms` (I 5.3: audience
    exactly `place:home/<operator>`, the operator fitting `[a-z][a-z0-9-]{0,62}`; actions `imprint`, optionally
    `route`; purposes `calibration`, plus `trail-evaluation` exactly with `route`; days 1 to 365);
  - `parse_instant(text: str | None) -> datetime | None` (aware UTC; `None` when it does not parse);
  - `SourceContext` (frozen): `source_path: Path`, `source_id: str`, `instance_name: str`, `owner: str`,
    `published: Path | None`, `ledger: object | None`;
  - `base(conn, layer: str, sel: Selection, ctx: SourceContext, counts: Counter) -> list[str]`, ids in
    `(created_at, id)` order; Task 8 adds `cosubjects` and `pending` to it;
  - `shared(published_conn, row: dict, layer: str, ctx: SourceContext, audience: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
def test_lanes_and_the_half_open_window(tmp_path):
    s = new_store(tmp_path, "s")
    for i, at in {"in": "2026-01-01T00:00:00+00:00", "no-zone": "2026-05-01T00:00:00",
                  "just-before": "2026-10-25T17:59:59.999999+00:00", "at-t1": "2026-10-25T18:00:00+00:00",
                  "before": "2025-12-31T23:59:59.999999+00:00", "bad": "yesterday"}.items():
        ep(s, i, at=at)
    ep(s, "personal", lane="personal", at="2026-02-01T00:00:00+00:00")
    counts = Counter()
    got = base(s.conn, "episode", selection(since=T("2026-01-01"), until=T("2026-10-25T18:00:00Z")), ctx(s), counts)
    assert got == ["in", "no-zone", "just-before"] and counts["unparseable_time"] == 1

def test_exclude_and_layers(tmp_path):
    s = new_store(tmp_path, "s"); ep(s, "a"); ep(s, "b")
    assert base(s.conn, "episode", selection(exclude={"b"}), ctx(s), Counter()) == ["a"]
    with pytest.raises(PlanRefused):
        parse_selection(lanes="", layers="episode", since=None, until=None, shared_with=None,
                        exclude_file=None, unsourced=False, now=T("2026-10-25"))

def test_shared_with_matches_instance_layer_audience_and_digest(tmp_path):
    s, pub = new_store(tmp_path, "s"), published_house(tmp_path)
    for i in ("shared", "other-audience", "changed", "other-instance", "other-layer"): ep(s, i)
    share_as(s, pub, "shared", "group:ph"); share_as(s, pub, "other-audience", "group:parks")
    share_as(s, pub, "changed", "group:ph"); s.conn.execute("UPDATE episodes SET content='edited' WHERE id='changed'")
    share_as(s, pub, "other-instance", "group:ph", source_instance_id=str(uuid.uuid4()))  # another store's share of that id
    share_as(s, pub, "other-layer", "group:ph", layer="semantic")         # the id shared as a semantic, not this episode
    got = base(s.conn, "episode", selection(shared_with="group:ph"), ctx(s, published=pub), Counter())
    assert got == ["shared"]

def test_terms_accept_only_step_one_values():
    assert parse_terms(audience="place:home/andy", actions="imprint,route", purposes="calibration,trail-evaluation",
                       days=90, operator="andy").route
    for bad in [dict(audience="place:home/jenn"), dict(actions="route"), dict(purposes="calibration"),
                dict(days=366), dict(days=0), dict(operator="andy.b", audience="place:home/andy.b")]:
        with pytest.raises(PlanRefused):
            parse_terms(**{**ROUTE_TERMS, **bad})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_selection.py`
Expected: FAIL, `ImportError: cannot import name 'base' from 'imprint_filter'`.

- [ ] **Step 3: Implement the selection**

`base` reads each row's id, lane, `created_at` and content in `ORDER BY created_at, id`, and keeps it by I 5.2's
`base(m)` less the two ledger terms. Instants compare as aware datetimes, fractions included. `shared` follows I 5.2's
four conditions; with 029's column present it matches on `source_instance_id` = `ctx.source_id`, and a row with a null
id matches nothing.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 4 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint_filter.py engram/tests/imprint_support.py engram/tests/test_imprint_selection.py
git commit -m "Imprints: the selection, its half-open window, shared-with and the terms (I 5.2, 5.3)"
```

### Task 8: The ledger's reads and the source's refusals

**Files:**
- Modify: `engram/imprint_filter.py`
- Modify: `engram/tests/imprint_support.py` (`ledger`)
- Test: `engram/tests/test_imprint_selection.py`

**Interfaces:**
- Consumes: the permissions plan's `Ledger.open_read_only`, `store_row`, `cosubjects`, `latest_lane_note`.
- Produces:
  - `open_ledger(engram_home: Path) -> Ledger | None` (no file: `None`; unreadable: `PlanRefused("The permissions ledger can't be read; nothing was planned.")`);
  - `check_owner(ledger, source_id: str, owner: str) -> None` (D37);
  - `base` now also drops `cosubjects(m) ≠ ∅` (counted under `needs_yes`, keyed by person) and `pending(m)` (counted
    under `lane_unsettled`);
  - `published_house(engram_home: Path) -> Path` (`.engram/instances/lighthouse/graph.db`);
  - `check_source(path: Path, conn, *, engram_home: Path, imprint_roots: Sequence[Path] = ()) -> None`: refuses the
    published house and anything under an imprints root by resolved path, an imprint by origin, unknown migrations
    (`store_reader._schema(...)["unknown"]`) and a store with no derivable identity.

- [ ] **Step 1: Write the failing tests**

```python
def test_co_subjects_and_unsettled_lanes_stay_home_and_are_counted(tmp_path):
    s = new_store(tmp_path, "s"); home = tmp_path / "home"
    for i in ("plain", "about-jenn", "pending", "other-lane", "no-note"): ep(s, i)
    led = ledger(home, owner="sam", store=s, cosubjects={"about-jenn": "person:jenn"},
                 lane_notes={"pending": "pending", "other-lane": "personal", "plain": "work"})
    counts = Counter()
    got = base(s.conn, "episode", selection(), ctx(s, ledger=led), counts)
    assert got == ["no-note", "plain"]                   # one created_at, so id order
    assert counts["needs_yes:person:jenn"] == 1 and counts["lane_unsettled"] == 2
    assert sorted(base(s.conn, "episode", selection(), ctx(s, ledger=None), Counter())) == sorted(
        ["plain", "about-jenn", "pending", "other-lane", "no-note"])

def test_source_owner_d37(tmp_path):
    s = new_store(tmp_path, "s"); home = tmp_path / "home"
    with pytest.raises(PlanRefused, match="not registered"):
        check_owner(ledger(home, owner="sam", store=None), iid(s), "sam")
    with pytest.raises(PlanRefused, match="person:jenn"):
        check_owner(ledger(tmp_path / "h2", owner="sam", store=s, store_owner="person:jenn"), iid(s), "sam")
    check_owner(None, iid(s), "sam")                     # no ledger: the owner's word stands

def test_refused_sources(tmp_path):
    home = tmp_path / "engram"
    for path, why in [(published_house_file(home), "published house"), (imprint_file(tmp_path), "imprint"),
                      (empty_old_store(tmp_path), "no identity"), (future_store(tmp_path), "newer than this code")]:
        with pytest.raises(PlanRefused, match=why):
            check_source(path, store_reader.connect(path, immutable=True), engram_home=home)

def test_rf4_store_paths_resolve_before_refusals(tmp_path):
    home = tmp_path / "engram"; pub = published_house_file(home)
    link = tmp_path / "link.db"; link.symlink_to(pub)
    dotted = home / ".engram" / "instances" / "x" / ".." / "lighthouse" / "graph.db"
    root = tmp_path / "imprints"; inside = root / "c0a8" / "imprint.db"; inside.parent.mkdir(parents=True)
    shutil.copyfile(new_store(tmp_path, "plain").db_path, inside)
    for path in (link, dotted, inside):
        with pytest.raises(PlanRefused):
            check_source(path, store_reader.connect(path, immutable=True), engram_home=home, imprint_roots=[root])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_selection.py`
Expected: FAIL, `ImportError: cannot import name 'check_owner' from 'imprint_filter'`.

- [ ] **Step 3: Implement the reads and refusals**

Refs are `mem:<source id>/<layer>/<id>`. `cosubjects(m)` is `ledger.cosubjects(ref) - {f"person:{owner}"}`.
`pending(m)` is true when `ledger.latest_lane_note(ref)` is `pending` or names a lane other than the row's `lane`; no
ledger or no note gives false (D40). `check_source` compares `Path.resolve()` of the given path with the published
house and each root. Messages are fixed sentences that name the reason, never a memory.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint_filter.py engram/tests/imprint_support.py engram/tests/test_imprint_selection.py
git commit -m "Imprints: co-subjects, unsettled lanes, the source owner and refused sources (I 5.1, 5.2, D37, D40)"
```

### Task 9: Down-closure, the shipped memories and induced links

**Files:**
- Modify: `engram/imprint_filter.py`
- Modify: `engram/tests/imprint_support.py` (`sem`, `prune`, `resonance`, `peer_edge`, `subdivision`)
- Test: `engram/tests/test_imprint_links.py`

**Interfaces:**
- Consumes: Tasks 7, 8.
- Produces:
  - `MAX_MEMORIES = 100_000`;
  - `Admissible(episodes: tuple[str, ...], semantics: tuple[str, ...], counts: Counter)`;
    `admissible(conn, sel, ctx) -> Admissible`: Ê, then Ŝ = base semantics whose recorded sources all lie in Ê and
    that have one (or `sel.unsourced`); counts `semantic_source_stays` and `semantic_unsourced`;
  - `Shipped(episodes: tuple[str, ...], semantics: tuple[str, ...])` with `members() -> frozenset[tuple[str, str]]`
    of (layer, id) and `refs(source_id: str) -> list[str]` (sorted `mem:` refs); `shipped(adm, sel) -> Shipped`
    (Λ chooses; refuses none or more than `MAX_MEMORIES`);
  - `semantic_rows(conn, sh) -> list[dict]` (`contradicted_by` null when it names a semantic outside S);
    `vector_rows(conn, layer: str, ids: Sequence[str]) -> list[dict]` (`{"id", "embedding"}` in memory order);
  - `link_rows(conn, sel, sh) -> dict[str, list[dict]]` for `semantic_sources`, `resonances`, `semantic_peers`,
    `subdivision_events`, by I 6.2.

- [ ] **Step 1: Write the failing tests**

```python
def test_down_closure_over_recorded_sources(tmp_path):
    s = new_store(tmp_path, "s")
    for i in ("e-in", "e2", "gone"): ep(s, i)
    ep(s, "e-out", lane="personal")
    sem(s, "s-mixed", sources=["e-in", "e-out"]); sem(s, "s-whole", sources=["e-in", "e2"])
    sem(s, "s-none", sources=[]); sem(s, "s-pruned-one", sources=["e2", "gone"]); prune(s, "gone")
    adm = admissible(s.conn, selection(), ctx(s))
    assert set(adm.semantics) == {"s-whole", "s-pruned-one"}
    assert adm.counts["semantic_source_stays"] == 1 and adm.counts["semantic_unsourced"] == 1
    assert "s-none" in admissible(s.conn, selection(unsourced=True), ctx(s)).semantics

def test_layers_choose_what_ships_never_what_is_admissible(tmp_path):
    s = new_store(tmp_path, "s"); ep(s, "e1"); ep(s, "e2"); sem(s, "s1", sources=["e1"]); sem(s, "s2", sources=["e2"])
    sh = shipped(admissible(s.conn, selection(layers={"semantic"}, exclude={"e2"}), ctx(s)), selection(layers={"semantic"}))
    assert sh.episodes == () and sh.semantics == ("s1",)

def test_each_link_row_with_an_endpoint_outside_m_is_dropped(tmp_path):
    s = links_store(tmp_path)      # every link table with one row inside M and one row reaching outside it
    rows = link_rows(s.conn, selection(until=T("2026-10-25T18:00:00Z")), shipped_all(s))
    assert [r["episode_id"] for r in rows["semantic_sources"]] == ["e-in"]
    assert [r["id"] for r in rows["resonances"]] == ["res-in"]          # res-out and res-after-t1 dropped
    assert [r["peer_id"] for r in rows["semantic_peers"]] == ["s-peer-in"]
    assert [r["id"] for r in rows["subdivision_events"]] == ["sub-in"]

def test_contradicted_by_is_cleared_when_it_names_a_semantic_that_stays(tmp_path):
    s = new_store(tmp_path, "s"); ep(s, "e1"); sem(s, "kept", sources=["e1"], contradicted_by="home-only")
    sem(s, "home-only", sources=["e1"], lane="personal")
    assert semantic_rows(s.conn, Shipped(("e1",), ("kept",)))[0]["contradicted_by"] is None

def test_no_memories_or_too_many_is_refused(tmp_path, monkeypatch):
    s = new_store(tmp_path, "s")
    with pytest.raises(PlanRefused, match="no memories"):
        shipped(admissible(s.conn, selection(), ctx(s)), selection())
    for i in range(4): ep(s, f"e{i}")
    monkeypatch.setattr(imprint_filter, "MAX_MEMORIES", 3)
    with pytest.raises(PlanRefused, match="100,000"):
        shipped(admissible(s.conn, selection(), ctx(s)), selection())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_links.py`
Expected: FAIL, `ImportError: cannot import name 'admissible' from 'imprint_filter'`.

- [ ] **Step 3: Implement down-closure, Λ and the link rules**

`src(s)` is read from `semantic_sources` as it is now (pruning cascaded, I 5.2). A resonance ships when both
`(layer_a, memory_a)` and `(layer_b, memory_b)` are in `members()` and `t₀ ≤ τ(created_at) < t₁`. A subdivision event
ships when `parent_id` and every id in `json.loads(peer_ids)` are semantics in S. The refusal message for too many is
"This selection holds more than 100,000 memories, the most one imprint can hold. Narrow it."

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint_filter.py engram/tests/imprint_support.py engram/tests/test_imprint_links.py
git commit -m "Imprints: down-closure, the shipped memories and links induced on them (I 5.2, 6.2, 6.4)"
```

### Task 10: Sessions closed at t₁, session ids and `operation_log`

**Files:**
- Modify: `engram/imprint_filter.py`
- Modify: `engram/tests/imprint_support.py` (`op`, `log_row`, `footpath_store`)
- Test: `engram/tests/test_imprint_logs.py`

**Interfaces:**
- Consumes: Tasks 7, 9.
- Produces:
  - `CLOSED_SECONDS = 3600`;
  - `closed_sessions(conn, t1: int) -> frozenset[str]`: sessions whose newest row before t₁ (episodes by
    `session_id`, `memory_log` by `context.session_id` of any event type, `operation_log` by `session_id`) is older
    than t₁ − 3,600 s;
  - `episode_rows(conn, sh, terms, closed) -> list[dict]`: every column but `rowid`, in `(created_at, id)` order;
    `session_id` kept only when `terms.route` and the session is in `closed`, else null (D6, D7);
  - `operation_rows(conn, sel, terms, closed, sh) -> list[dict]`: empty without `route`; else rows with `operation`
    in `CITING_OPERATIONS`, `t₀ ≤ τ < t₁`, a closed session, every target in M; `harness`, `model`, `repo` null and
    `details` `{}`.

- [ ] **Step 1: Write the failing tests**

```python
T1 = T("2026-10-25T18:00:00Z")

def test_closed_at_t1_reads_every_row_kind_before_t1_only(tmp_path):
    s = new_store(tmp_path, "s")
    ep(s, "a", session="old", at="2026-10-25T16:00:00+00:00")
    ep(s, "b", session="late-log", at="2026-10-25T16:00:00+00:00")
    log_row(s, session="late-log", at="2026-10-25T17:30:00+00:00", event="cohesion_pass")
    ep(s, "c", session="late-op", at="2026-10-25T16:00:00+00:00")
    op(s, "o1", session="late-op", at="2026-10-25T17:10:00+00:00", operation="share", targets=["c"])
    ep(s, "d", session="after", at="2026-10-25T16:00:00+00:00"); ep(s, "e", session="after", at="2026-10-25T19:00:00+00:00")
    assert closed_sessions(s.conn, T1) == {"old", "after"}

def test_session_ids_ship_only_with_route_and_only_for_closed_sessions(tmp_path):
    s = new_store(tmp_path, "s")
    ep(s, "w1", session="closed", at="2026-10-25T15:00:00+00:00"); ep(s, "w2", session="open", at="2026-10-25T17:30:00+00:00")
    sh, closed = Shipped(("w1", "w2"), ()), closed_sessions(s.conn, T1)
    assert [r["session_id"] for r in episode_rows(s.conn, sh, terms(route=False), closed)] == [None, None]
    assert [r["session_id"] for r in episode_rows(s.conn, sh, terms(route=True), closed)] == ["closed", None]
    assert "rowid" not in episode_rows(s.conn, sh, terms(route=True), closed)[0]

def test_operation_rows_are_citing_closed_inside_m_and_scrubbed(tmp_path):
    s = ops_store(tmp_path)        # mark_core on a kept episode; share; a target outside M; a row after t1; an open session
    rows = operation_rows(s.conn, selection(until=T1), terms(route=True), closed_sessions(s.conn, T1), shipped_all(s))
    assert [r["id"] for r in rows] == ["o-kept"]
    assert (rows[0]["harness"], rows[0]["model"], rows[0]["repo"], rows[0]["details"]) == (None, None, None, "{}")
    assert operation_rows(s.conn, selection(until=T1), terms(route=False), closed_sessions(s.conn, T1), shipped_all(s)) == []

def test_no_footpath_rows_without_route(tmp_path):
    s = footpath_store(tmp_path)  # one closed session wrote two work-lane episodes and made no recall
    rows = episode_rows(s.conn, shipped_all(s), terms(route=False), closed_sessions(s.conn, T1))
    assert len(rows) == 2 and all(r["session_id"] is None for r in rows)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_logs.py`
Expected: FAIL, `ImportError: cannot import name 'closed_sessions' from 'imprint_filter'`.

- [ ] **Step 3: Implement sessions and the two scrubs**

Times are compared with `parse_instant`; rows whose time does not parse take no part in "newest". Episodes' columns
come from `PRAGMA table_info(episodes)`, so the row is whole but for `session_id`. `operation_log.target_ids` is a
JSON list; a row with no target, or any target not an episode or semantic in M, is dropped.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 4 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint_filter.py engram/tests/imprint_support.py engram/tests/test_imprint_logs.py
git commit -m "Imprints: sessions closed at t1; session ids and citing operations only with route (I 5.2, D7)"
```

### Task 11: `memory_log` rows

**Files:**
- Modify: `engram/imprint_filter.py`
- Modify: `engram/tests/imprint_support.py` (`recall`, `route_shown`, `inst`)
- Test: `engram/tests/test_imprint_logs.py`

**Interfaces:**
- Consumes: Task 10.
- Produces:
  - `normalize_outcome(text: str | None) -> str | None`: `used: auto: cited` when equal to it, else `used` or
    `not_used` by prefix, else null;
  - `memory_log_rows(conn, sel, terms, closed, sh, instinct_ids: frozenset[str]) -> list[dict]`: empty without
    `route`. Recall rows lose instinct ids, and ship whole only when the rest is non-empty and inside M, with `context`
    `{recall_id, session_id}` (those present). `route_shown` rows ship with targets cut to M in order, dropped when cut
    to nothing or when `context.lane ∉ L`, with `context` `{receipt_id, session_id, tool, lane}` and `outcome` null.
    Every other event type is dropped. Every kept row has a closed session and `t₀ ≤ τ < t₁`.

- [ ] **Step 1: Write the failing tests**

```python
def test_recall_rows_lose_instincts_and_ship_whole_or_not_at_all(tmp_path):
    s = recall_store(tmp_path)   # rows: [e1, i1] kept; [e1, e-home] dropped; [i1] dropped; [e1, e2] kept
    rows = memory_log_rows(s.conn, selection(until=T1), terms(route=True), closed_sessions(s.conn, T1),
                           shipped_all(s), instinct_ids(s))
    assert [json.loads(r["target_ids"]) for r in rows if r["event_type"] == "recall"] == [["e1"], ["e1", "e2"]]

def test_kept_recall_rows_keep_two_context_keys_and_normalized_outcomes(tmp_path):
    s = recall_store(tmp_path, outcomes=["used: auto: cited", "used — it helped me with Jenn", "not_used, meh", "odd"],
                     query="who drove me")
    rows = recall_rows_of(s)
    assert [r["outcome"] for r in rows] == ["used: auto: cited", "used", "not_used", None]
    assert all(set(json.loads(r["context"])) <= {"recall_id", "session_id"} for r in rows)
    assert all("who drove" not in json.dumps(r) and "Jenn" not in json.dumps(r) for r in rows)

def test_route_shown_rows_are_cut_to_m_in_order(tmp_path):
    s = route_shown_store(tmp_path)   # [e3, e-home, e1] work; [e-home] work; [e1] personal lane; extra context keys
    rows = [r for r in rows_of(s) if r["event_type"] == "route_shown"]
    assert [json.loads(r["target_ids"]) for r in rows] == [["e3", "e1"]]
    assert set(json.loads(rows[0]["context"])) == {"receipt_id", "session_id", "tool", "lane"} and rows[0]["outcome"] is None

def test_no_kept_row_carries_a_cut_mark(tmp_path):
    for r in rows_of(route_shown_store(tmp_path)) + rows_of(recall_store(tmp_path)):
        assert "cut" not in json.loads(r["context"]) and set(r) == set(MEMORY_LOG_COLUMNS)

def test_log_rows_need_route_a_closed_session_and_the_window(tmp_path):
    s = recall_store(tmp_path, extra=[("after-t1", "2026-10-25T18:00:00+00:00"), ("open", "2026-10-25T17:45:00+00:00")])
    ids = [r["id"] for r in rows_of(s)]
    assert "after-t1" not in ids and "open" not in ids
    assert memory_log_rows(s.conn, selection(until=T1), terms(route=False), closed_sessions(s.conn, T1),
                           shipped_all(s), instinct_ids(s)) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_logs.py`
Expected: FAIL, `ImportError: cannot import name 'memory_log_rows' from 'imprint_filter'`.

- [ ] **Step 3: Implement the two kept event types**

`instinct_ids` is every id in the source's `instincts` table. The session of a row is `context.session_id`; a row
without one is dropped. The row keeps its `id`, `timestamp`, `event_type` and `layer` as stored.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 9 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint_filter.py engram/tests/imprint_support.py engram/tests/test_imprint_logs.py
git commit -m "Imprints: recall and route_shown rows, whole or cut to what ships, with no mark (I 6.2, D35)"
```

### Task 12: The package's rows and the plan digest

**Files:**
- Modify: `engram/imprint_filter.py`
- Test: `engram/tests/test_imprint_digest.py`

**Interfaces:**
- Consumes: Tasks 7 to 11.
- Produces:
  - `FILTER = "imprint-filter-v1"`; `canonical(value) -> bytes` (R5; raises `ValueError` on a float, NaN or a
    non-JSON value); `sha256_value(v: str | bytes | None) -> str` (a null hashes as `""`);
  - `row_key(table: str, row: dict) -> list` for the ten tables of I 5.4's table;
  - `scope_of(sel: Selection) -> dict`: `{"lanes", "layers", "since", "until", "shared_with", "unsourced_semantics"}`,
    lists sorted, times as `YYYY-MM-DDTHH:MM:SSZ`, `since` null for −∞;
  - `PackageRows(rows: dict[str, list[dict]], counts: Counter, shipped: Shipped)`, `rows` keyed by `DIGEST_TABLES`;
    `package_rows(conn, sel, terms, ctx) -> PackageRows`;
  - `plan_digest(scope: dict, rows: Mapping[str, list[dict]]) -> str`: SHA-256 of
    `canonical({"filter": FILTER, "scope": scope, "rows": {t: sorted(row keys, key=canonical)}})`;
  - `contents_of(rows) -> dict[str, int]`: the tables with at least one row, and their counts.

- [ ] **Step 1: Write the failing tests**

```python
def test_canonical_is_the_peers_form_and_refuses_floats():
    assert canonical({"b": [1, "é", None, True], "a": {"z": 0}}) == '{"a":{"z":0},"b":[1,"é",null,true]}'.encode()
    for bad in ({"x": 1.5}, {"x": float("nan")}):
        with pytest.raises(ValueError):
            canonical(bad)

def test_the_digest_input_has_exactly_the_ten_tables_sorted_by_canonical_bytes():
    rows = {t: [] for t in DIGEST_TABLES} | {"semantic_sources": [{"semantic_id": "s2", "episode_id": "e1"},
                                                                 {"semantic_id": "s1", "episode_id": "e9"}]}
    expected = hashlib.sha256(canonical({"filter": "imprint-filter-v1", "scope": SCOPE, "rows": {
        t: ([["s1", "e9"], ["s2", "e1"]] if t == "semantic_sources" else []) for t in DIGEST_TABLES}})).hexdigest()
    assert plan_digest(SCOPE, rows) == expected

def test_measured_numbers_are_not_keys_but_content_is(tmp_path):
    s = digest_store(tmp_path)
    before = plan_digest(SCOPE, package_rows(s.conn, selection(), terms(), ctx(s)).rows)
    s.conn.execute("UPDATE episodes SET accessed_count = accessed_count + 7, last_accessed = '2026-10-25T17:00:00+00:00'")
    s.conn.execute("UPDATE resonances SET co_occurrences = co_occurrences + 1")
    assert plan_digest(SCOPE, package_rows(s.conn, selection(), terms(), ctx(s)).rows) == before
    s.conn.execute("UPDATE episodes SET content = content || '!' WHERE id = 'e1'")
    assert plan_digest(SCOPE, package_rows(s.conn, selection(), terms(), ctx(s)).rows) != before

def test_contents_names_only_non_empty_tables(tmp_path):
    rows = package_rows(digest_store(tmp_path).conn, selection(), terms(route=False), ctx_of(tmp_path)).rows
    assert set(contents_of(rows)) <= set(DIGEST_TABLES) and "memory_log" not in contents_of(rows)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_digest.py`
Expected: FAIL, `ImportError: cannot import name 'canonical' from 'imprint_filter'`.

- [ ] **Step 3: Implement the digest**

`canonical` is `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
.encode()` after a walk that refuses `float`. Row keys follow I 5.4's table: `sha256_value` of TEXT as UTF-8 bytes
and of BLOB as bytes, `created_at` as stored, `target_ids` as a list, `context` as an object, `peer_ids` as a sorted
list. `package_rows` assembles Tasks 9 to 11 in one pass over one connection.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 4 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint_filter.py engram/tests/test_imprint_digest.py
git commit -m "Imprints: the package's rows and the plan digest over canonical row keys (I 5.4, D22)"
```

### Task 13: The package writer

**Files:**
- Create: `engram/imprint.py`
- Modify: `engram/pyproject.toml` (`py-modules` gains `"imprint"`)
- Test: `engram/tests/test_imprint_build.py`

**Interfaces:**
- Consumes: Task 1's `stamp_imprint`; Task 6's `check_package_tables`; Task 12's `PackageRows`.
- Produces: `write_package(rows: PackageRows, dest: Path, *, source_id: str, source_ancestry: list[str],
  source_complete: bool, imprint_id: str) -> None`, I 6.1 steps 4 to 7: `Storage(dest)` (every migration), then
  `stamp_imprint` on its connection; with foreign keys off, inserts table by table with explicit column lists that
  never name `rowid`, memories in `(created_at, id)` order and vectors in their memories' order, vectors as the
  source's raw `embedding` bytes; then `foreign_key_check` empty, `integrity_check` `ok`, `journal_mode=DELETE`,
  `VACUUM`, `freelist_count` 0; then `check_package_tables`. It refuses to write over an existing file.

- [ ] **Step 1: Write the failing tests**

```python
def test_insertion_only(tmp_path):
    path = written(tmp_path)                 # a package from a source whose rowids have gaps and odd order
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA freelist_count").fetchone()[0] == 0 and conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert path.read_bytes()[18:20] == b"\x01\x01"

def test_rowids_run_one_to_n(tmp_path):
    conn = sqlite3.connect(written(tmp_path))
    for table in ("episodes", "semantics", "episode_fts_docsize", "semantic_fts_docsize"):
        ids = [r[0] for r in conn.execute(f"SELECT rowid FROM {table} ORDER BY rowid")]
        assert ids == list(range(1, len(ids) + 1)), table

def test_vectors_are_copied_bit_for_bit(tmp_path):
    src, path = written_with_source(tmp_path)
    for layer in ("episode", "semantic"):
        assert vectors_of(path, layer) == vectors_of(src, layer, only=shipped_ids(path, layer))

def test_the_package_is_an_imprint_of_its_source(tmp_path):
    src, path = written_with_source(tmp_path, source="fork")
    meta = dict(sqlite3.connect(path).execute("SELECT key, value FROM meta"))
    assert meta["instance_id_origin"] == "imprint" and meta["forked_from_instance_id"] == iid(src)
    assert json.loads(meta["ancestry"]) == [iid(src)] + ancestry(src.conn)[0] and uuid.UUID(meta["instance_id"]).version == 4
    assert set(meta) == set(store_identity.KEYS) - {"instance_id_basis_episode"}

def test_a_source_older_than_identity_names_its_derived_id(tmp_path):
    src, path = written_with_source(tmp_path, source="before_identity")   # episodes, no stored instance_id
    derived = store_identity.effective_id(src.conn)                       # the id its migration would assign
    meta = dict(sqlite3.connect(path).execute("SELECT key, value FROM meta"))
    assert meta["forked_from_instance_id"] == derived and stored_instance_id(src) is None
    assert (json.loads(meta["ancestry"]), meta["ancestry_complete"]) == ([derived], "false")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_build.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'imprint'`.

- [ ] **Step 3: Implement `write_package` in `engram/imprint.py`**

The FTS triggers fill `episode_fts` and `semantic_fts`; vec0 fills its own shadow tables. `meta` holds only the
identity keys `stamp_imprint` writes. Add `"imprint"` to `py-modules`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint.py engram/pyproject.toml engram/tests/imprint_support.py engram/tests/test_imprint_build.py
git commit -m "Imprints: write a package by insertion into a fresh, vacuumed file (I 6.1, D3, D33)"
```

### Task 14: The leak checks L1 to L4

**Files:**
- Create: `engram/imprint_checks.py`
- Modify: `engram/pyproject.toml` (`py-modules` gains `"imprint_checks"`)
- Test: `engram/tests/test_imprint_leaks.py`

**Interfaces:**
- Consumes: Task 13's packages.
- Produces (each returns a list of failure lines; empty is a pass; none names a value, only the table, the column or
  the slot):
  - `UUID_TOKEN` (I 6.4's pattern, case ignored);
  - `l1_values(conn, x_star: frozenset[str]) -> list[str]`: every value of every ordinary table, TEXT and BLOB (as
    Latin-1), scanned for UUID tokens in `x_star`;
  - `l2_fts(conn, scratch: Path) -> list[str]`: per FTS5 table, a scratch FTS5 table with the same columns and
    options but no `content=`, filled in rowid order from the base table; `fts5vocab` `instance` rows of both,
    streamed and compared; `_docsize` ids equal the base's rowids;
  - `l3_vec0(conn, expected: Mapping[str, Mapping[str, str]] | None) -> list[str]`: I 6.4's slot layout for
    sqlite-vec 0.1.7 (`_rowids`, `_chunks` validity bits and rowids, `_vector_chunks00`); `expected` maps each vec0
    table to `{id: SHA-256 hex of the embedding bytes}`, one form on both machines (at the build, hashed from the
    source's bytes; on the Pi, the plan digest's vector keys, which are those hashes, I 5.4), and L3 compares
    `sha256(slot bytes)` with it;
  - `l4_raw(path: Path, x_star) -> list[str]`: 1 MiB chunks overlapping by 35 bytes.

- [ ] **Step 1: Write the failing tests**

```python
def test_l2_fails_an_index_entry_with_no_content_row_that_integrity_check_passes(tmp_path):
    conn = writable_copy(written(tmp_path))
    plant_index_only_term(conn, "episode_fts", rowid=999, term="orphan")
    assert conn.execute("INSERT INTO episode_fts(episode_fts) VALUES('integrity-check')") is not None   # passes
    assert l2_fts(conn, tmp_path / "scratch") != []

def test_l3_fails_a_non_zero_invalid_slot_and_an_unknown_id(tmp_path):
    a, b = writable_copy(written(tmp_path)), writable_copy(written(tmp_path, name="b"))
    poke_invalid_slot(a, "episode_vectors", byte=0x7F)
    rename_rowids_id(b, "episode_vectors", to=str(uuid.uuid4()))
    assert l3_vec0(a, None) != [] and l3_vec0(b, None) != []

def test_l1_finds_a_uuid_split_across_an_overflow_page(tmp_path):
    left_out = str(uuid.uuid4())
    conn = writable_copy(written(tmp_path))
    put_value_across_page_boundary(conn, "episodes", "content", left_out)
    assert l1_values(conn, frozenset({left_out})) != []

def test_a_clean_package_passes_all_four(tmp_path):
    path, x_star, expected = written_with_x_star(tmp_path)
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True); load_vec(conn)
    assert l1_values(conn, x_star) == l2_fts(conn, tmp_path / "s") == l3_vec0(conn, expected) == l4_raw(path, x_star) == []

def test_rf3_honest_unicode_package_passes_every_leak_check(tmp_path):
    texts = ["Jenn drove me to the clinic 🚗", "café naïve façade", "東京で会議", "x" * 5000, "ﬁ ligature and ß"]
    path, x_star, expected = written_with_x_star(tmp_path, contents=texts)
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True); load_vec(conn)
    assert l1_values(conn, x_star) == l2_fts(conn, tmp_path / "s") == l3_vec0(conn, expected) == l4_raw(path, x_star) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_leaks.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'imprint_checks'`.

- [ ] **Step 3: Implement L1 to L4 in `engram/imprint_checks.py`**

L2 reads each FTS table's DDL from `sqlite_master`, drops only its `content=` and `content_rowid=` options, and keeps
the tokenizer options, so honest Unicode text indexes the same way on both sides (RF3). L3's `V_info` comparison is
check 7's job; here it reads the layout only. Add `"imprint_checks"` to `py-modules`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint_checks.py engram/pyproject.toml engram/tests/imprint_support.py engram/tests/test_imprint_leaks.py
git commit -m "Imprints: leak checks L1 to L4 on values, FTS vocabularies, vec0 slots and raw bytes (I 6.4, D34)"
```

### Task 15: `imprint.py plan` and the dry run

**Files:**
- Modify: `engram/imprint.py`
- Modify: `engram/imprint_filter.py` (`TIMES_WORDS`, `WITHOUT_ROUTE_WORDS`)
- Test: `engram/tests/test_imprint_plan.py`

**Interfaces:**
- Consumes: Tasks 7 to 13; `calibrate.snapshot`; `config.resolve_db_path`; `store_identity.effective_id`,
  `describe`, `ancestry`.
- Produces:
  - `Context(station: str, ship: str, owner: str, operator: str, station_peer_id: str)`; `read_context(home: Path) ->
    Context` (R7; missing file: `PlanRefused("No station context. Run make imprint-plan again; it asks the station
    first.")`). `parse_terms` gets `operator=context.operator`, so `--audience` must name `place:home/<operator>`, and
    the dry run's audience line reads "the station's imprint agent, acting for <operator>" from the station's answer,
    not from the owner's flag;
  - `resolve_store(store: Path | None, *, engram_home: Path, project_root: Path) -> Path` (I 5.1); `project_root` is
    `--project-root`, else `$ENGRAM_PROJECT_ROOT` (as `server.py:163` reads it), else the current directory;
  - `Plan` (frozen): `id`, `created`, `store`, `source_id`, `source_identity` (`present` or `derived`), `ancestry`,
    `ancestry_complete`, `selection`, `terms`, `digest`, `counts`, `contents`, `package_bytes`, `parts`;
  - `make_plan(store: Path, sel, terms, ctx, context: Context, *, home: Path, now: int) -> Plan`: a snapshot and a
    working copy in a 0700 directory under `home/imprints/plans/` (removed when it ends); `package_rows` on the
    working copy; the size from a scratch `write_package`; the plan written to `home/imprints/plans/<plan id>.json`
    (0600: selection, X, terms, digest);
  - `render_dry_run(plan, context) -> str`: I 5.4's text, with YS1's words (`TIMES_WORDS`), the ancestry line, the
    "Other people" paragraph and the permission in words;
  - `main(argv) -> int` with `plan` and its flags: `--store`, `--project-root`, `--lanes`, `--layers`, `--since`, `--until`,
    `--shared-with`, `--exclude FILE`, `--include-unsourced-semantics`, `--audience`, `--actions`, `--purposes`,
    `--days`, `--show-cross-references` (Task 17), `--list FILE`, `--json`, `--superyak-home`, `--engram-home`.
  - `TIMES_WORDS`, in `imprint_filter.py`, reads: "With them, route or not: when each memory was written; how often
    and when last each episode was recalled; and the resonances, pairs of memories recalls returned together, with
    when they formed and when either was last recalled. These show when memories were recalled together." Its
    builder's note: `last_accessed` also moves when an episode leaves core (`engram/storage.py:987-1012`), so "when
    last it was recalled" is nearly, not exactly, true (YS1).

- [ ] **Step 1: Write the failing tests**

```python
def test_plan_never_writes_the_source(tmp_path):
    src = live_source(tmp_path)                      # a WAL store; a second connection writes during the plan
    before = sha(src.db_path)
    plan = make_plan(Path(src.db_path), selection(), terms(), ctx(src), CONTEXT, home=tmp_path / "home", now=NOW)
    assert writer_wrote_during(plan) and source_unchanged_but_for_the_writer(src, before)
    assert list((tmp_path / "home" / "imprints" / "plans").glob("*/")) == []          # scratch removed

def test_plan_file_is_private_and_never_holds_content(tmp_path):
    plan = make_plan(*plan_args(tmp_path))
    path = tmp_path / "home" / "imprints" / "plans" / f"{plan.id}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and "Jenn drove" not in path.read_text()

def test_the_dry_run_says_what_leaves_and_what_stays(tmp_path):
    text = render_dry_run(make_plan(*plan_args(tmp_path, route=True)), CONTEXT)
    for line in ("Imprint plan", "(nothing has left this machine)", "Store id", "lineage complete",
                 "as ship voyager (owner sam)", "Session ids",
                 "sent only because you chose route", TIMES_WORDS.split(";")[0], "when either was last recalled",
                 "What stays here", "Other people:", "Plan digest", "make imprint-send PLAN="):
        assert line in text, line
    assert "Without route" in render_dry_run(make_plan(*plan_args(tmp_path / "b", route=False)), CONTEXT)

def test_list_writes_one_line_per_row_that_would_leave(tmp_path):
    rc = main(["plan", *PLAN_FLAGS, "--list", str(tmp_path / "rows.jsonl"), "--superyak-home", str(tmp_path / "h")])
    lines = [json.loads(l) for l in (tmp_path / "rows.jsonl").read_text().splitlines()]
    assert rc == 0 and {l["table"] for l in lines} <= set(DIGEST_TABLES) and all(set(l) == {"table", "key"} for l in lines)

def test_until_is_always_written(tmp_path):
    plan = make_plan(*plan_args(tmp_path, until=None))
    assert plan.selection.until == NOW and scope_of(plan.selection)["until"] == "2026-10-25T18:00:00Z"

def test_a_plan_naming_another_home_is_refused_before_anything_is_written(tmp_path):
    home = tmp_path / "h"; write_context(home, CONTEXT)                 # the station said: operator andy
    assert main(["plan", *PLAN_FLAGS, "--audience", "place:home/jenn", "--superyak-home", str(home)]) != 0
    assert not list((home / "imprints" / "plans").glob("*.json"))
    assert "acting for andy" in render_dry_run(make_plan(*plan_args(tmp_path / "ok")), CONTEXT)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_plan.py`
Expected: FAIL, `ImportError: cannot import name 'make_plan' from 'imprint'`.

- [ ] **Step 3: Implement the plan command**

The working copy is migrated with `Storage(working, imprint_working_copy=False)` only when migrations are pending;
the source is read only through `calibrate.snapshot`. `check_source` (Task 8) runs on the snapshot, with the source's
own resolved path and the imprints roots `~/.engram/imprints` and the `--imprints-dir` defaults. The context's owner
is the plan's owner (D37, I 5.3), and its operator is the only home the audience may name. The dry run prints the
resolved store path always (I 5.1).

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint.py engram/imprint_filter.py engram/tests/imprint_support.py engram/tests/test_imprint_plan.py
git commit -m "Imprints: imprint.py plan, its private plan file and the dry run in words (I 5.4)"
```

### Task 16: `imprint.py read`

**Files:**
- Modify: `engram/imprint.py`
- Test: `engram/tests/test_imprint_plan.py`

**Interfaces:**
- Consumes: Task 15; `store_reader.read_episodes`.
- Produces: `read_plan(plan_id: str, *, home: Path, start: int = 0, limit: int = 1) -> list[dict]`: a new snapshot,
  `PlanRefused("Your store changed since the plan. Run the plan again.")` when the digest differs, then every memory
  that would leave in `(created_at, id)` order, episodes as `read_episodes` reads them and then as the package will
  hold them (`session_id` null where the package holds null), semantics by `imprint.py`'s own reader in the same order;
  `resolve_plan(home, prefix) -> Path` (R6); the `read` subcommand with `--plan`, `--start`, `--limit`.

- [ ] **Step 1: Write the failing tests**

```python
def test_read_pages_through_what_would_leave(tmp_path):
    plan = make_plan(*plan_args(tmp_path, route=False))
    first, rest = read_plan(plan.id[:4], home=HOME(tmp_path)), read_plan(plan.id, home=HOME(tmp_path), start=1, limit=99)
    seen = first + rest
    assert [m["id"] for m in seen] == expected_order(plan) and all(m.get("session_id") is None for m in seen if m["layer"] == "episode")

def test_read_refuses_when_the_store_changed(tmp_path):
    plan = make_plan(*plan_args(tmp_path))
    edit_source(tmp_path, "e1", content="changed")
    with pytest.raises(PlanRefused, match="changed since the plan"):
        read_plan(plan.id, home=HOME(tmp_path))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_plan.py`
Expected: FAIL, `ImportError: cannot import name 'read_plan' from 'imprint'`.

- [ ] **Step 3: Implement `read_plan`**

It recomputes `package_rows` on a fresh snapshot and compares digests before showing anything.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint.py engram/tests/test_imprint_plan.py
git commit -m "Imprints: imprint.py read pages through what would leave (I 5.4)"
```

### Task 17: Cross-references

**Files:**
- Modify: `engram/imprint_filter.py`, `engram/imprint.py` (`--show-cross-references`; the dry run's count)
- Test: `engram/tests/test_imprint_crossrefs.py`

**Interfaces:**
- Consumes: Tasks 12, 15.
- Produces:
  - `left_out_keys(source_conn, cold_conn: sqlite3.Connection | None, rows: PackageRows) -> frozenset[str]`: X*, every
    single-column TEXT primary key (and every vec0 `id`) of a row of `graph.db` or `cold.db` that does not ship, lower
    case, minus the session ids that kept columns of shipped rows hold;
  - `CrossRef(table: str, id: str, keys: int)`; `cross_references(rows: PackageRows, x_star) -> list[CrossRef]`: a
    shipped memory whose text holds a UUID token in X*;
  - the plan prints the count and, with `--show-cross-references`, each memory's id and the table of the key it names,
    never the key itself.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("kind", ["episode", "instinct", "residue", "assessment", "drift_report", "memory_log"])
def test_text_naming_any_left_out_key_is_a_cross_reference_ignoring_case(tmp_path, kind):
    s, key = store_with_left_out(tmp_path, kind)
    ep(s, "names-it", content=f"see {key.upper()} for the rest")
    rows = package_rows(s.conn, selection(exclude=excluded(kind, key)), terms(), ctx(s))
    assert [c.id for c in cross_references(rows, left_out_keys(s.conn, None, rows))] == ["names-it"]

def test_a_shipped_session_id_in_a_kept_column_is_not_one_but_without_route_a_registered_session_is(tmp_path):
    s = session_text_store(tmp_path)        # e2's content names the closed session that wrote e1 and e2
    with_route = package_rows(s.conn, selection(), terms(route=True), ctx(s))
    without = package_rows(s.conn, selection(), terms(route=False), ctx(s))
    assert cross_references(with_route, left_out_keys(s.conn, None, with_route)) == []
    assert [c.id for c in cross_references(without, left_out_keys(s.conn, None, without))] == ["e2"]

def test_exclude_clears_them_and_no_flag_keeps_one(tmp_path):
    s, key = store_with_left_out(tmp_path, "episode"); ep(s, "names-it", content=key)
    rows = package_rows(s.conn, selection(exclude={"names-it", "left"}), terms(), ctx(s))
    assert cross_references(rows, left_out_keys(s.conn, None, rows)) == []
    assert not any("keep" in a and "cross" in a for a in plan_flags())

def test_cold_db_keys_count(tmp_path):
    s, cold = store_with_cold(tmp_path)     # e-cold pruned to cold.db; a kept episode names it
    rows = package_rows(s.conn, selection(), terms(), ctx(s))
    assert cross_references(rows, left_out_keys(s.conn, cold, rows))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_crossrefs.py`
Expected: FAIL, `ImportError: cannot import name 'left_out_keys' from 'imprint_filter'`.

- [ ] **Step 3: Implement X* and the scan**

Tables and their keys come from `PRAGMA table_info` (`pk = 1`, one column, type TEXT) over every table of both files.
`cold.db` is `<store dir>/cold.db` when it exists, opened with `store_reader.connect(..., immutable=True)`. The scan
reads the shipped rows' TEXT values with `UUID_TOKEN` (Task 14).

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 9 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint_filter.py engram/imprint.py engram/tests/imprint_support.py engram/tests/test_imprint_crossrefs.py
git commit -m "Imprints: cross-references to anything that stays home, ignoring case (I 6.4 item 1, D23)"
```

### Task 18: The request, the manifest and `objects.json`

**Files:**
- Modify: `engram/imprint.py`
- Test: `engram/tests/test_imprint_request.py`

**Interfaces:**
- Consumes: Tasks 12, 15.
- Produces:
  - `REQUEST_KEYS`, the exact key tree of I 7.1; `request_for(plan: Plan, imprint_id: str, package_bytes: int) -> dict`
    (`parts` = ⌈bytes / `PART_BYTES`⌉);
  - `manifest_for(request: dict, package: Path, *, built_at: int, engram_commit: str | None) -> dict` (I 7.2: canonical,
    no floats; `schema.applied` from the package; `embedding` from `embeddings.NomicEmbedProvider.MODEL_NAME` and the
    vec0 DDL's dimension; `vec.create_version` from `episode_vectors_info`; part hashes over 1 MiB reads);
  - `render_request(request: dict) -> str`: the request in words, the ancestry by short ids, and I 7.1's paragraph on
    what the station keeps and for how long, word for word;
  - `objects_for(rows: PackageRows, source_id: str) -> list[str]`: the sorted `mem:` refs, written as `objects.json`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_request_has_exactly_the_section_7_1_keys(tmp_path):
    req = request_for(make_plan(*plan_args(tmp_path, route=True)), IMPRINT_ID, package_bytes=43_188_224)
    assert key_tree(req) == REQUEST_KEYS and req["package"] == {"bytes": 43_188_224, "parts": 11}
    assert set(req["contents"]) <= set(DIGEST_TABLES) and all(v >= 1 for v in req["contents"].values())
    assert not set(req["contents"]) & {"meta", "schema_version", "episode_fts", "sqlite_sequence"}

def test_a_request_without_route_names_no_log_table(tmp_path):
    req = request_for(make_plan(*plan_args(tmp_path, route=False)), IMPRINT_ID, package_bytes=4_194_304)
    assert not {"memory_log", "operation_log"} & set(req["contents"]) and req["package"]["parts"] == 1

def test_the_manifest_agrees_with_the_request(tmp_path):
    req, pkg = request_and_package(tmp_path)
    man = manifest_for(req, pkg, built_at=NOW, engram_commit=None)
    for k in ("imprint_id", "plan_digest", "scope", "contents"):
        assert man[k] == req[k]
    assert man["request_sha256"] == hashlib.sha256(canonical(req)).hexdigest()
    assert len(man["package"]["parts"]) == req["package"]["parts"] and man["vec"] == {"create_version": "v0.1.7"}
    canonical(man)                                    # no float anywhere

def test_the_terminal_prints_the_request_and_what_the_station_keeps(tmp_path):
    text = render_request(request_for(make_plan(*plan_args(tmp_path, ancestry=["3f2a9c1e-5b7d-4c2a-9e1f-0a6b8c4d2e10"])), IMPRINT_ID, 1))
    assert "This goes to the station now, before you say yes." in text and "Nothing is kept with no end." in text
    assert "30 days" in text and "400 days" in text and "3f2a" in text and IMPRINT_ID[:4] in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_request.py`
Expected: FAIL, `ImportError: cannot import name 'request_for' from 'imprint'`.

- [ ] **Step 3: Implement the three documents**

`engram_commit` is `git rev-parse HEAD` in the engram checkout, or null when that fails. `source.identity` is
`present` or `derived` from `store_identity.describe`. Every count and byte value is an int.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 4 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint.py engram/tests/test_imprint_request.py
git commit -m "Imprints: the request, the manifest and objects.json (I 7.1, 7.2, D26)"
```

### Task 19: `imprint.py build`

**Files:**
- Modify: `engram/imprint.py`
- Test: `engram/tests/test_imprint_build.py`

**Interfaces:**
- Consumes: Tasks 13 to 18.
- Produces: `Built(imprint_id: str, dir: Path, request: dict, manifest: dict)`;
  `build(plan_id: str, *, home: Path, now: int, if_needed: bool = False) -> Built`: I 6.1 steps 1 to 10 (a new
  snapshot and working copy; digest compared; cross-references refused; `home/imprints/<imprint id>/` 0700 with a new
  lowercase uuid4; `write_package`; L1 to L4, with X* and the SHA-256s of the source's vectors; `request.json`, `manifest.json` and
  `objects.json`; `imprint.db` 0400; scratch removed; the plan file gains `imprint_id`). With `if_needed`, a plan
  already built returns its `Built` and prints nothing. The `build` subcommand prints `render_request`.
  `build` holds an exclusive `fcntl.flock(LOCK_EX | LOCK_NB)` on `home/imprints/plans/<plan id>.lock` from before it
  reads the plan file until it has written `imprint_id` there, so two builds of one plan never make two imprint ids
  (RF5); a held lock raises `PlanBusy(PlanRefused)`, which the subcommand prints as "Another make imprint-send of this
  plan is running." and exits 4.

- [ ] **Step 1: Write the failing tests**

```python
def test_build_refuses_when_a_memory_changed_since_the_plan(tmp_path):
    plan = make_plan(*plan_args(tmp_path)); edit_source(tmp_path, "e1", content="changed")
    with pytest.raises(PlanRefused, match="changed since the plan"):
        build(plan.id, home=HOME(tmp_path), now=NOW)

def test_a_recall_and_a_log_outcome_after_the_plan_change_nothing_but_a_late_outcome_on_a_kept_row_does(tmp_path):
    plan = make_plan(*plan_args(tmp_path, route=True))
    recall_now(tmp_path); log_outcome_now(tmp_path, on="a-row-that-stays")
    build(plan.id, home=HOME(tmp_path), now=NOW)                                   # same digest
    plan2 = make_plan(*plan_args(tmp_path / "2", route=True)); log_outcome_now(tmp_path / "2", on="a-kept-row")
    with pytest.raises(PlanRefused):
        build(plan2.id, home=HOME(tmp_path / "2"), now=NOW)

def test_plan_list_equals_the_package_rows(tmp_path):
    plan = make_plan(*plan_args(tmp_path, route=True)); built = build(plan.id, home=HOME(tmp_path), now=NOW)
    assert listed_rows(tmp_path) == rows_read_from(built.dir / "imprint.db")

def test_plan_digest_from_the_definitions(tmp_path):
    built = build(make_plan(*plan_args(tmp_path, route=True, every_table=True)).id, home=HOME(tmp_path), now=NOW)
    assert digest_written_from_section_5_4(built.dir / "imprint.db", built.request["scope"]) == built.request["plan_digest"]

def test_cross_references_stop_the_build_until_excluded(tmp_path):
    plan = make_plan(*plan_args(tmp_path, cross_ref=True))
    with pytest.raises(PlanRefused, match="names something staying here"):
        build(plan.id, home=HOME(tmp_path), now=NOW)
    built = build(make_plan(*plan_args(tmp_path, cross_ref=True, exclude={"names-it"})).id, home=HOME(tmp_path), now=NOW)
    assert all_leak_checks_pass(built)

def test_no_footpath_without_route(tmp_path):
    without = build(make_plan(*plan_args(tmp_path, store=footpath_store, route=False)).id, home=HOME(tmp_path), now=NOW)
    with_route = build(make_plan(*plan_args(tmp_path / "r", store=footpath_store, route=True)).id, home=HOME(tmp_path / "r"), now=NOW)
    assert section_4_sessions(without.dir / "imprint.db") == {} and empty(without, "memory_log", "operation_log")
    assert section_4_trails(with_route.dir / "imprint.db") == [["w1", "w2"]]
    assert session_of(with_route, "open-episode") is None

def test_the_files_on_the_source_machine(tmp_path):
    built = build(make_plan(*plan_args(tmp_path)).id, home=HOME(tmp_path), now=NOW)
    assert stat.S_IMODE((built.dir / "imprint.db").stat().st_mode) == 0o400 and stat.S_IMODE(built.dir.stat().st_mode) == 0o700
    assert json.loads((built.dir / "objects.json").read_text()) == sorted(json.loads((built.dir / "objects.json").read_text()))
    assert build(built_plan_id(tmp_path), home=HOME(tmp_path), now=NOW, if_needed=True).imprint_id == built.imprint_id

def test_rf5_a_second_build_of_one_plan_refuses(tmp_path):
    plan = make_plan(*plan_args(tmp_path))
    with held_lock(HOME(tmp_path) / "imprints" / "plans" / f"{plan.id}.lock"):          # the first run is building
        assert main(["build", "--plan", plan.id[:4], "--if-needed", "--superyak-home", str(HOME(tmp_path))]) == 4
    assert not [p for p in (HOME(tmp_path) / "imprints").iterdir() if p.is_dir() and p.name != "plans"]   # no imprint dir
    assert "imprint_id" not in plan_file(tmp_path, plan)
```

`section_4_sessions` and `section_4_trails` are a session reader written in the test from T 4 alone ("any distinct
non-null `episodes.session_id`"; wrote touches; two touches make a trail), importing nothing from this plan's code.
`digest_written_from_section_5_4` is the second implementation I 16 asks for, written from I 5.4 alone.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_build.py`
Expected: FAIL, `ImportError: cannot import name 'build' from 'imprint'`.

- [ ] **Step 3: Implement `build`**

Each step stops on failure and removes the half-made imprint directory, so a refused build leaves nothing behind.
The cross-reference refusal says how many memories, and "See them with --show-cross-references, then leave them out
with --exclude FILE and plan again."

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 13 passed (Task 13's 5 and these 8).

- [ ] **Step 5: Commit**

```bash
git add engram/imprint.py engram/tests/imprint_support.py engram/tests/test_imprint_build.py
git commit -m "Imprints: imprint.py build, refusing changes and cross-references, with every leak check (I 6.1)"
```

### Task 20: The canaries

**Files:**
- Test: `engram/tests/test_imprint_canaries.py`
- Modify: `engram/tests/imprint_support.py` (`canary_store`)

**Interfaces:**
- Consumes: Tasks 14, 19.
- Produces: `canary_store(tmp_path) -> tuple[Storage, list[str]]`: the anti-goal fixture of I 16, returning every
  planted canary.

- [ ] **Step 1: Write the test**

```python
def test_no_canary_survives_the_build(tmp_path):
    store, canaries = canary_store(tmp_path)
    # every TEXT column of every left-out row and dropped table; a query; an outcome note; cold.db, categories.db,
    # categories_v2.db, clipboard.db and notepad.db beside graph.db; terms sharing a 14-letter prefix with a shipped
    # term; left-out UUIDs that the tokenizer splits at hyphens; UUIDs in long values across an overflow page boundary;
    # a unique 3,072-byte vector in every left-out vector row
    built = build(make_plan(*plan_args(tmp_path, store=lambda _: store, route=True)).id, home=HOME(tmp_path), now=NOW)
    conn = open_package(built.dir / "imprint.db")
    raw = (built.dir / "imprint.db").read_bytes()
    for c in canaries:
        assert not any_value_contains(conn, c), c
        assert not fts_vocab_contains(conn, c), c
        assert c.encode() not in raw and c.encode("latin-1", "ignore") not in raw, c
    assert not any_vec0_slot_equals(conn, planted_vectors(store))
```

- [ ] **Step 2: Run the test**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_canaries.py`
Expected: PASS, 1 passed. (Tasks 13 to 19 are built test first; this is I 16's anti-goal test over all of them. If it
fails, the defect is in the task whose rule let the canary through, and that task is reopened.)

- [ ] **Step 3: Commit**

```bash
git add engram/tests/imprint_support.py engram/tests/test_imprint_canaries.py
git commit -m "Imprints: the canary test over every left-out row, file and index (I 16, anti-goal Leakage)"
```

### Task 21: Recall-row touches agree with the source's

**Files:**
- Test: `engram/tests/test_imprint_touches.py`
- Modify: `engram/tests/imprint_support.py` (`mixed_lane_recall_store`, `touches_from`)

**Interfaces:**
- Consumes: Task 19.
- Produces: `touches_from(path: Path, as_of: int) -> list[Touch]`, a reader written in the test from T 4 alone
  (sessions, wrote and cited touches, the "exactly one target" rule, suggested touches), importing nothing from
  `imprint*.py` or `trails.py`; `Touch(session, memory, kind, time, rank, recall_id, suggested)`.

- [ ] **Step 1: Write the test**

```python
@pytest.mark.parametrize("fixture", ["nothing_at_or_after_t1", "as_of_t1_nothing_at_t1"])
def test_every_package_touch_is_a_source_touch(tmp_path, fixture):
    store, t1 = mixed_lane_recall_store(tmp_path, fixture)   # route; a mixed-lane recall; a used recall of one target
    built = build(make_plan(*plan_args(tmp_path, store=lambda _: store, route=True, until=t1)).id,
                  home=HOME(tmp_path), now=t1)
    as_of = t1 if fixture == "as_of_t1_nothing_at_t1" else t1 + 7200
    pkg, src = touches_from(built.dir / "imprint.db", as_of), touches_from(Path(store.db_path), as_of)
    for t in pkg:
        twin = [s for s in src if (s.session, s.memory, s.kind, s.time) == (t.session, t.memory, t.kind, t.time)]
        assert twin and (not t.suggested or twin[0].suggested)
    assert order_within_recalls(pkg) == order_within_recalls(src, only=recalls_of(pkg))
    assert exactly_one_target_answers(built.dir / "imprint.db") == exactly_one_target_answers(Path(store.db_path),
                                                                                             only=kept_recalls(built))
```

The package's trails are not asserted to equal the source's restricted to M (I 16; T 7, "The cost, chosen for
privacy"). T 12's synthetic-imprint test measures what an imprint loses.

- [ ] **Step 2: Run the test**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_touches.py`
Expected: PASS, 2 passed. (Each fixture follows XS1: its source holds no row at or after t₁ with `as_of` after t₁, or
the test takes `as_of` = t₁ and the source holds no row at exactly t₁.)

- [ ] **Step 3: Commit**

```bash
git add engram/tests/imprint_support.py engram/tests/test_imprint_touches.py
git commit -m "Imprints: every touch an imprint gives is one its source gives (I 16, T's I6, XS1)"
```

### Task 22: The station's two record kinds

**Files:**
- Modify: `peer/superyak_peer/identity.py` (`RECORD_KEYS` at `:76-83`; a verifier after `verify_record`, `:189-200`)
- Modify: `peer/pyproject.toml` (the sdist list gains `tests/test_imprint_records.py`)
- Test: `peer/tests/test_imprint_records.py`

**Interfaces:**
- Produces:
  - `RECORD_KEYS["imprint-permission"] = frozenset({"kind", "station", "id", "owner", "owner_id", "ship_id",
    "imprint_id", "source_instance_id", "request_sha256", "plan_digest", "attestation", "created", "records"})`;
  - `RECORD_KEYS["imprint-receipt"] = frozenset({"kind", "station", "id", "permission", "event", "actor_id", "at",
    "detail", "previous"})`;
  - `INNER_RECORD_KEYS = frozenset({"id", "layer", "effect", "selector", "valid_from", "valid_until", "anchor",
    "backing", "set_by", "channel", "under_grant", "proposal_id", "replaces", "reason", "created"})` (P 5.1 less the
    five ledger-only fields);
  - `verify_station_record(public_key_b64: str, record: dict, signature: str) -> bool`: true only when SHA-256 of the
    key equals `record["station"]`, the shape is right (each `records` entry of a permission with exactly
    `INNER_RECORD_KEYS`) and the signature verifies over the canonical record; never raises.

- [ ] **Step 1: Write the failing tests**

```python
def test_both_kinds_sign_with_exactly_their_keys(tmp_path):
    ident = PeerIdentity.load_or_create(tmp_path / "id")
    perm, receipt = example_permission(ident.peer_id), example_receipt(ident.peer_id)   # I 8's and I 12's examples
    for record in (perm, receipt):
        assert verify_station_record(public_b64(ident), record, ident.sign_record(record))
        with pytest.raises(ValueError):
            ident.sign_record({**record, "extra": 1})

def test_verify_station_record_is_false_for_anything_else(tmp_path):
    ident, other = PeerIdentity.load_or_create(tmp_path / "a"), PeerIdentity.load_or_create(tmp_path / "b")
    perm = example_permission(ident.peer_id); sig = ident.sign_record(perm)
    inner_extra = {**perm, "records": [{**perm["records"][0], "revoked": None}]}
    for key, record, signature in [(public_b64(other), perm, sig), (public_b64(ident), {**perm, "station": other.peer_id}, sig),
                                   (public_b64(ident), {**perm, "kind": "imprint-receipt"}, sig),
                                   (public_b64(ident), inner_extra, sig), (public_b64(ident), perm, "not base64!"),
                                   ("!!", perm, sig), (public_b64(ident), ["not", "a", "dict"], sig)]:
        assert verify_station_record(key, record, signature) is False

def test_an_imprint_record_is_no_grant_and_no_envelope(tmp_path):
    ident = PeerIdentity.load_or_create(tmp_path / "id")
    perm = example_permission(ident.peer_id)
    assert not verify_record(ident.card("https://smart.example", {"id": "andy", "name": "Andy"}),
                             {**perm, "kind": "grant"}, ident.sign_record(perm))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_records.py`
Expected: FAIL, `ImportError: cannot import name 'verify_station_record' from 'superyak_peer.identity'`.

- [ ] **Step 3: Implement the kinds and the verifier**

`verify_station_record` decodes the key with `base64.b64decode(..., validate=True)`, compares `hashlib.sha256(key)
.hexdigest()` with `record["station"]` (`identity.py:94` makes the peer id this way), checks `_record_shape_ok` and,
for a permission, every inner record's keys, then verifies, all inside one `try` that returns False on anything.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 3 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/identity.py peer/pyproject.toml peer/tests/test_imprint_records.py
git commit -m "Peer: imprint-permission and imprint-receipt records, and verify_station_record (I 8, 15)"
```

### Task 23: Imprint tables, receipts and their chain

**Files:**
- Create: `peer/superyak_peer/imprints.py`
- Modify: `peer/superyak_peer/db.py` (the `Imprints` mixin in `Store`; `IMPRINT_SCHEMA` in the schema script)
- Modify: `peer/superyak_peer/signatures.py:14-19` (`SIGNED_RECORDS` gains the two imprint signatures; G4b)
- Modify: `peer/pyproject.toml` (both module lists gain `superyak_peer/imprints.py`; the sdist list gains the tests and `tests/imprint_support.py`)
- Create: `peer/tests/imprint_support.py`
- Test: `peer/tests/test_imprint_receipts.py`

**Interfaces:**
- Produces:
  - `IMPRINT_SCHEMA` (R2):
    ```sql
    CREATE TABLE IF NOT EXISTS imprint_requests(id TEXT PRIMARY KEY, imprint_id TEXT UNIQUE NOT NULL,
      ship_id TEXT NOT NULL REFERENCES users(id), owner_id TEXT NOT NULL REFERENCES users(id), status TEXT NOT NULL,
      code_hash TEXT, created INTEGER NOT NULL, expires INTEGER NOT NULL, decided_at INTEGER, decided_by TEXT,
      ended_at INTEGER, request_sha256 TEXT NOT NULL, source_instance_id TEXT NOT NULL, imprints_root TEXT,
      permission TEXT, permission_signature TEXT, station_key TEXT, delete_reason TEXT);
    CREATE TABLE IF NOT EXISTS imprint_receipts(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
      request_id TEXT NOT NULL REFERENCES imprint_requests(id), record TEXT NOT NULL, signature TEXT);
    ```
    `expires` is the end of the current window (code, upload or review). `source_instance_id` enforces D20. No
    column holds the scope, the counts or the terms;
  - `STATUSES`, `EVENTS`, `DELETE_REASONS`;
  - `DETAIL_KEYS: dict[str, tuple[frozenset[str], ...]]`, each event's allowed key sets, the one list every task
    writes and Task 45 reads (R25; I 12's receipts table, with `step` for a failure's step, `term` on `denied` and
    `failed`, and `limits` on `deleted`, which carries I 12's known-limits sentence). A detail's keys must equal one
    of its event's sets:
    - `received`: {`bytes`, `sha256`, `parts`, `manifest_sha256`};
    - `approved`, `withdrawn`, `ended`: {};
    - `denied`: {} (Andy's denial) or {`term`} (the decision refused at approval, Task 29);
    - `admitted`: {`checks`, `report_sha256`, `skipped`, `roads_and_trails`};
    - `failed`: {`step`, `message`} (admission ran and failed: a check number 1 to 17, `calibration` or `count`, R11)
      or {`term`} (the decision refused at a run's start, or the run ended during admission, Task 36);
    - `use-started`: U = {`use`, `use_id`, `actions`, `purpose`, `objects`};
    - `use-finished`: U ∪ {`end`}, with `report_sha256` added for `report`, `reason` for `deleted`, and `exit` or
      `error` for `failed`;
    - `refused`: {`use`, `actions`, `purpose`, `term`}, with `roads_and_trails` added once admitted;
    - `shortened`: {`valid_until`};
    - `deleted`: {`reason`, `files`, `limits`};
    - `delete-failed`: {`path`, `error`};
  - `SIGNED_RECORDS` (`signatures.py`) gains `('imprint_requests', "SELECT 1 FROM imprint_requests WHERE
    permission_signature IS NOT NULL LIMIT 1")` and `('imprint_receipts', "SELECT 1 FROM imprint_receipts WHERE
    signature IS NOT NULL LIMIT 1")`, so a lost `identity.json` is refused, not replaced by a new key that would void
    every pending receipt (G4b). The confirm loads the identity before it stores the signature, so the first imprint on
    a new station still creates the identity (G4);
  - `class Imprints` with `_append_imprint_receipt(db, request_id: str, event: str, actor_id: str | None,
    detail: dict, *, sign: bool) -> dict`: reads the last receipt of that permission inside the caller's
    transaction (`Store.transaction()` is `BEGIN IMMEDIATE`, `db.py:113`), sets `previous` to the SHA-256 of its
    canonical record or, for the first, of the permission record, inserts, and signs only when `sign`; refuses a
    `detail` key the event's row does not name; `imprint_receipts(request_id: str) -> list[dict]` (`{seq, record,
    signature}` in chain order);
  - `peer/tests/imprint_support.py`: `station(tmp_path) -> Station` (Task 24 adds `imprints_dir`) with `app`, `store`, `clock` (a one-item list),
    `root` (a test imprints root), `andy` (the super admin's client), `sam` (a person's client), `voyager` (sam's
    docked ship's client, through `test_presence.docked`), `jenn` and `other_ship`; `seed_imprint(st, *, status,
    route=False, owner="sam", **over) -> str` (a row and a signed permission, for tests that skip the routes);
    `only_signed_imprint_record(st, signed: str)` (a station whose only signed record is one imprint permission, or
    one receipt with the permission's signature cleared).

- [ ] **Step 1: Write the failing tests**

```python
def test_receipts_chain_from_the_permission(tmp_path):
    st = station(tmp_path); rid = seed_imprint(st, status="received")
    with st.store.transaction() as db:
        a = st.store._append_imprint_receipt(db, rid, "approved", st.andy_id, {}, sign=False)
        b = st.store._append_imprint_receipt(db, rid, "failed", None, {"step": 2, "message": "m"}, sign=False)
    assert a["previous"] == sha256_canonical(permission_of(st, rid)) and b["previous"] == sha256_canonical(a)
    assert [r["signature"] for r in st.store.imprint_receipts(rid)] == [None, None]

def test_two_processes_appending_at_once_keep_one_chain(tmp_path):
    st = station(tmp_path); rid = seed_imprint(st, status="admitted")
    run_in_two_processes(tmp_path / "peer", rid, each=40)    # Store(signing=False) in each, appending "refused"
    chain = st.store.imprint_receipts(rid)
    assert len(chain) == 80 and all(r2["record"]["previous"] == sha256_canonical(r1["record"]) for r1, r2 in zip(chain, chain[1:]))

def test_a_receipt_holds_no_detail_its_event_does_not_name(tmp_path):
    st = station(tmp_path); rid = seed_imprint(st, status="admitted")
    for event, bad in [("refused", {"content": "x"}), ("refused", {"query": "who"}), ("refused", {"memory_ids": ["e1"]}),
                       ("failed", {"check": 2, "message": "m"}), ("failed", {"step": 2, "term": "end"})]:
        with pytest.raises(ValueError), st.store.transaction() as db:
            st.store._append_imprint_receipt(db, rid, event, None, bad, sign=False)

def test_the_request_row_holds_no_scope_counts_or_terms(tmp_path):
    columns = table_columns(station(tmp_path).store, "imprint_requests")
    assert not columns & {"scope", "contents", "terms", "lanes", "layers", "since", "until", "episodes"}

@pytest.mark.parametrize("signed", ["permission", "receipt"])
def test_a_lost_identity_is_refused_while_an_imprint_record_is_signed(tmp_path, signed):
    st = station(tmp_path); only_signed_imprint_record(st, signed)    # no grant or revision signature on this station
    (st.store.data_dir / "identity.json").unlink()
    with pytest.raises(ValueError, match="identity.json.*station-new-identity"):
        Store(st.store.data_dir)                                     # as test_signatures.py's G4b test 4b does
    Store(st.store.data_dir, signing=False)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_receipts.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'superyak_peer.imprints'` (in `imprint_support`).

- [ ] **Step 3: Implement the tables and the chain**

Receipt ids are `uid()` (32 hex). `at` is `int(self.clock())`. The record's `station` is the permission record's
`station`, so a key-less store (`signing=False`, `__main__.py:322-327`) never loads the identity: every receipt
follows a permission (goal 6), and the confirm stores the station's public key in `station_key` (Task 25).

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/superyak_peer/db.py peer/superyak_peer/signatures.py peer/pyproject.toml peer/tests/imprint_support.py peer/tests/test_imprint_receipts.py
git commit -m "Peer: imprint tables and hash-chained receipts written in one transaction (I 12, D19)"
```

### Task 24: Requests and their checks

**Files:**
- Modify: `peer/superyak_peer/imprints.py` (`check_request`, `create_imprint_request`, `list_imprints` for a ship)
- Modify: `peer/superyak_peer/app.py` (`create_app(..., imprints_dir: Path | None = None)`; `POST /api/imprints`, `GET /api/imprints`)
- Modify: `peer/superyak_peer/__main__.py` (`serve --imprints-dir`, passed to `create_app`; R8)
- Modify: `peer/tests/imprint_support.py` (`station(tmp_path, imprints_dir=<the test root>)`; `None` turns the routes off)
- Test: `peer/tests/test_imprint_requests.py`

**Interfaces:**
- Consumes: Task 23.
- Produces:
  - `check_request(doc: dict, *, super_admin: str, owner_username: str) -> dict`: every rule of I 14 for `POST
    /api/imprints`, with R14 (`until` required); refusals are `Problem(400, <fixed message naming the field>)`;
  - `Imprints.create_imprint_request(ship_id: str, raw: bytes, *, staging: Path) -> dict` →
    `{"id", "code", "expires", "imprint_short", "request_short"}`: parses with `identity.parse`, checks, applies the
    disk, size, per-ship (4 open) and per-source (D20) limits, writes `$(STATION_DATA)/imprints/<request id>/request.json`
    (directory 0700, file 0600), and the row in status `requested` with `expires` = now + 600 and the code's hash
    (8 characters from `CODE_ALPHABET`, as `start_docking` makes it, `ships.py:133`);
  - the route answers `{id, code, confirm_url, expires}` with `confirm_url` = `<base>/#imprint?code=<code>`;
  - `GET /api/imprints` with a ship key: `{"ship", "owner", "operator", "station", "imprints": [...]}` (R7;
    `operator` is the super admin's username, the one `check_request` takes as `super_admin`); with a person's
    session: `{"imprints": [...]}`;
  - without `--imprints-dir`, no imprint route exists (404).

- [ ] **Step 1: Write the failing tests**

```python
def test_routes_take_the_ships_key_and_the_door_has_none(tmp_path):
    st = station(tmp_path)
    assert st.voyager.post("/api/imprints", content=canonical(request_doc())).status_code == 201
    assert st.sam.post("/api/imprints", content=canonical(request_doc())).status_code == 403
    door = TestClient(create_door(tmp_path / "door"), base_url="http://testserver")
    assert door.post("/api/imprints", content=b"{}").status_code == 404

def test_routes_are_off_without_imprints_dir(tmp_path):
    st = station(tmp_path, imprints_dir=None)
    assert st.voyager.post("/api/imprints", content=canonical(request_doc())).status_code == 404

@pytest.mark.parametrize("change", [
    {"imprint_id": "C0A8F5E2-0000-4000-8000-000000000000"}, {"imprint_id": "c0a8f5e2-0000-1000-8000-000000000000"},
    {"imprint_id": "../../etc"}, {"plan_digest": "9d3e"}, {"scope.until": "2026-10-25 18:00:00"},
    {"scope.until": None}, {"contents.episodes": 1.0}, {"contents.episodes": -1}, {"package.parts": 12},
    {"terms.audience": ["place:home/sam"]}, {"terms.days": 366}, {"contents.memory_log": 3, "terms.actions": ["imprint"]},
    {"contents.episodes": 99_999, "contents.semantics": 2}, {"extra": 1}, {"scope.lanes": ["work", "personal"]}])
def test_each_format_refuses_a_bad_value(tmp_path, change):
    st = station(tmp_path)
    assert st.voyager.post("/api/imprints", content=canonical(request_doc(**change))).status_code == 400

def test_a_duplicate_imprint_id_and_the_limits(tmp_path, monkeypatch):
    st = station(tmp_path); doc = request_doc()
    assert post(st, doc).status_code == 201 and post(st, doc).status_code == 409
    assert post(st, request_doc(source_instance_id=doc["source_instance_id"])).status_code == 409     # D20
    monkeypatch.setattr(imprints, "free_bytes", lambda path: 5 * 2**30)
    assert post(st, request_doc(**{"package.bytes": 2**30, "package.parts": 256})).status_code == 507
    assert post(st, request_doc(**{"package.bytes": 2**31 + 1})).status_code == 400
    assert [post(st, request_doc()).status_code for _ in range(4)][-1] == 429                       # 4 open per ship

def test_the_request_lives_in_staging_and_a_ship_sees_its_owner(tmp_path):
    st = station(tmp_path); made = post(st, request_doc()).json()
    staged = tmp_path / "peer" / "imprints" / made["id"] / "request.json"
    assert stat.S_IMODE(staged.stat().st_mode) == 0o600 and b'"scope"' not in (tmp_path / "peer" / "peer.sqlite3").read_bytes()
    context = st.voyager.get("/api/imprints").json()
    assert (context["owner"], context["operator"]) == ("sam", "andy")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_requests.py`
Expected: FAIL, `TypeError: create_app() got an unexpected keyword argument 'imprints_dir'`.

- [ ] **Step 3: Implement the request**

The route reads the raw body (`await request.body()`), refuses over 64 KiB with 413, and passes it on. The audience's
handle must be the super admin's username (`users.is_super_admin`), and the ship's owner's username must fit
`[a-z][a-z0-9-]{0,62}` (I 5.3). `free_bytes` is `shutil.disk_usage(...).free`; the floor is 4 GiB left after reserving
3 × `package.bytes`; live bytes across non-terminal rows stay within 16 GiB.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 19 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/superyak_peer/app.py peer/superyak_peer/__main__.py peer/pyproject.toml peer/tests/test_imprint_requests.py
git commit -m "Peer: imprint requests, every format and limit checked, kept in staging (I 7.1, 14, R8, R14)"
```

### Task 25: The confirm view, the confirm and the signed permission

**Files:**
- Modify: `peer/superyak_peer/imprints.py` (`imprint_preview`, `confirm_imprint`, `decline_imprint`, `permission_record`, `TIMES_WORDS`, `KEEPS_WORDS`, `CHECK_TEXT`, `STATION_NAME`)
- Modify: `peer/superyak_peer/auth.py:80-100` (`check_password_attempt`, R19; `login` calls it)
- Modify: `peer/superyak_peer/app.py` (`GET /api/imprints/code/{code}`, `POST /api/imprints/{id}/confirm`, `POST /api/imprints/{id}/decline`)
- Test: `peer/tests/test_imprint_confirm.py`

**Interfaces:**
- Consumes: Tasks 22 to 24.
- Produces:
  - `Auth.check_password_attempt(username: str, password: str, source: str) -> bool`;
  - `imprint_preview(actor: str, code: str) -> dict`: for the ship's owner only (anyone else, 404): the ship and
    machine; `imprint_short`, `request_short`; the store id with its ancestry by short ids and "lineage complete",
    "lineage incomplete" or "copied from no recorded store"; scope, counts and size; the audience in words; the closed
    actions in words, or the without-route words; `TIMES_WORDS` (YS1); the end date if confirmed now; the digest's
    first 8 characters and "the whole 64-character digest is sent"; `CHECK_TEXT`; `KEEPS_WORDS` (D32, I 9's
    words); the closing paragraph;
  - `confirm_imprint(actor: str, request_id: str, *, code: str, password: str, attest: bool, source: str) -> dict`:
    the owner, CSRF (through `current_user`), the password (`check_password_attempt`), the ticked check; in one
    transaction it builds `permission_record`, signs it, stores both and sets status `allowed`, `expires` = now + 7 days;
  - `decline_imprint(actor: str, request_id: str) -> dict`: removes the staging directory at once; status `declined`;
  - `permission_record(*, station: str, request_id: str, owner: str, owner_id: str, ship_id: str, request: dict,
    request_sha256: str, now: int) -> dict`: I 8's record, with r_M and, with `route`, r_T; ids `r-` + 32 random hex;
    `valid_until` = now + days × 86,400; every list sorted; `reason` = `f"imprint {imprint_id[:4]} at {STATION_NAME}"`;
  - `TIMES_WORDS = "Each memory keeps when it was written. Each episode keeps how often and when last it was recalled.
    Resonances, pairs of memories recalls returned together, keep when they formed and when either was last recalled.
    These show when memories were recalled together."` (YS1's correction of I 9's line).

- [ ] **Step 1: Write the failing tests**

```python
def test_only_the_ships_owner_sees_and_confirms(tmp_path):
    st = station(tmp_path); made = post(st, request_doc()).json()
    assert st.jenn.get(f"/api/imprints/code/{made['code']}").status_code == 404
    assert st.andy.get(f"/api/imprints/code/{made['code']}").status_code == 404
    assert confirm(st.jenn, made).status_code == 404 and confirm(st.sam, made).status_code == 200

def test_csrf_password_and_the_check_are_required(tmp_path):
    st = station(tmp_path); made = post(st, request_doc()).json()
    assert confirm(st.sam, made, csrf=False).status_code == 403
    assert confirm(st.sam, made, password="wrong").status_code == 401
    assert confirm(st.sam, made, attest=False).status_code == 400
    assert row(st, made["id"])["status"] == "requested"

def test_a_wrong_password_counts_toward_the_login_limits(tmp_path):
    st = station(tmp_path); made = post(st, request_doc()).json()
    for _ in range(8): confirm(st.sam, made, password="wrong")
    assert st.anonymous.post("/api/login", json={"username": "sam", "password": SAM_PASSWORD}).status_code == 429

def test_the_code_is_single_use_and_expires(tmp_path):
    st = station(tmp_path); made = post(st, request_doc()).json()
    assert confirm(st.sam, made).status_code == 200 and confirm(st.sam, made).status_code == 404
    late = post(st, request_doc()).json(); st.clock[0] += 601
    assert confirm(st.sam, late).status_code == 404

def test_the_permission_is_signed_in_the_confirming_transaction(tmp_path, monkeypatch):
    st = station(tmp_path); made = post(st, request_doc(route=True)).json()
    confirm(st.sam, made)
    stored = row(st, made["id"])
    record = json.loads(stored["permission"])
    assert verify_station_record(station_key(st), record, stored["permission_signature"])
    assert set(record) == RECORD_KEYS["imprint-permission"] and all(set(r) == INNER_RECORD_KEYS for r in record["records"])
    r_m, r_t = record["records"]
    assert r_m["selector"]["objects"]["collections"] == [f"collection:sam/imprint-{made_imprint_id(made)}"]
    assert (r_m["selector"]["objects"]["layers"], r_m["selector"]["objects"]["lanes"]) == ("*", "*")
    assert r_t["selector"]["objects"]["stores"] == [SOURCE_ID] and r_t["selector"]["purposes"] == ["trail-evaluation"]
    failing = post(st, request_doc()).json()
    monkeypatch.setattr(imprints, "permission_record", explode_after_sign)
    assert confirm(st.sam, failing).status_code == 500 and row(st, failing["id"])["permission"] is None

def test_records_pass_the_outside_home_write_rules_as_written_from_p_5_4(tmp_path):
    record = confirmed_permission(tmp_path, route=True)
    for r in record["records"]:
        assert outside_home_allow_ok(r)      # written in the test from P 5.4: finite purposes, valid_until ≤ 366 days
                                             # after valid_from, memories only by collection, roads and trails by a
                                             # finite stores list, sorted distinct lists, integer times (P13, P14, P28)

def test_the_view_shows_every_field_but_kind_and_version(tmp_path):
    st = station(tmp_path); doc = request_doc(route=True, ancestry=[ANCESTOR]); made = post(st, doc).json()
    view = json.dumps(st.sam.get(f"/api/imprints/code/{made['code']}").json())
    for shown in (doc["imprint_id"][:4], made["id"][:4], doc["plan_digest"][:8], "the whole 64-character digest is sent",
                  ANCESTOR[:4], "lineage complete", "1204", "41.2 MiB", "the station's imprint agent, acting for andy",
                  "when either was last recalled", CHECK_TEXT, "Nothing is kept with no end."):
        assert shown in view, shown
    assert doc["plan_digest"] not in view and "engram-imprint-request" not in view

def test_decline_removes_staging_at_once_and_keeps_a_content_free_row(tmp_path):
    st = station(tmp_path); made = post(st, request_doc()).json()
    assert st.sam.post(f"/api/imprints/{made['id']}/decline").status_code == 200
    assert not (tmp_path / "peer" / "imprints" / made["id"]).exists() and row(st, made["id"])["status"] == "declined"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_confirm.py`
Expected: FAIL, `assert 404 == 200` (no confirm route yet).

- [ ] **Step 3: Implement the confirm**

The code row is matched by hash, refused once used or past `expires`. The confirm's request body is `{code, password,
attest}`; a wrong password is 401 after `check_password_attempt` counts it, and too many give 429 as `/api/login` does.
The confirm also stores the station's public key, base64, in the row's `station_key`, so key-less commands can write
`permission.json` and receipts without loading the identity. `r_M`'s actions are `["imprint", "read", "recall"]` and its purposes `["calibration"]`, plus `"trail-evaluation"` with
`route`; `r_T`'s actions are `["imprint", "read", "recall", "route"]`. The signature comes from
`self._station_identity(db).sign_record(record)` inside the transaction, as grants are signed (`signatures.py:140-144`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/superyak_peer/auth.py peer/superyak_peer/app.py peer/pyproject.toml peer/tests/test_imprint_confirm.py
git commit -m "Peer: the owner's browser yes, with password and check, signs the imprint permission (I 8, D1, D27)"
```

### Task 26: The manifest, the parts and `complete`

**Files:**
- Modify: `peer/superyak_peer/imprints.py` (`check_manifest`, `put_imprint_manifest`, `put_imprint_part`, `complete_imprint`, `pending_imprints`)
- Modify: `peer/superyak_peer/app.py` (`PUT /api/imprints/{id}/manifest`, `PUT /api/imprints/{id}/parts/{n}`, `POST /api/imprints/{id}/complete`, `GET /api/imprints/{id}`)
- Modify: `peer/superyak_peer/ships.py:191-199` (`station_pending` lists `received` imprints), `:380-393` (`station_notices`)
- Modify: `peer/superyak_peer/__main__.py:49-64` (`describe_pending` prints the `IMPRINT` item)
- Test: `peer/tests/test_imprint_upload.py`

**Interfaces:**
- Consumes: Tasks 23 to 25.
- Produces:
  - `check_manifest(man: dict, request: dict) -> None` (I 7.2 and I 14's manifest formats; every shared field equal);
  - `put_imprint_manifest(ship_id, request_id, raw: bytes) -> dict` (once, only in `allowed`);
  - `put_imprint_part(ship_id, request_id, n: int, data: bytes) -> dict` → `{"held": [...]}`: only after the manifest,
    the right length, SHA-256 equal to `manifest.package.parts[n]`, written as `part-n.tmp`, fsynced, renamed; a part
    held with the same hash returns 200 and changes nothing; 120 per ship per minute;
  - `complete_imprint(ship_id, request_id) -> dict`: joins the parts in order into a temporary file, streaming,
    checks bytes and SHA-256, fsyncs, renames it to `imprint.db`, deletes the parts, sets `received` with `expires` =
    now + 7 days, and writes the signed `received` receipt (bytes, SHA-256 and parts; `manifest_sha256`);
  - `GET /api/imprints/{id}` for the owner or the requesting ship: `{"status", "held"}` (`held` the part numbers
    the station holds, so a send resumes after a restart); anyone else gets 404. Task 41 adds the rest of I 12's
    "What the owner sees afterwards" to this answer;
  - `station_pending()` gains `{"kind": "imprint", ...}` items read from `request.json`; `describe_pending` prints I
    10's two lines through `safe_line`; `station_notices()` gains "An imprint is waiting for Andy's review. He decides
    with make station-pending on the Pi." per received item, naming no one.

- [ ] **Step 1: Write the failing tests**

```python
def test_manifest_before_parts(tmp_path):
    st = station(tmp_path); made, data = requested_with_package(st)
    assert put_manifest(st, made, manifest_for_doc(made, data)).status_code == 409          # before allowed
    confirm(st.sam, made)
    assert put_part(st, made, 0, data[:PART_BYTES]).status_code == 409                       # before the manifest
    assert put_manifest(st, made, manifest_for_doc(made, data, plan_digest="0" * 64)).status_code == 400
    assert put_manifest(st, made, manifest_for_doc(made, data)).status_code == 200
    assert put_manifest(st, made, manifest_for_doc(made, data)).status_code == 409          # a second one

@pytest.mark.parametrize("field", ["scope", "contents", "imprint_id", "plan_digest", "request_sha256",
                                   "source.instance_id", "source.ancestry", "source.ancestry_complete",
                                   "package.bytes", "package.parts"])                    # I 7.2's shared fields
def test_a_manifest_that_differs_from_the_request_in_any_shared_field_is_refused(tmp_path, field):
    st = station(tmp_path); made, data = requested_with_package(st); confirm(st.sam, made)
    assert put_manifest(st, made, manifest_for_doc(made, data, differ=field)).status_code == 400
    assert put_manifest(st, made, manifest_for_doc(made, data)).status_code == 200          # nothing was kept

def test_another_ship_gets_404_on_every_upload_route(tmp_path):
    st, made, data = allowed_with_manifest(tmp_path, nbytes=PART_BYTES)
    rid, other = made["id"], st.other_ship
    assert other.put(f"/api/imprints/{rid}/manifest", content=canonical(manifest_for_doc(made, data))).status_code == 404
    assert other.put(f"/api/imprints/{rid}/parts/0", content=data).status_code == 404
    assert other.post(f"/api/imprints/{rid}/complete").status_code == 404
    assert other.get(f"/api/imprints/{rid}").status_code == 404 and st.jenn.get(f"/api/imprints/{rid}").status_code == 404
    assert st.voyager.get(f"/api/imprints/{rid}").json()["held"] == []

def test_parts(tmp_path):
    st, made, data = allowed_with_manifest(tmp_path, nbytes=2 * PART_BYTES)                  # an exact multiple: 2 parts
    assert put_part(st, made, 0, data[:-1][:PART_BYTES - 1]).status_code == 400              # wrong length
    assert put_part(st, made, 1, data[:PART_BYTES]).status_code == 400                       # wrong hash
    assert put_part(st, made, 0, data[:PART_BYTES]).status_code == 200
    before = part_files(tmp_path, made)
    assert put_part(st, made, 0, data[:PART_BYTES]).status_code == 200 and part_files(tmp_path, made) == before
    restarted = station_again(tmp_path)                                                      # a new Store on the same data
    assert restarted.voyager.get(f"/api/imprints/{made['id']}").json()["held"] == [0]
    assert st.voyager.put(f"/api/imprints/{made['id']}/parts/1", content=b"x" * (6 * 2**20 + 1)).status_code == 413

def test_complete(tmp_path):
    st, made, data = allowed_with_all_parts(tmp_path)
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").json()["status"] == "received"
    joined = tmp_path / "peer" / "imprints" / made["id"] / "imprint.db"
    assert joined.read_bytes() == data and not list(joined.parent.glob("part-*"))
    lines = describe_pending(st.store.station_pending(), st.clock[0], "andy")
    assert "IMPRINT  from sam (ship voyager, machine" in lines and "\n" not in safe_parts(lines)
    notice = [n for n in st.store.station_notices() if n["id"].startswith("imprint-")][0]
    assert notice["text"] == "An imprint is waiting for Andy's review. He decides with make station-pending on the Pi."

def test_rf2_failed_join_leaves_no_partial_file(tmp_path, monkeypatch):
    st, made, data = allowed_with_all_parts(tmp_path)
    monkeypatch.setattr(imprints, "_copy_part", fail_on_second_part(OSError(28, "No space left on device")))
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").status_code == 507
    staged = tmp_path / "peer" / "imprints" / made["id"]
    assert not (staged / "imprint.db").exists() and not list(staged.glob("*.tmp")) and len(list(staged.glob("part-*"))) == 2
    assert row(st, made["id"])["status"] == "allowed"
    monkeypatch.undo()
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").json()["status"] == "received"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_upload.py`
Expected: FAIL, `assert 405 == 409` (no manifest route yet).

- [ ] **Step 3: Implement the upload**

Only the requesting ship (`ship_member`) uses these routes; any other ship gets 404. Hashing reads 1 MiB at a time as
`store_reader.sha256_file` does. `_copy_part(src, dst)` streams one part into the open temporary file, so a failure
removes only the temporary file. An `OSError` with `errno.ENOSPC` maps to `Problem(507, "The station is out of disk
space; nothing was kept. Run make imprint-send again later.")`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 15 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/superyak_peer/app.py peer/superyak_peer/ships.py peer/superyak_peer/__main__.py peer/pyproject.toml peer/tests/test_imprint_upload.py
git commit -m "Peer: the manifest, resumable 4 MiB parts, the join, and the IMPRINT item (I 9, 10)"
```

### Task 27: The use decision and the per-copy ceiling

**Files:**
- Modify: `peer/superyak_peer/imprints.py` (pure functions)
- Create: `peer/tests/fixtures/imprints/ceiling_agreement.json` (and add it to `peer/pyproject.toml`'s sdist list)
- Test: `peer/tests/test_imprint_decide.py`

**Interfaces:**
- Consumes: Task 25's records.
- Produces:
  - `CEILING = frozenset({("recall", "calibration"), ("read", "calibration"), ("imprint", "calibration"),
    ("recall", "trail-evaluation"), ("read", "trail-evaluation"), ("imprint", "trail-evaluation"),
    ("route", "trail-evaluation")})` (I 8's C);
  - `need(kind: str, *, route: bool) -> frozenset[tuple[str, str, str]]` of `(object kind, action, purpose)`, object
    kind `memory` or `road-or-trail`: I 8's `Need(admission, t)` and `Need(trail-evaluation, t)`;
  - `effective_end(permission: dict, receipts: Sequence[dict]) -> int`: the earliest of the records' `valid_until` and
    every `shortened` receipt's, by the owner or the ship;
  - `owner_layer(imprints: Sequence[tuple[dict, list[dict]]], *, owner_id: str) -> list[dict]`: every inner record
    of the owner's imprints of one store, less those the owner withdrew, each `valid_until` cut by the owner's
    shortenings (the owner's layer at the station, I 8);
  - `UseDecision(allowed: bool, term: str | None, code: str | None, valid_until: int, records: tuple[str, ...])`;
  - `decide_use(permission: dict, receipts: Sequence[dict], owner_records: Sequence[dict], *, status: str, kind: str,
    t: int, operator: str, uses: Iterable[tuple[str, str, str]] | None = None) -> UseDecision`. Terms in I 8's order:
    status, `valid_from`, the effective end, withdrawal (any `withdrawn` receipt at or before t), then audience,
    requester, action and purpose (necessary conditions, read over `owner_records`), then the ceiling (items 1 to 5
    over this copy's own records and receipts, and C). The verdict is the ceiling's, so a use of copy I is allowed
    exactly when `Need ⊆ ⟦c_I⟧` (I 8, "Why the station's check is the permissions spec's meet"). Codes: `NOT_YET` for
    `valid_from`, `EXPIRED` for the end, `NO_ALLOW` for the rest. `uses` replaces `need(...)` in tests only.

- [ ] **Step 1: Write the fixture and the failing tests**

The fixture holds two owners, `sam` and `andy` (the operator, XM1), each with imprints; sam's copy 1 (with `route`,
withdrawn by the ship, so its records stay unrevoked) and copy 2 (without `route`, holding only memories copy 1 held)
of one store; a shortening by the ship and one by the owner; and a list of uses `{imprint, kind, t, expected,
expected_term}` that covers every term, Need(admission) with and without `route`, and Need(trail-evaluation).

```python
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "imprints" / "ceiling_agreement.json").read_text())

@pytest.mark.parametrize("case", FIXTURE["uses"], ids=lambda c: c["name"])
def test_the_station_check_gives_the_fixtures_answer(case):
    imp = FIXTURE["imprints"][case["imprint"]]
    d = decide_use(imp["permission"], imp["receipts"], owner_records_for(FIXTURE, imp), status=imp["status"],
                   kind=case["kind"], t=case["t"], operator=FIXTURE["operator"])
    assert (d.allowed, d.term) == (case["expected"], case["expected_term"])

def test_each_term_alone_refuses_with_that_term_in_order():
    for term, broken in one_fault_each():          # status, valid_from, end, withdrawal, audience, requester, action,
        d = decide_use(**broken)                   # purpose, ceiling (a pair outside C through `uses`)
        assert (d.allowed, d.term) == (False, term)
        assert d.code == {"valid_from": "NOT_YET", "end": "EXPIRED"}.get(term, "NO_ALLOW")

def test_one_ceiling_per_copy():
    copy1, copy2 = FIXTURE["imprints"]["sam-copy-1"], FIXTURE["imprints"]["sam-copy-2"]
    layer = owner_records_for(FIXTURE, copy2)                    # holds copy 1's unrevoked r_M and r_T
    d = decide_use(copy2["permission"], copy2["receipts"], layer, status="admitted", kind="trail-evaluation",
                   t=FIXTURE["now"], operator="andy")
    assert (d.allowed, d.term) == (False, "ceiling")
    after_end = effective_end(copy2["permission"], copy2["receipts"]) + 1     # copy 1's records still run past it
    late = decide_use(copy2["permission"], copy2["receipts"], layer, status="approved", kind="admission",
                      t=after_end, operator="andy")                       # admission's own status, so the end decides
    assert (late.allowed, late.term) == (False, "end")

def test_shortening_only_narrows():
    imp = FIXTURE["imprints"]["sam-c0a8"]
    for receipts in shortenings_of(imp):               # by the ship and by the owner, at several times
        assert effective_end(imp["permission"], receipts) <= effective_end(imp["permission"], imp["receipts"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_decide.py`
Expected: FAIL, `ImportError: cannot import name 'decide_use' from 'superyak_peer.imprints'`.

- [ ] **Step 3: Implement the decision**

A record speaks for a need `(object kind, action, purpose)` when its audience holds `place:home/<operator>`, its
requesters hold `agent:station-imprints`, its kinds hold the object kind (`memory`, or `road` and `trail`), its
stores hold the copy's source id, the action and purpose are listed, and `valid_from ≤ t < valid_until`. The ceiling
asks the same of this copy's own records, with `(action, purpose) ∈ CEILING`, t before the effective end and before
every `withdrawn` receipt. `records` names the ids of this copy's records that the decision used.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, every fixture case and 3 more.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/tests/fixtures/imprints/ceiling_agreement.json peer/pyproject.toml peer/tests/test_imprint_decide.py
git commit -m "Peer: the use decision, one ceiling per copy, and its fixture (I 8, D28, D38)"
```

### Task 28: The station's check is the permissions spec's meet

**Files:**
- Test: `engram/tests/test_imprint_ceiling.py`
- Modify: `engram/tests/imprint_support.py` (`ceiling_world`)

**Interfaces:**
- Consumes: Task 27's fixture; the permissions plan's `permissions.decide_bulk`, `BulkUse` and
  `tests/permissions_support.World`.
- Produces: `ceiling_world(fixture: dict) -> tuple[State, Callable]`: P 5.5's tables built with `World` from the
  fixture (persons `sam` and `andy`; their homes; `agent:station-imprints` acting for andy in `place:home/andy`; each
  source store with its owner; each imprint's collection and its members; every inner record in its owner's home
  layer), and the ceiling ⟦c⟧ written in the test from I 8's items 1 to 5, passed to `decide_bulk` as the layer kept
  outside a ledger for `place:home/andy` (P 6.1; XM1).

- [ ] **Step 1: Write the test**

```python
FIXTURE = json.loads((REPO / "peer" / "tests" / "fixtures" / "imprints" / "ceiling_agreement.json").read_text())

@pytest.mark.parametrize("case", FIXTURE["uses"], ids=lambda c: c["name"])
def test_p_meet_over_req_gives_the_fixtures_answer(case):
    state, ceiling = ceiling_world(FIXTURE)
    bulks = bulk_uses_of(FIXTURE, case)        # Need(kind) as P's bulk uses: memories in batches of 512, R(I) counted
    allowed = all(decide_bulk(state, b, outside={"place:home/andy": ceiling}).allowed for b in bulks)
    assert allowed is case["expected"]

def test_a_trail_of_40_touches_is_no_bound_refusal():
    state, ceiling = ceiling_world(FIXTURE)
    bulk = evaluation_route_bulk(FIXTURE, "sam-c0a8", touches=40)
    assert decide_bulk(state, bulk, outside={"place:home/andy": ceiling}).allowed
```

- [ ] **Step 2: Run the test**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_ceiling.py`
Expected: PASS, every fixture case and 1 more. (It is written after Task 27's fixture, against the permissions plan's
merged `decide_bulk`. A case where the two packages disagree is a defect in Task 27, or in the fixture, never fixed by
editing `permissions.py`.)

- [ ] **Step 3: Commit**

```bash
git add engram/tests/imprint_support.py engram/tests/test_imprint_ceiling.py
git commit -m "Imprints: the station's per-copy check agrees with the permissions spec's meet (I 8, I 16, XM1)"
```

### Task 29: Approval and the hand-off

**Files:**
- Modify: `peer/superyak_peer/imprints.py` (`_approve_imprint`, `_deny_imprint`, `_hand_off`)
- Modify: `peer/superyak_peer/ships.py:279-302` (`station_decide(username, prefix, approve, *, imprints_root: Path | None = None)` routes an imprint item)
- Modify: `peer/superyak_peer/__main__.py` (`station-approve` and `station-deny` take `--imprints-dir`; `describe_decision` for an imprint)
- Modify: `peer/tests/imprint_support.py` (`ship_shortens`)
- Test: `peer/tests/test_imprint_approval.py`

**Interfaces:**
- Consumes: Tasks 26, 27.
- Produces:
  - approving an imprint: first, before any transaction, a refusal if `<root>/<imprint id>/`,
    `<root>/<imprint id>.state/` or a tombstone for the id exists, which changes nothing (the row stays `received`,
    no receipt); then, in one transaction, `decide_use(..., kind="admission", t=now)`; a refusal there is a denial
    whose `denied` receipt names the term (`{"term"}`, R25); else status `approved` and the unsigned `approved`
    receipt; then the two directories (0700, exclusive create, so a race that loses one leaves the row for the
    sweep's `missing`), the absolute root recorded in the row, `imprint.db` and `manifest.json` moved from staging,
    `permission.json` (`{record, signature, station_key}`) and `approved.json` written, staging removed;
  - refusing an audience other than `place:home/<APPROVER>`;
  - a denial deletes the staged bytes and writes `denied` and `deleted` (reason `denied`);
  - `describe_decision` prints "Approved 4f1c. Admitting in the background; see make station-imprints." and then, as
    its last line, `ADMIT: <full imprint id>`, which the Makefile reads to start that one admission (Task 40); or
    "Denied the imprint 4f1c; its bytes are deleted." A docking's decision prints no `ADMIT:` line.
  - `peer/tests/imprint_support.py` gains `ship_shortens(st, *, to: int)`, which appends a `shortened` receipt by the
    ship directly through Task 23's `_append_imprint_receipt`, since Task 31 builds the shortening route later.

- [ ] **Step 1: Write the failing tests**

```python
def test_approve_by_short_id_hands_off_and_records_the_root(tmp_path):
    st = received(tmp_path)
    item, result = st.store.station_decide("andy", st.request_id[:4], True, imprints_root=st.root)
    imp = st.root / st.imprint_id
    assert sorted(p.name for p in imp.iterdir()) == ["approved.json", "imprint.db", "manifest.json", "permission.json"]
    assert (st.root / f"{st.imprint_id}.state").is_dir() and stat.S_IMODE(imp.stat().st_mode) == 0o700
    assert row(st, st.request_id)["imprints_root"] == str(st.root.resolve()) and not staging(st).exists()
    assert [r["record"]["event"] for r in receipts(st)][-1] == "approved"

def test_deny_deletes_everything_and_writes_receipts(tmp_path):
    st = received(tmp_path)
    st.store.station_decide("andy", st.request_id[:4], False, imprints_root=st.root)
    assert not staging(st).exists() and not (st.root / st.imprint_id).exists()
    assert [r["record"]["event"] for r in receipts(st)][-2:] == ["denied", "deleted"]

def test_an_audience_other_than_the_approvers_home_is_refused(tmp_path):
    st = received(tmp_path)
    with pytest.raises(Problem, match="place:home/jenn"):
        st.store.station_decide("jenn", st.request_id[:4], True, imprints_root=st.root)

def test_existing_directories_or_a_tombstone_refuse_the_hand_off(tmp_path):
    st = received(tmp_path); (st.root / "tombstones").mkdir(parents=True)
    (st.root / "tombstones" / f"{st.imprint_id}.json").write_text("{}")
    before = receipts(st)
    with pytest.raises(Problem):
        st.store.station_decide("andy", st.request_id[:4], True, imprints_root=st.root)
    assert row(st, st.request_id)["status"] == "received" and receipts(st) == before and staging(st).exists()

def test_an_approval_names_the_full_imprint_id_for_the_makefile(tmp_path):
    st = received(tmp_path)
    lines = describe_decision(*st.store.station_decide("andy", st.request_id[:4], True, imprints_root=st.root)).splitlines()
    assert lines[-1] == f"ADMIT: {st.imprint_id}" and sum(l.startswith("ADMIT: ") for l in lines) == 1
    assert "ADMIT: " not in describe_decision(*approved_docking(tmp_path / "dock"))

def test_a_refusal_at_approval_is_a_denial_naming_the_term(tmp_path):
    st = received(tmp_path); ship_shortens(st, to=st.clock[0] + 10); st.clock[0] += 20
    st.store.station_decide("andy", st.request_id[:4], True, imprints_root=st.root)
    denied = [r["record"] for r in receipts(st) if r["record"]["event"] == "denied"][0]
    assert denied["detail"] == {"term": "end"} and row(st, st.request_id)["status"] == "deleted"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_approval.py`
Expected: FAIL, `TypeError: station_decide() got an unexpected keyword argument 'imprints_root'`.

- [ ] **Step 3: Implement the approval**

`station_decide` matches imprint items by their request id's prefix, as it does dockings. The `station_key` in
`permission.json` is the row's `station_key`, which the confirm stored (Task 25); `station-approve` holds no key. The denied
receipt's `detail` is `{"term": <term>}` for a refusal by the decision and `{}` for Andy's denial. The `ADMIT:` line
carries the row's imprint id, which `check_request` held to a lowercase uuid4 (Task 24), so it is safe in a unit name.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/superyak_peer/ships.py peer/superyak_peer/__main__.py peer/pyproject.toml peer/tests/imprint_support.py peer/tests/test_imprint_approval.py
git commit -m "Peer: Andy approves or denies an imprint by short id; the hand-off records its root (I 10, A2)"
```

### Task 30: Withdrawal and the station's delete

**Files:**
- Modify: `peer/superyak_peer/imprints.py` (`withdraw_imprint`, `_remove_imprint`, `tombstone_path`, `station_imprint_delete`)
- Modify: `peer/superyak_peer/app.py` (`POST /api/imprints/{id}/withdraw`, for the owner or the requesting ship, through `member`)
- Modify: `peer/superyak_peer/__main__.py` (`station-imprint-delete --id --as --imprints-dir`)
- Test: `peer/tests/test_imprint_withdrawal.py`

**Interfaces:**
- Consumes: Tasks 23, 27, 29.
- Produces:
  - `withdraw_imprint(principal: dict, request_id: str, *, root: Path) -> dict`, I 12's four steps: status
    `deleting` and the signed `withdrawn` receipt (actor: the owner or the ship); removal of the staging, imprint and
    state directories under the root the row records, after restoring write permission, hashing each file first
    (`imprint.db` by the manifest's hash); the tombstone `<recorded root>/tombstones/<imprint id>.json` holding both
    receipts; `deleted` (reason `withdrawn`, the files, and `limits` = `KNOWN_LIMITS`, "Files removed. The station
    does not overwrite disk blocks, and cannot reach copies anyone made by hand.", in every `deleted` receipt) and
    status `deleted`. A failed removal leaves `deleting` and writes
    `delete-failed` (path, error class). A `requested` item is declined instead (R22). Another person or ship: 404;
  - `_remove_imprint(db, row, *, reason: str, actor_id: str | None, root_flag: Path | None) -> list[dict]` (each
    removed file's path, bytes and SHA-256), used by withdrawal, the station delete, the sync and the sweep; when
    `root_flag` differs from the recorded root it logs `"imprints root mismatch: recorded <a>, flag <b>"`;
  - `station_imprint_delete(username: str, prefix: str, *, root: Path) -> dict` (reason `station`).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("status", ["allowed", "received", "approved", "admitted"])
@pytest.mark.parametrize("who", ["owner", "ship"])
def test_withdrawal_in_every_status(tmp_path, status, who):
    st = at_status(tmp_path, status)
    files = every_file_of(st)
    assert withdraw(st, who).status_code == 200
    assert not any(p.exists() for p in files) and tombstone(st).is_file()
    deleted = receipts(st)[-1]["record"]
    assert deleted["event"] == "deleted" and deleted["detail"]["reason"] == "withdrawn"
    assert deleted["detail"]["limits"] == KNOWN_LIMITS
    assert {f["path"] for f in deleted["detail"]["files"]} == {str(p) for p in files}       # files, not directories
    assert withdraw(st, who).status_code == 200 and receipts(st)[-1]["record"]["id"] == deleted["id"]

def test_another_person_or_ship_gets_404_and_a_request_is_declined(tmp_path):
    st = at_status(tmp_path, "admitted")
    assert withdraw_as(st, st.jenn).status_code == 404 and withdraw_as(st, st.other_ship).status_code == 404
    early = at_status(tmp_path / "r", "requested"); withdraw(early, "ship")
    assert row(early, early.request_id)["status"] == "declined" and receipts(early) == []

def test_the_ship_narrows_without_editing_the_owners_records(tmp_path):
    st = at_status(tmp_path, "admitted"); before = row(st, st.request_id)["permission"]
    withdraw(st, "ship")
    assert row(st, st.request_id)["permission"] == before
    assert not st.store.station_imprint_use_decision(st.imprint_id, "trail-evaluation").allowed

def test_the_recorded_root_is_used_and_a_mismatch_is_logged(tmp_path, caplog):
    st = at_status(tmp_path, "admitted"); home_imprints = Path(os.environ["HOME"]) / ".engram" / "imprints"
    other = tmp_path / "other-root"
    st.store.withdraw_imprint(owner_principal(st), st.request_id, root=other)
    assert not (st.root / st.imprint_id).exists() and not home_imprints.exists()
    assert "imprints root mismatch" in caplog.text

def test_a_failed_removal_stays_deleting(tmp_path, monkeypatch):
    st = at_status(tmp_path, "admitted"); monkeypatch.setattr(imprints, "_unlink", raise_once(PermissionError()))
    withdraw(st, "owner")
    assert row(st, st.request_id)["status"] == "deleting"
    assert receipts(st)[-1]["record"]["detail"]["error"] == "PermissionError"

def test_the_station_may_delete(tmp_path):
    st = at_status(tmp_path, "admitted")
    st.store.station_imprint_delete("andy", st.imprint_id[:4], root=st.root)
    assert receipts(st)[-1]["record"]["detail"]["reason"] == "station"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_withdrawal.py`
Expected: FAIL, `assert 405 == 200` (no withdraw route yet).

- [ ] **Step 3: Implement withdrawal**

`station_imprint_use_decision(imprint_id, kind)` is a read-only helper over `decide_use` at the store's clock, used by
the tests here and by Task 37. The tombstone is written with `O_CREAT | O_EXCL`, 0600, after the removal, before
`deleted`. Withdrawal never waits for Andy and needs no operator.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 13 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/superyak_peer/app.py peer/superyak_peer/__main__.py peer/pyproject.toml peer/tests/test_imprint_withdrawal.py
git commit -m "Peer: withdrawal and the station's delete, at once, with hashes and a tombstone (I 12, D17)"
```

### Task 31: Shortening

**Files:**
- Modify: `peer/superyak_peer/imprints.py` (`shorten_imprint`, `_replace_allow_files`)
- Modify: `peer/superyak_peer/app.py` (`POST /api/imprints/{id}/shorten`)
- Test: `peer/tests/test_imprint_withdrawal.py`

**Interfaces:**
- Consumes: Tasks 27, 30.
- Produces: `shorten_imprint(principal: dict, request_id: str, valid_until: int, *, root: Path) -> dict`: refused
  unless `now < valid_until < effective_end`; writes a signed `shortened` receipt (`{"valid_until"}`; actor the owner
  or the ship). The owner's shortening is the replacement of P 5.3 rule 4 and counts in `owner_layer`; the ship's
  narrows only the ceiling. `_replace_allow_files(state_dir: Path, valid_until: int) -> None` rewrites
  `admission.json` and every `uses/*.allow.json` atomically (a temporary file in the same directory, `os.replace`,
  0400), changing only `valid_until`, so `admission.json` keeps the `decided_at` that R24's bound counts from.

- [ ] **Step 1: Write the failing tests**

```python
def test_shortening_narrows_only(tmp_path):
    st = at_status(tmp_path, "admitted"); end = current_end(st)
    for bad in (end, end + 1, st.clock[0] - 1, st.clock[0]):
        assert shorten(st, "owner", bad).status_code == 400
    assert shorten(st, "ship", end - 100).status_code == 200 and current_end(st) == end - 100
    assert shorten(st, "owner", end - 50).status_code == 400              # later than the effective end now

def test_shortening_replaces_admission_json_and_allow_files_atomically(tmp_path):
    st = at_status(tmp_path, "approved"); write_admission_json(st); write_allow_file(st, USE_ID)
    inodes = {p: p.stat().st_ino for p in allow_files(st)}
    docs = {p: json.loads(p.read_text()) for p in allow_files(st)}
    shorten(st, "ship", current_end(st) - 100)
    for p in allow_files(st):
        doc = json.loads(p.read_text())                         # only valid_until moves; decided_at stays (R24)
        assert doc == {**docs[p], "valid_until": current_end(st)} and p.stat().st_ino != inodes[p] and stat.S_IMODE(p.stat().st_mode) == 0o400
    assert row(st, st.request_id)["permission"] == original_permission(st)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_withdrawal.py`
Expected: FAIL, `assert 405 == 400` (no shorten route yet).

- [ ] **Step 3: Implement shortening**

The receipt is written first, then the files are replaced, so a reader of an allow file never sees an end later than
the station's. Lengthening is refused with "An end can only move earlier. A later end needs a new imprint and a new
yes." (D18).

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 15 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/superyak_peer/app.py peer/tests/test_imprint_withdrawal.py
git commit -m "Peer: shortening by the owner or the ship, narrowing only, rewriting allow files atomically (I 12, D18)"
```

### Task 32: Admission checks 1 to 9, and `store_reader.connect(vec=True)`

**Files:**
- Modify: `engram/store_reader.py:43-55` (`connect(path, immutable=False, vec=False)`)
- Modify: `engram/imprint_checks.py`
- Modify: `engram/tests/imprint_support.py` (`handed_off`, `tampered`)
- Test: `engram/tests/test_imprint_checks.py`

**Interfaces:**
- Consumes: Task 19's packages; Task 14's L2 and L3.
- Produces:
  - `store_reader.connect(..., vec=True)` loads `sqlite_vec` as `Storage.open_read_only` does (`storage.py:153-156`);
  - `CheckFailure(step: int | str, message: str)` (R11); `CHECK_MESSAGES: dict[int, str]` (fixed sentences);
  - `verify(imprint_dir: Path, *, verify_cmd: Sequence[str], migrations_dir: Path, scratch: Path) -> CheckFailure | None`:
    I 10's checks in order, stopping at the first failure; this task writes 1 to 9 (Task 33 adds 10 to 17). The file
    is opened `mode=ro&immutable=1` with sqlite-vec loaded. Check 3 runs `verify_cmd + ["--permission",
    str(imprint_dir / "permission.json")]` and needs exit 0 (R9), then compares `request_sha256`, `plan_digest`, the two
    `imprint_id`s and the source ids. Check 7 builds the reference with `Storage(ref, migrations_dir=<a scratch copy of
    exactly manifest.schema.applied>)` and compares `sqlite_master` (type, name, tbl_name, sql) and every vec0 `_info`;
  - `imprint_support.handed_off(tmp_path, built, *, route: bool, valid_until: int) -> tuple[Path, str]` lays out a
    root as the station's hand-off would (the four files, `<id>.state/` with `admission.json`); `tampered(tmp_path,
    change) -> Path` changes a copy, then fixes `manifest.package` so checks before the target pass.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("change,step", [
    ("extra_file", 1), ("symlinked_manifest", 1), ("changed_byte", 2), ("permission_fails_verify", 3),
    ("request_sha256_differs", 3), ("wal_header", 4), ("corrupt_page", 5), ("unknown_migration", 6),
    ("planted_trigger", 7), ("extra_table", 7), ("other_vec_info", 7), ("changed_meta", 8), ("non_empty_dropped_table", 9)])
def test_each_check_fails(tmp_path, change, step):
    root, imprint_id = tampered(tmp_path, change)
    failure = verify(root / imprint_id, verify_cmd=stub_verify(ok=change != "permission_fails_verify"),
                     migrations_dir=MIGRATIONS, scratch=tmp_path / "s")
    assert failure is not None and failure.step == step and failure.message == CHECK_MESSAGES[step]

def test_vec0_reading_is_immutable_and_makes_no_side_file(tmp_path):
    root, imprint_id = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    conn = store_reader.connect(root / imprint_id / "imprint.db", immutable=True, vec=True)
    assert conn.execute("SELECT count(*) FROM episode_vectors").fetchone()[0] > 0
    assert sorted(p.name for p in (root / imprint_id).iterdir()) == ["approved.json", "imprint.db", "manifest.json", "permission.json"]

def test_a_clean_package_passes_checks_1_to_9(tmp_path):
    root, imprint_id = handed_off(tmp_path, built_package(tmp_path), route=True, valid_until=FAR)
    assert verify(root / imprint_id, verify_cmd=stub_verify(ok=True), migrations_dir=MIGRATIONS, scratch=tmp_path / "s") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_checks.py`
Expected: FAIL, `TypeError: connect() got an unexpected keyword argument 'vec'`.

- [ ] **Step 3: Implement checks 1 to 9**

Check 1 uses `os.lstat` so a symlink fails. Check 4 reads the first 100 bytes. Check 6 uses `store_reader._schema`.
A mismatch at check 7 says "Put the engram code and sqlite-vec on the two machines on one commit." Check 9 counts
rows of every `dropped` table that exists.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 15 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/store_reader.py engram/imprint_checks.py engram/tests/imprint_support.py engram/tests/test_imprint_checks.py
git commit -m "Imprints: admission checks 1 to 9 on an immutable, vec-loaded open (I 10)"
```

### Task 33: Admission checks 10 to 17

**Files:**
- Modify: `engram/imprint_checks.py`
- Test: `engram/tests/test_imprint_checks.py`

**Interfaces:**
- Consumes: Tasks 12, 14, 32.
- Produces: checks 10 to 17 in `verify`, each also callable alone as `check_<n>(conn, manifest) -> str | None`: 10
  references resolve inside the package, the log rows' `target_ids` included, so an instinct id in a recall row
  (the instincts table is empty, check 9) fails here, before check 11; 11 the scrubs (I 10's rules for `memory_log` and `operation_log`); 12 the
  scope (with D7's rule without `route`); 13 counts equal `manifest.contents` and the recomputed plan digest equals
  `manifest.plan_digest`; 14 `freelist_count` 0; 15 rowids 1..n in every memory table and FTS `_docsize`; 16 L2;
  17 L3 against the plan digest's vector keys.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("change,step", [
    ("dangling_target", 10), ("unscrubbed_context", 11), ("instinct_id_in_recall", 10), ("lane_outside_scope", 12),
    ("time_outside_scope", 12), ("session_id_without_route", 12), ("digest_mismatch", 13), ("free_page", 14),
    ("rowid_gap", 15), ("fts_orphan", 16), ("non_zero_invalid_vec0_slot", 17)])
def test_each_check_fails(tmp_path, change, step):
    root, imprint_id = tampered(tmp_path, change)
    failure = verify(root / imprint_id, verify_cmd=stub_verify(ok=True), migrations_dir=MIGRATIONS, scratch=tmp_path / "s")
    assert failure is not None and failure.step == step

def test_a_session_id_set_by_hand_also_fails_the_digest(tmp_path):
    root, imprint_id = tampered(tmp_path, "session_id_without_route")
    conn, manifest = open_checked(root / imprint_id)
    assert check_12(conn, manifest) is not None and check_13(conn, manifest) is not None

def test_a_clean_package_passes_all_17(tmp_path):
    for route in (False, True):
        root, imprint_id = handed_off(tmp_path / str(route), built_package(tmp_path / str(route), route=route), route=route, valid_until=FAR)
        assert verify(root / imprint_id, verify_cmd=stub_verify(ok=True), migrations_dir=MIGRATIONS, scratch=tmp_path / "s") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_checks.py`
Expected: FAIL, `AssertionError` on `failure is not None` for step 10.

- [ ] **Step 3: Implement checks 10 to 17**

Check 13 recomputes row keys from the package with Task 12's `row_key`, so both sides share one definition, and
Task 19's second implementation guards that definition. Check 17 passes L3 the plan digest's vector keys, the SHA-256
form the build passes too (Task 14).

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 28 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint_checks.py engram/tests/test_imprint_checks.py
git commit -m "Imprints: admission checks 10 to 17, the digest recomputed from the package (I 10, D22)"
```

### Task 34: `imprint.py admit`

**Files:**
- Modify: `engram/imprint.py` (`admit`, `list_imprints`, the `admit` and `list` subcommands)
- Test: `engram/tests/test_imprint_admit.py`

**Interfaces:**
- Consumes: Tasks 4, 5, 32, 33.
- Produces:
  - `admit(imprint_id: str, *, root: Path, verify_cmd: Sequence[str], now: Callable[[], float] = time.time,
    derive=None, record_use=None, calibrate_fn=calibrate.calibrate, calibration_now: datetime | None = None) -> int`
    (exit codes of R11);
  - `_still_allowed(root: Path, imprint_id: str, now: float) -> str | None`: `None`, or `"withdrawn"` (a tombstone, or
    `approved.json` gone) or `"ended"` (`admission.json` gone or its `valid_until` ≤ now). Run before verification,
    before calibration, and before each write. Admission never creates `<id>/` or `<id>.state/`;
  - a `calibration/` directory already in `<id>.state/` means a second run of a begun admission, which R24 forbids
    (only `imprint.py admit` run twice by hand gets here): it fails before verification with step `calibration` and
    `RERUN_REFUSED = "This admission already began once, and an admission runs once. Nothing was admitted."`, and
    nothing is calibrated or cleared (RF1);
  - a calibration that raises (a `MemoryError` included), or whose report has `source_unchanged` false, fails with
    step `calibration` and `CALIBRATION_FAILED = "Calibration did not finish. Nothing was admitted."`, never the
    exception's text (YN4);
  - calibration: `calibrate_fn(<id>/imprint.db, <id>.state/calibration, migrate=True, no_content=True, no_paths=True,
    notes=…, max_lane_episodes=7500, create_parents=False, now=calibration_now)`, with `notes = {"snapshot": "0
    sessions and 0 log rows, because route was not chosen"}` without `route`; then `snapshot.db` and `working.db` go;
  - registration: `<id>/imprint.json` (status, manifest, permission, admission time, the report's SHA-256, the engram
    commit); files 0444, the directory 0555; `<id>.state/result.json` `{"status": "admitted", "checks": 17,
    "report_sha256", "skipped", "roads_and_trails": N, "ended_at"}`. A failure writes `{"status": "failed", "step",
    "message", "ended_at"}` and exits 1;
  - `list_imprints(root: Path) -> list[dict]` and `imprint.py list --imprints-dir`.

- [ ] **Step 1: Write the failing tests**

```python
CAL_NOW = datetime(2026, 10, 25, 19, 30, tzinfo=timezone.utc)

def test_calibration_at_admission_is_content_free_and_leaves_no_copies(tmp_path):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    assert admit(iid_, root=root, verify_cmd=OK, calibration_now=CAL_NOW) == 0
    cal = root / f"{iid_}.state" / "calibration"
    report = json.loads((cal / "report.json").read_text())
    assert not has_key(report, "content") and no_memory_text(report, built_texts(tmp_path))
    assert report["source_unchanged"] and report["source_side_files_created"] == []
    assert sorted(p.name for p in cal.iterdir()) == ["report.json", "report.md"]
    assert sorted(p.name for p in (root / iid_).iterdir()) == ["approved.json", "imprint.db", "imprint.json", "manifest.json", "permission.json"]

def test_calibration_with_and_without_route_agree_where_they_must(tmp_path):
    a = admitted_report(tmp_path / "a", route=False, now=CAL_NOW); b = admitted_report(tmp_path / "b", route=True, now=CAL_NOW)
    for name in ("first_open", "persistence_scores", "cohesion", "persistence"):
        assert a["analyses"].get(name) == b["analyses"].get(name), name
    assert survey_minus(a) == survey_minus(b)    # less episodes.sessions, memory_log, operation_log, file, identity
    assert a["snapshot"]["episodes"]["sessions"] == 0 and a["snapshot"]["row_counts"]["memory_log"] == 0
    assert a["notes"] == {"snapshot": "0 sessions and 0 log rows, because route was not chosen"} and "notes" not in b
    assert a["analyses"]["paths"] == b["analyses"]["paths"] == PATHS_NOT_MEASURED
    assert not mentions_any(a, session_ids(tmp_path / "b")) and not mentions_any(b, session_ids(tmp_path / "b"))

@pytest.mark.parametrize("when", ["checking", "calibrating"])
def test_a_withdrawal_during_admission_stops_it(tmp_path, when):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    hook = remove_like_withdrawal(root, iid_)                    # removes both directories, writes the tombstone
    code = admit(iid_, root=root, verify_cmd=OK if when == "calibrating" else hooked_verify(hook),
                 calibrate_fn=hooked_calibrate(hook) if when == "calibrating" else calibrate.calibrate)
    assert code == 4 and not (root / iid_).exists() and not (root / f"{iid_}.state").exists()

def test_an_end_reached_during_calibration_stops_it_before_the_report(tmp_path):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    code = admit(iid_, root=root, verify_cmd=OK, calibrate_fn=hooked_calibrate(lambda: shorten_admission_json(root, iid_, to=1)))
    assert code == 5 and not (root / f"{iid_}.state" / "result.json").exists()

def test_rf1_a_dead_runs_calibration_fails_the_rerun(tmp_path):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    (root / f"{iid_}.state" / "calibration").mkdir(); (root / f"{iid_}.state" / "calibration" / "snapshot.db").write_bytes(b"x")
    assert admit(iid_, root=root, verify_cmd=must_not_run, calibrate_fn=must_not_be_called) == 1
    result = json.loads((root / f"{iid_}.state" / "result.json").read_text())
    assert (result["step"], result["message"]) == ("calibration", RERUN_REFUSED) and not (root / iid_ / "imprint.json").exists()

def test_a_calibration_that_raises_fails_with_step_calibration(tmp_path):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    assert admit(iid_, root=root, verify_cmd=OK, calibrate_fn=raise_(MemoryError("/home/sam/secret path"))) == 1
    text = (root / f"{iid_}.state" / "result.json").read_text()
    assert (json.loads(text)["step"], json.loads(text)["message"]) == ("calibration", CALIBRATION_FAILED) and "secret" not in text

def test_a_failed_check_writes_a_failed_result(tmp_path):
    root, iid_ = tampered(tmp_path, "changed_byte")
    assert admit(iid_, root=root, verify_cmd=OK) == 1
    assert json.loads((root / f"{iid_}.state" / "result.json").read_text())["step"] == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_admit.py`
Expected: FAIL, `ImportError: cannot import name 'admit' from 'imprint'`.

- [ ] **Step 3: Implement admission**

Each write goes through one helper, `_write_state(root, imprint_id, name, doc)`, that calls `_still_allowed` first
and writes atomically. A run killed at its memory cap or time limit writes nothing; the station's sync fails it once
R24's bound passes (Task 36). The subcommand is `imprint.py admit --id ID --imprints-dir DIR --verify-cmd
"<command>"`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint.py engram/tests/imprint_support.py engram/tests/test_imprint_admit.py
git commit -m "Imprints: imprint.py admit, decided again, checked before each write, calibrated content-free (I 10, D39)"
```

### Task 35: Counting R(I), and admission's `Need`

**Files:**
- Modify: `engram/imprint.py` (`count_roads_and_trails`, `CountUnavailable`, `UseRecord`, `NEED_ADMISSION`)
- Test: `engram/tests/test_imprint_admit.py`

**Interfaces:**
- Consumes: Task 34; the trails plan's pure functions through `derive` (R10); Task 28's `ceiling_world`.
- Produces:
  - `class CountUnavailable(RuntimeError)`;
  - `count_roads_and_trails(conn, *, lanes: Sequence[str], as_of: int, derive: Callable | None = None) -> int`: N,
    the sum over the scope's lanes of the roads and trails `derive(conn, lane=lane, as_of=as_of)` returns (T 4 and
    5). `derive=None` imports `trails` and raises `CountUnavailable` when it can't. With `route`, `admit` calls it
    after check 17 at `as_of` = the scope's `until`; without `route`, N = 0 and nothing is imported. A
    `CountUnavailable` fails admission with step `count` and R10's message (YN4);
  - `UseRecord(object_kind: str, action: str, purpose: str, batch: int, count: int)`; `admit` calls `record_use`
    before each use it performs: named bulk uses on the memories in batches of 512, and the counted use on R(I);
  - `NEED_ADMISSION(route: bool) -> frozenset[tuple[str, str, str]]`, I 8's Need(admission);
  - the docstring of `count_roads_and_trails` says N is R(I) as `Need` names it, at `as_of` = t₁ over the scope's
    lanes, and may exceed what one evaluation derives (YN1).

- [ ] **Step 1: Write the failing tests**

```python
def test_the_count_reaches_result_json_and_is_zero_without_route(tmp_path):
    for route, expected in ((True, 3), (False, 0)):
        root, iid_ = handed_off(tmp_path / str(route), built_package(tmp_path / str(route), route=route), route=route, valid_until=FAR)
        derive = counting_stub(3) if route else must_not_be_called
        assert admit(iid_, root=root, verify_cmd=OK, derive=derive) == 0
        assert json.loads((root / f"{iid_}.state" / "result.json").read_text())["roads_and_trails"] == expected

def test_admission_with_route_fails_closed_without_the_trail_functions(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "trails", None)
    root, iid_ = handed_off(tmp_path, built_package(tmp_path, route=True), route=True, valid_until=FAR)
    assert admit(iid_, root=root, verify_cmd=OK) == 1
    result = json.loads((root / f"{iid_}.state" / "result.json").read_text())
    assert (result["step"], result["message"]) == ("count", "roads and trails can't be counted: trails.py is not installed")

def test_counting_reads_the_package_at_t1(tmp_path):
    seen = []
    root, iid_ = handed_off(tmp_path, built_package(tmp_path, route=True, until=T1), route=True, valid_until=FAR)
    admit(iid_, root=root, verify_cmd=OK, derive=recording_stub(seen))
    assert {s["as_of"] for s in seen} == {T1} and {s["lane"] for s in seen} == {"work"}

def test_admission_stays_inside_its_need(tmp_path):
    recorded = []
    root, iid_ = handed_off(tmp_path, built_package(tmp_path, route=True), route=True, valid_until=FAR)
    admit(iid_, root=root, verify_cmd=OK, derive=counting_stub(2), record_use=recorded.append)
    assert {(u.object_kind, u.action, u.purpose) for u in recorded} <= NEED_ADMISSION(route=True)
    assert not [u for u in recorded if u.object_kind == "road-or-trail" and u.purpose == "calibration"]
    state, ceiling = ceiling_world(fixture_for(root, iid_))
    assert all(decide_bulk(state, as_bulk(u, root, iid_), outside={"place:home/andy": ceiling}).allowed for u in recorded)

def test_count_matches_the_trail_functions(tmp_path):
    trails = pytest.importorskip("trails", reason="trails.py comes with the trails plan (gate G13)")
    root, iid_ = handed_off(tmp_path, built_package(tmp_path, route=True, store=trail_rich_store, until=T1), route=True, valid_until=FAR)
    assert admit(iid_, root=root, verify_cmd=OK) == 0
    n = json.loads((root / f"{iid_}.state" / "result.json").read_text())["roads_and_trails"]
    assert n == roads_and_trails_by_hand(trails, root / iid_ / "imprint.db", as_of=T1) == roads_and_trails_by_hand(
        trails, root / iid_ / "imprint.db", as_of=T1 + 86_400)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_admit.py`
Expected: FAIL, `TypeError: admit() got an unexpected keyword argument 'derive'`.

- [ ] **Step 3: Implement the count**

The count opens the package with `store_reader.connect(..., immutable=True)`. It keeps only the number. The real
`derive` is a thin adapter over the trails plan's pure functions, in one place (`_trail_derive`), so the trails plan
changes one function when it fixes their names. Those functions take `as_of` in integer microseconds (the trails
plan's TR22), so `_trail_derive` passes `as_of * 10**6`; every time this plan holds stays in seconds.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 12 passed, 1 skipped (`test_count_matches_the_trail_functions`, until the
trails plan's pure functions exist).

- [ ] **Step 5: Commit**

```bash
git add engram/imprint.py engram/tests/imprint_support.py engram/tests/test_imprint_admit.py
git commit -m "Imprints: admission counts R(I) at t1 with route, inside its Need, failing closed (I 10, XS2, YN4)"
```

### Task 36: Admission runs on the station

**Files:**
- Modify: `peer/superyak_peer/imprints.py` (`station_imprint_admit_begin`, the admission part of `station_imprint_sync`, `station_imprints`)
- Modify: `peer/superyak_peer/__main__.py` (`station-imprint-admit-begin --id`, `station-imprint-sync`, `station-imprints [--awaiting-admission] [--resolve PREFIX]`, each with `--imprints-dir` and `--as`)
- Test: `peer/tests/test_imprint_admission.py`

**Interfaces:**
- Consumes: Tasks 27, 29, 30; engram's `result.json` (Task 34).
- Produces:
  - `ADMISSION_BOUND = 1860` (the unit's `RuntimeMaxSec=1800` plus `TimeoutStopSec=60`, R24) and
    `ADMISSION_STOPPED = "Admission stopped before it wrote a result: it reached its memory or time limit, or the
    station stopped. Nothing was admitted; send it again."`;
  - `station_imprint_admit_begin(imprint_id: str, *, root: Path, operator: str) -> dict`: when `admission.json`
    already exists, it refuses (`{"allowed": False, "begun": True}`) and writes nothing, no receipt: a begun
    admission runs once (R24). Else I 8's check at the store's clock; allowed → `<id>.state/admission.json` (0400,
    `{"kind": "imprint-admission-allow", "instance_id", "decided_at", "valid_until"}`, `decided_at` the store's clock);
    refused → a `failed` receipt `{"term"}` (R25), no file. The command exits 0 when allowed and 3 otherwise;
  - `station_imprint_sync(*, root: Path) -> dict` (admission part): for each `approved` row, the first rule that
    holds:
    1. `result.json` says `admitted`: the `admitted` receipt (`{"checks": 17, "report_sha256", "skipped",
       "roads_and_trails"}`) and status `admitted`;
    2. `result.json` says `failed`: `failed` `{"step", "message"}` from it, then the deletion, reason `failed`;
    3. a `failed` receipt naming a term exists (refused at a run's start): the deletion, reason `ended` when the term
       is `end`, else `failed`;
    4. the effective end has passed, whether the admission ended while it ran (`imprint.py admit`'s exit 5) or never
       began: `failed` `{"term": "end"}`, then the deletion, reason `ended` (I 10's "On 'ended'");
    5. `admission.json` exists and its `decided_at` is more than `ADMISSION_BOUND` seconds ago, with no `result.json`
       (the unit hit its memory cap or time limit, or died): `failed` `{"step": "calibration", "message":
       ADMISSION_STOPPED}`, then the deletion, reason `failed` (R24, I 10, D16);
    6. else nothing: the admission waits or runs.
    Rows in `deleting` or `deleted` never move. A killed unit runs no sync of its own, so rule 5 is applied by the
    first sync after the bound, which the hourly sweep runs (as Task 39 finishes a stopped use);
  - `station_imprints(*, root: Path, awaiting: bool = False) -> list[dict]` and its lines (I 10's example, with
    "receipts signed" or "receipts not yet signed"); `--awaiting-admission` prints the full ids of `approved` rows
    with neither `admission.json` nor `result.json`, never begun (R24); `--resolve PREFIX` prints one full imprint id
    or exits 2.

- [ ] **Step 1: Write the failing tests**

```python
def test_admission_after_the_end_is_refused_and_deleted_before_any_sweep(tmp_path):
    st = approved(tmp_path); st.clock[0] = effective_end_of(st) + 1
    assert st.store.station_imprint_admit_begin(st.imprint_id, root=st.root, operator="andy")["allowed"] is False
    assert not (st.root / f"{st.imprint_id}.state" / "admission.json").exists()
    st.store.station_imprint_sync(root=st.root)
    assert [r["record"]["event"] for r in receipts(st)][-2:] == ["failed", "deleted"]
    assert receipts(st)[-2]["record"]["detail"]["term"] == "end" and receipts(st)[-1]["record"]["detail"]["reason"] == "ended"

def test_the_same_when_the_ship_shortened_to_a_time_that_passed(tmp_path):
    st = approved(tmp_path); ship_shortens(st, to=st.clock[0] + 5); st.clock[0] += 10
    assert st.store.station_imprint_admit_begin(st.imprint_id, root=st.root, operator="andy")["term"] == "end"

def test_sync_records_an_admitted_result_with_its_count(tmp_path):
    st = approved(tmp_path, route=True); begin(st); write_result(st, status="admitted", roads_and_trails=150_000)
    st.store.station_imprint_sync(root=st.root)
    admitted = receipts(st)[-1]["record"]
    assert admitted["event"] == "admitted" and admitted["detail"]["roads_and_trails"] == 150_000 and row(st)["status"] == "admitted"

def test_sync_never_moves_a_withdrawn_imprint_to_admitted(tmp_path):
    st = approved(tmp_path); begin(st); write_result(st, status="admitted", roads_and_trails=0)
    withdraw(st, "owner"); leftover_result(st)                    # a write that landed after the removal
    st.store.station_imprint_sync(root=st.root)
    assert row(st)["status"] == "deleted" and "admitted" not in [r["record"]["event"] for r in receipts(st)]

def test_a_failed_result_deletes_the_package(tmp_path):
    st = approved(tmp_path); begin(st); write_result(st, status="failed", step=13, message=CHECK_13)
    st.store.station_imprint_sync(root=st.root)
    assert [r["record"]["event"] for r in receipts(st)][-2:] == ["failed", "deleted"] and not (st.root / st.imprint_id).exists()
    assert receipts(st)[-2]["record"]["detail"] == {"step": 13, "message": CHECK_13}

def test_ended_during_admission_writes_failed_then_deleted(tmp_path):
    st = approved(tmp_path); begin(st)                       # imprint.py admit then exits 5 and writes no result
    st.clock[0] = effective_end_of(st) + 1; st.store.station_imprint_sync(root=st.root)
    failed, deleted = [r["record"] for r in receipts(st)][-2:]
    assert (failed["event"], failed["detail"]) == ("failed", {"term": "end"})
    assert (deleted["event"], deleted["detail"]["reason"], row(st)["status"]) == ("deleted", "ended", "deleted")

def test_a_begun_admission_with_no_result_fails_once_its_bound_passes(tmp_path):
    st = approved(tmp_path); begin(st)                       # the unit was killed at MemoryMax or RuntimeMaxSec
    st.clock[0] = decided_at_of(st) + ADMISSION_BOUND; st.store.station_imprint_sync(root=st.root)
    assert row(st)["status"] == "approved"                    # the unit may still be stopping
    st.clock[0] += 1; st.store.station_imprint_sync(root=st.root)
    failed, deleted = [r["record"] for r in receipts(st)][-2:]
    assert (failed["event"], failed["detail"]) == ("failed", {"step": "calibration", "message": ADMISSION_STOPPED})
    assert (deleted["event"], deleted["detail"]["reason"]) == ("deleted", "failed") and not (st.root / st.imprint_id).exists()

def test_only_an_admission_never_begun_awaits_and_a_begun_one_never_begins_again(tmp_path):
    st = approved(tmp_path)
    assert [r["imprint_id"] for r in st.store.station_imprints(root=st.root, awaiting=True)] == [st.imprint_id]
    begin(st); before = admission_json_bytes(st); events = [r["record"]["event"] for r in receipts(st)]
    assert st.store.station_imprint_admit_begin(st.imprint_id, root=st.root, operator="andy") == {"allowed": False, "begun": True}
    assert admission_json_bytes(st) == before and [r["record"]["event"] for r in receipts(st)] == events
    assert st.store.station_imprints(root=st.root, awaiting=True) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_admission.py`
Expected: FAIL, `AttributeError: 'Store' object has no attribute 'station_imprint_admit_begin'`.

- [ ] **Step 3: Implement the runs**

The sync takes rows in one transaction each, re-reading the status inside it, so a withdrawal between read and write
wins. `station-imprints` opens `Store(signing=False)`. `ship_shortens` is Task 29's helper; `approved(tmp_path)`
approves through `station_decide`; `begin(st)` runs `station_imprint_admit_begin` and asserts it allowed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/superyak_peer/__main__.py peer/pyproject.toml peer/tests/test_imprint_admission.py
git commit -m "Peer: admission decided again at each run; the sync records results and never revives a withdrawal (I 10)"
```

### Task 37: A use begins

**Files:**
- Modify: `peer/superyak_peer/imprints.py` (`station_imprint_use_begin`)
- Modify: `peer/superyak_peer/__main__.py` (`station-imprint-use-begin --id --use --as --imprints-dir`; R23)
- Test: `peer/tests/test_imprint_uses.py`

**Interfaces:**
- Consumes: Tasks 27, 36.
- Produces: `station_imprint_use_begin(username: str, prefix: str, use: str, *, root: Path) -> dict`. Allowed: a new
  lowercase uuid4 `use_id`, the `use-started` receipt (`use`, `use_id`, `actions`, `purpose`, `objects` as
  `{"imprint", "count", "roads_and_trails"}` with N from the `admitted` receipt) and the allow file
  `<id>.state/uses/<use id>.allow.json` (0400) with exactly I 12's keys, written after the receipt. Refused: a
  `refused` receipt (`use`, `actions`, `purpose`, `term`, and `roads_and_trails` once admitted) and nothing else. The
  command prints the use id as its only stdout line, or exits 3 when refused.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_allowed_use_writes_its_receipt_then_its_allow_file(tmp_path):
    st = admitted(tmp_path, route=True, n=4)
    out = st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    allow = json.loads((st.root / f"{st.imprint_id}.state" / "uses" / f"{out['use_id']}.allow.json").read_text())
    assert USE_ID.fullmatch(out["use_id"]) and set(allow) == ALLOW_KEYS and allow["actions"] == ["read", "recall", "route"]
    assert (allow["requester"], allow["acting_for"], allow["place"]) == ("agent:station-imprints", "person:andy", "place:home/andy")
    started = receipts(st)[-1]["record"]
    assert started["event"] == "use-started" and started["detail"]["objects"] == {"imprint": st.imprint_id, "count": st.count, "roads_and_trails": 4}

@pytest.mark.parametrize("fault,term", [("not_admitted", "status"), ("withdrawn", "withdrawal"), ("ended", "end"),
                                        ("other_operator", "audience"), ("no_route", "ceiling")])
def test_a_refused_use_writes_a_refused_receipt_and_nothing_else(tmp_path, fault, term):
    st = admitted_with_fault(tmp_path, fault)
    out = st.store.station_imprint_use_begin(operator_for(fault), st.imprint_id[:4], "trail-evaluation", root=st.root)
    assert out == {"allowed": False, "term": term} and not list((st.root / f"{st.imprint_id}.state").glob("uses/*"))
    assert receipts(st)[-1]["record"]["event"] == "refused" and receipts(st)[-1]["record"]["detail"]["term"] == term

def test_the_command_prints_only_the_use_id(tmp_path):
    st = admitted(tmp_path, route=True, n=0)
    done = run_peer_cli(st, ["station-imprint-use-begin", "--id", st.imprint_id[:4], "--use", "trail-evaluation", "--as", "andy"])
    assert done.returncode == 0 and USE_ID.fullmatch(done.stdout.strip()) and len(done.stdout.splitlines()) == 1
```

`admitted_with_fault`'s `withdrawn` plants a `withdrawn` receipt and leaves the status `admitted`, so the withdrawal
term is reached alone. A real withdrawal sets `deleting`, then `deleted`, and is refused first at `status`, which
`not_admitted` covers.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_uses.py`
Expected: FAIL, `AttributeError: 'Store' object has no attribute 'station_imprint_use_begin'`.

- [ ] **Step 3: Implement the begin step**

`uses/` is created under the existing state directory with `parents=False`, so a removed state directory is never
recreated. `records` in the allow file are the ids `decide_use` returned.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/superyak_peer/__main__.py peer/pyproject.toml peer/tests/test_imprint_uses.py
git commit -m "Peer: a use is decided, given a uuid4, a use-started receipt and an allow file (I 12, D41)"
```

### Task 38: `imprint.py use`

**Files:**
- Modify: `engram/imprint.py` (`use`, `USE_ID`, the `use` subcommand)
- Test: `engram/tests/test_imprint_use.py`

**Interfaces:**
- Consumes: Task 37's allow file; the trails plan's CLI through `trails_cmd` (R10).
- Produces: `USE_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")`;
  `use(imprint_id: str, use_id: str, *, root: Path, lane: str | None = None, trails_cmd: Sequence[str] | None = None,
  now: Callable[[], float] = time.time) -> int`. It refuses, writing nothing, a use id that is not a lowercase uuid4,
  no allow file, a tombstone, a passed `valid_until`, or an existing `uses/<use id>/`. It creates that directory (0700,
  never its parents), then in a `try`/`finally` fills `--lane` from `manifest.json`'s one lane when `lane` is None (a
  two-lane scope raises), runs `trails_cmd + [<root>/<id>/imprint.db, "--evaluate", "--lane", lane, "--seed",
  str(int(use_id[:8], 16)), "--deadline", "1740", "--json", "--imprint-use", use_id]`, writes `report.json` (stdout,
  only on exit 0) and then `result.json` (`{"kind": "imprint-use-result", "use_id", "exit", "error", "report",
  "ended_at"}`), each atomically. `exit` is the exit status, or minus the signal; an exception gives `exit` null and
  `error` its class name.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("bad", ["C0A8F5E2-0000-4000-8000-000000000000", "c0a8f5e2-0000-1000-8000-000000000000", "x", ""])
def test_a_use_id_must_be_a_lowercase_uuid4(tmp_path, bad):
    root, iid_ = admitted_imprint(tmp_path)
    assert use(iid_, bad, root=root, trails_cmd=STUB_OK) == 2 and not uses_dirs(root, iid_)

def test_a_use_runs_once(tmp_path):
    root, iid_, use_id = with_allow(tmp_path)
    assert use(iid_, use_id, root=root, trails_cmd=STUB_OK) == 0
    assert use(iid_, use_id, root=root, trails_cmd=STUB_OK) == 2              # its directory exists

def test_report_then_result_each_atomic(tmp_path, monkeypatch):
    root, iid_, use_id = with_allow(tmp_path); order = []
    monkeypatch.setattr(imprint.os, "replace", recording_replace(order))
    use(iid_, use_id, root=root, trails_cmd=STUB_OK)
    assert [Path(dst).name for _, dst in order] == ["report.json", "result.json"]
    result = json.loads((root / f"{iid_}.state" / "uses" / use_id / "result.json").read_text())
    assert result | {"ended_at": 0} == {"kind": "imprint-use-result", "use_id": use_id, "exit": 0, "error": None, "report": True, "ended_at": 0}

def test_lane_is_filled_from_a_one_lane_scope_and_refused_for_two(tmp_path):
    root, iid_, use_id = with_allow(tmp_path, lanes=["work"]); argv = []
    use(iid_, use_id, root=root, trails_cmd=recording_stub(argv))
    assert argv[argv.index("--lane") + 1] == "work" and argv[argv.index("--deadline") + 1] == "1740"
    root2, iid2, use2 = with_allow(tmp_path / "two", lanes=["personal", "work"])
    use(iid2, use2, root=root2, trails_cmd=must_not_run)
    assert json.loads(result_of(root2, iid2, use2))["error"] == "ValueError" and json.loads(result_of(root2, iid2, use2))["exit"] is None

def test_failures_name_a_class_never_a_message(tmp_path, monkeypatch):
    root, iid_, use_id = with_allow(tmp_path)
    monkeypatch.setattr(imprint, "_run_trails", raise_(OSError("/home/sam/secret path")))
    use(iid_, use_id, root=root, trails_cmd=STUB_OK)
    text = result_of(root, iid_, use_id)
    assert json.loads(text)["error"] == "OSError" and "secret" not in text

def test_exit_statuses_and_signals(tmp_path):
    for stub, exit_, report in ((STUB_EXIT_3, 3, False), (STUB_KILLED, -9, False), (STUB_EXIT_1, 1, False)):
        root, iid_, use_id = with_allow(tmp_path / str(exit_))
        use(iid_, use_id, root=root, trails_cmd=stub)
        assert (json.loads(result_of(root, iid_, use_id))["exit"], report_exists(root, iid_, use_id)) == (exit_, report)

def test_a_tombstone_or_a_passed_end_refuses_before_the_directory(tmp_path):
    for fault in ("tombstone", "ended", "no_allow_file"):
        root, iid_, use_id = with_allow(tmp_path / fault, fault=fault)
        assert use(iid_, use_id, root=root, trails_cmd=STUB_OK) == 2 and not uses_dir(root, iid_, use_id).exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_use.py`
Expected: FAIL, `ImportError: cannot import name 'use' from 'imprint'`.

- [ ] **Step 3: Implement the use**

`_run_trails(argv)` runs the subprocess with stdout captured and stderr to the unit's journal; its own environment is
the unit's. A signal that stops `imprint.py use` itself writes nothing (I 12; XN1): only the `finally` writes, and it
does not run on SIGKILL.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 10 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint.py engram/tests/imprint_support.py engram/tests/test_imprint_use.py
git commit -m "Imprints: imprint.py use runs once, always with --lane, and records how it ended (I 12, D41)"
```

### Task 39: The sync finishes uses

**Files:**
- Modify: `peer/superyak_peer/imprints.py` (the use part of `station_imprint_sync`: `_finish_uses`)
- Test: `peer/tests/test_imprint_uses.py`

**Interfaces:**
- Consumes: Tasks 37, 38.
- Produces: the sync finishes every use with `use-started` and no `use-finished` once `result.json` exists, the
  imprint is `deleted`, or 1,860 s have passed since `use-started`; never while the imprint is `deleting`. It deletes
  the allow file (missing is no error), then appends `use-finished` after checking, inside the receipt's transaction,
  that none exists. The end is the first of I 12's rules 1 to 7 at t_end (`result.json`'s `ended_at`, else the
  earlier of now and `use-started` + 1,860 s), with the report's SHA-256, the deletion's reason, the exit status or
  the error class in `detail`, and `objects` as in `use-started`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("ending,expected", [
    ("report", {"end": "report", "report_sha256": SHA_OF_STUB_REPORT}),
    ("withdrawn_during_run", {"end": "withdrawn"}), ("ended_during_run", {"end": "ended"}),
    ("station_deleted_during_run", {"end": "deleted", "reason": "station"}),
    ("shortened_still_ahead", {"end": "allow changed"}), ("killed_by_signal", {"end": "not evaluable: limit"}),
    ("trails_exit_1", {"end": "failed", "exit": 1}), ("use_raised", {"end": "failed", "error": "ValueError"})])
def test_use_finished_records_how_the_run_ended(tmp_path, ending, expected):
    st, use_id = run_ending(tmp_path, ending)
    st.store.station_imprint_sync(root=st.root)
    finished = [r["record"] for r in receipts(st) if r["record"]["event"] == "use-finished"]
    assert len(finished) == 1 and expected.items() <= finished[0]["detail"].items()
    assert not allow_file(st, use_id).exists()

def test_a_stopped_unit_is_finished_by_the_first_sync_after_1860_s(tmp_path):
    st, use_id = started_without_result(tmp_path)
    st.clock[0] = started_at(st, use_id) + 1859; st.store.station_imprint_sync(root=st.root)
    assert not finished(st, use_id)
    st.clock[0] += 1; st.store.station_imprint_sync(root=st.root)
    assert finished(st, use_id)["detail"]["end"] == "not evaluable: limit"

def test_two_syncs_at_once_write_one_use_finished(tmp_path):
    st, use_id = run_ending(tmp_path, "report")
    sync_in_two_processes(st)
    assert len([r for r in receipts(st) if r["record"]["event"] == "use-finished"]) == 1

def test_a_sync_between_the_two_writes_finishes_nothing(tmp_path):
    st, use_id = run_ending(tmp_path, "report_written_result_not_yet")
    st.store.station_imprint_sync(root=st.root)
    assert not finished(st, use_id)
    write_result(st, use_id, exit=0); st.store.station_imprint_sync(root=st.root)
    assert finished(st, use_id)["detail"]["end"] == "report"

def test_no_use_is_finished_while_deleting(tmp_path):
    st, use_id = run_ending(tmp_path, "report"); force_status(st, "deleting")
    st.store.station_imprint_sync(root=st.root)
    assert not finished(st, use_id)

def test_no_receipt_names_a_road_a_trail_or_a_session(tmp_path):
    st, use_id = run_ending(tmp_path, "report", route=True)   # the stub report names sessions, trails and steps by id
    st.store.station_imprint_sync(root=st.root)
    text = json.dumps([r["record"] for r in receipts(st)])
    assert not any(s in text for s in package_session_ids(st) + stub_report_trail_keys())
    assert {tuple(sorted(r["record"]["detail"]["objects"])) for r in receipts(st) if "objects" in r["record"]["detail"]} == {
        ("count", "imprint", "roads_and_trails")}                 # objects only as counts (I 12)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_uses.py`
Expected: FAIL, `assert 0 == 1` (no `use-finished` written yet).

- [ ] **Step 3: Implement the rules**

Rule 2 needs the tombstone and a `withdrawn` receipt at or before t_end; rule 4 the tombstone and a `deleted`
receipt at or before t_end. Rule 6 covers a negative `exit` and a missing `result.json`. A rerun of a finished use's
command is then refused by `imprint.py use` (its directory exists) and by T's checks 2 and 5.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 20 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/tests/test_imprint_uses.py
git commit -m "Peer: the sync finishes each use once, retiring its allow file and naming its end (I 12, D41, CN7)"
```

### Task 40: The station's Makefile targets and units

**Files:**
- Modify: `Makefile` (variables `IMPRINTS ?= $(HOME)/.engram/imprints`, `USE ?=`, `LANE ?=`; targets `station-imprints`, `station-imprint-admit`, `station-imprint-use`, `station-imprint-use-run`, `station-imprint-delete`; `station-approve` starts the approved imprint's admission unit; `--imprints-dir "$(IMPRINTS)"` on every imprint command)
- Modify: `peer/superyak_peer/__main__.py` (`station-imprint-unit-env`, R20)
- Test: `peer/tests/test_imprint_units.py`

**Interfaces:**
- Consumes: Tasks 29, 34, 36 to 39.
- Produces:
  - `station-imprint-admit ID=<full id>` runs, in order, the peer's `station-imprint-admit-begin`; engram's
    `imprint.py admit --verify-cmd "uv run --locked --project <repo>/peer python -m superyak_peer verify-imprint"`,
    only when begin exited 0 (a refused or already-begun admission is never run, R24); and the peer's
    `station-imprint-sync`, whatever happened before;
  - the admission unit is `systemd-run --user --unit=superyak-imprint-admit-<imprint id> --collect -p MemoryMax=4G
    -p MemorySwapMax=0 -p RuntimeMaxSec=1800 -p TimeoutStopSec=60 make -C <repository> station-imprint-admit
    ID=<imprint id>`, written once in a Make `define` that both of the next two recipes call;
  - `station-approve` runs the peer's approval, prints its output but the `ADMIT:` line, and starts the unit for the
    one id that line names (Task 29), and no other. A docking's approval prints no `ADMIT:` line, so it starts no unit
    and runs no engram command (I 10). When the start fails, it prints "Approved c0a8, but its admission did not
    start. Run make station-imprint-admit." and exits 1; begin never ran, so that command resumes it;
  - `station-imprint-admit` with no ID starts the unit for each id `station-imprints --awaiting-admission` prints
    (never begun, R24), skipping an id whose unit `systemctl --user show -p LoadState --value` reports `loaded`;
  - `station-imprint-use ID=… USE=trail-evaluation [LANE=…]` resolves the full id, `eval`s the output of
    `station-imprint-unit-env`, and starts `systemd-run --user --unit=superyak-imprint-use-<imprint id> --collect
    -p MemoryMax=4G -p MemorySwapMax=0 -p RuntimeMaxSec=1800 -p TimeoutStopSec=60 <env> make -C <repository>
    station-imprint-use-run ID=<imprint id> USE=trail-evaluation [LANE=<lane>]`, printing "Started a use of c0a8 in
    the background; see make station-imprints."; when the unit name is loaded it prints "A use of c0a8 is already
    running; see make station-imprints.", starts nothing and exits 3;
  - `station-imprint-use-run` runs the begin step (R23), `imprint.py use --id --use-id [--lane]`, and the sync;
  - `station-imprint-unit-env` prints `--setenv=ENGRAM_EMBEDDER_SOCKET=<path>` when `$HOME/.config/superyak/runtime.json`
    names an absolute `embedder_socket`, else `-p UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET` (R15); a relative path or
    a non-string exits 2 with "embedder_socket must be an absolute path"; it reads neither `SUPERYAK_RUNTIME_CONFIG` nor
    the Make variable `RUNTIME_CONFIG`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("runtime,expected", [
    ({"embedder_socket": "/run/user/1000/embed.sock"}, ["--setenv=ENGRAM_EMBEDDER_SOCKET=/run/user/1000/embed.sock"]),
    ({}, ["-p", "UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET"]), ({"embedder_socket": None}, ["-p", "UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET"]),
    (None, ["-p", "UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET"])])
def test_the_use_unit_gets_the_socket_exactly_when_runtime_json_names_one(tmp_path, runtime, expected):
    home = fake_home(tmp_path, runtime)
    unit = started_unit(tmp_path, home, env={"SUPERYAK_RUNTIME_CONFIG": str(other_runtime(tmp_path))}, make_vars={"RUNTIME_CONFIG": "/elsewhere"})
    assert unit.env_options == expected
    assert not ("--setenv=ENGRAM_EMBEDDER_SOCKET" in " ".join(unit.argv) and "UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET" in unit.argv)
    assert {"-p", "TimeoutStopSec=60", "MemoryMax=4G", "MemorySwapMax=0", "RuntimeMaxSec=1800"} <= set(unit.argv)
    assert unit.name == f"superyak-imprint-use-{FULL_ID}" and not [a for a in unit.argv if a.startswith("LANE=")]

@pytest.mark.parametrize("bad", [{"embedder_socket": "relative/sock"}, {"embedder_socket": 3}])
def test_a_bad_socket_stops_the_use_before_the_unit(tmp_path, bad):
    done, calls = make_use(tmp_path, fake_home(tmp_path, bad))
    assert done.returncode != 0 and calls == [] and "absolute path" in done.stderr

def test_a_second_use_of_one_imprint_starts_nothing(tmp_path):
    done, calls = make_use(tmp_path, fake_home(tmp_path, {}), loaded=True)
    assert done.returncode == 3 and "A use of c0a8 is already running; see make station-imprints." in done.stdout
    assert [c for c in calls if c[0] == "systemd-run"] == [first_attempt(calls)]

ID1, ID2 = "c0a8f5e2-0000-4000-8000-000000000001", "c0a8f5e2-0000-4000-8000-000000000002"

def test_approve_starts_only_the_approved_imprints_unit(tmp_path):
    calls = make_approve(tmp_path, admit_line=ID2, awaiting=[ID1, ID2], loaded=[f"superyak-imprint-admit-{ID1}"])
    units = [c for c in calls if c[0] == "systemd-run"]
    assert [u[u.index("--user") + 1] for u in units] == [f"--unit=superyak-imprint-admit-{ID2}"]
    assert {"TimeoutStopSec=60", "MemoryMax=4G", "MemorySwapMax=0", "RuntimeMaxSec=1800"} <= set(units[0])
    dock = make_approve(tmp_path / "dock", admit_line=None, awaiting=[ID1])                   # a docking's approval
    assert not [c for c in dock if c[0] == "systemd-run" or "imprint.py" in " ".join(c) or "--awaiting-admission" in c]

def test_the_no_id_resume_skips_a_loaded_unit(tmp_path):
    calls = make_admit_all(tmp_path, awaiting=[ID1, ID2], loaded=[f"superyak-imprint-admit-{ID1}"])
    assert [u[u.index("--user") + 1] for u in calls if u[0] == "systemd-run"] == [f"--unit=superyak-imprint-admit-{ID2}"]

def test_admit_runs_only_when_begin_allows(tmp_path):
    calls = make_admit(tmp_path, FULL_ID, begin_exit=3)                     # refused, or begun already (R24)
    assert [step_of(c) for c in calls] == ["station-imprint-admit-begin", "station-imprint-sync"]

def test_station_imprint_admit_runs_begin_admit_and_sync_in_order(tmp_path):
    lines = dry_run(tmp_path, "station-imprint-admit", f"ID={FULL_ID}")
    assert [step_of(l) for l in lines] == ["station-imprint-admit-begin", "imprint.py admit", "station-imprint-sync"]
    assert all(f"--imprints-dir {IMPRINTS_OF(tmp_path)}" in l for l in lines if "imprints" in l)
```

`make_use`, `make_approve`, `make_admit_all`, `make_admit` and `started_unit` run `make` with `systemd-run`,
`systemctl` and `uv` shimmed on `PATH`, recording their argv, with `HOME` in `tmp_path`, as
`peer/tests/test_station_units.py:89-112` does. The `uv` shim answers `station-approve` with `admit_line`'s
`ADMIT:` line, and `station-imprint-admit-begin` with `begin_exit`. The file starts with `pytestmark =
pytest.mark.skipif(not (REPO / "Makefile").is_file() or not shutil.which("make"), reason="needs the parent repository
Makefile")`, as `test_station_units.py:88` does, so the standalone bundle skips it. The admission command names
`verify-imprint`, which Task 44 builds; these tests are dry runs and shims, so they pass before it exists.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_units.py`
Expected: FAIL, `make: *** No rule to make target 'station-imprint-use'`.

- [ ] **Step 3: Implement the targets**

The repository is `$(CURDIR)`. The unit-env output is shell-quoted with `shlex.quote` and `eval`ed, so a path with a
space stays one argument. "Already running" is decided by `systemctl --user show -p LoadState --value <unit>` being
`loaded` after `systemd-run` fails. Every target that takes `ID=` prints its usage line and exits 2 without it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 11 passed.

- [ ] **Step 5: Commit**

```bash
git add Makefile peer/superyak_peer/__main__.py peer/pyproject.toml peer/tests/test_imprint_units.py
git commit -m "Make: admission and uses as detached units, the socket rule and UnsetEnvironment otherwise (I 10, 12, D29, XN2)"
```

### Task 41: The lighthouse signs receipts

**Files:**
- Modify: `peer/superyak_peer/imprints.py` (`sign_imprint_receipts`, `SIGN_INTERVAL = 60`)
- Modify: `peer/superyak_peer/peer_routes.py:10-25` (a signing task in the lifespan, beside federation's worker, only where the store signs and `imprints_dir` is set)
- Modify: `peer/superyak_peer/app.py` (every imprint read signs first)
- Test: `peer/tests/test_imprint_receipts.py`

**Interfaces:**
- Consumes: Task 23.
- Produces: `sign_imprint_receipts() -> int` (receipts signed, in one transaction, by `self._station_identity(db)`);
  run at start, every `SIGN_INTERVAL` seconds, and before `GET /api/imprints` and `GET /api/imprints/{id}` answer. The
  lighthouse's own receipts (`received`, `shortened`, `withdrawn` and a withdrawal's `deleted`) are signed when
  written. `station-imprints` shows "receipts not yet signed" while any is unsigned. Task 26's `GET
  /api/imprints/{id}` (`{status, held}`, the owner or the requesting ship) gains `permission: {record, signature,
  station_key}`, `receipts`, `calibration_report`, `use_reports` and `keeps`: the content-free `report.json` once
  admitted, each use's `report.json`, and `KEEPS_WORDS` with the date each thing will be removed (I 12, "What the
  owner sees afterwards"). A signing error never stops the loop or a read: the loop logs the error's class (and, for
  the lost-identity refusal of `signatures.refuse_a_lost_identity`, its fixed sentence, which names only the
  identity file) and waits for the next interval; a read answers with the receipts as they are, the unsigned ones
  without a signature.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_receipt_from_a_keyless_command_is_signed_within_the_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(imprints, "SIGN_INTERVAL", 0.05)
    st = admitted_keyless(tmp_path)                     # the admitted receipt written by Store(signing=False)
    with TestClient(lighthouse_app(tmp_path), base_url="http://testserver"):
        wait_until(lambda: unsigned_count(tmp_path) == 0, seconds=2)
    assert verify_station_record(station_key(st), *last_receipt_with_signature(st))

def test_receipts_wait_while_the_lighthouse_is_down_and_are_signed_at_its_start(tmp_path):
    st = admitted_keyless(tmp_path)
    assert "receipts not yet signed" in describe_station_imprints(st)
    with TestClient(lighthouse_app(tmp_path), base_url="http://testserver"):
        pass
    assert unsigned_count(tmp_path) == 0 and "receipts signed" in describe_station_imprints(st)

def test_an_imprint_read_signs_first(tmp_path):
    st = admitted_keyless(tmp_path)
    body = st.voyager.get(f"/api/imprints/{st.request_id}").json()
    assert all(r["signature"] for r in body["receipts"])
    assert not has_key(body["calibration_report"], "content") and "400 days after" in body["keeps"]["text"]
    assert set(body["keeps"]["removed_on"]) == {"row", "permission", "receipts", "tombstone"}

def test_a_signing_error_is_logged_and_the_loop_goes_on(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(imprints, "SIGN_INTERVAL", 0.05); calls = []
    monkeypatch.setattr(Store, "sign_imprint_receipts", fail_first(calls, ValueError("identity.json is missing")))
    with TestClient(lighthouse_app(tmp_path), base_url="http://testserver") as client:
        wait_until(lambda: len(calls) >= 2, seconds=2)               # it ran again after the error
        assert client.get("/api/health").status_code == 200
    assert "ValueError" in caplog.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_receipts.py`
Expected: FAIL, `AttributeError: module 'superyak_peer.imprints' has no attribute 'SIGN_INTERVAL'`.

- [ ] **Step 3: Implement signing**

The lifespan task loops `await asyncio.to_thread(store.sign_imprint_receipts)` then waits `SIGN_INTERVAL` or the stop
event, as federation's worker does (`peer_routes.py:10-19`), with each call inside a `try` that logs and goes on.
Signing changes no record, so the chain never depends on it (D19).

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 10 passed (Task 23's 6 and these 4).

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/superyak_peer/peer_routes.py peer/superyak_peer/app.py peer/tests/test_imprint_receipts.py
git commit -m "Peer: the lighthouse signs key-less commands' receipts at start, every 60 s and before reads (I 12, D19)"
```

### Task 42a: The sweep, retention and restore

(Task 42 is split in two for size, the plan review's N14. The halves are 42a and 42b, so every later task keeps the
number the other two plans cite.)

**Files:**
- Modify: `peer/superyak_peer/imprints.py` (`station_imprint_sweep`)
- Modify: `peer/superyak_peer/__main__.py` (`station-imprint-sweep --data-dir --imprints-dir`)
- Modify: `peer/pyproject.toml` (the sdist list gains `tests/test_imprint_sweep.py`)
- Test: `peer/tests/test_imprint_sweep.py`

**Interfaces:**
- Consumes: Tasks 29, 30, 36, 39.
- Produces: `station_imprint_sweep(*, root: Path) -> dict`, I 12's list in order: deletes past the effective end
  (an `ended` receipt, then the deletion with reason `ended`) and past the upload or review window (reasons
  `upload-expired`, `review-expired`); expires `requested` rows past 10 minutes and removes their staging within the
  hour; runs `station_imprint_sync`; retries `deleting`; reconciles after a restore (a tombstone makes a row
  `deleted`; a row before `deleting` whose files are gone becomes `deleted` with reason `missing` when it has a
  permission and `expired` when it has none; a directory with no live row is removed, with a `deleted` receipt,
  reason `restore`, when the station holds a permission for it); removes every row, permission, receipt and tombstone
  400 days after `deleted`, and every declined or expired row 30 days after it ended. The first step skips `approved`
  rows: the sync it runs next ends them as I 10 says (`failed` `{"term": "end"}`, then reason `ended`; Task 36's rule
  4), so an admission's end always leaves the same receipts.

- [ ] **Step 1: Write the failing tests**

```python
def test_end_dates_and_windows_delete(tmp_path):
    st = several(tmp_path, ["admitted-past-end", "allowed-8-days", "received-8-days", "requested-11-minutes"])
    st.store.station_imprint_sweep(root=st.root)
    assert reasons(st) == {"admitted-past-end": "ended", "allowed-8-days": "upload-expired", "received-8-days": "review-expired"}
    assert status_of(st, "requested-11-minutes") == "expired" and not staging_of(st, "requested-11-minutes").exists()

def test_a_failed_removal_is_retried(tmp_path, monkeypatch):
    st = deleting_after_failure(tmp_path)
    st.store.station_imprint_sweep(root=st.root)
    assert row(st)["status"] == "deleted"

def test_restore_reconciliation(tmp_path):
    st = restored(tmp_path)  # rows: approved with files gone; received with files gone; requested with no permission;
                             # one row with a tombstone; one directory with no row but a permission
    st.store.station_imprint_sweep(root=st.root)
    assert status_reasons(st) == {"approved-gone": ("deleted", "missing"), "received-gone": ("deleted", "missing"),
                                  "requested-gone": ("expired", None), "tombstoned": ("deleted", None)}
    assert not orphan_dir(st).exists() and last_event_of(st, "orphan") == ("deleted", "restore")

def test_nothing_is_kept_past_its_end(tmp_path):
    st = deleted_and_declined(tmp_path)          # a declined row, an expired row and a deleted imprint, all ended now
    st.clock[0] += 30 * 86400 + 1; st.store.station_imprint_sweep(root=st.root)
    assert request_ids(st) == {st.deleted_id}                                # the 30-day rows are gone
    assert receipts_of(st, st.deleted_id) and row(st, st.deleted_id)["permission"] and tombstone_of(st, st.deleted_id).is_file()
    st.clock[0] += 370 * 86400; st.store.station_imprint_sweep(root=st.root)    # 400 days + 1 after the deletion
    assert count_rows(st, "imprint_requests") == count_rows(st, "imprint_receipts") == 0 and not list((st.root / "tombstones").iterdir())

def test_a_leftover_after_a_withdrawal_during_admission_is_removed(tmp_path):
    st = withdrawn_with_leftover_result(tmp_path)
    st.store.station_imprint_sweep(root=st.root)
    assert not (st.root / f"{st.imprint_id}.state").exists()

def test_a_station_backup_holds_no_imprint_file_and_no_request_contents(tmp_path):
    st = admitted(tmp_path, route=True, package_canary=CANARY)
    copy = station_backup(st)                        # the station-backup command into a tmp rotation
    raw = copy.read_bytes()
    assert sorted(p.name for p in copy.parent.iterdir()) == [copy.name]          # only the database copy
    assert CANARY.encode() not in raw and b'"scope"' not in raw and b'"contents"' not in raw
    assert station_restore_test(st).returncode == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_sweep.py`
Expected: FAIL, `AttributeError: 'Store' object has no attribute 'station_imprint_sweep'`.

- [ ] **Step 3: Implement the sweep**

Backups copy only `peer.sqlite3` (`backups.py:167-176`), so no imprint file and no staged request reaches one (D15).
The row's root and the deletion receipts' file paths are paths, not content, and are kept as I 9's table says. Each
sweep step runs in its own transaction and logs a failure without stopping the others.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/superyak_peer/__main__.py peer/pyproject.toml peer/tests/test_imprint_sweep.py
git commit -m "Peer: the sweep: ends, windows, retries, restore reconciliation and retention (I 12, D32)"
```

### Task 42b: The sweep's units and `station-units`

**Files:**
- Create: `peer/systemd/superyak-imprint-sweep.service`, `peer/systemd/superyak-imprint-sweep.timer`
- Modify: `peer/pyproject.toml` (the sdist list's `systemd/` entries, `:45-50`, gain both units)
- Modify: `Makefile` (`STATION_UNITS` gains both; `station-units` enables and `station-units-remove` disables `superyak-imprint-sweep.timer`)
- Modify: `peer/tests/test_station_units.py` (targeted edits: `INSTALLED` and `EXPECTED` gain the two units; the expected `systemctl` calls name the third timer). This is the one existing test this plan changes, because I 15 adds the units to `station-units`.

**Interfaces:**
- Consumes: Task 42a's `station-imprint-sweep`.
- Produces: the service runs `%h/superyak/peer/.venv/bin/python -I -m superyak_peer station-imprint-sweep --data-dir
  %h/.local/share/superyak/lighthouse --imprints-dir %h/.engram/imprints`, `Type=oneshot`,
  `OnFailure=superyak-alert@%n.service`, `MemoryMax=512M`; the timer `OnCalendar=hourly`, `Persistent=true`. Both
  ship in the standalone bundle, whose `tests/test_station_units.py` lists them.

- [ ] **Step 1: Change the existing test**

Make the targeted edits to `peer/tests/test_station_units.py` named under Files, and nothing else in it.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_station_units.py`
Expected: FAIL, `test_units_say_what_the_spec_says` on the two missing files.

- [ ] **Step 3: Write the units and the Makefile lines**

The units follow `peer/systemd/superyak-backup.service` and `.timer`. Add both to the sdist list. `make
station-units` is not run here: installing the timer is gate G5.

- [ ] **Step 4: Run it to verify it passes**

Run: the command of step 2. Expected: PASS, every test in the file (those that need `systemd-analyze` or the
Makefile skip where their tools are missing, as today).

- [ ] **Step 5: Commit**

```bash
git add peer/systemd/superyak-imprint-sweep.service peer/systemd/superyak-imprint-sweep.timer Makefile peer/pyproject.toml peer/tests/test_station_units.py
git commit -m "Peer: the hourly sweep's units, in station-units and the source bundle (I 12, 15)"
```

### Task 43a: The agent's `imprint context` and `send`

(Task 43 split in two, as Task 42 was: 43a and 43b.)

**Files:**
- Create: `agent/superyak_agent/imprint.py`
- Modify: `agent/superyak_agent/__main__.py` (`imprint context|send`), `agent/superyak_agent/station.py` (a raw `PUT` body), `agent/pyproject.toml` (`only-include`)
- Test: `agent/tests/test_imprint_agent.py`

**Interfaces:**
- Consumes: Tasks 24 to 26; `station.StationClient`, `write_private`, `read_json`.
- Produces: `class Imprint(home: Path, client: StationClient, out=print)` with
  - `context() -> dict`: `GET /api/imprints`, written to `home/imprints/context.json` (0600; R7, `operator`
    included);
  - `send(plan_prefix: str, *, wait: int = 540) -> str`: holds an exclusive `fcntl.flock` on
    `home/imprints/<imprint id>/send.lock` (a second send of the plan exits 4 with "Another make imprint-send of this
    plan is running."; RF5); with no `send.json`, posts `request.json`'s bytes and prints the imprint's and the
    request's short ids, the code and the confirm link; saves `send.json`; waits up to 9 minutes, then returns
    `waiting-for-you`; after the yes, sends the manifest, then only the parts the station does not hold, with progress,
    then `complete`, and returns `received`; later runs return the status (`admitted`, `declined`, `denied`, `failed`
    or `deleted` with the reason). Which parts the station holds comes from Task 26's `GET /api/imprints/{id}`;
  - `_drop_local_copy(imprint_id)`: after any call that sees `admitted`, `declined`, `denied`, `failed` or
    `deleted`, it deletes the local `imprint.db` and keeps `manifest.json`, the plan, `objects.json` and `receipts/`
    (D24); Task 43b's calls use it too;
  - the command prints `STATUS: <value>` last and exits 3 for `waiting-for-you`, as `make dock` does.

- [ ] **Step 1: Write the failing tests**

```python
def test_nothing_of_the_package_leaves_before_the_yes(tmp_path):
    station, home = FakeStation(), built_home(tmp_path)
    assert Imprint(home, station.client()).send(PLAN) == "waiting-for-you"
    assert [c.method for c in station.calls] == ["POST", "GET"] and not station.part_bodies

def test_after_the_yes_it_sends_the_manifest_then_the_missing_parts(tmp_path):
    station, home = FakeStation(holds=[0]), built_home(tmp_path, parts=3); station.allow()
    assert Imprint(home, station.client()).send(PLAN) == "received"
    assert station.order() == ["manifest", "part 1", "part 2", "complete"]

def test_later_runs_report_and_drop_the_local_copy(tmp_path):
    station, home = FakeStation(status="admitted"), sent_home(tmp_path)
    assert Imprint(home, station.client()).send(PLAN) == "admitted"
    local = home / "imprints" / IMPRINT_ID
    assert not (local / "imprint.db").exists() and {p.name for p in local.iterdir()} >= {"manifest.json", "objects.json"}

def test_rf5_two_sends_of_one_plan_never_interleave(tmp_path):
    home = built_home(tmp_path)
    with held_lock(home / "imprints" / IMPRINT_ID / "send.lock"):
        done = run_agent(["imprint", "send", "--plan", PLAN], home=home)
    assert done.returncode == 4 and "Another make imprint-send of this plan is running." in done.stdout
    assert not (home / "imprints" / IMPRINT_ID / "send.json").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_agent.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'superyak_agent.imprint'`.

- [ ] **Step 3: Implement the two commands**

The client sends parts with `PUT` and a raw body (`content-type: application/octet-stream`); `StationClient.request`
gains a `raw: bytes | None` argument for that. Claude relays the link and never types the password or ticks the
check (I 13). The plan's own lock is `imprint.py build`'s (Task 19); `send` locks the imprint.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/superyak_agent/imprint.py agent/superyak_agent/__main__.py agent/superyak_agent/station.py agent/pyproject.toml agent/tests/test_imprint_agent.py
git commit -m "Agent: imprint context and send over the ship key, nothing of the package before the yes (I 9, 13, D24)"
```

### Task 43b: The agent's `imprint status`, `withdraw` and `shorten`

**Files:**
- Modify: `agent/superyak_agent/imprint.py`, `agent/superyak_agent/__main__.py` (`imprint status|withdraw|shorten`)
- Test: `agent/tests/test_imprint_agent.py`

**Interfaces:**
- Consumes: Task 43a; Tasks 30, 31, 41.
- Produces, on `Imprint`:
  - `status(imprint_id: str | None = None) -> dict`: with no id, one line per imprint (short id, status, end date,
    last event); with one, it saves each receipt in `home/imprints/<id>/receipts/<seq>-<id>.json`, checks the chain
    (`previous`), prints "not yet signed" for unsigned ones, and prints the calibration report, any use reports and
    what the station keeps with each removal date, from Task 41's detail route;
  - `withdraw(imprint_id: str) -> dict`; `shorten(imprint_id: str, days: int) -> dict`;
  - each calls `_drop_local_copy` when it sees a final status (Task 43a).

- [ ] **Step 1: Write the failing tests**

```python
def test_status_saves_receipts_and_finds_a_broken_chain(tmp_path):
    station, home = FakeStation(receipts=chain(4, drop=2)), sent_home(tmp_path)
    out = Imprint(home, station.client()).status(IMPRINT_ID)
    assert out["chain"] == "broken after receipt 1" and len(list((home / "imprints" / IMPRINT_ID / "receipts").iterdir())) == 3

def test_withdraw_and_shorten_call_the_station(tmp_path):
    station, home = FakeStation(), sent_home(tmp_path)
    Imprint(home, station.client()).withdraw(IMPRINT_ID); Imprint(home, station.client()).shorten(IMPRINT_ID, 30)
    assert station.paths()[-2:] == [f"/api/imprints/{REQUEST_ID}/withdraw", f"/api/imprints/{REQUEST_ID}/shorten"]
    assert station.last_body() == {"valid_until": NOW + 30 * 86400}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_agent.py`
Expected: FAIL, `AttributeError: 'Imprint' object has no attribute 'status'`.

- [ ] **Step 3: Implement the three commands**

Canonical JSON for the chain check is the peer's form, written with the standard library.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/superyak_agent/imprint.py agent/superyak_agent/__main__.py agent/tests/test_imprint_agent.py
git commit -m "Agent: imprint status, withdraw and shorten; receipts saved and their chain checked (I 12, 13)"
```

### Task 44: `verify-imprint`

**Files:**
- Modify: `peer/superyak_peer/imprints.py` (`verify_imprint_dir`)
- Modify: `peer/superyak_peer/__main__.py` (`verify-imprint --dir DIR [--home DIR]` and `verify-imprint --permission FILE`)
- Test: `peer/tests/test_imprint_verify.py`

**Interfaces:**
- Consumes: Task 22's `verify_station_record`; Task 43b's saved receipts.
- Produces: `verify_imprint_dir(dir: Path, *, home: Path) -> dict`: SHA-256 of `station_key` equals every record's
  `station` (`identity.py:94`); every signature verifies; the chain is unbroken from the permission; the key equals the
  one pinned in `home/imprints/station-key.json` at the first imprint, else a loud warning and exit 1 (`peer/API.md:304-309`);
  writes `dir/verified.json` (R21). `--permission FILE` exits 0 exactly when `verify_station_record` accepts the
  file's `{record, signature, station_key}` (R9).

- [ ] **Step 1: Write the failing tests**

```python
def test_a_removed_receipt_is_detected(tmp_path):
    d = saved_imprint(tmp_path, receipts=5); (d / "receipts" / sorted(os.listdir(d / "receipts"))[2]).unlink()
    out = verify_imprint_dir(d, home=tmp_path / "home")
    assert out["chain"] == "broken" and len(json.loads((d / "verified.json").read_text())["verified"]) == 2

def test_a_changed_station_key_is_a_loud_warning_not_a_pass(tmp_path):
    verify_imprint_dir(saved_imprint(tmp_path / "a"), home=tmp_path / "home")
    done = run_peer(["verify-imprint", "--dir", str(saved_imprint(tmp_path / "b", new_key=True)), "--home", str(tmp_path / "home")])
    assert done.returncode == 1 and "station key changed" in done.stdout.lower()

def test_unsigned_receipts_are_not_verified(tmp_path):
    d = saved_imprint(tmp_path, receipts=3, unsigned_last=True)
    verify_imprint_dir(d, home=tmp_path / "h")
    assert len(json.loads((d / "verified.json").read_text())["verified"]) == 2

def test_permission_mode(tmp_path):
    good, bad = permission_file(tmp_path, ok=True), permission_file(tmp_path, ok=False)
    assert run_peer(["verify-imprint", "--permission", str(good)]).returncode == 0
    assert run_peer(["verify-imprint", "--permission", str(bad)]).returncode == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_verify.py`
Expected: FAIL, `ImportError: cannot import name 'verify_imprint_dir' from 'superyak_peer.imprints'`.

- [ ] **Step 3: Implement the verifier**

It reads only local files and holds no key. The pin is written with `O_EXCL` the first time.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 4 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/imprints.py peer/superyak_peer/__main__.py peer/pyproject.toml peer/tests/test_imprint_verify.py
git commit -m "Peer: verify-imprint checks the key, every signature, the chain and the pin (I 12)"
```

### Task 45: `import-receipts` and the owner's use list

**Files:**
- Modify: `engram/imprint.py` (`import_receipts`, the `import-receipts` subcommand)
- Create: `engram/imprint_copies.py` (`copies_held`; standard library only); `engram/pyproject.toml` (`py-modules` gains `"imprint_copies"`)
- Modify: `engram/permission_uses.py` (`Uses.owner_list(..., copies: Sequence[dict] = ())`, the permissions plan's Task 15) and `engram/permission_cli.py` (its `uses` command passes `imprint_copies.copies_held(...)`, the permissions plan's Task 27)
- Test: `engram/tests/test_imprint_import.py`

**Interfaces:**
- Consumes: Task 44's `verified.json`; the permissions plan's `Uses.open`, `UseRow`, `Uses.append_imported`,
  `Uses.owner_list`; P 9.1's imported form.
- Produces:
  - `import_receipts(imprint_id: str, *, home: Path, engram_home: Path) -> int`: with no ledger, does nothing. Else, for
    each verified, not yet imported receipt of a use (`admitted`, or `failed` or `denied` naming a term, for
    admission; `use-finished` or `refused` for a later use), one row per (action, purpose) the use needed (YN6) and
    per batch of at most 512 refs of `objects.json`, in order, with R13's id, `returned` = `{"count", "sha256"}` and
    one `use_subjects` row (owner, ref) per ref; for each action on roads and trails, ⌈N / 100,000⌉ counted rows with
    `returned` = `{"count"}` and one `use_subjects` row (owner, h), N from `roads_and_trails`; when the imprint has
    `route` and the receipt carries no `roads_and_trails`, one row per action on roads and trails with `returned`
    null (YN2). Every row: `ledger_id` = the station's peer id, `ledger_seq` = the receipt's place in its chain,
    `agent` `agent:station-imprints`, `place` and `acting_for` from the terms, `object` null, `copy` = h, `cited` =
    the record ids, `until` = the effective end. Importing twice adds nothing;
  - `imprint_copies.copies_held(home: Path) -> list[dict]`: per local imprint, "copy held at Deep Space 9 (imprint
    c0a8), deletion not confirmed" until a verified `deleted` receipt, then the deletion's date and receipt short id;
    `owner_list(..., copies=...)` puts these lines first. The module reads only `verified.json` and the saved
    receipts with the standard library, so `permission_cli` never imports `imprint`, `calibrate` or numpy.

- [ ] **Step 1: Write the failing tests**

```python
def test_memory_rows_are_per_action_purpose_and_batch(tmp_path):
    led_home, home = ledger_home(tmp_path), imported_home(tmp_path, memories=1300, route=False, receipts=["admitted"])
    import_receipts(IMPRINT_ID, home=home, engram_home=led_home)
    rows = imported_rows(led_home)
    assert Counter((r["action"], r["purpose"]) for r in rows) == {(a, "calibration"): 3 for a in ("imprint", "read", "recall")}
    assert sum(json.loads(r["returned"])["count"] for r in rows if r["action"] == "read") == 1300
    assert subject_rows(led_home, action="read") == 1300

def test_roads_and_trails_rows_split_at_100000_and_are_null_without_a_count(tmp_path):
    led_home, home = ledger_home(tmp_path), imported_home(tmp_path, route=True, receipts=[("admitted", 150_000)])
    import_receipts(IMPRINT_ID, home=home, engram_home=led_home)
    counted = [r for r in imported_rows(led_home) if r["purpose"] == "trail-evaluation" and r["object"] is None and is_copy_subject(r)]
    assert sorted(json.loads(r["returned"])["count"] for r in counted if r["action"] == "imprint") == [50_000, 100_000]
    for receipt in (("denied", None, "end"), ("failed", None, "end")):        # a denial naming a term; ended during admission
        lh, h = ledger_home(tmp_path / receipt[0]), imported_home(tmp_path / receipt[0], route=True, receipts=[receipt])
        import_receipts(IMPRINT_ID, home=h, engram_home=lh)
        assert {r["returned"] for r in imported_rows(lh) if is_copy_subject(r)} == {None}

def test_the_use_list_finds_an_imprint_use_by_a_shipped_ref_and_shows_the_copy(tmp_path):
    led_home, home = ledger_home(tmp_path), imported_home(tmp_path, memories=10, receipts=["admitted"])
    import_receipts(IMPRINT_ID, home=home, engram_home=led_home)
    listed = Uses.open(led_home).owner_list(state_of(led_home), obj=first_ref(home), copies=copies_held(home))
    assert listed.rows and "copy held at Deep Space 9 (imprint c0a8), deletion not confirmed" in render(listed)
    add_verified(home, "deleted"); assert "deletion not confirmed" not in render_list(led_home, home)

def test_importing_twice_adds_nothing_and_no_station_receipt_names_a_memory(tmp_path):
    led_home, home = ledger_home(tmp_path), imported_home(tmp_path, memories=10, receipts=["admitted", "use-finished"])
    first = import_receipts(IMPRINT_ID, home=home, engram_home=led_home)
    assert import_receipts(IMPRINT_ID, home=home, engram_home=led_home) == 0 and first > 0
    assert not any(ref in json.dumps(r) for r in saved_receipts(home) for ref in shipped_refs(home))

def test_the_copies_module_loads_no_numpy():
    done = subprocess.run([sys.executable, "-c", "import imprint_copies, sys; print('numpy' in sys.modules, 'imprint' in sys.modules)"],
                          cwd=ENGRAM, capture_output=True, text=True, check=True)
    assert done.stdout.split() == ["False", "False"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_import.py`
Expected: FAIL, `ImportError: cannot import name 'import_receipts' from 'imprint'`.

- [ ] **Step 3: Implement the import**

The (action, purpose) pairs per use come from Task 35's `NEED_ADMISSION` and the evaluation's `Need`. A refusal's
`refusal` is `{"code", "layer": null, "action"}`, its code mapped by I 8 (`NOT_YET`, `EXPIRED`, else `NO_ALLOW`).
The receipt keys read are Task 23's `DETAIL_KEYS` names (`term` on `denied` and `failed`; R25).

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/imprint.py engram/imprint_copies.py engram/pyproject.toml engram/permission_uses.py engram/permission_cli.py engram/tests/imprint_support.py engram/tests/test_imprint_import.py
git commit -m "Imprints: verified station receipts imported per action, purpose and batch; copy held until deleted (I 12, YN2, YN6)"
```

### Task 46: The owner's Makefile targets

**Files:**
- Modify: `Makefile` (`IMPRINT_ARGS ?=`, `PLAN ?=`, `START ?=`, `LIMIT ?=`, `DAYS ?=`, `ENGRAM_PROJECT_ROOT ?= $(CURDIR)`; targets `imprint-plan`, `imprint-read`, `imprint-send`, `imprint-status`, `imprint-withdraw`, `imprint-shorten`, `imprint-verify`; `.PHONY`)
- Test: `peer/tests/test_imprint_units.py`

**Interfaces:**
- Consumes: Tasks 15, 16, 19, 43a to 45.
- Produces: `imprint-plan` runs `agent imprint context` then `imprint.py plan --project-root "$(ENGRAM_PROJECT_ROOT)"
  $(IMPRINT_ARGS)`, so the default store (I 5.1) resolves from where the owner ran `make`, not from the engram
  checkout that `cd engram` enters (`--store` in `IMPRINT_ARGS` still wins, and the dry run prints the store it
  resolved); `imprint-read
  PLAN=… [START=… LIMIT=…]`; `imprint-send PLAN=…` runs `imprint.py build --plan … --if-needed` then `agent imprint
  send --plan …`; `imprint-status [ID=…]` runs `agent imprint status`, `verify-imprint --dir` for each local imprint and
  `imprint.py import-receipts`; `imprint-withdraw ID=…`; `imprint-shorten ID=… DAYS=…`; `imprint-verify ID=…`. Each
  that needs a variable prints its usage and exits 2 without it.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_owner_targets_run_the_spec_commands(tmp_path):
    assert dry_run(tmp_path, "imprint-plan", "IMPRINT_ARGS=--lanes work --layers episode,semantic --days 90") == [
        AGENT + ["imprint", "context", "--station", STATION],
        ENGRAM + ["plan", "--project-root", str(REPO), "--lanes", "work", "--layers", "episode,semantic", "--days", "90"]]
    assert dry_run(tmp_path, "imprint-send", "PLAN=7c41") == [ENGRAM + ["build", "--plan", "7c41", "--if-needed"],
                                                             AGENT + ["imprint", "send", "--plan", "7c41", "--station", STATION]]
    assert dry_run(tmp_path, "imprint-shorten", "ID=c0a8", "DAYS=30")[-1][-4:] == ["--id", "c0a8", "--days", "30"]

@pytest.mark.parametrize("target", ["imprint-read", "imprint-send", "imprint-withdraw", "imprint-shorten", "imprint-verify"])
def test_targets_without_their_variable_print_usage(tmp_path, target):
    done = make(tmp_path, target)
    assert done.returncode == 2 and done.stdout.startswith(f"Usage: make {target}")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_units.py`
Expected: FAIL, `make: *** No rule to make target 'imprint-plan'`.

- [ ] **Step 3: Implement the targets**

The agent runs as `$(AGENT_PYTHON) agent/run_agent.py`, as `make dock` does; engram as `cd engram && uv run --locked
python imprint.py`; the verifier as `uv run --locked --project peer python -m superyak_peer verify-imprint`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 17 passed (Task 40's 11 and these 6).

- [ ] **Step 5: Commit**

```bash
git add Makefile peer/tests/test_imprint_units.py
git commit -m "Make: the owner's imprint targets, plan to verify (I 13)"
```

### Task 47: The confirm view and Accounts → Imprints

**Files:**
- Modify: `peer/superyak_peer/static/app.js`, `peer/superyak_peer/static/app.css`
- Test: `peer/tests/test_imprint_browser.py`

**Interfaces:**
- Consumes: Tasks 25, 30, 31.
- Produces: the route `/#imprint?code=<code>` (as `/#dock?code=`) renders `imprint_preview`'s fields in words, a box
  with `CHECK_TEXT` that must be ticked, a password field and "Allow" and "Decline" buttons; Accounts → Imprints lists
  the person's imprints (short id, status, end date, last event) with Withdraw and Shorten. When `GET /api/imprints`
  answers 404 (R8), the Accounts section is not shown.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_confirm_view_needs_the_check_and_the_password(imprint_browser):
    page = signed_in(imprint_browser, "sam"); made = imprint_browser.request()
    page.goto(f"{imprint_browser.url}/#imprint?code={made['code']}")
    expect(page.get_by_text("the whole 64-character digest is sent")).to_be_visible()
    expect(page.get_by_text("when either was last recalled")).to_be_visible()
    page.get_by_label("Password").fill(SAM_PASSWORD); page.get_by_role("button", name="Allow").click()
    expect(page.get_by_text("Tick the box")).to_be_visible()
    page.get_by_label(CHECK_TEXT).check(); page.get_by_role("button", name="Allow").click()
    expect(page.get_by_text("Allowed")).to_be_visible()

def test_accounts_imprints_withdraw(imprint_browser):
    page = signed_in(imprint_browser, "sam"); imprint_browser.admitted()
    page.goto(f"{imprint_browser.url}/#accounts"); page.get_by_role("button", name="Withdraw").click()
    page.get_by_role("button", name="Yes, withdraw").click()
    expect(page.get_by_text("deleted")).to_be_visible()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_browser.py`
Expected: FAIL, a Playwright timeout waiting for "the whole 64-character digest is sent".

- [ ] **Step 3: Implement the views**

Follow the docking view's code paths in `app.js`. Every requester-supplied string is set with `textContent`, never
`innerHTML`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 2 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/static/app.js peer/superyak_peer/static/app.css peer/pyproject.toml peer/tests/test_imprint_browser.py
git commit -m "Peer web: the imprint confirm view and Accounts, Imprints (I 9, 12)"
```

### Task 48: The docs

**Files:**
- Modify: `peer/API.md` (the routes of I 9; the two record kinds; that receipts from key-less commands are signed by the lighthouse, beside `:300-302`; `roads_and_trails` as R(I) at t₁ over the scope's lanes, YN1)
- Modify: `engram/CLAUDE.md` (an "Imprints" paragraph under Architecture; Key Files rows for `imprint.py`, `imprint_filter.py`, `imprint_checks.py`)
- Modify: `CLAUDE.md` (the approving section: an `IMPRINT` item is a person's memories; Andy confirms its short id against the owner's machine; `station-approve` returns while admission runs; agents never read `~/.engram/imprints/` except through `imprint.py use`, and never sign or write imprint records by hand)
- Test: `peer/tests/test_imprint_docs.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_docs_name_what_the_spec_requires():
    api, engram_md, claude_md = (REPO / "peer" / "API.md").read_text(), (REPO / "engram" / "CLAUDE.md").read_text(), (REPO / "CLAUDE.md").read_text()
    for route in ("POST /api/imprints", "/api/imprints/{id}/confirm", "/api/imprints/{id}/parts/{n}", "/api/imprints/{id}/withdraw",
                  "imprint-permission", "imprint-receipt", "roads_and_trails"):
        assert route in api, route
    assert "**Imprints:**" in engram_md and "| `imprint.py` |" in engram_md
    approving = claude_md.split("# Approving on the station")[1]
    assert "IMPRINT" in approving and "~/.engram/imprints/" in approving and "imprint.py use" in approving
```

The file starts with `pytestmark = pytest.mark.skipif(not (REPO / "CLAUDE.md").is_file() or not (REPO / "engram" /
"CLAUDE.md").is_file(), reason="needs CLAUDE.md and engram/ from the full repository")`, as
`test_ship_agent.py:10-13` skips, so the standalone peer bundle skips it.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_docs.py`
Expected: FAIL, `AssertionError: POST /api/imprints`.

- [ ] **Step 3: Write the docs**

Plain language, short sentences, as the files already read. The CLAUDE.md lines treat requester text as data, as the
section already says for dockings.

- [ ] **Step 4: Run the test to verify it passes**

Run: the command of step 2. Expected: PASS, 1 passed.

- [ ] **Step 5: Commit**

```bash
git add peer/API.md engram/CLAUDE.md CLAUDE.md peer/pyproject.toml peer/tests/test_imprint_docs.py
git commit -m "Docs: imprint routes and records, the Imprints paragraph, and the approving rule (I 15)"
```

### Task 49: End to end, and the whole suites

**Files:**
- Test: `peer/tests/test_imprint_end_to_end.py` (skipped in the standalone peer bundle, as `peer/tests/test_ship_agent.py:10-13` is)

- [ ] **Step 1: Write the test**

```python
def test_an_imprint_end_to_end(tmp_path):
    # A source store in tmp_path; HOME, ENGRAM_HOME, STATION_DATA and IMPRINTS all under tmp_path.
    src = engram_source(tmp_path, route=False)                                 # via `uv run --project ../engram`
    st = station(tmp_path)                                                     # the app with --imprints-dir
    # agent: a thin test wrapper over Task 43a's Imprint that also reads send.json for the ids it prints
    agent = AgentUnderTest(tmp_path / "superyak", client_over(st.voyager))    # test_ship_agent.py's TestClient transport
    agent.context(); plan = engram(["plan", *FLAGS]); engram(["build", "--plan", plan])
    assert agent.send(plan) == "waiting-for-you"
    confirm_in_browser_api(st.sam, agent.saved())                             # the owner's password and ticked check
    assert agent.send(plan) == "received"
    st.store.station_decide("andy", agent.request_short(), True, imprints_root=st.root)
    st.store.station_imprint_admit_begin(agent.imprint_id(), root=st.root, operator="andy")
    assert engram(["admit", "--id", agent.imprint_id(), "--imprints-dir", str(st.root), "--verify-cmd", PEER_VERIFY]).returncode == 0
    st.store.station_imprint_sync(root=st.root)
    assert agent.send(plan) == "admitted" and not (tmp_path / "superyak" / "imprints" / agent.imprint_id() / "imprint.db").exists()
    raw = (tmp_path / "peer" / "peer.sqlite3").read_bytes()
    assert src.canary.encode() not in raw and b'"scope"' not in raw
    agent.withdraw(agent.imprint_id())
    assert not (st.root / agent.imprint_id()).exists() and (st.root / "tombstones" / f"{agent.imprint_id()}.json").is_file()
    verify = run_peer(["verify-imprint", "--dir", str(agent.local_dir()), "--home", str(tmp_path / "superyak")])
    assert verify.returncode == 0 and agent.status(agent.imprint_id())["last"] == "deleted"
```

- [ ] **Step 2: Run it**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_imprint_end_to_end.py`
Expected: PASS, 1 passed.

- [ ] **Step 3: Run the three suites as the reviewer will** (the commands of "Verification before merge", steps 3, 5
  and 6). Expected: as stated there.

- [ ] **Step 4: Commit**

```bash
git add peer/pyproject.toml peer/tests/test_imprint_end_to_end.py
git commit -m "Imprints: one imprint end to end, from the plan to the tombstone"
```

## Verification before merge (station law section 2)

Section 2 merges a branch only when it was approved in the room, by a fresh reviewer agent started on the Pi that took
no part in writing it, and its test suites pass on the Pi. That reviewer runs these from
`/home/andy/superyak/.worktrees/imprints` and posts its verdict whole in the room ("Superyak: city of AI", 39fd79, or
the room that replaced it), with the branch head and every result below. It never @mentions a ship.

1. **Up to date with main, by a merge, never a rebase.**
   `git merge-base --is-ancestor main HEAD || git merge --no-ff main -m "Merge main into imprints"`
2. **The diff is what the plan says.** `git diff --stat main...HEAD` lists only the files in "File Structure".
   `git diff --name-only --diff-filter=MDR main...HEAD -- engram/tests/ peer/tests/ agent/tests/` prints only
   `peer/tests/test_station_units.py` (Task 42b). `git diff --check main...HEAD` prints nothing.
3. **The engram suite on the Pi, capped:**
   `cd engram && LIGHTHOUSE_REPO="$(cd .. && pwd)/lighthouse" PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked --extra dev python -m pytest -q -ra --tb=short -p no:cacheprovider`
   Expected: every test passes except any that also fail on `main` at the merge base (run the same command there
   first and report both). `-ra` lists two skips this branch adds, and no other new one:
   `test_count_matches_the_trail_functions` (trails.py not built yet; gate G13) and
   `test_pi_budget_a_7500_episode_lane_fits_in_4g` (step 4).
4. **The Pi measurement:**
   `cd engram && ENGRAM_PI_BUDGET=1 PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_imprint_calibrate.py::test_pi_budget_a_7500_episode_lane_fits_in_4g`
   Expected: 1 passed; report the child's peak resident size.
5. **The peer suite on the Pi, capped:**
   `cd peer && PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -ra --tb=short -p no:cacheprovider`
   Expected: every test passes, the browser tests included (Playwright's Chromium is in `~/.cache/ms-playwright` on
   the Pi, checked 2026-10-25), except any that fail on `main` at the merge base.
6. **The agent suite:**
   `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -ra --tb=short -p no:cacheprovider`
   Expected: every test passes.
7. **Off by default, checked by hand:**
   `cd peer && D=$(mktemp -d /var/tmp/imprint-off.XXXX) && uv run --locked python -c "from fastapi.testclient import TestClient; from superyak_peer.app import create_app; c = TestClient(create_app('$D', allowed_origins=['http://testserver']), base_url='http://testserver'); print(c.post('/api/imprints', content=b'{}', headers={'origin': 'http://testserver'}).status_code)"; rm -r "$D"`
   Expected: `404`.
8. **Nothing live was touched.** `systemctl --user list-units 'superyak-imprint-*' --all --no-legend` prints nothing;
   `ls ~/.engram/imprints ~/.superyak/imprints` shows neither exists (or each is as it was before the suites);
   `systemctl --user cat superyak-lighthouse.service | grep -c -- --imprints-dir` prints `0`.
9. **Read the safety-critical code against the spec**, at least: `TABLE_RULES` against I 6.2; `row_key` against I
   5.4; `closed_sessions` and the two log scrubs against I 5.2 and 6.2; L1 to L4 against I 6.4; the 17 checks against I
   10; `decide_use`'s terms, order and codes against I 8; withdrawal's four steps and the sync's rules 1 to 7 against I
   12; `station-imprint-unit-env` against D29 and R15; the confirm against D1 and D27; each receipt's `detail` keys
   against `DETAIL_KEYS` (I 12's table with R25); the admission sync's six rules and `ADMISSION_BOUND` against R24.
10. **Not a Pi suite.** `make check-integration` needs Node.js 24 and pnpm 11.20.0, which the Pi lacks (checked
    2026-10-25). This branch touches no Lighthouse protocol file, so it is run in CI or on the Mac only if a reviewer
    finds one in the diff.

The merging ship then merges as section 2 says. This branch changes peer code that `superyak-lighthouse` runs on the
Pi, so after the merge section 2's restart and check apply (gate G1), and the imprint routes stay off until gate G4.

## Gates (for later)

None of these is run by this plan. Each waits for the person or the plan named.

| # | Gate | Why it waits |
|---|---|---|
| G1 | The merge, under section 2 (above), then the merging ship's restart of `superyak-lighthouse` and its check. | Station law. |
| G2 | Andy accepts the ceiling, the set C and the five items of I 8, as his home's rule for imprints (D38; the re-check's RN7). No imprint is approved before. | His home's consent layer. |
| G3 | `make setup-engram` succeeds on the Pi (aarch64 wheels), or the builder adds an admission environment holding numpy, scipy and sqlite-vec and says so (I 18). | Before the first live imprint. |
| G4 | The lighthouse's installed unit `~/.config/systemd/user/superyak-lighthouse.service` gains `--imprints-dir %h/.engram/imprints`, the same root as the Makefile's `IMPRINTS` and the sweep's unit, and restarts under section 2. This turns the routes on (R8). | A deploy; after G1 and G2. |
| G5 | `make station-units` installs and enables `superyak-imprint-sweep.timer`. | A deploy. |
| G6 | Live checks after G4: the imprint routes answer 404 on the door; a `station-backup` holds no imprint file and no request contents; the lighthouse signs a key-less command's receipt within 60 s. | I 18. |
| G7 | The station's super admin is `andy` (`users.is_super_admin`), since the audience check names the super admin's home. | I 14, I 18. |
| G8 | The CLAUDE.md rule about `~/.engram/imprints/` is on main and in the Pi's checkout. | I 18. |
| G9 | `systemctl --user show-environment` lists no `ENGRAM_` variable. R15 covers the socket variable whatever it holds; this covers the rest. | I 18, D29. |
| G10 | Before the first imprint is sent: the owner's machine is docked (`make dock`), and only the owner types the password and ticks the check. | D1, D27. |
| G11 | Before the first trail-evaluation use: trails step 1 merged and on the Pi; the store's embedding model on the Pi, through the shared service named in `~/.config/superyak/runtime.json` or in `~/.kairos/models/fastembed`, loaded inside the 4 GB cap; the run never downloads (T 7 step 8.2). | I 18; the trails plan. |
| G12 | The trails plan keeps the imprint check in the `trails.py` CLI, out of the pure functions admission calls (YN5), and fixes `_trail_derive`'s calls (R10). | The trails plan. |
| G13 | Before the first imprint with `route` is approved: the trails plan's pure functions are on the Pi, so admission can count R(I); `test_count_matches_the_trail_functions` runs unskipped in that branch's verification. Until then such an admission fails closed with step `count`. | Build order. |
| G14 | I 20, Andy's: which store first and its owner's yes; whether the station-signed browser yes is enough; whether memories that mention other people may move at all, and whether the first store must be work lane only. | Andy's. Each default stands until he answers. |
| G15 | The spec's next revision takes YS1's words (5.4, 9), YN1 (what N means), YN2 ("every imported receipt with no N"), YN3 (`until` required, R14), YN4 (failure names, R11), YN6 (per action and purpose, R13), XN2 (R15) and R8; and, from the plan's review, R24 (a begun admission runs once; a run killed at its limit fails 1,860 s after `decided_at`, and I 10's "after a crash … resumes" covers only an admission that never began), R25 (receipt `detail` keys: `step`, never `check`; `term` on `denied` and `failed`), R7's `operator`, and the two dense sets I 10's list of three missed (`sheaf.measure_all`'s per-semantic matrices, `audit_unchecked_events`' per-event distance matrix; Task 5). | This plan edits no spec. |
| G16 | CN8: a withdrawal or station delete also stopping `superyak-imprint-use-<imprint id>`. | Not built in step 1; it only narrows, and the run's end checks and rules 2 to 4 already record it. |
| G17 | I 17's later steps, XN6 (which item of P's `Req` holds the ceiling in a step-2 ledger), owner-held keys, encrypted imprints. | Later specs. |

## Self-review: every component and test to its task

| Spec item (I 15, I 16) | Task |
|---|---|
| `engram/imprint.py` (with R1's split, `imprint_copies.py` included) | 6 to 19, 32 to 35, 38, 45 |
| `engram/store_identity.py` | 1 |
| `engram/storage.py` | 2 |
| `engram/store_reader.py` | 32 |
| `engram/calibrate.py` | 2 (working-copy flag), 4, 5 |
| `engram/persistence.py` (and `engram/sheaf.py`'s `measure_all`, the review's S2) | 5 |
| `sharing.py`, `federation.py`, `cli.py`, `lighthouse_sheaf.py` | 1 (fork's ancestry), 2, 3 |
| `peer/superyak_peer/identity.py` (and `signatures.py`'s `SIGNED_RECORDS`) | 22, 23 |
| `peer/superyak_peer/imprints.py` | 23 to 27, 29 to 31, 36, 37, 39, 41, 42a, 44 |
| `app.py`, `peer_routes.py` | 24 to 26, 30, 31, 41 |
| `ships.py`, `__main__.py` | 24, 26, 29, 30, 36, 37, 40, 42a, 44 |
| Peer database migration | 23 |
| The lighthouse's installed unit | G4 |
| Peer web app | 47 |
| `peer/systemd/` | 42b |
| `agent/superyak_agent` | 43a, 43b |
| `Makefile` | 40, 42b, 46 |
| `peer/API.md`, `engram/CLAUDE.md`, `CLAUDE.md` | 48 |
| Every table classified | 6 |
| Selection | 7, 8 |
| Down-closure; Induced links | 9 |
| Log rows | 10, 11 (rows), 19 (digest after the plan), 34 (calibration with and without `route`) |
| No footpath without `route` | 10, 17, 19, 33 |
| Source owner (D37) | 8 |
| Recall rows | 11 (scrubs), 21 (touches, XS1) |
| `route_shown` rows | 11 |
| Plan digest from the definitions; Plan digest | 19 (and 12) |
| Rowids; Insertion only; Vectors | 13 |
| Canaries | 20 |
| The checks catch what they claim | 14 |
| Cross-references | 17, 19 |
| Source untouched | 15 |
| Identity and ancestry | 1, 8, 13 |
| Request | 18 (engram), 25 (the confirm view) |
| Routes; Request checks | 24, 26 (another ship gets 404) |
| Confirm | 25 |
| Signing | 22, 25 |
| The ship narrows without editing the owner's records | 27, 30, 31 |
| One ceiling per copy | 27, 28 |
| Manifest before parts; Parts; Complete | 26 |
| Decline and expiry | 25, 42a |
| Approval | 29, 40 (only the approved imprint's unit starts) |
| Admission after the end | 36, 40 |
| The imprints root | 30, 41 |
| Receipts | 23, 41, 44 |
| Withdrawal | 30 |
| Withdrawal during admission | 34, 36, 42a |
| Shortening | 27, 31 |
| Sweep; Backups | 42a (and 42b, the units) |
| Each check fails; vec0 reading | 32, 33 |
| Calibration | 4, 5, 34, 36 (a memory limit or timeout fails, R24) |
| Guards | 2, 3 |
| Uses | 27, 37, 28 (40 touches) |
| Admission stays inside its `Need`; The count of R(I) | 35, 39 (no receipt names a road, a trail or a session) |
| Use ends | 38, 39, 40 |
| The use's unit | 40 |
| Lineage | 1 |
| Owner's use list | 45 |
| Review Focus 1 to 5 | 34 and 36, 26, 14, 8, 19 and 43a |
| Carried YS1, YN1 to YN6, XN2, CN7, CN8, XN6 | 15, 25, 47; 35, 48; 45; 15, 24; 34, 35; G12; 45; 40; 39; G16; G17 |
