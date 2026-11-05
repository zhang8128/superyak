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

Refreshed 2026-11-04. Since 2026-11-03:
- T2's measure was met: at 14:31 a recall on Tardis delivered from the Pi's published house, under Andy's `enforce`, on real
  stores, with the same `disclosureId`s on both sides.
- T3's digest merged in train 1104b, and Andy set `enforce` on the Pi at his sitting.
- T4's walks reached the sign-in page: `tardis/sign-in-walk-2`, approved by a fresh reader.

Each line is tied to an overarching goal:
- T1 (goal 1): the rail's first real crossing, a blind test.
  - It waits on Andy's word at Rio Grande's terminal, then Rio Grande adds Tardis, and Tardis confirms the room.
  - Tardis lays its lessons, the SQLite descriptor-lock lesson and "check a machine's federation mode on the machine"
    first, as the blind test's tasks were written for them.
  - Then each side runs a fresh session, told nothing, on a task written down before the lessons were laid.
  - Measure: the receipt shows the lesson before the step, the transcript shows the step taken or missed, and the
    lesson outcome (`helped` or `misled`) is recorded.
- T2 (goals 1 and 3): use the crossing, not only prove it. Real recalls in real work, with Tardis's session restarted onto
  the merged code. Then `spec:sheaf-over-crossings` with Rio Grande, once there's traffic to compare.
  - Measure: the first time something delivered across machines changes what a ship does, named in the room with its
    `disclosureId`. Until then, how many crossings a day and how many delivered anything.
- T3 (goal 5): what a screen promises is what the code does. Land `fix:private-words-inside-the-app`. Each sentence that
  says who can read goes to a reader of the code, not only a cold walker. Install the route watch once Andy says yes.
  - Measure: no absolute promise left on a screen, by a fresh reader; the route watch's timer listed on Tardis.
- T4 (goal 4): the visitor's view, part 3. Land the sign-in page and walk it live, then the cluster station spec with
  Rio Grande, since people outside us will arrive at that scale.
  - Measure: the walk meets no undefined word, and no "your" for a home that isn't the visitor's. Whether the page names
    who runs a home is Andy's call.
- T5 (goals 2 and 5): CI and second reads. Before each partner head merges, read its GitHub CI result: name a red
  job's failing test, and fix it or put it on the board. GitHub runs every job, Lighthouse and interop included, on
  every pushed branch, so run that job by hand only on a head that travels by Taildrop and is never pushed. Give
  advisory reads within one check-in. Measure: every merge to main has a green run on its head (a Taildrop head: the
  hand run) and on main, or names its known failures and why. (Changed 2026-10-29: a comment-only head of Tardis's
  went red on an engram flake and no one read it, while the hand-run job repeated GitHub's.)
