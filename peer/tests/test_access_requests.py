from fastapi.testclient import TestClient


def anonymous(app):
    return TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})


def submit(client, **override):
    data = {'name': 'Jenn', 'contact': 'jenn@example.org', 'note': 'Andy asked me to join', **override}
    return client.post('/api/access-requests', json=data)


def test_request_is_approved_by_admin_and_token_is_picked_up_once(env):
    app, clients, users, _ = env
    guest = anonymous(app)
    response = submit(guest)
    assert response.status_code == 201, response.text
    request = response.json()
    assert set(request) == {'id', 'secret', 'expires'}
    status = guest.get(f'/api/access-requests/{request["id"]}', params={'secret': request['secret']}).json()
    assert status['status'] == 'pending' and 'token' not in status

    admin = clients[2]
    listed = admin.get('/api/access-requests').json()
    assert [(row['name'], row['contact'], row['status']) for row in listed] == [('Jenn', 'jenn@example.org', 'pending')]
    assert 'secret_hash' not in listed[0] and 'token' not in listed[0]
    assert admin.post(f'/api/access-requests/{request["id"]}/approve', json={}).json()['status'] == 'approved'

    first = guest.get(f'/api/access-requests/{request["id"]}', params={'secret': request['secret']}).json()
    assert first['status'] == 'approved' and first['token']
    second = guest.get(f'/api/access-requests/{request["id"]}', params={'secret': request['secret']}).json()
    assert second['status'] == 'approved' and 'token' not in second

    redeemed = guest.post('/api/invitations/redeem', json={'token': first['token'], 'username': 'jenn', 'name': 'Jenn', 'password': 'jenn-chosen-password'})
    assert redeemed.status_code == 201, redeemed.text
    assert redeemed.json()['is_admin'] == 0


def test_wrong_secret_and_unknown_request_are_indistinguishable(env):
    app, *_ = env
    guest = anonymous(app)
    request = submit(guest).json()
    wrong = guest.get(f'/api/access-requests/{request["id"]}', params={'secret': 'nope'})
    missing = guest.get('/api/access-requests/unknown', params={'secret': request['secret']})
    assert wrong.status_code == missing.status_code == 404


def test_only_admins_list_and_decide(env):
    app, clients, *_ = env
    request = submit(anonymous(app)).json()
    participant = clients[0]
    assert participant.get('/api/access-requests').status_code == 403
    assert participant.post(f'/api/access-requests/{request["id"]}/approve', json={}).status_code == 403
    assert anonymous(app).get('/api/access-requests').status_code == 401


def test_denied_request_never_yields_a_token(env):
    app, clients, *_ = env
    guest = anonymous(app)
    request = submit(guest).json()
    assert clients[2].post(f'/api/access-requests/{request["id"]}/deny', json={}).json()['status'] == 'denied'
    status = guest.get(f'/api/access-requests/{request["id"]}', params={'secret': request['secret']}).json()
    assert status == {'status': 'denied', 'expires': request['expires'], 'share': None}
    assert clients[2].post(f'/api/access-requests/{request["id"]}/approve', json={}).status_code == 409


def test_requests_expire(env):
    app, clients, _, clock = env
    guest = anonymous(app)
    request = submit(guest).json()
    clock[0] += 604801
    status = guest.get(f'/api/access-requests/{request["id"]}', params={'secret': request['secret']}).json()
    assert status['status'] == 'expired'
    login = clients[2].post('/api/login', json={'username': 'organizer', 'password': 'long-password-organizer'})
    clients[2].headers['x-csrf-token'] = login.json()['csrf_token']
    assert clients[2].post(f'/api/access-requests/{request["id"]}/approve', json={}).status_code == 409


def test_input_limits_and_rate_limit(env):
    app, *_ = env
    guest = anonymous(app)
    assert submit(guest, note='x' * 2001).status_code == 400
    assert submit(guest, name='').status_code == 400
    assert submit(guest, contact='c' * 201).status_code == 400
    assert submit(guest, note='').status_code == 201
    for _ in range(19):
        assert submit(guest).status_code == 201
    assert submit(guest).status_code == 429


def test_pending_listing_for_trusted_local_worker(env):
    app, clients, *_ = env
    request = submit(anonymous(app)).json()
    pending = app.state.store.pending_access_requests()
    assert [(row['id'], row['name']) for row in pending] == [(request['id'], 'Jenn')]
    clients[2].post(f'/api/access-requests/{request["id"]}/deny', json={})
    assert app.state.store.pending_access_requests() == []


import pytest


def station_with_share_link(tmp_path, link):
    from superyak_peer.app import create_app
    path = tmp_path / 'tailscale-share-url'
    if link is not None:
        path.write_text(link + '\n')
    app = create_app(tmp_path / 'peer', clock=lambda: 1000000.0, allowed_origins=['http://testserver'], share_link_file=path)
    app.state.store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    admin = anonymous(app)
    admin.headers['x-csrf-token'] = admin.post('/api/login', json={'username': 'andy', 'password': 'long-password-andy'}).json()['csrf_token']
    return app, admin


def test_approval_releases_the_share_link_once_with_the_invitation(tmp_path):
    app, admin = station_with_share_link(tmp_path, 'https://login.tailscale.com/admin/invite/abc')
    guest = anonymous(app)
    request = submit(guest).json()
    admin.post(f'/api/access-requests/{request["id"]}/approve', json={})
    first = guest.get(f'/api/access-requests/{request["id"]}', params={'secret': request['secret']}).json()
    assert (first['share'], first['share_url']) == ('ready', 'https://login.tailscale.com/admin/invite/abc') and first['token']
    second = guest.get(f'/api/access-requests/{request["id"]}', params={'secret': request['secret']}).json()
    assert second['share'] == 'collected' and 'share_url' not in second and 'token' not in second


@pytest.mark.parametrize('link', [None, 'https://evil.example/invite', ''])
def test_missing_or_invalid_share_link_is_reported_and_announced(tmp_path, link):
    app, admin = station_with_share_link(tmp_path, link)
    guest = anonymous(app)
    request = submit(guest).json()
    admin.post(f'/api/access-requests/{request["id"]}/approve', json={})
    status = guest.get(f'/api/access-requests/{request["id"]}', params={'secret': request['secret']}).json()
    assert status['share'] == 'missing' and 'share_url' not in status and status['token']
    assert admin.get('/api/access-requests').json()[0]['share_status'] == 'missing'
    assert [n['id'] for n in app.state.store.station_notices()] == [f'share-{request["id"]}']
