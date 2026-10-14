"""Service alerts (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S9-S14; R10-R15). Every test
works in tmp_path with systemd's variables set by hand; none runs systemctl."""
import calendar
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import time
import pytest
from superyak_peer import alerts, backups
from superyak_peer.__main__ import main as cli
from superyak_peer.db import Store

SYSTEMD = ('SERVICE_RESULT', 'EXIT_CODE', 'EXIT_STATUS', 'INVOCATION_ID')
CRASH = {'result': 'exit-code', 'exit_code': 'exited', 'exit_status': '1'}
GIVE_UP = {'result': 'start-limit-hit', 'exit_code': None, 'exit_status': None}
T0 = calendar.timegm((2026, 10, 14, 2, 0, 0))
HOLD = ('import fcntl, os, sys, time\n'
        'fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR)\n'
        'fcntl.flock(fd, fcntl.LOCK_EX)\n'
        'print("held", flush=True)\n'
        'time.sleep(60)\n')


def under_systemd(monkeypatch, monitor=False, **values):
    """The variables systemd gives ExecStopPost= (or, with monitor, an OnFailure= handler); nothing else of systemd's."""
    for name in SYSTEMD:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f'MONITOR_{name}', raising=False)
    for name, value in values.items():
        monkeypatch.setenv(('MONITOR_' if monitor else '') + name.upper(), value)


def alert(data, unit, *extra):
    """station-alert as systemd runs it; returns its exit code."""
    try:
        cli(['station-alert', '--data-dir', str(data), '--unit', unit, *extra])
    except SystemExit as stopped:
        return stopped.code
    return 0


def files(data):
    """The queued alert files, read directly: [(path, alert)], oldest first."""
    queue = Path(data) / 'alerts'
    if not queue.is_dir():
        return []
    found = [(path, json.loads(path.read_text())) for path in queue.iterdir() if re.fullmatch(r'[0-9a-f]{12}\.json', path.name)]
    return sorted(found, key=lambda item: (item[1]['at'], item[0].name))


def local(at, fmt='%H:%M on %Y-%m-%d'):
    return time.strftime(fmt, time.localtime(at))


@pytest.fixture
def utc(monkeypatch):
    """Alert lines use the Pi's local zone, and a held-back time on another day gains its date; tests that compare a
    bare HH:MM run in UTC, so their times stay on one day wherever the suite runs."""
    monkeypatch.setenv('TZ', 'UTC')
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_a_crash_queues_one_alert_and_a_clean_stop_queues_none(tmp_path, monkeypatch):
    """R10: ExecStopPost= with a failing result queues one 0600 stopped alert in a 0700 queue; success queues nothing; a
    run outside systemd exits 2. The notifier deletes alert files over 30 days old each time it runs, clean stops
    included (S10, review N1)."""
    data = tmp_path / 'lighthouse'
    data.mkdir(mode=0o700)
    month_old = alerts.record(data / 'alerts', 'superyak-door.service', 'stopped', CRASH, time.time() - 31 * 86400)
    under_systemd(monkeypatch, service_result='exit-code', exit_code='exited', exit_status='1')
    assert alert(data, 'superyak-lighthouse.service') == 0
    [(path, one)] = files(data)
    assert one['id'] != month_old['id']
    assert (one['unit'], one['kind'], one['result'], one['exit_code'], one['exit_status'], one['held_back']) == (
        'superyak-lighthouse.service', 'stopped', 'exit-code', 'exited', '1', 0)
    assert one['text'] == (f'Station alert: superyak-lighthouse stopped unexpectedly at {local(one["at"])} (exit-code, status 1). '
                           'systemd restarts it unless it was being stopped. Log on the Pi: journalctl --user-unit '
                           f"superyak-lighthouse.service --since '{local(one['at'] - 600, '%Y-%m-%d %H:%M')}'.")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    alerts.record(data / 'alerts', 'superyak-odo.service', 'stopped', CRASH, time.time() - 40 * 86400)
    under_systemd(monkeypatch, service_result='success', exit_code='killed', exit_status='TERM')
    assert alert(data, 'superyak-door.service') == 0 and [found['id'] for _, found in files(data)] == [one['id']]
    under_systemd(monkeypatch)
    assert alert(data, 'superyak-lighthouse.service') == 2 and len(files(data)) == 1


def test_monitor_kinds(tmp_path, monkeypatch):
    """R10, S11: --monitor with start-limit-hit queues down for a service, and failed for the backup or restore-test
    unit. Without the MONITOR_* variables an OnFailure= run refuses with 2."""
    data = tmp_path / 'lighthouse'
    data.mkdir(mode=0o700)
    under_systemd(monkeypatch, monitor=True, service_result='start-limit-hit')
    for unit in ('superyak-odo.service', 'superyak-backup.service', 'superyak-restore-test.service'):
        assert alert(data, unit, '--monitor') == 0
    queued = {one['unit']: one for _, one in files(data)}
    assert {unit: one['kind'] for unit, one in queued.items()} == {
        'superyak-odo.service': 'down', 'superyak-backup.service': 'failed', 'superyak-restore-test.service': 'failed'}
    odo, nightly = queued['superyak-odo.service'], queued['superyak-backup.service']
    assert odo['text'] == (f'Station alert: superyak-odo is down since {local(odo["at"])}: systemd stopped restarting it '
                           "(start-limit-hit). Log on the Pi: journalctl --user-unit superyak-odo.service --since "
                           f"'{local(odo['at'] - 600, '%Y-%m-%d %H:%M')}'.")
    assert nightly['text'].startswith(f'Station alert: the nightly backup failed at {local(nightly["at"])}: see the log. ')
    assert queued['superyak-restore-test.service']['text'].startswith('Station alert: the monthly restore test failed at ')
    under_systemd(monkeypatch, service_result='start-limit-hit')
    assert alert(data, 'superyak-odo.service', '--monitor') == 2


REASON_CASES = [
    ('superyak-backup.service', 'exit-code', '10', 'not enough disk space'),
    ('superyak-backup.service', 'exit-code', '11', "the copy failed its check; tomorrow's run tries again"),
    ('superyak-backup.service', 'exit-code', '12', "the live database may be damaged: don't restart or deploy before reading docs/station-restore.md"),
    ('superyak-backup.service', 'exit-code', '13', 'the copy off the Pi failed'),
    ('superyak-backup.service', 'exit-code', '1', 'see the log'),
    ('superyak-restore-test.service', 'exit-code', '20', 'there is no backup to test'),
    ('superyak-restore-test.service', 'exit-code', '21', 'the newest copy failed its check'),
    ('superyak-restore-test.service', 'exit-code', '22', 'the restored station did not start'),
    ('superyak-restore-test.service', 'exit-code', '23', 'the restored station is missing data'),
    ('superyak-restore-test.service', 'exit-code', '24', "the restore's reconcile step failed"),
    ('superyak-restore-test.service', 'exit-code', '1', 'see the log'),
    ('superyak-backup.service', 'timeout', '', 'it ran past its time limit'),
    ('superyak-backup.service', 'signal', 'KILL', 'it was killed (KILL)'),
    ('superyak-restore-test.service', 'core-dump', 'SEGV', 'it was killed (SEGV)'),
    ('superyak-backup.service', 'oom-kill', 'KILL', 'it was killed (KILL)'),
]


@pytest.mark.parametrize('unit, result, status, reason', REASON_CASES)
def test_failed_backup_and_restore_runs_name_their_reason(tmp_path, monkeypatch, unit, result, status, reason):
    """R12: every exit code in the Error handling table, and the systemd results timeout, signal, core-dump and oom-kill,
    in the spec's words."""
    data = tmp_path / 'lighthouse'
    data.mkdir(mode=0o700)
    under_systemd(monkeypatch, monitor=True, service_result=result, exit_code='exited' if result == 'exit-code' else 'killed',
                  **({'exit_status': status} if status else {}))
    assert alert(data, unit, '--monitor') == 0
    [(_, failed)] = files(data)
    assert f': {reason}. The earlier copies are kept. Log on the Pi: journalctl --user-unit {unit} --since ' in failed['text']


def test_alert_lines_hold_no_log_lines_mentions_or_unchecked_values(tmp_path, monkeypatch):
    """R12: invalid units are refused with nothing queued; an unknown result becomes unknown; a secret in the environment
    reaches neither the file nor the text; no at sign and no newline."""
    data = tmp_path / 'lighthouse'
    data.mkdir(mode=0o700)
    under_systemd(monkeypatch, service_result='exit-code', exit_code='exited', exit_status='1')
    for unit in ('superyak-door', 'sshd.service', 'superyak-x@y.service', 'superyak-Door.service', '../superyak-door.service',
                 'superyak-door.service\nTraceback', 'superyak-' + 'a' * 61 + '.service'):
        assert alert(data, unit) == 2, unit
    assert files(data) == []
    monkeypatch.setenv('LIGHTHOUSE_ORIGIN', 'https://s3cret-origin.example')
    monkeypatch.setenv('SUPERYAK_SECRET', 's3cret-value')
    under_systemd(monkeypatch, service_result='exit-code @serenity', exit_code='exited\nTraceback (most recent call last)',
                  exit_status='s3cret-status', invocation_id='s3cret-invocation')
    assert alert(data, 'superyak-door.service') == 0
    [(path, one)] = files(data)
    raw = path.read_text()
    assert 's3cret' not in raw and 'Traceback' not in raw and '@' not in raw
    assert (one['result'], one['exit_code'], one['exit_status']) == ('unknown', None, None)
    assert '(unknown). ' in one['text'] and '\n' not in one['text'] and len(one['text']) <= 400


def test_a_notifier_that_cannot_write_its_queue_exits_0(tmp_path, monkeypatch, capsys):
    """Error handling: a queue it can't write (disk full, permissions) is said on stderr, which goes to the journal, and
    the exit is 0, so the unit's result doesn't change."""
    data = tmp_path / 'lighthouse'
    (data / 'alerts').mkdir(parents=True, mode=0o700)
    os.chmod(data / 'alerts', 0o500)
    under_systemd(monkeypatch, monitor=True, service_result='start-limit-hit')
    try:
        assert alert(data, 'superyak-odo.service', '--monitor') == 0
    finally:
        os.chmod(data / 'alerts', 0o700)
    assert 'could not queue the alert for superyak-odo.service' in capsys.readouterr().err
    assert files(data) == []


def test_stopped_alerts_are_held_back_and_back_off_per_unit(tmp_path, utc):
    """R11, with a fake clock: one stopped line per unit per window. The window doubles within an unbroken burst, up to
    6 hours, and a full window without a failure ends the burst. down is never windowed, up to 6 per unit in a day."""
    queue, ship = tmp_path / 'alerts', 'superyak-ship.service'

    def at(minutes):
        return T0 + minutes * 60

    six = [alerts.record(queue, ship, 'stopped', CRASH, at(m)) for m in (0, 2, 4, 6, 8, 10)]
    assert [one is not None for one in six] == [True, False, False, False, False, False]   # 6 crashes in 10 minutes: one file
    second = alerts.record(queue, ship, 'stopped', CRASH, at(31))
    assert (second['held_back'], second['held_since']) == (5, at(2))
    assert second['text'].endswith(f' 5 more stops since {local(at(2), "%H:%M")} were held back.')
    assert alerts.record(queue, ship, 'stopped', CRASH, at(61)) is None                     # the second window is 60 minutes
    assert alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, at(61)) is not None   # windows are per unit
    downs = [alerts.record(queue, ship, 'down', GIVE_UP, at(m)) for m in range(62, 69)]
    assert [one is not None for one in downs] == [True] * 6 + [False]                       # inside the window; the 7th held
    third = alerts.record(queue, ship, 'stopped', CRASH, at(121))                            # a full 60 minutes since 61
    assert third['held_back'] == 2                                                         # the stop at 61 and the 7th down
    assert third['text'].endswith(f' 2 more stops since {local(at(61), "%H:%M")} were held back.')
    assert alerts.record(queue, ship, 'stopped', CRASH, at(140)) is None                     # the burst ended: 30 minutes again,
    assert alerts.record(queue, ship, 'stopped', CRASH, at(152)) is not None                 # so 152 is past it
    loop = tmp_path / 'loop'                                                                 # a watcher crash-looping for a day
    posted = [m for m in range(0, 1440, 5) if alerts.record(loop, 'superyak-odo.service', 'stopped', CRASH, at(m))]
    assert posted == [0, 30, 90, 210, 450, 810, 1170]                                        # windows of 30, 60, 120, 240, 360, 360
    assert [m for m in posted if m < 480] == [0, 30, 90, 210, 450]                           # overnight: 5 lines, not 16


def test_the_lock_fallback_queues_anyway(tmp_path):
    """R11: with alerts/.lock held by another process, the alert is queued after 5 s, without the rate record: a
    duplicate beats a lost alert."""
    queue = tmp_path / 'alerts'
    queue.mkdir(mode=0o700)
    holder = subprocess.Popen([sys.executable, '-c', HOLD, str(queue / '.lock')], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'held'
        started = time.monotonic()
        one = alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, T0)
        waited = time.monotonic() - started
    finally:
        holder.kill()
        holder.wait()
    assert alerts.LOCK_WAIT == 5 and 5 <= waited < 8
    assert one is not None and [found['id'] for _, found in files(tmp_path)] == [one['id']]
    assert not (queue / 'rate.json').exists()


def test_a_cleaning_error_never_stops_the_alert_being_queued(tmp_path, monkeypatch, capsys):
    """Review of task 8, fix 1: clean() runs after record() in its own try. An error unlinking an old alert is said on
    stderr and the exit stays 0, but the failure's alert is queued."""
    def broken(alerts_dir, now):
        raise PermissionError(13, 'Permission denied')

    monkeypatch.setattr(alerts, 'clean', broken)
    under_systemd(monkeypatch, service_result='exit-code', exit_code='exited', exit_status='1')
    assert alert(tmp_path, 'superyak-door.service') == 0
    assert len(files(tmp_path)) == 1
    assert 'could not clean' in capsys.readouterr().err


def test_a_symlinked_alerts_directory_is_never_cleaned(tmp_path, monkeypatch, capsys):
    """Review of task 8, fix 2: clean() refuses a symlinked alerts directory, so it never unlinks files in the target."""
    target = tmp_path / 'elsewhere'
    target.mkdir()
    old = alerts.record(target, 'superyak-door.service', 'stopped', CRASH, time.time() - 40 * 86400)
    data = tmp_path / 'lighthouse'
    data.mkdir()
    (data / 'alerts').symlink_to(target)
    under_systemd(monkeypatch, service_result='exit-code', exit_code='exited', exit_status='1')
    assert alert(data, 'superyak-door.service') == 0
    assert (target / f'{old["id"]}.json').exists()
    assert [path.name for path in target.iterdir() if path.name != 'rate.json' and path.name != '.lock'] == [f'{old["id"]}.json']
    assert 'symlink' in capsys.readouterr().err


def test_an_existing_wide_alerts_directory_is_tightened_to_0700(tmp_path):
    """Review of task 8, fix 3: mkdir(exist_ok=True) leaves a wider mode in place, so the queue chmods it."""
    queue = tmp_path / 'alerts'
    queue.mkdir(mode=0o755)
    os.chmod(queue, 0o755)
    alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, T0)
    assert stat.S_IMODE(queue.stat().st_mode) == 0o700


def test_rate_json_and_the_lock_are_private_and_not_followed_through_symlinks(tmp_path):
    """The lock and the rate record follow the queue's rules: 0600, atomic, never through a symlink."""
    queue = tmp_path / 'alerts'
    alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, T0)
    for name in ('rate.json', '.lock'):
        assert stat.S_IMODE((queue / name).stat().st_mode) == 0o600
    victim = tmp_path / 'victim'
    victim.write_text('keep')
    (queue / '.lock').unlink()
    (queue / '.lock').symlink_to(victim)
    with pytest.raises(OSError):
        alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, T0 + 99999)
    assert victim.read_text() == 'keep'
    (queue / '.lock').unlink()
    (queue / 'rate.json').unlink()
    (queue / 'rate.json').symlink_to(victim)
    alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, T0 + 99999)
    assert victim.read_text() == 'keep' and not (queue / 'rate.json').is_symlink()
