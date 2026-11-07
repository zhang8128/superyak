"""Federation pull, plan Task 8: federation-listen's app, three routes and nothing else (P9, nits 11, 18 and 20); the
third, /federation/crossing, is the ship home and crossing plan's Task 5."""
import json
import subprocess
import sys

import pytest
from starlette.testclient import TestClient

from superyak_peer.identity import MAX_ENVELOPE, canonical, pairing_code
from test_federation_outcomes import Clock, share, station
from test_federation_pull import request as pull_request


@pytest.fixture
def listening(tmp_path):
    """Alice's push peer `a` behind its listener, paired with a push peer `pat` and a pull peer `mo`."""
    from superyak_peer.listener import create_listener
    clock = Clock()
    a = station(tmp_path / 'a', 'alice', clock)
    pat, mo = station(tmp_path / 'pat', 'pat', clock), station(tmp_path / 'mo', 'mo', clock, mode='pull')
    contacts = {}
    for key, peer in (('pat', pat), ('mo', mo)):
        card = peer[2].card(peer[1])
        contacts[key] = a[2].pair(a[1], card, code=pairing_code(card))['id']
        mine = a[2].card(a[1])
        contacts[key + '-there'] = peer[2].pair(peer[1], mine, code=pairing_code(mine))['id']
    client = TestClient(create_listener(None, federation=a[2]), base_url='https://listener.example')
    return client, clock, a, pat, mo, contacts


def test_a_push_from_a_paired_peer_is_received(listening):
    client, clock, a, pat, mo, contacts = listening
    share(pat, contacts['pat-there'], 'from pat')
    pat[2].collect()
    with pat[0].transaction() as db:
        key = db.execute('SELECT id FROM outbox').fetchone()[0]
    answer = client.post('/federation/events', content=pat[2]._prepared(key))
    assert (answer.status_code, answer.json()) == (200, {'ok': True, 'duplicate': False})


def test_a_pull_from_a_paired_pull_peer_is_served(listening):
    client, clock, a, pat, mo, contacts = listening
    share(a, contacts['mo'], 'for the mac')
    answer = client.post('/federation/pull', content=canonical(pull_request(mo, a, clock)))
    assert answer.status_code == 200 and len(answer.json()['envelopes']) == 1 and answer.json()['ok'] is True
    assert int(answer.headers['content-length']) == len(answer.content)  # the puller refuses a 2xx without one


def test_a_refusal_answers_with_its_status_and_words(listening):
    client, clock, a, pat, mo, contacts = listening
    answer = client.post('/federation/pull', content=b'{"not": "a pull"}')
    assert (answer.status_code, answer.json()) == (400, {'error': 'Invalid pull request'})


@pytest.mark.parametrize('method, path', [('GET', '/federation/events'), ('GET', '/federation/pull'), ('GET', '/'),
                                          ('POST', '/'), ('POST', '/federation/events/x'), ('PUT', '/federation/pull'),
                                          ('POST', '/api/sync'), ('GET', '/federation/crossing'),
                                          ('POST', '/federation/crossing/x')])
def test_only_its_three_routes_are_served(listening, method, path):
    client = listening[0]
    assert client.request(method, path, content=b'{}').status_code == 404


@pytest.mark.parametrize('path, cap', [('/federation/events', MAX_ENVELOPE), ('/federation/pull', 16 * 1024),
                                       ('/federation/crossing', 16 * 1024)])
def test_a_body_over_its_cap_is_refused(listening, path, cap):
    client = listening[0]
    assert client.post(path, content=b'x' * (cap + 1)).status_code == 413


def test_a_larger_content_length_is_refused_unread(listening):
    client = listening[0]
    answer = client.post('/federation/pull', content=b'{}', headers={'content-length': str(16 * 1024 + 1)})
    assert answer.status_code == 413


def test_https_is_required_and_any_host_is_served(listening):
    """No Host check (nit 20): a pinned peer dials the name its card gives. Plain HTTP is refused as the lighthouse
    refuses it, in the words the outcome table knows."""
    from superyak_peer.listener import create_listener
    client, clock, a, pat, mo, contacts = listening
    plain = TestClient(create_listener(None, federation=a[2]), base_url='http://listener.example')
    assert plain.post('/federation/pull', content=b'{}').json() == {'error': 'Federation requires HTTPS'}
    answer = client.post('/federation/pull', content=b'{"x": 1}', headers={'host': 'somewhere.else.example'})
    assert answer.status_code == 400



def largest_release(a, contact, char):
    """The largest release the limits allow (plan P5, SF4): 100 files totalling 4 MiB with 120-character names, a body of
    100,000 and a title of 200 of `char`."""
    import base64
    from superyak_peer.files import MAX_FILE
    size = MAX_FILE // 100
    ids = [a[0].upload_file(a[1], f'{n:03d}' + 'a' * 113 + '.pdf', 'application/pdf',
                            base64.b64encode(b'%PDF-' + b'0' * (size - 5)).decode())['id'] for n in range(100)]
    layer = a[0].create_layer(a[1], {'title': char * 200, 'body': char * 100_000, 'audience_users': [contact],
                                     'attachment_ids': ids})
    a[0].activate_layer(a[1], layer['id'], 1)


@pytest.mark.parametrize('char', ['\x01', '\U0001F600'], ids=['control', 'astral'])
def test_the_largest_release_pulls_through_the_real_listener_encoding(listening, char):
    """Rio Grande's section 2, MF2: P5 and the budget count the bytes the listener sends. A control character costs 7
    bytes in the answer, escaped twice, and is the worst case P5 computed; an astral one cost 12 while the listener sent
    ASCII escapes, which took this release over PULL_CAP, refused unread at every pull for good. Both now arrive."""
    from superyak_peer.transport import PULL_CAP
    client, clock, a, pat, mo, contacts = listening
    largest_release(a, contacts['mo'], char)
    answer = client.post('/federation/pull', content=canonical(pull_request(mo, a, clock)))
    assert answer.status_code == 200 and len(answer.content) <= PULL_CAP, len(answer.content)
    [envelope] = answer.json()['envelopes']
    assert mo[2].receive(envelope.encode())['ok']

def listen(*args):
    return subprocess.run([sys.executable, '-m', 'superyak_peer', 'federation-listen', *map(str, args)],
                          capture_output=True, text=True, timeout=60)


def test_federation_listen_refuses_before_it_serves(tmp_path):
    """P9 and nit 18: no database, no files made; not loopback; not a push peer; no identity."""
    from superyak_peer.db import Store
    empty = tmp_path / 'typo'
    empty.mkdir()
    done = listen('--data-dir', empty, '--port', '0')
    assert done.returncode == 1 and 'peer.sqlite3' in done.stderr and list(empty.iterdir()) == []
    clock = Clock()
    push = station(tmp_path / 'push', 'pat', clock)
    push[2].card(push[1])
    push[0].claim_federation_mode('push')
    done = listen('--data-dir', push[0].data_dir, '--host', '0.0.0.0', '--port', '0')
    assert done.returncode == 1 and 'loopback' in done.stderr
    pull = station(tmp_path / 'pull', 'mo', clock, mode='pull')
    done = listen('--data-dir', pull[0].data_dir, '--port', '0')
    assert done.returncode == 1 and 'push peer' in done.stderr
    bare = Store(tmp_path / 'bare')
    bare.claim_federation_mode('push')
    done = listen('--data-dir', bare.data_dir, '--port', '0')
    assert done.returncode == 1 and 'identity.json' in done.stderr and not (bare.data_dir / 'identity.json').exists()


def test_every_server_waits_only_a_moment_on_open_requests_when_stopped(tmp_path, monkeypatch):
    """fix:lighthouse-shutdown-gap: a restart waited on every open long-poll (an unread waits up to 25 s), so each deploy
    answered 502 for 25 to 41 s. The lighthouse, the door and the listener each pass a short graceful-shutdown timeout."""
    import uvicorn
    from superyak_peer import __main__ as cli
    ran = []
    monkeypatch.setattr(uvicorn, 'run', lambda app, **options: ran.append(options))
    push = station(tmp_path / 'push', 'pat', Clock())
    push[2].card(push[1])
    push[0].claim_federation_mode('push')
    cli.main(['federation-listen', '--data-dir', str(push[0].data_dir), '--port', '0'])
    cli.main(['door', '--data-dir', str(tmp_path / 'door'), '--port', '7999'])
    cli.main(['serve', '--data-dir', str(tmp_path / 'lighthouse'), '--port', '0'])
    assert [options.get('timeout_graceful_shutdown') for options in ran] == [cli.SHUTDOWN_GRACE] * 3
    assert 0 < cli.SHUTDOWN_GRACE <= 5



# Crossing plan, Task 5: the crossing route on the listener, and the load (P6): two crossings in flight per origin,
# four in all, and sixty a minute per origin, so events and pulls are never starved.

import threading as _threading
import time as _time
import uuid as _uuid

from test_crossing_route import (INSTANCE, crossing_rows, frame_of, recall_result, request as crossing_request,
                                 world)  # noqa: F401 - `world` is the crossing route's fixture
from conftest import lesson_ship as _lesson_ship, paired as _paired


@pytest.fixture
def crossing_client(world):
    from superyak_peer.listener import create_listener
    return TestClient(create_listener(None, federation=world.a[2]), base_url='https://listener.example')


def test_a_crossing_is_served_over_https(world, crossing_client):
    answer = crossing_client.post('/federation/crossing', content=canonical(crossing_request(world)))
    assert answer.status_code == 200 and answer.json()['kind'] == 'crossing-answer'
    assert int(answer.headers['content-length']) == len(answer.content)  # the asking side refuses a 2xx without one
    from superyak_peer.listener import create_listener
    plain = TestClient(create_listener(None, federation=world.a[2]), base_url='http://listener.example')
    assert plain.post('/federation/crossing', content=b'{}').json() == {'error': 'Federation requires HTTPS'}


def test_a_crossing_refusal_answers_with_its_status_and_words(world, crossing_client):
    answer = crossing_client.post('/federation/crossing', content=b'{"not": "a crossing"}')
    assert (answer.status_code, answer.json()) == (400, {'error': 'Invalid crossing request'})


def another_origin(world, tmp_path, name):
    """A pull peer paired with `a`, with a ship that is a code-confirmed contact there: (identity, ship id)."""
    peer = station(tmp_path / name, name, world.clock, mode='pull')
    ship = _lesson_ship(peer[0], peer[1], name + '-ship')
    _paired(world.a[2], world.a[1], peer[2].card(ship['id']))
    return peer[2].identity, ship['id']


def in_flight(client, bodies):
    """Post each body on its own thread; returns the threads and a list their (status, json) answers land in."""
    answers, threads = [], []
    for body in bodies:
        thread = _threading.Thread(target=lambda b=body: answers.append(
            (lambda r: (r.status_code, r.json()))(client.post('/federation/crossing', content=canonical(b)))))
        thread.start()
        threads.append(thread)
    return threads, answers


def wait_for(condition, seconds=20):
    end = _time.monotonic() + seconds
    while not condition():
        assert _time.monotonic() < end, 'timed out'
        _time.sleep(0.01)


def unique_disclosures(world):
    world.daemon.answer = lambda frame: recall_result(frame, disclosure=_uuid.uuid4().hex)


def test_a_third_crossing_from_one_origin_gets_429_while_events_and_pulls_flow(world, crossing_client, tmp_path):
    from test_federation_pull import request as pull_request
    unique_disclosures(world)
    world.daemon.hold = _threading.Event()
    pat = station(tmp_path / 'pat', 'pat', world.clock)
    contact_there = _paired(pat[2], pat[1], world.a[2].card(world.a[1]))['id']
    _paired(world.a[2], world.a[1], pat[2].card(pat[1]))
    share(pat, contact_there, 'from pat')
    pat[2].collect()
    with pat[0].transaction() as db:
        key = db.execute('SELECT id FROM outbox').fetchone()[0]
    threads, answers = in_flight(crossing_client, [crossing_request(world), crossing_request(world)])
    try:
        wait_for(lambda: world.daemon.connections == 2)
        third = crossing_client.post('/federation/crossing', content=canonical(crossing_request(world)))
        assert (third.status_code, third.json()) == (429, {'error': 'Too many crossings'})
        # the load is checked after the signature: a bad one is still 403 while the origin is full
        forged = {**crossing_request(world), 'deadline_ms': 3000}
        assert crossing_client.post('/federation/crossing', content=canonical(forged)).status_code == 403
        push = crossing_client.post('/federation/events', content=pat[2]._prepared(key))
        assert (push.status_code, push.json()) == (200, {'ok': True, 'duplicate': False})
        mo = (world.m[0], world.m[1], world.m[2])
        pulled = crossing_client.post('/federation/pull', content=canonical(pull_request(mo, world.a, world.clock)))
        assert pulled.status_code == 200
    finally:
        world.daemon.hold.set()
        for thread in threads:
            thread.join(20)
    assert [status for status, _ in answers] == [200, 200]
    world.daemon.hold = None
    assert crossing_client.post('/federation/crossing', content=canonical(crossing_request(world))).status_code == 200


def test_a_fifth_crossing_in_flight_from_any_origin_gets_429(world, crossing_client, tmp_path):
    unique_disclosures(world)
    world.daemon.hold = _threading.Event()
    (n, n_ship), (o, o_ship) = another_origin(world, tmp_path, 'nina'), another_origin(world, tmp_path, 'olga')
    bodies = [crossing_request(world), crossing_request(world), crossing_request(world, signer=n, receiver_ship=n_ship),
              crossing_request(world, signer=n, receiver_ship=n_ship)]
    threads, answers = in_flight(crossing_client, bodies)
    try:
        wait_for(lambda: world.daemon.connections == 4)
        fifth = crossing_client.post('/federation/crossing',
                                     content=canonical(crossing_request(world, signer=o, receiver_ship=o_ship)))
        assert (fifth.status_code, fifth.json()) == (429, {'error': 'Too many crossings'})
    finally:
        world.daemon.hold.set()
        for thread in threads:
            thread.join(20)
    assert sorted(status for status, _ in answers) == [200] * 4


def test_the_61st_crossing_in_60_seconds_from_one_origin_gets_429(world):
    from superyak_peer.common import Problem
    from superyak_peer.crossing import Limiter
    now = [5000.0]
    world.a[2].crossing_limiter = Limiter(clock=lambda: now[0])
    unique_disclosures(world)
    for _ in range(60):
        world.a[2].serve_crossing(canonical(crossing_request(world)))
        now[0] += 0.5
    with pytest.raises(Problem) as refused:
        world.a[2].serve_crossing(canonical(crossing_request(world)))
    assert (refused.value.status, refused.value.message) == (429, 'Too many crossings')
    now[0] = 5000.0 + 60.0  # the first of the sixty is a minute old
    assert world.a[2].serve_crossing(canonical(crossing_request(world)))['kind'] == 'crossing-answer'


def test_the_main_app_never_serves_the_crossing_route(tmp_path, monkeypatch):
    """The crossing route is listener-only (spec 2.3: on federation-listen only). The main app (create_app) answers a
    POST to /federation/crossing with its own refusal, both as a public request (Funnel's header) and as a tailnet one,
    and the crossing handler never runs. If the route were ever mounted on the main app, this fails (coordinated with
    Rio Grande's public-route bound build)."""
    from fastapi.testclient import TestClient as AppClient
    from superyak_peer import crossing
    from superyak_peer.app import create_app
    monkeypatch.setattr(crossing, 'serve', lambda federation, raw: (_ for _ in ()).throw(
        AssertionError('the main app reached the crossing handler')))
    public_origin = 'https://home.example'
    app = create_app(tmp_path / 'peer', allowed_origins=['http://testserver', public_origin], public_origin=public_origin)
    body = b'{"version": 1, "kind": "crossing"}'
    tailnet = AppClient(app, base_url='http://testserver', client=('100.70.202.124', 50000))
    public = AppClient(app, base_url=public_origin, client=('100.70.202.124', 50000),
                       headers={'Tailscale-Funnel-Request': '?1'})
    for client in (tailnet, public):
        answer = client.post('/federation/crossing', content=body, headers={'content-type': 'application/json'})
        assert answer.status_code in (401, 404), (answer.status_code, answer.text)
        assert 'crossing-answer' not in answer.text
