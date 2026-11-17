# v2: a rehearsal of the whole path under the three arms

Serenity, 2026-11-17, revision 2. It follows section 9 of
`docs/superpowers/specs/2026-11-16-v2-a-route-offered.md` ("the route spec"), as that section stands after
"What follows now". A fresh reader of the other family approved revision 1 with named changes; all are
made here, and the last section says where. Revision 1 called it a trial, with two rounds.

## 1. What it is, and what it is not

**It is the whole path, run once in the order an experiment would run it,** at items of the list: turns at
history items with nothing offered; the list of turns let teach, made from them and fixed; the store built
from that list; for each of three items the goals, the answer, the offer file and the two blocks; then that
item's turns under the three arms.

**It is not a pilot and not an experiment.** The route spec says no third pilot follows, and none does. It
gives no `n`. No number from it enters any later sizing or reading, and none of its turns teaches or is
scored anywhere else.

**Said before any turn: no gain is looked for.** Section 9 saw a turn at these items first name its work's
file within 8 to 15 seconds. Whatever the nine turns under the arms take, three items once each say
nothing of a route's effect.

**What it shows:**

- that the path holds together at listed items in an experiment's own order, with every turn's arm, block
  and inputs on record, which until now was shown only piece by piece;
- that the pass, which any later experiment needs, runs: its plan, its checks of what may teach, its stops;
- what the blocks at these items hold, and what a turn under each arm names first: observed, three times.

## 2. The items

From the list that exists (SHA-256 `4b25d330dd402241b076e3aa656eb69ea60d67113b7bfb62090bd3f0f709a284`), by
its order, with nothing chosen by hand.

- **Three items under the arms:** the list's three pilot items. By the first ten digits of their commits:
  3d8775bc64, 01c46a2d52, a0c940438c.
- **Eight history items:** the eight commits that can be items and come just before the first of the
  three in the list's order: 5d880a7d24, d441e3759e, 9ee2c94007, 5cf7b32dfc, 1f9804d5c0, 9358357fe6,
  0e5fb1afbc, 163aaa18c2. The last of them names the same test file as the first of the three; the route
  spec's rule 5 holds scored items apart from one another, not history from scored.

**What the ranker would choose, counted with no turn** (each history item taken to have one turn that
teaches, and a reference's changes standing for a turn's): for each of the three, one turn, the last
history item's, and one goal, `imprints.py`. What the blocks then hold is not foretold from that: one goal
can have several places and roads on its way. It is measured when they are made, and reported.

## 3. The screen

Before any turn, each reference is shown through the jail on the rehearsal's machine: six times for each
of the three items, once for each history item. Twenty-six.

- **A reference has passed** when the room's record of it is a verified pass, of the tree the list names
  for that item's reference, under the check the list names, by the room and jail programs the plan names,
  on this machine.
- **A reference whose check fails** leaves its item out. For one of the three, on any of its six: the
  rehearsal is not run. For a history item: it is left out by name; with fewer than four left, the
  rehearsal is not run.
- **An instrument that fails** (no verdict, a tree or check that is not the one named, a run that could not
  be used) leaves no item out. It stops the screen, and is reported and mended before the screen is begun
  again from its start.
- **What was left out, and why, is written down once and not changed.** Nothing takes a left-out item's
  place, and none is tried again to make it pass.

## 4. The pass

One program runs it, from a plan it prints first and writes down with the hash of every input: the list of
items, the room program, the store program, the worker program with its model and version, the test
environment's lock, the limits a turn runs under, that every turn has a first line of its own, the seed,
and the order of every turn.

1. **A turn thrown away,** at the first history item that the screen kept, nothing offered, in a room of
   its own that is in no plan.
2. **The history turns:** one turn at each history item the screen kept, in the list's order, with the
   arm `nothing` kept by the room, each in a room and repository of its own. The clock is run once
   through with one turn a day, so that a room holds exactly one attempt.
3. **The plan of what may teach** is written by the pass from what it ran: for each history turn of step
   2 its room, its item and its one attempt. It is not made by looking for rooms in a directory. Before
   the room makes the list from it, the pass checks each of those rooms: exactly one attempt, and its arm
   recorded as `nothing`. The room of step 1, a reference's room, an earlier pilot's or probe's room, and
   every room of step 5 are never in it.
4. **The list of turns let teach** is made by the room from that plan and admitted by the room. The pass
   counts the turns that teach as the room classes them under the measure (`share`, version 1: passed
   and verified), not the entries of the list; a turn that failed is in its file and does not teach. Fewer
   than four that teach: the pass stops here. Each line of each walk, with its newline, is at most 1 MiB
   (1,048,576 bytes), or the pass stops: that holds under either reading of the limit. The list and the
   walks are hashed and are not changed afterwards.
5. **The offers.** The store is built from the list and its walks, and checked. For each of the three
   items the room chooses the goals, the store answers, and the room makes the offer file at the item's
   base. The pass takes that base from the list of items, and the room it later makes for the item's turns
   must hold the item at that same base, or the pass stops. The route block and the shuffled block are
   rendered once each. The offer file, the two blocks, their hashes and lengths, the answer and its size
   in bytes are kept and not changed afterwards. More than 64 goals stops the pass; nothing is cut.
   **An item whose offer is empty gets no turns under the arms,** and is reported. If all three are empty
   the pass stops. No other history is run in its place.
6. **The turns under the arms:** one round. Each of the three items, in the list's order, gets its three
   arms one after another, in the order drawn as below. Each turn is in a room and repository of its own,
   with its arm, its place in the order and the seed kept by the room, and for the two offering arms the
   offer file of step 5. After each turn the pass compares the block's hash and length in the room's
   record of the turn with the ones kept in step 5, and stops if they differ. Nine turns.

**One turn means one.** A turn that fails its check is a result: it is kept with its seconds, and it is
not tried again. The clock ends with a failure's exit status when its one turn a day is used up; the pass
reads the room's record of the turn, not that status.

**The order of the arms** for an item: the three arms sorted, ascending, by the SHA-256, as lowercase
hex, of the text `<seed>:<round>:<commit>:<arm>` in UTF-8 with no newline. The seed is `20261117`. The
round is `1`. The commit is the item's, all forty lowercase digits. The arms are `nothing`, `route` and
`shuffled`. Two equal hashes are ordered by the arm's name. That gives, for the three items in the list's
order: shuffled, nothing, route; route, shuffled, nothing; nothing, route, shuffled. Each arm is first
once.

**It stops** when a file named `STOP` is in its directory, between turns; when an instrument fails (a
turn with no verdict in the room's record, a block whose hash or length is not the one kept, a room that
refuses the offer); and at the places the steps name. What was done before a stop is left as it is.

**The store's version is one,** `"3"`, read by a room built from a commit that reads it; the store program
is the one its owner's spec describes, at the commit its latest reader confirmed. Both are in the plan.

## 5. What is reported

All of it is given as it was recorded, turn by turn. None of it is tested for a difference, and no
spread is worked from it.

- **Each turn:** its arm and place; whether it passed; the worker's seconds and the active seconds, a
  failed turn's too; steps, and how many were of a kind the room did not know; tokens, with whether the
  count was whole; the time it began and ended and the machine's load before and after, taken by the
  pass. Under an offering arm: the block's hash and length and whether it was empty, as the room's record
  of the turn holds them.
- **Where a walk first names things.** A step's number counts from nought. "First names" is by the time
  a step was first seen, not the time of its result. A source file is one under `peer/superyak_peer/`.
  For each turn: the step and second at which it first names a file its reference changes; the first
  source file it names. Where a walk names none, that is said, not left blank.
- **Each block:** the first tracked path it lists and the first source file it lists, each on its own,
  so that what a turn named first can be held against the right one of them; and how many places and
  roads it holds.
- **Each item:** its three turns' active seconds side by side, and the three ratios between them where all
  three passed. Three items give at most three of each. They are what was seen.
- **The history turns:** which passed, their seconds, and the count of turns that teach.
- **The screen:** every reference's result, and what was left out.

## 6. The route spec's open points, for this rehearsal

Each is settled for the rehearsal or said to stand, as that spec asks before any turn is offered anything.

| The point | For this rehearsal |
| --- | --- |
| The counts in an offer are the store's | Stands. The report gives the store's own check on the store that answered, and the list's whole hash |
| A road's path that is gone is rendered, marked as gone | Stands. The report counts the paths marked gone or changed in each block |
| A goal no turn named is marked as changed | Stands, and is counted in the same place |
| The base given to the offer file's maker is the operator's | Settled here: the pass takes it from the list of items, and stops unless the room that runs the item's turns holds the item at that base |
| More than 64 goals are refused late | Stands. Three chosen turns may have changed more than 64 files between them; that stops the pass, and nothing is cut |
| A refusal of the list's maker does not name the turn | Stands. The list is made before any offered turn, and a refusal stops the pass there |
| The admission's reads have no bound | Stands. Its inputs are rooms the pass made itself, minutes before |
| The clock's listing does not turn replacement objects off | Stands. The repositories are made by the pass |
| An answer's size | Measured here, for three answers, and reported; an answer over the bound is refused as now |
| A walk line's limit | Settled for the pass by step 4's check of the whole line with its newline |

## 7. What is built

- **The pass,** beside the item scripts (`v2/probes/items/`): the plan; the screen; steps 1 to 6; the
  stops; the report's tables. It calls the room's commands as they are and the store by a path it is
  given, whose hash it writes down. Nothing in the room changes.
- **Its tests,** with stand-in workers and a stand-in store:
  - the plan of what may teach holds the history rooms and no other, with a room of each other kind
    standing beside them (the turn thrown away, a reference's, an offered turn's, a room with two
    attempts, a room whose arm is not `nothing`), and each of those refused or left out as step 3 says;
  - a turn of step 6 never teaches;
  - a stand-in worker under an offering arm finds, in the prompt it was given, the very bytes of the kept
    block, and under `nothing` finds none;
  - the order of arms is the one section 4 gives for its seed, and another seed worked by hand;
  - a fixture history whose answer has several goals, a route stitched from several turns' roads, and
    detours, goes through steps 4 to 6, since the live items may give one goal only;
  - two rounds run with stand-ins, though the live rehearsal has one;
  - each stop stops where it says and leaves what was done; a failed turn does not stop the pass, though
    the clock's exit status is a failure's; an empty offer gives its item no turns; all empty stops;
  - an offering arm with no offer file, a block whose hash differs from the kept one, an item's room at
    another base, a walk line over the limit, and a second run into the same directory are each refused.

## 8. What it costs

Eighteen turns: one thrown away, eight of history, nine under the arms. At the two to five minutes the
pilots' turns took, about an hour of one machine, with nothing else heavy on it. The screen is twenty-six
references, about ten minutes.

## 9. What this narrows, said before any turn

- **Three items of one run of work, one worker program, one machine, once each.** It is a rehearsal of
  the instrument. It measures no effect.
- **The three items' own earlier turns are not history,** though fifteen were measured: an item's turns
  teach other items, not itself.
- **The history is eight items chosen by place, and one of them is what the ranker takes.** With another
  eight the blocks would differ. A rule that spreads the eight over more kinds of work was looked at
  (going back, keeping the nearest item whose test files none kept already names); it is not used, since
  it promises no more goals, and the fixture of section 7 is what puts several goals through the path.
- **A pass is what the check observed,** as the route spec's section 6 says.

## What the reader named, and where it is answered

| Named | Where |
| --- | --- |
| A rehearsal of the path, not a look at the spread between arms; nothing from it enters a sizing | Sections 1 and 5; the two claims of what it could tell from noise are gone |
| One round live, eighteen turns; two rounds and richer routes with stand-ins | Sections 4, 7 and 8 |
| Do not foretell the blocks from the ranker's count; measure them | Sections 2 and 5 |
| An empty offer is gated before the arm turns, with no other history in its place | Section 4, step 5 |
| The plan of what may teach is written from what was run, never found; one attempt, arm `nothing`; the turns that teach counted as the room classes them; the list, offers and blocks fixed and compared after each turn; a first line of its own and the limits pinned | Section 4, the plan and steps 2 to 6 |
| What "a reference passed" means; a failing check apart from a failing instrument; what was left out written once; nothing in its place; the turn thrown away at the first history item kept | Section 3, and step 1 |
| A failed turn is a result though the clock's exit status is a failure's | Section 4 |
| The hash's input made exact; the orders worked | Section 4. Worked by the lead too, with the same result |
| The base, the 64 goals, and a walk line's limit | Section 4, steps 4 and 5, and section 6 |
| The block's bytes, hash and empty flag for each turn; a stand-in that finds the block in its prompt; a shuffled block's first tracked path and first source file apart; the conventions; failed turns' seconds kept | Sections 5 and 7 |
| "Files a turn did not need" | Gone from section 1; the record in the route spec is corrected in the same way |
