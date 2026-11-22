"""The public-route-bound plan, Task 4: the device cookie at sign-in. A device cookie serve's live set lacks, or one
over 128 characters, skips the read before the sign-in lane and goes through the public lane, where Store.login checks
it as before. A person's real device keeps its exemption (the known lane), and a mistyped username leaves it in the
set: devices never leave on a lookup."""
from fastapi.testclient import TestClient
import pytest

from superyak_peer import counting
from superyak_peer.app import create_app
from superyak_peer.auth import token_hash

PUBLIC_CLIENT = ('203.0.113.5', 50000)
PASSWORD = 'long-password-patient'


@pytest.fixture
def app(tmp_path):
    clock = [1000000.0]
    app = create_app(tmp_path / 'peer', clock=lambda: clock[0], allowed_origins=['http://testserver'])
    app.state.store.create_user('patient', 'Patient', PASSWORD)
    return app


def sign_in(app, device=None, username='patient'):
    client = TestClient(app, base_url='http://testserver', client=PUBLIC_CLIENT, headers={'origin': 'http://testserver'},
                        cookies={'superyak_device': device} if device is not None else None)
    return client.post('/api/login', json={'username': username, 'password': PASSWORD})


def real_device(app):
    answer = sign_in(app)
    assert answer.status_code == 200
    return answer.cookies.get('superyak_device')


@pytest.mark.parametrize('device', ['junk-device-cookie', 'd' * 129, 'd' * 4000])
def test_a_device_the_set_lacks_or_an_over_long_one_reads_nothing_before_the_lane(app, device):
    if len(device) > 128:  # even one the set held: the length is checked before the hash
        app.state.store.live.add('device', token_hash(device), float('inf'), None)
    with app.state.store.counting() as counted:
        assert sign_in(app, device).status_code == 200
    assert counted.total('read', path='/api/login', lane=counting.BEFORE) == 0
    assert counted.total(path='/api/login', lane='public') > 0 and counted.total(lane='known') == 0


def test_a_persons_real_device_keeps_its_exemption(app):
    device = real_device(app)
    with app.state.store.counting() as counted:
        assert sign_in(app, device).status_code == 200
    assert counted.total('read', path='/api/login', lane=counting.BEFORE) == 1  # device_is_valid, then the known lane
    assert counted.total(path='/api/login', lane='known') > 0 and counted.total(lane='public') == 0


def test_a_mistyped_username_leaves_the_device_in_the_set(app):
    device = real_device(app)
    assert sign_in(app, device, username='patiant').status_code == 401
    assert app.state.store.live.has(token_hash(device), 'device', app.state.store.clock())
    with app.state.store.counting() as counted:
        assert sign_in(app, device).status_code == 200
    assert counted.total(path='/api/login', lane='known') > 0


def test_a_tailnet_sign_in_is_as_before(app):
    """No device read before the lane over the tailnet, set or no set: its lane is the tailnet's."""
    device = real_device(app)
    client = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'}, cookies={'superyak_device': device})
    with app.state.store.counting() as counted:
        assert client.post('/api/login', json={'username': 'patient', 'password': PASSWORD}).status_code == 200
    assert counted.total('read', path='/api/login', lane=counting.BEFORE) == 0
    assert counted.total(path='/api/login', lane='tailnet') > 0
