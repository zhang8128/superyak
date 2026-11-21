"""The public-route-bound plan, Task 2: serve's live set. It is loaded once in create_app with every live session, device
and ship key, and changed only after a commit: Store.login's new session, its new or extended device and every row its
deletes remove (change C), logout's session, and a lookup that finds no live row. A lookup that raises changes nothing,
and devices never leave on a lookup."""
from contextlib import contextmanager
import sqlite3

from fastapi.testclient import TestClient
import pytest

from superyak_peer.app import create_app
from superyak_peer.auth import DEVICE_LIFETIME, DEVICES_PER_USER, SESSION_LIFETIME, SESSIONS_PER_USER, token_hash
from superyak_peer.live_set import LiveSet

PUBLIC_CLIENT = ('203.0.113.5', 50000)
PASSWORD = 'long-password-patient'


def docked(store, owner_id, name):
    started = store.start_docking(name, 'test-host')
    ship = store.confirm_docking(owner_id, started['id'], started['code'])
    return ship, store.docking_status(started['id'], started['secret'])['key']


@pytest.fixture
def env(tmp_path):
    clock = [1000000.0]
    app = create_app(tmp_path / 'peer', clock=lambda: clock[0], allowed_origins=['http://testserver'])
    owner = app.state.store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    app.state.store.create_user('patient', 'Patient', PASSWORD)
    return app, clock, owner


def browser(app, device=None):
    client = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    if device is not None:
        client.cookies.set('superyak_device', device)
    return client


def sign_in(app, device=None, username='patient', password=PASSWORD):
    """A browser signed in, and the session and device tokens its answer set."""
    client = browser(app, device)
    answer = client.post('/api/login', json={'username': username, 'password': password})
    assert answer.status_code == 200, answer.text
    client.headers['x-csrf-token'] = answer.json()['csrf_token']
    return client, answer.cookies.get('superyak_session'), answer.cookies.get('superyak_device')


def live(app, kind, token, clock):
    return app.state.store.live.has(token_hash(token), kind, clock[0])


def rows(app, table, user=None):
    with app.state.store.reading() as db:
        where, args = ('WHERE user_id=?', (user,)) if user else ('', ())
        return {row[0] for row in db.execute(f'SELECT token_hash FROM {table} {where}', args)}


def user_id(app, username):
    with app.state.store.reading() as db:
        return db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()[0]


def test_a_sign_in_puts_its_session_and_device_in_the_set_and_logout_takes_the_session_out(env):
    app, clock, _ = env
    client, session, device = sign_in(app)
    assert live(app, 'session', session, clock) and live(app, 'device', device, clock)
    assert client.post('/api/logout').status_code == 200
    assert not live(app, 'session', session, clock)
    assert live(app, 'device', device, clock)  # a device leaves only through a sign-in's own deletes


def test_the_set_says_no_once_an_entry_expires(env):
    app, clock, _ = env
    _, session, device = sign_in(app)
    clock[0] += SESSION_LIFETIME
    assert not live(app, 'session', session, clock) and live(app, 'device', device, clock)
    clock[0] += DEVICE_LIFETIME
    assert not live(app, 'device', device, clock)


def test_the_21st_session_drops_the_oldest_and_a_sign_in_clears_the_expired(env):
    """The cap counts live sessions, the new one included; ties in expiry go by age. Each removal reaches the set."""
    app, clock, _ = env
    patient = user_id(app, 'patient')
    first = [sign_in(app)[1] for _ in range(SESSIONS_PER_USER)]
    assert len(rows(app, 'sessions', patient)) == SESSIONS_PER_USER
    newest = sign_in(app)[1]
    kept = rows(app, 'sessions', patient)
    assert len(kept) == SESSIONS_PER_USER and token_hash(first[0]) not in kept and token_hash(newest) in kept
    assert not live(app, 'session', first[0], clock)
    assert all(live(app, 'session', token, clock) for token in [*first[1:], newest])
    clock[0] += SESSION_LIFETIME  # every one of them expires
    later = sign_in(app)[1]
    assert rows(app, 'sessions', patient) == {token_hash(later)}
    with app.state.store.live._lock:
        sessions = {token for kind, token in app.state.store.live._rows if kind == 'session'}
    assert sessions == {token_hash(later)}  # the expired left the set with their rows, not only by their exp


def test_the_cap_never_drops_the_session_it_just_made(env):
    """A clock set back makes the new session expire before the others: the cap still drops one of those."""
    app, clock, _ = env
    patient = user_id(app, 'patient')
    for _ in range(SESSIONS_PER_USER):
        sign_in(app)
    clock[0] -= 1000
    newest = sign_in(app)[1]
    kept = rows(app, 'sessions', patient)
    assert len(kept) == SESSIONS_PER_USER and token_hash(newest) in kept and live(app, 'session', newest, clock)


def test_a_new_device_prunes_the_oldest_and_the_expired_and_the_set_follows(env):
    app, clock, _ = env
    patient = user_id(app, 'patient')
    devices = []
    for _ in range(DEVICES_PER_USER):
        devices.append(sign_in(app)[2])
        clock[0] += 1  # each newer than the last
    assert len(rows(app, 'login_devices', patient)) == DEVICES_PER_USER
    newest = sign_in(app)[2]
    assert token_hash(devices[0]) not in rows(app, 'login_devices', patient)
    assert not live(app, 'device', devices[0], clock) and live(app, 'device', newest, clock)
    andy_device = sign_in(app, username='andy', password='long-password-andy')[2]
    clock[0] += DEVICE_LIFETIME + 100  # all expired
    fresh = sign_in(app)[2]  # a new device: the expired delete takes every user's expired rows
    assert rows(app, 'login_devices') == {token_hash(fresh)}
    with app.state.store.live._lock:
        held = {token for kind, token in app.state.store.live._rows if kind == 'device'}
    assert held == {token_hash(fresh)} and token_hash(andy_device) not in held


def test_a_devices_extension_outlives_its_old_exp_in_the_set(env):
    app, clock, _ = env
    _, _, device = sign_in(app)
    clock[0] += DEVICE_LIFETIME - 10
    _, _, again = sign_in(app, device)
    assert again == device  # the same token, extended
    clock[0] += 20  # past the old exp
    assert live(app, 'device', device, clock)


def test_a_devices_extension_returns_to_the_set_after_it_left(env):
    """An expired device row stays until a sign-in's delete; its own sign-in extends it, so it must come back."""
    app, clock, _ = env
    _, _, device = sign_in(app)
    store = app.state.store
    store.live.remove('device', token_hash(device))
    _, _, again = sign_in(app, device)
    assert again == device and live(app, 'device', device, clock)


def test_a_rolled_back_sign_in_changes_nothing_in_the_set(env, monkeypatch):
    app, clock, _ = env
    store = app.state.store
    before = len(store.live)
    made = type(store)._device_signed_in

    def fails_after_the_session(self, db, *args):
        made(self, db, *args)
        raise sqlite3.OperationalError('disk I/O error')
    monkeypatch.setattr(type(store), '_device_signed_in', fails_after_the_session)
    with pytest.raises(sqlite3.OperationalError):
        store.login('patient', PASSWORD, '127.0.0.1', public=False)
    assert len(store.live) == before and rows(app, 'sessions') == set()


def test_a_sign_in_whose_commit_fails_takes_nothing_out_of_the_set(env, monkeypatch):
    """The Tasks 2-3 reader's S1: login's whole body runs (the cap drops the oldest session, the prune the oldest
    device), then its transaction fails where it would commit, as a "database is locked" at COMMIT does in rollback
    mode. Nothing it gathered may reach the set: an apply before the commit would sign out a live session and device."""
    app, clock, _ = env
    store = app.state.store
    sessions, devices = [], []
    for _ in range(SESSIONS_PER_USER):  # 20 sessions and 20 devices, each newer than the last: both caps are due
        _, session, device = sign_in(app)
        sessions.append(session)
        devices.append(device)
        clock[0] += 1
    held, opened, real = len(store.live), [], type(store)._transaction

    @contextmanager
    def fails_at_the_commit(self, wait=None):
        with real(self, wait) as db:
            yield db
            opened.append(1)
            if len(opened) == 2:  # login's own transaction, after _reserve's
                raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(type(store), '_transaction', fails_at_the_commit)
    with pytest.raises(sqlite3.OperationalError):
        store.login('patient', PASSWORD, '127.0.0.1', public=False)
    assert len(opened) == 2
    monkeypatch.undo()
    assert len(store.live) == held
    assert live(app, 'session', sessions[0], clock) and live(app, 'device', devices[0], clock)
    assert token_hash(sessions[0]) in rows(app, 'sessions') and token_hash(devices[0]) in rows(app, 'login_devices')


def test_an_add_keeps_the_later_exp_whatever_order_it_lands_in():
    """N1: two extensions of one device applied out of order leave the later exp."""
    live_set = LiveSet()
    live_set.add('device', 'd', 200.0, 'u')
    live_set.add('device', 'd', 100.0, 'u')  # the earlier commit's add, applied late
    assert live_set.has('d', 'device', 150.0)


def test_the_set_holds_a_new_session_before_login_returns_its_cookie(env, monkeypatch):
    """A request with the new cookie can't arrive before login returns it, and by then the set has it."""
    app, clock, _ = env
    store, seen = app.state.store, []
    applied = LiveSet.apply

    def watched(self, changes):
        applied(self, changes)
        seen.append([change[:2] for change in changes])
    monkeypatch.setattr(LiveSet, 'apply', watched)
    result = store.login('patient', PASSWORD, '127.0.0.1', public=False)
    assert seen == [[('add', 'session'), ('add', 'device')]]  # one apply, after the commit
    assert store.live.has(token_hash(result['token']), 'session', clock[0])
    assert store.live.has(token_hash(result['device']), 'device', clock[0])


def test_a_second_start_loads_every_live_row_and_no_dead_one(env, tmp_path):
    """The plan reader's P2: rows made under one app are in the set of the next create_app on the same dir, and an
    expired session or device, a revoked key and a key whose account is no longer a ship's are not."""
    app, clock, owner = env
    store = app.state.store
    _, session, device = sign_in(app)
    _, old_session, old_device = sign_in(app)
    with store.transaction() as db:
        db.execute('UPDATE sessions SET expires=? WHERE token_hash=?', (clock[0] - 1, token_hash(old_session)))
        db.execute('UPDATE login_devices SET expires=? WHERE token_hash=?', (clock[0] - 1, token_hash(old_device)))
    _, key = docked(store, owner['id'], 'serenity')
    _, revoked = docked(store, owner['id'], 'defiant')
    _, unshipped = docked(store, owner['id'], 'tardis')
    with store.transaction() as db:
        db.execute('UPDATE ship_keys SET revoked=? WHERE key_hash=?', (clock[0], token_hash(revoked)))
        db.execute("UPDATE users SET kind='person' WHERE id=(SELECT ship_id FROM ship_keys WHERE key_hash=?)",
                   (token_hash(unshipped),))
    again = create_app(tmp_path / 'peer', clock=lambda: clock[0], allowed_origins=['http://testserver'])
    loaded = again.state.store.live
    assert loaded.has(token_hash(session), 'session', clock[0]) and loaded.has(token_hash(device), 'device', clock[0])
    assert loaded.has(token_hash(key), 'ship_key', clock[0])
    assert len(loaded) == 3
    public = TestClient(again, base_url='http://testserver', client=PUBLIC_CLIENT, headers={'origin': 'http://testserver'})
    public.cookies.set('superyak_session', session)
    assert public.get('/api/chats').status_code == 200
    ship = TestClient(again, base_url='http://testserver', client=PUBLIC_CLIENT, headers={'authorization': f'Bearer {key}'})
    assert ship.get('/api/me').status_code == 200


@pytest.mark.parametrize('kind', ['session', 'ship_key'])
def test_a_lookup_that_raises_leaves_the_set_as_it_was(env, monkeypatch, kind):
    """The plan reader's P3, after test_public_route's store-error case: the lookup's 503 takes nothing out, and the
    same credential passes on the next request."""
    app, clock, owner = env
    store = app.state.store
    if kind == 'session':
        token = sign_in(app)[1]
        headers = {'cookie': f'superyak_session={token}'}
    else:
        _, token = docked(store, owner['id'], 'serenity')
        store.live.add('ship_key', token_hash(token), float('inf'), owner['id'])
        headers = {'authorization': f'Bearer {token}'}
    reading = type(store).reading
    broken = [True]

    def failing(self):
        if broken.pop() if broken else False:
            raise sqlite3.OperationalError('database is locked')
        return reading(self)
    monkeypatch.setattr(type(store), 'reading', failing)
    public = TestClient(app, base_url='http://testserver', client=PUBLIC_CLIENT, headers=headers)
    assert public.get('/api/chats' if kind == 'session' else '/api/me').status_code == 503
    assert store.live.has(token_hash(token), kind, clock[0])
    assert public.get('/api/chats' if kind == 'session' else '/api/me').status_code == 200


def test_a_session_revoked_elsewhere_fails_its_lookup_once_and_leaves(env):
    """Another process (a CLI, a restore) deletes the row: the set still holds it, so the public check looks it up,
    finds no live row, and takes it out. A device is never taken out by a lookup."""
    app, clock, _ = env
    store = app.state.store
    _, session, device = sign_in(app)
    with store.transaction() as db:
        db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(session),))
    assert live(app, 'session', session, clock)
    public = TestClient(app, base_url='http://testserver', client=PUBLIC_CLIENT)
    public.cookies.set('superyak_session', session)
    assert public.get('/api/chats').status_code == 401
    assert not live(app, 'session', session, clock) and live(app, 'device', device, clock)


def test_a_key_revoked_elsewhere_fails_its_lookup_once_and_leaves(env):
    app, clock, owner = env
    store = app.state.store
    _, key = docked(store, owner['id'], 'serenity')
    store.live.add('ship_key', token_hash(key), float('inf'), owner['id'])
    with store.transaction() as db:
        db.execute('UPDATE ship_keys SET revoked=? WHERE key_hash=?', (clock[0], token_hash(key)))
    ship = TestClient(app, base_url='http://testserver', client=PUBLIC_CLIENT, headers={'authorization': f'Bearer {key}'})
    assert ship.get('/api/me').status_code == 401
    assert not live(app, 'ship_key', key, clock)


def test_a_store_outside_serve_has_no_set(tmp_path):
    from superyak_peer.db import Store
    store = Store(tmp_path / 'cli')
    store.create_user('patient', 'Patient', PASSWORD)
    assert store.live is None
    assert store.login('patient', PASSWORD, '127.0.0.1', public=False)['token']


def test_the_set_refuses_a_kind_or_change_it_does_not_know():
    live_set = LiveSet()
    with pytest.raises(ValueError):
        live_set.apply([('add', 'password', 'x', 1, 'u')])
    with pytest.raises(ValueError):
        live_set.apply([('touch', 'session', 'x')])
