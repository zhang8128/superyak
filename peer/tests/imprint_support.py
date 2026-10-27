"""Fixtures for the station side of store-copy imprints (spec I 7, 8, 12): a station on a temporary data directory with
its people and ships, and rows and receipts written without the routes."""
from dataclasses import dataclass
import copy
import hashlib
import json
import uuid

from fastapi.testclient import TestClient

from superyak_peer.app import create_app
from superyak_peer.identity import canonical
from superyak_peer.imprints import STATUSES
from test_presence import docked, ship_client

NOW = 1792951950


@dataclass
class Station:
    app: object
    store: object
    clock: list
    root: object
    andy: TestClient
    sam: TestClient
    jenn: TestClient
    voyager: TestClient       # sam's docked ship
    serenity: TestClient      # andy's own docked ship
    other_ship: TestClient    # jenn's docked ship
    ids: dict                 # username or ship name to user id

    @property
    def andy_id(self):
        return self.ids['andy']


def _person(app, name, password):
    client = TestClient(app, base_url='http://testserver')
    client.headers['origin'] = 'http://testserver'
    response = client.post('/api/login', json={'username': name, 'password': password})
    assert response.status_code == 200, response.text
    client.headers['x-csrf-token'] = response.json()['csrf_token']
    return client


_TEST_ROOT = object()


def station(tmp_path, imprints_dir=_TEST_ROOT):
    """A station with andy (super admin), sam and jenn, and a docked ship each: serenity, voyager and rio-grande.
    Nothing is signed and no identity exists until a test signs something. The imprint routes are on, rooted in
    tmp_path / 'imprints'; `imprints_dir=None` turns them off (R8)."""
    clock = [float(NOW)]
    root = tmp_path / 'imprints'
    if imprints_dir is _TEST_ROOT:
        imprints_dir = root
    app = create_app(tmp_path / 'peer', clock=lambda: clock[0], allowed_origins=['http://testserver'],
                     imprints_dir=imprints_dir)
    store, ids, clients, ships = app.state.store, {}, {}, {}
    for name, admin in (('andy', True), ('sam', False), ('jenn', False)):
        ids[name] = store.create_user(name, name.title(), 'long-password-' + name, is_admin=admin)['id']
    with store.transaction() as db:
        db.execute('UPDATE users SET is_super_admin=1 WHERE id=?', (ids['andy'],))
    for name in ids:
        clients[name] = _person(app, name, 'long-password-' + name)
    for owner, ship in (('andy', 'serenity'), ('sam', 'voyager'), ('jenn', 'rio-grande')):
        record, key = docked(store, ids[owner], ship)
        ids[ship] = record['id']
        ships[ship] = ship_client(app, key)
    root.mkdir(mode=0o700)
    return Station(app, store, clock, root, clients['andy'], clients['sam'], clients['jenn'], ships['voyager'],
                   ships['serenity'], ships['rio-grande'], ids)


def sha256_canonical(record):
    return hashlib.sha256(canonical(record)).hexdigest()


def permission_record(st, request_id, *, owner='sam', imprint_id='c0a8f5e2', source_instance_id='3f2a9c1e'):
    """An imprint-permission with exactly its record keys; its id is the request's."""
    ship = 'serenity' if owner == 'andy' else 'voyager'
    inner = {'id': 'r-' + 'ab' * 16, 'layer': f'place:home/{owner}', 'effect': 'allow',
             'selector': {'audience': ['place:home/andy'], 'requesters': ['agent:station-imprints'],
                          'objects': {'kinds': ['memory'], 'stores': [source_instance_id], 'layers': '*', 'lanes': '*',
                                      'collections': [f'collection:{owner}/imprint-{imprint_id}'], 'memories': '*'},
                          'actions': ['imprint', 'read', 'recall'], 'purposes': ['calibration']},
             'valid_from': NOW, 'valid_until': NOW + 86400, 'anchor': NOW, 'backing': 'person',
             'set_by': f'person:{owner}', 'channel': 'browser', 'under_grant': None, 'proposal_id': None,
             'replaces': None, 'reason': f'imprint {imprint_id[:4]} at Deep Space 9', 'created': NOW}
    with st.store.transaction() as db:
        station_id = st.store._station_identity(db).peer_id
    return {'kind': 'imprint-permission', 'station': station_id, 'id': request_id, 'owner': f'person:{owner}',
            'owner_id': st.ids[owner], 'ship_id': st.ids[ship], 'imprint_id': imprint_id,
            'source_instance_id': source_instance_id, 'request_sha256': '0' * 64, 'plan_digest': '9d3e',
            'attestation': 'no-unconsented-others-v1', 'created': NOW, 'records': [inner]}


def seed_imprint(st, *, status, route=False, owner='sam', **over):
    """A request row and its signed permission, for tests that skip the routes. `over` replaces row columns; the
    permission's id is the row's id."""
    if route:
        raise NotImplementedError('the routes arrive with Task 24')
    assert status in STATUSES, status
    ship = 'serenity' if owner == 'andy' else 'voyager'
    request_id = over.pop('id', 'a' * 32)
    imprint_id = over.pop('imprint_id', 'c0a8f5e2')
    source = over.pop('source_instance_id', '3f2a9c1e')
    permission = permission_record(st, request_id, owner=owner, imprint_id=imprint_id, source_instance_id=source)
    with st.store.transaction() as db:
        signature = st.store._station_identity(db).sign_record(permission)
        row = {'id': request_id, 'imprint_id': imprint_id, 'ship_id': st.ids[ship], 'owner_id': st.ids[owner],
               'status': status, 'code_hash': None, 'created': NOW, 'expires': NOW + 600, 'decided_at': None,
               'decided_by': None, 'ended_at': None, 'request_sha256': '0' * 64, 'source_instance_id': source,
               'imprints_root': str(st.root), 'permission': canonical(permission).decode(),
               'permission_signature': signature, 'station_key': None, 'delete_reason': None, **over}
        db.execute(f'INSERT INTO imprint_requests({",".join(row)}) VALUES({",".join("?" * len(row))})', list(row.values()))
    return request_id


def permission_of(st, request_id):
    with st.store.transaction() as db:
        return json.loads(db.execute('SELECT permission FROM imprint_requests WHERE id=?', (request_id,)).fetchone()[0])


def only_signed_imprint_record(st, signed):
    """Leaves the station with one signed record: an imprint permission (`signed='permission'`), or one signed receipt
    over a permission whose signature is cleared (`'receipt'`). Revisions and grants are never signed here."""
    rid = seed_imprint(st, status='received')
    if signed == 'receipt':
        with st.store.transaction() as db:
            st.store._append_imprint_receipt(db, rid, 'approved', st.andy_id, {}, sign=True)
            db.execute('UPDATE imprint_requests SET permission_signature=NULL WHERE id=?', (rid,))
    else:
        assert signed == 'permission', signed
    return rid


REQUEST = {
    'kind': 'engram-imprint-request', 'version': 1, 'imprint_id': 'c0a8f5e2-0000-4000-8000-000000000000',
    'plan_digest': '9d3e' * 16, 'source_instance_id': '3f2a9c1e-0000-4000-8000-000000000000',
    'source_ancestry': [], 'source_ancestry_complete': True,
    'scope': {'lanes': ['work'], 'layers': ['episode', 'semantic'], 'since': '2026-01-01T00:00:00Z',
              'until': '2026-10-25T18:00:00Z', 'shared_with': None, 'unsourced_semantics': False},
    'contents': {'episodes': 1204, 'semantics': 88, 'episode_vectors': 1204, 'semantic_vectors': 88,
                 'semantic_sources': 201, 'resonances': 31, 'semantic_peers': 8, 'memory_log': 1940},
    'others': {'memories': 0, 'people': 0}, 'package': {'bytes': 43188224, 'parts': 11},
    'terms': {'audience': ['place:home/andy'], 'actions': ['imprint', 'route'],
              'purposes': ['calibration', 'trail-evaluation'], 'days': 90}}


def request_doc(**changes):
    """I 7.1's example request, with a fresh imprint id (a uuid4) and, unless given, a fresh source store id. A key
    with a dot sets a nested value (`"scope.until"`); None sets null."""
    doc = copy.deepcopy(REQUEST)
    doc['imprint_id'] = str(uuid.uuid4())
    doc['source_instance_id'] = str(uuid.uuid4())
    for key, value in changes.items():
        if key == 'owner_ship':
            continue
        target = doc
        *path, last = key.split('.')
        for part in path:
            target = target[part]
        target[last] = value
    return doc


def post(st, doc, ship='voyager'):
    """POST a request document, canonically encoded, from a docked ship ('voyager' is Sam's, 'serenity' Andy's)."""
    return getattr(st, ship).post('/api/imprints', content=canonical(doc))
