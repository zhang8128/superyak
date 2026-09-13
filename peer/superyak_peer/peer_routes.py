"""Browser-authorized pairing and separately signed federation ingress."""
from contextlib import asynccontextmanager
import asyncio
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from .common import Problem
from .identity import validate_card

@asynccontextmanager
async def federation_lifespan(app):
    stop = asyncio.Event()
    async def worker():
        while not stop.is_set():
            await asyncio.to_thread(app.state.federation.sync_once)
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
    task = asyncio.create_task(worker()) if app.state.sync_enabled else None
    try:
        yield
    finally:
        stop.set()
        if task:
            await task

def install(app):
    from .app import actor, body
    router = APIRouter()
    fed = app.state.federation

    @router.get('/api/connections')
    def connections(request: Request):
        return fed.connections(actor(request))

    @router.get('/api/connections/card')
    def card(request: Request):
        who = actor(request)
        if not fed.endpoint:
            raise Problem(409, 'Configure this peer HTTPS endpoint before exporting a card')
        return fed.card(who)

    @router.post('/api/connections/preview')
    async def preview(request: Request):
        who = actor(request)
        with fed.store.transaction() as db:
            fed.store._admin(db, who)
        return validate_card((await body(request)).get('card'))

    @router.post('/api/connections/pair', status_code=201)
    async def pair(request: Request):
        who = actor(request)
        data = await body(request)
        card = validate_card(data.get('card'))
        if data.get('fingerprint') != card['fingerprint']:
            raise Problem(400, 'Review and confirm the certificate fingerprint')
        return fed.pair(who, card)

    @router.delete('/api/connections/{contact_id}')
    def unpair(contact_id: str, request: Request):
        return fed.unpair(actor(request), contact_id)

    @router.get('/api/sync')
    def status(request: Request):
        return {'enabled':app.state.sync_enabled, 'deliveries':fed.status(actor(request))}

    @router.post('/api/sync')
    async def sync(request: Request):
        who = actor(request)
        await run_in_threadpool(fed.sync_once)
        return {'enabled':app.state.sync_enabled, 'deliveries':fed.status(who)}

    @router.post('/api/sync/{key}/retry')
    def retry(key: str, request: Request):
        return fed.retry(actor(request),key)

    @router.post('/federation/events')
    async def receive(request: Request):
        if request.url.scheme != 'https':
            raise Problem(403, 'Federation requires HTTPS')
        return await run_in_threadpool(fed.receive, await request.body())

    app.include_router(router)
