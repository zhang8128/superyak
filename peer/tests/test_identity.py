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
