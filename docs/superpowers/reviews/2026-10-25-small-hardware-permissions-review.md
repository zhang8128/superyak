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
