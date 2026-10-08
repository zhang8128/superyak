"""Station inbox, step 3: a reply names the message it answers as a field (message_replies), not through its client
id, so a session's reply and the watcher's reply never collide (spec I7)."""
from fastapi.testclient import TestClient


def ship_client(app, key):
    return TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver', 'authorization': f'Bearer {key}'})


def setup(env):
    app, clients, users, clock = env
    store = app.state.store
    started = store.start_docking('serenity', 'test-host')
    ship = store.confirm_docking(users[0]['id'], started['id'], started['code'])
    key = store.docking_status(started['id'], started['secret'])['key']
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id'], users[1]['id']]}).json()['id']
    return app, clients, users, clock, ship, ship_client(app, key), room


def post(client, room, cid, body, **extra):
    return client.post(f'/api/chats/{room}/messages', json={'client_message_id': cid, 'body': body, **extra})


def by_id(client, room):
    return {m['id']: m for m in client.get(f'/api/chats/{room}').json()['messages']}


def test_a_reply_names_the_message_it_answers(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    asked = post(clients[0], room, 'a', '@serenity what changed?').json()
    answer = post(serenity, room, 'session-1', 'run tickets went live', reply_to=asked['id'])
    assert answer.status_code == 201
    messages = by_id(clients[0], room)
    assert messages[answer.json()['id']]['reply_to'] == asked['id']
    assert messages[asked['id']]['reply_to'] is None


def test_two_different_replies_to_one_message_both_post(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    asked = post(clients[0], room, 'a', '@serenity two questions').json()
    assert post(serenity, room, 'one', 'first answer', reply_to=asked['id']).status_code == 201
    assert post(serenity, room, 'two', 'second answer', reply_to=asked['id']).status_code == 201
    assert sorted(m['body'] for m in by_id(clients[0], room).values() if m['reply_to'] == asked['id']) == ['first answer', 'second answer']


def test_a_reply_must_answer_a_message_in_the_same_room(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    other = clients[0].post('/api/chats', json={'title': 'Elsewhere', 'member_ids': [ship['id']]}).json()['id']
    elsewhere = post(clients[0], other, 'x', 'in another room').json()
    assert post(serenity, room, 'a', 'wrong room', reply_to=elsewhere['id']).status_code == 400
    assert post(serenity, room, 'b', 'no such message', reply_to='0' * 32).status_code == 400
    assert post(serenity, room, 'c', 'not an id', reply_to=7).status_code == 400
    assert all(m['reply_to'] is None for m in by_id(clients[0], room).values())


def test_a_reply_can_answer_a_federated_members_message(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    store = app.state.store
    with store.transaction() as db:
        epoch = db.execute('SELECT epoch FROM rooms WHERE id=?', (room,)).fetchone()[0]
        db.execute('INSERT INTO peer_messages VALUES(?,?,?,?,?,?,?)', ('pm1', room, f'{"a" * 64}:remote', 'x', 'from afar', epoch, clock[0]))
    assert post(serenity, room, 'a', 'answering the wormhole', reply_to='pm1').status_code == 201


def test_retries_keep_their_reply_and_a_changed_reply_is_refused(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    first = post(clients[0], room, 'a', 'one').json()
    second = post(clients[0], room, 'b', 'two').json()
    sent = post(serenity, room, 'r', 'answer', reply_to=first['id']).json()
    assert post(serenity, room, 'r', 'answer', reply_to=first['id']).json()['id'] == sent['id']
    assert post(serenity, room, 'r', 'answer', reply_to=second['id']).status_code == 409


def test_unread_shows_what_a_message_replies_to(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    started = app.state.store.start_docking('rio-grande', 'pi')
    rio = app.state.store.confirm_docking(users[0]['id'], started['id'], started['code'])
    rio_key = app.state.store.docking_status(started['id'], started['secret'])['key']
    room2 = clients[0].post('/api/chats', json={'title': 'Ships', 'member_ids': [ship['id'], rio['id']]}).json()['id']
    asked = post(serenity, room2, 'a', 'question for rio').json()
    post(ship_client(app, rio_key), room2, 'b', 'answer for serenity', reply_to=asked['id'])
    got = serenity.post('/api/ships/me/unread', json={'cursor': 's1'}).json()['messages']
    assert [(m['body'], m['reply_to']) for m in got] == [('answer for serenity', asked['id'])]


def test_replies_are_for_local_rooms_only(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    import pytest
    from superyak_peer.common import Problem
    with pytest.raises(Problem) as refused:
        app.state.store.send_message(users[0]['id'], 'peer:room', 'a', 'hi', reply_to='m1')
    assert refused.value.status == 400


def test_a_reply_carrying_a_live_key_is_refused_and_writes_no_reply_row(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    asked = post(clients[0], room, 'a', 'what is the key?').json()
    key = serenity.headers['authorization'].removeprefix('Bearer ')
    assert post(serenity, room, 'b', f'it is {key}', reply_to=asked['id']).status_code == 422
    with app.state.store.transaction() as db:
        assert db.execute('SELECT count(*) FROM message_replies').fetchone()[0] == 0
