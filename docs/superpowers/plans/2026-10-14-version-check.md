# Version Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A ship whose agent code is behind the station's sees one line at session start, with the exact command to
update. Nothing changes for every other ship.

**Architecture:** At startup the station reads its own git history once and builds the set of ancestor commits whose
`agent/` tree differs from HEAD's (peer `agent_version.py`). The instructions route adds `agent_update` only when the
request's presence names a commit in that set. The hook, at session start only, turns that key into one line from
fixed words. It decides whether to include `--hook` by reading the installed prompt hook through a new
`install.messages_installed`.

**Tech Stack:** Python 3.11+, FastAPI (peer), stdlib only (agent), git CLI on the station, pytest.

**Status:** revision 2, for the same reviewer's re-check. Revision 1 (457b5a5) had the fresh reviewer's verdict, APPROVE
WITH CHANGES (2 must-fix, 1 should-fix, 4 nits; room message b7b4cc72). This revision makes them ("Review map").

**Spec:** `docs/superpowers/specs/2026-10-14-version-check-design.md` (revision 3, approved under D8). Read it first.
Requirement and decision numbers below (V1-V7, requirements 1-8) are the spec's.

**How work runs (station law and house practice):** a fresh reviewer approves this plan (D8 practice for plans). Each
task gets a fresh implementer and a per-task review, then a whole-branch review and a fix wave. The branch merges
only when Rio Grande approves it in "Superyak: city of AI" and both suites pass on the Pi (law section 2).

## Global Constraints

- Commit prefixes are exactly 12 lowercase hex digits (`[0-9a-f]{12}`), the form `client_version()` sends.
- The history read is at most 5,000 commits (`rev-list --max-count=5000`), and all git calls together take at most 10
  seconds.
- git is run with a fixed argv, no shell, `git -C <checkout>`, only at station startup, never in a request.
- With `agent_update` absent, the hook's output and the instructions response are byte-for-byte what they are today
  (requirement 1).
- The line shows only when `event == 'session-start'`, after the law, and only if it fits in `TOTAL_CHARS` (9,500)
  without shortening the law (V5, V6).
- No new state anywhere: no file written, no table, no migration (V7).
- The line's words are verbatim from spec V5:
  - Specific: "This machine's Superyak agent is behind the station's: this checkout (`<CHECKOUT>`) is on `<client12>`,
    the station on `<station12>`, and the agent code changed in between. To update, run `git -C <CHECKOUT> pull
    --ff-only`, then `make dock DOCK_ARGS='--ship <ship> --hook'` in that checkout, then start new sessions."
  - General second sentence: "To update, run `git -C <CHECKOUT> pull --ff-only`, then run `make dock` again the way
    this ship was docked, then start new sessions."
- Station text never reaches the line: only the 12-hex `station` value, after it has been checked.
- `peer/pyproject.toml` keeps reviewed release inventories that list every file. A new peer module goes in both the
  sdist and the wheel `only-include` lists, and a new peer test file in the sdist list, or the built station fails to
  start (`test_packaging.py`). The agent package has no new module in this plan.

## Review Focus

Five inputs the spec implies but its requirements don't name, most likely first. Each has a test in its task.

1. **A checkout path with a space or a quote** (`/Users/a b/superyak`). A person copies the command into a shell, so
   it must still work: the path in the `git -C <path> pull --ff-only` command is `shlex.quote`d (the `make dock`
   command holds no path) (Task 4, `test_a_checkout_path_with_a_space_is_quoted_in_the_commands`).
2. **The station's checkout is a git worktree or a detached HEAD.** `.git` is a file in a worktree, and a deploy can
   leave HEAD detached. Both must still read (Task 1, `test_a_worktree_checkout_is_found_and_read` and
   `test_a_detached_head_reads`).
3. **The settings file holds another clone's station hook** (a second checkout of superyak on the same Mac). It isn't
   this checkout's hook, so it must not decide `--hook` (Task 3, `test_another_checkouts_hook_is_not_ours`).
4. **An `mcp/` client**, not only `hook/`. A Codex or MCP call with an old commit gets the key too, because V3 names
   both forms (Task 2, `test_an_mcp_client_behind_gets_the_key_too`).
5. **An empty law** (no layers) with `agent_update` present. The line then stands alone at session start, and nothing
   else changes (Task 4, `test_the_line_stands_alone_when_there_is_no_law`).

---

### Task 1: Peer, the station reads its agent history

**Files:**
- Create: `peer/superyak_peer/agent_version.py`
- Modify: `peer/pyproject.toml` (both `only-include` inventories)
- Test: `peer/tests/test_agent_version.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `AgentHistory(station: str, behind: frozenset[str])`, a `NamedTuple`;
  - `find_checkout(module_file: str | Path = __file__) -> Path | None`;
  - `read_history(checkout: Path, run=subprocess.run, limit: int = 5000, timeout: float = 10.0, clock=time.monotonic) -> tuple[AgentHistory | None, str | None]`, which returns `(history, None)` or `(None, reason)` and never raises;
  - `load(module_file=__file__, run=subprocess.run, err=None) -> AgentHistory | None`, which writes one line to `err` (default `sys.stderr`) when the check is off;
  - `agent_update(history: AgentHistory | None, presence: dict | None) -> dict | None`.

- [ ] **Step 1: Write the failing tests**

```python
# peer/tests/test_agent_version.py
import subprocess
from pathlib import Path

import pytest

from superyak_peer import agent_version
from superyak_peer.agent_version import AgentHistory, agent_update, find_checkout, load, read_history


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, files, message):
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, 'add', '-A')
    git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', message)
    return git(repo, 'rev-parse', 'HEAD')


@pytest.fixture
def history_repo(tmp_path):
    """P: agent v1. A: agent v2. B, C: docs only. HEAD is C (requirement 2). Plus O, before agent/ existed."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    o = commit(repo, {'README.md': 'old\n'}, 'O')
    p = commit(repo, {'agent/a.py': 'v1\n'}, 'P')
    a = commit(repo, {'agent/a.py': 'v2\n'}, 'A')
    b = commit(repo, {'docs/x.md': 'b\n'}, 'B')
    c = commit(repo, {'docs/x.md': 'c\n'}, 'C')
    (repo / 'peer' / 'superyak_peer').mkdir(parents=True)
    return repo, dict(O=o, P=p, A=a, B=b, C=c)


def test_behind_holds_only_ancestors_whose_agent_tree_differs(history_repo):
    repo, c = history_repo
    history, reason = read_history(repo)
    assert reason is None
    assert history.station == c['C'][:12]
    assert history.behind == frozenset({c['P'][:12], c['O'][:12]})  # O has no agent/ at all: "missing" differs


def test_the_limit_bounds_how_far_back_the_read_goes(history_repo):
    repo, c = history_repo
    history, _ = read_history(repo, limit=3)  # C, B, A: all share HEAD's agent tree
    assert history.behind == frozenset()


def test_agent_update_names_the_station_only_for_a_client_behind(history_repo):
    repo, c = history_repo
    history, _ = read_history(repo)
    for name in ('C', 'B', 'A'):
        assert agent_update(history, {'name': 's', 'client': f'hook/{c[name][:12]}', 'mode': None}) is None, name
    assert agent_update(history, {'name': 's', 'client': f'hook/{c["P"][:12]}', 'mode': None}) == {'station': c['C'][:12]}


@pytest.mark.parametrize('presence', [None, {'name': 's', 'client': 'unknown', 'mode': None},
                                      {'name': 's', 'client': 'hook/0123456789ab', 'mode': None}])
def test_no_presence_unknown_or_a_commit_outside_the_history_gets_nothing(history_repo, presence):
    repo, _ = history_repo
    history, _ = read_history(repo)
    assert agent_update(history, presence) is None


def test_no_history_means_no_key():
    assert agent_update(None, {'name': 's', 'client': 'hook/0123456789ab', 'mode': None}) is None


def test_find_checkout_needs_git_and_agent(history_repo, tmp_path):
    repo, _ = history_repo
    module = repo / 'peer' / 'superyak_peer' / 'agent_version.py'
    assert find_checkout(module) == repo.resolve()
    lone = tmp_path / 'lone' / 'peer' / 'superyak_peer'
    lone.mkdir(parents=True)
    assert find_checkout(lone / 'agent_version.py') is None


def test_a_worktree_checkout_is_found_and_read(history_repo, tmp_path):
    repo, c = history_repo
    tree = tmp_path / 'wt'
    git(repo, 'worktree', 'add', '-q', str(tree), c['C'])
    (tree / 'peer' / 'superyak_peer').mkdir(parents=True)
    assert (tree / '.git').is_file()
    assert find_checkout(tree / 'peer' / 'superyak_peer' / 'agent_version.py') == tree.resolve()
    history, reason = read_history(tree)
    assert reason is None and history.station == c['C'][:12]


def test_a_detached_head_reads(history_repo):
    repo, c = history_repo
    git(repo, 'checkout', '-q', '--detach', c['B'])
    history, reason = read_history(repo)
    assert reason is None and history.station == c['B'][:12] and c['P'][:12] in history.behind


@pytest.mark.parametrize('error', [FileNotFoundError('git'), subprocess.TimeoutExpired('git', 10),
                                   subprocess.CalledProcessError(128, 'git')])
def test_git_missing_slow_or_failing_turns_the_check_off(history_repo, error):
    repo, _ = history_repo

    def run(*args, **kwargs):
        raise error
    history, reason = read_history(repo, run=run)
    assert history is None and reason


def test_the_ten_second_budget_is_shared_by_every_call(history_repo):
    repo, _ = history_repo
    times = iter([0.0, 4.0, 8.0, 12.0, 16.0])
    seen = []

    def run(argv, **kwargs):
        seen.append(kwargs['timeout'])
        return subprocess.run(argv, **kwargs)
    history, reason = read_history(repo, run=run, clock=lambda: next(times))
    assert history is None and 'time' in reason
    assert seen == [6.0, 2.0]  # 10 - 4, then 10 - 8; the third call finds no time left


def test_load_logs_one_line_when_off(tmp_path, capsys):
    lone = tmp_path / 'lone' / 'peer' / 'superyak_peer'
    lone.mkdir(parents=True)
    assert load(lone / 'agent_version.py') is None
    err = capsys.readouterr().err
    assert err.count('\n') == 1 and 'version check off' in err


def test_load_reads_a_real_checkout_quietly(history_repo, capsys):
    repo, c = history_repo
    history = load(repo / 'peer' / 'superyak_peer' / 'agent_version.py')
    assert history == AgentHistory(c['C'][:12], frozenset({c['P'][:12], c['O'][:12]}))
    assert capsys.readouterr().err == ''
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_agent_version.py`
Expected: an error at collection, `ModuleNotFoundError: No module named 'superyak_peer.agent_version'`.

- [ ] **Step 3: Write the module**

```python
# peer/superyak_peer/agent_version.py
"""Version check (docs/superpowers/specs/2026-10-14-version-check-design.md, V1-V3): at startup the station reads its
own git history once, so the instructions route can tell a ship whose agent code is behind. Nothing here runs in a
request, and no client value ever reaches git."""
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

HISTORY_LIMIT = 5000
TIMEOUT_SECONDS = 10.0
FULL_HEX = re.compile(r'[0-9a-f]{40,64}')


class AgentHistory(NamedTuple):
    station: str          # the station's commit, 12 hex digits
    behind: frozenset     # 12-digit prefixes of ancestors whose agent/ tree differs from HEAD's (V1)


def find_checkout(module_file=__file__):
    """The git work tree holding this package, only if it has both .git (a folder, or a worktree's file) and agent/."""
    root = Path(module_file).resolve().parents[2]
    return root if (root / '.git').exists() and (root / 'agent').is_dir() else None


def read_history(checkout, run=subprocess.run, limit=HISTORY_LIMIT, timeout=TIMEOUT_SECONDS, clock=time.monotonic):
    """(AgentHistory, None), or (None, why) when git is missing, fails, is slow or answers oddly. Never raises."""
    deadline = clock() + timeout

    def git(*args, stdin=None):
        left = deadline - clock()
        if left <= 0:
            raise subprocess.TimeoutExpired('git', timeout)
        return run(['git', '-C', str(checkout), *args], input=stdin, capture_output=True, text=True, timeout=left,
                   check=True).stdout

    try:
        head = git('rev-parse', 'HEAD').strip()
        tree = git('rev-parse', 'HEAD:agent').strip()
        commits = git('rev-list', f'--max-count={limit}', 'HEAD').split()
        trees = git('cat-file', '--batch-check=%(objectname)', stdin=''.join(f'{c}:agent\n' for c in commits)).splitlines()
    except subprocess.TimeoutExpired:
        return None, f'git ran out of time ({timeout:g} seconds)'
    except (OSError, subprocess.SubprocessError) as error:
        return None, f'git failed ({type(error).__name__})'
    if not FULL_HEX.fullmatch(head) or not FULL_HEX.fullmatch(tree) or len(trees) != len(commits):
        return None, 'git answered in an unexpected form'
    behind = frozenset(c[:12] for c, t in zip(commits, trees) if t != tree and c != head)
    return AgentHistory(head[:12], behind), None


def load(module_file=__file__, run=subprocess.run, err=None):
    """V1 at startup: the history, or None with one line saying why the check is off."""
    err = err or sys.stderr
    checkout = find_checkout(module_file)
    if checkout is None:
        print('superyak: version check off: not running from a git checkout with agent/', file=err, flush=True)
        return None
    history, reason = read_history(checkout, run=run)
    if history is None:
        print(f'superyak: version check off: {reason}', file=err, flush=True)
    return history


def agent_update(history, presence):
    """V2, V3: {'station': ...} when the presence's commit is behind; None for anything else."""
    if history is None or not presence:
        return None
    commit = presence['client'].partition('/')[2]
    return {'station': history.station} if commit in history.behind else None
```

- [ ] **Step 4: List the new files in the release inventories**

In `peer/pyproject.toml`, add `"superyak_peer/agent_version.py",` right after `"superyak_peer/access_requests.py",`
in **both** `only-include` lists: `[tool.hatch.build.targets.sdist]` (about line 47) and
`[tool.hatch.build.targets.wheel]` (about line 121). Add `"tests/test_agent_version.py",` right after
`"tests/test_access_requests.py",` in the sdist list (about line 82). The lists are alphabetical. Every peer test file
is listed there, and a test that isn't listed silently drops out of the released source bundle.

- [ ] **Step 5: Run the tests to verify they pass, with the packaging tests**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_agent_version.py tests/test_packaging.py`
Expected: 16 + 3 passed. Without Step 4, Task 2's import of `agent_version` in `__main__.py` makes two packaging tests
fail: the built station can't import the module.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/agent_version.py peer/tests/test_agent_version.py peer/pyproject.toml
git commit -m "Version check, peer: the station reads its agent history once at startup (V1, V2)"
```

---

### Task 2: Peer, the instructions route answers a ship that is behind

**Files:**
- Modify: `peer/superyak_peer/app.py` (`create_app` signature at :116 and its body near :137; the
  `/api/ships/me/instructions` route at :221-223)
- Modify: `peer/superyak_peer/__main__.py:335` (the `serve` command's `create_app` call)
- Modify: `peer/pyproject.toml` (the sdist inventory: the new test file)
- Test: `peer/tests/test_agent_version_route.py`

**Interfaces:**
- Consumes: `AgentHistory`, `agent_update`, `load` from Task 1.
- Produces: `create_app(..., agent_history=None)`, kept on `app.state.agent_history`; and the response key
  `agent_update: {"station": "<12 hex>"}` on `GET /api/ships/me/instructions`.

- [ ] **Step 1: Write the failing tests**

```python
# peer/tests/test_agent_version_route.py
from fastapi.testclient import TestClient

from superyak_peer.agent_version import AgentHistory

BEHIND, CURRENT, STATION = 'aaaaaaaaaaaa', 'bbbbbbbbbbbb', 'cccccccccccc'


def ship_client(app, client=None):
    store = app.state.store
    ship = store.create_station_ship('odo', 'Odo')
    headers = {'origin': 'http://testserver', 'authorization': f'Bearer {store.issue_ship_key(ship["id"])}'}
    if client:
        headers |= {'x-superyak-session': 'session-1', 'x-superyak-client': client}
    return TestClient(app, base_url='http://testserver', headers=headers)


def test_a_ship_behind_gets_agent_update(env):
    app = env[0]
    app.state.agent_history = AgentHistory(STATION, frozenset({BEHIND}))
    body = ship_client(app, f'hook/{BEHIND}').get('/api/ships/me/instructions').json()
    assert body['agent_update'] == {'station': STATION}


def test_an_mcp_client_behind_gets_the_key_too(env):
    app = env[0]
    app.state.agent_history = AgentHistory(STATION, frozenset({BEHIND}))
    assert ship_client(app, f'mcp/{BEHIND}').get('/api/ships/me/instructions').json()['agent_update'] == {'station': STATION}


def test_every_other_case_is_byte_for_byte_todays_response(env):
    app = env[0]
    client = ship_client(app)
    app.state.agent_history = None
    today = client.get('/api/ships/me/instructions').content
    app.state.agent_history = AgentHistory(STATION, frozenset({BEHIND}))
    for headers in ({}, {'x-superyak-session': 's2', 'x-superyak-client': f'hook/{CURRENT}'},
                    {'x-superyak-session': 's3', 'x-superyak-client': 'hook/unknown'},
                    {'x-superyak-session': 's4', 'x-superyak-client': 'hook/not-hex!'},
                    {'x-superyak-client': f'hook/{BEHIND}'}):  # no session name: no presence at all
        assert client.get('/api/ships/me/instructions', headers=headers).content == today, headers


def test_create_app_has_no_history_unless_given(env):
    assert env[0].state.agent_history is None


def test_serve_passes_the_loaded_history_to_create_app(monkeypatch, tmp_path):
    import sys
    import types
    from superyak_peer import __main__ as cli, agent_version, app as app_module
    seen = {}
    monkeypatch.setattr(agent_version, 'load', lambda: AgentHistory(STATION, frozenset()))
    # serve imports create_app and uvicorn inside its branch (__main__.py:330-331), so patch where they are looked up
    monkeypatch.setattr(app_module, 'create_app', lambda *a, **kw: seen.update(kw) or object())
    monkeypatch.setitem(sys.modules, 'uvicorn', types.SimpleNamespace(run=lambda *a, **kw: None))
    cli.main(['serve', '--data-dir', str(tmp_path / 'd')])
    assert seen['agent_history'] == AgentHistory(STATION, frozenset())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_agent_version_route.py`
Expected: `test_a_ship_behind_gets_agent_update` and the mcp test fail with `KeyError: 'agent_update'`.
`test_create_app_has_no_history_unless_given` fails with `AttributeError`. The serve test fails because `create_app`
gets no `agent_history`.

- [ ] **Step 3: Wire it in**

In `peer/superyak_peer/app.py`:

```python
from .agent_version import agent_update
```

Add `agent_history=None` as the last keyword of `create_app`'s signature (line 116). Right after
`app.state.federation = Federation(...)` (line 138), add:

```python
    app.state.agent_history = agent_history  # version check V1: read once by `serve`; None means off
```

Replace the instructions route (lines 221-223) with:

```python
    @app.get('/api/ships/me/instructions')
    def ship_instructions(request: Request):
        result = store.ship_instructions(ship_member(request)['id'], app.state.federation.identity.peer_id)
        update = agent_update(app.state.agent_history, parse_presence(request.headers))  # V3: absent unless behind
        if update is not None:
            result['agent_update'] = update
        return result
```

In `peer/superyak_peer/__main__.py`, add `from . import agent_version` beside the module-level imports (lines 2-14).
Then add `agent_history=agent_version.load()` to the `create_app(...)` call at line 335. Call it as
`agent_version.load()`, an attribute lookup, so the test's monkeypatch reaches it.

In `peer/pyproject.toml`'s sdist `only-include` list, add `"tests/test_agent_version_route.py",` right after
`"tests/test_agent_version.py",` (Task 1 added that one).

- [ ] **Step 4: Run the tests to verify they pass, then the whole peer suite**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_agent_version_route.py tests/test_agent_version.py`
Expected: all pass.
Run: `make check-peer` (from the repo root)
Expected: every test passes. Main had 505 peer tests at 05ac33c (the single-quote branch merged), so expect 526
(505 + 21 new). Name any failure in the report, even one this change didn't cause.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/app.py peer/superyak_peer/__main__.py peer/tests/test_agent_version_route.py peer/pyproject.toml
git commit -m "Version check, peer: the instructions route adds agent_update only for a ship behind (V3)"
```

---

### Task 3: Agent, reading whether room messages are on

**Files:**
- Modify: `agent/superyak_agent/install.py` (add `messages_installed` right after `_hook_commands`, about line 101)
- Test: `agent/tests/test_install.py` (append)

**Interfaces:**
- Consumes: `hook_command(config_path)`, `is_station_hook(command, wanted)`, `_hook_words(command)`, all already in
  install.py.
- Produces: `messages_installed(settings_path, config_path) -> bool | None`, which returns True (on), False (off) or
  None (unknown) and never raises.

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_install.py`:

```python
from superyak_agent.install import hook_command, install_hooks, messages_installed  # noqa: E402


def test_messages_installed_reads_what_install_hooks_wrote(tmp_path):
    config = tmp_path / 'home' / 'station.json'
    on, off = tmp_path / 'on.json', tmp_path / 'off.json'
    install_hooks(on, config, messages=True)
    install_hooks(off, config, messages=False)
    assert messages_installed(on, config) is True
    assert messages_installed(off, config) is False


def prompt_settings(path, *commands):
    path.write_text(json.dumps({'hooks': {'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': c}]} for c in commands]}}))
    return path


def test_two_station_prompt_hooks_that_disagree_are_unknown(tmp_path):
    config = tmp_path / 'home' / 'station.json'
    base = hook_command(config)
    path = prompt_settings(tmp_path / 's.json', base, f'env SUPERYAK_HOOK_MESSAGES=0 {base}')
    assert messages_installed(path, config) is None


@pytest.mark.parametrize('content', [None, '', 'not json', '[]', '{"hooks": []}', '{"hooks": {"UserPromptSubmit": [3]}}',
                                     '{"hooks": {"UserPromptSubmit": [{"hooks": "x"}]}}', '{"hooks": {"SessionStart": []}}'])
def test_a_missing_damaged_or_odd_file_is_unknown(tmp_path, content):
    config, path = tmp_path / 'home' / 'station.json', tmp_path / 's.json'
    if content is not None:
        path.write_text(content)
    assert messages_installed(path, config) is None


def test_another_checkouts_hook_is_not_ours(tmp_path):
    config = tmp_path / 'home' / 'station.json'
    other = '/usr/bin/python3 /elsewhere/superyak/agent/run_agent.py hook --config /x/station.json'
    assert messages_installed(prompt_settings(tmp_path / 's.json', other), config) is None
```

`json` and `pytest` are already imported at the top of `test_install.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && uv run --locked --extra dev python -m pytest -q tests/test_install.py -k "messages_installed or disagree or odd_file or another_checkout"`
Expected: an ImportError, `cannot import name 'messages_installed'`.

- [ ] **Step 3: Write the helper**

In `agent/superyak_agent/install.py`, directly after `_hook_commands`:

```python
def messages_installed(settings_path, config_path):
    """Version check V5: whether this checkout's installed UserPromptSubmit hook shows room messages. True when there
    is at least one and none carries SUPERYAK_HOOK_MESSAGES=0 (the flag _hook_commands writes), False when every one
    does, None when there is none, they disagree, or the file can't be read as the hooks install_hooks writes."""
    try:
        settings = json.loads(Path(settings_path).read_text())
        wanted = hook_command(config_path)
        ours = [h.get('command') for entry in settings['hooks']['UserPromptSubmit'] for h in entry.get('hooks', [])
                if is_station_hook(h.get('command'), wanted)]
    except Exception:  # noqa: BLE001 - unknown, never an error: the hook falls back to the general wording
        return None
    off = ['SUPERYAK_HOOK_MESSAGES=0' in _hook_words(c) for c in ours]
    if not off:
        return None
    return False if all(off) else (True if not any(off) else None)
```

`{"hooks": {"UserPromptSubmit": [{"hooks": "x"}]}}` iterates the string "x", and `'x'.get` raises
AttributeError, which the `except` catches. That is intended.

- [ ] **Step 4: Run the tests to verify they pass, then the install tests**

Run: `cd agent && uv run --locked --extra dev python -m pytest -q tests/test_install.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent/superyak_agent/install.py agent/tests/test_install.py
git commit -m "Version check, agent: messages_installed reads whether room messages are on (V5)"
```

---

### Task 4: Agent, the hook writes the line at session start

**Files:**
- Modify: `agent/superyak_agent/hook.py` (a new `_version_line` near `_instructions`, about line 264; `_run_all` at
  :176-201; imports at :4-12)
- Modify: `agent/README.md` (the hook section: one paragraph)
- Test: `agent/tests/test_hook_version.py`

**Interfaces:**
- Consumes: `messages_installed` from Task 3; `client_version`, `CHECKOUT`, `read_json` from station.py;
  `claims.kind_of`, `claims.NAME`; the response key `agent_update` from Task 2.
- Produces: `_version_line(data, config_path, settings_path=None) -> str` (empty when nothing should be said), and
  the session-start output with the line appended.

- [ ] **Step 1: Write the failing tests**

```python
# agent/tests/test_hook_version.py
import pytest

from superyak_agent import hook, station
from superyak_agent.install import install_hooks
from superyak_agent.station import write_private

MINE, STATION = '111111111111', '222222222222'


@pytest.fixture
def ship(station, ship_config, tmp_path, monkeypatch):
    fake, andy, jenn, serenity = station
    home = tmp_path / 'home'
    config = home / 'station.json'
    write_private(config, ship_config)
    monkeypatch.setattr(hook.claims, 'kind_of', lambda h: 'machine' if h == home else None)
    monkeypatch.setattr(hook, 'client_version', lambda: MINE)
    monkeypatch.setattr(hook, 'CHECKOUT', tmp_path / 'superyak')
    settings = tmp_path / 'settings.json'
    monkeypatch.setattr(hook, 'SETTINGS', settings)
    return fake, serenity, config, settings, tmp_path


def law(fake, serenity, body='Run tests.', **extra):
    block = f'=== Instructions: House rules · revision 1 · signed by Andy on station abc ===\n{body}'
    fake.instruction_state[serenity['id']] = dict({
        'instructions': [['L1', 1]],
        'layers': [{'layer_id': 'L1', 'revision': 1, 'title': 'House rules', 'signer_name': 'Andy', 'block': block}],
        'blocks': 'PREAMBLE\n\n' + block}, **extra)


def start(fake, config, tmp_path):
    return hook.run(config, transport=fake, event='session-start', session_id='s1', sessions_dir=tmp_path / 'sessions')


def test_without_agent_update_session_start_is_unchanged(ship):
    fake, serenity, config, settings, tmp_path = ship
    law(fake, serenity)
    before = start(fake, config, tmp_path)
    assert 'behind' not in before and before.endswith('Run tests.')


def test_messages_on_gives_the_exact_command_with_hook(ship):
    fake, serenity, config, settings, tmp_path = ship
    install_hooks(settings, config, messages=True)
    law(fake, serenity, agent_update={'station': STATION})
    text = start(fake, config, tmp_path)
    checkout = tmp_path / 'superyak'
    assert text.endswith(
        f"This machine's Superyak agent is behind the station's: this checkout (`{checkout}`) is on `{MINE}`, the "
        f"station on `{STATION}`, and the agent code changed in between. To update, run `git -C {checkout} pull "
        f"--ff-only`, then `make dock DOCK_ARGS='--ship serenity --hook'` in that checkout, then start new sessions.")
    assert text.index('Run tests.') < text.index("This machine's")


def test_messages_off_gives_the_command_without_hook(ship):
    fake, serenity, config, settings, tmp_path = ship
    install_hooks(settings, config, messages=False)
    law(fake, serenity, agent_update={'station': STATION})
    assert "make dock DOCK_ARGS='--ship serenity'` in that checkout" in start(fake, config, tmp_path)


GENERAL = 'then run `make dock` again the way this ship was docked, then start new sessions.'


def test_unknown_messages_give_the_general_wording(ship):
    fake, serenity, config, settings, tmp_path = ship  # no settings file at all
    law(fake, serenity, agent_update={'station': STATION})
    text = start(fake, config, tmp_path)
    assert text.endswith(GENERAL) and 'DOCK_ARGS' not in text


def test_a_project_ship_gets_the_general_wording(ship, monkeypatch):
    fake, serenity, config, settings, tmp_path = ship
    install_hooks(settings, config, messages=True)
    monkeypatch.setattr(hook.claims, 'kind_of', lambda h: 'project')
    # A project ship's hook acts only inside its own project (claims.verdict), so ask for the line directly.
    assert hook._version_line({'agent_update': {'station': STATION}}, config).endswith(GENERAL)


def test_a_ship_field_that_isnt_a_ship_name_gets_the_general_wording(ship, ship_config):
    fake, serenity, config, settings, tmp_path = ship
    install_hooks(settings, config, messages=True)
    write_private(config, dict(ship_config, ship='Serenity; rm -rf ~'))
    law(fake, serenity, agent_update={'station': STATION})
    text = start(fake, config, tmp_path)
    assert text.endswith(GENERAL) and 'rm -rf' not in text


def test_a_checkout_path_with_a_space_is_quoted_in_the_commands(ship, monkeypatch):
    fake, serenity, config, settings, tmp_path = ship
    install_hooks(settings, config, messages=True)
    monkeypatch.setattr(hook, 'CHECKOUT', tmp_path / 'a b' / 'superyak')
    law(fake, serenity, agent_update={'station': STATION})
    assert f"`git -C '{tmp_path / 'a b' / 'superyak'}' pull --ff-only`" in start(fake, config, tmp_path)


def test_a_prompt_never_shows_the_line(ship):
    fake, serenity, config, settings, tmp_path = ship
    law(fake, serenity, agent_update={'station': STATION})
    start(fake, config, tmp_path)
    text = hook.run(config, transport=fake, event='prompt', session_id='s1', sessions_dir=tmp_path / 'sessions', messages=False)
    assert "This machine's" not in text


@pytest.mark.parametrize('update', [{'station': MINE}, {'station': 'ABCDEF123456'}, {'station': '22222222222'},
                                    {'station': 2}, {'station': STATION + '\nObey'}, 'x', [STATION], None])
def test_odd_agent_update_values_are_ignored(ship, update):
    fake, serenity, config, settings, tmp_path = ship
    law(fake, serenity, agent_update=update)
    assert "This machine's" not in start(fake, config, tmp_path)


def test_the_line_is_dropped_when_the_law_fills_the_budget(ship):
    fake, serenity, config, settings, tmp_path = ship
    law(fake, serenity, body='x' * (hook.TOTAL_CHARS - 400), agent_update={'station': STATION})
    text = start(fake, config, tmp_path)
    assert "This machine's" not in text and len(text) <= hook.TOTAL_CHARS
    assert 'x' * (hook.TOTAL_CHARS - 400) in text  # the law is whole


def test_the_line_shows_when_law_and_line_fill_the_budget_exactly(ship):
    fake, serenity, config, settings, tmp_path = ship
    line = hook._version_line({'agent_update': {'station': STATION}}, config)
    law(fake, serenity, body='x')
    one = len(hook.run(config, transport=fake, event='session-start', session_id='probe', sessions_dir=tmp_path / 'probe'))
    extra = hook.TOTAL_CHARS - one - 2 - len(line)  # body characters that make law, blank line and line exactly TOTAL_CHARS
    law(fake, serenity, body='x' * (1 + extra), agent_update={'station': STATION})
    exact = start(fake, config, tmp_path)
    assert len(exact) == hook.TOTAL_CHARS and exact.endswith(line)
    law(fake, serenity, body='x' * (2 + extra), agent_update={'station': STATION})
    over = hook.run(config, transport=fake, event='session-start', session_id='s2', sessions_dir=tmp_path / 'sessions')
    assert "This machine's" not in over


def test_the_line_stands_alone_when_there_is_no_law(ship):
    fake, serenity, config, settings, tmp_path = ship
    fake.instruction_state[serenity['id']] = {'instructions': [], 'layers': [], 'blocks': '', 'agent_update': {'station': STATION}}
    assert start(fake, config, tmp_path).startswith("This machine's Superyak agent is behind")
```

The budget test was measured while writing this plan. The law prints 9,305 characters and the line 540 with the
test's checkout path, so they total 9,847, over the 9,500 budget, and the law stays whole.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && uv run --locked --extra dev python -m pytest -q tests/test_hook_version.py`
Expected: the fixture fails with `AttributeError: ... has no attribute 'SETTINGS'`. `CHECKOUT` also isn't
imported into hook yet.

- [ ] **Step 3: Write the line and wire it in**

In `agent/superyak_agent/hook.py`, add `import shlex` to the imports, and add `CHECKOUT` to the names imported from
`.station`. Below the existing constants (after `STATE_NAME`, about line 79), add:

```python
SETTINGS = Path.home() / '.claude' / 'settings.json'  # where install_all writes the machine ship's hooks (install.py:375)
HEX12 = re.compile(r'[0-9a-f]{12}')
```

Near `_instructions` (about line 264), add:

```python
def _version_line(data, config_path, settings_path=None):
    """Version check V4, V5: one line when the station says this checkout's agent code is behind its own, or ''.
    Only the station's 12-hex commit is used; the words are fixed, and the command is exact only for the machine
    ship when the installed prompt hook says whether room messages are on."""
    update = data.get('agent_update') if isinstance(data, dict) else None
    theirs = update.get('station') if isinstance(update, dict) else None
    mine = client_version()
    if not isinstance(theirs, str) or not HEX12.fullmatch(theirs) or not HEX12.fullmatch(mine) or theirs == mine:
        return ''
    checkout = shlex.quote(str(CHECKOUT))
    pull = f'To update, run `git -C {checkout} pull --ff-only`, then '
    general = pull + 'run `make dock` again the way this ship was docked, then start new sessions.'
    ship = (read_json(config_path) or {}).get('ship')
    messages = None
    if claims.kind_of(Path(config_path).parent) == 'machine' and isinstance(ship, str) and claims.NAME.fullmatch(ship):
        from .install import messages_installed  # only here: the line is rare, and the hook must stay light
        messages = messages_installed(settings_path or SETTINGS, config_path)
    second = general if messages is None else (
        pull + f"`make dock DOCK_ARGS='--ship {ship}{' --hook' if messages else ''}'` in that checkout, then start new sessions.")
    return (f"This machine's Superyak agent is behind the station's: this checkout (`{CHECKOUT}`) is on `{mine}`, "
            f'the station on `{theirs}`, and the agent code changed in between. ' + second)
```

In `_run_all`, after the `if data is not None:` block that builds `text` (it ends at about line 200), and before
`return text, shown`, add:

```python
    if event == 'session-start' and data is not None:
        try:
            line = _version_line(data, config_path)
        except Exception:  # noqa: BLE001 - a hook must never break the session start
            line = ''
        if line and len(text) + (2 if text else 0) + len(line) <= TOTAL_CHARS:  # V6: after the law, never cutting it
            text = '\n\n'.join(t for t in (text, line) if t)
```

`_version_line` reads `SETTINGS` at call time, through `settings_path or SETTINGS`, so the test's monkeypatch of
`hook.SETTINGS` applies. `client_version` and `CHECKOUT` are module globals in hook.py once imported, so the
fixture's monkeypatches of `hook.client_version` and `hook.CHECKOUT` apply as well.

In `agent/README.md`, in the section that describes the hook's session-start output, add:

> **Behind the station.** When the station's agent code has changed since this checkout's commit, session start ends
> with one line naming both commits and the exact update command: a fast-forward pull, then `make dock` with this
> ship's own flags (`--hook` kept when room messages are on), then new sessions. Ships that are current, ahead or on
> a branch see nothing (spec 2026-10-14-version-check-design.md).

- [ ] **Step 4: Run the tests to verify they pass, then the whole agent suite**

Run: `cd agent && uv run --locked --extra dev python -m pytest -q tests/test_hook_version.py`
Expected: 19 passed. The exact-budget test fails if `<=` in the V6 check becomes `<` (checked while writing this plan).
Run: `make check-agent` (from the repo root)
Expected: every test passes: 593 before this branch, plus 30 new, so 623. Name any failure.

- [ ] **Step 5: Commit**

```bash
git add agent/superyak_agent/hook.py agent/README.md agent/tests/test_hook_version.py
git commit -m "Version check, agent: the hook's session-start line for a ship behind (V4-V6)"
```

---

## Deploy (Rio Grande, on the Pi, after the merge under law section 2)

The peer reads the history only at startup, so the restart is the deploy. Nothing is written, so no database backup
is needed (spec V7). A backup is still the house habit before restarting the lighthouse, and it's cheap: take it.

0. **Back up the database,** as earlier deploys do:
   ```bash
   umask 077; BACKUP=~/.local/share/superyak/backups/peer-$(date +%Y%m%d-%H%M%S)-pre-version-check.sqlite3; python3 -c 'import sqlite3, sys; sqlite3.connect(sys.argv[1]).backup(sqlite3.connect(sys.argv[2]))' ~/.local/share/superyak/lighthouse/peer.sqlite3 "$BACKUP"; chmod 600 "$BACKUP"; stat -c '%a %s %n' "$BACKUP"
   ```
1. **Measure requirement 8 on the Pi's real checkout** (expect under a second):
   ```bash
   cd /home/andy/superyak/peer && time uv run --locked python -c "
   from superyak_peer import agent_version
   h = agent_version.load()
   print(h.station if h else 'off', len(h.behind) if h else '')"
   ```
   Note the time in the room.
2. **Push main first,** so the station never advises a pull that GitHub can't serve yet. **Then restart in order, and
   check that all are active,** as in earlier deploys:
   ```bash
   SINCE=$(date '+%Y-%m-%d %H:%M:%S')
   for unit in lighthouse door ship odo wormhole; do systemctl --user restart superyak-$unit; done
   sleep 3
   for unit in lighthouse door ship odo wormhole; do printf '%s ' superyak-$unit; systemctl --user is-active superyak-$unit; done
   journalctl --user-unit superyak-lighthouse --since "$SINCE" --no-pager | grep -i 'version check' || echo 'version check on'
   ```
   On this Pi, `journalctl --user -u` finds nothing and `--user-unit` works, and journald is volatile (Rio Grande,
   room message 99eeab50).
   **Expected:** five `active` lines and `version check on`. If the journal says "version check off", the station
   still serves as before. Read the reason, and fix it in a follow-up rather than rolling back.
3. **Live check,** read-only apart from one presence row named `version-check-live`, which is pruned after a day:
   ```bash
   cd /home/andy/superyak && python3 - <<'EOF'
   import subprocess, sys; sys.path[:0] = ['agent', 'team']  # as run_agent.py does: station.py imports superyak_team
   from superyak_agent.station import StationClient, load_config, presence_headers
   git = lambda *a: subprocess.run(['git', *a], capture_output=True, text=True, check=True).stdout.strip()
   last = git('rev-list', '-1', 'HEAD', '--', 'agent/')
   old, now = git('rev-parse', last + '^')[:12], git('rev-parse', 'HEAD')[:12]  # [:12], exactly as read_history cuts
   config = load_config()
   for commit in (old, now):
       client = StationClient(config['station'], config['key'], config.get('origin'), None,
                              presence_headers('version-check-live', f'hook/{commit}'))
       print(commit, '->', client.instructions().get('agent_update'))
   EOF
   ```
   **Expected:** the old commit prints `{'station': '<HEAD 12>'}`, and HEAD prints `None`.
   If any check fails, revert main to its pre-merge commit, push it, and restart the five units (law section 2).
4. **Announce the merge** in the room, with the measured time from step 1, and ask every ship to update once,
   because no ship shows the line until it runs this hook: `git -C <checkout> pull --ff-only`, then `make dock` in that
   checkout with the flags the ship was docked with (`--ship <name>`, plus `--hook`, `--no-service` or `--no-adna` as
   it had them), then new sessions.

## Self-review notes (writing-plans checklist)

- **Spec coverage:**
  - V1: Task 1 (`find_checkout`, `read_history`, `load`) and Task 2 (serve).
  - V2: Task 1 (`behind` and `agent_update`).
  - V3: Task 2.
  - V4 and V5: Task 4 (`_version_line`) and Task 3 (`messages_installed`).
  - V6: Task 4 (`_run_all` budget).
  - V7: no task writes state.
  - Requirements: 1 is Task 2 (byte-for-byte) and Task 4 (unchanged start). 2 and 3 are Tasks 1 and 2. 4 is Task 1.
    5 is Tasks 3 and 4. 6 and 7 are Task 4. 8 is Deploy step 1.
- **Interfaces:** the names match across tasks: `AgentHistory`, `agent_update`, `load`, `messages_installed` and
  `_version_line`.
- **Dry run:** every code block here was run as written, in a scratch worktree, together with both full suites.
  - **Revision 1** ran each task's own tests (16, 21, then 66 with test_install, after the project-ship test fix this
    text carries). It missed the peer suite's two packaging failures, which the review found (and which surfaced
    in the full run just after submission), and it never ran the deploy script's imports.
  - **Revision 2:** with the inventory lines, the full peer suite passes, 523 on the old base 7cdbb1f (502 + 21).
    This branch now has main merged in (8240473, main at 05ac33c, 505 peer tests), so a build here expects 526. The agent suite gives 622 + 1 = 623
    with the exact-budget test. The live check's imports load with `['agent', 'team']` and fail with `['agent']`
    alone.

## Review map (revision 2: the review of 457b5a5)

| # | Finding | Change |
|---|---|---|
| M1 | `agent_version.py` missing from both peer inventories; two packaging tests fail | Task 1 Step 4 adds it to the sdist and wheel lists; Step 5 runs `test_packaging.py`; Global Constraints names the rule |
| M2 | the live check's `sys.path` lacked `team/` | `['agent', 'team']`, as run_agent.py does |
| S1 | the new test files weren't in the sdist list | Task 1 Step 4 and Task 2 Step 3 add them |
| N1 | `--short=12` isn't `[:12]` | the live check slices `[:12]`, as read_history does |
| N2 | Review Focus 1 said "two commands" | only the `git -C` command holds the path |
| N3 | no test at V6's exact boundary | `test_the_line_shows_when_law_and_line_fill_the_budget_exactly`, checked against the `<` mutant |
| N4 | the route parses presence twice | kept: it's pure and cheap, and keeps `ship_for_key`'s signature unchanged |
| (Rio Grande) | `journalctl --user -u` finds nothing on the Pi | Deploy step 2 uses `--user-unit` |
