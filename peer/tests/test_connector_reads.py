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


def test_the_text_is_structured_contents_json_byte_for_byte(connected):
    """The section 2 re-check's nit 2: with real room text, not ASCII, the text holds the characters as sent, not
    escaped, and equals structuredContent's JSON exactly."""
    say(connected, connected.rooms[0], 'Zo\u00eb \U0001f642 "quoted" back\\slash')
    result = call(connected, 'read_room', room=connected.rooms[0])
    text = result['content'][0]['text']
    assert 'Zo\u00eb \U0001f642' in text
    assert text == json.dumps(result['structuredContent'], ensure_ascii=False, separators=(',', ':'))


def test_shapes_and_iso_times(connected):
    message = say(connected, connected.rooms[0], 'hello')
    read = ok(call(connected, 'read_room', room=connected.rooms[0]))
    assert set(read) == {'room', 'title', 'brief', 'messages', 'total', 'first_position', 'seq', 'more'}
    assert read['messages'] == [{'id': message['id'], 'author': 'Sam Example', 'author_kind': 'person', 'time': EPOCH,
                                 'text': 'hello', 'reply_to': None}]
    assert read['brief'] is None and read['total'] == 1 and read['first_position'] == 0 and read['more'] is False


# ---- search and fetch ----

DOT = ' \u00b7 '  # the separator in a result's title: room title, author, date


def remote_member(connected, room, name='Remy Remote', contact='remote_remy'):
    """A member on a paired home, as federation leaves one: a peer, its contact, and the contact in the room."""
    with connected.store.transaction() as db:
        db.execute("INSERT OR IGNORE INTO peers(peer_id, card, paired) VALUES('peer-remy', '{}', 1)")
        db.execute("INSERT OR IGNORE INTO remote_contacts VALUES(?, 'peer-remy', 'u-remy', ?)", (contact, name))
        db.execute('INSERT OR IGNORE INTO remote_room_members VALUES(?, ?)', (room, contact))
    return contact


def remote_says(connected, room, text, author='peer-remy:u-remy'):
    """A paired home's message as federation stores one: its author is `<peer>:<user>` (federation.py:881), never the
    contact's own id (the reader's must-fix 2: a fixture in another shape passed on fiction)."""
    message = f'pm-{len(text)}-{text[:12]}-{room[:6]}'
    with connected.store.transaction() as db:
        db.execute('INSERT INTO peer_messages VALUES(?,?,?,?,?,1,?)',
                   (message, room, author, f'c-{message}', text, connected.clock[0]))
        db.execute("INSERT INTO events(kind, resource_id, resource_version, payload, created) VALUES('chat.message', ?, 1, "
                   "json_object('message_id', ?, 'author_id', ?), ?)", (room, message, author, connected.clock[0]))
    return message


def test_search_bounds_and_escapes(connected):
    for query in ('', 'x' * 201, 7, None):
        assert refused(call(connected, 'search', **({'query': query} if query is not None else {})))
    plain = say(connected, connected.rooms[0], 'plain text')
    connected.clock[0] += 1
    percent = say(connected, connected.rooms[0], '100% done')
    connected.clock[0] += 1
    under = say(connected, connected.rooms[1], 'snake_case here')
    assert [r['id'] for r in ok(call(connected, 'search', query='%'))['results']] == [percent['id']]
    assert [r['id'] for r in ok(call(connected, 'search', query='_'))['results']] == [under['id']]
    assert [r['id'] for r in ok(call(connected, 'search', query='E'))['results']] == [under['id'], percent['id'], plain['id']]
    for n in range(25):
        connected.clock[0] += 1
        say(connected, connected.rooms[0], f'many {n:02d}')
    found = ok(call(connected, 'search', query='many'))['results']
    assert len(found) == 20 and found[0]['title'].endswith(DOT.join(['', 'Sam Example', '1970-01-12']))
    assert set(found[0]) == {'id', 'title', 'url'}
    assert all('many' not in r['url'] for r in found)  # the url never carries the query


def test_search_matches_non_ascii_exactly(connected):
    """SQLite's LIKE folds ASCII case only, which is enough for phase 1: non-ASCII matches exactly as written."""
    for text in ('\u0412\u0441\u0442\u0440\u0435\u0447\u0430 at noon', 'smile \U0001f642', 'Zo\u00eb wrote'):
        say(connected, connected.rooms[0], text)
        connected.clock[0] += 1
    for query, count in (('\u0412\u0441\u0442\u0440\u0435\u0447\u0430', 1), ('\U0001f642', 1), ('Zo\u00eb', 1),
                         ('ZOE', 0), ('ZO\u00cb', 0), ('zo\u00eb', 1)):
        assert len(ok(call(connected, 'search', query=query))['results']) == count, query


def test_search_is_one_statement(connected, monkeypatch):
    """Store calls hold the process lock, so search is one bounded SQL statement, never a loop over rooms."""
    import sqlite3
    say(connected, connected.rooms[0], 'needle one')
    say(connected, connected.rooms[1], 'needle two')
    statements, connect = [], sqlite3.connect

    def traced(*args, **kwargs):
        db = connect(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db
    monkeypatch.setattr(sqlite3, 'connect', traced)
    assert len(ok(call(connected, 'search', query='needle'))['results']) == 2
    searching = [s for s in statements if 'LIKE' in s.upper() and 'ESCAPE' in s.upper()]
    assert len(searching) == 1 and 'LIMIT 20' in searching[0]
    assert not [s for s in statements if 'FROM messages WHERE room_id' in s]  # no read of a whole room


def test_search_reads_only_the_grants_rooms(connected):
    andy = person(connected, 'andy@example.org', 'Andy Example')
    other = connected.store.create_room(andy['id'], 'Andy alone', [])['id']
    diary = connected.store.create_room(connected.person['id'], 'Diary', [])['id']
    say(connected, other, 'secret needle', andy)
    say(connected, diary, 'diary needle')
    shared = say(connected, connected.rooms[0], 'shared needle')
    assert [r['id'] for r in ok(call(connected, 'search', query='needle'))['results']] == [shared['id']]


def test_fetch_returns_two_before_and_two_after(connected):
    ids = []
    for n in range(7):
        connected.clock[0] += 1
        ids.append(say(connected, connected.rooms[0], f'line {n}')['id'])
    got = ok(call(connected, 'fetch', id=ids[3]))
    assert set(got) == {'id', 'title', 'text', 'url'} and got['id'] == ids[3]
    lines = [json.loads(line) for line in got['text'].split('\n')]
    assert [line['id'] for line in lines] == ids[1:6]
    assert set(lines[0]) == {'id', 'author', 'author_kind', 'time', 'text', 'reply_to'}
    assert got['title'] == DOT.join(['Care plan', 'Sam Example', '1970-01-12'])
    edge = [json.loads(line)['id'] for line in ok(call(connected, 'fetch', id=ids[0]))['text'].split('\n')]
    assert edge == ids[:3]
    assert refused(call(connected, 'fetch', id='nope')) == NO_SUCH


def test_fetch_refuses_a_message_in_a_room_it_cant_read(connected):
    andy = person(connected, 'andy@example.org', 'Andy Example')
    other = connected.store.create_room(andy['id'], 'Andy alone', [])['id']
    diary = connected.store.create_room(connected.person['id'], 'Diary', [])['id']
    assert refused(call(connected, 'fetch', id=say(connected, other, 'not yours', andy)['id'])) == NO_SUCH
    assert refused(call(connected, 'fetch', id=say(connected, diary, 'not shared')['id'])) == NOT_SHARED


def test_search_and_fetch_urls(connected):
    message = say(connected, connected.rooms[0], 'find me')
    found = ok(call(connected, 'search', query='find me'))['results'][0]
    assert found['url'] == 'https://home.example/#chats/' + connected.rooms[0]
    assert ok(call(connected, 'fetch', id=message['id']))['url'] == found['url']


def test_a_marked_rooms_text_takes_no_side_path(connected):
    """Review Focus, all three together: a marked room's local and peer text, and a carried brief, appear in no tool."""
    marked = connected.store.create_room(connected.person['id'], 'Marked', [])['id']
    remote_member(connected, marked)
    say(connected, marked, 'zebra-417 local')
    remote_says(connected, marked, 'zebra-417 from afar')
    connected.store.save_brief(connected.person['id'], marked, 'brief-zebra', 0)
    connected.store.mark_room(connected.person['id'], marked)
    connected.clock[0] += 1
    beside = say(connected, connected.rooms[0], 'right beside it')
    from connector_support import allowed, exchange
    client, code = allowed(connected, rooms='*', state='st-all')
    connected.tokens = exchange(connected, client, code).json()
    andy = person(connected, 'andy@example.org', 'Andy Example')
    later = connected.store.add_participants(connected.person['id'], marked, [andy['id']], carry_brief=1)['id']  # the brief's revision, carried
    seen = json.dumps([ok(call(connected, 'search', query='zebra')), ok(call(connected, 'fetch', id=beside['id'])),
                       ok(call(connected, 'rooms'))])
    assert 'zebra-417' not in seen and 'brief-zebra' not in seen and later not in seen
    assert refused(call(connected, 'read_room', room=later)) == MARKED


def test_remote_authors_are_named_and_kinded(connected):
    remote_member(connected, connected.rooms[0])
    connected.clock[0] += 1
    remote_says(connected, connected.rooms[0], 'hello from afar')
    messages = ok(call(connected, 'read_room', room=connected.rooms[0]))['messages']
    assert [(m['author'], m['author_kind']) for m in messages] == [('Remy Remote', 'remote')]
    found = ok(call(connected, 'search', query='from afar'))['results']
    assert [r['title'].split(DOT)[1] for r in found] == ['Remy Remote']  # search names a paired home's author too
    assert ok(call(connected, 'rooms'))['rooms'][0]['members'] == ['Remy Remote', 'Sam Example']


# ---- receipts and the limit ----

def receipts(connected):
    with connected.store.transaction() as db:
        return [dict(row) | {'rooms_read': json.loads(row['rooms_read']), 'rooms_refused': json.loads(row['rooms_refused'])}
                for row in db.execute('SELECT * FROM connector_reads ORDER BY at, rowid')]


def test_one_receipt_per_call_with_ids_and_never_arguments(connected):
    say(connected, connected.rooms[0], 'the zebra-query text')
    ok(call(connected, 'search', query='zebra-query'))
    ok(call(connected, 'read_room', room=connected.rooms[0], limit=5))
    rows = receipts(connected)
    assert [(r['tool'], r['outcome'], r['rooms_read']) for r in rows] == [
        ('search', 'ok', [connected.rooms[0]]), ('read_room', 'ok', [connected.rooms[0]])]
    assert rows[0]['person_id'] == connected.person['id'] and rows[0]['app'] == 'claude.ai' and rows[0]['size'] > 0
    assert 'zebra-query' not in json.dumps(rows)  # neither the query nor any other argument is kept


def test_a_refused_call_leaves_a_receipt_naming_only_a_room_the_person_is_in(connected):
    andy = person(connected, 'andy@example.org', 'Andy Example')
    andys = connected.store.create_room(andy['id'], 'Andy alone', [])['id']
    diary = connected.store.create_room(connected.person['id'], 'Diary', [])['id']
    connected.store.mark_room(connected.person['id'], connected.rooms[1])
    for room in (andys, diary, connected.rooms[1], 'peer-1:room-1'):
        refused(call(connected, 'read_room', room=room))
    assert [(r['outcome'], r['rooms_refused']) for r in receipts(connected)] == [
        ('refused', []), ('refused', [{'room': diary, 'why': 'not_shared'}]),
        ('refused', [{'room': connected.rooms[1], 'why': 'marked'}]), ('refused', [])]


def test_a_failed_call_leaves_a_receipt_in_a_fresh_transaction(connected, monkeypatch):
    from superyak_peer import connector_reads

    def broken(self, db, grant, args, seen):
        seen.reading(connected.rooms[0])
        db.execute('INSERT INTO connector_reads VALUES(?,?,?,?,?,?,?,?,?,?)',
                   ('half', grant['grant_id'], grant['person_id'], 'x', 0, 'rooms', '[]', '[]', 0, 'ok'))
        raise RuntimeError('a bug')
    monkeypatch.setitem(connector_reads.TOOLS, 'rooms', broken)
    assert mcp(connected, rpc('tools/call', {'name': 'rooms', 'arguments': {}}), connected.tokens['access_token'],
               raise_server_exceptions=False).status_code == 500
    assert [(r['id'] == 'half', r['outcome'], r['rooms_read']) for r in receipts(connected)] == [(False, 'failed', [connected.rooms[0]])]


def test_a_query_past_5_seconds_is_ended(connected, monkeypatch):
    """SQLite's progress handler ends a connector query that runs past QUERY_SECONDS, since it holds the store's lock."""
    from superyak_peer import connector_reads
    for n in range(50):
        say(connected, connected.rooms[0], f'line {n}')
    ticks = iter(range(0, 10 ** 6, 3))  # each look at the clock, 3 s later
    monkeypatch.setattr(connector_reads.time, 'monotonic', lambda: next(ticks))
    assert refused(call(connected, 'search', query='line')) == connector_reads.TOO_LONG
    assert [r['outcome'] for r in receipts(connected)] == ['failed']


def test_a_429_writes_no_receipt(connected):
    for _ in range(60):
        ok(call(connected, 'rooms'))
    answer = mcp(connected, rpc('tools/call', {'name': 'rooms', 'arguments': {}}), connected.tokens['access_token'])
    assert answer.status_code == 429 and len(receipts(connected)) == 60


def test_the_limit_holds_across_a_restart(connected):
    """The limit counts receipts, so a restart doesn't empty it (Task 8 replaces Task 7's in-memory count)."""
    from types import SimpleNamespace
    from superyak_peer.app import create_app
    from connector_support import PUBLIC_ORIGIN
    for _ in range(60):
        ok(call(connected, 'rooms'))
    again = create_app(connected.store.data_dir, clock=lambda: connected.clock[0],
                       allowed_origins=['http://testserver', PUBLIC_ORIGIN], public_origin=PUBLIC_ORIGIN)
    answer = mcp(SimpleNamespace(app=again), rpc('tools/call', {'name': 'rooms', 'arguments': {}}),
                 connected.tokens['access_token'])
    assert answer.status_code == 429 and answer.headers['retry-after'] == '60'


def test_receipts_are_kept_while_the_grant_lives_plus_a_year(connected):
    """Spec "Receipts": kept while the grant lives, plus one year; one whose grant is gone (a restore removed it) is
    kept a year from when it was made. The sweep runs after a good /token."""
    from connector_support import allowed, exchange
    ok(call(connected, 'rooms'))
    with connected.store.transaction() as db:
        grant = db.execute('SELECT grant_id FROM connector_reads').fetchone()[0]
        db.execute('INSERT INTO connector_reads VALUES(?,?,?,?,?,?,?,?,?,?)',
                   ('orphan', 'gone', connected.person['id'], 'claude.ai', connected.clock[0], 'rooms', '[]', '[]', 1, 'ok'))
        db.execute('UPDATE connector_grants SET revoked=? WHERE id=?', (connected.clock[0], grant))

    def sweep(state):  # another connection's good /token runs the sweep
        client, code = allowed(connected, state=state)
        assert exchange(connected, client, code).status_code == 200
    with connected.store.transaction() as db:  # revoked 100 days after the read, so its end is later than the read
        db.execute('UPDATE connector_grants SET revoked=NULL, ends=? WHERE id=?', (connected.clock[0] + 100 * 86400, grant))
    start = connected.clock[0]
    connected.clock[0] = start + 365 * 86400 + 10  # a year past the read, not past the grant's end
    sweep('st-a-year-on')
    assert [r['id'] != 'orphan' for r in receipts(connected)] == [True]  # the orphan goes a year past when it was made
    connected.clock[0] = start + 465 * 86400 + 10
    sweep('st-a-year-past-the-end')
    assert receipts(connected) == []


# ---- cut at a boundary at 100,000 characters (spec: Claude takes about 150,000) ----

def test_results_are_cut_at_a_message_boundary(connected):
    """A backward read keeps the newest messages that fit, with `truncated` and `before` to continue; a since read
    keeps the oldest to arrive, with `truncated` and `seq` to continue. Each result stays valid JSON under the cap."""
    from superyak_peer.connector_reads import TEXT_CAP
    ids = []
    for n in range(30):
        connected.clock[0] += 1
        ids.append(say(connected, connected.rooms[0], f'{n:02d} ' + 'x' * 4996)['id'])
    back = call(connected, 'read_room', room=connected.rooms[0])
    assert len(back['content'][0]['text']) <= TEXT_CAP
    back = ok(back)
    kept = [m['id'] for m in back['messages']]
    assert back['truncated'] is True and kept == ids[-len(kept):] and 0 < len(kept) < 30
    assert back['before'] == back['first_position'] == 30 - len(kept) and back['more'] is True
    rest = ok(call(connected, 'read_room', room=connected.rooms[0], before=back['before']))
    assert [m['id'] for m in rest['messages']] == ids[:30 - len(kept)][-len(rest['messages']):]
    forward = call(connected, 'read_room', room=connected.rooms[0], since=0)
    assert len(forward['content'][0]['text']) <= TEXT_CAP
    forward = ok(forward)
    first = [m['id'] for m in forward['messages']]
    assert forward['truncated'] is True and forward['more'] is True and first == ids[:len(first)]
    after = ok(call(connected, 'read_room', room=connected.rooms[0], since=forward['seq']))
    assert after['messages'] and [m['id'] for m in after['messages']] == ids[len(first):len(first) + len(after['messages'])]


def test_rooms_is_cut_at_a_room_boundary(connected):
    """Review Focus: 600 rooms with 200-character titles is more than the cap; the list stays valid JSON, cut whole."""
    from connector_support import allowed, exchange
    from superyak_peer.connector_reads import TEXT_CAP
    for n in range(600):
        connected.store.create_room(connected.person['id'], f'{n:03d} ' + 't' * 196, [])
    client, code = allowed(connected, rooms='*', state='st-all')
    connected.tokens = exchange(connected, client, code).json()
    result = call(connected, 'rooms')
    assert len(result['content'][0]['text']) <= TEXT_CAP
    listed = ok(result)
    assert listed['truncated'] is True and 300 < len(listed['rooms']) < 602
    assert all(len(room['title']) == 200 or room['title'] in ('Care plan', 'Lab notes') for room in listed['rooms'])


def test_fetch_is_cut_with_its_message_kept(connected):
    from superyak_peer.connector_reads import TEXT_CAP
    ids = []
    for n in range(5):
        connected.clock[0] += 1
        ids.append(say(connected, connected.rooms[0], f'{n} ' + 'y' * 19990)['id'])
    result = call(connected, 'fetch', id=ids[2])
    assert len(result['content'][0]['text']) <= TEXT_CAP
    got = ok(result)
    kept = [json.loads(line)['id'] for line in got['text'].split('\n')]
    assert got['truncated'] is True and ids[2] in kept and len(kept) == 4 and ids[4] not in kept  # the later edge goes first


def test_read_room_refuses_bad_arguments(connected):
    say(connected, connected.rooms[0], 'one')
    for args in ({'limit': 0}, {'limit': 101}, {'limit': '5'}, {'limit': True}, {'limit': 2.0}, {'before': -1},
                 {'since': 'x'}, {'before': 0, 'since': 0}, {'before': 2}, {'since': True}):
        assert refused(call(connected, 'read_room', room=connected.rooms[0], **args)), args
    assert ok(call(connected, 'read_room', room=connected.rooms[0], before=0))['messages'] == []
    assert [m['text'] for m in ok(call(connected, 'read_room', room=connected.rooms[0], before=1))['messages']] == ['one']


def test_the_system_author_and_a_ship_are_kinded(connected):
    andy = connected.store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    started = connected.store.start_docking('serenity', 'test-host')
    ship = connected.store.confirm_docking(andy['id'], started['id'], started['code'])
    room = connected.store.create_room(connected.person['id'], 'With a ship', [ship['id']])['id']
    connected.store.send_message(ship['id'], room, 'c-ship', 'from the ship')
    with connected.store.transaction() as db:
        connected.store._post_as_system(db, room, 'c-notice', 'a station notice')
    from connector_support import allowed, exchange
    client, code = allowed(connected, rooms=[room], state='st-ship')
    connected.tokens = exchange(connected, client, code).json()
    kinds = [m['author_kind'] for m in ok(call(connected, 'read_room', room=room))['messages']]
    assert sorted(kinds) == ['ship', 'system']


def test_a_paired_homes_message_is_activity(connected):
    remote_member(connected, connected.rooms[1])
    connected.clock[0] += 500
    remote_says(connected, connected.rooms[1], 'latest, from afar')
    rooms = ok(call(connected, 'rooms'))['rooms']
    assert rooms[0]['room'] == connected.rooms[1] and rooms[0]['last_activity'] == '1970-01-12T13:55:00Z'


# ---- a hostile-input pass (Serenity's after-action review, 2026-10-29: mutants find untested lines, not inputs) ----

HOSTILE = [[], {}, True, False, None, 1.5, -1, 0, 10 ** 30, 10 ** 15, '', ' ', 'x' * 10000, '%', '_', chr(92), ':',
           'a:b', '../x', {'$gt': ''}, [1, 2], 'NaN', chr(0), chr(0x202e), '<script>']  # a backslash, NUL, RTL override
FIELDS = {'rooms': ['extra'], 'read_room': ['room', 'limit', 'before', 'since'], 'search': ['query'], 'fetch': ['id']}


def test_no_hostile_argument_is_a_500(connected):
    """Every field an outside caller sets, sent each wrong type, empty, huge and odd: a result or a refusal, never a
    500. The first pass found `since=10**30`, which overflowed SQLite's integer."""
    bad = []
    for tool, fields in FIELDS.items():
        base = {'read_room': {'room': connected.rooms[0]}, 'search': {'query': 'x'}, 'fetch': {'id': 'x'}}.get(tool, {})
        for field in fields:
            for value in HOSTILE:
                connected.clock[0] += 2  # under the minute's 60
                answer = mcp(connected, rpc('tools/call', {'name': tool, 'arguments': base | {field: value}}),
                             connected.tokens['access_token'], raise_server_exceptions=False)
                if answer.status_code != 200 or 'result' not in answer.json():
                    bad.append((tool, field, repr(value)[:30], answer.status_code))
    assert bad == []


def test_a_cursor_past_15_digits_is_refused_as_the_station_does(connected):
    """app.py's paging takes at most 15 digits; read_room's cursors take the same bound, below SQLite's integer."""
    for field in ('before', 'since'):
        assert refused(call(connected, 'read_room', room=connected.rooms[0], **{field: 10 ** 15}))
    assert ok(call(connected, 'read_room', room=connected.rooms[0], since=10 ** 15 - 1))['messages'] == []


def test_search_returns_exactly_the_grants_readable_messages(connected):
    """The reader's must-fix 1: each of search's six filters, local and paired-home, pinned by the result ids exactly.
    A result holds no text, so a test that looks for text can't see a leak."""
    from connector_support import allowed, exchange
    andy = person(connected, 'andy@example.org', 'Andy Example')
    mine = connected.rooms[0]
    marked = connected.store.create_room(connected.person['id'], 'Marked', [])['id']
    unchosen = connected.store.create_room(connected.person['id'], 'Unchosen', [])['id']
    elsewhere = connected.store.create_room(andy['id'], 'Andy alone', [])['id']
    ids = {}
    for room in (mine, marked, unchosen, elsewhere):
        connected.clock[0] += 1
        remote_member(connected, room)
        ids[room] = {say(connected, room, f'needle local {room}', andy if room == elsewhere else None)['id'],
                     remote_says(connected, room, f'needle far {room}')}
    connected.store.mark_room(connected.person['id'], marked)
    assert {r['id'] for r in ok(call(connected, 'search', query='needle'))['results']} == ids[mine]  # the list
    client, code = allowed(connected, rooms='*', state='st-all')
    connected.tokens = exchange(connected, client, code).json()
    assert {r['id'] for r in ok(call(connected, 'search', query='needle'))['results']} == ids[mine] | ids[unchosen]


def test_one_message_over_the_cap_is_kept_cut_and_the_cursor_moves(connected):
    """The reader's must-fix 3: a message whose JSON alone passes the cap (20,000 control characters is about 120,000)
    stalled read_room both ways. It's kept with its text cut and `text_cut`, and the cursor moves past it."""
    from superyak_peer.connector_reads import TEXT_CAP
    say(connected, connected.rooms[0], 'before it')
    connected.clock[0] += 1
    huge = say(connected, connected.rooms[0], chr(1) * 20000)
    back = call(connected, 'read_room', room=connected.rooms[0])
    assert len(back['content'][0]['text']) <= TEXT_CAP
    back = ok(back)
    cut = back['messages'][0]
    assert [m['id'] for m in back['messages']] == [huge['id']] and cut['text_cut'] == 20000 - len(cut['text']) > 0
    assert back['truncated'] is True and back['before'] == 1 and back['more'] is True
    earlier = ok(call(connected, 'read_room', room=connected.rooms[0], before=back['before']))
    assert [m['text'] for m in earlier['messages']] == ['before it']
    alone = connected.store.send_message(connected.person['id'], connected.rooms[1], 'c-huge-2', chr(1) * 20000)
    connected.store.send_message(connected.person['id'], connected.rooms[1], 'c-after', 'after it')
    forward = ok(call(connected, 'read_room', room=connected.rooms[1], since=0))
    first = forward['messages'][0]
    assert [m['id'] for m in forward['messages']] == [alone['id']] and first['text_cut'] == 20000 - len(first['text']) > 0
    assert forward['more'] is True
    following = ok(call(connected, 'read_room', room=connected.rooms[1], since=forward['seq']))
    assert [m['text'] for m in following['messages']] == ['after it']


def test_fetch_stays_under_the_cap_measured_on_its_whole_json(connected):
    """The reader's should-fix: fetch's lines are JSON inside a JSON string, escaped twice, so measuring the lines
    alone let a result reach about twice the cap. A target too big alone is cut and marked."""
    from superyak_peer.connector_reads import TEXT_CAP
    ids = []
    for n in range(5):
        connected.clock[0] += 1
        ids.append(say(connected, connected.rooms[0], f'{n} ' + '"' * 19990)['id'])
    result = call(connected, 'fetch', id=ids[2])
    assert len(result['content'][0]['text']) <= TEXT_CAP and ok(result)['truncated'] is True
    connected.clock[0] += 1
    alone = say(connected, connected.rooms[1], chr(1) * 20000)['id']
    result = call(connected, 'fetch', id=alone)
    assert len(result['content'][0]['text']) <= TEXT_CAP
    line = json.loads(ok(result)['text'])
    assert line['id'] == alone and line['text_cut'] == 20000 - len(line['text']) > 0
    assert ok(result)['truncated'] is True  # N8: fetch says it was cut when its one message was


def test_a_revoke_or_a_narrowing_mid_call_is_seen_inside_the_read(connected, monkeypatch):
    """The reader's should-fix: bearer's check and the read were two transactions, so a revoke landing between them
    still let text out. The call re-reads the token and the connection inside its own transaction: a revoke gives the
    challenge, and a narrowed room set the refusal."""
    say(connected, connected.rooms[0], 'after the revoke')
    real = connected.store.connector_call

    def revoking(grant, tool, args):
        with connected.store.transaction() as db:
            db.execute('UPDATE connector_grants SET revoked=? WHERE id=?', (connected.clock[0], grant['grant_id']))
        return real(grant, tool, args)
    monkeypatch.setattr(connected.store, 'connector_call', revoking)
    answer = mcp(connected, rpc('tools/call', {'name': 'read_room', 'arguments': {'room': connected.rooms[0]}}),
                 connected.tokens['access_token'])
    assert answer.status_code == 401 and 'after the revoke' not in answer.text
    assert 'error="invalid_token"' in answer.headers['www-authenticate']


def test_a_narrowed_room_set_mid_call_is_refused(connected, monkeypatch):
    real = connected.store.connector_call

    def narrowing(grant, tool, args):
        with connected.store.transaction() as db:
            db.execute('UPDATE connector_grants SET rooms=? WHERE id=?', (json.dumps([connected.rooms[1]]), grant['grant_id']))
        return real(grant, tool, args)
    monkeypatch.setattr(connected.store, 'connector_call', narrowing)
    assert refused(call(connected, 'read_room', room=connected.rooms[0])) == NOT_SHARED


def test_a_page_that_is_only_one_cut_message_says_truncated(connected):
    """A room whose one message is past the cap: the page holds all of it there is, and still says it was cut."""
    say(connected, connected.rooms[1], chr(1) * 20000)
    back = ok(call(connected, 'read_room', room=connected.rooms[1]))
    assert back['truncated'] is True and back['messages'][0]['text_cut'] > 0


def test_an_access_token_revoked_mid_call_is_seen_inside_the_read(connected, monkeypatch):
    """A reuse's walk revokes an access token while its connection stays live: the call re-reads the token too."""
    from superyak_peer.connector import REVOKED
    say(connected, connected.rooms[0], 'after the token went')
    real = connected.store.connector_call

    def walking(grant, tool, args):
        with connected.store.transaction() as db:
            db.execute("UPDATE connector_tokens SET expires=? WHERE kind='access'", (REVOKED,))
        return real(grant, tool, args)
    monkeypatch.setattr(connected.store, 'connector_call', walking)
    answer = mcp(connected, rpc('tools/call', {'name': 'read_room', 'arguments': {'room': connected.rooms[0]}}),
                 connected.tokens['access_token'])
    assert answer.status_code == 401 and 'after the token went' not in answer.text



def test_the_token_rechecked_in_the_call_is_bound_to_its_grant(connected):
    """Task 8's re-check, nit 2: _still_live read the token by hash and the grant by id apart. A token of another live
    connection beside this grant's id is no token for it."""
    import pytest
    from connector_support import allowed, exchange
    from superyak_peer.connector_reads import GrantGone
    from connector_support import RESOURCE_URL
    client, code = allowed(connected, state='st-other')
    other = connected.store.bearer(exchange(connected, client, code).json()['access_token'], RESOURCE_URL)
    mine = connected.store.bearer(connected.tokens['access_token'], RESOURCE_URL)
    with pytest.raises(GrantGone):
        connected.store.connector_call(mine | {'token': other['token']}, 'rooms', {})


def test_a_cut_message_with_the_longest_author_name_stays_under_the_cap(connected):
    """Tardis's unverified case: a paired home's name is at most 200 characters (identity.validate_card), each control
    character six as JSON, so a cut message's floor stays far under the cap, in read_room and fetch alike."""
    from superyak_peer.connector_reads import TEXT_CAP
    remote_member(connected, connected.rooms[0], name=chr(1) * 200)
    connected.clock[0] += 1
    huge = remote_says(connected, connected.rooms[0], chr(1) * 20000)
    for result in (call(connected, 'read_room', room=connected.rooms[0]), call(connected, 'fetch', id=huge)):
        assert len(result['content'][0]['text']) <= TEXT_CAP and ok(result)
