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

| The item's own reference, through the same path | Items | The turn's change |
| --- | --- | --- |
| Passes (run once) | 37a887d3, 9490f597, d9860589, 6f57b4cb, 72889183 | Passes at one (72889183, three replays of three). Fails at four, one replay each |
| Fails every time (three or four runs) | 5b0c8376, 113d188e, 79aaa586, 027834bf, 7c6cda37 | Passes at one (7c6cda37, three replays of three). Fails at four |

- **Where the control passes, a commit message got one turn in five through its item's tests.** That
  one's task is 252 words and spells out each point. The four failures are single observations. At
  37a887d3 the tests use names the reference adds (`SINCE_SQL`, `events_kind_room_id`) that the message
  never gives; the other three were not looked into.
- **Where the control fails, a failed replay says nothing of the turn.** Five of the ten items are such:
  their reference's own tree fails the item's check in the jail each time, though two of them, tried by
  hand, pass the same check outside it. At one, the turn's change passes three times of three. Why is not
  known, because the room keeps no words from a failed check. The rehearsal's screen exists for this and
  found none among its eleven items.

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
- **A commit message got a turn's change through its item's tests at one of the five items that could
  be judged.** At the one failure looked into, what the message lacked was names the tests use.
- **On the reading-work lists, counts of places scored as the store's routes did.** The store's owner
  has drafted places as a next store version.
- **Another reading holds as well as this one.** Messages in the project's own words and the parent's
  tests gave these turns quick entry, and sparse history with lists that mostly tie left the offline
  comparison of routes little room. On that reading, help after a turn's first entry is untried.

## Limits

- One worker program and one model for every item turn; ten probe turns; three rehearsal items of one
  feature.
- **What the probes' rules chose.** Small merged changes to one Python component that change tests,
  meet the item-maker's rule (the tests fail before and pass after), were left out of the experiment's
  parts by its fifth rule, and have a message of eight words or more. Larger changes, deletions, renames,
  other components and work not yet done are outside it.
- The probes' tasks are commit messages written by the people who did the work. They carry the
  project's own words for its parts, and some name the component or a symbol. A task in a user's words
  was not tried.
- The parent's tests were in the probes' sandboxes. Only the item's new tests were withheld.
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
- **The description-first experiment is not written now,** by the same judgement. What was learnt for it
  is kept here: a task must travel in a file; the parent's tests would have to be withheld too; a turn
  can be judged against held-back tests by replay with no new room code; every item needs its screen.
- **A failed check leaves no words in the room.** Five references failed in the jail and nothing says
  why. Words kept from the check, held as data, could help explain such failures.
- **Open, and not decided here:** a larger repository; a grain finer than a file; help after a turn's
  first entry; whether a short list of places saves a reader anything, which only a trial with readers
  can say.

## Read

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
