# Atlas Monorepo Implementation Plan

> **For agentic workers:** Use the existing independent import audit and boundary
> review tasks. Controller owns import, root wiring and plan. Reviewers do not edit
> implementation. Verify each slice before integrating it locally.

**Goal:** Make Superyak a self-contained hackathon checkout including Atlas research.

**Architecture:** Add `atlas/` alongside Engram and Lighthouse, preserve the
`workbench` package, wire the existing memory POC to the bundled source, and keep
runtime state under ignored local directories. Subsequent integration joins
interfaces through measured slices rather than merging private histories or schemas.

**Tech Stack:** Python 3.13, existing uv/pytest environment, Atlas stdlib workbench,
optional MCP in Atlas’s own environment, Lighthouse TypeScript conformance tooling.

**Spec:** `docs/superpowers/specs/2026-09-12-atlas-monorepo-design.md`.

## Constraints

- Preserve dirty `HANDOFF.md`, standalone Atlas changes and all existing research state.
- Import only reviewed current workbench files and dependencies; record hashes and source status.
- No live model calls, model downloads, remote jobs, service restarts, or push for this migration.
- Keep explicit external Atlas overrides and existing frozen POC snapshots intact.
- License choice remains an owner decision; record any unresolved gap rather than inventing permission.

## Task 1: Import the current Atlas component

Files: `atlas/workbench/`, `atlas/tests/workbench/`, selected `atlas/docs/`,
`atlas/scripts/`, public seed data, `atlas/pyproject.toml`,
`atlas/README.md`, `atlas/IMPORT-MANIFEST.json`.

- [x] Audit dependencies, public fixtures, license and unsafe/local-state paths.
- [x] Capture an immutable local source snapshot; verify copy hashes and unchanged source files.
- [x] Run imported Atlas tests against isolated projects; resolve migration-specific failures.
- [x] Record upstream baseline versus integration edits and migration scope.

## Task 2: Make the monorepo executable without an external Atlas checkout

Files: `research_poc/__main__.py`, `research_poc/atlas_bridge.py` as needed,
`engram/tests/test_atlas_poc_bridge.py`, `engram/tests/test_atlas_monorepo.py`,
`Makefile`, `.github/workflows/ci.yml`, `scripts/atlas.py`, `.gitignore`.

- [x] Write failing tests for bundled source resolution and root offline demo/CLI behavior.
- [x] Add root pilot/CLI/test commands with isolated data paths and explicit project selection.
- [x] Update POC default and tests; external override remains available.
- [x] Add Atlas to setup/check/CI and validate its real Lighthouse artifacts.

## Task 3: Source distribution and fresh checkout

Files: `deploy/stampede/launcher.py`, appropriate bundle tests, component metadata.

- [x] Add failing archive test for Atlas/POC files and exclusions.
- [x] Extend allowlisted staging to carry executable Atlas data/assets and POC source.
- [x] Extract source archive and run pilot/help without local editable imports.
- [x] Confirm bundling does not change the current synthetic launch workflow.

## Task 4: Plan, review and local integration

Files: root `README.md`, `docs/monorepo-migration.md`, `docs/atlas-research-poc.md`,
`docs/atlas-integration.md`, a verification report; owner-approved license if supplied.

- [x] Document exact next interfaces, parallel work, done checks, and research-quality limits.
- [x] Run full appropriate regression checks and independent review; resolve material findings.
- [x] Commit and integrate locally, preserving original dirty work and snapshots.
- [x] Update the handoff with completed behavior and next bounded work; no running process is migrated implicitly.
