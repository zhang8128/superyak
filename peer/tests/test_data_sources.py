"""Private source management, atomic import receipts, and retained provenance."""
import base64
import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient


def source(client, kind='file', name='My reports'):
    result = client.post('/api/data-sources', json={'name': name, 'kind': kind})
    assert result.status_code == 201, result.text
    return result.json()


def upload(client, content=b'private report', name='report.txt', media_type='text/plain'):
    result = client.post('/api/files', json={'name': name, 'media_type': media_type, 'content_base64': base64.b64encode(content).decode()})
    assert result.status_code == 201, result.text
    return result.json()


def selected(client):
    layer = client.post('/api/layers', json={'title': 'Original evidence', 'body': 'Selected exact words'}).json()
    return client.post('/api/interchange/export', json={'selections': [{'layer_id': layer['id'], 'kind': 'draft', 'version': 1}]}).json()


def test_registry_ownership_version_pause_and_no_sharing(env):
    _, (patient, doctor, organizer, _), _, _ = env
    registered = source(patient)
    path = '/api/data-sources/' + registered['id']
    assert registered['enabled'] is True and registered['version'] == 1
    assert registered['item_count'] == 0
    assert patient.get('/api/data-sources').json()['sources'] == [registered]
    for outsider in (doctor, organizer):
        assert outsider.get('/api/data-sources').json()['sources'] == []
        for suffix in ('', '/items', '/imports'):
            assert outsider.get(path + suffix).status_code == 404
        assert outsider.patch(path, json={'version': 1, 'enabled': False}).status_code == 404
        assert outsider.post(path + '/imports', json={'request_id': 'x', 'version': 1, 'file_ids': ['x']}).status_code == 404
    assert patient.patch(path, json={'version': 1, 'enabled': False}, headers={'x-csrf-token': ''}).status_code == 403
    paused = patient.patch(path, json={'version': 1, 'enabled': False, 'name': 'Corrected source name'}).json()
    assert paused['version'] == 2 and paused['enabled'] is False
    assert patient.patch(path, json={'version': 1, 'name': 'stale name'}).status_code == 409
    assert patient.get(path).json()['name'] == 'Corrected source name'
    assert patient.get('/api/layers').json() == []
    assert doctor.get('/api/shared/layers').json() == []


def test_file_import_receipt_retry_pause_and_resume(env):
    _, (patient, doctor, *_), _, _ = env
    registered, file = source(patient), upload(patient)
    path = '/api/data-sources/' + registered['id']
    payload = {'request_id': 'first-upload', 'version': 1, 'file_ids': [file['id']]}
    imported = patient.post(path + '/imports', json=payload)
    assert imported.status_code == 201, imported.text
    receipt = imported.json()
    assert receipt['status'] == 'succeeded' and receipt['added_count'] == 1
    assert patient.post(path + '/imports', json=payload).json() == receipt
    assert patient.get(path + '/imports').json()['imports'] == [receipt]
    assert patient.get(path).json()['item_count'] == 1
    assert patient.get(path + '/items').json()['items'] == [{'kind': 'file', 'file': file}]
    assert doctor.get('/api/files/' + file['id']).status_code == 404

    patient.patch(path, json={'version': 1, 'enabled': False})
    # A replay reads a receipt; it does not import while paused.
    assert patient.post(path + '/imports', json=payload).json() == receipt
    failed = patient.post(path + '/imports', json={**payload, 'request_id': 'second-upload', 'version': 2})
    assert failed.status_code == 409
    history = patient.get(path + '/imports').json()['imports']
    assert len(history) == 2 and history[0]['status'] == 'failed'
    assert history[0]['error'] and 'file_ids' not in history[0]
    assert patient.get('/api/files/' + file['id']).content == b'private report'
    patient.patch(path, json={'version': 2, 'enabled': True})
    retry = patient.post(path + '/imports', json={**payload, 'request_id': 'second-upload', 'version': 3})
    assert retry.status_code == 201 and retry.json()['added_count'] == 0
    other = upload(patient, b'new bytes', name='other.txt')
    assert patient.post(path + '/imports', json={**payload, 'version': 3, 'file_ids': [other['id']]}).status_code == 409
    assert patient.get(path).json()['item_count'] == 1


def test_file_batch_owner_failure_is_atomic_and_receipt_omits_payload(env):
    _, (patient, doctor, *_), _, _ = env
    registered = source(patient)
    owned, foreign = upload(patient), upload(doctor, b'OTHER ACCOUNT SECRET')
    path = '/api/data-sources/' + registered['id']
    result = patient.post(path + '/imports', json={'request_id': 'batch', 'version': 1, 'file_ids': [owned['id'], foreign['id']]})
    assert result.status_code == 404
    assert patient.get(path + '/items').json()['items'] == []
    history = patient.get(path + '/imports')
    assert history.json()['imports'][0]['status'] == 'failed'
    assert foreign['id'] not in history.text and 'OTHER ACCOUNT SECRET' not in history.text


def test_selected_records_conflict_rolls_back_batch_and_keeps_original(env):
    _, (patient, doctor, *_), _, _ = env
    registered = source(doctor, 'selected-records')
    path = '/api/data-sources/' + registered['id']
    document = selected(patient)
    payload = {'request_id': 'one', 'version': 1, 'document': document}
    receipt = doctor.post(path + '/imports', json=payload)
    assert receipt.status_code == 201, receipt.text
    original = doctor.get('/api/sources').json()[0]
    assert original['record'] == document['records'][0]
    assert doctor.get(path + '/items').json()['items'] == [{'kind': 'record', 'source': original}]

    conflict = copy.deepcopy(document)
    conflict['records'][0]['author'] = 'different author'
    new_record = copy.deepcopy(document['records'][0])
    new_record['id'] += '-new'
    conflict['records'].insert(0, new_record)
    failed = doctor.post(path + '/imports', json={**payload, 'request_id': 'two', 'document': conflict})
    assert failed.status_code == 409
    assert doctor.get('/api/sources').json() == [original]
    assert doctor.get(path).json()['item_count'] == 1
    assert doctor.get(path + '/imports').json()['imports'][0]['status'] == 'failed'
    assert doctor.get('/api/layers').json() == []
    assert doctor.post('/api/interchange/export', json={'source_ids': [original['id']]}).json() == document


def test_legacy_import_is_managed_and_pause_is_enforced(env):
    _, (patient, doctor, *_), _, _ = env
    document = selected(patient)
    imported = doctor.post('/api/interchange/import', json=document).json()
    registered = doctor.get('/api/data-sources').json()['sources'][0]
    assert registered['kind'] == 'selected-records' and registered['item_count'] == 1
    path = '/api/data-sources/' + registered['id']
    assert doctor.get(path + '/items').json()['items'][0]['source'] == imported['records'][0]
    doctor.patch(path, json={'version': registered['version'], 'enabled': False})
    assert doctor.post('/api/interchange/import', json=document).status_code == 409
    assert doctor.get('/api/sources').json() == imported['records']


def test_existing_records_backfill_without_rewriting_history_or_creating_receipts(tmp_path):
    from superyak_peer.app import create_app
    from superyak_peer.db import Store
    from superyak_peer.interchange import Interchange
    store = Store(tmp_path / 'old-peer')
    person = store.create_user('legacy', 'Legacy account', 'long-legacy-password')
    interchange = Interchange(store, 'legacy-origin')
    layer = store.create_layer(person['id'], {'title': 'Unchanged', 'body': 'Original private text'})
    document = interchange.export(person['id'], {'selections': [{'layer_id': layer['id'], 'kind': 'draft', 'version': 1}]})
    imported = interchange.import_document(person['id'], document)
    for _ in range(2):
        app = create_app(store.data_dir, allowed_origins=['http://testserver'])
        with TestClient(app, headers={'origin': 'http://testserver'}) as client:
            client.post('/api/login', json={'username': 'legacy', 'password': 'long-legacy-password'})
            registered, = client.get('/api/data-sources').json()['sources']
            assert registered['item_count'] == 1
            assert client.get('/api/data-sources/' + registered['id'] + '/imports').json()['imports'] == []
            assert client.get('/api/sources').json() == imported['records']
    assert store.get_layer(person['id'], layer['id'])['body'] == 'Original private text'


def test_concurrent_identical_imports_return_one_receipt(env):
    app, (patient, *_), _, _ = env
    registered, file = source(patient), upload(patient)
    path = '/api/data-sources/' + registered['id'] + '/imports'
    payload = {'request_id': 'race', 'version': 1, 'file_ids': [file['id']]}
    headers, cookies = dict(patient.headers), dict(patient.cookies)
    def run(_):
        with TestClient(app, headers=headers, cookies=cookies) as client:
            return client.post(path, json=payload)
    with ThreadPoolExecutor(2) as pool:
        first, second = pool.map(run, range(2))
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert len(patient.get(path).json()['imports']) == 1


def test_managed_records_settings_and_receipts_survive_restart_without_default_duplicate(env):
    from superyak_peer.app import create_app
    app, (patient, doctor, *_), _, _ = env
    registered = source(doctor, 'selected-records', 'My studies')
    path = '/api/data-sources/' + registered['id']
    payload = {'request_id': 'study', 'version': 1, 'document': selected(patient)}
    receipt = doctor.post(path + '/imports', json=payload).json()
    paused = doctor.patch(path, json={'version': 1, 'enabled': False}).json()
    original = doctor.get('/api/sources').json()
    restarted = create_app(app.state.store.data_dir, clock=app.state.store.clock, allowed_origins=['http://testserver'])
    with TestClient(restarted, headers=dict(doctor.headers), cookies=dict(doctor.cookies)) as client:
        assert client.get('/api/data-sources').json()['sources'] == [paused]
        assert client.get(path + '/imports').json()['imports'] == [receipt]
        assert client.get('/api/sources').json() == original
        assert client.post(path + '/imports', json={**payload, 'request_id': 'next', 'version': 2}).status_code == 409


def test_invalid_and_stale_imports_do_not_add_items(env):
    _, (patient, *_), _, _ = env
    registered, file = source(patient), upload(patient)
    path = '/api/data-sources/' + registered['id']
    patient.patch(path, json={'version': 1, 'description': 'Corrected context'})
    assert patient.post(path + '/imports', json={'request_id': 'stale', 'version': 1, 'file_ids': [file['id']]}).status_code == 409
    for invalid in ({'version': True, 'file_ids': [file['id']]}, {'version': 2, 'file_ids': []}, {'version': 2, 'file_ids': [None]}, {'version': 2, 'document': {}}):
        assert patient.post(path + '/imports', json={'request_id': 'invalid', **invalid}).status_code == 400
    assert patient.get(path).json()['item_count'] == 0


@pytest.mark.parametrize('media_type,name,content', [
    ('text/csv', 'dataset.csv', b'name,note\r\nAlex,"two, values"\r\n'),
    ('application/json', 'dataset.json', b'{"items": [1, 2], "note": "original spacing"}\n'),
])
def test_dataset_files_preserve_exact_bytes(env, media_type, name, content):
    _, (patient, *_), _, _ = env
    registered, file = source(patient), upload(patient, content, name, media_type)
    result = patient.post('/api/data-sources/' + registered['id'] + '/imports', json={'request_id': 'dataset', 'version': 1, 'file_ids': [file['id']]})
    assert result.status_code == 201
    assert patient.get('/api/files/' + file['id']).content == content


@pytest.mark.parametrize('media_type,content', [('application/json', b'{bad'), ('application/json', b'NaN'), ('text/csv', b'\xff\xfe'), ('text/csv', b'a,b\n"unterminated')])
def test_invalid_dataset_file_is_rejected(env, media_type, content):
    _, (patient, *_), _, _ = env
    response = patient.post('/api/files', json={'name': 'dataset.txt', 'media_type': media_type, 'content_base64': base64.b64encode(content).decode()})
    assert response.status_code == 400
    assert patient.get('/api/files').json() == []


def test_pagination_and_input_boundaries(env):
    app, (patient, *_), _, _ = env
    ids = {source(patient, name=f'Source {i}')['id'] for i in range(3)}
    first = patient.get('/api/data-sources?limit=2&offset=0').json()['sources']
    last = patient.get('/api/data-sources?limit=2&offset=2').json()['sources']
    assert len(first) == 2 and len(last) == 1 and {r['id'] for r in first + last} == ids
    for query in ('limit=0', 'limit=101', 'offset=-1', 'limit=abc'):
        assert patient.get('/api/data-sources?' + query).status_code == 400
    for data in ({'name': 'x', 'kind': 'url'}, {'name': 'x', 'kind': 'file', 'endpoint': 'http://localhost'}, {'name': 'x', 'kind': 'file', 'owner_id': 'other'}):
        assert patient.post('/api/data-sources', json=data).status_code == 400
    with TestClient(app, headers={'origin': 'http://testserver'}) as anonymous:
        assert anonymous.get('/api/data-sources').status_code == 401
        assert anonymous.post('/api/data-sources', json={'name': 'x', 'kind': 'file'}).status_code == 401
