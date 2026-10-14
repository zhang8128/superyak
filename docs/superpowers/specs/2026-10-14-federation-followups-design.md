# Federation follow-ups: the unverified mark in the browser, and delivery state only from this station

Status: revision 2, for the same reviewer's re-check. Revision 1 (5507c0e) had the fresh reviewer's verdict, APPROVE
WITH CHANGES (4 should-fix, 5 nits; room message 98d2778d): see "Review map". Base: `main` (3b48646). Branch
`federation-followups`. Roadmap phase 4, claimed by Serenity as `fix:federation-followups`. Both items are the
follow-ups left by the merge of federation-own-author (d15ab04): "the browser doesn't show the unverified mark, and a
remote message's state should come only from the local outbox."

## Where this sits

A station can pair with another station and receive rooms that the other one hosts (the origin). The origin orders and
timestamps its own room and can say anything in it. Since d15ab04 it can't put words in a local user's mouth: a message
attributed to one of this station's users stands only when it matches a reply this station sent (its `room.reply`
outbox row: author, client message id and body), and only the first copy. Anything else is rewritten to
`<origin>:(unverified)` with `unverified: true` (peer_store.py:102-124). Two gaps remain, and a paired station is a
neighbour in the city, so both are about whose word a person reads.

## F1. The browser shows the unverified mark

- **Gap:** the server marks the message, but the browser ignores `unverified`. `messageMarkup` (app.js:513-518) names
  the author with `participantName` (app.js:458-464), which finds no contact for `<origin>:(unverified)` and shows
  "Someone in this chat", the same as any unknown member. Nothing tells the reader that the room's host attributed
  these words to someone on this station (another local user, or the reader, after an outbox loss or a restore) and
  this station couldn't prove it.
- **Fix:**
  - When `message.unverified` is true, the author line reads **"Unverified: the room's host says this is from someone
    on this station"**, static and escaped as today.
  - The message element gets the class `unverified`, styled in app.css as `.message.unverified { border-style:
    dashed; }`.
  - `mine` stays false (the author id matches no local user). The label comes only from the server's flag, and F2's
    allowlist keeps an origin from setting it.

## F2. A received message's delivery state comes only from this station

- **Gap 1, the origin sets it:** `REMOTE_MESSAGE_KEYS` (peer_store.py:9) passes `state` through from the origin's
  payload, and `receive()` stores a message with any extra keys (federation.py:362-368). The browser shows
  `message.state` first (app.js:474). An origin that adds `state: "failed"` to an echo of a reply this station
  delivered makes this station's browser show "Failed to send"; `"delivered"` on its own words shows them as delivered.
- **Gap 2, the browser guesses it:** an honest echo carries no state, so `messageDelivery` matches it against all of
  this user's deliveries by message id **or client message id** (app.js:475). The client id is chosen by whoever wrote
  the message. An origin message, or another member's, whose client id equals one of this user's deliveries takes that
  delivery's status.
- **Fix, on the server** (`_remote_room` and `_unverified_local_authors`):
  - `state` leaves `REMOTE_MESSAGE_KEYS` (`unverified` stays out of it), so nothing the origin sends becomes a state or
    a mark.
  - `_unverified_local_authors` gains the viewer (`actor`). A message it verifies against one of **the viewer's own**
    outbox rows gets `state: "delivered"`. The origin holds words that match the row exactly, which proves delivery
    even when the row still says pending or failed because an acknowledgement was lost, or withdrawn after one was
    (the case peer_store.py:77-78 already names). Another local user's verified reply keeps its author and gets no
    state in this viewer's view: it is that user's outbox, not this viewer's.
  - A queued reply with no copy from the origin keeps its outbox row's status, as today (peer_store.py:79-86).
  - Every other received message carries no `state`.
- **Fix, in the browser:**
  - In a received room (`state.room.origin` set), `messageDelivery` returns `message.state`, or nothing, and never
    matches deliveries.
  - `messageMarkup` shows the delivery text only when there is a state. In a received room the viewer's own messages
    always have one (delivered, or the queued row's status), and other people's messages show none instead of "Saved
    here".
  - A local room keeps today's matching and text: its messages and deliveries are all this station's own.
- **PROTOCOL.md** (room.message, after the verified/unverified sentence, :132-139) gains: "A received message's
  delivery state is the receiver's alone: its own reply shows delivered once the origin's copy matches its outbox row,
  a reply still queued shows that row's status, and any state the origin sends is ignored. A second copy of a verified
  reply is shown as unverified: it may be a replay, not tampering."

## Requirements

1. An origin's `state` on any message never reaches this station's room view, and neither does its `unverified` (peer
   tests 1 and 2: the `state` half is red today; `unverified` is already outside the allowlist, and test 2 pins that).
2. The viewer's verified reply shows `state: "delivered"`, whatever state or mark the origin adds (test 2, red today).
3. Another local user's verified reply carries no state in this viewer's view, and `"delivered"` in that user's own
   (test 3, red today on the second half).
4. A queued reply keeps its outbox status; the existing federation tests stay green.
5. A received message that isn't the viewer's own verified or queued reply has no `state`.
6. In the browser, a received room's unverified message reads "Unverified: the room's host says this is from someone
   on this station" and is never "You". An origin message that carries `state: "delivered"` and reuses the client id
   of one of this user's delivered replies shows no delivery text: neither "Delivered" nor "Saved here".
7. A local room's delivery text is unchanged (the existing browser tests stay green, among them
   `test_pairing_pending_delivery_and_peer_wide_disconnect_states` and
   `test_delivery_waiting_acknowledgement_refresh_and_unsaved_state`).
8. PROTOCOL.md carries the sentence above.

## Testing

- **Peer**, in test_federation.py, all red today:
  1. `test_an_origin_cannot_set_a_messages_delivery_state_or_mark`: the origin's own message with `state` and
     `unverified` added;
  2. `test_this_stations_echoed_reply_shows_delivered_whatever_state_the_origin_adds`: the viewer's reply, first copy
     from the origin with `state: "failed"` and `unverified: true` added;
  3. `test_another_local_users_echoed_reply_carries_no_state_in_this_view`: two local users in one received room.

  The helper `_forged_message` gains `**extra` (keys the origin adds) and accepts a full participant id as `author`;
  the 42 existing federation tests pass with it.
- **Browser**, one test in test_browser.py:
  - It writes a paired peer and a received room into the browser peer's store. The room holds one message forged as
    the signed-in user's, and one origin message with `state: "delivered"` whose client id is that of a delivered
    `room.reply` outbox row.
  - The outbox row must pass `federation.status`'s filter (`_delivery_authority`). So the test makes it with the
    store's own `remote_send`, marks it delivered, and checks that the page lists that delivery before it checks the
    room. Otherwise the guard's mutation could pass for the wrong reason.
  - The assertions are scoped to each message's element: the user's own queued reply, also shown, says "Delivered"
    rightly.
  - Browser tests run on the Mac (Playwright, 3.5 s for one) and on the Pi.
- **Mutation checks:**
  - put `state` back in `REMOTE_MESSAGE_KEYS`: test 1 fails;
  - put `unverified` in `REMOTE_MESSAGE_KEYS`: test 2 fails;
  - drop the `"delivered"` assignment: tests 2 and 3 fail;
  - drop the viewer check (any local row counts): test 3 fails;
  - remove the `origin` guard in `messageDelivery`: the browser test's no-delivery-text check fails;
  - remove the `unverified` branch in `messageMarkup`: the browser test's label check fails.

## Security

- Every change narrows what a paired origin controls: no key it sends becomes a state or a mark, and the browser stops
  inferring state from client ids the origin chooses.
- `"delivered"` is set only for a message already proven against the viewer's own outbox row, which is the proof
  d15ab04 uses for authorship. An origin can earn it only by echoing words it really received.
- The label is static text; the author line is escaped as today.

## Changed files and deploy

peer_store.py, app.js, app.css, PROTOCOL.md, test_federation.py, test_browser.py. Restart the lighthouse (it serves
app.js and runs the peer). Ships don't need to update: no agent file changes.

## Known limits

- The delivery panel (`resourceDelivery`, app.js:551 and :597) reads the outbox rows as they are. A verified echo whose
  row is still pending or failed shows "Delivered" on the message and the row's status in the panel, until the retry
  gets its acknowledgement. The row is left alone: it is the outbox's own record, and the echo is the better evidence
  of arrival.
- Right after sending, the browser shows the `pending` state `remote_send` returned (app.js:1205-1206) until the next
  read. Unchanged.
- Ships reading a received room see no member names: a received room's members carry only `{peer, id}`. Unchanged,
  and outside this fix.
- The origin still orders and timestamps its own room and chooses which copy of a replay comes first (PROTOCOL.md,
  room.message). Unchanged.

## Review map (revision 2: the D8 review of 5507c0e)

| # | Finding | Change |
|---|---|---|
| S1 | the delivery panel contradicts the message | a Known limit: the row is left alone, the echo is the better evidence |
| S2 | the label framed the host as the speaker | "Unverified: the room's host says this is from someone on this station"; "their people" fixed |
| S3 | "Saved here" on everyone else's messages | in a received room, delivery text only when there is a state |
| S4 | PROTOCOL.md not updated | the sentence, with the replay note; PROTOCOL.md in the changed files |
| N5 | another local user's reply marked delivered | `delivered` only for the viewer's own rows; test 3 |
| N6 | the class had no style | a dashed border in app.css |
| N7 | the guard's test could pass for the wrong reason | the row made with `remote_send`; the page lists it before the room is checked |
| N8 | `unverified` in the allowlist wasn't caught | test 2 adds `unverified: true`; its own mutation |
| N9 | the pending state until refresh | a Known limit, unchanged |
| refs | 77-86 and 463 loose | 79-86; 458-464 |
