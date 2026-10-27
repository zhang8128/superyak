# Chat Paging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /api/chats/{key}` returns a page of a room instead of its whole history when asked, and `station_read` and the web app ask for pages.

**Architecture:** The station computes a room's message order from a light query (ids only), picks a window by position or by events seq, and reads full rows, sources and replies only for that window. Clients pass paging parameters and fall back to today's behaviour when the answer isn't paged. With no parameters, the answer is byte-identical to today's.

**Tech Stack:** Python 3.13, FastAPI, SQLite (peer); stdlib urllib (agent); vanilla JS (peer/superyak_peer/static/app.js); pytest and Playwright (`peer/tests/test_browser.py`).

**Spec:** `docs/superpowers/specs/2026-10-27-chat-paging-design.md` (revision 3, approved).

## Global Constraints

- No query parameters → the response is byte-identical to today's (same keys, same order, same values).
- Order key: `(created, source, rowid)` with local messages as source 0 and `peer_messages` as source 1.
- `limit` is 1 to 500; it defaults to 100 when another paging parameter is given.
- At most one of `before`, `at`, `start`, `after`, `since` (400 otherwise).
- A paged response adds `paged: true`, `total`, `first_position`, `seq`, and `more` on `since` reads only.
- `system_author` is room-wide on every page: present when any message in the room is by the system author.
- `since` returns the oldest `limit` matches by event id; `seq` is the last returned event id when `more` is true, otherwise the room's newest `chat.message` event id (0 if none).
- Remote rooms (key contains `:`) ignore paging and return today's answer.
- Index: `CREATE INDEX IF NOT EXISTS events_kind_resource ON events(kind, resource_id, id)`.
- `station_read` output, errors included, is identical to today's for the same room; `thread` keeps the full read.
- Run the peer suite with `cd peer && uv run --locked python -m pytest -q`, and the agent suite with `cd agent && uv run --locked --extra dev python -m pytest -q`.

## Review Focus

- An empty room: every paged read returns `messages: []`, `total: 0`, `first_position: 0`; `station_read` says `(no messages)`; the web app shows its empty state. Tests in Tasks 1 and 4.
- A non-member asking with parameters gets today's 404 and learns nothing (no `total` or `seq`). Test in Task 1.
- Garbage parameters (`limit=0`, `limit=501`, `at=-1`, `before=x`, two window parameters) get a 400, never a 500. Test in Task 1.
- An answer without `paged` (a remote room, or an older station) is used as the full room by both clients. Tests: Task 4's `pages = False` comparison and Task 5's remote room.
- A refresh never shows a message twice when it overlaps what's already shown (de-duplicated by id). Test in Task 5.

---

### Task 1: Server windows by position

**Files:**
- Modify: `peer/superyak_peer/chats.py` (`get_room`, new `_message_order`, `_page`)
- Modify: `peer/superyak_peer/tickets.py` (`_sources` takes `ids`), `peer/superyak_peer/inbox.py` (`_replies` takes `ids`)
- Modify: `peer/superyak_peer/app.py` (`chat_get` reads and validates the query)
- Test: `peer/tests/test_chat_paging.py` (new)

**Interfaces:**
- Produces: `Chats.get_room(actor: str, key: str, page: dict | None = None) -> dict`. `page` holds already-validated keys among `limit:int`, `before:int`, `at:int`, `start:str`, `after:str`, `since:int`; `None` or `{}` is today's path, unchanged.
- Produces: `Chats._message_order(db, key) -> list[tuple[str, int]]`: `(message_id, source)` in display order.
- Produces: `Chats._room_seq(db, key) -> int`.
- Produces: `_sources(db, room_id, ids=None)` and `_replies(db, room_id, ids=None)`: with `ids` (an iterable of message ids), only those messages; without, exactly as today.
- Errors: unknown `start` or `after` id → `Problem(404, 'No message in this room')`; `at` out of range → `Problem(400, f'at must be between 0 and {total - 1}')`; `before` above `total` → `Problem(400, f'before must be between 0 and {total}')`.

- [ ] **Step 1: Write the failing tests** in `peer/tests/test_chat_paging.py`, using the `env` fixture and a helper `fill(client, key, n)` that posts `n` messages with `client_message_id` `m{i}`, advancing `clock[0]` by 1 between posts:
  - `test_no_parameters_is_byte_identical`: build a room with local posts, two `peer_messages` rows (inserted as `test_chats.py` does, line 63), a claim note (`POST /api/chats/{key}/claims`) and a station notice (saving a brief with `PUT /api/chats/{key}/brief` posts one). Assert that the no-parameter response's JSON equals `app.state.store.get_room(user_id, key)` called with no `page`, and that it has none of `paged`, `total`, `first_position`, `seq`, `more`. The `page=None` path must stay today's code, untouched.
  - `test_limit_alone_returns_the_newest`: 30 messages, `?limit=10` → ids equal the full read's last 10, `paged is True`, `total == 30`, `first_position == 20`.
  - `test_before_at_start_after_windows`: 30 messages; `before=20&limit=5` → positions 15-19; `at=3&limit=4` → 3-6; `start=<id of 7>&limit=2` → 7-8; `after=<id of 7>&limit=2` → 8-9. Each checked against the full read's slice.
  - `test_local_and_peer_with_the_same_created_keep_todays_order`: a local message and a peer message with the same `created`, between others; for `at=0&limit=100`, `before=total&limit=100`, `start=<first id>`, the ids equal the full read's ids in the same order.
  - `test_empty_room_pages`: `?limit=5` → `messages == []`, `total == 0`, `first_position == 0`.
  - `test_bad_parameters_are_400`: `limit=0`, `limit=501`, `at=-1`, `before=x`, `at=1&before=2` → 400; `at=30` on a 30-message room → 400 with `'at must be between 0 and 29'` in the body.
  - `test_unknown_start_is_404_and_a_non_member_learns_nothing`: `start=nope` → 404; a non-member's `?limit=5` → 404 with today's body.
  - `test_system_author_is_room_wide`: a system notice at position 0 and 10 posts after it; `?limit=3` → `system_author` present.
- [ ] **Step 2: Run the tests and see them fail.** `cd peer && uv run --locked python -m pytest tests/test_chat_paging.py -q` → failures on missing `paged`/`total` and on 400s (parameters ignored today).
- [ ] **Step 3: Add `ids=None` to `_sources` and `_replies`.** With `ids`, add `AND messages.id IN (…)` to each of their room-scoped queries (the run sources, the kinds and the final message list in `_sources`; the join in `_replies`). Pages are at most 500, under SQLite's variable limit.
- [ ] **Step 4: Implement `_message_order`, `_room_seq` and the paged branch of `get_room`.** `_message_order` is one query: `SELECT id, 0 AS source, created, rowid FROM messages WHERE room_id=? UNION ALL SELECT id, 1, created, rowid FROM peer_messages WHERE room_id=? ORDER BY created, source, rowid`. The paged branch keeps the membership check and every room field from today's code, picks positions per the table in the spec, reads full rows for the picked ids from each table, attaches `source`/`reply_to` exactly as today (peer rows get `reply_to: None`), and sets `system_author` from `EXISTS (SELECT 1 FROM messages WHERE room_id=? AND author_id=?)`. A key with `:` ignores `page`.
- [ ] **Step 5: Parse the query in `app.py` `chat_get`.** Read `limit`, `before`, `at`, `start`, `after`, `since` from `request.query_params`; integers via `int()` with a 400 on failure; enforce the bounds and the one-window rule from Global Constraints; pass `page` only when at least one parameter is present.
- [ ] **Step 6: Run the new tests and the whole peer suite.** Both pass; `tests/test_chats.py` unchanged.
- [ ] **Step 7: Commit.** `git commit -m "Chat paging: the station returns a window of a room by position"`

### Task 2: Server `since`, `more` and the events index

**Files:**
- Modify: `peer/superyak_peer/chats.py` (the `since` branch of `get_room`)
- Modify: `peer/superyak_peer/db.py` (the index in `SCHEMA`)
- Test: `peer/tests/test_chat_paging.py`

**Interfaces:**
- Consumes: Task 1's `get_room(actor, key, page)`, `_message_order`, `_room_seq`.
- Produces: `page['since']` reads, with `more: bool` in the response.

- [ ] **Step 1: Write the failing tests:**
  - `test_since_returns_what_arrived_after_the_cursor`: 5 messages; read `?limit=1`, take `seq`; post 3 more; `?since=<seq>` → those 3 ids, `more is False`, `seq` equals the room's newest event id.
  - `test_since_sees_a_late_peer_message_with_an_older_created`: after taking `seq`, insert a `peer_messages` row with `created` earlier than every local message and emit `chat.message` for it (`store.emit(db, 'chat.message', key, epoch, {'message_id': …, 'author_id': …})`, as `federation.py` does); `?since=<seq>` → that message, with `first_position == 0`.
  - `test_since_pages_from_the_oldest_and_never_skips`: take `seq`, post 150; `?since=<seq>&limit=100` → the first 100 by arrival, `more is True`; `?since=<returned seq>&limit=100` → the remaining 50, `more is False`; together exactly the 150 ids, none repeated.
  - `test_since_with_nothing_new`: `?since=<newest seq>` → `messages == []`, `more is False`, `first_position == total`.
  - `test_the_events_index_exists`: `PRAGMA index_list(events)` names `events_kind_resource`.
- [ ] **Step 2: Run and see them fail** (`since` is accepted by Task 1's parser but not yet handled).
- [ ] **Step 3: Implement the `since` branch:** ids from `SELECT id, json_extract(payload, '$.message_id') FROM events WHERE kind='chat.message' AND resource_id=? AND id>? ORDER BY id`; take the first `limit` whose message is in the room's order (skip any that aren't, but count them toward advancing `seq`); `more` = rows remain after them; `seq` per Global Constraints; return the taken messages sorted by position. Add the index line to `SCHEMA` in `db.py`.
- [ ] **Step 4: Run the new tests and the whole peer suite.** All pass.
- [ ] **Step 5: Commit.** `git commit -m "Chat paging: since reads by events seq, oldest first, with more"`

### Task 3: The ship client and the test station

**Files:**
- Modify: `agent/superyak_agent/station.py` (`StationClient.room`)
- Modify: `agent/tests/conftest.py` (`FakeStation`: room GET applies paging; `self.pages = True` by default)
- Test: `agent/tests/test_station_paging.py` (new)

**Interfaces:**
- Produces: `StationClient.room(room_id: str, **page) -> dict`: `page` values that are not `None` go into the query string with `urllib.parse.urlencode`, in the order given; no `page` → today's exact request.
- Produces: `FakeStation.pages: bool`. When true, a room GET with parameters returns the same paged shape as the server (Global Constraints), computed from the room's in-memory `messages` list, whose order is the display order. When false, it behaves like an older station and ignores parameters. Errors match the server's messages and statuses.

- [ ] **Step 1: Write the failing tests:**
  - `test_room_without_page_sends_todays_request`: a recording transport sees `GET {base}/api/chats/{id}` with no query.
  - `test_room_with_page_sends_the_parameters`: `room(id, start='m1', limit=1)` → path ends `?start=m1&limit=1`.
  - `test_fake_station_pages_like_the_server`: for a 30-message room, `limit=10`, `before`, `at`, `start`, `after` and `since` give the same ids, `total`, `first_position`, `seq` and `more` as the rules in Global Constraints.
  - `test_fake_station_as_an_older_station_ignores_parameters`: with `pages = False`, `?limit=1` returns every message and no `paged`.
- [ ] **Step 2: Run and see them fail.** `cd agent && uv run --locked --extra dev python -m pytest tests/test_station_paging.py -q`
- [ ] **Step 3: Implement `room(**page)` and the fake's paging.** In the fake, keep the paging rules in one helper (`_page(room, query) -> dict`) next to `view`, with `seq` taken from a per-room counter that increments on every message the fake appends.
- [ ] **Step 4: Run the new tests and the whole agent suite.** All pass.
- [ ] **Step 5: Commit.** `git commit -m "Chat paging: StationClient.room passes a page; the test station pages like the station"`

### Task 4: `station_read` reads pages

**Files:**
- Modify: `agent/superyak_agent/mcp.py` (`station_read`, `render_newest`, `render_forward`, `render_one`)
- Test: `agent/tests/test_mcp.py`

**Interfaces:**
- Consumes: Task 3's `StationClient.room(room_id, **page)` and the paged response shape.
- Produces: `render_newest(room, messages, limit, chars, used=0, offset=0, total=None)`, `render_forward(room, messages, first, limit, chars, used=0, offset=0, total=None)` and `render_one(room, messages, position, offset=0)`. `offset` is the room position of `messages[0]` and `total` the room's message count (default `len(messages)`). Every printed position and every "earlier"/"more follow" count uses room positions, so output is unchanged.

- [ ] **Step 1: Write the failing tests:**
  - `test_each_read_mode_asks_for_a_page`: with a recording transport over the fake, the newest view requests `limit=<limit>`, `oldest=true` requests `at=0&limit=`, `at=5` requests `at=5&limit=`, `start=X` requests `start=X&limit=`, `after=X` requests `after=X&limit=`, `message=X` requests `start=X&limit=1`, and `thread=X` requests no parameters.
  - `test_paged_and_full_reads_print_the_same`: for a 40-message room with a brief, a system notice and a long message, every mode's output with `pages = True` equals its output with `pages = False`.
  - `test_errors_keep_todays_wording`: an unknown `start` id → `ValueError` whose text is today's (`No message '<id>' in this room`); `at=99` on a 40-message room → `at must be between 0 and 39`.
  - `test_an_empty_room_reads_no_messages`: the newest view of an empty room → `(no messages)` after the header.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.** `station_read` keeps its argument checks that need no room (types, `oldest` values, one mode at a time), asks for the page per the mode, and passes `offset=room['first_position']` and `total=room['total']` to the renderers when `room.get('paged')`; otherwise it keeps today's full-list path. It maps a `StationError` with status 404 or 400 from the room call to `ValueError` with today's wording. The brief opens a read only when the window starts at position 0, as today.
- [ ] **Step 4: Run the agent suite.** All pass, including every existing `test_mcp.py` read test unchanged.
- [ ] **Step 5: Commit.** `git commit -m "Chat paging: station_read asks for the window it shows"`

### Task 5: The web app opens on the newest hundred

**Files:**
- Modify: `peer/superyak_peer/static/app.js` (the opens at lines 1084, 1392 and 1416; the refreshes at 825, 1432, 1464 and 1479; the message list markup at 875)
- Test: `peer/tests/test_browser.py`

**Interfaces:**
- Consumes: Tasks 1 and 2's paged response.
- Produces: `loadRoom(id)` (opens with `?limit=100`), `loadEarlier()` (prepends `?before=<first_position>&limit=100`), and `refreshRoom(room)` (follows `?since=<seq>&limit=100` while `more`, keeps the shown messages, appends new ones de-duplicated by id, and takes every other room field from the answer). A non-paged answer replaces `state.room` as today.

- [ ] **Step 1: Write the failing browser tests** using `browser_peer`:
  - `test_a_long_room_opens_on_the_newest_hundred_and_loads_earlier`: a room with 150 messages opens showing 100 (`message 50` … `message 149`) and a "Load earlier messages" button; clicking it shows all 150 in order, and the button goes away.
  - `test_a_refresh_appends_a_new_message_once`: with the room open, another user posts; saving the brief (the 1479 path) shows that message exactly once.
  - `test_a_remote_room_still_opens`: a paired peer's room (as in the existing pairing browser test) opens and lists its messages.
- [ ] **Step 2: Run and see them fail.** `cd peer && uv run --locked python -m pytest tests/test_browser.py -k "newest_hundred or appends_a_new_message or remote_room_still_opens" -q`
- [ ] **Step 3: Implement** `loadRoom`, `loadEarlier` and `refreshRoom`, route the seven call sites through them, and render the button inside the messages section when `state.room.first_position > 0`. Keep the scroll position on prepend by restoring `scrollTop` by the change in `scrollHeight`.
- [ ] **Step 4: Run the whole peer suite, browser tests included.** All pass.
- [ ] **Step 5: Commit.** `git commit -m "Chat paging: the web app opens on the newest hundred and refreshes by since"`

## Verification and deploy (after Task 5)

- [ ] Both suites pass on the Mac; Rio Grande runs the peer and agent suites on the Pi (law section 2).
- [ ] Measure from the Mac, median of 5, before the merge (the Pi on main) and after the deploy: `GET /api/chats/{City of AI}` with no parameters, with `?limit=30`, and with `?limit=100`. Targets: `station_read` newest 30 below 400 ms; the web app's first paint below 600 ms.
- [ ] Deploy per the spec: back up the station database, restart `superyak-lighthouse`, check a no-parameter read is unchanged, a paged read works, and the web app opens City of AI. Rollback: revert the merge and restart; the index can stay.
