# v2: a line that says a plan may exist. A second pilot

Serenity, 2026-11-19 (UTC). Revision 1. Not read and not built. It follows the pilot "a document
offered" (`docs/superpowers/specs/2026-11-18-v2-a-document-offered.md`, revision 4; its report is
`docs/reports/2026-11-19-v2-a-document-offered-pilot.md`) and changes no code of the room. Where this
spec is silent, that spec's sections 3, 5 and 6 hold: how a base is made, the order, the pins, the
controls, the score over cases frozen from the reference, the rows with no score.

## 1. What the first pilot left open

At twelve items that each have a plan for their work in the repository, a Codex turn told "There is a
plan for this work in the repository" passed 367 of 453 frozen test cases, and with nothing added 151
and 154. Its walk named a matching file at 11 of 12 items when told, and in 1 of 24 turns when not.
Three things that report says it does not show are what this pilot asks:

1. **A room cannot say "there is a plan" without knowing.** What it can say to every turn is that one
   may exist. Whether that weaker line does what the cue did is not known.
2. **Every item had a plan.** What the line costs where there is nothing to find, and whether a turn
   then takes up some other document, is not known.
3. **The tasks withhold every name.** At the one item probed before, turns whose task was the commit's
   own message passed 55 and 54 of 64 with nothing added, against 0 of 64 in the pilot. How much of the
   pilot's gap is the task's wording is known at one item.

**This pilot describes, at the same twelve items: what a turn's change passes of the reference's tests
when the task ends with a line saying a plan may exist; the same when every document about the work has
been taken out of the repository the turn is given; and the same when the task is the commit's own
message.** It is descriptive. It tests nothing for a difference.

**The twelve items are not fresh.** They were chosen for the first pilot, 96 turns have been run at
them, and their results informed this design. Nothing here confirms the first pilot on new work.

## 2. The items, the tasks and the two bases

The twelve items of the first pilot, with the same frozen tasks (`v2/probes/documents/tasks/`, hashes
in `FROZEN.sha256`), the same frozen cases, and the same parent control. The first pilot's controls are
made again for this plan and must give the same case lists.

Each item has two bases. Both hold the task file and the small check file laid over a tree; they differ
in the tree.

**Each base is a single commit with no parent,** so the repository a turn is given holds no history.
In the first pilot a base had the item's first parent as its parent, and the whole history was there.
Here it is not, for either base: a removed file would otherwise be one command away. So a `present`
row here is not an exact repeat of a first-pilot row; it differs by the absent history.

- **The documents present:** the tree of the commit's first parent.
- **The documents removed:** that tree with these files deleted, and nothing else changed:
  - every Markdown file whose own file name holds the plan's slug. The slug is the direct path's file
    name without its leading date (`YYYY-MM-DD-`) and its ending `.md`: for example `federation-pull`;
  - every Markdown file that holds, as a whole word, a name the commit adds, by the first pilot's
    reading of its second rule, with no limit on how many files hold it and in any folder.

Counted on 2026-11-19 with no model: the rule removes between 1 and 7 files an item, 46 over the twelve
bases: the plan, and where they exist its design spec and the reviews and rechecks of either.

**What "removed" does not mean.** Other files may still mention the work: between 0 and 6 files an item
hold the slug or its words in their text and are kept. No kept Markdown file holds one of the item's new
names or has the slug in its name. Other plans, for other work, are all still there; that is the point
of the second question.

The maker proves for every item, before any turn: no base has a parent; the removed base's tree is
the present base's tree less exactly the files of the rule; within a base the rows differ by the task
file alone, byte for byte the same up to the last paragraph; and no object of a removed file is among
the objects a removed row's turn is given.

## 3. The rows

Twelve rows an item. A row is a base, a task and a last paragraph.

| Row | Base | Task | Last paragraph | Runs |
| --- | --- | --- | --- | --- |
| `present-nothing-1`, `present-nothing-2` | present | frozen | none | 2 |
| `present-may-1`, `present-may-2` | present | frozen | the line | 2 |
| `present-exists` | present | frozen | "There is a plan for this work in the repository." | 1 |
| `removed-nothing-1`, `removed-nothing-2` | removed | frozen | none | 2 |
| `removed-may-1`, `removed-may-2` | removed | frozen | the line | 2 |
| `removed-exists` | removed | frozen | "There is a plan for this work in the repository." | 1 |
| `message-nothing` | present | the commit's message | none | 1 |
| `message-may` | present | the commit's message | the line | 1 |

- **The line,** exactly: "There may be a plan for this work in the repository. Look for one before you
  change code." It names no folder and no file. One wording is tried; another might do otherwise.
- **`removed-exists` tells the turn something false.** It is there to see what a wrong assurance costs.
  No task asks a turn to believe it.
- **The commit's message as a task:** the message's bytes as the item list holds them, then the same
  fixed sentence as the frozen tasks have, then the last paragraph if any. A commit's message is written
  after the work by those who did it, in the plan's words. It may name the plan.
- A task file is otherwise as the first pilot's section 3 gives it.

## 4. The turns

Twelve items by twelve rows: 144 turns, one at a time, in one order over all rows by the first pilot's
hash with seed 20261120 and these rows' names. Worker, limits and pins as in the first pilot; the plan
pins both bases of every item, the removal set of every item with each removed file's blob, and every
script.

## 5. What is read from each turn

As the first pilot's section 6: the frozen cases passed, the cases that do not pass on the parent, the
room's verdict by replay, the outcomes with no score. A turn's change is judged on the item list's own
base, which holds the documents; only what the turn changed under the source directory is applied. So
the base a turn was given does not enter its judging.

From the walk, where "names" is all a walk can say:

- whether and when a step names a matching file (it cannot at a removed base, where none exists);
- **at every row, how many files under a `plans`, `specs` or `reviews` folder the walk names, and
  which;** at a removed base those are documents for other work;
- the second of the first step that names a file under the source directory;
- the turn's steps, its seconds and its tokens.

## 6. How it is read

Shares are of the frozen cases; every tally is given again on the cases that do not pass on the parent,
as in the first pilot.

For a base and an item, with two Nothing shares `n1`, `n2` and two shares under the line `m1`, `m2`:

- the baseline `b = (n1 + n2) / 2` and its gap `rn = |n1 - n2|`;
- the line's share `m = (m1 + m2) / 2`, its gap `rm = |m1 - m2|`, and `d = m - b`;
- the line is **higher** at the item when `d > max(rn, rm)`, **lower** when `d < -max(rn, rm)`, and
  otherwise within the observed gaps.

The single-run rows (`present-exists`, `removed-exists`) are read against their base's baseline with
its gap `rn` alone, as the first pilot read a row. The two `message` rows are one run each and are
given as counts beside each other; no class is read on them.

**Five questions, each answered with counts and no test:**

1. **Where the plan is there, does the line do what the cue did?** `present-may`: items higher, lower
   and within; in how many of its 24 turns the walk names a matching file; beside `present-exists` in
   this run and the first pilot's 11 of 12.
2. **Where the documents are gone, what does the line cost?** `removed-may` against `removed-nothing`:
   items lower; the mean seconds, steps and tokens of a turn; the second of the first source file
   named; how many of its 24 walks name a file under `plans`, `specs` or `reviews`, and which.
3. **What does a false assurance cost?** `removed-exists` against `removed-nothing`, the same counts.
4. **Does a turn with nothing added depend on the documents at all?** `removed-nothing` against
   `present-nothing`: frozen cases passed, item by item.
5. **How much of the first pilot's gap is the task's wording?** `message-nothing` against
   `present-nothing`, and `message-may` against `message-nothing`: frozen cases passed, item by item.

Beside these: the first pilot's rows at the same items (its two Nothing rows and its cue), as a look at
how much a cell moves between runs days apart. They are another day's turns, from bases that had a
history, and enter no class here.

**A rule for what to recommend, fixed here before any turn.** It is a heuristic of the lead's, chosen
after the first pilot's results were seen, and no protection against chance:

- **Recommend the line for the room's text before work** when `present-may` is higher at six or more of
  the twelve items and lower at one or none; and `removed-may` is lower at one or none; and the mean
  seconds of a `removed-may` turn are no more than 60 above a `removed-nothing` turn's.
- **Recommend against it** when `present-may` is higher at three or fewer, or `removed-may` is lower at
  four or more.
- **Between:** reported as that.

If a row the rule needs has no score, the rule is not applied and the report says so.

## 7. What is built

Changes to the three scripts of the first pilot, in place, each with tests and a mutant for every
condition added. The first pilot is judged and reported; its plan is not read by the changed scripts.

1. **The maker:** the removal rule and its set for each item; the second base and the proof of section
   2; the twelve rows and their paragraphs; the commit's message as a task; the order over 144.
2. **The runner:** unchanged but for what the tests show it needs. A row's base comes from the plan.
3. **The judge:** the rows; the readings of section 6 with two runs a cell; the walk's counts of
   section 5; the five questions' tables; the rule.

Before the plan is made, the lead runs the whole path on the real room with a stand-in script in the
worker's place, at a removed base and a present one, and the judge and report over those rows: the plan
pins the judge.

## 8. What it costs

144 turns at about 190 seconds: seven to eight hours of one machine. The judging about an hour and a
half.

## 9. What this narrows, said before any turn

- The same twelve items of six plans, seen before. One repository, one component, one worker program
  and model, one machine.
- The outcome is agreement with the reference's tests, as before: names, calls and wordings as well as
  behaviour. Nothing here judges a change as work.
- "Removed" is a tree with files deleted, in a repository with no history. Source comments, other
  documents and the code itself may still speak of the work.
- No base here has a history, and the first pilot's bases had. What a turn does with a history was not
  looked at in either pilot.
- One wording of the line. It names no folder; a line that did would be another condition.
- Two runs a cell where the rule reads, one elsewhere. Two runs give two gaps, not a measure of
  variation.
- A commit's message is not what a person who wants the work would write, and not what the frozen tasks
  are. The two `message` rows show the other end of the task's wording, not a middle.
- The first pilot's rows are another day's. Putting them beside these is a look, not a comparison.
