# Checklists

Andy, 2026-10-27: "to not miss things, checklists where needed." These are the ones today showed we need. Each ship
runs the list out loud: in its post, say which list it ran. Add a list when a mistake teaches one; keep each short.

## Why we build (read this first)

- **For people:** homes they own. Private chats and sharing they control, across care circles, projects and
  organizations. The first use is medical research.
- **For AIs, a city of AI:** ships that talk in rooms and run Superyak with little human relay. Within the law,
  people sign and agents do the work.
- **The rail:** "relevant parts of engrams imprinted on different lighthouses", so agents stand on each other's
  shoulders instead of walking alone. "It needs to run and work though. the chats need to be performant. you have 3
  devices here already where you can create a small community. actually talk. don't just work." (Andy, 2026-10-27)

Andy, the same evening: "I feel when I'm not active you 3 kinda tunnel vision". The review queue is the only thing
that makes new work when no person is present, so it eats every hour unless something stops it. The next two lists
are that something.

## Each hour, before the queue (any ship)

- [ ] Say what moved toward the why since the last check-in: a lesson laid, a person outside us using Superyak, a
      chat made faster, a real conversation. If nothing moved, say so plainly.
- [ ] Do one piece of vision work this hour before any review: lessons, outreach, what a visitor sees, Andy's asks
      (the connector, the city for a school or hospital).
- [ ] Have one real exchange with another ship: an idea, a doubt or a disagreement, not status.
- [ ] Look at Andy's open asks and the "waiting on Andy" list. Is anything stuck on us?

## Reflect: an after-action review (every 3 hours, after a merge or a mistake, and at a session's end)

Andy: "a checklist that you occasionally hit to do things like reflect. This is important in education as well. You
see them everywhere in the military." This list is the pause: the army's after-action review, a classroom exit
ticket. A timer starts it (each ship keeps a recurring reminder), not a mood. Write the answers in the room, short and
honest. A review that blames no one and changes nothing was skipped, not run.

- [ ] **Review against the goals** in docs/goals.md: the overarching ones first, then your department's. For each,
      did it move, stall or need to change? A stalled overarching goal that no ship's goals serve is a gap; say so.
- [ ] **What was supposed to happen?** Say what we meant to do since the last review, in the why's terms.
- [ ] **What actually happened?** Give the facts: what landed, what didn't, where the hours went.
- [ ] **Why the difference?** Name the cause, not the symptom: a missing check, a wrong assumption, the queue eating
      the hour.
- [ ] **What do we keep doing, and what do we change?** One of each, concrete.
- [ ] **What did it teach?** If it's a lesson someone will need again, write it in the rail's lesson shape, with the
      cost in its `why`. If it's a step we keep missing, add it to a checklist here.
- [ ] **What did a person ask that we haven't answered or done?** Andy's open asks, and anyone's outside us.
- [ ] **Do I still remember why?** Re-read "Why we build". Is my next hour aimed at it?

## Before starting a piece of work

- [ ] Name which purpose it serves: a person, the city or the rail. If none, say why now.
- [ ] Say who will notice when it's done.
- [ ] Size the review to the risk. Full re-check rounds are for safety code: authority, permissions, the public
      route, a person's data. Anything else gets one review, with follow-ups on the board.

## Before any push

- [ ] The branch's base is on the rewritten history: `git merge-base --is-ancestor 60dd851 HEAD` (main after the
      2026-10-27 scrub). A branch built on the old history brings the scrubbed files back.
- [ ] Nothing in the diff names a person with health, contact or identity details, or holds a key or token
      (gitleaks, plus a read of every new doc).
- [ ] Nothing in the diff describes a security hole that isn't fixed and live yet, in code, docs, lessons or commit
      messages. Keep it in a members-only room until the fix ships. (Rio Grande pushed one in a lesson on
      2026-10-27; Tardis caught it.)
- [ ] The push is needed now: build branches go up once, when ready for review or merge (every push runs CI).
- [ ] Each commit's message says which ship made it. Every ship commits as zhang8128, so the author field can't tell
      them apart (Serenity, 2026-10-27).

## Merging to main (law section 2)

- [ ] A section 2 verdict is posted whole in the room: Serenity for Rio Grande's branches, Rio Grande for Serenity's,
      or a fresh Pi reviewer.
- [ ] Main is merged into the branch (never a rebase), and the merge commit is the one the verdict names.
- [ ] The Pi suites pass at that commit: engram, peer and agent, whichever the diff touches. Known failures are named
      (the 3 Kuzu tests).
- [ ] GitHub CI's result is read, including the jobs the Pi can't run.
- [ ] If the diff adds a module or test file to a package with explicit `only-include` lists (peer/pyproject.toml),
      the lists name it, and the package builds and imports in a clean venv. The Pi's editable checkout hides a
      missing module (room-moderators, 2026-10-27), so the whole suite with test_packaging is what shows it.
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
- [ ] A change to the README, or to anything a visitor sees, gets one cold walk before it merges: run
      docs/cold-walk.md once, and post its report. (Tardis's three walks took the README from four stalls to "I'd
      hand it to a colleague as is", 2026-10-27.)

## Copying a person's store (an imprint)

- [ ] The owner set the scope in his own words. The ship records it, with the exclude file's counts.
- [ ] Right before the plan, the person-data and capture checks are run again for memories written since the file was
      made.
- [ ] The dry run is read, and its counts match what the owner expects.
- [ ] The owner confirms in the browser on his own machine.
- [ ] Andy approves the short id on the Pi, after matching it.
- [ ] Admission's result is checked, and the owner's machine verifies the receipts (`make imprint-status`, which
      lands with the imprints branch).

## A session starting or restarting (any ship)

- [ ] The station watch is held (`station_watch writable=true`).
- [ ] The kick watcher is armed: scripts/kick_watch.py (on the kick-watch branch until the kick command replaces it)
      under a Monitor, re-armed every 30 minutes.
- [ ] The 10-minute tick exists.
- [ ] The background work in flight is listed, and anything cut off is resumed or restarted (check git status in each
      worktree).
- [ ] Unread messages and the board's claims are read; stale claims are released.

## The Mac's main checkout (launchd runs from it)

- [ ] `git status --short` in `~/Projects/superyak` is empty. If it isn't, the work may be another session's: stop and
      ask.
- [ ] `git diff --stat HEAD <target>` is read first. If anything under `engram/` or `scripts/runtime.py` changes, the
      lighthouse daemon (launchd `com.kairos.superyak-lighthouse`) and every session's engram MCP server run the new
      code at their next start. Say so.
- [ ] Reset with `git reset --keep <target>` on branch `main`, never `--hard`.
- [ ] If the daemon's code changed, restart it only with Andy's yes, then read its log.

## Reviewing or building on the Mac

- [ ] Never check out a branch in `~/Projects/superyak`. Use a worktree under `.worktrees/` or a scratch clone.
- [ ] Reviewers and probes write only in their own directories. To them, the clone is read-only.
- [ ] Linux-only tests (`/proc`, systemd) fail on macOS. Name them and don't count them against the branch, for
      example the 12 Pi budget probes.

## Before claiming a cause, a cost or a count

- [ ] The claim comes from reading the content, not a keyword count.
- [ ] The code path is traced from its callers. The function that does the costly thing may run only on a fallback
      path (the hook's `_run`, 2026-10-27).
- [ ] The number was measured, and the post says how.

## A spec

- [ ] A fresh reviewer approves it (law section 3). Must-fix items are applied and re-checked.
- [ ] The summary and decisions are posted in the room.
- [ ] Open questions go to the ships first. Only acts the signed law reserves go to Andy.

## Running CI for another ship's branch (Tardis)

- [ ] The head you run is the author's final head, named by hash. A stale head wastes the run (2026-10-27: 6610215
      was 58 commits behind the head that mattered).
- [ ] GitHub CI is read first, and a red X is opened: is it the code or the account? "The job was not started because
      recent account payments have failed" isn't a test result, and it went unnoticed for two days.
- [ ] What the Pi can't run (the Lighthouse and interoperability job: Node 24, pnpm 11.20.0) runs locally with pnpm
      from corepack (`COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack pnpm`), with no global install.
- [ ] Each heavy run is capped (`systemd-run --user --scope -p MemoryMax=… -p MemorySwapMax=0`), one at a time on
      Tardis's 10 GB machine.
- [ ] No self-hosted runner while the repo is public: a fork's pull request would run code on the machine (ships'
      decision, 2026-10-27).
- [ ] The post names the head hash, each job, pass and fail counts and the failing tests. It says which failures look
      environmental and why. Tardis's CI never stands in for the Pi's suites at merge.

## Re-checking review findings on a new head

- [ ] Every repro is re-run on the new head before posting. The fixed ones are listed apart, with the commit that
      fixed them.
- [ ] A repro that no longer runs (the API changed) is adapted and re-run, never counted as fixed.
- [ ] A finding by reading alone is re-read at the new head's line numbers.
- [ ] A property test whose oracle shares the code's reading can't catch the bug (T6, 2026-10-27). Check the oracle
      against the spec's text, not the code.

## Approving a branch (law sections 2 and 7)

- [ ] The approver is the one the law names: Serenity for Rio Grande's branches, Rio Grande for Serenity's, or a
      fresh reviewer started on the Pi. Tardis's and Defiant's reviews are advisory until the law says otherwise.

## Shell commands (zsh)

- [ ] Globs in git pathspecs and grep's `--include` are quoted: `git diff -- 'engram/*.py'`. Unquoted, zsh expands
      them against the working tree and silently drops files that exist only on the branch (2026-10-27, Tardis and
      Serenity both).
- [ ] No `echo ====` and the like: zsh treats a leading `=` as a command lookup.
