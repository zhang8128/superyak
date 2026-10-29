"""Remote connector, Task 8: the four tools and their receipts (spec "The tools", "Receipts and revoking")."""
import json

from connector_support import connected, home, mcp, person, rpc  # noqa: F401

NO_SUCH = 'No such room.'
NOT_SHARED = "This room isn't shared with Claude. You can add it in Connected apps on your home."
MARKED = 'A member of this room keeps it away from cloud models.'
REMOTE = 'This room is on another home. This connector reads rooms on this home only.'
EPOCH = '1970-01-12T13:46:40Z'  # the test clock's 1,000,000.0 in UTC


def call(connected, tool, **arguments):
    """One tools/call through /mcp: the result, as Claude gets it."""
    answer = mcp(connected, rpc('tools/call', {'name': tool, 'arguments': arguments}), connected.tokens['access_token'])
    assert answer.status_code == 200, answer.text
    return answer.json()['result']


def ok(result):
    assert result['isError'] is False, result
    assert json.loads(result['content'][0]['text']) == result['structuredContent']
    return result['structuredContent']


def refused(result):
    assert result['isError'] is True and 'structuredContent' not in result, result
    return result['content'][0]['text']


def say(connected, room, text, who=None):
    return connected.store.send_message((who or connected.person)['id'], room, f'c-{text[:20]}-{room[:6]}', text)


def test_rooms_lists_the_granted_rooms_with_member_names(connected):
    andy = person(connected, 'andy@example.org', 'Andy Example')
    connected.store.create_room(connected.person['id'], 'Diary', [])  # Sam's, but not chosen
    shared = connected.store.add_participants(connected.person['id'], connected.rooms[1], [andy['id']])['id']
    connected.clock[0] += 60
    say(connected, connected.rooms[0], 'newest first')
    rooms = ok(call(connected, 'rooms'))['rooms']
    assert [room['title'] for room in rooms] == ['Care plan', 'earlier part of Lab notes']  # newest activity first
    first = rooms[0]
    assert first == {'room': connected.rooms[0], 'title': 'Care plan', 'members': ['Sam Example'],
                     'last_activity': '1970-01-12T13:47:40Z'}
    assert shared not in [room['room'] for room in rooms]  # the continuation wasn't chosen (D9)


def test_each_tool_reads_only_the_persons_granted_rooms(connected):
    andy = person(connected, 'andy@example.org', 'Andy Example')
    andys = connected.store.create_room(andy['id'], 'Andy alone', [])['id']
    diary = connected.store.create_room(connected.person['id'], 'Diary', [])['id']
    left = connected.store.create_room(andy['id'], 'Was shared', [connected.person['id']])['id']
    connected.store.remove_participant(andy['id'], left, connected.person['id'])
    assert refused(call(connected, 'read_room', room=andys)) == NO_SUCH
    assert refused(call(connected, 'read_room', room=left)) == NO_SUCH
    assert refused(call(connected, 'read_room', room=diary)) == NOT_SHARED
    assert refused(call(connected, 'read_room', room='nope')) == NO_SUCH
    assert ok(call(connected, 'read_room', room=connected.rooms[0]))['room'] == connected.rooms[0]


def test_a_remote_room_never_appears_and_is_refused(connected):
    assert refused(call(connected, 'read_room', room='peer-1:room-1')) == REMOTE
    assert all(':' not in room['room'] for room in ok(call(connected, 'rooms'))['rooms'])


def test_a_room_marked_after_consent_is_refused_on_the_next_call(connected):
    assert ok(call(connected, 'read_room', room=connected.rooms[0]))
    connected.store.mark_room(connected.person['id'], connected.rooms[0])
    assert refused(call(connected, 'read_room', room=connected.rooms[0])) == MARKED
    assert connected.rooms[0] not in [room['room'] for room in ok(call(connected, 'rooms'))['rooms']]


def test_a_continuation_after_consent_is_refused_until_added(connected):
    andy = person(connected, 'andy@example.org', 'Andy Example')
    say(connected, connected.rooms[0], 'before the add')
    later = connected.store.add_participants(connected.person['id'], connected.rooms[0], [andy['id']])['id']
    assert refused(call(connected, 'read_room', room=later)) == NOT_SHARED
    assert [m['text'] for m in ok(call(connected, 'read_room', room=connected.rooms[0]))['messages']] == ['before the add']


def test_rooms_groups_a_replaced_room_with_its_continuation(connected):
    """With "All my rooms", a replaced room comes right after the room that continues it, as one conversation."""
    from connector_support import allowed, exchange
    andy = person(connected, 'andy@example.org', 'Andy Example')
    later = connected.store.add_participants(connected.person['id'], connected.rooms[0], [andy['id']])['id']
    client, code = allowed(connected, rooms='*', state='st-all')
    connected.tokens = exchange(connected, client, code).json()
    rooms = ok(call(connected, 'rooms'))['rooms']
    at = [room['room'] for room in rooms].index(later)
    assert rooms[at + 1] == {'room': connected.rooms[0], 'title': 'earlier part of Care plan', 'members': ['Sam Example'],
                             'last_activity': rooms[at + 1]['last_activity']}
    assert rooms[at]['title'] == 'Care plan' and rooms[at]['members'] == ['Andy Example', 'Sam Example']


def test_all_my_rooms_covers_a_later_room_and_a_list_doesnt(connected):
    from connector_support import allowed, exchange
    client, code = allowed(connected, rooms='*', state='st-all')
    everything = exchange(connected, client, code).json()['access_token']
    new = connected.store.create_room(connected.person['id'], 'Made later', [])['id']
    marked = connected.store.create_room(connected.person['id'], 'Made later, marked', [])['id']
    connected.store.mark_room(connected.person['id'], marked)
    listed = [room['room'] for room in ok(call(connected, 'rooms'))['rooms']]
    assert new not in listed and refused(call(connected, 'read_room', room=new)) == NOT_SHARED
    connected.tokens = {'access_token': everything}
    listed = [room['room'] for room in ok(call(connected, 'rooms'))['rooms']]
    assert new in listed and marked not in listed
    assert refused(call(connected, 'read_room', room=marked)) == MARKED


def test_no_username_or_id_leaks(connected):
    """D11: no username, person, owner or peer id leaves the home; the only ids are room and message ids."""
    andy = person(connected, 'andy@example.org', 'Andy Example')
    say(connected, connected.rooms[0], 'a note from sam')
    say(connected, connected.rooms[1], 'before andy')
    shared = connected.store.add_participants(connected.person['id'], connected.rooms[1], [andy['id']])['id']
    say(connected, shared, 'after andy', andy)
    from connector_support import allowed, exchange
    client, code = allowed(connected, rooms='*', state='st-all')
    connected.tokens = exchange(connected, client, code).json()
    seen = json.dumps([ok(call(connected, 'rooms')), ok(call(connected, 'read_room', room=connected.rooms[0])),
                       ok(call(connected, 'read_room', room=shared))])
    for secret in ('sam@example.org', 'andy@example.org', connected.person['id'], andy['id']):
        assert secret not in seen, secret


def test_shapes_and_iso_times(connected):
    message = say(connected, connected.rooms[0], 'hello')
    read = ok(call(connected, 'read_room', room=connected.rooms[0]))
    assert set(read) == {'room', 'title', 'brief', 'messages', 'total', 'first_position', 'seq', 'more'}
    assert read['messages'] == [{'id': message['id'], 'author': 'Sam Example', 'author_kind': 'person', 'time': EPOCH,
                                 'text': 'hello', 'reply_to': None}]
    assert read['brief'] is None and read['total'] == 1 and read['first_position'] == 0 and read['more'] is False
