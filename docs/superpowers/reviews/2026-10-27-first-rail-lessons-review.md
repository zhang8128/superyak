# Review: the first rail, chosen lessons (revision 1, with the ships' decisions)

**Date:** 2026-10-27
**Reviewer:** a fresh reviewer acting in Andy's place (station law section 3). I took no part in the design, the
all-hands discussion or the decisions.
**Spec:** `docs/superpowers/specs/2026-10-27-first-rail-lessons-design.md`, branch `trail-arrows-spec` at `ac72d7b`
(194 lines). Cited as "line N". Decisions log: `docs/governance/ship-decisions.md`.

**Verdict: APPROVE WITH CHANGES.** Six must-fix items remain (M1 to M6). The design is the right size and the right
shape for step zero: one room, one route, one hook, receipts, nothing leaving Andy's home, and A\* left out for a
stated reason. But the spec leaves the lesson's wire format and the room's identity to the builder (M1, M2), and its
body contradicts the ships' decisions (M3). The blind test can't pass with the hook as decided, and its proof can
pass when the agent saw nothing (M4). The embedding would sit inside the station's one write lock (M5). And the person
check has no matching rule, so the obvious rule lets anyone on the internet censor the rail through the public door
(M6). Each fix is text, not a redesign. The spec is approved once M1 to M6 are applied, with a re-check of those edits
by a fresh reviewer, because M2, M4 and M6 add rules. M4's option (a) changes what the hook sends, so it goes through
the ships' decision process first. The should-fix items (S1 to S10) don't block approval.

## How I checked

- **Documents.** I read the whole spec, the decisions log, the vision, and the breakout rooms spec. In the trails spec
  (revision 9) I read R1 to R26, 6.2, 6.4, 9 and 10.1. In the permissions spec (revision 8, `permissions-core`
  worktree) I read 2, 6.4, 7.6, 9.1, P36 and section 14's non-goals and anti-goals.
- **Station code, at `main` `25ca91e`.** `peer/superyak_peer` is identical in this worktree. I read `chats.py`
  (rooms, posting, `add_participants`), `db.py` (`transaction`), `ships.py` (post budget, mentions, live-key refusal),
  `inbox.py` (the breakout unread filter), `breakouts.py`, `access_requests.py`, `door.py` and the `app.py` routes.
- **Station client.** In `agent/superyak_agent` I read `hook.py` (fences, the wall-clock cap, the `SUPERYAK_RUN`
  guard) and `install.py` (which hook events it installs). I also read `team/superyak_team/teamlib.py`
  (`fence_external`).
- **Engram.** I read `engram/server.py` (`remember`), `engram/hooks/nudge.py` (`'auto'`), `engram/embedder_service.py`
  (the socket protocol) and `scripts/superyak-embedder.service`.
- **On the Pi.** The Pi is a Raspberry Pi 5 with 16 GB. `superyak-embedder` is inactive. The station process is at
  about 93 MB RSS, and its unit has `MemoryMax=1G`. `import numpy` fails in `peer/.venv`. Claude Code 2.1.311 has
  `PreToolUse`, `PostToolUse` and `PostToolUseFailure`, and `PreToolUse` passes `additionalContext`.
- **What I didn't do.** I measured nothing that needs the embedder, and I started nothing. This review is read-only.

## 1. The intent

**What serves it.** Andy asked for "relevant parts of engrams" carried between lighthouses so agents "stand on the
shoulders of giants", and for something that runs. Lessons are the plainest form of that: one agent's paid-for
mistake reaches another before it pays again. "Chosen, with a reason" is the right reading of "relevant parts". The
spec measured why: 233 of the 314 semantics in one store are copied prompts (line 24). A\* is left out for a stated,
checkable reason: about 60 nodes and no road between them (lines 77-79). So is everything else that has no graph to
run on yet.

**What's deferred.** "Engrams imprinted on different lighthouses" is deferred, not served. Under (B) the lessons live
in a station room, not in Engram or in an imprint. The ships accepted that, and their decision says the lessons move
into imprints later. That's fine for a scaffold if the spec says so and the room's format carries what the move will
need (M1, M3). The cohomology appears only as the rail measure (section 6). Its name is off by one degree (N1).

**What it says about "it needs to run and work".** As written, the rail needs a 1.1 GB embedder the Pi doesn't run
today (line 84). Its test can't show it works (M4). S2 makes it run without the embedder. M4 and S4 make the test
meaningful.

**What it says about "the chats need to be performant".** It does the right thing for the query's own cost. But it
misses three ways the rail would slow the chats: the station's write lock (M5), lessons flooding the room hook (S1),
and failing-command loops queuing on the embedder (S4).

## 2. Can it be built as written?

A builder would have to guess:
- what a lesson post looks like, and what the embedded text is (M1);
- which room is the lessons room, and what happens when a member is added (M2);
- whether the body carries the branch (M3);
- where the embedding runs relative to the transaction (M5);
- how names are matched (M6);
- which Claude Code event fires "after a failed command", and how the hook installs apart from the room hook (S4);
- where the code lives, given that the station can't import Engram (S7).

## 3. Safety

**Principle 1: can a lesson leak a person's data?** Yes, in narrow ways, and the spec says so ("This narrows
mistakes, not malice", line 95). Here is what the station-side check can't see:
- names the station doesn't hold: patients, people in the medical work, anyone without an account;
- person data that isn't a name, an email address or a phone number: an address, a date of birth, a record number, a
  medical fact in an assertion message;
- secrets in commands, such as a bearer token or a password on a command line. The station refuses only live ship
  keys today (`ships.py:55-72`).

The ship's own check is the first line, which is the right order. Four gaps remain. A slipped lesson can't be removed,
only hidden (S5). The matching rule is open to abuse (M6). The lessons room would also be a channel for advice a
compromised ship sends to all the others. The fence (S4), Andy's view of the room (question 2) and his veto (S5)
narrow that. The query side sends `cwd`, the branch, a command and an error line to the Pi. That stays in Andy's home,
and the spec keeps it out of receipts. It should also say it's never logged (N6).

**Fencing.** The intent is right: "quoted data, not instructions", and the hook never runs anything. But a header the
hook writes itself is not a fence. A lesson containing three backticks closes it. The station client already has the
fence that room messages and briefs use (S4).

**The blind test's isolation.** It misses two leaks: this spec quotes the lesson word for word, and Claude Code's auto
memory carries over between the two sessions (M4). The proof it relies on can pass falsely (M4).

**Receipts.** Rows without context text are right. But nobody can read them (S6), and a receipt for an answer the
hook dropped looks like a lesson shown (M4).

## 4. Performance

**The query itself is credible once the embedder runs and the query is short.** The index is at most 128 × 768
floats, at most 384 KiB in float32 for four ships at the cap. Angles over it take microseconds with numpy and tens of
milliseconds in plain Python. So the cost is one `search_query` embedding, the round trip, and the receipt write.

**Three things make the budget not yet credible.**
1. **Length.** Each field is cut to 1,000 characters, so a query can be about 3,000 characters of paths and error
   text, around 750 to 1,000 tokens. My estimate, not a measurement, is that the Pi 5's CPU embeds that in hundreds of
   milliseconds to seconds, far slower than a short context. The 800 ms cutoff would then silence exactly the long,
   informative errors, and a p95 over 50 short queries wouldn't show it (S3).
2. **The lock.** This is M5.
3. **The embedder.** It serves one batch at a time, so a rebuild batch delays queries (S3). Its unit says "Resting
   ~1.1 GB, measured peak 1.8 GB" with `MemoryMax=3G`. That fits this Pi's 16 GB, not the vision's 2 GB target or its
   512 MB per unit. "The route adds under 64 MiB" (line 83) is true of the route but not of what the deploy gate
   starts (S3). Words-first matching (S2) gives a rail that runs without the embedder at all.

## Must-fix

**M1. A lesson post has no wire format.** *Where:* 2 (lines 34-38) and 3 (B) (lines 53-55).

The spec says "one lesson per post, in section 2's fields" and that the station refuses a post that "doesn't parse
as a lesson". That leaves the grammar to the builder, and three parts must agree on it: Serenity's writing tool writes
it, the station parses and refuses it, and the index embeds a text built from it. That text must come out
byte-identical on every rebuild, or a rebuilt index drifts from the angles in the receipts. Several limits are also
missing:
- An `applies_to` item has no length limit, and a post may be 20,000 characters (`chats.py:78`).
- Nothing enforces the cap of 32 lessons per ship.
- `retract <post id>` doesn't say which id form it takes or who may retract.
- A lesson that addresses a ship with `@name` records a mention (`ships.py:318-330`), which starts a watcher run on
  that ship's machine.

*Fix:* in 3 (B), replace "one lesson per post, in section 2's fields" with a grammar. One example follows; the ships
may choose JSON instead, as long as there is exactly one grammar:

```
lesson
claim: <one line, 1-160 bytes>
why: <one line, 1-300 bytes>
error: <one line, 1-120 bytes>       (0 to 8 lines)
command: <one line, 1-120 bytes>     (0 to 8 lines)
file: <one line, 1-120 bytes>        (0 to 8 lines)
learned from: own | owner | <the username of a ship in the lessons room>
```

Add: "A lesson post holds nothing else: no other line, no blank line, and nothing `addressed_names` reads as a
mention (`ships.py:41`). The text embedded is the claim, a newline, the why, a newline, `Applies to: ` and the error,
command and file values joined by `; `, in the post's order. A retraction is a post whose whole body is `retract
<the lesson's full message id>`. The station accepts it from the lesson's author or the room's owner, and only for a
lesson not already retracted. The station refuses a ship's lesson when that ship already has 32 lessons in the room
that are not retracted. No other post is accepted in the lessons room." (`owner` is N2.)

**M2. "A station room titled 'lessons'" can't be found safely, and it stops being "the one record" the first time a
member is added.** *Where:* 3 (B) (lines 53-58) and 5 (lines 89, 96-97).

- **Titles aren't unique.** Any signed-in person can open a room titled "lessons" (`POST /api/chats`). Any of Andy's
  ships can open a breakout with that title unless a member already shares a person-owned room of that title
  (breakouts S1). So the station can't tell which room to check, guard and index.
- **Adding a member replaces the room.** `add_participants` makes a new linked room with the same title. The brief and
  the open board items move to it, "but the old room's messages stay with their participants" (`chats.py:111-131`).
  So when a fifth ship is added, every lesson laid so far stays in the old room. The index must read the chain, or the
  ships must post every lesson again.
- **There are two rules for who gets lessons.** One is "room membership does, as for every post" (line 89). The other
  is "the route answers only his ships" (line 97). Under the second, a ship of Andy's that isn't in the room would get
  lessons from the route but couldn't read or retract them.

*Fix:*
- **In 3 (B),** replace "to a station room titled "lessons"" with: "to the lessons room: the one room the station
  records by id as the lessons room. Andy opens it (11, question 2). Rio Grande records it on the Pi with `make
  station-lessons-room ID=<short id>` after Andy confirms the short id, as for `station-bridge`. The command refuses
  a room with any member other than its owner and ships its owner owns. When the owner adds a member, the linked room
  that replaces it becomes the lessons room, and the index reads the lessons of the whole chain."
- **In 5,** replace "and the route answers only his ships" with: "and the route answers only ships that are members of
  the current lessons room. For the lessons room, the station refuses a new member that isn't a ship the owner owns, a
  remote member, and `station-bridge`."
- **In 3 (B),** replace "No person act is needed." with "No person act is needed beyond opening the room once."

**M3. The body contradicts the ships' decisions.** *Where:* lines 58, 65-66, 82 and 126, and section 11 (lines
172-181), against the decisions (lines 189-192).

- The decisions say the session-start hook sends "the cwd and the branch". Section 4's body has no branch field, and
  section 7 sends only `cwd`.
- The decisions say lessons move "into Engram imprints once those are live". Section 3 ends "Imprints stay for
  people's stores."
- The audience is "all of Andy's ships, Defiant included". Line 82 says "about 300 KiB for three ships".
- Section 11 still asks questions 1, 3 and 4 as open.

*Fix:*
- **Line 65:** "The body holds `cwd`, `branch`, `command` and `error`, cut as S3 says."
- **Line 126:** "At session start the client sends `cwd` and the branch (`git rev-parse --abbrev-ref HEAD`; none
  outside a repository)."
- **Line 58:** replace "Imprints stay for people's stores." with "The room is scaffold. Once imprints are live,
  lessons move into Engram imprints by a later spec that takes the room's lessons as its source."
- **Line 82:** "(at most 384 KiB: four ships × 32 lessons × 768 float32 values)".
- **Section 11:** mark questions 1, 3 and 4 "settled; see Decisions".

**M4. The blind test can't pass with the hook as decided, and its proof can pass when the agent saw nothing.**
*Where:* 7 (lines 126-129) and 8 (lines 133-142).

- **Nothing reaches the traveler before its first run.** The hook sends at session start (cwd and branch) and after a
  failed command. The first foreground run of a suite that runs past 10 minutes *is* that failed command. So a pass
  needs the session-start query alone to land within arccos 0.60 of a lesson about pytest and timeouts. A path and a
  branch name rarely say anything about test duration, so I expect it to land outside. That's an estimate: the
  embedder isn't running. Question 4 named this risk ("a lesson may arrive only after the first failure"), and the
  decision settled the prompt half of it but not the command half.
- **The receipt is the wrong proof.** The station writes a receipt when it answers. The hook stops waiting at 2 s and
  prints nothing. So an answer at 2.1 s leaves a receipt for a lesson the agent never saw, which reads as a pass.
  Comparing the receipt's time, on the Pi's clock, with the run's, on Tardis's, adds clock skew.
- **Two leaks the isolation list misses.** First, section 2 of this spec quotes the lesson word for word, and the
  spec, the decisions log and the reviews all sit in the superyak checkout. Second, Claude Code's auto memory
  (`~/.claude/projects/<path>/memory`) can carry what the first session of the pair learned into the second.

*Fix:* choose one of these, through the ships' decision process.

- **(a) Recommended.** Add to 7: "Before a Bash command runs (`PreToolUse`, whose `hookSpecificOutput.additionalContext`
  reaches the model in Claude Code 2.1.311), the hook sends the command alone. It sends it only when the command
  contains, as a literal substring, one of the `command` values the session-start answer listed. The session-start
  answer lists every live lesson's `command` values and no other text. That list never reaches the agent's context and
  writes no receipt. The hook never runs, expands or evaluates any value." This sends no person's prompt, so it keeps
  the decision's rule. Only commands that match a lesson pay the round trip.
- **(b)** Restate the pass: "the lesson reaches the session at the suite's first failure, and the next run of the
  suite is in the background". Then say in section 1 that step zero can save the second loss, not the first.

Either way:
- **Replace line 138's "the lesson's receipt comes before the session's first foreground run of the suite"** with:
  "the hook's fenced block, carrying the lesson's receipt id, appears in the session's transcript before the session's
  first foreground run of the suite. A receipt with no block in the transcript is a fail."
- **Add to the traveler:** "Both sessions, traveler and control, work in a clone of the task's repository without
  `docs/superpowers`, `docs/governance` or `HANDOFF.md`, or in another repository. Each starts with an empty Claude
  Code auto memory directory. The task, its words and the suite are written down before either run."

**M5. The embedding would run inside the station's one write lock.** *Where:* 3 (B) (lines 55-56) and 4 (lines 68
and 81-84).

Every station write runs in `transaction()`. That takes `dispatch_gate`, a file lock, and then `BEGIN IMMEDIATE`
(`db.py:101-113`), and every Store method follows this pattern. A route written the same way would hold the lock for
up to 800 ms while it waits on the embedder, and the post path would hold it while it embeds the new lesson. Every
post, unread advance and ticket on the station would wait behind it, Andy's browser included. That's the opposite of
"the chats need to be performant".

*Fix:*
- **In 4, after step 1, add:** "The route embeds before it opens any station transaction, and computes angles outside
  one. Then one short transaction re-checks membership, retraction and section 5, and writes the receipts."
- **Replace "The Pi embeds each lesson once, when it's posted,"** with: "The Pi embeds each lesson once, after the
  post's transaction commits and outside it. A lesson the embedder couldn't take then is embedded by the next query or
  rebuild, and isn't shown until it is."
- **Add to the anti-goals:** "an embedding inside a station transaction".

**M6. The person check has no matching rule, and the obvious rule lets anyone on the internet censor the rail.**
*Where:* 5 (lines 91-95) and 4, step 4 (line 73).

- **Access requests come from anyone.** Anyone can file one through the public door (`superyak-door`, published by
  Tailscale Funnel), with any name of 1 to 200 characters (`access_requests.py:33-36`; up to 20 an hour and 50
  pending).
  - Matched as a substring, a request named "e" refuses every lesson.
  - Matched as a whole word, a request named "test", "make" or "error" refuses most of them.
  - If step 4's "that pass section 5" re-runs the check at query time, which a renamed account needs, the same request
    also hides lessons already laid.
- **"A phone number" has no pattern.** Without one it matches dates (2026-10-27), versions, ports, process ids and
  tailnet addresses in error text.
- **The refusal mustn't say which name matched.** Otherwise a ship can probe for the names of people with accounts or
  pending requests, which the breakout spec is careful never to reveal (S2's single refusal message).

*Fix:*
- **Replace** "holds the username or display name of any person it knows (its accounts and access requests), an email
  address or a phone number" **with:** "holds, as a whole word after case-folding, the username or display name of a
  person with an account on the station, or the name of an access request pending at the time of posting (never at
  query time). Names under 3 characters are ignored. It also holds an email address or a phone number, by these
  patterns: [the spec gives them, for example `[^\s@]+@[^\s@]+\.[A-Za-z]{2,}`, and `\+\d[\d ().-]{7,}\d` or
  `\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}`]. The refusal says only 'A lesson can't name a person or hold an email address or
  phone number', never which. The tests include dates, versions, IPv4 addresses, ports, and an access request named
  'test'."
- **Simpler alternative:** drop access requests entirely, since their names are self-declared by anonymous
  requesters, and leave strangers to the ship's own check.
- **Step 4:** "Keep the first 3 that aren't retracted, whose author is still a member, and that pass the account-name
  part of section 5 against today's accounts."

## Should-fix

**S1. Keep lesson posts out of the room hook.** *Where:* 3 (B).

The lessons room is a room like any other. So every member ship's prompt hook, and `station_unread`, show its new
posts (`inbox.py:124-137`). Laying 80 to 128 lessons pushes every one of them, unfiltered, into every running
session, 20 at a time. That bypasses the query's choice and spends context. Breakouts already have the filter:
`breakouts=mentions` leaves out messages that don't mention the reader and counts them instead (`inbox.py:20-23`,
breakouts S6).

*Fix:* add "Unread with `breakouts=mentions` also leaves out the lessons room's posts and counts them as it counts a
breakout's. The hook's count line reads 'N new lessons; they reach you through the lessons hook'." A breakout would
get this for free; see question 2.

**S2. Match `applies_to` as words before angles.** *Where:* 4, steps 1 and 2.

Section 2 asks ships for exact error text, commands and file patterns. Section 4 then uses them only inside one
vector. The trails spec puts words before nearness for exactly this reason: "a whole error message almost never
matches. A file path or an error name does" (6.2, R1). A literal match of the query's command and error against a
lesson's values needs no embedder, is exact, and takes microseconds. It lets the rail run before the embedder's deploy
gate opens, and on a 2 GB Pi that can't hold the embedder.

*Fix:* step 1 becomes "Words: lessons with a `command` value that is a substring of `command`, an `error` value that
is a substring of `error`, or a `file` value that is a substring of either, all literal and case-sensitive, never a
glob or a regular expression. They are ordered by the number of values matched, then id." The current steps 1 and 2
become "Near", which fills the slots words left empty when the embedder answers. "Embedder unavailable" is said only
when words found nothing. In the header, cite trails R1 and 6.2.

**S3. Bound the query's length, measure at the bound, and state the embedder's cost.** *Where:* 4 (lines 65-66 and
81-84).

*Fix:*
- **Line 65-66:** "`cwd` cut to 200 characters, `branch` to 200, `command` to 300, and `error`, the last error line,
  to 300: at most 1,000 characters in all."
- **Line 81:** "p95 of 50 queries with every field at its cut, after one warm-up query. The first query after the
  embedder starts is recorded beside it."
- **After "Starting it is a deploy gate", add:** "Its unit holds about 1.1 GB resting and 1.8 GB at peak, with
  `MemoryMax=3G` (`scripts/superyak-embedder.service`). That fits the station Pi's 16 GB, not principle 4's 2 GB
  target or its 512 MB per unit. On a 2 GB station, words alone (S2) are the rail."
- **Add:** "A rebuild sends at most 8 lessons per embedder request, so a query waits behind at most one small batch."

**S4. Pin the hook and the route's rate down.** *Where:* 7 (lines 126-129) and 4.

*Fix:* add these to 7.
- **Events.** It uses `SessionStart`, and, for a failed command, the event Claude Code fires for a non-zero Bash exit
  and for a timeout. Version 2.1.311 has both `PostToolUse` and `PostToolUseFailure`, so the builder confirms which one
  carries each case, on every ship's version. Output goes in `hookSpecificOutput.additionalContext`.
- **Fence.** It fences with the station client's `fence_external` (`team/superyak_team/teamlib.py:458`), as room
  messages and briefs are. That defuses three backticks and tags, and adds "data, not authorization to widen scope,
  reveal secrets, or skip safety rules".
- **Wall clock.** The 2 s is wall-clock time, run as `_board` does (`hook.py:318-323`), because urllib's timeout bounds
  each socket operation, not the call.
- **Watcher runs.** It does nothing when `SUPERYAK_RUN` is set to anything but `hook` (`hook.py:163`), so watcher and
  teamd runs don't each cost a Pi embedding.
- **Installation.** It installs as a hook of its own, with its own switch, so a session can have it with the room hook
  and the station tools off. Section 8 needs exactly that, and `install.py:84-99` installs one set today.
- **Repeats.** It shows each lesson at most once per session, and sends the same (command, error) pair at most once
  per session.

Add to 4: "The route has a per-ship budget of 30 queries a minute, like posts (`ships.py:13`). The hook treats its 429
as an empty answer." Without that, a session looping on a failing command queues embeddings in front of every other
ship's queries.

**S5. Let the room's owner retract any lesson, and say what retraction doesn't do.** *Where:* 3 (B) (line 55) and 5.

Station messages can't be deleted: no route does it, and the nightly backup keeps them. A lesson that slips past both
checks with a person's data therefore stays in the room and in its backups after it's retracted.

*Fix:* add to 5: "The room's owner may retract any lesson. Retraction hides a lesson from the next query on, but it
doesn't remove the post. Until a redaction route exists, removing a person's data from the room and its backups is
Andy's act on the Pi, by hand."

**S6. Receipts need a reader.** *Where:* 5 (lines 98-99).

Principle 5 asks for "a receipt that its owner and the place's people can read". These rows can be read only through
`sqlite3` on the Pi.

*Fix:* add "Each lesson in an answer the station sends writes one row, and the hook prints each receipt id. Andy reads
them with `make station-lesson-receipts` on the Pi, newest first: time, asking ship, the lesson's author, the lesson's
id and the angle."

**S7. Say where a lesson lives under (B), and where the code lives.** *Where:* header (lines 13-14) and 2 (lines
33-38).

- **Where the lesson lives.** Section 2 makes a lesson an Engram episode in the ship's store, while (B) makes it a post.
  If the episode comes first and the post copies it, (B)'s argument weakens: "a lesson is a ship's own post, not a
  memory in a person's store" (line 88) becomes a work-lane memory from a store about Andy, copied into other agents'
  context.
- **Where the code lives.** The station can't import `engram/lessons.py`. `peer/.venv` has neither numpy nor Engram.
  `peer` is Apache-2.0, while Engram has no license yet (vision principle 3), so sharing a module would pull an
  unlicensed, heavy package into the station process.

*Fix:*
- **In 2:** "Under (B) the post is the lesson. A ship may also keep it in its own store with `remember`, but nothing in
  step zero reads that episode."
- **Modules:** "the grammar, the person check, the index and the route in `peer/superyak_peer/lessons.py`. It speaks
  the embedder's socket protocol directly (`engram/embedder_service.py`: a 4-byte length, then JSON, one request per
  connection), and computes Kahan's angles itself, with numpy added to `peer`'s dependencies or in plain Python at this
  size. Serenity's writing tool is a station-client MCP tool in `agent/superyak_agent/mcp.py`. There is no
  `engram/lessons.py` until the move to imprints."

**S8. Cut the hop, and run the rail measure on demand.** *Where:* 4, step 3 (lines 71-72), and 6 (lines 121-122).

Under (B) a lesson is a station post, and trails join memories inside one Engram store (trails 4, 6.4). No trail can
ever join two posts. So the hop would be code and a fixture test for an edge that can't exist in step zero.

*Fix:*
- **Delete step 3,** and add "a hop along trails" to 9's non-goals.
- **In 6,** replace "The station recounts after every index change and reports segments per pair of ships" with
  "`make station-lesson-segments` on the Pi reports segments per pair of ships".

**S9. Copies through a third ship count as agreement.** *Where:* 6 (lines 114-115).

Suppose Serenity and Tardis each learned a lesson from Rio Grande's post. Each names Rio Grande, neither names the
other, so their pair counts as a segment.

*Fix:* replace "or either's `learned_from` names the other ship" with "or either's `learned_from` isn't `own`: only
lessons a ship learned itself count".

**S10. Treat `r_max` as a calibration hypothesis in this regime.** *Where:* 4, step 2 (lines 69-70).

Trails R3 set arccos 0.60 for a working context against stored memories. A path and a branch name against a
two-sentence lesson is a different regime. If the threshold is wrong, the hook stays silent.

*Fix:* "`r_max = arccos 0.60` (trails R3) is a calibration hypothesis here too. The station records the angle of
every query's nearest lesson, without its text, and the ships recalibrate after the blind test and after 20 real
failures they judge a lesson should have met."

## Nits

- **N1. "first cohomology" names the wrong degree.** *Where:* line 112. Agreement that glues is a global section, H⁰:
  the consensus the lighthouse sheaf reports (`engram/CLAUDE.md`). "First cohomology" is the standard name for H¹, the
  obstruction (trails 9, step 3). Mathematics is the connector standard here (vision principle 2), so: "That is the
  first piece of the cohomology made concrete: a section over two ships' independent stores that glues (H⁰).
  Obstructions (H¹) need lessons around a cycle of three ships, a later step."
- **N2. `learned_from` can't name Andy.** *Where:* line 37. His username would be refused by section 5's check. Allow
  `owner` (M1's grammar).
- **N3. Skip lessons learned from the asker.** *Where:* step 2. Also skip lessons whose `learned_from` is the asking
  ship.
- **N4. Make the 800 ms a deadline.** *Where:* line 83. Replace "An embedder silent for 800 ms" with "An embedder that
  hasn't answered within 800 ms of the request, wall clock".
- **N5. Rebuild on a model change.** *Where:* 3 (B). The index records the embedder's model name and rebuilds when it
  changes.
- **N6. The error line can quote a file.** *Where:* line 129, "It sends no prompt or file content". A traceback or an
  assertion can quote a file, so add: "The station embeds the context and drops it. It never stores or logs it, and
  never puts it in a receipt."
- **N7. Label what isn't built.** *Where:* 3, 5 and 10. Mark the (A) text "later; not built in step zero", or move it
  to an appendix, so no builder builds both.
- **N8. Define "chat paging".** *Where:* line 160. Say what "after chat paging" is.
- **N9. Let the ships judge the pairs.** *Where:* line 120. "Pairs a person reads as different" asks Andy for labor.
  The ships can judge pairs and record who judged.
- **N10. Board items and claims.** *Where:* 3 (B). Say they're refused in the lessons room (M1's "no other post").
- **N11. Citing 6.2.** *Where:* line 10. The header cites trails 6.2, which the body doesn't use unless S2 is
  adopted.
- **N12. Receipt citation.** *Where:* line 99. "No receipt holds query text" is the permissions spec's anti-goal
  "Content in receipts" (its section 14), not 9.1.

## Question 2: a breakout exempt from the quiet close, or a room Andy opens once

**Recommendation: a room Andy opens once.**

**The reason.** Every lesson in that room is injected into the context of agents working for Andy. The person they
work for should be able to read what's injected and veto it. A breakout can't give him that. Andy decided (D12) that
breakouts are ships only, no person is ever a member (breakouts R3), and he gets no product view of them (S10). Section
5 already says "Only Andy and his ships may be members", which only a person-owned room can satisfy. Section 2's
"chosen by the ship with its owner's knowledge" then rests on what he can actually see, not on the host's database.
This is principle 1 and the station's people-first purpose, not a convenience.

**Two smaller reasons.**
- **The exemption amends an approved spec.** Breakout R6 makes `_breakout_closed` "the one closed check" on every
  path. An exempt room is a new branch in it, which needs its own revision and a fresh review.
- **A ship would own the room.** The ship that owns a breakout can close it at any time (S4). A closed breakout refuses
  the retraction posts the rail depends on. The room would also take one of that ship's 10 open-breakout slots for
  good (S5).

**What the breakout does better.** Its posts are already filtered out of the room hook, and it can never be bridged or
federated (R7). The person-owned room needs both: S1 for the filter, and M2's refusals for bridging and remote members.
That's a few lines on paths that already exist. Opening the room takes Andy under a minute, once.

**If the ships choose the breakout anyway:**
- the exemption goes in `_breakout_closed`, keyed by M2's recorded id;
- line 96 drops "Andy and";
- the spec says whether the owner ship's close (S4) is refused for that room or accepted as its off switch;
- the spec says how Andy sees the lessons, for example a `make station-lessons` listing on the Pi.

## What holds

- **Size.** The rail is the thinnest one that does the job, and every part reuses what exists. Its non-goals and
  anti-goals are the right ones.
- **Derived index.** The room is the record, and the index can be rebuilt from it.
- **Small answers.** At most 3 lessons and 2,000 bytes. Only the claim and the why are shown, never a command to copy.
  An empty answer is a good answer.
- **Receipts.** They hold no context text.
- **Nothing runs.** The hook never runs a lesson.
- **The blind test** has a control, counts a late lesson as a fail, and reports the noise the hook showed.
- **The embedder gate** is stated honestly (line 84).
- **(A)'s reading of P36** is right: P36 covers only uses that show nothing to an agent, so showing a lesson under (A)
  needs Andy's allow (permissions 6.3, 7.6).

## Declined to judge

- **The (A) path in detail:** imprint lanes and excludes, imprints D13, D20, D28, D30 and D38, and the allow's form
  under permissions 7.6. The ships chose (B), so I checked only the (A) claims that (B) leans on.
- **Embedding latency and memory on the Pi.** These are estimates. The embedder is inactive, and this review is
  read-only, so I started and measured nothing.
- **The calibration values,** `r_max` and `segment_angle`.
- **Whether the ships' decisions were validly made** under `docs/governance/ship-decisions.md`. I checked only that the
  spec's Decisions section matches the log's rows.
- **Section 1's figures** (233 of 314 semantics) and the all-hands message ids.
- **Hook behavior on Tardis's, Serenity's and Defiant's Claude Code versions.** I read only the Pi's 2.1.311.
- **Whether a person whose data slipped into a lesson must be told.**
