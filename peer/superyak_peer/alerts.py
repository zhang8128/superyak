"""Service alerts (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S9-S14): one checked line per
failure, queued as a private file that station-notices lists and Odo posts once in Ops. Standard library only. The
notifier reads nothing from the environment but systemd's result variables, and never a journal line (S11)."""
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import secrets
import sys
import time
from .backups import REASONS, SEE_LOG, stale_notice
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
LISTED_DAYS, LISTED_NEWEST = 7, 20
WINDOW, MAX_WINDOW = 1800, 6 * 3600
GIVE_UPS_PER_DAY = 6
LOCK_WAIT = 5
MAX_HELD = 1_000_000
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
    try:
        return time.strftime(fmt, time.localtime(at))
    except (OverflowError, OSError, ValueError, TypeError):
        return 'an unknown time'  # a stored value out of range never stops an alert being rendered


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
        if held and alert['held_since'] is not None:
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
    if alerts_dir.stat().st_mode & 0o077:  # mkdir leaves an existing wider mode in place
        os.chmod(alerts_dir, 0o700)
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


@contextmanager
def _lock(path, wait):
    """S12: records are written under a flock on alerts/.lock. After `wait` seconds without it, go on unlocked."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError:
        yield False  # a symlink, a directory or anything else that can't be locked: queue the alert unlocked
        return
    try:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    locked = False
                    break
                time.sleep(0.1)
        yield locked
    finally:
        os.close(fd)


def _rates(alerts_dir):
    """alerts/rate.json; a missing or garbled file starts fresh."""
    path = Path(alerts_dir) / 'rate.json'
    try:
        if path.is_symlink():
            return {}  # never read through a link; the next write replaces it
        rates = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return rates if isinstance(rates, dict) else {}


def _number(value):
    """A finite int or float; a bool, NaN, Infinity or an int too big for a float is not."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _state(value, now):
    """One unit's record from rate.json. A field of the wrong type or out of range (a hand edit, a clock that stepped back)
    is dropped, never fatal and never able to hold an alert back: a duplicate is better than a lost alert (review S2, I1)."""
    value = value if isinstance(value, dict) else {}
    state = {key: value[key] for key in ('window', 'until', 'last', 'held', 'held_since') if _number(value.get(key))}
    if not 0 < state.get('window', 1) <= MAX_WINDOW:
        del state['window']
    for key in ('until', 'last'):
        if key in state and state[key] > now + MAX_WINDOW:
            del state[key]
    if 'held' in state and not (isinstance(state['held'], int) and 0 <= state['held'] <= MAX_HELD):
        del state['held']
    if 'held_since' in state and state['held_since'] > now:
        del state['held_since']
    if ('held' in state) != ('held_since' in state):
        state.pop('held', None)
        state.pop('held_since', None)
    give_ups = value.get('give_ups')
    state['give_ups'] = [t for t in give_ups if _number(t) and t <= now] if isinstance(give_ups, list) else []
    return state


def _save_rates(alerts_dir, rates):
    """A rate.json that can't be written is said on stderr and never stops an alert."""
    try:
        _write_private(alerts_dir / 'rate.json', rates)
    except OSError as error:
        print(f'station-alert: could not write {alerts_dir / "rate.json"}: {type(error).__name__}: {error.strerror or error}', file=sys.stderr)


def _hold(state, now, *, stop):
    state['held'] = state.get('held', 0) + 1
    state['held_since'] = state.get('held_since') or now
    if stop:
        state['last'] = now


def record(alerts_dir, unit, kind, fields, now, *, lock_wait=LOCK_WAIT):
    """S12, then S10. A stopped failure inside its unit's window is held back and counted; the window is 30 minutes and
    doubles within an unbroken burst up to 6 hours, and a full window since the unit's last stop ends the burst. down and
    failed are always queued, except a 7th in a day for one unit (the backstop), which is held and counted like a stop.
    Without the lock within 5 s the alert is queued anyway: a duplicate is better than a lost alert. Returns the queued
    alert, or None when it was held back."""
    alerts_dir = _queue_dir(alerts_dir)
    held, held_since = 0, None
    with _lock(alerts_dir / '.lock', lock_wait) as locked:
        rates = None
        if locked:
            rates = _rates(alerts_dir)
            state = rates[unit] = _state(rates.get(unit), now)
            if kind == 'stopped':
                if now < state.get('until', 0):
                    _hold(state, now, stop=True)
                    _save_rates(alerts_dir, rates)
                    return None
                burst = 'last' in state and now - state['last'] < state.get('window', WINDOW)
                window = min(state.get('window', WINDOW) * 2, MAX_WINDOW) if burst else WINDOW
                held, held_since = state.get('held', 0), state.get('held_since')
                state.update(window=window, until=now + window, last=now, held=0, held_since=None)
            else:
                recent = [t for t in state.get('give_ups', []) if t > now - DAY]
                if len(recent) >= GIVE_UPS_PER_DAY:
                    _hold(state, now, stop=False)
                    state['give_ups'] = recent
                    _save_rates(alerts_dir, rates)
                    return None
                state['give_ups'] = recent + [now]
        alert = {'id': secrets.token_hex(6), 'unit': unit, 'kind': kind, 'at': now, **fields,
                 'held_back': held, 'held_since': held_since}
        alert['text'] = render(alert)
        _write_private(alerts_dir / f'{alert["id"]}.json', alert)
        if rates is not None:  # after the alert: if it can't be written, no window is set
            _save_rates(alerts_dir, rates)
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
                and isinstance(alert.get('at'), (int, float)) and not isinstance(alert['at'], bool) and math.isfinite(alert['at'])
                and isinstance(alert.get('text'), str)):
            found.append(alert)
    return sorted(found, key=lambda alert: (alert['at'], alert['id']))


def clean(alerts_dir, now):
    """S10: alert files more than 30 days old are deleted each time the notifier runs."""
    if Path(alerts_dir).is_symlink():
        raise OSError(f'{alerts_dir} is a symlink')  # never unlink files in a link's target
    waiting = queued(alerts_dir)
    for alert in waiting:
        if alert['at'] < now - KEPT_DAYS * DAY:
            (Path(alerts_dir) / f'{alert["id"]}.json').unlink(missing_ok=True)
    # Follow-up 6: a file queued() skips (an "at" of Infinity, say) can never be old by "at"; it goes by its own age.
    kept = {f'{alert["id"]}.json' for alert in waiting}
    for entry in os.scandir(alerts_dir):
        if (ALERT_FILE.fullmatch(entry.name) and entry.name not in kept and entry.is_file(follow_symlinks=False)
                and entry.stat(follow_symlinks=False).st_mtime < now - KEPT_DAYS * DAY):
            Path(entry.path).unlink(missing_ok=True)


def station_alert(data_dir, unit, *, monitor, environ, now=None):
    """The station-alert command (S9-S11). Refused (exit 2) outside systemd or for an invalid unit. A queue it can't
    write is said on stderr, which goes to the journal, and the exit is still 0: the unit's result never changes."""
    if not isinstance(unit, str) or not UNIT.fullmatch(unit):
        raise Refused('the unit must look like superyak-<name>.service')
    fields = systemd_fields(environ, monitor)
    now = time.time() if now is None else now
    alerts_dir = Path(data_dir) / 'alerts'
    try:
        if fields['result'] != 'success':  # a clean stop queues nothing: deploy restarts, systemctl stop, shutdown, and the stops Requires= carries along
            return record(alerts_dir, unit, kind_for(unit, monitor), fields, now)
    except OSError as error:
        print(f'station-alert: could not queue the alert for {unit}: {type(error).__name__}: {error.strerror or error}', file=sys.stderr)
    finally:
        try:
            clean(alerts_dir, now)  # S10: each time the notifier runs, clean stops included; never stops an alert (review N1)
        except OSError as error:
            print(f'station-alert: could not clean the old alerts in {alerts_dir}: {type(error).__name__}: {error.strerror or error}', file=sys.stderr)
    return None


def listed(alerts_dir, now):
    """S10: the last 7 days' alerts, oldest first: at most the 20 newest, plus every down and failed alert of those
    days, so a give-up line is never pushed out by restarts. The text goes through safe_line again on the way out."""
    waiting = queued(alerts_dir)
    shown = {alert['id']: safe_line(alert['text'], LINE_LIMIT) for alert in waiting}
    # follow-up 6: text of only invisible characters would list as nothing, so it is not an alert to list (or to count)
    recent = [alert for alert in waiting if alert['at'] > now - LISTED_DAYS * DAY and shown[alert['id']]]
    newest = {alert['id'] for alert in recent[-LISTED_NEWEST:]}
    return [{'id': f'alert-{alert["id"]}', 'text': shown[alert['id']]}
            for alert in recent if alert['id'] in newest or alert['kind'] != 'stopped']


def notices_beside(data_dir, backup_dir, now):
    """What station-notices appends to Store.station_notices() (S10, S14). None when neither the alert queue nor the
    rotation exists, so the command prints exactly what it printed before (R15)."""
    alerts_dir, backup_dir = Path(data_dir) / 'alerts', Path(backup_dir)
    if not alerts_dir.is_dir() and not backup_dir.is_dir():
        return None
    stale = stale_notice(backup_dir, now)
    return listed(alerts_dir, now) + ([stale] if stale else [])


def describe_queue(alerts_dir, now):
    """make station-alerts (S13): the queue and the held-back counts. Every value here is ours: checked units and
    rendered lines."""
    waiting = queued(alerts_dir)
    lines = ['Queued alerts, oldest first (Odo posts each once in Ops; files over 30 days old are deleted):'] if waiting else ['No alerts are queued.']
    lines += [f'  {_local(alert["at"], "%Y-%m-%d %H:%M")}  {alert["kind"]:<7}  {alert["unit"]}  {alert["id"]}' for alert in waiting]
    held = [(unit, state) for unit, state in ((unit, _state(value, now)) for unit, value in sorted(_rates(alerts_dir).items()))
            if UNIT.fullmatch(unit) and state.get('held') and state.get('held_since')]
    lines.append("Held back (counted in that unit's next stopped line, or only shown here):" if held else 'Nothing is held back.')
    lines += [f'  {unit}: {state["held"]} {"stop" if state["held"] == 1 else "stops"} held back since {_local(state["held_since"])}'
              for unit, state in held]
    return '\n'.join(lines)
