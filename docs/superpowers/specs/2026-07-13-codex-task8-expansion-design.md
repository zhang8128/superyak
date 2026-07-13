# Codex Task 8 Expansion: Complete Identity and Silent Attribution

**Date:** 2026-07-13  
**Status:** Approved for implementation by Kairos (“proceed”)

## Goal

Close the final whole-branch review findings without weakening the shared
identity experiment: a Codex encounter must resolve one authoritative Engram
session, all mutating MCP operations must be silently attributable, and hook
failure must remain non-fatal.

## Design

### Identity resolution

Codex and Claude use harness-specific environment precedence. Claude may use
`CLAUDE_SESSION_ID`; Codex ignores that variable and resolves only its
`ENGRAM_RUN_KEY` binding. Run keys are accepted only in the exact
`codex:<decimal-pid>` form. Invalid or missing keys, missing bindings, and
missing migrations return no binding and preserve the generated-UUID fallback.

### Stop fail-open behavior

The Stop hook keeps processing, binding cleanup, and connection close as
independent best-effort operations. Every cleanup/close action is wrapped so a
failure in one cannot prevent the other or produce a nonzero hook exit.

### Project routing

The MCP launcher uses the Engram checkout as the uv project/environment while
preserving the Codex process working directory. Hooks and MCP therefore read
the same project-local `.engram/config.toml` and select the same instance.
The Codex launcher is intentionally installed in the machine-local
`~/.codex/config.toml`; tracked `.mcp.json` remains the Claude Code
registration and must retain `ENGRAM_HARNESS=claude-code`.

### Silent mutation attribution

Migration 025 adds an append-only `operation_log` table with operation name,
session ID, harness, model, repo, timestamp, target IDs, and JSON details.
Every mutating MCP tool records one best-effort operation entry after its
domain mutation. Logging never gates the mutation or changes normal output.
Representative tests cover episode writes, instinct feedback, task context,
core/anchor mutation, dream writes, clipboard/notes, and compression commits.

## Error handling and compatibility

All attribution is observational. Existing domain tables and return shapes
remain unchanged. A missing operation-log table or malformed provenance is
silently ignored. Existing Claude session precedence and reviewer-child skip
behavior remain covered by regression tests.

## Acceptance

- Codex with a decoy `CLAUDE_SESSION_ID` still adopts the hook-bound session.
- Malformed run keys never bind or resolve.
- Stop cleanup and close failures both remain zero-exit and attempt close.
- A Codex process launched from another configured project selects the same
  instance in hooks and MCP.
- Every mutating MCP tool family creates an operation-log row joined to the
  authoritative registry session.
- Existing live identity, Thread, reviewer-isolation, and full-suite checks
  remain green.
