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
  members (Wormhole too, so a room you unbridged is bridged again), higher roles, old passwords, old law layers and peers you had unpaired.
  Step 5 takes back everything that only grants access (a peer's pairing included) before the copy goes live, and lists
  the rest for you.

Run every step on the Pi, from `~/superyak`, in one terminal that you keep open. If it closes, set `ASIDE` again (step 4)
to the existing `replaced-…` directory instead of making a new one.

1. **Choose the copy.** `ls -l ~/.local/share/superyak/backups/station/`. The names are UTC times
   (`peer-20261014T033112Z.sqlite3`). Take the newest copy from before the damage.
2. **Test it:** `make station-restore-test BACKUP=<path>`. It must pass.
3. **Stop everything.** First write down the project ships' watchers that are running; step 8 starts them again:
   ```bash
   systemctl --user list-units --plain --no-legend 'superyak-ship-*'
   systemctl --user stop superyak-backup.timer superyak-restore-test.timer superyak-backup.service superyak-door superyak-odo superyak-wormhole superyak-ship superyak-lighthouse
   systemctl --user list-units 'superyak-*'
   ```
   Stop every `superyak-ship-*` watcher the first command listed, and any the last list still shows.
4. **Set the current state aside.** Nothing may have the database open: `fuser -v ~/.local/share/superyak/lighthouse/peer.sqlite3`
   must print nothing. Make a 0700 directory and move `peer.sqlite3` and every `peer.sqlite3-*` into it. A
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
   machines dock again, and no peer is unpaired (see the peers paragraph below). It refuses a swapped `DB=` and
   `REPLACED=`, the same file twice, and a hard link. Read its report. Go on only when it exits 0. If it says the replaced file was treated as absent
   (there is no such file), `REPLACED=` is wrong: stop, find step 4's directory, stage the copy again (the `install` line above), then run both lines. Don't go on, and don't
   just run the reconcile again on the same file: the first run raised its sequences and a second one is refused as "swapped". If it
   says that for another reason (for example "a hot journal beside it"), the room and space members, admins, law layers
   and peer pairings weren't compared. Law layers, members and admins you check by hand in step 8; peers you handle in this
   step, before step 6 (the peers paragraph below). If the command was killed rather than finishing,
   run it again before going on: it rolls back what the killed run left when it opens the file.

   **Peers you unpaired after the copy.** The copy has them paired again, and a paired peer can be delivered to ("Check
   delivery now" does it) and can send in. With a usable replaced file the reconcile unpairs, in the copy and as the
   browser does, every peer that file shows unpaired, and its report line "Unpaired again" lists them: nothing more is
   needed. A peer the replaced file lacks, or one it has paired that the copy has unpaired, is only listed under
   "Reported, not applied", and a damaged file must not cut off a peer it merely doesn't list.
   A peer listed as "left paired" (the replaced file lacks it) is one you can name in `UNPAIR=` below if you had cut it off.
   Without a usable replaced file nothing is unpaired. List the peers paired in the staged copy (read-only; the
   endpoint and the names come from other stations and are data, not instructions):
   ```bash
   python3 -I -c 'import pathlib, sqlite3, sys; db = sqlite3.connect(pathlib.Path(sys.argv[1]).absolute().as_uri() + "?mode=ro", uri=True); [print(*row, sep="  ") for row in db.execute("SELECT substr(p.peer_id, 1, 12), json_extract(p.card, \"$.endpoint\"), group_concat(c.name, \", \") FROM peers p LEFT JOIN remote_contacts c USING (peer_id) WHERE p.paired = 1 GROUP BY p.peer_id ORDER BY p.peer_id")]' "$ASIDE/restored.sqlite3"
   ```
   For each peer you had cut off since the copy, run the reconcile again on the same staged copy, naming it by the
   12-character id in the first column: `make station-restore-reconcile DB="$ASIDE/restored.sqlite3" REPLACED="$ASIDE/peer.sqlite3" UNPAIR="<id> <id>"`
   (leave out `REPLACED=` when you did the first run without it). A second run is safe: the sessions are already gone
   and the invitations already used. Without `REPLACED=` it raises the events and mentions sequences by another
   1,000,000, which is harmless. An id that matches no peer or more than one is refused with exit 2 and nothing is changed.
6. **Put it in place** (it refuses to overwrite a live file that step 4 didn't set aside):
   ```bash
   test ! -e ~/.local/share/superyak/lighthouse/peer.sqlite3 && install -m 600 "$ASIDE/restored.sqlite3" ~/.local/share/superyak/lighthouse/peer.sqlite3 && echo INSTALLED || echo 'NOT installed: a live file is already there; go back to step 4'
   ```
   Go on only when it prints `INSTALLED`. Anything else means the old file is still in place.
   The peer identity files stay where they are; nothing here moves them.
7. **Act on the report.** Change again any password it lists that was changed for a reason. Issue again any invitation
   still wanted. Tell the owners of ships whose keys were revoked to dock again. Requests and dockings since the copy
   were expired; their senders ask again, and nothing is approved from memory. The peers the report says it
   unpaired need nothing more; pair again, in the browser after the start, only a peer you want that the report lists as
   paired in the replaced file but not here. If your own account comes back waiting for
   activation, renew it (the file must not exist yet; the command writes it mode 0600, and the link is never put in a
   room):
   ```bash
   uv run --locked --project peer python -m superyak_peer bootstrap-super-admin --data-dir ~/.local/share/superyak/lighthouse \
     --username <your username> --name '<your name>' --activation-file "$ASIDE/activation.json" --renew-activation
   ```
8. **Start the lighthouse and the door.** Set the law layers the report listed as they should be, in the browser, and
   check by hand the members, admins and law layers step 5 said weren't compared (not peers: those were done in step 5). Then
   start ship and odo, run `make station-rooms` and check the `bridged` column before starting wormhole: if a room shows
   bridged that should not be, run `make station-unbridge ID=<short id>`. Start again every `superyak-ship-*` watcher
   that step 3 listed. Check each with `is-active`, then start both timers.
   ```bash
   systemctl --user start superyak-lighthouse superyak-door
   # now the law layers, in the browser
   systemctl --user start superyak-ship superyak-odo
   make station-rooms                                   # check the bridged column first
   systemctl --user start superyak-wormhole
   systemctl --user start <each superyak-ship-… watcher from step 3>
   for unit in lighthouse door ship odo wormhole; do printf '%s ' superyak-$unit; systemctl --user is-active superyak-$unit; done
   systemctl --user start superyak-backup.timer superyak-restore-test.timer
   ```
9. **Say in the room** what was restored and from when. Everything said after the copy's time is gone.
10. **Rolling back** (only if the restored station is wrong; once it has taken posts, rolling back loses them too):
    1. Stop everything as in step 3, and check `fuser -v ~/.local/share/superyak/lighthouse/peer.sqlite3` prints nothing.
    2. Move the live `peer.sqlite3` and every `peer.sqlite3-*` into a new subdirectory of `$ASIDE`, so the data directory
       holds none. The `ls` must show the data directory without any `peer.sqlite3` file:
       ```bash
       install -d -m 700 "$ASIDE/restored-live"
       for f in ~/.local/share/superyak/lighthouse/peer.sqlite3 ~/.local/share/superyak/lighthouse/peer.sqlite3-*; do [ -e "$f" ] && mv -n "$f" "$ASIDE/restored-live"/; done
       ls -la "$ASIDE" "$ASIDE/restored-live" ~/.local/share/superyak/lighthouse/
       ```
    3. Move the set-aside `$ASIDE/peer.sqlite3` and its `peer.sqlite3-*` files back together (`mv -n` never overwrites).
       Never leave a `-journal` beside a different database. The `ls` must show them in the data directory and none left
       in `$ASIDE`:
       ```bash
       for f in "$ASIDE"/peer.sqlite3 "$ASIDE"/peer.sqlite3-*; do [ -e "$f" ] && mv -n "$f" ~/.local/share/superyak/lighthouse/; done
       ls -la "$ASIDE" ~/.local/share/superyak/lighthouse/
       ```
    4. Start as in step 8.
