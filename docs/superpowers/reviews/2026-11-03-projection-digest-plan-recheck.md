# Re-check: the projection digest plan, revision 3 (b837240d)

**Verdict: APPROVE WITH CHANGES.** The safety design now holds: the key is read under the lock, the writer checks for
c+1, and WAL is pinned out. What's left is mostly about availability. Fix the two Must-fixes before the build; its
review can check them.

**By:** the same fresh reviewer (Claude, on Tardis).

## Each earlier item

**Closed:**
- **M1:** the c+1 rule, the two stats and the raw-writer race test (lines 106-135, 218-219).
- **M3:** the bytes 18-19 and `-wal` pin (:99-104).
- **S2, S3, S5, S6, S9.**
- **N1-N8.** The script's docstring is fixed.

**Closed, with a new issue:**
- **M2:** `pread` keeps the locks, but the descriptor cache leaks (new Must-fix 1).
- **S7:** the `meta` part and the log count are in, but StateRows' check is too strict (new Must-fix 2).

**Mostly closed:**
- **M4.** The inode test (line 217) doesn't isolate inode, because a file renamed over the ledger also has a new ctime,
  so the "drops inode" mutant survives. Forge that marker as the head test does.
- **S1.** The writer's full check is now outside the write lock. But every full check runs inside a read transaction,
  so it holds SHARED for its whole length. A committing writer then waits for EXCLUSIVE, up to `BUSY_MS` = 5 s
  (permission_ledger.py:46). It holds PENDING meanwhile, so new readers queue too. D9 allows 8 s on the Pi (:181),
  and Rio Grande's loaded run is already at about 3.8 s. Keep the rare path under 5 s with margin, or raise writers'
  busy timeout above it.
- **S4.** D9 cites `REBUILD_LEDGER_S` (:185), but that's the eligible set's 6 s (test_permissions_pi_budget.py:108).
  Nothing times a ledger rebuild, so set a real budget. Rebuild and migrate builds should skip the key steps entirely,
  not just the marker: the file is private until its rename.
- **S8.** The autouse check recomputes the whole digest after every `_append`, 811,000 times in U24's rebuild, and it
  skews the budget tests. Limit it to small ledgers.

## New

**Must-fix 1: the never-closed descriptor leaks one per distinct ledger file, not one per restore** (:93-95, :270).
- **Locking:** it's sound. `open` changes no lock, and `pread` inside SHARED or RESERVED reads a stable header.
- **The leak:** every ledger file a process reads keeps a descriptor, and its disk space, until the process exits. One
  pytest process builds a ledger in most of about 1,180 tests, past the Pi's default limit of 1,024 descriptors and
  the Mac's 256. So the suite fails there, as would a long-lived service that opens many homes
  (`imprint_filter.py:511`).
- **Fix:**
  - Count the open `_connect` connections per inode, including StateRows and LogTimes, which close by finalizer.
  - Close the descriptor only when that count reaches zero, since no lock of this process can remain then.
  - After opening, `fstat` the descriptor and keep it under the (dev, ino) it really has.
  - Test: 2,000 ledgers in one process with `RLIMIT_NOFILE` set to 256.

**Must-fix 2: StateRows' check refuses ordinary concurrent writes** (:119-124).
- **The problem:** requiring "the counter the check saw" fails every lazy read after any verified append. Today such
  reads are allowed by design: the rows up to `seq` read the same later (permission_ledger.py:691-693). Under enforce,
  every MCP write landing during a daemon build or a `perform` would fail that frame or act.
- **Fix:** accept a changed counter when the current key matches the memo or a marker, with the 50 ms re-read. Refuse
  only an unverified change.

**Should-fix:**
- **The writer's step 1 has no 50 ms re-read** (:127). A writer sent back by step 2 usually lands in the gap before the
  winning writer writes its marker, and then runs a full check. Give writers the readers' re-read.
- **`SCHEMA_VERSION`** (:166-170). Say that new code opens both "1" (unstamped, `off` and `shadow` only) and "2".
  Otherwise, raising the constant breaks D5's "works as today". Also, reverting the branch leaves every "2" ledger
  unreadable, so name a way back.

**Nits:**
- **WAL to DELETE:** `PRAGMA journal_mode=DELETE` on a WAL ledger with any reader open raises "database is locked"
  after the timeout (tested). A writing open should try it and carry on if it fails.
- **Busy retries:** after three tries, raise a busy error, not `LedgerUnreadable`, which callers read as torn.
- **Unstamped ledgers:** `rebuild` writes elsewhere, so the cause text should give the move-into-place step with
  processes stopped.
- **`meta` writes:** an upsert should subtract the old row first, and the stamp in `_blank` includes `ledger_id` and
  `schema_version`.
