# Fresh owner mentions: an old or already answered owner mention gets a read-only ticket

Status: revision 3, **approved under D8**. Revision 1 (2688265) had the fresh reviewer's verdict, APPROVE WITH CHANGES
(0 must-fix, 8 should-fix, 8 nits; room message ce9facd6). The same reviewer's re-check of revision 2 (66de370) is
APPROVE, with one should-fix and five nits, all folded into this revision; see "Review map". Base: `main` (3e823a8). Branch
`owner-mention-fresh`. Claimed by Rio Grande as `spec:owner-mention-fresh` (room message 984a346e). Source: HANDOFF's
parked note, now roadmap Phase 5: "the station gives a build ticket for any owner mention, however old. Once acts spend
build tickets, it must refuse messages that are old or already answered." Serenity confirmed that grants step 3 does not
cover owner builds (room message 74bebac0). Its spec bounds only grant builds (step 3 spec S6, G15), and it asked for one
shared helper that its merge 3c can call. She has agreed that 3c reuses this helper and its basis values (room message
1b20ddd1).

## Where this sits

A watcher asks the station for a run ticket for each mention (`issue_ticket`, tickets.py:43-73). The station decides
the run's mode in `_mode_for` (tickets.py:84-91): if the author is a person who owns the ship and the message mentions
the ship, the ticket is `build`, basis `owner`; anything else is `read`, basis `none` (spec A, section 4, rules 2 and
4). A ticket is single-use per (ship, message), so one message never builds twice.

Nothing looks at the mention's age, or at whether the ship already answered it. A builder run starts in two cases where
no person is asking for one now:

1. **Old.** The ship's watcher was down, or a ship comes back after days away. Its watcher then asks for every mention
   it missed, and each of the owner's old mentions builds: a builder acting on words its owner wrote days ago, which
   the owner may have dropped or done another way.
2. **Already answered.** A writable session on watch answers an owner mention itself with `reply_to`. A watcher that
   asks with `decisions` gets `answered` (tickets.py:54-56). A watcher that asks without `decisions` still gets a
   builder ticket, so the same request is built twice. Two kinds of watcher ask without `decisions`: one on code from
   before decisions existed, and a current one whose deferred list is full (watch.py:132; ship status R10).

Spec A's step 3 makes builder tickets something a grant can spend, so a stale build will matter more. Step 3 bounds
grant builds by age and answered (its S6, G15) and leaves owner builds unchanged. This spec bounds owner builds the same
way, with one helper that both use.

## The change

- **One helper,** `_mention_stale(db, ship_id, message)` in tickets.py, next to `_answered`. It returns `None` when the
  mention may build, or the reason it may not:
  - `'old'` unless `created` is an `int` or `float` (not a `bool`), finite, and within `MENTION_FRESH_SECONDS` (86,400,
    24 hours) of now on either side: `abs(now - created) <= 86400`. Exactly 24 hours still counts as fresh, matching
    step 3's G15. So text, infinity, and a time more than a day in the future are `'old'`. A clock that stepped back by
    less than a day still builds;
  - `'answered'` when `_answered(db, ship_id, message['id'])` is true (R7: a message by this ship whose `reply_to` is
    the mention, never a kind message).
  `'old'` is checked first, so an old mention that was also answered says `'old'`.
  (Serenity suggested `_mention_fresh` returning a boolean. A reason is more useful to the run and to her 3c, which
  tests `is None`.)
- **The owner rule uses it.** In `_mode_for`, when rule 2 holds (the author is the person who owns the ship and the
  ship is mentioned), the result is `build`, basis `owner`, root the owner, only if the helper returns `None`.
  Otherwise it is `read` with the reason as its basis (`old` or `answered`) and no root. Every other path is unchanged.
- **The decision is made once, at issue.** A running ticket sent again returns as it was issued (tickets.py:57-61). A
  mention that was 23.5 hours old when its builder ticket was issued keeps that ticket for its two-hour lifetime, and an
  answer posted after the issue doesn't stop that build (Known limits).
- **What follows from `read`.** A downgraded mention is an ordinary read mention for everything after `_mode_for`:
  - when the watcher asked with `decisions` and the ship has a writable session on watch, it is deferred to that
    session (ship status S5). The session is told `would_be: "read"` (inbox.py:165), which is the truth, and a deferral
    moves no authority;
  - otherwise a read-only run answers it.
  A watcher that asks with `decisions` never sees `answered` reach `_mode_for`, because step 1 of `issue_ticket`
  returns `answered` first, as today. So basis `answered` reaches a watcher only when it asked without `decisions`:
  an old watcher, which ignores the new prompt, or a current one with a full deferred list, which uses it.
- **The watcher tells the run why.** `build_prompt` gains a keyword `limited` (default `None`). The watcher passes the
  ticket's basis when it is `old` or `answered`, and `None` otherwise. Then, in read mode only, the task's last sentence
  ("If the request needs changes, say what you would do and that {author} can ask the ship's owner.") becomes:
  - for `old`: "This mention is more than 24 hours old, so this run is read-only. If the request needs changes, say
    what you would do, and that a new message will start a builder run if it is still wanted.";
  - for `answered`: "This ship has already answered this mention in this room, so this run is read-only. Say so, and
    that a new message will start a builder run if more is wanted."
  Neither sentence says who wrote the mention, so both read true for an owner's mention and for a grantee's (3c). The
  run can't see the earlier answer: the history ends at the mention, and runs have no station tools. So the sentence
  doesn't ask it to quote that answer. Any other basis, or none, and build mode with any value, leave the prompt byte
  for byte as today.
- **Docs.** peer/API.md's "Run tickets" paragraph names the new basis values. agent/README.md line 50 ("an owner's
  mention still runs as a builder") becomes "an owner's fresh mention (posted within 24 hours, not yet answered by the
  ship) still runs as a builder".

## Amended rules

Each amendment is made in place, with the note "(fresh owner mentions spec)".

- **Spec A,** docs/superpowers/specs/2026-10-08-instruction-layers-and-grants-design.md, section 4:
  - rule 2 gains: "...the author is a person who owns the ship, *and the mention is fresh: posted within 24 hours of the
    ticket, and not yet answered by the ship*";
  - rule 4 gains: "Otherwise `read`, basis `none`*, or basis `old` or `answered` when rule 2 failed only on
    freshness*".
- **Ship status,** docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md:
  - line 60, S5 step 4 (line 165), the "Owner mentions" bullet (line 174) and R25 (line 402): "owner mentions never
    defer" becomes "*fresh* owner mentions never defer". An old owner mention decides `read`, so it may defer like
    any read mention. An answered one never reaches the defer step: only a request with `decisions` can defer, and
    with `decisions` step 1 returns `answered` first. No authority moves: the session is told `would_be: "read"`.
- **Watch default,** docs/superpowers/specs/2026-10-14-watch-default-design.md line 133: "an owner's mention still
  builds through the watcher (S5)" becomes "an owner's *fresh* mention still builds through the watcher (S5)".
- **Grants step 3** (Serenity's branch): S6's "Owner builds are unchanged" becomes "Owner builds are bounded the same
  way (fresh owner mentions spec)", and G15 cites `_mention_stale`. Serenity makes that amendment in her branch.

## Order with grants step 3

This spec's code lands first, and 3c calls `_mention_stale` and reuses the `old` and `answered` basis values for a grant
mention that fails only on age or answered (agreed, room message 1b20ddd1). If 3c reaches main first instead, it adds
`_mention_stale` exactly as specified here, and this branch keeps it unchanged. Step 3's G19 rewrites the same read-mode
sentence (watch.py:40-42) for non-owner authors. Whichever lands second keeps both: the `limited` sentence replaces the
last sentence when `limited` is set, and G19's sentence is used otherwise.

## Requirements

- **R1.** An owner mention posted within 86,400 seconds of the ticket, which the ship hasn't answered, gets `build`,
  basis `owner`, as today. Exactly 86,400 seconds still builds.
- **R2.** An owner mention posted more than 86,400 seconds before the ticket gets `read`, basis `old`, root `None`,
  footer empty.
- **R3.** An owner mention the ship has answered (`_answered`) gets `read`, basis `answered`, when the watcher asked
  without `decisions`. With `decisions` the answer stays `{decision: 'answered'}`, as today.
- **R4.** A `created` that isn't a finite `int` or `float`, or is more than 86,400 seconds in the future, gives `old`
  when rule 2 would otherwise build. It never raises.
- **R5.** Mentions by anyone other than the owner, resident ships, and the order of `issue_ticket`'s steps are
  unchanged. A running ticket sent again returns as issued.
- **R6.** A downgraded mention is deferred like any read mention when the watcher asked with `decisions` and the ship
  has a writable session on watch.
- **R7.** `_mention_stale` is the only place the bound and the answered check are combined for builds, so 3c can call
  it. This is checked in review, not by a test.
- **R8.** The read prompt for `old` and `answered` says why, as in "The change". For every other ticket the prompt is
  unchanged, byte for byte.
- **R9.** Source labels are unchanged: a reply posted under a downgraded ticket has source `{kind: run, mode: read,
  basis: old}` (or `answered`) and the label "read-only run".

## Testing

Peer, in peer/tests/test_tickets.py, using the store's injectable clock. Each test names the wrong implementation it
catches; the ones marked *guard* pass on today's code and fail on a plausible wrong one.
1. Owner mention: at `created + 86400`, `build`, `owner` (guard: `<` in place of `<=`). In a fresh store, at `created +
   86400.5`, `read`, `old`, no root, no footer (fails today). A reply posted with that ticket has source mode `read`,
   basis `old` (R9).
2. Answered. After a reply by another ship with `reply_to`, and after the ship's own kind message, `_mention_stale`
   still returns `None` (guards: a looser answered query). It is called directly, because issuing a ticket there
   would leave a running build ticket that later asks get back. Then the ship's own `reply_to` answer, on a second
   owner mention with no ticket yet: without `decisions`, `read`, `answered` (fails today); on a third, with
   `decisions`, the `answered` decision and the deferral row gone, as today.
3. A message whose `created` is set by hand to infinity, and one set to the text `'abc'`: `read`, `old`, with no
   exception (fails today: both build; a naive `math.isfinite` would raise on the text).
4. A `created` set to now plus 90,000 seconds: `read`, `old`. Now plus 60 seconds still builds (guard: a bound that
   rejects every future time).
5. An old owner mention, `decisions` asked, while the ship holds a writable watch: `defer` (fails today: it builds).
   The session's unread item for it carries `deferred.would_be` `read` (inbox.py:165).
6. A builder ticket issued at 23.5 hours, sent again at 24.5 hours, inside its two-hour lifetime: the same `build`
   ticket (guard: a recheck on resend).
7. A non-owner's mention 48 hours old: `read`, `none`, as today (guard: a bound applied to everyone).
8. Old and answered together, without `decisions`: `old` (guard: the check order).

Agent, in agent/tests/test_watch.py and agent/tests/test_watch_deferral.py:
9. `build_prompt` in read mode with `limited='old'` and with `limited='answered'` contains its sentence, and neither
   "can ask the ship's owner" nor "from the ship's owner". With `limited=None`, and in build mode with any value, the
   prompt equals today's, byte for byte.
10. A watcher handed `{mode: 'read', basis: 'old'}` passes `limited='old'`. One with basis `none`, `grant` or no basis
    passes `None`.
11. The full-list path: a current watcher whose deferred list is full asks without `decisions`, gets `{mode: 'read',
    basis: 'answered'}` from the fake station, and passes `limited='answered'`.

## Security

- The change only narrows: some tickets that built become read, and none that read become build.
- The bound uses the station's clock and the stored `created`, both written by the station. No client value is
  involved. The owner's messages are local, so federation's clamped times don't reach this rule.
- A `created` that is text, infinite or more than a day ahead reads `old`, never an exception. Whoever can edit rows
  controls the Pi anyway; this only keeps a bad row from building or from failing the request.
- The prompt sentences are fixed strings. Nothing from the message goes into them.

## Deploy

Under section 2: approved in the room, and the Pi suites passing. Back up the database first. No schema change: basis
is free text, and `old` and `answered` are new values. Restart the lighthouse and door for the station, and the ship,
odo and wormhole watchers for the prompt. Each machine's watcher gets the prompt sentences when it updates.

Live check, needing no person's login: copy the live database with SQLite's backup API (the backups tool, or the same
call the merge backup uses; never `cp`, because the database runs in WAL mode), open the copy with a throwaway store in
the test style, never the live file, issue tickets there for one old owner mention and one fresh one, and check `old`
and `build`. Delete the copy afterwards.

## Known limits

- **24 hours for owners as for grants.** A watcher down for more than a day answers its owner's mentions read-only, and
  the owner asks again. That is the point. The number matches step 3's G15, so the two never disagree on a mention.
- **Watchers on older code.** One that uses tickets but predates `limited` gets `read`, basis `old` or `answered`,
  and runs the plain read-only prompt, which says the author "can ask the ship's owner", who is the author. Safe, only
  confusing, until that machine updates. A watcher from before tickets decides locally that the owner builds, so it
  still builds old owner mentions, and the station can't stop it (API.md: "replies from watchers too old to use
  tickets"). Such a ship needs `make dock` first.
- **Decided at issue.** Without `decisions`, an answer posted after a builder ticket was issued doesn't stop that build:
  a resend returns the running ticket (step 2), as today.
- **The clock.** A clock stepped back makes a message look younger, or from the future. A step back of X makes
  messages posted about X ago, within a day either side, look fresh, so they build: after a 3-day step back, a mention
  posted 2.5 days ago looks half a day ahead. A clock stepped forward makes messages look older, and they read.
  Neither widens what a ship may do beyond today's rule, under which every owner mention builds.
- **Not a refusal.** An old owner mention still gets an answer, read-only. A long outage can bring one read-only reply
  per old mention, as non-owner mentions already do today.

## Out of scope

- Grant builds: step 3's 3c calls `_mention_stale` (R7) and reuses the basis values, as agreed.
- Directs (spec A step 5).
- Any change to deferral bounds, unread or the hook.

## Review map (revision 2: the D8 review of 2688265)

| Finding | Change | Where |
|---|---|---|
| S1: `answered` reaches current watchers with a full deferred list | Says so, and test 11 | Where this sits 2; The change; Testing 11 |
| S2: the run can't see the answer | The sentence no longer asks it to point to the answer | The change |
| S3: both sentences named the owner | Neither names the author, so both fit 3c | The change; Testing 9 |
| S4: ship status says owner mentions never defer | Amended: fresh owner mentions never defer | Amended rules |
| S5: API.md names only basis `none` | API.md and the agent README updated in the build | The change (Docs) |
| S6: order with grants step 3 | This code lands first, or 3c adds the helper as here; G19 and this sentence both kept; Serenity amends step 3's S6 | Order with grants step 3; Amended rules |
| S7: test 6's times were past the lifetime | 23.5 h and 24.5 h | Testing 6 |
| S8: watchers from before tickets | Named in Known limits | Known limits |
| N1: not every test fails today | Each test names what it catches; guards marked | Testing |
| N2: text `created` would raise | Type checked first; text in test 3 | The change; R4; Testing 3 |
| N3: a far-future `created` builds | Within a day either side; test 4 | The change; R4; Testing 4 |
| N4: test 8 holds only without decisions | Says so | Testing 8 |
| N5: R9 untested; R7 untestable | R9 in test 1; R7 checked in review | R7; R9; Testing 1 |
| N6: an answer after issue doesn't stop the build | Known limits | The change; Known limits |
| N7: copy the live database safely | SQLite backup API, never `cp` | Deploy |
| N8: resend path line numbers | 57-61 | The change |
| Re-check R1: test 2 couldn't run as one sequence | Uncounted answers checked on the helper; second and third mentions | Testing 2 |
| Re-check R2: an answered owner mention never defers | Says only an old one may | Amended rules |
| Re-check R3: `would_be` is on the unread item | Test 5 reads it there | Testing 5 |
| Re-check R4: the watch-default spec's line 133 | Amended too | Amended rules |
| Re-check R5: "a fresh owner's mention" | "an owner's fresh mention" | The change (Docs) |
| Re-check R6: a step back of more than a day | The clock limit says how | Known limits |
