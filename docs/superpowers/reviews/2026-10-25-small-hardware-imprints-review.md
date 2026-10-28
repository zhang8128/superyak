# Review: imprints spec revision 7 and its plan (small hardware, and the full store)

**Date:** 2026-10-26
**Reviewer:** a fresh reviewer acting in Andy's place (station law section 3). I took no part in the amendment.
**Spec:** `engram/docs/superpowers/specs/2026-10-25-store-imprint-design.md`, revision 7 (`git diff HEAD`, branch
`trail-arrows-spec`). Cited as "spec line N".
**Plan:** `engram/docs/superpowers/plans/2026-10-25-store-imprint.md`, the same diff. Cited as "plan line N".
**Verdict: reject in this form.** Two must-fix items remain, and both are about other people. The memory work is
sound. Every figure I redid holds, and every process stays under 384 MiB even after the items the spec leaves out (S5).
M1: the spec's account of the permissions spec is out of date. Rio Grande has since ruled on P36, and this spec now
contradicts that ruling, which says a co-subject's "no" holds. M2: the box the owner ticks at n = 0 promises a
protection that doesn't exist, and n = 0 is the case Andy will meet first. A revision that fixes M1 and M2 should
pass a re-check. The should-fix items can go in the same revision.

## What the amendment changed

- **The full store (A3).** In a copy kept in the owner's own home, memories with recorded co-subjects now ship. They
  carry those people in a new package-only table, `imprint_subjects`. The plan digest binds the rows, and the request
  and manifest count them (`others`). The station checks them (checks 10, 12, 13), registers them, and limits their
  uses to the owner's home (the ceiling's item 6). The owner's check becomes an acknowledgment
  (`others-copied-at-home-v1`). A copy that leaves the owner's home keeps revision 6's filter and confirmation.
- **Small hardware (A4).** The target is a 2 GB Pi. Each process stays under 512 MiB, with a 384 MiB design peak.
  Every unit gets `MemoryMax=512M` and `MemorySwapMax=0`. One imprint job runs at a time, under `flock`. Reads go
  through cursors in batches, and growing id sets live in a scratch SQLite file. The digest is hashed in pieces from a
  sort on disk. Calibration builds lane and core sets in blocks, with no n × n matrix (at most 16,000 episodes), and
  keeps per-semantic sets dense (at most 1,024). Section 14.1 and the plan's Task 50 add Pi peak tests.
- **Plan.** New rulings A3, A4 and R26 to R30, the new Task 50, gates G18 to G20, and changed Tasks 5 to 19, 23 to
  27, 32 to 35, 38, 40, 42a, 42b, 43a, 45, 47 and 48.

## How I checked

- I read the whole diff of both files. I also read the vision (`docs/city-rail-vision.md`, principle 4 and "Open for
  Andy") and the permissions spec's current text. So did its sibling review,
  `docs/superpowers/reviews/2026-10-25-small-hardware-permissions-review.md`, with Rio Grande's rulings at its end.
  I read the trail spec's revision 9 too, which was edited after this spec.
- I checked each code claim this revision adds against the code in this worktree.
- I redid each memory figure by hand. I measured the ones that could be measured on this Pi: the Python base sizes,
  object sizes, the sqlite-vec chunk, SQLite's compile options, and the `uv` wrapper.
- I ran four small experiments in the session scratchpad. None touched the repository:
  - the streamed digest against the definition;
  - Prim's tree against `build_filtration`;
  - where SQLite puts temporary files;
  - `flock`'s exit codes.
- MiB means 2²⁰ bytes, as in the spec (D42).

## Decision 1: "yes you can copy the full store"

**Carried exactly.**
- The quote is word for word at spec lines 105 and 242 (A3). A3 also says "Copying is not sharing", that the
  memories keep their recorded people as co-subjects, and that any use outside the owner's home still needs those
  people's yes (P12, P25). That is the vision's "Open for Andy" item, almost word for word.
- D27 (spec line 270) marks the line between inside and outside the home, and the rule for a copy that leaves the
  home, as Rio Grande's call.
- Section 13 shows Andy's full-store plan. It says plainly what still stays home: the 6.3 files and instincts (D8),
  cross-references (D23), unsettled lanes (D40), and the 100,000-memory cap (D36).
- Section 20 keeps open one narrower question for Andy: may an owner who isn't the operator send such memories?

**One fact Andy should know** (not a finding). If his machine has no permissions ledger, cosubjects(m) is ∅ (5.2). The
first full-store imprint then carries no co-subject at all, and G18 doesn't hold it. Until his machine records
co-subjects, his copy protects other people in one way only: step 1 has no use outside his home. The spec says this
(spec lines 2553-2555). M2 is about the box he ticks in exactly this case.

## Decision 2: small hardware

**Carried exactly.**
- The quote is word for word at spec lines 106 and 243 (A4).
- D42 (spec line 285) carries each of Rio Grande's five points:
  - a 2 GB Pi;
  - under 512 MiB per process, measured on the Pi;
  - streaming or bounded batches, with no whole table, dense matrix or graph that grows with the store;
  - the embedder never loaded in a process this work adds, which is stricter than "never loaded twice";
  - `MemoryMax=512M` on each added unit.
- All three added units carry the cap: admission's, the use's and the sweep's. The plan's units test checks this.
- D42, D31, D43, section 14.1 and the job lock are each marked as Rio Grande's call.
- The two remaining large sets are bounded by constants, not by the store: blocked lanes at 16,000 and dense
  per-semantic sets at 1,024. Per-memory tuples are bounded by the 100,000-memory cap.

**The figures, redone.**

| Figure | Arithmetic | Holds |
|---|---|---|
| Revision 6's dense bound | 7.5 × 7,500² × 8 = 7.5 × 56,250,000 × 8 = 3,375,000,000 B = 3.14 GiB | yes |
| Blocked lane set, per episode | 768 × 8 = 6,144 (vectors) + 256 × 8 = 2,048 (one block) + 512 (state) = 8,704 B | yes |
| Blocked lane set at 16,000 | 8,704 × 16,000 = 139,264,000 B = 132.8 MiB | yes |
| Per-point state | Edge tuple measured here at 159.3 B (spec: 161). Edges 159 + sorted copy 8 + three union-find lists about 80 + the id string 93.6 + float arrays about 60 ≈ 400 B, under the 512 allowed | yes |
| Dense set at 1,024 | 16 × 1,024² × 8 = 16 × 8,388,608 = 134,217,728 B = 128 MiB. Vectors 1,024 × 6,144 = 6,291,456 B = 6 MiB | yes; ratio to be measured |
| Held scores | 2 × 16,000 × 350 = 11,200,000 B = 10.7 MiB. Measured here at 375 B per entry (id 93.6 + dict 281.6): 12,000,000 B = 11.4 MiB | yes; 0.7 MiB low |
| One vector batch | 1,000 × (3,072 + 6,144) = 9,216,000 B = 8.8 MiB | yes |
| SQLite page cache | 5 × 2,000 KiB = 10,000 KiB = 9.8 MiB. `DEFAULT_CACHE_SIZE=-2000` in both SQLite 3.40.1 (system) and 3.53.1 (engram venv). Engram sets no `cache_size` or `mmap_size` (`storage.py:122-125`, `:158-159`; `store_reader.py:54`) | yes |
| vec0 chunk | 1,024 × 768 × 4 = 3,145,728 B. Measured: one insert into a vec0 `float[768]` table with sqlite-vec v0.1.7 gives a 3,145,728-byte `_vector_chunks00` blob and `size` 1,024 | yes |
| Plan, read | 96 + 9.8 + 16 = 121.8 MiB | yes; see S5 |
| Build | 121.8 + 2 + 8 + 6 + 3 + 1 = 141.8 MiB | yes; see S5 |
| Agent | 64 + 4 + 1 = 69 MiB | yes |
| Import-receipts | 96 + 3.9 + under 1 ≈ 101 MiB | yes |
| Admit, lane | 128 + 7.8 + 132.8 + 8.8 + 10.7 = 288.1 MiB | yes; see S5 |
| Admit, semantic | 128 + 7.8 + 128 + 6 + 10.7 = 280.5 MiB | yes |
| Admit, verify and count | 128 + 7.8 + 8 + 3 + under 1 ≈ 148 MiB | understated; see S5 |
| Admission's unit during verification | 128 + 96 = 224 MiB | yes |
| The use's unit | 64 + 320 = 384 MiB | yes; see S5 |
| Co-subject rows in a manifest | 7 × 100,000 = 700,000 rows × 80 B = 56,000,000 B = 53.4 MiB, far over 256 KiB | yes |
| Prim's reads | 6,144 × 16,000² = 1.572864 × 10¹² B | yes; see S2 |
| The whole Pi | 1.1 × 10⁹ + 536,870,912 = 1,636,870,912 B ≈ 1.64 GB. 2,048 − 256 = 1,792 | yes; see S6 |
| Bases | Measured here: system Python with numpy 1.24.2, 30,816 KiB (spec: 30,832). With `sqlite3` alone, 9,968 KiB; the spec's 13,712 is higher, so safe. The engram venv with numpy, `scipy.sparse.csgraph` and `sqlite_vec`, 65,088 KiB (63.6 MiB), under its 128 allowance. The peer importing `__main__` and `app`, 49,376 KiB (48.2 MiB), under 96 | yes |

The code each figure rests on is as the spec says:
- `persistence.py`: `:41-46` (`_mst_edges`), `:57-88` (`build_filtration`, with `D` and `off` at `:63-64` and the
  union-find at `:67-86`), `:110-125` (`split_band`), `:163-188` and `:172-174` (`generativity_scores`), `:215-253`,
  `:269-304` (with its query at `:274-277`), `:342-396` and `:399-416`;
- `calibrate.py`: `:82-122`, `fetchall` at `:90-93`, `:146-162`, `:165-180`, `:207-208` and `:211`;
- `sheaf.py`: `:61-87` and `:266-282`;
- `store_reader.py`: `:44-55` and `:58-63`;
- `storage.py`: `:122` and `:153-156`;
- `app.py:19`: `MAX_REQUEST = 6 * 1024 * 1024`;
- `peer/systemd/superyak-backup.service:14`: `MemoryMax=512M`;
- `scripts/superyak-embedder.service:13-14`: "Resting ~1.1 GB", `MemoryMax=3G`;
- `engram/CLAUDE.md:45`: "~1.8 GB loading its own model";
- the system tools: `/usr/bin/flock` is util-linux 2.38.1, and `findmnt /tmp` shows no mount of its own.

## Streaming and batching: no verdict, receipt or privacy rule changes

- **The digest.** The streamed form gives exactly the definition's bytes. I checked it with a script over all eleven
  tables, with keys that are prefixes of each other, non-ASCII text and JSON escapes. SHA-256 of the pieces equals
  SHA-256 of `canonical` of the whole object. SQLite's `ORDER BY` on a BLOB compares bytes as Python sorts `bytes`.
  The only proviso: the scratch table must keep duplicate keys (nit 6).
- **The leak checks.**
  - L1 looks up X* on disk. It is the same set as before.
  - L2 compares two `fts5vocab` cursors in one order.
  - L3 works one chunk at a time.
  - L4 is unchanged.
  - Check 15 by `count`, `min` and `max` is the same test, because rowids are unique.
  - Check 10 by anti-joins finds the same references. A malformed JSON list makes `json_each` raise, and admission
    then fails closed.
- **Calibration.**
  - The blocked filtration gives the same nearest-neighbour distances and the same tree edge set.
  - It gives the same deaths only if each edge is written (h, min, max). See S2.
  - A skipped set is recorded and never sampled.
  - Calibration feeds a report. It decides no use.
- **The job lock.**
  - A unit that loses the lock runs nothing and writes no receipt.
  - The admission stays resumable, and it is decided again when it resumes (D39).
  - Withdrawal, the sweep and the sync never wait for the lock.
  - No receipt changes.
- **The `others` counts.**
  - They reach the station before the yes. For another owner's copy they are always 0, and the confirm text is fixed,
    so nothing about what stayed home reaches the station.
  - The request, the manifest, the receipts and `station-pending` carry counts only. Names stay on the owner's machine
    (the dry run and `subjects.json`).

## Co-subjects of copied memories

**What protects them.**
- **Away copies.** In a copy that leaves the owner's home, base(m) keeps every memory with a recorded co-subject at
  home (5.2). `POST /api/imprints` refuses `others` above 0 (14). Check 12 refuses any `imprint_subjects` row.
- **Home copies.** Each shipped memory carries every effective co-subject (5.2):
  - The digest binds the rows, so a change between the plan and the build makes the build refuse.
  - Check 10 refuses the owner as a subject, and a row naming a memory the package lacks.
  - Check 13 compares the counts with the manifest.
  - Item 6 of the ceiling keeps their uses in the owner's home.
  - The rows are deleted with the imprint.
  - Imported memory receipts list each co-subject in `use_subjects`.
  - A step-2 ledger turns the rows into `subjects` rows (17).

**The gaps.** M1 (a co-subject's "no"), M2 (the box's words), S4 (receipts for roads and trails) and nit 4
(completeness rests on the source build).

## Plan against spec

- **Test counts.** I added up each task's expected count from its tests and parametrize cases. Each one matches,
  except Task 46 (S7).
  - Task 24 has 18 bad values: 15 before and 3 added, for 23 in all.
  - Task 33 has 15 tampered cases, for 32.
  - Task 5 has 7 tests and 4 skipped, for 12.
- **Coverage.** Every new spec test in section 16 has a task, except two noted in S7.
- **Review Focus.** Focus 6 and 7, and gates G18 to G20, match sections 17 and 18. They inherit M1, and G19 is stale
  (S8).

## Files

- Both files end with a newline.
- Every `## ` and `### Task` heading of HEAD is still present.
- The spec gains `### 14.1 Memory on a small Pi`.
- The plan retitles Task 5 and adds `### Task 50`. The plan's count goes from 60 to 61, the spec's stays at 21.

## Must-fix

**M1. The spec misstates the permissions spec, and its own reading drops a co-subject's "no".**

- **What this spec says.** "Carried co-subjects in the meet" (spec lines 1126-1146) says three things:
  - Line 1138: the permissions spec's revision 7 "offers, without applying, a narrower form", in which "every later
    use, the trail evaluation included, still needs every subject's yes".
  - Lines 1140-1142: under that form, admission's third set and every trail evaluation of a copy with a carried
    co-subject "would be refused whole".
  - Lines 1131-1133: inside the owner's home, a use "is decided on the owner's layer and the ceiling alone, and a
    carried co-subject's layer is not in it". Line 1259 adds that "their layers are in no step-1 decision".
- **What the permissions spec says now.**
  - It applies the rule as P36 (its lines 621-633). Its section 19 says "Resolved by Rio Grande on Andy's answer: P36"
    (its line 2135).
  - Rio Grande's rulings on its check (permissions review lines 262-280) set P36's reach. It covers the owner's
    `imprint` into his own home, and every bulk use there that shows no content to any agent, named or counted. That
    includes admission's checks and calibration, and the trail evaluation's `read` batches.
  - The same rulings say a co-subject's layer is read as a restriction layer: "a person who has said no keeps their
    no, even inside Andy's home".
- **Why it matters.**
  - This spec's own header says the permissions spec wins where they differ (spec line 72).
  - The person who settles G18 is told something about the other spec that is no longer true.
  - Leaving the co-subject's layer out drops their deny as well as their silence. In step 1 the station holds no
    co-subject layer, so nothing changes there. But 5.2 reads only the source ledger's `subjects` rows. A memory whose
    co-subject has a deny on the owner's ledger would still ship, and it would be used in admission and the trail
    evaluation.
  - The general reading, "inside the home the co-subject's layer is not in the decision", is also wider than P36. P36
    still needs every subject's yes for any use that shows content to an agent, even inside the home.
- **Fix.**
  - Describe P36 as Rio Grande ruled it, and drop "offers, without applying" and the "refused whole" forecast.
  - Take the deny ruling. At the source, a memory stays home if a co-subject's layer on the owner's ledger refuses a
    use in Need(admission) or Need(trail-evaluation). Count it as "<name> said no". At the station, read a carried
    co-subject's layer as a restriction layer; in step 1 it is empty.
  - Narrow "This spec follows the reading…" (spec lines 1142-1143) to P36's reach: uses inside the owner's home that
    show nothing to any agent. Every step-1 use is one of these, so step 1 loses nothing.
  - Make the same changes to the status line, D27, the bulk-use bound note (spec line 1259), 17's ask (a), 18's gate
    "Other people inside the home" and section 20.
  - In the plan, make them in A3 (plan line 123), G18 (plan line 4669) and the carried items.
  - Add a Task 8 test: a co-subject's deny on the source ledger keeps the memory home.
  - Keep G18 until both specs, revised, are re-checked side by side. The line between inside and outside the home
    stays Rio Grande's call, as D27 says.

**M2. At n = 0 the owner's box promises a protection that doesn't exist.**

- **What the box says.** Section 8 (spec lines 972-977) gives the box for a copy kept in the owner's home: "I know
  these memories may be about other people… <n> of them have other people recorded on them (<p> people). They are
  copied with those people as co-subjects, and no use of them outside my home can happen without their yes." At
  n = 0 only the second sentence changes, to "Engram has no record of the people they mention." The third sentence
  stays. So Andy would tick: "…Engram has no record of the people they mention. They are copied with those people as
  co-subjects, and no use of them outside my home can happen without their yes."
- **Why it is false.** At n = 0 nothing is recorded, so these memories carry no co-subject. A later use outside the
  home would then go on the owner's yes alone. That is the permissions spec's default (its section 19), and this
  spec's D27 says so too ("a memory that mentions someone with nothing recorded leaves on the owner's yes"). The dry
  run's words for no ledger are right (spec lines 598-600). The box is not.
- **Why it matters now.** It is the case Andy meets first: with no ledger on his machine, n = 0 (5.2). The plan
  carries the same words (Task 25, `CHECK_TEXT_AT_HOME`, "or, at n = 0, …"). Its browser test covers only n = 37.
- **The n > 0 box too.** It says nothing about memories that mention people with no record. The confirm view does
  (section 9).
- **Fix.**
  - At n = 0: "…Engram has no record of the people they mention, so no one but me is recorded on them. They are copied
    on my yes alone."
  - At n > 0, add: "Other memories may mention people Engram has no record of. They are copied on my yes alone, with
    no one else recorded on them."
  - Test both texts in Task 25. Give a ledger with no co-subjects the same words as no ledger. Today the dry run would
    print "0 memories … (0 people: )".

## Should-fix

**S1. Setting `SQLITE_TMPDIR` from inside the process does nothing, and the test for it can't fail.**

- **The claim.** Spec line 642 (6.1, step 7) says `imprint.py` "sets `SQLITE_TMPDIR` to its own 0700 scratch
  directory on disk before it opens any [connection]". Spec line 1491 says the same for admission. Plan R26 and
  Tasks 19 and 34 do the same.
- **What happens.** I measured it with `strace` on this Pi.
  - Python's `sqlite3` module initializes SQLite when it is imported, and SQLite reads `SQLITE_TMPDIR` and `TMPDIR`
    only then.
  - Set after `import sqlite3`, the variable is ignored. `VACUUM`'s temporary file went to `/var/tmp`. This held in
    both SQLite 3.40.1 and the engram venv's 3.53.1.
  - Set before the import, or in the environment at start, it is used.
- **The test.** Task 50's `test_scratch_stays_on_disk_where_it_belongs` (plan line 4540) runs `build` and `admit` in
  the pytest process, which imported `sqlite3` long before. It passes whatever `imprint.py` does.
- **Impact.** Small on this Pi. SQLite falls back to `/var/tmp`, on disk, before `/tmp`. So no memory figure fails,
  and SQLite unlinks its temporary files at once. But the stated mechanism is wrong. Temporary files from admission
  don't land in `<imprint id>.state/scratch/`, and a caller's `TMPDIR` pointing at a tmpfs would be used.
- **Fix.**
  - Set both variables in the environment before Python starts: in the Makefile recipes, and through `systemd-run
    --setenv` for admission's unit, with the directory made first. Or have `imprint.py` re-exec itself.
  - Run the test as a subprocess.
  - Python's `tempfile` caches `TMPDIR` too.

**S2. Prim's edges must be written (h, min(u, v), max(u, v)), or the deaths differ.**

- **What R28 says.** R28 (plan line 152) and D31 / section 10 (spec line 1562) say: build the tree by Prim's, then
  sort the edges by (height, i, j) for today's union-find.
- **What scipy does.** Today's `_mst_edges` (`persistence.py:41-46`) gets every edge with i < j from scipy: 39 of 39
  at n = 40, and 299 of 299 at n = 300, on random 768-dimension vectors.
- **Why it matters.** The union-find makes j's lineage die when the two sizes are equal (`persistence.py:82-84`). So
  the orientation decides the deaths. I compared a Prim's tree with `build_filtration` at n = 40 and n = 300:
  - Written as (min, max), the deaths are equal.
  - Written as (parent, child) or (max, min), they are not.
  - The nearest-neighbour distances and the edge set are equal every time.
- **Fix.** Say "(h, min(u, v), max(u, v))" in R28. Note that `nn` must clip at 0 as `distance_matrix` does
  (`persistence.py:38`). D31's "the same outputs" holds only then, and only without exact duplicates. Task 5's test
  already says so for duplicates.

**S3. Admission's time doesn't fit at the bounds, and no test runs it there.**

- **The claim.** Spec lines 1581-1583: each 16,000-episode lane must finish in 600 s, "so two lanes and the core set
  fit the unit's 1,800 s".
- **The sum.** 3 × 600 = 1,800 s. That is all of `RuntimeMaxSec`. Nothing is left for the rest of admission:
  - verification (17 checks over up to 100,000 memories, with L2's FTS rebuild and the digest recomputed);
  - the snapshot and the migrated working copy;
  - cohesion over up to 10,000 semantics;
  - hubs with ripser;
  - the conjunct audit;
  - the count of R(I).
- **The consequence.** A killed admission fails closed (R24), so this is safe. But Andy's full store could fail every
  time at the bounds.
- **No test reaches it.** The cap fixture puts 45,000 episodes in each lane and 1,025 sources in the hub (spec line
  2461; plan lines 4512-4514). So every calibration set is skipped, and no test runs a whole admission with its sets
  at the bounds, for memory or for time.
- **Fix.**
  - Give a time budget per step that sums under 1,800 s. Or lower the per-lane limit, or raise `RuntimeMaxSec` (with
    `ADMISSION_BOUND`, R24).
  - Add a Pi test of one admission with two 16,000-episode lanes and a 1,024-source hub, timed and peak-measured.

**S4. Imported receipts for roads and trails don't list the carried co-subjects.**

- Spec lines 2012-2016 give each road-and-trail row one `use_subjects` row, (owner, the copy's ref).
- A road or trail has the union of its memories' subjects (P24, quoted at spec section 8). And owners see every use
  of their memories (P17).
- The station names no roads, so the owner's machine can't tell which roads touch which memories.
- **Fix.** Add one (s, copy ref) row for each co-subject in `subjects.json` to each such row. That lists a little
  too many people, which is the safe side. Rio Grande's call. Add a test in Task 45.

**S5. Section 14.1 leaves some memory out. All of it still fits, but the arithmetic should show it.**

- **`generativity_scores`.** It returns a dict with one entry per episode that has a resonance. It is not bounded by
  the lane bound. Measured here: 14.1 MiB at 100,000 entries. Admit, lane: 288.1 + 14.1 = 302.2 MiB.
- **The second block.** `1 − X_block · Xᵀ` makes a second 256 × n block unless it is done in place: 256 × 16,000 × 8
  = 32,768,000 B = 31.25 MiB, giving 302.2 + 31.25 = 333.5 MiB. Also, the 132.8 MiB holds only if X is preallocated,
  filled batch by batch, and normalized in place. Today's code stacks a list of per-row arrays
  (`persistence.py:137`), then divides into a new array (`:35`). Each extra copy is 6,144 × 16,000 = 98,304,000 B =
  93.75 MiB. One copy gives 288.1 + 93.75 = 381.9; two exceed 384. Say this in R28.
- **`Shipped`.** R26 measures it at 18.2 MiB, but it is missing from the plan and build rows. They become 121.8 +
  18.2 = 140.0 and 141.8 + 18.2 = 160.0 MiB.
- **The count of R(I).** The trail spec's revision 9 puts it at 47.0 MiB on top of `imprint.py admit` (its line 1609:
  one session 32.8, lookups 4.2, a batch 8, the connection 2.0). This spec says "under 1" (spec line 2189). The row
  becomes about 148 − 1 + 47.0 = 194 MiB.
- **The wrappers in each unit.** `uv run` held 19,920 KiB (19.5 MiB) here, and `make` and `flock` run beside it. The
  use's unit is then 64 + 320 + 19.5 + a few for `make` and `flock` ≈ 405 MiB. That is under 512 but over the 384
  given to the unit.
- **Conclusion.** The worst process is 333.5 MiB, under 384, and every unit is under 512. Add these lines so the
  table is the whole sum.

**S6. The whole-Pi gate uses 2,048 MiB, more than a 2 GB Pi can use.**

- Section 18 (spec lines 2553-2558) and G20 (plan line 4671) require "under 1,792 MiB (2,048 − 256)".
- The kernel and firmware hold some RAM back. This Pi shows `MemTotal` 16,608,224 kB against 16 GiB = 16,777,216 kB.
  That is 168,992 kB (165 MiB) it can't use.
- **Fix.** Use the 2 GB Pi's `MemTotal` minus 256 MiB, measured or stated, not 2,048 − 256.
- Also say that this Pi runs 16 KiB pages (`getconf PAGESIZE` is 16384). Resident sizes measured here are larger than
  on a 4 KiB-page Pi, so the Pi tests err on the safe side.

**S7. Plan tests that don't match the spec.**

- Spec 16 says: "`imprint.py use`, with a stub child that sleeps, peaks under 64 MiB" (spec line 2471). No task
  measures it. Task 38's test only checks that importing `imprint` loads no numpy (plan line 3532). Add that
  measurement to Task 50.
- Task 50's peer test measures four station commands (plan line 4556). Section 14.1 names nine, plus
  `verify-imprint`. Add the rest, or say why four cover them.
- Task 46 shares Task 40's test file. It still says "17 passed (Task 40's 11 and these 6)" (plan line 4334). Task 40
  now has 12, so this should read 18.

**S8. Stale references to the trail spec, and a stale signature.**

- The trail spec is now revision 9. It took this spec's asks (a) to (d):
  - its R19 (its line 108): no model in process;
  - its R20 (its line 129): a 320 MiB design peak and `MemoryMax=512M`;
  - its R21 and line 1501: one session at a time.
- This spec still says revision 8 at spec lines 75, 1866-1867 and 2533. It still says the text goes to the embedder
  "in the run's process" at spec line 1236.
- The plan still depends on `create_embedding_provider(local_files_only=True)` (plan line 270).
- R10 (plan line 134) lacks the `scratch` parameter that Task 35 adds.
- Who aggregates the steps on disk differs. The trail spec says its count does ("steps counted with SQL on disk", its
  line 1501). Task 35 does it itself with T's per-session `derive`. Settle which side.
- Point G19 at revision 9 and its review.

## Nits

1. Spec line 1576 says "twice the filtration's measured 7.5". 2 × 7.5 = 15. Say "a little over twice".
2. `flock -n` exits 1 when the lock is held, and 66 when the lock file can't be opened (measured: util-linux 2.38.1,
   with the imprints root missing). R29 prints "another imprint job is running" on any failure. Test for 1.
3. A unit can lose the lock after the Makefile's check passed. By then the Makefile has printed "Approved …
   Admitting in the background" or "Started a use". Say so in `station-imprints`, or in the sentence.
4. D43 says "The station verifies them (checks 10, 12 and 13)". It verifies their form and counts. Whether every
   co-subject was carried rests on the source build, as spec line 1542 says of the other content rules. Say so.
5. Task 8's `"person:andy" not in str(list(...))` is true of any empty list. Test the owner's exclusion on a memory
   that also has a co-subject.
6. The digest's scratch table must keep duplicate keys: no unique constraint. Or say why no two shipped rows share a
   key (each key includes a primary key).

## What holds

- **The decisions.** Both are carried word for word, and every choice that isn't Andy's is marked Rio Grande's call.
- **Memory.** Every memory figure in the diff is right as written. Every process is under 384 MiB, even with S5's
  additions (worst 333.5 MiB), and every unit is under 512 MiB.
- **Units and jobs.** All three added units carry `MemoryMax=512M` and `MemorySwapMax=0`. One imprint job runs at a
  time.
- **Streaming.** The digest, the leak checks and the checks give the same results streamed. The streamed digest is
  byte for byte the definition.
- **Away copies.** A copy that leaves the owner's home keeps revision 6's rules, enforced at the request, at check 12
  and in the fixed confirm text.
- **Home copies.** A copy kept in the owner's home carries every effective co-subject, binds them in the digest,
  counts them without names, and keeps their uses in the home.
- **Receipts.** No receipt changes, and none names a memory.
- **The plan.** It matches the spec task by task, apart from S7.
- **The files.** Both are complete.

## Response

Date: 2026-10-26. By the spec's reviser, in the same worktree. I edited only the spec, the plan and this file, with
targeted edits. No code, commit, push, merge, deploy or post. The spec stays revision 7: its header and history row
now list these fixes. M1, M2, S1 to S3 and S5 to S8 are applied, and all six nits. S4 is not applied; it goes to gate
G18 (below says why). Choices that are not Andy's are marked Rio Grande's call in the files.

The permissions spec has moved since this check. P36 is now its table row at its line 237, its rule at lines
659-698 ("The owner's own copies"), and its section 19 at lines 2338-2361. Rio Grande's rulings are where the check
said (permissions review lines 262-280).

### Must-fix

- **M1. Applied.** The spec now follows P36 as ruled.
  - Section 8, "Carried co-subjects in the meet", is rewritten. It states P36: a qualifying use is the owner's
    `imprint` into his home, or a bulk use there that shows nothing to any agent. For such a use, a co-subject's
    layer is a restriction layer, so silence passes and a deny refuses. Every other use needs their yes. The section
    then gives four cases: outside the home, inside with nothing shown, a co-subject's no, inside with content shown.
    "Offers, without applying" and the "refused whole" forecast are gone. The "inside the home" reading is limited to
    uses that show nothing to an agent.
  - A co-subject's no now keeps a memory home. New `denied(m)` in 5.2, added to base(m). It holds when a co-subject's
    layer on the source ledger has an unrevoked deny, not ended at the plan, that matches a use of Need(admission) or
    Need(trail-evaluation) on m, read by the permissions spec's 5.3 as a deny. It is counted as "<name> said no". A
    deny added between plan and build changes the digest, so the build refuses. Rio Grande's call on the check's
    form.
  - At the station a carried co-subject's layer is read as a restriction layer (D43, section 8). In step 1 the
    station holds none, so it is 𝒰 and removes nothing. Every step-1 verdict is unchanged.
  - Also changed: the header, D27 (and its source column), D43, the non-goal, the anti-goal "Lost co-subjects", the
    vision constraint, 6.2's `imprint_subjects` row, 6.4 item 5, "Why the station's check is the permissions spec's
    meet", the bulk-use bound note, section 13, 16 (a new "A co-subject's no" test), 17 (step 1, step 8 and ask (a),
    now answered), 18's gate and 20.
  - Plan: A3, the carried items, "What this plan uses" (the ledger's `records` table at `permission_ledger.py:68-72`,
    `Ledger.state()` at `:229`, `permissions.Use` at `permissions.py:797-808` and `record_matches` at `:1026-1036`,
    all read on branch `permissions-core`), G18 and the self-review.
  - New tests. Task 8: `test_a_co_subjects_no_keeps_the_memory_home`. It also shows that a revoked deny, an ended
    one, and one naming only another place keep nothing home, and that no State is built without a deny. Task 19:
    `test_a_co_subjects_no_between_plan_and_build_refuses_the_build`. Task 15's dry-run test checks "said no".
  - Memory. The plan builds the ledger's State only when such a deny exists. The State costs at most 45.0 + 64.5 +
    25.3 + 6.1 = 140.9 MiB (the permissions spec's 15, at its bounds). The plan's row becomes 140.0 + 140.9 = 280.9
    MiB, and the build's 160.0 + 140.9 = 300.9 MiB. Both are under 384.
  - G18 is kept. It now waits for both specs, revised, to be re-checked side by side.
- **Found while applying M1, for that re-check** (not fixed; Rio Grande's call to route them there):
  - **The bound of 8 subjects on roads and trails.** Reading a layer as a restriction layer doesn't remove it from
    the subject count. A road or trail has the owner plus every co-subject its memories carry (P24). If a trail's
    memories carry 8 or more distinct co-subjects, it has 9 or more subjects. The permissions spec then refuses the
    whole bulk use with `BOUND` (its 6.4, "Nothing else is waived", and 6.5 step 1). So admission's count and the
    trail evaluation would be refused. This spec's check doesn't test that bound. Section 8 now says so. No step-1
    verdict differs while G18 holds, since with no carried co-subject every road has one subject.
  - **A deny can exist in step 1.** The permissions spec's section 19 says a co-subject's deny "can exist only from
    step 2". But its 7.6 lets the CLI write "the layers of places the owner stewards". So a place co-subject that the
    owner stewards can hold a deny in step 1. This spec's `denied(m)` covers it. The permissions spec's sentence is
    for its own revision.
- **M2. Applied.** Section 8 now gives two home texts.
  - n above 0 adds: "Other memories may mention people Engram has no record of. They are copied on my yes alone,
    with no one else recorded on them." Its promise now also covers uses that show the memories to an agent.
  - n = 0 reads: "I know these memories may be about other people, such as family, colleagues, patients or study
    participants. Engram has no record of the people they mention, so no one but me is recorded on them. They are
    copied on my yes alone."
  - The confirm view (section 9) and the dry run (5.4) get the same split. A ledger that records no co-subject on
    what leaves gets the no-ledger words. The dry run never prints "0 memories" or "(0 people: )". The station
    chooses by `others.memories` alone, so it can't tell the two n = 0 cases apart, and doesn't need to.
  - Plan: Task 25 gets `CHECK_TEXT_AT_HOME_NONE`, `OTHERS_AT_HOME_NONE_WORDS` and
    `test_both_home_texts_say_only_what_is_true`, which tests both texts and the n = 0 attestation. Task 15's test
    checks the n = 0 words with no ledger and with an empty one. Section 16's "Confirm" and "Co-subjects carried" say
    the same.

### Should-fix

- **S1. Applied** (6.1 step 7, section 10, 14, 15, 16; plan R26, Tasks 15, 34, 50).
  - I confirmed it with `strace` on this Pi, SQLite 3.40.1, in my scratchpad. Set after `import sqlite3`, the
    variable is ignored: `VACUUM`'s file went to `/var/tmp`. Set before the import, it went to the named directory.
  - The fix is a re-exec. `imprint.main` makes the scratch directory, then re-executes itself once unless
    `SQLITE_TMPDIR`, `TMPDIR` and `IMPRINT_SCRATCH` all name it. Rio Grande's call over Makefile recipes and
    `systemd-run --setenv`: a re-exec works the same from `make`, a unit or a shell, and the plan's scratch
    directory is made per run, which a recipe can't know.
  - The test. SQLite unlinks a temporary file right after it opens it (`strace`: `openat`, then `unlinkat`). So a
    directory listing can never fail. Task 50's test now runs `build` and `admit` as child processes under
    `strace -f`. It asserts every `etilqs_` file lies in the scratch directory. It skips where `strace` is missing;
    the Pi has it. Task 15 adds a unit test of `ensure_scratch_env` with a stub `execve`.
- **S2. Applied** (D31, section 10, 16; plan R28, Task 5). Each edge is written (h, min(u, v), max(u, v)) and sorted by
  that triple. Distances are clipped at 0 as `distance_matrix` clips (`persistence.py:38`). I read the code: the
  union-find lets j's lineage die on equal sizes (`persistence.py:82-84`), and `_mst_edges` sorts scipy's
  (h, row, col) (`:41-46`). Task 5 asserts i < j on every edge. D31's "the same outputs" now says "with no exact
  duplicates".
- **S3. Applied, by raising the limit** (Rio Grande's call). Admission's unit gets `RuntimeMaxSec=3600`, with a budget:
  three blocked sets at 600 s each, 1,800 s; the rest at most 1,500 s; 300 s spare. 1,800 + 1,500 + 300 = 3,600.
  `ADMISSION_BOUND` becomes 3,600 + 60 = 3,660 (R24, constants, Review Focus 1, Tasks 36 and 40, G15). A new Pi
  test times one whole admission at its bounds: two lanes and a core set of 16,000 each, a 1,024-source hub, at most
  3,300 s and under 384 MiB. I chose this over a lower lane bound because time costs no memory, and a lower bound
  would leave more of Andy's store uncalibrated. The use's unit keeps 1,800 s.
- **S4. Not applied. It goes to G18's re-check** (spec section 12, 17 ask (a), 18; plan G18). Three reasons:
  - The permissions spec's 9.1, item 3 fixes the counted row's one `use_subjects` row, (owner, h). Where the two specs
    differ, that one wins.
  - Listing every carried co-subject on each counted row has no bound that fits that spec's fold. At the cap,
    700,000 × 671 B = 469,700,000 B = 447.9 MiB, against the fold's 38.2 MiB at its bounds (its 15). A memory row
    lists at most 512 × 8 = 4,096 pairs, its largest named bulk receipt.
  - In step 1 no co-subject reads the owner's use list (its 7.6). The memory rows already list each co-subject, so
    `uses --object <ref>` finds the use.
- **S5. Applied** (14.1, section 10). The table is now the whole sum:
  - plan 96 + 9.8 + 16 + the shipped ids 18.2 = 140.0; build 140.0 + 20 = 160.0;
  - lane set 288.1 + the generativity dict 14.1 = 302.2, + a second 256 × 16,000 × 8 = 32,768,000 B = 31.25 →
    333.5; semantic 280.5 + 14.1 = 294.6; verifying and counting 128 + 7.8 + 8 + 3 = 146.8, + the trail spec's 47.0
    = 193.8;
  - X is allocated once and normalized in place (R28). One copy, 6,144 × 16,000 = 98,304,000 B = 93.75 MiB, would
    give 333.5 + 93.75 = 427.2, over 384.
  - Each unit: `uv run` 19,920 KiB (the check's figure), `make` 2,320 kB and `flock` 1,568 kB (`VmHWM`, measured on
    this Pi). 19,920 + 2,320 + 1,568 = 23,808 KiB = 23.25 MiB. The use's unit holds 64 + 320 + 23.25 = 407.25 MiB,
    and admission's at most 333.5 + 23.25 = 356.75 MiB. Both are under 512.
  - The worst process is 333.5 MiB, under 384.
- **S6. Applied** (14.1, 18; plan G20). I read `MemTotal` 16,608,224 kB here. 16,777,216 − 16,608,224 = 168,992 kB =
  165 MiB held back. Until a 2 GB Pi is measured, the gate takes 2,048 − 165 = 1,883 MiB, so the sum must be under
  1,883 − 256 = 1,627 MiB. The embedder beside one job is 1.1 × 10⁹ B = 1,049 MiB + 512 = 1,561 MiB, which leaves 66
  MiB for the system and the lighthouse. 14.1 now says that is unlikely to be enough. `getconf PAGESIZE` is 16384,
  and 14.1 and the verification say the Pi tests err high.
- **S7. Applied** (Task 50, Task 46, spec 16). Task 50 adds `test_pi_the_use_parent_with_a_sleeping_child` (under 64
  MiB). Its peer test now measures all ten peer commands of 14.1, `verify-imprint` included. Task 46 reads "18
  passed (Task 40's 12 and these 6)"; I counted Task 40's tests: 4 + 2 parametrized cases and 6 tests.
- **S8. Applied.**
  - The trail spec is revision 9 in the header (the check's line 75), in section 12 and in section 17. The check's
    line 1236, "in the run's process", is gone.
  - Plan line 270 now says T's revision 9 withdrew `local_files_only=True` (its R19).
  - Aggregation is settled toward the trail spec (Rio Grande's call). Its `roads_and_trails` derives one session at
    a time and counts with SQL under `TMPDIR` (its R21, I7 (c)). The trails plan already builds it as this plan's
    `derive` seam (its TR20, Task 4). So R10 keeps `count_roads_and_trails(conn, *, lanes, as_of, derive=None)`.
    Task 35 drops its `scratch` parameter and its own aggregation, so the support rule has one implementation.
    `test_the_count_aggregates_steps_on_disk` is replaced by `test_the_count_is_the_sum_of_the_trail_specs_lane_counts`.
  - Section 17's asks of the trail spec are marked answered on paper by its I7, with a note that its own check asked
    for a revision. Both of its asks back are taken: the 47.0 MiB row, and `TMPDIR` for the use's child, which
    section 12 already gave. G19 now points at revision 9 and its review.

### Nits

1. Applied: "a little over twice the filtration's measured 7.5 (2 × 7.5 = 15)".
2. Applied (R29, Task 40). I measured it: util-linux 2.38.1's `flock -n` exits 1 on a held lock and 66 on a missing
   directory. Only 1 means "another job is running"; any other status prints that the lock can't be taken.
3. Applied (section 10, R29). `station-imprints` shows "waiting: not begun; run make station-imprint-admit".
4. Applied (D43). The station verifies the rows' form and counts. Completeness rests on the source build.
5. Applied (Task 8). m4 carries the owner and lee, and only lee's row is carried.
6. Applied (Task 12). The scratch table has no `PRIMARY KEY` or `UNIQUE`. I checked the link tables' keys:
   `semantic_sources` and `semantic_peers` have composite primary keys (`002_v3_layers.sql:25-29`,
   `020_sheaf_cohesion.sql:17-23`), so no key repeats today.

### Counts and files

- Test counts changed: Task 8, 10 → 11; Task 15, 7 → 8; Task 16, 9 → 10; Task 19, 14 → 15; Task 25, 9 → 10; Task 46,
  17 → 18; Task 50's engram file, "2 passed, 6 skipped" → "2 passed, 8 skipped".
- Every `## ` and `### Task` heading is still present: the plan has 61, the spec 21 `## ` and 11 `### `, as before
  these edits. Both files end with a newline.
- Ready for a re-check of M1 and M2. G18 then needs the side-by-side re-check of both specs.

## Re-check (2026-10-26)

**Reviewer:** a fresh reviewer acting in Andy's place (station law section 3). I took no part in writing, checking or
fixing this amendment. I edited only this file, by appending this section.

**What I read:**
- `git diff e084597` of the spec and the plan, both changed in `c795c59`, and the "Response" above;
- the vision (principle 4 and "Open for Andy");
- the permissions spec as it stands: P36 at its lines 237 and 659-698, 7.4 at 1034-1091, 7.6 at 1100-1104, section 19
  at 2325-2371;
- Rio Grande's rulings (permissions review lines 262-278);
- the trail spec's revision 9 as revised after its check;
- the code in this worktree and on branch `permissions-core` at `dc0881e`.

Spec and plan lines below are the files at `c795c59`.

**Verdict: reject in this form, one must-fix.**
- **Fixed:** M1 and M2. So is every other item of the check, except S4, which goes to gate G18 for reasons that hold.
- **Holds:** every memory figure. The three specs state P36 the same way.
- **Must-fix (RM1):** the source reads a memory's co-subjects from that memory's own rows only. The permissions spec
  also counts the people recorded on the memory it was copied from.

A revision that fixes RM1 should pass. The should-fix items can go in the same revision.

### The check's must-fix items

- **M1: resolved.**
  - Section 8, "Carried co-subjects in the meet" (spec lines 1185-1225), states P36 as Rio Grande ruled it:
    - who qualifies (line 1190);
    - silence and a missing layer pass, and a deny refuses;
    - every other use needs every co-subject's yes.

    "Offers, without applying" and "refused whole" survive only as history (lines 1217-1219).
  - A co-subject's no keeps a memory home: `denied(m)` in 5.2 (lines 385-406), a term of base(m) (line 347). I read its
    matcher on `permissions-core`. `record_matches` (`engram/permissions.py:1026-1036`) checks revocation and
    `valid_from ≤ t < valid_until` (`:990-991`) before the selector. So a revoked deny, an ended one, and one whose
    audience is another place refuse nothing, as Task 8's test expects.
  - The plan doesn't know the imprint id. That doesn't matter: a selector has no copy dimension (permissions spec 5.2).
  - The cited code is where the plan says: the `records` table at `permission_ledger.py:68-72`, `state()` at `:229`,
    `Use` at `permissions.py:797-808`.
  - Every place the check named was changed:
    - in the spec: the header, D27 with its source column, D43, the non-goal, the anti-goal, the vision constraint,
      6.4 item 5, the bulk-use note, 13, 16, 17, 18 and 20;
    - in the plan: A3, the carried items, G18 and the self-review.
  - The asked tests are there. Task 8 has `test_a_co_subjects_no_keeps_the_memory_home`. Task 19 has a deny written
    between the plan and the build. G18 is kept.
- **M2: resolved.**
  - Section 8 (lines 1025-1036) gives the n = 0 box in the check's words, and adds the asked sentence at n above 0.
    Section 9 and 5.4 split their texts the same way.
  - Task 25's `test_both_home_texts_say_only_what_is_true` tests both texts and the n = 0 attestation. The words it
    forbids at n = 0, "co-subjects" and "their yes", occur in section 9 only in the n above 0 text. I grepped the
    whole section.
  - Task 15 tests the n = 0 words with no ledger and with an empty one.

### The rest of the check

**Applied.** S1 to S3, S5 to S8 and nits 1 to 6 are in the diff, as the "Response" says. Where a fix cites code, I
read the code:
- `persistence.py`: the union-find at `:82-84`, `_mst_edges` at `:41-46`, the clip at `:38`, the stack at `:137`;
- the composite keys at `002_v3_layers.sql:25-29` and `020_sheaf_cohesion.sql:17-23`;
- `peer/systemd/superyak-backup.service:14` and `scripts/superyak-embedder.service:13-14`.

On this Pi:
- `findmnt -T /tmp` shows `/` on ext4;
- `getconf PAGESIZE` is 16384;
- `MemTotal` is 16,608,224 kB;
- `strace` and `flock` are in `/usr/bin`.

**S4 waits for G18.** Two of the reviser's three reasons hold. One fact matters for the re-check:
- The permissions spec's general rule for a counted bulk use is already "one `use_subjects` row per distinct subject of
  its objects, with the copy ref h in the `object` column" (its 9.1, the "counted" bullet).
- So the safe form lists each distinct carried person once per counted row. That is `others.people` rows per counted
  row.
- It reaches the reviser's 700,000 only if every co-subject at the cap is a different person. A cap on distinct
  carried people would bound it (Rio Grande's call).
- Item 3's "(owner, h)" was written when the owner was the only subject.

### Do the three specs agree?

| Point | Permissions spec | Imprints spec | Trail spec | Agree |
|---|---|---|---|---|
| Who P36 covers | The requester acts for the owner, and P and H are in his home. The use is his `imprint` into a copy kept there, or a bulk use that shows nothing to any agent, with the uses its `need` adds (its lines 662-675). | The same (spec line 1190). Every step-1 use qualifies, since the operator is then the owner (D9). | "the owner's `imprint`, and every bulk use inside his home that shows nothing to any agent" (its lines 1057-1060). | yes |
| A co-subject's deny | Refuses with `DENIED` (its line 675; ruling M3). | Refuses. The source keeps the memory home (`denied(m)`; D27; line 1207). | "a co-subject's no holds inside the home too" (its line 1060). | yes |
| Content shown to an agent, or a use outside the home | Never covered (its lines 687-691). | Never covered (lines 1199, 1213; 17, step 1). | The run shows nothing and lets only counts leave (R24, its line 146). | yes |
| Memory | Under 512 MB per process, MB = 2²⁰ bytes, every unit `MemoryMax` ≤ 512 MB (P37, its lines 238, 1926). | Under 512 MiB per process, a 384 design peak, `MemoryMax=512M` and `MemorySwapMax=0` (D42). | The same 384 peak, 320 for the evaluation, no unit of its own (R20, its line 142). | yes. The count of R(I): 47.0 MiB, 193.8 in all, on both sides (trail I7, its lines 1896-1900; spec 14.1). |
| What an imprint carries | "An imprint's carried subjects are its `imprint_subjects` rows" (7.4, its line 1082). | `imprint_subjects` (D43, 6.2), the `others` counts, and `subjects.json` at home. | Reads no `imprint_subjects` row; its test denies the table through an authorizer (R24; its 12). | yes |

**The rules agree. Two accounts don't.**
- The permissions spec's own account of the imprints spec is out of date (S2).
- All three specs miss a co-subject recorded through a copy (RM1).

### Memory, redone

MiB is 2²⁰ bytes.

| Figure | Arithmetic | Holds |
|---|---|---|
| Plan | 96 + 9.8 + 16 + 18.2 = 140.0 | yes |
| The ledger's State | 45.0 + 64.5 + 25.3 + 6.1 = 140.9. That is the permissions spec's `state()` at its bounds less its base: 30.3 + 45.0 + 64.5 = 139.8, + 25.3 + 6.1 = 171.2, and 171.2 − 30.3 = 140.9 (its line 1994). | yes |
| Plan with the State | 140.0 + 140.9 = 280.9 | yes |
| Build | 140.0 + 2 + 8 + 6 + 3 + 1 = 160.0; with the State, 160.0 + 140.9 = 300.9 | yes |
| Blocked lane set | 8,704 × 16,000 = 139,264,000 B = 132.8 MiB. X: 6,144 × 16,000 = 98,304,000 B = 93.75 MiB. One block: 256 × 16,000 × 8 = 32,768,000 B = 31.25 MiB. | yes |
| Admit, lane | 128 + 7.8 + 132.8 + 8.8 + 10.7 = 288.1; + 14.1 = 302.2; + 31.25 = 333.45, shown as 333.5. One more copy of X: 333.45 + 93.75 = 427.2. | yes |
| Admit, semantic | 16 × 1,024² × 8 = 134,217,728 B = 128 MiB. 128 + 7.8 + 128 + 6 + 10.7 = 280.5; + 14.1 = 294.6. Also 2 × 7.5 = 15, "a little over twice". | yes |
| Admit, verify and count | 128 + 7.8 + 8 + 3 = 146.8. The trail spec's 32.8 + 4.2 + 8 + 2.0 = 47.0. 146.8 + 47.0 = 193.8. | yes |
| Page caches | 5 × 2,000 KiB = 10,000 KiB = 9.77 MiB. 4 connections: 8,000 KiB = 7.8. 2 connections: 4,000 KiB = 3.9. | yes |
| Each unit | 19,920 + 2,320 + 1,568 = 23,808 KiB = 23.25 MiB. Use: 64 + 320 + 23.25 = 407.25. Admission: 333.5 + 23.25 = 356.75. During verification: 224 + 23.25 + 19.45 = 266.7. Left in the use's unit: 512 − 407.25 = 104.75. | yes |
| Time | 3 × 600 = 1,800. 1,800 + 1,500 + 300 = 3,600. `ADMISSION_BOUND` = 3,600 + 60 = 3,660. The test's limit: 3,600 − 300 = 3,300. | yes |
| The whole Pi | 16,777,216 − 16,608,224 = 168,992 kB = 165.0 MiB (I re-read `MemTotal`). 2,048 − 165 = 1,883; 1,883 − 256 = 1,627. 1.1 × 10⁹ / 2²⁰ = 1,049.0; + 512 = 1,561. 1,627 − 1,561 = 66. | yes; nit 2 |
| Co-subject rows in a manifest | 7 × 100,000 = 700,000 rows × 80 B = 56,000,000 B = 53.4 MiB | yes |
| S4's bound | 700,000 × 671 B = 469,700,000 B = 447.9 MiB. 512 × 8 = 4,096. | yes |
| Revision 6 dense set; Prim's reads | 7.5 × 7,500² × 8 = 3,375,000,000 B = 3.14 GiB. 6,144 × 16,000² = 1.572864 × 10¹² B. | yes |
| `import-receipts` | 96 + 3.9 + "under 1" | understated; nit 1 |
| Per-person counts on the source | not in 14.1 | missing; S3 |

The worst process is still admission's lane set, at 333.5 MiB. Every unit stays under 512 MiB.

### Plan against spec

**Counts.** I counted the tests of every task the fixes changed. Each matches its "Expected" line:
- Task 7: 4. Task 8: 4 + 7 = 11.
- Task 13: 6. Task 19: 6 + 9 = 15.
- Task 15: 8. Task 16: 8 + 2 = 10.
- Task 24: 23, of which 18 are bad values.
- Task 25: 10. Task 26: 16, with 11 shared-field cases.
- Task 33: 15 + 15 + 2 = 32. Task 34: 9. Task 35: 9 + 5 = 14, with 1 skipped. Task 38: 11.
- Task 40: (8 − 2) + 4 + 2 = 12. Task 46: 12 + 1 + 5 = 18.
- Task 42a: 7. Task 45: 6. Task 47: 3.
- Task 5: 5 + 7 = 12, with 4 skipped.
- Task 50, engram file: 2 passed and 6 + 2 = 8 skipped, or 1 and 9 without `strace`. Peer file: 1 passed, 1 skipped.

**Coverage.** Every new test in spec 16 has a task. S5 is about tests that exist but are too weak.

### Files

- Both files end with a newline.
- Every `## ` and `### Task` heading of `e084597` is still present. The one exception is Task 5, retitled on purpose.
- The plan has 61 such headings. The spec has 21 `## ` and 11 `### `.

### Must-fix

**RM1. A co-subject recorded on a copy's source is never read, so the copy can leave without them.**

- **This spec.** 5.2 (spec lines 367-369) reads cosubjects(m) from the ledger's `subjects` table, rows with no
  `removed_seq`. The plan calls `ledger.cosubjects(ref)` (plan line 1001). That function runs only that query:
  `SELECT subject FROM subjects WHERE object=? AND removed_seq IS NULL` (`permission_ledger.py:574-577` on
  `permissions-core`).
- **The permissions spec.** An object's subjects also include, for a kept copy on the same ledger as its source, the
  source's subjects at the decision, read through `copies` up to 4 links (its 6.3 item 1, lines 641-643). That covers
  a subject recorded on the source after the copy was made (its 7.4, "Subjects recorded on the source later", lines
  1068-1076).
- **The code.**
  - `subjects_of` walks the chain (`permissions.py:1100-1117`).
  - `record_copy` writes the source's subjects into the copy's own rows once, when the copy is made
    (`permission_ledger.py:488-519`).
  - Step 1 already makes such copies: genome sync (`federation.py:207-213`) and a kept `remember`
    (`server.py:1999-2012`).
- **What happens.** Andy's genome sync copies an episode into an instance. Later he records Jenn on the genome episode.
  The permissions spec counts Jenn as a subject of the copy. This spec doesn't see her.
  - **A copy that leaves its owner's home** (any owner but Andy) sends that memory on the owner's yes alone. D27 says
    such a memory stays home, and the permissions spec refuses every use of it at the station. G18 doesn't hold it,
    since `others` counts 0.
  - **Andy's own copy** carries the memory without Jenn, against the anti-goal "Lost co-subjects" (line 213). If no
    other memory carries a co-subject, n = 0, and Andy's box says "no one but me is recorded on them". That is false:
    the M2 problem again.
  - **Her no.** Her deny or her retirement (S1) is never checked.
  - **Step 2.** The carried rows become the copy's `subjects` rows (D43), so the copy loses her for good.
- **Fix.**
  - Define cosubjects(m) as the permissions spec's subjects of m at the plan's time, less the owner: m's own rows plus
    each source's, up the `copies` chain (its 6.3 item 1 and 7.4). One recursive SQL query over `copies`, `subjects`
    and `stores` reads them without a State. `subjects_of` gives the same set.
  - Keep home a memory whose subjects number more than 8, since the permissions spec refuses it with `BOUND` (its 6.5,
    step 1, line 819).
  - `denied(m)` and `others` then follow by themselves.
  - Add a Task 8 test: a copy whose source gains a co-subject after the copy. At home the copy carries her and is
    counted in `others`. Away it stays home as "needs jenn's yes".

### Should-fix

**S1. A retired co-subject still refuses every use, and the source doesn't check it.**

- **The rule.** "The person, or a ledger admin, may retire a person ... every use of an object they are a subject of
  is refused (`RETIRED`)" (permissions spec lines 299-301). A steward may retire a place (lines 296-297).
- **It can happen in step 1.** The ledger owner is an admin (`permission_ledger.py:204`, `is_admin` 1), and
  `_may_retire_person` lets an admin retire anyone (`:1076-1078`). The CLI has `person retire`
  (`permission_cli.py:396-397`).
- **P36 keeps the rule.** It leaves step 1 of 6.5 unchanged: "a retired co-subject's home still refuses with
  `RETIRED`" (its lines 677-678; `_subject_retired`, `permissions.py:1418-1420`).
- **The gap.** The station can't see a retirement, and the source doesn't keep such a memory home. So admission and
  the trail evaluation would use a memory the permissions spec refuses. G18 holds it, since the memory carries the
  person, but not when the person comes through a copy (RM1).
- **Fix.** Keep such a memory home at the source, as `denied(m)` does, with counted words that are Rio Grande's call.
  Or name the case for G18's re-check.
- **Also.** Section 8's "Every step-1 verdict is the one this section's check gives" (line 1206) is too strong. Name
  the bound of 8 and a retired co-subject as its exceptions.

**S2. The permissions spec's account of this spec is out of date.**

- **Section 19** (its lines 2351-2361) says this spec's section 8 "leaves a carried co-subject's layer out of a decision
  inside the owner's home", and that the two "differ on a co-subject's deny, which can exist only from step 2". Both
  are now false:
  - this spec follows P36;
  - the permissions spec's own 7.6 (its lines 1103-1104) lets the owner write, in step 1, the layer of a place he stewards,
    and such a place can be a co-subject.
- **P36's "Why this form"** (its lines 696-697) has the same gap: "In step 1 only the ledger owner can write a layer
  (7.6), so a co-subject's layer is empty or missing."
- **Who fixes it.** The permissions spec's next revision, before G18's re-check. I edited neither spec.

**S3. The per-person counts on the source grow with the number of people.**

- **The counts.** The plan counts `others_people:<person>`, `needs_yes:<person>` and `said_no:<person>` in an
  in-memory `Counter` (plan Task 8). The dry run lists every name ("(3 people: jenn, lee, sam)"). Both grow with the
  number of distinct co-subjects. That number is at most 7 × 100,000 = 700,000, the spec's own worst case (D43).
- **Measured** on this Pi, in the session scratchpad, with system Python 3.11 and `tracemalloc`:

  | Distinct people | `Counter` keys `others_people:person:<16 characters>` | Peak, with the sorted names and the joined line |
  |---|---|---|
  | 100,000 | 11.9 MiB | 20.5 MiB |
  | 700,000 | 86.7 MiB (130 B a key) | 147.8 MiB |

- **At 700,000 people:**
  - plan: 140.0 + 147.8 = 287.8;
  - plan with the State: 280.9 + 147.8 = 428.7, over the 384 design peak (still under 512);
  - build: 300.9 + 86.7 = 387.6, over 384.
- **No test reaches it.** Task 50's cap fixture has co-subjects on 1,000 memories, so at most 7,000 people.
- **Fix.**
  - Count people with SQL in the scratch file, as the request's `others` already is (Task 18).
  - Print at most a fixed number of names, then "and N more".
  - Add the line to 14.1.

**S4. Catch up with the trail spec.**

- **Its third ask.** The trail spec's I7 asks a third thing: that admission show beside N how many sessions it couldn't
  count (`sessions_too_large`; its lines 1902-1905 and 319). Spec 17 says "It asks two things back, both taken" (line
  2715) and doesn't answer it.
  - To take it: carry the number in `result.json`, the `admitted` receipt and `station-imprints`.
  - Or decline it. Rio Grande's call.
- **Its check is now applied.** The trail spec has been revised after its check (its header, lines 23-33). These lines
  should point at that revision's re-check:
  - spec 17's "these answers hold as written until that revision" (line 2711);
  - G19's "Still waiting: that review's fixes" (plan line 4803).
- **A withdrawn sum.** 14.1's row for verifying and counting (line 2317) still says "The trail spec's own sum, 185.0
  (its I7), counts the batch once". The trail spec has withdrawn 185.0 and now gives 193.8 itself (its lines
  1898-1900). Drop the sentence.

**S5. Tests that can't fail, or don't test what they name.**

- **Task 50**, `test_scratch_stays_on_disk_where_it_belongs` (plan lines 4660-4670). Only the build half asserts that
  some temporary file was opened. The admit half asserts `all(...)` over a list that may be empty, so it passes whether
  or not the re-exec works. Assert a file there too, for example with a step that needs a temporary file. Or read the
  variables from the re-executed process's environment.
- **Task 24.** Every bad `others` case is sent by Sam's ship, so the audience rule refuses it first. No case tests the
  counts rule on Andy's own request (`serenity`). Two are missing:
  - `imprint_subjects` with `others` 0 (spec 16's "or the reverse");
  - `others.memories` above `contents.imprint_subjects`.
- **Task 8.** `not Refusals(...).any` doesn't show that no State was built, which spec 16 asks. Spy on
  `Ledger.state`.
- **Task 47** names only `CHECK_TEXT_AT_HOME` and `CHECK_TEXT` (plan line 4453), and its browser test covers only
  n = 37. Name `CHECK_TEXT_AT_HOME_NONE` too. Task 25 already tests that text through the API.
- **Task 45**'s new test gives Sam's imprint carried co-subjects (plan line 4333). That can't happen: only the
  operator's own copy carries any. Use Andy.

### Nits

1. **`import-receipts`** (spec line 2314). One batch holds up to 512 × 8 = 4,096 (subject, ref) pairs. The permissions
   spec measured 492 B a pair in `Uses.append`. 4,096 × 492 = 2,015,232 B = 1.9 MiB, not "under 1". The row comes to
   96 + 3.9 + 1.9 = 101.8, about 102 MiB, far under 384.
2. **The whole Pi** (14.1). The embedder unit says "~1.1 GB". Read as GiB, that is 1.1 × 1,024 = 1,126.4 MiB, and
   1,126.4 + 512 = 1,638.4 MiB is already over 1,627 before the system. 14.1's conclusion holds either way: the
   embedder may not fit, and then the station runs without it.

### What holds

- **The check's must-fix items.** M1 and M2 are resolved, everywhere the check named. The rest of the check is applied,
  and S4's hand-off to G18 is sound.
- **P36.** The three specs state it the same way: who it covers, that a deny refuses, and that it covers nothing shown
  to an agent and nothing outside the home. They agree on the memory budget and on what an imprint carries.
- **Memory.** Every figure holds when redone. The worst process is 333.5 MiB, and every unit stays under 512 MiB.
- **The plan.** It matches the spec task by task, and its test counts are right.
- **The files.** Both are complete.

**Next.** A revision that fixes RM1 should pass a re-check. G18 stays closed until the side-by-side re-check, which
should take S1, S2 and the S4 fact above.

## Re-check response

Date: 2026-10-26. By the spec's reviser, in the same worktree. I edited only the spec, the plan and this file, with
targeted edits. No code, commit, push, merge, deploy or post. The spec stays revision 7; its header and history row
list these fixes. RM1, S1, S3, S4, S5 and both nits are applied. S2 is the permissions spec's: I left that spec alone,
and its own reviser has since fixed it (below). Choices that are not Andy's are marked Rio Grande's call in the files.

Two other files changed in this worktree while I worked, both uncommitted and not by me. The trails review now has
its re-check ("approve with one change to the plan"). The permissions spec has its revision after its own re-check.
Where they touch this spec, I followed them (S2, S4).

### Must-fix

- **RM1. Applied.**
  - **The rule** (spec 5.2). cosubjects(m) is now the permissions spec's set of subjects of m at the plan, less the
    owner (its 6.3, item 1, and 7.4). That is m's own `subjects` rows with no `removed_seq`, plus, up the `copies`
    chain at most 4 links, each source's rows and its store's owner when the store is registered and no imprint.
    The spec says why `Ledger.cosubjects` falls short, citing the code you named. I re-read it on `permissions-core`
    at `dc0881e`: `cosubjects` at `permission_ledger.py:574-577`, `record_copy` at `:488-519`, `subjects_of` at
    `permissions.py:1100-1117`, genome sync at `federation.py:207-213`, `remember` at `server.py:1999-2012`.
  - **The query.** Plan Task 8 now has `COSUBJECTS_SQL`, one recursive query over `copies`, `subjects` and `stores`,
    asked once per memory, with no State. I ran it on this Pi (SQLite 3.40.1) against `subjects_of` on a fixture
    State built with the ledger's own schema: a copy of a copy, a removed row, a place subject, another owner's
    registered store, a source in an unregistered store, and a chain of 6 links. Every set matched, and the chain
    stopped after 4 sources. 100,000 queries took 2.9 s and 3.0 s in two runs.
  - **The bound** (spec 5.2, `bound(m)`). A memory with more than 8 subjects stays home, counted with no names. The
    query stops at 8 rows, which is enough to tell. Only a copy reaches the bound: `check_new_subject`
    (`permissions.py:2447-2451`) and `record_copy` (`permission_ledger.py:512-513`) stop an object's own rows at 8.
    So a shipped memory now carries at most 7 co-subjects by construction, the figure 7.2's 700,000 rows assume.
  - **What follows by itself.** `denied(m)`, `others`, the n = 0 box and the "Lost co-subjects" anti-goal now see a
    co-subject recorded on a source. One more change was needed: the plan's first query for denies asked only
    about the source's own co-subjects. A co-subject read through `copies` can belong to another store, so it now
    asks about every layer but the owner's home (5.2; plan Task 8, `Refusals`).
  - **Also changed:** the header, the history row, the non-goal, the anti-goal, D27 and its source column, 6.4 item
    5, section 8's "Subjects", section 13, 15, 16 (a new "Co-subjects through copies" test), 17 ask (b), and 18.
    Plan: A3, "What this plan uses" (the tables at `permission_ledger.py:56`, `:63`, `:65`; `MAX_COPY_CHAIN` and
    `MAX_SUBJECTS` at `permissions.py:33`, `:21`), the carried items, the verification and the self-review.
  - **Tests** (Task 8). `test_a_copy_carries_what_its_source_gains_after_the_copy`, which you asked for. The copy
    is made with the real `record_copy`, then jenn is recorded on its source. The copy's own rows don't name her,
    the query's set equals `subjects_of`'s less the owner, the copy is carried and counted at home, and away it
    stays home as "needs jenn's yes". A source 5 links up adds nothing. Also
    `test_what_the_permissions_spec_refuses_whole_stays_home`: a copy whose source gains 7 co-subjects after the
    copy ships with 7 when it has 8 subjects, and stays home when an own co-subject makes 9.
  - **The cap fixture** (Task 50) now has 7 co-subjects on every memory, 700,000 people in all, so the Pi tests
    reach the bounds this fix and S3 depend on.

### Should-fix

- **S1. Applied, by keeping such a memory home** (spec 5.2, `retired(m)`; section 8; Rio Grande's call).
  - The rule is the permissions code's own test, `_subject_retired` (`permissions.py:1418-1420`) with
    `place_retired` (`:547-553`): a person co-subject who is retired, or whose home or a place above it is. I
    re-read each step of your path: `is_admin` 1 at `permission_ledger.py:204`, `_may_retire_person` at
    `:1076-1078`, `person retire` at `permission_cli.py:396-397`.
  - Counted by person as "<name> is retired in your permissions ledger". A retirement between plan and build
    changes the digest, so the build refuses.
  - A retired **place** co-subject keeps nothing home. The permissions spec's 4.2 says a place's retirement refuses
    uses at it and below it, and `_subject_retired` reads only persons. That reading is named for G18's re-check.
  - The State is built when the ledger holds a retirement as well as a deny. It is already budgeted (14.1).
  - Section 8's "Every step-1 verdict is the one this section's check gives" now names its three exceptions, which
    the permissions spec refuses before any layer: a retired co-subject and more than 8 subjects (kept home now),
    and a road or trail with more than 8 (G18).
  - Test: the same new Task 8 test retires ava, and bo's home, and a place. The first two keep their memories home;
    the place keeps nothing.
- **S2. Not applied here, and now done in its own spec.** It is the permissions spec's text, and this task let me
  edit only the imprint spec and plan. That spec's revision after its own re-check, uncommitted in this worktree,
  now fixes both places. "Why this form" says a person co-subject's layer is empty in step 1, and a place
  co-subject's can hold a deny. Section 19, "The other two specs", says this spec reads a carried co-subject's layer
  as a restriction layer. Its 7.4 also states RM1's rule ("through `copies` too") and asks this spec's next revision
  to read the set that way, which it now does. Spec 17's new ask (c) and G18 record it, and G18's re-check confirms
  it.
- **S3. Applied** (spec 5.4, 14.1; plan Tasks 8, 15, 50).
  - Each memory's people go into a scratch table, `plan_people`. The counts and names are SQL over it. No key of
    `counts` names a person, and Task 8's first test checks that.
  - The dry run names at most 10 people for each reason (`NAMES_SHOWN`), then "and N more", and `--json` the same.
    Task 15's test plants 12 people and expects 10 names and "and 2 more".
  - Measured on this Pi (system Python 3.11, SQLite 3.40.1, `temp_store = FILE`, `SQLITE_TMPDIR` set before the
    start), using the plan's three queries: the peak rose by 5,440 KiB over 700,000 rows and by 4,624 KiB over
    2,800,000. A first run, counting memories by id alone, gave 5,504 and 5,264 KiB, and `strace` put its four
    temporary files in `SQLITE_TMPDIR`. So the cost doesn't grow with the rows. 14.1 allows the largest:
    5,504 / 1,024 = 5.375, shown as 5.4 MiB.
  - Your figures, checked: 280.9 + 147.8 = 428.7 and 300.9 + 86.7 = 387.6 under the old `Counter`. Now:
    - plan 96 + 9.8 + 16 + 18.2 + 5.4 = 145.4, and with the State 145.4 + 140.9 = 286.3;
    - build 145.4 + 2 + 8 + 6 + 3 + 1 = 165.4, and with the State 165.4 + 140.9 = 306.3;
    - one memory's co-subjects at a time, at most 8 ids of at most 255 characters (`MAX_PLACE_CHARS`):
      8 × (49 + 255) = 2,432 bytes, which doesn't show at 0.1 MiB.
    All are under 384. The worst process is still admission's lane set, at 333.5 MiB.
- **S4. Applied** (spec 10, 12, 14.1, 16, 17; plan R10, Tasks 23, 34 to 36, 48, G19).
  - **The third ask, taken** (Rio Grande's call). Admission keeps K, `sessions_too_large`, beside N in
    `result.json`, the `admitted` receipt (`DETAIL_KEYS`) and `make station-imprints`. Use receipts copy N alone,
    as before. K counts sessions the package holds, so it says nothing about what stayed home.
  - **One choice beyond the check.** The trail spec's re-check (its RS3) asks whether a session over the bound counts
    once per lane, and admission calls the count once per lane. So K is the largest lane's count, not the sum. It
    counts no session twice and is 0 only when every lane's count is 0. Task 35's test sees one session in both
    lanes and expects K = 1. G19 waits on RS3.
  - **Spec 17 and G19** now say the trail spec's revision is made and its re-check approves it, with one change to
    the trails plan. 17 says "three things back, all taken".
  - **14.1** drops the withdrawn 185.0. The row now says 193.8 is the sum the trail spec gives too.
- **S5. Applied.**
  - Task 50: the admit half reads each `execve`'s environment under `strace -f -v` and asserts that the re-exec
    set `SQLITE_TMPDIR`, `TMPDIR` and `IMPRINT_SCRATCH` to the scratch directory. strace 6.1 on this Pi prints
    that environment; I checked. Every temporary file must still lie there, but there may be none.
  - Task 24: `test_the_counts_rule_on_the_operators_own_request`, two cases on serenity: the reverse
    (`imprint_subjects` 3 with `others` 0), and `others.memories` 4 against 3 rows.
  - Task 8: `forbid_state` fails on any `Ledger.state` call. Under it the calm ledger's `Refusals` and a whole
    `base` pass run.
  - Task 47 names `CHECK_TEXT_AT_HOME_NONE` and gains a browser test at n = 0.
  - Task 45's test now uses Andy's ledger and imprint.

### Nits

1. **Applied** (14.1). The `import-receipts` row is 4,096 × 492 = 2,015,232 bytes = 1.9 MiB, and 96 + 3.9 + 1.9 =
   101.8, about 102. One correction to the wording: the permissions spec gives 492 bytes as a receipt's pair (its
   15: 75.1 MB for 20,000 refs of 8 subjects each), not as `Uses.append`'s, and 14.1 says so.
2. **Applied** (14.1). Read as GiB: 1.1 × 1,024 = 1,126.4 MiB, and 1,126.4 + 512 = 1,638.4 MiB, over 1,627 before the
   system. The conclusion holds either way.

### Counts and files

- Test counts changed: Task 8, 11 → 13 (Task 7's 4 and 9); Task 24, 23 → 25; Task 47, 3 → 4. Tasks 15, 35, 36, 45
  and 50 keep their counts. Their tests gained assertions or changed fixtures.
- Every `## ` and `### ` heading of `c795c59` is still present in both files, in the same order. The plan has 61
  `## ` and `### Task` headings. The spec has 21 `## ` and 11 `### `. Both files end with a newline, and
  `git diff --check` is clean.
- Ready for a re-check of RM1. G18 stays closed until the side-by-side re-check. It now lists the retired place
  co-subject reading and S2, and your S4 fact on the roads-and-trails rows.

## Final check (2026-10-26)

**Reviewer:** a fresh reviewer making the final check in Andy's place. I took no part in writing, checking,
re-checking or fixing this amendment. I edited only this file, by appending this section.

**What I read:**
- the uncommitted diff of the spec and the plan against `c795c59`, and the "Re-check response" above;
- the vision's principle 4 and "Open for Andy" (`docs/city-rail-vision.md:36-42`, `:137-143`);
- Rio Grande's rulings (permissions review lines 262-278);
- the permissions spec as revised after its own re-check (uncommitted): 6.3 at its lines 648-727, 7.4 at 1065-1129,
  15's budget at 2022-2045, and section 19 at 2369-2449;
- the trail spec as revised after its re-check: section 4 at its lines 326-335, R26 at 155, section 7 at 1063-1081,
  I7 at 1940-1950, and section 14 at 2208-2220;
- the code on `permissions-core` at `dc0881e`, in its own worktree.

Spec and plan lines below are the files as they stand now, uncommitted.

**Verdict: approve.**
- **RM1 is resolved** in the spec, the plan and the tests.
- **The fixes add no must-fix**, and the three specs still agree.
- **Two should-fix items and four nits** follow. None needs another check.

### RM1: resolved

**The rule.** Spec 5.2 (lines 380-392) now defines cosubjects(m) as the permissions spec's subjects of m at the
plan, less the owner. That is m's own rows plus, up the `copies` chain at most 4 links, each source's rows and its
store's owner when that store is registered and no imprint. This is the permissions spec's 6.3 item 1 (its lines
652-656) and 7.4, "Subjects recorded on the source later" (its lines 1101-1109).

**The code it must match.** I read each cited place on `permissions-core`:
- `subjects_of` (`permissions.py:1100-1117`) walks `copies` over at most `MAX_COPY_CHAIN + 1` = 5 refs: the ref
  and 4 sources. For each it adds `_own_subjects` (`:1083-1097`): the store's owner when its `stores` row has
  `imprint_of` null, and the subject rows in force.
- `Ledger.cosubjects` (`permission_ledger.py:574-577`) reads the ref's own rows only. The plan no longer calls it
  except in one test assertion (plan line 1000). I grepped both files: the other two mentions only say why.
- `record_copy` (`permission_ledger.py:488-519`) carries the source's subjects once (`:510-511`) and refuses a copy
  past 8 (`:512-513`). Genome sync (`federation.py:207-213`) and `remember` (`server.py:1999-2012`) call it.
- `check_new_subject` (`permissions.py:2447-2451`) caps an object's own subjects at 8, and ignores its copies. So
  only a copy can pass 8, through its sources, as `bound(m)` says (spec lines 423-430).
- The rest is where the plan says it is:
  - the tables (`permission_ledger.py:56`, `:63`, `:65`) and the index on `subjects(object)` (`:84`);
  - `MAX_SUBJECTS` and `MAX_COPY_CHAIN` (`permissions.py:21`, `:33`).

**The query.** This is `COSUBJECTS_SQL`, plan Task 8 step 3 (lines 1070-1085). I checked it myself rather than rely
on the reviser's run.
- **Setup.** In the session scratchpad (system Python 3.11, SQLite 3.40.1), I built 400 random ledgers with the
  ledger's own schema and log (`Ledger.create`, `_append`). They held:
  - registered, unregistered, other-owner and imprint stores;
  - subject rows, a third of them removed, and place subjects;
  - copy forests whose chains reached 11 refs.
- **Comparison.** For each ref and two owners, I compared the query's set with `subjects_of` less the owner. I also
  compared its 8-row form with the first 8 of that set.
- **Result.** 9,600 pairs, 0 mismatches.
- **The RM1 case on the real `record_copy`.**
  - `Ledger.cosubjects`: `[]`
  - the query: `['person:jenn']`
  - `subjects_of` less the owner: `['person:jenn']`
- **Time at the cap.** The ledger held 700,000 subject rows: 7 on each of 100,000 memories, half of them copies.
  100,000 queries took 4.3 s on this Pi. The reviser's 2.9 s and 3.0 s were at 100,000 rows.

**RM1's four effects are gone.**
1. **A copy that leaves its owner's home.** Without `home`, `base` drops a memory with cosubjects(m) ≠ ∅ (spec line
   359; plan lines 904-905). The away half of the new test sees the copy kept home as "needs jenn's yes" (plan lines
   1008-1009). D27 holds.
2. **Andy's copy.** The at-home half carries jenn as an `imprint_subjects` row and counts the copy in `others` (plan
   lines 1005-1007). `others` is counted from those rows (plan lines 1947-1949). The anti-goal "Lost co-subjects"
   now names the chain (spec lines 223-228).
3. **The n = 0 box.** n counts shipped memories that carry a row. So a co-subject recorded on a source makes n at
   least 1, and "no one but you is recorded on them" is true whenever n = 0.
4. **Her no and her retirement.** `denied(m)` and `retired(m)` read the same set (spec lines 410-445).
   - `Refusals.any` now asks about every layer but the owner's home, and about any retirement (plan lines 915-920).
     A co-subject reached through `copies` may belong to another store.
   - Building the State more often costs nothing new: 14.1 already counts it.

**The bound.**
- With a ledger, D37 requires the source store to be registered to the operator (`check_owner`). So the owner is
  always one of m's subjects.
- So 8 or more co-subjects means 9 or more subjects, which `decide` refuses with `BOUND` (`permissions.py:1629-1630`).
- The second new test (plan lines 1016-1031):
  - "eight" (andy and 7 people) ships with 7 rows;
  - "nine" (andy, kim and the same 7) stays home.

**The asked test.** `test_a_copy_carries_what_its_source_gains_after_the_copy` (plan lines 993-1014) is the test
RM1 asked for.
- It makes the copy with the real `record_copy`.
- It adds the chain's bound: a subject 5 links up adds nothing. The query recurses while `links < 4`, so it reads the
  ref and c1 to c4. `subjects_of` reads the same 5 refs.

**The digest.** A co-subject added up the chain between plan and build changes the build's result:
- at home, the `imprint_subjects` rows;
- away, which memories ship.

Either way the digest changes and the build refuses (spec lines 402-403).

**Count.** Task 8 has 9 tests, so 4 + 9 = 13, as plan line 1110 says.

### The rest of the re-check's fixes

- **S1.** `retired(m)` is the code's own test: `_subject_retired` (`permissions.py:1418-1420`) with
  `place_retired` (`:547-553`).
  - `decide` runs that test through `_any_retired` (`:1559-1566`), before `BOUND` (`:1629-1630`). The plan keeps the
    same order.
  - The step-1 path to a retirement is as cited: `permission_ledger.py:204`, `:1076-1078`, `permission_cli.py:396-397`.
  - A retired place keeps nothing home, since the code tests only persons. G18 is asked to confirm that.
- **S2.** Done in the permissions spec:
  - its "Why this form" (its lines 720-727) now says a place co-subject's layer can hold a deny in step 1;
  - its section 19, "The other two specs" (its lines 2409-2439), now tells this spec's rules;
  - that section 19 names RM1's fix: "the set is `subjects_of` at the plan, less the owner, and `denied(m)` and the
    bound of 8 read the same set". That is what 5.2 now does.
- **S3.**
  - People go into the scratch table `plan_people`, and the counts are SQL over it.
  - The dry run names at most 10 people for each reason (`NAMES_SHOWN`).
  - Task 8's first test checks that no key of `counts` names a person.
  - The memory figures are redone below.
- **S4.** K stands beside N. The trail spec has since settled RS3, the question of whether a session over the bound
  counts once per lane:
  - every lane's count is the same number, shown once and never summed (its lines 332-335, R26 at 155, I7 at
    1945-1950);
  - the largest lane's count is that number, and the trail spec says the two specs agree (its line 1950).

  Only the wording here is out of date (should-fix 1).
- **S5.**
  - Task 50 reads the re-exec's environment.
  - Task 24 adds two cases on serenity: 23 + 2 = 25.
  - Task 8 uses `forbid_state`.
  - Task 47 adds a browser test at n = 0: 3 + 1 = 4.
  - Task 45 now uses Andy.
- **Nits 1 and 2.** Applied. The arithmetic is below.

### Do the three specs agree?

| Point | Permissions spec | Imprints spec | Trail spec | Agree |
|---|---|---|---|---|
| A copy's subjects | Its own, plus each source's up `copies`, 4 links, at the decision (6.3 item 1; 7.4). A copy on another ledger carries them as read at the copy, "through `copies` too" (its lines 1111-1123). | cosubjects(m) is that set at the plan, less the owner, carried as `imprint_subjects` (5.2; section 8, "Subjects"). | Reads no co-subject row (R24; its line 1067). | yes |
| Who P36 covers | The owner's `imprint` and his bulk uses inside his home that show nothing to any agent. Each `need` use is tested on its own object (its lines 670-692). | Every step-1 use of a copy kept in the owner's home (section 8). Every memory is the owner's store's, so each `need` use qualifies too. | The same (its lines 1071-1077). | yes |
| A co-subject's deny | Refuses (its line 694; ruling M3). | Keeps the memory home (`denied(m)`), now read through `copies` too. | "a co-subject's no holds inside the home too" (its line 1076). | yes |
| A retired co-subject, more than 8 subjects | Refused before any layer, `RETIRED` and `BOUND` (its lines 696-697). | Kept home (`retired(m)`, `bound(m)`); section 8 names them as exceptions to its check. | Decides none of it (its line 1081). | yes |
| Content shown to an agent, or a use outside the home | Never covered (its lines 714-718). | Never covered (section 8; D27). | Shows nothing; only counts leave (R24). | yes |
| K beside N | — | The largest lane's count (10). | One number, the same in every lane (its lines 332-335). | yes |

### Memory, redone

MiB is 2²⁰ bytes.

| Figure | Arithmetic | Holds |
|---|---|---|
| The ledger's State | 45.0 + 64.5 + 25.3 + 6.1 = 140.9. That equals the permissions spec's 171.2 − 30.3 = 140.9 (its line 2037). | yes |
| Plan | 96 + 9.8 + 16 + 18.2 + 5.4 = 145.4. With the State: 145.4 + 140.9 = 286.3. | yes, under 384 |
| Build | 145.4 + 2 + 8 + 6 + 3 + 1 = 165.4. With the State: 165.4 + 140.9 = 306.3. | yes, under 384 |
| The people counts | 5,504 KiB / 1,024 = 5.375 MiB, shown as 5.4 | yes |
| One memory's co-subjects | 8 × (49 + 255) = 8 × 304 = 2,432 B, which is 2,432 / 1,048,576 = 0.002 MiB | yes |
| Revision 7's `Counter`, for the record | 280.9 + 147.8 = 428.7; 300.9 + 86.7 = 387.6 | yes |
| `import-receipts` | 512 × 8 = 4,096 pairs. 4,096 × 492 = 2,015,232 B, and 2,015,232 / 1,048,576 = 1.92, shown as 1.9. 96 + 3.9 + 1.9 = 101.8. The source of 492 B: 20,000 × 8 = 160,000 pairs, and 160,000 × 492 = 78,720,000 B = 75.07 MiB, the permissions spec's 75.1. | yes |
| The whole Pi, GiB reading | 2,048 − 165 = 1,883, and 1,883 − 256 = 1,627. 1.1 × 1,024 = 1,126.4, and 1,126.4 + 512 = 1,638.4, which is over 1,627. | yes |
| Co-subject rows | 7 × 100,000 = 700,000 rows. 700,000 × 80 B = 56,000,000 B, and 56,000,000 / 1,048,576 = 53.4 MiB. | yes |
| Worst process | 128 + 7.8 + 132.8 + 8.8 + 10.7 = 288.1. Then 288.1 + 14.1 = 302.2, and 302.2 + 31.25 = 333.45, shown as 333.5. | yes, unchanged |

Every process stays under its 384 MiB design peak, and every unit under 512 MiB.

### Files

- In both files, every `## ` and `### ` heading of `c795c59` is still there, in the same order. I diffed the heading
  lines.
- The plan has 61 `## ` and `### Task` headings. The spec has 21 `## ` and 11 `### `.
- Both files end with a newline.
- `git diff --check c795c59` is clean on the specs and plans.

### Must-fix

None.

### Should-fix

**1. RS3 is settled, so drop the wait.**
- **The out-of-date text:**
  - spec 10 (lines 1826-1827): "the trail spec's own re-check asks it to say ... Until it says, K is the largest";
  - plan R10 (line 139) and Task 35 (lines 3403-3405);
  - G19's "Still waiting: ... its RS3" (plan line 4943).
- **What changed.** The trail spec now says each such session counts once, and every lane's count is the same (its
  lines 332-335).
- **Fix.** Keep the largest, which equals that number, and say the trail spec settled it. Then G19 doesn't wait on an
  answered question.

**2. Date the test ledger's rows before NOW.**
- **The comparison.** Task 8's new test compares the query with `subjects_of(led.state(), ref, NOW)` (plan line
  1002).
- **Why the dates matter.** `subjects_of` counts a row only if its log time is at or before `at` (`_in_force`,
  `permissions.py:825-827`; `_span`, `:817-822`).
- **What the plan leaves open.** It doesn't say when `ledger`, `copy_of` and `add_subject` date their rows, and
  `copy_of` must pass `record_copy` a `now`.
- **How it fails.** If a helper uses the real clock, jenn's row isn't yet in force at a NOW of 2026-10-25. The
  assertion then fails while the code is right.
- **Fix.**
  - Say every test ledger row is written at NOW − 60 or earlier, including `record_copy(now=...)`. Or compare at the
    ledger's last time.
  - Name `GENOME_ID` and `ref_of` among Task 8's helpers.
  - Say `GENOME_ID` names no registered store. Otherwise sam's half would also count the genome store's owner, and
    its expected `{"person:jenn"}` would fail.

### Nits

1. **The counting order under the 8-row limit.** A memory can have 8 or more co-subjects with a retired one that
   sorts after the first 8 the query returns. It is then counted as "more than 8", not "<name> is retired", which
   is against 5.2's order (spec lines 458-460). It stays home either way. Say the order applies to the 8 rows read.
2. **The station could check the bound.** Check 10 (spec lines 1691-1694) checks each `imprint_subjects` row's form.
   The station's own check doesn't test `BOUND` (section 8), and it relies on the source for at most 7 rows a memory
   (D43). One `GROUP BY memory_id, layer HAVING COUNT(*) > 7` in check 10 would refuse a package that breaks the
   bound. It only narrows (Rio Grande's call).
3. **The trail spec's account is incomplete.** It says this spec keeps home a memory whose co-subject said no (its
   lines 1078 and 2216-2217). This spec now also keeps home a memory with a retired co-subject or more than 8
   subjects. The trail spec isn't wrong; its next revision can add it.
4. **Two permissions-spec passages are now out of date.** Its 7.4 says this spec's next revision "must read the set
   as this paragraph says" (its lines 1121-1123). Its section 19 gives that fix as still to come (its lines
   2428-2436). This spec now does it. G18's side-by-side re-check can say so.

### What holds

- **RM1.** It is resolved:
  - the query equals `subjects_of` less the owner on every case I tried, and stays fast at the cap;
  - a co-subject recorded on a source after the copy is carried at home and keeps the memory home away;
  - their deny and their retirement are checked;
  - a memory that the permissions spec refuses whole stays home.
- **The other fixes.** S1, S3, S4, S5 and both nits are applied, and S2 is done in the permissions spec. None adds a
  must-fix.
- **The three specs.** They agree on what a copy carries, on P36's reach, and on denies, retirements and the bound.
  They also agree that nothing is shown to an agent, and on K.
- **Memory.** Every figure holds when redone. The worst process is still 333.5 MiB.
- **Next.** The should-fix items can go in without another check. G18 still holds every imprint whose
  `others.memories` is above 0 until the side-by-side re-check. That check can take nits 2 and 4.
