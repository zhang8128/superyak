# Superyak team mode

A lead (Claude Code or Codex) runs a team of Codex (`gpt-6.1-sol`) and Claude Code workers:
**builders** implement in their own git worktree, **collaborators** research, debate and write
documents read-only. Teams coordinate in a Slack thread per task, publish plans as canvases, and
use local plus shared engram memory. See [docs/team-mode.md](../docs/team-mode.md).

```sh
superyak-runtime team status          # CLI (any op: start, list, spawn, message, collect, end, ...)
superyak-runtime team                 # MCP server over stdio (Claude Code and Codex use this)
make check-team                       # tests (mock agents, no network)
```

## Browser lanes (macOS)

A Claude builder can start the app it builds and test it in a real Chromium, Playwright's headless shell, with no
network beyond its own block of 32 loopback ports (`team_spawn(..., kind="claude", browser=true)`). The browser runs
in a broker beside the worker, outside its sandbox, under a deny-default Seatbelt profile teamd owns. The design and
its known limits are in [the spec](../docs/superpowers/specs/2026-10-08-browser-lane-design.md).

A person turns lanes on; a lead can't:
- `browser_lane: true` in `~/.superyak/team/config.json` or a preset (never in `team_start`'s config). Don't make a
  preset with it until the Mac acceptance run has passed; the run makes its own, and removes it.
- `lane_node` in `config.json`: the absolute path of the node binary the broker runs, outside your home folder and
  every worktree, for example `/opt/homebrew/bin/node`.
- `~/.superyak/team/lane-listeners.json`: the programs that may keep listening while a lane runs. Only Apple's own
  programs, by executable path, in `/System`, `/usr/libexec`, `/usr/sbin` or `/sbin`, never an interpreter; each is
  approved on any port. For example `["/usr/libexec/rapportd", "/sbin/launchd"]`. Approving `/sbin/launchd` (pid 1)
  covers every socket-activated job, such as Remote Login's `*:22`, until that job's own program first accepts a
  connection; from then on the listener is that program's, and it needs its own entry.
  `python3 team/scripts/lane_acceptance.py --list-listeners` prints what is listening now. Stop dev servers, Ollama,
  Postgres and everything else while a lane runs: a lane's turn waits until they are gone. A listener bound only to a
  specific address that isn't loopback (the tailnet's, say) can't be reached from a lane and doesn't count, but a
  lane's own process listening on any address beyond loopback (`*`, a LAN or tailnet address) always fails the check.
- The acceptance run is normally started by Serenity (an agent), in the background, and needs no password. Step 4
  observes a root-owned listener: the run first looks for one that already exists (launchd's `*:22` with Remote Login
  on, or cupsd's 631) and uses it; otherwise it tries `sudo -n -v`, which an agent's Bash tool can't do (macOS caches
  sudo credentials per terminal). If both fail, a person does it, inside step 4 after the D9/D10/D11 rows: the script
  prints `ANDY ACTION: in your own Terminal run: sudo /usr/bin/nc -lk 127.0.0.1 <port>` and waits up to 15 minutes,
  checks that the listener is root-owned and named, then prints `ANDY ACTION: stop it now: press Ctrl-C in that
  Terminal`. Serenity passes each `ANDY ACTION:` line to Andy as soon as it appears. The script never signals that
  listener; if it is still there 10 minutes after the request, the row is BROKEN with `sudo kill <pid>` and the run
  stops. Andy's own terminal is needed only for this.
- `lane_one_at_a_time: true` in `config.json` lets only one lane run on the Mac at a time. Set it if the acceptance
  run shows that one lane's worker can read another lane's endpoint. An idle browser worker keeps its block, so under
  this setting it holds the Mac's only lane until it is done or stopped.

The profile self-check runs 17 negative probes (each action must be refused by the profile) and
3 positive ones (the lane's own port, its own folder and `node` must work, so the refusals are the profile's doing).
Only one teamd runs per team (a second refuses to start), which is how a lane's port block is known to be live.

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

**Known limit: Bricks' specs need the Bricks change before they run in a lane.** They have to take their ports from
the lane's block (`SUPERYAK_LANE_PORT_BASE`) instead of fixed ones; that change is the Bricks lead's to make.
