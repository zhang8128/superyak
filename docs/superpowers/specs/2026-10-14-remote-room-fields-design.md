# Remote room fields: a received room's linked room and activity are checked

Status: revision 1, for a fresh reviewer under D8. Base: `main` (3620203). Branch `remote-room-fields`. Claimed by
Serenity as `fix:remote-room-fields`. These are the two pre-existing items the section 2 review of
federation-followups (96030b0) declined to judge and Rio Grande assigned as a follow-up (room message 29a10301):
"linked_room_id isn't validated when a room is received... an unhashable value would break Wormhole" and
"last_activity can be as large as 2^53, so an origin can pin its room to the top of the chat list".

## Where this sits

A paired station (the origin) sends a room snapshot with every `room.roster` and `room.message` event:
`{title, owner_id, member_ids, members, linked_room_id, created, last_activity}` (federation.py:85). The receiver checks
the title, the roster, the owner and the two timestamps' range (federation.py:318-336), then stores the snapshot. The
view (`_remote_room`, peer_store.py) passes `REMOTE_ROOM_KEYS` through, including `linked_room_id` and
`last_activity`, and sets the room's `last_activity` to the largest of the snapshot's and its messages' `created`
(peer_store.py:102). Two gaps:

1. **`linked_room_id` is never checked.** An honest origin sends `None` or `<origin>:<its earlier room id>` (federation.py:85).
   A hostile one can send a list or a dict (Wormhole's `_bridged` builds a set from every room's `linked_room_id`,
   wormhole.py:93, and an unhashable value raises), or the id of one of this station's own rooms, or another station's
   room: a claim to replace a room the origin doesn't host. Wormhole skips a room that another room replaces, so a
   received room naming a local room would hide that local room from the bridge.
2. **The origin chooses the activity.** `last_activity` and each message's `created` may be anything from 0 to 2^53
   (federation.py:331-334, 343-344), and the chat list sorts on `last_activity` (chats.py:40). A hostile origin can pin
   its room to the top of every member's list for good, with a far-future date beside it (app.js:615).

Measured on main with seven peer tests, all red today (peer/tests/test_federation.py, uncommitted on this branch): six
cases of `test_a_received_rooms_linked_room_is_its_origins_own_or_none` (a list, a dict, a number, a bare id, another
station's room, a local room) fail with "DID NOT RAISE", and `test_a_received_room_cannot_claim_activity_after_it_arrived`
fails with `9007199254740992 <= <now>`.

Exposure today is nil: the Pi has no paired peers (Rio Grande counted, read-only). Wormhole would need to be a member
of a received room, and a ship's pairing card comes only from the CLI.

## The change

- **F1, `linked_room_id` at receive.** For `room.roster` and `room.message`, the snapshot's `linked_room_id` must be
  `None` or a string `<origin>:<id>`, where `<origin>` is the envelope's origin and `<id>` matches `[A-Za-z0-9_-]{1,64}`.
  Anything else is refused with 400 ("Invalid linked room"), as the other snapshot checks are.
- **F1, the view's backstop.** `_remote_room` keeps a stored `linked_room_id` only if it meets the same rule (with the
  inbox row's origin); otherwise the view shows `None`. That covers whatever an older receiver stored before F1.
- **F2, this station's own receive time.** A new table, `inbox_received(origin, resource_id, recipient, received
  REAL, PRIMARY KEY(origin, resource_id, recipient))`, records this station's clock each time it stores a room event's
  snapshot for that recipient. It's written in the same transaction as the inbox row.
  - It is a separate table, not a column, on purpose: `inbox` is written with a positional `INSERT` (federation.py:371),
    so an added column would break a rollback to main's code. A new table is ignored by old code.
  - At startup, `CREATE TABLE IF NOT EXISTS`, then a one-time backfill: every stored room row without an
    `inbox_received` row gets one with `received` = now. An honest room's activity is already in the past, so its order
    doesn't change; a room pinned before the upgrade drops to the upgrade time.
- **F2, the clamp.** In the view, the activity the origin claims (the snapshot's `last_activity` and its messages'
  `created`) counts only up to `received`. This station's own queued replies still count at their own time. So:
  `last_activity = max(min(origin's activity, received), this station's queued replies' created)`. With no
  `inbox_received` row (only possible between an older receive and the backfill), the view keeps today's value.
- **Unchanged:** a message's `created` as shown inside the room and the room's message order. The origin still orders
  and timestamps its own room (PROTOCOL.md, room.message, Known limit). Only the list's sort key and the date beside
  it are clamped.

## Requirements

1. A received room's `linked_room_id` that is a list, a dict, a number, a string without the origin's prefix, another
   station's room, or a local room's id is refused at receive (tests: the six cases, red today).
2. An honest linked room (an origin adding a member, which makes a new linked room) is still received, and the view
   shows `<origin>:<earlier id>` (a guard test).
3. A stored `linked_room_id` that breaks the rule shows as `None` in the view, and `list_rooms` works (a guard test
   that writes one straight into the inbox).
4. A received room claiming `last_activity` or a message `created` of 2^53 lists with `last_activity` no later than
   when this station received it, in `list_rooms` and in `get_room` (red today).
5. An honest received room's `last_activity` is unchanged (its claims are already in the past): the existing
   federation tests stay green.
6. This station's own queued reply in a received room still moves the room to its own time (a guard test).
7. The migration is additive and idempotent, and main's code runs on the migrated database (a test: start twice, one
   table; main's federation receive still works on it).

## Testing

- **Peer:** the seven red cases; the three guards (honest linked room; a stored bad `linked_room_id`; a queued reply's
  time); the migration test. The full peer suite.
- **Mutation checks:**
  - drop the origin-prefix check: the `another-station` and `a-local-room` cases fail;
  - drop the type check: the list, dict and number cases fail;
  - drop the view's backstop: the stored-value guard fails;
  - drop the clamp: the 2^53 test fails;
  - clamp the queued replies too: the queued-reply guard fails;
  - write `received` only on `room.message`: the 2^53 test fails at the roster's `last_activity`.

## Security

- Every change narrows what a paired origin controls: no value it sends can name a room it doesn't host or break a
  reader that builds a set from the field, and no value it sends can move its room ahead of when it really arrived.
- `received` is this station's clock alone. No client value is written to it.

## Deploy

Back up the database (the new table), merge, push, then restart the lighthouse (the table and backfill run at start).
Check the journal and `grep 'version check'`. Ships need nothing: no agent change.

## Known limits

- An origin that delivers often still sits near the top: each delivery is real activity on this station.
- Message `created` inside a room, and the order the origin gives its messages, stay the origin's (PROTOCOL.md).
- After a rollback to main and a later return, `inbox_received` rows written before the rollback are stale (older);
  the clamp then holds a room's activity at its last receive under the new code until its next event. Harmless.
