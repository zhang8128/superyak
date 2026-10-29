import copy
import pytest
from superyak_peer.common import Problem


def test_identity_is_persistent_private_and_card_validated(tmp_path):
    from superyak_peer.identity import PeerIdentity, validate_card
    ident = PeerIdentity.load_or_create(tmp_path)
    card = ident.card('https://localhost:7435', {'id': 'alice', 'name': 'Alice'})
    assert PeerIdentity.load_or_create(tmp_path).peer_id == ident.peer_id
    assert validate_card(card) == card
    assert 'private' not in str(card)
    assert (tmp_path / 'identity.json').stat().st_mode & 0o777 == 0o600
    for endpoint in ['http://example.com', 'https://a:b@example.com', 'https://example.com/#x', 'https://example.com/path']:
        bad = {**card, 'endpoint': endpoint}
        with pytest.raises(Problem):
            validate_card(bad)
    bad = copy.deepcopy(card)
    bad['peer_id'] = '0' * 64
    with pytest.raises(Problem):
        validate_card(bad)


def test_signed_envelope_binds_every_field(tmp_path):
    from superyak_peer.identity import PeerIdentity, verify_envelope, canonical
    ident = PeerIdentity.load_or_create(tmp_path)
    card = ident.card('https://localhost:7435', {'id': 'alice', 'name': 'Alice'})
    event = ident.envelope(destination='b' * 64, actor='alice', resource_id='layer1', revision=1,
                           action='layer.release', recipients=['bob'], payload={'body': 'hello'})
    assert verify_envelope(event, card, 'b' * 64)['payload']['body'] == 'hello'
    for key, value in [('destination', 'c' * 64), ('recipients', ['eve']), ('actor', {'peer': ident.peer_id, 'id': 'eve'}), ('payload', {'body': 'bad'})]:
        with pytest.raises(Problem):
            verify_envelope({**event, key: value}, card, 'b' * 64)
    with pytest.raises(Problem):
        canonical({'x': float('nan')})

@pytest.mark.parametrize('raw',[b'{"x":NaN}', b'{"x":1,"x":2}', b'[]', b'{"x":"\\ud800"}'])
def test_strict_json_rejects_ambiguous_inputs(raw):
    from superyak_peer.identity import parse
    with pytest.raises(Problem):
        parse(raw)


def test_protocol_version_is_integer_not_boolean(tmp_path):
    from superyak_peer.identity import PeerIdentity, validate_card
    identity=PeerIdentity.load_or_create(tmp_path)
    card=identity.card('https://localhost:7435',{'id':'alice','name':'Alice'})
    with pytest.raises(Problem):
        validate_card({**card,'version':True})


# fix:pairing-code (federation-pull spec §2): the code a person types covers the whole card

def test_the_pairing_code_is_32_hex_over_the_whole_canonical_card_in_any_key_order(tmp_path):
    import hashlib
    from superyak_peer.identity import PeerIdentity, canonical, pairing_code
    card = PeerIdentity.load_or_create(tmp_path).card('https://localhost:7435', {'id': 'alice', 'name': 'Alice'})
    code = pairing_code(card)
    assert code == hashlib.sha256(canonical(card)).hexdigest()[:32]
    assert len(code) == 32 and code == code.lower() and int(code, 16) >= 0
    assert pairing_code(dict(reversed(list(card.items())))) == code


def test_every_field_of_the_card_changes_the_code(tmp_path):
    """Version has no other valid value; the key and the certificate change with their pairs, from a second
    identity (plan review nit)."""
    from superyak_peer.identity import PeerIdentity, pairing_code
    card = PeerIdentity.load_or_create(tmp_path / 'a').card('https://localhost:7435', {'id': 'alice', 'name': 'Alice'})
    other = PeerIdentity.load_or_create(tmp_path / 'b').card('https://localhost:7435', {'id': 'alice', 'name': 'Alice'})
    changed = [
        {**card, 'participant': {'id': 'alice2', 'name': 'Alice'}},
        {**card, 'participant': {'id': 'alice', 'name': 'Alice B'}},
        {**card, 'endpoint': 'https://localhost:7436'},
        {**card, 'signing_key': other['signing_key'], 'peer_id': other['peer_id']},
        {**card, 'certificate': other['certificate'], 'fingerprint': other['fingerprint']},
    ]
    codes = {pairing_code(card)} | {pairing_code(c) for c in changed}
    assert len(codes) == 1 + len(changed)


def test_an_invalid_card_has_no_code(tmp_path):
    from superyak_peer.identity import PeerIdentity, pairing_code
    card = PeerIdentity.load_or_create(tmp_path).card('https://localhost:7435', {'id': 'alice', 'name': 'Alice'})
    for bad in ({**card, 'peer_id': '0' * 64}, {**card, 'extra': 1}, None, 'card'):
        with pytest.raises(Problem):
            pairing_code(bad)


def test_the_code_is_shown_in_groups_of_four():
    from superyak_peer.identity import show_code
    assert show_code('0123456789abcdef0123456789abcdef') == '0123 4567 89ab cdef 0123 4567 89ab cdef'


@pytest.mark.parametrize('typed, expected', [
    ('0123 4567 89AB CDEF 0123 4567 89ab cdef', '0123456789abcdef0123456789abcdef'),
    ('0123-4567-89ab-cdef-0123-4567-89ab-cdef', '0123456789abcdef0123456789abcdef'),
    (' 0123456789abcdef0123456789abcdef ', '0123456789abcdef0123456789abcdef'),
    ('0123456789abcdef0123456789abcde', None),           # 31
    ('0123456789abcdef0123456789abcdef0', None),         # 33
    ('0123456789abcdef0123456789abcdeg', None),          # not hex
    ('0123456789abcdef0123456789abcde٣', None),     # an Arabic-Indic three: int(x, 16) would take it
    ('', None), (None, None), (123, None), (['0' * 32], None),
])
def test_a_typed_code_is_normalised_or_refused(typed, expected):
    from superyak_peer.identity import typed_code
    assert typed_code(typed) == expected


# Federation pull (spec §2 and §4; plan Task 1): v2 cards mean pull, and a pull request's signature is its own

ALICE = {'id': 'alice', 'name': 'Alice'}


def test_a_v2_card_means_pull_and_its_variants_are_refused(tmp_path):
    from superyak_peer.identity import PeerIdentity, validate_card
    ident = PeerIdentity.load_or_create(tmp_path)
    pull = ident.card(None, ALICE, delivery='pull')
    push = ident.card('https://localhost:7435', ALICE)
    assert (pull['version'], pull['endpoint'], pull['delivery']) == (2, None, 'pull')
    assert set(pull) == set(push) | {'delivery'}
    assert validate_card(pull) == pull
    without_delivery = {k: v for k, v in pull.items() if k != 'delivery'}
    for bad in ({**pull, 'endpoint': 'https://localhost:7435'}, {**pull, 'delivery': 'push'}, {**pull, 'delivery': None},
                {**pull, 'version': 3}, {**pull, 'version': 1}, {**pull, 'version': True}, without_delivery,
                {**push, 'delivery': 'pull'}, {**push, 'delivery': 'push'}, {**push, 'endpoint': None}):
        with pytest.raises(Problem):
            validate_card(bad)
    with pytest.raises(Problem):
        ident.card('https://localhost:7435', ALICE, delivery='pull')
    with pytest.raises(Problem):
        ident.card(None, ALICE)


def test_a_v1_card_is_byte_identical_to_todays(tmp_path):
    import base64
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from superyak_peer.identity import PeerIdentity, canonical, validate_card
    ident = PeerIdentity.load_or_create(tmp_path)
    fingerprint = x509.load_pem_x509_certificate(ident.certificate.encode()).fingerprint(hashes.SHA256()).hex()
    today = {'version': 1, 'peer_id': ident.peer_id, 'signing_key': base64.b64encode(ident.public_key).decode(),
             'certificate': ident.certificate, 'fingerprint': fingerprint, 'endpoint': 'https://localhost:7435',
             'participant': ALICE}
    card = ident.card('https://localhost:7435', ALICE)
    assert canonical(card) == canonical(today)
    assert canonical(validate_card(card)) == canonical(today)


def test_a_v2_cards_code_covers_its_key_and_participant(tmp_path):
    from superyak_peer.identity import PeerIdentity, pairing_code
    pull = PeerIdentity.load_or_create(tmp_path / 'a').card(None, ALICE, delivery='pull')
    other = PeerIdentity.load_or_create(tmp_path / 'b').card(None, ALICE, delivery='pull')
    push = PeerIdentity.load_or_create(tmp_path / 'a').card('https://localhost:7435', ALICE)
    changed = [{**pull, 'signing_key': other['signing_key'], 'peer_id': other['peer_id']},
               {**pull, 'participant': {'id': 'alice2', 'name': 'Alice'}}, push]
    assert len({pairing_code(pull)} | {pairing_code(c) for c in changed}) == 1 + len(changed)


def _pull_request(ident, **change):
    return {'version': 1, 'kind': 'pull', 'origin': ident.peer_id, 'destination': 'b' * 64, 'nonce': '0' * 32,
            'at': 1_800_000_000, 'limit': 20, 'budget': 1024 * 1024, 'ack': [], 'refused': [], **change}


def test_a_pull_requests_signature_is_its_own(tmp_path):
    """A pull request, an envelope and a signed record are signed the same way by the same key, so each verifier
    insists on its own exact keys: none of the three passes as another (spec §4, `pull` reserved as a kind)."""
    from superyak_peer.identity import PeerIdentity, RECORD_KEYS, verify_envelope, verify_pull, verify_record
    ident = PeerIdentity.load_or_create(tmp_path / 'a')
    card = ident.card(None, ALICE, delivery='pull')
    signed = ident.sign_pull(_pull_request(ident))
    assert verify_pull(card, signed) == signed
    for key, value in [('destination', 'c' * 64), ('nonce', '1' * 32), ('at', 1_800_000_001), ('limit', 0),
                       ('budget', 65536), ('ack', ['a' * 32]), ('refused', [{'event_id': 'a' * 32, 'code': 400}])]:
        with pytest.raises(Problem) as refused:
            verify_pull(card, {**signed, key: value})
        assert refused.value.status == 403
    other = PeerIdentity.load_or_create(tmp_path / 'b')
    with pytest.raises(Problem):
        verify_pull(other.card(None, ALICE, delivery='pull'), signed)
    envelope = ident.envelope(destination='b' * 64, actor='alice', resource_id='layer1', revision=1,
                              action='layer.release', recipients=['bob'], payload={'body': 'hello'})
    with pytest.raises(Problem):
        verify_pull(card, envelope)
    with pytest.raises(Problem):
        verify_envelope(signed, card, 'b' * 64)
    assert not verify_record(card, {k: v for k, v in signed.items() if k != 'signature'}, signed['signature'])
    assert 'pull' not in RECORD_KEYS
    for bad in (_pull_request(ident, origin='c' * 64), _pull_request(ident, kind='push'), {**_pull_request(ident), 'x': 1}):
        with pytest.raises(ValueError):
            ident.sign_pull(bad)


def test_parse_takes_an_explicit_limit():
    from superyak_peer.identity import MAX_ENVELOPE, parse
    raw = b'{"x":"' + b'a' * MAX_ENVELOPE + b'"}'
    with pytest.raises(Problem) as refused:
        parse(raw)
    assert refused.value.status == 413
    assert len(parse(raw, limit=MAX_ENVELOPE + 64 * 1024)['x']) == MAX_ENVELOPE
    with pytest.raises(Problem):
        parse(b'{"x":1}', limit=6)
