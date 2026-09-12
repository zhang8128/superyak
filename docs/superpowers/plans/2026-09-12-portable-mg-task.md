# Portable MG Task Implementation Plan

> Controller owns packet/replay/CLI; the independent transport and provider agents
> own their assigned boundaries. Use test-driven development and independent
> review, then integrate locally without moving live journals.

**Goal:** Recover cleanly from slow literature requests and execute one frozen MG
question/source task through local or cluster model protocols.

**Architecture:** Two bounded HTTP lanes; a separate root `research_tasks` package
for explicit export, provider adaptation, durable calls and Atlas capture.

**Tech Stack:** Python 3.13, standard-library Atlas, existing Engram provider,
pytest, uv, controlled local HTTP fixtures and an opt-in existing Qwen model.

**Spec:** `docs/superpowers/specs/2026-09-12-portable-mg-task-design.md`.

## Constraints

- Preserve dirty HANDOFF.md, live MG state, original Atlas and old POC fingerprints.
- No retries of uncertain model calls, raw-output repair, remote jobs or push.
- Maintain separate pytest processes for Engram POC and portable-task tests.
- Record full source hashes, actual model identity, raw replies and unverified
  user-declared deployment identity without treating them as scientific approval.

## Transport

Files: `atlas/workbench/research_sources.py`, `research_http.py`, minimal
`research_model.py` callsites, and transport tests.

- [x] Reproduce paper timeout blocking a local model in a controlled fixture.
- [x] Add absolute-deadline socket handling and fixed paper/model lanes.
- [x] Verify slow headers/body, no post-deadline dispatch, bounded outstanding
  operations, cleanup and model independence. Document resolver limitation.

## Packet and replay

Files: `research_tasks/{__init__,storage,packet,runner,__main__}.py`,
`tests/research_tasks/test_tasks.py`.

- [x] Test export without private context/graph state and reject source mismatch.
- [x] Implement exact selected question/document packet and full hash validation.
- [x] Test completed replay, interrupted capture, unknown request outcome,
  malformed/unsupported output and changed task/model/code.
- [x] Implement one extraction/review turn with immutable attempt artifacts and
  isolated idempotent Atlas capture; source-only review has no prior memory.

## Provider

Files: `research_tasks/providers.py`, minimal `deploy/stampede/provider.py`
additions, `tests/research_tasks/test_providers.py`.

- [x] Exercise new research protocol and preserved raw/assistant state with HTTP fixtures.
- [x] Reuse Atlas compiler/high-level methods and LocalModel transport, preserving
  existing synthetic behavior, exact dispatch hashes and actual byte budgets.

## Delivery

Files: Makefile, CI, launcher allowlist, user guide and verification report.

- [x] Add `make research-task`, separate tests, CLI and extracted-source smoke.
- [x] Run relevant/full suites, independent review and a bounded real Qwen task;
  replay it with the endpoint unavailable and compare artifact hashes.
- [x] Integrate locally, activate the transport fix with a controlled MG restart,
  verify resumed identity/state and update handoff. Whole-cluster execution and
  multi-researcher comparisons remain the next measured integration slice.
