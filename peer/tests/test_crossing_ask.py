"""Ship home and crossing plan, Task 6: the asking side (P8, P17, P6). `ask` takes one line from crossing.sock, checks
the hosted store and the destination, signs a crossing as this peer with a fresh nonce, dials the publisher pinned
within the deadline, and hands back the frame only once the signed answer verifies."""
import json
import threading
import time
import uuid

import pytest

from superyak_peer import crossing
from superyak_peer.identity import canonical, verify_crossing
from superyak_peer.transport import PeerAnswer, PinMismatch

from test_crossing_route import INSTANCE, frame_of, recall_result, write_settings, world  # noqa: F401 - the fixture
from test_federation_outcomes import station


def hosted(w, ship='tardis', instance=INSTANCE):
    write_settings(w.m[0].data_dir, f'[[hosted]]\nship = "{ship}"\ninstance_id = "{instance}"\n',
                   mtime=time.time_ns())


def line(w, frame=None, **change):
    value = {'receiver_instance': INSTANCE, 'receiver_ship': w.tardis['id'], 'destination': w.a[2].identity.peer_id,
             'publisher_ship': w.rio['id'], 'frame': frame or frame_of(), 'deadline_ms': 2000}
    value.update(change)
    return canonical(value)


@pytest.fixture
def asking(world, monkeypatch):
    """`m` hosts tardis's store, and its dial is `a` serving in process: `dials` records each (card, body, deadline)."""
    hosted(world)
    dials = []

    def dial(card, body, *, deadline):
        dials.append((card, json.loads(body), deadline))
        return world.a[2].serve_crossing(body)
    monkeypatch.setattr(crossing, 'crossing_pinned', dial)
    return world, dials


def ask(w, raw):
    return crossing.ask(w.m[2], raw)


def test_a_hosted_store_asks_and_gets_the_frame(asking):
    w, dials = asking
    reply = ask(w, line(w))
    assert reply['ok'] is True and reply['frame']['kind'] == 'recall_result'
    assert reply['frame']['disclosureId'] == 'd' * 32
    assert len(dials) == 1


def test_the_request_it_sends_is_this_peers_with_a_fresh_nonce_and_verifies(asking):
    w, dials = asking
    w.daemon.answer = lambda frame: recall_result(frame, disclosure=uuid.uuid4().hex)
    ask(w, line(w))
    ask(w, line(w))
    [(card, first, deadline), (_, second, _)] = dials
    assert card['peer_id'] == w.a[2].identity.peer_id and card['endpoint']
    assert first['origin'] == w.m[2].identity.peer_id and first['kind'] == 'crossing'
    assert first['nonce'] != second['nonce'] and len(first['nonce']) == 32
    assert first['at'] == int(w.clock())
    m_card = w.m[2].identity.card(None, {'id': w.tardis['id'], 'name': 'Tardis'}, delivery='pull')
    assert verify_crossing(m_card, first) == first
    assert 1900 <= first['deadline_ms'] <= 2000 and deadline - time.monotonic() < 2.5


@pytest.mark.parametrize('case', ['unlisted store', 'another ship', 'no settings'])
def test_a_store_not_hosted_for_that_ship_is_not_hosted(asking, case):
    w, dials = asking
    if case == 'unlisted store':
        raw = line(w, receiver_instance='00000000-0000-4000-8000-000000000000')
    elif case == 'another ship':
        raw = line(w, receiver_ship=w.m[1])  # mo is a person, and no [[hosted]] row names it
    else:
        (w.m[0].data_dir / 'crossings.toml').unlink()
        raw = line(w)
    assert ask(w, raw) == {'ok': False, 'code': 'NOT_HOSTED'}
    assert dials == []


def test_a_destination_that_isnt_a_paired_push_peer_is_not_paired(asking, tmp_path):
    w, dials = asking
    assert ask(w, line(w, destination='c' * 64)) == {'ok': False, 'code': 'NOT_PAIRED'}
    puller = station(tmp_path / 'p', 'pia', w.clock, mode='pull')
    card = puller[2].card(puller[1])
    with w.m[0].transaction() as db:  # a pull card here: two pull peers can't pair, so this is a hand-made row
        db.execute('INSERT INTO peers VALUES(?,?,1)', (card['peer_id'], json.dumps(card)))
    assert ask(w, line(w, destination=card['peer_id'])) == {'ok': False, 'code': 'NOT_PAIRED'}
    with w.m[0].transaction() as db:
        db.execute('UPDATE peers SET paired=0 WHERE peer_id=?', (w.a[2].identity.peer_id,))
    assert ask(w, line(w)) == {'ok': False, 'code': 'NOT_PAIRED'}
    assert dials == []


@pytest.mark.parametrize('ms', [0, 50, 99])
def test_under_100_ms_is_a_timeout_without_a_dial(asking, ms):
    w, dials = asking
    assert ask(w, line(w, deadline_ms=ms)) == {'ok': False, 'code': 'TIMEOUT'}
    assert dials == []


def test_a_query_too_large_for_the_route_is_refused_without_a_dial(asking):
    """P17: 4,096 four-byte characters are 16 KiB of UTF-8 alone, so the canonical signed request passes 16 KiB."""
    w, dials = asking
    assert ask(w, line(w, frame_of(query='\U0001F600' * 4096))) == {'ok': False, 'code': 'QUERY_TOO_LARGE'}
    assert dials == []


@pytest.mark.parametrize('raw', [b'not json', b'{}', b'[]', b'{"receiver_instance": 1}', b'{"x": "' + b'y' * 32 * 1024 + b'"}'])
def test_a_malformed_local_request_is_refused_without_a_dial(asking, raw):
    w, dials = asking
    assert ask(w, raw) == {'ok': False, 'code': 'BAD_REQUEST'}
    assert dials == []


def test_a_local_request_with_an_extra_key_or_a_bad_frame_is_refused(asking):
    w, dials = asking
    extra = json.loads(line(w))
    extra['origin'] = 'f' * 64
    assert ask(w, canonical(extra)) == {'ok': False, 'code': 'BAD_REQUEST'}
    assert ask(w, line(w, frame_of(k=21))) == {'ok': False, 'code': 'BAD_REQUEST'}
    assert dials == []


@pytest.mark.parametrize('error, code', [(PeerAnswer(429, 'Too many crossings'), 'REFUSED_429'),
                                         (PeerAnswer(403, 'Receiving ship is not a current contact'), 'REFUSED_CONTACT'),
                                         (PeerAnswer(403, 'Receiving ship is paired only by an owner trust, which '
                                                          'crossings do not accept'), 'REFUSED_TRUST_ONLY'),
                                         (PeerAnswer(403, 'Clocks differ by more than 5 minutes'), 'REFUSED_CLOCK'),
                                         (PeerAnswer(403, 'Peer authentication failed'), 'REFUSED_SIGNATURE'),
                                         (PeerAnswer(403, 'Unknown or unpaired peer'), 'REFUSED_UNPAIRED'),
                                         (PeerAnswer(403, 'Some other refusal'), 'REFUSED_403'),
                                         (PeerAnswer(404, 'No published house for that ship'), 'REFUSED_404'),
                                         (TimeoutError('Peer deadline exceeded'), 'TIMEOUT'),
                                         (PinMismatch('Peer certificate differs from its card'), 'UNAVAILABLE'),
                                         (ConnectionRefusedError(), 'UNAVAILABLE')])
def test_a_failed_dial_answers_its_code(asking, monkeypatch, error, code):
    w, _ = asking

    def dial(card, body, *, deadline):
        raise error
    monkeypatch.setattr(crossing, 'crossing_pinned', dial)
    assert ask(w, line(w)) == {'ok': False, 'code': code}


BAD_ANSWERS = ['signature', 'request_digest', 'nonce', 'origin', 'destination', 'extra', 'read_result for a recall',
               'no disclosureId', 'kind', 'not a dict']


@pytest.mark.parametrize('change', BAD_ANSWERS)
def test_every_bad_answer_is_bad_answer_and_returns_no_frame(asking, monkeypatch, change):
    import base64
    w, _ = asking
    a_identity = w.a[2].identity

    def dial(card, body, *, deadline):
        good = w.a[2].serve_crossing(body)
        unsigned = {k: v for k, v in good.items() if k != 'signature'}
        if change == 'signature':
            raw = bytearray(base64.b64decode(good['signature']))
            raw[0] ^= 1
            return {**good, 'signature': base64.b64encode(bytes(raw)).decode()}
        if change in ('request_digest', 'nonce', 'destination'):
            return a_identity.sign_crossing_answer({**unsigned, change: '0' * len(unsigned[change])})
        if change == 'origin':
            return {**good, 'origin': w.m[2].identity.peer_id}
        if change == 'extra':
            return {**good, 'more': 1}
        if change == 'read_result for a recall':
            return a_identity.sign_crossing_answer({**unsigned, 'frame': {**unsigned['frame'], 'kind': 'read_result'}})
        if change == 'no disclosureId':
            frame = {k: v for k, v in unsigned['frame'].items() if k != 'disclosureId'}
            return a_identity.sign_crossing_answer({**unsigned, 'frame': frame})
        if change == 'kind':
            return {**good, 'kind': 'crossing'}
        return ['not', 'a', 'dict']
    monkeypatch.setattr(crossing, 'crossing_pinned', dial)
    assert ask(w, line(w)) == {'ok': False, 'code': 'BAD_ANSWER'}


def test_a_good_answer_returns_the_frame_unchanged(asking, monkeypatch):
    w, _ = asking
    seen = []

    def dial(card, body, *, deadline):
        answer = w.a[2].serve_crossing(body)
        seen.append(answer)
        return answer
    monkeypatch.setattr(crossing, 'crossing_pinned', dial)
    reply = ask(w, line(w, frame_of('read')))
    assert reply == {'ok': True, 'frame': seen[0]['frame']}


def test_a_third_crossing_to_one_destination_waits_then_runs(asking, monkeypatch):
    """P6, the asking side: at most two crossings in flight per destination, so its own load can't earn 429s. A third
    waits within its deadline, and runs when one finishes."""
    w, _ = asking
    release, started, lock = threading.Event(), [], threading.Lock()

    def dial(card, body, *, deadline):
        with lock:
            started.append(json.loads(body)['nonce'])
            first_two = len(started) <= 2
        if first_two:
            release.wait(10)
        return w.a[2].serve_crossing(body)
    monkeypatch.setattr(crossing, 'crossing_pinned', dial)
    w.daemon.answer = lambda frame: recall_result(frame, disclosure=uuid.uuid4().hex)
    replies = []
    threads = [threading.Thread(target=lambda: replies.append(ask(w, line(w, deadline_ms=10_000)))) for _ in range(3)]
    for thread in threads:
        thread.start()
    end = time.monotonic() + 10
    while len(started) < 2 and time.monotonic() < end:
        time.sleep(0.01)
    time.sleep(0.3)
    assert len(started) == 2  # the third waits for a slot
    release.set()
    for thread in threads:
        thread.join(10)
    assert len(started) == 3 and [r['ok'] for r in replies] == [True] * 3


def test_a_third_crossing_whose_deadline_passes_while_waiting_is_a_timeout(asking, monkeypatch):
    w, _ = asking
    release = threading.Event()

    def dial(card, body, *, deadline):
        release.wait(10)
        raise TimeoutError()
    monkeypatch.setattr(crossing, 'crossing_pinned', dial)
    threads = [threading.Thread(target=lambda: ask(w, line(w, deadline_ms=10_000))) for _ in range(2)]
    for thread in threads:
        thread.start()
    time.sleep(0.2)
    try:
        started = time.monotonic()
        assert ask(w, line(w, deadline_ms=300)) == {'ok': False, 'code': 'TIMEOUT'}
        assert time.monotonic() - started < 1.5
    finally:
        release.set()
        for thread in threads:
            thread.join(10)


@pytest.mark.parametrize('why, code', [('held', 'REFUSED_CONTACT'), ('trust only', 'REFUSED_TRUST_ONLY'),
                                       ('unpaired', 'REFUSED_UNPAIRED'), ('stale clock', 'REFUSED_CLOCK')])
def test_the_publishers_refusal_reaches_the_receiver_by_its_code(asking, monkeypatch, why, code):
    """The section 2 review's M2, both ends: the publisher's 403 words, carried as HTTP carries them, become the
    asking side's code, so the receipt tells a trust-only ship from a held one, an unpaired origin or a clock."""
    from superyak_peer.common import Problem
    from test_crossing_route import hold_contact, trust_only
    w, _ = asking

    def dial(card, body, *, deadline):
        try:
            return w.a[2].serve_crossing(body)
        except Problem as refusal:
            raise PeerAnswer(refusal.status, refusal.message) from None
    monkeypatch.setattr(crossing, 'crossing_pinned', dial)
    if why == 'held':
        hold_contact(w)
    elif why == 'trust only':
        trust_only(w)
    elif why == 'unpaired':
        w.a[2].unpair(w.a[1], w.contact)
    else:
        shared = w.clock
        monkeypatch.setattr(w.a[0], 'clock', lambda: shared() + 600)  # the publisher's clock alone, ten minutes ahead
    assert ask(w, line(w)) == {'ok': False, 'code': code}
