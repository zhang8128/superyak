"""Shared fixtures for the remote connector's tests (plan 2026-10-28-remote-connector)."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PUBLIC_ORIGIN = 'https://home.example'
CALLBACK = 'https://claude.ai/api/mcp/auth_callback'
PUBLIC_CLIENT = ('203.0.113.5', 50000)  # an internet address, as a Funnel request looks after the proxy


@pytest.fixture
def home(tmp_path):
    """A home with the connector on: its public origin is one of its origins, beside the test server's."""
    from superyak_peer.app import create_app
    clock = [1000000.0]
    app = create_app(tmp_path / 'peer', clock=lambda: clock[0], allowed_origins=['http://testserver', PUBLIC_ORIGIN],
                     public_origin=PUBLIC_ORIGIN)
    return SimpleNamespace(app=app, store=app.state.store, clock=clock)


def public_client(app, **headers):
    """A public request at the public origin, with no Origin header unless one is given (Claude's servers send none)."""
    return TestClient(app, base_url=PUBLIC_ORIGIN, client=PUBLIC_CLIENT, headers=headers)


# ---- The real flow, moved here from test_connector_auth.py for Tasks 7 to 9 (plan Task 6's `connected`): register,
# /authorize, the sign-in, Allow and /token, as Claude and the consent page send them. ----

REGISTRATION = {'redirect_uris': [CALLBACK], 'client_name': 'Claude', 'grant_types': ['authorization_code', 'refresh_token'],
                'response_types': ['code'], 'token_endpoint_auth_method': 'none'}
CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'  # RFC 7636's S256 example challenge
RESOURCE_URL = PUBLIC_ORIGIN + '/mcp'
VERIFIER = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'  # RFC 7636's example verifier for CHALLENGE


def register(app, body=None, source='203.0.113.5'):
    client = TestClient(app, base_url=PUBLIC_ORIGIN, client=(source, 50000))
    return client.post('/register', json=REGISTRATION if body is None else body)


def authorize(home, client=None, raw=None, **override):
    """GET /authorize as Claude sends it for `client` (an id; a new registration when None), with `override` replacing
    (or, as None, dropping) a parameter; or `raw`, a query string as it is. Never follows the redirect."""
    browser = public_client(home.app)
    if raw is not None:
        return browser.get('/authorize?' + raw, follow_redirects=False)
    params = {'response_type': 'code', 'client_id': client or register(home.app).json()['client_id'],
              'redirect_uri': CALLBACK, 'state': 'st-1', 'code_challenge': CHALLENGE, 'code_challenge_method': 'S256',
              'resource': RESOURCE_URL, 'scope': 'rooms.read offline_access'} | override
    return browser.get('/authorize', params={k: v for k, v in params.items() if v is not None}, follow_redirects=False)


def redirected(response):
    """(the redirect's URL without its query, its query as one value per name) for a 303."""
    from urllib.parse import parse_qs, urlsplit
    assert response.status_code == 303, (response.status_code, response.text)
    where = urlsplit(response.headers['location'])
    return where._replace(query='', fragment='').geturl(), {k: v[0] for k, v in parse_qs(where.query).items()}, where.fragment


def person(home, username='sam@example.org', name='Sam Example'):
    return home.store.create_user(username, name, 'long-password-' + username.split('@')[0])


def consent(home, **headers):
    """The consent page's own requests: at the public origin, from a public address, with the home's Origin."""
    return public_client(home.app, origin=PUBLIC_ORIGIN, **headers)


def sign_in(home, fragment, username='sam@example.org', password=None, csrf=None):
    """The consent page's sign-in; `csrf` is what Switch person sends, the token the page holds for that request."""
    return consent(home).post('/authorize/signin', json={
        'request': fragment, 'username': username,
        'password': 'long-password-' + username.split('@')[0] if password is None else password}
        | ({'csrf': csrf} if csrf is not None else {}))


def a_fragment(home, client=None, **override):
    return redirected(authorize(home, client, **override))[2]


def table(home, name):
    with home.store.transaction() as db:
        return [dict(row) for row in db.execute(f'SELECT * FROM {name}')]


def signed_in(home, client=None, username='sam@example.org', **override):
    """A sign-in on a fresh request: (its client id, the view)."""
    client = client or register(home.app).json()['client_id']
    view = sign_in(home, a_fragment(home, client, **override), username)
    assert view.status_code == 200, view.text
    return client, view.json()


def decide(home, view, allow=True, rooms=None, **extra):
    body = {'pending': view['pending'], 'csrf': view['csrf'], 'allow': allow,
            'rooms': [room['room'] for room in view['rooms'] if not room['cloud'] and not room['earlier_of']][:1]
            if rooms is None else rooms} | extra
    return consent(home).post('/authorize/decision', json=body)


def sent_back(decision):
    from urllib.parse import parse_qs, urlsplit
    assert decision.status_code == 200, decision.text
    where = urlsplit(decision.json()['redirect'])
    return where._replace(query='').geturl(), {k: v[0] for k, v in parse_qs(where.query).items()}


def token(home, form, *, content_type='application/x-www-form-urlencoded', raw=None, **headers):
    """POST /token as Claude sends it: form-encoded, from a public address, with no Origin."""
    from urllib.parse import urlencode
    return public_client(home.app, **headers).post('/token', content=raw if raw is not None else urlencode(form),
                                                   headers={'content-type': content_type})


def allowed(home, client=None, rooms='*', state='st-1', **override):
    """A real Allow: (client id, code, the grant's rooms as sent). Sam signs in on a fresh request and allows."""
    if not table(home, 'users') or not any(row['username'] == 'sam@example.org' for row in table(home, 'users')):
        person(home)
    client, view = signed_in(home, client, state=state, **override)
    _, query = sent_back(decide(home, view, rooms=rooms))
    return client, query['code']


def exchange(home, for_client, the_code, **override):
    """The code exchange as Claude sends it; `override` replaces (or, as None, drops) any field, `code` included."""
    form = {'grant_type': 'authorization_code', 'code': the_code, 'redirect_uri': CALLBACK, 'client_id': for_client,
            'code_verifier': VERIFIER, 'resource': RESOURCE_URL} | override
    return token(home, {k: v for k, v in form.items() if v is not None})


def refresh(home, client, refresh_token, **override):
    form = {'grant_type': 'refresh_token', 'refresh_token': refresh_token, 'client_id': client,
            'resource': RESOURCE_URL} | override
    return token(home, {k: v for k, v in form.items() if v is not None})


def bearer(home, access):
    return home.store.bearer(access, RESOURCE_URL)


@pytest.fixture
def connected(home):
    """Plan Task 6's `connected`: Sam connected by the real flow (register, /authorize, the sign-in, Allow with two of
    Sam's rooms, /token). It is `home` with `tokens` (the token answer), `rooms` (the chosen room ids), `client` (the
    client id) and `person` (Sam). Tasks 7 to 9 use it."""
    sam = person(home)
    rooms = [home.store.create_room(sam['id'], title, [])['id'] for title in ('Care plan', 'Lab notes')]
    client, view = signed_in(home)
    _, query = sent_back(decide(home, view, rooms=rooms))
    tokens = exchange(home, client, query['code']).json()
    return SimpleNamespace(**vars(home), tokens=tokens, rooms=rooms, client=client, person=sam)


def mcp(home, message, token=None, **headers):
    """POST /mcp as Claude sends it: JSON, from a public address, with no Origin; `message` as JSON, or bytes as they are."""
    auth = {'authorization': f'Bearer {token}'} if token is not None else {}
    client = public_client(home.app, **auth, **headers)
    if isinstance(message, bytes):
        return client.post('/mcp', content=message, headers={'content-type': 'application/json'})
    return client.post('/mcp', json=message)


def rpc(method, params=None, id=1):
    return {'jsonrpc': '2.0', 'id': id, 'method': method} | ({'params': params} if params is not None else {})
