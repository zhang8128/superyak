"""fix:docked-ships-over-tailnet: a ship reaches a *.ts.net station at the tailnet address MagicDNS gives, while TLS, SNI
and the Host header stay on the station's name. A Mac's resolver can answer Funnel's public pair for that name, and
every call then went out to the internet and back in (health 299 ms against 36 ms on the tailnet, 2026-10-29)."""
import http.server
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import pytest
from superyak_agent import station
from superyak_agent.station import magicdns_address, tailnet_pin, urllib_transport

NAME = 'station.tail0000.ts.net'


def certificate(tmp_path, name):
    """A self-signed certificate for `name`, made with the openssl CLI: (cert path, key path)."""
    if not shutil.which('openssl'):
        pytest.skip('needs the openssl command')
    cert, key = tmp_path / f'{name}.pem', tmp_path / f'{name}.key'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes',
                    '-days', '1', '-subj', f'/CN={name}', '-addext', f'subjectAltName=DNS:{name}',
                    '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
    return cert, key


class Station:
    """An HTTPS server on 127.0.0.1 that records each request's SNI name and Host header."""

    def __init__(self, cert, key):
        self.seen = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        sni = []
        context.sni_callback = lambda sock, server_name, ctx: sni.append(server_name)
        seen = self.seen

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((sni[-1] if sni else None, self.headers.get('Host'), self.path))
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        self.server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def trusted(tmp_path, monkeypatch):
    """A station whose certificate names NAME, trusted the way an operator adds a root (SSL_CERT_FILE)."""
    cert, key = certificate(tmp_path, NAME)
    monkeypatch.setenv('SSL_CERT_FILE', str(cert))
    served = Station(cert, key)
    yield served
    served.close()


def test_a_ts_net_station_is_reached_at_its_pinned_address_with_tls_on_the_name(trusted):
    """The connection goes to the pinned address; the certificate is checked against the name, and SNI and Host are the
    name's, so the station can't tell the path apart."""
    send = urllib_transport(timeout=5, pin=lambda host: '127.0.0.1' if host == NAME else None)
    assert send('GET', f'https://{NAME}:{trusted.port}/api/health', {}, None) == (200, b'{"ok": true}')
    assert trusted.seen == [(NAME, f'{NAME}:{trusted.port}', '/api/health')]


def test_a_pinned_address_still_needs_the_names_certificate(tmp_path, monkeypatch):
    """A wrong address can't stand in for the station: a server whose certificate names something else is refused, as it
    is without a pin. Mutation: verifying against the address, or not at all."""
    cert, key = certificate(tmp_path, 'other.example')
    monkeypatch.setenv('SSL_CERT_FILE', str(cert))
    served = Station(cert, key)
    try:
        send = urllib_transport(timeout=5, pin=lambda host: '127.0.0.1')
        with pytest.raises(OSError) as refused:  # urllib's URLError wraps the certificate error
            send('GET', f'https://{NAME}:{served.port}/api/health', {}, None)
        assert 'CERTIFICATE_VERIFY_FAILED' in str(refused.value) or 'certificate' in str(refused.value).lower()
        assert served.seen == []
    finally:
        served.close()


def test_a_pinned_request_goes_direct_whatever_proxy_the_environment_names(trusted, monkeypatch):
    """A pinned station is reached over the tailnet itself, so an HTTPS proxy in the environment (here a dead one) is
    never in its way."""
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:9')
    send = urllib_transport(timeout=5, pin=lambda host: '127.0.0.1')
    assert send('GET', f'https://{NAME}:{trusted.port}/api/me', {}, None)[0] == 200


def test_without_a_pin_the_transport_resolves_as_before(trusted):
    """No pin, no change: the name is resolved by the system, which here can't find it."""
    send = urllib_transport(timeout=5, pin=lambda host: None)
    with pytest.raises(OSError):
        send('GET', f'https://{NAME}:{trusted.port}/api/health', {}, None)
    assert trusted.seen == []


def test_the_default_pin_is_tailnet_pin():
    assert station.urllib_transport.__kwdefaults__['pin'] is tailnet_pin


def test_tailnet_pin_asks_only_for_ts_net_names_and_keeps_each_answer_a_minute():
    asked, clock = [], [1000.0]

    def ask(host):
        asked.append(host)
        return '100.70.202.124' if host == NAME else None
    pins = {}
    pin = lambda host: tailnet_pin(host, ask=ask, now=lambda: clock[0], pins=pins)  # noqa: E731
    assert pin('example.com') is None and pin(None) is None and pin('127.0.0.1') is None and asked == []
    assert pin(NAME) == '100.70.202.124' and pin(NAME) == '100.70.202.124' and asked == [NAME]
    assert pin('gone.tail0000.ts.net') is None and pin('gone.tail0000.ts.net') is None  # a miss is kept too
    assert asked == [NAME, 'gone.tail0000.ts.net']
    clock[0] += 61
    assert pin(NAME) == '100.70.202.124' and asked == [NAME, 'gone.tail0000.ts.net', NAME]


def dns_answer(query, *, rcode=0, records=(), same_id=True, pointer=True, flags=0x8180, question=None):
    """A DNS response to `query` (RFC 1035): its id (or another), QR and RD set, the question echoed (or another), then
    A records."""
    ident = struct.unpack('>H', query[:2])[0] ^ (0 if same_id else 1)
    question = question or query[12:]
    out = struct.pack('>HHHHHH', ident, flags | rcode, 1, len(records), 0, 0) + question
    for kind, address in records:
        name = b'\xc0\x0c' if pointer else question[:-4]
        rdata = socket.inet_aton(address)
        out += name + struct.pack('>HHIH', kind, 1, 5, len(rdata)) + rdata
    return out


class FakeDns:
    """A UDP DNS server on 127.0.0.1 that answers each query with `respond(query)`, or not at all for None."""

    def __init__(self, respond):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', 0))
        self.queries = []

        def serve():
            while True:
                try:
                    query, peer = self.sock.recvfrom(512)
                except OSError:
                    return
                self.queries.append(query)
                answer = respond(query)
                if answer is not None:
                    self.sock.sendto(answer, peer)
        threading.Thread(target=serve, daemon=True).start()

    @property
    def address(self):
        return self.sock.getsockname()

    def close(self):
        self.sock.close()


@pytest.mark.parametrize('respond, expected', [
    (lambda q: dns_answer(q, records=[(1, '100.70.202.124')]), '100.70.202.124'),
    (lambda q: dns_answer(q, records=[(1, '100.70.202.124')], pointer=False), '100.70.202.124'),
    (lambda q: dns_answer(q, records=[(5, '1.2.3.4'), (1, '100.64.0.1')]), '100.64.0.1'),  # another type first
    (lambda q: dns_answer(q, records=[(1, '208.111.35.209')]), None),   # Funnel's public address
    (lambda q: dns_answer(q, records=[(1, '100.128.0.1')]), None),      # just past 100.64.0.0/10
    (lambda q: dns_answer(q, records=[]), None),
    (lambda q: dns_answer(q, rcode=3, records=[(1, '100.70.202.124')]), None),  # an error code, whatever follows
    (lambda q: dns_answer(q, flags=0x0100, records=[(1, '100.70.202.124')]), None),  # not a response (no QR)
    (lambda q: dns_answer(q, records=[(1, '100.70.202.124')],
                          question=b'\x07statiox\x08tail0000\x02ts\x03net\x00' + struct.pack('>HH', 1, 1)), None),  # same length
    (lambda q: dns_answer(q, records=[(1, '100.70.202.124')], same_id=False), None),
    (lambda q: dns_answer(q, records=[(1, '100.70.202.124')])[:-3], None),  # cut short
    (lambda q: b'\x00' * 5, None),
    (lambda q: None, None),                                             # no answer within the timeout
], ids=['tailnet', 'tailnet-no-pointer', 'cname-first', 'public', 'past-the-range', 'empty', 'error-code',
        'not-a-response', 'other-question', 'other-id',
        'cut-short', 'garbage', 'silent'])
def test_magicdns_address_takes_only_a_tailnet_answer_to_its_own_question(respond, expected):
    served = FakeDns(respond)
    try:
        assert magicdns_address(NAME, server=served.address, timeout=0.2) == expected
        [query] = served.queries
        ident, flags, questions = struct.unpack('>HHH', query[:6])
        assert flags == 0x0100 and questions == 1  # a standard query, recursion desired
        assert query[12:] == b'\x07station\x08tail0000\x02ts\x03net\x00' + struct.pack('>HH', 1, 1)
    finally:
        served.close()


def test_magicdns_address_refuses_a_name_it_cant_ask_for():
    assert magicdns_address('a' * 64 + '.ts.net', server=('127.0.0.1', 9)) is None
    assert magicdns_address('caf\u00e9.ts.net', server=('127.0.0.1', 9)) is None
