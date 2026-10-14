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
    assert calls.read_text().splitlines() == ['--user daemon-reload',
                                              '--user enable --now superyak-backup.timer superyak-restore-test.timer']
    calls.unlink()
    removed = make('station-units-remove')
    assert removed.returncode == 0, removed.stderr
    assert sorted(str(path.relative_to(units)) for path in units.rglob('*')) == before
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
