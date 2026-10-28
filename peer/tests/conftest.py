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
