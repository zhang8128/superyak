# v2: the whole stack, run end to end, and what it can carry here

Serenity, 2026-11-17 (Pacific; every time below is UTC on the 17th). Two things are reported. First, the
rehearsal of `docs/superpowers/specs/2026-11-17-v2-a-rehearsal-of-three-arms.md`: the whole path, from
recorded walks to a route offered to a turn under an arm, run in an experiment's own order with real
turns. Second, what was counted and probed the same day about whether such an offer has anything to
shorten at this repository. The rehearsal looks for no gain and nothing here is tested for a difference.

## In short

- **The path holds.** Eighteen turns, every stage complete, every turn's own record agreeing with the
  frozen plan. No fault was found in it.
- **At this repository a turn finds where its work is in seconds, with or without help.** With its tests
  in the sandbox, 8 to 12 seconds. Begun from a commit message with no tests, 10 to 22 seconds, and it
  found every file the work needed: sixteen of sixteen in ten turns.
- **What earlier walks know is which places matter. The way between them added nothing that could be
  measured,** by two instruments, on the team's own reading work.
- **So an offer of roads to files has little to carry here.** Whether it carries more at a larger
  repository, or at a grain finer than a file, is not known.

## The rehearsal

### What was fixed before the first turn

| What | Fixed as |
| --- | --- |
| The plan | Frozen with its hashes before any turn: seed 20261117, one round, eighteen turns |
| The items | The item-maker's list, SHA-256 beginning 4b25d330. Its three pilot items A (3d8775bc), B (01c46a2d), C (a0c94043), and eight history items |
| The room program | Built from 670a3ba7; SHA-256 beginning 53863d42 |
| The scripts | `v2/probes/items/` at 670a3ba7 |
| The store | Store version "3", at its owner's commit 45be5dd0 on the branch `tardis/v2-walks-and-routes`, its four files held by hash. Not yet in `v2` |
| The worker | `codex:gpt-6.1-sol`, codex-cli 0.163.0 |
| The machine | macOS on arm64, at a load of 5 to 17 from other work throughout |
| The screen | Every reference through the room's jail before any turn: six times for A, B and C, once for each history item. 26 of 26 passed and verified |

### What ran

19:42:39 to 20:25:18, 43 minutes.

| Stage | Result |
| --- | --- |
| History | One turn thrown away and eight turns, nothing offered. All passed. 64 to 179 worker seconds |
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
  plan and the block files give. The route block is 742 bytes and the shuffled block 391, the same for
  all three items. The three turns under "nothing" hold no block.
- The order of arms is the plan's: shuffled, nothing, route at A; route, shuffled, nothing at B; nothing,
  route, shuffled at C.

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

1. **The places between are what every turn reads at its start:** the README, and the check's own file.
   On these walks the road to a file runs through them.
2. **A list of places ranked by how many turns named them would put the README first.** Such a list needs
   what the title rule already has for words: leave out what over half the turns that teach name, and
   leave out the check's own files.
3. **Every turn, the three given nothing among them, first named the goal at its second step,** 7.8 to
   11.7 seconds in. The tests say where the work is.
4. **The first turn at an item was the slowest of its three at all three items, whatever its arm.** By
   place within an item, worker seconds: 98.3, 80.7, 97.2; 223.1, 199.3, 178.7; 126.6, 112.0, 119.2. If
   place did nothing that would happen one time in 27. Why is not known. A scored design should throw
   away a first turn at each item, or balance place across arms.
5. **Seconds by arm, for the record only.** Active seconds, route over nothing: 1.18, 1.24, 0.90.
   Shuffled over nothing: 1.19, 1.11, 0.95. Arm is tangled with place, the machine was loaded, and there
   are three items.
6. **Two cells of the pass's table print raw:** the tokens and the loads. The report's JSON holds the
   numbers. To be mended with the pass's next change.

## Work begun from a description

The route spec's section 9 names an experiment not yet written: work begun from a description, with the
tests kept from the sandbox until the check. Before writing it, two probes asked what it would have to
shorten. They are exploratory: ten turns, one worker program, no arm, nothing offered.

**How a probe turn was made, with no new room code.** The base is the commit's true parent with two
files laid over it: the commit's own message as `TASK.md`, and a small check that passes when anything
under the source directory differs from the parent. So a verdict in the probe says nothing of the work;
what is read is the walk. The room holds a title to 200 characters on one line, so a description cannot
travel in a title: the title names `TASK.md`. Each turn's copy was checked to hold its base and none of
the reference, the commit or the tests. Two turns with a script in the worker's place came first: one
that changes a source file passed, one that hands in nothing failed.

**The items,** by rules fixed before any turn, from items the list leaves out of every part of the
experiment: for the first probe, the reference changes exactly one source file and the message names
neither that file nor its stem as a word (28 meet it, five taken evenly); for the second, the reference
changes two or more source files and the message names none of them (eight meet it, the first five).

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

- **In the first probe the first source file each turn named was the file the work is in,** at its third
  or fourth step. The first 5 to 8 seconds of that is reading the task and the README.
- **In the second probe every file a reference changes was named and changed by its turn, and no other
  source file was changed.** Sixteen files to find in the ten turns; sixteen found.
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

**What a description would have had to work with,** counted with no turn over the list's 40 scored items
and 51 history items, every history item earlier:

| What would be offered to a scored item | Names a file of its work | All of them |
| --- | --- | --- |
| Any file any history reference changed | 22 of 40 | 12 |
| The three files history changed most | 15 | 4 |
| The room's rule on the commit's subject: the three nearest, the files they changed | 11 | 3 |
| Three history items by chance (2,000 draws) | 8.3 (mean) | |

The room's rule as it stands barely beats chance on these subjects, and a fixed list of the three
most-changed files beats it. A walk names more than its turn changes, so real walks would know more than
the first row; how much more was not counted. The package is 38 to 54 Python files.

## Reading work: the team's own workers

The team's readers and builders are not in a room, but their logs record what each read. For each worker
with a brief, the files its brief named and the files it read, in order of first reading, were taken from
the logs: 49 workers under one program, 68 with the other program's added. **These logs are not in the
repository:** a reader can check the arithmetic and not the source. A file counts as read when a reading
command names it; a search does not count; only first readings are kept. Each count scores a list made
from earlier workers against what a later worker read beyond its brief (a median of 8 files), by how
much of that falls in the list's first 5, 10 and 16 files.

| Question | Compared | First 5 | First 10 | First 16 |
| --- | --- | --- | --- | --- |
| Do roads say more than places? (the store, 43 workers, the same area's history) | Route | 0.280 | 0.391 | 0.513 |
| | Places by count | 0.284 | 0.413 | 0.511 |
| Whose earlier work counts? (32 workers whose briefs have a title line) | Every earlier worker | 0.17 | 0.24 | 0.36 |
| | The last three | 0.18 | 0.27 | 0.38 |
| | Title words, the nearest three | 0.25 | 0.33 | 0.42 |
| | Shared brief files, the nearest three | 0.34 | 0.42 | 0.48 |
| One walk or many? (39 workers with five or more of the same area) | The nearest one, in its own order | 0.20 | 0.34 | 0.40 |
| | The nearest three | 0.30 | 0.42 | 0.52 |
| | Every one of the area | 0.22 | 0.33 | 0.49 |
| Its own program's walk, or the other's? (48 workers with one of each) | Its own | 0.16 | 0.29 | 0.34 |
| | The other | 0.19 | 0.29 | 0.35 |

- **Roads against places** is the store's owner's measure, written before it was run, with the store
  built from each worker's earlier workers. The route was better, worse or the same at the first 5 in
  6, 7 and 30 of the 43. A cruder count by the lead, of roads one and two steps long, gave the same
  answer.
- **Whose work counts moves the result more than how the list is ordered.** The room does not choose a
  store's history by area today: its rule picks at most three earlier turns by title words and makes
  the files they changed the goals, and the store is built from every walk in the list.
- **A few near walks rank places better than one, and the whole area pooled falls back** at the short
  end. With one program alone the rise at 5 and 10 is three points.
- **No difference was seen between a walk of a worker's own program and one of the other's.** A longer
  walk finds more, and one program's workers here are mostly readers with longer walks.
- **"The same area" in these logs is mostly the same job a round earlier:** of the three nearest by
  shared brief files, three in four are among the five workers just before.
- None of this says that giving a worker such a list saves it anything. It says where workers went. In
  the same logs, searching is about a sixth of a worker's commands.

## What it comes to

- **The stack runs.** Walks are recorded, a store makes roads of them and answers a route, the room
  offers it to a turn under an arm drawn from a seed, and a report is written from the records. All of
  it has now run together with real turns, in order, with every input held by hash.
- **At this repository there is little for it to carry.** A turn is at its file within seconds whether
  it is given its tests, a commit message, or a route. In ten turns begun from a message no place was
  left out.
- **A commit message got a turn to the right files every time, and through its item's tests one time in
  the five that could be judged.** At the one failure looked into, what the message lacked was names
  the tests use. That is a thing of the work itself, which a walk of earlier work does not hold.
- **What earlier walks do know is places, from a few near walks, across programs.** That is a simpler
  thing than a road network, and the store's owner has drafted it as a next store version.

## Limits

- One worker program and one model for every item turn; ten probe turns; three rehearsal items of one
  feature.
- The probes' tasks are commit messages written by the people who did the work. They carry the
  project's own words for its parts. A task in a user's words was not tried.
- The package is small. Nothing here says what happens where there are thousands of files.
- A walk records a file's name and blob, not the part read. Whatever a turn spends inside a file is
  outside what was measured and outside what a route of file names could carry.
- The reading-work counts are of where workers went, from logs outside the repository, with first
  readings only.
- The machine was loaded by other work all day. Seconds here are rough.

## What follows

- **No scored experiment of routes is proposed for this repository's item work.** The rehearsal's
  design stands ready for a place where finding costs something.
- **The description-first experiment is not written,** for the reason above: at this repository it would
  have seconds to shorten. What was learnt for it is kept here: a task must travel in a file; a turn
  can be judged against held-back tests by replay with no new room code; every item needs its screen.
- **A failed check leaves no words in the room.** Five references failed in the jail and nothing says
  why. A line kept from the check, held as data, would have said.
- **Open, and not decided here:** a larger repository; a grain finer than a file; whether a short list
  of places saves a reader anything, which only a trial with readers can say.
- **The store's branch merges into `v2`** by the three steps agreed with its owner.
