# v2 stage 2: the experiment, written down before it runs

Serenity, 2026-11-15. **Draft 3.** It fills in section 12 of `2026-11-14-superyak-v2-design.md` ("Stage 2,
written down before it runs") with what stage 1's first run measured. Nothing here is built.

Two readers of the other model family have read it. The first read draft 1 cold: approve with named changes,
for building the instrument (part 0) and running the pilot (part 1) only, with nine findings. The second read
draft 2 against those nine: five made as named, four partly, and four changes of its own, two of them to be
settled before anything is built. Draft 3 makes those four. The last two sections say which change answers
which. Draft 3 itself has not been read.

## Two words

- **A turn** is one launch of a worker on an item. It is what stage 1 calls a turn.
- **A run** is one item under one arm: up to three turns, as stage 1 runs an item. Part 3 compares runs.

The pilot of part 1 counts turns: fifteen launches, each kept whether it passed or not.

## The question

**Does offering a turn something recorded from earlier turns shorten its work?** This is the spec's claim B.

**What "nothing" means here.** A turn that is offered nothing still has the repository, with its history: it
can read every earlier commit and its message with git. So this experiment asks what an *offer* adds beyond
what a worker can already find. It does not compare against a worker that has no past to read.

**What a result can and cannot say.** A benefit that is not shown is not a benefit ruled out. The readings
below keep those apart. The spec says stage 2 can end the rail. This document keeps that open, as a decision
about what to build next, and not as a finding that nothing recorded can help.

## What stage 1's record says first

The first run with model workers (`docs/reports/2026-11-15-v2-stage-1-run.md`) kept seven turns: four
rehearsals and three real. Four things in that record shape this experiment.

**1. The walks the room keeps are mostly blanks.** Of the 32 steps of the three real turns, 22 are recorded as
"shell, outside": a command ran, and the room does not know which files it named.

| Turn | Steps | Before its first change | After its last change | Steps with a file's name |
| --- | ---: | ---: | ---: | ---: |
| 1, claude:opus | 9 | 8 | 0 | 3 |
| 2, codex:gpt-6.1-sol | 10 | 3 | 5 | 3 |
| 3, claude:opus | 13 | 5 | 6 | 3 |

- A shell step is given a file only when its command names exactly one tracked file.
- A change made by a shell command is not recorded as a change. Turn 1 has no edit step at all.
- So an arm that handed a later turn one of these walks would test the instrument and not the idea.

**2. What finding costs is not established.** By steps, 16 of 32 came before a turn's first recorded change,
and 11 of 32 after its last. "Before the first change" is not the same as finding, least of all for turn 1,
whose change was a shell command at its last step. Draft 1 read this table backwards and drew a conclusion
about the spec's claim A from it. It supports none.

**3. The room does not hold a turn's whole cost.** It sums what a worker's tool-bearing messages report. A
captured stream in the repository shows 18,291 tokens by that sum, against 37,220 in the program's own
closing total. For Codex it holds nothing at all. No step carries a time.

**4. The room failed a correct turn about once in a hundred,** when something was still tidying the turn's
clone as the room inspected it. That is fixed (45ce58b0). It would have counted against whichever arm it
struck.

## The order of work

Four parts. A later part does not start until the one before it has said what it found.

| Part | What it settles | The experiment stops here if |
| --- | --- | --- |
| 0. The instrument | What a turn's record holds, and that turns cannot teach each other | A turn's whole cost cannot be had for every way a turn can end, by tokens or by time |
| 1. The pilot | That the instrument works on live turns, and a first look at how identical turns differ | The instrument loses turns or costs on live turns |
| 2. The items | The work, its checks, and what an arm may retrieve | Too few items can be given honest checks |
| 3. The experiment | Whether an offer shows a benefit | It ends by its own rule, below |

**The reader's verdict covers parts 0 and 1.** Parts 2 and 3 as written here are a plan. They are read again,
by a fresh reader, with part 1's numbers in hand, before any scored turn runs.

## Part 0. The instrument

Everything here stays inside rule 9: names of tracked files at a commit, numbers and verdicts. No text of a
turn is kept.

**Turns that cannot teach each other.** Today a sandbox is cloned from the item's repository, and the clock
brings each returned commit into that same repository. A second turn at the same item can therefore hold the
first one's answer as an object.

- Every turn is cloned from its own copy of the item's source, made fresh from one frozen set of objects:
  the base, the wrong commits, and what they reach. Nothing else. This holds for a run's second and third
  turns as much as for another arm's.
- Returned commits go to a repository that no later turn is cloned from.
- Before a turn starts, its source copy is shown to hold no earlier answer and no reference fix, by object
  id, beside a control object that has to be there. The answers of stage 1's own run are among those shown
  absent.
- Within a block of turns that will be compared, the worker's program and model, the rules, the check and
  the limits do not change, and their versions are recorded.

**A turn's whole cost.**

- **Tokens:** what the worker's program reports at the end for the whole turn, not a sum over steps. For
  Claude that is the closing total: fresh input, cache writes, cache reads and output, each once. For Codex it
  is the turn's own total, once part 0 has established which of its fields are totals and which are parts of
  another, so that nothing is added twice. The parts are kept, with where each came from.
- **A cost that is missing is never zero.** A killed or crashed program may give no closing total. Each
  turn's record says whether its token cost is complete, and it says so from what the program reported: a
  turn that timed out after giving a whole total is complete.
- **Active seconds,** measured on a clock that does not jump. A turn's active seconds run from the moment the
  room starts making its sandbox to the moment its verdict is recorded. They hold the worker's whole run, the
  room's commit on a worker's behalf, bringing the commit in, and the check. A second look at a pass is timed
  and kept beside them, not in them: it is the room's sampling, not the turn's work. Time between turns, and
  time waiting on the day's ceiling, is in no turn. A turn with no check, because it handed in nothing, ends
  when that is recorded.
- Each step also keeps when its call was seen and when its result came.

**What a record is tied to.** Enough to put a run's cost back together from its turns, and to say what was
compared with what: the item, its source copy, base and check; the worker, its program's version, the model,
the rules and the limits; the arm, the seed and the order; the run and which of its turns this is; what was
offered; the commit handed in; how the turn ended and its verdict; the token parts and whether they are
complete; the durations. A run's cost is the sum over its turns.

**What a turn touched.**

- A shell step records every tracked file its command names, in the order named. It says "named in a
  command", not "read". The room cannot tell which, and a search over a directory names nothing.
- A turn's record says which tracked files its commit added, changed or removed, taken from the
  difference between the base and the commit. This covers a change made by a shell command.
- What cannot be named is recorded as unknown. How much of each turn is unknown is measured and reported.
  Nobody promises that every file a turn touched has a name in its record.

**What a turn was given.** Its arm, the order it ran in, and what it was offered: the ids of the walks or
commits offered, the version and hash of the ranker and of the renderer that made the text, the text's
length, and its hash. A hash alone is not a recipe, so the ranker and renderer are deterministic and pinned,
and an offer can be made again from what is kept. The text itself is not kept.

**A prompt of its own.** Two turns given the same prompt share its opening words, and a worker's program
keeps what it has lately been sent. Within that memory's life the second turn reads the first one's: it is
cheaper and faster, and the order turns ran in leaks into what they cost. So a turn's prompt can be made to
begin with a line that is that turn's alone. The pilot and the experiment run with it on. Reads from that
memory are kept apart from fresh input in a turn's tokens, never added to it as equals.

**A worker that cannot commit can still say what it did.** The room commits for Codex with a fixed message
today. A worker may leave its message in one untracked file. The room uses it as the commit's message and
removes the file before the commit is made, so the file is never part of what is checked.

**Where rule 9's line falls for notes.** The store keeps commit ids and a hash. Commit messages live in the
repository, where they already are. The rendered offer, the message file and the full prompt are not kept in
any store, log or cache of the room's.

**How we know part 0 is done.** The cases below are fixed before any live replay. Each is shown with
captured streams or scripts for both workers' programs. The three live replays of the stage 1 items come
after, as a smoke test: they are not expected to produce the rare cases by themselves.

| Case | What must hold |
| --- | --- |
| A turn that ends normally | Its token total equals the program's own closing total, with a message that arrives twice counted once |
| A turn with no tool call | It has a record, with a cost |
| A turn that fails its check, one that hands in nothing | Each has a record with a cost and its durations |
| A turn that times out, one whose program crashes, one that is killed | Each has a record. Its token cost is marked complete or incomplete by what the program reported. Its active seconds are whole either way |
| A command naming several files | All are recorded, in order. A command that names none is recorded as unknown, not left out |
| Files added, changed and removed | Taken from the difference between base and commit, a change made by a shell command among them |
| Durations | Never negative, across every case above; a turn's parts add up to its active seconds; a run's cost is rebuilt from its turns |
| An offer | Made again from what is kept, it has the same ids, length and hash |
| The record's ties | Everything under "What a record is tied to" is written and read back |
| No text of a turn | None in the store, or in any log or cache of the room's. The message file is not in the committed tree: it is gone before the commit is made |
| Two turns at one item | Shown not to share an answer, with the control present |
| Two turns given the same item | Their prompts differ from the first line, and neither turn's line is kept in the store |

**Tokens or seconds: decided by the table, before the pilot.** Tokens are the deciding outcome only if every
row above that speaks of a token cost shows a complete total: the normal turn, the turn with no tool call, the
failures, the timeout, the crash and the kill, for both programs. If any does not, the deciding outcome is
active seconds. If active seconds cannot be shown whole for every row either, the experiment stops at part 0.

- **Measured before the build, once for each program (2026-11-15).** Ended by TERM in the middle of a shell
  command, the way the room ends a turn at its limit, neither program writes its closing total. Claude exits
  with 143 and Codex with 0. So unless part 0's cases find a whole total some other way, seconds decide. A
  first try at this measured nothing: Claude's own harness refused a bare `sleep`, ran it in the background
  and finished its turn, so the program that was ended had already closed its books.
- The choice, the version of the instrument and the evidence are published before the first pilot turn.
- After that it does not change. A deciding cost that turns out incomplete in the pilot or the experiment is
  an instrument failure and stops the work. It is not an occasion to change the outcome.

## Part 1. The pilot

**What it is for.** To show the instrument working on live turns, and to give a first look at how much the
same turn differs from itself. It is a pilot. Its numbers do not by themselves fix the size of part 3.

- **What is run:** each of the three items of the first run, five times, with nothing offered, each turn
  from its own source copy, by the worker that may take it. Fifteen turns, each one launch, each kept whether
  it passed or not, plus the three replays of part 0.
- **What is read:** for each item and worker, the spread of the deciding outcome across its five turns, as a
  standard deviation of the logarithm. All three are kept and reported, with the worker beside each.
- **Each turn's prompt begins with its own line,** as part 0 provides. Without it the later of five identical
  turns would be cheaper and faster than the first, and the spread would measure a program's memory.
- **An item's five turns are spread out,** not run back to back: one of each item, then round again. What an
  hour does to a model's speed then falls on every item alike.
- **What it cannot say:** how turns differ on the work part 2 will choose, how an offer changes the spread,
  or how much the gain differs from item to item.

## Part 2. The items, and what an arm may retrieve

**Two sets, frozen separately, before any scored turn.**

- **History.** Items run first, with nothing offered. Their arrived turns are the only thing any arm may
  retrieve from.
- **Scored.** Different items. No scored item, and no turn at one, ever enters what an arm may retrieve.

**Which items.** Open items of v2's own work, taken in the order they are found, each with a frozen check
written by the other model family from the worker that takes it, shown before any turn to fail on the base,
fail on a wrong fix, and pass on a reference fix. No two items come from one fault. The order items were
found in, the ones left out and why, and the fault each came from are written down before any scored turn, so
that this can be checked afterwards.

- Draft 1 admitted an item only if its reference fix changed two files, and a scored item only if it shared a
  changed file with a history item. Both rules are gone. They used knowledge of the answer, and the second
  chose work the rail was likeliest to help.
- How many files an item's arrived turn changed, and whether a history turn changed any of them, are
  reported for every scored item as descriptions, after the fact. They choose nothing.
- **So the conclusion is about this work:** small items of one repository's own maintenance, in the order
  they came. It is not about work in general.

## Part 3. The experiment

**Arms.** The only difference between arms is a block of text added to the prompt.

| Arm | What the turn is given |
| --- | --- |
| Nothing | The stage 1 prompt: the item's title, its check's command, the rules |
| Notes | The same, and the whole commit messages of the nearest arrived history turns, up to three |
| Walks | The same, and the whole walks of the same turns: every file each named, in order, which it changed, what it cost, its verdict |

- **Whole means whole.** There is no limit on the block's length. The arm pays for what it offers: the cost is
  what the worker's program reports, which includes the block every time it is sent again.
- **One ranker for both arms, frozen before the run.** A title's words are its runs of letters and digits,
  in lower case. A history turn's score is the number of different words its item's title shares with the
  scored item's title. A word that is in more than half of the history items' titles scores nothing: in one
  repository's titles a few words are everywhere, and without this rule every history turn would score and
  the offer would be whichever came last. Highest first; ties go to the later turn. A score of nought is not
  offered. The score of every offer made is kept and reported.
- **Fewer than three, or none.** A run whose arm has nothing to offer is still its arm's run, and is counted
  as that. How often it happened is reported.
- **A walk is offered with its age.** A file it names that has changed since is marked as changed. A file
  that is gone is marked as gone. Neither is left out.
- **What this tests is a package:** this ranker, this rendering, these histories. If it shows no benefit, that
  is a result about the package. Whether the turns it offered had touched the files the scored turn went on
  to change is reported, so a reader can tell a poor match from a walk that did not help.
- **A fourth arm, stitched routes,** only if walks show a benefit over notes, and then on fresh items.

**Assignment.** Every scored item is run under every arm. Each turn has its own source copy, so no turn can
find another's answer. The order of an item's three arms is one of the six possible orders, drawn
by a seeded draw. The seed and the order are recorded.

**Paired in time as well.** An item's three runs follow one another, with no other item's run between them.
If seconds decide, a model's speed drifts with the hour, and three runs an hour apart would carry that drift
into the comparison.

**One run, defined.** An item under an arm is run as stage 1 runs an item: up to three turns, each fresh,
on the same base, with the same offer, told nothing of the turns before it. Its cost is the cost of all its
turns. It is complete if one of them passed verified.

**The deciding outcome.** The whole cost of an item under an arm, in tokens, if part 0 allowed tokens;
otherwise in active seconds. Reported beside it, and deciding nothing: the other of the two, steps, the
check's seconds, and whether the item was complete at the first turn.

- The figure for an arm against another is the typical ratio over the scored items: the mean of the ratios'
  logarithms, turned back into a ratio. It says by how much a typical item's cost is multiplied. Totals over
  all items are reported too, since a typical ratio is not a saving in total.

**An arm must finish the work to win on cost.** In any comparison, the arm that would be shown to benefit is
not read for one if it leaves incomplete an item that the arm it is compared with completes. Against nothing,
that is every item nothing completes. For walks against notes, it is every item notes complete. Every item
stays in the figures either way. Draft 1 would have let an arm win by failing cheaply.

**How uncertainty is worked out.** Two ways, and the wider one is used.

- By resampling the scored items with replacement, ten thousand times, each item carried whole with all its
  arms, and taking the middle 95% of the resampled figures.
- By the ordinary interval for a mean, on the logarithms of the items' ratios.

Resampling a score of items gives an interval that runs narrow. A benefit is shown only if the upper end of
both is below 1, so that it is not the method that shows it.

**How a comparison is read.** Four readings, which between them cover every interval, fixed now:

| The interval | Reading |
| --- | --- |
| Its upper end is below 1 | **A benefit is shown** |
| Its lower end is above 1 | **A cost is shown:** the arm makes the work dearer |
| It holds 1, and its lower end is above 0.85 | **A gain of 15% is ruled out** |
| It holds 1, and its lower end is 0.85 or below | **Nothing is shown either way** |

**Worth building on.** An offer is built on only if a benefit is shown *and* its figure is 0.85 or less. A
shown benefit with a figure above 0.85 is real and too small to build a rail for. The sizing below is for
showing a benefit. It does not promise that an arm whose true gain is exactly 15% will also show a figure of
0.85 or less: that happens about half the time.

**Which comparisons, in what order.**

1. Notes against nothing, and walks against nothing. Each uses the middle 95%, so that the two together are
   held to one chance in twenty of a false benefit.
2. Walks against notes, read only if walks showed a benefit against nothing.

Walks beating notes means nothing if walks did not beat nothing.

**How many.** Sized so that an arm with a true gain of 15% has a benefit shown four times in five:

`n = (1.96 + 0.84)^2 * (t^2 + 2 * c^2) / 0.1625^2`, rounded up.

- `c` is how much identical turns differ, and `t` is how much the gain differs from item to item. Both are
  standard deviations of logarithms. 0.1625 is the logarithm of 1 / 0.85.
- For planning, `c` is the largest of the pilot's three, not the middle one, and `t` is taken to be equal to
  `c`, since nothing measures it before the experiment. With both at 0.15 that is 21 items. At 0.2 it is 36.
  At 0.3 it is 81.
- This is a planning rule, not a promise. It leans on the pilot's three small items, and it is checked again
  by the fresh reader before part 3 with whatever the history items have shown by then.
- **Never fewer than 20 scored items,** whatever the rule gives. Resampling a handful of items says little.
- **If `n` is above 40, part 3 is not run in this form.** That is reported as "not affordable at this noise",
  with the question open. It is not reported as an answer.
- **What the pilot cannot give this rule.** It measures single turns on three small items. A run is up to
  three turns, an offer may change the spread, and the work will be different. Before part 3 the planning
  numbers are looked at again with what the history items have shown: their retries, and how their turns
  differ.

**When it stops.** After the planned `n`, and not before. Nothing is read for a decision until then.

**Read against these thresholds.** A failure changes the design, not the thresholds.

## What each outcome means

Read from the top. The first row that fits is the outcome.

| Outcome | What follows |
| --- | --- |
| The experiment stopped at part 0, 1 or 2, or was not affordable | Reported as that. The question stays open and the design changes |
| An arm left unfinished an item that the arm it is compared with finished | That arm is out of that comparison, and why is reported |
| Walks are worth building on against nothing, and show a benefit over notes | Stage 3 builds whole walks. Stitched routes get their own fresh test |
| Walks are worth building on against nothing, notes are too, and walks show no benefit over notes | v2 keeps notes and does not build the graph: the simpler thing did as well |
| Walks are worth building on against nothing, notes are not, and walks show no benefit over notes | Walks are kept as the only offer shown to help. Whether a note would do as well is not settled, and is said to be open |
| Notes are worth building on against nothing, and walks are not | v2 keeps notes and does not build the graph |
| Neither is worth building on | The rail is not built now. For each offer the report says which it was: a cost shown, a 15% gain ruled out, a benefit too small, or nothing shown either way. Only the first two close the question for that offer |

## What it costs, estimated

- **Turns before any scored one:** 3 replays and 15 pilot turns, then one item's worth for each history item,
  with their retries and second looks.
- **Scored turns:** three arms for each of `n` items, each up to three turns, plus second looks.
- **Checks to write:** one for every history and scored item, each with a wrong fix, a reference fix and a
  read by the other family. At the first run's rate, three took two builders and a reader half an hour, and a
  third reader then found three wrong fixes that passed two of them.
- **The room's ceiling is 40 turns a day,** so the experiment takes days.
- **Sign-ins:** every turn uses a person's model accounts. That is recorded where the person will see it.

## Not in this experiment

- **The hook:** telling a turn something at the moment of an act. That is claim C, and it needs its own test.
- **Lighthouses,** names and samenesses between machines.
- **Any text of a turn in the store.** Rule 9 stands.
- **A worker with no past to read.** See "What nothing means here".

## What the first reader found, and where it is answered

| Finding | Answer in this draft |
| --- | --- |
| 1. A fresh process on the same base is not isolation: a second turn's clone can hold the first one's answer | "Turns that cannot teach each other"; a source copy for every turn; "What nothing means here" |
| 2. A sum over steps is not a turn's whole cost | "A turn's whole cost"; the decision at the end of part 0 |
| 3. An arm can win by failing cheaply | "An arm must finish the work to win on cost"; "One run, defined" |
| 4. No benefit shown is not no benefit; walks over notes means nothing below nothing | The four readings; the order of comparisons; the outcome table |
| 5. The sizing's arithmetic holds and its variance model is optimistic | Part 1 is a pilot; the planning rule with `t`, the largest `c`, and a second read before part 3 |
| 6. The admission rules used the answer and favoured the rail; a table was read backwards | Both rules gone; the table read as it stands |
| 7. A cap is not a whole walk, and a weak ranker tests a package | No cap; the ranker written out; "What this tests is a package" |
| 8. The test for a finished instrument tested too little | "How we know part 0 is done" |
| 9. Notes are inside rule 9, with the line stated | "Where rule 9's line falls for notes" |

## What the second reader found, and where it is answered

It called five of the nine made as named (1, 3, 6, 7, 9) and four partly made (2, 4, 5, 8), and named four
changes.

| Change | Answer in this draft |
| --- | --- |
| A. The choice between tokens and seconds left a door open: "or a total the analysis has a written rule for" | "Tokens or seconds: decided by the table, before the pilot". The door is gone, and an incomplete deciding cost later stops the work |
| B. Time, the unit and the acceptance list were not yet something to build from | "Two words"; "Active seconds"; "What a record is tied to"; the table under "How we know part 0 is done" |
| C. The readings left an interval wholly above 1 unread, and the outcome table could keep notes that had shown nothing | Four readings; "Worth building on"; the outcome table, read from the top |
| D. An arm could still win cheaply against notes | "An arm must finish the work to win on cost", for each comparison's own reference |
| Also: a smallest number of items; the pilot measures turns, not runs | "Never fewer than 20"; "What the pilot cannot give this rule" |

## What a third reader added

The ship Tardis read draft 3 as an advisory reader. It checked the sizing and the two readings against
nothing, and added four points that neither earlier reader had raised. None stops parts 0 and 1 as it saw
them; the lead takes the first to bear on the pilot as well.

| Point | Answer in this draft |
| --- | --- |
| 1. A program's memory of its last prompt is a channel between turns: the second reads the first one's | "A prompt of its own", in part 0; used by the pilot and the experiment; memory reads kept apart in the tokens |
| 2. If seconds decide, a model's speed drifts with the hour | "Paired in time as well"; the pilot's turns spread across items |
| 3. Titles in one repository share a few words, so the ranker would offer whichever turn came last | A word in more than half the history titles scores nothing; every offer's score is reported |
| 4. Resampling about twenty items gives an interval that runs narrow | Two intervals, and the wider one decides |

## Decisions the lead made here, for the next reader to attack

1. "Nothing" keeps the repository's real history, and the claim is narrowed to what an offer adds.
2. Tokens decide if the instrument shows a whole total for every way a turn can end, and seconds decide if
   it does not. Which, is settled by part 0's table before the pilot, and does not change after.
3. Items are taken in the order they are found, with no rule that looks at the answer.
4. Whole walks and whole messages are offered with no cap.
5. The gain from item to item is planned for as equal to the noise between identical turns.
6. Above 40 items, part 3 is not run in this form, and below 20 it is run with 20.
7. A second look at a pass is timed beside a turn's active seconds, not in them.
8. An offer is built on only if its benefit is shown and its figure is 0.85 or less.
