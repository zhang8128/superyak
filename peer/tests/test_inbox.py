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


def test_advance_only_accepts_messages_in_the_ships_own_rooms(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    elsewhere = clients[2].post('/api/chats', json={'title': 'Not mine', 'member_ids': [users[3]['id']]}).json()['id']
    say(clients[2], elsewhere, 'x', 'secret room')
    hidden = max(e['id'] for e in app.state.store.events_since(0) if e['kind'] == 'chat.message')
    assert advance(serenity, hidden, cursor='s1').status_code == 400


def test_cursors_unused_for_thirty_days_are_pruned_when_a_new_one_is_made_except_the_furthest(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    say(clients[0], room, 'a', 'one')
    unread(serenity, cursor='old-session')
    event = unread(serenity, cursor='ahead')['messages'][0]['event_id']
    advance(serenity, event, cursor='ahead')
    clock[0] += 31 * 86400
    unread(serenity, cursor='new-session')
    with app.state.store.transaction() as db:
        names = {r['name'] for r in db.execute('SELECT name FROM read_cursors WHERE ship_id=?', (ship['id'],))}
    assert names == {'ahead', 'new-session'}


def test_installing_the_inbox_on_existing_data_never_replays_history(env, tmp_path):
    app, clients, users, clock, ship, serenity, room = setup(env)
    say(clients[0], room, 'a', 'posted before the inbox existed')
    store = app.state.store
    with store.transaction() as db:  # as if this station ran without the inbox until now
        db.execute('DROP TABLE inbox_meta')
    from superyak_peer.db import Store
    Store(store.data_dir, clock=store.clock)  # the next start installs the inbox onto existing data
    assert unread(serenity, cursor='first-ever')['messages'] == []
    say(clients[0], room, 'b', 'posted after')
    assert [m['body'] for m in unread(serenity, cursor='first-ever')['messages']] == ['posted after']


def test_a_ship_idle_for_a_month_never_replays_what_it_read(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    say(clients[0], room, 'a', 'read long ago')
    got = unread(serenity, cursor='sess-1')['messages']
    advance(serenity, got[-1]['event_id'], cursor='sess-1')
    clock[0] += 31 * 86400
    assert unread(serenity, cursor='sess-2')['messages'] == []


def test_cursors_per_ship_are_capped_and_the_furthest_is_kept(env):
    from superyak_peer.inbox import CURSORS_PER_SHIP
    app, clients, users, clock, ship, serenity, room = setup(env)
    say(clients[0], room, 'a', 'one')
    event = unread(serenity, cursor='furthest')['messages'][0]['event_id']
    advance(serenity, event, cursor='furthest')
    for n in range(CURSORS_PER_SHIP + 5):
        clock[0] += 2  # stay inside the read budget; the furthest cursor becomes the least recently used
        unread(serenity, cursor=f'n{n}')
    with app.state.store.transaction() as db:
        rows = {r['name']: r['position'] for r in db.execute('SELECT name, position FROM read_cursors WHERE ship_id=?', (ship['id'],))}
    assert len(rows) <= CURSORS_PER_SHIP and max(rows.values()) == event
    assert unread(serenity, cursor='brand-new')['messages'] == []


def test_advance_refuses_an_id_too_large_to_be_an_event(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    assert advance(serenity, 10 ** 30, cursor='s1').status_code == 400


def reply(client, room, cid, body, to):
    response = client.post(f'/api/chats/{room}/messages', json={'client_message_id': cid, 'body': body, 'reply_to': to})
    assert response.status_code == 201, response.text
    return response.json()


def test_a_reply_to_the_readers_own_post_is_flagged_replies_to_me(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    mine = say(serenity, room, 'a', 'my post')
    other = say(clients[0], room, 'b', 'someone elses post')
    to_mine = reply(clients[1], room, 'c', 'answer to the ship', mine['id'])
    to_other = reply(clients[1], room, 'd', 'answer to a person', other['id'])
    plain = say(clients[1], room, 'e', '@serenity hello')
    got = {m['message_id']: m for m in unread(serenity, cursor='k')['messages']}
    assert got[to_mine['id']]['replies_to_me'] is True
    assert 'replies_to_me' not in got[to_other['id']]
    assert 'replies_to_me' not in got[plain['id']] and got[plain['id']]['mentions_me'] is True
    assert 'replies_to_me' not in got[other['id']]


def test_a_reply_to_a_post_made_after_the_cursor_was_created_is_flagged(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    assert unread(serenity, cursor='k')['messages'] == []  # the cursor exists now
    mine = say(serenity, room, 'a', 'posted after the cursor')
    to_mine = reply(clients[0], room, 'b', 'answer', mine['id'])
    got = unread(serenity, cursor='k')['messages']
    assert [(m['message_id'], m.get('replies_to_me')) for m in got] == [(to_mine['id'], True)]


def test_the_readers_reply_to_its_own_post_is_not_in_its_unread(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    mine = say(serenity, room, 'a', 'my post')
    reply(serenity, room, 'b', 'my own follow up', mine['id'])
    assert unread(serenity, cursor='k')['messages'] == []


def test_a_watchers_cursor_never_sets_where_a_new_session_starts(env):
    """The kick (`<ship>-kick`) reads ahead of every session. If a new cursor started at the kick's position, a session
    started after a quiet spell would never see what arrived while no session ran (first-rail Task 13's report)."""
    app, clients, users, clock, ship, serenity, room = setup(env)
    say(clients[0], room, 'a', 'read by the last session')
    advance(serenity, unread(serenity, cursor='session-one')['messages'][-1]['event_id'], cursor='session-one')
    for n in range(3):
        say(clients[0], room, f'gap{n}', f'arrived while no session ran {n}')
    advance(serenity, unread(serenity, cursor='serenity-kick')['messages'][-1]['event_id'], cursor='serenity-kick')
    assert [m['body'] for m in unread(serenity, cursor='session-two')['messages']] == [
        'arrived while no session ran 0', 'arrived while no session ran 1', 'arrived while no session ran 2']


def test_a_ship_with_only_a_watchers_cursor_still_starts_new_sessions_without_replaying_history(env):
    """Passes on the old code too: it guards the fallback, failing if a watcher-only ship started at the epoch."""
    app, clients, users, clock, ship, serenity, room = setup(env)
    for n in range(3):
        say(clients[0], room, f'old{n}', f'old {n}')
    advance(serenity, unread(serenity, cursor='serenity-kick')['messages'][-1]['event_id'], cursor='serenity-kick')
    say(clients[0], room, 'new', 'new')
    assert [m['body'] for m in unread(serenity, cursor='first-session')['messages']] == ['new']
