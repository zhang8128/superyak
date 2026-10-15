# Federation follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A received room's delivery state comes only from this station, and the browser shows the unverified mark.

**Architecture:** The server stops taking `state` from the origin and sets "delivered" itself on the viewer's own reply
once the origin's copy matches its outbox row. The browser stops guessing a received message's state from client ids
and labels an unverified message for what it is.

**Tech Stack:** Python (FastAPI peer, SQLite), vanilla JS, Playwright browser tests, pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-federation-followups-design.md`, revision 2, approved under D8 (443ef75).

**Status:** revision 2, for the same reviewer's re-check. Revision 1 (6816f43) had the fresh reviewer's verdict, APPROVE
WITH CHANGES (2 should-fix, 4 nits; room message bf8e0f3d): see "Review map".

## Global Constraints

- Nothing the origin sends becomes a state or a mark: `state` leaves `REMOTE_MESSAGE_KEYS`; `unverified` stays out.
- `"delivered"` is set only on a message verified against **the viewer's own** `room.reply` outbox row (author, client
  message id and body, first copy). Another local user's verified reply gets no state in this viewer's view.
- A queued reply keeps its outbox row's status (peer_store.py:79-86, unchanged).
- In a received room (`state.room.origin`) the browser uses only `message.state`, never the client-id match, and shows
  delivery text only when there is a state. A local room is unchanged.
- The unverified label is exactly "Unverified: the room's host says this is from someone on this station", static and
  escaped; the element gets the class `unverified`, styled `border: 1px dashed var(--muted); padding: 11px 14px;`.
- PROTOCOL.md gains the spec's sentence, with "the receiver" for "this station".
- No agent file changes; ships don't update.

## Review Focus

1. An honest echo whose outbox row is pending, failed or withdrawn after a lost acknowledgement: shows "Delivered" on
   the message (Task 1, test 4, with the row set to failed; the spec accepts the panel showing the row).
2. Two local users in one received room: each sees "delivered" only on their own reply (Task 1, test 3).
3. An origin that adds `unverified: true` to an honest echo: no mark (Task 1, test 2).
4. A received room with the user's own queued reply and a host message reusing its client id: the user's reply says
   "Delivered", the host's says nothing (Task 2's browser test).
5. A local room with remote members: delivery text unchanged (the existing browser tests in Task 2's suite run).

---

### Task 1: Server, a received message's state is this station's (F2 server, PROTOCOL.md)

**Files:**
- Modify: `peer/superyak_peer/peer_store.py` (`REMOTE_MESSAGE_KEYS`, `_remote_room`, `_unverified_local_authors`)
- Modify: `peer/PROTOCOL.md` (room.message, after "The receiver cannot detect either.")
- Test: `peer/tests/test_federation.py`: the four tests at the end of the file are already committed (5507c0e,
  dd76d28, 1e63b9b), red today. No test changes in this task.

**Interfaces:**
- Produces: a received room's messages carry `state: "delivered"` on the viewer's own verified reply, the outbox
  status on a queued reply, and no `state` otherwise. Task 2's browser relies on that.

- [ ] **Step 1: Run the red tests**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_federation.py`
Expected: 4 failed, 42 passed. The four:
- `test_an_origin_cannot_set_a_messages_delivery_state_or_mark`: `assert 'state' not in shown`;
- `test_this_stations_echoed_reply_shows_delivered_whatever_state_the_origin_adds`: `'failed' == 'delivered'`;
- `test_another_local_users_echoed_reply_carries_no_state_in_this_view`: `None == 'delivered'` (second assertion);
- `test_an_echoed_reply_shows_delivered_even_while_its_row_says_failed`: the echo has no `state`.

- [ ] **Step 2: The code**

In `peer/superyak_peer/peer_store.py`, replace

```python
REMOTE_MESSAGE_KEYS = ('id', 'room_id', 'author_id', 'client_message_id', 'body', 'epoch', 'created', 'state')
```

with

```python
# No `state` and no `unverified`: a received message's delivery state and mark are this station's word alone.
REMOTE_MESSAGE_KEYS = ('id', 'room_id', 'author_id', 'client_message_id', 'body', 'epoch', 'created')
```

In `_remote_room`, change `self._unverified_local_authors(replies, row['origin'], result['messages'])` to
`self._unverified_local_authors(replies, row['origin'], result['messages'], actor)`.

In `_unverified_local_authors`, change the signature to `def _unverified_local_authors(self, replies, origin,
messages, actor):`. Replace the docstring's whole final line,
`        message, and with a replayed copy it chooses which copy comes first (PROTOCOL.md, room.message)."""`,
with these three lines:

```python
        message, and with a replayed copy it chooses which copy comes first (PROTOCOL.md, room.message).
        A copy that stands and matches the viewer's own row shows "delivered": the origin holds those exact words, so
        the reply arrived even if its acknowledgement was lost. Another local user's copy stands with no state here."""
```

Replace

```python
        sent = set()
        for delivery in replies:
            local = json.loads(delivery['metadata'])['message']
            sent.add((local['author_id'], local['client_message_id'], local['body']))
```

with

```python
        sent = {}  # (author, client message id, body) -> whether the row is the viewer's
        for delivery in replies:
            data = json.loads(delivery['metadata'])
            local = data['message']
            sent[(local['author_id'], local['client_message_id'], local['body'])] = data['actor'] == actor
```

and replace

```python
            if reply in sent:
                sent.discard(reply)
            else:
```

with

```python
            if reply in sent:
                if sent.pop(reply):
                    message['state'] = 'delivered'
            else:
```

In `peer/PROTOCOL.md`, after the line `copy comes first and is shown as the reply. The receiver cannot detect either.`,
add:

```
A received message's delivery state is the receiver's alone: its own reply shows
delivered once the origin's copy matches its outbox row, a reply still queued
shows that row's status, and any state the origin sends is ignored. A second copy
of a verified reply is shown as unverified: it may be a replay, and the receiver
cannot tell a replay from a forgery.
```

- [ ] **Step 3: Run the tests**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_federation.py`
Expected: 46 passed.

- [ ] **Step 4: Mutation checks**, one at a time, each restored before the next (`git diff --stat` after each restore
  shows only your change):
  - put `'state'` back at the end of `REMOTE_MESSAGE_KEYS`: test 1 fails;
  - add `'unverified'` at the end of `REMOTE_MESSAGE_KEYS`: tests 1 and 2 fail;
  - replace `message['state'] = 'delivered'` with `pass`: tests 2 and 3 fail;
  - replace `= data['actor'] == actor` with `= True`: test 3 fails;
  - append ` and delivery['status'] == 'delivered'` to `= data['actor'] == actor`: test 4 fails.

- [ ] **Step 5: The peer suite**

Run: `make check-peer`. Expected: every test passes (the branch base's count plus 4 on this Mac: 539). Name any
failure.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/peer_store.py peer/PROTOCOL.md
git commit -m "Federation follow-ups F2, server: a received message's state is this station's, delivered only on the viewer's own proven reply"
```

---

### Task 2: Browser, the unverified mark and no guessed state (F1, F2 browser)

**Files:**
- Modify: `peer/superyak_peer/static/app.js` (`messageDelivery`, `messageMarkup`, a new constant)
- Modify: `peer/superyak_peer/static/app.css` (one rule after `.message.mine`)
- Modify: `peer/tests/test_browser.py` (the `browser_peer` fixture, an import, one new test at the end)

**Interfaces:**
- Consumes: Task 1's states (the browser test's own reply shows "Delivered" only because Task 1 leaves a queued
  reply's outbox status in place, and the host's message has no `state` because Task 1 drops it).

- [ ] **Step 1: The fixture and the test**

In `peer/tests/test_browser.py`:
- after `from urllib.error import HTTPError, URLError`, add `from urllib.parse import quote`;
- in `browser_peer`, make the stand-in station's user an admin, so it can pair back:

```python
    remote_user = remote_store.create_user(  # the stand-in station's admin, so it can pair back
        "casey", "Casey Remote", "long-remote-password", is_admin=True
    )
```

- keep the remote `Federation` as `remote_federation` and take the card from it:

```python
    remote_federation = Federation(
        remote_store,
        endpoint="https://remote.example:7443",
        identity=remote_identity,
    )
    remote_card = remote_federation.card(remote_user["id"])
```

- in the fixture's `yield {...}`, after `"remote_card": remote_card,`, add
  `"remote": {"store": remote_store, "federation": remote_federation, "user": remote_user},`.

Append at the end of the file:

```python
def test_a_received_room_marks_unverified_words_and_shows_only_this_stations_delivery_state(browser_peer):
    """Federation follow-ups (spec 2026-10-14-federation-followups-design.md), F1 and F2 in the browser. Words the
    room's host attributes to the signed-in person without proof read as unverified, never "You". A host's message that
    carries a delivery state and reuses the client id of the person's own delivered reply shows no delivery text."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    here, remote = browser_peer["app"].state.federation, browser_peer["remote"]
    there, casey, patient = remote["federation"], remote["user"]["id"], users["patient"]["id"]
    here.pair(users["organizer"]["id"], browser_peer["remote_card"])  # pairing is an admin's act, for the station
    card = Federation(store, endpoint="https://localhost:7435").card(patient)  # this station's identity, an endpoint
    contact = there.pair(casey, card)
    room = remote["store"].create_room(casey, "Hosted elsewhere", [contact["id"]])
    there.sync_once(send=lambda card, prepare: here.receive(prepare()))
    key = f"{there.identity.peer_id}:{room['id']}"
    store.send_message(patient, key, "reply-1", "my real words")
    here.sync_once(send=lambda card, prepare: there.receive(prepare()))  # delivered; the host never echoes it back

    def host_says(message_id, author_id, client_id, body, created, **extra):
        with remote["store"].transaction() as db:
            snapshot = there._room_snapshot(db, db.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone())
        message = {"id": message_id, "room_id": room["id"], "author_id": author_id, "client_message_id": client_id,
                   "body": body, "epoch": 1, "created": created, **extra}
        assert here.receive(there.identity.envelope(
            destination=here.identity.peer_id, actor=casey, resource_id=room["id"], revision=1,
            action="room.message", recipients=[patient], payload={**snapshot, "message": message}))["ok"]

    host_says("m-forged", f"{here.identity.peer_id}:{patient}", "forged-1", "I approve the merge", 5.0)
    host_says("m-claims", f"{there.identity.peer_id}:{casey}", "reply-1", "the host's own words", 6.0,
              state="delivered")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Connections", exact=True).click()
            # The person's reply is delivered and the page knows it, so a client-id guess would find it.
            expect(page.locator(".item-main", has_text="Hosted elsewhere").get_by_text("Send reply · Delivered")).to_be_visible()
            page.goto(f"{base}/#chats/{quote(key, safe='')}")
            page.reload()
            forged = page.locator(".message", has_text="I approve the merge")
            expect(forged.locator(".message-meta").first).to_have_text(
                "Unverified: the room's host says this is from someone on this station")
            expect(forged).to_have_class("message unverified")
            expect(forged.locator(".message-meta").last).not_to_contain_text("Delivered")
            expect(forged.locator(".message-meta").last).not_to_contain_text("Saved here")
            claims = page.locator(".message", has_text="the host's own words")
            expect(claims).to_be_visible()
            expect(claims.locator(".message-meta").first).not_to_contain_text("Unverified")
            expect(claims).to_have_class("message")
            expect(claims.locator(".message-meta").last).not_to_contain_text("Delivered")
            expect(claims.locator(".message-meta").last).not_to_contain_text("Saved here")
            mine = page.locator(".message", has_text="my real words")
            expect(mine.locator(".message-meta").first).to_have_text("You")
            expect(mine.locator(".message-meta").last).to_contain_text("Delivered")
```

Notes: pairing is an admin's act, so the browser side pairs as the organizer; the received room belongs to the patient.
The browser app's own federation has no endpoint, so the card for the remote side comes from a second `Federation` on
the same store (same identity) with an endpoint, as test_federation.py's peers use.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_browser.py -k received_room_marks_unverified`
Expected: FAIL at the label: `Locator expected to have text 'Unverified: the room's host says this is from someone on
this station'`, got `"Someone in this chat"`.

- [ ] **Step 3: The code**

In `peer/superyak_peer/static/app.js`, in `messageDelivery`, after `if (message.state) return message.state;` add:

```javascript
  if (state.room?.origin) return null;  // a received room: only the station's own state, never a guess from client ids
```

Right before `function messageMarkup(message) {` add:

```javascript
// The server's mark for words a room's host attributes to someone on this station that this station never sent.
const UNVERIFIED_AUTHOR = "Unverified: the room's host says this is from someone on this station";

```

In `messageMarkup`, replace the `const author = ...` line and the `return` line with:

```javascript
  const author = mine ? "You" : system && message.author_id === system.id ? "Station" : message.unverified ? UNVERIFIED_AUTHOR : participantName(message.author_id);
  const delivery = messageDelivery(message);
  return `<div class="message${mine ? " mine" : ""}${message.unverified ? " unverified" : ""}"><div class="message-meta">${escapeHtml(author)}${sourceLabel(message) ? ` · <span class="message-source">${escapeHtml(sourceLabel(message))}</span>` : ""}</div><p>${escapeHtml(message.body)}</p><div class="message-meta">${formatDate(message.created)}${delivery ? ` · ${escapeHtml(deliveryText(delivery))}` : ""}</div></div>`;
```

In `peer/superyak_peer/static/app.css`, after the `.message.mine { ... }` line add:

```css
.message.unverified { border: 1px dashed var(--muted); padding: 11px 14px; }
```

- [ ] **Step 4: Run it, then the peer suite**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_browser.py -k received_room_marks_unverified`.
Expected: PASS.
Run: `make check-peer`. Expected: every test passes (540 on this Mac). Name any failure, especially in
test_browser.py's chat and delivery tests.

- [ ] **Step 5: Mutation checks**, each restored before the next:
  - delete the `if (state.room?.origin) return null;` line: the new test fails at `not_to_contain_text("Delivered")`;
  - replace ` : message.unverified ? UNVERIFIED_AUTHOR : ` with ` : ` in the `author` line: the new test fails at the
    label;
  - replace ` : message.unverified ? UNVERIFIED_AUTHOR : ` with ` : !mine ? UNVERIFIED_AUTHOR : ` (every message not the
    viewer's labelled unverified): the new test fails at the host message's author line;
  - in peer_store.py, add `message['state'] = 'delivered'` after `message['unverified'] = True` (a state on the
    unverified copy): the new test fails at the forged message's `not_to_contain_text("Delivered")`.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/static/app.js peer/superyak_peer/static/app.css peer/tests/test_browser.py
git commit -m "Federation follow-ups F1 and F2, browser: the unverified mark, and no guessed state in a received room"
```

---

## Deploy (Rio Grande, after the merge under law section 2)

1. Back up the database, merge with `--no-ff`, push, then restart the lighthouse (it serves app.js and runs the peer;
   restarting after the push keeps the version check on). Check the journal.
2. Ships need nothing: no agent file changes.
3. Announce it.

## Self-review notes

- **Spec coverage:** F2 server and requirements 1-5 and 8: Task 1. F1, F2 browser and requirements 6-7: Task 2.
- **Dry run:** revision 1's blocks were applied as written in a scratch worktree (the plan reviewer reproduced them at
  6816f43); revision 2's at 1e63b9b.
  - Task 1: RED 4 failed and 42 passed; GREEN 46; the five mutations each fail exactly the tests named.
  - Task 2: RED fails at the label ("Someone in this chat"); GREEN passes; all four mutations fail the new test.
  - `make check-peer`: 540 passed (the branch base's 535 on this Mac, plus 4 federation, plus 1 browser).

## Review map (revision 2: the plan review of 6816f43)

| # | Finding | Change |
|---|---|---|
| S1 | no test pinned "no state on an unverified message" | the browser test checks the forged message shows neither "Delivered" nor "Saved here"; Task 2's third new mutation |
| S2 | the host message's author line was unchecked | the browser test checks it isn't "Unverified" and its class is exactly `message`; Task 2's second new mutation |
| N3 | Review Focus 1 claimed but untested | test 4 (1e63b9b): an honest echo while the row says failed shows "delivered"; Task 1's fifth mutation |
| N4 | the docstring edit was ambiguous | "replace the docstring's whole final line", quoted |
| N5 | the dry run's base | revision 2's dry run at 1e63b9b |
| N6 | the class string | no change: harmless, and the test pins the exact strings |
