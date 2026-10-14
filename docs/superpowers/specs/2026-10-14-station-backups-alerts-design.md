# Station backups, a restore test and service alerts

Status: revision 1, for a fresh reviewer's approval under D8 (station law, section 3). Roadmap items 1.1 and 1.3
([roadmap](../plans/2026-10-12-station-roadmap.md)), with a seam for 1.2. Base: `main` (7cdbb1f). Written by a Rio
Grande crew member.

## Goal

Every room, message, key hash and law layer on the station lives in one SQLite file on the Pi,
`~/.local/share/superyak/lighthouse/peer.sqlite3` (1.36 MB today). Its only copies are the hand-made ones taken
before migrations. No timer makes them, nobody has ever restored one, and nobody hears when a service fails. This spec
adds:
- a nightly checked copy kept for 8 weeks;
- a monthly restore test that boots a throwaway station from the newest copy;
- one line in Ops when a service crashes, gives up, or a backup or restore test fails.

The copy off the Pi (1.2) gets a switch that stays off until Andy picks where the copies go.

## What the code and the Pi show

The decisions below rest on these facts, each checked on 2026-10-14.
- **The units.** Five systemd user units (`~/.config/systemd/user/superyak-*.service`), all `Restart=always`:
  - `RestartSec=5` for the lighthouse and the door, 10 for ship, odo and wormhole;
  - no `StartLimit*`, so the user manager's defaults apply: 5 starts per 10 s (`/etc/systemd/user.conf` leaves them
    commented out);
  - odo and wormhole have `Requires=superyak-lighthouse.service`.
- **systemd is 252** (Debian 12). Since systemd 239, `OnFailure=` doesn't fire for a failure that leads to an automatic
  restart (systemd NEWS, "CHANGES WITH 239"). With 5–10 s between restarts these units never reach 5 starts in 10 s.
  So **`OnFailure=` alone would never fire for a crash loop of the five services**: it restarts forever and stays
  silent (S9).
- **How the station opens SQLite** (db.py:56, 88–99):
  - the default rollback journal; WAL is never set;
  - `sqlite3.connect(..., timeout=30)`, so the busy timeout is 30 s;
  - `BEGIN IMMEDIATE` for every transaction, reads included, all behind the `dispatch.lock` flock.
- **There's no `/api/health`.** app.py has no such route, though the roadmap's 1.1 acceptance names it. S6 adds it.
- **The reviewed path into Ops.** A trusted local process reaches Ops this way today:
  - the `station-notices` CLI (ships.py:370, `__main__.py:271`) prints `[{id, text}]`;
  - Odo runs it every 30 s cycle through `--notices-command` and posts each new id once in Ops, with client id
    `notice-<id>` (watch.py:262–285);
  - the station returns the same message for a repeated client id with the same text, and 409 when the text has
    changed (chats.py:80–83).

  `_post_as_system`, the `_station` author, has exactly one writer by spec S11, the ticket notice. It isn't reused.
- **journald is `Storage=volatile`.** Logs are lost at reboot.
  - `journalctl --user -u superyak-lighthouse` prints "No journal files were found".
  - `journalctl --user-unit superyak-lighthouse.service` works, since andy is in `adm`.
  - The `journalctl --user -u` lines in earlier Deploy sections print nothing on this Pi.
- **The hand-made copies** live in `~/.local/share/superyak/backups/` (0700), under three naming styles. One of them,
  `peer-20261007-083623-before-andy-password.sqlite3`, is mode 0644.
- **Disk.** A 939 GB NVMe, 2% used. `/tmp` is on it, not tmpfs. `/run/user/1000` is a 1.6 GB tmpfs, and linger is
  on.
- **`make dock` rewrites `superyak-ship.service` whole** (install.py:289–301). Changes to the five units therefore
  go in drop-ins.
- **The units run main's code.** Each unit runs `%h/superyak/peer/.venv/bin/python`, an editable install of the main
  checkout. It imports `superyak_peer` under `-I` from any directory, which was checked.

## Decisions

- **S1. Trusted CLI commands and systemd timers, not the station process.**
  - **Why:** a backup or an alert must work while the lighthouse is down or crash-looping. Running them outside the
    server keeps new threads out of it. systemd brings the schedule, the catch-up after downtime, the journal and
    `OnFailure=`.
  - **New commands** in `__main__.py`: `station-backup`, `station-restore-test`, `station-alert` and
    `station-alerts`. `station-notices` gains alerts. The logic goes in new modules, `backups.py` and `alerts.py`,
    which use only the standard library.
  - **No agent change.** Odo's watcher posts the alerts as it is.
- **S2. The backup.**
  - **Source.** `sqlite3.connect('file:…/peer.sqlite3?mode=ro', uri=True, timeout=30)`. It refuses a symlinked data
    dir or database, as `_check_paths` does. It never constructs `Store`, whose constructor writes the schema, the
    migrations and the system author. It never takes the dispatch gate either: SQLite's backup API copies a
    consistent snapshot of committed data on its own.
  - **One step:** `source.backup(dest, pages=-1)`. That copy holds a shared lock for milliseconds at this size, and a
    station commit waits for it within its 30 s busy timeout. A stepped copy is rejected: without WAL, every station
    write would restart it from the first page.
  - **Where.** Copies go in `~/.local/share/superyak/backups/station/` (0700), named `peer-YYYYMMDDTHHMMSSZ.sqlite3`
    in UTC. The hand-made copies one level up are never read, moved or pruned.
  - **Atomic and private.** Each copy goes through these steps:
    1. Set umask 077, and create a temporary file `.peer-<stamp>-<pid>.tmp` with
       `O_CREAT|O_EXCL|O_NOFOLLOW`, mode 0600.
    2. Back up into it.
    3. `PRAGMA integrity_check` on it must return exactly one row, `ok`.
    4. Close it, fsync it, `os.replace` it to the final name, and fsync the directory.

    So a file with a final name is always a checked copy.
  - **One run at a time:** a flock on `backups/station/.lock`.
  - **`--output FILE`** writes one checked copy to a new path, outside the rotation, and refuses a path that exists.
    Future Deploy sections use `make station-backup OUTPUT=…` in place of their one-line Python copies.
- **S3. Keep 14 nightly and 8 weekly copies.**
  - **Nightly:** keep the newest copy of each of the 14 most recent UTC days that have a copy.
  - **Weekly:** keep the newest copy of each of the 8 most recent ISO weeks that have a copy.
  - **Everything else in the rotation is deleted.** Because only days and weeks that have a copy count, a Pi that
    was off, or nights that failed, never age out the last good copies.
  - **When and what:** pruning runs only after a new checked copy is in place. It deletes only files whose names
    match the pattern, plus temporary files more than a day old. That's at most 22 copies, about 30 MB today.
- **S4. Disk space and failed checks.**
  - **Low disk.** Before copying, the free space left after the copy (estimated as `page_count × page_size`) must
    be at least 1 GiB. If it isn't, nothing is written.
  - **A failed check.** The temporary copy is deleted. The command then runs `PRAGMA quick_check` on the live
    database, read-only, to tell a bad copy from a damaged station.
  - **Every failure before a new copy is in place** prunes nothing and keeps the old copies. The command exits with
    its code (Error handling), and the unit's `OnFailure=` sends the alert (S9, S10).
- **S5. The copy off the Pi (1.2): a switch that stays off.**
  - **Off by default.** `station-backup --copy-to DIR` does nothing when DIR is empty. The unit passes
    `--copy-to=${SUPERYAK_BACKUP_COPY_TO}` from an optional `~/.config/superyak/backup.env`, which doesn't exist
    until Andy writes it.
  - **When it's set,** DIR must:
    - exist, be a directory and not be a symlink;
    - be on a different filesystem from the rotation (a different `st_dev`), so a share that isn't mounted never
      silently fills the Pi's own disk.

    The checked file is then copied there atomically at mode 0600, its sha256 is compared, and S3's rule applies there
    too.
  - **Left for 1.2's spec:**
    - **Andy's decisions:** the destination and whether copies are encrypted at rest. The file holds room text, key
      hashes and salted password hashes.
    - **Transports other than a mounted directory,** such as scp or rsync.
- **S6. `GET /api/health`.**
  - **What it answers:** `{"ok": true}` with 200, after `SELECT 1 FROM system_meta` through `store.transaction()`.
    It needs no session and carries no other field. A database error goes to the existing 500 handler.
  - **Where:** the lighthouse app only. The public door's two routes are unchanged. Roadmap 1.4 may add the commit
    later.
- **S7. The restore test.**
  - **The command:** `station-restore-test --backup-dir DIR [--backup FILE]`. It takes no data dir, so it can't name
    the live one.
  - **The steps:**
    1. Pick the newest copy with a final name, or FILE.
    2. Make a scratch directory with `mkdtemp(prefix='superyak-restore-test-')` (0700) in `$XDG_RUNTIME_DIR`, or the
       system temp dir when that's unset. Remove leftover scratch directories more than a day old.
    3. Copy the backup into `scratch/peer.sqlite3` (0600) with the backup API, and run `integrity_check` on it.
    4. Read three counts, read-only: users that aren't the system author, rooms, and messages.
    5. Start `sys.executable -I -m superyak_peer serve --data-dir <scratch> --host 127.0.0.1 --port P`. P comes from
       binding port 0 and closing it; the start is tried up to 3 times if the server exits during start-up.
    6. Wait up to 60 s for `http://127.0.0.1:P/api/health` to answer 200.
    7. Read the counts again through `Store(<scratch>)`, the trusted local path. They must equal the first counts, with
       at least one user and one room.
    8. Tear down on every path: SIGTERM, then SIGKILL after 10 s. Remove the scratch directory in `finally`.
  - **Why the store and not HTTP for "rooms and users are listed":** listing rooms over HTTP needs a session, and the
    test must never mint one or hold a password. The server's start proves today's code opens and migrates the copy.
    The counts prove nothing was lost on the way.
  - **The throwaway station** listens on loopback at an ephemeral port only. It has no proxy headers, no sync, no
    share link and no Odo, and it lives for seconds.
- **S8. Units and timers.** The unit files live in `peer/systemd/`. `make station-units` installs them, writes the S9
  drop-ins, runs `daemon-reload` and enables both timers. It refuses unless `$(STATION_DATA)/peer.sqlite3` exists.
  `make station-units-remove` undoes all of it. The five existing unit files are never edited.
  - **`superyak-backup.service`:**
    - `Type=oneshot`, `After=superyak-lighthouse.service` and `OnFailure=superyak-alert@%n.service`;
    - `WorkingDirectory=%h/superyak/peer` and `EnvironmentFile=-%h/.config/superyak/backup.env`;
    - `ExecStart=%h/superyak/peer/.venv/bin/python -I -m superyak_peer station-backup --data-dir
      %h/.local/share/superyak/lighthouse --backup-dir %h/.local/share/superyak/backups/station
      --copy-to=${SUPERYAK_BACKUP_COPY_TO}`;
    - `Nice=10`, `IOSchedulingClass=idle`, `TimeoutStartSec=15min` and `MemoryMax=512M`.
  - **`superyak-backup.timer`:** `OnCalendar=*-*-* 03:30:00`, `RandomizedDelaySec=30min`, `Persistent=true` and
    `WantedBy=timers.target`.
  - **`superyak-restore-test.service`:** the same shape (oneshot, `OnFailure=`, the working directory, `-I`), with
    `After=superyak-backup.service` and no environment file. It runs `station-restore-test --backup-dir
    …/backups/station`, with `TimeoutStartSec=10min` and `MemoryMax=1G`.
  - **`superyak-restore-test.timer`:** `OnCalendar=*-*-01 04:30:00`, `RandomizedDelaySec=30min` and
    `Persistent=true`.
  - **`superyak-alert@.service`:** `Type=oneshot`, `TimeoutStartSec=1min`. It runs `ExecStart=%h/superyak/peer/.venv/bin/python -I -m
    superyak_peer station-alert --data-dir %h/.local/share/superyak/lighthouse --unit %i --monitor`. `%i` is the raw
    instance; `%I` would turn its dashes into slashes. It has no `OnFailure=` of its own, so it can't recurse.
  - **`Persistent=true` on a Pi that was off.** The user manager starts at boot, since linger is on. Each timer that
    missed its time then runs once, not once per missed night, after its random delay.
    - **The backup** is ordered after the lighthouse's start job.
    - **After a power cut,** the lighthouse may not yet have recovered a hot journal, and a read-only open fails until
      it has. So the backup retries the open for up to 60 s.
    - **The restore test** is ordered after the backup, so a boot that catches up both tests the fresh copy.
- **S9. Alerts fire from `ExecStopPost=` and `OnFailure=`.**
  - **The drop-in.** Each of the five services gets `~/.config/systemd/user/superyak-<name>.service.d/50-alerts.conf`:
    ```ini
    [Unit]
    OnFailure=superyak-alert@%n.service

    [Service]
    ExecStopPost=-%h/superyak/peer/.venv/bin/python -I -m superyak_peer station-alert --data-dir %h/.local/share/superyak/lighthouse --unit %n
    ```
  - **Why both.**
    - `ExecStopPost=` runs after every stop, including a crash that systemd is about to restart, with
      `$SERVICE_RESULT`, `$EXIT_CODE` and `$EXIT_STATUS`. A result of `success` records nothing. That covers deploy
      restarts, `systemctl stop`, shutdown and the stops that `Requires=` carries along.
    - `OnFailure=` stays for a unit that gives up, at its start limit after a burst of manual restarts, or if restart
      settings are tightened later. It doesn't fire today (see the facts above).

    The roadmap's 1.3 ("when a service fails or restarts outside a deploy") needs the first; the brief's `OnFailure=`
    is the second.
  - **Restart behaviour is unchanged.** Start limits stay as they are, and the services keep restarting forever. A
    station that heals itself beats one that stays down until Andy notices.
  - **The `-` prefix** means a failing notifier never changes the unit's result. **`-I`** keeps the unit's working
    directory, such as Odo's workspace, off `sys.path` and ignores `PYTHON*` variables.
  - **The backup and restore-test units** have `OnFailure=` only.
- **S10. One posting path: a queue, `station-notices`, Odo, Ops.**
  - **The queue.** `station-alert` writes one JSON file per alert into `<data-dir>/alerts/` (0700). Each file is 0600,
    written through a temporary file and a rename. It holds:
    - `id`, 12 random hex characters;
    - `unit`, `kind` (`stopped`, `down` or `failed`) and `at`;
    - `result`, `exit_code` and `exit_status`;
    - `held_back` and `held_since`;
    - `text`, rendered once, so a repeated listing posts the same words.
  - **The listing.** The `station-notices` command appends to `Store.station_notices()`, which is unchanged:
    - the alerts of the last 7 days, as `{'id': 'alert-<id>', 'text': …}`, at most the 20 newest, oldest first;
    - S14's stale-backup notice.
  - **The post.** Odo's existing `_announce` posts each one once, under client id `notice-alert-<id>`. Its existing
    rules apply: other errors are retried next cycle, and 403, 404 or 409 is never retried.
  - **Not `_station`.** Spec S11 gives the system author one writer, and this spec doesn't add a second.
  - **Clean-up.** The notifier deletes alert files more than 30 days old each time it runs.
- **S11. The line in Ops: no journal lines.**
  - **The templates.** These are examples; values in angle brackets vary.
    - `stopped`: "Station alert: superyak-lighthouse stopped unexpectedly at 03:12 on 2026-10-14 (exit-code, status 1);
      systemd is restarting it. Log on the Pi: journalctl --user-unit superyak-lighthouse.service --since
      '2026-10-14 03:02'." When failures were held back, it adds " <4> more stops since <02:41> were held back."
    - `down`: "Station alert: superyak-odo is down since 03:12 on 2026-10-14: systemd stopped restarting it
      (start-limit-hit). Log on the Pi: …"
    - `failed`: "Station alert: the nightly backup failed at 03:41 on 2026-10-14: <not enough disk space>. The earlier
      copies are kept. Log on the Pi: …". The restore test's line starts "the monthly restore test failed". The
      reason comes from the exit code (Error handling).
  - **Why no journal lines, scrubbed or not.** Scrubbing is a deny-list, and nobody can show it's complete. A traceback
    can carry request data, the door's status secrets, the share link, or the names and contacts from access
    requests. Every Ops member reads the line, and so does the aDNA lattice if Ops is ever bridged. The journal stays
    on the Pi, and the line says where to read it.
  - **Every value is checked.**
    - The unit must match `superyak-[a-z0-9-]{1,60}\.service`, so it can't contain an at sign. Anything else is
      refused with exit 2, and nothing is queued.
    - The result must be in systemd's documented set (`success`, `protocol`, `timeout`, `exit-code`, `signal`,
      `core-dump`, `watchdog`, `start-limit-hit` and `resources`), or be `oom-kill`, which systemd reports for a
      `MemoryMax=` kill. Anything else becomes `unknown`.
    - The status is digits or `[A-Z0-9+]{1,16}`.
    - Times are in the Pi's local zone, with the date. The `--since` time is 10 minutes before the earliest failure
      the line reports.
    - The whole line goes through `safe_line(…, 400)`.
  - **The environment stays private.** The notifier reads only `SERVICE_RESULT`, `EXIT_CODE`, `EXIT_STATUS` and
    `INVOCATION_ID`, or their `MONITOR_*` forms. It never reads or stores anything else from the environment, such as
    the lighthouse's `lighthouse.env`.
- **S12. At most one alert per unit and kind every 30 minutes.**
  - **Held back, then counted.** A failure inside the window adds to a count in `alerts/rate.json`. The next alert for
    that unit and kind reports the count, and then the count resets.
  - **Giving up is never held back.** `down` and `failed` are kinds of their own, so an earlier `stopped` line can't
    hold back the line that says a unit has given up.
  - **Locking.** Records are written under a flock on `alerts/.lock`. If 5 s pass without the lock, the alert is
    queued anyway: a duplicate is better than a lost alert.
  - **The worst case** is two lines per unit and kind per hour.
- **S13. When the station is down.**
  - **The lighthouse is down.** Odo's cycles fail and the files wait in the queue. Once the lighthouse is back, Odo's
    next cycle, within 30 s, posts them. Each line says when its failure happened.
  - **Odo is down.** The alerts wait the same way. Odo posts them, its own included, when it returns.
  - **Both stay down, or the Pi is down or loses power.** Nobody hears. This spec has no channel outside the station;
    choosing one is Andy's call (open question 3).
  - **`make station-alerts`** on the Pi shows the queue and the held-back counts at any time.
- **S14. A timer that stopped.**
  - **The notice.** When the newest copy in the rotation is more than 36 hours old, `station-notices` adds one notice,
    with id `backup-stale-<that file's name>`: "Station alert: the newest station backup is from <2026-10-12 03:31>,
    more than 36 hours ago. The nightly timer may have stopped. On the Pi: systemctl --user list-timers
    superyak-backup.timer."
  - **Once per lapse.** The id changes as soon as a new copy appears.
  - **When there's nothing to say.** No notice is added when the rotation directory is missing or empty, so machines
    without backups never see one.
  - **`--backup-dir`** defaults to `backups/station` beside the data dir.
- **S15. What stays with Andy.**
  - Restoring over the live database. That's a person's step, with the runbook `docs/station-restore.md` (below).
  - The destination off the Pi, and encryption (S5).
  - A channel outside the station for when it's down (S13).
  - Making journald persistent, which is root's configuration.
  - The 0644 hand-made copy. This spec doesn't touch it, and he may `chmod 600` it.

### The restore runbook (`docs/station-restore.md`)

1. **Choose the copy.** List `~/.local/share/superyak/backups/station/`; the names are UTC times. Take the newest copy
   from before the damage.
2. **Test it:** `make station-restore-test BACKUP=<path>`. It must pass.
3. **Stop everything:**
   `systemctl --user stop superyak-backup.timer superyak-door superyak-odo superyak-wormhole superyak-ship superyak-lighthouse`.
4. **Set the current state aside.** Make a 0700 directory `backups/replaced-<local time>`. Move `peer.sqlite3` and
   every `peer.sqlite3-*` into it. A `peer.sqlite3-journal` left beside the restored file would be applied to it and
   corrupt it.
5. **Put the copy in place:** `install -m 600 <copy> ~/.local/share/superyak/lighthouse/peer.sqlite3`.
6. **Undo what the restore brings back,** before starting. The copy restores sessions, ship keys, invitations,
   activations, passwords and roles as they stood at its time.
   1. End every session:
      `~/superyak/peer/.venv/bin/python -I -c "import sqlite3,sys; d=sqlite3.connect(sys.argv[1]); d.execute('DELETE FROM sessions'); d.commit()" <db>`.
      Everyone signs in again.
   2. Revoke again, before the start, the keys of every ship revoked since the copy's time: set `ship_keys.revoked`
      for that ship's unrevoked keys, in the same one-line form. Once the lighthouse is up, a remote machine could use
      them at once, so the web app's revoke would come too late.
   3. Change again any password changed since then.
   4. Ships docked since then are gone: their machines dock again.
   5. Invitations and access requests decided since then are back to their earlier state.
7. **Start the services** in order: lighthouse, door, ship, odo and wormhole. Check each with `is-active`, run
   `make station-rooms`, then start the timer.
8. **Say in the room** what was restored and from when. Everything said after the copy's time is gone.

## Requirements

- **R1.** `station-backup` copies with SQLite's online backup API, from a read-only connection, in one step. It never
  opens the live database for writing, never constructs `Store` and never takes the dispatch gate.
- **R2.** A copy appears under its final name only after it has passed `integrity_check`. It is created 0600 inside a
  0700 directory and renamed atomically, with the file and the directory fsynced.
- **R3.** S3's rule decides retention. Pruning runs only after a new checked copy is in place, and it deletes only
  names that match the pattern in the rotation directory, plus temporary files more than a day old.
- **R4.** `--output FILE` writes one checked copy to a new path, outside the rotation, and refuses an existing path.
- **R5.** Low disk and failed checks write nothing, prune nothing and keep every earlier copy. They exit with the codes
  in Error handling.
- **R6.** An empty `--copy-to` does nothing. A set one refuses a missing directory, a symlink, or a directory on the
  rotation's filesystem. It copies the file at 0600, verifies the sha256 and applies S3 there. If it fails, the
  command exits 13 and keeps the local copy.
- **R7.** `GET /api/health` answers 200 `{"ok": true}` without a session, after one database read, and returns nothing
  else. The door is unchanged.
- **R8.** `station-restore-test` works as S7 says. It boots a loopback station from the copy, checks health and the
  counts, and always tears down: no process is left, and the scratch directory is removed.
- **R9.** The restore test has no data-dir option, and it exits with the codes in Error handling.
- **R10.** Each of the five services has the S9 drop-in. A stop with `SERVICE_RESULT=success` queues nothing; any
  other result queues an alert. The backup and restore-test units alert through `OnFailure=`.
- **R11.** There is at most one alert per unit and kind every 30 minutes, and held-back failures are counted in the
  next one. `down` and `failed` are never held back by `stopped`. When the lock can't be had within 5 s, the alert is
  queued anyway.
- **R12.** An alert is one line from S11's templates, with checked values only. It has no journal lines, no
  environment and no at sign, and an invalid unit is refused with nothing queued.
- **R13.** Alerts are queued as 0600 files in `<data-dir>/alerts/`. `station-notices` lists at most the 20 newest
  from the last 7 days, and Odo posts each once in Ops through its existing path. Files more than 30 days old are
  deleted.
- **R14.** A rotation whose newest copy is more than 36 hours old gives exactly one `backup-stale-<name>` notice. No
  rotation, or an empty one, gives none.
- **R15.** With no alerts directory and no rotation directory, `station-notices` prints exactly what it prints today,
  byte for byte. `Store.station_notices()` is unchanged.
- **R16.** The timers and units are exactly S8's. They're installed and removed only by the two make targets, and the
  five existing unit files are not edited.
- **R17.** `make station-backup [OUTPUT=…]`, `make station-restore-test [BACKUP=…]` and `make station-alerts` run the
  same commands by hand.

## Error handling

| Command | Exit | Meaning | What happens |
|---|---|---|---|
| backup | 10 | Less than 1 GiB would be left, or ENOSPC during the copy | No copy, no pruning, the temporary file is removed; "not enough disk space" |
| backup | 11 | The copy failed `integrity_check` (or raised), and the live `quick_check` passed | Copy deleted; "the copy failed its check; tomorrow's run tries again" |
| backup | 12 | The live database fails `quick_check` | Copy deleted; "the live database may be damaged: don't restart or deploy before reading docs/station-restore.md" |
| backup | 13 | `--copy-to` failed | The local copy is kept and pruning has run; "the copy off the Pi failed" |
| backup | 1 | Anything else: a missing or symlinked database, an open still failing after 60 s, a pruning error | Old copies kept; "see the log" |
| restore test | 20 | No copy to test | "there is no backup to test" |
| restore test | 21 | The restored copy fails `integrity_check` | "the newest copy failed its check" |
| restore test | 22 | No health answer within 60 s, or the server exited | "the restored station did not start" |
| restore test | 23 | No users or rooms, or the counts changed | "the restored station is missing data" |
| restore test | 1 | Anything else | "see the log" |
| alert | 2 | A run outside systemd (no `SERVICE_RESULT` or `--monitor` variables), or an invalid unit | Nothing queued; a usage message |

- **Every failing timer run** fails its unit. `OnFailure=` then queues the reason that matches the exit status.
- **A notifier that can't write its queue** (disk full, permissions) prints to stderr, which goes to the journal, and
  exits 0. The unit's result doesn't change.
- **Busy or locked database.** Python's backup loop sleeps and retries; the unit's `TimeoutStartSec` bounds it.
- **A stop that times out** (`timeout`) or an OOM kill (`oom-kill`) is a failure, and it alerts.
- **Odo's post is refused for good** (403, 404 or 409). It's marked announced, as today, and the file stays on the
  Pi.

## Security

- **What a copy holds.** Every copy holds everything the station holds: room text, salted password hashes, session,
  key and docking-secret hashes, and requesters' contacts. Copies are 0600 in 0700 directories, owned by andy, on the
  Pi's own disk. Anyone who can read them can already read the live file, so a copy on the Pi adds no exposure.
  The copy off the Pi does add exposure, and it stays off until Andy decides (S5).
- **A restore brings back old secrets.** Revoked keys, ended sessions, used invitations and old passwords come back.
  Restoring is a person's step, and runbook step 6 undoes them.
- **The throwaway station** listens on loopback at an ephemeral port. It has no proxy headers, no sync and no share
  link. It accepts the same credentials as the live station, which is also on loopback, so it opens nothing new. No
  watcher points at it.
- **The Ops line** carries only a unit name, a time, systemd's words and a fixed reason. It holds no log text, no
  environment and no at sign, so it starts no ship's run.
- **The queue** sits in the 0700 data dir. No HTTP route reads it.
- **`/api/health`** is unauthenticated and says only "ok". It sits behind tailscale serve on the tailnet, not on the
  public door.
- **`-I`** keeps a unit's working directory and `PYTHON*` variables away from the interpreter of every new unit
  and every `ExecStopPost=`.
- **Nothing here acts on the station's data.** These are local operator commands. None of them posts as a person, and
  none of them restores over the live file.

## Testing

All the tests are Pi-safe and use temporary directories; station tests use the existing fixtures. Each one fails
without its feature.

- **`peer/tests/test_backups.py`:**
  - `test_backup_copies_committed_data_from_a_read_only_connection` (R1). An uncommitted write is open on another
    connection. The copy passes its check and lacks that row. The live file's bytes and mtime are unchanged, and no
    journal appears beside it. Constructing `Store` raises (monkeypatched) and isn't reached.
  - `test_copies_are_private_checked_and_appear_whole` (R2). The modes are 0600 and 0700. A failure injected after
    the temporary write leaves neither a final file nor a temporary one.
  - `test_retention_keeps_14_days_and_8_weeks_and_nothing_else` (R3). Synthetic names cover 200 days, with gaps,
    several copies in one day and a month off. Hand-made names and other files are never touched.
  - `test_output_writes_one_checked_copy_and_never_overwrites` (R4).
  - `test_failures_keep_old_copies_and_exit_with_their_code` (R5), parametrised over the following, each leaving the
    earlier copies, no pruning and no temporary file:
    - a faked low free space, which gives 10;
    - a forced check failure, which gives 11;
    - a database with overwritten pages, which gives 12.
  - `test_copy_to_is_off_by_default_and_refuses_the_same_disk` (R6). An empty value copies nothing. The same device
    gives 13, with the local copy kept. A faked different device gives a 0600 copy with the same sha256.
- **`peer/tests/test_restore.py`:**
  - `test_health_answers_without_a_session` (R7).
  - `test_restore_test_boots_a_throwaway_station_from_the_newest_copy` (R8). A real subprocess server runs, the
    command exits 0, the scratch directory is gone and the port is closed.
  - `test_restore_test_failures_clean_up_and_exit_with_their_code` (R9), each removing the scratch directory and
    leaving no process:
    - no copy gives 20;
    - a damaged copy gives 21;
    - a server command that exits gives 22;
    - changed counts give 23.
- **`peer/tests/test_alerts.py`:**
  - `test_a_crash_queues_one_alert_and_a_clean_stop_queues_none` (R10).
  - `test_alerts_are_held_back_per_unit_and_kind_for_30_minutes` (R11), with a fake clock:
    - 6 crashes in 10 minutes queue one file;
    - 31 minutes later one more is queued, saying "5 more stops since …";
    - a `down` inside the window is still queued.
  - `test_failed_backup_and_restore_runs_name_their_reason` (R12): every exit code in the table.
  - `test_alert_lines_hold_no_log_lines_mentions_or_unchecked_values` (R12):
    - invalid units are refused, with nothing queued;
    - an unknown result becomes `unknown`;
    - a fake secret in the environment appears in neither the file nor the text;
    - there's no at sign and no newline.
  - `test_notices_list_queued_alerts_and_are_unchanged_without_them` (R13, R15): the output without either directory
    is compared byte for byte.
  - `test_a_stale_backup_is_announced_once_per_lapse` (R14).
  - `test_odo_posts_a_queued_alert_in_ops_once` (R13), in `test_ship_agent.py` beside
    `test_odo_announces_station_notices_in_ops`. An alert is queued while the watcher can't reach the station. The
    next cycle posts it, and the one after posts nothing.
- **`peer/tests/test_station_units.py`:** `test_units_say_what_the_spec_says` (R16). It parses `peer/systemd/` and
  checks:
  - the `OnCalendar` values and `Persistent=true`;
  - `OnFailure=` on both oneshots, and no `Restart=` on them;
  - the drop-in's `ExecStopPost=-` with `-I`.

  When `systemd-analyze` exists, `systemd-analyze --user verify` must also pass; elsewhere that part is skipped.
- **Mutation checks** on R1 (`Store` constructed), R3, R10 (a `success` that alerts) and R11, run with
  `PYTHONDONTWRITEBYTECODE=1` and the caches cleared.

## Deploy, with rollback

Under section 2 of the station law: a fresh reviewer's approval is posted in the room, and the Pi suites pass. Nothing
changes the schema. Nothing @mentions a ship.

1. **Merge and run the suites** as in earlier Deploy sections (peer and agent, capped with `systemd-run --scope`).
2. **Run both commands once by hand,** before any unit exists:
   - `make station-backup`: expect one `peer-…Z.sqlite3`, mode 600, in `backups/station/`;
   - `make station-restore-test`: expect exit 0.
3. **Install the units** with `make station-units`. Then check:
   - `systemctl --user list-timers 'superyak-*'` shows both timers;
   - `systemctl --user show -p OnFailure -p ExecStopPost superyak-door` shows the drop-in.
4. **Restart the five in order** (lighthouse, door, ship, odo, wormhole), so the lighthouse serves `/api/health`.
   Expect five `active`. `make station-alerts` must then show an empty queue: these were clean stops, through the new
   `ExecStopPost=`.
5. **The alert check.** A throwaway unit that this deploy starts and stops itself; no live service is killed:
   ```bash
   systemd-run --user --unit superyak-alerttest -p Restart=always -p RestartSec=3 -p StartLimitBurst=4 \
     -p StartLimitIntervalSec=120 -p OnFailure=superyak-alert@superyak-alerttest.service.service \
     -p "ExecStopPost=-$HOME/superyak/peer/.venv/bin/python -I -m superyak_peer station-alert --data-dir $HOME/.local/share/superyak/lighthouse --unit superyak-alerttest.service" \
     /bin/false
   ```
   Within about a minute, Ops shows exactly two lines from Odo:
   - "superyak-alerttest stopped unexpectedly … systemd is restarting it";
   - "superyak-alerttest is down … (start-limit-hit)".

   `make station-alerts` shows 3 stops held back. Then run `systemctl --user reset-failed superyak-alerttest`.
6. **Push main and announce** in the room what shipped, and that the Ops lines from step 5 were the test.
7. **Rollback.**
   1. `make station-units-remove`: the timers are disabled and the units and drop-ins removed, then `daemon-reload`.
   2. Revert the merge as earlier Deploy sections do, and restart the five.
   3. `backups/station/` and `<data-dir>/alerts/` stay. The old code ignores both; delete them only if Andy asks.
   4. There's no database change to undo.

## Known limits

- **`OnFailure=` is dormant on the five services** with today's restart settings. `ExecStopPost=` does the work (S9).
- **Some stops aren't alerted.** A clean exit (status 0, or SIGTERM from something other than systemd) that systemd
  then restarts isn't alerted. Neither is a service that's up but failing every cycle: the watchers catch their own
  exceptions. There's no health monitor.
- **Nobody hears while the lighthouse or Odo stays down,** or after a power loss or a broken venv. The notifier runs
  on the station's own interpreter (S13).
- **Logs vanish at reboot** (volatile journald). On this Pi, `journalctl --user -u` finds nothing; use
  `--user-unit`.
- **Until 1.2, every copy is on the Pi's one NVMe disk.**
- **Copies cover `peer.sqlite3` only.** These aren't copied:
  - the peer identity in the data dir (`identity.json`, `peer-cert.pem`, `peer-key.pem`);
  - Odo's and Wormhole's configs and state, and the `Station.aDNA` vault;
  - `~/.config/superyak`.
- **A restore loses everything said since the copy,** and the runbook's undo steps depend on Andy remembering
  revocations and password changes.
- **Some held-back counts are never posted.** A count held back after a burst's last alert shows only in
  `make station-alerts`. After a long outage, only the 20 newest alerts are posted.
- **A project ship's watcher docked on the Pi later** gets the drop-in only when `make station-units` runs again.
- **Odo's `announced` list grows by one id per alert.** It's unbounded today.
- **The single-step copy holds its read lock for the whole copy.** Revisit if the file passes about 100 MB; the
  `files` table holds blobs.

## Open questions for the reviewer

1. **Deploy authority.** Does section 2 ("restarts the affected Pi services") cover installing new units and timers
   and adding drop-ins to Andy's five services? Or does `make station-units` wait for Andy? The writer leans to
   covered: they are this branch's deploy, and they can be removed in one command.
2. **`ExecStopPost=` as well as `OnFailure=`.** This departs from the brief's "OnFailure= on each unit", because of
   systemd 239's change. Confirm, or rule that a crash loop may stay silent.
3. **A channel outside the station** for when the lighthouse, Odo or the Pi is down, such as a push service or mail.
   This is Andy's choice, like 1.2.
4. **The constants:**
   - a 30-minute alert window;
   - a 36-hour stale threshold;
   - 1 GiB of free disk kept;
   - 7 days listed and 30 days kept for alerts;
   - the restore test monthly rather than nightly. It takes a few seconds, so nightly is cheap if preferred.
5. **The restore's undo steps** (runbook step 6) as a trusted command, `station-restore-reconcile --replaced <db>`.
   It would re-revoke keys and re-mark used invitations from the replaced file when that file is readable. This spec
   leaves them as a person's steps.
6. **The peer identity files** in the backup and in 1.2's copy. They're secrets, and losing them changes the
   station's federation identity.

## Out of scope

- Choosing the destination off the Pi, and transports other than a mounted directory (1.2).
- Health monitoring of running services, and a channel outside the station.
- Restoring automatically, or any command that writes the live database.
- Changes to the five unit files' own settings, to journald, or to Odo's watcher.
