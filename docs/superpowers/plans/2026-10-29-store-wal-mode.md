# Reads That Don't Wait (Store WAL Mode) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pure reads stop waiting for writes once the store runs in WAL mode, while every write, and every read with
a side effect, keeps the dispatch gate, and backups and the restore runbook stay correct in either mode.

**Architecture:** A switch command decides the journal mode with SQLite's own lock, under the gate (Task 1). Backup
copies are always single rollback-mode files, and the runbook records and restores the mode (Tasks 2 and 3). A new
`Store.reading()` refuses to nest with the gate in both modes and is gate-free only in WAL; a suite-wide switch runs
every test in WAL too (Task 4). The named pure reads move one at a time, as named helpers, each proved by a gate-held
test on a WAL store and a transitive caller check (Task 5). WAL's own costs are bounded (Task 6), the rollback-mode
assumptions are made explicit (Task 7), and bounded health and the live switch land together as a named act (Tasks 8
and 9).

**Tech Stack:** Python 3.11 (the Pi's system Python) and 3.13+ (venvs), SQLite 3.40.1, FastAPI and Starlette, anyio
(peer); pytest. No new dependencies. `journal_mode.py` is standard-library only (backups.py imports it and stays
stdlib when imported).

**Spec:** `docs/superpowers/specs/2026-10-29-store-wal-mode-design.md` (revision 2 as amended by its re-check,
approved under law section 3). Research: `docs/research/2026-10-29-store-wal-research.md`.

**Revision 2** of this plan applies its fresh review (must-fixes M1 to M7, should-fixes S1 to S13, nits), and is
amended by its re-check (approved with changes, applied as written: the five named services in the unit list, the
rollback-only marks in Task 4, the timers disabled and kept off the watcher lines, Tardis's pinned pull replay test): named
helpers for the inline reads, a transitive caller check and a nesting refusal in both modes, the suite run in WAL too,
the snapshot test, the timers restored at step 8, a per-call wait and an async single-flight for health, and the long
gate holds measured before bounded health merges.

## Global Constraints

- Every write, and every read with any side effect (a commit, a file, a process, shared memory), takes the dispatch
  gate, in every process. Only the functions Task 5 names move to `reading()`.
- `reading()` refuses, in both modes, when entered by a thread that holds the gate or is already inside `reading()`;
  `transaction()` refuses inside `reading()`. It is gate-free only when its connection's `PRAGMA journal_mode` answers
  `wal`; otherwise it is the gate plus a deferred `BEGIN` (`BEGIN IMMEDIATE` is refused on a `query_only` connection).
  It is never held across an `await` or in a yield dependency.
- `synchronous` stays SQLite's default, FULL. Never set NORMAL or OFF.
- `PRAGMA journal_size_limit` = 67108864 (64 MB) on every Store connection except the keeper.
- Checkpoints: `wal_checkpoint(PASSIVE)` hourly, plus `wal_checkpoint(TRUNCATE)` on a connection with a 100 ms busy
  timeout; neither takes the gate. `station-notices` raises a notice when `peer.sqlite3-wal` passes 64 MB.
- The keeper connection runs exactly one statement, `PRAGMA journal_mode`, at open, then nothing; it never holds a
  cursor or a transaction; `check_same_thread=False`.
- `station-journal`: refuses without `peer.sqlite3`, without `dispatch.lock`, or with a symlink among the four names
  (creates nothing); refuses while any station unit is active; opens with a `mode=rw` URI; switches under the gate;
  retries "database is locked" for up to 10 s; checks the PRAGMA's answer; prints the mode before and after; a second
  run changes nothing.
- Backup copies (`_checked_copy`, `_restored_copy`) are set to `journal_mode=DELETE`, and the answer `delete` is checked.
- Health: async; one leader takes the gate through `bounded(3 s)` with a per-call SQLite wait of 3 s; followers await
  the leader's answer; 503 on timeout. It merges with the live switch (Task 9), not before, and only after the longest
  gate holds are measured under 3 s.
- The live switch is a named act: Andy, or a ship with his yes in the room, with everything stopped, measured before
  and after, both posted.

## Review Focus

- One `reading()` is one snapshot (two SELECTs inside it agree across a concurrent commit), and it refuses nesting and
  a held gate in both modes (Task 4).
- A moved function that writes, creates a file or opens its own transaction only on some data (a quiet breakout, a
  received imprint, a failing push peer): its gate-held test seeds those rows and compares a dump hash (Task 5).
- A backup taken while the newest commit is only in the `-wal`, then the station is killed before a checkpoint: the
  copy holds the commit and needs no sidecar (Task 2).
- A production path that reaches a moved function while holding the gate, through a helper or a method passed as a
  value: the transitive caller check finds it; a callback called only by its parameter name it can't see, and there the
  refusal raises at run time in both modes (Tasks 4 and 5).
- Health under a flood while the gate is held for more than 3 s: one gate wait in all, 503s within 3 s, another sync
  route not delayed, and a check arriving mid-wait gets the same answer as the leader (Task 8).

---

### Task 1: `station-journal`, the switch decided by SQLite's lock

**Files:**
- Create: `peer/superyak_peer/journal_mode.py`, `peer/tests/test_journal_mode.py`
- Modify: `peer/superyak_peer/dispatch.py` (`held`), `peer/superyak_peer/__main__.py` (the command), `Makefile` (target
  after `station-restore-reconcile`), `docs/station-restore.md` steps 3 and 8 (the two timers), the existing runbook
  test for steps 3 and 8 in `peer/tests/test_restore.py`

**Interfaces:**
- Produces: `DispatchGate.held(self) -> bool` (this thread's depth > 0).
- Produces: `STATION_UNITS_TO_STOP: tuple[str, ...]`: `superyak-lighthouse`, `superyak-door`, `superyak-ship`,
  `superyak-odo` and `superyak-wormhole` (their unit files live outside the repo), plus every unit in
  `peer/systemd/*.service` except `superyak-alert@`.
- Produces: `header_mode(path: Path) -> str`: `'wal'` when bytes 18-19 are `2 2`, else `'delete'` (a short or
  unreadable header counts as not WAL), read with a plain `open()`.
- Produces: `units_active() -> list[str]`: one `systemctl --user is-active <unit>` per unit; `active`, `activating`,
  `deactivating`, `reloading` and `refreshing` count as active; an exit other than 0 or 3, or a missing line, raises
  ValueError (fail closed).
- Produces: `switch_journal(data_dir: Path, mode: str, *, active=None, retry_seconds=10.0, clock=time.monotonic,
  sleep=time.sleep) -> tuple[str, str]` returning (before, after); `active=None` resolves to `units_active` at call
  time.

- [ ] **Step 1: Write the failing tests** in `test_journal_mode.py`:
  `test_switches_to_wal_and_back_and_a_second_run_changes_nothing` (`('delete', 'wal')`, `header_mode` reads `'wal'`,
  `('wal', 'wal')`, then `('wal', 'delete')` with no `-wal` or `-shm` left); `test_refuses_a_missing_store_and_creates_
  nothing`, `test_refuses_without_dispatch_lock_and_creates_none` and `test_refuses_a_symlink_among_the_four_names`
  (the directory listing unchanged each time); `test_refuses_while_a_unit_is_active` (the message names it, mode
  unchanged); `test_units_active_reads_systemctl` (a stub `systemctl` on PATH printing each state in turn: the five
  active states count, `inactive` and `failed` don't, exit 1 or a missing line raises); `test_every_station_service_is
  _stopped_first` (`STATION_UNITS_TO_STOP` holds the five named services and is a superset of the
  `peer/systemd/*.service` names minus `superyak-alert@`);
  `test_retries_locked_then_gives_up_unchanged`, in both directions (WAL to `delete` blocked by an idle open
  connection; `delete` to WAL blocked by a reader holding `BEGIN` mid-read), with a fake clock: ValueError after 10 s,
  `header_mode` unchanged; `test_switch_holds_the_gate`; `test_cli_prints_before_and_after` (with `active` stubbed
  through the module, not by patching a bound default).
- [ ] **Step 2: Run** `cd peer && uv run --locked python -m pytest -q tests/test_journal_mode.py` — expect failures.
- [ ] **Step 3: Implement** `journal_mode.py` (stdlib only) and `DispatchGate.held`. Connect with a `mode=rw` URI
  built as backups.py's `_read_only` builds its URI (quoting `?`, `#` and `%`), `timeout=0.1`, inside
  `DispatchGate(data_dir / 'dispatch.lock')` (entered only after checking the file exists); on "database is locked" sleep 0.2 s and retry until `retry_seconds`.
  The CLI prints `Journal mode: <before> -> <after>` and exits 1 with the reason on any refusal. Makefile
  `station-journal:` requires `MODE=` and passes `--data-dir "$(STATION_DATA)"`.
- [ ] **Step 4: Runbook steps 3 and 8.** Step 3 gains its own lines, not edits to the watcher lines: for each of
  `superyak-imprint-sweep.timer` and `superyak-lessons-index.timer`, one `systemctl --user is-enabled` call (a missing
  unit prints nothing and exits 1; `is-active` can't tell missing from inactive), recording the enabled ones to
  `$ASIDE/timers.txt`; then each recorded timer is disabled and stopped, with its `.service` stopped, since both are
  `WantedBy=timers.target` and a reboot mid-restore would start them on a half-restored store. They don't use the
  watchers' `list-units --all --plain --no-legend` form, which test_station_units picks out as the one capture line.
  Step 8 gains new lines after the two watcher lines, reading only `timers.txt`, that enable and start each recorded
  timer; the two watcher lines and the `is-active` check line stay byte for byte, so the carry branch's 10.4 copies need
  no change. Extend the existing step 3 and step 8 runbook test with an installed and an absent timer. Guard every new
  line with `[ -d "$ASIDE" ]`.
- [ ] **Step 5: Run** the tests above, `tests/test_station_units.py` and `tests/test_restore.py` — expect PASS.
- [ ] **Step 6: Commit** `station-journal: the journal mode switched under the gate, decided by SQLite's lock`.

### Task 2: Backup copies are single rollback-mode files

**Files:**
- Modify: `peer/superyak_peer/backups.py` (`_checked_copy`, `_restored_copy`, `TEMP_NAME`, `_remove_temporary`,
  `reconcile`)
- Test: `peer/tests/test_backups.py`, `peer/tests/test_restore.py`

**Interfaces:**
- Consumes: `switch_journal`, `header_mode` (Task 1).
- Produces: `_as_single_file(copy: sqlite3.Connection) -> None`: `PRAGMA journal_mode=DELETE`, BackupError(1, ...) unless
  the answer is `delete`.

- [ ] **Step 1: Write the failing tests**: in test_backups.py,
  `test_a_copy_of_a_wal_store_is_one_rollback_file_with_every_commit` (a WAL store, a commit left only in the `-wal` by
  a held open reader, `run_backup`; the copy's `header_mode` is `'delete'`, `integrity_check` is `ok`, the row is
  there, and a `mode=ro` open of the copy leaves no `-wal` or `-shm`); `test_a_stray_tmp_wal_is_pruned` (`TEMP_NAME`
  matches `.peer-x.tmp-wal` and `.peer-x.tmp-shm`, `_remove_temporary` removes both, and `prune` with a `now` past
  TEMP_MAX_AGE removes a stray of each). In test_restore.py,
  `test_restore_test_copies_a_wal_store_as_one_file` and `test_reconcile_refuses_a_wal_flagged_staged_copy` (a staged
  copy switched to WAL is refused as `ReconcileRefused` with the store unchanged), keeping
  `test_reconcile_refuses_a_copy_that_is_not_a_station_database` passing on its 0-byte file.
- [ ] **Step 2: Run** those tests — expect failures.
- [ ] **Step 3: Implement**: `_as_single_file(copy)` after `source.backup(copy, pages=-1)` in both copy paths, before
  the integrity check; `TEMP_NAME = re.compile(r'\.peer-.+\.tmp(?:-journal|-wal|-shm)?')`; `_remove_temporary` covers
  the four names; `reconcile()` refuses `header_mode(db_path) == 'wal'` as a `ReconcileRefused` after `_refuse` (not in
  `refuse_unstaged_db`, whose contract is before any file is opened).
- [ ] **Step 4: Run** `tests/test_backups.py tests/test_restore.py` — expect PASS.
- [ ] **Step 5: Commit** `Backups: every copy is one rollback-mode file, whatever the live store's mode`.

### Task 3: The restore runbook records and restores the mode

**Files:**
- Modify: `docs/station-restore.md` (step 4's record, a new `6b. **` step, the `_replaced` note, and the 10.3 carry
  note gated as below)
- Test: `peer/tests/test_restore.py`

**Interfaces:**
- Consumes: `header_mode`, `switch_journal` (Task 1); the runbook helpers `runbook_block`, `run_runbook`, `step_6`.

- [ ] **Step 1: Write the failing tests**: `test_step_4_records_the_mode_once_the_store_has_moved` (a WAL store:
  after the move `$ASIDE/journal-mode` says `wal`; the fuser branch, where nothing moved, writes no record; a rerun
  after 10.3, with `$ASIDE/peer.sqlite3` gone, keeps `wal`; with no database ever set aside it says `delete`);
  `test_step_6b_switches_back_only_when_recorded` (the `make` shim logs `make station-journal MODE=wal` when `wal` is
  recorded, and nothing for `delete` or no file); `test_replaced_reads_a_set_aside_wal_file_through_its_wal` (a
  set-aside WAL file whose newest commit is only in its `-wal`: `_replaced` answers compared and sees it, and leaves a
  `-shm` in `$ASIDE`); the end-to-end runs (M3): `test_a_restore_from_a_wal_store_through_6b` (steps 3, 4, 5, 6 and 6b
  on a WAL store: the installed store reads `wal` after a real `switch_journal`), `test_a_restore_from_a_rollback_store
  _leaves_it_rollback`, and `test_a_rollback_keeps_the_put_back_files_mode`; and
  `test_the_carry_note_is_there_when_the_carry_is` (skipped unless `backups.carry_pull_nonces` exists; then the
  runbook's 10.3 must name the `-shm` it leaves and its fail-closed case).
- [ ] **Step 2: Run** them — expect failures.
- [ ] **Step 3: Write** step 4's lines: once `peer.sqlite3` is no longer in the data directory, a `python3 -I -c`
  reads bytes 18-19 of `$ASIDE/peer.sqlite3` with `open(..., 'rb')` and writes `wal` or `delete` to
  `$ASIDE/journal-mode` only if that file doesn't exist yet (`delete` when there is no `$ASIDE/peer.sqlite3` at all).
  Step `6b. **Put the journal mode back.**`: run `make station-journal MODE=wal` if the record says `wal`; on a new disk
  without `dispatch.lock`, start and stop the lighthouse once, then 6b again. The `_replaced` note. The 10.3 note lands
  with whichever of this branch and tardis/rollback-carry-nonces merges second (the gated test enforces it).
- [ ] **Step 4: Run** `tests/test_restore.py` — expect PASS.
- [ ] **Step 5: Commit** `Restore runbook: step 4 records the journal mode, step 6b restores it`.

### Task 4: `Store.reading()`, and the suite in WAL too

**Files:**
- Modify: `peer/superyak_peer/db.py` (`reading`, a thread-local depth checked by `transaction`, `transaction`'s
  per-call `wait`), `peer/superyak_peer/signatures.py` (`_station_identity`), `peer/tests/conftest.py` (the suite-wide
  journal switch)
- Create: `peer/tests/test_reading.py`

**Interfaces:**
- Consumes: `DispatchGate.held`, `switch_journal` (Task 1).
- Produces: `Store.reading(self) -> contextmanager[sqlite3.Connection]`; `Store.in_reading(self) -> bool`;
  `Store.transaction(self, *, wait: float | None = None)` (a per-call SQLite busy wait; None keeps the Store's rule).
- Produces: the environment variable `SUPERYAK_TEST_JOURNAL=wal`: an autouse fixture switches every Store a test
  creates to WAL right after it is made; tests that pin rollback mode carry `@pytest.mark.journal('delete')` and are
  skipped in a WAL run. This task marks every such test that exists (the research's list, and Tasks 1 to 3's tests
  that start from a rollback store), so the first WAL run (Step 4) can pass; Task 7 adds their WAL twins.

- [ ] **Step 1: Write the failing tests**: `test_reading_takes_no_gate_in_wal` (another thread holds the gate and an
  open `BEGIN IMMEDIATE` write; a `reading()` SELECT returns within 50 ms); `test_reading_takes_the_gate_in_rollback_
  mode`; `test_one_reading_is_one_snapshot` (on a WAL store it builds itself: two SELECTs in one `reading()` see the same
  count while another thread commits a row between them; in rollback mode the commit would wait, so this test is WAL
  only); `test_an_open_snapshot_does_not_delay_a_gated_commit_in_wal` (a `reading()` held 300 ms;
  an INSERT on another thread commits within 50 ms); `test_reading_refuses_a_held_gate_and_nesting_in_both_modes`
  (parametrized `wal`/`delete`: inside `transaction()`, inside `dispatch_gate`, and inside another `reading()`, each
  raises before connecting); `test_transaction_refuses_inside_reading`; `test_transaction_works_after_a_reading_that_
  raised` (a `reading()` whose `_check_paths` raises, then `transaction()` succeeds); `test_check_paths_refuses_a_
  symlinked_wal`; `test_reading_refuses_sql_writes` (INSERT, UPDATE, DELETE, CREATE TEMP TABLE); `test_reading_maps_
  errors_as_transaction_does`; `test_transaction_wait_is_per_call` (with `wait=3` a held write raises within 3.5 s, and
  the next plain `transaction()` still waits the Store's 30 s rule, checked with `busy_until`); and, on a WAL store,
  `test_identity_is_not_created_without_the_gate` (from inside `reading()` and from a raw connection with no gate,
  `_station_identity(db)` raises and creates no file; with an existing identity.json both load it).
- [ ] **Step 2: Run** `tests/test_reading.py` — expect failures.
- [ ] **Step 3: Implement** `reading()`: first refuse if `self.dispatch_gate.held()` or the thread-local depth is above
  0; then `_check_paths()`; connect; `PRAGMA query_only=ON`, `foreign_keys=ON`, `journal_size_limit=67108864`; read
  `PRAGMA journal_mode`; in `wal`, a deferred `BEGIN` with no gate; otherwise enter `self.dispatch_gate`, compute the
  busy wait after entering it as `_transaction()` does, then `BEGIN`; increment the depth only after both succeed, in a
  `try` whose own `finally` decrements it, so a failure before the increment never decrements; roll back and close in
  `finally`; a test makes `_check_paths` raise, then checks the depth is 0 and that `transaction()` inside a later
  `reading()` still raises; map exceptions as `_transaction()`. The docstring
  forbids holding it across an `await` or in a yield dependency. `transaction()` raises RuntimeError('a write inside
  reading()') when the depth is above 0. `_station_identity`: if identity.json is missing and
  `not self.dispatch_gate.held()`, raise RuntimeError before `load_or_create`. The conftest fixture and marker.
- [ ] **Step 4: Run** `tests/test_reading.py tests/test_signatures.py tests/test_transport.py tests/test_federation_
  pull.py`, then the same with `SUPERYAK_TEST_JOURNAL=wal` — expect PASS in both.
- [ ] **Step 5: Commit** `Store.reading(): one snapshot, gate-free in WAL only, never nested with the gate`.

### Task 5: The named pure reads move, one at a time

**Files:**
- Modify: `peer/superyak_peer/auth.py` (`session`, `session_is_valid`, `device_is_valid`), `ships.py`
  (`ship_key_is_valid`, `station_rooms`, `station_notices`), `connector.py` (`bearer`), `federation.py` (extract
  `_due_rows`, `_pending_count`, `_pull_keys`, `_pull_left` from `sync_once` and `_serve_pull`'s inline reads at
  :341-347, :377-378, :473-476, :494-496), `federate.py` (`_requests`, `pull_cards`, `_pushed`, on the store handle
  each already uses), `room_board.py` (`board_counts`, `board_view`), `layers.py` (`get_layer`, `list_layers`,
  `layer_revisions`), `inbox.py` (a `threading.Lock` around `_inbox_budget`'s shared state)
- Create: `peer/tests/test_reading_moves.py`

**Interfaces:**
- Consumes: `Store.reading()` (Task 4), `switch_journal` (Task 1).
- Produces: `MOVED_READS: tuple[str, ...]` in `test_reading_moves.py`, the qualified names above, written literally.
- Stays gated, by name: `directory`, `station_pending`, health, every lessons function, `active_layer`,
  `shared_layers`, `preview_layer`, `can_deliver_layer`, every lazily writing read, and in `serve_pull` the paired-peer
  read (federation.py:425-426) and the one `BEGIN IMMEDIATE` transaction holding the prune, `_replay_floor`, the
  `pull_nonces` lookup and its INSERT (:433-443), which decide a write.

- [ ] **Step 1: Write the failing tests**: `test_each_moved_read_runs_while_the_gate_and_a_write_are_held`,
  parametrized over `MOVED_READS`. A fixture `busy_wal_store(tmp_path)` builds a WAL store seeded with a quiet
  breakout, a replaced room, a docked ship, a pending docking, a received imprint, a quiet pull peer and a failing push
  peer, a connector grant and token, a board item and a claim, a moderate grant, a local layer and an outbox row, then
  holds the gate and an open write on another thread. Each case runs its call on a worker thread joined with a 2 s
  timeout and asserts it returned within 200 ms, a dump hash of every table is unchanged, and (name, size, mtime_ns) of
  every file in the data directory apart from `-wal` and `-shm` is unchanged.
  `test_no_gated_caller_reaches_a_moved_read`: a transitive by-name walk of `peer/superyak_peer` (functions that call a
  moved name, directly, through a method reference or a lambda, closed transitively) finds none reached from inside a
  `with ...transaction()`, `with ...dispatch_gate`, `bounded(...)`, `with gate or nullcontext()` or `reading()` block,
  with one named allowance for the false positive the review found on main. `test_inbox_budget_is_locked`: the cap
  patched high, an advancing clock and `sys.setswitchinterval(1e-6)`, two threads of 10,000 updates; 20,000 entries.
  `test_one_signed_pull_served_twice_at_once_is_one_replay` (Tardis's pin, in both modes): two threads serve the same
  signed pull request; `_replay_floor` is patched so each caller signals and then waits up to 0.3 s for the other (the
  correct code proceeds after 0.3 s because the second caller can't enter; a barrier would deadlock it); exactly one
  is served, the other answers 409 with the message `Replay`, there is exactly one `pull_nonces` row, and no 500 (a
  split check would reach the primary key as an IntegrityError, or the per-origin lock as `409 Busy`).
- [ ] **Step 2: Run** them — expect every gate-held case to time out at its join, and the budget test to lose entries.
- [ ] **Step 3: Extract** the four federation helpers first (one commit, no behaviour change, existing tests pass).
  Then move each function's `with self.transaction() as db:` to `with self.reading() as db:`, one function per
  commit, rerunning its case and its module's tests each time; any whose case fails stays gated and is named in that
  commit. Add the budget lock.
- [ ] **Step 4: Run** `tests/test_reading_moves.py` and the whole peer suite, then the whole peer suite with
  `SUPERYAK_TEST_JOURNAL=wal` — expect PASS in both.
- [ ] **Step 5: Commit** each move as `reading(): <function> moves off the gate (its gate-held test)`.

### Task 6: WAL's own costs, bounded

**Files:**
- Modify: `peer/superyak_peer/db.py` (`journal_size_limit` in `_transaction`; `keep_open`, `close_keeper`,
  `checkpoint`; `__init__` creating `peer.sqlite3` only when missing, with `O_EXCL`), `peer_routes.py`
  (`federation_lifespan`: the keeper and an hourly checkpoint thread), `door.py` (`create_door`), the federate and
  federation-listen paths in `__main__.py`, `ships.py` (`station_notices`' notice)
- Create: `peer/tests/test_wal_costs.py`

**Interfaces:**
- Consumes: `switch_journal` (Task 1), `reading()` (Task 4).
- Produces: `Store.keep_open(self) -> None`; `Store.close_keeper(self) -> None`; `Store.checkpoint(self) -> tuple[int,
  int, int]` (PASSIVE, then TRUNCATE at a 100 ms busy timeout; TRUNCATE's busy, log and checkpointed);
  `WAL_NOTICE_BYTES = 67108864`.

- [ ] **Step 1: Write the failing tests**: `test_the_keeper_holds_no_transaction_and_truncate_completes`;
  `test_checkpoint_never_waits_behind_a_long_reader` (a `reading()` held 3 s and the gate held on another thread:
  `checkpoint` returns within 400 ms, and a post on a third thread commits within 400 ms); `test_every_store_
  connection_sets_the_size_limit` (inside `transaction()` and `reading()`; the keeper is exempt);
  `test_each_long_running_process_opens_a_keeper` (`create_door`, `federation_lifespan`, `federate` and
  `federation-listen` each call `keep_open`); `test_a_second_store_open_keeps_the_keepers_lock` (with a keeper open, a
  second `Store()` on the same directory, then another process's `switch_journal(..., 'delete')` still gets "locked");
  `test_notices_say_when_the_wal_is_large` (the size stubbed above 64 MB gives one notice naming it).
- [ ] **Step 2: Run** them — expect failures.
- [ ] **Step 3: Implement** as the Interfaces say; the lighthouse's checkpoint thread runs every 3,600 s and stops in
  the lifespan's exit, where the keeper closes too.
- [ ] **Step 4: Run** `tests/test_wal_costs.py tests/test_station_units.py`, in both journal modes — expect PASS.
- [ ] **Step 5: Commit** `WAL's costs bounded: a keeper per process, a non-blocking checkpoint, a size notice`.

### Task 7: Rollback-mode assumptions made explicit

**Files:**
- Modify: `peer/superyak_peer/signatures.py` (the identity check's docstring), `lessons.py` (`_lessons_answer`'s
  docstring), `peer/PROTOCOL.md` (:203-204, :271-272), `docs/superpowers/plans/2026-10-15-owner-mention-fresh.md:333`,
  `docs/superpowers/specs/2026-10-15-owner-mention-fresh-design.md:173`,
  `docs/superpowers/reviews/2026-10-27-federation-pull-recheck.md:260`, `.superyak/checklists/live-station-act.md`
  (`when:` gains `command make station-journal`)
- Test: `peer/tests/test_backups.py` (the crash test), `test_restore.py` (hot-journal tests, `set_aside` and the other
  main-file copies), `test_lessons_index.py` (held-reader tests), `test_federate.py` (:404-422)

**Interfaces:**
- Consumes: the `journal` marker and `SUPERYAK_TEST_JOURNAL` (Task 4).

- [ ] **Step 1: Mark** the rollback-assuming tests `@pytest.mark.journal('delete')` and give each a WAL twin where both
  apply: the held-reader tests' WAL case asserts the commit is not blocked; test_federate's directory hash excludes
  `-wal` and `-shm`; `set_aside` and the other copies use the backup API.
- [ ] **Step 2: Run** the whole peer suite in both modes — expect PASS.
- [ ] **Step 3: Amend** the docs as listed: PROTOCOL.md says gate-free reads in WAL take no part in the promise and
  why; the docstrings say which mode they describe and what a read-only open creates; the owner-mention docs stop
  saying the store already runs in WAL; the recheck's "SD card" says NVMe; the live-station-act list fires on
  `make station-journal`. Run the agent checklist tests.
- [ ] **Step 4: Commit** `Tests and docs say which journal mode they assume`.

### Task 8: Health, bounded and shared (merged with the switch)

**Files:**
- Modify: `peer/superyak_peer/app.py` (`health`, async)
- Create: `peer/tests/test_health.py`

**Interfaces:**
- Consumes: `Store.transaction(wait=...)` (Task 4), `DispatchGate.bounded`.
- Produces: `HEALTH_WAIT_SECONDS = 3.0`.

- [ ] **Step 1: Write the failing tests**: `test_health_answers_503_within_3_s_when_the_gate_is_held`;
  `test_concurrent_checks_share_one_gate_wait` (gate held: 20 concurrent checks answer 503 within 3.5 s, and only one
  entered `bounded`); `test_a_check_arriving_mid_wait_shares_the_leaders_200` (the gate frees at 1 s: the leader and a
  check that arrived at 0.5 s both answer 200); `test_a_flood_does_not_delay_another_sync_route` (with the gate held,
  200 concurrent health checks, and a sync route that takes no gate answers within 100 ms); `test_a_check_after_the_
  gate_frees_answers_200`; `test_health_still_reads_the_store` (no system_meta answers 500, as today).
- [ ] **Step 2: Run** them — expect failures.
- [ ] **Step 3: Implement**: `async def health()`; the single flight is its own asyncio task, created by the first
  check and awaited by every check with `asyncio.shield`, so a request that disconnects never cancels it. The task runs
  the gated read in `run_in_threadpool`, and the function handed to the threadpool enters
  `store.dispatch_gate.bounded(now + 3)` itself (the bound is per thread) before `store.transaction(wait=3)`;
  `GateTimeout` and "locked" answer 503 `{'ok': False}`. Add `health` to the event-loop guard's walk if it isn't
  covered.
- [ ] **Step 4: Run** `tests/test_health.py tests/test_event_loop.py` and agent's route_watch tests — expect PASS.
- [ ] **Step 5: Commit** on its own branch, `Health: bounded at 3 s, one shared wait` (merged in Task 9).

### Task 9: Measure, then the switch as a named act

**Files:**
- Create: `peer/scripts/store_timing.py`
- Modify: `docs/station-restore.md` (a line under step 8 naming the mode the store runs in)

- [ ] **Step 1: Write** `store_timing.py`. It works on a scratch copy made with `station-backup --output` (never `cp`)
  and on a 10x scratch store, and starts a two-peer scratch pair as `peer/scripts/two_peer_check.py` does, for the push.
  It measures:
  - the longest gate holds, by instrumenting `DispatchGate` during an imprint sweep and an hour's replayed traffic;
  - a session check's p50 and p99, including close, while another thread holds a 300 ms write;
  - a post's commit time, idle and busy;
  - the peak `-wal` size, over an hour of normal use and over a read flood;
  - the push's gate-hold time and any transport deadline failures.

  It prints one table.
- [ ] **Step 2: Run** it on main before any switch, and post the table in the room. If any gate hold passes 3 s,
  bounded health doesn't merge: that hold is fixed first, on its own board item.
- [ ] **Step 3: Ask** in the room for Andy's yes to switch the live store, naming the measures and the rollback
  (`make station-journal MODE=delete` with everything stopped). Nothing else in this task runs without it.
- [ ] **Step 4: With the yes:**
  1. Deploy main, with Tasks 1 to 7 and Task 8 merged, to the Pi's checkout.
  2. Make a fresh `ASIDE` named `switch-<time>` (outside `replaced-*`, so no restore step mistakes it), then stop
     everything with runbook step 3's lines.
  3. Run `make station-journal MODE=wal`.
  4. Start the station with step 8's lines, and read the lighthouse's stop time from the unit.
  5. Run `store_timing.py` again, post both tables, and watch health and route-watch for an hour.
- [ ] **Step 5: If any check fails,** stop everything, run `make station-journal MODE=delete`, start with step 8, and
  say so in the room.
