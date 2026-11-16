# v2: a route, made from many walks, offered to a turn

Serenity, 2026-11-16, revision 3. A change to the design of stage 2
(`docs/superpowers/specs/2026-11-15-v2-stage-2-experiment.md`, "the first design" below), after its pilot
(`docs/reports/2026-11-15-v2-stage-2-pilot.md`) and the repair that followed
(`docs/reports/2026-11-16-v2-tests-that-need-the-room.md`).

A fresh reader of the other family approved revision 1 with seven named changes, and confirmed revision 2
with four more. All eleven are made here; the last section says where. Two things came from the ship
Tardis, which owns the store this rests on, and one from a measurement; that section names them too.

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
| standing | how the room classes the turn now: passed and verified, passed and not verified, or failed. A second look can change it after the verdict, so it is its own field |
| steps | in order of `seq`: the tool, whether it went well, every tracked file the step named in the order named (each a path and its blob at the base), the two times, the token counts |
| changed | the paths the turn's commit changed, in the order recorded, and how: added, changed, removed |

- **A step of an older store** has a file it was aimed at and no list of files named. Its one file is
  written as its list. Nothing is invented for what was not recorded.
- **A named file was tracked at the base.** A changed file may not have been: an added file is in no walk.
- **Nothing is filtered silently.** A failed step and a failed turn are written, marked as such, and stay
  in the files for whoever checks afterwards. Which standing lets a turn teach is the store's rule, said
  there and bound in section 2.

## 2. What the room needs of a route

The room asks: this repository, this history, these files in this order. It needs back, for each file in
the order asked, the route to it from where every turn starts, or the plain answer that there is none.

- **One answer.** The same history and the same question give the same bytes on any machine. Where two
  ways cost the same, a fixed order of their paths decides, not the order files were read in.
- **A measure with a name.** The answer names the measure of cost it used and that measure's version, and
  both are in the list of section 3. For each route it gives the cost under that measure and, apart from
  it, the number of roads. One way is better than another when its cost under the named measure is
  strictly lower. The number of roads is said beside it and decides nothing: under a measure that prices
  a road by how few turns walked it, a longer way along well-worn roads can be the cheaper.
- **Which turns were let teach.** The answer says which standings it counted, and its counts are of those
  turns only. A turn it did not count is still in its file.
- **Counts that mean one thing.** How many of the turns let teach walked a road, each turn counted once
  however often it walked it, and two turns that walked alike counted as two.
- **Where every turn starts is not a file.** A repository may hold a file of any plain name.
- **A route's roads were each walked** by some admitted turn, named with the road.
- **A detour can be looked at.** Where a route is cheaper than the way a turn went to the same file, the
  answer names that turn, how far along its walk the file first came, the way it went and the way offered,
  each with its cost and its number of roads. A way that is not cheaper is not called a detour.
- **Three kinds of no route, told apart:** no turn that was let teach reached the file; no turn named it
  at all, as with a file a turn added; the kernel refused.
- **A refusal is said.** If the kernel refuses a cell, there is no route for that file and the reason is
  given. A network made of what was left is not passed off as whole.

## 3. Which turns may teach

An experiment's network is made from a list, fixed and hashed before any turn that is offered anything:

- each entry names a room, an arrived turn of a history item, its repository and base, its standing as the
  room holds it when the list is made, and the SHA-256 of its walk file; the list also names the measure
  of cost, with its version;
- the room checks each walk file against its own store before any offer is made: the turn is listed, is of
  a history item, arrived, is there once, and has the standing the list gives it; each named path and blob
  is in the tree of the base;
- anything else stops the run and is said: a file not listed, a second copy, another repository's walk, a
  walk marked as a ship's, a file that does not match its hash. Nothing is dropped silently.

No scored item, and no turn at one, is ever on the list. The store's general command may still be given
any walks, to build and try it.

**The list's form,** fixed here because the room writes it and the store reads it. One JSON object, its
keys sorted, no spaces, in UTF-8: `v`, which is 1; `repo`; `measure`, with its `name` and `version`; and
`turns`, sorted by `attempt`, each with `attempt`, `item`, `base`, `standing` and `sha256`, the hash of that
turn's walk file. A walk file on the list holds one walk and no more, so an entry is one file and one
turn. An attempt is on the list once, and is the turn's name wherever a turn is named. The list is of one
repository. Every listed turn's file is given to the store, and no other: one missing changes the count of
turns that taught, and so the price of every road. The list's own SHA-256 is of exactly those bytes.

**A repository's id** is a root commit of it. This repository has three, so "the root" names nothing:
the id is the root that is first in byte order among those the turn's base reaches.

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
  order; the versions of the ranker, the store, its measure of cost, the kernel and the renderer; the
  block's SHA-256 and its length. An arm that offers, with nothing to offer, is recorded as that and not as the arm that offers
  nothing. From what is kept, the block can be made again, byte for byte, for as
  long as the list and the named versions are kept; they are kept with the experiment's records.

## 5. What is compared

| Arm | What the turn is given |
| --- | --- |
| Nothing | Today's prompt |
| Route | The route to each file that the nearest history turns changed, over the whole of the history let teach: the files along each way in order, how many turns walked each road, how many turns went a dearer way, and for each file whether it has changed since or is gone |
| The same places, shuffled | Every different file of the route arm's block, once, with the same mark of changed or gone, in an order drawn by the seeded draw, under the same opening sentence. Nothing of a road: no order, no counts, no dearer ways |

- **The goals.** The first design's ranker, unchanged, picks up to three arrived history turns by shared
  title words. The files asked for are the files those turns changed, in the ranker's order of turns and
  each turn's recorded order, a file named twice kept where it first comes. A score of nought offers
  nothing. The scored item's own answer is never consulted, to find goals or to mend a poor match.
- **Route against nothing compares a package:** this ranker, these goals, this history, this rendering. A
  benefit would not say which part earned it.
- **Route against shuffled is ordered routes with their roads, against the same places with no roads.**
  The places are the same. What differs is everything said of a road: the order along each way, the
  counts, and that a file on the way to two goals is said twice in one arm and once in the other. So the
  two blocks are not of one length, and each turn's block length is reported. A difference between these
  arms is the effect of all of that together, not of order alone.
- **What this cannot decide:** whether a commit message would do as well, or three walks shown whole, or a
  simpler program that made the same block. The first design's notes and walks arms are not run. Either
  comes back, on fresh scored items, if a route shows a benefit.

**The comparisons, and what gates each.** These replace the first design's list, whose arms are gone.

1. Route against nothing, and shuffled against nothing. Each is read by the first design's four readings
   on the wider of its two intervals, at the middle 95%, so that the two together are held to one chance
   in twenty of a false benefit.
2. Route against shuffled, read only if route showed a benefit against nothing.

**The guard, as the first design has it, for each comparison:** the arm that would be shown to benefit is
not read for one if it leaves incomplete an item that the arm it is compared with completes. That is item
by item. Two arms that each finish as many items, but not the same ones, do not pass it.

**The report says two things apart,** so that neither hides the other. This replaces the first design's
table of outcomes.

| Field | What it holds |
| --- | --- |
| Whether to build on a route | Yes only if route shows a benefit against nothing, its figure is 0.85 or less, and it passes the guard. Otherwise which of the four readings it was: a cost shown, a gain of 15% ruled out, nothing shown either way, or a benefit too small. Only the first two close the question |
| What the roads added | Read only when route showed a benefit against nothing. Route shows a benefit against shuffled: ordered routes with their roads did better than the same places with none. It shows none: route helped, and an advantage over the same places shuffled was not established. Shuffled's own reading against nothing is given beside it, whatever it is |

Reported with both: how often an offer was empty, and how often its files were ones the turn went on to
change.

- **Everything else of the first design's part 3 stands:** every item under every arm, the order drawn by a
  seeded draw, an item's runs one after another, the deciding outcome, how uncertainty is worked out, the
  sizing rule, and the reading of all of it by a fresh reader with the pilot's results in hand, before any
  scored turn.

## 6. Where a route could matter, measured

- **In the first pilot there was little to shorten.** Its 21 turns took 244 steps, of which 103 named a
  tracked file. Together they named 16 different files and made 50 roads. A turn of one worker program
  named 1 to 7 files; of the other, 9 to 19. In the 11 turns whose first change shows as a step, about 30
  seconds passed before it, the worker's own thinking included.
- **What that does and does not show.** Files named and the first recorded change are stand-ins. They do
  not measure time spent finding, and they do not show that a route could not have helped there. The
  counts of files and roads are from the pilot's own stores, kept on the lead's machine; the public data
  file holds each step without its files.
- **The idea is about work in which finding is most of the cost.** The first design's items, small repairs
  to one command of three crates, do not look like that. This is a change of the work the experiment is
  about, made for that reason, and not a result of the first pilot.

**So the scored items, and the pilot's, come from the whole repository's waiting work,** taken in the order
it was posted on the project's board, each with a check frozen beforehand by the other family, as the first
design has it. The conclusion is then about that work, and not about work in general. What it costs is
said below.

**The list of items is fixed before any route is looked at and before any measured turn:** the board as it
stood at a stated time; every waiting item in the order posted; each one taken or left out, with the
reason (no check can be frozen for it, it needs a person, it is not work on the repository); and which of
those taken are history and which are scored, kept apart as the first design has them. Written down and
hashed. No item is chosen, left out or reworded for how well a route might serve it.

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
- A turn of each worker is thrown away before its first measured turn, as in the first pilot.
- The same rule gives `n` from the largest of the three spreads, worked before rounding. Over 40 is
  reported as over 40 and not cut to it, and no third pilot follows.
- One turn at each item under each offering arm is run as well. The costs of those six, of the turns thrown
  away and of the six turns of "ready to test" enter no sizing and no reading. Only the fifteen do.

## 8. How we know it is ready

Each row has a case that must pass and a case that must be refused.

| What | Shown by |
| --- | --- |
| A walk file holds what the store holds, and no text | Field by field, on a turn with several files named in one step, a step of an older store, a step of unknown kind, and files added, changed and removed. A marker planted in the turn's output is in no file, store or log |
| A route is a stitching, and the cheapest | Two walks: one from the start to `a.txt`, `b.txt`, `target.txt`; one from the start to `b.txt`, `x.txt`. The route to `target.txt` is the start, `b.txt`, `target.txt`: two roads, walked whole by neither, a detour from the first walk. A small search written apart from the store, given the same measure, agrees, on this and on walks drawn at random |
| Cheaper is by the named measure, not by the number of roads | Three walks: two as the first above, one as the second. Under a measure that prices a road by the share of turns that walked it, the three-road way is now the cheaper, and it is the answer, with its cost, its three roads, and no detour claimed |
| One answer | Two ways that cost the same give the same route on two machines; a road walked twice by one turn counts once |
| A detour is a real one | One kept by the store and read back. Refused: a way no turn went, a road no turn walked, a way that is no shorter, ends that do not meet |
| What is not there is said | Each told from the others: a file no turn let teach reached; a file no turn named, as one a turn added; an empty history; a kernel refusal, with its reason |
| Only listed turns teach | Refused, each by name: an unlisted file, a second copy, another repository's, a ship's, a wrong hash, a path not in the base's tree, a standing other than the list's. A turn that passed and was not verified is in its file and in no count, where only verified turns teach |
| The offer is data, and the prompt without it is unchanged | The pinned prompt test. A tracked file whose name reads as an instruction is rendered inside the block, after its opening sentence, and nowhere else. Route JSON holding a path that is not plain is refused by the renderer itself |
| What a turn was given can be made again | A stand-in worker's received block has the recorded hash and length; the block made again from what the store kept is the same bytes; an empty offer is told from no offer |
| Two machines can run it | The same fixture gives the same route bytes on both, and one turn with a block that is not empty runs on the second |

## What it costs

- **To be ready:** the room's export and offer, the store's reading of walks and its route, the fixture,
  and six turns.
- **The pilot:** three items of the whole repository, each needing its check written and tried by the
  other family, and the repository's own tests running inside a worker's sandbox and the room's jail. From
  a fresh copy, with its environment kept outside the copy, two of its test files pass on the lead's
  machine. Through the room it was tried once and did not start: the interpreter under that environment
  is kept in a directory the room hides from every run, because keys are kept there, and the room refused
  to show it. That refusal is right. An environment has to be made where the room may show it. Then
  fifteen turns, the two thrown away, and six.
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

**The same reader confirmed revision 2 with four more:**

| Named change | Where |
| --- | --- |
| R1. Keep the first design's logic of outcomes: the guard item by item, the four readings, building apart from attribution | Section 5 |
| R2. Say exactly what the shuffled arm changes | Section 5: its row, and "Route against shuffled" |
| R3. Finish what is fixed beforehand: the board's list, the turns thrown away, what enters sizing; and say what the measurement does not show | Sections 6 and 7 |
| R4. Carry across the seam which turns may teach and the measure of cost | Sections 1, 2 and 3, and three rows of section 8 |

**Made plain since, by the lead, as the two sides were built:** the list's form and a repository's id, in
section 3; and that a path is rendered after the block's opening sentence, which is fixed and holds none.

**Changed between the two reads, and confirmed in the second:**

- **The third arm is the same places shuffled,** not three walks shown whole. From Tardis. It holds the
  places fixed. What it changes beside, and that the two blocks are not of one length, is said in section 5.
- **A road's cost and a route's definition move to the store's spec.** From Tardis, whose first proposal
  prices a road by how small a share of verified turns walked it. This spec keeps what the room needs.
- **The items come from the whole repository,** by the measurement in section 6.
- **Ready to test is parted from the pilot,** so that the path can be shown working on what exists before
  the costlier items are made.
