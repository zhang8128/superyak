"""Federation pull, plan Task 8: the processes. One process syncs a data directory, `serve --sync` or `federate`
(dispatch.federation_lock)."""
import os
import subprocess
import sys
from contextlib import contextmanager

import pytest


def test_a_second_sync_process_exits_and_the_lock_is_private(tmp_path):
    from superyak_peer.db import Store
    from superyak_peer.dispatch import federation_lock
    data = tmp_path / 'peer'
    Store(data)
    held = federation_lock(data)
    try:
        with pytest.raises(ValueError, match='another process already syncs this directory'):
            federation_lock(data)
        done = subprocess.run([sys.executable, '-m', 'superyak_peer', 'serve', '--data-dir', str(data), '--sync',
                               '--port', '0'], capture_output=True, text=True, timeout=60)
        assert done.returncode == 1 and 'another process already syncs this directory' in done.stderr
    finally:
        os.close(held)
    assert (data / 'federation.lock').stat().st_mode & 0o777 == 0o600
    os.close(federation_lock(data))  # released with its descriptor, as when the holding process ends


def test_the_lock_never_follows_a_link(tmp_path):
    from superyak_peer.dispatch import federation_lock
    (tmp_path / 'elsewhere').write_text('')
    (tmp_path / 'federation.lock').symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(OSError):
        federation_lock(tmp_path)


# Task 8d: federate (plan P4, P7, P9, P13, nit 18)

class Wake:
    """A clock federate reads and a sleep that moves it, so passes run without waiting."""
    def __init__(self, at=1_000_000.0):
        self.at = at

    def __call__(self):
        return self.at

    def sleep(self, seconds):
        self.at += seconds


def puller(tmp_path):
    from superyak_peer.identity import pairing_code
    from test_federation_outcomes import Clock, station
    clock = Clock()
    a = station(tmp_path / 'a', 'alice', clock)
    mac = station(tmp_path / 'mac', 'mo', clock, mode='pull')
    a[2].pair(a[1], mac[2].card(mac[1]), code=pairing_code(mac[2].card(mac[1])))
    mac[2].pair(mac[1], a[2].card(a[1]), code=pairing_code(a[2].card(a[1])))
    return clock, a, mac


def test_federate_pulls_at_start_after_a_recovery_and_after_a_sleep_overrun(tmp_path, monkeypatch):
    from superyak_peer.federate import Federate
    clock, a, mac = puller(tmp_path)
    wake, pulls, answers = Wake(), [], [{'next': 2}, {'next': 60}, {'next': 60}, {'next': 60}]
    monkeypatch.setattr(mac[2], 'pull_once', lambda card, send=None: pulls.append(wake()) or answers.pop(0))
    loop = Federate(mac[2], clock=wake, sleep=wake.sleep)
    loop.run_pass()                                   # at start: nothing is due yet, so it pulls
    wake.sleep(1), loop.run_pass()                    # 1 s later its 2 s backoff isn't over
    wake.sleep(1), loop.run_pass()                    # it is now: the retry recovers, and the next pull is 60 s off
    wake.sleep(5), loop.run_pass()                    # a normal pass: not due
    wake.sleep(5 + 31), loop.run_pass()               # the machine slept past the pass by more than 30 s: at once
    assert pulls == [1_000_000.0, 1_000_002.0, 1_000_043.0]


def test_federate_survives_a_locked_store_in_its_own_reads(tmp_path, monkeypatch):
    """Rio Grande's SF4: run_pass's own reads (the sync requests, the mode, the cards) sat outside every try, and run()
    had none, so one locked database ended federate: a restart, an alert, and the acks held in memory dropped. A pass that
    raises is logged now, and the next one goes on."""
    import sqlite3
    from superyak_peer.federate import Federate
    clock, a, mac = puller(tmp_path)
    wake = Wake()
    loop = Federate(mac[2], clock=wake, sleep=wake.sleep)
    real, calls = loop._requests, []

    def requests():
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError('database is locked')
        loop.stopping = len(calls) >= 3
        return real()
    monkeypatch.setattr(loop, '_requests', requests)
    loop.run()
    assert len(calls) == 3

def test_federate_survives_a_pull_that_raises_and_still_pushes(tmp_path, monkeypatch):
    from superyak_peer.federate import Federate
    clock, a, mac = puller(tmp_path)
    synced = []

    def broken(card, send=None):
        raise RuntimeError('the pull broke')
    monkeypatch.setattr(mac[2], 'pull_once', broken)
    monkeypatch.setattr(mac[2], 'sync_once', lambda **k: synced.append(1) or {})
    loop = Federate(mac[2], clock=Wake(), sleep=lambda s: None)
    loop.run_pass()
    loop.run_pass()
    assert len(synced) == 2


def test_a_push_peer_runs_federate_without_pulling(tmp_path, monkeypatch):
    from superyak_peer.federate import Federate
    clock, a, mac = puller(tmp_path)
    monkeypatch.setattr(a[2], 'pull_once', lambda card, send=None: (_ for _ in ()).throw(AssertionError('pulled')))
    synced = []
    monkeypatch.setattr(a[2], 'sync_once', lambda **k: synced.append(1) or {})
    Federate(a[2], clock=Wake(), sleep=lambda s: None).run_pass()
    assert synced == [1]


def test_federate_creates_nothing_without_a_database_and_takes_the_sync_lock(tmp_path):
    from superyak_peer.dispatch import federation_lock
    empty = tmp_path / 'typo'
    empty.mkdir()
    done = subprocess.run([sys.executable, '-m', 'superyak_peer', 'federate', '--data-dir', str(empty)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 1 and 'peer.sqlite3' in done.stderr and list(empty.iterdir()) == []
    clock, a, mac = puller(tmp_path)
    held = federation_lock(mac[0].data_dir)
    try:
        done = subprocess.run([sys.executable, '-m', 'superyak_peer', 'federate', '--data-dir', str(mac[0].data_dir)],
                              capture_output=True, text=True, timeout=60)
    finally:
        os.close(held)
    assert done.returncode == 1 and 'another process already syncs this directory' in done.stderr


def test_federate_runs_its_passes_and_sigterm_ends_it_cleanly(tmp_path):
    """The real process on a pull peer: it starts, runs passes (its peer's address can't be dialled here, so each pull
    fails, is logged and backs off), and SIGTERM ends it between steps with exit 0 and no traceback."""
    import signal
    import time
    clock, a, mac = puller(tmp_path)
    proc = subprocess.Popen([sys.executable, '-m', 'superyak_peer', 'federate', '--data-dir', str(mac[0].data_dir)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(3)
    proc.send_signal(signal.SIGTERM)
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 0, err
    assert 'Traceback (most recent call last)' not in err.split('A pull from')[0]  # only a logged pull failure, if any
    assert not (mac[0].data_dir / 'crossing.sock').exists()  # no --crossing-socket, no socket (crossing plan P9)


# Task 8e: "Check delivery now", POST /api/sync (plan P11, nit 9)

def sync_app(tmp_path, *, sync_enabled):
    from starlette.testclient import TestClient
    from superyak_peer.app import create_app
    app = create_app(tmp_path / 'peer', allowed_origins=['http://testserver'], sync_enabled=sync_enabled)
    app.state.store.create_user('owner', 'Owner', 'long-password-owner', is_admin=True)
    client = TestClient(app, base_url='http://testserver')
    client.headers['origin'] = 'http://testserver'
    return app, client


def sign_in(client):
    answer = client.post('/api/login', json={'username': 'owner', 'password': 'long-password-owner'})
    client.headers['x-csrf-token'] = answer.json()['csrf_token']


def test_check_delivery_now_without_sync_never_dials_and_makes_every_peer_due(tmp_path, monkeypatch):
    """With federate holding the lock, the lighthouse never dials: the button makes every peer due, and federate's next
    pass delivers."""
    from superyak_peer import transport
    app, client = sync_app(tmp_path, sync_enabled=False)
    sign_in(client)

    def dial(*args, **kwargs):
        raise AssertionError('the lighthouse dialled without --sync')
    monkeypatch.setattr(transport, 'send_pinned', dial)
    monkeypatch.setattr(transport, 'pull_pinned', dial)
    monkeypatch.setattr(app.state.federation, 'sync_once', dial)
    store = app.state.store
    with store.transaction() as db:
        db.execute("INSERT INTO peer_delivery(peer_id, mode, failures, next_attempt) VALUES(?, 'push', 3, ?)",
                   ('a' * 64, store.clock() + 1000))
    answer = client.post('/api/sync')
    assert answer.status_code == 200 and answer.json()['enabled'] is False
    with store.transaction() as db:
        assert db.execute('SELECT next_attempt FROM peer_delivery').fetchone()[0] is None
        assert db.execute("SELECT value FROM peer_meta WHERE key='sync_requests'").fetchone()[0] == '1'
    client.post('/api/sync')
    with store.transaction() as db:
        assert db.execute("SELECT value FROM peer_meta WHERE key='sync_requests'").fetchone()[0] == '2'


def test_check_delivery_now_runs_its_session_and_store_calls_in_workers(tmp_path, monkeypatch):
    """fix:actor-off-the-event-loop's shape (Rio Grande's): a store waiting on its lock never stalls the lighthouse.
    The session check comes first, then making peers due, then the status, each in a worker. Mutation: any of the three
    called on the loop."""
    import asyncio
    app, client = sync_app(tmp_path, sync_enabled=False)
    sign_in(client)
    store, fed, seen = app.state.store, app.state.federation, []

    def recording(name, real):
        def call(*args):
            try:
                asyncio.get_running_loop()
                seen.append((name, 'loop'))
            except RuntimeError:
                seen.append((name, 'worker'))
            return real(*args)
        return call
    monkeypatch.setattr(store, 'session', recording('session', store.session))
    monkeypatch.setattr(fed, 'make_due', recording('make_due', fed.make_due))
    monkeypatch.setattr(fed, 'status', recording('status', fed.status))
    assert client.post('/api/sync').status_code == 200
    assert seen == [('session', 'worker'), ('make_due', 'worker'), ('status', 'worker')]


def test_check_delivery_now_with_sync_answers_after_the_pass_it_woke(tmp_path, monkeypatch):
    import time
    from superyak_peer.federate import Federate
    app, client = sync_app(tmp_path, sync_enabled=True)
    passes = []

    def run_pass(self):
        passes.append(time.monotonic())
        time.sleep(0.2)
    monkeypatch.setattr(Federate, 'run_pass', run_pass)
    with client:                                      # the lifespan runs the worker
        sign_in(client)
        time.sleep(0.5)                               # its first pass is over, and it waits up to 5 s for the next
        began = time.monotonic()
        answer = client.post('/api/sync')
        took = time.monotonic() - began
    assert answer.status_code == 200 and answer.json()['enabled'] is True
    assert any(at >= began for at in passes) and 0.2 <= took < 5


def test_the_sync_worker_survives_a_pass_that_raises(tmp_path, monkeypatch):
    import time
    from superyak_peer.federate import Federate
    app, client = sync_app(tmp_path, sync_enabled=True)
    calls = []

    def run_pass(self):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('a pass broke')
    monkeypatch.setattr(Federate, 'run_pass', run_pass)
    with client:
        sign_in(client)
        time.sleep(0.3)
        assert client.post('/api/sync').status_code == 200
    assert len(calls) >= 2


def test_federate_pulls_at_once_after_a_push_to_that_peer_succeeds(tmp_path, monkeypatch):
    """Spec §1 (Rio Grande's N2): a push that succeeds shows the listener is back, so its pull goes at the next pass
    rather than waiting out the 60 s."""
    from superyak_peer.federate import Federate
    clock, a, mac = puller(tmp_path)
    wake, pulls = Wake(), []
    monkeypatch.setattr(mac[2], 'pull_once', lambda card, send=None: pulls.append(wake()) or {'next': 60})
    listener = a[2].identity.peer_id

    def pushed(send=None):
        with mac[0].transaction() as db:
            db.execute('UPDATE peer_delivery SET last_success=? WHERE peer_id=?', (wake(), listener))
        return {}
    loop = Federate(mac[2], clock=wake, sleep=wake.sleep)
    loop.run_pass()                                   # at start
    wake.sleep(5), loop.run_pass()                    # not due: 60 s off
    monkeypatch.setattr(mac[2], 'sync_once', pushed)
    wake.sleep(5), loop.run_pass()                    # a push to it succeeds in this pass
    monkeypatch.setattr(mac[2], 'sync_once', lambda send=None: {})
    wake.sleep(5), loop.run_pass()                    # so its pull goes now
    wake.sleep(5), loop.run_pass()                    # and once
    assert pulls == [1_000_000.0, 1_000_015.0]

def test_federate_pulls_at_once_after_check_delivery_now(tmp_path, monkeypatch):
    from superyak_peer.federate import Federate
    clock, a, mac = puller(tmp_path)
    wake, pulls = Wake(), []
    monkeypatch.setattr(mac[2], 'pull_once', lambda card, send=None: pulls.append(wake()) or {'next': 60})
    loop = Federate(mac[2], clock=wake, sleep=wake.sleep)
    loop.run_pass()
    wake.sleep(5), loop.run_pass()                    # not due: 60 s off
    mac[2].make_due()
    wake.sleep(5), loop.run_pass()                    # asked: at once
    wake.sleep(5), loop.run_pass()                    # once per ask
    assert pulls == [1_000_000.0, 1_000_010.0]


# Task 8f: end to end over real HTTPS. Two `federation-listen` processes on loopback, each behind its own certificate,
# and a pull peer in process that only dials out: what a room message, its reply and a withdrawal take between them.

@contextmanager
def listening_peer(path, name):
    """A push peer whose card names a real `federation-listen` process on a loopback port."""
    import socket
    import time
    from test_federation_outcomes import station
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    store, user, fed = station(path, name, time.time)
    store.claim_federation_mode('push')
    fed.endpoint = f'https://127.0.0.1:{port}'
    log = path.parent / f'{name}-listen.log'
    with log.open('wb') as out:
        process = subprocess.Popen([sys.executable, '-m', 'superyak_peer', 'federation-listen', '--data-dir', str(path),
                                    '--port', str(port)], stdout=out, stderr=out)
    try:
        deadline = time.monotonic() + 30  # a loaded Pi starts a process slowly
        while True:
            assert process.poll() is None, log.read_text()
            try:
                socket.create_connection(('127.0.0.1', port), timeout=1).close()
                break
            except OSError:
                assert time.monotonic() < deadline, log.read_text()
                time.sleep(0.05)
        yield store, user, fed
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_end_to_end_over_real_https_pull_push_and_withdrawal(tmp_path):
    import time
    from superyak_peer.federate import Federate
    from superyak_peer.identity import pairing_code
    from test_federation_outcomes import share, station
    mo = station(tmp_path / 'mo', 'mo', time.time, mode='pull')
    with listening_peer(tmp_path / 'a', 'alice') as a, listening_peer(tmp_path / 'pat', 'pat') as pat:
        contacts = {}
        for key, peer in (('a', a), ('pat', pat)):
            card, mine = peer[2].card(peer[1]), mo[2].card(mo[1])
            contacts[key] = peer[2].pair(peer[1], mine, code=pairing_code(mine))['id']
            mo[2].pair(mo[1], card, code=pairing_code(card))
        room = a[0].create_room(a[1], 'Across HTTPS', [contacts['a']])
        a[0].send_message(a[1], room['id'], 'one', 'hello mac')
        share(pat, contacts['pat'], 'from pat')
        loop = Federate(mo[2])

        loop.run_pass()                                   # a pull from each listener
        remote = mo[0].list_rooms(mo[1])[0]
        assert [m['body'] for m in mo[0].get_room(mo[1], remote['id'])['messages']] == ['hello mac']
        assert [layer['body'] for layer in mo[0].shared_layers(mo[1])] == ['from pat']

        mo[0].send_message(mo[1], remote['id'], 'reply', 'hello back')
        loop.run_pass()                                   # no pull is due; the reply is pushed to alice's listener
        assert [m['body'] for m in a[0].get_room(a[1], room['id'])['messages']] == ['hello mac', 'hello back']

        a[0].remove_participant(a[1], room['id'], contacts['a'])
        mo[2].make_due()                                  # Check delivery now
        loop.run_pass()                                   # the next pull carries the withdrawal
        assert mo[0].list_rooms(mo[1]) == []
        assert [layer['body'] for layer in mo[0].shared_layers(mo[1])] == ['from pat']


@pytest.mark.parametrize('char', ['\x01', '\U0001F600'], ids=['control', 'astral'])
def test_the_largest_release_arrives_by_pull_end_to_end(tmp_path, char):
    """Rio Grande's MF2, end to end as Serenity asked: a real federation-listen process, its TLS and pull_pinned's cap,
    so the bytes P5 counts are the bytes that cross the wire. The largest release the limits allow, in U+0001 (P5's worst
    case) and in emoji, which answered over PULL_CAP while the listener sent ASCII escapes, arrives at the pull peer."""
    import time
    from superyak_peer.federate import Federate
    from superyak_peer.identity import pairing_code
    from test_federation_outcomes import station
    from test_listener import largest_release
    mo = station(tmp_path / 'mo', 'mo', time.time, mode='pull')
    with listening_peer(tmp_path / 'a', 'alice') as a:
        mine, card = mo[2].card(mo[1]), a[2].card(a[1])
        contact = a[2].pair(a[1], mine, code=pairing_code(mine))['id']
        mo[2].pair(mo[1], card, code=pairing_code(card))
        largest_release(a, contact, char)
        Federate(mo[2]).run_pass()
        assert [(layer['title'], layer['body']) for layer in mo[0].shared_layers(mo[1])] == [(char * 200, char * 100_000)]


def test_federate_and_the_listener_refuse_a_lost_identity_and_make_none(tmp_path):
    """Plan Task 8, G4b for both commands (found missing on the spec walk after Rio Grande's section 2): a store that holds
    signed records and lost identity.json is refused before any Store opens, and neither command makes a new identity,
    which would void those records. The store is made as a pre-pull one, so a Store opened before the refusal would
    migrate it: every file is byte for byte as it was (the re-check's N8; Store() migrates before it refuses)."""
    import hashlib
    from test_signatures import signed_station
    store, owner, ship, room, docking = signed_station(tmp_path)
    store.claim_federation_mode('push')
    with store.transaction() as db:
        db.execute('DROP TABLE peer_delivery')  # as a store from before federation pull has it
    (store.data_dir / 'identity.json').unlink()

    def files():  # leaving out the -wal and -shm a read-only open of a WAL store makes, which are SQLite's own
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in store.data_dir.iterdir()
                if path.is_file() and not path.name.endswith(('-wal', '-shm'))}
    before = files()
    for command, extra in (('federate', []), ('federation-listen', ['--port', '0'])):
        done = subprocess.run([sys.executable, '-m', 'superyak_peer', command, '--data-dir', str(store.data_dir), *extra],
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 1 and 'holds signed records' in done.stderr, (command, done.stderr)
        assert not (store.data_dir / 'identity.json').exists(), command
        assert files() == before, command


# Ship home and crossing plan, Task 7: crossing.sock (P9, S3). One Unix socket, only under --crossing-socket, on its
# own supervised thread; one owner per directory by crossing.lock; a held lock starts the process without the socket
# (the plan re-check's item 4), so events and pulls keep flowing.

import json as _json
import socket as _socket
import stat as _stat
import tempfile as _tempfile
import time as _time
from pathlib import Path as _Path


def short_puller():
    """puller() in a short directory: a Unix socket path must stay under 108 bytes."""
    return puller(_Path(_tempfile.mkdtemp(prefix='x')))


def over_socket(path, raw, timeout=5):
    with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        client.sendall(raw + b'\n')
        data = b''
        while not data.endswith(b'\n'):
            part = client.recv(65536)
            if not part:
                break
            data += part
    return data


def wait_until(condition, seconds=20):
    end = _time.monotonic() + seconds
    while not condition():
        if _time.monotonic() > end:
            return False
        _time.sleep(0.02)
    return True


def started_socket(fed):
    from superyak_peer.crossing import CrossingSocket
    sockets = CrossingSocket(fed)
    sockets.start()
    assert wait_until(lambda: sockets.serving)
    return sockets


LINE = b'{"deadline_ms": 2000}'


def test_federate_binds_no_network_socket_and_crossing_sock_only_under_the_flag(monkeypatch):
    """Spec 2.1 and P9: "no network bind; one Unix bind at crossing.sock only under --crossing-socket". Binds and
    listens are recorded, not refused; without the socket the list is empty."""
    from superyak_peer.federate import Federate
    clock, a, mac = short_puller()
    bound, real_bind, real_listen = [], _socket.socket.bind, _socket.socket.listen

    def bind(self, address):
        bound.append(('bind', self.family, address))
        return real_bind(self, address)

    def listen(self, *args):
        bound.append(('listen', self.family, None))
        return real_listen(self, *args)
    monkeypatch.setattr(_socket.socket, 'bind', bind)
    monkeypatch.setattr(_socket.socket, 'listen', listen)
    monkeypatch.setattr(mac[2], 'pull_once', lambda card, send=None: {'next': 60})
    Federate(mac[2], clock=Wake(), sleep=lambda s: None).run_pass()
    assert bound == []
    sockets = started_socket(mac[2])
    try:
        Federate(mac[2], clock=Wake(), sleep=lambda s: None).run_pass()
    finally:
        sockets.stop()
    assert bound == [('bind', _socket.AF_UNIX, str(mac[0].data_dir / 'crossing.sock')), ('listen', _socket.AF_UNIX, None)]


def test_the_socket_is_private_and_a_request_reaches_ask(monkeypatch):
    from superyak_peer import crossing
    clock, a, mac = short_puller()
    asked = []
    monkeypatch.setattr(crossing, 'ask', lambda fed, raw: asked.append((fed, raw)) or {'ok': False, 'code': 'X'})
    sockets = started_socket(mac[2])
    try:
        path = mac[0].data_dir / 'crossing.sock'
        mode = path.lstat().st_mode
        assert _stat.S_ISSOCK(mode) and mode & 0o777 == 0o600
        assert (mac[0].data_dir / 'crossing.lock').stat().st_mode & 0o777 == 0o600
        assert _json.loads(over_socket(path, LINE)) == {'ok': False, 'code': 'X'}
    finally:
        sockets.stop()
    assert asked == [(mac[2], LINE)]
    assert not (mac[0].data_dir / 'crossing.sock').exists()  # stop removes it


def test_a_handler_that_raises_is_logged_and_the_socket_answers_again(monkeypatch, caplog):
    from superyak_peer import crossing
    clock, a, mac = short_puller()
    sockets = started_socket(mac[2])
    path = mac[0].data_dir / 'crossing.sock'
    try:
        monkeypatch.setattr(crossing, 'ask', lambda fed, raw: (_ for _ in ()).throw(RuntimeError('the handler broke')))
        assert over_socket(path, LINE) == b''
        assert any('crossing.sock' in r.getMessage() and r.levelname == 'ERROR' for r in caplog.records)
        monkeypatch.setattr(crossing, 'ask', lambda fed, raw: {'ok': False, 'code': 'BACK'})
        assert _json.loads(over_socket(path, LINE)) == {'ok': False, 'code': 'BACK'}
    finally:
        sockets.stop()


def test_a_server_that_dies_is_logged_and_comes_back_within_2_s_while_passes_run(monkeypatch, caplog):
    from superyak_peer import crossing
    from superyak_peer.federate import Federate
    clock, a, mac = short_puller()
    monkeypatch.setattr(crossing, 'ask', lambda fed, raw: {'ok': False, 'code': 'ALIVE'})
    monkeypatch.setattr(mac[2], 'pull_once', lambda card, send=None: {'next': 60})
    synced = []
    monkeypatch.setattr(mac[2], 'sync_once', lambda **k: synced.append(1) or {})
    sockets = started_socket(mac[2])
    try:
        dead = sockets._server

        def boom():
            raise RuntimeError('the server died')
        dead.service_actions = boom
        died = _time.monotonic()
        loop = Federate(mac[2], clock=Wake(), sleep=lambda s: None)
        loop.run_pass()
        assert wait_until(lambda: sockets._server is not dead and sockets.serving, 5)
        assert _json.loads(over_socket(mac[0].data_dir / 'crossing.sock', LINE)) == {'ok': False, 'code': 'ALIVE'}
        assert _time.monotonic() - died < 2
        loop.run_pass()
        assert synced == [1, 1]
        assert any('crossing.sock' in r.getMessage() and 'restart' in r.getMessage() for r in caplog.records)
    finally:
        sockets.stop()


def test_a_stale_socket_with_no_lock_holder_is_replaced(monkeypatch):
    from superyak_peer import crossing
    clock, a, mac = short_puller()
    path = mac[0].data_dir / 'crossing.sock'
    stale = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    stale.bind(str(path))
    stale.close()  # its file stays, with nobody behind it
    monkeypatch.setattr(crossing, 'ask', lambda fed, raw: {'ok': False, 'code': 'NEW'})
    sockets = started_socket(mac[2])
    try:
        assert _json.loads(over_socket(path, LINE)) == {'ok': False, 'code': 'NEW'}
    finally:
        sockets.stop()


def test_a_symlinked_socket_path_or_lock_is_refused():
    from superyak_peer.crossing import CrossingSocket, crossing_lock
    clock, a, mac = short_puller()
    data = mac[0].data_dir
    (data / 'elsewhere').write_text('')
    (data / 'crossing.sock').symlink_to(data / 'elsewhere')
    with pytest.raises(ValueError, match='symlink'):
        CrossingSocket(mac[2]).start()
    (data / 'crossing.sock').unlink()
    (data / 'crossing.lock').unlink()
    (data / 'crossing.lock').symlink_to(data / 'elsewhere')
    with pytest.raises(OSError):
        crossing_lock(data)


def test_a_second_owner_is_refused_and_the_first_socket_still_answers(monkeypatch):
    """S3: only crossing.lock's holder binds or unlinks crossing.sock, so no process takes over a live one."""
    from superyak_peer import crossing
    clock, a, mac = short_puller()
    monkeypatch.setattr(crossing, 'ask', lambda fed, raw: {'ok': False, 'code': 'FIRST'})
    sockets = started_socket(mac[2])
    try:
        with pytest.raises(ValueError, match='another process already serves crossing.sock'):
            crossing.CrossingSocket(mac[2]).start()
        assert crossing.start_crossing_socket(mac[2]) is None  # the commands' way in: logged, and no socket
        assert _json.loads(over_socket(mac[0].data_dir / 'crossing.sock', LINE)) == {'ok': False, 'code': 'FIRST'}
    finally:
        sockets.stop()


def test_federate_with_the_flag_serves_crossing_sock_and_sigterm_ends_both():
    import signal
    clock, a, mac = short_puller()
    path = mac[0].data_dir / 'crossing.sock'
    proc = subprocess.Popen([sys.executable, '-m', 'superyak_peer', 'federate', '--crossing-socket', '--data-dir',
                             str(mac[0].data_dir)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert wait_until(path.exists, 30)
        assert path.lstat().st_mode & 0o777 == 0o600
        assert _json.loads(over_socket(path, b'{"not": "a request"}')) == {'ok': False, 'code': 'BAD_REQUEST'}
    finally:
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
    assert proc.returncode == 0, err
    assert not path.exists()


def test_a_second_federate_starts_without_the_socket_and_the_first_still_answers(monkeypatch):
    """S3 and the plan re-check's item 4: a held crossing.lock is logged, and federate runs on without the socket, so
    its pulls and pushes go on; the socket that was there keeps answering, never taken over."""
    import signal
    from superyak_peer import crossing
    clock, a, mac = short_puller()
    path = mac[0].data_dir / 'crossing.sock'
    monkeypatch.setattr(crossing, 'ask', lambda fed, raw: {'ok': False, 'code': 'FIRST'})
    sockets = started_socket(mac[2])
    inode = path.lstat().st_ino
    proc = subprocess.Popen([sys.executable, '-m', 'superyak_peer', 'federate', '--crossing-socket', '--data-dir',
                             str(mac[0].data_dir)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _time.sleep(4)
        assert proc.poll() is None  # it runs on
        assert path.lstat().st_ino == inode
        assert _json.loads(over_socket(path, LINE)) == {'ok': False, 'code': 'FIRST'}
    finally:
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
        sockets.stop()
    assert proc.returncode == 0, err
    assert 'another process already serves crossing.sock' in err


def push_peer_here():
    from test_federation_outcomes import Clock, station
    push = station(_Path(_tempfile.mkdtemp(prefix='x')) / 'push', 'pat', Clock())
    push[2].card(push[1])
    push[0].claim_federation_mode('push')
    return push


@pytest.mark.parametrize('flag', [True, False])
def test_federation_listen_opens_crossing_sock_only_under_the_flag(monkeypatch, flag):
    import uvicorn
    from superyak_peer import __main__ as cli
    push = push_peer_here()
    path = push[0].data_dir / 'crossing.sock'
    seen = []
    monkeypatch.setattr(uvicorn, 'run', lambda app, **options: seen.append(wait_until(path.exists, 5 if flag else 0.5)))
    cli.main(['federation-listen', '--data-dir', str(push[0].data_dir), '--port', '0']
             + (['--crossing-socket'] if flag else []))
    assert seen == [flag]
    assert not path.exists()


def test_federation_listen_with_a_held_lock_still_serves_events_and_pulls(monkeypatch, caplog):
    import uvicorn
    from superyak_peer import __main__ as cli
    from superyak_peer import crossing
    push = push_peer_here()
    monkeypatch.setattr(crossing, 'ask', lambda fed, raw: {'ok': False, 'code': 'FIRST'})
    sockets = started_socket(push[2])
    ran = []
    monkeypatch.setattr(uvicorn, 'run', lambda app, **options: ran.append(app))
    try:
        cli.main(['federation-listen', '--data-dir', str(push[0].data_dir), '--port', '0', '--crossing-socket'])
        assert len(ran) == 1  # the listener still runs: events and pulls flow
        assert _json.loads(over_socket(push[0].data_dir / 'crossing.sock', LINE)) == {'ok': False, 'code': 'FIRST'}
    finally:
        sockets.stop()
    assert any('another process already serves crossing.sock' in r.getMessage() for r in caplog.records)
