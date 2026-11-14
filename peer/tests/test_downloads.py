"""What a person downloads (docs/superpowers/specs/2026-11-09-what-a-person-downloads-design.md): one start-time table of
the static files, served from memory at /assets by exact raw_path; a year's caching only for a `.js` or `.css` file at
its current hash; gzip only for those; and the security headers on every answer the app gives, refusals included."""
import asyncio
import gzip
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from superyak_peer.app import STATIC_DIR, BrowserBoundary, create_app
from superyak_peer.static_assets import IMMUTABLE, PAGES, StartError, accepts_gzip, table_for

SECURITY = {b'x-content-type-options': b'nosniff', b'referrer-policy': b'no-referrer',
            b'content-security-policy': b"default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"}


@pytest.fixture
def static(tmp_path):
    """A copy of the static directory: no test writes under the package the live peer serves."""
    copy = tmp_path / 'static'
    shutil.copytree(STATIC_DIR, copy)
    return copy


@pytest.fixture
def app(tmp_path, static):
    return create_app(tmp_path / 'peer', allowed_origins=['http://testserver'], static_dir=static)


def call(app, raw_path, *, method='GET', query=b'', headers=(), client=('127.0.0.1', 50000), host=b'testserver'):
    """One request through the whole app, with the raw_path a server would give it (TestClient's URL handling would
    normalize some of these paths first). Returns (status, headers as a list of lowercase pairs, the raw body)."""
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': 'http',
             'path': unquote(raw_path.decode('latin-1')), 'raw_path': raw_path, 'query_string': query,
             'root_path': '', 'headers': [(b'host', host), *headers], 'client': client, 'server': ('testserver', 80)}
    messages = []

    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = messages[0]
    return (start['status'], [(name.lower(), value) for name, value in start['headers']],
            b''.join(m.get('body', b'') for m in messages[1:]))


def header(headers, name):
    values = [value for key, value in headers if key == name]
    return values[0] if len(values) == 1 else values or None


def cache_controls(headers):
    return [value for key, value in headers if key == b'cache-control']


def current(app, name):
    return app.state.assets[name]


# 1. The table.

def test_a_file_overwritten_after_start_changes_no_response(app, static):
    before = call(app, b'/assets/app.js')
    (static / 'app.js').write_text('overwritten();')
    (static / 'index.html').write_text('<p>overwritten</p>')
    assert call(app, b'/assets/app.js') == before
    assert TestClient(app).get('/').text == current(app, 'index.html').body.decode()


def test_start_refuses_a_page_that_names_a_missing_file(tmp_path, static):
    (static / 'index.html').write_text('<script src="/assets/missing.js" defer></script>')
    with pytest.raises(StartError, match='missing.js'):
        create_app(tmp_path / 'peer', allowed_origins=['http://testserver'], static_dir=static)


@pytest.mark.parametrize('raw', [b'/assets/x/../app.js', b'/assets//app.js', b'/assets/%61pp.js', b'/assets/./app.js',
                                 b'/assets/APP.JS', b'/assets/app.js/'])
def test_only_an_exact_key_is_served(app, raw):
    assert call(app, b'/assets/app.js')[0] == 200
    status, headers, _ = call(app, raw)
    assert status == 404 and cache_controls(headers) == [b'no-store']


def test_only_the_files_the_app_ships_are_in_the_table(tmp_path, static):
    """A link to a file outside the directory, an editor's leftovers and a type TYPES doesn't name are never read or
    served; the files the app ships are unchanged."""
    outside = tmp_path / 'outside.txt'
    outside.write_text('not for the internet')
    (static / 'leak.js').symlink_to(outside)
    (static / 'leak.txt').symlink_to(outside)
    (static / '.app.js.swp').write_text('swap')
    (static / '.hidden.js').write_text('hidden()')
    (static / 'app.js~').write_text('backup')
    (static / 'notes.txt').write_text('notes')
    (static / 'module.mjs').write_text('export {}')
    (static / '.inner-secret').write_text('not for the internet')
    (static / 'todot.js').symlink_to(static / '.inner-secret')  # a shipped name, pointing at an excluded file
    (static / 'alias.js').symlink_to(static / 'app.js')  # even to a shipped file: the app ships no link
    (tmp_path / 'linked').mkdir()
    (tmp_path / 'linked' / 'secret.js').write_text('not for the internet')
    (static / 'linkdir').symlink_to(tmp_path / 'linked', target_is_directory=True)
    app = create_app(tmp_path / 'peer', allowed_origins=['http://testserver'], static_dir=static)
    for name in ('leak.js', 'leak.txt', '.app.js.swp', '.hidden.js', 'app.js~', 'notes.txt', 'module.mjs',
                 'todot.js', 'alias.js', 'linkdir/secret.js', '.inner-secret'):
        assert name not in app.state.assets
        for client in (('127.0.0.1', 50000), ('203.0.113.5', 1)):
            status, _, body = call(app, f'/assets/{name}'.encode(), client=client)
            assert status == 404 and b'not for the internet' not in body, (name, client)
    assert sorted(app.state.assets) == sorted(path.name for path in STATIC_DIR.iterdir() if path.is_file())


def test_the_table_is_read_only_and_its_gzip_the_same_at_every_start(app, static):
    with pytest.raises(TypeError):
        app.state.assets['x.js'] = None
    assert all(entry.gzipped[4:8] == b'\0\0\0\0' for entry in app.state.assets.values() if entry.gzipped)  # mtime 0
    assert issubclass(StartError, ValueError)  # serve's one-line refusal, as for every other start check


def test_a_request_with_no_raw_path_is_a_404(app):
    from superyak_peer.static_assets import AssetApp
    sent = []

    async def send(message):
        sent.append(message)

    asyncio.run(AssetApp(app.state.assets)({'type': 'http', 'method': 'GET', 'path': '/assets/app.js', 'headers': []},
                                           None, send))
    assert sent[0]['status'] == 404


# 2. References.

def test_each_page_names_its_assets_at_their_current_hash(app):
    for name, route in (('index.html', '/'), ('consent.html', '/assets/consent.html')):
        text = call(app, route.encode())[2].decode()
        named = re.findall(r'(?:src|href)="/assets/([^"?]+)\?v=([0-9a-f]{16})"', text)
        assert named and all(current(app, asset).hash == hash_ for asset, hash_ in named)
        assert not re.search(r'(?:src|href)="/assets/[^"?]+"', text)  # none left without its hash


def test_no_static_file_but_the_pages_names_another(static):
    """An import, a url() or a Worker naming another file would fetch it at no hash, unseen by the table's rewrite: a
    name after a quote, a slash or url( is such a reference. A comment that mentions one, "(app.css)", is not."""
    files = [path for path in static.iterdir() if path.is_file()]
    for path in files:
        if path.name in PAGES:
            continue
        text = path.read_text(errors='replace')
        for other in files:
            if other != path:
                assert not re.search(r'(?:["\'`/]|url\(\s*)' + re.escape(other.name), text), (path.name, other.name)


def test_the_content_types_are_todays(app):
    types = {name: entry.content_type for name, entry in app.state.assets.items()}
    assert types['app.js'] == types['dashboard.js'] == 'text/javascript; charset=utf-8'
    assert types['app.css'] == 'text/css; charset=utf-8' and types['index.html'] == 'text/html; charset=utf-8'
    status, headers, _ = call(app, b'/assets/app.js')
    assert header(headers, b'content-type') == b'text/javascript; charset=utf-8'


# 3. Caching.

def test_the_current_hash_is_cached_for_a_year_with_the_start_time_bytes(app, static):
    entry = current(app, 'app.js')
    status, headers, body = call(app, b'/assets/app.js', query=b'v=' + entry.hash.encode())
    assert status == 200 and body == (STATIC_DIR / 'app.js').read_bytes() == entry.body
    assert cache_controls(headers) == [IMMUTABLE]
    assert all(header(headers, name) == value for name, value in SECURITY.items())
    assert header(headers, b'set-cookie') is None


def test_everything_else_is_no_store_exactly_once(app):
    js = current(app, 'app.js').hash.encode()
    cases = [(b'/assets/app.js', b'v=' + b'0' * 16), (b'/assets/app.js', b''), (b'/assets/app.js', b'v=' + js.upper()),
             (b'/assets/app.js', b'v=' + js + b'&x=1'), (b'/assets/app.js', b'v=' + js + b'&v=' + js),
             (b'/assets/app.js', b'x=1&v=' + js), (b'/assets/index.html', b'v=' + current(app, 'index.html').hash.encode()),
             (b'/', b''), (b'/public/', b''), (b'/assets/consent.html', b''), (b'/assets/nothing.js', b'v=' + js),
             (b'/api/health', b''), (b'/api/me', b'')]
    for raw, query in cases:
        status, headers, _ = call(app, raw, query=query)
        assert cache_controls(headers) == [b'no-store'], (raw, query, status)


def test_a_post_to_a_current_hash_is_not_cached(app):
    js = current(app, 'app.js').hash.encode()
    status, headers, _ = call(app, b'/assets/app.js', method='POST', query=b'v=' + js,
                              headers=[(b'origin', b'http://testserver')])
    assert status == 405 and cache_controls(headers) == [b'no-store']


def _behind_the_boundary(static, status, headers, method='GET'):
    """The cache-control BrowserBoundary gives an inner app's answer at app.js's current-hash URL."""
    assets = table_for(static)

    async def inner(scope, receive, send):
        await send({'type': 'http.response.start', 'status': status, 'headers': list(headers)})
        await send({'type': 'http.response.body', 'body': b''})

    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    scope = {'type': 'http', 'method': method, 'scheme': 'http', 'path': '/assets/app.js', 'raw_path': b'/assets/app.js',
             'query_string': b'v=' + assets['app.js'].hash.encode(),
             'headers': [(b'host', b'testserver'), (b'origin', b'http://testserver')]}
    asyncio.run(BrowserBoundary(inner, router=None, allowed_origins=['http://testserver'], assets=assets)(
        scope, receive, send))
    return [v for k, v in sent[0]['headers'] if k == b'cache-control']


def test_only_a_200_or_304_without_a_cookie_is_cached_at_a_current_hash(static):
    """Whatever answers a current-hash URL: an error is never storable for a year (RFC 9111), nor a Set-Cookie."""
    assert _behind_the_boundary(static, 200, []) == [IMMUTABLE] == _behind_the_boundary(static, 304, [])
    for status in (404, 405, 500, 503, 206):
        assert _behind_the_boundary(static, status, []) == [b'no-store'], status
    assert _behind_the_boundary(static, 200, [(b'set-cookie', b'a=b')]) == [b'no-store']
    assert _behind_the_boundary(static, 200, [], method='HEAD') == [IMMUTABLE]
    for method in ('POST', 'PUT', 'DELETE'):  # whatever answers it, a write is never cached
        assert _behind_the_boundary(static, 200, [], method=method) == [b'no-store'], method


def test_the_table_is_built_once_per_directory(static, tmp_path):
    """A build costs about 15 ms on the Pi, and the suites call create_app thousands of times."""
    assert table_for(static) is table_for(static) is table_for(tmp_path / 'static' / '.' )


# Section 3: the security headers on every answer, refusals included.

def test_the_boundarys_refusals_and_a_500_carry_the_security_headers(tmp_path, static):
    app = create_app(tmp_path / 'peer', allowed_origins=['http://testserver'], static_dir=static)

    @app.get('/api/boom')
    def boom():
        raise RuntimeError('boom')

    client = TestClient(app, raise_server_exceptions=False)
    answers = {'unknown host': client.get('/api/health', headers={'host': 'elsewhere.example'}),
               'no origin': client.post('/api/login', json={}),
               'too large': client.post('/api/inbox', content=b'x' * (6 * 1024 * 1024 + 10),
                                        headers={'origin': 'http://testserver'}),
               'a 500': client.get('/api/boom')}
    assert [answer.status_code for answer in answers.values()] == [403, 403, 413, 500]
    for name, answer in answers.items():
        for key, value in SECURITY.items():
            assert answer.headers.get(key.decode()) == value.decode(), (name, key)
        assert answer.headers.get_list('cache-control') == ['no-store'], name


# 4. Compression.

@pytest.mark.parametrize('name', ['app.js', 'app.css', 'consent.js'])
def test_a_js_or_css_asset_comes_gzipped_when_asked(app, name):
    entry = current(app, name)
    status, headers, body = call(app, f'/assets/{name}'.encode(), headers=[(b'accept-encoding', b'gzip, br')])
    assert status == 200 and header(headers, b'content-encoding') == b'gzip'
    assert gzip.decompress(body) == entry.body and body == entry.gzipped
    assert header(headers, b'content-length') == str(len(body)).encode()
    assert header(headers, b'vary') == b'Accept-Encoding' and header(headers, b'etag') == f'"{entry.hash}-gz"'.encode()


@pytest.mark.parametrize('accept', [None, b'gzip;q=0', b'gzip;q=abc', b'GZIP ; Q=0', b'gzip;q=1.5', b'br, deflate',
                                    b'identity'])
def test_otherwise_the_plain_bytes(app, accept):
    entry = current(app, 'app.js')
    status, headers, body = call(app, b'/assets/app.js', headers=[(b'accept-encoding', accept)] if accept else [])
    assert status == 200 and body == entry.body and header(headers, b'content-encoding') is None
    assert header(headers, b'etag') == f'"{entry.hash}"'.encode() and header(headers, b'vary') == b'Accept-Encoding'


@pytest.mark.parametrize('value, chosen', [('gzip', True), ('GZIP', True), ('gzip; q=0.5', True), ('gzip;Q=1', True),
                                           ('deflate, gzip;q=0.001', True), ('gzip;q=0', False), ('gzip;q=0.000', False),
                                           ('gzip;q=abc', False), ('gzip;q=', False), ('gzip;q=2', False), ('', False),
                                           ('x-gzip', False), ('gzip;q=0.5000', False)])
def test_accept_encoding_is_read_as_tokens_and_never_raises(value, chosen):
    assert accepts_gzip(value) is chosen


@pytest.mark.parametrize('raw', [b'/', b'/public/', b'/assets/index.html', b'/assets/consent.html', b'/api/health',
                                 b'/api/me', b'/assets/nothing.js', b'/public/layers/nothing', b'/authorize'])
def test_nothing_else_is_ever_compressed(app, raw):
    status, headers, _ = call(app, raw, headers=[(b'accept-encoding', b'gzip, deflate, br')])
    assert header(headers, b'content-encoding') is None, (raw, status)


# Conditional requests, ranges, HEAD.

def test_if_none_match_is_compared_with_the_chosen_variant(app):
    entry = current(app, 'app.js')
    query = b'v=' + entry.hash.encode()
    gz = [(b'accept-encoding', b'gzip')]
    status, headers, body = call(app, b'/assets/app.js', query=query,
                                 headers=[*gz, (b'if-none-match', f'"{entry.hash}-gz"'.encode())])
    assert (status, body) == (304, b'')
    assert header(headers, b'etag') == f'"{entry.hash}-gz"'.encode() and header(headers, b'vary') == b'Accept-Encoding'
    assert cache_controls(headers) == [IMMUTABLE]  # the same cache-control the 200 would carry
    for other in (f'"{entry.hash}"', f'W/"{entry.hash}-gz"', f'"{entry.hash}-gz", "x"', '*'):
        assert call(app, b'/assets/app.js', query=query, headers=[*gz, (b'if-none-match', other.encode())])[0] == 200
    plain = call(app, b'/assets/app.js', headers=[(b'if-none-match', f'"{entry.hash}"'.encode())])
    assert plain[0] == 304 and cache_controls(plain[1]) == [b'no-store']  # no v: revalidated, never cached


def test_a_range_gets_the_whole_file_and_head_gets_no_body(app):
    entry = current(app, 'app.js')
    status, headers, body = call(app, b'/assets/app.js', headers=[(b'range', b'bytes=0-9')])
    assert status == 200 and body == entry.body and header(headers, b'accept-ranges') is None
    for accept, size in ((b'gzip', len(entry.gzipped)), (b'identity', len(entry.body))):
        status, headers, body = call(app, b'/assets/app.js', method='HEAD', headers=[(b'accept-encoding', accept)])
        assert (status, body) == (200, b'') and header(headers, b'content-length') == str(size).encode()


# Public requests.

def test_a_public_request_gets_the_same_assets_and_headers(app):
    entry = current(app, 'app.js')
    query = b'v=' + entry.hash.encode()
    tailnet = call(app, b'/assets/app.js', query=query, headers=[(b'accept-encoding', b'gzip')])
    public = call(app, b'/assets/app.js', query=query, headers=[(b'accept-encoding', b'gzip')], client=('203.0.113.5', 1))
    assert public == tailnet
    status, headers, _ = call(app, b'/api/me', client=('203.0.113.5', 1))
    assert status == 401 and cache_controls(headers) == [b'no-store']
    assert call(app, b'/assets/nothing.js', client=('203.0.113.5', 1))[0] == 404
