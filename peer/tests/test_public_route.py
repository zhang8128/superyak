"""The public route (docs/superpowers/specs/2026-10-27-public-route-design.md, phase 1): a public (Funnel) request
reaches only the allow-list, or carries a valid session or ship key; a tailnet request is handled as before."""
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import pytest
from superyak_peer.app import TRUSTED_PROXY, is_public

PROXY = (TRUSTED_PROXY, 50000)  # tailscale serve, as `serve --proxy-headers` sees it


def classified(client, headers=None):
    """What is_public says behind uvicorn's ProxyHeadersMiddleware, configured as `serve` configures it (spec 6.2)."""
    seen = []

    async def recorder(scope, receive, send):
        seen.append((scope['client'], is_public(scope)))
        await PlainTextResponse('')(scope, receive, send)
    TestClient(ProxyHeadersMiddleware(recorder, trusted_hosts=TRUSTED_PROXY), client=client).get('/', headers=headers or {})
    return seen[0][1]


def test_every_test_client_runs_as_tailnet_unless_told_otherwise():
    """Spec 6.1: Starlette's default client host is "testclient", which is not an IP address and so is public; the
    conftest helper gives every TestClient 127.0.0.1 instead, so the suite runs as tailnet."""
    seen = []

    async def recorder(scope, receive, send):
        seen.append(scope['client'])
        await PlainTextResponse('')(scope, receive, send)
    TestClient(recorder).get('/')
    TestClient(recorder, client=('203.0.113.5', 1234)).get('/')
    assert seen == [('127.0.0.1', 50000), ('203.0.113.5', 1234)]


@pytest.mark.parametrize('client', [('testclient', 50000), ('localhost', 1), ('', 1), None, (), ('100.70.202.124.example', 1)])
def test_a_client_that_is_not_an_ip_address_is_never_tailnet(client):
    assert is_public({'type': 'http', 'headers': [], 'client': client})
    assert is_public({'type': 'http', 'headers': []})  # no client at all


@pytest.mark.parametrize('host, public', [
    ('127.0.0.1', False), ('127.8.9.10', False), ('::1', False), ('100.64.0.1', False), ('100.127.255.254', False),
    ('100.70.202.124', False), ('fd7a:115c:a1e0::1', False), ('fd7a:115c:a1e0:ab12::42', False),
    ('::ffff:100.70.202.124', False), ('::ffff:127.0.0.1', False),
    ('100.128.0.1', True), ('100.63.255.255', True), ('203.0.113.5', True), ('192.168.1.10', True), ('10.0.0.2', True),
    ('2001:db8::1', True), ('fd7a:115c:a1e1::1', True), ('::ffff:203.0.113.5', True), ('fe80::1', True)])
def test_loopback_and_tailnet_addresses_are_tailnet_and_every_other_address_is_public(host, public):
    assert is_public({'type': 'http', 'headers': [], 'client': (host, 1)}) is public


def test_classification_behind_the_proxy_serve_trusts():
    """Spec 6.2, through uvicorn's ProxyHeadersMiddleware with 127.0.0.1 trusted, as `serve` configures it."""
    assert classified(PROXY, {'x-forwarded-for': '203.0.113.5'})
    assert classified(PROXY, {'x-forwarded-for': '100.70.202.124, 203.0.113.5'})  # the rightmost untrusted entry
    assert not classified(PROXY, {'x-forwarded-for': '100.70.202.124'})
    assert not classified(PROXY)  # 127.0.0.1 with no forwarded header: a local process, tailnet by design (spec 1)
    # forwarded headers from a client serve doesn't trust are ignored, whichever way they would point
    assert classified(('203.0.113.9', 50000), {'x-forwarded-for': '100.70.202.124'})
    assert not classified(('100.70.202.124', 50000), {'x-forwarded-for': '203.0.113.5'})
    assert not classified(PROXY, {'x-forwarded-for': '::ffff:100.70.202.124'})  # unmapped to tailnet
    assert not classified(('::ffff:100.70.202.124', 50000))


@pytest.mark.parametrize('value', ['?1', '', '0', 'anything'])
def test_a_funnel_header_with_any_value_makes_a_tailnet_request_public(value):
    assert classified(PROXY, {'x-forwarded-for': '100.70.202.124', 'tailscale-funnel-request': value})
    assert classified(('100.70.202.124', 50000), {'Tailscale-Funnel-Request': value})
    assert classified(PROXY, {'tailscale-funnel-request': value})

PRESENCE = {'x-superyak-session': 'session-one', 'x-superyak-client': 'hook/0123456789ab', 'x-superyak-mode': 'write'}


def docked(store, owner_id, name='serenity'):
    started = store.start_docking(name, 'test-host')
    ship = store.confirm_docking(owner_id, started['id'], started['code'])
    return ship, store.docking_status(started['id'], started['secret'])['key']


def written(store, ship_id):
    """What a ship lookup writes: its keys' last_used and its presence rows."""
    with store.transaction() as db:
        return ([tuple(r) for r in db.execute('SELECT key_hash,last_used FROM ship_keys WHERE ship_id=? ORDER BY key_hash', (ship_id,))],
                [tuple(r) for r in db.execute('SELECT * FROM presence WHERE ship_id=? ORDER BY name', (ship_id,))])


def test_the_validity_reads_answer_as_the_routes_own_checks_do(env):
    """Spec 2, "valid means checked": session_is_valid and ship_key_is_valid do the lookups store.session and
    ship_for_key do, and answer True or False."""
    app, clients, users, clock = env
    store = app.state.store
    token = clients[0].cookies.get('superyak_session')
    assert store.session_is_valid(token) is True
    for made_up in ('made-up', '', None, 42, 'x' * 5000):
        assert store.session_is_valid(made_up) is False, made_up
    ship, key = docked(store, users[0]['id'])
    assert store.ship_key_is_valid(key) is True
    for made_up in ('made-up', '', None, 42, key + 'x', 'x' * 129):
        assert store.ship_key_is_valid(made_up) is False, made_up
    assert store.session_is_valid(key) is False and store.ship_key_is_valid(token) is False  # not interchangeable
    with store.transaction() as db:  # a person waiting on activation has no valid session, as store.session says
        db.execute('UPDATE users SET activation_pending=1 WHERE id=?', (users[1]['id'],))
    assert store.session_is_valid(clients[1].cookies.get('superyak_session')) is False
    store.revoke_presented_key(key)
    assert store.ship_key_is_valid(key) is False
    clock[0] += 86401
    assert store.session_is_valid(token) is False


def test_the_validity_reads_write_nothing(env):
    """Spec 2: no last_used and no presence, which ship_for_key writes (shown first, so the check can see a write)."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    store.ship_for_key(key, {'name': 'session-one', 'client': 'hook/0123456789ab', 'mode': 'write'})
    before = written(store, ship['id'])
    clock[0] += 3600
    store.ship_for_key(key, {'name': 'session-one', 'client': 'hook/0123456789ab', 'mode': 'write'})
    assert written(store, ship['id']) != before
    before = written(store, ship['id'])
    clock[0] += 3600
    assert store.ship_key_is_valid(key) and store.session_is_valid(clients[0].cookies.get('superyak_session'))
    assert written(store, ship['id']) == before

