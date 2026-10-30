"""Store.reading() (spec 2026-10-29-store-wal-mode D3, plan Task 4): one snapshot, gate-free only in WAL, never nested
with the gate in either mode, and unable to write; the station identity is created only under the gate."""
from contextlib import closing, contextmanager
import sqlite3
import threading
import time

import pytest

from superyak_peer.common import Problem
from superyak_peer.db import Store
from superyak_peer.journal_mode import switch_journal


def store_in(tmp_path, mode, **kwargs):
    store = Store(tmp_path / 'station', **kwargs)
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    if mode == 'wal':
        switch_journal(store.data_dir, 'wal', active=lambda: [])
    else:
        with closing(sqlite3.connect(store.db_path)) as db:  # the suite may run in WAL; these cases pin a mode
            db.execute('PRAGMA journal_mode=DELETE').fetchone()
    return store


@contextmanager
def gate_and_write_held(store):
    """Another thread holds the dispatch gate and an open BEGIN IMMEDIATE write until the block ends."""
    ready, release = threading.Event(), threading.Event()

    def hold():
        with store.dispatch_gate:
            db = sqlite3.connect(store.db_path, isolation_level=None)
            db.execute('BEGIN IMMEDIATE')
            db.execute("INSERT INTO system_meta(key, value) VALUES('held', '1')")
            ready.set()
            release.wait(10)
            db.execute('ROLLBACK')
            db.close()
    holder = threading.Thread(target=hold)
    holder.start()
    assert ready.wait(5)
    try:
        yield
    finally:
        release.set()
        holder.join(10)


def timed(call):
    started = time.monotonic()
    result = call()
    return result, time.monotonic() - started


def count_users(store):
    with store.reading() as db:
        return db.execute('SELECT count(*) FROM users').fetchone()[0]


def test_reading_takes_no_gate_in_wal(tmp_path):
    store = store_in(tmp_path, 'wal')
    before = count_users(store)
    with gate_and_write_held(store):
        count, took = timed(lambda: count_users(store))
    assert count == before and took < 1.0  # a gated read would wait out the held gate, up to 10 s


def test_reading_takes_the_gate_in_rollback_mode(tmp_path):
    store = store_in(tmp_path, 'delete')
    before, result = count_users(store), {}
    with gate_and_write_held(store):
        reader = threading.Thread(target=lambda: result.update(count=count_users(store)))
        reader.start()
        time.sleep(0.3)
        assert reader.is_alive()  # waiting on the gate the other thread holds
    reader.join(10)
    assert result['count'] == before


def test_rollback_reading_takes_the_gate_before_touching_sqlite(tmp_path):
    """The Tasks 4-5 review's S3: in rollback mode reading() reads the mode from the file's header, takes the gate, and
    only then opens SQLite, as transaction() does. So a short SQLite wait (the lessons query's `busy_until`) can't fail
    it behind a write that holds the gate and SQLite's EXCLUSIVE lock: it waits at the gate instead. Mutation: the mode
    probed with a PRAGMA before the gate ("database is locked" after the short wait)."""
    store = store_in(tmp_path, 'delete')
    short = Store(store.data_dir, busy_until=time.monotonic() + 0.2)
    ready = threading.Event()

    def hold():
        with short.dispatch_gate:
            db = sqlite3.connect(short.db_path, isolation_level=None)
            db.execute('BEGIN EXCLUSIVE')
            ready.set()
            time.sleep(0.6)
            db.execute('ROLLBACK')
            db.close()
    holder = threading.Thread(target=hold)
    holder.start()
    assert ready.wait(5)
    try:
        with short.reading() as db:
            assert db.execute('SELECT count(*) FROM users').fetchone()[0] >= 1
    finally:
        holder.join(10)


def test_one_reading_is_one_snapshot(tmp_path):
    """WAL only: in rollback mode the commit below would wait for the reader."""
    store = store_in(tmp_path, 'wal')
    before = count_users(store)
    with store.reading() as db:
        first = db.execute('SELECT count(*) FROM users').fetchone()[0]
        writer = threading.Thread(target=lambda: store.create_user('jenn', 'Jenn', 'long-password-jenn'))
        writer.start()
        writer.join(10)
        second = db.execute('SELECT count(*) FROM users').fetchone()[0]
    assert first == second == before
    assert count_users(store) == before + 1


def test_an_open_snapshot_does_not_delay_a_gated_commit_in_wal(tmp_path):
    store = store_in(tmp_path, 'wal')
    took = {}

    def write():
        started = time.monotonic()
        store.create_user('jenn', 'Jenn', 'long-password-jenn')
        took['commit'] = time.monotonic() - started
    with store.reading() as db:
        db.execute('SELECT count(*) FROM users').fetchone()
        writer = threading.Thread(target=write)
        writer.start()
        writer.join(10)
        time.sleep(0.3)
    assert took['commit'] < 2.0  # a commit with its password hash: it never waited for the open snapshot


@pytest.mark.parametrize('mode', ['wal', 'delete'])
def test_reading_refuses_a_held_gate_and_nesting_in_both_modes(tmp_path, mode):
    store = store_in(tmp_path, mode)
    with store.transaction():
        with pytest.raises(RuntimeError, match='gate'):
            with store.reading():
                pass
    with store.dispatch_gate:
        with pytest.raises(RuntimeError, match='gate'):
            with store.reading():
                pass
    with store.reading():
        with pytest.raises(RuntimeError, match='inside reading'):
            with store.reading():
                pass


@pytest.mark.parametrize('mode', ['wal', 'delete'])
def test_transaction_refuses_inside_reading(tmp_path, mode):
    store = store_in(tmp_path, mode)
    with store.reading():
        with pytest.raises(RuntimeError, match='inside reading'):
            with store.transaction():
                pass
    with store.transaction() as db:  # and works again once the reading has ended
        assert db.execute("SELECT count(*) FROM users WHERE username='andy'").fetchone()[0] == 1


def test_transaction_works_after_a_reading_that_raised(tmp_path, monkeypatch):
    """A reading that fails before it starts leaves no depth behind (the plan re-check's R-S4)."""
    store = store_in(tmp_path, 'wal')
    real = store._check_paths
    monkeypatch.setattr(store, '_check_paths', lambda: (_ for _ in ()).throw(ValueError('Symlinked state')))
    with pytest.raises(ValueError):
        with store.reading():
            pass
    monkeypatch.setattr(store, '_check_paths', real)
    assert not store.in_reading()
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM users WHERE username='andy'").fetchone()[0] == 1
    with store.reading():
        with pytest.raises(RuntimeError, match='inside reading'):
            with store.transaction():
                pass


def test_check_paths_refuses_a_symlinked_wal(tmp_path):
    store = store_in(tmp_path, 'wal')
    (tmp_path / 'elsewhere').write_bytes(b'')
    wal = store.data_dir / 'peer.sqlite3-wal'
    wal.unlink(missing_ok=True)
    wal.symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(ValueError, match='ymlink'):
        with store.reading():
            pass
    assert not store.in_reading()


@pytest.mark.parametrize('sql', ["INSERT INTO system_meta(key, value) VALUES('x', 'y')",
                                 "UPDATE users SET name='Changed'",
                                 'DELETE FROM users',
                                 'CREATE TEMP TABLE scratch(x)'])
@pytest.mark.parametrize('mode', ['wal', 'delete'])
def test_reading_refuses_sql_writes(tmp_path, mode, sql):
    store = store_in(tmp_path, mode)
    before = count_users(store)
    with pytest.raises(sqlite3.OperationalError):
        with store.reading() as db:
            db.execute(sql)
    assert count_users(store) == before


def test_reading_maps_errors_as_transaction_does(tmp_path):
    store = store_in(tmp_path, 'wal')
    with pytest.raises(Problem) as refused:
        with store.reading() as db:
            db.execute('SELECT ?', ('\ud800',)).fetchone()
    assert refused.value.status == 400


def test_transaction_wait_is_per_call(tmp_path):
    """A per-call wait bounds one transaction's SQLite wait; the next plain one keeps the Store's rule."""
    store = store_in(tmp_path, 'delete')
    holder = sqlite3.connect(store.db_path, isolation_level=None)
    holder.execute('BEGIN IMMEDIATE')
    try:
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            with store.transaction(wait=0.5) as db:
                db.execute("INSERT INTO system_meta(key, value) VALUES('w', '1')")
        assert time.monotonic() - started < 2
    finally:
        holder.execute('ROLLBACK')
        holder.close()
    seen = {}
    real = sqlite3.connect

    def watching(*args, **kwargs):
        seen['timeout'] = kwargs.get('timeout')
        return real(*args, **kwargs)
    sqlite3.connect = watching
    try:
        with store.transaction() as db:
            db.execute('SELECT 1').fetchone()
    finally:
        sqlite3.connect = real
    assert seen['timeout'] == 30


def test_identity_is_not_created_without_the_gate(tmp_path):
    """On a WAL store (in rollback mode reading() holds the gate, so the rule would allow it): neither a reading nor a raw
    connection with no gate creates identity.json; with one there, both load it."""
    store = store_in(tmp_path, 'wal', signing=False)
    identity = store.data_dir / 'identity.json'
    assert not identity.exists()
    with store.reading() as db:
        with pytest.raises(RuntimeError, match='gate'):
            store._station_identity(db)
    with closing(sqlite3.connect(store.db_path)) as raw:
        with pytest.raises(RuntimeError, match='gate'):
            store._station_identity(raw)
    assert not identity.exists()
    made = store._station_identity()  # its own gated transaction creates it
    assert identity.exists()
    store._identity = None
    with store.reading() as db:
        assert store._station_identity(db).peer_id == made.peer_id
    store._identity = None
    with closing(sqlite3.connect(store.db_path)) as raw:
        assert store._station_identity(raw).peer_id == made.peer_id
