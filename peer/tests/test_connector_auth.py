"""The remote connector's configuration, discovery and boundary (plan 2026-10-28-remote-connector, Task 3; spec
"Where it lives", "The home is its own authorization server")."""
import pytest
from fastapi.testclient import TestClient
from connector_support import CALLBACK, PUBLIC_ORIGIN, home, public_client  # noqa: F401

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
    for method, path in CONNECTOR_PATHS:
        assert client.request(method, path).status_code in (404, 405), (method, path)
    assert getattr(app.state, 'public_origin', None) is None


def test_every_connector_route_answers_a_public_request(home):
    """Each is on PublicRoute's allow-list, so a public request with no session reaches its handler: the discovery
    documents answer, and the routes later tasks build answer 501 until then, never the middleware's refusal."""
    client = public_client(home.app, origin=PUBLIC_ORIGIN)
    for method, path in CONNECTOR_PATHS:
        response = client.request(method, path, json={} if method == 'POST' else None)
        expected = 200 if path.startswith('/.well-known/') else 501
        assert response.status_code == expected, (method, path, response.status_code, response.text)


def test_register_token_and_mcp_pass_the_boundary_without_an_origin(home):
    client = public_client(home.app)
    for path in ('/register', '/token', '/mcp'):
        response = client.post(path)
        assert response.status_code != 403, (path, response.text)  # never 'Same-origin request required'


def test_the_consent_posts_still_need_the_homes_origin(home):
    for path in ('/authorize/request', '/authorize/signin', '/authorize/decision'):
        response = public_client(home.app).post(path, json={})
        assert (response.status_code, response.json()) == (403, {'error': 'Same-origin request required'}), path


def test_no_connector_route_sends_cors_headers(home):
    client = public_client(home.app, origin='https://claude.ai')
    for method, path in CONNECTOR_PATHS:
        response = client.request(method, path)
        assert not [name for name in response.headers if name.lower().startswith('access-control-')], (method, path)


@pytest.mark.parametrize('origins, public', [
    (['http://testserver'], 'https://home.example'),          # not one of the origins
    (['http://home.example'], 'http://home.example'),          # not https
    (['https://home.example/x'], 'https://home.example/x'),    # a path
    (['https://Home.example'], 'https://Home.example'),         # not lowercase
])
def test_create_app_refuses_a_public_origin_it_cant_be(tmp_path, origins, public):
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
