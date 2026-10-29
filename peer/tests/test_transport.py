"""Real TCP/TLS tests: generated independent certificates, no verification bypass."""
from superyak_peer.identity import pairing_code
from contextlib import contextmanager
import socket
import threading
import time
import pytest
import uvicorn
from superyak_peer.common import Problem

@contextmanager
def server(path, host='127.0.0.1'):
    from superyak_peer.identity import PeerIdentity
    from superyak_peer.app import create_app
    ident = PeerIdentity.load_or_create(path)
    sock = socket.socket()
    sock.bind(('127.0.0.1',0))
    endpoint = f'https://{host}:'+str(sock.getsockname()[1])
    app = create_app(path, allowed_origins=[endpoint], federation_endpoint=endpoint)
    config = uvicorn.Config(app, log_level='error', ssl_certfile=str(ident.cert_path), ssl_keyfile=str(ident.key_path), proxy_headers=False)
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=lambda:srv.run(sockets=[sock]), daemon=True)
    thread.start()
    until = time.monotonic()+5
    while not srv.started and thread.is_alive() and time.monotonic()<until:
        time.sleep(.01)
    assert srv.started
    try:
        yield app
    finally:
        srv.should_exit=True
        thread.join(5)
        sock.close()
        assert not thread.is_alive()


def test_real_https_delivery_restart_and_pin_mismatch(tmp_path):
    from superyak_peer.identity import PeerIdentity
    from superyak_peer.transport import send_pinned
    from superyak_peer.federation import Federation
    from superyak_peer.db import Store
    a = Federation(Store(tmp_path/'a'),endpoint='https://localhost:7435')
    alice = a.store.create_user('alice','Alice','long-password',is_admin=True)['id']
    with server(tmp_path/'b') as app:
        b=app.state.federation
        bob=b.store.create_user('bob','Bob','long-password',is_admin=True)['id']
        bc=b.card(bob)
        ca=a.pair(alice,bc, code=pairing_code(bc))
        b.pair(bob,a.card(alice), code=pairing_code(a.card(alice)))
        layer=a.store.create_layer(alice,{'body':'over verified TLS','audience_users':[ca['id']]})
        a.store.activate_layer(alice,layer['id'],1)
        assert a.sync_once()['delivered']==1
        assert b.store.shared_layers(bob)[0]['body']=='over verified TLS'
        restarted=Federation(Store(tmp_path/'a'),endpoint=a.endpoint)
        assert restarted.sync_once()['delivered']==0
        with a.store.transaction() as db:
            original=db.execute('SELECT envelope FROM outbox').fetchone()[0].encode()
        assert send_pinned(bc,lambda:original)['duplicate']
        wrong=PeerIdentity.load_or_create(tmp_path/'wrong').card(bc['endpoint'],{'id':'bob','name':'Bob'})
        from superyak_peer.transport import PinMismatch
        with pytest.raises(PinMismatch):
            send_pinned(wrong,lambda:original)
        # Receipts and private content survive receiver restart as well.
        reloaded=Federation(Store(tmp_path/'b'),endpoint=bc['endpoint'])
        assert reloaded.receive(original)['duplicate']
        a.store.withdraw_layer(alice,layer['id'])
        assert a.sync_once()['delivered']==1
        assert not b.store.shared_layers(bob)


def test_offline_queue_stable_and_bounded(tmp_path):
    from superyak_peer.federation import Federation
    from superyak_peer.db import Store
    a=Federation(Store(tmp_path/'a'),endpoint='https://localhost:7435')
    b=Federation(Store(tmp_path/'b'),endpoint='https://127.0.0.1:1')
    alice=a.store.create_user('alice','Alice','long-password',is_admin=True)['id']
    bob=b.store.create_user('bob','Bob','long-password',is_admin=True)['id']
    contact=a.pair(alice,b.card(bob), code=pairing_code(b.card(bob)))
    l=a.store.create_layer(alice,{'body':'offline','audience_users':[contact['id']]})
    a.store.activate_layer(alice,l['id'],1)
    start=time.monotonic()
    assert a.sync_once()['failed']==1
    assert time.monotonic()-start<4
    first=a.status(alice)[0]
    a=Federation(Store(tmp_path/'a'),endpoint=a.endpoint)
    assert a.status(alice)[0]['id']==first['id']
    assert a.sync_once()['failed']==0 # Backoff survives restart.
    a.store.save_layer(alice,l['id'],{'version':1,'body':'still editing offline'})


def test_connection_api_requires_owner_and_signed_route(env):
    app,clients,users,_=env
    assert clients[0].get('/api/connections').status_code==403
    assert clients[2].get('/api/connections').status_code==200
    assert clients[2].post('/federation/events',json={}).status_code==403


def test_two_live_https_peers_exchange_rooms_and_final_dispatch_rechecks(tmp_path):
    from superyak_peer.transport import send_pinned
    with server(tmp_path/'a') as aa, server(tmp_path/'b') as bb:
        a,b=aa.state.federation,bb.state.federation
        alice=a.store.create_user('alice','Alice','long-password',is_admin=True)['id']
        bob=b.store.create_user('bob','Bob','long-password',is_admin=True)['id']
        ca=a.pair(alice,b.card(bob), code=pairing_code(b.card(bob)))
        b.pair(bob,a.card(alice), code=pairing_code(a.card(alice)))
        room=a.store.create_room(alice,'TLS chat',[ca['id']])
        a.store.send_message(alice,room['id'],'first','hello')
        assert a.sync_once()['delivered']==2
        remote=b.store.list_rooms(bob)[0]['id']
        b.store.send_message(bob,remote,'response','reply over TLS')
        assert b.sync_once()['delivered']==1
        assert a.store.get_room(alice,room['id'])['messages'][-1]['body']=='reply over TLS'
        assert a.sync_once()['delivered']==1
        assert len(b.store.get_room(bob,remote)['messages'])==2
        layer=a.store.create_layer(alice,{'body':'withdraw during handshake','audience_users':[ca['id']]})
        a.store.activate_layer(alice,layer['id'],1)
        def send_after_change(card,prepare):
            def final():
                a.store.withdraw_layer(alice,layer['id'])
                return prepare()
            return send_pinned(card, final, gate=a.store.dispatch_gate)
        result=a.sync_once(send=send_after_change)
        assert result['withdrawn']==1
        assert not b.store.shared_layers(bob)
        assert a.sync_once()['delivered']==1


def test_exhausted_retry_keeps_event_id_and_rechecks_current_state(tmp_path):
    from superyak_peer.federation import Federation
    from superyak_peer.db import Store
    a=Federation(Store(tmp_path/'a'),endpoint='https://localhost:7435')
    b=Federation(Store(tmp_path/'b'),endpoint='https://localhost:7436')
    alice=a.store.create_user('alice','Alice','long-password',is_admin=True)['id']
    bob=b.store.create_user('bob','Bob','long-password',is_admin=True)['id']
    ca=a.pair(alice,b.card(bob), code=pairing_code(b.card(bob)))
    b.pair(bob,a.card(alice), code=pairing_code(a.card(alice)))
    layer=a.store.create_layer(alice,{'body':'one','audience_users':[ca['id']]})
    a.store.activate_layer(alice,layer['id'],1)
    a.collect()
    key=a.status(alice)[0]['id']
    with a.store.transaction() as db:
        db.execute("UPDATE outbox SET status='failed',attempts=8")
    assert a.sync_once()['delivered']==0
    a.retry(alice,key)
    assert a.status(alice)[0]['id']==key
    assert a.sync_once(send=lambda card,prepare:b.receive(prepare()))['delivered']==1


def test_trickling_response_has_total_deadline(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import ssl
    from superyak_peer.identity import PeerIdentity
    from superyak_peer.transport import send_pinned
    identity=PeerIdentity.load_or_create(tmp_path/'slow')
    class Slow(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Length','100')
            self.end_headers()
            try:
                for _ in range(100):
                    self.wfile.write(b' ')
                    self.wfile.flush()
                    time.sleep(.05)
            except OSError:
                pass
        def log_message(self,*args):
            pass
    srv=ThreadingHTTPServer(('127.0.0.1',0),Slow)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(identity.cert_path,identity.key_path)
    srv.socket=context.wrap_socket(srv.socket,server_side=True)
    thread=threading.Thread(target=srv.serve_forever,daemon=True)
    thread.start()
    card=identity.card('https://127.0.0.1:'+str(srv.server_port),{'id':'slow','name':'Slow'})
    started=time.monotonic()
    try:
        with pytest.raises(OSError):  # the deadline cut the reply: a network failure, never a 2xx PeerAnswer (plan SF3)
            send_pinned(card,lambda:b'{}',timeout=.2)
        assert time.monotonic()-started<.8
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(2)


def test_exact_pin_rejects_different_leaf_signed_by_trusted_certificate(tmp_path):
    from datetime import datetime,timedelta,timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    import ipaddress
    import ssl
    from superyak_peer.identity import PeerIdentity
    from superyak_peer.transport import send_pinned
    root=PeerIdentity.load_or_create(tmp_path/'root')
    root_cert=x509.load_pem_x509_certificate(root.certificate.encode())
    root_key=serialization.load_pem_private_key(root.key_path.read_bytes(),password=None)
    leaf_key=ec.generate_private_key(ec.SECP256R1())
    now=datetime.now(timezone.utc)
    leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Other leaf')]))
          .issuer_name(root_cert.subject).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
          .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
          .sign(root_key,hashes.SHA256()))
    cert_path,key_path=tmp_path/'leaf.pem',tmp_path/'leaf-key.pem'
    cert_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    sock=socket.socket()
    sock.bind(('127.0.0.1',0))
    sock.listen(2)
    port=sock.getsockname()[1]
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path,key_path)
    def accept_twice():
        for _ in range(2):
            connection,_=sock.accept()
            with context.wrap_socket(connection,server_side=True) as tls:
                try:
                    tls.recv(1)
                except OSError:
                    pass
    thread=threading.Thread(target=accept_twice,daemon=True)
    thread.start()
    try:
        trusted=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        trusted.load_verify_locations(cadata=root.certificate)
        with socket.create_connection(('127.0.0.1',port),timeout=1) as raw:
            with trusted.wrap_socket(raw,server_hostname='127.0.0.1') as tls:
                assert tls.getpeercert() # Standard chain/hostname verification succeeds.
        card=root.card('https://127.0.0.1:'+str(port),{'id':'root','name':'Root'})
        from superyak_peer.transport import PinMismatch
        with pytest.raises(PinMismatch):
            send_pinned(card,lambda:b'{}')
    finally:
        sock.close()
        thread.join(2)
    assert not thread.is_alive()


def test_authenticated_me_exposes_own_peer_id_without_endpoint(env):
    from fastapi.testclient import TestClient
    app,clients,users,_=env
    assert app.state.federation.endpoint is None
    response=clients[0].get('/api/me')
    assert response.status_code==200
    assert response.json()['peer_id']==app.state.federation.identity.peer_id
    assert clients[0].get('/api/connections/card').status_code==409
    with TestClient(app,base_url='http://testserver') as signed_out:
        assert signed_out.get('/api/me').status_code==401


# Federation pull, plan Task 3: the pin-only dial (spec §3), one pinned dial for push and pull (review MF1), and the
# pull transport's caps and minimum rate (spec §5)

def identity_with_dates(path, not_before, not_after):
    """An identity.json whose certificate is valid only between the two times, written before anything loads it."""
    import ipaddress
    import json
    import os
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519
    from cryptography.x509.oid import NameOID
    path.mkdir(mode=0o700)
    key, tls = ed25519.Ed25519PrivateKey.generate(), ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Superyak peer')])
    sans = [x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(tls.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(not_before).not_valid_after(not_after)
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).sign(tls, hashes.SHA256()))
    pem = lambda k: k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
    record = {'signing_private': pem(key), 'tls_private': pem(tls),
              'certificate': cert.public_bytes(serialization.Encoding.PEM).decode()}
    with os.fdopen(os.open(path / 'identity.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        stream.write(json.dumps(record))


def share_with(tmp_path, b, body):
    """A pushing peer `a` paired both ways with the served peer `b`, and a layer shared with b's admin."""
    from superyak_peer.db import Store
    from superyak_peer.federation import Federation
    a = Federation(Store(tmp_path / 'a'), endpoint='https://localhost:7435')
    alice = a.store.create_user('alice', 'Alice', 'long-password', is_admin=True)['id']
    bob = b.store.create_user('bob', 'Bob', 'long-password', is_admin=True)['id']
    contact = a.pair(alice, b.card(bob), code=pairing_code(b.card(bob)))
    b.pair(bob, a.card(alice), code=pairing_code(a.card(alice)))
    layer = a.store.create_layer(alice, {'body': body, 'audience_users': [contact['id']]})
    a.store.activate_layer(alice, layer['id'], 1)
    return a, bob


def test_a_dial_by_tailnet_name_works_against_a_certificate_naming_only_localhost(tmp_path, monkeypatch):
    from superyak_peer import transport
    name = 'tardis.example-tailnet.ts.net'
    with server(tmp_path / 'b', host=name) as app:
        b = app.state.federation
        port = int(b.endpoint.rsplit(':', 1)[1])
        dialled = []
        def resolve(host, wanted, timeout):
            dialled.append((host, wanted))
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))]
        monkeypatch.setattr(transport, 'resolve', resolve)
        a, bob = share_with(tmp_path, b, 'by tailnet name')
        assert a.sync_once()['delivered'] == 1
        assert dialled == [(name, port)]
        assert b.store.shared_layers(bob)[0]['body'] == 'by tailnet name'


@pytest.mark.parametrize('dates', ['expired', 'not yet valid'])
def test_a_pinned_certificate_outside_its_dates_still_dials(tmp_path, dates):
    """Spec §3: the exact pin alone; checking dates would end every link a year after its identity was made."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    window = ((now - timedelta(days=400), now - timedelta(days=35)) if dates == 'expired'
              else (now + timedelta(days=1), now + timedelta(days=400)))
    identity_with_dates(tmp_path / 'b', *window)
    with server(tmp_path / 'b') as app:
        a, bob = share_with(tmp_path, app.state.federation, dates)
        assert a.sync_once()['delivered'] == 1
        assert app.state.federation.store.shared_layers(bob)[0]['body'] == dates


def other_leaf_server(tmp_path):
    """A TLS server whose certificate is a different leaf signed by the pinned certificate's key. It takes one
    connection and records every application byte it receives on it."""
    from datetime import datetime, timedelta, timezone
    import ipaddress
    import ssl
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    from superyak_peer.identity import PeerIdentity
    root = PeerIdentity.load_or_create(tmp_path / 'root')
    root_cert = x509.load_pem_x509_certificate(root.certificate.encode())
    root_key = serialization.load_pem_private_key(root.key_path.read_bytes(), password=None)
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    leaf = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Other leaf')]))
            .issuer_name(root_cert.subject).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(root_key, hashes.SHA256()))
    (tmp_path / 'leaf.pem').write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    (tmp_path / 'leaf-key.pem').write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                                   serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / 'leaf.pem', tmp_path / 'leaf-key.pem')
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(1)
    received = []
    def take_one():
        connection, _ = sock.accept()
        connection.settimeout(5)
        with context.wrap_socket(connection, server_side=True) as tls:
            while True:
                try:
                    chunk = tls.recv(65536)
                except OSError:
                    break
                if not chunk:
                    break
                received.append(chunk)
    thread = threading.Thread(target=take_one, daemon=True)
    thread.start()
    def stop():
        thread.join(5)
        sock.close()
        assert not thread.is_alive()
    return root, sock.getsockname()[1], received, stop


@pytest.mark.parametrize('dial', ['send_pinned', 'pull_pinned'])
def test_no_byte_is_written_before_the_pin_is_compared(tmp_path, dial):
    """Review MF1: a pull request is authorised only by its signature, so one written to the wrong server could be
    replayed for the pull peer's envelopes. Push and pull share one pinned dial, and neither writes a byte first."""
    from superyak_peer import transport
    root, port, received, stop = other_leaf_server(tmp_path)
    card = root.card(f'https://127.0.0.1:{port}', {'id': 'root', 'name': 'Root'})
    try:
        with pytest.raises(transport.PinMismatch):
            if dial == 'send_pinned':
                transport.send_pinned(card, lambda: b'{"signed":"secret"}')
            else:
                transport.pull_pinned(card, b'{"signed":"secret"}')
    finally:
        stop()
    assert received == []


def pull_server(tmp_path, respond):
    """A TLS server with a peer identity's certificate, whose POST handler reads the request and calls respond(handler).
    It speaks HTTP/1.0, so a reply without Content-Length ends when the connection closes."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import ssl
    from superyak_peer.identity import PeerIdentity
    identity = PeerIdentity.load_or_create(tmp_path / 'listener')
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            try:
                respond(self)
            except OSError:
                pass
        def log_message(self, *args):
            pass
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(identity.cert_path, identity.key_path)
    srv.socket = context.wrap_socket(srv.socket, server_side=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    def stop():
        srv.shutdown()
        srv.server_close()
        thread.join(2)
    return identity.card(f'https://127.0.0.1:{srv.server_port}', {'id': 'listener', 'name': 'Listener'}), stop


def pull_body(size=3000):
    from superyak_peer.identity import canonical
    return canonical({'ok': True, 'envelopes': ['x' * size], 'more': False})


def test_a_pull_response_faster_than_the_minimum_rate_arrives(tmp_path):
    from superyak_peer.transport import pull_pinned
    body = pull_body()
    def respond(handler):
        handler.send_response(200)
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        for at in range(0, len(body), 1000):
            handler.wfile.write(body[at:at + 1000])
            handler.wfile.flush()
            time.sleep(.05)
    card, stop = pull_server(tmp_path, respond)
    try:
        assert pull_pinned(card, b'{}', rate=4096) == {'ok': True, 'envelopes': ['x' * 3000], 'more': False}
    finally:
        stop()


def test_a_stalled_pull_response_ends_by_the_scaled_deadline(tmp_path):
    """Spec §5: headers within the header deadline, then Content-Length / rate for the body. At 2,000 B/s a 3 KB body
    gets about 1.5 s; one that stops after 100 bytes ends then, as a network failure (plan SF3)."""
    from superyak_peer.transport import pull_pinned
    body = pull_body()
    def respond(handler):
        handler.send_response(200)
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        handler.wfile.write(body[:100])
        handler.wfile.flush()
        time.sleep(4)
    card, stop = pull_server(tmp_path, respond)
    started = time.monotonic()
    try:
        with pytest.raises(OSError):  # TimeoutError, or the shut-down socket's own error: a network failure either way
            pull_pinned(card, b'{}', rate=2000)
        assert 1.2 < time.monotonic() - started < 3
    finally:
        stop()


def test_a_pull_response_over_the_cap_or_without_a_length_is_refused(tmp_path):
    from superyak_peer.transport import PULL_CAP, PeerAnswer, pull_pinned
    def over(handler):
        handler.send_response(200)
        handler.send_header('Content-Length', str(PULL_CAP + 1))
        handler.end_headers()
        time.sleep(3)
    def unmeasured(handler):
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(pull_body())
    for respond in (over, unmeasured):
        card, stop = pull_server(tmp_path / respond.__name__, respond)
        started = time.monotonic()
        try:
            with pytest.raises(PeerAnswer) as refused:
                pull_pinned(card, b'{}')
            assert refused.value.status == 200 and time.monotonic() - started < 2  # refused unread
        finally:
            stop()


@pytest.mark.parametrize('dial', ['send_pinned', 'pull_pinned'])
def test_a_peer_answer_carries_its_real_status_and_message(tmp_path, dial):
    """Spec §7: the real status and message are what tell a peer-scoped answer from a row-scoped one."""
    import json
    from superyak_peer import transport
    answers = iter([(409, {'error': 'Revision already used'}), (200, {'x': 1})])
    def respond(handler):
        status, value = next(answers)
        raw = json.dumps(value).encode()
        handler.send_response(status)
        handler.send_header('Content-Length', str(len(raw)))
        handler.end_headers()
        handler.wfile.write(raw)
    card, stop = pull_server(tmp_path, respond)
    call = (lambda: transport.send_pinned(card, lambda: b'{}')) if dial == 'send_pinned' else (lambda: transport.pull_pinned(card, b'{}'))
    try:
        with pytest.raises(transport.PeerAnswer) as answered:
            call()
        assert (answered.value.status, answered.value.message) == (409, 'Revision already used')
        with pytest.raises(transport.PeerAnswer) as answered:
            call()
        assert answered.value.status == 200  # a 2xx that isn't an acknowledgement is still a PeerAnswer, peer-scoped
    finally:
        stop()


def test_a_card_that_cant_be_dialled_is_refused_before_anything_resolves(tmp_path, monkeypatch):
    """Plan SF7: send_pinned's own refusals are ValueError, raised before any socket opens."""
    from superyak_peer import transport
    from superyak_peer.identity import PeerIdentity
    def resolve(*args):
        raise AssertionError('resolved')
    monkeypatch.setattr(transport, 'resolve', resolve)
    identity = PeerIdentity.load_or_create(tmp_path / 'mac')
    pull = identity.card(None, {'id': 'mac', 'name': 'Mac'}, delivery='pull')
    tampered = {**identity.card('https://localhost:7435', {'id': 'mac', 'name': 'Mac'}), 'peer_id': '0' * 64}
    for card in (pull, tampered):
        with pytest.raises(ValueError):
            transport.send_pinned(card, lambda: b'{}')
        with pytest.raises(ValueError):
            transport.pull_pinned(card, b'{}')


def test_a_handshake_with_no_certificate_is_a_pin_mismatch(tmp_path, monkeypatch):
    """Serenity's read of 13766378: a peer that shows no certificate is "certificate differs", a peer failure with its
    reason, never a TypeError from hashing nothing."""
    import ssl
    from superyak_peer import transport
    card, stop = pull_server(tmp_path, lambda handler: None)
    monkeypatch.setattr(ssl.SSLSocket, 'getpeercert', lambda self, binary_form=False: None)
    try:
        with pytest.raises(transport.PinMismatch):
            transport.pull_pinned(card, b'{}')
    finally:
        stop()
