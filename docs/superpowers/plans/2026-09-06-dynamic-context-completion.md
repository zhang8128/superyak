# Dynamic Context Completion Plan

**Goal:** Finish the recovered runtime implementation with verified continuation
source validity, immutable correction inspection, and measured runtime bounds.

**Architecture:** Retain the existing archive/compiler/provider boundaries and
explicit subscription versus API modes. Treat the sources used by an unfinished
provider episode as dependencies: a changed dependency stops further dispatch.
Historical inspection resolves the original event recorded by each selection.

**Spec:** `../specs/2026-09-05-dynamic-context-runtime-design.md`

**Worktree:** `.worktrees/dynamic-context`, recovered at `737213f`.
The user authorized implementation on September 6. Existing work is preserved;
this plan records completion of that implementation, not a replacement design.

## Tasks

- [x] Recover the existing implementation and run its 181 context tests.
- [x] Verify a synthetic Astra subscription response with no private source.
- [x] Add failing regressions for external memory changes during a tool episode,
  including prior selected evidence and source-backed tool results. Stop the
  episode before further generation if any such source is no longer valid.
- [x] Add failing regressions for correction revision/unpin after a model call.
  Record immutable original event references in each manifest and use those
  references in the browser's source inspector.
- [x] Bound archive query time after profiling exposed growing ranking cost.
  Keep recent/required context and explicitly report incomplete retrieval when
  the SQLite deadline expires, in both chat and coding paths.
- [ ] Measure at least 10,000 synthetic runtime model calls including tool
  continuations and a growing archive; record counted/dispatched equality,
  budget compliance, bounded candidate counts, and runtime allocation growth.
- [ ] Recheck the fixes independently; run the final targeted and repository
  checks, then document exact results and start a local review instance.

The existing human continuity pilot and strict Codex-internal request integration
remain separate, explicitly unevaluated gates. No API billing fallback, live
Lighthouse network changes, or normal-use rollout is introduced by this work.

## Review record

Independent read-only review confirmed two defects: external source plaintext
could survive revocation in active tool output, and historical correction
inspection resolved mutable state keys. The proposed encrypted-reasoning include
issue was rejected after current official documentation confirmed stateless
responses return encrypted reasoning by default.

All six regressions failed before the fixes; the runtime/compiler/source/CLI
checks passed afterward (32 tests). Scoped independent re-review accepted both
fixes with no additional material findings. Prior selected evidence also remains
an episode dependency, because opaque provider items may derive from it.

The repeated-prose replay exposed unbounded archive ranking time. A separate
1,000-call profile measured 32.91 seconds in search out of 56.96 seconds total;
100-call intervals grew from 3.61 to 10.11 seconds. The original workload was
retained. A 50 ms SQLite progress deadline now stops ranking and marks coverage
incomplete; its cost is potentially missing old sources. Three regressions failed
first and the store/runtime/coding/replay group then passed 53 tests. The code
also carries immutable correction references through coding manifests.
