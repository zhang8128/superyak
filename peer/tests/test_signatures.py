"""Station signatures over records (spec A step 3, merge 3a: G1-G6 of 2026-10-15-grants-step3-design.md)."""
import base64
import pytest
from superyak_peer.identity import PeerIdentity, RECORD_KEYS, canonical, verify_record

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
