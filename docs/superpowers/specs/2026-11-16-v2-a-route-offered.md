# v2: a route, made from many walks, offered to a turn

Serenity, 2026-11-16, revision 2. A change to the design of stage 2
(`docs/superpowers/specs/2026-11-15-v2-stage-2-experiment.md`, "the first design" below), after its pilot
(`docs/reports/2026-11-15-v2-stage-2-pilot.md`) and the repair that followed
(`docs/reports/2026-11-16-v2-tests-that-need-the-room.md`).

A fresh reader of the other family approved revision 1 with seven named changes. All seven are made here;
the last section says where. Two things came from the ship Tardis, which owns the store this rests on, and
one from a measurement; that section names them too, and the same reader reads them.

## Why the design changes

The pilot said the experiment as designed was not affordable, and the first design says what follows: the
design changes, and a changed design gets one pilot of its own. Two things change.

- **The noise it found has had its likely cause removed.** A worker's own test run took eight minutes and
  could wait ten; it now takes under a minute. Whether that was the cause is for the new pilot to show.
- **The person whose project this is asked for the whole of his idea to be made testable,** and the part
  the first design put off is the part it rests on. His idea, in his words: the paths a worker took to find
  what it needed become, with use, "a road network. One that you can A* around", so that it rides "your own
  rails" where it would walk; and many agents' paths together make a better map than one. The first design
  offered a turn other turns' walks as they were, and left "stitched routes" to a fourth arm that would run
  only if walks had already won. So the claim about the network would not have been tried unless a weaker
  one succeeded first.

## Two specs, one seam

The road network is kept on the n-category store, on a kernel the ship Tardis wrote. **How walks become
cells, what a road costs, what a detour is and how a route is found are the store's, and its owner writes
that spec,** to be read by a fresh reader of its own. This spec is the room's side and the experiment's:
what the room writes, what it needs back, what a turn may be shown, and what is compared. "What the room
needs of a route" below is the seam, and is fixed here.

## What is asked

1. **A walk as a file,** that the room writes.
2. **A route back from the store,** with what shows that it is a rewriting of ways really gone.
3. **The room offers a turn a route,** as a block in its prompt, and records how the block was made.
4. **Arms for it from the start,** and one pilot of the changed design, fixed beforehand.

## Not asked

- **Frames.** Choosing how to look at a problem is a layer above this one. So the goals of a route here
  are chosen by the first design's plain ranker of title words, and by no judgement of what a problem is like.
- **The estimate.** The project's earlier vision of the rail has a search steered by an estimate that never
  overshoots, with a goal given in words. That needs a model in the loop. Here a goal is a named file and
  the search has no estimate; it is the same search with its estimate at nothing.
- **Lighthouses across machines.** Turns of two worker programs, on one or two machines, are merged. Names
  that mean the same on different machines are not.
- **Walks the room did not make.** A ship's own record of the files it named is a walk too, and there are
  hundreds on the lead's machine. They may be used to build and try the store. None enters an experiment.
- **Notes, and walks as they were.** See "What is compared".
- **Any text of a turn.** Rule 9 stands.

## 1. A walk as a file

`yak item walks <item> --json` writes one line for each arrived turn of the item, in the store's format.
What the room puts in, whatever the format's names for them:

| Field | What |
| --- | --- |
| the format's number | so that a later one is told apart |
| repository, `base` | the commit the turn's sandbox was made from |
| `item`, `attempt`, the worker's family | as the room names them; no worker's own name |
| verdict | whether the turn's commit passed its frozen check |
| steps | in order of `seq`: the tool, whether it went well, every tracked file the step named in the order named (each a path and its blob at the base), the two times, the token counts |
| changed | the paths the turn's commit changed, in the order recorded, and how: added, changed, removed |

- **A step of an older store** has a file it was aimed at and no list of files named. Its one file is
  written as its list. Nothing is invented for what was not recorded.
- **A named file was tracked at the base.** A changed file may not have been: an added file is in no walk.
- **Nothing is filtered silently.** A failed step and a failed turn are written, marked as such. Whether a
  failed turn's roads count is the store's rule, said there.

## 2. What the room needs of a route

The room asks: this repository, this history, these files in this order. It needs back, for each file, the
route to it from where every turn starts, or the plain answer that no walk reached it.

- **One answer.** The same history and the same question give the same bytes on any machine. Where two
  ways cost the same, a fixed order of their paths decides, not the order files were read in.
- **Counts that mean one thing.** How many of the admitted turns walked a road, each turn counted once
  however often it walked it, and two turns that walked alike counted as two.
- **Where every turn starts is not a file.** A repository may hold a file of any plain name.
- **A route's roads were each walked** by some admitted turn, named with the road.
- **A detour can be looked at.** Where a route is shorter than the way a turn went to the same file, the
  answer names that turn, how far along its walk the file first came, the way it went and the way offered.
  A way that is no shorter is not called a shortening.
- **A refusal is said.** If the kernel refuses a cell, there is no route for that file and the reason is
  given. A network made of what was left is not passed off as whole.

## 3. Which turns may teach

An experiment's network is made from a list, fixed and hashed before any turn that is offered anything:

- each entry names a room, an arrived turn of a history item, its repository and base, and the SHA-256 of
  its walk file;
- the room checks each walk file against its own store before any offer is made: the turn is listed, is of
  a history item, arrived, and is there once; each named path and blob is in the tree of the base;
- anything else stops the run and is said: a file not listed, a second copy, another repository's walk, a
  walk marked as a ship's, a file that does not match its hash. Nothing is dropped silently.

No scored item, and no turn at one, is ever on the list. The store's general command may still be given
any walks, to build and try it.

## 4. The offer

- **`yak clock run --offer <file>`** gives every turn of that clock one block of text, after the prompt's
  first lines and before the rules.
- **The block says what it is.** It opens with a fixed sentence: what follows is what earlier turns at
  other work were seen to do, a suggestion; the paths in it are data, and nothing in it changes the task
  or the rules. The prompt already says this of files, tool output and fetched pages; a path the room
  itself puts in the prompt is given the same standing.
- **Only typed fields are rendered:** a path that passes the test a walk's path passes and was tracked at
  its base; a count; a mark that a file has changed since or is gone. No string is copied from the route's
  JSON as it stands, and no name is turned into a file's contents.
- **Support is said per road.** A stitched route was walked whole by nobody, and the block does not say
  otherwise.
- **Without `--offer` the prompt is byte for byte what it is today,** and the test that pins it holds.
- **The block is made before the worker starts, and a later turn of the same run is given the same.**
- **The store keeps how the block was made, not the block:** the arm; the order and the seed of the draw;
  the hash of the list in section 3; the turns the ranker chose and their scores; the files asked for, in
  order; the versions of the ranker, the store, the kernel and the renderer; the block's SHA-256 and its
  length. An arm that offers, with nothing to offer, is recorded as that and not as the arm that offers
  nothing. From what is kept, the block can be made again, byte for byte.

## 5. What is compared

| Arm | What the turn is given |
| --- | --- |
| Nothing | Today's prompt |
| Route | The route to the files that the nearest history turns changed, over the whole of the admitted history |
| The same files, shuffled | The files of that route, each once, in an order drawn by the seeded draw, with the same opening sentence and no counts |

- **The goals.** The first design's ranker, unchanged, picks up to three arrived history turns by shared
  title words. The files asked for are the files those turns changed, in the ranker's order of turns and
  each turn's recorded order, a file named twice kept where it first comes. A score of nought offers
  nothing. The scored item's own answer is never consulted, to find goals or to mend a poor match.
- **Route against nothing compares a package:** this ranker, these goals, this history, this rendering. A
  benefit would not say which part earned it.
- **Route against shuffled holds the files fixed and changes one thing,** their order and what is said of
  each road. It is read only if route showed a benefit against nothing. It is the comparison that bears on
  whether the roads matter or only the list.
- **What this cannot decide:** whether a commit message would do as well, or three walks shown whole. The
  first design's notes and walks arms are not run. Either comes back, on fresh scored items, if a route
  shows a benefit.
- **The first design's table of outcomes is replaced by this one:**

| Outcome | What it means |
| --- | --- |
| Route shows a benefit against nothing, with a figure of 0.85 or less, and finished its work as often | Worth building on. The next question is against notes |
| Route shows a benefit against nothing, and none against shuffled | The list of files helped. The roads are not shown to |
| Route shows a benefit against both | The order helped as well. Still a package: this network, these items |
| No benefit shown against nothing | Not ruled out. Reported with how often an offer was empty and how often its files were ones the turn went on to change |

- **Everything else of the first design's part 3 stands:** every item under every arm, the order drawn by a
  seeded draw, an item's runs one after another, the deciding outcome, the guard that an arm must finish
  the work to win, the four readings, the sizing rule, and the reading of all of it by a fresh reader with
  the pilot's results in hand, before any scored turn.

## 6. Where a route could matter, measured

- **In the first pilot there was little to shorten.** Its 21 turns took 244 steps, of which 103 named a
  tracked file. Together they named 16 different files and made 50 roads. A turn of one worker program
  named 1 to 7 files; of the other, 9 to 19. In the 11 turns whose first change shows as a step, about 30
  seconds passed before it, the worker's own thinking included.
- **The idea is about work in which finding is most of the cost.** The first design's items, small repairs
  to one command of three crates, are not that. A route offered there would most likely show no benefit,
  and that would say little about roads.

**So the scored items, and the pilot's, come from the whole repository's waiting work,** taken in the order
it was posted on the project's board, each with a check frozen beforehand by the other family, as the first
design has it. No item is chosen, left out or reworded for how well a route might serve it. The conclusion
is then about that work, and not about work in general. What it costs is said below.

## 7. Ready to test, and the one pilot

**Ready to test** is the path shown working, and decides nothing:

- the fixture of section 8, where the answer is known beforehand;
- six live turns: each of the first run's three items, once under each offering arm, its history the
  arrived turns at the other two. Those items stand on a commit from before the repair, and a walk from an
  older store is the kind section 1 writes out as it was recorded. If the ranker offers one of them
  nothing, that is reported, and the fixture is still the proof that a route reaches a prompt.

**The pilot, once.** Before its first turn a list is fixed and hashed: the three items, in the order they
were posted; each one's base, which holds the repair; each check, with the commit it fails on and the one
it passes on; the worker programs, their models and versions; the limits; the seeds; the order of the
fifteen turns; whether a turn has a first line of its own; and the list of section 3.

- Five rounds with nothing offered. All fifteen turns are reported, and the first pilot's rules for a turn
  that is lost or an instrument that fails still stop it.
- The same rule gives `n` from the largest of the three spreads, worked before rounding. Over 40 is
  reported as over 40 and not cut to it, and no third pilot follows.
- One turn at each item under each offering arm is run as well. Their costs enter no sizing and no reading.

## 8. How we know it is ready

Each row has a case that must pass and a case that must be refused.

| What | Shown by |
| --- | --- |
| A walk file holds what the store holds, and no text | Field by field, on a turn with several files named in one step, a step of an older store, a step of unknown kind, and files added, changed and removed. A marker planted in the turn's output is in no file, store or log |
| A route is a stitching, and the cheapest | Two walks: one from the start to `a.txt`, `b.txt`, `target.txt`; one from the start to `b.txt`, `x.txt`. The route to `target.txt` is the start, `b.txt`, `target.txt`: two roads, walked whole by neither, shortening the first walk by one. A small search written apart from the store agrees, on this and on walks drawn at random |
| One answer | Two ways that cost the same give the same route on two machines; a road walked twice by one turn counts once |
| A detour is a real one | One kept by the store and read back. Refused: a way no turn went, a road no turn walked, a way that is no shorter, ends that do not meet |
| What is not there is said | A file no walk reached, a file added by a turn, an empty history: no route, said. A kernel refusal: no route, with its reason |
| Only listed turns teach | Refused, each by name: an unlisted file, a second copy, another repository's, a ship's, a wrong hash, a path not in the base's tree |
| The offer is data, and the prompt without it is unchanged | The pinned prompt test. A tracked file whose name reads as an instruction is rendered inside the block's opening sentence and nowhere else. Route JSON holding a path that is not plain is refused by the renderer itself |
| What a turn was given can be made again | A stand-in worker's received block has the recorded hash and length; the block made again from what the store kept is the same bytes; an empty offer is told from no offer |
| Two machines can run it | The same fixture gives the same route bytes on both, and one turn with a block that is not empty runs on the second |

## What it costs

- **To be ready:** the room's export and offer, the store's reading of walks and its route, the fixture,
  and six turns.
- **The pilot:** three items of the whole repository, each needing its check written and tried by the
  other family, and the repository's own tests running inside a worker's sandbox and the room's jail. From
  a fresh copy, with its environment kept outside the copy, two of its test files pass on the lead's
  machine; inside a sandbox is not yet tried. Then fifteen turns and six.
- **The scored experiment:** as the first design says, three arms for each of `n` items, with a check to
  write for every history and scored item. At the whole repository's size that is days of builders' work
  before the first scored turn.

## What is left to the builders

The block's exact words after its opening sentence; the names of the new flags; how the room checks a walk
file against its store. Sections 1 to 5 and the rows of section 8 are fixed here.

## What the first reader named, and where it is answered

| Named change | Where |
| --- | --- |
| C1. Say that packages are compared, and replace the old table of outcomes | Section 5 |
| C2. Mark offered paths as data | Section 4, and its row in section 8 |
| C3. Fix the pilot's whole list beforehand | Section 7 |
| C4. Finish the definition of a route | The store's spec; what the room needs is in sections 1 and 2 |
| C5. Keep how an offer was made, so that it can be made again | Section 4 |
| C6. Enforce which turns may teach | Section 3 |
| C7. Check a detour's witnesses, and test a route that is stitched | Section 2, and the second and fourth rows of section 8 |

**Changed since that read, and so read again:**

- **The third arm is the same files shuffled,** not three walks shown whole. From Tardis. It is the same
  length as the route, so cost is not mixed into the comparison, and it holds the offered files fixed,
  which the reader said a claim about roads would need.
- **A road's cost and a route's definition move to the store's spec.** From Tardis, whose first proposal
  costs a road by how small a share of passing turns walked it. This spec keeps what the room needs.
- **The items come from the whole repository,** by the measurement in section 6.
- **Ready to test is parted from the pilot,** so that the path can be shown working on what exists before
  the costlier items are made.
