"""Pinned HTTPS with bounded DNS, wire deadlines and no redirects: the card's exact certificate, and nothing else."""
from contextlib import nullcontext
import hashlib
import http.client
import queue
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit
from .identity import MAX_ENVELOPE, validate_card, parse
from .common import Problem

TIMEOUT = 3.0
PEER_REPLY = 64 * 1024  # a peer's answer to a push, and the most of any non-2xx answer read
PULL_CAP = MAX_ENVELOPE + 64 * 1024  # federation-pull spec §5: one envelope at the most, and its frame
PULL_RATE = 64 * 1024  # bytes a second over the declared length, after the headers
_resolvers = threading.BoundedSemaphore(4)


class PinMismatch(Exception):
    """The peer's certificate isn't its card's (spec §3). Raised after the handshake and before any byte is written."""


class PeerAnswer(Exception):
    """A peer's HTTP answer that isn't an acknowledgement, with its real status and its `error` text (spec §7)."""

    def __init__(self, status, message):
        super().__init__(f'{status} {message}')
        self.status, self.message = status, message


def resolve(host, port, timeout):
    """Bound waiting on platform DNS; at most four stalled daemon resolvers."""
    if not _resolvers.acquire(blocking=False):
        raise TimeoutError('Peer resolver is busy')
    result = queue.Queue(maxsize=1)
    def worker():
        try:
            result.put(socket.getaddrinfo(host,port,type=socket.SOCK_STREAM))
        except OSError as exc:
            result.put(exc)
        finally:
            _resolvers.release()
    threading.Thread(target=worker,daemon=True).start()
    try:
        value = result.get(timeout=max(.001,timeout))
    except queue.Empty:
        raise TimeoutError('Peer DNS deadline exceeded') from None
    if isinstance(value,Exception):
        raise value
    return value


def _dialable(card):
    """Plan SF7: a card this side can't dial is refused as ValueError, before anything resolves or opens."""
    try:
        validate_card(card)
    except Problem:
        raise ValueError('Peer card is invalid') from None
    if card['endpoint'] is None:
        raise ValueError('Peer card has no endpoint: that peer fetches from us')
    return urlsplit(card['endpoint'])


def _pinned_socket(card, url, deadline):
    """Spec §3 and review MF1: connect, complete the TLS 1.3 handshake, and compare the certificate's SHA-256 with the
    card's fingerprint. Push and pull both dial here, so neither can write a byte before the compare. Names and dates
    aren't checked: the handshake's signature proves the peer holds the pinned certificate's key, and checking them is
    what made peers undialable by tailnet name and would end every link a year after its identity was made."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    addresses = resolve(url.hostname, url.port or 443, deadline-time.monotonic())
    failure = None
    for family,kind,proto,_,address in addresses:
        raw = socket.socket(family,kind,proto)
        try:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Peer deadline exceeded')
            raw.settimeout(remaining)
            raw.connect(address)
            raw.settimeout(max(.001,deadline-time.monotonic()))
            tls = context.wrap_socket(raw,server_hostname=url.hostname)  # SNI is still sent
            break
        except OSError as exc:
            raw.close()
            failure = exc
    else:
        raise failure or OSError('No peer addresses')
    der = tls.getpeercert(binary_form=True)  # None if the peer showed no certificate: a mismatch too (Serenity)
    if not der or hashlib.sha256(der).hexdigest() != card['fingerprint']:
        tls.close()
        raise PinMismatch('Peer certificate differs from its card')
    return tls


def _expire(wire_socket, deadline):
    """Shut the socket down at the deadline, so a stalled peer can't hold a read open."""
    def expire():
        try:
            wire_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    timer = threading.Timer(max(.001,deadline-time.monotonic()),expire)
    timer.daemon = True
    timer.start()
    return timer


def _error_text(raw):
    try:
        message = parse(raw, limit=PEER_REPLY).get('error')
    except Problem:
        return ''
    return message if isinstance(message, str) else ''


def _short(response, raw):
    """A body shorter than its Content-Length: the deadline cut it, and `read` returned what it had (plan SF3)."""
    declared = response.getheader('Content-Length')
    return declared is not None and declared.isdigit() and len(raw) < int(declared)


def send_pinned(card, prepare, *, gate=None, timeout=TIMEOUT):
    url = _dialable(card)
    deadline = time.monotonic()+timeout
    conn = http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=timeout)
    timer = None
    try:
        wire = conn.sock = _pinned_socket(card, url, deadline)
        timer = _expire(wire, deadline)
        # Connect/handshake first, then recheck authorization and write. No SQLite
        # transaction spans this socket write; local commits serialize on gate.
        with gate or nullcontext():
            body = prepare()
            if time.monotonic() >= deadline:
                raise TimeoutError('Peer deadline exceeded')
            conn.request('POST', '/federation/events', body=body, headers={'Content-Type':'application/json'})
        response = conn.getresponse()
        raw = response.read(PEER_REPLY+1)
        if len(raw) > PEER_REPLY:
            raise OSError('Peer reply is over 64 KiB')  # peer-scoped, as a network failure is (spec §7)
        if _short(response, raw):
            raise TimeoutError('Peer reply stalled')
        if not 200 <= response.status < 300:
            raise PeerAnswer(response.status, _error_text(raw))
        try:
            result = parse(raw)
        except Problem:
            raise PeerAnswer(response.status, 'Peer did not acknowledge delivery') from None
        if result.get('ok') is not True:
            raise PeerAnswer(response.status, 'Peer did not acknowledge delivery')
        return result
    finally:
        if timer:
            timer.cancel()
        conn.close()


def pull_answer_ok(result):
    """A pull response's shape (spec §5): exactly `ok` (true), `envelopes` (a list of strings) and `more` (a bool). The
    puller checks an in-process answer with it too, so both paths refuse the same bodies (plan SF7)."""
    return (isinstance(result, dict) and set(result) == {'ok', 'envelopes', 'more'} and result['ok'] is True
            and type(result['more']) is bool and isinstance(result['envelopes'], list)
            and all(isinstance(e, str) for e in result['envelopes']))


def pull_pinned(card, body, *, header_timeout=10.0, rate=PULL_RATE):
    """Spec §5: POST a signed pull request to /federation/pull over the same pinned dial. The headers must come within
    header_timeout; then the body gets its declared Content-Length / rate, so a large response on a slow link has time
    and a stalled one still ends. A 2xx needs a Content-Length within PULL_CAP, refused unread otherwise."""
    url = _dialable(card)
    deadline = time.monotonic()+header_timeout
    conn = http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=header_timeout)
    timer = None
    try:
        # Its own reference: getresponse() hands a closing connection's socket to the response and sets conn.sock to None.
        wire = conn.sock = _pinned_socket(card, url, deadline)
        timer = _expire(wire, deadline)
        conn.request('POST', '/federation/pull', body=body, headers={'Content-Type':'application/json'})
        response = conn.getresponse()
        timer.cancel()
        if not 200 <= response.status < 300:
            timer = _expire(wire, time.monotonic()+header_timeout)
            raw = response.read(PEER_REPLY+1)
            raise PeerAnswer(response.status, _error_text(raw) if len(raw) <= PEER_REPLY else '')
        declared = response.getheader('Content-Length')
        if declared is None or not declared.isdigit() or int(declared) > PULL_CAP:
            raise PeerAnswer(response.status, 'Pull response has no Content-Length within the cap')
        length = int(declared)
        timer = _expire(wire, time.monotonic()+length/rate)
        raw = response.read(length)
        if len(raw) < length:
            raise TimeoutError('Peer pull response stalled')
        try:
            result = parse(raw, limit=PULL_CAP)
        except Problem:
            raise PeerAnswer(response.status, 'Peer pull response is malformed') from None
        if not pull_answer_ok(result):
            raise PeerAnswer(response.status, 'Peer pull response is malformed')
        return result
    finally:
        if timer:
            timer.cancel()
        conn.close()
