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

## Re-check (a fresh reviewer, 2026-10-26)

**Reviewer:** a fresh reviewer acting in Andy's place (station law section 3). I took no part in writing, checking or
fixing this amendment.
**What I read:** the spec and plan at `c795c59` (`git diff e084597`), this file's check and response, the vision's
principle 4 and "Open for Andy", the permissions review's "Controller rulings on the check", and the permissions and
imprint specs at `c795c59`: P36 (permissions spec lines 659-698), its sections 15 and 19, and the imprint spec's
header, section 8 ("Carried co-subjects in the meet", its lines 1185-1224), 10, 14.1, 17 and 18. The working tree's
only change is to the imprints review, which I didn't touch. "Spec line N" and "plan line N" are at `c795c59`.
**Verdict: approve with one change to the plan.** Every must-fix of the check is resolved in the spec, and M1 and M2
are resolved in the plan too. One part of M3 is not. The plan finds a session over the bound in a way that misses
two of the four things the bound counts (RM1). The fix touches only the plan: TR31, Task 23 and Task 25's test.
Andy's two decisions are carried in his words, and the three specs agree on P36 and on what an imprint carries. Two
budget figures need aligning across specs (RS4, RS5). Once RM1 is applied, which a reader can confirm in those three
places, nothing else blocks.

### The check's must-fix items

- **M1. Resolved.** Section 4, "The session bound" (spec line 298), bounds a session by 16,384 rows and 327,680 ids,
  counting its log rows' `target_ids` and its episodes' mentions. "One value" (spec line 321, R25) keeps any text
  value over 1 MiB from being read whole. The cause reads as stated: `max_results: int = 20` with no cap
  (`engram/server.py:2068`), the row logs `scored[:max_results]` (`:2367`, `:2380-2386`), `target_ids TEXT NOT NULL`
  (`engram/migrations/025_operation_log.sql:9`), and `remember` checks only a 10-character minimum
  (`engram/server.py:1850-1852`). `json.dumps` writes each uuid id as 36 characters, 2 quotes and a 2-byte separator,
  40 bytes (`engram/storage.py:1673`), so 1 MiB holds 1,048,576 / 40 = 26,214. The arithmetic holds:
  (2,098 − 1,168) / 10 = 93 bytes an id, 1,168 − 930 = 238 a row, and 16,384 × 238 + 327,680 × 93 = 3,899,392 +
  30,474,240 = 34,373,632 bytes = 16,384 × 2,098, 32.78 MiB. An episode row with k mentions (192 + 40 + 8k bytes,
  10.1's table) costs less than a row with k ids (238 + 93k) for every k, so the bound covers episode rows too. Task 1
  tests a wide row, many mentions, an id across two pieces, a long `target_ids` and a long `context` (plan lines
  405-436). Task 28's stores hold both session bounds and a 128 MiB value.
- **M2. Resolved.** (a) T and each S hold at most 262,144 touches of full trails (R23; `EVAL_MAX_TOUCHES`, plan line
  113; Task 25's parametrize, plan line 2996). Each graph's trails take 3,407,872 + 1,048,576 + 1,703,936 + 80,004 =
  6,240,388 bytes, 5.95 MiB. An S can't hold more touches than T, since shuffling a trail of at most 512 touches and
  collapsing repeats only removes touches. (b) and (c) `find_detours` yields one `Detour` at a time from SQL on the
  scratch file (section 5, "In bounded memory"; TR11; Task 8). Task 8's new test (plan line 1274) has exactly two
  detours in its fixture, (a, y) and (p, r), each run by 3 + 3 = 6 sessions, as it asserts. The other candidate keys
  either share an inner memory or have no shorter side. (d) `Split` holds a cutoff and two counts (TR31), and
  200,000 × 93 = 18,600,000 bytes, 17.74 MiB, as stated.
- **M3. Resolved in the spec, not fully in the plan.** Section 7 step 3 (spec line 1245) makes any closed session over
  the bound, in any lane, turn both gates to "not evaluable: too large". Step 7 puts `sessions_too_large` and
  `rows_unparsed` in every report. Section 4 says R(I), and so N, is counted under the bound (spec line 316). The plan
  detects such a session less widely than the spec's rule (RM1).

### The check's should-fix items and nits

All twelve are applied as the response says. I found each in the text: S1 (spec lines 1048-1067, section 14, G6 at
plan line 3402); S2 (plan line 3016, coverage row at 3472); S3 (TR29, plan line 183, and section 12); S4 (plan line
2754); S5 (plan line 703, but see RS2); S6 (10.1's pass and routing rows); S7 (spec lines 19-20 and 87); S8 (spec
lines 1622-1625); S9 (R25); S10 (I7 and the imprint spec's 14.1 row, both 193.8); S11 (10.1 and the Results row); and
S12 (TR28 and Task 1's test). Both nits are taken, and the imprint spec's stale line about revision 8's in-process
model is gone.

### The three specs on P36

They agree on all three points.

- **Whom it covers.** P36: the requester acts for the owner, P and H are inside the owner's home, and the use is his
  `imprint` into a copy kept there or a bulk use, named or counted, together with the uses their `need` adds. The
  imprint spec's section 8 says the same in the same terms. The trail spec's section 7 (spec lines 1053-1067) names
  the same two kinds of use and leaves the decision to the other two specs ("This spec decides none of it"). It drops
  "his" before "bulk use" (RN3), as the permissions spec's own section 19 does.
- **A co-subject's no still refuses.** All three specs say so. P36 reads each other subject's layer as a restriction
  layer, ⟦L⟧ = 𝒰 \ D_L, so silence and a missing layer pass and a deny refuses with `DENIED`. The imprint spec keeps
  such a memory at home (`denied(m)`, D27). The trail spec cites Rio Grande's ruling (M3 of the permissions review).
- **Nothing that shows content to an agent, or leaves the home, is covered.** P36's "What it never covers" says so.
  The imprint spec says "Outside the owner's home no use qualifies", and that a use that shows content doesn't qualify
  inside the home either. The trail spec's R24 says the run reads no co-subject row, shows nothing to any agent and
  lets only counts and rates leave. Any use outside the owner's home still needs those people's yes.

### What an imprint carries

The specs agree here too. With `route`, episodes keep `session_id` and log rows ship only for sessions closed at t₁,
and log rows only inside the plan's dates. A recall row ships only when every target that isn't an instinct ships,
and its context is cut to `recall_id` and `session_id`. `route_shown` rows are cut to what ships and dropped when
nothing is left, and citing operations ship only when all their targets do. Without `route`, no session id and no log
row ship (imprint spec D7, D35; trail spec section 7). Cold storage never ships. A copy kept in the owner's home
carries its co-subjects in `imprint_subjects` (imprint spec D43, its line 738). The permissions spec's 7.4 and P25
treat those rows as the copy's subjects, and the trail evaluation never reads them (R24, Task 25). Since a recall
row's context is cut, the "One value" rule for a long `context` can't fire on an imprint. It matters on a plain copy.

### The memory budget across the specs

All three specs use one unit, 2²⁰ bytes, and one rule. Every process this work adds stays under 512 MiB, and the use's
unit has `MemoryMax=512M`. The evaluation's design peak is 384 − 64 = 320 MiB beside `imprint.py use` (imprint spec
14.1, its line 2319). Counting R(I) is the same figure in both specs: 47.0 MiB, with admission at 128 + 7.8 + 8 + 3 +
47.0 = 193.8 MiB (its line 2317). Two figures tell different stories (RS4, RS5), and some cross-references are stale
(RS6).

### The figures, redone

I redid every figure in sections 4, 7, 10.1 and I7 with a script in the session scratchpad. It takes 1 MiB as
1,048,576 bytes and one connection as 2,048,000 bytes. Each figure matches the spec to the rounding it shows. Where
the last digit differs, the spec rounded its parts first:

| Figure | Exact, MiB | Spec |
|---|---|---|
| Observer pass: 6,144,000 + 8 MiB + 34,373,632 + 6,946,816 + 23,789,568 + 4,358,144 + 323,705 + 16,384 bytes | 80.43 | 80.5 (80.52 from rounded parts) |
| Tool graph held: 61,440,000 + 3,260,000 + 200,000 + 6,553,600 + 3,407,872 + 868,352 + 1,048,576 bytes | 73.22 | 73.2 |
| Build: deriving, aggregating, reading vectors | 66.53, 31.84, 83.13 | 66.6, 31.9, 83.1 |
| A tool call: 73.22 + 6.0 + 0.46 + 40.0 + 3.81 + 1 + 1 | 125.49 | 125.5 |
| Counting R(I): 32.8 + 4.2 + 8 + 2.0 | 47.0 | 47.0 |
| Evaluation, deriving: 128 + 3.9 + 8 + 32.8 + 4.2 | 176.9 | 176.9 |
| Evaluation, building B: + T's trails 5.95, lookups 4.16, B 7.63, tiles 1.5 + 6.0 + 2.0, candidates 3.66 | 230.76 | 230.8 |
| Evaluation, routing: 273.48 + 6.0 + 0.46 + 4.16 + 0.89 + 5.95 + 5.95 | 296.89 | 296.9 |
| Evaluation, bootstrap: its parts + 64 × 40,000 × 16 = 40,960,000 bytes (39.06) | 262.76 | 262.8 |
| The embedder check's one text: 65,536 × (1 + 4 + 4 × 6) = 1,900,544 bytes | 1.81 | 1.8 |
| With `imprint.py use`: 64 + 296.9; the margin, 320 − 296.9 | 360.9; 23.1 | 360.9; 23.1 |
| Units: 512 × 10⁶ bytes; 433.2 MiB in 10⁶ bytes | 488.28; 454.24 | 488.3; 454.2 |
| The whole Pi: 1.1 × 10⁹ bytes; 2,048 − 1,049 − 512 | 1,049.04; 487 | 1,049; 487 |
| Admission counting R(I): 128 + 4 × 1.95 + 8 + 3 + 47.0 | 193.81 | 193.8 |

The factor 29 in W's texts (2 × 16,000 × 29 = 928,000 bytes) and in the check's text matches the code.
`send_message` builds the request with `json.dumps`, then encodes and frames it (`engram/embedder_service.py:57-59`),
and `json.dumps` escapes a control or non-ASCII character in up to 6 bytes for each byte of text. So the text is held
as bytes (1), as a string (at most 4), and as four copies of the request at up to 6 each (24). The other checks:
156 × 64 + 16 = 10,000 resamples; 16 searches × 10,000 expansions = 160,000; 16,384 × 2,248 = 36,831,232 bytes,
35.12 MiB, 2.34 over 32.78; 2 × 1,000,000 × 17 = 34,000,000 bytes, 32.42 MiB; and 2 × 2,000,000 × 17 = 68,000,000
bytes, 64.85 MiB.

### Plan against spec

The plan carries every fix. The constants (plan lines 96-117) include the six new ones. Task 1's 12 tests match its
"12 passed", Task 3's 6 match its "6 passed", and Task 23's 12 match its "12 passed". Task 28 has 6 processes × 2
stores = 12 peak tests, plus 2 long-value tests and the times, embedding and answers tests, 17 in all. That matches
Task 29's "seventeen skipped" and verification item 4's "17 passed, or 16". The coverage table maps R21, R23, R24,
R25 and R26 to tasks. The spec keeps all 22 `## `/`### ` headings of `e084597` and adds "Decisions in revision 9" and
"10.1 Memory on a small Pi". The plan keeps all 42, with Task 20's title changed on purpose. Both files end with a
newline, and code fences pair (spec 2, plan 120).

### Code claims

Each new citation reads as stated: `engram/server.py:2068`, `:2367`, `:2380-2386`, `:1850-1852`;
`engram/storage.py:1673`; `engram/migrations/025_operation_log.sql:9`, `:13`; `001_initial.sql:46-52`;
`002_v3_layers.sql:4`, `:51-59`, `:62`; `engram/pyproject.toml:9` (`>=3.12`); `engram/embedder_service.py:57-59`;
`engram/CLAUDE.md:44-45`, `:302`; and `scripts/superyak-embedder.service:13`. No migration declares `WITHOUT ROWID`,
so the blob reader can open every table TR30 names. Every MCP tool runs as a `_server_operation` under the lifecycle
lock (`engram/server.py:653-683`, `:690-697`).

### Must-fix

**RM1. The plan only detects a session over the bound when the index shows it.** TR31 (plan line 185) has `evaluate`
count closed sessions over the bound "from the `Reader`'s index". Task 23 does that "before it loads anything" (plan
line 2787). By TR24 (plan line 178), that index holds episodes, `recall` and `route_shown` rows, and those log rows'
ids. `operation_log` rows and their ids are counted only later, in `rows(info)`, and episode mentions only while the
episodes stream (plan lines 473-477). A closed session that passes the bound only through those is found while
`ScratchTrails.load` runs. It is counted and left out of T, every S and the held-out set, and both gates still
decide. That is the sample that section 7 step 3 and R26 forbid (spec line 1245): the check's M3 again. Two examples:

- A session of 10,000 recall rows and 7,000 `operation_log` rows has 17,000 rows, over 16,384, but its index shows
  10,000.
- A session of 8,192 recall rows of 39 ids and 8,192 episodes that each mention 2 of them holds 319,488 + 16,384 =
  335,872 ids, over 327,680, but its index shows 319,488. Its 16,384 rows are at the row bound, which is allowed.

The report would then show `sessions_too_large: 1` beside a pass. Task 25's test (plan lines 3004-3014) can't tell
the difference, because WIDE's 13 rows and 48 ids are all recall rows, which the index sees. Fix: decide after
loading, on the `Reader`'s count, `counts["sessions_too_large"]`. By then that count covers every closed session in
every lane, since `iter_trails` reads each one. The early check from the index can stay as a shortcut. Add two cases
to Task 25's parametrize: a session over the bound by `operation_log` rows, and one over it by mentions. The spec
already states the rule this way; only TR31, Task 23's interface and step 3, and the test change.

### Should-fix

- **RS1. Two stale test counts.** Task 6 gained `test_the_pass_holds_no_whole_store_and_leaves_no_scratch` and now
  expects 9 (plan line 1085). Task 7 adds 6 tests and Task 8 adds 5, and both run the whole file. So they should
  expect 15 and 20, not 14 (plan line 1193) and 19 (plan line 1349). At `e084597` the counts were 8, then 8 + 6 = 14,
  then 14 + 4 = 18.
- **RS2. Task 3's reference keys.** The test builds keys `(session_id, lane)`, since `SessionTrails.full` is keyed by
  lane (plan line 630). But `reference_trails` is documented as returning `{(session, (session, lane)): digest}`
  (plan line 712), so the comparison can't be equal as written. Document `{(session, lane): digest}`.
- **RS3. Test R(I) under the bound.** Task 4 gives `roads_and_trails` and `count_roads_and_trails` a `counts=` that
  counts sessions over the bound (plan lines 755-758), and R26 says N leaves them out. But none of Task 4's seven
  tests passes `counts` or plants such a session, and the coverage row for R26 names only Task 25 (plan line 3484).
  Add one test. Also say whether such a session counts once or once per lane: `count_roads_and_trails` sums one call
  per lane, and so does admission (imprint spec section 10), so with two lanes one session would count twice.
- **RS4. The whole Pi, told two ways.** 10.1 (spec line 1742) and G15 (plan line 3411) leave 2,048 − 1,049 − 512 =
  487 MiB for the system and the lighthouse. The imprint spec's 14.1, after its check's S6, takes a 2 GB Pi's usable
  memory as 2,048 − 165 = 1,883 MiB and keeps 256 MiB free. That leaves 1,883 − 256 − (1,049 + 512) = 66 MiB, which
  it calls "unlikely to be enough". Both sums are right, but they answer different questions. The imprint spec's
  deploy gate is the one that decides, so 10.1 and G15 should give or cite its figure. Otherwise a reader may take
  487 MiB as room to spare.
- **RS5. One engram server, two specs' additions.** 10.1 holds what trails add to a server to 128 MiB, and calls
  433.2 MiB "the largest figure" (spec line 1624). The permissions spec adds up to 183.1 MiB to the same process when
  `permit` runs `perform` (its lines 2032-2036). Tool calls run one at a time, but the held tool graph stays resident,
  and the pass lets calls in between its batches. So a server with both on can reach 320 + 73.2 + 183.1 = 576.3 MiB,
  or 320 + 80.5 + 183.1 = 583.6 MiB while a pass waits on a `permit` call. With 320 MB read as 10⁶ bytes, the first is
  305.2 + 73.2 + 183.1 = 561.5. Neither spec bounds the server, since this work doesn't add it, so no rule breaks.
  But 10.1 should say that the permissions spec adds to the same process and that together they pass 512 MiB. Rio
  Grande may want one server figure across both specs.
- **RS6. For the other specs' revisers** (not this amendment's files).
  - The imprint spec's 14.1 row (its line 2317) still calls 185.0 "the trail spec's own sum (its I7)". I7 now
    withdraws that sum (spec line 1899).
  - Its section 17 (its lines 2709-2717) says the trail spec "asks two things back, both taken", and that this spec's
    answers "hold as written until that revision". I7 (spec lines 1882-1906) now asks three things. The third, showing
    `sessions_too_large` beside N, is neither taken nor declined.
  - The permissions spec's section 19 (its lines 2358-2361) says the trail spec cites "this section's finding of
    revision 7's first draft". Section 7 now cites P36.

### Nits

- **RN1.** Task 28's `long_value` store inserts 128 MiB of content in one SQL statement (plan line 3316). Episodes have
  an FTS insert trigger (`engram/migrations/002_v3_layers.sql:102`), so the parent also indexes that content in FTS5,
  as one token of 134,217,728 characters, under its own 512 MiB cap. Say so, or use content of short words.
- **RN2.** The plan doesn't say how the mention search runs. Testing each recalled id against each episode costs, for
  a session at the bounds with no mentions (8,192 recall rows of 40 ids, 327,680 ids, and 8,192 episodes), 327,680 ×
  8,192 = 2,684,354,560 substring tests. For the pass, that runs in the startup thread. Finding id-shaped tokens in
  each piece and looking them up keeps the cost linear in the text. Such a lookup holds the session's distinct ids. A
  set of 327,680 of them measured 16,777,432 bytes here, 16.0 MiB (a dict, 7.3 MiB). That isn't in 10.1, but it fits
  every budget: 80.5 + 16.0 = 96.5, under 128, and 176.9 + 16.0 = 192.9, under 320.
- **RN3.** Section 7 (spec line 1057) says "every bulk use inside his home". P36 and the imprint spec's section 8
  require that the requester acts for the owner. "His bulk uses" would match them.
- **RN4.** TR20 (plan line 174) still gives `roads_and_trails(conn, *, lane, as_of)`, while Task 4 adds `scratch` and
  `counts`.

## Re-check response (the reviser, 2026-10-26)

Applied to the spec (still revision 9) and its plan, uncommitted on `trail-arrows-spec`. Only those two files were
edited, and this section appended. Nothing is committed, pushed or posted, and no code changed. Every new choice is
marked "Rio Grande's call" in the spec. Code claims were read again in this worktree. New measurements were made on
this Pi with the system Python 3.11.2 and SQLite 3.40.1, in scripts and files under the session scratchpad; none
touched the repository. "Spec line N" and "plan line N" are in the working tree after these edits. Every `## ` and
`### ` heading of `HEAD` is still in each file (spec 24; plan 42, of them 29 `### Task`), both end with a newline,
code fences still pair (spec 2, plan 120), and no table changed its column count. The spec's one table whose rows
count differently, at its line 894 at `HEAD`, was so before (pipes inside code). The imprint and permissions specs
were being revised in parallel while I worked. I read them and edited neither.

**RM1. Done.** The cause reads as you state. TR24 (plan line 181) streams into the index only episodes, `recall` and
`route_shown` rows and those log rows' id counts. `rows(info)` counts the `operation_log` rows and ids, and the
mentions are counted while the episodes stream (Task 1 step 3, plan lines 473-481). Your examples hold:
10,000 + 7,000 = 17,000 > 16,384, and 8,192 × 39 = 319,488, + 8,192 × 2 = 16,384, gives 335,872 > 327,680, with
8,192 + 8,192 = 16,384 rows, at the row bound, which is allowed.
- *TR31* (plan line 188) now decides after `ScratchTrails.load` returns, on `counts["sessions_too_large"]`. The load
  reads `iter_trails`, which asks for the rows of every closed session in every lane, so by then each closed session
  over the bound has been counted once, by everything T 4 counts. The load is the evaluation's only `Reader`: the
  plan's other uses of `iter_trails` are Tasks 3, 4, 6 to 8 and 16, none in the evaluation. A run whose deadline
  passes during the load reports `limit`.
- *The index check as a shortcut: dropped, not kept.* It sees no operation row and no mention, so it can only
  short-cut. And it would then report the index's count, which differs from what the pass and `roads_and_trails`
  give for the same store. One count with one meaning is worth the time: a store with such a session pays for its load
  before the answer, and the load is bounded like any other.
- *Task 23.* `ScratchTrails.load` passes `counts` to `iter_trails` (plan line 2683). `evaluate`'s interface and
  step 3 (plan line 2811) read the count once the load has returned, before the split, and build nothing more when it
  is above 0.
- *Task 25* (plan lines 3032-3058). The parametrize has four cases: by recall rows (13 > 10) and by recall ids
  (48 > 30), as before; by `operation_log` rows (the index shows 2 rows, and 2 + 9 operation rows = 11 > 10); and by
  mentions (the index shows 20 ids, and one episode that mentions all 20 makes 40 > 30). A `seen` column checks what
  the index alone shows of WIDE, (13, 48), (2, 2) and (21, 20), so the two new cases are ones the old rule would
  pass. The coverage row says so (plan line 3543).
- *The spec.* Section 7 step 3 (spec line 1265) says that the run decides once it has read every closed session, and
  gives your two examples. R26 and section 12's test item (spec line 2102) say the same.

**RS1. Done.** Task 6 has 9 test functions: 8 in step 1, plus `test_the_pass_holds_no_whole_store_and_leaves_no_scratch`
in step 3. Task 7 adds 6 and Task 8 adds 5, none parametrized. So 9 + 6 = 15 (plan line 1214) and 15 + 5 = 20 (plan
line 1370). At `e084597` it was 8, then 8 + 6 = 14, then 14 + 4 = 18, as you say.

**RS2. Done.** `reference_trails` returns `{"full": {(session, lane): digest}, "revisit": {(session, lane): digest}}`,
keyed as the test keys `iter_trails`' results (plan lines 714-719).

**RS3. Done. Such a session counts once** (Rio Grande's call). Its lane can't be known without reading it, so every
lane's call reads every closed session and counts the same ones. A sum over two lanes would count one session twice,
and K is meant as a count of sessions. TR20 (plan line 177) gives the full signatures, which also answers RN4.
`count_roads_and_trails` gives each lane's call its own `Counter` and adds the first lane's number only. Task 4's new
`test_r26_n_leaves_out_a_session_over_the_bound_and_counts_it_once` (plan line 840) works as follows. Three
sessions S0 to S2 of 2 rows each give 3 trails and 1 road. WIDE has 12 rows and gives 1 more trail and no road, so
N = 5. With `SESSION_ROWS_MAX` patched to 10, the work lane gives N = 4 and the personal lane 0. Each call counts WIDE
once, and `count_roads_and_trails` gives 4 and counts it once. The coverage row now names Task 4. The spec says this in
section 4 (spec lines 332-335), R26, I7 and section 12. The imprint spec, revised in parallel, now keeps K as "the
largest of the lanes' counts" until this spec answers. Every lane's count is equal, so that is this number and the
two agree. I7 and the plan's note for the imprints plan say so, and that plan should take K the same way.

**RS4. Done.** 10.1's "The whole Pi" (spec line 1778) and G15 (plan line 3470) still give 487 MiB, now "of the 2,048",
and say it is not room to spare. They then give the imprint spec's deploy-gate figure. It takes a 2 GB Pi as
2,048 − 165 = 1,883 MiB, where 165 = (16,777,216 − 16,608,224) kB / 1,024 = 165.03. It keeps 256 MiB available, so
everything must fit in 1,883 − 256 = 1,627. One job and the embedder take 1,049 + 512 = 1,561, which leaves
1,627 − 1,561 = 66 MiB, "unlikely to be enough". I cite that spec's 14.1 and its section 18 bullet "Memory on the Pi"
by name, not line, since that file is still moving.

**RS5. Done.** 10.1 has a new paragraph, "One server, two specs" (spec line 1767), and "Units" now calls 433.2 MiB
the largest figure of this spec's own. The permissions spec's 183.1 is at its section 15, "Memory", in the bullet "The
engram server" (its line 2077 in the working tree, 2034 at `HEAD`). Tool calls run one at a time:
`_server_lifecycle_lock` is a `threading.RLock()` (`engram/server.py:196`), held by `_server_operation` around every
tool (`:653-683`, `:690-697`). The pass reads `graph.db` outside that lock (TR9), so a `permit` call can run while the
pass is at its peak. The sums are 305.2 + 73.2 + 183.1 = 561.5 and 305.2 + 80.5 + 183.1 = 568.8, or, reading 320 MB
as MiB, 320 + 73.2 + 183.1 = 576.3 and 320 + 80.5 + 183.1 = 583.6. Each is over 512. The paragraph says that no rule
breaks, since neither spec bounds the server, and it leaves one server figure to Rio Grande. It sets none and adds no
new rule.

**RS6. Read, not edited** (not this amendment's files). In the working tree as of this response, those specs'
revisers have already made all three changes. The imprint spec's 14.1 row for admission gives 193.8, "the sum the
trail spec now gives too", and no "185.0" is left in that file. Its section 17 says "three things back, all taken"
and notes that its earlier count missed the third. The permissions spec's section 19 now says that the trail spec
"says that both specs follow P36". One new point for the imprint side comes from RN2 below: one session can run
7.8 MiB over 10.1's figures, so admission's 193.8 can reach 193.8 + 7.8 = 201.6, still under 384.

**Nits.**
- **RN1. Done, and it was more than a nit.** Task 28's parent runs under the same 512 MiB cap. On this Pi, a fresh
  process (10.2 MiB at the start) peaked as follows. With the FTS trigger in place: `hex(zeroblob(67108864))` in one
  statement, 716.4 MiB; `replace(..., '0000', 'abc ')` for short words, 620.4. Without the trigger: 332.2 and 460.0.
  So the fixture as written would have been killed. The fixture (plan line 3362) now drops `episode_fts_insert`,
  inserts `CAST(zeroblob(134217728) AS TEXT)` with every column set, creates the trigger again and writes
  `b"abc " * 262_144` 128 times through `blobopen`. That peaked at 267.8 MiB, or 396.2 with the trigger kept. A blob
  write fires no trigger: with all three triggers in place, FTS had no hit for `abc` afterwards. The value stays TEXT,
  not a BLOB. `length()` raised the peak by 130.5 MiB on a 128 MiB TEXT row but by 0.5 on a BLOB, so a BLOB would hide
  a regression to `length(content)`. It is the fixture's last write, and nothing updates or deletes that row. The
  update and delete triggers would ask FTS to delete content it never held, which the migration's own comment says
  fails as "database disk image is malformed" (`engram/migrations/002_v3_layers.sql:107-121`).
- **RN2. Done, with a smaller structure than either one you measured.** TR24 (plan line 181) and T 4 step 3 (spec line
  302) say how the search runs. Each piece is scanned once with a regular expression, as a lookahead so that
  overlapping matches count, for the lowercase uuid form engram writes (`str(uuid.uuid4())`, `engram/server.py:1866`,
  `engram/compress.py:538`). Each match is looked up by bisection in one sorted tuple of the session's distinct
  recalled ids, which shares the recall rows' strings. `Storage.add_episode` takes its id from the caller
  (`engram/storage.py:553-572`), so a recalled id of any other form is searched for directly. The result is exactly
  what a substring search finds. Measured here, one 1 MiB piece took 107.3 s against 327,680 ids one at a time, and
  0.033 s for the scan. The tuple holds 40 + 8 × 327,680 = 2,621,480 bytes, 2.5 MiB. It peaks at 5,761,832 bytes,
  5.5 MiB, while it is sorted from the rows' ids and deduplicated in order. Building it from a set first peaked at
  25,166,728 bytes, 24.0 MiB. A dict held 7,689,648 bytes (7.3 MiB) and peaked at 11.0. 10.1 (spec line 1705) adds
  the 5.5 MiB to the dataclass's 2.3: 2.3 + 5.5 = 7.8 MiB over the figures. That still fits everywhere: the pass
  80.5 + 7.8 = 88.3 under 128, the build's deriving 66.6 + 7.8 = 74.4 under 128, counting R(I) 47.0 + 7.8 = 54.8
  (admission 201.6, under 384), and the evaluation's deriving 176.9 + 7.8 = 184.7 under 320. Task 3's `varied` store
  gains a cited memory whose id is not in uuid form, so the reference also checks the direct path.
- **RN3. Done.** "his bulk uses inside his home that show nothing to any agent" (spec line 1073).
- **RN4. Done** in TR20, as under RS3.

**Not changed, and why.** The early check from the index is gone, not kept as a shortcut (RM1, above). 10.1's rows
keep their figures, 47.0 for counting R(I) among them. The tuple is noted beside them, as the dataclass's 2.3 MiB
already was, so the 193.8 the imprint spec carries doesn't move again. Every design peak has room for both.

## Final check (2026-10-26, a fresh reviewer)

**Reviewer:** a fresh reviewer acting in Andy's place (station law section 3). I took no part in writing, checking,
re-checking or fixing this amendment.
**What I read:**
- the spec and plan as they stand in the worktree (`git diff HEAD`, uncommitted on `trail-arrows-spec`, HEAD
  `c795c59`);
- this file's re-check and its response;
- the vision (principle 4 and "Open for Andy");
- the permissions review's "Controller rulings on the check" and its own "Final check";
- the permissions and imprint specs, and the imprints plan, as they stand in the worktree;
- the code in this worktree, for every claim below.

"Spec line N" and "plan line N" are in the working tree. I edited nothing but this section, and ran no code.

**Verdict: approve.** RM1 is resolved in the plan and in the spec. The fixes add no must-fix, and the three specs
still agree. Two should-fix items and two nits follow. None changes a verdict or a rule.

### RM1

**Resolved.** The evaluation now decides on the session bound only after it has read every closed session.
- **TR31** (plan line 188) decides after `ScratchTrails.load` returns, on `counts["sessions_too_large"]`. It never
  decides from the index alone, not even as a shortcut.
- **Why the count is complete by then.**
  - `iter_trails` yields every closed session, newest first, with empty dicts when a session has no trail (plan line
    637). It asks the `Reader` for each session's rows as it reaches that session (line 731).
  - The load reads `iter_trails` into the scratch file and passes it `counts` (lines 2680-2685). So `rows(info)` runs
    for every closed session, in every lane.
  - `rows(info)` counts the session's `operation_log` rows and ids before it reads anything (TR24, line 181; Task 1
    step 3, line 476). It counts the episodes' mentions as they stream (lines 480-481).
  - Only closed sessions are read, which is the spec's "any closed session up to `as_of`" (spec line 1264).
- **A deadline during the load** gives `limit` for both gates (TR31), so a partial count never decides.
- **Task 23.** Its interface (lines 2683-2685, 2709-2712) and step 3 (lines 2811-2815) read the count once the load
  has returned, before the split, and build nothing more when it is above 0.
- **Task 25's test** (lines 3032-3058) now has four cases. I redid each count:
  - by recall rows: 12 + 1 = 13 rows, over 10;
  - by recall ids: 12 × 1 + 36 = 48 ids, over 30;
  - by `operation_log` rows: the index shows 2 rows and 2 ids, and 2 + 9 = 11 rows, over 10;
  - by mentions: the index shows 20 + 1 = 21 rows and 20 ids, and 20 + 20 = 40 ids, over 30.
- **The test pins what the old rule missed.**
  - The `seen` column asserts what the index alone shows (line 3054). The old rule would pass both new cases:
    2 ≤ 10 and 20 ≤ 30.
  - In each new case the part counted later is under the bound on its own: 9 ≤ 10 and 20 ≤ 30. So the test also
    pins that `rows` adds the index's rows and ids to the later part, as the spec counts them (spec line 312).
  - The figures depend on the walked memories having no session. `create=True` makes them that way (plan lines
    710-712).
  - `operation(...)` and `episode(None, ...)` are Task 1's helpers (plan line 338 and the tests at 416 and 428).
    `"share"` is a non-citing operation that Task 2 already uses (line 543).
  - "Exactly 1" (line 3058) also catches a fixture in which planted sessions exceed the patched bounds.
- **The spec agrees.**
  - Section 7 step 3 (spec lines 1261-1271), R26 (spec line 155) and section 12 (spec lines 2101-2105) all say the
    run decides after reading every closed session.
  - Its examples hold:
    - 10,000 + 7,000 = 17,000 rows, over 16,384;
    - 8,192 × 39 = 319,488 ids, and 319,488 + 8,192 × 2 = 319,488 + 16,384 = 335,872, over 327,680;
    - that session has 8,192 + 8,192 = 16,384 rows, which is not over the row bound.
- **Nothing old is left.** The coverage row (line 3543) and Verification item 7 (line 3627) say the gates are decided
  after the load. A grep finds no "before it loads anything" and no decision "from the `Reader`'s index" in either
  file.

### The re-check's other items

Each is in the text as the response says, and each figure checks.
- **RS1.** Counting `def test_` lines gives 9 tests in Task 6, 6 in Task 7 and 5 in Task 8, with no parametrize.
  So 9 + 6 = 15 (line 1214) and 15 + 5 = 20 (line 1370).
- **RS2.** `reference_trails` is keyed `{(session, lane): digest}` (lines 717-719).
- **RS3.** I redid Task 4's new test (lines 840-852):
  - S0 to S2 make 3 trails. Their step a→b runs from day 2 10:00 to day 3 11:00, which is 25 h = 90,000 s, at least
    60,480. That makes 1 road.
  - WIDE has 12 rows and 1 trail. Each of its 11 steps has 1 session, so it adds no road. So N = 3 + 1 + 1 = 5.
  - With the bound at 10, WIDE is over (12 > 10) and S0 to S2 are not (2 ≤ 10). Work gives 4, personal gives 0, and
    each counts WIDE once. `count_roads_and_trails` gives 4 + 0 = 4 and counts it once.
  - Task 4 now has 8 tests. Its step 4 gives no count, so no count goes stale.
- **RS4.** The imprint spec's figures (its lines 2436-2444 and 2870-2876):
  - 165 = (16,777,216 − 16,608,224) / 1,024 = 168,992 / 1,024 = 165.03;
  - 2,048 − 165 = 1,883 and 1,883 − 256 = 1,627;
  - 1,049 + 512 = 1,561 and 1,627 − 1,561 = 66 MiB;
  - 10.1 (spec lines 1778-1786) and G15 (plan line 3470) now carry them.
- **RS5.** The sums are 305.2 + 73.2 + 183.1 = 561.5, 305.2 + 80.5 + 183.1 = 568.8, 320 + 73.2 + 183.1 = 576.3 and
  320 + 80.5 + 183.1 = 583.6. The permissions spec gives the 183.1 (its line 2077). But see FS1.
- **RS6.** The other revisers made all three changes:
  - no "185.0" is left in the imprint spec;
  - its section 17 says "three things back, all taken" (its line 2846);
  - the permissions spec's section 19 says the trail spec "says that both specs follow P36" (its lines 2413-2414).
- **RN1.** The fixture (plan lines 3362-3376) drops and recreates the insert trigger. The cited lines read as stated:
  `engram/migrations/002_v3_layers.sql:102-105` is that trigger, and `:107-121` holds the delete and update triggers
  and the "database disk image is malformed" comment.
- **RN2.** The tuple's figures:
  - 40 + 8 × 327,680 = 2,621,480 bytes = 2.50 MiB, and 5,761,832 bytes = 5.49 MiB;
  - 2.3 + 5.5 = 7.8 MiB;
  - with that 7.8 added, every design peak still holds:
    - the pass, 80.5 + 7.8 = 88.3, under 128;
    - the build's deriving, 66.6 + 7.8 = 74.4, under 128;
    - counting R(I), 47.0 + 7.8 = 54.8, so admission at 193.8 + 7.8 = 201.6, under 384;
    - the evaluation's deriving, 176.9 + 7.8 = 184.7, under 320.
- **RN3.** Spec line 1073 says "his bulk uses", as P36 does (permissions spec line 241).
- **RN4.** TR20 (plan line 177) gives the full signatures.

### Do the fixes break an agreement?

No. I checked each point where the specs meet.
- **K, the count beside N.**
  - The trail spec counts each such session once. The count beside N is one lane's number (spec lines 332-335).
  - The imprint spec keeps K as the largest of the lanes' counts (its lines 1824-1829 and 2694-2695). The imprints
    plan does the same (its line 139).
  - Every lane's call reads every closed session, so all the lanes' counts are equal. The largest is then that one
    number, and both are 0 together.
- **Admission's memory.** Both specs give 193.8 MiB (imprint spec line 2403; trail spec 10.1 and I7). The 201.6 is
  the trail spec's note of the overrun, under the same 384.
- **The evaluation's unit.** It holds 320 MiB beside `imprint.py use`'s 64, in the use's 512 MiB unit (imprint spec
  lines 2072-2078).
- **P36.**
  - The meaning is unchanged. RN3 only brings the wording into line with P36's row and with 6.3, which names this
    run's `read` batches and its counted bulk `route` (permissions spec line 684).
  - A co-subject's deny still refuses, as Rio Grande ruled (permissions review, "Controller rulings", M3).
- **The engram server.** The permissions spec puts it at about 503 MB with `perform` alone (its lines 2075-2079). The
  trail spec's new paragraph and that review's final check (its FS6) both say that together they pass 512. Neither
  spec bounds the server.
- **The whole Pi.** The trail spec and the imprint spec both give 66 MiB under the imprint spec's deploy gate. The
  permissions spec gives no whole-Pi figure.

### Code claims

Each new citation reads as stated:
- `engram/server.py:196` is `_server_lifecycle_lock = threading.RLock()`;
- `:653-683` is `_server_operation`, which holds that lock around each call;
- `:690-697` is `_server_tool`, which wraps every tool;
- `:1866` and `engram/compress.py:538` write `str(uuid.uuid4())`;
- `engram/storage.py:553-572` is `add_episode`, which takes its id from the caller;
- `:1673` writes `json.dumps(target_ids)`;
- `engram/migrations/025_operation_log.sql:9` is `target_ids TEXT NOT NULL`, and `:13` is the index on `session_id`.

### Files

Both files are whole:
- Every `## ` and `### ` heading of HEAD is present, in order: spec 24, plan 42, 29 of them `### Task`.
- The code fences pair: 2 in the spec, 120 in the plan.
- Both files end with a newline.

### Should-fix

- **FS1. "One server, two specs" leaves out the largest case** (spec lines 1767-1776).
  - The build's reading-vectors phase holds 83.1 MiB (10.1, spec line 1750). That is more than the pass's 80.5.
  - The build runs in the maintenance thread and takes the barrier only to swap the graph in (spec lines 937 and
    2069). So a `permit` call can run during it: 305.2 + 83.1 + 183.1 = 571.4 MiB, or 320 + 83.1 + 183.1 = 586.2.
  - With RN2's 7.8 MiB overrun, the pass reaches 88.3, and 305.2 + 88.3 + 183.1 = 576.6.
  - The pass and the held graph never overlap: the pass runs before `prune` (spec line 436), and the build is the
    last maintenance step (line 1795). So the paragraph's own two cases are right as far as they go.
  - No rule changes. Give the largest figure, or say "at least". The permissions review's FS6 copies the paragraph's
    figures and should follow.
- **FS2. For the imprint side's revisers** (not this amendment's files). The rules agree; only the wording is behind.
  - The imprint spec's section 10 (its lines 1825-1827) still says the trail spec's re-check asks whether a session
    counts once, and "Until it says, K is the largest". The trail spec has now said: once, one lane's number.
  - The imprints plan's G19 (its line 4943) still lists RS3 and the RM1 change as "still waiting".
  - The imprint spec's section 17 (its line 2840) can say the RM1 change is made.

### Nits

- **FN1.** Section 12's item on the session bound (spec lines 2104-2105) says "the sum over lanes counts it once too". Read
  quickly, that clashes with section 4's "never the sum" (spec line 335). Suggested wording:
  "`count_roads_and_trails`, which sums N over the lanes, counts it once".
- **FN2.** TR24 (plan line 181) and section 4 step 3 (spec line 305) say the search finds "exactly" what a whole-text
  search finds.
  - That holds for ids of up to 64 bytes, the bound behind "One value"'s 63-byte overlap (spec lines 351-352).
  - Every engram writer makes 36-character ids: `server.py:1866`, `compress.py:538`, `engine.py:100`,
    `federation.py:196` and `:217`. But `add_episode` accepts any id.
  - Say "of up to 64 bytes" there too.

### What holds

- **Andy's decisions.** Both are carried in his words (A7, A8). Each new choice is marked Rio Grande's call: the timing
  of the decision (RM1), counting once (RS3) and the linear search (RN2).
- **The rest.** Nothing is committed, pushed or posted, and no code changed.
