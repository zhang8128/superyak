# Team mode

A lead (Claude Code or Codex) runs a small team of agents on a goal. Team mode is a
**developer-agent orchestrator**: it drives the Codex and Claude Code CLIs on git worktrees and
private rooms. It is not the medical pilot's bounded research-agent pool
([pilot plan](medical-lighthouse-pilot-plan.md)) or Atlas's `WorkerRotation`, and it must never
carry patient or participant data. Slack is off unless configured.

## Using it

The lead posts as **Mal**; workers are named for Serenity's crew in spawn order (kaylee, wash, zoe,
simon, river, jayne, inara, book, then w9, w10, ...). Use those names wherever a worker is addressed
(`team message worker=kaylee`, Slack threads, branches `team/<team>/kaylee`).

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
`~/.superyak/team/presets.json`. Per-team overrides (validated, see `teamlib.OVERRIDE_KEYS`):
`max_workers`, `default_mode`, `default_kind`, `codex_model`, `codex_effort`, `claude_model`,
`collab_max_turns`, `peer_limit_build`, `peer_limit_collab`, `collab_web_search`,
`slack_channel`, `engram_tool_prefix`. A person sets `browser_lane` in a preset
(`teamlib.PRESET_KEYS`), never in `config.json`, which every team would take; `team_start` never can.

### Browser lanes (macOS)
A Claude builder spawned with `browser=true` runs and tests the app it builds in Playwright's
headless shell, with no network beyond its own block of 32 loopback ports. The browser runs in a
broker beside the worker, under a deny-default Seatbelt profile teamd owns. Setup, the listener
rule and the firewall note are in [team/README.md](../team/README.md#browser-lanes-macos); the
design is [the browser-lane spec](superpowers/specs/2026-10-08-browser-lane-design.md).

### Slack
Create the app from `team/superyak_team/slack-manifest.yml` (Superyak Team), invite
`@superyak-team` to the channel, and store its bot token:
`security add-generic-password -U -a "$USER" -s superyak-team-slack-bot -w`.
`~/.superyak/team/config.json` holds `slack_channel`, `allowed_user_ids` (only those users'
replies reach agents) and `slack_repos`: the repos whose teams may mirror to Slack. Mirroring is
fail-closed: workers can read their repo and Slack is a third-party destination, so a repo must be
listed there (config file only, never a per-team override), and a `.superyak-team-local-only`
file in a repo blocks it permanently. Other teams keep a local transcript only. Kickoff message
per team; one thread per task; plans as canvases.

### Memory
Each worker's engram project root is its own folder (the repo's `.engram/config.toml` is copied
in), so nothing is written to the repo. Durable learnings are shared with
`share(..., audience="group:agent-team")` and recalled with `lighthouse_context`.

## Security model (all verified live 2026-10-02)
- **Caller auth:** token = HMAC(master key in the Keychain, per-caller secret file). Codex's
  sandbox reads files but not the Keychain; Claude workers reach the Keychain but cannot read the
  team home. No worker can forge the lead's or a teammate's token.
- **Sockets:** no worker sandbox can connect to a Unix socket, so only the team MCP servers
  (identity fixed by teamd) can reach the daemon.
- **Daemon git:** commits for workers use the recorded git dir with hooks/fsmonitor off.
- **Codex workers:** `web_search="disabled"` (Codex searches by default), every
  `[mcp_servers.X]` except team/engram and every enabled Codex plugin switched off; workers
  cannot commit (Codex protects `.git`), the daemon commits for them.
- **Claude workers:** `--permission-mode dontAsk` with explicit allow rules; OS sandbox denies
  reading `$HOME` except the worker folder, repo and dev-tool paths, and `**/.env*` everywhere;
  no WebFetch.
- **One teamd per team:** `lane.hold_team` holds the team's lock for teamd's whole life, so a second teamd for the
  same team refuses to start. Browser lanes rely on it: a lane's port block is live exactly while its teamd holds that lock.
- **Messages:** everything external reaches agents fenced as quoted data; outbound text is
  secret-redacted; builder peer messages are pull-only; per-pair loop guards escalate to the lead.

State: `~/.superyak/team/` (teams, rooms, config, presets); sockets in `/tmp/sy-team-<uid>/`.
Tests: `make check-team`.
