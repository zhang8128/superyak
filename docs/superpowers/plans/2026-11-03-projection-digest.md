# Plan: the permission ledger's projection digest

**By:** Tardis, 2026-11-03. **Board item:** `build:permissions-projection-digest`.

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
- **A row's hash:** SHA-256 of `canonical_json([table, [values in _COLUMNS order]])`. A BLOB is written as
  `{"hex": "…"}`, and `canonical_json` gains that case.
- **A table's part:** its row count, and the sum of its rows' hashes mod 2^256, as an additive multiset hash. Order
  doesn't matter, and an insert or update changes it by a delta.
- **The whole:** SHA-256 of `canonical_json([[table, count, sum_hex] …])`, in `_COLUMNS` order.
- **Why additive:** it detects accidental tears. Anyone who can write the file can rewrite anything anyway, so this
  isn't an adversarial MAC, and the plan says so.

**D3. The writer keeps it incrementally.**
- `_project` reads, before each update, the rows its `WHERE` matches, and subtracts their hashes. After the update it
  adds their new hashes. Each insert adds its row's hash.
- Only changed tables' parts change, and the new `projection` is written in the same transaction.
- **Cost:** one extra read per update, of the rows it touches. That's measured in Task 6.

**D4. The reader checks it fully, once per file state per process.**
- **The full check,** in `state()`, before any row is served:
  - recompute every table's part by a `NOT INDEXED` scan;
  - compare the parts and the whole with `meta`;
  - run `PRAGMA integrity_check`, which catches a torn index page that the partial-index reads would trust.
- Any mismatch, or any answer but `ok`, raises `LedgerUnreadable("the projection digest …")`, so the ledger fails
  closed.
- **The cache:** one process cache, keyed by (path, `st_dev`, `st_ino`, `st_size`, `st_mtime_ns`, `head`). A hit skips
  the full check. A writer that commits from a verified base updates the cache with its new stat and head, since it
  computed the digest incrementally.
- **Why the stat is in the key:** any write changes the mtime. The xfail test tampers with the file in place, in the
  same process, and the check must still catch it. So does a `cp` over a live file.
- **The residual limit, said plainly:** on a filesystem with coarse mtimes, a same-size in-place change within one
  tick could hit the cache. Ext4 and APFS keep nanoseconds. The runbook's restore stops every process that opens the
  ledger, so a restored file always meets an empty cache.

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

**D9. Budgets, measured, not guessed.**
- **Append:** at the records bound (16,384), the append median grows by at most 1 ms on the dev machine, and N4's
  covering-index plan is kept.
- **Full check:** at the records bound, at most 300 ms on the dev machine, and at most 1.5 s on the Pi, in a Pi-only
  test like U24 (test_permissions_pi_budget.py).
- **If `integrity_check` takes the Pi over budget:** it moves to `verify`, to `gate` and to writing opens, and the
  per-state check keeps the digest alone. That fallback is decided by the measurement and reported to the reviewer,
  never assumed.

## Tasks (test-first: each test is seen failing before its code)

0. **Measure first.** Time `state()` and a full `NOT INDEXED` scan, plus `integrity_check`, at the records bound, on
   the dev machine and on the Pi. Record both, since they set D9.
1. **The row hash and `canonical_json`'s BLOB case.** Tests: a known row's hash; a BLOB round-trips as hex; a table's
   column order follows `_COLUMNS`.
2. **The full recompute (`projection_now`),** a pure read with no writes. Tests: an empty ledger's digest is fixed;
   two ledgers holding the same rows in a different insert order give the same digest.
3. **The incremental writer** (D3). A seeded property test: after each of 200 random acts across every act kind,
   `meta.projection` equals `projection_now`.
4. **The reader check and its cache** (D4). Tests:
   - **The acceptance test:** the strict xfail at :204-222 passes, and its mark goes.
   - A torn index page made by `_tear_index` (:69-82) reads as unreadable through `state()`.
   - An in-place tamper in the same process is caught, since the mtime changed.
   - A file renamed over the ledger is caught, since the inode changed.
   - A second `state()` with no change does no full check, which a counter proves.
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
- Each mutant must die on the assert its test names.
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
- **The cache's coarse-mtime limit,** named in D4.
