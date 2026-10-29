"""federation-listen (federation pull plan, Task 8): a push peer's federation listener, two routes and nothing else,
served on loopback behind the identity's own certificate. POST /federation/events goes to `receive` (one envelope,
MAX_ENVELOPE at most) and POST /federation/pull to `serve_pull` (16 KiB at most). Bodies are capped as they stream,
and a larger Content-Length is refused unread with 413. Both handlers run in a worker thread, so a 5 s walk never
holds a push back and "busy" can happen (nit 11). Every other method and path is 404, and there is no Host check
(nit 20): a pinned peer dials the name its card gives. Plain HTTP is refused, as the lighthouse refuses it."""
import asyncio
import json

from .common import Problem
from .identity import MAX_ENVELOPE

PULL_REQUEST_MAX = 16 * 1024
ROUTES = {'/federation/events': ('receive', MAX_ENVELOPE), '/federation/pull': ('serve_pull', PULL_REQUEST_MAX)}


async def _reply(send, status, value):
    # UTF-8, compact: the bytes federation.py counts for P5 and the budget (Rio Grande's MF2). ASCII escapes made an
    # astral character 12 bytes, which took a release P5 had passed over the transport's cap.
    body = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    await send({'type': 'http.response.start', 'status': status,
                'headers': [(b'content-type', b'application/json'), (b'content-length', str(len(body)).encode()),
                            (b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff')]})
    await send({'type': 'http.response.body', 'body': body})


async def _body(receive, cap):
    """The request's body, or None once it passes `cap` (the rest is never read)."""
    chunks, size = [], 0
    while True:
        message = await receive()
        if message['type'] == 'http.disconnect':
            return None
        chunk = message.get('body', b'')
        size += len(chunk)
        if size > cap:
            return None
        chunks.append(chunk)
        if not message.get('more_body', False):
            return b''.join(chunks)


def create_listener(data_dir, *, federation=None):
    """The listener's ASGI app. federation-listen passes its Federation, built from an identity it checked exists (P9);
    without one, `data_dir`'s store and identity.json are used, and an identity is never made here."""
    if federation is None:
        from .db import Store
        from .federation import Federation
        from .identity import PeerIdentity
        store = Store(data_dir)
        if not (store.data_dir / 'identity.json').is_file():
            raise ValueError('identity.json is missing, and federation-listen never makes one')
        federation = Federation(store, endpoint=None, identity=PeerIdentity.load_or_create(store.data_dir))

    async def app(scope, receive, send):
        if scope['type'] == 'lifespan':
            while True:
                message = await receive()
                if message['type'] == 'lifespan.startup':
                    await send({'type': 'lifespan.startup.complete'})
                elif message['type'] == 'lifespan.shutdown':
                    await send({'type': 'lifespan.shutdown.complete'})
                    return
        if scope['type'] != 'http':
            return
        route = ROUTES.get(scope['path']) if scope['method'] == 'POST' else None
        if route is None:
            return await _reply(send, 404, {'error': 'Not found'})
        name, cap = route
        if scope.get('scheme') != 'https':
            return await _reply(send, 403, {'error': 'Federation requires HTTPS'})
        declared = dict(scope['headers']).get(b'content-length')
        if declared is not None and (not declared.isdigit() or int(declared) > cap):
            return await _reply(send, 413, {'error': 'Request too large'})
        raw = await _body(receive, cap)
        if raw is None:
            return await _reply(send, 413, {'error': 'Request too large'})
        try:
            answer = await asyncio.to_thread(getattr(federation, name), raw)
        except Problem as problem:
            return await _reply(send, problem.status, {'error': problem.message})
        except Exception:  # noqa: BLE001 - nothing of the fault leaves the listener
            return await _reply(send, 500, {'error': 'Request could not be completed'})
        await _reply(send, 200, answer)
    return app
