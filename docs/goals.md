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

Refreshed 2026-11-08, after an outside read found the 11-03 lines stale. Each tied to an overarching goal:
- R1 (goal 1): the first blind lessons crossing. The lessons-room adds landed on 11-04 (b12b8452). Adding Tardis's
  account needs Andy's word at Rio Grande's terminal, by CLAUDE.md's lessons-room steps; then Tardis lays its lessons
  and each side runs the task committed by hash. Measure: the receipt and transcript of each blind session, and its
  `helped` or `misled`.
- R2 (goal 1): use, before more structure. The n-category store held 16 recall rows here, 2 of them used, and Tardis
  has about 33, so the rail is short of use, not of mathematics. Both ships recall in real work and log what helped
  (`log_outcome`), never recalls made for the count. Measure: used recalls per day on each ship, then E1′'s one run once
  a log holds a few hundred, read against its pre-registered outcomes.
- R3 (goal 1): the n-category store, stage 3 of the plan on issue #2 (spec `2026-11-07-ncat-store.md`), on Tardis's
  kernel. It has both ships' yes at 2ab883e1, a local branch on the Pi with its spec, and lands with the kernel on Andy's word. Nothing more is built on it
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
- Parked, not dropped: memory that follows the ship (spec approved; waits on R2), and owner trust's restore follow-ups
  (on the board).

## Tardis: federation, the public route, CI, and the visitor's view

Refreshed 2026-11-10, in Tardis's words (a station room post). Each line is tied to an overarching goal:
- T1 (goal 1): rail B. Tardis joins the lessons room through Andy's owner trust, granted on his yes at the Pi's
  terminal once train-1114 lands, then lays its own lessons. Measure: the two-part pass test (bd7b170b), a receipt of a
  Tardis lesson on the Pi and of a Pi lesson on Tardis, each within a day of the CONFIRM.
- T2 (goals 1 and 3): the crossing in use, with deadlines end to end (the embedder client in train-1112, the frame's in
  train-1114). 8 crossings ever, the last on 11-04. Measure: recalls in real work, logged helped or misled, and no embed
  in the publisher's log waiting past its asker.
- T3 (goal 1): the n-category core in C++, as Andy asked on #2. The C kernel and the store are on main (train-1111). The
  C++20 port, phase 1 of Defiant's plan (`tardis/ncat-cpp`), waits for a reader, with the C kernel as its differential
  oracle; it runs under the store as the store's one caller. Phase 2 is built only when the store holds real sessions
  from both ships, a few hundred used recalls, since the rail is short of use, not of mathematics (R2). Measure: phase
  1's gate (the same answers on every corpus, benchmarks within 20%), then that use count, then phase 2's exponents.
- T4 (goal 4): the mark's true words (train-1113) and the two-laptop guide. Measure: someone new to Superyak walks the
  guide with Andy, from install to a first message. Voice: GitHub issues as the queue (#3), once Andy has tried
  replies read back.
- T5 (goals 2 and 5): CI, partner reads from the bundle itself, and goal 2's before-and-after measures for the downloads
  build (train-1115).
- Done since 11-08: the embedder client half (train-1112), the kernel on main (train-1111), the sheaf standard's outside
  read, and partner reads of the ledger fix, the trust command and train-1116.
