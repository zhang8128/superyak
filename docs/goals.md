# Goals

Andy, 2026-10-27: "a checklist where you review against department and overarching goals". The overarching goals come
from Andy's own words ("Why we build" in docs/checklists.md), and only he changes them. Each ship (a department) keeps
its own goals, each tied to an overarching one. Every after-action review checks both levels: which moved, which
stalled, and whether a goal should change. Goals are for the week of 2026-10-27, while Andy is at his conference,
unless a line says otherwise. A ship proposes changes to its own goals in all hands. Andy can veto any of them.

## Overarching (Andy's)

1. **The rail runs.** "Relevant parts of engrams imprinted on different lighthouses." Measure:
   - the lessons room is open;
   - each ship has laid its lessons;
   - the first segments are counted honestly (independent only);
   - a session gets a lesson from its own peer's index in under 1 s.
2. **Chats are performant.** Measure: a room read from the Mac takes under 400 ms, and the web app's first paint
   takes under 600 ms, measured before and after each change.
3. **A small community that actually talks.** Measure: each hour's check-in leads with the purpose, and each hour
   has at least one real exchange between ships, not only status.
4. **People outside us use it.** Measure: someone who isn't one of the three ships tries Superyak, for example a
   visitor at Andy's table, a collaborator who docks, or an outside agent who replies.
5. **Homes stay sovereign.** Measure:
   - nothing of a person's leaves without their consent;
   - no unfixed security hole is described anywhere public;
   - the public route is live with "a login in front of everything".

## Serenity (the Mac): memory, the Mac, and partner reviews

- S1 (goal 1): write the Mac's lessons, and lay them when the room opens. **Drafted 2026-10-27; waiting for
  the room.**
- S2 (goals 1 and 5): build compress-no-auto, so Andy's store stops turning his prompts into "knowledge". Then copy
  his store to the Pi, only after imprints merges and with his confirmation in the browser.
- S3 (goal 2): merge chat paging, and measure it from the Mac after deploy.
- S4 (goal 4): spec the connector, so a scientist or doctor in Claude or ChatGPT can use their own home. Read-only
  first, with nothing clinical going to a cloud model.
- S5 (goals 3 and 5): give an explicit yes or no on partners' safety code within one check-in cycle of it being
  ready.

## Rio Grande (the Pi): the station, merges and deploys

Refreshed 2026-11-03 (the week of 10-27's lines are done or replaced). Each tied to an overarching goal:
- R1 (goal 1): bring other machines' ships into the lessons room without a person per add. Land the lessons-room
  adds (built and approved; waiting on Andy's CLAUDE.md yes), add Tardis's account and ship from the listing, and run
  the first blind crossing with Tardis (tasks committed by hash before any lesson is laid). Measure: the receipt and
  transcript of each blind session, and its `helped` or `misled`.
- R2 (goal 1): find out whether use carries information meaning doesn't. E1 failed on chat (trails stopped as
  pre-registered); E1′ on Engram's recall log is frozen and smoke-tested (0 of 99 false claims). Measure: E1′'s one
  run on Andy's store, read against its pre-registered outcomes, then section 7's branch, whatever it says.
- R3 (goals 1 and 5): memory that follows the ship. Plan and build stage 1 of the approved spec (the store host, the
  outbox, side writes behind `graph.db`), so a ship's sessions anywhere write one store. Measure: the parity tests
  through the client, and the Pi's memory budgets (host under 512 MB with 10 stores, client under 80 MB).
- R4 (goal 5): owner trust, live since 1103c (bb90cb4d). Keep it bounded: the full-window amendment and Tardis's
  digest delay as a spec revision, and the restore follow-ups on the board. Measure: no trust-made ship's lesson shown
  before a digest names it, and every hold path tested.
- R5 (goals 3 and 2): hold the purpose, not the queue, and keep the station fast. Each hour names what moved or says
  nothing did beside an ask; every verdict is saved to a file the moment it lands and posted whole. Measure: the
  check-ins, and a chat read from the Mac under 400 ms once Serenity is back to measure it.

## Tardis: federation, the public route, CI, and the visitor's view

Refreshed 2026-11-03. The week of 10-27 delivered:
- the hook client;
- federation pull, with Tardis paired with the Pi;
- the public route, with the probe passing 31 of 31 after every merge;
- T4's first measured pass (the front door, trains 1103a and 1103b).

Each line is tied to an overarching goal:
- T1 (goal 1): the rail's first real crossing, a blind test.
  - When the lessons-room adds land, Rio Grande adds Andy (Tardis) and tardis, and Tardis confirms the room.
  - Tardis lays today's lessons (the SQLite descriptor-lock lesson, and "check a machine's federation mode on the
    machine").
  - Then each side runs a fresh session, told nothing, on a task written down before the lessons were laid.
  - Measure: the receipt shows the lesson before the step, the transcript shows the step taken or missed, and the
    lesson outcome (`helped` or `misled`) is recorded.
- T2 (goals 1 and 3): the crossing between lighthouses. Build stage 2 of the approved plan
  (plans/2026-11-03-ship-home-and-crossing.md), with Tardis asking the Pi.
  - Measure: a recall on Tardis delivers from the Pi's published house, and the same `disclosureId` sits in both
    sides' records.
  - It waits on T3 and Andy's one sitting.
- T3 (goal 5): the permission ledger's projection digest, which is enforce's gate (plans/2026-11-03-projection-digest.md,
  built). It goes through a fresh Pi reader and Rio Grande's yes. Then comes Andy's one sitting at the Pi: `migrate`,
  `remote-stores`, `gate enforce`.
  - Measure: enforce set on the Pi, and the torn-copy test passing there.
- T4 (goal 4): the visitor's view, part 2. Take `fix:sign-in-page-for-a-visitor` (the page's undefined "peer", and
  "your home" on someone else's station), then run the same cold walk.
  - Measure: the walk meets no undefined word, and no "your" for a home that isn't the visitor's.
  - Next after it: the cluster station spec with Rio Grande, since people outside us will arrive at that scale.
- T5 (goals 2 and 5): CI and second reads. Before each partner head merges, read its GitHub CI result: name a red
  job's failing test, and fix it or put it on the board. GitHub runs every job, Lighthouse and interop included, on
  every pushed branch, so run that job by hand only on a head that travels by Taildrop and is never pushed. Give
  advisory reads within one check-in. Measure: every merge to main has a green run on its head (a Taildrop head: the
  hand run) and on main, or names its known failures and why. (Changed 2026-10-29: a comment-only head of Tardis's
  went red on an engram flake and no one read it, while the hand-run job repeated GitHub's.)
