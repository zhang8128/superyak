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
  members (Wormhole too, so a room you unbridged is bridged again), higher roles, old passwords, old law layers, old room briefs, peers you had unpaired, revoked grants and spent grant budgets.
  Step 5 takes back everything that only grants access (a peer's pairing included) before the copy goes live, and lists
  the rest for you.

Run every step on the Pi, from `~/superyak`, in one terminal that you keep open: the steps share `ASIDE`, the directory
step 1 makes for this restore. If the terminal closes or the Pi restarts, open a new one in `~/superyak` and set `ASIDE`
again with the line below; never run step 1 again for that. The directory names are the local time of step 1, all of
one width, so the last one listed is the newest: this restore's. Check that its name holds the date and time you ran
step 1. From step 4 on (until a rollback's 10.3) it holds `peer.sqlite3`.
```bash
ASIDE=$(ls -d ~/.local/share/superyak/backups/replaced-* | tail -n 1); ls -la "$ASIDE"
```

**A database file and its `-journal`, `-wal` and `-shm` files always move together, never alone.** SQLite applies a
journal to whatever database it finds beside it, so a journal beside a different database corrupts it. Every move
below takes the whole set, and moves nothing when the place it goes to already holds a `peer.sqlite3` file.

Between steps 3 and 8, run no `make station-*` command the steps don't give, and nothing else that opens the station's
data directory: opening it with nothing there creates a fresh, empty `peer.sqlite3`. Step 3 disables everything but
the lighthouse and the door, so if the Pi restarts mid-restore only those two start again, on whatever is in the data
directory then (between steps 4 and 6, a new, empty `peer.sqlite3`, which step 6 finds). Set `ASIDE` again and stop
everything as in step 3 before going on.

If `make station-units` has never run, the backup timers don't exist yet, and the lines in steps 3 and 8 that name
`superyak-backup` or `superyak-restore-test` print that the unit does not exist or is not loaded. Ignore that.

1. **Choose the copy and take it out of the rotation.** `ls -l ~/.local/share/superyak/backups/station/`. The names are
   UTC times (`peer-20261014T033112Z.sqlite3`). Take the newest copy from before the damage. Make the directory for this
   restore and copy the choice into it; later steps use that copy, and nothing in the rotation is needed again. Run this
   step once per restore; only a failed step 2 sends you back to it:
   ```bash
   ASIDE=~/.local/share/superyak/backups/replaced-$(date +%Y%m%d-%H%M%S)
   install -d -m 700 "$ASIDE"
   install -m 600 ~/.local/share/superyak/backups/station/<chosen copy> "$ASIDE/chosen.sqlite3"
   ```
2. **Test it:** `make station-restore-test BACKUP="$ASIDE/chosen.sqlite3"`. It must pass. If it fails, that copy is no
   good: go back to step 1 and choose the next older one. Step 1 then makes a new directory, which is fine, since nothing
   has been moved yet; the old one keeps only the failed `chosen.sqlite3`, and setting `ASIDE` again finds the new one.
3. **Stop everything.** The lines do nothing, and print why, when `ASIDE` is not set: set it again (see the top) and
   run them again. Their first line saves every project ship's watcher (`superyak-ship-…`) and every federation unit
   (`superyak-federate`, `superyak-federation-listen`) that systemd has loaded, running, crashed or stopped, in
   `$ASIDE/watchers.txt` (empty when there are none), each with whether it was enabled and whether it was running; step 8
   puts each back as it was, so a unit you had stopped stays stopped, and one that isn't installed is never named.
   Running these lines again, after a restart or from steps 6 and 10, keeps the list from the first run. The ship, odo,
   wormhole, the listed units and both timers are disabled as well as stopped, so a restart starts none of them before
   step 8 does: federate and the listener would write into a half-restored database. The lighthouse and the door stay
   enabled: step 8 starts them first anyway.
   ```bash
   if [ ! -d "$ASIDE" ]; then echo 'NOT stopped: ASIDE is not set; set it again (see the top), then run these lines again'
   else
     test -e "$ASIDE/watchers.txt" || { units=$(systemctl --user list-units --all --plain --no-legend 'superyak-ship-*' 'superyak-federat*') && for unit in $(printf '%s\n' "$units" | awk '{print $1}'); do echo "$unit enabled=$(systemctl --user is-enabled "$unit") active=$(systemctl --user is-active "$unit")"; done > "$ASIDE/watchers.new" && mv "$ASIDE/watchers.new" "$ASIDE/watchers.txt"; }; cat "$ASIDE/watchers.txt"
     systemctl --user disable --now superyak-backup.timer superyak-restore-test.timer   # a restart must not run a catch-up backup on a half-restored station
     for unit in superyak-ship superyak-odo superyak-wormhole $(awk '{print $1}' "$ASIDE/watchers.txt"); do systemctl --user disable --now "$unit"; done
     systemctl --user stop superyak-backup.service superyak-door superyak-odo superyak-wormhole superyak-ship superyak-lighthouse
     systemctl --user list-units 'superyak-*'
   fi
   ```
   Stop any unit the last list still shows as active: `systemctl --user stop <unit>`.
4. **Set the current state aside.** Move the station's database and its sidecars into `$ASIDE`, as one set. The lines
   move nothing, and print why, when `ASIDE` is not set, when `$ASIDE` already holds a `peer.sqlite3` file (step 4 ran
   before), or when a process still has the database open (`fuser -v ~/.local/share/superyak/lighthouse/peer.sqlite3*`
   shows which: stop everything again as in step 3). A `peer.sqlite3-journal` left beside the restored file would be
   applied to it and corrupt it.
   ```bash
   if [ ! -d "$ASIDE" ]; then echo 'NOT moved: ASIDE is not set; set it again (see the top)'
   elif [ -e "$ASIDE/peer.sqlite3" ] || ls -d "$ASIDE"/peer.sqlite3-* >/dev/null 2>&1; then echo 'NOT moved: $ASIDE already holds a peer.sqlite3 file, so step 4 ran before. A peer.sqlite3 file in the data directory now is a stray: see step 6, the stray case'
   elif fuser -s ~/.local/share/superyak/lighthouse/peer.sqlite3* 2>/dev/null; then echo 'NOT moved: a process has the database open; stop everything again as in step 3'
   else for f in ~/.local/share/superyak/lighthouse/peer.sqlite3 ~/.local/share/superyak/lighthouse/peer.sqlite3-*; do [ -e "$f" ] && mv -n "$f" "$ASIDE"/; done
   fi
   ls -la "$ASIDE" ~/.local/share/superyak/lighthouse/   # every peer.sqlite3 file is in $ASIDE, none in the data dir
   ```
   If it printed that step 4 ran before and the `ls` shows no `peer.sqlite3` file in the data directory, step 4 is
   done: go on. If one is there, it is a stray: deal with it in step 6's stray case before going on. If after the first
   run the `ls` shows `peer.sqlite3` in neither directory, the data directory had no database to set aside: run step 5
   without `REPLACED=`.
5. **Stage and reconcile the copy.** The first line stages a fresh copy, unless a killed reconcile left its journal
   beside the staged one; then it leaves that copy alone, and the reconcile on the next line rolls the killed run back
   before it starts.
   ```bash
   if ls -d "$ASIDE"/restored.sqlite3-* >/dev/null 2>&1; then echo 'NOT staged again: a killed reconcile left its journal; the next line rolls it back'; else install -m 600 "$ASIDE/chosen.sqlite3" "$ASIDE/restored.sqlite3"; fi
   make station-restore-reconcile DB="$ASIDE/restored.sqlite3" REPLACED="$ASIDE/peer.sqlite3"
   ```
   Leave out `REPLACED=` only when the old file won't open; then every docked ship's keys are revoked, and those
   machines dock again, and no peer is unpaired (see the peers paragraph below). It refuses a `DB=` with any name but
   `restored.sqlite3` (`peer.sqlite3` there is the set-aside original, or `DB=` and `REPLACED=` swapped;
   `chosen.sqlite3` there would be reconciled while step 6 installs `restored.sqlite3` unreconciled), a `REPLACED=` with
   any name but `peer.sqlite3` (`chosen.sqlite3` there would compare the copy with itself and take nothing back), a
   staged copy that isn't a station database, a swapped `DB=` and `REPLACED=`, the same file twice, and a hard link.
   Read its report. Go on only when it exits 0. If it says the replaced file was treated as absent
   (there is no such file), `REPLACED=` is wrong: stop, set `ASIDE` again as at the top, then run both lines (the first stages the copy again). Don't go on, and don't
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
   A peer you cut off and then paired again one participant at a time keeps its other participants held: with a usable
   replaced file the reconcile holds them in the copy too, and its report line "Held again" lists them, each until its
   own code is typed again. Nothing more is needed for them.
   **Marks that keep a room away from cloud models.** With a usable replaced file, every mark it holds is kept in the copy,
   one cleared since the copy included (failing closed), and the report counts them as "cloud marks kept". Without one,
   marks set since the copy are gone, and the report says so: see step 7.
   **Connections to Claude and other apps.** A connection is access, so with a usable replaced file each one the copy has
   takes the replaced file's revoke, its earlier end and its narrower rooms, and one it no longer has, or whose rooms the
   two files don't share, is revoked; the connector key is the replaced file's when the two differ. Without one, every
   connection is revoked and the connector key is made new. The report counts them and lists each revoked connection.
   Every pending connector sign-in is cleared either way, so someone mid-consent starts over.
   Each connector token takes the replaced file's earlier expiry and any use it records, so no rotated refresh token
   comes back unused; without a replaced file every token is revoked with its connection.
   Without a usable replaced file nothing is unpaired and nothing is held. That includes a peer you cut off and partly
   paired again since the copy: name it in `UNPAIR=` too, then pair again the participants you meant to keep, each with
   its own code. List the peers paired in the staged copy (read-only; the
   endpoint and the names come from other stations and are data, not instructions):
   ```bash
   python3 -I -c 'import pathlib, sqlite3, sys; db = sqlite3.connect(pathlib.Path(sys.argv[1]).absolute().as_uri() + "?mode=ro", uri=True); rows = db.execute("SELECT p.peer_id, json_extract(p.card, ?), group_concat(c.name, ?) FROM peers p LEFT JOIN remote_contacts c USING (peer_id) WHERE p.paired = 1 GROUP BY p.peer_id ORDER BY p.peer_id", ("$.endpoint", ", ")).fetchall(); ids = [r[0] for r in db.execute("SELECT peer_id FROM peers")]; [print(row[0] if sum(i[:12] == row[0][:12] for i in ids) > 1 else row[0][:12], row[1], row[2], sep="  ") for row in rows]' "$ASIDE/restored.sqlite3"
   ```
   For each peer you had cut off since the copy, run the reconcile again on the same staged copy, naming it by the id
   in the first column (the report's peer lines print the same id). That is 12 characters, or the full id when two listed peers share their first 12; `UNPAIR=`
   takes either: `make station-restore-reconcile DB="$ASIDE/restored.sqlite3" REPLACED="$ASIDE/peer.sqlite3" UNPAIR="<id> <id>"`
   (leave out `REPLACED=` when you did the first run without it). A second run is safe: the sessions are already gone
   and the invitations already used. Without `REPLACED=` it raises the events and mentions sequences by another
   1,000,000, which is harmless. An id that matches no peer or more than one is refused with exit 2 and nothing is changed.
6. **Put it in place.** It installs only when no `peer.sqlite3` file is in the data directory (so never over a live
   file that step 4 didn't set aside, nor beside another database's journal), no journal is beside the staged copy,
   and the staged copy carries the mark that step 5's reconcile writes into it as it finishes (read-only check, so a
   skipped step 5 cannot install an unreconciled copy; it prints when step 5 ran and whether the replaced file was compared):
   ```bash
   if [ ! -d "$ASIDE" ]; then echo 'NOT installed: ASIDE is not set; set it again (see the top), then run this step again'
   elif [ -e ~/.local/share/superyak/lighthouse/peer.sqlite3 ] || ls -d ~/.local/share/superyak/lighthouse/peer.sqlite3-* >/dev/null 2>&1; then echo 'NOT installed: a peer.sqlite3 file is already in the data directory; do not go on (read step 6)'
   elif ls -d "$ASIDE"/restored.sqlite3-* >/dev/null 2>&1; then echo 'NOT installed: a journal is beside restored.sqlite3, so a reconcile did not finish; do not go on (read step 6)'
   elif ! python3 -I -c 'import datetime, json, os, pathlib, sqlite3, sys; db = sqlite3.connect(pathlib.Path(sys.argv[1]).absolute().as_uri() + "?mode=ro", uri=True); row = db.execute("SELECT value FROM system_meta WHERE key = ?", ("restore_reconcile",)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name = ?", ("system_meta",)).fetchone() else None; mark = json.loads(row[0]) if row else None; ok = bool(mark) and mark["path"] == os.path.abspath(sys.argv[1]) and mark["at"] >= os.stat(sys.argv[2]).st_mtime; print("step 5 ran " + datetime.datetime.fromtimestamp(mark["at"], datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ") + (", replaced file compared" if mark["replaced"] else ", replaced file NOT compared") if ok else "no step 5 mark"); sys.exit(not ok)' "$ASIDE/restored.sqlite3" "$ASIDE/chosen.sqlite3" 2>/dev/null; then echo "NOT installed: step 5 hasn't run on this copy; do not go on (read step 6)"
   elif install -m 600 "$ASIDE/restored.sqlite3" ~/.local/share/superyak/lighthouse/peer.sqlite3; then echo INSTALLED
   else echo 'NOT installed: the install failed; do not go on (read step 6)'
   fi
   ```
   Go on only when it prints `INSTALLED`. If it prints `NOT installed`, do not go on, and read which case you are in:
   - **A `peer.sqlite3` file is already in the data directory, and `$ASIDE/peer.sqlite3` exists: the stray case.** Step 4
     ran, and what is in the data directory now is a new, empty database (something opened the data directory, or the
     Pi restarted), not the station. Stop everything again as in step 3, then move the stray set into a new directory
     of its own, never over `$ASIDE/peer.sqlite3`. The lines move nothing, and print why, when `$ASIDE` holds no
     `peer.sqlite3` (then this is not the stray case) or a process still has the stray open (`fuser -v` as in step 4
     shows which):
     ```bash
     STRAY="$ASIDE/stray-$(date +%Y%m%d-%H%M%S)"
     if [ ! -e "$ASIDE/peer.sqlite3" ]; then echo 'NOT moved: $ASIDE holds no peer.sqlite3, so this is not the stray case (read step 6)'
     elif fuser -s ~/.local/share/superyak/lighthouse/peer.sqlite3* 2>/dev/null; then echo 'NOT moved: a process has the stray open; stop everything again as in step 3'
     else mkdir -m 700 "$STRAY" && for f in ~/.local/share/superyak/lighthouse/peer.sqlite3 ~/.local/share/superyak/lighthouse/peer.sqlite3-*; do [ -e "$f" ] && mv -n "$f" "$STRAY"/; done; ls -la "$STRAY"
     fi
     ls -la "$ASIDE" ~/.local/share/superyak/lighthouse/   # $ASIDE still holds peer.sqlite3; no peer.sqlite3 file in the data dir
     ```
     Then, if `$ASIDE/restored.sqlite3` exists, run step 6 again. If it doesn't (step 4's note sent you here before
     step 5 ran), go on from step 5.
   - **A `peer.sqlite3` file is already in the data directory, and `$ASIDE/peer.sqlite3` does not exist:** step 4 never
     ran, or `ASIDE` is not this restore's directory (set it again as at the top). Go back to step 4.
   - **Step 5 hasn't run on this copy:** the staged copy has no mark from a finished reconcile of this very file that is
     newer than `chosen.sqlite3`, so step 5 was skipped, or its reconcile did not exit 0. Run step 5 (both lines), go on only when
     the reconcile exits 0, then run step 6 again. Nothing was installed.
   - **A journal is beside `restored.sqlite3`:** a reconcile was killed. Run step 5 again (its first line keeps the
     staged copy, and the reconcile rolls the killed run back), and the `UNPAIR=` run too if you made one; then step 6.
   - **The install failed:** its error says why. `$ASIDE/restored.sqlite3` must exist: set `ASIDE` again as at the top
     if it is not set, and run step 5 if it hasn't made the file. Then run step 6 again; if the failed install left a
     partial file in the data directory, step 6 sends you to the stray case.

   The peer identity files stay where they are; nothing here moves them. A station that holds signed records refuses to start without its identity.json; restore the file rather than delete it. If it is truly lost, `station-new-identity` (API.md, Signed records) gives the station a new key on purpose. Run it with the lighthouse stopped; add `--endpoint https://HOST:PORT` when the station federates:
   ```bash
   uv run --locked --project peer python -m superyak_peer station-new-identity --data-dir ~/.local/share/superyak/lighthouse
   ```
7. **Act on the report.** Change again any password it lists that was changed for a reason. Read each room brief it lists
   ("room briefs that differ"; the report never shows brief text) in the browser, and save again the one you want. Issue again any invitation
   still wanted. Tell the owners of ships whose keys were revoked to dock again. Ask the issuers of the grants the report lists as missing from the replaced file, or revoked with no usable replaced file, to make again any still wanted; a grant made after the copy is gone too. Requests and dockings since the copy
   were expired; their senders ask again, and nothing is approved from memory. If the report says marks set since the
   copy were not kept, ask the members of the rooms that matter to check their "never to a cloud model" marks in the
   browser before any ship is added to those rooms. Tell the people whose connections the report lists as revoked to
   connect again from their app if they still want it; a connection made after the copy is gone too. The peers the report says it
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
   enable and start ship and odo, run `make station-rooms` and check the `bridged` column before enabling and starting
   wormhole: if a room shows bridged that should not be, run `make station-unbridge ID=<short id>`. Put the units
   step 3 saved, the watchers and the federation units, back as they were, after the lighthouse: enable again those that
   were enabled, and start again those that were running (a crashed one restarting counts as running). Check each
   started unit with `is-active`, then enable both timers again. A pull peer's deliveries resume about 5 minutes after
   step 5's reconcile: until then the listener answers its pulls "Replay", counts no failure and keeps its acks, so a
   copy's lost pull nonces can't be replayed (fix:restore-keeps-pull-nonces).
   ```bash
   systemctl --user start superyak-lighthouse superyak-door
   # now the law layers, in the browser
   for unit in superyak-ship superyak-odo; do systemctl --user enable --now "$unit"; done
   make station-rooms                                   # check the bridged column first
   systemctl --user enable --now superyak-wormhole
   for unit in $(awk '$2 == "enabled=enabled" {print $1}' "$ASIDE/watchers.txt"); do systemctl --user enable "$unit"; done   # the watchers step 3 saved as enabled
   for unit in $(awk '$3 ~ /^active=(active|activating|reloading)$/ {print $1}' "$ASIDE/watchers.txt"); do systemctl --user start "$unit"; done   # and those it saved as running
   for unit in superyak-lighthouse superyak-door superyak-ship superyak-odo superyak-wormhole $(awk '$3 ~ /^active=(active|activating|reloading)$/ {print $1}' "$ASIDE/watchers.txt"); do printf '%s ' "$unit"; systemctl --user is-active "$unit"; done
   systemctl --user enable --now superyak-backup.timer superyak-restore-test.timer   # as make station-units does
   ```
9. **Say in the room** what was restored and from when. Everything said after the copy's time is gone.
10. **Rolling back** (only if the restored station is wrong; once it has taken posts, rolling back loses them too):
    1. Stop everything: set `ASIDE` again if the terminal closed (see the top), and run step 3's lines again. Its first
       line keeps the watchers list from step 3's first run.
    2. Move the live database and its sidecars, as one set, into `$ASIDE/restored-live`. The lines move nothing, and
       print why, when `ASIDE` is not set, when `restored-live` already holds a `peer.sqlite3` file (10.2 ran before),
       or when a process still has the database open (stop everything again). The `ls` must show the data directory
       without any `peer.sqlite3` file:
       ```bash
       if [ ! -d "$ASIDE" ]; then echo 'NOT moved: ASIDE is not set; set it again (see the top)'
       elif [ -e "$ASIDE/restored-live/peer.sqlite3" ] || ls -d "$ASIDE"/restored-live/peer.sqlite3-* >/dev/null 2>&1; then echo 'NOT moved: $ASIDE/restored-live already holds a peer.sqlite3 file, so 10.2 ran before (read 10.2)'
       elif fuser -s ~/.local/share/superyak/lighthouse/peer.sqlite3* 2>/dev/null; then echo 'NOT moved: a process has the database open; stop everything again as in step 3'
       else install -d -m 700 "$ASIDE/restored-live" && for f in ~/.local/share/superyak/lighthouse/peer.sqlite3 ~/.local/share/superyak/lighthouse/peer.sqlite3-*; do [ -e "$f" ] && mv -n "$f" "$ASIDE/restored-live"/; done
       fi
       ls -la "$ASIDE" "$ASIDE/restored-live" ~/.local/share/superyak/lighthouse/
       ```
       If it says 10.2 ran before and `$ASIDE/peer.sqlite3` still exists, any `peer.sqlite3` file now in the data
       directory is a stray: set it aside with step 6's stray-case lines, then go on with 10.3. If `$ASIDE/peer.sqlite3`
       is gone, 10.3 has run: go on with 10.4.
    3. Move the set-aside `$ASIDE/peer.sqlite3` and its sidecars back, as one set. The lines move nothing, and print
       why, when `$ASIDE` holds no `peer.sqlite3` (10.3 ran before, or `ASIDE` is not this restore's directory) or a
       `peer.sqlite3` file is in the data directory. The `ls` must show them in the data directory and none left in
       `$ASIDE`:
       ```bash
       if [ ! -e "$ASIDE/peer.sqlite3" ]; then echo 'NOT moved: $ASIDE holds no peer.sqlite3 (read 10.3)'
       elif [ -e ~/.local/share/superyak/lighthouse/peer.sqlite3 ] || ls -d ~/.local/share/superyak/lighthouse/peer.sqlite3-* >/dev/null 2>&1; then echo 'NOT moved: a peer.sqlite3 file is in the data directory (read 10.3)'
       else for f in "$ASIDE"/peer.sqlite3 "$ASIDE"/peer.sqlite3-*; do [ -e "$f" ] && mv -n "$f" ~/.local/share/superyak/lighthouse/; done
       fi
       ls -la "$ASIDE" ~/.local/share/superyak/lighthouse/
       ```
       If a `peer.sqlite3` file is in the data directory: when 10.2 ran, it is a stray, so set it aside with step 6's
       stray-case lines and run 10.3 again; when 10.2 didn't run, run 10.2 first.
    4. Run step 8's commands, in its order. They start the lighthouse and the door, enable and start the ship, odo and
       wormhole, put the watchers step 3 saved back as they were, and enable the timers again. Step 8's checks that act
       on step 5's report (the law layers, the members and admins, the `bridged` column) are for a restored copy and
       don't apply to a rollback. If a federation unit was running, note the time 10.1 stopped it, and start it again
       more than 10 minutes after that: the file put back lacks the pull nonces the restored station recorded and
       carries no newer restore mark, and a pull it served just before the stop, from a peer whose clock ran 300 s
       ahead, could pass the clock check for 10 minutes after the stop (fix:restore-keeps-pull-nonces). The lighthouse,
       the door, the ships and the timers needn't wait. Until `fix:pull-floor-after-rollback` writes a mark at 10.3,
       this wait is the guard.
