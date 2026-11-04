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


SYNC_SECONDS = 5
CHECKPOINT_SECONDS = 3600  # store-wal-mode D2: the lighthouse checkpoints the store hourly

@asynccontextmanager
async def federation_lifespan(app):
    """serve --sync's worker (federation pull plan P11): federate's pass every SYNC_SECONDS, or at once when "Check
    delivery now" wakes it. Passes are counted, so the button can answer after the pass it woke. A pass that raises
    is logged and the worker goes on (nit 9): one OperationalError used to end it silently. Store-wal-mode D2: the
    lighthouse's keeper is open for the lifespan, and Store.checkpoint runs every CHECKPOINT_SECONDS on a worker
    thread; the exit stops the checkpoints, then closes the keeper."""
    from .federate import Federate
    await asyncio.to_thread(app.state.store.keep_open)  # after the Store is built: create_app built it
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
                log.exception('A delivery pass failed')
            app.state.sync_finished += 1
            waits = [asyncio.create_task(stop.wait()), asyncio.create_task(app.state.sync_wake.wait())]
            await asyncio.wait(waits, timeout=SYNC_SECONDS, return_when=asyncio.FIRST_COMPLETED)
            for waiting in waits:
                waiting.cancel()
    async def signer():
        from . import imprints
        while not stop.is_set():
            await asyncio.to_thread(sign_first, app.state.store)
            try:
                await asyncio.wait_for(stop.wait(), timeout=imprints.SIGN_INTERVAL)
            except asyncio.TimeoutError:
                pass
    async def checkpointer():
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=CHECKPOINT_SECONDS)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await asyncio.to_thread(app.state.store.checkpoint)
            except Exception:  # noqa: BLE001 - logged; the next hour's goes on
                log.exception('A checkpoint failed')
    task = asyncio.create_task(worker()) if app.state.sync_enabled else None
    signing = asyncio.create_task(signer()) if app.state.imprints_dir is not None else None
    checkpoints = asyncio.create_task(checkpointer())
    try:
        yield
    finally:
        stop.set()
        try:
            for running in (task, signing, checkpoints):
                if running:
                    await running
        finally:
            await asyncio.to_thread(app.state.store.close_keeper)

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
    async def unpair(contact_id: str, request: Request):
        """Disconnects the peer; with {"retire": true}, for a host that may be compromised, also retires it (owner trust
        spec item 6, S11). No body, or retire false, unpairs as before."""
        who = await caller(current_user, request)
        sent = (await request.body()).strip()  # old callers send no body at all
        retire = (await body(request)).get('retire', False) if sent else False
        if type(retire) is not bool:
            raise Problem(400, 'retire is true or false')
        return await run_in_threadpool(fed.unpair, who, contact_id, retire=retire)

    # Owner trust (spec items 2, 4a and 6): the admin's acts in the browser. Each takes a person's session with CSRF
    # (current_user), so a ship key gets 403 and never acts. The grant's and the renewal's password run in a sign-in
    # lane and count as /api/login counts a sign-in from the same client, as the imprint confirm's does (app.py).
    async def with_password(request, call, target, **more):
        """`call(person, target, days=, expect=, password=, shown=, ...)` in the lane; `more` names a body field to pass
        on. `shown` is the grant line the page showed the admin, which the store refuses unless it is what it stores."""
        user = await run_in_threadpool(current_user, request)  # a person with CSRF; a ship key gets 403
        data = await body(request)
        if not isinstance(data.get('shown'), str):
            raise Problem(400, 'shown is the grant line the page showed')
        lane, public, device = await app.state.sign_in_lane(request, user['username'])
        return await lane.run(call, user['id'], target, days=data.get('days'), expect=data.get('expect'),
                              password=data.get('password'), source=request.client.host if request.client else 'unknown',
                              public=public, device=device, shown=data['shown'],
                              **{name: read(data) for name, read in more.items()})

    @router.get('/api/connections/{contact_id}/trust')
    def trust_line(contact_id: str, request: Request, days: int = 90):
        """The grant line for this owner contact and `days`, by this station's clock: the page shows it, for a grant
        or a renewal, before it asks for the password, and sends it back as `shown`."""
        return fed.store.owner_trust_line(actor(request), contact_id, days)

    @router.post('/api/connections/{contact_id}/trust', status_code=201)
    async def grant_trust(contact_id: str, request: Request):
        return await with_password(request, fed.store.grant_owner_trust, contact_id)

    @router.get('/api/owner-trust/{grant_id}')
    def trust_renewal(grant_id: str, request: Request):
        """What the renewal page shows before it asks for the password: the trust and the ships in its window."""
        return fed.store.owner_trust_renewal(actor(request), grant_id)

    @router.post('/api/owner-trust/{grant_id}/renew')
    async def renew_trust(grant_id: str, request: Request):
        def seen(data):  # the (window_seq, paired) the page showed, a JSON pair; anything else is renew's 400
            shown = data.get('seen')
            return tuple(shown) if isinstance(shown, list) else shown
        return await with_password(request, fed.store.renew_owner_trust, grant_id, seen=seen)

    @router.post('/api/owner-trust/{grant_id}/revoke')
    async def revoke_trust(grant_id: str, request: Request):
        """It only takes power away, so it needs no password (revoke_owner_trust)."""
        who = await caller(current_user, request)
        await body(request)
        return await run_in_threadpool(fed.store.revoke_owner_trust, who, grant_id)

    @router.get('/api/sync')
    def status(request: Request):
        return {'enabled':app.state.sync_enabled, 'deliveries':fed.status(actor(request))}

    @router.post('/api/sync')
    async def sync(request: Request):
        """Check delivery now (plan P11). Every peer becomes due. With --sync, this process's worker is woken and the
        answer waits, about 10 s at most, for the pass it woke, so the person sees fresh status. Without it, another
        process (federate) syncs, so this one never dials and answers at once. The session and the store run in workers,
        identity first; the wake and the counters stay on the loop, since an asyncio.Event isn't thread-safe."""
        who = await run_in_threadpool(actor, request)
        await run_in_threadpool(fed.make_due)
        if app.state.sync_enabled and hasattr(app.state, 'sync_wake'):
            want = app.state.sync_started + 1
            app.state.sync_wake.set()
            for _ in range(200):
                if app.state.sync_finished >= want:
                    break
                await asyncio.sleep(0.05)
        return {'enabled':app.state.sync_enabled, 'deliveries':await run_in_threadpool(fed.status, who)}

    @router.post('/api/sync/{key}/retry')
    def retry(key: str, request: Request):
        return fed.retry(actor(request),key)

    @router.post('/federation/events')
    async def receive(request: Request):
        if request.url.scheme != 'https':
            raise Problem(403, 'Federation requires HTTPS')
        return await run_in_threadpool(fed.receive, await request.body())

    app.include_router(router)
