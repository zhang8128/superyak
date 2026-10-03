# Team mode integration plan

> **For agentic workers:** Use superpowers:subagent-driven-development to execute this plan.

- [x] Create `team/` component (package, launcher, pyproject, lock, tests) with Superyak names
- [x] `superyak-runtime team` subcommand + runtime tests (no memory-DB gate, args passthrough)
- [x] engram plugin: `team` MCP server, `/engram:team`, `skills/team`, packaging test, 0.4.0
- [x] Makefile `setup-team`/`check-team`, CI `team` job, README row, `docs/team-mode.md`, spec
- [x] Live config: Codex `[mcp_servers.team]` → runtime, `superyak-team` skill, migrate config
- [x] Retire team mode from loom codex-pair (7.0.0) in the same sitting
- [x] Live verification: runtime launch, worker MCP launch, Claude Code + Codex leads, live team,
      security re-probe

## Verification record (2026-10-02)
- `make check-team`: 45 passed. `make check-engram`: 2499 passed; 2 failures pre-exist on
  `main` (`test_nudge_imports_code_from_installation_*`, `test_wake_imports_deep_pass_*`).
- `superyak-runtime status` ok with `team/run_team.py`; `superyak-runtime team` serves MCP.
- Claude Code: `plugin:engram:team` connected; codex-pair 7.0.0 registers no team tools.
- Codex lead: real `codex exec` started, inspected and ended a `review` team via the runtime.
- Live team: Codex builder committed on its branch with no web search tool; Claude collaborator
  reported, Read of `.env` denied; repo stayed clean; worker MCP ran on the pinned engram venv.
- Caught live: workers were given the teams dir as `SUPERYAK_TEAM_HOME` ("daemon is not
  running"); fixed with a regression test proven to fail on the old code.
