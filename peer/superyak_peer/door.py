"""Public door: only access requests and their status. `tailscale funnel` publishes this
process alone; it has no sessions, reads no cookies and serves no browser interface."""
import time
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .app import body
from .common import Problem
from .db import Store

DOOR_MAX_REQUEST = 16 * 1024
DROPPED_HEADERS = (b'cookie', b'authorization')


class DoorBoundary:
    """Drop ambient credentials, bound bodies, and add the app's security headers."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        scope = dict(scope, headers=[(k, v) for k, v in scope['headers'] if k.lower() not in DROPPED_HEADERS])
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > DOOR_MAX_REQUEST:
                return await JSONResponse({'error': 'Request too large'}, 413)(scope, receive, send)
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()

        async def secure_send(message):
            if message['type'] == 'http.response.start':
                message.setdefault('headers', []).extend([
                    (b'x-content-type-options', b'nosniff'), (b'cache-control', b'no-store'), (b'referrer-policy', b'no-referrer')])
            await send(message)
        await self.app(scope, replay, secure_send)


def create_door(data_dir, *, clock=time.time):
    app = FastAPI(title='Superyak door', docs_url=None, redoc_url=None, openapi_url=None)
    store = app.state.store = Store(data_dir, clock=clock)

    @app.exception_handler(Problem)
    async def problem(request, exc):
        return JSONResponse({'error': exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({'error': 'Invalid request'}, status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        return JSONResponse({'error': 'Request could not be completed'}, status_code=500)

    @app.post('/api/access-requests', status_code=201)
    async def request_access(request: Request):
        data = await body(request)
        return store.request_access(data.get('name'), data.get('contact'), data.get('note', ''))

    @app.get('/api/access-requests/{key}')
    def access_request_status(key: str, secret: str = ''):
        return store.access_request_status(key, secret)

    app.add_middleware(DoorBoundary)
    return app
