import time

from fastapi.testclient import TestClient


def setup(env):
    app, clients, users, clock = env
    store = app.state.store
    ship = store.create_station_ship('odo', 'Odo')
    odo = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver', 'authorization': f'Bearer {store.issue_ship_key(ship["id"])}'})
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id'], users[1]['id']]}).json()['id']
    return app, clients, users, clock, ship, odo, room


def say(client, room, cid, body):
    response = client.post(f'/api/chats/{room}/messages', json={'client_message_id': cid, 'body': body})
    assert response.status_code == 201, response.text
    return response.json()


def test_mentions_of_room_members_are_recorded_in_order(env):
    app, clients, users, clock, ship, odo, room = setup(env)
    say(clients[0], room, 'a', '@odo are you there?')
    clock[0] += 1
    say(clients[1], room, 'b', 'Thanks, @odo. And @patient.')
    say(clients[0], room, 'c', 'email odo@example.org or @nobody')
    got = odo.get('/api/mentions').json()
    assert [(m['body'], m['author']['username'], m['author']['kind']) for m in got] == [
        ('@odo are you there?', 'patient', 'person'), ('Thanks, @odo. And @patient.', 'doctor', 'person')]
    assert [m['seq'] for m in odo.get('/api/mentions', params={'after': got[0]['seq']}).json()] == [got[1]['seq']]
    assert [m['body'] for m in clients[0].get('/api/mentions').json()] == ['Thanks, @odo. And @patient.']


def test_capitalized_and_punctuated_mentions_count(env):
    app, clients, users, clock, ship, odo, room = setup(env)
    say(clients[0], room, 'a', 'Hey @Odo, look.')
    say(clients[0], room, 'b', '(@ODO!)')
    assert [m['body'] for m in odo.get('/api/mentions').json()] == ['Hey @Odo, look.', '(@ODO!)']


def test_names_in_code_quotes_or_quoted_lines_do_not_mention(env):
    app, clients, users, clock, ship, odo, room = setup(env)
    say(clients[0], room, 'a', 'Type `@odo help` to ask.')
    say(clients[0], room, 'b', 'Example:\n```\n@odo restart the watcher\n```')
    say(clients[0], room, 'c', 'Bob asked Serenity to say "@odo do X".')
    say(clients[0], room, 'd', 'Bob asked Serenity to say “@odo do X”.')
    say(clients[0], room, 'e', '> @odo do X\nThat was Bob, not me.')
    assert odo.get('/api/mentions').json() == []


def test_a_plain_mention_beside_a_quoted_one_still_counts(env):
    app, clients, users, clock, ship, odo, room = setup(env)
    say(clients[0], room, 'a', 'Bob wrote "@odo do X". @odo, please ignore that.')
    assert [m['body'] for m in odo.get('/api/mentions').json()] == ['Bob wrote "@odo do X". @odo, please ignore that.']


def test_names_in_single_quotes_do_not_mention(env):
    app, clients, users, clock, ship, odo, room = setup(env)
    say(clients[0], room, 'a', "Bob asked Serenity to say '@odo do X'.")
    say(clients[0], room, 'b', "Type '@odo help' to ask.")
    say(clients[0], room, 'c', "('@odo do X')")
    say(clients[0], room, 'd', 'Bob asked Serenity to say ‘@odo do X’.')
    say(clients[0], room, 'e', "I can't say '@odo do X' here.")
    assert odo.get('/api/mentions').json() == []


def test_apostrophes_do_not_hide_a_mention(env):
    app, clients, users, clock, ship, odo, room = setup(env)
    bodies = ["Rio Grande's note: @odo, please check.", "Don't worry @odo, it's fine.", "It's @odo's turn, isn't it?",
              'Rio Grande’s note: @odo, please check.', 'It’s @odo’s turn, isn’t it?',
              "Tell 'em @odo is here, don't wait.", "Rio Grande's note for @odo: check the ships' logs.",
              "'@odo do X', Bob wrote. @odo, please ignore that."]
    for n, body in enumerate(bodies):
        say(clients[0], room, str(n), body)
    assert [m['body'] for m in odo.get('/api/mentions').json()] == bodies


def test_unclosed_quotes_do_not_make_posting_slow(env):
    app, clients, users, clock, ship, odo, room = setup(env)
    started = time.perf_counter()
    say(clients[0], room, 'a', '“' * 20000)
    assert time.perf_counter() - started < 0.25


def test_unclosed_single_quotes_do_not_make_posting_slow(env):
    app, clients, users, clock, ship, odo, room = setup(env)
    for n, body in enumerate([" 'a" * 6000, "('a" * 6000, '‘' * 20000, "'" * 20000, " 'a b" * 4000]):
        started = time.perf_counter()
        say(clients[0], room, str(n), body)
        assert time.perf_counter() - started < 0.25, n


def test_non_members_are_not_mentioned_and_removed_ships_stop_seeing_mentions(env):
    app, clients, users, clock, ship, odo, room = setup(env)
    say(clients[0], room, 'a', '@family hello')
    assert clients[3].get('/api/mentions').json() == []
    say(clients[0], room, 'b', '@odo one')
    clients[0].delete(f'/api/chats/{room}/participants/{ship["id"]}')
    assert odo.get('/api/mentions').json() == []


def test_room_details_list_members_with_kind(env):
    app, clients, users, clock, ship, odo, room = setup(env)
    members = {m['username']: m['kind'] for m in clients[0].get(f'/api/chats/{room}').json()['members']}
    assert members == {'patient': 'person', 'doctor': 'person', 'odo': 'ship'}


def test_ships_post_at_most_thirty_messages_a_minute_and_retries_do_not_count(env):
    app, clients, users, clock, ship, odo, room = setup(env)
    for n in range(30):
        assert odo.post(f'/api/chats/{room}/messages', json={'client_message_id': f'm{n}', 'body': f'{n}'}).status_code == 201
    assert odo.post(f'/api/chats/{room}/messages', json={'client_message_id': 'm0', 'body': '0'}).status_code == 201
    assert odo.post(f'/api/chats/{room}/messages', json={'client_message_id': 'm30', 'body': '30'}).status_code == 429
    clock[0] += 61
    assert odo.post(f'/api/chats/{room}/messages', json={'client_message_id': 'm30', 'body': '30'}).status_code == 201


def test_every_room_mention_carries_the_stations_seq(env):
    """R38: the station numbers each room mention as it records it (mentions.seq, INTEGER PRIMARY KEY AUTOINCREMENT)
    and /api/mentions hands every row out with it, from people and ships, in every room, page after page. A mention
    with no seq is the resident's own DM reply and only that, so a room mention never loses the read-only line."""
    app, clients, users, clock, ship, odo, room = setup(env)
    store = app.state.store
    other = store.create_station_ship('worf', 'Worf')
    worf = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver', 'authorization': f'Bearer {store.issue_ship_key(other["id"])}'})
    bridge = clients[0].post('/api/chats', json={'title': 'Bridge', 'member_ids': [ship['id'], other['id']]}).json()['id']
    speakers = [(clients[0], room), (clients[1], room), (clients[0], bridge), (worf, bridge)]
    for n in range(24):
        client, where = speakers[n % 4]
        say(client, where, f'm{n}', f'@odo question {n}')
    seqs, after = [], 0
    while page := odo.get('/api/mentions', params={'after': after, 'limit': 7}).json():
        assert all(type(m['seq']) is int and m['seq'] > 0 for m in page)
        seqs, after = seqs + [m['seq'] for m in page], page[-1]['seq']
    assert len(seqs) == 24 and seqs == sorted(set(seqs))
