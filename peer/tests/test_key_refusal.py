"""A message that carries a live ship key is refused before anything is written: a room is history that many readers
keep, so a key posted there is a key given away."""
import secrets
import time

import pytest
from fastapi.testclient import TestClient

from superyak_peer.common import Problem


def ship_client(app, key):
    return TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver', 'authorization': f'Bearer {key}'})


def setup(env):
    app, clients, users, clock = env
    store = app.state.store
    started = store.start_docking('serenity', 'test-host')
    ship = store.confirm_docking(users[0]['id'], started['id'], started['code'])
    key = store.docking_status(started['id'], started['secret'])['key']
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id'], users[1]['id']]}).json()['id']
    return app, clients, users, ship, key, room


def post(client, room, cid, body, **extra):
    return client.post(f'/api/chats/{room}/messages', json={'client_message_id': cid, 'body': body, **extra})


def bodies(client, room):
    return [m['body'] for m in client.get(f'/api/chats/{room}').json()['messages']]


def test_a_live_ship_key_in_a_message_is_refused_and_nothing_is_written(env):
    app, clients, users, ship, key, room = setup(env)
    refused = post(clients[0], room, 'a', f'@serenity the key is "{key}", keep it safe')
    assert refused.status_code == 422
    assert key not in refused.text and 'ship key' in refused.json()['error']
    assert bodies(clients[0], room) == []
    assert ship_client(app, key).get('/api/mentions').json() == []


def test_a_ship_cannot_post_its_own_key_either(env):
    app, clients, users, ship, key, room = setup(env)
    serenity = ship_client(app, key)
    assert post(serenity, room, 'a', f'config: {{"key": "{key}"}}').status_code == 422
    assert post(serenity, room, 'b', f'Authorization: Bearer {key}\n').status_code == 422
    assert bodies(clients[0], room) == []


def test_revoked_keys_and_lookalikes_post_normally(env):
    app, clients, users, ship, key, room = setup(env)
    lookalike = secrets.token_urlsafe(32)
    assert post(clients[0], room, 'a', f'not a key: {lookalike}').status_code == 201
    app.state.store.revoke_presented_key(key)
    assert post(clients[0], room, 'b', f'old, revoked: {key}').status_code == 201
    assert sorted(bodies(clients[0], room)) == sorted([f'not a key: {lookalike}', f'old, revoked: {key}'])


def test_the_key_check_comes_before_the_ticket_check(env):
    app, clients, users, ship, key, room = setup(env)
    refused = post(ship_client(app, key), room, 'a', f'leaking {key}', ticket_id='no-such-ticket')
    assert refused.status_code == 422 and 'ship key' in refused.json()['error']


def test_keys_are_refused_on_the_way_to_federated_rooms_too(env, monkeypatch):
    app, clients, users, ship, key, room = setup(env)
    store = app.state.store
    monkeypatch.setattr(store, 'remote_send', lambda *a, **k: pytest.fail('a key must not leave for another peer'))
    with pytest.raises(Problem) as refused:
        store.send_message(users[0]['id'], 'peer:room', 'a', f'here: {key}')
    assert refused.value.status == 422


def test_checking_a_long_message_stays_fast(env):
    app, clients, users, ship, key, room = setup(env)
    body = ' '.join(secrets.token_urlsafe(32) for _ in range(450))[:20000]
    started = time.perf_counter()
    assert post(clients[0], room, 'a', body).status_code == 201
    assert time.perf_counter() - started < 0.5
