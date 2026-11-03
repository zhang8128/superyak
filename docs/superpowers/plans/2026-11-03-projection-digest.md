# Plan: the permission ledger's projection digest

**By:** Tardis, 2026-11-03. **Board item:** `build:permissions-projection-digest`. **Revision 2.**
- Rio Grande's three drift rules are in D3.
- Task 0, measured on Tardis, changed D2's encoding and replaced revision 1's mtime-keyed process cache with a verified
  marker (D4).

**What it closes:** R48's follow-up in docs/superpowers/plans/2026-10-25-permissions-by-place.md (line 167), Serenity's
re-check N1, and pre-merge item 5. `ENFORCE_WAITS` (permission_ledger.py:2070-2074) blocks `gate enforce` until this
lands.

**Who's waiting on it:** the crossing spec's stage 2 (tardis/crossing-spec) needs a publisher home at `enforce`. So does
any house that wants `enforce`.

**This is safety code** (what the permission ledger serves). It gets a test-first build, a fresh Pi reviewer, and each
partner's yes before merge, under law section 2.

## The hole, in one paragraph

R48's tail checks catch a copy torn in one row per column. But a tear across several rows of one column, or a torn
index page, can still read whole. The ledger's own example is the strict xfail at
engram/tests/test_permissions_premerge_fixes.py:204-222:
- Andy uncollects m2 and m3 in one act;
- a tear keeps m3's removal and loses m2's;
- the column's highest seq is still the act's, so every tail check passes;
- m2 reads as a member again.

Under `enforce`, a lost removal or revocation would serve what it took away.

## What the code does today (read at main b7d91462)

- **Tables:** sixteen projected tables, listed with their columns in `permissions._COLUMNS` (permissions.py:374-397),
  plus `meta` and `ledger_log` (permission_ledger.py:48-99). Rows are only inserted, or updated to set a later seq
  column, and never deleted (plan line 167). One column is a BLOB: `places.pseudonym_salt` (:56).
- **`_append`** (:840-879), all under `BEGIN IMMEDIATE`, then COMMIT, or ROLLBACK on error:
  1. checks the bounds;
  2. runs `_tail_problems`;
  3. inserts the log row;
  4. runs `_project`, which applies inserts and updates, and raises when an update matches no row (:969-970);
  5. sets `meta.head`.
- **`state()`** (:660-703) reads twelve tables whole and four per object through partial indexes (`_PER_OBJECT`, :112;
  `_SPECS`, :241-248), then runs the R48 checks (:791-816). Nothing times it.
- **Opens:** no process keeps a ledger open. The daemon opens one and calls `state()` on every frame under shadow or
  enforce (lighthouse_daemon.py:871-878), and server.py opens per tool call. So a check run on every `state()` would
  run per frame.
- **`rebuild`** (:1306-1359) replays the log and compares log digests, never tables.
- **Helpers:** `canonical_json` (lighthouse_protocol.py:78) has no case for bytes (:143).

## Decisions

**D1. Where the digest lives.** Two new `meta` keys, written in `_append`'s transaction beside `head`:
- `projection`: `<seq>:<64 hex>`;
- `projection_parts`: canonical JSON of each table's row count and sum.

The log body and the chain format don't change, so no existing ledger's digests move.
- A meta page torn old already reads as unreadable, since `head` isn't the log's last row (R48).
- So a torn copy can't pair an old `projection` with a new head.

**D2. The digest.**
- **A row's hash:** BLAKE2b-256 of an explicit encoding. That's the table name, then each value in `_COLUMNS` order as a
  type tag (`n`, `i`, `s`, `b`), a decimal length, `:`, and its bytes. This is revision 2's change, measured in Task 0:
  canonical JSON with SHA-256 took 3.6 s on x86 at the large shape, and this encoding takes 1.0 s. It also needs no
  BLOB case in `canonical_json`.
- **A table's part:** its row count, and the sum of its rows' hashes mod 2^256, as an additive multiset hash. Order
  doesn't matter, and an insert or update changes it by a delta.
- **The whole:** SHA-256 of `canonical_json([[table, count, sum_hex] …])`, in `_COLUMNS` order.
- **Why additive:** it detects accidental tears. Anyone who can write the file can rewrite anything anyway, so this
  isn't an adversarial MAC, and the plan says so.

**D3. The writer keeps it incrementally, hashing only what SQLite holds** (Rio Grande, all hands a5598b76). Any drift
from the reader's recompute reads as a tear and closes the ledger, so:
- **Hash what SQLite returns, not what Python bound.** Column affinity converts values on the way in: an int bound to
  a TEXT column comes back as `'1'`. So after each insert, `_project` re-reads the new row by `lastrowid`, in the same
  transaction, and hashes that.
- **Updates go by rowid.** `_project` captures the rowids its `WHERE` matches before an update, subtracts those rows'
  hashes, applies the update, then re-reads **those rowids** and adds their hashes. It never re-evaluates the
  `WHERE`, since an update that changes a column its own `WHERE` tests would lose rows.
- **Deletes:** no projection table loses a row today. A test fails when a `DELETE` reaches a projection table outside
  `_project`, and `_project` subtracts any row it deletes, so that stays true.
- Only changed tables' parts change. The new `projection` and parts are written in the same transaction.
- **Cost:** one re-read per inserted or updated row. That's measured in Task 6.

**D4. The reader checks fully only when the file changed in a way no verified writer recorded.**

Task 0 measured, on x86 at the large shape (236,389 rows, 28.7 MB):

| Step | Time |
|---|---|
| `state()` | 0.35 s |
| the full recompute | 1.0 s |
| `integrity_check` | 0.15 s |

The Pi will be several times slower. Every caller opens per call, and the daemon calls `state()` on every frame. So a
full check after every write, which revision 1's per-process cache keyed on mtime amounted to, is far over budget.
(Hooks never open the ledger.)

**The full check,** before any row is served:
- recompute every table's part by a `NOT INDEXED` scan;
- compare the parts and the whole with `meta`;
- run `PRAGMA integrity_check`, which catches a torn index page that the partial-index reads would trust.

Any mismatch, or any answer but `ok`, raises `LedgerUnreadable("the projection digest …")`, so the ledger fails
closed.

**A verified marker,** `permissions.verified` beside the ledger, mode 0600, written atomically (temporary file, then
rename). It records the file state that was last verified, as (`st_dev`, `st_ino`, `st_size`, `st_ctime_ns`, the
header's file change counter, `head`).
- **The change counter:** the ledger runs SQLite's rollback journal, so every commit by any connection increments the
  4-byte counter at header offset 24.
- **ctime:** a `cp` over the file, or a rename onto it, changes ctime, which user tools can't set.

**How it's used:**
- **Readers:** `state()` stats the file, reads the header's 4 bytes and `head`, and compares them with the marker. A
  match serves with no full check. A mismatch or a missing marker runs the full check, and on success writes the
  marker.
- **Writers:** `_append` runs only from a verified base. If the marker doesn't match before its write, the full check
  runs first. After COMMIT, the writer writes the marker for the new state, since it computed the digest incrementally
  from that verified base. If another commit lands between its COMMIT and its stat, the marker it writes won't match
  the next reader's view, and that reader runs one full check. That's safe, just slower.
- **Why this catches the threats:**
  - **The xfail test,** an in-place SQL tamper in the same process, increments the change counter, so the full check
    runs and refuses.
  - **A restored or copied file** has a new inode or ctime.
  - **A crash** between COMMIT and the marker write leaves a mismatch, which costs one full check.
- **What the marker isn't:** a security boundary. It sits beside the ledger, under the same user. It guards against
  accidental tears, as the digest does (D2).

**D5. Ledgers made before this.**
- **A writing open** computes and writes `projection` and `projection_parts` once, under the write lock, after R48's
  checks pass. That's the way a writing open already adds the partial indexes (:593-599).
- **A read-only open of a ledger with no `projection`** reads as today under `off` and `shadow`. Under `enforce`,
  `effective_gate` reads `closed`, with the cause "no projection digest".

**D6. `enforce` requires the digest.**
- `ENFORCE_WAITS` becomes `None`, in its own commit, so it can be reverted alone.
- `check_gate_mode` refuses `enforce` on a ledger with no `projection`.
- The tests that put the old refusal back (test_permissions_premerge_fixes.py:225-270) become tests of this rule.

**D7. `verify` and `rebuild`.**
- `engram-permissions verify` stays read-only and also reports the recomputed parts and whole against `meta`.
- `rebuild` compares the rebuilt ledger's recomputed digest with the old ledger's recompute. That's table equality,
  which it never asserted.

**D8. Fixtures that write tables by SQL.** A test-only helper, `restamp_projection(path)`, recomputes and writes both
keys. It's used by:
- `synthetic_ledger` (permissions_memory_support.py:20-67);
- `add_records_by_sql` (:71);
- `add_revoked_records` and `detach_last_collect` (permissions_budget_ledger.py:90, :109);
- the U24 reference ledger.

The tear tests never call it, since a tear must stay a tear.

**D9. Budgets, measured, not guessed.** These are set from Task 0. The Pi's numbers are pending Rio Grande's run of
scripts/projection_digest_timing.py.
- **Steady state, a marker match:** the reader's extra cost is at most 2 ms, for a stat, 4 header bytes and a small
  JSON file.
- **Append:** the median grows by at most 2 ms at the large shape on the dev machine (the re-reads plus the marker
  write), and N4's covering-index plan is kept.
- **The full check, which is rare:** at most 1.5 s on the dev machine (1.15 s measured), and at most 8 s on the Pi, in a
  Pi-only test like U24 (test_permissions_pi_budget.py). It runs after a restore, a tamper, a crash, or a ledger's first
  sight. A daemon frame that meets it may miss its deadline once, which reads as `degraded`, never as a wrong answer.

## Tasks (test-first: each test is seen failing before its code)

0. **Measure first.** The script is scripts/projection_digest_timing.py.
   - **Tardis, done:** at 20,000 memories and 16,384 records (236,389 rows, 28.7 MB), `state()` took 0.35 s, the full
     recompute 1.0 s (3.6 s with canonical JSON and SHA-256), and `integrity_check` 0.15 s.
   - **The Pi:** Rio Grande runs it after E1, and the result sets D9's Pi line.
1. **The row hash and `canonical_json`'s BLOB case.** Tests: a known row's hash; a BLOB round-trips as hex; a table's
   column order follows `_COLUMNS`.
2. **The full recompute (`projection_now`),** a pure read with no writes. Tests: an empty ledger's digest is fixed;
   two ledgers holding the same rows in a different insert order give the same digest.
3. **The incremental writer** (D3). Tests:
   - **A seeded property test:** after each of 200 random acts across every act kind, `meta.projection` equals
     `projection_now`. It includes values that affinity converts, and an update whose own `WHERE` column changes.
   - A `DELETE` on a projection table outside `_project` fails a test.
4. **The reader check and its marker** (D4). Tests:
   - **The acceptance test:** the strict xfail at :204-222 passes, and its mark goes.
   - A torn index page made by `_tear_index` (:69-82) reads as unreadable through `state()`.
   - An in-place SQL tamper is caught, since the change counter moved. So is a file renamed over the ledger (new inode)
     and a `cp -p` over it (new ctime, same mtime).
   - A second `state()` with no change does no full check, which a counter proves. So does a `state()` in a second
     process after a verified writer's append.
   - A writer killed between COMMIT and its marker write leads to exactly one full check, then a match.
   - A missing or malformed marker leads to a full check, never to a pass.
5. **Old ledgers, the gate, `verify` and `rebuild`** (D5, D6, D7). Tests:
   - a writing open adds the keys;
   - a read-only open of a ledger with no digest, under enforce, reads `closed`;
   - `gate enforce` is refused with no digest and allowed with one;
   - `verify` reports a mismatch;
   - `rebuild`'s table equality is checked.
6. **The fixtures and budgets** (D8, D9). `restamp_projection` is used in the named fixtures, and the whole Engram
   suite passes. The append and full-check budget tests are added.
7. **`ENFORCE_WAITS = None`,** its own commit (D6).

## Checks before review

- The whole Engram suite passes, plus `make mutants SPEC=` for these mutants:
  - the reader skips the parts comparison;
  - the cache ignores `st_mtime_ns`;
  - `_project` forgets to subtract an updated row;
  - `integrity_check` isn't run.
- Each mutant must die on the assert its test names. Three more mutants:
  - the marker key drops `st_ctime_ns`;
  - the marker key drops the change counter;
  - `_project` hashes bound values instead of re-reading the row.
- The Pi budget test passes on the Pi.

## Deploy

Merging changes nothing live. A ledger gets its digest at its next writing open. The Pi has no ledger today (Rio
Grande, all hands, ddd4c343). So the live steps are Andy's, in the one sitting the crossing plan names:
- `migrate`;
- register `remote-stores` at `outside-home`;
- `gate enforce`.

## Risks

- **The full check's cost on the Pi.** It's measured in Task 0, with D9's fallback.
- **A tear the digest can't see:** two compensating changes whose hash sums cancel. That's negligible for accidental
  tears, as D2 says.
- **The marker's limits:** it isn't a security boundary (D4). A filesystem with coarse ctime could miss a same-tick
  `cp` over a file whose change counter and head both match, and the runbook's restore stops every process first.
- **Writer drift reads as a tear** (D3). The property test and the three drift rules are the guard. If drift ever
  happens live, `rebuild` restores the tables from the log.
