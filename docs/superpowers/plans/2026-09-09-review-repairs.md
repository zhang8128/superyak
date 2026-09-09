# Repository review repairs

**Goal:** Fix the eight reproduced bugs accepted by the user after the review of
`3fb91b15d837ed96e03e9fc9ea6414fae121a6f6`.

**Approach:** Keep the existing component interfaces and permission model. Use
populated temporary databases and real parsers/validators for regression tests;
replace only external model calls with deterministic test providers. Independent
indexing, maintenance, and Lighthouse repairs run in parallel; the controller
owns migrations, transactions, integration, and final review.

**Constraints:** Preserve unrelated changes. Do not operate on live memory stores,
restart services, publish memories, or expand sharing permissions. Historical
provenance already deleted by an applied migration cannot be inferred reliably;
the migration repair protects stores that have not yet applied version 015.

## Repairs and acceptance checks

- [x] Preserve both provenance junction tables across migration 015. Upgrade a
  populated version-014 store through 015 and through the current schema; verify
  source similarities, semantic contradictions, vectors, search, and foreign keys.
  A failed upgrade must leave the old records intact.
- [x] Roll back interrupted `Storage.transaction()` scopes. Exercise cancellation
  and nested scopes, then verify another writer can write and a subsequent commit
  does not persist the interrupted changes.
- [x] Make code-symbol IDs distinguish lexical scopes. Index actual Python,
  JavaScript, and TypeScript with repeated methods and inspect stored results.
- [x] Prepare file indexes before transactionally replacing them. Inject parsing,
  embedding, and storage failures and verify the old index survives. Deletion
  must match the exact file, including filenames containing SQL wildcard characters.
- [x] Generate backfill embeddings outside SQLite write transactions. Probe a
  second connection during episode, semantic, and instinct embedding, and exercise
  failure and concurrent source/vector changes without leaving open transactions.
- [x] Rank publisher results within the eligible share set. Add more than eighty
  closer inaccessible rows and confirm the eligible share remains reachable;
  preserve digest checks, revocation, audiences, and deterministic ordering.
- [x] Export only receipts beneath the declared export root. Count valid omitted
  receipts separately and validate the resulting corpus with TypeScript.
- [x] Match UTF-16 code-unit ordering in Python canonical JSON. Validate a sealed
  receipt containing non-BMP extension keys in both Python and TypeScript.

Each repair starts with a regression that fails against the reviewed code, then
runs its affected test files after the fix. The final gate is `make check`, a
review of the combined diff, and `git diff --check`. Baseline: 2,257 Python tests,
129 TypeScript tests, both proofs, and interoperability passed; two live-host
configuration tests were intentionally skipped.

Completed: all eight repairs and independent diff reviews passed. Final
`make check`: 2,329 Python tests (two opt-in skips), 129 TypeScript tests, both
proofs, and interoperability passed. See
`docs/reports/2026-09-09-review-repairs.md` for evidence and operational limits.
