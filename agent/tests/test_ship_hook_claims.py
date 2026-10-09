"""Many ships on one machine (D7), build step 4: the hook stands down in a project another ship claims and runs
everywhere else (R13, R14); a project ship's hook runs only in its own project; a partial match is a stale claim
(R15); an unreadable registry is loud (R16); the hook reads stdin once, for both the session and its cwd (R12)."""
import io
import os
from pathlib import Path
import shutil
import pytest
from superyak_agent import __main__ as cli, claims, hook
from superyak_agent.station import write_private
from ships_fakes import git, isolate_git, make_repo

SHIP = 'serenity-bricks'
LOUD = ("Superyak: ~/.superyak/projects.json can't be read, so the station hooks on this machine are off. "
        "Run `make dock` for your ship to see why.")


class Counting:
    def __init__(self, inner):
        self.inner, self.calls = inner, []

    def __call__(self, method, url, headers, data):
        self.calls.append(url)
        return self.inner(method, url, headers, data)


class Ships:
    """The machine ship (serenity) in ~/.superyak and a project ship (serenity-bricks) that claims a repository with a
    worktree and a subdirectory; a room with a message waiting for both."""
    def __init__(self, monkeypatch, tmp_path, station, ship_config):
        isolate_git(monkeypatch, tmp_path)
        fake, andy, jenn, serenity = station
        bricks = fake.user(SHIP, 'Serenity Bricks', 'ship', andy['id'], key='bricks-key')
        room = fake.room('Ops', andy, serenity, bricks)
        fake.say(room, andy, 'news for both ships')
        self.fake, self.andy, self.room = fake, andy, room
        self.repo = make_repo(tmp_path / 'hyper-bricks', worktree=tmp_path / 'hyper-bricks-wt')
        self.wt = Path(os.path.realpath(tmp_path / 'hyper-bricks-wt'))
        self.machine_config = claims.machine_home() / 'station.json'
        write_private(self.machine_config, ship_config)
        self.project_config = claims.project_home(SHIP) / 'station.json'
        write_private(self.project_config, ship_config | {'ship': SHIP, 'ship_name': 'Serenity Bricks', 'key': 'bricks-key'})
        claims.claim(SHIP, self.repo)
        self.elsewhere = make_repo(tmp_path / 'unclaimed')
        self.plain = tmp_path / 'plain'
        self.plain.mkdir()

    def run(self, config, monkeypatch, *, project_dir=None, cwd=None, event='prompt', session='s1'):
        if project_dir is None:
            monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
        else:
            monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(project_dir))
        transport = Counting(self.fake)
        text = hook.run(config, session_id=session, cwd=None if cwd is None else str(cwd), event=event, transport=transport)
        return text, transport.calls


@pytest.fixture
def ships(monkeypatch, tmp_path, station, ship_config):
    return Ships(monkeypatch, tmp_path, station, ship_config)


def sessions_files(config):
    folder = Path(config).parent / 'sessions'
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_machine_ship_hook_stands_down_in_a_claimed_project(ships, monkeypatch):
    """R13, R14: from the root, a subdirectory and a worktree, via CLAUDE_PROJECT_DIR and via stdin cwd when it's
    unset: nothing printed, no station call, no session file and no unreachable marker touched."""
    for where in (ships.repo, ships.repo / 'sub', ships.wt, ships.wt / 'sub'):
        for event in ('prompt', 'session-start'):
            assert ships.run(ships.machine_config, monkeypatch, project_dir=where, event=event) == ('', [])
            assert ships.run(ships.machine_config, monkeypatch, cwd=where, event=event) == ('', [])
    assert sessions_files(ships.machine_config) == []


def test_machine_ship_hook_runs_elsewhere(ships, monkeypatch):
    for where in (ships.elsewhere, ships.plain):
        ships.fake.say(ships.room, ships.andy, f'news for {where.name}')      # a new session starts at the furthest read
        text, calls = ships.run(ships.machine_config, monkeypatch, project_dir=where, session=f's-{where.name}')
        assert f'news for {where.name}' in text and calls


def test_project_ship_hook_runs_only_in_its_project(ships, monkeypatch, tmp_path):
    """Its project and its worktree; silent elsewhere, even with its settings copied there."""
    text, calls = ships.run(ships.project_config, monkeypatch, project_dir=ships.repo, session='p1')
    assert 'news for both ships' in text and calls
    ships.fake.say(ships.room, ships.andy, 'news for the worktree')
    text, calls = ships.run(ships.project_config, monkeypatch, project_dir=ships.wt / 'sub', session='p2')
    assert 'news for the worktree' in text
    copied = ships.elsewhere / '.claude'
    copied.mkdir()
    (copied / 'settings.local.json').write_text('{"hooks": {}}')
    for where in (ships.elsewhere, ships.plain, None):
        assert ships.run(ships.project_config, monkeypatch, project_dir=where, session='p3') == ('', [])


def test_a_project_ship_without_its_claim_in_the_registry_stays_quiet(ships, monkeypatch):
    """A project ship acts only when its claim.json is also, equal, in the registry."""
    write_private(claims.registry_path(), [])
    assert ships.run(ships.project_config, monkeypatch, project_dir=ships.repo) == ('', [])


@pytest.mark.parametrize('how', ['moved', 'recloned'])
def test_a_moved_or_recloned_repository_is_a_stale_claim(ships, monkeypatch, tmp_path, capsys, how):
    """R15: a moved repository (inode kept, path changed) and a re-clone at the same path (path kept, inode changed):
    both hooks print nothing, status names the claim, and a project re-dock refreshes it."""
    if how == 'moved':
        root = Path(os.path.realpath(tmp_path)) / 'moved-bricks'
        ships.repo.rename(root)
    else:
        root = ships.repo
        shutil.rmtree(root)
        make_repo(tmp_path / 'hyper-bricks')
    for config in (ships.machine_config, ships.project_config):
        assert ships.run(config, monkeypatch, project_dir=root) == ('', [])
    stale = claims.stale_claims(claims.read_registry())
    assert [entry['ship'] for entry, why in stale] == [SHIP]
    from superyak_agent import station as station_module
    monkeypatch.setattr(station_module, 'load_config', lambda path: (_ for _ in ()).throw(SystemExit('stop')))
    with pytest.raises(SystemExit):
        cli.main(['status', '--home', str(claims.machine_home())])
    out = capsys.readouterr().out
    assert f"{SHIP}'s claim on {ships.repo}" in out and 'stale' in out and f'dock {SHIP} again' in out
    claims.claim(SHIP, root)                    # what a project re-dock does with a stale claim of its own
    assert claims.stale_claims(claims.read_registry()) == []
    ships.fake.say(ships.room, ships.andy, 'after the refresh')
    text, _ = ships.run(ships.project_config, monkeypatch, project_dir=root, session='after')
    assert 'after the refresh' in text


@pytest.mark.parametrize('breakage', ['garbled', 'schema', 'missing-with-claim'])
def test_unreadable_registry_is_loud(ships, monkeypatch, breakage):
    """R16 (the hook's part): the fixed line at SessionStart, nothing at a prompt, no station call, from any ship and
    anywhere."""
    if breakage == 'garbled':
        claims.registry_path().write_text('{garbled')
    elif breakage == 'schema':
        claims.registry_path().write_text('[{"ship": 1}]')
    else:
        claims.registry_path().unlink()
    for config in (ships.machine_config, ships.project_config):
        for where in (ships.repo, ships.plain):
            assert ships.run(config, monkeypatch, project_dir=where, event='session-start') == (LOUD, [])
            assert ships.run(config, monkeypatch, project_dir=where, event='prompt') == ('', [])


def test_a_docked_ship_without_a_claim_keeps_the_hooks_on(monkeypatch, tmp_path, station, ship_config):
    """R16, Rio Grande's required edit 2: ships/<n>/station.json with no claim.json and no projects.json is no claim;
    the machine ship's hook acts as before, in the repository too."""
    isolate_git(monkeypatch, tmp_path)
    fake, andy, jenn, serenity = station
    fake.say(fake.room('Ops', andy, serenity), andy, 'still here')
    write_private(claims.machine_home() / 'station.json', ship_config)
    write_private(claims.project_home(SHIP) / 'station.json', ship_config | {'ship': SHIP, 'key': 'bricks-key'})
    repo = make_repo(tmp_path / 'hyper-bricks')
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(repo))
    assert 'still here' in hook.run(claims.machine_home() / 'station.json', session_id='s', transport=fake)


def test_the_hook_reads_stdin_once_for_the_session_and_its_cwd():
    """R12."""
    reads = []

    class Once(io.StringIO):
        def read(self, *a):
            reads.append(1)
            return super().read(*a)
    assert hook.hook_input(Once('{"session_id": "abc", "cwd": "/w/x", "prompt": "hi"}')) == ('abc', '/w/x')
    assert reads == [1]
    assert hook.hook_input(io.StringIO('not json')) == (None, None)
    assert hook.hook_input(io.StringIO('{"session_id": 5, "cwd": 7}')) == (None, None)
    assert hook.session_from_stdin(io.StringIO('{"session_id": "abc"}')) == 'abc'


def test_the_cli_hook_passes_stdin_cwd_to_the_stand_down(ships, monkeypatch, capsys):
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    monkeypatch.setattr('sys.stdin', io.StringIO('{"session_id": "s9", "cwd": "%s"}' % ships.repo))
    seen = []
    real = hook.run

    def spy(*a, **kw):
        seen.append(kw.get('cwd'))
        return real(*a, **kw | {'transport': ships.fake})
    monkeypatch.setattr(hook, 'run', spy)
    assert cli.main(['hook', '--config', str(ships.machine_config)]) == 0
    assert seen == [str(ships.repo)] and capsys.readouterr().out == ''


@pytest.mark.parametrize('project', [False, True])
def test_dock_refuses_an_unreadable_registry_and_names_it(ships, monkeypatch, capsys, project):
    """R16 (dock's part): a machine dock and a project dock both refuse before the network, naming the file."""
    from superyak_agent import dock as dock_module
    made = []
    monkeypatch.setattr(dock_module, 'Dock', lambda *a, **kw: made.append(1))
    claims.registry_path().write_text('{garbled')
    args = ['dock', '--station', 'http://station.test', '--ship', SHIP if project else 'serenity']
    if project:
        args += ['--project', str(ships.repo)]
    assert cli.main(args) == 2
    assert str(claims.registry_path()) in capsys.readouterr().err and made == []
