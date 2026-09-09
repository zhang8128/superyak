# Superyak Runtime Consolidation Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the isolated code task; the controller owns source integration and live deployment. Steps use checkbox syntax.

**Goal:** Complete the approved Superyak source and installation migration, retaining existing memories and restoring one scoped Lighthouse receiver.

**Architecture:** Superyak is canonical, with independent Engram and Lighthouse packages. A small stdlib launcher selects the repository's Python environment and the explicitly configured memory home; hooks resolve code from their own installation. The publisher runs as a user LaunchAgent, with existing publisher grants and an explicit Engram receiver.

**Tech Stack:** Python 3.13, uv, SQLite, Python MCP, TypeScript/pnpm, macOS launchd.

**Spec:** User-approved consolidation recommendation in /tmp/architecture-review-20260909.html and this conversation (2026-09-09). Existing receiver behavior is documented in engram/docs/lighthouse-receiver.md.

## Global Constraints

- Canonical source: /Users/kairos/Projects/superyak. Build in the existing /Users/kairos/Projects/superyak-automation worktree.
- Preserve ENGRAM_HOME=/Users/kairos/Projects/engram during this cutover, including root and named-instance stores.
- Do not combine memory databases, publish new memories, expand publisher audiences, or change existing permission expirations.
- Keep hook harness I/O, session binding, and project cwd behavior intact.
- Use the repository virtualenv for hooks and MCP. Do not install dependencies or mutate live stores during health inspection.
- All new behavior is tested with temporary data and no paid model calls.
- Live configuration changes are atomic and backed up. Old sources are frozen with clear redirects; any relocation must preserve dependent paths.
- Integrate existing capture and session messaging branches with preserved ancestry.
- No agent sends messages to other user sessions. Delivery tests use their existing disposable synthetic harness only.
- The controller performs live installation after code validation and review.

### Task 1: Integrate existing branches

Files: existing capture and session messaging changes.
- [x] Fetch origin and create integrate/runtime-consolidation in existing automation worktree.
- [x] Merge origin/feat/codex-session-messaging into the capture-fix history without conflicts.
- [x] Review existing branch changes and their recorded independent reviews.
- [x] Run make check-engram, make check-lighthouse, make check-integration.
- [x] Commit the verified integration merge.

### Task 2: Separate source from state and provide the canonical launcher

Files:
- Modify engram/hooks/nudge.py and engram/hooks/wake.py; harness.py or sleep.py only if required to keep source imports correct.
- Create scripts/runtime.py.
- Create engram/tests/test_runtime_installation.py (and a focused hook test file if needed).
- Modify Makefile, README.md and add docs/runtime-installation.md.
- Do not modify live configs, policies, databases, plugin caches, branches, or other project files.

Interfaces:
- scripts/runtime.py uses only the standard library and runs from any cwd.
- Configuration file comes from --config PATH or SUPERYAK_RUNTIME_CONFIG, default ~/.config/superyak/runtime.json.
- JSON configuration contains memory_home (absolute existing directory) and default_instance (a valid named instance). Require explicit config; never silently create a replacement memory home.
- The source repository is resolved from scripts/runtime.py itself, never from memory_home. Python is source_root/engram/.venv/bin/python.
- Commands: mcp; hook wake|nudge|sleep; publisher; status. Optional --instance NAME before the command overrides the configured default.
- Launcher sets ENGRAM_HOME and ENGRAM_DEFAULT_INSTANCE, preserves other environment variables (including ENGRAM_HARNESS and ENGRAM_RUN_KEY) and caller cwd, and execs the configured Python with the absolute source script. Publisher uses the existing memory home's .engram/lighthouse-daemon.toml and lighthouse_daemon.py.
- Invalid/missing config or missing interpreter fails visibly without creating files.
- status outputs JSON and a nonzero exit when required installation resources are missing or the receiver/publisher is unavailable. It must be usable without importing server, initializing models, migrating stores, or writing to live databases.
- status reports configured source revision (label it configured, not running), source path, interpreter path, memory home, selected instance/db path, receiver state/chosen publishers, socket connectivity, and latest Lighthouse receipt timestamp/id when present. Missing receipt is an honest null, not alone a health failure for a new installation.
- status uses bounded socket connection and readonly SQLite metadata queries. Never output memory/query content, environment secrets, or raw receipt bodies. Represent missing/invalid policies/configs with bounded errors and no traceback dump of data.
- Status should distinguish disabled receiver from enabled but invalid, and identify a disconnected socket. Make no query disclosure during status.
- Hook code imports must come from the installed source even if ENGRAM_HOME contains stale same-named Python modules; data still comes from ENGRAM_HOME. Preserve packaged-wheel usage.
- Add make status invoking scripts/runtime.py status, with explicit configuration documented.

Execution:
- [x] Write subprocess regressions that give ENGRAM_HOME stale module files and prove installed hook imports/data routing; run them red before modifying hooks.
- [x] Write launcher behavior tests using a synthetic source layout/interpreter, controlled cwd/config/env, and temporary stores/socket. Assert actual argv/env/cwd and status output/exit rather than source strings. Cover missing config/interpreter, instance override, unavailable socket, healthy receiver and receipts, missing database, and no writes.
- [x] Implement minimal launcher and import corrections, run focused tests green.
- [x] Document the config example, launch commands, shared installation binding, live-data preservation, restart semantics, publisher supervision, scoped receiver setup, health meaning, and rollback.
- [x] Run the full Engram suite once, integration checks, and git diff --check. Self-review, commit only task files, and record evidence.
- [x] Controller arranges independent task review; fix verified issues and rerun covering tests.

### Task 3: Install and verify

Controller-owned operational task, after Task 2:
- [x] Back up affected user config files and take SQLite online backups of affected live stores. Record paths, hashes and permission modes without secrets.
- [x] Review the final combined branch; integrate to canonical main with ordinary Git history and preserve both prior PR ancestries.
- [x] Write ~/.config/superyak/runtime.json with the existing memory_home and default_instance=engram.
- [x] Point Codex MCP/hooks and Claude/plugin bindings at scripts/runtime.py using canonical source Python. Preserve unrelated settings and run keys.
- [x] Install a user LaunchAgent to run publisher under the canonical launcher; retain existing publisher policy and shares.
- [x] Enable only receiver engram -> publisher lighthouse, using existing memory/technical, session-recall, recall/read/inject_context grants; keep existing expiry.
- [ ] Verify fresh MCP initialization exposes receiver arguments; test live delivery and persisted receipt without publishing synthetic material. Run denial/withdrawal controls in the disposable pilot.
- [x] Verify hook capture, installed code origins, original data paths, health, supervised restart and clean source trees.
- [x] Freeze standalone development with explicit canonical pointers. Retain data and compatibility paths while old sessions exist; do not break active sessions by moving their modules.
- [x] Document operational evidence, backup/rollback paths, canonical source, and any unavoidable existing-session reconnect requirement.


Execution evidence: docs/reports/2026-09-09-runtime-consolidation.md. Live recall/receipt verification is pending a legacy MCP writer releasing the original receiver database; no successful live crossing is claimed.
