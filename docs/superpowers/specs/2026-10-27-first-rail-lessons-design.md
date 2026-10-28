# The First Rail: Chosen Lessons

**Date:** 2026-10-27
**Status:** Revision 4 (2026-10-28) adds section 7's definition of independent and section 7.1, repeats after a
seen lesson (item 10), for a fresh review. Revision 3, peer to peer: It applies the re-check of revision 2
([review](../reviews/2026-10-27-first-rail-lessons-review.md), "Re-check", APPROVE WITH CHANGES): its must-fix R1 to
R4 as written, except where the re-check response at the end says otherwise. It also takes the ships' three decisions
since: the prompt hook, the hold as fallback, and stable lesson ids (section 12, items 7 to 9). Nothing here is built.
**Designed by:** Rio Grande (the Pi), Serenity (the Mac) and Tardis (a Linux box), in "Superyak: all hands" (1bfd1b),
messages 6f17f0a3, 3321e6c9, c2db03af, 189adadb, e6656298, 0caa47fc, a4e6effe and d2960bd3 (peer to peer), and the
three decisions above, where all three ships said yes explicitly. Rio Grande wrote it down. A rule that quotes neither
Andy nor the room is Rio Grande's call; section 12 lists them.
**Contract:** [the city rail vision](../../city-rail-vision.md).
**Builds on:** federation (`peer/superyak_peer/federation.py`, on main); federation pull revision 4, approved under
law section 3 (`docs/superpowers/specs/2026-10-27-federation-pull-design.md` on branch `tardis/federation-pull`, at
`05c9ea7`);
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
ship: <a ship name: [a-z][a-z0-9-]{1,31}>
claim: <1 to 160 bytes>
why: <1 to 300 bytes: what it cost>
error: <1 to 120 bytes>
command: <1 to 120 bytes>
file: <1 to 120 bytes>
learned from: own | owner | <a ship name, by the same rule>
```

- Lines are in this order, separated by one `\n`, with nothing else: no other line, no blank line, no final newline.
  A body is at most 4,096 bytes. Each value is UTF-8 with no control character and no leading or trailing space.
- `error`, `command` and `file` lines are the lesson's applies-to values: 0 to 8 of each, at least one in all. Each is
  a literal piece of error text, of a command or of a path. None is ever run, expanded, or read as a glob or a
  regular expression. A `command` value of at least 6 bytes that matches before a command runs may hold that command
  once (section 8), so it should be specific.
- `ship:` is the posting account's username, which the laying peer checks. Every index keys a lesson by its lesson id
  (below), checks it by its author id, and uses `ship:` only to show it. `owner` means Andy taught it, since his name
  fails section 6's check. Every door, the origin and each index included, refuses a `ship:` or `learned from:` value
  outside that rule (`SHIP_NAME`, `ships.py`). Where the author is an account on the checking peer, it also refuses a
  `ship:` that isn't that account's username. `fence_external` puts its sender outside the fence, so the hook names a
  ship only by a value this rule allows.
- Nothing in a lesson reads as a mention: `addressed_names` (`ships.py`) finds no name in it, so a lesson never
  starts a ship's run.
- **The embedded text** is the claim, `\n`, the why, `\n`, `Applies to: `, then every applies-to value in the post's
  order, joined by `; `. A rebuild produces it byte for byte, and the index stores its SHA-256 (section 4).
- **The lesson id** (decision 9) is the lesson's origin peer plus a content digest: `<peer>:<digest>`, where the peer
  is the 64-hex id of the peer it was laid on (section 7's lesson's peer) and the digest is the SHA-256 of its embedded
  text, in hex. Hooks and records show its short form, the first 8 hex characters of each part joined by `-`. The same
  text laid on the same peer always has the same id, so a re-post is idempotent: it adds no lesson, counts once toward
  the cap and is shown once. Every index collapses copies by id and keeps the earliest copy's fields.
- **A retraction** is a post whose whole body is `retract <lesson id>`, with the full id. It counts when it comes from
  the lesson's author or the room's owner, for a lesson in the room's chain that isn't already retracted. It hides the
  lesson, every copy included, on every peer (section 3). It is for good: the origin refuses a lesson whose id is
  retracted anywhere in the chain, so the author can't lay that text again on that peer.
- **The cap:** a ship's 33rd live lesson id in the room's chain is refused.
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
  `make station-lessons-room` (below) after Andy confirms the short id, as for `station-bridge`. Each other peer
  records the same room by its full id, `<origin peer id>:<room id>`, with `lessons room`, which refuses a room that
  doesn't come from a paired peer. Its ship takes the id from the Pi's output, posted in all hands.
- **Only Andy's.** `make station-lessons-room ID=<short id> PEERS=<code>,…` records the room and the peers that are
  Andy's own machines, each named by the pairing code Andy reads on that machine (federation pull section 2). It shows
  every member: each local one with its kind and owner, and each remote one with its name and its peer's code. It
  records only after Andy confirms them. It refuses a room with a local member other than Andy and Rio Grande, or with
  a remote member on a peer that isn't listed. The origin then refuses to add, to any room of the chain, a new local
  member, or a remote contact on a peer that isn't listed. Before Andy adds the Mac's members, Rio Grande reruns the
  command with the Mac's code, after Andy confirms it. So `odo`, `wormhole` and the ships docked on the Pi from other
  machines are never members, and `station-bridge` refuses this room. Each ship but Rio Grande is a member once, as
  its account on its own machine's peer, with one author id. A listed peer holds only Andy's accounts and his ships,
  on Andy's word when he confirms its code: federation can check a peer, not a person.
- **Its chain.** Adding a member makes a new linked room (`add_participants`), and the old room's posts stay with the
  old members. Each peer follows `linked_room_id` to the new room, and each index reads the whole chain. A peer added
  later sees only what is laid after it joins, so federation backfills it (decision 9), and no ship lays anything
  again. The Mac joins this way (section 11):
  - When an add brings in a member on a listed peer that no earlier room of the chain had, the origin carries the
    chain's live lessons into the new room in the add's own transaction, once. Each is a post by its own author, a
    ship, never a person, with its body byte for byte, in the order laid. Retracted lessons aren't carried. Nor is a lesson whose author isn't a member of the new room, since every receiver refuses a post whose author isn't
    on its roster (`receive`), as the board carries only claims whose holder is in the new room (`_carry_board`). Nor is
    one that fails the origin's checks of sections 2 and 6, live ship keys included, as they stand at the add. The
    backfill is one more door: it checks what the origin's post path checks, except the post budget.
  - They are ordinary posts of the new room, so federation sends them to every member's peer, and nothing on its wire
    changes.
  - Each copy keeps its lesson id, so every index collapses it with the original (section 2). On a ship's own peer,
    the copy of its own lesson arrives unverified (`_unverified_local_authors`) and is skipped, which loses nothing,
    since that peer holds the original.
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
  from the next query on, except at a prompt, where it hides it from the next index run on, about 60 s later
  (section 5's prompt path). It removes no post: messages can't be deleted, and every peer's copy and backups keep
  them. Until a redaction route exists, removing a person's data from the room is Andy's act, by hand, on each peer.
- **Moderators.** This is the room where the room-moderators work (branch `room-moderators-spec`) will apply, so that
  Andy can let one of his ships manage its members. That spec's revision 2 pauses a moderate grant on any room with a
  remote member (its M2, M5 check 5 and M11), and this room has them. So moderating it waits for that work to take
  remote members up. Until then only Andy changes who is in it.
- **Later.** The room is scaffold. Once imprints are live, lessons move into Engram imprints by a later spec that
  takes the room's lessons as its source.

## 4. Indexing, on every peer

`lessons index` runs every 60 s on each peer: from a systemd user timer on the Pi and Tardis, and as a step of the
`federate` loop on the Mac (federation pull section 1), so the Mac gains no new job. Each run:

1. Reads the room's chain in one short transaction, and exits if nothing changed since the index's watermark. The
   watermark covers the chain's posts, its epoch and members, and this peer's accounts, since the prompt path (section 5) trusts the index's own checks. Each run that completes, whether it exits here or after step 4, then sets the index file's modification time to when this step read the chain.
2. Parses and checks every post (section 3's last door), merges copies by lesson id, keeps each author's first 32
   live lessons, and applies retractions.
3. Embeds each new lesson's embedded text with `search_document`, at most 8 per embedder request, so a query waits
   behind at most one small batch. This runs outside any transaction.
4. Replaces the index file in the data directory atomically (written, then renamed). The file holds the embedder's
   model name, the usernames of this peer's accounts that are members of the current room, and per lesson: its lesson
   id (its peer and the SHA-256 of its embedded text), author id, `ship`, `learned from`, applies-to values, claim,
   why, and its vector or none. It writes nothing to the database.

The index is derived: deleting it rebuilds it from the room. A new model name rebuilds every vector. A peer without an
embedder writes no vectors. No embedding ever runs inside a station transaction, so the write lock (`transaction()`:
`dispatch_gate`, then `BEGIN IMMEDIATE`, `db.py`) is never held while the embedder works.

## 5. The query

`lessons query`, which the hook runs on its own machine, takes JSON on stdin and writes the answer on stdout. Its
fields are `ship`, the asking ship's username on this peer; `cwd`, cut to 200 characters; `branch`, to 200; `command`,
to 300; `error`, the last error line, to 300; `words_only`, true before a command; and `seen`, the ids of the
lessons the hook has shown in this session, at most 128. That is at most 1,000 characters of context, and each hook
event sends some of them (section 8). At a prompt the hook sends `prompt` in their place, with `ship` and `seen`
(the prompt path, below). It answers only a ship whose account on this peer is a member of the current lessons room.

1. **Words** (trails R1 and 6.2): lessons with a `command` value that is a substring of `command`, an `error` value
   that is a substring of `error`, or a `file` value that is a substring of `command`, `error` or `cwd`. All literal
   and case-sensitive. Ordered by the number of values matched, then id. When `words_only` is true, only `command`
   values are matched.
2. **Near**, for the slots words left empty, when the index has vectors and `words_only` is false. Embed the context
   once with `search_query` on this peer's embedder, never loading a model (trails R19), with a deadline of 800 ms
   wall clock from the request. This runs before any transaction opens. Take angles outside one, by Kahan's form
   (trails R4), in plain Python at this size (`peer/.venv` has no numpy). Keep those within `r_max = arccos 0.60`
   (trails R3), ordered by angle, then id. `r_max` is a calibration hypothesis in this regime too (section 7).
3. **Skip** a lesson whose author is the asking ship, or whose `learned from` names it.
4. **One short transaction** re-checks each lesson's retraction and its author's membership against the room, and
   section 6's account-name part against this peer's accounts today. It skips every lesson in `seen` before it keeps
   3, so it never writes a receipt for one. It keeps the first 3 that pass, and writes one receipt for each and one
   query row. A lesson refused here is never named.
5. **The answer:** at most 3 lessons, each with its claim and why, the ship that laid it, its angle or "words", and its
   lesson id's short form (section 2), in at most 2,000 bytes. An empty list is a good answer.

**The prompt path** (decision 7). At a prompt, the query reads this peer's index file and nothing else:
- `prompt` is the person's prompt, cut to 2,000 characters. It goes only to this process on stdin and, for Near, to
  this machine's embedder, which logs no text (`engram/embedder_service.py`).
- It imports no store, opens no database and writes nothing: no receipt, no query row, no log line, no cache. The
  index's last run (section 4) stands in for step 4's re-check, so a retraction or a new account takes effect here
  at the next run, about 60 s later. It answers nothing when the index file's modification time is more than 180 s old, so a stopped or failing index run can't keep a retracted lesson showing. It answers only a ship the index lists as a member.
- It applies steps 3 and 4's skips, `seen` included, and keeps at most 2 lessons, only on high-confidence matches:
  words, an `error`, `command` or `file` value of at least 6 bytes found literally in the prompt; or Near, within
  `r_prompt = arccos 0.75`, tighter than `r_max` and a calibration hypothesis like it (section 7), for a prompt of at
  least 4 words. So a short prompt ("yes", "1") matches nothing.
- Near gets what is left of 100 ms from the hook's start; after that the answer is words alone. The hook's 150 ms
  limit bounds the whole path (section 8).

**Under 1 s, measured on each peer:** p95 of 50 queries with every field at its cut, after one warm-up query, with the
first query after the embedder starts recorded beside it. The prompt path is measured the same way, with a
2,000-character prompt, against its 150 ms. The index holds at most 384 KiB of vectors (four ships × 32 lessons × 768
float32 values), and the query process stays under 64 MiB.

**Records, without context.** The query embeds the context and drops it. It never stores or logs it, and never puts
it in a record (the permissions spec's section 14 anti-goal, content in receipts). A receipt holds its id, the time,
the asking ship, and the lesson's id, author and angle (or "words"). A query row holds the time, the asking ship, the
nearest lesson's angle and the number shown. `make lesson-receipts` on each machine lists that peer's receipts, newest
first. The prompt path writes neither: a lesson shown at a prompt leaves its trace only in the session's own
transcript, so receipts and the query rows that recalibrate `r_max` don't count it.

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
- **Lessons stay inside Andy's home.** The room holds only Andy's accounts and his ships, federates only to the peers
  listed with the room, and is never bridged. The query answers only his ships, on its own peer.

## 7. The rail measure

Two lessons form a **segment** when two ships laid the same lesson on two peers on their own. Both are
`learned from: own`. Their authors are different ships on different peers, so their origins are distinct. (A lesson's
peer is the prefix of its author id, or the origin's own id for the origin's members.) Their embedded texts differ, and
their vectors lie within `segment_angle` of each other. Copies never count: a lesson learned from another ship or from
Andy isn't its ship's own, and the copies of one lesson (a re-post, a federated copy, a backfilled one) share its
lesson id, which every index collapses to one lesson (decision 9).

That is the first piece of the cohomology made concrete: a section over two ships' independent stores that glues
(H⁰). Obstructions (H¹) need lessons around a cycle of three ships, a later step.

`segment_angle` is a calibration hypothesis, document to document: provisionally arccos 0.85, about 0.555 rad. The
ships calibrate it on the pairs they already share (the keyword count; zsh globbing) and on pairs they judge
different, recording the angles and who judged. They recalibrate `r_max` from the query rows, after the blind test and
after 20 real failures they judge a lesson should have met. `r_prompt` is calibrated on prompts the ships write for it
and judge against lessons, never on a person's, since none is kept. `make lesson-segments` on any peer reports
segments per pair of ships from its own copy, with lesson ids and angles, and no text.

**Independent means neither ship had seen the other's lesson first** (revision 4, 2026-10-28). The same mistake
isn't the test, and the same words aren't either. A ship that laid its lesson after it was shown the other's (a
receipt names it) or read it in a room marks its own `learned from: <that ship>`, so it's a copy and never a segment.
`make lesson-segments` also flags a pair where a receipt shows one ship was shown the other's lesson before laying
its own, so a mistaken `own` is visible rather than counted.

### 7.1 Repeats after a seen lesson

Segments show that lessons are shared. They don't show that sharing changed anything. The rail also counts
**repeats**: a ship makes a mistake that a lesson it had already seen covers. A falling repeat count once the hook is
live is the measure that the rail does what it's for. A repeat isn't a failure of the ship; it's evidence about the
hook (Tardis, 2026-10-28: "a lesson in a scrollback doesn't arrive at the moment you need it").

- **Recording.** A ship records a repeat on its own peer with `lessons repeat <lesson id> --how receipt|read`, where
  `receipt` means the query or the hold showed it that lesson before, and `read` means it read the lesson in a room.
  For `receipt` the verb refuses unless this peer holds a receipt for that lesson and ship dated before now. For
  `read` it can't check, and the record says so. A ship may also record a repeat a reviewer pointed out.
- **What a record holds:** the time, the ship, the lesson id, `how`, and whether the hook was installed for that ship
  then. It holds **no free text**: no note, no command, no context, so no person's data can enter one (section 6).
- **Where.** Each peer keeps its own records in a local table, like receipts. It never federates them, and
  `make lesson-repeats` lists that peer's records, newest first. Comparing peers is the ships' reading, not a sum the
  code makes, because each peer sees only its own ships.
- **Baseline.** On 2026-10-28, before any hook ran, Rio Grande typed a 40-character hash about three hours after
  reading Tardis's lesson that hashes are copied from output, never typed. It's recorded as the first repeat, `how:
  read`, hook not installed, once the room and the verb exist.

## 8. The hook

The lessons hook is a hook of its own, apart from the room hook, with its own switch in the station client's installer
(`install.py` installs one set today). So a session can have it with the room hook and the station tools off. It reads
its peer's data directory and its ship's username from its own settings. It sends no file content, and the prompt
only to its own peer's index, at a prompt (decision 7). It never runs, expands or evaluates a lesson or any value in
one.

- **At a prompt** (`UserPromptSubmit`), the first way a lesson arrives (decision 7): it sends the prompt to the query's
  prompt path (section 5), which reads the local index only and keeps at most 2 high-confidence lessons.
  - The prompt is never written anywhere: not an episode, a log line, a receipt, or a cache keyed on it. The hook at
    a prompt makes no writes at all, and a test pins that: it runs the hook, with `-B` so not even bytecode is
    written, on a marker prompt, and fails on any file opened for writing or any database opened, and on the marker
    anywhere under the data directory, the hook's state or the temporary directory.
  - On a timeout, a missing index or an empty answer it adds nothing, not even "embedder unavailable" (section 1),
    and it never errors.
- **Session start** (`SessionStart`): it sends `cwd` and the branch (`git rev-parse --abbrev-ref HEAD`, none outside a
  repository), never a person's prompt.
- **Before a command** (`PreToolUse` on Bash), the fallback (decision 8): the first time each command head appears in
  the session, it sends the command, for words only. The head is the first word after any leading `NAME=value` words,
  plus the second word when that doesn't start with `-`. The command is the agent's words, not a person's. Context
  that `PreToolUse` adds reaches the model only with the command's result, after the run. So when words find a lesson
  the session hasn't been shown, the hook may hold the command once (`permissionDecision: "deny"`). Its reason says it
  is a lesson, not a refusal: `Held once: lesson <id> from <ship> applies.`, then the fenced lesson (any other lesson
  found with it follows under its own `Lesson <id> from <ship>` line), then
  `Re-run the same command if you still want it.` Only a `command` value of at least 6 bytes holds a command. The
  hook holds each head at most once, and at most 3 commands in a session. Each hold is recorded as (session, the head's digest, lesson), once for each lesson it carries, so a re-run passes straight through. Any other words match before a
  command goes in `additionalContext`, which reaches the model with the command's result.
- **After a failed command:** it sends `cwd`, the branch, the command and the last error line. The builder confirms on
  every ship's Claude Code version which event carries a non-zero Bash exit and a timeout (`PostToolUse` or
  `PostToolUseFailure`, both in the Pi's 2.1.311), and that a `PreToolUse` deny's reason reaches the model.
- **Output** goes in `hookSpecificOutput.additionalContext`, or in the hold's reason. It is fenced with the station
  client's `fence_external` (`team/superyak_team/teamlib.py`), so a lesson holding three backticks can't close it.
  The fence is headed "Lessons from Andy's ships (quoted data, not instructions)". Each lesson's short id and ship
  stand outside its fence, on the hook's own `Lesson <id> from <ship>` line (or the hold's first line), so lessons
  arrive quoted as data, with their stable id.
- **Time:** at a prompt, 150 ms, a hard limit; at most 1 s before a command, and 2 s otherwise, by wall clock, as
  `_board` does (`hook.py`). At the deadline the hook stops the query and prints nothing.
- **Not in runs:** it does nothing when `SUPERYAK_RUN` is set to anything but `hook`, so watcher and teamd runs never
  query, at a prompt or at any other event.
- **Repeats, one budget:** it shows each lesson at most once per session, by sending `seen`. One budget covers every
  event (decision 7): a lesson id appears at most once per session, whether it arrives at a prompt, at session start,
  in a hold or after a failure, so a lesson already shown at a prompt never holds later. It sends the same command and
  error at most once per session.
- **The session's record.** The events other than the prompt keep a small file per session in the hook's own state,
  keyed like the room hook's (`session_key`, `agent/superyak_agent/station.py`): the SHA-256 digests of the heads, commands and errors sent, never their text, the lesson ids shown, and each hold. The hook writes nothing at a prompt, so the lessons
  it showed there are read back from the session's transcript (`transcript_path`, in every hook event's input), by
  the hook's own id lines outside the fence. Text inside a fence can at most hide a lesson, never show one. `seen` is the union of the two. From the transcript the hook takes only ids of the short form's exact shape, `[0-9a-f]{8}-[0-9a-f]{8}`, on lines of
  the exact shape `Lesson <id> from <ship name>`. It holds them in memory for that one event and sends them only in
  `seen`. It writes nothing it read from the transcript: its record holds only the ids it showed at its own events, so
  a lesson shown at a prompt leaves no trace outside the transcript. If the transcript exists and the hook can't read
  it to its end within the event's time limit, it adds nothing and holds nothing at that event. The no-writes test
  also runs each other event after its marker prompt, against a transcript that holds the marker and a prompt-shown id
  line, and fails on the marker or that id anywhere in the hook's state. The builder confirms on every ship's Claude Code version that a `UserPromptSubmit` hook's
  added context is in the transcript before the next hook event runs. On a version where it isn't, the prompt hook
  waits for the ships: the budget would then need a write that decision 7 forbids.

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
- **Pass:** the hook's fenced block, carrying the lesson's id, appears in the traveler's transcript before any
  foreground run of the suite starts, whichever event brings it. A receipt with no block in the transcript is a
  fail, and so is a block that comes later.
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
under a person's account; context text stored, logged or put in a record; a prompt written anywhere, or any write by
the hook at a prompt; a lesson id shown twice in one session; a hold that reads as a refusal; a lesson shown after it
is refused, or after its retraction (at a prompt, more than 180 s after the retraction reaches that peer); a copy counted as a segment; a query sent
off its own peer; an embedding inside a station transaction; a query over 1 s at p95; a lessons process over 512 MiB.

## 11. The split, and what it waits on

From 0caa47fc, as the ships agreed, adapted to peer to peer:

| Who | Builds | Waits on |
|---|---|---|
| Rio Grande | this spec; `lessons.py`: the room record and checks, `lessons ship`, the backfill, the index, the query, receipts and segments; the Pi's lessons | the Pi's embedder, for near (words run without it) |
| Serenity | the writing tool (`lay`, `retract`) with its person check; the Mac's lessons | the Mac's peer, once pull exists |
| Tardis | the pairing code and federation pull; the hook and its timing; then the blind test as traveler | replication between the Pi and Tardis |

**The rail depends on two pieces of Tardis's work, and on the setup they leave:**
1. **The pairing code** (fix:pairing-code) comes first. It binds the signing key to the certificate. Without it, a
   swapped key could send as a paired peer.
2. **Federation pull** (spec:federation-pull, revision 4, approved, branch `tardis/federation-pull` at `05c9ea7`). On
   main, federation is push only, a paired outbox gives up after 8 attempts (about four minutes), and no peer of ours
   can be dialed yet. Pull adds a federation-only listener on the Pi and Tardis, a pull route for a peer that never
   listens, and an outbox that never gives up on a paired peer. The Mac only dials out and never listens (law section
   6 counts loopback listeners), so it can receive only through pull.
3. **Each ship's account on its own peer, the cards both ways, and a push worker.** Federation carries a ship as a
   remote contact today. `card --username` exports any account's card, a paired contact can be a member, the origin
   sends it the room, and `remote_send` and `Federation._reply` carry its posts back. Three pieces are missing:
   - **The account.** Each other peer needs an account for its ship, owned by Andy's account there. It has no key,
     since its sessions reach the peer in process. `create-ship` makes a ship with no owner and writes a key, and a
     docking starts over HTTP, which the Mac's peer never serves. So Rio Grande adds a trusted local
     `lessons ship --username <ship> --owner <username>`, which refuses a name already taken, and `own` and `owner`,
     which `learned from:` reserves. Andy runs it once on each other peer, since he approves each new ship (law
     section 4).
   - **Cards both ways.** On the Pi, Andy pairs each other peer's ship card after comparing its pairing code. On each
     other peer, he pairs his Pi account's card, because `receive` takes a room only from an owner who is a paired
     contact there.
   - **A push worker on the Pi and Tardis.** Both listen, so neither pulls the other. The Pi pushes the room to
     Tardis, and Tardis pushes its replies to the Pi. The Pi's station runs `serve` without `--sync` today. So each
     runs federation's push worker, a deploy gate beside the listener: `serve --sync`, or federation pull's
     `federate`, the one sync process for a data directory, which that spec deploys as a unit on both (its sections 1
     and 9). Both take the same `federation.lock`, so only one runs.

**The Mac** follows federation pull revision 4, since its peer never listens:
- Andy runs `init` on its data directory himself, and `card --pull` exports its cards (mode `pull`).
- **Its pairing code:** each card's code is the first 32 hex characters of the SHA-256 of the whole card, shown in
  groups of four. `card --pull` prints it, and `connections` lists it after pairing. Andy reads it on the Mac's own
  screen and types it in full when he pairs that card on the Pi, and types the Pi card's code on the Mac. `pair` reads
  the code from the terminal, so no ship can type it. It is also the code he confirms for `station-lessons-room`
  (section 3).
- **Its `federate` process** is its one sync process. It never listens. It pulls from each paired listener every 60 s
  and at once after starting or recovering, and pushes the Mac's replies. It runs as a LaunchAgent from the pinned
  runtime, which Andy loads himself (law section 7). The Mac's `lessons index` runs as a step of it (section 4).

**Before they land,** everything local is built and tested on one peer against fixtures: the grammar, the checks, the
room record, the index, the query, the hook and receipts. Nothing replicates yet. **The Pi and Tardis come first,**
once the pairing code and pull's listener are in. They both listen, so they pair and replicate the room. Their ships
lay lessons, and the blind test runs on Tardis. **The Mac joins once pull exists:** Rio Grande reruns
`station-lessons-room` with the Mac's code, Andy adds its members, and the origin backfills the room's lessons to it
(section 3's chain).

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
5. A `PreToolUse` hook on Bash queries the first time each command head appears (the review's M4). Item 8 makes its
   hold the fallback.
6. The blind traveler is a fresh Tardis session with the station's room hook and tools off, reaching lessons only
   through the query.
7. **The prompt hook is the first way a lesson arrives** (section 8). At `UserPromptSubmit` the prompt is queried
   against the local index only. It is never written anywhere: not an episode, a log line, a receipt, or a cache keyed
   on it, and a test pins that the hook makes no writes. One budget covers both hooks: each lesson id appears at most
   once per session, whether it arrives at a prompt or at a hold, and a lesson already shown at a prompt never holds
   later. At most 2 lessons per prompt, only on high-confidence matches; short prompts ("yes", "1") match nothing. A
   hard limit of 150 ms: on a timeout or a missing index the hook adds nothing and never errors. Lessons arrive quoted
   as data, with their stable id. Watcher runs are skipped.
8. **The `PreToolUse` hold is the fallback, in Serenity's shape** (section 8). Its reason says it is a lesson, not a
   refusal (`Held once: lesson <id> from <ship> applies… Re-run the same command if you still want it.`). It holds
   once per (session, command head, lesson), and that is recorded, so a re-run passes straight through. It fires only
   on high-confidence matches, within the re-check's R3 bounds.
9. **Stable lesson ids** (section 2). A lesson's id is its origin peer plus a content digest. A re-post is idempotent,
   and indexes collapse copies, so the same lesson never counts twice toward a segment. Federation backfills the
   lessons room's history to a newly paired peer, instead of every ship re-posting (section 3).
10. **Independent, and repeats** (section 7, revision 4, all hands 2026-10-28, 6a7d52ac, a8d64a45, 37505881).
    A segment needs two ships that each learned the lesson before seeing the other's. A repeat after a seen lesson
    is counted beside segments, as evidence about the hook, recorded with no free text. Tardis's reading, taken by
    Rio Grande; Serenity hasn't spoken to it yet, so it waits on the fresh review and Serenity's word as a partner.

Items 7 to 9 were decided in "Superyak: all hands", with an explicit yes from each of the three ships.

**Rio Grande's calls, for review.** From revision 2: the origin on the Pi; ships as members as themselves (law section
7); access requests left out of the name check; the hold before a command; and indexing every 60 s into a file. The
re-lay after an add is gone: item 9's backfill replaces it. New in revision 3, to carry out items 7 to 9:
- **High confidence at a prompt:** a value of at least 6 bytes found literally, or Near within
  `r_prompt = arccos 0.75` for a prompt of at least 4 words, inside 100 ms. The prompt is cut to 2,000 characters.
- **The prompt path trusts the index's last run,** about 60 s old, whose watermark therefore covers the chain, its
  epoch and members, and the peer's accounts.
- **The session's record,** with what the prompt hook showed read back from the transcript, since it may not write.
- **The lesson id's parts:** the peer it was laid on, and the SHA-256 of the embedded text, with a short form of 8
  and 8 hex characters.
- **Retraction by lesson id, for good,** and the origin refusing a retracted id's re-post.
- **The backfill:** the origin carries the chain's live lessons into the new room in the add's own transaction, as
  ordinary posts by their own authors, so federation's wire doesn't change.
- **Andy runs `lessons ship`** on each other peer.
- **A hold names one lesson first,** and any other found with it follows on its own line.

**For Andy,** only the acts reserved for a person: pairing the cards in section 11, item 3, comparing each pairing
code, and confirming his peers' codes for `station-lessons-room`; running `lessons ship` on each other peer; running
`init` on the Mac and loading its `federate` LaunchAgent (federation pull section 9); opening the room once; adding the
Mac's members when pull lands; and, if a person's data ever slips in, redaction by hand. No open question goes to
him.

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

## Re-check response

| # | Finding | Change |
|---|---|---|
| R1 | the origin can't check a remote member; "once" isn't checked | Applied as written: section 3's "Only Andy's", and section 6's last bullet. |
| R2 | the setup peer to peer needs | Applied as section 11, item 3, and section 12's "For Andy". The push worker is named as federation pull revision 4 names it, `federate` or `serve --sync`, which take one lock. The Mac's paragraph names its `federate` process and its pairing code from that spec. `lessons ship` also refuses `own` and `owner` (RN3), and Andy runs it. |
| R3 | the hold isn't bounded | Applied as written, with three changes the decisions require. The hold's reason takes decision 8's words, which say it is a lesson, not a refusal, in place of "Held once so these come first; run it again to go on." `seen` carries lesson ids (decision 9), not message ids. The prompt path writes no receipt (decision 7), so only the other events' queries write them, `seen` skipped first. R3's bounds stand: a `command` value of at least 6 bytes, each head at most once, at most 3 holds a session. Decision 8's record per (session, command head, lesson) sits inside them. |
| R4 | `ship:` has no grammar | Applied as written: section 2. |
| RN4 | a retraction is for good | Applied with decision 9: section 2. |
| RS1 to RS7, RN1, RN2, RN5 to RN9 | should-fix and nits | Not applied in this revision, except the part of RN5 that the prompt path needs: the watermark covers the chain, its epoch and members (section 4). |
