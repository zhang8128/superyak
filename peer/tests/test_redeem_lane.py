"""The public-route-bound plan, Task 7b: redeem checks before its lane. A public redeem is checked in memory first, its
tag under its label's key, or for an untagged invitation or activation made before the deploy the start-time set,
which only shrinks. Whatever fails is refused with no read, no lock and no place in the lane. What passes enters
redeem's lane of 1 inside and 4 waiting, whose work is bounded at 2 s as every public lane's is. The tailnet keeps its
own path."""
import asyncio
import time

from fastapi.testclient import TestClient
import httpx
import pytest

from superyak_peer import tags
from superyak_peer.app import LANE_BOUND, create_app
from superyak_peer.auth import token_hash
from superyak_peer.dispatch import DispatchGate
from test_public_lanes import _no_bound, busy, exclusive_outside_the_gate, gate_held, holding, timed

PUBLIC_CLIENT = ('203.0.113.5', 50000)
TAILNET_CLIENT = ('100.64.0.7', 50000)
PASSWORD = 'long-password-new'


def start(data_dir):
    return create_app(data_dir, allowed_origins=['http://testserver'])


@pytest.fixture
def env(tmp_path):
    app = start(tmp_path / 'home')
    admin = app.state.store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    return app, admin


def client(app, where=PUBLIC_CLIENT):
    return TestClient(app, base_url='http://testserver', client=where, headers={'origin': 'http://testserver'})


def form(token, username='newcomer'):
    return {'token': token, 'username': username, 'name': 'A Newcomer', 'password': PASSWORD}


def invitation(app, admin):
    return app.state.store.invite(admin['id'], 3600)['token']


def forged(app, label):
    """For `label`: junk, a wrong tag, an expired one, another label's tag and an unknown kid, each well-formed."""
    keys, now = app.state.store.tag_keys, time.time()
    [(kid, key)] = keys[label].items()
    [(other_kid, other_key)] = keys['activation' if label == 'invitation' else 'invitation'].items()
    real = tags.mint(label, key, kid, now + 3600)
    return {
        'junk': 'junk-token',
        'wrong tag': real[:-1] + ('A' if real[-1] != 'A' else 'B'),
        'expired': tags.mint(label, key, kid, now - 10),
        "another label's tag": tags.mint(label, other_key, other_kid, now + 3600),
        'unknown kid': tags.mint(label, key, 'ffffffff', now + 3600),
        'an untagged one never made': 'u' * 43,
    }


@pytest.mark.parametrize('label', tags.LABELS)
def test_a_forged_credential_is_refused_with_no_read_no_lock_and_no_place_in_the_lane(env, label):
    app, _ = env
    for what, token in forged(app, label).items():
        with app.state.store.counting() as counted:
            answer = client(app).post('/api/invitations/redeem', json=form(token))
        assert answer.status_code == 400 and answer.json() == {'error': 'Invitation unavailable'}, what
        assert counted.total() == 0, (what, counted.table())


def test_a_real_redeem_is_admitted_while_junk_is_in_flight(env):
    """The plan reader's P4: junk never takes a place in the lane, so 30 at once leave it free."""
    app, admin = env
    real = invitation(app, admin)

    async def together():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=PUBLIC_CLIENT), base_url='http://testserver',
                                     headers={'origin': 'http://testserver'}) as http:
            junk = [http.post('/api/invitations/redeem', json=form(f'junk-{n}', f'junk{n}')) for n in range(30)]
            return await asyncio.gather(*junk, http.post('/api/invitations/redeem', json=form(real)))
    with app.state.store.counting() as counted:
        *junk, mine = asyncio.run(together())
    assert mine.status_code == 201 and all(answer.status_code == 400 for answer in junk)
    assert counted.total('transaction', lane='redeem') == 1 and counted.total('transaction') == 1


def test_a_used_invitation_replayed_takes_the_lane_reads_once_and_is_refused(env):
    app, admin = env
    token = invitation(app, admin)
    assert client(app).post('/api/invitations/redeem', json=form(token)).status_code == 201
    with app.state.store.counting() as counted:
        again = client(app).post('/api/invitations/redeem', json=form(token, 'second'))
    assert again.status_code == 400
    assert counted.total('transaction', lane='redeem') == 1 and counted.total('transaction') == 1


def made_before_the_deploy(app, admin, token, used=0):
    with app.state.store.transaction() as db:
        db.execute('INSERT INTO invitations(token_hash,creator_id,expires,used) VALUES(?,?,?,?)',
                   (token_hash(token), admin['id'], time.time() + 3600, used))


def test_an_untagged_invitation_from_before_the_deploy_redeems_once_then_leaves_the_set(env, tmp_path):
    app, admin = env
    old = 'o' * 43
    made_before_the_deploy(app, admin, old)
    app = start(tmp_path / 'home')  # serve's next start loads it
    assert app.state.store.untagged.label(token_hash(old)) == 'invitation'
    assert client(app).post('/api/invitations/redeem', json=form(old)).status_code == 201
    assert app.state.store.untagged.label(token_hash(old)) is None
    with app.state.store.counting() as counted:
        assert client(app).post('/api/invitations/redeem', json=form(old, 'second')).status_code == 400
    assert counted.total() == 0  # gone from the set: refused unread


def test_an_untagged_one_whose_row_died_since_the_start_leaves_after_one_lookup(env, tmp_path):
    app, admin = env
    old = 'p' * 43
    made_before_the_deploy(app, admin, old)
    app = start(tmp_path / 'home')
    with app.state.store.transaction() as db:  # used elsewhere since the start: the CLI, or a tailnet redeem
        db.execute('UPDATE invitations SET used=1 WHERE token_hash=?', (token_hash(old),))
    with app.state.store.counting() as counted:
        assert client(app).post('/api/invitations/redeem', json=form(old)).status_code == 400
    assert counted.total('transaction', lane='redeem') == 1 and app.state.store.untagged.label(token_hash(old)) is None


def test_a_failed_commit_keeps_an_untagged_invitations_place_in_the_set(env, tmp_path, monkeypatch):
    """A lock at COMMIT rolls the redeem back, so its row is still live: it stays in the set, answered busy, and the
    page's one retry or a later try redeems it."""
    from contextlib import contextmanager
    import sqlite3
    app, admin = env
    old = 'q' * 43
    made_before_the_deploy(app, admin, old)
    app = start(tmp_path / 'home')
    store, real = app.state.store, type(app.state.store)._transaction
    fail = [True]

    @contextmanager
    def locked_at_the_commit(self, wait=None):
        with real(self, wait) as db:
            yield db
            if fail.pop() if fail else False:
                raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(type(store), '_transaction', locked_at_the_commit)
    assert busy(client(app).post('/api/invitations/redeem', json=form(old)))
    assert store.untagged.label(token_hash(old)) == 'invitation'
    assert client(app).post('/api/invitations/redeem', json=form(old)).status_code == 201


def test_the_kid_picks_the_label_and_its_table(env):
    """An invitation's tag looks only in invitations: an activation row under the same hash is never read for it."""
    app, admin = env
    store = app.state.store
    token = invitation(app, admin)
    with store.transaction() as db:  # an activation row with this invitation's hash, which only a forger could make
        db.execute('UPDATE invitations SET used=1 WHERE token_hash=?', (token_hash(token),))
        pending = store._create_user(db, 'pending', 'Pending', 'long-password-pending')
        db.execute('UPDATE users SET activation_pending=1 WHERE id=?', (pending['id'],))
        db.execute('INSERT INTO account_activations(token_hash,user_id,expires) VALUES(?,?,?)', (token_hash(token), pending['id'], time.time() + 3600))
    answer = client(app).post('/api/invitations/redeem', json={**form(token), 'username': 'pending', 'name': 'Pending'})
    assert answer.status_code == 400 and answer.json() == {'error': 'Invitation unavailable'}


def slowed_redeem(store, monkeypatch, seconds):
    redeem = type(store).redeem

    def slow(self, *args, **kwargs):
        time.sleep(seconds)
        return redeem(self, *args, **kwargs)
    monkeypatch.setattr(type(store), 'redeem', slow)


def test_the_redeem_lane_admits_5_and_the_6th_is_busy(env, monkeypatch):
    app, admin = env
    tokens = [invitation(app, admin) for _ in range(6)]
    slowed_redeem(app.state.store, monkeypatch, 0.3)

    async def together():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=PUBLIC_CLIENT), base_url='http://testserver',
                                     headers={'origin': 'http://testserver'}) as http:
            return await asyncio.gather(*(http.post('/api/invitations/redeem', json=form(token, f'person{n}'))
                                          for n, token in enumerate(tokens)))
    answers = asyncio.run(together())
    assert sorted(answer.status_code for answer in answers) == [201] * 5 + [503]
    assert busy(next(answer for answer in answers if answer.status_code == 503))


def test_a_tailnet_redeem_passes_while_the_public_lane_is_full(env, monkeypatch):
    app, admin = env
    tokens = [invitation(app, admin) for _ in range(6)]
    slowed_redeem(app.state.store, monkeypatch, 0.5)

    async def both():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=PUBLIC_CLIENT), base_url='http://testserver',
                                     headers={'origin': 'http://testserver'}) as public, \
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=TAILNET_CLIENT), base_url='http://testserver',
                                  headers={'origin': 'http://testserver'}) as tailnet:
            waiting = [asyncio.create_task(public.post('/api/invitations/redeem', json=form(token, f'person{n}')))
                       for n, token in enumerate(tokens[:5])]
            deadline = time.monotonic() + 10
            while app.state.redeem_lane.inside < 5:
                assert time.monotonic() < deadline, 'the lane never filled'
                await asyncio.sleep(0.01)
            mine = await tailnet.post('/api/invitations/redeem', json=form(tokens[5], 'tailnet'))
            return mine, await asyncio.gather(*waiting)
    mine, flood = asyncio.run(both())
    assert mine.status_code == 201 and [answer.status_code for answer in flood] == [201] * 5


@pytest.mark.parametrize('writer', [gate_held, exclusive_outside_the_gate])
def test_redeems_work_gives_up_at_the_bound_with_the_marked_503(env, writer):
    """The plan reader's N3: the gate held, and a raw BEGIN EXCLUSIVE from outside the gate."""
    app, admin = env
    token = invitation(app, admin)
    holder = holding(4.0, writer(app.state.store))
    answer, took = timed(lambda: client(app).post('/api/invitations/redeem', json=form(token)))
    holder.join(10)
    assert busy(answer) and LANE_BOUND - 0.1 <= took < LANE_BOUND + 1.5, took
    assert client(app).post('/api/invitations/redeem', json=form(token)).status_code == 201  # nothing was kept


@pytest.mark.parametrize('writer, unbound', [(gate_held, 'gate'), (exclusive_outside_the_gate, 'sqlite')])
def test_with_either_bound_removed_redeem_waits_past_it(env, monkeypatch, writer, unbound):
    app, admin = env
    store = app.state.store
    token = invitation(app, admin)
    if unbound == 'gate':
        monkeypatch.setattr(DispatchGate, 'bounded', lambda self, deadline, clock=None: _no_bound())
    else:
        monkeypatch.setattr(type(store), '_wait', lambda self, wait=None: 30 if wait is None else wait)
    holder = holding(3.5, writer(store))
    answer, took = timed(lambda: client(app).post('/api/invitations/redeem', json=form(token)))
    holder.join(10)
    assert answer.status_code == 201 and took >= 3.0, (answer.status_code, took)
