"""A public write's body is capped by its route while it is read (board fix:public-post-body-cap-before-buffer).

BrowserBoundary read up to MAX_REQUEST before any route looked at a body, so a stranger could make the home hold 6 MB per
request for a route that takes 8 KB, and for the two sign-in routes, which had no cap of their own, parse it as JSON too."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from superyak_peer.app import MAX_REQUEST, PUBLIC_ROUTES, ROUTE_BODY_MAX, SIGN_IN_BODY_MAX, BrowserBoundary, create_app
from superyak_peer.connector import MCP_BODY_MAX, REGISTER_BODY_MAX


def boundary_run(path, *, chunk, chunks=10_000):
    """BrowserBoundary on a POST of `chunks` chunks: how many it pulled, what the route got, and any answer it gave."""
    pulled, got, answers = [0], [], []

    async def receive():
        pulled[0] += 1
        return {'type': 'http.request', 'body': b'x' * chunk, 'more_body': pulled[0] < chunks}

    async def route(scope, route_receive, send):
        got.append(await route_receive())

    async def send(message):
        answers.append(message)

    scope = {'type': 'http', 'method': 'POST', 'path': path, 'scheme': 'http',
             'headers': [(b'host', b'testserver'), (b'origin', b'http://testserver')]}
    asyncio.run(BrowserBoundary(route)(scope, receive, send))
    return pulled[0], got, answers


def test_every_public_write_has_a_cap_so_a_route_added_later_cant_skip_it():
    assert {path for path, methods in PUBLIC_ROUTES.items() if 'POST' in methods} == set(ROUTE_BODY_MAX)


@pytest.mark.parametrize('path, cap', [('/register', REGISTER_BODY_MAX), ('/authorize/signin', REGISTER_BODY_MAX),
                                       ('/authorize/decision', REGISTER_BODY_MAX), ('/token', REGISTER_BODY_MAX),
                                       ('/mcp', MCP_BODY_MAX), ('/api/login', SIGN_IN_BODY_MAX),
                                       ('/api/invitations/redeem', SIGN_IN_BODY_MAX)])
def test_a_public_route_never_buffers_past_its_cap_and_gets_to_answer_for_itself(path, cap):
    chunk = 1024
    pulled, got, answers = boundary_run(path, chunk=chunk)
    assert pulled == cap // chunk + 1, 'one chunk past the cap, and no more'
    assert answers == [], 'the route says too large, in its own words'
    assert got[0]['more_body'] is False and cap < len(got[0]['body']) <= cap + chunk


def test_a_body_at_the_cap_reaches_its_route_whole():
    pulled, got, _ = boundary_run('/register', chunk=REGISTER_BODY_MAX, chunks=1)
    assert pulled == 1 and len(got[0]['body']) == REGISTER_BODY_MAX and got[0]['more_body'] is False


def test_any_other_route_keeps_the_6_mb_bound():
    chunk = 1024 * 1024
    pulled, got, answers = boundary_run('/api/rooms/x/messages', chunk=chunk)
    assert pulled == MAX_REQUEST // chunk + 1 and got == []
    assert answers[0]['status'] == 413
    pulled, got, answers = boundary_run('/api/rooms/x/messages', chunk=chunk, chunks=6)
    assert pulled == 6 and len(got[0]['body']) == 6 * chunk and answers == []


@pytest.fixture
def home(tmp_path):
    return TestClient(create_app(tmp_path / 'home', allowed_origins=['http://testserver']), base_url='http://testserver',
                      headers={'origin': 'http://testserver'})


@pytest.mark.parametrize('path', ['/api/login', '/api/invitations/redeem'])
def test_a_sign_in_route_refuses_past_its_cap_before_it_parses(home, path, monkeypatch):
    parsed = []
    real_loads = json.loads
    monkeypatch.setattr(json, 'loads', lambda *a, **kw: (parsed.append(1), real_loads(*a, **kw))[1])
    pad = b'{"username": "a", "password": "' + b'x' * SIGN_IN_BODY_MAX + b'"}'
    answer = home.post(path, content=pad, headers={'content-type': 'application/json'})
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


def test_a_sign_in_at_its_cap_is_still_judged_as_a_sign_in(home):
    raw = json.dumps({'username': 'nobody', 'password': 'x'}).encode()
    raw = raw[:-1] + b' ' * (SIGN_IN_BODY_MAX - len(raw)) + b'}'
    assert len(raw) == SIGN_IN_BODY_MAX
    assert home.post('/api/login', content=raw, headers={'content-type': 'application/json'}).status_code == 401
