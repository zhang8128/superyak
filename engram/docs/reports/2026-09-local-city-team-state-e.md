# Team State: local-city-e

- Base ref: `main` at `5fb3804`
- Full suite baseline: 1490 passing
- Shared contract: `docs/superpowers/plans/2026-09-01-lighthouse-local-city.md`
- Design: `docs/superpowers/specs/2026-09-01-lighthouse-local-city-design.md`
- Integration order: E1's `server.py` call-site change first, then E2 rebases across it.
- Shared-file conflicts allowed only in `pyproject.toml` and `CLAUDE.md`, resolved during integration.
- Never touch or restart the running Engram MCP server; the human restarts it after integration.
- Integration SHA: `a034f2a` on `team/local-city-e/integration`, produced by the human/integrator: E1 head `5d9a9d4` fast-forwarded first, then E2 head `4aa6483` merged as `a034f2a`, with no conflicts.
- Integration verification: PASSED at `a034f2a` — `1673 passed, 1 skipped`.
- Local main history: human/integrator first merged integration as `927bcca`, then fast-forwarded accepted E1y to `1f9dab1`; E1p cut from `c60e722a`; main independently advanced to `d8107b8` with the disjoint knowledge-graph index fix; human/integrator merged accepted E1p as conflict-free merge commit `e19e915`. Nothing was pushed.
- Final overnight verification: full suite PASSED at E1y/main — `1674 passed`.
- Team status: stood down. dev panes stay alive and branches are preserved. The B0 gate remains closed and no receiver work is authorized.
- Gate resume: E1's receiver arm, `recall()` call site, and `lighthouse_label.py` remain closed until the human's morning B0 spike rerun. When reopened, dev1 resumes on a new branch cut from `main` at/after `927bcca` as directed by the human.
- Launcher blocker resolved by codex-team `617df61`, which grants dev sandboxes a writable root for the repo `.git` directory. Both dev panes were relaunched with worktree files preserved; resume assignments were delivered from this state.

## E1 — Publisher daemon and receiver arm

- Owner: dev1
- Status: merged (complete through E1x on local main `927bcca`; receiver arm/call site/labeler remain gated and absent)
- Plan: `docs/superpowers/plans/2026-09-01-local-city-e1-publisher-daemon.md`
- Last known SHA: `5d9a9d4fe02a14179e452659bf99f27345f76bed`
- Scope/seam: exactly the E1 allowed/forbidden file lists in the human brief and assigned plan.
- Gate: stop before `neighbors.py`, the `recall()` receiver call site, and `lighthouse_label.py`. Continue only after the human confirms the B0 spike rerun recorded in `docs/reports/2026-09-b0-neighbor-spike.md`.
- Current progress: Tasks 1–6 plus exporter 1.1 complete in ordered SHAs `011624d`, `a19da5e`, `fd4d644`, `0c3cc56`, `2b39894`, `9ae8b10`, `60e3365`. Worktree clean; lead verified base-to-head file list contains only E1 pre-gate surfaces and excludes all gated receiver files. Targeted evidence: `60 passed, 1 skipped`; daemon/server import grep empty. Full suite: `1528 passed, 1 skipped, 1 failed`; sole failure is packaging lock metadata because the plan-required `jsonschema>=4.23` was added to `pyproject.toml` while `uv.lock` is outside E1 scope.
- Human decisions: B0 remains closed overnight because the Lighthouse publisher store was empty until its instance binding was repaired; receiver arm, call site, and labeler remain gated. `uv.lock` is authorized as a one-change E1 scope exception: dev1 runs `uv lock`, verifies the diff is only the `jsonschema` metadata, requires `uv lock --check` and packaging/full-suite tests to pass, then commits the lockfile alone.
- Challenge finding at `6192700`: `decode()` accepts recognized frame kinds without required-field/type validation and `handle_frame()` looks up publishers before validating request shape, misclassifying malformed input as `PUBLISHER_UNAVAILABLE`. Required fix is shared per-kind structural validation in `lighthouse_protocol.py`, invoked by `decode()` and by daemon handling before store lookup, with missing/wrong-type protocol and daemon regressions. Reviewer verdict: NOT READY pending fix and re-review.
- Fix evidence at `5d9a9d4`: regression commit `67d7f82` red first, fix commit `5d9a9d4`; only `lighthouse_protocol.py`, `lighthouse_daemon.py`, and their two test files changed. Reviewer reproductions now yield `MALFORMED_FRAME`; focused suite `103 passed`; full suite `1616 passed, 1 skipped, 3 warnings`; diff-check clean. Awaiting dev2 re-review of the new pinned head.
- Re-review verdict: READY with no findings. Reviewer independently reran E1 focused tests (`184 passed, 1 skipped, 1 warning`), full suite (`1616 passed, 1 skipped, 3 warnings`), `uv lock --check`, server-import grep, and diff checks; attested all completed pre-B0 E1 criteria, E1x behavior, authorized 23-file surface, and absence of every B0-gated receiver file.

Acceptance criteria:

1. `tests/test_storage_readonly.py` passes, proving no SQLite changes and unchanged `graph.db` SHA across vector retrieval, including a closed WAL store with deleted side files.
2. `tests/test_lighthouse_policy.py` passes, including fixture parity and policy digest `f12270e190c2961e56e0cc793dfe43199611d406fbedaa22e971156de33d8a3f`.
3. `tests/test_lighthouse_daemon.py` passes: policy-before-retrieval, work lane only, no instincts, disclosure sidecar, complete unavailable-store handling, and unchanged `graph.db` SHA.
4. `tests/test_neighbors.py tests/test_recall_neighbors.py` passes: conditional `neighbors`, no merge into `results`, exact daemon-down degradation behavior, unchanged margin, and correct receipt `injected` value.
5. `tests/test_lighthouse_export.py` passes with `formatVersion == "1.1"` and content/query-free receipts.
6. Full `tests/` suite passes.
7. `grep -n "import server" lighthouse_daemon.py` returns nothing.

## E1x — Config routing warnings

- Owner: dev1
- Status: merged (complete on local main `927bcca`)
- Base: dev1 E1 branch after the authorized `uv.lock` commit
- Last known SHA: `6192700`
- Allowed files: `config.py` only within `load_config` and `resolve_db_path`; new `tests/test_config_routing.py`; one sentence under Memory lanes in `CLAUDE.md`.
- Forbidden surface: `MemoryConfig` and `_DEFAULT_TOML` remain E2-owned. All original E1 B0-gated files remain closed.

Acceptance criteria:

1. Unknown keys inside a known config section are ignored with a WARNING naming the key; a newer config still resolves to its configured instance.
2. A TOML parse error falls back with a WARNING naming the config path, parse error, and fallback path.
3. A configured instance whose store is missing logs the selected fallback store.
4. `tests/test_config_routing.py tests/test_server_registry.py` pass.
5. Full suite passes.
6. E1x is committed separately, followed by a clean stop at the B0 gate.

## E2 — Recall targeting

- Owner: dev2
- Status: merged (complete on local main `927bcca`)
- Plan: `docs/superpowers/plans/2026-09-01-local-city-e2-targeting.md`
- Last known SHA: `4aa6483b88664795bf6ef65f4bfe79c463c4a91e`
- Scope/seam: exactly the E2 allowed/forbidden file lists in the human brief and assigned plan.
- Current progress: complete through After replay in 16 ordered commits from report-only `64266d0` through head `7c944b5`; lead verified clean worktree, exact 14-file E2 seam, and report commit before scoring history. Completion evidence: targeted nine-file suite `89 passed, 1 warning`; full suite `1546 passed, 3 warnings`; `git diff --check` clean. Before/After historical replay is intentionally identical: additive near-tie/.<=7d/.<=1d = `.30 / 90.5% / 83.5%`; tiebreak = `.66 / 73.5% / 61.0%`; 118/200 winners changed between modes. `server.py` changed, so the human must restart the running MCP server only after integration.
- Challenge finding at `7c944b5`: `_derive_lane` returns `work` for `work=True` before honoring `context.lane == "personal"`, contradicting the binding shared contract in which explicit personal overrides every work signal after core/genome precedence. Required fix: reorder precedence, add pure and `remember()` regressions for `work=True` plus explicit personal, and correct CLAUDE's conflicting “work=True wins” wording. Reviewer verdict: NOT READY pending fix and re-review.
- Fix evidence at `4aa6483`: regression commit `16b128b` red first, fix commit `4aa6483`; only `CLAUDE.md`, `server.py`, and `tests/test_remember_lane.py` changed. Direct reproduction now returns `personal`; targeted E2 suite `90 passed, 1 warning`; full suite `1547 passed, 3 warnings`; clean worktree and diff-check. Awaiting dev1 re-review of the new pinned head.
- Re-review verdict: READY with no findings. Reviewer independently reran the 9-file E2 suite (`90 passed, 1 warning`) and full suite (`1547 passed, 3 warnings`), attested all 11 acceptance criteria, exact 14-file seam, read-only replay protections, outcome behavior, and no running MCP touch.

Lead rulings:

- Task 1's generated replay report is committed by itself before any commit containing `scoring.py` or scoring changes; the plan's conflicting combined `git add` recipe does not apply.
- Do not create the unlisted `tests/test_recall_recency_mode.py`. Its two planned integration tests belong in the allowed `tests/test_scoring.py`; corresponding pytest and staging commands are adjusted to that file.
- Linked worktrees use `/Users/kairos/Projects/engram/.venv/bin/python` from their own cwd for every plan command written as `.venv/bin/python`, with per-dev `UV_CACHE_DIR` paths under `/private/tmp`. The main checkout and venv remain read-only; if a new dependency is required, the dev reports it and the human installs it.
- Team messaging budget: at most 8 messages per pair per 30 minutes. Until raised, dev traffic is limited to readiness, one completion report per task with SHA/test output, and one challenge-review report; no acknowledgments or progress notes. Lead traffic is limited to one assignment per WP and one review verdict. On any guard refusal, stop cleanly and wait for the human reset.

Acceptance criteria:

1. `docs/reports/2026-09-margins-replay.md` is committed before scoring changes.
2. The report includes near-tie rate, under-7-day and under-1-day winner shares under both modes, plus changed-winner count.
3. Scoring/replay tests pass and tiebreak recency is bounded by `recency_cap`.
4. Existing recall-margin tests pass with default `tiebreak` using the same scorer as `recall()`.
5. Lane derivation tests pass for project tags, explicit lane, and core memories.
6. Per-instance `default_lane` tests pass, with explicit and core overrides.
7. `dream_verify` splits matched `scores` and `uninvited_scores`.
8. Lane filtering occurs before margin and fills `max_results` from the requested lane.
9. Sleep-time auto-capture marks only later-cited recall results and preserves existing outcomes.
10. Full `tests/` suite passes.
11. `CLAUDE.md` documents recency controls, lane/default-lane derivation, score split, lane-before-margin, and sleep-time auto-capture.
12. The replay report gains an `After` section from a post-Task-6 rerun.

## E1y — Cross-repo Lighthouse artifact reconciliation

- Owner: dev1
- Status: merged (complete on local main `1f9dab1`; full suite `1674 passed`)
- Branch base step: merge local `main` (`927bcca` or later) into `team/local-city-e/dev1` as its own commit before E1y changes.
- Source pin: Lighthouse local main `b178460` at `/Users/kairos/Projects/lighthouse` (read-only source).
- Synchronized Engram base: `50b135d4987c7b42e95fa4110a1f2ff71aa7ea9b` (clean fast-forward of dev1 branch to then-current main).
- Last known SHA: `1f9dab1340f01e672a1fe7bca1eb8725cd24dd35`.
- Allowed files: `tests/test_lighthouse_policy.py`; `tests/test_lighthouse_receipts.py`; `lighthouse_receipts.py` only within `validate_receipt`; `schemas/lighthouse/**`; `tests/fixtures/lighthouse/policy/**`.
- Gate: `neighbors.py`, the `recall()` receiver call site, and `lighthouse_label.py` remain closed and untouched.

Ordered work/commits:

1. Merge local main into dev1 branch; resolve nothing manually unless Git asks, and stop on any unexpected conflict.
2. Additively sync generated receipt schema and 14 generated policy fixtures from Lighthouse `b178460`, retaining `workflow-policy.json` and the two hand-vendored requests; commit `chore: sync Lighthouse artifacts at b178460`.
3. Update policy parity test resolution so `policy: "local-city"` tries `policies/local-city` then `policies/local-city.json`; all 16 cases must pass; commit separately.
4. Make `validate_receipt` check injected/delivered invariant before schema and digest, and adjust receipt tests so digest mismatch tampers only the digest; commit separately.

Acceptance criteria:

1. `tests/test_lighthouse_policy.py tests/test_lighthouse_receipts.py tests/test_lighthouse_export.py` pass.
2. All 16 policy parity cases pass.
3. Engram-built receipts validate against the generated schema while `INJECTED_MISMATCH`, `SCHEMA_INVALID`, and `DIGEST_MISMATCH` remain distinguishable.
4. Full suite passes; worktree and diff-check are clean; only E1y files are changed after the required main merge.

Completion evidence: commits `2eb010d` artifact sync, `363ae9f` parity reconciliation, `1f9dab1` receipt validation order; targeted suite `37 passed`; full suite `1674 passed, 3 warnings`; exact Lighthouse source pin confirmed; generated artifacts byte-identical; 16 request/decision cases pass; clean worktree and diff-check. Awaiting dev2 challenge review.

Challenge verdict: READY with no Critical, Important, or Minor findings. Reviewer independently verified Lighthouse pin `b1784608e30be17784a9cdbe5f58fcf89d8915be`, byte equality for the schema and 29 generated fixture files, preservation of the hand-vendored files, all 16 parity cases, invariant/schema/digest error isolation, exact E1y seam, targeted `37 passed`, full `1674 passed, 3 warnings`, and no B0-gated or running-MCP touch. Human/integrator fast-forwarded E1y into local main as `1f9dab1`; nothing pushed.

## E1p — JSON-number canonicalization

- Owner: dev1
- Status: merged (accepted pin `f59518d470f7e2efeffe68cc93d138ee18822451` merged by human/integrator into local main as `e19e915`; no conflicts)
- Base: fast-forward `team/local-city-e/dev1` to local `main` at `c60e7223` with `git merge --ff-only main`, then verify branch HEAD equals main before edits.
- Allowed files: `lighthouse_protocol.py` only within `canonical_json` and new `_canonical_number(value: int | float) -> str`; `tests/test_lighthouse_protocol.py`; optionally one reviewer-required `local-city-weight-float` fixture pair under `tests/fixtures/lighthouse/policy/**`.
- Forbidden: `.engram/**`, live receiver policy, `server.py`, `neighbors.py`, receiver arm/call site/`lighthouse_label.py`, and every other file.
- Baseline evidence: ff-only synchronization succeeded to exact main `c60e722a6e1cebc1f1377ed2cdb8a63d554d59a1`; branch clean and HEAD equals main. E1p targeted baseline is `104 passed in 0.17s`. Unchanged-main full `tests/` did not complete: interrupted after `1267 passed` at 404.42s near `test_recall_margins`; narrowed adjacent tests reached `8 passed` then stalled in `TestMarginInRecall::test_margin_matches_the_returned_top_two_scores`, with teardown pointing to the new server startup/watcher path. This is outside E1p scope; dev1 must not touch it and continues bounded E1p TDD. Final full-suite evidence may require human/integrator handling of the synchronized-main issue.
- Implementation evidence: red-test commit `9164fa7`, fix commit/head `eb0e1c5`; exact allowed two-file diff (`lighthouse_protocol.py`, `tests/test_lighthouse_protocol.py`), clean worktree/diff-check. Protocol suite `98 passed`; acceptance target `112 passed`. Vendored digest remains `f12270e190c2961e56e0cc793dfe43199611d406fbedaa22e971156de33d8a3f`. Node/Lighthouse boundary comparisons pass, and a scratch float-weight artifact validates through the kit with digest `de44dc86720a2554dfe5535ec6fe017851f0262e225418edc9bceb9fdb006f5a` and `ok:true`.
- Prior stall ruling: human/integrator identified machine contention, not a code defect—the machine was simultaneously running two other full suites and a 27B-model extraction probe. Integrator evidence on the same tree: `1682 passed` in 29 minutes under load and `1680 passed` in 4m36s when quiet. dev1 was instructed to rerun the full suite once at `eb0e1c5` now that the machine is quiet, stop after 15 minutes if unfinished with current-test/`ps` evidence, and make no code changes. Challenge review follows only after this result.
- Quiet-machine rerun: full suite completed successfully at `eb0e1c5` — `1688 passed, 3 warnings in 347.07s (5m47s)`, exit 0. No code change or MCP/integration action accompanied the rerun.
- Challenge special checks: dev2 must assess the use of private `json.encoder._make_iterencode` against installed Python 3.13 and whether a public-API encoder/pre-pass is safer; must also compare the Python-int branch with ECMAScript at `10**20`/`10**21` and decide from contract/protocol scope whether large integer-valued numbers require exponent handling. An in-scope mismatch is a finding.
- Challenge finding: NOT READY. Python 3.13 `_make_iterencode` routes ints through private `_intstr`, bypassing `_canonical_number`; exact-binary64 integers therefore diverge from ECMAScript (`10**21`, `2**68`, `10**21+131072`). Required fix: red regressions for exact large integers, rejection of non-exact binary64 ints such as `2**53+1`, Number spelling for exact ints, and replacement of private `_make_iterencode` dependence with a public direct/encoder implementation that preserves canonical behavior. dev1 independently reproduced the finding; fix verdict delivered.
- Fix evidence at `f59518d`: red test commit `133206c`, implementation commit `f59518d`; exact pinned-base diff remains only `lighthouse_protocol.py` and `tests/test_lighthouse_protocol.py`, clean worktree/diff-check, no private encoder references. Exact-binary64 ints now match Node (including `10**21`, `-10**21`, `2**68`, `10**21+131072`); `2**53+1` raises the documented ValueError; direct public recursive serializer preserves canonical/container/error behavior. Protocol `106 passed`; targeted `120 passed`; full suite `1696 passed, 3 warnings`; vendored and float-policy digests/cross-kit validation remain green. Local main advanced independently to `d8107b8`; review remains pinned to base `c60e722a` and head `f59518d`.
- Re-review verdict: READY with no Critical, Important, or Minor findings. Reviewer independently verified 20,000 exact integer-valued binary64 samples with zero Node mismatches, rejection of non-exact/out-of-range ints, absence of private encoder APIs, public-recursion compatibility across containers/errors/types, targeted `120 passed`, full `1696 passed, 3 warnings`, both stable digests, successful Lighthouse float-policy validation, exact two-file seam, and no B0/`.engram`/MCP/integration/main touch.
- Main verification: targeted suite `120 passed`; the original float-weight reproduction validates through the Lighthouse kit with digest `491bde6e…`; full suite is running under the human/integrator. Nothing pushed. Team stood down with panes alive and branches preserved.

Acceptance criteria:

1. RFC 8785/ECMAScript number spelling is defined on the JSON value: integral floats lose `.0`, negative zero is `0`, non-integral values use shortest round-trip, and ES6 exponent boundaries/spelling match Node/kit bytes; booleans and finite-value rejection remain unchanged.
2. Strict red-first tests cover integral float, negative zero, non-integral float, both exponent boundaries, and a kit-derived artifact digest for a ConnectionPolicy weight `1.0`.
3. Existing vendored policy digest remains `f12270e190c2961e56e0cc793dfe43199611d406fbedaa22e971156de33d8a3f`.
4. `tests/test_lighthouse_protocol.py tests/test_lighthouse_policy.py tests/test_lighthouse_receipts.py` pass; full suite passes.
5. A float-weight artifact sealed by Engram validates successfully through Lighthouse `pnpm --silent lighthouse validate`; scratch artifacts stay under `/private/tmp`.
6. Diff/stat, worktree, and diff-check are clean and limited to allowed files. Report pinned SHA and stop for dev2 challenge review; no integration/main merge.
