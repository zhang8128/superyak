"""The public-route-bound plan, Task 3: PublicRoute asks serve's live set first. A junk session costs no read; a junk
ship key waits in the miss lane, 1 inside and 4 waiting, and a full lane answers 503 busy. A present key decides alone.
Tailnet requests keep every lookup as before, outside every lane."""
import asyncio
import time

from fastapi.testclient import TestClient
import httpx
import pytest

from superyak_peer import counting
from superyak_peer.app import create_app

PUBLIC_CLIENT = ('203.0.113.5', 50000)
PASSWORD = 'long-password-patient'
JUNK_KEY = 'k' * 43  # the length of a real key's token_urlsafe(32)


def docked(store, owner_id, name):
    started = store.start_docking(name, 'test-host')
    ship = store.confirm_docking(owner_id, started['id'], started['code'])
    return ship, store.docking_status(started['id'], started['secret'])['key']


@pytest.fixture
def env(tmp_path):
    clock = [1000000.0]
    app = create_app(tmp_path / 'peer', clock=lambda: clock[0], allowed_origins=['http://testserver'])
    owner = app.state.store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    app.state.store.create_user('patient', 'Patient', PASSWORD)
    return app, owner


def public(app, **headers):
    return TestClient(app, base_url='http://testserver', client=PUBLIC_CLIENT, headers=headers)


def session_of(app):
    browser = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    answer = browser.post('/api/login', json={'username': 'patient', 'password': PASSWORD})
    assert answer.status_code == 200
    return answer.cookies.get('superyak_session')


def slowed(store, monkeypatch, seconds=0.3):
    """Each ship-key lookup takes `seconds`, so concurrent ones overlap if nothing holds them apart."""
    looked = type(store).ship_key_is_valid

    def slow(self, key):
        time.sleep(seconds)
        return looked(self, key)
    monkeypatch.setattr(type(store), 'ship_key_is_valid', slow)


async def gathered(app, requests, client=PUBLIC_CLIENT):
    """Requests on one event loop, as serve runs them: (path, headers) each, answers in order."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=client), base_url='http://testserver') as http:
        return await asyncio.gather(*(http.get(path, headers=headers) for path, headers in requests))


def test_junk_sessions_make_no_read(env):
    app, _ = env
    with app.state.store.counting() as counted:
        for n in range(5):
            assert public(app, cookie=f'superyak_session=junk-{n}').get('/api/chats').status_code == 401
    assert counted.total() == 0


def test_junk_keys_read_one_at_a_time_and_a_full_lane_is_503_busy(env, monkeypatch):
    """Ten junk keys at once: 1 looked up, 4 waiting, 5 refused busy with no read; at most 1 read at once."""
    app, _ = env
    slowed(app.state.store, monkeypatch)
    with app.state.store.counting() as counted:
        answers = asyncio.run(gathered(app, [('/api/chats', {'authorization': f'Bearer {JUNK_KEY}{n}'}) for n in range(10)]))
    codes = sorted(answer.status_code for answer in answers)
    assert codes == [401] * 5 + [503] * 5
    for busy in (answer for answer in answers if answer.status_code == 503):
        assert busy.headers['retry-after'] == '1' and busy.headers['x-superyak-busy'] == '1'
        assert busy.json() == {'error': 'This home is busy; try again shortly'}
        assert busy.headers['x-content-type-options'] == 'nosniff'
    assert counted.total('read', lane='miss') == 5 and counted.peak('read', lane='miss') == 1
    assert counted.total('read') == 5  # nothing outside the lane
    assert app.state.miss_lane.inside == 0


def test_a_present_key_decides_alone_so_a_valid_cookie_beside_a_junk_key_goes_to_the_lane(env):
    app, _ = env
    session = session_of(app)
    with app.state.store.counting() as counted:
        answer = public(app, cookie=f'superyak_session={session}', authorization=f'Bearer {JUNK_KEY}').get('/api/chats')
    assert answer.status_code == 401
    assert counted.total('read', lane='miss') == 1 and counted.total('read') == 1  # the session was never looked up


def test_a_valid_session_passes(env):
    app, _ = env
    session = session_of(app)
    assert public(app, cookie=f'superyak_session={session}').get('/api/chats').status_code == 200


def test_a_docked_ships_key_passes_and_the_route_watch_and_undock_read_as_before(env):
    """The route watch's 403 at /api/home and undock's answers: 200, then 401 once revoked, read as revoked."""
    app, owner = env
    _, key = docked(app.state.store, owner['id'], 'tardis')
    ship = public(app, authorization=f'Bearer {key}', origin='http://testserver')  # as the ship's client sends it
    assert ship.get('/api/me').status_code == 200
    assert ship.get('/api/home').json() == {'error': 'Ship keys cannot use this route'}
    assert ship.get('/api/home').status_code == 403
    assert ship.delete('/api/ships/me/key').status_code == 200
    assert ship.delete('/api/ships/me/key').status_code == 401  # in the set, stale: its lookup finds no live row
    assert ship.delete('/api/ships/me/key').status_code == 401  # out of the set: the miss lane's lookup, the same answer


def test_a_key_made_after_start_passes_through_the_lane_once_then_skips_it(env):
    app, owner = env
    _, key = docked(app.state.store, owner['id'], 'serenity')  # as station-approve makes one, in another process
    ship = public(app, authorization=f'Bearer {key}')
    with app.state.store.counting() as first:
        assert ship.get('/api/me').status_code == 200
    assert first.total('read', lane='miss') == 1
    with app.state.store.counting() as then:
        assert ship.get('/api/me').status_code == 200
    assert then.total(lane='miss') == 0 and then.total('read', path='/api/me', lane=counting.BEFORE) > 0


@pytest.mark.parametrize('length, reads', [(128, 1), (129, 0), (4000, 0)])
def test_an_over_long_key_is_refused_unread_and_never_waits_in_the_lane(env, monkeypatch, length, reads):
    app, _ = env
    entered, run = [], app.state.miss_lane.run

    async def watched(*args):
        entered.append(1)
        return await run(*args)
    monkeypatch.setattr(app.state.miss_lane, 'run', watched)
    with app.state.store.counting() as counted:
        assert public(app, authorization=f'Bearer {"k" * length}').get('/api/chats').status_code == 401
    assert counted.total('read') == reads and counted.total('read', lane='miss') == reads and len(entered) == reads


@pytest.mark.parametrize('length', [129, 4000])
def test_an_over_long_session_cookie_is_refused_unread(env, monkeypatch, length):
    """Even one the set held: the length is checked before the hash."""
    app, _ = env
    long = 's' * length
    from superyak_peer.auth import token_hash
    app.state.store.live.add('session', token_hash(long), float('inf'), None)
    with app.state.store.counting() as counted:
        assert public(app, cookie=f'superyak_session={long}').get('/api/chats').status_code == 401
    assert counted.total() == 0


def test_a_key_over_the_tailnet_passes_while_the_public_miss_lane_is_full(env, monkeypatch):
    """The plan reader's P8: the tailnet keeps its lookups outside every lane."""
    app, owner = env
    _, key = docked(app.state.store, owner['id'], 'serenity')  # not in the set
    slowed(app.state.store, monkeypatch, 0.5)

    async def both():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=PUBLIC_CLIENT), base_url='http://testserver') as junk, \
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('100.64.0.7', 50000)), base_url='http://testserver') as tailnet:
            flood = [asyncio.create_task(junk.get('/api/chats', headers={'authorization': f'Bearer {JUNK_KEY}{n}'})) for n in range(5)]
            await asyncio.sleep(0.05)
            assert app.state.miss_lane.inside == 5  # full
            ship = await tailnet.get('/api/me', headers={'authorization': f'Bearer {key}'})
            return ship, await asyncio.gather(*flood)
    ship, flood = asyncio.run(both())
    assert ship.status_code == 200
    assert sorted(answer.status_code for answer in flood) == [401] * 5
