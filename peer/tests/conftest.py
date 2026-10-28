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
    """Route waits until trails ships (`imprints.ROUTE_OPEN`, Serenity's condition S1). The tests of what route does
    open it, so that code stays tested for the day trails lands; a test that takes `route_closed` gets the value that
    ships."""
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
