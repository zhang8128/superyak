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
    cli.main(['serve', '--data-dir', str(tmp_path / 'lighthouse')])
    assert [options.get('timeout_graceful_shutdown') for options in ran] == [cli.SHUTDOWN_GRACE] * 3
    assert 0 < cli.SHUTDOWN_GRACE <= 5

