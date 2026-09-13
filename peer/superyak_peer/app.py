"""Same-origin browser API; additional peer routers attach to this factory."""
import hmac
import time
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from .common import Problem, valid_utf8
from .db import Store

MAX_REQUEST = 6 * 1024 * 1024
COOKIE = 'superyak_session'
DEFAULT_ORIGINS = ('http://127.0.0.1:7435', 'http://localhost:7435')
STATIC_DIR = Path(__file__).with_name('static')

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

def current_user(request: Request):
    """Shared route dependency; verifies session and CSRF on browser mutations."""
    user = request.app.state.store.session(request.cookies.get(COOKIE))
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        csrf = request.headers.get('x-csrf-token', '')
        if not hmac.compare_digest(csrf.encode(), user['csrf_token'].encode()):
            raise Problem(403, 'Refresh the page before making changes')
    return user

def actor(request):
    return current_user(request)['id']

def download(row):
    return Response(row['content'], media_type='application/octet-stream', headers={'Content-Disposition': f'attachment; filename="{row["name"]}"'})

def create_app(data_dir: Path, *, clock=time.time, allowed_origins=DEFAULT_ORIGINS, secure_cookies=False, federation_endpoint=None, sync_enabled=False):
    allowed_origins = tuple(allowed_origins) or DEFAULT_ORIGINS
    from .peer_routes import federation_lifespan, install
    from .federation import Federation
    if federation_endpoint and federation_endpoint not in allowed_origins:
        raise ValueError('Federation endpoint must be an explicitly allowed HTTPS origin')
    if federation_endpoint and not federation_endpoint.startswith('https://'):
        raise ValueError('Federation requires HTTPS')
    app = FastAPI(title='Superyak', docs_url=None, redoc_url=None, openapi_url=None, lifespan=federation_lifespan)
    store = app.state.store = Store(data_dir, clock=clock)
    app.state.federation = Federation(store, endpoint=federation_endpoint)
    app.state.sync_enabled = sync_enabled
    install(app)
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

    @app.post('/api/login')
    async def login(request: Request):
        data = await body(request)
        result = store.login(data.get('username'), data.get('password'), request.client.host if request.client else 'unknown')
        token = result.pop('token')
        response = JSONResponse(result)
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=secure_cookies or request.url.scheme == 'https', max_age=86400)
        return response

    @app.get('/api/me')
    def me(request: Request):
        return {**current_user(request), 'peer_id':app.state.federation.identity.peer_id}

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

    @app.post('/api/invitations')
    async def invite(request: Request):
        who = actor(request)
        data = await body(request)
        return store.invite(who, data.get('expires_in', 86400))

    @app.post('/api/invitations/redeem', status_code=201)
    async def redeem(request: Request):
        data = await body(request)
        return store.redeem(data.get('token'), data.get('username'), data.get('name'), data.get('password'))

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

    @app.post('/api/layers/{key}/activate')
    async def layer_activate(key: str, request: Request):
        who, data = actor(request), await body(request)
        return store.activate_layer(who, key, data.get('version'))

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
        return store.list_rooms(actor(request))

    @app.post('/api/chats', status_code=201)
    async def chat_create(request: Request):
        who, data = actor(request), await body(request)
        return store.create_room(who, data.get('title', 'Private chat'), data.get('member_ids', []))

    @app.get('/api/chats/{key}')
    def chat_get(key: str, request: Request):
        return store.get_room(actor(request), key)

    @app.post('/api/chats/{key}/messages', status_code=201)
    async def chat_send(key: str, request: Request):
        who, data = actor(request), await body(request)
        return store.send_message(who, key, data.get('client_message_id'), data.get('body'))

    @app.post('/api/chats/{key}/participants', status_code=201)
    async def chat_add(key: str, request: Request):
        who, data = actor(request), await body(request)
        return store.add_participants(who, key, data.get('member_ids', []))

    @app.delete('/api/chats/{key}/participants/{user_id}')
    def chat_remove(key: str, user_id: str, request: Request):
        return store.remove_participant(actor(request), key, user_id)

    return app
