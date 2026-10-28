"""Federation pull, plan Task 8: federation-listen's app, two routes and nothing else (P9, nits 11, 18 and 20)."""
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
                                          ('POST', '/api/sync')])
def test_only_its_two_routes_are_served(listening, method, path):
    client = listening[0]
    assert client.request(method, path, content=b'{}').status_code == 404


@pytest.mark.parametrize('path, cap', [('/federation/events', MAX_ENVELOPE), ('/federation/pull', 16 * 1024)])
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
