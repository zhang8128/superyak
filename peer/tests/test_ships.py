import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from superyak_peer.__main__ import main as cli
from superyak_peer.db import Store


def ship_client(app, key):
    return TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver', 'authorization': f'Bearer {key}'})


def station_ship(app, username='odo', name='Odo'):
    store = app.state.store
    ship = store.create_station_ship(username, name)
    return ship, store.issue_ship_key(ship['id'])


def test_station_ship_has_no_owner_and_cannot_sign_in(env):
    app, clients, users, _ = env
    ship, _ = station_ship(app)
    assert (ship['kind'], ship['owner_id'], ship['is_admin']) == ('ship', None, 0)
    assert (users[0]['kind'], users[0]['owner_id']) == ('person', None)
    guest = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    assert guest.post('/api/login', json={'username': 'odo', 'password': 'whatever-long-pass'}).status_code == 401


def test_ship_key_reaches_only_room_routes(env):
    app, clients, users, _ = env
    ship, key = station_ship(app)
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id']]}).json()['id']
    odo = ship_client(app, key)
    me = odo.get('/api/me')
    assert me.status_code == 200 and (me.json()['username'], me.json()['kind']) == ('odo', 'ship')
    assert [r['id'] for r in odo.get('/api/chats').json()] == [room]
    assert odo.get(f'/api/chats/{room}').status_code == 200
    sent = odo.post(f'/api/chats/{room}/messages', json={'client_message_id': 'n1', 'body': 'On watch.'})
    assert sent.status_code == 201 and sent.json()['author_id'] == ship['id']
    for method, path, body in [('GET', '/api/home', None), ('GET', '/api/accounts', None), ('GET', '/api/contacts', None),
                               ('POST', '/api/chats', {'title': 'x', 'member_ids': []}),
                               ('POST', f'/api/chats/{room}/participants', {'member_ids': [users[1]['id']]}),
                               ('GET', '/api/access-requests', None), ('POST', '/api/invitations', {}),
                               ('GET', '/api/layers', None), ('GET', '/api/files', None), ('GET', '/api/connections', None)]:
        response = odo.request(method, path, json=body)
        assert response.status_code == 403, (method, path, response.status_code)


def test_bad_or_revoked_key_is_rejected(env):
    app, clients, users, _ = env
    ship, key = station_ship(app)
    assert ship_client(app, 'not-a-key').get('/api/chats').status_code == 401
    odo = ship_client(app, key)
    assert odo.delete('/api/ships/me/key').status_code == 200
    assert odo.get('/api/chats').status_code == 401
    assert clients[0].delete('/api/ships/me/key').status_code == 403


def test_ships_cannot_hold_account_roles_and_are_not_listed_as_accounts(env):
    app, clients, users, _ = env
    ship, _ = station_ship(app)
    with app.state.store.transaction() as db:
        db.execute('UPDATE users SET is_super_admin=1 WHERE id=?', (users[2]['id'],))
    response = clients[2].patch(f'/api/accounts/{ship["id"]}/role', json={'role': 'admin', 'expected_version': 1})
    assert response.status_code == 400
    assert all(account['kind'] == 'person' for account in clients[2].get('/api/accounts').json())


def test_create_ship_cli_writes_a_private_station_config(env, tmp_path):
    app, *_ = env
    config = tmp_path / 'odo' / 'station.json'
    cli(['create-ship', '--data-dir', str(app.state.store.data_dir), '--username', 'odo', '--name', 'Odo',
         '--station', 'http://127.0.0.1:7435', '--origin', 'https://smart.example.ts.net',
         '--workspace', str(tmp_path), '--config', str(config)])
    data = json.loads(config.read_text())
    assert config.stat().st_mode & 0o777 == 0o600
    assert (data['ship'], data['ship_name'], data['owner_id'], data['origin']) == ('odo', 'Odo', None, 'https://smart.example.ts.net')
    assert ship_client(app, data['key']).get('/api/me').json()['username'] == 'odo'


def create_ship_args(app, tmp_path, config, username='odo'):
    return ['create-ship', '--data-dir', str(app.state.store.data_dir), '--username', username, '--name', 'Odo',
            '--station', 'http://127.0.0.1:7435', '--workspace', str(tmp_path), '--config', str(config)]


def ship_usernames(app):
    with app.state.store.transaction() as db:
        return [row['username'] for row in db.execute("SELECT username FROM users WHERE kind='ship'")]


def test_create_ship_claims_the_config_before_creating_the_ship(env, tmp_path):
    app, *_ = env
    stale = tmp_path / 'odo' / 'station.json'
    stale.parent.mkdir()
    stale.write_text('stale\n')
    with pytest.raises(SystemExit):
        cli(create_ship_args(app, tmp_path, stale))
    assert stale.read_text() == 'stale\n' and ship_usernames(app) == []
    fresh = tmp_path / 'odo' / 'fresh.json'
    cli(create_ship_args(app, tmp_path, fresh))
    assert ship_usernames(app) == ['odo']
    assert ship_client(app, json.loads(fresh.read_text())['key']).get('/api/me').json()['username'] == 'odo'


def test_create_ship_leaves_no_config_when_the_ship_cannot_be_created(env, tmp_path):
    app, *_ = env
    cli(create_ship_args(app, tmp_path, tmp_path / 'first.json'))
    again = tmp_path / 'again.json'
    with pytest.raises(SystemExit):
        cli(create_ship_args(app, tmp_path, again))
    assert not again.exists() and ship_usernames(app) == ['odo']


def test_existing_accounts_become_people_on_migration(tmp_path):
    data = tmp_path / 'old'
    data.mkdir(mode=0o700)
    db = sqlite3.connect(data / 'peer.sqlite3')
    db.execute('CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL, salt BLOB NOT NULL, password_hash BLOB NOT NULL, is_admin INTEGER NOT NULL, created REAL NOT NULL)')
    db.execute("INSERT INTO users VALUES('u1','andy','Andy',x'00',x'00',1,1.0)")
    db.commit()
    db.close()
    store = Store(data)
    with store.transaction() as conn:
        row = conn.execute("SELECT kind, owner_id, is_super_admin FROM users WHERE username='andy'").fetchone()
    assert (row['kind'], row['owner_id'], row['is_super_admin']) == ('person', None, 0)
