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
             'superyak-restore-test.timer', 'superyak-imprint-sweep.service', 'superyak-imprint-sweep.timer',
             'superyak-alert@.service']
LESSONS_UNITS = ['superyak-lessons-index.service', 'superyak-lessons-index.timer']  # make lessons-units, on the Pi and Tardis
FEDERATION_UNITS = ['superyak-federate.service', 'superyak-federation-listen.service']  # make federation-units (plan SF10, SF11)
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
    'superyak-imprint-sweep.service': {
        'Unit': {'After': 'superyak-lighthouse.service', 'OnFailure': 'superyak-alert@%n.service'},
        'Service': {'Type': 'oneshot', 'WorkingDirectory': '%h/superyak/peer',
                    'ExecStart': f'{PYTHON} station-imprint-sweep --data-dir {DATA} --imprints-dir %h/.engram/imprints',
                    'Nice': '10', 'IOSchedulingClass': 'idle', 'TimeoutStartSec': '15min', 'MemoryMax': '512M', 'MemorySwapMax': '0',
                    'LimitDATA': '512M', 'Environment': 'OPENBLAS_NUM_THREADS=1'},   # the cap that holds where the user
                                                                # manager has no memory controller, and one BLAS thread (review I4)
    },
    'superyak-imprint-sweep.timer': {
        'Unit': {},
        'Timer': {'OnCalendar': 'hourly', 'Persistent': 'true'},
        'Install': {'WantedBy': 'timers.target'},
    },
    'superyak-alert@.service': {
        'Unit': {},
        'Service': {'Type': 'oneshot', 'TimeoutStartSec': '1min',
                    'ExecStart': f'{PYTHON} station-alert --data-dir {DATA} --unit %i --monitor'},
    },
    'superyak-lessons-index.service': {  # first rail section 4; LimitDATA, since the Pi has no memory cgroup
        'Unit': {'OnFailure': 'superyak-alert@%n.service'},
        'Service': {'Type': 'oneshot', 'WorkingDirectory': '%h/superyak/peer', 'EnvironmentFile': '%h/.config/superyak/lessons.env',
                    'ExecStart': '%h/superyak/peer/.venv/bin/python -I -m superyak_peer.lessons index --data-dir ${SUPERYAK_LESSONS_DATA}',
                    'Nice': '10', 'TimeoutStartSec': '5min', 'LimitDATA': '512M'},
    },
    'superyak-lessons-index.timer': {
        'Unit': {},
        'Timer': {'OnBootSec': '1min', 'OnUnitInactiveSec': '60s', 'AccuracySec': '5s'},
        'Install': {'WantedBy': 'timers.target'},
    },
    'superyak-federate.service': {  # federation pull plan SF10: long-running, restarted; the data dir from a drop-in
        'Unit': {'After': 'network-online.target superyak-lighthouse.service', 'Wants': 'network-online.target'},
        'Service': {'Type': 'simple', 'WorkingDirectory': '%h/superyak/peer', 'Environment': 'FEDERATION_DATA=%h/.local/share/superyak/lighthouse OPENBLAS_NUM_THREADS=1',
                    'ExecStart': f'{PYTHON} federate --data-dir ${{FEDERATION_DATA}}',
                    'Restart': 'on-failure', 'RestartSec': '30', 'MemoryMax': '256M', 'MemorySwapMax': '0'},
        'Install': {'WantedBy': 'default.target'},
    },
    'superyak-federation-listen.service': {
        'Unit': {'After': 'network-online.target superyak-lighthouse.service', 'Wants': 'network-online.target'},
        'Service': {'Type': 'simple', 'WorkingDirectory': '%h/superyak/peer', 'Environment': 'FEDERATION_DATA=%h/.local/share/superyak/lighthouse OPENBLAS_NUM_THREADS=1',
                    'ExecStart': f'{PYTHON} federation-listen --data-dir ${{FEDERATION_DATA}} --host 127.0.0.1 --port 7437',
                    'Restart': 'on-failure', 'RestartSec': '30', 'MemoryMax': '256M', 'MemorySwapMax': '0'},
        'Install': {'WantedBy': 'default.target'},
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
    assert sorted(path.name for path in UNITS.iterdir()) == sorted(INSTALLED + LESSONS_UNITS + FEDERATION_UNITS + ['50-alerts.conf'])
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
    files = [str(probe / name) for name in INSTALLED + LESSONS_UNITS + FEDERATION_UNITS + ['superyak-verifycheck.service']]
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
                'superyak-ship-serenity-bricks', 'superyak-federate', 'superyak-federation-listen']  # the last two: plan SF10
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
                                              '--user enable --now superyak-backup.timer superyak-restore-test.timer superyak-imprint-sweep.timer']
    calls.unlink()
    removed = make('station-units-remove')
    assert removed.returncode == 0, removed.stderr
    assert sorted(str(path.relative_to(units)) for path in units.rglob('*')) == before
    assert {path: path.read_bytes() for path in units.rglob('*') if path.is_file()} == contents
    assert andys.read_text() == '[Service]\nNice=5\n'
    assert stray.read_text() == '[Service]\nNice=7\n'
    assert calls.read_text().splitlines() == [
        '--user disable --now superyak-backup.timer superyak-restore-test.timer superyak-imprint-sweep.timer',
        '--user stop superyak-backup.service superyak-restore-test.service superyak-imprint-sweep.service',
        '--user reset-failed superyak-backup.service superyak-restore-test.service superyak-imprint-sweep.service superyak-alert@*',
        '--user daemon-reload']
    assert not (home / '.config').exists()


@pytest.mark.parametrize('name', ['superyak-backup.service', 'superyak-restore-test.service', 'superyak-imprint-sweep.service',
                                  'superyak-lessons-index.service'])
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


@pytest.mark.skipif(not (REPO / 'Makefile').is_file() or not shutil.which('make'), reason='needs the parent repository Makefile')
def test_lessons_units_install_and_remove_only_their_own_files(tmp_path):
    """First rail section 4: make lessons-units refuses without a peer database, installs the index service and timer,
    writes the data directory into lessons.env (0600) and starts the timer; make lessons-units-remove takes back exactly
    that. systemctl is shimmed on PATH and HOME is tmp_path."""
    units, data, home, shim = tmp_path / 'systemd-user', tmp_path / 'tardis peer', tmp_path / 'home', tmp_path / 'bin'
    for directory in (units, data, home, shim):
        directory.mkdir()
    (units / 'superyak-lighthouse.service').write_text('[Service]\nExecStart=/bin/true\n')
    calls = tmp_path / 'systemctl.log'
    (shim / 'systemctl').write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\n')
    (shim / 'systemctl').chmod(0o755)
    env = {**os.environ, 'HOME': str(home), 'PATH': f'{shim}:{os.environ["PATH"]}'}

    def make(target):
        return subprocess.run(['make', '-s', target, f'SYSTEMD_USER={units}', f'LESSONS_DATA={data}'], cwd=REPO, env=env,
                              capture_output=True, text=True, timeout=60)
    refused = make('lessons-units')
    assert refused.returncode != 0 and 'No peer database' in refused.stdout + refused.stderr and not calls.exists()
    (data / 'peer.sqlite3').write_bytes(b'')
    installed = make('lessons-units')
    assert installed.returncode == 0, installed.stderr
    for name in LESSONS_UNITS:
        assert (units / name).read_bytes() == (UNITS / name).read_bytes() and stat.S_IMODE((units / name).stat().st_mode) == 0o644
    written = home / '.config' / 'superyak' / 'lessons.env'
    assert written.read_text() == f'SUPERYAK_LESSONS_DATA={data}\n' and stat.S_IMODE(written.stat().st_mode) == 0o600
    assert calls.read_text().splitlines() == ['--user daemon-reload', '--user enable --now superyak-lessons-index.timer']
    calls.unlink()
    removed = make('lessons-units-remove')
    assert removed.returncode == 0, removed.stderr
    assert sorted(path.name for path in units.iterdir()) == ['superyak-lighthouse.service'] and not written.exists()
    assert calls.read_text().splitlines() == ['--user disable --now superyak-lessons-index.timer', '--user stop superyak-lessons-index.service',
                                              '--user reset-failed superyak-lessons-index.service', '--user daemon-reload']


@pytest.mark.skipif(not (REPO / 'Makefile').is_file() or not shutil.which('make'), reason='needs the parent repository Makefile')
@pytest.mark.parametrize('target, variables, verb', [
    ('station-lessons-room', ['ID=ab12', 'CONFIRM=0f0f0f0f'], ['station-room', '--data-dir', 'S', '--id', 'ab12', '--as', 'andy',
                                                             '--ship', 'rio-grande', '--confirm', '0f0f0f0f']),
    ('station-lessons-room', ['ID=ab12'], ['station-room', '--data-dir', 'S', '--id', 'ab12', '--as', 'andy', '--ship', 'rio-grande']),
    ('lessons-room', ['ID=x:y'], ['room', '--data-dir', 'L', '--id', 'x:y']),
    ('lessons-room', ['ID=x:y', 'CONFIRM=0f0f0f0f'], ['room', '--data-dir', 'L', '--id', 'x:y', '--confirm', '0f0f0f0f']),
    ('lessons-where', [], ['where', '--data-dir', 'L']),
    ('lessons-list', [], ['list', '--data-dir', 'L']),
    ('lessons-ship', ['SHIP=tardis', 'OWNER=andy'], ['ship', '--data-dir', 'L', '--username', 'tardis', '--owner', 'andy']),
    ('lesson-receipts', [], ['receipts', '--data-dir', 'L']),
    ('lesson-segments', [], ['segments', '--data-dir', 'L']),
    ('lesson-repeat', ['LESSON=ab12cd34-ef56ab78', 'HOW=read', 'HOOK=off'],
     ['repeat', '--data-dir', 'L', 'ab12cd34-ef56ab78', '--how', 'read', '--hook', 'off']),
    ('lesson-repeats', [], ['repeats', '--data-dir', 'L']),
])
def test_lessons_targets_run_the_lessons_command(tmp_path, target, variables, verb):
    """Each lessons target is one call of python -m superyak_peer.lessons; LESSONS_DATA defaults to STATION_DATA, and a
    path with a space stays one argument."""
    import shlex
    station, lessons_data = tmp_path / 'station data', tmp_path / 'peer data'
    done = subprocess.run(['make', '-n', '-s', target, *variables, f'STATION_DATA={station}', f'LESSONS_DATA={lessons_data}'],
                          cwd=REPO, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    command = shlex.split(done.stdout.strip().splitlines()[-1])
    expected = [{'S': str(station), 'L': str(lessons_data)}.get(word, word) for word in verb]
    assert command == ['uv', 'run', '--locked', '--project', 'peer', 'python', '-m', 'superyak_peer.lessons', *expected]
    default = subprocess.run(['make', '-n', '-s', 'lessons-where', f'STATION_DATA={station}'], cwd=REPO, capture_output=True, text=True)
    assert shlex.split(default.stdout.strip().splitlines()[-1])[-2:] == ['--data-dir', str(station)]   # on the Pi, the station's


@pytest.mark.skipif(not (REPO / 'Makefile').is_file() or not shutil.which('make'), reason='needs the parent repository Makefile')
def test_lessons_prompt_near_switches_near_at_a_prompt_and_timing_can_restart_the_embedder(tmp_path):
    """C44: NEAR=off leaves the switch file (0600) the prompt path looks for, NEAR=on removes it, anything else is
    refused; RESTART=1 makes the timing check restart the embedder after it builds its fixture (review S4)."""
    from superyak_peer.lessons import PROMPT_NEAR_OFF
    data = tmp_path / 'peer data'
    data.mkdir()

    def make(near):
        return subprocess.run(['make', '-s', 'lessons-prompt-near', f'NEAR={near}', f'LESSONS_DATA={data}'], cwd=REPO,
                              capture_output=True, text=True, timeout=60)
    assert make('maybe').returncode != 0 and not (data / PROMPT_NEAR_OFF).exists()
    assert make('off').returncode == 0 and stat.S_IMODE((data / PROMPT_NEAR_OFF).stat().st_mode) == 0o600
    assert make('on').returncode == 0 and not (data / PROMPT_NEAR_OFF).exists()
    timing = subprocess.run(['make', '-n', '-s', 'lessons-timing', 'RESTART=1'], cwd=REPO, capture_output=True, text=True, timeout=60)
    assert timing.stdout.strip().endswith('scripts/lessons_timing.py --restart-unit superyak-embedder')


@pytest.mark.skipif(not (REPO / 'Makefile').is_file() or not shutil.which('make'), reason='needs the parent repository Makefile')
def test_federation_units_install_and_remove_only_their_own_files(tmp_path):
    """Federation pull plan SF10, SF11: make federation-units refuses without a peer database, installs the two units and
    a drop-in naming the data dir (a space kept in one argument), adds the alert drop-in only where the station's alert
    unit is installed (its ExecStopPost writes into the station's database), and enables nothing: which unit runs where
    is the deploy's step. make federation-units-remove takes back exactly that, and leaves the alert unit."""
    units, data, home, shim = tmp_path / 'systemd-user', tmp_path / 'tardis peer', tmp_path / 'home', tmp_path / 'bin'
    for directory in (units, data, home, shim):
        directory.mkdir()
    (units / 'superyak-lighthouse.service').write_text('[Service]\nExecStart=/bin/true\n')
    calls = tmp_path / 'systemctl.log'
    (shim / 'systemctl').write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\n')
    (shim / 'systemctl').chmod(0o755)
    env = {**os.environ, 'HOME': str(home), 'PATH': f'{shim}:{os.environ["PATH"]}'}

    def make(target):
        return subprocess.run(['make', '-s', target, f'SYSTEMD_USER={units}', f'FEDERATION_DATA={data}'], cwd=REPO, env=env,
                              capture_output=True, text=True, timeout=60)

    def listing():
        return sorted(str(path.relative_to(units)) for path in units.rglob('*'))
    refused = make('federation-units')
    assert refused.returncode != 0 and 'No peer database' in refused.stdout + refused.stderr and not calls.exists()
    assert listing() == ['superyak-lighthouse.service']
    (data / 'peer.sqlite3').write_bytes(b'')
    installed = make('federation-units')
    assert installed.returncode == 0, installed.stderr
    for name in FEDERATION_UNITS:
        assert (units / name).read_bytes() == (UNITS / name).read_bytes() and stat.S_IMODE((units / name).stat().st_mode) == 0o644
        drop = units / f'{name}.d' / '20-federation-data.conf'
        assert drop.read_text() == f'[Service]\nEnvironment="FEDERATION_DATA={data}"\n' and stat.S_IMODE(drop.stat().st_mode) == 0o644
        assert not (units / f'{name}.d' / '50-alerts.conf').exists()        # not the station: no alert unit here
    assert calls.read_text().splitlines() == ['--user daemon-reload']      # nothing enabled
    (units / 'superyak-alert@.service').write_text('[Service]\nType=oneshot\nExecStart=/bin/true\n')
    assert make('federation-units').returncode == 0
    for name in FEDERATION_UNITS:
        assert (units / f'{name}.d' / '50-alerts.conf').read_bytes() == (UNITS / '50-alerts.conf').read_bytes()
    calls.unlink()
    removed = make('federation-units-remove')
    assert removed.returncode == 0, removed.stderr
    assert listing() == ['superyak-alert@.service', 'superyak-lighthouse.service']
    assert calls.read_text().splitlines() == ['--user disable --now superyak-federate.service superyak-federation-listen.service',
                                              '--user reset-failed superyak-federate.service superyak-federation-listen.service',
                                              '--user daemon-reload']


def test_the_restore_runbook_puts_the_federation_units_back_as_they_were():
    """Federation pull plan SF10 and Rio Grande's SF5: step 3 saves each federation unit's state with the watchers'
    (by pattern, so only installed ones), then disables and stops it, so a restart mid-restore can't start one writing
    into a half-restored database. Step 8 puts each back as it was, after the lighthouse. Nothing names the units
    elsewhere, so nothing enables one that isn't installed, or one Andy turned off."""
    lines = (REPO / 'docs' / 'station-restore.md').read_text().splitlines()
    [capture] = [text for text in lines if 'list-units --all --plain --no-legend' in text]
    assert "'superyak-ship-*'" in capture and "'superyak-federat*'" in capture
    assert [text for text in lines if 'superyak-federat' in text and 'systemctl' in text] == [capture]  # commands only
    lighthouse = lines.index('   systemctl --user start superyak-lighthouse superyak-door')
    restored = [n for n, text in enumerate(lines) if 'watchers.txt' in text and 'systemctl --user start "$unit"' in text]
    assert restored and restored[0] > lighthouse


def test_the_launchd_template_runs_federate_and_is_restarted_only_after_a_crash():
    """Federation pull plan SF10: the Mac's template, which Andy fills in and loads himself (law section 7)."""
    import plistlib
    plist = plistlib.loads((UNITS.parent / 'launchd' / 'superyak-federate.plist').read_bytes())
    assert plist['ProgramArguments'] == ['USER_HOME/superyak/peer/.venv/bin/python', '-I', '-m', 'superyak_peer', 'federate',
                                         '--data-dir', 'PEER_DATA']
    assert (plist['KeepAlive'], plist['ThrottleInterval'], plist['RunAtLoad']) == ({'SuccessfulExit': False}, 30, True)
