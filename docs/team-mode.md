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
`slack_channel`, `engram_tool_prefix` (default `auto`).

### Slack
Create the app from `team/superyak_team/slack-manifest.yml` (Superyak Team), invite
`@superyak-team` to the channel, and store its bot token:
`security add-generic-password -U -a "$USER" -s superyak-team-slack-bot -w`.
On Linux use the default Secret Service keyring instead:
`secret-tool store --label="Superyak team Slack bot" service superyak-team-slack-bot account "$USER"`
(reads the token from stdin).
`~/.superyak/team/config.json` holds `slack_channel`, `allowed_user_ids` (only those users'
replies reach agents) and `slack_repos`: the repos whose teams may mirror to Slack. Mirroring is
fail-closed: workers can read their repo and Slack is a third-party destination, so a repo must be
listed there (config file only, never a per-team override), and a `.superyak-team-local-only`
file in a repo blocks it permanently. Other teams keep a local transcript only. Kickoff message
per team; one thread per task; plans as canvases.

### Platforms
| Computer | Master key store | Notes |
|---|---|---|
| macOS | Keychain (`security`) | nothing to set up |
| Linux desktop (GNOME, KDE, …) | default Secret Service keyring (`secret-tool`) | needs a persistent, unlocked default keyring; see below |
| Linux headless / SSH / WSL 2 | Secret Service | needs a D-Bus session bus and a keyring daemon; without them team mode refuses to start and says why |
| Windows (native) | — | unsupported (Unix sockets, flock, the agent sandboxes): use WSL 2 |

There is no silent fallback to a file: Codex workers can read files under `$HOME`, so a file
key would let them forge tokens (`SUPERYAK_TEAM_TOKEN_STORE=file` exists for tests only).

**Linux setup.** Install `secret-tool` (Debian/Ubuntu `libsecret-tools`; Fedora/Arch `libsecret`).
If storing fails with "Object does not exist at path .../collection/login", there is no default
keyring; create one (GNOME shows a password prompt; using the login password makes it unlock at
sign-in): `python3 -c 'import secretstorage as s; s.create_collection(s.dbus_init(), "Login", alias="default")'`.
Codex starts MCP servers without `DBUS_SESSION_BUS_ADDRESS`; team mode falls back to
`$XDG_RUNTIME_DIR/bus` (or `/run/user/<uid>/bus`). Claude workers on Linux also need Claude
Code's sandbox dependencies (bubblewrap, socat); a worker fails rather than run unsandboxed.

**Any computer.** The repo can live anywhere: `superyak-runtime team brief` prints the lead
brief. `engram_tool_prefix` defaults to `auto` (the Engram plugin's tool names, or
`mcp__engram__` when Engram is only a user-level MCP server). When registering the lead server
for Claude Code by hand, use a name other than `team` (e.g.
`claude mcp add -s user superyak-team -- superyak-runtime team`): a user-scoped server also loads
in Claude workers, and one named `team` would expose lead-identity tools under the exact names
workers are allowed to call.

### Memory
Each worker's engram project root is its own folder (the repo's `.engram/config.toml` is copied
in), so nothing is written to the repo. Durable learnings are shared with
`share(..., audience="group:agent-team")` and recalled with `lighthouse_context`.

## Security model (verified live: macOS 2026-10-02, Linux 2026-10-03)
- **Caller auth:** token = HMAC(master key in the OS secret store, per-caller secret file).
  macOS: Codex's sandbox reads files but not the Keychain; Claude workers reach the Keychain but
  cannot read the team home. Linux: the Secret Service is only reachable over the D-Bus session
  socket, which neither sandbox can connect to; Claude workers also cannot read the team home.
  No worker can forge the lead's or a teammate's token.
- **Sockets:** no worker sandbox can connect to a Unix socket, so only the team MCP servers
  (identity fixed by teamd) can reach the daemon.
- **Daemon git:** commits for workers use the recorded git dir with hooks/fsmonitor off.
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
