"""The public-route-bound plan, Task 8: public health reads nothing. From a public client /api/health answers
{"ok": true} with no store work at all; over the tailnet it makes its one read, as Task 0's positive control counts,
so the sitting's health check still finds a store that can't be read."""
import sqlite3

from fastapi.testclient import TestClient
import pytest

from superyak_peer.app import create_app

PUBLIC_CLIENT = ('203.0.113.5', 50000)


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / 'home', allowed_origins=['http://testserver'])


def test_public_health_reads_nothing(app):
    public = TestClient(app, base_url='http://testserver', client=PUBLIC_CLIENT)
    with app.state.store.counting() as counted:
        for _ in range(3):
            answer = public.get('/api/health')
            assert answer.status_code == 200 and answer.json() == {'ok': True}
    assert counted.total() == 0


def test_tailnet_health_makes_its_one_read(app):
    with app.state.store.counting() as counted:
        assert TestClient(app, base_url='http://testserver').get('/api/health').json() == {'ok': True}
    assert counted.total('transaction') == 1 and counted.total() == 2  # its transaction and its gate


def test_a_store_that_cant_be_read_fails_tailnet_health_and_not_public(app, monkeypatch):
    """What each says: the tailnet's read finds the broken store (the sitting checks it); the public one, which reads
    nothing, says only that serve answers."""
    def broken(self, *args, **kwargs):
        raise sqlite3.OperationalError('disk I/O error')
    monkeypatch.setattr(type(app.state.store), 'transaction', broken)
    tailnet = TestClient(app, base_url='http://testserver', raise_server_exceptions=False)
    assert tailnet.get('/api/health').status_code == 500
    public = TestClient(app, base_url='http://testserver', client=PUBLIC_CLIENT, raise_server_exceptions=False)
    assert public.get('/api/health').json() == {'ok': True}
