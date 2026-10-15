"""Station signatures over records (spec A step 3, merge 3a: G1-G6 of 2026-10-15-grants-step3-design.md)."""
import base64
import pytest
from superyak_peer.identity import PeerIdentity, RECORD_KEYS, canonical, verify_record
from test_instructions import activate, docked, new_layer

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
    (tmp_path / 'station').mkdir(mode=0o700)
    (tmp_path / 'station' / 'identity.json').write_text('not json')
    with pytest.raises(ValueError):
        Store(tmp_path / 'station')


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
