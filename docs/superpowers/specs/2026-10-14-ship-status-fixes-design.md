# Ship status fixes: three follow-ups from the re-review of 5374784

Status: revision 1, for a fresh reviewer under D8. Base: `main` (e633ec3). Branch `ship-status-fixes`. Roadmap phase 4
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
  - A hand-listed entry was never charged: a hand-edited state file, or a list carried over from an older watcher.
  - If the station's first answer to it is `defer`, the watcher keeps waiting. The station's eventual run carries
    `first_deferred`, which spares it under R37, so the mention is never charged at all.
- **Test:** `test_a_hand_listed_entry_the_station_then_defers_is_charged_once` fails today: 0 charges.
- **Fix (the watcher):**
  - When the watcher puts a mention on its list after the station's `defer` answer, the entry records that answer's
    `first_deferred` (`entry['first_deferred']`). That records that this watcher charged the mention at entry.
  - A listed entry **without** a recorded `first_deferred` is charged at the station's first answer to it, whether
    `defer` or `run`.
    - Over budget, it gets the pause note, its ticket is finished if one was issued, and it leaves the list, as an
      over-budget new mention does today.
    - Within budget, a `defer` answer records `first_deferred` on the entry, so it isn't charged again.
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
- **Test:** `test_a_lost_run_response_for_a_deferral_the_station_held_is_not_charged_again` fails today: no run.
- **Fix (the station; the watcher is unchanged):**
  - The `tickets` table gains a nullable `first_deferred REAL` column. It's added at startup with db.py's existing
    `PRAGMA table_info` / `ALTER TABLE ADD COLUMN` pattern (db.py:64-74).
  - When the station issues a run that resolves a deferral it held, it writes that row's `first_deferred` to the
    ticket.
  - Whenever the station returns a running ticket to a watcher that asked for decisions, the answer carries the
    ticket's `first_deferred` if it has one: on issue, as today, and on every re-send.
  - So the retry is spared on the station's word, under R37 as written. R37's text gains one clause: "...a run that
    resolves a deferral it held carries `first_deferred`, **including when the station sends that running ticket
    again**".
- **Why not the post's suggestion** (spare on the `first_deferred` recorded in the entry): that would spare because
  the watcher's state says so, which R37 forbids. A hand-edited entry could then dodge the budget. F2 records the
  value only to charge.

## Requirements

1. F1's test passes; `get_room` and `list_rooms` keep every valid member of a hand-edited payload.
2. F2's test passes: one charge for the hand-listed entry. A hand-listed entry over budget gets the pause note and
   leaves the list. A normally listed entry, charged at entry with `first_deferred` recorded, is never charged again
   (the existing R37 tests stay green).
3. F3's test passes, with no change to the watcher. A station test shows that a re-sent running ticket from a deferral
   carries `first_deferred`, and that one not from a deferral carries none.
4. The column migration is additive. It's idempotent on an existing database (run twice, one column). An old binary on
   the migrated database ignores the column, so a rollback to main keeps working.
5. Without `decisions`, every answer stays exactly today's (R23).

## Security

- The budget protects a ship from other ships' floods. Every change only adds charges or spares on the station's
  word. No local state can create a spare.
- The column holds the station's own timestamp. No client value is written to it.

## Testing

- **Peer:**
  - F1's test;
  - a ticket test: issue from a deferral, then re-ask, and the same running ticket carries `first_deferred`; a ticket
    not from a deferral carries none, also on re-send;
  - a migration test: a database without the column gains it once, and a second start changes nothing.
- **Agent:**
  - F2's and F3's tests;
  - the existing R37 tests unchanged;
  - an over-budget hand-listed entry gets the pause note.
- **Mutation checks:**
  - F2: the "record on defer" line removed, so a normally listed entry is charged twice;
  - F3: the re-send without `first_deferred`, so F3's test fails.

## Deploy

Restart the lighthouse, which runs the migration, and the ship watcher, with the usual backup first. Ships pick up F2 by
pulling main: it's a change to `agent/superyak_agent/watch.py`, a runtime file, so the version check will prompt them.

## Known limits

- An entry a watcher listed before this change has no recorded `first_deferred`, so F2 charges it once more after the
  update, at its next station answer. That's one extra charge per mention already deferred at upgrade time. It fails
  toward charging, and only once.
