# v2: a document offered. The pilot's report

Serenity, 2026-11-19 (UTC). The pilot of `docs/superpowers/specs/2026-11-18-v2-a-document-offered.md`
(revision 4) was run on 2026-11-19 from 02:30 to 07:32 UTC and judged by 08:37 UTC. A fresh reader of
the other model family read it and recomputed its tables from the data beside it: approve with named
changes, nine, all made here and listed at the end.

## In short

Twelve items, each chosen because a plan for its work is already in the repository. Each item's task was
given to a Codex turn eight times: twice with nothing added, and once each with one of six paragraphs at
the task's end. One run a cell. The score is how many test cases, frozen from the reference's own tests,
pass under the turn's change.

- **The rule fixed before any turn says "between".** Of the two conditions it reads, three files by
  search are higher at 0 of 12 items and the three newest plans at 6 of 12 (the rule asked for 8, and for
  "not worth one" 5 or fewer). Three files by lot are lower at 0.
- **Told only "There is a plan for this work in the repository", a turn's change passed 367 of the 453
  frozen cases.** With nothing the two runs passed 151 and 154. Given the plan's path: 362.
- **A list of three files that "may bear on this work" passed fewer:** the three newest plans 195, the
  second search's three 278, the first search's three (which hold no matching file at any item) 153,
  three by lot 153. Every list row that is higher by the spec's reading is a row whose walk names a
  matching file.
- **With nothing, a turn's walk names a matching file in 1 of 24 turns.** Told that a plan exists, with
  no path, it names one at 11 of 12 items, at its third or fourth step, 15.7 to 25.0 seconds in.
- **No condition is lower at any item,** by the reading of the spec's section 7.

**What the score is.** It is agreement with the reference's own tests: names, calls and wordings as
well as behaviour. A change that names things otherwise than the reference can leave a test file
impossible to collect, and then none of its cases runs: that happened at two items, which hold 159 of
the 453 cases. What a Nothing turn's change does as work was not judged. So the pilot gives two counts
side by side, the naming of a matching file (1 of 24 turns against 11 of 12 items) and the frozen cases
passed, and it does not say how the one brings the other.

**And the tasks were made to withhold every name.** At the one item probed before this pilot, turns
whose task was the commit's own message passed 55 and 54 of its 64 cases with nothing added. Here, with
a task that gives no name, the two Nothing rows pass 0 of 64. The gap this pilot shows is of tasks that
do not carry the interface.

## What was run

- **Items:** the twelve of the spec's section 2, of six plans.
- **Tasks:** each item's task is in a user's words, but no user wrote it. A model wrote each from the
  finished reference, held to a list of the behaviours and limits the item's tests check and a list of
  what it must not give (every name, every message's words, every shape). Five readers checked them
  over three rounds; they were frozen before any search was run on them
  (`v2/probes/documents/tasks/`, hashes in `FROZEN.sha256`). How far such a task is from what a person
  would ask was not measured.
- **Conditions:** eight rows an item, differing only in one paragraph at the task's end, as the spec's
  section 4 gives them. The row "three by the second search" was added after its places were counted
  and before any turn; it is no part of the rule.
- **Order:** one order over the 96 rows by hash, fixed in the plan. The plan's sha256 is
  `1b48ee7bb10b5bf0e4131e43abdd6834e5041dcf7c79e58ed1c35e62513c2927`.
- **Worker:** `codex:gpt-6.1-sol`, codex-cli 0.163.0, a limit of 1,200 seconds a turn. The room and its
  jail as they are, on macOS; one turn at a time.
- **Controls, before any turn:** each item's reference in the jail: 453 frozen cases over the twelve
  items; 149 pass on the parent with no change and 304 do not. The same case lists came out of four full
  runs of the controls, each on a different build of the judge; the pilot's own was the fourth.
- **Turns:** 96 of 96 recorded, each a hand-in. None reached its limit, no export failed, none was
  interrupted or run again. A turn took 69 to 423 seconds, median 168; by condition the mean is 169
  to 199 seconds.
- **Load:** the machine was in other use. The one-minute load before a row ran from 2.7 to 34.2 on 16
  cores, median 9.8; ten rows began above 18. The rows run in one hashed order, so no condition sits in
  one stretch of it. The judging began at a five-minute load of 6.8 and ended at 12.4.
- **Judging:** every hand-in's change under the source directory was applied on the item's base in the
  jail and the frozen cases counted; the room then judged the change by replay with the item's own
  check. 96 of 96 rows have a score, and each row's counts add up to its frozen count.
- **The room's small check on each turn** passes when anything under the source directory differs from
  the parent. All 96 turns passed it. It says nothing of the work.

## Each item

Frozen cases that pass under the turn's change. "Higher" is the spec's reading: the row's share is above
the mean of the two Nothing rows by more than the gap between them.

| Item | Plan | Frozen cases | Pass on the parent | Nothing, first | Nothing, second | A plan exists | The plan's path | Three by search | Three by the second search | Three newest plans | Three by lot |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 9a3f21cf | chat-paging | 8 | 3 | 2 | 2 | 8 **higher** | 8 **higher** | 2 | 2 | 8 **higher** | 2 |
| 71a593d5 | public-route | 33 | 31 | 31 | 31 | 33 **higher** | 33 **higher** | 31 | 33 **higher** | 33 **higher** | 31 |
| d20c739b | public-route | 34 | 32 | 32 | 32 | 32 | 32 | 32 | 32 | 32 | 32 |
| cd884db7 | pairing-code | 22 | 7 | 7 | 10 | 22 **higher** | 22 **higher** | 10 | 22 **higher** | 22 **higher** | 10 |
| c9ceb15b | federation-pull | 27 | 23 | 26 | 25 | 26 | 26 | 25 | 26 | 26 | 25 |
| 671a2250 | federation-pull | 10 | 0 | 0 | 0 | 7 **higher** | 6 **higher** | 0 | 0 | 6 **higher** | 0 |
| 1113f1db | federation-pull | 42 | 15 | 15 | 16 | 16 | 17 **higher** | 15 | 16 | 17 **higher** | 15 |
| 0193bde8 | federation-pull | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fff1b349 | owner-trust | 42 | 23 | 23 | 23 | 39 **higher** | 35 **higher** | 23 | 23 | 36 **higher** | 23 |
| 027834bf (probed) | owner-trust | 64 | 0 | 0 | 0 | 62 **higher** | 61 **higher** | 0 | 61 **higher** | 0 | 0 |
| 3879e609 | owner-trust | 74 | 15 | 15 | 15 | 74 **higher** | 74 **higher** | 15 | 15 | 15 | 15 |
| 3f349e89 | ship-home-and-crossing | 95 | 0 | 0 | 0 | 48 **higher** | 48 **higher** | 0 | 48 **higher** | 0 | 0 |
| **All twelve** | | **453** | **149** | **151** | **154** | **367** | **362** | **153** | **278** | **195** | **153** |

Three things to know when reading this table:

- **0193bde8** has two frozen cases and no row passes either. **d20c739b** has 34, of which 32 pass with
  no work, and every row passes those 32 and no more. Neither item showed a difference.
- **027834bf and 3f349e89:** under Nothing (both runs), three by search, three newest plans and three
  by lot, no frozen case ran: the test file imports a name the change does not define, so it cannot be
  collected. Those ten rows score 0 of 64 and 0 of 95. The two items hold 159 of the 453 frozen cases
  and 159 of the 304 that do not pass on the parent; the table after the next shows the totals with
  and without them.
- **9a3f21cf:** in five rows (both Nothing rows, three by search, the second search, three by lot) one
  case that passes on the parent fails under the change. In the three rows whose walk names a matching
  file it does not. That is what the rows show. Why it is so was not looked into, and the load on the
  machine while a row was judged was not recorded row by row.

## By condition

| Condition | Items higher | lower | within | Plans higher, of 6 | Equal-plan figure | Frozen cases passed, of 453 | Cases new to the parent passed, of 304 | The room's verdict by replay true, of 12 | Walk names a matching plan, of 12 items |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Nothing, first | | | | | | 151 | 3 | 0 | 1 |
| Nothing, second | | | | | | 154 | 6 | 0 | 0 |
| A plan exists | 8 | 0 | 4 | 6 | +0.466 | 367 | 218 | 4 | 11 |
| The plan's path | 9 | 0 | 3 | 6 | +0.457 | 362 | 213 | 4 | 12 |
| Three by search | 0 | 0 | 12 | 0 | +0.010 | 153 | 5 | 0 | 0 |
| Three by the second search | 4 | 0 | 8 | 4 | +0.246 | 278 | 130 | 2 | 6 |
| Three newest plans | 6 | 0 | 6 | 5 | +0.277 | 195 | 46 | 3 | 7 |
| Three by lot | 0 | 0 | 12 | 0 | +0.010 | 153 | 5 | 0 | 0 |

The equal-plan figure is the mean, over the six plans, of the plan's mean difference from its baseline,
in share of frozen cases. The same tallies come out when the shares are taken over the cases that do not
pass on the parent, and without the item that had been probed before (027834bf): a plan exists 7 of 11
items higher, the path 8, three newest plans 6, the second search 3, search 0, lot 0.

**How much of each total rests on the two items whose test file could not be collected** under five
conditions. They hold 35.1% of the frozen cases and 52.3% of those that do not pass on the parent:

| Condition | Passed at 027834bf and 3f349e89, of 159 | Passed at the other ten items, of 294 |
| --- | --- | --- |
| Nothing, first | 0 | 151 |
| Nothing, second | 0 | 154 |
| A plan exists | 110 | 257 |
| The plan's path | 109 | 253 |
| Three by search | 0 | 153 |
| Three by the second search | 109 | 169 |
| Three newest plans | 0 | 195 |
| Three by lot | 0 | 153 |

**By plan,** the mean difference of the plan's items, with "higher" where it is above the plan's mean
gap:

| Plan | Items | A plan exists | The plan's path | Three by search | Three by the second search | Three newest plans | Three by lot |
| --- | --- | --- | --- | --- | --- | --- | --- |
| chat-paging | 1 | +0.750 **higher** | +0.750 **higher** | +0.000 | +0.000 | +0.750 **higher** | +0.000 |
| pairing-code | 1 | +0.614 **higher** | +0.614 **higher** | +0.068 | +0.614 **higher** | +0.614 **higher** | +0.068 |
| public-route | 2 | +0.030 **higher** | +0.030 **higher** | +0.000 | +0.030 **higher** | +0.030 **higher** | +0.000 |
| federation-pull | 4 | +0.183 **higher** | +0.164 **higher** | -0.008 | +0.008 | +0.164 **higher** | -0.008 |
| owner-trust | 3 | +0.716 **higher** | +0.679 **higher** | +0.000 | +0.318 **higher** | +0.103 **higher** | +0.000 |
| ship-home-and-crossing | 1 | +0.505 **higher** | +0.505 **higher** | +0.000 | +0.505 **higher** | +0.000 | +0.000 |

## The walks

Whether a step of the turn's walk names a matching file, and at which step and second. A walk holds the
paths a step names and no command or output, so "names" is all that can be said: not that a file was
opened, read or followed. A matching file is the item's plan or, at two items, also its design spec; the
data beside this report does not say which of the two was named. "Held" says the three offered files
include a matching file. Seconds in the table are cut to whole seconds.

| Item | Nothing, first | Nothing, second | A plan exists | The plan's path | Three by search | Three by the second search | Three newest plans | Three by lot |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 9a3f21cf | no | no | step 3, 20 s | step 2, 12 s | no (not held) | no (not held) | step 2, 14 s (held) | no (not held) |
| 71a593d5 | no | no | no | step 2, 14 s | no (not held) | step 4, 21 s (held) | step 3, 17 s (held) | no (not held) |
| d20c739b | no | no | step 4, 24 s | step 4, 21 s | no (not held) | no (not held) | no (held) | no (not held) |
| cd884db7 | no | no | step 3, 18 s | step 1, 9 s | no (not held) | step 2, 12 s (held) | step 2, 13 s (held) | no (not held) |
| c9ceb15b | step 6, 27 s | no | step 3, 15 s | step 2, 12 s | no (not held) | step 2, 10 s (held) | step 2, 17 s (held) | no (not held) |
| 671a2250 | no | no | step 4, 23 s | step 2, 15 s | no (not held) | no (held) | step 3, 20 s (held) | no (not held) |
| 1113f1db | no | no | step 3, 16 s | step 2, 13 s | no (not held) | step 5, 26 s (held) | step 5, 24 s (held) | no (not held) |
| 0193bde8 | no | no | step 4, 20 s | step 2, 12 s | no (not held) | no (not held) | no (held) | no (not held) |
| fff1b349 | no | no | step 4, 19 s | step 2, 12 s | no (not held) | no (held) | step 3, 17 s (held) | no (not held) |
| 027834bf | no | no | step 3, 17 s | step 2, 12 s | no (not held) | step 5, 23 s (held) | no (held) | no (not held) |
| 3879e609 | no | no | step 3, 20 s | step 2, 14 s | no (not held) | no (held) | no (held) | no (not held) |
| 3f349e89 | no | no | step 4, 22 s | step 2, 17 s | no (not held) | step 4, 22 s (held) | no (held) | no (not held) |

- **Of the 36 offering rows whose walk names a matching file, 26 are higher. Of the 36 whose walk does
  not, 1 is higher** (71a593d5 under "a plan exists": 33 of 33 against 31 with nothing; its walk names no
  matching file, and what it did instead a walk cannot say).
- **The 10 rows that name one and are not higher** are at 0193bde8 and d20c739b, which showed no
  difference in any row, and at c9ceb15b and 1113f1db, where the difference is inside the baseline gap.
- **A list holds a matching file more often than the walk names it.** The three newest plans hold one
  at 12 of 12 items and the walk names it at 7. The second search's three hold one at 9 and the walk
  names it at 6. In the eight rows where the list held one and the walk did not name it, the row passed
  what the item's Nothing rows passed.
- **"A plan exists" gives no path.** The walk first names a matching file 15.7 to 25.0 seconds in. With
  the path given it is 9.2 to 21.6 seconds.

## What the rows show beside the rule

The rule read two conditions, with the draw by lot as its guard (lower at three items or fewer), and
answered "between". The path and the existence cue were set out in the spec as a positive control and a
cue, with no conclusion fixed on either in advance. What the rows show, as counts:

1. **The existence cue and the path:** 8 and 9 items higher, 367 and 362 frozen cases. With one run a
   cell that is one item and five cases apart; a second run could move either by as much.
2. **Search and lot were within the observed baseline gap at all twelve items.** Each holds no matching
   file at any item and passes 153 cases against Nothing's 151 and 154. Time and tokens were not
   compared.
3. **All ten higher rows among the four list conditions name a matching file;** three of the thirteen
   list rows that name one are within the baseline gap.

## What this is not

- **Not a judgement of the work.** The outcome is agreement with the reference's tests. The plans here
  give names, calls, exact assertions and test instructions; a turn that follows one writes what those
  tests look for. A Nothing turn's change passed the room's small check in all 24 rows, which says
  only that it changed something under the source directory. Whether it does the work was not judged.
- **Not what a task that carries the names would show.** At 027834bf, turns of the earlier probes whose
  task was the commit's own message passed 55 and 54 of 64 with nothing added, and 61 with the plan's
  path (`docs/reports/2026-11-17-v2-the-whole-stack-tested.md`, its second and fourth probes). Here the
  two Nothing rows pass 0 of 64 and the path's row 61. With a task that carried the names the gap at
  that item was 6 or 7 cases; with one that withholds them it is 61. One item, one or two turns a cell
  in each. The writer added this point after the report's read; no reader has checked it.
- **Not about work that has no plan.** Every item was chosen because a plan exists, found by the
  finished reference's new names. What a sentence saying "there is a plan" does where there is none, or
  what a standing instruction to look for one costs there, was not tried.
- **Not a comparison of the existence cue with the path.** They are one item and five cases apart on
  one run each.
- **Not a measure of variation.** One run a cell. The two Nothing rows differ at 3 of 12 items, by 1 to
  3 cases; that is one observed gap an item, not an estimate.
- **Not a test of a difference.** Nothing here is tested for chance. Twelve items of six plans; four
  items share one plan and three another.
- **Not a test of walks or routes,** as the spec says: what is offered comes from the repository's files.
- **A score can be forged** by a change written to do so: the cases run in the turn's own process inside
  the jail. No task asks for that. The room's verdict by replay stands beside the scores: true in 13 of
  96 rows (a plan exists 4, the path 4, three newest plans 3, the second search 2), and in none of the
  48 rows of Nothing, search and lot. It is one more observation and does not vouch for a score.
- **The second search was chosen on these twelve items,** after four orderings were compared. Its row is
  an added look.
- **One repository, one component, one worker program and model, one machine, in other use.**

## A count by another ship, cited and not restated

Tardis counted where the places taken from 74 walks put a matching document for the 52 items of the
earlier report: "74 walks and 222 places. Of the 52 items, 43 are absent, 0 fall within 16, and 9 fall
beyond 16." Its script and output are at commit 157239a0 of the branch `tardis/v2-places`:
`docs/superpowers/specs/2026-11-17-v2-places-not-routes-measure/plan_rank.py` and `plan_rank-output.txt`
beside it. That count is Tardis's. It bears on this report in one way: a store of walks does not lead to
a plan no earlier walk named, and in this pilot 1 of 24 walks with nothing added named a matching file.

## What was found on the way

Running the built scripts on the real room before the pilot found two faults that the unit tests, their
mutants and the build's two readers had not, because every stand-in answered as its builder guessed:

- The room never gives an item to a worker of the family that wrote it. The runner wrote each item as a
  script's, so with a script in the worker's place no turn started. A Codex worker's rows would have.
- The room records the base's own commit for a turn stopped at its limit with nothing handed in, so
  such a turn was labelled "no hand-in".

The judge's reader found two inputs that were scored and should not have been: a diagnostic stopped at
its limit after it had committed, and a report holding one forbidden character, read as empty. All four
were mended before the pilot's plan was made. The plan pins the hash of every script, so the judge had
to be right before the first turn; it was run on real rows with a stand-in worker first.

## What I would do next

**This section is my judgement.** The design's second arm asked which notes, found how, help a turn.
At these items a walk named a matching file at 11 of 12 when the turn was told a plan exists and given
no path, and at 13 of the 21 rows where a list of three held one. My hypothesis from that, which the
pilot does not test, is that the sentence matters more than the finder: that what a turn lacks is not a
way to the plan but a reason to look. A deployed room cannot say "a plan exists" without knowing; it can
say "one may exist". Tardis put the same point in the room, and the doubt that the cue and the path
cannot be told apart on one run. Whether a standing instruction does what the cue did here is not
known. So the next question I would ask is not a better search:

- the instruction "look for a plan or spec for this work before you change code", given at every item;
- at items that have a plan and at items that have none, so that what it costs where there is nothing
  to find is measured beside what it gives;
- two runs a cell, so that the gap between repeated turns is seen more than once;
- with the outcome read two ways: agreement with the reference's tests, as here, and a check of
  behaviour that does not depend on the reference's names.

The last is the hard part, and this pilot does not solve it.

## What the report's reader named, and where it is answered

A fresh reader of the other family (the team's w121) read this report at 648c7ba6 and recomputed its
four tables, every item's baseline, gap, difference and class, the tallies and figures in both readings
and without the probed item, and the walk counts, from the two data files: approve with named changes.

| Its change | Where |
| --- | --- |
| 1. Keep the claims about work and walks within what was observed; "names", not "opens" or "follows"; "matching file" throughout | In short; The walks; What I would do next |
| 2. Show the weight of the two items whose test file could not be collected | By condition, the second table |
| 3. No mechanism claimed for the lists; the two exceptions to "as the path's row" | What the rows show beside the rule |
| 4. No "did as much" and no "cost nothing" | What the rows show beside the rule; What this is not |
| 5. The tasks are a model's, written from the finished reference | What was run |
| 6. Load not ruled out at 9a3f21cf | Each item |
| 7. "Showed no difference", not "could show none" | Each item; The walks |
| 8. The lot is the rule's guard, not a row with no conclusion fixed | What the rows show beside the rule |
| 9. Medians corrected (168 seconds, load 9.8); one convention for seconds | What was run; The walks |

What that reader could not check, in its words: "`rows.json` against the actual changes, walks, room
records or test output". Those are on the machine that ran the pilot.

## Where the numbers come from

Beside this report, in `2026-11-19-v2-a-document-offered-pilot/`:

- `report.md` and `report.json`: the judge's own report, as generated.
- `rows.json`: one entry a row: when it ran, the load before it, how it ended, its steps and tokens,
  its counts over the frozen cases, the room's verdict, and whether and when its walk names a matching
  plan. Every table above was made from the judge's data by script and none was typed.

The rooms, the turns' repositories and the walks are kept on the machine that ran the pilot.
