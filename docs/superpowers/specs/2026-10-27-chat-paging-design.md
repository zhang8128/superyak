# Chat paging: read a room's newest messages, not its whole history

Serenity, 2026-10-27. Branch `chat-paging`. Shaped with Rio Grande in "Superyak: all hands" (messages 3edb9d1e,
04ab129f, 951270a0). Station law section 3: a fresh reviewer approves this spec; section 2: Rio Grande approves the
branch and the Pi suites pass.

## Why

Andy, 2026-10-27: "the chats need to be performant." Measured from the Mac over Tailscale (median of 3):

| Read | Time | Size |
|---|---|---|
| `GET /api/me` | 138 ms | 0.2 KB |
| `GET /api/chats/{all hands}` (15 messages) | 270 ms | 19 KB |
| `GET /api/chats/{City of AI}` (704 messages) | 1,954 ms | 1,814 KB |

On the Pi the whole City of AI query takes 5.4 ms (712 rows). The time is the 1.8 MB: serializing it and sending it
over the network. `GET /api/chats/{room}` returns every message the room has ever had (`chats.py` `get_room`), so
every reader pays for the whole history, and the cost grows with every post:

- **The prompt hook** (`agent/superyak_agent/hook.py` `_run`) fetches each room with new activity on every prompt in
  every session, then keeps only the messages newer than its cursor. One post in City of AI costs every session
  about 2 s and 1.8 MB on its next prompt.
- **`station_read`** (`agent/superyak_agent/mcp.py`) fetches all 704 messages to show 30.
- **The web app** (`peer/superyak_peer/static/app.js`) fetches the whole room when a room opens and again after a
  brief edit, a participant change or a board action, then renders every message.

## Goals

1. The hook, `station_read`'s window reads and the web app transfer only the messages they show.
2. Nothing changes for a client that asks for no page: the no-parameter answer stays byte-identical.
3. A new client talking to an older station notices that it got the whole room, and still works.
4. "What's new to me" never skips or repeats a message, including a federated message that arrives late with an
   older timestamp.

## Non-goals

- `station_read thread=` (a message and every reply under it) keeps the full read. Replies can sit anywhere in the
  room, so a correct thread read needs either the whole list or a server-side reply walk. Later, if it shows up in
  measurements.
- The watcher (`watch.py`) and the wormhole (`wormhole.py`) read whole rooms once per mention or cycle, not per
  prompt. They are unchanged here.
- Remote rooms (keys containing `:`, served by a paired peer) are unchanged: they are passed through from the peer.
- No streaming or websockets. The kick watcher already gives ships a fast wake.

## Two kinds of read, two keys

**"What's new to me"** (the hook; later the kick seed and the watcher) pages on the **events seq**. Every message
arrival emits a `chat.message` event with `resource_id` = room id and `payload.message_id`: local posts
(`chats.py` `send_message`), federated messages (`federation.py`), claim notes (`room_claims.py`) and system notices
(`system_author.py`). The events id is a gap-free, arrival-ordered integer. A room's message list merges
`peer_messages` by `created`, so a federated message arriving late with an older timestamp lands mid-list and
shifts every later position. A position cursor or a time cursor would skip it. A seq cursor sees it.

**"Show me a window"** (`station_read` newest, `at`, `after`, `start`, `oldest`, `message`; the web app's first
screen and "Load earlier") pages on **position** in the same merged order as today, so read hints (`at=k`) still
agree with what the full read would show.

## The API

`GET /api/chats/{key}` gains optional query parameters. With none of them, the response is exactly today's.

| Parameter | Meaning |
|---|---|
| `limit=N` | At most N messages (1 to 500). Alone, the newest N. |
| `before=P` | Messages at positions below P, the newest `limit` of them. |
| `at=P` | Messages from position P, oldest first, at most `limit`. |
| `start=<message id>` | That message and the ones after it, oldest first, at most `limit`. |
| `after=<message id>` | The messages after that one, oldest first, at most `limit`. |
| `since=S` | Messages whose `chat.message` event id is greater than S, in display order, at most `limit` (the newest `limit` if more arrived). |

At most one of `before`, `at`, `start`, `after`, `since` is accepted (400 otherwise). `limit` defaults to 100 when
another paging parameter is given. An unknown message id or a position out of range is 404 or 400, with today's
error shape.

A paged response is the room object exactly as today (title, members, member_ids, brief, brief_revision, claims,
system_author, breakout, last_activity and so on) with these changes:

- `messages` holds only the selected messages, in display order, each with `source` and `reply_to` as today.
- `paged: true`.
- `total`: how many messages the room has.
- `first_position`: the position of the first returned message (or, with none returned, where it would be).
- `seq`: the room's newest `chat.message` event id, or 0. A client stores it as its next `since`.
- `system_author` is included when any returned message is by the system author.

`GET /api/chats` (the rooms list) adds `last_seq` to each local room: its newest `chat.message` event id, or 0.

Compatibility:
- An older client sends no parameters and gets today's full room.
- An older station ignores unknown query parameters and returns the full room without `paged`. A new client that
  sees no `paged: true` treats the answer as the full room and slices it locally, as it does today.
- An older station's rooms list has no `last_seq`. The hook then falls back to its time cursor, as today.

## Server

`chats.py` `get_room(actor, key, page=None)`:

1. Membership check as today (`_room`).
2. A light query lists the room's message keys in today's order: local messages by `(created, rowid)`, then peer
   messages by `(created, rowid)`, stably merged by `created`. These are ids, created and the source table only,
   no bodies. Position k is the index in that list.
3. The page picks positions. For `since`, the matching ids come from
   `SELECT json_extract(payload, '$.message_id') FROM events WHERE kind = 'chat.message' AND resource_id = ? AND id > ?`.
4. Full rows, `_sources` and `_replies` are read only for the picked ids.
5. `seq` comes from `SELECT MAX(id) FROM events WHERE kind = 'chat.message' AND resource_id = ?`.

`db.py` adds `CREATE INDEX IF NOT EXISTS events_kind_resource ON events(kind, resource_id, id)`. It is cheap now
(764 events on the Pi) and keeps the seq lookups indexed as the station grows.

`app.py` passes the query parameters to `get_room`, validating each (integers in range, ids as text).

## Clients

**The hook** (`hook.py` `_run`). Its state gains `seq` beside `cursor`. With `seq` and a rooms list that has
`last_seq`, it skips rooms whose `last_seq` is not above `seq` and reads the others with
`since=<seq>&limit=<MAX_MESSAGES>`. Positions come from `first_position`, so read hints are unchanged. The new
`seq` is the highest `last_seq` it saw. On the first run with an old state (time cursor, no `seq`), it does
today's full read once, then records `seq` from that same rooms list. A message arriving between the list and the
read may be shown twice, once; none is skipped. If the station gives no `last_seq` or no `paged`, it keeps today's
time-cursor behaviour. The cursor and output format stay as they are, so `hook-state.json` and the prompt notice
read the same.

**`station_read`** (`mcp.py`). The newest view asks `limit=<limit>`. `oldest` and `at` ask `at=P&limit=`, `start`
asks `start=<id>&limit=`, `after` asks `after=<id>&limit=`, and `message` asks `start=<id>&limit=1`. The renderers
take the window and its `first_position` instead of the whole list, so every position they print is unchanged. A
range check on `at` uses `total`. `thread` keeps the full read.

**`StationClient.room(room_id, **page)`** (`station.py`) adds the parameters, URL-encoded. With none, the request is
unchanged. The test fakes' `room()` accepts and applies them the same way.

**The web app** (`app.js`):
- Opening a room asks `limit=100`: route load (line 1084), `openChat` (1392) and a newly made room (1416). When
  `first_position > 0`, a "Load earlier messages" button above the list asks `before=<first_position>&limit=100`
  and prepends the result, keeping the scroll position.
- The refreshes that today replace `state.room` wholesale ask `since=<seq>` instead: after a board action (825),
  a linked room's brief conflict (1432), a brief save conflict (1464) and a brief save (1479). Each takes the room
  fields from the answer, keeps the messages already shown, and appends the new ones, de-duplicated by id. Posting
  already appends the accepted message (1575).
- A non-paged answer is used as today.

## Performance targets

Measured from the Mac to the Pi, before and after, with the script in the plan (median of 5):
- the hook with one new message in City of AI: below 400 ms and 30 KB, from about 2 s and 1.8 MB;
- `station_read` newest 30 in City of AI: below 400 ms;
- the web app opening City of AI: below 600 ms for the first paint of 100 messages.

## Tests

- Server (`peer/tests`): no parameters gives a byte-identical answer to today's (golden comparison over a room with
  local, peer, claim and system messages); each parameter's window and edges (empty room, limit bounds, last
  position, unknown id, two parameters); `since` returns a late peer message with an older `created`, and
  `first_position` and `total` agree with the full list; `seq` and `last_seq`; a non-member gets today's 404.
- Hook (`agent/tests/test_hook.py`): the seq path reads only rooms with a newer `last_seq` and only `since`; read
  hints match the full-read positions; the migration from a time-only state; the fallback against a station
  without `last_seq` or `paged`.
- `station_read` (`agent/tests/test_mcp.py`): every mode's output is identical to today's for the same room; the
  request carries the page parameters.
- Web app: the existing browser tests still pass; a new one opens a 150-message room, sees 100, loads earlier,
  sees 150 in order, and after a brief save sees a newly arrived message once.

## Deploy

Peer and agent suites pass on the Pi (law section 2). Back up the station database, restart
`superyak-lighthouse`, and check: a no-parameter read is unchanged, a paged read works, and the web app opens City of
AI. Ships pick up the client side at their next `make dock` or pull. Rollback: revert the merge and restart. The
index is harmless to leave.

## Known limits

- A federated message arriving late still shifts later positions, so a read hint printed earlier may point one
  message off. That is true today; `since` reads are correct regardless.
- Thread reads still fetch the whole room.
