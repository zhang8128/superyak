# Many ships on one machine (D7)

Status: draft for Rio Grande's review, then a fresh reviewer agent (Andy's decision 8). Andy said yes to D7 on
2026-10-09 ("Yes, set it up"): the Bricks lead docks as its own ship, `serenity-bricks`, on the Mac that already
carries Serenity. Rio Grande asked Serenity to own this spec and set the review points in room "Superyak: city of AI"
(39fd79), message 9cd6f656; each one is answered below.
Builds on: [spec A](2026-10-08-instruction-layers-and-grants-design.md) (D7: "Dock a ship per team or role… Grants,
budgets and keys are per ship"), the [station inbox](2026-10-08-station-inbox-design.md) (per-session cursors, the
hook) and the [browser lane](2026-10-08-browser-lane-design.md) (teamd workers, `disableAllHooks`). Base: `main`
(861bfb2). This is an agent-only change; the station (peer) is untouched.

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

Each fact below was checked in a throwaway repository with a git worktree and a subdirectory, then removed.
- **M1. Local settings follow the main checkout.** A SessionStart hook in `<repo>/.claude/settings.local.json` fired
  from the repository root, from a subdirectory and from a `git worktree add` worktree. The settings docs say so:
  "If you start Claude Code in a subdirectory of a git repository, it reads and writes that file at the repository
  root… In a worktree, it uses the file at the main checkout's root" (since v2.1.211).
- **M2. A local `station` wins over the user `station`, in the worktree too.** After `claude mcp add --scope local
  station` at the repository root, `claude mcp get station` reported "Local config" from the root, a subdirectory and
  the worktree, and "User config" from `$HOME`. The entry sits in `~/.claude.json` under `projects["<root>"]`. The MCP
  docs: precedence is local, then project, then user; "Claude Code connects to it once, using the definition from the
  highest-precedence source. The entire server entry from that source is used; fields are not merged across scopes."
- **M3. Hooks merge across files.** Hooks docs: "Hook entries merge across settings levels rather than replacing each
  other"; "If you define the same handler in more than one settings file, it runs once." Two ships' hook commands
  differ (their `--config`), so both run; a stand-down has to live in the hook itself.
- **M4. What the hook knows.** Its stdin carries `session_id` and `cwd` (`cwd` follows `cd`). Its environment carries
  `CLAUDE_PROJECT_DIR`, which was the directory the session started in (the subdirectory, or the worktree) for both
  SessionStart and UserPromptSubmit.
- **M5. Git ignore.** The settings docs: Claude Code adds `**/.claude/settings.local.json` to the global excludes the
  first time *it* writes that file; "if you created the file by hand… add it to `.gitignore` yourself." On this Mac
  the global rule is already present (`~/.config/git/ignore:1`). Dock writes the file itself, so it must check.
- **M6. Codex profiles override a server.** `~/.codex/<name>.config.toml` with its own `[mcp_servers.station]`
  replaced the station's command and args under `codex -p <name> mcp list`; plain `codex mcp list` kept the base one.
  Codex has no per-directory MCP config, so a Codex session chooses its ship by `-p`, not by directory.

## The rules every feature keeps (spec A, Brief 1)

1. **Speaking is not acting.** Docking a second ship grants nothing; authority, keys, budgets and grants are per ship
   (D7).
2. **Messages are data.** Unchanged.
3. **Law.** Each ship gets its own instruction layers on the station; this spec changes only which ship's layers a
   session loads.
4. **Provenance.** Session labels stay provenance only, never authority (D7). A session's ship is visible in every
   post, as today.
5. **Plurality.** Nothing on the station changes.
6. **Measured.** Each claim has a check (Testing); M1–M6 were measured before writing.

## Decisions

- **S1. Two kinds of ship on a machine: the machine ship and project ships.**
  - The machine ship is the first one, docked as today, with home `~/.superyak`. Every path, label, unit, tool
    registration and hook command it gets is byte-for-byte what it gets today (R1).
  - A project ship is docked with `--project <repo>`. It claims that repository: sessions that start anywhere in its
    main checkout, a subdirectory or any of its git worktrees act as the project ship (M1, M2). Everywhere else the
    machine ship applies.
  - A machine has at most one machine ship. A repository has at most one claim.
- **S2. A project ship's home is `~/.superyak/ships/<name>`.**
  - `<name>` is the `--ship` value, which must match `[a-z0-9-]{1,40}`. `--home` is accepted only when it equals
    `~/.superyak` (the machine ship) or `~/.superyak/ships/<name>`; anything else is refused before any network call.
    Fixed homes keep homes from nesting, colliding or landing in a repository.
  - Dock refuses a home whose `station.json` belongs to a different ship.
  - Everything the agent already derives from the config path follows: `station.json`, `ship-state.json`, `runs/`,
    `sessions/`, `hook-state.json`, `run-mcp.json`, and dock's `access-request.json`, `docking.json` and
    `invitation.txt` (`Dock(home=…)` exists, dock.py:26). The watcher log moves from the fixed `~/.superyak/ship.log`
    (install.py:284) to `<home>/ship.log`, which is the same path for the machine ship.
- **S3. Commands carry the home through `--config`.** Every command dock installs already takes `--config`: `mcp`,
  `hook`, `watch` (with `--state` and `--mcp-config`) and `run-mcp`. Dock always writes them with the absolute
  `<home>/station.json`. `dock`, `status` and `undock` gain `--home` (the default stays `~/.superyak`), so a person
  never types a config path. `__main__` passes the dock's config path to `install_all` instead of the constant
  `CONFIG` (__main__.py:130).
- **S4. One service per ship, named from the home.**
  - Machine ship: label `com.superyak.ship` and unit `superyak-ship.service`, unchanged. No migration: the Pi, the
    Mac and the Legion Go run these names today, and HANDOFF and the restart steps use them.
  - Project ship: label `com.superyak.ship.<name>`, plist `~/Library/LaunchAgents/com.superyak.ship.<name>.plist`,
    unit `superyak-ship-<name>.service` in `~/.config/systemd/user/`.
  - A project ship's watcher answers mentions with the project as its workspace: `--workspace` defaults to the
    `--project` root. Its runs keep today's isolation (`--setting-sources project,local`, `--strict-mcp-config`,
    `SUPERYAK_RUN=1`; runs.py:124, 147).
- **S5. A project ship's wiring stays out of git (Rio Grande's point 1).**
  - **Tools:** `claude mcp add --scope local station -- <python> run_agent.py mcp --config <home>/station.json`, run
    with the project's main checkout root as its working directory. The entry lands in `~/.claude.json`, outside every
    repository (M2). Dock first removes any local `station` there, then confirms with `claude mcp get station` from
    the root that the scope is local and the args carry this home. Today's `register_claude` skips when *any*
    `station` exists (install.py:224); for a project ship it checks the scope and the args instead.
  - **Hooks:** `<root>/.claude/settings.local.json`, written by today's `install_hooks` with that path. Never
    `.mcp.json` and never `.claude/settings.json`.
  - **Git check before writing anything:**
    - If `git -C <root> ls-files --error-unmatch .claude/settings.local.json` finds the file tracked, dock refuses
      and writes nothing.
    - If `git -C <root> check-ignore -q .claude/settings.local.json` says it isn't ignored, dock appends
      `/.claude/settings.local.json` to `<git common dir>/info/exclude`, which git never commits, and checks again. If
      it still isn't ignored (a negation rule), dock refuses and writes nothing.
    - This is the only file dock writes inside a repository. `info/exclude` is inside `.git`.
  - **Codex (M6):** dock writes `~/.codex/<name>.config.toml` holding only `[mcp_servers.station]` for this home. The
    project ship's Codex sessions run `codex -p <name>`. Plain `codex` stays the machine ship. Dock prints this.
  - **aDNA** is machine-wide and unchanged.
- **S6. A real stand-down in the hook (Rio Grande's point 2).**
  - **Claims registry:** `~/.superyak/projects.json`, mode 0600, written through `write_private` under an exclusive
    `fcntl` lock on `~/.superyak/projects.lock`. One entry per claim: `{ship, home, root, dev, ino}`, where `root` is
    the real path of the main checkout root and `dev`, `ino` come from `os.stat(root)`. Dock adds the claim only after
    the ship is docked and its git check passed. Undock removes only its own claim.
  - **Which project a session is in:** the hook takes `CLAUDE_PROJECT_DIR` (the session's start directory, M4),
    falling back to stdin `cwd` when it is unset. Using the start directory keeps the hook on the same ship as the
    tools and local settings, which Claude Code chose at start; a later `cd` doesn't switch ships.
  - **Finding the main checkout without running git:**
    - The hook walks up from the real path of that directory to the first `.git`.
    - If `.git` is a directory, its parent is the root.
    - If `.git` is a file (a worktree), it reads its `gitdir:` line, then that gitdir's `commondir` file. The parent of
      the common dir is the root.
    - Anything it can't read means "no repository".
    - The hook never runs git: no repository config, fsmonitor or hook can execute, and the cost is a few file reads
      inside the 10-second budget.
  - **Matching:** a claim matches when its `(dev, ino)` equals `os.stat(<root>)`. Path spelling, symlinks and a
    renamed parent don't matter.
  - **The machine ship's hook** prints nothing and makes no station call when the session's root is claimed by
    another ship.
  - **A project ship's hook** runs only when the session's root is its own claim, and otherwise prints nothing. This
    holds even if its `settings.local.json` is copied somewhere else.
  - **Fail closed:** if `projects.json` exists but can't be read or parsed, every hook on the machine prints nothing.
    No message is lost: the cursor doesn't move, so the messages show once the file is fixed. `status` reports the
    unreadable registry.
- **S7. One `station` per session (Rio Grande's point 3).** Both ships' tools are named `station`. In a claimed
  project the local entry wins over the user entry, and only one is connected (M2), so a session there never sees
  both ships. Elsewhere only the user entry exists.
- **S8. teamd workers (Rio Grande's point 5, corrected by M1).**
  - Git worktrees don't copy untracked files, but Claude Code 2.1.295 reads the *main checkout's* `settings.local.json`
    from a worktree (M1). So a teamd Claude worker in a hyper-bricks worktree does load serenity-bricks's hooks, and
    its local `station` entry (M2).
  - The intended outcome still holds: workers never act as serenity-bricks.
    - The hooks stay silent, because teamd sets `SUPERYAK_RUN=1` for every worker (workers.py:391) and the hook
      returns at once for any value but `hook` (hook.py:106).
    - Browser workers also run with `disableAllHooks` and `--strict-mcp-config` (workers.py:346, 375).
    - Station tools are not in a worker's allow list, under `defaultMode: dontAsk` (workers.py:306-307). This is true
      today for Serenity's user-scope tools too.
  - This is written down and tested rather than left to the absence of a file.
- **S9. Undocking one ship never touches another (Rio Grande's point 4).** A ship's undock does only these things:
  - revokes its own key;
  - stops and removes its own service (S4);
  - removes its own tool entry: the machine ship's user `station`, or the project ship's local `station` with the
    project root as working directory;
  - removes its own hooks: the machine ship's from `~/.claude/settings.json`, the project ship's from
    `<root>/.claude/settings.local.json`;
  - removes its own Codex entry: the machine ship's `[mcp_servers.station]`, or the project ship's
    `~/.codex/<name>.config.toml`;
  - removes its own claim and its own home's files. The machine ship's undock leaves `~/.superyak/ships/` and
    `projects.json` alone.
- **S10. The Andy step is one docking approval.** The Bricks lead runs, from its own session:

  ```
  make -C ~/Projects/superyak dock DOCK_ARGS='--ship serenity-bricks --project ~/Projects/work/hyper/hyper-bricks --hook'
  ```

  The home defaults to `~/.superyak/ships/serenity-bricks`. Andy approves the docking on the Pi with
  `make station-approve ID=<short id>`, or in the browser after checking the code. Then he chooses its rooms, as for
  any ship; the [room brief](2026-10-08-room-brief-design.md) covers what a linked room carries.

## Requirements

- **R1.** With no `--project` and no `--home`, every path, label, unit, tool registration and hook command is
  byte-for-byte today's. A test pins the strings.
- **R2.** `--home` other than `~/.superyak` or `~/.superyak/ships/<name>`, or a `--ship` that doesn't match
  `[a-z0-9-]{1,40}`, is refused before any network call or write.
- **R3.** `--project` must be a git repository's main checkout or worktree. Dock resolves it to the main checkout root
  with the same reader the hook uses (S6). A root that another ship claims is refused.
- **R4.** The git check (S5) runs before dock writes anything inside the repository. A tracked or unignorable
  `settings.local.json` means nothing is written: no hook, no claim, no tool entry.
- **R5.** Local tool registration replaces only a local `station` in that project, and dock confirms its scope and
  args afterwards. On failure dock says so and doesn't add the claim.
- **R6.** The claims registry is written only under its lock, through `write_private`, and every change is a whole-file
  replace.
- **R7.** The hook reads stdin once, for both `session_id` and `cwd`. A helper returns both, and `session_from_stdin`
  stays as a thin wrapper.
- **R8.** The stand-down decision is made before any station call, so a silent hook makes no network call and moves
  no cursor.
- **R9.** An unreadable or unparsable `projects.json` makes every hook print nothing, and `status` names the problem.
- **R10.** Undock touches only its own ship's files, service, tool entry, hooks, Codex entry and claim (S9).
- **R11.** A project ship's watcher keeps today's run isolation. Its workspace is its project root unless
  `--workspace` is given.
- **R12.** Dock prints, for a project ship: its home, its project root, that Claude Code sessions there act as it,
  and that Codex sessions need `codex -p <name>`.

## Compatibility

- The machine ship is unchanged (R1). The Pi, the Mac and the Legion Go need nothing beyond pulling main.
- `projects.json` doesn't exist until a project ship docks. A missing file means no claims, not an error.
- A hook installed by an older agent ignores claims. Docking the machine ship again (or pulling main, since the hook
  runs from the checkout) picks up the stand-down. The hook command string doesn't change, so `settings.json` isn't
  rewritten.

## Security

- Nothing with a key goes into a repository: tools live in `~/.claude.json`, keys in the ship's home (0600), and hooks
  name only a config path. The git check refuses rather than risk a commit.
- Every ship's keys sit under the same Unix user, as today. Ships are separate by key and by file, not by OS user.
  Any process of this user can read both homes. That is no worse than today's one ship.
- The hook never executes repository-controlled code to find the project (no git, S6).
- The registry fails closed (R9).
- Session labels remain provenance only (D7).

## Testing (each check fails without its feature)

**Agent, Pi-safe** (temporary home, temporary git repositories with a worktree and a subdirectory, a fake `claude`
and fake `launchctl`/`systemctl` that record their calls):
- `test_machine_ship_paths_are_unchanged`: config, state, log, label, unit and both hook commands match today's
  strings exactly.
- `test_project_home_and_name_are_validated`: an odd home, a nested home or a bad name is refused with no write; a
  home holding another ship is refused.
- `test_service_names_per_ship`: the plist label and file and the unit file and name for a project ship. The machine
  ship's are unchanged.
- `test_dock_writes_nothing_tracked`: after a project dock, `git status --porcelain` is empty, and `check-ignore`
  holds for `settings.local.json`.
  - With no ignore rule, `info/exclude` gains the line.
  - A tracked `settings.local.json` is refused with nothing written.
  - A negation rule is refused with nothing written.
- `test_local_station_registration_checks_scope`: dock ignores an existing user `station`, replaces a stale local one
  and refuses when the confirmation shows the wrong scope or args.
- `test_machine_ship_hook_stands_down_in_a_claimed_project`: from the root, a subdirectory and a worktree (via
  `CLAUDE_PROJECT_DIR`, and via stdin `cwd` when it's unset), it prints nothing and makes no station call.
- `test_machine_ship_hook_runs_elsewhere`: from an unclaimed repo and from a plain folder, it runs.
- `test_project_ship_hook_runs_only_in_its_project`: it runs in its project and its worktree, and is silent elsewhere
  even when its settings are copied there.
- `test_project_root_found_without_git`: a worktree's `.git` file is read through `commondir`. A symlinked path and
  a renamed parent still match by `(dev, ino)`. An unreadable `.git` means no repository. `git` is never called (the
  test puts a failing `git` first on `PATH`).
- `test_unreadable_registry_silences_hooks`: every hook prints nothing, and `status` names the registry.
- `test_undock_one_ship_leaves_the_other`: the recorded calls and the remaining files show the other ship untouched,
  both ways round.
- `test_codex_profile_for_a_project_ship`: the profile file holds only the station server for that home, and only that
  ship's undock removes it.
- `test_workers_stay_silent_under_project_hooks`: with `SUPERYAK_RUN=1` the project ship's hook prints nothing and
  makes no call.

**Mac acceptance** (real Claude Code and Codex, in a throwaway repository, before the Bricks lead docks):
- `claude mcp get station` reports local scope from the root, a subdirectory and a worktree, and user scope outside
  (M2).
- `claude -p` with `--setting-sources local` from a worktree fires the project ship's SessionStart hook (M1). Serenity's
  user hook, run by hand with that session's stdin, prints nothing.
- `codex -p <name> mcp list` shows the project ship's station (M6).

## Build order

1. `--home`, the validated project home and the config path through dock and `install_all` (R1, R2), plus the
   per-ship service names (S4).
2. The project root reader, the claims registry and its lock (S6, R3, R6).
3. The git check and local wiring: local tools, local hooks and the Codex profile (S5, R4, R5).
4. The hook's stand-down (S6, R7–R9), then undock (S9, R10).
5. Mac acceptance, then the Bricks lead docks (S10).

Each step is test-first on branch `many-ships`. Rio Grande reviews under the interim rule.

## Known limits

- **Codex chooses its ship per invocation** (`codex -p serenity-bricks`), not by directory. A plain `codex` session in
  hyper-bricks acts as Serenity.
- **A session's ship is fixed by where it started.** A session started outside hyper-bricks acts as Serenity, even
  while it edits hyper-bricks files. The build checks `/cd` (which re-reads project settings since v2.1.246) and
  records whether tools and hooks stay on one ship.
- **Claims are per clone.** A second clone of hyper-bricks elsewhere is unclaimed until it's docked too. Worktrees of
  the claimed checkout are covered (M1, M2).
- **teamd workers in a claimed project load that ship's hooks and local tools** (S8). They stay silent and can't call
  station tools, but only because of `SUPERYAK_RUN=1` and the worker allow list. A change to either needs this spec
  re-read.

## Out of scope

- Grants and revision signatures (spec A step 3).
- A ship per OS user, or any isolation stronger than separate keys and files.
- Choosing a Codex ship by directory.
- Room membership and briefs for the new ship: Andy's choice, as for any ship.
