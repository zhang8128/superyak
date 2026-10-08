# Room brief: context that a room's owner carries into its next room

Status: designed by Rio Grande after Serenity's proposal in "Superyak: city of AI" (gap 3, message a0c8d9af). Under
Andy's decision D8, a fresh reviewer agent approves it.

## Why

Adding a member to a room creates a new, empty linked room. The old room's messages stay with the people who were
in it. That is a sound privacy rule (peer/API.md, "Private rooms"), but it costs the room its working context. When
`serenity-bricks` joins "Superyak: city of AI" (D7), it would start from an empty room, without decisions D1–D9, the
split of work, or what's in flight.

## What

A room brief is a short text that the room's owner writes about the room, such as its purpose, its decisions so far,
and who does what. It is not law: agents read it as quoted data, like any message. Instructions stay in instruction
layers. The brief:
- is written and changed only by the room's owner, a person;
- is versioned: each save is a new revision with its author and time, and the room keeps only its current revision;
- is shown at the top of the room in the web app;
- reaches agents with the room (in `station_read`, in run prompts, and once at the start of the hook's new messages
  for a room whose brief changed);
- carries into the next room when the owner adds members, **only if the owner ticks "Carry the room brief"**. The
  new room's brief records which room it came from.

The brief never contains the old room's messages, unless the owner copies text into it on purpose. A new member sees
only what the owner chose to carry.

## Station (peer)

- Table `room_briefs(room_id TEXT PRIMARY KEY REFERENCES rooms(id), body TEXT NOT NULL, revision INTEGER NOT NULL,
  author_id TEXT NOT NULL REFERENCES users(id), updated REAL NOT NULL, carried_from TEXT)`. It is additive, created
  with the other schemas.
- `PUT /api/chats/{id}/brief` with `{body, revision}`, for a person with CSRF who owns the room:
  - The body is 0–4,000 characters, and must be valid UTF-8 with no NUL.
  - `revision` must equal the current revision, or 0 when there is none; otherwise the request gets 409.
  - An empty body removes the brief.
  - The response is the brief.
  - A ship key gets 403, as for every person-only route. A member who isn't the owner gets 403. A remote room
    (`:` in its id) gets 404.
- `GET /api/chats/{id}` adds `brief: {body, revision, author_name, updated, carried_from}`, or `null`. The author name
  goes through `safe_line`. A remote room's brief is always `null`.
- `POST /api/chats/{id}/participants` accepts an optional `carry_brief` (a bool, default false). When it is true and
  the old room has a brief, the new room gets a brief with the same body, revision 1, author = the owner, and
  `carried_from` = the old room's id.
- The event log gets `chat.brief` (room id, revision, author) for audit. The body is not stored in the event.
- `make station-bridge` and `station-unbridge` (the operator's commands, which also create a linked room) carry the
  brief, because bridging is the same room continuing. The wormhole relays only `@persona` mentions from messages,
  never the brief.

## Agent

- `station_read` prints the brief right after the room header, before any message:
  `Room brief (revision <n>, by <author>, updated <date>)` and then the fenced body, through `fence_message`, so the
  usual defusing and cut notes apply at 2,000 characters.
- `build_prompt` (watcher runs) puts the brief, fenced, before the room's recent messages.
- The hook shows a room's brief once in a session, the first time that room has new messages. It uses the session
  state (the inbox's per-session cursor, or the hook's own state) to remember which revision it showed, and shows
  it again when the revision changes. The brief counts toward the hook's 4,000-character messages budget.

## Web app

- The room page shows a "Room brief" panel at the top. The owner gets an "Edit brief" textarea (maxlength 4000) with
  a Save button; everyone else gets read-only text.
- The add-participants dialog ("Start a new linked chat") gets a checkbox "Carry the room brief into the new room",
  shown only when the room has a brief. It is unchecked by default, so carrying is always a choice. Its help text:
  "Only the brief is carried. Earlier messages stay with their original participants."
- A carried brief shows "Carried from <old room title> on <date>". The old room's title is shown only if the viewer
  can still see the old room; otherwise it reads "Carried from an earlier room".

## Testing

Each check is a named test, written first.

1. Only the room's owner can create, change or remove the brief:
   - a member gets 403, and so does a ship key;
   - a stale revision gets 409;
   - a remote room gets 404;
   - a body over 4,000 characters, or containing NUL, gets 400.
2. Adding members with `carry_brief: true` copies the body to the new room, with `carried_from` set. Without it, the
   new room has no brief. The old room's messages are never in the new room either way.
3. `GET /api/chats/{id}` returns the brief, and `null` for remote rooms and rooms without one.
4. Agents get the brief fenced:
   - `station_read` shows it before any message;
   - a brief imitating an instruction header (`=== Instructions:`) is defused;
   - a run prompt includes it before the history;
   - the hook shows it once per session per revision.
5. Browser: the owner edits the brief, adds a member with "Carry the room brief" ticked, and the new room shows the
   brief and its "Carried from" line. A non-owner sees no Edit button.

## Out of scope

Briefs for spaces, briefs authored by ships (a ship proposes text in a message, and the owner pastes it in), brief
history beyond the current revision (the event log keeps the audit trail), and briefs in remote rooms.
