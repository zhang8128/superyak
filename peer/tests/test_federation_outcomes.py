"""Federation pull, plan Task 4: one outcome table for push and pull, and per-peer backoff (spec §7; plan P4, SF7,
SF13, nits 2, 6, 12, 13). Every case here runs in process: a `send=` hook stands in for the wire, and a Problem it
raises arrives as the PeerAnswer HTTP would give (SF7)."""
import http.client
import json
import sqlite3

import pytest

from superyak_peer.common import Problem
from superyak_peer.identity import pairing_code

PEER_SCOPED_403 = ('Unknown or unpaired peer', 'Peer authentication failed', 'Unrecognized host',
                   'Same-origin request required', 'Federation requires HTTPS')


class Clock:
    def __init__(self, at=1_000_000.0):
        self.at = at

    def __call__(self):
        return self.at


def station(path, name, clock, mode=None):
    from superyak_peer.db import Store
    from superyak_peer.federation import Federation
    store = Store(path, clock=clock)
    user = store.create_user(name, name.title(), 'a-long-password', is_admin=True)['id']
    if mode:
        store.claim_federation_mode(mode)
    return store, user, Federation(store, endpoint=None if mode == 'pull' else f'https://localhost:{7400 + len(name)}')


@pytest.fixture
def world(tmp_path):
    """Alice's station `a` paired with three peers: `live` and `slow` push peers, `mac` a pull peer."""
    clock = Clock()
    a = station(tmp_path / 'a', 'alice', clock)
    peers = {'live': station(tmp_path / 'live', 'lena', clock), 'slow': station(tmp_path / 'slow', 'sam', clock),
             'mac': station(tmp_path / 'mac', 'mo', clock, mode='pull')}
    contacts = {}
    for key, (store, user, fed) in peers.items():
        card = fed.card(user)
        contacts[key] = a[2].pair(a[1], card, code=pairing_code(card))['id']
        fed.pair(user, a[2].card(a[1]), code=pairing_code(a[2].card(a[1])))
    return clock, a, peers, contacts


def share(a, contact, body='hello'):
    store, user, _ = a
    layer = store.create_layer(user, {'body': body, 'audience_users': [contact]})
    store.activate_layer(user, layer['id'], 1)
    return layer['id']


def rows(a):
    with a[0].transaction() as db:
        return [dict(r) for r in db.execute('SELECT outbox.*, remote_contacts.peer_id FROM outbox JOIN remote_contacts '
                                            'ON contact_id=remote_contacts.id ORDER BY event_seq, outbox.id')]


def delivery(a, peer_id):
    with a[0].transaction() as db:
        return dict(db.execute('SELECT * FROM peer_delivery WHERE peer_id=?', (peer_id,)).fetchone())


def peer_of(peers, key):
    return peers[key][2].identity.peer_id


def receiver(peers):
    """A send= hook delivering to whichever peer the card names, through its real receive."""
    by_id = {fed.identity.peer_id: fed for _, _, fed in peers.values()}
    sent = []

    def send(card, prepare):
        body = prepare()
        sent.append(card['peer_id'])
        return by_id[card['peer_id']].receive(body)
    send.sent = sent
    return send


def test_a_pull_peers_queue_and_a_peer_in_backoff_never_fill_the_page_a_live_peer_needs(world):
    """Spec §7 (MF2): mode and due-ness are in the SQL before LIMIT, so 25 rows for a pull peer and 25 for a peer in
    backoff, all ahead of a live peer's row, still leave the live row in a page of 20."""
    clock, a, peers, contacts = world
    for n in range(25):
        share(a, contacts['mac'], f'for the mac {n}')
        share(a, contacts['slow'], f'for the slow one {n}')
    share(a, contacts['live'], 'for the live one')
    with a[0].transaction() as db:
        db.execute('UPDATE peer_delivery SET failures=3, next_attempt=? WHERE peer_id=?', (clock() + 600, peer_of(peers, 'slow')))
    send = receiver(peers)
    result = a[2].sync_once(send=send, limit=20)
    assert send.sent == [peer_of(peers, 'live')] and result['delivered'] == 1


def test_a_local_keyerror_refuses_its_row_without_backing_off_the_peer(world, monkeypatch):
    """Spec §7: a local exception from _prepare is the row's, never the peer's, so the row behind it goes at once."""
    clock, a, peers, contacts = world
    first, _ = share(a, contacts['live'], 'poison'), share(a, contacts['live'], 'fine')
    a[2].collect()
    poison = next(r['id'] for r in rows(a) if r['resource_id'] == first)
    real = a[2]._prepare

    def prepare(key):
        if key == poison:
            raise KeyError('a missing column')
        return real(key)
    monkeypatch.setattr(a[2], '_prepare', prepare)
    result = a[2].sync_once(send=receiver(peers))
    states = {r['resource_id']: (r['status'], r['last_error']) for r in rows(a)}
    assert states[first] == ('refused', 'KeyError') and result['delivered'] == 1 and result['refused'] == 1
    assert delivery(a, peer_of(peers, 'live'))['failures'] == 0


def test_a_local_operationalerror_leaves_the_row_failed_and_the_peer_alone(world, monkeypatch):
    """Check 3 SF2: a locked or busy store (the nightly backup on the Pi) is nobody's fault: failed, neutral."""
    clock, a, peers, contacts = world
    share(a, contacts['live'])

    def prepare(key):
        raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(a[2], '_prepare', prepare)
    a[2].sync_once(send=receiver(peers))
    assert [(r['status'], r['last_error']) for r in rows(a)] == [('failed', None)]
    assert delivery(a, peer_of(peers, 'live'))['failures'] == 0


def answering(peers, first):
    """A send= hook raising `first` for its first row (after preparing it), then delivering the rest for real."""
    deliver = receiver(peers)
    calls = []

    def send(card, prepare):
        calls.append(card['peer_id'])
        if len(calls) == 1:
            prepare()
            raise first
        return deliver(card, prepare)
    send.calls = calls
    return send


@pytest.mark.parametrize('answer, wording', [
    (Problem(403, 'Unknown remote participant'), '403 Unknown remote participant'),
    (Problem(400, 'Invalid event payload'), '400 Invalid event payload'),
    (Problem(409, 'Revision already used'), '409 Revision already used'),
    (Problem(413, 'Envelope too large'), '413 Envelope too large'),
])
def test_a_row_scoped_answer_refuses_the_row_resets_the_peer_and_the_next_row_goes(world, answer, wording):
    """Spec §7 (check 3 MF1): every other 4xx is the peer's answer about this row. The row is refused with the status
    and message, the peer is reset, and the row behind it is delivered in the same pass."""
    clock, a, peers, contacts = world
    first, second = share(a, contacts['live'], 'one'), share(a, contacts['live'], 'two')
    with a[0].transaction() as db:
        db.execute('UPDATE peer_delivery SET failures=2, failing_since=? WHERE peer_id=?', (clock() - 10, peer_of(peers, 'live')))
    send = answering(peers, answer)
    a[2].sync_once(send=send)
    states = {r['resource_id']: (r['status'], r['last_error']) for r in rows(a)}
    assert states == {first: ('refused', wording), second: ('delivered', None)}
    row = delivery(a, peer_of(peers, 'live'))
    assert (row['failures'], row['next_attempt'], row['failing_since']) == (0, None, None)


PEER_SCOPED = ([Problem(status, 'whatever') for status in (500, 502, 503, 401, 404, 408, 421, 425, 429)]
               + [Problem(403, message) for message in PEER_SCOPED_403]
               + [Problem(301, 'Moved'), Problem(200, 'Peer did not acknowledge delivery')])


@pytest.mark.parametrize('answer', PEER_SCOPED, ids=lambda p: f'{p.status} {p.message}')
def test_a_peer_scoped_answer_fails_the_row_and_backs_off_the_peer(world, answer):
    """Spec §7, every listed status and all five 403 names (nit 13), and a 3xx (nit 6): the row is failed, the peer
    backs off, and its other rows wait for the next pass."""
    clock, a, peers, contacts = world
    first, second = share(a, contacts['live'], 'one'), share(a, contacts['live'], 'two')
    send = answering(peers, answer)
    a[2].sync_once(send=send)
    states = {r['resource_id']: r['status'] for r in rows(a)}
    assert states == {first: 'failed', second: 'pending'} and len(send.calls) == 1
    row = delivery(a, peer_of(peers, 'live'))
    assert (row['failures'], row['next_attempt'], row['failing_since']) == (1, clock() + 2, clock())
    assert row['last_problem'] == f'{answer.status} {answer.message}'


@pytest.mark.parametrize('error', [OSError('connection refused'), TimeoutError('Peer deadline exceeded'),
                                   http.client.RemoteDisconnected('closed'), http.client.IncompleteRead(b'')],
                         ids=lambda e: type(e).__name__)
def test_a_network_failure_fails_the_row_and_backs_off_the_peer(world, error):
    clock, a, peers, contacts = world
    share(a, contacts['live'])
    a[2].sync_once(send=answering(peers, error))
    assert [r['status'] for r in rows(a)] == ['failed']
    assert delivery(a, peer_of(peers, 'live'))['failures'] == 1


def test_a_pin_mismatch_is_a_peer_failure_and_connections_says_certificate_differs(world):
    """Spec §7 (check 3 SF1), plan group 4's push half."""
    from superyak_peer.transport import PinMismatch
    clock, a, peers, contacts = world
    share(a, contacts['live'])
    a[2].sync_once(send=answering(peers, PinMismatch('Peer certificate differs from its card')))
    assert [r['status'] for r in rows(a)] == ['failed']
    listed = {c['id']: c for c in a[2].connections(a[1])}[contacts['live']]
    assert (listed['failures'], listed['last_problem']) == (1, 'certificate differs')


def test_a_card_send_pinned_refuses_is_a_peer_failure_with_its_reason(world, monkeypatch):
    """Plan SF7: send_pinned's own refusals are ValueError, the peer's card being the one at fault."""
    clock, a, peers, contacts = world
    share(a, contacts['live'])
    a[2].sync_once(send=answering(peers, ValueError('Peer card is invalid')))
    row = delivery(a, peer_of(peers, 'live'))
    assert (row['failures'], row['last_problem']) == (1, 'Peer card is invalid')


def run_failures(a, peer_id, clock, count, send):
    waits = []
    for _ in range(count):
        a[2].sync_once(send=send)
        row = delivery(a, peer_id)
        waits.append(round(row['next_attempt'] - clock()))
        clock.at = row['next_attempt']
    return waits


def test_the_backoff_schedule_on_a_listener_and_on_a_pull_peer(tmp_path):
    """Plan P4, against hard-coded lists (nit 12): failures counted first, then min(cap, 2**min(failures, 12)); a
    listener caps at an hour, a pull peer at five minutes for every dial it makes."""
    def failing(card, prepare):
        prepare()
        raise OSError('down')
    for mode, expected in ((None, [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 3600, 3600]),
                           ('pull', [2, 4, 8, 16, 32, 64, 128, 256, 300, 300, 300, 300, 300])):
        clock = Clock()
        a = station(tmp_path / f'a-{mode}', 'alice', clock, mode=mode)
        b = station(tmp_path / f'b-{mode}', 'bob', clock)
        contact = a[2].pair(a[1], b[2].card(b[1]), code=pairing_code(b[2].card(b[1])))['id']
        share(a, contact)
        assert run_failures(a, b[2].identity.peer_id, clock, 13, failing) == expected


def test_a_peer_in_backoff_is_not_dialled_until_due_and_retry_makes_it_due(world):
    """The spec's rename of test_exhausted_retry: no row-level give-up, a peer-level wait; the event id is kept."""
    clock, a, peers, contacts = world
    share(a, contacts['live'])
    a[2].collect()
    [row] = rows(a)
    with a[0].transaction() as db:
        db.execute("UPDATE outbox SET status='failed', attempts=12")
        db.execute('UPDATE peer_delivery SET failures=5, next_attempt=? WHERE peer_id=?', (clock() + 60, peer_of(peers, 'live')))
    send = receiver(peers)
    assert a[2].sync_once(send=send)['delivered'] == 0 and send.sent == []
    a[2].retry(a[1], row['id'])
    assert delivery(a, peer_of(peers, 'live'))['next_attempt'] is None
    assert a[2].sync_once(send=send)['delivered'] == 1
    assert rows(a)[0]['id'] == row['id']


def test_retry_takes_a_refused_row_and_clears_its_error(world):
    clock, a, peers, contacts = world
    share(a, contacts['live'])
    a[2].sync_once(send=answering(peers, Problem(403, 'Unknown remote participant')))
    [row] = rows(a)
    assert row['status'] == 'refused'
    a[2].retry(a[1], row['id'])
    assert (rows(a)[0]['status'], rows(a)[0]['last_error']) == ('pending', None)
    assert a[2].sync_once(send=receiver(peers))['delivered'] == 1


def test_a_reply_to_a_room_the_receiver_no_longer_has_is_refused_and_the_next_row_goes(world):
    """Plan SF13: _reply answered require()'s 404 for a missing room, which §7 calls peer-scoped, so one such reply
    stalled push for good. It answers 403 'Room recipient or epoch changed' now: row-scoped."""
    clock, a, peers, contacts = world
    store, user, fed = peers['live']
    room = a[0].create_room(a[1], 'Gone soon', [contacts['live']])
    a[2].sync_once(send=receiver(peers))
    remote = store.list_rooms(user)[0]['id']
    store.send_message(user, remote, 'r1', 'a reply')
    with a[0].transaction() as db:  # the receiver loses the room, as a restore from an older copy would leave it
        for table, column in (('room_activity', 'room_id'), ('room_members', 'room_id'), ('remote_room_members', 'room_id'),
                              ('messages', 'room_id'), ('peer_messages', 'room_id'), ('rooms', 'id')):
            db.execute(f'DELETE FROM {table} WHERE {column}=?', (room['id'],))
    share(peers['live'], fed_contact(peers['live'], a))
    by_id = {a[2].identity.peer_id: a[2]}

    def send(card, prepare):
        return by_id[card['peer_id']].receive(prepare())
    fed.sync_once(send=send)
    states = sorted((r['action'], r['status'], r['last_error']) for r in rows(peers['live']))
    assert ('room.reply', 'refused', '403 Room recipient or epoch changed') in states
    assert ('layer.release', 'delivered', None) in states


def fed_contact(peer, a):
    """The contact id `peer` holds for Alice."""
    with peer[0].transaction() as db:
        return db.execute('SELECT id FROM remote_contacts WHERE peer_id=?', (a[2].identity.peer_id,)).fetchone()[0]


# Plan Task 9: the two Ops notices (spec §8, nit 22). Each id names its episode, so Odo, which announces an id once,
# announces a peer again after it recovers and goes quiet or fails again.

DAY = 86400


def notices(a, kind):
    return [n for n in a[0].station_notices() if n['id'].startswith(kind)]


def test_ops_notices_a_push_peer_failing_for_a_day_but_not_a_first_failure_after_a_quiet_day(world):
    """failing_since starts when failures goes from 0 to 1, so the notice means a day of failing, not a day since the
    last success: a peer quiet for two days that fails once is not announced (nit 22)."""
    clock, a, peers, contacts = world
    share(a, contacts['live'])
    a[2].sync_once(send=receiver(peers))
    clock.at += 2 * DAY
    share(a, contacts['live'], 'after a quiet day')
    a[2].sync_once(send=answering(peers, OSError('connection refused')))
    assert delivery(a, peer_of(peers, 'live'))['failing_since'] == clock() and notices(a, 'push-failing-') == []
    clock.at += DAY
    assert notices(a, 'push-failing-') == []
    clock.at += 1
    [notice] = notices(a, 'push-failing-')
    assert notice['text'].startswith('Delivery to Lena has failed for a day.') and '@' not in notice['text']
    assert all('Lena' not in n['text'] for n in notices(a, 'pull-quiet-'))  # Mo, the pull peer, is quiet too by now
    assert a[2].sync_once(send=receiver(peers))['delivered'] == 1  # its retry is long due: it delivers, and recovers
    assert notices(a, 'push-failing-') == []


def test_ops_notices_a_pull_peer_quiet_for_a_day_from_its_last_pull_or_else_its_pairing(world):
    from test_federation_pull import pull
    clock, a, peers, contacts = world
    assert notices(a, 'pull-quiet-') == []              # paired just now, never pulled
    clock.at += DAY
    assert notices(a, 'pull-quiet-') == []
    clock.at += 1
    [first] = notices(a, 'pull-quiet-')                 # a day since the pairing's confirmation
    assert first['text'].startswith("Mo hasn't fetched from this station for a day.") and '@' not in first['text']
    pull(peers['mac'], a, clock)
    assert notices(a, 'pull-quiet-') == []
    clock.at += DAY + 1
    [second] = notices(a, 'pull-quiet-')                # a day since its last pull: a new episode, a new id
    assert second['id'] != first['id']
    assert notices(a, 'push-failing-') == []
