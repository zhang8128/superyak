"""Station inbox, step 1: a read cursor per ship and name on the station, unread over both message tables, and an
explicit forward-only advance (docs/superpowers/specs/2026-10-08-station-inbox-design.md)."""
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


def say(client, room, cid, body):
    response = client.post(f'/api/chats/{room}/messages', json={'client_message_id': cid, 'body': body})
    assert response.status_code == 201, response.text
    return response.json()


def unread(ship, **body):
    response = ship.post('/api/ships/me/unread', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def advance(ship, to, **body):
    return ship.post('/api/ships/me/unread/advance', json={'to': to, **body})


def test_unread_is_oldest_first_from_my_rooms_and_skips_my_own_posts(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    elsewhere = clients[2].post('/api/chats', json={'title': 'Not mine', 'member_ids': [users[3]['id']]}).json()['id']
    first = say(clients[0], room, 'a', 'first')
    clock[0] += 1
    say(serenity, room, 'b', 'my own post')
    say(clients[2], elsewhere, 'c', 'a room the ship is not in')
    second = say(clients[1], room, 'd', '@serenity second')
    got = unread(serenity, cursor='s1')
    assert [m['message_id'] for m in got['messages']] == [first['id'], second['id']]
    head = got['messages'][0]
    assert (head['room_id'], head['room_title'], head['body'], head['author']['username'], head['author']['kind']) == (
        room, 'Ops', 'first', 'patient', 'person')
    assert [m['mentions_me'] for m in got['messages']] == [False, True]
    assert all(m['reply_to'] is None and m['source'] is None for m in got['messages'])
    assert got['messages'][0]['event_id'] < got['messages'][1]['event_id'] and got['more'] is False


def test_reading_never_moves_the_cursor_and_advance_only_goes_forward(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    say(clients[0], room, 'a', 'one')
    say(clients[0], room, 'b', 'two')
    events = [m['event_id'] for m in unread(serenity, cursor='s1')['messages']]
    assert [m['event_id'] for m in unread(serenity, cursor='s1')['messages']] == events
    assert advance(serenity, events[0], cursor='s1').json()['position'] == events[0]
    assert [m['body'] for m in unread(serenity, cursor='s1')['messages']] == ['two']
    assert advance(serenity, events[1], cursor='s1').json()['position'] == events[1]
    assert advance(serenity, events[0], cursor='s1').json()['position'] == events[1]  # earlier is a no-op
    assert unread(serenity, cursor='s1')['messages'] == []


def test_advance_refuses_ids_that_are_not_message_events(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    say(clients[0], room, 'a', 'one')
    event = unread(serenity, cursor='s1')['messages'][0]['event_id']
    assert advance(serenity, event + 1000, cursor='s1').status_code == 400
    assert advance(serenity, 'soon', cursor='s1').status_code == 400
    room_created = app.state.store.events_since(0)[0]
    assert room_created['kind'] != 'chat.message'
    assert advance(serenity, room_created['id'], cursor='s1').status_code == 400


def test_two_cursor_names_never_take_each_others_messages(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    say(clients[0], room, 'a', 'for everyone')
    one = unread(serenity, cursor='session-one')['messages']
    advance(serenity, one[-1]['event_id'], cursor='session-one')
    assert unread(serenity, cursor='session-one')['messages'] == []
    assert [m['body'] for m in unread(serenity, cursor='session-two')['messages']] == []  # starts where the ship read furthest
    say(clients[1], room, 'b', 'after both')
    assert [m['body'] for m in unread(serenity, cursor='session-one')['messages']] == ['after both']
    assert [m['body'] for m in unread(serenity, cursor='session-two')['messages']] == ['after both']


def test_a_new_name_starts_at_the_furthest_read_and_a_first_cursor_pages_from_the_beginning(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    for n in range(5):
        say(clients[0], room, f'm{n}', f'message {n}')
    page = unread(serenity, cursor='first', limit=3)
    assert [m['body'] for m in page['messages']] == ['message 0', 'message 1', 'message 2'] and page['more'] is True
    assert page['position'] == 0
    advance(serenity, page['messages'][1]['event_id'], cursor='behind')
    advance(serenity, page['messages'][2]['event_id'], cursor='ahead')
    assert [m['body'] for m in unread(serenity, cursor='newcomer')['messages']] == ['message 3', 'message 4']


def test_a_ship_removed_from_a_room_sees_nothing_from_it(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    say(clients[0], room, 'a', 'before removal')
    assert clients[0].delete(f'/api/chats/{room}/participants/{ship["id"]}').status_code in (200, 204)
    say(clients[0], room, 'b', 'after removal')
    assert unread(serenity, cursor='s1')['messages'] == []


def test_a_federated_members_reply_in_a_local_room_is_unread_with_a_remote_author(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    store = app.state.store
    peer, actor = 'a' * 64, 'remote-user'
    with store.transaction() as db:  # exactly what federation.py does for a member's reply (federation.py:408-409)
        db.execute('INSERT INTO peers VALUES(?,?,?)', (peer, '{}', 1))
        db.execute('INSERT INTO remote_contacts VALUES(?,?,?,?)', ('c1', peer, actor, 'Wormhole Willa'))
        epoch = db.execute('SELECT epoch FROM rooms WHERE id=?', (room,)).fetchone()[0]
        db.execute('INSERT INTO peer_messages VALUES(?,?,?,?,?,?,?)', ('pm1', room, f'{peer}:{actor}', 'x', 'from afar', epoch, clock[0]))
        store.emit(db, 'chat.message', room, epoch, {'message_id': 'pm1', 'author_id': f'{peer}:{actor}'})
    got = unread(serenity, cursor='s1')['messages']
    assert [(m['message_id'], m['body']) for m in got] == [('pm1', 'from afar')]
    assert got[0]['author'] == {'id': f'{peer}:{actor}', 'username': None, 'name': 'Wormhole Willa', 'kind': 'remote', 'owner_id': None}


def test_only_ships_use_the_inbox_and_bad_input_is_refused(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    assert clients[0].post('/api/ships/me/unread', json={}).status_code == 403
    for bad in ({'cursor': ''}, {'cursor': 'has space'}, {'cursor': 'x' * 101}, {'limit': 0}, {'limit': 101}, {'limit': 'ten'}):
        assert serenity.post('/api/ships/me/unread', json=bad).status_code == 400, bad
    assert unread(serenity)['cursor'] == 'default'


def test_reads_that_do_not_wait_have_a_budget(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    for _ in range(60):
        unread(serenity, cursor='s1')
    assert serenity.post('/api/ships/me/unread', json={'cursor': 's1'}).status_code == 429
    clock[0] += 61
    assert serenity.post('/api/ships/me/unread', json={'cursor': 's1'}).status_code == 200
