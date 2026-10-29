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
    until `at` + 300; replayed 598 s later it still passes the clock, so its nonce must still be there. With a day's
    keep this no longer tells `at` from arrival (storing `int(now)` would pass); the boundary test below pins the keep."""
    clock, a, peers, contacts = pulling
    early = request(peers['mac'], a, clock, at=int(clock()) + 299)
    a[2].serve_pull(canonical(early))
    clock.at += 598
    refused(lambda: a[2].serve_pull(canonical(early)), 409, 'Replay')


def test_a_clock_that_runs_ahead_and_is_set_back_prunes_no_nonce_a_replay_needs(pulling):
    """fix:pull-nonces-prune-margin (the restore reader's adjacent note): the prune reads the listener's own clock. If
    it runs 20 minutes ahead while a pull comes in, then is set right, a request served before the jump still passes
    the 300 s check, so its nonce must still be there. Mutation: the prune back at 600 s."""
    clock, a, peers, contacts = pulling
    start = clock.at
    first = request(peers['mac'], a, clock)
    a[2].serve_pull(canonical(first))
    clock.at = start + 1200  # both clocks jump ahead (one fake clock here), and a pull in that time prunes by it
    pull(peers['mac'], a, clock)
    clock.at = start + 10  # and are set right
    refused(lambda: a[2].serve_pull(canonical(first)), 409, 'Replay')


def test_a_nonce_is_kept_exactly_a_day_by_its_at_then_pruned(pulling):
    """The keep's boundary (Rio Grande's reader, S2): a nonce is still there a day after its `at`, and gone a second
    later, so the table stays bounded. Mutations: a shorter keep, `<=` in the prune, no prune at all."""
    clock, a, peers, contacts = pulling
    start = clock.at
    first = request(peers['mac'], a, clock)
    a[2].serve_pull(canonical(first))

    def kept():
        with a[0].transaction() as db:
            return db.execute('SELECT 1 FROM pull_nonces WHERE nonce=?', (first['nonce'],)).fetchone() is not None
    clock.at = start + 86400
    pull(peers['mac'], a, clock)
    assert kept()
    clock.at = start + 86401
    pull(peers['mac'], a, clock)
    assert not kept()


def test_the_nonce_prune_uses_an_index_on_at(pulling):
    """The prune runs under the write lock on every verified pull, and a day's keep is about 144 times the rows, so it
    must not scan (Rio Grande's reader, S1: 175 ms at 1.44 M rows without the index, 0.03 ms with it)."""
    clock, a, peers, contacts = pulling
    with a[0].transaction() as db:
        plan = ' '.join(row[-1] for row in db.execute('EXPLAIN QUERY PLAN DELETE FROM pull_nonces WHERE at<?', (0,)))
    assert 'pull_nonces_at' in plan, plan


def mark_restored(a, value):
    """The mark the restore reconcile leaves in system_meta (backups.py _write_mark)."""
    with a[0].transaction() as db:
        db.execute("INSERT OR REPLACE INTO system_meta VALUES('restore_reconcile', ?)", (value,))


def test_a_request_signed_before_a_restore_is_a_replay_even_from_a_fast_clock(pulling):
    """fix:restore-keeps-pull-nonces: a restored copy's nonces end where it was taken, and a request used before the
    restore had an `at` of at most the mark plus 300 s (Rio Grande's reader: a peer whose clock runs ahead). So up to
    there it counts as a replay even though its nonce isn't there; past it, a request is served. The puller asks again
    on a Replay, so pulls wait out those 5 minutes once. Mutations: no floor, the mark alone, `<` for `<=`."""
    clock, a, peers, contacts = pulling
    signed = request(peers['mac'], a, clock)  # within the 300 s, its nonce unseen
    restored = int(clock())
    mark_restored(a, json.dumps({'at': float(restored), 'replaced': True, 'path': '/x'}))
    refused(lambda: a[2].serve_pull(canonical(signed)), 409, 'Replay')
    refused(lambda: pull(peers['mac'], a, clock, at=restored - 100), 409, 'Replay')
    refused(lambda: pull(peers['mac'], a, clock, at=restored + 300), 409, 'Replay')  # a peer 300 s ahead
    clock.at += 1
    assert pull(peers['mac'], a, clock, at=restored + 301)['more'] is False


def test_a_restore_mark_in_the_past_holds_only_until_it_plus_300_s(pulling):
    """The floor follows the mark, not the listener's clock (the reader's M5: `now` for the mark survived a test whose
    mark was now). Mutation: the floor taken from now."""
    clock, a, peers, contacts = pulling
    restored = int(clock()) - 200
    mark_restored(a, json.dumps({'at': float(restored), 'replaced': False, 'path': '/x'}))
    refused(lambda: pull(peers['mac'], a, clock, at=restored + 300), 409, 'Replay')
    assert pull(peers['mac'], a, clock, at=restored + 301)['more'] is False


@pytest.mark.parametrize('mark', ['not json', '{"at": 1e999}', '{"at": NaN}', '{"at": 1%s}' % ('0' * 400), '{}'],
                         ids=['not-json', 'infinite', 'nan', 'overflow', 'no-at'])
def test_a_damaged_restore_mark_holds_pulls_for_300_s_from_the_listeners_start(pulling, mark):
    """A damaged mark can't say when the restore was, and the listener restarts after every restore (runbook step 8),
    so the floor falls back to its start plus 300 s: closed for 5 minutes, and no longer. A time that isn't a finite
    number is damaged too: 1e999 used to refuse every pull for good, NaN set no floor, 10**400 raised (the reader's
    should-fix 2). Mutations: a damaged mark as no floor, or as +inf."""
    clock, a, peers, contacts = pulling
    started = a[2]._started
    mark_restored(a, mark)
    refused(lambda: pull(peers['mac'], a, clock, at=int(started) + 300), 409, 'Replay')
    clock.at = started + 301
    assert pull(peers['mac'], a, clock, at=int(started) + 301)['more'] is False


# Federation pull, plan Task 6: the per-envelope boundary (spec §4, M3; tests 8a and 8b) and the walk's bounds (§4, SF8,
# check 3 SF6; P5 and RG)

def two_layers(a, contact):
    first, second = share(a, contact, 'first'), share(a, contact, 'second')
    a[2].collect()
    by_layer = {r['resource_id']: r['id'] for r in outbox(a)}
    return first, second, by_layer[first], by_layer[second]


def test_8a_a_withdrawal_committed_before_a_row_is_prepared_comes_back_withdrawn(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    first, second, row1, row2 = two_layers(a, contacts['mac'])

    def between(key):
        if key == row2:
            a[0].withdraw_layer(a[1], second)  # committed while the walk runs, before row 2 is prepared
    a[2]._between_rows = between
    got = pull(mac, a, clock)
    assert [json.loads(e)['event_id'] for e in got['envelopes']] == [row1]
    states = {r['id']: r['status'] for r in outbox(a)}
    assert states[row2] == 'withdrawn'


def test_8b_a_withdrawal_committed_after_a_row_was_prepared_arrives_as_the_next_pulls_withdraw(pulling):
    """The pull boundary is per envelope: a release prepared before the withdrawal stays in this response, and the
    withdrawal goes out as the next pull's own event (layer.withdraw here, room.withdraw for a room)."""
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    first, second, row1, row2 = two_layers(a, contacts['mac'])

    def between(key):
        if key == row2:
            a[0].withdraw_layer(a[1], first)  # row 1 was already prepared and is in this response
    a[2]._between_rows = between
    got = pull(mac, a, clock)
    sent = {json.loads(e)['event_id']: json.loads(e)['action'] for e in got['envelopes']}
    assert sent == {row1: 'layer.release', row2: 'layer.release'}
    a[2]._between_rows = lambda key: None
    after = pull(mac, a, clock, ack=[row1, row2])
    actions = [(json.loads(e)['resource_id'], json.loads(e)['action']) for e in after['envelopes']]
    assert actions == [(first, 'layer.withdraw')]


def test_300_obsolete_rows_examine_200_hold_the_gate_per_row_and_leave_more(pulling):
    """Spec §4 (SF8): at most 200 rows examined per pull, each under its own hold of the gate, never one across rows."""
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    layer = share(a, contacts['mac'], 'current')
    a[2].collect()
    with a[0].transaction() as db:  # 300 rows ahead of it for a revision the layer no longer has: each is obsolete
        for n in range(300):
            db.execute("INSERT INTO outbox(id,event_seq,contact_id,resource_id,revision,action,metadata,status) "
                       "VALUES(?,?,?,?,0,'layer.release','{}','pending')", (uuid.uuid4().hex, -300 + n, contacts['mac'], layer))
    lock, local = a[0].dispatch_gate.state
    depths = []
    a[2]._between_rows = lambda key: depths.append(getattr(local, 'depth', 0))
    got = pull(mac, a, clock)
    assert got['envelopes'] == [] and got['more'] is True
    assert len(depths) == 200 and set(depths) == {0}
    assert sum(r['status'] == 'withdrawn' for r in outbox(a)) == 200



@pytest.mark.parametrize('first, second', [('x' * 70_000, 'y' * 70_000), ('\U0001F600' * 20_000, '\U0001F601' * 20_000)],
                         ids=['ascii', 'astral'])
def test_a_pull_stops_at_its_budget_and_an_envelope_over_it_goes_alone(pulling, first, second):
    """Spec §4, step 5 (found untested on the spec walk after Rio Grande's section 2): the walk stops at the request's
    budget in encoded bytes, but an envelope over the budget still goes when nothing else is ready, so a large row can't
    block the queue. The next one waits, `more` says so, and the next pull brings it."""
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    share(a, contacts['mac'], first)  # each over the 65,536-byte budget in bytes; the astral ones only in bytes (MF2)
    share(a, contacts['mac'], second)
    got = pull(mac, a, clock, budget=65_536)
    assert [json.loads(e)['payload']['body'] for e in got['envelopes']] == [first] and got['more'] is True
    acked = [json.loads(e)['event_id'] for e in got['envelopes']]
    again = pull(mac, a, clock, budget=65_536, ack=acked)
    assert [json.loads(e)['payload']['body'] for e in again['envelopes']] == [second] and again['more'] is False

def test_the_walk_stops_at_its_time_and_says_more(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    for n in range(10):
        share(a, contacts['mac'], f'slow {n}')
    a[2].pull_walk_seconds = 0.3
    a[2]._between_rows = lambda key: __import__('time').sleep(0.1)
    got = pull(mac, a, clock)
    assert 1 <= len(got['envelopes']) < 10 and got['more'] is True


@pytest.mark.parametrize('pad', ['ascii', 'astral'])
def test_an_envelope_too_large_to_pull_is_refused_where_it_waits_and_its_owner_sees_why(pulling, monkeypatch, pad):
    """Plan P5 and RG: an envelope whose JSON-string form alone can't fit the transport's cap is refused, "413 Too large to
    pull", the row behind it arrives in the same pull, and the release's owner sees why in status(). The astral pad is
    a quarter of the cap in characters and the whole cap in bytes, so P5 must count bytes (the re-check's N9)."""
    from superyak_peer.transport import PULL_CAP
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    first, second, row1, row2 = two_layers(a, contacts['mac'])
    real = a[2]._prepare_in
    extra = (' ' * PULL_CAP if pad == 'ascii' else '\U0001F600' * (PULL_CAP // 4)).encode()

    def huge(db, key):
        body = real(db, key)
        return body + extra if key == row1 else body  # test-only: a body the cap can't carry
    monkeypatch.setattr(a[2], '_prepare_in', huge)
    got = pull(mac, a, clock)
    assert [json.loads(e)['event_id'] for e in got['envelopes']] == [row2]
    seen = {s['id']: (s['status'], s['last_error']) for s in a[2].status(a[1])}
    assert seen[row1] == ('refused', '413 Too large to pull')


# Task 7: the puller (spec §6; plan P7, P12, SF1, SF2, nits 20 and 23), with the listener's serve_pull as `send=`

REAL = object()


def listener_card(peer, a):
    """The listener's card as the puller holds it, from its own peers table."""
    with peer[0].transaction() as db:
        return json.loads(db.execute('SELECT card FROM peers WHERE peer_id=?', (a[2].identity.peer_id,)).fetchone()[0])


def delivery(peer, a):
    with peer[0].transaction() as db:
        return dict(db.execute('SELECT * FROM peer_delivery WHERE peer_id=?', (a[2].identity.peer_id,)).fetchone())


class Wire:
    """`send=` for pull_once: each request it carried, parsed, and each answer's status. A scripted step answers first
    (an exception is raised, a dict returned, REAL goes to the listener); after the script, the listener answers."""
    def __init__(self, a, *script):
        self.a, self.script, self.requests, self.answers = a, list(script), [], []

    def __call__(self, card, body):
        self.requests.append(json.loads(body))
        step = self.script.pop(0) if self.script else REAL
        if isinstance(step, BaseException):
            self.answers.append(getattr(step, 'status', type(step).__name__))
            raise step
        if step is not REAL:
            self.answers.append(200)
            return step
        try:
            answer = self.a[2].serve_pull(body)
        except Problem as problem:
            self.answers.append(problem.status)
            raise
        self.answers.append(200)
        return answer


def test_pull_once_receives_and_its_acks_deliver_the_rows(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    share(a, contacts['mac'], 'one'), share(a, contacts['mac'], 'two')
    wire = Wire(a)
    got = mac[2].pull_once(listener_card(mac, a), send=wire)
    assert (got['received'], got['next']) == (2, 60)
    assert [r['status'] for r in outbox(a, mac[2].identity.peer_id)] == ['delivered', 'delivered']
    assert wire.requests[-1]['limit'] == 0 and len(wire.requests[-1]['ack']) == 2  # acks left: limit 0 (nit 20)
    assert len({r['nonce'] for r in wire.requests}) == len(wire.requests)
    later = Wire(a)
    mac[2].pull_once(listener_card(mac, a), send=later)
    assert later.requests[0]['ack'] == []  # acks a pull carried are owed no more


def test_an_envelope_from_another_origin_is_dropped_and_one_that_doesnt_parse_goes_to_receive(pulling, monkeypatch):
    clock, a, peers, contacts = pulling
    mac, push = peers['mac'], peers['push']
    foreign = push[2].identity.envelope(destination=mac[2].identity.peer_id, actor=push[1], resource_id='x', revision=1,
                                        action='layer.release', recipients=[mac[1]], payload={})
    seen, real = [], mac[2].receive

    def receive(raw):
        seen.append(raw)
        return real(raw)
    monkeypatch.setattr(mac[2], 'receive', receive)
    wire = Wire(a, {'ok': True, 'envelopes': [canonical(foreign).decode(), 'not json'], 'more': False})
    got = mac[2].pull_once(listener_card(mac, a), send=wire)
    assert got['dropped'] == 1 and seen == [b'not json']  # the foreign one never reached receive (nit 23)
    assert (got['received'], got['refused'], got['unreadable'], len(wire.requests)) == (0, 0, 1, 1)


def test_unknown_remote_participant_comes_back_refused_and_the_next_row_arrives(pulling, monkeypatch):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    first, second, row1, row2 = two_layers(a, contacts['mac'])
    real = mac[2].receive

    def receive(raw):
        if json.loads(raw)['event_id'] == row1:
            raise Problem(403, 'Unknown remote participant')
        return real(raw)
    monkeypatch.setattr(mac[2], 'receive', receive)
    got = mac[2].pull_once(listener_card(mac, a), send=Wire(a))
    states = {r['id']: (r['status'], r['last_error']) for r in outbox(a)}
    assert states[row1] == ('refused', '403') and states[row2][0] == 'delivered'
    assert (got['received'], got['refused']) == (1, 1)


@pytest.mark.parametrize('answer', [Problem(429, 'Slow down'), Problem(403, 'Peer authentication failed'),
                                    Problem(500, 'Boom'), OSError('disk')])
def test_a_peer_scoped_answer_to_an_envelope_is_neither_acked_nor_refused_and_the_rounds_stop(pulling, monkeypatch,
                                                                                              answer):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    share(a, contacts['mac'])

    def receive(raw):
        raise answer
    monkeypatch.setattr(mac[2], 'receive', receive)
    [envelope] = pull(mac, a, clock)['envelopes']
    wire = Wire(a, *[{'ok': True, 'envelopes': [envelope], 'more': True}] * 12)  # more to come, and nothing it can take
    got = mac[2].pull_once(listener_card(mac, a), send=wire)
    assert [r['status'] for r in outbox(a, mac[2].identity.peer_id)] == ['pending']
    assert len(wire.requests) == 1 and (got['received'], got['refused']) == (0, 0)  # nothing new: one round (P12)


FAILURES = [Problem(500, 'Boom'), Problem(401, 'Who'), Problem(408, 'Slow'), Problem(421, 'Misdirected'),
            Problem(425, 'Early'), Problem(429, 'Wait'), TimeoutError('Peer pull response stalled'), OSError('reset'),
            {'ok': True, 'envelopes': 'not a list', 'more': False}, {'ok': True, 'envelopes': []}]


@pytest.mark.parametrize('answer', FAILURES)
def test_a_failing_pull_is_a_peer_failure_with_its_own_backoff(pulling, answer):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    got = mac[2].pull_once(listener_card(mac, a), send=Wire(a, answer))
    row = delivery(mac, a)
    assert (row['failures'], row['next_attempt'], got['next']) == (1, clock() + 2, 2) and row['last_problem']
    assert row['failing_since'] == clock()


def test_the_pull_backoff_is_capped_at_5_minutes(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    with mac[0].transaction() as db:
        db.execute('UPDATE peer_delivery SET failures=10 WHERE peer_id=?', (a[2].identity.peer_id,))
    got = mac[2].pull_once(listener_card(mac, a), send=Wire(a, Problem(503, 'Down')))
    assert got['next'] == 300 and delivery(mac, a)['next_attempt'] == clock() + 300


def test_a_pin_mismatch_on_a_pull_is_a_peer_failure_that_says_certificate_differs(pulling):
    from superyak_peer.transport import PinMismatch
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    mac[2].pull_once(listener_card(mac, a), send=Wire(a, PinMismatch('the pin')))
    assert (delivery(mac, a)['failures'], delivery(mac, a)['last_problem']) == (1, 'certificate differs')


def test_busy_is_asked_again_after_5_s_with_a_new_nonce_and_a_second_busy_waits_60_s(pulling, caplog):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    share(a, contacts['mac'])
    slept, wire = [], Wire(a, Problem(409, 'Busy'))
    got = mac[2].pull_once(listener_card(mac, a), send=wire, sleep=slept.append)
    assert slept == [5] and got['received'] == 1 and wire.requests[0]['nonce'] != wire.requests[1]['nonce']
    again = mac[2].pull_once(listener_card(mac, a), send=Wire(a, Problem(409, 'Busy'), Problem(409, 'Busy')),
                             sleep=slept.append)
    assert again['next'] == 60 and slept == [5, 5] and delivery(mac, a)['failures'] == 0
    assert not [r for r in caplog.records if 'a bug on one side' in r.getMessage()]  # Rio Grande's N6: no bug, the next pull


def test_replay_is_asked_again_at_once_once(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    share(a, contacts['mac'])
    slept = []
    got = mac[2].pull_once(listener_card(mac, a), send=Wire(a, Problem(409, 'Replay')), sleep=slept.append)
    assert slept == [] and got['received'] == 1
    twice = mac[2].pull_once(listener_card(mac, a), send=Wire(a, Problem(409, 'Replay'), Problem(409, 'Replay')))
    assert twice['next'] == 60 and delivery(mac, a)['failures'] == 0


def test_a_403_is_no_failure_its_words_are_kept_and_a_clock_warning_too(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    got = mac[2].pull_once(listener_card(mac, a), send=Wire(a, Problem(403, 'Clocks differ by more than 5 minutes')))
    row = delivery(mac, a)
    assert (row['failures'], row['last_problem']) == (0, '403 Clocks differ by more than 5 minutes')
    assert got['next'] == 60 and got['clock'] is True


def test_a_404_waits_5_minutes_and_leaves_peer_delivery_untouched(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    before = delivery(mac, a)
    got = mac[2].pull_once(listener_card(mac, a), send=Wire(a, Problem(404, 'Not found')))
    assert got['next'] == 300 and delivery(mac, a) == before


def test_a_400_waits_60_s_and_keeps_the_acks_for_the_next_pull(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    share(a, contacts['mac'])
    got = mac[2].pull_once(listener_card(mac, a), send=Wire(a, REAL, Problem(400, 'Invalid pull request')))
    [row] = outbox(a, mac[2].identity.peer_id)
    assert (got['received'], got['next'], row['status']) == (1, 60, 'pending') and delivery(mac, a)['failures'] == 0
    wire = Wire(a)
    mac[2].pull_once(listener_card(mac, a), send=wire)
    assert wire.requests[0]['ack'] == [row['id']] and outbox(a, mac[2].identity.peer_id)[0]['status'] == 'delivered'


def test_300_obsolete_rows_then_a_live_one_come_in_one_pull_once_and_its_own_rounds_never_get_409(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    layer = share(a, contacts['mac'], 'current')
    a[2].collect()
    with a[0].transaction() as db:
        for n in range(300):
            db.execute("INSERT INTO outbox(id,event_seq,contact_id,resource_id,revision,action,metadata,status) "
                       "VALUES(?,?,?,?,0,'layer.release','{}','pending')", (uuid.uuid4().hex, -300 + n, contacts['mac'], layer))
    wire = Wire(a)
    got = mac[2].pull_once(listener_card(mac, a), send=wire)
    assert got['received'] == 1 and got['rounds'] == 2 and 409 not in wire.answers
    states = [r['status'] for r in outbox(a, mac[2].identity.peer_id)]
    assert states.count('withdrawn') == 300 and states.count('delivered') == 1


def test_rounds_stop_at_10_and_the_next_pull_goes_at_once(pulling):
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    empty = {'ok': True, 'envelopes': [], 'more': True}  # what a walk that stopped at 200 rows or 5 s returns
    wire = Wire(a, *[empty] * 12)
    got = mac[2].pull_once(listener_card(mac, a), send=wire)
    assert (got['rounds'], len(wire.requests), got['next']) == (10, 10, 0)


def test_a_push_backoff_doesnt_hold_back_a_pull_and_a_pull_resets_it(pulling):
    """SF2: the pull keeps its own due time. A listener whose events route kept failing still gets pulled, its
    envelopes arrive, and the successful pull resets the row so pushes go again at once."""
    clock, a, peers, contacts = pulling
    mac = peers['mac']
    with mac[0].transaction() as db:
        db.execute('UPDATE peer_delivery SET failures=7, next_attempt=?, failing_since=?, last_problem=? WHERE peer_id=?',
                   (clock() + 3000, clock() - 100, '500 Boom', a[2].identity.peer_id))
    share(a, contacts['mac'])
    got = mac[2].pull_once(listener_card(mac, a), send=Wire(a))
    row = delivery(mac, a)
    assert got['received'] == 1
    assert (row['failures'], row['next_attempt'], row['failing_since'], row['last_problem']) == (0, None, None, None)
    # Rio Grande's SF2: a pull is "last pulled from it", never "last delivered", which only a push to it records
    assert (row['last_pull'], row['last_success']) == (clock(), None)
