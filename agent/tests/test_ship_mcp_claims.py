"""Many ships on one machine (D7), build step 5: the station MCP server follows the claims on every call and sends
no instructions when it would refuse (S7, R18); it refuses everything inside teamd workers and watcher runs; and every
settings file claude_sandbox_settings builds denies the station tools and reads of ~/.superyak (S8, S11, R19)."""
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
        shutil.rmtree(root)
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


def test_workers_deny_the_station(tmp_path, monkeypatch):
    """R19: teamd's Claude workers (builders, collaborators, browser lanes), builder runs and read runs all deny the
    station tools and reads of ~/.superyak through Read and Grep, as absolute (//) rules."""
    home = str(Path.home())
    wanted = {'mcp__station', f'Read(/{home}/.superyak/**)', f'Grep(/{home}/.superyak/**)'}
    assert all(rule.startswith(('mcp__', 'Read(//', 'Grep(//')) for rule in wanted)
    built = [workers.claude_sandbox_settings(str(tmp_path / 'wt'), mode='build', repo=str(tmp_path / 'repo')),
             workers.claude_sandbox_settings(str(tmp_path / 'wt'), mode='collab'),
             runs.builder_settings(tmp_path / 'wt', tmp_path / 'repo'),
             runs.read_only_settings(tmp_path / 'snapshot')]
    for settings in built:
        assert wanted <= set(settings['permissions']['deny']), settings['permissions']['deny']
