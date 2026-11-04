# Section 2 review: tardis/projection-digest at 3562a6e1 (fresh Pi reviewer)

Saved whole from all hands, message b6a50b452cd743178976d201fbc7082c (posted by Rio Grande), the moment it landed.
**Verdict: changes required.** 2 Must-fix, 6 Should-fix, 3 nits. The reviewer says a re-check of M1 and M2, with their
probes re-run, is enough.

**By:** a fresh Pi reviewer (Claude, on the Pi `smart`), who took no part in the plan or the build. It read the whole
diff by area, ran the Pi suites and U24's Pi-only test, timed rebuild before and after, and ran probes and four
mutants in scratch copies under pd-review/. The checkout is untouched, and `~/.engram` was never touched.

**In short:** the digest and the key protocol are sound. It found no way for a torn copy to read whole through
`state()`, and nothing that drops SQLite's locks. Two small things block the merge, each with a probe that fails on
3562a6e1 and a fix of a few lines.

## Strengths (summary)

- **The digest covers the whole projection:**
  - all 17 tables and every column, plus `meta`;
  - an injective, length-framed encoding, with known-answer tests;
  - `NOT INDEXED` scans, the log count and `integrity_check`.
- **The incremental updates keep a mismatch:** an existing tear stays visible through later appends.
- **The key protocol is right:**
  - the key is read inside SHARED or RESERVED, with the inode pinned and a stat before and after;
  - the c+1 rule and `head` gate the marker;
  - the WAL pin forces a full check;
  - every failure raises `LedgerUnreadable`.
- **SQLite's POSIX locks are safe:**
  - the header is read with `pread` on an `O_RDONLY | O_CLOEXEC` descriptor, checked by `fstat` and reference-counted per inode;
  - `make_private` uses `O_EXCL` before any connection;
  - `_fsync_file` touches only the `.rebuilding` file;
  - the marker is a different file.
- **The builder's two findings are sound and inside the design,** each pinned by a test that kills its mutant.
- **The tests are strong:**
  - each key field is isolated;
  - the lock test uses a second process;
  - 2,000 ledgers run under `RLIMIT_NOFILE` 256;
  - a killed writer is covered, and so is the 60 s loop;
  - the acceptance test has a control;
  - `ENFORCE_WAITS = None` is its own commit (bdf24a41).

## Must-fix

### M1. A torn `meta` index page makes the gate read `off` on a ledger at `enforce`

**Where:** permission_ledger.py:1247 (`Ledger.meta()`), called by `effective_gate` at :2896-2897 and by `house_mark` at
:2955.

**The cause:** `SELECT key, value FROM meta ORDER BY key` runs as `SCAN meta USING INDEX sqlite_autoindex_meta_1`.
`effective_gate` decides the mode from that read and the head check alone. No reader checks the digest before it,
and under `off` nothing checks it after: the daemon's `_ledger_side` never calls `state()`, and server.py's
`_lane_notes` returns at once.

**The probe** (pd-review/probe_meta_index.py):
1. Raise the gate to `enforce` on a fresh ledger (its first raise inserts `gate` and `gate_raised`).
2. Write page 3, the `meta` autoindex root, back as it was before the raise.
3. `effective_gate` now gives `Gate('off')`, and `meta()` shows neither key, while `NOT INDEXED` shows them.
4. `state()` refuses, but under `off` nothing calls it, so every house is served by the legacy path.

That's the torn-index-page class the branch says it closes, failing open all the way to `off`.

**The fix:**
- Read `meta` `NOT INDEXED` in `Ledger.meta()`.
- Do the same in the key protocol's meta reads:
  - `_read_key`'s head;
  - the version reads in `_base_key` and `_parts`;
  - `_differs_from_replay_later`.
- Add the probe as a test.

**Optional follow-up:** on a stamped ledger, `effective_gate` checks the key as `state()` does (about 1.5 ms on a memo
match).

### M2. `rebuild` refuses a ledger whose log is whole but one table page is malformed

**Where:** permission_ledger.py:2052 calls `_differs_from_replay_later` (:1595-1608) before the replay. It runs
`projection_now`, which reads every projected table, where main's rebuild read only `ledger_log`. D7 says rebuild
"reports whether the old tables matched and never refuses".

**The probe** (pd-review/probe_rebuild_malformed.py): E1's county ledger, with an uncollect, and `collection_members`'
root page overwritten with 0xFF.
- `verify()` returns None, so the chain is whole.
- On 3562a6e1, `rebuild` raises `DatabaseError: database disk image is malformed`, and the CLI says "the ledger cannot
  be used", exit 1.
- Main's rebuild completes.

**The fix:**
- Catch `sqlite3.Error` from `_differs_from_replay_later`.
- Set `rebuilt_differs` to say the old tables couldn't be read, with the error.
- Replay anyway, and print it in the CLI.
- Add the probe as a test.

## Should-fix

- **S1. `verify` says "which every reader checks" (permission_cli.py:755), but `imprint_filter` reads outside a verified
  read.** The reads are `check_owner` → `store_row` (:522), `cosubjects_of` (:534) and `Refusals` (:564). A tear that
  loses a deny's row plans an imprint without it. This is older than the branch, and privacy-relevant.
  - **The fix:** correct the sentence, and file a board item to run those queries inside one verified read
    transaction.
- **S2. engram/CLAUDE.md is stale** at line 262 and lines 278-281. It should say:
  - `enforce` needs a stamped (version 2) ledger, and an unstamped one reads `closed`;
  - the marker `permissions.verified` exists;
  - the recovery is `rebuild`, then the move with every Engram process stopped;
  - which readers check the digest.
- **S3. `LedgerBusy` surfaces as a traceback.** `permission_cli.main` (:1573) and server.py's `permit` (:2518-2523)
  don't catch it. It should read "the ledger was busy; nothing was written; try again".
- **S4. At U24's reference shape, a rare check outlasts the writers' wait.** On the loaded Pi, the full check takes
  19-22 s (274 MB, 1.21 million projected rows), against `APPEND_BUSY_MS` 12 s and the daemon's `LEDGER_BUSY_MS` 5 s.
  An append fails at COMMIT with nothing written, and frames time out.
  - **The fix:** raise `APPEND_BUSY_MS` above the reference shape's rare path with margin, or scale it by file size.
    Add the reference shape to D9's Pi line, and name the cost in Risks.
- **S5. The Pi's D9 append bound flakes:** 2.15 ms once in 6 runs, since it's a difference of medians taken in turn.
  - **The fix:** interleave the appends, or give the bound a margin. Record the Pi's D9 line and its rebuild budget in
    the builder findings.
- **S6. Rebuild is 86% slower on the Pi** (Tardis: 46%).
  - **The fix:** in fresh mode, carry the parts in memory and write `projection*` once at `_finish_fresh`. This is
    optional.

**Nits:**
- `_mark_moved` (:937) should compare size too.
- `_Conn.close` (:831-838) should release its count only after a successful close.
- The unstamp script's text could say that a gate at `enforce` then reads `closed`.

## Mutants (in scratch copies)

| Mutant | Dies on |
|---|---|
| A: the header read by `open()`/`close()` (:963) | `test_4_the_key_read_keeps_sqlites_locks` alone, at :525 (`'wrote' == 'database is locked'`) |
| B: the marker written without c+1 (:1238) | `test_4_a_raw_write_between_a_writers_commit…` alone, at :491 |
| C: step 2 rolls back on any changed key (:1484) | `test_4_two_writers_in_contention…` at :772 (`busy == 0`), and `test_rf5_two_writers_keep_one_chain` dies by an escaped `LedgerBusy` |
| D: the late lookup after its read transaction (:1187-1195) | `test_6_two_writers_and_a_reader…` at :1091 (111 of 1,805 reads refused); the loop test is its only pin |

## Pi measurements (loaded, load 6-9; the embedder holding about 3.6 of 4 cores)

- **The suite** (permission, projection, digest, ledger): 1,133 passed, 31 skipped, 0 failed, in 87 min. The loop test
  passed (65 s).
- **D9, the Pi line** at Task 0's shape, six runs:

| Measurement | Budget | Six runs | Median |
|---|---|---|---|
| rare path | 8 s | 4.49, 5.03, 4.36, 4.37, 5.64, 5.37 s | 4.8 s |
| memo match | 2 ms | 1.69, 1.72, 1.20, 1.44, 1.41, 1.35 ms | 1.4 ms |
| append over no digest | 2 ms | 0.98, **2.15**, 0.83, 1.83, 1.95, 0.44 ms | 1.4 ms (one failed) |

- **Rebuild** of U24's reference ledger (811,000 rows, 274 MB): main 574.1 s, 3562a6e1 1,070.5 s (+86%), with peaks of
  55.2 and 55.8 MB, within spec 15's 69.9 MB. The Pi's rebuild budget by the plan's rule is about 1,340 s.
- **The rare path at the reference shape** (1,210,657 projected rows): `state()` with the full check 20.6-22.1 s.
  Split: `projection_now` 9.6-10.2 s, `integrity_check` 1.8 s, the log count 0.1 s. `state()` on a memo match takes
  2.1 s, which predates the branch.

## Notes

- **The two-row tear:** refused.
- **A torn index page:** refused by `state()`, with the gate as M1.
- **`cp -p`:** refused, since ctime differs.
- **A WAL switch:** a full check until a writing open switches the ledger back.
- **A crash between COMMIT and the marker:** one full check.
- **Racing writers, a raw one included:** refused by the next reader's full check.
- **A restore:** a full check.
- **A deliberate tamper:** out of scope (D2).
- **Residual windows the runbook covers:**
  - `_check_late` (:1190) compares only the counter;
  - StateRows' and LogTimes' lazy reads after `_late` aren't keyed;
  - coarse ctime.
- **Older than this branch, for a follow-up:** a whole older backup from before the first gate raise, restored while the
  houses are marked, reads `off`. Cross-check in `effective_gate`: a house carries this ledger's id, but the gate was
  never raised, so it reads closed.
