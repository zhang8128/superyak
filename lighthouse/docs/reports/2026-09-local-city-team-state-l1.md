# Team State: local-city-l1

## Authority

- Plan: `docs/superpowers/plans/2026-09-01-local-city-l1-receipts-shadow.md`
- Design: `/Users/kairos/Projects/engram/docs/superpowers/specs/2026-09-01-lighthouse-local-city-design.md`
- Base ref: `main` at `b9dc7029191ad77b93523941f7918adcd941a4cf`
- Protected proof: `bridgeDigest` must remain `8f2194e9508bea7887196d8adbf668ddabef24f11c2b93513ab505f3736b4538`, with all 15 original checks unchanged.

## WP L1-A — Tasks 1–4

- Owner: dev1
- Status: accepted after final cross-review corrections
- Scope: RecallReceipt artifact and generated schema; recall-evaluation receipt emission and negative controls; Engram export 1.1 with receipts; receiver-owned labels document.
- Allowed files: exactly the files named under Tasks 1–4 in the plan.
- Acceptance: execute every TDD step and task-local verification in Tasks 1–4; commit after each task; final report must include SHA, summary, and actual `pnpm check` output.
- Last known SHA: `c5f0416532e23d0f00530ce511dda790fd88eaa3` (Tasks 1–4 corrected final); earlier task SHAs: `da8afa98e20a160a42e33ba29ad9e8b9d3db493d`, `5bbb26229195cc428f0be4ce34b3616a15ad4453`, `287411d56b02dfc238bf5ee4b50dfe9ec70d1829`, `d162b2f04d39f39d0e10f7c7dc20832608db7031`
- Review findings resolved: selected/delivered membership now uses an unambiguous tuple key with a delimiter-collision regression; export 1.0 rejects any explicitly present `receipts` member, including `[]`, with a regression.
- Coordination: owns shared `packages/recall-evaluation/src/index.ts` and `types.ts` until this WP passes cross-review.
- Authorized exception: `schemas/lighthouse-descriptor.schema.json` may change only as output of `pnpm schema:generate`, and its diff must contain only the `"RecallReceipt"` addition to `artifactEndpoints.kind`. No hand edits.
- Relaunch checkpoint: resolved. Dev1 has writable Git metadata and committed Tasks 1–4.

## WP L1-B — Tasks 5–7

- Owner: dev2
- Status: accepted after focused correction review at `1c80c338b2b4e87ead829625584b5c2c3be03aee`
- Scope: preregistration, seeded bootstrap, shadow evaluation; recall shadow/digest CLI and conformance wiring; policy conformance fixtures and generator.
- Allowed files: exactly the files named under Tasks 5–7 in the plan.
- Acceptance: execute every TDD step and task-local verification in Tasks 5–7; commit after each task; final report must include SHA, summary, and actual `pnpm check` output.
- Last known SHA: `1c80c338b2b4e87ead829625584b5c2c3be03aee` (review-corrected final); Task 6 `f4f1a80270b17c7444a08e9d502fbcf761d97aac`; Task 5 `cad10ff49e289b949a070d4f81af87145679b507`; accepted L1-A merge `7210f8a862834fe7cea39ff299f2a7674c9b50e5`; Task 7 `7e24d29862c6ff7cc99676dade6ea95750bbbf00`
- Coordination: merge pinned accepted L1-A SHA `c5f0416532e23d0f00530ce511dda790fd88eaa3` into the clean Task 7 branch, verify, then execute Tasks 5–6.
- Authorized exceptions: `biome.json` may differ from base only by the two include exclusions `!!fixtures/policy-conformance` and `!!fixtures/engram/receipts`. Root lint and package scripts must not change for formatting. Canonical one-line fixture bytes must survive because their digests are evidence.
- Task 6 pre-authorization evidence: focused suites green (recall-evaluation 47/47; conformance 8/8), and the lock diff is workspace-link-only.
- Final review findings corrected: contribution publisher must equal selected publisher, and duplicate selected `[publisher,memoryId]` refs reject before measurement; both use existing `RECEIPT_SCORE_MISMATCH` with focused regressions.
- Relaunch checkpoint: resolved. Dev2 has writable Git metadata and Task 7 is committed and accepted.

## Launcher incident

- Codex 0.152 workspace-write does not currently grant developer panes write access to `<repo>/.git/worktrees/<dev>/`.
- Human is fixing launcher permissions and will relaunch each developer pane. Files in both worktrees are safe and expected to survive.
- Loop guard is cleared. Developers must not retry commits until after relaunch.
- Fixed at launcher commit `617df61`; both developer panes relaunched with writable repository Git metadata. Preserved-tree recovery instructions were reissued from this state file.

## Communication rail

- Loop guard: 8 messages per role pair per 30 minutes; recent escalations were legitimate traffic, not loops.
- Developers send only readiness, one completion report per task with SHA/test output, and one challenge-review report.
- Lead sends only one assignment per WP and one review verdict; no acknowledgments or progress prompts.

## WP L1-C — Task 8

- Owner: dev1 (first finisher after cross-review)
- Status: accepted after challenge review at `4992a156e64114133fa9213370ab1609ce9b98b0`
- Scope: spec, vocabulary, and README updates exactly as Task 8 specifies.
- Allowed files: `spec/engram-recall-v0.1.md`, `spec/lighthouse-v0.1.md`, `spec/vocabulary.md`, `README.md`.
- Acceptance: Task 8 steps and full-package acceptance below.
- Last known SHA: `4992a156e64114133fa9213370ab1609ce9b98b0`

## Full-package acceptance

1. `pnpm check` exits 0.
2. `pnpm proof` passes, retains 15 checks, and prints protected `bridgeDigest` above.
3. `pnpm recall:proof` passes with 14 checks.
4. Schema generation is clean and `schemas/recall-receipt.schema.json` exists.
5. Valid receipt fixture validates; injected-mismatch fixture exits 1 with `SCHEMA_INVALID`.
6. Preregistered shadow succeeds; missing preregistration exits 1 with `PREREGISTRATION_REQUIRED`.
7. Policy fixture regeneration is clean and produces 14 decisions.
8. Specs mention export 1.1 and RecallReceipt as required.
9. Recall digest output exactly matches the preregistration corpus digest.

## Integration

- Integration SHA: `7839f27` (dev1 `4992a156e64114133fa9213370ab1609ce9b98b0` fast-forward, then dev2 `1c80c338b2b4e87ead829625584b5c2c3be03aee` merged without conflicts).
- Local main SHA: `b1784608e30be17784a9cdbe5f58fcf89d8915be`; nothing pushed.
- Status: DONE. Human/integrator full acceptance passed on integration and was re-verified after merge to local main. Lead fresh verification on integration: `CI=true pnpm check` exit 0; `CI=true pnpm proof` passed with 15 checks and protected bridge digest; `CI=true pnpm recall:proof` passed with 14 checks.
- Developer panes: stood down with branches/worktrees preserved.

## Global boundaries

- Forbidden files are exactly those listed in the human brief and plan.
- A `pnpm-lock.yaml` diff is accepted only for the `@lighthouse/recall-evaluation` workspace dependency in `packages/conformance`.
- Engram publisher ids use `urn:engram:<instance>`.
- Turns without receipts are local-only and count under `holdout.localOnlyTurns`.
- No reports beyond committed fixtures and final WP reports with passing `pnpm check` output.
