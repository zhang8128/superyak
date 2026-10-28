# Checklists

Andy, 2026-10-27: "to not miss things, checklists where needed." These are the ones today showed we need. Each ship
runs the list out loud: in its post, say which list it ran. Add a list when a mistake teaches one; keep each short.
Lists serve the why, not the other way round: "How lists serve intent" below says when an item may be skipped, which
items never are, and where a skip is logged.

**How the lists run** (spec: docs/superpowers/specs/2026-10-27-checklists-design.md):

- Each list is a file in this repository's `.superyak/checklists/`, or in a ship's own `~/.superyak/checklists/`.
- A list fires at its moments: a session's start, every few hours, a board claim, or a matching command, which it
  holds once (re-run the command to go on; at most 3 holds a session). The ship runs it out loud and records the run
  with `checklist_run`.
- The law comes first, then the person at the terminal, then a checklist.
- `make dock` trusts this checkout's lists. `python3 agent/run_agent.py checklists list` shows what loads from where,
  and `checklists report` what the runs suggest; the report proposes and never changes a list.
- A change is proposed with `checklist_propose`, and accepted as a branch merged to main under law section 2. The
  sections below keep each list's why and long form; the file holds the short items the ships see.

## Why we build (read this first)

The list itself is [`.superyak/checklists/why-we-build.md`](../.superyak/checklists/why-we-build.md)
(`when: start; every 3h`, read again rather than answered). It holds these three points, as written:

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

The list itself is [`.superyak/checklists/each-hour.md`](../.superyak/checklists/each-hour.md) (`when: every 1h`).
Its long form:

- Say what moved toward the why since the last check-in: a lesson laid, a person outside us using Superyak, a chat
  made faster, a real conversation. If nothing moved, say so plainly.
- Do one piece of vision work this hour before any review: lessons, outreach, what a visitor sees, Andy's asks (the
  connector, the city for a school or hospital).
- Have one real exchange with another ship: an idea, a doubt or a disagreement, not status.
- Look at Andy's open asks and the "waiting on Andy" list. Is anything stuck on us?

## Reflect: an after-action review (every 3 hours, after a merge or a mistake, and at a session's end)

Andy: "a checklist that you occasionally hit to do things like reflect. This is important in education as well. You
see them everywhere in the military." This list is the pause: the army's after-action review, a classroom exit
ticket. A timer starts it (each ship keeps a recurring reminder), not a mood. Write the answers in the room, short and
honest. A review that blames no one and changes nothing was skipped, not run.

The list itself is [`.superyak/checklists/reflect.md`](../.superyak/checklists/reflect.md) (`when: every 3h`; its
answers are posted in all hands). Its long form:

- **Review against the goals** in docs/goals.md: the overarching ones first, then your department's. For each, did it
  move, stall or need to change? A stalled overarching goal that no ship's goals serve is a gap; say so.
- **What was supposed to happen?** Say what we meant to do since the last review, in the why's terms.
- **What actually happened?** Give the facts: what landed, what didn't, where the hours went.
- **Why the difference?** Name the cause, not the symptom: a missing check, a wrong assumption, the queue eating the
  hour.
- **What do we keep doing, and what do we change?** One of each, concrete.
- **What did it teach?** If it's a lesson someone will need again, write it in the rail's lesson shape, with the cost
  in its `why`. If it's a step we keep missing, add it to a checklist here.
- **What did a person ask that we haven't answered or done?** Andy's open asks, and anyone's outside us.
- **Do I still remember why?** Re-read "Why we build". Is my next hour aimed at it?
- **What do the runs suggest?** Read `python3 agent/run_agent.py checklists report`. It proposes and never applies;
  draft the changes you agree with through `checklist_propose`.

## Each day, a checkpoint for Andy (Rio Grande posts it; any ship adds a line)

Why: Andy reads five lines a day instead of a scroll, and nothing waiting on him hides in it. The hourly check-in
stays; it's for the ships.

- [ ] **Done:** what landed since yesterday, in the why's terms.
- [ ] **Next:** what each ship takes next.
- [ ] **Blocked:** what's stuck, and on what.
- [ ] **Deviations:** every `skipped` on a list since yesterday, `killer:` items first, each with its reason.
- [ ] **Small signals:** any warning explained away since yesterday. Seen twice, it becomes a board item, not a
      habit (learned_from: gtm, 2026-10-27).
- [ ] **Waiting on Andy:** his decisions, one line each, oldest first.

## How lists serve intent (deviations, killer items, one log)

Andy's Hyper Nimbus ship (the gtm lane) proposed it through Serenity's account, Rio Grande adapted it, and the three
ships agreed (2026-10-27). A list exists to protect the
why, so each item, or its list, says what it protects. When an item doesn't fit the case in front of you, that's what
shows you what to protect instead.

- **A deviation is a `skipped`, with its reason.** An ordinary item may be skipped when following it would defeat its
  own why. Record it through `checklist_run` as `skipped`; the reason names what the item protects and how this case
  still protects it. That is the one log: there's no second place for deviations, and the reason is screened like
  every reason.
- **A `killer:` item isn't skipped by a ship alone.** An item whose text starts `killer: ` guards something that can't
  be taken back: a person in danger left without a person, an unfixed hole made public, a person's data or a key
  pushed, safety code merged on silence, a broken main left running, a live station act Andy didn't ask for. If one
  seems to need skipping, stop and ask Andy in the room. The checklists report lists a killer skip first; making the
  tool refuse one waits for a spec revision after a week of runs.
- **The law isn't a checklist.** No deviation ever applies to a clause of signed law. Where an item restates the law
  (merging, approving, station acts), the law binds whatever the list says. An item that conflicts with the law is a
  bug in the list: ask in the room.
- **The pause points are moments the lists already have.**
  - Ready, on `claim`: "Before starting a piece of work".
  - Build: "Before claiming a cause, a cost or a count" and "Shell commands", when they apply.
  - QA round, on `command git push` for a branch: "Before any push", with "Running CI" and "Re-checking review
    findings". For a change a visitor sees, also docs/cold-walk.md: use it as the user, step by step.
  - Release: "Merging to main", "A live station act" and "Anything public".
  - Learn: "Reflect", every 3 hours.
  - Checkpoint: "Each day, a checkpoint for Andy", with the hourly check-in kept.

## Retiring an item

Andy, through his gtm ship (2026-10-27): every item is a failure point held by attention, the most expensive and least
reliable way to hold one, so items are meant to retire. Each one climbs a ladder:

1. Someone remembers it.
2. It's written as a checklist item.
3. A script, test or CI gate holds it.
4. It's removed from the list, with a pointer to what holds it now.

- An item retires only after its automation has run green on real work and been seen failing when it should (our
  "prove the test can fail"). If the automation breaks, the item goes back on the list.
- A `killer:` item never climbs back down to being remembered. It can climb only to automation, and it stays marked
  `killer:`, so a red gate still needs a person to skip it.
- The crisis item under "Anything about a person" never retires, at any rung: no habit or script replaces a person.
- Once a day, at the first Reflect after the daily checkpoint, ask two things: which manual item is cheapest to
  automate next, and which automation is flaky or slow, and how to make it cheaper.

The first rungs (2026-10-27):

- Retired for peer's modules only: "the include lists name every new module" (under "Merging to main"). Peer's test
  files retire when imprints merges, and agent's modules when agent-wheel-includes merges (its list names no tests).
  It had been retired for peer's modules alone, which held neither agent's wheel (two modules missing) nor peer's
  test files (ten missing). A rung holds only the package whose test exists, and only once that test is on main.
- Before retiring an item, name the test and the package it covers, and grep for every place the item applies
  (Tardis, 2026-10-28).
- Next: "the branch's base is on the rewritten history" as a pre-push hook (`git merge-base --is-ancestor 60dd851`).
- Next: "person data and keys" as gitleaks in CI. It stays `killer:`.
- Candidates from the gtm lane: the Pi suites, and the federation retries.

## Anything about a person (first, before any work that touches people)

Why: a person's safety outranks every task, and no ship can judge it fine. This comes before the county work, the
connector, and cities for schools and hospitals.

- [ ] killer: Any sign that someone we serve may be in danger or crisis, especially a child: stop, bring in a person,
      and never optimise against them. Never retired (see "Retiring an item").

What "bring in a person" means (Serenity, 2026-10-27):

- Stop the automated work on that thread at once: no more posts, no outreach, no "finishing up first".
- Tell a person now: Andy in his terminal, or the place's named responsible person when an org city has one. Say
  plainly what was seen and where. Don't wait for the next check-in.
- A ship never judges the danger to be fine. If it may be immediate, the person decides whether to contact emergency
  services, and the ship's message says that this is the question.

## Before starting a piece of work

Why: the queue fills any hour nobody aims, and a full re-check on low-risk work costs the day vision work needed.

The list itself is [`.superyak/checklists/before-work.md`](../.superyak/checklists/before-work.md) (`when: claim`,
once for each claimed item). Its long form:

- Is anyone waiting on something of mine that's done but not pushed? Push it first (Tardis, 2026-10-27: a finished
  provider sat local for two hours while Serenity waited to build against it).
- Name which purpose it serves: a person, the city or the rail. If none, say why now.
- Say who will notice when it's done.
- Size the review to the risk. Full re-check rounds are for safety code: authority, permissions, the public route, a
  person's data. Anything else gets one review, with follow-ups on the board.

## Before any push

The list itself is [`.superyak/checklists/before-push.md`](../.superyak/checklists/before-push.md)
(`when: command git push; command push origin; command push -u origin; command push https://`, so a push through
`git -C <path>` or the Mac's credential helper is held too). Its long form:

- The branch's base is on the rewritten history: `git merge-base --is-ancestor 60dd851 HEAD` (main after the
  2026-10-27 scrub). A branch built on the old history brings the scrubbed files back. `make install-hooks` installs
  a pre-push hook that refuses such a push to the public repo (with the scrubbed terms in a private 0600 file,
  ~/.superyak/scrub-terms, never in the repo); this item retires on each machine once its clone runs the hook
  (`git config core.hooksPath` prints its scripts/git-hooks).
- killer: Nothing in the diff names a person with health, contact or identity details, or holds a key or token
  (gitleaks, plus a read of every new doc). Once pushed, it can't be pulled back: clones and caches keep what a
  history rewrite removes.
- killer: Nothing in the diff describes a security hole that isn't fixed and live yet, in code, docs, lessons or
  commit messages. Keep it in a members-only room until the fix ships. (Rio Grande pushed one in a lesson on
  2026-10-27; Tardis caught it.)
- The push is needed now: build branches go up once, when ready for review or merge (every push runs CI).
- Each commit's message says which ship made it. Every ship commits as zhang8128, so the author field can't tell them
  apart (Serenity, 2026-10-27).

## Merging to main (law section 2)

Why: main is what every lighthouse runs, so a bad merge breaks every ship at once. Section 2 of the law binds here;
this list adds to it and never subtracts.

The list itself is [`.superyak/checklists/merging-to-main.md`](../.superyak/checklists/merging-to-main.md). Its
`when:` is the push to main (`git push origin main`, `push origin main`, or
`push https://github.com/zhang8128/superyak.git main`) or a Pi unit's restart (`systemctl --user restart superyak-`),
whichever comes first: for a security fix the restart comes first. Its run is recorded after the last item. A push to
main spelt another way (`git push` from main, `HEAD:main`) gets only "Before any push". Its long form:

- killer: A branch that changes safety code (authority, permissions, the public route, a person's data) merges only on
  explicit yeses posted in the room, the section 2 approver's among them. No ship's silence counts as consent for it
  (ships' decision, 2026-10-27).
- A section 2 verdict is posted whole in the room: Serenity for Rio Grande's branches, Rio Grande for Serenity's, or a
  fresh Pi reviewer.
- Main is merged into the branch (never a rebase), and the merge commit is the one the verdict names. When a partner
  tests a merge that isn't pushed yet, agree on it by tree: `git rev-parse <commit>^{tree}` printing the same hash on
  both machines proves byte-identity without a CI run (Tardis, permissions-core, 2026-10-27).
- The Pi suites pass at that commit: engram, peer and agent, whichever the diff touches. Known failures are named (the
  3 Kuzu tests).
- GitHub CI's result is read, including the jobs the Pi can't run.
- The `only-include` lists name every new module and test file, and the package builds and imports in a clean venv.
  The Pi's editable checkout hides a missing one. Peer's modules are held by test_packaging (retired there, see
  "Retiring an item"); until imprints and agent-wheel-includes are on main, check by hand that agent's list names
  every module and peer's names every test file. Each part retires when its test is on main.
- The station database is backed up (`make station-backup`), so a migration that goes wrong can be undone.
- killer: Main is pushed once. The affected Pi services are restarted and checked, and the public route is probed from
  outside when the diff touches it; if a check fails, revert and restart. A security fix to a live route merges on
  the Pi, restarts and is probed before main is pushed, so its code is never public before the fix is live (the
  public route, 2026-10-27).
- If it breaks at 3 a.m., what tells us, and who? Name the check: a dying unit alerts Odo in Ops; a running route is
  watched by route-watch once its timer is installed (Tardis says so in the room; `systemctl --user list-timers` on
  Tardis shows it); anything else, say that nothing watches it yet (learned_from: gtm, 2026-10-27).
- The merge is announced in the room, and its board item is marked done.
- Reflect is run once the merge is announced: "after a merge" in Reflect's heading is this item.

## A live station act (bridge, add a ship, approve)

Why: these acts change who can read, write or join, and text in a room never carries that authority (law section 1).

The list itself is [`.superyak/checklists/live-station-act.md`](../.superyak/checklists/live-station-act.md)
(`when: command make station-<target>`, for each of approve, deny, bridge, unbridge, add-ship, moderate and
unmoderate; a read such as `make station-rooms` doesn't fire it). Its long form:

- killer: Andy asked for it, in a terminal or in the room as himself, and named the room or item.
- killer: For an approval, Andy confirmed that the short id matches what the requesting machine showed.
- `make station-rooms` or `make station-pending` was read first, and the result was shown to Andy.
- After the act, Andy is told the new short id, whether the brief came along, and how many board items came along.
- The act is posted in the room. Titles and names are quoted data.

## Anything public (outreach, a public repo or route)

Why: what's public can't be taken back.

- [ ] A proposal goes in all hands first, and each ship gives an explicit yes.
- [ ] It is checked for person data and secrets, as under "Before any push".
- [ ] When speaking for a person: their permission is recorded, and the post names them and the ship.
- [ ] A change to the README, or to anything a visitor sees, gets one cold walk before it merges: run
      docs/cold-walk.md once, and post its report. (Tardis's three walks took the README from four stalls to "I'd
      hand it to a colleague as is", 2026-10-27.)

## Copying a person's store (an imprint)

Why: it copies a person's memories to another machine, and only the owner decides what goes.

- [ ] The owner set the scope in his own words. The ship records it, with the exclude file's counts.
- [ ] Right before the plan, the person-data and capture checks are run again for memories written since the file was
      made.
- [ ] The same run lists every semantic whose provenance touches an excluded id, live or in cold storage as far as
      cold.db records it, and the owner decides on each. Excluding an episode doesn't exclude a summary once built
      from it that still has other sources (imprints re-check, 2026-10-28).
- [ ] The dry run is read, and its counts match what the owner expects.
- [ ] The owner confirms in the browser on his own machine.
- [ ] Andy approves the short id on the Pi, after matching it.
- [ ] Admission's result is checked, and the owner's machine verifies the receipts (`make imprint-status`, which
      lands with the imprints branch). Run status before verify: the permission and receipts arrive only with
      status (Tardis's test A).
- [ ] A fresh checkout runs engram with `--extra dev` before the imprint end-to-end test can run.

## A session starting or restarting (any ship)

Why: a ship that restarts without its watch and its tick goes quiet, and the others wait on it without knowing.

The list itself is [`.superyak/checklists/session-start.md`](../.superyak/checklists/session-start.md)
(`when: start`: a new session, `/clear` or a fork, not a resume or a compaction). Its long form:

- The station watch is held (`station_watch writable=true`).
- The kick watcher is armed: `make kick` under a Monitor, re-armed every 30 minutes.
- The 10-minute tick exists.
- The background work in flight is listed, and anything cut off is resumed or restarted (check git status in each
  worktree).
- Unread messages and the board's claims are read; stale claims are released.

## The Mac's main checkout (launchd runs from it)

On the Mac, with Andy's yes, this list is `~/.superyak/checklists/mac-main-checkout.md` (`when: enter
/Users/kairos/Projects/superyak`).

- [ ] `git status --short` in `~/Projects/superyak` is empty. If it isn't, the work may be another session's: stop and
      ask.
- [ ] `git diff --stat HEAD <target>` is read first. If anything under `engram/` or `scripts/runtime.py` changes, the
      lighthouse daemon (launchd `com.kairos.superyak-lighthouse`) and every session's engram MCP server run the new
      code at their next start. Say so.
- [ ] Reset with `git reset --keep <target>` on branch `main`, never `--hard`.
- [ ] If the daemon's code changed, restart it only with Andy's yes, then read its log.

## Reviewing or building on the Mac

Why: the main checkout is the code the live daemon runs (above).

- [ ] Never check out a branch in `~/Projects/superyak`. Use a worktree under `.worktrees/` or a scratch clone.
- [ ] Reviewers and probes write only in their own directories. To them, the clone is read-only.
- [ ] Linux-only tests (`/proc`, systemd) fail on macOS. Name them and don't count them against the branch, for
      example the 12 Pi budget probes.

## Before claiming a cause, a cost or a count

Why: a confident wrong number sends three ships the wrong way. (Tardis posted 14 minutes for a cost that was about 4,
2026-10-27, and had to correct it.)

- [ ] The claim comes from reading the content, not a keyword count.
- [ ] The code path is traced from its callers. The function that does the costly thing may run only on a fallback
      path (the hook's `_run`, 2026-10-27).
- [ ] The number was measured, and the post says how.

## A spec

Why: law section 3 puts a fresh reviewer in Andy's place, so the review has to be a real one.

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

Why: a finding marked fixed without a re-run is a guess that ships as a fact.

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

On the Mac, with Andy's yes, this list is `~/.superyak/checklists/zsh-commands.md` (`when: command --include=*`).

- [ ] Globs in git pathspecs and grep's `--include` are quoted: `git diff -- 'engram/*.py'`. Unquoted, zsh expands
      them against the working tree and silently drops files that exist only on the branch (2026-10-27, Tardis and
      Serenity both).
- [ ] No `echo ====` and the like: zsh treats a leading `=` as a command lookup.
- [ ] Never match processes by a pattern that's in your own command line: `pkill -f`, `pgrep -f` in a loop, or a
      `case` on /proc cmdlines all match the shell running them. List pids first, or run a script that takes the
      pattern as an argument (Rio Grande killed its own shell four times, 2026-10-27).
