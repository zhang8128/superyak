# Stampede3 Launch Implementation Plan

> **For agentic workers:** Use the dispatching-parallel-agents skill for the independent file ownership below; use test-driven-development for each component and review integration before delivery.

**Goal:** A single launch command prepares and starts the Intel research campaign without needing patient or participant details.

**Architecture:** A local allowlisted source bundle and resumable SSH launcher feed isolated remote bootstrap and Slurm node workers. Each node runs bounded memory experiments using a local model service, with durable snapshots and inspectable results.

**Tech Stack:** Python 3.12+, standard-library deployment client, Engram SQLite/storage/sharing, Intel vLLM/SYCL, Slurm/ibrun, pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-stampede-launch.md`

## Global constraints

- Preserve existing uncommitted work and private memory; no actual remote deployment during preparation.
- Startup is independent of patient and participant details.
- Source files are allowlisted; local credentials, memory, and clinical files are excluded.
- Implement the shared JSON and function interfaces in the spec. Use lazy imports at component boundaries so independent tests can run.
- Parallel workers own disjoint files. No worker creates subagents or commits another worker's files.
- Tests run with `/Users/kairos/Projects/superyak/engram/.venv/bin/python`, with the worktree root and its `engram` on `PYTHONPATH`.

## Task 1: Launcher and staging

Own `deploy/__init__.py`, `deploy/stampede/__init__.py`, `deploy/stampede/__main__.py`, `deploy/stampede/config.py`, `deploy/stampede/launcher.py`, `deploy/stampede/config.example.json`, and `engram/tests/test_stampede_launcher.py`.

- [x] Write tests that call `prepare_bundle(source, destination)` on real temporary trees and inspect archive members; a seeded `.engram` or key file must never appear. Test shell metacharacters in config and duplicate deployment reconciliation through a recording SSH/Slurm boundary.
- [x] Run these tests red, then implement bounded config validation, deterministic staging, generated Slurm script, and `plan/deploy/status/fetch` commands. The batch body invokes the shared cluster entry point. `simulate` lazily imports controller-owned `deploy.stampede.simulate.main`.
- [x] Add durable local run state and remote submission reconciliation. Report ambiguous SSH disconnects honestly and never blindly resubmit.
- [x] Verify behavioral tests and write `.superpowers/stampede/launcher-report.md` with interfaces, commands, limitations, and test results.

## Task 2: Remote bootstrap and node workers

Own `deploy/stampede/bootstrap.sh`, `deploy/stampede/cluster.py`, `deploy/stampede/profiles.py`, and `engram/tests/test_stampede_cluster.py`.

- [x] Test bootstrap/worker behavior with a fake process boundary: independent probe failures, job expiry, cell assignment across ranks, restore, and continued execution of unrelated cells.
- [x] Implement isolated run-local Python setup and pinned Intel backend profiles verified against official upstream sources. Probe vLLM and SYCL independently within bounded time and retain both result logs; use a successful compatible branch for the campaign. Do not silently run inference on login nodes.
- [x] Implement `python -m deploy.stampede.cluster batch --run-dir PATH` and node-worker mode. Fan out through TACC `ibrun`, one owner per node; assign cells from `build_cells(config)` and call `run_cell` with `LocalModel`.
- [x] Keep node-local live stores and consistent snapshots in the durable run directory. Log host/device/package/model revisions and failures. Stop work before job expiry, terminate child servers, and return usable status.
- [x] Verify tests and write `.superpowers/stampede/cluster-report.md` with commands and exact deployment assumptions.

## Task 3: Individual/shared memory experiments

Own `deploy/stampede/experiment.py`, `deploy/stampede/corpus/`, and `engram/tests/test_stampede_experiment.py`.

- [x] Write a failing real-storage test where separate agents retain distinct histories, sharing exposes only an explicit selected publication, and restarting skips completed turns.
- [x] Implement `build_cells(config)` with the factorial combinations and four serial references; deterministic IDs and explicit seed/kind. Implement `run_cell` with bounded concurrency, deadlines, actual Engram Storage and sharing, task packets, provenance, structured publication choices, and atomic results.
- [x] Add a synthetic evidence sequence with a later correction and source ancestry. Record that the corpus is synthetic. Keep enough metadata for independent evaluation and recovery; do not fabricate model usage.
- [x] Test all memory conditions, data isolation, bad model responses, interrupted turns, and complete snapshot restoration. Write `.superpowers/stampede/experiment-report.md`.

## Task 4: Provider, simulation, and integration (controller)

Own `deploy/stampede/provider.py`, `deploy/stampede/simulate.py`, `engram/tests/test_stampede_provider.py`, `engram/tests/test_stampede_integration.py`, root Makefile/README and `docs/stampede3-deployment.md`.

- [x] Start a real local test HTTP server; test correct bounded chat completion parsing, mismatched model, errors, timeouts, redirects, and absent usage. Implement the explicit local provider boundary without changing the existing fixed-origin Responses provider.
- [x] Add a clearly labeled deterministic simulation using the actual experiment APIs. Verify a whole small matrix, distinct stores, results, and resume without extra completed turns.
- [x] Wire one launch command and a double-click local wrapper if useful. Document exact connection/account configuration, plan/launch/status/fetch/resume commands, source exclusions, and unverified hardware checks.
- [x] Finish the parallel research worksheet revision, including 16 cells plus four reference runs and wave/node-hour accounting. Update report/handoff to match the executable scope.
- [x] Run all relevant tests, the offline campaign, archive inspection, shell syntax checks, and repository integration checks; conduct independent component and whole-change review. Integrate only owned changes into the user's working checkout.

Local integration completed on `main` at `e417885`. Verification and independent review are recorded in `docs/superpowers/reviews/2026-09-12-stampede-verification.md` and its linked review. Main-checkout plan and full rehearsal passed; repetition made zero additional scripted calls. No remote deployment or push occurred.
