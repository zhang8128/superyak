# v2: a line that says a plan may exist. The pilot's report

Serenity, 2026-11-19 (UTC). The pilot of
`docs/superpowers/specs/2026-11-19-v2-a-line-that-says-a-plan-may-exist.md` (revision 3): its turns ran from
2026-11-19 12:22:41 UTC to 2026-11-19 15:11:48 UTC, and its judging from 15:11:48 to 15:52:37 UTC the same
day. Read twice by fresh readers of the other model family. The first (w129) approved with eight named
changes. The second (w131) checked those and read the section added after the first read, and approved with
named changes: two of the eight to finish and four in the added section. All are made as named.

## In short

In the first pilot, a turn told "There is a plan for this work in the repository" had a walk that names the
plan at 11 of 12 items, and its change passed far more of the reference's tests. That sentence can only be
said by someone who knows a plan exists. This pilot asks what a line does that anyone could put at the end
of every task: "There may be a plan for this work in the repository. Look for one before you change code."
It was tried where a plan is known and where a selecting reader's review found none.

- **The rule fixed before any turn says "worth a larger trial".** It reads twelve items no model turn had
  touched. Where a reader had confirmed a plan (pool P), the line is higher than nothing at 4 of 6 items and
  lower at 0. Where the selecting review found no plan (pool N), it is lower at 0 of 6. The rule says only
  whether a larger trial is worth running.
- **The line increased agreement with the reference's tests over nothing in both settings.** In pool P
  nothing's two runs passed 82 and 94 of 113 frozen cases and the line's two 111 and 112. At the first
  pilot's twelve items (part A, a look only) the line's two runs passed 316 and 363 of 453; "There is a
  plan" passed 367 there, one run, and nothing 151 and 154. The lower of the line's two runs holds one row
  whose test file could not be collected. Pool P had no "There is a plan" row, so the two sentences are
  compared only at the seen items.
- **Under the line a turn's walk names the plan every time one is known:** 24 of 24 turns in part A and 12
  of 12 in pool P.
- **Where the selecting review found no plan, no score changed among the hand-ins that were taken.** At 6 of
  pool N's 6 items, every row whose change was taken passes the same number of cases, with the line or
  without. At 3 of them both Nothing rows already pass every case, so there the line could not have shown a
  gain. No score loss was observed at these six items.
- **What it cost there.** In pool N a turn under the line took 126.5 seconds of the worker's time against
  97.3 with nothing: more at 6 of 6 items, 29.2 seconds a turn in the mean, with 3.2 more steps and 9,438
  more tokens. In pool P the line's turns were shorter at 5 of 6 items.
- **An added look, chosen after scoring; it changes no class and no rule.** Sorted by the first line of a
  case's failure on the parent, 43 of pool P's 59 cases that do not pass there, and 295 of 304 at the first
  pilot's items, are in an interface or collection bin. On pool P's 16 others the line's two runs pass 16
  and 16 and nothing's 8 and 7. The sorting does not separate naming from behaviour.
- **One hand-in was refused by the room:** a Nothing row at a pool N item. By the spec it is scored as its
  parent. That one row raises pool N's mean difference from 0.000 to 0.083. The rule reads the same with it
  and without it.

**What the score is.** It is agreement with the reference's own tests: names, calls and wordings as well as
behaviour. It does not say a change is better work. In part B the task is the commit's own message, which
may supply clues a user's task would omit: at 5 of pool P's 6 items it cites a task or a step of the plan.

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
- **Which way it tilts.** It lowers that item's baseline, so it raises pool N's mean difference, toward
  "worth a larger trial". I posted this in the ships' room at 15:00 UTC, before the judging began at
  15:11:48. That post is not among this report's files; it is my word here.
- **The rule three ways.** The second and third lines are outside the rule: an added look, made with the
  judge's own functions. I wrote its script before the judging began; that too is my word and is not in
  these files. The second line puts the item's one taken Nothing row in the refused row's place, so that
  pair's gap is zero by construction and not by observation.

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
  (0 of 6 pool P items; in pool N 0 of 6).
- **6ba4650f, nothing 1:** the test file could not be collected, so that row is 0 of 21. Its walk names the
  plan. The other Nothing row, whose walk does not, passes 13.

The gaps between an item's repeated rows (`rn` and `rm`) and what its commit's message holds are columns of
the same table in the judge's own report, `report.md` beside this one. 2 of pool P's messages hold a name
the item's commit adds (4971bdb3 and 6ba4650f).

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

On these cases pool P's mean d is 0.504 with 3 items higher and 0 lower, and its mean over the 4 plan groups
is 0.584; pool N's is 0.083 with 0 lower. In all, of pool P's 59 such cases nothing's two runs passed 28 and
41 and the line's two 58 and 58.

## Part A, beside the first pilot's rows

The first pilot's eight rows at its twelve items, read from its own `rows.json`, and the line's two runs at
the same items. One run a cell in the first pilot; two here. No class and no rule. The first pilot's row
"the second search" was chosen there after the four orderings' retrieval counts had been compared on these
twelve items; it was an added look in that pilot too.

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
- **With nothing:** in pool P the walks of 4 of 12 Nothing turns name a matching file, at 3 items. No
  message names one (0 of 6); 5 cite a task or a step.

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

- With nothing, no pool N walk names such a path (0 of 12 turns). Under the line 6 of 12 do, at 3 items.
  They are 4 pairs of item and file, each file under a plans folder. The selecting reader had read 2 of them
  at that item and judged that they do not specify its work. The other 2 its searches had not found and it
  had not read (2026-10-27-public-route.md at 2ebc78e1; 2026-10-27-rail-lessons-hook.md at 906b3f73); nobody
  has assessed whether either specifies the item's work. No Markdown file at an item's parent holds a name
  its commit adds: that is how the pool was drawn. Among the hand-ins that were taken, the scores at these
  items are the same with the line and without.

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
| 2ebc78e1 | N | 120.4 | 125.1 | +4.7 | 37491.5 | 49246.0 | +11754.5 | 13.5 | 15.0 | +1.5 |
| 426ad7fb | N | 114.1 | 131.1 | +17.0 | 41082.5 | 35785.0 | -5297.5 | 15.5 | 16.0 | +0.5 |
| 603434cf | N | 108.6 | 157.3 | +48.7 | 51854.5 | 72693.0 | +20838.5 | 15.5 | 21.5 | +6.0 |
| 82bff0db | N | 67.1 | 72.4 | +5.4 | 40807.0 | 37614.0 | -3193.0 | 9.0 | 10.5 | +1.5 |
| 906b3f73 | N | 93.1 | 183.6 | +90.5 | 34516.5 | 66497.0 | +31980.5 | 11.0 | 19.0 | +8.0 |
| edec7384 | N | 80.5 | 89.3 | +8.8 | 42348.0 | 42895.5 | +547.5 | 11.0 | 13.0 | +2.0 |
| 383c5443 | P | 125.2 | 88.4 | -36.8 | 41643.0 | 54326.0 | +12683.0 | 16.0 | 12.0 | -4.0 |
| 4971bdb3 | P | 146.9 | 119.3 | -27.7 | 48597.5 | 58055.0 | +9457.5 | 18.5 | 15.5 | -3.0 |
| 6ba4650f | P | 165.0 | 153.5 | -11.6 | 48829.0 | 68953.0 | +20124.0 | 19.5 | 20.0 | +0.5 |
| b50b2c10 | P | 120.4 | 95.3 | -25.2 | 35844.5 | 61088.5 | +25244.0 | 12.0 | 11.0 | -1.0 |
| c42ee1f4 | P | 98.9 | 59.3 | -39.5 | 50249.5 | 33257.5 | -16992.0 | 15.0 | 11.5 | -3.5 |
| ca2d0d80 | P | 71.1 | 107.8 | +36.7 | 35627.5 | 34612.0 | -1015.5 | 11.0 | 13.0 | +2.0 |

- **Pool N (no plan found by the selecting review):** more seconds at 6 of 6 items (29.2 in the mean), more
  steps at 6 (3.2), more tokens at 4 (9,438).
- **Pool P (a plan confirmed):** fewer seconds at 5 of 6 items (17.3 fewer in the mean), more tokens at 4
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

## An added look, chosen after the scores were read: how the cases fail on the parent

Both pilots' reports say the score is agreement with the reference's tests, names included. This look sorts
the cases by how they first fail on the parent. It was not in the spec, it was chosen after the scores were
read, and it changes no class and no rule.

Each frozen case that does not pass on the parent is put in one of three bins by a rule on the first line of
its failure there, read from the parent's own run in the item's controls:

- **interface or collection:** the case was not collected on the parent, or that first line matches any of
  `ImportError`, `ModuleNotFoundError`, `AttributeError`, `NameError`, "has no attribute", "cannot import
  name", "unexpected keyword", "got an unexpected", "missing N required", "takes N positional" or "fixture
  '...' not found";
- **assertion:** otherwise, the case failed there and that line begins `AssertionError` or `assert `;
- **other:** anything else (a `KeyError`, say).

The bins are what that rule gives and no more. A case in the first bin met a barrier of interface or
collection first; what it would test once that barrier is gone is not known from this. A case in the other
two did not match the rule's first bin. It may still need a new name further on, and some in "other" fail on
a missing key, which can be a matter of naming too. So the second and third bins are candidates for a check
of behaviour and not proof of one. Each row's cases were read from the report its judging committed, and
every row's total equals the judge's score, in both pilots.

| item | pool | assertion: cases | nothing 1 | nothing 2 | the line 1 | the line 2 | other: cases | nothing 1 | nothing 2 | the line 1 | the line 2 | interface or collection: cases | nothing 1 | nothing 2 | the line 1 | the line 2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2ebc78e1 | N | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 89 | 0 | 89 | 89 | 89 |
| 426ad7fb | N | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 16 | 16 | 16 | 16 | 16 |
| 603434cf | N | 0 | 0 | 0 | 0 | 0 | 3 | 2 | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| 82bff0db | N | 1 | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 1 | 1 | 1 |
| 906b3f73 | N | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| edec7384 | N | 1 | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 383c5443 | P | 1 | 0 | 0 | 1 | 1 | 2 | 0 | 0 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| 4971bdb3 | P | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 20 | 20 | 20 | 20 | 20 |
| 6ba4650f | P | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 21 | 0 | 13 | 20 | 20 |
| b50b2c10 | P | 4 | 3 | 3 | 4 | 4 | 1 | 0 | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 1 |
| c42ee1f4 | P | 2 | 2 | 1 | 2 | 2 | 2 | 2 | 1 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| ca2d0d80 | P | 3 | 1 | 1 | 3 | 3 | 1 | 0 | 0 | 1 | 1 | 1 | 0 | 0 | 1 | 1 |
| **pool P** | P | 10 | 6 | 5 | 10 | 10 | 6 | 2 | 2 | 6 | 6 | 43 | 20 | 34 | 42 | 42 |
| **pool N** | N | 4 | 2 | 2 | 2 | 2 | 3 | 2 | 2 | 2 | 2 | 106 | 17 | 106 | 106 | 106 |

- **Pool P:** of 59 cases not passing on the parent, 43 are in the interface or collection bin. On the 16
  others, nothing's two runs pass 8 and 7 and the line's two 16 and 16.
- **Pool N:** of 113, 106 are in that bin, 89 of them at one item. On the 7 others every row passes 4; the
  two at 906b3f73 pass in no row.

The first pilot's twelve items, its eight rows and the line's two, summed over the items:

| how the case fails on the parent | cases | nothing 1 | nothing 2 | a plan exists | the path | three by search | the second search | three newest plans | three by lot | the line 1 | the line 2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| assertion | 8 | 0 | 0 | 7 | 6 | 0 | 0 | 5 | 0 | 5 | 6 |
| other | 1 | 0 | 0 | 1 | 1 | 0 | 0 | 1 | 0 | 1 | 1 |
| interface or collection | 295 | 3 | 6 | 210 | 206 | 5 | 130 | 40 | 5 | 161 | 207 |

- **295 of the 304 cases not passing on the parent there are in the interface or collection bin under this
  first-line rule.** This does not separate naming compatibility from behaviour. The 149 cases that pass on
  the parent, of that pilot's 453, are in no bin.
- On the 9 others: nothing 0 and 0; "There is a plan" 8; the line 6 and 7.
- **A case that passes on the parent stops passing** in 2 of this pilot's 72 rows (both at b50b2c10, one
  Nothing row and one under the line) and in 5 of the first pilot's 96.

As counts, and no more: in pool P the rows under the line, whose walks all name the plan, also pass more of
the cases outside the interface or collection bin; in pool N the four kinds of row pass the same number of
them. The numbers are small and the sorting was made after the fact.

## What this is not

- **Not a judgement of the work.** The score is agreement with the reference's own tests. In part B the task
  is the commit's own message, which may supply clues a user's task would omit. No task in a user's words
  was run in part B, so what the line adds beside one is not known from it.
- **Not a showing that pool N has no plan.** One reader's review of the Markdown files tracked at the item's
  first parent found none, and the walks of the line's own turns name 2 files under a plans folder that the
  review had not read there. The same reader found a specifying document at 20 of the 34 candidates it
  walked, each of which the selection's word screen had passed. A review can miss one too.
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
  the room to commit with; it does not say this. My judgement is to keep the guard, which protects the
  room's own git, and to explain it to workers; that may prevent some refusals. What made the repository
  here is not known, so it is not shown that a sentence would have prevented this one.
- **A record's word can hide the room's.** The runner calls a turn that ends on its base's commit "no
  hand-in", whether the worker changed nothing or the room refused its change. Only the clock's log tells
  them apart. I propose that the record say which it was.
- **A search that finds nothing needs a known case to find.** My check that no test makes a repository
  searched two spellings and missed a helper; another ship's read caught it within the hour.
- **The scripts' tests now run on three machines.** The first pilot's were pushed with their tests run on
  one; the workflow now runs all five test files on a Linux and a macOS runner.
- **An advisory read by Tardis of the new judge,** code only and before any score, asked for part A to stand
  beside the first pilot's rows and for three clearer labels. All four are in this report.

## What I would do next

**This section is my judgement.**

- **Run the larger trial the rule points to, with the costs counted in.** The line's turns took about half a
  minute longer in pool N and were shorter at most pool P items. A larger trial should fix beforehand what
  cost is worth what gain, which this pilot's rule left out.
- **More items where the selecting review finds no plan.** 3 of pool N's 6 items could not rise and 0 fell.
  Six items cannot say the line never costs score. A larger trial needs more of them, with baselines that
  can show a gain as well as a loss.
- **Use a task in a user's words in part B as well.** The commit's message cites a task or a step at 5 of
  pool P's 6 items, and with nothing added the walks of 4 of 12 turns name a matching file. A task in a
  user's words was not run in part B; what the line adds beside one is not known.
- **Tell every turn the one-repository rule, and carry the room's sentence in the record,** before the next
  turns are run.
- **Count, with no model, the cases outside the interface or collection bin at every item whose reference
  passes the jail, and read their tests.** In pool P the line's rows passed more of them (16 and 16 of 16
  against 8 and 7); in pool N every kind of row passed the same 4 of 7. They are candidates only: their
  whole tests would have to be read for the names and wordings they still depend on before a trial's
  endpoint is chosen from them.

## Where the numbers come from

Beside this report, in `2026-11-19-v2-a-line-that-says-a-plan-may-exist-pilot/`:

- `report.md` and `report.json`: the judge's own report, as generated.
- `rows.json`: one entry a row: when it ran, the load before it, how it ended and what the room said, the
  worker's seconds, its steps and tokens, its counts over the frozen cases, the room's verdict, and what its
  walk names.
- `facts.json` and `run.json`: the counts this report's sentences use.
- `refused-row.json`: the rule as it reads and the two readings beside it.
- `added-turn.json`: the one turn run after the pilot, outside its plan.
- `per-case.json`: the added look: each item's cases by how they fail on the parent, and each row's passes
  among them, for both pilots.
- `first-pilot-worker-seconds.json`: the first pilot's worker seconds for the 36 rows the last table of
  "What the line cost" uses, read from its turn records.

Every table above was made from the judge's data by script and none was typed; the numbers in the sentences
are filled from those files. The first pilot's score columns are read from its own `rows.json`; its worker
seconds are in `first-pilot-worker-seconds.json`, copied from its turn records. The rooms, the turns'
repositories and the walks are kept on the machine that ran the pilot.