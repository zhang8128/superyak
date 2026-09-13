"""Real TCP/TLS tests: generated independent certificates, no verification bypass."""
from contextlib import contextmanager
import socket
import threading
import time
import pytest
import uvicorn
from superyak_peer.common import Problem

@contextmanager
def server(path):
    from superyak_peer.identity import PeerIdentity
    from superyak_peer.app import create_app
    ident = PeerIdentity.load_or_create(path)
    sock = socket.socket()
    sock.bind(('127.0.0.1',0))
    endpoint = 'https://127.0.0.1:'+str(sock.getsockname()[1])
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
        ca=a.pair(alice,bc)
        b.pair(bob,a.card(alice))
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
        with pytest.raises((OSError,Problem)):
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
    contact=a.pair(alice,b.card(bob))
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
        ca=a.pair(alice,b.card(bob))
        b.pair(bob,a.card(alice))
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
    ca=a.pair(alice,b.card(bob))
    b.pair(bob,a.card(alice))
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
        with pytest.raises((OSError,Problem)):
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
        with pytest.raises(Problem,match='fingerprint differs'):
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
