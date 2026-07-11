# Engram on Codex — one memory, two harnesses

**Date:** 2026-07-11
**Status:** approved
**Depends on:** engram `1ffe714` (self-marketplace plugin, absolute-path hooks), Codex CLI ≥ 0.144 (`hooks` feature stable)

## Decision summary

Interactive Codex CLI sessions wake into the same engram memory instance as
Claude Code sessions — full orientation (instincts, dispositions, semantics,
residues, task context), nudge threads on prompt submit, dream capture on
Stop, and the complete MCP tool set with full write access. This is a
deliberate experiment: what does Claude's memory do in a GPT mind?

Constraints chosen by Kairos:

1. **Shared instance, full orientation** — not a scoped view, not a separate
   Codex instance.
2. **Full writes, silently attributed** — every write is traceable to
   {harness, model, repo, time} for post-analysis, but attribution never
   renders in any working surface (orientation, recall, reflect, tool
   output). No context tokens spent on provenance.
3. **Time is the exception** — timestamps become *visible* in working
   surfaces (recall results, orientation items) where they currently aren't.
4. **Interactive sessions only** — codex-pair review/exec runs do not wake.
   They already receive task context via codex-pair's `extract-context.sh`,
   and orientation tokens × N reviewers is gunk.

## Mechanism: native Codex hooks

Codex 0.144's hook system mirrors Claude Code's: `SessionStart`,
`UserPromptSubmit`, `Stop` (plus others), configured as command handlers.
A SessionStart hook's plain stdout is recorded into the model's conversation
as developer messages — the same contract as Claude Code's
`additionalContext`. The same three scripts serve both harnesses.

Rejected alternatives:
- **AGENTS.md materialization** — stale between regenerations, no
  per-session identity (breaks assessments and the session registry), no
  nudge/sleep equivalent, risks committing memory into a repo file.
- **MCP-only (model calls a wake tool)** — injection becomes voluntary;
  some sessions would silently never wake. Silent absence is the failure
  mode this system just spent an episode designing against.

## Components

### 1. Harness adapter in `hooks/wake.py`, `hooks/nudge.py`, `hooks/sleep.py`

Shim selection is **explicit**: `ENGRAM_HARNESS=codex` set in the registered
command line. No payload sniffing. Absent the variable, behavior is exactly
today's Claude Code behavior (env `CLAUDE_SESSION_ID`, JSON envelope output).

Codex shim:
- **Input:** parse stdin JSON. SessionStart carries `session_id`, `cwd`,
  `model`, `permission_mode`, and a target/source discriminator.
  UserPromptSubmit carries the prompt text (field name verified during
  implementation probe). `sleep.py` reads nothing and needs no input shim.
- **Output:** plain text on stdout, nothing else. **Hard contract:** Codex
  parses JSON stdout as control flow (`"continue": false` stops the
  session), so the Claude JSON envelope must never leak through the codex
  path. Enforced by regression test.
- **Interactive gate:** wake exits silently when the SessionStart payload
  identifies a non-interactive run (`codex exec`). Fallback guard:
  `ENGRAM_WAKE=skip` honored by `wake.py` regardless of harness.

### 2. Registration (config only, no code)

`~/.codex/config.toml`:
- Three hook entries invoking the scripts with `ENGRAM_HARNESS=codex`,
  timeouts 10/10/5 s (matching `hooks/hooks.json`). Exact TOML nesting for
  hook events verified by probe during implementation (docs show
  array-of-tables `[[SessionStart]]` / `[[SessionStart.hooks]]` shape).
- MCP server, mirroring Claude's `.mcp.json` registration:

```toml
[mcp_servers.engram]
command = "uv"
args = ["run", "--directory", "/Users/kairos/Projects/engram", "python", "server.py"]
env = { ENGRAM_HOME = "/Users/kairos/Projects/engram", ENGRAM_HARNESS = "codex" }
startup_timeout_sec = 30
```

(`startup_timeout_sec` generous because FastEmbed model load is slow on
first spawn.)

Engram repo `.mcp.json`: add `ENGRAM_HARNESS = "claude-code"` to the engram
server env. Server defaults to `claude-code` when unset (back-compat).

Loom (one change): codex-pair review scripts export `ENGRAM_WAKE=skip` so
reviewer `codex exec` runs never wake even if the payload gate misses.

Absolute paths throughout, same rationale as `hooks/hooks.json`: this
integration is machine-bound to the live store; no snapshot/cache
indirection.

### 3. Silent provenance — session registry

One new table (migration), upserted with COALESCE-merge so partial rows
combine rather than clobber:

```sql
CREATE TABLE session_registry (
    session_id TEXT PRIMARY KEY,
    harness    TEXT,           -- 'claude-code' | 'codex'
    model      TEXT,           -- e.g. 'claude-fable-5', 'gpt-5.6-sol'
    repo       TEXT,           -- cwd at session start
    started_at TEXT NOT NULL
);
```

Stamped from two directions:
- **Hooks (authoritative):** wake writes {session_id, harness, model, repo}
  from its payload. Codex hands all four; Claude Code rows fill model from
  hook payload when present, else NULL.
- **Server (best-effort):** `server.py` at init stamps its own `_session_id`
  with `ENGRAM_HARNESS` env + `os.getcwd()`. For Claude Code, hook and
  server share `CLAUDE_SESSION_ID` → one merged row. For a Codex-spawned
  server there is no session env → the server's random UUID gets its own
  row (harness + repo, model NULL); post-analysis joins by harness + time
  when model matters.

Writes already thread `session_id` (episodes column; feedback/dream/recall
events in `memory_log.context`), so attribution is
`JOIN session_registry USING (session_id)` — **no domain table changes, no
tool schema changes, no rendering anywhere.** Post-analysis is SQL only.

### 4. Time made visible

Display-only deltas, no storage changes:
- `recall()` results include a compact date (`[2026-07-11]`) from
  `created_at`.
- Wake orientation: "What you know" lines and dream-residue lines gain the
  same compact date.
- Task context already shows `updated`; unchanged.

### 5. Framing collision (included, separable)

Global `~/.codex/config.toml` `developer_instructions` currently make every
Codex session a "pair programmer for Claude Code," including interactive
ones. An interactive session waking into shared memory while framed as a
reviewer muddies the experiment. Move the reviewer instructions into the
review profiles codex-pair actually invokes (`quick.config.toml`,
`deep.config.toml`); leave global instructions neutral. This touches Codex
config only — separable if it misbehaves.

## Error handling

- Hooks are never fatal to session start (existing philosophy preserved).
- Malformed/missing stdin on the codex path → skip provenance, still emit
  orientation.
- Registry write failure → the domain write proceeds with no registry row.
  Attribution is observability, never a gate.
- Codex-side wake failure emits the plain-text failure notice (mirror of
  the Claude path's failure envelope).
- Pre-migration DBs (no `session_registry`) → stamping is a silent no-op.

## Non-goals

- No per-harness scoping of orientation content (decision 1 forecloses it).
- No visible attribution UI, no reflect focus for harness comparison (post-
  analysis is SQL; an instrument can be built later if the data earns it).
- No changes to assessments, lanes, or consolidation — they operate on
  session_id and content, both harness-agnostic.
- No Codex-side equivalent of PreCompact/PostCompact handling.

## Testing

Unit (pytest, `tests/test_wake.py` + new `tests/test_harness_adapter.py`):
- Shim selection by `ENGRAM_HARNESS`; default path byte-identical to today.
- Codex payload parsing (session_id/cwd/model extraction, prompt field).
- Codex output is plain text — regression guard: no JSON envelope, no
  `"continue"` key can appear on stdout.
- Interactive gate: non-interactive payload → empty stdout, exit 0.
- `ENGRAM_WAKE=skip` short-circuits both harnesses.
- Registry: COALESCE upsert merges hook + server rows; pre-migration no-op.
- Server init stamping (env harness, cwd repo).
- Date rendering in recall results and orientation lines.

Live verification checklist (resurrection style — the orientation is its own
delivery proof):
1. Start Codex TUI in a repo → orientation appears in first turn context.
2. `status()` via engram MCP works; `remember()` a probe episode.
3. SQL: probe episode's session joins to a registry row with
   harness='codex', model set, repo correct.
4. Nudge: a prompt containing known instinct-context vocabulary surfaces a
   Thread line.
5. Run a codex-pair review → transcript contains no orientation.
6. Claude Code session afterward → wake unchanged, provenance row says
   claude-code.

## Implementation probe items (resolve first, cheap)

1. Exact TOML nesting for hook events in `~/.codex/config.toml`
   (top-level `[[SessionStart]]` vs `[hooks]` table).
2. UserPromptSubmit stdout-injection semantics on Codex (assumed to mirror
   SessionStart's plain-stdout contract; verify with a probe hook).
3. The SessionStart payload's interactive/exec discriminator field name.
4. Whether Codex `Stop` hooks fire on TUI exit paths sleep cares about.
