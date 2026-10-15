# Station Backups, a Restore Test and Service Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The station's one SQLite file gets a nightly checked copy kept for 8 weeks, a monthly restore test that boots
a throwaway station from the newest copy, a reconcile command that takes back what a restore would revive, and one line
in Ops when a service crashes, gives up, or a backup or restore test fails.

**Architecture:**
- **Two new standard-library modules in `peer/superyak_peer/`, run as trusted CLI commands by systemd, never inside the
  station process (S1):**
  - `backups.py`: `station-backup` (a read-only connection, SQLite's backup API in one step, `integrity_check`, an
    atomic private publish, the 14-day and 8-week rotation, the switched-off copy off the Pi), `station-restore-test`
    (a scratch copy, the reconcile, a loopback `serve`, `/api/health`, the counts), `station-restore-reconcile` (one
    transaction on a staged copy that only takes access away) and the stale-backup notice;
  - `alerts.py`: `station-alert` (systemd's result variables only, checked, rendered once into one line, held back and
    backed off per unit under a flock, queued as a 0600 file in `<data-dir>/alerts/`), the listing that
    `station-notices` appends, and `station-alerts`.
- **The station process gains one route,** `GET /api/health` (S6). `Store.station_notices()` is unchanged; the
  `station-notices` command appends the alerts and the stale notice, read before `Store` is opened (S10, R15).
- **systemd does the scheduling and the watching:** two oneshot services and their timers, an `OnFailure=` template,
  and one drop-in (`ExecStopPost=` and `OnFailure=`) on each of the five services, all in `peer/systemd/` and installed
  only by `make station-units` (S8, S9). Odo posts the alerts through its existing `--notices-command` path; nothing
  under `agent/` changes.

**Tech Stack:** Python 3.11+ standard library (`sqlite3` backup API, `fcntl`, `subprocess`, `urllib`), FastAPI for the
one route, systemd 252 user units, GNU make, pytest.

**Spec:** [`docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md`](../specs/2026-10-14-station-backups-alerts-design.md),
revision 3, approved under D8 at b09ed70, with one line added to S16 and one to R18's tests by Rio Grande's ruling on
the plan review's Q1 (closed breakouts, 2026-10-14; access-removing only, so no new D8 round). It is the binding
authority: where this plan and the spec disagree, the spec wins and the plan is wrong. The spec's two review maps walk every item of its D8 review and re-check. Read the spec's
S1–S16, R1–R18, Error handling and Deploy before Task 1. Line references below are to b09ed70 (base 7cdbb1f).

**Reviews:**
- After each task, a fresh reviewer checks that task's diff against the spec before the next task starts
  (subagent-driven development).
- Before merge, a fresh reviewer with no history of this work reviews the whole branch (Task 12). Merging, restarting
  and checking follow section 2 of the station law and the spec's Deploy section (Task 13). **Deploy steps 4 and 5 wait
  for Andy's go-ahead.**
- This revision of the plan applies a fresh reviewer's plan review of 48678cf in full (2 must-fix, 5 should-fix, 6
  nits), as Rio Grande ruled, and his ruling on its Q1.

**Checked before commit:** every task's edits were applied, as written, to a scratch export of b09ed70 (with main's
`ships.py` and `memos.py`) on the Pi, for 48678cf and again for this revision. The 60 new tests passed (10 in
`test_backups.py`, 20 in `test_restore.py`, 26 in `test_alerts.py`, 3 in `test_station_units.py` and 1 in
`test_ship_agent.py`), as did the rest of the peer suite except the browser tests (501 in all), the agent suite and the
team suite. Every mutation row this revision adds, and most of the earlier ones, failed the test it names. The executor
still runs each red step and each mutation: the check proves the code and tests fit together, not that a later edit
keeps them so.

## Global Constraints

- **Base.**
  - Work in the existing worktree `/home/andy/superyak/.worktrees/backups-alerts`, on a new branch `backups-alerts`
    created from `backups-alerts-spec` (which holds the spec and this plan):
    ```bash
    cd /home/andy/superyak/.worktrees/backups-alerts
    git switch -c backups-alerts
    git merge --no-ff main -m "Merge main into backups-alerts"   # a merge, never a rebase
    ```
    Main was 05ac33c when this plan was written. That merge moves `ships.py` lines 15 and below down by 4 (the
    single-quote mention rule) and touches no other file this plan edits.
  - Never edit `/home/andy/superyak`: the lighthouse and the door run its editable venv.
- **Test commands** (from the worktree root):
  - **Peer:** `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider`
    (with test files or `-k` appended for a targeted run).
  - **Agent:** `cd agent && uv run --locked --extra dev python -m pytest -q`
  - **Team:** `cd team && uv run --locked --extra dev python -m pytest -q`
  - `peer/tests/test_ship_agent.py` runs in the peer suite and imports `agent/` and `team/` from this worktree.
- **Mutation checks** (spec, Testing): run each mutated test with `PYTHONDONTWRITEBYTECODE=1` and delete every
  `__pycache__` before each mutated run (`find peer -name __pycache__ -type d -prune -exec rm -rf {} +`), because
  Python can reuse stale bytecode when a file's size and modification second are unchanged. Revert each mutation with
  `git checkout -- <file>` before the next.
- **Standard library only** in `backups.py` and `alerts.py`: no new dependency, and `uv.lock` doesn't change. They may
  import from `superyak_peer` itself (`auth.token_hash`, `ships.safe_line`); only `restore_test` imports `Store`.
- **No agent change** (S1). Nothing under `agent/` is edited; Odo's watcher posts the alerts as it is.
- **The five unit files in `~/.config/systemd/user/` are never edited** (R16). No test runs `systemctl`, touches
  `~/.config/systemd/user`, `~/.local/share/superyak` or `~/.superyak`, or reads a key file. Every test works in
  `tmp_path`.
- **The interpreter** of every new unit and every `ExecStopPost=` is `%h/superyak/peer/.venv/bin/python -I -m superyak_peer`
  (S9: `-I` keeps a unit's working directory off `sys.path` and ignores `PYTHON*` variables). The throwaway station
  runs `sys.executable -I -m superyak_peer serve`.
- **Paths** (S2, S7, S10, S12):
  - live database: `<data-dir>/peer.sqlite3`; on the Pi `~/.local/share/superyak/lighthouse/peer.sqlite3`;
  - rotation: `~/.local/share/superyak/backups/station/` (0700), the default `--backup-dir`, which is
    `backups/station` beside the data dir (S14);
  - copies: `peer-YYYYMMDDTHHMMSSZ.sqlite3` in UTC, 0600; temporary files `.peer-<stamp>-<pid>.tmp` and their
    `.tmp-journal`; the rotation lock `backups/station/.lock`;
  - the hand-made copies one level up, in `backups/`, are never read, moved or pruned;
  - alert queue: `<data-dir>/alerts/` (0700), one 0600 `<12 hex>.json` per alert, `alerts/rate.json`, the lock
    `alerts/.lock`;
  - scratch: `mkdtemp(prefix='superyak-restore-test-')` in `$XDG_RUNTIME_DIR`, or the system temp dir when unset.
- **Constants.** Use these names and values exactly:

  | Module | Name | Value | Meaning |
  |---|---|---|---|
  | backups | `STAMP` | `'%Y%m%dT%H%M%SZ'` | a copy's UTC time in its name |
  | backups | `KEEP_DAYS` | 14 | newest copy of each of the 14 most recent UTC days that have one |
  | backups | `KEEP_WEEKS` | 8 | newest copy of each of the 8 most recent ISO weeks that have one |
  | backups | `MIN_FREE` | `1 << 30` | free bytes that must be left after the copy (1 GiB) |
  | backups | `RETRY_SECONDS` | 60 | how long the open and the copy are retried (a hot journal after a power cut) |
  | backups | `TEMP_MAX_AGE` | 86400 | temporary files and scratch directories older than a day are leftovers |
  | backups | `STALE_AFTER` | 129600 | 36 hours: the stale-backup notice |
  | backups | `SCRATCH_PREFIX` | `'superyak-restore-test-'` | the restore test's scratch directories |
  | backups | `START_WAIT`, `START_TRIES`, `STOP_WAIT` | 60, 3, 10 | the throwaway station's start and stop |
  | backups | `SEQUENCE_JUMP` | 1_000_000 | step 5 of the reconcile without a replaced file |
  | alerts | `WINDOW`, `MAX_WINDOW` | 1800, 21600 | the first `stopped` window, and its cap (6 hours) |
  | alerts | `GIVE_UPS_PER_DAY` | 6 | the backstop for `down` and `failed` per unit per day |
  | alerts | `LOCK_WAIT` | 5 | seconds before an alert is queued without the lock |
  | alerts | `LISTED_DAYS`, `LISTED_NEWEST`, `KEPT_DAYS` | 7, 20, 30 | the listing and the clean-up |
  | alerts | `SINCE_BEFORE` | 600 | `--since` is 10 minutes before the earliest failure a line reports |
  | alerts | `LINE_LIMIT` | 400 | `safe_line(…, 400)` |

- **Exit codes and their reasons** (spec, Error handling). `backups.REASONS` holds these words verbatim; the CLI prints
  them on stderr and `alerts.failure_reason` puts them in the Ops line:

  | Code | Command | Reason |
  |---|---|---|
  | 10 | backup | `not enough disk space` |
  | 11 | backup | `the copy failed its check; tomorrow's run tries again` |
  | 12 | backup | `the live database may be damaged: don't restart or deploy before reading docs/station-restore.md` |
  | 13 | backup | `the copy off the Pi failed` |
  | 1 | backup | the clock (`the Pi's clock is behind the newest copy`, on stderr) or anything else; the Ops line says `see the log` |
  | 20 | restore test | `there is no backup to test` |
  | 21 | restore test | `the newest copy failed its check` |
  | 22 | restore test | `the restored station did not start` |
  | 23 | restore test | `the restored station is missing data` |
  | 24 | restore test | `the restore's reconcile step failed` |
  | 1 | restore test | anything else: `see the log` |
  | 2 | alert | a run outside systemd, or an invalid unit: nothing queued |
  | 1 | reconcile | a refused FILE or any error in the transaction: the staged copy is unchanged |

- **Fixed texts.** Copy these verbatim (values in angle brackets vary; times are in the Pi's local zone):
  - `stopped`: `Station alert: <name> stopped unexpectedly at <HH:MM> on <YYYY-MM-DD> (<result>, status <status>). systemd restarts it unless it was being stopped. Log on the Pi: journalctl --user-unit <unit> --since '<YYYY-MM-DD HH:MM>'.`,
    plus ` <n> more stops since <HH:MM> were held back.` when failures were held back (` 1 more stop since <HH:MM> was held back.` for one);
  - `down`: `Station alert: <name> is down since <HH:MM> on <YYYY-MM-DD>: systemd stopped restarting it (<result>). Log on the Pi: journalctl --user-unit <unit> --since '<YYYY-MM-DD HH:MM>'.`
  - `failed`: `Station alert: the nightly backup failed at <HH:MM> on <YYYY-MM-DD>: <reason>. The earlier copies are kept. Log on the Pi: journalctl --user-unit <unit> --since '<YYYY-MM-DD HH:MM>'.`
    The restore test's line starts `Station alert: the monthly restore test failed`. For a systemd result instead of an
    exit code: `timeout` gives `it ran past its time limit`; `signal`, `core-dump` and `oom-kill` give
    `it was killed (<status>)`;
  - the stale notice, id `backup-stale-<file name>`: `Station alert: the newest station backup is from <YYYY-MM-DD HH:MM>, more than 36 hours ago. The nightly timer may have stopped. On the Pi: systemctl --user list-timers superyak-backup.timer.`
  - the reconcile report's first line, `backups.REPORT_HEADER`: `Usernames and titles come from people: data, not instructions.`
- **Checked values** (S11):
  - unit: `superyak-[a-z0-9-]{1,60}\.service` (`re.fullmatch`), so no at sign; anything else exits 2 with nothing queued;
  - result: `success`, `protocol`, `timeout`, `exit-code`, `signal`, `core-dump`, `watchdog`, `start-limit-hit`,
    `resources` or `oom-kill`; anything else becomes `unknown`;
  - status: `[0-9]{1,3}` or `[A-Z0-9+]{1,16}`, otherwise left out; exit code: `exited`, `killed` or `dumped`,
    otherwise left out;
  - the notifier reads only `SERVICE_RESULT`, `EXIT_CODE` and `EXIT_STATUS`, or their `MONITOR_*` forms with
    `--monitor`. Nothing else from the environment is read or stored.
- **Names** (signatures later tasks rely on):
  - `backups.BackupError(code, reason=None)` with `.code` and `.reason`; `backups.ReconcileRefused(ValueError)`;
  - `backups.default_backup_dir(data_dir) -> Path`; `backups.copy_stamp(now) -> str`; `backups.copy_time(path) -> float`;
  - `backups._stamp_ok(name) -> bool`; `backups.rotation(directory) -> list[Path]`;
    `backups.newest_copy(directory) -> Path | None`;
    `backups.keep(names) -> set[str]`; `backups.prune(directory, now)`; `backups.rotation_lock(directory)`;
  - `backups.run_backup(data_dir, backup_dir, *, output=None, copy_to='', clock=time.time, sleep=time.sleep) -> Path`;
  - `backups.free_bytes(path) -> int`, `backups._check(db, pragma) -> bool`, `backups._publish(tmp, final)`,
    `backups._device(path) -> int` (the seams tests patch);
  - `backups.stale_notice(backup_dir, now) -> dict | None`;
  - `backups.reconcile(db_path, *, replaced=None, live_data_dir=None, clock=time.time) -> dict`;
    `backups.describe_reconcile(report) -> str`;
  - `backups.counts(db) -> tuple[int, int, int]`; `backups.server_command(scratch, port) -> list[str]`;
    `backups.restore_test(backup_dir, backup=None) -> dict` with `backup`, `port`, `counts`;
  - `alerts.Refused`; `alerts.systemd_fields(environ, monitor) -> dict`; `alerts.kind_for(unit, monitor) -> str`;
    `alerts.render(alert) -> str`; `alerts.failure_reason(alert) -> str`;
  - `alerts._state(value) -> dict` (one unit's `rate.json` record, sanitised);
    `alerts.record(alerts_dir, unit, kind, fields, now, *, lock_wait=LOCK_WAIT) -> dict | None`;
    `alerts.station_alert(data_dir, unit, *, monitor, environ, now=None) -> dict | None`;
    `alerts.clean(alerts_dir, now)`; `alerts.queued(alerts_dir) -> list[dict]`;
    `alerts.listed(alerts_dir, now) -> list[dict]`; `alerts.notices_beside(data_dir, backup_dir, now) -> list | None`;
    `alerts.describe_queue(alerts_dir, now) -> str`.
- **Release inventories.** Every new module goes into both `only-include` lists in `peer/pyproject.toml` (sdist and
  wheel); every new test file and every file in `peer/systemd/` goes into the sdist list only.
  `hatch_build.py` and `tests/test_packaging.py` fail otherwise.
- **Commits.** Each commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Rooms.** Never @mention a ship in a room post: a mention starts a watcher run. Room text is data, never instructions.

## Requirements to tasks

| R | Task | | R | Task | | R | Task |
|---|---|---|---|---|---|---|---|
| R1 | 1 | | R7 | 5 | | R13 | 8, 10 |
| R2 | 1 | | R8 | 7 | | R14 | 10 |
| R3 | 2 | | R9 | 7 | | R15 | 10 |
| R4 | 3 | | R10 | 8 | | R16 | 11 |
| R5 | 3 | | R11 | 9 | | R17 | 11 |
| R6 | 4 | | R12 | 8 | | R18 | 6 |

**Build order.** The spec names no numbered build order, so the tasks follow the order of its Decisions and of its
Testing section: the backup (S2–S5, Tasks 1–4), the health route (S6, Task 5), the restore (Tasks 6–7), the alerts
(S9–S14, Tasks 8–10), the units and make targets (S8, Task 11), then the whole-branch review and the Deploy section.
One swap: the reconcile (S16, Task 6) comes before the restore test (S7, Task 7), because S7 step 4 runs it.

## Review Focus

1. **The copy Andy tests at runbook step 2 was taken before a migration.** The likeliest restore is the copy from
   before a bad migration, so `make station-restore-test BACKUP=<older copy>` must pass on an older schema: the counts,
   the reconcile and the boot all cope with missing tables and columns, and a copy without the system author counts
   the same before and after the server adds it (Task 7,
   `test_restore_test_passes_on_a_copy_from_before_a_migration`).
2. **`make station-units` and `make station-units-remove` run on Andy's real unit directory.** They install and remove
   only the five unit files and the `50-alerts.conf` drop-ins (including on a `superyak-ship-*` watcher's unit), never
   one of Andy's own drop-ins, and the first refuses without a station database (Task 11,
   `test_station_units_install_and_remove_only_their_own_files`, with `systemctl` shimmed on `PATH`).
3. **The restore test is stopped mid-boot**, by systemd's `TimeoutStartSec=` or by hand. SIGTERM or SIGHUP leaves no
   server running and no scratch directory (Task 7, `test_a_stopped_restore_test_leaves_no_server_and_no_scratch`).
4. **A power cut leaves a hot journal beside the live database.** The read-only backup retries for 60 s, then exits 1
   ("see the log"), never 12 ("may be damaged"); it never changes the live file or its journal, which the lighthouse
   recovers (Task 3, `test_a_hot_journal_after_a_power_cut_is_retried_never_called_damage`).
5. **An empty or foreign file in the alert queue** (a power cut after a rename, a hand edit, `rate.json` garbled).
   `station-notices` skips it and still lists everything else, and an at sign in a hand-edited text never reaches Ops,
   because Odo runs the command with `check=True` and one crash would silence every notice (Task 10,
   `test_a_junk_file_in_the_queue_is_skipped_not_fatal`).

## Decisions this plan makes where the spec is silent

- **A deploy step 0** backs up the database before the merge, as earlier Deploy sections do, so steps 1–7 keep the
  spec's numbers (Task 13).
- **Exit 1 in the Ops line.** The backup's exit 1 means either the clock or anything else, so its Ops line says `see
  the log`; the clock's words, naming the future-dated copy and what to do, go to the journal.
- **"A full window with no failure"** (S12) is measured from the unit's last `stopped` failure, queued or held, against
  the current window's length. `down` and `failed` don't extend a `stopped` burst. A `down` or `failed` line held by the
  backstop is added to the same held count, "counted like stops".
- **The restore test retries the start only when the server exits during start-up**; a server that runs for 60 s
  without answering gives 22 at once.
- **Alert and rate files are fsynced before their rename,** so a power cut can't leave an empty file under a final
  name.
- **The reconcile:** spaces are reported like rooms (short id and name); a peer's short id is 12 hex characters; a
  sequence the replaced file lacks is raised by 1,000,000 (fail closed); a law layer active in the replaced file but
  missing from the copy is reported too.
- **The reconcile fails closed on Andy's likeliest slips at runbook step 5** (plan review M2): a `--db` with a second
  name (a hard link, which could be the live file), a `--replaced` that is the staged copy itself, and a replaced file
  whose `events` sequence is lower than the copy's, which means `DB=` and `REPLACED=` were swapped. Equal sequences pass.
- **A room or space that loses a member in the reconcile** has its `epoch` or `version` raised by one, as
  `remove_participant` and `change_space_member` do, so a delivery queued under the old epoch is refused (review N6).
- **The reconcile says when no active super admin remains** after it lowered one, and points at
  `bootstrap-super-admin` (review N5).
- **A name that matches the copy pattern but isn't a real time** (`peer-20261399T000000Z.sqlite3`) is not a rotation
  copy: never read, pruned or counted as newest (review S1). A `rate.json` record of the wrong shape is sanitised field
  by field (review S2). The notifier cleans old alert files on every run, clean stops included (review N1).
- **`make station-units` never changes the mode of a directory that exists** (review N2).
- **`make station-units`** enables the timers with `--now` (Deploy step 4 expects `list-timers` to show them), and
  writes the drop-in on every `superyak-ship-*.service` present as well (Known limits). The by-hand make targets run
  `uv run --locked --project peer`, as the other `station-*` targets do; the units run the venv's interpreter with `-I`.
- **The restore-test unit** shares the backup unit's shape as S8 lists it (oneshot, `OnFailure=`, the working
  directory, `-I`), without `Nice=` or `IOSchedulingClass=`.
- **Report and output wording** the spec doesn't fix: the reconcile's lines after its header, `Restore test passed: …`,
  and `station-alerts`' "No alerts are queued." and "N stops held back since …", which Deploy steps 4 and 5 check.
- **The `peer/systemd/` files go into the sdist** so `test_station_units.py` passes in the standalone bundle; the
  `systemd-analyze verify` half is its own test, skipped where the Pi's venv interpreter doesn't exist.

## Files

- **Create (peer):**
  - `peer/superyak_peer/backups.py`: the backup, the rotation, the copy off the Pi, the stale notice, the reconcile and
    the restore test;
  - `peer/superyak_peer/alerts.py`: the notifier, holding back, the queue, the listing and `station-alerts`;
  - `peer/systemd/superyak-backup.service`, `superyak-backup.timer`, `superyak-restore-test.service`,
    `superyak-restore-test.timer`, `superyak-alert@.service`, `50-alerts.conf`.
- **Modify (peer):**
  - `peer/superyak_peer/__main__.py`: six commands (`station-backup`, `station-restore-test`,
    `station-restore-reconcile`, `station-alert`, `station-alerts`, and `station-notices --backup-dir`);
  - `peer/superyak_peer/app.py`: `GET /api/health`;
  - `peer/pyproject.toml`: both inventories;
  - `peer/API.md`, `peer/README.md`.
- **Create (peer tests):** `peer/tests/test_backups.py`, `peer/tests/test_restore.py`, `peer/tests/test_alerts.py`,
  `peer/tests/test_station_units.py`.
- **Modify (peer tests):** `peer/tests/test_ship_agent.py`: `test_odo_posts_a_queued_alert_in_ops_once`.
- **Create (repo):** `docs/station-restore.md`, the restore runbook.
- **Modify (repo):** `Makefile`: `station-backup`, `station-restore-test`, `station-restore-reconcile`,
  `station-alerts`, `station-units`, `station-units-remove`.
- **Unchanged:** everything under `agent/`; `peer/superyak_peer/ships.py` (`Store.station_notices()`, R15); the
  door; the five unit files.

---
## The backup (S2–S5)

### Task 1: The checked copy: read-only, one step, private and whole (R1, R2)

**Files:**
- Create: `peer/superyak_peer/backups.py`
- Modify: `peer/superyak_peer/__main__.py:206` (a `station-backup` parser after the `station-unbridge` loop) and
  `:271-272` (its dispatch, after `station-notices`)
- Modify: `peer/pyproject.toml` (`superyak_peer/backups.py` in both lists after `auth.py`; `tests/test_backups.py`
  in the sdist list after `tests/test_auth.py`)
- Test: `peer/tests/test_backups.py` (new)

**Interfaces:**
- Consumes: `Store` (tests only), `__main__.main`.
- Produces: `backups.BackupError`, `REASONS`, `SEE_LOG`, `STAMP`, `default_backup_dir`, `copy_stamp`, `_read_only`,
  `_check`, `_fsync`, `_live_database`, `_rotation_dir`, `rotation_lock`, `_remove_temporary`, `_checked_copy(database,
  tmp, clock, sleep)`, `_publish(tmp, final)`, `run_backup(data_dir, backup_dir, *, clock, sleep) -> Path`; the CLI
  `station-backup --data-dir DIR [--backup-dir DIR]`. Tasks 2–4 extend `run_backup` and `_checked_copy`.

- [ ] **Step 1: Write the failing tests**

Create `peer/tests/test_backups.py`:

```python
"""Station backups (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S2–S5; R1–R6). Every test
works on a station in tmp_path; none touches ~/.local/share/superyak."""
import calendar
from contextlib import closing
import datetime
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import time
import pytest
from superyak_peer import backups
from superyak_peer.__main__ import main as cli
from superyak_peer.db import Store

HOLD = ('import fcntl, os, sys, time\n'
        'fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR)\n'
        'fcntl.flock(fd, fcntl.LOCK_EX)\n'
        'print("held", flush=True)\n'
        'time.sleep(60)\n')


def station(tmp_path):
    """A small live station in tmp_path/lighthouse, and where its rotation goes: backups/station beside it."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    jenn = store.create_user('jenn', 'Jenn', 'long-password-jenn')
    room = store.create_room(andy['id'], 'Ops', [jenn['id']])
    store.send_message(andy['id'], room['id'], 'm1', 'hello')
    return store, tmp_path / 'backups' / 'station'


def backup(store, rotation, *extra):
    """station-backup as the timer runs it; returns its exit code."""
    try:
        cli(['station-backup', '--data-dir', str(store.data_dir), '--backup-dir', str(rotation), *map(str, extra)])
    except SystemExit as stopped:
        return stopped.code
    return 0


def names(directory):
    return sorted(p.name for p in directory.iterdir() if p.name != '.lock')


def ok(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]


def test_backup_copies_committed_data_from_a_read_only_connection(tmp_path, monkeypatch):
    """R1: the backup API from a mode=ro connection, in one step; never Store, never the dispatch gate."""
    store, rotation = station(tmp_path)
    live = store.db_path
    before, mtime = live.read_bytes(), live.stat().st_mtime_ns
    real_connect, opened = sqlite3.connect, []

    def connect(target, *args, **kwargs):
        opened.append((str(target), kwargs.get('uri', False)))
        return real_connect(target, *args, **kwargs)

    writer = real_connect(live, isolation_level=None)
    writer.execute('BEGIN IMMEDIATE')
    writer.execute("INSERT INTO login_attempts VALUES('uncommitted', 1, 0)")
    monkeypatch.setattr(sqlite3, 'connect', connect)
    monkeypatch.setattr(Store, '__init__', lambda *a, **k: pytest.fail('station-backup constructed Store'))
    try:
        assert backup(store, rotation) == 0
    finally:
        writer.execute('ROLLBACK')
        writer.close()
    [copy] = rotation.glob('peer-*.sqlite3')
    assert ok(copy)
    with closing(real_connect(copy)) as db:
        assert db.execute("SELECT count(*) FROM login_attempts WHERE key='uncommitted'").fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM messages').fetchone()[0] == 1
    assert live.read_bytes() == before and live.stat().st_mtime_ns == mtime
    assert not Path(f'{live}-journal').exists()
    live_opens = [o for o in opened if str(live) in o[0]]
    assert live_opens and all(target.endswith('?mode=ro') and uri for target, uri in live_opens)
    # A second run while another process holds dispatch.lock finishes too, so the backup never takes the gate.
    holder = subprocess.Popen([sys.executable, '-c', HOLD, str(store.data_dir / 'dispatch.lock')], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'held'
        again = subprocess.run([sys.executable, '-m', 'superyak_peer', 'station-backup', '--data-dir', str(store.data_dir),
                                '--backup-dir', str(rotation)], capture_output=True, text=True, timeout=30)
    finally:
        holder.kill()
        holder.wait()
    assert again.returncode == 0, again.stderr


def test_copies_are_private_checked_and_appear_whole(tmp_path, monkeypatch):
    """R2: 0600 in a 0700 directory; a failure after the temporary write leaves neither a final nor a temporary file."""
    store, rotation = station(tmp_path)
    assert backup(store, rotation) == 0
    [copy] = rotation.glob('peer-*.sqlite3')
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600 and stat.S_IMODE(rotation.stat().st_mode) == 0o700
    assert ok(copy) and re.fullmatch(r'peer-\d{8}T\d{6}Z\.sqlite3', copy.name)
    copy.unlink()

    def fail(tmp, final):
        raise OSError('injected after the temporary write')

    monkeypatch.setattr(backups, '_publish', fail)
    assert backup(store, rotation) == 1
    assert names(rotation) == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_backups.py`
Expected: FAIL at collection with `ImportError: cannot import name 'backups' from 'superyak_peer'`.

- [ ] **Step 3: Create `peer/superyak_peer/backups.py`**

```python
"""Station backups and the restore (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S2-S5, S7,
S14, S16). Trusted local commands, standard library only. station-backup never constructs Store and never takes the
dispatch gate: it reads the live file through a read-only connection, and SQLite's backup API copies a consistent
snapshot of committed data on its own (S2)."""
from contextlib import closing, contextmanager
import fcntl
import os
from pathlib import Path
import sqlite3
import time

STAMP = '%Y%m%dT%H%M%SZ'
SEE_LOG = 'see the log'
REASONS = {  # spec, Error handling: the words the CLI prints and the Ops line carries
    10: 'not enough disk space',
    11: "the copy failed its check; tomorrow's run tries again",
    12: "the live database may be damaged: don't restart or deploy before reading docs/station-restore.md",
    13: 'the copy off the Pi failed',
    20: 'there is no backup to test',
    21: 'the newest copy failed its check',
    22: 'the restored station did not start',
    23: 'the restored station is missing data',
    24: "the restore's reconcile step failed",
}


class BackupError(Exception):
    """A failure with its exit code (spec, Error handling). The CLI prints the reason and exits with the code."""
    def __init__(self, code, reason=None):
        self.code, self.reason = code, reason or REASONS.get(code, SEE_LOG)
        super().__init__(self.reason)


def default_backup_dir(data_dir):
    """S14: backups/station beside the data dir, so ~/.local/share/superyak/backups/station for the lighthouse."""
    return Path(data_dir).absolute().parent / 'backups' / 'station'


def copy_stamp(now):
    return time.strftime(STAMP, time.gmtime(now))


def _read_only(path):
    """S2: the URI is built as validate_demo builds it (__main__.py:125); a hand-built file: URI breaks on ?, # or %."""
    return sqlite3.connect(Path(path).absolute().as_uri() + '?mode=ro', uri=True, timeout=30)


def _check(db, pragma):
    """True when PRAGMA integrity_check or quick_check returns exactly one row, 'ok'. Raising counts as failing."""
    try:
        return [tuple(row) for row in db.execute(f'PRAGMA {pragma}')] == [('ok',)]
    except sqlite3.DatabaseError:
        return False


def _fsync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _live_database(data_dir):
    """S2: refuse a symlinked data dir or database, as Store._check_paths does, and a missing database."""
    data_dir = Path(data_dir).absolute()
    names = ('peer.sqlite3', 'peer.sqlite3-wal', 'peer.sqlite3-shm', 'peer.sqlite3-journal')
    if data_dir.is_symlink() or any((data_dir / name).is_symlink() for name in names):
        raise ValueError('Symlinked state is not allowed')
    database = data_dir / 'peer.sqlite3'
    if not database.is_file():
        raise ValueError(f'There is no station database at {database}')
    return database


def _rotation_dir(backup_dir):
    backup_dir = Path(backup_dir).absolute()
    if backup_dir.is_symlink():
        raise ValueError('A symlinked backup directory is not allowed')
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    return backup_dir


@contextmanager
def rotation_lock(directory):
    """S2: one run at a time. The restore test copies under it too, so pruning can't remove its file mid-copy (S7)."""
    fd = os.open(Path(directory) / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _remove_temporary(tmp):
    for path in (Path(tmp), Path(f'{tmp}-journal')):
        path.unlink(missing_ok=True)


def _checked_copy(database, tmp, clock, sleep):
    """S2 steps 1-3: a new 0600 file, SQLite's backup API in one step from a read-only connection, then
    integrity_check. Every failure removes the file."""
    os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
    try:
        with closing(_read_only(database)) as source, closing(sqlite3.connect(tmp)) as copy:
            source.backup(copy, pages=-1)
            sound = _check(copy, 'integrity_check')
        if not sound:
            raise BackupError(11)
        _fsync(tmp)
    except BaseException:
        _remove_temporary(tmp)
        raise


def _publish(tmp, final):
    """S2 step 4: the rename, then the directory's fsync. A file with a final name is always a checked copy."""
    os.replace(tmp, final)
    _fsync(final.parent)


def run_backup(data_dir, backup_dir, *, clock=time.time, sleep=time.sleep):
    """station-backup (S2). Returns the new copy's path; raises BackupError with its exit code."""
    database = _live_database(data_dir)
    old_umask = os.umask(0o077)
    try:
        backup_dir = _rotation_dir(backup_dir)
        with rotation_lock(backup_dir):
            stamp = copy_stamp(clock())
            final, tmp = backup_dir / f'peer-{stamp}.sqlite3', backup_dir / f'.peer-{stamp}-{os.getpid()}.tmp'
            _checked_copy(database, tmp, clock, sleep)
            try:
                _publish(tmp, final)
            except BaseException:
                _remove_temporary(tmp)
                raise
        return final
    finally:
        os.umask(old_umask)
```

- [ ] **Step 4: Add the command to `peer/superyak_peer/__main__.py`**

Add `import sys` after `import sqlite3` (line 10). It is used by later tasks' dispatch; nothing in `main()` assigns
`sys`, so it stays a module name. Keep every `import time` inside the branch that uses it, as the existing branches do:
`main()` already imports `time` locally, which makes `time` a local name throughout `main()`.

After the `station-bridge`/`station-unbridge` loop (line 206), before `door = commands.add_parser('door', …)`:

```python
    backup_cmd = commands.add_parser('station-backup', help='Trusted local: a checked copy of the station database into the rotation')
    backup_cmd.add_argument('--data-dir', type=Path, default=Path('.engram/home'))
    backup_cmd.add_argument('--backup-dir', type=Path, help='The rotation (default: backups/station beside the data dir)')
```

After the `station-notices` branch (lines 271-272):

```python
        elif args.command == 'station-backup':
            from .backups import BackupError, default_backup_dir, run_backup
            try:
                written = run_backup(args.data_dir, args.backup_dir or default_backup_dir(args.data_dir))
            except BackupError as failed:
                parser.exit(failed.code, f'station-backup: {failed.reason}\n')
            print(f'Checked copy: {written}')
```

An `OSError` or `ValueError` from `run_backup` reaches the existing handler at line 337 and exits 1 ("see the log").

- [ ] **Step 5: Add the release inventory entries**

In `peer/pyproject.toml`, add `"superyak_peer/backups.py",` after `"superyak_peer/auth.py",` in both `only-include`
lists, and `"tests/test_backups.py",` after `"tests/test_auth.py",` in the sdist list.

- [ ] **Step 6: Run the tests to see them pass**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_backups.py tests/test_packaging.py`
Expected: all passed.

- [ ] **Step 7: Mutation checks** (`PYTHONDONTWRITEBYTECODE=1`, caches cleared before each)

| Mutation | Must fail |
|---|---|
| R1: construct `Store(data_dir)` at the top of `run_backup` (`from .db import Store`) | `test_backup_copies_committed_data_from_a_read_only_connection` |
| R1: open the source read-write, `sqlite3.connect(database, timeout=30)`, in `_checked_copy` | same |
| R1: wrap the copy in `with DispatchGate(Path(data_dir) / 'dispatch.lock'):` (`from .dispatch import DispatchGate`) | same (the second run times out) |
| R2: drop `os.umask(0o077)` and create the rotation with `mode=0o755` and `os.chmod(backup_dir, 0o755)` | `test_copies_are_private_checked_and_appear_whole` |
| R2: drop `_remove_temporary(tmp)` from `run_backup`'s publish failure | same |

- [ ] **Step 8: Run the whole peer suite and commit**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider`
Expected: all passed.

```bash
git add peer/superyak_peer/backups.py peer/superyak_peer/__main__.py peer/pyproject.toml peer/tests/test_backups.py
git commit -m "Backups, task 1: a checked copy from a read-only connection, published whole and private (R1, R2)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Retention, and a clock that must move forward (R3)

**Files:**
- Modify: `peer/superyak_peer/backups.py` (the rotation helpers; `run_backup`'s locked block)
- Test: `peer/tests/test_backups.py`

**Interfaces:**
- Consumes: Task 1's `run_backup`, `rotation_lock`, `copy_stamp`, `STAMP`.
- Produces: `COPY_NAME`, `TEMP_NAME`, `KEEP_DAYS`, `KEEP_WEEKS`, `TEMP_MAX_AGE`, `copy_time(path) -> float`,
  `_stamp_ok(name) -> bool`, `rotation(directory) -> list[Path]` (oldest first), `newest_copy(directory) -> Path | None`, `keep(names) -> set[str]`,
  `prune(directory, now)`. Task 4 prunes the copy off the Pi with `prune`; Tasks 7 and 10 use `newest_copy` and
  `copy_time`.

- [ ] **Step 1: Write the failing test**

Append to `peer/tests/test_backups.py`:

```python
NOW = calendar.timegm((2026, 10, 17, 3, 30, 0))
# Worked out by hand, not by the code under test. The test makes copies at 03:30 UTC on the 200 days 2026-03-31 to
# 2026-10-16, except September (the Pi was off) and 2026-10-10 (a failed night), plus 2026-10-16 03:31:10 and 15:00:00;
# the run adds 2026-10-17 03:30:00. S3 then keeps:
# - the newest copy of the 14 most recent days that have one: 10-03 to 10-09 and 10-11 to 10-17 (10-16 keeps 15:00);
# - the newest copy of the 8 most recent ISO weeks that have one: weeks 42 (10-17), 41 (10-11), 40 (10-04), then,
#   since weeks 37-39 have none, 36 (08-31), 35 (08-30), 34 (08-23), 33 (08-16) and 32 (08-09).
KEPT = ['20260809T033000Z', '20260816T033000Z', '20260823T033000Z', '20260830T033000Z', '20260831T033000Z',
        '20261003T033000Z', '20261004T033000Z', '20261005T033000Z', '20261006T033000Z', '20261007T033000Z',
        '20261008T033000Z', '20261009T033000Z', '20261011T033000Z', '20261012T033000Z', '20261013T033000Z',
        '20261014T033000Z', '20261015T033000Z', '20261016T150000Z', '20261017T033000Z']


def test_retention_keeps_14_days_and_8_weeks_and_nothing_else(tmp_path):
    """R3: S3's rule over 200 days with gaps, several copies in one day and a month off. Hand-made names and other files
    are never touched; stale temporary files go; a clock behind the newest name writes and prunes nothing, exit 1."""
    store, rotation = station(tmp_path)
    rotation.mkdir(parents=True, mode=0o700)
    day = datetime.date(2026, 3, 31)
    for _ in range(200):
        if day.month != 9 and day != datetime.date(2026, 10, 10):
            (rotation / f'peer-{day:%Y%m%d}T033000Z.sqlite3').write_bytes(b'copy')
        day += datetime.timedelta(days=1)
    for extra in ('20261016T033110Z', '20261016T150000Z'):
        (rotation / f'peer-{extra}.sqlite3').write_bytes(b'copy')
    others = ['peer-20261007-083623-before-andy-password.sqlite3', 'peer.sqlite3.pre-instruction-layers-20261008-163222',
              'peer-20260101T000000Z.sqlite3.bak', 'notes.txt',
              'peer-20261399T000000Z.sqlite3']        # matches the pattern but isn't a time: never newest, never pruned
    for name in others:
        (rotation / name).write_bytes(b'not a rotation copy')
    stale = [rotation / '.peer-20261001T033000Z-41.tmp', rotation / '.peer-20261001T033000Z-41.tmp-journal']
    fresh = rotation / '.peer-20261017T030000Z-42.tmp'
    for path in [*stale, fresh]:
        path.write_bytes(b'temporary')
    for path in stale:
        os.utime(path, (NOW - 2 * 86400, NOW - 2 * 86400))
    os.utime(fresh, (NOW - 3600, NOW - 3600))
    before = names(rotation)
    with pytest.raises(backups.BackupError) as behind:
        backups.run_backup(store.data_dir, rotation, clock=lambda: calendar.timegm((2026, 10, 16, 14, 0, 0)))
    assert behind.value.code == 1
    assert "the Pi's clock is behind the newest copy (peer-20261016T150000Z.sqlite3)" in behind.value.reason
    assert names(rotation) == before
    written = backups.run_backup(store.data_dir, rotation, clock=lambda: NOW)
    assert written.name == 'peer-20261017T033000Z.sqlite3' and ok(written)
    assert [path.name for path in backups.rotation(rotation)] == [f'peer-{stamp}.sqlite3' for stamp in KEPT]
    assert all((rotation / name).read_bytes() == b'not a rotation copy' for name in others)
    assert not any(path.exists() for path in stale) and fresh.exists()
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_backups.py -k retention`
Expected: FAIL: `DID NOT RAISE <class 'superyak_peer.backups.BackupError'>` (there is no clock check yet).

- [ ] **Step 3: Add the rotation to `peer/superyak_peer/backups.py`**

Add `import calendar`, `import datetime` and `import re` to the imports, these constants after `STAMP`:

```python
COPY_NAME = re.compile(r'peer-(\d{8}T\d{6}Z)\.sqlite3')
TEMP_NAME = re.compile(r'\.peer-.+\.tmp(?:-journal)?')
KEEP_DAYS, KEEP_WEEKS = 14, 8
TEMP_MAX_AGE = 86400
```

and these functions after `copy_stamp`:

```python
def copy_time(path):
    """A copy's UTC time, from its name."""
    return calendar.timegm(time.strptime(COPY_NAME.fullmatch(Path(path).name)[1], STAMP))


def _stamp_ok(name):
    """A name that matches COPY_NAME and holds a real UTC time; peer-20261399T000000Z.sqlite3 only looks like one. A
    stray one would otherwise sort newest: every backup would fail on the clock check and station-notices would crash."""
    try:
        time.strptime(COPY_NAME.fullmatch(name)[1], STAMP)
    except (TypeError, ValueError):
        return False
    return True


def rotation(directory):
    """The copies with a final name, oldest first. Symlinks and every other name are never read, moved or pruned."""
    try:
        entries = list(os.scandir(directory))
    except FileNotFoundError:
        return []
    return sorted((Path(entry.path) for entry in entries
                   if _stamp_ok(entry.name) and entry.is_file(follow_symlinks=False)), key=lambda path: path.name)


def newest_copy(directory):
    copies = rotation(directory)
    return copies[-1] if copies else None


def keep(names):
    """S3: the newest copy of each of the 14 most recent UTC days that have a copy, and of each of the 8 most recent ISO
    weeks that have one. Only days and weeks with a copy count, so a Pi that was off never ages out its last copies."""
    days, weeks = {}, {}
    for name in sorted(names, reverse=True):
        when = datetime.datetime.strptime(COPY_NAME.fullmatch(name)[1], STAMP)
        days.setdefault(when.date(), name)
        weeks.setdefault(when.isocalendar()[:2], name)
    return ({days[day] for day in sorted(days, reverse=True)[:KEEP_DAYS]}
            | {weeks[week] for week in sorted(weeks, reverse=True)[:KEEP_WEEKS]})


def prune(directory, now):
    """S3, R3: run only once a new checked copy is in place. Deletes the copies S3 doesn't keep, and temporary files
    (.tmp and .tmp-journal) over a day old. Nothing else in the directory is touched."""
    copies = rotation(directory)
    kept = keep([path.name for path in copies])
    for path in copies:
        if path.name not in kept:
            path.unlink()
    for entry in list(os.scandir(directory)):
        if (TEMP_NAME.fullmatch(entry.name) and entry.is_file(follow_symlinks=False)
                and now - entry.stat(follow_symlinks=False).st_mtime > TEMP_MAX_AGE):
            os.unlink(entry.path)
```

Replace the locked block in `run_backup` with:

```python
        with rotation_lock(backup_dir):
            now = clock()
            stamp, newest = copy_stamp(now), newest_copy(backup_dir)
            if newest is not None and stamp < COPY_NAME.fullmatch(newest.name)[1]:
                # S3: a clock behind would give the copy an old name that pruning could delete at once; a clock that
                # was ahead left a future name "newest". Either way: nothing written, nothing pruned, every night.
                raise BackupError(1, f"the Pi's clock is behind the newest copy ({newest.name}); if the clock is right, "
                                     f'move that copy out of {backup_dir}')
            final, tmp = backup_dir / f'peer-{stamp}.sqlite3', backup_dir / f'.peer-{stamp}-{os.getpid()}.tmp'
            _checked_copy(database, tmp, clock, sleep)
            try:
                _publish(tmp, final)
            except BaseException:
                _remove_temporary(tmp)
                raise
            prune(backup_dir, now)
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_backups.py`
Expected: all passed.

- [ ] **Step 5: Mutation checks** (`PYTHONDONTWRITEBYTECODE=1`, caches cleared before each)

| Mutation | Must fail |
|---|---|
| R3: `KEEP_DAYS = 13` | `test_retention_keeps_14_days_and_8_weeks_and_nothing_else` |
| R3: group weeks by `(when.year, when.month)` instead of `when.isocalendar()[:2]` | same |
| R3: call `prune(backup_dir, now)` before `_checked_copy` | same |
| R3: in `prune`, delete every file whose name starts with `peer-` | same |
| R3: drop the clock check | same |
| R3, review S1: `rotation` filters with `COPY_NAME.fullmatch` instead of `_stamp_ok` | same (the stray name sorts newest, so the run at `NOW` exits 1) |

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/backups.py peer/tests/test_backups.py
git commit -m "Backups, task 2: keep 14 nightly and 8 weekly copies, and refuse a clock behind the newest copy (R3)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Low disk, failed checks, a hot journal, and `--output` (R4, R5)

**Files:**
- Modify: `peer/superyak_peer/backups.py` (`_checked_copy` replaced; `free_bytes`, `_write_output`; `run_backup` takes
  `output`)
- Modify: `peer/superyak_peer/__main__.py` (`--output` on `station-backup`)
- Test: `peer/tests/test_backups.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: `MIN_FREE`, `RETRY_SECONDS`, `free_bytes(path) -> int`, `_write_output(database, output, clock, sleep)`,
  `run_backup(..., output=None, ...)`; exit codes 10, 11 and 12; `station-backup --output FILE`. Tasks 6 and 7 stage
  copies with `run_backup(data_dir, None, output=path)`.

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_backups.py`:

```python
def overwrite_pages(path, first=2):
    """Junk over every page after the first two: the header survives, the tables don't."""
    size = path.stat().st_size
    with open(path, 'r+b') as stream:
        stream.seek(first * 4096)
        stream.write(b'\xff' * (size - first * 4096))


def test_output_writes_one_checked_copy_and_never_overwrites(tmp_path, monkeypatch):
    """R4: one checked copy at a new path outside the rotation; an existing path is refused, even one created during the
    copy, because the copy is published with os.link."""
    store, rotation = station(tmp_path)
    target = tmp_path / 'before-deploy.sqlite3'
    assert backup(store, rotation, '--output', target) == 0
    assert ok(target) and stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not rotation.exists()
    kept = target.read_bytes()
    assert backup(store, rotation, '--output', target) == 1 and target.read_bytes() == kept
    racing, real_check = tmp_path / 'racing.sqlite3', backups._check

    def check_then_race(db, pragma):
        racing.write_bytes(b'made by someone else during the copy')
        return real_check(db, pragma)

    monkeypatch.setattr(backups, '_check', check_then_race)
    assert backup(store, rotation, '--output', racing) == 1
    assert racing.read_bytes() == b'made by someone else during the copy'
    assert not list(tmp_path.glob('.peer-*'))


@pytest.mark.parametrize('failure, code', [(None, 0), ('low disk', 10), ('copy fails its check', 11),
                                           ('live database damaged', 12)])
def test_failures_keep_old_copies_and_exit_with_their_code(tmp_path, monkeypatch, failure, code):
    """R5: low disk and failed checks write nothing, prune nothing, leave no temporary file and exit with their code. The
    first case is the control: the same rotation and a run that works, which prunes the older of one day's two copies."""
    store, rotation = station(tmp_path)
    rotation.mkdir(parents=True, mode=0o700)
    day = time.strftime('%Y%m%d', time.gmtime(time.time() - 3 * 86400))
    old = [f'peer-{day}T010000Z.sqlite3', f'peer-{day}T020000Z.sqlite3'] + [
        f'peer-{time.strftime(backups.STAMP, time.gmtime(time.time() - days * 86400))}.sqlite3' for days in (2, 1)]
    for name in old:
        (rotation / name).write_bytes(b'an earlier copy')
    if failure == 'low disk':
        monkeypatch.setattr(backups, 'free_bytes', lambda path: 10 * 2**20)
    elif failure == 'copy fails its check':
        monkeypatch.setattr(backups, '_check', lambda db, pragma: pragma == 'quick_check')
    elif failure == 'live database damaged':
        overwrite_pages(store.db_path)
    assert backup(store, rotation) == code
    if failure is None:
        [new] = [name for name in names(rotation) if name not in old]
        assert names(rotation) == sorted(old[1:] + [new])
    else:
        assert names(rotation) == sorted(old)


CRASH = '''import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute('PRAGMA cache_size=2')
db.execute('BEGIN IMMEDIATE')
db.execute("UPDATE filler SET v = v || 'y'")
os._exit(0)
'''


def test_a_hot_journal_after_a_power_cut_is_retried_never_called_damage(tmp_path):
    """Review Focus 4 (S8): a power cut mid-commit leaves a hot journal. The read-only open succeeds and the first read
    fails with SQLITE_READONLY_ROLLBACK. The backup retries for 60 s, then exits 1, never 12, and leaves the live file
    and its journal exactly as they were: the lighthouse recovers them when it opens the database."""
    store, rotation = station(tmp_path)
    with closing(sqlite3.connect(store.db_path)) as db:
        db.execute('CREATE TABLE filler(v TEXT)')
        db.executemany('INSERT INTO filler VALUES(?)', [('x' * 500,) for _ in range(2000)])
        db.commit()
    subprocess.run([sys.executable, '-I', '-c', CRASH, str(store.db_path)], check=True)   # the cache spills, then "power off"
    journal = Path(f'{store.db_path}-journal')
    assert journal.stat().st_size > 0
    live, hot = store.db_path.read_bytes(), journal.read_bytes()
    now = [time.time()]
    with pytest.raises(backups.BackupError) as failed:
        backups.run_backup(store.data_dir, rotation, clock=lambda: now[0],
                           sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
    assert failed.value.code == 1 and f'could not be copied for {backups.RETRY_SECONDS} s' in failed.value.reason
    assert store.db_path.read_bytes() == live and journal.read_bytes() == hot
    assert names(rotation) == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_backups.py`
Expected: FAIL. `--output` is an unrecognized argument (exit 2), `free_bytes` doesn't exist, the damaged case exits 11,
and the hot journal raises a bare `sqlite3.OperationalError` instead of `BackupError`.

- [ ] **Step 3: Replace `_checked_copy` and add `--output` in `peer/superyak_peer/backups.py`**

Add `import errno` and `import shutil` to the imports, and after `TEMP_MAX_AGE`:

```python
MIN_FREE = 1 << 30
RETRY_SECONDS = 60
```

Add before `_checked_copy`:

```python
def free_bytes(path):
    return shutil.disk_usage(path).free
```

Replace `_checked_copy` with:

```python
def _checked_copy(database, tmp, clock, sleep):
    """S2 steps 1-3 and S4: a new 0600 file, SQLite's backup API in one step from a read-only connection, then
    integrity_check. A busy database or a hot journal is retried for 60 s (S8: after a power cut the read-only open
    succeeds and the first read fails with SQLITE_READONLY_ROLLBACK). Every failure removes the file."""
    os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
    try:
        deadline = clock() + RETRY_SECONDS
        while True:
            try:
                with closing(_read_only(database)) as source:
                    size = source.execute('PRAGMA page_count').fetchone()[0] * source.execute('PRAGMA page_size').fetchone()[0]
                    if free_bytes(tmp.parent) - size < MIN_FREE:  # S4: at least 1 GiB left after the copy
                        raise BackupError(10)
                    with closing(sqlite3.connect(tmp)) as copy:
                        source.backup(copy, pages=-1)
                        sound = _check(copy, 'integrity_check')
                break
            except sqlite3.OperationalError as error:
                if getattr(error, 'sqlite_errorcode', None) == sqlite3.SQLITE_FULL:
                    raise BackupError(10) from error
                if clock() >= deadline:
                    raise BackupError(1, f'the station database could not be copied for {RETRY_SECONDS} s: {error}') from error
                sleep(1)
            except sqlite3.DatabaseError:
                sound = False  # a copy that raised is a copy that failed its check
                break
        if not sound:
            with closing(_read_only(database)) as live:  # S4: tell a bad copy from a damaged station
                raise BackupError(11 if _check(live, 'quick_check') else 12)
        _fsync(tmp)
    except OSError as error:
        _remove_temporary(tmp)
        if error.errno == errno.ENOSPC:
            raise BackupError(10) from error
        raise
    except BaseException:
        _remove_temporary(tmp)
        raise
```

`sqlite3.OperationalError` is a subclass of `sqlite3.DatabaseError`, so its `except` must stay first: a busy or
read-only-rollback error is retried, and only a corrupt page ("database disk image is malformed") counts as a failed
check.

Add after `_publish`:

```python
def _write_output(database, output, clock, sleep):
    """S2 --output FILE: one checked copy at a new path, outside the rotation. It publishes with os.link, so an existing
    FILE is never replaced, even one created after the check (R4)."""
    if os.path.lexists(output):
        raise ValueError(f'{output} exists; --output never replaces a file')
    tmp = output.parent / f'.peer-{copy_stamp(clock())}-{os.getpid()}.tmp'
    _checked_copy(database, tmp, clock, sleep)
    try:
        os.link(tmp, output)
        _fsync(output.parent)
    finally:
        _remove_temporary(tmp)
    return output
```

In `run_backup`, change the signature to `def run_backup(data_dir, backup_dir, *, output=None, clock=time.time,
sleep=time.sleep):` and put this first inside the `try`, before `backup_dir = _rotation_dir(backup_dir)`:

```python
        if output is not None:
            return _write_output(database, Path(output).absolute(), clock, sleep)
```

- [ ] **Step 4: Add `--output` to the command**

In `peer/superyak_peer/__main__.py`, after the `--backup-dir` argument of `backup_cmd`:

```python
    backup_cmd.add_argument('--output', type=Path, help='One checked copy at this new path, outside the rotation; never replaces a file')
```

and pass it in the dispatch: `written = run_backup(args.data_dir, args.backup_dir or default_backup_dir(args.data_dir), output=args.output)`.

- [ ] **Step 5: Run the tests to see them pass**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_backups.py`
Expected: all passed.

- [ ] **Step 6: Mutation checks** (`PYTHONDONTWRITEBYTECODE=1`, caches cleared before each)

| Mutation | Must fail |
|---|---|
| R5: drop the free-space check | `test_failures_keep_old_copies_and_exit_with_their_code[low disk-10]` |
| R5: always `raise BackupError(11)` (no live `quick_check`) | `…[live database damaged-12]` |
| R5: in `run_backup`, prune in a `finally` around `_checked_copy`, so failures prune too | `…[copy fails its check-11]` |
| R4: publish `--output` with `os.replace(tmp, output)` instead of `os.link` | `test_output_writes_one_checked_copy_and_never_overwrites` |
| Review Focus 4: drop the `except sqlite3.OperationalError` branch, so a hot journal counts as a failed check | `test_a_hot_journal_after_a_power_cut_is_retried_never_called_damage` |

- [ ] **Step 7: Commit**

```bash
git add peer/superyak_peer/backups.py peer/superyak_peer/__main__.py peer/tests/test_backups.py
git commit -m "Backups, task 3: low disk, failed checks, a hot journal, and --output that never replaces a file (R4, R5)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: The copy off the Pi, switched off (R6)

**Files:**
- Modify: `peer/superyak_peer/backups.py` (`_device`, `_sha256`, `copy_off`; `run_backup` takes `copy_to`)
- Modify: `peer/superyak_peer/__main__.py` (`--copy-to` on `station-backup`)
- Test: `peer/tests/test_backups.py`

**Interfaces:**
- Consumes: Tasks 1–3, `prune`.
- Produces: `_device(path) -> int` (patched by tests), `copy_off(final, target, backup_dir, now)`, exit 13,
  `run_backup(..., copy_to='', ...)`, `station-backup --copy-to=DIR`. The unit (Task 11) passes
  `--copy-to=${SUPERYAK_BACKUP_COPY_TO}`, which is empty until Andy writes `~/.config/superyak/backup.env`.

- [ ] **Step 1: Write the failing test**

Append to `peer/tests/test_backups.py`:

```python
def test_copy_to_is_off_by_default_and_refuses_the_same_disk(tmp_path, monkeypatch):
    """R6: an empty --copy-to does nothing. The rotation's own disk, a missing directory or a symlink gives 13 and keeps
    the local copy. Another disk gets a 0600 copy with the same sha256, and S3 applies there too."""
    store, rotation = station(tmp_path)
    offsite = tmp_path / 'offsite'
    offsite.mkdir()
    assert backup(store, rotation, '--copy-to=') == 0                  # what the unit passes while backup.env is absent
    assert len(backups.rotation(rotation)) == 1 and list(offsite.iterdir()) == []
    assert backup(store, rotation, f'--copy-to={offsite}') == 13       # tmp_path is the rotation's disk too
    assert backups.rotation(rotation) and list(offsite.iterdir()) == []
    monkeypatch.setattr(backups, '_device', lambda path: 2 if Path(path) == rotation else 1)   # every other path: another disk
    link = tmp_path / 'link'
    link.symlink_to(offsite)
    for refused in (tmp_path / 'missing', link):
        assert backup(store, rotation, f'--copy-to={refused}') == 13
        assert backups.rotation(rotation) and list(offsite.iterdir()) == []
    day = time.strftime('%Y%m%d', time.gmtime(time.time() - 3 * 86400))
    for hour in ('01', '02'):
        (offsite / f'peer-{day}T{hour}0000Z.sqlite3').write_bytes(b'an earlier copy')
    assert backup(store, rotation, f'--copy-to={offsite}') == 0
    local = backups.newest_copy(rotation)
    copied = offsite / local.name
    assert stat.S_IMODE(copied.stat().st_mode) == 0o600
    assert hashlib.sha256(copied.read_bytes()).digest() == hashlib.sha256(local.read_bytes()).digest()
    assert sorted(p.name for p in offsite.iterdir()) == sorted([f'peer-{day}T020000Z.sqlite3', local.name])
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_backups.py -k copy_to`
Expected: FAIL: `--copy-to` is an unrecognized argument, so the first call exits 2.

- [ ] **Step 3: Add the copy off the Pi to `peer/superyak_peer/backups.py`**

Add `import hashlib` to the imports, and after `_write_output`:

```python
def _device(path):
    return os.stat(path).st_dev


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def copy_off(final, target, backup_dir, now):
    """S5, 1.2's switch: the checked copy to a mounted directory on another disk, atomically at 0600, its sha256
    compared, and S3 applied there. A share that isn't mounted is the Pi's own disk, so it is refused rather than
    silently filled. Any failure is exit 13; the local copy stays, and the rotation is already pruned."""
    target = Path(target).absolute()
    tmp = target / f'.peer-{COPY_NAME.fullmatch(final.name)[1]}-{os.getpid()}.tmp'
    made = False
    try:
        if target.is_symlink() or not target.is_dir():
            raise ValueError(f'{target} is not a directory')
        if _device(target) == _device(backup_dir):
            raise ValueError(f"{target} is on the rotation's own disk; is the share mounted?")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        made = True
        with os.fdopen(fd, 'wb') as out, open(final, 'rb') as source:
            shutil.copyfileobj(source, out, 1 << 20)
            out.flush()
            os.fsync(out.fileno())
        if _sha256(tmp) != _sha256(final):
            raise ValueError('the copy off the Pi does not match the checked copy')
        os.replace(tmp, target / final.name)
        made = False
        _fsync(target)
        prune(target, now)
    except (OSError, ValueError) as error:
        if made:
            _remove_temporary(tmp)
        raise BackupError(13, f'the copy off the Pi failed: {error}') from error
```

In `run_backup`, change the signature to `def run_backup(data_dir, backup_dir, *, output=None, copy_to='',
clock=time.time, sleep=time.sleep):` and, inside the locked block after `prune(backup_dir, now)`:

```python
            if copy_to:
                copy_off(final, copy_to, backup_dir, now)
```

- [ ] **Step 4: Add `--copy-to` to the command**

In `peer/superyak_peer/__main__.py`, after the `--output` argument:

```python
    backup_cmd.add_argument('--copy-to', default='', help='A mounted directory on another disk for the copy off the Pi; empty does nothing')
```

and the dispatch becomes:

```python
            try:
                written = run_backup(args.data_dir, args.backup_dir or default_backup_dir(args.data_dir),
                                     output=args.output, copy_to=args.copy_to)
            except BackupError as failed:
                parser.exit(failed.code, f'station-backup: {failed.reason}\n')
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_backups.py`
Expected: all passed.

- [ ] **Step 6: Mutation checks** (`PYTHONDONTWRITEBYTECODE=1`, caches cleared before each)

| Mutation | Must fail |
|---|---|
| R6: drop the `_device` comparison | `test_copy_to_is_off_by_default_and_refuses_the_same_disk` |
| R6: drop `target.is_symlink() or` | same |
| R6: drop `prune(target, now)` | same |

- [ ] **Step 7: Run the whole peer suite and commit**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider`
Expected: all passed.

```bash
git add peer/superyak_peer/backups.py peer/superyak_peer/__main__.py peer/tests/test_backups.py
git commit -m "Backups, task 4: the copy off the Pi, off until Andy picks a destination (R6)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## The health route (S6)

### Task 5: `GET /api/health` (R7)

**Files:**
- Modify: `peer/superyak_peer/app.py:166` (a route after `browser_public`)
- Modify: `peer/API.md:106` (one row in the browser routes table, before `POST /api/login`)
- Modify: `peer/pyproject.toml` (`tests/test_restore.py` in the sdist list after `tests/test_replies.py`)
- Test: `peer/tests/test_restore.py` (new)

**Interfaces:**
- Consumes: `create_app`, `create_door`, the existing 500 handler (`app.py:156-158`).
- Produces: `GET /api/health` → 200 `{"ok": true}`. Task 7's restore test polls it.

- [ ] **Step 1: Write the failing test**

Create `peer/tests/test_restore.py`:

```python
"""The restore (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S6, S7, S16; R7-R9, R18). Every
test works in tmp_path; the restore test boots real loopback servers and stops every one of them."""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import pytest
from fastapi.testclient import TestClient
from superyak_peer import backups
from superyak_peer.__main__ import main as cli
from superyak_peer.app import create_app
from superyak_peer.auth import token_hash
from superyak_peer.common import Problem
from superyak_peer.db import Store
from superyak_peer.door import create_door


def test_health_answers_without_a_session(tmp_path, monkeypatch):
    """R7: 200 with exactly {"ok": true}, no session, after one database read (a failing read is the 500 handler's);
    the door answers 404."""
    app = create_app(tmp_path / 'peer', clock=lambda: 1000000.0, allowed_origins=['http://testserver'])
    reply = TestClient(app, base_url='http://testserver').get('/api/health')
    assert reply.status_code == 200 and reply.json() == {'ok': True} and 'set-cookie' not in reply.headers
    door = TestClient(create_door(tmp_path / 'peer', clock=lambda: 1000000.0), base_url='https://door.example:8443')
    assert door.get('/api/health').status_code == 404

    def broken():
        raise sqlite3.OperationalError('disk I/O error')

    monkeypatch.setattr(app.state.store, 'transaction', broken)
    reply = TestClient(app, base_url='http://testserver', raise_server_exceptions=False).get('/api/health')
    assert reply.status_code == 500 and reply.json() == {'error': 'Request could not be completed'}
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_restore.py`
Expected: FAIL: `assert 404 == 200`.

- [ ] **Step 3: Add the route**

In `peer/superyak_peer/app.py`, after `browser_public` (line 166):

```python
    @app.get('/api/health')
    def health():
        """Spec 2026-10-14 S6: one database read, no session, nothing but ok. A database error goes to the 500 handler
        above. It sits behind tailscale serve on the tailnet; the public door has no such route."""
        with store.transaction() as db:
            db.execute('SELECT 1 FROM system_meta').fetchone()
        return {'ok': True}
```

In `peer/API.md`, add this row before the `POST /api/login` row (line 106):

```markdown
| GET `/api/health` | — | `{ok:true}` after one database read; no session; the lighthouse only, never the door |
```

In `peer/pyproject.toml`, add `"tests/test_restore.py",` after `"tests/test_replies.py",` in the sdist list.

- [ ] **Step 4: Run the test to see it pass**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_restore.py tests/test_door.py tests/test_packaging.py`
Expected: all passed.

- [ ] **Step 5: Mutation checks** (`PYTHONDONTWRITEBYTECODE=1`, caches cleared before each)

| Mutation | Must fail |
|---|---|
| R7: return `{'ok': True}` without the database read | `test_health_answers_without_a_session` |
| R7: require a session (`current_user(request)`) | same |
| R7: add `'commit': 'unknown'` to the body | same |

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/app.py peer/API.md peer/pyproject.toml peer/tests/test_restore.py
git commit -m "Health, task 5: GET /api/health answers ok after one database read, without a session (R7)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## The restore (S16, then S7)

### Task 6: `station-restore-reconcile`: take back what a restore revives (R18)

This is the riskiest task: it is the only point in the design where a mistake reopens access (S16), and Andy runs it at
the most stressful moment. Every step only takes access away, in one transaction, on a staged copy.

**Files:**
- Modify: `peer/superyak_peer/backups.py` (the reconcile, after the backup code)
- Modify: `peer/superyak_peer/__main__.py` (the `station-restore-reconcile` parser and dispatch)
- Test: `peer/tests/test_restore.py`

**Interfaces:**
- Consumes: `_read_only`, `_check` (Task 1), `run_backup(..., output=…)` (Task 3, to stage copies in tests),
  `auth.token_hash`, `ships.safe_line`.
- Produces: `ReconcileRefused(ValueError)`, `REPORT_HEADER`, `SEQUENCE_JUMP`,
  `reconcile(db_path, *, replaced=None, live_data_dir=None, clock=time.time) -> dict` (the report),
  `describe_reconcile(report) -> str`, the step functions `_end_sessions`, `_use_invitations`, `_revoke_held_keys`,
  `_clear_uncollected`, `_expire_waiting`, `_raise_sequences`, `_revoke_owned_ship_keys`, `_revoke_like_replaced`,
  `_remove_members_like_replaced`, `_lower_roles_like_replaced`, `_close_breakouts_like_replaced` (Rio Grande's ruling
  on the plan review's Q1), `_report_differences`, each
  `(db, old, now, report) -> None` and looked up by name at call time (tests patch one);
  `station-restore-reconcile --db FILE [--replaced FILE] [--live-data-dir DIR]`. Task 7 calls `reconcile(path)`.

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_restore.py`:

```python
def docked(store, owner_id, name):
    """A ship docked for owner_id, as its machine sees it: (ship, key)."""
    started = store.start_docking(name, 'test-host')
    ship = store.confirm_docking(owner_id, started['id'], started['code'])
    return ship, store.docking_status(started['id'], started['secret'])['key']


def staged(tmp_path, store, label='replaced-20261017-120000'):
    """Runbook steps 4-5: a checked copy staged as restored.sqlite3 in a replaced-<time> directory (no dispatch.lock)."""
    aside = tmp_path / 'backups' / label
    aside.mkdir(parents=True, mode=0o700)
    return backups.run_backup(store.data_dir, None, output=aside / 'restored.sqlite3')


def go_live(copy, directory):
    """Runbook step 6: the reconciled copy installed as a data directory's peer.sqlite3, opened as the station does."""
    directory.mkdir(mode=0o700)
    shutil.copyfile(copy, directory / 'peer.sqlite3')
    return Store(directory)


def reconcile(capsys, *args):
    """station-restore-reconcile; returns (exit code, stdout, stderr)."""
    try:
        cli(['station-restore-reconcile', *map(str, args)])
        code = 0
    except SystemExit as stopped:
        code = stopped.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def overwrite_pages(path, first=2):
    """Junk over every page after the first two: the header survives, the tables don't."""
    size = path.stat().st_size
    with open(path, 'r+b') as stream:
        stream.seek(first * 4096)
        stream.write(b'\xff' * (size - first * 4096))


def test_reconcile_refuses_the_live_data_dir_and_symlinks(tmp_path, capsys):
    """R18: the directory --live-data-dir names, a directory holding dispatch.lock (the live one), a symlink and a copy
    that fails its check are each refused with exit 1, and the file is unchanged."""
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    copy = staged(tmp_path, store)
    named = tmp_path / 'named'
    named.mkdir()
    shutil.copyfile(copy, named / 'peer.sqlite3')
    link = copy.parent / 'link.sqlite3'
    link.symlink_to(copy)
    damaged = tmp_path / 'damaged' / 'restored.sqlite3'
    damaged.parent.mkdir()
    shutil.copyfile(copy, damaged)
    overwrite_pages(damaged)
    for path, extra in [(named / 'peer.sqlite3', ['--live-data-dir', named]), (store.db_path, []), (link, []), (damaged, [])]:
        before = path.read_bytes()
        code, out, err = reconcile(capsys, '--db', path, *extra)
        assert code == 1 and err.startswith('Refused') and out == '', (path, err)
        assert path.read_bytes() == before


def test_reconcile_rolls_back_when_a_step_fails(tmp_path, monkeypatch, capsys):
    """R18: a later step raises; the earlier steps' writes roll back, the staged bytes are unchanged and the exit is 1."""
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    store.login('andy', 'long-password-andy', 'test')               # a session for step 1 to delete
    copy = staged(tmp_path, store)
    before = copy.read_bytes()

    def fails(*args):
        raise RuntimeError('step 5 failed')

    monkeypatch.setattr(backups, '_raise_sequences', fails)
    code, out, err = reconcile(capsys, '--db', copy)
    assert code == 1 and 'nothing was changed' in err and 'RuntimeError' in err
    assert copy.read_bytes() == before and not Path(f'{copy}-journal').exists()


def test_reconcile_without_the_replaced_file_fails_closed(tmp_path, capsys):
    """R18: without a usable replaced file every owned ship's keys are revoked, and the station's ships (no owner) keep
    theirs. A replaced file of junk bytes, or a symlink (here to the usable live file), gives the same result as none,
    and the report says it was treated as absent and why."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    serenity, serenity_key = docked(store, andy['id'], 'serenity')
    odo = store.create_station_ship('odo', 'Odo')
    odo_key = store.issue_ship_key(odo['id'])
    why = {None: 'not given', 'junk': 'treated as absent (it failed its check)', 'link': 'treated as absent (it is a symlink)'}
    for label, replaced in (('replaced-none', None), ('replaced-junk', 'junk'), ('replaced-link', 'link')):
        copy = staged(tmp_path, store, label)
        args = ['--db', copy]
        if replaced == 'junk':
            (copy.parent / 'peer.sqlite3').write_bytes(os.urandom(8192))
        elif replaced == 'link':
            (copy.parent / 'peer.sqlite3').symlink_to(store.db_path)
        if replaced:
            args += ['--replaced', copy.parent / 'peer.sqlite3']
        code, out, err = reconcile(capsys, *args)
        assert code == 0, err
        assert 'Ship keys revoked for: serenity.' in out.splitlines()
        assert f'The replaced file was {why[replaced]}.' in out
        live = go_live(copy, tmp_path / f'live-{label}')
        with pytest.raises(Problem):
            live.ship_for_key(serenity_key)
        assert live.ship_for_key(odo_key)['username'] == 'odo'


def test_reconcile_skips_what_an_older_copy_lacks(tmp_path, capsys):
    """R18, S16 'An older copy': a copy without access_requests.share_url and without space_members reconciles with exit
    0, takes back its sessions, invitations and keys, and names the two skipped steps."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    jenn = store.create_user('jenn', 'Jenn', 'long-password-jenn')
    store.create_space(andy['id'], 'Crew', 'project', [jenn['id']])
    session = store.login('jenn', 'long-password-jenn', 'test')
    invitation = store.invite(andy['id'])
    started = store.start_docking('defiant', 'bazzite')
    store.confirm_docking(andy['id'], started['id'], started['code'])   # confirmed; its key not collected yet
    with store.transaction() as db:
        held_key = db.execute('SELECT key FROM dockings WHERE id=?', (started['id'],)).fetchone()[0]
    copy = staged(tmp_path, store)
    with closing(sqlite3.connect(copy)) as db:                          # the copy as an older station wrote it
        db.execute('ALTER TABLE access_requests DROP COLUMN share_url')
        db.execute('DROP TABLE space_members')
        db.commit()
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    assert 'Skipped, because this copy lacks them: access_requests.share_url, space_members.' in out.splitlines()
    live = go_live(copy, tmp_path / 'live')
    with pytest.raises(Problem):
        live.session(session['token'])
    with pytest.raises(Problem):
        live.redeem(invitation['token'], 'newcomer', 'Newcomer', 'long-password-newcomer')
    with pytest.raises(Problem):
        live.ship_for_key(held_key)


def test_reconcile_takes_back_what_the_restore_revived(tmp_path, capsys):
    """R18: copy a station (A); then in the live file (B) revoke a key, remove a room member, demote an admin, use an
    invitation, deny a request and record a mention. Reconciling A against B takes all of it back, never raises a role,
    reports a changed password and a changed active layer without applying them, and prints no hash, key or token."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    jenn = store.create_user('jenn', 'Jenn', 'long-password-jenn', is_admin=True)
    patient = store.create_user('patient', 'Patient', 'long-password-patient')
    serenity, key = docked(store, andy['id'], 'serenity')
    room = store.create_room(andy['id'], 'Ops', [patient['id'], serenity['id']])
    space = store.create_space(andy['id'], 'Crew', 'project', [patient['id']])
    invitation = store.invite(andy['id'])
    request = store.request_access('Eve', 'eve@example.org', '')
    session = store.login('patient', 'long-password-patient', 'test')
    layer = store.create_layer(andy['id'], {'title': 'Station law', 'body': 'Ask before you merge.'})
    store.activate_layer(andy['id'], layer['id'], layer['version'])
    copy = staged(tmp_path, store)                                               # A
    store.revoke_ship(andy['id'], serenity['id'])                                # B moves on
    store.remove_participant(andy['id'], room['id'], patient['id'])
    store.change_space_member(andy['id'], space['id'], patient['id'], remove=True)
    store.redeem(invitation['token'], 'newcomer', 'Newcomer', 'long-password-newcomer')
    store.decide_access_request(andy['id'], request['id'], False)
    store.send_message(andy['id'], room['id'], 'after-the-copy', '@serenity a mention recorded after the copy')
    store.withdraw_layer(andy['id'], layer['id'])
    with store.transaction() as db:
        db.execute('UPDATE users SET is_admin=0 WHERE id=?', (jenn['id'],))                        # demoted in B
        db.execute('UPDATE users SET is_admin=1 WHERE id=?', (patient['id'],))                     # promoted in B
        db.execute('UPDATE users SET salt=?, password_hash=? WHERE id=?', (b'\x01' * 16, b'\x02' * 32, patient['id']))
        mention_seq = db.execute("SELECT seq FROM sqlite_sequence WHERE name='mentions'").fetchone()[0]
        hashes = [row[0].hex() for row in db.execute('SELECT password_hash FROM users')]
    with closing(sqlite3.connect(copy)) as db:
        hashes += [row[0].hex() for row in db.execute('SELECT password_hash FROM users')]
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    live = go_live(copy, tmp_path / 'live')
    with pytest.raises(Problem):
        live.ship_for_key(key)                                                   # the key is refused
    with pytest.raises(Problem):
        live.get_room(patient['id'], room['id'])                                 # the member can't read the room
    with live.transaction() as db:
        roles = {row['username']: row['is_admin'] for row in db.execute('SELECT username, is_admin FROM users')}
        crew = [row[0] for row in db.execute('SELECT user_id FROM space_members WHERE space_id=?', (space['id'],))]
        sessions = db.execute('SELECT count(*) FROM sessions').fetchone()[0]
        counters = (db.execute('SELECT epoch FROM rooms WHERE id=?', (room['id'],)).fetchone()[0],
                    db.execute('SELECT version FROM spaces WHERE id=?', (space['id'],)).fetchone()[0])
    assert (roles['jenn'], roles['patient'], roles['andy']) == (0, 0, 1)         # lowered, never raised
    assert counters == (2, 2)            # raised once, as remove_participant and change_space_member do (review N6)
    assert patient['id'] not in crew
    with pytest.raises(Problem):
        live.redeem(invitation['token'], 'newcomer-again', 'Newcomer', 'long-password-newcomer')
    assert request['id'] not in [item['id'] for item in live.station_pending()]
    with pytest.raises(Problem):
        live.decide_access_request(andy['id'], request['id'], True)
    assert sessions == 0
    with pytest.raises(Problem):
        live.session(session['token'])
    live.send_message(andy['id'], room['id'], 'after-the-restore', '@serenity a mention after the restore')
    with live.transaction() as db:
        assert db.execute('SELECT max(seq) FROM mentions').fetchone()[0] > mention_seq
    assert live.login('patient', 'long-password-patient', 'test')['user']['username'] == 'patient'   # reported, not applied
    lines = out.splitlines()
    assert lines[0] == backups.REPORT_HEADER
    assert 'Ship keys revoked for: serenity.' in lines and 'Roles lowered for: jenn.' in lines
    assert f'Removed: patient from room {room["id"][:6]} Ops; patient from space {space["id"][:6]} Crew.' in lines
    assert any(line.startswith('Reported, not applied: these passwords differ from the replaced file: patient.') for line in lines)
    assert any(line.startswith(f'Reported, not applied: law layers whose active revision differs: {layer["id"][:6]} Station law')
               for line in lines)
    for secret in [key, token_hash(key), invitation['token'], token_hash(invitation['token']), session['token'], *hashes]:
        assert secret not in out


def test_reconcile_takes_back_every_other_step(tmp_path, capsys):
    """R18, S16 (plan review M1): the steps the main test doesn't reach. An activation, an approved request's uncollected
    token and share link, a waiting docking, a remote room member, a super admin's role, a peer's pairing and the events
    sequence. Lowering the only active super admin is said (review N5)."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    store.bootstrap_super_admin('root', 'Root', tmp_path / 'activation.json')
    activation = json.loads((tmp_path / 'activation.json').read_text())['token']
    request = store.request_access('Eve', 'eve@example.org', '')
    store.decide_access_request(andy['id'], request['id'], True)                  # approved; token not yet collected
    waiting = store.start_docking('defiant', 'bazzite')                           # waiting for a person to confirm
    room = store.create_room(andy['id'], 'Ops', [])
    peer = 'ab' * 32
    with store.transaction() as db:
        db.execute("UPDATE access_requests SET share_url='https://login.tailscale.com/admin/invite/abc', share_status='ready' WHERE id=?", (request['id'],))
        db.execute("INSERT INTO peers(peer_id, card, paired) VALUES(?, '{}', 1)", (peer,))
        db.execute("INSERT INTO remote_contacts(id, peer_id, user_id, name) VALUES('contact-1', ?, 'remote-user', 'Remote')", (peer,))
        db.execute("INSERT INTO remote_room_members(room_id, contact_id) VALUES(?, 'contact-1')", (room['id'],))
        db.execute('UPDATE users SET is_super_admin=1 WHERE id=?', (andy['id'],))
    copy = staged(tmp_path, store)                                                # A
    store.redeem(activation, 'root', 'Root', 'long-password-root')                # B moves on
    with store.transaction() as db:
        db.execute('DELETE FROM remote_room_members WHERE room_id=?', (room['id'],))
        db.execute('UPDATE users SET is_super_admin=0 WHERE id=?', (andy['id'],))
        db.execute('UPDATE peers SET paired=0 WHERE peer_id=?', (peer,))
    store.send_message(andy['id'], room['id'], 'after-the-copy', 'an event after the copy')
    with store.transaction() as db:
        events = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()[0]
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    live = go_live(copy, tmp_path / 'live')
    with pytest.raises(Problem):
        live.redeem(activation, 'root', 'Root', 'long-password-root')
    status = live.access_request_status(request['id'], request['secret'])
    assert 'token' not in status and 'share_url' not in status
    assert waiting['id'] not in [item['id'] for item in live.station_pending()]
    with pytest.raises(Problem):
        live.confirm_docking(andy['id'], waiting['id'], waiting['code'])
    with live.transaction() as db:
        assert db.execute('SELECT count(*) FROM remote_room_members').fetchone()[0] == 0
        assert db.execute("SELECT is_super_admin FROM users WHERE username='andy'").fetchone()[0] == 0
        assert live.emit(db, 'probe', 'probe', 1) > events
    lines = out.splitlines()
    assert f'Reported, not applied: peers whose pairing differs: {peer[:12]}.' in lines
    assert any(line.startswith('No active super admin remains after lowering roles') for line in lines)
    for secret in ['https://login.tailscale.com/admin/invite/abc', activation, token_hash(activation)]:
        assert secret not in out


def test_reconcile_without_a_replaced_file_raises_both_sequences(tmp_path, capsys):
    """R18, S16 step 5 without a replaced file (plan review M1): mentions and events jump by SEQUENCE_JUMP."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    room = store.create_room(andy['id'], 'Ops', [])
    store.send_message(andy['id'], room['id'], 'm1', 'hello')
    copy = staged(tmp_path, store)
    with closing(sqlite3.connect(copy)) as db:
        before = dict(db.execute("SELECT name, seq FROM sqlite_sequence WHERE name IN ('mentions', 'events')").fetchall())
    code, out, err = reconcile(capsys, '--db', copy)
    assert code == 0, err
    with closing(sqlite3.connect(copy)) as db:
        after = dict(db.execute("SELECT name, seq FROM sqlite_sequence WHERE name IN ('mentions', 'events')").fetchall())
    assert after == {table: before.get(table, 0) + backups.SEQUENCE_JUMP for table in ('mentions', 'events')}


def test_reconcile_refuses_a_hard_link_and_a_same_or_older_replaced_file(tmp_path, capsys):
    """R18, S16 fails closed (plan review M2): a hard link to the live file elsewhere, --replaced naming the staged copy
    itself, and a replaced file older than the staged copy (DB= and REPLACED= swapped) are each refused, and no file
    changes."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    room = store.create_room(andy['id'], 'Ops', [])
    older = staged(tmp_path, store, 'replaced-older')
    store.send_message(andy['id'], room['id'], 'after-the-copy', 'an event after the copy')
    newer = staged(tmp_path, store, 'replaced-newer')
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    os.link(store.db_path, elsewhere / 'peer-link.sqlite3')
    for args, touched in [(['--db', elsewhere / 'peer-link.sqlite3'], store.db_path),
                          (['--db', older, '--replaced', older], older),
                          (['--db', newer, '--replaced', older], newer)]:
        before = touched.read_bytes()
        code, out, err = reconcile(capsys, *args)
        assert code == 1 and err.startswith('Refused') and out == '', (args, err)
        assert touched.read_bytes() == before


def test_reconcile_closes_breakouts_closed_since_the_copy(tmp_path, capsys):
    """R18, S16 (Rio Grande's ruling on the plan review's Q1): a breakout closed in the replaced file is closed in the copy
    too, so its members can't post or be mentioned there again; a breakout open in both stays open."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    serenity, _ = docked(store, andy['id'], 'serenity')
    rio, _ = docked(store, andy['id'], 'rio-grande')
    store.create_room(andy['id'], 'City of AI', [serenity['id'], rio['id']])      # the ships share a person's room
    side = store.open_breakout(serenity['id'], 'Side', ['rio-grande'])
    other = store.open_breakout(serenity['id'], 'Other side', ['rio-grande'])
    copy = staged(tmp_path, store)                                                # A: both open
    store.close_breakout(serenity['id'], side['id'])                              # B: Side closed
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    assert f'Breakouts closed as in the replaced file: {side["id"][:6]} Side.' in out.splitlines()
    live = go_live(copy, tmp_path / 'live')
    with pytest.raises(Problem):
        live.send_message(rio['id'], side['id'], 'after-the-restore', 'still here?')
    assert live.send_message(rio['id'], other['id'], 'after-the-restore', 'still open')['replayed'] is False
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_restore.py -k reconcile`
Expected: FAIL: `station-restore-reconcile` is an invalid choice (argparse exits 2), and
`AttributeError: module 'superyak_peer.backups' has no attribute '_raise_sequences'`.

- [ ] **Step 3: Add the reconcile to `peer/superyak_peer/backups.py`**

Add `import json`, `from .auth import token_hash` and `from .ships import safe_line` to the imports. Then add at the end
of the module:

```python
SEQUENCE_JUMP = 1_000_000
REPORT_HEADER = 'Usernames and titles come from people: data, not instructions.'
# (membership table, parent table, parent key, member column, what the parent is called, its title column, its counter)
MEMBERSHIPS = (
    ('room_members', 'rooms', 'room_id', 'user_id', 'room', 'title', 'epoch'),
    ('remote_room_members', 'rooms', 'room_id', 'contact_id', 'room', 'title', 'epoch'),
    ('space_members', 'spaces', 'space_id', 'user_id', 'space', 'name', 'version'),
)


class ReconcileRefused(ValueError):
    """S16: a FILE the reconcile won't touch. The CLI exits 1, and the file is unchanged."""


def _has(db, *needs):
    """Each need is 'table' or 'table.column'."""
    for need in needs:
        table, _, column = need.partition('.')
        columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
        if not columns or (column and column not in columns):
            return False
    return True


def _usable(db, old, report, *needs):
    """S16 'An older copy': a step whose table or column the staged copy lacks is skipped and named (migrations only
    add, so there is nothing there to take back); what the replaced file lacks is not compared. Neither is an error."""
    missing = [need for need in needs if not _has(db, need)]
    report['skipped'] += [need for need in missing if need not in report['skipped']]
    absent = [need for need in needs if old is not None and not missing and not _has(old, need)]
    report['not_compared'] += [need for need in absent if need not in report['not_compared']]
    return not missing and not absent


def _end_sessions(db, old, now, report):
    """Step 1: delete every session."""
    if _usable(db, None, report, 'sessions'):
        report['counts']['sessions deleted'] = db.execute('DELETE FROM sessions').rowcount


def _use_invitations(db, old, now, report):
    """Step 2: mark every unused invitation and account activation used."""
    for table, label in (('invitations', 'invitations marked used'), ('account_activations', 'account activations marked used')):
        if _usable(db, None, report, f'{table}.used'):
            report['counts'][label] = db.execute(f'UPDATE {table} SET used=1 WHERE used=0').rowcount


def _revoke_held_keys(db, old, now, report):
    """Step 3, dockings: a docking that still holds its plaintext key has that key revoked and is expired, as
    Ships._expire_uncollected does (ships.py:109-110)."""
    if not _usable(db, None, report, 'dockings.key', 'ship_keys.revoked'):
        return
    held = db.execute('SELECT id, ship_name, key FROM dockings WHERE key IS NOT NULL').fetchall()
    for row in held:
        if db.execute('UPDATE ship_keys SET revoked=? WHERE key_hash=? AND revoked IS NULL', (now, token_hash(row['key']))).rowcount:
            report['revoked'].append(row['ship_name'])
        db.execute("UPDATE dockings SET key=NULL,status='expired' WHERE id=?", (row['id'],))
    report['counts']['uncollected docking keys revoked'] = len(held)


def _clear_uncollected(db, old, now, report):
    """Step 3, requests: clear every access request's uncollected invitation token and share link."""
    for column, label in (('token', 'uncollected invitation tokens cleared'), ('share_url', 'uncollected share links cleared')):
        if _usable(db, None, report, f'access_requests.{column}'):
            report['counts'][label] = db.execute(f'UPDATE access_requests SET {column}=NULL WHERE {column} IS NOT NULL').rowcount


def _expire_waiting(db, old, now, report):
    """Step 4: every pending access request and waiting docking expires now, so requesters ask again."""
    for table, status, label in (('access_requests', 'pending', 'pending access requests expired'),
                                 ('dockings', 'waiting', 'waiting dockings expired')):
        if _usable(db, None, report, f'{table}.expires', f'{table}.status'):
            report['counts'][label] = db.execute(f'UPDATE {table} SET expires=? WHERE status=? AND expires>?', (now, status, now)).rowcount


def _sequence(db, table):
    row = db.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (table,)).fetchone() if _has(db, 'sqlite_sequence') else None
    return max(row[0] if row else 0, db.execute(f'SELECT COALESCE(MAX(rowid), 0) FROM "{table}"').fetchone()[0])


def _raise_sequences(db, old, now, report):
    """Step 5: no watcher's saved cursor may hide a new mention: each sequence becomes the replaced file's where that is
    higher, or 1,000,000 more without a usable replaced file (or one that lacks the table: fail closed)."""
    for table in ('mentions', 'events'):
        if not _usable(db, None, report, table):
            continue
        current = _sequence(db, table)
        target = max(current, _sequence(old, table)) if old is not None and _has(old, table) else current + SEQUENCE_JUMP
        if target > current and not db.execute('UPDATE sqlite_sequence SET seq=? WHERE name=?', (target, table)).rowcount:
            db.execute('INSERT INTO sqlite_sequence(name, seq) VALUES(?, ?)', (table, target))
        report['sequences'][table] = (current, target)


def _revoke_owned_ship_keys(db, old, now, report):
    """Without a usable replaced file: every key of every ship that has an owner; those machines dock again. The
    station's own ships, which have no owner (Odo, Wormhole), keep their keys."""
    if not _usable(db, None, report, 'users.kind', 'users.owner_id', 'ship_keys.revoked'):
        return
    owned = "SELECT id FROM users WHERE kind='ship' AND owner_id IS NOT NULL"
    report['revoked'] += [row[0] for row in db.execute(
        f'SELECT DISTINCT users.username FROM ship_keys JOIN users ON users.id=ship_keys.ship_id '
        f'WHERE ship_keys.revoked IS NULL AND ship_keys.ship_id IN ({owned}) ORDER BY users.username')]
    report['counts']['ship keys revoked'] = db.execute(f'UPDATE ship_keys SET revoked=? WHERE revoked IS NULL AND ship_id IN ({owned})', (now,)).rowcount


def _revoke_like_replaced(db, old, now, report):
    """With a usable replaced file: every ship key revoked there is revoked here."""
    if not _usable(db, old, report, 'ship_keys.revoked'):
        return
    count = 0
    for key_id, revoked in old.execute('SELECT id, revoked FROM ship_keys WHERE revoked IS NOT NULL').fetchall():
        ship = db.execute('SELECT users.username FROM ship_keys JOIN users ON users.id=ship_keys.ship_id '
                          'WHERE ship_keys.id=? AND ship_keys.revoked IS NULL', (key_id,)).fetchone()
        if ship:
            db.execute('UPDATE ship_keys SET revoked=? WHERE id=?', (revoked, key_id))
            report['revoked'].append(ship[0])
            count += 1
    report['counts']['ship keys revoked as in the replaced file'] = count


def _member_name(db, table, member):
    if table == 'remote_room_members':
        row = db.execute('SELECT name FROM remote_contacts WHERE id=?', (member,)).fetchone() if _has(db, 'remote_contacts.name') else None
        return f'remote contact {row[0]}' if row else f'remote contact {member[:6]}'
    row = db.execute('SELECT username FROM users WHERE id=?', (member,)).fetchone()
    return row[0] if row else member[:6]


def _remove_members_like_replaced(db, old, now, report):
    """With a usable replaced file: for rooms and spaces in both files, each room, remote-room or space membership that
    isn't there is removed here (Wormhole included, so a room Andy unbridged stays unbridged). A room or space that loses
    a member has its epoch or version raised once, as remove_participant and change_space_member do, so a delivery
    queued under the old epoch is refused."""
    raised = set()
    for table, parent, key, member, kind, title, counter in MEMBERSHIPS:
        if not _usable(db, old, report, table, f'{parent}.{title}'):
            continue
        both = ({row[0] for row in db.execute(f'SELECT id FROM {parent}')}
                & {row[0] for row in old.execute(f'SELECT id FROM {parent}')})
        there = set(old.execute(f'SELECT {key}, {member} FROM {table}').fetchall())
        for place, who in db.execute(f'SELECT {key}, {member} FROM {table} ORDER BY {key}, {member}').fetchall():
            if place in both and (place, who) not in there:
                db.execute(f'DELETE FROM {table} WHERE {key}=? AND {member}=?', (place, who))
                if (parent, place) not in raised and _has(db, f'{parent}.{counter}'):
                    db.execute(f'UPDATE {parent} SET {counter}={counter}+1 WHERE id=?', (place,))
                    raised.add((parent, place))
                name = db.execute(f'SELECT {title} FROM {parent} WHERE id=?', (place,)).fetchone()[0]
                report['removed'].append((_member_name(db, table, who), kind, place[:6], name))


def _lower_roles_like_replaced(db, old, now, report):
    """With a usable replaced file: is_admin and is_super_admin come down to the replaced file's value where that is
    lower. Never up. When that leaves no active super admin, the report says so."""
    lowered_super = False
    for column in ('is_admin', 'is_super_admin'):
        if not _usable(db, old, report, f'users.{column}'):
            continue
        there = dict(old.execute(f'SELECT id, {column} FROM users').fetchall())
        for row in db.execute(f'SELECT id, username, {column} FROM users ORDER BY username').fetchall():
            if row['id'] in there and there[row['id']] < row[column]:
                db.execute(f'UPDATE users SET {column}=? WHERE id=?', (there[row['id']], row['id']))
                lowered_super = lowered_super or column == 'is_super_admin'
                if row['username'] not in report['lowered']:
                    report['lowered'].append(row['username'])
    if lowered_super and _has(db, 'users.activation_pending'):
        report['no_super_admin'] = db.execute('SELECT 1 FROM users WHERE is_super_admin=1 AND activation_pending=0').fetchone() is None


def _close_breakouts_like_replaced(db, old, now, report):
    """With a usable replaced file (Rio Grande's ruling on the plan review's Q1): a breakout closed there and still open
    here is closed here, at the same time, so its members can't post or record mentions in it again."""
    if not _usable(db, old, report, 'breakouts.closed', 'rooms.title'):
        return
    for room_id, closed in old.execute('SELECT room_id, closed FROM breakouts WHERE closed IS NOT NULL ORDER BY room_id').fetchall():
        if db.execute('UPDATE breakouts SET closed=? WHERE room_id=? AND closed IS NULL', (closed, room_id)).rowcount:
            title = db.execute('SELECT title FROM rooms WHERE id=?', (room_id,)).fetchone()
            report['closed'].append((room_id[:6], title[0] if title else ''))


def _title(draft):
    try:
        return json.loads(draft).get('title') or 'Untitled'
    except (TypeError, ValueError, AttributeError):
        return 'Untitled'


def _report_differences(db, old, now, report):
    """Reported, never applied, since a bad replaced file may be the reason for the restore: users whose password
    differs, instruction layers whose active revision differs, and peers whose pairing differs."""
    if _usable(db, old, report, 'users.salt', 'users.password_hash'):
        there = {row[0]: (row[1], row[2]) for row in old.execute('SELECT id, salt, password_hash FROM users')}
        report['passwords'] = [row['username'] for row in db.execute('SELECT id, username, salt, password_hash FROM users ORDER BY username')
                               if row['id'] in there and there[row['id']] != (row['salt'], row['password_hash'])]
    if _usable(db, old, report, 'layers.active_revision', 'layers.draft'):
        here = {row['id']: row['active_revision'] for row in db.execute('SELECT id, active_revision FROM layers')}
        for layer_id, active, draft in old.execute('SELECT id, active_revision, draft FROM layers ORDER BY id').fetchall():
            if (layer_id in here and here[layer_id] != active) or (layer_id not in here and active is not None):
                report['layers'].append((layer_id[:6], _title(draft), here.get(layer_id), active))
    if _usable(db, old, report, 'peers.paired'):
        here = dict(db.execute('SELECT peer_id, paired FROM peers').fetchall())
        there = dict(old.execute('SELECT peer_id, paired FROM peers').fetchall())
        report['peers'] = [peer[:12] for peer in sorted(set(here) | set(there)) if here.get(peer) != there.get(peer)]


def _refuse(db_path, live_data_dir):
    """S16: never a file in the live data dir (the one --live-data-dir names, or any directory holding a dispatch.lock,
    which every directory a station has opened holds), never a symlink. The check runs on the file's real directory,
    so a path, a symlinked parent or '..' can't fool it. A file with a second name (a hard link) is refused too, since
    the other name could be the live file (plan review M2)."""
    if db_path.is_symlink() or any(Path(f'{db_path}{end}').is_symlink() for end in ('-journal', '-wal', '-shm')):
        raise ReconcileRefused('Refused: the copy is a symlink. Stage a real file (runbook step 5).')
    if not db_path.is_file():
        raise ReconcileRefused(f'Refused: there is no file at {db_path}')
    if db_path.stat().st_nlink > 1:
        raise ReconcileRefused('Refused: the copy has another name (a hard link), so writing it could write another file. '
                               'Stage a real copy with install (runbook step 5).')
    home = db_path.resolve().parent
    if os.path.lexists(home / 'dispatch.lock') or (live_data_dir is not None and home == Path(live_data_dir).resolve()):
        raise ReconcileRefused('Refused: that file is in a live data directory. Stage the copy in the replaced directory (runbook step 5).')


def _replaced(path):
    """(read-only connection, None) when the replaced file is usable, else (None, why). A replaced file that won't open
    or fails quick_check is treated as absent, and the reconcile fails closed; the report says why."""
    if path is None:
        return None, 'not given'
    path = Path(path).absolute()
    if path.is_symlink():
        return None, 'treated as absent (it is a symlink)'
    if not path.is_file():
        return None, 'treated as absent (there is no such file)'
    old = None
    try:
        old = _read_only(path)
        if _check(old, 'quick_check'):
            return old, None
    except sqlite3.Error:
        pass
    if old is not None:
        old.close()
    journal = Path(f'{path}-journal')
    return None, f'treated as absent ({"a hot journal beside it, " + journal.name if journal.exists() else "it failed its check"})'


def reconcile(db_path, *, replaced=None, live_data_dir=None, clock=time.time):
    """station-restore-reconcile (S16): on a staged copy, take back what a restore revives. Every step only takes access
    away, all in one transaction: if any step fails it rolls back and the copy is unchanged. Returns the report."""
    db_path = Path(db_path).absolute()
    _refuse(db_path, live_data_dir)
    old, why = _replaced(replaced)
    report = {'replaced': why or 'compared', 'counts': {}, 'sequences': {}, 'revoked': [], 'removed': [], 'lowered': [],
              'no_super_admin': False, 'closed': [], 'passwords': [], 'layers': [], 'peers': [], 'skipped': [],
              'not_compared': []}
    db = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        if not _check(db, 'integrity_check'):
            raise ReconcileRefused('Refused: the copy failed its integrity check.')
        # Plan review M2: the likeliest slips at runbook step 5. The live file always holds the copy's history and more,
        # so its events sequence is never lower; a lower one means DB= and REPLACED= were swapped.
        if old is not None and os.path.samefile(Path(replaced).absolute(), db_path):
            raise ReconcileRefused('Refused: --replaced is the staged copy itself. REPLACED= is the peer.sqlite3 set aside in runbook step 4.')
        if old is not None and _has(old, 'events') and _has(db, 'events') and _sequence(old, 'events') < _sequence(db, 'events'):
            raise ReconcileRefused('Refused: the replaced file is older than the staged copy. Are DB= and REPLACED= swapped? '
                                   'DB= is the staged restored.sqlite3; REPLACED= is the peer.sqlite3 set aside in runbook step 4.')
        db.execute('BEGIN IMMEDIATE')
        try:
            now = clock()
            for step in (_end_sessions, _use_invitations, _revoke_held_keys, _clear_uncollected, _expire_waiting, _raise_sequences):
                step(db, old, now, report)
            if old is None:
                _revoke_owned_ship_keys(db, old, now, report)
            else:
                for step in (_revoke_like_replaced, _remove_members_like_replaced, _lower_roles_like_replaced,
                             _close_breakouts_like_replaced, _report_differences):
                    step(db, old, now, report)
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
    finally:
        db.close()
        if old is not None:
            old.close()
    return report


def _revision(value):
    return 'none' if value is None else f'revision {value}'


def describe_reconcile(report):
    """What Andy reads at runbook step 5 (S16): counts, then usernames, short ids and titles under the header that they
    come from people. Never a hash, a key or a token."""
    def people(values):
        return ', '.join(safe_line(value) for value in values)
    lines = [REPORT_HEADER]
    if report['replaced'] == 'compared':
        lines.append('Compared with the replaced file.')
    else:
        lines.append(f"The replaced file was {report['replaced']}. Room and space members, admins and law layers were not "
                     "compared: check them by hand in runbook step 8. Every owned ship's keys were revoked, so those "
                     'machines dock again.')
    lines.append('Taken back: ' + ', '.join(f'{label} ({count})' for label, count in report['counts'].items()) + '.')
    for table, (before, after) in report['sequences'].items():
        if after != before:
            lines.append(f"The {table} sequence was raised from {before} to {after}, so no watcher's saved cursor hides what comes next.")
    if report['revoked']:
        lines.append(f'Ship keys revoked for: {people(sorted(set(report["revoked"])))}.')
    if report['removed']:
        lines.append('Removed: ' + '; '.join(f'{safe_line(who)} from {kind} {short} {safe_line(title)}'
                                             for who, kind, short, title in report['removed']) + '.')
    if report['lowered']:
        lines.append(f'Roles lowered for: {people(report["lowered"])}.')
    if report['no_super_admin']:
        lines.append('No active super admin remains after lowering roles: renew a pending one with bootstrap-super-admin '
                     '--renew-activation, or reserve one with bootstrap-super-admin (runbook step 7).')
    if report['closed']:
        lines.append('Breakouts closed as in the replaced file: '
                     + '; '.join(f'{short} {safe_line(title)}' for short, title in report['closed']) + '.')
    if report['passwords']:
        lines.append(f'Reported, not applied: these passwords differ from the replaced file: {people(report["passwords"])}. '
                     'Change again any that was changed for a reason.')
    if report['layers']:
        lines.append('Reported, not applied: law layers whose active revision differs: ' + '; '.join(
            f'{short} {safe_line(title)} (here {_revision(here)}, in the replaced file {_revision(there)})'
            for short, title, here, there in report['layers']) + '. Set them in the browser before the ships start.')
    if report['peers']:
        lines.append(f'Reported, not applied: peers whose pairing differs: {", ".join(report["peers"])}.')
    if report['skipped']:
        lines.append(f'Skipped, because this copy lacks them: {", ".join(report["skipped"])}.')
    if report['not_compared']:
        lines.append(f'Not compared, because the replaced file lacks them: {", ".join(report["not_compared"])}.')
    return '\n'.join(lines)
```

Two notes for the implementer:
- `db` has `row_factory = sqlite3.Row`; `old` keeps plain tuples, so `set(old.execute(...).fetchall())` compares with
  `(place, who)`.
- The step tuples are built at call time from module globals, which is what lets the rollback test patch
  `backups._raise_sequences`.

- [ ] **Step 4: Add the command**

In `peer/superyak_peer/__main__.py`, after the `backup_cmd` arguments:

```python
    reconcile_cmd = commands.add_parser('station-restore-reconcile', help='Trusted local: on a staged copy, take back what a restore revives (runbook step 5)')
    reconcile_cmd.add_argument('--db', type=Path, required=True, help='The staged copy; never a file in a live data directory')
    reconcile_cmd.add_argument('--replaced', type=Path, help='The peer.sqlite3 the restore replaces, opened read-only')
    reconcile_cmd.add_argument('--live-data-dir', type=Path, help='The live data directory, which is refused (make passes STATION_DATA)')
```

and after the `station-backup` dispatch:

```python
        elif args.command == 'station-restore-reconcile':
            from .backups import ReconcileRefused, describe_reconcile, reconcile
            try:
                report = reconcile(args.db, replaced=args.replaced, live_data_dir=args.live_data_dir)
            except ReconcileRefused:
                raise  # a ValueError: the handler below prints it and exits 1
            except Exception as error:  # noqa: BLE001 - the transaction rolled back, so the staged copy is unchanged
                parser.exit(1, f'station-restore-reconcile: nothing was changed: {type(error).__name__}: {safe_line(error, 200)}\n')
            print(describe_reconcile(report))
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_restore.py`
Expected: all passed.

- [ ] **Step 6: Mutation checks** (`PYTHONDONTWRITEBYTECODE=1`, caches cleared before each). The spec's R18 check is a
  step that grants access; the first four are such steps.

| Mutation | Must fail |
|---|---|
| R18: step 2 sets `used=0` | `test_reconcile_takes_back_what_the_restore_revived`, `test_reconcile_skips_what_an_older_copy_lacks` |
| R18: `_lower_roles_like_replaced` compares with `!=` instead of `<` (raises a role) | `test_reconcile_takes_back_what_the_restore_revived` |
| R18: `_raise_sequences` uses `min` instead of `max` | same |
| R18: `_revoke_owned_ship_keys` revokes ships with `owner_id IS NULL` instead | `test_reconcile_without_the_replaced_file_fails_closed` |
| R18: drop the `dispatch.lock` check in `_refuse` | `test_reconcile_refuses_the_live_data_dir_and_symlinks` |
| R18: `COMMIT` instead of `ROLLBACK` in the `except` | `test_reconcile_rolls_back_when_a_step_fails` |
| R18: `_usable` raises `ValueError` for a missing table instead of skipping it | `test_reconcile_skips_what_an_older_copy_lacks` |
| R18: `_replaced` returns the connection even when `quick_check` fails | `test_reconcile_without_the_replaced_file_fails_closed` |
| R18 (review N3): drop the symlink check in `_replaced` | `test_reconcile_without_the_replaced_file_fails_closed` |
| R18 (review M1): step 2 skips `account_activations` | `test_reconcile_takes_back_every_other_step` |
| R18 (review M1): `_clear_uncollected` keeps the values (`SET {column}={column}`) | same |
| R18 (review M1): `_expire_waiting` skips dockings | same |
| R18 (review M1): `_raise_sequences` raises only `mentions` | same |
| R18 (review M1): drop the `remote_room_members` row of `MEMBERSHIPS` | same |
| R18 (review M1): `_lower_roles_like_replaced` lowers only `is_admin` | same |
| R18 (review M1): skip the peers block of `_report_differences` | same |
| Review N5: never set `no_super_admin` | same |
| R18 (review M1): `SEQUENCE_JUMP = 0` | `test_reconcile_without_a_replaced_file_raises_both_sequences` |
| R18 (review M2): drop the `st_nlink` guard in `_refuse` | `test_reconcile_refuses_a_hard_link_and_a_same_or_older_replaced_file` |
| R18 (review M2): drop the `samefile` guard | same |
| R18 (review M2): drop the older-`events` guard | same |
| R18 (Q1 ruling): drop `_close_breakouts_like_replaced` from the step tuple | `test_reconcile_closes_breakouts_closed_since_the_copy` |
| Review N6: drop the epoch and version raise in `_remove_members_like_replaced` | `test_reconcile_takes_back_what_the_restore_revived` |

- [ ] **Step 7: Run the whole peer suite and commit**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider`
Expected: all passed.

```bash
git add peer/superyak_peer/backups.py peer/superyak_peer/__main__.py peer/tests/test_restore.py
git commit -m "Restore, task 6: station-restore-reconcile takes back what a restore revives, on the staged copy (R18)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: `station-restore-test`: a throwaway station from the newest copy (R8, R9)

**Files:**
- Modify: `peer/superyak_peer/backups.py` (the restore test)
- Modify: `peer/superyak_peer/__main__.py` (the `station-restore-test` parser and dispatch)
- Test: `peer/tests/test_restore.py`

**Interfaces:**
- Consumes: `newest_copy`, `rotation_lock`, `_read_only`, `_check` (Tasks 1–2), `reconcile` (Task 6), `Store`, the
  `serve` command and `GET /api/health` (Task 5).
- Produces: `SCRATCH_PREFIX`, `START_WAIT`, `START_TRIES`, `STOP_WAIT`, `counts(db) -> (users, rooms, messages)`,
  `server_command(scratch, port) -> list[str]` (patched by tests), `restore_test(backup_dir, backup=None) -> dict`
  (`backup`, `port`, `counts`), exit codes 20–24, `station-restore-test --backup-dir DIR [--backup FILE]`, which has no
  `--data-dir` (R9).

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_restore.py`:

```python
def small_station(tmp_path):
    """Two people, a room and a message, with one checked copy in the rotation beside the data dir."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    jenn = store.create_user('jenn', 'Jenn', 'long-password-jenn')
    room = store.create_room(andy['id'], 'Ops', [jenn['id']])
    store.send_message(andy['id'], room['id'], 'm1', 'hello')
    rotation = tmp_path / 'backups' / 'station'
    backups.run_backup(store.data_dir, rotation)
    return store, rotation


def runtime_dir(tmp_path, monkeypatch):
    run = tmp_path / 'run'
    run.mkdir(mode=0o700)
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(run))
    return run


def restore_test(*args):
    """station-restore-test as the timer runs it; returns its exit code."""
    try:
        cli(['station-restore-test', *map(str, args)])
    except SystemExit as stopped:
        return stopped.code
    return 0


def record_processes(monkeypatch):
    """Every process the restore test starts, so a test can prove none is left."""
    started, real_popen = [], subprocess.Popen

    class Recorded(real_popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            started.append(self)

    monkeypatch.setattr(backups.subprocess, 'Popen', Recorded)
    return started


def test_restore_test_boots_a_throwaway_station_from_the_newest_copy(tmp_path, monkeypatch, capsys):
    """R8: a real subprocess server boots from the newest copy; the command exits 0, the scratch directory is gone and the
    port is closed. Leftover scratch directories over a day old are removed; fresh ones and symlinks are not."""
    run = runtime_dir(tmp_path, monkeypatch)
    store, rotation = small_station(tmp_path)
    old, fresh, elsewhere = run / 'superyak-restore-test-old', run / 'superyak-restore-test-fresh', tmp_path / 'elsewhere'
    for directory in (old, fresh, elsewhere):
        directory.mkdir()
    (run / 'superyak-restore-test-link').symlink_to(elsewhere)
    two_days_ago = time.time() - 2 * 86400
    for directory in (old, elsewhere):
        os.utime(directory, (two_days_ago, two_days_ago))
    assert restore_test('--backup-dir', rotation) == 0
    out = capsys.readouterr().out
    assert out.startswith(f'Restore test passed: {backups.newest_copy(rotation).name} booted on 127.0.0.1:')
    assert out.rstrip().endswith('; users 2, rooms 1, messages 1.')
    port = int(re.search(r'127\.0\.0\.1:(\d+)', out)[1])
    assert sorted(p.name for p in run.iterdir()) == ['superyak-restore-test-fresh', 'superyak-restore-test-link']
    assert elsewhere.is_dir()
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', port)) != 0


@pytest.mark.parametrize('failure, code', [('no copy', 20), ('damaged copy', 21), ('server exits', 22),
                                           ('counts changed', 23), ('reconcile raises', 24)])
def test_restore_test_failures_clean_up_and_exit_with_their_code(tmp_path, monkeypatch, failure, code):
    """R8, R9: each failure exits with its code, removes the scratch directory and leaves no process."""
    run = runtime_dir(tmp_path, monkeypatch)
    rotation = tmp_path / 'backups' / 'station' if failure == 'no copy' else small_station(tmp_path)[1]
    started = record_processes(monkeypatch)
    if failure == 'damaged copy':
        overwrite_pages(backups.newest_copy(rotation))
    elif failure == 'server exits':
        monkeypatch.setattr(backups, 'server_command', lambda scratch, port: [sys.executable, '-c', 'raise SystemExit(3)'])
    elif failure == 'counts changed':
        real_counts, seen = backups.counts, []

        def changed(db):
            seen.append(real_counts(db))
            users, rooms, messages = seen[-1]
            return seen[-1] if len(seen) == 1 else (users, rooms, messages + 1)

        monkeypatch.setattr(backups, 'counts', changed)
    elif failure == 'reconcile raises':
        def raises(*args, **kwargs):
            raise RuntimeError('a schema change broke the reconcile')

        monkeypatch.setattr(backups, 'reconcile', raises)
    assert restore_test('--backup-dir', rotation) == code
    assert list(run.iterdir()) == []
    assert all(process.poll() is not None for process in started)
    assert len(started) == {'server exits': 3, 'counts changed': 1}.get(failure, 0)


def test_restore_test_has_no_data_dir_option(tmp_path, capsys):
    """R9: it can't name the live data dir."""
    with pytest.raises(SystemExit) as refused:
        cli(['station-restore-test', '--backup-dir', str(tmp_path), '--data-dir', str(tmp_path)])
    assert refused.value.code == 2 and 'unrecognized arguments: --data-dir' in capsys.readouterr().err


def test_restore_test_passes_on_a_copy_from_before_a_migration(tmp_path, monkeypatch, capsys):
    """Review Focus 1: runbook step 2 most likely tests the copy from before a bad migration. A copy without the system
    author, message_kinds, space_members and access_requests.share_url still passes: the counts read the same before the
    server migrates it and after."""
    runtime_dir(tmp_path, monkeypatch)
    store, rotation = small_station(tmp_path)
    with closing(sqlite3.connect(backups.newest_copy(rotation))) as db:
        db.execute("DELETE FROM users WHERE id=(SELECT value FROM system_meta WHERE key='system_author')")
        db.execute('DROP TABLE system_meta')
        db.execute('DROP TABLE message_kinds')
        db.execute('DROP TABLE space_members')
        db.execute('ALTER TABLE access_requests DROP COLUMN share_url')
        db.commit()
    assert restore_test('--backup-dir', rotation) == 0
    assert capsys.readouterr().out.rstrip().endswith('; users 2, rooms 1, messages 1.')


@pytest.mark.parametrize('stop', [signal.SIGTERM, signal.SIGHUP])
def test_a_stopped_restore_test_leaves_no_server_and_no_scratch(tmp_path, monkeypatch, stop):
    """Review Focus 3: systemd's TimeoutStartSec= or a person stops the restore test while its station boots. The signal
    becomes SystemExit, so the server is stopped and reaped and the scratch directory is removed."""
    run = runtime_dir(tmp_path, monkeypatch)
    store, rotation = small_station(tmp_path)
    started = record_processes(monkeypatch)
    booting = 'import pathlib, sys, time\npathlib.Path(sys.argv[1], "booting").touch()\ntime.sleep(120)\n'
    monkeypatch.setattr(backups, 'server_command', lambda scratch, port: [sys.executable, '-c', booting, str(scratch)])

    def stop_while_booting():
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if any((p / 'booting').exists() for p in run.glob('superyak-restore-test-*')):
                os.kill(os.getpid(), stop)  # the handler the command installed turns it into SystemExit
                return
            time.sleep(0.05)

    threading.Thread(target=stop_while_booting, daemon=True).start()
    assert restore_test('--backup-dir', rotation) == 128 + stop
    assert list(run.iterdir()) == []
    assert started and all(process.poll() is not None for process in started)
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_restore.py -k restore_test`
Expected: FAIL: `station-restore-test` is an invalid choice (exit 2), and `backups` has no `server_command` or `counts`.

- [ ] **Step 3: Add the restore test to `peer/superyak_peer/backups.py`**

Add `import socket`, `import stat`, `import subprocess`, `import sys`, `import tempfile` and `import urllib.request` to
the imports, and `nullcontext` to the `contextlib` import. After `RETRY_SECONDS`:

```python
SCRATCH_PREFIX = 'superyak-restore-test-'
START_WAIT, START_TRIES, STOP_WAIT = 60, 3, 10
```

At the end of the module:

```python
def counts(db):
    """S7: users that aren't the system author, rooms and messages. A copy from before the system author counts every
    user, which is the same number once the server's start has added it."""
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    users = ("SELECT count(*) FROM users WHERE id NOT IN (SELECT value FROM system_meta WHERE key='system_author')"
             if 'system_meta' in tables else 'SELECT count(*) FROM users')
    return tuple(db.execute(sql).fetchone()[0] for sql in (users, 'SELECT count(*) FROM rooms', 'SELECT count(*) FROM messages'))


def server_command(scratch, port):
    """S7 step 5: today's code serving the copy on loopback: no proxy headers, no sync, no share link, no Odo."""
    return [sys.executable, '-I', '-m', 'superyak_peer', 'serve', '--data-dir', str(scratch), '--host', '127.0.0.1', '--port', str(port)]


def _free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def _answers(port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback never goes through a proxy
    try:
        with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=2) as reply:
            return reply.status == 200
    except OSError:
        return False


def _stop(process):
    """S7 step 8: SIGTERM, then SIGKILL after 10 s, then wait()."""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(STOP_WAIT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _start(scratch):
    """S7 steps 5-6: serve the scratch copy on a free loopback port until /api/health answers 200, within 60 s. A server
    that exits during start-up (its port taken in the meantime) is started again, up to 3 times."""
    for _ in range(START_TRIES):
        port = _free_port()
        process = subprocess.Popen(server_command(scratch, port), cwd=scratch, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + START_WAIT
            while process.poll() is None and time.monotonic() < deadline:
                if _answers(port):
                    return process, port
                time.sleep(0.2)
        except BaseException:
            _stop(process)
            raise
        exited = process.poll() is not None
        _stop(process)
        if not exited:
            break  # it ran for 60 s without answering: no second try
    raise BackupError(22)


def _leftovers(parent, now):
    """S7 step 2: scratch directories over a day old, owned by this user; never symlinks (the shared /tmp fallback)."""
    try:
        entries = list(os.scandir(parent))
    except OSError:
        return
    for entry in entries:
        if not entry.name.startswith(SCRATCH_PREFIX):
            continue
        info = entry.stat(follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and now - info.st_mtime > TEMP_MAX_AGE:
            shutil.rmtree(entry.path, ignore_errors=True)


def _restored_copy(source, target):
    """S7 step 3: the backup API from a read-only connection into a new 0600 file, then integrity_check. BACKUP=
    pointed at the live file reads it and nothing more."""
    os.close(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
    try:
        with closing(_read_only(source)) as copy_from, closing(sqlite3.connect(target)) as copy:
            copy_from.backup(copy, pages=-1)
            return _check(copy, 'integrity_check')
    except sqlite3.DatabaseError:
        return False


def restore_test(backup_dir, backup=None):
    """station-restore-test (S7). It takes no data dir, so it can't name the live one (R9). Every path tears down: the
    server is stopped and reaped and the scratch directory removed."""
    backup_dir = Path(backup_dir).absolute()
    source = Path(backup).absolute() if backup else newest_copy(backup_dir)
    if source is None or not source.is_file():
        raise BackupError(20)
    parent = Path(os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir())
    _leftovers(parent, time.time())
    scratch = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX, dir=parent))
    server = None
    try:
        target = scratch / 'peer.sqlite3'
        with rotation_lock(backup_dir) if backup_dir.is_dir() else nullcontext():  # pruning can't remove it mid-copy
            sound = _restored_copy(source, target)
        if not sound:
            raise BackupError(21)
        with closing(_read_only(target)) as db:
            before = counts(db)
        try:
            reconcile(target)  # S16 without --replaced, before the server's start: the scratch holds no dispatch.lock yet
        except Exception as error:
            raise BackupError(24) from error
        server, port = _start(scratch)
        from .db import Store  # S7 step 7: the trusted local path; the test never mints a session or holds a password
        with Store(scratch).transaction() as db:
            after = counts(db)
        if after != before or after[0] < 1 or after[1] < 1:
            raise BackupError(23)
        return {'backup': source, 'port': port, 'counts': after}
    finally:
        _stop(server)
        shutil.rmtree(scratch, ignore_errors=True)
```

The reconcile must stay before `_start`: the server's `Store` creates `dispatch.lock` in the scratch directory, and the
reconcile refuses any directory holding one (S7 step 4, S-R5).

- [ ] **Step 4: Add the command**

In `peer/superyak_peer/__main__.py`, after the `reconcile_cmd` arguments:

```python
    restore_cmd = commands.add_parser('station-restore-test', help='Trusted local: boot a throwaway loopback station from the newest copy (or --backup FILE)')
    restore_cmd.add_argument('--backup-dir', type=Path, required=True, help='The rotation')
    restore_cmd.add_argument('--backup', type=Path, help='Test this copy instead of the newest one')
```

and after the `station-restore-reconcile` dispatch:

```python
        elif args.command == 'station-restore-test':
            import signal
            from .backups import BackupError, restore_test

            def stopped(signum, frame):
                raise SystemExit(128 + signum)  # S7 step 8: stopped by hand or by systemd, the finally blocks tear down

            previous = {number: signal.signal(number, stopped) for number in (signal.SIGTERM, signal.SIGHUP)}
            try:
                tested = restore_test(args.backup_dir, args.backup)
            except BackupError as failed:
                parser.exit(failed.code, f'station-restore-test: {failed.reason}\n')
            finally:
                for number, handler in previous.items():
                    signal.signal(number, handler)
            users, rooms, messages = tested['counts']
            print(f'Restore test passed: {tested["backup"].name} booted on 127.0.0.1:{tested["port"]}; '
                  f'users {users}, rooms {rooms}, messages {messages}.')
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_restore.py`
Expected: all passed (the boot tests take a few seconds each).

- [ ] **Step 6: Mutation checks** (`PYTHONDONTWRITEBYTECODE=1`, caches cleared before each)

| Mutation | Must fail |
|---|---|
| R8: drop `shutil.rmtree(scratch, ...)` from the `finally` | `test_restore_test_boots_a_throwaway_station_from_the_newest_copy` |
| R8: drop `_stop(server)` from the `finally` | `test_restore_test_failures_clean_up_and_exit_with_their_code[counts changed-23]` |
| R8: `_leftovers` removes every leftover, however fresh (drop the age check) | `test_restore_test_boots_a_throwaway_station_from_the_newest_copy` |
| R8, S-R5: move `reconcile(target)` after `_start(scratch)` | same (24: the reconcile refuses the scratch directory once the server has made `dispatch.lock`) |
| R9: `reconcile` failures pass through as exit 1 (drop the `BackupError(24)` wrapper) | `test_restore_test_failures_clean_up_and_exit_with_their_code[reconcile raises-24]` |
| Review Focus 1: count every user (drop the `system_meta` clause) | `test_restore_test_passes_on_a_copy_from_before_a_migration` (23) |
| Review Focus 3: drop `except BaseException: _stop(process); raise` in `_start` | `test_a_stopped_restore_test_leaves_no_server_and_no_scratch` |

Two guards no test pins, so the reviewer reads them: `_leftovers` never follows a symlink and checks the owner (a
symlink is safe twice over, since `shutil.rmtree` refuses one), and a server that runs 60 s without answering is not
started again.

- [ ] **Step 7: Run the whole peer suite and commit**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider`
Expected: all passed.

```bash
git add peer/superyak_peer/backups.py peer/superyak_peer/__main__.py peer/tests/test_restore.py
git commit -m "Restore, task 7: station-restore-test boots a throwaway loopback station from the newest copy (R8, R9)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## The alerts (S9–S14)

### Task 8: `station-alert`: one checked line per failure (R10, R12)

**Files:**
- Create: `peer/superyak_peer/alerts.py`
- Modify: `peer/superyak_peer/__main__.py` (the `station-alert` parser and dispatch)
- Modify: `peer/pyproject.toml` (`superyak_peer/alerts.py` in both lists after `access_requests.py`;
  `tests/test_alerts.py` in the sdist list after `tests/test_access_requests.py`)
- Test: `peer/tests/test_alerts.py` (new)

**Interfaces:**
- Consumes: `backups.REASONS`, `backups.SEE_LOG` (Task 1), `ships.safe_line`.
- Produces: `Refused`, `UNIT`, `RESULTS`, `STATUS`, `EXIT_CODES`, `TIMER_UNITS`, `ALERT_FILE`, `KINDS`,
  `systemd_fields(environ, monitor) -> dict` (`result`, `exit_code`, `exit_status`), `kind_for(unit, monitor) -> str`,
  `failure_reason(alert) -> str`, `render(alert) -> str`, `_local(at, fmt)`, `_queue_dir`, `_write_private`,
  `record(alerts_dir, unit, kind, fields, now) -> dict` (Task 9 adds holding back), `queued(alerts_dir) -> list[dict]`,
  `clean(alerts_dir, now)`, `station_alert(data_dir, unit, *, monitor, environ, now=None) -> dict | None`;
  `station-alert --data-dir DIR --unit UNIT [--monitor]`. An alert file is
  `{id, unit, kind, at, result, exit_code, exit_status, held_back, held_since, text}`.

- [ ] **Step 1: Write the failing tests**

Create `peer/tests/test_alerts.py`:

```python
"""Service alerts (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S9-S14; R10-R15). Every test
works in tmp_path with systemd's variables set by hand; none runs systemctl."""
import calendar
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import time
import pytest
from superyak_peer import alerts, backups
from superyak_peer.__main__ import main as cli
from superyak_peer.db import Store

SYSTEMD = ('SERVICE_RESULT', 'EXIT_CODE', 'EXIT_STATUS', 'INVOCATION_ID')
CRASH = {'result': 'exit-code', 'exit_code': 'exited', 'exit_status': '1'}
GIVE_UP = {'result': 'start-limit-hit', 'exit_code': None, 'exit_status': None}
T0 = calendar.timegm((2026, 10, 14, 2, 0, 0))
HOLD = ('import fcntl, os, sys, time\n'
        'fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR)\n'
        'fcntl.flock(fd, fcntl.LOCK_EX)\n'
        'print("held", flush=True)\n'
        'time.sleep(60)\n')


def under_systemd(monkeypatch, monitor=False, **values):
    """The variables systemd gives ExecStopPost= (or, with monitor, an OnFailure= handler); nothing else of systemd's."""
    for name in SYSTEMD:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f'MONITOR_{name}', raising=False)
    for name, value in values.items():
        monkeypatch.setenv(('MONITOR_' if monitor else '') + name.upper(), value)


def alert(data, unit, *extra):
    """station-alert as systemd runs it; returns its exit code."""
    try:
        cli(['station-alert', '--data-dir', str(data), '--unit', unit, *extra])
    except SystemExit as stopped:
        return stopped.code
    return 0


def files(data):
    """The queued alert files, read directly: [(path, alert)], oldest first."""
    queue = Path(data) / 'alerts'
    if not queue.is_dir():
        return []
    found = [(path, json.loads(path.read_text())) for path in queue.iterdir() if re.fullmatch(r'[0-9a-f]{12}\.json', path.name)]
    return sorted(found, key=lambda item: (item[1]['at'], item[0].name))


def local(at, fmt='%H:%M on %Y-%m-%d'):
    return time.strftime(fmt, time.localtime(at))


@pytest.fixture
def utc(monkeypatch):
    """Alert lines use the Pi's local zone, and a held-back time on another day gains its date; tests that compare a
    bare HH:MM run in UTC, so their times stay on one day wherever the suite runs."""
    monkeypatch.setenv('TZ', 'UTC')
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_a_crash_queues_one_alert_and_a_clean_stop_queues_none(tmp_path, monkeypatch):
    """R10: ExecStopPost= with a failing result queues one 0600 stopped alert in a 0700 queue; success queues nothing; a
    run outside systemd exits 2. The notifier deletes alert files over 30 days old each time it runs, clean stops
    included (S10, review N1)."""
    data = tmp_path / 'lighthouse'
    data.mkdir(mode=0o700)
    month_old = alerts.record(data / 'alerts', 'superyak-door.service', 'stopped', CRASH, time.time() - 31 * 86400)
    under_systemd(monkeypatch, service_result='exit-code', exit_code='exited', exit_status='1')
    assert alert(data, 'superyak-lighthouse.service') == 0
    [(path, one)] = files(data)
    assert one['id'] != month_old['id']
    assert (one['unit'], one['kind'], one['result'], one['exit_code'], one['exit_status'], one['held_back']) == (
        'superyak-lighthouse.service', 'stopped', 'exit-code', 'exited', '1', 0)
    assert one['text'] == (f'Station alert: superyak-lighthouse stopped unexpectedly at {local(one["at"])} (exit-code, status 1). '
                           'systemd restarts it unless it was being stopped. Log on the Pi: journalctl --user-unit '
                           f"superyak-lighthouse.service --since '{local(one['at'] - 600, '%Y-%m-%d %H:%M')}'.")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    alerts.record(data / 'alerts', 'superyak-odo.service', 'stopped', CRASH, time.time() - 40 * 86400)
    under_systemd(monkeypatch, service_result='success', exit_code='killed', exit_status='TERM')
    assert alert(data, 'superyak-door.service') == 0 and [found['id'] for _, found in files(data)] == [one['id']]
    under_systemd(monkeypatch)
    assert alert(data, 'superyak-lighthouse.service') == 2 and len(files(data)) == 1


def test_monitor_kinds(tmp_path, monkeypatch):
    """R10, S11: --monitor with start-limit-hit queues down for a service, and failed for the backup or restore-test
    unit. Without the MONITOR_* variables an OnFailure= run refuses with 2."""
    data = tmp_path / 'lighthouse'
    data.mkdir(mode=0o700)
    under_systemd(monkeypatch, monitor=True, service_result='start-limit-hit')
    for unit in ('superyak-odo.service', 'superyak-backup.service', 'superyak-restore-test.service'):
        assert alert(data, unit, '--monitor') == 0
    queued = {one['unit']: one for _, one in files(data)}
    assert {unit: one['kind'] for unit, one in queued.items()} == {
        'superyak-odo.service': 'down', 'superyak-backup.service': 'failed', 'superyak-restore-test.service': 'failed'}
    odo, nightly = queued['superyak-odo.service'], queued['superyak-backup.service']
    assert odo['text'] == (f'Station alert: superyak-odo is down since {local(odo["at"])}: systemd stopped restarting it '
                           "(start-limit-hit). Log on the Pi: journalctl --user-unit superyak-odo.service --since "
                           f"'{local(odo['at'] - 600, '%Y-%m-%d %H:%M')}'.")
    assert nightly['text'].startswith(f'Station alert: the nightly backup failed at {local(nightly["at"])}: see the log. ')
    assert queued['superyak-restore-test.service']['text'].startswith('Station alert: the monthly restore test failed at ')
    under_systemd(monkeypatch, service_result='start-limit-hit')
    assert alert(data, 'superyak-odo.service', '--monitor') == 2


REASON_CASES = [
    ('superyak-backup.service', 'exit-code', '10', 'not enough disk space'),
    ('superyak-backup.service', 'exit-code', '11', "the copy failed its check; tomorrow's run tries again"),
    ('superyak-backup.service', 'exit-code', '12', "the live database may be damaged: don't restart or deploy before reading docs/station-restore.md"),
    ('superyak-backup.service', 'exit-code', '13', 'the copy off the Pi failed'),
    ('superyak-backup.service', 'exit-code', '1', 'see the log'),
    ('superyak-restore-test.service', 'exit-code', '20', 'there is no backup to test'),
    ('superyak-restore-test.service', 'exit-code', '21', 'the newest copy failed its check'),
    ('superyak-restore-test.service', 'exit-code', '22', 'the restored station did not start'),
    ('superyak-restore-test.service', 'exit-code', '23', 'the restored station is missing data'),
    ('superyak-restore-test.service', 'exit-code', '24', "the restore's reconcile step failed"),
    ('superyak-restore-test.service', 'exit-code', '1', 'see the log'),
    ('superyak-backup.service', 'timeout', '', 'it ran past its time limit'),
    ('superyak-backup.service', 'signal', 'KILL', 'it was killed (KILL)'),
    ('superyak-restore-test.service', 'core-dump', 'SEGV', 'it was killed (SEGV)'),
    ('superyak-backup.service', 'oom-kill', 'KILL', 'it was killed (KILL)'),
]


@pytest.mark.parametrize('unit, result, status, reason', REASON_CASES)
def test_failed_backup_and_restore_runs_name_their_reason(tmp_path, monkeypatch, unit, result, status, reason):
    """R12: every exit code in the Error handling table, and the systemd results timeout, signal, core-dump and oom-kill,
    in the spec's words."""
    data = tmp_path / 'lighthouse'
    data.mkdir(mode=0o700)
    under_systemd(monkeypatch, monitor=True, service_result=result, exit_code='exited' if result == 'exit-code' else 'killed',
                  **({'exit_status': status} if status else {}))
    assert alert(data, unit, '--monitor') == 0
    [(_, failed)] = files(data)
    assert f': {reason}. The earlier copies are kept. Log on the Pi: journalctl --user-unit {unit} --since ' in failed['text']


def test_alert_lines_hold_no_log_lines_mentions_or_unchecked_values(tmp_path, monkeypatch):
    """R12: invalid units are refused with nothing queued; an unknown result becomes unknown; a secret in the environment
    reaches neither the file nor the text; no at sign and no newline."""
    data = tmp_path / 'lighthouse'
    data.mkdir(mode=0o700)
    under_systemd(monkeypatch, service_result='exit-code', exit_code='exited', exit_status='1')
    for unit in ('superyak-door', 'sshd.service', 'superyak-x@y.service', 'superyak-Door.service', '../superyak-door.service',
                 'superyak-door.service\nTraceback', 'superyak-' + 'a' * 61 + '.service'):
        assert alert(data, unit) == 2, unit
    assert files(data) == []
    monkeypatch.setenv('LIGHTHOUSE_ORIGIN', 'https://s3cret-origin.example')
    monkeypatch.setenv('SUPERYAK_SECRET', 's3cret-value')
    under_systemd(monkeypatch, service_result='exit-code @serenity', exit_code='exited\nTraceback (most recent call last)',
                  exit_status='s3cret-status', invocation_id='s3cret-invocation')
    assert alert(data, 'superyak-door.service') == 0
    [(path, one)] = files(data)
    raw = path.read_text()
    assert 's3cret' not in raw and 'Traceback' not in raw and '@' not in raw
    assert (one['result'], one['exit_code'], one['exit_status']) == ('unknown', None, None)
    assert '(unknown). ' in one['text'] and '\n' not in one['text'] and len(one['text']) <= 400


def test_a_notifier_that_cannot_write_its_queue_exits_0(tmp_path, monkeypatch, capsys):
    """Error handling: a queue it can't write (disk full, permissions) is said on stderr, which goes to the journal, and
    the exit is 0, so the unit's result doesn't change."""
    data = tmp_path / 'lighthouse'
    (data / 'alerts').mkdir(parents=True, mode=0o700)
    os.chmod(data / 'alerts', 0o500)
    under_systemd(monkeypatch, monitor=True, service_result='start-limit-hit')
    try:
        assert alert(data, 'superyak-odo.service', '--monitor') == 0
    finally:
        os.chmod(data / 'alerts', 0o700)
    assert 'could not queue the alert for superyak-odo.service' in capsys.readouterr().err
    assert files(data) == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_alerts.py`
Expected: FAIL at collection: `ImportError: cannot import name 'alerts' from 'superyak_peer'`.

- [ ] **Step 3: Create `peer/superyak_peer/alerts.py`**

```python
"""Service alerts (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S9-S14): one checked line per
failure, queued as a private file that station-notices lists and Odo posts once in Ops. Standard library only. The
notifier reads nothing from the environment but systemd's result variables, and never a journal line (S11)."""
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
from .backups import REASONS, SEE_LOG
from .ships import safe_line

UNIT = re.compile(r'superyak-[a-z0-9-]{1,60}\.service')
RESULTS = frozenset({'success', 'protocol', 'timeout', 'exit-code', 'signal', 'core-dump', 'watchdog', 'start-limit-hit',
                     'resources', 'oom-kill'})
STATUS = re.compile(r'[0-9]{1,3}|[A-Z0-9+]{1,16}')
EXIT_CODES = frozenset({'exited', 'killed', 'dumped'})
KILLED = frozenset({'signal', 'core-dump', 'oom-kill'})
TIMER_UNITS = {'superyak-backup.service': 'the nightly backup', 'superyak-restore-test.service': 'the monthly restore test'}
ALERT_FILE = re.compile(r'([0-9a-f]{12})\.json')
KINDS = ('stopped', 'down', 'failed')
KEPT_DAYS = 30
SINCE_BEFORE = 600
LINE_LIMIT = 400
DAY = 86400


class Refused(Exception):
    """Exit 2 (Error handling): a run outside systemd, or an invalid unit. Nothing is queued."""


def systemd_fields(environ, monitor):
    """S11: only SERVICE_RESULT, EXIT_CODE and EXIT_STATUS (their MONITOR_* forms for an OnFailure= handler), each
    checked. Nothing else is read from the environment."""
    prefix = 'MONITOR_' if monitor else ''
    result = environ.get(prefix + 'SERVICE_RESULT')
    if result is None:
        raise Refused(f'station-alert runs under systemd only: {prefix}SERVICE_RESULT is not set')
    code, status = environ.get(prefix + 'EXIT_CODE'), environ.get(prefix + 'EXIT_STATUS')
    return {'result': result if result in RESULTS else 'unknown',
            'exit_code': code if code in EXIT_CODES else None,
            'exit_status': status if status is not None and STATUS.fullmatch(status) else None}


def kind_for(unit, monitor):
    """S11: ExecStopPost= gives stopped; --monitor gives failed for the backup and restore-test units, down otherwise."""
    if not monitor:
        return 'stopped'
    return 'failed' if unit in TIMER_UNITS else 'down'


def _local(at, fmt='%H:%M on %Y-%m-%d'):
    """S11: times in the Pi's local zone, with the date."""
    return time.strftime(fmt, time.localtime(at))


def failure_reason(alert):
    """S11: the reason from the exit code (Error handling), or the words for a systemd result."""
    result, status = alert['result'], alert['exit_status']
    if result == 'exit-code' and status and status.isdigit():
        return REASONS.get(int(status), SEE_LOG)
    if result == 'timeout':
        return 'it ran past its time limit'
    if result in KILLED:
        return f'it was killed ({status})' if status else 'it was killed'
    return SEE_LOG


def render(alert):
    """S11's templates. Every value was checked before it got here, and the line still goes through safe_line."""
    unit, at = alert['unit'], alert['at']
    since = min(at, alert['held_since'] or at) - SINCE_BEFORE  # 10 minutes before the earliest failure it reports
    log = f"Log on the Pi: journalctl --user-unit {unit} --since '{_local(since, '%Y-%m-%d %H:%M')}'."
    when, name = _local(at), unit.removesuffix('.service')
    if alert['kind'] == 'stopped':
        status = f", status {alert['exit_status']}" if alert['exit_status'] else ''
        line = (f'Station alert: {name} stopped unexpectedly at {when} ({alert["result"]}{status}). '
                f'systemd restarts it unless it was being stopped. {log}')
        held = alert['held_back']
        if held:
            first = alert['held_since']
            day = _local(first, '%H:%M') if _local(first, '%Y-%m-%d') == _local(at, '%Y-%m-%d') else _local(first)
            line += f' {held} more {"stop" if held == 1 else "stops"} since {day} {"was" if held == 1 else "were"} held back.'
    elif alert['kind'] == 'down':
        line = f'Station alert: {name} is down since {when}: systemd stopped restarting it ({alert["result"]}). {log}'
    else:
        line = f'Station alert: {TIMER_UNITS[unit]} failed at {when}: {failure_reason(alert)}. The earlier copies are kept. {log}'
    return safe_line(line, LINE_LIMIT)


def _queue_dir(alerts_dir):
    """S10: <data-dir>/alerts/, 0700; never a symlink."""
    alerts_dir = Path(alerts_dir)
    if alerts_dir.is_symlink():
        raise OSError(f'{alerts_dir} is a symlink')
    alerts_dir.mkdir(mode=0o700, exist_ok=True)
    return alerts_dir


def _write_private(path, data):
    """A 0600 file through a temporary file and a rename, fsynced first, so a power cut can't leave an empty file under
    a final name."""
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def record(alerts_dir, unit, kind, fields, now):
    """S10: queue one alert, its text rendered once, so a repeated listing posts the same words. Returns the alert."""
    alerts_dir = _queue_dir(alerts_dir)
    alert = {'id': secrets.token_hex(6), 'unit': unit, 'kind': kind, 'at': now, **fields, 'held_back': 0, 'held_since': None}
    alert['text'] = render(alert)
    _write_private(alerts_dir / f'{alert["id"]}.json', alert)
    return alert


def queued(alerts_dir):
    """Every readable alert, oldest first. A file that is empty, half-written or not shaped like ours is skipped, never
    fatal: station-notices runs under Odo's check=True."""
    try:
        entries = list(os.scandir(alerts_dir))
    except OSError:
        return []
    found = []
    for entry in entries:
        match = ALERT_FILE.fullmatch(entry.name)
        if not match or not entry.is_file(follow_symlinks=False):
            continue
        try:
            alert = json.loads(Path(entry.path).read_text())
        except (OSError, ValueError):
            continue
        if (isinstance(alert, dict) and alert.get('id') == match[1] and isinstance(alert.get('unit'), str)
                and UNIT.fullmatch(alert['unit']) and alert.get('kind') in KINDS
                and isinstance(alert.get('at'), (int, float)) and isinstance(alert.get('text'), str)):
            found.append(alert)
    return sorted(found, key=lambda alert: (alert['at'], alert['id']))


def clean(alerts_dir, now):
    """S10: alert files more than 30 days old are deleted each time the notifier runs."""
    for alert in queued(alerts_dir):
        if alert['at'] < now - KEPT_DAYS * DAY:
            (Path(alerts_dir) / f'{alert["id"]}.json').unlink(missing_ok=True)


def station_alert(data_dir, unit, *, monitor, environ, now=None):
    """The station-alert command (S9-S11). Refused (exit 2) outside systemd or for an invalid unit. A queue it can't
    write is said on stderr, which goes to the journal, and the exit is still 0: the unit's result never changes."""
    if not isinstance(unit, str) or not UNIT.fullmatch(unit):
        raise Refused('the unit must look like superyak-<name>.service')
    fields = systemd_fields(environ, monitor)
    now = time.time() if now is None else now
    alerts_dir = Path(data_dir) / 'alerts'
    try:
        clean(alerts_dir, now)  # S10: each time the notifier runs, clean stops included (review N1)
        if fields['result'] == 'success':
            return None  # a clean stop: deploy restarts, systemctl stop, shutdown, and the stops Requires= carries along
        return record(alerts_dir, unit, kind_for(unit, monitor), fields, now)
    except OSError as error:
        print(f'station-alert: could not queue the alert for {unit}: {type(error).__name__}: {error.strerror or error}', file=sys.stderr)
        return None
```

- [ ] **Step 4: Add the command**

In `peer/superyak_peer/__main__.py`, after the `restore_cmd` arguments:

```python
    alert_cmd = commands.add_parser('station-alert', help='Run by systemd only: queue one alert line for Odo to post in Ops')
    alert_cmd.add_argument('--data-dir', type=Path, default=Path('.engram/home'))
    alert_cmd.add_argument('--unit', required=True)
    alert_cmd.add_argument('--monitor', action='store_true', help="As an OnFailure= handler: read systemd's MONITOR_* variables")
```

and after the `station-restore-test` dispatch:

```python
        elif args.command == 'station-alert':
            from .alerts import Refused, station_alert
            try:
                station_alert(args.data_dir, args.unit, monitor=args.monitor, environ=os.environ)
            except Refused as refused:
                parser.exit(2, f'station-alert: {refused}\n')
```

Add `"superyak_peer/alerts.py",` after `"superyak_peer/access_requests.py",` in both lists of `peer/pyproject.toml`,
and `"tests/test_alerts.py",` after `"tests/test_access_requests.py",` in the sdist list.

- [ ] **Step 5: Run the tests to see them pass**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_alerts.py tests/test_packaging.py`
Expected: all passed.

- [ ] **Step 6: Mutation checks** (`PYTHONDONTWRITEBYTECODE=1`, caches cleared before each)

| Mutation | Must fail |
|---|---|
| R10 (the spec's): drop `if fields['result'] == 'success': return None` | `test_a_crash_queues_one_alert_and_a_clean_stop_queues_none` |
| R10: `kind_for` returns `down` for every `--monitor` run | `test_monitor_kinds` |
| R12: `UNIT = re.compile(r'superyak-\S{1,60}\.service')` | `test_alert_lines_hold_no_log_lines_mentions_or_unchecked_values` |
| R12: keep an unknown result as given (`'result': result`) | same |
| R12: `failure_reason` maps every exit code to `see the log` | `test_failed_backup_and_restore_runs_name_their_reason` |
| Error handling: drop the `except OSError` in `station_alert` | `test_a_notifier_that_cannot_write_its_queue_exits_0` |
| S10, review N1: clean only when an alert is queued (move `clean` after the `success` return) | `test_a_crash_queues_one_alert_and_a_clean_stop_queues_none` |

- [ ] **Step 7: Commit**

```bash
git add peer/superyak_peer/alerts.py peer/superyak_peer/__main__.py peer/pyproject.toml peer/tests/test_alerts.py
git commit -m "Alerts, task 8: station-alert queues one checked line per failure, never log text (R10, R12)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: Holding back and backing off (R11)

**Files:**
- Modify: `peer/superyak_peer/alerts.py` (`record` replaced; `_lock`, `_rates`, `_hold`)
- Test: `peer/tests/test_alerts.py`

**Interfaces:**
- Consumes: Task 8.
- Produces: `WINDOW`, `MAX_WINDOW`, `GIVE_UPS_PER_DAY`, `LOCK_WAIT`, `_rates(alerts_dir) -> dict`,
  `_state(value) -> dict` (one unit's record with every field of the wrong type dropped),
  `record(alerts_dir, unit, kind, fields, now, *, lock_wait=LOCK_WAIT) -> dict | None` (None when held back).
  `alerts/rate.json` maps each unit to `{window, until, last, held, held_since, give_ups}`; Task 10's
  `describe_queue` reads `held` and `held_since` from it.

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_alerts.py`:

```python
def test_stopped_alerts_are_held_back_and_back_off_per_unit(tmp_path, utc):
    """R11, with a fake clock: one stopped line per unit per window. The window doubles within an unbroken burst, up to
    6 hours, and a full window without a failure ends the burst. down is never windowed, up to 6 per unit in a day."""
    queue, ship = tmp_path / 'alerts', 'superyak-ship.service'

    def at(minutes):
        return T0 + minutes * 60

    six = [alerts.record(queue, ship, 'stopped', CRASH, at(m)) for m in (0, 2, 4, 6, 8, 10)]
    assert [one is not None for one in six] == [True, False, False, False, False, False]   # 6 crashes in 10 minutes: one file
    second = alerts.record(queue, ship, 'stopped', CRASH, at(31))
    assert (second['held_back'], second['held_since']) == (5, at(2))
    assert second['text'].endswith(f' 5 more stops since {local(at(2), "%H:%M")} were held back.')
    assert alerts.record(queue, ship, 'stopped', CRASH, at(61)) is None                     # the second window is 60 minutes
    assert alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, at(61)) is not None   # windows are per unit
    downs = [alerts.record(queue, ship, 'down', GIVE_UP, at(m)) for m in range(62, 69)]
    assert [one is not None for one in downs] == [True] * 6 + [False]                       # inside the window; the 7th held
    third = alerts.record(queue, ship, 'stopped', CRASH, at(121))                            # a full 60 minutes since 61
    assert third['held_back'] == 2                                                         # the stop at 61 and the 7th down
    assert third['text'].endswith(f' 2 more stops since {local(at(61), "%H:%M")} were held back.')
    assert alerts.record(queue, ship, 'stopped', CRASH, at(140)) is None                     # the burst ended: 30 minutes again,
    assert alerts.record(queue, ship, 'stopped', CRASH, at(152)) is not None                 # so 152 is past it
    loop = tmp_path / 'loop'                                                                 # a watcher crash-looping for a day
    posted = [m for m in range(0, 1440, 5) if alerts.record(loop, 'superyak-odo.service', 'stopped', CRASH, at(m))]
    assert posted == [0, 30, 90, 210, 450, 810, 1170]                                        # windows of 30, 60, 120, 240, 360, 360
    assert [m for m in posted if m < 480] == [0, 30, 90, 210, 450]                           # overnight: 5 lines, not 16


def test_the_lock_fallback_queues_anyway(tmp_path):
    """R11: with alerts/.lock held by another process, the alert is queued after 5 s, without the rate record: a
    duplicate beats a lost alert."""
    queue = tmp_path / 'alerts'
    queue.mkdir(mode=0o700)
    holder = subprocess.Popen([sys.executable, '-c', HOLD, str(queue / '.lock')], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'held'
        started = time.monotonic()
        one = alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, T0)
        waited = time.monotonic() - started
    finally:
        holder.kill()
        holder.wait()
    assert alerts.LOCK_WAIT == 5 and 5 <= waited < 8
    assert one is not None and [found['id'] for _, found in files(tmp_path)] == [one['id']]
    assert not (queue / 'rate.json').exists()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_alerts.py -k "held_back or lock_fallback"`
Expected: FAIL: every crash is queued (`[True, True, …]`), and `alerts` has no `LOCK_WAIT`.

- [ ] **Step 3: Hold back and back off in `peer/superyak_peer/alerts.py`**

Add `from contextlib import contextmanager` and `import fcntl` to the imports, and after `KEPT_DAYS`:

```python
WINDOW, MAX_WINDOW = 1800, 6 * 3600
GIVE_UPS_PER_DAY = 6
LOCK_WAIT = 5
```

Replace `record` with:

```python
@contextmanager
def _lock(path, wait):
    """S12: records are written under a flock on alerts/.lock. After `wait` seconds without it, go on unlocked."""
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    locked = False
                    break
                time.sleep(0.1)
        yield locked
    finally:
        os.close(fd)


def _rates(alerts_dir):
    """alerts/rate.json; a missing or garbled file starts fresh."""
    try:
        rates = json.loads((Path(alerts_dir) / 'rate.json').read_text())
    except (OSError, ValueError):
        return {}
    return rates if isinstance(rates, dict) else {}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _state(value):
    """One unit's record from rate.json. A field of the wrong type (a hand edit) is dropped, never fatal: a duplicate is
    better than a lost alert (review S2)."""
    value = value if isinstance(value, dict) else {}
    state = {key: value[key] for key in ('window', 'until', 'last', 'held', 'held_since') if _number(value.get(key))}
    give_ups = value.get('give_ups')
    state['give_ups'] = [t for t in give_ups if _number(t)] if isinstance(give_ups, list) else []
    return state


def _hold(state, now, *, stop):
    state['held'] = state.get('held', 0) + 1
    state['held_since'] = state.get('held_since') or now
    if stop:
        state['last'] = now


def record(alerts_dir, unit, kind, fields, now, *, lock_wait=LOCK_WAIT):
    """S12, then S10. A stopped failure inside its unit's window is held back and counted; the window is 30 minutes and
    doubles within an unbroken burst up to 6 hours, and a full window since the unit's last stop ends the burst. down and
    failed are always queued, except a 7th in a day for one unit (the backstop), which is held and counted like a stop.
    Without the lock within 5 s the alert is queued anyway: a duplicate is better than a lost alert. Returns the queued
    alert, or None when it was held back."""
    alerts_dir = _queue_dir(alerts_dir)
    held, held_since = 0, None
    with _lock(alerts_dir / '.lock', lock_wait) as locked:
        if locked:
            rates = _rates(alerts_dir)
            state = rates[unit] = _state(rates.get(unit))
            if kind == 'stopped':
                if now < state.get('until', 0):
                    _hold(state, now, stop=True)
                    _write_private(alerts_dir / 'rate.json', rates)
                    return None
                burst = 'last' in state and now - state['last'] < state.get('window', WINDOW)
                window = min(state.get('window', WINDOW) * 2, MAX_WINDOW) if burst else WINDOW
                held, held_since = state.get('held', 0), state.get('held_since')
                state.update(window=window, until=now + window, last=now, held=0, held_since=None)
            else:
                recent = [t for t in state.get('give_ups', []) if t > now - DAY]
                if len(recent) >= GIVE_UPS_PER_DAY:
                    _hold(state, now, stop=False)
                    state['give_ups'] = recent
                    _write_private(alerts_dir / 'rate.json', rates)
                    return None
                state['give_ups'] = recent + [now]
            _write_private(alerts_dir / 'rate.json', rates)
        alert = {'id': secrets.token_hex(6), 'unit': unit, 'kind': kind, 'at': now, **fields,
                 'held_back': held, 'held_since': held_since}
        alert['text'] = render(alert)
        _write_private(alerts_dir / f'{alert["id"]}.json', alert)
        return alert
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_alerts.py`
Expected: all passed (the lock test takes 5 s).

- [ ] **Step 5: Mutation checks** (`PYTHONDONTWRITEBYTECODE=1`, caches cleared before each)

| Mutation | Must fail |
|---|---|
| R11 (the spec's): the window never doubles (`window = WINDOW`) | `test_stopped_alerts_are_held_back_and_back_off_per_unit` |
| R11: no cap (`MAX_WINDOW = 10**9`) | same |
| R11: a burst never ends (`burst = 'last' in state`) | same |
| R11: hold `down` inside a stop window as well | same |
| R11: drop the backstop | same |
| R11: without the lock, drop the alert (`return None` when not `locked`) | `test_the_lock_fallback_queues_anyway` |

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/alerts.py peer/tests/test_alerts.py
git commit -m "Alerts, task 9: one stopped line per unit per window, backing off to 6 hours; give-ups never windowed (R11)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: The listing: `station-notices`, the stale backup, `station-alerts`, and Odo (R13, R14, R15)

**Files:**
- Modify: `peer/superyak_peer/backups.py` (`STALE_AFTER`, `stale_notice`)
- Modify: `peer/superyak_peer/alerts.py` (`listed`, `notices_beside`, `describe_queue`)
- Modify: `peer/superyak_peer/__main__.py:189-190` (`station-notices --backup-dir`), `:271-272` (its dispatch), and the
  `station-alerts` parser and dispatch
- Test: `peer/tests/test_alerts.py`, `peer/tests/test_ship_agent.py` (after
  `test_odo_announces_station_notices_in_ops`, line 191)

**Interfaces:**
- Consumes: Tasks 2, 8 and 9; `Store.station_notices()` (unchanged); Odo's `Watcher` and `StationClient` (unchanged).
- Produces: `backups.STALE_AFTER`, `backups.stale_notice(backup_dir, now) -> dict | None`; `alerts.LISTED_DAYS`,
  `alerts.LISTED_NEWEST`, `alerts.listed(alerts_dir, now) -> list[{'id', 'text'}]`,
  `alerts.notices_beside(data_dir, backup_dir, now) -> list | None` (None when neither directory exists),
  `alerts.describe_queue(alerts_dir, now) -> str`; `station-notices --backup-dir DIR`; `station-alerts --data-dir DIR`.
  Odo posts each `alert-<id>` under client id `notice-alert-<id>`.

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_alerts.py`:

```python
def notices(capsys, data, *extra):
    """station-notices as Odo runs it: (exit code, stdout, stderr)."""
    try:
        cli(['station-notices', '--data-dir', str(data), *map(str, extra)])
        code = 0
    except SystemExit as stopped:
        code = stopped.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_notices_list_queued_alerts_and_are_unchanged_without_them(tmp_path, capsys):
    """R13, R15: without an alert queue or a rotation the output is today's, byte for byte. With 25 stopped alerts and an
    older down, the store's notices come first, then the down and the 20 newest stops, oldest first."""
    store = Store(tmp_path / 'lighthouse')
    store.request_access('Jenn', 'jenn@example.org', 'Andy invited me')
    assert notices(capsys, store.data_dir) == (0, json.dumps(store.station_notices(), indent=2) + '\n', '')
    now, queue = time.time(), store.data_dir / 'alerts'
    down = alerts.record(queue, 'superyak-odo.service', 'down', GIVE_UP, now - 3600)
    stops = [alerts.record(queue, f'superyak-w{i:02d}.service', 'stopped', CRASH, now - (25 - i) * 60) for i in range(25)]
    alerts.record(queue, 'superyak-door.service', 'down', GIVE_UP, now - 8 * 86400)          # older than 7 days
    code, out, err = notices(capsys, store.data_dir)
    listed = json.loads(out)
    assert code == 0 and listed[:1] == store.station_notices()
    assert [notice['id'] for notice in listed[1:]] == [f'alert-{one["id"]}' for one in [down, *stops[5:]]]
    assert listed[1]['text'] == down['text']


def test_notices_still_list_alerts_when_the_store_cannot_open(tmp_path, capsys):
    """R13 (M3): the database overwritten with junk and one alert queued: the alert is listed, the error's class name goes
    to stderr, and the exit is 0. Without either directory the failure is today's."""
    store = Store(tmp_path / 'lighthouse')
    store.db_path.write_bytes(b'not a database ' * 1000)
    with pytest.raises(sqlite3.DatabaseError):
        notices(capsys, store.data_dir)
    one = alerts.record(store.data_dir / 'alerts', 'superyak-lighthouse.service', 'stopped', CRASH, time.time())
    code, out, err = notices(capsys, store.data_dir)
    assert code == 0 and json.loads(out) == [{'id': f'alert-{one["id"]}', 'text': one['text']}]
    assert 'DatabaseError' in err


def test_a_stale_backup_is_announced_once_per_lapse(tmp_path, capsys):
    """R14: a rotation whose newest copy is more than 36 hours old gives one backup-stale-<name> notice, the same on
    every listing; a new copy ends the lapse; no rotation, or an empty one, gives none."""
    data, rotation = tmp_path / 'lighthouse', tmp_path / 'backups' / 'station'
    data.mkdir()
    now = calendar.timegm((2026, 10, 14, 12, 0, 0))

    def copy(at):
        path = rotation / f'peer-{backups.copy_stamp(at)}.sqlite3'
        path.write_bytes(b'copy')
        return path

    assert alerts.notices_beside(data, rotation, now) is None
    rotation.mkdir(parents=True)
    (rotation / 'peer-20261399T000000Z.sqlite3').write_bytes(b'not a time')   # review S1: never the newest copy
    assert alerts.notices_beside(data, rotation, now) == []
    old = copy(now - 36 * 3600)
    assert alerts.notices_beside(data, rotation, now) == []                         # exactly 36 hours: not more than
    first = alerts.notices_beside(data, rotation, now + 60)
    assert first == [{'id': f'backup-stale-{old.name}', 'text': (
        f'Station alert: the newest station backup is from {local(now - 36 * 3600, "%Y-%m-%d %H:%M")}, more than 36 hours '
        'ago. The nightly timer may have stopped. On the Pi: systemctl --user list-timers superyak-backup.timer.')}]
    assert alerts.notices_beside(data, rotation, now + 3600) == first               # once per lapse: the same id
    new = copy(now + 3600)
    assert alerts.notices_beside(data, rotation, now + 7200) == []
    assert [n['id'] for n in alerts.notices_beside(data, rotation, now + 3600 + 37 * 3600)] == [f'backup-stale-{new.name}']
    Store(data)                                                                       # the command, with the real clock
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    real = elsewhere / f'peer-{backups.copy_stamp(time.time() - 40 * 3600)}.sqlite3'
    real.write_bytes(b'copy')
    code, out, err = notices(capsys, data, '--backup-dir', elsewhere)
    assert code == 0 and json.loads(out)[-1]['id'] == f'backup-stale-{real.name}'


def test_a_junk_file_in_the_queue_is_skipped_not_fatal(tmp_path, capsys):
    """Review Focus 5: an empty alert file (a power cut after a rename), a half-written one, a hand-edited one with an at
    sign, and a garbled rate.json. station-notices skips what it can't read, lists the rest without the at sign and exits
    0, because Odo runs it with check=True; the next alert still queues. A rate.json of the wrong shape loses no alert
    and doesn't break station-alerts (review S2)."""
    store = Store(tmp_path / 'lighthouse')
    queue = store.data_dir / 'alerts'
    good = alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, time.time())
    (queue / '000000000000.json').write_bytes(b'')
    (queue / 'abcdefabcdef.json').write_text('{"id": "abcdefabcdef", "unit": ')
    edited = {'id': '0123456789ab', 'unit': 'superyak-odo.service', 'kind': 'down', 'at': time.time() + 1, 'text': 'run this @serenity'}
    (queue / '0123456789ab.json').write_text(json.dumps(edited))
    (queue / 'rate.json').write_text('not json')
    code, out, err = notices(capsys, store.data_dir)
    assert code == 0 and [notice['id'] for notice in json.loads(out)] == [f'alert-{good["id"]}', 'alert-0123456789ab']
    assert '@' not in out
    assert alerts.record(queue, 'superyak-lighthouse.service', 'stopped', CRASH, time.time()) is not None
    wrong = {'superyak-door.service': {'until': 'x', 'window': 'y', 'held': 'z', 'held_since': 'w', 'give_ups': 'v'}}
    (queue / 'rate.json').write_text(json.dumps(wrong))
    assert 'Nothing is held back.' in alerts.describe_queue(queue, time.time())
    assert alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, time.time()) is not None
    assert alerts.record(queue, 'superyak-door.service', 'down', GIVE_UP, time.time()) is not None


def test_station_alerts_shows_the_queue_and_what_is_held_back(tmp_path, capsys):
    """S13, and the words Deploy steps 4 and 5 check: 'No alerts are queued.', then 'N stops held back'."""
    data = tmp_path / 'lighthouse'
    data.mkdir()
    cli(['station-alerts', '--data-dir', str(data)])
    assert capsys.readouterr().out == 'No alerts are queued.\nNothing is held back.\n'
    queue = data / 'alerts'
    first = alerts.record(queue, 'superyak-alerttest.service', 'stopped', CRASH, time.time() - 30)
    for seconds in (20, 10, 5):
        alerts.record(queue, 'superyak-alerttest.service', 'stopped', CRASH, time.time() - seconds)
    cli(['station-alerts', '--data-dir', str(data)])
    out = capsys.readouterr().out
    assert f'stopped  superyak-alerttest.service  {first["id"]}' in out
    assert 'superyak-alerttest.service: 3 stops held back since ' in out
```

In `peer/tests/test_ship_agent.py`, after `test_odo_announces_station_notices_in_ops` (line 191):

```python
def test_odo_posts_a_queued_alert_in_ops_once(env, tmp_path):
    """R13 (spec S10, S13): an alert queued while Odo can't reach the station waits in the queue; the next cycle posts
    it in Ops through the existing notices path, and the one after posts nothing."""
    from superyak_agent.station import StationClient, StationError
    from superyak_agent.watch import Watcher
    from superyak_peer import alerts
    app, clients, users, clock = env
    store = app.state.store
    odo = store.create_station_ship('odo', 'Odo')
    key = store.issue_ship_key(odo['id'])
    ops = clients[2].post('/api/chats', json={'title': 'Ops', 'member_ids': [odo['id']]}).json()['id']
    down, send = [False], transport_for(app)

    def flaky(method, url, headers, data):
        return (503, b'{"error": "The station is restarting"}') if down[0] else send(method, url, headers, data)

    notices = [sys.executable, '-m', 'superyak_peer', 'station-notices', '--data-dir', str(store.data_dir)]
    config = {'station': 'http://testserver', 'origin': None, 'ship': 'odo', 'ship_name': 'Odo', 'owner_id': None, 'key': key, 'workspace': str(tmp_path)}
    watcher = Watcher(StationClient('http://testserver', key, transport=flaky), config, tmp_path / 'odo.json', None,
                      notices_command=notices, resident=True)
    assert watcher.cycle() == 0
    down[0] = True
    one = alerts.record(store.data_dir / 'alerts', 'superyak-lighthouse.service', 'stopped',
                        {'result': 'exit-code', 'exit_code': 'exited', 'exit_status': '1'}, time.time())
    with pytest.raises(StationError):
        watcher.cycle()
    down[0] = False
    assert watcher.cycle() == 1
    posted = clients[2].get(f'/api/chats/{ops}').json()['messages'][-1]
    assert posted['body'] == one['text'] and posted['client_message_id'] == f'notice-alert-{one["id"]}'
    assert watcher.cycle() == 0
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_alerts.py tests/test_ship_agent.py -k "notices or stale or junk or station_alerts or queued_alert"`
Expected: FAIL: the listing has no alerts, `alerts.notices_beside` doesn't exist, and `station-alerts` is an invalid
choice.

- [ ] **Step 3: Add the stale notice to `peer/superyak_peer/backups.py`**

After `TEMP_MAX_AGE`:

```python
STALE_AFTER = 36 * 3600
```

After `newest_copy`:

```python
def stale_notice(backup_dir, now):
    """S14: one notice while the newest copy is more than 36 hours old. Its id names that copy, so it changes as soon as
    a new copy appears; no rotation, or an empty one, gives none."""
    newest = newest_copy(backup_dir)
    if newest is None or now - copy_time(newest) <= STALE_AFTER:
        return None
    taken = time.strftime('%Y-%m-%d %H:%M', time.localtime(copy_time(newest)))
    return {'id': f'backup-stale-{newest.name}',
            'text': f'Station alert: the newest station backup is from {taken}, more than 36 hours ago. The nightly timer '
                    'may have stopped. On the Pi: systemctl --user list-timers superyak-backup.timer.'}
```

- [ ] **Step 4: Add the listing to `peer/superyak_peer/alerts.py`**

Change the backups import to `from .backups import REASONS, SEE_LOG, stale_notice`, add after `KEPT_DAYS`:

```python
LISTED_DAYS, LISTED_NEWEST = 7, 20
```

and at the end of the module:

```python
def listed(alerts_dir, now):
    """S10: the last 7 days' alerts, oldest first: at most the 20 newest, plus every down and failed alert of those
    days, so a give-up line is never pushed out by restarts. The text goes through safe_line again on the way out."""
    recent = [alert for alert in queued(alerts_dir) if alert['at'] > now - LISTED_DAYS * DAY]
    newest = {alert['id'] for alert in recent[-LISTED_NEWEST:]}
    return [{'id': f'alert-{alert["id"]}', 'text': safe_line(alert['text'], LINE_LIMIT)}
            for alert in recent if alert['id'] in newest or alert['kind'] != 'stopped']


def notices_beside(data_dir, backup_dir, now):
    """What station-notices appends to Store.station_notices() (S10, S14). None when neither the alert queue nor the
    rotation exists, so the command prints exactly what it printed before (R15)."""
    alerts_dir, backup_dir = Path(data_dir) / 'alerts', Path(backup_dir)
    if not alerts_dir.is_dir() and not backup_dir.is_dir():
        return None
    stale = stale_notice(backup_dir, now)
    return listed(alerts_dir, now) + ([stale] if stale else [])


def describe_queue(alerts_dir, now):
    """make station-alerts (S13): the queue and the held-back counts. Every value here is ours: checked units and
    rendered lines."""
    waiting = queued(alerts_dir)
    lines = ['Queued alerts, oldest first (Odo posts each once in Ops; files over 30 days old are deleted):'] if waiting else ['No alerts are queued.']
    lines += [f'  {_local(alert["at"], "%Y-%m-%d %H:%M")}  {alert["kind"]:<7}  {alert["unit"]}  {alert["id"]}' for alert in waiting]
    held = [(unit, state) for unit, state in ((unit, _state(value)) for unit, value in sorted(_rates(alerts_dir).items()))
            if UNIT.fullmatch(unit) and state.get('held') and state.get('held_since')]
    lines.append("Held back (counted in that unit's next stopped line, or only shown here):" if held else 'Nothing is held back.')
    lines += [f'  {unit}: {state["held"]} {"stop" if state["held"] == 1 else "stops"} held back since {_local(state["held_since"])}'
              for unit, state in held]
    return '\n'.join(lines)
```

- [ ] **Step 5: Wire the commands in `peer/superyak_peer/__main__.py`**

After `notices.add_argument('--data-dir', …)` (line 190):

```python
    notices.add_argument('--backup-dir', type=Path, help='The backup rotation (default: backups/station beside the data dir)')
```

After the `alert_cmd` arguments:

```python
    queue_cmd = commands.add_parser('station-alerts', help='Trusted local: show the alert queue and what is held back')
    queue_cmd.add_argument('--data-dir', type=Path, default=Path('.engram/home'))
```

Replace the `station-notices` branch (lines 271-272) with:

```python
        elif args.command == 'station-notices':
            import time
            from .alerts import notices_beside
            from .backups import default_backup_dir
            extra = notices_beside(args.data_dir, args.backup_dir or default_backup_dir(args.data_dir), time.time())
            if extra is None:  # R15: neither directory, so exactly today's output and today's failures
                print(json.dumps(Store(args.data_dir).station_notices(), indent=2))
            else:
                try:
                    listed = Store(args.data_dir).station_notices()
                except Exception as error:  # noqa: BLE001 - S10: a damaged store must not silence the alerts
                    print(f'station-notices: listing the queued alerts only; the store could not be read ({type(error).__name__})',
                          file=sys.stderr)
                    listed = []
                print(json.dumps(listed + extra, indent=2))
```

and after the `station-alert` dispatch:

```python
        elif args.command == 'station-alerts':
            import time
            from .alerts import describe_queue
            print(describe_queue(args.data_dir / 'alerts', time.time()))
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_alerts.py tests/test_ship_agent.py tests/test_ships.py tests/test_access_requests.py`
Expected: all passed; `test_odo_announces_station_notices_in_ops` and `test_station_notices_list_requests_and_docked_ships`
are unchanged and still pass.

- [ ] **Step 7: Mutation checks** (`PYTHONDONTWRITEBYTECODE=1`, caches cleared before each)

| Mutation | Must fail |
|---|---|
| R15: drop the `extra is None` branch, so every listing goes through the `try` | `test_notices_still_list_alerts_when_the_store_cannot_open` |
| R13: list only the 20 newest (drop `or alert['kind'] != 'stopped'`) | `test_notices_list_queued_alerts_and_are_unchanged_without_them` |
| R13: list the alerts before the store's notices | same |
| R13: read the store first and let its error escape | `test_notices_still_list_alerts_when_the_store_cannot_open` |
| R14: `<` instead of `<=` against `STALE_AFTER` | `test_a_stale_backup_is_announced_once_per_lapse` |
| Review Focus 5: `queued` stops catching `ValueError` | `test_a_junk_file_in_the_queue_is_skipped_not_fatal` |
| Review Focus 5: `listed` returns `alert['text']` without `safe_line` | same |
| Review S2: `record` takes `rates.get(unit)` as it is, without `_state` | same |

- [ ] **Step 8: Run all three suites and commit**

Run:
- `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider`
- `cd agent && uv run --locked --extra dev python -m pytest -q`

Expected: all passed. Nothing under `agent/` changed; the agent suite proves it.

```bash
git add peer/superyak_peer/backups.py peer/superyak_peer/alerts.py peer/superyak_peer/__main__.py peer/tests/test_alerts.py peer/tests/test_ship_agent.py
git commit -m "Alerts, task 10: station-notices lists the queue and a stale backup; station-alerts; Odo posts each once (R13-R15)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## The units and the make targets (S8)

### Task 11: Units, timers, the alert drop-in, the make targets, and the runbook (R16, R17)

**Files:**
- Create: `peer/systemd/superyak-backup.service`, `peer/systemd/superyak-backup.timer`,
  `peer/systemd/superyak-restore-test.service`, `peer/systemd/superyak-restore-test.timer`,
  `peer/systemd/superyak-alert@.service`, `peer/systemd/50-alerts.conf`
- Create: `docs/station-restore.md`
- Modify: `Makefile:26-31` (variables), `:40` (`.PHONY`), `:54` (help lines), `:198-200` (the targets, after
  `station-bridge station-unbridge`)
- Modify: `peer/README.md:306-308` (one paragraph before "Create the resident ship")
- Modify: `peer/pyproject.toml` (the six `systemd/` files and `tests/test_station_units.py` in the sdist list)
- Test: `peer/tests/test_station_units.py` (new)

**Interfaces:**
- Consumes: the commands of Tasks 1–10.
- Produces: the units S8 and S9 name; `make station-backup [OUTPUT=…]`, `make station-restore-test [BACKUP=…]`,
  `make station-restore-reconcile DB=… [REPLACED=…]`, `make station-alerts`, `make station-units`,
  `make station-units-remove`; Make variables `STATION_BACKUPS` and `SYSTEMD_USER`. Task 13 runs them on the Pi.

- [ ] **Step 1: Write the failing tests**

Create `peer/tests/test_station_units.py`:

```python
"""The station's units, timers and alert drop-in (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md,
S8, S9; R16, R17). Nothing here runs the real systemctl or touches ~/.config/systemd/user."""
import configparser
import os
from pathlib import Path
import shutil
import stat
import subprocess
import pytest

UNITS = Path(__file__).resolve().parents[1] / 'systemd'
REPO = Path(__file__).resolve().parents[2]
PYTHON = '%h/superyak/peer/.venv/bin/python -I -m superyak_peer'
DATA = '%h/.local/share/superyak/lighthouse'
ROTATION = '%h/.local/share/superyak/backups/station'
INSTALLED = ['superyak-backup.service', 'superyak-backup.timer', 'superyak-restore-test.service',
             'superyak-restore-test.timer', 'superyak-alert@.service']
EXPECTED = {
    'superyak-backup.service': {
        'Unit': {'After': 'superyak-lighthouse.service', 'OnFailure': 'superyak-alert@%n.service'},
        'Service': {'Type': 'oneshot', 'WorkingDirectory': '%h/superyak/peer',
                    'EnvironmentFile': '-%h/.config/superyak/backup.env',
                    'ExecStart': f'{PYTHON} station-backup --data-dir {DATA} --backup-dir {ROTATION} --copy-to=${{SUPERYAK_BACKUP_COPY_TO}}',
                    'Nice': '10', 'IOSchedulingClass': 'idle', 'TimeoutStartSec': '15min', 'MemoryMax': '512M'},
    },
    'superyak-backup.timer': {
        'Unit': {},
        'Timer': {'OnCalendar': '*-*-* 03:30:00', 'RandomizedDelaySec': '30min', 'Persistent': 'true'},
        'Install': {'WantedBy': 'timers.target'},
    },
    'superyak-restore-test.service': {
        'Unit': {'After': 'superyak-backup.service', 'OnFailure': 'superyak-alert@%n.service'},
        'Service': {'Type': 'oneshot', 'WorkingDirectory': '%h/superyak/peer',
                    'ExecStart': f'{PYTHON} station-restore-test --backup-dir {ROTATION}',
                    'TimeoutStartSec': '10min', 'MemoryMax': '1G'},
    },
    'superyak-restore-test.timer': {
        'Unit': {},
        'Timer': {'OnCalendar': '*-*-01 04:30:00', 'RandomizedDelaySec': '30min', 'Persistent': 'true'},
        'Install': {'WantedBy': 'timers.target'},
    },
    'superyak-alert@.service': {
        'Unit': {},
        'Service': {'Type': 'oneshot', 'TimeoutStartSec': '1min',
                    'ExecStart': f'{PYTHON} station-alert --data-dir {DATA} --unit %i --monitor'},
    },
    '50-alerts.conf': {
        'Unit': {'OnFailure': 'superyak-alert@%n.service'},
        'Service': {'ExecStopPost': f'-{PYTHON} station-alert --data-dir {DATA} --unit %n'},
    },
}


def sections(name):
    """A unit file as {section: {key: value}}, Description (free text) left out."""
    parser = configparser.ConfigParser(interpolation=None, strict=True, delimiters=('=',))
    parser.optionxform = str
    parser.read_string((UNITS / name).read_text())
    return {section: {key: value for key, value in parser[section].items() if key != 'Description'} for section in parser.sections()}


def test_units_say_what_the_spec_says():
    """R16: the timers (OnCalendar, Persistent=true, WantedBy=timers.target), the oneshots (OnFailure=, no Restart=),
    the alert template (%i, no OnFailure= of its own) and the drop-in (ExecStopPost=- with -I) are exactly S8's and S9's."""
    assert sorted(path.name for path in UNITS.iterdir()) == sorted(INSTALLED + ['50-alerts.conf'])
    for name, expected in EXPECTED.items():
        assert sections(name) == expected, name


VENV_PYTHON = Path.home() / 'superyak' / 'peer' / '.venv' / 'bin' / 'python'


@pytest.mark.skipif(not VENV_PYTHON.exists() or not shutil.which('systemd-analyze'),
                    reason='verify fails on the missing %h/superyak/peer/.venv/bin/python away from the station host')
def test_units_pass_systemd_analyze_verify(tmp_path):
    """R16, spec Testing: systemd-analyze --user verify passes, with no warning, on the units and on a throwaway service
    carrying the drop-in. It only parses: nothing is loaded into the user manager."""
    probe = tmp_path / 'units'
    shutil.copytree(UNITS, probe)
    (probe / 'superyak-verifycheck.service').write_text('[Unit]\nDescription=Throwaway unit for the drop-in\n\n[Service]\nExecStart=/bin/true\n')
    (probe / 'superyak-verifycheck.service.d').mkdir()
    shutil.move(probe / '50-alerts.conf', probe / 'superyak-verifycheck.service.d' / '50-alerts.conf')
    files = [str(probe / name) for name in INSTALLED + ['superyak-verifycheck.service']]
    result = subprocess.run(['systemd-analyze', '--user', 'verify', *files], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0 and result.stderr == '', result.stderr


@pytest.mark.skipif(not (REPO / 'Makefile').is_file() or not shutil.which('make'), reason='needs the parent repository Makefile')
def test_station_units_install_and_remove_only_their_own_files(tmp_path):
    """Review Focus 2: make station-units and station-units-remove on a stand-in for ~/.config/systemd/user, with
    systemctl shimmed on PATH and HOME in tmp_path. They refuse without a station database, install the five files and the
    drop-in on the five services and a project ship's watcher, and remove exactly that, keeping Andy's own drop-in."""
    units, data, home, shim = tmp_path / 'systemd-user', tmp_path / 'lighthouse', tmp_path / 'home', tmp_path / 'bin'
    for directory in (units, data, home, shim):
        directory.mkdir()
    services = ['superyak-lighthouse', 'superyak-door', 'superyak-ship', 'superyak-odo', 'superyak-wormhole',
                'superyak-ship-serenity-bricks']
    for service in services:
        (units / f'{service}.service').write_text('[Service]\nExecStart=/bin/true\n')
    andys = units / 'superyak-door.service.d' / '10-andy.conf'
    andys.parent.mkdir(mode=0o700)          # an existing directory keeps its mode (review N2)
    andys.write_text('[Service]\nNice=5\n')
    calls = tmp_path / 'systemctl.log'
    (shim / 'systemctl').write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\n')
    (shim / 'systemctl').chmod(0o755)
    env = {**os.environ, 'HOME': str(home), 'PATH': f'{shim}:{os.environ["PATH"]}'}

    def make(target):
        return subprocess.run(['make', '-s', target, f'SYSTEMD_USER={units}', f'STATION_DATA={data}'], cwd=REPO, env=env,
                              capture_output=True, text=True, timeout=60)

    before = sorted(str(path.relative_to(units)) for path in units.rglob('*'))
    refused = make('station-units')
    assert refused.returncode != 0 and 'No station database' in refused.stdout + refused.stderr
    assert sorted(str(path.relative_to(units)) for path in units.rglob('*')) == before and not calls.exists()
    (data / 'peer.sqlite3').write_bytes(b'')
    installed = make('station-units')
    assert installed.returncode == 0, installed.stderr
    for name in INSTALLED:
        assert (units / name).read_bytes() == (UNITS / name).read_bytes()
        assert stat.S_IMODE((units / name).stat().st_mode) == 0o644
    for service in services:
        assert (units / f'{service}.service.d' / '50-alerts.conf').read_bytes() == (UNITS / '50-alerts.conf').read_bytes()
    assert stat.S_IMODE(andys.parent.stat().st_mode) == 0o700
    assert calls.read_text().splitlines() == ['--user daemon-reload',
                                              '--user enable --now superyak-backup.timer superyak-restore-test.timer']
    calls.unlink()
    removed = make('station-units-remove')
    assert removed.returncode == 0, removed.stderr
    assert sorted(str(path.relative_to(units)) for path in units.rglob('*')) == before
    assert andys.read_text() == '[Service]\nNice=5\n'
    assert calls.read_text().splitlines() == [
        '--user disable --now superyak-backup.timer superyak-restore-test.timer',
        '--user stop superyak-backup.service superyak-restore-test.service',
        '--user reset-failed superyak-backup.service superyak-restore-test.service superyak-alert@*',
        '--user daemon-reload']
    assert not (home / '.config').exists()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_station_units.py`
Expected: FAIL: `peer/systemd` doesn't exist, and `make station-units` is not a target ("No rule to make target").

- [ ] **Step 3: Create the units in `peer/systemd/`**

`peer/systemd/superyak-backup.service`:

```ini
[Unit]
Description=Superyak station backup: a checked copy of peer.sqlite3 (spec 2026-10-14 S2)
After=superyak-lighthouse.service
OnFailure=superyak-alert@%n.service

[Service]
Type=oneshot
WorkingDirectory=%h/superyak/peer
EnvironmentFile=-%h/.config/superyak/backup.env
ExecStart=%h/superyak/peer/.venv/bin/python -I -m superyak_peer station-backup --data-dir %h/.local/share/superyak/lighthouse --backup-dir %h/.local/share/superyak/backups/station --copy-to=${SUPERYAK_BACKUP_COPY_TO}
Nice=10
IOSchedulingClass=idle
TimeoutStartSec=15min
MemoryMax=512M
```

`peer/systemd/superyak-backup.timer`:

```ini
[Unit]
Description=Nightly Superyak station backup

[Timer]
OnCalendar=*-*-* 03:30:00
RandomizedDelaySec=30min
Persistent=true

[Install]
WantedBy=timers.target
```

`peer/systemd/superyak-restore-test.service`:

```ini
[Unit]
Description=Superyak restore test: a throwaway station from the newest copy (spec 2026-10-14 S7)
After=superyak-backup.service
OnFailure=superyak-alert@%n.service

[Service]
Type=oneshot
WorkingDirectory=%h/superyak/peer
ExecStart=%h/superyak/peer/.venv/bin/python -I -m superyak_peer station-restore-test --backup-dir %h/.local/share/superyak/backups/station
TimeoutStartSec=10min
MemoryMax=1G
```

`peer/systemd/superyak-restore-test.timer`:

```ini
[Unit]
Description=Monthly Superyak restore test

[Timer]
OnCalendar=*-*-01 04:30:00
RandomizedDelaySec=30min
Persistent=true

[Install]
WantedBy=timers.target
```

`peer/systemd/superyak-alert@.service` (`%i` is the raw instance; `%I` would turn its dashes into slashes; no
`OnFailure=` of its own, so it can't recurse):

```ini
[Unit]
Description=Superyak station alert for %i

[Service]
Type=oneshot
TimeoutStartSec=1min
ExecStart=%h/superyak/peer/.venv/bin/python -I -m superyak_peer station-alert --data-dir %h/.local/share/superyak/lighthouse --unit %i --monitor
```

`peer/systemd/50-alerts.conf` (S9's drop-in, verbatim; `make station-units` writes it as
`superyak-<name>.service.d/50-alerts.conf`):

```ini
[Unit]
OnFailure=superyak-alert@%n.service

[Service]
ExecStopPost=-%h/superyak/peer/.venv/bin/python -I -m superyak_peer station-alert --data-dir %h/.local/share/superyak/lighthouse --unit %n
```

- [ ] **Step 4: Add the make targets**

In `Makefile`, after `STATION_DATA ?= …` (line 26):

```make
STATION_BACKUPS ?= $(HOME)/.local/share/superyak/backups/station
SYSTEMD_USER ?= $(HOME)/.config/systemd/user
```

after `ID ?=` (line 31):

```make
OUTPUT ?=
BACKUP ?=
DB ?=
REPLACED ?=
# Spec 2026-10-14 S8, S9: the files make station-units installs, and the services that get the alert drop-in: the five,
# and any project ship's watcher on this machine (a later one gets it when make station-units runs again).
STATION_UNITS := superyak-backup.service superyak-backup.timer superyak-restore-test.service superyak-restore-test.timer superyak-alert@.service
ALERTED_SERVICES = superyak-lighthouse superyak-door superyak-ship superyak-odo superyak-wormhole $(patsubst %.service,%,$(notdir $(wildcard $(SYSTEMD_USER)/superyak-ship-*.service)))
```

Add `station-backup station-restore-test station-restore-reconcile station-alerts station-units station-units-remove`
to `.PHONY` (line 40). After the `station-bridge` help line (line 54):

```make
	@echo "make station-backup [OUTPUT=…]  On the Pi: a checked copy of the station database (the rotation, or OUTPUT)"
	@echo "make station-restore-test [BACKUP=…]  On the Pi: boot a throwaway station from the newest copy (or BACKUP)"
	@echo "make station-restore-reconcile DB=… [REPLACED=…]  On the Pi: runbook step 5 (docs/station-restore.md)"
	@echo "make station-alerts     On the Pi: show the alert queue and what is held back"
	@echo "make station-units      On the Pi: install the backup timers and the alert drop-ins; make station-units-remove undoes it"
```

After the `station-bridge station-unbridge` target (lines 198-200):

```make
station-backup:
	uv run --locked --project peer python -m superyak_peer station-backup --data-dir "$(STATION_DATA)" --backup-dir "$(STATION_BACKUPS)"$(if $(OUTPUT), --output "$(OUTPUT)")

station-restore-test:
	uv run --locked --project peer python -m superyak_peer station-restore-test --backup-dir "$(STATION_BACKUPS)"$(if $(BACKUP), --backup "$(BACKUP)")

station-restore-reconcile:
	@test -n "$(DB)" || { echo 'Usage: make station-restore-reconcile DB=<staged copy> [REPLACED=<the replaced peer.sqlite3>]'; exit 2; }
	uv run --locked --project peer python -m superyak_peer station-restore-reconcile --db "$(DB)" --live-data-dir "$(STATION_DATA)"$(if $(REPLACED), --replaced "$(REPLACED)")

station-alerts:
	uv run --locked --project peer python -m superyak_peer station-alerts --data-dir "$(STATION_DATA)"

station-units:
	@test -f "$(STATION_DATA)/peer.sqlite3" || { echo 'No station database at $(STATION_DATA)/peer.sqlite3: make station-units runs on the station host only'; exit 2; }
	test -d "$(SYSTEMD_USER)" || install -d -m 755 "$(SYSTEMD_USER)"
	for unit in $(STATION_UNITS); do install -m 644 "peer/systemd/$$unit" "$(SYSTEMD_USER)/$$unit" || exit 1; done
	for service in $(ALERTED_SERVICES); do d="$(SYSTEMD_USER)/$$service.service.d"; { test -d "$$d" || install -d -m 755 "$$d"; } && install -m 644 peer/systemd/50-alerts.conf "$$d/50-alerts.conf" || exit 1; done
	systemctl --user daemon-reload
	systemctl --user enable --now superyak-backup.timer superyak-restore-test.timer

station-units-remove:
	-systemctl --user disable --now superyak-backup.timer superyak-restore-test.timer
	-systemctl --user stop superyak-backup.service superyak-restore-test.service
	-systemctl --user reset-failed superyak-backup.service superyak-restore-test.service 'superyak-alert@*'
	for unit in $(STATION_UNITS); do rm -f "$(SYSTEMD_USER)/$$unit"; done
	for dir in "$(SYSTEMD_USER)"/superyak-*.service.d; do if [ -d "$$dir" ]; then rm -f "$$dir/50-alerts.conf"; rmdir "$$dir" 2>/dev/null || true; fi; done
	systemctl --user daemon-reload
```

`station-units` never edits the five unit files; it only adds files beside them, and it never changes the mode of a
directory that already exists (review N2). `station-units-remove` deletes only
the five files it installed and `50-alerts.conf`, and removes a `.d` directory only when that leaves it empty.

- [ ] **Step 5: Check the targets without running them**

Run, from the worktree root: `make -n station-units STATION_DATA=/nonexistent && make -n station-units-remove && make -n station-backup OUTPUT=/tmp/x.sqlite3 && make -n station-restore-reconcile DB=/tmp/a REPLACED=/tmp/b`
Expected: each prints its commands and runs none of them (`-n`). Read them: the backup line ends
`--output "/tmp/x.sqlite3"`, the reconcile line holds `--live-data-dir "…/lighthouse"` and `--replaced "/tmp/b"`, and the
drop-in loop names the five services.

- [ ] **Step 6: Write the runbook, `docs/station-restore.md`**

````markdown
# Restoring the station database

Every room, message, account, ship key and law layer on the station lives in one SQLite file on the Pi,
`~/.local/share/superyak/lighthouse/peer.sqlite3`. A timer copies it every night into
`~/.local/share/superyak/backups/station/`, and a monthly timer boots a throwaway station from the newest copy
(docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md). Restoring a copy over the live file is a person's
step: nothing does it automatically.

Before you start, know two things:
- **Everything said after the copy's time is lost.**
- **A restored copy brings back access that was taken away since:** ended sessions, revoked ship keys, used invitations
  and activations, uncollected docking keys and invitation tokens, decided requests and dockings, removed room and space
  members (Wormhole too, so a room you unbridged is bridged again), higher roles, old passwords and old law layers.
  Step 5 takes back everything that only grants access before the copy goes live, and lists the rest for you.

Run every step on the Pi, from `~/superyak`.

1. **Choose the copy.** `ls -l ~/.local/share/superyak/backups/station/`. The names are UTC times
   (`peer-20261014T033112Z.sqlite3`). Take the newest copy from before the damage.
2. **Test it:** `make station-restore-test BACKUP=<path>`. It must pass.
3. **Stop everything:**
   ```bash
   systemctl --user stop superyak-backup.timer superyak-restore-test.timer superyak-backup.service superyak-door superyak-odo superyak-wormhole superyak-ship superyak-lighthouse
   systemctl --user list-units 'superyak-*'
   ```
   Stop any `superyak-ship-*` watcher the list still shows.
4. **Set the current state aside.** Make a 0700 directory and move `peer.sqlite3` and every `peer.sqlite3-*` into it. A
   `peer.sqlite3-journal` left beside the restored file would be applied to it and corrupt it.
   ```bash
   ASIDE=~/.local/share/superyak/backups/replaced-$(date +%Y%m%d-%H%M%S)
   install -d -m 700 "$ASIDE"
   for f in ~/.local/share/superyak/lighthouse/peer.sqlite3 ~/.local/share/superyak/lighthouse/peer.sqlite3-*; do [ -e "$f" ] && mv "$f" "$ASIDE"/; done
   ls -la "$ASIDE" ~/.local/share/superyak/lighthouse/   # every peer.sqlite3 file is in $ASIDE, none in the data dir
   ```
5. **Stage and reconcile the copy:**
   ```bash
   install -m 600 <copy> "$ASIDE/restored.sqlite3"
   make station-restore-reconcile DB="$ASIDE/restored.sqlite3" REPLACED="$ASIDE/peer.sqlite3"
   ```
   Leave out `REPLACED=` only when the old file won't open; then every docked ship's keys are revoked, and those
   machines dock again. It refuses a swapped `DB=` and `REPLACED=`, the same file twice, and a hard link. Read its
   report. Go on only when it exits 0. If it says the replaced file was treated as absent
   (for example "a hot journal beside it"), the room and space members, admins and law layers weren't compared: check
   them by hand in step 8. If the command was killed rather than finishing, run it again before going on: it rolls back
   what the killed run left when it opens the file.
6. **Put it in place:**
   ```bash
   install -m 600 "$ASIDE/restored.sqlite3" ~/.local/share/superyak/lighthouse/peer.sqlite3
   ```
   The peer identity files stay where they are; nothing here moves them.
7. **Act on the report.** Change again any password it lists that was changed for a reason. Issue again any invitation
   still wanted. Tell the owners of ships whose keys were revoked to dock again. Requests and dockings since the copy
   were expired; their senders ask again, and nothing is approved from memory. If your own account comes back waiting
   for activation, renew it with `bootstrap-super-admin --renew-activation`.
8. **Start the lighthouse and the door.** Set the law layers the report listed as they should be, in the browser. Then
   start ship and odo, run `make station-rooms` and check the `bridged` column before starting wormhole. Check each with
   `is-active`, then start both timers.
   ```bash
   systemctl --user start superyak-lighthouse superyak-door
   # now the law layers, in the browser
   systemctl --user start superyak-ship superyak-odo
   make station-rooms                                   # check the bridged column first
   systemctl --user start superyak-wormhole
   for unit in lighthouse door ship odo wormhole; do printf '%s ' superyak-$unit; systemctl --user is-active superyak-$unit; done
   systemctl --user start superyak-backup.timer superyak-restore-test.timer
   ```
9. **Say in the room** what was restored and from when. Everything said after the copy's time is gone.
````

- [ ] **Step 7: Document the commands in `peer/README.md`**

Before "Create the resident ship, …" (line 308):

```markdown
Backups, the restore test and service alerts are trusted local commands too (spec
`docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md` in the parent repository). `station-backup` writes a
checked copy of `peer.sqlite3` into the rotation, `backups/station/` beside the data directory, and keeps 14 nightly and
8 weekly copies; `--output FILE` writes one copy elsewhere and never replaces a file. `station-restore-test` boots a
throwaway loopback station from the newest copy. `station-restore-reconcile` takes back, on a staged copy, the access a
restore would revive. `station-alert` runs under systemd only and queues one line in `alerts/` in the data directory,
which `station-notices` lists for Odo to post in `Ops`; `station-alerts` shows the queue. In the parent repository these
are `make station-backup [OUTPUT=…]`, `make station-restore-test [BACKUP=…]`, `make station-restore-reconcile DB=…
[REPLACED=…]` and `make station-alerts`; `make station-units` installs the timers, the alert handler and the alert
drop-ins on the station host, and `make station-units-remove` undoes it. Restoring over the live file is a person's
step: `docs/station-restore.md`. A deploy that changes the schema runs `make station-restore-test` after its restart,
and takes its pre-deploy copy with `make station-backup OUTPUT=…`.
```

- [ ] **Step 8: Add the release inventory entries**

In the sdist list of `peer/pyproject.toml`, add after `"scripts/two_peer_check.py",`:

```toml
    "systemd/50-alerts.conf",
    "systemd/superyak-alert@.service",
    "systemd/superyak-backup.service",
    "systemd/superyak-backup.timer",
    "systemd/superyak-restore-test.service",
    "systemd/superyak-restore-test.timer",
```

and `"tests/test_station_units.py",` after `"tests/test_station_cli.py",`. The wheel list doesn't change: units are
installed from the checkout, never from the wheel.

- [ ] **Step 9: Run the tests to see them pass**

Run: `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_station_units.py tests/test_packaging.py`
Expected: all passed. On the Pi, `test_units_pass_systemd_analyze_verify` runs (the venv interpreter exists there);
elsewhere it is skipped.

- [ ] **Step 10: Mutation checks** (`PYTHONDONTWRITEBYTECODE=1`, caches cleared before each)

| Mutation | Must fail |
|---|---|
| R16: drop `[Install]` from `superyak-restore-test.timer` (revision 1's bug, SF1) | `test_units_say_what_the_spec_says` |
| R16: `Restart=on-failure` in `superyak-backup.service` | same |
| R16: drop `-I` from the drop-in's `ExecStopPost=` | same |
| R16: `--unit %I` in `superyak-alert@.service` | same |
| R16: `Type=oneshoot` in `superyak-alert@.service` (verify warns and exits 0) | `test_units_pass_systemd_analyze_verify` (on the Pi) |
| Review Focus 2: `station-units-remove` runs `rm -rf "$$dir"` instead of removing only `50-alerts.conf` | `test_station_units_install_and_remove_only_their_own_files` |
| Review Focus 2: drop the `superyak-ship-*` wildcard from `ALERTED_SERVICES` | same |
| Review Focus 2: drop the `peer.sqlite3` refusal | same |
| Review N2: create each `.d` directory with a bare `install -d -m 755 "$$d"` again | same |

- [ ] **Step 11: Run all three suites and commit**

Run:
- `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider`
- `cd agent && uv run --locked --extra dev python -m pytest -q`
- `cd team && uv run --locked --extra dev python -m pytest -q`

Expected: all passed.

```bash
git add peer/systemd peer/tests/test_station_units.py peer/pyproject.toml peer/README.md Makefile docs/station-restore.md
git commit -m "Units, task 11: the timers, the alert drop-in, the make targets and the restore runbook (R16, R17)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Review, merge and deploy

### Task 12: The whole-branch review (section 2 of the station law)

This task and the next are the lead session's work, never a subagent's: pushing, merging and deploying stay with the
ship section 2 names.

- [ ] **Step 1: Run every suite on the Pi**

Run, from `/home/andy/superyak/.worktrees/backups-alerts`:
- `cd peer && systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider`
- `cd agent && uv run --locked --extra dev python -m pytest -q`
- `cd team && uv run --locked --extra dev python -m pytest -q`

Expected: all passed, with `test_units_pass_systemd_analyze_verify` run, not skipped. Then confirm that every test the
spec names exists, and the plan review's three:

```bash
for name in test_backup_copies_committed_data_from_a_read_only_connection test_copies_are_private_checked_and_appear_whole \
  test_retention_keeps_14_days_and_8_weeks_and_nothing_else test_output_writes_one_checked_copy_and_never_overwrites \
  test_failures_keep_old_copies_and_exit_with_their_code test_copy_to_is_off_by_default_and_refuses_the_same_disk \
  test_health_answers_without_a_session test_restore_test_boots_a_throwaway_station_from_the_newest_copy \
  test_restore_test_failures_clean_up_and_exit_with_their_code test_restore_test_has_no_data_dir_option \
  test_reconcile_takes_back_what_the_restore_revived test_reconcile_without_the_replaced_file_fails_closed \
  test_reconcile_rolls_back_when_a_step_fails test_reconcile_skips_what_an_older_copy_lacks \
  test_reconcile_refuses_the_live_data_dir_and_symlinks test_a_crash_queues_one_alert_and_a_clean_stop_queues_none \
  test_monitor_kinds test_stopped_alerts_are_held_back_and_back_off_per_unit test_the_lock_fallback_queues_anyway \
  test_failed_backup_and_restore_runs_name_their_reason test_alert_lines_hold_no_log_lines_mentions_or_unchecked_values \
  test_notices_list_queued_alerts_and_are_unchanged_without_them test_notices_still_list_alerts_when_the_store_cannot_open \
  test_a_stale_backup_is_announced_once_per_lapse test_odo_posts_a_queued_alert_in_ops_once test_units_say_what_the_spec_says \
  test_reconcile_closes_breakouts_closed_since_the_copy test_reconcile_takes_back_every_other_step \
  test_reconcile_without_a_replaced_file_raises_both_sequences test_reconcile_refuses_a_hard_link_and_a_same_or_older_replaced_file; do
  grep -q "def $name(" peer/tests/*.py || echo "MISSING $name"
done
```

Expected: no output.

- [ ] **Step 2: Share the branch**

Push `backups-alerts` (never `main`): `git push -u origin backups-alerts`.

- [ ] **Step 3: A fresh reviewer gets the whole branch**

Dispatch one reviewer agent with no history of this work. Give it:
- the spec (revision 3) and this plan;
- `git diff main...backups-alerts`;
- the Requirements-to-tasks table, the Review Focus list, and "Decisions this plan makes where the spec is silent".

Ask for:
- a verdict: APPROVE, APPROVE WITH CHANGES or REJECT;
- every requirement R1–R18 without a test that fails when its feature is removed;
- every Deploy step below whose command or expected output doesn't match the code (the `station-alerts` wording, the
  health body, the make variables);
- anything in `station-units`/`station-units-remove` that could touch a file it didn't install.

Fix every must-fix on the branch, test first, and send the changed diff back to the same reviewer until it approves.

- [ ] **Step 4: Post the approval in the room**

Post the reviewer's verdict whole in the room ("Superyak: city of AI", 39fd79, or the current room that replaced it),
with the branch head and the three suite results. Never @mention a ship.

### Task 13: Deploy, with rollback (the spec's Deploy section)

Under section 2 of the station law: a fresh reviewer's approval is posted in the room (Task 12), and the Pi suites pass.
Nothing changes the schema. Nothing @mentions a ship. Section 2 covers merging, restarting and checking the affected
services, and reverting. It does not cover new standing jobs or drop-ins on Andy's five services, so **steps 4 and 5
wait for Andy's go-ahead**, in his own words in a session's terminal or in his own mention, or he runs them himself. The
merging ship asks him once, after step 3. Rollback is a revert: the merging ship runs it whenever a check fails.

Steps 1–7 are the spec's, with its numbers; step 0 comes first, as in earlier Deploy sections.

- [ ] **Step 0: Back up the database first (mode 0600)**

The new `make station-backup OUTPUT=…` isn't on main yet, so this is the last one-line copy; the source is opened
read-only. It goes in `backups/`, beside the hand-made copies, which the rotation never reads, moves or prunes.

```bash
umask 077
COPY=~/.local/share/superyak/backups/peer-$(date +%Y%m%d-%H%M%S)-pre-backups-alerts.sqlite3
python3 -I -c 'import pathlib, sqlite3, sys; s = sqlite3.connect(pathlib.Path(sys.argv[1]).absolute().as_uri() + "?mode=ro", uri=True); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()' ~/.local/share/superyak/lighthouse/peer.sqlite3 "$COPY"
chmod 600 "$COPY" && stat -c '%a %s %n' "$COPY"   # expect 600 and a non-zero size
```

- [ ] **Step 1: Merge and run the suites** (as in earlier Deploy sections; peer and agent capped)

```bash
cd /home/andy/superyak/.worktrees/backups-alerts
git merge-base --is-ancestor main HEAD || git merge --no-ff main -m "Merge main into backups-alerts"   # a merge, never a rebase
CAP='systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0'
(cd peer && $CAP uv run --locked python -m pytest -q -p no:cacheprovider)
(cd agent && $CAP uv run --locked --extra dev python -m pytest -q)
(cd team && uv run --locked --extra dev python -m pytest -q)
cd /home/andy/superyak
test "$(git branch --show-current)" = main && test -z "$(git status --short)" && echo 'on main, clean'   # must print it
git fetch -q origin
git log --oneline main..origin/main   # must print nothing: main is not behind origin/main
git merge --no-ff backups-alerts -m "Merge backups-alerts: nightly checked copies, a monthly restore test, the reconcile and service alerts"
```

If main is behind, run `git merge --ff-only origin/main` there and go back to the start of this step. If that fails
because the two have diverged, stop and ask in the room.

- [ ] **Step 2: Run both commands once by hand**, before any unit exists

```bash
cd /home/andy/superyak
make station-backup
ls -l ~/.local/share/superyak/backups/station/   # expect one peer-…Z.sqlite3, mode -rw-------, in a drwx------ directory
make station-restore-test                        # expect exit 0 and "Restore test passed: peer-…Z.sqlite3 booted on 127.0.0.1:…"
```

If either fails, go to the rollback.

- [ ] **Step 3: Restart the lighthouse, check it, and ask Andy once**

Restart the lighthouse so it serves `/api/health`; Odo and Wormhole restart with it, through `Requires=`.

```bash
systemctl --user restart superyak-lighthouse
for unit in lighthouse odo wormhole; do printf '%s ' superyak-$unit; systemctl --user is-active superyak-$unit; done   # three lines ending in active
curl -fsS https://smart.tail7db420.ts.net/api/health; echo   # expect {"ok":true}
sleep 10
for unit in lighthouse odo wormhole; do printf '%s ' superyak-$unit; systemctl --user is-active superyak-$unit; done   # still three active
```

The units are `Type=simple`, so `restart` returns at the fork; the second `is-active` loop, about 10 s later, sees a
crash the first can't.

A loopback call gets 403 from the Host check unless it sends the origin's Host, so the check goes over the tailnet. If a
unit isn't active or the body differs, show the log (`journalctl --user-unit superyak-lighthouse.service -n 50
--no-pager`; on this Pi `journalctl --user -u` finds nothing) and go to the rollback.

Then push main (`cd /home/andy/superyak && git push origin main`). Announce the merge in the room, without @mentions,
and ask Andy one question: **may the units, timers and alert drop-ins be installed (`make station-units`)?** Say what it
does: two timers that run as him (a nightly backup at 03:30 and a monthly restore test on the 1st at 04:30), the
`superyak-alert@` handler, and an `ExecStopPost=`/`OnFailure=` drop-in on each of the five services; nothing else
changes, and `make station-units-remove` undoes it. The copy from step 2 starts the 36-hour clock: if he hasn't answered
by then, Odo's stale-backup notice is the reminder.

- [ ] **Step 4: After his go-ahead, install the units** (waits for Andy)

```bash
cd /home/andy/superyak
make station-units
systemctl --user list-timers 'superyak-*'                          # both timers listed
systemctl --user show -p OnFailure -p ExecStopPost superyak-door   # OnFailure=superyak-alert@superyak-door.service.service and the station-alert ExecStopPost
for unit in lighthouse door ship odo wormhole; do systemctl --user restart superyak-$unit; done
for unit in lighthouse door ship odo wormhole; do printf '%s ' superyak-$unit; systemctl --user is-active superyak-$unit; done   # five lines ending in active
sleep 10
for unit in lighthouse door ship odo wormhole; do printf '%s ' superyak-$unit; systemctl --user is-active superyak-$unit; done   # still five active
make station-alerts   # "No alerts are queued." and "Nothing is held back.": these were clean stops, through the new ExecStopPost=
```

- [ ] **Step 5: The alert check** (waits for Andy, like step 4)

A throwaway unit that this deploy starts and stops itself; no live service is killed:

```bash
systemd-run --user --unit superyak-alerttest -p Restart=always -p RestartSec=3 -p StartLimitBurst=4 \
  -p StartLimitIntervalSec=120 -p OnFailure=superyak-alert@superyak-alerttest.service.service \
  -p "ExecStopPost=-$HOME/superyak/peer/.venv/bin/python -I -m superyak_peer station-alert --data-dir $HOME/.local/share/superyak/lighthouse --unit superyak-alerttest.service" \
  /bin/false
```

Run it once: inside 30 minutes, a second run queues only the `down` line. Within about a minute, Ops shows exactly two
lines from Odo (read Ops with the station tools; don't post in it):
- "superyak-alerttest stopped unexpectedly … systemd restarts it unless it was being stopped";
- "superyak-alerttest is down … (start-limit-hit)".

`make station-alerts` shows `superyak-alerttest.service: 3 stops held back since …`. Then:

```bash
systemctl --user reset-failed superyak-alerttest
systemctl --user reset-failed 'superyak-alert@superyak-alerttest.service.service'   # only if that unit failed
```

- [ ] **Step 6: Announce**

Say in the room, without @mentions, what was installed, and that the two Ops lines from step 5 were the test. Say
plainly that an outage of the lighthouse, Odo or the Pi is still silent until Andy picks a channel outside the station.
Name the one item that is his (spec S15, Known limits): add `-I` to Odo's `--notices-command` in his odo unit, so Odo's
workspace stays off `sys.path` for the command this branch extends.

- [ ] **Step 7: Rollback**

1. `make station-units-remove`: the timers are disabled and the units and drop-ins removed, then `daemon-reload`; it
   also stops a running backup or restore test and resets their failed state. Skip this step if the units were never
   installed. If step 5 ran, also stop its test unit, which may still be restarting:
   ```bash
   systemctl --user stop superyak-alerttest 2>/dev/null; systemctl --user reset-failed superyak-alerttest 'superyak-alert@superyak-alerttest.service.service' 2>/dev/null || true
   ```
2. Revert the merge as earlier Deploy sections do, and restart the five:
   - **Before the push:** check that `git -C /home/andy/superyak log -1 --oneline ORIG_HEAD` is main from before the
     merge, then `git -C /home/andy/superyak reset --hard ORIG_HEAD`.
   - **After the push:**
     ```bash
     cd /home/andy/superyak
     MERGE=$(git log -1 --merges --format=%H --grep='^Merge backups-alerts:' main)
     git log -1 --oneline "$MERGE"   # check that it is this merge
     git revert --no-edit -m 1 "$MERGE" && git push origin main
     ```
   - Then:
     ```bash
     for unit in lighthouse door ship odo wormhole; do systemctl --user restart superyak-$unit; done
     for unit in lighthouse door ship odo wormhole; do printf '%s ' superyak-$unit; systemctl --user is-active superyak-$unit; done
     sleep 10
     for unit in lighthouse door ship odo wormhole; do printf '%s ' superyak-$unit; systemctl --user is-active superyak-$unit; done   # still five active
     ```
     and announce the revert in the room. Bringing the feature back after a pushed revert means reverting that revert,
     not merging the branch again.
3. `backups/station/` and `<data-dir>/alerts/` stay. The old code ignores both; delete them only if Andy asks.
4. There's no database change to undo.
