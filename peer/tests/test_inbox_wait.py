"""Station inbox, step 2: an unread read may wait up to 25 s for a message, and a wait never blocks the station.
The station's routes share one event loop, so these tests drive the app on a single loop (httpx's ASGI transport)
rather than TestClient, which gives each request its own loop and would hide a blocking wait."""
import asyncio
import time

import httpx


def setup(env):
    app, clients, users, clock = env
    store = app.state.store
    started = store.start_docking('serenity', 'test-host')
    ship = store.confirm_docking(users[0]['id'], started['id'], started['code'])
    key = store.docking_status(started['id'], started['secret'])['key']
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id'], users[1]['id']]}).json()['id']
    return app, users, store, key, room


def ship(app, key):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver',
                             headers={'origin': 'http://testserver', 'authorization': f'Bearer {key}'})


async def timed(call):
    started = time.perf_counter()
    response = await call
    return response, time.perf_counter() - started


def test_a_wait_returns_soon_after_a_message_arrives(env):
    app, users, store, key, room = setup(env)

    async def scenario():
        async with ship(app, key) as serenity:
            waiting = asyncio.create_task(timed(serenity.post('/api/ships/me/unread', json={'cursor': 's1', 'wait': 10})))
            await asyncio.sleep(0.3)
            store.send_message(users[0]['id'], room, 'a', 'hello while you wait')
            return await waiting
    response, elapsed = asyncio.run(scenario())
    assert response.status_code == 200
    assert [m['body'] for m in response.json()['messages']] == ['hello while you wait']
    assert elapsed < 2.5


def test_a_wait_returns_empty_at_its_limit(env):
    app, users, store, key, room = setup(env)

    async def scenario():
        async with ship(app, key) as serenity:
            return await timed(serenity.post('/api/ships/me/unread', json={'cursor': 's1', 'wait': 1}))
    response, elapsed = asyncio.run(scenario())
    assert response.status_code == 200 and response.json()['messages'] == []
    assert 0.9 <= elapsed < 2.5


def test_other_requests_stay_fast_while_a_ship_waits(env):
    app, users, store, key, room = setup(env)

    async def scenario():
        async with ship(app, key) as serenity:
            waiting = asyncio.create_task(serenity.post('/api/ships/me/unread', json={'cursor': 's1', 'wait': 3}))
            await asyncio.sleep(0.2)
            other, elapsed = await timed(serenity.get('/api/me'))
            still_waiting = not waiting.done()
            await waiting
            return other, elapsed, still_waiting
    other, elapsed, still_waiting = asyncio.run(scenario())
    assert other.status_code == 200 and still_waiting
    assert elapsed < 0.5


def test_a_ship_holds_at_most_two_waits_and_a_dropped_wait_frees_its_slot(env):
    app, users, store, key, room = setup(env)

    async def scenario():
        async with ship(app, key) as serenity:
            waits = [asyncio.create_task(serenity.post('/api/ships/me/unread', json={'cursor': f's{n}', 'wait': 5})) for n in range(2)]
            await asyncio.sleep(0.2)
            third = await serenity.post('/api/ships/me/unread', json={'cursor': 's3', 'wait': 5})
            waits[0].cancel()  # the client goes away mid-wait
            await asyncio.gather(waits[0], return_exceptions=True)
            await asyncio.sleep(0.1)
            again = asyncio.create_task(serenity.post('/api/ships/me/unread', json={'cursor': 's4', 'wait': 1}))
            replacement = await again
            await waits[1]
            return third, replacement
    third, replacement = asyncio.run(scenario())
    assert third.status_code == 429
    assert replacement.status_code == 200


def test_bad_waits_are_refused(env):
    app, users, store, key, room = setup(env)

    async def scenario():
        async with ship(app, key) as serenity:
            return [(await serenity.post('/api/ships/me/unread', json={'wait': bad})).status_code for bad in (-1, 26, 'soon', True)]
    assert asyncio.run(scenario()) == [400, 400, 400, 400]


def test_a_key_revoked_mid_wait_gets_nothing_more(env):
    app, users, store, key, room = setup(env)

    async def scenario():
        async with ship(app, key) as serenity:
            waiting = asyncio.create_task(serenity.post('/api/ships/me/unread', json={'cursor': 's1', 'wait': 5}))
            await asyncio.sleep(0.3)
            store.revoke_presented_key(key)
            store.send_message(users[0]['id'], room, 'a', 'after the key was revoked')
            return await waiting
    response = asyncio.run(scenario())
    assert response.status_code == 401
    assert 'after the key was revoked' not in response.text


def test_a_client_that_goes_away_mid_wait_frees_its_slot_on_a_real_server(env):
    """uvicorn never cancels a handler when the client goes away; it answers receive() with http.disconnect. So the
    wait must notice that itself (R6). A raw ASGI call reproduces exactly what uvicorn sends."""
    import json
    app, users, store, key, room = setup(env)
    first = [{'type': 'http.request', 'body': json.dumps({'cursor': 's1', 'wait': 10}).encode(), 'more_body': False}]

    async def receive():
        return first.pop() if first else {'type': 'http.disconnect'}

    async def send(message):
        pass
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST', 'scheme': 'http',
             'path': '/api/ships/me/unread', 'raw_path': b'/api/ships/me/unread', 'query_string': b'', 'root_path': '',
             'headers': [(b'host', b'testserver'), (b'origin', b'http://testserver'), (b'content-type', b'application/json'),
                         (b'authorization', f'Bearer {key}'.encode())],
             'client': ('127.0.0.1', 50000), 'server': ('testserver', 80)}

    async def scenario():
        started = time.perf_counter()
        await app(scope, receive, send)
        elapsed = time.perf_counter() - started
        async with ship(app, key) as serenity:
            again = await asyncio.gather(*[serenity.post('/api/ships/me/unread', json={'cursor': f'n{n}', 'wait': 1}) for n in range(2)])
        return elapsed, [r.status_code for r in again]
    elapsed, statuses = asyncio.run(scenario())
    assert elapsed < 3
    assert statuses == [200, 200]


def test_a_wait_counts_as_one_read(env):
    app, users, store, key, room = setup(env)

    async def scenario():
        async with ship(app, key) as serenity:
            for _ in range(58):
                assert (await serenity.post('/api/ships/me/unread', json={'cursor': 's1'})).status_code == 200
            waited = await serenity.post('/api/ships/me/unread', json={'cursor': 's1', 'wait': 3})
            last = await serenity.post('/api/ships/me/unread', json={'cursor': 's1'})
            over = await serenity.post('/api/ships/me/unread', json={'cursor': 's1'})
            return waited.status_code, last.status_code, over.status_code
    assert asyncio.run(scenario()) == (200, 200, 429)


def test_a_slow_store_never_stalls_the_station_during_a_wait(env, monkeypatch):
    """Each pass of a wait reads through the store, which takes the process lock; those calls run off the event
    loop, so a slow or busy store delays only the waiter. Measured as event-loop lag: a blocked loop would also block
    any timer in the test, so the test watches the largest gap between 50 ms ticks."""
    app, users, store, key, room = setup(env)
    real = store.unread

    def slow(*args, **kwargs):
        if kwargs.get('counted') is False:
            time.sleep(0.8)
        return real(*args, **kwargs)
    monkeypatch.setattr(store, 'unread', slow)

    async def scenario():
        gaps, done = [], asyncio.Event()

        async def ticker():
            last = time.perf_counter()
            while not done.is_set():
                await asyncio.sleep(0.05)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now
        async with ship(app, key) as serenity:
            tick = asyncio.create_task(ticker())
            await serenity.post('/api/ships/me/unread', json={'cursor': 's1', 'wait': 3})
            done.set()
            await tick
        return max(gaps)
    assert asyncio.run(scenario()) < 0.4
