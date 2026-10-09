"""Many ships on one machine (D7), build step 1: the machine ship is byte-for-byte today's (R1); modes, names and
collisions are refused before the network (R2); service names per ship (S4); the first service install starts the
watcher at the newest mention (R22). docs/superpowers/specs/2026-10-09-many-ships-one-machine-design.md"""
import os
import plistlib
import shlex
from types import SimpleNamespace
import pytest
from superyak_agent import __main__ as cli, claims, install
from superyak_agent.station import StationClient, read_json, write_private
from ships_fakes import FakeMachine, PYTHON, RUN_AGENT, hook_commands


def watcher_argv(home):
    sy = home / '.superyak'
    return [PYTHON, RUN_AGENT, 'watch', '--config', str(sy / 'station.json'), '--state', str(sy / 'ship-state.json'),
            '--mcp-config', str(sy / 'run-mcp.json')]


@pytest.mark.parametrize('system', ['Linux', 'Darwin'])
def test_machine_ship_is_byte_for_byte_today(monkeypatch, tmp_path, system):
    """R1: the machine ship's tool registration, Codex block, hooks, service, watcher args and undock calls, written
    out literally so a change anywhere shows."""
    machine = FakeMachine(monkeypatch, tmp_path, system=system)
    config = machine.dock_machine()
    sy = machine.home / '.superyak'
    write_private(sy / 'ship-state.json', {'mention_seq': 7})        # every machine ship today has one

    def no_station(_config):
        raise AssertionError('a ship with a mention cursor makes no station call at install')
    monkeypatch.setattr(install, 'client_for', no_station)
    install.install_all(config, hook=True, adna=False, service=True, out=machine.out.append)

    station_argv = [PYTHON, RUN_AGENT, 'mcp', '--config', str(config)]
    uid = os.getuid()
    plist = machine.home / 'Library' / 'LaunchAgents' / 'com.superyak.ship.plist'
    unit = machine.home / '.config' / 'systemd' / 'user' / 'superyak-ship.service'
    service_calls = ([['systemctl', '--user', 'daemon-reload'], ['systemctl', '--user', 'enable', 'superyak-ship.service'],
                      ['systemctl', '--user', 'restart', 'superyak-ship.service'], ['loginctl', 'enable-linger']]
                     if system == 'Linux' else
                     [['launchctl', 'bootout', f'gui/{uid}/com.superyak.ship'], ['launchctl', 'bootstrap', f'gui/{uid}', str(plist)]])
    assert machine.argvs() == [['claude', 'mcp', 'get', 'station'],
                               ['claude', 'mcp', 'add', '--scope', 'user', 'station', '--', *station_argv]] + service_calls
    assert read_json(sy / 'run-mcp.json') == {'mcpServers': {}}
    assert (machine.home / '.codex' / 'config.toml').read_text() == (
        f'[mcp_servers.station]\ncommand = "{PYTHON}"\nargs = ["{RUN_AGENT}", "mcp", "--config", "{config}"]\n')
    base = shlex.join([PYTHON, RUN_AGENT, 'hook', '--config', str(config)])
    settings = machine.home / '.claude' / 'settings.json'
    assert hook_commands(settings, 'SessionStart') == [f'SUPERYAK_RUN=${{SUPERYAK_RUN:-hook}} SUPERYAK_HOOK_EVENT=session-start {base} || true']
    assert hook_commands(settings, 'UserPromptSubmit') == [f'{base} || true']
    assert not (machine.home / '.claude' / 'settings.json.bak-superyak').exists()   # nothing to back up: a new file
    if system == 'Linux':
        text = unit.read_text()
        assert 'ExecStart=' + ' '.join(install.systemd_quote(a) for a in watcher_argv(machine.home)) in text.splitlines()
        assert not plist.exists()
    else:
        loaded = plistlib.loads(plist.read_bytes())
        assert loaded['Label'] == 'com.superyak.ship' and loaded['ProgramArguments'] == watcher_argv(machine.home)
        assert loaded['StandardOutPath'] == loaded['StandardErrorPath'] == str(sy / 'ship.log')
        assert not unit.exists()
    assert read_json(sy / 'ship-state.json') == {'mention_seq': 7}

    machine.calls.clear()
    revoked = []
    monkeypatch.setattr(install, 'client_for', lambda cfg: SimpleNamespace(revoke_key=lambda: revoked.append(cfg['key'])))
    install.uninstall_all(config, out=machine.out.append)
    undock_service = ([['systemctl', '--user', 'disable', '--now', 'superyak-ship.service'], ['systemctl', '--user', 'daemon-reload']]
                      if system == 'Linux' else [['launchctl', 'bootout', f'gui/{uid}/com.superyak.ship']])
    assert machine.argvs() == undock_service + [['claude', 'mcp', 'remove', '--scope', 'user', 'station']]
    assert revoked == ['k'] and not config.exists() and not (sy / 'run-mcp.json').exists()
    assert not unit.exists() and not plist.exists()
    assert '[mcp_servers.station]' not in (machine.home / '.codex' / 'config.toml').read_text()
    assert hook_commands(settings, 'SessionStart') == [] and hook_commands(settings, 'UserPromptSubmit') == []


class DockSpy:
    """Stands in for dock.Dock: records that the network side was reached."""
    made = []

    def __init__(self, *args, **kwargs):
        DockSpy.made.append((args, kwargs))

    def run(self, *args, **kwargs):
        return 0


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob('*')) if root.exists() else []


def dock(monkeypatch, capsys, *args):
    from superyak_agent import dock as dock_module
    DockSpy.made = []
    monkeypatch.setattr(dock_module, 'Dock', DockSpy)
    monkeypatch.setattr(install, 'install_all', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('installed')))
    code = cli.main(['dock', '--station', 'http://station', *args])
    return code, capsys.readouterr().err


@pytest.mark.parametrize('args, why', [
    (['--ship', 'serenity-bricks', '--home', '{ships}/serenity-bricks'], 'needs --project'),
    (['--ship', 'serenity-bricks', '--project', '{repo}', '--home', '{sy}'], 'needs the project home'),
    (['--ship', 'serenity-bricks', '--project', '{repo}', '--home', '{ships}/other'], 'the home must be'),
    (['--ship', 'serenity', '--home', '{tmp}/elsewhere'], 'the home must be'),
    (['--ship', 'Serenity'], 'ship names'),
    (['--ship', 's'], 'ship names'),
    (['--ship', 'bad_name', '--project', '{repo}'], 'ship names'),
    (['--ship=-x'], 'ship names'),
    (['--project', '{repo}'], 'needs --ship'),
    (['--ship', 'serenity', '--project', '{repo}'], "already this machine's ship"),
    (['--ship', 'serenity-bricks'], "already this machine's ship"),
    (['--ship', 'odo', '--project', '{repo}'], 'holds the ship'),
    (['--ship', 'kaylee'], 'holds the ship'),
])
def test_modes_names_and_collisions_are_refused_before_the_network(monkeypatch, tmp_path, capsys, args, why):
    """R2: every refusal comes before any docking request and any write. The fixtures have ship != ship_name, as the
    station writes them, so the collision check must read `ship` (the username) to fire."""
    machine = FakeMachine(monkeypatch, tmp_path)
    sy, ships = machine.home / '.superyak', machine.home / '.superyak' / 'ships'
    write_private(sy / 'station.json', {'station': 'http://s', 'key': 'k1', 'ship': 'serenity', 'ship_name': 'Serenity'})
    write_private(ships / 'serenity-bricks' / 'station.json',
                  {'station': 'http://s', 'key': 'k2', 'ship': 'serenity-bricks', 'ship_name': 'Serenity Bricks'})
    write_private(ships / 'odo' / 'station.json', {'station': 'http://s', 'key': 'k3', 'ship': 'quark', 'ship_name': 'Quark'})
    repo = tmp_path / 'repo'
    repo.mkdir()
    if args == ['--ship', 'serenity-bricks']:
        (sy / 'station.json').unlink()        # a machine dock whose only conflict is the project ship's name
    before = tree(machine.home)
    filled = [a.format(sy=sy, ships=ships, repo=repo, tmp=tmp_path) for a in args]
    code, err = dock(monkeypatch, capsys, *filled)
    assert code == 2 and why in err, err
    assert DockSpy.made == [] and tree(machine.home) == before and machine.calls == []


def test_the_machine_ship_docks_with_its_old_defaults(monkeypatch, tmp_path, capsys):
    """S3: no --home and no --workspace give today's home and today's workspace (this checkout)."""
    machine = FakeMachine(monkeypatch, tmp_path)
    from superyak_agent import dock as dock_module
    DockSpy.made, installed = [], []
    monkeypatch.setattr(dock_module, 'Dock', DockSpy)
    monkeypatch.setattr(install, 'install_all', lambda config, **kw: installed.append((config, kw)))
    assert cli.main(['dock', '--station', 'http://station', '--ship', 'serenity', '--hook']) == 0
    (_, kwargs), = DockSpy.made
    assert kwargs['home'] == machine.home / '.superyak' and kwargs['workspace'] == str(install.AGENT_DIR.parent)
    assert installed == [(machine.home / '.superyak' / 'station.json', {'hook': True, 'adna': True, 'service': True})]


def test_service_names_per_ship(monkeypatch, tmp_path):
    """S4: a project ship's label, plist, unit and log come from its name; the machine ship's are unchanged."""
    machine = FakeMachine(monkeypatch, tmp_path, system='Darwin')
    sy = machine.home / '.superyak'
    assert install.service_names(sy) == ('com.superyak.ship', 'superyak-ship.service', sy / 'ship.log')
    home = sy / 'ships' / 'serenity-bricks'
    assert install.service_names(home) == ('com.superyak.ship.serenity-bricks', 'superyak-ship-serenity-bricks.service',
                                           home / 'ship.log')
    install.install_service(['w'], machine.out.append, names=install.service_names(home))
    plist = machine.home / 'Library' / 'LaunchAgents' / 'com.superyak.ship.serenity-bricks.plist'
    loaded = plistlib.loads(plist.read_bytes())
    assert loaded['Label'] == 'com.superyak.ship.serenity-bricks' and loaded['StandardOutPath'] == str(home / 'ship.log')
    uid = os.getuid()
    assert machine.argvs() == [['launchctl', 'bootout', f'gui/{uid}/com.superyak.ship.serenity-bricks'],
                               ['launchctl', 'bootstrap', f'gui/{uid}', str(plist)]]
    machine.calls.clear()
    linux = FakeMachine(monkeypatch, tmp_path, system='Linux')
    install.install_service(['w'], linux.out.append, names=install.service_names(home))
    assert (linux.home / '.config' / 'systemd' / 'user' / 'superyak-ship-serenity-bricks.service').exists()
    assert ['systemctl', '--user', 'restart', 'superyak-ship-serenity-bricks.service'] in linux.argvs()


def test_first_service_install_skips_the_backlog(monkeypatch, tmp_path, station):
    """R22: with no mention cursor, the first service install reads the mentions to the end (more than one page) and
    stores the newest, so the watcher never answers the backlog; an existing cursor is kept with no station call."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, serenity)
    for n in range(120):
        fake.say(room, andy, f'@serenity number {n}')
    machine = FakeMachine(monkeypatch, tmp_path)
    config = machine.dock_machine()
    client = StationClient('http://station.test', 'serenity-key', transport=fake)
    install.install_all(config, hook=False, adna=False, service=True, out=machine.out.append, client=client)
    state = machine.home / '.superyak' / 'ship-state.json'
    assert read_json(state) == {'mention_seq': 120}
    assert "The watcher starts after mention 120; earlier mentions won't be answered." in machine.out
    fake.say(room, andy, '@serenity one more')
    write_private(state, {'mention_seq': 3, 'answered': ['m1']})
    install.install_all(config, hook=False, adna=False, service=True, out=machine.out.append,
                        client=StationClient('http://station.test', 'wrong', transport=fake))
    assert read_json(state) == {'mention_seq': 3, 'answered': ['m1']}


def test_a_station_that_cannot_list_mentions_installs_no_watcher(monkeypatch, tmp_path, station):
    """R22, failing closed: without the newest mention, no service is installed rather than one that would answer
    the backlog."""
    fake, andy, jenn, serenity = station
    machine = FakeMachine(monkeypatch, tmp_path)
    config = machine.dock_machine()
    fake.down = True
    install.install_all(config, hook=False, adna=False, service=True, out=machine.out.append,
                        client=StationClient('http://station.test', 'serenity-key', transport=fake))
    assert not any(argv[0] in ('systemctl', 'launchctl') for argv in machine.argvs())
    assert any('watcher was not installed' in line for line in machine.out)
    assert not (machine.home / '.superyak' / 'ship-state.json').exists()


def test_check_mode_answers_the_home_and_kind(monkeypatch, tmp_path):
    machine = FakeMachine(monkeypatch, tmp_path)
    sy = machine.home / '.superyak'
    assert claims.check_mode('serenity', None, None) == (sy, 'machine')
    assert claims.check_mode(None, str(sy), None) == (sy, 'machine')
    assert claims.check_mode('serenity-bricks', None, str(tmp_path)) == (sy / 'ships' / 'serenity-bricks', 'project')
    assert claims.kind_of(sy) == 'machine' and claims.kind_of(sy / 'ships' / 'serenity-bricks') == 'project'
    assert claims.kind_of(tmp_path / 'elsewhere') is None
