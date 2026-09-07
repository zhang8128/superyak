# Codex Task 8 Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Codex Task 8 identity, fail-open, routing, and silent mutation attribution after the final branch review.

**Architecture:** Harden the existing runtime binding boundary, keep Stop cleanup independently fail-open, preserve the caller's project cwd while using Engram's uv project, and add one append-only operation log populated by a shared wrapper around mutating MCP tools. Existing domain schemas and tool return shapes remain unchanged.

**Tech Stack:** Python 3.14, SQLite migrations, FastMCP decorators, pytest, Codex TOML.

## Global Constraints

- Codex ignores inherited `CLAUDE_SESSION_ID`; Claude continues to prefer it.
- Valid runtime keys match exactly `codex:<decimal-pid>`; malformed input falls back without binding.
- Missing bindings, migrations, malformed input, and hook failures remain fail-open.
- Stop cleanup must attempt close even when binding cleanup fails.
- MCP preserves the caller's cwd while using `/Users/kairos/Projects/engram` as its uv project.
- Operation logging is best-effort, append-only, silent, and never gates a domain mutation.
- Existing output, orientation, reviewer-child suppression, and assessment behavior remain unchanged.

---

### Task 1: Harden binding identity and Stop cleanup

**Files:**
- Modify: `hooks/harness.py`, `storage.py`, `server.py`, `hooks/sleep.py`
- Test: `tests/test_harness.py`, `tests/test_session_bindings.py`, `tests/test_server_registry.py`, `tests/test_nudge_harness.py`

**Interfaces:** `valid_codex_run_key(value: object) -> str | None`; Codex resolution ignores `CLAUDE_SESSION_ID`; `sleep()` never propagates cleanup/close errors.

- [ ] Write failing tests for malformed run keys, Codex with a decoy Claude session, and cleanup failure where `clear_session_binding` raises but `close()` is still attempted.
- [ ] Run the focused tests and confirm each fails for the expected pre-fix reason.
- [ ] Add one shared `^codex:[0-9]+$` validator and apply it in raw hook helpers, Storage bind/resolve/clear, and server resolution.
- [ ] Change server resolution to use `CLAUDE_SESSION_ID` only when `ENGRAM_HARNESS != "codex"`.
- [ ] Wrap sleep binding cleanup and close independently in nested broad exception guards.
- [ ] Run `pytest -q tests/test_harness.py tests/test_session_bindings.py tests/test_server_registry.py tests/test_nudge_harness.py tests/test_wake.py` and commit.

### Task 2: Preserve project cwd in MCP routing

**Files:**
- Modify: `/Users/kairos/.codex/config.toml` (Engram MCP command only)
- Test: `tests/test_codex_config.py` (create)

**Interfaces:** MCP command uses `uv run --project /Users/kairos/Projects/engram python /Users/kairos/Projects/engram/server.py`; process cwd remains Codex's caller cwd.

The Codex config is machine-local by design (`~/.codex/config.toml`). The
tracked `.mcp.json` is Claude Code's separate registration and is not changed
to the Codex launcher.

- [ ] Add a config assertion test that parses TOML and requires `--project`, the absolute server path, no `--directory`, and unchanged environment/approvals.
- [ ] Run it RED against the current `--directory` launcher.
- [ ] Change only the MCP command/args in `~/.codex/config.toml` to use `--project` and the absolute script path.
- [ ] Run the config test plus `codex mcp list` and a temporary non-Engram cwd instance-routing smoke check.
- [ ] Record whether hook hashes remain unchanged and commit the repository test/documentation if applicable.

### Task 3: Add append-only operation attribution

**Files:**
- Create: `migrations/025_operation_log.sql`
- Modify: `storage.py`, `server.py`
- Test: `tests/test_operation_log.py` (create), `tests/test_server_registry.py`

**Interfaces:** `Storage.add_operation(operation, session_id, harness, model, repo, target_ids, details, outcome) -> str`; `_mutation_logged` wraps mutating MCP functions and records one best-effort row after each call.

- [ ] Write failing Storage and wrapper tests asserting exact schema, registry provenance fields, target extraction, silent logging failure, and unchanged tool return values.
- [ ] Run those tests RED.
- [ ] Add migration 025 with `id`, `timestamp`, `operation`, `session_id`, `harness`, `model`, `repo`, `target_ids`, `details`, and `outcome`, plus indexes on session/timestamp.
- [ ] Implement `Storage.add_operation` with JSON serialization and broad fail-open handling.
- [ ] Implement `_mutation_logged` using `functools.wraps`; query the authoritative registry row, call the tool, derive target IDs from its result/arguments, and log without changing exceptions or return values.
- [ ] Apply the wrapper to every mutating tool: `remember`, `log_outcome`, `instinct_feedback`, `challenge_instinct`, `retire_instinct`, `compress_commit`, `mark_core`, `unmark_core`, `unmark_core_batch`, `add_anchor`, `propose_retirement`, `revive`, `assessment_schedule`, `assessment_report`, `reindex`, `reflect`, `task_focus`, `task_update`, `task_done`, `dream_capture`, `dream_react`, `jot`, `erase`, `graph_view` (suggestion logging), `clipboard_pin`, `clipboard_unpin`, `clipboard_remind`, `clipboard_dismiss`, and `clipboard_view` (state advancement). Read-only tools remain unwrapped.
- [ ] Run focused operation/server tests, then the complete suite, and commit.

### Task 4: Live acceptance, documentation, and review

**Files:**
- Modify: `docs/superpowers/plans/2026-07-11-engram-codex-harness.md`, Task 8 evidence report

- [ ] Run the full suite and focused identity, routing, malformed-key, and Stop tests.
- [ ] Run fresh Codex identity/status/remember, Thread, reviewer-isolation, and non-Engram-cwd routing probes.
- [ ] Query operation-log rows for representative mutation families and join them to `session_registry`.
- [ ] Run the next feasible Claude continuity check and document any human-only remainder.
- [ ] Update the acceptance checklist with concrete IDs and commands; commit documentation.
- [ ] Package `main...HEAD`, run a fresh whole-branch review, fix all Critical/Important findings, and re-review.
- [ ] Run the final full suite and leave the feature branch clean for the user's merge decision.
