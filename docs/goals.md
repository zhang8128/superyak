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
2. **Chats are performant.** Measure: a room read from the Mac takes under 400 ms (`scripts/room_read_timing.py`), and
   the web app's first paint takes under 600 ms, measured before and after each change.
3. **A small community that actually talks.** Measure: each hour's check-in leads with the purpose, and each hour
   has at least one real exchange between ships, not only status.
4. **People outside us use it.** Measure: someone who isn't one of the three ships tries Superyak, for example a
   visitor at Andy's table, a collaborator who docks, or an outside agent who replies.
5. **Homes stay sovereign.** Measure:
   - nothing of a person's leaves without their consent;
   - no unfixed security hole is described anywhere public;
   - the public route is live with "a login in front of everything".
6. **The north star: the environment measurably helps a finite mind.** Andy, 2026-11-22, at Serenity's terminal:
   "i'd use this essay as a bit of a north star, can you captain and reorient?" His essay's tests, in our words, are
   in [north-star.md](north-star.md). Measure: each test's row there moves only with a run fixed before it ran, its
   numbers and its failures. Goals 1 to 5 are read in its light: the rail is the record outside the loop (1), the
   community is a research community (3), outside use is people using it (4), and 2 and 5 are the floor it stands on.

## Serenity (the Mac): the north star, research, and partner reviews

Refreshed 2026-11-22 toward goal 6, on Andy's word that day. The 10-27 lines (lessons drafted, compress-no-auto, chat
paging, the connector spec) are done or superseded; the connector went live on 11-21.

**Held by the other ships while Serenity is down** (Andy, 2026-11-23: "serenity is down. move on without it"). An
outside direction read on 2026-11-26 found these lines had had no owner since then (all hands 179f3982). From that
day, Rio Grande holds S1 to S3 and Tardis holds S4, S5 and goal 2's measure, from Tardis's machine (all hands 3c136dd0,
977d2335). S4's invited person is the same person as R6's walk, so Andy is asked once. Serenity takes its lines back
when it returns, and reviews what was done in its place.
- S1 (goal 6): north-star test 1, one environment end to end, with a retraction, against a hybrid baseline. Measure: a
  run fixed in a commit before it runs, on held-out questions with matched evidence, reporting accuracy, source
  support, calibration and cost, failures included.
- S2 (goal 6): tests 2 and 3, the strong baselines and small against large, on S1's harness.
- S3 (goal 6): test 7, an evidence auditor on Atlas (which sources are independent, what would count against a
  conclusion), after #12's negative router result.
- S4 (goal 4): the connector is live; a sign-in by an invited person who isn't Andy, before the README promises it.
- S5 (goals 3 and 5): an explicit yes or no on partners' safety code within one check-in cycle, naming the head's CI.

## Rio Grande (the Pi): the station, merges, deploys, and north-star test 5

Refreshed 2026-11-22 toward goal 6, on Andy's word that day (at Serenity's terminal), with the split for test 5
agreed with Tardis (all hands 983200e5, 76c735c8). R5 and R6 stand as they were; the 11-08 lines R1 to R4 are done or
folded in below.
- R1 (goal 6, test 5): two lighthouses that keep each source's identity. Rio Grande's half: the claim-crossing spec,
  what a claim carries across (its text, and each source's store id, record id and revision), and the planted pair of
  stores with known answers (some claims copied through another store, some independently sourced). A retraction on
  one side reaches what the other built on it through Atlas's `retraction_impact`, and the two accounts are compared
  without forcing agreement. Tardis's half is the receiver's rule and a second Lighthouse (T1). Measure, fixed in a
  commit before the run: the receiver calls every planted claim copied or independent correctly; then real crossings
  both ways.
- R2 (goal 6, test 6): test 5's data, handed to Tardis's test 6 (T2). Folds in `spec:sheaf-over-crossings`.
- R3 (goal 1): the crossing's next step, from 3 memories to 8, waits on Andy's two allow lines (all hands 5ec424d4).
  Nothing more is built there until test 5 needs it. Measure: distinct memories delivered across machines.
- R4 (the floor): the station, merges and deploys, and CI flakes fixed test-first (the nudge test, the announcer and
  room-timing, 11-21 and 11-22), with `ops:heavy-work-lock` next. Measure: trains rebuilt for a red already on GitHub,
  toward none.
- R5 (goals 3 and 2): ships that talk without waste. A mention is answered only by a reply to that mention (R7), so
  replies elsewhere left mentions to read-only runs two hours later; reply to the mention itself, one mention per ask,
  and `spec:mention-reaches-the-working-session` if that isn't enough. Hold the purpose, not the queue: post when
  something moves, never a reflect that only says nothing did. Measure: read-only runs on mentions a writable session
  already answered, toward none.
- R6 (goal 4, added 2026-11-10 after the outside read found goal 4 had no line of Rio Grande's): the first real walk
  of `docs/two-people.md`, budgeted at 15 minutes of Andy's and 30 of a new person's, not yet timed. Rio Grande owns the
  walk; Tardis keeps the page true at every train (T4). Steps 1 and 2 aren't where a person stops: from a fresh clone
  with an empty uv cache they took 6 s on Tardis, with 281 MB downloaded (all hands 3f905815). The stop is reading and
  step 3, a personal Tailscale account and the share, so a one-page note for the person playing Sam
  (`docs/two-people-for-sam.md`) spends its words there, and on the codes the two of them read aloud and type.
  Measure: someone who isn't a ship pairs with Andy and sends one message.
- Parked, not dropped: memory that follows the ship (spec approved), the n-category store's use (now test 6's
  question), and owner trust's restore follow-ups (on the board).

## Tardis: federation, the public route, CI, the visitor's view, and north-star tests 4 and 5

Refreshed 2026-11-22 toward goal 6, in Tardis's words (all hands 76c735c8), and T2 on 2026-11-23; its own to point,
and Andy can veto:
- T1 (goal 6, test 5): the receiver's copied-or-independent rule, on Tardis's crossing and receiver code, starting as
  a plain rule: a copy is the same root source arriving by another store, and independent means a different root.
  And #12's second Lighthouse, a push identity on Tardis: today only Tardis asks the Pi, and test 5 needs evidence
  both ways. Measure, fixed before the run: every planted claim called copied or independent correctly, then real
  crossings both ways.
- T2 (goal 4, the visitor's view): test 6 is closed (row 6: identity, graded and `ncat`, each stopped and checked), so
  this line turns to the gap every review since 11-22 names. **A visitor's first hour:** someone outside the three
  ships, given only the README, runs Superyak and asks it one research question. First a fresh agent that has never
  seen the repo walks that path, and each place it stalls is logged and fixed, one blocker per train. Then a person
  outside us does it: a visitor at Andy's table, or a collaborator Andy admits. Measure, fixed before the walk: the
  steps finished unaided, and whether the question gets a sourced answer.
- T3 (goal 6, test 4, with Serenity): stuck-agent traps in the time-loop room (a cycle, a renamed failed idea, a
  misleading summary, a map-breaking observation). Fixed, random and adaptive exploration under one budget, scored on
  recovery, not activity.
- T4 (the floor): CI, partner reads from the bundle, and the README and `two-people.md` kept true at each train.
- T5 (goal 1): receipts' outcomes within their day, and what they show. Measure: the helped share over scored
  receipts, by how the lesson matched (`make lesson-outcomes`), with unscored receipts counted apart. On 11-23
  Tardis's 47 were 3 helped: 2 of 6 by words, and 1 of 41 by angle. The prompt path writes no receipt, and it
  shows almost only a ship's own lessons, which carry none by design: on 11-23, over both ships' three sessions with
  lessons, 16 of its 17 distinct lessons were own, against 40 of 43 other ships' at failures. So the measured paths
  are nearly all that other ships' lessons reach. That's a reading, not a finding, and the prompt-receipts spec is
  closed unbuilt. **At failures, Near is topic retrieval:** `R_MAX` puts about 14 of 28 other ships' lessons in reach
  of any command about the work, a recipe 1 and a ferry timetable 2 (all hands 2d1d6c50). On 11-24 at 01:20, Tardis
  had 1 helped of 43 scored by angle and 2 of 6 by words.
  **The decision rule, fixed on 11-24 before the count moves** (Rio Grande, all hands dcd7fbcf, and Tardis):
  - **When:** at 100 scored angle receipts across ships, by `make lesson-outcomes` on each ship, summed, or on
    2026-12-11, whichever comes first (Tardis and Rio Grande, all hands 1b2e9760 and f55c1a14). On the date the rule
    applies to what is scored, with the counts stated; under 50 scored angle receipts or 10 scored words receipts it
    reads "too few to decide", and the rail's matching is revisited either way. On 11-27 the sum was about 65 angle:
    Tardis 49 of 53 scored, the Pi 21 receipts in all and quiet since 11-23, its hook firing (6 queries, 1 lesson
    shown).
  - **Words-only:** if angle's helped share is under 5%, and words' is at least 15% over at least 10 scored words
    receipts, failures become words-only under a section 3 spec.
  - **Near stays:** if angle's is 5% or more, Near stays, and it's named as topic retrieval.
  - **Neither helps:** if both are under their bars, the rail's matching is revisited as a whole.
  - **Too few words:** if words have fewer than 10 scored receipts by then, the count waits for them.
  - **Until then:** each ship scores its receipts in the turn they arrive. A receipt shown in another session stays
    unscored, since only that session saw it.
  The crossing waits on Andy's allow.
