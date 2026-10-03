# Team mode integration plan

> **For agentic workers:** Use superpowers:subagent-driven-development to execute this plan.

- [x] Create `team/` component (package, launcher, pyproject, lock, tests) with Superyak names
- [x] `superyak-runtime team` subcommand + runtime tests (no memory-DB gate, args passthrough)
- [x] engram plugin: `team` MCP server, `/engram:team`, `skills/team`, packaging test, 0.4.0
- [x] Makefile `setup-team`/`check-team`, CI `team` job, README row, `docs/team-mode.md`, spec
- [ ] Live config: Codex `[mcp_servers.team]` → runtime, `superyak-team` skill, migrate config
- [ ] Retire team mode from loom codex-pair (7.0.0) in the same sitting
- [ ] Live verification: runtime launch, worker MCP launch, Claude Code + Codex leads, live team,
      security re-probe
