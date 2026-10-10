import json
from pathlib import Path
import plistlib
import subprocess
import sys
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


SETTINGS_CONFIG = '/home/j/.superyak/station.json'


def hook_commands(settings, event):
    data = json.loads(Path(settings).read_text())
    return [h['command'] for entry in data['hooks'].get(event, []) for h in entry['hooks']]


def test_both_hooks_are_installed_with_the_given_commands_and_settings_are_kept(tmp_path):
    settings = tmp_path / '.claude' / 'settings.json'
    settings.parent.mkdir()
    settings.write_text(json.dumps({'model': 'opus', 'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'x'}]}]}}))
    assert install.install_hooks(settings, SETTINGS_CONFIG, messages=True)
    base = install.hook_command(SETTINGS_CONFIG)
    data = json.loads(settings.read_text())
    assert data['model'] == 'opus' and data['hooks']['Stop']
    assert hook_commands(settings, 'SessionStart') == ['SUPERYAK_RUN=${SUPERYAK_RUN:-hook} SUPERYAK_HOOK_EVENT=session-start ' + base + ' || true']
    assert hook_commands(settings, 'UserPromptSubmit') == [base + ' || true']
    assert data['hooks']['UserPromptSubmit'][0]['hooks'][0]['timeout'] == 10
    assert (tmp_path / '.claude' / 'settings.json.bak-superyak').exists()


def test_messages_off_prompt_hook_command(tmp_path):
    settings = tmp_path / 'settings.json'
    install.install_hooks(settings, SETTINGS_CONFIG, messages=False)
    base = install.hook_command(SETTINGS_CONFIG)
    assert hook_commands(settings, 'UserPromptSubmit') == ['SUPERYAK_RUN=${SUPERYAK_RUN:-hook} SUPERYAK_HOOK_MESSAGES=0 ' + base + ' || true']
    assert not settings.with_name('settings.json.bak-superyak').exists()  # nothing to back up


@pytest.mark.parametrize('messages', [True, False])
def test_installing_hooks_twice_changes_nothing(tmp_path, messages):
    settings = tmp_path / 'settings.json'
    settings.write_text('{}')
    assert install.install_hooks(settings, SETTINGS_CONFIG, messages=messages)
    first = settings.read_text()
    assert not install.install_hooks(settings, SETTINGS_CONFIG, messages=messages)
    assert settings.read_text() == first


def test_switching_messages_replaces_the_prompt_hook_without_duplicating_it(tmp_path):
    settings = tmp_path / 'settings.json'
    mine = {'type': 'command', 'command': 'notify-me'}
    settings.write_text(json.dumps({'hooks': {'UserPromptSubmit': [{'hooks': [mine]}]}}))
    install.install_hooks(settings, SETTINGS_CONFIG, messages=True)
    install.install_hooks(settings, SETTINGS_CONFIG, messages=False)
    prompt = hook_commands(settings, 'UserPromptSubmit')
    assert prompt[0] == 'notify-me' and len(prompt) == 2 and 'SUPERYAK_HOOK_MESSAGES=0' in prompt[1]
    install.install_hooks(settings, SETTINGS_CONFIG, messages=True)
    assert hook_commands(settings, 'UserPromptSubmit') == ['notify-me', install.hook_command(SETTINGS_CONFIG) + ' || true']
    assert len(hook_commands(settings, 'SessionStart')) == 1


def test_remove_hooks_removes_both_and_keeps_the_persons_own(tmp_path):
    settings = tmp_path / 'settings.json'
    mine = {'type': 'command', 'command': 'notify-me'}
    settings.write_text(json.dumps({'hooks': {'SessionStart': [{'hooks': [mine]}]}}))
    install.install_hooks(settings, SETTINGS_CONFIG, messages=True)
    assert install.remove_hooks(settings) is True
    assert hook_commands(settings, 'SessionStart') == ['notify-me'] and hook_commands(settings, 'UserPromptSubmit') == []
    assert install.remove_hooks(settings) is False


def test_prefixed_commands_are_station_hooks():
    base = install.hook_command(SETTINGS_CONFIG)
    assert install.is_station_hook('SUPERYAK_RUN=${SUPERYAK_RUN:-hook} SUPERYAK_HOOK_EVENT=session-start ' + base)
    assert install.is_station_hook('SUPERYAK_RUN=${SUPERYAK_RUN:-hook} SUPERYAK_HOOK_MESSAGES=0 ' + base)
    assert not install.is_station_hook('SUPERYAK_RUN=${SUPERYAK_RUN:-hook} python3 other.py hook')


@pytest.mark.parametrize('run_agent', ['/home/j/repo/agent/run_agent.py', '/home/j/My Repo/agent/run_agent.py'])
def test_a_station_hook_is_run_agent_py_as_one_word_followed_by_hook(monkeypatch, run_agent):
    monkeypatch.setattr(install, 'RUN_AGENT', Path(run_agent))
    for messages in (True, False):
        for command in install._hook_commands(SETTINGS_CONFIG, messages).values():
            assert command.endswith(' || true') and install.is_station_hook(command), command
    quoted = install.shlex.join(['/usr/bin/python3', run_agent, 'hook', '--config', SETTINGS_CONFIG])
    assert install.is_station_hook(quoted) and install.is_station_hook(quoted + ' || true')
    for other in [f'/usr/bin/python3 {install.shlex.quote(run_agent + ".bak")} hook',
                  f'/usr/bin/python3 {install.shlex.quote(run_agent)} hook-log',
                  f'/usr/bin/python3 {install.shlex.quote(run_agent)} watch --note hook',
                  f'echo {install.shlex.quote(run_agent)}; python3 other.py hook',
                  f'/usr/bin/python3 {install.shlex.quote(run_agent)} "hook',  # shlex cannot parse it
                  None, 5, ['hook']]:
        assert not install.is_station_hook(other), other


def unguarded(config, messages):
    """The commands an earlier dock installed: the same, without the guard."""
    return {event: command.removesuffix(' || true') for event, command in install._hook_commands(config, messages).items()}


@pytest.mark.parametrize('messages', [True, False])
def test_every_installed_hook_exits_0_and_prints_nothing_when_the_checkout_is_gone(monkeypatch, tmp_path, messages):
    """Break caught: python exits 2 when its script is missing, and a UserPromptSubmit hook that exits 2 blocks and
    erases the prompt: a moved or deleted checkout would block every prompt on a docked machine."""
    gone = tmp_path / 'moved away' / 'agent' / 'run_agent.py'
    monkeypatch.setattr(install, 'RUN_AGENT', gone)
    assert subprocess.run([sys.executable, str(gone)], capture_output=True).returncode == 2  # what the guard is for
    settings = tmp_path / 'settings.json'
    install.install_hooks(settings, tmp_path / 'station.json', messages=messages)
    commands = hook_commands(settings, 'SessionStart') + hook_commands(settings, 'UserPromptSubmit') + hook_commands(settings, 'SessionEnd')
    assert len(commands) == 3
    for command in commands:
        done = subprocess.run(['sh', '-c', command], capture_output=True, input=b'{"session_id": "s1"}', timeout=30)
        assert (done.returncode, done.stdout) == (0, b''), command
    for command in unguarded(tmp_path / 'station.json', messages).values():  # the test can tell the difference
        assert subprocess.run(['sh', '-c', command], capture_output=True, timeout=30).returncode == 2


@pytest.mark.parametrize('messages', [True, False])
def test_docking_again_upgrades_unguarded_hooks_without_adding_a_second(tmp_path, messages):
    settings = tmp_path / 'settings.json'
    mine = {'type': 'command', 'command': 'notify-me'}
    old = unguarded(SETTINGS_CONFIG, messages)
    settings.write_text(json.dumps({'hooks': {event: [{'hooks': [mine, {'type': 'command', 'command': command, 'timeout': 10}]}]
                                              for event, command in old.items()}}))
    assert sorted(install.install_hooks(settings, SETTINGS_CONFIG, messages=messages)) == ['SessionEnd', 'SessionStart', 'UserPromptSubmit']
    for event, wanted in install._hook_commands(SETTINGS_CONFIG, messages).items():
        assert hook_commands(settings, event) == ['notify-me', wanted]
    assert install.install_hooks(settings, SETTINGS_CONFIG, messages=messages) == []
    assert install.remove_hooks(settings) is True
    assert hook_commands(settings, 'SessionStart') == ['notify-me'] and hook_commands(settings, 'UserPromptSubmit') == ['notify-me']
    assert hook_commands(settings, 'SessionEnd') == ['notify-me']


def test_remove_hooks_skips_what_it_cannot_read_and_drops_emptied_events(tmp_path):
    settings = tmp_path / 'settings.json'
    ours = install._hook_commands(SETTINGS_CONFIG, True)['UserPromptSubmit']
    odd = {'hooks': {'SessionStart': 'not a list', 'Stop': [{'hooks': [{'command': 'x'}]}],
                     'UserPromptSubmit': [5, 'text', {'hooks': 'not a list'}, {'hooks': [7, {'command': 9}, {'type': 'command', 'command': ours}]}]}}
    settings.write_text(json.dumps(odd))
    assert install.remove_hooks(settings) is True
    data = json.loads(settings.read_text())
    assert data['hooks']['SessionStart'] == 'not a list' and data['hooks']['Stop'] == odd['hooks']['Stop']
    assert data['hooks']['UserPromptSubmit'] == [5, 'text', {'hooks': 'not a list'}, {'hooks': [7, {'command': 9}]}]
    settings.write_text(json.dumps({'hooks': {'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': ours}]}]}}))
    assert install.remove_hooks(settings) is True and json.loads(settings.read_text()) == {'hooks': {}}
    for value in ([], {'hooks': []}, {'hooks': None}, 'text'):
        settings.write_text(json.dumps(value))
        assert install.remove_hooks(settings) is False and json.loads(settings.read_text()) == value


@pytest.mark.parametrize('mode', [0o600, 0o644])
def test_settings_keep_their_mode_and_a_new_file_is_private(tmp_path, mode):
    """Break caught: settings.json can hold `env` secrets, and every dock rewrote it with the umask's mode."""
    settings = tmp_path / 'settings.json'
    settings.write_text('{"env": {"TOKEN": "secret"}}')
    settings.chmod(mode)
    assert install.install_hooks(settings, SETTINGS_CONFIG, messages=True)
    assert settings.stat().st_mode & 0o777 == mode
    assert install.remove_hooks(settings) and settings.stat().st_mode & 0o777 == mode
    assert json.loads(settings.read_text())['env'] == {'TOKEN': 'secret'} and sorted(p.name for p in tmp_path.iterdir()) == [
        'settings.json', 'settings.json.bak-superyak']
    fresh = tmp_path / 'new' / 'settings.json'
    fresh.parent.mkdir()
    install.install_hooks(fresh, SETTINGS_CONFIG, messages=False)
    assert fresh.stat().st_mode & 0o777 == 0o600


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
    ours = lambda python: f'{python} {install.RUN_AGENT} hook --config /home/j/.superyak/station.json || true'  # noqa: E731
    mine = {'type': 'command', 'command': 'notify-me'}
    settings.write_text(json.dumps({'hooks': {'UserPromptSubmit': [{'hooks': [mine, {'type': 'command', 'command': ours('/old/python3.11')}]}]}}))
    install.install_hooks(settings, '/home/j/.superyak/station.json', messages=True)
    assert json.loads(settings.read_text())['hooks']['UserPromptSubmit'][0]['hooks'][1]['command'] == ours('/old/python3.11')
    assert len(hook_commands(settings, 'UserPromptSubmit')) == 2
    assert install.remove_hooks(settings) is True
    assert json.loads(settings.read_text())['hooks']['UserPromptSubmit'] == [{'hooks': [mine]}]
    assert install.remove_hooks(settings) is False
    unrelated = {'hooks': {'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': 'python3 other.py hook'}]}]}}
    settings.write_text(json.dumps(unrelated))
    assert install.remove_hooks(settings) is False and json.loads(settings.read_text()) == unrelated


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
        # a ship that already has a mention cursor, as every docked ship had before R22: the service installs with no
        # station call (test_ship_homes covers the first install)
        write_private(self.config.parent / 'ship-state.json', {'mention_seq': 0})

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
    assert 'UserPromptSubmit' not in json.loads(settings.read_text())['hooks']  # an event left empty is removed
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


def test_dock_without_hook_flag_installs_the_law_hooks_with_messages_off(monkeypatch, tmp_path):
    machine = Machine(monkeypatch, tmp_path)
    machine.install(adna=False)
    settings = machine.home / '.claude' / 'settings.json'
    assert len(hook_commands(settings, 'SessionStart')) == 1
    assert 'SUPERYAK_HOOK_MESSAGES=0' in hook_commands(settings, 'UserPromptSubmit')[0]
    machine.out.clear()
    machine.install(adna=False, hook=True)
    assert hook_commands(settings, 'UserPromptSubmit') == [install.hook_command(machine.config) + ' || true']
    machine.out.clear()
    machine.install(adna=False)
    assert 'Room messages will no longer appear in Claude Code sessions (instructions still load).' in machine.out
    assert len(hook_commands(settings, 'UserPromptSubmit')) == 1


def test_a_malformed_settings_file_is_reported_and_the_service_still_installs(monkeypatch, tmp_path):
    machine = Machine(monkeypatch, tmp_path)
    settings = machine.home / '.claude' / 'settings.json'
    settings.parent.mkdir()
    settings.write_text('{not json')
    machine.install(adna=False, hook=True)
    assert any('hook' in line and 'settings.json' in line for line in machine.out)
    assert machine.called('systemctl', '--user', 'restart', install.UNIT)
    assert settings.read_text() == '{not json'


def test_a_private_settings_file_is_still_private_after_dock(monkeypatch, tmp_path):
    machine = Machine(monkeypatch, tmp_path)
    settings = machine.home / '.claude' / 'settings.json'
    settings.parent.mkdir()
    settings.write_text('{"env": {"TOKEN": "secret"}}')
    settings.chmod(0o600)
    machine.install(adna=False)
    assert settings.stat().st_mode & 0o777 == 0o600 and 'hook' in settings.read_text()


def test_undock_finishes_with_a_malformed_settings_file(monkeypatch, tmp_path):
    """Break caught: a malformed settings file stopped undock after the key was revoked but before station.json went."""
    machine = Machine(monkeypatch, tmp_path)
    settings = machine.home / '.claude' / 'settings.json'
    settings.parent.mkdir()
    settings.write_text('{not json')
    monkeypatch.setattr(install, 'client_for', lambda config: SimpleNamespace(revoke_key=lambda: None))
    install.uninstall_all(machine.config, out=machine.out.append)
    assert not machine.config.exists() and settings.read_text() == '{not json'
    assert machine.out[0].startswith('Could not remove the Claude Code hooks from ~/.claude/settings.json (Expecting property name')
    assert machine.out[-1] == 'Undocked: key revoked, watcher stopped and station tools removed; the hooks stay in ~/.claude/settings.json.'
