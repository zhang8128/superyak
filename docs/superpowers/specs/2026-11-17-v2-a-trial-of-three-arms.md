# v2: a trial of the three arms

Serenity, 2026-11-17, revision 1. Not yet read. It follows section 9 of
`docs/superpowers/specs/2026-11-16-v2-a-route-offered.md` ("the route spec"), as that section stands after
"What follows now". It is a small run, and it is built so that what it needs can be used by whichever
experiment is run later.

## 1. What it is, and what it is not

**It is the whole path, run once in the order an experiment would run it,** at items of the list: turns at
history items with nothing offered; the list of turns let teach, made from them and fixed; the store built
from that list; for each of three items the goals, the answer, the offer file and the two blocks; then that
item's turns under the three arms.

**It is not a pilot for sizing and not an experiment.** The route spec says no third pilot follows, and
none does: nothing here gives an `n`, and no turn of it enters a later reading.

**Said before any turn: no gain is expected.** Section 9 counted that a turn at these items is at its
work's file within 8 to 15 seconds, and that the steps naming only files a turn did not need are a median
6% of a walk's time. A route of file names has that little to take away here.

**What it can show:**

- that the path holds together at listed items in an experiment's own order, with every turn's arm, block
  and inputs on record, which until now was shown only piece by piece;
- what a turn does with a block: whether it goes first where a route points, and what the same places
  shuffled do instead;
- the spread, between two rounds and three items, of the ratio of one arm's seconds to another's. No
  sizing has had that: both pilots offered nothing.

## 2. The items

From the list that exists (SHA-256 beginning 4b25d330), by its order, with nothing chosen by hand.

- **Three items under the arms:** the list's three pilot items, which have fifteen measured turns with
  nothing offered already. By the first ten digits of their commits: 3d8775bc64, 01c46a2d52, a0c940438c.
- **Eight history items:** the eight commits that can be items and come just before the first of the
  three in the list's order: 5d880a7d24, d441e3759e, 9ee2c94007, 5cf7b32dfc, 1f9804d5c0, 9358357fe6,
  0e5fb1afbc, 163aaa18c2. The last of them names the same test file as the first of the three; the route
  spec's rule 5 holds scored items apart from one another, not history from scored.

**What the ranker would choose, counted with no turn** (each history item taken to have one turn that
teaches, and a reference's changes standing for a turn's): for each of the three, one turn, the last
history item's, and one goal, `imprints.py`, which each of the three's references changes. So the blocks
will be short, and the route and the shuffled places will differ little. That is reported as it comes out.

**Before any turn, each reference is shown through the jail on the trial's machine:** six times for each
of the three, once for each history item. If any of the eighteen fails, the trial is not run and that is
reported. A history item whose reference fails is left out by name; with fewer than four left, the trial
is not run. None is tried again to make it pass.

## 3. The pass

One program runs it, from a plan it prints first and writes down with the hash of every input: the list of
items, the room program, the store program, the worker program with its model and version, the test
environment's lock, the seed, and the order of every turn.

1. **A turn thrown away,** at the first history item, nothing offered, as both pilots did.
2. **The history turns:** one turn at each history item, nothing offered, each in a room and repository of
   its own. One turn means one: a failed turn is not tried again.
3. **The list of turns let teach** is made by the room from those rooms and from no other: not the turn
   thrown away, no reference's room, none of the earlier pilots' or probes' rooms, and no room of step 5.
   The room admits it. It is hashed and does not change afterwards. Fewer than four turns that teach: the
   pass stops here and says so.
4. **The store** is built from that list and its walks, and checked. For each of the three items the room
   chooses the goals, the store answers, and the room makes the offer file at the item's base, which the
   pass takes from the list of items and writes down beside the offer file's hash. The route block and the
   shuffled block are rendered once each and kept, with their hashes and the answer's size in bytes.
5. **The turns under the arms:** two rounds. In a round each of the three items, in the list's order,
   gets its three arms one after another, in an order drawn as below. Each turn is in a room and
   repository of its own, with its arm, its place in the order and the seed kept by the room, and for the
   two offering arms the offer file of step 4. Eighteen turns. One turn means one.

**The order of the arms** for an item in a round: the three arms sorted by the SHA-256 of the text
`<seed>:<round>:<the item's commit>:<arm>`, as lowercase hex. The seed is 20261117. So the order can be
worked by anyone and depends on no library's generator.

**It stops** when a file named `STOP` is in its directory, between turns; when an instrument fails (a
turn with no verdict, a block whose hash is not the one kept, a room that refuses the offer); and at the
places steps 3 and the screen name. A turn that fails its check is a result and stops nothing.

**The store's version is one,** `"3"`, read by a room built from a commit that reads it; the store program
is the one its owner's spec describes at the commit its latest reader confirmed. Both are in the plan.

## 4. What is read from it

All of it is given as it was measured, turn by turn, and none of it is tested for a difference.

- **Each turn:** its arm and place; whether it passed; the worker's seconds and the active seconds; steps;
  tokens; the machine's load before and after; the step and second at which its walk first names a file
  its reference changes; and, under an offering arm, the first source file it names and whether that is
  the first place its block gave.
- **Each item in each round:** the ratio of active seconds, route to nothing, shuffled to nothing, route to
  shuffled, where all three turns passed; and which did not.
- **Over the six:** the least, middle and greatest of each ratio, and the spread of its logarithm.
- **What it could not have shown,** said with the result: with six ratios, and the largest of the second
  pilot's three spreads between rounds taken for every turn, a ratio would have to be about a fifth from
  1 (under 0.83 or over 1.21) before these turns could tell it from noise.
- **The history turns:** which passed, their seconds, and the list's count of turns that teach.

## 5. The route spec's open points, for this trial

Each is settled for the trial or said to stand, as that spec asks before any turn is offered anything.

| The point | For this trial |
| --- | --- |
| The counts in an offer are the store's | Stands. The report gives the store's own check on the store that answered, and the list's hash |
| A road's path that is gone is rendered, marked as gone | Stands. The report counts the paths marked gone or changed in each block |
| A goal no turn named is marked as changed | Stands, and is counted in the same place |
| The base given to the offer file's maker is the operator's | Settled here: the pass takes it from the list of items and writes it beside the offer file's hash |
| More than 64 goals are refused late | Stands. The ranker takes at most three turns' files |
| A refusal of the list's maker does not name the turn | Stands. The list is made before any offered turn, and a refusal stops the pass there |
| The admission's reads have no bound | Stands. Its inputs are the pass's own rooms |
| The clock's listing does not turn replacement objects off | Stands |
| An answer's size | Measured here, for three answers, and reported |
| A walk line's limit | Stands |

## 6. What is built

- **The pass,** beside the item scripts (`v2/probes/items/`): a plan printed and written before anything
  runs; the screen; steps 1 to 5; the stops; a table of the turns. It calls the room's commands as they
  are and the store by a path it is given, whose hash it writes down. Nothing in the room changes.
- **Its tests,** with stand-in workers and a stand-in store: the list is made from the history rooms and
  no other (a room of each other kind beside them, and the list unchanged); a turn of step 5 never
  teaches; the order of arms is the one the rule gives, for a seed worked by hand; each stop stops where
  it says and leaves what was done; an offering arm with no offer file, or one whose block's hash differs
  from the kept one, is refused; a second run into the same directory is refused.

## 7. What it costs

Twenty-seven turns: one thrown away, eight of history, eighteen under the arms. At the two to five
minutes the pilots' turns took, about an hour and a half of one machine, with nothing else heavy on it.
The screen is twenty-six references, about ten minutes.

## 8. What this narrows, said before any turn

- **Three items of one run of work, one worker program, one machine, two rounds.** It is a look, not a
  measurement of an effect.
- **The three items' own earlier turns are not history,** though fifteen of them passed: an item's turns
  teach other items, not itself.
- **The history is eight items chosen by place, and one of them is what the ranker takes.** With another
  eight the blocks would differ.
- **A pass is what the check observed,** as the route spec's section 6 says.
