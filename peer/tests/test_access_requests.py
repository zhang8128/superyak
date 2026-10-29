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


def test_a_decided_or_expired_request_keeps_its_name_but_not_its_contact_after_the_retention(env):
    """fix:door-request-retention (visitor access spec §1): a decided request's contact, note, token and share link
    are cleared REQUEST_RETENTION after its decision, and an expired one's that long after it expired. Its name, status
    and decision stay, for the station's record. A request still waiting keeps everything."""
    from superyak_peer.access_requests import REQUEST_LIFETIME, REQUEST_RETENTION
    app, clients, _, clock = env
    store, guest, admin = app.state.store, anonymous(app), clients[2]
    approved = submit(guest, name='Ann', contact='ann@example.org').json()
    denied = submit(guest, name='Dee', contact='dee@example.org').json()
    submit(guest, name='Wes', contact='wes@example.org')
    admin.post(f'/api/access-requests/{approved["id"]}/approve', json={})
    admin.post(f'/api/access-requests/{denied["id"]}/deny', json={})

    def rows():
        with store.transaction() as db:
            return {r['name']: dict(r) for r in db.execute('SELECT * FROM access_requests')}
    assert rows()['Ann']['token']                       # approved, its token not yet picked up
    clock[0] += REQUEST_RETENTION - 1
    assert store.sweep_access_requests() == 0
    clock[0] += 2
    assert store.sweep_access_requests() == 2
    kept = rows()
    for name, status in (('Ann', 'approved'), ('Dee', 'denied')):
        assert (kept[name]['contact'], kept[name]['note'], kept[name]['token'], kept[name]['status']) == ('', '', None, status)
        assert kept[name]['decided_by'] and kept[name]['decided']
    assert kept['Wes']['contact'] == 'wes@example.org'  # expired at 7 days, kept until 7 days + the retention
    clock[0] += REQUEST_LIFETIME
    assert store.sweep_access_requests() == 1 and rows()['Wes'] | {'contact': '', 'note': ''} == rows()['Wes']
    assert store.sweep_access_requests() == 0           # a second sweep finds nothing left to clear


def test_the_door_sweep_command_says_how_many_it_cleared(tmp_path):
    import subprocess
    import sys
    from superyak_peer.db import Store
    Store(tmp_path / 'peer')
    done = subprocess.run([sys.executable, '-m', 'superyak_peer', 'station-door-sweep', '--data-dir', str(tmp_path / 'peer')],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == 'Cleared the contact and note of 0 access requests past their retention.'


def test_the_door_sweep_refuses_a_data_dir_without_a_database(tmp_path):
    """Serenity, on door-request-retention: a moved or mistyped --data-dir must fail the unit, so OnFailure alerts,
    not sweep a new empty database, print 0 and leave §1's promise broken in silence. Nothing is created there."""
    import subprocess
    import sys
    moved, empty = tmp_path / 'moved', tmp_path / 'empty'
    empty.mkdir()
    for data_dir in (moved, empty):
        done = subprocess.run([sys.executable, '-m', 'superyak_peer', 'station-door-sweep', '--data-dir', str(data_dir)],
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 1 and str(data_dir / 'peer.sqlite3') in done.stderr, done.stderr
        assert done.stdout == ''
    assert not moved.exists() and list(empty.iterdir()) == []
