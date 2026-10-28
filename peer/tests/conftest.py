import pytest
from fastapi.testclient import TestClient

# Public route spec 6.1: Starlette's default client host, "testclient", is not an IP address, so the station treats it
# as public. Every TestClient the suite builds runs as tailnet instead, unless the test passes its own client.
TAILNET_CLIENT = ('127.0.0.1', 50000)


@pytest.fixture(autouse=True)
def tailnet_test_clients(monkeypatch):
    built = TestClient.__init__

    def tailnet(self, *args, client=TAILNET_CLIENT, **kwargs):
        built(self, *args, client=client, **kwargs)
    monkeypatch.setattr(TestClient, '__init__', tailnet)

@pytest.fixture
def env(tmp_path):
    from superyak_peer.app import create_app
    clock = [1000000.0]
    app = create_app(tmp_path / 'peer', clock=lambda: clock[0], allowed_origins=['http://testserver'])
    clients, users = [], []
    for name in ('patient', 'doctor', 'organizer', 'family'):
        user = app.state.store.create_user(name, name.title(), 'long-password-' + name, is_admin=name == 'organizer')
        client = TestClient(app, base_url='http://testserver')
        client.headers['origin'] = 'http://testserver'
        response = client.post('/api/login', json={'username': name, 'password': 'long-password-' + name})
        assert response.status_code == 200
        client.headers['x-csrf-token'] = response.json()['csrf_token']
        clients.append(client)
        users.append(user)
    yield app, clients, users, clock
    for client in clients:
        client.close()

@pytest.fixture
def peer_clients(env):
    return env[1][:3]


_ROUTE_AS_SHIPPED = {}


@pytest.fixture(autouse=True, scope='session')
def route_open_as_for_trails():
    """Route waits until trails ships (`imprints.ROUTE_OPEN`, Serenity's condition S1). Every test here runs with route
    open unless it takes `route_closed`; production never does. So the route code stays tested for the day trails
    lands. Opening it per test was weighed (Serenity's note 1): 96 test functions in 12 files need it, because the
    shared `request_doc` asks with route, so the opening stays session-wide."""
    from superyak_peer import imprints
    _ROUTE_AS_SHIPPED['value'] = imprints.ROUTE_OPEN
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(imprints, 'ROUTE_OPEN', True)
        yield


@pytest.fixture
def route_closed(monkeypatch):
    """`imprints.ROUTE_OPEN` as it ships, put back for one test."""
    from superyak_peer import imprints
    monkeypatch.setattr(imprints, 'ROUTE_OPEN', _ROUTE_AS_SHIPPED['value'])


# First rail (docs/superpowers/specs/2026-10-27-first-rail-lessons-design.md): one peer with a recorded lessons room,
# two peers federated in process, and a fake shared embedder that speaks engram/embedder_service.py's protocol.
LESSON_TIME = 1_800_000_000.0


def lesson_body(ship='tardis', claim='Quote a glob in zsh.', why='An unquoted glob cost a rerun.', error=(), command=('--include=*',),
                file=(), learned='own'):
    lines = ['lesson', f'ship: {ship}', f'claim: {claim}', f'why: {why}']
    lines += [f'error: {v}' for v in error] + [f'command: {v}' for v in command] + [f'file: {v}' for v in file]
    return '\n'.join(lines + [f'learned from: {learned}'])


def run_lessons(*args, stdin='', now=LESSON_TIME):
    """`python -m superyak_peer.lessons <verb>` in a child whose clock is pinned at `now`, set before anything binds
    time.time (the store's default clock binds it at import)."""
    import os, subprocess, sys
    code = f'import time; time.time = lambda: {now!r}\nimport sys\nfrom superyak_peer.lessons import main\nmain(sys.argv[1:])'
    return subprocess.run([sys.executable, '-c', code, *map(str, args)], input=stdin, capture_output=True, text=True,
                          env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})


class FakeEmbedder:
    """A Unix socket that answers engram/embedder_service.py's protocol. `vectors` maps a text to its vector; any other
    text gets `default`. It records every request, and whether a station transaction was open when it came."""
    def __init__(self, path, model='fake-model', dimension=4):
        import socketserver, threading
        from superyak_peer import lessons
        self.path, self.model, self.dimension = path, model, dimension
        self.vectors, self.default, self.requests, self.delay, self.down = {}, [0.0, 0.0, 0.0, 1.0][:dimension], [], 0.0, False
        self.in_transaction = threading.Event()
        fake = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                import json, struct, time
                size = struct.unpack('>I', self.request.recv(4))[0]
                data = b''
                while len(data) < size:
                    data += self.request.recv(size - len(data))
                request = json.loads(data)
                fake.requests.append({**request, 'in_transaction': fake.in_transaction.is_set()})
                time.sleep(fake.delay)
                reply = {'ok': True, 'model': fake.model, 'dimension': fake.dimension}
                if request['op'] == 'embed':
                    reply['vectors'] = [fake.vectors.get(t, fake.default) for t in request['texts']]
                body = json.dumps(reply).encode()
                self.request.sendall(struct.pack('>I', len(body)) + body)

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True
        self.server = Server(str(path), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_embedder():
    import shutil, tempfile
    from pathlib import Path
    folder = Path(tempfile.mkdtemp(prefix='emb'))  # a Unix socket path must stay under 108 bytes
    embedder = FakeEmbedder(folder / 's')
    yield embedder
    embedder.close()
    shutil.rmtree(folder, ignore_errors=True)


def paired(fed, actor, card):
    """Pair `card` as an admin does since fix:pairing-code: typing the code the other machine shows, its own."""
    from superyak_peer.identity import pairing_code
    return fed.pair(actor, card, code=pairing_code(card))


def lesson_ship(store, owner_id, username):
    with store.transaction() as db:
        return store._new_ship(db, username, username.title(), owner_id)


@pytest.fixture
def lessons_station(tmp_path):
    """The origin: andy, his ships rio-grande and tardis (both local here, so one peer can lay as two ships), and a
    recorded lessons room holding all three. Returns (store, clock, ids, room id)."""
    from superyak_peer.db import Store
    from superyak_peer.identity import PeerIdentity
    clock = [LESSON_TIME]
    store = Store(tmp_path / 'pi', clock=lambda: clock[0])
    PeerIdentity.load_or_create(store.data_dir)
    andy = store.create_user('andy', 'Andy Example', 'a-long-password', is_admin=True)['id']
    ids = {'andy': andy, 'rio-grande': lesson_ship(store, andy, 'rio-grande')['id'], 'tardis': lesson_ship(store, andy, 'tardis')['id']}
    room = store.create_room(andy, 'Lessons', [ids['rio-grande'], ids['tardis']])['id']
    with store.transaction() as db:
        db.execute('INSERT INTO lessons_room VALUES(1,?,?,?)', (room, ids['rio-grande'], clock[0]))
    return store, clock, ids, room


@pytest.fixture
def lessons_peers(tmp_path):
    """The origin (the Pi: andy and rio-grande) and a second peer (Tardis: andy's account there and its ship tardis),
    paired both ways, card by card, with a lessons room on the origin holding all four and recorded on both. Returns a
    dict; deliver(src, dst) runs one in-process sync."""
    from superyak_peer.db import Store
    from superyak_peer.federation import Federation
    clock = [LESSON_TIME]
    pi, tardis = Store(tmp_path / 'pi', clock=lambda: clock[0]), Store(tmp_path / 'tardis', clock=lambda: clock[0])
    pi_fed, tardis_fed = Federation(pi, endpoint='https://pi:7437'), Federation(tardis, endpoint='https://tardis:7437')
    andy = pi.create_user('andy', 'Andy Example', 'a-long-password', is_admin=True)['id']
    rio = lesson_ship(pi, andy, 'rio-grande')['id']
    andy_t = tardis.create_user('andy', 'Andy Example', 'a-long-password', is_admin=True)['id']
    ship_t = tardis.lessons_ship('tardis', 'andy')['id']
    contact_ship = paired(pi_fed, andy, tardis_fed.card(ship_t))['id']
    contact_andy = paired(pi_fed, andy, tardis_fed.card(andy_t))['id']
    paired(tardis_fed, andy_t, pi_fed.card(andy))
    room = pi.create_room(andy, 'Lessons', [rio, contact_ship, contact_andy])['id']
    view = pi.station_lessons_room('andy', room[:6], 'rio-grande', [tardis_fed.identity.peer_id])
    recorded = pi.station_lessons_room('andy', room[:6], 'rio-grande', [tardis_fed.identity.peer_id], view['confirm'])
    assert view['full_id'] == recorded['full_id'] == f'{pi_fed.identity.peer_id}:{room}'   # the origin's, never a listed peer's
    peers = {'pi': (pi, pi_fed, {'andy': andy, 'rio-grande': rio, 'contact': contact_ship}), 'tardis': (tardis, tardis_fed, {'andy': andy_t, 'tardis': ship_t})}

    def deliver(src, dst):
        return peers[src][1].sync_once(send=lambda card, prepare: peers[dst][1].receive(prepare()))
    deliver('pi', 'tardis')
    key = pi_fed.identity.peer_id + ':' + room
    tardis.record_lessons_room(key)
    return {'peers': peers, 'deliver': deliver, 'clock': clock, 'room': room, 'key': key}
