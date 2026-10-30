"""station-journal (spec 2026-10-29-store-wal-mode D1): the store's journal mode, switched only with every station unit
stopped, under the dispatch gate, and decided by SQLite's own lock. Standard library only: backups.py imports it."""
from pathlib import Path
import sqlite3
import subprocess
import time

from .dispatch import DispatchGate

NAMES = ('peer.sqlite3', 'peer.sqlite3-journal', 'peer.sqlite3-wal', 'peer.sqlite3-shm')
MODES = ('wal', 'delete')
# The five services whose unit files live outside the repo, then every unit in peer/systemd/ but the alert template.
STATION_UNITS_TO_STOP = (
    'superyak-lighthouse.service', 'superyak-door.service', 'superyak-ship.service', 'superyak-odo.service',
    'superyak-wormhole.service', 'superyak-federate.service', 'superyak-federation-listen.service',
    'superyak-backup.service', 'superyak-restore-test.service', 'superyak-imprint-sweep.service',
    'superyak-lessons-index.service')
RUNNING = ('active', 'activating', 'deactivating', 'reloading', 'refreshing')
RETRY_PAUSE = 0.2


def header_mode(path):
    """'wal' when the file's header says WAL (bytes 18-19 are 2 2), else 'delete'; a short header is not WAL."""
    with open(path, 'rb') as file:
        header = file.read(20)
    return 'wal' if header[18:20] == b'\x02\x02' else 'delete'


def units_active():
    """The station units that are running or changing state, one `systemctl --user is-active` per unit, decided by the
    state it prints (it exits 3 for `activating` and `deactivating`), and any exit 0 counts as running whatever the
    state. A systemctl that can't answer (an exit other than 0 or 3, or no state printed) refuses: the switch fails
    closed. A unit that isn't loaded reads `inactive`, so a renamed unit isn't caught here:
    test_every_station_service_is_stopped_first keeps STATION_UNITS_TO_STOP in step with peer/systemd."""
    active = []
    for unit in STATION_UNITS_TO_STOP:
        try:
            done = subprocess.run(['systemctl', '--user', 'is-active', unit], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError(f'systemctl could not say whether {unit} is running: {error}') from None
        state = done.stdout.strip()
        if done.returncode not in (0, 3) or not state:
            raise ValueError(f'systemctl could not say whether {unit} is running (exit {done.returncode})')
        if state in RUNNING or done.returncode == 0:
            active.append(unit)
    return active


def _store_path(data_dir):
    data_dir = Path(data_dir).absolute()
    if data_dir.is_symlink() or any((data_dir / name).is_symlink() for name in NAMES + ('dispatch.lock',)):
        raise ValueError('Symlinked state is not allowed')
    database = data_dir / 'peer.sqlite3'
    if not database.is_file():
        raise ValueError(f'There is no station database at {database}, and station-journal never makes one')
    if not (data_dir / 'dispatch.lock').is_file():
        raise ValueError(f'{data_dir} holds no dispatch.lock, so no station has run there; station-journal never makes one')
    return database


def _set_mode(db, mode):
    return db.execute(f'PRAGMA journal_mode={mode}').fetchone()[0]


def switch_journal(data_dir, mode, *, active=None, retry_seconds=10.0, clock=time.monotonic, sleep=time.sleep):
    """(before, after) for the store in `data_dir`. Refuses a missing store or gate file, a symlink, or a running unit;
    then switches under the gate, retrying "database is locked" for `retry_seconds`, and checks SQLite's answer."""
    if mode not in MODES:
        raise ValueError(f'The journal mode is one of {", ".join(MODES)}')
    database = _store_path(data_dir)
    running = (active or units_active)()
    if running:
        raise ValueError(f'Stop every station unit first; still running: {", ".join(running)}')
    with DispatchGate(Path(data_dir).absolute() / 'dispatch.lock'):
        before = header_mode(database)
        deadline = clock() + retry_seconds  # from inside the gate, so a long wait for it still leaves the retries
        while True:
            try:
                db = sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=0.1)
            except sqlite3.Error as error:
                raise ValueError(f'SQLite refused the switch: {error}; nothing was changed') from None
            try:
                answer = _set_mode(db, mode)
                break
            except sqlite3.Error as error:  # a damaged header is a DatabaseError: "file is not a database"
                if not (isinstance(error, sqlite3.OperationalError) and 'locked' in str(error)):
                    raise ValueError(f'SQLite refused the switch: {error}; nothing was changed') from None
                if clock() >= deadline:
                    raise ValueError(f'The store stayed locked for {retry_seconds:g} s; nothing was changed') from None
            finally:
                db.close()
            sleep(RETRY_PAUSE)
    if answer != mode:
        raise ValueError(f'SQLite answered journal_mode={answer}, not {mode}')
    return before, header_mode(database)
