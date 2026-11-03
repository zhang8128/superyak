# Plan: the permission ledger's projection digest

**By:** Tardis, 2026-11-03. **Board item:** `build:permissions-projection-digest`. **Revision 3.**

**History:**
- **Revision 1** used a process cache keyed on mtime. Task 0 showed a full check is too slow to repeat after every
  write.
- **Revision 2** (bc3b5950) moved to a verified marker and took Rio Grande's three drift rules (D3). A fresh reviewer
  gave it REVISE, with four Must-fixes, nine Should-fixes and eight nits
  ([review](../reviews/2026-11-03-projection-digest-plan-review.md)). Each is answered here, marked M1-M4, S1-S9 and
  N1-N8.
- **Rio Grande's Pi run** of Task 0 sets D9 (all hands, 706cb8fb).

**What it closes:** R48's follow-up in docs/superpowers/plans/2026-10-25-permissions-by-place.md (line 167), Serenity's
re-check N1, and pre-merge item 5. `ENFORCE_WAITS` (permission_ledger.py:2070-2074) blocks `gate enforce` until this
lands.

**Who waits on it:** the crossing's stage 2 (tardis/crossing-spec, approved), and any house that wants `enforce`.

**This is safety code** (what the permission ledger serves). It gets a test-first build, a fresh Pi reviewer and each
partner's yes before merge, under law section 2.

## The hole

R48's tail checks catch a copy torn in one row per column. A tear across several rows of one column, or a torn index
page, can still read whole. The strict xfail at engram/tests/test_permissions_premerge_fixes.py:204-222 is the case:
- Andy uncollects m2 and m3 in one act;
- a tear keeps m3's removal and loses m2's;
- every tail check passes;
- m2 reads as a member again.

## What the code does today (main b7d91462)

- **Tables:** seventeen projected tables, named with their columns in `permissions._COLUMNS` (permissions.py:374-397),
  plus `meta` and `ledger_log` (permission_ledger.py:48-99) (N1). `proposals` is read on demand (:114). Rows are only
  inserted, or updated to set later columns, and never deleted. One column is a BLOB (`places.pseudonym_salt`, :56).
- **`_append`** (:840-879) works under `BEGIN IMMEDIATE`: bounds, `_tail_problems`, the log row, `_project`,
  `meta.head`, then COMMIT. `_project` also writes `meta` (:971-973).
- **`state()`** (:660-703) reads twelve tables whole, in one read transaction. It then opens two more read-only
  connections, StateRows and LogTimes (:694-696), which the daemon keeps across threads.
- **Journal mode:** connections run SQLite's default rollback journal. `rebuild` sets `MEMORY` per connection (:1329).
  No code sets WAL.
- **The change counter:** in DELETE and MEMORY mode, the 4-byte counter at header offset 24 rises once per commit. It
  doesn't move on a rollback, an empty transaction, a no-op `CREATE INDEX IF NOT EXISTS` or a same-value update. The
  reviewer tested this on SQLite 3.46.1.
- **Opens:** every caller opens per call. The daemon calls `state()` per frame under shadow and enforce
  (lighthouse_daemon.py:871-878). server.py opens and writes per tool call (:2512-2522). Hooks never open the ledger.
- **SQLite here:** `sqlite_dbpage` isn't compiled into the Engram venv's SQLite (3.53.1, checked on Tardis), though
  the system Python's 3.46.1 has it.

## Decisions

**D1. Where the digest lives.** Two `meta` keys, `projection` (`<seq>:<64 hex>`) and `projection_parts` (canonical
JSON of each part's count and sum), are written in `_append`'s transaction beside `head`.
- The log body and the chain don't change.
- `_project` refuses a body that sets `projection` or `projection_parts`, as it refuses `head` (:946-947) (N5).

**D2. The digest.**
- **A row's hash:** BLAKE2b-256 of an explicit encoding (N3):
  - first `t<len>:<table name>`;
  - then, for each value in `_COLUMNS` order, a tag with a length and the bytes: `n` (NULL, no length or bytes), `i`
    (decimal), `s` (UTF-8), `b` (raw bytes) or `r` (`repr` of a REAL).
- **A part:** a count and a sum of row hashes mod 2^256. There's one part per projected table, plus one part `meta` over
  every `meta` key except `head`, `projection` and `projection_parts`, so `gate`, `admins` and `owner` are covered
  (S7).
- **The whole:** BLAKE2b-256 of the parts' canonical JSON, in a fixed order.
- **What it's for:** it detects accidental tears. It isn't a MAC against someone who can write the file.
- **`canonical_json` is left alone** (N2), since this encoding doesn't use it.

**D3. The incremental writer: hash only what SQLite holds** (Rio Grande, a5598b76):
- after each insert, `_project` re-reads the row by `lastrowid` and hashes that, since affinity converts bound values;
- for updates, it captures the matched rowids first, subtracts those rows, updates, re-reads those rowids and adds
  them, never re-evaluating the `WHERE`;
- `meta` writes are re-read the same way;
- an `sqlite3` authorizer refuses any `DELETE` on a projection table outside `_project` (S8). Only the test fixture
  `detach_last_collect` (permissions_budget_ledger.py:109) is exempt, and it restamps after.

**D4. The full check, and when it runs.**

**The full check:**
- recompute every part by a `NOT INDEXED` scan, including `meta`;
- compare each part and the whole with `meta`. A mismatch names the part, for example "the projection digest:
  collection_members differs" (M4c);
- check that `SELECT COUNT(*) FROM ledger_log NOT INDEXED` equals the top seq, so a log's middle rows can't vanish
  unseen (S7);
- run `PRAGMA integrity_check`, which catches torn index pages.

Any failure, including any `sqlite3.Error` during the check, raises `LedgerUnreadable("the projection digest …")` (N3),
so the ledger fails closed.

**Reading the file's state, never with `open()`/`close()`** (M2). Closing any descriptor on the file drops all of the
process's POSIX locks on it, which SQLite holds.
- The counter and the journal bytes come from `os.pread` on a descriptor that the process opens once per (dev,
  inode) and **never closes**. A replaced file gets a new descriptor, and the old one stays open. That's one
  descriptor per replacement, which is rare.
- `os.stat` opens nothing.
- `sqlite_dbpage` isn't available in the Engram venv's SQLite, so it isn't used.

**The key:** (`st_dev`, `st_ino`, `st_size`, `st_ctime_ns`, the change counter, `head`). It's trusted only when **the
rollback journal is pinned** (M3):
- header bytes 18 and 19 are both 1;
- there's no non-empty `-wal` file beside the ledger.

Otherwise every `state()` runs the full check. Writing opens also set `PRAGMA journal_mode=DELETE`.

**Readers capture the key inside their read transaction** (M1):
1. Stat the path before connecting.
2. `BEGIN`, then a `SELECT` to take SHARED.
3. Read the counter and journal bytes by `pread`, `head` by SQL, and stat again.
4. Require the same (dev, inode) both times.
5. Compare with the in-process memo, then the on-disk marker. On a match, serve from this transaction.
6. On a mismatch, wait 50 ms and re-read the marker once (S2). That covers the moment between another writer's
   COMMIT and its marker write. Only then run the full check.

Readers never write files (S5), so `verify`, `check` and test_u9 stay true. A full check that passes is kept in the
**in-process memo** under that key, behind a lock, so two concurrent frames (FRAMES_AT_ONCE=2) don't both run one
(N8).

**StateRows and LogTimes** (:694-696), which connect after the check (S7):
- each stats the path after connecting and requires the checked (dev, inode);
- inside its own read transaction, it requires the counter the check saw.

Otherwise it raises `LedgerUnreadable("the ledger changed during this read; retry")`, which callers already treat as
unreadable.

**Writers** (M1, S1):
1. **Before `BEGIN IMMEDIATE`,** the writer makes sure its base is verified (a memo or marker match, or a full check),
   outside the write lock. A full check can take seconds on the Pi, and other writers wait 5 s at most (`BUSY_MS`,
   :46).
2. **Under `BEGIN IMMEDIATE`,** it re-reads the key and counter c. If they differ from the verified key, it rolls back
   and returns to step 1, at most three times, then raises `LedgerUnreadable` (busy).
3. **After COMMIT,** it runs `BEGIN` and a `SELECT` (SHARED, so no other commit lands), then reads the counter, `head`
   and stat, and ENDs.
4. **The marker** is written only if the counter is c+1 and `head` is its own. Otherwise there's no marker, and the
   next reader runs one full check.

The marker is `permissions.verified`, a canonical JSON of the key (N8), written best-effort:
- under a unique temporary name, then renamed;
- not fsynced (S2);
- ignoring EACCES and EROFS.

`_forget_ledger` (permission_cli.py:1063) removes it (N7).

**D5. Ledgers made before this** (S6):
- **A ledger is stamped only when it's new or rebuilt:** `Ledger._blank` writes the empty projection, and `rebuild`
  makes fresh tables from the log, then runs one full check. A writing open doesn't stamp an old ledger, since that
  would bless a tear it already holds.
- **An unstamped ledger** works as today under `off` and `shadow`. `_append` maintains no digest there (N8). Under
  `enforce` it reads `closed`, with the cause "no projection digest; run rebuild".
- The Pi has no ledger yet, so Andy's `migrate` creates a stamped one.

**D6. `enforce` requires the digest** (N6):
- `ENFORCE_WAITS` becomes `None`, in its own commit;
- the digest rule moves to `_prep_gate` (:2233) and the CLI's gate path, where the ledger is open, because
  `check_gate_mode(mode)` (:2237) sees no ledger;
- `gate enforce` is refused on an unstamped ledger;
- the refusal tests (test_permissions_premerge_fixes.py:225-270) become tests of this rule.

**D7. `verify` and `rebuild`** (S4):
- **`verify`** stays read-only, and also reports the parts.
- **`rebuild`** is the recovery path, so it **reports** whether the old tables matched and never refuses. It writes no
  marker per append, runs one full check at the end, and then writes the marker.
- **Tests that change:** test_permissions_ledger.py:323, :337 and :355 pin rebuild's folder contents and its
  `os.replace` calls. They're updated for the marker, which arrives after the replace.

**D8. Version skew** (S3):
- **Old code can't write a stamped ledger:** `SCHEMA_VERSION` rises with the stamp (:579-583), so an MCP server still
  on old code refuses it, instead of leaving `projection` behind `head`.
- **The reader names the cause:** "projection seq N behind head M".
- **Deploy:** restart every Engram process.

**D9. Budgets, set from Task 0 on both machines** (S9):

| Measurement, at 236,389 rows and 28.7 MB | Tardis (x86, quiet) | Pi (loaded, 6.4) |
|---|---|---|
| `state()` | 0.35 s | 0.94 s |
| full recompute | 1.0 s | 2.43 s |
| `integrity_check` | 0.15 s | 0.40 s |
| the full-check path through `state()` | ≈1.5 s | ≈3.8 s |

- **The rare path's budget,** `state()` plus the full check: 2.5 s on x86 and 8 s on the Pi. `integrity_check` stays in
  it, since there's no fallback to define.
- **A marker or memo match:** at most 2 ms over today's `state()`.
- **Append:** at most 2 ms more than today's median.
- **Rebuild:** within the existing rebuild budgets (permissions_support's `REBUILD_LEDGER_S`), with the digest kept
  per append.
- **Today's 0.94 s `state()` on the Pi** is a separate cost of the daemon's per-frame reads. It belongs to the daemon's
  own cache, not to this build (Rio Grande).

## Tasks (test-first: each test is seen failing before its code)

0. **Measured** (above). **0b:** check `sqlite_dbpage` and `os.pread` in the Pi's and the Mac's Engram Python. Only
   `os.pread` is relied on.
1. **The row encoding and hash** (D2). Tests:
   - known rows hash to fixed values, with every tag and a REAL;
   - a part ignores insert order;
   - the `meta` part excludes `head` and `projection*`.
2. **`projection_now`, the full recompute** (D2, D4): a pure read. Tests:
   - an empty ledger's digest is fixed;
   - a mismatch names its part;
   - a missing log middle row is caught by the count.
3. **The incremental writer** (D3). Tests:
   - **An autouse conftest check** after every `_append`, across the whole Engram suite: `meta.projection` equals
     `projection_now` (S8). That replaces a random-act generator, which doesn't exist.
   - **Hand-made bodies:** an int into TEXT, `"5"`, `1.5`, a bool, a dict, and the salt.
   - **An update that changes its own `WHERE` column.**
   - **The authorizer** refuses a `DELETE` outside `_project`.
4. **The reader and the marker** (D4). Tests:
   - **The acceptance test:** the xfail at :204-222 passes with `match="projection digest"`, naming
     `collection_members`. A control with no tear reads whole (M4d).
   - **A torn index page** (`_tear_index`, :69-82) is caught.
   - **Field by field** (M4a), so each mutant dies:
     - **ctime only:** a `cp -p` of a tampered copy over the ledger, with bytes 24-27 poked back to the marker's
       counter;
     - **the counter only:** an in-place tamper, with `os.stat` patched to round ctime to 1 s;
     - **head only:** a marker forged with the right counter and a wrong head;
     - **inode:** a file renamed over the ledger.
   - **Writers racing, with a raw writer as B** (M1, Rio Grande): A commits, B is a raw SQL `UPDATE`, then A's
     post-commit read sees c+2 and writes no marker. The next reader runs the full check.
   - **Locks survive the marker read** (M2): process A holds `BEGIN IMMEDIATE` and runs the key read, and process B
     still gets "database is locked". The same holds inside a read transaction.
   - **WAL** (M3): with the ledger switched to WAL, or a non-empty `-wal` present, every `state()` runs the full check.
   - **No duplicates:** two concurrent frames run one full check (a counter hook, `full_checks`, N8).
   - **A killed writer** between COMMIT and its marker leads to one full check.
   - **Readers write nothing:** `verify` and test_u9 still find only `permissions.db` after a full check.
   - **Late connections:** StateRows refuses when the file changed after the check.
5. **Old ledgers, the gate, `verify`, `rebuild` and version skew** (D5-D8). Tests:
   - an unstamped ledger reads `closed` under enforce, and `gate enforce` is refused on it;
   - `rebuild` stamps, reports a mismatch without refusing, and writes no per-append marker;
   - the folder tests are updated;
   - old code refuses a stamped ledger (`SCHEMA_VERSION`);
   - the skew message names both seqs.
6. **The fixtures and budgets** (D8, D9):
   - `restamp_projection` in `synthetic_ledger`, `add_records_by_sql`, `add_revoked_records`, `detach_last_collect`
     and the U24 reference ledger;
   - the whole Engram suite passes;
   - budget tests for the rare path and the match path, with the Pi line in the U24 file.
   - **A loop test (S2):** two writers and a reader for 60 s, with full checks at most 1% of reads.
7. **`ENFORCE_WAITS = None`,** its own commit (D6).

## Checks before review

The whole Engram suite passes, plus `make mutants SPEC=` with each mutant dying on its own test's assert:
- the key drops ctime, the counter, head or inode (one test each, Task 4);
- the parts comparison is skipped (the part-named assert);
- `_project` hashes bound values;
- an update re-evaluates its `WHERE`;
- `integrity_check` isn't run;
- the reader reads the header with `open()`;
- the WAL pin is skipped;
- a writer writes the marker without the c+1 check.

The Pi budget test passes on the Pi.

## Deploy

Merging changes nothing live. Restart every Engram process after the merge (D8). The Pi has no ledger, so the live
steps are Andy's, in the one sitting the crossing plan names:
- `migrate`, which creates a stamped ledger;
- register `remote-stores` at outside-home;
- `gate enforce`.

## Risks

- **Two compensating changes** whose hash sums cancel. That's negligible for accidental tears (D2).
- **A filesystem with coarse ctime** could pair a same-tick `cp` with a matching counter and head. That's three fields
  at once. The restore runbook stops every process first.
- **Writer drift reads as a tear.** The suite-wide conftest check and the drift rules are the guard, and `rebuild` is
  the live recovery.
- **Descriptors kept open** grow by one per file replacement in a process's life, which is bounded by restores.

## Plan re-check: decided items (approved)

The same fresh reviewer re-read revision 3 and gave **APPROVE WITH CHANGES**
([re-check](../reviews/2026-11-03-projection-digest-plan-recheck.md)). M1, M3, S2, S3, S5, S6, S9 and N1-N8 are closed.
It said a third plan review isn't needed, since the build's review can check these. Each remaining item is decided
here, and each overrides the text above where they differ.

**Must-fix 1: the descriptor closes when no connection needs it.** The reviewer confirmed it's sound against SQLite's
locking, but one descriptor per ledger ever read would exhaust a test process's limit (about 1,180 tests; the Pi's
default is 1,024, the Mac's 256).
- **The count:** the process keeps one descriptor per (dev, inode), with a count of this process's open SQLite
  connections on that inode, StateRows and LogTimes included.
- **When it closes:** only when the count reaches zero. Then the process holds no SQLite lock on that inode, so closing
  drops nothing.
- **How it opens:** with `O_RDONLY | O_CLOEXEC`, so hooks and subprocesses don't inherit it (Rio Grande, ee2d95a3). It's
  `fstat`ed after opening and must match the path's (dev, inode).
- **The test:** 2,000 ledgers opened and closed in one process, under `RLIMIT_NOFILE` 256.
- **Risks, named for `lsof` readers:** after a restore replaces the inode, a still-open descriptor pins the deleted
  file's space until that process's last connection on it closes.

**Must-fix 2: late connections accept a verified change.** StateRows and LogTimes still require the checked (dev,
inode).
- A changed counter is **accepted when the current key matches the in-process memo or the marker,** after one 50 ms
  re-read. That's an ordinary verified write landing mid-build, which today's lazy reads allow by design
  (permission_ledger.py:691-693).
- Only an unverified change refuses.

**M4: the inode test forges the marker,** as the head test does: right counter, ctime and head, and a wrong inode. A
renamed file also changes ctime, so a rename-over would let the "drops inode" mutant live.

**S1: writers wait out a rare check.**
- A full check holds SHARED for its whole length, which is about 3.8 s on a loaded Pi. So `_append`'s busy timeout is
  12 s, against `BUSY_MS`'s 5 s elsewhere, and the Pi's rare-path budget stays at 8 s.
- New readers can queue behind a pending writer during a rare check. That's accepted for a rare path, and named in
  Risks.

**S4: rebuild.**
- **Task 0c** measures rebuild at the large shape before and after this change, and sets a rebuild budget of the
  measured time plus 25%. `REBUILD_LEDGER_S` is the eligible set's budget, not rebuild's.
- **Rebuild and migrate** own a fresh file, so they skip the key protocol entirely, with no memo, marker or key reads
  per append. They run one full check at the end.

**S8: the suite-wide conftest check** runs only on ledgers under 5,000 projected rows, and is off in the budget tests
(an environment flag), so U24's 811,000-append rebuild isn't recomputed per append.

**Writers' first step** (should-fix) gets the same 50 ms marker re-read before it falls back to a full check.

**`SCHEMA_VERSION`** (should-fix):
- New code opens "1", which is unstamped, `off` and `shadow` only, and "2".
- **The way back,** if this branch is ever reverted: scripts/unstamp_ledger.py sets the version to "1" and deletes the
  `projection*` keys and the marker. It's a writing act on the ledger, so it's the person's terminal yes, and it's
  tested.

**Nits:**
- A writing open **tries** `PRAGMA journal_mode=DELETE` and carries on if the database is locked. The WAL pin still
  forces a full check until the switch succeeds.
- After the writer's three tries, it raises a new `LedgerBusy`, not `LedgerUnreadable`, since callers read the latter as
  a torn ledger.
- The unstamped cause text gives the whole recovery: "run `engram-permissions rebuild`, then the move step it prints".
- A `meta` upsert subtracts the old row's hash before adding the new one.

### Builder findings (Tardis, during the build; approved by the coordinator)

**Writers' step 2 takes a verified change under the lock.** As first approved, step 2 rolled back on any key changed
since step 1. With two writers in contention that fails `test_rf5_two_writers_keep_one_chain` 3 runs in 10 with
`LedgerBusy`.
- **Measured** (two spawned writers, 50 appends each, tries counted with the limit raised, three runs): most appends took
  one try; the multi-try ones took 2, 2, 3, 2 and 6. One append in 300 needed more than three, and about one in fifty
  needed more than one.
- **The cause:** the other writer commits between step 1 and the lock, so the key differs although its state is
  verified (its marker, or this process's memo).
- **The fix:** under the write lock, a changed key is taken when this process's memo or the marker holds it as
  verified, after one marker re-read 50 ms later while holding RESERVED. RESERVED blocks no reader, so the writer that
  made the change can still read its key and write its marker. Only an unverified change rolls back to step 1, and no
  full check ever runs under the lock (S1). The three tries and `LedgerBusy` stay. It's the rule Must-fix 2 gave
  StateRows and LogTimes.
- **After the fix,** in a prototype: all 300 contended appends took one try, with no full check. The suite's test (two
  writers, 150 appends each) asserts no `LedgerBusy`, no full check under the lock and every append in one try; under
  the old rule it failed 3 runs in 3 (2 `LedgerBusy` each). A mutant that drops the acceptance must die on it.

**Other changes from the text above:**
- **The marker** is JSON with sorted keys and no spaces, not `canonical_json`, which refuses integers past 2^53: dev,
  inode and ctime_ns are 64-bit.
- **The marker write ignores every OS error,** not only EACCES and EROFS (EDQUOT, ENOSPC too), so a committed act never
  reports a failure; a missing marker costs the next reader one full check.
- **The authorizer also refuses deletes on `meta`,** which is one of the digest's parts.
- **`_blank` runs the full check on the new, empty file and keeps its key in the memo,** so a new ledger's first append
  needs no 50 ms wait.
- **Fresh mode lands in Task 4,** with the key protocol: rebuild and migrate build their files with no key, memo or
  marker per append. Their end-of-build check and marker stay in Task 5.
- **The restamp list** moved from Task 6 to Task 3, where the suite-wide check needs it, and grew beyond the fixtures
  named: `lazy_state` (test_permissions_reference), `_write_world`, `_with_agent` and `_member_world`
  (test_permissions_memory_rows). Two `should_fix_3` tests restamp after their tamper, so they still test the writer's
  tail checks, which a digest that holds the torn tables can't see.
- **A connection collected unclosed** releases its count at once but leaves its descriptor's close to the next hold or
  release, since its own SQLite close may still be running.
