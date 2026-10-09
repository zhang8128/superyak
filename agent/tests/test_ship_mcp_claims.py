"""Many ships on one machine (D7), build step 5: the station MCP server follows the claims on every call and sends
no instructions when it would refuse (S7, R18); it refuses everything inside teamd workers and watcher runs; and every
settings file claude_sandbox_settings builds denies the station tools and reads of ~/.superyak (S8, S11, R19)."""
import fnmatch
import os
from pathlib import Path
import shutil
import pytest
from superyak_agent import claims, mcp, runs
from superyak_agent.mcp import Tools, handle
from superyak_agent.station import StationClient, write_private
from superyak_team import workers
from ships_fakes import make_repo
from test_ship_hook_claims import SHIP, Ships


@pytest.fixture
def ships(monkeypatch, tmp_path, station, ship_config):
    world = Ships(monkeypatch, tmp_path, station, ship_config)
    fake, andy, jenn, serenity = station
    fake.blocks[serenity['id']] = 'Serenity law.'
    fake.blocks['u-' + SHIP] = 'Bricks law.'
    return world


def tools(ships, config, key):
    client = StationClient('http://station.test', key, transport=ships.fake)
    return Tools(client, quick_client=client, guard=mcp.claim_guard(config))


def call(t, name='station_rooms', **arguments):
    result = handle(t, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}})['result']
    return result['content'][0]['text'], result['isError']


def initialize(t):
    params = {'protocolVersion': '2025-06-18', 'clientInfo': {'name': 'codex-mcp-client'}}
    return handle(t, {'id': 1, 'method': 'initialize', 'params': params})['result']


def test_mcp_server_follows_the_claims(ships, monkeypatch):
    """R18: the machine server refuses inside a claim with the codex -p hint; the project server refuses outside its own
    claim; neither sends instructions at initialize then; a claim added between two calls applies to the second."""
    machine, project = tools(ships, ships.machine_config, 'serenity-key'), tools(ships, ships.project_config, 'bricks-key')
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(ships.wt / 'sub'))
    text, error = call(machine)
    assert error and f'which {SHIP} claims' in text and f'codex -p {SHIP}' in text and str(ships.repo) in text
    assert 'instructions' not in initialize(machine)
    text, error = call(project)
    assert not error and 'Ops' in text and initialize(project)['instructions'] == 'Bricks law.'
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(ships.plain))
    assert not call(machine)[1] and initialize(machine)['instructions'] == 'Serenity law.'
    text, error = call(project)
    assert error and f'{SHIP} acts only in {ships.repo}' in text
    assert 'instructions' not in initialize(project)
    # a claim added between two calls applies to the second
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(ships.elsewhere))
    assert not call(machine)[1]
    other = claims.claim_entry('odo', ships.elsewhere) | {'home': str(claims.project_home('odo'))}
    write_private(claims.registry_path(), claims.read_registry() + [other])
    write_private(claims.project_home('odo') / 'claim.json', other)
    text, error = call(machine)
    assert error and 'which odo claims' in text


def test_without_claude_project_dir_the_server_uses_its_own_cwd(ships, monkeypatch):
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    monkeypatch.chdir(ships.repo / 'sub')                 # where Claude Code and Codex start the server (M8)
    assert call(tools(ships, ships.machine_config, 'serenity-key'))[1] is True
    assert call(tools(ships, ships.project_config, 'bricks-key'))[1] is False


@pytest.mark.parametrize('value, refused', [('1', True), ('anything', True), ('', False), ('hook', False), (None, False)])
def test_station_tools_refuse_inside_runs(ships, monkeypatch, value, refused):
    """R18, S7 rule 1: SUPERYAK_RUN (teamd sets 1 for every worker) refuses every call, whatever allow rule the
    session's settings.local.json holds, since the refusal is in the server itself."""
    (ships.repo / '.claude').mkdir(exist_ok=True)
    (ships.repo / '.claude' / 'settings.local.json').write_text('{"permissions": {"allow": ["mcp__station__station_post"]}}')
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(ships.repo))
    if value is None:
        monkeypatch.delenv('SUPERYAK_RUN', raising=False)
    else:
        monkeypatch.setenv('SUPERYAK_RUN', value)
    text, error = call(tools(ships, ships.project_config, 'bricks-key'), 'station_post', room=ships.room, text='hi')
    assert error is refused
    if refused:
        assert 'SUPERYAK_RUN' in text and not any(m['body'] == 'hi' for m in ships.fake.rooms[ships.room]['messages'])
        assert 'instructions' not in initialize(tools(ships, ships.project_config, 'bricks-key'))


def test_mcp_refuses_everywhere_while_the_registry_is_unreadable(ships, monkeypatch):
    """R16 (the server's part): every call refuses, naming the file, from either ship, anywhere."""
    claims.registry_path().write_text('{garbled')
    for config, key in ((ships.machine_config, 'serenity-key'), (ships.project_config, 'bricks-key')):
        for where in (ships.repo, ships.plain):
            monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(where))
            text, error = call(tools(ships, config, key))
            assert error and str(claims.registry_path()) in text


@pytest.mark.parametrize('how', ['moved', 'recloned'])
def test_both_servers_refuse_at_a_stale_claim(ships, monkeypatch, tmp_path, how):
    """R15 (the servers' part): both refuse there, naming the claim and how to refresh it."""
    if how == 'moved':
        root = Path(os.path.realpath(tmp_path)) / 'moved-bricks'
        ships.repo.rename(root)
    else:
        root = ships.repo
        # The old checkout is renamed to a sibling, not deleted, so its inode number stays taken: ext4 reuses a deleted
        # folder's number (20 of 20 tries on the Pi), and a re-clone would then match fully (Known limits).
        root.rename(root.parent / 'hyper-bricks-old')
        make_repo(tmp_path / 'hyper-bricks')
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(root))
    for config, key in ((ships.machine_config, 'serenity-key'), (ships.project_config, 'bricks-key')):
        text, error = call(tools(ships, config, key))
        assert error and 'stale' in text and f'Dock {SHIP} again' in text


def test_a_docked_ship_without_a_claim_keeps_the_machine_server_on(monkeypatch, tmp_path, station, ship_config):
    """R16, Rio Grande's required edit 2 (the server's part)."""
    fake, andy, jenn, serenity = station
    fake.room('Ops', andy, serenity)
    write_private(claims.machine_home() / 'station.json', ship_config)
    write_private(claims.project_home(SHIP) / 'station.json', ship_config | {'ship': SHIP, 'key': 'bricks-key'})
    repo = make_repo(tmp_path / 'hyper-bricks')
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(repo))
    client = StationClient('http://station.test', 'serenity-key', transport=fake)
    text, error = call(Tools(client, quick_client=client, guard=mcp.claim_guard(claims.machine_home() / 'station.json')))
    assert not error and 'Ops' in text


def _covers(rule, path):
    """Whether a Read/Grep/Edit/Glob permission rule with a path covers `path` (a `//` rule is absolute)."""
    if '(' not in rule or not rule.split('(', 1)[0] in ('Read', 'Grep', 'Edit', 'Glob'):
        return False
    pattern = rule[rule.index('(') + 1:-1]
    pattern = pattern[1:] if pattern.startswith('//') else pattern
    return fnmatch.fnmatchcase(path, pattern)


def _all_settings(build_wt, workspace, read_dir, room):
    return {'teamd builder': (workers.claude_sandbox_settings(str(build_wt), mode='build', repo=str(workspace)), build_wt),
            'teamd collab': (workers.claude_sandbox_settings(str(room), mode='collab'), room),
            'builder run': (runs.builder_settings(build_wt, workspace), build_wt),
            'read run': (runs.read_only_settings(read_dir), read_dir)}


def test_workers_deny_the_station_and_the_keys(tmp_path):
    """R19 (narrowed, review 487c070b): every kind of settings denies the station tools, and Read and Grep of what
    holds keys: ~/.superyak/station.json, docking.json, access-request.json, invitation.txt, ships/** and the settings
    backups outside ships/. `//` rules are absolute."""
    home = str(Path.home())
    keys = [f'{home}/.superyak/{name}' for name in ('station.json', 'docking.json', 'access-request.json', 'invitation.txt')]
    keys += [f'{home}/.superyak/ships/serenity-bricks/station.json', f'{home}/.superyak/ships/serenity-bricks/claim.json',
             f'{home}/.superyak/ships/serenity-bricks/settings.local.json.bak-superyak',
             f'{home}/.claude/settings.json.bak-superyak', f'{home}/.superyak/settings.json.bak-superyak']
    for name, (settings, _) in _all_settings(tmp_path / 'wt', tmp_path / 'repo', tmp_path / 'snapshot', tmp_path / 'room').items():
        deny = settings['permissions']['deny']
        assert 'mcp__station' in deny, name
        for tool in ('Read', 'Grep'):
            for key in keys:
                assert any(_covers(rule, key) for rule in deny if rule.startswith(tool + '(')), (name, tool, key)


def test_no_deny_covers_a_runs_own_folder(monkeypatch, tmp_path):
    """Review 487c070b, critical: the watcher's read runs (~/.superyak/worktrees/<ship>/read-<id>), its builder runs
    (~/.superyak/worktrees/<ship>/<id>), teamd's collab rooms (~/.superyak/team/rooms/<team>/<w>) and a lane's preload
    sit under ~/.superyak. A deny beats any allow and reaches the OS sandbox, so none may cover them."""
    home = tmp_path / 'home'
    monkeypatch.setenv('HOME', str(home))
    sy = home / '.superyak'
    build_wt, read_dir = sy / 'worktrees' / 'rio-grande' / 'm1', sy / 'worktrees' / 'rio-grande' / 'read-m2'
    room, workspace = sy / 'team' / 'rooms' / 't1' / 'wash', home / 'superyak'
    preload = sy / 'team' / 'teams' / 't1' / 'workers' / 'kaylee' / 'lane-preload.cjs'
    for name, (settings, folder) in _all_settings(build_wt, workspace, read_dir, room).items():
        deny = settings['permissions']['deny']
        for path in (str(folder), f'{folder}/src/app.py', str(preload)):
            assert not [rule for rule in deny if _covers(rule, path)], (name, path, deny)
        allowed = settings['permissions']['allow']
        assert any(_covers(rule, f'{folder}/src/app.py') for rule in allowed if rule.startswith('Read(')), name


def test_the_guard_reads_the_cwd_only_when_it_needs_it_and_survives_a_deleted_one(ships, monkeypatch):
    """Review 487c070b, finding 5: with CLAUDE_PROJECT_DIR the server's cwd is never read; without it, a server whose
    start folder was deleted (a removed worktree) acts as before D7 for the machine ship (R1), and the project ship,
    which can't tell where it is, refuses."""
    def no_cwd():
        raise FileNotFoundError(2, 'No such file or directory')
    monkeypatch.setattr(os, 'getcwd', no_cwd)
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(ships.repo))
    assert call(tools(ships, ships.project_config, 'bricks-key'))[1] is False      # getcwd never called
    monkeypatch.delenv('CLAUDE_PROJECT_DIR')
    assert call(tools(ships, ships.machine_config, 'serenity-key'))[1] is False
    text, error = call(tools(ships, ships.project_config, 'bricks-key'))
    assert error and f'{SHIP} acts only in' in text


def test_a_guard_that_breaks_refuses(ships):
    """Review 487c070b, finding 7: the server never acts when it can't tell."""
    def broken():
        raise RuntimeError('boom')
    client = StationClient('http://station.test', 'serenity-key', transport=ships.fake)
    t = Tools(client, quick_client=client, guard=broken)
    text, error = call(t)
    assert error and 'could not be checked' in text and 'RuntimeError' in text
    assert 'instructions' not in initialize(t)
