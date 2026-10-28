"""Federation pull, plan Task 5: the pull route on the listener (spec §4; plan P6, nit 17; review MF2), in process: a
pull peer's request is signed by its own identity and given to the listener's serve_pull."""
import json
import threading
import uuid

import pytest

from superyak_peer.common import Problem
from superyak_peer.identity import canonical, pairing_code
from test_federation_outcomes import Clock, share, station


@pytest.fixture
def pulling(tmp_path):
    """Alice's listener `a`, paired both ways with two pull peers (`mac`, `mac2`) and one push peer (`push`)."""
    clock = Clock()
    a = station(tmp_path / 'a', 'alice', clock)
    peers = {'mac': station(tmp_path / 'mac', 'mo', clock, mode='pull'),
             'mac2': station(tmp_path / 'mac2', 'mia', clock, mode='pull'),
             'push': station(tmp_path / 'push', 'pat', clock)}
    contacts = {}
    for key, (store, user, fed) in peers.items():
        card = fed.card(user)
        contacts[key] = a[2].pair(a[1], card, code=pairing_code(card))['id']
        fed.pair(user, a[2].card(a[1]), code=pairing_code(a[2].card(a[1])))
    return clock, a, peers, contacts


def request(peer, a, clock, **change):
    """A pull request from `peer` to the listener `a`, signed by `peer` after `change` is applied."""
    value = {'version': 1, 'kind': 'pull', 'origin': peer[2].identity.peer_id, 'destination': a[2].identity.peer_id,
             'nonce': uuid.uuid4().hex, 'at': int(clock()), 'limit': 20, 'budget': 1024 * 1024, 'ack': [], 'refused': []}
    value.update(change)
    return peer[2].identity.sign_pull(value)


def pull(peer, a, clock, **change):
    return a[2].serve_pull(canonical(request(peer, a, clock, **change)))


def outbox(a, key=None):
    with a[0].transaction() as db:
        rows = [dict(r) for r in db.execute('SELECT outbox.*, remote_contacts.peer_id FROM outbox JOIN remote_contacts '
                                            'ON contact_id=remote_contacts.id ORDER BY event_seq, outbox.id')]
    return rows if key is None else [r for r in rows if r['peer_id'] == key]


def refused(call, status, message):
    with pytest.raises(Problem) as answer:
        call()
    assert (answer.value.status, answer.value.message) == (status, message)


def test_a_pull_returns_exactly_the_bytes_push_would_send_and_an_ack_delivers(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    share(a, contacts['mac'], 'for the mac')
    got = pull(mac, a, clock)
    [row] = outbox(a, mac[2].identity.peer_id)
    assert got['envelopes'] == [row['envelope']] and got['more'] is False  # nothing beyond the row it examined
    assert mac[2].receive(got['envelopes'][0].encode()) == {'ok': True, 'duplicate': False}
    assert row['status'] == 'pending'
    after = pull(mac, a, clock, ack=[row['id']])
    assert after == {'ok': True, 'envelopes': [], 'more': False}
    assert outbox(a, mac[2].identity.peer_id)[0]['status'] == 'delivered'


def test_a_lost_response_costs_one_duplicate(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    share(a, contacts['mac'])
    first, again = pull(mac, a, clock), pull(mac, a, clock)  # the first response was lost: nothing acked it
    assert first['envelopes'] == again['envelopes']
    assert mac[2].receive(first['envelopes'][0].encode())['duplicate'] is False
    assert mac[2].receive(again['envelopes'][0].encode())['duplicate'] is True


def test_limit_zero_only_acks(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    share(a, contacts['mac'], 'one'), share(a, contacts['mac'], 'two')
    first = pull(mac, a, clock, limit=1)['envelopes']
    [row] = [r for r in outbox(a, mac[2].identity.peer_id) if r['envelope'] in first]
    got = pull(mac, a, clock, limit=0, ack=[row['id']])
    assert got == {'ok': True, 'envelopes': [], 'more': True}
    assert [r['status'] for r in outbox(a, mac[2].identity.peer_id)] == ['delivered', 'pending']


def test_a_refusal_sets_last_error_and_leaves_metadata_alone(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    share(a, contacts['mac'])
    pull(mac, a, clock)
    [before] = outbox(a, mac[2].identity.peer_id)
    pull(mac, a, clock, refused=[{'event_id': before['id'], 'code': 403}])
    [after] = outbox(a, mac[2].identity.peer_id)
    assert (after['status'], after['last_error'], after['metadata']) == ('refused', '403', before['metadata'])


def test_the_wrong_destination_is_refused_before_any_nonce_is_stored(pulling):
    """Spec §4, check 2 (SF9): the defence against one listener replaying a puller's request at another."""
    clock, a, peers, contacts = pulling
    refused(lambda: pull(peers['mac'], a, clock, destination=peers['push'][2].identity.peer_id), 403, 'Not addressed to this peer')
    with a[0].transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM pull_nonces').fetchone()[0] == 0


def test_requests_that_fail_a_check_are_refused(pulling):
    clock, a, peers, contacts = pulling
    mac, push = peers['mac'], peers['push']
    same = request(mac, a, clock)
    a[2].serve_pull(canonical(same))
    refused(lambda: a[2].serve_pull(canonical(same)), 409, 'Replay')
    refused(lambda: pull(mac, a, clock, at=int(clock()) - 301), 403, 'Clocks differ by more than 5 minutes')
    tampered = {**request(mac, a, clock), 'limit': 3}
    refused(lambda: a[2].serve_pull(canonical(tampered)), 403, 'Peer authentication failed')
    refused(lambda: pull(push, a, clock), 403, 'Not a pull peer')
    for change in ({'limit': True}, {'limit': 21}, {'budget': 1024}, {'ack': ['a' * 40]}, {'nonce': 'A' * 32},
                   {'refused': [{'event_id': 'a' * 32, 'code': 500}]}, {'version': 2}):
        value = {**request(mac, a, clock), **change}
        refused(lambda: a[2].serve_pull(canonical(value)), 400, 'Invalid pull request')
    refused(lambda: a[2].serve_pull(canonical({**request(mac, a, clock), 'extra': 1})), 400, 'Invalid pull request')
    envelope = mac[2].identity.envelope(destination=a[2].identity.peer_id, actor=mac[1], resource_id='x', revision=1,
                                        action='layer.release', recipients=[a[1]], payload={})
    refused(lambda: a[2].serve_pull(canonical(envelope)), 400, 'Invalid pull request')
    record = {'kind': 'grant', 'station': mac[2].identity.peer_id, 'id': 'g1'}
    refused(lambda: a[2].serve_pull(canonical(record)), 400, 'Invalid pull request')
    a[2].unpair(a[1], contacts['mac'])
    refused(lambda: pull(mac, a, clock), 403, 'Unknown or unpaired peer')


def test_an_ack_naming_another_peers_row_changes_nothing(pulling):
    clock, a, peers, contacts = pulling
    share(a, contacts['push'])
    a[2].collect()
    [theirs] = outbox(a, peers['push'][2].identity.peer_id)
    pull(peers['mac'], a, clock, ack=[theirs['id']], refused=[{'event_id': theirs['id'], 'code': 400}])
    assert outbox(a, peers['push'][2].identity.peer_id)[0]['status'] == 'pending'


def test_a_pull_returns_only_the_origins_rows(pulling):
    """Review MF2: _prepare builds whatever row it is given, so the walk's own filter is all that keeps one peer's
    envelopes out of another's response. Two pull peers and a push peer: each puller gets only rows addressed to it,
    `more` counts only its own, and neither walk touches the push peer's rows."""
    clock, a, peers, contacts = pulling
    for key in ('mac', 'mac2', 'push'):
        for n in range(3):
            share(a, contacts[key], f'{key} {n}')
    for key in ('mac', 'mac2'):
        peer_id = peers[key][2].identity.peer_id
        got = pull(peers[key], a, clock, limit=2)
        assert len(got['envelopes']) == 2 and got['more'] is True  # its third row is left: its own count
        assert all(json.loads(e)['destination'] == peer_id for e in got['envelopes'])
    push_rows = outbox(a, peers['push'][2].identity.peer_id)
    assert [(r['status'], r['attempts'], r['envelope']) for r in push_rows] == [('pending', 0, None)] * 3


def test_only_a_verified_request_can_be_busy(pulling):
    """Spec §4, check 7: a forged request during a held pull is refused on its signature, never made busy; a second
    valid one is busy."""
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    share(a, contacts['mac'])
    inside, release = threading.Event(), threading.Event()

    def hold(key):
        inside.set()
        assert release.wait(10)
    a[2]._between_rows = hold
    worker = threading.Thread(target=lambda: pull(mac, a, clock))
    worker.start()
    try:
        assert inside.wait(10)
        forged = {**request(mac, a, clock), 'budget': 65536}
        refused(lambda: a[2].serve_pull(canonical(forged)), 403, 'Peer authentication failed')
        refused(lambda: pull(mac, a, clock), 409, 'Busy')
    finally:
        release.set()
        worker.join(10)


def test_a_nonce_is_kept_for_as_long_as_a_replay_could_pass_the_clock(pulling):
    """Plan P6: pruned by the request's `at`, not by arrival. A request 299 s ahead of the listener's clock is valid
    until `at` + 300; replayed 598 s later it still passes the clock, so its nonce must still be there."""
    clock, a, peers, contacts = pulling
    early = request(peers['mac'], a, clock, at=int(clock()) + 299)
    a[2].serve_pull(canonical(early))
    clock.at += 598
    refused(lambda: a[2].serve_pull(canonical(early)), 409, 'Replay')
