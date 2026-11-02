"""WAL's own costs, bounded (spec 2026-10-29-store-wal-mode D2, plan Task 6): a keeper connection per long-running
process, a checkpoint that never waits behind a reader, the size limit on every other connection, and a notice when
the -wal grows past 64 MB. Nothing in a process that holds a connection opens the store's files outside SQLite."""
import asyncio
import builtins
import io
import os
import sqlite3
import subprocess
import sys
import threading
import time

from fastapi.testclient import TestClient

from superyak_peer.db import JOURNAL_SIZE_LIMIT, Store
from test_reading import TRY_SHARED_RANGE, store_in, timed

# Another process asks to take the store out of WAL, retrying "locked" for half a second, and prints the answer.
SWITCH_TO_DELETE = ('import sys\nfrom superyak_peer.journal_mode import switch_journal\ntry:\n'
                    '    print(switch_journal(sys.argv[1], "delete", active=lambda: [], retry_seconds=0.5))\n'
                    'except ValueError as error:\n    print(error)\n')


def andy(store):
    with store.reading() as db:
        return db.execute("SELECT id FROM users WHERE username='andy'").fetchone()[0]


def wal_size(store):
    return os.stat(f'{store.db_path}-wal').st_size


def test_the_keeper_holds_no_transaction_and_truncate_completes(tmp_path):
    """D2 (p7b, p8): the keeper runs its one PRAGMA and then nothing, so it holds no transaction and no cursor, and a
    TRUNCATE checkpoint completes with it open; and it keeps the -wal between commits, so no commit pays a last close.
    Mutation: the keeper leaving a SELECT's cursor unfinished (TRUNCATE answers busy), or left inside a BEGIN."""
    store = store_in(tmp_path, 'wal')
    who = andy(store)
    store.keep_open()
    try:
        assert store._keeper.in_transaction is False
        room = store.create_room(who, 'Ops')['id']
        for number in range(20):
            store.send_message(who, room, f'kept-{number}', 'a commit beside the keeper')
        assert wal_size(store) > 0  # every commit's close was not the last: the -wal is still there
        assert store.checkpoint() == (0, 0, 0)  # TRUNCATE: not busy, and nothing left in the log
        assert wal_size(store) == 0 and store._keeper.in_transaction is False
    finally:
        store.close_keeper()
    assert store._keeper is None
    store.close_keeper()  # a second close is a no-op


def test_checkpoint_never_waits_behind_a_long_reader(tmp_path):
    """D2 (p8b): a gated or unbounded TRUNCATE kept a post waiting 2.44 s behind a 3 s reader. With a reading() held 3 s
    and the gate held on another thread, checkpoint() takes no gate and its TRUNCATE gives up after its 100 ms wait
    (answering busy); then a post on a third thread, made while another checkpoint runs, commits within 400 ms.
    Mutation: checkpoint() under the gate, or its TRUNCATE at the Store's 30 s wait (each takes seconds)."""
    store = store_in(tmp_path, 'wal')
    who = andy(store)
    room = store.create_room(who, 'Ops')['id']
    reading, release_reader, holding, release_gate = (threading.Event() for _ in range(4))

    def reader():
        with store.reading() as db:
            db.execute('SELECT count(*) FROM messages').fetchone()
            reading.set()
            release_reader.wait(3)

    def gate():
        with store.dispatch_gate:
            holding.set()
            release_gate.wait(5)
    threads = [threading.Thread(target=reader), threading.Thread(target=gate)]
    threads[0].start()
    assert reading.wait(5)
    try:
        store.send_message(who, room, 'after-the-snapshot', 'a commit the reader cannot see')  # so TRUNCATE must wait
        threads[1].start()
        assert holding.wait(5)
        result, took = timed(store.checkpoint)
        release_gate.set()
        threads[1].join(10)
        assert took < 0.4 and result[0] == 1, (took, result)  # busy: the reader kept it from finishing
        start, posted = threading.Barrier(2), {}

        def post():
            start.wait(5)
            posted['took'] = timed(lambda: store.send_message(who, room, 'beside-a-checkpoint', 'a post'))[1]
        poster = threading.Thread(target=post)
        poster.start()
        start.wait(5)
        _, took = timed(store.checkpoint)
        poster.join(10)
        assert took < 0.4 and posted['took'] < 0.4, (took, posted)
        assert threads[0].is_alive()  # all of it inside the reader's 3 s
    finally:
        release_gate.set()
        release_reader.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(10)


def test_every_store_connection_sets_the_size_limit(tmp_path, monkeypatch):
    """D2: journal_size_limit is per connection, so every connection a Store opens sets it: transaction()'s, reading()'s
    (both of its branches) and checkpoint()'s. The keeper is exempt: it runs PRAGMA journal_mode and nothing else.
    Mutation: the limit gone from _transaction or from checkpoint(), or the keeper setting it too."""
    traced = []
    connect = sqlite3.connect

    def tracing(*args, **kwargs):
        db = connect(*args, **kwargs)
        statements = []
        db.set_trace_callback(statements.append)
        traced.append((db, statements))
        return db
    limit = f'PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT}'
    for mode in ('wal', 'delete'):
        store = store_in(tmp_path / mode, mode)
        traced.clear()
        monkeypatch.setattr(sqlite3, 'connect', tracing)
        with store.transaction() as db:
            assert db.execute('PRAGMA journal_size_limit').fetchone()[0] == JOURNAL_SIZE_LIMIT
        with store.reading() as db:
            assert db.execute('PRAGMA journal_size_limit').fetchone()[0] == JOURNAL_SIZE_LIMIT
        store.checkpoint()
        store.keep_open()
        monkeypatch.setattr(sqlite3, 'connect', connect)
        try:
            kept = [statements for db, statements in traced if db is store._keeper]
            others = [statements for db, statements in traced if db is not store._keeper]
        finally:
            store.close_keeper()
        assert kept == [['PRAGMA journal_mode']], mode
        assert len(others) == 3 and all(limit in statements for statements in others), (mode, others)


def test_each_long_running_process_opens_a_keeper(tmp_path, monkeypatch):
    """D2: the lighthouse (its lifespan), the door, federate and federation-listen each open one keeper after their Store
    is built, keep it for their life and close it at the end. Mutation: any one of the four keep_open calls gone."""
    import uvicorn
    from superyak_peer import __main__ as cli, dispatch
    from superyak_peer.app import create_app
    from superyak_peer.door import create_door
    from superyak_peer.federate import Federate
    from test_federation_outcomes import Clock, station
    events, stores = [], []
    keep_open, close_keeper = Store.keep_open, Store.close_keeper

    def opening(self):
        events.append(('open', self.data_dir.name))
        stores.append(self)
        keep_open(self)

    def closing(self):
        events.append(('close', self.data_dir.name))
        close_keeper(self)
    monkeypatch.setattr(Store, 'keep_open', opening)
    monkeypatch.setattr(Store, 'close_keeper', closing)
    lighthouse = create_app(tmp_path / 'lighthouse', allowed_origins=['http://testserver'])
    with TestClient(lighthouse, base_url='http://testserver'):
        events.append(('serving', lighthouse.state.store._keeper is not None))
    assert lighthouse.state.store._keeper is None
    door = create_door(tmp_path / 'door')
    with TestClient(door):
        events.append(('serving', door.state.store._keeper is not None))
    assert door.state.store._keeper is None
    pull = station(tmp_path / 'federate', 'mo', Clock(), mode='pull')
    pull[2].card(pull[1])  # federate needs identity.json, and never makes one
    locks, federation_lock = [], dispatch.federation_lock
    monkeypatch.setattr(dispatch, 'federation_lock', lambda data_dir: locks.append(federation_lock(data_dir)) or locks[-1])
    monkeypatch.setattr(Federate, 'run', lambda self: events.append(('serving', self.federation.store._keeper is not None)))
    try:
        cli.main(['federate', '--data-dir', str(pull[0].data_dir)])
    finally:
        for fd in locks:
            os.close(fd)
    push = station(tmp_path / 'listen', 'pat', Clock())
    push[2].card(push[1])
    push[0].claim_federation_mode('push')
    monkeypatch.setattr(uvicorn, 'run', lambda app, **options: events.append(('serving', stores[-1]._keeper is not None)))
    cli.main(['federation-listen', '--data-dir', str(push[0].data_dir), '--port', '0'])
    assert events == [item for name in ('lighthouse', 'door', 'federate', 'listen')
                      for item in (('open', name), ('serving', True), ('close', name))], events
    assert all(store._keeper is None for store in stores)


def test_the_lighthouse_checkpoints_every_hour_until_its_lifespan_ends(tmp_path, monkeypatch):
    """D2: the lighthouse checkpoints every CHECKPOINT_SECONDS (3,600) off the event loop, with its keeper open; a
    checkpoint that raises is logged and the next one still runs; the lifespan's exit stops them, then closes the
    keeper. Mutation: the checkpoint task left out (none runs), run on the loop, or the keeper closed before the
    checkpoints stop."""
    from superyak_peer import peer_routes
    from superyak_peer.app import create_app
    assert peer_routes.CHECKPOINT_SECONDS == 3600
    monkeypatch.setattr(peer_routes, 'CHECKPOINT_SECONDS', 0.05)
    ran = []

    def checkpoint(self):
        ran.append((self._keeper is not None, asyncio._get_running_loop() is None))
        if len(ran) == 1:
            raise sqlite3.OperationalError('disk I/O error')
        return 0, 0, 0
    monkeypatch.setattr(Store, 'checkpoint', checkpoint)
    app = create_app(tmp_path / 'lighthouse', allowed_origins=['http://testserver'])
    with TestClient(app, base_url='http://testserver'):
        deadline = time.monotonic() + 10
        while len(ran) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
    stopped = len(ran)
    time.sleep(0.3)
    assert stopped >= 3 and len(ran) == stopped, ran  # it went on past the failure, and stopped at the exit
    assert set(ran) == {(True, True)}  # with the keeper open, on a worker thread rather than the loop
    assert app.state.store._keeper is None


def test_a_second_store_open_keeps_the_keepers_lock(tmp_path):
    """The Tasks 4-5 re-check's M1: on Linux, closing any descriptor of the file drops every POSIX lock this process holds
    on it, the keeper's included. Store() creates peer.sqlite3 only when it is missing (O_EXCL), so a second Store beside
    a keeper opens nothing outside SQLite: another process is still refused SQLite's shared byte range and the switch
    out of WAL, and once the keeper closes, the same switch goes through. The fcntl probe sees a dropped lock whatever
    the SQLite; the switch alone doesn't (3.40.1 lets it through, 3.53.1's WAL defenses still refuse it). Mutation:
    __init__'s os.open and os.close on every start (the probe gets the range, and on 3.40.1 the switch succeeds)."""
    store = store_in(tmp_path, 'wal')
    probe = [sys.executable, '-c', TRY_SHARED_RANGE, str(store.db_path)]
    switch = [sys.executable, '-c', SWITCH_TO_DELETE, str(store.data_dir)]
    store.keep_open()
    try:
        assert subprocess.run(probe, capture_output=True, text=True, timeout=30).stdout == 'refused\n'  # the control
        Store(store.data_dir)
        after = subprocess.run(probe, capture_output=True, text=True, timeout=30)
        refused = subprocess.run(switch, capture_output=True, text=True, timeout=60)
    finally:
        store.close_keeper()
    assert after.stdout == 'refused\n', after.stderr
    assert 'locked' in refused.stdout, (refused.stdout, refused.stderr)
    switched = subprocess.run(switch, capture_output=True, text=True, timeout=60)
    assert switched.stdout == "('wal', 'delete')\n", (switched.stdout, switched.stderr)


def test_notices_say_when_the_wal_is_large(tmp_path, monkeypatch):
    """D2: station-notices raises one notice when peer.sqlite3-wal passes 64 MB, naming it, with no VACUUM in its advice
    (connector-apps pages receipts by rowid). The size is stubbed; it is read with stat, and nothing in the notice opens
    the store's files outside SQLite, the -wal and -shm above all (re-check 2 of Tasks 4-5). Mutation: the size read by
    opening the -wal (seen here), the notice at 64 MB exactly, or VACUUM in its words."""
    from superyak_peer.ships import WAL_NOTICE_BYTES
    store = store_in(tmp_path, 'wal')
    store.keep_open()
    try:
        store.create_room(andy(store), 'Ops')  # a commit beside the keeper, so the -wal is there
        wal = f'{store.db_path}-wal'
        assert 0 < wal_size(store) < WAL_NOTICE_BYTES == 67108864
        assert not [n for n in store.station_notices() if n['id'].startswith('wal-')]
        names = {os.path.basename(wal), os.path.basename(f'{store.db_path}-shm'), store.db_path.name}
        opened, stat = [], os.stat

        def watched(real):
            def opening(path, *args, **kwargs):
                if isinstance(path, (str, bytes, os.PathLike)) and os.path.basename(os.fsdecode(path)) in names:
                    opened.append(os.fsdecode(path))
                return real(path, *args, **kwargs)
            return opening

        def stubbed(size):
            def stubbing(path, *args, **kwargs):
                found = stat(path, *args, **kwargs)
                if isinstance(path, (str, os.PathLike)) and os.fspath(path) == wal:
                    return os.stat_result((*found[:6], size, *found[7:10]))
                return found
            return stubbing
        for module, name in ((builtins, 'open'), (io, 'open'), (os, 'open')):
            monkeypatch.setattr(module, name, watched(getattr(module, name)))
        monkeypatch.setattr(os, 'stat', stubbed(WAL_NOTICE_BYTES))
        assert not [n for n in store.station_notices() if n['id'].startswith('wal-')]  # at 64 MB: not past it
        monkeypatch.setattr(os, 'stat', stubbed(WAL_NOTICE_BYTES + 1))
        large = [n for n in store.station_notices() if n['id'].startswith('wal-')]
        monkeypatch.undo()
    finally:
        store.close_keeper()
    assert opened == []
    assert len(large) == 1 and 'peer.sqlite3-wal' in large[0]['text'] and 'VACUUM' not in large[0]['text'].upper()
