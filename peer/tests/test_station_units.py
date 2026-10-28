"""The station's units, timers and alert drop-in (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md,
S8, S9; R16, R17). Nothing here runs the real systemctl or touches ~/.config/systemd/user."""
import configparser
import os
from pathlib import Path
import shutil
import stat
import subprocess
import pytest

UNITS = Path(__file__).resolve().parents[1] / 'systemd'
REPO = Path(__file__).resolve().parents[2]
PYTHON = '%h/superyak/peer/.venv/bin/python -I -m superyak_peer'
DATA = '%h/.local/share/superyak/lighthouse'
ROTATION = '%h/.local/share/superyak/backups/station'
INSTALLED = ['superyak-backup.service', 'superyak-backup.timer', 'superyak-restore-test.service',
             'superyak-restore-test.timer', 'superyak-alert@.service']
EXPECTED = {
    'superyak-backup.service': {
        'Unit': {'After': 'superyak-lighthouse.service', 'OnFailure': 'superyak-alert@%n.service'},
        'Service': {'Type': 'oneshot', 'WorkingDirectory': '%h/superyak/peer',
                    'EnvironmentFile': '-%h/.config/superyak/backup.env',
                    'ExecStart': f'{PYTHON} station-backup --data-dir {DATA} --backup-dir {ROTATION} --copy-to=${{SUPERYAK_BACKUP_COPY_TO}}',
                    'Nice': '10', 'IOSchedulingClass': 'idle', 'TimeoutStartSec': '15min', 'MemoryMax': '512M'},
    },
    'superyak-backup.timer': {
        'Unit': {},
        'Timer': {'OnCalendar': '*-*-* 03:30:00', 'RandomizedDelaySec': '30min', 'Persistent': 'true'},
        'Install': {'WantedBy': 'timers.target'},
    },
    'superyak-restore-test.service': {
        'Unit': {'After': 'superyak-backup.service', 'OnFailure': 'superyak-alert@%n.service'},
        'Service': {'Type': 'oneshot', 'WorkingDirectory': '%h/superyak/peer',
                    'ExecStart': f'{PYTHON} station-restore-test --backup-dir {ROTATION}',
                    'TimeoutStartSec': '10min', 'MemoryMax': '1G'},
    },
    'superyak-restore-test.timer': {
        'Unit': {},
        'Timer': {'OnCalendar': '*-*-01 04:30:00', 'RandomizedDelaySec': '30min', 'Persistent': 'true'},
        'Install': {'WantedBy': 'timers.target'},
    },
    'superyak-alert@.service': {
        'Unit': {},
        'Service': {'Type': 'oneshot', 'TimeoutStartSec': '1min',
                    'ExecStart': f'{PYTHON} station-alert --data-dir {DATA} --unit %i --monitor'},
    },
    '50-alerts.conf': {
        'Unit': {'OnFailure': 'superyak-alert@%n.service'},
        'Service': {'ExecStopPost': f'-{PYTHON} station-alert --data-dir {DATA} --unit %n'},
    },
}


def sections(name):
    """A unit file as {section: {key: value}}, Description (free text) left out."""
    parser = configparser.ConfigParser(interpolation=None, strict=True, delimiters=('=',))
    parser.optionxform = str
    parser.read_string((UNITS / name).read_text())
    return {section: {key: value for key, value in parser[section].items() if key != 'Description'} for section in parser.sections()}


def test_units_say_what_the_spec_says():
    """R16: the timers (OnCalendar, Persistent=true, WantedBy=timers.target), the oneshots (OnFailure=, no Restart=),
    the alert template (%i, no OnFailure= of its own) and the drop-in (ExecStopPost=- with -I) are exactly S8's and S9's."""
    assert sorted(path.name for path in UNITS.iterdir()) == sorted(INSTALLED + ['50-alerts.conf'])
    for name, expected in EXPECTED.items():
        assert sections(name) == expected, name


VENV_PYTHON = Path.home() / 'superyak' / 'peer' / '.venv' / 'bin' / 'python'


@pytest.mark.skipif(not VENV_PYTHON.exists() or not shutil.which('systemd-analyze'),
                    reason='verify fails on the missing %h/superyak/peer/.venv/bin/python away from the station host')
def test_units_pass_systemd_analyze_verify(tmp_path):
    """R16, spec Testing: systemd-analyze --user verify passes, with no warning, on the units and on a throwaway service
    carrying the drop-in. It only parses: nothing is loaded into the user manager."""
    probe = tmp_path / 'units'
    shutil.copytree(UNITS, probe)
    (probe / 'superyak-verifycheck.service').write_text('[Unit]\nDescription=Throwaway unit for the drop-in\n\n[Service]\nExecStart=/bin/true\n')
    (probe / 'superyak-verifycheck.service.d').mkdir()
    shutil.move(probe / '50-alerts.conf', probe / 'superyak-verifycheck.service.d' / '50-alerts.conf')
    files = [str(probe / name) for name in INSTALLED + ['superyak-verifycheck.service']]
    result = subprocess.run(['systemd-analyze', '--user', 'verify', *files], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0 and result.stderr == '', result.stderr


@pytest.mark.skipif(not (REPO / 'Makefile').is_file() or not shutil.which('make'), reason='needs the parent repository Makefile')
def test_station_units_install_and_remove_only_their_own_files(tmp_path):
    """Review Focus 2: make station-units and station-units-remove on a stand-in for ~/.config/systemd/user, with
    systemctl shimmed on PATH and HOME in tmp_path. They refuse without a station database, install the five files and the
    drop-in on the five services and a project ship's watcher, and remove exactly that, keeping Andy's own drop-in."""
    units, data, home, shim = tmp_path / 'systemd-user', tmp_path / 'lighthouse', tmp_path / 'home', tmp_path / 'bin'
    for directory in (units, data, home, shim):
        directory.mkdir()
    services = ['superyak-lighthouse', 'superyak-door', 'superyak-ship', 'superyak-odo', 'superyak-wormhole',
                'superyak-ship-serenity-bricks']
    for service in services:
        (units / f'{service}.service').write_text('[Service]\nExecStart=/bin/true\n')
    andys = units / 'superyak-door.service.d' / '10-andy.conf'
    andys.parent.mkdir(mode=0o700)          # an existing directory keeps its mode (review N2)
    andys.write_text('[Service]\nNice=5\n')
    stray = units / 'superyak-other.service.d' / '50-alerts.conf'      # not a service the install names: remove leaves it (review M8)
    stray.parent.mkdir()
    stray.write_text('[Service]\nNice=7\n')
    calls = tmp_path / 'systemctl.log'
    (shim / 'systemctl').write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\n')
    (shim / 'systemctl').chmod(0o755)
    env = {**os.environ, 'HOME': str(home), 'PATH': f'{shim}:{os.environ["PATH"]}'}

    def make(target):
        return subprocess.run(['make', '-s', target, f'SYSTEMD_USER={units}', f'STATION_DATA={data}'], cwd=REPO, env=env,
                              capture_output=True, text=True, timeout=60)

    before = sorted(str(path.relative_to(units)) for path in units.rglob('*'))
    contents = {path: path.read_bytes() for path in units.rglob('*') if path.is_file()}   # R16: compared by bytes, not by name
    refused = make('station-units')
    assert refused.returncode != 0 and 'No station database' in refused.stdout + refused.stderr
    assert sorted(str(path.relative_to(units)) for path in units.rglob('*')) == before and not calls.exists()
    (data / 'peer.sqlite3').write_bytes(b'')
    installed = make('station-units')
    assert installed.returncode == 0, installed.stderr
    for name in INSTALLED:
        assert (units / name).read_bytes() == (UNITS / name).read_bytes()
        assert stat.S_IMODE((units / name).stat().st_mode) == 0o644
    for service in services:
        assert (units / f'{service}.service.d' / '50-alerts.conf').read_bytes() == (UNITS / '50-alerts.conf').read_bytes()
    assert stat.S_IMODE(andys.parent.stat().st_mode) == 0o700
    assert {path: path.read_bytes() for path in contents} == contents      # R16: no existing unit or drop-in is edited
    assert calls.read_text().splitlines() == ['--user daemon-reload',
                                              '--user enable --now superyak-backup.timer superyak-restore-test.timer']
    calls.unlink()
    removed = make('station-units-remove')
    assert removed.returncode == 0, removed.stderr
    assert sorted(str(path.relative_to(units)) for path in units.rglob('*')) == before
    assert {path: path.read_bytes() for path in units.rglob('*') if path.is_file()} == contents
    assert andys.read_text() == '[Service]\nNice=5\n'
    assert stray.read_text() == '[Service]\nNice=7\n'
    assert calls.read_text().splitlines() == [
        '--user disable --now superyak-backup.timer superyak-restore-test.timer',
        '--user stop superyak-backup.service superyak-restore-test.service',
        '--user reset-failed superyak-backup.service superyak-restore-test.service superyak-alert@*',
        '--user daemon-reload']
    assert not (home / '.config').exists()


@pytest.mark.parametrize('name', ['superyak-backup.service', 'superyak-restore-test.service'])
def test_no_exit_code_is_masked(name):
    """Any non-zero exit is a failure: the backup exits 10-13, the restore test 20-24 and 1 for the unexpected. The units
    declare no SuccessExitStatus= (or Restart=), and ExecStart= has no '-', '@', ':', '+' or '!' prefix, so systemd's SERVICE_RESULT is non-success and station-alert fires for every non-zero exit."""
    service = sections(name)['Service']
    forbidden = {'SuccessExitStatus', 'ExecStartPre', 'ExecStartPost', 'Restart', 'RestartForceExitStatus'}
    assert not forbidden & set(service), name
    assert service['ExecStart'].startswith('%h/'), name


MAKE_VARIABLES = ('DB', 'REPLACED', 'UNPAIR', 'OUTPUT', 'BACKUP', 'STATION_DATA', 'STATION_BACKUPS', 'MAKEFLAGS', 'MFLAGS',
                  'MAKELEVEL')
CLI = ['uv', 'run', '--locked', '--project', 'peer', 'python', '-m', 'superyak_peer']


@pytest.mark.skipif(not (REPO / 'Makefile').is_file() or not shutil.which('make'), reason='needs the parent repository Makefile')
def test_by_hand_targets_run_the_same_commands(tmp_path):
    """R17 (final review M6): make -n of station-backup [OUTPUT=], station-restore-test [BACKUP=],
    station-restore-reconcile DB= [REPLACED=] [UNPAIR=] and station-alerts. Paths with a space stay one argument, the
    reconcile always gets --live-data-dir "$(STATION_DATA)", and each UNPAIR= id is its own --unpair. Without DB= the
    reconcile stops at its usage line before uv runs. Mutations: drop --live-data-dir; drop the quotes around $(DB);
    drop the UNPAIR expansion."""
    import shlex
    root = tmp_path / 'a b'
    data, rotation = root / 'lighthouse', root / 'backups' / 'station'
    env = {name: value for name, value in os.environ.items() if name not in MAKE_VARIABLES}

    def make(*args, dry=True):
        return subprocess.run(['make', '--no-print-directory', *(['-n'] if dry else []), *args, f'STATION_DATA={data}',
                               f'STATION_BACKUPS={rotation}'], cwd=REPO, env=env, capture_output=True, text=True, timeout=60)

    def commands(*args):
        made = make(*args)
        assert made.returncode == 0, made.stderr
        return [shlex.split(line) for line in made.stdout.splitlines()]

    staged, replaced, output, chosen = (root / name for name in ('restored.sqlite3', 'peer.sqlite3', 'out.sqlite3', 'chosen.sqlite3'))
    assert commands('station-backup') == [CLI + ['station-backup', '--data-dir', str(data), '--backup-dir', str(rotation)]]
    assert commands('station-backup', f'OUTPUT={output}') == [
        CLI + ['station-backup', '--data-dir', str(data), '--backup-dir', str(rotation), '--output', str(output)]]
    assert commands('station-restore-test') == [CLI + ['station-restore-test', '--backup-dir', str(rotation)]]
    assert commands('station-restore-test', f'BACKUP={chosen}') == [
        CLI + ['station-restore-test', '--backup-dir', str(rotation), '--backup', str(chosen)]]
    assert commands('station-alerts') == [CLI + ['station-alerts', '--data-dir', str(data)]]
    reconcile = CLI + ['station-restore-reconcile', '--db', str(staged), '--live-data-dir', str(data)]
    usage = commands('station-restore-reconcile', f'DB={staged}')[0]
    assert usage[:3] == ['test', '-n', str(staged)]
    assert commands('station-restore-reconcile', f'DB={staged}')[1:] == [reconcile]
    assert commands('station-restore-reconcile', f'DB={staged}', f'REPLACED={replaced}', 'UNPAIR=abcdef012345 ' + 'ab' * 32)[1:] == [
        reconcile + ['--replaced', str(replaced), '--unpair', 'abcdef012345', '--unpair', 'ab' * 32]]
    refused = make('station-restore-reconcile', dry=False)
    assert refused.returncode == 2 and refused.stdout.startswith('Usage: make station-restore-reconcile DB=')


@pytest.mark.skipif(not (REPO / 'Makefile').is_file() or not shutil.which('make'), reason='needs the parent repository Makefile')
def test_station_moderate_ignores_exported_hours_budget_and_actions_but_takes_the_command_line():
    """An exported HOURS, BUDGET or ACTIONS must not silently change a grant; the make command line still wins."""
    env = {**os.environ, 'HOURS': '1', 'BUDGET': '1', 'ACTIONS': 'kick'}
    base = ['make', '-n', '-C', str(REPO), 'station-moderate', 'ID=abc123', 'GRANTEE=rio-grande']
    plain = subprocess.run(base, capture_output=True, text=True, env=env, check=True).stdout
    assert '--hours "720" --budget "10" --actions "add,remove"' in plain
    typed = subprocess.run([*base, 'HOURS=5'], capture_output=True, text=True, env=env, check=True).stdout
    assert '--hours "5" --budget "10"' in typed
