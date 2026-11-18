# v2: the whole stack, run end to end, and what was seen of finding here

Serenity, 2026-11-17 (Pacific; every time below is UTC on the 17th). Two things are reported. First, the
rehearsal of `docs/superpowers/specs/2026-11-17-v2-a-rehearsal-of-three-arms.md`: the whole path, from
recorded walks to a route offered to a turn under an arm, run in an experiment's own order with real
turns. Second, what was counted and probed the same day about how a turn comes to the files of its work
at this repository. The rehearsal looks for no gain and nothing here is tested for a difference.

## In short

- **The path holds.** Eighteen turns, every stage complete, every turn's own record agreeing with the
  frozen plan. No fault was found in what was checked: that each stage completed, and each turn's
  recorded arm, place, seed and block.
- **At this repository a turn names a first file of its work within seconds.** With the item's tests in
  the sandbox, 8 to 12 seconds, in nine turns. Begun from a commit message, with the item's new tests
  withheld and the parent's existing tests still there, 10 to 22 seconds, and every file its reference
  changes by 81 seconds, in ten turns.
- **On the team's own reading work, lists made from earlier walks held about as much of where a later
  worker went whether they were ordered by roads or by counts of places.**
- **None of this measures a saving, or an upper bound on one.** That a scored experiment of routes at
  this repository's item work is not worth its turns now is the lead's judgement, not a result.

## The rehearsal

### What was fixed before the first turn

| What | Fixed as |
| --- | --- |
| The plan | Frozen with its hashes before any turn: seed 20261117, one round, eighteen turns |
| The items | The item-maker's list, SHA-256 beginning 4b25d330. Its three pilot items A (3d8775bc), B (01c46a2d), C (a0c94043), and eight history items |
| The room program | Built from 670a3ba7; SHA-256 beginning 53863d42 |
| The scripts | `v2/probes/items/` at 670a3ba7 |
| The store | Store version "3", at its owner's commit 45be5dd0 on the branch `tardis/v2-walks-and-routes`, its four files held by hash. That branch was merged into `v2` after the rehearsal, at 7ab0a28b |
| The worker | `codex:gpt-6.1-sol`, codex-cli 0.163.0 |
| The machine | macOS on arm64, at a load of 5 to 17 from other work throughout |
| The screen | Every reference through the room's jail before any turn: six times for A, B and C, once for each history item. 26 of 26 passed and verified |

### What ran

19:42:39 to 20:25:18, 43 minutes.

| Stage | Result |
| --- | --- |
| History | One turn thrown away (59.6 worker seconds) and eight turns kept, nothing offered. All passed. The eight took 64 to 179 worker seconds |
| List | Eight turns teach. The store's own check replayed 297 cells |
| Offers | All three items were offered. One earlier turn was chosen for each, and one goal: `imprints.py` |
| Arms | Nine turns, in the order the plan's seed gave. All passed |
| Report | Written from the records |

| Place | Item | Arm | Worker s | Active s | Steps | First source file named | At |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | A | shuffled | 98.3 | 107.7 | 15 | `imprints.py` | 9.4 s |
| 11 | A | nothing | 80.7 | 90.4 | 14 | `imprints.py` | 8.4 s |
| 12 | A | route | 97.2 | 106.8 | 14 | `imprints.py` | 8.8 s |
| 13 | B | route | 223.1 | 232.0 | 20 | `imprints.py` | 10.8 s |
| 14 | B | shuffled | 199.3 | 208.1 | 18 | `imprints.py` | 10.1 s |
| 15 | B | nothing | 178.7 | 187.4 | 17 | `imprints.py` | 8.4 s |
| 16 | C | nothing | 126.6 | 139.5 | 13 | `imprints.py` | 11.7 s |
| 17 | C | route | 112.0 | 125.1 | 11 | `imprints.py` | 9.1 s |
| 18 | C | shuffled | 119.2 | 131.9 | 13 | `imprints.py` | 7.8 s |

`imprints.py` is a file each of the three references changes.

### What was held against the raw records afterwards

- Each of the nine turns' own room records the arm, the place, the seed and the block's hash that the
  plan and the block files give. The three turns under "nothing" hold no block.
- The order of arms is the plan's: shuffled, nothing, route at A; route, shuffled, nothing at B; nothing,
  route, shuffled at C. So every arm stood at every place once.
- **The blocks,** the same for all three items: each answer from the store is 1,327 bytes; the route
  block is 742 bytes, with three places and three roads; the shuffled block is 391 bytes, with three
  places and no roads; in each, no path is gone and one is marked as changed since.
- The list of turns that teach has SHA-256
  ba5bc6d39ffc9af34db90d0d14b0510a262397edd2b18eeeb41badeef1c04691.
- **The pass's own report is kept beside this one,** as the pass wrote it:
  `2026-11-17-v2-the-whole-stack-tested-pass-report.json`. It holds what the rehearsal's sections 5 and
  6 ask for and this page leaves out: each turn's unknown steps, its tokens and whether they are whole,
  its start, end and the machine's load, and every block's figures.

### What a turn was shown

The route block, after its opening sentences:

```
1. peer/superyak_peer/imprints.py (changed since)
   from where every turn starts to README.md: walked by 8 earlier turns
   then to .yak-check/check.py: walked by 1 earlier turn
   then to peer/superyak_peer/imprints.py (changed since): walked by 1 earlier turn
   1 earlier turn went a dearer way to it
```

The shuffled block lists `imprints.py`, `README.md` and `.yak-check/check.py`.

### What it showed

1. **The places between are what turns read at their start:** the README, and the check's own file. On
   these walks the road to a file runs through them.
2. **Three paths were named by all eight history turns:** `README.md`, `AGENTS.md` and
   `.yak-check/check.py`. A list of places ranked by how many turns named them would be led by those
   three. Such a list needs a rule for what every turn names, as the title rule has one for words.
3. **Every turn, the three given nothing among them, first named the goal at its second step,** 7.8 to
   11.7 seconds in. The route spec's section 9 already records that at these items the tests, which are
   in the sandbox, say where the work is.
4. **The first turn at an item was the slowest of its three at all three items.** By place within an
   item, worker seconds: 98.3, 80.7, 97.2; 223.1, 199.3, 178.7; 126.6, 112.0, 119.2. The first turns
   also took the most steps or as many: 15 against 14 and 14; 20 against 18 and 17; 13 against 11 and
   13. Every arm stood at every place once, the turns ran one after another, and the machine's load
   moved. No cause is identified, and by the rehearsal's spec nothing is read from it.
5. **Seconds by arm, for the record only.** Active seconds, route over nothing: 1.18, 1.24, 0.90.
   Shuffled over nothing: 1.19, 1.11, 0.95. The machine was loaded, and there are three items.
6. **Two cells of the pass's table print raw:** the tokens and the loads. The report's JSON holds the
   numbers. To be mended with the pass's next change.

## Work begun from a description

The route spec's section 9 names an experiment not yet written: work begun from a description, with the
tests kept from the sandbox until the check. Two probes looked at how a turn begun from a description
comes to its files. They are exploratory: ten turns, one worker program, no arm, nothing offered.

**How a probe turn was made, with no new room code.** The base is the commit's true parent with two
files laid over it: the commit's own message as `TASK.md`, and a small check that passes when anything
under the source directory differs from the parent. So a verdict in the probe says nothing of the work;
what is read is the walk. The room holds a title to 200 characters on one line, so a description cannot
travel in a title: the title names `TASK.md`. Each turn's copy was checked to hold its base and none of
the reference, the commit or the item's new test blobs. Two turns with a script in the worker's place
came first: one that changes a source file passed, one that hands in nothing failed.

**The parent's own tests were in the sandbox.** Only the item's new tests were withheld. At nine of the
ten items the item's test file was already there in its earlier version. Every turn named a test file
at some point, and two named one at or before their first source file (37a887d3 in the same step,
9490f597 two steps before). These were not turns without tests.

**The items,** by rules fixed before any turn, from items the list leaves out of every part of the
experiment: for the first probe, the reference changes exactly one source file and the message holds
neither that file's name nor its stem as a word (28 meet it, five taken evenly); for the second, the
reference changes two or more source files and the message holds none of their names or stems (eight
meet it, the first five). Both ask for a message of eight words or more. **The rules shut out a literal
file name. They do not shut out a message that names the component or a symbol:** "Owner trust" for
`owner_trust.py`, "Chat paging" for `chats.py`, `could_hold` as the function to add. These are not
descriptions that hide the place.

| Probe | Item | The reference changes | Named by the turn at | Changed by the turn | Steps, last step |
| --- | --- | --- | --- | --- | --- |
| 1 | 37a887d3 | `chats.py` | 13 s | yes | 13, 96 s |
| 1 | 5b0c8376 | `lessons.py` | 11 s | yes | 16, 85 s |
| 1 | 9490f597 | `ships.py` | 22 s | yes | 21, 129 s |
| 1 | 113d188e | `peer_routes.py` | 20 s | yes | 11, 112 s |
| 1 | 79aaa586 | `owner_trust.py` | 13 s | yes | 13, 104 s |
| 2 | d9860589 | `imprints.py`, `__main__.py` | 12 s, 41 s | both | 21, 160 s |
| 2 | 6f57b4cb | `chats.py`, `tickets.py`, `inbox.py` | 10 s, 19 s, 81 s | all three | 15, 84 s |
| 2 | 72889183 | `connector_apps.py`, `connector_routes.py` | 15 s, 15 s | both | 16, 103 s |
| 2 | 027834bf | `federation.py`, `owner_trust.py` | 12 s, 15 s | both | 20, 163 s |
| 2 | 7c6cda37 | `owner_trust.py`, `federation.py` | 14 s, 22 s | both | 11, 118 s |

- **In the first probe the first source file each turn named was the file its reference changes,** at
  its third or fourth step, 11 to 22 seconds in. The first 5 to 8 seconds of that is reading the task
  and the README.
- **In the second probe every file a reference changes was named and changed by its turn, and no other
  source file was changed.** The first reference-changed file was named at 10 to 15 seconds, the last at
  15 to 81 seconds.
- **Over the ten turns that is sixteen occurrences, of twelve distinct files, all named and all
  changed.**
- **Naming a file is not the end of finding.** These walks do not show what a turn understood of a file,
  whether it found everything the work needed inside it, or what it would have done with help after its
  first entry.
- One item has a turn from the night before with its tests in the sandbox: it first named `ships.py` at
  59 seconds. From the description, 22 seconds. One pair.

**Judged against the held-back tests, by replay.** What each turn changed under the source directory
was applied on its item's own base (the parent with the item's tests and its check laid over) by a script
in the worker's place, and the room judged that in its jail with the item's frozen check, as it judges a
reference. Nothing new was built for it. The control is the item's own reference through the same path.

| Items | The item's own reference, through the same path | The turn's change |
| --- | --- | --- |
| 37a887d3, 9490f597, 6f57b4cb, 72889183 | Passes, three runs of three | Passes at 72889183 (three replays of three). Fails at the other three, one replay each |
| d9860589 | Passes, run once | Fails, one replay |
| 79aaa586, 027834bf, 7c6cda37 | Fails from a directory named by the item's whole commit id: three runs of three at first, and again later at the two tried. Passes three of three from a directory not so named | From directories not so named: passes at 7c6cda37 (four replays of four), fails at the other two (two replays each) |
| 5b0c8376 | Fails wherever it was run: three runs as at first, one from a short directory with another name | Cannot be judged |
| 113d188e | Fails wherever it was run: four runs as at first, one from a short directory with another name | Cannot be judged |

- **Eight of the ten could be judged. A commit message got two turns' changes through their item's
  tests, and six failed.** The two are 72889183, whose task is 252 words and spells out each point, and
  7c6cda37. At 37a887d3 the tests use names the reference adds (`SINCE_SQL`, `events_kind_room_id`)
  that the message never gives. The other five failures were not looked into and are undiagnosed.
- **This table is a correction,** made the same day after both reads recorded below. It first said that
  five references failed in the jail for a cause not known, and that only five items could be judged.

**Why five references failed at first,** found afterwards with no new room code. A script in the
worker's place applies the reference's change inside the jail, runs the item's tests there as the check
runs them, and hands in what they printed as a file, which is read from the turn's repository. Only the
repository's own merged code runs, and the room's store takes in no text, as the design's rule 9 asks. A
passing item was run the same way first and passed.

- **5b0c8376: twelve errors, "AF_UNIX path too long".** The room gives a check its temporary directory
  inside the room's own directory; the item's check and the test runner nest theirs inside that; and
  macOS holds a Unix socket's path to 104 bytes. In the worker's place the temporary directory's own
  path was 118 characters. This item fails from the shorter directory too.
- **113d188e: "Operation not permitted"** in a test over real HTTPS. The jail forbids the network. That
  is the jail doing its work.
- **79aaa586, 027834bf, 7c6cda37: the directory's name.** One test of these items asserts that what it
  writes holds no secret, by finding in it no run of 32 hexadecimal characters; and what it writes holds
  a path. The controls ran in directories named by the item's whole commit id, forty such characters, so
  that test failed whatever the code. This was seen directly at 79aaa586, in the test's own words: one
  test failed and 22 passed. At the other two it is inferred: the same test, unchanged, is in both, and
  they show the same contrast. From directories not so named all three references pass three runs of
  three. Only 7c6cda37 was also run at three depths under another name, the deepest the first
  directory's own, and passed each. Run again as at first, 79aaa586 and 7c6cda37 failed again. So at
  these it is the name, and not the depth, the hour or the load.
- **The naming was the lead's, and it was the pass's too.** The lead's controls were named by whole
  commit ids and the replays by ten characters of them, so at 7c6cda37 a turn's change passed where its
  reference seemed to fail. The pass and the pilot's driver named every turn's directory, and every
  screened reference's, by the whole commit id as well. The rehearsal's items hold no such test, and
  passed. With the pass as it then stood, its own screen at these three items stopped: their references
  failed six runs of six. The pass now names its directories by ten characters of the id, and the same
  screen passes all three. The pilot's driver keeps the old names and says so.
- The rehearsal's screen ran its eleven references where the rehearsal itself ran, and all passed.

**What earlier work holds of the place,** counted with no turn over the list's 40 scored items and 51
history items, every history item earlier:

| What would be offered to a scored item | Names a file of its work | All of them |
| --- | --- | --- |
| Any file any history reference changed | 22 of 40 | 12 |
| The three files history changed most | 15 | 4 |
| The room's rule on the commit's subject: the three nearest, the files they changed | 11 | 3 |
| Three history items by chance (2,000 draws) | 8.3 (mean) | |

On these subjects the room's rule as it stands scored 11 where chance scored 8.3, and a fixed list of
the three most-changed files scored 15. A walk names files its turn does not change, so the first row
may undercount what walks would hold; that was not counted. The package is 38 to 54 Python files.

## A third probe: a user's words, and every test of the component withheld

Added the same day, after this report's reader suggested two things that may have aided the description
probes' turns in their quick entry: the parent's tests, and messages in the project's own words.
Exploratory again: five turns, one worker program, nothing offered. This section was written after the
read recorded below and has a read of its own.

**What was changed from the first two probes.**

- **Every test of the component is withheld, and there is no history.** The base is a commit with no
  parent, holding the parent's tree without `peer/tests`. Each turn's copy was checked to hold none of
  the parent's test blobs (45 to 90 of them), nor the parent commit, the reference, the commit or the
  item's new tests. Other components' tests stayed.
- **The task is in a user's words,** written by the lead from the commit's message by a rule fixed
  first: what a person using or running the station would see or want, in everyday words; no
  identifier; none of the project's own names for its parts or its work; at most 130 words; the same
  change as the message asks. Two fresh readers of the other family read the tasks before any turn. The
  first kept one, named changes to three, and had one item replaced because its one-line message could
  not bear a faithful task. The second confirmed those and named two more changes. All were made. The
  tasks run are 31 to 130 words.
- **This takes away the project's own naming. It does not take away every clue.** "Conversation",
  "board", "claim", "lessons" and "app" are everyday words and are also near to files' names.
- **Neither the title nor the check names the component's folder, and the check is a different one.**
  In the first two probes the check asked for a change under the component's source folder. Here it
  passes on any tracked change outside `TASK.md` and the check's own folder, tests and documents
  included. That is one more difference between a pair's two turns; all five turns here changed source,
  so no cell of the table rests on it. The title is "Make the change that TASK.md at the repository's
  root describes."
- **The items:** the four of the earlier ten whose own reference was then known to pass in the jail and
  whose message could bear a task, and one new item chosen by a rule (the first unused item in the
  list's order whose reference changes two or more source files, whose message has sixty words or more,
  and whose reference passed the jail three times of three). So four have a pair: their earlier turn,
  from the commit message with the parent's tests there.

In each cell the third probe's turn comes first and the item's earlier turn second.

| Item | The reference changes | First of them named | Named and changed | Steps, last step | Its change against the held-back tests |
| --- | --- | --- | --- | --- | --- |
| 37a887d3 | `chats.py` | 20 s; 13 s | 1 of 1; 1 of 1 | 18, 91 s; 13, 96 s | fails; fails |
| 9490f597 | `ships.py` | 20 s; 22 s | 1 of 1; 1 of 1 | 13, 64 s; 21, 129 s | fails; fails |
| 317a6e0b | `lessons.py`, `room_board.py`, `room_claims.py` | 15 s, the last at 27 s; no earlier turn | 3 of 3 | 15, 82 s | fails |
| 6f57b4cb | `chats.py`, `tickets.py`, `inbox.py` | 14 s; 10 s | named 2 and changed 1 of 3; 3 of 3 | 12, 72 s; 15, 84 s | fails; fails |
| 72889183 | `connector_apps.py`, `connector_routes.py` | 17 s; 15 s | 2 of 2; 2 of 2 | 15, 95 s; 16, 103 s | passes; passes |

Each item's own reference passed through the same path three times of three. Each replay of this
probe's turns ran once.

- **Every turn named a first file its reference changes at 14 to 20 seconds,** at its fourth to seventh
  step. The four earlier turns did at 10 to 22 seconds.
- **The five references hold ten reference-file occurrences, covering nine distinct files** (`chats.py`
  is in two). **Eight occurrences were named and changed, one was named and not changed, and one was
  never named.** The last two are both at 6f57b4cb.
- **At 6f57b4cb the turn changed `chats.py` alone among source files** (it also added a test file of
  its own). The reference makes the same kind of change in
  three places: where a page's messages are looked up in `chats.py`, their replies in `inbox.py`, and
  their sources in `tickets.py`. The item's earlier turn changed all three. Between the two turns the
  task's words, the tests and the history all differ, and the task here speaks of looking up messages.
  One pair cannot say which of those made the difference, or whether the turn took the other two
  lookups to be outside what it was asked.
- **One change of the five passes the held-back tests:** the same item as before, whose task spells
  out five points. The four failures are undiagnosed. Held-back tests may require unstated details, but
  these records do not distinguish that from implementation or discovery failures.
- **No turn named a file of another component's code.** Beyond the root and the check's folder, four
  turns named files under `peer` only, and one also named a file under `docs`.

**What it adds, and no more.** With the component's tests and the history withheld, and the task
rewritten without project identifiers, a first file of the work was still named within about twenty
seconds at all five items. Source files' names and the documents stayed, and every walk names
`README.md`. And it is the first of the three probes in which a turn did not change a file its
reference changes: at one item, in one pair.

## Reading work: the team's own workers

The team's readers and builders are not in a room, but their logs record what each read. For each worker
with a brief, the files its brief named and the files it read, in order of first reading, were taken from
the logs: 49 workers under one program, 68 with the other program's added. **These logs are not in the
repository:** a reader can check the arithmetic and not the source. A file counts as read when a reading
command names it; a search does not count; only first readings are kept. Each count scores a list made
from earlier workers against what a later worker read beyond its brief (a median of 8 files among the
49, and 6 among the 68), by how much of that falls in the list's first 5, 10 and 16 files. The scores
are means of that share over workers.

| Question | Compared | First 5 | First 10 | First 16 |
| --- | --- | --- | --- | --- |
| Roads or places? (the store, 43 workers, the same area's history) | Route | 0.280 | 0.391 | 0.513 |
| | Places by count | 0.284 | 0.413 | 0.511 |
| Whose earlier work? (32 workers of one program whose briefs have a title line) | Every earlier worker | 0.17 | 0.24 | 0.36 |
| | The last three | 0.18 | 0.27 | 0.38 |
| | Title words, the nearest three | 0.25 | 0.33 | 0.42 |
| | Shared brief files, the nearest three | 0.34 | 0.42 | 0.48 |
| One walk or many? (39 workers with five or more of the same area) | The nearest one, in its own order | 0.20 | 0.34 | 0.40 |
| | The nearest three | 0.30 | 0.42 | 0.52 |
| | Every one of the area | 0.22 | 0.33 | 0.49 |
| A walk of its own program, or the other's? (48 workers with one of each, pooled) | Its own | 0.16 | 0.29 | 0.34 |
| | The other | 0.19 | 0.29 | 0.35 |
| The same, for the 15 workers of one program | Its own | 0.12 | 0.18 | 0.20 |
| | The other | 0.16 | 0.37 | 0.52 |
| The same, for the 33 workers of the other program | Its own | 0.18 | 0.34 | 0.41 |
| | The other | 0.21 | 0.26 | 0.27 |

- **Roads or places** is the store's owner's measure, written before it was run, with the store built
  from each worker's earlier workers. The two lists scored the same at the first five for 30 of the 43,
  with the route better for 6 and worse for 7. A comparison in which most pairs tie had little room to
  show a difference either way: it does not show that order holds nothing. A cruder count by the lead,
  of roads one and two steps long, gave the same answer.
- **On these lists, whose work is taken moves the score more than how the list is ordered.** The room
  does not choose a store's history by area today: its rule picks at most three earlier turns by title
  words and makes the files they changed the goals, and the store is built from every walk in the list.
- **On these lists, places from the three nearest scored higher than places from the nearest one, and
  the whole area pooled scored lower again** at the short end. With one program alone the rise at 5 and
  10 is three points.
- **The pooled means for a walk of a worker's own program and of the other are close, and the two
  programs' workers go opposite ways,** as the last four rows show. One program's workers here are
  mostly readers with longer walks, the other's mostly builders. Roles, walk lengths and which histories
  were chosen are not controlled, so nothing is concluded about programs.
- **"The same area" in these logs is mostly the same job a round earlier.** Of the three nearest by
  shared brief files, 53 of 70 among the titled workers of one program, and 115 of 167 across both
  programs, are among the five workers just before.
- None of this says that giving a worker such a list saves it anything. It says where workers went. In
  the same logs, searching is about a sixth of a worker's commands.

## What it comes to

- **The stack runs.** Walks are recorded, a store makes roads of them and answers a route, the room
  offers it to a turn under an arm drawn from a seed, and a report is written from the records. All of
  it has now run together with real turns, in order, with every input held by hash.
- **A turn came to a first file of its work within seconds in every setting tried,** and in ten turns
  begun from a message every file its reference changes was named and changed. That says nothing of
  what came after a file was named. These observations establish no time saving and no upper bound on
  one.
- **A commit message got a turn's change through its item's tests at two of the eight items that could
  be judged.** At the one failure looked into, what the message lacked was names the tests use.
- **On the reading-work lists, counts of places scored as the store's routes did.** The store's owner
  has drafted places as a next store version.
- **Another reading holds as well as this one.** Messages in the project's own words and the parent's
  tests gave these turns quick entry, and sparse history with lists that mostly tie left the offline
  comparison of routes little room. On that reading, help after a turn's first entry is untried.

## Limits

- One worker program and one model for every item turn; fifteen probe turns; three rehearsal items of
  one feature.
- **What the first two probes' rules chose,** and the third's items come from the same pool. Small
  merged changes to one Python component that change tests, meet the item-maker's rule (the tests fail
  before and pass after), were left out of the experiment's parts by its fifth rule, and have a message
  of eight words or more. Larger changes, deletions, renames, other components and work not yet done are
  outside it.
- In the first two probes (ten turns) the tasks are commit messages written by the people who did the
  work. They carry the project's own words for its parts, and some name the component or a symbol. And
  the parent's tests were in those sandboxes: only the item's new tests were withheld.
- In the third probe (five turns) the tasks were rewritten by the lead without project identifiers and
  every test of the component was withheld. Five turns at five items, four of them paired with an
  earlier turn that differs in task, tests, history, title and check at once.
- The package is small. Nothing here says what happens where there are thousands of files.
- A walk records a file's name and blob, not the part read. Whatever a turn spends inside a file is
  outside what was measured.
- The reading-work counts are of where workers went, from logs outside the repository, with first
  readings only.
- The machine was loaded by other work all day. Seconds here are rough.

## What follows

- **No scored experiment of routes is proposed for this repository's item work.** This is the lead's
  judgement from what was seen, and not a result: nothing here measures what a route could save. The
  rehearsal's design stands ready.
- **The description-first experiment is not written now,** by the same judgement. The third probe is
  the nearest thing to it that was run: it needed no new room code. What was learnt for it
  is kept here: a task must travel in a file; the parent's tests would have to be withheld too; a turn
  can be judged against held-back tests by replay with no new room code; every item needs its screen.
- **Whether a test passes in the room can depend on where the room is and on what its directory is
  called. These are two different failures.** On macOS one item's tests bind a Unix socket whose path
  grows too long under the room's nested temporary directories; a short temporary directory for a check
  would be a change to the room, and is neither made nor designed here. Three items' tests fail under a
  directory whose name holds a commit id; a shorter path does not cure that, and another name does. The
  pass and the pilot's driver gave every turn such a name themselves, so this went beyond the lead's own
  directories; the pass's naming is changed, the pilot's is not. A screen shows such things only when it
  is run where and as the experiment runs, as the rehearsal's was.
- **The room keeps no words from a failed check, and by the design's rule 9 its store should not.** A
  script in the worker's place can hand in what a reference's tests printed, outside the store. That is
  how the causes above were found.
- **Open, and not decided here:** a larger repository; a grain finer than a file; help after a turn's
  first entry, which nothing here tries; whether a short list of places saves a reader anything, which
  only a trial with readers can say.

## Read

The reader's verdict is kept whole beside this report:
`2026-11-17-v2-the-whole-stack-tested-read.md`.

A fresh reader of the other model family read this report at 87e8ad9d against the run's records and
said: **push with named changes.** It worked every table again and got the same numbers. What it changed
is what they are said to show, and all of it is made here:

1. The probes did not run without tests: the parent's tests were in the sandbox. Said now where the
   probes are described, in "In short" and in the limits.
2. Quick first naming does not show that finding was finished, and bounds nothing a route could save.
   The first-file times are called that; the range to the last file is given; "little to carry" and
   "seconds to shorten" are gone; the choice not to run an experiment is marked as a judgement; and the
   other reading the reader gave is set beside the lead's.
3. The rehearsal's first-turn observation stays as an observation. The arithmetic of chance and the
   advice for a scored design are removed: the spec lets nothing be read from the rehearsal, and every
   arm already stood at every place.
4. The probes' rules shut out a literal file name and not a component's name or a symbol. Said, with
   what kind of work the rules chose.
5. The reading-work sentences are narrowed to these lists and their scores; the two programs' opposite
   results are shown beside the pooled means; that most route and places pairs tie is said.
6. The receipts of the repeated replays and controls, which the reader could not find, are added to the
   evidence kept with the read.
7. The pass's own report is kept beside this one, and the blocks' figures are given.
8. Smaller corrections: three paths, not the README alone, were named by every history turn; each
   median and each share of recent workers names its cohort; the thrown-away turn's time is given apart
   from the eight kept; kept words from a check "could help explain" a failure.

**The third probe's section** was added after that read, and read on its own at dc3dfc0f by another
fresh reader of the other family: **push with named changes,** five. It worked the section's table and
counts again from the walks and the records and got the same. All five are made here:

1. The four failed replays are called undiagnosed. A sentence that put them down to a gap between task
   and tests is gone: the records do not tell that from a mistake in the work or a place not found.
2. The first reader "suggested" two possible aids to quick entry; it did not establish them. And the
   tasks are said to be rewritten without project identifiers, not to have the project's naming taken
   away: source files' names and the documents stayed.
3. The third probe's check differs from the first two's, and that is named among the differences
   between a pair's turns.
4. The limits now count fifteen probe turns and say which probes each limit describes.
5. Ten reference-file occurrences are nine distinct files, and the one turn changed `chats.py` alone
   among source files.

One sentence of the lead's own judgement, at the end of that section, was withdrawn by the lead after
the read. The section now ends on what was observed.

**The correction on references that failed in the jail** was made the same day and read at 61962697 by a
third fresh reader of the other family: **push with named changes,** two. It counted every run again and
got the same: eight items that can be judged, two changes that pass and six that fail. The draft it read
put three items' failures down to the depth of the directory. The lead's own runs during the read showed
that wrong, and the reader named the change:

1. The depth is withdrawn as the cause. It is the directory's name, seen directly at one item and
   inferred at the other two, with each run said for the item it was made at.
2. What follows now tells the two failures apart, the socket's path and the name, and says that the
   pass and the pilot's driver make such names themselves.
