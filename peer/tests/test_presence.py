"""Ship status (docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md): presence, the watch lease and
the directory. The first test is the guard (R2): requests behave the same with and without the presence headers."""
from fastapi.testclient import TestClient
from superyak_peer.presence import parse_presence

HEADERS = {'x-superyak-session': 'session-one', 'x-superyak-client': 'hook/0123456789ab', 'x-superyak-mode': 'write'}


def ship_client(app, key, **headers):
    return TestClient(app, base_url='http://testserver',
                      headers={'origin': 'http://testserver', 'authorization': f'Bearer {key}', **headers})


def docked(store, owner_id, name='serenity'):
    started = store.start_docking(name, 'test-host')
    ship = store.confirm_docking(owner_id, started['id'], started['code'])
    return ship, store.docking_status(started['id'], started['secret'])['key']


def say(client, room, cid, body):
    response = client.post(f'/api/chats/{room}/messages', json={'client_message_id': cid, 'body': body})
    assert response.status_code == 201, response.text
    return response.json()


def scrub(value):
    """Times move with every request; everything else must be equal."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in ('created', 'last_activity', 'last_used')}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def test_without_the_headers_nothing_changes(env):
    """R2: the same calls with and without the headers give the same answers."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id']]}).json()['id']
    asked = say(clients[0], room, 'a', '@serenity what changed?')
    plain, marked = ship_client(app, key), ship_client(app, key, **HEADERS)
    answers = []
    for client in (plain, marked):
        answers.append([
            client.get('/api/me').json(),
            client.get('/api/chats').json(),
            client.get(f'/api/chats/{room}').json(),
            client.get('/api/mentions?after=0').json(),
            client.post('/api/ships/me/unread', json={'cursor': f'c-{len(answers)}'}).json()['messages'],
        ])
    assert scrub(answers[0]) == scrub(answers[1])
    first = plain.post('/api/ships/me/tickets', json={'message_id': asked['id']}).json()
    again = marked.post('/api/ships/me/tickets', json={'message_id': asked['id']}).json()
    assert first['id'] == again['id'] and 'decision' not in first and 'decision' not in again



def rows(store, ship_id):
    with store.transaction() as db:
        return [dict(r) for r in db.execute('SELECT * FROM presence WHERE ship_id=? ORDER BY name', (ship_id,))]


def test_presence_is_written_for_the_authenticated_ship_only(env):
    """R1: a ship key with the headers writes a row for that ship; a person's request, or a ship key without a
    session header, writes none; a header can't name another ship."""
    app, clients, users, clock = env
    store = app.state.store
    serenity, key = docked(store, users[0]['id'])
    rio, _ = docked(store, users[0]['id'], 'rio-grande')
    clients[0].headers.update(HEADERS)
    clients[0].get('/api/chats')
    ship_client(app, key).get('/api/chats')
    ship_client(app, key, **{**HEADERS, 'x-superyak-session': rio['id']}).get('/api/chats')
    assert [r['name'] for r in rows(store, serenity['id'])] == [rio['id']]
    assert rows(store, rio['id']) == [] and rows(store, users[0]['id']) == []


def test_presence_writes_are_coalesced_inside_the_key_check(env):
    """R3: at most one write per session per 30 s; a malformed header is ignored, never a 400; the name `default`
    writes nothing (R28, station side)."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    client = ship_client(app, key, **HEADERS)
    client.get('/api/me')
    first = rows(store, ship['id'])[0]
    clock[0] += 29
    client.get('/api/me')
    assert rows(store, ship['id'])[0]['last_seen'] == first['last_seen']
    clock[0] += 2
    client.get('/api/me')
    assert rows(store, ship['id'])[0]['last_seen'] == first['last_seen'] + 31
    for bad in ({'x-superyak-session': 'a b'}, {'x-superyak-session': 'x' * 101}, {'x-superyak-session': 'default'},
                {**HEADERS, 'x-superyak-session': 's2', 'x-superyak-client': 'evil/1', 'x-superyak-mode': 'root'}):
        assert ship_client(app, key, **bad).get('/api/me').status_code == 200
    got = {r['name']: r for r in rows(store, ship['id'])}
    assert set(got) == {'session-one', 's2'} and got['s2']['client'] == 'unknown' and got['s2']['mode'] == 'unknown'


def test_presence_stores_no_text_paths_or_raw_mode(env):
    """R4: only the declared columns exist, and the raw permission mode never lands."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    ship_client(app, key, **{**HEADERS, 'x-superyak-mode': 'plan'}).get('/api/me')
    ship_client(app, key, **{**HEADERS, 'x-superyak-session': 's2', 'x-superyak-mode': 'bypassPermissions'}).get('/api/me')
    got = {r['name']: r for r in rows(store, ship['id'])}
    assert set(got['session-one']) == {'ship_id', 'name', 'client', 'mode', 'label', 'first_seen', 'last_seen',
                                       'watch_minutes', 'watch_writable', 'watch_until'}
    assert got['session-one']['mode'] == 'plan' and got['s2']['mode'] == 'unknown'


def test_parse_presence_reads_only_well_formed_headers():
    assert parse_presence({'x-superyak-session': 's1', 'x-superyak-client': 'mcp/0123456789ab', 'x-superyak-mode': 'write'}) == {
        'name': 's1', 'client': 'mcp/0123456789ab', 'mode': 'write'}
    assert parse_presence({}) is None and parse_presence({'x-superyak-session': 'default'}) is None
    assert parse_presence({'x-superyak-session': 's1', 'x-superyak-client': 'mcp/unknown'})['client'] == 'mcp/unknown'
    assert parse_presence({'x-superyak-session': 's1', 'x-superyak-client': 'mcp/v1.2'})['client'] == 'unknown'


def test_live_is_computed_from_times(env):
    """R5, the live half: live while last seen within 120 s; it decides nothing but the directory field."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    ship_client(app, key, **HEADERS).get('/api/me')
    sessions = lambda: clients[0].get('/api/ships/directory').json()[0]['sessions']
    assert sessions()[0]['live'] is True
    clock[0] += 121
    assert sessions()[0]['live'] is False


def test_rows_are_pruned_after_a_day_and_capped_at_100(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    ship_client(app, key, **{**HEADERS, 'x-superyak-session': 'old'}).get('/api/me')
    clock[0] += 86401
    for n in range(101):
        ship_client(app, key, **{**HEADERS, 'x-superyak-session': f's{n:03d}'}).get('/api/me')
        clock[0] += 1
    names = [r['name'] for r in rows(store, ship['id'])]
    assert 'old' not in names and len(names) == 100 and 's000' not in names and 's100' in names


def test_the_directory_shows_each_caller_what_s7_allows(env):
    """R13: the owner sees session rows, labels, versions and the machine; a co-member ship sees three ship-level
    fields with last_seen rounded down to 15 minutes; a stranger sees nothing; an admin sees everything. Review
    Focus 5: a plan-mode session on watch shows mode plan to the owner."""
    app, clients, users, clock = env
    store = app.state.store
    serenity, key = docked(store, users[0]['id'])
    rio, rio_key = docked(store, users[1]['id'], 'rio-grande')
    clients[0].post('/api/chats', json={'title': 'Shared', 'member_ids': [serenity['id'], rio['id']]})
    clock[0] = 1000000.0 + 7 * 60
    ship_client(app, key, **{**HEADERS, 'x-superyak-mode': 'plan'}).get('/api/me')
    with store.transaction() as db:
        db.execute("UPDATE presence SET watch_minutes=20, watch_writable=1, watch_until=? WHERE ship_id=?",
                   (clock[0] + 1200, serenity['id']))
    owner_view = {s['username']: s for s in clients[0].get('/api/ships/directory').json()}
    mine = owner_view['serenity']
    assert mine['machine'] == 'test-host' and mine['writable_on_watch'] is True and mine['live_runs'] == 0
    assert [(s['name'], s['mode'], s['on_watch'], s['client']) for s in mine['sessions']] == [
        ('session-one', 'plan', True, 'hook/0123456789ab')]
    co = {s['username']: s for s in ship_client(app, rio_key).get('/api/ships/directory').json()}
    assert set(co['serenity']) == {'id', 'username', 'name', 'owner_name', 'writable_on_watch', 'live_runs', 'last_seen'}
    assert co['serenity']['last_seen'] == 999900.0 and co['serenity']['writable_on_watch'] is True  # 1000420 rounded down
    assert sorted(s['username'] for s in clients[2].get('/api/ships/directory').json()) == ['rio-grande', 'serenity']  # admin; order isn't S7's
    assert clients[3].get('/api/ships/directory').json() == []


def test_a_refused_key_writes_no_presence(env):
    """Gate check (Rio Grande, cbd8774e): a wrong, malformed or revoked key is 401 and writes no presence row."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    store.revoke_presented_key(key)
    for bad in (key, 'not-a-key', 'x' * 200):
        assert ship_client(app, bad, **HEADERS).get('/api/me').status_code == 401
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM presence').fetchone()[0] == 0


def test_calls_racing_inside_the_window_write_once(env):
    """Gate check: eight calls racing inside one 30 s window write one row once, and none fails. The clock moves on
    every read, so a second write would show as a later last_seen."""
    import threading
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    lock, ticks = threading.Lock(), [clock[0]]

    def moving():
        with lock:
            ticks[0] += 0.001
            return ticks[0]
    store.clock = moving
    presence, barrier, errors = parse_presence(HEADERS), threading.Barrier(8), []

    def call():
        barrier.wait()
        try:
            store.ship_for_key(key, presence)
        except Exception as e:  # noqa: BLE001 - any failure is the finding
            errors.append(repr(e))
    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    got = rows(store, ship['id'])
    assert errors == [] and len(got) == 1 and got[0]['last_seen'] == got[0]['first_seen']


def test_no_prompt_path_or_branch_reaches_the_table(env):
    """Gate check: a path, a branch name or prompt-like text smuggled through the client header, or through a label
    header the station doesn't read, never lands; the client is only hook/ or mcp/ plus client_version()'s 12 hex
    digits or 'unknown'."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    smuggled = ['hook/lane-mac-leftovers', 'hook/feature/lane-mac-leftovers', 'mcp/../../Users/me/.ssh',
                'mcp/please summarise my notes', 'hook/0123456789abcdef0']
    for n, client in enumerate(smuggled):
        ship_client(app, key, **{**HEADERS, 'x-superyak-session': f's{n}', 'x-superyak-client': client,
                                 'x-superyak-label': '/Users/me/notes.md'}).get('/api/me')
    for name in ('/Users/me/x', 'what is the key?'):
        ship_client(app, key, **{**HEADERS, 'x-superyak-session': name}).get('/api/me')
    got = rows(store, ship['id'])
    assert [r['name'] for r in got] == [f's{n}' for n in range(len(smuggled))]
    assert {r['client'] for r in got} == {'unknown'} and {r['label'] for r in got} == {None}
    stored = repr([tuple(r.values()) for r in got])
    for needle in ('lane-mac-leftovers', '/Users', 'notes', 'summarise'):
        assert needle not in stored


def watch(client, **body):
    return client.post('/api/ships/me/watch', json=body)


def test_live_and_on_watch_are_computed_from_times(env):
    """R5: on watch is watch_until > now with no liveness check, so a session busy in long tool calls stays on watch
    for its declared minutes, while `live` lapses after 120 s of silence."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    got = watch(ship_client(app, key, **HEADERS), minutes=20, writable=True).json()
    assert got['on_watch'] is True and got['watch_until'] == clock[0] + 1200
    session = lambda: clients[0].get('/api/ships/directory').json()[0]['sessions'][0]
    clock[0] += 121
    assert session()['live'] is False and session()['on_watch'] is True
    clock[0] += 1200 - 121
    assert session()['on_watch'] is False


def test_the_watch_renews_on_each_presence_write(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    client = ship_client(app, key, **HEADERS)
    watch(client, minutes=20, writable=True)
    clock[0] += 900
    client.get('/api/me')
    assert rows(store, ship['id'])[0]['watch_until'] == clock[0] + 1200


def test_only_sessions_can_watch_and_ended_or_lapsed_watches_stay_ended(env):
    """R6: no session header, no watch; a person can't call the route; a write after watch(0) can't bring the watch
    back, and a lease that ran out stays ended until the session declares again."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    assert watch(ship_client(app, key), minutes=20).status_code == 400
    assert clients[0].post('/api/ships/me/watch', json={'minutes': 20}).status_code == 403
    client = ship_client(app, key, **HEADERS)
    watch(client, minutes=20, writable=True)
    assert watch(client, minutes=0).json()['on_watch'] is False
    clock[0] += 31
    client.get('/api/me')
    assert rows(store, ship['id'])[0]['watch_until'] is None
    watch(client, minutes=1, writable=True)
    clock[0] += 61
    client.get('/api/me')
    assert rows(store, ship['id'])[0]['watch_until'] < clock[0]


def test_watch_arguments_are_checked(env):
    """S4: minutes 0-120 (default 20), writable a boolean, a label of 1-40 characters from S2's set. 40 characters
    can never hold a 43-character ship key, so the label needs no separate key check."""
    app, clients, users, clock = env
    ship, key = docked(app.state.store, users[0]['id'])
    client = ship_client(app, key, **HEADERS)
    assert watch(client).json()['watch_until'] == clock[0] + 1200
    for bad in ({'minutes': 121}, {'minutes': -1}, {'minutes': 1.5}, {'minutes': True}, {'writable': 'yes'},
                {'label': 'a\nb'}, {'label': 'x' * 41}, {'label': ''}):
        assert watch(client, **bad).status_code == 400, bad
    assert watch(client, minutes=5, label='lead terminal').json()['label'] == 'lead terminal'


def test_a_full_table_never_grows_even_when_every_row_is_on_watch(env):
    """Commit review (resource cap): pruning never deletes a session on watch, so with every one of a ship's 100 rows on
    watch a new session's row is not written; presence is best effort, so its request still succeeds. With some rows
    off watch, the least recently seen of those makes room as before."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    with store.transaction() as db:
        for n in range(100):
            db.execute('INSERT INTO presence(ship_id,name,client,mode,first_seen,last_seen,watch_minutes,watch_writable,watch_until) '
                       'VALUES(?,?,?,?,?,?,20,1,?)', (ship['id'], f'w{n:03d}', 'unknown', 'unknown', clock[0], clock[0], clock[0] + 1200))
    assert ship_client(app, key, **{**HEADERS, 'x-superyak-session': 'newcomer'}).get('/api/me').status_code == 200
    names = [r['name'] for r in rows(store, ship['id'])]
    assert len(names) == 100 and 'newcomer' not in names
    with store.transaction() as db:
        db.execute("UPDATE presence SET watch_until=NULL, watch_minutes=NULL WHERE ship_id=? AND name='w000'", (ship['id'],))
    assert ship_client(app, key, **{**HEADERS, 'x-superyak-session': 'newcomer'}).get('/api/me').status_code == 200
    names = [r['name'] for r in rows(store, ship['id'])]
    assert len(names) == 100 and 'newcomer' in names and 'w000' not in names


def test_a_ship_has_at_most_ten_sessions_on_watch(env):
    """Commit review (resource cap): the eleventh session to declare a watch is refused, naming the cap; renewing one
    already on watch is not a new watch; once one ends, another may start."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    on = lambda n, minutes=20: watch(ship_client(app, key, **{**HEADERS, 'x-superyak-session': f's{n}'}), minutes=minutes)
    assert all(on(n).status_code == 200 for n in range(10))
    refused = on(10)
    assert refused.status_code == 429 and '10' in refused.json()['error']
    assert on(3, 30).status_code == 200                     # a renewal, not a new watch
    assert on(4, 0).status_code == 200                      # one ends
    assert on(10).status_code == 200
