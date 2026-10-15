# Station backups, a restore test and service alerts

Status: revision 4, approved under D8 (revision 4's own D8 re-check is in its review map). Revision 1 (11e488b) had a fresh reviewer's verdict, APPROVE WITH CHANGES: 3
must-fix, 14 should-fix and rulings on Q1–Q6. Revision 2 (14234fd) applied all of it. The same reviewer's re-check of
revision 2 was APPROVE WITH CHANGES, with 2 must-fix (R-M1, R-M2) and 6 should-fix (S-R1 to S-R6), and said that
applied as written the spec passes D8 and goes to planning with no further review. Rio Grande ruled to apply all of it
exactly as written, and this revision does. The review maps at the end walk each item. Roadmap items 1.1 and 1.3
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
- **The hand-made copies** live in `~/.local/share/superyak/backups/` (0700), under three naming styles. All are
  0600.
- **Disk.** A 939 GB NVMe, 2% used. `/tmp` is on it, not tmpfs. `/run/user/1000` is a 1.6 GB tmpfs, and linger is
  on.
- **`make dock` rewrites `superyak-ship.service` whole** (install.py:289–301). Changes to the five units therefore
  go in drop-ins.
- **Which interpreter each unit runs.** The lighthouse and the door run `%h/superyak/peer/.venv/bin/python`, an
  editable install of the main checkout; ship, odo and wormhole run `/usr/bin/python3 %h/superyak/agent/run_agent.py`.
  Every new unit and every `ExecStopPost=` uses the venv's interpreter, which imports `superyak_peer` under `-I` from
  any directory (checked).

## Decisions

- **S1. Trusted CLI commands and systemd timers, not the station process.**
  - **Why:** a backup or an alert must work while the lighthouse is down or crash-looping. Running them outside the
    server keeps new threads out of it. systemd brings the schedule, the catch-up after downtime, the journal and
    `OnFailure=`.
  - **New commands** in `__main__.py`: `station-backup`, `station-restore-test`, `station-restore-reconcile` (S16),
    `station-alert` and `station-alerts`. `station-notices` gains alerts. The logic goes in new modules, `backups.py` and `alerts.py`,
    which use only the standard library.
  - **No agent change.** Odo's watcher posts the alerts as it is.
- **S2. The backup.**
  - **Source.** It refuses a symlinked data dir or database, as `_check_paths` does. Then it opens
    `sqlite3.connect(db_path.absolute().as_uri() + '?mode=ro', uri=True, timeout=30)`, as `validate_demo` builds its
    URI (`__main__.py:125`), with `absolute()` for `resolve()` since symlinks are already refused. A hand-built
    `file:…` URI breaks on a path that holds `?`, `#` or `%`.
  - **No writes to the live file.** It never constructs `Store`, whose constructor writes the schema, the migrations
    and the system author. It never takes the dispatch gate either: SQLite's backup API copies a consistent snapshot
    of committed data on its own.
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
    It publishes with `os.link(tmp, FILE)` and then removes the temporary file, so an existing FILE is never replaced,
    even one created after the check. Future Deploy sections use `make station-backup OUTPUT=…` in place of their
    one-line Python copies.
  - **After a schema change.** Future Deploy sections that change the schema also run `make station-restore-test`
    after their restart, so a migration that can't open last night's copy is found the same day.
- **S3. Keep 14 nightly and 8 weekly copies.**
  - **Nightly:** keep the newest copy of each of the 14 most recent UTC days that have a copy.
  - **Weekly:** keep the newest copy of each of the 8 most recent ISO weeks that have a copy.
  - **Everything else in the rotation is deleted.** Because only days and weeks that have a copy count, a Pi that
    was off, or nights that failed, never age out the last good copies.
  - **When and what:** pruning runs only after a new checked copy is in place. It deletes only files whose names
    match the pattern, plus temporary files (`.peer-*.tmp` and their `.tmp-journal`) more than a day old. That's at
    most 22 copies, about 30 MB today.
  - **The clock must move forward.** If the clock reads earlier than the newest copy's name, the backup writes nothing,
    prunes nothing and exits 1 ("the Pi's clock is behind the newest copy"). So a clock that is wrong in either
    direction fails loudly every night instead of skewing the rotation: a clock behind would give a new copy an old
    name that pruning could delete at once, and a clock ahead would leave a future name "newest" for good, so the stale
    notice would never fire and the restore test would keep testing an old file.
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
      and password hashes, and the uncollected plaintext secrets listed under Security.
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
       system temp dir when that's unset. Remove leftover scratch directories more than a day old: only directories
       owned by this user, and never symlinks, which matters in the shared `/tmp` fallback.
    3. Copy the backup into `scratch/peer.sqlite3` (0600) with the backup API, and run `integrity_check` on it. The
       backup is opened with `mode=ro`, so `BACKUP=` pointed at the live file reads it and nothing more. The copy is
       taken under the rotation's `.lock`, so a concurrent backup's pruning can't remove the file mid-copy.
    4. Read three counts, read-only: users that aren't the system author, rooms, and messages. Then run
       `station-restore-reconcile` (S16) on the scratch copy, without `--replaced`, so a schema change that breaks it
       fails a restore test within a month. It changes none of the three counts. The scratch directory holds no
       `dispatch.lock` until step 5, so S16's live-directory rule doesn't refuse it; the reconcile must stay before the
       server's start.
    5. Start `sys.executable -I -m superyak_peer serve --data-dir <scratch> --host 127.0.0.1 --port P`. P comes from
       binding port 0 and closing it; the start is tried up to 3 times if the server exits during start-up.
    6. Wait up to 60 s for `http://127.0.0.1:P/api/health` to answer 200.
    7. Read the counts again through `Store(<scratch>)`, the trusted local path. They must equal the first counts, with
       at least one user and one room.
    8. Tear down on every path: SIGTERM, then SIGKILL after 10 s, then `wait()`. Remove the scratch directory in
       `finally`. SIGTERM and SIGHUP to the command become `SystemExit`, so `finally` runs when it's stopped by hand;
       under systemd the cgroup kill also covers the child.
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
  - **`superyak-restore-test.timer`:** `OnCalendar=*-*-01 04:30:00`, `RandomizedDelaySec=30min`, `Persistent=true`
    and `WantedBy=timers.target`.
  - **`superyak-alert@.service`:** `Type=oneshot` and `TimeoutStartSec=1min`. It runs
    `ExecStart=%h/superyak/peer/.venv/bin/python -I -m superyak_peer station-alert --data-dir
    %h/.local/share/superyak/lighthouse --unit %i --monitor`. `%i` is the raw
    instance; `%I` would turn its dashes into slashes. It has no `OnFailure=` of its own, so it can't recurse.
  - **`Persistent=true` on a Pi that was off.** The user manager starts at boot, since linger is on. Each timer that
    missed its time then runs once, not once per missed night, after its random delay.
    - **The backup** is ordered after the lighthouse's start job.
    - **After a power cut,** the lighthouse may not yet have recovered a hot journal. The read-only open succeeds, but
      the copy then fails with `SQLITE_READONLY_ROLLBACK`, so the backup retries the open and the copy together for up
      to 60 s.
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
    - the alerts of the last 7 days, as `{'id': 'alert-<id>', 'text': …}`: at most the 20 newest, plus every `down`
      and `failed` alert of those 7 days, so a give-up line is never pushed out by restarts; oldest first;
    - S14's stale-backup notice.
  - **A damaged store doesn't silence alerts.** The alerts and the stale notice are read before `Store` is opened. If
    `Store()` or `station_notices()` raises while either directory exists, `station-notices` still prints them,
    writes the error's class name to stderr, and exits 0. Odo runs the command with `check=True` (watch.py:265), so
    otherwise the backup's exit-12 line, "the live database may be damaged", would never be posted. Without either
    directory it behaves exactly as today (R15).
  - **The post.** Odo's existing `_announce` posts each one once, under client id `notice-alert-<id>`. Its existing
    rules apply: other errors are retried next cycle, and 403, 404 or 409 is never retried.
  - **Not `_station`.** Spec S11 gives the system author one writer, and this spec doesn't add a second.
  - **Clean-up.** The notifier deletes alert files more than 30 days old each time it runs.
- **S11. The line in Ops: no journal lines.**
  - **The templates.** These are examples; values in angle brackets vary.
    - `stopped`: "Station alert: superyak-lighthouse stopped unexpectedly at 03:12 on 2026-10-14 (exit-code, status 1).
      systemd restarts it unless it was being stopped. Log on the Pi: journalctl --user-unit
      superyak-lighthouse.service --since '2026-10-14 03:02'." When failures were held back, it adds " <4> more stops
      since <02:41> were held back."
    - `down`: "Station alert: superyak-odo is down since 03:12 on 2026-10-14: systemd stopped restarting it
      (start-limit-hit). Log on the Pi: …"
    - `failed`: "Station alert: the nightly backup failed at 03:41 on 2026-10-14: <not enough disk space>. The earlier
      copies are kept. Log on the Pi: …". The restore test's line starts "the monthly restore test failed". The
      reason comes from the exit code (Error handling). When the timer unit ended on a systemd result rather than an
      exit code, `timeout` gives "it ran past its time limit", and `signal`, `core-dump` and `oom-kill` give "it was
      killed (<status>)".
  - **How `kind` is chosen.** The `ExecStopPost=` path gives `stopped`. `--monitor` for `superyak-backup.service` or
    `superyak-restore-test.service` gives `failed`, and `--monitor` for any other unit gives `down`.
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
- **S12. At most one `stopped` line per unit per window: 30 minutes, doubling up to 6 hours in a burst.**
  - **Held back, then counted.** A `stopped` failure inside the window adds to a count in `alerts/rate.json`. The next
    `stopped` alert for that unit reports the count, and then the count resets.
  - **Giving up isn't windowed.** `down` and `failed` are always queued, up to the backstop below. An earlier
    `stopped` line can't hold them back, and they aren't windowed among themselves: neither can repeat unless a person or a timer starts the unit
    again, so they can't loop. (Revision 1 windowed them per unit and kind; the reviewer's deploy check, "a second run
    queues only the `down` line", needs them unwindowed.)
  - **A backstop.** As a backstop, more than 6 `down` or `failed` lines for one unit in a day are held back and
    counted like stops. This is not needed for any path known today.
  - **Locking.** Records are written under a flock on `alerts/.lock`. If 5 s pass without the lock, the alert is
    queued anyway: a duplicate is better than a lost alert.
  - **Backing off.** Inside an unbroken burst, each further window for the same unit doubles, from 30 minutes up to
    6 hours. The burst ends after a full window with no failure. An overnight crash loop of a watcher then posts 5
    lines, not 16, and a long lighthouse outage queues fewer.
  - **The worst case** for a crash loop is two `stopped` lines per unit in its first hour, then one per 6 hours.
- **S13. When the station is down.**
  - **The lighthouse is down.** Odo's cycles fail and the files wait in the queue. Once the lighthouse is back, Odo's
    next cycle, within 30 s, posts them. Each line says when its failure happened.
  - **Odo is down.** The alerts wait the same way. Odo posts them, its own included, when it returns.
  - **Both stay down, or the Pi is down or loses power.** The outage is silent: nobody hears. This spec has no
    channel outside the station and builds nothing toward one. Choosing one is Andy's call, and it goes on the
    roadmap's list of his decisions beside 1.2's destination (ruling Q3). The queue files are the only seam: a later
    sender reads the same files and keeps its own record of what it sent, and nothing here changes.
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
  - A channel outside the station for when it's down (S13), now on the roadmap's list of his decisions.
  - Making journald persistent, which is root's configuration.
  - Adding `-I` to Odo's `--notices-command`, an edit to his odo unit (Known limits).
- **S16. `station-restore-reconcile`: take back what a restore revives.** A restored copy gives back, before anyone can
  act in the browser:
  - ended sessions and revoked ship keys;
  - used invitations and account activations;
  - uncollected secrets: a confirmed docking's plaintext ship key (`dockings.key`, ships.py:164), and an approved
    request's invitation `token` and reusable `share_url` (access_requests.py:88), even ones the station had since
    expired and revoked (ships.py:109–110);
  - requests and dockings decided since the copy, pending or waiting again;
  - members removed from rooms or spaces since then, Wormhole included, so a room Andy unbridged is bridged again;
  - higher roles (`is_admin`, `is_super_admin`), old passwords and old law layers;
  - lower `mentions` sequence numbers, so every watcher's saved `mention_seq` hides new mentions until the numbers
    catch up (watch.py:92–97).

  These are the only point in the design where a mistake reopens access, and they come at the most stressful moment.
  So a small trusted command takes them back, on a staged copy, before that copy goes live.
  - **The command:** `station-restore-reconcile --db FILE [--replaced FILE] [--live-data-dir DIR]`, and
    `make station-restore-reconcile DB=… [REPLACED=…]`. Andy runs it in runbook step 5 on the staged copy.
    - It refuses a FILE in the live data dir: the directory `--live-data-dir` names (the make target passes
      `$(STATION_DATA)`), and any directory holding a `dispatch.lock`, which every directory a station has opened
      holds.
    - It refuses a symlink, and a copy that fails `integrity_check` or has no `users` table (a 0-byte file is a valid
      empty database; final review M5).
    - The command (not the restore test, which calls the reconcile directly on its scratch `peer.sqlite3`) refuses a
      FILE with any name but `restored.sqlite3`, the name runbook step 5 always stages, before anything is opened.
      `peer.sqlite3` there is the live file or the original runbook step 4 set aside (final review I1), and
      `chosen.sqlite3` there would be reconciled while step 6 installs `restored.sqlite3` unreconciled (re-review probe
      (f), ruled in by the coordinator; it only narrows). For the same reason it refuses a
      `--replaced` FILE with any name but `peer.sqlite3`, before anything is opened: REPLACED= is always the one runbook
      step 4 set aside, and a typo naming `chosen.sqlite3` (or `restored.sqlite3`, or a rotation copy) would compare
      the copy with itself, exit 0 and leave every key revoked since the copy working (final fix round, ruled in by
      the coordinator; it only narrows).
    - **An older copy.** A copy taken before a later migration lacks some tables or columns. A step whose table or
      column the staged copy doesn't have is skipped and named in the report: migrations only add, empty or at a
      default that grants nothing, so there is nothing there to take back. A missing table or column is never an
      error. The same holds for the replaced file: what it lacks is not compared.
    - It opens `--replaced` read-only (`mode=ro`), and uses it only when its `quick_check` passes. A replaced file that
      won't open or fails its check is treated as absent, and the report says so: the command fails closed. The report
      gives the reason, such as a hot journal beside the replaced file.
  - **Always, in one transaction.** Each step only takes access away:
    1. delete every session;
    2. mark every unused invitation and account activation used;
    3. for each docking that still holds a key, revoke that key and expire the docking, as ships.py:109–110 does, and
       clear every access request's uncollected `token` and `share_url`;
    4. expire every pending access request and waiting docking (`expires` = now), so requesters ask again;
    5. set the `mentions` and `events` sequences to the replaced file's when they are higher, or raise them by
       1,000,000 without one, so no watcher's saved cursor hides a new mention.
  - **With a usable replaced file:**
    - revoke every ship key revoked there;
    - for rooms and spaces in both files, remove each room, remote-room or space membership that isn't there
      (`room_members`, `remote_room_members`, `space_members`);
    - lower `is_admin` and `is_super_admin` to the replaced file's value where that is lower.
      Each account lowered is recorded as `change_account_role` records a change (auth.py): `role_version` becomes one
      past the higher of the two files' values, and one `account_role_changes` row is written with the old and new
      role, that version and the system author as actor (the account itself when a copy has no system author). A
      copy lacking `role_version` or the table is still lowered, and the report names what it skipped. (Follow-up
      from the final reviews; narrows, no new D8 round.)
    - close each breakout that is closed there and still open here, with its closing time (Rio Grande's ruling, Q1).
    - unpair each peer that is paired here and has a `peers` row with `paired` = 0 there, exactly as
      `Federation.unpair` does (federation.py:43-45): `peers.paired` = 0, the `pending` and `failed` outbox rows of
      that peer's contacts (by `peer_id` through `remote_contacts`) `withdrawn`, and its inbox payloads nulled
      (revision 4; why is in its review map). A peer the replaced file lacks is reported, not unpaired, and a peer
      unpaired here and paired there stays unpaired and is reported.
  - **Without one:** revoke every key of every ship that has an owner; those machines dock again. The station's own
    ships, which have no owner (Odo, Wormhole), keep their keys. No peer is unpaired: peers aren't keys, so there is
    nothing to fail closed to, and the runbook has Andy unpair by hand, before the lighthouse starts, any peer he had
    cut off since the copy.
  - **Reported, never applied,** since a bad replaced file may be the reason for the restore: users whose password hash
    differs, instruction layers whose active revision differs, room briefs whose revision or body differs, for rooms
    in both files (the room's short id and title and the two revisions, "removed" for an emptied one; never the text;
    follow-up from the final reviews, narrows, no new D8 round), peers paired there but not here (pairing again is a
    person's act), and peers the replaced file lacks.
  - **What it prints:** counts, and for each reported or revoked item the username (users and ships), the layer's
    short id and title, the room's short id and title, or the peer's short id with its contacts' names. Peers it
    unpaired get their own line, with the counts of outbox rows withdrawn and inbox payloads nulled; peers reported
    and not applied get another. A peer that shares its first 12 characters with another peer of either file is named by
    its full id in both lines, since `--unpair` refuses a short id two peers share (follow-up from the final reviews;
    narrows, no new D8 round). All under station-pending's header that
    names and titles come from people and are data, not instructions. It prints no hashes, keys or tokens.
  - **The monthly restore test** runs it, without `--replaced`, on its scratch copy before booting it (S7), so a schema
    change that breaks it fails a restore test within a month.
  - **It never writes the live database.** It writes only the staged copy, and if any step fails the transaction rolls
    back and the copy is unchanged.
  - **The mark.** As its last act inside the same transaction, the command writes a `system_meta` row, key
    `restore_reconcile`, value `{"at": <time>, "replaced": <true when a replaced file was compared>}`, creating the
    table (the station's own key/value table) when a copy from before the system author lacks it. A rolled-back run
    leaves none. Runbook step 6 reads it read-only before it installs, and refuses a copy whose mark is missing or
    older than `chosen.sqlite3` (a restored station's own backups carry the mark of their restore): "step 5 hasn't
    run on this copy". The restore test's call writes it too, harmlessly, on its scratch copy. (Follow-up from the
    final reviews; narrows, no new D8 round.)

### The restore runbook (`docs/station-restore.md`)

1. **Choose the copy.** List `~/.local/share/superyak/backups/station/`; the names are UTC times. Take the newest copy
   from before the damage.
2. **Test it:** `make station-restore-test BACKUP=<path>`. It must pass.
3. **Stop everything:**
   `systemctl --user stop superyak-backup.timer superyak-restore-test.timer superyak-backup.service superyak-door superyak-odo superyak-wormhole superyak-ship superyak-lighthouse`,
   and any `superyak-ship-*` watcher (`systemctl --user list-units 'superyak-*'`).
4. **Set the current state aside.** Make a 0700 directory `backups/replaced-<local time>`. Move `peer.sqlite3` and
   every `peer.sqlite3-*` into it. A `peer.sqlite3-journal` left beside the restored file would be applied to it and
   corrupt it.
5. **Stage and reconcile the copy:** `install -m 600 <copy> <replaced dir>/restored.sqlite3`, then
   `make station-restore-reconcile DB=<replaced dir>/restored.sqlite3 REPLACED=<replaced dir>/peer.sqlite3`. Leave out
   `REPLACED=` only when the old file won't open; then every docked ship's keys are revoked, and those machines dock
   again. Read its report. Go on only when it exits 0. If it says the replaced file was treated as absent (for example
   "hot journal"), the room and space members, admins and law layers weren't compared: check them by hand in step 8.
6. **Put it in place:**
   `install -m 600 <replaced dir>/restored.sqlite3 ~/.local/share/superyak/lighthouse/peer.sqlite3`.
   The peer identity files stay where they are; nothing here moves them.
7. **Act on the report.** Change again any password it lists that was changed for a reason. Issue again any invitation
   still wanted. Tell the owners of ships whose keys were revoked to dock again. Requests and dockings since the copy
   were expired; their senders ask again, and nothing is approved from memory. If your own account comes back waiting
   for activation, renew it with `bootstrap-super-admin --renew-activation`.
8. **Start the lighthouse and the door.** Set the law layers the report listed as they should be, in the browser.
   Then start ship and odo, run `make station-rooms` and check the `bridged` column before starting wormhole. Check
   each with `is-active`, then start both timers.
9. **Say in the room** what was restored and from when. Everything said after the copy's time is gone.

## Requirements

- **R1.** `station-backup` copies with SQLite's online backup API, from a read-only connection, in one step. It never
  opens the live database for writing, never constructs `Store` and never takes the dispatch gate.
- **R2.** A copy appears under its final name only after it has passed `integrity_check`. It is created 0600 inside a
  0700 directory and renamed atomically, with the file and the directory fsynced.
- **R3.** S3's rule decides retention. Pruning runs only after a new checked copy is in place, and it deletes only
  names that match the pattern in the rotation directory, plus temporary files (`.tmp` and `.tmp-journal`) more than a
  day old. A clock earlier than the newest copy's name writes nothing, prunes nothing and exits 1.
- **R4.** `--output FILE` writes one checked copy to a new path, outside the rotation, and never replaces an existing
  path, even one created during the copy (`os.link`).
- **R5.** Low disk and failed checks write nothing, prune nothing and keep every earlier copy. They exit with the codes
  in Error handling.
- **R6.** An empty `--copy-to` does nothing. A set one refuses a missing directory, a symlink, or a directory on the
  rotation's filesystem. It copies the file at 0600, verifies the sha256 and applies S3 there. If it fails, the
  command exits 13 and keeps the local copy.
- **R7.** `GET /api/health` answers 200 `{"ok": true}` without a session, after one database read, and returns nothing
  else. The door is unchanged.
- **R8.** `station-restore-test` works as S7 says. It reads the copy read-only under the rotation lock, reconciles
  the scratch copy (S16), boots a loopback station from it, checks health and the counts, and always tears down, also
  on SIGTERM or SIGHUP: no process is left, and the scratch directory is removed. It removes only leftover scratch
  directories this user owns, never symlinks.
- **R9.** The restore test has no data-dir option, and it exits with the codes in Error handling.
- **R10.** Each of the five services has the S9 drop-in. A stop with `SERVICE_RESULT=success` queues nothing; any
  other result queues an alert. The backup and restore-test units alert through `OnFailure=`.
- **R11.** There is at most one `stopped` alert per unit per window. The window is 30 minutes and doubles, up to 6
  hours, with each further window of an unbroken burst; a full window without a failure ends the burst. Held-back
  failures are counted in the next `stopped` alert. `down` and `failed` are always queued, up to the backstop of 6 per
  unit in a day. When the lock can't be had within 5 s, the alert is queued anyway.
- **R12.** An alert is one line from S11's templates, with checked values only. It has no journal lines, no
  environment and no at sign, and an invalid unit is refused with nothing queued.
- **R13.** Alerts are queued as 0600 files in `<data-dir>/alerts/`. `station-notices` lists, from the last 7 days,
  at most the 20 newest plus every `down` and `failed` alert, and Odo posts each once in Ops through its existing
  path. Files more than 30 days old are deleted. When the store can't be opened, the queued alerts are still listed
  and the command exits 0. A file whose `at` is not a finite number is not an alert: it is skipped, and deleted once
  the file itself is over 30 days old. An alert whose text sanitises to nothing is not listed. (Follow-up from the
  final reviews; narrows, no new D8 round.)
- **R14.** A rotation whose newest copy is more than 36 hours old gives exactly one `backup-stale-<name>` notice. No
  rotation, or an empty one, gives none.
- **R15.** With no alerts directory and no rotation directory, `station-notices` prints exactly what it prints today,
  byte for byte. `Store.station_notices()` is unchanged.
- **R16.** The timers and units are exactly S8's. They're installed and removed only by the two make targets, and the
  five existing unit files are not edited.
- **R17.** `make station-backup [OUTPUT=…]`, `make station-restore-test [BACKUP=…]`, `make station-alerts` and
  `make station-restore-reconcile DB=… [REPLACED=…]` run the same commands by hand.
- **R18.** `station-restore-reconcile` works as S16 says. It refuses the live data dir, symlinks, a FILE not
  named `restored.sqlite3`, a `--replaced` not named `peer.sqlite3`, a copy without `users` and a copy that fails its check, and
  applies only changes that take access
  away, in one transaction. It prints counts, and the usernames,
  short ids and titles S16 names under the data-not-instructions header, never hashes, keys or tokens. With a usable
  replaced file it takes back the keys, memberships and roles taken away there, and unpairs the peers unpaired there
  (a peer the replaced file lacks is reported, not unpaired); without one, or with one that fails its check, it
  revokes every owned ship's keys, unpairs no peer, and says why. A step whose table or column the copy lacks is skipped
  and named, never an error.

## Error handling

| Command | Exit | Meaning | What happens |
|---|---|---|---|
| backup | 10 | Less than 1 GiB would be left, or ENOSPC during the copy | No copy, no pruning, the temporary file is removed; "not enough disk space" |
| backup | 11 | The copy failed `integrity_check` (or raised), and the live `quick_check` passed | Copy deleted; "the copy failed its check; tomorrow's run tries again" |
| backup | 12 | The live database fails `quick_check` | Copy deleted; "the live database may be damaged: don't restart or deploy before reading docs/station-restore.md" |
| backup | 13 | `--copy-to` failed | The local copy is kept and pruning has run; "the copy off the Pi failed" |
| backup | 1 | The clock is behind the newest copy's name | Nothing written or pruned; "the Pi's clock is behind the newest copy" |
| backup | 1 | Anything else: a missing or symlinked database, an open or copy still failing after 60 s, a pruning error | Old copies kept; "see the log" |
| restore test | 20 | No copy to test | "there is no backup to test" |
| restore test | 21 | The restored copy fails `integrity_check` | "the newest copy failed its check" |
| restore test | 22 | No health answer within 60 s, or the server exited | "the restored station did not start" |
| restore test | 23 | No users or rooms, or the counts changed | "the restored station is missing data" |
| restore test | 24 | `station-restore-reconcile` failed on the scratch copy | "the restore's reconcile step failed" |
| restore test | 1 | Anything else | "see the log" |
| alert | 2 | A run outside systemd (no `SERVICE_RESULT` or `--monitor` variables), or an invalid unit | Nothing queued; a usage message |
| reconcile | 1 | A refused FILE (live data dir, symlink, not named `restored.sqlite3`, no `users` table, failed check), a `--replaced` not named `peer.sqlite3`, or any error during the transaction; a missing table or column is skipped and named, never an error | The staged copy is unchanged; go on in the runbook only after exit 0 |

- **Every failing timer run** fails its unit. `OnFailure=` then queues the reason that matches the exit status, or
  S11's words for a systemd result.
- **A damaged live database** can't silence the queue: `station-notices` lists the alerts and exits 0 even when
  `Store()` raises (S10).
- **A notifier that can't write its queue** (disk full, permissions) prints to stderr, which goes to the journal, and
  exits 0. The unit's result doesn't change.
- **Busy or locked database.** Python's backup loop sleeps and retries; the unit's `TimeoutStartSec` bounds it.
- **A stop that times out** (`timeout`) or an OOM kill (`oom-kill`) is a failure, and it alerts.
- **Odo's post is refused for good** (403, 404 or 409). It's marked announced, as today, and the file stays on the
  Pi.

## Security

- **What a copy holds.** Every copy holds everything the station holds: room text, salted password hashes, session,
  key and docking-secret hashes, requesters' contacts, and, until they are collected, a docking's plaintext ship key,
  an approved request's invitation token and the reusable Tailscale share link. A copy keeps them for up to 8 weeks
  after the live file has cleared them. Copies are 0600 in 0700 directories, owned by andy, on the Pi's own disk.
  Anyone who can read them can already read the live file, the ships' key files and the share-link file, so a copy on
  the Pi adds little. A docking key a copy keeps can still be live: once a machine collects it, the live file holds
  only its hash, while the ship goes on using the key until it is revoked. So a copy can hold a working key for a
  remote machine's ship. That is why the copy off the Pi waits for Andy's decision on encryption (S5); on a restore,
  S16 revokes every key the restored copy still holds.
- **A restore brings back old access:** ended sessions, revoked keys, used invitations and activations, uncollected
  docking keys and invitation tokens, decided requests, removed room and space members, higher roles, old passwords
  and old law layers, and pairings with peers Andy had cut off. Restoring is a person's step.
  `station-restore-reconcile` (S16) takes back everything that only grants access before the copy goes live (a
  pairing only when the replaced file says it was taken away), and lists the rest for Andy.
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
    connection. The copy passes its check and lacks that row. After the writer rolls back and closes, the live file's
    bytes and mtime are unchanged and no journal is left beside it. A second run, while another process holds
    `dispatch.lock`, finishes too, which proves the gate isn't taken. The source connection is opened with `mode=ro`.
    Constructing `Store` raises (monkeypatched) and isn't reached.
  - `test_copies_are_private_checked_and_appear_whole` (R2). The modes are 0600 and 0700. A failure injected after
    the temporary write leaves neither a final file nor a temporary one.
  - `test_retention_keeps_14_days_and_8_weeks_and_nothing_else` (R3). Synthetic names cover 200 days, with gaps,
    several copies in one day and a month off. Hand-made names and other files are never touched; stale `.tmp` and
    `.tmp-journal` files are removed. A clock earlier than the newest name writes and prunes nothing and exits 1.
  - `test_output_writes_one_checked_copy_and_never_overwrites` (R4), including a FILE created during the copy.
  - `test_failures_keep_old_copies_and_exit_with_their_code` (R5), parametrised over the following, each leaving the
    earlier copies, no pruning and no temporary file:
    - a faked low free space, which gives 10;
    - a forced check failure, which gives 11;
    - a database with overwritten pages, which gives 12.
  - `test_copy_to_is_off_by_default_and_refuses_the_same_disk` (R6). An empty value copies nothing. The same device
    gives 13, with the local copy kept. A faked different device gives a 0600 copy with the same sha256.
- **`peer/tests/test_restore.py`:**
  - `test_health_answers_without_a_session` (R7). The body is exactly `{"ok": true}`, and the door answers 404 for
    `/api/health`.
  - `test_restore_test_boots_a_throwaway_station_from_the_newest_copy` (R8). A real subprocess server runs, the
    command exits 0, the scratch directory is gone and the port is closed.
  - `test_restore_test_failures_clean_up_and_exit_with_their_code` (R9), each removing the scratch directory and
    leaving no process:
    - no copy gives 20;
    - a damaged copy gives 21;
    - a server command that exits gives 22;
    - changed counts give 23;
    - a reconcile that raises (monkeypatched) gives 24.
  - `test_restore_test_has_no_data_dir_option` (R9): the parser rejects `--data-dir`.
  - `test_reconcile_takes_back_what_the_restore_revived` (R18). Build a station, copy it (A), then in the live file (B)
    revoke a key, remove a room member, demote an admin, use an invitation, deny a request and record a mention. After
    reconciling A against B:
    - the key is refused, the member can't read the room and the role is lower;
    - the invitation and the request can't be used;
    - no session is left, and the next mention's seq is past B's;
    - a changed password and a changed active layer are reported, not applied;
    - the output names the user whose password changed and contains no hash, key or token;
    - a peer unpaired in B after A ends with `paired` = 0, its contacts' `pending` and `failed` outbox rows
      `withdrawn` and `delivered` rows untouched, and its inbox payloads NULL; a peer unpaired in A and paired in B
      stays unpaired and is reported; a peer absent from B stays paired and is reported; another peer is unchanged.
  - `test_reconcile_without_the_replaced_file_fails_closed` (R18): every owned ship's keys are revoked, the station
    ships keep theirs, and every peer stays paired. A replaced file of junk bytes gives the same result as none, and the report says it was treated
    as absent.
  - `test_reconcile_rolls_back_when_a_step_fails` (R18): a later step raises (monkeypatched), the staged file's bytes
    are unchanged and the exit is 1.
  - `test_reconcile_skips_what_an_older_copy_lacks` (R18): a copy without `access_requests.share_url` and without
    `space_members` reconciles with exit 0, takes back its sessions, invitations and keys, and names the two skipped
    steps.
  - `test_reconcile_refuses_the_live_data_dir_and_symlinks` (R18): the `--live-data-dir`, a directory holding
    `dispatch.lock`, a symlink and a copy that fails its check are each refused, and the file is unchanged.
  - `test_reconcile_closes_breakouts_closed_since_the_copy` (R18): a breakout closed in B is closed after reconciling A.
- **`peer/tests/test_alerts.py`:**
  - `test_a_crash_queues_one_alert_and_a_clean_stop_queues_none` (R10).
  - `test_monitor_kinds` (R10): `--monitor` with `MONITOR_SERVICE_RESULT=start-limit-hit` for a service queues
    `down`; for the backup or restore-test unit it queues `failed`.
  - `test_stopped_alerts_are_held_back_and_back_off_per_unit` (R11), with a fake clock:
    - 6 crashes in 10 minutes queue one file;
    - one at 31 minutes is queued, saying "5 more stops since …";
    - one at 61 minutes is still held, because the second window is 60 minutes;
    - a `down` inside the window is queued, and so is a second `down` a minute later; a seventh `down` for the
      same unit in a day is held back and counted (the S12 backstop);
    - a full window without a failure ends the burst, and the window is 30 minutes again.
  - `test_the_lock_fallback_queues_anyway` (R11): with `alerts/.lock` held by another process, the alert is queued
    after 5 s.
  - `test_failed_backup_and_restore_runs_name_their_reason` (R12): every exit code in the table, and the systemd
    results `timeout`, `signal`, `core-dump` and `oom-kill`.
  - `test_alert_lines_hold_no_log_lines_mentions_or_unchecked_values` (R12):
    - invalid units are refused, with nothing queued;
    - an unknown result becomes `unknown`;
    - a fake secret in the environment appears in neither the file nor the text;
    - there's no at sign and no newline.
  - `test_notices_list_queued_alerts_and_are_unchanged_without_them` (R13, R15): the output without either directory
    is compared byte for byte. With 25 `stopped` alerts and one `down`, the 20 newest and the `down` are listed.
  - `test_notices_still_list_alerts_when_the_store_cannot_open` (R13). The database file is overwritten with junk and
    one alert is queued: the alert is listed and the exit is 0.
  - `test_a_stale_backup_is_announced_once_per_lapse` (R14).
  - `test_odo_posts_a_queued_alert_in_ops_once` (R13), in `test_ship_agent.py` beside
    `test_odo_announces_station_notices_in_ops`. An alert is queued while the watcher can't reach the station. The
    next cycle posts it, and the one after posts nothing.
- **`peer/tests/test_station_units.py`:** `test_units_say_what_the_spec_says` (R16). It parses `peer/systemd/` and
  checks:
  - the `OnCalendar` values, `Persistent=true` and `WantedBy=timers.target` on both timers;
  - `OnFailure=` on both oneshots, and no `Restart=` on them;
  - the drop-in's `ExecStopPost=-` with `-I`.

  `systemd-analyze --user verify` must also pass, but it runs only when `%h/superyak/peer/.venv/bin/python` exists:
  on other Linux machines verify fails on the missing executable, so there that part is skipped.
- **Mutation checks** on R1 (`Store` constructed), R3, R10 (a `success` that alerts), R11 and R18 (a step that grants
  access, and an unpair that leaves `paired` = 1), run with `PYTHONDONTWRITEBYTECODE=1` and the caches cleared.

## Deploy, with rollback

Under section 2 of the station law: a fresh reviewer's approval is posted in the room, and the Pi suites pass. Nothing
changes the schema. Nothing @mentions a ship. Section 2 covers merging, restarting and checking the affected services,
and reverting. It does not cover new standing jobs or drop-ins on Andy's five services, so steps 4 and 5 wait for
Andy's go-ahead, in his own words in a session's terminal or in his own mention, or he runs them himself. The merging
ship asks him once, after step 3. Rollback is a revert: the merging ship runs it whenever a check fails.

1. **Merge and run the suites** as in earlier Deploy sections (peer and agent, capped with `systemd-run --scope`).
2. **Run both commands once by hand,** before any unit exists:
   - `make station-backup`: expect one `peer-…Z.sqlite3`, mode 600, in `backups/station/`;
   - `make station-restore-test`: expect exit 0.
3. **Restart the lighthouse** so it serves `/api/health` (Odo and Wormhole restart with it, through `Requires=`).
   Check that `curl -fsS https://smart.tail7db420.ts.net/api/health` prints `{"ok":true}`. A loopback call gets 403
   from the Host check unless it sends the origin's Host. Announce the merge in the room, and ask Andy one question:
   may the units, timers and alert drop-ins be installed (`make station-units`)? The copy from step 2 starts the
   36-hour clock: if he hasn't answered by then, Odo's stale-backup notice is the reminder.
4. **After his go-ahead, install the units** with `make station-units`. Check that `systemctl --user list-timers
   'superyak-*'` shows both timers and that `systemctl --user show -p OnFailure -p ExecStopPost superyak-door` shows
   the drop-in. Restart the five in order (lighthouse, door, ship, odo, wormhole) and expect five `active`.
   `make station-alerts` must show an empty queue: these were clean stops, through the new `ExecStopPost=`.
5. **The alert check.** A throwaway unit that this deploy starts and stops itself; no live service is killed:
   ```bash
   systemd-run --user --unit superyak-alerttest -p Restart=always -p RestartSec=3 -p StartLimitBurst=4 \
     -p StartLimitIntervalSec=120 -p OnFailure=superyak-alert@superyak-alerttest.service.service \
     -p "ExecStopPost=-$HOME/superyak/peer/.venv/bin/python -I -m superyak_peer station-alert --data-dir $HOME/.local/share/superyak/lighthouse --unit superyak-alerttest.service" \
     /bin/false
   ```
   Run it once: inside 30 minutes, a second run queues only the `down` line. Within about a minute, Ops shows exactly
   two lines from Odo:
   - "superyak-alerttest stopped unexpectedly … systemd restarts it unless it was being stopped";
   - "superyak-alerttest is down … (start-limit-hit)".

   `make station-alerts` shows 3 stops held back. Then run `systemctl --user reset-failed superyak-alerttest`, and
   also `systemctl --user reset-failed 'superyak-alert@superyak-alerttest.service.service'` if that unit failed.
6. **Announce** in the room what was installed, and that the Ops lines from step 5 were the test. Say plainly that an
   outage of the lighthouse, Odo or the Pi is still silent until Andy picks a channel outside the station.
7. **Rollback.**
   1. `make station-units-remove`: the timers are disabled and the units and drop-ins removed, then `daemon-reload`;
      it also stops a running backup or restore test and resets their failed state. Skip this step if the units were
      never installed.
   2. Revert the merge as earlier Deploy sections do, and restart the five.
   3. `backups/station/` and `<data-dir>/alerts/` stay. The old code ignores both; delete them only if Andy asks.
   4. There's no database change to undo.

## Known limits

- **`OnFailure=` is dormant on the five services** with today's restart settings. `ExecStopPost=` does the work (S9).
- **Some stops aren't alerted.** A clean exit (status 0, or SIGTERM from something other than systemd) that systemd
  then restarts isn't alerted. Neither is a service that's up but failing every cycle: the watchers catch their own
  exceptions. There's no health monitor.
- **An outage of the lighthouse, Odo or the Pi is silent.** Nobody hears while the lighthouse or Odo stays down, after
  a power loss, or when the peer venv is broken: every notifier runs on the venv's interpreter (S13). A channel
  outside the station is on Andy's decision list.
- **Logs vanish at reboot** (volatile journald). On this Pi, `journalctl --user -u` finds nothing; use
  `--user-unit`.
- **A peer is unpaired on the replaced file's word** (S16, revision 4). If that file is damaged but passes its check, a
  wanted peer is cut off; Andy pairs it again, and the withdrawn outbox rows and nulled inbox payloads don't come
  back. Without a usable replaced file no peer is unpaired, and the runbook's hand step covers it.
- **Until 1.2, every copy is on the Pi's one NVMe disk.**
- **Copies cover `peer.sqlite3` only.** These aren't copied:
  - the peer identity in the data dir (`identity.json`, `peer-cert.pem`, `peer-key.pem`). By ruling Q6 they stay out
    of the nightly rotation: they never change, they're private keys, and the lighthouse doesn't use them today. A
    restore keeps them in place. Whether 1.2's copy includes them, encrypted, is Andy's;
  - Odo's and Wormhole's configs and state, and the `Station.aDNA` vault;
  - `~/.config/superyak`.
- **A restore loses everything said since the copy,** and a password changed since the copy is only reported, not
  restored (S16).
- **Some held-back counts are never posted.** A count held back after a burst's last alert shows only in
  `make station-alerts`. After a long outage, only the 20 newest alerts plus every `down` and `failed` are posted.
- **A project ship's watcher docked on the Pi later** gets the drop-in only when `make station-units` runs again.
- **Odo's `announced` list grows by one id per alert.** It's unbounded today.
- **Odo's `--notices-command` runs without `-I`** from Odo's workspace, so that directory is on `sys.path` for the
  command this spec extends. Fixing it is an edit to Andy's odo unit; it is listed for him.
- **The single-step copy holds its read lock for the whole copy.** Revisit if the file passes about 100 MB; the
  `files` table holds blobs.

## Rulings on the open questions

1. **Deploy authority.** Ruled by the reviewer: not covered; it waits for Andy (Deploy).
2. **`ExecStopPost=` as well as `OnFailure=`.** Confirmed: the 239 change is in the Pi's NEWS, and a crash loop must
   not stay silent. Restart settings stay unchanged (S9).
3. **A channel outside the station.** Andy's. Nothing is built toward one; the queue files are the only seam, an
   outage is said to be silent (S13, Known limits, Deploy step 6), and the question is on the roadmap's list of his
   decisions.
4. **The constants.** Kept: a 30-minute first window, now doubling up to 6 hours within a burst (S12); 36 hours; 1
   GiB; 7 days listed, with every `down` and `failed` always listed (S10), and 30 days kept; the restore test monthly,
   plus a by-hand run after schema changes (S2).
5. **The restore's undo steps.** Built in this spec: `station-restore-reconcile` (S16).
6. **The peer identity files.** Left out of the nightly rotation (Known limits); 1.2's copy is Andy's.

## Out of scope

- Choosing the destination off the Pi, and transports other than a mounted directory (1.2).
- Health monitoring of running services, and a channel outside the station.
- Restoring automatically, or any command that writes the live database. S16 writes only the staged copy.
- Changes to the five unit files' own settings, to journald, or to Odo's watcher.

## Review map (revision 2: the D8 review of 11e488b)

| Item | Ruling | Where |
|---|---|---|
| M1: installing units waits for Andy (Q1) | Applied: steps 4–5 wait for his go-ahead; step 3 restarts the lighthouse, checks `/api/health` over the tailnet and asks once; removing the units is a revert | Deploy (opening paragraph, steps 3–7), ruling 1 |
| M2: a restore leaves revived access in place (Q5) | Applied, with the reviewer's text; **re-check before the plan**. The writer added: `--live-data-dir` plus the `dispatch.lock` rule for "the live data dir"; a replaced file that fails its check counts as absent (fail closed); restore-test exit 24; the transaction's roll-back on failure; the reported-not-applied check in the first reconcile test | S16, the runbook (steps 3–9), R18, R8, S7 step 4, Security, Error handling, `test_reconcile_*` in test_restore.py, Known limits |
| M3: a damaged database silences its own alert | Applied | S10 ("A damaged store doesn't silence alerts"), R13, Error handling, `test_notices_still_list_alerts_when_the_store_cannot_open` |
| SF1: the restore-test timer has no `[Install]` | Applied | S8, Testing (`test_units_say_what_the_spec_says`) |
| SF2: a wrong clock breaks the rotation | Applied | S3, R3, Error handling, retention test |
| SF3: what a copy holds | Applied | Security, S5 |
| SF4: stale facts (interpreters, the 0644 copy) | Applied; the S15 bullet replaced by the odo `-I` item | What the code and the Pi show, S15 |
| SF5: where a hot journal fails, and the URI | Applied | S8, S2 |
| SF6: the R1 test | Applied | Testing |
| SF7: `--output` overwrites in a race | Applied (`os.link`) | S2, R4, Testing |
| SF8: restore-test hygiene | Applied | S7 steps 2, 3 and 8, R8 |
| SF9: the `stopped` line, systemd results, how `kind` is chosen | Applied | S11, Deploy step 5, Testing (`test_monitor_kinds`) |
| SF10: crash loops and the queue (Q4) | Applied. The writer also made `down` and `failed` unwindowed, which Deploy step 5's "a second run queues only the `down` line" needs | S12, S10, R11, R13, Testing |
| SF11: deploy details | Applied | Deploy steps 5 and 7.1 |
| SF12: Odo's notices command lacks `-I` | Applied | Known limits, S15 |
| SF13: test gaps | Applied | Testing (`test_monitor_kinds`, `test_the_lock_fallback_queues_anyway`, the health test, `test_restore_test_has_no_data_dir_option`, the retention test, the verify condition) |
| SF14: future Deploy sections | Applied | S2 ("After a schema change") |
| Q1–Q6 | Adopted as ruled | Rulings on the open questions |
| Q3's decision list | "A channel for when the station is down" added beside 1.2 | [roadmap](../plans/2026-10-12-station-roadmap.md), "What Andy does" |

## Review map (revision 3: the re-check of 14234fd)

| Item | Ruling | Where |
|---|---|---|
| R-M1: a report Andy can't act on | Applied as written: usernames, layer and room short ids and titles, and peer short ids under station-pending's data-not-instructions header; never hashes, keys or tokens | S16 ("What it prints"), R18, `test_reconcile_takes_back_what_the_restore_revived` |
| R-M2: an older copy makes the reconcile fail | Applied as written: a missing table or column is skipped and named, never an error, in the staged copy and the replaced file | S16 ("An older copy"), R18, Error handling, `test_reconcile_skips_what_an_older_copy_lacks` |
| S-R1: say why the replaced file was treated as absent | Applied | S16 (the replaced-file bullet), runbook step 5 |
| S-R2: fix the law before the ships start | Applied | Runbook step 8 |
| S-R3: tests for the writer's additions | Applied; exit 24 was already tested | `test_reconcile_without_the_replaced_file_fails_closed` (junk replaced file), `test_reconcile_rolls_back_when_a_step_fails`, `test_restore_test_failures_clean_up_and_exit_with_their_code` (24) |
| S-R4: a copy can hold a working key | Applied | Security ("What a copy holds") |
| S-R5: the reconcile stays before the server's start | Applied | S7 step 4 |
| S-R6: a backstop for `down` and `failed` | Applied | S12, R11, `test_stopped_alerts_are_held_back_and_back_off_per_unit` |

## Review map (Rio Grande's ruling on the plan review's Q1 (2026-10-14))

| Item | Ruling | Where |
|---|---|---|
| Q1: a breakout its ship closed since the copy reopens after a restore, and its members can post and record mentions there again | Ruled in. It only takes access away, so it narrows S16 and needs no new D8 round | S16 ("With a usable replaced file"), Testing (`test_reconcile_closes_breakouts_closed_since_the_copy`) |

## Review map (revision 4: the Task 11 review's C1, and its D8 re-check)

| Item | Ruling | Where |
|---|---|---|
| C1: the runbook's re-unpair window is real. "Check delivery now" and `POST /api/sync` deliver to every paired peer whatever `--sync` says, and inbound `/federation/events` accepts any paired peer | Rio Grande ruled the take-away direction into the reconcile, exactly as `Federation.unpair`; re-pairing stays a person's act | S16, R18, Security, Testing, Known limits, the runbook |
| D8 re-check must-fix 1: "unpaired there" undefined for a peer the replaced file lacks | A `peers` row with `paired` = 0; a lacked peer is reported, not unpaired | S16, R18, Testing |
| D8 re-check must-fix 2: the runbook kept the false `--sync` claim | Removed. With a usable replaced file the reconcile unpairs; without one, Andy unpairs by hand with the lighthouse stopped | the runbook |
| D8 re-check should-fix 3 and 4: the unpaired report line; a Known limit | Applied | S16 ("What it prints"), Known limits |

## Follow-ups (from the final reviews; each narrows, no new D8 round)

| Item | Change | Where |
|---|---|---|
| The step-6 mark catches a skipped step 5 | The reconcile writes the mark above; step 6 refuses a copy without it | S16 ("The mark"), the runbook step 6, `test_step_6_*` |
| R16: the existing unit files are not edited | The units test compares their bytes before and after `make station-units` and `station-units-remove` | R16, `test_station_units_install_and_remove_only_their_own_files` |
| Role lowering leaves a trace | `role_version` bump and an `account_role_changes` row, as the station's role changes do | S16 ("With a usable replaced file"), `test_lowering_a_role_bumps_role_version_and_records_a_change` |
| A restore brings back a changed or removed room brief | Reported by room short id and title, "reported, not applied", never the text | S16 ("Reported, never applied"), runbook step 7, `test_reconcile_reports_briefs_changed_since_the_copy_without_their_text` |
| A colliding short id prints twice | The two peer lines print the full id for a peer sharing its 12-character prefix | S16 ("What it prints"), `test_a_peer_sharing_its_short_id_prints_its_full_id_in_every_peer_line` |
| Odd alert files | `at` must be finite, else the file is skipped and cleaned by its mtime; an alert whose text sanitises to empty is not listed | R13, `test_an_alert_with_a_non_finite_time_is_skipped_and_cleaned`, `test_an_alert_whose_text_sanitises_to_nothing_is_not_listed` |
| The work board's tables (`board_items`, `board_links`, `claims`) | Checked: the reconcile skips nothing. Board items and claims are coordination, not access, and are not compared; a test makes any new table be classified | S16, `test_every_table_is_either_reconciled_or_named_coordination` |
