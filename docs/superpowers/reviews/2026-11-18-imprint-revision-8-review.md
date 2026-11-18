# Fresh review: imprint spec revision 8 (601d7102, branch tardis/imprint-filter-one-state)

Reviewer: a fresh agent on Tardis, 2026-11-18. I took no part in writing it. I only read files and ran probes: I edited,
committed and posted nothing, and I did not read `~/.engram/imprints/`.

## Verdict: APPROVE WITH CHANGES

The core change is right. On a stamped ledger, one `Ledger.state()` closes the class revision 7 left open, as of the
moment the State is built. Every fact the plan uses is either loaded whole by a table scan that the projection digest
covers, or read through an index that SQLite's integrity check holds against its table. The measurements reproduce.
The revision widens no permission and lets nothing more leave.

One thing blocks building it. The plan's Task 8a cannot pass on the Pi as written, because the cap fixture's ledger
fails the very check the revision now always runs (finding 1). The Should-fixes bound the claim honestly (2, 3) and
make the interface and tests match what was measured and what main actually does (4 to 7).

## Answers to the six questions

1. **Does one `state()` close the class?** Yes on a stamped ledger, at the check, with three gaps.
   - How it works: `state()` reads the key, loads every table except the per-object four by `ORDER BY rowid` scans, and
     reads meta `NOT INDEXED`, all in one read transaction (`permission_ledger.py:1332-1371`). It then trusts the memo or
     marker for that key, or runs `_full_check`: every part `NOT INDEXED`, then `PRAGMA integrity_check`
     (`permission_ledger.py:650-728`, `:1216-1234`).
   - After that, `RowMap` reads go through the very same indexes revision 7 used (`subjects_object`,
     `lane_notes_object`, `sqlite_autoindex_copies_1`; EXPLAIN QUERY PLAN below). They run on `_late` connections that
     are checked once, when they open (`:1236-1268`), and never again.
   - Gap one: a file overwritten in place during the plan's run is read unchecked (finding 2).
   - Gap two: an unstamped ledger is read with no check at all (finding 3).
   - Gap three: the marker path trusts D4's key. That is inherited, and the prose says so.
2. **Is the 851 MiB real, and is the lazy `_with_agent` sound?**
   - The 851 MiB is real: I reproduced 851 MiB and 17.25 s. The `{**state.seq_at, 0: 0}` reads all 811,000 log times,
     and `to_tables()` holds 700,000 subject rows and 300,000 lane notes.
   - The lazy version is sound, with one caveat. `State.from_tables` derives nothing from `agents` or `agent_places`,
     and there is no `__post_init__`. But `dataclasses.replace` shares `_cache` unless it is passed `_cache={}`
     (finding 4).
   - With the seq-0 wrapper, the lazy State's decisions on Task 8's denies equal revision 7's. Without the wrapper, a
     deny naming another place raises `KeyError: 0`.
3. **Are the statements about revision 7 accurate?** Yes.
   - `COSUBJECTS_SQL` searches `sqlite_autoindex_copies_1`, `subjects_object` and `sqlite_autoindex_stores_1`.
     `latest_lane_note` uses `lane_notes_object`, and `store_row` uses `sqlite_autoindex_stores_1`. `REFUSALS_SQL` scans
     `records`, `persons` and `places`.
   - The cap fixture holds no deny and no retirement (`tests/imprint_support.py:2596-2625`, `:824-845`). So
     `Refusals.any` is false, and the only `state()` call in the imprint path (`imprint_filter.py:570`) never runs at
     the cap: the cap test runs the calm path only.
4. **Are the tests feasible and sufficient?** Mostly, but not as written.
   - The torn-page test can't tear an autoindex with the helper it names, and its "on main the same plan ships m3"
     is false for two of its parameters (finding 6).
   - Nothing tests a lazy `LedgerUnreadable`, or the `sqlite3.Error` that `state()`'s own reads raise (finding 5).
   - `read` and `cosubject_rows` aren't named or counted, and `check_owner` runs inside `_working_copy` on the raw
     ledger (finding 7).
   - The lazy-agent test needs a deny that reaches `seq_at[0]` (finding 4).
   - The cap's deny variant can't run until the fixture is restamped (finding 1).
5. **Does more leave, or is any permission widened?** No.
   - `subjects_of(state, ref, None)` minus the owner equals `COSUBJECTS_SQL` on all 100,000 refs of the reference
     ledger ("differ: 0").
   - The one semantic difference: `_own_subjects` drops a ref that doesn't parse. That can't bite, because
     `record_copy` parses both refs (`permission_ledger.py:1975-1976`).
   - The 8 kept "in sorted order" only decide which reason a memory over the bound is counted under. It stays home
     either way.
   - The agent goes into the State only, never into the ledger.
   - Revision 8 refuses in more cases: a failed check, more than `MAX_RECORDS` records, or a write racing `_late`.
     That only narrows.
6. **Are the 14.1 rows consistent?** Yes.
   - 45.0 + 64.5 + 25.3 + 6.1 = 140.9, as the permissions spec's 15 has it
     (`docs/superpowers/specs/2026-10-25-permissions-by-place-design.md:2132-2138`).
   - 145.4 + 140.9 = 286.3, and 165.4 + 140.9 = 306.3. Both are under 384.
   - A 512-ref prefetch fits in `STATE_ROWS` (65,536), which the 25.3 counts.
   - The measured 106 MiB is a probe process's peak, not the plan's (finding 9).

## Findings

### 1. Must-fix: the cap fixture's ledger fails the check, so Task 8a's Step 4, and today's cap test, refuse

- **What happens:** `_fixture_ledger` (`engram/tests/imprint_support.py:2596-2625`) creates a stamped ledger
  (`Ledger.create`, schema version 2). It then inserts 700,000 `subjects` rows by raw SQL and never restamps.
- **Why it never showed:** on main, nothing on the cap's plan, read or build path calls `Ledger.state()`. The only call
  is the deny path (`imprint_filter.py:570`), and the cap fixture has no deny.
- **Under revision 8:** every cap process builds a State. The raw commit moved the key off the marker, so the full check
  runs and fails: "the projection digest: subjects differs". That becomes `PlanRefused("The permissions ledger can't
  be read; nothing was planned.")`.
- **Reproduced:** `review-r8/rawfix.py` (create, register a store by append, insert 50 subject rows by SQL, then
  `state()` in a fresh process) gives exactly that refusal.
- **Consequence:** `test_pi_every_process_at_the_cap` (plan, read, build) goes red the day Task 8a merges, and Step 4's
  `plan-deny` and `build-deny` can't run.
- **What Task 8a, and section 16's cap bullet, should say:**
  - `_fixture_ledger` calls `restamp_projection(eh)` (`tests/permissions_memory_support.py:13`) after its inserts.
  - The fixture kept under `/var/tmp/imprint-cap-<uid>` is versioned so the Pi rebuilds it. `_cap_world` checks only
    `.ready`, and the store's ids are uuid4, so `STAGE_VERSION` moves too.
  - The deny variant's deny and retired place are written with `_append` (or restamped), on a copy of `eh`.

### 2. Should-fix: the check holds when the State is built, not through the plan's run

- **The prose:** "it reads the State's per-object rows on a connection checked against that state" (spec:50). Each
  `_late` connection is checked once, when it opens (`_check_late`, `permission_ledger.py:1254-1268`).
- **What actually happens:** every `RowMap` and `LogTimes` read after that runs in its own autocommit transaction, with
  no new key read. The plan's 100,000 memories, and the build's `cosubject_rows`, are read over minutes at the cap.
- **The risk:** ordinary writes landing mid-run are safe by design (seq filtering). A ledger overwritten in place
  during the run (same inode, as `cp` onto the path writes it) is read past, through the same indexes, unchecked.
- **The fix:** state the residual. Better, close it cheaply: after the last per-object read of a plan, a read and a
  build, read the key once more on the `StateRows` connection and refuse if it moved to a key that neither the memo
  nor the marker holds. That is `_check_late`'s own test, and it costs one SELECT, one pread and one stat.

### 3. Should-fix: unstamped ledgers stay open, where an open ledger costs the most

- **The prose (spec:63-66):** a schema-1 ledger is read unverified, as revision 7 did and every reader does. That is
  accurate: `state()` skips `_verify` and `_late(None)` checks nothing (`permission_ledger.py:1355-1358`, `:1236-1240`).
- **The problem:** the Status line and the revision-history row say the plan's facts are "checked by the projection
  digest and SQLite's integrity check" with no such caveat. And the plan is the act that copies other people's
  memories off the machine. If the owner's ledger predates the digest, revision 8 changes nothing for the first real
  imprint.
- **Proposal:** refuse plan, read and build on an unstamped ledger with the gate's own words (`UNSTAMPED`,
  `permission_ledger.py:2911`; the gate already refuses `enforce` there, `:3042-3043`). The way out is one
  `engram-permissions rebuild`. Add one test.
- **If that's judged too strict:** run `PRAGMA integrity_check` on such a ledger before the State, which closes the
  torn-index half of the class. Failing that, at least put "on a stamped ledger" into the Status line and the row.

### 4. Should-fix: name the `_cache={}` and the wrapper's `prefetch` that the measured prototype used

- **Where the text falls short:** the plan's interface says the agent is added "through `dataclasses.replace`" (plan:1142).
  But `replace` copies `_cache` by reference. `review-r8/replace_cache.py` shows "replace shares _cache: True", and
  after `layer_boxes` an `lbox` memo (computed from `state.agents` and `agent_places` by `_audience_boxes`,
  `permissions.py:2987-3030`) sits in the shared dict.
- **Why it isn't a live bug today:** the memos on `record_matches`'s path (seq-times, lane-tests, record-terms, anc,
  dom) don't depend on the agent. But a later memo that does would answer for the agent from the State without it.
- **What the prototype did:** `lazy_agent.py:27` passes `_cache={}`. Its `WithZero` also forwards `prefetch`, without
  which `State.prefetch` silently skips batching the log times (`permissions.py:497-500`).
- **Fixes:**
  - Write both into the interface.
  - In `test_the_agent_keeps_the_state_lazy`, assert that the State's `_cache` isn't the ledger State's.
  - Include a deny that reaches `seq_at[0]`: Task 8's jenn deny naming only `place:la-county/parks` does, through
    `_audience_entry`'s `_meets` on the agent's placement (`permissions.py:986-990`).
- **Evidence:** `review-r8/seq0.py`. With the wrapper, the lazy decisions equal revision 7's whole State. Without it,
  `KeyError 0`. A test without such a deny would pass with the wrapper missing.

### 5. Should-fix: the `LedgerUnreadable` to `PlanRefused` mapping covers only the State's build

- **The plan says:** "`LedgerUnreadable` from the State reads as `PlanRefused`" (plan:1144).
- **What else raises, later and elsewhere:**
  - `StateRows._query` and `LogTimes._query` raise `LedgerUnreadable` on the lazy reads (`permission_ledger.py:170-175`,
    `:279-284`). Those happen deep in `base()`, `cosubject_rows` and `record_matches`.
  - `_late` raises the `_CHANGED` "changed during this read; retry" error when a write lands between `state()`'s
    COMMIT and its own check, and no marker follows within 50 ms.
  - `state()`'s whole-table reads, before `_verify`, raise plain `sqlite3.DatabaseError` on a malformed page, because
    it wraps none of them.
  - In read and build, `_working_copy`'s callers catch only `sqlite3.Error` and call it "the source store changed"
    (`imprint.py:842-847`, `:983-988`). The State may now be built inside `check_owner`, in `_working_copy`, so a
    ledger fault would be reported as the store's.
- **Is it unsafe?** No, all of these fail closed: the build removes its directory on any `BaseException`
  (`imprint.py:1031-1035`). But the sentence the spec promises isn't what the owner sees.
- **Fixes:**
  - Every `LedgerFacts` read maps `LedgerUnreadable` and `sqlite3.Error` to the ledger's sentence. `_CHANGED` gets a
    "retry" sentence: the engram server writes lane notes during a plan, so the race can happen.
  - Add a test where a per-object read fails after `state()` succeeds: monkeypatch `StateRows._query`, then check that
    plan and build refuse with the sentence and leave no plan or package.

### 6. Should-fix: the torn-page test, as written, can't tear two of its indexes, and its "on main" claim fails for two

The test is spec:2611-2616 and plan:1159-1160.

- **(a) The autoindexes can't be torn with the named helper.** The plan's `tear_index` follows the permissions tests'
  `_tear_index` (`tests/test_permissions_premerge_fixes.py:69-82`): drop, rebuild as a partial index, then rename in
  the schema. SQLite refuses `DROP INDEX` on `sqlite_autoindex_copies_1` ("index associated with UNIQUE or PRIMARY KEY
  constraint cannot be dropped"), and the index's `sql` is NULL.
  - What works: splice the index's root page from a twin file in which the row was deleted. I prototyped it: the
    indexed read misses the row, the `NOT INDEXED` read finds it, and `integrity_check` reports "row 4 missing from
    index sqlite_autoindex_copies_1".
- **(b) "On main the same plan ships m3" is false for two parameters.**
  - With `lane_notes_object` torn, main misses only the lane note. Lee's deny still keeps m3 home.
  - With the stores autoindex torn so that it hides the source store's row, main's `check_owner` refuses with "not
    registered" (`imprint_filter.py:522-524`). So a test that asserts only `PlanRefused` passes on main.
  - Each parameter needs its own memory and row:
    - copies tear: lee recorded on m3's copy source, not on m3;
    - stores tear: lee as owner of another registered store that m3's copy chain reaches, with only that store's
      index entry hidden;
    - lane tear: a memory with a `pending` note and no co-subject.
  - Every case should assert the "can't be read" sentence.
- **(c) The tear has to move the key.** A page splice leaves the size and the change counter alone, so only ctime moves
  the key. Sleep first, as `test_4_the_key_holds_ctime` does (`tests/test_permissions_projection_digest.py:420-436`),
  or clear the memo and the marker. Otherwise the marker is trusted and the test is flaky.

### 7. Should-fix: name `read`, `cosubject_rows` and `check_owner`'s place, and count all three processes

- `imprint.py read` opens the ledger and runs `package_rows`, so `base` and `_admits` too (`imprint.py:841-856`). It is
  in 14.1's first row. Yet Task 8a's Files (plan:1132) names only "a plan or a build", and its count test (plan:1154)
  counts only those two.
- `cosubject_rows` (`imprint_filter.py:876-884`) is the second user of `cosubjects_of`, and the one that writes
  `imprint_subjects`.
- `check_owner` runs inside `_working_copy` on the raw ledger (`imprint.py:334`). In `make_plan` that happens before
  `c = replace(ctx, ...)`. So `LedgerFacts` has to be passed into `_working_copy`, or keyed by the ledger, or each
  process builds two States.
- Say "one per plan, per read and per build", and have the count test cover all three. In 14.1, "once per plan" becomes
  "once per process".

### 8. Nit: the speed comparison was measured in ref order

- `measure.py`, `peak.py` and `lazy_agent.py` read refs `ORDER BY` object. The plan reads by `(created_at, id)`, and
  engram ids are uuid4, so the plan's order is effectively shuffled.
- Shuffled (`review-r8/lazy_random.py`), the State's reads with prefetch take 6.72 s, against 6.65 s for revision 7's
  queries. That is about equal, not 5.0 against 6.4. The peak is the same 106 MiB.
- The reference ledger also holds no `copies` rows. Chain reads, one unprefetched query per link
  (`StateRows.prefetch` loads only the refs it is given), aren't in the measurement.
- Say both. The conclusion, no slower, holds.

### 9. Nit: the 106 MiB in 14.1 is a probe's whole-process peak

`lazy_agent.py` starts at about 35 MiB (VmHWM 36.5 MB before any read). The plan's base is 96. Write "a process holding
only the State: 106 MiB, about 71 over its base", so nobody reads it as the plan's peak (spec:2488).

### 10. Nit: stale and missing text

- Spec:459 still says "The plan's query stops at 8 rows for a memory". With no query left, it is the State's read that
  keeps 8.
- Plan:1166 keeps `COSUBJECTS_SQL` in the test as an oracle. But `test_the_state_answers_as_the_queries_did` also
  compares against `REFUSALS_SQL`, so keep it there too.
- Step 3 should say that `base()`, today a cursor generator deciding each row inline (`imprint_filter.py:648-680`),
  reads in chunks of 512 so that `prefetch` has refs to batch.

### 11. Nit: a calm-path refusal revision 7 didn't have

With a State always built, a ledger holding more than `MAX_RECORDS` (16,384) records now refuses the plan
(`permission_ledger.py:1342-1347`), where revision 7's calm path planned. That narrows, and P 5.6 already reads such a
ledger as unreadable. One sentence in the revision paragraph would do.

## What I ran

All runs were in `/home/doctor/.cache/claude-scratch/wt-imprint-state/engram`, at 601d7102 (code as main cdc639c1),
with `.venv/bin/python -I`, on the reference ledger at
`/tmp/claude-1000/-home-doctor-Projects-superyak/8312d28a-0287-4c9c-83bc-219f737116a6/scratchpad/cosub/home`. It holds
274 MB: 700,000 subjects, 0 copies, 300,000 lane notes, 10,498 records and 811,000 log rows, stamped v2, with no
marker.

| Probe | Result |
|---|---|
| `cosub/measure.py` | SQL 6.63 s; `state()` 6.66 s; State lookups 5.83 s; differ 0 of 100,000 |
| `cosub/lazy_agent.py` | `state()` with the lazy agent 6.64 s at 66 MiB; prefetch lookups 4.95 s; peak 106 MiB; 700,000 co-subjects |
| `cosub/peak.py sql` / `state` | 6.32 s at 35 MiB / 12.08 s at 86 MiB |
| `cosub/with_agent.py` (under `systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0`) | `_with_agent` 17.25 s, peak 851 MiB, 700,000 subjects held |
| `review-r8/eqp.py` | EXPLAIN QUERY PLAN for revision 7's queries, `StateRows.load` and `state()`'s reads (answer 3) |
| `review-r8/lazy_random.py` | shuffled refs: SQL 6.65 s; State with prefetch 6.72 s after a 6.69 s build; 106 MiB |
| `review-r8/rawfix.py` | the cap fixture's raw-SQL ledger: `state()` raises "the projection digest: subjects differs" |
| `review-r8/replace_cache.py` | `dataclasses.replace` shares `_cache`; `lbox` lands in it; `_cache={}` separates it |
| `review-r8/seq0.py` | Task 8's denies: lazy with the wrapper equals the whole State; without it, `KeyError 0` |
| autoindex tear | `DROP INDEX` refused; a root-page splice hides the row, and `integrity_check` names the index |

The `review-r8/` scripts are in
`/tmp/claude-1000/-home-doctor-Projects-superyak/8312d28a-0287-4c9c-83bc-219f737116a6/scratchpad/review-r8/`.

## Re-check of the second draft (16f07941)


Reviewer: the same fresh reviewer, on Tardis, 2026-11-18. I only read files and ran probes: I edited, committed and
posted nothing, left the main checkout alone, and did not read `~/.engram/imprints/`.

## Verdict: APPROVE WITH CHANGES

The draft resolves the Must-fix and nine of the other ten findings fully. Restamping the cap fixture works: a
restamped raw-SQL ledger is served by `state()` in a fresh process.

Two of its new texts still say more than they hold:

- **The closing key read**, as specified, can pass the very case it is there to catch (R1 below).
- **The torn-page test** claims revision 7 ships each case's memory. On the shared fixture that is false: main refuses
  too, by its own checked State (R2 below).

Both are one or two sentences to fix. Nothing in the draft widens a permission or lets more leave.

## The eleven findings

| # | Finding | Second draft |
|---|---|---|
| 1 | Must-fix: the cap fixture fails the check | **Resolved.** `_fixture_ledger` restamps, the fixture's version and `STAGE_VERSION` move, and the deny variant appends on a copy of `eh` (plan Files, Step 4; spec 16). Run on my raw-SQL ledger, `restamp_projection` makes `state()` serve it in a fresh process. Nit R4 below: where the deny and the retired place go. |
| 2 | Should-fix: the check holds only when the State is built | **Partly resolved.** `.close()` is the right shape, but it needs a key to compare against and a whole-key rule (R1). |
| 3 | Should-fix: unstamped ledgers | **Resolved on its merits** (see below), apart from one piece: `.close()` on such a ledger is undefined (R1c). The history row states the table-page gap. The Status line only says "on a stamped ledger by the projection digest" and points to the paragraph, which states the gap. That is enough. |
| 4 | Should-fix: `_cache={}` and the wrapper's `prefetch` | **Resolved.** `dataclasses.replace(..., seq_at=SeqZero(...), _cache={})`, a `SeqZero` that forwards `prefetch`, and a test that the `_cache` is the State's own and that holds jenn's `place:la-county/parks` deny. |
| 5 | Should-fix: the error mapping | **Resolved.** Every read, `.close()` included, maps `LedgerUnreadable` and `sqlite3.Error`. The `_CHANGED` race gets "Run it again". `read` and `build` get their own verbs. The late-failure test covers all three processes and leaves nothing behind. |
| 6 | Should-fix: the torn-page test | **Partly resolved.** The page splice, the ctime pause, one memory per case and the asserted sentence are all in. But the claim about revision 7 is false on the shared fixture, and two cases need copies made without `record_copy` (R2). |
| 7 | Should-fix: `read`, `cosubject_rows`, `check_owner` | **Resolved.** One State per process, `_working_copy` takes the `LedgerFacts`, and the count test covers plan, read and build. |
| 8 | Nit: the speed comparison | **Resolved.** 6.7 s against 6.7 s in the plan's order, and no copies in the reference, both said. My shuffled run gave 6.72 s against 6.65 s. |
| 9 | Nit: the probe's peak | **Resolved.** "About 71 over its base" is in the paragraph and in 14.1. |
| 10 | Nit: stale and missing text | **Resolved.** Line 459, `REFUSALS_SQL` kept as an oracle, and `base()` reading in chunks of 512. |
| 11 | Nit: the `MAX_RECORDS` refusal | **Resolved,** though "two refusals are new" now undercounts (R3). |

### The coordinator's two choices, on their merits

**Finding 3, an integrity check instead of refusing: sound, and I accept it.**

- It closes the torn-index half of the class on a schema-1 ledger, and that half is the M1 class.
- It costs one `PRAGMA integrity_check` per process. Only schema-1 ledgers pay it, since they never hold a mark.
- The reason given is fair: refusing would ask the owner for a rebuild that no other reader needs.
- What remains is a table page and its index pages torn consistently, or a column no index holds (a `retired_seq`).
  The history row says this plainly.
- It needs one more sentence on how `.close()` works on such a ledger (R1c).

**Finding 2, the closing key read: the right choice, not yet the right rule.** Details in R1.

## New findings

### R1. Should-fix: the closing key read needs its key, the whole key, and a rule for schema 1

The plan's interface (plan Interfaces, `.close()`) says the key is "read once more on the State's row connection, as
`_check_late` reads it; a key moved to a state neither the memo nor the marker holds refuses". The history row says
"a closing key read holds the run".

- **(a) Which key?** `Ledger.state()` keeps the key it checked in a local variable (`checked`,
  `permission_ledger.py:1336-1358`). It hands it to `_late` and stores it nowhere, so `LedgerFacts` has no key to
  compare against. Task 8a's Files list no change to `permission_ledger.py`.
  - Option one: expose the checked key from `state()`, which is a permissions-code change with that code's own review
    path.
  - Option two: right after `state()` returns, read K0 on the row connection, inside a BEGIN/COMMIT, with
    `permission_ledger._read_key`, and compare against K0 at the close.
- **(b) The whole key, not the counter.** `_check_late` treats only a changed change counter as a move:
  `if now.counter != key.counter and not _verified(...)` (`permission_ledger.py:1262`). A ledger overwritten in place
  by a copy with the same size and counter is the very construction of `test_4_the_key_holds_ctime`, and it passes.
  - I ran this in `review-r8/close_check.py`. After `state()`, I overwrote the ledger in place with a copy that had
    lee's row changed and its counter poked back. `_check_late` at the close: passes. Fields that moved: `{'ctime_ns'}`.
    A whole-key rule refuses.
  - SQLite also trusts that counter for its own page cache, so such a file is read half from cache and half from disk.
  - So the close must refuse when any field of the key differs from K0 and neither the memo nor the marker holds the
    new key.
  - `test_the_ledger_moved_mid_run_refuses` should replace the file with that same-counter, same-size copy. A plain
    replacement moves the counter and passes under either rule.
  - The close runs before the plan, the page or the package is written, and the test asserts that none is left.
- **(c) Schema 1.** On an unstamped ledger, `checked` is None, writers leave no mark (`permission_ledger.py:1538-1543`),
  and the integrity check runs in a transaction of its own before `state()`. A write between the two is never seen
  by the check.
  - Say that K0 is read in the integrity check's own transaction, and that at the close any change from K0 refuses
    with "Run it again". With no marks on schema 1, a share or a re-lane during the run then means one retry. That is
    the price of the choice, and it should be stated with it.

### R2. Should-fix: the torn-page test's claim about revision 7 is false on the shared fixture

Spec 16 says "under revision 7 the same plan shipped that case's memory". The plan's Step 1 says "on main each case's
memory ships".

- **The fixture holds lee's deny,** which the `records` case needs. Lee's layer is outside andy's home, so on main
  `REFUSALS_SQL` finds it. Then any memory whose co-subject survives the tear reaches `_refusals`, and main builds
  `ledger.state()`, whose full check catches the torn index and raises.
- **Demonstrated** in `review-r8/main_tear.py`, on main, with `subjects_object` torn so that it misses lee on m3 and
  jenn left on m4:

  | Case | Result |
  |---|---|
  | home, lee's deny in the ledger | `LedgerUnreadable`: SQLite's integrity check, "wrong # of entries in index s…" (raised, not `PlanRefused`) |
  | home, no deny | ships m3, m4 and plain, with `others_memories` 1 (m3 left without lee) |
  | away, no deny | ships m3 and plain, with `needs_yes` 1 |

- **So the test is still red on main, but because main crashes, not because it leaks,** and the stated reason is wrong.
- **The fix, for the four index cases:**
  - Use copies of the fixture made before any deny or retirement outside the home.
  - Plan away from home, where a hidden co-subject turns "needs yes" into "ships". Or keep home and assert on main that
    the memory ships without lee's `imprint_subjects` row.
- **The `records` case** needs a copy whose only deny outside the home is lee's.
- **m4 and m5 need their copies made without `record_copy`.** It writes the source's subjects, the source store's owner
  included, into the copy's own rows (`permission_ledger.py:1999-2012`). Then lee would sit on m4 or m5 itself, and
  neither the copies tear nor the stores tear would hide lee.
  - Make those `copies` rows with `link_copies` (`tests/imprint_support.py:792-795`), or add lee to m4's source after
    the copy.

### R3. Nit: "two refusals are new" undercounts

The revision paragraph names the failed check and `MAX_RECORDS`. Three more refusals are new, each refusing a plan that
revision 7 made: the closing key read, the integrity check on a schema-1 ledger, and the `_CHANGED` race. All of them
narrow, so the closing sentence still holds. Name all five.

### R4. Nit: put the cap's deny where it is tested

Step 4 appends "one deny outside the owner's home and one retired place".

- If the deny sits in a layer that no cap co-subject has, `refuses` returns at once for every memory, and
  `record_matches` never runs at the cap.
- Put it in one co-subject's home, say `place:home/p0000000`, so that it matches the imprint's use and keeps that
  memory home.
- Register the retired place as a new place, not `place:home/andy`.

### R5. Nit: co-subjects are read by plan, read and build

The added sentence in 5.2 says "`imprint.py read` and `build` read them the same way, the build for the
`imprint_subjects` rows it writes". The plan reads them the same way too, through `cosubject_rows`, for `others` and for
the digest's `imprint_subjects` table (`imprint_filter.py:1154-1187`). A small fix: say that all three read them.

## What I ran

All runs were in `/home/doctor/.cache/claude-scratch/wt-imprint-state/engram`, with `.venv/bin/python -I`. The scripts
are in `/tmp/claude-1000/-home-doctor-Projects-superyak/8312d28a-0287-4c9c-83bc-219f737116a6/scratchpad/review-r8/`.

- `git show 16f07941`, read whole, against the code at main cdc639c1.
- **`restamp_projection`** on the raw-SQL fixture from my first review (a copy at `review-r8/restamped`): served, at seq
  2 with 50 subject keys, in a fresh process.
- **`close_check.py`:** an in-place, same-counter, same-size copy after `state()`. `_check_late` passes; only `ctime_ns`
  moved; a whole-key rule refuses.
- **`main_tear.py`:** main's `base()` on a torn `subjects_object` page, three ways (the table in R2).
- **Code read:** `permission_ledger.py:1254-1268` (`_check_late`), `:1332-1371` (`state()`), `:1521-1545` (writers mark
  only with a base key), `:1965-2013` (`record_copy` carries subjects); `server.py:2450-2472` (lane notes written on
  share); `imprint_filter.py:1154-1187` (`_others` and the digest use `cosubject_rows`).

## Last check of the third draft (92b84d52)


Reviewer: the same fresh reviewer, on Tardis, 2026-11-18. Scope: R1 to R5 from the re-check, and anything the new
text breaks or overclaims. I only read files and ran probes: I edited, committed and posted nothing, left the main
checkout alone, and did not read `~/.engram/imprints/`.

## Verdict: APPROVE WITH CHANGES

R2 to R5 are resolved, and so are R1's three parts as I asked them. The remaining change is one sentence, F1 below.

The new closing rule says a ledger overwritten in place does not pass. It does pass if the overwrite is a clean, older,
stamped ledger and a writer appends to it during the run. Both a probe and the code show it.

The fix is one more condition, read on a fresh connection. If F1 goes in as written, I don't need to see the spec
again. The nits are optional.

## R1 to R5

| # | Re-check finding | Third draft |
|---|---|---|
| R1(a) | Which key the close compares with | **Resolved.** `Ledger.state()` keeps the key it checked as `Ledger.state_key`, listed in Task 8a's Files as the one change to permissions code. On a stamped ledger K0 is `state_key`; on an unstamped one, K0 is read in the integrity check's transaction. |
| R1(b) | The whole key, not the counter | **Resolved.** Every field is compared (`dev`, `ino`, `size`, `ctime_ns`, `counter`, `head`), not only the counter as `_check_late` compares it. The close runs before anything is saved. The mid-run test uses a same-size, same-counter copy with lee's row changed, and a marked append passes. |
| R1(c) | Schema 1 | **Resolved.** K0 comes from the integrity check's transaction, and any change refuses with "Run it again". The cost, one retry when a write lands during the run, is stated, as is the test. |
| R2 | The torn-page test's claim about revision 7 | **Resolved.** See the notes below this table. |
| R3 | "Two refusals are new" | **Resolved.** All of them are named. |
| R4 | Where the cap's deny goes | **Resolved.** The deny is in a cap co-subject's home layer, matching `imprint` for the plan's purpose, and a newly registered place is retired, both appended. This runs: a cap co-subject isn't a registered person, so `_layer` gives `home_of(subject)`, and the fixture's `deny()` audience matches the agent at the owner's home, as Task 8's lee test already shows. |
| R5 | Who reads co-subjects | **Resolved.** "Every read of them goes through that State, `cosubject_rows` included", for `others`, the digest and `imprint_subjects`, in plan, read and build. |

Notes on R2:

- **The four index cases** run on ledgers with no deny outside the owner's home, so revision 7 builds no State there.
- **m4 and m5** have their copy links written with `link_copies`, so their own rows don't carry lee.
- **The `records` case** holds lee's deny and nothing else.
- **What revision 7 does in each case** is now stated correctly: it ships each memory without lee's `imprint_subjects`
  row, with its re-lane unsettled, or carrying lee despite lee's no. This matches `main_tear.py`: "home, no deny:
  ships m3, others_memories 1".

## New findings

### F1. Should-fix: after a clean in-place restore and a writer's marked appends, the close passes

**The claim.** The revision paragraph says "a writer's ordinary append during the run is marked and passes, and a file
overwritten in place, even at the same size and counter, does not". The history row says the closing read "holds the
run".

**The probe.** `review-r8/restore_append2.py` builds the State at seq 3, with lee on m3 written by seq 3. It then:

- writes over the ledger in place with a clean backup taken before lee's append, with the same inode;
- has a writer append twice to it. The writer's base check passes, because the backup is a consistent stamped ledger,
  so the writer marks its commit.

**The result.**

- The State's lazy read of m3 now returns `[]`, so lee is gone.
- At the close the whole key has moved, but the marker holds the new key, so the third draft's rule passes.
- A memory could then ship without lee's co-subject row. That is the class this revision closes.

**Why "verified" isn't enough.** Under D4 it means "some process checked this state". It doesn't mean "this state
follows the one the State was read at".

**The fix.**

- At the close, also require that the log still holds, at the State's seq, the row K0's head names:
  `SELECT seq, digest FROM ledger_log WHERE seq = <State seq>` must equal K0's `head`.
- The log is append-only, so an ordinary write never changes that row. A restore to an older state removes it or
  changes it. In the probe this check reads `False`.

**Read the close on a fresh read-only connection, not the State's row connection.**

- `head`, and that log row, come through SQLite's page cache. SQLite reuses its cached pages whenever the file's change
  counter is unchanged.
- The one-append run (`restore_append.py`) shows this. The restored backup plus one append landed on K0's counter (37).
  The row connection then read a stale `head` (`3:5149…`) while the marker held the true one (`3:68f7…`). The close
  refused there, but by the luck of the cache.
- The probe that gave `[]` for m3 shows the State's own row connection mixing cached and fresh pages.
- A new connection gives the close fresh pages. If the file was renamed in its place, the close sees the new file; that
  refuses or passes by the same two rules.

**Add one test case:** a clean older backup restored in place, then two marked appends, and the close refuses.

**What to change in the text.** The paragraph's sentence and the history row then hold as written, with "and the log
still holds the State's own row" added.

### Nits

- **N1. The mid-run test needs the ctime pause.** "The ledger moved during the run" overwrites the file right after the
  State is built. If the overwrite lands in the ctime tick of the last append, the whole key is unchanged and the close
  passes, so the test is flaky on a coarse-ctime filesystem. Pause as the torn-page cases do (`time.sleep(0.02)`, as in
  `test_4_the_key_holds_ctime`).
- **N2. The stamped close's refusal sentence.** On a stamped ledger, a moved key that no mark holds is more often an
  ordinary write whose mark failed (two quick commits, or WAL) than a tear. A rerun runs the full check, which tells the
  two apart. Give the stamped close the "Run it again" sentence too, or say which sentence it uses. The test asserts
  "the ledger's sentence", which as written means "can't be read".
- **N3. More than shares and re-lanes write the ledger.** "A share or a re-lane during the run costs one retry" (on an
  unstamped ledger) undercounts. A kept `remember` (`record_copy`), genome sync and any CLI act also write it. Say "any
  write, such as a share or a re-lane".
- **N4. The index cases need no retirement either.** "On ledgers with no deny outside the owner's home": `REFUSALS_SQL`
  also counts retirements, and one would make revision 7 build its checked State. Say "no deny outside the owner's home
  and no retirement".

## What I ran

All runs were in `/home/doctor/.cache/claude-scratch/wt-imprint-state/engram`, with `.venv/bin/python -I`. The scripts
are in `/tmp/claude-1000/-home-doctor-Projects-superyak/8312d28a-0287-4c9c-83bc-219f737116a6/scratchpad/review-r8/`.

- `git show 92b84d52 -- engram/docs/superpowers/specs engram/docs/superpowers/plans`, read whole. The commit changes
  docs only; `state_key` is a plan item.
- **`restore_append.py`:** a clean backup restored in place after `state()`, then one marked append. The close refuses,
  but only because the row connection reads a stale `head` from SQLite's cache (the counter matched K0's).
- **`restore_append2.py`:** the same with two appends. The close passes under the third draft's rule, while the State's
  read of m3 has lost lee. The check of the log row at the State's seq refuses.
- **Code read:**
  - `permission_ledger.py`: `:1254-1268` (`_check_late`), `:1298-1314` (`_mark_after_commit`), `:1521-1545` (writers
    mark only with a base key), `:2603-2616` (`_layer`, `home_of`);
  - `tests/imprint_support.py:740-795` (`deny`, `link_copies`).
