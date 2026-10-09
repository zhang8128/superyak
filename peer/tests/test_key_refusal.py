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


# --- layers: a note or instructions layer refuses a live ship key too ---------------------------------------------

LAYER_REFUSAL = ('This layer contains a live ship key, so it was not saved. Treat that key as exposed: its ship '
                 'should revoke it and dock again.')


def layer_rows(app):
    with app.state.store.transaction() as db:
        return ([tuple(r) for r in db.execute('SELECT id,version,resource_version,draft,active_revision FROM layers ORDER BY id')],
                [tuple(r) for r in db.execute('SELECT * FROM layer_revisions ORDER BY layer_id,revision')])


def refused_layer(response, key):
    assert response.status_code == 422
    assert key not in response.text and response.json()['error'] == LAYER_REFUSAL


def test_a_note_with_a_live_ship_key_is_refused_on_create_and_save(env):
    app, clients, users, ship, key, room = setup(env)
    before = layer_rows(app)
    refused_layer(clients[0].post('/api/layers', json={'title': 'Notes', 'body': f'key: {key}'}), key)
    refused_layer(clients[0].post('/api/layers', json={'title': key, 'body': 'x'}), key)
    assert layer_rows(app) == before
    layer = clients[0].post('/api/layers', json={'title': 'Fine', 'body': 'ok'}).json()
    before = layer_rows(app)
    refused_layer(clients[0].put(f'/api/layers/{layer["id"]}', json={'version': layer['version'], 'body': f'Bearer {key}'}), key)
    refused_layer(clients[0].put(f'/api/layers/{layer["id"]}', json={'version': layer['version'], 'title': key}), key)
    assert layer_rows(app) == before


def test_a_switch_to_instructions_with_a_live_key_is_refused(env):
    app, clients, users, ship, key, room = setup(env)
    layer = clients[0].post('/api/layers', json={'title': 'Fine', 'body': 'none'}).json()
    before = layer_rows(app)
    refused_layer(clients[0].put(f'/api/layers/{layer["id"]}', json={
        'version': layer['version'], 'kind': 'instructions', 'body': key, 'audience_users': [ship['id']]}), key)
    assert layer_rows(app) == before


def test_a_ship_draft_with_a_live_key_is_refused(env):
    app, clients, users, ship, key, room = setup(env)
    before = layer_rows(app)
    refused_layer(ship_client(app, key).post('/api/ships/me/drafts', json={'title': 'Rule', 'body': f'use {key}'}), key)
    refused_layer(ship_client(app, key).post('/api/ships/me/drafts', json={'title': key, 'body': 'x'}), key)
    assert layer_rows(app) == before


def test_an_older_stored_draft_with_a_key_cannot_be_previewed_or_activated(env):
    import json
    app, clients, users, ship, key, room = setup(env)
    layer = clients[0].post('/api/layers', json={'title': 'Old', 'body': 'clean'}).json()
    with app.state.store.transaction() as db:
        draft = json.loads(db.execute('SELECT draft FROM layers WHERE id=?', (layer['id'],)).fetchone()['draft'])
        draft['body'] = f'pasted {key}'
        db.execute('UPDATE layers SET draft=? WHERE id=?', (json.dumps(draft), layer['id']))
    before = layer_rows(app)
    refused_layer(clients[0].get(f'/api/layers/{layer["id"]}/preview'), key)
    refused_layer(clients[0].post(f'/api/layers/{layer["id"]}/activate', json={'version': layer['version']}), key)
    assert layer_rows(app) == before and before[1] == []


def test_a_revoked_key_or_lookalike_saves_in_a_layer(env):
    app, clients, users, ship, key, room = setup(env)
    lookalike = secrets.token_urlsafe(32)
    assert clients[0].post('/api/layers', json={'title': 'a', 'body': lookalike}).status_code == 201
    app.state.store.revoke_presented_key(key)
    assert clients[0].post('/api/layers', json={'title': 'b', 'body': f'old {key}'}).status_code == 201


def test_the_message_and_brief_refusal_wordings_are_unchanged(env):
    app, clients, users, ship, key, room = setup(env)
    refused = post(clients[0], room, 'a', key)
    assert refused.json()['error'] == ('This message contains a live ship key, so it was not posted. Treat that key as '
                                       'exposed: its ship should revoke it and dock again.')
    with pytest.raises(Problem) as brief:
        app.state.store._refuse_live_ship_keys(key, what='brief')
    assert brief.value.message == ('This brief contains a live ship key, so it was not saved. Treat that key as '
                                   'exposed: its ship should revoke it and dock again.')
