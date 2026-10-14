# Version Check 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The station compares only the files ships run, refuses to judge when its own HEAD isn't on `origin/main`,
says "on" as well as "off", and never fails to start because of the read; the agent suite keeps the runtime list true.

**Architecture:** `peer/superyak_peer/agent_version.py` gains a literal `RUNTIME_PATHS` and reads one tuple of object
names per commit (one `cat-file --batch-check`), after a `merge-base --is-ancestor` guard whose exit status is read
directly. `load()` prints exactly one line, "on" or "off", inside a guard. The agent suite gains a parity test that asks
a fresh interpreter which `team/` files the agent loads, plus requirement 1's equality test. No runtime file of the
agent changes, so no ship needs to update after this deploys.

**Tech Stack:** Python 3.11+, git CLI on the station, pytest.

**Status:** revision 2, for the same reviewer's re-check. Revision 1 (560ff06) had the fresh reviewer's verdict,
APPROVE WITH CHANGES (1 must-fix, 1 should-fix, 1 nit; room message 29d2390e): see "Review map".

**Spec:** `docs/superpowers/specs/2026-10-14-version-check-design.md`, revision 5 (approved under D8, a4afa8f). Read
V1, V2, V8, requirements 2, 4, 9, 10 and the revision-5 review maps first.

**How work runs:** a fresh reviewer approves this plan. Each task gets a fresh implementer and a task review, then a
whole-branch review. The branch merges when Rio Grande approves it in "Superyak: city of AI" and the Pi suites pass
(law section 2).

## Global Constraints

- `RUNTIME_PATHS` is exactly, in this order, a literal tuple of string constants:
  `('agent/superyak_agent', 'agent/run_agent.py', 'team/superyak_team/__init__.py', 'team/superyak_team/teamlib.py', 'team/superyak_team/workers.py')`.
- The read is four git calls sharing one 10-second deadline: `rev-parse HEAD`; `merge-base --is-ancestor HEAD
  refs/remotes/origin/main` (exit status read directly: 0 on, 1 off with the reason `HEAD is not on origin/main`,
  anything else the git-failure path with git's first stderr line); `rev-list --max-count=5000 HEAD`; one
  `cat-file --batch-check=%(objectname)` with `<commit>:<path>` for every commit and every path, in that order.
- `behind` = ancestors (not HEAD) whose tuple of object names differs from HEAD's; `missing` is a value like any other.
  git prints an unresolvable `<commit>:<path>` as `<commit>:<path> missing`, ignoring the format, so that text differs
  per commit. Every answer that isn't a full hex object name becomes the one value `'missing'` before comparing.
- `load()` prints exactly one line: `superyak: version check on: <station12>, <N> behind`, or
  `superyak: version check off: <reason>`. It never raises: finding the checkout and printing are guarded too.
- No client value reaches git; git runs only at startup; no new state.
- The parity test runs its imports in a fresh interpreter (`subprocess`, `cwd=agent/`), never in the test process.

## Review Focus

Five inputs the spec implies and the tasks must pin, most likely first:

1. **A station checkout whose `origin/main` lags or is missing** (the Mac's own clone has `origin/main` at 7cdbb1f).
   The check is off with a reason that says which: `HEAD is not on origin/main`, or git's "Not a valid object name"
   line (Task 1: `test_head_not_on_origin_main_turns_the_check_off`, `test_no_origin_main_turns_the_check_off_with_gits_reason`).
2. **An agent module that prints at import time.** The probe's JSON is its last stdout line, so stray output can't
   break the parity test (Task 2: the probe reads `splitlines()[-1]`).
3. **A `PYTHONPATH` in the test's environment.** The probe runs without it, so only `run_agent.py`'s path decides
   what loads (Task 2: `env` without `PYTHONPATH`).
4. **Commits from before the runtime files existed.** Every path is `missing`, a tuple unlike HEAD's, so they're
   behind, as revision 4 counted them (Task 1: the fixture's commit O).
5. **git answering in an unexpected form** (fewer `cat-file` lines than commits times paths). The check is off, never
   a wrong set (Task 1: `test_an_unexpected_answer_from_git_turns_the_check_off`, which also closes revision 4's deferred
   minor).

---

### Task 1: Peer, the runtime list, the origin/main guard, and "on"

**Files:**
- Modify: `peer/superyak_peer/agent_version.py` (whole module below)
- Modify: `peer/tests/test_agent_version.py` (the fixture and the tests named below)

**Interfaces:**
- Consumes: nothing new. `peer/superyak_peer/app.py` and `__main__.py` keep calling `agent_update` and `load()` as
  they do; their signatures don't change.
- Produces: `RUNTIME_PATHS` (Task 2 reads it with `ast.literal_eval`); `read_history` and `load` with the behavior
  above; `AgentHistory` unchanged.

- [ ] **Step 1: Rewrite the fixture and write the failing tests**

In `peer/tests/test_agent_version.py`, replace the `history_repo` fixture with:

```python
RUNTIME = {'agent/superyak_agent/a.py': 'v1\n', 'agent/run_agent.py': 'run\n', 'team/superyak_team/__init__.py': '',
           'team/superyak_team/teamlib.py': 'lib\n', 'team/superyak_team/workers.py': 'w\n'}


@pytest.fixture
def history_repo(tmp_path):
    """O: before any runtime file. P: runtime v1. A: runtime v2. B: docs only. T: only agent/tests and agent/README.md.
    C: docs only, HEAD, with refs/remotes/origin/main at C (spec requirement 2)."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    o = commit(repo, {'README.md': 'old\n'}, 'O')
    p = commit(repo, RUNTIME, 'P')
    a = commit(repo, {'agent/superyak_agent/a.py': 'v2\n'}, 'A')
    b = commit(repo, {'docs/x.md': 'b\n'}, 'B')
    t = commit(repo, {'agent/tests/test_a.py': 't\n', 'agent/README.md': 'r\n'}, 'T')
    c = commit(repo, {'docs/x.md': 'c\n'}, 'C')
    git(repo, 'update-ref', 'refs/remotes/origin/main', c)
    (repo / 'peer' / 'superyak_peer').mkdir(parents=True)
    return repo, dict(O=o, P=p, A=a, B=b, T=t, C=c)
```

Replace `test_behind_holds_only_ancestors_whose_agent_tree_differs` with:

```python
def test_behind_holds_only_ancestors_whose_runtime_files_differ(history_repo):
    repo, c = history_repo
    history, reason = read_history(repo)
    assert reason is None
    assert history.station == c['C'][:12]
    assert history.behind == frozenset({c['P'][:12], c['O'][:12]})  # O has no runtime file at all: "missing" differs
```

In `test_the_limit_bounds_how_far_back_the_read_goes`, change the comment to `# C, T, B: all share HEAD's runtime
files`. In `test_agent_update_names_the_station_only_for_a_client_behind`, loop over `('C', 'T', 'B', 'A')`.

Replace `test_load_reads_a_real_checkout_quietly` with:

```python
def test_load_reads_a_real_checkout_and_says_it_is_on(history_repo, capsys):
    repo, c = history_repo
    history = load(repo / 'peer' / 'superyak_peer' / 'agent_version.py')
    assert history == AgentHistory(c['C'][:12], frozenset({c['P'][:12], c['O'][:12]}))
    assert capsys.readouterr().err == f'superyak: version check on: {c["C"][:12]}, 2 behind\n'
```

Append:

```python
def test_a_team_runtime_change_makes_earlier_commits_behind(tmp_path):
    repo = tmp_path / 'repo2'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    p = commit(repo, RUNTIME, 'P')
    x = commit(repo, {'team/superyak_team/teamlib.py': 'lib v2\n'}, 'X')
    git(repo, 'update-ref', 'refs/remotes/origin/main', x)
    history, reason = read_history(repo)
    assert reason is None and history.behind == frozenset({p[:12]})


def test_a_runtime_path_missing_from_head_and_its_ancestors_alike_is_ignored(tmp_path):
    repo = tmp_path / 'repo3'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    p = commit(repo, {k: v for k, v in RUNTIME.items() if not k.endswith('workers.py')}, 'P')
    c = commit(repo, {'docs/x.md': 'c\n'}, 'C')
    git(repo, 'update-ref', 'refs/remotes/origin/main', c)
    history, reason = read_history(repo)
    assert reason is None and history.behind == frozenset()  # workers.py is missing from both: not a difference


def test_head_not_on_origin_main_turns_the_check_off(history_repo):
    repo, c = history_repo
    git(repo, 'checkout', '-q', '-b', 'feature')
    commit(repo, {'agent/superyak_agent/a.py': 'feature\n'}, 'F')
    assert read_history(repo) == (None, 'HEAD is not on origin/main')


def test_no_origin_main_turns_the_check_off_with_gits_reason(history_repo):
    repo, _ = history_repo
    git(repo, 'update-ref', '-d', 'refs/remotes/origin/main')
    history, reason = read_history(repo)
    assert history is None and reason.startswith('git failed (CalledProcessError): ') and len(reason) > 33


def test_an_unexpected_answer_from_git_turns_the_check_off(history_repo):
    repo, c = history_repo

    def run(argv, **kwargs):
        if 'cat-file' in argv:
            return subprocess.CompletedProcess(argv, 0, stdout='only-one-line\n', stderr='')
        return subprocess.run(argv, **kwargs)
    assert read_history(repo, run=run) == (None, 'git answered in an unexpected form')


def test_load_never_raises_when_finding_the_checkout_raises(history_repo, monkeypatch, capsys):
    from superyak_peer import agent_version
    repo, _ = history_repo

    def boom(*args, **kwargs):
        raise PermissionError('no')
    monkeypatch.setattr(agent_version, 'find_checkout', boom)
    assert load(repo / 'peer' / 'superyak_peer' / 'agent_version.py') is None
    err = capsys.readouterr().err
    assert err.count('\n') == 1 and 'unexpected error (PermissionError)' in err


def test_load_never_raises_when_printing_raises(tmp_path):
    class Broken:
        def write(self, text):
            raise OSError('stderr is gone')

        def flush(self):
            raise OSError('stderr is gone')
    lone = tmp_path / 'lone' / 'peer' / 'superyak_peer'
    lone.mkdir(parents=True)
    assert load(lone / 'agent_version.py', err=Broken()) is None
```

`test_the_ten_second_budget_is_shared_by_every_call` stays as it is: the second call is now `merge-base`, and it still
gets 2.0 seconds.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_agent_version.py`
Expected (checked while writing this plan): 9 failed, 16 passed. The failures:
- `test_behind_holds_only_ancestors_whose_runtime_files_differ`, `test_the_limit_bounds_how_far_back_the_read_goes`
  and `test_agent_update_names_the_station_only_for_a_client_behind`: today's code compares `agent/` trees, so B is
  behind;
- `test_a_team_runtime_change_makes_earlier_commits_behind`;
- the two origin/main tests;
- `test_load_reads_a_real_checkout_and_says_it_is_on` (no line today);
- the two never-raises tests.

`test_an_unexpected_answer_from_git_turns_the_check_off` and
`test_a_runtime_path_missing_from_head_and_its_ancestors_alike_is_ignored` pass on today's code too, because they're
guards. The second one fails if the module's `names = [n if FULL_HEX.fullmatch(n) else 'missing' ...]` line is left
out. Check that once after Step 3, by commenting the line out and running that test, then restore the line. Put the
observation in the report.

- [ ] **Step 3: Write the module**

Replace `peer/superyak_peer/agent_version.py` with:

```python
"""Version check (docs/superpowers/specs/2026-10-14-version-check-design.md, V1-V3 and V8): at startup the station
reads its own git history once, so the instructions route can tell a ship whose agent code is behind. Nothing here runs
in a request, and no client value ever reaches git."""
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

HISTORY_LIMIT = 5000
TIMEOUT_SECONDS = 10.0
FULL_HEX = re.compile(r'[0-9a-f]{40,64}')
# What ships run (V1): the agent package as one tree, its entry point, and the team modules the agent imports. A literal
# tuple of string constants, so the agent suite's parity test can read it with ast.literal_eval (V8).
RUNTIME_PATHS = (
    'agent/superyak_agent',
    'agent/run_agent.py',
    'team/superyak_team/__init__.py',
    'team/superyak_team/teamlib.py',
    'team/superyak_team/workers.py',
)


class AgentHistory(NamedTuple):
    station: str          # the station's commit, 12 hex digits
    behind: frozenset     # 12-digit prefixes of ancestors whose runtime files differ from HEAD's (V1)


def find_checkout(module_file=__file__):
    """The git work tree holding this package, only if it has both .git (a folder, or a worktree's file) and agent/."""
    root = Path(module_file).resolve().parents[2]
    return root if (root / '.git').exists() and (root / 'agent').is_dir() else None


def read_history(checkout, run=subprocess.run, limit=HISTORY_LIMIT, timeout=TIMEOUT_SECONDS, clock=time.monotonic):
    """(AgentHistory, None), or (None, why) when HEAD isn't on origin/main, or git is missing, fails, is slow or
    answers oddly. Never raises."""
    deadline = clock() + timeout

    def git(*args, stdin=None, check=True):
        left = deadline - clock()
        if left <= 0:
            raise subprocess.TimeoutExpired('git', timeout)
        return run(['git', '-C', str(checkout), *args], input=stdin, capture_output=True, text=True, errors='replace',
                   timeout=left, check=check)

    try:
        head = git('rev-parse', 'HEAD').stdout.strip()
        on_main = git('merge-base', '--is-ancestor', 'HEAD', 'refs/remotes/origin/main', check=False)
        if on_main.returncode == 1:  # not an ancestor; git says so with empty output
            return None, 'HEAD is not on origin/main'
        if on_main.returncode != 0:
            raise subprocess.CalledProcessError(on_main.returncode, 'git merge-base', stderr=on_main.stderr)
        commits = git('rev-list', f'--max-count={limit}', 'HEAD').stdout.split()
        names = git('cat-file', '--batch-check=%(objectname)',
                    stdin=''.join(f'{c}:{p}\n' for c in commits for p in RUNTIME_PATHS)).stdout.splitlines()
    except subprocess.TimeoutExpired:
        return None, f'git ran out of time ({timeout:g} seconds)'
    except subprocess.CalledProcessError as error:
        stderr = error.stderr if isinstance(error.stderr, str) else ''
        first = (stderr.strip().splitlines() or [''])[0].strip()[:200]  # station-local text, never client data
        return None, f'git failed (CalledProcessError): {first}' if first else 'git failed (CalledProcessError)'
    except (OSError, subprocess.SubprocessError) as error:
        return None, f'git failed ({type(error).__name__})'
    width = len(RUNTIME_PATHS)
    if not FULL_HEX.fullmatch(head) or not commits or commits[0] != head or len(names) != len(commits) * width:
        return None, 'git answered in an unexpected form'
    # git prints a path a commit lacks as "<commit>:<path> missing", ignoring the format: different for every commit.
    # One value for all of them, so a path missing from HEAD and an ancestor alike compares equal (V1).
    names = [n if FULL_HEX.fullmatch(n) else 'missing' for n in names]
    files = {c: tuple(names[i * width:(i + 1) * width]) for i, c in enumerate(commits)}
    behind = frozenset(c[:12] for c in commits if c != head and files[c] != files[head])
    return AgentHistory(head[:12], behind), None


def load(module_file=__file__, run=subprocess.run, err=None):
    """V1 at startup: the history, or None. Exactly one line, "on" or "off" with why, and it never raises (N1): the
    station must start whatever happens here."""
    err = err or sys.stderr
    try:
        checkout = find_checkout(module_file)
        if checkout is None:
            history, reason = None, 'not running from a git checkout with agent/'
        else:
            history, reason = read_history(checkout, run=run)
    except Exception as error:  # noqa: BLE001
        history, reason = None, f'unexpected error ({type(error).__name__})'
    line = (f'superyak: version check on: {history.station}, {len(history.behind)} behind' if history is not None
            else f'superyak: version check off: {reason}')
    try:
        print(line, file=err, flush=True)
    except Exception:  # noqa: BLE001 - a broken stderr must not stop the station either
        pass
    return history


def agent_update(history, presence):
    """V2, V3: {'station': ...} when the presence's commit is behind; None for anything else."""
    if history is None or not presence:
        return None
    commit = presence['client'].partition('/')[2]
    return {'station': history.station} if commit in history.behind else None
```

- [ ] **Step 4: Run the tests to verify they pass, then the peer suite**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_agent_version.py tests/test_agent_version_route.py tests/test_packaging.py`
Expected: all pass.
Run: `make check-peer` (from the repository root). Expected: 535 passed (528 at main e633ec3, plus 7). Name any
failure.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/agent_version.py peer/tests/test_agent_version.py
git commit -m "Version check 2, peer: compare the files ships run, require HEAD on origin/main, say on (S1-S3, N1)"
```

---

### Task 2: Agent, the parity test and requirement 1's equality

**Files:**
- Create: `agent/tests/test_runtime_parity.py`
- Modify: `agent/tests/test_hook_version.py` (append one test)
- Modify: `agent/README.md` (one sentence in the "Behind the station" paragraph)

**Interfaces:**
- Consumes: `RUNTIME_PATHS` from Task 1, read from `peer/superyak_peer/agent_version.py` with `ast.literal_eval`
  (the peer is never imported); `hook._version_line`, `hook.run`, and test_hook_version.py's `ship` fixture and `law`
  helper, as they are at e633ec3.
- Produces: tests only. No runtime file of the agent changes.

- [ ] **Step 1: Write the parity tests**

Create `agent/tests/test_runtime_parity.py`:

```python
"""Version check V8: the station's RUNTIME_PATHS names every team/ file the agent loads. A fresh interpreter answers,
because under the full suite pytest has already imported team modules before any test runs."""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1]
ROOT = AGENT.parent
PROBE = r'''
import importlib, json, pkgutil, sys
from pathlib import Path
sys.path[:0] = ['.', '../team']  # run_agent.py's own path
import superyak_agent
for module in pkgutil.iter_modules(superyak_agent.__path__):
    importlib.import_module('superyak_agent.' + module.name)
root = Path('..').resolve()
print(json.dumps(sorted(str(Path(mod.__file__).resolve().relative_to(root)) if getattr(mod, '__file__', None)
                        else '(no file) ' + name  # a namespace package or an extension can't hide from the check
                        for name, mod in list(sys.modules.items())
                        if name == 'superyak_team' or name.startswith('superyak_team.'))))
'''


def runtime_paths():
    """RUNTIME_PATHS from peer/superyak_peer/agent_version.py, read with ast, without importing the peer."""
    tree = ast.parse((ROOT / 'peer' / 'superyak_peer' / 'agent_version.py').read_bytes())
    [node] = [n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'RUNTIME_PATHS']
    return ast.literal_eval(node.value)


def missing_from(paths, files):
    """The files no path names: a path names a file itself, or every file under it when it is a folder."""
    return [f for f in files if not any(f == p or f.startswith(p + '/') for p in paths)]


def agent_team_files():
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    done = subprocess.run([sys.executable, '-c', PROBE], cwd=AGENT, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])  # the last line: an import that prints can't break it


def test_runtime_paths_name_every_team_file_the_agent_loads():
    files = agent_team_files()
    assert 'team/superyak_team/workers.py' in files  # the probe really sees the agent's imports
    assert missing_from(runtime_paths(), files) == []


def test_every_runtime_path_still_names_a_file():
    files = agent_team_files()

    def stale(path):  # a team entry must be a file the agent loads; an agent entry must exist
        return path not in files if path.startswith('team/') else not (ROOT / path).exists()
    assert [path for path in runtime_paths() if stale(path)] == []  # a renamed or removed file must leave the list too


def test_the_check_names_a_team_file_left_out_of_the_list():
    paths = tuple(p for p in runtime_paths() if p != 'team/superyak_team/teamlib.py')
    assert missing_from(paths, agent_team_files()) == ['team/superyak_team/teamlib.py']
```

Append to `agent/tests/test_hook_version.py`:

```python
def test_the_line_is_the_only_difference_at_session_start(ship):
    fake, serenity, config, settings, tmp_path = ship
    install_hooks(settings, config, messages=True)
    law(fake, serenity)
    without = hook.run(config, transport=fake, event='session-start', session_id='a', sessions_dir=tmp_path / 'a')
    law(fake, serenity, agent_update={'station': STATION})
    with_key = hook.run(config, transport=fake, event='session-start', session_id='b', sessions_dir=tmp_path / 'b')
    line = hook._version_line({'agent_update': {'station': STATION}}, config)
    assert line and with_key == without + '\n\n' + line
```

- [ ] **Step 2: Run them**

Run: `cd agent && uv run --locked --extra dev python -m pytest -q tests/test_runtime_parity.py tests/test_hook_version.py`
Expected: 24 passed once Task 1 is in. These are guards, so they pass at once. Check that each can fail instead:
- temporarily remove `'team/superyak_team/teamlib.py',` from `RUNTIME_PATHS` in agent_version.py: the first parity
  test fails, naming teamlib.py; restore it;
- temporarily change `'\n\n'.join` in hook.py's `_run_all` version-line block to `'\n'.join`: the equality test
  fails; restore it.
Put both observations in the report. `git diff --stat` must show neither file changed afterwards.

- [ ] **Step 3: The README sentence**

In `agent/README.md`'s "Behind the station" paragraph, change "When the station's agent code has changed since this
checkout's commit" to "When the files ships run (the agent package, `run_agent.py`, and the team modules it imports)
have changed since this checkout's commit". If the paragraph words it differently, make the same change of meaning
there and say so in the report.

- [ ] **Step 4: The agent suite**

Run: `make check-agent` (from the repository root). Expected: 631 passed (627 at main e633ec3, plus 4). Name any
failure.

- [ ] **Step 5: Commit**

```bash
git add agent/tests/test_runtime_parity.py agent/tests/test_hook_version.py agent/README.md
git commit -m "Version check 2, agent: the runtime parity test (V8) and requirement 1 by equality (N2)"
```

---

## Deploy (Rio Grande, on the Pi, after the merge under law section 2)

The runtime change is the peer's; the agent change is tests and a README sentence, so no ship needs to update.

0. **Back up the database** (as for revision 4):
   `umask 077; BACKUP=~/.local/share/superyak/backups/peer-$(date +%Y%m%d-%H%M%S)-pre-version-check-2.sqlite3; python3 -c 'import sqlite3, sys; sqlite3.connect(sys.argv[1]).backup(sqlite3.connect(sys.argv[2]))' ~/.local/share/superyak/lighthouse/peer.sqlite3 "$BACKUP"; chmod 600 "$BACKUP"; stat -c '%a %s %n' "$BACKUP"`
1. **Merge with `--no-ff`, push, then guard before any restart:**
   `git -C ~/superyak push origin main && test "$(git -C ~/superyak branch --show-current)" = main && test "$(git -C ~/superyak rev-parse HEAD)" = "$(git -C ~/superyak rev-parse origin/main)"`.
   The guard matters more now: S1 turns the check off if HEAD isn't on `origin/main`.
2. **Time the read** (requirement 8): `cd ~/superyak/peer && time uv run --locked python -c "from superyak_peer import agent_version; h = agent_version.load(); print(h.station if h else 'off', len(h.behind) if h else '')"`.
   It prints the "on" line itself now.
3. **Restart and read the journal:**
   ```bash
   SINCE=$(date '+%Y-%m-%d %H:%M:%S')
   for unit in lighthouse door ship odo wormhole; do systemctl --user restart superyak-$unit; done
   sleep 3
   for unit in lighthouse door ship odo wormhole; do printf '%s ' superyak-$unit; systemctl --user is-active superyak-$unit; done
   journalctl --user-unit superyak-lighthouse --since "$SINCE" --no-pager | grep 'version check'
   ```
   **Expected:** five `active` lines, and one `superyak: version check on: <HEAD 12>, <N> behind` line: evidence, not
   absence (S2).
4. **Live check at the route** (one presence row named `version-check-live`, pruned after a day):
   ```bash
   cd ~/superyak && python3 - <<'EOF'
   import subprocess, sys; sys.path[:0] = ['agent', 'team']  # as run_agent.py does
   from superyak_agent.station import StationClient, load_config, presence_headers
   config = load_config()
   for commit in ('05ac33c78804', 'e892717', 'HEAD'):
       full = subprocess.run(['git', 'rev-parse', commit], capture_output=True, text=True, check=True).stdout.strip()
       client = StationClient(config['station'], config['key'], config.get('origin'), None,
                              presence_headers('version-check-live', f'hook/{full[:12]}'))
       print(commit, '->', client.instructions().get('agent_update'))
   EOF
   ```
   **Expected:** 05ac33c (before the version check's hook) gets `{'station': ...}`; e892717 (revision 4's live-check
   commit, behind then only through a README) gets `None`; HEAD gets `None`.
5. **Revert rule** (Rio Grande's, 2026-10-14): revert only if a unit isn't active or the route changes for a ship that
   is current: `git -C ~/superyak revert -m 1 --no-edit <merge> && git -C ~/superyak push origin main`, then restart the
   five units. "Version check off" alone is a follow-up.
6. **Announce the merge** in the room with the measured time and the "on" line. No ship needs to update.

## Self-review notes

- **Spec coverage:** S3 and V1/V2 (`RUNTIME_PATHS`, the tuple read) and S1 (the guard and its exit statuses) and S2
  (the "on" line) and N1 (the guarded `load`): Task 1. V8 (the parity test and its self-test) and N2 (equality): Task 2.
  N3 is spec text only. Requirements 2, 4, 9: Task 1; 10 and 1: Task 2; 8: Deploy step 2.
- **Interfaces:** `RUNTIME_PATHS` (Task 1) is read by name in Task 2; `load`, `read_history`, `agent_update` and
  `AgentHistory` keep their signatures, so `app.py`, `__main__.py` and test_agent_version_route.py need no change.
- **Dry run:** every block was run as written in a scratch worktree, before each review. Revision 2's run:
  - Task 1's tests against today's module: 9 failed, 16 passed, as Step 2 says. With the new module, the focused peer
    run gives 33 passed. Without the normalization line, exactly the new missing-path test fails.
  - Task 2: 24 passed.
  - Full suites: `make check-agent` 631 passed, `make check-peer` 535 passed.
  - Revision 1's mutation checks and the Deploy script's imports were re-run by the reviewer and still hold.

## Review map (revision 2: the review of 560ff06)

| # | Finding | Change |
|---|---|---|
| M1 | git's `missing` answer embeds the commit, so a path absent from HEAD and an ancestor alike compared unequal | the module maps every non-hex answer to `'missing'`; Task 1 adds `test_a_runtime_path_missing_from_head_and_its_ancestors_alike_is_ignored` and checks it fails without the line; Global Constraints says so |
| S1 | the parity test checked only one direction | Task 2 adds `test_every_runtime_path_still_names_a_file` (team entries among the files the agent loads, agent entries present) |
| N1 | a team module without `__file__` was invisible | the probe reports it as `(no file) <name>`, which the check names |
