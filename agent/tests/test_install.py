import json
from pathlib import Path
import plistlib
import subprocess
from types import SimpleNamespace
import pytest
from superyak_agent import install
from superyak_agent.station import StationError, write_private


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


def test_hook_installed_with_another_interpreter_is_the_same_hook(tmp_path):
    settings = tmp_path / 'settings.json'
    ours = lambda python: f'{python} {install.RUN_AGENT} hook --config /home/j/.superyak/station.json'  # noqa: E731
    mine = {'type': 'command', 'command': 'notify-me'}
    settings.write_text(json.dumps({'hooks': {'UserPromptSubmit': [{'hooks': [mine, {'type': 'command', 'command': ours('/old/python3.11')}]}]}}))
    assert install.install_hook(settings, ours('/new/python3.13')) is False
    assert json.loads(settings.read_text())['hooks']['UserPromptSubmit'][0]['hooks'][1]['command'] == ours('/old/python3.11')
    assert install.remove_hook(settings, ours('/new/python3.13')) is True
    assert json.loads(settings.read_text())['hooks']['UserPromptSubmit'] == [{'hooks': [mine]}]
    assert install.remove_hook(settings, ours('/new/python3.13')) is False
    unrelated = {'hooks': {'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': 'python3 other.py hook'}]}]}}
    settings.write_text(json.dumps(unrelated))
    assert install.remove_hook(settings, ours('/new/python3.13')) is False and json.loads(settings.read_text()) == unrelated


def test_codex_block_is_removed_and_other_tables_are_kept(tmp_path):
    config = tmp_path / 'config.toml'
    config.write_text('model = "gpt-6.1-sol"\n')
    install.register_codex(config, 'station', ['/usr/bin/python3', '/r/agent/run_agent.py', 'mcp'])
    assert install.remove_codex(config, 'station') is True
    assert config.read_text() == 'model = "gpt-6.1-sol"\n'
    assert install.remove_codex(config, 'station') is False and install.remove_codex(tmp_path / 'missing.toml', 'station') is False
    config.write_text('model = "m"\n\n[mcp_servers.other]\ncommand = "o"\n\n[mcp_servers.station]\ncommand = "/usr/bin/python3"\n'
                      'args = ["/r/agent/run_agent.py", "mcp"]\n\n[mcp_servers.station.env]\nA = "1"\n\n[projects."/x"]\ntrust = "trusted"\n')
    assert install.remove_codex(config, 'station') is True
    assert config.read_text() == 'model = "m"\n\n[mcp_servers.other]\ncommand = "o"\n\n[projects."/x"]\ntrust = "trusted"\n'


class Machine:
    """A fake machine for install_all and uninstall_all: HOME is a temp directory, `subprocess.run` records
    the commands instead of running them and `shutil.which` finds only the tools it is given."""

    def __init__(self, monkeypatch, tmp_path, tools=('claude', 'codex', 'node', 'npm', 'git'), fail=(), node_version='v22.1.0'):
        self.calls, self.fail, self.node_version, self.out = [], fail, node_version, []
        self.home = tmp_path / 'home'
        self.home.mkdir()
        monkeypatch.setenv('HOME', str(self.home))
        monkeypatch.setattr(install.subprocess, 'run', self.run)
        monkeypatch.setattr(install.shutil, 'which', lambda name: f'/fake/bin/{name}' if name in tools else None)
        monkeypatch.setattr(install, 'platform', SimpleNamespace(system=lambda: 'Linux'))
        self.config = self.home / '.superyak' / 'station.json'
        write_private(self.config, {'station': 'http://station', 'key': 'k', 'ship': 'serenity'})

    def run(self, argv, **kwargs):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        name = Path(argv[0]).name
        if any(name == f[0] and argv[1:len(f)] == list(f[1:]) for f in self.fail):
            raise subprocess.CalledProcessError(1, argv)
        if argv[1:2] == ['--version']:
            return subprocess.CompletedProcess(argv, 0, stdout=self.node_version + '\n')
        if name == 'claude' and argv[1:3] == ['mcp', 'get']:
            return subprocess.CompletedProcess(argv, 1)
        if name == 'npm' and argv[1:3] == ['run', 'build']:
            dist = Path(kwargs['cwd']) / 'dist' / 'index.js'
            dist.parent.mkdir(parents=True, exist_ok=True)
            dist.write_text('//')
        return subprocess.CompletedProcess(argv, 0, stdout='')

    def called(self, *prefix):
        return any(call[:len(prefix)] == list(prefix) for call in self.calls)

    def run_mcp(self):
        return json.loads((self.config.parent / 'run-mcp.json').read_text())

    def install(self, **kw):
        install.install_all(self.config, out=self.out.append, **kw)


def test_a_failing_adna_build_does_not_hold_up_the_required_steps(monkeypatch, tmp_path):
    machine = Machine(monkeypatch, tmp_path, fail=[('npm', 'ci')])
    machine.install(hook=True)
    assert machine.called('/fake/bin/npm', 'ci')
    assert machine.called('claude', 'mcp', 'add', '--scope', 'user', 'station') and not machine.called('claude', 'mcp', 'add', '--scope', 'user', 'adna')
    assert machine.called('systemctl', '--user', 'restart', install.UNIT)
    assert (machine.home / '.config' / 'systemd' / 'user' / install.UNIT).exists()
    assert '[mcp_servers.station]' in (machine.home / '.codex' / 'config.toml').read_text()
    assert 'hook' in (machine.home / '.claude' / 'settings.json').read_text()
    assert machine.run_mcp() == {'mcpServers': {}}
    skipped = [line for line in machine.out if line.startswith('aDNA tools skipped')]
    assert skipped == ['aDNA tools skipped: npm ci failed with exit status 1. Run make dock again to retry, or add --no-adna.']


def test_adna_that_installs_is_added_to_the_watcher_config_and_claude_code(monkeypatch, tmp_path):
    machine = Machine(monkeypatch, tmp_path)
    machine.install()
    dist = machine.home / 'aDNA' / 'aDNA.aDNA' / 'mcp' / 'dist' / 'index.js'
    assert machine.run_mcp()['mcpServers']['adna']['args'] == [str(dist)] and 'station' not in machine.run_mcp()['mcpServers']
    assert machine.called('claude', 'mcp', 'add', '--scope', 'user', 'adna', '--', '/fake/bin/node', str(dist))
    assert machine.called('systemctl', '--user', 'restart', install.UNIT)
    assert not any(line.startswith('aDNA tools skipped') for line in machine.out)


@pytest.mark.parametrize('tools, version, failing, reason', [
    (('claude', 'npm', 'git'), '', [], 'they need Node.js 20 or newer, npm and git'),
    (('claude', 'node', 'npm', 'git'), 'v18.19.0', [], 'they need Node.js 20 or newer, npm and git'),
    (('claude', 'node', 'npm', 'git'), 'not-a-version', [], 'could not read the Node.js version'),
    (('claude', 'node', 'npm', 'git'), 'v22.1.0', [('git', 'clone')], 'git clone failed with exit status 1'),
    (('claude', 'node', 'npm', 'git'), 'v22.1.0', [('npm', 'run', 'build')], 'npm run build failed with exit status 1'),
])
def test_setup_adna_never_raises_and_says_why_it_skipped(monkeypatch, tmp_path, tools, version, failing, reason):
    machine = Machine(monkeypatch, tmp_path, tools=tools, fail=failing, node_version=version)
    assert install.setup_adna(machine.out.append) is None
    assert machine.out == [f'aDNA tools skipped: {reason}. Run make dock again to retry, or add --no-adna.']


def test_a_build_that_leaves_no_dist_is_skipped_too(monkeypatch, tmp_path):
    machine = Machine(monkeypatch, tmp_path)
    monkeypatch.setattr(install.subprocess, 'run', lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout='v22.1.0\n'))
    assert install.setup_adna(machine.out.append) is None
    assert 'did not produce mcp/dist/index.js' in machine.out[0]


def test_a_failing_claude_registration_does_not_hold_up_the_hook_or_the_service(monkeypatch, tmp_path):
    machine = Machine(monkeypatch, tmp_path, fail=[('claude', 'mcp', 'add')])
    machine.install(hook=True, adna=False)
    assert any(line.startswith('Could not register the station tools with Claude Code') for line in machine.out)
    assert machine.called('systemctl', '--user', 'restart', install.UNIT) and 'hook' in (machine.home / '.claude' / 'settings.json').read_text()
    assert not machine.called('/fake/bin/npm')


def test_undock_removes_everything_it_added_and_says_when_the_key_could_not_be_revoked(monkeypatch, tmp_path):
    machine = Machine(monkeypatch, tmp_path)
    machine.install(hook=True, adna=False)
    other_python = f'/elsewhere/python3 {install.RUN_AGENT} hook --config {machine.config}'
    settings = machine.home / '.claude' / 'settings.json'
    data = json.loads(settings.read_text())
    data['hooks']['UserPromptSubmit'][0]['hooks'][0]['command'] = other_python
    settings.write_text(json.dumps(data))

    def refuse():
        raise StationError(500, 'station is on fire')
    monkeypatch.setattr(install, 'client_for', lambda config: SimpleNamespace(revoke_key=refuse))
    machine.out.clear()
    install.uninstall_all(machine.config, out=machine.out.append)
    assert machine.called('systemctl', '--user', 'disable', '--now', install.UNIT) and machine.called('claude', 'mcp', 'remove', '--scope', 'user', 'station')
    assert 'mcp_servers' not in (machine.home / '.codex' / 'config.toml').read_text()
    assert json.loads(settings.read_text())['hooks']['UserPromptSubmit'] == []
    assert not machine.config.exists() and not (machine.config.parent / 'run-mcp.json').exists()
    assert not (machine.home / '.config' / 'systemd' / 'user' / install.UNIT).exists()
    assert machine.out[0].startswith('Could not revoke the key on the station (500: station is on fire)')
    assert machine.out[-1] == 'Undocked on this machine (watcher stopped, station tools and hook removed), but the key was NOT revoked on the station: ask an admin to revoke it.'


def test_undock_reports_a_revoked_key(monkeypatch, tmp_path):
    machine = Machine(monkeypatch, tmp_path)
    revoked = []
    monkeypatch.setattr(install, 'client_for', lambda config: SimpleNamespace(revoke_key=lambda: revoked.append(config['key'])))
    install.uninstall_all(machine.config, out=machine.out.append)
    assert revoked == ['k'] and machine.out == ['Undocked: key revoked, watcher stopped, station tools and hook removed.']
