"""Browser-authorized pairing and separately signed federation ingress."""
from contextlib import asynccontextmanager
import asyncio
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from .common import Problem
from .identity import validate_card, pairing_code, show_code

SYNC_SECONDS = 5

@asynccontextmanager
async def federation_lifespan(app):
    """serve --sync's worker (federation pull plan P11): federate's pass every SYNC_SECONDS, or at once when "Check
    delivery now" wakes it. Passes are counted, so the button can answer after the pass it woke. A pass that raises is logged and
    the worker goes on (nit 9): one OperationalError used to end it silently."""
    import logging
    from .federate import Federate
    stop, app.state.sync_wake = asyncio.Event(), asyncio.Event()
    app.state.sync_started = app.state.sync_finished = 0
    async def worker():
        loop = Federate(app.state.federation)
        while not stop.is_set():
            app.state.sync_wake.clear()
            app.state.sync_started += 1
            try:
                await asyncio.to_thread(loop.run_pass)
            except Exception:  # noqa: BLE001 - logged; the next pass goes on
                logging.getLogger(__name__).exception('A delivery pass failed')
            app.state.sync_finished += 1
            waits = [asyncio.create_task(stop.wait()), asyncio.create_task(app.state.sync_wake.wait())]
            await asyncio.wait(waits, timeout=SYNC_SECONDS, return_when=asyncio.FIRST_COMPLETED)
            for waiting in waits:
                waiting.cancel()
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

    @router.get('/api/connections/code')
    def code(request: Request):
        """The actor's own pairing code, for the other machine's person to type (fix:pairing-code)."""
        who = actor(request)
        if not fed.endpoint:
            raise Problem(409, 'Configure this peer HTTPS endpoint before exporting a card')
        return {'code': show_code(pairing_code(fed.card(who)))}

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
        return fed.pair(who, data.get('card'), code=data.get('code'))  # the one check is in pair()

    @router.delete('/api/connections/{contact_id}')
    def unpair(contact_id: str, request: Request):
        return fed.unpair(actor(request), contact_id)

    @router.get('/api/sync')
    def status(request: Request):
        return {'enabled':app.state.sync_enabled, 'deliveries':fed.status(actor(request))}

    @router.post('/api/sync')
    async def sync(request: Request):
        """Check delivery now (plan P11). Every peer becomes due. With --sync, this process's worker is woken and the
        answer waits, about 10 s at most, for the pass it woke, so the person sees fresh status. Without it, another
        process (federate) syncs, so this one never dials and answers at once."""
        who = actor(request)
        await run_in_threadpool(fed.make_due)
        if app.state.sync_enabled and hasattr(app.state, 'sync_wake'):
            want = app.state.sync_started + 1
            app.state.sync_wake.set()
            for _ in range(200):
                if app.state.sync_finished >= want:
                    break
                await asyncio.sleep(0.05)
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
