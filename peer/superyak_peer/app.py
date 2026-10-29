"""Same-origin browser API; additional peer routers attach to this factory."""
import asyncio
import functools
import hmac
import re
import ipaddress
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
import anyio
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.routing import Match, Mount
from starlette.websockets import WebSocketClose
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from .agent_version import agent_update
from .auth import DEVICE_LIFETIME
from .common import Problem, valid_utf8
from .db import Store
from .inbox import breakout_filter, wait_seconds, with_earlier_noise
from .presence import parse_presence

MAX_REQUEST = 6 * 1024 * 1024
MAX_IMPRINT_REQUEST = 64 * 1024  # I 14: the largest request body
COOKIE = 'superyak_session'
DEVICE_COOKIE = 'superyak_device'  # public route spec 3: the known-device cookie, kept at logout
DEFAULT_ORIGINS = ('http://127.0.0.1:7435', 'http://localhost:7435')
STATIC_DIR = Path(__file__).with_name('static')
# Public route spec 1: loopback and these tailnet ranges are tailnet; every other client is public. `serve` trusts
# forwarded headers from TRUSTED_PROXY only (tailscale serve), so an internet client can't pass as a tailnet address.
TAILNET = (ipaddress.ip_network('100.64.0.0/10'), ipaddress.ip_network('fd7a:115c:a1e0::/48'))
TRUSTED_PROXY = '127.0.0.1'
SECURITY_HEADERS = [
    (b'x-content-type-options', b'nosniff'),
    (b'cache-control', b'no-store'),
    (b'content-security-policy', b"default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
    (b'referrer-policy', b'no-referrer'),
]
# Public route spec 2: what a public request reaches with no valid session or ship key, named by the template of the
# route object the router dispatches it to, never by path prefix: the app shell and its assets, health, the login,
# an invitation link and the layers their owners published. A route added later starts closed.
PUBLIC_ROUTES = {
    '/': {'GET', 'HEAD'}, '/public/': {'GET', 'HEAD'}, '/assets': {'GET', 'HEAD'}, '/api/health': {'GET'},
    '/api/login': {'POST'}, '/api/invitations/redeem': {'POST'},
    '/public/layers/{key}': {'GET'}, '/public/layers/{layer_id}/files/{key}': {'GET'},
}


def is_public(scope):
    """Public route spec 1: a Funnel request (the Tailscale-Funnel-Request header with any value: Tailscale sets it
    and strips it from what clients send, so a forged one only restricts), a client that isn't an IP address (or no
    client), or a client neither loopback nor on the tailnet. scope['client'] is what uvicorn's ProxyHeadersMiddleware
    left there. A request from 127.0.0.1 with no forwarded header is tailnet: a local process, trusted by design."""
    if any(name.lower() == b'tailscale-funnel-request' for name, _ in scope.get('headers', ())):
        return True
    try:
        address = ipaddress.ip_address(scope['client'][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return True
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    return not (address.is_loopback or any(address in network for network in TAILNET))

class BrowserBoundary:
    """Bound input before JSON parsing; check origins for browser writes."""
    def __init__(self, app, *, allowed_origins=()):
        self.app, self.allowed_origins = app, set(allowed_origins)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in scope['headers']}
        request_origin = scope['scheme'] + '://' + headers.get('host', '')
        if self.allowed_origins and request_origin not in self.allowed_origins:
            return await JSONResponse({'error': 'Unrecognized host'}, 403)(scope, receive, send)
        origin = headers.get('origin')
        method = scope['method']
        # Federation endpoints use separate cryptographic auth; their router must
        # verify signed envelopes and never accept browser session authority.
        browser_write = method not in ('GET', 'HEAD', 'OPTIONS') and not scope['path'].startswith('/federation/')
        if browser_write:
            if not origin or origin != request_origin:
                return await JSONResponse({'error': 'Same-origin request required'}, 403)(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > MAX_REQUEST:
                return await JSONResponse({'error': 'Request too large'}, 413)(scope, receive, send)
            if not message.get('more_body', False):
                break
        sent = False
        async def bounded_receive():
            nonlocal sent
            if not sent:
                sent = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        async def secure_send(message):
            if message['type'] == 'http.response.start':
                message.setdefault('headers', []).extend(SECURITY_HEADERS)
            await send(message)
        await self.app(scope, bounded_receive, secure_send)

class PublicRoute:
    """Public route spec 2: default deny for public (Funnel) requests. Outermost, so it runs before the body is read.
    A public request passes to an allow-listed route, or with a valid session or ship key (checked, not just present;
    the route's own check still decides). Anything else gets 401 under /api/, which app.js acts on, and 404 elsewhere.
    Tailnet requests pass untouched."""
    def __init__(self, app, *, store, router):
        self.app, self.store, self.router = app, store, router

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        try:  # only the classification and the lookup: 401 would tell the dock client its key was revoked
            refusal = await self.refusal(scope)
        except Exception as error:  # noqa: BLE001
            logging.getLogger(__name__).warning('Public route check failed: %s', type(error).__name__)
            refusal = (503, 'Try again shortly')
        if refusal is None:
            return await self.app(scope, receive, send)  # outside the guard: route errors reach the 500 handler
        if scope['type'] == 'websocket':
            return await WebSocketClose()(scope, receive, send)
        response = JSONResponse({'error': refusal[1]}, refusal[0])
        response.raw_headers.extend(SECURITY_HEADERS)
        await response(scope, receive, send)

    async def refusal(self, scope):
        """None lets the request through; otherwise the (status, message) that refuses it."""
        if not is_public(scope):
            return None
        if scope['type'] == 'websocket':
            return (403, 'No route takes a public websocket')  # none exists; __call__ closes the socket
        if self.allowed(scope):  # before any lookup: a browser sends its session cookie with every asset
            return None
        request = Request(scope)  # Starlette's cookie parser and bearer_key, so this sees what the route will
        key, token = bearer_key(request), request.cookies.get(COOKIE)
        if (key is not None or token is not None) and await run_in_threadpool(self.valid, key, token):
            return None
        return (401, 'Sign in required') if scope['path'].startswith('/api/') else (404, 'Not found')

    def valid(self, key, token):
        """In a worker, as the inbox wait's store calls are: the store gate is a blocking flock."""
        return bool(key is not None and self.store.ship_key_is_valid(key)
                    or token is not None and self.store.session_is_valid(token))

    def allowed(self, scope):
        """Whether the route the router dispatches this request to is on the allow-list, for this method. The router
        (FastAPI's APIRouter.app) takes the first full match, else the first partial one (a 405)."""
        probe, partial = dict(scope), None  # a router's matches() may note itself in the scope it is given
        for route in self.router.routes:
            match, _ = route.matches(probe)
            if match == Match.FULL:
                return self.listed(route, scope['method'])
            if match == Match.PARTIAL and partial is None:
                partial = route
        return partial is not None and self.listed(partial, scope['method'])

    @staticmethod
    def listed(route, method):
        return isinstance(route, (APIRoute, Mount)) and method in PUBLIC_ROUTES.get(route.path, ())

class SignInLane:
    """Public route spec 3: all of Store.login runs in a worker under its lane's own limiter, so sign-ins never compete
    with sync routes for anyio's shared threads. `size` sign-ins at a time with `queue` waiting; a full lane answers
    429 without hashing or counting."""
    def __init__(self, size, queue):
        self.size, self.queue, self.inside = size, queue, 0
        self.limiter = anyio.CapacityLimiter(size)

    async def run(self, call, *args, **kwargs):
        if self.inside >= self.size + self.queue:
            raise Problem(429, 'Too many sign-ins at once; try again shortly')
        self.inside += 1  # only the event loop changes it
        try:
            return await anyio.to_thread.run_sync(functools.partial(call, *args, **kwargs), limiter=self.limiter)
        finally:
            self.inside -= 1

async def body(request):
    try:
        value = await request.json()
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise Problem(400, 'Invalid JSON') from None
    if not isinstance(value, dict):
        raise Problem(400, 'Expected a JSON object')
    try:
        return valid_utf8(value)
    except RecursionError:
        raise Problem(400, 'JSON is too deeply nested') from None

def bearer_key(request):
    scheme, _, value = request.headers.get('authorization', '').partition(' ')
    return value.strip() if scheme.lower() == 'bearer' else None

def current_user(request: Request):
    """Shared route dependency; verifies session and CSRF on browser mutations."""
    if bearer_key(request) is not None:
        raise Problem(403, 'Ship keys cannot use this route')
    user = request.app.state.store.session(request.cookies.get(COOKIE))
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        csrf = request.headers.get('x-csrf-token', '')
        if not hmac.compare_digest(csrf.encode(), user['csrf_token'].encode()):
            raise Problem(403, 'Refresh the page before making changes')
    return user

def member(request: Request):
    """Room routes: a signed-in person, or a ship presenting its key."""
    key = bearer_key(request)
    return current_user(request) if key is None else request.app.state.store.ship_for_key(key, parse_presence(request.headers))

def ship_member(request: Request):
    """Ship-only routes: the ship that presented its key. A signed-in person gets 403."""
    key = bearer_key(request)
    if key is None:
        raise Problem(403, 'Only a ship key can use this route')
    return request.app.state.store.ship_for_key(key, parse_presence(request.headers))

def actor(request):
    return current_user(request)['id']

def tailnet_only(request):
    """Store-copy spec I 9: an imprint reaches the station over the tailnet only. The public route lets a request with
    a valid ship key through, so the request, manifest, parts and complete routes refuse a public (Funnel) one here,
    before the ship is looked up (review S5)."""
    if is_public(request.scope):
        raise Problem(403, 'Imprints go to the station over the tailnet only')

def paging(query):
    """The paging query of GET /api/chats/{key}, validated; None when it has none (today's full read)."""
    page = {}
    for name in ('limit', 'before', 'at', 'since'):
        if name in query:
            if not re.fullmatch(r'[0-9]{1,15}', query[name]):
                raise Problem(400, f'{name} must be a whole number, 0 or more')
            page[name] = int(query[name])
    for name in ('start', 'after'):
        if name in query:
            if not 0 < len(query[name]) <= 100:
                raise Problem(400, f'{name} is the id of a message')
            page[name] = query[name]
    if sum(name in page for name in ('before', 'at', 'start', 'after', 'since')) > 1:
        raise Problem(400, 'Give at most one of before, at, start, after and since')
    if 'limit' in page and not 1 <= page['limit'] <= 500:
        raise Problem(400, 'limit must be between 1 and 500')
    if page and 'limit' not in page:
        page['limit'] = 100
    return page or None

def download(row):
    return Response(row['content'], media_type='application/octet-stream', headers={'Content-Disposition': f'attachment; filename="{row["name"]}"'})

def create_app(data_dir: Path, *, clock=time.time, allowed_origins=DEFAULT_ORIGINS, secure_cookies=False, federation_endpoint=None, sync_enabled=False, model_config=None, local_demo=False, share_link_file=None, agent_history=None, imprints_dir: Path | None = None):
    allowed_origins = tuple(allowed_origins) or DEFAULT_ORIGINS
    demo_credentials = []
    if local_demo:
        from .__main__ import validate_demo
        for origin in allowed_origins:
            parsed = urlsplit(origin)
            try:
                loopback = parsed.hostname == 'localhost' or ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError:
                loopback = False
            if not loopback or parsed.scheme not in ('http', 'https'):
                raise ValueError('Local demo requires loopback origins')
        demo_credentials = validate_demo(Path(data_dir))
    from .peer_routes import federation_lifespan, install, sign_first
    from .federation import Federation
    if federation_endpoint and federation_endpoint not in allowed_origins:
        raise ValueError('Federation endpoint must be an explicitly allowed HTTPS origin')
    if federation_endpoint and not federation_endpoint.startswith('https://'):
        raise ValueError('Federation requires HTTPS')
    app = FastAPI(title='Superyak', docs_url=None, redoc_url=None, openapi_url=None, lifespan=federation_lifespan)
    store = app.state.store = Store(data_dir, clock=clock, share_link_file=share_link_file)
    app.state.federation = Federation(store, endpoint=federation_endpoint)
    app.state.agent_history = agent_history  # version check V1: read once by `serve`; None means off
    app.state.sync_enabled = sync_enabled
    app.state.imprints_dir = imprints_dir  # R8: None leaves the imprint routes out
    # public route spec 3: public sign-ins, tailnet ones (public requests never enter) and known browsers' public ones
    lanes = app.state.sign_in_lanes = SimpleNamespace(public=SignInLane(2, 8), tailnet=SignInLane(1, 4), known=SignInLane(1, 4))
    install(app)
    from .models import LocalGemma
    from .source_routes import install as install_sources
    app.state.assistant = LocalGemma(model_config)
    install_sources(app)
    app.mount('/assets', StaticFiles(directory=STATIC_DIR), name='assets')
    app.add_middleware(BrowserBoundary, allowed_origins=allowed_origins)
    app.add_middleware(PublicRoute, store=store, router=app.router)  # added last, so outermost (spec 2)

    @app.exception_handler(Problem)
    async def problem(request, exc):
        return JSONResponse({'error': exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({'error': 'Invalid request'}, status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        return JSONResponse({'error': 'Request could not be completed'}, status_code=500)

    @app.get('/', include_in_schema=False)
    def browser_home():
        return FileResponse(STATIC_DIR / 'index.html')

    @app.get('/public/', include_in_schema=False)
    def browser_public():
        return FileResponse(STATIC_DIR / 'index.html')

    @app.get('/api/health')
    def health():
        """Spec 2026-10-14 S6: one database read, no session, nothing but ok. A database error goes to the 500 handler
        above. It says only that the station is up: the main app is public through Tailscale Funnel by Andy's choice
        (2026-10-14), so this route is public too and must never say more. The access-request door has no such route."""
        with store.transaction() as db:
            db.execute('SELECT 1 FROM system_meta').fetchone()
        return {'ok': True}

    async def sign_in_lane(request, username):
        """Public route spec 3: the lane a sign-in runs in, and the `public` and `device` it counts with. /api/login and
        the imprint confirm's password (R19) both take it, so a confirm is laned as a sign-in is (review S3)."""
        public, device = is_public(request.scope), request.cookies.get(DEVICE_COOKIE)
        lane = lanes.public if public else lanes.tailnet
        if public and device is not None and await run_in_threadpool(store.device_is_valid, device, username):
            lane = lanes.known  # the read writes nothing, runs before queueing and refuses a held token; Store.login checks again
        return lane, public, device

    async def login_response(request, username, password):
        lane, public, device = await sign_in_lane(request, username)
        result = await lane.run(store.login, username, password, request.client.host if request.client else 'unknown',
                                public=public, device=device)
        token, device = result.pop('token'), result.pop('device')
        response = JSONResponse(result)
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=secure_cookies or request.url.scheme == 'https', max_age=86400)
        response.set_cookie(DEVICE_COOKIE, device, httponly=True, samesite='strict', secure=True, max_age=DEVICE_LIFETIME)
        return response

    @app.post('/api/login')
    async def login(request: Request):
        data = await body(request)
        return await login_response(request, data.get('username'), data.get('password'))

    if local_demo:
        def require_local_client(request):
            try:
                loopback = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
            except ValueError:
                loopback = False
            if not loopback:
                raise Problem(403, 'Local demo requires a loopback connection')

        @app.get('/api/local-demo')
        def demo_accounts(request: Request):
            require_local_client(request)
            with store.transaction() as db:
                accounts = [dict(db.execute('SELECT username,name FROM users WHERE username=?', (c['username'],)).fetchone()) for c in demo_credentials]
            return {'accounts': accounts}

        @app.post('/api/local-demo/login')
        async def demo_login(request: Request):
            require_local_client(request)
            data = await body(request)
            credential = next((c for c in demo_credentials if c['username'] == data.get('username')), None)
            if credential is None:
                raise Problem(400, 'Choose one of the demo accounts')
            response = await login_response(request, credential['username'], credential['password'])
            store.logout(request.cookies.get(COOKIE))
            return response

    @app.get('/api/me')
    def me(request: Request):
        user = member(request)
        if user['kind'] == 'ship':
            return user
        return {**user, 'peer_id': app.state.federation.identity.peer_id}

    @app.delete('/api/ships/me/key')
    def ship_undock(request: Request):
        key = bearer_key(request)
        if key is None:
            raise Problem(403, 'Only a ship key can revoke itself')
        return store.revoke_presented_key(key)

    @app.get('/api/ships/me/instructions')
    def ship_instructions(request: Request):
        result = store.ship_instructions(ship_member(request)['id'], app.state.federation.identity.peer_id)
        update = agent_update(app.state.agent_history, parse_presence(request.headers))  # V3: absent unless behind
        if update is not None:
            result['agent_update'] = update
        return result

    @app.post('/api/ships/me/drafts', status_code=201)
    async def ship_draft(request: Request):
        who, data = ship_member(request)['id'], await body(request)
        return store.ship_draft(who, data)

    @app.get('/api/ships/directory')
    def ship_directory(request: Request):
        return store.directory(member(request)['id'])

    @app.get('/api/ships/me/board')
    def ship_board(request: Request):
        return store.board_counts(ship_member(request)['id'])  # work board 5.1: about the ship itself, so ships only

    @app.post('/api/ships/me/tickets')
    async def ticket_issue(request: Request):
        who, data = ship_member(request)['id'], await body(request)
        asked = data.get('decisions')
        decisions = isinstance(asked, list) and {'defer', 'answered'} <= {d for d in asked if isinstance(d, str)}
        return store.issue_ticket(who, data.get('message_id'), app.state.federation.identity.peer_id, decisions=decisions)

    @app.post('/api/ships/me/unread')
    async def inbox_unread(request: Request, breakouts: str | None = None):
        who, data = ship_member(request)['id'], await body(request)
        cursor, limit, wait = data.get('cursor'), data.get('limit', 30), wait_seconds(data.get('wait'))
        only_mentions = breakout_filter(breakouts)  # breakouts S6: the query's opt-in breakouts=mentions
        if not wait:
            return store.unread(who, cursor, limit, breakouts=only_mentions)
        # Every route shares this event loop, so a wait sleeps with await and holds no transaction across a sleep.
        # Store calls take the process lock and write (last_used, the cursor touch), so in a wait they run on the
        # threadpool: a busy store delays only this waiter, never the event loop the other routes share.
        with store.inbox_wait_slot(who):
            loop = asyncio.get_running_loop()
            deadline, got = loop.time() + wait, await run_in_threadpool(store.unread, who, cursor, limit, breakouts=only_mentions)
            while not got['messages'] and (left := deadline - loop.time()) > 0:
                await asyncio.sleep(min(1, left))
                if await request.is_disconnected():  # uvicorn never cancels us; the slot is freed on the way out (R6)
                    return got
                await run_in_threadpool(ship_member, request)  # a key revoked mid-wait gets 401
                got = with_earlier_noise(got, await run_in_threadpool(store.unread, who, cursor, limit, counted=False,
                                                                      breakouts=only_mentions))
            return got

    @app.post('/api/ships/me/unread/advance')
    async def inbox_advance(request: Request):
        who, data = ship_member(request)['id'], await body(request)
        return store.advance(who, data.get('cursor'), data.get('to'))

    @app.post('/api/ships/me/watch')
    async def ship_watch(request: Request):
        who, data = ship_member(request)['id'], await body(request)
        return store.station_watch(who, parse_presence(request.headers), data.get('minutes'),
                                   data.get('writable', False), data.get('label'))

    @app.post('/api/ships/me/rooms', status_code=201)
    async def breakout_open(request: Request):
        who, data = ship_member(request)['id'], await body(request)
        return store.open_breakout(who, data.get('title'), data.get('ships'))

    @app.post('/api/ships/me/rooms/{key}/leave')
    def breakout_leave(key: str, request: Request):
        return store.leave_breakout(ship_member(request)['id'], key)

    @app.post('/api/ships/me/rooms/{key}/close')
    def breakout_close(key: str, request: Request):
        return store.close_breakout(ship_member(request)['id'], key)

    @app.put('/api/ships/me/rooms/{key}/brief')
    async def ship_brief(key: str, request: Request):
        who, data = ship_member(request)['id'], await body(request)  # ship briefs S3: a ship key only; a person gets 403
        return store.save_ship_brief(who, key, data.get('body'), data.get('revision'))

    @app.post('/api/ships/me/rooms/{key}/members', status_code=201)
    async def ship_member_add(key: str, request: Request):
        who, data = ship_member(request)['id'], await body(request)  # room moderators §6: a ship key only
        return store.ship_add_member(who, key, data.get('member'), data.get('grant_id'))

    @app.delete('/api/ships/me/rooms/{key}/members/{member}')
    def ship_member_remove(key: str, member: str, request: Request, grant_id: str | None = None):
        return store.ship_remove_member(ship_member(request)['id'], key, member, grant_id)

    @app.post('/api/ships/me/tickets/{key}/finish')
    def ticket_finish(key: str, request: Request):
        return store.finish_ticket(ship_member(request)['id'], key, app.state.federation.identity.peer_id)

    @app.patch('/api/me')
    async def rename_me(request: Request):
        who, data = actor(request), await body(request)
        return store.rename_user(who, data.get('name'))

    @app.get('/api/me/corrections')
    def my_corrections(request: Request):
        return store.account_corrections(actor(request))

    @app.post('/api/logout')
    def logout(request: Request):
        actor(request)
        store.logout(request.cookies.get(COOKIE))
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE)
        return response

    @app.get('/api/accounts')
    def accounts(request: Request):
        return store.accounts(actor(request))

    @app.patch('/api/accounts/{user_id}/role')
    async def account_role(request: Request, user_id: str):
        who = actor(request)
        data = await body(request)
        if set(data) != {'role', 'expected_version'}:
            raise Problem(400, 'Provide only the role and saved version')
        return store.change_account_role(who, user_id, data['role'], data['expected_version'])

    @app.get('/api/account-role-changes')
    def role_changes(request: Request):
        return store.account_role_changes(actor(request))

    @app.post('/api/invitations')
    async def invite(request: Request):
        who = actor(request)
        data = await body(request)
        return store.invite(who, data.get('expires_in', 86400))

    @app.post('/api/invitations/redeem', status_code=201)
    async def redeem(request: Request):
        data = await body(request)
        # off the event loop: under a held write lock, one forged token stalled the whole station (Serenity's read)
        return await run_in_threadpool(store.redeem, data.get('token'), data.get('username'), data.get('name'), data.get('password'))

    @app.post('/api/access-requests', status_code=201)
    async def request_access(request: Request):
        data = await body(request)
        return store.request_access(data.get('name'), data.get('contact'), data.get('note', ''))

    @app.get('/api/ships')
    def ships(request: Request):
        return store.ships(actor(request))

    @app.post('/api/ships/{ship_id}/revoke')
    def ship_revoke(ship_id: str, request: Request):
        return store.revoke_ship(actor(request), ship_id)

    @app.get('/api/access-requests')
    def access_requests(request: Request):
        return store.access_requests(actor(request))

    @app.get('/api/access-requests/{key}')
    def access_request_status(key: str, secret: str = ''):
        return store.access_request_status(key, secret)

    @app.post('/api/access-requests/{key}/approve')
    def approve_access(request: Request, key: str):
        return store.decide_access_request(actor(request), key, True)

    @app.post('/api/access-requests/{key}/deny')
    def deny_access(request: Request, key: str):
        return store.decide_access_request(actor(request), key, False)

    @app.post('/api/dockings', status_code=201)
    async def docking_start(request: Request):
        data = await body(request)
        started = store.start_docking(data.get('ship_name'), data.get('machine'))
        return {**started, 'confirm_url': str(request.base_url).rstrip('/') + f'/#dock?code={started["code"]}'}

    @app.get('/api/dockings/code/{code}')
    def docking_preview(code: str, request: Request):
        return store.docking_preview(actor(request), code)

    @app.post('/api/dockings/{key}/confirm')
    async def docking_confirm(key: str, request: Request):
        who, data = actor(request), await body(request)
        return store.confirm_docking(who, key, data.get('code'))

    @app.get('/api/dockings/{key}')
    def docking_status(key: str, request: Request, secret: str = ''):
        # public route spec 4: the secret comes in X-Superyak-Secret, out of URLs; ?secret= is accepted for one release
        return store.docking_status(key, request.headers.get('x-superyak-secret', secret))

    @app.get('/api/contacts')
    def contacts(request: Request):
        return store.contacts(actor(request))

    @app.get('/api/home')
    def home(request: Request):
        user = current_user(request)
        who = user['id']
        spaces, chats, layers, shared = store.list_spaces(who), store.list_rooms(who), store.list_layers(who), store.shared_layers(who)
        return {'user': user, 'spaces': spaces, 'chats': chats, 'layers': layers, 'shared_layers': shared, 'counts': {'spaces': len(spaces), 'chats': len(chats), 'layers': len(layers), 'shared_layers': len(shared)}}

    @app.get('/api/spaces')
    def spaces(request: Request):
        return store.list_spaces(actor(request))

    @app.post('/api/spaces', status_code=201)
    async def space_create(request: Request):
        who, data = actor(request), await body(request)
        return store.create_space(who, data.get('name'), data.get('kind'), data.get('member_ids', []))

    @app.get('/api/spaces/{key}')
    def space_get(key: str, request: Request):
        return store.get_space(actor(request), key)

    @app.patch('/api/spaces/{key}')
    async def space_rename(key: str, request: Request):
        who, data = actor(request), await body(request)
        return store.rename_space(who, key, data.get('name'))

    @app.post('/api/spaces/{key}/members')
    async def space_member_add(key: str, request: Request):
        who, data = actor(request), await body(request)
        return store.change_space_member(who, key, data.get('user_id'))

    @app.delete('/api/spaces/{key}/members/{user_id}')
    def space_member_remove(key: str, user_id: str, request: Request):
        return store.change_space_member(actor(request), key, user_id, remove=True)

    @app.get('/api/layers')
    def layers(request: Request):
        return store.list_layers(actor(request))

    @app.post('/api/layers', status_code=201)
    async def layer_create(request: Request):
        who, data = actor(request), await body(request)
        return store.create_layer(who, data)

    @app.get('/api/layers/{key}')
    def layer_get(key: str, request: Request):
        return store.get_layer(actor(request), key)

    @app.put('/api/layers/{key}')
    async def layer_save(key: str, request: Request):
        who, data = actor(request), await body(request)
        return store.save_layer(who, key, data)

    @app.get('/api/layers/{key}/preview')
    def layer_preview(key: str, request: Request):
        return store.preview_layer(actor(request), key)

    @app.post('/api/layers/{key}/activate')
    async def layer_activate(key: str, request: Request):
        who, data = actor(request), await body(request)
        return store.activate_layer(who, key, data.get('version'), data.get('space_versions'))

    @app.post('/api/layers/{key}/withdraw')
    def layer_withdraw(key: str, request: Request):
        return store.withdraw_layer(actor(request), key)

    @app.post('/api/layers/{key}/revoke')
    async def layer_revoke(key: str, request: Request):
        who, data = actor(request), await body(request)
        return store.revoke_layer_routes(who, key, data)

    @app.get('/api/layers/{key}/revisions')
    def revisions(key: str, request: Request):
        return store.layer_revisions(actor(request), key)

    @app.get('/api/layers/{key}/revisions/{revision}/signed')
    def revision_signed(key: str, revision: int, request: Request):
        return store.revision_signed(actor(request), key, revision)

    @app.get('/api/grants')
    def grants(request: Request):
        return store.list_grants(actor(request))  # G14: a person only; current_user gives a ship key 403

    @app.post('/api/grants', status_code=201)
    async def grant_make(request: Request):
        who, data = actor(request), await body(request)  # a person with CSRF; a ship key gets 403 (G14)
        return store.make_grant(who, data.get('grantee'), data.get('targets'), data.get('rooms'), data.get('hours'),
                                data.get('budget'))

    @app.post('/api/grants/moderate', status_code=201)
    async def grant_moderate(request: Request):
        who, data = actor(request), await body(request)  # a person with CSRF; a ship key gets 403 (G14); no depth (M13)
        return store.make_moderate_grant(who, data.get('grantee'), data.get('room'), data.get('hours'),
                                         data.get('budget'), data.get('actions'))

    @app.get('/api/grants/people')
    def grant_people(request: Request):
        return store.grant_people(actor(request))

    @app.post('/api/grants/{key}/revoke')
    async def grant_revoke(key: str, request: Request):
        who, data = actor(request), await body(request)
        return store.revoke_grant(who, key, data.get('reason'))

    @app.get('/api/grants/{key}/signed')
    def grant_signed(key: str, request: Request):
        return store.grant_signed(actor(request), key)

    @app.get('/api/shared/layers')
    def shared(request: Request):
        return store.shared_layers(actor(request))

    @app.get('/api/shared/layers/{key}')
    def shared_get(key: str, request: Request):
        return store.active_layer(key, actor(request))

    @app.get('/public/layers/{key}')
    def public_get(key: str):
        return store.active_layer(key, public=True)

    @app.get('/api/files')
    def files(request: Request):
        return store.list_files(actor(request))

    @app.post('/api/files', status_code=201)
    async def file_upload(request: Request):
        who, data = actor(request), await body(request)
        return store.upload_file(who, data.get('name'), data.get('media_type'), data.get('content_base64'))

    @app.get('/api/files/{key}')
    def file_get(key: str, request: Request):
        return download(store.download_file(actor(request), key))

    @app.get('/api/shared/layers/{layer_id}/files/{key}')
    def shared_file_get(layer_id: str, key: str, request: Request):
        return download(store.download_file(actor(request), key, layer_id=layer_id))

    @app.get('/public/layers/{layer_id}/files/{key}')
    def public_file_get(layer_id: str, key: str):
        return download(store.download_file(None, key, layer_id=layer_id, public=True))

    @app.get('/api/chats')
    def chats(request: Request):
        return store.list_rooms(member(request)['id'])

    @app.post('/api/chats', status_code=201)
    async def chat_create(request: Request):
        who, data = actor(request), await body(request)
        return store.create_room(who, data.get('title', 'Private chat'), data.get('member_ids', []))

    @app.get('/api/chats/{key}')
    def chat_get(key: str, request: Request):
        return store.get_room(member(request)['id'], key, None if ':' in key else paging(request.query_params))

    @app.post('/api/chats/{key}/messages', status_code=201)
    async def chat_send(key: str, request: Request):
        who, data = member(request)['id'], await body(request)
        return store.send_message(who, key, data.get('client_message_id'), data.get('body'), data.get('ticket_id'), data.get('reply_to'))

    @app.get('/api/chats/{key}/claims')
    def chat_claims(key: str, request: Request):
        return store.room_claims(member(request)['id'], key)

    @app.post('/api/chats/{key}/claims', status_code=201)
    async def chat_claim(key: str, request: Request):
        who, data = member(request)['id'], await body(request)
        return store.claim(who, key, data.get('key'), data.get('note'), data.get('minutes'))

    @app.post('/api/chats/{key}/claims/release')
    async def chat_release(key: str, request: Request):
        who, data = member(request)['id'], await body(request)
        return store.release(who, key, data.get('key'))

    @app.get('/api/chats/{key}/board')
    def chat_board(key: str, request: Request):
        return store.room_board(member(request)['id'], key)

    @app.post('/api/chats/{key}/board', status_code=201)
    async def chat_board_post(key: str, request: Request):
        who, data = member(request)['id'], await body(request)  # the key travels in the body: it can hold `/` (R40)
        return store.post_item(who, key, data.get('key'), data.get('title'), data.get('kind'))

    @app.post('/api/chats/{key}/board/link')
    async def chat_board_link(key: str, request: Request):
        who, data = member(request)['id'], await body(request)
        return store.link_item(who, key, data.get('key'), data.get('link'))

    @app.post('/api/chats/{key}/board/done')
    async def chat_board_done(key: str, request: Request):
        who, data = member(request)['id'], await body(request)
        return store.done_item(who, key, data.get('key'), data.get('outcome'))

    @app.post('/api/chats/{key}/board/drop')
    async def chat_board_drop(key: str, request: Request):
        who, data = member(request)['id'], await body(request)
        return store.drop_item(who, key, data.get('key'))

    @app.get('/api/board')
    def person_board(request: Request):
        return store.board_view(actor(request))  # a person's Board view; current_user: a ship key 403, no session 401

    @app.put('/api/chats/{key}/brief')
    async def chat_brief(key: str, request: Request):
        who, data = actor(request), await body(request)  # a person with CSRF; a ship key gets 403
        return store.save_brief(who, key, data.get('body'), data.get('revision'))

    @app.get('/api/chats/{key}/brief/revisions')
    def chat_brief_revisions(key: str, request: Request):
        return store.brief_history(actor(request), key)  # the room's owner only; a ship key gets 403

    @app.post('/api/chats/{key}/participants', status_code=201)
    async def chat_add(key: str, request: Request):
        who, data = actor(request), await body(request)
        return store.add_participants(who, key, data.get('member_ids', []), data.get('carry_brief'), data.get('grant_id'))

    @app.delete('/api/chats/{key}/participants/{user_id}')
    def chat_remove(key: str, user_id: str, request: Request, grant_id: str | None = None):
        return store.remove_participant(actor(request), key, user_id, grant_id)

    @app.post('/api/chats/{key}/cloud')
    async def chat_cloud_mark(key: str, request: Request):
        """Never to a cloud model: the person's own mark on a room they're in (persons only; a ship key gets 403)."""
        who, data = actor(request), await body(request)
        return await run_in_threadpool(store.mark_room, who, key, data.get('earlier', True))

    @app.delete('/api/chats/{key}/cloud')
    def chat_cloud_clear(key: str, request: Request):
        return store.unmark_room(actor(request), key)

    if imprints_dir is not None:
        # Review S3: every store call, hash, write and fsync of these async routes runs in a worker, never on the event
        # loop; the confirm's in a sign-in lane. The sync routes below already run in FastAPI's threadpool.
        @app.post('/api/imprints', status_code=201)
        async def imprint_request(request: Request):
            tailnet_only(request)
            ship = await run_in_threadpool(ship_member, request)
            raw = await request.body()
            if len(raw) > MAX_IMPRINT_REQUEST:
                raise Problem(413, 'Imprint request too large')
            made = await run_in_threadpool(store.create_imprint_request, ship['id'], raw,
                                           staging=store.data_dir / 'imprints', root=imprints_dir)
            return {'id': made['id'], 'code': made['code'], 'expires': made['expires'],
                    'confirm_url': str(request.base_url).rstrip('/') + f'/#imprint?code={made["code"]}'}

        @app.get('/api/imprints')
        def imprint_list(request: Request):
            user = member(request)
            sign_first(store)
            if user['kind'] == 'ship':
                return store.imprint_context(user['id'])
            return {'imprints': store.list_imprints(user['id'])}

        @app.get('/api/imprints/code/{code}')
        def imprint_view(code: str, request: Request):
            return store.imprint_preview(actor(request), code)  # the ship's owner only; anyone else gets 404

        @app.post('/api/imprints/{request_id}/confirm')
        async def imprint_confirm(request_id: str, request: Request):
            user = await run_in_threadpool(current_user, request)  # a person with CSRF; a ship key gets 403
            data = await body(request)
            lane, public, device = await sign_in_lane(request, user['username'])  # counted as /api/login counts (S2)
            return await lane.run(store.confirm_imprint, user['id'], request_id, code=data.get('code'),
                                  password=data.get('password'), attest=data.get('attest'),
                                  source=request.client.host if request.client else 'unknown',
                                  public=public, device=device)

        @app.post('/api/imprints/{request_id}/decline')
        def imprint_decline(request_id: str, request: Request):
            return store.decline_imprint(actor(request), request_id)

        @app.put('/api/imprints/{request_id}/manifest')
        async def imprint_manifest(request_id: str, request: Request):
            tailnet_only(request)
            ship = await run_in_threadpool(ship_member, request)
            raw = await request.body()
            return await run_in_threadpool(store.put_imprint_manifest, ship['id'], request_id, raw)

        @app.put('/api/imprints/{request_id}/parts/{n}')
        async def imprint_part(request_id: str, n: int, request: Request):
            tailnet_only(request)
            ship = await run_in_threadpool(ship_member, request)
            data = await request.body()
            return await run_in_threadpool(store.put_imprint_part, ship['id'], request_id, n, data)

        @app.post('/api/imprints/{request_id}/complete')
        def imprint_complete(request_id: str, request: Request):
            tailnet_only(request)
            return store.complete_imprint(ship_member(request)['id'], request_id)

        @app.post('/api/imprints/{request_id}/withdraw')
        def imprint_withdraw(request_id: str, request: Request):
            return store.withdraw_imprint(member(request), request_id, root=imprints_dir)  # the owner or the ship; else 404

        @app.post('/api/imprints/{request_id}/shorten')
        async def imprint_shorten(request_id: str, request: Request):
            who = await run_in_threadpool(member, request)
            try:
                body = await request.json()
            except ValueError:
                body = None
            if not isinstance(body, dict) or set(body) != {'valid_until'}:
                raise Problem(400, 'Send {"valid_until": seconds}')
            return await run_in_threadpool(store.shorten_imprint, who, request_id, body['valid_until'], root=imprints_dir)

        @app.get('/api/imprints/{request_id}')
        def imprint_one(request_id: str, request: Request):
            who = member(request)['id']
            sign_first(store)
            return store.imprint_status(who, request_id)

    @app.get('/api/mentions')
    def mentions(request: Request, after: int = 0, limit: int = 50):
        return store.mentions(member(request)['id'], after, limit)

    return app
