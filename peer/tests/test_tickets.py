"""Run tickets: the station decides a run's mode just before it starts and records it (spec A, section 4)."""
from fastapi.testclient import TestClient


def ship_client(app, key):
    return TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver', 'authorization': f'Bearer {key}'})


def docked(store, owner_id, name='serenity'):
    started = store.start_docking(name, 'test-host')
    ship = store.confirm_docking(owner_id, started['id'], started['code'])
    return ship, store.docking_status(started['id'], started['secret'])['key']


def setup(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id'], users[1]['id']]}).json()['id']
    return app, clients, users, clock, ship, ship_client(app, key), room


def say(client, room, cid, body):
    response = client.post(f'/api/chats/{room}/messages', json={'client_message_id': cid, 'body': body})
    assert response.status_code == 201, response.text
    return response.json()


def ticket(ship, message_id):
    return ship.post('/api/ships/me/tickets', json={'message_id': message_id})


def test_the_owners_mention_gets_a_build_ticket_and_everyone_else_read(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    owner = say(clients[0], room, 'a', '@serenity add notes')
    other = say(clients[1], room, 'b', '@serenity what is this?')
    unmentioned = say(clients[0], room, 'c', 'just talking')
    selfpost = say(serenity, room, 'd', '@serenity talking to myself')
    got = {m['id']: ticket(serenity, m['id']).json() for m in (owner, other, unmentioned, selfpost)}
    assert [(got[m['id']]['mode'], got[m['id']]['basis']) for m in (owner, other, unmentioned, selfpost)] == [
        ('build', 'owner'), ('read', 'none'), ('read', 'none'), ('read', 'none')]
    assert got[owner['id']]['root_id'] == users[0]['id'] and got[owner['id']]['footer'] == 'Builder for Patient (owner)'
    assert got[other['id']]['footer'] == '' and got[other['id']]['root_id'] is None
    assert got[owner['id']]['chain'] == [] and got[owner['id']]['instructions'] == [] and got[owner['id']]['hops'] == 0


def test_a_resident_ship_only_ever_reads_and_needs_no_mention(env):
    app, clients, users, clock = env
    store = app.state.store
    odo = store.create_station_ship('odo', 'Odo')
    client = ship_client(app, store.issue_ship_key(odo['id']))
    room = clients[0].post('/api/chats', json={'title': 'Quiet', 'member_ids': [odo['id']]}).json()['id']
    asked = say(clients[0], room, 'a', 'hello, anyone?')
    got = ticket(client, asked['id'])
    assert got.status_code == 200 and (got.json()['mode'], got.json()['basis']) == ('read', 'none')


def test_retries_get_the_same_ticket_until_it_is_finished_then_409(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    owner = say(clients[0], room, 'a', '@serenity add notes')
    first = ticket(serenity, owner['id']).json()
    assert ticket(serenity, owner['id']).json()['id'] == first['id']
    done = serenity.post(f'/api/ships/me/tickets/{first["id"]}/finish', json={})
    assert done.status_code == 200 and done.json()['status'] == 'finished'
    assert serenity.post(f'/api/ships/me/tickets/{first["id"]}/finish', json={}).status_code == 200
    assert ticket(serenity, owner['id']).status_code == 409


def test_a_ticket_left_running_counts_as_finished_after_two_hours(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    owner = say(clients[0], room, 'a', '@serenity add notes')
    first = ticket(serenity, owner['id']).json()
    clock[0] += 7199
    assert ticket(serenity, owner['id']).json()['id'] == first['id']
    clock[0] += 2
    assert ticket(serenity, owner['id']).status_code == 409


def test_only_room_members_and_only_ship_keys_get_tickets(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    elsewhere = clients[2].post('/api/chats', json={'title': 'Private', 'member_ids': []}).json()['id']
    hidden = say(clients[2], elsewhere, 'a', 'not for ships')
    assert ticket(serenity, hidden['id']).status_code == 404
    assert ticket(serenity, 'no-such-message').status_code == 404
    assert ticket(serenity, None).status_code == 400
    owner = say(clients[0], room, 'b', '@serenity add notes')
    assert clients[0].post('/api/ships/me/tickets', json={'message_id': owner['id']}).status_code == 403
    first = ticket(serenity, owner['id']).json()
    other, other_key = docked(app.state.store, users[1]['id'], 'defiant')
    assert ship_client(app, other_key).post(f'/api/ships/me/tickets/{first["id"]}/finish', json={}).status_code == 404


def test_the_footer_never_mentions_anyone(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    assert clients[0].patch('/api/me', json={'name': '@odo\nboss'}).status_code == 200
    owner = say(clients[0], room, 'a', '@serenity add notes')
    footer = ticket(serenity, owner['id']).json()['footer']
    assert '@' not in footer and '\n' not in footer and footer == 'Builder for (at)odo boss (owner)'


def post(client, room, cid, body, ticket_id=None):
    payload = {'client_message_id': cid, 'body': body}
    if ticket_id is not None:
        payload['ticket_id'] = ticket_id
    return client.post(f'/api/chats/{room}/messages', json=payload)


def sources(client, room):
    return {m['body']: m['source'] for m in client.get(f'/api/chats/{room}').json()['messages']}


def test_a_reply_with_its_ticket_is_labelled_as_that_run(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    owner = say(clients[0], room, 'a', '@serenity add notes')
    other = say(clients[1], room, 'b', '@serenity what is this?')
    build, read = ticket(serenity, owner['id']).json(), ticket(serenity, other['id']).json()
    assert post(serenity, room, f'reply-{owner["id"]}', 'Added notes', build['id']).status_code == 201
    assert post(serenity, room, f'reply-{other["id"]}', 'It is a station', read['id']).status_code == 201
    assert post(serenity, room, 'post-1', 'Hello from my session').status_code == 201
    got = sources(clients[0], room)
    assert got['Added notes'] == {'kind': 'run', 'mode': 'build', 'basis': 'owner', 'root_name': 'Patient', 'answering': owner['id']}
    assert got['It is a station'] == {'kind': 'run', 'mode': 'read', 'basis': 'none', 'root_name': None, 'answering': other['id']}
    assert got['Hello from my session'] == {'kind': 'post'}
    assert got['@serenity add notes'] is None


def test_a_ticket_labels_one_message_only_and_never_a_finished_or_foreign_one(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    owner = say(clients[0], room, 'a', '@serenity add notes')
    build = ticket(serenity, owner['id']).json()
    assert post(serenity, room, 'r1', 'first', build['id']).status_code == 201
    assert post(serenity, room, 'r1', 'first', build['id']).status_code == 201  # the same post again is idempotent
    assert post(serenity, room, 'r2', 'second', build['id']).status_code == 409
    second = say(clients[0], room, 'b', '@serenity more notes')
    later = ticket(serenity, second['id']).json()
    serenity.post(f'/api/ships/me/tickets/{later["id"]}/finish', json={})
    assert post(serenity, room, 'r3', 'too late', later['id']).status_code == 409
    other_room = clients[0].post('/api/chats', json={'title': 'Elsewhere', 'member_ids': [ship['id']]}).json()['id']
    third = say(clients[0], room, 'c', '@serenity again')
    wrong_room = ticket(serenity, third['id']).json()
    assert post(serenity, other_room, 'r4', 'misplaced', wrong_room['id']).status_code == 409
    assert post(clients[0], room, 'r5', 'a person cannot use a ticket', wrong_room['id']).status_code == 409
    assert 'second' not in sources(clients[0], room) and 'too late' not in sources(clients[0], room)


def test_a_remote_rooms_messages_never_carry_a_label(env, monkeypatch):
    """A paired peer's payload is passed through for ':' rooms; a label in it must never reach a reader."""
    app, clients, users, clock = env
    store = app.state.store
    forged = {'id': 'peer1:room1', 'title': 'Remote', 'messages': [
        {'id': 'x', 'body': 'hi', 'source': {'kind': 'run', 'mode': 'build', 'basis': 'owner', 'root_name': 'Andy'}}]}
    monkeypatch.setattr(type(store), 'remote_room', lambda self, actor, key: forged)
    assert store.get_room(users[0]['id'], 'peer1:room1')['messages'][0]['source'] is None


def test_a_reply_prefix_without_a_ticket_is_not_a_run(env):
    app, clients, users, clock, ship, serenity, room = setup(env)
    owner = say(clients[0], room, 'a', '@serenity add notes')
    assert post(serenity, room, f'reply-{owner["id"]}', 'Pretending to be a run').status_code == 201
    assert sources(clients[0], room)['Pretending to be a run'] == {'kind': 'post'}


def test_an_owner_mention_builds_for_exactly_a_day_then_reads_old(env):
    """Fresh owner mentions R1, R2, R9: exactly 86,400 s still builds; just after, read with basis old, and a reply
    under that ticket is labelled a read-only run with basis old."""
    app, clients, users, clock, ship, serenity, room = setup(env)
    edge = say(clients[0], room, 'a', '@serenity add notes')
    late = say(clients[0], room, 'b', '@serenity add more notes')
    clock[0] += 86400
    got = ticket(serenity, edge['id']).json()
    assert (got['mode'], got['basis']) == ('build', 'owner')
    clock[0] += 0.5
    got = ticket(serenity, late['id']).json()
    assert (got['mode'], got['basis'], got['root_id'], got['footer']) == ('read', 'old', None, '')
    assert post(serenity, room, 'reply-late', 'That was a day ago', got['id']).status_code == 201
    assert sources(serenity, room)['That was a day ago'] == {  # as the ship: a person's login lasts exactly a day
        'kind': 'run', 'mode': 'read', 'basis': 'old', 'root_name': None, 'answering': late['id']}


def test_an_owner_mention_with_an_unusable_created_reads_old_and_never_raises(env):
    """Fresh owner mentions R4: infinity and text both read old with status 200."""
    app, clients, users, clock, ship, serenity, room = setup(env)
    store = app.state.store
    for cid, value in (('a', float('inf')), ('b', 'abc')):
        sent = say(clients[0], room, cid, f'@serenity add {cid}')
        with store.transaction() as db:
            db.execute('UPDATE messages SET created=? WHERE id=?', (value, sent['id']))
        got = ticket(serenity, sent['id'])
        assert got.status_code == 200, got.text
        assert (got.json()['mode'], got.json()['basis']) == ('read', 'old')


def test_an_owner_mention_from_the_far_future_reads_old_but_a_minute_ahead_builds(env):
    """Fresh owner mentions R4: within a day either side."""
    app, clients, users, clock, ship, serenity, room = setup(env)
    store = app.state.store
    far, near = say(clients[0], room, 'a', '@serenity far'), say(clients[0], room, 'b', '@serenity near')
    with store.transaction() as db:
        db.execute('UPDATE messages SET created=? WHERE id=?', (clock[0] + 90000, far['id']))
        db.execute('UPDATE messages SET created=? WHERE id=?', (clock[0] + 60, near['id']))
    assert (lambda g: (g['mode'], g['basis']))(ticket(serenity, far['id']).json()) == ('read', 'old')
    assert (lambda g: (g['mode'], g['basis']))(ticket(serenity, near['id']).json()) == ('build', 'owner')


def test_a_running_build_ticket_sent_again_after_a_day_is_the_same_ticket(env):
    """Fresh owner mentions R5: the decision is made at issue only."""
    app, clients, users, clock, ship, serenity, room = setup(env)
    owner = say(clients[0], room, 'a', '@serenity add notes')
    clock[0] += 84600
    first = ticket(serenity, owner['id']).json()
    assert (first['mode'], first['basis']) == ('build', 'owner')
    clock[0] += 3600
    again = ticket(serenity, owner['id']).json()
    assert (again['id'], again['mode'], again['basis']) == (first['id'], 'build', 'owner')


def test_a_non_owners_old_mention_is_read_with_basis_none(env):
    """Fresh owner mentions R5: only the owner's mention is bounded."""
    app, clients, users, clock, ship, serenity, room = setup(env)
    other = say(clients[1], room, 'a', '@serenity what is this?')
    clock[0] += 172800
    got = ticket(serenity, other['id']).json()
    assert (got['mode'], got['basis']) == ('read', 'none')
