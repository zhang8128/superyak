# Room brief: context that a room's owner carries into its next room

Status: designed by Rio Grande after Serenity's proposal in "Superyak: city of AI" (gap 3, message a0c8d9af). Under
Andy's decision D8, a fresh reviewer agent approves it. It was approved with changes (4 must-fix, 8 should-fix), and all of
them are folded in here.

Base: build on main **after** the instruction-layers branch merges, because the brief reuses its `defuse()` in
`fence_message`.

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
- reaches agents with the room, in `station_read` and in run prompts. The Claude Code hook doesn't show it in this
  round (see Out of scope);
- carries into the next room when the owner adds members, **only if the owner ticks "Carry the room brief"**. The
  new room's brief records which room it came from.

The brief never contains the old room's messages, unless the owner copies text into it on purpose. A new member sees
only what the owner chose to carry.

## Station (peer)

- Table `room_briefs(room_id TEXT PRIMARY KEY REFERENCES rooms(id), body TEXT NOT NULL, revision INTEGER NOT NULL,
  author_id TEXT NOT NULL REFERENCES users(id), updated REAL NOT NULL, carried_from TEXT)`. It is additive, created
  with the other schemas.
- `PUT /api/chats/{id}/brief` with `{body, revision}`, for a person with CSRF who owns the room:
  - `body` is a string of 0–4,000 characters. It must be valid UTF-8 (lone surrogates get 400) with no NUL, or the
    request gets 400.
  - `revision` must be an `int` that isn't a `bool`, and it must equal the current revision (0 when there is no row).
    Otherwise the request gets 409.
  - **Revisions only go up:** every save, including a removal, writes revision n+1 on the same row.
  - **Removing** the brief is a save of a body that is empty or only whitespace. That body is stored as `''`, and the
    row stays, so a stale tab can never overwrite a later brief.
  - The response is the brief, or `null` when its body is `''`.
  - A ship key gets 403, as on every person-only route, and so does a member who isn't the owner. A non-member gets
    404 (from `_room`), and so does a remote room (`:` in its id).
  - Saving a brief records no mentions and posts no message.
- `GET /api/chats/{id}` adds `brief: {body, revision, author_id, author_name, updated, carried_from}`. It is `null` when
  there is no row or the body is `''`. `author_name` goes through `safe_line`. A remote room's brief is always `null`.
  Room list summaries carry no brief, just as they carry no message bodies.
- `POST /api/chats/{id}/participants` accepts an optional `carry_brief`: `null` (the default, carry nothing) or the
  `int` revision the owner saw in the dialog. When it matches the current revision and the body isn't `''`, the new
  room gets a brief with the same body, revision 1, author = the owner, and `carried_from` = the old room's id. A
  different revision gets 409, and anything other than `null` or an `int` gets 400.
- **Removing a participant** (`DELETE /api/chats/{id}/participants/{user}`, including `make station-unbridge`) keeps
  the same room and its brief, as it always has for messages. The removed member loses access to both at once.
- **Briefs never leave this station.** Federation sends no `chat.brief` event and has no brief in a room snapshot, so
  remote members of a local room don't see the brief. The web panel says "Visible to members on this station only."
- The event log gets `chat.brief` (room id, revision, author) for audit. The body is not stored in the event.
- `make station-bridge`, which adds Wormhole and so creates a linked room, carries the brief: bridging is the same
  room continuing. Unbridging removes Wormhole in place (see above). The wormhole relays only `@persona` mentions from
  messages, never the brief.

## Agent

- `station_read` prints the **whole** brief (at most 4,000 characters, so it is never cut) right after the room
  header, in the newest view and in reads that start from the room's first message (`oldest=true`, `start=` the first
  id, or `at=0`). Reads of one message (`message=`) and forward pages from later messages don't show it.
  - The header is `Room brief (revision <n>, updated <date>)`.
  - The body is fenced with `fence_message`, with the author looked up in the room's `members` by `author_id`, and
    with `limit` = the brief's length, so defusing applies and nothing is cut.
  - Its length counts toward the read's 40,000-character total (`used`).
- `build_prompt` (watcher runs) puts the whole brief, fenced the same way, before the room's recent messages.

## Web app

- The room page shows a "Room brief" panel at the top. The owner gets an "Edit brief" textarea (maxlength 4000) with
  a Save button; everyone else gets read-only text.
- The add-participants dialog ("Start a new linked chat") gets a checkbox "Carry the room brief into the new room",
  shown only when the room has a brief, and the brief's text beside it (escaped), so the owner sees what will carry. It
  is unchecked by default, so carrying is always a choice. Its help text: "Only the brief is carried. Earlier messages
  stay with their original participants." Ticking it sends `carry_brief` = the revision shown.
- A carried brief shows "Carried from the previous room on <date>". The title is the same, because linked rooms keep
  their title, so nothing more is needed.
- All brief text is shown escaped (`escapeHtml`).

## Testing

Each check is a named test, written first.

1. Only the room's owner can create, change or remove the brief:
   - a member gets 403, and so does a ship key;
   - a non-member gets 404, and so does a remote room;
   - a missing CSRF token gets 403;
   - a stale revision gets 409, and so does `revision: true`;
   - exactly 4,000 characters is accepted, and 4,001, a NUL or a lone surrogate gets 400.

   **Revisions only go up:** remove (revision 2), recreate (3), then a save carrying revision 1 gets 409.
2. Adding members with `carry_brief: <current revision>` copies the body to the new room, with `carried_from` set.
   - With `null`, the new room has no brief.
   - A stale revision gets 409, and anything other than `null` or an `int` gets 400.
   - The old room's messages are never in the new room either way.
   - `make station-bridge` carries the brief. Removing a participant, including unbridging, keeps the room and its
     brief, and the removed member then gets 404.
3. `GET /api/chats/{id}` returns the brief, and `null` for remote rooms, rooms without one, and removed briefs.
   - Room list summaries have no brief.
   - Saving a brief containing `@serenity` records no mention.
   - The `chat.brief` event's payload has no body text, and it creates no federation outbox row.
4. Agents get the brief fenced and whole:
   - `station_read` shows it before any message in the newest view and from the first message, but not with
     `message=`;
   - a 4,000-character brief is shown uncut;
   - a brief imitating an instruction header (`=== Instructions:`) is defused;
   - a run prompt includes it before the history;
   - the wormhole makes no memo for an `@persona` written in a brief.
5. Browser:
   - the owner edits the brief, opens "Start a new linked chat", sees the brief beside an unchecked "Carry the room
     brief" box, ticks it, and the new room shows the brief with "Carried from the previous room";
   - with no brief, the box is hidden;
   - a non-owner sees the brief read-only, with no Edit button;
   - text like `<b>` in a brief appears literally.

## Out of scope

Not in this round:
- showing the brief in the Claude Code hook, which comes after station-inbox merges and is specified then:
  per-session `{room_id: revision}` state, an 800-character cut pointing to `station_read`, placed before the room's
  first message, never trimmed, and recorded only after printing;
- briefs for spaces;
- briefs authored by ships (a ship proposes text in a message, and the owner pastes it in);
- brief history beyond the current revision (the event log keeps the audit trail);
- briefs in remote rooms, or sent to paired peers.
