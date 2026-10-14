"""Station backups and the restore (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S2-S5, S7,
S14, S16). Trusted local commands, standard library only. station-backup never constructs Store and never takes the
dispatch gate: it reads the live file through a read-only connection, and SQLite's backup API copies a consistent
snapshot of committed data on its own (S2)."""
import calendar
from contextlib import closing, contextmanager
import datetime
import fcntl
import os
from pathlib import Path
import re
import sqlite3
import time

STAMP = '%Y%m%dT%H%M%SZ'
COPY_NAME = re.compile(r'peer-(\d{8}T\d{6}Z)\.sqlite3')
TEMP_NAME = re.compile(r'\.peer-.+\.tmp(?:-journal)?')
KEEP_DAYS, KEEP_WEEKS = 14, 8
TEMP_MAX_AGE = 86400
SEE_LOG = 'see the log'
REASONS = {  # spec, Error handling: the words the CLI prints and the Ops line carries
    10: 'not enough disk space',
    11: "the copy failed its check; tomorrow's run tries again",
    12: "the live database may be damaged: don't restart or deploy before reading docs/station-restore.md",
    13: 'the copy off the Pi failed',
    20: 'there is no backup to test',
    21: 'the newest copy failed its check',
    22: 'the restored station did not start',
    23: 'the restored station is missing data',
    24: "the restore's reconcile step failed",
}


class BackupError(Exception):
    """A failure with its exit code (spec, Error handling). The CLI prints the reason and exits with the code."""
    def __init__(self, code, reason=None):
        self.code, self.reason = code, reason or REASONS.get(code, SEE_LOG)
        super().__init__(self.reason)


def default_backup_dir(data_dir):
    """S14: backups/station beside the data dir, so ~/.local/share/superyak/backups/station for the lighthouse."""
    return Path(data_dir).absolute().parent / 'backups' / 'station'


def copy_stamp(now):
    return time.strftime(STAMP, time.gmtime(now))


def copy_time(path):
    """A copy's UTC time, from its name."""
    return calendar.timegm(time.strptime(COPY_NAME.fullmatch(Path(path).name)[1], STAMP))


def _stamp_ok(name):
    """A name that matches COPY_NAME and holds a real UTC time; peer-20261399T000000Z.sqlite3 only looks like one. A
    stray one would otherwise sort newest: every backup would fail on the clock check and station-notices would crash."""
    try:
        time.strptime(COPY_NAME.fullmatch(name)[1], STAMP)
    except (TypeError, ValueError):
        return False
    return True


def rotation(directory):
    """The copies with a final name, oldest first. Symlinks and every other name are never read, moved or pruned."""
    try:
        entries = list(os.scandir(directory))
    except FileNotFoundError:
        return []
    return sorted((Path(entry.path) for entry in entries
                   if _stamp_ok(entry.name) and entry.is_file(follow_symlinks=False)), key=lambda path: path.name)


def newest_copy(directory):
    copies = rotation(directory)
    return copies[-1] if copies else None


def keep(names):
    """S3: the newest copy of each of the 14 most recent UTC days that have a copy, and of each of the 8 most recent ISO
    weeks that have one. Only days and weeks with a copy count, so a Pi that was off never ages out its last copies."""
    days, weeks = {}, {}
    for name in sorted(names, reverse=True):
        when = datetime.datetime.strptime(COPY_NAME.fullmatch(name)[1], STAMP)
        days.setdefault(when.date(), name)
        weeks.setdefault(when.isocalendar()[:2], name)
    return ({days[day] for day in sorted(days, reverse=True)[:KEEP_DAYS]}
            | {weeks[week] for week in sorted(weeks, reverse=True)[:KEEP_WEEKS]})


def prune(directory, now):
    """S3, R3: run only once a new checked copy is in place. Deletes the copies S3 doesn't keep, and temporary files
    (.tmp and .tmp-journal) over a day old. Nothing else in the directory is touched."""
    copies = rotation(directory)
    kept = keep([path.name for path in copies])
    for path in copies:
        if path.name not in kept:
            path.unlink()
    for entry in list(os.scandir(directory)):
        if (TEMP_NAME.fullmatch(entry.name) and entry.is_file(follow_symlinks=False)
                and now - entry.stat(follow_symlinks=False).st_mtime > TEMP_MAX_AGE):
            os.unlink(entry.path)


def _read_only(path):
    """S2: the URI is built as validate_demo builds it (__main__.py:125); a hand-built file: URI breaks on ?, # or %."""
    return sqlite3.connect(Path(path).absolute().as_uri() + '?mode=ro', uri=True, timeout=30)


def _check(db, pragma):
    """True when PRAGMA integrity_check or quick_check returns exactly one row, 'ok'. Raising counts as failing."""
    try:
        return [tuple(row) for row in db.execute(f'PRAGMA {pragma}')] == [('ok',)]
    except sqlite3.DatabaseError:
        return False


def _fsync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _live_database(data_dir):
    """S2: refuse a symlinked data dir or database, as Store._check_paths does, and a missing database."""
    data_dir = Path(data_dir).absolute()
    names = ('peer.sqlite3', 'peer.sqlite3-wal', 'peer.sqlite3-shm', 'peer.sqlite3-journal')
    if data_dir.is_symlink() or any((data_dir / name).is_symlink() for name in names):
        raise ValueError('Symlinked state is not allowed')
    database = data_dir / 'peer.sqlite3'
    if not database.is_file():
        raise ValueError(f'There is no station database at {database}')
    return database


def _rotation_dir(backup_dir):
    backup_dir = Path(backup_dir).absolute()
    if backup_dir.is_symlink():
        raise ValueError('A symlinked backup directory is not allowed')
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    return backup_dir


@contextmanager
def rotation_lock(directory):
    """S2: one run at a time. The restore test copies under it too, so pruning can't remove its file mid-copy (S7)."""
    fd = os.open(Path(directory) / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _remove_temporary(tmp):
    for path in (Path(tmp), Path(f'{tmp}-journal')):
        path.unlink(missing_ok=True)


def _checked_copy(database, tmp, clock, sleep):
    """S2 steps 1-3: a new 0600 file, SQLite's backup API in one step from a read-only connection, then
    integrity_check. Every failure removes the file."""
    os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
    try:
        with closing(_read_only(database)) as source, closing(sqlite3.connect(tmp)) as copy:
            source.backup(copy, pages=-1)
            sound = _check(copy, 'integrity_check')
        if not sound:
            raise BackupError(11)
        _fsync(tmp)
    except BaseException:
        _remove_temporary(tmp)
        raise


def _publish(tmp, final):
    """S2 step 4: the rename, then the directory's fsync. A file with a final name is always a checked copy."""
    os.replace(tmp, final)
    _fsync(final.parent)


def run_backup(data_dir, backup_dir, *, clock=time.time, sleep=time.sleep):
    """station-backup (S2). Returns the new copy's path; raises BackupError with its exit code."""
    database = _live_database(data_dir)
    old_umask = os.umask(0o077)
    try:
        backup_dir = _rotation_dir(backup_dir)
        with rotation_lock(backup_dir):
            now = clock()
            stamp, newest = copy_stamp(now), newest_copy(backup_dir)
            if newest is not None and stamp < COPY_NAME.fullmatch(newest.name)[1]:
                # S3: a clock behind would give the copy an old name that pruning could delete at once; a clock that
                # was ahead left a future name "newest". Either way: nothing written, nothing pruned, every night.
                raise BackupError(1, f"the Pi's clock is behind the newest copy ({newest.name}); if the clock is right, "
                                     f'move that copy out of {backup_dir}')
            final, tmp = backup_dir / f'peer-{stamp}.sqlite3', backup_dir / f'.peer-{stamp}-{os.getpid()}.tmp'
            _checked_copy(database, tmp, clock, sleep)
            try:
                _publish(tmp, final)
            except BaseException:
                _remove_temporary(tmp)
                raise
            prune(backup_dir, now)
        return final
    finally:
        os.umask(old_umask)
