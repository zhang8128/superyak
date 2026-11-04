"""A public write's body is capped by its route while it is read (board fix:public-post-body-cap-before-buffer).

BrowserBoundary read up to MAX_REQUEST before any route looked at a body, so a stranger could make the home hold 6 MB per
request for a route that takes 8 KB, and for the two sign-in routes, which had no cap of their own, parse it as JSON too."""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Match

from connector_support import connected, consent, home, public_client  # noqa: F401
from superyak_peer.app import (BODYLESS_METHODS, MAX_REQUEST, PUBLIC_ROUTES, ROUTE_BODY_MAX, SIGN_IN_BODY_MAX, BrowserBoundary,
                               create_app, dispatched, route_body_max)
from superyak_peer.connector import MCP_BODY_MAX, REGISTER_BODY_MAX


PUBLIC_ORIGIN = 'https://home.example'


@pytest.fixture(scope='module')
def router(tmp_path_factory):
    """The real router, with the connector's routes: the cap is found by what it dispatches, not by a path's text."""
    return create_app(tmp_path_factory.mktemp('home') / 'home', allowed_origins=[PUBLIC_ORIGIN],
                      public_origin=PUBLIC_ORIGIN).router


def boundary_run(router, path, *, chunk, chunks=10_000, method='POST'):
    """BrowserBoundary on a request of `chunks` chunks: how many it pulled, what the route got, and any answer it gave."""
    pulled, got, answers = [0], [], []

    async def receive():
        pulled[0] += 1
        return {'type': 'http.request', 'body': b'x' * chunk, 'more_body': pulled[0] < chunks}

    async def route(scope, route_receive, send):
        got.append(await route_receive())

    async def send(message):
        answers.append(message)

    scope = {'type': 'http', 'method': method, 'path': path, 'scheme': 'http', 'root_path': '',
             'headers': [(b'host', b'testserver'), (b'origin', b'http://testserver')]}
    asyncio.run(BrowserBoundary(route, router=router)(scope, receive, send))
    return pulled[0], got, answers


def test_the_sign_in_cap_is_8_kb():
    assert SIGN_IN_BODY_MAX == 8192


def test_every_public_route_that_takes_a_body_has_a_cap_so_one_added_later_cant_skip_it():
    """By method, not only POST: anything but a bodyless method needs a line, or a stranger's body is read to 6 MB."""
    assert {path for path, methods in PUBLIC_ROUTES.items() if set(methods) - BODYLESS_METHODS} == set(ROUTE_BODY_MAX)
    assert BODYLESS_METHODS == {'GET', 'HEAD', 'OPTIONS'}


@pytest.mark.parametrize('path, cap', [('/register', REGISTER_BODY_MAX), ('/authorize/signin', REGISTER_BODY_MAX),
                                       ('/authorize/decision', REGISTER_BODY_MAX), ('/token', REGISTER_BODY_MAX),
                                       ('/mcp', MCP_BODY_MAX), ('/api/login', SIGN_IN_BODY_MAX),
                                       ('/api/invitations/redeem', SIGN_IN_BODY_MAX)])
def test_a_public_route_never_buffers_past_its_cap_and_gets_to_answer_for_itself(router, path, cap):
    chunk = 1024
    pulled, got, answers = boundary_run(router, path, chunk=chunk)
    assert pulled == cap // chunk + 1, 'one chunk past the cap, and no more'
    assert answers == [], 'the route says too large, in its own words'
    assert got[0]['more_body'] is False and cap < len(got[0]['body']) <= cap + chunk


@pytest.mark.parametrize('path, cap', [('/api/login\n', SIGN_IN_BODY_MAX), ('/api/invitations/redeem\n', SIGN_IN_BODY_MAX),
                                       ('/register\n', REGISTER_BODY_MAX), ('/token\n', REGISTER_BODY_MAX),
                                       ('/mcp\n', MCP_BODY_MAX)])
def test_the_cap_follows_what_the_router_dispatches_not_the_paths_text(router, path, cap):
    """A route's pattern ends in `$`, which matches before a trailing newline: `/api/login%0A` is login to the router and
    to nothing in a dict. Found by the automated security review of the first version of this fix."""
    pulled, got, answers = boundary_run(router, path, chunk=1024)
    assert pulled == cap // 1024 + 1 and answers == [] and got[0]['more_body'] is False


@pytest.mark.parametrize('method', sorted(BODYLESS_METHODS))
@pytest.mark.parametrize('path', ['/', '/register', '/mcp', '/api/health', '/api/rooms/x/messages', '/not/a/route'])
def test_a_bodyless_method_reads_nothing_at_all_and_its_route_sees_no_body(router, path, method):
    pulled, got, answers = boundary_run(router, path, chunk=1024, method=method)
    assert pulled == 0 and answers == []
    assert got == [{'type': 'http.request', 'body': b'', 'more_body': False}]


def test_a_path_no_route_takes_keeps_the_6_mb_bound_and_doesnt_fall_over(router):
    pulled, got, answers = boundary_run(router, '/not/a/route', chunk=1024, chunks=64)
    assert pulled == 64 and len(got[0]['body']) == 64 * 1024 and answers == []


def test_the_cap_holds_for_a_method_the_route_refuses(router):
    assert boundary_run(router, '/register', chunk=1024, method='PUT')[0] == REGISTER_BODY_MAX // 1024 + 1
    assert boundary_run(router, '/mcp', chunk=1024, method='DELETE')[0] == MCP_BODY_MAX // 1024 + 1


PUBLIC_GETS = sorted(('/assets/app.js' if path == '/assets' else
                      path.replace('{key}', 'k').replace('{layer_id}', 'l'), method)
                     for path, methods in PUBLIC_ROUTES.items() for method in methods if method in BODYLESS_METHODS)


@pytest.mark.parametrize('client', [('203.0.113.5', 50000), ('127.0.0.1', 50000)], ids=['stranger', 'tailnet'])
@pytest.mark.parametrize('path, method', PUBLIC_GETS)
def test_the_real_app_reads_no_body_on_any_public_get(tmp_path, path, method, client):
    """Through the whole stack, for every public template and method. 6 MB held per stalled connection before this."""
    app = create_app(tmp_path / 'home', allowed_origins=[PUBLIC_ORIGIN], public_origin=PUBLIC_ORIGIN)
    pulled, started = [0], []

    async def receive():
        pulled[0] += 1
        return {'type': 'http.request', 'body': b'x' * 1024, 'more_body': True}

    async def send(message):
        if message['type'] == 'http.response.start':
            started.append(message['status'])

    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': 'https',
             'path': path, 'raw_path': path.encode(), 'root_path': '', 'query_string': b'', 'client': client,
             'server': ('home.example', 443), 'headers': [(b'host', b'home.example'), (b'content-length', b'6000000')]}
    asyncio.run(app(scope, receive, send))
    assert pulled[0] == 0 and started and started[0] < 500


FORM = {'content-type': 'application/x-www-form-urlencoded'}
JSON_TYPE = {'content-type': 'application/json'}


def padded_json(length):
    """A valid JSON body of exactly `length` bytes, padded after its brace, so a route parsing a prefix would answer it."""
    return b'{}' + b' ' * (length - 2)


def padded_form(length):
    return b'x=' + b'y' * (length - 2)


@pytest.mark.parametrize('path, body, headers, cap, words', [
    ('/register', padded_json, {}, REGISTER_BODY_MAX, 'invalid_client_metadata'),
    ('/token', padded_form, FORM, REGISTER_BODY_MAX, 'invalid_request'),
    ('/authorize/signin', padded_json, JSON_TYPE, REGISTER_BODY_MAX, 'invalid_request'),
    ('/authorize/decision', padded_json, JSON_TYPE, REGISTER_BODY_MAX, 'invalid_request'),
    ('/mcp', padded_json, JSON_TYPE, MCP_BODY_MAX, 'Request too large'),
    ('/api/login', padded_json, JSON_TYPE, SIGN_IN_BODY_MAX, 'Request too large'),
    ('/api/invitations/redeem', padded_json, JSON_TYPE, SIGN_IN_BODY_MAX, 'Request too large'),
])
def test_each_routes_own_cap_is_the_tables_at_its_edge(connected, path, body, headers, cap, words):
    """The hand-on is truncated, so it is safe only while a route's own check equals its entry. One byte over, on JSON that
    parses, answers the route's own 413, not a request made of the prefix. At the cap it isn't refused for size."""
    client = public_client(connected.app) if path in ('/register', '/token', '/mcp') else consent(connected)
    sent = dict(headers, authorization=f'Bearer {connected.tokens["access_token"]}') if path == '/mcp' else headers
    over = client.post(path, content=body(cap + 1), headers=sent)
    assert (over.status_code, over.json()) == (413, {'error': words}), over.text
    assert client.post(path, content=body(cap), headers=sent).status_code != 413


def test_an_oauth_write_on_a_near_miss_of_its_path_still_needs_the_same_origin(connected):
    """OAUTH_WRITES is exact text, so `/register%0A`, which the router dispatches to /register, isn't exempt: it fails closed."""
    client = public_client(connected.app)
    assert client.post('/register', content=padded_json(16)).status_code != 403
    assert client.post('/register%0A', content=padded_json(16)).status_code == 403


def test_one_rule_finds_the_route_for_the_cap_and_the_guard():
    """The first bypass here was two copies of this rule drifting: both now ask `dispatched`."""
    def stub(path, match):
        return type('Route', (), {'path': path, 'matches': lambda self, scope: (match, {})})()
    first, second = stub('/token', Match.PARTIAL), stub('/mcp', Match.FULL)
    assert dispatched(type('R', (), {'routes': [first, second]}), {}) is second
    assert dispatched(type('R', (), {'routes': [first, stub('/mcp', Match.PARTIAL)]}), {}) is first
    assert dispatched(type('R', (), {'routes': [stub('/x', Match.NONE)]}), {}) is None
    source = (Path(__file__).resolve().parent.parent / 'superyak_peer' / 'app.py').read_text()
    assert source.count('route.matches(') == 1


@pytest.mark.parametrize('path', ['/api/login', '/api/login\n', '/api/invitations/redeem'])
def test_the_real_app_stops_reading_a_strangers_body_at_the_cap(tmp_path, path):
    """Through the whole stack as create_app builds it, the guard and the boundary both: the wiring is the point."""
    app = create_app(tmp_path / 'home', allowed_origins=['http://testserver'])
    pulled, started = [0], []

    async def receive():
        pulled[0] += 1
        return {'type': 'http.request', 'body': b'x' * 1024, 'more_body': True}

    async def send(message):
        if message['type'] == 'http.response.start':
            started.append(message['status'])

    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST', 'scheme': 'http',
             'path': path, 'raw_path': path.encode(), 'root_path': '', 'query_string': b'', 'client': ('203.0.113.5', 50000),
             'server': ('testserver', 80), 'headers': [(b'host', b'testserver'), (b'origin', b'http://testserver'),
                                                       (b'content-type', b'application/json')]}
    asyncio.run(app(scope, receive, send))
    assert pulled[0] == SIGN_IN_BODY_MAX // 1024 + 1 and started == [413]


def test_the_first_partial_match_decides_as_it_does_for_the_router():
    """A method the route doesn't take is still its path: the same rule as PublicRoute.allowed, and a full match wins."""
    def stub(path, match):
        return type('Route', (), {'path': path, 'matches': lambda self, scope: (match, {})})()
    assert route_body_max(type('R', (), {'routes': [stub('/token', Match.PARTIAL), stub('/mcp', Match.PARTIAL)]}), {}) \
        == REGISTER_BODY_MAX
    assert route_body_max(type('R', (), {'routes': [stub('/token', Match.PARTIAL), stub('/mcp', Match.FULL)]}), {}) \
        == MCP_BODY_MAX
    assert route_body_max(type('R', (), {'routes': [stub('/token', Match.NONE)]}), {}) is None


class CountingRouter:
    """A router that counts its scans: a request under every cap should cost none, and a larger one one."""

    def __init__(self, router):
        self.real, self.scans = router, 0

    @property
    def routes(self):
        self.scans += 1
        return self.real.routes


def test_a_small_body_costs_no_route_scan_and_a_large_one_costs_one(router):
    counting = CountingRouter(router)
    boundary_run(counting, '/api/rooms/x/messages', chunk=1024, chunks=4)
    assert counting.scans == 0
    boundary_run(counting, '/api/rooms/x/messages', chunk=1024, chunks=64)
    assert counting.scans == 1


def test_a_body_at_the_cap_reaches_its_route_whole(router):
    pulled, got, _ = boundary_run(router, '/register', chunk=REGISTER_BODY_MAX, chunks=1)
    assert pulled == 1 and len(got[0]['body']) == REGISTER_BODY_MAX and got[0]['more_body'] is False


def test_any_other_route_keeps_the_6_mb_bound(router):
    chunk = 1024 * 1024
    pulled, got, answers = boundary_run(router, '/api/rooms/x/messages', chunk=chunk)
    assert pulled == MAX_REQUEST // chunk + 1 and got == []
    assert answers[0]['status'] == 413
    pulled, got, answers = boundary_run(router, '/api/rooms/x/messages', chunk=chunk, chunks=6)
    assert pulled == 6 and len(got[0]['body']) == 6 * chunk and answers == []


@pytest.fixture
def sign_in_client(tmp_path):
    return TestClient(create_app(tmp_path / 'home', allowed_origins=['http://testserver']), base_url='http://testserver',
                      headers={'origin': 'http://testserver'})


@pytest.mark.parametrize('path', ['/api/login', '/api/invitations/redeem', '/api/login%0A', '/api/invitations/redeem%0A'])
def test_a_sign_in_route_refuses_past_its_cap_before_it_parses(sign_in_client, path, monkeypatch):
    parsed = []
    real_loads = json.loads
    monkeypatch.setattr(json, 'loads', lambda *a, **kw: (parsed.append(1), real_loads(*a, **kw))[1])
    pad = b'{"username": "a", "password": "' + b'x' * SIGN_IN_BODY_MAX + b'"}'
    answer = sign_in_client.post(path, content=pad, headers={'content-type': 'application/json'})
    assert parsed == [], 'refused before anything parsed it'
    assert (answer.status_code, answer.json()) == (413, {'error': 'Request too large'})


@pytest.mark.parametrize('path', ['/api/login/', '/register/', '/token/', '/api/login//', '/API/LOGIN'])
def test_a_stranger_cant_slip_past_the_table_on_a_near_miss_of_a_path(tmp_path, path):
    """The table is by exact path, and a near miss isn't in it. The guard stands outermost, so a public request to one
    is refused before BrowserBoundary reads a byte: only a route the guard allows is ever read."""
    app = create_app(tmp_path / 'home', allowed_origins=['http://testserver'])
    pulled = []
    real_call = BrowserBoundary.__call__

    async def watched(self, scope, receive, send):
        pulled.append(scope['path'])
        return await real_call(self, scope, receive, send)
    BrowserBoundary.__call__ = watched
    try:
        stranger = TestClient(app, base_url='http://testserver', client=('203.0.113.5', 50000),
                              headers={'origin': 'http://testserver'})
        answer = stranger.post(path, content=b'x' * (2 * 1024 * 1024), follow_redirects=False)
    finally:
        BrowserBoundary.__call__ = real_call
    assert answer.status_code in (401, 404) and pulled == []


def test_a_route_with_no_cap_of_its_own_still_reads_its_body(sign_in_client):
    answer = sign_in_client.post('/api/access-requests', json={'name': 'x', 'contact': 'y', 'note': 'z'})
    assert answer.status_code not in (413, 500), answer.text


def test_a_sign_in_at_its_cap_is_still_judged_as_a_sign_in(sign_in_client):
    raw = json.dumps({'username': 'nobody', 'password': 'x'}).encode()
    raw = raw[:-1] + b' ' * (SIGN_IN_BODY_MAX - len(raw)) + b'}'
    assert len(raw) == SIGN_IN_BODY_MAX
    assert sign_in_client.post('/api/login', content=raw, headers={'content-type': 'application/json'}).status_code == 401
