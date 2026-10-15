# Fresh owner mentions: an old or already answered owner mention gets a read-only ticket

Status: revision 1, for D8 review. Base: `main` (3e823a8). Branch `owner-mention-fresh`. Claimed by Rio Grande as
`spec:owner-mention-fresh` (room message 984a346e). Source: HANDOFF's parked note, now roadmap Phase 5: "the station
gives a build ticket for any owner mention, however old. Once acts spend build tickets, it must refuse messages that are
old or already answered." Serenity confirmed that grants step 3 does not cover owner builds (room message 74bebac0). Its
spec bounds only grant builds (step 3 spec S6, G15), and it asked for one shared helper that its merge 3c can call.

## Where this sits

A watcher asks the station for a run ticket for each mention (`issue_ticket`, tickets.py:43-73). The station decides
the run's mode in `_mode_for` (tickets.py:84-91): if the author is a person who owns the ship and the message mentions
the ship, the ticket is `build`, basis `owner`; anything else is `read`, basis `none` (spec A, section 4, rules 2 and
4). A ticket is single-use per (ship, message), so one message never builds twice.

Nothing looks at the mention's age, or at whether the ship already answered it. A builder run starts in two cases where
no person is asking for one now:

1. **Old.** The ship's watcher was down, or a ship comes back after days away (Defiant hasn't checked in since ship
   status went live). Its watcher then asks for every mention it missed, and each of the owner's old mentions builds:
   a builder acting on words its owner wrote days ago, which the owner may have dropped or done another way.
2. **Already answered.** A writable session on watch answers an owner mention itself with `reply_to`. A watcher that
   asks with `decisions` gets `answered` (tickets.py:54-56). But a watcher too old to ask with `decisions` still gets a
   builder ticket, so the same request is built twice.

Spec A's step 3 makes builder tickets something a grant can spend, so a stale build will matter more. Step 3 bounds
grant builds by age and answered (its S6, G15) and leaves owner builds unchanged. This spec bounds owner builds the same
way, with one helper that both use.

## The change

- **One helper,** `_mention_stale(db, ship_id, message)` in tickets.py, next to `_answered`. It returns `None` when the
  mention may build, or the reason it may not:
  - `'old'` when the message was posted more than `MENTION_FRESH_SECONDS` (86,400, 24 hours) before now. Exactly 24
    hours still counts as fresh (`now - created <= 86400`), matching step 3's G15. A `created` that isn't a finite
    number also gives `'old'`, so a hand-edited row fails closed;
  - `'answered'` when `_answered(db, ship_id, message['id'])` is true (R7: a message by this ship whose `reply_to` is
    the mention, never a kind message).
  `'old'` is checked first, so an old mention that was also answered says `'old'`.
  (Serenity suggested `_mention_fresh` returning a boolean. A reason is more useful to the run and to her 3c, which
  can still test `is None`.)
- **The owner rule uses it.** In `_mode_for`, when rule 2 holds (the author is the person who owns the ship and the
  ship is mentioned), the result is `build`, basis `owner`, root the owner, only if the helper returns `None`.
  Otherwise it is `read` with the reason as its basis (`old` or `answered`) and no root. Every other path is unchanged.
- **The decision is made once, at issue.** A running ticket sent again returns as it was issued (tickets.py:57-59). A
  mention that was 23 hours old when its builder ticket was issued keeps that ticket for its two-hour lifetime.
- **What follows from `read`.** A downgraded mention is an ordinary read mention for everything after `_mode_for`:
  - a watcher that asked with `decisions`, while the ship has a writable session on watch, gets it deferred to that
    session (S5 of ship status). The session has a person at its terminal and can act on it within its owner's work;
  - otherwise a read-only run answers it.
  A `decisions` watcher never sees `answered` reach `_mode_for`: step 1 of `issue_ticket` returns `answered` first, as
  today. So basis `answered` is seen only by watchers too old to ask with `decisions`.
- **The watcher tells the run why.** `build_prompt` gains a keyword `limited` (default `None`). The watcher passes the
  ticket's basis when it is `old` or `answered`. Then, in read mode, the task's last sentence ("If the request needs
  changes, say what you would do and that {author} can ask the ship's owner.") becomes:
  - for `old`: "This mention is from the ship's owner, but it is more than 24 hours old, so this run is read-only. If
    it needs changes, say what you would do, and that a new message will start a builder run if it is still wanted.";
  - for `answered`: "This mention is from the ship's owner, but this ship has already answered it, so this run is
    read-only. Point to that answer, and say a new message will start a builder run if more is wanted."
  Any other basis, or none, leaves the prompt byte-for-byte as today.

## Amended rules (docs/superpowers/specs/2026-10-08-instruction-layers-and-grants-design.md, section 4)

- **Rule 2** gains: "...the author is a person who owns the ship, *and the mention is fresh: posted at most 24 hours
  before the ticket, and not yet answered by the ship (fresh owner mentions spec)*."
- **Rule 4** gains: "Otherwise `read`, basis `none`*, or basis `old` or `answered` when rule 2 failed only on
  freshness*."

## Requirements

- **R1.** An owner mention posted at most 86,400 seconds before the ticket, which the ship hasn't answered, gets `build`,
  basis `owner`, as today. Exactly 86,400 seconds still builds.
- **R2.** An owner mention posted more than 86,400 seconds before the ticket gets `read`, basis `old`, root `None`,
  footer empty.
- **R3.** An owner mention the ship has answered (`_answered`) gets `read`, basis `answered`, when the watcher didn't
  ask with `decisions`. With `decisions` the answer stays `{decision: 'answered'}`, as today.
- **R4.** A message whose `created` isn't a finite number gets `old` when rule 2 would otherwise build.
- **R5.** Mentions by anyone other than the owner, resident ships, and the order of `issue_ticket`'s steps are
  unchanged. A running ticket sent again returns as issued.
- **R6.** A downgraded mention is deferred like any read mention when the watcher asked with `decisions` and the ship
  has a writable session on watch.
- **R7.** `_mention_stale` is the only place the bound and the answered check are combined for builds, so 3c can call
  it for grant builds.
- **R8.** The read prompt for `old` and `answered` says why, as in "The change". For every other ticket the prompt is
  unchanged, byte for byte.
- **R9.** Source labels are unchanged: a downgraded run's reply is labelled a read-only run, as any read run is.

## Testing

Peer, in peer/tests/test_tickets.py, using the store's injectable clock:
1. Owner mention at `created + 86400`: `build`, `owner`. At `created + 86400.5`: `read`, `old`, no root, no footer.
2. Owner mention the ship answered with `reply_to`, no `decisions`: `read`, `answered`. With `decisions`: `answered`
   decision, and the deferral row is gone, as today.
3. Answers that don't count, as `_answered` defines them: another ship's reply, and the ship's own kind message. The
   mention still builds.
4. A message with `created` set to infinity by hand: `read`, `old`.
5. An old owner mention, `decisions` asked, while the ship holds a writable watch: `defer`, as R6.
6. A builder ticket issued at 23 hours, sent again after 25 hours while it is still running: the same `build` ticket.
7. A non-owner's mention: `read`, `none`, as today, whatever its age.
8. Old and answered together: `old`.

Agent, in agent/tests/test_watch.py:
9. `build_prompt` in read mode with `limited='old'` and with `limited='answered'` contains its sentence, and not the
   "can ask the ship's owner" one. With `limited=None`, and in build mode with any value, it is unchanged.
10. A watcher handed a ticket `{mode: 'read', basis: 'old'}` passes `limited='old'`. One with basis `none` or no basis
    passes `None`.

Each test must fail when its production change is removed.

## Security

- The change only narrows: some tickets that built become read, and none that read become build.
- The bound uses the station's clock and the stored `created`, both written by the station. No client value is
  involved. The owner's messages are local, so federation's clamped times don't reach this rule.
- A non-finite `created` fails closed.
- The prompt sentences are fixed strings. Nothing from the message goes into them.

## Deploy

Under section 2: approved in the room, and the Pi suites passing. Back up the database first. No schema change: basis
is free text, and `old` and `answered` are new values. Restart the lighthouse and door for the station, and the
ship, odo and wormhole watchers for the prompt. Each machine's watcher gets the prompt sentences when it updates. An
older watcher gives a downgraded mention the plain read-only prompt (the mixed-versions limit below).

Live check, needing no person's login: in a scratch copy of the live database, opened by a throwaway store in the test
style (never the live file), issue tickets for one old owner mention and one fresh one, and check `old` and `build`.

## Known limits

- **24 hours for owners as for grants.** A watcher down for more than a day answers its owner's mentions read-only, and
  the owner asks again. That is the point. The number matches step 3's G15, so the two never disagree on a mention.
- **Mixed versions.** A watcher on older code gets `read`, basis `old` or `answered`, and runs the plain read-only
  prompt. That prompt says the author "can ask the ship's owner", who is the author. It is safe, only confusing, and it
  ends when that machine updates.
- **The clock.** A clock stepped back makes a message look younger, or from the future, and it builds. A clock stepped
  forward makes it look older, and it reads. Neither widens what a ship may do beyond today's rule.
- **Not a refusal.** An old owner mention still gets an answer, read-only. A long outage can bring one read-only reply
  per old mention, as non-owner mentions already do today.

## Out of scope

- Grant builds: step 3's 3c calls `_mention_stale` (R7), and Serenity's spec decides its basis on a downgrade.
- Directs (spec A step 5).
- Any change to deferral bounds, unread or the hook.
