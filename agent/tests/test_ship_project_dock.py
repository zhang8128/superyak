"""Many ships on one machine (D7), build step 3: a project dock's checks before the request, before each poll and
inside the claim's lock hold, all writing nothing (R3, R4, R9); hardened git from the root (R5); the backup in the
home (R6); local tools from the root and the machine's from ~/.superyak (R7); the reservation, rollback and cleanup
messages (R9); the machine ship's checkout (R10); the Codex profile (R20); what dock prints (R23)."""
import json
import os
from pathlib import Path
import subprocess
import pytest
from superyak_agent import __main__ as cli, claims, install, project_dock
from superyak_agent.station import read_json, write_private
from superyak_team.workers import HARDENED_GIT
from superyak_agent.dock import Dock as RealDock
from ships_fakes import FakeMachine, PYTHON, RUN_AGENT, git, hook_commands, isolate_git, make_repo

SHIP = 'serenity-bricks'


class DockedAtOnce:
    """Stands in for dock.Dock: the station approves at once. Records the check it was given (R9)."""
    made = []

    def __init__(self, station, door=None, ship=None, workspace=None, home=None, check=None, **kwargs):
        self.home, self.ship, self.workspace, self.check = Path(home), ship, workspace, check
        DockedAtOnce.made.append(self)

    def run(self, fields=None, wait=540):
        write_private(self.home / 'station.json', {'station': 'http://station.test', 'key': f'key-{self.ship}', 'ship': self.ship,
                                                   'ship_name': self.ship.replace('-', ' ').title(), 'workspace': self.workspace})
        return 0


class World:
    def __init__(self, monkeypatch, tmp_path, capsys, system='Linux', fail=()):
        isolate_git(monkeypatch, tmp_path)
        self.monkeypatch, self.capsys = monkeypatch, capsys
        self.machine = FakeMachine(monkeypatch, tmp_path, system=system, fail=fail)
        self.repo = make_repo(tmp_path / 'hyper-bricks', worktree=tmp_path / 'hyper-bricks-wt')
        self.home = claims.project_home(SHIP)
        # the machine ship, docked from this checkout as today
        config = self.machine.dock_machine()
        write_private(config.parent / 'ship-state.json', {'mention_seq': 0})
        install.install_all(config, hook=True, adna=False, service=False, out=self.machine.out.append)
        self.machine.calls.clear()
        self.machine.git_calls.clear()
        from superyak_agent import dock as dock_module
        DockedAtOnce.made = []
        monkeypatch.setattr(dock_module, 'Dock', DockedAtOnce)

    def dock(self, *extra, project=None):
        code = cli.main(['dock', '--station', 'http://station.test', '--ship', SHIP, '--project', str(project or self.repo),
                         '--hook', '--no-service', *extra])
        out = self.capsys.readouterr()
        return code, out.out + out.err

    def porcelain(self):
        return git('status', '--porcelain', '--untracked-files=all', cwd=self.repo)

    def exclude(self):
        path = self.repo / '.git' / 'info' / 'exclude'
        return path.read_bytes() if path.exists() else None

    def registry(self):
        return claims.read_registry()


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    return World(monkeypatch, tmp_path, capsys)


def test_a_project_dock_wires_the_project_and_says_so(world):
    """S5, R23: the claim, the excludes, a local station from the root, hooks in settings.local.json, the Codex
    profile; and what dock prints."""
    code, out = world.dock()
    assert code == 0, out
    (made,) = DockedAtOnce.made
    assert made.home == world.home and made.workspace == str(world.repo) and made.check is not None
    entry = claims.claim_entry(SHIP, world.repo)
    assert world.registry() == [entry] and read_json(world.home / 'claim.json') == entry
    config = world.home / 'station.json'
    assert world.machine.local_station == {str(world.repo): [PYTHON, RUN_AGENT, 'mcp', '--config', str(config)]}
    assert world.machine.user_station[-1] == str(world.machine.config)        # the machine ship's is untouched
    settings = world.repo / '.claude' / 'settings.local.json'
    base = f'{PYTHON} {RUN_AGENT} hook --config {config}'
    assert hook_commands(settings, 'UserPromptSubmit') == [f'{base} || true']
    assert len(hook_commands(settings, 'SessionStart')) == 1 and str(config) in hook_commands(settings, 'SessionStart')[0]
    profile = world.machine.home / '.codex' / f'{SHIP}.config.toml'
    assert profile.read_text() == (f'[mcp_servers.station]\ncommand = "{PYTHON}"\n'
                                   f'args = ["{RUN_AGENT}", "mcp", "--config", "{config}"]\n')
    assert world.porcelain() == ''
    for line in (f'Home: {world.home}', f'Project: {world.repo}', f'act as {SHIP}', f'codex -p {SHIP}'):
        assert line in out, line


def test_dock_writes_nothing_tracked(world):
    """R4, R6, R11: an existing settings.local.json is backed up into the ship's home, never beside it; afterwards git
    status is empty, and two docks leave each exclude line once."""
    settings = world.repo / '.claude' / 'settings.local.json'
    settings.parent.mkdir()
    settings.write_text('{"env": {"TOKEN": "secret"}, "permissions": {"allow": ["Bash(ls)"]}}\n')
    original = settings.read_text()
    assert world.dock()[0] == 0
    assert world.porcelain() == ''
    assert (world.home / 'settings.local.json.bak-superyak').read_text() == original
    assert not list(settings.parent.glob('*bak*')) and not list(settings.parent.glob('.settings.local.json.*'))
    assert json.loads(settings.read_text())['env'] == {'TOKEN': 'secret'}
    assert world.dock()[0] == 0
    lines = world.exclude().decode().splitlines()
    assert lines.count('/.claude/settings.local.json') == 1 and lines.count('/.claude/.settings.local.json.*') == 1
    assert world.porcelain() == ''


@pytest.mark.parametrize('setup, why', [
    ('tracked', 'is tracked'),
    ('negation', 'not ignored'),
    ('symlink', 'symlink'),
    ('not-a-repo', 'no repository'),
    ('claimed', 'claimed by'),
    ('claimed-partially', 'claimed by'),
])
def test_refused_project_never_reaches_the_station(world, tmp_path, setup, why):
    """R3, R4: a folder that is no repository, a root another ship claims (fully or partially), a tracked file, a
    negation rule and a symlinked .claude each fail before any docking request, writing nothing anywhere."""
    project = world.repo
    if setup == 'tracked':
        (world.repo / '.claude').mkdir()
        (world.repo / '.claude' / 'settings.local.json').write_text('{}')
        git('add', '-f', '.claude/settings.local.json', cwd=world.repo)
        git('commit', '-q', '-m', 'track it', cwd=world.repo)
    elif setup == 'negation':
        (world.repo / '.gitignore').write_text('!.claude/settings.local.json\n')
        git('add', '.gitignore', cwd=world.repo)
        git('commit', '-q', '-m', 'negate', cwd=world.repo)
    elif setup == 'symlink':
        elsewhere = tmp_path / 'elsewhere'
        elsewhere.mkdir()
        (world.repo / '.claude').symlink_to(elsewhere)
    elif setup == 'not-a-repo':
        project = tmp_path / 'plain'
        project.mkdir()
    else:
        st = os.stat(world.repo)
        other = {'ship': 'odo', 'home': str(claims.project_home('odo')), 'root': str(world.repo), 'dev': st.st_dev,
                 'ino': st.st_ino if setup == 'claimed' else st.st_ino + 1}
        write_private(claims.registry_path(), [other])
        write_private(claims.project_home('odo') / 'claim.json', other)
    before_status, before_exclude = world.porcelain(), world.exclude()
    before_home = sorted(str(p) for p in world.machine.home.rglob('*'))
    code, out = world.dock(project=project)
    assert code == 2 and why in out, out
    assert DockedAtOnce.made == []
    assert world.porcelain() == before_status and world.exclude() == before_exclude
    assert sorted(str(p) for p in world.machine.home.rglob('*')) == before_home
    assert world.machine.local_station == {}


def test_dock_git_is_hardened(world, monkeypatch):
    """R5: every git call dock makes in the repository is `git --git-dir <common> --work-tree <root>` with every
    HARDENED_GIT option and the isolated environment, run from the root, even when dock runs from a subdirectory; a
    repository fsmonitor never runs; from a subdirectory a tracked file is refused as tracked."""
    marker = world.repo.parent / 'fsmonitor-ran'
    git('config', 'core.fsmonitor', f'touch {marker}; false', cwd=world.repo)
    monkeypatch.chdir(world.repo / 'sub')
    assert world.dock(project=world.repo / 'sub')[0] == 0
    assert world.machine.git_calls, 'dock ran no git'
    for argv, cwd, env in world.machine.git_calls:
        assert argv[:5] == ['git', '--git-dir', str(world.repo / '.git'), '--work-tree', str(world.repo)], argv
        assert argv[5:5 + len(HARDENED_GIT)] == HARDENED_GIT, argv
        assert cwd == str(world.repo) and env.get('GIT_CONFIG_GLOBAL') == os.devnull and env.get('GIT_CONFIG_NOSYSTEM') == '1'
    assert not marker.exists()
    claims.unclaim(world.home)
    (world.home / 'station.json').unlink()
    git('add', '-f', '.claude/settings.local.json', cwd=world.repo)
    git('-c', 'core.fsmonitor=false', 'commit', '-q', '-m', 'track', cwd=world.repo)
    code, out = world.dock(project=world.repo / 'sub')
    assert code == 2 and 'is tracked' in out, out


class Lock:
    def __init__(self):
        self.held, self.holds, self.events = False, 0, []

    def __call__(self):
        lock = self

        class Hold:
            def __enter__(self):
                lock.held, lock.holds = True, lock.holds + 1

            def __exit__(self, *exc):
                lock.held = False
        return Hold()


@pytest.mark.parametrize('failing', ['exclude-check', 'local-tools', 'hooks', 'codex', 'service'])
def test_claim_first_and_rollback(monkeypatch, tmp_path, capsys, failing):
    """R9: the last checks and the claim happen in one hold of the lock, and a failure at any later write leaves no
    claim and none of this run's files (exclude lines only if this run added them)."""
    fail = [('claude', 'mcp', 'add')] if failing == 'local-tools' else [('systemctl', '--user', 'restart')] if failing == 'service' else []
    w = World(monkeypatch, tmp_path, capsys, fail=())
    w.machine.fail = fail
    lock = Lock()
    monkeypatch.setattr(claims, 'registry_lock', lock)
    real_checks = project_dock.ProjectDock.checks

    def checks(self):
        lock.events.append(('checks', lock.held, lock.holds))
        return real_checks(self)
    monkeypatch.setattr(project_dock.ProjectDock, 'checks', checks)
    real_claim = claims.claim

    def claim(*a, **kw):
        lock.events.append(('claim', lock.held, lock.holds))
        return real_claim(*a, **kw)
    monkeypatch.setattr(claims, 'claim', claim)
    if failing == 'exclude-check':
        def refuse(repo):
            raise claims.Refused('the real check-ignore says .claude/settings.local.json is not ignored')
        monkeypatch.setattr(project_dock, 'real_exclude_check', refuse)
    if failing == 'hooks':
        def broken(*a, **kw):
            raise OSError('disk full')
        monkeypatch.setattr(install, 'install_hooks', broken)
    if failing == 'codex':
        def broken_codex(*a, **kw):
            raise OSError('read-only file system')
        monkeypatch.setattr(project_dock, 'write_codex_profile', broken_codex)
    extra = ()
    if failing == 'service':
        write_private(w.home / 'ship-state.json', {'mention_seq': 0})
        extra = ()
    before_exclude = w.exclude()
    args = ['dock', '--station', 'http://station.test', '--ship', SHIP, '--project', str(w.repo), '--hook']
    if failing != 'service':
        args.append('--no-service')
    code = cli.main(args)
    out = capsys.readouterr()
    text = out.out + out.err
    assert code == 2, text
    last_checks = [e for e in lock.events if e[0] == 'checks'][-1]
    claimed = [e for e in lock.events if e[0] == 'claim']
    assert claimed and last_checks[1] is True and claimed[-1] == ('claim', True, last_checks[2])
    assert w.registry() == [] and not (w.home / 'claim.json').exists()
    assert w.exclude() == before_exclude
    assert not (w.repo / '.claude' / 'settings.local.json').exists()
    assert w.machine.local_station == {}
    assert not (w.machine.home / '.codex' / f'{SHIP}.config.toml').exists()
    assert not (w.machine.home / '.config' / 'systemd' / 'user' / f'superyak-ship-{SHIP}.service').exists()
    assert (w.home / 'station.json').exists()          # kept for a retry
    assert 'rolled back' in text and f'undock --home {w.home}' in text
    assert w.porcelain() == ''


def test_a_rollback_keeps_exclude_lines_this_run_did_not_add(world, monkeypatch):
    git_dir = world.repo / '.git' / 'info'
    git_dir.mkdir(exist_ok=True)
    (git_dir / 'exclude').write_text('# mine\n/.claude/settings.local.json\n/.claude/.settings.local.json.*\n')
    before = world.exclude()

    def broken(*a, **kw):
        raise OSError('disk full')
    monkeypatch.setattr(install, 'install_hooks', broken)
    assert world.dock()[0] == 2
    assert world.exclude() == before


class DockingStation:
    """The station's docking endpoints: a docking stays pending until `approve` is set."""
    def __init__(self):
        self.approve, self.posts = False, 0

    def __call__(self, method, url, headers, data):
        if url.endswith('/api/dockings') and method == 'POST':
            self.posts += 1
            return 201, json.dumps({'id': 'd1a2b3c4', 'code': 'ABCD2345', 'secret': 's', 'expires': 600.0,
                                    'confirm_url': 'http://station.test/#dock?code=ABCD2345'}).encode()
        if '/api/dockings/d1a2b3c4' in url:
            if self.approve:
                return 200, json.dumps({'status': 'confirmed', 'key': 'key-sb', 'ship': {
                    'id': 'u-sb', 'username': SHIP, 'name': 'Serenity Bricks', 'owner_id': 'u-andy'}}).encode()
            return 200, b'{"status": "waiting"}'
        return 401, b'{"error": "Sign in"}'


def test_a_claim_lost_to_a_race_names_the_orphan_ship(monkeypatch, tmp_path, capsys):
    """R9: a check that starts failing while the docking is pending stops dock before its next poll; one that fails
    inside the lock after docking writes no claim. Each message names the check, the ship and its cleanup, and
    station.json stays for a retry."""
    w = World(monkeypatch, tmp_path, capsys)
    from superyak_agent import dock as dock_module
    station, between_polls = DockingStation(), []

    def factory(*args, **kwargs):
        return RealDock(*args, transport=station, sleep=lambda s: [f() for f in between_polls], open_url=lambda url: None,
                        machine='mac', **kwargs)
    monkeypatch.setattr(dock_module, 'Dock', factory)

    def track_the_file():
        (w.repo / '.claude').mkdir(exist_ok=True)
        (w.repo / '.claude' / 'settings.local.json').write_text('{}')
        git('add', '-f', '.claude/settings.local.json', cwd=w.repo)
        git('commit', '-q', '-m', 'someone tracked it', cwd=w.repo)
        between_polls.clear()
    between_polls.append(track_the_file)
    code, out = w.dock('--wait', '60')
    assert code == 2 and station.posts == 1, out
    assert 'is tracked' in out and SHIP in out and str(w.home / 'docking.json') in out
    assert 'make station-deny ID=d1a2b3' in out and '10 minutes' in out
    assert not (w.home / 'station.json').exists() and w.registry() == []

    # the person cleans up as told; this time the station approves, and another ship claims the root just as dock
    # takes the lock
    git('rm', '-q', '--cached', '.claude/settings.local.json', cwd=w.repo)
    git('commit', '-q', '-m', 'untrack', cwd=w.repo)
    (w.repo / '.claude' / 'settings.local.json').unlink()
    (w.home / 'docking.json').unlink()
    station.approve = True
    real_lock = claims.registry_lock

    class Raced:
        def __enter__(self):
            self.hold = real_lock()
            self.hold.__enter__()
            other = claims.claim_entry('odo', w.repo) | {'home': str(claims.project_home('odo'))}
            write_private(claims.registry_path(), [other])
            write_private(claims.project_home('odo') / 'claim.json', other)

        def __exit__(self, *exc):
            return self.hold.__exit__(*exc)
    monkeypatch.setattr(claims, 'registry_lock', Raced)
    code, out = w.dock('--wait', '60')
    assert code == 2, out
    assert "claimed by 'odo'" in out and SHIP in out and f'undock --home {w.home}' in out
    assert 'kept' in out and (w.home / 'station.json').exists()
    assert [e['ship'] for e in w.registry()] == ['odo'] and not (w.home / 'claim.json').exists()


def test_a_docked_ship_without_a_claim_keeps_the_first_project_dock_working(world):
    """R16 (dock's part): a project home with only station.json and no projects.json is no claim, so the first
    project dock's own checks under the lock pass."""
    write_private(world.home / 'station.json', {'station': 'http://station.test', 'key': 'key-sb', 'ship': SHIP,
                                                'ship_name': 'Serenity Bricks'})
    assert not claims.registry_path().exists()
    assert world.dock()[0] == 0 and world.registry() == [claims.claim_entry(SHIP, world.repo)]


def test_local_station_registration_checks_scope(world, monkeypatch):
    """R7: dock ignores the user station, replaces a stale local one, and refuses (rolling back) when the confirmation
    shows the wrong scope or the wrong args."""
    world.machine.local_station[str(world.repo)] = [PYTHON, RUN_AGENT, 'mcp', '--config', '/stale/station.json']
    assert world.dock()[0] == 0
    assert world.machine.local_station[str(world.repo)][-1] == str(world.home / 'station.json')
    removes = [cwd for argv, cwd in world.machine.calls if argv[:5] == ['claude', 'mcp', 'remove', '--scope', 'local']]
    assert removes == [str(world.repo)]
    claims.unclaim(world.home)
    real = world.machine._claude_mcp

    def wrong_scope(args, cwd):
        result = real(args, cwd)
        if args[:1] == ['get']:
            return subprocess.CompletedProcess(args, 0, stdout=result.stdout.replace('Local config', 'User config'))
        return result
    monkeypatch.setattr(world.machine, '_claude_mcp', wrong_scope)
    code, out = world.dock()
    assert code == 2 and 'scope' in out and world.registry() == [], out


def test_machine_registration_runs_outside_claims(monkeypatch, tmp_path, capsys):
    """R7: the machine ship's `claude mcp` calls run in ~/.superyak, even when dock runs inside a claimed project."""
    w = World(monkeypatch, tmp_path, capsys)
    assert w.dock()[0] == 0
    w.machine.calls.clear()
    w.machine.user_station = None
    monkeypatch.chdir(w.repo / 'sub')
    install.install_all(w.machine.config, hook=True, adna=False, service=False, out=w.machine.out.append)
    mcp_calls = [(argv, cwd) for argv, cwd in w.machine.calls if argv[:2] == ['claude', 'mcp']]
    assert mcp_calls and all(cwd == str(w.machine.home / '.superyak') for argv, cwd in mcp_calls)
    assert w.machine.user_station[-1] == str(w.machine.config)


@pytest.mark.parametrize('where', ['hook', 'user-station', 'codex'])
def test_project_dock_checks_the_machine_ship_checkout(world, where):
    """R10: a machine hook, a user station or a Codex station table that runs another checkout's run_agent.py is
    refused; the message names both checkouts, lists the foreign entries and gives both fixes, never "dock the
    machine ship again" alone. After the entries go and the machine ship docks again here, the project dock passes."""
    other = '/other/checkout/agent/run_agent.py'
    settings = world.machine.home / '.claude' / 'settings.json'
    codex = world.machine.home / '.codex' / 'config.toml'
    if where == 'hook':
        data = json.loads(settings.read_text())
        data['hooks']['UserPromptSubmit'].append({'hooks': [{'type': 'command', 'command': f'{PYTHON} {other} hook --config /x || true'}]})
        settings.write_text(json.dumps(data))
    elif where == 'user-station':
        world.machine.user_station = [PYTHON, other, 'mcp', '--config', str(world.machine.config)]
    else:
        codex.write_text(codex.read_text().replace(RUN_AGENT, other))
    code, out = world.dock()
    assert code == 2 and DockedAtOnce.made == [], out
    assert other in out and RUN_AGENT in out
    assert '/other/checkout' in out and str(install.AGENT_DIR.parent) in out
    assert 'remove' in out and 'from the other checkout' in out
    # the fix: remove the foreign entries, then dock the machine ship again from this checkout
    if where == 'hook':
        install.remove_hooks(settings)
        data = json.loads(settings.read_text()) if settings.exists() else {}
        data.get('hooks', {}).pop('UserPromptSubmit', None)
        settings.write_text(json.dumps(data))
    elif where == 'user-station':
        world.machine.user_station = None
    else:
        install.remove_codex(codex, 'station')
    install.install_all(world.machine.config, hook=True, adna=False, service=False, out=world.machine.out.append)
    assert world.dock()[0] == 0


def test_codex_profile_is_never_overwritten(world):
    """R20 (dock's part): a profile file keeps its other tables and gets only a station table; a station table for
    another home is refused."""
    profile = world.machine.home / '.codex' / f'{SHIP}.config.toml'
    profile.parent.mkdir(exist_ok=True)
    profile.write_text('model = "m"\n\n[mcp_servers.other]\ncommand = "o"\n')
    assert world.dock()[0] == 0
    text = profile.read_text()
    assert text.startswith('model = "m"\n\n[mcp_servers.other]\ncommand = "o"\n') and '[mcp_servers.station]' in text
    claims.unclaim(world.home)
    profile.write_text('[mcp_servers.station]\ncommand = "p"\nargs = ["x", "mcp", "--config", "/some/other/home/station.json"]\n')
    code, out = world.dock()
    assert code == 2 and 'another home' in out and world.registry() == [], out
    assert profile.read_text().endswith('"/some/other/home/station.json"]\n')
