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
                   ('POST', '/authorize/signin'), ('POST', '/authorize/decision'),
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
        # {} is no registration or sign-in, and /authorize with no client shows its page
        expected = (200 if path.startswith('/.well-known/') else
                    400 if path in ('/register', '/authorize', '/authorize/signin', '/authorize/decision') else 501)
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
    for path in ('/authorize/signin', '/authorize/decision'):
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


# ---- Task 4: registration (spec revision 4, "Registration (/register)", D18) ----

REGISTRATION = {'redirect_uris': [CALLBACK], 'client_name': 'Claude', 'grant_types': ['authorization_code', 'refresh_token'],
                'response_types': ['code'], 'token_endpoint_auth_method': 'none'}


def register(app, body=None, source='203.0.113.5'):
    client = TestClient(app, base_url=PUBLIC_ORIGIN, client=(source, 50000))
    return client.post('/register', json=REGISTRATION if body is None else body)


def raw_register(app, raw):
    client = TestClient(app, base_url=PUBLIC_ORIGIN, client=PUBLIC_CLIENT)
    return client.post('/register', content=raw, headers={'content-type': 'application/json'})


def everything(store):
    """Every table's rows: registration writes none of them."""
    with store.transaction() as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: db.execute(f'SELECT * FROM "{t}" ORDER BY 1').fetchall() for t in tables}


def test_a_registration_gets_a_public_client(home):
    made = register(home.app)
    assert made.status_code == 201, made.text
    body = made.json()
    assert set(body) == {'client_id', 'client_id_issued_at', 'redirect_uris', 'grant_types', 'response_types',
                         'token_endpoint_auth_method', 'client_name'}
    assert (body['redirect_uris'], body['grant_types'], body['response_types'], body['token_endpoint_auth_method'],
            body['client_name'], body['client_id_issued_at']) == (
        [CALLBACK], ['authorization_code', 'refresh_token'], ['code'], 'none', 'Claude', int(home.clock[0]))
    assert register(home.app, {'redirect_uris': [CALLBACK]}).json()['grant_types'] == ['authorization_code']


def test_registration_writes_nothing(home):
    """D18: /register checks and writes nothing, so there is nothing to fill, evict or sweep: the store is unchanged
    after a thousand registrations."""
    before = everything(home.store)
    for n in range(1000):
        assert register(home.app, source=f'198.51.100.{n % 250}').status_code == 201
    assert everything(home.store) == before


def test_only_the_configured_callback_registers(home):
    for uris in ([], [CALLBACK, CALLBACK], ['https://evil.example/callback'], [CALLBACK + '/'], CALLBACK,
                 [CALLBACK.replace('claude.ai', 'CLAUDE.AI')]):
        refused = register(home.app, {**REGISTRATION, 'redirect_uris': uris})
        assert (refused.status_code, refused.json()) == (400, {'error': 'invalid_redirect_uri'}), uris
    missing = {key: value for key, value in REGISTRATION.items() if key != 'redirect_uris'}
    assert register(home.app, missing).json() == {'error': 'invalid_redirect_uri'}


def test_registration_bounds(home):
    """8 KB counted in bytes; a client_name of at most 100 characters and 200 bytes, with no Cc, Cf or lone surrogate;
    grant types within authorization_code and refresh_token; code responses; no client secret. A refusal says only
    its error."""
    exact = b'{"redirect_uris": ["' + CALLBACK.encode() + b'"]'
    exact += b' ' * (8192 - len(exact) - 1) + b'}'
    assert raw_register(home.app, exact).status_code == 201
    over = raw_register(home.app, exact[:-1] + b' }')
    assert (over.status_code, over.json()) == (413, {'error': 'invalid_client_metadata'})
    wide = ('{"redirect_uris": ["' + CALLBACK + '"], "x": "' + '\u00e9' * 4096 + '"}').encode()
    assert len(wide.decode()) < 8192 < len(wide)  # under 8,192 characters, over 8,192 bytes
    assert raw_register(home.app, wide).status_code == 413
    for bad in ({'client_name': 'x' * 101}, {'client_name': '\u20ac' * 67}, {'client_name': 5},
                {'client_name': 'a\x00b'}, {'client_name': 'a\x1bb'}, {'client_name': 'a\nb'},
                {'client_name': 'Claude\u202e'}, {'client_name': 'a\u200bb'},
                {'client_name': 'a\u2028b'}, {'client_name': 'a\u2029b'},  # line breaks, so a name is one line
                {'client_name': '"' * 67 + '\U0001F600' * 33},  # 199 bytes, but 266 as the id carries it (MF1)
                {'grant_types': ['implicit']}, {'grant_types': 'authorization_code'}, {'grant_types': []},
                {'grant_types': ['refresh_token', 'refresh_token']}, {'response_types': ['token']},
                {'token_endpoint_auth_method': 'client_secret_basic'}):
        refused = register(home.app, {**REGISTRATION, **bad})
        assert (refused.status_code, refused.json()) == (400, {'error': 'invalid_client_metadata'}), bad
    surrogate = ('{"redirect_uris": ["' + CALLBACK + '"], "client_name": "a\\ud800b"}').encode()
    assert raw_register(home.app, surrogate).json() == {'error': 'invalid_client_metadata'}
    for raw in (b'not json', b'[]'):
        assert raw_register(home.app, raw).json() == {'error': 'invalid_client_metadata'}, raw
    assert register(home.app, {**REGISTRATION, 'client_name': '\u20ac' * 66}).status_code == 201  # 198 bytes
    assert register(home.app, {**REGISTRATION, 'client_name': '"' * 34 + '\U0001F600' * 33}).status_code == 201  # 200


def test_an_id_is_at_most_512_characters(home):
    """The name's 200 bytes are counted as the id carries them, after JSON escaping (Task 4's re-check, MF1), so the
    worst mixes of escapes and astral characters still make ids the 512 pre-check lets through."""
    for name in ('"' * 100, '\\' * 100, '\u20ac' * 66, 'x' * 100, '"' * 34 + '\U0001F600' * 33,
                 '\\' * 50 + '\u20ac' * 33 + 'x'):
        made = register(home.app, {**REGISTRATION, 'client_name': name})
        assert made.status_code == 201 and len(made.json()['client_id']) <= 512, (name[:3], len(made.json()['client_id']))
        assert known(home, made.json()['client_id'])['name'] == name


def known(home, client_id):
    with home.store.transaction() as db:
        return home.store.known_client(db, client_id, CALLBACK)


def test_one_ordered_check_knows_a_client(home):
    """Spec revision 4: a row with exactly this id first, else the tag (compare_digest), the version and the payload
    checked again by /register's rules. Anything else is unknown."""
    import base64
    import hashlib
    import hmac
    import json
    made = register(home.app).json()
    assert known(home, made['client_id'])['name'] == 'Claude'
    payload, tag = made['client_id'].split('.')
    flipped = payload[:-1] + ('A' if payload[-1] != 'A' else 'B')
    assert known(home, flipped + '.' + tag) is None  # a changed byte
    with home.store.transaction() as db:
        assert home.store.known_client(db, made['client_id'], CALLBACK + 'x') is None  # another callback

    def mint(body, raw=None):
        raw = raw or json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        mac = hmac.new(home.store._connector_key, b'client\n' + raw + b'\n' + CALLBACK.encode(), hashlib.sha256).digest()
        enc = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=').decode()  # noqa: E731
        return enc(raw) + '.' + enc(mac)
    good = {'v': 1, 'name': 'Claude', 'grant_types': ['authorization_code'], 'issued_at': 1}
    assert known(home, mint(good)) is not None  # an unused id from long ago still works
    assert known(home, mint({**good, 'v': 2})) is None  # an unknown version
    assert known(home, mint({**good, 'name': 'x' * 101})) is None  # a payload /register would refuse
    assert known(home, mint({**good, 'grant_types': ['implicit']})) is None
    # Task 4's re-check, S1 and S3: with the key, only the payload /register itself makes is a client
    for loose in ({**good, 'v': True}, {**good, 'v': 1.0}, {**good, 'extra': 1}, {**good, 'name': None},
                  {**good, 'issued_at': -1}, {**good, 'issued_at': '1'}, {**good, 'issued_at': 1.5}):
        assert known(home, mint(loose)) is None, loose
    assert known(home, mint(None, b'{"grant_types":["authorization_code"],"issued_at":1,"name":"x","name":"Claude","v":1}')) is None
    assert known(home, mint(None, json.dumps(good, sort_keys=True).encode())) is None  # spaces: not canonical
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
    spare = tag[:-1] + alphabet[alphabet.index(tag[-1]) ^ 1]  # the tag's last character has 2 bits to spare
    assert base64.urlsafe_b64decode(spare + '=') == base64.urlsafe_b64decode(tag + '=')
    assert known(home, payload + '.' + spare) is None  # the same bytes, encoded another way (S3, R6)
    assert known(home, 'no-dot') is None and known(home, '.') is None and known(home, '!!.!!') is None


def test_a_connected_client_survives_a_key_rotation(home):
    """Known by its row, never by its tag: rotating the key voids only unused ids (the reviewer's must-fix 1)."""
    used = register(home.app).json()['client_id']
    home.clock[0] += 1  # the same registration in the same second is the same id, which grants nothing either way
    unused = register(home.app).json()['client_id']
    assert used != unused
    with home.store.transaction() as db:
        db.execute('INSERT INTO oauth_clients VALUES(?,?,?,?)', (used, 'Claude', 'authorization_code', home.clock[0]))
    home.store._connector_key = b'\x01' * 32  # a rotation
    assert known(home, used) is not None and known(home, unused) is None


def test_the_key_is_made_once_and_kept(tmp_path):
    from superyak_peer.db import Store
    first = Store(tmp_path / 'peer')._connector_key
    assert len(first) == 32 and Store(tmp_path / 'peer')._connector_key == first


@pytest.mark.parametrize('callback', ['http://claude.ai/api/mcp/auth_callback', CALLBACK + '#x', CALLBACK + '?x=1',
                                      'https://user@claude.ai/api/mcp/auth_callback', 'claude.ai/api/mcp/auth_callback'])
def test_create_app_refuses_a_callback_it_cant_match(tmp_path, callback):
    """Task 3's review, N5: the one redirect is an https URL with no query, fragment or userinfo."""
    from superyak_peer.app import create_app
    with pytest.raises(ValueError):
        create_app(tmp_path / 'peer', allowed_origins=[PUBLIC_ORIGIN], public_origin=PUBLIC_ORIGIN, connector_callback=callback)


def test_serve_refuses_a_public_origin_without_proxy_headers(tmp_path, monkeypatch, capsys):
    """Task 4's section 2, S4: behind Funnel without --proxy-headers every sender is 127.0.0.1, so the sign-in's holds
    would be one shared bucket. serve refuses the pair at start."""
    import uvicorn
    from superyak_peer.__main__ import main
    monkeypatch.setattr(uvicorn, 'run', lambda app, **options: None)
    with pytest.raises(SystemExit) as stopped:
        main(['serve', '--data-dir', str(tmp_path / 'peer'), '--origin', PUBLIC_ORIGIN, '--public-origin', PUBLIC_ORIGIN])
    assert stopped.value.code == 1 and '--proxy-headers' in capsys.readouterr().err


# ---- Task 5: /authorize, the sign-in and the consent page (plan revision 2; spec "The authorization request") ----

CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'  # RFC 7636's S256 example challenge
RESOURCE_URL = PUBLIC_ORIGIN + '/mcp'


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


def a_page(response):
    """An error page: 400, HTML, no redirect, and nothing the request sent shown back."""
    assert response.status_code == 400 and 'location' not in response.headers, (response.status_code, response.headers)
    assert response.headers['content-type'].startswith('text/html')
    return response.text


def pending_payload(fragment):
    import base64
    import json
    encoded = fragment.split('.')[0]
    return json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))


def test_a_good_request_goes_to_the_consent_page_with_a_signed_request(home):
    """Spec r4: the validated request travels in the consent page's fragment, signed with the home's key under its own
    label, and nothing is stored."""
    import base64
    import hashlib
    import hmac
    client_id = register(home.app).json()['client_id']
    page, query, fragment = redirected(authorize(home, client_id))
    assert (page, query) == (PUBLIC_ORIGIN + '/assets/consent.html', {})
    assert pending_payload(fragment) == {'v': 1, 'client_id': client_id, 'redirect_uri': CALLBACK, 'state': 'st-1',
                                         'challenge': CHALLENGE, 'resource': RESOURCE_URL,
                                         'scope': 'rooms.read offline_access', 'at': int(home.clock[0])}
    encoded, tag = fragment.split('.')
    raw = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
    expected = hmac.new(home.store._connector_key, b'pending\n' + raw, hashlib.sha256).digest()
    assert base64.urlsafe_b64decode(tag + '=' * (-len(tag) % 4)) == expected


def test_authorize_writes_nothing(home):
    """D18: no public write before a sign-in. A thousand good requests leave every table as it was."""
    client_id = register(home.app).json()['client_id']
    before = everything(home.store)
    for n in range(1000):
        assert authorize(home, client_id, state=f's{n}').status_code == 303
    assert everything(home.store) == before


def test_a_bad_client_or_redirect_shows_a_page_and_never_redirects(home):
    client_id = register(home.app).json()['client_id']
    for override in ({'client_id': 'not-a-client'}, {'client_id': client_id + 'x'}, {'redirect_uri': None},
                     {'redirect_uri': 'https://evil.example/callback'}):
        a_page(authorize(home, client_id, **override))
    a_page(authorize(home, raw=''))  # no client at all
    shown = a_page(authorize(home, client_id, redirect_uri='https://evil.example/<script>'))
    assert 'evil.example' not in shown and '<script>' not in shown  # the page repeats nothing it was sent


def test_redirect_tricks_are_refused(home):
    client_id = register(home.app).json()['client_id']
    for uri in ('http://localhost.evil.example/callback', 'http://127.0.0.1@evil.example/', CALLBACK + '#x', CALLBACK + '/',
                CALLBACK.replace('auth_callback', 'other'), CALLBACK.replace('claude.ai', 'CLAUDE.AI'), CALLBACK + '?x=1'):
        a_page(authorize(home, client_id, redirect_uri=uri))


def test_a_repeated_parameter_is_refused(home):
    """RFC 6749 3.1: a parameter sent twice. A repeated client or redirect is a page; anything else redirects."""
    from urllib.parse import urlencode
    client_id = register(home.app).json()['client_id']
    good = {'response_type': 'code', 'client_id': client_id, 'redirect_uri': CALLBACK, 'state': 'st-1',
            'code_challenge': CHALLENGE, 'code_challenge_method': 'S256'}
    for name in ('client_id', 'redirect_uri'):
        a_page(authorize(home, raw=urlencode(good) + '&' + urlencode({name: good[name]})))
    _, query, _ = redirected(authorize(home, raw=urlencode(good) + '&scope=rooms.read&scope=offline_access'))
    assert query == {'error': 'invalid_request', 'state': 'st-1', 'iss': PUBLIC_ORIGIN}


def test_pkce_s256_is_required(home):
    client_id = register(home.app).json()['client_id']
    for override in ({'code_challenge': None}, {'code_challenge_method': 'plain'}, {'code_challenge_method': None},
                     {'code_challenge': 'too-short'}, {'code_challenge': CHALLENGE + '!'}, {'code_challenge': 'a' * 129}):
        target, query, _ = redirected(authorize(home, client_id, **override))
        assert (target, query) == (CALLBACK, {'error': 'invalid_request', 'state': 'st-1', 'iss': PUBLIC_ORIGIN}), override


def test_response_type_must_be_code(home):
    target, query, _ = redirected(authorize(home, response_type='token'))
    assert (target, query) == (CALLBACK, {'error': 'unsupported_response_type', 'state': 'st-1', 'iss': PUBLIC_ORIGIN})


def test_resource_and_scope(home):
    client_id = register(home.app).json()['client_id']
    for resource in ('https://other.example/mcp', PUBLIC_ORIGIN, PUBLIC_ORIGIN + '/mcp/', PUBLIC_ORIGIN + '/MCP',
                     'https://[', 'https://[::1'):  # one urlsplit can't parse is a target too (Task 5's S3), never a 500
        assert redirected(authorize(home, client_id, resource=resource))[1]['error'] == 'invalid_target', resource
    for resource, kept in (('HTTPS://HOME.EXAMPLE/mcp', RESOURCE_URL), (None, RESOURCE_URL)):  # MCP: case-insensitive
        page, _, fragment = redirected(authorize(home, client_id, resource=resource))
        assert page.endswith('/assets/consent.html') and pending_payload(fragment)['resource'] == kept
    for scope in ('rooms.write', 'rooms.read admin', ''):
        assert redirected(authorize(home, client_id, scope=scope))[1]['error'] == 'invalid_scope', scope
    assert pending_payload(redirected(authorize(home, client_id, scope=None))[2])['scope'] == 'rooms.read'
    assert pending_payload(redirected(authorize(home, client_id, scope='offline_access rooms.read'))[2])['scope'] == (
        'rooms.read offline_access')  # one spelling, SCOPES' order


def test_every_authorization_error_carries_iss_and_the_state_as_sent(home):
    """RFC 9207: iss on every authorization response. The state goes back as it came, and an error without one
    sends none."""
    _, query, _ = redirected(authorize(home, state='a b&c', response_type='token'))
    assert query == {'error': 'unsupported_response_type', 'state': 'a b&c', 'iss': PUBLIC_ORIGIN}
    _, query, _ = redirected(authorize(home, state=None, response_type='token'))
    assert query == {'error': 'unsupported_response_type', 'iss': PUBLIC_ORIGIN}
    _, query, _ = redirected(authorize(home, state='x' * 513))  # bounded, so the fragment is
    assert query == {'error': 'invalid_request', 'iss': PUBLIC_ORIGIN}  # and a state refused as too long isn't sent back (Tardis)
    for state in ('\x01' * 512, 'a\nb', '\u00e9', ''):  # RFC 6749 A.5: one or more VSCHAR (0x20 to 0x7E), the nit's 512 x \x01
        _, query, _ = redirected(authorize(home, state=state))
        assert query == {'error': 'invalid_request', 'iss': PUBLIC_ORIGIN}, repr(state)
    longest = '"\\' * 256  # every character JSON escapes: the largest request a good state can make
    page, _, fragment = redirected(authorize(home, state=longest))
    assert page.endswith('/assets/consent.html') and len(fragment) < 4096 and pending_payload(fragment)['state'] == longest


def test_authorize_request_is_gone(home):
    """Spec r4: the consent page's first post is the sign-in, so there is no /authorize/request."""
    assert public_client(home.app, origin=PUBLIC_ORIGIN).post('/authorize/request', json={}).status_code in (404, 405)


# ---- Task 5, the sign-in: the first row anyone on the internet can cause belongs to a person who has just typed their
# password (spec r4, D18). The request is checked, then checked again as /authorize did, before the password counts. ----

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


def mint_pending(home, body, raw=None):
    """A pending request signed with the home's own key, as anyone holding a backup could make one (Task 4's S2)."""
    import base64
    import hashlib
    import hmac
    import json
    raw = raw or json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    tag = hmac.new(home.store._connector_key, b'pending\n' + raw, hashlib.sha256).digest()
    enc = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=').decode()  # noqa: E731
    return enc(raw) + '.' + enc(tag)


def test_the_first_row_is_made_at_a_good_sign_in(home):
    sam = person(home)
    fragment = a_fragment(home)
    wrong = sign_in(home, fragment, password='not-the-password')
    assert (wrong.status_code, wrong.json()) == (401, {'error': 'invalid_login'}) and table(home, 'oauth_pending') == []
    good = sign_in(home, fragment)
    assert good.status_code == 200, good.text
    view = good.json()
    assert set(view) == {'pending', 'csrf', 'name', 'app', 'client_name', 'scope', 'rooms'}
    assert (view['name'], view['app'], view['client_name'], view['scope']) == (
        'Sam Example', 'Claude (claude.ai)', 'Claude', 'rooms.read offline_access')
    [row] = table(home, 'oauth_pending')
    request = pending_payload(fragment)
    assert {k: row[k] for k in ('client_id', 'redirect_uri', 'state', 'challenge', 'resource', 'scope', 'at')} == {
        'client_id': request['client_id'], 'redirect_uri': CALLBACK, 'state': 'st-1', 'challenge': CHALLENGE,
        'resource': RESOURCE_URL, 'scope': 'rooms.read offline_access', 'at': request['at']}
    assert (row['id'], row['person_id'], row['decided'], row['code_hash']) == (view['pending'], sam['id'], None, None)
    assert row['csrf'] != view['csrf'] and len(view['csrf']) >= 40  # kept only as a hash


def attempts(home):
    return table(home, 'login_attempts')


def test_a_forged_or_stale_request_is_refused_before_the_password(home):
    """A changed byte, a client id's tag in place of the request's (the labels differ), a request 600 s or more after
    /authorize: 400, before any password attempt counts, and no row. Mutation: the password checked first."""
    person(home)
    client_id = register(home.app).json()['client_id']
    fragment = a_fragment(home, client_id)
    encoded, tag = fragment.split('.')
    changed = encoded[:-2] + ('A' if encoded[-2] != 'A' else 'B') + encoded[-1] + '.' + tag
    for forged in (changed, client_id, fragment + 'x', 'no-dot', '', '.'.join([encoded, tag, tag])):
        refused = sign_in(home, forged, password='wrong')
        assert (refused.status_code, refused.json()) == (400, {'error': 'invalid_request'}), forged[:20]
    assert attempts(home) == [] and table(home, 'oauth_pending') == []
    home.clock[0] += 600
    stale = sign_in(home, fragment, password='wrong')
    assert (stale.status_code, stale.json()) == (400, {'error': 'request_expired'})
    assert attempts(home) == [] and table(home, 'oauth_pending') == []
    home.clock[0] -= 1
    assert sign_in(home, fragment).status_code == 200  # 599 s in, still good


def test_a_request_signed_with_the_key_is_checked_again(home):
    """Task 4's re-check, S2: the key is backed up, so a request it signs is checked again from its own values as
    /authorize did. Another redirect, an unknown client, another resource, a scope outside SCOPES, a missing field, a
    payload /authorize wouldn't make (spaces, an unknown version): 400 before the password, and no row."""
    import json
    person(home)
    good = pending_payload(a_fragment(home))
    for change in ({'redirect_uri': 'https://evil.example/callback'}, {'client_id': 'made-up'},
                   {'resource': 'https://other.example/mcp'}, {'scope': 'rooms.read rooms.write'}, {'scope': ''},
                   {'v': 2}, {'challenge': 'short'}, {'at': str(good['at'])}, {'state': 5}, {'at': good['at'] + 1},
                   {'state': 'a\x01'}):  # a request from the future, and a state /authorize wouldn't take
        refused = sign_in(home, mint_pending(home, good | change), password='wrong')
        assert (refused.status_code, refused.json()) == (400, {'error': 'invalid_request'}), change
    for raw in (json.dumps(good).encode(), json.dumps({k: v for k, v in good.items() if k != 'state'},
                                                      sort_keys=True, separators=(',', ':')).encode()):
        assert sign_in(home, mint_pending(home, None, raw), password='wrong').status_code == 400
    assert attempts(home) == [] and table(home, 'oauth_pending') == []
    assert sign_in(home, mint_pending(home, good)).status_code == 200  # the same values, signed the same way: good


def test_signing_in_again_switches_the_person(home):
    """One fragment, sam then jenn through Switch person, which sends the CSRF token the page holds: one row, jenn's,
    with a new token, and the same pending id."""
    from superyak_peer.auth import token_hash
    person(home)
    jenn = person(home, 'jenn@example.org', 'Jenn Example')
    fragment = a_fragment(home)
    first = sign_in(home, fragment).json()
    second = sign_in(home, fragment, 'jenn@example.org', csrf=first['csrf']).json()
    [row] = table(home, 'oauth_pending')
    assert (row['person_id'], row['csrf'], second['pending'], second['name']) == (
        jenn['id'], token_hash(second['csrf']), first['pending'], 'Jenn Example')
    assert second['csrf'] != first['csrf']


def test_a_signed_in_request_is_taken_over_only_with_its_csrf_token(home):
    """Task 5's section 2, S1: someone else holding the fragment (a copy made before the page cleared it) can't take a
    signed-in request over by signing in: a rebind needs the token the page holds, so it comes only from that page's
    Switch person. Without it, 403, and the request stays the first person's, their token still good."""
    sam = person(home)
    person(home, 'jenn@example.org', 'Jenn Example')
    fragment = a_fragment(home)
    sams = sign_in(home, fragment).json()
    counted = counters(home)
    for csrf in (None, 'x' * 43):
        for username, password in (('jenn@example.org', None), ('sam@example.org', None), ('jenn@example.org', 'wrong')):
            refused = sign_in(home, fragment, username, password, csrf=csrf)
            assert (refused.status_code, refused.json()) == (403, {'error': 'invalid_request'}), (username, csrf)
    assert counters(home) == counted  # refused before the password, so no attempt was counted
    [row] = table(home, 'oauth_pending')
    assert row['person_id'] == sam['id']
    assert sent_back(decide(home, sams, rooms='*'))[1]['state'] == 'st-1'  # sam's token still decides


def test_signing_in_after_a_decision_is_refused(home):
    """After a real Allow, and after a real Deny: 400, and the row keeps its person, code and grant."""
    person(home)
    for allow in (True, False):
        fragment = a_fragment(home, state=f'st-{allow}')
        view = sign_in(home, fragment).json()
        sent_back(decide(home, view, allow=allow, rooms='*'))
        before = [row for row in table(home, 'oauth_pending') if row['id'] == view['pending']]
        refused = sign_in(home, fragment, csrf=view['csrf'])
        assert (refused.status_code, refused.json()) == (400, {'error': 'already_decided'}), allow
        assert [row for row in table(home, 'oauth_pending') if row['id'] == view['pending']] == before


def test_the_sign_in_shares_login_holds_and_leaves_no_session(home):
    """The same holds as /api/login: eight wrong passwords from one source, then even the right one gets 429. A good
    sign-in makes no session and sets no cookie."""
    person(home)
    good = sign_in(home, a_fragment(home))
    assert good.status_code == 200 and 'set-cookie' not in good.headers and table(home, 'sessions') == []
    fragment = a_fragment(home, state='st-2')  # one nobody has signed in on, so each wrong password reaches the check
    for _ in range(8):
        assert sign_in(home, fragment, password='wrong').status_code == 401
    held = sign_in(home, fragment)
    assert (held.status_code, held.json()) == (429, {'error': 'too_many_attempts'})


def test_the_page_asks_for_the_password_even_with_a_session(home):
    """A session cookie changes nothing: the sign-in always needs the password, and nothing before it returns rooms."""
    person(home)
    login = consent(home).post('/api/login', json={'username': 'sam@example.org', 'password': 'long-password-sam'})
    assert login.status_code == 200
    cookie = {'cookie': f'superyak_session={login.cookies.get("superyak_session")}'}
    fragment = a_fragment(home)
    for password in ('', None):
        body = {'request': fragment, 'username': 'sam@example.org'} | ({'password': password} if password is not None else {})
        refused = consent(home, **cookie).post('/authorize/signin', json=body)
        assert refused.status_code in (400, 401) and 'rooms' not in refused.text
    assert table(home, 'oauth_pending') == []


def test_the_consent_rooms_group_earlier_parts_and_flag_marked_rooms(home):
    """Each of the person's current rooms, with its earlier parts grouped under it, and marked rooms flagged: the
    page offers none of them chosen and can't offer a marked one."""
    sam, jenn = person(home), person(home, 'jenn@example.org', 'Jenn Example')
    store = home.store
    plain = store.create_room(sam['id'], 'Plain', [])['id']
    earlier = store.create_room(sam['id'], 'Growing', [])['id']
    later = store.add_participants(sam['id'], earlier, [jenn['id']])['id']
    marked = store.create_room(sam['id'], 'Marked', [])['id']
    with store.transaction() as db:
        db.execute('INSERT INTO room_cloud VALUES(?,?,?)', (marked, sam['id'], home.clock[0]))
    rooms = sign_in(home, a_fragment(home)).json()['rooms']
    assert sorted(rooms, key=lambda room: room['room']) == sorted([
        {'room': plain, 'title': 'Plain', 'earlier_of': None, 'cloud': False},
        {'room': later, 'title': 'Growing', 'earlier_of': None, 'cloud': False},
        {'room': earlier, 'title': 'Growing', 'earlier_of': later, 'cloud': False},
        {'room': marked, 'title': 'Marked', 'earlier_of': None, 'cloud': True}], key=lambda room: room['room'])
    assert [room['room'] for room in rooms].index(earlier) == [room['room'] for room in rooms].index(later) + 1


def test_a_good_sign_in_sweeps_requests_past_their_ten_minutes(home):
    person(home)
    old = a_fragment(home)
    sign_in(home, old)
    home.clock[0] += 601
    sign_in(home, a_fragment(home), password='wrong')
    assert len(table(home, 'oauth_pending')) == 1  # a wrong password sweeps nothing
    sign_in(home, a_fragment(home))
    assert [row['at'] for row in table(home, 'oauth_pending')] == [int(home.clock[0])]


def test_the_sweep_keeps_a_request_whose_code_is_still_live(home):
    """Allowed 590 s after /authorize, its code lives to 650 s: a sweep at 601 s keeps it, one at 651 s doesn't."""
    person(home)
    view = sign_in(home, a_fragment(home)).json()
    home.clock[0] += 590
    sent_back(decide(home, view, rooms='*'))
    home.clock[0] += 11
    sign_in(home, a_fragment(home, state='st-2'))
    assert view['pending'] in [row['id'] for row in table(home, 'oauth_pending')]
    home.clock[0] += 50
    sign_in(home, a_fragment(home, state='st-3'))
    assert view['pending'] not in [row['id'] for row in table(home, 'oauth_pending')]


# ---- Task 5, the decision: Allow and Deny post the pending id with its CSRF token. Allow sends the browser to the
# stored redirect with a code, the state and iss; Deny with access_denied. Every later step uses only stored values. ----

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


def test_allow_sends_a_code_and_makes_the_grant(home):
    import json
    from superyak_peer.auth import token_hash
    sam = person(home)
    room = home.store.create_room(sam['id'], 'Care plan', [])['id']
    client, view = signed_in(home)
    target, query = sent_back(decide(home, view, rooms=[room]))
    assert (target, set(query), query['state'], query['iss']) == (CALLBACK, {'code', 'state', 'iss'}, 'st-1', PUBLIC_ORIGIN)
    [grant] = table(home, 'connector_grants')
    assert {k: grant[k] for k in ('person_id', 'client_id', 'redirect_host', 'scope', 'created', 'ends', 'revoked')} == {
        'person_id': sam['id'], 'client_id': client, 'redirect_host': 'claude.ai', 'scope': 'rooms.read offline_access',
        'created': home.clock[0], 'ends': home.clock[0] + 30 * 86400, 'revoked': None}
    assert json.loads(grant['rooms']) == [room]
    [row] = table(home, 'oauth_pending')
    assert (row['decided'], row['code_hash'], row['code_expires'], row['grant_id']) == (
        home.clock[0], token_hash(query['code']), home.clock[0] + 60, grant['id'])
    assert len(query['code']) >= 43  # 256 bits


def test_deny_redirects_with_access_denied_state_and_iss(home):
    person(home)
    _, view = signed_in(home)
    target, query = sent_back(decide(home, view, allow=False))
    assert (target, query) == (CALLBACK, {'error': 'access_denied', 'state': 'st-1', 'iss': PUBLIC_ORIGIN})
    [row] = table(home, 'oauth_pending')
    assert row['decided'] == home.clock[0] and row['code_hash'] is None
    assert table(home, 'connector_grants') == [] and table(home, 'oauth_clients') == []


def test_decisions_need_the_pending_id_and_its_csrf(home):
    """A wrong CSRF token is 403, an unknown pending id 400, and the ten minutes run from /authorize, not the sign-in."""
    person(home)
    jenn = person(home, 'jenn@example.org', 'Jenn Example')
    client = register(home.app).json()['client_id']
    fragment = a_fragment(home, client)
    sams = sign_in(home, fragment).json()
    jenns = sign_in(home, fragment, 'jenn@example.org', csrf=sams['csrf']).json()  # Switch person
    for wrong in ({'csrf': 'x' * 43}, {'csrf': sams['csrf']}):  # sam's token died when jenn signed in on that request
        refused = decide(home, jenns | wrong, rooms='*')
        assert (refused.status_code, refused.json()) == (403, {'error': 'invalid_request'}), wrong
    refused = decide(home, jenns | {'pending': 'made-up'}, rooms='*')
    assert (refused.status_code, refused.json()) == (400, {'error': 'invalid_request'})
    home.clock[0] += 600
    stale = decide(home, jenns, rooms='*')
    assert (stale.status_code, stale.json()) == (400, {'error': 'request_expired'})
    assert table(home, 'connector_grants') == [] and jenn  # nothing was issued


def test_a_second_decision_mints_no_second_code(home):
    """Review Focus: the back button after Allow, or a double click. The second decision gets 400 and mints nothing."""
    person(home)
    _, view = signed_in(home)
    sent_back(decide(home, view, rooms='*'))
    for allow in (True, False):
        again = decide(home, view, allow=allow, rooms='*')
        assert (again.status_code, again.json()) == (400, {'error': 'already_decided'}), allow
    assert len(table(home, 'connector_grants')) == 1 and len({row['code_hash'] for row in table(home, 'oauth_pending')}) == 1


def test_nothing_is_chosen_by_default_and_marked_rooms_cant_be_chosen(home):
    sam, jenn = person(home), person(home, 'jenn@example.org', 'Jenn Example')
    store = home.store
    mine = store.create_room(sam['id'], 'Mine', [])['id']
    earlier = store.create_room(sam['id'], 'Growing', [])['id']
    store.add_participants(sam['id'], earlier, [jenn['id']])
    marked = store.create_room(sam['id'], 'Marked', [])['id']
    theirs = store.create_room(jenn['id'], 'Theirs', [])['id']
    with store.transaction() as db:
        db.execute('INSERT INTO room_cloud VALUES(?,?,?)', (marked, sam['id'], home.clock[0]))
    for n, rooms in enumerate(([], None, [marked], [earlier], [theirs], [mine, mine], ['*'], 'all', [5], {'room': mine})):
        _, view = signed_in(home, state=f'st-{n}')  # a request of its own each time
        body = {'pending': view['pending'], 'csrf': view['csrf'], 'allow': True} | ({} if rooms is None else {'rooms': rooms})
        refused = consent(home).post('/authorize/decision', json=body)
        assert (refused.status_code, refused.json()) == (400, {'error': 'invalid_request'}), rooms
    assert table(home, 'connector_grants') == []
    _, view = signed_in(home, state='st-all')
    sent_back(decide(home, view, rooms='*'))  # "All my rooms, including new ones" only when sent as itself
    assert [grant['rooms'] for grant in table(home, 'connector_grants')] == ['*']


def test_days_are_1_to_30(home):
    person(home)
    for n, days in enumerate((0, 31, -1, '30', True, 1.5, None)):
        _, view = signed_in(home, state=f'st-{n}')
        refused = decide(home, view, rooms='*', days=days)
        assert (refused.status_code, refused.json()) == (400, {'error': 'invalid_request'}), days
    _, view = signed_in(home, state='st-one-day')
    sent_back(decide(home, view, rooms='*', days=1))
    assert [grant['ends'] for grant in table(home, 'connector_grants')] == [home.clock[0] + 86400]


def test_the_first_allow_writes_the_clients_row(home):
    """D18: a client is known by its row once a code has been issued to it, so a key rotation disconnects no one."""
    person(home)
    client, view = signed_in(home)
    assert table(home, 'oauth_clients') == []
    sent_back(decide(home, view, rooms='*'))
    assert [(row['client_id'], row['name'], row['grant_types']) for row in table(home, 'oauth_clients')] == [
        (client, 'Claude', 'authorization_code refresh_token')]
    _, view = signed_in(home, client, state='st-2')  # the same request again would be the same fragment, decided
    sent_back(decide(home, view, rooms='*'))  # a second connection from the same client
    assert len(table(home, 'oauth_clients')) == 1


# ---- Task 5's section 2, S2 and S4: the code goes only to the configured callback, and the sign-in is counted and laned
# exactly as /api/login is ----

def test_the_decision_sends_a_code_only_to_the_configured_callback(home):
    """S2: a request signed in under one --connector-callback isn't allowed under another; nothing is minted."""
    import pytest as _pytest
    from superyak_peer.connector import OAuthError
    person(home)
    _, view = signed_in(home)
    with _pytest.raises(OAuthError) as refused:
        home.store.pending_decide(view['pending'], view['csrf'], True, '*', issuer=PUBLIC_ORIGIN,
                                  callback='https://other.example/callback')
    assert (refused.value.status, refused.value.error) == (400, 'invalid_request')
    assert table(home, 'connector_grants') == [] and [row['decided'] for row in table(home, 'oauth_pending')] == [None]


def counters(home):
    return sorted((row['key'], row['count']) for row in table(home, 'login_attempts'))


@pytest.mark.parametrize('where', ['public', 'tailnet'])
def test_a_wrong_password_is_counted_as_api_login_counts_it(home, where):
    """S4: the same login_attempts rows as one wrong /api/login from the same place, public or tailnet."""
    person(home)
    client = consent(home) if where == 'public' else TestClient(home.app, base_url=PUBLIC_ORIGIN,
                                                                 headers={'origin': PUBLIC_ORIGIN})
    fragment = a_fragment(home)
    assert client.post('/api/login', json={'username': 'sam@example.org', 'password': 'wrong'}).status_code == 401
    by_login = counters(home)
    with home.store.transaction() as db:
        db.execute('DELETE FROM login_attempts')
    assert client.post('/authorize/signin', json={'request': fragment, 'username': 'sam@example.org',
                                                  'password': 'wrong'}).status_code == 401
    assert counters(home) == by_login and any(f'"{where}"' in key for key, _ in by_login)  # keys name their kind


def test_a_known_browser_counts_on_its_own_token_as_api_login_does(home):
    """S4: a browser with a valid superyak_device cookie: a wrong sign-in changes its token's failures and every
    counter exactly as one wrong /api/login from that browser does."""
    from collections import Counter
    person(home)
    browser = consent(home)
    assert browser.post('/api/login', json={'username': 'sam@example.org', 'password': 'long-password-sam'}).status_code == 200
    failures = lambda: [row['failures'] for row in table(home, 'login_devices')]  # noqa: E731
    fragment = a_fragment(home)
    start = Counter(dict(counters(home)))
    browser.post('/api/login', json={'username': 'sam@example.org', 'password': 'wrong'})
    after_login = Counter(dict(counters(home)))
    assert failures() == [1]
    browser.post('/authorize/signin', json={'request': fragment, 'username': 'sam@example.org', 'password': 'wrong'})
    after_sign_in = Counter(dict(counters(home)))
    assert failures() == [2]
    assert after_sign_in - after_login == after_login - start and after_login - start  # the same counters moved


def test_the_sign_in_waits_in_the_lane_api_login_uses(home, monkeypatch):
    """S4: a public sign-in runs in the public lane, a tailnet one in the tailnet lane; a forged request takes none."""
    person(home)
    lanes, used = home.app.state.sign_in_lanes, []
    for name in ('public', 'tailnet', 'known'):
        lane = getattr(lanes, name)
        monkeypatch.setattr(lane, 'run', lambda call, *args, real=lane.run, name=name, **kwargs: (
            used.append((name, call.__name__)), real(call, *args, **kwargs))[1])
    sign_in(home, a_fragment(home), password='wrong')
    TestClient(home.app, base_url=PUBLIC_ORIGIN, headers={'origin': PUBLIC_ORIGIN}).post(
        '/authorize/signin', json={'request': a_fragment(home, state='st-2'), 'username': 'sam@example.org',
                                   'password': 'wrong'})
    sign_in(home, 'forged.request', password='wrong')
    assert used == [('public', 'pending_sign_in'), ('tailnet', 'pending_sign_in')]
