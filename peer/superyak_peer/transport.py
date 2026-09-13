"""Verified pinned HTTPS with bounded DNS, wire deadline and no redirects."""
from contextlib import nullcontext
import hashlib
import http.client
import queue
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit
from .identity import validate_card, parse
from .common import Problem

TIMEOUT = 3.0
_resolvers = threading.BoundedSemaphore(4)

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

def send_pinned(card, prepare, *, gate=None, timeout=TIMEOUT):
    validate_card(card)
    deadline = time.monotonic()+timeout
    url = urlsplit(card['endpoint'])
    addresses = resolve(url.hostname,url.port or 443,timeout)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cadata=card['certificate'])
    conn = http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=timeout, context=context)
    timer = None
    try:
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
                conn.sock = context.wrap_socket(raw,server_hostname=url.hostname)
                break
            except OSError as exc:
                raw.close()
                failure = exc
        if conn.sock is None:
            raise failure or OSError('No peer addresses')
        if hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest() != card['fingerprint']:
            raise Problem(403, 'Peer certificate fingerprint differs')
        wire_socket = conn.sock
        def expire():
            try:
                wire_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = threading.Timer(max(.001,deadline-time.monotonic()),expire)
        timer.daemon = True
        timer.start()
        # Connect/handshake first, then recheck authorization and write. No SQLite
        # transaction spans this socket write; local commits serialize on gate.
        with gate or nullcontext():
            body = prepare()
            if time.monotonic() >= deadline:
                raise TimeoutError('Peer deadline exceeded')
            conn.request('POST', '/federation/events', body=body, headers={'Content-Type':'application/json'})
        response = conn.getresponse()
        result = response.read(65537)
        if response.status != 200 or len(result)>65536:
            raise Problem(403 if response.status in (401,403) else 409, 'Peer delivery was not accepted')
        result = parse(result)
        if result.get('ok') is not True:
            raise Problem(409, 'Peer did not acknowledge delivery')
        return result
    except http.client.HTTPException:
        raise Problem(409, 'Peer HTTP exchange failed') from None
    finally:
        if timer:
            timer.cancel()
        conn.close()
