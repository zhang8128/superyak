# Stampede3 launch preparation — verification

Verified locally on September 12, 2026. No Stampede3 login, Slurm submission,
model download, or Intel inference was performed.

- Full Engram/Python suite against the implementation worktree: **2,442 passed,
  2 skipped** in 276.45 seconds. The skipped checks require explicitly selected
  live Codex configuration. Three existing dependency/fork deprecation warnings
  remain. The test command used the existing Python environment and built
  Lighthouse checkout with `LIGHTHOUSE_REPO` set explicitly.
- Stampede-specific suite: **101 passed**, covering actual HTTP responses,
  filesystem bundles, memory/sharing, exports, restart, and fake SSH/Slurm/GPU
  process boundaries. An initially fragile 150 ms interpreter-startup test was
  corrected to use three seconds; production timeouts did not change.
- `make check-lighthouse`: build, lint, typecheck, package tests, protocol proof,
  and recall proof passed.
- `make check-integration`: two matching schemas, seven socket checks, four
  receipts validated by TypeScript, and three required interoperability tests
  passed. These existing modules were unchanged by the launch addition.
- Full offline rehearsal: 20 cells completed with 156 scripted model calls.
  Repeating it restored completed cells with zero new calls. Usage and hardware
  are explicitly unmeasured in the simulation.
- The actual allowlisted source archive was extracted into a clean temporary
  directory; its plan and entire small campaign succeeded using the installed
  Python dependencies. All 117 source manifest hashes matched; the archive had
  118 members including its manifest and no private-state paths.
- Real SQLite export/restore survived deletion of the original run and local
  stores. An independent partial-restore check preserved one completed turn and
  executed exactly the five unfinished calls.
- Shell syntax, Python compilation, staged whitespace checks, and the macOS
  wrapper's project/argument forwarding passed. The wrapper check intercepted
  the execution boundary and made no remote call.
- Independent review verified resolution of structured-output acceptance,
  backend consistency, checkpoint export races, serial evidence exposure, and
  stale job status. See the [review](2026-09-12-stampede-launch-review.md).

The first allocation must establish site driver/compiler compatibility, Intel
build success, inference latency, memory fit, shared-filesystem lock behavior,
and useful agent capacity. The bootstrap exercises a synthetic task; it does
not yet implement open-ended research or a matched-token scientific evaluation.
