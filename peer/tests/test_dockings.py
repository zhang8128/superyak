from fastapi.testclient import TestClient


def anonymous(app):
    return TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})


def bearer(app, key):
    return TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver', 'authorization': f'Bearer {key}'})


def start(app, name='serenity', machine='andy-mac'):
    response = anonymous(app).post('/api/dockings', json={'ship_name': name, 'machine': machine})
    assert response.status_code == 201, response.text
    return response.json()


def status(app, docking):
    return anonymous(app).get(f'/api/dockings/{docking["id"]}', params={'secret': docking['secret']}).json()


def confirm(client, docking):
    return client.post(f'/api/dockings/{docking["id"]}/confirm', json={'code': docking['code']})


def test_docking_confirmed_by_a_person_releases_the_key_once(env):
    app, clients, users, clock = env
    docking = start(app)
    assert docking['confirm_url'] == f'http://testserver/#dock?code={docking["code"]}'
    assert status(app, docking) == {'status': 'waiting'}
    preview = clients[0].get(f'/api/dockings/code/{docking["code"]}').json()
    assert preview == {'id': docking['id'], 'ship_name': 'serenity', 'machine': 'andy-mac', 'expires': docking['expires'], 'redock': False}
    ship = confirm(clients[0], docking).json()
    assert (ship['username'], ship['name'], ship['kind'], ship['owner_id']) == ('serenity', 'Serenity', 'ship', users[0]['id'])
    first = status(app, docking)
    assert first['status'] == 'confirmed' and first['ship']['id'] == ship['id'] and first['key']
    assert status(app, docking) == {'status': 'collected'}
    assert bearer(app, first['key']).get('/api/me').json()['username'] == 'serenity'


def test_code_is_single_use_and_expires(env):
    app, clients, users, clock = env
    used = start(app, 'defiant')
    assert confirm(clients[0], used).status_code == 200
    assert confirm(clients[0], used).status_code == 404
    late = start(app, 'rio-grande')
    clock[0] += 601
    assert clients[1].get(f'/api/dockings/code/{late["code"]}').status_code == 404
    assert status(app, late) == {'status': 'expired'}


def test_redocking_your_own_ship_replaces_its_key(env):
    app, clients, users, clock = env

    def dock():
        docking = start(app, 'serenity')
        assert confirm(clients[0], docking).status_code == 200
        return status(app, docking)['key']
    old = dock()
    again = start(app, 'serenity')
    assert clients[0].get(f'/api/dockings/code/{again["code"]}').json()['redock'] is True
    new = dock()
    assert bearer(app, old).get('/api/me').status_code == 401
    assert bearer(app, new).get('/api/me').status_code == 200


def test_names_of_other_ships_or_people_cannot_be_taken(env):
    app, clients, users, clock = env
    confirm(clients[0], start(app, 'serenity'))
    assert confirm(clients[1], start(app, 'serenity')).status_code == 409
    assert confirm(clients[1], start(app, 'doctor')).status_code == 409


def test_invalid_names_ship_keys_and_rate_limit(env):
    app, clients, users, clock = env
    guest = anonymous(app)
    for bad in ['s', 'Serenity', '-x', 'a' * 33, 'odo!']:
        assert guest.post('/api/dockings', json={'ship_name': bad, 'machine': 'm'}).status_code == 400
    ship = app.state.store.create_station_ship('odo', 'Odo')
    key = app.state.store.issue_ship_key(ship['id'])
    docking = start(app, 'defiant')
    assert confirm(bearer(app, key), docking).status_code == 403
    for n in range(19):          # 'defiant' was the first of 20 this hour
        start(app, f'ship-{n}')
    assert guest.post('/api/dockings', json={'ship_name': 'one-more', 'machine': 'm'}).status_code == 429


def pending_key(app, docking):
    # Read the confirmed key straight from the table, without collecting it through the status route.
    with app.state.store.transaction() as db:
        return db.execute('SELECT key FROM dockings WHERE id=?', (docking['id'],)).fetchone()['key']


def test_uncollected_key_is_revoked_after_an_hour(env):
    app, clients, users, clock = env
    docking = start(app, 'serenity')
    assert confirm(clients[0], docking).status_code == 200
    key = pending_key(app, docking)
    assert key
    assert bearer(app, key).get('/api/me').json()['username'] == 'serenity'
    clock[0] += 3601
    assert status(app, docking) == {'status': 'expired'}
    assert bearer(app, key).get('/api/me').status_code == 401
    assert pending_key(app, docking) is None


def test_collected_key_survives_the_uncollected_sweep(env):
    app, clients, users, clock = env
    docking = start(app, 'serenity')
    assert confirm(clients[0], docking).status_code == 200
    key = status(app, docking)['key']
    clock[0] += 3601
    assert status(app, docking) == {'status': 'collected'}
    start(app, 'defiant')            # starting another docking sweeps too
    assert bearer(app, key).get('/api/me').json()['username'] == 'serenity'


def test_the_status_poll_takes_its_secret_in_a_header_or_for_now_the_query(env):
    """Public route spec 4: X-Superyak-Secret keeps the secret out of URLs; ?secret= still works for one release.
    The header wins when both are sent."""
    app, clients, users, clock = env
    docking = start(app)
    poll = f'/api/dockings/{docking["id"]}'
    assert anonymous(app).get(poll, headers={'x-superyak-secret': docking['secret']}).json() == {'status': 'waiting'}
    assert anonymous(app).get(poll, params={'secret': docking['secret']}).json() == {'status': 'waiting'}
    assert anonymous(app).get(poll, headers={'x-superyak-secret': 'wrong'}).status_code == 404
    assert anonymous(app).get(poll, headers={'x-superyak-secret': 'wrong'}, params={'secret': docking['secret']}).status_code == 404
    assert confirm(clients[0], docking).status_code == 200
    assert anonymous(app).get(poll, headers={'x-superyak-secret': docking['secret']}).json()['key']
