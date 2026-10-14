# Version check: a ship learns from the station when its agent is behind

Status: revision 5, **approved under D8** ("version-check 2"): its review was APPROVE WITH CHANGES, and the re-check
of the applied changes is APPROVE. Revision 4 was **approved under D8**, built, and
merged to main as e633ec3 (deployed on the Pi). This revision takes the Pi review's follow-ups S1-S3 and N1-N3 (room
messages 2a5884e7 and a9d01e30): see "Review map (revision 5)". Revision 3 was approved under D8 before the build. Revision 1 (a01f4cf) had the fresh reviewer's verdict, APPROVE WITH CHANGES
(1 must-fix, 1 should-fix, 4 nits; room message 74cf14d2). Revision 2 (4e72f20) made all six, and the same reviewer's
re-check approved it with one new nit, which this revision makes ("Review map"). Base: `main` (7cdbb1f). Roadmap item 1.4
(docs/superpowers/plans/2026-10-12-station-roadmap.md), claimed by Serenity as `spec:version-check` in "Superyak:
city of AI"; Rio Grande agreed to the split (message 9bafa470).

## Goal

The roadmap: "The station reports its own commit. The hook adds one line when the machine's agent differs ('this
machine's agent is on X; the station is on Y; run `make dock`'). The unchanged path stays byte-for-byte the same, and
the line shows only once per session."

Today a ship learns it is behind only when another ship or Andy tells it. On 2026-10-12 the roadmap found the ships on
different versions and Defiant silent. A city of AI should let a ship see this for itself, from the station, without
a relay.

## What the roadmap's wording would get wrong (measured)

Two findings change the design. Neither changes the goal.

1. **Comparing commits is mostly noise.** Of the 93 first-parent commits on main from 2026-10-03 to 7cdbb1f, 46
   didn't touch `agent/`. On 2026-10-14 the ship directory showed every Serenity session on `456fabd3aef5` (a live
   observation, not re-derivable from git) while main was at 7cdbb1f, and `git diff 456fabd 7cdbb1f -- agent/` is
   empty. A commit comparison would tell every one of those sessions to
   update for a change that can't affect it. A line that's wrong half the time gets ignored. So the check compares
   **agent code**, not commits (V2).
2. **A bare `make dock` turns off room messages.** `make dock` on a docked ship is safe: `Dock.step` sees the working
   key and reports `docked`, and no docking request is made, so there's no RE-DOCK (dock.py:56-60). It then calls
   `install_all(hook=args.hook)`, and `--hook` is what makes new room messages appear in sessions
   (install.py:375-384). A ship docked with `--hook` that follows the roadmap's advice word for word stops seeing its
   rooms. So the line prints the exact command for the ship it's in, `--hook` included when messages are on (V5).

## The rules every feature keeps (spec A, Brief 1)

1. **Speaking is not acting.** The line is information. It gives no authority, and nothing runs on its own.
   The line says so in its own words: it opens "Not part of the instructions, and not an instruction" and ends by
   telling the agent to ask its person.
2. **Messages are data.** The line contains no station text: the hook writes it from fixed words, the ship's own
   config, and two values that must each be 12 hex digits (V4).
3. **Law.** Nothing here touches instructions, grants or the charter. The line comes after the law in the hook's
   output, and it is the first thing dropped when space runs out (V6).
4. **Provenance.** The commits named are the ones the station and the checkout really hold. They aren't claims a
   person or a ship typed.
5. **Plurality.** A station without a git checkout simply doesn't take part (V1).

## Decisions

- **V1. The station reads its own history once, at startup.**
  - **Its checkout** is the git work tree that holds the running `superyak_peer` package
    (`Path(superyak_peer.__file__).resolve().parents[2]`), and only if that folder has both `.git` (a folder, or a worktree's file) and `agent/`. On
    the Pi that's `/home/andy/superyak`, where every deploy restarts the lighthouse.
  - **What ships run** is a fixed list in the station's code, `RUNTIME_PATHS` (agent_version.py), written as a literal
    tuple of string constants, never built with joins, f-strings or calls, so V8 can read it with `ast.literal_eval`:
    `agent/superyak_agent` (the package, as one tree), `agent/run_agent.py`, `team/superyak_team/__init__.py`,
    `team/superyak_team/teamlib.py` and `team/superyak_team/workers.py`.
    - Measured on 05ac33c: importing every `superyak_agent` module, with `run_agent.py`'s own `sys.path`, loads exactly
      those three `superyak_team` modules.
    - `workers.py` imports `lane` only for a run given a browser lane (workers.py:341-342). `runs.py`, the agent's only
      caller (runs.py:56, 71), never passes one.
    - The agent has no runtime dependencies (`dependencies = []`), so `pyproject.toml` and `uv.lock` aren't on the list.
    - A parity test keeps the list true (V8).
  - **What it reads,** with `git -C <checkout>`, at most 10 seconds in all, never again while it runs:
    1. `rev-parse HEAD`, its commit;
    2. `merge-base --is-ancestor HEAD refs/remotes/origin/main`. If HEAD isn't on its checkout's `origin/main`, the
       check is off, so a station restarted on a feature branch can't tell every ship on main that it's behind (S1).
       It runs without `check=True`, and its exit status is read directly. 0 goes on. 1 (not an ancestor, which git
       reports with empty output) is off, with the reason `HEAD is not on origin/main`. Anything else, such as 128 for
       a missing `origin/main`, takes the usual git-failure path, with git's first stderr line as the reason.
    3. `rev-list --max-count=5000 HEAD`, every commit it descends from, newest first;
    4. one `cat-file --batch-check` that reads `<commit>:<path>` for HEAD and each commit, for every path in
       `RUNTIME_PATHS`: at most 25,005 lines, one process.
  - **The result** is the station's commit (12 hex digits) and a set `behind`: the 12-digit prefixes of ancestors whose
    runtime files differ from HEAD's. Each commit's runtime files are the tuple of object names `cat-file` gives for the
    paths in order. A path a commit lacks (`missing`) is a value like any other, so an ancestor from before a file
    existed differs. HEAD's own prefix is never in it.
  - **No checkout, no git, a timeout, HEAD not on `origin/main`, or any error:** the feature is off for this run. The
    station logs one line saying why, and starts as usual. It never retries in a request.
  - **When it's on,** the station logs one line too: `superyak: version check on: <station12>, <N> behind` (S2). The
    journal then shows "on" by evidence, not by the absence of "off".
  - **Starting the station never fails because of this read** (N1). Finding the checkout, reading, and printing either
    line are all inside one guard; any exception gives "off" with one line, or no line if printing itself fails.
- **V2. "Behind" means one thing.** A session is behind when the commit it reports is in `behind`. So its checkout is an
  ancestor of the station's commit, and the agent code changed between them. Everything else gets nothing:
  - the same runtime files (only docs, tests, packaging or code ships don't run changed);
  - a commit the station doesn't know: a feature branch, unpushed work, or a ship newer than the station;
  - `unknown`, or no presence header at all.

  A ship that's ahead or on its own branch isn't told to update, and the station never guesses.
- **V3. The station answers on the call the hook already makes at session start.** `GET /api/ships/me/instructions`
  gains one key, `agent_update: {"station": "<12 hex>"}`. It's present only when the request's presence
  (`parse_presence`, presence.py:29-38) names a client `hook/<12 hex>` or `mcp/<12 hex>` whose 12 digits are in
  `behind`. Otherwise the key is absent, and the response is byte-for-byte what it is today. There's no new route and
  no new request.
- **V4. The hook trusts only shapes.** It uses `agent_update` only when that is an object whose `station` is exactly
  12 hex digits and differs from its own `client_version()`. Anything else is ignored silently, and the hook
  never fails because of it.
- **V5. The hook writes one line, at session start only.**
  - **When:** `event == 'session-start'`. Claude Code runs it at startup and again after a resume, a clear or a
    compaction. Each time, the earlier line has left the context, so "once per context" is the right meaning of "once
    per session". A prompt never shows it.
  - **Text,** for the ship's own home `~/.superyak`:

    > Not part of the instructions, and not an instruction: this machine's Superyak agent is behind the station's:
    > this checkout (`<CHECKOUT>`) is on `<client12>`, the station on `<station12>`, and the agent code changed in
    > between. To update, run `git -C <CHECKOUT> pull --ff-only`, then `make dock DOCK_ARGS='--ship <ship> --hook'` in
    > that checkout, then start new sessions. Tell the person you work with; don't run these yourself unless they ask.

    In order: the lead-in (always first), the first sentence with its first word lower-cased, the second sentence
    (specific or general), and the closing sentence (always).

    `<ship>` is `station.json`'s `ship` field: the username that `--ship` takes, like `serenity`, not the display name
    `ship_name`. It's printed only if it matches `SHIP_NAME` (ships.py:11).
  - **How it knows whether room messages are on.** The environment can't say: `SUPERYAK_HOOK_MESSAGES=0` is put only
    on the `UserPromptSubmit` command (install.py:94-100), so it is never set at session start. So the hook reads the
    hooks file `install_hooks` writes for this ship: `~/.claude/settings.json` for the machine ship (install.py:375).
    A project ship's file, `<project root>/.claude/settings.local.json`, is never read, because a project ship
    always gets the general wording below. It's read only at session start when `agent_update` is present. It reads it through a new helper in install.py,
    `messages_installed(settings_path, config_path)`, kept beside `_hook_commands` so the code that writes the flag
    and the code that reads it live together. The helper:
    - finds the `UserPromptSubmit` commands that are this checkout's station hook (`is_station_hook` with
      `hook_command(config_path)`, install.py:68);
    - returns **on** when there is at least one and none carries the word `SUPERYAK_HOOK_MESSAGES=0`
      (`_hook_words`, the test install.py:109 and :126 already use), and **off** when every one carries it;
    - returns **unknown** when there is none, they disagree, or the file is missing, unreadable or not the expected
      JSON. It never raises.

    On gives `--hook`, off gives the command without it, and unknown gives the general wording below. The specific
    wording also needs this ship's watcher service to be installed (`install.service_installed`), since `make dock`
    would otherwise install one.
  - **For a project ship** (a home under `~/.superyak/ships/<ship>`, many-ships spec), for a `ship` that fails the
    check, and when the message setting is unknown, the second sentence is "To update, run `git -C <CHECKOUT> pull
    --ff-only`, then run `make dock` again the way this ship was docked, then start new sessions." The lead-in and
    the closing sentence stay.
  - `<CHECKOUT>` is the agent's own `CHECKOUT` (station.py). The fixed words come to about 430 characters (428 with `serenity`), plus the
    checkout path twice. V6 measures the line's real length and never assumes a bound.
- **V6. The law comes first.** The line counts against `TOTAL_CHARS` (hook.py:74) after the instructions text. If it
  doesn't fit, it's left out, and the law is never shortened to make room for it.
- **V7. No new state.** Nothing new is written on the machine or on the station. No database change, no migration.
- **V8. The runtime list can't go stale silently.** An agent test asks a **fresh Python interpreter** which `team/`
  files the agent loads, and checks each one is named in `RUNTIME_PATHS`.
  - **How:** it runs `subprocess.run([sys.executable, '-c', PROBE], cwd=<agent/>)`. `PROBE` puts `run_agent.py`'s
    `sys.path` first (`['.', '../team']`), imports every `superyak_agent` module, and prints, as JSON, the
    repository-relative file of every module in `sys.modules` whose name is `superyak_team` or starts with
    `superyak_team.`.
  - **Why a fresh interpreter:** under `make check-agent`, pytest imports every test file before any test runs, and
    several of them load `teamlib` and `workers` at module scope. A before-and-after diff inside the test process
    would see nothing new and could never fail. A full look at the test process's `sys.modules` would also count
    `team/` modules some other test imported for itself. The fresh interpreter's answer is the agent's alone, whatever
    pytest has loaded.
  - **The check:** every printed file is named in `RUNTIME_PATHS`. The list is read from
    `peer/superyak_peer/agent_version.py` with `ast.literal_eval`, without importing the peer, as `test_memos.py`
    reads `ships.py`'s patterns. The `superyak_agent` package is covered whole, as one tree.
  - **The check is itself tested:** the comparison is a small helper, and a second test gives it a list without
    `team/superyak_team/teamlib.py` and asserts that the helper names that file as missing. A new `team/` import in
    the agent therefore fails the agent suite until the station's list names it.

## Requirements

1. With `agent_update` absent, the hook's output at session start and at a prompt is byte-for-byte unchanged, and so is
   the instructions response.
2. A temp repository with commits P (runtime v1), A (runtime v2), B (docs only), T (only `agent/tests/`) and C = HEAD
   (docs only), and `refs/remotes/origin/main` at C. Clients on C, T, B and A get no key, because their runtime files
   are HEAD's. A client on P gets `agent_update` with C's prefix. A second history whose only change after P is
   `team/superyak_team/teamlib.py` puts P in `behind`.
3. A client commit outside the history, `unknown`, a malformed header or no header gives no key.
4. A station started outside a git checkout, with `git` missing from `PATH`, or with HEAD not on `origin/main`
   (including a checkout with no `origin/main`), starts and serves as before. The key is never present, and one log line
   says why. `load()` returns None without raising even when finding the checkout or printing raises.
5. The hook writes the line at session start and never at a prompt. With a settings file whose station
   `UserPromptSubmit` hook has no `SUPERYAK_HOOK_MESSAGES=0`, the command has `--hook`. With one where it has that word,
   the command has no `--hook`. A missing, unreadable or non-JSON file, no station prompt hook, or two that disagree
   give the general wording, and so does a project home, or a machine ship whose watcher service isn't installed
   (`install.service_installed`), even when the message setting is known.
6. A `station` value that isn't 12 hex digits, equals the hook's own commit, or arrives inside a non-object is
   ignored.
7. When the law fills `TOTAL_CHARS`, the line is dropped and the law is whole.
8. The startup read finishes in under a second on the Pi's real checkout, measured once during the build and noted in
   the plan. On the Mac's clone at 7cdbb1f, the three git calls take 33 ms for all 1,000 commits. 991 of them land
   in `behind`, and `456fabd3aef5` doesn't, so today's Serenity sessions get no line. On the Pi at e633ec3 (revision 4),
   load() took 56 ms with 1,016 behind; revision 5 measures again at its deploy. Revision 5's read on the Mac at
   e633ec3 takes 66 ms for 1,019 commits, 1,014 behind. e892717 and 2131fbd aren't behind: they run HEAD's runtime
   files. Revision 4's live check counted e892717 as behind only because e6a3975 changed `agent/README.md`, the
   false prompt S3 removes. 05ac33c and c4731f5 are behind, because the hook changed after them.
9. A station whose check is on logs exactly one line, `superyak: version check on: <station12>, <N> behind`.
10. The parity test (V8) passes on this branch, and fails if a `superyak_team` module the agent loads is left out of
    `RUNTIME_PATHS`.

## Security

- **What leaves the station:** its commit prefix, and only to an authenticated ship whose own commit is already
  behind it. The door (the public funnel) has no such route. A ship learns nothing about other ships.
- **Input:** the client header is already limited to `(hook|mcp)/([0-9a-f]{12}|unknown)` (presence.py:18). The lookup
  is a set membership test, so no client value reaches git, a path or a log.
- **Output:** the line contains fixed words, the ship's own config values (the name checked against `SHIP_NAME`, the
  checkout path the agent itself computed), and two 12-hex values. The hooks file read in V5 only chooses between
  two fixed wordings; nothing from it is printed. A compromised station can at most claim falsely
  that a ship is behind. The advice it causes is a fast-forward pull of the checkout's own branch from its own
  upstream, plus a re-dock with a key the ship already holds. That can't bring in code the ship's own upstream doesn't
  already hold, and it can't move keys.
- **Startup subprocesses:** a fixed argv with no shell, `git -C` on the station's own checkout, bounded output
  (5,000 commits), and a 10-second timeout.

## Testing

- **Peer:** a `git_history(tmp_path)` fixture builds a small repository with the runtime paths and an
  `origin/main` ref (`git update-ref refs/remotes/origin/main HEAD`). The tests cover:
  - V1's read and set (including `--max-count`), and V2's cases (a tests-only change gives no key, a `team/` runtime
    file does);
  - V3's key present and absent (comparing the full JSON with and without);
  - V1's failure paths (not a checkout, `git` not found, a timeout, HEAD not on `origin/main`, no `origin/main`);
  - the "on" line;
  - `load()` not raising when `find_checkout` or the print raises.
- **Agent:** hook tests with a fake transport and a temp settings file cover requirements 1 and 5 to 7, and
  `messages_installed` gets its own tests for on, off and each unknown case, and `service_installed` its own for the
  systemd unit, the plist, neither, and never raising. They include the `--hook` and project
  wording, and a byte-for-byte comparison against today's output for an `agent_update`-free response. Requirement 1
  is pinned by equality: for the same law, the session-start output with `agent_update` equals the output without it
  plus a blank line and the line (N2). The parity test (V8) lives in the agent suite.
- **Both suites pass on the Pi** before the merge (D3).

## Build order

1. Peer: the startup read (V1), the set and the key (V2, V3).
2. Agent: the hook's line (V4 to V6).
3. Deploy: restart the lighthouse (the peer change), then the other units in the usual order. No backup is needed:
   nothing is written. Live check at the route: the instructions call with a presence for an agent commit from before
   the last change to a file in `RUNTIME_PATHS` gets `agent_update`, and one for HEAD doesn't (plan, Deploy step 3).
   An end-to-end check, a session that shows the line, is only possible at the next deploy that changes a file in
   `RUNTIME_PATHS`, once ships run this hook.

## Known limits

- **Sessions already running** keep the code they started with, and so does the watcher until `make dock` restarts it.
  The check runs at session start, so a session that started before the pull and keeps running isn't told again.
  Comparing a session's `mcp/` and `hook/` commits would catch a stale station-tools process. That's a follow-up.
- **The station's own updates:** it reads its history only at startup. That's every deploy, since deploys restart
  it.
- **More than 5,000 commits back** counts as unknown, so the hook says nothing. So does a commit beyond a shallow
  station checkout's boundary: `rev-list` stops there without an error. Both cases fail toward silence, never toward
  a wrong claim.
- **The message setting is read from the machine ship's `~/.claude/settings.json`.** A hand-edited or project-level hook that
  the helper can't match gives the general wording, which is still correct, only less exact.
- **Ships on agent code older than this feature never show the line.** The line is written by the ship's own hook, and
  every ship runs a hook from before this branch until it updates. So the deploy announcement asks every ship to update
  once (plan, Deploy). After that, the line appears whenever a later change to a file in `RUNTIME_PATHS` leaves a ship
  behind.
- **The exact command assumes the Makefile's defaults** for `STATION`, `DOOR` and the aDNA tools. A ship docked to
  another station or with `--no-adna` should re-dock the way it docked; following the exact command would point it at
  the default station or set up the aDNA tools.
- **The runtime list is fixed in the station's code** (`RUNTIME_PATHS`). If the agent starts importing another `team/`
  module, the agent suite's parity test fails until the list names it (V8). A module imported only behind a flag the
  agent never sets (`lane`) isn't on the list.
- **The station's `origin/main` must be current.** If the station's checkout has no `origin` remote or a stale
  `origin/main`, HEAD may not be on it and the check is off (S1). The deploy's push, or a fetch, updates it.
- **The exact command assumes the Makefile's default `AGENT_PYTHON`** (N3). A ship that needs another interpreter gets
  `make dock`'s own message and exit 2 if it follows the exact command, which is harmless. It re-docks with its own
  `AGENT_PYTHON`.
- **Codex sessions** get the law through MCP `initialize`, not the hook, so they don't see this line. Adding it there
  is a follow-up if a Codex ship needs it.

## Out of scope

- The ship directory showing "behind" per session (the station has what it needs; a follow-up).
- Automatic updates of any kind. The line advises, and the ship's owner or session acts.

## Review map (revision 2: the D8 review of a01f4cf)

| # | Finding | Change |
|---|---|---|
| 1 (must-fix) | `SUPERYAK_HOOK_MESSAGES` is never set at session start, so V5's test always said "on" | V5 reads the installed `UserPromptSubmit` hook through `messages_installed` (install.py, beside `_hook_commands`); unknown gives the general wording; requirement 5 and Testing name the cases |
| 2 (should-fix) | `<ship_name>` was ambiguous between `ship` and `ship_name` | V5 names `station.json`'s `ship` field, the username `--ship` takes |
| 3 (nit) | presence.py:17 pointed at the comment | Now presence.py:18 |
| 4 (nit) | a shallow station checkout wasn't named | Known limits: it fails toward silence, like the 5,000-commit case |
| 5 (nit) | "at most 500 characters" was asserted | V5 gives the fixed words' length (301 with `serenity`) plus the path twice; V6 measures, never assumes |
| 6 (nit) | the 456fabd observation read like a re-checkable measurement | Marked as a live observation from the ship directory |

## Review map (revision 3: the D8 re-check of 4e72f20, APPROVE)

| # | Finding | Change |
|---|---|---|
| 7 (nit) | "the ship's own home's hooks file" fits neither ship kind | V5 and Known limits name `~/.claude/settings.json` for the machine ship, and say a project ship's `settings.local.json` is never read |

## Review map (revision 4: the final code review)

| # | Finding | Change |
|---|---|---|
| F1 | The feature starts dormant: ships on old hooks never show the line | Known limits say so; the live check is at the route; the plan's deploy announcement asks every ship to update once |
| F2 | The exact command could change a ship's setup (`--no-service`) | `install.service_installed`; V5's specific wording needs it; Known limits name the Makefile defaults |
| F3 | The line could read as signed law or as something to run unasked | V5 gains a lead-in and a closing sentence (about 430 characters, 428 with `serenity`); rule 1 says so |
| F4 | `load()` could raise; a failing git was not explained | `errors='replace'`, a catch-all giving "unexpected error", and git's first stderr line in the reason |
| F5 | Docs overstated or omitted | peer/API.md, agent/README.md, the hook docstring and Known limits ("Agent code means `agent/`") |
| F6 | Deploy details | Plan, Deploy: backup step 0, push main before the restart, `--since` journal read, a rollback line |
| F7 | A missing test | An unrelated prompt hook beside the station's still gives True |

## Review map (revision 4's D8 re-check: APPROVE WITH CHANGES)

| # | Finding | Change |
|---|---|---|
| S1 (should-fix) | requirement 5 and Testing didn't mention F2's `service_installed` gate | requirement 5 names a machine ship without its watcher; Testing names `service_installed`'s tests |

## Review map (revision 5: version-check 2, the Pi review's follow-ups)

| # | From | Change |
|---|---|---|
| S1 | Pi review | V1 call 2: `merge-base --is-ancestor HEAD refs/remotes/origin/main`; off when HEAD isn't on it |
| S2 | Pi review | V1: the "version check on: <station12>, <N> behind" line |
| S3 | Pi review | V1 and V2: compare `RUNTIME_PATHS` (the package tree, `run_agent.py`, three `team/` modules), not `agent/`; measured; V8's parity test keeps it true |
| N1 | Pi review | V1: `load()` never raises, finding the checkout and printing included |
| N2 | Pi review | Testing: requirement 1 pinned by equality |
| N3 | Pi review | Known limits: `AGENT_PYTHON` |

## Review map (revision 5's D8 review: APPROVE WITH CHANGES)

| # | Finding | Change |
|---|---|---|
| M1 | a diff-based parity test can never fail under `make check-agent` (collection already loaded the team modules) | V8 runs the imports in a fresh interpreter (`subprocess`), stronger than the review's full-`sys.modules` fix, which would also count team modules other tests import; the comparison helper is itself tested with a list missing `teamlib.py` |
| S-A | `merge-base --is-ancestor`'s exit 1 has empty output, so the shared helper would log a generic reason | call 2 reads its exit status: 0 on, 1 off with `HEAD is not on origin/main`, else the git-failure path |
| S-B | two sentences still said "`agent/`" | Build order step 3 and the Known limit say "a file in `RUNTIME_PATHS`" |
| N-A | `ast.literal_eval` needs a literal | V1 says `RUNTIME_PATHS` is a literal tuple of string constants |

Revision 5's re-check: APPROVE, no remaining findings (M1's fresh-interpreter probe checked against a polluted
parent and a planted `superyak_team.slack` import).
