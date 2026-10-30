# Reads that don't wait: the store in WAL mode

Revision 2, 2026-10-29. Rio Grande (the Pi). Board item `spec:store-wal-mode` (City of AI).
Research, with file:line sources: docs/research/2026-10-29-store-wal-research.md (read-only, on main 26433c84).
Review of revision 1, with probes p1 to p6 on scratch stores: City of AI, message 4adf3108 (a fresh Pi reviewer).

Revision 2 applies that review. Must-fixes: the gate-free read runs only in WAL mode (M1); writes are kept out of it by
rules the code enforces, not by `query_only` alone, and the lessons lists stay gated (M2); the switch is decided by
SQLite's lock under the gate, not by `fuser` (M3); the restore's `_replaced` needs no change, and the mode is recorded
and restored by named steps (M4). Should-fixes S1 to S7 and the nits are applied below.

## Why

Every store transaction on a station, reads included, takes one process-wide gate and SQLite's write lock: the dispatch
gate (`dispatch.py`), then `BEGIN IMMEDIATE` (`db.py`), in rollback-journal mode. So a read waits for every write, and
a write waits for every read. Today that is cheap because rooms are small. Measured on the Pi this week:

- A connector search holds the lock 7 to 31 ms on today's store and 31 to 284 ms at about 10 times its size. A ship's
  post during back-to-back searches waits 12 ms today (4 ms alone) and 64 ms at 10 times (Task 8's section 2).
- Every authenticated request starts with a store read of about 1 ms (a session, a ship key, a connector token), and
  a flood of them at about 500 a second lifts another request's p50 from 6.7 ms to about 100 ms (Task 7's section 2).
- Each read-only CLI process (Odo's `station-notices` every 30 s, every `lessons query`, `lessons index` every 60 s)
  takes the gate and the write lock several times just by opening the store, because opening runs the schema and
  migrations.

Goal 2 (chats are performant) and goal 4 (people outside us use it) both meet this as the store grows. WAL lets readers
and one writer run at once, but only for reads that don't take the gate. So this spec is about which reads may leave
the gate, why that keeps the gate's promise, and what WAL changes for backups and restore.

## The gate's promise, and why some reads may leave it

The gate exists so that "commits cannot pass final dispatch writes" (commit 66884140; peer/PROTOCOL.md:205-216). Under
the gate, a push re-reads the current authorization state (the outbox row, the pairing and hold, the layer's version,
the room's epoch, the member), commits the envelope, and writes the HTTP bytes while still holding the gate. Every local
commit needs the gate, so a withdrawal, unpair, hold, removal or epoch change lands either before the push re-reads
(the row comes back obsolete or withdrawn) or after the bytes are on the wire (in flight, and a tombstone follows).
Only two places take the gate explicitly (federation.py:362 and :482), and each covers one transaction.

The promise orders commits against the network write. But the gate also serializes things outside SQLite: identity
creation (a file), the imprint sweep's filesystem acts, `_pending_imprints` reading staged files, and in-memory state
such as `directory`'s `_inbox_budget`. So the line this spec draws is: **a read with no side effect anywhere (no commit,
no file, no process, no shared memory) may leave the gate, and only in WAL mode; everything else stays inside.** In WAL
a gate-free read sees one snapshot taken between two commits, so it never sees a half-done push.

## Goals

1. In WAL mode, the listed pure reads stop waiting for writes, and writes stop waiting for them: session and device
   checks, the public route's key checks, the connector's token check, the station commands' lists, federate's read
   passes, the board's counts and views, the directory and the layer reads named below.
2. The gate's promise holds unchanged: every write, and every read with a side effect, still takes it, in every
   process.
3. Every backup copy stays one self-contained file, and the restore runbook stays correct in either mode.
4. Nothing a person wrote can be lost to a power cut that today's store would keep.

## Non-goals

- Changing the dispatch promise, the push or pull code, or the outbox.
- A connection pool, async SQLite, or more than one host opening the store.
- Phase 2's items (below) in phase 1.

## Anti-goals

- A gate-free read in rollback mode. There it makes gated writes wait on readers (M1's probe: 333 ms for a 300 ms
  read, the gate held throughout) and can deadlock a gated write nested inside it.
- A function moved off the gate that writes, creates a file or changes shared memory.
- A backup copy that needs a `-wal` beside it to be complete, or a restore step that copies only a main file while
  committed pages sit in a `-wal`.
- `synchronous=NORMAL`: faster commits that a power cut can undo.

## Design

### D1. WAL is switched by an explicit command that SQLite's lock decides

`make station-journal MODE=wal` (and `MODE=delete` to go back):

1. refuses a data directory without `peer.sqlite3` and never creates one; refuses a directory without `dispatch.lock`
   rather than creating it (DispatchGate opens it with `O_CREAT`, and backups.py:1131 reads any directory holding one
   as live), so it only runs on a station that has run;
2. refuses while any station unit is active, checked with `systemctl --user is-active` for the lighthouse, door,
   ship, Odo, Wormhole, federation units and every station timer's service (backup, restore-test, imprint sweep, lessons
   index), since `fuser` can't see an idle store: a connection per transaction holds no descriptor (M3's probe: 0 of 20
   checks saw a live writer);
3. takes the dispatch gate, then runs `PRAGMA journal_mode=...` and retries "database is locked" for up to 10 s,
   since SQLite's own lock is what decides (to `wal` succeeds with a writer open; to `delete` fails at once while any
   other connection is open);
4. checks that the PRAGMA's answer is the mode asked for, prints the mode before and after, and is safe to run twice.

The mode is a property of the file and persists. The lighthouse never switches it. Going back to `delete` checkpoints
the WAL into the main file and removes the sidecars, which is this change's rollback, safe because `reading()` takes
the gate again in rollback mode (D3). Switching the live store is a named act (N5): Andy, or a ship with his yes in the
room, runs it with everything stopped, measures before and after (Measure), and posts both.

Runbook step 3's list of stopped units gains the imprint-sweep and lessons-index timers, which it misses today.

### D2. Durability, and WAL's own costs

`synchronous` stays at SQLite's default, FULL: every commit is fsynced, as today, so WAL is no less durable than the
rollback journal (the reviewer confirmed it). The disk is NVMe (ext4).

WAL brings costs of its own, named and bounded:

- **Growth.** With readers always overlapping, the `-wal` grew to 39 MB in 4 s (p5a), because a checkpoint can't pass
  an open snapshot. So the store sets `PRAGMA journal_size_limit` (64 MB), the station's hourly sweep runs a gated
  `wal_checkpoint(TRUNCATE)`, and `station-notices` raises a notice when the `-wal` passes 64 MB.
- **Who pays the checkpoint.** The last connection to close pays it, and that can be a gate-free reader (5.6 ms for
  3.9 MB, p5b). Accepted, and measured as read p99 including close.
- **Idle commits.** A post on an idle store took 2.4 ms in WAL against 1.85 ms in rollback, because every close is a
  last close (p5c). Each long-running process (the lighthouse, the door) keeps one idle connection open for its life,
  which brought it to 1.20 ms and lets `fuser` see the process. That connection runs no statements.

### D3. A gate-free read path, in WAL only

`Store.reading()`:

- opens its own connection with `PRAGMA query_only=ON` and `foreign_keys=ON`, and reads `PRAGMA journal_mode` first
  (a fresh connection answers correctly before any read, p6);
- in `wal`, starts a deferred `BEGIN` and takes neither the dispatch gate nor a write lock, so it reads one snapshot;
- in any other mode, takes the dispatch gate and runs as a gated read, exactly as today, so rollback mode is never
  worse than now (M1);
- refuses (raises) when entered by a thread that holds the gate, and `transaction()` refuses when entered inside
  `reading()` on the same thread, so the nested-write deadlock can't be built;
- maps exceptions as `_transaction()` does (UTF-8 errors to 400, `Problem` kept or rolled back) and takes its timeout
  from `busy_until` the same way (N4); closes in `finally`; keeps `_check_paths()`.

`query_only` refuses SQL writes on its own connection, including temp tables and triggers (p1). It doesn't stop a
helper that opens its own `self.transaction()`, a file write, or `PRAGMA query_only=OFF` (p2b, p2c). Those are kept
out by two rules the code enforces:

1. `_station_identity` refuses to create `identity.json` unless the calling thread holds the gate (it may still load
   an existing one). So no gate-free read can create the identity, even by a path nobody listed.
2. Each moved function gets a test that runs it inside `reading()` on a WAL store while another thread holds the gate
   and an open write: it must complete without waiting, and must leave the data directory's file list and every table
   unchanged. A function that writes, creates a file or opens its own transaction fails that test.

Functions move to `reading()` only from this list:

- `session`, `session_is_valid` and `device_is_valid` (`auth.py`);
- the public route's checks, `ship_key_is_valid` (`ships.py`);
- the connector's `bearer` only (`connector.py`); `_live_grant` and `check_client` are also called inside writing
  transactions, so they stay as helpers and run in whatever transaction calls them;
- `station_pending` (`ships.py`) for its database rows only; `_pending_imprints`' staged-file reads stay gated, so the
  command reads rows in `reading()` and the staged files in a gated read after it (N3: an imprint being removed can
  show its row without its request for that moment, display only);
- `station_rooms` and `station_notices` (`ships.py`);
- federate's read passes (`federate.py`) and `sync_once`'s work list and pending count (`federation.py`), whose writes
  stay in `_prepare` under the gate;
- `_serve_pull`'s key listing and remainder count (the per-row work stays gated);
- `board_counts` and `board_view` (`room_board.py`);
- the owner's own layer reads by name: `get_layer`, `list_layers` and `layer_revisions` (`layers.py`). `active_layer`
  (whose remote branch the review flagged), `shared_layers`, `preview_layer` and `can_deliver_layer` stay gated unless
  the build's gate-held test shows one pure, and then it is named in the commit (S7).

These stay gated: health (S1, below); `directory` (`presence.py`), because `_inbox_budget` is shared memory updated
there and would lose updates between threads (N2); every lessons function, because `lessons_list` reaches
`_station_identity` through `_lessons_snapshot` and the range includes writers (M2, N1); anything that can create the
station identity; the imprint sweep; every read that writes lazily (room reads closing a quiet breakout, `unread`
touching cursors, `ship_for_key` updating `last_used`, `mentions`); and every read-then-write in one transaction (the
lessons query's step 4, connector Task 8's tools). `events_since` has no production caller and isn't moved (S7).

A read on `reading()` that later decides a write already re-checks inside the deciding transaction today (auth then
the route; `station_pending` then `station_decide`, which re-reads `_received_row` and the docking row; `sync_once` then
`_prepare`; `_serve_pull` then `_walk_row`), so moving the read adds no gap. One existing gap is named, not widened:
`_refuse_live_ship_keys` checks in its own transaction before the post's.

### D4. Backup copies are written in rollback mode

After `source.backup(copy)` and before its integrity check, `_checked_copy` and `_restored_copy` set the copy to
`journal_mode=DELETE` and check that the PRAGMA answers `delete` (S4). Every copy path goes through one of the two
(`_checked_copy` with or without `--output`; `copy_off` byte-copies a checked copy). So every copy is one
self-contained file whatever the live store's mode, a later `mode=ro` open of a copy creates no `-wal` or `-shm`, and
`prune` and `rotation` stay right. `TEMP_NAME` and `_remove_temporary` also cover `.tmp-wal` and `.tmp-shm`. The
reconcile refuses a staged `restored.sqlite3` whose header says WAL (it can only come from a copy made outside these
paths). The backup API reads through the WAL, so a copy taken while the store is in WAL holds every committed page
(p4: a commit only in the source's `-wal` is in the copy).

### D5. The restore runbook

- The runbook already moves `peer.sqlite3` with its `-journal`, `-wal` and `-shm` together, and every symlink check
  covers all four names. Both stay.
- **Step 4 records the mode.** After the move, a plain Python `open()` reads header bytes 18-19 of
  `$ASIDE/peer.sqlite3` (`2 2` is WAL, `1 1` rollback) and writes `wal` or `delete` to `$ASIDE/journal-mode`. With no
  database to set aside (a store that never started), it writes `delete`.
- The reconcile works on `restored.sqlite3`, a rollback-mode copy (D4), so step 6's `install` copies one complete file.
- **Step 6b** (after step 6, before step 8 starts anything): if `$ASIDE/journal-mode` says `wal`, run
  `make station-journal MODE=wal`; if it says `delete` or is missing, do nothing and say so. A rerun is safe.
- A rollback (step 10) puts back the file set aside at step 4 with its sidecars, as today, so it keeps its own mode.
- `_replaced` needs no change (M4): opened read-only through SQLite, it reads a set-aside WAL file through its `-wal`
  and compares correctly (p4c). A test pins that, and the runbook notes the `-shm` it creates in `$ASIDE`.

### D6. Read-only openers of the live store

A `mode=ro` connection to a WAL database needs `-shm` and creates it if the directory is writable, and a read-only
connection that closes last leaves `-wal` and `-shm` behind (S6). The read-only openers of the live store are: the
identity check (`signatures.py`), `validate_demo`, the runbook's one-liners, the backup's source connection
(`_checked_copy`) and `_restored_copy`'s source. That is accepted: the sidecars are SQLite's own, removed at the next
read-write last close's checkpoint, and the data directory stays 0700. The identity check's docstring ("read-only, so
nothing is created") changes to say what is created, and test_federate.py's before-and-after hash of the data directory
excludes `-wal` and `-shm`.

### D7. Tests and docs that assume rollback mode

The tests the research lists say which mode they test: the backup crash test that asserts a `-journal`, the hot-journal
restore tests, and test_lessons_index's held-reader tests ("a SHARED reader blocks the commit"). They pin rollback mode
explicitly and gain a WAL case. Test helpers that copy a live store by its main file (`set_aside` and test_restore.py's
other copies) copy through the backup API or checkpoint first. Docs amended (S5): PROTOCOL.md:203-204 and :271-272 say
that gate-free reads in WAL mode take no part in the promise and why; `_lessons_answer`'s docstring says which mode it
describes; the owner-mention plan and spec stop saying the store already runs in WAL; the federation-pull recheck's
"SD card" says NVMe.

### S1. Health stays gated, bounded

Health stays on the gate on purpose: it is how a stuck gate or a wedged store shows, to route-watch and to a person.
But after D3 it is the only public, unauthenticated route on the gate, and its wait is unbounded, so a flood could park
every threadpool worker. So health takes the gate through `bounded(3 s)` and answers 503 on timeout (inside
route-watch's 15 s), and at most one health check waits for the gate at a time; others answer 503 at once.

## Phase 2 (named now, built later)

- Make the lazily writing reads pure: close quiet breakouts in a sweep instead of on read, and write a ship key's
  `last_used` at most once a minute in its own small transaction. Then room reads, `unread` and ship auth
  (`ship_for_key`, which tailnet junk bearers still reach) move to `reading()`.
- Split read-then-write calls (connector Task 8's tools, the lessons query's step 4): read on `reading()`, then one
  short gated transaction that re-runs the whole room check (the grant live and its set, membership, the mark, the room
  not replaced), counts the limit, and writes the receipt. If anything changed, the read's result is withheld and the
  call is refused. Text leaves only with the response, so a mark or revoke landing between the two lets nothing out.
- A store opening that runs no schema or migrations, for read-only CLI processes (Odo's `station-notices`), refusing a
  store whose schema is behind the code. Only the lighthouse and explicit commands migrate.

## Measure

On the Pi, before and after the switch, with the store at today's size and at 10 times (a scratch store):

- a session check's p50 and p99 (including the connection's close) while another thread holds a 300 ms write, which
  should fall from about 300 ms to about its alone time in WAL, and stay as today in rollback mode;
- a post's commit time on an idle store and a busy one, with FULL;
- the peak `-wal` size over an hour of normal use, and over a flood of reads;
- the push's gate-hold time and any transport deadline failures (`transport.py`'s 3 s);
- the stop time of a restart, read from the unit, which must stay inside its 6 s pass mark.

Phase 1 doesn't improve: tailnet junk bearers (they reach the gated `ship_for_key`), Odo's CLI (`Store()` writes at
open), room reads and `unread` (they write lazily), and connector tool calls (read-then-write). Those are phase 2's.

## Tests

- `reading()`: in WAL it takes no gate and sees one snapshot; in rollback mode it takes the gate; it raises when
  entered holding the gate; `transaction()` raises inside it; `query_only` refuses SQL writes.
- The reverse test: an open `reading()` snapshot in WAL doesn't delay a gated commit (p2's 3 ms case).
- `_station_identity` refuses to create the identity without the gate held, and still loads an existing one.
- Each moved function's gate-held test on a WAL store (it completes, and leaves the file list and tables unchanged),
  and its old behaviour tests pass unchanged in both modes.
- The push and pull gate tests (test_transport.py's withdrawal inside `prepare`, test_federation_pull's per-row gate)
  pass unchanged in both modes.
- `station-journal`: refuses a missing store and creates nothing; refuses without `dispatch.lock` and creates none;
  refuses while a unit is active (stubbed `systemctl`); switches both ways under the gate; retries "locked" and gives up
  at 10 s with the store unchanged; a second run changes nothing.
- Health: a held gate makes it answer 503 within 3 s, and a second waiting health check answers 503 at once.
- A backup copy taken from a WAL store answers `delete`, passes `integrity_check`, holds a commit that was only in the
  `-wal`, and a `mode=ro` open of it leaves no sidecars; a stray `.tmp-wal` is pruned.
- The reconcile refuses a WAL-flagged staged copy; `_replaced` compares a set-aside WAL file correctly.
- A restore end to end from a WAL store through step 4's record and step 6b's switch; one from a rollback store where
  6b does nothing; and a rollback that keeps the file's mode.

## Order of work

1. `station-journal` and its tests (D1), runbook step 3's timers; backup copies in rollback mode (D4); the restore
   runbook's step 4 record and step 6b, and `_replaced`'s pinning test (D5).
2. `reading()` and its tests (D3), `_station_identity`'s gate rule, then the listed functions moved one at a time, each
   with its gate-held test on a WAL store; health bounded (S1).
3. The keeper connection, `journal_size_limit`, the sweep's checkpoint and the notice (D2); read-only openers and the
   tests and docs that assume rollback mode (D6, D7).
4. Measure before; the live switch as a named act with everything stopped; measure after; post both.

Everything in steps 1 to 3 is safe to merge before the switch: in rollback mode `reading()` takes the gate, so the
station behaves as today until step 4.

## Decisions

- D1 to D7 and S1 above are the author's, revised by the review of revision 1.
- No question waits for Andy except the live switch itself (step 4), which is a named act with his yes; he can veto
  the spec.
