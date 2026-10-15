"""Station signatures over records (spec A step 3, merge 3a: G1-G6 of 2026-10-15-grants-step3-design.md)."""
import base64
import pytest
from superyak_peer.identity import PeerIdentity, RECORD_KEYS, canonical, verify_record
from test_instructions import activate, docked, new_layer, ship_client

ENDPOINT = 'https://station.test'  # a card needs an HTTPS endpoint; any will do for checking signatures


def card_of(identity):
    return identity.card(ENDPOINT, {'id': 'station', 'name': 'Station'})


def revision_record(identity, **changes):
    record = {'kind': 'instructions-revision', 'station': identity.peer_id, 'layer_id': 'l1', 'revision': 2,
              'owner_id': 'u1', 'title': 'House rules', 'body': 'Run the tests.', 'audience_users': ['s1'],
              'policy': None, 'created': 1000.5}
    record.update(changes)
    return record


def raw_sign(identity, record):
    """A signature made with the key directly, past sign_record's own checks, so verify_record's checks are tested."""
    return base64.b64encode(identity.key.sign(canonical(record))).decode()


def test_a_signed_record_verifies_and_one_changed_byte_fails(tmp_path):
    identity = PeerIdentity.load_or_create(tmp_path / 'a')
    card, record = card_of(identity), revision_record(identity)
    signature = identity.sign_record(record)
    assert verify_record(card, record, signature)
    assert not verify_record(card, revision_record(identity, body='Run the tests!'), signature)
    flipped = bytearray(base64.b64decode(signature))
    flipped[0] ^= 1
    assert not verify_record(card, record, base64.b64encode(bytes(flipped)).decode())


def test_a_record_naming_another_station_or_with_other_keys_never_verifies(tmp_path):
    a, b = PeerIdentity.load_or_create(tmp_path / 'a'), PeerIdentity.load_or_create(tmp_path / 'b')
    card = card_of(a)
    assert not verify_record(card_of(b), revision_record(a), a.sign_record(revision_record(a)))  # another station's card
    named_b = revision_record(a, station=b.peer_id)
    assert not verify_record(card, named_b, raw_sign(a, named_b))  # a's key, a's card, but the record names b
    added = {**revision_record(a), 'note': 'x'}
    assert not verify_record(card, added, raw_sign(a, added))
    missing = revision_record(a)
    del missing['policy']
    assert not verify_record(card, missing, raw_sign(a, missing))
    envelope = a.envelope(destination=b.peer_id, actor='u1', resource_id='r1', revision=1, action='room.message',
                          recipients=['u2'], payload={})
    signature = envelope.pop('signature')
    assert not verify_record(card, envelope, signature)  # an envelope without its signature has no record kind


def test_a_bad_card_or_malformed_input_gives_false_and_never_raises(tmp_path):
    identity = PeerIdentity.load_or_create(tmp_path / 'a')
    card, record = card_of(identity), revision_record(identity)
    signature = identity.sign_record(record)
    forged = revision_record(identity, station='0' * 64)  # names the forged id, so only validate_card can refuse it
    assert not verify_record({**card, 'peer_id': '0' * 64}, forged, raw_sign(identity, forged))  # peer id isn't the key's hash
    for args in ((None, record, signature), (card, None, signature), (card, record, None), (card, record, 'not base64!'),
                 (card, {**record, 'kind': ['instructions-revision']}, signature),
                 (card, revision_record(identity, created=float('nan')), signature), ('card', record, signature)):
        assert verify_record(*args) is False


def test_sign_record_refuses_anything_but_this_stations_records(tmp_path):
    a, b = PeerIdentity.load_or_create(tmp_path / 'a'), PeerIdentity.load_or_create(tmp_path / 'b')
    envelope = a.envelope(destination=b.peer_id, actor='u1', resource_id='r1', revision=1, action='room.message',
                          recipients=['u2'], payload={})
    for record in (revision_record(a, station=b.peer_id), {**revision_record(a), 'note': 'x'}, envelope,
                   {**revision_record(a), 'kind': 'grant'}):
        with pytest.raises(ValueError):
            a.sign_record(record)


def test_each_record_kind_signs_and_verifies_with_exactly_its_keys(tmp_path):
    identity = PeerIdentity.load_or_create(tmp_path / 'a')
    card = card_of(identity)
    assert set(RECORD_KEYS) == {'instructions-revision', 'grant', 'grant-revocation'}
    for kind, keys in RECORD_KEYS.items():
        record = {key: None for key in keys} | {'kind': kind, 'station': identity.peer_id}
        assert verify_record(card, record, identity.sign_record(record)), kind
    assert RECORD_KEYS['grant-revocation'] == {'kind', 'station', 'grant', 'revoked', 'revoked_by', 'reason'}
    assert RECORD_KEYS['instructions-revision'] == {'kind', 'station', 'layer_id', 'revision', 'owner_id', 'title',
                                                    'body', 'audience_users', 'policy', 'created'}
    assert RECORD_KEYS['grant'] == {'kind', 'station', 'id', 'issuer_id', 'grantee_id', 'actions', 'targets', 'rooms',
                                    'expires', 'budget', 'depth', 'confirm', 'parent_id', 'charter_layer_id',
                                    'charter_revision', 'follow', 'created'}


def signature_rows(store):
    with store.transaction() as db:
        return {(r['layer_id'], r['revision']): r['signature'] for r in db.execute('SELECT * FROM revision_signatures')}


def stored_record(store, layer_id, revision):
    with store.transaction() as db:
        return store._revision_record(db, layer_id, revision)


def test_activation_and_narrowing_sign_each_instructions_revision(env):
    app, clients, users, clock = env
    store = app.state.store
    first, _ = docked(store, users[0]['id'], 'serenity')
    second, _ = docked(store, users[0]['id'], 'rio-grande')
    layer = new_layer(clients[0], kind='instructions', title='Règles · 規則', body='Run the tests. ✓',
                      audience_users=[first['id'], second['id']])
    assert activate(clients[0], layer).status_code == 200
    edited = clients[0].put(f'/api/layers/{layer["id"]}', json={'version': layer['version'], 'title': 'Changed',
                                                                'body': 'Changed draft'})
    assert edited.status_code == 200, edited.text  # the draft moves on; the revisions keep what was activated
    narrowed = clients[0].post(f'/api/layers/{layer["id"]}/revoke', json={'revision': 1, 'user_ids': [second['id']]})
    assert narrowed.status_code == 200, narrowed.text
    rows, card = signature_rows(store), card_of(store._station_identity())
    assert set(rows) == {(layer['id'], 1), (layer['id'], 2)}
    for revision, audience in ((1, [first['id'], second['id']]), (2, [first['id']])):
        record = stored_record(store, layer['id'], revision)
        assert record['audience_users'] == audience and record['policy'] is None
        assert record['title'] == 'Règles · 規則' and record['body'] == 'Run the tests. ✓'
        assert record['owner_id'] == users[0]['id'] and record['station'] == store._station_identity().peer_id
        assert verify_record(card, record, rows[(layer['id'], revision)])
    read = clients[0].get(f'/api/layers/{layer["id"]}/revisions/2/signed')
    assert read.status_code == 200, read.text
    body = read.json()
    assert body['record']['revision'] == 2 and body['record']['audience_users'] == [first['id']]
    assert verify_record(card, body['record'], body['signature'])


def test_a_note_is_never_signed_and_the_kind_comes_from_the_revision(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    note = new_layer(clients[0], title='Private note', body='mine')
    assert activate(clients[0], note).status_code == 200
    changing = new_layer(clients[0], title='Was a note', body='first')
    assert activate(clients[0], changing).status_code == 200  # revision 1: a note
    saved = clients[0].put(f'/api/layers/{changing["id"]}', json={'version': changing['version'], 'kind': 'instructions',
                                                                  'title': 'Now law', 'body': 'second',
                                                                  'audience_users': [ship['id']]})
    assert saved.status_code == 200, saved.text
    assert activate(clients[0], saved.json()).status_code == 200  # revision 2: instructions
    assert set(signature_rows(store)) == {(changing['id'], 2)}
    assert stored_record(store, changing['id'], 1) is None and stored_record(store, note['id'], 1) is None


def test_startup_signs_each_unsigned_instructions_revision_once(env, monkeypatch):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    law = new_layer(clients[0], kind='instructions', title='Station law', body='Be kind.', audience_users=[ship['id']])
    assert activate(clients[0], law).status_code == 200
    note = new_layer(clients[0], title='Note')
    assert activate(clients[0], note).status_code == 200
    with store.transaction() as db:
        db.execute('DELETE FROM revision_signatures')  # as a station from before this release has them
    from superyak_peer.db import Store
    restarted = Store(store.data_dir)
    rows = signature_rows(restarted)
    assert set(rows) == {(law['id'], 1)}
    assert verify_record(card_of(restarted._station_identity()), stored_record(restarted, law['id'], 1), rows[(law['id'], 1)])
    assert restarted._station_identity().peer_id == app.state.federation.identity.peer_id  # the identity federation uses
    signed, real = [], PeerIdentity.sign_record
    monkeypatch.setattr(PeerIdentity, 'sign_record', lambda self, record: signed.append(record) or real(self, record))
    assert signature_rows(Store(store.data_dir)) == rows and signed == []  # a second start signs nothing


def test_a_station_whose_identity_cannot_be_read_does_not_start(tmp_path):
    from superyak_peer.db import Store
    for index, damaged in enumerate(('not json', '{}')):  # unreadable, and valid JSON without the keys
        directory = tmp_path / f'station{index}'
        directory.mkdir(mode=0o700)
        (directory / 'identity.json').write_text(damaged)
        with pytest.raises(ValueError, match='identity.json'):
            Store(directory)


def test_a_dangling_identity_symlink_does_not_start(tmp_path):
    from superyak_peer.db import Store
    directory = tmp_path / 'station'
    directory.mkdir(mode=0o700)
    (directory / 'identity.json').symlink_to(tmp_path / 'missing.json')
    with pytest.raises(ValueError):
        Store(directory)


def test_a_new_stations_first_card_still_names_its_host(tmp_path, capsys):
    """Plan review M1: opening a store creates no identity, so `card --endpoint` (after `init`) can still put the
    station's host in its certificate, which peers reaching it by hostname check."""
    import json
    from cryptography import x509
    from superyak_peer.__main__ import main
    from superyak_peer.db import Store
    store = Store(tmp_path / 'state')
    assert not (store.data_dir / 'identity.json').exists()
    store.create_user('owner', 'Owner', 'long-password', is_admin=True)
    main(['card', '--data-dir', str(store.data_dir), '--username', 'owner', '--endpoint', 'https://peer.example:7435'])
    certificate = x509.load_pem_x509_certificate(json.loads(capsys.readouterr().out)['certificate'].encode())
    names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    assert 'peer.example' in names


def test_the_first_signature_creates_a_missing_identity(tmp_path):
    from superyak_peer.db import Store
    store = Store(tmp_path / 'state')
    owner = store.create_user('owner', 'Owner', 'long-password')
    ship, _ = docked(store, owner['id'], 'serenity')
    layer = store.create_layer(owner['id'], {'kind': 'instructions', 'title': 'Law', 'body': 'Be kind.',
                                             'audience_users': [ship['id']]})
    assert not (store.data_dir / 'identity.json').exists()
    store.activate_layer(owner['id'], layer['id'], layer['version'])
    assert (store.data_dir / 'identity.json').exists()
    card = card_of(PeerIdentity.load_or_create(store.data_dir))
    assert verify_record(card, stored_record(store, layer['id'], 1), signature_rows(store)[(layer['id'], 1)])


def test_a_failed_signature_leaves_no_revision_behind(tmp_path, monkeypatch):
    from superyak_peer.db import Store
    store = Store(tmp_path / 'state')
    owner = store.create_user('owner', 'Owner', 'long-password')
    ship, _ = docked(store, owner['id'], 'serenity')
    layer = store.create_layer(owner['id'], {'kind': 'instructions', 'title': 'Law', 'body': 'Be kind.',
                                             'audience_users': [ship['id']]})
    assert not (store.data_dir / 'identity.json').exists()

    def failing(cls, data_dir, **kwargs):
        raise OSError('disk full')

    monkeypatch.setattr(PeerIdentity, 'load_or_create', classmethod(failing))
    with pytest.raises(OSError):
        store.activate_layer(owner['id'], layer['id'], layer['version'])
    with store.transaction() as db:
        assert db.execute('SELECT 1 FROM layer_revisions WHERE layer_id=?', (layer['id'],)).fetchone() is None
        assert db.execute('SELECT active_revision FROM layers WHERE id=?', (layer['id'],)).fetchone()[0] is None
    assert signature_rows(store) == {}
    assert not (store.data_dir / 'identity.json').exists()


def test_a_failed_sign_record_leaves_no_revision_behind(tmp_path, monkeypatch):
    from superyak_peer.db import Store
    store = Store(tmp_path / 'state')
    owner = store.create_user('owner', 'Owner', 'long-password')
    ship, _ = docked(store, owner['id'], 'serenity')
    layer = store.create_layer(owner['id'], {'kind': 'instructions', 'title': 'Law', 'body': 'Be kind.',
                                             'audience_users': [ship['id']]})
    PeerIdentity.load_or_create(store.data_dir)

    def failing(self, record):
        raise ValueError('signing failed')

    monkeypatch.setattr(PeerIdentity, 'sign_record', failing)
    with pytest.raises(ValueError):
        store.activate_layer(owner['id'], layer['id'], layer['version'])
    with store.transaction() as db:
        assert db.execute('SELECT 1 FROM layer_revisions WHERE layer_id=?', (layer['id'],)).fetchone() is None
        assert db.execute('SELECT active_revision FROM layers WHERE id=?', (layer['id'],)).fetchone()[0] is None
    assert signature_rows(store) == {}


def test_only_the_layers_owner_reads_a_signed_revision(env):
    app, clients, users, clock = env
    store = app.state.store
    mine, key = docked(store, users[0]['id'], 'serenity')
    theirs, _ = docked(store, users[1]['id'], 'jenn-ship')
    layer = new_layer(clients[0], kind='instructions', title='Law', body='Be kind.', audience_users=[mine['id'], theirs['id']])
    assert activate(clients[0], layer).status_code == 200
    path = f'/api/layers/{layer["id"]}/revisions/1/signed'
    answer = clients[0].get(path)
    assert answer.status_code == 200, answer.text
    signed = answer.json()
    assert set(signed) == {'station', 'record', 'signature'} and signed['station'] == store._station_identity().peer_id
    assert verify_record(card_of(store._station_identity()), signed['record'], signed['signature'])
    assert clients[1].get(path).status_code == 404  # owns a ship in the audience, but the layer binds only its owner's
    assert clients[2].get(path).status_code == 404  # an admin with no tie to it
    assert clients[0].get('/api/layers/no-such-layer/revisions/1/signed').status_code == 404
    for missing in (7, 0, 2 ** 63):  # none of them is a revision, and 2**63 is past SQLite's integers
        assert clients[0].get(f'/api/layers/{layer["id"]}/revisions/{missing}/signed').status_code == 404
    assert ship_client(app, key).get(path).status_code == 403


def test_a_notes_revision_has_no_signed_record_and_a_withdrawn_layers_still_does(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    note = new_layer(clients[0], title='Note')
    assert activate(clients[0], note).status_code == 200
    assert clients[0].get(f'/api/layers/{note["id"]}/revisions/1/signed').status_code == 404
    law = new_layer(clients[0], kind='instructions', title='Law', body='Be kind.', audience_users=[ship['id']])
    assert activate(clients[0], law).status_code == 200
    assert clients[0].post(f'/api/layers/{law["id"]}/withdraw').status_code == 200
    kept = clients[0].get(f'/api/layers/{law["id"]}/revisions/1/signed')
    assert kept.status_code == 200 and verify_record(card_of(store._station_identity()), kept.json()['record'], kept.json()['signature'])


def signed_station(tmp_path):
    """A station with one signed revision, a person, a room, a waiting docking and the wormhole ship, so each station
    command below has something to do: (store, owner, ship, room, docking)."""
    from superyak_peer.db import Store
    store = Store(tmp_path / 'station')
    owner = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    ship, _ = docked(store, owner['id'], 'serenity')
    law = store.create_layer(owner['id'], {'kind': 'instructions', 'title': 'Law', 'body': 'Be kind.', 'audience_users': [ship['id']]})
    store.activate_layer(owner['id'], law['id'], law['version'])
    store.create_station_ship('wormhole', 'Wormhole')
    room = store.create_room(owner['id'], 'Ops', [])
    return store, owner, ship, room, store.start_docking('defiant', 'bazzite')


def run_cli(capsys, *argv):
    """The CLI's exit code, stdout and stderr."""
    from superyak_peer.__main__ import main
    try:
        main([str(arg) for arg in argv])
        code = 0
    except SystemExit as stopped:
        code = stopped.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_the_door_and_the_station_commands_work_while_the_identity_is_damaged(tmp_path, capsys):
    """G4a, test 4a: a damaged identity.json stops the lighthouse alone. The door takes access requests, and each
    station command that never signs starts and does its work. A revision left unsigned shows they skip the backfill."""
    from fastapi.testclient import TestClient
    from superyak_peer.app import create_app
    from superyak_peer.db import Store
    from superyak_peer.door import create_door
    store, owner, ship, room, docking = signed_station(tmp_path)
    late = store.create_layer(owner['id'], {'kind': 'instructions', 'title': 'Later', 'body': 'x', 'audience_users': [ship['id']]})
    store.activate_layer(owner['id'], late['id'], late['version'])
    with store.transaction() as db:  # unsigned, as from before merge 3a: a backfill here would need the key
        db.execute('DELETE FROM revision_signatures WHERE layer_id=?', (late['id'],))
    (store.data_dir / 'identity.json').write_text('not json')
    with pytest.raises(ValueError, match='identity.json'):
        Store(store.data_dir)
    with pytest.raises(ValueError, match='identity.json'):
        create_app(store.data_dir, allowed_origins=['http://testserver'])
    door = create_door(store.data_dir)
    assert getattr(door.state.store, '_identity', None) is None
    asked = TestClient(door, base_url='https://door.example:8443').post(
        '/api/access-requests', json={'name': 'Eve', 'contact': 'eve@example.org'})
    assert asked.status_code == 201, asked.text
    data = ['--data-dir', store.data_dir]
    (tmp_path / 'rotation').mkdir()
    for argv in (['station-pending', *data], ['station-notices', *data],
                 ['station-notices', *data, '--backup-dir', tmp_path / 'rotation'],  # the branch that lists alerts too
                 ['station-approve', *data, '--id', docking['id'][:8], '--as', 'andy'],
                 ['station-deny', *data, '--id', asked.json()['id'][:8], '--as', 'andy'],
                 ['station-rooms', *data, '--as', 'andy'], ['station-bridge', *data, '--id', room['id'][:8], '--as', 'andy']):
        code, out, err = run_cli(capsys, *argv)
        assert code == 0 and 'could not be read' not in err, (argv[0], err)
    bridged = next(listed for listed in Store(store.data_dir, signing=False).station_rooms('andy') if listed['bridged'])
    code, out, err = run_cli(capsys, 'station-unbridge', *data, '--id', bridged['id'][:8], '--as', 'andy')
    assert code == 0, err
    with Store(store.data_dir, signing=False).transaction() as db:
        assert db.execute('SELECT count(*) FROM revision_signatures WHERE layer_id=?', (late['id'],)).fetchone()[0] == 0


def test_the_door_holds_no_key_even_when_the_identity_is_sound(tmp_path):
    from superyak_peer.door import create_door
    store, owner, ship, room, docking = signed_station(tmp_path)
    assert (store.data_dir / 'identity.json').is_file()
    assert getattr(create_door(store.data_dir).state.store, '_identity', None) is None


def test_a_store_opened_without_signing_still_signs_what_it_writes(tmp_path):
    """G4a: signing=False holds no key at the start, but an activation through it is still signed, and the first
    signature on a station with no signed records creates the identity (G4)."""
    from superyak_peer.db import Store
    quiet = Store(tmp_path / 'station', signing=False)
    owner = quiet.create_user('owner', 'Owner', 'long-password')
    ship, _ = docked(quiet, owner['id'], 'serenity')
    layer = quiet.create_layer(owner['id'], {'kind': 'instructions', 'title': 'Law', 'body': 'Be kind.', 'audience_users': [ship['id']]})
    assert not (quiet.data_dir / 'identity.json').exists()
    quiet.activate_layer(owner['id'], layer['id'], layer['version'])
    card = card_of(PeerIdentity.load_or_create(quiet.data_dir))
    assert verify_record(card, stored_record(quiet, layer['id'], 1), signature_rows(quiet)[(layer['id'], 1)])


def test_own_peer_id_reads_the_stores_one_identity(tmp_path):
    """G4a: remote rooms read this station's peer id through _station_identity(), the one loader."""
    from superyak_peer.db import Store
    store = Store(tmp_path / 'station')
    other = PeerIdentity.load_or_create(tmp_path / 'other')
    store._identity = other  # whatever the store holds is what _own_peer_id answers
    assert store._own_peer_id() == other.peer_id


def test_own_peer_id_inside_a_room_read_does_not_stall(tmp_path):
    """G4a, test 4c: a remote room's read runs in a transaction and asks for this station's peer id; on a station without
    an identity that creates it through the caller's connection, never a second BEGIN IMMEDIATE that waits 30 s."""
    import json
    import time
    from superyak_peer.db import Store
    store = Store(tmp_path / 'station')
    andy = store.create_user('andy', 'Andy', 'long-password-andy')
    peer = 'ab' * 32
    with store.transaction() as db:
        db.execute("INSERT INTO peers(peer_id, card, paired) VALUES(?, '{}', 1)", (peer,))
        db.execute("INSERT INTO inbox(origin, resource_id, kind, recipient, revision, actor, payload) "
                   "VALUES(?, 'r1', 'room', ?, 1, 'remote-user', ?)", (peer, andy['id'], json.dumps({'title': 'Theirs'})))
    assert not (store.data_dir / 'identity.json').exists()
    started = time.monotonic()
    assert store.get_room(andy['id'], f'{peer}:r1')['title'] == 'Theirs'
    assert time.monotonic() - started < 10 and (store.data_dir / 'identity.json').is_file()


def test_a_lost_identity_is_not_replaced_silently(tmp_path, capsys, monkeypatch):
    """G4b, test 4b: with a signed revision and identity.json removed, every signing start refuses, naming the file and
    station-new-identity, and none of them makes a key; a signing=False start still opens."""
    import uvicorn
    from superyak_peer.app import create_app
    from superyak_peer.db import Store
    store, owner, ship, room, docking = signed_station(tmp_path)
    (store.data_dir / 'identity.json').unlink()
    for start in (lambda: Store(store.data_dir), lambda: create_app(store.data_dir, allowed_origins=['http://testserver'])):
        with pytest.raises(ValueError, match='identity.json.*station-new-identity'):
            start()
    served = []
    monkeypatch.setattr(uvicorn, 'run', lambda *args, **kwargs: served.append(args))  # a start that got this far would serve
    for argv in (['card', '--data-dir', store.data_dir, '--username', 'andy', '--endpoint', 'https://peer.example:7435'],
                 ['serve', '--data-dir', store.data_dir, '--peer-tls']):
        code, out, err = run_cli(capsys, *argv)
        assert code == 1 and 'identity.json' in err and 'station-new-identity' in err, (argv[0], err)
    assert served == [] and not (store.data_dir / 'identity.json').exists()  # no new key from any of them
    Store(store.data_dir, signing=False)


def test_a_station_with_no_signed_records_still_creates_its_identity_at_the_first_signature(tmp_path):
    """G4b keeps G4: a note's revision is not a signed record, so a station holding one and no identity starts, and
    creates none until it signs."""
    from superyak_peer.db import Store
    store = Store(tmp_path / 'station')
    owner = store.create_user('owner', 'Owner', 'long-password')
    note = store.create_layer(owner['id'], {'title': 'Note', 'body': 'mine'})
    store.activate_layer(owner['id'], note['id'], note['version'])
    Store(store.data_dir)
    assert not (store.data_dir / 'identity.json').exists()


def test_a_store_without_signing_refuses_to_sign_over_a_lost_identity(tmp_path):
    """G4b's lazy path, test 4a: a signing=False store opens, but an activation through it fails, writing nothing, when
    the station holds signed records and identity.json is missing."""
    from superyak_peer.db import Store
    store, owner, ship, room, docking = signed_station(tmp_path)
    (store.data_dir / 'identity.json').unlink()
    quiet = Store(store.data_dir, signing=False)
    layer = quiet.create_layer(owner['id'], {'kind': 'instructions', 'title': 'More', 'body': 'x', 'audience_users': [ship['id']]})
    with pytest.raises(ValueError, match='identity.json'):
        quiet.activate_layer(owner['id'], layer['id'], layer['version'])
    with quiet.transaction() as db:
        assert db.execute('SELECT active_revision FROM layers WHERE id=?', (layer['id'],)).fetchone()[0] is None
        assert db.execute('SELECT count(*) FROM revision_signatures').fetchone()[0] == 1
    assert not (store.data_dir / 'identity.json').exists()


def test_the_peer_tls_check_reads_an_old_or_missing_database_without_changing_it(tmp_path):
    """G4b, test 4c: `serve --peer-tls` checks before any Store opens, read-only. A database from before merge 3a (no
    revision_signatures table) and a missing one hold no signed records; neither is created or changed. One that can't
    be read gives a message naming it, not a traceback (plan review N1)."""
    import sqlite3
    from contextlib import closing
    from superyak_peer.signatures import refuse_a_lost_identity_before_the_store
    old = tmp_path / 'old'
    old.mkdir(mode=0o700)
    with closing(sqlite3.connect(old / 'peer.sqlite3')) as db:
        db.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
        db.commit()
    before = (old / 'peer.sqlite3').read_bytes()
    refuse_a_lost_identity_before_the_store(old)
    assert (old / 'peer.sqlite3').read_bytes() == before and sorted(p.name for p in old.iterdir()) == ['peer.sqlite3']
    missing = tmp_path / 'missing'
    refuse_a_lost_identity_before_the_store(missing)
    assert not missing.exists()
    junk = tmp_path / 'junk'  # unreadable, with no identity.json: it can't rule out signed records, so it refuses
    junk.mkdir(mode=0o700)
    (junk / 'peer.sqlite3').write_bytes(b'not a database, ' * 64)
    with pytest.raises(ValueError, match='peer.sqlite3'):
        refuse_a_lost_identity_before_the_store(junk)


def test_the_restore_test_passes_on_a_copy_holding_signed_records(tmp_path, monkeypatch, capsys):
    """G4b, test 4c: the copy holds a signed revision and has no identity file, so served as it is it would refuse to
    start (exit 22). The restore test gives its scratch directory a throwaway identity, removed with it."""
    from superyak_peer import backups
    from test_restore import restore_test as run_restore_test, runtime_dir
    run = runtime_dir(tmp_path, monkeypatch)
    store, owner, ship, room, docking = signed_station(tmp_path)
    store.send_message(owner['id'], room['id'], 'm1', 'hello')
    rotation = tmp_path / 'backups' / 'station'
    backups.run_backup(store.data_dir, rotation)
    assert run_restore_test('--backup-dir', rotation) == 0, capsys.readouterr().err
    assert capsys.readouterr().out.rstrip().endswith('; users 3, rooms 1, messages 1.')
    assert list(run.iterdir()) == []  # the scratch directory, and the throwaway identity in it, are gone


def test_station_new_identity_is_the_one_deliberate_way_to_a_new_key(tmp_path, capsys, monkeypatch):
    """G4c, test 4c: refused while identity.json exists, and without --data-dir; with it lost (its TLS files left behind),
    it moves those aside, creates an identity whose certificate names the endpoint's host, says what changes, leaves the
    database byte for byte the same, and the station starts."""
    from cryptography import x509
    from superyak_peer.db import Store
    store, owner, ship, room, docking = signed_station(tmp_path)
    data, identity = store.data_dir, store.data_dir / 'identity.json'
    kept = identity.read_bytes()
    code, out, err = run_cli(capsys, 'station-new-identity', '--data-dir', data)
    assert code == 1 and 'exists' in err and identity.read_bytes() == kept
    monkeypatch.chdir(tmp_path)  # without --data-dir it refuses; a default would mint a key in the wrong directory
    code, out, err = run_cli(capsys, 'station-new-identity', '--endpoint', 'https://peer.example:7435')
    assert code == 2 and '--data-dir' in err and not (tmp_path / '.engram').exists()
    old_peer = store._station_identity().peer_id
    identity.unlink()  # lost; peer-cert.pem and peer-key.pem survive, as they usually do
    database = (data / 'peer.sqlite3').read_bytes()
    code, out, err = run_cli(capsys, 'station-new-identity', '--data-dir', data, '--endpoint', 'https://peer.example:7435')
    assert code == 0, err
    moved = sorted(path.name for path in data.glob('peer-*.pem.lost-*'))
    assert [name.split('.lost-')[0] for name in moved] == ['peer-cert.pem', 'peer-key.pem']
    new = PeerIdentity.load_or_create(data)
    assert new.peer_id != old_peer and new.peer_id in out
    for words in ('stops verifying', 'pair again', 'unverified', 'stopped'):
        assert words in out, words
    names = x509.load_pem_x509_certificate(new.certificate.encode()).extensions.get_extension_for_class(
        x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    assert 'peer.example' in names
    assert (data / 'peer.sqlite3').read_bytes() == database
    assert Store(data)._station_identity().peer_id == new.peer_id  # the station starts, on the new key
