"""The remote connector's configuration, discovery and boundary (plan 2026-10-28-remote-connector, Task 3; spec
"Where it lives", "The home is its own authorization server")."""
import pytest
from fastapi.testclient import TestClient
from connector_support import CALLBACK, PUBLIC_CLIENT, PUBLIC_ORIGIN, home, public_client  # noqa: F401

RESOURCE = {'resource': 'https://home.example/mcp', 'authorization_servers': ['https://home.example'],
            'bearer_methods_supported': ['header'], 'scopes_supported': ['rooms.read']}
ISSUER = {'issuer': 'https://home.example', 'authorization_endpoint': 'https://home.example/authorize',
          'token_endpoint': 'https://home.example/token', 'registration_endpoint': 'https://home.example/register',
          'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code', 'refresh_token'],
          'token_endpoint_auth_methods_supported': ['none'], 'code_challenge_methods_supported': ['S256'],
          'scopes_supported': ['rooms.read', 'offline_access'], 'authorization_response_iss_parameter_supported': True}
CONNECTOR_PATHS = [('GET', '/.well-known/oauth-protected-resource'), ('GET', '/.well-known/oauth-protected-resource/mcp'),
                   ('GET', '/.well-known/oauth-authorization-server'), ('POST', '/register'), ('GET', '/authorize'),
                   ('POST', '/authorize/request'), ('POST', '/authorize/signin'), ('POST', '/authorize/decision'),
                   ('POST', '/token'), ('GET', '/mcp'), ('POST', '/mcp'), ('DELETE', '/mcp')]


def test_discovery_documents_carry_the_exact_values(home):
    client = public_client(home.app)
    for path in ('/.well-known/oauth-protected-resource/mcp', '/.well-known/oauth-protected-resource'):
        found = client.get(path)
        assert (found.status_code, found.json()) == (200, RESOURCE), path
    found = client.get('/.well-known/oauth-authorization-server')
    assert (found.status_code, found.json()) == (200, ISSUER)


def test_connector_routes_are_404_on_any_other_origin(home):
    """Every connector route at the test server's origin is 404. A tailnet client using the public name is served, as
    on the Pi, where Funnel and the tailnet share one name: the connector authenticates by OAuth, not by where a request
    comes from."""
    other = TestClient(home.app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    for method, path in CONNECTOR_PATHS:
        assert other.request(method, path).status_code == 404, (method, path)
    tailnet = TestClient(home.app, base_url=PUBLIC_ORIGIN)
    assert tailnet.get('/.well-known/oauth-authorization-server').json() == ISSUER


def test_no_connector_route_exists_without_a_public_origin(env):
    app = env[0]
    client = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    templates = {getattr(route, 'path', None) for route in app.router.routes}
    assert not templates & {path for _, path in CONNECTOR_PATHS}
    for method, path in CONNECTOR_PATHS:
        assert client.request(method, path).status_code in (404, 405), (method, path)
    assert getattr(app.state, 'public_origin', None) is None


def test_every_connector_route_answers_a_public_request(home):
    """Each is on PublicRoute's allow-list, so a public request with no session reaches its handler: the discovery
    documents answer, and the routes later tasks build answer 501 until then, never the middleware's refusal."""
    client = public_client(home.app, origin=PUBLIC_ORIGIN)
    for method, path in CONNECTOR_PATHS:
        response = client.request(method, path, json={} if method == 'POST' else None)
        expected = 200 if path.startswith('/.well-known/') else 400 if path == '/register' else 501  # {} is no registration
        assert response.status_code == expected, (method, path, response.status_code, response.text)


def test_register_token_and_mcp_pass_the_boundary_without_an_origin(home):
    client = public_client(home.app)
    for path, ran in (('/register', 400), ('/token', 501), ('/mcp', 501)):
        response = client.post(path)
        assert response.status_code == ran, (path, response.text)  # the handler ran: never 'Same-origin request required'


def test_the_body_bound_still_holds_where_the_origin_check_is_skipped(home):
    """Rio Grande's section 2, S2: /register, /token and /mcp are the only anonymous public POSTs without the
    same-origin check, so the 6 MB bound must still apply to them."""
    from superyak_peer.app import MAX_REQUEST
    client = public_client(home.app)
    for path in ('/register', '/token', '/mcp'):
        response = client.post(path, content=b'x' * (MAX_REQUEST + 1))
        assert (response.status_code, response.json()) == (413, {'error': 'Request too large'}), path


def test_another_scheme_or_port_on_the_public_name_is_another_origin(tmp_path):
    """S3: the origin rule compares scheme, host and port, not the host alone."""
    from superyak_peer.app import create_app
    app = create_app(tmp_path / 'peer', allowed_origins=[PUBLIC_ORIGIN, 'https://home.example:8443', 'http://home.example'],
                     public_origin=PUBLIC_ORIGIN)
    for base in ('https://home.example:8443', 'http://home.example'):
        client = TestClient(app, base_url=base, headers={'origin': base})
        for method, path in CONNECTOR_PATHS:
            assert client.request(method, path).status_code == 404, (base, method, path)


def test_the_consent_posts_still_need_the_homes_origin(home):
    for path in ('/authorize/request', '/authorize/signin', '/authorize/decision'):
        response = public_client(home.app).post(path, json={})
        assert (response.status_code, response.json()) == (403, {'error': 'Same-origin request required'}), path


def test_no_connector_route_sends_cors_headers(home):
    client = public_client(home.app, origin='https://claude.ai')
    for method, path in CONNECTOR_PATHS:
        response = client.request(method, path)
        assert not [name for name in response.headers if name.lower().startswith('access-control-')], (method, path)


def test_a_canonical_public_origin_with_a_port_is_accepted(tmp_path):
    from superyak_peer.app import create_app
    app = create_app(tmp_path / 'peer', allowed_origins=['https://home.example:8443'], public_origin='https://home.example:8443')
    assert app.state.public_origin == 'https://home.example:8443'


@pytest.mark.parametrize('origins, public', [
    (['http://testserver'], 'https://home.example'),          # not one of the origins
    (['http://home.example'], 'http://home.example'),          # not https
    (['https://home.example/x'], 'https://home.example/x'),    # a path
    (['https://Home.example'], 'https://Home.example'),         # not lowercase
    (['https://home.example?'], 'https://home.example?'),       # an empty query
    (['https://home.example#'], 'https://home.example#'),       # an empty fragment
    (['https://home.example:'], 'https://home.example:'),       # an empty port
    (['https://home.example:443'], 'https://home.example:443'),  # the default port, spelled out
    (['https://home.example:0443'], 'https://home.example:0443'),  # a leading zero
    (['https://home.example.'], 'https://home.example.'),       # a trailing dot
    (['https://user@home.example'], 'https://user@home.example'),  # userinfo
    (['https://hôme.example'], 'https://hôme.example'),         # not ASCII
    (['https://home.example\n'], 'https://home.example\n'),     # a newline
    (['https://home\\example'], 'https://home\\example'),      # a backslash
])
def test_create_app_refuses_a_public_origin_it_cant_be(tmp_path, origins, public):
    """D13 and S1: one canonical https origin, or serve stops; a typo never quietly turns the connector off."""
    from superyak_peer.app import create_app
    with pytest.raises(ValueError):
        create_app(tmp_path / 'peer', allowed_origins=origins, public_origin=public)


def test_serve_keeps_access_logs_off_with_a_public_origin(tmp_path, monkeypatch):
    import uvicorn
    from superyak_peer.__main__ import main
    ran = {}
    monkeypatch.setattr(uvicorn, 'run', lambda app, **options: ran.update(app=app, **options))
    main(['serve', '--data-dir', str(tmp_path / 'peer'), '--origin', PUBLIC_ORIGIN, '--proxy-headers',
          '--public-origin', PUBLIC_ORIGIN, '--connector-callback', CALLBACK])
    assert ran['access_log'] is False and ran['app'].state.public_origin == PUBLIC_ORIGIN


# ---- Task 4: registration (spec "Registration (/register)") ----

REGISTRATION = {'redirect_uris': [CALLBACK], 'client_name': 'Claude', 'grant_types': ['authorization_code', 'refresh_token'],
                'response_types': ['code'], 'token_endpoint_auth_method': 'none'}


def register(app, body=None, source='203.0.113.5'):
    client = TestClient(app, base_url=PUBLIC_ORIGIN, client=(source, 50000))
    return client.post('/register', json=REGISTRATION if body is None else body)


def client_ids(store):
    with store.transaction() as db:
        return [r[0] for r in db.execute('SELECT client_id FROM oauth_clients ORDER BY created, rowid')]


def test_a_registration_gets_a_public_client(home):
    made = register(home.app)
    assert made.status_code == 201, made.text
    body = made.json()
    assert set(body) == {'client_id', 'client_id_issued_at', 'redirect_uris', 'grant_types', 'response_types',
                         'token_endpoint_auth_method', 'client_name'}
    assert (body['redirect_uris'], body['grant_types'], body['response_types'], body['token_endpoint_auth_method'],
            body['client_name'], body['client_id_issued_at']) == (
        [CALLBACK], ['authorization_code', 'refresh_token'], ['code'], 'none', 'Claude', int(home.clock[0]))
    assert client_ids(home.store) == [body['client_id']]


def test_only_the_configured_callback_registers(home):
    for uris in ([], [CALLBACK, CALLBACK], ['https://evil.example/callback'], [CALLBACK + '/'], CALLBACK):
        refused = register(home.app, {**REGISTRATION, 'redirect_uris': uris})
        assert (refused.status_code, refused.json()) == (400, {'error': 'invalid_redirect_uri'}), uris
    missing = {key: value for key, value in REGISTRATION.items() if key != 'redirect_uris'}
    assert register(home.app, missing).json() == {'error': 'invalid_redirect_uri'}
    assert client_ids(home.store) == []


def test_registration_bounds(home):
    """8 KB at most, a client_name of at most 100 characters, grant types within authorization_code and refresh_token,
    code responses and no client secret only. A refusal says only its error."""
    client = TestClient(home.app, base_url=PUBLIC_ORIGIN, client=PUBLIC_CLIENT)
    exact = b'{"redirect_uris": ["' + CALLBACK.encode() + b'"]'
    exact += b' ' * (8192 - len(exact) - 1) + b'}'
    assert client.post('/register', content=exact, headers={'content-type': 'application/json'}).status_code == 201
    over = client.post('/register', content=exact[:-1] + b' }', headers={'content-type': 'application/json'})
    assert (over.status_code, over.json()) == (413, {'error': 'invalid_client_metadata'})
    for bad in ({'client_name': 'x' * 101}, {'client_name': 5}, {'grant_types': ['implicit']},
                {'grant_types': 'authorization_code'}, {'grant_types': []}, {'response_types': ['token']},
                {'token_endpoint_auth_method': 'client_secret_basic'}):
        refused = register(home.app, {**REGISTRATION, **bad})
        assert (refused.status_code, refused.json()) == (400, {'error': 'invalid_client_metadata'}), bad
    for raw in (b'not json', b'[]'):
        refused = client.post('/register', content=raw, headers={'content-type': 'application/json'})
        assert (refused.status_code, refused.json()) == (400, {'error': 'invalid_client_metadata'}), raw
    assert register(home.app, {'redirect_uris': [CALLBACK]}).json()['grant_types'] == ['authorization_code']


def test_the_101st_unused_registration_evicts_the_oldest(home):
    """A flood costs the sender only their own registrations: at 100 unused, the oldest goes, never the new one."""
    first = register(home.app, source='198.51.100.0').json()['client_id']
    for n in range(1, 100):
        home.clock[0] += 1
        assert register(home.app, source=f'198.51.100.{n}').status_code == 201
    assert len(client_ids(home.store)) == 100
    home.clock[0] += 1
    assert register(home.app, source='198.51.101.1').status_code == 201
    ids = client_ids(home.store)
    assert first not in ids and len(ids) == 100


def test_the_per_source_limit(home):
    for _ in range(10):
        assert register(home.app).status_code == 201
    limited = register(home.app)
    assert (limited.status_code, limited.json()) == (429, {'error': 'slow_down'})
    assert register(home.app, source='198.51.100.9').status_code == 201  # another source isn't held
    home.clock[0] += 3601
    assert register(home.app).status_code == 201


def test_an_unused_registration_is_gone_after_24_hours(home):
    old = register(home.app).json()['client_id']
    home.clock[0] += 86400
    register(home.app, source='198.51.100.7')
    assert old in client_ids(home.store)  # not yet: a day and no more
    home.clock[0] += 1
    register(home.app, source='198.51.100.8')
    assert old not in client_ids(home.store)


@pytest.mark.parametrize('callback', ['http://claude.ai/api/mcp/auth_callback', CALLBACK + '#x', CALLBACK + '?x=1',
                                      'https://user@claude.ai/api/mcp/auth_callback', 'claude.ai/api/mcp/auth_callback'])
def test_create_app_refuses_a_callback_it_cant_match(tmp_path, callback):
    """Task 3's review, N5: the one redirect is an https URL with no query, fragment or userinfo."""
    from superyak_peer.app import create_app
    with pytest.raises(ValueError):
        create_app(tmp_path / 'peer', allowed_origins=[PUBLIC_ORIGIN], public_origin=PUBLIC_ORIGIN, connector_callback=callback)
