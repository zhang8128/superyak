# v2: a document offered. A pilot of the design's second arm

Serenity, 2026-11-18 (UTC). Revision 3. A fresh reader read revision 1 (approve with named changes,
seven) and a second fresh reader read revision 2 (approve with named changes, four); all are made here
and listed at the end. Not built. It changes no code of the room: the pilot is run by scripts over the
room as it is. Before any model turn it has two more reads to pass: the twelve tasks, and the build.

## 1. What it is, and what it is not

The v2 design names its arms in order: nothing; notes found by ordinary search; whole walks; routes only
if walks beat notes. It says stage 2 can end the rail: "If no arm beats nothing, v2 is a room with checks
and a ledger." No saving has been measured so far. The rehearsal and the probes observed that a turn
names a first source file of its work within seconds; what help after that entry could do is unresolved.

On 2026-11-18 one thing was found that an offer could carry, and it is a document. The report
`docs/reports/2026-11-17-v2-the-whole-stack-tested.md` holds it under "The plan for the work". In short:

- At two items a plan for the work was already in the repository, gives calls and returns the held-back
  tests want, and was named in neither turn's walk.
- In four turns at those two items, the changes of the two turns given the plan's path pass 11 of 11
  and 61 of 64 held-back tests; of the two with the task unchanged, one named the plan by itself and
  passes 10 of 11, and one did not and passes 54 of 64.
- Over the list, at 52 of the 107 items that add a name to the source, a Markdown file at the parent
  matches one by a word. That is a match of words. At fifteen of eighteen whose text a reader read, it
  is a plan for the item's own work.

That a turn led to the plan for its work hands in something closer to what the tests want is a
hypothesis. Six turns fit it, and they also fit the variation between repeated turns.

**This pilot describes one thing: at twelve chosen items that have a plan for their work, how much of
the reference's own tests a turn's change passes when documents are offered, beside when nothing is.**
It is a descriptive pilot of conformance to the reference's tests at these items. It cannot establish a
dependable effect across plans, that a change behaves rightly, or a saving from the design's second arm.
It tests nothing for a difference and fixes no size for an experiment.

It is not a test of walks or routes. The store of walks holds no way to a plan that no earlier walk
named, as its owner has said. What is offered here comes from the repository's own files.

**It is not the stage-2 experiment's Notes arm.** That spec's notes are the commit messages of earlier
turns. Here the notes are documents kept in the repository: plans and specs.

## 2. The items

Twelve items of the item list the earlier probes used (its sha256 begins 4b25d330), chosen by rule before
any turn of this pilot. The rule and so the twelve were chosen after six probe turns at two items had
been seen, one of them among the twelve:

1. The item's reference passed the room's jail in the census of 2026-11-18.
2. A file under a `plans` or `specs` folder, tracked at the commit's first parent, holds as a whole word
   a name the commit adds under the source directory: eight letters or more, with an underscore inside
   it, absent from the parent's source, and held by five Markdown files or fewer.
3. No such file has a line that begins a test function (`def test_`).

Forty items meet the first two rules and twelve meet all three: 9a3f21cf, 71a593d5, d20c739b, cd884db7,
c9ceb15b, 671a2250, 1113f1db, 0193bde8, fff1b349, 027834bf, 3879e609, 3f349e89. By the list's parts seven
are scored and five are left out by its fifth rule. By the plan each matches: four are tasks of one plan,
three of another, two of a third, and three have a plan each. So the twelve are of six plans and are not
twelve unrelated things.

**Confirmed by the reader of revision 1, by reading each document at the item's parent:** each of the
twelve is a plan for the item's own work, and gives something the item's held-back tests use. Its table
is in its verdict.

**The matching files are frozen.** Ten items have one matching file. Two have two, a plan and its design
spec: 71a593d5 and 1113f1db. For every item:

- **The direct path** is one file: a file under `plans` before one under `specs`, then the file that
  holds most of the item's matched names, then the first by path. At all twelve that is the plan under
  `docs/superpowers/plans/` the reader confirmed.
- **A matching file** is any file the second rule finds for the item. A search's or a draw's hit, and
  what is looked for in a walk, are counted against that whole set.

**What this selection is.** It uses the finished reference's new names to find the document, so every
item here is known to have a document about its work: the pilot says nothing about offers where no such
plan exists. The third rule says only that the matching documents hold no test-function definition.
These plans still hold test names, exact assertions and step-by-step instructions for the tests. They
are unusually rich specifications, not documents without test information.

**The seven scored items are pilot-used after this.** No walk of this pilot is put in any store and no
turn here is history for any other, which prevents teaching one experiment with another's turns. It does
not leave those seven untouched as confirming work for a later design, since what they show will have
informed whoever designs it. They are to be marked so.

One of the twelve, 027834bf, has had probe turns; it stays, its row is marked, and every summary is also
given without it.

## 3. The task

Each item's task is written in a user's words: what is wanted and why. A commit's message is written
after the work by those who did it, in the plan's vocabulary; a search by it placed the matching file
first at ten of these twelve items. That is why the task is not the commit's message. What a search does
with a task in a user's words has not been measured.

**What a task must hold and must not, fixed for each item before it is written:**

- **Required facts:** a list, for the item, of what the change must do as a user would see it: each
  behaviour, each limit with its number, each refusal and when it happens. The list is drawn from the
  commit's message and the reference's change.
- **Withheld facts:** a list of what the task must not give: every file's name, every name of a
  function, class, constant, table or column, every test's name, the exact words of any message, and the
  shape of any call or return.
- **The plan's own words:** the task does not hold the plan's file name, the plan's title line, or any
  task number. Ordinary words that happen to be in a title are allowed.

**How the twelve are made.**

1. The lead writes each item's two lists and its task. The task states every required fact and no
   withheld fact, and nothing else.
2. A fresh reader of the other family checks each list against the commit and each task against its
   lists: is a required fact missing or added; is a withheld fact given; would a person who reads only
   the task know what is wanted?
3. Its changes are made, and the lists and the task's exact bytes are frozen with their hashes.
4. Only then is any search run on a task. A task is never rewritten after its search's result is seen.

A task file is the task's paragraphs, then one fixed sentence ("Make this change in the code under
`peer/superyak_peer`. Add tests for it if you like."), then the condition's paragraph if it has one.

The base is the commit's first parent with the task file and one small check file laid over it, as in
the earlier probes: the parent's own tests are there, and the item's new and changed tests are not. The
earlier probes' checks stay: before each turn, that the reference and the withheld test objects are not
among the objects the sandbox holds.

## 4. The conditions

The only difference between conditions is one paragraph at the end of the task file. That is proved for
every item before any turn: the seven bases have one parent and one tree but for the task file, and the
seven task files are byte for byte the same up to that paragraph.

| Condition | The paragraph | What it is here |
| --- | --- | --- |
| Nothing, first and second | None | The baseline, twice, as two rows named `nothing-1` and `nothing-2` |
| A plan exists | "There is a plan for this work in the repository." | An existence cue. It changes what the turn may look for; it does not measure what the worker knows |
| The plan's path | "The plan for this work is in the repository at" and the direct path | A targeted positive control. It is not the most a document could do: a turn may ignore it, and another document may add to it |
| Three by search | "These documents in the repository may bear on this work:" and three paths | The three Markdown files placed first by the task's words |
| Three newest plans | The same sentence and three paths | The three files under a `plans` folder whose names come last in byte order. A practical baseline with a strong advantage in time: here a plan is committed just before its work |
| Three nonmatching by lot | The same sentence and three paths | Three files drawn by lot from those under `plans` and `specs` folders that are not matching files of the item |

- **"May bear on this work" is itself a suggestion.** What is seen under the last three conditions is of
  that sentence with those paths.
- **Nonmatching is not wrong.** A file that the second rule does not find can still be about the work:
  at 9a3f21cf the design spec beside the plan gives the paging call the tests use and is not a matching
  file. So the last condition is an offer of three files drawn from those that do not match by a word,
  and nothing is said of what a wrong recommendation costs. Likewise a search that places no matching
  file in its three has low recall of matching files; its three are not thereby wrong.
- **The search is fixed here.** The query is the bytes of the task's own paragraphs: not the fixed
  sentence and not the condition's paragraph. Words are runs matching `[a-z][a-z0-9_]{3,}` in the text
  put to lower case. A file's score is the number of different query words it holds; a word held by more
  than half the Markdown files at the parent counts nothing. Highest first; ties by the path's bytes.
  Every Markdown file tracked at the parent is a candidate.
- **The lot is fixed here.** Seed 20261118. For an item, the candidate files are sorted by the path's
  bytes; each gets the SHA-256, in hexadecimal, of the ASCII text `<seed>:lot:<commit>:<path>`; the three
  smallest are taken, which draws without replacement. Here and in the order of section 5, `<commit>` is
  the item's whole commit id as the list gives it: forty hexadecimal characters in lower case.
- **Counted with no model before any turn, and reported whatever it is:** for each item, the place of
  the best-placed matching file under the search and under the newest plans. The newest plans' order
  does not depend on the task, and is counted already: they hold a matching file within three at all
  twelve. If the search holds one within three at fewer than four items, its condition is run all the
  same and is read as an offer with low recall of matching files.
- A document is offered by its path alone. Nothing of its text is put in the task.

## 5. The turns

Twelve items by seven rows: 84 turns.

- **Order.** One order over all 84 rows, not item by item: each row gets the SHA-256, in hexadecimal, of
  the ASCII text `<seed>:order:<commit>:<row's name>`, with the seed above and the row's name one of
  `nothing-1`, `nothing-2`, `exists`, `path`, `search`, `newest`, `lot`; rows run in ascending order of
  that hash. The order is written into the plan before the first turn.
- **Pinned in the plan with their hashes:** the worker program, its version and the model's name, as the
  earlier probes used; the room's program; every script of the pilot; every task file; every base; the
  check; every offered and every matching document's blob.
- **Pinned in the plan as numbers:** every limit in force: the worker's wall-clock limit as the room is
  given it, the check's, the replay's and the diagnostic's.
- **The small check's rule,** exactly: it passes when anything under the source directory differs from
  the parent. Its verdict says nothing of the work.
- Turns run one at a time, with nothing else heavy on the machine. For each turn the plan's record keeps
  when it began and ended, the machine's load at both, and how it ended.
- **Every scheduled row is kept.** A turn that the room ends without a hand-in, or at its limit, is kept
  and reported as that. Nothing is run a second time. A run that is interrupted is taken up at the first
  row with no record, and no row is ever run twice.

## 6. What is read from each turn

**The score is a count over a list of cases frozen from the reference.** A test file can import a new
name at its top, so one missing name stops every case in it from being collected; and a file can make
its cases from the candidate's own constants, so the number of cases can change with the change judged.
"Passed, of how many" from the turn's own run is therefore not a score.

- **The frozen cases.** For each item, before any turn, the item's reference is run in the jail and the
  identifier of every case of the item's test files that passes there is written down. Those cases, and
  only those, are the item's denominator.
- **A turn's score** is how many of the frozen cases pass under the turn's change, of that number. Beside
  it, for the frozen cases: passed, failed, in error, skipped, and not run (not collected, or not reached
  before a limit). Cases the turn's run collects that are not frozen cases are counted apart and are not
  in the score. Collection errors are kept in their own words.
- **The parent, with no change:** the frozen cases run once on the base as it is. That count is given
  for every item, so that tests which pass with no work at all are seen. One item's test file holds 23
  test functions before the item adds two.
- **Outcomes that are not a judged change,** each kept as its own outcome and scored as the parent with
  no change: no hand-in; a hand-in that changes nothing under the source directory.
- **Rows with no score.** A turn's change that does not apply on its own base, or a diagnostic that
  reaches its limit, has no score: the row is kept, with its outcome named and whatever was counted
  before it stopped given beside it, and it enters no sum. A diagnostic that reaches its limit is not
  thereby the instrument's fault; why it did is not decided here.
- **What a row with no score does to the reading of section 7.** If either Nothing row of an item has
  no score, that item has no baseline and no gap, and no condition is read at it. If an offering row has
  no score, that condition is not read at that item. Every table says how many items it stands on. If
  any row the spending rule needs has no score, the rule is not applied: the pilot reports what it has
  and says the rule is suspended.
- **By replay,** as the report describes it: only what the turn changed under the source directory is
  applied on the item's base by a script in the worker's place, and the room judges it in its jail with
  the item's frozen check. The room's verdict stands beside the score.
- **What the failing cases print first** is reported as first obstacles, not as a diagnosis of the
  change.
- **From the walk:** whether a step names a matching file, at which step and second, and which offered
  files it names. A walk holds the paths a step names and no command or output, so "named" is all that
  is said.
- **A control for every item before its turns:** the item's reference through the replay and the
  diagnostic, in directories named as the pilot's are, which must pass every frozen case. A turn's code
  runs only inside the jail.

## 7. What is reported, and how it is read

For each item, with `n1` and `n2` the two Nothing scores as shares of the frozen cases:

- the baseline `b = (n1 + n2) / 2` and the observed gap `r = |n1 - n2|`;
- for each offering condition its share `o` and the difference `d = o - b`;
- the condition is **higher** at the item when `d > r`, **lower** when `d < -r`, and otherwise **within
  the observed baseline gap**. The raw `d` is given beside each.

Two Nothing turns give one observed gap. It is not a margin of equivalence and not an estimate of how
much repeated turns vary.

For each offering condition: how many of the twelve items are higher, lower and within the gap, and the
same without 027834bf.

**By plan.** For each of the six plans and each offering condition, over that plan's items: `D` is the
mean of the items' `d` and `R` the mean of the items' `r`. The condition is **higher at the plan** when
`D > R`, **lower at the plan** when `D < -R`, and otherwise within the plan's mean baseline gap. Each
plan's items are listed with it. With every plan weighing the same, a condition's figure is the sum of
the six plans' `D`, divided by six.

**No test of a difference is made. The following is a rule for where to spend next. It and the twelve
items were both chosen by the lead after seeing six probe turns at two items, one of which is among the
twelve, and before any turn of this pilot. It is not a protection against chance:** four items of one
plan, three of another and two of a third could give nine higher rows from three plans.

- **Worth designing an experiment:** one condition of the two, Three by search or Three newest plans, is
  higher at eight or more of the twelve items, lower at two or fewer, and higher at four or more of the
  six plans; and Three nonmatching by lot is lower at three or fewer of the twelve items.
- **Not worth one:** neither of the two is higher at more than five items.
- **Between:** reported as that.

The plan's path and A plan exists are read beside these as what they are, a positive control and an
existence cue. Whatever they show is reported; no conclusion about the hypothesis is fixed here on
either alone.

## 8. What is built

No change to the room. Scripts beside the earlier probes' in `v2/probes/`, each with tests:

1. **A maker of the pilot's plan:** the items by the rule, the frozen lists and tasks, the paragraph of
   each row, the direct path and the matching files, the search's and the newest plans' places, the
   lot's draws, the order, the frozen cases, and every pin of section 5, in one file with its hash.
   Every later stage refuses a plan whose hash or inputs have changed.
2. **A runner:** one row at a time in the frozen order, each in a room of its own, in directories named
   without a commit's whole id, keeping each row's record and taking up an interrupted run without
   running a row twice.
3. **A judge:** the controls, the replay, the diagnostic over the frozen cases, the walk's reading, and
   the report's tables of section 7.

The earlier probes' scripts did these by hand and are the starting point.

**Tests.** Unit tests, and one test of the whole path against the real room and its jail with a script
named for the worker and no model, run by the lead before any reader sees the build. Between them they
must show: all seven rows of an item scheduled and run once each; each row's paragraph exactly as
section 4 gives it; a result where some frozen cases pass and some fail; a test file that cannot be
collected, scored as not run; a turn with no hand-in and one stopped at its limit, kept and scored as
section 6 says; an interrupted run taken up with no row run twice; and a plan refused after one of its
inputs is changed.

## 9. What it costs

84 turns at about three minutes: over four hours of one machine, with nothing else heavy on it. The
judging is about 220 script turns in the jail with no model, over an hour.

## 10. What this narrows, said before any turn

- One repository, one component, one worker program and model, macOS. Twelve items of six plans, each
  offering condition once and Nothing twice.
- The outcome is conformance to the reference's tests: names, calls and wordings as well as behaviour.
  Where a plan gives those, that is a fair thing to ask of a turn that was shown the plan; it is not a
  judgement of behaviour.
- Every item was chosen because a document about its work exists, found by the finished reference's own
  new names. Nothing is said of work with no such document.
- Forty items meet the first two rules; the 28 left out have a test-function definition in a matching
  document. The twelve kept still have plans with test names, assertions and test instructions in them.
- The tasks are the lead's words, bound by the lists of section 3 and one reader. A person's own words
  may be further from the plan's, or nearer. A task is written from the finished work.
- An offer is a paragraph in the task file, with one sentence of suggestion. What the room's own offer
  block would do with documents is not tried.
- The newest plans hold the matching plan here because of how this repository's work is kept: spec,
  then plan, then build, with the plan committed just before. That is not a showing that search works.
- Other work on the machine can end a turn at its limit or fail a test that waits on time. Load is
  recorded; it is not controlled beyond running nothing else heavy.

## What the reader of revision 1 named, and where it is answered

A fresh reader of the other family (the team's w101) read revision 1 at ae11de2c: approve with named
changes, seven. It rebuilt the 47, 40 and 12, and confirmed all twelve plans by reading them.

| Its change | Where |
| --- | --- |
| 1. Freeze the outcome's denominator from the reference's own cases; define every unsuccessful outcome; a parent control | Section 6 |
| 2. Make the decision rule executable (`b`, `r`, `d`); read it as a heuristic; by plan, equally weighted, and without the probed item; say when it was chosen | Section 7 |
| 3. Remove two bounds: that nothing was lacking before, and that the path is the most a document could do | Sections 1 and 4 |
| 4. Bind what a task holds, not only what it must not name; freeze before searching; fix the query's bytes and the search's rules | Sections 3 and 4 |
| 5. "Nonmatching", not "wrong"; low recall of matching files; the suggestion's own sentence; the newest plans' advantage in time | Section 4 |
| 6. Close what a builder could choose: the direct path, the matching set, seed, lot, order, pins, the check's rule, replay of source only, what the tests must cover, load | Sections 2, 4, 5, 6 and 8 |
| 7. Narrow two claims: the scored items are pilot-used; the twelve plans are rich in test information; say what the selection is | Sections 2 and 10 |

A second fresh reader of the other family (the team's w102) read revision 2 at 18e72194 against that
verdict: approve with named changes. It found three of the seven made as named, three made otherwise
and not yet enough, and one made otherwise and mostly enough. What it named is made in revision 3:

| Its change | Where |
| --- | --- |
| A row with no score, and what it does to the reading: no baseline without both Nothing rows; the rule suspended when a row it needs is missing | Section 6 |
| The by-plan rule written out (`D`, `R`), the equally weighted figure, the lot's threshold in items, and when the rule and the twelve were chosen | Sections 2 and 7 |
| The commit in both hashes is the whole id in lower case; every limit and every script pinned | Sections 4 and 5 |
| "Each offering condition once and Nothing twice" | Section 10 |
