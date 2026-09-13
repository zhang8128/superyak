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

def test_store_rejects_invalid_unicode_text_and_identifiers_without_persisting(env):
    import pytest
    from superyak_peer.common import Problem
    app, clients, users, _ = env
    store, owner = app.state.store, users[0]['id']
    layer = store.create_layer(owner, {'title': 'Valid', 'body': 'original', 'public': True})
    actions = [lambda: store.create_layer(owner, {'title': '\ud800'}),
               lambda: store.save_layer(owner, layer['id'], {'version': 1, 'body': '\ud800'}),
               lambda: store.create_layer(owner, {'audience_users': ['\ud800']}),
               lambda: store.get_layer(owner, '\ud800')]
    for action in actions:
        with pytest.raises(Problem) as error:
            action()
        assert error.value.status == 400
    assert len(store.list_layers(owner)) == 1
    assert store.get_layer(owner, layer['id'])['version'] == 1
    assert store.get_layer(owner, layer['id'])['body'] == 'original'
    store.activate_layer(owner, layer['id'], 1)
    assert clients[1].get('/api/home').status_code == 200
    for action in [lambda: store.active_layer(layer['id'], '\ud800'),
                   lambda: store.download_file(owner, '\ud800', layer_id=layer['id'], public=True)]:
        with pytest.raises(Problem) as error:
            action()
        assert error.value.status == 400

def test_public_only_account_sees_no_private_audience_metadata(env):
    app, clients, users, _ = env
    patient, doctor, organizer, family = clients
    space = patient.post('/api/spaces', json={'name': 'Private care context', 'kind': 'care-circle', 'member_ids': [users[1]['id']]}).json()
    layer = patient.post('/api/layers', json={'title': 'Public words', 'body': 'Released', 'public': True, 'audience_spaces': [space['id']]}).json()
    key = layer['id']
    patient.post(f'/api/layers/{key}/activate', json={'version': 1})
    public = TestClient(app).get(f'/public/layers/{key}').json()
    visible = organizer.get(f'/api/shared/layers/{key}').json()
    assert visible == {**public, 'resource_version': 1, 'access_routes': ['public']}
    home = organizer.get('/api/home').json()
    assert home['shared_layers'] == [visible]
    assert space['id'] not in organizer.get('/api/home').text
    assert 'Private care context' not in organizer.get('/api/shared/layers').text
    # Named/space recipients receive attribution and their own effective routes,
    # but management lists and other audience identities remain owner-only.
    named = doctor.get(f'/api/shared/layers/{key}').json()
    assert named['owner_id'] == users[0]['id']
    assert named['access_routes'] == ['space:' + space['id'], 'public']
    for field in ('audience_users', 'audience_spaces', 'resolved_space_users', 'audience_notes'):
        assert field not in named
    assert app.state.store.can_deliver_layer(key, users[2]['id'], 1)
    assert not app.state.store.can_deliver_layer(key, users[2]['id'], 2)
    patient.post(f'/api/layers/{key}/withdraw', json={})
    assert not app.state.store.can_deliver_layer(key, users[2]['id'], 1)


def test_authoritative_preview_files_members_and_membership_conflict(env):
    app, clients, users, _ = env
    patient, doctor, organizer, family = clients
    space = patient.post('/api/spaces', json={'name':'Selected circle', 'kind':'care-circle', 'member_ids':[users[1]['id']]}).json()
    file = app.state.store.upload_file(users[0]['id'], 'selected.txt', 'text/plain', base64.b64encode(b'chosen').decode())
    layer = patient.post('/api/layers', json={'attachment_ids':[file['id']], 'audience_spaces':[space['id']]}).json()
    url = '/api/layers/' + layer['id']
    response = patient.get(url + '/preview')
    assert response.status_code == 200
    preview = response.json()
    assert preview['files'][0]['name'] == 'selected.txt'
    assert {m['name'] for m in preview['audience_details'][0]['members']} == {'Patient','Doctor'}
    assert organizer.get(url + '/preview').status_code == 404
    patient.post('/api/spaces/' + space['id'] + '/members', json={'user_id':users[3]['id']})
    assert patient.post(url + '/activate', json={'version':1, 'space_versions':preview['space_versions']}).status_code == 409
    preview = patient.get(url + '/preview').json()
    assert patient.post(url + '/activate', json={'version':1, 'space_versions':preview['space_versions']}).status_code == 200
    patient.delete('/api/spaces/' + space['id'] + '/members/' + users[1]['id'])
    active = patient.get('/api/shared/layers/' + layer['id']).json()
    assert {m['name'] for m in active['audience_details'][0]['members']} == {'Patient','Doctor','Family'}
    assert 'audience_details' not in doctor.get('/api/shared/layers/' + layer['id']).json()
    patient.put(url, json={'version':1, 'body':'new draft'})
    assert patient.post(url + '/activate', json={'version':1, 'space_versions':preview['space_versions']}).status_code == 409
