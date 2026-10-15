"""Room briefs: the context a room's owner writes, and chooses to carry into the next room
(docs/superpowers/specs/2026-10-08-room-brief-design.md)."""
import json
from fastapi.testclient import TestClient


def ship_client(app, key):
    return TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver', 'authorization': f'Bearer {key}'})


def docked(store, owner_id, name):
    started = store.start_docking(name, 'test-host')
    ship = store.confirm_docking(owner_id, started['id'], started['code'])
    return ship, store.docking_status(started['id'], started['secret'])['key']


def new_room(client, *members, title='City of AI'):
    response = client.post('/api/chats', json={'title': title, 'member_ids': [m['id'] for m in members]})
    assert response.status_code == 201, response.text
    return response.json()['id']


def put_brief(client, room, body, revision):
    return client.put(f'/api/chats/{room}/brief', json={'body': body, 'revision': revision})


def brief_row(app, room):
    """(body, revision) as stored, or None: a removal keeps the row."""
    with app.state.store.transaction() as db:
        row = db.execute('SELECT body, revision FROM room_briefs WHERE room_id=?', (room,)).fetchone()
    return (row['body'], row['revision']) if row else None


def test_only_the_owner_writes_the_brief(env):
    """Create, change and remove: a member and a ship key are refused each one, and nothing is written."""
    app, clients, users, clock = env
    patient, doctor, organizer, family = clients
    ship, key = docked(app.state.store, users[0]['id'], 'serenity')
    serenity = ship_client(app, key)
    room = new_room(patient, users[1], ship)

    def refused_ship_key(body, revision):
        """403 at the route itself: the detail shows it is the person-only route, not the owner check."""
        response = serenity.put(f'/api/chats/{room}/brief', json={'body': body, 'revision': revision})
        return response.status_code == 403 and response.json()['error'] == 'Ship keys cannot use this route'

    assert put_brief(doctor, room, 'Mine.', 0).status_code == 403  # a member cannot write the first brief
    assert brief_row(app, room) is None
    assert refused_ship_key('Mine.', 0) and refused_ship_key('', 0)
    assert brief_row(app, room) is None
    saved = put_brief(patient, room, 'Decisions D1-D9. Rio Grande builds the brief.', 0)
    assert saved.status_code == 200, saved.text
    assert saved.json() == {'body': 'Decisions D1-D9. Rio Grande builds the brief.', 'revision': 1, 'author_id': users[0]['id'],
                            'author_name': 'Patient', 'author_kind': 'person', 'author_username': 'patient', 'updated': 1000000.0, 'carried_from': None}
    kept = ('Decisions D1-D9. Rio Grande builds the brief.', 1)
    for body in ('Mine now.', ''):  # a change, then a removal
        assert put_brief(doctor, room, body, 1).status_code == 403, body
        assert brief_row(app, room) == kept
        assert refused_ship_key(body, 1), body
        assert brief_row(app, room) == kept
    assert put_brief(organizer, room, 'Mine now.', 1).status_code == 404  # not a member
    assert put_brief(patient, 'f' * 64 + ':' + room, 'Remote.', 0).status_code == 404  # a remote room's id
    no_csrf = patient.put(f'/api/chats/{room}/brief', json={'body': 'Mine now.', 'revision': 1}, headers={'x-csrf-token': ''})
    assert no_csrf.status_code == 403
    assert brief_row(app, room) == kept


def test_a_stale_or_non_int_revision_gets_409(env):
    app, clients, users, clock = env
    patient = clients[0]
    room = new_room(patient, users[1])
    assert put_brief(patient, room, 'First.', 1).status_code == 409  # there is no brief yet: its revision is 0
    assert put_brief(patient, room, 'First.', 0).status_code == 200
    assert put_brief(patient, room, 'From a stale tab.', 0).status_code == 409
    for bad in (True, '1', 1.0, None):  # True == 1 and 1.0 == 1 in Python, so each needs the type check
        assert put_brief(patient, room, 'Odd.', bad).status_code == 409, bad
    assert patient.put(f'/api/chats/{room}/brief', json={'body': 'No revision.'}).status_code == 409
    assert brief_row(app, room) == ('First.', 1)


def test_the_body_is_up_to_4000_characters_of_valid_text(env):
    app, clients, users, clock = env
    patient = clients[0]
    room = new_room(patient)
    too_long = put_brief(patient, room, 'x' * 4001, 0)
    assert too_long.status_code == 400 and too_long.json()['error'] == 'A brief is at most 4,000 characters'
    assert put_brief(patient, room, 'a NUL\x00inside', 0).status_code == 400
    lone = patient.put(f'/api/chats/{room}/brief', content=json.dumps({'body': 'bad\ud800', 'revision': 0}),
                       headers={'content-type': 'application/json'})
    assert lone.status_code == 400
    for bad in (None, 5, ['x'], {'x': 1}):
        assert put_brief(patient, room, bad, 0).status_code == 400, bad
    assert brief_row(app, room) is None
    accepted = put_brief(patient, room, 'x' * 4000, 0)
    assert accepted.status_code == 200 and accepted.json()['body'] == 'x' * 4000


def test_the_limit_counts_characters_not_bytes_or_utf16_units(env):
    """Review focus: unicode at the 4,000 boundary."""
    app, clients, users, clock = env
    patient = clients[0]
    room = new_room(patient)
    assert put_brief(patient, room, '😀' * 4001, 0).status_code == 400
    assert put_brief(patient, room, chr(0xe9) * 4000, 0).status_code == 200  # é, one code point: 8,000 bytes
    assert put_brief(patient, room, '😀' * 4000, 1).status_code == 200     # 16,000 bytes, 8,000 UTF-16 units
    accented = 'e' + chr(0x301)  # two code points: a letter and a combining accent, shown as one character
    assert put_brief(patient, room, accented * 2000, 2).status_code == 200  # 4,000 code points
    assert put_brief(patient, room, accented * 2000 + '!', 3).status_code == 400
    assert brief_row(app, room) == (accented * 2000, 3)


def test_revisions_only_go_up_and_a_removal_keeps_the_row(env):
    app, clients, users, clock = env
    patient = clients[0]
    room = new_room(patient, users[1])
    assert put_brief(patient, room, 'First.', 0).json()['revision'] == 1
    removed = put_brief(patient, room, '  \n\t ', 1)
    assert removed.status_code == 200 and removed.json() is None
    assert brief_row(app, room) == ('', 2)
    assert put_brief(patient, room, 'Again.', 0).status_code == 409  # a tab that saw no brief at all
    assert put_brief(patient, room, 'Again.', 2).json()['revision'] == 3
    assert put_brief(patient, room, 'From the first tab.', 1).status_code == 409
    assert brief_row(app, room) == ('Again.', 3)



def brief_of(client, room):
    response = client.get(f'/api/chats/{room}')
    assert response.status_code == 200, response.text
    return response.json()['brief']


def add_members(client, room, *members, **extra):
    return client.post(f'/api/chats/{room}/participants', json={'member_ids': [m['id'] for m in members], **extra})


def test_get_returns_the_brief_to_members_and_null_when_there_is_none(env):
    app, clients, users, clock = env
    patient, doctor, organizer = clients[:3]
    ship, key = docked(app.state.store, users[0]['id'], 'serenity')
    room = new_room(patient, users[1], ship)
    fresh = doctor.get(f'/api/chats/{room}').json()
    assert fresh['brief'] is None and fresh['brief_revision'] == 0
    put_brief(patient, room, 'Purpose: the city of AI.', 0)
    clock[0] += 60
    expected = {'body': 'Purpose: the city of AI.', 'revision': 1, 'author_id': users[0]['id'], 'author_name': 'Patient', 'author_kind': 'person', 'author_username': 'patient',
                'updated': 1000000.0, 'carried_from': None}
    assert brief_of(doctor, room) == expected and brief_of(patient, room) == expected
    assert ship_client(app, key).get(f'/api/chats/{room}').json()['brief'] == expected
    assert organizer.get(f'/api/chats/{room}').status_code == 404
    put_brief(patient, room, '', 1)
    removed = doctor.get(f'/api/chats/{room}').json()
    assert removed['brief'] is None and removed['brief_revision'] == 2


def test_the_brief_authors_name_is_one_safe_line(env):
    app, clients, users, clock = env
    room = new_room(clients[0], users[1])
    put_brief(clients[0], room, 'Plan.', 0)
    with app.state.store.transaction() as db:
        db.execute('UPDATE users SET name=? WHERE id=?', ('Patient\n@serenity\x1b[2J', users[0]['id']))
    assert brief_of(clients[1], room)['author_name'] == 'Patient (at)serenity [2J'


def test_room_summaries_carry_no_brief(env):
    app, clients, users, clock = env
    room = new_room(clients[0], users[1])
    put_brief(clients[0], room, 'A plan only the room shows.', 0)
    assert all('brief' not in r and 'brief_revision' not in r for r in clients[1].get('/api/chats').json())
    home = clients[1].get('/api/home')
    assert all('brief' not in r for r in home.json()['chats']) and 'A plan only the room shows.' not in home.text


def test_carrying_copies_the_brief_into_the_new_room_and_never_its_messages(env):
    app, clients, users, clock = env
    patient, doctor, organizer = clients[:3]
    room = new_room(patient, users[1])
    patient.post(f'/api/chats/{room}/messages', json={'client_message_id': 'a', 'body': 'An old secret for the first audience.'})
    put_brief(patient, room, 'D1-D9 are decided.', 0)
    put_brief(patient, room, 'D1-D9 are decided. Rio Grande builds the brief.', 1)
    clock[0] += 60
    response = add_members(patient, room, users[2], carry_brief=2)
    assert response.status_code == 201, response.text
    new = response.json()['id']
    got = organizer.get(f'/api/chats/{new}').json()
    assert got['brief'] == {'body': 'D1-D9 are decided. Rio Grande builds the brief.', 'revision': 1, 'author_id': users[0]['id'],
                            'author_name': 'Patient', 'author_kind': 'person', 'author_username': 'patient', 'updated': 1000060.0, 'carried_from': room}
    assert got['brief_revision'] == 1 and got['messages'] == []
    assert 'old secret' not in organizer.get(f'/api/chats/{new}').text
    assert organizer.get(f'/api/chats/{room}').status_code == 404
    assert brief_of(doctor, room)['revision'] == 2  # the old room keeps its own brief
    edited = put_brief(patient, new, 'Edited in the new room.', 1).json()
    assert edited['revision'] == 2 and edited['carried_from'] is None  # the carried note dates the carried revision only


def test_without_carry_the_new_room_has_no_brief(env):
    app, clients, users, clock = env
    patient, organizer = clients[0], clients[2]
    for extra in ({}, {'carry_brief': None}):  # a fresh room each time: a replaced room takes no more adds (work board 8.4)
        room = new_room(patient, users[1])
        patient.post(f'/api/chats/{room}/messages', json={'client_message_id': 'a', 'body': 'An old secret.'})
        put_brief(patient, room, 'Plan.', 0)
        response = add_members(patient, room, users[2], **extra)
        assert response.status_code == 201, response.text
        got = organizer.get(f'/api/chats/{response.json()["id"]}').json()
        assert got['brief'] is None and got['brief_revision'] == 0 and got['messages'] == []
    room = new_room(patient, users[1])
    put_brief(patient, room, 'Plan.', 0)
    put_brief(patient, room, '', 1)
    removed = add_members(patient, room, users[2], carry_brief=2)  # a removed brief leaves nothing to carry
    assert removed.status_code == 201 and brief_of(organizer, removed.json()['id']) is None


def test_a_stale_carry_gets_409_and_anything_but_null_or_an_int_gets_400(env):
    app, clients, users, clock = env
    patient, organizer = clients[0], clients[2]
    room = new_room(patient, users[1])
    put_brief(patient, room, 'Plan.', 0)
    before = len(patient.get('/api/chats').json())
    for stale in (0, 2):
        assert add_members(patient, room, users[2], carry_brief=stale).status_code == 409, stale
    for bad in (True, '1', 1.0, [1], {'revision': 1}):
        assert add_members(patient, room, users[2], carry_brief=bad).status_code == 400, bad
    assert len(patient.get('/api/chats').json()) == before and organizer.get('/api/chats').json() == []


def test_a_brief_changed_after_the_dialog_opened_is_never_carried(env):
    """Review focus: the owner saw revision 1 in the dialog; another tab then wrote what the new member must not see."""
    app, clients, users, clock = env
    patient, organizer = clients[0], clients[2]
    room = new_room(patient, users[1])
    put_brief(patient, room, 'Plan for everyone.', 0)
    seen = brief_of(patient, room)['revision']
    put_brief(patient, room, 'Plan for everyone. Private: the doctor is leaving.', seen)
    assert add_members(patient, room, users[2], carry_brief=seen).status_code == 409
    assert organizer.get('/api/chats').json() == []
    assert 'leaving' not in organizer.get('/api/home').text


def test_removing_a_member_keeps_the_room_and_its_brief(env):
    app, clients, users, clock = env
    patient, doctor, family = clients[0], clients[1], clients[3]
    room = new_room(patient, users[1], users[3])
    put_brief(patient, room, 'Plan.', 0)
    assert patient.delete(f'/api/chats/{room}/participants/{users[3]["id"]}').status_code == 200
    assert brief_of(patient, room)['body'] == 'Plan.' and brief_of(doctor, room)['body'] == 'Plan.'
    assert family.get(f'/api/chats/{room}').status_code == 404


def test_a_live_ship_key_in_a_brief_is_refused_and_nothing_is_written(env):
    app, clients, users, clock = env
    patient = clients[0]
    ship, key = docked(app.state.store, users[0]['id'], 'serenity')
    room = new_room(patient, ship)
    assert put_brief(patient, room, 'Plan.', 0).status_code == 200
    refused = put_brief(patient, room, f'Plan. The key is "{key}"', 1)
    assert refused.status_code == 422
    assert key not in refused.text and 'brief' in refused.json()['error'] and 'ship key' in refused.json()['error']
    assert brief_row(app, room) == ('Plan.', 1)
    other = new_room(patient, ship, title='Other')
    assert put_brief(patient, other, f'Bearer {key}', 0).status_code == 422
    assert brief_row(app, other) is None


def test_a_revoked_ship_key_in_a_brief_saves_normally(env):
    app, clients, users, clock = env
    ship, key = docked(app.state.store, users[0]['id'], 'serenity')
    room = new_room(clients[0], ship)
    app.state.store.revoke_presented_key(key)
    assert put_brief(clients[0], room, f'old, revoked: {key}', 0).status_code == 200
    assert brief_row(app, room) == (f'old, revoked: {key}', 1)


def test_the_message_refusal_keeps_its_wording(env):
    app, clients, users, clock = env
    ship, key = docked(app.state.store, users[0]['id'], 'serenity')
    room = new_room(clients[0], ship)
    refused = clients[0].post(f'/api/chats/{room}/messages', json={'client_message_id': 'a', 'body': key})
    assert refused.status_code == 422
    assert refused.json()['error'] == ('This message contains a live ship key, so it was not posted. Treat that key as '
                                       'exposed: its ship should revoke it and dock again.')
