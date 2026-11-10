"""What a person downloads (docs/superpowers/specs/2026-11-09-what-a-person-downloads-design.md): the static files, read
once at start into one table, served from memory at /assets, gzipped for `.js` and `.css` when asked, and cacheable for
a year only at the URL naming their current hash.

Nothing is read from disk after the table is built. The live peer runs from the checkout a merge updates, so between a
merge and its restart (or after a revert) the disk holds other bytes than the ones read at start: served from disk, new
bytes would go out as immutable under an old hash. One consequence for whoever edits the app by hand: an edit to a file
under `static/` shows only after a restart."""
import functools
import gzip
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

HASH_LEN = 16
PAGES = ('index.html', 'consent.html')  # the pages whose /assets/ references are rewritten to carry each file's hash
COMPRESSED = ('.js', '.css')  # the only answers ever compressed or made immutable; never a page (BREACH, spec 4)
TYPES = {'.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
         '.html': 'text/html; charset=utf-8'}  # today's, as StaticFiles sent them; with nosniff a wrong one blocks it
IMMUTABLE = b'public, max-age=31536000, immutable'
REFERENCE = re.compile(r'(\b(?:src|href)=")/assets/([^"?#]+)(")')
QVALUE = re.compile(r'(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)\Z')  # RFC 9110's qvalue


@dataclass(frozen=True)
class Entry:
    body: bytes
    hash: str
    content_type: str
    gzipped: bytes | None  # `.js` and `.css` only


class StartError(RuntimeError):
    """The static directory can't be served as it stands: start doesn't finish."""


@functools.lru_cache(maxsize=None)
def _table(directory: str) -> dict:
    """Every file under `directory`, keyed by its exact path relative to it ('app.js'), with the two pages rewritten.
    Built once per directory per process: a build costs about 15 ms on the Pi, and the suites call create_app thousands
    of times."""
    root = Path(directory)
    raw = {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob('*')) if path.is_file()}
    table = {}
    for name, body in raw.items():
        if name not in PAGES:
            table[name] = _entry(name, body)
    for name in PAGES:
        if name in raw:
            table[name] = _entry(name, _rewritten(name, raw[name].decode('utf-8'), table).encode('utf-8'))
    return table


def _entry(name, body):
    suffix = Path(name).suffix
    return Entry(body=body, hash=hashlib.sha256(body).hexdigest()[:HASH_LEN],
                 content_type=TYPES.get(suffix, 'application/octet-stream'),
                 gzipped=gzip.compress(body, 9, mtime=0) if suffix in COMPRESSED else None)


def _rewritten(page, text, table):
    """Each src="/assets/<name>" and href="/assets/<name>" becomes /assets/<name>?v=<hash>. A page naming a file the
    table doesn't hold stops the start."""
    def versioned(match):
        name = match.group(2)
        if name not in table:
            raise StartError(f'{page} names /assets/{name}, which the static directory does not hold')
        return f'{match.group(1)}/assets/{name}?v={table[name].hash}{match.group(3)}'
    return REFERENCE.sub(versioned, text)


def table_for(directory: Path) -> dict:
    return _table(str(Path(directory).resolve()))


def key_of(scope):
    """The table key a request names: its raw_path with /assets/ taken off, exactly as sent. Starlette hands a mounted
    app the percent-decoded `path`, so only raw_path keeps `%61pp.js` apart from `app.js`. None when there is no
    raw_path, or it isn't under /assets/."""
    raw = scope.get('raw_path')
    if not isinstance(raw, bytes) or not raw.startswith(b'/assets/'):
        return None
    try:
        return raw[len(b'/assets/'):].decode('ascii')
    except UnicodeDecodeError:
        return None


def immutable(table, scope, status):
    """Spec 2: an answer may be cached for a year only when it is a GET or HEAD of an exact `.js` or `.css` key, at the
    query `v=<that file's 16 lowercase hex>` byte for byte, answered 200 or 304."""
    if scope.get('method') not in ('GET', 'HEAD') or status not in (200, 304):
        return False
    key = key_of(scope)
    entry = table.get(key) if key is not None else None
    if entry is None or entry.gzipped is None:
        return False
    return scope.get('query_string', b'') == b'v=' + entry.hash.encode('ascii')


def accepts_gzip(header):
    """Spec 4: `gzip` among the Accept-Encoding tokens, case-insensitively, with no q or a q above 0. A q that isn't an
    RFC 9110 qvalue counts as 0 and never raises."""
    for item in header.split(','):
        token, *params = [part.strip() for part in item.split(';')]
        if token.lower() != 'gzip':
            continue
        q = '1'
        for param in params:
            name, _, value = (piece.strip() for piece in param.partition('='))
            if name.lower() == 'q':
                q = value
        if QVALUE.match(q) and float(q) > 0:
            return True
    return False


class AssetApp:
    """The app mounted at /assets: exact keys from the start-time table, GET and HEAD only. A page is served whole and
    plain; a `.js` or `.css` file as gzip when the request accepts it, with Vary and an ETag per variant. Range is
    ignored. Cache-Control is the security middleware's to set (BrowserBoundary)."""

    def __init__(self, table):
        self.table = table

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return
        key = key_of(scope)
        entry = self.table.get(key) if key is not None else None
        if scope['method'] not in ('GET', 'HEAD'):
            return await self._plain(send, 405, b'Method Not Allowed', [(b'allow', b'GET, HEAD')])
        if entry is None:
            return await self._plain(send, 404, b'Not Found')
        headers = [(b'content-type', entry.content_type.encode('ascii'))]
        body = entry.body
        if entry.gzipped is not None:
            request = {name.lower(): value for name, value in scope.get('headers', ())}
            zipped = accepts_gzip(request.get(b'accept-encoding', b'').decode('latin-1'))
            etag = f'"{entry.hash}-gz"' if zipped else f'"{entry.hash}"'
            validators = [(b'etag', etag.encode('ascii')), (b'vary', b'Accept-Encoding')]
            if request.get(b'if-none-match', b'').decode('latin-1').strip() == etag:  # a whole-header compare
                await send({'type': 'http.response.start', 'status': 304, 'headers': validators})
                return await send({'type': 'http.response.body', 'body': b''})
            headers += validators
            if zipped:
                body = entry.gzipped
                headers.append((b'content-encoding', b'gzip'))
        headers.append((b'content-length', str(len(body)).encode('ascii')))
        await send({'type': 'http.response.start', 'status': 200, 'headers': headers})
        await send({'type': 'http.response.body', 'body': b'' if scope['method'] == 'HEAD' else body})

    @staticmethod
    async def _plain(send, status, text, extra=()):
        await send({'type': 'http.response.start', 'status': status,
                    'headers': [(b'content-type', b'text/plain; charset=utf-8'),
                                (b'content-length', str(len(text)).encode('ascii')), *extra]})
        await send({'type': 'http.response.body', 'body': text})
