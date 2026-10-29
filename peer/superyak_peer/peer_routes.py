"""Browser-authorized pairing and separately signed federation ingress."""
from contextlib import asynccontextmanager
import asyncio
import logging
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from .common import Problem
from .identity import validate_card, pairing_code, show_code
from .signatures import LOST_IDENTITY

log = logging.getLogger(__name__)
_LOST_START = LOST_IDENTITY.split('{path}')[0]


def sign_first(store):
    """Signs the receipts key-less commands left. An error is logged (its class; for a lost identity also the fixed
    sentence, which names only the identity file) and never stops the caller: a read answers with what is there."""
    try:
        return store.sign_imprint_receipts()
    except Exception as error:  # noqa: BLE001 - signing must not stop the loop or a read
        if isinstance(error, ValueError) and str(error).startswith(_LOST_START):
            log.error('Signing imprint receipts failed (ValueError): %s', str(error))
        else:
            log.error('Signing imprint receipts failed (%s)', type(error).__name__)
        return 0


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
    async def signer():
        from . import imprints
        while not stop.is_set():
            await asyncio.to_thread(sign_first, app.state.store)
            try:
                await asyncio.wait_for(stop.wait(), timeout=imprints.SIGN_INTERVAL)
            except asyncio.TimeoutError:
                pass
    task = asyncio.create_task(worker()) if app.state.sync_enabled else None
    signing = asyncio.create_task(signer()) if app.state.imprints_dir is not None else None
    try:
        yield
    finally:
        stop.set()
        for running in (task, signing):
            if running:
                await running

def install(app):
    from .app import actor, body, caller, current_user
    router = APIRouter()
    fed = app.state.federation

    def admin_check(who):
        with fed.store.transaction() as db:
            fed.store._admin(db, who)

    @router.get('/api/connections')
    def connections(request: Request):
        return fed.connections(actor(request))

    @router.get('/api/connections/card')
    def card(request: Request):
        who = actor(request)
        if not fed.endpoint:
            raise Problem(409, 'Configure this peer HTTPS endpoint before exporting a card')
        return fed.card(who)

    @router.get('/api/connections/code')
    def code(request: Request):
        """The actor's own pairing code, for the other machine's person to type (fix:pairing-code)."""
        who = actor(request)
        if not fed.endpoint:
            raise Problem(409, 'Configure this peer HTTPS endpoint before exporting a card')
        return {'code': show_code(pairing_code(fed.card(who)))}

    @router.post('/api/connections/preview')
    async def preview(request: Request):
        await run_in_threadpool(admin_check, await caller(current_user, request))
        return validate_card((await body(request)).get('card'))

    @router.post('/api/connections/pair', status_code=201)
    async def pair(request: Request):
        who = await caller(current_user, request)
        data = await body(request)
        # the one check is in pair()
        return await run_in_threadpool(fed.pair, who, data.get('card'), code=data.get('code'))

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
