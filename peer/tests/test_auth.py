from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
import pytest

def test_local_demo_uses_normal_sessions_without_exposing_credentials(tmp_path):
    from superyak_peer.__main__ import seed_demo
    from superyak_peer.app import create_app
    from superyak_peer.common import Problem
    target = tmp_path / 'demo'
    seed_demo(target)
    credentials = (target / 'demo-credentials.json').read_bytes()
    app = create_app(target, local_demo=True)
    client = TestClient(app, base_url='http://127.0.0.1:7435', client=('127.0.0.1', 1234), headers={'origin': 'http://127.0.0.1:7435'})
    accounts = client.get('/api/local-demo').json()['accounts']
    assert {a['username'] for a in accounts} == {'patient', 'family', 'doctor', 'organizer'}
    assert all(set(a) == {'username', 'name'} for a in accounts)
    assert client.get('/api/home').status_code == 401
    assert client.post('/api/local-demo/login', json={'username': 'patient'}, headers={'origin': 'https://evil.test'}).status_code == 403
    assert client.post('/api/local-demo/login', json={'username': 'unknown'}).status_code == 400
    result = client.post('/api/local-demo/login', json={'username': 'patient'})
    assert result.status_code == 200
    assert 'HttpOnly' in result.headers['set-cookie']
    assert 'password' not in result.text
    me = client.get('/api/me').json()
    assert me['username'] == 'patient'
    assert client.post('/api/layers', json={'title': 'secret'}).status_code == 403
    layer = client.post('/api/layers', json={'title': 'secret'}, headers={'x-csrf-token': me['csrf_token']}).json()
    previous_token = client.cookies.get('superyak_session')
    assert client.post('/api/local-demo/login', json={'username': 'doctor'}).status_code == 200
    assert client.get('/api/me').json()['username'] == 'doctor'
    assert layer['id'] not in client.get('/api/home').text
    assert client.get('/api/layers/' + layer['id']).status_code == 404
    with pytest.raises(Problem) as expired:
        app.state.store.session(previous_token)
    assert expired.value.status == 401
    assert (target / 'demo-credentials.json').read_bytes() == credentials
    remote = TestClient(app, base_url='http://127.0.0.1:7435', client=('192.0.2.5', 1234), headers={'origin': 'http://127.0.0.1:7435'})
    assert remote.get('/api/local-demo').status_code == 403
    assert remote.post('/api/local-demo/login', json={'username': 'organizer'}).status_code == 403

def test_local_demo_is_explicit_and_rejects_ordinary_state_or_remote_origins(tmp_path):
    from superyak_peer.__main__ import seed_demo
    from superyak_peer.app import create_app
    target = tmp_path / 'demo'
    seed_demo(target)
    ordinary = TestClient(create_app(target), base_url='http://127.0.0.1:7435', headers={'origin': 'http://127.0.0.1:7435'})
    assert ordinary.get('/api/local-demo').status_code == 404
    assert ordinary.post('/api/local-demo/login', json={'username': 'patient'}).status_code == 404
    assert ordinary.get('/api/home').status_code == 401
    with pytest.raises(ValueError, match='loopback'):
        create_app(target, local_demo=True, allowed_origins=['https://demo.example'])
    unseeded = tmp_path / 'ordinary'
    with pytest.raises(ValueError, match='demo state'):
        create_app(unseeded, local_demo=True)
    assert not unseeded.exists()

def test_application_factory_exists():
    import importlib.util
    assert importlib.util.find_spec('superyak_peer.app') is not None, 'The local application factory is missing'

def test_password_checks_cookie_logout_and_expiry(env):
    app, clients, users, clock = env
    patient = clients[0]
    assert 'password' not in patient.get('/api/me').text
    outsider = TestClient(app)
    bad = outsider.post('/api/login', headers={'origin': 'http://testserver'}, json={'username': 'patient', 'password': 'wrong'})
    unknown = outsider.post('/api/login', headers={'origin': 'http://testserver'}, json={'username': 'missing', 'password': 'wrong'})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()
    login = outsider.post('/api/login', headers={'origin': 'http://testserver'}, json={'username': 'patient', 'password': 'long-password-patient'})
    assert 'HttpOnly' in login.headers['set-cookie'] and 'SameSite=strict' in login.headers['set-cookie']
    assert patient.post('/api/logout').status_code == 200
    assert patient.get('/api/me').status_code == 401
    clock[0] += 86401
    assert clients[1].get('/api/me').status_code == 401

def test_csrf_and_origin_denied(env):
    app, clients, _, _ = env
    client = clients[0]
    assert client.post('/api/layers', json={'title': 'x'}, headers={'x-csrf-token': ''}).status_code == 403
    assert client.post('/api/layers', json={'title': 'x'}, headers={'origin': 'https://evil.test'}).status_code == 403
    assert TestClient(app).post('/api/login', json={'username': 'patient', 'password': 'long-password-patient'}).status_code == 403

def test_login_is_bounded(env):
    app, _, _, _ = env
    client = TestClient(app, headers={'origin': 'http://testserver'})
    codes = [client.post('/api/login', json={'username': 'patient', 'password': 'wrong'}).status_code for _ in range(12)]
    assert codes[-1] == 429

def test_invitation_one_use_race_and_expiry(env):
    app, clients, _, clock = env
    assert clients[0].post('/api/invitations', json={}).status_code == 403
    invitation = clients[2].post('/api/invitations', json={'expires_in': 60}).json()
    def redeem(i):
        with TestClient(app, headers={'origin': 'http://testserver'}) as client:
            return client.post('/api/invitations/redeem', json={'token': invitation['token'], 'username': f'new{i}', 'name': 'New', 'password': 'a-long-new-password'}).status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(redeem, range(2))) == [201, 400]
    invitation = clients[2].post('/api/invitations', json={'expires_in': 60}).json()
    clock[0] += 61
    assert TestClient(app, headers={'origin': 'http://testserver'}).post('/api/invitations/redeem', json={'token': invitation['token'], 'username': 'late', 'name': 'Late', 'password': 'a-long-new-password'}).status_code == 400

def test_admin_metadata_and_independent_homes(env):
    _, clients, users, _ = env
    layer = clients[0].post('/api/layers', json={'title': 'secret', 'body': 'private-body'}).json()
    assert layer['id'] in clients[0].get('/api/home').text
    assert layer['id'] not in clients[2].get('/api/home').text
    accounts = clients[2].get('/api/accounts')
    assert accounts.status_code == 200
    assert 'private-body' not in accounts.text and 'password' not in accounts.text
    assert clients[0].get('/api/accounts').status_code == 403

def test_invalid_shapes_and_large_requests_are_safe(env):
    app, clients, users, _ = env
    for route, data in [('/api/spaces', {'name': 'Invalid', 'kind': 'project', 'member_ids': 'oops'}), ('/api/files', {'name': 'x', 'media_type': [], 'content_base64': ''}), ('/api/spaces', {'name': 'Invalid', 'kind': 'project', 'member_ids': [None]})]:
        response = clients[0].post(route, json=data)
        assert response.status_code == 400
    response = clients[0].post('/api/layers', content=b'x' * (6 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert clients[0].post('/api/layers', content='not json').status_code == 400
    assert clients[0].post('/api/layers', json=[]).status_code == 400

def test_actor_spoofing_and_unauthenticated_reads_fail(env):
    app, clients, users, _ = env
    created = clients[0].post('/api/layers', json={'title': 'Forgery', 'owner_id': users[1]['id']})
    assert created.status_code == 400
    for path in ['/api/home', '/api/layers', '/api/chats', '/api/files', '/api/contacts', '/api/spaces']:
        assert TestClient(app).get(path).status_code == 401

def test_explicit_origin_configuration_rejects_forged_host(env):
    from superyak_peer.app import create_app
    app, _, _, _ = env
    secured = create_app(app.state.store.data_dir, allowed_origins=['http://testserver'])
    client = TestClient(secured, base_url='http://attacker.test', headers={'origin': 'http://attacker.test'})
    assert client.post('/api/login', json={'username': 'patient', 'password': 'long-password-patient'}).status_code == 403
    assert client.get('/api/me').status_code == 403

def test_factory_default_rejects_unrecognized_host(tmp_path):
    from superyak_peer.app import create_app
    app = create_app(tmp_path / 'peer')
    response = TestClient(app, base_url='http://attacker.test').get('/api/me')
    assert response.status_code == 403

def test_name_correction_keeps_identity_and_grants(env):
    _, clients, users, _ = env
    patient, doctor = clients[:2]
    layer = patient.post('/api/layers', json={'title': 'Update', 'audience_users': [users[1]['id']]}).json()
    patient.post('/api/layers/' + layer['id'] + '/activate', json={'version': 1})
    renamed = doctor.patch('/api/me', json={'name': 'Corrected Name'})
    assert renamed.status_code == 200
    assert renamed.json()['id'] == users[1]['id']
    assert renamed.json()['name'] == 'Corrected Name'
    assert doctor.get('/api/shared/layers/' + layer['id']).json()['access_routes'] == ['person']
    assert patient.get('/api/layers/' + layer['id']).json()['audience_users'] == [users[1]['id']]

def test_name_correction_records_actual_self_history_without_fabricating_past_entries(env):
    _, clients, users, clock = env
    doctor = clients[1]
    assert doctor.get('/api/me/corrections').json() == []

    clock[0] += 30
    assert doctor.patch('/api/me', json={'name': 'Morgan Reed'}).status_code == 200
    history = doctor.get('/api/me/corrections')
    assert history.status_code == 200
    assert history.json() == [{
        'id': 1,
        'user_id': users[1]['id'],
        'old_name': 'Doctor',
        'new_name': 'Morgan Reed',
        'actor_id': users[1]['id'],
        'created': clock[0],
    }]

    # A no-op name save is not a correction and does not invent another event.
    doctor.patch('/api/me', json={'name': 'Morgan Reed'})
    assert doctor.get('/api/me/corrections').json() == history.json()

    # The owner/account-support role has no route for another person's history.
    assert clients[2].get('/api/me/corrections').json() == []

def test_malformed_origin_is_public_safe_denial(env):
    _, clients, _, _ = env
    response = clients[0].post('/api/layers', headers={'origin': 'http://['}, json={'title': 'x'})
    assert response.status_code == 403

def test_invalid_unicode_json_is_rejected_before_mutation(env):
    import json
    app, clients, users, _ = env
    patient, doctor = clients[:2]
    for payload in [{'title': 'bad\ud800', 'public': True}, {'title': 'valid', 'body': '\udfff'}, {'title': 'valid', 'audience_users': ['\ud800']}, {'title': 'valid', 'unused': {'\ud800': 'value'}}]:
        response = patient.post('/api/layers', content=json.dumps(payload), headers={'content-type': 'application/json'})
        assert response.status_code == 400
    assert app.state.store.list_layers(users[0]['id']) == []
    assert doctor.get('/api/home').status_code == 200
    assert doctor.get('/api/shared/layers').json() == []
