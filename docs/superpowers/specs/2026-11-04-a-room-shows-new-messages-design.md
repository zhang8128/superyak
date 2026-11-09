# A room shows its new messages

Status: revision 4. A fresh reviewer approved revision 3 with changes (law section 3), and they're applied. Revision 4
is the builder's corrections from what building and a reader's run found (D2, D4, D5, D6, D8, the tests), and the
build's reader re-reads them; that reader also found D2's rule that a poll's older answer is dropped true as written.
Andy can veto anything. Board item:
`spec:a-room-shows-new-messages`. It serves goal 2, "Chats are performant", and adds to how that goal is measured.

## What a person meets today

Measured on a throwaway home at f45fd686, in real Chromium on the Mac, 2026-11-04. The store was the control: the
message was in it.

- **An open room never updates by itself.** Another member's message arrived; after 45 s of reading, the page showed
  nothing and had made 0 API requests. It appeared after clicking Chats. No script in `static/` has a timer, a stream
  or a socket, and there is no Refresh control. A ship's watcher polls every 30 s (`watch.py`'s `POLL_SECONDS`); a
  person's page doesn't poll at all.
- **A busy room opens at its oldest shown message.** 150 messages, 100 shown: `scrollY` 0, page height 11,567 px, a
  960 px window, the newest message at 11,125 px, about 12 screens below. A click and a reload did the same.

Goal 2 measures how long a read takes. Neither of these shows up in that number, because a read that doesn't happen has
no duration, and a page that paints quickly can still paint the wrong end of the room.

## Decisions

**D1. A room opens at its newest message.** When a room's view is first drawn (the route enters it, or a reload), the
page scrolls so the newest message is on screen. Later renders of the same room don't scroll. "Load earlier" keeps the
reader's line, as it does now (`app.js:581-585`).

**D2. While a room is open and its tab is visible, the page asks what's new every 5 s,** with up to 20% jitter either
way so a home's tabs don't fall into step. It uses the read that exists for this: `refreshRoom`,
`?since=<seq>&limit=100` (chat paging's "what's new to me"). One ask at a time: a slow answer delays the next and
never stacks. A hidden tab asks nothing. Coming back asks at once. Leaving the room stops it. An answer for a room the
person has left changes nothing. No other view polls.

A room that isn't paged (a received room) has no `?since`: each ask reads it whole, which a reader measured at 1.9 MB and
41 ms of the gate for 5,000 messages. A home that pulls hears news about once a minute (a host that dials in delivers on
its 5 s pass), so it waits at least 30 s, or 30 ms per message if that's longer. That keeps one visible tab at most about
370 MB in 8 hours, for messages of about 150 characters. Another room starts over with its own wait and no failures.

Send, the board, the brief and a removal also call `refreshRoom`, and they keep doing so. It builds its answer from
the room on screen when the answer arrives, so overlapping callers can't lose a message from `state.room`. But an
older answer can move `seq` back and put what it fetched after newer messages (the reviewer ran it: `seed, msg2,
msg1`). So a poll never competes: it doesn't start while another refresh of this room is on its way, and its answer is
dropped if another started after it did. That answer is older, and the next ask fetches whatever is missing, so the
worst a poll does is show a message one interval later. Overlaps among the other callers stay as they are today.

**D3. Nothing new, nothing happens.** An answer has something new when it carries a message whose id isn't in
`state.room.messages`. Otherwise no render and no DOM change, and its other fields (members, brief, claims) are
dropped, as they wait today for the person's next action.

**D4. New messages are appended, not rendered, and `state.room` stays the truth.** `render()` rebuilds the whole page,
which would drop a text selection, close open panels and disturb a dialog every time someone spoke.
`messageMarkup(message, room)` depends on one message and the room (checked: nothing in `app.js` or `app.css` groups
by neighbour). So an answer with something new does these together:

1. `state.room` takes `refreshRoom`'s answer whole: `messages`, `seq`, `first_position`, `total` and the other fields.
   Every render draws from `state.room`, so a later one keeps what was appended, and the next ask doesn't fetch it
   again.
2. Only if the `.messages` on screen is this room, the messages in `state.room.messages` that aren't on screen yet go
   on the end. `.messages` carries `data-room` for this, and the check is `boardOnScreen`'s (`app.js:704`), the one the
   board panel already uses. Each message's markup gains its id, for "aren't on screen yet". A drawn message the answer
   no longer has comes off the list: a whole room's answer does this when a queued reply in a received room comes back
   with the host's id.

Nothing else on the page is touched, so members, the brief and claims stay as drawn until the next render, as they do
today. A message that sorts earlier (a step in the station's clock, which paging's seq cursor brings in anyway) goes on
the end at once, where a render also draws it until the room is reopened (chat paging's Known limits). Revision 3 held it
back for the next render, and a reader's run showed that only hid it and what came after it, with no sign. Sorting at
draw time would place it, and it isn't worth it for a clock step.

**D5. Where the person is decides what moves.**
- At the newest (the end of the messages with the composer under them, within 120 px of the window's bottom): the page
  follows, so the newest message is on screen, or its start if it's too long to fit. It's measured from the end of the
  messages and not the page's: a room's management sits below the composer, so an owner never gets near the page's end.
- Scrolled up to read, or down past the messages: the page doesn't move. A small "New messages" button jumps to the
  newest, and goes when they reach it. The composer stopped being sticky with D1, so the button is fixed in the window,
  above a phone's bottom bar. Your own words coming back from another device or a host show but aren't announced, and
  bring no button.
- Screen readers: `announce()` says how many, "2 new messages", never the words, so a busy room doesn't talk over them.

**D6. Failures are quiet, then said once.** A failed ask (connection, 5xx) doubles the wait: 5, 10, 20, 40, then 60 s,
each with the same 20% jitter, so tabs don't come back in step after a station restart. After three in a row, one line
in the composer's status: "Can't reach this home. New messages will show when it's back." It clears on the next good
answer. A draft is never touched. An ask gives up after 30 s and counts as a failure: a hung answer would otherwise stop
the asking, with no line. A 401 does what `refresh()` does (`showLogin`, the draft kept in `sessionStorage`;
`clearChatDrafts` runs only from `logout`). A 403 or 404 (removed, or the room is gone) stops asking, the list catches up,
and the person is told, with their unsent text where they can copy it. The note doesn't name the room.

**D7. The room list isn't polled.** It's the heaviest read a person's page makes: in a timed run on a scratch store, a
200-room list held the gate about 36 ms, before it moved to `reading()`. Nothing here needs it. So another room's news
still waits until the person navigates, as today. A cheap "which rooms have news" read is a later spec, and nothing
here claims to solve it.

**D8. It doesn't wait for two others (revised by the builder; the build's reader upheld it).** Revision 3 had
`fix-typing-keeps-its-place` and the branch that marks the composer with its room landing first, because Send and much
else still render, and any render drops the focus of whoever is typing. But D4 means an arrival never rebuilds the page,
so polling doesn't make that worse, and D6's 401 and 404 remove the composer whichever lands first. Those two are still
wanted. `.messages` takes the room's mark here; when the composer's mark lands, it's one rule.

## What it costs

A read that finds nothing new, 200 reads each on a scratch store at f45fd686, one room: in-process (the time holding
the gate) and over HTTP through the app. `_page` walks `_message_order` before it reaches `since`, so it grows with
the room.

| Messages | Mac, gate p50 / p99 | Mac, HTTP p50 / p99 | Pi, gate p50 / p99 | Pi, HTTP p50 / p99 | Answer |
|---|---|---|---|---|---|
| 10 | 1.06 / 1.21 ms | 2.92 / 4.05 ms | 2.21 / 2.48 ms | 7.07 / 10.91 ms | 655 bytes |
| 100 | 1.16 / 1.30 ms | 3.06 / 4.00 ms | 2.42 / 3.14 ms | 7.20 / 9.38 ms | 658 bytes |
| 1,200 (about all hands) | 2.64 / 3.36 ms | 4.51 / 5.62 ms | 6.01 / 8.49 ms | 10.62 / 13.37 ms | 661 bytes |
| 5,000 | 7.77 / 8.99 ms | 9.82 / 11.24 ms | not run | not run | 661 bytes |

The Pi's run was at load 3.5 with other suites running, at lowest priority, so it should read high. So one visible tab
on an all-hands-sized room holds the Pi's gate about 0.12% of the time (6 ms every 5 s), and 20 such tabs about 2.4%.
For scale, that 200-room list, five times a second, held it about 18%. A tab left visible for 8 hours sends about
5,760 reads and 3.8 MB. Not measured: a real store's larger events table, which this read touches.

These numbers are all under `transaction()`: `get_room` stays on the write path (see Safety), which is why a read
holds the gate at all. If the Pi's real store says otherwise, the first thing to change is the `_message_order` walk
before `since`, which a no-news answer doesn't need for its messages. No fix to it is made here, since these numbers
don't ask for one.

## Rejected

- **A stream (SSE or WebSocket).** No route serves one, the browser boundary closes WebSockets (`app.py:183`), and
  each open tab would hold a connection on a station with one GIL core.
- **Long polling.** Each waiting request holds a worker from the same threadpool the people's reads use.
- **Refreshing only when the tab regains focus.** Cheap, but someone watching a room still sees nothing, which is the
  complaint. D2 includes it as "coming back asks at once".
- **A Refresh button.** It makes the person do the station's job.

## Safety

Nothing here widens who reads what. It's the same route and the same member check at each ask, with a `since` the
client already holds. The only write reachable from `get_room` is a breakout's closure (the reviewer walked the whole
path; I read `_room`'s), and breakouts have no person members (`breakouts.py:1-3`), so a person's poll never reaches
it. Because of that write, `get_room` stays on `transaction()` until the WAL spec's phase 2, and the cost table is the
gate's cost. Messages go through `messageMarkup`, the same escaping as a render, and the id it gains is escaped the
same way.

## Tests, for the plan

- A message another member posts appears with no action, and the box, its text, caret and focus are the same element.
- No-news: no DOM change (the `.messages` node and the textarea are the same objects), and a selection survives.
- A selection, an open panel and a dialog each survive an arrival.
- A hidden tab asks nothing; coming back asks at once. Leaving the room stops it; a late answer for that room changes
  nothing.
- One at a time: with an answer held, no second ask.
- D5, each of the three. D6: the wait doubles, the line comes after three and goes on a good answer, a draft stays
  through
  all of it, and 401, 403 and 404 each do what D6 says.
- D1: a busy room opens with its newest message on screen, by click and by reload. A later render doesn't scroll.
  "Load earlier" still keeps the line.
- An older-sorting message goes on the end at once, and a render keeps it there.
- A person's own Send isn't shown twice when the next ask carries it.
- After an append, a render keeps the message, and the next ask doesn't fetch it again (`state.room` in step).
- An answer for a room no longer on screen appends nothing.
- A poll overlapping Send, "Load earlier" or the board's refresh shows every message once and loses none.
- A poll's held answer, released after a newer refresh, changes nothing, and the order stays right.
- A poll doesn't start while another refresh of the room is on its way.
- A received room's reply isn't shown twice when the host's copy comes back, and its asks wait longer as it grows.
- An arrival during Send's wait for sync stays on screen.
- An ask that hangs gives up and counts as a failure.
- A removal says so, shows the unsent text, and takes the room off the list.
- A leftover timer asks nothing for the next person signing in, and sign-out clears `state.room`.
- A wait armed for a big received room doesn't carry into the next room.
- If sync fails before Send's refresh returns, what the refresh brought is still drawn.
- An ask held across opening the room leaves "Load earlier" working.
- The "New messages" button is on screen and uncovered, measured in the window: `to_be_visible` says yes at 10,000 px
  below it.
- D5 at a phone width as well as a desktop one.

## Order of work

1. Build D2 to D7, through a reader (D1 landed first, on its own branch).
2. `fix-typing-keeps-its-place` and the branch that marks the composer with its room land when they're ready (D8).
3. One timed arm at load: 20 pollers at 5 s on a 1,200-message room, with goal 2's read time as the bar. Rio Grande's,
   if it wants it; it holds the harness.
4. After deploy, measure from the Mac, tailnet and Funnel, what this is for: **from a post to a person seeing it.**
   Propose it for goal 2 as a line of its own: a new message shows within 6 s in a visible paged room.

## Not in this spec

- **A keyboard send.** Enter adds a newline and the only `keydown` listener in `app.js` is the dialog's. It's a small
  separate question: Ctrl or Cmd+Enter adds without taking anything away; Enter to send changes what people may rely
  on.
- Unread counts, a tab-title count, or notifications.
- Another room's news (D7).
