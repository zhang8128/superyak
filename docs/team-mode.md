# Team mode

A lead (Claude Code or Codex) runs a small team of agents on a goal. Team mode is a
**developer-agent orchestrator**: it drives the Codex and Claude Code CLIs on git worktrees and
private rooms. It is not the medical pilot's bounded research-agent pool
([pilot plan](medical-lighthouse-pilot-plan.md)) or Atlas's `WorkerRotation`, and it must never
carry patient or participant data. Slack is off unless configured.

## Using it

| From | How |
|---|---|
| Claude Code | `/engram:team <goal>`, or the `team` MCP tools (`plugin:engram:team`) |
| Codex | the `superyak-team` skill, or the `team` MCP tools (`[mcp_servers.team]`) |
| Any shell | `superyak-runtime team <op> key=value ...` (e.g. `status`, `list`) |

Lead tools: `team_start(goal, preset, config, name)`, `team_list`, `team_plan(title, markdown)`,
`team_spawn(task, kind, mode, context)`, `team_message`, `team_status`, `team_collect`,
`team_stop`, `team_post`, `team_end`. Every lead tool takes an optional `team` (several teams can
run in one repo). Worker tools: `team_post`, `team_read`, `team_message`, `team_plan`,
`team_ask_lead`, `team_status`, `team_done`.

### Workers

| | `build` | `collab` |
|---|---|---|
| Purpose | implement | research, debate, plan, review, write |
| Files | own worktree (`team/<team>/<wN>` branch) | read-only; private room outside the repo |
| Output | commit made by the daemon on `team_done` | documents (`team_plan` → Slack canvas) + summary |
| Peer messages | pull-only (`team_read`) | live; can wake the recipient (turn budget) |
| Kinds | `codex` (`gpt-6.1-sol`) or `claude` | same; web search for Claude collaborators only |

### Presets and per-team config
Presets `build`, `research`, `review`, `mixed`, plus custom ones in
`~/.superyak/team/presets.json`. Per-team overrides (validated, see `teamlib.TEAM_KEYS`):
`max_workers`, `default_mode`, `default_kind`, `codex_model`, `codex_effort`, `claude_model`,
`collab_max_turns`, `peer_limit_build`, `peer_limit_collab`, `collab_web_search`,
`slack_channel`, `engram_tool_prefix`.

### Slack
Create the app from `team/superyak_team/slack-manifest.yml` (Superyak Team), invite
`@superyak-team` to the channel, and store its bot token:
`security add-generic-password -U -a "$USER" -s superyak-team-slack-bot -w`.
`~/.superyak/team/config.json` holds `slack_channel` and `allowed_user_ids` (only those users'
replies reach agents). Kickoff message per team; one thread per task; plans as canvases.

### Memory
Each worker's engram project root is its own folder (the repo's `.engram/config.toml` is copied
in), so nothing is written to the repo. Durable learnings are shared with
`share(..., audience="group:agent-team")` and recalled with `lighthouse_context`.

## Security model (all verified live 2026-10-02)
- **Caller auth:** token = HMAC(master key in the Keychain, per-caller secret file). Codex's
  sandbox reads files but not the Keychain; Claude workers reach the Keychain but cannot read the
  team home. No worker can forge the lead's or a teammate's token.
- **Codex workers:** `web_search="disabled"` (Codex searches by default), every
  `[mcp_servers.X]` except team/engram and every enabled Codex plugin switched off; workers
  cannot commit (Codex protects `.git`), the daemon commits for them.
- **Claude workers:** `--permission-mode dontAsk` with explicit allow rules; OS sandbox denies
  reading `$HOME` except the worker folder, repo and dev-tool paths, and `**/.env*` everywhere;
  no WebFetch.
- **Messages:** everything external reaches agents fenced as quoted data; outbound text is
  secret-redacted; builder peer messages are pull-only; per-pair loop guards escalate to the lead.

State: `~/.superyak/team/` (teams, rooms, config, presets); sockets in `/tmp/sy-team-<uid>/`.
Tests: `make check-team`.
