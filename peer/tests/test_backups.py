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
