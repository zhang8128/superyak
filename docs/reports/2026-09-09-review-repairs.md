# Repository review repairs — 2026-09-09

The eight reproduced issues from the review of `3fb91b1` are repaired. Changes
retain the existing memory schema version, component interfaces, and sharing
permissions.

| Issue | Result |
| --- | --- |
| Migration 015 cascaded away provenance | The table replacement preserves both source junctions, similarity values, and semantic rowids within the migration transaction. |
| Interrupted storage transactions stayed open | Cancellation, keyboard interrupts, and process-exit exceptions roll back the owning transaction and release its writer lock. |
| Same-named methods collided | Symbol identity includes lexical scope; same-scope overloads and redefinitions additionally use source position. Unique top-level IDs remain unchanged. |
| Failed indexing erased the prior index | Parsing and complete embedding preparation precede transactional replacement of symbols, FTS entries, and vectors. File deletion matches the exact path, including wildcard characters and case. |
| Backfill held a writer lock during embedding | Episode, semantic, instinct, and perceptual backfills compute first, then recheck source state and commit short writes. Concurrent fills/edits/deletions and failed writes are covered. |
| Inaccessible neighbors hid valid shares | Publisher retrieval ranks within the intact, authorized shared pool, using 256-row batches and a bounded top-k working set. |
| Receipts outside the export root invalidated exports | Technical exports keep only receipts within that context subtree, counting other valid receipts separately from malformed records. |
| Python and TypeScript disagreed on Unicode digests | Python recursively orders object keys by UTF-16 code units, matching the TypeScript implementation. |

Actual JavaScript/TypeScript indexing tests also required correcting the existing
JavaScript import query and TypeScript class/signature queries. Tree-sitter's
syntax-recovery behavior and the existing TSX grammar choice remain unchanged.
Refreshing a file replaces old flat IDs with its new scoped IDs. Source-position
suffixes can change when overloaded/redefined declarations move.

## Focused verification

Regressions were observed failing against the reviewed code before implementation.
Tests use temporary SQLite stores, real parsers and TypeScript validators, with
deterministic substitutes for model calls.

- Storage: 88 tests passed, including populated upgrades to version 015 and the
  current schema, failed-upgrade rollback, preserved search/vectors, and cancellation.
- Indexing: 31 tests passed, including persisted FTS/vector search after failed
  replacement, lexical scopes, overloads, legacy IDs, and exact-file deletion.
- Backfill/startup: 32 tests passed, including independent writers during model
  calls, concurrent source changes, and embedding/SQL failures.
- Lighthouse: 198 tests passed, including a 600-row ranking case, corrupted share
  records, scoped receipt export, and bidirectional Unicode artifact verification.
- Independent reviews of the migration/runtime, indexing, and Lighthouse changes
  found no additional substantive issues.

`make check-integration` now requires the cross-language regression tests as well
as the existing socket/schema/receipt pilot. Python-only environments may skip
the cross-language tests if Node or built Lighthouse dependencies are absent.
Both missing-dependency modes were exercised: optional skips; required fails.

## Complete verification

`make check` exited successfully after all changes:

- 2,329 Python tests passed; two explicitly opt-in live-host configuration tests
  were skipped. The three dependency/fork deprecation warnings match the baseline.
- Lighthouse build, lint, and typecheck passed; all 129 TypeScript tests passed.
- Both protocol proofs passed (15 and 14 checks).
- Interoperability passed: two matching schemas, seven socket checks, four
  validated receipts, and all three required cross-language regression tests.
- `git diff --check` passed.

This adds 72 Python regression cases to the reviewed baseline. The complete run
log is `/tmp/superyak-review-repairs-check-20260909.log` on the repair host.

## Operational limits

No live memory stores, policies, or service configurations were changed by this
repair task. Existing MCP processes must reconnect, and an existing publisher
must restart, to load the updated source. The lifecycle barrier still serializes
each maintenance step inside one process; the backfill repair releases SQLite's
writer slot for other processes during embedding.

The migration repair protects stores that have not yet applied version 015.
Previously deleted provenance requires an authoritative backup or another
verified source; these changes do not invent replacement links. Exact shared
retrieval scans the shared candidate pool; large-store latency has not been
benchmarked by this repair task.
