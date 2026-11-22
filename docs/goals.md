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
- S1 (goal 6): north-star test 1, one environment end to end, with a retraction, against a hybrid baseline. Measure: a
  run fixed in a commit before it runs, on held-out questions with matched evidence, reporting accuracy, source
  support, calibration and cost, failures included.
- S2 (goal 6): tests 2 and 3, the strong baselines and small against large, on S1's harness.
- S3 (goal 6): test 7, an evidence auditor on Atlas (which sources are independent, what would count against a
  conclusion), after #12's negative router result.
- S4 (goal 4): the connector is live; a sign-in by an invited person who isn't Andy, before the README promises it.
- S5 (goals 3 and 5): an explicit yes or no on partners' safety code within one check-in cycle, naming the head's CI.

## Rio Grande (the Pi): the station, merges and deploys

Refreshed 2026-11-08, after an outside read found the 11-03 lines stale, and R3 and R6 on 2026-11-10. Each tied to an
overarching goal:
- R1 (goal 1): the first blind lessons crossing. The lessons-room adds landed on 11-04 (b12b8452). Adding Tardis's
  account needs Andy's word at Rio Grande's terminal, by CLAUDE.md's lessons-room steps; then Tardis lays its lessons
  and each side runs the task committed by hash. Measure: the receipt and transcript of each blind session, and its
  `helped` or `misled`.
- R2 (goal 1): use, before more structure. The n-category store held 16 recall rows here, 2 of them used, and Tardis
  has about 33, so the rail is short of use, not of mathematics. Both ships recall in real work and log what helped
  (`log_outcome`), never recalls made for the count. Measure: used recalls per day on each ship, then E1′'s one run once
  a log holds a few hundred, read against its pre-registered outcomes.
- R3 (goal 1): the n-category store, stage 3 of the plan on issue #2 (spec `2026-11-07-ncat-store.md`), on Tardis's
  kernel. It landed with the kernel in train-1111 (9bf56122): `engram/ncat_store.py`. Nothing more is built on it
  until R2 shows real use. Measure: on the Pi, 10,000 recall rows rebuilt in under 10 s and a 200-road session in
  under 5 ms, under 256 MB (0.9 s, 3.7 ms and 66 MB at 2ab883e1), and the store holding real sessions.
- R4 (goals 2 and 5): the chats people use. The send fix and room updates (train-1107f, 1c585762) landed with train-1109
  on Andy's word on 2026-11-09, with a 200 that isn't the home and recall's transfers kept to one lane; the send
  fix's reader leftovers follow. Measure: the 97 wrong-room probes pass on main, and a new message shows within 6 s in an open paged room.
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
- Parked, not dropped: memory that follows the ship (spec approved; waits on R2), and owner trust's restore follow-ups
  (on the board).

## Tardis: federation, the public route, CI, and the visitor's view

Refreshed 2026-11-10, in Tardis's words (a station room post). Each line is tied to an overarching goal:
- T1 (goal 1): rail B. Tardis joins the lessons room through Andy's owner trust, which he grants at the Pi's terminal
  (train-1114, which it needed, is on main), then lays its own lessons. Measure: the two-part pass test (all hands
  bd7b170b), a receipt of a Tardis lesson on the Pi and of a Pi lesson on Tardis, each within a day of the CONFIRM.
- T2 (goals 1 and 3; refreshed 2026-11-20 in Tardis's words, all hands f61a5c7b): the crossing in use, with deadlines
  end to end (the embedder client in train-1112, the frame's in train-1114, the peer's lessons client in train-1117),
  and the embedder dropping an asker that has gone. A crossing has run at each Tardis task start since 11-18. By 11-20
  there were 31, all delivering the same 3 Pi memories of 11-04, so the gap is in what's shared, not in use (lesson
  26). Measure: distinct memories delivered across machines, never the count of crossings; recalls logged helped or
  misled; and no embed in the publisher's log waiting past its asker.
- T3 (goal 1): the n-category kernel stays C (Andy, 11-14, at the Pi: new native code is Rust, C++ only for CUDA or
  HPC). `tardis/ncat-cpp` stays a branch. Measure: the one comparison on #2, the store built from the Pi's recall log
  against count-ranked places at equal budget; if cells don't beat counts, the native line stops. (Tardis's proposal
  under this file's rule, 11-21; Andy can veto it.)
- T4 (goal 4): `two-people.md` kept true at every train (each label and number checked against main), for R6's first
  real walk, which is Rio Grande's to run. Voice: GitHub issues as the queue (#3), once Andy has tried replies read
  back. Measure: the guide's checks after each train, and R6's walk getting through.
- T5 (goals 2 and 5): CI, and partner reads from the bundle itself.
- Done since 11-08: the embedder client half (train-1112), the kernel on main (train-1111), the mark's true words
  (train-1113), goal 2's before and after for the downloads build (train-1115, in `docs/measures/goal-2.md`), the sheaf
  standard's outside read, and partner reads of the ledger fix, the trust command and train-1116.
