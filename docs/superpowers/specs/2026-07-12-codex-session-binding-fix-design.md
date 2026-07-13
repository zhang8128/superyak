# Codex Session Binding and Sleep Fail-Open Fix

**Date:** 2026-07-12
**Status:** Approved design
**Scope:** The two blockers found during Task 8 live acceptance of the Codex harness

## Context

The Codex harness successfully delivers orientation, nudges, MCP access, and
review-child suppression. Live verification exposed two remaining defects:

1. A Codex hook receives the real Codex `session_id`, model, and cwd, while the
   independently launched Engram MCP server receives none of that dynamic
   identity. The server therefore generates a UUID. MCP writes join a
   model-less registry row rather than the model-bearing hook row.
2. `hooks/sleep.py` opens SQLite and loads `sqlite_vec` before entering its
   protective `try/finally`. An extension-load failure can make the Stop hook
   exit nonzero and leak the open connection.

The conceptual requirement is one shared Engram identity with distinguishable
perspectives. A hook and MCP calls belonging to one Codex encounter must share
one session identity. GPT/Claude provenance remains silent during normal work
and available only for explicit post-analysis.

## Decision 1: Explicit Runtime Binding

Use an internal runtime key shared by the hook subprocess and MCP subprocess to
bind both to the hook's authoritative session row. Do not infer identity from
timestamps, repository paths, or the configured default model.

### Runtime key

Codex launches both registered hooks and stdio MCP servers as child processes.
Their launcher shells will export:

```text
ENGRAM_RUN_KEY=codex:<codex-parent-pid>
```

The existing hook commands already use `sh -c`; they will export a key derived
from that shell's `$PPID`. The MCP registration will change from launching `uv`
directly to a `sh -c` wrapper that exports the same key and then `exec`s `uv`.

Before changing production configuration, an isolated probe must demonstrate
that SessionStart and MCP launcher shells observe the same parent PID in TUI and
`codex exec`. If an extra launcher layer makes them differ, a small helper will
walk process ancestry to the nearest common Codex process. Approximate
timestamp correlation is not an allowed fallback.

Changing the hook command strings invalidates their trusted hashes. Task 8 live
verification must therefore include one deliberate hook re-approval.

### Storage

Migration 024 adds a runtime-only mapping:

```sql
CREATE TABLE IF NOT EXISTS session_bindings (
    run_key    TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    bound_at   TEXT NOT NULL
);
```

`session_registry` remains the durable provenance record. It continues to hold
`session_id`, harness, model, repo, and start time. `session_bindings` only
answers which durable session belongs to the current client process.

SessionStart performs these writes in order:

1. Upsert the authoritative `session_registry` row from the hook payload.
2. Upsert `run_key -> session_id` in `session_bindings`.
3. Continue orientation generation.

The binding upsert replaces an older value for the same key, making OS PID reuse
safe once the new SessionStart hook has run. Bindings are not rendered by
orientation, recall, reflect, or MCP tool output.

The Stop hook deletes its run-key binding after dream capture, best-effort. A
crash may leave a stale row, but stale rows are inert: a later SessionStart with
the same OS PID overwrites the mapping before that session can make an MCP tool
call. This patch adds no periodic cleanup job.

### MCP identity resolution

Engram's MCP server remains lazily initialized on the first tool call. During
initialization it resolves session identity in this order:

1. `CLAUDE_SESSION_ID`, preserving the existing Claude Code path.
2. For `ENGRAM_HARNESS=codex` with `ENGRAM_RUN_KEY`, look up the binding and use
   its authoritative `session_id`.
3. Generate a UUID as the fail-open fallback for untrusted/skipped hooks,
   pre-migration stores, malformed keys, or standalone server runs.

After resolution, the existing server-side `session_registry` COALESCE upsert
runs unchanged. For a bound Codex session it targets the hook's existing row,
preserving its model and repository. Episodes and session-log events then carry
the same session ID as wake, nudge, sleep, and assessments.

Binding lookup is best-effort and never gates MCP availability or writes. A
missing binding loses model-level provenance but not memory functionality.

## Alternatives Rejected

### PID-keyed sidecar file

A temporary JSON file could carry the hook payload to MCP without a migration.
It introduces atomic-write, cleanup, stale-file, permission, and PID-reuse
failure modes. The instance database is already the coordination boundary and
is safer.

### Latest matching registry row

Selecting the newest Codex row for the same repository would avoid config
changes but cross-wire concurrent sessions. Repository plus timestamp is not an
identity.

### Static MCP model attribution

Adding the configured model to the MCP environment would populate the missing
column but not unify session identity. It also becomes wrong when a user changes
models for one thread. This would repair the symptom while leaving assessment
continuity and per-session analysis incorrect.

## Decision 2: Sleep Hook Fails Open Across Connection Setup

Keep the sleep repair local to `hooks/sleep.py`:

1. Initialize `conn = None` before database setup.
2. Put SQLite connection creation, busy timeout, extension enabling,
   `sqlite_vec.load`, row-factory assignment, queries, and commit inside one
   fail-open `try` boundary.
3. Catch all exceptions at the hook boundary because Stop hooks are explicitly
   non-critical.
4. In `finally`, close the connection whenever creation succeeded, including
   partial extension-load failures.

The existing early returns for a missing database or missing `sqlite_vec`
package remain. No error text is emitted into model context, and the process
returns zero.

`hooks/nudge.py` has a similar pre-existing connection shape, but it is outside
this Task 8 repair. Hardening it should be a separate change so this patch stays
traceable to the live-review blocker.

## Testing

### Runtime binding tests

- Migration 024 creates `session_bindings` with the exact schema above.
- Binding upsert and lookup round-trip a run key and session ID.
- Rebinding the same run key replaces the older session ID.
- Stop deletes its binding without deleting the durable registry row.
- Missing table, missing key, and malformed data fail open.
- MCP initialization under Codex adopts the bound hook session ID.
- The server's COALESCE stamp preserves the hook's model and repo.
- An MCP `remember()` episode joins the model-bearing Codex registry row.
- Claude Code continues to prefer `CLAUDE_SESSION_ID` and ignores a Codex run
  key inherited accidentally.
- No binding falls back to a generated UUID.
- Two concurrent run keys in one repository remain isolated.

### Sleep tests

- Force `sqlite_vec.load()` to raise after connection creation.
- Verify `sleep()` does not raise or emit output.
- Verify the partially initialized connection is closed.
- Preserve the existing successful Codex Stop test proving residues carry the
  payload session ID.

### Full and live verification

1. Run the complete pytest suite.
2. Re-approve the changed hook commands.
3. Start an interactive Codex session in the Engram repo.
4. Call `status()` and `remember()`.
5. Verify the probe episode joins a registry row with `harness='codex'`, the
   active model, and the correct repo.
6. Verify orientation and Thread delivery remain unchanged.
7. Run codex-pair and confirm reviewer children still contain no orientation.
8. Run a Claude Code session and verify its provenance path is unchanged.

## Non-goals

- No provenance labels in orientation, recall, reflect, or normal tool output.
- No behavioral specialization by harness.
- No retrospective repair of existing model-less rows.
- No general hook connection refactor.
- No change to assessment scheduling or content.
