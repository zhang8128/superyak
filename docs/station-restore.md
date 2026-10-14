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

   **Peers you unpaired after the copy come back paired.** The report doesn't undo that: it lists them only as "peers
   whose pairing differs" (the first 12 characters of each peer id), because federation had withdrawn that peer's outbox
   and the copy still holds it. Don't let the restored station deliver to a peer you cut off. Find which listed peers the
   replaced file had unpaired (`paired` is 0):
   ```bash
   python3 -c "import sqlite3,sys; [print(r) for r in sqlite3.connect('file:'+sys.argv[1]+'?mode=ro', uri=True).execute('SELECT substr(peer_id,1,12), paired FROM peers')]" "$ASIDE/peer.sqlite3"
   ```
   If the replaced file won't open, go by your own record of who you cut off. Unpairing is done in the browser, so it
   is the first thing step 8 does, right after the lighthouse and the door start and before ship and odo. Confirm first
   that nothing delivers in the meantime: `grep -c -- '--sync' ~/.config/systemd/user/superyak-lighthouse.service` must
   print 0 (federation delivers only when the lighthouse runs with `--sync`). If it prints anything else, take `--sync`
   out of the unit for this start, run `systemctl --user daemon-reload`, and put it back after unpairing.
8. **Start the lighthouse and the door.** Disconnect again, in the browser, every peer
   step 7 named. Then set the law layers the report listed as they should be. Then start ship and odo, run `make station-rooms` and check the `bridged` column before starting wormhole. Check each with
   `is-active`, then start both timers.
   ```bash
   systemctl --user start superyak-lighthouse superyak-door
   # now, in the browser: disconnect again every peer step 7 named ("Disconnect peer"), then the law layers
   systemctl --user start superyak-ship superyak-odo
   make station-rooms                                   # check the bridged column first
   systemctl --user start superyak-wormhole
   for unit in lighthouse door ship odo wormhole; do printf '%s ' superyak-$unit; systemctl --user is-active superyak-$unit; done
   systemctl --user start superyak-backup.timer superyak-restore-test.timer
   ```
9. **Say in the room** what was restored and from when. Everything said after the copy's time is gone.
