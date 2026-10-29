"""Run synthetic acceptance against two independent HTTPS peers over SSH forwards.

Ships don't run this checker: it's Andy's, or a test's. It pairs its two synthetic hosts by computing their codes,
which CLAUDE.md forbids a ship (a ship never computes a pairing code).

Requires a new local output directory and a new remote run directory, plus a
remote Python with this release's locked production dependencies. SSH host-key
checking remains enabled. See README.md for the generic configuration format.
"""
import argparse
import base64
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import shlex
import socket
import sqlite3
import ssl
import subprocess
import sys
import tarfile
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPSHandler


def pairing_code(card):
    """identity.pairing_code, standalone (this script imports nothing from the peer): the first 32 hex of the whole
    canonical card's SHA-256. tests/test_cli.py (test_the_two_peer_checker_s_code_is_the_peer_s) pins the two together.
    The person running this checker owns both
    synthetic hosts and holds both cards this run just made, so computing the code here is that person's own act on
    their own machines. A ship never runs this checker against a station (CLAUDE.md: a ship never computes a code)."""
    canonical = json.dumps(card, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(canonical).hexdigest()[:32]


class Client:
    def __init__(self, url, certificate):
        self.url, self.csrf = url, None
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()), HTTPSHandler(context=ssl.create_default_context(cadata=certificate)))

    def request(self, method, path, data=None, expected=200):
        headers = {'Origin': self.url, 'Content-Type': 'application/json'}
        if self.csrf:
            headers['X-CSRF-Token'] = self.csrf
        request = Request(self.url + path, None if data is None else json.dumps(data).encode(), headers, method=method)
        try:
            response = self.opener.open(request, timeout=8)
        except HTTPError as error:
            response = error
        with response:
            status, payload = response.status, json.loads(response.read())
        if status != expected:
            raise AssertionError(f'{method} {path}: expected {expected}, got {status}: {payload}')
        return payload

    def login(self, username, password):
        self.csrf = self.request('POST', '/api/login', {'username': username, 'password': password})['csrf_token']
        return self.request('GET', '/api/me')

    def ready(self):
        deadline = time.monotonic() + 15
        while True:
            try:
                # This endpoint is authenticated. Readiness must not require a login.
                self.request('GET', '/api/me', expected=401)
                return
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.1)


def extract(archive, output):
    with tarfile.open(archive) as source:
        members = source.getmembers()
        for member in members:
            parts = Path(member.name).parts
            if not member.isfile() or not parts or parts[0] != 'superyak-peer' or any(p in ('.', '..') or p.startswith('.') for p in parts):
                raise ValueError('Invalid source archive entry')
        names = [m.name for m in members]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate archive entry')
        output.mkdir(parents=True)
        for member in members:
            target = output / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(source.extractfile(member).read())
    root = output / 'superyak-peer'
    checksums = json.loads((root / 'CHECKSUMS.json').read_text())
    actual = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and p.name != 'CHECKSUMS.json'}
    if checksums != actual:
        raise ValueError('Source checksums differ')
    return root


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def run(args):
    os.umask(0o077)
    config = json.loads(args.config.read_text())
    ssh = config.get('ssh', ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6'])
    target, remote_python = config['target'], config['python']
    remote_root = config['root']
    if not remote_root.startswith('/') or not remote_python.startswith('/') or target.startswith('-'):
        raise ValueError('Use absolute remote paths and an explicit SSH target')
    ap, bp, rp, fp = config.get('ports', [17435, 17436, 17437, 17438])
    if len({ap, bp, rp, fp}) != 4 or any(type(p) is not int or not 1024 <= p <= 65535 for p in (ap, bp, rp, fp)):
        raise ValueError('Four distinct unprivileged ports are required')
    a_url, b_url, a_card_url = [f'https://127.0.0.1:{p}' for p in (ap, bp, fp)]
    output = args.output.resolve()
    output.mkdir(mode=0o700)  # Refuse output reuse, even an empty directory.
    result = {'started': time.time(), 'local_host': socket.gethostname(), 'checks': {}, 'configuration': config, 'archive_sha256': hashlib.sha256(args.archive.read_bytes()).hexdigest()}
    processes = []
    remote_attempted = False
    run_token = os.urandom(24).hex()
    def remote(code):
        reply = subprocess.run(ssh + [target, shlex.join([remote_python, '-'])], input=code, text=True, capture_output=True, timeout=45)
        if reply.returncode:
            raise RuntimeError('Remote operation failed: ' + reply.stderr[-1800:])
        return json.loads(reply.stdout)
    remote_prefix = f'''
import json,os,pathlib,signal,socket,sqlite3,subprocess,sys,time
os.umask(0o077)
root=pathlib.Path({remote_root!r})
source=root/'source/superyak-peer'
state=root/'state'
def start():
    with (root/'server.log').open('ab') as log:
        p=subprocess.Popen([sys.executable,'-m','superyak_peer','serve','--data-dir',str(state),'--port',{str(rp)!r},'--peer-tls','--origin',{f'https://127.0.0.1:{rp}'!r},'--origin',{b_url!r},'--federation-endpoint',{b_url!r},'--sync'],cwd=source,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    (root/'server.pid').write_text(str(p.pid))
    return p.pid
def stop():
    if not (root/'check-owner').is_file() or (root/'check-owner').read_text() != {run_token!r}:
        raise ValueError('Refusing cleanup of an unowned run directory')
    pidfile=root/'server.pid'
    if not pidfile.exists(): return True
    pid=int(pidfile.read_text())
    cmd=pathlib.Path('/proc')/str(pid)/'cmdline'
    if cmd.exists() and cmd.read_bytes():
        value=cmd.read_bytes().split(b'\\0')
        assert b'superyak_peer' in value and str(state).encode() in value, 'Refusing unrelated process'
        os.kill(pid,signal.SIGTERM)
    until=time.monotonic()+5
    while cmd.exists() and cmd.read_bytes() and time.monotonic()<until: time.sleep(.1)
    return not cmd.exists() or not cmd.read_bytes()
'''
    try:
        for port in (ap, bp):
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', port))
        source = extract(args.archive, output / 'source')
        sys.path.insert(0, str(source))
        from superyak_peer.db import Store
        from superyak_peer.federation import Federation
        from superyak_peer.identity import PeerIdentity
        from superyak_peer.transport import send_pinned
        from superyak_peer.common import Problem
        import secrets
        passwords = {k: secrets.token_urlsafe(24) for k in ('a', 'b')}
        (output / 'credentials.json').write_text(json.dumps(passwords))
        state = output / 'state'
        store = Store(state)
        user_a = store.create_user('host_a', 'Alex Example', passwords['a'], is_admin=True)
        identity = PeerIdentity.load_or_create(state)
        card_a = Federation(store, endpoint=a_card_url, identity=identity).card(user_a['id'])
        archive_data = base64.b64encode(args.archive.read_bytes()).decode()
        # Bootstrap only the new synthetic directory; never install or touch services.
        remote_attempted = True
        info = remote(remote_prefix + f'''
import base64,hashlib,importlib.util
root.mkdir(mode=0o700)
(root/'check-owner').write_text({run_token!r})
archive=root/'source.tar.gz'
archive.write_bytes(base64.b64decode({archive_data!r}))
assert hashlib.sha256(archive.read_bytes()).hexdigest()=={result['archive_sha256']!r}
# Extractor is the exact reviewed checker from the release being verified.
import tarfile
with tarfile.open(archive) as tf:
    checker=tf.extractfile('superyak-peer/scripts/two_peer_check.py').read()
namespace={{'__name__':'bootstrap'}}
exec(compile(checker,'two_peer_check.py','exec'),namespace)
namespace['extract'](archive,root/'source')
sys.path.insert(0,str(source))
for port in ({rp},{fp}):
    with socket.socket() as probe: probe.bind(('127.0.0.1',port))
from superyak_peer.db import Store
from superyak_peer.federation import Federation
from superyak_peer.identity import PeerIdentity
store=Store(state)
user=store.create_user('host_b','Sam Example',{passwords['b']!r},is_admin=True)
card=Federation(store,endpoint={b_url!r},identity=PeerIdentity.load_or_create(state)).card(user['id'])
(root/'card.json').write_text(json.dumps(card))
print(json.dumps({{'card':card,'host':socket.gethostname(),'python':sys.version.split()[0],'pid':start(),'archive_sha256':{result['archive_sha256']!r}}}))
''')
        card_b = info.pop('card')
        result['remote'] = info
        result['peers'] = {'a': card_a['peer_id'], 'b': card_b['peer_id']}
        for name, card in [('a', card_a), ('b', card_b)]:
            (output / f'{name}-card.json').write_text(json.dumps(card, indent=2))
        assert card_a['peer_id'] != card_b['peer_id']
        result['checks']['distinct_origins'] = True
        # Both serve with --sync: "Check delivery now" dials only from a sync worker (federation pull P11)
        command = [sys.executable, '-m', 'superyak_peer', 'serve', '--data-dir', str(state), '--port', str(ap), '--peer-tls', '--origin', a_url, '--origin', a_card_url, '--federation-endpoint', a_card_url, '--sync']
        def start_local():
            with (output / 'server.log').open('ab') as log:
                process = subprocess.Popen(command, cwd=source, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            processes.append(process)
            return process
        local = start_local()
        with (output / 'ssh.log').open('ab') as log:
            tunnel = subprocess.Popen(ssh + ['-N', '-o', 'ExitOnForwardFailure=yes', '-L', f'127.0.0.1:{bp}:127.0.0.1:{rp}', '-R', f'127.0.0.1:{fp}:127.0.0.1:{ap}', target], stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        processes.append(tunnel)
        a, b = Client(a_url, card_a['certificate']), Client(b_url, card_b['certificate'])
        a.ready(); b.ready()
        me_a, me_b = a.login('host_a', passwords['a']), b.login('host_b', passwords['b'])
        contact_b = a.request('POST', '/api/connections/pair', {'card': card_b, 'code': pairing_code(card_b)}, 201)
        b.request('POST', '/api/connections/pair', {'card': card_a, 'code': pairing_code(card_a)}, 201)
        layer = a.request('POST', '/api/layers', {'title': 'Fictional correction check', 'body': 'Fictional original event attribution.', 'audience_users': [contact_b['id']]}, 201)
        assert b.request('GET', '/api/shared/layers') == []
        result['checks']['draft_private_across_hosts'] = True
        layer_path = '/api/layers/' + layer['id']
        a.request('POST', layer_path + '/activate', {'version': layer['version']})
        a.request('POST', '/api/sync')
        received = b.request('GET', '/api/shared/layers')
        assert len(received) == 1 and received[0]['body'] == layer['body']
        remote_layer = '/api/shared/layers/' + quote(received[0]['id'], safe='')
        result['checks']['selected_share_crossed_hosts'] = True
        room = a.request('POST', '/api/chats', {'title': 'Fictional private chat', 'member_ids': [contact_b['id']]}, 201)
        room_path = '/api/chats/' + room['id']
        first = a.request('POST', room_path + '/messages', {'client_message_id': 'a-first', 'body': 'Hello from fixture A.'}, 201)
        a.request('POST', '/api/sync')
        remote_room = b.request('GET', '/api/chats')[0]
        remote_room_path = '/api/chats/' + quote(remote_room['id'], safe='')
        assert b.request('GET', remote_room_path)['messages'][0]['body'] == first['body']
        b.request('POST', remote_room_path + '/messages', {'client_message_id': 'b-first', 'body': 'Hello from fixture B.'}, 201)
        b.request('POST', '/api/sync'); a.request('POST', '/api/sync')
        for client, path in [(a, room_path), (b, remote_room_path)]:
            messages = client.request('GET', path)['messages']
            assert [m['body'] for m in messages].count('Hello from fixture B.') == 1
            assert len(messages) == 2
        result['checks']['bidirectional_chat_and_single_echo'] = True
        changed = a.request('PUT', layer_path, {'version': layer['version'], 'body': 'Fictional corrected event attribution.'})
        assert b.request('GET', remote_layer)['body'] == layer['body']
        assert changed['audience_users'] == layer['audience_users']
        a.request('PATCH', '/api/me', {'name': 'Alex Corrected'})
        assert a.request('GET', '/api/me')['id'] == me_a['id']
        assert a.request('GET', layer_path)['audience_users'] == layer['audience_users']
        result['checks']['private_replacement_and_name_correction_keep_grants'] = True
        a.request('POST', layer_path + '/activate', {'version': changed['version']})
        a.request('POST', '/api/sync')
        assert b.request('GET', remote_layer)['body'] == changed['body']
        result['checks']['correction_crossed_hosts'] = True
        # Independent signed sender is unpaired; altered paired envelope fails too.
        stranger = PeerIdentity.load_or_create(output / 'unpaired')
        envelope = stranger.envelope(destination=card_b['peer_id'], actor='stranger', resource_id='unshared', revision=1, action='layer.release', recipients=[me_b['id']], payload={})
        b.request('POST', '/federation/events', envelope, expected=403)
        with store.transaction() as db:
            original = json.loads(db.execute('SELECT envelope FROM outbox WHERE envelope IS NOT NULL LIMIT 1').fetchone()[0])
        tampered = {**original, 'signature': envelope['signature']}
        b.request('POST', '/federation/events', tampered, expected=403)
        wrong_card = stranger.card(b_url, {'id': 'stranger', 'name': 'Stranger'})
        try:
            send_pinned(wrong_card, lambda: json.dumps(original).encode())
        except (OSError, Problem):
            pass
        else:
            raise AssertionError('Wrong TLS identity was accepted')
        result['checks']['unpaired_signature_tamper_and_wrong_tls_denied'] = True
        # Take only the temporary receiver offline, persist a failed signed event,
        # restart both processes and retry the same event without editing its bytes.
        assert remote(remote_prefix + "\nprint(json.dumps({'stopped':stop()}))")['stopped']
        offline = a.request('POST', room_path + '/messages', {'client_message_id': 'offline', 'body': 'Retained while the other peer is offline.'}, 201)
        assert any(d['status'] == 'failed' for d in a.request('POST', '/api/sync')['deliveries'])
        queued = next(d for d in a.request('GET', '/api/sync')['deliveries'] if d.get('client_message_id') == 'offline')
        with store.transaction() as db:
            wire_before = db.execute('SELECT envelope FROM outbox WHERE id=?', (queued['id'],)).fetchone()[0]
        saved = a.request('PUT', layer_path, {'version': changed['version'], 'body': 'Private editing continued offline.'})
        stop(local)
        local = start_local()
        restarted = remote(remote_prefix + "\nprint(json.dumps({'pid':start()}))")
        result['remote']['restart_pid'] = restarted['pid']
        a, b = Client(a_url, card_a['certificate']), Client(b_url, card_b['certificate'])
        a.ready(); b.ready()
        assert a.login('host_a', passwords['a'])['peer_id'] == card_a['peer_id']
        assert b.login('host_b', passwords['b'])['peer_id'] == card_b['peer_id']
        assert a.request('GET', layer_path)['body'] == saved['body']
        assert any(d['id'] == queued['id'] for d in a.request('GET', '/api/sync')['deliveries'])
        # A's own worker may already have retried it once its backoff ran out. "Check delivery now" makes it due either
        # way and answers after that pass (P11), so a Retry, which a delivered row would refuse, isn't sent here.
        assert any(d['id'] == queued['id'] and d['status'] == 'delivered' for d in a.request('POST', '/api/sync')['deliveries'])
        with store.transaction() as db:
            wire_after = db.execute('SELECT envelope FROM outbox WHERE id=?', (queued['id'],)).fetchone()[0]
        assert wire_before is None, 'Offline TLS failure should precede signing'
        assert json.loads(wire_after)['event_id'] == queued['id']
        assert [m['body'] for m in b.request('GET', remote_room_path)['messages']].count(offline['body']) == 1
        assert send_pinned(card_b, lambda: wire_after.encode())['duplicate']
        # Deliver over real pinned HTTPS, then inject loss of the acknowledgement
        # before the sender can record success. Retry must preserve signed bytes.
        # A is stopped first: its own sync worker would otherwise deliver "lost-ack" before this checker's sync_once can
        # lose the acknowledgement. The message is queued through the store for the same reason.
        stop(local)
        store.send_message(me_a['id'], room['id'], 'lost-ack', 'One accepted message despite a lost acknowledgement.')
        federation = Federation(store, endpoint=a_card_url, identity=identity)
        def lose_ack(card, prepare):
            send_pinned(card, prepare, gate=store.dispatch_gate)
            raise OSError('Acceptance-check injected acknowledgement loss')
        assert federation.sync_once(send=lose_ack)['failed'] == 1
        lost = next(d for d in federation.status(me_a['id']) if d.get('client_message_id') == 'lost-ack')
        with store.transaction() as db:
            signed_before = db.execute('SELECT envelope FROM outbox WHERE id=?', (lost['id'],)).fetchone()[0]
        local = start_local()
        assert remote(remote_prefix + "\nprint(json.dumps({'stopped':stop()}))")['stopped']
        result['remote']['ack_restart_pid'] = remote(remote_prefix + "\nprint(json.dumps({'pid':start()}))")['pid']
        a, b = Client(a_url, card_a['certificate']), Client(b_url, card_b['certificate'])
        a.ready(); b.ready()
        a.login('host_a', passwords['a']); b.login('host_b', passwords['b'])
        # As above: A's worker may have resent it already; either way the receiver's answer is a duplicate receipt
        assert next(d for d in a.request('POST', '/api/sync')['deliveries'] if d['id'] == lost['id'])['status'] == 'delivered'
        with store.transaction() as db:
            signed_after = db.execute('SELECT envelope FROM outbox WHERE id=?', (lost['id'],)).fetchone()[0]
        assert signed_before == signed_after
        assert [m['client_message_id'] for m in b.request('GET', remote_room_path)['messages']].count('lost-ack') == 1
        result['signed_retry'] = {'event_id': lost['id'], 'envelope_sha256': hashlib.sha256(signed_after.encode()).hexdigest(), 'injected_ack_loss': True}
        result['recovery'] = {'event_id': queued['id'], 'envelope_sha256': hashlib.sha256(wire_after.encode()).hexdigest(), 'message_id': offline['id']}
        result['checks']['offline_editing_restart_same_signed_event_and_duplicate_receipt'] = True
        a.request('POST', layer_path + '/withdraw'); a.request('POST', '/api/sync')
        b.request('GET', remote_layer, expected=404)
        assert b.request('GET', '/api/shared/layers') == []
        result['checks']['withdrawal_removed_remote_read'] = True
        a.request('DELETE', room_path + '/participants/' + contact_b['id']); a.request('POST', '/api/sync')
        b.request('GET', remote_room_path, expected=404)
        b.request('POST', remote_room_path + '/messages', {'client_message_id': 'denied', 'body': 'Must not send.'}, expected=404)
        result['checks']['removed_member_denied_read_and_send'] = True
        result['deliveries'] = {'a': a.request('GET', '/api/sync'), 'b': b.request('GET', '/api/sync')}
        result['resource_ids'] = {'layer': layer['id'], 'room': room['id'], 'remote_layer': received[0]['id'], 'remote_room': remote_room['id']}
        result['ok'] = True
    except Exception as error:
        import traceback
        result['ok'], result['error'] = False, f'{type(error).__name__}: {error}'
        result['traceback'] = traceback.format_exc()
    finally:
        for process in reversed(processes):
            stop(process)
        result['local_cleanup'] = {'stopped': all(p.poll() is not None for p in processes), 'pids': [p.pid for p in processes]}
        if remote_attempted:
            try:
                cleanup = remote(remote_prefix + '''
stopped=stop()
receipts=[]
if (state/'peer.sqlite3').is_file():
    db=sqlite3.connect('file:'+str(state/'peer.sqlite3')+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    receipts=[dict(r) for r in db.execute('SELECT origin,event_id,digest,created FROM receipts')]
    db.close()
print(json.dumps({'stopped':stopped,'receipts':receipts}))
''')
                result['remote_cleanup'] = cleanup
                if not cleanup['stopped']:
                    result['ok'] = False
            except Exception as error:
                result['cleanup_error'], result['ok'] = str(error), False
        if (output / 'state/peer.sqlite3').exists():
            with sqlite3.connect(f'file:{output}/state/peer.sqlite3?mode=ro', uri=True) as db:
                db.row_factory = sqlite3.Row
                result['local_receipts'] = [dict(r) for r in db.execute('SELECT origin,event_id,digest,created FROM receipts')]
        result['finished'] = time.time()
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'ok': result.get('ok'), 'checks': result['checks'], 'error': result.get('error'), 'cleanup_error': result.get('cleanup_error'), 'result_file': str(output / 'result.json')}))
    return 0 if result.get('ok') else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        return run(args)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
