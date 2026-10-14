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
