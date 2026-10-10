"""Ship status, build step 4: the SessionEnd hook ends this session's watch, best effort, and is the one new client
call (spec S4, M2, R2)."""
import io
import json
import pytest
from superyak_agent import __main__ as cli, hook, install
from superyak_agent.station import StationClient, write_private
from ships_fakes import hook_commands

CONFIG = '/home/me/.superyak/station.json'


def write_config(ship_config, tmp_path):
    path = tmp_path / 'home' / 'station.json'
    write_private(path, ship_config)
    return path


def declare(fake, session):
    StationClient('http://station.test', 'serenity-key', transport=fake, presence={'x-superyak-session': session}).watch(20, writable=True)


def test_session_end_ends_the_watch(station, ship_config, tmp_path):
    """R2, S4: SessionEnd calls watch(0) for that session, nothing else, and prints nothing; without a session id it
    calls nothing; with the station down it prints nothing and the next hook skips the station for a minute."""
    fake, andy, jenn, serenity = station
    config_path, sessions = write_config(ship_config, tmp_path), tmp_path / 'sessions'
    declare(fake, 's1')
    fake.requests.clear()
    assert hook.run(config_path, transport=fake, event='session-end', session_id='s1', sessions_dir=sessions) == ''
    assert [(r['method'], r['path'], r['body'], r['presence'].get('x-superyak-session')) for r in fake.requests] == [
        ('POST', '/api/ships/me/watch', {'minutes': 0, 'writable': False}, 's1')]
    assert fake.watches == {}
    fake.requests.clear()
    assert hook.run(config_path, transport=fake, event='session-end', sessions_dir=sessions) == '' and fake.requests == []
    declare(fake, 's1')
    fake.down = True
    assert hook.run(config_path, transport=fake, event='session-end', session_id='s1', sessions_dir=sessions) == ''
    assert (sessions / hook.UNREACHABLE).exists()


def test_the_installed_session_end_command_reaches_the_station(station, ship_config, tmp_path, monkeypatch, capsys):
    """M2: what Claude Code runs at SessionEnd, as installed: SUPERYAK_HOOK_EVENT=session-end, the stdin it measured."""
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    declare(fake, 's1')
    monkeypatch.setattr(hook, 'urllib_transport', lambda timeout=5: fake)
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps({'session_id': 's1', 'hook_event_name': 'SessionEnd', 'reason': 'other'})))
    monkeypatch.setenv('SUPERYAK_HOOK_EVENT', 'session-end')
    assert cli.main(['hook', '--config', str(config_path)]) == 0
    assert fake.watches == {} and capsys.readouterr().out == ''


@pytest.mark.parametrize('messages', [True, False])
def test_the_session_end_hook_is_installed_and_removed_with_the_others(tmp_path, messages):
    settings = tmp_path / 'settings.json'
    assert sorted(install.install_hooks(settings, CONFIG, messages=messages)) == ['SessionEnd', 'SessionStart', 'UserPromptSubmit']
    base = install.hook_command(CONFIG)
    assert hook_commands(settings, 'SessionEnd') == [f'SUPERYAK_RUN=${{SUPERYAK_RUN:-hook}} SUPERYAK_HOOK_EVENT=session-end {base} || true']
    assert install.install_hooks(settings, CONFIG, messages=messages) == []
    assert install.remove_hooks(settings) is True and hook_commands(settings, 'SessionEnd') == []
