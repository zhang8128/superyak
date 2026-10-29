"""fix:docked-ships-over-tailnet: a ship reaches a *.ts.net station at the tailnet address MagicDNS gives, while TLS, SNI
and the Host header stay on the station's name. A Mac's resolver can answer Funnel's public pair for that name, and
every call then went out to the internet and back in (health 299 ms against 36 ms on the tailnet, 2026-10-29)."""
import http.server
import json
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import pytest
from superyak_agent import station
import time
from superyak_agent.station import StationClient, client_for, magicdns_address, tailnet_pin, tailnet_unpin, urllib_transport

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

    def __init__(self, cert, key, redirect=None, delay=0):
        self.seen = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        sni = []
        context.sni_callback = lambda sock, server_name, ctx: sni.append(server_name)
        seen = self.seen

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((sni[-1] if sni else None, self.headers.get('Host'), self.path))
                time.sleep(delay)
                if redirect and self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', redirect)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length') or 0))
                seen.append((sni[-1] if sni else None, self.headers.get('Host'), 'POST ' + self.path))
                self.send_response(201)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'{}')

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


def test_a_ts_net_station_is_reached_at_its_pinned_address_with_tls_on_the_name(trusted, monkeypatch):
    """The connection goes to the pinned address; the certificate is checked against the name, and SNI and Host are the
    name's, so the station can't tell the path apart. The pinned opener is built once, since its TLS context costs
    about 7 ms to make."""
    import urllib.request
    built, real = [], urllib.request.build_opener
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *handlers: built.append(1) or real(*handlers))
    send = urllib_transport(timeout=5, pin=lambda host: '127.0.0.1' if host == NAME else None)
    assert send('GET', f'https://{NAME}:{trusted.port}/api/health', {}, None) == (200, b'{"ok": true}')
    assert send('GET', f'https://{NAME}:{trusted.port}/api/me', {}, None)[0] == 200
    assert trusted.seen == [(NAME, f'{NAME}:{trusted.port}', '/api/health'), (NAME, f'{NAME}:{trusted.port}', '/api/me')]
    assert len(built) == 1


def test_a_pinned_station_that_answers_slowly_still_answers(tmp_path, monkeypatch):
    """Rio Grande's section 2, S1: the pinned connect gets PIN_CONNECT, but the reads after it get the call's own
    timeout. An answer 1.5 s in, with timeout=5, arrives; imprint-send waits up to 120 s. Mutation: no settimeout."""
    cert, key = certificate(tmp_path, NAME)
    monkeypatch.setenv('SSL_CERT_FILE', str(cert))
    served = Station(cert, key, delay=station.PIN_CONNECT + 0.5)
    try:
        send = urllib_transport(timeout=5, pin=lambda host: '127.0.0.1')
        assert send('GET', f'https://{NAME}:{served.port}/api/health', {}, None)[0] == 200
    finally:
        served.close()


def test_a_station_named_in_capitals_is_pinned_too(trusted):
    """Rio Grande's section 2, S3 (Tardis's catch): urlsplit's hostname is lowercase while the request keeps the name's
    case, so a station configured as Station.tail0000.ts.net was asked for and then never pinned."""
    upper = NAME.replace('station', 'Station')
    send = urllib_transport(timeout=5, pin=lambda host: '127.0.0.1' if host == NAME else None)
    assert send('GET', f'https://{upper}:{trusted.port}/api/health', {}, None)[0] == 200  # the name alone can't resolve


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


def test_an_address_that_wont_connect_falls_back_to_the_name_once_per_minute(tmp_path, monkeypatch):
    """Tardis: MagicDNS can answer 100.x while the connect still fails (an ACL, a node shared in, serve down). The pinned
    connect gives up after PIN_CONNECT; the call goes by the name as before, and the miss is kept, so the next call
    doesn't wait again. 192.0.2.1 is TEST-NET-1 (RFC 5737), never routed. Mutation: no fallback, or no miss kept."""
    import urllib.request
    cert, key = certificate(tmp_path, 'localhost')
    monkeypatch.setenv('SSL_CERT_FILE', str(cert))
    # urlopen's global opener makes its TLS context once (Python 3.12 on), so one an earlier test made wouldn't trust this
    # certificate: start a fresh one, as a new process would
    monkeypatch.setattr(urllib.request, '_opener', None)
    served = Station(cert, key)
    asked, pins = [], {}
    try:
        send = urllib_transport(timeout=5, pin=lambda host: tailnet_pin(host, ask=lambda h: asked.append(h) or '192.0.2.1',
                                                                          pins=pins, suffix=''),
                                unpin=lambda host: tailnet_unpin(host, pins=pins))
        began = time.monotonic()
        assert send('GET', f'https://localhost:{served.port}/api/health', {}, None)[0] == 200
        assert time.monotonic() - began < station.PIN_CONNECT + 2
        began = time.monotonic()
        assert send('GET', f'https://localhost:{served.port}/api/me', {}, None)[0] == 200
        assert time.monotonic() - began < 0.5 and asked == ['localhost'] and pins['localhost'][0] is None
        assert [path for _, _, path in served.seen] == ['/api/health', '/api/me']
        # Rio Grande's point 3: a POST whose pinned connect fails reaches the station once, by the name
        pins.clear()
        assert send('POST', f'https://localhost:{served.port}/api/chats/r/messages', {'content-type': 'application/json'},
                    b'{"body": "once"}')[0] == 201
        assert [path for _, _, path in served.seen].count('POST /api/chats/r/messages') == 1
    finally:
        served.close()


def test_a_redirect_to_another_name_is_never_sent_to_the_pinned_address(tmp_path, monkeypatch):
    """Rio Grande's point 1: the pin is for the name it was asked for. A redirect from the pinned station to another
    name connects to that name, as urllib would without a pin, never to the station's tailnet address."""
    first, first_key = certificate(tmp_path, NAME)
    second, second_key = certificate(tmp_path, 'localhost')
    roots = tmp_path / 'roots.pem'
    roots.write_bytes(first.read_bytes() + second.read_bytes())
    monkeypatch.setenv('SSL_CERT_FILE', str(roots))
    target = Station(second, second_key)
    station_a = Station(first, first_key, redirect=f'https://localhost:{target.port}/api/health')
    dialled, real = [], socket.create_connection
    monkeypatch.setattr(socket, 'create_connection', lambda where, *rest: dialled.append(where) or real(where, *rest))
    try:
        send = urllib_transport(timeout=5, pin=lambda host: '127.0.0.1' if host == NAME else None)
        assert send('GET', f'https://{NAME}:{station_a.port}/redirect', {}, None) == (200, b'{"ok": true}')
        assert dialled == [('127.0.0.1', station_a.port), ('localhost', target.port)]
        assert [host for _, host, _ in target.seen] == [f'localhost:{target.port}']
    finally:
        target.close()
        station_a.close()


def test_every_client_the_agent_makes_takes_the_pin(trusted, monkeypatch):
    """Rio Grande: one transport for every path. client_for (the MCP server, the watcher, kick, imprint-send, Wormhole)
    and a StationClient with no transport (dock) both reach a pinned station at its pinned address."""
    monkeypatch.setitem(station._PINS, NAME, ('127.0.0.1', time.monotonic() + 60))
    base = f'https://{NAME}:{trusted.port}'
    assert client_for({'station': base, 'key': 'k'}).request('GET', '/api/health') == {'ok': True}
    assert StationClient(base).request('GET', '/api/health') == {'ok': True}
    assert [host for _, host, _ in trusted.seen] == [f'{NAME}:{trusted.port}'] * 2


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
    (lambda q: dns_answer(q, records=[(1, '100.63.255.255')]), None),   # just before it (Rio Grande's S2)
    (lambda q: dns_answer(q, records=[(5, '100.70.202.124')]), None),   # four bytes in 100.64/10, but not an A record
    (lambda q: dns_answer(q, records=[]), None),
    (lambda q: dns_answer(q, rcode=3, records=[(1, '100.70.202.124')]), None),  # an error code, whatever follows
    (lambda q: dns_answer(q, flags=0x0100, records=[(1, '100.70.202.124')]), None),  # not a response (no QR)
    (lambda q: dns_answer(q, records=[(1, '100.70.202.124')],
                          question=b'\x07statiox\x08tail0000\x02ts\x03net\x00' + struct.pack('>HH', 1, 1)), None),  # same length
    (lambda q: dns_answer(q, records=[(1, '100.70.202.124')], same_id=False), None),
    (lambda q: dns_answer(q, records=[(1, '100.70.202.124')])[:-3], None),  # cut short
    (lambda q: b'\x00' * 5, None),
    (lambda q: None, None),                                             # no answer within the timeout
], ids=['tailnet', 'tailnet-no-pointer', 'cname-first', 'public', 'past-the-range', 'before-the-range', 'not-a-record',
        'empty', 'error-code',
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


def test_each_query_has_its_own_id():
    """An answer must carry its query's id, so the id is drawn fresh each time (Rio Grande's N2: a fixed one survived)."""
    served = FakeDns(lambda q: None)
    try:
        for _ in range(4):
            magicdns_address(NAME, server=served.address, timeout=0.05)
        assert len({struct.unpack('>H', query[:2])[0] for query in served.queries}) > 1
    finally:
        served.close()


def test_magicdns_address_refuses_a_name_it_cant_ask_for():
    assert magicdns_address('a' * 64 + '.ts.net', server=('127.0.0.1', 9)) is None
    assert magicdns_address('caf\u00e9.ts.net', server=('127.0.0.1', 9)) is None


def test_a_hook_run_keeps_a_pin_miss_on_disk_for_the_next_prompt(tmp_path):
    """Tardis: the prompt hook is a new process each prompt, so a miss kept in memory was paid again every prompt (a
    1 s connect, or a 50 ms query off the tailnet). Each hook run's pin keeps a miss on disk beside the unreachable
    marker, for the same minute. Mutation: no marker written, or the marker not read."""
    from superyak_agent.hook import PIN_MISS, _pinning
    marker, clock, asked = tmp_path / PIN_MISS, [1000.0], []

    def ask(host):
        asked.append(host)
        return '100.70.202.124'
    pin, unpin = _pinning(marker, lambda: clock[0], ask=ask)
    assert pin(NAME) == '100.70.202.124' and not marker.exists()  # an answer writes nothing
    unpin(NAME)                                                    # that address wouldn't connect
    assert oct(marker.stat().st_mode & 0o777) == '0o600'
    assert json.loads(marker.read_text()) == {'at': 1000.0, 'host': NAME}  # a time and a host, never an address
    pin, unpin = _pinning(marker, lambda: clock[0] + 30, ask=ask)  # the next prompt, a new process
    assert pin(NAME) is None and asked == [NAME]                   # by the name, without asking
    assert pin('other.tail0000.ts.net') == '100.70.202.124'        # another name's miss is its own
    pin, unpin = _pinning(marker, lambda: clock[0] + 61, ask=ask)  # a minute on
    assert pin(NAME) == '100.70.202.124' and asked == [NAME, 'other.tail0000.ts.net', NAME]
    for damaged in ('not json', '{"at": "x", "host": "%s"}' % NAME, '{"host": "%s"}' % NAME, '[]',
                    '{"at": 99999999, "host": "%s"}' % NAME):  # damaged, or from the future: as if absent
        marker.write_text(damaged)
        assert _pinning(marker, lambda: clock[0], ask=ask)[0](NAME) == '100.70.202.124', damaged


def test_a_hook_run_keeps_a_magicdns_miss_too_but_never_for_another_name(tmp_path):
    from superyak_agent.hook import PIN_MISS, _pinning
    marker, asked = tmp_path / PIN_MISS, []
    pin, _ = _pinning(marker, lambda: 1000.0, ask=lambda host: asked.append(host))
    assert pin('example.com') is None and not marker.exists() and asked == []  # not a tailnet name: nothing kept
    assert pin(NAME) is None and marker.exists() and asked == [NAME]          # off the tailnet: kept
    pin, _ = _pinning(marker, lambda: 1010.0, ask=lambda host: asked.append(host))
    assert pin(NAME) is None and asked == [NAME]


def test_the_hook_builds_its_transports_with_its_runs_pin(tmp_path, monkeypatch):
    """Every transport a hook run makes, the board's apart from the rest included, takes that run's pin and unpin."""
    from superyak_agent import hook
    made = []
    monkeypatch.setattr(hook, 'urllib_transport', lambda *args, **kwargs: made.append(kwargs) or (lambda *a: (200, b'{}')))
    pin, unpin = (lambda host: None), (lambda host: None)
    link = hook._Link(None, pin, unpin)
    link(5)
    link.apart(5, 100)
    assert made == [{'pin': pin, 'unpin': unpin}, {'pin': pin, 'unpin': unpin}]
