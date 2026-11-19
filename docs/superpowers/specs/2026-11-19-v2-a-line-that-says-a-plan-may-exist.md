# v2: a line that says a plan may exist. A second pilot

Serenity, 2026-11-19 (UTC). Revision 2. A fresh reader of the other family read revision 1: do not
approve, six findings. Revision 1 reran the first pilot's twelve items with their documents taken out of
the base; the reader showed that no rule of file names can make "no plan exists" true, and the design is
dropped. This revision is the spend the reader proposed, with one small part added. What it named and
where each is answered is at the end. Not built. It changes no code of the room.

It follows the pilot "a document offered" (`docs/superpowers/specs/2026-11-18-v2-a-document-offered.md`,
revision 4; report `docs/reports/2026-11-19-v2-a-document-offered-pilot.md`). Where this spec is silent,
that spec's sections 3, 5 and 6 hold: how a base is made, the order, the pins, the controls, the score
over cases frozen from the reference, the rows with no score.

## 1. What the first pilot left open

At twelve items that each have a plan for their work in the repository, a Codex turn told "There is a
plan for this work in the repository" passed 367 of 453 frozen test cases, and with nothing added 151
and 154. Its walk named a matching file at 11 of 12 items when told, and in 1 of 24 turns when not.
That report says what it does not show. Three of those things are asked here:

1. **A room cannot say "there is a plan" without knowing.** What it can say to every turn is that one
   may exist, and to look. What a turn does under that line was not observed.
2. **Every item had a plan.** What a turn does under the line at work for which no plan is found was
   not observed.
3. **The tasks withheld every name.** At one item, earlier turns whose task was the commit's own message
   passed 55 and 54 of 64 with nothing added, against 0 of 64 in the pilot. Those are observations under
   two task texts at one item.

**This pilot describes what a turn's change passes of the reference's tests, and what its walk names,
with and without one added line, at twelve items not used before, six with a plan confirmed by reading
and six where a stated review finds none; and, apart, what the line does at the first pilot's twelve.**
It is descriptive. It tests nothing for a difference, and it recommends nothing for the room: its rule
says only whether a larger trial is worth running.

## 2. The line

Exactly, as one unwrapped ASCII paragraph with no quotation marks:

`There may be a plan for this work in the repository. Look for one before you change code.`

It names no folder and no file. It is two things at once, a statement that a plan may exist and an
instruction to look; this pilot does not take them apart. One wording is tried.

## 3. Part A: the first pilot's twelve, one new row

The first pilot's twelve items, bases, frozen tasks and frozen cases, unchanged. One new last paragraph,
the line, run twice: rows `may-1` and `may-2`. 24 turns.

These items are not fresh: 96 turns have been run at them and their results shaped this design. Part A
is a look at whether, under the line, a walk names a matching file as it did under the cue, in the one
setting where the first pilot saw a large gap. It enters no class and no rule. Its rows are given beside
the first pilot's rows for the same items, which are an earlier run.

## 4. Part B: twelve items not used before

**Not used before** means: not one of the first pilot's twelve, and no model turn of any earlier probe,
rehearsal or pass was run at it. The lead lists those items from its run records before selection; the
list is pinned in the plan.

Two pools, counted on 2026-11-19 with no model from the item list's 188 commits (157 references pass
the room's jail in the census; 101 commits add a counted name by the first pilot's reading of its
second rule):

- **Pool P, a plan by the first pilot's rules:** the commit meets that pilot's rules 1 and 2 and is not
  one of its twelve. 28 commits, 19 of them not used before; those 19 are of ten plans. All 28 have a
  test-function definition in a matching file: the first pilot took every item without one. So these
  plans hold test code, which the first pilot's did not.
- **Pool N, no document holding a new name:** the reference passes the jail, the commit adds a counted
  name, and no Markdown file tracked at the first parent, in any folder and with no limit of five,
  holds a counted name as a whole word. 46 commits, 43 of them not used before.

**Selection, frozen before any turn.** Each pool is put in ascending order of the SHA-256, in
hexadecimal, of the ASCII text `20261120:pick:<commit>`, the commit's forty lower-case characters, with
no newline. A fresh reader of the other family than the lead walks each order and takes an item or
skips it, with its reason written down, until six are taken from each:

- **From pool P,** an item is taken when the reader, having read the matching file at the item's parent
  and the commit's change, finds that the file is a plan for this item's own work and gives something
  the item's tests use. No more than two items of one plan are taken.
- **From pool N,** an item is taken when the reader's review finds no document at the parent that
  specifies the item's work. The review, for each item: from the commit's message and change, the
  reader writes down the work's subject and its distinctive terms (identifiers, routes, table and file
  names, the message's own nouns); searches the path and the text of every Markdown file at the parent
  for each; reads every file a search finds; and says "none found" or names the file. A file that
  specifies the work under another name counts. An item with any doubt is skipped.

The reader's record, for every item walked: the terms searched, the files read, the verdict. It is
kept beside the plan and its hash pinned.

**What "none found" is.** It is the outcome of that review by one reader. It is not a showing that no
document bears on the work. The report says "no plan found by the review", never "no plan exists".

**After the controls,** an item none of whose frozen cases fails on the parent is replaced by the next
of its pool's order that the reader takes: such an item can show no gain.

## 5. Part B's tasks and rows

**The task is the commit's own message.** No task in a user's words is written for these items. The
bytes: the output of `git show -s --encoding=UTF-8 --format=%s%n%n%b <commit>` in the item list's
repository, with trailing ASCII white space removed from its end (space, tab, carriage return, line
feed, vertical tab, form feed) and nothing else changed, so trailers stay; then the fixed sentence and
the last paragraph, framed as the first pilot's maker frames a task. The message's bytes are pinned for
every item.

A commit's message is written after the work by those who did it, in their own words for it. It may
carry the plan's names and it may name the plan. That is what is tried here: the line beside a task
that already speaks the work's language.

Four rows an item: `nothing-1`, `nothing-2`, `may-1`, `may-2`. 48 turns. The four task files of an item
are byte for byte the same up to the last paragraph, and the maker proves it.

**The bases are made as the first pilot's:** a commit on the item's first parent holding the task file
and the small check file. The history up to the parent is in the turn's repository, as it was in the
first pilot; no document is removed anywhere.

## 6. The turns

72 turns, one at a time, in one order over both parts: ascending SHA-256, in hexadecimal, of the ASCII
text `20261120:order:<commit>:<row's name>` with no newline. Worker, limits and pins as in the first
pilot. The plan also pins the list of items used before, the two pools in their orders, and the
selecting reader's record.

## 7. What is read from each turn

As the first pilot's section 6: the frozen cases passed; of those that do not pass on the parent, how
many pass; the room's verdict by replay; the outcomes with no score.

From the walk, which holds the paths a step names and no command or output:

- at a part A item and a pool P item, whether and when a step names a matching file;
- at every item, how many distinct paths under a `plans`, `specs` or `reviews` folder the walk names,
  and the paths. This says a path was named. It does not say a file was read, used or followed, and a
  search can take in a file's text without naming it;
- the second of the first step that names a path under the source directory;
- the turn's steps, seconds and tokens. Where a turn's record lacks a number, the table says how many
  turns it stands on.

## 8. How it is read

Shares are of the frozen cases. Every table is given again on the cases that do not pass on the parent,
leaving out an item with no such case and saying how many items it stands on.

**Part B, an item.** With both Nothing rows scored: `b = (n1 + n2) / 2` and `rn = |n1 - n2|`. With both
rows under the line scored as well: `m = (m1 + m2) / 2`, `rm = |m1 - m2|` and `d = m - b`. The line is
**higher** when `d > max(rn, rm)`, **lower** when `d < -max(rn, rm)`, otherwise within the observed
gaps. If either row of a pair has no score, that pair gives no number for the item: one run is never
taken as the cell. Every raw `d`, `rn` and `rm` is printed.

**Part B, a pool.** The mean of `d` over the pool's items that have one, with the number of items it
stands on; and for pool P the mean over plans of each plan's mean `d`. Beside it: how many items are
higher, lower and within.

**Counts beside the scores, by pool and row kind:** in how many turns the walk names a matching file
(pool P); the distinct paths under `plans`, `specs` or `reviews` a walk names; the first second a
source path is named; steps, seconds, tokens.

**Part A** is given as counts: in how many of the 24 turns the walk names a matching file, and the
frozen cases passed at each item in each run, beside the first pilot's rows. No class.

**A rule for whether a larger trial of the line is worth running.** It was written by the lead after
the first pilot's results were seen. It is a heuristic for spending, no protection against chance, and
it recommends nothing for the room. It reads part B alone:

- **Worth a larger trial:** at pool N the mean `d` is zero or above and no item is lower; and at pool P
  the mean `d`, and the mean over plans, are zero or above.
- **Not worth one:** at pool N two or more items are lower, or the mean `d` is below -0.05.
- **Between:** reported as that.

The rule needs both Nothing rows and both line rows of every part B item. If one has no score the rule
is not applied and the report says which. "Within" is not a finding of no cost: a loss inside a wide
gap reads within, which is why the rule reads the mean and the raw differences are printed.

## 9. What is built

Changes to the first pilot's three scripts, in place, each with tests and a mutant for every condition
added. The first pilot is judged and reported; its plan is not read by the changed scripts.

1. **The maker:** the two parts; the pools, their orders and the pinned record of the selection; the
   commit's message as a task with its exact bytes; the rows; the order over 72.
2. **The runner:** unchanged but for what its tests show it needs.
3. **The judge:** the readings of section 8 with two runs a cell; the walk's counts of section 7; the
   tables; the rule.
4. **The scripts' tests on a second machine:** the three test files are added to the list the
   repository's "v2 checks" workflow runs on Linux and macOS, with the maker's history test skipped
   where the checkout holds no history. The first pilot's scripts were pushed with their tests run on
   one machine.

Before the plan is made, the lead runs the whole path on the real room with a stand-in script in the
worker's place, at one item of each part and pool, through the judge and the report: the plan pins the
judge.

## 10. What it costs

72 turns at about 190 seconds: about four hours of one machine. The judging under an hour. Before
them, the selecting reader's review of up to 62 candidates, and the controls.

## 11. What this narrows, said before any turn

- Twelve fresh items of one repository and one component, six an arm; one worker program and model; one
  machine. Part A's twelve are seen.
- The outcome is agreement with the reference's tests: names, calls and wordings as well as behaviour.
  Nothing here judges a change as work.
- Pool P's plans hold test code. A turn that names one may be taking its tests' own expectations from
  it.
- "No plan found" is one reader's review. A document may bear on the work and be missed.
- The task is the commit's message. It is not what a person who wants the work would write, and it is
  not the first pilot's kind of task; part B and the first pilot differ in items and in task kind at
  once, and no difference between them is read as either's doing.
- Two runs a cell give two gaps, not a measure of variation.
- One wording of the line, which states and instructs at once.
- Part A's rows and the first pilot's are two runs at different times; putting them side by side is a
  look.

## What the reader of revision 1 named, and where it is answered

A fresh reader of the other family (the team's w122) read revision 1 at 674f6652: do not approve. It
reproduced the removal counts and the first pilot's totals.

| Its finding | Where |
| --- | --- |
| 1. A rule of file names does not establish that no plan remains: at three items the work's own design stayed under another name | The removed base is dropped. Section 4: "none found" by a stated review, with its record, and said as that |
| 2. The rule could recommend while the line lost half the cases at every item, inside a wide gap | Section 8: a rule for a larger trial only; raw differences printed; means zero or above required |
| 3. A base with no parent breaks the small check, and removed objects must be shown absent | No base without a parent and nothing removed: section 5 |
| 4. The item list holds no commit message; message tasks cannot share the frozen tasks' prefix | Section 5: the message's exact bytes from the repository; the proof is within an item |
| 5. No rule for a cell with one run missing | Section 8: a pair with a missing score gives no number |
| 6. Each question claimed more than its rows show; "takes up", "false", "days apart" | Sections 1, 7 and 8 say what is named and counted; the false assurance row is dropped |
| Its spend: 48 turns at twelve unused items, six with a plan confirmed by reading and six with none found | Part B. Part A, 24 turns at the seen twelve, is the lead's addition and enters no rule |
