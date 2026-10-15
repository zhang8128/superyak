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
        one = alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, T0, lock_wait=0.5)
        waited = time.monotonic() - started
    finally:
        holder.kill()
        holder.wait()
    assert alerts.LOCK_WAIT == 5 and 0.5 <= waited < 3
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
    assert alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, T0 + 99999) is not None   # unlocked, not lost
    assert victim.read_text() == 'keep'
    (queue / '.lock').unlink()
    (queue / 'rate.json').unlink()
    (queue / 'rate.json').symlink_to(victim)
    alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, T0 + 99999)
    assert victim.read_text() == 'keep' and not (queue / 'rate.json').is_symlink()


def seed_rates(queue, unit, **state):
    """A rate.json as a clock step or a hand edit could leave it (json.dumps writes Infinity and NaN)."""
    queue.mkdir(mode=0o700, exist_ok=True)
    (queue / 'rate.json').write_text(json.dumps({unit: state}))


def test_a_future_until_or_give_up_never_holds_a_real_failure(tmp_path):
    """Review I1: timestamps are bounded by the clock. A clock that stepped back (no RTC), Infinity, NaN or 1e18 in
    rate.json must not hold stopped alerts or shut the give-up backstop. Catches: no clamp of until/last/give_ups in
    _state, or no non-finite check."""
    unit = 'superyak-door.service'
    for value in (T0 + 10 * 86400, float('inf'), float('nan'), 1e18, -float('inf')):
        queue = tmp_path / f'q{value}'
        seed_rates(queue, unit, window=1800, until=value, last=value)
        assert alerts.record(queue, unit, 'stopped', CRASH, T0) is not None, value
    queue = tmp_path / 'give-ups'
    seed_rates(queue, unit, give_ups=[T0 + 3600] * 6 + [float('nan'), 1e18])
    assert alerts.record(queue, unit, 'down', GIVE_UP, T0) is not None
    queue = tmp_path / 'window'
    seed_rates(queue, unit, window=float('inf'), until=0, last=T0 - 1)
    one = alerts.record(queue, unit, 'stopped', CRASH, T0)
    assert one is not None and json.loads((queue / 'rate.json').read_text())[unit]['until'] <= T0 + alerts.MAX_WINDOW


def test_a_wild_held_since_still_queues_readable_text(tmp_path, utc):
    """Review I1: held_since = 1e30 (a hand edit) can't make render raise. Catches: no bound on held/held_since in
    _state, and (for render called directly) no fallback in _local."""
    unit = 'superyak-door.service'
    queue = tmp_path / 'alerts'
    seed_rates(queue, unit, window=1800, until=T0 - 1, last=T0 - 5000, held=3, held_since=1e30)
    one = alerts.record(queue, unit, 'stopped', CRASH, T0)
    assert one is not None and one['text'].startswith('Station alert: superyak-door stopped')
    assert '\n' not in one['text'] and 'Traceback' not in one['text']
    assert (one['held_back'], one['held_since']) == (0, None)             # the wild value was dropped, not carried
    queue = tmp_path / 'nan'
    seed_rates(queue, unit, until=0, last=T0 - 5000, held=2, held_since=float('nan'))
    assert alerts.record(queue, unit, 'stopped', CRASH, T0)['held_since'] is None
    odd = dict(one, held_back=3, held_since=1e30)
    assert 'held back' in alerts.render(odd) or alerts.render(odd).startswith('Station alert')
    for held in (-4, 10**30, 'x', float('nan'), True):
        queue = tmp_path / f'h{held}'
        seed_rates(queue, unit, until=0, last=T0 - 5000, held=held, held_since=T0 - 60)
        assert alerts.record(queue, unit, 'stopped', CRASH, T0)['held_back'] in (0, 1_000_000)


@pytest.mark.parametrize('kind', ['symlink', 'directory'])
def test_a_bad_lock_never_loses_the_alert(tmp_path, kind):
    """Review M1: a symlinked or directory .lock is a lock that can't be taken: the alert goes out unlocked. Catches: an
    os.open error in _lock propagating."""
    queue = tmp_path / 'alerts'
    queue.mkdir(mode=0o700)
    victim = tmp_path / 'victim'
    victim.write_text('keep')
    if kind == 'symlink':
        (queue / '.lock').symlink_to(victim)
    else:
        (queue / '.lock').mkdir()
    one = alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, T0)
    assert one is not None and [found['id'] for _, found in files(tmp_path)] == [one['id']]
    assert victim.read_text() == 'keep' and not (queue / 'rate.json').exists()


def test_a_rate_json_that_cannot_be_written_never_loses_the_alert(tmp_path, capsys):
    """Review M2: the alert file is written before rate.json, and a failing rate write is said on stderr, not raised.
    Catches: writing rate.json first, or no try/except around the rate write."""
    queue = tmp_path / 'alerts'
    queue.mkdir(mode=0o700)
    (queue / 'rate.json').mkdir()
    one = alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, T0)
    assert one is not None and [found['id'] for _, found in files(tmp_path)] == [one['id']]
    assert 'rate' in capsys.readouterr().err


def test_a_failed_alert_write_leaves_no_window_set(tmp_path, monkeypatch):
    """Review M2: if the alert can't be written, the unit's window is not already set, so the next failure still queues.
    Catches: updating rate.json before the alert write."""
    queue = tmp_path / 'alerts'
    real = alerts._write_private

    def failing(path, data):
        if path.name != 'rate.json':
            raise OSError(28, 'No space left on device')
        real(path, data)

    monkeypatch.setattr(alerts, '_write_private', failing)
    with pytest.raises(OSError):
        alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, T0)
    monkeypatch.setattr(alerts, '_write_private', real)
    assert alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, T0 + 1) is not None


def notices(capsys, data, *extra):
    """station-notices as Odo runs it: (exit code, stdout, stderr)."""
    try:
        cli(['station-notices', '--data-dir', str(data), *map(str, extra)])
        code = 0
    except SystemExit as stopped:
        code = stopped.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_notices_list_queued_alerts_and_are_unchanged_without_them(tmp_path, capsys):
    """R13, R15: without an alert queue or a rotation the output is today's, byte for byte. With 25 stopped alerts and an
    older down, the store's notices come first, then the down and the 20 newest stops, oldest first."""
    store = Store(tmp_path / 'lighthouse')
    store.request_access('Jenn', 'jenn@example.org', 'Andy invited me')
    assert notices(capsys, store.data_dir) == (0, json.dumps(store.station_notices(), indent=2) + '\n', '')
    now, queue = time.time(), store.data_dir / 'alerts'
    down = alerts.record(queue, 'superyak-odo.service', 'down', GIVE_UP, now - 3600)
    stops = [alerts.record(queue, f'superyak-w{i:02d}.service', 'stopped', CRASH, now - (25 - i) * 60) for i in range(25)]
    alerts.record(queue, 'superyak-door.service', 'down', GIVE_UP, now - 8 * 86400)          # older than 7 days
    code, out, err = notices(capsys, store.data_dir)
    listed = json.loads(out)
    assert code == 0 and listed[:1] == store.station_notices()
    assert [notice['id'] for notice in listed[1:]] == [f'alert-{one["id"]}' for one in [down, *stops[5:]]]
    assert listed[1]['text'] == down['text']


def test_notices_still_list_alerts_when_the_store_cannot_open(tmp_path, capsys):
    """R13 (M3): the database overwritten with junk and one alert queued: the alert is listed, the error's class name goes
    to stderr, and the exit is 0. Without either directory the failure is today's."""
    store = Store(tmp_path / 'lighthouse')
    store.db_path.write_bytes(b'not a database ' * 1000)
    with pytest.raises(sqlite3.DatabaseError):
        notices(capsys, store.data_dir)
    one = alerts.record(store.data_dir / 'alerts', 'superyak-lighthouse.service', 'stopped', CRASH, time.time())
    code, out, err = notices(capsys, store.data_dir)
    assert code == 0 and json.loads(out) == [{'id': f'alert-{one["id"]}', 'text': one['text']}]
    assert 'DatabaseError' in err


def test_a_stale_backup_is_announced_once_per_lapse(tmp_path, capsys):
    """R14: a rotation whose newest copy is more than 36 hours old gives one backup-stale-<name> notice, the same on
    every listing; a new copy ends the lapse; no rotation, or an empty one, gives none."""
    data, rotation = tmp_path / 'lighthouse', tmp_path / 'backups' / 'station'
    data.mkdir()
    now = calendar.timegm((2026, 10, 14, 12, 0, 0))

    def copy(at):
        path = rotation / f'peer-{backups.copy_stamp(at)}.sqlite3'
        path.write_bytes(b'copy')
        return path

    assert alerts.notices_beside(data, rotation, now) is None
    rotation.mkdir(parents=True)
    (rotation / 'peer-20261399T000000Z.sqlite3').write_bytes(b'not a time')   # review S1: never the newest copy
    assert alerts.notices_beside(data, rotation, now) == []
    old = copy(now - 36 * 3600)
    assert alerts.notices_beside(data, rotation, now) == []                         # exactly 36 hours: not more than
    first = alerts.notices_beside(data, rotation, now + 60)
    assert first == [{'id': f'backup-stale-{old.name}', 'text': (
        f'Station alert: the newest station backup is from {local(now - 36 * 3600, "%Y-%m-%d %H:%M")}, more than 36 hours '
        'ago. The nightly timer may have stopped. On the Pi: systemctl --user list-timers superyak-backup.timer.')}]
    assert alerts.notices_beside(data, rotation, now + 3600) == first               # once per lapse: the same id
    new = copy(now + 3600)
    assert alerts.notices_beside(data, rotation, now + 7200) == []
    assert [n['id'] for n in alerts.notices_beside(data, rotation, now + 3600 + 37 * 3600)] == [f'backup-stale-{new.name}']
    Store(data)                                                                       # the command, with the real clock
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    real = elsewhere / f'peer-{backups.copy_stamp(time.time() - 40 * 3600)}.sqlite3'
    real.write_bytes(b'copy')
    code, out, err = notices(capsys, data, '--backup-dir', elsewhere)
    assert code == 0 and json.loads(out)[-1]['id'] == f'backup-stale-{real.name}'


def test_a_junk_file_in_the_queue_is_skipped_not_fatal(tmp_path, capsys):
    """Review Focus 5: an empty alert file (a power cut after a rename), a half-written one, a hand-edited one with an at
    sign, and a garbled rate.json. station-notices skips what it can't read, lists the rest without the at sign and exits
    0, because Odo runs it with check=True; the next alert still queues. A rate.json of the wrong shape loses no alert
    and doesn't break station-alerts (review S2)."""
    store = Store(tmp_path / 'lighthouse')
    queue = store.data_dir / 'alerts'
    good = alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, time.time())
    (queue / '000000000000.json').write_bytes(b'')
    (queue / 'abcdefabcdef.json').write_text('{"id": "abcdefabcdef", "unit": ')
    edited = {'id': '0123456789ab', 'unit': 'superyak-odo.service', 'kind': 'down', 'at': time.time() + 1, 'text': 'run this @serenity'}
    (queue / '0123456789ab.json').write_text(json.dumps(edited))
    (queue / 'rate.json').write_text('not json')
    code, out, err = notices(capsys, store.data_dir)
    assert code == 0 and [notice['id'] for notice in json.loads(out)] == [f'alert-{good["id"]}', 'alert-0123456789ab']
    assert '@' not in out
    assert alerts.record(queue, 'superyak-lighthouse.service', 'stopped', CRASH, time.time()) is not None
    wrong = {'superyak-door.service': {'until': 'x', 'window': 'y', 'held': 'z', 'held_since': 'w', 'give_ups': 'v'}}
    (queue / 'rate.json').write_text(json.dumps(wrong))
    assert 'Nothing is held back.' in alerts.describe_queue(queue, time.time())
    assert alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, time.time()) is not None
    assert alerts.record(queue, 'superyak-door.service', 'down', GIVE_UP, time.time()) is not None


def test_station_alerts_shows_the_queue_and_what_is_held_back(tmp_path, capsys):
    """S13, and the words Deploy steps 4 and 5 check: 'No alerts are queued.', then 'N stops held back'."""
    data = tmp_path / 'lighthouse'
    data.mkdir()
    cli(['station-alerts', '--data-dir', str(data)])
    assert capsys.readouterr().out == 'No alerts are queued.\nNothing is held back.\n'
    queue = data / 'alerts'
    first = alerts.record(queue, 'superyak-alerttest.service', 'stopped', CRASH, time.time() - 30)
    for seconds in (20, 10, 5):
        alerts.record(queue, 'superyak-alerttest.service', 'stopped', CRASH, time.time() - seconds)
    cli(['station-alerts', '--data-dir', str(data)])
    out = capsys.readouterr().out
    assert f'stopped  superyak-alerttest.service  {first["id"]}' in out
    assert 'superyak-alerttest.service: 3 stops held back since ' in out


def hand_made(queue, name, **fields):
    """An alert file as a person might write it: the shape of ours with fields changed."""
    body = {'id': name, 'unit': 'superyak-odo.service', 'kind': 'down', 'at': time.time(), 'text': 'Odo gave up'} | fields
    (queue / f'{name}.json').write_text(json.dumps(body).replace('"INF"', 'Infinity').replace('"-INF"', '-Infinity').replace('"NAN"', 'NaN'))
    return queue / f'{name}.json'


def test_an_alert_with_a_non_finite_time_is_skipped_and_cleaned(tmp_path, capsys):
    """Follow-up 6 (I1, M4, M5): a hand-made "at" that is Infinity, -Infinity, NaN, true, an integer too big for a float,
    1e300 or more than a day ahead is not an alert. queued() skips it, so station-alerts (describe_queue), station-notices
    and clean() don't raise on it (Odo runs station-notices with check=True), and clean() removes it once the file is
    over 30 days old by its own mtime, as it never could by "at". A valid, recent alert whose file is old stays.
    Mutations: the number check dropped (queued skips nothing); `_number` replaced by isfinite() alone (the big integer
    raises OverflowError); the bool exclusion dropped (true is read as 1); the day-ahead rule dropped (1e300 and
    tomorrow's-after stay queued); clean() deleting a kept alert."""
    store = Store(tmp_path / 'lighthouse')
    queue = store.data_dir / 'alerts'
    now = time.time()
    good = alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, now)
    values = {'INF': 'INF', 'NINF': '-INF', 'NAN': 'NAN', 'BIG': 10 ** 400, 'TRUE': True, 'HUGE': 1e300, 'AHEAD': now + 2 * 86400}
    odd = {name: hand_made(queue, f'{index:012x}', at=value) for index, (name, value) in enumerate(values.items(), 1)}
    recent_but_old_file = hand_made(queue, 'f' * 12, at=now - 60)           # valid and recent; only its file is old
    old = now - 40 * 86400
    os.utime(recent_but_old_file, (old, old))
    assert [alert['id'] for alert in alerts.queued(queue)] == ['f' * 12, good['id']]
    assert good['id'] in alerts.describe_queue(queue, time.time())
    code, out, err = notices(capsys, store.data_dir)
    assert code == 0 and [notice['id'] for notice in json.loads(out)] == ['alert-' + 'f' * 12, f'alert-{good["id"]}'], err
    alerts.clean(queue, time.time())
    assert all(path.exists() for path in odd.values())                  # fresh files may be mid-write: not cleaned yet
    for path in odd.values():
        os.utime(path, (old, old))
    alerts.clean(queue, time.time())
    assert not any(path.exists() for path in odd.values())
    assert recent_but_old_file.exists() and (queue / f'{good["id"]}.json').exists()      # a valid alert is never cleaned by its mtime


def test_an_alert_whose_text_sanitises_to_nothing_is_not_listed(tmp_path, capsys):
    """Follow-up 6: text of only invisible characters shows as an empty notice. listed() skips it. Mutation: the empty
    check dropped (the notice is listed with empty text)."""
    store = Store(tmp_path / 'lighthouse')
    queue = store.data_dir / 'alerts'
    good = alerts.record(queue, 'superyak-door.service', 'stopped', CRASH, time.time())
    hand_made(queue, 'dddddddddddd', text='​‮ ​')
    hand_made(queue, 'eeeeeeeeeeee', text='')
    code, out, err = notices(capsys, store.data_dir)
    assert code == 0 and [notice['id'] for notice in json.loads(out)] == [f'alert-{good["id"]}']
    assert all(notice['text'] for notice in alerts.listed(queue, time.time()))


def test_an_empty_newest_alert_does_not_take_one_of_the_twenty_places(tmp_path, capsys):
    """M5: twenty stopped alerts and, newest of all, one whose text sanitises to nothing. The empty one is dropped before
    the cut to the 20 newest, so all twenty real ones are listed. Mutation: the filter after the cut (nineteen listed)."""
    store = Store(tmp_path / 'lighthouse')
    queue = store.data_dir / 'alerts'
    now = time.time()
    queue.mkdir(mode=0o700)
    real = [hand_made(queue, f'{index:012x}', kind='stopped', at=now - 1000 + index, text=f'stop {index}') for index in range(20)]
    hand_made(queue, 'f' * 12, kind='stopped', at=now - 1, text='\u200b')
    listed = alerts.listed(queue, now)
    assert [item['text'] for item in listed] == [f'stop {index}' for index in range(20)] and len(real) == 20
