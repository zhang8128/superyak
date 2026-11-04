"""Ship home and crossing plan, Task 1: the crossing's wire (spec 2.3, plan P4 and P7). A crossing request has exactly
its twelve keys and P4's frame; it, a pull and an answer each verify only as themselves; an answer binds the request by
its digest and nonce, from the peer the asking side dialled, to the asking side."""
import base64
import copy
import uuid

import pytest

from superyak_peer.common import Problem
from superyak_peer.identity import (CROSSING_ANSWER_KEYS, CROSSING_KEYS, PULL_KEYS, RECORD_KEYS, RESERVED_KINDS,
                                    PeerIdentity, canonical, crossing_digest, crossing_shape_ok, verify_crossing,
                                    verify_crossing_answer, verify_pull)

INSTANCE = '2f1c8a64-3b7e-4d2a-9c11-5e8f0a7b6c3d'


@pytest.fixture
def peers(tmp_path):
    """Two identities: `asker` (the origin) and `answerer` (the destination), each with its card."""
    asker = PeerIdentity.load_or_create(tmp_path / 'asker')
    answerer = PeerIdentity.load_or_create(tmp_path / 'answerer')
    cards = {name: ident.card('https://localhost:7437', {'id': name, 'name': name.title()})
             for name, ident in (('asker', asker), ('answerer', answerer))}
    return asker, answerer, cards


def recall_frame(**change):
    frame = {'protocolVersion': '0.1', 'kind': 'recall', 'receiver': 'tardis', 'publisher': 'rio-grande',
             'context': {'id': 'work/lighthouse', 'path': ['work', 'lighthouse']}, 'purpose': 'session-recall',
             'audience': 'self', 'query': 'what did the lighthouse decide', 'k': 20, 'at': '2026-11-03T12:00:00+00:00'}
    frame.update(change)
    return frame


def read_frame(**change):
    frame = {'protocolVersion': '0.1', 'kind': 'read', 'receiver': 'tardis', 'publisher': 'rio-grande',
             'context': {'id': 'work/lighthouse', 'path': ['work', 'lighthouse']}, 'purpose': 'session-recall',
             'turnId': str(uuid.uuid4()), 'memoryIds': ['m1', 'm2']}
    frame.update(change)
    return frame


def unsigned(asker, answerer, frame=None, **change):
    value = {'version': 1, 'kind': 'crossing', 'origin': asker.peer_id, 'destination': answerer.peer_id,
             'receiver_instance': INSTANCE, 'receiver_ship': 'a' * 32, 'publisher_ship': 'b' * 32,
             'frame': frame or recall_frame(), 'deadline_ms': 2000, 'nonce': uuid.uuid4().hex, 'at': 1_000_000}
    value.update(change)
    return value


def signed(asker, answerer, frame=None, **change):
    return asker.sign_crossing(unsigned(asker, answerer, frame, **change))


def answer_for(answerer, request, frame=None, **change):
    kind = 'recall_result' if request['frame']['kind'] == 'recall' else 'read_result'
    value = {'version': 1, 'kind': 'crossing-answer', 'origin': answerer.peer_id, 'destination': request['origin'],
             'request_digest': crossing_digest(request), 'nonce': request['nonce'],
             'frame': frame or {'protocolVersion': '0.1', 'kind': kind, 'items': [], 'disclosureId': 'd' * 32}}
    value.update(change)
    return answerer.sign_crossing_answer(value)


def test_a_recall_and_a_read_have_the_crossing_shape(peers):
    asker, answerer, _ = peers
    assert set(signed(asker, answerer)) == CROSSING_KEYS and len(CROSSING_KEYS) == 12
    assert crossing_shape_ok(signed(asker, answerer))
    assert crossing_shape_ok(signed(asker, answerer, read_frame()))


@pytest.mark.parametrize('key', sorted(CROSSING_KEYS))
def test_each_missing_key_is_refused(peers, key):
    asker, answerer, _ = peers
    request = signed(asker, answerer)
    del request[key]
    assert not crossing_shape_ok(request)


def test_an_extra_key_is_refused(peers):
    asker, answerer, _ = peers
    assert not crossing_shape_ok({**signed(asker, answerer), 'station': 'x'})


@pytest.mark.parametrize('key, value', [
    ('version', True), ('version', 2), ('version', '1'), ('kind', 'pull'), ('kind', 'crossing-answer'),
    ('origin', 'A' * 64), ('destination', 'a' * 63), ('receiver_instance', 'not-a-uuid'),
    ('receiver_instance', INSTANCE.upper()), ('receiver_instance', INSTANCE.replace('-', '')),
    ('receiver_ship', 'has space'), ('receiver_ship', 'x' * 65), ('publisher_ship', ''), ('publisher_ship', 7),
    ('frame', 'recall'), ('deadline_ms', 99), ('deadline_ms', 10_001), ('deadline_ms', 2000.0), ('deadline_ms', True),
    ('nonce', 'A' * 32), ('nonce', 'a' * 31), ('at', 1_000_000.5), ('at', '1000000'), ('at', True),
    ('signature', 'x' * 129), ('signature', 5)])
def test_each_wrong_type_or_range_is_refused(peers, key, value):
    asker, answerer, _ = peers
    assert not crossing_shape_ok({**signed(asker, answerer), key: value})


def test_the_edges_of_each_range_pass(peers):
    asker, answerer, _ = peers
    for change in ({'deadline_ms': 100}, {'deadline_ms': 10_000}):
        assert crossing_shape_ok(signed(asker, answerer, **change))
    assert crossing_shape_ok(signed(asker, answerer, recall_frame(k=1, query='q')))
    assert crossing_shape_ok(signed(asker, answerer, recall_frame(query='q' * 4096)))
    assert crossing_shape_ok(signed(asker, answerer, read_frame(memoryIds=['1', '2', '3', '4', '5'])))


@pytest.mark.parametrize('frame', [
    recall_frame(k=21), recall_frame(k=0), recall_frame(k=True), recall_frame(k=2.0),
    recall_frame(query='q' * 4097), recall_frame(query=''), recall_frame(audience='commons'),
    recall_frame(protocolVersion='0.2'), recall_frame(kind='recall_result'), recall_frame(purpose=''),
    recall_frame(purpose='p' * 257), recall_frame(receiver=''), recall_frame(publisher='p' * 257),
    recall_frame(at=1_000_000), recall_frame(context={'id': 'work', 'path': ['work'], 'x': 1}),
    recall_frame(context={'id': 'w' * 513, 'path': ['w' * 513]}), recall_frame(context={'id': 'work', 'path': ['other']}),
    recall_frame(context={'id': 'work'}), recall_frame(turnId='t'), recall_frame(memoryIds=['m1']),
    read_frame(memoryIds=['1', '2', '3', '4', '5', '6']), read_frame(memoryIds=[]), read_frame(memoryIds=['m', 'm']),
    read_frame(memoryIds=['m' * 129]), read_frame(memoryIds=[1]), read_frame(turnId=''), read_frame(turnId='t' * 65),
    read_frame(query='q'), read_frame(audience='self'), read_frame(kind='read_result'), {'kind': 'recall'}],
    ids=lambda f: ','.join(sorted(f))[:40] if isinstance(f, dict) else str(f))
def test_a_frame_off_p4_is_refused(peers, frame):
    asker, answerer, _ = peers
    assert not crossing_shape_ok(signed(asker, answerer, frame))


def test_a_frame_missing_any_key_is_refused(peers):
    asker, answerer, _ = peers
    for build in (recall_frame, read_frame):
        for key in build():
            frame = build()
            del frame[key]
            assert not crossing_shape_ok(signed(asker, answerer, frame)), key


def test_a_memory_route_envelope_is_refused():
    """Spec section 4, "Two routes": a 3.11 envelope on the crossing route is a 400."""
    envelope = {'session_id': 's', 'outbox_id': 'o', 'seq': 1, 'op_id': 'op', 'client_time': 1, 'deadline_ms': 2000,
                'kind': 'tool', 'tool': 'remember', 'arguments': {'content': 'x'}}
    assert not crossing_shape_ok(envelope)


def test_a_crossing_verifies_as_a_crossing_only(peers):
    asker, answerer, cards = peers
    request = signed(asker, answerer)
    assert verify_crossing(cards['asker'], request) == request
    with pytest.raises(Problem) as refused:
        verify_crossing(cards['answerer'], request)  # another peer's card
    assert (refused.value.status, refused.value.message) == (403, 'Peer authentication failed')
    with pytest.raises(Problem):
        verify_pull(cards['asker'], request)


def test_a_changed_crossing_fails_its_signature(peers):
    asker, answerer, cards = peers
    request = signed(asker, answerer)
    for key, value in (('receiver_instance', '00000000-0000-4000-8000-000000000000'), ('deadline_ms', 3000),
                       ('frame', recall_frame(query='another question'))):
        with pytest.raises(Problem) as refused:
            verify_crossing(cards['asker'], {**request, key: value})
        assert refused.value.status == 403, key


def test_a_pull_does_not_verify_as_a_crossing(peers):
    asker, answerer, cards = peers
    pull = asker.sign_pull({'version': 1, 'kind': 'pull', 'origin': asker.peer_id, 'destination': answerer.peer_id,
                            'nonce': uuid.uuid4().hex, 'at': 1_000_000, 'limit': 20, 'budget': 1024 * 1024,
                            'ack': [], 'refused': []})
    assert set(pull) == PULL_KEYS
    with pytest.raises(Problem) as refused:
        verify_crossing(cards['asker'], pull)
    assert refused.value.status == 403
    assert not crossing_shape_ok(pull)


def test_an_answer_verifies_as_neither_a_crossing_nor_a_pull(peers):
    asker, answerer, cards = peers
    answer = answer_for(answerer, signed(asker, answerer))
    for verify in (verify_crossing, verify_pull):
        with pytest.raises(Problem) as refused:
            verify(cards['answerer'], answer)
        assert refused.value.status == 403


def test_a_peer_signs_only_its_own_crossing(peers):
    asker, answerer, _ = peers
    with pytest.raises(ValueError):
        answerer.sign_crossing(unsigned(asker, answerer))  # its origin is another peer
    with pytest.raises(ValueError):
        asker.sign_crossing({**unsigned(asker, answerer), 'kind': 'pull'})
    with pytest.raises(ValueError):
        answerer.sign_crossing_answer({'version': 1, 'kind': 'crossing-answer', 'origin': asker.peer_id,
                                       'destination': answerer.peer_id, 'request_digest': 'a' * 64,
                                       'nonce': 'b' * 32, 'frame': {}})


def test_reserved_kinds_are_no_record_kind(peers):
    asker, _, _ = peers
    assert RESERVED_KINDS == {'pull', 'crossing', 'crossing-answer'}
    assert not RESERVED_KINDS & set(RECORD_KEYS)
    with pytest.raises(ValueError):
        asker.sign_record({'kind': 'crossing-answer', 'station': asker.peer_id})
    with pytest.raises(ValueError):
        asker.sign_record({k: 'x' for k in CROSSING_ANSWER_KEYS - {'signature'}} | {'station': asker.peer_id,
                                                                                    'kind': 'crossing-answer'})


def test_the_digest_is_the_sha256_of_the_canonical_signed_request(peers):
    import hashlib
    asker, answerer, _ = peers
    request = signed(asker, answerer)
    assert crossing_digest(request) == hashlib.sha256(canonical(request)).hexdigest()


def test_a_good_answer_verifies(peers):
    asker, answerer, cards = peers
    request = signed(asker, answerer)
    answer = answer_for(answerer, request)
    assert set(answer) == CROSSING_ANSWER_KEYS
    got = verify_crossing_answer(cards['answerer'], answer, me=asker.peer_id, digest=crossing_digest(request),
                                 nonce=request['nonce'], kind='recall')
    assert got == answer


def flip(signature):
    raw = bytearray(base64.b64decode(signature))
    raw[0] ^= 1
    return base64.b64encode(bytes(raw)).decode()


@pytest.mark.parametrize('change', ['signature', 'request_digest', 'nonce', 'origin', 'destination', 'extra',
                                    'read_result for a recall', 'no disclosureId', 'null disclosureId', 'error frame',
                                    'kind', 'version'])
def test_a_bad_answer_is_refused(peers, change):
    asker, answerer, cards = peers
    request = signed(asker, answerer)
    answer = answer_for(answerer, request)
    if change == 'signature':
        answer['signature'] = flip(answer['signature'])
    elif change == 'request_digest':
        answer = answer_for(answerer, request, request_digest='0' * 64)
    elif change == 'nonce':
        answer = answer_for(answerer, request, nonce='0' * 32)
    elif change == 'origin':
        answer = {**answer, 'origin': asker.peer_id}  # also no longer the dialled card's signature
    elif change == 'destination':
        answer = answer_for(answerer, request, destination='c' * 64)
    elif change == 'extra':
        answer = {**answer, 'more': 1}
    elif change == 'read_result for a recall':
        answer = answer_for(answerer, request, frame={'protocolVersion': '0.1', 'kind': 'read_result', 'items': [],
                                                       'disclosureId': 'd' * 32})
    elif change == 'no disclosureId':
        answer = answer_for(answerer, request, frame={'protocolVersion': '0.1', 'kind': 'recall_result', 'items': []})
    elif change == 'null disclosureId':
        answer = answer_for(answerer, request, frame={'protocolVersion': '0.1', 'kind': 'recall_result',
                                                       'disclosureId': None})
    elif change == 'error frame':
        answer = answer_for(answerer, request, frame={'protocolVersion': '0.1', 'kind': 'error', 'code': 'X',
                                                       'detail': '', 'disclosureId': 'd' * 32})
    elif change == 'kind':
        answer = {**answer, 'kind': 'crossing'}
    elif change == 'version':
        answer = {**answer, 'version': 2}
    with pytest.raises(ValueError):
        verify_crossing_answer(cards['answerer'], copy.deepcopy(answer), me=asker.peer_id,
                               digest=crossing_digest(request), nonce=request['nonce'], kind='recall')


def test_an_answer_signed_by_another_peer_is_refused(peers):
    asker, answerer, cards = peers
    request = signed(asker, answerer)
    forged = asker.sign_crossing_answer({'version': 1, 'kind': 'crossing-answer', 'origin': asker.peer_id,
                                         'destination': asker.peer_id, 'request_digest': crossing_digest(request),
                                         'nonce': request['nonce'],
                                         'frame': {'protocolVersion': '0.1', 'kind': 'recall_result',
                                                   'disclosureId': 'd' * 32}})
    with pytest.raises(ValueError):
        verify_crossing_answer(cards['answerer'], forged, me=asker.peer_id, digest=crossing_digest(request),
                               nonce=request['nonce'], kind='recall')
