# Automatic prompt capture repair

Engram's `UserPromptSubmit` hook attempted to insert `episodes.origin`, but the
live and migrated schemas have `episodes.source`. A novel prompt therefore
failed before the hook emitted its prepared memory context. The same wrong
column prevented bounded pruning of automatically captured memories.

The hook now records `source='auto'`, the originating session, a content hash,
and `lane='work'`. These captures stay non-core. The existing 50-character
minimum and novelty threshold remain in place; this does not capture every
message or make automatic summaries of entire conversations.

Capture and pruning use separate transactions that roll back on failure.
This also fixes a reproduced partial-pruning bug: a later dream write could
otherwise commit an earlier incomplete deletion. An optional capture failure
emits a diagnostic and leaves the normal memory context available. Pruning
preserves manual, core, and externally tagged memories.

## Verification

Seventeen focused hook/capture/harness tests passed against disposable migrated
Storage databases with deterministic embeddings. Red regressions demonstrated
the missing-column failure, suppressed memory context, and partial-pruning
commit before the fixes. No model, embedding service, or live memory store was
used for these tests.

The full Engram suite passed **2,202 tests**, with **2 opt-in checks skipped**,
in 205.06 seconds. Dependency/fork deprecation warnings were unchanged. The
source implementation commit is `6fa2bd11cb91f590f1c981de3e14657ac72d04c7`.

## Local installation

The exact reviewed hook and its new tests were applied to the existing live
checkout at `/Users/kairos/Projects/engram` and committed locally as `c0d5b12`.
All 17 focused tests passed again there. No database schema or existing memory
content was changed during installation, and no synthetic probe was inserted
into the live store. The installed hook runs as a new process on each prompt,
so its fix applies on the next eligible prompt without restarting Engram MCP.

The separate Atlas research inbox records intentionally selected proposed
findings. This prompt-memory repair does not automatically publish user prompts
into that research graph or Lighthouse.
