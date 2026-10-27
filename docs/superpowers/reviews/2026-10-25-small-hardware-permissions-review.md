# Review: permissions spec revision 7 (small hardware, and the full store)

**Date:** 2026-10-26
**Reviewer:** a fresh reviewer acting in Andy's place (station law section 3). I took no part in the amendment.
**Spec:** `docs/superpowers/specs/2026-10-25-permissions-by-place-design.md`, revision 7 (`git diff HEAD`, branch
`trail-arrows-spec`).
**Controller tasks:** `permissions-core/.superpowers/sdd/2026-10-25-permissions-by-place/small-hardware-tasks.md`
(SH-1 to SH-11).
**Verdict: reject in this form.** Seven must-fix items remain. The memory work is mostly sound, and three of the
must-fix items are about it (M5 to M7). The other four are about P36, the new rule for the full store. P36 is a real
change to who may copy what, but the rest of the spec still says that no rule changed. A revision that fixes M1 to M7
should pass a re-check.

## What the amendment changed

- Header, 5.6, 6.4, 9.1, 12.2, 15, 16 and the tests U9, U15, U24 and U27: a memory budget of 512 MB per process on a
  2 GB Pi. A State now reads per-object rows lazily, `rebuild` reads the log row by row, the receipts fold works in
  batches, the cache has a byte bound, at most 2 frames decide at once, and the daemon uses only the shared embedder.
- 6.3: a new rule, P36. Inside the owner's home, an `imprint`, or a counted bulk use, reads the owner's layer alone.
  The co-subjects' layers are left out.
- 14 and 19: Andy's answer, "yes you can copy the full store", is recorded.
- Files are complete. Every `## ` and `### ` heading of HEAD is still present, the spec ends with a newline (2,013 to
  2,145 lines), and the task file ends with a newline and has all 11 SH tasks.

## How I checked

I read the diff, the vision (`docs/city-rail-vision.md`), the task file, and the imprints spec revision 7 in this
worktree. I read the built code on `permissions-core` (HEAD `0630947`) for every code claim below. I redid every memory
figure with the task file's unit sizes. MB means 2^20 bytes, as in the task file and as systemd's `512M`.

## Decision 1: small hardware

**Carried exactly.** Spec lines 44-50 quote Andy word for word, as the vision does (its principle 4). They list Rio
Grande's five points: a 2 GB Pi; under 512 MB resident per added process, measured on the Pi; streaming or bounded
batches; one shared embedder; `MemoryMax` of 512 MB or less on each added unit. The vision's clause "nothing holds a
whole store, a dense matrix or a whole graph" is in section 15 (line 1843). Section 15 marks the numbers as Rio
Grande's call (line 1817). Step 1 adds no systemd unit: the permissions plan names `systemd-run` only for test runs
(plan lines 3812, 3875, 3882).

**The "before" figures hold.** I redid each one:

| Figure | Arithmetic | Spec says |
|---|---|---|
| `Ledger.state()` at the reference ledger | (133.3 − 66.8) / 5,000 × 100,000 = 1,330.0, + 93.5 for records = 1,423.5 MB traced. Measured resident: +1,342.3 MB at 100,000 memories without records | about 1.4 GB (line 1859) |
| `rebuild`'s `fetchall` | 800,802 × 1,068 B = 815.6 MB, + 10,537 × 2,930 B = 29.4 MB, = 845.1 MB | about 845 MB (line 1860) |
| One eligible set | 20,000 × 9,546 B = 182.1 MB | about 182 MB (line 1861) |
| 64 cached sets | 64 × 182.1 MB = 11,654 MB = 11.38 GiB | about 11.4 GB (line 1862) |
| Reference ledger log rows | 7 × 100,000 + 100,000 + 2 × ⌈100,000 / 256⌉ + 10 + 10,496, plus setup rows ≈ 811,300 | about 811,000 (line 1818) |

The code claims behind them are right. `state()` reads every log row with its body and every table in one transaction
(`permission_ledger.py:229-250`). `rebuild` calls `.fetchall()` on the whole log (`permission_ledger.py:640`). The cache
holds 64 entries (`permissions.py:43`) with no byte bound (`lighthouse_daemon.py:556-562`). `FSet.__and__` copies a set
met with `FULL` (`permissions.py:1877-1884`). The daemon loads its own model when `ENGRAM_EMBEDDER_SOCKET` is unset
(`lighthouse_daemon.py:918-923`, `embeddings.py:200-207`).

**The "after" estimates hold at the reference ledger.** These are the task file's figures. I redid them:

| Operation | Arithmetic | Peak |
|---|---|---|
| A State | rows 65,536 × 404 B = 25.3 MB; log times 65,536 × 97 B = 6.1 MB; records 41.3 MB. Build peak 30.3 + 28.8 + 41.3 = 100.4 MB | 131.7 MB at most |
| Eligible-set rebuild | 30.3 + State 72.7 + set 16.0 + `made` 1.8 + placements 6.0 | 126.8 MB |
| The set itself | 20,000 × (569 + 134 + 29 + 80) B + 32,768 × 16 B = 10.85 + 2.56 + 0.55 + 1.53 + 0.50 | 16.0 MB |
| Bulk decision at its largest | 30.3 + 72.7 + run 47.5 (26.9 + 12.8 + 5.5 + 1.5 + 0.8) + trail refs 13.5 | 164.1 MB |
| Fold, small receipts | 30.3 + 4,096 × 8,608 B = 30.3 + 33.6 | 63.9 MB |
| Daemon | 30.3 + 2 × 119.2 (72.7 + 23.8 + 15.5 + 7.2) + cache 96 + page caches 15.6 | 380.3 MB; 409.1 MB with one frame's build transient of 28.8 MB |

So at the reference ledger every listed operation is under 512 MB. M5 to M7 are where the claim stops holding, or is
not shown.

## Decision 2: "yes you can copy the full store"

The quote is exact (lines 60, 2115), and the vision's reading is carried (lines 2115-2117). But the spec says two
opposite things about it. M1 to M4 follow.

**Do co-subjects of copied memories still protect those people?** Mostly yes, with one gap.
- The copy still carries every co-subject (P25; 7.4 lines 984-988). P36 keeps that (line 629).
- Every use that shows content to an agent, and every use outside the owner's home, still needs every subject's yes
  (lines 629-633). P36's conditions keep it inside the home: the requester acts for the owner, and `place:home/<owner>`
  dominates both P and H (lines 624-625). For Andy's own imprint at his station, H is the operator's home (6.1, lines
  565-567), so P36 can apply there.
- The gap: P36 drops a co-subject's whole layer, its denies included (M3).

## Must-fix

**M1. The spec says no rule changed, but P36 changes one.** P36 (lines 621-633) lets a use that revision 6 refused
through: an imprint of a memory with a recorded co-subject into the owner's home. These lines say otherwise:
- Lines 60-64: such a memory "is refused until that person says yes, even into his own home ... No rule changes here".
- Line 66: "No change in any pass widens a permission." P36 widens one.
- Lines 99-101: an imprint of such a memory "is refused until that co-subject says yes, wherever the copy is kept ...
  No rule either spec relies on changes."
- Section 3's table ends at P35 (line 219). P36 is used but never listed.
- 7.4, lines 973-974: "The memory doesn't move until they say yes on a ledger that holds their home." There is no P36
  exception.
- 19, lines 2117-2118: "This spec's rules stand. A recorded co-subject's layer must allow every use." Then lines
  2126-2134: "this spec stops it ... No pass of this spec does that by itself." Then line 2135: "Resolved ... P36".
- 19, lines 2119-2121: the imprints spec "keeps a stricter default ... no memory with a recorded co-subject leaves."
  The imprints spec's revision 7 dropped that for copies kept in the owner's home (its lines 4-9).
- Line 80 names the imprints spec as revision 6. It is now revision 7. That spec says this one offers P36's form
  "without applying" it (its line 1138).

Fix: tell one story. P36 is a widening inside the owner's home, made on Andy's answer. Say so in the header and at
line 66. Add P36 to section 3. Add Andy's two quotes as A6 and A7. Give 7.4 the P36 exception. Rewrite 19's item in
its resolved state. List P36 as a departure from the words of the vision's principle 1 inside the home, as 19 already
lists the two departures from principle 5 (lines 2107-2109).

**M2. P36 does not reach what it says it reaches, and it is unclear.**
- It covers `imprint` and *counted* bulk uses (line 626). But the trail evaluation's `read` batches are *named* bulk
  uses (9.1, lines 1178-1180; 15, line 1794). So are admission's `read` batches when the terms include `route` (6.4,
  lines 735-740). A bulk use that holds a refused memory is refused whole (6.4, lines 702-705). So with any carried
  co-subject, admission with `route` and every trail evaluation are still refused. The claims "and evaluate it there"
  (line 632) and "such as ... the trail evaluation" (line 627) are false as written.
- "Admission's calibration" is not a counted bulk use either. It runs under the named `imprint` batches (imprints spec,
  lines 1210 and 1230).
- An imprint needs `recall` and `read` too, and a counted `route` needs `recall` on every memory it names (6.4, lines
  637-653). P36 doesn't say whether it covers those needed uses. If each needed use is judged on its own action, only
  the `imprint` part passes, and the imprint is still refused.
- It doesn't say which of 6.5 step 1's subject tests still apply to a left-out co-subject: a retired home (`RETIRED`),
  or more than 8 subjects (`BOUND`).

Fix: say that P36 covers every use in `need(u)` of a use that qualifies. Say whether it covers named bulk uses (the
`read` batches) as well as counted ones. If it doesn't, drop the trail evaluation claim. Say which step 1 tests still
apply. Each choice is Rio Grande's call unless Andy takes it.

**M3. P36 drops a co-subject's denies too.** Leaving the layer out of `Req` removes its denies as well as its silence.
That conflicts with:
- P1, "deny records win literally" (line 185);
- the anti-goal "Widening by an agent ... or that removes a person's deny" (lines 1763-1764);
- the anti-goal "Picking a winner" (line 1767), and the vision's principle 6.

It also reaches people the owner never recorded. These include self-claimed co-subjects (7.4, line 965). They also
include the source's people that a kept copy carries (P25: `added_by` = `copy:<source ref>`, lines 984-986). Those are
other people's own memories, whose allows set a purpose and an end. Andy's answer lets the owner copy without their
yes. It doesn't say that a person's explicit no is overridden.

Fix (Rio Grande's call, or Andy's): under P36, read each co-subject's layer as a restriction layer. Silence and a
missing layer pass, and a deny refuses. In step 1 no co-subject has a layer (7.6, line 1025), so Andy's full store
copies exactly as P36 intends. If the choice is instead that denies don't hold, say so plainly and put it to Andy.

**M4. P36 has no test and no task.**
- Section 17 has no P36 test. U5 still says "a memory about Andy and Jenn is refused on Andy's yes alone" (line 1935).
- `decide` (Tasks 5 and 7, done) and the oracle `engram/tests/permissions_oracle.py` (Task 5A, done) don't have P36.
  The plan forbids editing an existing test file, with one named exception (plan lines 95-98). The task file has
  SH-1 to SH-11 only. None of them is P36.
- U22's last item (line 2041) and F1 (line 2080) need this spec's `decide` to give the imprints spec's verdicts. With
  a carried co-subject they can't, while the imprints spec reads Andy's answer more broadly (its lines 1130-1146). That
  spec holds back every such imprint until the two agree (its line 1144). That hold keeps step 1 safe, but the tests
  still need a fixture for this case.

Fix: add a U-test. If any P36 condition is false, the use is refused as before. If all are true, it is allowed. An
answer use inside the home is still refused, a use outside the home is refused, and the copy carries its co-subjects.
Add a deny case once M3 is settled. Add P36 to the oracle's rules and an F1 fixture with a carried co-subject. Add a
controller task for P36, with a named exception for the oracle file.

**M5. The 512 MB claim fails at the stated records bound.** Section 15 lets records grow to 32,768 before `state()`
merely warns (line 1820). A warning is not a bound. At 32,768 records:
- records in one State: 32,768 × 4,126 B = 128.9 MB (41.3 MB at the reference);
- a State: 128.9 + 25.3 + 6.1 = 160.3 MB; a frame: 160.3 + 23.8 + 15.5 + 7.2 = 206.8 MB;
- the daemon: 30.3 + 2 × 206.8 + 96 + 15.6 = **555.4 MB**. With one frame's build transient (32,768 × 2,877 B =
  89.9 MB) it is **645.3 MB**.
- `perform` holds up to three States at once: its own (`permission_ledger.py:340`, still live while `_outcome` runs),
  then `:372`, then `:377` while it is built. With 80 MB of box refs: 30.3 + 3 × 128.9 + 89.9 + 80 = **587.0 MB**.
  (At the reference it is 30.3 + 3 × 41.3 + 28.8 + 80 = 263.0 MB.)

The daemon fixed part is 30.3 + 2 × (25.3 + 6.1 + 46.5) + 96 + 15.6 = 297.5 MB, and each record costs 2 × 4,126 B in
two States plus 2,877 B in one build. So the daemon stays under 512 MB only up to (512 − 297.5) / 0.010613 ≈ 20,200
records. Fix (Rio Grande's call): put the warning at 16,384 records. That gives 297.5 + 16,384 × 0.010613 = 471.4 MB.
Make SH-10 due before a ledger passes it, or have the daemon serve nothing past it and say why. Show this arithmetic.

**M6. The fold's batch is bounded in count, not in bytes. SH-6's wording could also change receipts.**
- A recall receipt keeps every ref it returned in `returned` (`permission_uses.py:144-166`). The only limit on `k` is
  the 20,000 placements: `lighthouse_protocol.py:234-236` checks only `k > 0`, as the task file's item 12 says. A ref
  is about 86 characters, about 89 B in JSON. One such row holds 20,000 × 89 B = 1.70 MB of `returned`. A batch of
  4,096 such rows holds 4,096 × 1.70 MB ≈ **6,950 MB**. U24's fold fixture ("each a recall that cites 43 layers",
  line 2056) doesn't fix the size of `returned`, so it would miss this.
- SH-6 says to read "at most `FOLD_BATCH` rows past the latest anchor with `at` before the cutoff (`LIMIT`)". Today's
  fold takes only the leading run, and stops at the first row at or after the cutoff (`permission_uses.py:344-347`).
  That matters. A receipt's `at` is when the use was decided, and the daemon and the servers both append. So `at` is
  not in order of `seq`. A `WHERE at < cutoff` filter could fold rows past a younger row and anchor beyond it. The
  younger row would then sit behind the anchor, never verified and never folded.

Fix: inside each batch's transaction, verify and count row by row through a cursor. Keep only the running digest and
the monthly counts, and stop at the first row at or after the cutoff (or also bound a batch by bytes). Use recalls with
the largest `returned` in U24's fold fixture.

**M7. The spec doesn't show the budget it cites.** The cache row says the 96 MB comes "from the daemon's memory budget
(below)" (line 1805). Section 15's "Memory" says six operations peak under 512 MB (lines 1834-1841), but no figures
follow. The arithmetic is only in the controller's task file. Fix: add the "after" table above to section 15, with each
operation's figure and its margin. Say that MB means 2^20 bytes, and that U24's limit is `VmHWM` < 524,288 kB.

## Should-fix

- **S1. Processes left out of U24.** These are things this work adds that U24 doesn't measure (lines 2050-2058):
  - `perform` with gluing checks at the box refs bound (M5's three States, plus 80 MB);
  - `migrate`, whose collect acts can hold 100,000 members (the task file's Task 28 note: the body is held three
    times);
  - `rebuild` replaying that largest act. Neither the spec nor the task file gives that figure;
  - the `uses` views (SH-8);
  - `check`.

  Add them, or show their arithmetic. Also state what this work adds to the engram server, which already peaks at
  about 320 MB (`engram/CLAUDE.md`). Each server start runs the fold (task file item 10), and the server also builds
  States and the views.
- **S2.** U24 runs `systemd-run --scope` (line 2061). As a user that needs `--user`, as the plan (line 3812) and
  `engram/CLAUDE.md` use.
- **S3.** Section 8 (line 1139) states only the 4,096-box cap. Section 15 (line 1823) and U15 cite section 8 for the
  box refs bound. Add one sentence to section 8.
- **S4. Lazy State.**
  - Section 17 names no test that a State asked after later writes decides as it would at its own `seq`. SH-2 has
    guards for this. Add it to PT10 (line 1914), so other implementations meet it too.
  - Say that a failed lazy read during a decision counts as an unreadable ledger: serve nothing under `enforce`, and
    the CLI refuses. Today that handling covers only a failed `state()` (`lighthouse_daemon.py:677-688`).
  - The per-object tables can be read "as at `seq`" later. Their only in-place updates set `removed_seq` and
    `removed_by` (`permission_ledger.py:1026`, `:1052`; `permissions.py:390-399`), and lane notes and copies are only
    appended. Say so in 5.6.
- **S5. The embedder.**
  - SH-7 makes the daemon refuse to start without `ENGRAM_EMBEDDER_SOCKET`. `superyak-runtime` sets that variable only
    when `runtime.json` has `embedder_socket` (`scripts/runtime.py:653-655`). Before SH-7 merges, add a deploy gate:
    every machine that runs the daemon has that key and runs the embedder unit.
  - The 2 GB target is per process. The embedder unit carries `MemoryMax=3G` (`scripts/superyak-embedder.service:14`).
    Say that the spec doesn't claim the whole machine fits in 2 GB, or measure it.
- **S6. Margin.** The daemon's estimate (380.3 MB) leaves out a frame's build transient. With it the estimate is
  409.1 MB. That leaves 102.9 MB (20 %) for resident memory above traced bytes, and that gap was not measured. Name
  the first lever if U24 reads over about 450 MB, for example `CACHE_BYTES` 64 MB, or `FRAMES_AT_ONCE` 1. That is Rio
  Grande's call.
- **S7.** U24's claim that the 16 GB Pi 5 measures for the 2 GB target (lines 2061-2063) holds in the safe direction.
  Add why: this Pi's kernel (`6.12.109+rpt-rpi-2712`) uses 16 KB pages (`getconf PAGESIZE` = 16384). Resident figures
  here are no lower than on a 4 KB-page Pi.
- **S8.** Mark the new constants 65,536 rows, 2 frames, 4,096 receipts and 2,000,000 refs as Rio Grande's call, as the
  other new rows are (lines 1819-1823). Section 3's catch-all (line 175) covers them, but the text is uneven.
- **S9. Task file nits.**
  - The `server.py` line numbers moved by 9 after `169f51e`: `:2082` is now `:2091`, `:2251` is `:2260`, `:2436` is
    `:2445` and `:2484` is `:2493`.
  - "6 × 16.0 = 96.0 is not under it" doesn't fit "at most 96 MB". The sets are 15.99 MB each, so 6 do fit.
  - SH-4's estimate counts 16 B per memory id for the frozenset. The measured cost is 26 B per id (0.5 MB / 20,000).
    U9's ratio test (1.0 to 1.6) will catch this, but the estimate should round up.

## What holds

- **Batching changes no verdict.**
  - A running minimum gives the same `until` and horizon as the minimum over all terms (6.5 steps 6-7).
  - Shared `Cited` objects are equal values, so verdicts and receipts are the same.
  - A cache entry over 96 MB is served and not kept, which changes no verdict.
  - A third frame waits and is never refused (12.2, line 1471).
  - The fold's per-batch anchors verify from each anchor (U27 and SH-6's tests), apart from M6's leading-run point.
- **Rows read later still read as at `seq`.** The build reads the per-object tables with their seq columns
  (`permissions.py:384-399`, `:461-469`). SH-2's guard tests compare lazy and eager States at the last `seq` and at a
  `seq` halfway.
- **Existing tests that compare mappings still work.** Some compare a State's mappings to dicts
  (`tests/test_permissions_keep.py:133`, `:200`). A lazy mapping that subclasses `collections.abc.Mapping` compares
  by items, so they keep passing.
- **The task file's code claims hold.** I checked them against the code, at the lines given or nearby:
  - `state()` at `permission_ledger.py:229-250`, and `rebuild` at `:640`;
  - the fold at `permission_uses.py:335-373`, `_subjects_of_rows` at `:421-426`, `agent_view` at `:464-483` and
    `_self_claims` at `:580-589`;
  - `decide_bulk` at `permissions.py:1703-1750` (it takes trail touches through a callable, so the touches are never
    held whole) and `eligible_set` at `:1775-1805`;
  - the daemon's threaded server at `lighthouse_daemon.py:855-858`, `store_digest` at `:130-134` and `main` at
    `:904-934`.
- **The task file's test thresholds are right.** I redid each one: SH-1's 62.5 MB and 18.5 MB, SH-2's 84.8 MB, SH-3's
  953, 776, 274 and 450 B, SH-6's 41.0 MB and 11 anchors, and SH-8's 30.3 MB and 187.5 MB.

## Controller rulings on the check (Rio Grande, 2026-10-26 15:00)

- **M1 (one story).** P36 is a widening, made on Andy's own answer ("yes you can copy the full store", to a question
  that named family, colleagues and patients). Say so plainly: add Andy's two quotes as A6 and A7 and P36 to section 3,
  list P36 as a departure from the words of the vision's principle 1 inside the owner's home, and correct every line
  that says no rule changed, the 7.4 text, section 19 and the imprints revision named.
- **M2 (P36's reach).** P36 covers the owner's `imprint` into his own home and every bulk use inside his home that
  shows no content to any agent, named or counted: admission's checks and calibration, and the trail evaluation's
  `read` batches, whose outputs are counts and rates. It covers the `recall` and `read` that `need(u)` adds for those
  uses. It never covers a use that shows content to an agent or whose P or H is outside the home.
- **M3 (denies hold).** Under P36 each co-subject's layer is read as a restriction layer: silence and a missing layer
  pass, a deny refuses. So a person who has said no keeps their no, even inside Andy's home. This is narrower than
  dropping the layer and needs no question to Andy.
- **M4 to M7.** Apply as the check says: a U-test, oracle support and an F1 fixture for P36, written as a controller
  task for the permissions build (with a named exception for the oracle file); the records bound at 16,384 with the
  arithmetic; the fold bounded by bytes as well as count, through a cursor, keeping the leading-run rule; the budget
  table in section 15 with MB defined as 2^20 bytes.

## Response (the reviser, 2026-10-26)

Applied to the spec (revision 7, still uncommitted on `trail-arrows-spec`) and to the controller's task file
(`permissions-core/.superpowers/sdd/2026-10-25-permissions-by-place/small-hardware-tasks.md`, git-excluded). Nothing
is committed. Code claims were re-read at `permissions-core` HEAD `91a26a7` (Task 28 landed during this pass; it moved
only `permission_cli.py` lines and `Ledger.create`'s channel). Every `## ` and `### ` heading of HEAD is still in the
spec, in order, and both files end with a newline. Choices that aren't Andy's are marked "Rio Grande's call" in the
spec.

**M1 (one story). Done.** The header (status, the revision 7 bullets, the "no pass widens" line, "Depended on by"
and its revision 7 bullet) now says P36 widens one rule on Andy's decision. Section 3 gains A6 and A7 (Andy's two
quotes), P36, and P37 (Rio Grande's reading of A7). 7.4 gains P36's exception, and its stale sentence on the imprints
spec's D27 now says what that spec's revision 7 does (ship only in a copy kept in the owner's home, rows in
`imprint_subjects`, D43). Section 19 tells the item in its resolved state, drops "this spec stops it", and lists P36
as a departure from the words of principle 1 beside the two from principle 5. "Depended on by" names imprints
revision 7 and trail revision 9 (also in 6.4 and 11). 6.6 gains "P36 and the proofs": L1 to L3, L5, L7 and L8 hold,
L4's second half holds, its first half doesn't bound a qualifying use, by A6.

**M2 (reach). Done, as the ruling says.** P36 covers the owner's `imprint` kept in his home and every bulk use, named
or counted, inside his home, and every use in their `need`. That is all the imprints spec's step-1 uses on a copy
kept in the owner's home: its requester acts for the operator, who is then the owner (its D9). It never covers an
answer use, or a use whose requester, P or H is outside. 6.5 step 1 is unchanged: `RETIRED`, `NO_LAYER` and `BOUND`
still apply to every subject. A `remember` by the owner's agent into a store at home qualifies, as an `imprint`.

**M3 (denies). Done.** A co-subject's layer is read as a restriction layer: silence and a missing layer pass, a deny
refuses with `DENIED` at that layer, in its place in step 2's order, citing nothing, with its dated denies in `until`
and its records' times in the horizon. P36 states that it reaches self-claimed and carried co-subjects too, so a
copy the owner kept of someone else's memory imprints into his home on that person's silence but never against their
deny. New anti-goal "Overriding a no". In step 1 every co-subject layer is empty or missing, so Andy's full store
copies as he decided.

**M4 (tests). Done.** U5 now says "for every use P36 doesn't cover". New U29 has every case the check asked for, and
the deny case. U22's last item gains an imprint with a carried co-subject that has no layer (agrees with the imprints
spec in step 1). F1 gains the evaluation and admission on such an imprint, allowed with no layer and `DENIED` with a
deny. Spec 18's generators reach qualifying uses. Controller task SH-12 adds P36 to `decide`, `decide_bulk` and the
oracle, with a named exception to the plan's lines 95-98 for `tests/permissions_oracle.py` only (`layer_order`
`:472`, `object_refusal` `:493`), U29 in a new file, and the F1 fixture after Task 30.

**M5 (records). Done, with a hard bound.** Rio Grande's call: a ledger holds at most 16,384 records, revoked and
replaced ones included; a write past it is refused (5.4), as 5.4's other bounds are. A revocation writes no record, so
the owner can always narrow. A ledger past it, which only other code could write, reads as unreadable (5.6), so the
daemon serves nothing. SH-10 lifts the bound and is due before a ledger needs more. Arithmetic in 15 ("The records
bound"): fixed part 30.3 + 2 × (25.3 + 6.1 + 46.5) + 96.0 + 15.6 = 297.7 MB; 11,129 B a record; break-even
(512 − 297.7) / 0.0106 ≈ 20,200; at 16,384, 297.7 + 173.9 = 471.6 MB (471.7 in the table, parts rounded first; the
check's 471.4 rounds at the end). At 32,768: 645.5 MB, or 555.6 MB without a build (the check: 645.3 and 555.4).

**M6 (fold). Done.** 9.1: only the leading run folds, citing `permission_uses.py:344-347` and why `at` isn't in `seq`
order. Each batch reads through a cursor, verifies each receipt against the running digest, upserts its counts and
keeps nothing of it, so its memory is one receipt. SH-6 is rewritten so, with two new tests: rows of 1 MB each, and a
younger receipt at a lower `seq`. U24's fold fixture now fixes `returned` (20 refs with 8 subjects) and adds 64 named
bulk receipts at the largest. **Beyond the check:** `returned` is not the only thing a recall receipt grows with. It
has a `use_subjects` row per subject of each returned ref (`lighthouse_daemon.py:493`). I measured, on this Pi,
`Uses.append` of one recall of 20,000 refs × 8 subjects: 75.1 MB traced (492 B a pair), and `verify()` of it:
102.4 MB (671 B a pair). Two frames writing such receipts would add 150.2 MB to the daemon, past 512 MB at the bound
(471.7 + 150.2 = 621.9). So, Rio Grande's call (12.2, SH-14): the daemon answers a recall with at most 20 candidates,
the cap engram's own client already enforces (`lighthouse_client.py:17`, `:109`; both readers use it,
`neighbors.py:90`, `context_lighthouse.py:159`). Nothing engram sends changes.

**M7 (budget). Done.** Section 15 gains "The budget": MB = 2^20 bytes, the units, and a table with each operation's
parts, its figure at the reference ledger and at the bounds, and its margin: `state()` 100.4 to 131.8 (171.2 at the
bounds), eligible set 126.8 (150.0), bulk 164.1 (187.3), fold 32.4 (38.2), daemon 380.3 / 409.1 (426.7 / 471.7, margin
40.3), `perform` 190.2 (213.4), `check` 183.0 (206.2), `uses` 118.6 (141.8), `rebuild` 69.9. The check's 131.7 is
131.8 here, from rounding the parts first. U24 states the limit as `VmHWM` under 524,288 kB.

**S1 (left out of U24). Done.** U24 now runs `perform` (an `allow` whose gluing checks meet 100,000-member collections,
and a 10,000-member `collect`), `rebuild` of a log holding that act, `check`, `uses`, `migrate`, and the daemon again
at 16,384 records. Two more Rio Grande's calls, each measured or shown:
- `perform` holds one State at a time (5.6, SH-13). Three States at the bound are 30.3 + 3 × 95.9 + 45.0 + 80.0 =
  443.0 MB; one is 213.4 MB. This matters most in the engram server, where `permit` runs `perform`.
- one `collect` or `uncollect` act names at most 10,000 objects (5.4, SH-13). Measured on this Pi: a collect body
  peaks at 4,009 B a member with its first lane note in `perform`, and its replay in `rebuild` at 3,742 B a member
  (35.7 MB for 10,000). One act of 100,000 would hold 382.3 MB and 356.9 MB. `migrate` (Task 28, `91a26a7`) already
  writes acts of 500 (`permission_cli.py:754`).

The engram server is stated (15): it already peaks at about 320 MB (`engram/CLAUDE.md:44-45`); this work adds at most
one `perform` above its imports, 159.9 MB (183.1 at the bounds), so about 480 MB (503 MB). It is not a process this
work adds.

**S2. Done:** `systemd-run --user --scope` in U24. **S3. Done:** section 8 states the box refs bound. **S4. Done:**
PT10 gains the lazy-State test (and SH-2 a guard); 5.6 and 12.2 say a failed lazy read counts as an unreadable ledger,
handled as `lighthouse_daemon.py:678-689` handles a failed `state()` (and SH-1 a test); 5.6 says why later reads
read as at `seq` (`permission_ledger.py:1026-1027`, `:1052-1054`; `permissions.py:390-399`, `:458-467`). **S5.
Done:** 12.2 has the deploy gate (`scripts/runtime.py:653-655`; also in SH-7) and says the 2 GB target is per
process, not per machine (`scripts/superyak-embedder.service:14`, `MemoryMax=3G`). **S6. Done:** 15, "Margin": if a
daemon run reads 480 MB or more, first a 64 MB cache, then one frame at a time. I put the trigger at 480 MB, not 450,
because the estimate at the records bound is already 471.7. **S7. Done:** in U24 (`getconf PAGESIZE` = 16384 here).
**S8. Done:** the new constants are marked Rio Grande's call. **S9. Done** in the task file: the `server.py` lines
(`:2091`, `:2260`, `:2445`, `:2493`), and the CLI's eight `state()` callers at `91a26a7`; 6 sets fit in 96 MB
(6 × 15.99 = 95.9); 26 B per memory id.

**For the other specs' revisers** (not edited here):
- The imprints spec's section 8, "Carried co-subjects in the meet", leaves a carried co-subject's layer out; P36 reads
  it as a restriction layer. They agree in step 1 and differ on a deny from step 2. Its header (lines 10-12), its
  section 17 ask (a) and its section 18 hold should take P36's form; lifting the hold is that spec's call.
- The trail spec's section 7, "On a full-store imprint", cites this spec's "check of revision 7" finding, which is
  now replaced by P36.

**How I measured** (this Pi, the build's `engram/.venv`, Python 3.13, `tracemalloc`, scratch files only, `-I -B`):
a `collect` body of 10,000 members built, canonicalized, parsed and digested as `_append` does; `Ledger.rebuild` of
one such log row; `Uses.append` and `Uses.verify` of one recall receipt of 20,000 refs × 8 subjects.

## Re-check (2026-10-26, after the response)

**Reviewer:** a second fresh reviewer acting in Andy's place (station law section 3). I took no part in writing,
checking or fixing this amendment.
**What I read:** the spec as committed in `c795c59` (`git diff e084597`); this file's check, rulings and response;
the vision (principle 4 and "Open for Andy"); the imprints spec revision 7 and the trail spec revision 9, as committed
in the same commit; the task file (SH-1 to SH-14); and the build on `permissions-core` at HEAD `dc0881e` (Tasks 1 to
30). Since `91a26a7`, only `permission_cli.py`, the F1 fixtures and new test files changed in the build. I edited
nothing there. I ran one read-only count with its `.venv` and `-B` (RCS2).
**Verdict: reject in this form.** M1 to M7 and S1 to S9 are resolved, apart from the leftovers named in RC1, RCS2 and
RCS5. Every memory figure in section 15 checks to 0.1 MB. Four new must-fix items remain, each a few lines:
- the spec's account of the other two specs is out of date (RC1);
- an imprint doesn't carry the subjects a memory has through `copies` (RC2, mostly the imprints spec's fix);
- SH-13's records bound misses `sign` (RC3);
- P36's test of who qualifies is wider in two places than its own words (RC4).

A revision that fixes RC1 to RC4 should pass.

### The check's items

| Item | Now | Where |
|---|---|---|
| M1 one story | Resolved, with RC1's leftovers and RCS5 | header lines 65-77 and 108-116; section 3's A6, A7, P36 and P37 (lines 200-201, 237-238); 7.4 lines 1049-1052; 19 lines 2329-2361 |
| M2 reach | Resolved | 6.3 lines 662-679: the uses their `need` adds, named and counted bulk uses, admission's checks and calibration, the evaluation's `read` batches; 6.5 step 1 unchanged |
| M3 denies | Resolved | 6.3 lines 672-685; the anti-goal "Overriding a no" (line 1876) |
| M4 tests | Resolved; see RCS2 and RCS3 | U5 (line 2117), U22 (2225-2227), U29 (2272-2289), F1 (2297-2301), 18 (2309); SH-12 |
| M5 records | Resolved in the spec; SH-13 has a hole (RC3) | 5.4 lines 509-514; 5.6 lines 586-587; 15 lines 2015-2019; SH-1, SH-13 |
| M6 fold | Resolved | 9.1 lines 1307-1315; U27 (2263-2270); SH-6 |
| M7 budget | Resolved | 15 lines 1979-2041; U24 states `VmHWM` under 524,288 kB |

S1 to S9 are done as the response says. I checked each:
- S1 and S2 in U24 (lines 2238-2258);
- S3 in section 8 (lines 1219-1221);
- S4 in PT10 (lines 2094-2095), 5.6 (lines 579-587) and 12.2;
- S5 in 12.2 (lines 1576-1582);
- S6 in "Margin" (line 2038);
- S7 in U24 (line 2258);
- S8 in section 15's rows;
- S9 in the task file.

### P36 in the three specs

They agree on the rule:
- **Who it covers.** The requester acts for the owner. The use's place and its holding place are in his home. It is
  his `imprint` into a copy kept there, or a bulk use, named or counted, with the uses their `need` adds:
  - permissions 6.3 (lines 662-673);
  - imprints section 8, "Carried co-subjects in the meet" (its lines 1190-1194);
  - trail section 7, "On a full-store imprint" (its lines 1057-1060).
- **A co-subject's deny still refuses**, inside the home too:
  - permissions 6.3 (lines 674-676 and 693-696) and the new anti-goal;
  - imprints (its lines 1193-1194 and 1207-1212, and `denied(m)` at its lines 385-398);
  - trail (its lines 1058-1061).
- **Nothing that shows content to an agent, or leaves the home, is covered:**
  - permissions 6.3, "What it never covers" (lines 687-691);
  - imprints (its lines 1199-1201 and 1213-1215, and the ceiling's item 6);
  - trail (its lines 1051-1054).

The note on the proofs (6.6, lines 964-969) is right. A restriction layer is still a term of the meet, and adding a
co-subject still only narrows. So PT1 and PT7 (`tests/test_permissions_properties.py:431-466`, `:584-600`) keep holding
after SH-12.

Two gaps remain, both in RC1. This spec still describes the other two specs as they were before their revisions. And
the specs differ on one rule, which the imprints spec found: the bound of 8 subjects on a road or trail.

### What an imprint carries

By P25 and 7.4, a kept copy carries every subject of its source. On one ledger it also has its source's subjects at
each decision, read through `copies`. The imprints spec says an imprint carries "every co-subject its source's ledger
recorded at the plan" as `imprint_subjects` rows (its D43, and its lines 1129-1131). But it defines that set from
`subjects` rows only (its lines 366-369). The two differ for a memory that is itself a kept copy (RC2). The trail spec
reads no co-subject row (its line 1051), so this doesn't touch it.

### The memory budget

The three specs set the same target:
- a Raspberry Pi with 2 GB of RAM;
- each process this work adds peaks under 512 MiB resident, measured on the Pi;
- each unit it adds carries `MemoryMax=512M`;
- MB or MiB means 2^20 bytes.

These are in permissions P37 and 15 (lines 1942-1946 and 1979), imprints D42 and 14.1, and trail R20 and 10.1. The
imprints spec uses this spec's State at the bounds: 45.0 + 64.5 + 25.3 + 6.1 = 140.9 MB (its 14.1, first row). That
matches section 15.

I redid every figure in section 15 from its units, with 1 MB = 1,048,576 B:

| Figure | Arithmetic | Spec |
|---|---|---|
| Row and time caches | 65,536 × 404 B = 26,476,544 B = 25.25; 65,536 × 97 B = 6,356,992 B = 6.06 | 25.3, 6.1 |
| Records | 10,496 × 4,126 B = 41.30, × 2,877 B = 28.80; 16,384 × 4,126 B = 64.47, × 2,877 B = 44.95 | 41.3, 28.8, 64.5, 45.0 |
| A State with full caches | 41.3 + 25.3 + 6.1 = 72.7; 64.5 + 25.3 + 6.1 = 95.9 | 72.7, 95.9 |
| `state()` | 30.3 + 28.8 + 41.3 = 100.4, + 31.4 = 131.8; 30.3 + 45.0 + 64.5 = 139.8, + 31.4 = 171.2; 512 − 171.2 = 340.8 | the same |
| One eligible set | 20,000 × (569 + 134 + 29 + 80) B + 32,768 × 16 B = 16,764,288 B = 15.99 | 16.0 |
| Eligible-set rebuild | 30.3 + 72.7 + 16.0 + 1.8 (20,000 × 93 B) + 6.0 (20,000 × 316 B) = 126.8; with 95.9, 150.0 | the same |
| A bulk decision's run | 26.89 + 12.78 + 5.53 + 1.53 + 0.76, rounded first: 26.9 + 12.8 + 5.5 + 1.5 + 0.8 = 47.5; trail refs 100,000 × (134 + 8.45) B = 13.59 | 47.5, 13.6 |
| Bulk decision | 30.3 + 72.7 + 47.5 + 13.6 = 164.1; with 95.9, 187.3 | the same |
| The fold | 160 × 671 B = 0.10, so 30.3 + 0.1 + 2.0 = 32.4. 4,096 × 671 B = 2.62 and 3 × 30,720 × 37 B = 3.25, so 30.3 + 2.6 + 3.3 + 2.0 = 38.2 | the same |
| A daemon frame | 23.8 (16.0 + 1.8 + 6.0) + 15.51 (20,000 × 813 B) + 7.23 (20,000 × 379 B) = 46.5; 72.7 + 46.5 = 119.2; 95.9 + 46.5 = 142.4 | the same |
| The daemon | 30.3 + 2 × 119.2 + 96.0 + 15.6 = 380.3, + 28.8 = 409.1; 30.3 + 2 × 142.4 + 96.0 + 15.6 = 426.7, + 45.0 = 471.7; 512 − 471.7 = 40.3 | the same |
| The records bound | fixed part 30.3 + 2 × 77.9 + 96.0 + 15.6 = 297.7; a record 2 × 4,126 + 2,877 = 11,129 B = 0.010613; (512 − 297.7) / 0.010613 = 20,191; at 16,384, 297.7 + 173.9 = 471.6; at 32,768, 645.5, or 555.6 without a build | the same (about 20,200) |
| `perform` | the insert list 10,000 × 753 B = 7.18; 30.3 + 72.7 + 80.0 + 7.2 = 190.2; 213.4 at the bounds; before the check, 30.3 + 95.9 + 16.8 + 38.2 = 181.2; three States, 30.3 + 287.7 + 45.0 + 80.0 = 443.0 | the same |
| `check`, `uses`, `rebuild` | 30.3 + 72.7 + 80.0 = 183.0, and 206.2; 200 × 40 KB = 7.81, × 2 = 15.6, so 118.6 and 141.8; 10,000 × 3,742 B = 35.69, so 30.3 + 35.7 + 3.9 = 69.9 | the same |
| The engram server | 190.2 − 30.3 = 159.9 and 213.4 − 30.3 = 183.1; 320 + 159.9 ≈ 480, 320 + 183.1 ≈ 503 | the same |
| Before the bounds | 4,096 × 20,000 × 89 B = 6,953.1; 2 × 75.07 = 150.1 (the spec rounds first and gets 150.2) | the same |

The figures' assumptions hold in the code:
- A recall's receipt merges only the decisions of the refs it returned (`lighthouse_daemon.py:487-490`). So with at
  most 20 refs, the uses view's "at most 20 records cited in each of 40 consent layers" holds.
- Verifying a receipt never parses `cited` (`permission_uses.py:112-113`, `:314-322`). So "held about 3 times" is the
  row, its canonical JSON and its bytes.
- No step-1 code writes a local bulk receipt: `row_for_bulk` (`permission_uses.py:170`) has no caller outside tests.
  So the fold's 38.2 MB case is a safe over-estimate.

I did not re-measure the unit sizes, or check whether a whole 2 GB machine fits. The spec claims neither (12.2,
lines 1579-1582).

### The task file and the build

SH-1 to SH-14 match the spec as it now stands, apart from RC3, RC4, RCS2 and RCS6 to RCS9:
- **The records bound of 16,384.** SH-1 counts the records in SQL before loading them, and a State past the bound
  refuses to build. Its test also checks that the daemon then serves nothing. SH-10 lifts the bound. SH-13 refuses
  writes past it, but see RC3.
- **The fold, bounded in bytes, with the leading-run rule.** SH-6 reads through a cursor. It verifies and counts one
  receipt at a time, keeps only the running digest, stops at the first receipt at or after the cutoff, and commits
  each batch with its own anchor. Its new tests cover rows of 1 MB, and a younger receipt at a lower `seq`, where
  today's fold also stops (`permission_uses.py:344-347`). This is what 9.1 says.
- **SH-12 (P36).** Its rule matches 6.3, apart from RC4. Its tests are U29 and the F1 cases, in full.
- **SH-14** caps `k` at `lighthouse_daemon.py:752`, inside `_rank_recall` (`:742`).

I checked these code claims, at `dc0881e` unless marked:
- `perform`, `_outcome`, `_on_proposal` and `_sign_alone` (`permission_ledger.py:330-351`, `:364-380`, `:404-445`,
  `:447-465`). `perform` holds one State (`:340`), and `_outcome` builds two more (`:372`, `:377`).
- The in-place updates of `subjects` and `collection_members` (`:1026-1027`, `:1052-1054`). Every other `update` body
  touches other tables.
- `_UNDONE` and the cut at a State's `seq` (`permissions.py:390-399`, `:456-469`).
- `required_layers` (`:1151-1181`), `_ledger_verdict` (`:1370-1387`), `_Run` (`:1520-1680`), `decide` (`:1683`) and
  `decide_bulk` (`:1703-1753`).
- The oracle's `layer_order` (`tests/permissions_oracle.py:472-481`), `object_refusal` (`:493-520`) and
  `bulk_refusal` (`:537-565`).
- `rebuild`'s `.fetchall()` (`permission_ledger.py:640`), the fold (`permission_uses.py:335-373`), and the daemon's
  path for a State that can't be built (`lighthouse_daemon.py:677-690`).
- A recall receipt's `use_subjects` rows (`lighthouse_daemon.py:493`), the protocol's `k > 0`
  (`lighthouse_protocol.py:234-236`), and the client's `MAX_CANDIDATES` (`lighthouse_client.py:17`, `:109`), which
  both readers use (`neighbors.py:90`, `context_lighthouse.py:159`).
- `server.py:2205`, `scripts/runtime.py:653-655`, `scripts/superyak-embedder.service:14` and `engram/CLAUDE.md:44-45`.
- The CLI's lines at `91a26a7`, the commit the task file dates them to. RCS9 lists where they are now.

I found no existing test that P36 would break. None of the 11 F1 files has a bulk or `imprint` case on an object with
a co-subject (I checked with a script over `tests/fixtures/permissions/f1/*.json`). The bulk tests that add co-subjects
expect `BOUND`, or `DENIED` at Andy's home (`tests/test_permissions_bulk.py:131-151`), and P36 keeps both.

### Must-fix

**RC1. The spec's account of the other two specs, and of step 1, is out of date.**
- The header's "Depended on by" bullet for revision 7 (lines 108-116) says the imprints spec's section 8 "leaves a
  carried co-subject's layer out of such a decision altogether", and that the two specs "differ only on a
  co-subject's deny, from step 2". Section 19, "The other two specs" (lines 2351-2361), says the same. It also says
  the trail spec "cites this section's finding of revision 7's first draft, that such a memory was refused even in
  the owner's home".
- None of that is true now. The imprints spec's section 8 reads each carried co-subject's layer as a restriction
  layer under P36, and says the reading that left it out "is gone" (its lines 1185-1224). The trail spec says that
  both specs now follow P36 (its section 7, lines 1055-1063; its section 14, lines 2165-2170).
- "So the two give the same verdicts in step 1" (lines 113-114 and 2355-2356) has one exception, which the imprints
  spec found itself (its lines 1342-1353). A road or trail whose memories carry 8 or more distinct co-subjects has 9
  or more subjects. This spec refuses the whole bulk use with `BOUND`, since P36 keeps 6.5's step 1 (line 677). The
  build does the same (`permissions.py:1630`). The station's finite check doesn't test the bound. The imprints spec's
  gate holds every such imprint until the specs are re-checked side by side (its section 18).
- "In step 1 only the ledger owner can write a layer (7.6), so a co-subject's layer is empty or missing" (6.3, lines
  696-697) is wrong, and so is "a co-subject's deny, which can exist only from step 2" (line 2357). Both fail for a
  place co-subject that the owner stewards:
  - 7.6 lets the CLI write "the layers of places the owner stewards" (lines 1103-1105);
  - a place can be a subject (6.3, item 1; the build's test `tests/test_permissions_decide_more.py:40-44`);
  - the imprints spec's `denied(m)` exists for exactly this case (its lines 400-405).
- 7.4 (lines 1082-1084) says what the imprints spec keeps at home, but leaves out a memory whose co-subject's layer
  on the owner's ledger denies a use the imprint needs (its `denied(m)`).

Fix: rewrite those passages to say what is true now:
- the three specs read a carried co-subject's layer the same way;
- in step 1 a person co-subject's layer is empty, but a place co-subject the owner stewards may hold a deny, and that
  deny refuses;
- the specs still differ on the bound of 8 subjects for roads and trails in a bulk use, which the side-by-side
  re-check settles.

This spec already gives its own answer to that question: step 1 is unchanged, and "Nothing else is waived" (6.4). So
unless Rio Grande rules otherwise, the station's check should apply the bound and refuse, as `decide` does. Lifting
the bound for counted bulk uses would be another widening, which needs its own ruling.

**RC2. An imprint doesn't carry the subjects a memory has through `copies`.**
- What this spec requires:
  - P25 (line 226), 6.3 item 1 (lines 641-645) and 7.4 (lines 1068-1076): on one ledger, a kept copy's subjects at a
    decision include its source's subjects, read through `copies`, up to 4 links;
  - 7.4 (lines 1078-1080): a copy held on another ledger has only the subjects carried when it was made.
- What the imprints spec and the build do:
  - The imprints spec's `cosubjects(m)` reads only "table `subjects`, rows with no `removed_seq`" (its lines
    366-369).
  - The build's `Ledger.cosubjects` does the same (`permission_ledger.py:574-578`).
  - Only `subjects_of` follows `copies` (`permissions.py:1100-1118`).
- **Failure.**
  1. Andy's instance store holds c1, a kept copy of m1 from another of his stores. It was made by genome sync
     (`federation.py:155`) or by `remember`.
  2. Later, Andy records Jenn as a co-subject of m1.
  3. On his ledger, c1's subjects are now {Andy, Jenn}. The build's own test shows this chain
     (`tests/test_permissions_decide_more.py:67-71`). But `cosubjects(c1)` is ∅.
  4. An imprint of the instance store ships c1 with no `imprint_subjects` row and counts it under `others` = 0. So the
     imprints spec's hold doesn't stop it, and the ceiling's item 6 doesn't keep its uses at home.
  5. With an audience other than the owner's home, c1 leaves with no record that it is about Jenn. That is a use about
     her without her yes, against principle 1.

  Revision 6 had the same gap, but revision 7 is where the three specs must agree on what an imprint carries.
- **Fix.** The main fix belongs to the imprints spec's reviser:
  - define `cosubjects(m)` as m's subjects at the plan by this spec's 6.3, item 1, read through `copies` too, less the
    owner. That is `subjects_of` at the plan's `seq` and time, not `Ledger.cosubjects`;
  - read `denied(m)` over the same set;
  - apply the bound of 8 subjects to the whole set.

  In this spec, 7.4's "A copy held on another ledger" should say that a copy carries exactly that set, as of when it is
  made.

**RC3. SH-13's records bound misses `sign`, and two writers at once.** Spec 5.4 (lines 509-512) says a write over the
bound is refused. 5.6 (lines 586-587) says a ledger past it is one "which no write of this spec makes". SH-13 counts
"in `perform` ... before `_append`". Two paths get past that count:
- **`sign`.** `perform` hands `sign` and `decline` to `_on_proposal` before anything else
  (`permission_ledger.py:335-336`). A signed proposal then writes its record through `_append`, at `:444`, or at
  `:464` in `_sign_alone`. So signing an agent's proposal for an allow, a shortening or a narrowing at 16,384 records
  writes the 16,385th.
- **Two writers.** The count runs outside `_append`'s `BEGIN IMMEDIATE` (`:265`). So the CLI and an engram server
  writing at the same moment can both pass at 16,383.

Either way, SH-1's `state()` then refuses the ledger, as the spec says it must. The daemon serves nothing. Every later
act fails too, because `perform` builds a State first (`:340`), so the owner can't even revoke from the CLI until
SH-10 lands.

Fix: count inside `_append`'s transaction, for every body that inserts `records` rows. That covers `perform`, both
proposal paths and `migrate`. `rebuild` replays through `_append` too (`:641`), and a ledger this spec wrote never
meets the bound there. Add a case to `test_the_records_bound_refuses_a_write`: a `sign` of an agent's proposal for an
allow, refused at the bound.

**RC4. P36's test of who qualifies is wider, in two places, than 6.3 means.**
- **(a) The uses `need` adds, on another person's memory.**
  - 6.3 fixes "the owner" as the owner of o's store (lines 662-663). Then it says: "Every use in its `need` (6.4) is
    decided the same way ... the owner's home layer stays a consent layer. Each other subject's layer is read as a
    restriction layer" (lines 672-674). SH-12 turns this into "the uses `need` adds take their parent's answer".
  - A road or trail can name a memory in another store, since an edge across a store boundary is a road (6.4, line
    742).
  - **Failure.** Say Andy's trail names mj, a memory in Jenn's store with Lee recorded on it. In Andy's bulk `route`
    at home, the `recall` on mj takes the trail's answer. Andy is not a subject of mj. So Jenn's own layer (she is
    mj's default subject) and Lee's are both read as restriction layers, and mj is recalled with neither person's
    yes. A6 is Andy's answer about his own store. It says nothing about Jenn's memories.
  - **Fix.** In 6.3, say that a use in `need(u)` qualifies only when the requester acts for the owner of its own
    object's store. It keeps the parent's P and H. A named memory from another owner's store is decided with consent
    layers, as before. SH-12 and the oracle follow. U29 gains a trail of Andy's store that names a memory of Jenn's
    store: its bulk `route` at home is refused at Jenn's home, with `NO_ALLOW`, or `NO_LAYER` if she isn't
    registered. The imprints spec is not touched, since every memory that a road or trail of R(I) names is the
    owner's (its lines 1296-1298).
- **(b) A single `imprint`'s kept copy.**
  - 6.3 requires that "the copy it keeps is held inside the owner's home" (line 665).
  - In step 1 the only single `imprint` is the `remember` guard (section 10). Its use names the copy the delivery came
    from, not the store it keeps into (`server.py:2106`, `copy=d.copy`).
  - SH-12's `qualifies` tests "an `imprint` whose copy is held inside the owner's home" on `use.copy`. So a
    `remember` into a store registered at a place outside the home would qualify on the house's place, and keep a
    copy outside the home on a co-subject's silence. This needs Jenn to have allowed delivery to Andy's agent first,
    so it is narrow, but it is a widening.
  - **Fix**, Rio Grande's call which:
    - SH-12 says where the kept store's place comes from (the guard's own instance's `stores` row), and `qualifies`
      tests it; or
    - 6.1 says that for an `imprint`, h is the copy it keeps, and the guard follows.

    Either way, add a U29 case for it.

### Should-fix

- **RCS1. Name the `kind` that `cited` shows for a co-subject's layer under P36** (6.3, 6.5 step 5, 9.1).
  - F1 compares `cited` with its `kind` (`tests/test_permissions_f1.py:58`). For example, the restriction entries
    in `imprint_evaluation.json` carry a kind, a verdict, empty records and a version.
  - SH-12 adds "a new layer kind" with no name, while 6.3's words ("read as a restriction layer") point to
    `restriction`.
  - Reusing `restriction` has a cost. The steward view shows any layer of that kind as the word `restriction`
    (`permission_uses.py:616-617`), but 9.2 says a home's layer, cited or refusing, shows as that person's pseudonym.
  - Name the kind in the spec (Rio Grande's call), with its verdicts and its version, before SH-12's F1 fixture is
    written by hand.
- **RCS2. SH-12's oracle exception is too narrow, and its file list misses code that tests a layer's kind.**
  - **The oracle.** `bulk_refusal` (`tests/permissions_oracle.py:537-565`) calls `object_refusal` with the bulk's
    first use only (`:561`), so nothing tells `object_refusal` that the use is bulk. P36's "or any bulk use" can't be
    decided inside the two named functions. Name `bulk_refusal` in the exception too: it needs one more argument at
    `:561`.
  - **`permissions.py`.** These all test `layer.kind in ("consent", "restriction")`:
    - `_Run._row` (`:1594`, `passes`);
    - `_Run._register` (`:1617`). Only those kinds enter `ledger_layers`, which `_until` and `_horizon` read
      (`:1666-1667`);
    - `_Run.process` (`:1650`);
    - `layer_verdict` (`:1392`), which raises for any other kind.

    `_Run._merge` (`:1609`) also picks the refusal code. A new kind left out of `_register` would drop its dated
    denies from `until` and its records from the horizon, which 6.3 keeps. U29's dated-deny case would catch that,
    but naming these functions saves a round.
  - **The generators.** `random_world` already reaches qualifying uses. In a read-only count over 200 seeded worlds
    (`tests/permissions_support.py:878`, `:1121`), 109 of 2,900 sampled uses qualified, and 31 of those had a
    co-subject. So SH-12 needs no change to `permissions_support.py`. It should say so, since the plan forbids editing
    that file (plan line 95).
- **RCS3. U29's "condition false" cases need Andy's layer to allow them.** U29 has Andy's layer allow `recall`,
  `read`, `imprint` and `route` "for his own agents". With only that allow, three of its cases are refused at Andy's
  home, not Jenn's:
  - With P outside his home, his inside-home allow can't match (5.4, lines 488-491), so the refusal is `NO_ALLOW` at
    `place:home/andy`.
  - An agent acting for someone else is refused there too.
  - An `inject_context` of m3 fails at Andy's layer first, because the order takes each layer before the next
    (6.5 step 2; `_Run.process`, `permissions.py:1649-1654`).

  Each test would pass for the wrong reason. Fix: give Andy's layer allows that match those uses (an outside-home allow
  naming m3 for the outside place, one for the other agent, and `inject_context`), so each refusal falls at
  `place:home/jenn`.
- **RCS4. A layer that is both a co-subject's and a place's.** 6.3 doesn't say what happens when a place co-subject
  is also in anc(P) or anc(H), for example a sub-place of the owner's home. Item 2 or 3 needs it as a consent layer.
  P36 reads it as a restriction layer. "A layer that appears twice counts once" (line 656) doesn't say which reading
  wins. Say that it stays a consent layer. In the build, a new kind would share `required_layers`' key with consent
  (`permissions.py:1162`), and the subject reading would win, because it is added first (`:1167-1168`).
- **RCS5.** The vocabulary row "Subject" (line 178) still says "Each subject's consent layer must allow every use".
  Add "except as P36 reads it (6.3)".
- **RCS6.** SH-13 drops only `perform`'s State. `_on_proposal` and `_sign_alone` keep theirs through `_outcome`
  (`permission_ledger.py:405`, `:445`, `:465`), but 5.6 (lines 588-591) says an act drops its own State. At the bounds
  that costs one more State: 213.4 + 95.9 = 309.3 MB, still under 512. Fix it with RC3, and have
  `test_perform_holds_one_state` cover `sign`.
- **RCS7.** SH-1 adds `STATE_RECORDS` and SH-13 adds `MAX_RECORDS`, "shared ... one constant is enough". But their
  tests patch different names. Pick one name.
- **RCS8.** SH-9 counts "each new set's size" per State, and `_outcome` runs up to 64 joint checks with one State
  (`permission_ledger.py:377-380`; `JOINTS_PER_CHANGE`, `permissions.py:41`). So sets freed after one check still
  count against later ones, which could then report "could not check". That fails toward a disagreement report,
  never toward an allow. Say whether the bound counts the sets held (the memoized `layer_boxes`, `permissions.py:2231`,
  plus the current check's) or every set made.
- **RCS9. Small corrections.**
  - Since `91a26a7`, the CLI's lines have moved. `COLLECT_CHUNK` is now at `permission_cli.py:755`; spec 5.4 and 15
    cite `:754`. `_collection` is at `:456`, and the CLI's `state()` callers are at `:265`, `:284`, `:302`, `:600`,
    `:672`, `:706`, `:1149` and `:1210`.
  - Row 8 of the task file's survey: 200,000 × 338 B = 64.5 MB, not 64.4.
  - The F1 file names are snake_case (`imprint_evaluation.json`). SH-12's `p36-carried-co-subject.json` would still
    run, since the runner globs `*.json` (`tests/test_permissions_f1.py:15`), but it breaks the pattern.
- **RCS10.** At the records bound the owner can still revoke, but a new deny is refused too, because a deny writes a
  record. 5.4 says only "so a person can always revoke", which is true. Say that a deny waits for SH-10 as well.

### What holds

- Andy's two decisions are carried word for word (A6 and A7, lines 200-201; the vision's lines 37-38 and 141-143).
  Every choice beyond the quotes is marked as Rio Grande's call.
- P36 keeps every deny, keeps 6.5's step 1, and never covers a use that shows content to an agent or that happens
  outside the home. All three specs say so.
- The memory budget is the same in all three specs, and every figure in section 15 checks.
- Every `## ` and `### ` heading of `e084597` is still in the spec, in order, and the spec ends with a newline.

## Re-check response (the reviser, 2026-10-26)

Applied to the spec (revision 7, still uncommitted on `trail-arrows-spec`) and to the controller's task file
(`permissions-core/.superpowers/sdd/2026-10-25-permissions-by-place/small-hardware-tasks.md`, git-excluded). Nothing
is committed, pushed or posted. This pass could edit only those two files, so the imprints spec is not touched, and
RC2's main fix is left for its reviser (below). Code claims were re-read at `permissions-core` HEAD `dc0881e`. Every
`## ` and `### ` heading of `c795c59` is still in the spec, in order. The task file keeps every heading it had. The
spec has no `### Task` headings, and the task file's are `### SH-`. Both files end with a newline. Choices that aren't
Andy's are marked "Rio Grande's call" in the spec.

**RC1 (the account of the other two specs). Done.**
- The header's revision 7 bullet under "Depended on by" now says:
  - both other specs read a carried co-subject's layer as P36 does (imprints section 8; trail section 7);
  - they still differ on the bound of 8 subjects;
  - a copy carries subjects through `copies`, which the imprints spec's `cosubjects(m)` doesn't do yet.
- Section 19, "The other two specs", is rewritten with three points:
  - **Denies in step 1.** A place co-subject that the owner stewards can hold his deny (7.6). `denied(m)` keeps such a
    memory home.
  - **The bound of 8.** This spec and the build (`permissions.py:1630`) refuse with `BOUND`, and the station's check
    doesn't test it. This spec's answer for the side-by-side re-check, unless Rio Grande rules otherwise: the
    station's check takes the bound and refuses. Lifting it for counted bulk uses would be a second widening.
  - **What an imprint carries** (RC2).
- 6.3's "Why this form" now says a person co-subject's layer is empty in step 1, and that a place co-subject the owner
  stewards may hold a deny, which refuses. "Can exist only from step 2" is gone.
- 7.4 now names the imprints spec's `denied(m)` case.

**RC2 (what an imprint carries). Done here. The main fix is the imprints spec's.**
- I checked the gap. The imprints spec's `cosubjects(m)` (its lines 366-369) and the build's `Ledger.cosubjects`
  (`permission_ledger.py:574-577`) read `subjects` rows only. `subjects_of` (`permissions.py:1100-1118`) follows
  `copies`.
- 7.4, "A copy held on another ledger", now says a copy carries exactly its source's subjects at that moment, as 6.3,
  item 1 reads them (through `copies` too), less its own default subject. An imprint's `imprint_subjects` rows are
  that set less the owner, at the plan.
- 7.4, "Kept copies", says the same for a copy on one ledger. The build already does this (`subjects_of` at
  `permission_ledger.py:511`, in `record_copy`).
- Section 19 says what the imprints spec's reviser should change:
  - `cosubjects(m)` is `subjects_of` at the plan's `seq` and time, less the owner;
  - `denied(m)` and the bound of 8 read the same set.

**RC3 (the records bound and `sign`). Done, in SH-13 and 5.4.**
- The count moves into `_append` (`permission_ledger.py:261-282`). It runs inside its `BEGIN IMMEDIATE` (`:265`),
  before `_project`, for any body that inserts `records` rows. A refusal there is rolled back by the `except` that is
  already there (`:276-278`).
- So the count covers `perform`, both proposal paths (`:444` and `:464`, reached through `:335-336`), `migrate`, and
  two writers at once. `rebuild` replays through `_append` (`:641`), so it refuses a log past the bound, which no
  write of this code makes.
- Tests:
  - `test_the_records_bound_refuses_a_write` gains a `sign` at the bound;
  - a new `test_two_writers_meet_the_records_bound_once`: two `Ledger` objects in two threads, with a barrier before
    `_append`.
- 5.4 says the count runs inside the write's own transaction.

**RC4 (who qualifies). Done.**
- **(a) Uses that `need` adds.** 6.3 now tests each use in `need(u)` on its own object. Such a use qualifies when its
  parent does, and when the requester acts for the owner of that object's store, whose home dominates P and H.
  - So a memory of Jenn's store on Andy's trail is decided with consent layers.
  - P36's row in section 3, and section 19, now say "on the owner's own memories".
  - SH-12's `qualifies` and the oracle follow.
  - U29 gains the mj case: refused, `NO_ALLOW` at `place:home/jenn`, or `NO_LAYER` with Jenn unregistered.
- **(b) The `remember` guard's kept store.** Rio Grande's call, the first of the two options: the guard passes the
  store it keeps into, and `qualifies` tests that store's place.
  - 6.1 names that store k. No layer reads it.
  - 6.3 says that for a single `imprint` the kept copy is k. A store with no `stores` row never qualifies.
  - Section 10 says the guard passes k, and 6.5 says the result depends on k for a single `imprint`.
  - SH-12 adds `Use.keeps` (`permissions.py:797-808`) and has `server.py:2106` pass `store:<_store_id()>`
    (`:2212-2216`).
  - U29 gains the guard case: a kept store outside the home, at home, and with no `stores` row.

  Why not the other option (that h for an imprint is the copy it keeps): it would change H. Item 3 of `Req` would then
  need the kept store's place chain instead of the delivery's, which changes every guard decision, not only P36's
  test, and could drop a refusing holding place.

**RCS1 (the kind `cited` shows). Done.** Rio Grande's call: the kind is `co-subject` (6.3, "How `cited` shows it").
- Its verdict is `deny`, `missing` or `silent`. Its allows aren't read, and only `deny` fails.
- Its records are empty. Its version is the layer's version, 0 when the layer doesn't exist.
- 6.5 step 5, U29, F1 and SH-12 name it.

**Beyond the re-check:** reusing `restriction` would also break three things in the build.
- `_ledger_verdict` looks a `restriction` layer up among agents (`permissions.py:1372`), so a home would read as
  `missing`.
- `meet_legacy` puts the legacy layers before the first `restriction` entry (`:1837`).
- `meet_legacy` also ranks a refusal at a `restriction` layer after a legacy one (`:1848`).

With a new name, none of these, nor `annotation` (`:3149`) or the steward view, needs a change. The steward view's
kind test is at `permission_uses.py:618-619` (the re-check cited `:616-617`).

**RCS2 (SH-12's file list). Done.**
- The oracle exception now also names `bulk_refusal` (`tests/permissions_oracle.py:537-565`). Its call at `:561`
  gains the bulk flag.
- The file list now names:
  - `_Run._row` (`:1594`), `_Run._merge` (`:1609`) and `_Run._register` (`:1617`, with `_until` and `_horizon` at
    `:1666-1667`);
  - `_Run.process` (`:1650`), `layer_verdict` (`:1392`) and `_ledger_verdict` (`:1370-1378`);
  - `Use` (`:797-808`).
- SH-12 says `permissions_support.py` is not edited. It cites the re-check's count of 109 of 2,900, which I didn't
  re-run.

**RCS3 (U29's allows). Done.**
- Andy's layer also allows `inject_context` inside his home.
- It also holds outside-home allows: `commons` narrowed by `requesters` to his agent at an outside place Q and to Lee's
  agent b, with named purposes and an end date. One names m3 for `recall`, `read`, `inject_context` and `imprint`. One
  names his store for `route`.
- Each case with one condition false first asserts that his layer allows the use.

**RCS4 (a layer that is both). Done.**
- 6.3: a place co-subject that is also in anc(P) or anc(H) keeps its consent layer.
- SH-12: collect the place chains' ids first. Otherwise `required_layers`' key (`:1162`) lets the subject reading win,
  since the subjects are added first (`:1167-1168`).
- U29 has a case for it.

**RCS5 (the vocabulary row). Done.** "Subject" now ends "except as P36 reads it (6.3)".

**RCS6 (the States a signed proposal holds). Done**, in SH-13 and 5.6.
- `_sign_alone` returns what `_outcome` needs. `_on_proposal` drops its State and then calls `_outcome`.
- `test_perform_holds_one_state` now signs a proposal too.
- Without this, the bounds hold one more State: 213.4 + 95.9 = 309.3 MB.

**RCS7 (one name). Done.**
- The one name is `MAX_RECORDS`. SH-1 adds it, and SH-13 and SH-10 use it.
- `permission_ledger.py` reads it as `permissions.MAX_RECORDS` when it counts, so one `monkeypatch` reaches both
  tasks' code.

**RCS8 (what the box refs count). Done.** The bound counts the sets held, as two counts:
- `kept`: the sets the `layer_boxes` memo keeps (`permissions.py:2231`), counted once, when computed;
- `check`: every other set the box code makes, reset at each `_analyse`.

Section 8 and section 15's row say so. The bound is still 2,000,000 × 4.0 MB / 100,000 = 80.0 MB. SH-9 gains
`test_later_checks_dont_pay_for_freed_sets`. Its threshold is read from the first check, so it doesn't depend on how
many sets a check makes.

**RCS9 (small corrections). Done.**
- `COLLECT_CHUNK` is cited at `permission_cli.py:755` (5.4, 15, SH-13 and the Task 28 note).
- `_collection` is cited at `:456-485`.
- Row 2 gives the CLI's `state()` callers at `dc0881e`: `:265`, `:284`, `:302`, `:600`, `:672`, `:706`, `:1149` and
  `:1210`. The `91a26a7` lines are kept beside them.
- Row 8: 200,000 × 338 B = 67,600,000 B = 64.47 MB, so 64.5.
- SH-10's figure, 64.5, is unchanged: 16,384 × 4,126 B = 67,600,384 B = 64.47 MB.
- The F1 fixture is now `p36_carried_co_subject.json`.

**RCS10 (denies at the bound). Done.** 5.4: a new deny, a shortening and a narrowing each write a record, so they are
refused at the bound too. At the bound a person narrows by revoking.

**Not applied:** nothing. I found no item wrong.

**For the other specs' revisers** (not edited here):
- The imprints spec: RC2's `cosubjects(m)`, with `denied(m)` and the bound of 8 over the same set (its section 5.2).
  The bound of 8 for roads and trails in its finite check is settled at the side-by-side re-check (its section 18).
  While I worked, that spec and its plan showed uncommitted edits in this worktree that I didn't make. Its 5.2 there
  already defines `cosubjects(m)` up the `copies` chain. So this spec cites the imprints spec as committed in
  `c795c59`, and says what its revision must do. It doesn't say what that revision does. The side-by-side re-check
  reads both.
- The trail spec: nothing. It reads no co-subject row.

## Final check (2026-10-26, a fresh reviewer)

**Reviewer:** a third fresh reviewer acting in Andy's place (station law section 3). I took no part in writing,
checking, re-checking or fixing this amendment.
**What I read:**
- the spec as it stands in the worktree (`git diff HEAD`, uncommitted on `trail-arrows-spec`, HEAD `c795c59`);
- this file's re-check and its response;
- the vision (principle 4 and "Open for Andy");
- the imprints spec as it stands in the worktree. Its reviser has revised it after its own re-check (uncommitted;
  `2026-10-25-small-hardware-imprints-review.md`, "Re-check response");
- the trail spec as it stands in the worktree. Its reviser revised it after its own re-check while I worked
  (uncommitted; `2026-10-25-small-hardware-trails-review.md`, "Re-check response"). I read that diff too;
- the task file's SH-12 and SH-13;
- the build on `permissions-core` at `dc0881e`, for every code claim below.

I edited nothing but this section. I ran one read-only count with the build's `.venv` (`-I -B`). It was a scratch
script that imports the build and writes nothing.

**Verdict: approve.** RC1 to RC4 are resolved. The fixes add no must-fix. The three specs still agree on how P36
reads a co-subject's layer, on what an imprint carries, and on the memory budget. Six should-fix items and three nits
follow. None changes a verdict, and each fits in SH-12, SH-13 or the next revision of a spec.

### The re-check's must-fix items

**RC1 (the account of the other two specs). Resolved.**
- **The header** (lines 110-120) says both other specs now read a carried co-subject's layer as P36 does. It says the
  specs still differ on the bound of 8 subjects for a road or trail in a bulk use, which this spec refuses with
  `BOUND`. It also says a copy carries its source's subjects through `copies`.
- **Section 19, "The other two specs"** (lines 2409-2439), says the same. It gives the three open points: denies in
  step 1, the bound of 8, and what an imprint carries. "Leaves ... out altogether", "differ only" and "can exist only
  from step 2" are gone (I grepped for each).
- **6.3, "Why this form"** (lines 720-727), now separates the two cases. A person co-subject's layer is empty in
  step 1. A place co-subject the owner stewards may hold a deny, which refuses.
- **7.4** (lines 1111-1123) names the imprints spec's `denied(m)` case.
- **Checked against the other specs:**
  - The imprints spec's section 8 reads each carried co-subject's layer as a restriction layer (its lines 1252-1279).
    It names the bound of 8 on roads and trails as a question for the side-by-side re-check (its lines 1416-1428).
  - The trail spec says both specs follow P36 (its lines 1071-1081 and 2210-2219). Its revision in the worktree
    now says "his bulk uses", which fits RC4 (a).

**RC2 (what an imprint carries). Resolved in both specs.**
- **This spec.** 7.4's "Kept copies" (lines 1093-1099) and "A copy held on another ledger" (lines 1111-1123) say a
  copy carries its source's subjects as 6.3, item 1 reads them: through `copies` too, less its own default subject. An
  imprint's `imprint_subjects` rows are that set less the owner, at the plan. The build already carries the set this
  way when it records a copy (`subjects_of` at `permission_ledger.py:511`).
- **The imprints spec** (its 5.2, lines 380-392) now defines `cosubjects(m)` as the permissions spec's subjects of m
  at the plan, less the owner. It reads them from the memory's own rows and from each source up the `copies` chain, at
  most 4 links, with the source store's owner unless that store is an imprint.
- **That matches the build's `subjects_of`.** `subjects_of` (`permissions.py:1100-1118`) walks `MAX_COPY_CHAIN + 1`
  = 5 refs: the memory and 4 sources. `_own_subjects` (`:1083-1097`) adds a store's owner only when the store is no
  imprint (`:1092`).
- **`denied(m)` reads the same set.** Its pre-query now asks about every layer but the owner's home, not only the
  source's own co-subjects (its lines 448-456).
- **The bound of 8 is on the whole set.** `bound(m)` keeps home a memory with more than 8 subjects (its lines
  423-430).
- **The failure case is tested.** The re-check's case, a co-subject recorded on a copy's source after the copy was
  made, is now its test "Co-subjects through copies" (its line 2496).

**RC3 (the records bound and `sign`). Resolved, in SH-13 and 5.4.**
- **Where the count runs.** SH-13 now counts inside `_append`, inside its `BEGIN IMMEDIATE`
  (`permission_ledger.py:265`) and before `_project`. It counts for any body that inserts `records` rows. Its
  `except` already rolls back (`:276-278`).
- **Every record goes through it.** Every record write in the build is a body insert that goes through `_append`:
  - an act (`:1192`);
  - a replacement (`:1260`);
  - a signed proposal (`:444`, or `:464` in `_sign_alone`, both reached from `:335-336`).

  A revocation only updates (`:1212`), so it is never counted, and filing a proposal inserts only a `proposals` row
  (`:396`).
- **Two writers can't both pass.** `BEGIN IMMEDIATE` holds the write lock, and the connection's busy timeout
  (`:151-153`) makes the second writer wait and then count 50 + 1 > 50 at the test's bound.
- **Tests.** `test_the_records_bound_refuses_a_write` gains the `sign` case, and
  `test_two_writers_meet_the_records_bound_once` is new.
- **5.4** (lines 516-521) says the count runs inside the write's own `BEGIN IMMEDIATE`. 5.5 says every write is one
  (line 529).

**RC4 (who qualifies). Resolved.**
- **(a) The uses `need` adds.**
  - 6.3 (lines 687-692) now tests each use in `need(u)` on its own object. It qualifies only when its parent does and
    the requester acts for the owner of that object's store, whose home dominates P and H. A6 is read as Andy's
    answer about his own store, marked Rio Grande's call.
  - P36's row (line 241) and section 19 say "on the owner's own memories". SH-12's `qualifies` and the oracle's
    `object_refusal` follow.
  - U29 has the mj case (lines 2329-2332). Its expected refusal is right. mj's subjects sort as `person:jenn` before
    `person:lee`, and subjects come first in step 2's order, so the first failing layer is `place:home/jenn`.
  - **No imprint case changes.** An imprint keeps its source's refs (7.4, line 1125), and every memory a road or trail
    of R(I) names is in objects(I) (imprints spec line 1411), so each such use has the owner's store.
- **(b) The `remember` guard's kept store.** Rio Grande chose the first option.
  - 6.1 (lines 616-618) names k, the store a single `imprint` keeps into. No layer reads it.
  - 6.3 (lines 678-681) tests k's `stores` row. A store with no row never qualifies.
  - Section 10 (lines 1435-1436) and 6.5 (line 907) follow.
  - SH-12 adds `Use.keeps`, and `server.py:2106` passes `store:<_store_id()>` (`:2212-2216`). That is the store
    the kept copy is recorded in (`server.py:2012`, `mem:{sid}/episode/...`), so k names the right store.
  - The reason given for not changing H holds: item 3 of `Req` reads `holding_place(use.copy)`
    (`permissions.py:1171-1176`), and changing h would move every guard decision.
  - U29's three guard cases are in the spec (lines 2333-2335) and in SH-12.

### Do the fixes break an agreement?

No. I checked each point where the specs meet:
- **How P36 reads a layer.** The permissions spec (6.3), the imprints spec (section 8) and the trail spec (section 7)
  all read a carried co-subject's layer as a restriction layer: silence and a missing layer pass, and a deny refuses.
  None of them covers a use that shows content to an agent, or a use outside the owner's home.
- **What stays home.** The imprints spec now also keeps home a memory with a retired person co-subject
  (`retired(m)`), or one with more than 8 subjects (`bound(m)`). Both follow this spec:
  - Step 1 of 6.5 refuses on the home of a retired subject (line 847), and the build tests persons only
    (`_subject_retired`, `permissions.py:1418-1420`). So a retired place co-subject keeps nothing home, as that spec
    says.
  - 7.4 applies the bound of 8 to the union through `copies`.
- **The bound of 8 on roads and trails.** It is still open in both specs, and both say so. It is gated, since no
  imprint with a carried co-subject is approved before the side-by-side re-check (imprints section 18).
- **Existing tests.** The fixes break none. The guard tests that add a co-subject decide uses by
  `agent:ph-coordinator` at clinic-3 (`tests/permissions_support.py:2531-2535`), or a use with no co-subject
  (`tests/test_permissions_keep.py:99-105`). P36 never covers either.
- **The memory figures.** The fixes change none. I redid the ones they cite:
  - 16,384 × 11,129 B = 182,337,536 B = 173.9 MB, and 297.7 + 173.9 = 471.6 MB;
  - the States a signed proposal would hold: 213.4 + 95.9 = 309.3 MB;
  - 16,384 × 4,126 B = 67,600,384 B = 64.47 MB, and 200,000 × 338 B = 67,600,000 B = 64.47 MB;
  - the box refs bound, 2,000,000 × 4.0 MB / 100,000 = 80.0 MB.
- **The imprints figures that rest on this spec** also check:
  - a State at the bounds, 45.0 + 64.5 + 25.3 + 6.1 = 140.9 MB;
  - the plan, 96 + 9.8 + 16 + 18.2 + 5.4 = 145.4 MB, and 145.4 + 140.9 = 286.3 MB, under its 384;
  - `import-receipts`, 512 × 8 = 4,096 pairs × 492 B = 2,015,232 B = 1.9 MB, so 96 + 3.9 + 1.9 = 101.8 MB.

### Should-fix

- **FS1. U29's mj case with Jenn unregistered tests a state no act can write.**
  - A store's owner must be a registered, unretired person (`_live_person`, `permission_ledger.py:708-713`, called
    for `register-store` at `:913`). So "a memory of Jenn's store" with Jenn unregistered exists only as a fixture
    row, which `World.store` writes unchecked (`tests/permissions_support.py:134-136`).
  - The empty-layer case is the real one. Either drop the `NO_LAYER` variant from U29 and SH-12, or say it is a
    written-row fixture.
- **FS2. The property tests reach P36's bulk branch, but never its single `imprint` branch.**
  - `sample_uses` builds each `Use` with no `keeps` (`tests/permissions_support.py:1135-1137`). `use_json`, which the
    oracle reads, carries none either (`:706-709`). That file may not be edited (plan line 95).
  - My count, over 200 seeded `random_world`s with 15 sampled uses each: 2,543 single uses, and 1,909 per-object
    uses inside bulk uses.
    - Under the rule before RC4 (b), 36 single `imprint`s and 86 per-object bulk uses qualified (8 and 18 of them
      with a co-subject).
    - Under the rule now, 0 single uses and the same 86 qualify, 18 of them with a co-subject.
  - So SH-12's "the property tests' 500 seeded cases then cover P36" holds for bulk uses only. U29's guard cases are
    the only test of k. SH-12 should say so, and have the oracle read a missing `keeps` as `""`, which never
    qualifies.
- **FS3. A receipt and `explain` don't name k.**
  - 6.5 (line 907) says a single `imprint`'s result depends on k. But 9.1's `uses` table records `copy` (h) and no k
    (lines 1279-1283), and `explain` decides "a described use" (line 1855) with no way to give k.
  - So the receipt of a `remember` allowed under P36 doesn't show what allowed it.
  - Say what a guard receipt means by k, for example the store of the instance that wrote it, and let `explain` take
    k. Rio Grande's call.
- **FS4. This spec's account of the imprints spec now trails that spec's own revision.**
  - 7.4 (lines 1119-1123) and 19 (lines 2428-2436) cite the imprints spec as committed in `c795c59`, and say what its
    revision must do. Its revision in the worktree does it (its lines 380-392). It also adds `retired(m)` and
    `bound(m)` to what stays home.
  - When the two are committed together, 7.4's list of what that spec keeps home should add those two, and 19 should
    say the fix is made. The rules already agree (above).
- **FS5. Place co-subjects in step 1.**
  - The spec lets a place be a subject (line 182; 6.3, item 1). RC1's fix says a place co-subject the owner stewards
    can hold a deny in step 1 (lines 722-726 and 2416-2419).
  - The build can't record one by any act. `add-subject` takes a person id only (`permission_ledger.py:1033`), and
    the CLI makes its argument a person (`permission_cli.py:491`). Place subjects exist only in fixtures
    (`tests/test_permissions_decide_more.py:40-44`, through `World.subject`).
  - The text errs on the safe side, and the imprints spec's `denied(m)` query covers the case either way. Say which is
    meant: that the step-1 build records person co-subjects only, or a task to accept places. Rio Grande's call.
- **FS6. The engram server across two specs.**
  - Section 15 (lines 2075-2079) puts the server at about 503 MB at the bounds with this spec's `perform`
    (320 + 183.1 = 503.1).
  - The trail spec's new "One server, two specs" (its lines 1767-1777) adds its own held tool graph to the same
    server:
    - 305.2 + 73.2 + 183.1 = 561.5 MiB, and 305.2 + 80.5 + 183.1 = 568.8 during a pass;
    - with 320 read as MiB, 320 + 73.2 + 183.1 = 576.3 and 320 + 80.5 + 183.1 = 583.6.
  - All four are over 512. Neither spec breaks a rule: P37 binds only the processes this work adds, and the server
    isn't one. But 503 MB is this spec's share, not the server's peak.
  - Say so in 15, citing the trail spec. One figure for the server across the specs is Rio Grande's to set, if he
    wants one.

### Nits

- **N1.** SH-13's two-writer test must open each `Ledger` inside its own thread. Its connection uses
  `sqlite3.connect`'s default `check_same_thread` (`permission_ledger.py:151`).
- **N2.** SH-13's `sign` case reaches `_sign_alone`'s write (`:464`). The last signature of a joint proposal writes at
  `:444`, through the same `_append`. It is covered by construction, and one more case would pin it.
- **N3.** The imprints spec cites `subjects_of` at `permissions.py:1100-1117`. It ends at `:1118`.

### What holds

- **The code claims.** Every code claim in the re-check response checks at `dc0881e`:
  - `_append` and its rollback (`permission_ledger.py:261-282`, `:276-278`);
  - `perform`'s hand-off to `_on_proposal` (`:335-336`), its State (`:340`), and `_outcome`'s two States (`:372`,
    `:377`);
  - `_on_proposal`'s State (`:405`) and its write and `_outcome` (`:444-445`), and `_sign_alone`'s (`:464-465`);
  - `Ledger.cosubjects` (`:574-577`), `record_copy` (`:488-519`, `subjects_of` at `:511`), and `rebuild`'s replay
    (`:641`);
  - `Use` (`permissions.py:797-808`) and `holding_place` (`:1134-1141`);
  - `_ledger_verdict`'s lookup among agents (`:1372`) and its deny (`:1376-1377`), and `layer_verdict`'s raise
    (`:1392`);
  - `meet_legacy` (`:1837`, `:1848`), `annotation` (`:3149`) and the steward view (`permission_uses.py:618-619`);
  - `COLLECT_CHUNK` (`permission_cli.py:755`), `server.py:2106` and `_store_id` (`:2212-2216`).
- **The files are whole.** Every `## ` and `### ` heading of `c795c59` is still in the spec, in the imprints spec
  and in this file, in order. The spec has no `### Task` headings. All three end with a newline.
- **The decisions are carried.** Andy's two decisions are carried word for word (A6 and A7). Every choice beyond the
  quotes, the new ones included (k, `co-subject`, the per-object test), is marked Rio Grande's call.
