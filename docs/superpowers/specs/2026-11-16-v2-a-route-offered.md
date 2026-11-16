# v2: a route, made from many walks, offered to a turn

Serenity, 2026-11-16, revision 7. A change to the design of stage 2
(`docs/superpowers/specs/2026-11-15-v2-stage-2-experiment.md`, "the first design" below), after its pilot
(`docs/reports/2026-11-15-v2-stage-2-pilot.md`) and the repair that followed
(`docs/reports/2026-11-16-v2-tests-that-need-the-room.md`).

A fresh reader of the other family approved revision 1 with seven named changes, confirmed revision 2
with four more, confirmed revision 4's change of where the items come from with two more, and confirmed
revision 6's change to the reach of one rule with one more. All fourteen are made here; the last section
says where. Two things came from the ship
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
  block's SHA-256 and its length. An arm that offers, with nothing to offer, is recorded as that and not as
  the arm that offers nothing. From what is kept, the block can be made again, byte for byte, for as long
  as the list and the named versions are kept; they are kept with the experiment's records.

## 5. What is compared

| Arm | What the turn is given |
| --- | --- |
| Nothing | Today's prompt |
| Route | The route to each file that the nearest history turns changed, over the whole of the history let teach: the files along each way in order, how many turns walked each road, how many turns went a dearer way, and for each file whether it has changed since or is gone |
| The same places, shuffled | Every different file of the route arm's block, once, with the same mark of changed or gone, in an order drawn by the seeded draw, under the same opening sentence. Nothing of a road: no order, no counts, no dearer ways |

- **The goals.** The first design's ranker picks up to three arrived history turns by shared title words,
  with one narrowing: it ranks only the turns the list lets teach under its measure, where the first
  design ranked every arrived turn. A route can be made only from walks that teach, and a failed turn's
  changed files are not where the work was done. Equal scores go to the turn whose verdict came later, and
  then to the attempt id that is greater in byte order, which is a fixed order and not one of time. The
  files asked for are the files those turns changed, in the ranker's order of turns and each turn's
  recorded order, a file named twice kept where it first comes. A score of nought offers nothing. The
  scored item's own answer is never consulted, to find goals or to mend a poor match.
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

**The project's board could not supply such work.** Read once, on 2026-11-16: 69 items waited on its two
boards. By the lead's own pass about 20 are changes a frozen check could judge inside the room's jail. The
rest are specs, work on a machine, decisions for a person, work that needs a browser, and faults whose
text may not be published before they are fixed. The experiment's floor is 20 scored items with history
items beside them, and each of those 20 would need its check written by hand.

**So the items are made from the repository's own merged work.** A commit of the main branch can be an
item when the first four of these hold, by a program and not by eye. The fifth says which of them are
scored:

1. It is not a merge, and it is reached from a stated last commit and not from a stated first one.
2. It changes test files and source files of one component, and nothing outside that component but
   documents. The first component is the peer, whose tests are the ones shown to run in the room.
3. At most three test files and five source files; Python only; no test file that needs a browser.
4. With its test files laid over its parent, those tests fail. On the commit itself they pass. Both inside
   the room's jail, within the check's limit.
5. Among the scored items no two name one test file, and among the pilot's three. Which of two is kept is
   said below, under "The scored, the pilot's and history". History items are not held to this.

**Earlier, exactly.** The commits are put in one order, the same on any machine and however they are read
out: a commit comes after every commit it descends from; among commits free to come next, the one with
the earlier committer time comes first, and at one time, the one whose id is first in byte order.

Measured on 2026-11-16 by the first three rules: 257 such commits for the peer since October. Of 30 spread
over the whole period, 23 met the fourth. Of the seven that did not, the tests of two passed before the
change, and the tests of five failed on the commit itself, in the environment made on the lead's machine.
The two runs together took 10 seconds at the median and 105 at the most. That is not yet a count of items:
the list, when made, says how many the rules leave, and what each left out.

**Why rule 5 holds among the scored, and not between history and scored.** Revision 5 held every item to
it. Measured, the project's work comes in runs: of those commits, 108 name a test file that the one just
before also names. Held over every item, the rule left 64 of the 257, and by its making no scored item's
tests had been visited by any history item. The idea under test is that ways worn by use shorten later work
in the same places. A history from which every earlier visit to a scored item's tests has been taken out
holds nothing of that. So history is every commit that can be an item, runs and all, as the project's work
went.

Among the scored the rule stays, so that one feature's run of commits is not a large part of the scored
items: of the last 40 such commits, 10 name one test file.

**What the lead looked at before choosing this.** From titles alone, with no turn run, by the first three
rules only, and with the files each commit itself changed standing in for goals. Under revision 5's rule
the ranker found a history item for 8 of the last 20 commits, and for 3 of the 20 a chosen history commit
had changed a file that the scored commit also changed. With the rule among the scored only, and the 80
commits before the pilot's as history: 13 of 20, and 10 of 20. With 40 commits as history: 4 of 20, and 2.
So the figures are small and unsteady. This is a rule chosen knowing roughly how it bears on what a route
could find. It rests on the reasoning above and not on the figures, which are here so that a reader can
weigh the choice. That does not make it a blind choice: it was made with these stand-ins, drawn from the
commits' own answers, in view. No commit is taken or left out by them.

**Disjoint in their test files among the scored, and no more than that.** Rule 5 keeps two scored items
from naming one test file. It does not keep two items from coming from one fault or one feature, mended in
two places with two test files. The first design said no two items come from one fault. That is not claimed
here. Whether items are related, and what that does to the sizing and to the intervals, is for the reader
of the scored design to judge from the list and the history, before any scored turn.

**What such an item is.**

- **Its base** is the commit's parent with the commit's test files laid over it, made as one commit whose
  only parent is that parent, with one fixed message that says nothing of the fix, and a fixed name and
  time, so that the same item has the same base on any machine.
- **Its title** names those test files and asks that they be made to pass by changing the component's
  code, and not the tests. It is the same sentence for every item. It never holds the commit's own first
  line, which says what the fix was.
- **Its check** runs those test files, and is one program for every item, made by the item-maker and not
  by hand. It fails a turn that:
  - changed anything outside the component's source directory. So not the tests, not a helper the tests
    use, not the tests' configuration, and not another component. It is the whole source directory that
    may change, never a list of the files the fix touched, which would say where the answer is;
  - did not run the tests that the reference ran: the check holds how many tests passed and how many were
    skipped on the reference, and a run with fewer passed or more skipped is not a pass, though it ends
    well.
- **Its wrong commit** is the base with one unrelated file added. That shows the check is red on a change
  that fixes nothing. It does not show the tests would catch a clever wrong fix; they are the tests the
  project itself took. A pass here means: the protected tests pass. Nothing more is to be read into it.
- **Its reference** is the commit's own source changes over the base, shown to pass before the item is
  listed. No turn sees it: a sandbox holds only what its base reaches.

**The scored, the pilot's and history, by that order.** One commit that can be an item divides them: the
last that is not scored.

- **Scored.** Going forward from the first such commit after the dividing one, each is scored unless it
  names a test file that a scored commit before it names: of two, the earlier is kept. The dividing commit
  is the latest for which at least forty are found so, forty being the most the sizing rule allows. The
  scored are the first `n` of them.
- **The pilot's three.** Going back from the dividing commit, itself included, each is the pilot's unless
  it names a test file that one already taken names: so here, of two, the later is kept, where among the
  scored it is the earlier. The first three so found are the pilot's.
- **History.** Every commit that can be an item before the earliest of the pilot's three.
- A commit passed over in either scan is listed as left out by rule 5. If forty scored, or three for the
  pilot, cannot be found, no list is made, and that is said.

So no turn is ever offered a way learned from a change made after its own. How many history items are run,
the nearest first, is fixed with the scored design, by its reader, with the pilot's results in hand, with
the limits on attempts and on cost, and with the reason written down. It is fixed before any scored turn is
offered anything, and no scored result changes it.

**What this narrows, said before any turn.**

- **The tests are in the sandbox, and they point at the code.** This is the work of making failing tests
  pass. There is less to find than when work begins from a report of a fault.
- **Every turn is a turn of one worker program.** The tests were written by ships of one model family, and
  the room gives an item only to a worker of another. So the network is made of one program's walks, many
  times over, and not of two programs' together.
- **One component of one repository.** The conclusion is about that work.
- **It is work already done once, and chosen by knowing its answer.** A commit is taken because its tests
  go from failing to passing, which is known only from the fix. That is how a set of past work is made, and
  it is not a choice by how well a route might serve. The fix is in the project's public history after the
  base. A worker has no network and its sandbox no later commit. So the conclusion is about small merged
  Python changes of one component, done again, and not about the project's waiting work.

**The list of items is fixed before any route is looked at and before any measured turn:** the first and
last commits; every commit that met rules 1 to 3, in order; for each, whether rule 4 left it out, and
why, and whether it is history, the pilot's, scored, or left out by rule 5; how many of each; and the
dividing commit. Written down and hashed. No item is chosen, left out or reworded for how well a route
might serve it.

**The item-maker is in the repository, with tests of its own.** They show, on a small repository made for
the purpose: the same list whatever order the commits are read out in, and with two commits at one time;
the dividing commit found; a later scored commit left out for naming an earlier one's test file, while a
history commit that names it stays; the pilot's three found going back, the dividing commit among them and
the later of two kept; too few for the scored or for the pilot, refused; a base with one parent and the
fixed message; a reference that passes; and the check failing each of these, by name: the base, the wrong
commit, a turn that changed a test file, one that changed a helper the tests use, one that changed the
tests' configuration, and one that made the tests be skipped.

**For the reader of the scored design, beside the pilot's results:** how often the ranker finds a history
turn at all. Every title is one sentence with test files' names in it, and the ranker drops a word that
most titles hold. So a scored item whose test file's name shares no word with a history item's is offered
nothing. The scores and the goals reached are reported as they fall. No item is renamed or left out to
make a match, and an experiment in which most offers are empty is reported as that, and not as a test of
routes.

## 7. Ready to test, and the one pilot

**Ready to test** is the path shown working, and decides nothing:

- the fixture of section 8, where the answer is known beforehand;
- six live turns: each of the first run's three items, once under each offering arm, its history the
  arrived turns at the other two. Those items stand on a commit from before the repair, and a walk from an
  older store is the kind section 1 writes out as it was recorded. If the ranker offers one of them
  nothing, that is reported, and the fixture is still the proof that a route reaches a prompt.

**The pilot, once.** Before its first turn a list is fixed and hashed: the three items, by the rule of
section 6; each one's base; each check, with the commit it fails on and the one it passes on; the room
program, built from a commit that holds the repair; the worker program, its model and version; the
environment the tests run in, by the hash of its lock file; the limits; the seeds; the order of the
fifteen turns; and whether a turn has a first line of its own.

- Five rounds with nothing offered. All fifteen turns are reported, and the first pilot's rules for a turn
  that is lost or an instrument that fails still stop it.
- A turn of each worker is thrown away before its first measured turn, as in the first pilot.
- The same rule gives `n` from the largest of the three spreads, worked before rounding. Over 40 is
  reported as over 40 and not cut to it, and no third pilot follows.
- Nothing is offered in the pilot. Its items have no history yet: the turns that would teach are the ones
  it is about to run. The path from walks to a prompt is shown by "ready to test" above. The costs of the
  turn thrown away and of the six turns of "ready to test" enter no sizing and no reading. Only the
  fifteen do.

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
- **The pilot:** the program that makes items from merged commits, with its tests; three items; fifteen
  turns and one thrown away. No check is written by hand.
- **The repository's tests in the room,** tried on the lead's machine. The first try did not start: the
  interpreter under the project's test environment is kept in a directory the room hides from every run,
  because keys are kept there, and the room refused to show it. That refusal is right. With an
  environment made where the room may show it, a worker inside its sandbox ran two of the peer's test
  files (64 tests, 6 seconds), and a check that runs them passed inside the room's jail (7 seconds).
- **The scored experiment:** as the first design says, three arms for each of `n` items, and a run with
  nothing offered for each history item. The items cost machine time to make and no builder's.

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
| R3. Finish what is fixed beforehand: the list of items, the turns thrown away, what enters sizing; and say what the measurement does not show | Sections 6 and 7 |
| R4. Carry across the seam which turns may teach and the measure of cost | Sections 1, 2 and 3, and three rows of section 8 |

**Changed in revision 4: where the items come from.** Revision 3 took them from the project's board.
Section 6 now takes them from merged commits, each made into failing tests to be made to pass, with history
and scored divided by order, and the pilot offers nothing. The reasons, each measured, are in section 6.
The same reader confirmed it with two named changes, both made in revision 5:

| Named change | Where |
| --- | --- |
| S1. Say exactly what order the commits are in and what a base descends from, and that items disjoint in their test files are not shown to come from different faults | Section 6: "Earlier, exactly", "Disjoint in their test files", "Its base" |
| S2. Protect the whole of the tests' machinery and not only the chosen test files, and do not take a run that skipped the tests for a pass | Section 6: "Its check", and the item-maker's own tests |

It also asked that the reader of the scored design be shown how often the ranker offers anything at all
under these titles. That is in section 6's last paragraph.

**Changed in revision 6: the reach of rule 5.** Revision 5 let no two items name one test file. Revision 6
holds only the scored items to that, and the pilot's three, and makes history every commit that can be an
item. The reason and what was measured are in section 6, under "Why rule 5 holds among the scored". The
same reader confirmed it with one named change, made in revision 7:

| Named change | Where |
| --- | --- |
| T1. Say which commit the split falls on, which way each scan goes and which of two commits it keeps, and what happens when the pilot's three cannot be found | Section 6: "The scored, the pilot's and history", and the item-maker's own tests |

It also held that the choice of this rule, made with stand-ins drawn from the commits' own answers in
view, is an exploratory choice and not a blind one, and that the number of history items, once fixed, is
not to be moved by a scored result. Both are now said in section 6.

**Made plain since, by the lead, as the two sides were built:** the list's form and a repository's id, in
section 3; and that a path is rendered after the block's opening sentence, which is fixed and holds none.

**Changed between the two reads, and confirmed in the second:**

- **The third arm is the same places shuffled,** not three walks shown whole. From Tardis. It holds the
  places fixed. What it changes beside, and that the two blocks are not of one length, is said in section 5.
- **A road's cost and a route's definition move to the store's spec.** From Tardis, whose first proposal
  prices a road by how small a share of verified turns walked it. This spec keeps what the room needs.
- **The items come from the whole repository,** by the measurement in section 6. (Revision 3 took them
  from the board; revision 4, from merged commits.)
- **Ready to test is parted from the pilot,** so that the path can be shown working on what exists before
  the costlier items are made.
