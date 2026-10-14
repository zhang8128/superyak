# Ship status fixes: three follow-ups from the re-review of 5374784

Status: revision 2, **approved under D8**. Revision 1 (479ab84) had the fresh reviewer's verdict, APPROVE WITH CHANGES
(3 must-fix, 2 should-fix, 1 nit; room message 032f992e); the same reviewer's re-check of revision 2 is APPROVE, no
remaining findings (see "Review map"). Base: `main` (e633ec3). Branch `ship-status-fixes`. Roadmap phase 4
("small ship-status fixes"), claimed by Serenity as `fix:ship-status-small`. The three come from Rio Grande's post
cec51af8c2af4a8bb12997baae146546 (2026-10-10), the follow-ups of the ship-status re-review. That post gives one line and
a suggested fix for each; the scenarios below are reproduced as failing tests on this branch.

## The rule these keep: R37

Ship-status R37 (docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md:430): a re-ask of a deferred
mention is spared from the watcher's five-an-hour ship budget **only on the station's word**. That word is a run
carrying `first_deferred`, or the station echoing the exact ticket id it already issued for that mention. It is never
spared because the watcher's state says so. Both fixes below keep that rule: the watcher's state may cause a charge,
never a spare.

## F1. A hand-edited malformed member can't break a received room or the room list (done: b04d516)

- **Bug:** `receive()` refuses a malformed roster (federation.py:319-326), but a hand-edited inbox row reached
  `_remote_room`'s `m['peer']` (peer_store.py:73) and raised KeyError in `get_room` and `list_rooms`.
- **Fix:** members that aren't `{peer: str, id: str}` are left out.
- **Test:** `test_a_hand_edited_malformed_member_cannot_break_the_room_list`. It failed with KeyError at
  peer_store.py:73 and passes now.

## F2. A hand-listed deferred entry is charged once

- **Bug:**
  - An entry on the watcher's deferred list skips the charge at entry (watch.py:114, `not listed`).
  - Normally that's right: the entry was charged at entry when it was new, then deferred.
  - A hand-listed entry was never charged: the only source of such an entry is the owner's hand edit of the state file.
    A list carried over from an older watcher was charged at entry (every released watcher charged a ship's mention
    before listing it, since d179f8d), so the new watcher stamps those entries at its first start (`listed_charged`)
    and doesn't charge them again.
  - If the station's first answer to it is `defer`, the watcher keeps waiting. The station's eventual run carries
    `first_deferred`, which spares it under R37, so the mention is never charged at all.
- **Test:** `test_a_hand_listed_entry_the_station_then_defers_is_charged_once` fails today: 0 charges.
- **Fix (the watcher), in the `defer` branch only** (watch.py:143-152):
  - When the watcher puts a new mention on its list after the station's `defer` answer, the entry records that answer's
    `first_deferred` (`entry['first_deferred']`). That records that this watcher charged the mention at entry.
  - When the station answers `defer` for a listed entry **without** a recorded `first_deferred` (hand-listed), the
    watcher charges it there, once.
    - Over budget, it gets the pause note and leaves the list, as an over-budget new mention does today. No ticket was
      issued for a `defer`, so there's nothing to finish.
    - Within budget, it records the answer's `first_deferred` on the entry, so a later `defer` doesn't charge it
      again.
  - **A `run` answer is unchanged:** the existing `held` check (watch.py:155-162) already charges a run that carries
    neither `first_deferred` nor a recorded ticket id, and spares one that carries either. That's the station's word,
    so the hand-listed entry's eventual run carrying `first_deferred` is spared, correctly, because it was charged at
    its `defer`.
  - The recorded value is used only to decide whether to charge, never to spare. Sparing stays as R37 says.

## F3. A lost `run` response no longer over-charges a deferral the station held

- **Bug:**
  1. A ship's mention is charged at entry, then deferred by the station.
  2. The station later issues its run (tickets.py:67-68), deletes its deferral row, and answers with `first_deferred`,
     but the response is lost.
  3. The retry gets the same running ticket back (tickets.py:57-60, `_decided`) without `first_deferred`, because the
     row is gone. The watcher never recorded that ticket's id.
  4. So under R37 the retry is charged again, and with the hour's budget spent the mention is dropped with a pause
     note.
- **Tests:**
  - **Red evidence, on the station:** a peer test where a run ticket issued from a deferral, asked for again, carries
    no `first_deferred` today and must carry it.
  - **The agent side:** `test_a_lost_run_response_for_a_deferral_the_station_held_is_not_charged_again` models the
    fixed station, so its retry answer carries `first_deferred=1.0`. It passes with no watcher change, which shows the
    watcher needs none.
- **Fix (the station; the watcher is unchanged):**
  - The `tickets` table gains a nullable `first_deferred REAL` column. It's added at startup with db.py's existing
    `PRAGMA table_info` / `ALTER TABLE ADD COLUMN` pattern (db.py:64-74).
  - When the station issues a run that resolves a deferral it held, it writes that row's `first_deferred` to the
    ticket.
  - Whenever the station returns a running ticket to a watcher that asked for decisions, the answer carries the
    ticket's `first_deferred` if it has one: on issue, as today, and on every re-send.
  - **Where:** in `_decided` (tickets.py:78), gated on `decisions`, as today's issue-time field is (tickets.py:74-75).
    Never in `_ticket_json` (tickets.py:33), which `finish_ticket` and no-`decisions` answers share, so an old watcher
    never sees a new key (R23).
  - So the retry is spared on the station's word, under R37 as written. Two sentences of R37 change:
    - "...a `run` that resolves a deferral it held carry that row's `first_deferred`" gains "**including when the
      station sends that running ticket again**";
    - "The station deletes its deferral row when it issues the run ticket, so a retry after a failed run gets that same
      ticket back without `first_deferred`" becomes "...so a retry after a failed run gets that same ticket back, **now
      carrying the `first_deferred` the ticket itself recorded**". The echoed-id clause after it stays for tickets that
      never carried one.
- **Why not the post's suggestion** (spare on the `first_deferred` recorded in the entry): that would spare because
  the watcher's state says so, which R37 forbids. A hand-edited entry could then dodge the budget. F2 records the
  value only to charge.

## Requirements

1. F1's test passes; `get_room` and `list_rooms` keep every valid member of a hand-edited payload.
2. F2's test passes: one charge for the hand-listed entry. A hand-listed entry over budget gets the pause note and
   leaves the list. A normally listed entry, charged at entry with `first_deferred` recorded, is never charged again
   (the existing R37 tests stay green).
3. F3's agent test passes, with no change to the watcher. Station tests show:
   - a re-sent running ticket from a deferral carries `first_deferred`;
   - one not from a deferral carries none;
   - a no-`decisions` re-ask of a ticket from a deferral carries none (R23).
4. The column migration is additive. It's idempotent on an existing database (run twice, one column). An old binary on
   the migrated database ignores the column, so a rollback to main keeps working.
5. Without `decisions`, every answer stays exactly today's (R23).

## Security

- The budget protects a ship from other ships' floods. Every change only adds charges or spares on the station's
  word. Local state can withhold F2's charge, never create a spare (the first-start stamp only withholds a charge; a hand-edited entry that already has `first_deferred`
  skips F2's charge: it is the owner's own file, and the budget protects the owner from other ships).
- The column holds the station's own timestamp. No client value is written to it.

## Testing

- **Peer:**
  - F1's test;
  - a ticket test: issue from a deferral, then re-ask, and the same running ticket carries `first_deferred`; a ticket
    not from a deferral carries none, also on re-send; a no-`decisions` re-ask carries none;
  - a migration test: a database without the column gains it once, and a second start changes nothing.
- **Agent:**
  - F2's and F3's tests;
  - the existing R37 tests unchanged, except that
    `test_a_deferred_breakout_mention_keeps_its_mark_and_its_budget` (test_watch_deferral.py:332-347) adds the new
    `first_deferred` key to its expected entry (N1);
  - an over-budget hand-listed entry gets the pause note at its `defer`.
- **Mutation checks:**
  - F2: the "record on defer" line removed, so a hand-listed entry that's deferred twice is charged twice;
  - F3: the echo moved into `_ticket_json`, so the no-`decisions` test fails, or removed, so the re-send test fails.

## Deploy

Restart the lighthouse, which runs the migration, and the ship watcher, with the usual backup first. Ships pick up F2 by
pulling main: it's a change to `agent/superyak_agent/watch.py`, a runtime file, so the version check will prompt them.

## Known limits

- An entry a watcher listed before this change was charged at entry, so the new watcher stamps it at its first start
  (`first_deferred: None` and the state flag `listed_charged`) and F2 never charges it again. An entry the owner hand-adds
  later still lacks the key and is charged once at its `defer`.
- Mentions a watcher running main's code lists during a rollback lack the key, and the flag is already set, so when the
  new code returns they're charged once more at their next `defer`.
- A hand-edited entry dropped at its `defer` over budget leaves its station deferral row behind, because the station deletes a row
  only when the watcher asks again (or a breakout closes or the ship leaves it). That room's posts by the ship then
  carry a stale `deferred_here` id, and the mention keeps its R26 `deferred` mark. No safety or budget effect; a
  follow-up station spec will stop counting rows past the 120-minute bound, or already answered with `reply_to`, as
  waiting.

## Review map (revision 2: the D8 review of 479ab84)

| # | Finding | Change |
|---|---|---|
| M1 | F3's agent test modelled the old station | the retry carries `first_deferred=1.0`; the red evidence is a peer test |
| M2 | F2's "defer or run" broke three R37 tests | F2 acts only in the `defer` branch; a `run` stays with the `held` check |
| M3 | R37's retry sentence contradicted the amendment | both sentences revised |
| S1 | where to gate the echo was unstated | in `_decided`, gated on `decisions`; never in `_ticket_json` |
| S2 | no test for the no-`decisions` re-ask | requirement 3 and Testing add it |
| N1 | an existing test's expected entry | named in Testing |
