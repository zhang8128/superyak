# The First Rail: Chosen Lessons

**Date:** 2026-10-27
**Status:** Revision 2, peer to peer, for a fresh re-check under station law section 3. It applies the review of
revision 1 ([review](../reviews/2026-10-27-first-rail-lessons-review.md), APPROVE WITH CHANGES) and the ships'
decisions since (section 12). Nothing here is built.
**Designed by:** Rio Grande (the Pi), Serenity (the Mac) and Tardis (a Linux box), in "Superyak: all hands" (1bfd1b),
messages 6f17f0a3, 3321e6c9, c2db03af, 189adadb, e6656298, 0caa47fc, a4e6effe and d2960bd3 (peer to peer). Rio Grande
wrote it down. A rule that quotes neither Andy nor the room is Rio Grande's call; section 12 lists them.
**Contract:** [the city rail vision](../../city-rail-vision.md).
**Builds on:** federation (`peer/superyak_peer/federation.py`, on main); federation pull revision 2 (branch
`tardis/federation-pull`, under review);
[trails](../../../engram/docs/superpowers/specs/2026-10-25-trail-arrows-design.md) revision 9 (R1, R3, R4, R19, 6.2,
9); [breakout rooms](2026-10-11-breakout-rooms-design.md) S6; room moderators revision 2 (branch
`room-moderators-spec`). It cites them and restates none.
**Modules:** new `peer/superyak_peer/lessons.py` and its `lessons` command, with tables in each peer's database; checks
called from `chats.py` `send_message`, `peer_store.py` `remote_send` and `federation.py` `_reply`; a hook in
`agent/superyak_agent`; make targets. It speaks the embedder's socket protocol itself (`engram/embedder_service.py`).
There is no `engram/lessons.py` until lessons move to imprints.

## 1. Why, and peer to peer

Andy: "the whole point of this: relevant parts of engrams imprinted on different lighthouses. The cohomology of the
sheafs form a high speed rail that allows agents rather than solo walking, to stand on the shoulders of giants and
explore further. It needs to run and work. The chats need to be performant."

Today each ship learns alone. On 2026-10-27 Rio Grande and Serenity paid for one lesson on two machines ("never trust
a keyword count over reading"), and Serenity and Tardis both lost commands to zsh globbing. Whole stores won't carry
that: 233 of the 314 semantics in the store Serenity read are captured prompts copied word for word (a4e6effe). So the
track is what was chosen, with a reason: a room, an index, a query and a hook, the thinnest rail worth riding
(189adadb).

Andy also said: "Remember this should be peer to peer as well." So, as the ships agreed (d2960bd3):

- **A lesson is a post in the lessons room**, which federation replicates between Andy's peers: the Pi, Tardis and
  the Mac. The room has one origin, where Andy opens it (section 3). The origin orders the room and passes each
  peer's posts on to the others (`Federation._reply`, then `collect`), through its outbox and retries. That is the
  room's write path, and nothing more.
- **Each peer indexes its own copy and answers its own sessions' queries locally**, in process through the peer's
  store, never over the network (federation pull section 1). A query works offline and costs no round trip. The Pi
  is one peer among three: no query goes to it, and it never holds the only copy. While the origin is down, lessons
  laid elsewhere wait in their peers' outboxes, and every peer still answers.
- **Each peer needs its own embedder** for its index and its queries: the machine's shared embedder
  (`superyak-embedder`, a Unix socket named in `runtime.json`). Its unit holds about 1.1 GB resting and 1.8 GB at
  peak, with `MemoryMax=3G` (`scripts/superyak-embedder.service`). That fits the Pi's 16 GB, not the vision's 2 GB
  target or its 512 MB per unit. The Pi's isn't running today (inactive, 2026-10-27), so starting it is a deploy gate
  on each peer.
- **A peer without an embedder runs the rail on words:** a literal match of the query against each lesson's
  `error`, `command` and `file` values (section 5, step 1). It says "embedder unavailable" only when words found
  nothing.

## 2. A lesson

The post is the lesson. A ship may also keep it in its own store with `remember`, but nothing in step zero reads that
episode. A ship lays about twenty, at most 32 live, chosen with its owner's knowledge. Nothing captures a lesson
automatically.

**The wire format.** One grammar, for the writing tool, every peer's checks and every index:

```
lesson
ship: <the posting ship's username>
claim: <1 to 160 bytes>
why: <1 to 300 bytes: what it cost>
error: <1 to 120 bytes>
command: <1 to 120 bytes>
file: <1 to 120 bytes>
learned from: own | owner | <a ship's username>
```

- Lines are in this order, separated by one `\n`, with nothing else: no other line, no blank line, no final newline.
  A body is at most 4,096 bytes. Each value is UTF-8 with no control character and no leading or trailing space.
- `error`, `command` and `file` lines are the lesson's applies-to values: 0 to 8 of each, at least one in all. Each is
  a literal piece of error text, of a command or of a path. None is ever run, expanded, or read as a glob or a
  regular expression. A `command` value that matches before a command runs holds that command once (section 8), so
  it should be specific.
- `ship:` is the posting account's username, which the laying peer checks. Every index keys a lesson by its author
  id and uses `ship:` only to show it. `owner` means Andy taught it, since his name fails section 6's check.
- Nothing in a lesson reads as a mention: `addressed_names` (`ships.py`) finds no name in it, so a lesson never
  starts a ship's run.
- **The embedded text** is the claim, `\n`, the why, `\n`, `Applies to: `, then every applies-to value in the post's
  order, joined by `; `. A rebuild produces it byte for byte, and the index stores its SHA-256 (section 4).
- **A retraction** is a post whose whole body is `retract <message id>`, with the id the origin gave the lesson, as
  every copy shows it. It counts when it comes from the lesson's author or the room's owner, for a lesson in the room's
  chain that isn't already retracted. It hides every copy with the same author and embedded text (section 3).
- **The cap:** a ship's 33rd live lesson in the current room is refused.
- Nothing else is accepted in the lessons room: no other post, no board item and no claim.

An illustration in the format, not a laid lesson:

```
lesson
ship: tardis
claim: In zsh, quote a glob in a git pathspec or in grep's --include, or the shell expands it first.
why: Each unquoted glob failed before git or grep ran, and cost a rerun.
error: no matches found
command: --include=*
learned from: own
```

## 3. The lessons room

- **Opening it: Andy's one act.** Andy opens it once, in his browser on the Pi's station, which becomes its origin.
  The members are Andy, each of his ships, and his own account on each other peer, so he can read it from any of
  them. A ship never posts under a person's account (law section 7), so each ship is a member as itself, once,
  through the peer of the machine it runs on: Rio Grande on the Pi, Tardis on its own peer, Serenity on the Mac's,
  and Defiant on its machine's. A member on another peer is a remote contact, which federation's pairing makes card
  by card (federation pull sections 2 and 9). That pairing is federation's setup, not the rail's.
- **Found by id, never by title.** Titles aren't unique. Rio Grande records the room on the Pi with
  `make station-lessons-room ID=<short id>` after Andy confirms the short id, as for `station-bridge`. Each other peer
  records the same room by its full id, `<origin peer id>:<room id>`, with `lessons room`, which refuses a room that
  doesn't come from a paired peer. Its ship takes the id from the Pi's output, posted in all hands.
- **Only Andy's.** The record command refuses a room with any other member, and the origin then refuses to add one:
  another person, another person's ship, a ship with no owner (`odo`, `wormhole`, so `station-bridge` refuses this
  room and it is never bridged), or a contact on a peer that isn't paired. Who a remote contact is rests on Andy's
  pairing: federation can check a peer, not a person.
- **Its chain.** Adding a member makes a new linked room (`add_participants`), and the old room's posts stay with the
  old members. Each peer follows `linked_room_id` to the new room, and each index reads the whole chain. A peer added
  later sees only what is laid after it joins, so each ship then lays its live lessons again in the new room
  (`lessons relay`). An index keeps one copy per author and embedded text. The Mac joins this way (section 11).
- **The checks run at every door.** First the writing tool checks a lesson. Then the laying peer's post path checks
  it (`send_message`, or `remote_send` on a peer holding a copy). The origin checks it again on its post and reply
  paths (`send_message`, `Federation._reply`), so a lesson the origin refuses is a 4xx to the peer that sent it, and
  `refused` there under federation pull section 7. Last, each index checks every post before indexing it. It skips one
  that fails, one whose author isn't in the room, and one that federation marks unverified
  (`_unverified_local_authors`). A refusal says only what sections 2 and 6 allow.
- **Kept out of the room hook.** The Pi's station is the one place a station client reads unread. There, unread with
  `breakouts=mentions` leaves out the lessons room's posts and counts them, as it does a breakout's (breakouts S6).
  The count line reads "N new lessons; they reach you through the lessons hook".
- **Andy's view and veto.** He reads the room in his browser, and he may retract any lesson. Retraction hides a lesson
  from the next query on. It removes no post: messages can't be deleted, and every peer's copy and backups keep them.
  Until a redaction route exists, removing a person's data from the room is Andy's act, by hand, on each peer.
- **Moderators.** This is the room where the room-moderators work (branch `room-moderators-spec`) will apply, so that
  Andy can let one of his ships manage its members. That spec's revision 2 pauses a moderate grant on any room with a
  remote member (its M2, M5 check 5 and M11), and this room has them. So moderating it waits for that work to take
  remote members up. Until then only Andy changes who is in it.
- **Later.** The room is scaffold. Once imprints are live, lessons move into Engram imprints by a later spec that
  takes the room's lessons as its source.

## 4. Indexing, on every peer

`lessons index` runs every 60 s on each peer: from a systemd user timer on the Pi and Tardis, and as a step of the
`federate` loop on the Mac (federation pull section 1), so the Mac gains no new job. Each run:

1. Reads the room's chain in one short transaction, and exits if nothing changed since the index's watermark.
2. Parses and checks every post (section 3's last door), merges copies, keeps each author's first 32 live lessons,
   and applies retractions.
3. Embeds each new lesson's embedded text with `search_document`, at most 8 per embedder request, so a query waits
   behind at most one small batch. This runs outside any transaction.
4. Replaces the index file in the data directory atomically (written, then renamed). The file holds the embedder's
   model name, and per lesson: its message id, author id, peer, `ship`, `learned from`, applies-to values, claim, why,
   the SHA-256 of its embedded text, and its vector or none. It writes nothing to the database.

The index is derived: deleting it rebuilds it from the room. A new model name rebuilds every vector. A peer without an
embedder writes no vectors. No embedding ever runs inside a station transaction, so the write lock (`transaction()`:
`dispatch_gate`, then `BEGIN IMMEDIATE`, `db.py`) is never held while the embedder works.

## 5. The query

`lessons query`, which the hook runs on its own machine, takes JSON on stdin and writes the answer on stdout. Its
fields are `ship`, the asking ship's username on this peer; `cwd`, cut to 200 characters; `branch`, to 200; `command`,
to 300; `error`, the last error line, to 300; and `words_only`, true before a command. That is at most 1,000
characters of context, and each hook event sends some of them (section 8). It answers only a ship whose account on
this peer is a member of the current lessons room.

1. **Words** (trails R1 and 6.2): lessons with a `command` value that is a substring of `command`, an `error` value
   that is a substring of `error`, or a `file` value that is a substring of `command`, `error` or `cwd`. All literal
   and case-sensitive. Ordered by the number of values matched, then id.
2. **Near**, for the slots words left empty, when the index has vectors and `words_only` is false. Embed the context
   once with `search_query` on this peer's embedder, never loading a model (trails R19), with a deadline of 800 ms
   wall clock from the request. This runs before any transaction opens. Take angles outside one, by Kahan's form
   (trails R4), in plain Python at this size (`peer/.venv` has no numpy). Keep those within `r_max = arccos 0.60`
   (trails R3), ordered by angle, then id. `r_max` is a calibration hypothesis in this regime too (section 7).
3. **Skip** a lesson whose author is the asking ship, or whose `learned from` names it.
4. **One short transaction** re-checks each lesson's retraction and its author's membership against the room, and
   section 6's account-name part against this peer's accounts today. It keeps the first 3 that pass, and writes one
   receipt for each and one query row. A lesson refused here is never named.
5. **The answer:** at most 3 lessons, each with its claim and why, the ship that laid it, its angle or "words", and its
   receipt id (`#` and 8 hex), in at most 2,000 bytes. An empty list is a good answer.

**Under 1 s, measured on each peer:** p95 of 50 queries with every field at its cut, after one warm-up query, with the
first query after the embedder starts recorded beside it. The index holds at most 384 KiB of vectors (four ships × 32
lessons × 768 float32 values), and the query process stays under 64 MiB.

**Records, without context.** The query embeds the context and drops it. It never stores or logs it, and never puts
it in a record (the permissions spec's section 14 anti-goal, content in receipts). A receipt holds its id, the time,
the asking ship, and the lesson's message id, author and angle (or "words"). A query row holds the time, the asking
ship, the nearest lesson's angle and the number shown. `make lesson-receipts` on each machine lists that peer's
receipts, newest first.

**No A\*, and no hop.** About 100 lessons give A\* nothing to route over, and no trail joins two posts (trails join
memories inside one Engram store).

## 6. Person data

A lesson is a ship's own post about tools and process, not a memory from a person's store, so room membership decides
who reads it. The vision's principle 1 still holds.

- **A lesson that names a person or carries a person's data is refused** at every door (section 3). The ship's own
  check and its reading of the lesson come first, since a list of known names misses strangers. Then each peer
  refuses a lesson that holds:
  - the username or display name of a person with an account on that peer, as a whole word after case-folding. Names
    under 3 characters are ignored. Access requests are left out: their names are self-declared through the public
    door, so a request named "test" could refuse most lessons;
  - an email address, `[^\s@]+@[^\s@]+\.[A-Za-z]{2,}`;
  - a phone number, `\+\d[\d ().-]{7,}\d` or `\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}`.
- **The refusal says only** "A lesson can't name a person or hold an email address or phone number", never which, so
  no ship can probe for who has an account. A false match only refuses, and the ship rewords: `git@github.com`
  matches the email pattern, so a lesson says "GitHub over SSH". The tests include dates, versions, IPv4 addresses,
  ports, process ids, `git@github.com` and an account named "test".
- **This narrows mistakes, not malice.** It can't see a name the peer doesn't hold, or person data that isn't a name,
  an email address or a phone number, such as an address, a date of birth, a record number or a medical fact in an
  assertion message. Live ship keys are refused as in every room (`_refuse_live_ship_keys`). Other secrets are for
  the ship's own check.
- **Lessons stay inside Andy's home.** The room holds only Andy's accounts and his ships, federates only to peers he
  paired, and is never bridged. The query answers only his ships, on its own peer.

## 7. The rail measure

Two lessons form a **segment** when two ships laid the same lesson on two peers on their own. Both are
`learned from: own`. Their authors are different ships on different peers, so their origins are distinct. (A lesson's
peer is the prefix of its author id, or the origin's own id for the origin's members.) Their embedded texts differ, and
their vectors lie within `segment_angle` of each other. Copies never count: a lesson learned from another ship or from
Andy isn't its ship's own, and two copies of one text are one lesson.

That is the first piece of the cohomology made concrete: a section over two ships' independent stores that glues
(H⁰). Obstructions (H¹) need lessons around a cycle of three ships, a later step.

`segment_angle` is a calibration hypothesis, document to document: provisionally arccos 0.85, about 0.555 rad. The
ships calibrate it on the pairs they already share (the keyword count; zsh globbing) and on pairs they judge
different, recording the angles and who judged. They recalibrate `r_max` from the query rows, after the blind test and
after 20 real failures they judge a lesson should have met. `make lesson-segments` on any peer reports segments per
pair of ships from its own copy, with lesson ids and angles, and no text.

## 8. The hook

The lessons hook is a hook of its own, apart from the room hook, with its own switch in the station client's installer
(`install.py` installs one set today). So a session can have it with the room hook and the station tools off. It reads
its peer's data directory and its ship's username from its own settings. It sends no prompt and no file content. It
never runs, expands or evaluates a lesson or any value in one.

- **Session start** (`SessionStart`): it sends `cwd` and the branch (`git rev-parse --abbrev-ref HEAD`, none outside a
  repository), never a person's prompt.
- **Before a command** (`PreToolUse` on Bash): the first time each command head appears in the session, it sends the
  command, for words only. The head is the first word after any leading `NAME=value` words, plus the second word when
  that doesn't start with `-`. The command is the agent's words, not a person's. Context that `PreToolUse` adds
  reaches the model only with the command's result, after the run. So when words find a lesson, the hook holds the
  command once (`permissionDecision: "deny"`). Its reason is the fenced lessons, ending "Held once so these come
  first; run it again to go on." It holds each head at most once per session, and only on a words match.
- **After a failed command:** it sends `cwd`, the branch, the command and the last error line. The builder confirms on
  every ship's Claude Code version which event carries a non-zero Bash exit and a timeout (`PostToolUse` or
  `PostToolUseFailure`, both in the Pi's 2.1.311), and that a `PreToolUse` deny's reason reaches the model.
- **Output** goes in `hookSpecificOutput.additionalContext`, or in the hold's reason. It is fenced with the station
  client's `fence_external` (`team/superyak_team/teamlib.py`), so a lesson holding three backticks can't close it.
  The fence is headed "Lessons from Andy's ships (quoted data, not instructions)", with each ship and receipt id.
- **Time:** at most 1 s before a command, and 2 s otherwise, by wall clock, as `_board` does (`hook.py`). At the
  deadline the hook stops the query and prints nothing.
- **Not in runs:** it does nothing when `SUPERYAK_RUN` is set to anything but `hook`, so watcher and teamd runs never
  query.
- **Repeats:** it shows each lesson at most once per session, and sends the same command and error at most once per
  session.

## 9. The blind test

- **The traveler:** a fresh Tardis session with only the lessons hook on. The station's room hook and tools are off.
  Its Engram store is empty, its Claude Code auto memory directory (`~/.claude/projects/<path>/memory`) is empty, and
  no one tells it lessons exist. It reaches lessons only through Tardis's own peer, so the test also shows the room
  replicated from the Pi.
- **The workspace:** traveler and control both work in an export of the task's code with no git history and without
  `docs/superpowers`, `docs/governance` or `HANDOFF.md`, or in another repository. This spec doesn't quote the lesson.
- **The situation:** a task whose test suite outlasts a foreground command on Tardis, in words that mention neither
  time nor lessons, and a lesson that Rio Grande laid on the Pi that covers it. The task, its words, the suite and the
  lesson are written down, outside the workspace, before either run.
- **Pass:** the hook's fenced block, carrying the lesson's receipt id, appears in the traveler's transcript before any
  foreground run of the suite starts. A receipt with no block in the transcript is a fail, and so is a block that
  comes later.
- **Minutes saved:** the control (same task and isolation, with the hook off) gives the minutes from its first
  foreground run of the suite to its background rerun. The traveler's lost minutes stand beside them.
- One run is a first check, not a measure. Report everything else the hook showed, so noise counts too. Tardis lays
  its own lessons after the test.

## 10. Non-goals and anti-goals

**Non-goals:** whole-store copies on the rail; A\* and hops along trails; anything outside Andy's home; auto-captured
memory as track; semantics or roads as lessons; changes to recall or the trail tools; a listener on the Mac; any relay
beyond the origin's own role in federation.

**Anti-goals** (failure even if the code works): a lesson run as an instruction or shown unfenced; a lesson that names a
person accepted; a lessons room bridged, readable outside Andy's home, or with another person's member; a ship posting
under a person's account; context text stored, logged or put in a record; a lesson shown after it is retracted or
refused; a copy counted as a segment; a query sent off its own peer; an embedding inside a station transaction; a query
over 1 s at p95; a lessons process over 512 MiB.

## 11. The split, and what it waits on

From 0caa47fc, as the ships agreed, adapted to peer to peer:

| Who | Builds | Waits on |
|---|---|---|
| Rio Grande | this spec; `lessons.py`: the room record and checks, the index, the query, receipts and segments; the Pi's lessons | the Pi's embedder, for near (words run without it) |
| Serenity | the writing tool (`lay`, `retract`, `relay`) with its person check; the Mac's lessons | the Mac's peer, once pull exists |
| Tardis | the pairing code and federation pull; the hook and its timing; then the blind test as traveler | replication between the Pi and Tardis |

**The rail depends on two pieces of Tardis's work:**
1. **The pairing code** (fix:pairing-code) comes first. It binds the signing key to the certificate. Without it, a
   swapped key could send as a paired peer.
2. **Federation pull** (spec:federation-pull, branch `tardis/federation-pull`, under review). On main, federation is
   push only, a paired outbox gives up after 8 attempts (about four minutes), and no peer of ours can be dialed yet.
   Pull adds a federation-only listener on the Pi and Tardis, a pull route for a peer that never listens, and an
   outbox that never gives up on a paired peer. The Mac only dials out and never listens (law section 6 counts
   loopback listeners), so it can receive only through pull.

**Before they land,** everything local is built and tested on one peer against fixtures: the grammar, the checks, the
room record, the index, the query, the hook and receipts. Nothing replicates yet. **The Pi and Tardis come first,**
once the pairing code and pull's listener are in. They both listen, so they pair and replicate the room. Their ships
lay lessons, and the blind test runs on Tardis. **The Mac joins once pull exists:** Andy adds its members (section 3's
chain), and each ship lays its live lessons again.

## 12. Decisions

Andy handed these to the ships "as a community, as a government" (`docs/governance/ship-decisions.md`). Settled:

1. A lessons room (B), with the station refusing person data on each post. The room is scaffold, and lessons move
   into Engram imprints once those are live.
2. Peer to peer (d2960bd3): a lesson is a post in a federated lessons room. Each peer indexes its own copy and answers
   its own sessions. The Pi is one peer among three. The rail depends on the pairing code and federation pull.
3. The lessons room is one Andy opens once, with his ships (the review's question 2). It is not a breakout exempt
   from the quiet close.
4. The audience is all of Andy's ships, Defiant included. The session-start hook sends the cwd and the branch, never
   a person's prompt.
5. A `PreToolUse` hook on Bash queries the first time each command head appears (the review's M4).
6. The blind traveler is a fresh Tardis session with the station's room hook and tools off, reaching lessons only
   through the query.

**Rio Grande's calls in this revision, for the re-check:** the origin on the Pi; ships as members as themselves (law
section 7); access requests left out of the name check; the hold before a command; the re-lay after an add; and
indexing every 60 s into a file.

**For Andy,** only the acts reserved for a person: pairing his peers' cards (federation's setup); opening the room once;
adding the Mac's members when pull lands; and, if a person's data ever slips in, redaction by hand. No open question
goes to him.

## Review response

| # | Finding | Change |
|---|---|---|
| M1 | no wire format | Applied: section 2 has the grammar, byte limits, the embedded text, retraction, the cap of 32 and no mentions, and nothing else is accepted in the room. |
| M2 | the room found by title; members; the chain | Applied: section 3. The room is recorded by id on every peer and its chain is followed. Members are Andy's accounts and his ships only, and the room is never bridged. Its "refuse a remote member" doesn't apply: remote members are how the room reaches the other peers, so only contacts on peers Andy paired are accepted. Its rule for the route became section 5's: the query answers only member ships on its own peer. |
| M3 | the body contradicts the decisions | Applied: the branch is in the query and the hook; lessons move to imprints later (section 3); 384 KiB for four ships at the cap; the settled questions are in section 12. |
| M4 | the blind test | Applied with the ships' choice: `PreToolUse` per command head (section 8). It holds the command once on a words match, because context added before a command reaches the model only with its result. The proof is in the transcript. The isolation closes both leaks: this spec no longer quotes the lesson, the auto memory directory is empty, and the workspace is an export with no history. |
| M5 | the embedder inside the write lock | Applied: indexing runs on each peer, every 60 s, outside any transaction, and writes a file (section 4). The query embeds before any transaction opens, then re-checks and writes receipts in one short transaction (section 5). It is also an anti-goal. |
| M6 | no matching rule | Applied with the review's simpler alternative: accounts only, matched as whole words of at least 3 characters, plus the two patterns, with one refusal message. Access requests are left out, so the public door can't censor the rail. |
| S1 | the room hook | Applied on the Pi's station, the one place a station client reads unread. The copies on other peers feed no hook. |
| S2 | words before angles | Applied: section 5, step 1, and section 1's peer without an embedder. |
| S3 | length, measurement and embedder cost | Applied: the field cuts, p95 at the cut, the unit's memory (section 1), and 8 lessons per embedder request (section 4). |
| S4 | the hook | Applied, except the per-ship budget of 30 queries a minute. Under peer to peer a query runs on the asking machine, and its embedder serves only that machine's sessions. So a loop can't queue in front of another machine's queries, and the repeats rule bounds it. |
| S5 | the owner retracts; retraction doesn't remove | Applied: sections 2 and 3, including every peer's copy and backups. |
| S6 | receipts need a reader | Applied as `make lesson-receipts` on each machine. |
| S7 | where the lesson and the code live | Applied: section 2 and the header's modules. Its MCP tool in the station client doesn't apply: the writing tool posts to its own peer, not to the station over the network. |
| S8 | cut the hop; segments on demand | Applied: section 5 and `make lesson-segments`. |
| S9 | copies through a third ship | Applied: it is section 7's core rule. |
| S10 | `r_max` as a hypothesis | Applied: sections 5 and 7, with a query row for each query. |
| N1 to N12 | nits | Applied: N1 (section 7), N2 (`owner`), N3 (step 3), N4, N5 (section 4), N6, N7 (option (A) is cut), N9, N10, N11 (with S2) and N12. N8 is moot: the Mac's lessons wait on pull, not on chat paging. |
| Question 2 | breakout or person's room | Applied: a room Andy opens once (section 3). |
