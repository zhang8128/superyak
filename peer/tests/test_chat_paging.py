import uuid

def fill(client, key, n, clock=None, prefix='m'):
    ids = []
    for i in range(n):
        ids.append(client.post(f'/api/chats/{key}/messages', json={'client_message_id': f'{prefix}{i}', 'body': f'message {i}'}).json()['id'])
        if clock is not None:
            clock[0] += 1
    return ids

def room_of(env, n=30):
    app, clients, users, clock = env
    key = clients[0].post('/api/chats', json={'title': 'Paged', 'member_ids': [users[1]['id']]}).json()['id']
    fill(clients[0], key, n, clock)
    return key

def ids_of(response):
    assert response.status_code == 200, response.text
    return [m['id'] for m in response.json()['messages']]

def test_no_parameters_is_byte_identical(env):
    app, clients, users, clock = env
    key = room_of(env, 5)
    with app.state.store.transaction() as db:
        for i in range(2):
            db.execute('INSERT INTO peer_messages VALUES(?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex, key, f'{"a" * 64}:remote', f'p{i}', f'relayed {i}', 1, clock[0] - 2 + i))
    assert clients[0].post(f'/api/chats/{key}/claims', json={'key': 'spec:p1', 'note': 'working'}).status_code == 201
    assert clients[0].put(f'/api/chats/{key}/brief', json={'body': 'The brief', 'revision': 0}).status_code == 200
    response = clients[0].get(f'/api/chats/{key}')
    assert response.json() == app.state.store.get_room(users[0]['id'], key)
    for extra in ('paged', 'total', 'first_position', 'seq', 'more'):
        assert extra not in response.json()

def test_limit_alone_returns_the_newest(env):
    key = room_of(env)
    client = env[1][0]
    full = ids_of(client.get(f'/api/chats/{key}'))
    body = client.get(f'/api/chats/{key}?limit=10').json()
    assert [m['id'] for m in body['messages']] == full[-10:]
    assert body['paged'] is True and body['total'] == 30 and body['first_position'] == 20
    assert body['seq'] > 0

def test_before_at_start_after_windows(env):
    key = room_of(env)
    client = env[1][0]
    full = ids_of(client.get(f'/api/chats/{key}'))
    assert ids_of(client.get(f'/api/chats/{key}?before=20&limit=5')) == full[15:20]
    assert ids_of(client.get(f'/api/chats/{key}?at=3&limit=4')) == full[3:7]
    assert ids_of(client.get(f'/api/chats/{key}?start={full[7]}&limit=2')) == full[7:9]
    assert ids_of(client.get(f'/api/chats/{key}?after={full[7]}&limit=2')) == full[8:10]
    assert client.get(f'/api/chats/{key}?before=20&limit=5').json()['first_position'] == 15
    assert client.get(f'/api/chats/{key}?after={full[7]}&limit=2').json()['first_position'] == 8

def test_local_and_peer_with_the_same_created_keep_todays_order(env):
    app, clients, users, clock = env
    key = clients[0].post('/api/chats', json={'title': 'Ties', 'member_ids': [users[1]['id']]}).json()['id']
    fill(clients[0], key, 2, clock)
    with app.state.store.transaction() as db:
        for i in range(2):
            db.execute('INSERT INTO peer_messages VALUES(?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex, key, f'{"a" * 64}:remote', f'p{i}', f'relayed {i}', 1, clock[0]))
    tied = fill(clients[0], key, 1, None, prefix='tied')[0]
    with app.state.store.transaction() as db:
        db.execute('UPDATE messages SET created=? WHERE id=?', (clock[0], tied))  # a local message at the peers' instant
    clock[0] += 1
    fill(clients[0], key, 2, clock, prefix='n')
    client = clients[0]
    full = ids_of(client.get(f'/api/chats/{key}'))
    assert len(full) == 7 and full.index(tied) == 2  # the local message leads the two peer rows at its instant
    assert ids_of(client.get(f'/api/chats/{key}?at=0&limit=100')) == full
    assert ids_of(client.get(f'/api/chats/{key}?before={len(full)}&limit=100')) == full
    assert ids_of(client.get(f'/api/chats/{key}?start={full[0]}&limit=100')) == full

def test_empty_room_pages(env):
    app, clients, users, _ = env
    key = clients[0].post('/api/chats', json={'title': 'Empty'}).json()['id']
    body = clients[0].get(f'/api/chats/{key}?limit=5').json()
    assert body['messages'] == [] and body['total'] == 0 and body['first_position'] == 0 and body['paged'] is True
    body = clients[0].get(f'/api/chats/{key}?at=0&limit=5').json()
    assert body['messages'] == [] and body['total'] == 0 and body['first_position'] == 0 and body['paged'] is True
    assert clients[0].get(f'/api/chats/{key}?at=1').status_code == 400

def test_bad_parameters_are_400(env):
    key = room_of(env)
    client = env[1][0]
    for query in ('limit=0', 'limit=501', 'at=-1', 'before=x', 'at=1&before=2', 'since=-1', 'since=x'):
        assert client.get(f'/api/chats/{key}?{query}').status_code == 400, query
    refused = client.get(f'/api/chats/{key}?at=30')
    assert refused.status_code == 400 and 'at must be between 0 and 29' in refused.text
    refused = client.get(f'/api/chats/{key}?before=31')
    assert refused.status_code == 400 and 'before must be between 0 and 30' in refused.text

def test_unknown_start_is_404_and_a_non_member_learns_nothing(env):
    key = room_of(env)
    clients = env[1]
    assert clients[0].get(f'/api/chats/{key}?start=nope').status_code == 404
    assert clients[0].get(f'/api/chats/{key}?after=nope').status_code == 404
    outsider = clients[2].get(f'/api/chats/{key}?limit=5')
    assert outsider.status_code == 404
    assert outsider.json() == clients[2].get(f'/api/chats/{key}').json()

def test_system_author_is_room_wide(env):
    app, clients, users, clock = env
    key = clients[0].post('/api/chats', json={'title': 'Sys', 'member_ids': [users[1]['id']]}).json()['id']
    assert clients[0].put(f'/api/chats/{key}/brief', json={'body': 'A brief', 'revision': 0}).status_code == 200
    clock[0] += 1
    fill(clients[0], key, 10, clock)
    assert 'system_author' in clients[0].get(f'/api/chats/{key}').json()
    assert 'system_author' in clients[0].get(f'/api/chats/{key}?limit=3').json()

def mixed_room(env):
    """A room with a person's posts, a ship post, a reply, a station notice (the brief), a claim note, and peer rows,
    two of which share their instant with a local message."""
    from test_presence import docked, ship_client
    app, clients, users, clock = env
    ship, ship_key = docked(app.state.store, users[0]['id'])
    key = clients[0].post('/api/chats', json={'title': 'Mixed', 'member_ids': [users[1]['id'], ship['id']]}).json()['id']
    first = fill(clients[0], key, 3, clock)
    assert clients[0].put(f'/api/chats/{key}/brief', json={'body': 'The brief', 'revision': 0}).status_code == 200
    clock[0] += 1
    assert ship_client(app, ship_key).post(f'/api/chats/{key}/messages', json={'client_message_id': 'ship', 'body': 'from a ship'}).status_code == 201
    clock[0] += 1
    assert clients[1].post(f'/api/chats/{key}/messages', json={'client_message_id': 'r', 'body': 'a reply', 'reply_to': first[0]}).status_code == 201
    assert clients[0].post(f'/api/chats/{key}/claims', json={'key': 'spec:mixed', 'note': 'working'}).status_code == 201
    with app.state.store.transaction() as db:
        for i in range(3):
            db.execute('INSERT INTO peer_messages VALUES(?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex, key, f'{"a" * 64}:remote', f'p{i}', f'relayed {i}', 1, clock[0]))
        db.execute('UPDATE messages SET created=? WHERE client_message_id=?', (clock[0], 'r'))  # ties with the peer rows
    clock[0] += 1
    fill(clients[0], key, 2, clock, prefix='late')
    return app, users, key

def test_the_no_parameter_response_keeps_its_key_order(env):
    app, users, key = mixed_room(env)
    body = env[1][0].get(f'/api/chats/{key}').json()
    assert list(body) == ['id', 'owner_id', 'title', 'epoch', 'linked_room_id', 'member_ids', 'created', 'last_activity',
                          'messages', 'members', 'brief', 'brief_revision', 'system_author', 'claims',
                          'moderators']  # main's own order, moderators included
    local = [m for m in body['messages'] if 'source' in m]
    peer = [m for m in body['messages'] if 'source' not in m]
    assert len(local) + len(peer) == len(body['messages']) and len(peer) == 3
    assert {tuple(m) for m in local} == {('id', 'room_id', 'author_id', 'client_message_id', 'body', 'epoch', 'created', 'source', 'reply_to')}
    assert {tuple(m) for m in peer} == {('id', 'room_id', 'author_id', 'client_message_id', 'body', 'epoch', 'created', 'reply_to')}
    assert list(body['members'][0]) == ['id', 'username', 'name', 'kind', 'owner_id']

def test_paged_messages_equal_the_full_reads_slices(env):
    app, users, key = mixed_room(env)
    client = env[1][0]
    full = client.get(f'/api/chats/{key}').json()['messages']
    assert any(m.get('source') for m in full) and any(m.get('reply_to') for m in full)
    tie = next(i for i, m in enumerate(full) if 'source' not in m) - 1  # the local message that precedes the peer rows
    total = len(full)
    for query, begin, end in (('at=0&limit=100', 0, total), (f'at={tie}&limit=3', tie, tie + 3), (f'at={tie + 1}&limit=4', tie + 1, tie + 5),
                              ('limit=4', total - 4, total), (f'before={tie + 2}&limit=3', tie - 1, tie + 2),
                              (f'start={full[2]["id"]}&limit=6', 2, 8)):
        page = client.get(f'/api/chats/{key}?{query}').json()
        assert page['messages'] == full[begin:end], query
        assert page['first_position'] == begin

def seq_of(client, key):
    return client.get(f'/api/chats/{key}?limit=1').json()['seq']

def newest_event(app, key):
    with app.state.store.transaction() as db:
        return db.execute("SELECT MAX(id) FROM events WHERE kind='chat.message' AND resource_id=?", (key,)).fetchone()[0]

def test_since_returns_what_arrived_after_the_cursor(env):
    app, clients, users, clock = env
    key = room_of(env, 5)
    client = clients[0]
    cursor = seq_of(client, key)
    new = fill(client, key, 3, clock, prefix='n')
    body = client.get(f'/api/chats/{key}?since={cursor}').json()
    assert [m['id'] for m in body['messages']] == new
    assert body['more'] is False and body['seq'] == newest_event(app, key) and body['paged'] is True

def test_since_sees_a_late_peer_message_with_an_older_created(env):
    app, clients, users, clock = env
    key = room_of(env, 5)
    client = clients[0]
    cursor = seq_of(client, key)
    late = uuid.uuid4().hex
    with app.state.store.transaction() as db:
        db.execute('INSERT INTO peer_messages VALUES(?,?,?,?,?,?,?)', (late, key, f'{"a" * 64}:remote', 'late', 'relayed late', 1, 0.5))
        app.state.store.emit(db, 'chat.message', key, 1, {'message_id': late, 'author_id': f'{"a" * 64}:remote'})
    body = client.get(f'/api/chats/{key}?since={cursor}').json()
    assert [m['id'] for m in body['messages']] == [late]
    assert body['first_position'] == 0 and body['more'] is False

def test_since_pages_from_the_oldest_and_never_skips(env):
    app, clients, users, clock = env
    key = room_of(env, 5)
    client = clients[0]
    cursor = seq_of(client, key)
    new = fill(client, key, 150, clock, prefix='n')
    first = client.get(f'/api/chats/{key}?since={cursor}&limit=100').json()
    assert [m['id'] for m in first['messages']] == new[:100] and first['more'] is True
    second = client.get(f'/api/chats/{key}?since={first["seq"]}&limit=100').json()
    assert [m['id'] for m in second['messages']] == new[100:] and second['more'] is False
    assert second['seq'] == newest_event(app, key)

def test_since_with_nothing_new(env):
    app, clients, users, clock = env
    key = room_of(env, 5)
    client = clients[0]
    body = client.get(f'/api/chats/{key}?since={seq_of(client, key)}').json()
    assert body['messages'] == [] and body['more'] is False and body['first_position'] == body['total'] == 5

def test_since_skips_an_event_whose_message_is_gone_but_passes_the_cursor(env):
    app, clients, users, clock = env
    key = room_of(env, 2)
    client = clients[0]
    cursor = seq_of(client, key)
    with app.state.store.transaction() as db:
        app.state.store.emit(db, 'chat.message', key, 1, {'message_id': 'gone', 'author_id': users[0]['id']})
    body = client.get(f'/api/chats/{key}?since={cursor}').json()
    assert body['messages'] == [] and body['more'] is False and body['seq'] == newest_event(app, key) > cursor

def test_since_uses_the_existing_index(env):
    from superyak_peer.chats import SINCE_SQL
    app, clients, users, clock = env
    key = room_of(env, 2)
    with app.state.store.transaction() as db:
        plan = ' '.join(str(tuple(r)) for r in db.execute('EXPLAIN QUERY PLAN ' + SINCE_SQL, (key, 0)))
    assert 'events_kind_room_id' in plan, plan


def _plans(db, sql, params):
    return ' '.join(str(tuple(r)) for r in db.execute('EXPLAIN QUERY PLAN ' + sql, params))

def test_the_pages_id_queries_look_ids_up_by_primary_key_not_the_room_index(env):
    """M1: `room_id=? AND id IN (...)` made SQLite read the whole room through the room_id index."""
    from superyak_peer.chats import page_rows_sql
    from superyak_peer.inbox import replies_sql
    from superyak_peer.tickets import sources_sql
    app, clients, users, clock = env
    key = room_of(env, 150)
    others = [room_of(env, 1) for _ in range(10)]
    queries = [page_rows_sql('messages', 100), page_rows_sql('peer_messages', 100), replies_sql(100), *sources_sql(100)]
    with app.state.store.transaction() as db:
        # Statistics as a Pi that has run ANALYZE has them: many rooms, so the room index looks selective.
        for table in ('messages', 'peer_messages'):
            db.executemany(f'INSERT INTO {table} VALUES(?,?,?,?,?,?,?)', [
                (f'{table}-{n}', others[n % 10], users[0]['id'], f'c{n}', 'x', 1, float(n)) for n in range(1500)])
        db.execute('ANALYZE')
        ids = [r[0] for r in db.execute('SELECT id FROM messages WHERE room_id=? ORDER BY created DESC LIMIT 100', (key,))]
        for sql in queries:
            plan = _plans(db, sql, (key, *ids))
            assert 'autoindex_messages_2' not in plan and 'autoindex_peer_messages_2' not in plan, (sql, plan)
            assert 'autoindex_messages_1' in plan or 'autoindex_peer_messages_1' in plan or 'PRIMARY KEY' in plan, (sql, plan)

def test_the_whole_room_queries_are_unchanged_by_the_page_fix():
    from superyak_peer.inbox import replies_sql
    from superyak_peer.tickets import sources_sql
    assert '+' not in replies_sql() and not any('+' in sql for sql in sources_sql())

def test_a_remote_room_ignores_paging_even_when_it_is_invalid_for_a_local_room(env):
    """S3: a paired peer's room answers as today; an over-long start= (a peer's id station_read printed) is not a 400."""
    app, clients, users, clock = env
    remote = 'f' * 64 + ':' + 'r' * 8
    today = clients[0].get(f'/api/chats/{remote}')
    for query in ('start=' + 'x' * 150, 'limit=0', 'before=nope', 'since=1&at=2'):
        paged = clients[0].get(f'/api/chats/{remote}?{query}')
        assert (paged.status_code, paged.json()) == (today.status_code, today.json()), query
