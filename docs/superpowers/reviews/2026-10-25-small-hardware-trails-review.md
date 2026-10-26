# Review: trail spec revision 9 and its plan (small hardware, and the full store)

**Date:** 2026-10-26
**Reviewer:** a fresh reviewer acting in Andy's place (station law section 3). I took no part in the amendment.
**Spec:** `engram/docs/superpowers/specs/2026-10-25-trail-arrows-design.md`, revision 9 (`git diff HEAD`, branch
`trail-arrows-spec`). Cited as "spec line N".
**Plan:** `engram/docs/superpowers/plans/2026-10-25-trail-arrows.md`, the same diff. Cited as "plan line N".
**Verdict: reject in this form.** Three must-fix items remain. All three are about bounds. The design is sound, and
every figure the spec shows is right by its own arithmetic. But two of those figures rest on things nothing enforces
(M1, M2), and one new bound can move a gate verdict without the report saying so (M3). Both of Andy's decisions are
carried in his words. A revision that fixes M1 to M3 should pass a re-check. The should-fix items can go in the same
revision.

## What the amendment changed

- **The full store (A8, R24).** Section 14's question is answered with Andy's words. Section 7 gains "On a full-store
  imprint": the evaluation may run on an imprint of his whole store. It reads text only inside the run, reads no
  co-subject row, shows nothing to any agent, and lets only counts and rates leave. Whether the use is allowed stays
  with the imprint check and the permissions spec's meet.
- **Small hardware (A7, R19 to R23).** A 2 GB Pi; every process under 512 MiB, with design peaks of 384 MiB, 320 MiB
  for the evaluation, and 128 MiB added to an engram server. Stores are read one session at a time through cursors,
  and what grows with the store goes in a scratch SQLite file on disk. The tool graph is numpy arrays. B is built in
  tiles, the bootstrap in chunks of 64, and one S at a time. The in-process model is withdrawn: W uses only the shared
  embedder. New bounds: 16,384 rows per session, 262,144 touches in the tool graph, and "not evaluable: too large"
  past 262,144 steps or 40,000 held-out sessions. New section 10.1 holds the budget and its arithmetic; section 12
  adds a peak-memory test per pass on the Pi; I7 answers the imprint spec's four asks.
- **Plan.** New rulings TR24 to TR29; Task 20 rewritten (`open_embedder`, no change to `embeddings.py`); Tasks 1 to
  4, 6 to 8, 10, 12, 16, 19, 21, 23 to 25 and 28 changed; G6, G11 and G15; new Results rows and coverage rows.

## How I checked

- I read the whole diff of both files, the vision (`docs/city-rail-vision.md`, principle 4 and "Open for Andy"), the
  imprint spec's revision 7 (sections 8, 12, 14.1, 17 and 18) and the permissions spec's current text (P12, P25, P36,
  section 19). The permissions spec was edited at 15:25, after this spec (15:06).
- I checked every code claim the revision adds against the code in this worktree.
- I redid every memory figure by hand (below). I measured on this Pi, with the system Python 3.11.2 and `tracemalloc`,
  the object sizes the must-fix items depend on. I ran two small experiments in the session scratchpad; none touched
  the repository.
- I checked that every `## ` and `### ` heading of HEAD is still in both files, that both files end with a newline,
  and that code fences pair up (spec 2, plan 120).

## Decision 1: "yes you can copy the full store"

Carried exactly. A8 (spec line 128) has every clause of the vision's reading: the whole store, memories that mention
other people included; their recorded people stay co-subjects; any use outside the owner's home still needs their
yes (P12, P25); copying is not sharing. It names which part is Andy's words and which is Rio Grande's reading. Section
14 (spec lines 2010 to 2018) says Andy still says yes in the browser for that imprint (imprint spec D1). Section 7's
forecast of a thin first imprint is narrowed to an imprint that leaves memories at home, which is right: a full-store
imprint loses only rows that matched a memory pruned to cold storage.

One account is out of date (S1). Section 7 says the imprint and permissions specs' revisions 7 disagree (spec lines
994 to 999). Since then the permissions spec added P36 (its line 621), which lets "the trail evaluation" read the
owner's layer alone inside his home, and Rio Grande ruled that a co-subject's deny still refuses there (the permissions
review, "Controller rulings", M3). This spec decides none of that, so no rule here is wrong. But its text and the
plan's G6 (plan line 3223) describe a conflict that has moved.

## Decision 2: small hardware

Carried, with one reading of units. Every part of Rio Grande's reading is present: the 2 GB Pi (R20), under 512 MiB
measured on the Pi (R20, section 12), streaming and bounded batches (R21), no whole store, dense matrix or whole graph
(R21 to R23), the shared embedder never loaded twice (R19), and no unit added, any later one at `MemoryMax=512M` or
less (R20). Each is marked "Rio Grande's call, from A7".

Units (S8). The vision says "512 MB"; R20 reads MB as MiB, as systemd reads `512M`. Every peak holds under either
reading: 512 × 10⁶ bytes is 488.3 MiB, and the largest figure is a server with the tools on, 305.2 + 128 = 433.2 MiB
(454.2 × 10⁶ bytes). Only the cap itself depends on the reading: `512M` is 536,870,912 bytes, 536.9 × 10⁶.

### The figures, redone

1 MiB = 1,048,576 bytes. Every line below matches the spec to the rounding it shows.

Revision 8, before (spec lines 1579 to 1596):

| Item | Arithmetic | MiB |
|---|---|---|
| episode rows | 90,000 × 1,620 = 145,800,000 | 139.0 |
| recall rows | 200,000 × 1,168 = 233,600,000 | 222.8 |
| touches | 240,000 × 363 = 87,120,000 | 83.1 |
| step support | 150,000 × 596 = 89,400,000 | 85.3 |
| derivation in all | 555,920,000 bytes | 530.2 |
| observer pass in a server | 320,000,000 B = 305.2; 305.2 + 530.2 | 835.4 |
| tool graph as tuples | 2,097,152 × 156 = 327,155,712 (312.0) + 262,144 × 204 = 53,477,376 (51.0) + 58.6 + 3.1 | 424.7; 729.9 with its server |
| B's block | 1,024 × 20,000 × 8 = 163,840,000 | 156.25 |
| bootstrap in one draw | 10,000 × n × 16 = 160,000 n; n = 2,000 and 4,000 | 305.2 and 610.4 |
| A* on 262,144 and 320,000 edges | × 160 = 41,943,040 and 51,200,000 | 40.0 and 48.8 |
| costs and predecessors | 2 × 20,000 × 100 = 4,000,000 | 3.8 |

Revision 9, after (spec lines 1604 to 1613):

| Process | Arithmetic | MiB | Design peak |
|---|---|---|---|
| Observer pass, added | 3.9 + 8 + 16,384 × 2,098 = 34,373,632 (32.8) + 16,384 × 424 = 6,946,816 (6.6) + 64 × 2 × 512 × 363 = 23,789,568 (22.7) + 16,384 × 266 = 4,358,144 (4.2) + 323,705 (0.3) | 78.5 | 128 |
| Tool graph held | 20,000 × 3,072 = 61,440,000 (58.6) + 20,000 × 163 = 3,260,000 (3.1) + 0.2 + 262,144 × 25 = 6,553,600 (6.25) + 262,144 × 13 = 3,407,872 (3.25) + 8,192 × 106 = 868,352 (0.8) + 1,048,576 (1.0) | 73.2 | in 128 |
| Build, deriving | 3.1 + 4.1 + 524,288 × 21 = 11,010,048 (10.5) + 32.8 + 4.2 + 8 + 3.9 | 66.6 | 128 |
| Build, aggregating | 10.5 + 524,288 × 8 = 4,194,304 (4.0) + 7.2 + 6.25 + 3.9 | 31.9 | 128 |
| Build, reading vectors | 73.2 + 2 × 1,024 × 3,072 = 6,291,456 (6.0) + 3.9 | 83.1 | 128 |
| A tool call, added | 73.2 + 1,024 × 768 × 8 = 6,291,456 (6.0) + 480,000 (0.5) + 40.0 + 3.8 + 1 + 1 | 125.5 | 128 |
| CLI route modes | 128 + 125.5 | 253.5 | 384 |
| Counting R(I), added | 32.8 + 4.2 + 8 + 2.0 | 47.0 | 384 |
| Evaluation, deriving | 128 + 3.9 + 8 + 32.8 + 4.2 | 176.9 | 320 |
| Evaluation, building B | 128 + 3.9 + 3.1 + 58.6 + 6.25 + 320,000 × 25 = 8,000,000 (7.6) + 1.5 + 6.0 + 2.0 + 20,000 × 16 × 12 = 3,840,000 (3.7) | 220.7 | 320 |
| Evaluation, routing | 128 + 3.9 + 3.1 + 58.6 + 6.25 + 6.25 + 7.6 + 48.8 + 3.8 + 40,000 × 160 = 6,400,000 (6.1) + 1 | 273.4 | 320 |
| Evaluation, bootstrap | 128 + 3.9 + 3.1 + 58.6 + 6.25 + 7.6 + 6.1 + 64 × 40,000 × 16 = 40,960,000 (39.1) | 252.7 | 320 |

Other figures: the use's unit holds `imprint.py use` (64) and the evaluation, 64 + 273.4 = 337.4 MiB by arithmetic and
64 + 320 = 384 by design, both under 512. The whole Pi: 1.1 GB = 1,100,000,000 bytes = 1,049.0 MiB, and 2,048 − 1,049
− 512 = 487 MiB. The I7 ask: 148 + 32.8 + 4.2 = 185.0 MiB, under 384. The bootstrap: 156 × 64 + 16 = 10,000. SQLite's
default page cache is `-2000` (I read it on this Pi, SQLite 3.40.1): 2,048,000 bytes, 1.95 MiB.

My own measurements, on this Pi: a 7-field `Touch` 395 bytes (spec 363), a recall row of 20 ids as a frozen
dataclass 2,248 bytes (spec 2,098). Both are within 9% of the spec's figures, and with them the pass comes to about
82.8 MiB, still under 128. These differences don't matter; M1 does.

So every figure holds at the bounds the spec states. M1 and M2 are about what the stated bounds leave out.

## Streaming and batching: verdicts, receipts, privacy

- **One session at a time.** The order is the same (TR12), and the derivation's results are pinned by Tasks 2 to 4's
  fixed-answer tests. That holds.
- **The 16,384-row bound** is new, and it is not neutral (M3). A session over it gets no trail. In the evaluation that
  silently removes sessions from T, from every S and from the held-out set. That can move a gate either way, and the
  report doesn't name the count: `sessions_too_large` appears only in the pass's counts (spec line 501), not in
  section 7's report. R23 says the evaluation answers "not evaluable: too large", "never a sample" (spec line 1175).
  The same bound also lowers N, the count of R(I) that the imprint spec's `admitted` and use receipts carry (imprint
  spec lines 1619 to 1630), since R(I) is defined by this spec's section 4.
- **B in tiles.** The procedure defines B (spec lines 1169 to 1173), and Task 23 tests it against a brute-force B
  with exact duplicates. It can differ from revision 8's B only when more than 8 nodes tie within float64 rounding.
  Nothing has run, so no verdict moves.
- **The bootstrap in chunks.** On this Pi's system numpy 1.24.2, chunked draws of `(64, n)` gave exactly the same
  integers as one `(N, n)` draw, for n = 37 and n = 2,000. The spec makes the chunking part of the rule anyway, which
  is safe. Engram pins numpy 2.4.3, which I did not test; Task 23's reference loop covers it.
- **The embedder check, one text at a time.** The shared service runs one request as one batch, under a lock
  (`engram/embedder_service.py:6`, `:120`), so the client fixes the batch shape. That supports the determinism claim.
- **Receipts.** Tool receipts are unchanged. One diagnostic changed meaning (S7): `reflect`'s `suggested_touches` now
  counts only the tool graph's sessions, not every closed session in `graph.db` (spec line 957; plan line 2294).
- **Privacy.** Scratch files hold ids, times and counts, never text, in 0700 directories (TR24, TR28), and are removed
  at the end; the imprint's scratch goes with the state directory on withdrawal (imprint spec lines 1500, 1871). The
  shared embedder logs no text (`engram/embedder_service.py:84`, `:134` are its only log lines). Nothing new leaves a
  machine. One gap: the spec says "Never a tmpfs `/tmp`" (spec lines 1547 to 1548), but nothing checks it (S12).

## Co-subjects of copied memories

They stay protected, through the imprint check, not through anything new here. `trails.py` runs on an imprint only
with a valid allow file and checks it again at the end (spec section 7, "The imprint check", unchanged). Under the
permissions spec's P36 and Rio Grande's ruling, a co-subject's deny refuses the use inside the home too, so the station
writes no allow file and `trails.py` refuses. R24 adds that the run reads no co-subject row, shows nothing to any agent
and lets only counts and rates leave. Two things are missing: the text describing the other specs is stale (S1), and
R24 has no test and no plan task (S2).

## Plan against spec

The plan follows the spec closely. Constants match (plan lines 102 to 110). Task 20 builds `open_embedder` on
`RemoteEmbedProvider` only, and its test makes any fastembed import fail. Task 28's twelve peak tests, one per pass
and store, the times test, the embedding test and the token test make the 15 the plan expects (plan lines 3115 to
3150), and Task 29's "fifteen skipped" matches. Test counts in Tasks 1, 2, 3, 10, 16, 21 and 23 match the tests
listed. Gaps:

- No task tests `--evaluate` on a `batch_only` connection, which spec section 12 asks for (S4; plan line 3298).
- Task 3's equality test compares `iter_trails` with `derive_trails`, which is `iter_trails` collected (S5).
- R24 maps to no task or test (S2).
- Task 28 measures "added" as a difference of `ru_maxrss`, which can under-count (S3).

## Files

Both files are whole. HEAD's 22 `## `/`### ` headings of the spec are all present, plus "Decisions in revision 9"
and "10.1 Memory on a small Pi". All 29 `### Task` headings of the plan are present; Task 20's title changed on
purpose. Both files end with a newline. The new tables have a constant column count.

## Must-fix

**M1. One session's memory is bounded in rows, not in bytes.** Section 4 says one session holds "at most 16,384
recall rows of 20 ids" (spec line 282), and every figure that includes "one session 32.8" rests on it: the pass, the
build, counting R(I) and the evaluation. Nothing enforces 20 ids. `recall`'s `max_results` is a caller's argument
with default 20 (`engram/server.py:2068`); the row logs `scored[:max_results]` (`:2367`, `:2371`, `:2384`). An
`operation_log` row's `target_ids` is unbounded text (`engram/migrations/025_operation_log.sql:9`), and `Reader.rows`
holds those rows too (plan line 416). Measured here, a recall row costs 9,682 bytes with 100 ids and 18,982 with
200. At 16,384 rows:

- 100 ids: 16,384 × 9,682 = 158,629,888 bytes, 151.3 MiB. The pass then adds 78.5 − 32.8 + 151.3 = 197.0 MiB, over
  its 128.
- 200 ids: 16,384 × 18,982 = 311,001,088 bytes, 296.6 MiB. The pass adds 342.3 MiB, and the server reaches 305.2 +
  342.3 = 647.5 MiB, over 512. The evaluation, deriving, reaches 176.9 − 32.8 + 296.6 = 440.7 MiB, over its 320; with
  `imprint.py use`, 504.7 MiB, 7.3 MiB under the cap.

One agent calling `recall(max_results=200)` in a long session is enough. Fix: bound a session by what it holds, not
only by rows. For example, the `Reader` streams each row's `json_array_length(target_ids)` into the scratch index,
and a session whose rows hold more than 327,680 target ids (16,384 × 20) is `sessions_too_large` too. Then the 32.8
MiB figure holds. Say what bounds a single row: "1,000 rows or 8 MiB" can't split one row, and episode content has no
cap in engram (no length check in `server.py` or `storage.py`). Give Task 1 a test and Task 28's bounds store a
session at the new limit.

**M2. Three structures still grow with the store and are outside 10.1.** Spec line 1598 says "nothing held grows
with the store", and line 394 that the pass adds at most 78.5 MiB "whatever the store's size". These don't fit:

- *The evaluation's trails in T and in each S.* The next hit runs forward lookups in T and in each shuffle (spec lines
  1203 to 1206, 1334), and forward lookup reads a graph's `trails` and `through` (plan line 1755). So T and S hold
  their training trails' touches and postings, 17 bytes a touch by TR25's dtypes. No `EVAL_*` constant bounds
  touches, and 10.1 counts only T's and S's edges ("T 6.25", "one S 6.25"). A trail is cut at 512 touches, but
  sessions and recall rows are not bounded by the 100,000-memory cap. At 1,000,000 training touches T and one S hold
  2 × 17,000,000 bytes, 32.4 MiB, and routing comes to 305.8 MiB; at 2,000,000 touches, 338.2 MiB, over 320.
- *The evaluation's training detours.* The detour hit rate uses `find_detours` on the training trails (plan line
  2675), which returns a whole `list[Detour]` (plan line 1140).
- *The observer pass's detour search.* `find_detours` returns every detour found, each with a `sessions` tuple of
  every session that travelled it (plan line 1137), and it reads "one key's routes" with one row per travelling
  session (plan line 1230). Both grow with the store. 10.1's pass row has no detour term.

Fix: bound T's and S's touches (for example at 262,144 each, "not evaluable: too large" past it, 2 × 262,144 × 17 =
8,912,896 bytes, 8.5 MiB), or run the next hit from the scratch file with SQL. Have `find_detours` aggregate each
route in SQL (session count, first and last touch, at most `ROAD_EVIDENCE` session ids) and yield detours in TR11's
order, so the pass stops after its 32 and the hit rate streams its pairs. Put each figure in 10.1.

**M3. The row bound can change a gate verdict, and nothing reports it.** Section 4 says "None of this changes a
result for a session under the bound" (spec line 284), which is true of one session. But the evaluation drops every
session over the bound from T, S and the held-out set, and its report doesn't carry `sessions_too_large`. That is a
sample, which R23 forbids (spec line 1175). Fix: choose one rule and write it in section 7. The rule that fits R23 is
that a session over the bound in the evaluated lane makes both gates "not evaluable: too large". If Rio Grande prefers
to drop such sessions, the report must carry the count and the spec must say the drop can move a verdict. Either way,
add a test in Task 25. Section 4 should also say that R(I), and so the N in the imprint spec's receipts, is counted
under this bound.

## Should-fix

- **S1. The account of the other specs is stale.** Update section 7, "On a full-store imprint" (spec lines 987 to
  999), section 14 and the plan's G6. The permissions spec's P36 (its line 621) now lets the owner's `imprint` and
  counted bulk uses that show nothing to any agent, "such as admission's calibration and the trail evaluation", read
  the owner's layer alone inside his home, and Rio Grande ruled that a co-subject's deny still refuses there. What is
  still open is the imprint spec's side (its section 8 and its section 18 hold), not a disagreement about this run.
- **S2. Test R24.** Add a test that `--evaluate` on an imprint holding an `imprint_subjects` table never reads it (a
  `sqlite3` authorizer that denies reads of that table), and that its report holds counts and rates only. Map R24 to
  that task in the plan's coverage table.
- **S3. Measure "added" so it can't under-count.** A difference of `ru_maxrss` misses memory that setup used and freed
  (TR29, plan line 175; plan line 3118). After setup, write `5` to `/proc/self/clear_refs` to reset the peak, then read
  `VmHWM` from `/proc/self/status` at the end. Or record `VmRSS` at setup.
- **S4. Bounded reading for the evaluation.** Spec section 12 runs `--evaluate` on a connection that refuses `fetchall`
  and large `fetchmany`; no task does. Add it to Task 23 or 25 and to the coverage row (plan line 3298).
- **S5. An independent reference.** Task 3 (plan line 631) compares `iter_trails` with `derive_trails`, which is
  `iter_trails` collected, so the equality says little. Compare with a test-only whole-table derivation.
- **S6. Small gaps in the arithmetic, all inside budget.** The pass opens three connections (`graph.db`, the
  read-only `categories_v2.db`, the scratch), not two: +2.0, 80.5 MiB. The pass's deque holds `SessionTrails`, full and
  revisit (plan line 985); if it keeps both, +22.7, 103.2 MiB. Say it keeps only the full trails, or count both. The
  evaluation's routing row leaves out W's and locate's 1,024-row float64 block (6.0), the angle arrays (0.5) and the
  lookup cache (4.2): 284.1 MiB.
- **S7. Say that `reflect` changed.** `suggested_touches` now counts the tool graph's sessions only. Name it in the
  revision 9 row and in the status line's "No other rule changes" (spec line 20).
- **S8. Units.** State in 10.1 that every peak also holds under 512 × 10⁶ bytes (488.3 MiB), so the vision's "512 MB"
  holds under either reading, and that only the cap `512M` (536.9 × 10⁶ bytes) relies on reading MB as MiB.
- **S9. The single-row case.** "At most 1,000 rows or 8 MiB" (R21) should say "or one row". The `Reader`, the
  embedder check and W each hold one episode's whole text, which engram does not cap. Read long text in pieces, or
  skip it and count it. (This can go with M1.)
- **S10. One figure for counting R(I).** 10.1's row adds 47.0 MiB to `imprint.py admit`; the I7 ask adds 37.0 to the
  imprint spec's 148. If `roads_and_trails` opens its own `Scratch`, add one connection (2.0) to the ask: 187.0. Both
  are under 384.
- **S11. The server's own peak.** "A server peaks near 320 MB" (`engram/CLAUDE.md:45`) was measured on 2026-10-02 on
  another machine. Task 28 records the server's setup figure on the Pi; compare it with 305.2 MiB in Results, since
  "433.2 MiB, inside 512" rests on it.
- **S12. Check for tmpfs.** `engram/CLAUDE.md:302` says `/tmp` is tmpfs on one of Andy's machines. Have `Scratch`
  refuse or warn when its directory is on tmpfs (`statfs` type `0x01021994`), instead of relying on the owner to set
  `TMPDIR` (TR28).

## Nits

- The imprint spec's line 1866 still says the trail spec's revision 8 loads the model in process; the next bullet
  corrects it. That is the imprint review's to fix.
- The tool call's 125.5 MiB adds A* and a forward lookup, but one call does one or the other, so the figure is
  conservative. Saying so would explain the 2.5 MiB margin.

## What holds

- Both of Andy's decisions are quoted as the vision records them, and every other choice is marked Rio Grande's call.
- Every figure in 10.1 and section 10 is right by its own arithmetic (tables above).
- Every new code citation is right: `engram/migrations/001_initial.sql:46-52`, `002_v3_layers.sql:51-59` and `:62`,
  `025_operation_log.sql:13`; no index on `episodes.session_id` in any migration; `engram/embeddings.py:70-71`,
  `:73-74`, `:133-134`, `:137-153`, `:151-153`, `:158-163`, `:171-177`, `:191-196`, `:200-207`;
  `scripts/superyak-embedder.service:13`; `engram/pyproject.toml:9`; `engram/CLAUDE.md:45`.
- `embedder_service.py` imports no fastembed at module level (its import is inside `main`, line 131), so
  `RemoteEmbedProvider._call` keeps `trails.py` free of it, as Task 20's test needs.
- Tool calls run one at a time under the lifecycle lock (`engram/server.py:654-680`, `:1314`), so "one call" in 10.1
  is right.
- The withdrawal of the in-process model is complete in the spec and plan: R19, step 8.2, step 7's provider field,
  section 11, Task 20, Task 24 and FS1.
- This Pi has 16 GB (`free -m`: 16,218 MiB) and `/tmp` on ext4 (`findmnt`), as the plan says.

## Response (the reviser, 2026-10-26)

Applied to the spec (still revision 9, "with the fixes from its fresh check", uncommitted on `trail-arrows-spec`) and
to its plan. Nothing is committed, pushed or posted, and no code changed. Every choice here that isn't Andy's is
marked "Rio Grande's call" in the spec. Code claims were read again in this worktree. New measurements were made on
this Pi with the system Python 3.11.2, SQLite 3.40.1 and `tracemalloc`, in scripts and files under the session
scratchpad and `/var/tmp`, all removed; none touched the repository. Every `## ` and `### ` heading of HEAD is still
in the spec, and every `## ` and `### Task` heading of the pre-edit plan is still in the plan (Task 20's title changed
in revision 9, on purpose). Both files end with a newline, the code fences still pair (spec 2, plan 120), and every
table keeps one column count.

**M1 (a session bounded by rows, not bytes). Done.** I confirmed the cause: `recall`'s `max_results` defaults to 20
and is not capped (`engram/server.py:2068`), and the row logs `scored[:max_results]` (`:2367`, `:2371`, `:2384`);
`operation_log.target_ids` is `TEXT NOT NULL` with no bound (`engram/migrations/025_operation_log.sql:9`). Your
figures hold: 16,384 × 18,982 = 311,001,088 bytes, 296.6 MiB; the pass would add 78.5 − 32.8 + 296.6 = 342.3, the
server reach 305.2 + 342.3 = 647.5, and evaluation deriving 176.9 − 32.8 + 296.6 = 440.7.
- *The id bound* (T 4, "The session bound"; R21; TR24). A session over 16,384 rows **or 327,680 ids** gets no trail
  and counts as `sessions_too_large`. The ids are its log rows' `target_ids` entries, counted with
  `json_array_length` while the `Reader` indexes (so such a session is never read), plus the recalled ids its episodes
  mention, counted as they stream past. From 10.1's own table, a row is 238 bytes plus 93 an id ((2,098 − 1,168) / 10
  = 93; 1,168 − 930 = 238). So one session holds at most 16,384 × 238 + 327,680 × 93 = 3,899,392 + 30,474,240 =
  34,373,632 bytes, 32.8 MiB, the figure every row already uses.
- *Beyond the check:* `EpisodeRow.mentions` was a `frozenset`. Measured, a frozenset costs about 100 bytes a mention
  at small sizes (an episode row: 413 bytes with none, 919 with 5, 2,455 with 20), more than an id in a row. The plan
  now keeps a sorted tuple that shares the recall rows' id strings: 192 bytes with none, plus 40 + 8 a mention.
- *What bounds one row* (T 4, "One value"; R25; TR30; with S9). Engram caps no text (`engram/server.py:1851` checks a
  10-character minimum only). SQLite reads a value whole for any function on it: on one 200,000,011-byte episode,
  `length(content)` and `substr(content, 1, 4000)` each raised a fresh process's peak from 9.8 to 202.8 MiB. SQLite's
  blob reader (`Connection.blobopen`) gives the length without reading, and 1 MiB pieces peaked at 15.4 MiB. So no
  text value over 1 MiB is read whole, by Python or by SQLite. Episode text is searched in 1 MiB pieces overlapping by
  63 bytes, which finds exactly the ids the whole text holds (ASCII ids in UTF-8). A log row whose `target_ids` is over
  1 MiB (about 26,000 ids at 40 bytes each, `engram/storage.py:1673`) makes its session too large; one whose `context`
  is over 1 MiB can't name its session unread, so it is `rows_unparsed`. Two blob lengths a row cost 1.34 s over
  200,000 rows (the plain scan: 0.40 s). An authorizer sees `typeof(content)` as a read but not `blobopen`, and
  `blobopen` refuses a NULL ("cannot open value of type null"); the plan's test uses both facts.
- *Tests.* Task 1 gains `test_a_session_over_the_id_bound_gets_no_rows_and_is_counted` (one wide row, and many
  mentions) and `test_one_value_is_never_read_whole` (an authorizer denies SQL reads of episode text; an id across two
  pieces; a long `target_ids`; a long `context`; `text_head`). Task 28's `bounds` store gains a session at both bounds
  (16,384 rows of 20 ids) and one at the id bound by few rows (1,638 rows of 200 ids, 327,600 ids), and a new
  `long_value` store (one 128 MiB episode) has two Pi tests: `roads_and_trails` and the evaluation each add under
  64 MiB. Task 28 now expects 17 passed (or 16), Task 29 seventeen skipped, Verification item 4 the same.

**M2 (three things that grew with the store). Done, and a fourth found.**
- *(a) T's and S's trails.* Bounded, not moved to SQL, so the next hit keeps using the tools' own `forward` (Rio
  Grande's call). T and each S hold at most 262,144 touches of full trails (`EVAL_MAX_TOUCHES`); past it, "not
  evaluable: too large". One bound serves both, since an S holds T's touches in another order. Sessions are scratch
  indices, not id strings. A graph's trails: touches 262,144 × 13 = 3,407,872; postings 262,144 × 4 = 1,048,576;
  sessions at most 262,144 / 2 = 131,072 (a trail has two touches or more) × 13 = 1,703,936; posting offsets
  20,001 × 4 = 80,004; in all 6,240,388 bytes, 5.95 MiB. Your figures check: 2 × 1,000,000 × 17 = 34,000,000 bytes,
  32.4 MiB (305.8); 2 × 2,000,000 × 17 = 68,000,000 bytes, 64.8 MiB (338.2).
- *(b) and (c) detours.* `find_detours` now yields one `Detour` at a time in TR11's order (T 5; TR11; Task 8). SQL on
  the scratch file pairs one key's routes (different lengths, no shared inner memory, saving over 0.25) and gives
  each pair's evidence (the earliest 14 and the latest by first touch), count and first and last touch. `Detour`
  carries `evidence`, `sessions: int`, `first`, `last` instead of a tuple of every session. Measured at its largest
  (47 distinct ids), one `Detour` is 5,351 bytes. The pass stops after its 32 (new Task 8 test with the cap patched to
  1); the evaluation writes training detours to the scratch file and each held-out session reads its own through a
  cursor (Task 23, `training_detours`).
- *(d) beyond the check: the split.* `Split` held two lists of session ids. 40,000 held-out sessions are a fifth of
  at most 200,000, so the lists could hold 200,000 × 93 = 18,600,000 bytes, 17.7 MiB. `Split` now holds the cutoff
  and two counts, and the scratch file marks each session (TR31).
- *10.1.* The pass: 3 connections 5.9 + 8 + 32.8 + 6.6 + 22.7 + 4.2 + 0.3 + one detour and its rows at most
  16,384 bytes, 0.02 → 80.5 MiB (exactly 80.43). Routing: 273.4 + 6.0 + 0.5 + 4.2 (your S6) + W's two texts and their
  request 2 × 16,000 × 29 = 928,000 bytes, 0.9 + T's trails 5.95 + one S's 5.95 → 296.9 MiB. Building B: 220.65 +
  5.95 + lookups 4.2 → 230.8. Bootstrap: 252.65 + 5.95 + 4.2 → 262.8. With `imprint.py use`: 64 + 296.9 = 360.9 MiB.
  The 23.1 MiB left under 320 is the evaluation's margin now.

**M3 (the bound could move a verdict). Done, by the rule that fits R23** (T 7 step 3, "Sessions over section 4's
bound"; R26; TR31). Any closed session over the bound makes both gates "not evaluable: too large". Its lane can't be
known without reading it, so a session in any lane counts. The report carries `sessions_too_large` and `rows_unparsed`
in every run (step 7). Task 25 gains `test_a_closed_session_over_the_session_bound_makes_both_gates_too_large`, by
rows and by ids, with the session in the other lane. T 4 now says R(I), and so the N in the imprint spec's `admitted`
and use receipts, is counted under the bound: N leaves out such a session though its rows ship. `roads_and_trails`
takes `counts=` and gives that number, and I7 has a third ask: that admission show it beside N (Rio Grande's call).

**Should-fix.**
- **S1. Done.** Section 7 ("On a full-store imprint"), section 14 and G6 now say both specs follow P36 (permissions
  spec section 3 and 6.3, which names this run's `read` batches and counted bulk `route`); a co-subject's no holds,
  as Rio Grande ruled (M3 of that review); the imprint spec keeps such a memory home (its D27). What stays open is
  the side-by-side re-check, until which the imprint spec approves no imprint with `others.memories` above 0 (its
  section 8 and 18). P36 has moved since your check: it is now at that spec's lines 237 and 659, not 621.
- **S2. Done.** Section 12 and Task 25's `test_r24_a_run_on_a_full_store_imprint_reads_no_co_subject_row`: an
  authorizer denies every read of `imprint_subjects`, the run passes, and the report holds counts and rates only.
  Coverage row added.
- **S3. Done.** TR29, Task 28 and section 12: `VmRSS` and `VmHWM` at setup, then `5` to `/proc/self/clear_refs`, and
  `VmHWM` at the end; added = end `VmHWM` − setup `VmRSS`; whole = the larger `VmHWM`. Checked on this Pi: a freed
  200 MiB block left `VmHWM` at 208 MiB, the reset took it to 9, and a 50 MiB block after it read 59.
- **S4. Done.** Task 23's `test_the_evaluation_reads_through_bounded_cursors` (same report on `batch_only`), and the
  coverage row names Task 23.
- **S5. Done.** Task 3 compares `iter_trails` with `reference_trails`, a test-only whole-table derivation written
  from T 4 alone that imports only `canonical`, on a `varied` store that holds every case of T 4.
- **S6. Done**, as above: three connections; the deque keeps full trails only (events hold them, and the revisit view
  is derived again in step 3); routing gains 6.0, 0.5 and 4.2. Also beyond the check: lookups in building B and the
  bootstrap (the cache lives the whole run), W's texts (0.9), and the embedder check's one text, 65,536 × (1 + 4 +
  4 × 6) = 1,900,544 bytes, 1.8 MiB, which runs before routing and fits inside it.
- **S7. Done.** The status line and the revision 9 row say `reflect`'s suggested touches now come from the tool graph.
- **S8. Done.** 10.1, "Units": 512 × 10⁶ bytes = 488.3 MiB; the largest figure, 433.2 MiB, is 454.2 × 10⁶ bytes;
  only `512M` = 536,870,912 bytes reads MB as MiB.
- **S9. Done** with M1: "or one row" in R21, 10 and 10.1; pieces for episode text; W reads at most 16,000 bytes a
  text; the embedder check takes episodes of at most 64 KiB and counts `check_skipped_long` (a small rule change, Rio
  Grande's call); a summary reads at most the first 1 MiB (6.5), which the tool call's "one summary's text at most 1"
  had assumed and nothing enforced.
- **S10. Done, with a different number from yours.** One figure, 10.1's 47.0 MiB (32.8 + 4.2 + 8 + 2.0). The imprint
  spec's revised 14.1 now adds it whole to its own 128 + 7.8 + 8 + 3 = 146.8, so 193.8 MiB, under 384. Your 187.0 kept
  one batch; that spec counts its batch and ours. I7 and the plan's note now give 193.8 and withdraw 185.0.
- **S11. Done.** 10.1 says the 320 MB was not measured on the Pi (`engram/CLAUDE.md:44-45`; its `:302` describes a
  tmpfs `/tmp`, and the Pi's is ext4). Task 28 records the server's setup `VmRSS`, and "Results" has a row for it
  against 305.2 MiB.
- **S12. Done, by another means.** `Scratch` reads its directory's filesystem type from `/proc/self/mountinfo` and
  refuses `tmpfs` and `ramfs` with `ScratchOnRam`, naming `TMPDIR` (TR28; Task 1 test). `os.statvfs` has no
  filesystem type, and `statfs` through `ctypes` needs a per-architecture struct; mountinfo is plain text. Where it
  doesn't exist (macOS), nothing is checked.

**Nits.** The tool call's 125.5 MiB is now called a little high in 10.1, since one call does A* or a forward lookup,
not both. The imprint spec's line about revision 8's in-process model is that spec's to fix; not edited here.

**Not changed, and why.** The object sizes in 10.1's table stay as they were. The plan's frozen dataclass measures
larger (2,248 bytes with 20 ids by your count, 2,199 by mine), so one session can reach 16,384 × 2,248 = 36,831,232
bytes, 35.1 MiB, 2.3 MiB over the figures; 10.1 now says so, and every design peak has more room than that. The CLI's
`TrailGraph.detours` list stays: it is over the bounded tool graph, not the store.
