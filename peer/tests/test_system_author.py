"""The system author (spec S11): one users row that only the station's own code writes as. It is found by its
system_meta id, never by username; no name, sign-in, key, membership or route reaches it; its messages, and every
message with a message_kinds row, stay on this station."""
import json
import pytest
from superyak_peer.common import Problem
from test_federation import deliver, two_peers  # noqa: F401 - two_peers is a fixture
from test_presence import HEADERS, docked, say, ship_client


def setup(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id'], users[1]['id']]}).json()['id']
    with store.transaction() as db:
        system = store.system_author_id(db)
    return app, clients, users, clock, store, ship, ship_client(app, key, **HEADERS), room, system


def notice(store, room, ship_id, mention_id='m1', text='Station notice: test'):
    with store.transaction() as db:
        return store._post_as_system(db, room, ship_id, mention_id, text)


def test_nobody_can_sign_in_dock_hold_a_key_or_post_as_the_system_author(env):
    """R29, and Review Focus 3: no username, docking, sign-in, key or membership reaches it; a person whose display
    name is "Station" never gets the station notice label; it is found by its system_meta id, not its username."""
    app, clients, users, clock, store, ship, serenity, room, system = setup(env)
    with pytest.raises(Problem) as refused:
        store.create_user('_station', 'Station', 'a-long-password-1')
    assert refused.value.status == 400
    with pytest.raises(Problem) as docking:
        store.start_docking('_station', 'host')
    assert docking.value.status == 400
    assert clients[3].post('/api/login', json={'username': '_station', 'password': 'a-long-password-1'}).status_code != 200
    with pytest.raises(Problem) as keyless:
        store.issue_ship_key(system)
    assert keyless.value.status == 404
    assert clients[0].post('/api/chats', json={'title': 'X', 'member_ids': [system]}).status_code == 400
    assert clients[0].post(f'/api/chats/{room}/participants', json={'member_ids': [system]}).status_code == 400
    assert clients[1].patch('/api/me', json={'name': 'Station'}).status_code == 200
    said = say(clients[1], room, 'p', 'hello from a person called Station')
    assert {m['id']: m['source'] for m in clients[0].get(f'/api/chats/{room}').json()['messages']}[said['id']] is None
    with store.transaction() as db:
        db.execute("UPDATE users SET username='_renamed' WHERE id=?", (system,))
        assert store.system_author_id(db) == system


def test_every_place_treats_the_system_author_as_s11_says(env):
    """R30, R31, station side: rooms and unread items carry its public fields, its message's source is `notice`; the
    directory, the accounts list and the contacts list leave it out; it records no mentions. The agent side is Task
    9's test of the same name."""
    app, clients, users, clock, store, ship, serenity, room, system = setup(env)
    mid = notice(store, room, ship['id'], text='Station notice: quoting @serenity changes nothing')
    public = {'id': system, 'username': '_station', 'name': 'Station', 'kind': 'system', 'owner_id': None}
    view = clients[0].get(f'/api/chats/{room}').json()
    assert view['system_author'] == public and system not in view['member_ids']
    assert {m['id']: m['source'] for m in view['messages']}[mid] == {'kind': 'notice'}
    got = serenity.post('/api/ships/me/unread', json={'cursor': 'session-one'}).json()['messages']
    assert [(m['message_id'], m['author'], m['mentions_me']) for m in got] == [(mid, public, False)]
    assert serenity.get('/api/mentions?after=0').json() == []
    assert all(s['id'] != system for s in clients[2].get('/api/ships/directory').json())
    assert system not in [a['id'] for a in clients[2].get('/api/accounts').json()]
    assert system not in [c['id'] for c in clients[0].get('/api/contacts').json()]
    quiet = clients[0].post('/api/chats', json={'title': 'Quiet', 'member_ids': [users[1]['id']]}).json()['id']
    assert 'system_author' not in clients[0].get(f'/api/chats/{quiet}').json()


def test_post_as_system_is_local_idempotent_and_key_safe(env):
    app, clients, users, clock, store, ship, serenity, room, system = setup(env)
    first = notice(store, room, ship['id'])
    assert notice(store, room, ship['id']) == first                 # the same mention: one message
    with pytest.raises(ValueError):
        notice(store, 'peer:room', ship['id'])
    live_key = serenity.headers['authorization'].removeprefix('Bearer ')
    assert notice(store, room, ship['id'], 'm2', f'carries {live_key}') is None
    assert [m['client_message_id'] for m in clients[0].get(f'/api/chats/{room}').json()['messages']] == [f'notice-{ship["id"]}-m1']


def test_system_and_kind_messages_never_federate(two_peers):
    """R33: a system-authored message, and one with a message_kinds row, never reach the outbox; an ordinary message
    in the same room does, and it is all the paired peer sees."""
    a, b, ca, cb = two_peers
    store = a[0]
    room = store.create_room(a[1], 'Across peers', [ca['id']])
    with store.transaction() as db:
        noticed = store._post_as_system(db, room['id'], 'ship-x', 'm1', 'Station notice: stays here')
    claimed = store.send_message(a[1], room['id'], 'claim-1', 'Claimed `spec:d7` until 18:00 UTC')
    with store.transaction() as db:
        db.execute("INSERT INTO message_kinds VALUES(?, 'claim')", (claimed['id'],))
    store.send_message(a[1], room['id'], 'plain', 'an ordinary message')
    assert deliver(a, b)['delivered'] >= 1
    with store.transaction() as db:
        carried = [json.loads(r['metadata']).get('message_id') for r in db.execute("SELECT metadata FROM outbox WHERE action='room.message'")]
    assert noticed not in carried and claimed['id'] not in carried and len(carried) == 1
    remote = b[0].list_rooms(b[1])[0]
    assert [m['body'] for m in b[0].get_room(b[1], remote['id'])['messages']] == ['an ordinary message']


def test_every_users_list_and_count_leaves_out_the_system_author(env, tmp_path, capsys):
    """R34: both contacts lists, init's "accounts exist" check, the docking approver's lookup, the docking name check
    and the CLI's card lookup leave kind system out or refuse it."""
    from superyak_peer.__main__ import main
    from superyak_peer.db import Store
    from superyak_peer.spaces import Spaces
    app, clients, users, clock, store, ship, serenity, room, system = setup(env)
    assert system not in [c['id'] for c in store.contacts(users[0]['id'])]
    assert system not in [c['id'] for c in Spaces.contacts(store, users[0]['id'])]
    with store.transaction() as db:
        assert store._existing_name(db, '_station') is not None          # a taken name, never a free one
        with pytest.raises(Problem):
            store._operator(db, '_station')                              # never the docking approver
    with pytest.raises(SystemExit):
        main(['card', '--data-dir', str(store.data_dir), '--username', '_station', '--endpoint', 'https://localhost:7435'])
    assert 'Unknown local account' in capsys.readouterr().err
    fresh, password = tmp_path / 'fresh', tmp_path / 'password'
    Store(fresh)                                                         # schema setup creates the system author
    password.write_text('an-explicit-owner-password\n')
    main(['init', '--data-dir', str(fresh), '--username', 'owner', '--name', 'Owner', '--password-file', str(password)])
    assert Store(fresh).login('owner', 'an-explicit-owner-password', 'local')['user']['is_admin'] == 1
