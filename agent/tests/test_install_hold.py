"""Checklists: installing the hold and trusting the checkout at dock (spec, Install; Trust)."""
import json
import os
import subprocess
import sys
import pytest
from superyak_agent import install
from checklist_fakes import checkout, trust_dirs
from test_install import SETTINGS_CONFIG


def test_dock_adds_a_bash_pretooluse_entry_with_the_guard(tmp_path):
    settings = tmp_path / 'settings.json'
    install.install_hooks(settings, SETTINGS_CONFIG, messages=False)
    assert json.loads(settings.read_text())['hooks']['PreToolUse'] == [
        {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': install.hold_command(SETTINGS_CONFIG) + ' || true', 'timeout': 5}]}]
    assert install.hold_command(SETTINGS_CONFIG) == install.shlex.join(
        [sys.executable, str(install.RUN_AGENT), 'hold', '--config', SETTINGS_CONFIG])


def test_undock_removes_the_hold_and_keeps_the_persons_own_pretooluse_hooks(tmp_path):
    settings = tmp_path / 'settings.json'
    mine = {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'audit-bash'}]}
    settings.write_text(json.dumps({'hooks': {'PreToolUse': [mine]}}))
    install.install_hooks(settings, SETTINGS_CONFIG, messages=True)
    assert install.remove_hooks(settings) is True
    assert json.loads(settings.read_text())['hooks']['PreToolUse'] == [mine]


def test_the_hold_is_a_station_hook_and_its_neighbours_are_not():
    command = install.hold_command(SETTINGS_CONFIG) + ' || true'
    assert install.is_station_hook(command) and 'PreToolUse' in install.HOOK_EVENTS
    assert not install.is_station_hook(command.replace(' hold ', ' hold-log '))


@pytest.mark.parametrize('entry', [{}, {'matcher': 'Bash', 'timeout': 10}])
def test_a_hold_entry_without_the_bash_matcher_or_with_an_old_timeout_is_replaced(tmp_path, entry):
    settings = tmp_path / 'settings.json'
    held = {'type': 'command', 'command': install.hold_command(SETTINGS_CONFIG) + ' || true'}
    if 'timeout' in entry:
        held['timeout'] = entry['timeout']
    settings.write_text(json.dumps({'hooks': {'PreToolUse': [{**({'matcher': entry['matcher']} if 'matcher' in entry else {}), 'hooks': [held]}]}}))
    assert 'PreToolUse' in install.install_hooks(settings, SETTINGS_CONFIG, messages=True)
    entries = json.loads(settings.read_text())['hooks']['PreToolUse']
    assert [(e.get('matcher'), e['hooks'][0]['timeout']) for e in entries] == [('Bash', 5)]


OLD_AGENT = ('import argparse\nparser = argparse.ArgumentParser(prog="superyak-agent")\n'
             'commands = parser.add_subparsers(dest="command", required=True)\n'
             'commands.add_parser("hook").add_argument("--config")\nparser.parse_args()\n')


def test_an_older_agent_rejects_hold_and_the_guard_makes_that_silent(tmp_path, monkeypatch):
    old = tmp_path / 'old' / 'agent' / 'run_agent.py'
    old.parent.mkdir(parents=True)
    old.write_text(OLD_AGENT)
    monkeypatch.setattr(install, 'RUN_AGENT', old)
    command = install._hook_commands(tmp_path / 'station.json', True)['PreToolUse']
    done = subprocess.run(['sh', '-c', command], input=b'{"hook_event_name": "PreToolUse"}', capture_output=True, timeout=30)
    assert (done.returncode, done.stdout) == (0, b'')
    assert subprocess.run(['sh', '-c', command.removesuffix(' || true')], capture_output=True, timeout=30).returncode == 2


def test_dock_trusts_the_superyak_checkout_and_nothing_else(tmp_path):
    superyak = checkout(tmp_path / 'superyak', ('reflect', {}))
    home, said = tmp_path / 'home' / '.superyak', []
    assert install.trust_checkout(home, said.append, checkout=superyak) is True
    trusted = home / 'checklists' / 'trusted.json'
    assert json.loads(trusted.read_text()) == {'trusted': [os.path.realpath(superyak / '.superyak' / 'checklists')]}
    assert oct(trusted.stat().st_mode & 0o777) == '0o600' and said[0].startswith("Trusted this checkout's checklists")
    assert install.trust_checkout(home, said.append, checkout=superyak) is False and len(said) == 1


def test_dock_says_why_it_cannot_trust_a_group_writable_checkout(tmp_path):
    superyak = checkout(tmp_path / 'superyak', ('reflect', {}))
    (superyak / '.superyak' / 'checklists').chmod(0o775)                      # a checkout made under umask 002
    said = []
    assert install.trust_checkout(tmp_path / 'home', said.append, checkout=superyak) is False
    assert len(said) == 1 and 'chmod -R go-w' in said[0] and not (tmp_path / 'home' / 'checklists' / 'trusted.json').exists()


def test_a_checkout_without_lists_says_so_in_one_line(tmp_path):                       # section 2's S5
    said = []
    assert install.trust_checkout(tmp_path / 'home', said.append, checkout=tmp_path / 'old-checkout') is False
    assert said == [f"This checkout has no checklists to trust: {tmp_path / 'old-checkout' / '.superyak' / 'checklists'} "
                    'is missing. Dock again once it has them.']
    assert not (tmp_path / 'home' / 'checklists').exists()


def test_trust_checkout_never_raises(tmp_path, monkeypatch):                           # plan review S7
    superyak = checkout(tmp_path / 'superyak', ('reflect', {}))

    def full(*a):
        raise OSError(28, 'No space left on device')
    monkeypatch.setattr(install, 'add_trusted', full)
    said = []
    assert install.trust_checkout(tmp_path / 'home', said.append, checkout=superyak) is False and len(said) == 1


def test_a_trusted_checkout_is_told_a_list_git_rewrites_under_umask_002_is_skipped(tmp_path):   # the final review's M6
    superyak = checkout(tmp_path / 'superyak', ('reflect', {}))
    said = []
    assert install.trust_checkout(tmp_path / 'home', said.append, checkout=superyak) is True
    assert len(said) == 1 and 'umask 002' in said[0] and 'skipped' in said[0] and '`chmod -R go-w`' in said[0]


def test_a_valid_trust_file_keeps_its_other_entries(tmp_path):                             # the final review's M7
    superyak = checkout(tmp_path / 'superyak', ('reflect', {}))
    other = checkout(tmp_path / 'other', ('mine', {})) / '.superyak' / 'checklists'
    home = tmp_path / 'home'
    trust_dirs(home / 'checklists', other)
    assert install.trust_checkout(home, [].append, checkout=superyak) is True
    assert json.loads((home / 'checklists' / 'trusted.json').read_text())['trusted'] == sorted(
        [os.path.realpath(other), os.path.realpath(superyak / '.superyak' / 'checklists')])


DAMAGED = {'not JSON': ('{"trusted": ["/kept/.superyak/checklists"', 0o600, 'not a JSON list of paths'),
           'the wrong shape': ('{"trusted": "/kept/.superyak/checklists"}', 0o600, 'not a JSON list of paths'),
           'nested too deep': ('[' * 100000, 0o600, 'not a JSON list of paths'),
           'group-writable': ('{"trusted": ["/kept/.superyak/checklists"]}', 0o620, 'writable by its group or by others'),
           'a symlink': (None, 0o600, 'a symlink')}


@pytest.mark.parametrize('case', DAMAGED)
def test_a_damaged_or_unsafe_trust_file_is_left_as_it_is_and_named(tmp_path, case):    # the final review's M7
    text, mode, why = DAMAGED[case]
    superyak = checkout(tmp_path / 'superyak', ('reflect', {}))
    own = tmp_path / 'home' / 'checklists'
    own.mkdir(parents=True)
    path = own / 'trusted.json'
    if text is None:
        (tmp_path / 'elsewhere.json').write_text('{"trusted": []}')
        os.symlink(tmp_path / 'elsewhere.json', path)
    else:
        path.write_text(text)
        os.chmod(path, mode)
    before = (os.readlink(path) if path.is_symlink() else path.read_bytes(), os.lstat(path).st_mode)
    said = []
    assert install.trust_checkout(tmp_path / 'home', said.append, checkout=superyak) is False
    assert len(said) == 1 and str(path) in said[0] and why in said[0] and 'left as it is' in said[0], said
    assert (os.readlink(path) if path.is_symlink() else path.read_bytes(), os.lstat(path).st_mode) == before
    with pytest.raises(OSError):                       # `checklists trust` reports an OSError and trusts nothing
        install.add_trusted(own, superyak / '.superyak' / 'checklists')
