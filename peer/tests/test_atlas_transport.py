"""North-star test 5's transport (docs/superpowers/specs/2026-11-22-claim-crossing-transport-design.md, revision 4 with
amendment 1): sourced publications and notices sent ship to ship as atlas.publication and atlas.notice, with every
issuer bound to the delivering peer. The peer imports no Atlas code, so these packages carry only the fields the peer
reads; Atlas's own validation runs on the receiving side, after `atlas-received`."""
import hashlib
import json

import pytest

from conftest import paired
from superyak_peer.common import Problem
from superyak_peer.identity import canonical, verify_envelope

ONE_MIB = 1024 * 1024


def uri(fed):
    return f'urn:superyak:peer:{fed.identity.peer_id}'


def rules(destination, *, actions=('read', 'link_overlap', 'retain'), publishers=None, effect='allow'):
    return [{'id': 'r1', 'effect': effect, 'actions': list(actions), 'publishers': publishers or [destination],
             'audiences': ['self'], 'contexts': ['urn:x:context'], 'domains': ['research'], 'purposes': ['research'],
             'profiles': ['urn:superyak:profile:atlas-sourced'],
             'claimMediaTypes': ['application/vnd.superyak.atlas-sourced-claim+json']}]


def package(issuer, destination, *, carried=(), policy_rules=None, attestations=None, pad=0):
    """The fields of a sourced publication the transport reads (spec T2, T3), and nothing Atlas would need."""
    def artifact(kind, **extra):
        value = {'kind': kind, 'issuer': issuer, 'id': f'{issuer}:{kind}', **extra}
        if attestations is not None:
            value['attestations'] = attestations
        return value
    return {'format': 'atlas-sourced-publication', 'version': 1,
            'descriptor': artifact('LighthouseDescriptor'),
            'snapshot': artifact('Snapshot', payload={'pad': 'x' * pad}),
            'policy': artifact('ConnectionPolicy', payload={'rules': policy_rules if policy_rules is not None
                                                             else rules(destination)}),
            'claims': [artifact('Claim')],
            'carried': [{'claim': {'kind': 'Claim', 'issuer': c}, 'snapshot': {'kind': 'Snapshot', 'issuer': s}}
                        for c, s in carried]}


@pytest.fixture
def atlas_peers(lessons_peers):
    """lessons_peers, with amendment 1's one pairing: rio-grande's card typed into Tardis's peer."""
    pi, pi_fed, pi_ids = lessons_peers['peers']['pi']
    tardis, tardis_fed, t_ids = lessons_peers['peers']['tardis']
    contact_rio = paired(tardis_fed, t_ids['andy'], pi_fed.card(pi_ids['rio-grande']))['id']
    t_ids['rio-contact'] = contact_rio
    return lessons_peers


def parts(net):
    (pi, pi_fed, pi_ids), (tardis, tardis_fed, t_ids) = net['peers']['pi'], net['peers']['tardis']
    return pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids


def received(store, ship):
    with store.reading() as db:
        return [dict(r) for r in db.execute('SELECT * FROM atlas_received WHERE recipient=? ORDER BY received_at', (ship,))]


# --- 1. send and receive ---------------------------------------------------------------------------------------------

def test_a_publication_crosses_from_the_pi_to_tardis_with_who_delivered_it(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    sent = package(uri(pi_fed), uri(tardis_fed))
    queued = pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', sent)
    assert queued['state'] == 'pending'
    assert atlas_peers['deliver']('pi', 'tardis')['delivered'] >= 1
    [row] = received(tardis, t_ids['tardis'])
    assert row['origin'] == pi_fed.identity.peer_id and row['actor'] == pi_ids['rio-grande']
    assert row['kind'] == 'publication'
    envelope = json.loads(row['envelope'])
    assert verify_envelope(canonical(envelope), pi_fed.card(pi_ids['rio-grande']), tardis_fed.identity.peer_id)
    assert canonical(envelope['payload']['package']) == canonical(sent)
    assert row['payload_digest'] == hashlib.sha256(canonical({'package': sent})).hexdigest()


def test_and_from_tardis_to_the_pi(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    sent = package(uri(tardis_fed), uri(pi_fed))
    tardis.atlas_send(t_ids['tardis'], t_ids['rio-contact'], 'publication', sent)
    atlas_peers['deliver']('tardis', 'pi')
    [row] = received(pi, pi_ids['rio-grande'])
    assert row['origin'] == tardis_fed.identity.peer_id and row['actor'] == t_ids['tardis']


def test_without_rio_grande_as_a_contact_tardis_refuses_what_it_sends_as_amendment_1_says(lessons_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(lessons_peers)
    pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', package(uri(pi_fed), uri(tardis_fed)))
    lessons_peers['deliver']('pi', 'tardis')
    assert received(tardis, t_ids['tardis']) == []
    with pi.reading() as db:
        row = db.execute("SELECT status, last_error FROM outbox WHERE action='atlas.publication'").fetchone()
    assert (row['status'], row['last_error']) == ('refused', '403 Unknown remote participant')


# --- 2. the receiver's refusals (T3) --------------------------------------------------------------------------------

def envelope_from_pi(net, payload, *, action='atlas.publication', recipient=None, event_id='e' + 'a' * 31):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(net)
    return canonical(pi_fed.identity.envelope(
        destination=tardis_fed.identity.peer_id, actor=pi_ids['rio-grande'], resource_id='r' * 64, revision=1,
        action=action, recipients=[recipient or t_ids['tardis']], payload=payload, event_id=event_id))


def refused_at_tardis(net, payload, words, **kw):
    tardis_fed = net['peers']['tardis'][1]
    with pytest.raises(Problem) as caught:
        tardis_fed.receive(envelope_from_pi(net, payload, **kw))
    assert (caught.value.status, caught.value.message) == (400, words)
    assert received(net['peers']['tardis'][0], net['peers']['tardis'][2]['tardis']) == []


def test_tardis_refuses_a_publication_issued_by_anyone_but_its_sender(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_tardis(atlas_peers, {'package': package(uri(tardis_fed), uri(tardis_fed))},
                      "A publication's artifacts must all be issued by the peer that delivered it")


def test_tardis_refuses_a_carried_entry_from_a_third_issuer(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    third = 'urn:superyak:peer:' + 'c' * 64
    refused_at_tardis(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed), carried=[(third, third)])},
                      'A carried claim must be the receiver\'s own or the sender\'s')


def test_tardis_refuses_a_carried_entry_whose_claim_and_snapshot_issuers_differ(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_tardis(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed),
                                                       carried=[(uri(pi_fed), uri(tardis_fed))])},
                      "A carried claim's issuer isn't its snapshot's issuer")


def test_tardis_takes_a_carried_entry_that_is_its_own_or_the_senders(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    payload = {'package': package(uri(pi_fed), uri(tardis_fed),
                                  carried=[(uri(tardis_fed), uri(tardis_fed)), (uri(pi_fed), uri(pi_fed))])}
    assert tardis_fed.receive(envelope_from_pi(atlas_peers, payload))['ok']
    assert len(received(tardis, t_ids['tardis'])) == 1


def test_tardis_refuses_an_artifact_with_attestations(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_tardis(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed), attestations=[{'by': 'x'}])},
                      'This version takes no attestations')


def test_tardis_refuses_an_atlas_payload_for_a_person(atlas_peers):
    _, pi_fed, _, _, tardis_fed, t_ids = parts(atlas_peers)
    refused_at_tardis(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed))},
                      'Atlas publications go only to a ship', recipient=t_ids['andy'])


def test_tardis_refuses_a_payload_over_one_mib(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_tardis(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed), pad=ONE_MIB)},
                      'An atlas payload is at most 1 MiB')


def test_tardis_refuses_a_payload_with_other_keys(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_tardis(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed)), 'extra': 1},
                      'Invalid atlas payload')


def test_a_notice_must_be_issued_by_its_sender(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    notice = {'kind': 'Claim', 'issuer': uri(tardis_fed), 'id': 'n1'}
    refused_at_tardis(atlas_peers, {'notice': notice}, "A notice must be issued by the peer that delivered it",
                      action='atlas.notice')


def test_the_same_package_to_one_ship_is_kept_once(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    payload = {'package': package(uri(pi_fed), uri(tardis_fed))}
    assert tardis_fed.receive(envelope_from_pi(atlas_peers, payload)) == {'ok': True, 'duplicate': False}
    again = envelope_from_pi(atlas_peers, payload, event_id='e' + 'b' * 31)  # a second send, signed afresh
    assert tardis_fed.receive(again) == {'ok': True, 'duplicate': True}
    assert len(received(tardis, t_ids['tardis'])) == 1


# --- 3. the sender's refusals (T2, T3) ------------------------------------------------------------------------------

def refused_at_pi(net, words, *, ship=None, contact=None, kind='publication', payload=None):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(net)
    with pytest.raises(Problem) as caught:
        pi.atlas_send(ship or pi_ids['rio-grande'], contact or pi_ids['contact'], kind,
                      payload if payload is not None else package(uri(pi_fed), uri(tardis_fed)))
    assert caught.value.message == words
    with pi.reading() as db:
        assert db.execute("SELECT COUNT(*) FROM outbox WHERE action LIKE 'atlas.%'").fetchone()[0] == 0


def test_the_pi_refuses_to_send_a_package_it_did_not_issue(atlas_peers):
    _, _, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_pi(atlas_peers, 'A package you send must be issued by this peer',
                  payload=package(uri(tardis_fed), uri(tardis_fed)))


def test_the_pi_refuses_a_policy_with_no_exact_retain_for_the_destination(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_pi(atlas_peers, "The package's policy must allow the destination to retain it, by its exact name",
                  payload=package(uri(pi_fed), uri(tardis_fed), policy_rules=rules(uri(tardis_fed), actions=['read'])))


@pytest.mark.parametrize('change', [{'actions': ['*']}, {'actions': ['re*']}, {'publishers': ['urn:superyak:peer:*']},
                                    {'contexts': ['*']}])
def test_the_pi_refuses_a_policy_with_a_wildcard_anywhere(atlas_peers, change):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    policy = rules(uri(tardis_fed)) + [{**rules(uri(tardis_fed))[0], 'id': 'r2', **change}]
    refused_at_pi(atlas_peers, "The package's policy may hold no wildcard",
                  payload=package(uri(pi_fed), uri(tardis_fed), policy_rules=policy))


def test_the_pi_refuses_a_policy_that_allows_reshare(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_pi(atlas_peers, "The package's policy may not allow reshare",
                  payload=package(uri(pi_fed), uri(tardis_fed),
                                  policy_rules=rules(uri(tardis_fed), actions=['read', 'retain', 'reshare'])))


def test_the_pi_refuses_a_carried_entry_from_a_third_issuer(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    third = 'urn:superyak:peer:' + 'c' * 64
    refused_at_pi(atlas_peers, "A carried claim must be this peer's own or the destination's",
                  payload=package(uri(pi_fed), uri(tardis_fed), carried=[(third, third)]))


def test_the_pi_refuses_a_contact_on_a_peer_the_lessons_chain_does_not_list(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    with pi.transaction() as db:
        db.execute('DELETE FROM lessons_peers')
    refused_at_pi(atlas_peers, "That peer isn't listed for your lessons room: Atlas publications go only to peers "
                               "listed there")


def test_tardis_may_send_to_the_origin_of_its_recorded_lessons_room(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    with tardis.reading() as db:
        assert db.execute('SELECT COUNT(*) FROM lessons_peers').fetchone()[0] == 0  # as on the real tardis-peer
    assert tardis.atlas_send(t_ids['tardis'], t_ids['rio-contact'], 'publication',
                             package(uri(tardis_fed), uri(pi_fed)))['state'] == 'pending'


def test_the_pi_refuses_a_contact_without_a_current_typed_code(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    with pi.transaction() as db:
        db.execute('DELETE FROM pairing_confirmations WHERE contact_id=?', (pi_ids['contact'],))
    refused_at_pi(atlas_peers, 'That contact has no current typed code: Atlas publications need one')


def test_the_pi_refuses_a_person_sender_and_an_ownerless_ship(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    refused_at_pi(atlas_peers, 'Only a ship sends Atlas publications', ship=pi_ids['andy'])
    with pi.transaction() as db:
        db.execute('UPDATE users SET owner_id=NULL WHERE id=?', (pi_ids['rio-grande'],))
    refused_at_pi(atlas_peers, 'A ship with no owner who is an admin here sends no Atlas publications')


def test_the_pi_refuses_a_second_send_of_one_digest_to_one_contact(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    sent = package(uri(pi_fed), uri(tardis_fed))
    pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', sent)
    with pytest.raises(Problem) as caught:
        pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', sent)
    assert caught.value.message == 'Already sent to that contact'


def test_the_pi_refuses_a_payload_over_one_mib_before_queueing(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_pi(atlas_peers, 'An atlas payload is at most 1 MiB',
                  payload=package(uri(pi_fed), uri(tardis_fed), pad=ONE_MIB))


# --- 4. no stall, no hidden outage, no held gate (T1: R1, N1, N2, N5, A3) -------------------------------------------

def rows(store, *actions):
    with store.reading() as db:
        return [dict(r) for r in db.execute('SELECT * FROM outbox WHERE action IN (%s) ORDER BY event_seq'
                                            % ','.join('?' * len(actions)), actions)]


def recording(net, src, dst, *, fail_atlas=None):
    """A sync from src to dst in process that records each action it sends, and can make an atlas send fail."""
    order = []
    def send(card, prepare):
        raw = prepare()
        action = json.loads(raw)['action']
        order.append(action)
        if fail_atlas and action.startswith('atlas.'):
            raise fail_atlas
        return net['peers'][dst][1].receive(raw)
    return order, lambda: net['peers'][src][1].sync_once(send=send)


def test_an_atlas_row_goes_after_the_rooms_in_a_pass(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', package(uri(pi_fed), uri(tardis_fed)))
    pi.create_room(pi_ids['andy'], 'Later room', [pi_ids['contact']])  # queued after the atlas row
    order, run = recording(atlas_peers, 'pi', 'tardis')
    run()
    assert order.index('room.roster') < order.index('atlas.publication')


def test_one_atlas_row_per_peer_in_each_pass(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    for title in ('one', 'two'):
        body = package(uri(pi_fed), uri(tardis_fed))
        body['snapshot']['payload']['title'] = title
        pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', body)
    order, run = recording(atlas_peers, 'pi', 'tardis')
    run()
    assert order.count('atlas.publication') == 1
    run()
    assert order.count('atlas.publication') == 2
    assert len(received(tardis, t_ids['tardis'])) == 2


def test_a_write_past_its_deadline_is_the_rows_alone_and_waits_its_own_backoff(atlas_peers):
    from superyak_peer.transport import RowTimeout
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', package(uri(pi_fed), uri(tardis_fed)))
    order, run = recording(atlas_peers, 'pi', 'tardis', fail_atlas=RowTimeout(BrokenPipeError()))
    run()
    [row] = rows(pi, 'atlas.publication')
    assert row['status'] == 'failed' and row['next_attempt'] >= atlas_peers['clock'][0] + 60
    with pi.reading() as db:
        peer = db.execute('SELECT failing_since, next_attempt FROM peer_delivery WHERE peer_id=?',
                          (tardis_fed.identity.peer_id,)).fetchone()
    assert peer['failing_since'] is None and peer['next_attempt'] is None  # the peer isn't failing
    pi.create_room(pi_ids['andy'], 'After the timeout', [pi_ids['contact']])
    run()
    assert order.count('atlas.publication') == 1  # not due again yet
    assert order[-1] == 'room.roster' and rows(pi, 'room.roster')[-1]['status'] == 'delivered'
    atlas_peers['clock'][0] += 61
    order2, run2 = recording(atlas_peers, 'pi', 'tardis')
    run2()
    assert order2 == ['atlas.publication'] and rows(pi, 'atlas.publication')[0]['status'] == 'delivered'


def test_a_failure_before_the_write_deadline_is_the_peers_as_today(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', package(uri(pi_fed), uri(tardis_fed)))
    order, run = recording(atlas_peers, 'pi', 'tardis', fail_atlas=ConnectionResetError())
    run()
    with pi.reading() as db:
        peer = db.execute('SELECT failing_since FROM peer_delivery WHERE peer_id=?',
                          (tardis_fed.identity.peer_id,)).fetchone()
    assert peer['failing_since'] is not None


def test_check_delivery_now_makes_a_waiting_atlas_row_due(atlas_peers):
    from superyak_peer.transport import RowTimeout
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', package(uri(pi_fed), uri(tardis_fed)))
    _, run = recording(atlas_peers, 'pi', 'tardis', fail_atlas=RowTimeout(TimeoutError()))
    run()
    pi_fed.make_due()
    order, run2 = recording(atlas_peers, 'pi', 'tardis')
    run2()
    assert order == ['atlas.publication']


# --- send_pinned's two phases, over real TLS (N1, N2, N5) -----------------------------------------------------------

def tls_server(tmp_path, handler_body):
    """A TLS listener serving this test's own identity certificate, whose POST handler is `handler_body(handler)`."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import ssl
    import threading
    from superyak_peer.identity import PeerIdentity
    identity = PeerIdentity.load_or_create(tmp_path / 'listener')

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            handler_body(self)

        def log_message(self, *args):
            pass
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(identity.cert_path, identity.key_path)
    srv.socket = context.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    card = identity.card(f'https://127.0.0.1:{srv.server_address[1]}', {'id': 'u1', 'name': 'listener'})
    return srv, card


def ack(handler):
    body = b'{"ok":true,"duplicate":false}'
    handler.send_response(200)
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def test_a_slow_reader_gets_the_scaled_write_deadline(tmp_path):
    import time
    from superyak_peer.transport import send_pinned
    def slow(handler):
        left = int(handler.headers['Content-Length'])
        while left:
            left -= len(handler.rfile.read(min(left, 32 * 1024)))
            time.sleep(0.25)  # about 128 KiB a second
        ack(handler)
    srv, card = tls_server(tmp_path, slow)
    body = b'{"pad":"' + b'x' * (512 * 1024) + b'"}'
    try:
        start = time.monotonic()
        assert send_pinned(card, lambda: body, scaled=True)['ok']
        assert time.monotonic() - start > 3  # past today's 3 s, inside 3 s + 512 KiB / 64 KiB a second
    finally:
        srv.shutdown()


def test_a_stalled_reader_past_the_write_deadline_is_a_row_timeout_whatever_surfaces(tmp_path):
    import time
    from superyak_peer.transport import RowTimeout, send_pinned
    def stalled(handler):
        time.sleep(8)
    srv, card = tls_server(tmp_path, stalled)
    body = b'{"pad":"' + b'x' * (32 * 1024) + b'"}'  # 3 s + 0.5 s at PULL_RATE
    try:
        start = time.monotonic()
        with pytest.raises(RowTimeout):
            send_pinned(card, lambda: body, scaled=True)
        assert 3.4 < time.monotonic() - start < 6
    finally:
        srv.shutdown()


def test_an_unreachable_peer_is_a_peer_failure_even_for_an_atlas_row(tmp_path):
    import socket
    from superyak_peer.identity import PeerIdentity
    from superyak_peer.transport import RowTimeout, send_pinned
    probe = socket.socket()
    probe.bind(('127.0.0.1', 0))
    port = probe.getsockname()[1]
    probe.close()  # nothing listens there now
    card = PeerIdentity.load_or_create(tmp_path / 'gone').card(f'https://127.0.0.1:{port}', {'id': 'u1', 'name': 'x'})
    with pytest.raises(Exception) as caught:
        send_pinned(card, lambda: b'{}', scaled=True)
    assert not isinstance(caught.value, RowTimeout)


def test_the_gate_is_free_while_an_atlas_push_writes(tmp_path):
    import threading
    import time
    from superyak_peer.transport import send_pinned
    reading = threading.Event()
    def slow(handler):
        reading.set()
        left = int(handler.headers['Content-Length'])
        while left:
            left -= len(handler.rfile.read(min(left, 32 * 1024)))
            time.sleep(0.2)
        ack(handler)
    srv, card = tls_server(tmp_path, slow)
    gate = threading.Lock()
    body = b'{"pad":"' + b'x' * (256 * 1024) + b'"}'
    done = []
    sender = threading.Thread(target=lambda: done.append(send_pinned(card, lambda: body, gate=gate, scaled=True)))
    try:
        sender.start()
        assert reading.wait(5)
        assert gate.acquire(timeout=0.5)  # a store transaction would get the gate now
        gate.release()
        sender.join(20)
        assert done and done[0]['ok']
    finally:
        srv.shutdown()


def test_a_room_push_keeps_the_gate_through_its_write_as_today(tmp_path):
    import threading
    from superyak_peer.transport import send_pinned
    reading, release = threading.Event(), threading.Event()
    def held(handler):
        reading.set()
        release.wait(5)
        handler.rfile.read(int(handler.headers['Content-Length']))
        ack(handler)
    srv, card = tls_server(tmp_path, held)
    gate = threading.Lock()
    body = b'{"pad":"' + b'x' * (4 * 1024 * 1024) + b'"}'  # bigger than the socket buffers, so the write blocks
    sender = threading.Thread(target=lambda: send_pinned(card, lambda: body, gate=gate, timeout=10))
    try:
        sender.start()
        assert reading.wait(5)
        assert not gate.acquire(timeout=0.5)
        release.set()
        sender.join(15)
    finally:
        srv.shutdown()


# --- 5. the receiver's faults (N3, third check's advisory 1, A10) and clearing an origin (R7) ------------------------

def test_a_receiver_whose_gate_is_held_answers_503_within_its_bound(atlas_peers):
    import threading
    import time
    _, pi_fed, _, tardis, tardis_fed, t_ids = parts(atlas_peers)
    holding, done = threading.Event(), threading.Event()
    def hold():
        with tardis.transaction():
            holding.set()
            done.wait(10)
    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert holding.wait(5)
        start = time.monotonic()
        with pytest.raises(Problem) as caught:
            tardis_fed.receive(envelope_from_pi(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed))}))
        assert caught.value.status == 503 and time.monotonic() - start < 3.5
    finally:
        done.set()
        holder.join(5)
    assert received(tardis, t_ids['tardis']) == []


def test_a_passing_storage_fault_answers_503_and_a_deterministic_one_400(atlas_peers, monkeypatch):
    import sqlite3
    from superyak_peer import atlas_transport
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    raw = envelope_from_pi(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed))})
    for fault, status in ((sqlite3.OperationalError('database is locked'), 503),
                          (sqlite3.IntegrityError('constraint'), 400)):
        def broken(*args, fault=fault):
            raise fault
        monkeypatch.setattr(atlas_transport, 'apply', broken)
        with pytest.raises(Problem) as caught:
            tardis_fed.receive(raw)
        assert caught.value.status == status


def test_an_origin_past_its_quota_is_refused_in_its_own_words(atlas_peers, monkeypatch):
    from superyak_peer import atlas_transport
    _, pi_fed, _, tardis, tardis_fed, t_ids = parts(atlas_peers)
    first = envelope_from_pi(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed))})
    monkeypatch.setattr(atlas_transport, 'ORIGIN_QUOTA', int(len(first) * 1.5))
    assert tardis_fed.receive(first)['ok']
    second = package(uri(pi_fed), uri(tardis_fed))
    second['snapshot']['payload']['title'] = 'another'
    with pytest.raises(Problem) as caught:
        tardis_fed.receive(envelope_from_pi(atlas_peers, {'package': second}, event_id='e' + 'c' * 31))
    assert (caught.value.status, caught.value.message) == (400, 'This peer holds 64 MiB from that peer already')
    assert tardis_fed.receive(envelope_from_pi(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed))},
                                               event_id='e' + 'd' * 31))['duplicate']  # a duplicate isn't refused


def test_an_old_receiver_refuses_only_the_atlas_row_on_a_push(atlas_peers, monkeypatch):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    original = type(tardis_fed)._apply
    def old_apply(self, db, e):
        if e['action'].startswith('atlas.'):
            raise Problem(400, 'Unknown peer action')
        return original(self, db, e)
    monkeypatch.setattr(type(tardis_fed), '_apply', old_apply)
    pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', package(uri(pi_fed), uri(tardis_fed)))
    pi.create_room(pi_ids['andy'], 'Queued after it', [pi_ids['contact']])
    atlas_peers['deliver']('pi', 'tardis')
    [atlas] = rows(pi, 'atlas.publication')
    assert (atlas['status'], atlas['last_error']) == ('refused', '400 Unknown peer action')
    assert rows(pi, 'room.roster')[-1]['status'] == 'delivered'


def test_unpairing_a_peer_clears_what_it_delivered(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', package(uri(pi_fed), uri(tardis_fed)))
    atlas_peers['deliver']('pi', 'tardis')
    assert len(received(tardis, t_ids['tardis'])) == 1
    tardis_fed.unpair(t_ids['andy'], t_ids['rio-contact'])
    assert received(tardis, t_ids['tardis']) == []


def test_holding_a_contact_clears_what_it_sent(atlas_peers):
    from superyak_peer.owner_trust import hold_contact
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', package(uri(pi_fed), uri(tardis_fed)))
    atlas_peers['deliver']('pi', 'tardis')
    with tardis.transaction() as db:
        contact = db.execute('SELECT * FROM remote_contacts WHERE id=?', (t_ids['rio-contact'],)).fetchone()
        hold_contact(db, contact, 1.0)
    assert received(tardis, t_ids['tardis']) == []
