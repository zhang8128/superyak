"""The lessons hook's own switch in the installer (first rail spec section 8): apart from the room hook, so a session can
have it with the room hook and the station tools off, and nothing changes on a machine that doesn't ask for it."""
import json
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from superyak_agent import install
from superyak_agent.__main__ import build_parser
from test_install import Machine, hook_commands

LESSONS_EVENTS = {'SessionStart': None, 'UserPromptSubmit': None, 'PostToolUseFailure': 'Bash'}


def lessons_settings(folder, **fields):
    path = Path(folder) / 'lessons-hook.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'ship': 'tardis', 'data_dir': '/srv/peer', **fields}))
    return path


def entries(settings, event):
    return json.loads(Path(settings).read_text())['hooks'].get(event, [])


def lessons_commands(settings):
    data = json.loads(Path(settings).read_text())
    return [h['command'] for event in data.get('hooks', {}).values() for entry in event for h in entry['hooks']
            if 'lessons-hook' in h['command']]


def test_dock_installs_no_lessons_hook_unless_asked(monkeypatch, tmp_path):
    machine = Machine(monkeypatch, tmp_path)
    machine.install(adna=False, hook=True)
    settings = machine.home / '.claude' / 'settings.json'
    assert lessons_commands(settings) == [] and 'PostToolUseFailure' not in json.loads(settings.read_text())['hooks']
    assert build_parser().parse_args(['dock', '--station', 'http://s']).lessons is None


def test_the_switch_installs_the_lessons_hook_beside_the_room_hook(monkeypatch, tmp_path):
    machine = Machine(monkeypatch, tmp_path)
    path = lessons_settings(machine.home / '.superyak')
    machine.install(adna=False, lessons=path)
    settings = machine.home / '.claude' / 'settings.json'
    wanted = ('SUPERYAK_RUN=${SUPERYAK_RUN:-hook} '
              + shlex.join([sys.executable, '-B', str(install.RUN_AGENT), 'lessons-hook', '--settings', str(path)]) + ' || true')
    for event, matcher in LESSONS_EVENTS.items():
        [ours] = [e for e in entries(settings, event) if 'lessons-hook' in e['hooks'][0]['command']]
        assert ours == ({'matcher': matcher} if matcher else {}) | {'hooks': [{'type': 'command', 'command': wanted, 'timeout': 5}]}
    assert len(hook_commands(settings, 'SessionStart')) == 2 and len(hook_commands(settings, 'UserPromptSubmit')) == 2
    # PreToolUse belongs to the shared hold entry (`run_agent.py hold`, which checklists-feature installs); this hook
    # adds none of its own there
    assert not [c for c in hook_commands(settings, 'PreToolUse') if 'lessons-hook' in c]
    assert all(' hold' in c for c in hook_commands(settings, 'PreToolUse'))
    assert any('lessons hook' in line for line in machine.out)
    assert install.is_lessons_hook(wanted) and not install.is_station_hook(wanted)


def test_dock_passes_the_switch_only_when_given_and_refuses_it_for_a_project_ship(monkeypatch, tmp_path, capsys):
    from superyak_agent import __main__ as cli, dock as dock_module
    machine = Machine(monkeypatch, tmp_path)
    installed = []

    class Docked:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, fields, wait):
            return 0
    monkeypatch.setattr(dock_module, 'Dock', Docked)
    monkeypatch.setattr(install, 'install_all', lambda config, **kw: installed.append(kw))
    path = lessons_settings(machine.home / '.superyak')
    assert cli.main(['dock', '--station', 'http://s', '--ship', 'serenity', '--lessons', str(path)]) == 0
    assert installed == [{'hook': False, 'adna': True, 'service': True, 'lessons': path}]
    project = tmp_path / 'project'
    project.mkdir()
    assert cli.main(['dock', '--station', 'http://s', '--ship', 'kaylee', '--project', str(project), '--lessons',
                     str(path)]) == 2
    assert '--lessons is for the machine ship' in capsys.readouterr().err and len(installed) == 1


def test_installing_the_lessons_hook_twice_changes_nothing(tmp_path):
    settings, path = tmp_path / 'settings.json', lessons_settings(tmp_path)
    assert install.install_lessons_hooks(settings, path) == list(LESSONS_EVENTS)
    before = settings.read_text()
    assert install.install_lessons_hooks(settings, path) == [] and settings.read_text() == before
    other = lessons_settings(tmp_path / 'elsewhere')
    assert install.install_lessons_hooks(settings, other) == list(LESSONS_EVENTS)  # replaced, never doubled
    assert len(lessons_commands(settings)) == 3 and all(str(other) in c for c in lessons_commands(settings))


def test_each_switch_leaves_the_others_hooks_and_the_persons_own(tmp_path):
    settings, path = tmp_path / 'settings.json', lessons_settings(tmp_path)
    settings.write_text(json.dumps({'hooks': {'PostToolUseFailure': [{'matcher': 'Bash', 'hooks': [
        {'type': 'command', 'command': 'notify-send failed'}]}]}}))
    install.install_hooks(settings, tmp_path / 'station.json', messages=True)
    install.install_lessons_hooks(settings, path)
    install.install_hooks(settings, tmp_path / 'station.json', messages=False)  # docking again keeps the lessons hook
    assert len(lessons_commands(settings)) == 3
    assert install.remove_hooks(settings) is True  # undocking removes the room hook only
    assert len(lessons_commands(settings)) == 3 and hook_commands(settings, 'SessionEnd') == []
    install.install_hooks(settings, tmp_path / 'station.json', messages=True)
    assert install.remove_lessons_hooks(settings) is True
    assert lessons_commands(settings) == []
    assert len(hook_commands(settings, 'UserPromptSubmit')) == 1
    assert hook_commands(settings, 'PostToolUseFailure') == ['notify-send failed']
    assert install.remove_lessons_hooks(settings) is False


def test_removing_the_lessons_hook_drops_the_events_it_emptied(tmp_path):
    settings = tmp_path / 'settings.json'
    install.install_lessons_hooks(settings, lessons_settings(tmp_path))
    install.remove_lessons_hooks(settings)
    assert json.loads(settings.read_text())['hooks'] == {}


@pytest.mark.parametrize('fields', [{'ship': 'Not A Ship'}, {'data_dir': ''}, {'query': 'not a list'}])
def test_settings_the_hook_cant_use_install_nothing_and_say_so(monkeypatch, tmp_path, fields):
    machine = Machine(monkeypatch, tmp_path)
    machine.install(adna=False, lessons=lessons_settings(machine.home / '.superyak', **fields))
    assert lessons_commands(machine.home / '.claude' / 'settings.json') == []
    assert any('lessons hook' in line and 'not installed' in line for line in machine.out)


def test_the_lessons_hook_exits_0_and_prints_nothing_when_the_checkout_is_gone(monkeypatch, tmp_path):
    gone = tmp_path / 'moved away' / 'agent' / 'run_agent.py'
    monkeypatch.setattr(install, 'RUN_AGENT', gone)
    settings = tmp_path / 'settings.json'
    install.install_lessons_hooks(settings, lessons_settings(tmp_path))
    for command in lessons_commands(settings):
        done = subprocess.run(['sh', '-c', command], capture_output=True, input=b'{"session_id": "s1"}', timeout=30)
        assert (done.returncode, done.stdout) == (0, b''), command
        assert subprocess.run(['sh', '-c', command.removesuffix(' || true')], capture_output=True, timeout=30).returncode == 2


def settings_named(command):
    """The `--settings` file a lessons hook command names."""
    words = shlex.split(command.removesuffix(' || true'))
    return words[words.index('--settings') + 1]


def test_a_settings_file_elsewhere_is_copied_to_the_one_file_the_hook_and_the_hold_read(monkeypatch, tmp_path):
    """Rio Grande's S2: dock resolves `--lessons` as typed, copies it to lessons_hook.default_settings() at 0600, and
    the hook names that copy, the file the hold before each command reads, so the two can't disagree."""
    from superyak_agent import lessons_hook as lh
    machine = Machine(monkeypatch, tmp_path)
    elsewhere = lessons_settings(tmp_path / 'mine' / 'deep', query=['/opt/lessons-query'])
    monkeypatch.chdir(tmp_path / 'mine')
    machine.install(adna=False, lessons=Path('deep') / 'lessons-hook.json')
    copy, settings = lh.default_settings(), machine.home / '.claude' / 'settings.json'
    assert copy == machine.home / '.superyak' / 'lessons-hook.json'
    assert json.loads(copy.read_text()) == json.loads(elsewhere.read_text()) and oct(copy.stat().st_mode & 0o777) == '0o600'
    assert [settings_named(c) for c in lessons_commands(settings)] == [str(copy)] * 3
    assert any(str(copy) in line and str(elsewhere) in line for line in machine.out)
    elsewhere.write_text(json.dumps({'ship': 'tardis', 'data_dir': '/srv/other'}))   # changed, then docked again
    machine.install(adna=False, lessons=elsewhere)
    assert json.loads(copy.read_text()) == {'ship': 'tardis', 'data_dir': '/srv/other'}


def test_settings_the_hook_cant_use_leave_no_copy(monkeypatch, tmp_path):
    from superyak_agent import lessons_hook as lh
    machine = Machine(monkeypatch, tmp_path)
    machine.install(adna=False, lessons=lessons_settings(tmp_path / 'mine', ship='Not A Ship'))
    assert not lh.default_settings().exists() and lessons_commands(machine.home / '.claude' / 'settings.json') == []


def test_undock_removes_the_lessons_hook_and_its_settings_and_keeps_the_persons_own(monkeypatch, tmp_path):
    """Serenity's M1: undock removed only the room hook, so the lessons hook kept sending every prompt to the index
    reader. Now all three of its entries go, with the settings copy, and the person's own hook stays."""
    from types import SimpleNamespace
    from superyak_agent import lessons_hook as lh
    machine = Machine(monkeypatch, tmp_path)
    settings = machine.home / '.claude' / 'settings.json'
    settings.parent.mkdir(parents=True)
    mine = {'hooks': [{'type': 'command', 'command': 'echo mine'}]}
    settings.write_text(json.dumps({'hooks': {'UserPromptSubmit': [mine]}}))
    machine.install(adna=False, lessons=lessons_settings(tmp_path / 'mine'))
    assert len(lessons_commands(settings)) == 3 and lh.default_settings().exists()
    monkeypatch.setattr(install, 'client_for', lambda config: SimpleNamespace(revoke_key=lambda: None))
    install.uninstall_all(machine.config, out=machine.out.append)
    assert lessons_commands(settings) == [] and not lh.default_settings().exists()
    assert entries(settings, 'UserPromptSubmit') == [mine]
