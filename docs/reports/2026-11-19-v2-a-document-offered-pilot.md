# v2: a document offered. The pilot's report

Serenity, 2026-11-19 (UTC). The pilot of `docs/superpowers/specs/2026-11-18-v2-a-document-offered.md`
(revision 4) was run on 2026-11-19 from 02:30 to 07:32 UTC and judged by 08:37 UTC. Not yet read by anyone but its writer.

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
- **A list of three files that "may bear on this work" did less, and only where the plan was on the
  list and the turn named it:** the three newest plans 195, the second search's three 278, the first
  search's three (which hold no matching file at any item) 153, three by lot 153.
- **With nothing, a turn's walk names the plan in 1 of 24 turns.** Told that a plan exists, with no
  path, it names the plan at 11 of 12 items, at its third or fourth step, 16 to 25 seconds in.
- **No condition is lower than nothing at any item.**

**What the score is.** It is agreement with the reference's own tests: names, calls and wordings as
well as behaviour. With nothing a turn does the work under names of its own, and those tests cannot see
it: at two items the test file cannot even be collected. The pilot does not show that such work is
worse. It shows that a turn does not look for a plan unasked, that it finds one within seconds when told
one exists, and that following it brings agreement with the reference.

## What was run

- **Items:** the twelve of the spec's section 2, of six plans. Each item's task is in a user's words,
  frozen before any search was run on it (`v2/probes/documents/tasks/`, hashes in `FROZEN.sha256`).
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
  interrupted or run again. A turn took 69 to 423 seconds, median 170; by condition the mean is 169
  to 199 seconds.
- **Load:** the machine was in other use. The one-minute load before a row ran from 2.7 to 34.2 on 16
  cores, median 9.9; ten rows began above 18. The rows run in one hashed order, so no condition sits in
  one stretch of it. The judging began at a five-minute load of 6.8 and ended at 12.4.
- **Judging:** every hand-in's change under the source directory was applied on the item's base in the
  jail and the frozen cases counted; the room then judged the change by replay with the item's own
  check. 96 of 96 rows have a score, and each row's counts add up to its frozen count.

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
  no work, and every row passes those 32 and no more. Neither item could show a difference.
- **027834bf and 3f349e89:** under Nothing (both runs), three by search, three newest plans and three
  by lot, no frozen case ran: the test file imports a name the change does not define, so it cannot be
  collected. Those ten rows score 0 of 64 and 0 of 95.
- **9a3f21cf:** in five rows (both Nothing rows, three by search, the second search, three by lot) one
  case that passes on the parent fails under the change. In the three rows whose walk names the plan it
  does not. One item, and the rows that did not name the plan: this is the changes, not the load.

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

Whether a step of the turn's walk names a matching plan, and at which step and second. A walk holds the
paths a step names and no command or output, so "names" is all that can be said. "Held" says the three
offered files include a matching file.

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

- **Of the 36 offering rows whose walk names a matching plan, 26 are higher. Of the 36 whose walk does
  not, 1 is higher** (71a593d5 under "a plan exists": 33 of 33 against 31 with nothing; its walk names no
  plan, and what it did instead a walk cannot say).
- **The 10 rows that name the plan and are not higher** are at 0193bde8 and d20c739b, which could show
  no difference, and at c9ceb15b and 1113f1db, where the difference is inside or near the baseline gap.
- **A list holds the plan more often than the turn names it.** The three newest plans hold a matching
  file at 12 of 12 items and the walk names it at 7. The second search's three hold one at 9 and the walk
  names it at 6. Where the list held the plan and the walk did not name it, the row scored as Nothing did.
- **"A plan exists" gives no path.** The walk first names the plan 16 to 25 seconds in. With the path
  given it is 9 to 22 seconds.

## What the rows show beside the rule

The rule read two conditions and answered "between". The other rows were set out in the spec as a
positive control (the path), an existence cue, and a draw by lot, with no conclusion fixed on them in
advance. What they show, as counts:

1. **The existence cue did as much as the path:** 8 and 9 items higher, 367 and 362 frozen cases.
2. **An offer that misses did nothing and cost nothing here.** Three by search and three by lot hold no
   matching file at any item; each passes 153 cases against Nothing's 151 and 154, and neither is lower
   at any item.
3. **The same sentence with three paths ("may bear on this work") worked only through the plan.** Where
   the plan was on the list and named, the row is as the path's row; elsewhere as Nothing's.

## What this is not

- **Not a judgement of the work.** The outcome is agreement with the reference's tests. The plans here
  give names, calls, exact assertions and test instructions; a turn that follows one writes what those
  tests look for. A Nothing turn's change passed the room's small check in all 24 rows, and whether it
  does the work under other names was not judged.
- **Not about work that has no plan.** Every item was chosen because a plan exists, found by the
  finished reference's new names. What a sentence saying "there is a plan" does where there is none, or
  what a standing instruction to look for one costs there, was not tried.
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
a plan no earlier walk named, and in this pilot 1 of 24 unprompted walks named one.

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
At these items the finder mattered less than the sentence: a turn told that a plan exists found it
without help, and a turn handed three paths with a weaker sentence opened the right one about half the
time. So the next question is not a better search. It is whether a standing instruction can stand in
for knowing that a plan exists:

- the instruction "look for a plan or spec for this work before you change code", given at every item;
- at items that have a plan and at items that have none, so that what it costs where there is nothing
  to find is measured beside what it gives;
- two runs a cell, so that the gap between repeated turns is seen more than once;
- with the outcome read two ways: agreement with the reference's tests, as here, and a check of
  behaviour that does not depend on the reference's names.

The last is the hard part, and this pilot does not solve it.

## Where the numbers come from

Beside this report, in `2026-11-19-v2-a-document-offered-pilot/`:

- `report.md` and `report.json`: the judge's own report, as generated.
- `rows.json`: one entry a row: when it ran, the load before it, how it ended, its steps and tokens,
  its counts over the frozen cases, the room's verdict, and whether and when its walk names a matching
  plan. Every table above was made from the judge's data by script and none was typed.

The rooms, the turns' repositories and the walks are kept on the machine that ran the pilot.
