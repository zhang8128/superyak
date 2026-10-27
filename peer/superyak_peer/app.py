"""Same-origin browser API; additional peer routers attach to this factory."""
import asyncio
import hmac
import ipaddress
import time
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from .agent_version import agent_update
from .common import Problem, valid_utf8
from .db import Store
from .inbox import breakout_filter, wait_seconds, with_earlier_noise
from .presence import parse_presence

MAX_REQUEST = 6 * 1024 * 1024
COOKIE = 'superyak_session'
DEFAULT_ORIGINS = ('http://127.0.0.1:7435', 'http://localhost:7435')
STATIC_DIR = Path(__file__).with_name('static')
# Public route spec 1: loopback and these tailnet ranges are tailnet; every other client is public. `serve` trusts
# forwarded headers from TRUSTED_PROXY only (tailscale serve), so an internet client can't pass as a tailnet address.
TAILNET = (ipaddress.ip_network('100.64.0.0/10'), ipaddress.ip_network('fd7a:115c:a1e0::/48'))
TRUSTED_PROXY = '127.0.0.1'


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
                message.setdefault('headers', []).extend([
                    (b'x-content-type-options', b'nosniff'),
                    (b'cache-control', b'no-store'),
                    (b'content-security-policy', b"default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
                    (b'referrer-policy', b'no-referrer'),
                ])
            await send(message)
        await self.app(scope, bounded_receive, secure_send)

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

def download(row):
    return Response(row['content'], media_type='application/octet-stream', headers={'Content-Disposition': f'attachment; filename="{row["name"]}"'})

def create_app(data_dir: Path, *, clock=time.time, allowed_origins=DEFAULT_ORIGINS, secure_cookies=False, federation_endpoint=None, sync_enabled=False, model_config=None, local_demo=False, share_link_file=None, agent_history=None):
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
    from .peer_routes import federation_lifespan, install
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
    install(app)
    from .models import LocalGemma
    from .source_routes import install as install_sources
    app.state.assistant = LocalGemma(model_config)
    install_sources(app)
    app.mount('/assets', StaticFiles(directory=STATIC_DIR), name='assets')
    app.add_middleware(BrowserBoundary, allowed_origins=allowed_origins)

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

    def login_response(request, username, password):
        result = store.login(username, password, request.client.host if request.client else 'unknown')
        token = result.pop('token')
        response = JSONResponse(result)
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=secure_cookies or request.url.scheme == 'https', max_age=86400)
        return response

    @app.post('/api/login')
    async def login(request: Request):
        data = await body(request)
        return login_response(request, data.get('username'), data.get('password'))

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
            response = login_response(request, credential['username'], credential['password'])
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
        return store.redeem(data.get('token'), data.get('username'), data.get('name'), data.get('password'))

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
    def docking_status(key: str, secret: str = ''):
        return store.docking_status(key, secret)

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
        return store.get_room(member(request)['id'], key)

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
        return store.add_participants(who, key, data.get('member_ids', []), data.get('carry_brief'))

    @app.delete('/api/chats/{key}/participants/{user_id}')
    def chat_remove(key: str, user_id: str, request: Request):
        return store.remove_participant(actor(request), key, user_id)

    @app.get('/api/mentions')
    def mentions(request: Request, after: int = 0, limit: int = 50):
        return store.mentions(member(request)['id'], after, limit)

    return app
