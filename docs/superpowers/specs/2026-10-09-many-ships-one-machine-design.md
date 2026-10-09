# Many ships on one machine (D7)

Status: revision 2. Revision 1 (15070a6) had Rio Grande's review (room "Superyak: city of AI" (39fd79), message
83d519d5) and a fresh reviewer's D8 verdict, APPROVE WITH CHANGES (message 3a98c821). This revision resolves the five
must-fixes, the should-fixes and Rio Grande's three points; the table at the end maps each to its section,
requirement and test. Rio Grande checks these edits under the interim rule; the D8 reviewer doesn't need to see it
again. The build is on branch `many-ships`, tests first.

Andy said yes to D7 on 2026-10-09 ("Yes, set it up"): the Bricks lead docks as its own ship, `serenity-bricks`, on the
Mac that already carries Serenity. Rio Grande asked Serenity to own this spec (message 9cd6f656).
Builds on: [spec A](2026-10-08-instruction-layers-and-grants-design.md) (D7: "Dock a ship per team or role… Grants,
budgets and keys are per ship"), the [station inbox](2026-10-08-station-inbox-design.md) (per-session cursors, the
hook) and the [browser lane](2026-10-08-browser-lane-design.md) (teamd workers, `disableAllHooks`). Base: `main`
(861bfb2). This is an agent-only change, plus one deny rule for teamd's Claude workers (S8); the station (peer) is
untouched.

## Goal

A second ship can dock on a machine that already has one. Each Claude Code session acts as exactly one ship, chosen
by the project it started in, and nothing tied to a ship's key ever reaches a repository. Today four things are fixed
per machine:
- the ship's home: `HOME = ~/.superyak` (station.py:14), so station.json, ship-state, sessions and runs;
- the service: launchd label `com.superyak.ship` and systemd unit `superyak-ship.service` (install.py:18-19);
- the station tools: `claude mcp add --scope user station` (install.py:226);
- the hooks: user scope, `~/.claude/settings.json` (install.py:314), so every session on the machine is Serenity
  today, the Bricks lead's included.

## Measured on the Mac (Claude Code 2.1.295, Codex 0.160.0, 2026-10-09)

Each fact was checked in a throwaway repository with a git worktree and a subdirectory, then removed. M7 and M8 were
measured by the D8 reviewer with an isolated HOME; M9 was reproduced for this revision.
- **M1. Local settings follow the main checkout.** A SessionStart hook in `<repo>/.claude/settings.local.json` fired
  from the repository root, from a subdirectory and from a `git worktree add` worktree. The settings docs say so:
  "If you start Claude Code in a subdirectory of a git repository, it reads and writes that file at the repository
  root… In a worktree, it uses the file at the main checkout's root" (since v2.1.211).
- **M2. A local `station` wins over the user `station`, in the worktree too.** After `claude mcp add --scope local
  station` at the repository root, `claude mcp get station` reported "Local config" from the root, a subdirectory, the
  worktree and a symlinked path, and "User config" from `$HOME`. The entry sits in `~/.claude.json` under
  `projects["<root>"]`. The MCP docs: precedence is local, then project, then user; "Claude Code connects to it once,
  using the definition from the highest-precedence source."
- **M3. Hooks merge across files.** Hooks docs: "Hook entries merge across settings levels rather than replacing each
  other." Two ships' hook commands differ (their `--config`), so both run; a stand-down has to live in the hook itself.
- **M4. What the hook knows.** Its stdin carries `session_id` and `cwd` (`cwd` follows `cd`). Its environment carries
  `CLAUDE_PROJECT_DIR`, the directory the session started in, for both SessionStart and UserPromptSubmit.
- **M5. Git ignore.** Claude Code adds `**/.claude/settings.local.json` to the global excludes only when *it* writes
  that file first. On this Mac the global rule is already present (`~/.config/git/ignore:1`), which is why the tests
  isolate git's config (R11).
- **M6. Codex profiles override a server.** `~/.codex/<name>.config.toml` with its own `[mcp_servers.station]`
  replaced the station's command and args under `codex -p <name> mcp list`; plain `codex mcp list` kept the base one.
- **M7. The local MCP entry is keyed by path.** After the repository was moved (same inode), `claude mcp get station`
  there answered "No MCP server named station". So a claim matched by inode alone would give a moved repository the
  project ship's hooks with the machine ship's tools.
- **M8. What an MCP server knows.** Claude Code starts MCP servers with cwd set to the session's start directory and
  passes `CLAUDE_PROJECT_DIR` and the caller's `SUPERYAK_RUN`. Codex 0.160.0 starts MCP servers with cwd set to the
  session's directory: the shell's cwd, or `-C <dir>` when given (measured 2026-10-09 with a server that records its
  `pwd`, one run each way).
- **M9. The settings backup lands in the repository.** `install_hooks` on an existing `<repo>/.claude/settings.local.json`
  writes `settings.local.json.bak-superyak` beside it (install.py:132-134). With only `/.claude/settings.local.json`
  excluded and git's user config isolated, `git status --porcelain` showed `?? .claude/`. The backup can hold `env`
  secrets (install.py:51), and `git add -A` would commit it.

## The rules every feature keeps (spec A, Brief 1)

1. **Speaking is not acting.** Docking a second ship grants nothing; keys, budgets and grants are per ship (D7).
2. **Messages are data.** Unchanged.
3. **Law.** Each ship gets its own instruction layers on the station; this spec changes only which ship's layers a
   session loads.
4. **Provenance.** Session labels stay provenance only (D7). Per-ship keys on one Unix user separate provenance, not
   authority (Security).
5. **Plurality.** Nothing on the station changes.
6. **Measured.** Each claim has a check (Testing); M1–M9 were measured before writing.

## Decisions

- **S1. Two kinds of ship, fixed by the home.**
  - The **machine ship** has home `~/.superyak` and no project. Every path, label, unit, tool registration, hook
    command and undock call it gets is byte-for-byte today's (R1).
  - A **project ship** has home `~/.superyak/ships/<name>` and exactly one project. It claims that repository:
    sessions that start in its main checkout, a subdirectory or any of its git worktrees act as it (M1, M2).
  - A ship's kind comes from its home, never from the registry: `~/.superyak` is the machine ship; a home under
    `~/.superyak/ships/` is a project ship. Hooks, the MCP server, status and undock all derive it the same way.
  - A machine has at most one machine ship. A repository has at most one claim.
- **S2. Modes and names are checked before anything else.**
  - `--project` requires the project home, and the project home requires `--project`. `--home ~/.superyak/ships/<n>`
    without `--project` is refused, and so is `--project` with `~/.superyak`. Without this, a second ship would run the
    user-scope wiring, where `is_station_hook` matches any `run_agent.py hook` and `_same_hook` compares only the kind,
    so it would replace the machine ship's hooks.
  - `--ship` must fully match the station's own rule, `[a-z][a-z0-9-]{1,31}` (ships.py:11).
  - `--home` is accepted only when it equals `~/.superyak` (machine ship) or `~/.superyak/ships/<ship>`; with
    `--project` and no `--home`, the home is `~/.superyak/ships/<ship>`. Fixed homes can't nest, collide or land in a
    repository.
  - **No name collision.** Dock refuses a `--ship` equal to the `ship_name` in any *other* local home
    (`~/.superyak/station.json` and every `~/.superyak/ships/*/station.json`). The station treats a docking for an
    existing name as a re-dock and revokes all of that ship's keys (ships.py:153-160), so the approval would look
    routine and would kill the other session's key. A home whose `station.json` belongs to a different ship is also
    refused.
- **S3. Commands carry the home through `--config`.** Every command dock installs already takes `--config`: `mcp`,
  `hook`, `watch` (with `--state` and `--mcp-config`) and `run-mcp`. Dock always writes them with the absolute
  `<home>/station.json`. `dock`, `status` and `undock` gain `--home` (default `~/.superyak`), so a person never types
  a config path. `__main__` passes the dock's config path to `install_all` instead of the constant `CONFIG`
  (__main__.py:130). `--workspace` gets default None (__main__.py:27): the machine ship keeps today's default, and a
  project ship's workspace is its project root.
- **S4. One service per ship, named from the home.**
  - Machine ship: label `com.superyak.ship`, unit `superyak-ship.service`, log `~/.superyak/ship.log`, unchanged. No
    migration: the Pi, the Mac and the Legion Go run these names.
  - Project ship: label `com.superyak.ship.<name>`, plist `~/Library/LaunchAgents/com.superyak.ship.<name>.plist`,
    unit `superyak-ship-<name>.service` in `~/.config/systemd/user/`, log `<home>/ship.log`.
  - `install_service` takes the label, unit and log as parameters (install.py:269).
  - **The watcher starts at the newest mention.** When a ship's service is installed and its `<home>/ship-state.json`
    has no `mention_seq`, dock reads `GET /api/mentions` to the end first and stores the newest seq, so the watcher
    never answers the backlog: `mention_seq` otherwise starts at 0 (watch.py:61), and every mention since docking
    would become a run. Dock prints "The watcher starts after mention <seq>; earlier mentions won't be answered."
    A ship that already has `mention_seq` (every machine ship today) is unchanged.
  - **serenity-bricks docks without a service** (`--no-service`, S12). Adding it later is its own decision (The
    watcher day).
- **S5. A project ship's wiring stays out of git.**
  - **Git, hardened.** Dock runs git in the repository only as `git --git-dir <common dir from the reader (S6)>
    --work-tree <root>` with `HARDENED_GIT` (workers.py:32) and `_isolated_git_env()` (workers.py:43), so no
    repository config, hook, fsmonitor or filter can run, and no user or system config is read.
  - **The checks, all fail closed:**
    - `<root>/.claude`, if present, must be a real directory, not a symlink; `settings.local.json`, if present, a
      regular file. Otherwise dock refuses.
    - `ls-files --error-unmatch -- .claude/settings.local.json`: exit 1 means untracked and dock goes on; exit 0
      (tracked) or any other exit refuses.
    - Dock always appends, idempotently, `/.claude/settings.local.json` and `/.claude/.settings.local.json.*` (the
      temporary file `_write_settings` makes, install.py:57) to `<common dir>/info/exclude`, creating `info/` if
      needed. It appends even when a global rule exists, because the isolated environment can't see a custom
      `core.excludesFile`.
    - Then `check-ignore -q` must exit 0 for both `.claude/settings.local.json` and
      `.claude/.settings.local.json.probe.tmp`; any other exit (1 for a negation, 128 for an error) refuses.
  - **Tools:** `claude mcp add --scope local station -- <python> run_agent.py mcp --config <home>/station.json`, run
    with the main checkout root as its working directory (the entry lands in `~/.claude.json`, M2). Dock first removes
    any local `station` there, then confirms with `claude mcp get station` from the root that the scope is local and
    the args carry this home. Today's `register_claude` skips when *any* `station` exists (install.py:224); for a
    project ship it checks scope and args instead.
  - **Machine-ship registration runs outside every claim.** `claude mcp get` answers for its working directory, so a
    machine dock run inside a claimed project would see the local entry and skip the user registration. The machine
    ship's `claude mcp` calls run with `~/.superyak` as their working directory.
  - **Hooks:** `<root>/.claude/settings.local.json`, written by `install_hooks` with that path. Never `.mcp.json` and
    never `.claude/settings.json`. **The backup goes to the ship's home**, `<home>/settings.local.json.bak-superyak`,
    never beside the file in the repository (M9).
  - **Codex (M6):** dock writes the `[mcp_servers.station]` table for this home into `~/.codex/<name>.config.toml`.
    If that file exists, dock changes only that table and keeps the rest; it refuses if the file's `station` table
    points at another home. The project ship's Codex sessions run `codex -p <name>`; plain `codex` is the machine ship,
    which refuses inside a claimed project and says to use `-p` (S7). Dock prints this.
  - **The only files dock writes inside a repository's work tree** are `.claude/settings.local.json` and, while it is
    being written, its temporary file; both are excluded before they're written. `info/exclude` is inside `.git`.
  - **aDNA** is machine-wide and unchanged.
- **S6. Claims, and how a session's project is found.**
  - **The registry:** `~/.superyak/projects.json`, mode 0600, written through `write_private` under an exclusive
    `fcntl` lock on `~/.superyak/projects.lock`, whole-file replace. One entry per claim: `{ship, home, root, dev,
    ino}`: `root` is the real path of the main checkout root, `dev` and `ino` from `os.stat(root)`. The same claim is
    also written to `<home>/claim.json`, so undock and status work without the registry.
  - **The registry is unreadable** when it can't be read, isn't valid JSON, or fails the schema (a list of entries,
    each with exactly those five fields of the right types, ships and roots unique), and also when it's missing while
    any `~/.superyak/ships/*/station.json` exists. A missing registry with no project ship means no claims.
  - **The session's project:** `CLAUDE_PROJECT_DIR` (M4, M8); else stdin `cwd` for the hook, or the process cwd for
    the MCP server.
  - **The root reader** (shared by dock, the hook, the MCP server and status; it never runs git):
    - Walk up from the real path of that directory to the first `.git`. The first one found decides.
    - If `.git` is a directory, the common dir is that directory and the root is its parent.
    - If `.git` is a file, read its `gitdir:` line; a relative path resolves against the folder holding the `.git`
      file. If `<gitdir>/commondir` exists, it resolves against the gitdir; otherwise the gitdir is the common dir.
    - The worktree's back-link must hold: `<gitdir>/gitdir` must name this `.git` file (real paths compared).
    - The common dir must be named `.git`; the root is its parent. A common dir with another name (a submodule's
      `.git/modules/<name>`, a bare repository, `--separate-git-dir`) means "no repository".
    - Anything it can't read, or any check that fails, means "no repository".
  - **Matching a claim:** a claim matches *fully* when both its `root` equals the session root's real path and its
    `(dev, ino)` equals `os.stat` of that root; *partially* when exactly one does. Claude Code keys the local MCP
    entry by path (M7), so path and inode must agree for the tools and the hooks to stay on one ship.
    - The **machine ship** acts only when no claim matches the session root, fully or partially.
    - A **project ship** acts only when its own claim (from `<home>/claim.json`, also present and equal in the
      registry) matches fully.
    - A **partial match is a stale claim** (a moved repository, a re-clone at the same path, a remount that changes
      `st_dev`): neither ship's hook prints and both MCP servers refuse, naming the claim. `status` names it, and
      docking the project ship again refreshes it.
  - **The hook's stand-down** is the first thing `run()` does, before the unreachable marker and `_forget_unless`
    (hook.py:110-113): a hook that stands down makes no station call, moves no cursor and touches no session file.
  - **An unreadable registry is loud** (R16): every hook prints one fixed local line at SessionStart, and nothing at
    a prompt; the MCP server refuses every tool call and names the file; dock refuses and names it; `status` names it
    before reading the config or touching the network. The fixed line is "Superyak: ~/.superyak/projects.json can't
    be read, so the station hooks on this machine are off. Run `make dock` for your ship to see why." It carries no
    ship data and no station call.
- **S7. The MCP server follows the same rules** (Rio Grande's point 2, as ruled).
  - On every tool call the station MCP server re-reads the registry and applies, in order:
    1. `SUPERYAK_RUN` set to anything other than empty or `hook` (a teamd worker or a watcher run, M8): refuse every
       call, mirroring hook.py:106. Watcher runs never had station tools (install.py:40-43).
    2. An unreadable registry: refuse, naming the file.
    3. Machine ship, and a claim matches the session's project fully: refuse with "This session is in <root>, which
       <ship> claims. In Codex, run `codex -p <ship>`; a Claude Code session started there uses <ship>'s station."
       A partial match: refuse, naming the stale claim and "dock <ship> again".
    4. Project ship, and its own claim matches partially: refuse, naming the stale claim and "dock <ship> again".
       Its own claim doesn't match at all: refuse with "<ship> acts only in <claim root>."
  - At `initialize`, in any of those cases, the server sends no instructions (mcp.py:273-281).
  - Both ships' tools are named `station`. In a claimed project the local entry wins (M2) and only one is connected,
    so a Claude Code session never sees both ships. The refusal is what keeps a moved repository (M7) from splitting
    hooks and tools.
  - **Codex** starts MCP servers in the session's directory (M8), so the same rules apply to Codex: plain `codex` in a
    claimed project is refused by rule 3 and told to run `codex -p <ship>`, and `codex -p <ship>` outside its claim is
    refused by rule 4. Mac acceptance re-checks M8 on the Codex version present before build step 5; if a later Codex
    starts servers elsewhere, the build stops there and the spec is revised.
- **S8. teamd workers (corrected by M1).**
  - Worktrees don't copy untracked files, but Claude Code reads the *main checkout's* `settings.local.json` from a
    worktree (M1). So a teamd Claude worker in a hyper-bricks worktree loads serenity-bricks's hooks and its local
    `station` entry (M2).
  - "Don't ask again" approvals are saved to that same file, and allow rules merge across sources, so an absent allow
    rule is not a guarantee. Workers never act as serenity-bricks because of three independent layers:
    - the station MCP server refuses every call under `SUPERYAK_RUN=1` (S7 rule 1), which teamd sets for every
      worker (workers.py:391);
    - the hooks return at once for that value (hook.py:106);
    - teamd's Claude worker settings deny `mcp__station` (added to the deny list at workers.py:308).
  - Browser workers also run with `disableAllHooks` and `--strict-mcp-config` (workers.py:346, 375), and Codex workers
    switch the station off (workers.py:249-250).
- **S9. Order of writes, and rollback.**
  - Before the docking request, dock checks the mode and name (S2), finds the root (S6), refuses a root claimed by
    another ship (full or partial match), and runs the git checks (S5). A refused project never creates a station
    account.
  - After docking, it runs those checks again, then writes in this order: the claim (registry entry and
    `<home>/claim.json`, under the lock: a reservation), `info/exclude`, the local tool entry, the hooks, the Codex
    profile, the service. Any failure rolls back what this run wrote, the claim last.
  - A **project dock confirms the machine ship's hooks** in `~/.claude/settings.json` run this checkout's
    `run_agent.py`, because the stand-down lives in that code; if they run another checkout's, dock refuses and says to
    dock the machine ship again from this checkout.
- **S10. Undocking one ship never touches another.** A ship's undock does only these things, in this order:
  - revokes its own key;
  - stops and removes its own service (S4);
  - removes its own tool entry: the machine ship's user `station`, or the project ship's local `station`, run from
    the project root;
  - removes its own hooks: the machine ship's from `~/.claude/settings.json`, the project ship's from
    `<root>/.claude/settings.local.json`;
  - removes its own Codex entry: the machine ship's `[mcp_servers.station]`, or only the `station` table of
    `~/.codex/<name>.config.toml`, deleting that file only if it is then empty;
  - removes its own home's files;
  - removes its own claim last, from the registry and its home. Undock finds the claim in `<home>/claim.json`, so it
    works when the registry is unreadable. The machine ship's undock leaves `~/.superyak/ships/` and `projects.json`
    alone.
- **S11. Keys, provenance and authority.** Per-ship keys on one Unix user separate provenance, not authority: an
  unsandboxed session of either ship can read both homes, so spec A's per-ship grants must not assume one ship can't
  use another's key. teamd workers and builder runs can't read them (the OS sandbox denies reads of `$HOME`,
  workers.py:328), and read-only runs have no shell and read only their workspace snapshot (runs.py:47-62).
- **S12. The Andy step is one docking approval.** The Bricks lead runs, from its own session:

  ```
  make -C ~/Projects/superyak dock DOCK_ARGS='--ship serenity-bricks --project ~/Projects/work/hyper/hyper-bricks --hook --no-service'
  ```

  `--no-service` (Serenity's ruling): serenity-bricks starts without a watcher. Its sessions get the tools and hooks;
  owner mentions don't start runs in hyper-bricks, a shared GitLab repository, until Andy adds the watcher
  deliberately (The watcher day). The home is `~/.superyak/ships/serenity-bricks`. Andy approves the docking on the Pi
  with `make station-approve ID=<short id>`, or in the browser after checking the code, then chooses its rooms.

## Requirements

- **R1.** With no `--project` and no `--home`, every path, label, unit, log, tool registration, Codex block, watcher
  argument, hook command and undock call is byte-for-byte today's.
- **R2.** The mode pairing, the station's name rule, the fixed homes and the no-collision rule (S2) are checked before
  any network call or write.
- **R3.** `--project` resolves through the root reader (S6). "No repository", or a root claimed by another ship (fully
  or partially), is refused before the docking request.
- **R4.** The S5 checks run before the docking request and again before the first write. A symlinked `.claude`, a
  tracked or unignorable file, or any unexpected git exit means nothing is written.
- **R5.** Dock's git calls in a repository use `--git-dir`, `--work-tree`, `HARDENED_GIT` and `_isolated_git_env()`,
  and no other form.
- **R6.** The settings backup is written to the ship's home, never into the repository.
- **R7.** Local tool registration replaces only a local `station` in that project, and dock confirms its scope and
  args. The machine ship's `claude mcp` calls run with `~/.superyak` as their working directory.
- **R8.** The registry is written only under its lock, through `write_private`, as a whole-file replace; each claim is
  also in `<home>/claim.json`.
- **R9.** The claim is the first write after docking; any later failure rolls back this run's writes, the claim last.
- **R10.** A project dock refuses when the machine ship's hooks run another checkout's `run_agent.py`.
- **R11.** (Test rule) every dock test that checks git status points `XDG_CONFIG_HOME` and `GIT_CONFIG_GLOBAL` at empty
  temporary files and sets `GIT_CONFIG_NOSYSTEM=1`, so a machine's global ignore (M5) can't make it pass.
- **R12.** The hook reads stdin once, for both `session_id` and `cwd`; `session_from_stdin` stays as a thin wrapper.
- **R13.** The stand-down is the first step of `run()`: a standing-down hook makes no network call, moves no cursor
  and touches no session file.
- **R14.** A ship's kind comes from its home (S1). The machine ship acts only with no matching claim; a project ship
  only with a full match of its own claim.
- **R15.** A partial match is a stale claim: both hooks print nothing, both MCP servers refuse naming it, `status`
  names it, and a project re-dock refreshes it.
- **R16.** An unreadable registry (S6) gives the fixed SessionStart line, nothing at a prompt, MCP refusals naming the
  file, a dock refusal naming it, and a `status` line naming it before any config read or network call.
- **R17.** The root reader follows S6 exactly and never runs git.
- **R18.** The station MCP server applies S7's rules on every call, re-reading the registry each time, and sends no
  instructions at `initialize` when it would refuse.
- **R19.** teamd's Claude workers deny `mcp__station`.
- **R20.** The Codex profile file is never overwritten: dock changes only its `station` table, and undock removes only
  that table and deletes the file only if empty.
- **R21.** Undock touches only its own ship (S10), removes the claim last, and works without the registry.
- **R22.** A ship's first service install starts the watcher at the newest mention and says so (S4).
- **R23.** Dock prints, for a project ship: its home, its project root, that Claude Code sessions there act as it,
  and that Codex sessions need `codex -p <name>`.

## Compatibility

- The machine ship is unchanged (R1). The Pi, the Mac and the Legion Go need nothing beyond pulling main.
- `projects.json` doesn't exist until a project ship docks; with no project ship, a missing file means no claims.
- A hook installed by an older agent ignores claims. The hook runs from the checkout, so pulling main picks up the
  stand-down; R10 makes a project dock check it. The hook command string doesn't change, so `settings.json` isn't
  rewritten.
- The agent's `status` is `run_agent.py status` (__main__.py:137), not `make status`, which is the runtime's
  (Makefile:129).

## Security

- Nothing with a key goes into a repository: tools live in `~/.claude.json`, keys and the settings backup in the
  ship's home (0600), and hooks name only a config path. Every git check fails closed (R4).
- Git runs in the repository only hardened and isolated (R5). The hook and the MCP server never run git (R17).
- Per-ship keys separate provenance, not authority (S11).
- Workers can't act as a project ship, through three independent layers (S8).
- The registry fails closed, loudly (R16).

## Testing (each check fails without its feature)

**Agent and team, Pi-safe** (temporary home, temporary git repositories with a worktree and a subdirectory, git
config isolated per R11, a fake `claude` and fake `launchctl`/`systemctl` that record their calls and working
directory):
- `test_machine_ship_is_byte_for_byte_today`: the full recorded call list and file contents for a machine dock and
  undock: the `mcp add` args, the Codex block, the plist and unit, the watcher args, both hook commands and the undock
  calls (R1).
- `test_modes_names_and_collisions_are_refused_before_the_network`: `--home ships/<n>` without `--project`,
  `--project` with `~/.superyak`, a name outside `[a-z][a-z0-9-]{1,31}`, a `--ship` already in another local home,
  and a home holding another ship are each refused with no request and no write (R2).
- `test_service_names_per_ship`: the plist label and file, the unit file and name, and the log for a project ship; the
  machine ship's are unchanged (S4).
- `test_dock_writes_nothing_tracked`: starting with an existing `settings.local.json`, a project dock leaves
  `git status --porcelain` empty, the backup is in the ship's home, and `info/exclude` holds both lines once after two
  docks. A tracked file, a negation rule and a symlinked `.claude` are each refused with nothing written (R4, R6, R11).
- `test_dock_git_is_hardened`: every git call dock makes in the repository carries `--git-dir`, `--work-tree`, every
  `HARDENED_GIT` option and the isolated environment; a repository `core.fsmonitor` command never runs (R5).
- `test_refused_project_never_reaches_the_station`: a folder that is no repository, a claimed root and a tracked file
  each fail before any docking request (R3, R4).
- `test_claim_first_and_rollback`: a failure at each later write leaves no claim and none of this run's files (R9).
- `test_local_station_registration_checks_scope`: dock ignores an existing user `station`, replaces a stale local
  one, and refuses when the confirmation shows the wrong scope or args (R7).
- `test_machine_registration_runs_outside_claims`: a machine dock's `claude mcp` calls record `~/.superyak` as their
  working directory, even when dock runs inside a claimed project (R7).
- `test_project_dock_checks_the_machine_hook_checkout`: a machine hook naming another checkout's `run_agent.py` is
  refused (R10).
- `test_machine_ship_hook_stands_down_in_a_claimed_project`: from the root, a subdirectory and a worktree, via
  `CLAUDE_PROJECT_DIR` and via stdin `cwd` when it's unset, it prints nothing, makes no station call and doesn't touch
  the unreachable marker or session files (R13, R14).
- `test_machine_ship_hook_runs_elsewhere`: from an unclaimed repository and from a plain folder, it runs.
- `test_project_ship_hook_runs_only_in_its_project`: it runs in its project and its worktree, and is silent elsewhere,
  even when its settings are copied there.
- `test_a_moved_or_recloned_repository_is_a_stale_claim`: a moved repository (inode kept, path changed) and a
  re-clone at the same path (path kept, inode changed): both hooks print nothing, both MCP servers refuse naming the
  claim, `status` names it, and a project re-dock refreshes it (R15).
- `test_project_root_reader_layouts`: a worktree through `commondir`, a relative `gitdir:`, a broken back-link, a
  submodule, a bare repository with worktrees and a `--separate-git-dir` checkout give the S6 answers; an unreadable
  `.git` means no repository; `git` is never called (a failing `git` is first on `PATH`) (R17).
- `test_unreadable_registry_is_loud`: unreadable, schema-invalid, and missing-with-a-ship-home each give the fixed
  SessionStart line, nothing at a prompt, no station call, MCP refusals and a dock refusal naming the file, and a
  `status` line before any config read (R16).
- `test_station_tools_refuse_inside_runs`: with `SUPERYAK_RUN=1`, every tool call is refused even when the session's
  `settings.local.json` holds an allow rule for the station tools; with it unset or `hook`, calls go through (R18).
- `test_mcp_server_follows_the_claims`: the machine server refuses inside a claim with the `codex -p` hint; the project
  server refuses outside its own claim; neither sends instructions at `initialize` then; a claim added between two
  calls applies to the second (R18).
- `test_workers_deny_the_station`: teamd's Claude worker settings carry `mcp__station` in `deny` (R19).
- `test_codex_profile_is_never_overwritten`: a foreign profile file keeps its other tables; a `station` table for
  another home is refused; undock removes only the table and deletes the file only when empty (R20).
- `test_undock_one_ship_leaves_the_other`: the recorded calls and remaining files show the other ship untouched, both
  ways round; the claim goes last; undock works with the registry unreadable (R21).
- `test_first_service_install_skips_the_backlog`: with mentions on the fake station and no `mention_seq`, the service
  install stores the newest seq and prints it; an existing `mention_seq` is kept (R22).

**Mac acceptance** (real Claude Code and Codex, a throwaway repository, before the Bricks lead docks; hooks run by hand
get both `CLAUDE_PROJECT_DIR` and stdin):
- `claude mcp get station` reports local scope from the root, a subdirectory, a worktree and a symlinked path, and user
  scope outside (M2). After moving the repository, a session there gets the machine ship's tools, and they refuse,
  naming the stale claim (M7, R15).
- A real session with both ships' hooks live, from the root, a subdirectory and a worktree: the project ship's hook
  speaks and the machine ship's prints nothing.
- "Don't ask again" on a station tool lands in `settings.local.json`; a teamd worker in a worktree still has every
  station call refused (S8).
- Codex: where it starts MCP servers (decides S7 (a) or (b)), and `codex -p <name> mcp list` shows the project ship's
  station (M6).
- `/cd`: in a session started in hyper-bricks, `/cd` out and back; in one started outside, `/cd` in. Pass: the tools'
  ship and the hook's ship are the same after each `/cd` (whichever ship that is); record which.

## Build order

1. Modes, names and collisions; `--home`; the config path through dock and `install_all`; `--workspace` default None;
   `install_service` with label, unit and log; per-ship service names; the first-install mention cursor (S2–S4; R1,
   R2, R22).
2. The root reader, the registry, its lock and `<home>/claim.json`; `status` checks the registry first (S6; R8, R16,
   R17).
3. Hardened git checks and local wiring: local tools from the root, machine registration from `~/.superyak`, hooks
   with the backup in the home, the Codex profile; the reservation and rollback; the machine-hook checkout check (S5,
   S9; R3–R7, R9–R11, R20).
4. The hook's stand-down, stale claims and the loud registry (S6; R12–R16).
5. Mac acceptance for Codex's server cwd, then the MCP server's rules and the worker deny rule (S7, S8; R18, R19).
6. Undock (S10, R21).
7. The rest of Mac acceptance, then the Bricks lead docks with `--no-service` (S12).

Each step is test-first on branch `many-ships`. Rio Grande reviews under the interim rule.

## The watcher day (out of scope now; a separate decision)

Adding serenity-bricks's watcher later means docking again without `--no-service`. R22 keeps it from answering the
backlog. These change on that day and must be settled first:
- Its runs work in hyper-bricks with `--setting-sources project,local` (runs.py:124): they load the repository's
  tracked project settings, so other committers' hooks run unsandboxed and their allow rules apply, plus the lead's
  local approvals. Consider `disableAllHooks` for those runs and a deny on `~/.superyak/**`.
- Read runs show hyper-bricks's HEAD to anyone in serenity-bricks's rooms, bridged rooms included.
- `git worktree add` in runs.py:192 and 203 isn't hardened, so checkout hooks would run.
- Builder branches `lighthouse/serenity-bricks/*` appear in the shared clone.

## Known limits

- **Codex chooses its ship per invocation** (`codex -p serenity-bricks`), not by where it starts. A plain `codex` in
  hyper-bricks gets the machine ship's server, which refuses every call there (S7 rule 3) rather than acting as
  Serenity; the person has to restart with `-p`. This rests on M8, re-checked per Codex version.
- **A session's ship is fixed by where it started.** A session started outside hyper-bricks acts as Serenity even while
  it edits hyper-bricks files. Mac acceptance records what `/cd` does.
- **Claims are per clone.** A second clone of hyper-bricks elsewhere is unclaimed until it's docked too. Worktrees of
  the claimed checkout are covered (M1, M2).
- **teamd workers in a claimed project load that ship's hooks and local tools** (S8). Three layers keep them silent;
  a change to any of them needs this spec re-read.
- **A branch that tracks `.claude/settings.local.json`** silently replaces the ignored file on checkout (git 2.39).
  An upstream `.gitignore` negation can un-ignore it. `status` and dock re-run the hardened checks and say so.
- **The stand-down lives in the checkout.** Checking out an older branch of the superyak checkout removes it until
  main is back; R10 checks it only at dock time.
- **A submodule, a bare repository and a `--separate-git-dir` checkout are "no repository"**, so the machine ship
  applies there.
- **Keys separate provenance, not authority** (S11).

## Out of scope

- Grants and revision signatures (spec A step 3).
- A ship per OS user, or any isolation stronger than separate keys and files.
- Choosing a Codex ship by directory.
- serenity-bricks's watcher (The watcher day).
- Room membership and briefs for the new ship: Andy's choice, as for any ship.

## Review map (revision 2)

| Item | Where | Requirement | Test |
|---|---|---|---|
| D8 must-fix 1: backup and temp file in the repo | S5 Hooks, S5 checks; M9 | R4, R6, R11 | `test_dock_writes_nothing_tracked` |
| D8 must-fix 2: path vs inode | S6 Matching; S7; M7 | R14, R15 | `test_a_moved_or_recloned_repository_is_a_stale_claim`, Mac acceptance |
| D8 must-fix 3: modes, collision, name rule | S1, S2 | R2 | `test_modes_names_and_collisions_are_refused_before_the_network` |
| D8 must-fix 4: allow rules in settings.local.json | S7 rule 1, S8 | R18, R19 | `test_station_tools_refuse_inside_runs`, `test_workers_deny_the_station` |
| D8 must-fix 5: watcher backlog | S4 | R22 | `test_first_service_install_skips_the_backlog` |
| Should-fix: root reader layouts | S6 root reader | R17 | `test_project_root_reader_layouts` |
| Should-fix: git checks fail closed | S5 checks | R4 | `test_dock_writes_nothing_tracked` |
| Should-fix: ordering, reservation, claim in home | S9, S10 | R3, R9, R21 | `test_refused_project_never_reaches_the_station`, `test_claim_first_and_rollback`, `test_undock_one_ship_leaves_the_other` |
| Should-fix: registry schema and missing file | S6 registry | R16 | `test_unreadable_registry_is_loud` |
| Should-fix: hook kind from home, stand-down first | S1, S6 | R13, R14 | `test_machine_ship_hook_stands_down_in_a_claimed_project` |
| Should-fix: machine registration cwd | S5 | R7 | `test_machine_registration_runs_outside_claims` |
| Should-fix: stale checkout | S9 | R10 | `test_project_dock_checks_the_machine_hook_checkout`; Known limits |
| Should-fix: watcher day | The watcher day | — | — |
| Should-fix: security wording | S11 | — | — |
| Should-fix: Codex profile | S5 Codex, S10 | R20 | `test_codex_profile_is_never_overwritten` |
| Should-fix: known limits, `/cd` criterion | Known limits; Mac acceptance | — | Mac acceptance |
| Checked: R1 pins everything | R1 | R1 | `test_machine_ship_is_byte_for_byte_today` |
| Build notes: `--workspace`, `install_service`, status first | S3, S4, S6 | R16 | build steps 1–2 |
| Rio Grande 1: hardened git | S5 Git | R5 | `test_dock_git_is_hardened` |
| Rio Grande 2: MCP refusal | S7 | R18 | `test_mcp_server_follows_the_claims`; Mac acceptance (Codex cwd) |
| Rio Grande 3: R9 loud | S6 loud registry | R16 | `test_unreadable_registry_is_loud` |
