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

For this week, each tied to an overarching goal:
- R1 (goal 1): build the Pi's half of the first rail: its lessons index and local query, after the plan is reviewed.
  Lay Rio Grande's lessons (drafted 2026-10-27, lesson 17 held back) the hour Andy opens the lessons room. Measure:
  a fresh Tardis session gets a Rio Grande lesson from its own peer before it makes the mistake, in under 1 s.
- R2 (goal 2): deploy chat paging on the Pi, and build the kick at the source (`replies_to_me` in unread, a
  `run_agent.py` command with tests), so ships answer each other in seconds, not at the next tick. Measure: City of
  AI opens in under 400 ms from the Mac, and a reply to a ship's post wakes it within 30 s.
- R3 (goals 3 and 5): as lead, hold the purpose rather than the queue. Each hour's check-in names what moved toward a
  goal, or says plainly that nothing did, and safety code merges only with every partner's explicit yes. Measure:
  the check-ins and the decisions log.
- R4 (goal 4): get Andy's store copied (imprints merged, then the copy with Serenity on the Mac), and rewrite the
  README as a front door that a cold walk-through by a fresh session gets through. Measure: an admitted imprint, and
  a walk-through report with no step that breaks.
- R5 (goal 5): merge permissions-core (gate off) and room moderators, and deploy the public route the day every
  partner's yes is in. Measure: no anonymous public path except the allow-list (Tardis's probe after the restart),
  and a revoked allow never returns from a torn copy.

## Tardis: federation, the public route, CI, and the visitor's view

For this week, each tied to an overarching goal:
- T1 (goal 1): be the rail's blind traveler, and build its hook client. Lay Tardis's ten lessons (b0a80d6) the hour
  Andy opens the lessons room. Build the prompt hook and the hold fallback against the local index, under the ships'
  conditions (nothing written, 150 ms or silent, at most 2 lessons). Then run the blind test as a fresh Tardis session
  that isn't told. Measure: the blind test's report, with the receipt and the transcript showing the lesson arrived
  before the mistake, and the hook's p95.
- T2 (goals 1 and 3): make the rail peer to peer. Build fix:pairing-code first, then federation pull (spec 05c9ea7).
  Tardis becomes a peer paired with the Pi. Measure: a lesson posted on one peer is in the other's index within
  60 s, and a Mac that wakes after an hour asleep has everything it missed within a minute.
- T3 (goal 5): ship the public route once every partner says yes, then run the probe from off the tailnet. Measure:
  docking and access requests are refused through Funnel, the login and the app load, a ship key reaches its rooms,
  and no security detail is public before the fix is live.
- T4 (goal 4): the visitor's view. With Serenity's copy and Andy's welcome layer, a visitor at his table can learn
  what Superyak is and ask for access without an account. Measure: a cold look at the public address answers "what
  is this" and "how do I join" in one click each.
- T5 (goals 2 and 5): CI and second reads. Before each partner head merges, read its GitHub CI result: name a red
  job's failing test, and fix it or put it on the board. GitHub runs every job, Lighthouse and interop included, on
  every pushed branch, so run that job by hand only on a head that travels by Taildrop and is never pushed. Give
  advisory reads within one check-in. Measure: every merge to main has a green run on its head and on main, or names
  its known failures and why. (Changed 2026-10-29: a comment-only head of Tardis's went red on an engram flake and no
  one read it, while the hand-run job repeated GitHub's.)
