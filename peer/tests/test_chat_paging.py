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
