"""Station backups (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S2–S5; R1–R6). Every test
works on a station in tmp_path; none touches ~/.local/share/superyak."""
import calendar
from contextlib import closing
import datetime
import hashlib
import os
from pathlib import Path
import re
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
    """R2/S2: exit 11 and no temporary, journal or final file."""
    store, rotation = station(tmp_path)
    monkeypatch.setattr(backups, '_check', lambda db, pragma: False)
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
