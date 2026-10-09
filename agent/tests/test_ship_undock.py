"""Many ships on one machine (D7), build step 6: undocking one ship never touches another (S10, R21): its own key,
service, tool entry, hooks, Codex entry and home, then its claim last, in one lock hold; it works with the registry
unreadable and with no claim; the last claim's removal leaves projects.json holding [] (R8); the Codex profile keeps
its other tables (R20)."""
import json
from types import SimpleNamespace
import pytest
from superyak_agent import __main__ as cli, claims, install
from superyak_agent.station import read_json, write_private
from ships_fakes import hook_commands
from test_ship_project_dock import SHIP, World


@pytest.fixture
def both(monkeypatch, tmp_path, capsys):
    world = World(monkeypatch, tmp_path, capsys)
    assert world.dock()[0] == 0
    world.machine.calls.clear()
    world.revoked = []
    monkeypatch.setattr(install, 'client_for', lambda cfg: SimpleNamespace(revoke_key=lambda: world.revoked.append(cfg['key'])))
    return world


def machine_state(world):
    home = world.machine.home
    return {'config': read_json(world.machine.config), 'user_station': world.machine.user_station,
            'settings': (home / '.claude' / 'settings.json').read_text(), 'codex': (home / '.codex' / 'config.toml').read_text()}


def project_state(world):
    home = world.machine.home
    return {'config': read_json(world.home / 'station.json'), 'local': dict(world.machine.local_station),
            'settings': (world.repo / '.claude' / 'settings.local.json').read_text(),
            'profile': (home / '.codex' / f'{SHIP}.config.toml').read_text(), 'claim': read_json(world.home / 'claim.json'),
            'registry': claims.read_registry()}


def undock(world, home):
    code = cli.main(['undock', '--home', str(home)])
    out = world.capsys.readouterr()
    return code, out.out + out.err


def test_undocking_the_project_ship_leaves_the_machine_ship(both, monkeypatch):
    """R21: the project ship's key, service, local tools from its root, hooks in settings.local.json, profile table
    and home go; its claim goes last; the machine ship's everything stays."""
    before = machine_state(both)
    order = []
    real_unclaim = claims.unclaim

    def unclaim(home, held=False):
        order.append(('unclaim', (home / 'station.json').exists(), dict(both.machine.local_station)))
        return real_unclaim(home, held)
    monkeypatch.setattr(claims, 'unclaim', unclaim)
    code, out = undock(both, both.home)
    assert code == 0, out
    assert both.revoked == [f'key-{SHIP}']
    assert order == [('unclaim', False, {})]                       # last: after the home's files and the local tools
    calls = both.machine.calls
    assert (['claude', 'mcp', 'remove', '--scope', 'local', 'station'], str(both.repo)) in calls
    assert not any(argv[:5] == ['claude', 'mcp', 'remove', '--scope', 'user'] for argv, cwd in calls)
    assert not any('superyak-ship.service' in argv or 'com.superyak.ship' in argv for argv, cwd in calls)
    assert hook_commands(both.repo / '.claude' / 'settings.local.json', 'UserPromptSubmit') == []
    assert not (both.machine.home / '.codex' / f'{SHIP}.config.toml').exists()
    assert not both.home.exists() and claims.read_registry() == []
    assert json.loads(claims.registry_path().read_text()) == []      # the last claim leaves [], never no file (R8)
    assert machine_state(both) == before


def test_undocking_the_machine_ship_leaves_the_project_ship(both):
    before = project_state(both)
    code, out = undock(both, claims.machine_home())
    assert code == 0, out
    assert both.revoked == ['k'] and not both.machine.config.exists()
    assert both.machine.user_station is None
    assert not any(argv[:5] == ['claude', 'mcp', 'remove', '--scope', 'local'] for argv, cwd in both.machine.calls)
    assert hook_commands(both.machine.home / '.claude' / 'settings.json', 'UserPromptSubmit') == []
    assert '[mcp_servers.station]' not in (both.machine.home / '.codex' / 'config.toml').read_text()
    assert project_state(both) == before
    assert (claims.ships_root() / SHIP).is_dir()


def test_undock_works_with_the_registry_unreadable_and_with_no_claim(both):
    claims.registry_path().write_text('{garbled')
    code, out = undock(both, both.home)
    assert code == 0, out
    assert not (both.home / 'claim.json').exists() and both.machine.local_station == {}
    assert str(claims.registry_path()) in out
    # a project ship that stopped before its claim: only station.json
    write_private(claims.project_home('odo') / 'station.json', {'station': 'http://station.test', 'key': 'odo-key', 'ship': 'odo'})
    claims.registry_path().write_text('[]')
    code, out = undock(both, claims.project_home('odo'))
    assert code == 0, out
    assert not claims.project_home('odo').exists() and both.revoked[-1] == 'odo-key'


def test_codex_profile_is_never_overwritten_on_undock(both):
    """R20 (undock's part): only the station table goes, and the file only when nothing else is left in it."""
    profile = both.machine.home / '.codex' / f'{SHIP}.config.toml'
    profile.write_text('model = "m"\n\n' + profile.read_text())
    assert undock(both, both.home)[0] == 0
    assert profile.read_text() == 'model = "m"\n'


def test_undock_refuses_a_home_that_is_neither_kind(both, tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    write_private(elsewhere / 'station.json', {'station': 'http://station.test', 'key': 'x', 'ship': 'x'})
    before = machine_state(both)
    code, out = undock(both, elsewhere)
    assert code == 2 and 'home' in out and both.revoked == [] and machine_state(both) == before
