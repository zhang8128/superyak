import json
import plistlib
from superyak_agent import install


ARGV = ['/usr/bin/python3', '/home/j/My Repo/agent/run_agent.py', 'watch', '--config', '/home/j/.superyak/station.json']


def test_systemd_unit_quotes_arguments_and_restarts():
    unit = install.systemd_unit(ARGV, '/usr/bin:/bin')
    assert 'ExecStart="/usr/bin/python3" "/home/j/My Repo/agent/run_agent.py" "watch"' in unit
    assert 'Restart=always' in unit and 'MemoryMax=3G' in unit and 'Environment="PATH=/usr/bin:/bin"' in unit


def test_launchd_plist_keeps_the_watcher_alive():
    plist = plistlib.loads(install.launchd_plist(ARGV, '/usr/bin:/bin', '/home/j/.superyak/ship.log'))
    assert plist['Label'] == 'com.superyak.ship' and plist['ProgramArguments'] == ARGV
    assert plist['KeepAlive'] is True and plist['EnvironmentVariables'] == {'PATH': '/usr/bin:/bin'}


def test_hook_is_added_once_preserving_settings_and_can_be_removed(tmp_path):
    settings = tmp_path / '.claude' / 'settings.json'
    settings.parent.mkdir()
    settings.write_text(json.dumps({'model': 'opus', 'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'x'}]}]}}))
    assert install.install_hook(settings, 'python3 run_agent.py hook') is True
    assert install.install_hook(settings, 'python3 run_agent.py hook') is False
    data = json.loads(settings.read_text())
    assert data['model'] == 'opus' and data['hooks']['Stop']
    assert data['hooks']['UserPromptSubmit'] == [{'hooks': [{'type': 'command', 'command': 'python3 run_agent.py hook', 'timeout': 10}]}]
    assert (tmp_path / '.claude' / 'settings.json.bak-superyak').exists()
    assert install.remove_hook(settings, 'python3 run_agent.py hook') is True
    assert json.loads(settings.read_text())['hooks']['UserPromptSubmit'] == []


def test_codex_registration_appends_one_block(tmp_path):
    config = tmp_path / 'config.toml'
    config.write_text('model = "gpt-6.1-sol"\n')
    assert install.register_codex(config, 'station', ['/usr/bin/python3', '/r/agent/run_agent.py', 'mcp']) is True
    assert install.register_codex(config, 'station', ['/usr/bin/python3', '/r/agent/run_agent.py', 'mcp']) is False
    assert config.read_text() == 'model = "gpt-6.1-sol"\n\n[mcp_servers.station]\ncommand = "/usr/bin/python3"\nargs = ["/r/agent/run_agent.py", "mcp"]\n'


def test_run_mcp_config_gives_watcher_runs_only_the_adna_tools(tmp_path):
    dist = tmp_path / 'dist' / 'index.js'
    servers = install.run_mcp_config(tmp_path / 'station.json', dist)['mcpServers']
    assert 'station' not in servers
    assert servers['adna']['args'] == [str(dist)]
    assert install.run_mcp_config(tmp_path / 'station.json')['mcpServers'] == {}
