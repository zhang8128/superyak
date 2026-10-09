# Superyak team mode

A lead (Claude Code or Codex) runs a team of Codex (`gpt-6.1-sol`) and Claude Code workers:
**builders** implement in their own git worktree, **collaborators** research, debate and write
documents read-only. Teams coordinate in a Slack thread per task, publish plans as canvases, and
use local plus shared engram memory. See [docs/team-mode.md](../docs/team-mode.md).

```sh
superyak-runtime team status          # CLI (any op: start, list, spawn, message, collect, end, ...)
superyak-runtime team                 # MCP server over stdio (Claude Code and Codex use this)
make check-team                       # tests (mock agents, no network); run it from the repo root: team/ has no Makefile
```

## Browser lanes (macOS)

A Claude builder can start the app it builds and test it in a real Chromium, Playwright's headless shell, with no
network beyond its own block of 32 loopback ports (`team_spawn(..., kind="claude", browser=true)`). The browser runs
in a broker beside the worker, outside its sandbox, under a deny-default Seatbelt profile teamd owns. The design and
its known limits are in [the spec](../docs/superpowers/specs/2026-10-08-browser-lane-design.md).

A person turns lanes on; a lead can't:
- `browser_lane: true` in a preset, never in `~/.superyak/team/config.json` (which every team started on this Mac
  would take) and never in `team_start`'s config (refused). Don't make a
  preset with it until the Mac acceptance run has passed; the run makes its own, and removes it.
- `lane_node` in `config.json`: the absolute path of the node binary the broker runs, outside your home folder and
  every worktree, for example `/opt/homebrew/bin/node`.
- `~/.superyak/team/lane-listeners.json`: the programs that may keep listening while a lane runs. Only Apple's own
  programs, by executable path, in `/System`, `/usr/libexec`, `/usr/sbin` or `/sbin`, never an interpreter; each is
  approved on any port. For example `["/usr/libexec/rapportd", "/sbin/launchd"]`. Approving `/sbin/launchd` (pid 1)
  covers every socket-activated job, such as Remote Login's `*:22`, until that job's own program first accepts a
  connection; from then on the listener is that program's, and it needs its own entry.
  `python3 team/scripts/lane_acceptance.py --list-listeners` prints what is listening now. Stop dev servers, Ollama,
  Postgres and everything else while a lane runs: a lane's turn waits until they are gone. Another user's listener
  bound only to a specific address that isn't loopback (Tailscale's tailnet address, a root service's) can't be
  reached from a lane and doesn't count; one of yours there fails the check while any lane runs, except an approved
  Apple program (sharingd keeps AirDrop on a link-local address: a sealed Apple binary can't be a hidden lane
  process), and a lane's own
  process listening on any address beyond loopback (`*`, a LAN or tailnet address) always fails it. A listener in a
  lane's port block must be that lane's own (it carries the lane's `CLAUDE_CODE_TMPDIR`) or its broker's.
- The acceptance run is normally started by Serenity (an agent), in the background, and needs no password. Step 4
  observes a root-owned listener: the run first looks for one that already exists (launchd's `*:22` with Remote Login
  on, or cupsd's 631) and uses it; otherwise it tries `sudo -n -v`, which an agent's Bash tool can't do (macOS caches
  sudo credentials per terminal). If both fail, a person does it, inside step 4 after the D9/D10/D11 rows: the script
  prints `ANDY ACTION: in your own Terminal run: sudo /usr/bin/nc -lk 127.0.0.1 <port>` and waits up to 15 minutes,
  checks that the listener is root-owned and named, then prints `ANDY ACTION: stop it now: press Ctrl-C in that
  Terminal` (or, if the run stops before it gets there, `ANDY ACTION: stop it now (if you started it): ...`). Serenity passes each `ANDY ACTION:` line to Andy as soon as it appears. The script never signals that
  listener; if it is still there 10 minutes after the request, the row is BROKEN with `sudo kill <pid>` and the run
  stops. Andy's own terminal is needed only for this.
  The ssh-agent wall is tested with `SSH_AUTH_SOCK`; when that is unset (no agent in Serenity's shell) the run tests
  launchd's agent sockets, `/private/tmp/com.apple.launchd.*/Listeners`, and when there are none the row is INFO,
  "no ssh-agent socket on this machine; nothing to protect".
- `lane_one_at_a_time: true` in `config.json` lets only one lane run on the Mac at a time. Set it if the acceptance
  run shows that one lane's worker can read another lane's endpoint. An idle browser worker keeps its block, so under
  this setting it holds the Mac's only lane until it is done or stopped.

While lanes run, the loopback ports 41000–48999 are theirs: lanes take blocks of 32 from that pool, and anything else
listening there waits for the lane or fails its check. Lead calls that can start or end a lane (`team_spawn`,
`team_message`, `team_stop`, `team_end`) wait up to 15 minutes for teamd, since a first install or a lane's cleanup
runs inside them; a teamd that hangs holds the lead that long. Every teamd, lanes or not, holds
`~/.superyak/team/lane-teams/<team>.lock` for its whole life (a second teamd for the same team refuses to start), and
one that restarts with workers reads the lane registry, which creates `~/.superyak/team/lane-ports.lock` and makes
`~/.superyak/team` 0700.

The profile self-check runs 17 negative probes (each action must be refused by the profile) and
3 positive ones (the lane's own port, its own folder and `node` must work, so the refusals are the profile's doing).
Only one teamd runs per team (a second refuses to start), which is how a lane's port block is known to be live.

A browser worker starts with `--strict-mcp-config` and `"disableAllHooks": true`: only teamd's `team` MCP server
loads, and no hook runs, because whatever `claude` starts outside its sandbox inherits the lane's environment
(`NODE_OPTIONS`, and an `npm_config_cache` the worker can write). Its plugins are off too (each one your settings
or the worktree's `.claude/` names is set to `false` in its flag settings). So it has no engram memory. Its preload is teamd's
own file, `~/.superyak/team/teams/<team>/workers/<worker>/lane-preload.cjs`, never one under `/tmp`. A
`managed-settings.json` that defines hooks refuses lanes: Claude Code runs those even under `disableAllHooks`. So does
any `sandbox` key in your `~/.claude/settings.json`, `settings.local.json` or the managed policy, at any depth, except
an empty `network.allowedDomains`: those merge into the lane's sandbox (and `excludedCommands` run fully outside it).
A `managed-mcp.json` refuses lanes, and so does a helper command (`apiKeyHelper`, `awsAuthRefresh`,
`awsCredentialExport`, `gcpAuthRefresh`, `otelHeadersHelper`, `proxyAuthHelper`, `processWrapper`) in your settings or
the managed policy, a `policyHelper`/`policyHelpers` entry in the managed policy, and any plugin the managed policy
turns on (`enabledPlugins` true): flag settings can't switch that one off. A settings file of yours or the worktree's
that could name plugins but can't be fully read (not a regular file, over 1 MB, not JSON) refuses the turn, naming the
file. When a lane ends, teamd ends the processes that listen in its block, have their cwd under it or hold a file under it open; a hard-linked file is never evidence, so a lane can't get another program killed by linking its open file in. A lane also denies writes to the worktree's `.claude/` and `.mcp.json`. Claude Code runs those helpers outside the sandbox with the lane's environment. A lane's own flag settings blank every
helper, so one planted in the worktree's `.claude/` doesn't run either.

The broker's stderr is kept in teamd's folder, `~/.superyak/team/<team>/workers/<worker>/broker-stderr.log`, never in
the lane's folder.

Team mode needs Python 3.11.4 or later for lanes (tarfile's data filter): `cd team && uv sync --locked --python 3.13`
sets one up.

**Keep the macOS firewall's "Block all incoming connections" on while lanes run** (System Settings → Network →
Firewall → Options). A preload keeps a lane's servers on 127.0.0.1, but a child started without it could listen on
every address until the next listener check, up to 60 seconds later.

The first lane fetches the Playwright version the base commit's lockfile names into `~/.superyak/team/broker/`
and installs its headless shell there. A new headless-shell revision runs only once its manifest hash is recorded in
`team/superyak_team/lane/browsers.json`, after `lane_acceptance.py --self-check-only` passes on the Mac. Never point
another Playwright at `~/.superyak/team/broker/browsers`: only sandboxed brokers launch from it.

**Known limit: Codex workers can write `/tmp`.** Codex's workspace-write sandbox allows it, so a Codex worker anywhere
on the Mac could put files in `/tmp/sy-lane-<uid>`. teamd never follows a link there and nothing there decides what
the broker is, but whether to set Codex's `sandbox_workspace_write.exclude_slash_tmp` is Andy's call; Codex workers are
unchanged.

**Known limit: a process that leaves a lane's environment behind.** At the end of every browser turn, teamd ends any
process whose environment still carries the lane's `CLAUDE_CODE_TMPDIR`, so a turn's background leftovers don't
outlive it. When a lane ends, teamd ends the broker, every process with a file under the lane or a listener on its
ports, and every process whose environment still carries that variable. A child that started a new session, cleared
its own environment and holds nothing in the lane escapes all three, until the next listener check finds anything it
listens on.

**Known limit: Claude Code's own transcripts.** teamd scrubs the lane's secret from everything it keeps and sends,
but a worker's Claude Code session transcript (under `~/.claude/projects/`) may hold the lane's endpoint, from a
failing test's output. The secret dies with the lane: each broker gets a new one, and the broker stops when the lane
ends.

**Known limit: a compromised turn can persist instructions for the next one.** A browser turn taken over by page
content could write `CLAUDE.md`, `AGENTS.md` or files under `.claude/`, which the next turn reads at startup. teamd
compares those paths at the start and end of every browser turn and tells the lead, as `INSTRUCTION FILES CHANGED by
<worker> this turn: ...`; it doesn't block, since a task may change them on purpose. The lead reviews them.

**Known limit: a compromised turn can plant instructions in any file the next turn reads, not only instruction
files** (a source comment, a test fixture, a README the task points at). The flag covers the startup files; the lead
reviews the rest of the diff.

**Known limit: lanes share localhost.** With more than one lane, a lane's worker can connect to another lane's
servers; `lane_one_at_a_time` avoids it.

**Known limit: Bricks' specs need the Bricks change before they run in a lane.** They have to take their ports from
the lane's block (`SUPERYAK_LANE_PORT_BASE`) instead of fixed ones; that change is the Bricks lead's to make.
