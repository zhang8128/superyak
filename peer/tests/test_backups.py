"""Station backups (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S2–S5; R1–R6). Every test
works on a station in tmp_path; none touches ~/.local/share/superyak."""
import calendar
from contextlib import closing
import datetime
import hashlib
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
import pytest
from superyak_peer import backups
from superyak_peer.__main__ import main as cli
from superyak_peer.db import Store

HOLD = ('import fcntl, os, sys, time\n'
        'fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR)\n'
        'fcntl.flock(fd, fcntl.LOCK_EX)\n'
        'print("held", flush=True)\n'
        'time.sleep(60)\n')


def station(tmp_path):
    """A small live station in tmp_path/lighthouse, and where its rotation goes: backups/station beside it."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    jenn = store.create_user('jenn', 'Jenn', 'long-password-jenn')
    room = store.create_room(andy['id'], 'Ops', [jenn['id']])
    store.send_message(andy['id'], room['id'], 'm1', 'hello')
    return store, tmp_path / 'backups' / 'station'


def backup(store, rotation, *extra):
    """station-backup as the timer runs it; returns its exit code."""
    try:
        cli(['station-backup', '--data-dir', str(store.data_dir), '--backup-dir', str(rotation), *map(str, extra)])
    except SystemExit as stopped:
        return stopped.code
    return 0


def names(directory):
    return sorted(p.name for p in directory.iterdir() if p.name != '.lock')


def ok(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]


def test_backup_copies_committed_data_from_a_read_only_connection(tmp_path, monkeypatch):
    """R1: the backup API from a mode=ro connection, in one step; never Store, never the dispatch gate."""
    store, rotation = station(tmp_path)
    live = store.db_path
    before, mtime = live.read_bytes(), live.stat().st_mtime_ns
    real_connect, opened = sqlite3.connect, []

    def connect(target, *args, **kwargs):
        opened.append((str(target), kwargs.get('uri', False)))
        return real_connect(target, *args, **kwargs)

    writer = real_connect(live, isolation_level=None)
    writer.execute('BEGIN IMMEDIATE')
    writer.execute("INSERT INTO login_attempts VALUES('uncommitted', 1, 0)")
    monkeypatch.setattr(sqlite3, 'connect', connect)
    monkeypatch.setattr(Store, '__init__', lambda *a, **k: pytest.fail('station-backup constructed Store'))
    try:
        assert backup(store, rotation) == 0
    finally:
        writer.execute('ROLLBACK')
        writer.close()
    [copy] = rotation.glob('peer-*.sqlite3')
    assert ok(copy)
    with closing(real_connect(copy)) as db:
        assert db.execute("SELECT count(*) FROM login_attempts WHERE key='uncommitted'").fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM messages').fetchone()[0] == 1
    assert live.read_bytes() == before and live.stat().st_mtime_ns == mtime
    assert not Path(f'{live}-journal').exists()
    live_opens = [o for o in opened if str(live) in o[0]]
    assert live_opens and all(target.endswith('?mode=ro') and uri for target, uri in live_opens)
    # A second run while another process holds dispatch.lock finishes too, so the backup never takes the gate.
    holder = subprocess.Popen([sys.executable, '-c', HOLD, str(store.data_dir / 'dispatch.lock')], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'held'
        again = subprocess.run([sys.executable, '-m', 'superyak_peer', 'station-backup', '--data-dir', str(store.data_dir),
                                '--backup-dir', str(rotation)], capture_output=True, text=True, timeout=30)
    finally:
        holder.kill()
        holder.wait()
    assert again.returncode == 0, again.stderr


def test_copies_are_private_checked_and_appear_whole(tmp_path, monkeypatch):
    """R2: 0600 in a 0700 directory; a failure after the temporary write leaves neither a final nor a temporary file."""
    store, rotation = station(tmp_path)
    assert backup(store, rotation) == 0
    [copy] = rotation.glob('peer-*.sqlite3')
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600 and stat.S_IMODE(rotation.stat().st_mode) == 0o700
    assert ok(copy) and re.fullmatch(r'peer-\d{8}T\d{6}Z\.sqlite3', copy.name)
    copy.unlink()

    def fail(tmp, final):
        raise OSError('injected after the temporary write')

    monkeypatch.setattr(backups, '_publish', fail)
    assert backup(store, rotation) == 1
    assert names(rotation) == []


def test_a_hand_made_rotation_folder_is_tightened_to_0700(tmp_path):
    """R2: the real case on the Pi is a folder made by hand at 0755; the run must leave it 0700."""
    store, rotation = station(tmp_path)
    rotation.mkdir(parents=True, mode=0o755)
    os.chmod(rotation, 0o755)
    assert backup(store, rotation) == 0
    assert stat.S_IMODE(rotation.stat().st_mode) == 0o700


def test_each_layer_of_privacy_holds_without_the_umask(tmp_path, monkeypatch):
    """R2: with umask a no-op, the file's 0600 comes from O_CREAT's mode and the folder's 0700 from the chmod."""
    store, rotation = station(tmp_path)
    rotation.mkdir(parents=True, mode=0o755)
    os.chmod(rotation, 0o755)
    monkeypatch.setattr(os, 'umask', lambda mask: 0)  # a no-op: the process umask stays what the test runner has
    assert backup(store, rotation) == 0
    [copy] = rotation.glob('peer-*.sqlite3')
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600 and stat.S_IMODE(rotation.stat().st_mode) == 0o700


def test_a_failed_integrity_check_leaves_nothing_behind(tmp_path, monkeypatch):
    """R2/S2: exit 11 and no temporary, journal or final file. The live quick_check passes, so it is the copy that failed."""
    store, rotation = station(tmp_path)
    monkeypatch.setattr(backups, '_check', lambda db, pragma: pragma == 'quick_check')
    assert backup(store, rotation) == 11
    assert names(rotation) == []


NOW = calendar.timegm((2026, 10, 17, 3, 30, 0))
# Worked out by hand, not by the code under test. The test makes copies at 03:30 UTC on the 200 days 2026-03-31 to
# 2026-10-16, except September (the Pi was off) and 2026-10-10 (a failed night), plus 2026-10-16 03:31:10 and 15:00:00;
# the run adds 2026-10-17 03:30:00. S3 then keeps:
# - the newest copy of the 14 most recent days that have one: 10-03 to 10-09 and 10-11 to 10-17 (10-16 keeps 15:00);
# - the newest copy of the 8 most recent ISO weeks that have one: weeks 42 (10-17), 41 (10-11), 40 (10-04), then,
#   since weeks 37-39 have none, 36 (08-31), 35 (08-30), 34 (08-23), 33 (08-16) and 32 (08-09).
KEPT = ['20260809T033000Z', '20260816T033000Z', '20260823T033000Z', '20260830T033000Z', '20260831T033000Z',
        '20261003T033000Z', '20261004T033000Z', '20261005T033000Z', '20261006T033000Z', '20261007T033000Z',
        '20261008T033000Z', '20261009T033000Z', '20261011T033000Z', '20261012T033000Z', '20261013T033000Z',
        '20261014T033000Z', '20261015T033000Z', '20261016T150000Z', '20261017T033000Z']


def test_retention_keeps_14_days_and_8_weeks_and_nothing_else(tmp_path):
    """R3: S3's rule over 200 days with gaps, several copies in one day and a month off. Hand-made names and other files
    are never touched; stale temporary files go; a clock behind the newest name writes and prunes nothing, exit 1."""
    store, rotation = station(tmp_path)
    rotation.mkdir(parents=True, mode=0o700)
    day = datetime.date(2026, 3, 31)
    for _ in range(200):
        if day.month != 9 and day != datetime.date(2026, 10, 10):
            (rotation / f'peer-{day:%Y%m%d}T033000Z.sqlite3').write_bytes(b'copy')
        day += datetime.timedelta(days=1)
    for extra in ('20261016T033110Z', '20261016T150000Z'):
        (rotation / f'peer-{extra}.sqlite3').write_bytes(b'copy')
    others = ['peer-20261007-083623-before-andy-password.sqlite3', 'peer.sqlite3.pre-instruction-layers-20261008-163222',
              'peer-20260101T000000Z.sqlite3.bak', 'notes.txt',
              'peer-20261399T000000Z.sqlite3']        # matches the pattern but isn't a time: never newest, never pruned
    for name in others:
        (rotation / name).write_bytes(b'not a rotation copy')
    stale = [rotation / '.peer-20261001T033000Z-41.tmp', rotation / '.peer-20261001T033000Z-41.tmp-journal']
    fresh = rotation / '.peer-20261017T030000Z-42.tmp'
    for path in [*stale, fresh]:
        path.write_bytes(b'temporary')
    for path in stale:
        os.utime(path, (NOW - 2 * 86400, NOW - 2 * 86400))
    os.utime(fresh, (NOW - 3600, NOW - 3600))
    before = names(rotation)
    with pytest.raises(backups.BackupError) as behind:
        backups.run_backup(store.data_dir, rotation, clock=lambda: calendar.timegm((2026, 10, 16, 14, 0, 0)))
    assert behind.value.code == 1
    assert "the Pi's clock is behind the newest copy (peer-20261016T150000Z.sqlite3)" in behind.value.reason
    assert names(rotation) == before
    written = backups.run_backup(store.data_dir, rotation, clock=lambda: NOW)
    assert written.name == 'peer-20261017T033000Z.sqlite3' and ok(written)
    assert [path.name for path in backups.rotation(rotation)] == [f'peer-{stamp}.sqlite3' for stamp in KEPT]
    assert all((rotation / name).read_bytes() == b'not a rotation copy' for name in others)
    assert not any(path.exists() for path in stale) and fresh.exists()


def test_retention_weeks_cross_the_year_by_iso_year_and_week():
    """S3: a week is (ISO year, ISO week), so week 2 of 2026 and week 2 of 2027 are different weeks. Twenty daily
    copies fill the 14-day window; 2026-01-05 (2026, week 2) survives only as its own week's newest copy. Keyed by the
    week number alone, it would merge into 2027's week 2 and be pruned."""
    daily = [f'peer-202701{d:02d}T030000Z.sqlite3' for d in range(12, 32)]
    names = ['peer-20260105T030000Z.sqlite3', 'peer-20270111T030000Z.sqlite3'] + daily
    kept = backups.keep(names)
    assert 'peer-20260105T030000Z.sqlite3' in kept
    assert 'peer-20270117T030000Z.sqlite3' in kept  # (2027, 2)'s newest, older than the 14 days
    assert 'peer-20270111T030000Z.sqlite3' not in kept
    assert len(kept) == 14 + 2  # 01-18..01-31, plus the two week-2 copies, one per year


def overwrite_pages(path, first=2):
    """Junk over every page after the first two: the header survives, the tables don't."""
    size = path.stat().st_size
    with open(path, 'r+b') as stream:
        stream.seek(first * 4096)
        stream.write(b'\xff' * (size - first * 4096))


def test_output_writes_one_checked_copy_and_never_overwrites(tmp_path, monkeypatch):
    """R4: one checked copy at a new path outside the rotation; an existing path is refused, even one created during the
    copy, because the copy is published with os.link."""
    store, rotation = station(tmp_path)
    target = tmp_path / 'before-deploy.sqlite3'
    assert backup(store, rotation, '--output', target) == 0
    assert ok(target) and stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not rotation.exists()
    kept = target.read_bytes()
    assert backup(store, rotation, '--output', target) == 1 and target.read_bytes() == kept
    racing, real_check = tmp_path / 'racing.sqlite3', backups._check

    def check_then_race(db, pragma):
        racing.write_bytes(b'made by someone else during the copy')
        return real_check(db, pragma)

    monkeypatch.setattr(backups, '_check', check_then_race)
    assert backup(store, rotation, '--output', racing) == 1
    assert racing.read_bytes() == b'made by someone else during the copy'
    assert not list(tmp_path.glob('.peer-*'))


@pytest.mark.parametrize('failure, code', [(None, 0), ('low disk', 10), ('copy fails its check', 11),
                                           ('live database damaged', 12)])
def test_failures_keep_old_copies_and_exit_with_their_code(tmp_path, monkeypatch, failure, code):
    """R5: low disk and failed checks write nothing, prune nothing, leave no temporary file and exit with their code. The
    first case is the control: the same rotation and a run that works, which prunes the older of one day's two copies."""
    store, rotation = station(tmp_path)
    rotation.mkdir(parents=True, mode=0o700)
    day = time.strftime('%Y%m%d', time.gmtime(time.time() - 3 * 86400))
    old = [f'peer-{day}T010000Z.sqlite3', f'peer-{day}T020000Z.sqlite3'] + [
        f'peer-{time.strftime(backups.STAMP, time.gmtime(time.time() - days * 86400))}.sqlite3' for days in (2, 1)]
    for name in old:
        (rotation / name).write_bytes(b'an earlier copy')
    if failure == 'low disk':
        monkeypatch.setattr(backups, 'free_bytes', lambda path: 10 * 2**20)
    elif failure == 'copy fails its check':
        monkeypatch.setattr(backups, '_check', lambda db, pragma: pragma == 'quick_check')
    elif failure == 'live database damaged':
        overwrite_pages(store.db_path)
    assert backup(store, rotation) == code
    if failure is None:
        [new] = [name for name in names(rotation) if name not in old]
        assert names(rotation) == sorted(old[1:] + [new])
    else:
        assert names(rotation) == sorted(old)


CRASH = '''import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute('PRAGMA cache_size=2')
db.execute('BEGIN IMMEDIATE')
db.execute("UPDATE filler SET v = v || 'y'")
os._exit(0)
'''


def test_a_hot_journal_after_a_power_cut_is_retried_never_called_damage(tmp_path):
    """Review Focus 4 (S8): a power cut mid-commit leaves a hot journal. The read-only open succeeds and the first read
    fails with SQLITE_READONLY_ROLLBACK. The backup retries for 60 s, then exits 1, never 12, and leaves the live file
    and its journal exactly as they were: the lighthouse recovers them when it opens the database."""
    store, rotation = station(tmp_path)
    with closing(sqlite3.connect(store.db_path)) as db:
        db.execute('CREATE TABLE filler(v TEXT)')
        db.executemany('INSERT INTO filler VALUES(?)', [('x' * 500,) for _ in range(2000)])
        db.commit()
    subprocess.run([sys.executable, '-I', '-c', CRASH, str(store.db_path)], check=True)   # the cache spills, then "power off"
    journal = Path(f'{store.db_path}-journal')
    assert journal.stat().st_size > 0
    live, hot = store.db_path.read_bytes(), journal.read_bytes()
    now = [time.time()]
    with pytest.raises(backups.BackupError) as failed:
        backups.run_backup(store.data_dir, rotation, clock=lambda: now[0],
                           sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
    assert failed.value.code == 1 and f'could not be copied for {backups.RETRY_SECONDS} s' in failed.value.reason
    assert store.db_path.read_bytes() == live and journal.read_bytes() == hot
    assert names(rotation) == []


def test_a_pruning_failure_exits_1_and_says_the_new_copy_is_in_place(tmp_path, monkeypatch, capsys):
    """Spec, Error handling: a pruning error is exit 1 ("anything else"). The new copy is already published, so the
    reason says so rather than reading as a failed backup; one stuck file doesn't stop the rest being pruned."""
    store, rotation = station(tmp_path)
    rotation.mkdir(parents=True, mode=0o700)
    day = time.strftime('%Y%m%d', time.gmtime(time.time() - 3 * 86400))
    stuck, gone = (f'peer-{day}T0{hour}0000Z.sqlite3' for hour in (1, 2))
    newest_of_day = f'peer-{day}T030000Z.sqlite3'
    for name in (stuck, gone, newest_of_day):
        (rotation / name).write_bytes(b'an earlier copy')
    real_unlink = Path.unlink

    def unlink(self, *args, **kwargs):
        if self.name == stuck:
            raise PermissionError(13, 'Permission denied', str(self))
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', unlink)
    assert backup(store, rotation) == 1
    message = capsys.readouterr().err
    assert 'new copy is in place' in message and stuck in message
    [new] = [name for name in names(rotation) if name not in (stuck, gone, newest_of_day)]
    assert ok(rotation / new) and gone not in names(rotation) and stuck in names(rotation)


def test_copy_to_is_off_by_default_and_refuses_the_same_disk(tmp_path, monkeypatch):
    """R6: an empty --copy-to does nothing. The rotation's own disk, a missing directory or a symlink gives 13 and keeps
    the local copy. Another disk gets a 0600 copy with the same sha256, and S3 applies there too."""
    store, rotation = station(tmp_path)
    offsite = tmp_path / 'offsite'
    offsite.mkdir()
    assert backup(store, rotation, '--copy-to=') == 0                  # what the unit passes while backup.env is absent
    assert len(backups.rotation(rotation)) == 1 and list(offsite.iterdir()) == []
    assert backup(store, rotation, f'--copy-to={offsite}') == 13       # tmp_path is the rotation's disk too
    assert backups.rotation(rotation) and list(offsite.iterdir()) == []
    monkeypatch.setattr(backups, '_device', lambda path: 2 if Path(path) == rotation else 1)   # every other path: another disk
    link = tmp_path / 'link'
    link.symlink_to(offsite)
    for refused in (tmp_path / 'missing', link):
        assert backup(store, rotation, f'--copy-to={refused}') == 13
        assert backups.rotation(rotation) and list(offsite.iterdir()) == []
    day = time.strftime('%Y%m%d', time.gmtime(time.time() - 3 * 86400))
    for hour in ('01', '02'):
        (offsite / f'peer-{day}T{hour}0000Z.sqlite3').write_bytes(b'an earlier copy')
    assert backup(store, rotation, f'--copy-to={offsite}') == 0
    local = backups.newest_copy(rotation)
    copied = offsite / local.name
    assert stat.S_IMODE(copied.stat().st_mode) == 0o600
    assert hashlib.sha256(copied.read_bytes()).digest() == hashlib.sha256(local.read_bytes()).digest()
    assert sorted(p.name for p in offsite.iterdir()) == sorted([f'peer-{day}T020000Z.sqlite3', local.name])


def test_a_copy_that_does_not_match_is_removed_and_exits_13(tmp_path, monkeypatch, capsys):
    """R6: the sha256 comparison. A mismatch leaves no file, not even a temporary one, in the destination."""
    store, rotation = station(tmp_path)
    offsite = tmp_path / 'offsite'
    offsite.mkdir()
    monkeypatch.setattr(backups, '_device', lambda path: 2 if Path(path) == rotation else 1)
    real = backups._sha256
    monkeypatch.setattr(backups, '_sha256', lambda path: real(path) if Path(path).parent == rotation else 'different')
    assert backup(store, rotation, f'--copy-to={offsite}') == 13
    assert 'does not match' in capsys.readouterr().err
    assert list(offsite.iterdir()) == [] and len(backups.rotation(rotation)) == 1


def stuck_rotation(tmp_path, monkeypatch):
    """A rotation holding one old copy that pruning cannot remove, and the old copy's name."""
    rotation = tmp_path / 'backups' / 'station'
    rotation.mkdir(parents=True, mode=0o700)
    day = time.strftime('%Y%m%d', time.gmtime(time.time() - 3 * 86400))
    stuck, newest_of_day = (f'peer-{day}T0{hour}0000Z.sqlite3' for hour in (1, 2))
    for name in (stuck, newest_of_day):
        (rotation / name).write_bytes(b'an earlier copy')
    real_unlink = Path.unlink

    def unlink(self, *args, **kwargs):
        if self.name == stuck and self.parent == rotation:
            raise PermissionError(13, 'Permission denied', str(self))
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', unlink)
    return rotation, stuck


def test_the_copy_off_the_pi_still_runs_after_a_pruning_failure(tmp_path, monkeypatch, capsys):
    """A pruning problem never skips the copy off the Pi. Pruning alone failing is exit 1 and the copy is made; both
    failing is exit 13 (the more specific code), and the message carries both outcomes."""
    store, _ = station(tmp_path)
    rotation, stuck = stuck_rotation(tmp_path, monkeypatch)
    offsite = tmp_path / 'offsite'
    offsite.mkdir()
    monkeypatch.setattr(backups, '_device', lambda path: 2 if Path(path) == rotation else 1)
    assert backup(store, rotation, f'--copy-to={offsite}') == 1
    message = capsys.readouterr().err
    assert 'new copy is in place' in message and stuck in message
    [new] = [name for name in names(rotation) if not name.startswith('peer-' + stuck[5:13])]
    assert (offsite / new).read_bytes() == (rotation / new).read_bytes()
    shutil.rmtree(offsite)                                                   # now both fail: no destination
    assert backup(store, rotation, f'--copy-to={offsite}') == 13
    message = capsys.readouterr().err
    assert 'copy off the Pi failed' in message and 'new copy is in place' in message and stuck in message


def test_prune_of_a_missing_directory_removes_nothing_like_rotation(tmp_path):
    """A folder that isn't there has nothing to prune, as rotation() already treats it. For --copy-to the missing
    folder is refused earlier (13), so prune never has to guess."""
    assert backups.rotation(tmp_path / 'gone') == []
    assert backups.prune(tmp_path / 'gone', time.time()) == []


def test_a_full_disk_when_the_temporary_file_is_made_exits_10(tmp_path, monkeypatch, capsys):
    """S4: ENOSPC at the os.open that creates the temporary file is exit 10, not a traceback."""
    store, rotation = station(tmp_path)
    real_open = os.open

    def full(path, *args, **kwargs):
        if Path(path).name.endswith('.tmp'):
            raise OSError(28, 'No space left on device')
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, 'open', full)
    assert backup(store, rotation) == 10
    assert 'not enough disk space' in capsys.readouterr().err
    assert names(rotation) == []


def test_output_failures_say_why_instead_of_a_traceback(tmp_path, monkeypatch, capsys):
    """R4: an existing path, and a filesystem without hard links, are exit 1 with a plain message."""
    store, rotation = station(tmp_path)
    taken = tmp_path / 'taken.sqlite3'
    taken.write_bytes(b'mine')
    assert backup(store, rotation, '--output', taken) == 1
    assert 'never replaces a file' in capsys.readouterr().err and taken.read_bytes() == b'mine'

    def no_links(source, target, *args, **kwargs):
        raise OSError(1, 'Operation not permitted')

    monkeypatch.setattr(os, 'link', no_links)
    fresh = tmp_path / 'fresh.sqlite3'
    assert backup(store, rotation, '--output', fresh) == 1
    assert 'hard link' in capsys.readouterr().err
    assert not fresh.exists() and not list(tmp_path.glob('.peer-*'))
