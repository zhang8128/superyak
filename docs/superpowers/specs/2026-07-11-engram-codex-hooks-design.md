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
- **Input:** parse stdin JSON. Probe-verified (2026-07-11, Codex 0.144.1):
  Codex clones Claude Code's hook payload format field-for-field —
  `hook_event_name`, `session_id`, `transcript_path`, `cwd`, `model`,
  `permission_mode`; UserPromptSubmit adds `prompt`, Stop adds
  `stop_hook_active` + `last_assistant_message`. Because shapes are
  indistinguishable, harness selection MUST stay explicit (env), never
  sniffed. `sleep.py` needs only `session_id` from the payload.
  Env-leak hazard (probe-observed): a Codex child spawned from a Claude
  Code session inherits `CLAUDE_*` env vars — the codex shim must never
  read them.
- **Output:** plain text on stdout, nothing else. **Hard contract:** Codex
  parses JSON stdout as control flow (`"continue": false` stops the
  session), so the Claude JSON envelope must never leak through the codex
  path. Enforced by regression test. Probe-verified: plain stdout from
  SessionStart AND UserPromptSubmit both inject into model context.
- **Interactive gate:** probe-verified that the payload carries NO
  exec-vs-TUI discriminator (`source: "startup"` both ways) and that exec
  runs hooks. The gate is therefore environmental: skip when
  `ENGRAM_WAKE=skip` (any harness) or, on the codex shim, when
  `CODEX_PAIR_SESSION_ID` is present (codex-pair review children inherit
  it from the driving Claude session — free, reliable detection). Applies
  to all three hooks. Consequence: a manual `codex exec` run by the user
  wakes — acceptable; the decision's intent was that *reviews* stay lean.

### 2. Registration (config only, no code)

Hook registration (probe-corrected): hooks do NOT go in `config.toml`.
Codex discovers `<config_folder>/hooks.json` — i.e. `~/.codex/hooks.json`
(user scope) and `<repo>/.codex/hooks.json` (project scope) — in **Claude
Code's exact hooks.json format** (`HooksFile { description, hooks }`).
Register user-scope with the three commands prefixed `ENGRAM_HARNESS=codex`,
timeouts 10/10/5 s.

**Trust gate (probe-discovered):** Codex silently skips hooks with no
persisted `trusted_hash` — this is why misregistered/untrusted hooks fail
with zero symptoms. One-time interactive approval in the Codex TUI
(startup hooks review) persists trust; re-approval needed whenever the
command line changes (hash mismatch → `Modified` → skipped).
`--dangerously-bypass-hook-trust` exists for automated verification only.

`~/.codex/config.toml` gets only the MCP server, mirroring Claude's
`.mcp.json` registration:

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

## Probe findings (2026-07-11, Codex 0.144.1 — all four items resolved)

Probed via isolated `CODEX_HOME` + `codex exec --dangerously-bypass-hook-trust`
with marker-echo hooks; payloads captured to files:

1. Registration lives in `~/.codex/hooks.json` (or `<repo>/.codex/hooks.json`),
   Claude Code's hooks.json format verbatim. Hooks are trust-gated per
   handler hash; untrusted hooks are skipped silently.
2. UserPromptSubmit plain stdout injects into model context (marker
   appeared in the model's reply). Same for SessionStart.
3. No interactive/exec discriminator exists in the payload
   (`source: "startup"` in both). Gate is environmental:
   `ENGRAM_WAKE=skip` + `CODEX_PAIR_SESSION_ID` detection.
4. Stop hooks fire in exec mode (and receive `last_assistant_message`).
   Payload format across all events is identical to Claude Code's.
