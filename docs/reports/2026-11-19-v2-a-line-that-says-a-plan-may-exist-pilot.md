# v2: a line that says a plan may exist. The pilot's report

Serenity, 2026-11-19 (UTC). The pilot of
`docs/superpowers/specs/2026-11-19-v2-a-line-that-says-a-plan-may-exist.md` (revision 3): its turns ran from
2026-11-19 12:22:41 UTC to 2026-11-19 15:11:48 UTC, and its judging from 15:11:48 to 15:52:37 UTC the same
day. Not yet read by a fresh reader.

## In short

The first pilot found that a turn told "There is a plan for this work in the repository" finds the plan and
follows it. That sentence can only be said by someone who knows a plan exists. This pilot asks what a line
does that anyone could put at the end of every task: "There may be a plan for this work in the repository.
Look for one before you change code." It was tried where a plan is known and where a reader found none.

- **The rule fixed before any turn says "worth a larger trial".** It reads twelve items no model turn had
  touched. Where a reader had confirmed a plan (pool P), the line is higher than nothing at 4 of 6 items and
  lower at 0. Where a reader's review found no plan (pool N), it is lower at 0 of 6. The rule says only
  whether a larger trial is worth running.
- **Where a plan exists, the line did what "There is a plan" did.** In pool P nothing's two runs passed 82
  and 94 of 113 frozen cases and the line's two 111 and 112. At the first pilot's twelve items (part A, a
  look only) the line's two runs passed 316 and 363 of 453; "There is a plan" passed 367 there and nothing
  151 and 154.
- **Under the line a turn's walk names the plan every time one is known:** 24 of 24 turns in part A and 12
  of 12 in pool P.
- **Where no plan was found, the line changed no score.** At 6 of pool N's 6 items, every row whose change
  was taken passes the same number of cases, with the line or without. At 3 of them both Nothing rows
  already pass every case, so there the line could not have shown a gain; what the six show is no loss.
- **What it cost there.** In pool N a turn under the line took 126.5 seconds of the worker's time against
  97.3 with nothing: more at 6 of 6 items, 29.2 seconds a turn in the mean, with 3.2 more steps and 9,439
  more tokens. In pool P the line's turns were shorter at 5 of 6 items.
- **One hand-in was refused by the room:** a Nothing row at a pool N item. By the spec it is scored as its
  parent. That one row raises pool N's mean difference from 0.000 to 0.083. The rule reads the same with it
  and without it.

**What the score is.** It is agreement with the reference's own tests: names, calls and wordings as well as
behaviour. It does not say a change is better work. In part B the task is the commit's own message, which is
more than a user's words would give: at 5 of pool P's 6 items it cites a task or a step of the plan.

## What was run

- **The line,** added at a task's end as its last paragraph: "There may be a plan for this work in the
  repository. Look for one before you change code." It names no folder and no file.
- **Part A, a look only:** the first pilot's twelve items with their frozen tasks, the line twice at each:
  24 turns. These items are seen: earlier turns at them shaped this design. They enter no class and no rule.
- **Part B, the measurement:** twelve items at which no turn with a model worker had been run. Six are of
  pool P, where a reader read the matching files and confirmed a plan for the work; six are of pool N, where
  a reader's recorded review of the Markdown files tracked at the item's first parent found no document that
  specifies the work. "None found by this review" is all pool N says. At each item: nothing added twice and
  the line twice, 48 turns. The task is the commit's own message, whole.
- **How the twelve were chosen:** two hashed orders, one a pool, fixed in the spec before any reader saw an
  item. A reader walked each order and wrote a record: in pool P 12 walked and 12 accepted; in pool N 34
  walked and 9 accepted, and at 20 of the 25 skipped it found a document that specifies the work. Controls
  were then run at all 33 candidates, and one walk in the maker took the first six of each pool that the
  spec's conditions allow. The records and orders are in `v2/probes/documents/selection/`.
- **Order:** one order over the 72 rows by hash, fixed in the plan. The plan's sha256 is
  `5893a5e836c0df019320f76a7181ec31a1996aa927ef5ea983e7280f54de960a`.
- **Worker:** `codex:gpt-6.1-sol`, codex-cli 0.163.0, a limit of 1,200 seconds a turn. The room and its jail
  as they are, on macOS; one turn at a time. The worker, the pinned programs, the limits and the environment
  are the first pilot's, compared plan against plan.
- **Controls, before any turn:** each candidate's reference in the jail. All 33 stand. Part A's twelve give
  the first pilot's own counts again. Part B's frozen cases: pool P 113, of which 59 do not pass on the
  parent; pool N 309, of which 113 do not.
- **A rehearsal first:** the whole path (plan, 72 rows, both judges, the report) was run on the real room
  with a stand-in worker whose change has no effect. Every score came out the parent's own, every difference
  zero and the rule "between", as it must.
- **Turns:** 72 of 72 recorded. 71 are hand-ins and one is a hand-in the room refused (the next section).
  Rows that reached their limit: 0. Rows run again after an interruption: 0. No export failed. From a row's
  start to its end took 51 to 376 seconds, median 122.5. The worker's own time, which the tables below use,
  ran from 46 to 372 seconds, median 118.8.
- **Load:** the one-minute load before a row ran from 1.8 to 12.5 on 16 cores, median 5.1; 0 rows began
  above 18. The judging began at a five-minute load of 5.7 and ended at 15.2.
- **Judging:** as in the first pilot: every hand-in's change under the source directory applied on the
  item's base in the jail and the frozen cases counted; then the room's own verdict by replay. 72 of 72 rows
  have a score and each row's counts add up to its frozen count. At 3 rows the test file could not be
  collected, so no frozen case ran (2ebc78e1, nothing 1; 3f349e89, the line 1; 6ba4650f, nothing 1).

## Row 056: a hand-in the room refused

- **What happened.** Row 056 is a Nothing row at 2ebc78e1, the pool N item with the most room (none of its
  89 frozen cases pass on the parent). The worker ran 120 seconds and 13 steps, as its sibling rows did. The
  room then refused the hand-in: "the work tree must contain a single repository". The room commits for a
  Codex worker, and refuses to when anything named `.git` lies below the top of the work tree. It recorded
  the base's own commit, so the runner's record says "no hand-in", and the change is gone: the room keeps no
  work tree of a failed turn.
- **How rare.** By each turn's clock log: this row of the pilot's 72, and none of the first pilot's 96.
- **What made the second repository is not known.** A walk holds the paths a step names and no command. This
  walk names 13 paths, all tracked at the base. Three of its steps name no path. Tests elsewhere in that
  suite make repositories under pytest's temporary directory, which the room puts outside the work tree; so
  the candidates are a wider run of the suite with its temporary directory moved inside the tree, or a
  repository the worker made itself. Neither was tested. (Tardis found the tests that make repositories,
  after I had written that there were none.)
- **What the spec says.** Every scheduled row is kept, a turn with no hand-in is scored as its base, and a
  row with a record is never run again. So the row is in every table as recorded, marked `*`, at 0 of 89.
- **Which way it tilts, written and posted before any score was read:** it lowers that item's baseline, so
  it raises pool N's mean difference, toward "worth a larger trial".
- **The rule three ways.** The second and third lines are outside the rule: an added look, fixed before the
  scores, made with the judge's own functions.

| reading | pool N's mean difference | on items | the rule |
| --- | --- | --- | --- |
| as the rule reads | 0.083 | 6 | worth a larger trial |
| that item's Nothing pair taken from its one taken row | 0.000 | 6 | worth a larger trial |
| that item left out | 0.000 | 5 | worth a larger trial |

- **One added turn, after the pilot and outside its plan.** The same cell (2ebc78e1, nothing added) was run
  once more in a directory of its own, from the same plan. It was handed in and passes 89 of 89, as the
  item's other three taken rows do. It enters no table and no rule. It is one turn; it agrees with the zero
  at row 056 being the refusal's and not the item's.

## Part B, each item

Frozen cases that pass under the turn's change. `d` is the mean share of the line's two rows less the mean
share of nothing's two. An item is "higher" or "lower" when `d` is beyond the larger of the two gaps between
repeated rows, and "within" otherwise. `*` marks the refused row.

| item | pool | plan group | cases | pass on the parent | nothing 1 | nothing 2 | the line 1 | the line 2 | d | class |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2ebc78e1 | N | - | 89 | 0 | 0* | 89 | 89 | 89 | +0.500 | within |
| 426ad7fb | N | - | 133 | 117 | 133 | 133 | 133 | 133 | +0.000 | within |
| 603434cf | N | - | 23 | 20 | 22 | 22 | 22 | 22 | +0.000 | within |
| 82bff0db | N | - | 22 | 20 | 22 | 22 | 22 | 22 | +0.000 | within |
| 906b3f73 | N | - | 35 | 33 | 33 | 33 | 33 | 33 | +0.000 | within |
| edec7384 | N | - | 7 | 6 | 7 | 7 | 7 | 7 | +0.000 | within |
| 383c5443 | P | ds9-station | 18 | 15 | 15 | 15 | 18 | 18 | +0.167 | higher |
| 4971bdb3 | P | ship-status-and-claims | 20 | 0 | 20 | 20 | 20 | 20 | +0.000 | within |
| 6ba4650f | P | lessons-room-adds | 21 | 0 | 0 | 13 | 20 | 20 | +0.643 | higher |
| b50b2c10 | P | station-backups-alerts | 25 | 19 | 22 | 23 | 24 | 25 | +0.080 | higher |
| c42ee1f4 | P | ship-status-and-claims | 15 | 11 | 15 | 13 | 15 | 15 | +0.067 | within |
| ca2d0d80 | P | station-backups-alerts | 14 | 9 | 10 | 10 | 14 | 14 | +0.286 | higher |

- **Pool N:** apart from the refused row, the four rows of an item pass the same number at every item.
  426ad7fb, 82bff0db and edec7384 pass every case in every row. At 906b3f73 no row passes a case that does
  not already pass on the parent.
- **Pool P:** 4971bdb3 passes every case in every row. At the other five the line's rows pass as many as the
  better Nothing row or more; no row under the line passes fewer cases than a taken Nothing row at its item
  (0 of 12 items).
- **6ba4650f, nothing 1:** the test file could not be collected, so that row is 0 of 21. Its walk names the
  plan. The other Nothing row, whose walk does not, passes 13.

**The pools, as the rule reads them** (shares of all frozen cases):

| pool | mean d | items higher | lower | within | mean over plan groups |
| --- | --- | --- | --- | --- | --- |
| P, a plan confirmed | 0.207 | 4 | 0 | 2 | 0.256 (on 4 groups) |
| N, none found by the review | 0.083 | 0 | 0 | 6 | - |

The rule: "worth a larger trial" when pool P's mean and its mean over plan groups are above zero with at
least one item higher, and pool N's mean is not below zero with no item lower. All five hold.

In all, over all frozen cases: in pool P nothing's two runs pass 82 and 94 of 113 and the line's two 111 and
112. In pool N nothing's two pass 217 (with the refused row's 0 of 89) and 306 of 309, and the line's two
306 and 306.

**The same on the cases that do not pass on the parent** (the rule does not read these):

| item | pool | plan group | cases not passing on the parent | nothing 1 | nothing 2 | the line 1 | the line 2 | d | class |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2ebc78e1 | N | - | 89 | 0* | 89 | 89 | 89 | +0.500 | within |
| 426ad7fb | N | - | 16 | 16 | 16 | 16 | 16 | +0.000 | within |
| 603434cf | N | - | 3 | 2 | 2 | 2 | 2 | +0.000 | within |
| 82bff0db | N | - | 2 | 2 | 2 | 2 | 2 | +0.000 | within |
| 906b3f73 | N | - | 2 | 0 | 0 | 0 | 0 | +0.000 | within |
| edec7384 | N | - | 1 | 1 | 1 | 1 | 1 | +0.000 | within |
| 383c5443 | P | ds9-station | 3 | 0 | 0 | 3 | 3 | +1.000 | higher |
| 4971bdb3 | P | ship-status-and-claims | 20 | 20 | 20 | 20 | 20 | +0.000 | within |
| 6ba4650f | P | lessons-room-adds | 21 | 0 | 13 | 20 | 20 | +0.643 | higher |
| b50b2c10 | P | station-backups-alerts | 6 | 3 | 5 | 6 | 6 | +0.333 | within |
| c42ee1f4 | P | ship-status-and-claims | 4 | 4 | 2 | 4 | 4 | +0.250 | within |
| ca2d0d80 | P | station-backups-alerts | 5 | 1 | 1 | 5 | 5 | +0.800 | higher |

On these cases pool P's mean d is 0.504 with 3 items higher and 0 lower; pool N's is 0.083 with 0 lower. In
all, of pool P's 59 such cases nothing's two runs passed 28 and 41 and the line's two 58 and 58.

## Part A, beside the first pilot's rows

The first pilot's eight rows at its twelve items, read from its own `rows.json`, and the line's two runs at
the same items. One run a cell in the first pilot; two here. No class and no rule.

| item | cases | nothing 1 | nothing 2 | a plan exists | the path | three by search | the second search | three newest plans | three by lot | the line 1 | the line 2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0193bde8 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 027834bf | 64 | 0 | 0 | 62 | 61 | 0 | 61 | 0 | 0 | 61 | 61 |
| 1113f1db | 42 | 15 | 16 | 16 | 17 | 15 | 16 | 17 | 15 | 17 | 16 |
| 3879e609 | 74 | 15 | 15 | 74 | 74 | 15 | 15 | 15 | 15 | 74 | 74 |
| 3f349e89 | 95 | 0 | 0 | 48 | 48 | 0 | 48 | 0 | 0 | 0 | 48 |
| 671a2250 | 10 | 0 | 0 | 7 | 6 | 0 | 0 | 6 | 0 | 7 | 6 |
| 71a593d5 | 33 | 31 | 31 | 33 | 33 | 31 | 33 | 33 | 31 | 33 | 33 |
| 9a3f21cf | 8 | 2 | 2 | 8 | 8 | 2 | 2 | 8 | 2 | 8 | 8 |
| c9ceb15b | 27 | 26 | 25 | 26 | 26 | 25 | 26 | 26 | 25 | 26 | 26 |
| cd884db7 | 22 | 7 | 10 | 22 | 22 | 10 | 22 | 22 | 10 | 22 | 22 |
| d20c739b | 34 | 32 | 32 | 32 | 32 | 32 | 32 | 32 | 32 | 32 | 32 |
| fff1b349 | 42 | 23 | 23 | 39 | 35 | 23 | 23 | 36 | 23 | 36 | 37 |
| **all twelve** | 453 | 151 | 154 | 367 | 362 | 153 | 278 | 195 | 153 | 316 | 363 |

On the cases that do not pass on the parent:

| item | cases not passing on the parent | nothing 1 | nothing 2 | a plan exists | the path | three by search | the second search | three newest plans | three by lot | the line 1 | the line 2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0193bde8 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 027834bf | 64 | 0 | 0 | 62 | 61 | 0 | 61 | 0 | 0 | 61 | 61 |
| 1113f1db | 27 | 0 | 1 | 1 | 2 | 0 | 1 | 2 | 0 | 2 | 1 |
| 3879e609 | 59 | 0 | 0 | 59 | 59 | 0 | 0 | 0 | 0 | 59 | 59 |
| 3f349e89 | 95 | 0 | 0 | 48 | 48 | 0 | 48 | 0 | 0 | 0 | 48 |
| 671a2250 | 10 | 0 | 0 | 7 | 6 | 0 | 0 | 6 | 0 | 7 | 6 |
| 71a593d5 | 2 | 0 | 0 | 2 | 2 | 0 | 2 | 2 | 0 | 2 | 2 |
| 9a3f21cf | 5 | 0 | 0 | 5 | 5 | 0 | 0 | 5 | 0 | 5 | 5 |
| c9ceb15b | 4 | 3 | 2 | 3 | 3 | 2 | 3 | 3 | 2 | 3 | 3 |
| cd884db7 | 15 | 0 | 3 | 15 | 15 | 3 | 15 | 15 | 3 | 15 | 15 |
| d20c739b | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fff1b349 | 19 | 0 | 0 | 16 | 12 | 0 | 0 | 13 | 0 | 13 | 14 |
| **all twelve** | 304 | 3 | 6 | 218 | 213 | 5 | 130 | 46 | 5 | 167 | 214 |

- The line's two runs are within one case of each other at 11 of 12 items. The twelfth is 3f349e89: in the
  line's first run the walk names the plan and the test file still could not be collected, so the row scores
  as nothing did there; its second run scores as "There is a plan" did.
- The walk names a matching plan in 24 of 24 of the line's turns here. Under "There is a plan" the first
  pilot's walks named one at 11 of 12 items; with nothing, in 1 of 24 turns.

## The walks

Whether a step of the turn's walk names a file that matches the item's plan, which, and when. Steps are
numbered from 0. A walk holds the paths a step names and no command or output, so "names" is all that can be
said.

| item | part or pool | row | the walk names a matching file | which, and when | passed | of |
| --- | --- | --- | --- | --- | --- | --- |
| 0193bde8 | A | the line 1 | yes | 2026-10-28-federation-pull.md at step 2, 13.7 s | 0 | 2 |
| 0193bde8 | A | the line 2 | yes | 2026-10-28-federation-pull.md at step 6, 19.6 s | 0 | 2 |
| 027834bf | A | the line 1 | yes | 2026-11-02-owner-trust.md at step 3, 19.7 s | 61 | 64 |
| 027834bf | A | the line 2 | yes | 2026-11-02-owner-trust.md at step 4, 13.2 s | 61 | 64 |
| 1113f1db | A | the line 1 | yes | 2026-10-28-federation-pull.md at step 3, 13.2 s | 17 | 42 |
| 1113f1db | A | the line 2 | yes | 2026-10-28-federation-pull.md at step 2, 13.9 s | 16 | 42 |
| 3879e609 | A | the line 1 | yes | 2026-11-02-owner-trust.md at step 3, 34.8 s | 74 | 74 |
| 3879e609 | A | the line 2 | yes | 2026-11-02-owner-trust.md at step 2, 12.0 s | 74 | 74 |
| 3f349e89 | A | the line 1 | yes | 2026-11-03-ship-home-and-crossing.md at step 2, 13.1 s | 0 | 95 |
| 3f349e89 | A | the line 2 | yes | 2026-11-03-ship-home-and-crossing.md at step 4, 16.4 s | 48 | 95 |
| 671a2250 | A | the line 1 | yes | 2026-10-28-federation-pull.md at step 4, 12.5 s | 7 | 10 |
| 671a2250 | A | the line 2 | yes | 2026-10-28-federation-pull.md at step 2, 13.0 s | 6 | 10 |
| 71a593d5 | A | the line 1 | yes | 2026-10-27-public-route.md at step 3, 14.5 s | 33 | 33 |
| 71a593d5 | A | the line 2 | yes | 2026-10-27-public-route.md at step 2, 13.3 s; 2026-10-27-public-route-design.md at step 3, 16.9 s | 33 | 33 |
| 9a3f21cf | A | the line 1 | yes | 2026-10-27-chat-paging.md at step 3, 17.3 s | 8 | 8 |
| 9a3f21cf | A | the line 2 | yes | 2026-10-27-chat-paging.md at step 2, 15.3 s | 8 | 8 |
| c9ceb15b | A | the line 1 | yes | 2026-10-28-federation-pull.md at step 2, 13.0 s | 26 | 27 |
| c9ceb15b | A | the line 2 | yes | 2026-10-28-federation-pull.md at step 2, 14.8 s | 26 | 27 |
| cd884db7 | A | the line 1 | yes | 2026-10-27-pairing-code.md at step 2, 11.2 s | 22 | 22 |
| cd884db7 | A | the line 2 | yes | 2026-10-27-pairing-code.md at step 3, 13.5 s | 22 | 22 |
| d20c739b | A | the line 1 | yes | 2026-10-27-public-route.md at step 4, 18.5 s | 32 | 34 |
| d20c739b | A | the line 2 | yes | 2026-10-27-public-route.md at step 5, 27.3 s | 32 | 34 |
| fff1b349 | A | the line 1 | yes | 2026-11-02-owner-trust.md at step 3, 14.9 s | 36 | 42 |
| fff1b349 | A | the line 2 | yes | 2026-11-02-owner-trust.md at step 2, 14.2 s | 37 | 42 |
| 383c5443 | P | nothing 1 | no | - | 15 | 18 |
| 383c5443 | P | nothing 2 | no | - | 15 | 18 |
| 383c5443 | P | the line 1 | yes | 2026-10-03-ds9-station.md at step 3, 16.1 s | 18 | 18 |
| 383c5443 | P | the line 2 | yes | 2026-10-03-ds9-station.md at step 3, 15.8 s | 18 | 18 |
| 4971bdb3 | P | nothing 1 | no | - | 20 | 20 |
| 4971bdb3 | P | nothing 2 | yes | 2026-10-10-ship-status-and-claims.md at step 4, 13.6 s | 20 | 20 |
| 4971bdb3 | P | the line 1 | yes | 2026-10-10-ship-status-and-claims.md at step 4, 17.6 s | 20 | 20 |
| 4971bdb3 | P | the line 2 | yes | 2026-10-10-ship-status-and-claims.md at step 3, 15.4 s | 20 | 20 |
| 6ba4650f | P | nothing 1 | yes | 2026-11-03-lessons-room-adds.md at step 5, 30.0 s | 0 | 21 |
| 6ba4650f | P | nothing 2 | no | - | 13 | 21 |
| 6ba4650f | P | the line 1 | yes | 2026-11-03-lessons-room-adds.md at step 4, 21.2 s | 20 | 21 |
| 6ba4650f | P | the line 2 | yes | 2026-11-03-lessons-room-adds.md at step 3, 14.5 s | 20 | 21 |
| b50b2c10 | P | nothing 1 | no | - | 22 | 25 |
| b50b2c10 | P | nothing 2 | no | - | 23 | 25 |
| b50b2c10 | P | the line 1 | yes | 2026-10-14-station-backups-alerts.md at step 3, 12.9 s | 24 | 25 |
| b50b2c10 | P | the line 2 | yes | 2026-10-14-station-backups-alerts.md at step 3, 14.3 s | 25 | 25 |
| c42ee1f4 | P | nothing 1 | yes | 2026-10-10-ship-status-and-claims-design.md at step 3, 11.8 s | 15 | 15 |
| c42ee1f4 | P | nothing 2 | yes | 2026-10-10-ship-status-and-claims-design.md at step 4, 18.1 s | 13 | 15 |
| c42ee1f4 | P | the line 1 | yes | 2026-10-10-ship-status-and-claims.md at step 3, 12.8 s | 15 | 15 |
| c42ee1f4 | P | the line 2 | yes | 2026-10-10-ship-status-and-claims.md at step 3, 13.2 s | 15 | 15 |
| ca2d0d80 | P | nothing 1 | no | - | 10 | 14 |
| ca2d0d80 | P | nothing 2 | no | - | 10 | 14 |
| ca2d0d80 | P | the line 1 | yes | 2026-10-14-station-backups-alerts.md at step 3, 13.1 s | 14 | 14 |
| ca2d0d80 | P | the line 2 | yes | 2026-10-14-station-backups-alerts.md at step 3, 13.7 s | 14 | 14 |

- **Under the line the plan is named in every turn where one is known:** 12 of 12 in pool P, at step 3 or 4
  and 13 to 21 seconds in; and 24 of 24 in part A, at step 2 to 6 and 11 to 35 seconds in.
- **With nothing, a commit's message was sometimes enough:** in pool P 4 of 12 Nothing turns name a matching
  file, at 3 items. No message names one (0 of 6); 5 cite a task or a step.

Pool N has no matching file. What its walks name under a plans, specs or reviews folder:

| item | row | plans, specs or reviews paths named | which |
| --- | --- | --- | --- |
| 2ebc78e1 | nothing 1 | 0 | - |
| 2ebc78e1 | nothing 2 | 0 | - |
| 2ebc78e1 | the line 1 | 1 | docs/superpowers/plans/2026-10-27-public-route.md |
| 2ebc78e1 | the line 2 | 1 | docs/superpowers/plans/2026-10-27-public-route.md |
| 426ad7fb | nothing 1 | 0 | - |
| 426ad7fb | nothing 2 | 0 | - |
| 426ad7fb | the line 1 | 1 | docs/superpowers/plans/2026-10-27-public-route.md |
| 426ad7fb | the line 2 | 1 | docs/superpowers/plans/2026-10-27-public-route.md |
| 603434cf | nothing 1 | 0 | - |
| 603434cf | nothing 2 | 0 | - |
| 603434cf | the line 1 | 0 | - |
| 603434cf | the line 2 | 0 | - |
| 82bff0db | nothing 1 | 0 | - |
| 82bff0db | nothing 2 | 0 | - |
| 82bff0db | the line 1 | 0 | - |
| 82bff0db | the line 2 | 0 | - |
| 906b3f73 | nothing 1 | 0 | - |
| 906b3f73 | nothing 2 | 0 | - |
| 906b3f73 | the line 1 | 2 | docs/superpowers/plans/2026-10-27-rail-lessons-hook.md, docs/superpowers/plans/2026-11-09-own-lessons.md |
| 906b3f73 | the line 2 | 1 | docs/superpowers/plans/2026-11-09-own-lessons.md |
| edec7384 | nothing 1 | 0 | - |
| edec7384 | nothing 2 | 0 | - |
| edec7384 | the line 1 | 0 | - |
| edec7384 | the line 2 | 0 | - |

- With nothing, no pool N walk names such a path (0 of 12 turns). Under the line 6 of 12 do, at 3 items:
  plans for neighbouring work. They are 4 pairs of item and file. The selecting reader had read 2 of them at
  that item and judged that they do not specify its work. The other 2 its searches had not found and it had
  not read (2026-10-27-public-route.md at 2ebc78e1; 2026-10-27-rail-lessons-hook.md at 906b3f73); nobody has
  judged whether either specifies the item's work. No Markdown file at an item's parent holds a name its
  commit adds: that is how the pool was drawn. The scores at these items are the same with the line and
  without.

## What the line cost

The worker's own seconds, tokens as fresh input plus output (cached input is left out), and the room's count
of steps. The refused row is in these counts: its worker ran as the others did.

| pool and row kind | turns | worker seconds, mean | median | tokens (fresh in plus output), mean | median | output tokens, mean | steps, mean | median | first source path named, second, mean | turns naming a plans, specs or reviews path | such paths named a walk, mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A the line | 24 | 183.3 | 158.2 | 50793.0 | 45374.0 | 6071.0 | 18.6 | 18.5 | 13.9 | 24 | 1.29 |
| P nothing | 12 | 121.2 | 125.2 | 43465.0 | 42656.0 | 4045.0 | 15.3 | 15.0 | 13.1 | 8 | 0.75 |
| P the line | 12 | 103.9 | 96.4 | 51715.0 | 50482.0 | 3231.0 | 13.8 | 12.5 | 12.5 | 12 | 1.08 |
| N nothing | 12 | 97.3 | 100.5 | 41350.0 | 41397.0 | 2939.0 | 12.6 | 13.0 | 11.9 | 0 | 0.0 |
| N the line | 12 | 126.5 | 119.6 | 50788.0 | 44398.0 | 3475.0 | 15.8 | 15.0 | 14.1 | 6 | 0.58 |

Each part B item, the mean of its two Nothing rows against the mean of its two rows under the line:

| item | pool | worker seconds: nothing | the line | difference | tokens: nothing | the line | difference | steps: nothing | the line | difference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2ebc78e1 | N | 120.4 | 125.1 | +4.7 | 37492.0 | 49246.0 | +11754 | 13.5 | 15.0 | +1.5 |
| 426ad7fb | N | 114.1 | 131.1 | +17.0 | 41082.0 | 35785.0 | -5297 | 15.5 | 16.0 | +0.5 |
| 603434cf | N | 108.6 | 157.3 | +48.7 | 51854.0 | 72693.0 | +20839 | 15.5 | 21.5 | +6.0 |
| 82bff0db | N | 67.1 | 72.4 | +5.3 | 40807.0 | 37614.0 | -3193 | 9.0 | 10.5 | +1.5 |
| 906b3f73 | N | 93.1 | 183.6 | +90.5 | 34516.0 | 66497.0 | +31981 | 11.0 | 19.0 | +8.0 |
| edec7384 | N | 80.5 | 89.3 | +8.8 | 42348.0 | 42896.0 | +548 | 11.0 | 13.0 | +2.0 |
| 383c5443 | P | 125.2 | 88.4 | -36.8 | 41643.0 | 54326.0 | +12683 | 16.0 | 12.0 | -4.0 |
| 4971bdb3 | P | 146.9 | 119.3 | -27.6 | 48598.0 | 58055.0 | +9457 | 18.5 | 15.5 | -3.0 |
| 6ba4650f | P | 165.0 | 153.5 | -11.5 | 48829.0 | 68953.0 | +20124 | 19.5 | 20.0 | +0.5 |
| b50b2c10 | P | 120.4 | 95.3 | -25.1 | 35844.0 | 61088.0 | +25244 | 12.0 | 11.0 | -1.0 |
| c42ee1f4 | P | 98.9 | 59.3 | -39.6 | 50250.0 | 33258.0 | -16992 | 15.0 | 11.5 | -3.5 |
| ca2d0d80 | P | 71.1 | 107.8 | +36.7 | 35628.0 | 34612.0 | -1016 | 11.0 | 13.0 | +2.0 |

- **Pool N, where the look finds no plan for the work:** more seconds at 6 of 6 items (29.2 in the mean),
  more steps at 6 (3.2), more tokens at 4 (9,439).
- **Pool P, where it finds one:** fewer seconds at 5 of 6 items (17.3 fewer in the mean), more tokens at 4
  (8,250 more in the mean).
- **The room's own verdict by replay,** beside the scores and vouching for none: true in 3 of 12 Nothing
  rows and 9 of 12 rows under the line in pool P; 7 of 12 and 8 of 12 in pool N; 8 of 24 in part A.

At the twelve seen items, the worker's own seconds here and in the first pilot, read from each pilot's turn
records:

| rows at the twelve seen items | turns | worker seconds, mean | median |
| --- | --- | --- | --- |
| first pilot, a plan exists | 12 | 187.2 | 169.4 |
| first pilot, nothing | 24 | 183.9 | 155.6 |
| second pilot, the line (part A) | 24 | 183.3 | 158.2 |

## What this is not

- **Not a judgement of the work.** The score is agreement with the reference's own tests. In part B the task
  is the commit's own message, so a Nothing turn starts with more than a user's words would give it, and the
  line has less left to add than "There is a plan" had in the first pilot, where the tasks withheld every
  name.
- **Not a showing that pool N has no plan.** One reader's review of the Markdown files tracked at the item's
  first parent found none, and the line's own turns opened 2 files that review had not read there. The same
  reader found a specifying document at 20 of the 34 candidates it walked, each of which the selection's
  word screen had passed. A review can miss one too.
- **Not a measure of what the line costs in score where there is no plan.** Pool N shows no loss at 6 items,
  3 of which could not show a gain. It does not show that no item would lose.
- **Not a measure of variation.** Two runs a cell. A gap between two runs is one observed gap an item, and
  "within" says only that the difference is no larger than the larger of the two gaps seen.
- **Not a test of a difference.** Nothing here is tested for chance. Twelve items; pool P's 6 are of 4
  plans.
- **Not a recommendation for the room.** The rule says only whether a larger trial is worth running. It
  reads agreement with the reference's tests and leaves out what the line costs.
- **A score can be forged** by a change written to do so: the cases run in the turn's own process inside the
  jail. No task asks for that. The room's verdict by replay is one more observation and does not vouch for a
  score.
- **One wording of the line,** which states and instructs at once. Which half does the work was not tried.
- **One repository, one component, one worker program and model, one machine, in other use.**

## What was found on the way

- **A turn can lose its whole change to a rule it was never told.** The room refuses to commit a work tree
  that holds a second repository. What a worker reads at its start says to commit, or to leave a message for
  the room to commit with; it does not say this. The refusal is the room guarding its own git, and it should
  stay. One sentence in what every turn reads would let a worker avoid it.
- **A record's word can hide the room's.** The runner calls a turn that ends on its base's commit "no
  hand-in", whether the worker changed nothing or the room refused its change. Only the clock's log tells
  them apart. The record should carry the room's own sentence.
- **A search that finds nothing needs a known case to find.** My check that no test makes a repository
  searched two spellings and missed a helper; another ship's read caught it within the hour.
- **The scripts' tests now run on three machines.** The first pilot's were pushed with their tests run on
  one; the workflow now runs all five test files on a Linux and a macOS runner.
- **An advisory read by Tardis of the new judge,** code only and before any score, asked for part A to stand
  beside the first pilot's rows and for three clearer labels. All four are in this report.

## What I would do next

**This section is my judgement.**

- **Run the larger trial the rule points to, with the costs counted in.** The line cost about half a minute
  a turn where the look found nothing for the work, and it saved time where it found the plan. A larger
  trial should fix beforehand what cost is worth what gain, which this pilot's rule left out.
- **Give pool N room to move.** 3 of its 6 items could not rise and 0 fell. A trial that asks whether the
  line harms needs items where a Nothing turn passes some cases and not all, and more than six of them.
- **Use a task in a user's words in part B as well.** The commit's message cites a task or a step at 5 of
  pool P's 6 items, and with nothing added 4 of 12 turns found a matching file from it. With such a task the
  line's gain is what is left after the message.
- **Tell every turn the one-repository rule, and carry the room's sentence in the record,** before the next
  turns are run.
- **A behaviour check that does not depend on the reference's names** is still the missing instrument, as
  the first pilot's report said.

## Where the numbers come from

Beside this report, in `2026-11-19-v2-a-line-that-says-a-plan-may-exist-pilot/`:

- `report.md` and `report.json`: the judge's own report, as generated.
- `rows.json`: one entry a row: when it ran, the load before it, how it ended and what the room said, the
  worker's seconds, its steps and tokens, its counts over the frozen cases, the room's verdict, and what its
  walk names.
- `facts.json` and `run.json`: the counts this report's sentences use.
- `refused-row.json`: the rule as it reads and the two readings beside it.
- `added-turn.json`: the one turn run after the pilot, outside its plan.

Every table above was made from the judge's data by script and none was typed; the numbers in the sentences
are filled from those files. The first pilot's columns are read from its own `rows.json`. The rooms, the
turns' repositories and the walks are kept on the machine that ran the pilot.