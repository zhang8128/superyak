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
