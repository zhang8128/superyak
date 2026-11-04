# Review: the projection digest plan (revision 2, 6bebafea)

**Verdict: REVISE.** D2 and D3 are sound. D4's marker is unsafe as written, and four of the planned mutants can't
die.

**By:** a fresh reviewer (Claude, on Tardis) who took no part in writing the plan.

**What I checked:**
- **Citations:** they hold, except where noted below.
- **Task 0:** it reproduces on an Intel N150: `state()` 0.36 s, the recompute 0.99 s, `integrity_check` 0.15 s.
- **SQLite 3.46.1, tested here:** the counter at offset 24 rises once per commit in DELETE and MEMORY mode. It stays
  put on a rollback, an empty transaction, a no-op `CREATE INDEX IF NOT EXISTS` and a same-value update.
- **WAL:** no code puts the ledger in WAL.

## Must-fix

**M1. The plan doesn't say where the marker's fields come from, and the natural reading is unsafe** (lines 116-119).
- **Writers:** "After COMMIT, the writer writes the marker" invites reading the counter and stat after COMMIT. A raw
  write (the xfail's `_sql`) can land in between. It moves the counter but not `head`, so the writer records the
  tampered state as verified, and every later reader serves it.
- **Readers:** a reader that stats outside its read transaction, or after a rename-over, pairs a new inode with the
  old file's counter.
- **Fix:**
  - Writer: read counter c inside `BEGIN IMMEDIATE`. After COMMIT, run `BEGIN` and a SELECT, then read the counter,
    the head and the stat. Write the marker only if the counter is c+1 and the head is its own.
  - Reader: stat before connecting and inside the transaction, and require the same (dev, ino).
  - Test it with a raw `UPDATE` as the racing B.

**M2. Reading "the header's 4 bytes" with `open()` drops SQLite's locks.** Any `close()` on the file releases all of
the process's POSIX locks on it.
- **Tested here:**
  - With `BEGIN IMMEDIATE` held, an `open()`/`close()` let another process take RESERVED.
  - Inside a read transaction, it let another process commit.
- **Why it matters:** the daemon keeps StateRows and LogTimes connections open in threads (permission_ledger.py:694-695),
  and server.py writes (:2512-2522). This risks torn reads and two writers at once.
- **Fix:** read page 1 through the connection, with `sqlite_dbpage` (compiled in here; check the Mac's Python).
  Failing that, use `os.pread` on a descriptor that's never closed.
- **Test:** hold a write lock, run the marker read, and assert another process still sees "database is locked".

**M3. Nothing pins the rollback journal** that line 108 relies on.
- **The hole:** `PRAGMA journal_mode=WAL`, run from any tool, persists. Under WAL a commit leaves the counter, size and
  ctime unchanged (tested here), so a stale marker matches the new state.
- **Fix:** require header bytes 18 and 19 to be 1, and no non-empty `-wal`. Otherwise always run the full check.

**M4. The mutant plan can't be met.**
- **(a) Racing writers:** the test (lines 185-187) kills neither "drops head" nor "drops the counter" on its own,
  because the other field still mismatches. Head is nearly an equivalent mutant: drop it, or test it with a poked
  counter.
- **(b) The `st_mtime_ns` mutant (line 203)** is stale: the key has no mtime.
- **(c) Skipping the parts comparison** is an equivalent mutant while the whole is compared, unless the error names the
  table.
- **(d) The acceptance test** returns on any `LedgerUnreadable` (test_permissions_premerge_fixes.py:217-218). A stale
  fixture digest passes it.
- **Fix:**
  - ctime only: `cp -p` a tampered copy over the ledger, with its bytes 24-27 poked back.
  - The counter only: an in-place tamper, with stat monkeypatched to round ctime to 1 s.
  - The acceptance test: `match="projection digest"`, naming `collection_members`, plus a control without the tear.

## Should-fix

- **S1. The writer's full check runs under the write lock.** It can take 8 s on the Pi, and `BUSY_MS` is 5 s (:46).
  Check before `BEGIN IMMEDIATE`, then re-check the key under the lock.
- **S2. "Rare" isn't shown.** A writer in the busy handler (which sleeps 1-25 ms), or a frame, that lands between
  another writer's COMMIT and its marker write runs a full check.
  - Don't fsync the marker.
  - Retry briefly before a full check.
  - Add a loop test with two writers and a reader that counts full checks.
- **S3. Version skew.** Long-lived MCP servers on old code keep writing (server.py:2512-2522), leaving `projection`
  behind `head`, so every new reader reads closed. Bump `SCHEMA_VERSION` with the stamp (:579-583), or require
  restarts. Name the cause: "projection seq N behind head M".
- **S4. Rebuild.** It replays about 811,000 appends, and each would write the marker. Tests at
  test_permissions_ledger.py:323, :337 and :355 pin the folder's contents and the `os.replace` calls.
  - Skip the marker in builds, and run one full check at the end.
  - Budget rebuild in D9.
  - D7 must report a mismatch, not refuse: rebuild is the recovery path (`_CUT`, :137-142).
- **S5. Readers writing a file.** test_u9 (test_permissions_ledger.py:184-192) asserts `.engram` holds only
  `permissions.db`, and R48 lets agents run `verify` because it writes nothing.
  - Make the reader's marker best-effort, under a unique temporary name, ignoring EACCES and EROFS.
  - Exempt `verify` and `check`.
  - Update the U9 test.
- **S6. D5 blesses an old ledger's existing multi-row tear.** Stamp only after matching a replay, or state the
  residual.
- **S7. Still open:**
  - `ledger_log`'s middle rows, which LogTimes reads lazily: check that `COUNT(*) … NOT INDEXED` equals the top seq.
  - StateRows connecting after the check (:694-695).
  - Meta's `gate` and `admins`, which rely on meta staying one page: assert that with `dbstat`.
- **S8. The property test needs a random-act generator that doesn't exist,** and no real act makes affinity convert a
  value.
  - Add an autouse conftest check after every `_append`.
  - Add hand-made bodies: an int into TEXT, `"5"`, 1.5, a bool, a dict and the salt.
  - Guard deletes with `set_authorizer`, exempting `detach_last_collect` (permissions_budget_ledger.py:109).
- **S9. D9.**
  - A `state()` on the full-check path costs about 1.5 s (0.36 + 0.99 + 0.15), leaving the 1.5 s budget no headroom.
    Say what it times.
  - "D9's fallback" (line 222) isn't defined.
  - The Pi line is a guess.

## Nits

- There are 17 projected tables, not sixteen. `proposals` is read on demand (:114).
- Task 1's BLOB case for `canonical_json` contradicts D2. Leave the protocol function alone.
- D2 should name the REAL tag (the script uses `r`) and the table framing. Map `sqlite3.Error` to `LedgerUnreadable`.
- The script's docstring (lines 9-10) says SHA-256 of canonical JSON, but line 68 is BLAKE2b.
- `_project` should refuse body meta setting `projection*`, as it does for `head` (:947).
- `check_gate_mode(mode)` (:2237) sees no ledger, and D5 makes D6's rule almost unreachable.
- `_forget_ledger` (permission_cli.py:1063) should remove the marker.
- A builder would still invent:
  - the marker's name and format;
  - a hook that counts full checks;
  - what `_append` does with no `projection`;
  - a lock so FRAMES_AT_ONCE=2 frames don't run duplicate full checks.
