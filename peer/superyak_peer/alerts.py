"""Service alerts (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S9-S14): one checked line per
failure, queued as a private file that station-notices lists and Odo posts once in Ops. Standard library only. The
notifier reads nothing from the environment but systemd's result variables, and never a journal line (S11)."""
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
from .backups import REASONS, SEE_LOG
from .ships import safe_line

UNIT = re.compile(r'superyak-[a-z0-9-]{1,60}\.service')
RESULTS = frozenset({'success', 'protocol', 'timeout', 'exit-code', 'signal', 'core-dump', 'watchdog', 'start-limit-hit',
                     'resources', 'oom-kill'})
STATUS = re.compile(r'[0-9]{1,3}|[A-Z0-9+]{1,16}')
EXIT_CODES = frozenset({'exited', 'killed', 'dumped'})
KILLED = frozenset({'signal', 'core-dump', 'oom-kill'})
TIMER_UNITS = {'superyak-backup.service': 'the nightly backup', 'superyak-restore-test.service': 'the monthly restore test'}
ALERT_FILE = re.compile(r'([0-9a-f]{12})\.json')
KINDS = ('stopped', 'down', 'failed')
KEPT_DAYS = 30
SINCE_BEFORE = 600
LINE_LIMIT = 400
DAY = 86400


class Refused(Exception):
    """Exit 2 (Error handling): a run outside systemd, or an invalid unit. Nothing is queued."""


def systemd_fields(environ, monitor):
    """S11: only SERVICE_RESULT, EXIT_CODE and EXIT_STATUS (their MONITOR_* forms for an OnFailure= handler), each
    checked. Nothing else is read from the environment."""
    prefix = 'MONITOR_' if monitor else ''
    result = environ.get(prefix + 'SERVICE_RESULT')
    if result is None:
        raise Refused(f'station-alert runs under systemd only: {prefix}SERVICE_RESULT is not set')
    code, status = environ.get(prefix + 'EXIT_CODE'), environ.get(prefix + 'EXIT_STATUS')
    return {'result': result if result in RESULTS else 'unknown',
            'exit_code': code if code in EXIT_CODES else None,
            'exit_status': status if status is not None and STATUS.fullmatch(status) else None}


def kind_for(unit, monitor):
    """S11: ExecStopPost= gives stopped; --monitor gives failed for the backup and restore-test units, down otherwise."""
    if not monitor:
        return 'stopped'
    return 'failed' if unit in TIMER_UNITS else 'down'


def _local(at, fmt='%H:%M on %Y-%m-%d'):
    """S11: times in the Pi's local zone, with the date."""
    return time.strftime(fmt, time.localtime(at))


def failure_reason(alert):
    """S11: the reason from the exit code (Error handling), or the words for a systemd result."""
    result, status = alert['result'], alert['exit_status']
    if result == 'exit-code' and status and status.isdigit():
        return REASONS.get(int(status), SEE_LOG)
    if result == 'timeout':
        return 'it ran past its time limit'
    if result in KILLED:
        return f'it was killed ({status})' if status else 'it was killed'
    return SEE_LOG


def render(alert):
    """S11's templates. Every value was checked before it got here, and the line still goes through safe_line."""
    unit, at = alert['unit'], alert['at']
    since = min(at, alert['held_since'] or at) - SINCE_BEFORE  # 10 minutes before the earliest failure it reports
    log = f"Log on the Pi: journalctl --user-unit {unit} --since '{_local(since, '%Y-%m-%d %H:%M')}'."
    when, name = _local(at), unit.removesuffix('.service')
    if alert['kind'] == 'stopped':
        status = f", status {alert['exit_status']}" if alert['exit_status'] else ''
        line = (f'Station alert: {name} stopped unexpectedly at {when} ({alert["result"]}{status}). '
                f'systemd restarts it unless it was being stopped. {log}')
        held = alert['held_back']
        if held:
            first = alert['held_since']
            day = _local(first, '%H:%M') if _local(first, '%Y-%m-%d') == _local(at, '%Y-%m-%d') else _local(first)
            line += f' {held} more {"stop" if held == 1 else "stops"} since {day} {"was" if held == 1 else "were"} held back.'
    elif alert['kind'] == 'down':
        line = f'Station alert: {name} is down since {when}: systemd stopped restarting it ({alert["result"]}). {log}'
    else:
        line = f'Station alert: {TIMER_UNITS[unit]} failed at {when}: {failure_reason(alert)}. The earlier copies are kept. {log}'
    return safe_line(line, LINE_LIMIT)


def _queue_dir(alerts_dir):
    """S10: <data-dir>/alerts/, 0700; never a symlink."""
    alerts_dir = Path(alerts_dir)
    if alerts_dir.is_symlink():
        raise OSError(f'{alerts_dir} is a symlink')
    alerts_dir.mkdir(mode=0o700, exist_ok=True)
    return alerts_dir


def _write_private(path, data):
    """A 0600 file through a temporary file and a rename, fsynced first, so a power cut can't leave an empty file under
    a final name."""
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def record(alerts_dir, unit, kind, fields, now):
    """S10: queue one alert, its text rendered once, so a repeated listing posts the same words. Returns the alert."""
    alerts_dir = _queue_dir(alerts_dir)
    alert = {'id': secrets.token_hex(6), 'unit': unit, 'kind': kind, 'at': now, **fields, 'held_back': 0, 'held_since': None}
    alert['text'] = render(alert)
    _write_private(alerts_dir / f'{alert["id"]}.json', alert)
    return alert


def queued(alerts_dir):
    """Every readable alert, oldest first. A file that is empty, half-written or not shaped like ours is skipped, never
    fatal: station-notices runs under Odo's check=True."""
    try:
        entries = list(os.scandir(alerts_dir))
    except OSError:
        return []
    found = []
    for entry in entries:
        match = ALERT_FILE.fullmatch(entry.name)
        if not match or not entry.is_file(follow_symlinks=False):
            continue
        try:
            alert = json.loads(Path(entry.path).read_text())
        except (OSError, ValueError):
            continue
        if (isinstance(alert, dict) and alert.get('id') == match[1] and isinstance(alert.get('unit'), str)
                and UNIT.fullmatch(alert['unit']) and alert.get('kind') in KINDS
                and isinstance(alert.get('at'), (int, float)) and isinstance(alert.get('text'), str)):
            found.append(alert)
    return sorted(found, key=lambda alert: (alert['at'], alert['id']))


def clean(alerts_dir, now):
    """S10: alert files more than 30 days old are deleted each time the notifier runs."""
    for alert in queued(alerts_dir):
        if alert['at'] < now - KEPT_DAYS * DAY:
            (Path(alerts_dir) / f'{alert["id"]}.json').unlink(missing_ok=True)


def station_alert(data_dir, unit, *, monitor, environ, now=None):
    """The station-alert command (S9-S11). Refused (exit 2) outside systemd or for an invalid unit. A queue it can't
    write is said on stderr, which goes to the journal, and the exit is still 0: the unit's result never changes."""
    if not isinstance(unit, str) or not UNIT.fullmatch(unit):
        raise Refused('the unit must look like superyak-<name>.service')
    fields = systemd_fields(environ, monitor)
    now = time.time() if now is None else now
    alerts_dir = Path(data_dir) / 'alerts'
    try:
        clean(alerts_dir, now)  # S10: each time the notifier runs, clean stops included (review N1)
        if fields['result'] == 'success':
            return None  # a clean stop: deploy restarts, systemctl stop, shutdown, and the stops Requires= carries along
        return record(alerts_dir, unit, kind_for(unit, monitor), fields, now)
    except OSError as error:
        print(f'station-alert: could not queue the alert for {unit}: {type(error).__name__}: {error.strerror or error}', file=sys.stderr)
        return None
