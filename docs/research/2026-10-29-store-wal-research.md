# Research: the peer store's locking, for WAL mode

2026-10-29, Rio Grande (the Pi), read-only, on main 26433c84. For `spec:store-wal-mode`. Lines marked [inferred] are
SQLite behaviour, not read or observed here. A reviewer should check file:line references against the current code.

## The live store

- peer.sqlite3 is in rollback-journal mode: header bytes 18-19 read `1 1`, as do all 14 rotation copies. No PRAGMA in
  peer/superyak_peer sets `journal_mode` or `synchronous`. The backups spec says "the default rollback journal; WAL is
  never set" (2026-10-14-station-backups-alerts-design.md:36-38).
- SQLite 3.40.1 (system Python 3.11.2 and peer/.venv). The data dir is on NVMe (`/dev/nvme0n1p2`, ext4, `noatime`),
  not an SD card. The dir is 0700 and the database 0600, owned by andy.

## The dispatch gate

- `dispatch.py:47-98`: a per-process RLock plus `flock(LOCK_EX)` on `<data_dir>/dispatch.lock`, re-entrant per thread;
  `bounded()` (:53-65) ends a wait at a deadline. `federation_lock()` (:34-45) is a different lock.
- `Store.transaction()` (db.py:129-133) takes the gate, then `_transaction()` (:135-156): a new connection per
  transaction (:139), `PRAGMA foreign_keys=ON` (:141), `BEGIN IMMEDIATE` (:143), closed in `finally` (:156). So every
  Store transaction in every thread and process, reads included, is serialized by the gate.
- Other entries: `federation.py:362` (push: `send_pinned(..., gate=...)`; transport.py:135-141 holds the gate from
  `prepare()` until the request bytes are written, released before the response is read); `federation.py:482` (pull,
  per row); `lessons.py:707-713` (bounded, the lessons query). The file `dispatch.lock` is also a marker:
  backups.py:1131 refuses a reconcile in a directory holding it.
- **What it protects** (commit 66884140, 2026-09-12; .superpowers/sdd/2026-09-12-peer-home/task-2-report.md:18-20,
  155-168; peer/PROTOCOL.md:205-216, 271-273, 326-331): under the gate `_prepare` re-reads the current authorization
  state (the outbox row pending or failed, the contact paired and not held, the layer's version, the room's epoch, the
  remote member, the message epoch; federation.py:237-288), commits the envelope, then the HTTP bytes go out while the
  gate is still held. Every local commit needs the gate, so a withdrawal, unpair, hold, member removal or epoch change
  commits either before `prepare` (the row comes back obsolete or withdrawn) or after the bytes are on the wire (in
  flight, and a tombstone follows). Pinned by test_transport.py:98-123 and test_federation_pull.py:311, :326, :346.
- **The invariant orders commits against the network write. Reads that commit nothing don't take part in it.**
- Its cost was raised before: docs/superpowers/reviews/2026-10-27-federation-pull-review.md:66-75 and the recheck
  :254-264 (SF8: "the browser, ships, the door and Odo all wait").

## Reads through transaction()

Pure reads (no writes, directly or through helpers followed): health (app.py:350-357); session lookup on every browser
request (auth.py:272-286) and `device_is_valid` (:137-148); the public route's key checks (app.py:165-168,
ships.py:114-123); connector `bearer` (connector.py:501-513), `_live_grant` (:379-388), `check_client` (:192-202);
`station_pending` (ships.py:211-243), `station_rooms` (:258-269), `station_notices` (:445-478, Odo every 30 s);
federate's passes (federate.py:23-38) and `sync_once`'s work list and count (federation.py:342-348, 377-378);
`_serve_pull`'s keys and remainder (:473-476, 494-496); `directory` (presence.py:108-122); `board_counts`,
`board_view` (room_board.py:191-227); `events_since` (db.py:164-168); layers (layers.py:65-226); lessons lists and
receipts (lessons.py:1159-1285).

Reads that write lazily (they need a write transaction today):
- room reads `get_room`/`list_rooms` (chats.py:46-75) close a quiet breakout the first time they see it
  (breakouts.py:33-67: `UPDATE breakouts SET closed`, `DELETE FROM deferrals`); `room_board` likewise
  (room_board.py:178-182, kept through `Problem(keep=True)`);
- `unread` (inbox.py:143-196) touches read cursors (`_cursor` :106-131, `_left_out` :230) and closes breakouts;
- ship bearer auth `ship_for_key` (ships.py:99-112) updates `last_used` and presence on every ship request, and the
  inbox wait loop polls it every second (app.py:462-474);
- `mentions` (ships.py:404-421) closes breakouts;
- the lessons query's step 4 (lessons.py:1225-1269) reads, then writes receipts in the same transaction;
- connector Task 8's tools read, then write a receipt in the same transaction (origin/connector-reads).
- **Every `Store()` open writes**: the schema script, migrations, `_ensure_system_author`, `_ensure_connector_key`,
  `_backfill_brief_history`, signature backfills (db.py:78-118). So each read-only CLI process (`station-notices` every
  30 s, `station-pending`, every `lessons query`, `lessons index` every 60 s, the door's start) takes the gate and the
  write lock several times as it starts.

Reads that rely on the gate: identity creation (`_station_identity`, signatures.py:74-85: "inside a transaction that
holds the dispatch gate, so two processes can't both create it"), reached by remote room reads (peer_store.py:157-158)
and the lessons snapshot (lessons.py:869-872); the imprint sweep's filesystem actions inside transactions that may
write nothing (imprints.py:1528-1590, 1667-1679). Read-then-decide patterns that already span transactions re-check
in the deciding one, so moving the read off the gate adds no gap (auth then route; `station_decide`'s re-check,
ships.py:342-367; `sync_once` then `_prepare`). One existing gap, not new: `_refuse_live_ship_keys` checks in its own
transaction before the post's (ships.py:71-82).

[inferred] In WAL, a deferred read that later upgrades to a write fails with SQLITE_BUSY_SNAPSHOT, which the busy
timeout doesn't retry; such paths must stay `BEGIN IMMEDIATE`.

## Who opens peer.sqlite3

The lighthouse (`Store`, app.py:308), the door (`Store(signing=False)`, door.py:56), Odo's `station-notices` CLI each
cycle, `lessons query` (spawned by the agent hook) and `lessons index`, the imprint sweep, `federate` and
`federation-listen` (not installed on this Pi), every `__main__` CLI command (`Store`), and raw connections:
`station-backup` (`mode=ro` plus the backup API, never the gate; backups.py:147-149), `station-restore-test`
(backups.py:1456-1490), `station-restore-reconcile` (raw read-write with its own `BEGIN IMMEDIATE`, backups.py:1229,
1252; `REPLACED` `mode=ro`, :1150), the identity check (`mode=ro`, signatures.py:41-54), `validate_demo` (`mode=ro`,
__main__.py:221), the runbook's one-liners (station-restore.md:133, 149) and peer/scripts. Nothing under agent/ opens
SQLite. All openers are local user units on the Pi.

## Backups and restore under WAL

- The backup API (`_checked_copy`, backups.py:209-251; `_restored_copy`, :1451-1460) reads through the WAL, so it is
  correct. [inferred] Under WAL commits continue during it, and checkpoints can't pass its snapshot, so the WAL grows
  meanwhile. The hot-journal retry (:210-236) is rollback-specific.
- [inferred] A backup copy keeps the source's WAL flag, so every later `mode=ro` open of a copy leaves an empty `-wal`
  and a 32 KB `-shm` beside it (seen on this Pi for engram's WAL graph.db:
  2026-10-25-permissions-by-place-plan-review.md:1056-1057). Then `prune` never removes them (backups.py:83-144), `TEMP_NAME` never matches `.tmp-wal` (:30, 200-202),
  and runbook steps 5 and 6 read leftovers as "a killed reconcile" (station-restore.md:92, 148).
- Copies of a live file by its main file only would miss committed pages still in a `-wal`: test helpers `set_aside`
  (test_restore.py:630), :861, :863, :1322; runbook step 6's `install` of restored.sqlite3 (:150), guarded today only by
  the `:148` glob. `copy_off` byte-copies the main file (backups.py:309-315). `_replaced` checks only `-journal` for
  "hot" (:1157-1170). [inferred] A clean last close checkpoints and deletes the `-wal`, so this is mostly after a crash.
- The runbook already moves the database with its `-journal`, `-wal` and `-shm` together (station-restore.md:26-28,
  77-81, 231-249), and the symlink checks already cover all four names (db.py:120-127, backups.py:168-177, :1123).

## PRAGMAs, timeouts, tests

`foreign_keys=ON` every connection (db.py:141); `busy_timeout` in lessons step 4 (lessons.py:1255); timeouts 30 s
(db.py:138-139, backups.py:149, :1229, signatures.py:48). Tests that assume rollback mode: test_backups.py:263-290
(asserts a `-journal`), :57-97 (mtime unchanged; probably still passes); test_restore.py:902-944 (hot journal);
test_lessons_index.py:618-703 (a SHARED reader blocks a commit; the `_lessons_answer` docstring says so too,
lessons.py:1229-1231); test_federate.py:404-422 (hashes every file in the data dir around a `mode=ro` check, which
under WAL creates `-wal`/`-shm`). test_signatures.py:462-525 build their own rollback databases.

## Other

[inferred] `-wal`/`-shm` take the main file's mode (0600) in the 0700 dir. Each close by the last connection
checkpoints and deletes `-wal`/`-shm`, so with a connection per transaction they come and go often. With the default
`synchronous=FULL` every WAL commit is fsynced. The header flag persists: once set, every opener uses WAL. A `mode=ro`
open of a WAL database needs a writable directory or existing sidecars, and leaves them behind, so the docstring at
signatures.py:41-43 ("read-only, so nothing is created") would no longer hold for the live file. Stale docs: the
owner-mention plan and spec (2026-10-15-owner-mention-fresh.md:333, -design.md:173) say "the database runs in WAL
mode", which is false; the federation-pull recheck (:260) says "SD card", but the disk is NVMe.
