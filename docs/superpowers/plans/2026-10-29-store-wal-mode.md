# Reads That Don't Wait (Store WAL Mode) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pure reads stop waiting for writes once the store runs in WAL mode, while every write, and every read with
a side effect, keeps the dispatch gate, and backups and the restore runbook stay correct in either mode.

**Architecture:** A switch command decides the journal mode with SQLite's own lock, under the gate (Task 1). Backup
copies are always single rollback-mode files, and the runbook records and restores the mode (Tasks 2 and 3). A new
`Store.reading()` is gate-free only in WAL and refuses to nest with the gate (Task 4); the named pure reads move to it
one at a time, each proved by a gate-held test on a WAL store (Task 5). WAL's own costs are bounded (Task 6), the
rollback-mode assumptions in tests and docs are made explicit (Task 7), and bounded health and the live switch land
together as a named act (Tasks 8 and 9).

**Tech Stack:** Python 3.11 (the Pi's system Python) and 3.13+ (venvs), SQLite 3.40.1, FastAPI and Starlette (peer);
pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-29-store-wal-mode-design.md` (revision 2 as amended by its re-check,
approved under law section 3). Research: `docs/research/2026-10-29-store-wal-research.md`.

## Global Constraints

- Every write, and every read with any side effect (a commit, a file, a process, shared memory), takes the dispatch
  gate, in every process. Only the functions Task 5 names move to `reading()`.
- `reading()` is gate-free only when its connection's `PRAGMA journal_mode` answers `wal`; in any other mode it takes
  the gate. It raises when entered by a thread holding the gate; `transaction()` raises inside `reading()`.
- `synchronous` stays SQLite's default, FULL. Never set NORMAL or OFF.
- `PRAGMA journal_size_limit` = 67108864 (64 MB) on every connection the Store opens.
- Checkpoints: `wal_checkpoint(PASSIVE)` hourly, plus `wal_checkpoint(TRUNCATE)` on a connection with a 100 ms busy
  timeout; neither takes the gate. `station-notices` raises a notice when `peer.sqlite3-wal` passes 64 MB.
- The keeper connection runs exactly one statement, `PRAGMA journal_mode`, at open, then nothing; it never holds a
  cursor or a transaction; `check_same_thread=False`.
- `station-journal`: refuses without `peer.sqlite3` or without `dispatch.lock` (creates neither); refuses while any
  station unit is active; switches under the gate; retries "database is locked" for up to 10 s; checks the PRAGMA's
  answer; prints the mode before and after; a second run changes nothing.
- Backup copies (`_checked_copy`, `_restored_copy`) are set to `journal_mode=DELETE`, and the answer `delete` is checked.
- Health: the gate through `bounded(3 s)`, SQLite's busy wait 3 s, 503 on timeout, concurrent checks share one answer.
  It merges with the live switch (Task 9), not before.
- The live switch is a named act: Andy, or a ship with his yes in the room, with everything stopped, measured before
  and after, both posted.

## Review Focus

- A moved function that writes, creates a file or opens its own transaction only on some data (a quiet breakout, a
  replaced room, an imprint mid-removal): its gate-held test seeds those rows, so the branch runs (Task 5).
- A timer that starts a station process during the switch (backup, restore-test, imprint sweep, lessons index): the
  switch either gets SQLite's lock and the answer it asked for, or retries and gives up with the mode unchanged (Task 1).
- A backup taken while the newest commit is only in the `-wal`, then the station is killed before a checkpoint: the
  copy holds the commit and needs no sidecar (Task 2).
- A production path that calls a moved function while holding the gate (inside `_prepare`, `_walk_row` or another
  `transaction()`): it would now raise; a test walks every caller of each moved function (Task 5).
- Health under a flood while the gate is held for more than 3 s: one gate wait in all, 503s within 3 s, and a check
  arriving after the gate frees gets 200 (Task 8).

---

### Task 1: `station-journal`, the switch decided by SQLite's lock

**Files:**
- Create: `peer/superyak_peer/journal_mode.py`
- Modify: `peer/superyak_peer/dispatch.py` (add `held`), `peer/superyak_peer/__main__.py` (the command),
  `Makefile` (target after `station-restore-reconcile`), `docs/station-restore.md` step 3 (the two missing timers)
- Test: `peer/tests/test_journal_mode.py`

**Interfaces:**
- Produces: `DispatchGate.held(self) -> bool` (this thread's depth > 0).
- Produces: `STATION_UNITS_TO_STOP: tuple[str, ...]` (the lighthouse, door, ship, odo, wormhole, federate,
  federation-listen, and the backup, restore-test, imprint-sweep and lessons-index services).
- Produces: `header_mode(path: Path) -> str` returning `'wal'` (bytes 18-19 are `2 2`), `'delete'` (`1 1`) or raising
  ValueError, read with a plain `open()`.
- Produces: `switch_journal(data_dir: Path, mode: str, *, active=units_active, retry_seconds=10.0, clock=time.monotonic,
  sleep=time.sleep) -> tuple[str, str]` returning (before, after); `units_active() -> list[str]` runs
  `systemctl --user is-active` on `STATION_UNITS_TO_STOP` and returns the active ones.

- [ ] **Step 1: Write the failing tests** in `test_journal_mode.py`:
  `test_switches_to_wal_and_back_and_a_second_run_changes_nothing` (a Store made in tmp, then `switch_journal(...,
  'wal', active=lambda: [])` returns `('delete', 'wal')`, `header_mode` reads `'wal'`, a second call returns
  `('wal', 'wal')`, then `'delete'` returns `('wal', 'delete')` and no `-wal` or `-shm` remains);
  `test_refuses_a_missing_store_and_creates_nothing` and `test_refuses_without_dispatch_lock_and_creates_none` (the
  directory's file list unchanged); `test_refuses_while_a_unit_is_active` (`active=lambda: ['superyak-odo.service']`,
  the message names it, mode unchanged); `test_retries_locked_then_gives_up_unchanged` (another connection holds
  `BEGIN IMMEDIATE` for the whole run with a fake clock; ValueError after 10 s; `header_mode` unchanged);
  `test_switch_holds_the_gate` (a thread blocks on `store.dispatch_gate` until the switch returns);
  `test_cli_prints_before_and_after` (`main(['station-journal', '--data-dir', d, '--mode', 'wal'])` with
  `units_active` patched).
- [ ] **Step 2: Run** `cd peer && uv run --locked python -m pytest -q tests/test_journal_mode.py` — expect failures
  (module missing).
- [ ] **Step 3: Implement** `journal_mode.py` and `DispatchGate.held`. Open the store with `sqlite3.connect(path,
  timeout=0.1)`, inside `DispatchGate(data_dir / 'dispatch.lock')` (only after checking the file exists); on
  "database is locked" sleep 0.2 s and retry until `retry_seconds`; compare the PRAGMA's answer with `mode`. The CLI
  prints `Journal mode: <before> -> <after>` and exits 1 with the reason on any refusal. Makefile:
  `station-journal:` with `MODE=` required, `--data-dir "$(STATION_DATA)"`. Runbook step 3 gains
  `superyak-imprint-sweep.timer` and `superyak-lessons-index.timer` in its stop lines.
- [ ] **Step 4: Run** the tests above and `tests/test_station_units.py` — expect PASS.
- [ ] **Step 5: Commit** `station-journal: the journal mode switched under the gate, decided by SQLite's lock`.

### Task 2: Backup copies are single rollback-mode files

**Files:**
- Modify: `peer/superyak_peer/backups.py` (`_checked_copy`, `_restored_copy`, `TEMP_NAME`, `_remove_temporary`,
  `refuse_unstaged_db`)
- Test: `peer/tests/test_backups.py`, `peer/tests/test_restore.py`

**Interfaces:**
- Consumes: `switch_journal`, `header_mode` (Task 1) to make a WAL store in tests.
- Produces: `_as_single_file(copy: sqlite3.Connection) -> None`: runs `PRAGMA journal_mode=DELETE` and raises
  BackupError(1, ...) unless the answer is `delete`.

- [ ] **Step 1: Write the failing tests**: in test_backups.py,
  `test_a_copy_of_a_wal_store_is_one_rollback_file_with_every_commit` (a WAL store, a commit left only in the `-wal`
  by a held open reader, `run_backup`; the copy's `header_mode` is `'delete'`, `integrity_check` is `ok`, the commit's
  row is there, and a `mode=ro` open of the copy leaves no `-wal` or `-shm`);
  `test_a_stray_tmp_wal_is_pruned` (`TEMP_NAME` matches `.peer-x.tmp-wal` and `.peer-x.tmp-shm`, and
  `_remove_temporary` removes both). In test_restore.py,
  `test_restore_test_copies_a_wal_store_as_one_file` (`_restored_copy` from a WAL store gives `'delete'`) and
  `test_reconcile_refuses_a_wal_flagged_staged_copy` (a staged `restored.sqlite3` switched to WAL is refused with the
  store unchanged).
- [ ] **Step 2: Run** those tests — expect failures (copies are `wal`).
- [ ] **Step 3: Implement**: call `_as_single_file(copy)` after `source.backup(copy, pages=-1)` in both copy paths and
  before the integrity check; `TEMP_NAME = re.compile(r'\.peer-.+\.tmp(?:-journal|-wal|-shm)?')`; `_remove_temporary`
  covers the four names; `refuse_unstaged_db` refuses `header_mode(db_path) == 'wal'`.
- [ ] **Step 4: Run** `tests/test_backups.py tests/test_restore.py` — expect PASS.
- [ ] **Step 5: Commit** `Backups: every copy is one rollback-mode file, whatever the live store's mode`.

### Task 3: The restore runbook records and restores the mode

**Files:**
- Modify: `docs/station-restore.md` (step 4's record, a new step 6b, and, once tardis/rollback-carry-nonces is on
  main, the carry's WAL bullet at 10.3)
- Test: `peer/tests/test_restore.py`

**Interfaces:**
- Consumes: `header_mode` (Task 1); the runbook test helpers `runbook_block`, `run_runbook`, `step_6`.

- [ ] **Step 1: Write the failing tests**: `test_step_4_records_the_mode_and_a_rerun_keeps_it` (runs step 4's block
  on a WAL store: `$ASIDE/journal-mode` says `wal`; rerunning with `$ASIDE/peer.sqlite3` already moved keeps `wal`;
  with no database ever set aside it says `delete`); `test_step_6b_switches_back_only_when_recorded` (with `wal`
  recorded it runs the switch, stubbed, and the installed store reads `wal`; with `delete` or no file it prints that
  it does nothing); `test_replaced_reads_a_set_aside_wal_file_through_its_wal` (a set-aside WAL file whose newest
  commit is only in its `-wal`: `_replaced` answers compared and sees the commit, and leaves a `-shm` in `$ASIDE`).
- [ ] **Step 2: Run** them — expect failures (no record, no 6b).
- [ ] **Step 3: Write** step 4's lines (a `python3 -I -c` that opens `$ASIDE/peer.sqlite3` with `open(..., 'rb')`,
  reads bytes 18-19, and writes `wal` or `delete` to `$ASIDE/journal-mode` only if that file doesn't exist yet,
  `delete` when `$ASIDE/peer.sqlite3` is absent); step 6b (run `make station-journal MODE=wal` if the record says
  `wal`; on a new disk without `dispatch.lock`, start and stop the lighthouse once, then 6b again); the note that
  `_replaced` reads through a `-wal` and leaves a `-shm` in `$ASIDE`.
- [ ] **Step 4: Run** `tests/test_restore.py` — expect PASS.
- [ ] **Step 5: Commit** `Restore runbook: step 4 records the journal mode, step 6b restores it`.

### Task 4: `Store.reading()`, gate-free in WAL only

**Files:**
- Modify: `peer/superyak_peer/db.py` (`reading`, a thread-local `_reading` flag checked by `transaction`),
  `peer/superyak_peer/signatures.py` (`_station_identity`)
- Test: `peer/tests/test_reading.py`

**Interfaces:**
- Consumes: `DispatchGate.held` (Task 1).
- Produces: `Store.reading(self) -> contextmanager[sqlite3.Connection]`; `Store.in_reading(self) -> bool`.

- [ ] **Step 1: Write the failing tests**: `test_reading_takes_no_gate_in_wal` (a WAL store; another thread holds
  the gate and an open `BEGIN IMMEDIATE` write; a `reading()` SELECT returns within 50 ms);
  `test_reading_takes_the_gate_in_rollback_mode` (same setup, rollback store: it waits until the holder releases);
  `test_an_open_snapshot_does_not_delay_a_gated_commit_in_wal` (a `reading()` held open 300 ms; a `transaction()`
  INSERT on another thread commits within 50 ms); `test_reading_refuses_while_this_thread_holds_the_gate`;
  `test_transaction_refuses_inside_reading`; `test_reading_refuses_sql_writes` (INSERT, UPDATE, DELETE, CREATE TEMP
  TABLE each raise `sqlite3.OperationalError`); `test_reading_maps_errors_as_transaction_does` (a UTF-8 error is
  Problem 400); `test_identity_is_not_created_without_the_gate` (no identity.json: `_station_identity(db)` from inside
  `reading()` raises and creates no file; with an existing identity.json it loads).
- [ ] **Step 2: Run** `tests/test_reading.py` — expect failures.
- [ ] **Step 3: Implement** `reading()`: `_check_paths()`, connect with the same timeout rule as `_transaction()`,
  `PRAGMA query_only=ON`, `foreign_keys=ON`, `journal_size_limit=67108864`; read `PRAGMA journal_mode`; if `wal`,
  `BEGIN` (deferred) without the gate, else enter `self.dispatch_gate` first; set the thread-local flag; on exit
  `rollback()` and close in `finally`; map exceptions as `_transaction()`. `transaction()` raises
  RuntimeError('a write inside reading()') when the flag is set. `_station_identity`: if identity.json doesn't exist
  and `not self.dispatch_gate.held()`, raise RuntimeError before `load_or_create`.
- [ ] **Step 4: Run** `tests/test_reading.py tests/test_signatures.py tests/test_transport.py` — expect PASS.
- [ ] **Step 5: Commit** `Store.reading(): a gate-free snapshot in WAL, a gated read otherwise; identity needs the gate`.

### Task 5: The named pure reads move, one at a time

**Files:**
- Modify: `peer/superyak_peer/auth.py` (`session`, `session_is_valid`, `device_is_valid`), `ships.py`
  (`ship_key_is_valid`, `station_rooms`, `station_notices`), `connector.py` (`bearer`), `federate.py` (its read
  passes), `federation.py` (`sync_once`'s work list and pending count; `_serve_pull`'s key listing and remainder),
  `room_board.py` (`board_counts`, `board_view`), `layers.py` (`get_layer`, `list_layers`, `layer_revisions`),
  `inbox.py` (a `threading.Lock` around `_inbox_budget`'s shared state)
- Test: `peer/tests/test_reading_moves.py`

**Interfaces:**
- Consumes: `Store.reading()` (Task 4), `switch_journal` (Task 1).
- Produces: `MOVED_READS: tuple[str, ...]` in `test_reading_moves.py`, the qualified names above, literal.

- [ ] **Step 1: Write the failing test**: `test_each_moved_read_runs_while_the_gate_and_a_write_are_held`,
  parametrized over `MOVED_READS`. A fixture `busy_wal_store(tmp_path)` builds a WAL store seeded with a quiet
  breakout, a replaced room, a docked ship, a pending docking, a connector grant and token, a board item, a local
  layer and an outbox row, then holds the gate and an open write on another thread. Each case calls its function with
  arguments from the seed and asserts it returns within 200 ms, the data directory's file list (apart from `-wal` and
  `-shm`) is unchanged, and every table's row count and `total_changes` are unchanged. Also
  `test_no_production_caller_holds_the_gate_around_a_moved_read` (for each moved name, `grep`-style AST walk over
  `peer/superyak_peer`: no call inside a `with ...transaction()` or `with ...dispatch_gate` block), and
  `test_inbox_budget_is_locked` (two threads update the budget 10,000 times each; the total is exact).
- [ ] **Step 2: Run** it — expect every case to time out (still gated).
- [ ] **Step 3: Move** each function's `with self.transaction() as db:` to `with self.reading() as db:`, one function per
  commit, rerunning its case and that module's existing tests each time; any function whose case fails stays gated
  and is named in that commit. Add the budget lock.
- [ ] **Step 4: Run** `tests/test_reading_moves.py` and the whole peer suite — expect PASS.
- [ ] **Step 5: Commit** each move as `reading(): <function> moves off the gate (its gate-held test)`.

### Task 6: WAL's own costs, bounded

**Files:**
- Modify: `peer/superyak_peer/db.py` (`journal_size_limit` in `_transaction`; `keep_open`, `checkpoint`),
  `peer_routes.py` (`federation_lifespan`: the keeper and an hourly checkpoint thread), `door.py`, the federate and
  federation-listen paths in `__main__.py` (each calls `store.keep_open()`), `ships.py` (`station_notices`' notice)
- Test: `peer/tests/test_wal_costs.py`

**Interfaces:**
- Produces: `Store.keep_open(self) -> None` (one connection, `check_same_thread=False`, one `PRAGMA journal_mode`);
  `Store.close_keeper(self) -> None`; `Store.checkpoint(self) -> tuple[int, int, int]` (PASSIVE then TRUNCATE at 100 ms;
  returns TRUNCATE's busy, log and checkpointed); `WAL_NOTICE_BYTES = 67108864`.

- [ ] **Step 1: Write the failing tests**: `test_the_keeper_holds_no_transaction_and_truncate_completes` (after
  `keep_open()` on a WAL store and a post, the keeper's `in_transaction` is False and `checkpoint()` returns busy 0
  and the `-wal` is 0 bytes); `test_checkpoint_never_waits_behind_a_long_reader` (a `reading()` held 3 s: `checkpoint`
  returns within 300 ms, and a post on another thread meanwhile commits within 100 ms); `test_every_connection_sets_the
  _size_limit` (`PRAGMA journal_size_limit` reads 67108864 inside `transaction()` and `reading()`);
  `test_notices_say_when_the_wal_is_large` (a `peer.sqlite3-wal` padded past 64 MB gives one notice naming its size).
- [ ] **Step 2: Run** them — expect failures.
- [ ] **Step 3: Implement** as the Interfaces say; the lighthouse's checkpoint thread runs every 3,600 s and is
  stopped in the lifespan's exit; the keeper closes there too.
- [ ] **Step 4: Run** `tests/test_wal_costs.py` and `tests/test_station_units.py` — expect PASS.
- [ ] **Step 5: Commit** `WAL's costs bounded: a keeper per process, a non-blocking checkpoint, a size notice`.

### Task 7: Rollback-mode assumptions made explicit

**Files:**
- Modify: `peer/superyak_peer/signatures.py` (the identity check's docstring), `lessons.py` (`_lessons_answer`'s
  docstring), `peer/PROTOCOL.md` (:203-204, :271-272), `docs/superpowers/plans/2026-10-15-owner-mention-fresh.md:333`,
  `docs/superpowers/specs/2026-10-15-owner-mention-fresh-design.md:173`,
  `docs/superpowers/reviews/2026-10-27-federation-pull-recheck.md:260`
- Test: `peer/tests/test_backups.py` (the crash test), `test_restore.py` (hot-journal tests, `set_aside` and the other
  main-file copies), `test_lessons_index.py` (held-reader tests), `test_federate.py` (:404-422)

- [ ] **Step 1: Parametrize** the rollback-assuming tests by mode where both apply: the held-reader tests in
  test_lessons_index gain a WAL case asserting the commit is not blocked; the crash and hot-journal tests pin
  `delete` explicitly; test_federate's directory hash excludes `-wal` and `-shm`; `set_aside` and the other copies use
  the backup API.
- [ ] **Step 2: Run** those files in both modes — expect PASS.
- [ ] **Step 3: Amend** the docs: PROTOCOL.md says gate-free reads in WAL take no part in the promise and why; the
  docstrings say which mode they describe and what a read-only open creates; the two owner-mention docs stop saying
  the store already runs in WAL; the recheck's "SD card" says NVMe.
- [ ] **Step 4: Commit** `Tests and docs say which journal mode they assume`.

### Task 8: Health, bounded and shared (merged with the switch)

**Files:**
- Modify: `peer/superyak_peer/app.py` (`health`)
- Test: `peer/tests/test_health.py`

**Interfaces:**
- Produces: `HEALTH_WAIT_SECONDS = 3.0`.

- [ ] **Step 1: Write the failing tests**: `test_health_answers_503_within_3_s_when_the_gate_is_held`;
  `test_concurrent_checks_share_one_gate_wait` (with the gate held, 20 concurrent checks all answer 503 within 3.5 s
  and only one entered `bounded`); `test_a_check_after_the_gate_frees_answers_200`;
  `test_health_still_reads_the_store` (a store whose system_meta is gone answers 500 as today).
- [ ] **Step 2: Run** them — expect failures.
- [ ] **Step 3: Implement**: a single-flight around the gated read (a lock and the in-flight result shared by waiters),
  `store.dispatch_gate.bounded(now + 3)`, the transaction's busy wait 3 s via `busy_until`, `GateTimeout` and
  "locked" answer 503 `{'ok': False}`.
- [ ] **Step 4: Run** `tests/test_health.py` and route_watch's tests in agent — expect PASS.
- [ ] **Step 5: Commit** on its own branch, `Health: bounded at 3 s, one shared wait` (merged in Task 9).

### Task 9: Measure, then the switch as a named act

**Files:**
- Create: `peer/scripts/store_timing.py`
- Modify: `docs/station-restore.md` (a line under step 8 naming the mode the store runs in)

- [ ] **Step 1: Write** `store_timing.py` (on a scratch copy of the live store and a 10x scratch store, as
  `lessons_timing.py` does): a session check's p50 and p99 including close while another thread holds a 300 ms write;
  a post's commit time idle and busy; the peak `-wal` size over a read flood; the push's gate-hold time. It prints one
  table.
- [ ] **Step 2: Run** it on main before any switch; post the table in the room.
- [ ] **Step 3: Ask** in the room for Andy's yes to switch the live store, naming the measures and the rollback
  (`make station-journal MODE=delete` with everything stopped). Nothing else in this task runs without it.
- [ ] **Step 4: With the yes**: merge Task 8's branch; stop everything (runbook step 3's lines); `make station-journal
  MODE=wal`; start the units; read the lighthouse's stop time from the unit; run `store_timing.py` again; post both
  tables; watch health and route-watch for an hour.
- [ ] **Step 5: If any check fails**, stop everything, `make station-journal MODE=delete`, start, and say so.
