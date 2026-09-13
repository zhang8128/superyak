"""Selected source attribution conveys no access authority."""
import copy
import json

def selection(patient, **fields):
    layer = patient.post('/api/layers', json={'title': 'Chosen source', 'body': 'Selected words', **fields}).json()
    return layer, {'layer_id': layer['id'], 'kind': 'draft', 'version': 1}

def export(patient, records):
    return patient.post('/api/interchange/export', json={'selections': records})

def test_export_owned_explicit_selection_omits_secrets(env):
    _, (patient, doctor, *_), users, _ = env
    layer, selected = selection(patient)
    patient.post('/api/layers', json={'body': 'UNSELECTED DRAFT SECRET'})
    room = patient.post('/api/chats', json={}).json()
    patient.post(f"/api/chats/{room['id']}/messages", json={'body': 'CHAT SECRET', 'client_message_id': 'one'})
    response = export(patient, [selected])
    assert response.status_code == 200, response.text
    doc = response.json()
    assert len(doc['records']) == 1
    record = doc['records'][0]
    origin = patient.get('/api/me').json()['peer_id']
    assert record['id'] == f"peer:{origin}:layer/{layer['id']}"
    assert record['origin'] == origin
    assert record['source_locator'] == f"peer:{origin}:layer/{layer['id']}?draft=1"
    assert record['content'] == {'title': 'Chosen source', 'body': 'Selected words'}
    assert record['author'] == f"{origin}:{users[0]['id']}"
    assert len(record['source_hash']) == 64
    for forbidden in ('UNSELECTED DRAFT SECRET', 'CHAT SECRET', 'csrf', 'salt', 'password', 'private_key', 'sessions'):
        assert forbidden not in json.dumps(doc)
    assert export(doctor, [selected]).status_code == 404
    assert export(patient, [{**selected, 'version': 2}]).status_code == 409
    assert export(patient, []).status_code == 400

def test_import_retains_attribution_without_grants(env):
    _, (patient, doctor, *_), users, _ = env
    _, selected = selection(patient, public=True, audience_users=[users[1]['id']])
    doc = export(patient, [selected]).json()
    record = doc['records'][0]
    record['revision_of'] = record['id'] + '?draft=0'
    record['correction_of'] = ['peer:historical:record/original']
    result = doctor.post('/api/interchange/import', json=doc)
    assert result.status_code == 201, result.text
    imported = result.json()['records'][0]
    assert imported['record'] == record
    assert doctor.get('/api/sources').json() == [imported]
    assert patient.get('/api/sources').json() == []
    assert doctor.get('/api/layers').json() == []
    assert patient.get('/api/shared/layers').json() == []
    assert doctor.post('/api/interchange/import', json=doc).json()['records'][0]['id'] == imported['id']
    assert doctor.post('/api/interchange/export', json={'source_ids': [imported['id']]}).json() == doc
    assert patient.post('/api/interchange/export', json={'source_ids': [imported['id']]}).status_code == 404
    assert patient.get(f"/public/layers/{imported['id']}").status_code == 404

def test_tamper_unknown_fields_and_conflict_rejected(env):
    _, (patient, doctor, *_), _, _ = env
    _, selected = selection(patient)
    doc = export(patient, [selected]).json()
    tampered = copy.deepcopy(doc)
    tampered['records'][0]['content']['body'] = 'tampered'
    assert doctor.post('/api/interchange/import', json=tampered).status_code == 400
    extra = copy.deepcopy(doc)
    extra['records'][0]['execute'] = 'run instructions'
    assert doctor.post('/api/interchange/import', json=extra).status_code == 400
    assert doctor.get('/api/sources').json() == []
    assert doctor.post('/api/interchange/import', json=doc).status_code == 201
    conflict = copy.deepcopy(doc)
    conflict['records'][0]['author'] = 'forged attribution'
    assert doctor.post('/api/interchange/import', json=conflict).status_code == 409
    assert doctor.get('/api/sources').json()[0]['record'] == doc['records'][0]

def test_adna_exact_owned_active_excludes_next_draft(env):
    _, (patient, doctor, *_), _, _ = env
    layer, _ = selection(patient, public=True)
    url = f"/api/interchange/adna/{layer['id']}"
    assert patient.get(url).status_code == 404
    patient.post(f"/api/layers/{layer['id']}/activate", json={'version': 1})
    patient.put(f"/api/layers/{layer['id']}", json={'version': 1, 'body': 'PRIVATE NEXT DRAFT'})
    response = patient.get(url)
    assert response.status_code == 200
    assert 'Selected words' in response.text and 'PRIVATE NEXT DRAFT' not in response.text
    assert 'source_hash:' in response.text and 'source_locator:' in response.text
    assert response.headers['content-disposition'].startswith('attachment;')
    assert doctor.get(url).status_code == 404
    patient.post(f"/api/layers/{layer['id']}/withdraw", json={})
    assert patient.get(url).status_code == 404


def test_remote_audience_keeps_original_peer_and_person_identity(env, tmp_path):
    from superyak_peer.db import Store
    from superyak_peer.federation import Federation
    app, (patient, _, organizer, _), users, _ = env
    remote = Store(tmp_path / 'remote')
    person = remote.create_user('remote-person', 'Remote Person', 'long-remote-password')
    remote_fed = Federation(remote, endpoint='https://localhost:7443')
    card = remote_fed.card(person['id'])
    contact = app.state.federation.pair(users[2]['id'], card)
    _, selected = selection(patient, audience_users=[contact['id']])
    result = export(patient, [selected]).json()['records'][0]
    assert result['audience']['people'] == [f"{remote_fed.identity.peer_id}:{person['id']}"]


def test_active_revision_reference_skips_withdrawal_event(env):
    _, (patient, *_), _, _ = env
    layer, _ = selection(patient)
    patient.post(f"/api/layers/{layer['id']}/activate", json={'version': 1})
    patient.post(f"/api/layers/{layer['id']}/withdraw", json={})
    patient.post(f"/api/layers/{layer['id']}/activate", json={'version': 1})
    record = export(patient, [{'layer_id': layer['id'], 'kind': 'active', 'version': 3}]).json()['records'][0]
    assert record['revision_of'] == record['id'] + '?active=1'
