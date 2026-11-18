# v2: a document offered. A pilot of the design's second arm

Serenity, 2026-11-18 (UTC). A spec, not yet read and not built. It changes no code of the room: the pilot
is run by scripts over the room as it is. It goes to a fresh reader of the other family before any turn.

## 1. What it is, and what it is not

The v2 design names its arms in order: nothing; notes found by ordinary search; whole walks; routes only
if walks beat notes. It says stage 2 can end the rail: "If no arm beats nothing, v2 is a room with checks
and a ledger." Nothing so far has beaten nothing. The rehearsal and three probes found no place where a
turn lacked something an offer could carry: a source file is named within seconds.

On 2026-11-18 one such place was found, and it is a document. The report
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

**This pilot asks one thing: at items that have a plan for their work, does an offer of documents move
how much of the held-back tests a turn's change passes, against nothing offered?** It is a pilot: twelve
items, each condition once, the first condition twice. It tests nothing for a difference and fixes no
size for an experiment. It says beforehand what it would take to be worth one.

It is not a test of walks or routes. The store of walks holds no way to a plan that no earlier walk
named, as its owner has said. What is offered here comes from the repository's own files.

## 2. The items

Twelve items of the item list the earlier probes used (its sha256 begins 4b25d330), chosen by rule before
any turn:

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

**Two things a reader settles before the list is frozen.** For each of the twelve, by reading the
document at the parent: that it is a plan or spec for this item's own work, and that it gives at least
one name, call, return or wording that the item's held-back tests use. An item that fails either is
dropped and not replaced. One of the twelve, 027834bf, has had probe turns; it stays, and its row is
marked.

**Using the seven scored items here spends nothing of the route experiment's:** no walk of this pilot
is put in any store, and no turn here is history for any other.

## 3. The task

Each item's task is written in a user's words, as the third probe's were: what is wanted and why, with no
file's name, no symbol, no test's name, and none of the plan's own title words or its task numbers. By
the lead's reading of the twelve subjects, eleven carry the plan's title words or a task number, so the
commit's message cannot be the task: it would hand the search its answer.

- The lead writes the twelve tasks from each commit's message and diff. A fresh reader of the other
  family checks each against the commit: does a person who reads only the task know what is wanted, and
  does the task give away a file, a symbol or the plan? Its changes are made before any turn.
- A task ends with the same sentence in every condition: "Make this change in the code under
  `peer/superyak_peer`. Add tests for it if you like."
- The base is the commit's true parent with the task file and one small check file laid over it, as in
  the earlier probes: the parent's own tests are there, and the item's new and changed tests are not.

## 4. The conditions

The only difference between conditions is one paragraph at the end of the task file.

| Condition | The paragraph |
| --- | --- |
| Nothing | None. Run twice for every item |
| A plan exists | "There is a plan for this work in the repository." No path |
| The plan's path | "The plan for this work is in the repository at" and the path of the matching file |
| Three by search | "These documents in the repository may bear on this work:" and three paths: the three Markdown files placed first by the task's words |
| Three newest plans | The same sentence and three paths: the three files under a `plans` folder whose names come last in order, which begin with the latest dates |
| Three by lot | The same sentence and three paths drawn by lot, with a fixed seed, from the files under `plans` and `specs` folders, leaving out every file that matches the item |

- **The search is fixed here.** A file's score is the number of different words of the task that it
  holds: words of four letters or more in lower case; a word held by over half the Markdown files at the
  parent counts nothing. Highest first; ties by path. It is the first row of the report's table, with
  the task in place of the commit's message.
- **Counted with no model before any turn, and reported whatever it is:** for each item, the place of
  the matching file under the search and under the newest plans. If the search places it in the first
  three at fewer than four of the twelve, the search's condition is run all the same, and is read as an
  offer of mostly wrong documents.
- A document is offered by its path alone. Nothing of its text is put in the task.

## 5. The turns

Twelve items by seven turns: 84 turns, one worker program and model, the one the probes used. The order
is drawn by lot before the first turn, by a hash of a fixed seed, the item and the condition, as the pass
orders its turns, and written down with the plan. Turns run one at a time. A turn that the room ends
without a hand-in is kept and reported as that; nothing is run a second time.

## 6. What is read from each turn

- **By replay, as the report describes it:** the turn's change under the source directory is applied on
  the item's own base by a script in the worker's place, and the room judges it in its jail with the
  item's frozen check. The room's verdict is kept.
- **By the in-jail diagnostic:** how many of the item's held-back tests pass, of how many, and what the
  failing ones print first. A turn's code runs only inside the jail.
- **From the walk:** whether a step names the matching document, at which step and second, and which
  offered documents it names. A walk holds the paths a step names and no command or output, so "named"
  is all that is said.
- **A control for every item before its turns:** the item's own reference through the replay and the
  diagnostic, which must pass.

## 7. What is reported, and what would count

For each item and condition: the share of held-back tests that pass. For Nothing, the mean of its two
turns, and beside it the difference between them, which is the pilot's only view of how much a repeat
alone moves.

Then, for each offering condition against Nothing: at how many of the twelve items the share is higher,
lower and the same, where "the same" is a difference no larger than that item's own difference between
its two Nothing turns. The counts are given by plan as well, since four items share one.

No test of a difference is made. Said beforehand, as the lead's judgement of what would be worth an
experiment with its own design and reader:

- **Worth one:** Three by search or Three newest plans is higher than Nothing at eight or more of twelve
  and lower at two or fewer, and Three by lot is lower than Nothing at three or fewer.
- **Not worth one:** neither is higher at more than five.
- **Between:** reported as that.

The plan's path is the most an offer of the right document could do here; A plan exists shows how much
of it is knowing that a plan is there. If the plan's path is not higher than Nothing at eight or more,
the hypothesis is weakened whatever the other conditions do.

## 8. What is built

No change to the room. Scripts beside the earlier probes' in `v2/probes/`, each with tests:

1. A maker of the pilot's plan: the items by the rule, the tasks, the six paragraphs for each item, the
   search's and the newest plans' places, the lot's draws, the order. Frozen in one file with its hash.
2. A runner: one turn at a time in the frozen order, each in a room of its own.
3. A judge: the control, the replay, the diagnostic and the walk's reading for each turn, and the
   report's tables.

The earlier probes' scripts did these by hand and are the starting point. One test runs the whole path
against the real room and its jail with a script named for the worker and no model, before any reader
sees the build.

## 9. What it costs

84 turns at about three minutes: over four hours of one machine, with nothing else heavy on it. The
judging is about 190 script turns in the jail with no model, about an hour.

## 10. What this narrows, said before any turn

- One repository, one component, one worker program and model, macOS. Twelve items of six plans.
- The held-back tests judge conformance to the reference's names, calls and wordings as well as
  behaviour. Where a plan gives those, that is a fair thing to ask of a turn that was shown the plan; it
  is still not a judgement of behaviour alone.
- Plans that contain their own tests are left out. They are 28 of the 40, so the twelve are the smaller
  kind, and what is seen here says nothing of the larger.
- The tasks are the lead's words. A person's own words may be further from the plan's, or nearer.
- The matching file is chosen by a word and confirmed by one reader.
- An offer is a paragraph in the task file. What the room's own offer block would do with documents is
  not tried.
- This repository's work goes from spec to plan to build, and its plans are kept. Where no plan is
  written, there is nothing here to offer.
