# Reads that don't wait: the store in WAL mode

Revision 1, 2026-10-29. Rio Grande (the Pi). Board item `spec:store-wal-mode` (City of AI).
Research, with file:line sources: docs/research/2026-10-29-store-wal-research.md (read-only, on main 26433c84).

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

## The gate's promise, and why reads may leave it

The gate exists so that "commits cannot pass final dispatch writes" (commit 66884140; peer/PROTOCOL.md:205-216). Under
the gate, a push re-reads the current authorization state (the outbox row, the pairing and hold, the layer's version,
the room's epoch, the member), commits the envelope, and writes the HTTP bytes while still holding the gate. Every local
commit needs the gate, so a withdrawal, unpair, hold, removal or epoch change lands either before the push re-reads
(the row comes back obsolete or withdrawn) or after the bytes are on the wire (in flight, and a tombstone follows).

The promise orders **commits** against the network write. A read that commits nothing changes no state the push could
miss, so it takes no part in the promise. That is the line this spec draws: a transaction that writes nothing may run
outside the gate; anything that writes, or decides something written later in the same transaction, stays inside.

## Goals

1. Pure reads stop waiting for writes, and writes stop waiting for them: session and device checks, the
   public route's key checks, the connector's token checks, the station commands' lists, federate's read passes, the
   board's counts and views, the directory, events, layers and lessons lists.
2. The gate's promise holds unchanged: every write still takes it, in every process.
3. Every backup copy stays one self-contained file, and the restore runbook stays correct.
4. Nothing a person wrote can be lost to a power cut that today's store would keep.

## Non-goals

- Changing the dispatch promise, the push or pull code, or the outbox.
- A connection pool, async SQLite, or more than one host opening the store.
- Phase 2's items (below) in phase 1.

## Anti-goals

- A read moved off the gate that can write. It is refused by the database, not by review (D3).
- A backup copy that needs a `-wal` beside it to be complete, or a restore step that copies only a main file while
  committed pages sit in a `-wal`.
- `synchronous=NORMAL`: faster commits that a power cut can undo.

## Design

### D1. WAL is switched by an explicit command, with everything stopped

`make station-journal MODE=wal` (and `MODE=delete` to go back) runs `PRAGMA journal_mode=...` on the live store. It
refuses while any process holds the file (`fuser` on `peer.sqlite3*`, as runbook step 4 does), refuses a data
directory without `peer.sqlite3` (never creates one), prints the mode before and after, and is safe to run twice.
The mode is a property of the file, so it persists across restarts; the lighthouse never switches it. Going back to
`delete` with everything stopped checkpoints the WAL into the main file and removes the sidecars, which is the
rollback for this whole change.

### D2. Durability stays as it is

`synchronous` stays at SQLite's default, FULL: every commit is fsynced, as today. WAL with FULL is no less durable than
the rollback journal. The disk is NVMe (ext4), and the cost is measured before and after (Measure).

### D3. A read path that cannot write

`Store.reading()` opens its own connection, sets `PRAGMA query_only=ON` and `foreign_keys=ON`, starts a deferred
`BEGIN`, and takes neither the dispatch gate nor SQLite's write lock. Any INSERT, UPDATE or DELETE inside it raises,
so a function that writes lazily can't be moved here by mistake: its test fails. It reads one consistent snapshot. It
closes in `finally`, as `_transaction()` does, and keeps `_check_paths()` and the same timeouts.

Functions move to `reading()` only from this list, each with a test that calls it under `reading()` and with the gate
held by another thread (it must complete without waiting):

- `session`, `session_is_valid` and `device_is_valid` (`auth.py`);
- the public route's checks, `ship_key_is_valid` (`ships.py`);
- connector `bearer`, `_live_grant` and `check_client` (`connector.py`);
- `station_pending`, `station_rooms` and `station_notices` (`ships.py`);
- federate's read passes (`federate.py`) and `sync_once`'s work list and pending count (`federation.py`), whose writes
  stay in `_prepare` under the gate;
- `_serve_pull`'s key listing and remainder count (the per-row work stays gated);
- `directory` (`presence.py`), `board_counts` and `board_view` (`room_board.py`), `events_since` (`db.py`), the layer
  lists and gets (`layers.py`), and the lessons lists and receipts (`lessons.py`).

Health (`app.py`) stays gated on purpose: it is how a stuck gate or a wedged store shows, to route-watch and to a
person, so it must wait as a write would. These also stay gated, because they write or must be serialized: anything
that can create the station identity (remote room reads, the lessons snapshot: `signatures.py`'s `_station_identity`
relies on the gate so two processes can't both create it); the imprint sweep (its filesystem actions rely on the
row staying put); every read that writes lazily (room reads closing a quiet breakout, `unread` touching cursors,
`ship_for_key` updating `last_used`, `mentions`); and every read-then-write in one transaction (the lessons query's
step 4, connector Task 8's tools, which write a receipt).

A read on `reading()` that later decides a write already re-checks inside the deciding transaction today (auth then
the route; `station_pending` then `station_decide`; `sync_once` then `_prepare`), so moving the read adds no gap. One
existing gap is named, not widened: `_refuse_live_ship_keys` checks in its own transaction before the post's.

### D4. Backup copies are written in rollback mode

After `source.backup(copy)` and before its integrity check, the copy is set to `journal_mode=DELETE`, in
`_checked_copy` and `_restored_copy`. So every copy is one self-contained file whatever the live store's mode, a later
`mode=ro` open of a copy creates no `-wal` or `-shm`, `prune` and `rotation` stay right, and `copy_off`'s byte copy is
complete. `TEMP_NAME` also matches `.tmp-wal` and `.tmp-shm`, so a crash mid-check leaves nothing that is never pruned.
The backup API reads through the WAL, so a copy taken while the store is in WAL holds every committed page.

### D5. The restore runbook

- The runbook already moves `peer.sqlite3` with its `-journal`, `-wal` and `-shm` together, and every symlink check
  covers all four names. Both stay.
- The reconcile works on `restored.sqlite3`, a backup copy, so it is in rollback mode (D4), and step 6's `install`
  copies a single complete file.
- After step 6 installs the copy and before step 8 starts the units, a new line runs `make station-journal MODE=wal`
  if the store was in WAL before the restore (step 1 records the mode, read from the header with the runbook's existing
  read-only one-liner).
- A rollback (step 10) puts back the file set aside at step 4 with its sidecars, as today, so it keeps its own mode.
- `_replaced` treats a `-wal` beside the replaced file as it treats a hot `-journal` today: the file is opened read
  only through SQLite, which applies it, never copied by bytes.

### D6. Read-only openers of the live store

A `mode=ro` connection to a WAL database needs `-shm` and creates it if the directory is writable. The identity check
(`signatures.py`), `validate_demo` and the runbook's one-liners open the live store this way. That is accepted: the
sidecars are SQLite's own, removed at the last close's checkpoint, and the data directory stays 0700. The identity
check's docstring ("read-only, so nothing is created") changes to say what is created, and test_federate.py's
before-and-after hash of the data directory excludes `-wal` and `-shm`.

### D7. Tests that assume rollback mode

The tests the research lists are changed to say which mode they test: the backup crash test that asserts a `-journal`,
the hot-journal restore tests, and test_lessons_index's held-reader tests ("a SHARED reader blocks the commit"), whose
docstring and `_lessons_answer`'s say the station keeps a rollback journal. Under WAL a held reader no longer blocks a
commit, so those tests pin the rollback case explicitly and gain a WAL case. Test helpers that copy a live store by its
main file (`set_aside`, and test_restore.py's other copies) copy through the backup API or checkpoint first.

## Phase 2 (named now, built later)

- Make the lazily writing reads pure: close quiet breakouts in a sweep instead of on read, and write a ship key's
  `last_used` at most once a minute in its own small transaction. Then room reads, `unread` and ship auth move to
  `reading()`.
- Split read-then-write calls (connector Task 8's tools, the lessons query's step 4): read on `reading()`, then one
  short gated transaction that re-runs the whole room check (the grant live and its set, membership, the mark, the room
  not replaced), counts the limit, and writes the receipt. If anything changed, the read's result is withheld and the
  call is refused. Text leaves only with the response, so a mark or revoke landing between the two lets nothing out
  (Task 8's section 2 gave these two conditions).
- A store opening that runs no schema or migrations, for read-only CLI processes, refusing a store whose schema is
  behind the code. Only the lighthouse and explicit commands migrate.

## Measure

On the Pi, before and after phase 1, with the store at today's size and at 10 times (a scratch store):

- a session check's p50 and p99 while another thread holds a 300 ms write, which should fall from about
  300 ms to about its alone time;
- another request's p50 during a flood of junk bearers (today about 100 ms against 6.7 ms alone);
- a post's wait during back-to-back writes (unchanged: writes still take the gate);
- the commit time of a post, with FULL, so durability's cost is seen;
- the stop time of a restart, read from the unit, which must stay inside its 6 s pass mark.

Phase 2's measure is the post's wait during back-to-back connector searches at 10 times (64 ms today).

## Tests

- `reading()` raises on INSERT, UPDATE and DELETE (query_only), takes no gate (it completes while another thread
  holds the gate and a write is open), and sees one snapshot.
- Each moved function has its gate-held test, and its old behaviour tests pass unchanged.
- The push and pull gate tests (test_transport.py's withdrawal inside `prepare`, test_federation_pull's per-row gate)
  pass unchanged.
- `station-journal` refuses with an opener present, refuses a missing store and creates nothing, switches both ways,
  and a second run changes nothing.
- A backup copy taken from a WAL store is in rollback mode, passes `integrity_check`, holds a commit made just before
  the backup that is still in the `-wal`, and a `mode=ro` open of it leaves no sidecars.
- A restore end to end from a WAL store, through step 6's switch back, and a rollback that keeps the file's mode.

## Order of work

1. `station-journal` and its tests (D1); backup copies in rollback mode (D4); the restore runbook and `_replaced` (D5).
2. `reading()` and its tests (D3), then the listed functions moved one at a time, each with its gate-held test.
3. Read-only openers and the tests that assume rollback mode (D6, D7); the stale docs the research names.
4. Measure before, switch the live store with everything stopped, measure after, and post both.

## Decisions

- D1 to D7 above are the author's.
- No question waits for Andy: durability is kept, the switch is reversible with one command, and he can veto the spec.
