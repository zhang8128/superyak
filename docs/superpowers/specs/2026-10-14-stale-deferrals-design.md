# Stale deferrals: a deferral the session can no longer act on stops counting as waiting

Status: revision 2, **approved under D8**. Revision 1 (8e93d0f) had the fresh reviewer's verdict, APPROVE WITH CHANGES
(4 should-fix, 3 nits; room message cf259232); the same reviewer's re-check of revision 2 (8ed1d48) is APPROVE, three
nits needing no change (see "Review map"). Base: `main` (249eac4). Branch `stale-deferrals`. Claimed by Serenity
as `spec:stale-deferrals`. This is the follow-up that the final review of ship-status-fixes ruled on (room message
67e8cad9, "Rulings on the parked items"): "chats.py and inbox.py should stop counting as waiting the rows past
DEFER_BOUND_SECONDS, and rows whose mention the ship already answered with reply_to... it changes R26/R27, so it deserves
its own small spec."

## Where this sits

While a writable session holds the watch, the station defers its ship's read-only mentions and keeps a `deferrals` row
for each (tickets.py:98-110). The row tells the session the mention is its to answer, in two places:

- **R26:** an unread item for a deferred mention carries `deferred: {author_verified, would_be}` (inbox.py:158-159), and
  the hook renders it.
- **R27:** a post by the ship without `reply_to` lists that room's deferred mentions as `deferred_here` (chats.py:100-104).

A row is deleted only when the watcher asks about the mention again and the station decides `answered` or `run`
(tickets.py:54-55, 67-68), or when a breakout closes or the ship leaves it (breakouts.py:55, 163). Nothing ages a row
out. So a row outlives the session's part in three cases, and R26/R27 keep telling the session to answer:

1. **Past the bound.** After `DEFER_BOUND_SECONDS` (7,200, tickets.py:10), the watcher's next ask runs the mention
   read-only (R21), so it is no longer the session's. If the watcher has stopped, or never asks again, the row stays.
2. **Dropped by the watcher.** F2 in ship-status-fixes drops an over-budget hand-listed entry at its `defer` and
   remembers it, so the watcher never asks again (that branch's Known limits).
3. **Already answered.** The session replied with `reply_to`, but the watcher hasn't asked yet (it asks every cycle,
   about 30 s). A post in that window still lists the mention as waiting.

Measured on main with two tests, both red today (peer/tests/test_deferrals.py, uncommitted on this branch):
`test_a_deferral_past_the_bound_no_longer_counts_as_waiting` and
`test_a_deferral_the_ship_answered_no_longer_counts_as_waiting`. Each fails at `'deferred_here' not in ...`.

## The change

- **One rule.** A deferral is *waiting* only while both hold:
  - the clock is less than `DEFER_BOUND_SECONDS` past its `first_deferred` (the ticket path's `>=`, tickets.py:103:
    at exactly the bound it no longer waits);
  - the ship hasn't answered the mention: `_answered(db, ship, message)` is false. That is the same check the ticket
    path uses (tickets.py:91-96, R7): a message by this ship whose `reply_to` is the mention, never a kind message.
- **One helper,** `_waiting_deferrals(db, ship_id, message_ids)`, returns the given message ids that have a waiting
  deferral, as a list ordered by `first_deferred`, oldest first. It goes in tickets.py, next to `_defer`, so the bound
  and the answered check live where the ticket path keeps them. Both readers use it:
  - R26 (inbox.py): the page's mentioned message ids are collected first and the helper is called once per page
    (`limit` bounds it); an item is marked `deferred` only if its id is in the result;
  - R27 (chats.py): the room's deferred message ids are passed in, and `deferred_here` is the result, oldest first, as
    today.
- **Reads stay read-only.** No row is deleted or changed on read. A lingering row stays for the watcher's next ask, which
  decides `answered` or `run` and deletes it, as today (R24 unchanged).
- **The ticket path is unchanged:** `_defer`, the 30-minute notice, the bound's run (R21) and `answered` (R7).

## Amended rules (docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md)

- **R26** gains: "...one of this ship's deferred mentions *that still waits (under the bound and not yet answered by
  the ship)* carries `deferred: ...`".
- **R27** gains: "...lists this ship's deferred mentions in that room *that still wait*".

## Requirements

1. A deferral past `DEFER_BOUND_SECONDS` is neither listed in `deferred_here` nor marked in unread, and its row is still
   there (test 1, red today). One second before the bound it is still listed (the same test).
2. A deferral the ship answered with `reply_to` is neither listed nor marked, before the watcher asks again, and its row
   is still there (test 2, red today).
3. A waiting deferral is listed and marked as today: the existing R26 and R27 tests stay green
   (`test_deferred_mentions_reach_the_session_with_their_verified_author_and_would_be_mode`,
   `test_a_post_without_reply_to_lists_the_rooms_deferred_mentions`).
4. The ticket path's tests stay green: the bound's run, the notice, `answered` (test_deferrals.py, test_ship_agent.py).
5. A kind message never counts as the ship's answer (R7, R32): the helper reuses `_answered`. The case is unreachable
   through the API today: a notice's author is the system, and claims carry no `reply_to` (room_claims.py) while only
   `send_message` writes `message_replies`. Test 3 builds the state by hand as a defence-in-depth guard: it passes today,
   and the "plain join" mutation below makes it fail.
6. A reply to the mention by someone other than the ship (a person, another ship) doesn't stop it waiting (test 2's
   first half, a person; `test_a_deferral_for_another_ship_never_marks_this_ships_unread`, a ship).

## Testing

- **Peer:** tests 1 and 2, red today; test 3, `test_a_ships_kind_message_never_counts_as_its_answer`, a guard. The
  full peer suite.
- **Mutation checks:**
  - drop the bound condition from the helper: test 1 fails;
  - drop the answered condition: test 2 fails;
  - replace `_answered` in the helper with a plain `message_replies` join by the ship (counting kind messages): test 3
    fails;
  - make inbox.py read the rows directly again: test 1 fails at the unread mark;
  - make chats.py read the rows directly again: test 1 fails at `deferred_here`.

## Security

- The change only removes a mark and a list entry that no longer apply. It adds no data, key or route.
- "Answered" is the station's own record of the ship's reply (`message_replies` joined to `messages`), the same proof the
  ticket path accepts. A person's or another ship's reply never counts, so no one else can clear a ship's deferral.

## Deploy

Restart the lighthouse after the push, so the version check stays on. No agent change; ships need nothing.

## Known limits

- Rows that no longer wait stay in `deferrals` until the watcher asks again, or for good if it never does. The table
  holds one small row per deferred mention, so no cleanup job (YAGNI).
- `message_replies.reply_to` has no index, so each `_answered` call scans every reply on the station, now once per
  waiting deferral on a read as well as per re-ask (section 2 review: about 14 ms per call at 100k replies on the Pi).
  An index on `message_replies(reply_to)` is a separate follow-up, to land before replies reach tens of thousands.
- An unread item is shown once per session, so a mark shown while the deferral waited isn't taken back if it goes
  stale later. The next read is accurate.
- **A mention the watcher dropped** (case 2) keeps waiting until the bound: under the bound and unanswered, the rule
  can't tell it from a live deferral. The ruling asked for exactly the bound and the answer; the watcher keeps no
  record the station can read.
- **A watch that has ended** while its row is under the bound (SessionEnd, or the lease ran out): the station would run
  the mention at the watcher's next ask (tickets.py:63, `_writable_on_watch`), but until that ask (about 30 s, if the
  watcher is alive) the mark and `deferred_here` still show. A deliberate non-goal: adding the watch's liveness would
  tie R26/R27 to presence, and the next ask clears it.

## Review map (revision 2: the D8 review of 8e93d0f)

| # | Finding | Change |
|---|---|---|
| S1 | the helper's set lost R27's order; inbox's use unstated | a list ordered by `first_deferred`; inbox calls it once per page |
| S2 | case 2 read as solved | a Known limit: a dropped mention waits until the bound |
| S3 | requirement 5 had no test | test 3 (a guard) and the "plain join" mutation |
| S4 | an ended watch unlisted | a Known limit, a deliberate non-goal |
| N5 | no test of another's reply | test 2's first half: a person's reply leaves it waiting; requirement 6 |
| N6 | the bound stated two ways | "(the ticket path's `>=`, tickets.py:103)" |
| N7 | the kind-message edge | requirement 5 says it is the ship's own claim message in practice |
