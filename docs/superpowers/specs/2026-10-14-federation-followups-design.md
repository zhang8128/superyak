# Federation follow-ups: the unverified mark in the browser, and delivery state only from this station

Status: revision 1, for a fresh reviewer under D8. Base: `main` (3b48646). Branch `federation-followups`. Roadmap
phase 4, claimed by Serenity as `fix:federation-followups`. Both items are the follow-ups left by the merge of
federation-own-author (d15ab04): "the browser doesn't show the unverified mark, and a remote message's state should
come only from the local outbox."

## Where this sits

A station can pair with another station and receive rooms that the other one hosts (the origin). The origin orders and
timestamps its own room and can say anything in it. Since d15ab04 it can't put words in a local user's mouth: a message
attributed to one of this station's users stands only when it matches a reply this station sent (its `room.reply`
outbox row: author, client message id and body), and only the first copy. Anything else is rewritten to
`<origin>:(unverified)` with `unverified: true` (peer_store.py:102-124). Two gaps remain, and a paired station is a
neighbour in the city, so both are about whose word a person reads.

## F1. The browser shows the unverified mark

- **Gap:** the server marks the message, but the browser ignores `unverified`. `messageMarkup` (app.js:513-518) names
  the author with `participantName`, which finds no contact for `<origin>:(unverified)` and shows "Someone in this
  chat" (app.js:463), the same as any unknown member. Nothing tells the reader that the room's host attributed these
  words to one of their people and this station couldn't prove it.
- **Fix:** when `message.unverified` is true, the author line reads **"The room's host · unverified"**, and the message
  element gets the class `unverified`. `mine` stays false (the author id matches no local user). The label comes only
  from the server's flag. F2's allowlist keeps an origin from setting it.

## F2. A received message's delivery state comes only from this station

- **Gap 1, the origin sets it:** `REMOTE_MESSAGE_KEYS` (peer_store.py:9) passes `state` through from the origin's
  payload, and `receive()` stores a message with any extra keys (federation.py:362-368). The browser shows
  `message.state` first (app.js:474). An origin that adds `state: "failed"` to an echo of a reply this station
  delivered makes this station's browser show "Failed to send"; `"delivered"` on its own words shows them as this
  person's delivered message. Red test: `test_this_stations_echoed_reply_shows_delivered_whatever_state_the_origin_adds`
  fails with `'failed' == 'delivered'`.
- **Gap 2, the browser guesses it:** an honest echo carries no state (red test above, before the origin adds one), so
  `messageDelivery` matches it against all of this user's deliveries by message id **or client message id**
  (app.js:475). The client id is chosen by whoever wrote the message. An origin message, or another member's, whose
  client id equals one of this user's deliveries takes that delivery's status.
- **Fix, on the server** (`_remote_room` and `_unverified_local_authors`):
  - `state` leaves `REMOTE_MESSAGE_KEYS` (and `unverified` stays out of it), so nothing the origin sends becomes a
    state or a mark. Test: `test_an_origin_cannot_set_a_messages_delivery_state_or_mark`, red today.
  - A message that `_unverified_local_authors` verifies against an outbox row (this station's reply, first copy) gets
    `state: "delivered"`: the origin holds words that match the row exactly, which proves delivery even when the row
    still says pending or failed because an acknowledgement was lost, or withdrawn after one was (the case
    peer_store.py:77-78 already names).
  - A queued reply with no copy from the origin keeps its outbox row's status, as today (peer_store.py:80-86).
  - Every other received message carries no `state`.
- **Fix, in the browser:** in a received room (`state.room.origin` set), `messageDelivery` returns `message.state` or
  `"saved"` and never matches deliveries. A local room keeps today's matching: its messages and deliveries are all
  this station's own.

## Requirements

1. An origin's `state` or `unverified` on any message never reaches this station's room view (peer test, red today).
2. This station's verified reply shows `state: "delivered"`, whatever state the origin adds (peer test, red today).
3. A queued reply keeps its outbox status; the existing federation tests stay green.
4. A received message that isn't this station's verified or queued reply has no `state`.
5. In the browser, a received room's unverified message reads "The room's host · unverified" and is never "You"; an
   origin message that carries `state: "delivered"` and reuses the client id of one of this user's delivered replies
   reads "Saved here", not "Delivered" (browser test).
6. A local room's delivery text is unchanged (the existing browser tests stay green, among them
   `test_pairing_pending_delivery_and_peer_wide_disconnect_states` and
   `test_delivery_waiting_acknowledgement_refresh_and_unsaved_state`).

## Testing

- **Peer:** the two red tests above, in test_federation.py. The helper `_forged_message` gains `**extra` (keys the
  origin adds) and accepts a full participant id as `author`; the 42 existing federation tests pass with it.
- **Browser:** one test in test_browser.py. It writes a paired peer and a received room into the browser peer's store,
  holding one message forged as the signed-in user's, and one origin message with `state: "delivered"` whose client id
  is that of a delivered `room.reply` outbox row the test also writes. Today the second reads "Delivered" by either
  path (the origin's key or the client-id guess), so each half of F2 has a mutation the test catches. It then checks
  the room's text. Browser tests run on the Mac (Playwright, 3.5 s for one) and on the Pi.
- **Mutation checks:**
  - put `state` back in `REMOTE_MESSAGE_KEYS`: requirement 1's test fails;
  - drop the `"delivered"` assignment: requirement 2's test fails;
  - remove the `origin` guard in `messageDelivery`: the browser test's "Saved here" check fails;
  - remove the `unverified` branch in `messageMarkup`: the browser test's label check fails.

## Security

- Every change narrows what a paired origin controls: no key it sends becomes a state or a mark, and the browser stops
  inferring state from client ids the origin chooses.
- `"delivered"` is set only for a message already proven against this station's own outbox row, which is the proof
  d15ab04 uses for authorship.
- The label is static text; the author line is escaped as today.

## Deploy

Restart the lighthouse (it serves app.js and runs the peer). Ships don't need to update: no agent file changes.

## Known limits

- Ships reading a received room see no member names: a received room's members carry only `{peer, id}`. Unchanged,
  and outside this fix.
- The origin still orders and timestamps its own room and chooses which copy of a replay comes first (PROTOCOL.md,
  room.message). Unchanged.
