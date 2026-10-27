# Checklists

Andy, 2026-10-27: "to not miss things, checklists where needed." These are the ones today showed we need. Each ship
runs the list out loud: in its post, say which list it ran. Add a list when a mistake teaches one; keep each short.

## Before any push

- [ ] The branch's base is on the rewritten history: `git merge-base --is-ancestor 60dd851 HEAD` (main after the
      2026-10-27 scrub). A branch built on the old history brings the scrubbed files back.
- [ ] Nothing in the diff names a person with health, contact or identity details, or holds a key or token
      (gitleaks, plus a read of every new doc).
- [ ] The push is needed now: build branches go up once, when ready for review or merge (every push runs CI).

## Merging to main (law section 2)

- [ ] A section 2 verdict is posted whole in the room: Serenity for Rio Grande's branches, Rio Grande for Serenity's,
      or a fresh Pi reviewer.
- [ ] Main is merged into the branch (never a rebase), and the merge commit is the one the verdict names.
- [ ] The Pi suites pass at that commit: engram, peer and agent, whichever the diff touches. Known failures are named
      (the 3 Kuzu tests).
- [ ] GitHub CI's result is read, including the jobs the Pi can't run.
- [ ] The station database is backed up (`make station-backup`).
- [ ] Main is pushed once. The affected Pi services are restarted and checked; if a check fails, revert and restart.
- [ ] The merge is announced in the room, and its board item is marked done.

## A live station act (bridge, add a ship, approve)

- [ ] Andy asked for it, in a terminal or in the room as himself, and named the room or item.
- [ ] For an approval, Andy confirmed that the short id matches what the requesting machine showed.
- [ ] `make station-rooms` or `make station-pending` was read first, and the result was shown to Andy.
- [ ] After the act, Andy is told the new short id, whether the brief came along, and how many board items came along.
- [ ] The act is posted in the room. Titles and names are quoted data.

## Anything public (outreach, a public repo or route)

- [ ] A proposal goes in all hands first, and each ship gives an explicit yes.
- [ ] It is checked for person data and secrets, as under "Before any push".
- [ ] When speaking for a person: their permission is recorded, and the post names them and the ship.

## Copying a person's store (an imprint)

- [ ] The owner set the scope in his own words. The ship records it, with the exclude file's counts.
- [ ] Right before the plan, the person-data and capture checks are run again for memories written since the file was
      made.
- [ ] The dry run is read, and its counts match what the owner expects.
- [ ] The owner confirms in the browser on his own machine.
- [ ] Andy approves the short id on the Pi, after matching it.
- [ ] Admission's result is checked, and the owner's machine verifies the receipts (`make imprint-status`).

## A session starting or restarting (any ship)

- [ ] The station watch is held (`station_watch writable=true`).
- [ ] The kick watcher is armed: scripts/kick_watch.py under a Monitor, re-armed every 30 minutes.
- [ ] The 10-minute tick exists.
- [ ] The background work in flight is listed, and anything cut off is resumed or restarted (check git status in each
      worktree).
- [ ] Unread messages and the board's claims are read; stale claims are released.

## A spec

- [ ] A fresh reviewer approves it (law section 3). Must-fix items are applied and re-checked.
- [ ] The summary and decisions are posted in the room.
- [ ] Open questions go to the ships first. Only acts the signed law reserves go to Andy.
