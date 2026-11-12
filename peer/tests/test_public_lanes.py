"""The public-route-bound plan, Task 6: published layers' lane and the bounded waits. A public layer read or file read
waits in a lane of 4 inside and 32 waiting, which admits 36, so the 37th at once is answered busy. Every public lane's
work runs under the store's bound, so neither the dispatch gate nor SQLite's busy wait holds a slot past 2 s, and work
that meets either is answered with the marked 503. Tailnet reads are as before, outside every lane."""
import asyncio
import sqlite3
import threading
import time

from fastapi.testclient import TestClient
import httpx
import pytest

from superyak_peer import counting
from superyak_peer.app import LANE_BOUND, create_app
from superyak_peer.dispatch import DispatchGate

PUBLIC_CLIENT = ('203.0.113.5', 50000)
TAILNET_CLIENT = ('100.64.0.7', 50000)
JUNK_LAYER = 'no-such-layer'


@pytest.fixture
def env(tmp_path):
    app = create_app(tmp_path / 'peer', allowed_origins=['http://testserver'])
    store = app.state.store
    owner = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    layer = store.create_layer(owner['id'], {'title': 'Open', 'body': 'For anyone', 'public': True})
    store.activate_layer(owner['id'], layer['id'], layer['version'])
    return app, layer['id']


def public(app):
    return TestClient(app, base_url='http://testserver', client=PUBLIC_CLIENT)


def busy(answer):
    return (answer.status_code == 503 and answer.headers.get('x-superyak-busy') == '1'
            and answer.headers.get('retry-after') == '1' and answer.headers.get('x-content-type-options') == 'nosniff'
            and answer.json() == {'error': 'This home is busy; try again shortly'})


def test_a_public_layer_read_waits_in_the_layers_lane_and_a_tailnet_one_does_not(env):
    app, key = env
    tailnet = TestClient(app, base_url='http://testserver', client=TAILNET_CLIENT)
    with app.state.store.counting() as counted:
        assert public(app).get(f'/public/layers/{key}').json()['body'] == 'For anyone'
        assert public(app).get(f'/public/layers/{key}/files/no-such-file').status_code == 404
    assert counted.total('transaction', lane='layers') == 2 and counted.total('transaction', lane=counting.BEFORE) == 0
    with app.state.store.counting() as counted:
        assert tailnet.get(f'/public/layers/{key}').status_code == 200
        assert tailnet.get(f'/public/layers/{key}/files/no-such-file').status_code == 404
    assert counted.total(lane='layers') == 0 and counted.total('transaction') == 2


def holding(release_after, hold):
    """`hold` on its own thread until `release_after` seconds pass; returns the thread, started once it holds."""
    held = threading.Event()

    def run():
        with hold():
            held.set()
            time.sleep(release_after)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert held.wait(5)
    return thread


def gate_held(store):
    return lambda: store.dispatch_gate


def exclusive_outside_the_gate(store):
    """A raw writer that never takes the gate, as another process's sqlite3 would."""
    class Exclusive:
        def __enter__(self):
            self.db = sqlite3.connect(store.db_path, timeout=0, isolation_level=None)
            self.db.execute('BEGIN EXCLUSIVE')

        def __exit__(self, *_):
            self.db.execute('ROLLBACK')
            self.db.close()
    return Exclusive


def timed(call):
    started = time.monotonic()
    answer = call()
    return answer, time.monotonic() - started


@pytest.mark.parametrize('writer', [gate_held, exclusive_outside_the_gate])
def test_a_public_layer_read_gives_up_at_the_bound_with_the_marked_503(env, writer):
    """The plan reader's P5, two arms of one writer each: the gate held on another thread, and a raw BEGIN EXCLUSIVE
    from outside the gate. Each held for 4 s; the lane's work gives up at 2 s, answered busy."""
    app, key = env
    holder = holding(4.0, writer(app.state.store))
    answer, took = timed(lambda: public(app).get(f'/public/layers/{key}'))
    holder.join(10)
    assert busy(answer) and LANE_BOUND - 0.1 <= took < LANE_BOUND + 1.5, took
    assert app.state.layer_lane.inside == 0


@pytest.mark.parametrize('writer, unbound', [(gate_held, 'gate'), (exclusive_outside_the_gate, 'sqlite')])
def test_with_either_bound_removed_the_work_waits_past_it(env, monkeypatch, writer, unbound):
    """The control for the arms above: each bound is what stops its wait. With the gate's bound gone the read waits
    out the held gate; with SQLite's gone it waits out the raw writer; either way it answers only after the 3.5 s hold."""
    app, key = env
    store = app.state.store
    if unbound == 'gate':
        monkeypatch.setattr(DispatchGate, 'bounded', lambda self, deadline, clock=None: _no_bound())
    else:
        monkeypatch.setattr(type(store), '_wait', lambda self, wait=None: 30 if wait is None else wait)
    holder = holding(3.5, writer(store))
    answer, took = timed(lambda: public(app).get(f'/public/layers/{key}'))
    holder.join(10)
    assert answer.status_code == 200 and took >= 3.0, (answer.status_code, took)


class _no_bound:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.mark.journal('delete')
def test_the_miss_lanes_lookup_gives_up_at_the_bound_too(env, monkeypatch):
    """Its lookup is a reading(), which in rollback mode takes the gate: held, the key is answered busy at 2 s, never 401
    (undock would read a 401 as revoked)."""
    app, _ = env
    holder = holding(4.0, gate_held(app.state.store))
    ship = TestClient(app, base_url='http://testserver', client=PUBLIC_CLIENT, headers={'authorization': 'Bearer ' + 'k' * 43})
    answer, took = timed(lambda: ship.get('/api/me'))
    holder.join(10)
    assert busy(answer) and LANE_BOUND - 0.1 <= took < LANE_BOUND + 1.5, took


def slowed_layers(store, monkeypatch, seconds):
    read = type(store).active_layer

    def slow(self, *args, **kwargs):
        time.sleep(seconds)
        return read(self, *args, **kwargs)
    monkeypatch.setattr(type(store), 'active_layer', slow)


def test_the_37th_public_layer_read_at_once_is_busy(env, monkeypatch):
    """The plan reader's P10: 4 inside and 32 waiting admit 36."""
    app, _ = env
    slowed_layers(app.state.store, monkeypatch, 0.3)

    async def flood():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=PUBLIC_CLIENT), base_url='http://testserver') as http:
            return await asyncio.gather(*(http.get(f'/public/layers/{JUNK_LAYER}-{n}') for n in range(37)))
    answers = asyncio.run(flood())
    assert sorted(answer.status_code for answer in answers) == [404] * 36 + [503]
    assert busy(next(answer for answer in answers if answer.status_code == 503))
    assert app.state.layer_lane.inside == 0


def test_a_tailnet_layer_read_passes_while_the_public_lane_is_full(env, monkeypatch):
    app, key = env
    slowed_layers(app.state.store, monkeypatch, 0.6)

    async def both():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=PUBLIC_CLIENT), base_url='http://testserver') as flood, \
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=TAILNET_CLIENT), base_url='http://testserver') as tailnet:
            waiting = [asyncio.create_task(flood.get(f'/public/layers/{JUNK_LAYER}-{n}')) for n in range(36)]
            await asyncio.sleep(0.1)
            assert app.state.layer_lane.inside == 36  # full
            mine = await tailnet.get(f'/public/layers/{key}')
            return mine, await asyncio.gather(*waiting)
    mine, flood = asyncio.run(both())
    assert mine.status_code == 200 and mine.json()['body'] == 'For anyone'
    assert sorted(answer.status_code for answer in flood) == [404] * 36


@pytest.mark.journal('delete')
def test_reading_takes_a_wait_for_sqlites_busy_wait(env):
    """The plan reader's P5: reading() had only the connection's 30 s default. In rollback mode a raw writer holds off a
    reader; with wait=0.3 it gives up then, "database is locked"."""
    app, _ = env
    store = app.state.store
    holder = holding(3.0, exclusive_outside_the_gate(store))

    def read():
        with store.reading(wait=0.3) as db:
            return db.execute('SELECT 1').fetchone()
    started = time.monotonic()
    with pytest.raises(sqlite3.OperationalError, match='locked'):
        read()
    took = time.monotonic() - started
    holder.join(10)
    assert 0.25 <= took < 1.5, took


def test_a_sign_ins_failure_is_never_marked_busy(env, monkeypatch):
    """The Tasks 4-5 reader's C1: login, check_password_attempt and pending_sign_in commit _reserve's counted attempt
    first, so a page that asked again after a later failure would count it twice. Only the public lanes (the miss lane,
    the layers' lane) are bounded and marked; the sign-in lanes are neither, and a lock in login's later transaction
    is the unmarked 500 a page never asks again after."""
    from contextlib import contextmanager
    from superyak_peer.app import PublicLane, SignInLane
    app, _ = env
    lanes = vars(app.state.sign_in_lanes)
    assert set(lanes) == {'public', 'tailnet', 'known'}
    assert all(type(lane) is SignInLane and not isinstance(lane, PublicLane) for lane in lanes.values())
    store, opened, real = app.state.store, [], type(app.state.store)._transaction

    @contextmanager
    def locked_after_the_reserve(self, wait=None):
        with real(self, wait) as db:
            yield db
            opened.append(1)
            if len(opened) == 2:  # login's own transaction, after _reserve's committed the attempt
                raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(type(store), '_transaction', locked_after_the_reserve)
    browser = TestClient(app, base_url='http://testserver', client=PUBLIC_CLIENT, headers={'origin': 'http://testserver'},
                         raise_server_exceptions=False)  # the answer a page gets, not the test's own exception
    answer = browser.post('/api/login', json={'username': 'andy', 'password': 'long-password-andy'})
    assert len(opened) == 2
    assert answer.status_code == 500 and 'x-superyak-busy' not in answer.headers
