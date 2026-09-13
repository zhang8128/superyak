import base64
from fastapi.testclient import TestClient

def test_other_user_and_admin_cannot_read_private_draft(peer_clients):
    patient, doctor, organizer = peer_clients
    layer = patient.post('/api/layers', json={'title': 'Private', 'body': 'original'}).json()
    assert doctor.get('/api/layers/' + layer['id']).status_code == 404
    assert organizer.get('/api/layers/' + layer['id']).status_code == 404

def test_snapshot_conflict_public_withdrawal_and_history(env):
    app, clients, users, _ = env
    patient, doctor = clients[:2]
    layer = patient.post('/api/layers', json={'title': 'Update', 'body': 'original', 'public': True, 'audience_users': [users[1]['id']]}).json()
    key = layer['id']
    assert patient.post(f'/api/layers/{key}/activate', json={'version': 1}).status_code == 200
    assert patient.put(f'/api/layers/{key}', json={'version': 1, 'title': 'Update', 'body': 'private edit'}).json()['version'] == 2
    assert patient.put(f'/api/layers/{key}', json={'version': 1, 'body': 'stale'}).status_code == 409
    visitor = TestClient(app)
    assert visitor.get(f'/public/layers/{key}').json()['body'] == 'original'
    assert 'owner_id' not in visitor.get(f'/public/layers/{key}').json()
    assert doctor.get(f'/api/shared/layers/{key}').json()['body'] == 'original'
    assert patient.post(f'/api/layers/{key}/withdraw', json={}).status_code == 200
    assert visitor.get(f'/public/layers/{key}').status_code == 404
    assert doctor.get(f'/api/shared/layers/{key}').status_code == 404
    assert patient.get(f'/api/layers/{key}/revisions').json()[0]['body'] == 'original'
    events = app.state.store.events_since(0)
    assert [e['kind'] for e in events] == ['layer.activated', 'layer.withdrawn']
    assert events[1]['resource_version'] > events[0]['resource_version']

def test_organization_membership_and_overlapping_grants(env):
    _, clients, users, _ = env
    patient, doctor, admin, family = clients
    org = admin.post('/api/spaces', json={'name': 'Research to the People', 'kind': 'organization', 'member_ids': [users[0]['id'], users[1]['id']]}).json()
    layer = patient.post('/api/layers', json={'title': 'Update', 'body': 'shared', 'audience_users': [users[1]['id']], 'audience_spaces': [org['id']]}).json()
    key = layer['id']
    patient.post(f'/api/layers/{key}/activate', json={'version': 1})
    assert doctor.get(f'/api/shared/layers/{key}').json()['access_routes'] == ['person', 'space:' + org['id']]
    assert admin.get(f'/api/layers/{key}').status_code == 404
    assert family.get(f'/api/shared/layers/{key}').status_code == 404
    assert admin.patch('/api/spaces/' + org['id'], json={'name': 'Wilhelm Foundation'}).status_code == 200
    assert doctor.get(f'/api/shared/layers/{key}').json()['access_routes'] == ['person', 'space:' + org['id']]
    patient.put(f'/api/layers/{key}', json={'version': 1, 'audience_users': []})
    patient.post(f'/api/layers/{key}/activate', json={'version': 2})
    assert doctor.get(f'/api/shared/layers/{key}').json()['access_routes'] == ['space:' + org['id']]
    admin.post('/api/spaces/' + org['id'] + '/members', json={'user_id': users[3]['id']})
    assert family.get(f'/api/shared/layers/{key}').status_code == 200
    patient.post(f'/api/layers/{key}/withdraw', json={})
    assert doctor.get(f'/api/shared/layers/{key}').status_code == 404

def test_files_require_owned_explicit_release_and_limits(env):
    app, clients, _, _ = env
    patient, doctor = clients[:2]
    payload = {'name': 'notes.txt', 'media_type': 'text/plain', 'content_base64': base64.b64encode(b'hello').decode()}
    uploaded = patient.post('/api/files', json=payload).json()
    key = uploaded['id']
    assert uploaded['digest'] == '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'
    assert doctor.get('/api/files/' + key).status_code == 404
    assert patient.post('/api/files', json={**payload, 'name': '../secret.txt'}).status_code == 400
    assert patient.post('/api/files', json={**payload, 'content_base64': base64.b64encode(b'x' * (4 * 1024 * 1024 + 1)).decode()}).status_code == 413
    assert doctor.post('/api/layers', json={'title': 'stolen', 'attachment_ids': [key]}).status_code == 404
    layer = patient.post('/api/layers', json={'title': 'Public', 'public': True, 'attachment_ids': [key]}).json()
    visitor = TestClient(app)
    route = '/public/layers/' + layer['id'] + '/files/' + key
    assert visitor.get(route).status_code == 404
    patient.post('/api/layers/' + layer['id'] + '/activate', json={'version': 1})
    download = visitor.get(route)
    assert download.content == b'hello'
    assert download.headers['content-disposition'].startswith('attachment;')
    assert download.headers['x-content-type-options'] == 'nosniff'
    patient.post('/api/layers/' + layer['id'] + '/withdraw', json={})
    assert visitor.get(route).status_code == 404

def test_revoke_active_routes_never_publishes_private_replacement(env):
    app, clients, users, _ = env
    patient, doctor, admin, _ = clients
    org = admin.post('/api/spaces', json={'name': 'Team', 'kind': 'organization', 'member_ids': [users[0]['id'], users[1]['id']]}).json()
    layer = patient.post('/api/layers', json={'title': 'Update', 'body': 'released', 'public': True, 'audience_users': [users[1]['id']], 'audience_spaces': [org['id']]}).json()
    key = layer['id']
    patient.post(f'/api/layers/{key}/activate', json={'version': 1})
    patient.put(f'/api/layers/{key}', json={'version': 1, 'body': 'new private words'})
    revoked = patient.post(f'/api/layers/{key}/revoke', json={'revision': 1, 'public': True, 'user_ids': [users[1]['id']]} )
    assert revoked.status_code == 200
    assert TestClient(app).get(f'/public/layers/{key}').status_code == 404
    shared = doctor.get(f'/api/shared/layers/{key}').json()
    assert shared['body'] == 'released'
    assert shared['access_routes'] == ['space:' + org['id']]
    assert patient.get(f'/api/layers/{key}').json()['body'] == 'new private words'
    assert patient.post(f'/api/layers/{key}/revoke', json={'revision': 1, 'space_ids': [org['id']]}).status_code == 409
    assert patient.post(f'/api/layers/{key}/revoke', json={'revision': 2, 'space_ids': [org['id']]}).status_code == 200
    assert doctor.get(f'/api/shared/layers/{key}').status_code == 404

def test_care_circle_audience_is_frozen_at_release(env):
    _, clients, users, _ = env
    patient, doctor, _, family = clients
    space = patient.post('/api/spaces', json={'name': 'Care', 'kind': 'care-circle', 'member_ids': [users[1]['id']]}).json()
    layer = patient.post('/api/layers', json={'title': 'Selected people', 'audience_spaces': [space['id']]}).json()
    patient.post('/api/layers/' + layer['id'] + '/activate', json={'version': 1})
    patient.post('/api/spaces/' + space['id'] + '/members', json={'user_id': users[3]['id']})
    assert family.get('/api/shared/layers/' + layer['id']).status_code == 404
    assert doctor.get('/api/shared/layers/' + layer['id']).status_code == 200

def test_revocation_removes_obsolete_audience_label(env):
    _, clients, users, _ = env
    space = clients[0].post('/api/spaces', json={'name': 'Team', 'kind': 'organization'}).json()
    layer = clients[0].post('/api/layers', json={'audience_spaces': [space['id']]}).json()
    clients[0].post('/api/layers/' + layer['id'] + '/activate', json={'version': 1})
    result = clients[0].post('/api/layers/' + layer['id'] + '/revoke', json={'revision': 1, 'space_ids': [space['id']]}).json()
    assert result['audience_notes'] == []
