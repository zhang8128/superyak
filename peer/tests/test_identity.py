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
