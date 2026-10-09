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
                            'author_name': 'Patient', 'updated': 1000000.0, 'carried_from': None}
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


def test_saving_a_brief_records_no_mention_and_posts_nothing(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'], 'serenity')
    room = new_room(clients[0], users[1], ship)
    assert put_brief(clients[0], room, '@serenity and @doctor: read the plan.', 0).status_code == 200
    assert store.mentions(ship['id']) == [] and store.mentions(users[1]['id']) == []
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM messages WHERE room_id=?', (room,)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM events WHERE kind='chat.message'").fetchone()[0] == 0
