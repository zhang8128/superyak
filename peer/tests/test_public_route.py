"""The public route (docs/superpowers/specs/2026-10-27-public-route-design.md, phase 1): a public (Funnel) request
reaches only the allow-list, or carries a valid session or ship key; a tailnet request is handled as before."""
import base64
import logging
from pathlib import Path
import re
import sqlite3
import sys
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse
from starlette.routing import Mount
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import pytest
from superyak_peer.app import TRUSTED_PROXY, is_public

PROXY = (TRUSTED_PROXY, 50000)  # tailscale serve, as `serve --proxy-headers` sees it
AGENT = Path(__file__).resolve().parents[2] / 'agent'
if (AGENT / 'superyak_agent').is_dir() and str(AGENT) not in sys.path:
    sys.path[:0] = [str(AGENT), str(AGENT.parent / 'team')]


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


PUBLIC_CLIENT = ('203.0.113.5', 50000)  # an internet address: what a Funnel request looks like after the proxy
SIGN_IN = (401, {'error': 'Sign in required'})
NOT_FOUND = (404, {'error': 'Not found'})
SECURITY = {'x-content-type-options': 'nosniff', 'cache-control': 'no-store', 'referrer-policy': 'no-referrer',
            'content-security-policy': "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"}
# Spec 2's table, by route template; every other route, and every other method, is closed to anonymous public requests
ALLOWED = {('/', 'GET'), ('/', 'HEAD'), ('/public/', 'GET'), ('/public/', 'HEAD'), ('/assets', 'GET'), ('/assets', 'HEAD'),
           ('/api/health', 'GET'), ('/api/login', 'POST'), ('/api/invitations/redeem', 'POST'),
           ('/public/layers/{key}', 'GET'), ('/public/layers/{layer_id}/files/{key}', 'GET')}
METHODS = ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE')


def public(app, **headers):
    return TestClient(app, base_url='http://testserver', client=PUBLIC_CLIENT, headers={'origin': 'http://testserver', **headers})


def anonymous(app):
    return TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})


def answer(response):
    return response.status_code, response.json()


def refused(response):
    """The middleware's refusal: its exact body and BrowserBoundary's security headers. None when it let the request by."""
    expected = SIGN_IN if response.request.url.path.startswith('/api/') else NOT_FOUND
    if response.status_code != expected[0] or (response.request.method != 'HEAD' and response.json() != expected[1]):
        return None
    return all(response.headers.get(name) == value for name, value in SECURITY.items())


def every_route(app):
    """(template, method, path) for every route object: the app's own, those its routers added and the mounts."""
    from fastapi.routing import iter_route_contexts
    found = []
    for context in iter_route_contexts(app.router.routes):
        template = context.path
        concrete = re.sub(r'\{[^}]+\}', '1', template)
        if isinstance(context.original_route, Mount):
            concrete += '/app.js'
        found += [(template, method, concrete) for method in METHODS]
    return found


def rows(app):
    """Every table's row count: a refused walk writes nothing anywhere."""
    with app.state.store.transaction() as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {table: db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in tables}


@pytest.fixture
def watched(env, monkeypatch):
    """store.session and store.ship_for_key fail the test if any route handler gets as far as calling them (spec 6.3)."""
    app = env[0]
    reached = []
    for name in ('session', 'ship_for_key'):
        def fail(*args, name=name, **kwargs):
            reached.append(name)
            raise AssertionError(f'a route handler ran and called store.{name}')
        monkeypatch.setattr(app.state.store, name, fail)
    return env, reached


@pytest.mark.parametrize('credentials', [{}, {'authorization': 'Bearer made-up-ship-key'}], ids=['anonymous', 'made-up-key'])
def test_every_route_outside_the_allow_list_refuses_a_public_request(watched, credentials):
    (app, clients, users, clock), reached = watched
    walked = every_route(app)
    templates = {template for template, _, _ in walked}
    assert {'/api/connections', '/api/sync', '/federation/events', '/assets', '/api/dockings', '/api/access-requests'} <= templates
    before, client = rows(app), public(app, **credentials)
    for template, method, path in walked:
        if (template, method) in ALLOWED:
            continue
        response = client.request(method, path, json={} if method in ('POST', 'PUT', 'PATCH') else None)
        assert refused(response), (method, path, response.status_code, response.text)
    assert reached == [] and rows(app) == before


def test_allow_listed_routes_answer_anonymous_public_requests_normally(env):
    app, clients, users, clock = env
    payload = {'name': 'notes.txt', 'media_type': 'text/plain', 'content_base64': base64.b64encode(b'hello').decode()}
    attachment = clients[0].post('/api/files', json=payload).json()['id']
    layer = clients[0].post('/api/layers', json={'title': 'Published', 'body': 'for anyone', 'public': True, 'attachment_ids': [attachment]}).json()
    assert clients[0].post(f'/api/layers/{layer["id"]}/activate', json={'version': 1}).status_code == 200
    visitor, tailnet = public(app), anonymous(app)
    for path in ('/', '/public/'):
        shell = visitor.get(path)
        assert shell.status_code == 200 and shell.headers['content-type'].startswith('text/html') and refused(shell) is None
    script = visitor.get('/assets/app.js')
    assert script.status_code == 200 and script.content == tailnet.get('/assets/app.js').content
    assert visitor.head('/assets/app.js').status_code == 200
    assert visitor.head('/').status_code == tailnet.head('/').status_code
    assert answer(visitor.get('/api/health')) == (200, {'ok': True})
    assert visitor.get(f'/public/layers/{layer["id"]}').json()['body'] == 'for anyone'
    assert visitor.get(f'/public/layers/{layer["id"]}/files/{attachment}').content == b'hello'
    assert answer(visitor.post('/api/login', json={'username': 'patient', 'password': 'wrong'})) == (401, {'error': 'Invalid username or password'})
    signed_in = visitor.post('/api/login', json={'username': 'doctor', 'password': 'long-password-doctor'})
    assert signed_in.status_code == 200 and signed_in.json()['user']['username'] == 'doctor'


def test_an_expired_or_made_up_cookie_opens_nothing(env):
    """Spec 6.3: two routes that check no session themselves, or check it only after reading the body."""
    app, clients, users, clock = env
    layer = clients[0].post('/api/layers', json={'title': 'Draft', 'body': 'before'}).json()
    token = clients[0].cookies.get('superyak_session')
    clock[0] += 86401
    expired = public(app, cookie=f'superyak_session={token}', **{'x-csrf-token': clients[0].headers['x-csrf-token']})
    assert refused(expired.post('/api/dockings', json={'ship_name': 'serenity', 'machine': 'mac'}))
    assert refused(expired.put(f'/api/layers/{layer["id"]}', json={'version': 1, 'body': 'after'}))
    made_up = public(app, cookie='superyak_session=made-up')
    assert refused(made_up.get('/api/home')) and refused(made_up.post('/api/dockings', json={'ship_name': 'x1', 'machine': 'mac'}))
    assert refused(made_up.get('/no-such-page'))
    with app.state.store.transaction() as db:
        assert db.execute('SELECT count(*) FROM dockings').fetchone()[0] == 0
        assert db.execute('SELECT draft FROM layers WHERE id=?', (layer['id'],)).fetchone()[0].count('before') == 1


def test_dockings_and_access_requests_refuse_public_requests_with_a_real_id_and_secret(env):
    app, clients, users, clock = env
    visitor, tailnet = public(app), anonymous(app)
    assert refused(visitor.post('/api/dockings', json={'ship_name': 'serenity', 'machine': 'mac'}))
    started = tailnet.post('/api/dockings', json={'ship_name': 'serenity', 'machine': 'mac'}).json()
    assert refused(visitor.get(f'/api/dockings/code/{started["code"]}'))
    assert clients[0].post(f'/api/dockings/{started["id"]}/confirm', json={'code': started['code']}).status_code == 200
    assert refused(visitor.get(f'/api/dockings/{started["id"]}', params={'secret': started['secret']}))
    assert refused(visitor.get(f'/api/dockings/{started["id"]}', headers={'x-superyak-secret': started['secret']}))
    assert tailnet.get(f'/api/dockings/{started["id"]}', params={'secret': started['secret']}).json()['key']  # not collected
    assert refused(visitor.post('/api/access-requests', json={'name': 'Mallory', 'contact': 'm@example.org'}))
    with app.state.store.transaction() as db:
        assert db.execute('SELECT count(*) FROM access_requests').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM dockings').fetchone()[0] == 1
    asked = tailnet.post('/api/access-requests', json={'name': 'Jenn', 'contact': 'jenn@example.org'}).json()
    assert clients[2].post(f'/api/access-requests/{asked["id"]}/approve', json={}).status_code == 200
    assert refused(visitor.get(f'/api/access-requests/{asked["id"]}', params={'secret': asked['secret']}))
    assert tailnet.get(f'/api/access-requests/{asked["id"]}', params={'secret': asked['secret']}).json()['token']  # not released


def test_signed_in_use_works_over_the_public_route(env):
    """Spec 6.4: a session made over the public route reaches what the browser uses; an expired one gets the 401 that
    brings app.js back to its sign-in page."""
    app, clients, users, clock = env
    browser = public(app)
    signed_in = browser.post('/api/login', json={'username': 'doctor', 'password': 'long-password-doctor'})
    browser.headers['x-csrf-token'] = signed_in.json()['csrf_token']
    assert browser.get('/api/me').json()['username'] == 'doctor'
    assert browser.get('/api/chats').status_code == 200
    room = browser.post('/api/chats', json={'title': 'Clinic', 'member_ids': [users[0]['id']]}).json()['id']
    posted = browser.post(f'/api/chats/{room}/messages', json={'client_message_id': 'm1', 'body': 'Hello from outside'})
    assert posted.status_code == 201 and clients[0].get(f'/api/chats/{room}').json()['messages'][-1]['body'] == 'Hello from outside'
    clock[0] += 86401
    assert refused(browser.get('/api/me')) and refused(browser.get('/api/chats'))


def test_an_invitation_link_and_a_docking_confirm_link_from_outside(env):
    """Spec 2: an anonymous invitation redeem works; confirming a docking needs a session, and works with one."""
    app, clients, users, clock = env
    invitation = clients[2].post('/api/invitations', json={}).json()
    visitor = public(app)
    redeemed = visitor.post('/api/invitations/redeem', json={'token': invitation['token'], 'username': 'jenn', 'name': 'Jenn', 'password': 'jenn-chosen-password'})
    assert redeemed.status_code == 201, redeemed.text
    started = anonymous(app).post('/api/dockings', json={'ship_name': 'rio-grande', 'machine': 'jenn-laptop'}).json()
    assert refused(visitor.post(f'/api/dockings/{started["id"]}/confirm', json={'code': started['code']}))
    visitor.headers['x-csrf-token'] = visitor.post('/api/login', json={'username': 'jenn', 'password': 'jenn-chosen-password'}).json()['csrf_token']
    assert visitor.get(f'/api/dockings/code/{started["code"]}').json()['ship_name'] == 'rio-grande'
    confirmed = visitor.post(f'/api/dockings/{started["id"]}/confirm', json={'code': started['code']})
    assert confirmed.status_code == 200 and confirmed.json()['username'] == 'rio-grande'


@pytest.mark.skipif(not (AGENT / 'superyak_agent').is_dir(), reason='needs agent/ from the full repository')
def test_a_ship_key_reaches_every_station_client_route_over_the_public_route(env):
    """Spec 6.5, phase 1: a valid key passes for any route, and the route's own check decides. No call is refused
    by the middleware; a made-up key is."""
    from superyak_agent.station import StationClient, StationError
    app, clients, users, clock = env
    ship, key = docked(app.state.store, users[0]['id'])
    other, _ = docked(app.state.store, users[0]['id'], 'rio-grande')
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id'], other['id']]}).json()['id']
    asked = clients[0].post(f'/api/chats/{room}/messages', json={'client_message_id': 'q1', 'body': '@serenity status?'}).json()
    outside = TestClient(app, base_url='http://testserver', client=PUBLIC_CLIENT)

    def transport(method, url, headers, data):
        response = outside.request(method, url.removeprefix('http://testserver'), headers=headers, content=data)
        return response.status_code, response.content
    station = StationClient('http://testserver', key, transport=transport, presence={'x-superyak-session': 'public-one'})
    calls = [('me',), ('rooms',), ('room', room), ('post', room, 'Working on it.', 'c1', None, asked['id']),
             ('watch', 20), ('claim', room, 'tests', 'running them'), ('claims', room), ('release', room, 'tests'),
             ('board', room), ('board_counts',), ('post_item', room, 'deploy', 'Deploy the fix', 'build'),
             ('link_item', room, 'deploy', 'branch:fix'), ('done_item', room, 'deploy', 'branch:fix'),
             ('post_item', room, 'tidy', 'Tidy up', 'ops'), ('drop_item', room, 'tidy'),
             ('unread', None), ('advance', None, None), ('ticket', asked['id']), ('finish_ticket', 'no-such-ticket'),
             ('open_room', 'Side room', ['rio-grande']), ('directory',), ('instructions',),
             ('draft_instructions', 'Draft', 'Be brief.'), ('mentions',), ('set_brief', room, 'The plan.', 0),
             ('add_member', room, 'family'), ('remove_member', room, 'rio-grande')]
    # every route the client calls is in the list, so a method added later can't skip this test
    assert {name for name in vars(StationClient) if not name.startswith('_')} - {name for name, *_ in calls} == {
        'request', 'board_request', 'close_room', 'leave_room', 'revoke_key'}
    outcomes, results = {}, {}
    for name, *args in calls:
        try:
            results[name], outcomes[name] = getattr(station, name)(*args), 'ok'
        except StationError as error:
            outcomes[name] = (error.status, error.message)
        if name == 'open_room' and outcomes[name] == 'ok':
            calls += [('close_room', results[name]['id']), ('leave_room', results[name]['id'])]
    assert not [name for name, outcome in outcomes.items() if outcome != 'ok' and outcome[0] == 401], outcomes
    assert {name for name, outcome in outcomes.items() if outcome == 'ok'} >= {
        'me', 'rooms', 'room', 'post', 'watch', 'claim', 'claims', 'release', 'board', 'board_counts', 'post_item',
        'link_item', 'done_item', 'drop_item', 'unread', 'ticket', 'open_room', 'directory', 'instructions',
        'draft_instructions', 'mentions', 'close_room'}, outcomes
    with pytest.raises(StationError) as made_up:
        StationClient('http://testserver', 'made-up-ship-key', transport=transport).me()
    assert (made_up.value.status, made_up.value.message) == (401, 'Sign in required')
    assert station.revoke_key() == {'ok': True}
    with pytest.raises(StationError) as revoked:
        station.me()
    assert (revoked.value.status, revoked.value.message) == (401, 'Sign in required')


def test_the_whole_stack_behind_the_proxy_refuses_a_funnel_request_and_serves_the_same_request_without_it(env):
    """Spec 6.2 end to end: uvicorn's ProxyHeadersMiddleware, as `serve` configures it, in front of the app. A
    tailnet forwarded address plus the Funnel header is public, so starting a docking is refused; without it, served."""
    app, clients, users, clock = env
    stack = TestClient(ProxyHeadersMiddleware(app, trusted_hosts=TRUSTED_PROXY), base_url='http://testserver', client=PROXY,
                       headers={'origin': 'http://testserver', 'x-forwarded-for': '100.70.202.124'})
    docking = {'ship_name': 'rio-grande', 'machine': 'pi'}
    assert refused(stack.post('/api/dockings', json=docking, headers={'tailscale-funnel-request': '?1'}))
    served = stack.post('/api/dockings', json=docking)
    assert served.status_code == 201, served.text


def test_the_middleware_writes_nothing_for_a_ship_key(env):
    """Spec 6.6: GET /api/home refuses a ship key (403) before any ship lookup, so whatever is written was the middleware's."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    ship_client = public(app, authorization=f'Bearer {key}', **PRESENCE)
    assert ship_client.get('/api/me').status_code == 200  # the route's own check writes last_used and presence, as today
    before = written(store, ship['id'])
    clock[0] += 3600
    assert answer(ship_client.get('/api/home')) == (403, {'error': 'Ship keys cannot use this route'})
    assert written(store, ship['id']) == before
    assert ship_client.get('/api/me').status_code == 200
    assert written(store, ship['id']) != before


@pytest.mark.parametrize('failing', ['ship_key_is_valid', 'session_is_valid'])
def test_a_failed_lookup_answers_503_never_401(env, monkeypatch, caplog, failing):
    """Spec 2: the dock client reads 401 as "revoked" and would forget its key, so an internal failure is 503."""
    app, clients, users, clock = env
    ship, key = docked(app.state.store, users[0]['id'])

    def broken(*args):
        raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(app.state.store, failing, broken)
    credentials = {'authorization': f'Bearer {key}'} if failing == 'ship_key_is_valid' else {'cookie': f'superyak_session={clients[0].cookies.get("superyak_session")}'}
    with caplog.at_level(logging.WARNING):
        response = public(app, **credentials).get('/api/chats')
    assert answer(response) == (503, {'error': 'Try again shortly'})
    assert all(response.headers.get(name) == value for name, value in SECURITY.items())
    assert 'OperationalError' in caplog.text and 'database is locked' not in caplog.text
    assert clients[0].get('/api/chats').status_code == 200  # tailnet requests never look


@pytest.mark.parametrize('where', ['public', 'tailnet'])
def test_a_routes_own_error_still_reaches_the_500_handler(env, monkeypatch, where):
    app, clients, users, clock = env

    def broken(*args):
        raise RuntimeError('boom')
    monkeypatch.setattr(app.state.store, 'list_rooms', broken)
    cookie = f'superyak_session={clients[0].cookies.get("superyak_session")}'
    client = TestClient(app, base_url='http://testserver', raise_server_exceptions=False, headers={'cookie': cookie},
                        **({'client': PUBLIC_CLIENT} if where == 'public' else {}))
    assert answer(client.get('/api/chats')) == (500, {'error': 'Request could not be completed'})


CONNECTOR_ALLOWED = {('/.well-known/oauth-protected-resource', 'GET'), ('/.well-known/oauth-protected-resource/mcp', 'GET'),
                     ('/.well-known/oauth-authorization-server', 'GET'), ('/register', 'POST'), ('/authorize', 'GET'),
                     ('/authorize/signin', 'POST'), ('/authorize/decision', 'POST'),
                     ('/token', 'POST'), ('/mcp', 'GET'), ('/mcp', 'POST'), ('/mcp', 'DELETE')}


@pytest.mark.parametrize('credentials', [{}, {'authorization': 'Bearer made-up-ship-key'}], ids=['anonymous', 'made-up-key'])
def test_every_route_with_the_connector_on_refuses_a_public_request(tmp_path, monkeypatch, credentials):
    """The remote connector plan, Task 3: the walk again, at the public origin of a station with the connector on.
    Only spec 2's routes and the connector's own answer; no handler reaches a session or a ship key, and nothing changes."""
    from superyak_peer.app import create_app
    app = create_app(tmp_path / 'peer', allowed_origins=['http://testserver', 'https://home.example'],
                     public_origin='https://home.example')
    reached = []
    for name in ('session', 'ship_for_key'):
        def fail(*args, name=name, **kwargs):
            reached.append(name)
            raise AssertionError(f'a route handler ran and called store.{name}')
        monkeypatch.setattr(app.state.store, name, fail)
    walked = every_route(app)
    assert {(template, method) for template, method, _ in walked} >= CONNECTOR_ALLOWED
    client = TestClient(app, base_url='https://home.example', client=PUBLIC_CLIENT,
                        headers={'origin': 'https://home.example', **credentials})
    before = rows(app)
    for template, method, path in walked:
        if (template, method) in ALLOWED | CONNECTOR_ALLOWED:
            continue
        response = client.request(method, path, json={} if method in ('POST', 'PUT', 'PATCH') else None)
        assert refused(response), (method, path, response.status_code, response.text)
    assert reached == [] and rows(app) == before


IMPRINT_TEMPLATES = {'/api/imprints', '/api/imprints/code/{code}', '/api/imprints/{request_id}',
                     *(f'/api/imprints/{{request_id}}/{action}' for action in
                       ('confirm', 'decline', 'manifest', 'parts/{n}', 'complete', 'withdraw', 'shorten'))}


def files_under(path):
    return sorted(str(p) for p in Path(path).rglob('*'))


@pytest.mark.parametrize('credentials', [{}, {'authorization': 'Bearer made-up-ship-key'},
                                         {'cookie': 'superyak_session=made-up'}], ids=['anonymous', 'made-up-key', 'made-up-cookie'])
def test_every_route_with_the_imprint_routes_on_refuses_a_public_request(tmp_path, monkeypatch, credentials):
    """Section 2 review S1: the walk above, over a station with its imprint routes on (`imprints_dir`) and a live
    request, so every imprint template is walked with a real request id and code. No handler runs, and no row or
    file changes."""
    from imprint_support import post, request_doc, station
    st = station(tmp_path)
    made = post(st, request_doc()).json()
    reached = []
    for name in ('session', 'ship_for_key'):
        def fail(*args, name=name, **kwargs):
            reached.append(name)
            raise AssertionError(f'a route handler ran and called store.{name}')
        monkeypatch.setattr(st.store, name, fail)
    walked = every_route(st.app)
    assert {template for template, _, _ in walked if 'imprint' in template} == IMPRINT_TEMPLATES
    before, files, client = rows(st.app), files_under(tmp_path), public(st.app, **credentials)
    for template, method, path in walked:
        if (template, method) in ALLOWED:
            continue
        if 'imprint' in template:
            path = template.replace('{request_id}', made['id']).replace('{code}', made['code']).replace('{n}', '0')
        response = client.request(method, path, json={} if method in ('POST', 'PUT', 'PATCH') else None)
        assert refused(response), (method, path, response.status_code, response.text)
    assert reached == [] and rows(st.app) == before and files_under(tmp_path) == files


def test_a_public_websocket_is_closed_before_any_lookup(watched):
    from starlette.websockets import WebSocketDisconnect
    (app, clients, users, clock), reached = watched
    with pytest.raises(WebSocketDisconnect):
        with public(app, cookie=f'superyak_session={clients[0].cookies.get("superyak_session")}').websocket_connect('/api/chats'):
            pass
    assert reached == []


def served(monkeypatch, tmp_path, *args):
    """What `serve` hands uvicorn.run, or the error it exits with."""
    import uvicorn
    from superyak_peer.__main__ import main
    calls = []
    monkeypatch.setattr(uvicorn, 'run', lambda app, **kwargs: calls.append(kwargs))
    main(['serve', '--data-dir', str(tmp_path / 'peer'), *args])
    return calls[0]


def test_serve_turns_off_the_access_log(monkeypatch, tmp_path):
    """Spec 4: no secret lands in a log; a docking poll from an older client still carries ?secret=."""
    assert served(monkeypatch, tmp_path)['access_log'] is False
    behind = served(monkeypatch, tmp_path, '--proxy-headers', '--origin', 'https://station.example.ts.net')
    assert (behind['access_log'], behind['proxy_headers'], behind['forwarded_allow_ips']) == (False, True, TRUSTED_PROXY)


@pytest.mark.parametrize('host', ['localhost', '::1', '0.0.0.0', '100.70.202.124'])
def test_proxy_headers_need_an_ipv4_loopback_bind(monkeypatch, tmp_path, capsys, host):
    """Spec 1: the trusted proxy is 127.0.0.1 only, so a proxy on ::1 would make every request look like loopback."""
    with pytest.raises(SystemExit) as refused:
        served(monkeypatch, tmp_path, '--host', host, '--proxy-headers', '--origin', 'https://station.example.ts.net')
    assert refused.value.code == 1 and 'IPv4 loopback' in capsys.readouterr().err
    assert served(monkeypatch, tmp_path, '--host', '127.0.0.1', '--proxy-headers', '--origin', 'https://station.example.ts.net')['proxy_headers']


@pytest.mark.parametrize('path', ['/api/me/', '/API/me', '/api%2Fme', '/api/%6De', '//api/me', '/assets/../api/me',
                                  '/api/./me', '/api/dockings/', '/public/../api/home'])
def test_odd_path_forms_never_slip_past_the_allow_list(env, path):
    """The allow-list matches with the router's own route matching, so these are safe today; this pins it, so a later
    switch to prefix matching can't open them. Each is refused by the middleware or reaches only a 404 it can't use."""
    app, _clients, _users, _clock = env
    client = public(app)
    for method in ('GET', 'POST'):
        response = client.request(method, path)
        assert response.status_code in (401, 404, 405), (method, path, response.status_code)
        assert 'user' not in (response.json() if response.headers.get('content-type', '').startswith('application/json') else {})
