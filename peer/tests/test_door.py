from fastapi.testclient import TestClient
from superyak_peer.app import create_app
from superyak_peer.door import create_door


def door_and_station(tmp_path):
    app = create_app(tmp_path / 'peer', clock=lambda: 1000000.0, allowed_origins=['http://testserver'])
    door = TestClient(create_door(tmp_path / 'peer', clock=lambda: 1000000.0), base_url='https://door.example:8443')
    return app, door


def test_door_creates_requests_and_reports_status(tmp_path):
    app, door = door_and_station(tmp_path)
    created = door.post('/api/access-requests', json={'name': 'Jenn', 'contact': 'jenn@example.org', 'note': 'hi'})
    assert created.status_code == 201
    request = created.json()
    assert door.get(f'/api/access-requests/{request["id"]}', params={'secret': request['secret']}).json()['status'] == 'pending'
    assert [r['name'] for r in app.state.store.pending_access_requests()] == ['Jenn']


def test_door_serves_nothing_else_and_ignores_sessions(tmp_path):
    app, door = door_and_station(tmp_path)
    store = app.state.store
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    session = store.login('andy', 'long-password-andy', 'test')
    door.cookies.set('superyak_session', session['token'])
    request = door.post('/api/access-requests', json={'name': 'Jenn', 'contact': 'j', 'note': ''}).json()
    for method, path in [('GET', '/'), ('GET', '/api/me'), ('GET', '/api/access-requests'), ('POST', f'/api/access-requests/{request["id"]}/approve'),
                         ('GET', '/api/chats'), ('POST', '/api/login'), ('GET', '/assets/app.js'), ('POST', '/api/dockings'), ('GET', '/api/ships')]:
        response = door.request(method, path, headers={'x-csrf-token': session['csrf_token']})
        assert response.status_code in (404, 405), (method, path, response.status_code)
    assert store.pending_access_requests()[0]['name'] == 'Jenn'


def test_door_bounds_request_bodies(tmp_path):
    app, door = door_and_station(tmp_path)
    body = b'{"name": "' + b'x' * 20000 + b'"}'
    assert door.post('/api/access-requests', content=body, headers={'content-type': 'application/json'}).status_code == 413
