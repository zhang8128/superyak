# v2 stage 2: the experiment, written down before it runs

Serenity, 2026-11-15. **Draft 2.** It fills in section 12 of `2026-11-14-superyak-v2-design.md` ("Stage 2,
written down before it runs") with what stage 1's first run measured. Nothing here is built.

Draft 1 was read cold by a reader of the other model family. Its verdict: approve with named changes, for
building the instrument (part 0) and running the pilot (part 1) only. It made nine findings, and every one is
answered here. The last section says which change answers which.

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
| 0. The instrument | What an attempt's record holds, and that attempts cannot teach each other | An attempt's whole cost cannot be had for every way an attempt can end, by tokens or by time |
| 1. The pilot | That the instrument works on live turns, and a first look at how identical turns differ | The instrument loses attempts or costs on live turns |
| 2. The items | The work, its checks, and what an arm may retrieve | Too few items can be given honest checks |
| 3. The experiment | Whether an offer shows a benefit | It ends by its own rule, below |

**The reader's verdict covers parts 0 and 1.** Parts 2 and 3 as written here are a plan. They are read again,
by a fresh reader, with part 1's numbers in hand, before any scored turn runs.

## Part 0. The instrument

Everything here stays inside rule 9: names of tracked files at a commit, numbers and verdicts. No text of a
turn is kept.

**Attempts that cannot teach each other.** Today a sandbox is cloned from the item's repository, and the clock
brings each returned commit into that same repository. A second attempt at the same item can therefore hold
the first one's answer as an object.

- Every attempt is cloned from its own copy of the item's source, made fresh from one frozen set of objects:
  the base, the wrong commits, and what they reach. Nothing else.
- Returned commits go to a repository that no later attempt is cloned from.
- Before an attempt starts, its source copy is shown to hold no earlier answer and no reference fix, by
  object id, beside a control object that has to be there.
- Within a block of attempts that will be compared, the worker's program and model, the rules, the check and
  the limits do not change, and their versions are recorded.

**An attempt's whole cost.**

- **Tokens:** what the worker's program reports at the end for the whole attempt, not a sum over steps. For
  Claude that is the closing total: fresh input, cache writes, cache reads and output, each once. For Codex it
  is the turn's own total, once part 0 has established which of its fields are totals and which are parts of
  another, so that nothing is added twice. The parts are kept, with where each came from.
- **A cost that is missing is never zero.** A killed or crashed program may give no closing total. Each
  attempt's record says whether its cost is complete.
- **Time:** when the attempt started and ended, and when its check started and ended, measured on a clock
  that does not jump. Each step keeps when its call was seen and when its result came.

**What a turn touched.**

- A shell step records every tracked file its command names, in the order named. It says "named in a
  command", not "read". The room cannot tell which, and a search over a directory names nothing.
- An attempt's record says which tracked files its commit added, changed or removed, taken from the
  difference between the base and the commit. This covers a change made by a shell command.
- What cannot be named is recorded as unknown. How much of each attempt is unknown is measured and reported.
  Nobody promises that every file a turn touched has a name in its record.

**What an attempt was given.** Its arm, the order it ran in, and what it was offered: the ids of the walks or
commits offered, the version and hash of the ranker and of the renderer that made the text, the text's
length, and its hash. A hash alone is not a recipe, so the ranker and renderer are deterministic and pinned,
and an offer can be made again from what is kept. The text itself is not kept.

**A worker that cannot commit can still say what it did.** The room commits for Codex with a fixed message
today. A worker may leave its message in one untracked file. The room uses it as the commit's message and
removes the file before the commit is made, so the file is never part of what is checked.

**Where rule 9's line falls for notes.** The store keeps commit ids and a hash. Commit messages live in the
repository, where they already are. The rendered offer, the message file and the full prompt are not kept in
any store, log or cache of the room's.

**How we know part 0 is done.** Each line is shown with captured streams or scripts for both workers'
programs, and then on live replays of the three stage 1 items:

- the whole-attempt total agrees with the program's own closing total, with messages that arrive twice
  counted once;
- an attempt that is killed, crashes or times out has a record that says its cost is incomplete, and is not
  dropped;
- a turn with no tool call at all has a record;
- a command naming several files records them all, in order;
- added, changed and removed files are taken from the difference, including a change made by a shell command;
- no text of a turn is in the store;
- two attempts at one item are shown not to share an answer, with the control present.

**Decided at the end of part 0, before part 1:** whether tokens can be the deciding outcome. They can if every
way an attempt ends gives a total, or a total marked incomplete that the analysis has a written rule for. If
not, the deciding outcome is the attempt's active seconds through its verdict, and the pilot measures that.

## Part 1. The pilot

**What it is for.** To show the instrument working on live turns, and to give a first look at how much the
same turn differs from itself. It is a pilot. Its numbers do not by themselves fix the size of part 3.

- **What is run:** each of the three items of the first run, five times, with nothing offered, each attempt
  from its own source copy, by the worker that may take it. Fifteen turns, plus the three replays of part 0.
- **What is read:** for each item and worker, the spread of the deciding outcome across its five turns, as a
  standard deviation of the logarithm. All three are kept and reported, with the worker beside each.
- **What it cannot say:** how turns differ on the work part 2 will choose, how an offer changes the spread,
  or how much the gain differs from item to item.

## Part 2. The items, and what an arm may retrieve

**Two sets, frozen separately, before any scored turn.**

- **History.** Items run first, with nothing offered. Their arrived turns are the only thing any arm may
  retrieve from.
- **Scored.** Different items. No scored item, and no attempt at one, ever enters what an arm may retrieve.

**Which items.** Open items of v2's own work, taken in the order they are found, each with a frozen check
written by the other model family from the worker that takes it, shown before any turn to fail on the base,
fail on a wrong fix, and pass on a reference fix. No two items come from one fault.

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
  scored item's title. Highest first; ties go to the later turn. A score of nought is not offered.
- **Fewer than three, or none.** An attempt whose arm has nothing to offer is still its arm's attempt, and is
  counted as that. How often it happened is reported.
- **A walk is offered with its age.** A file it names that has changed since is marked as changed. A file
  that is gone is marked as gone. Neither is left out.
- **What this tests is a package:** this ranker, this rendering, these histories. If it shows no benefit, that
  is a result about the package. Whether the turns it offered had touched the files the scored turn went on
  to change is reported, so a reader can tell a poor match from a walk that did not help.
- **A fourth arm, stitched routes,** only if walks show a benefit over notes, and then on fresh items.

**Assignment.** Every scored item is attempted under every arm. Each attempt has its own source copy, so no
attempt can find another's answer. The order of an item's three arms is one of the six possible orders, drawn
by a seeded draw. The seed and the order are recorded.

**One attempt, defined.** An item under an arm is run as stage 1 runs an item: up to three turns, each fresh,
on the same base, with the same offer, told nothing of the turns before it. Its cost is the cost of all its
turns. It is complete if one of them passed verified.

**The deciding outcome.** The whole cost of an item under an arm, in tokens, if part 0 allowed tokens;
otherwise in active seconds. Reported beside it, and deciding nothing: the other of the two, steps, the
check's seconds, and whether the item was complete at the first turn.

- The figure for an arm against another is the typical ratio over the scored items: the mean of the ratios'
  logarithms, turned back into a ratio. It says by how much a typical item's cost is multiplied. Totals over
  all items are reported too, since a typical ratio is not a saving in total.

**An arm must finish the work to win on cost.** An arm is not read for a benefit at all if it leaves
incomplete any item that nothing completes. Draft 1 would have let an arm win by failing cheaply.

**How uncertainty is worked out.** By resampling the scored items with replacement, ten thousand times, each
item carried whole with all its arms, and taking the middle 95% of the resampled figures.

**How a comparison is read.** Three readings, fixed now:

| The interval | Reading |
| --- | --- |
| Its upper end is below 1 | **A benefit is shown.** Whether it is worth having is read from the figure: 0.85 or less is |
| It holds 1, and its lower end is above 0.85 | **A gain of 15% is ruled out** |
| It holds 1, and its lower end is 0.85 or below | **Nothing is shown either way** |

**Which comparisons, in what order.** Two against nothing: notes, and walks. Each uses the middle 95%, so
that the two together are held to one chance in twenty of a false benefit. Then walks against notes, read
only if walks showed a benefit against nothing. Walks beating notes means nothing if both are worse than
nothing.

**How many.** Sized so that an arm with a true gain of 15% has a benefit shown four times in five:

`n = (1.96 + 0.84)^2 * (t^2 + 2 * c^2) / 0.1625^2`, rounded up.

- `c` is how much identical turns differ, and `t` is how much the gain differs from item to item. Both are
  standard deviations of logarithms. 0.1625 is the logarithm of 1 / 0.85.
- For planning, `c` is the largest of the pilot's three, not the middle one, and `t` is taken to be equal to
  `c`, since nothing measures it before the experiment. With both at 0.15 that is 21 items. At 0.2 it is 36.
  At 0.3 it is 81.
- This is a planning rule, not a promise. It leans on the pilot's three small items, and it is checked again
  by the fresh reader before part 3 with whatever the history items have shown by then.
- **If `n` is above 40, part 3 is not run in this form.** That is reported as "not affordable at this noise",
  with the question open. It is not reported as an answer.

**When it stops.** After the planned `n`, and not before. Nothing is read for a decision until then.

**Read against these thresholds.** A failure changes the design, not the thresholds.

## What each outcome means

| Outcome | What follows |
| --- | --- |
| Neither offer shows a benefit | The rail is not built now. If a 15% gain was ruled out for both, that is said. If not, the question is open and stays open |
| Notes show a benefit, walks do not, or walks show none over notes | v2 keeps notes and does not build the graph |
| Walks show a benefit over nothing and over notes | Stage 3 builds whole walks. Stitched routes get their own fresh test |
| An arm left work unfinished that nothing finished | That arm is out, and why is reported |
| The experiment stops at part 0, 1 or 2, or is not affordable | Reported as that. The question stays open and the design changes |

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
| 1. A fresh process on the same base is not isolation: a second attempt's clone can hold the first one's answer | "Attempts that cannot teach each other"; a source copy for every attempt; "What nothing means here" |
| 2. A sum over steps is not a turn's whole cost | "An attempt's whole cost"; the decision at the end of part 0 |
| 3. An arm can win by failing cheaply | "An arm must finish the work to win on cost"; "One attempt, defined" |
| 4. No benefit shown is not no benefit; walks over notes means nothing below nothing | The three readings; the order of comparisons; the outcome table |
| 5. The sizing's arithmetic holds and its variance model is optimistic | Part 1 is a pilot; the planning rule with `t`, the largest `c`, and a second read before part 3 |
| 6. The admission rules used the answer and favoured the rail; a table was read backwards | Both rules gone; the table read as it stands |
| 7. A cap is not a whole walk, and a weak ranker tests a package | No cap; the ranker written out; "What this tests is a package" |
| 8. The test for a finished instrument tested too little | "How we know part 0 is done" |
| 9. Notes are inside rule 9, with the line stated | "Where rule 9's line falls for notes" |

## Decisions the lead made here, for the next reader to attack

1. "Nothing" keeps the repository's real history, and the claim is narrowed to what an offer adds.
2. Tokens decide if the instrument can give them for every attempt, and seconds decide if it cannot. Which,
   is settled before the pilot.
3. Items are taken in the order they are found, with no rule that looks at the answer.
4. Whole walks and whole messages are offered with no cap.
5. The gain from item to item is planned for as equal to the noise between identical turns.
6. Above 40 items, part 3 is not run in this form.
