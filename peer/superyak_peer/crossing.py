"""Lighthouse crossings between peers (ship home and crossing spec, section 2; plan P2 to P9, P17).

The publisher's side, `serve`, answers POST /federation/crossing on federation-listen: spec 2.3's seven checks touch
peer.sqlite3 only, then the rewritten frame goes to the publisher's read-only lighthouse daemon over its Unix socket,
and the signed answer comes back with a `crossings` row. The asking side, `ask`, serves one line on crossing.sock (P8):
it checks the hosted store and the destination, signs, dials the publisher pinned, and verifies the answer.

Settings live in crossings.toml in the peer data directory (P2), read per request by mtime: `[[published]]` maps a ship
of this peer to the daemon publisher serving its house, and `[[hosted]]` names the stores this home hosts (P19's
interim, until the store host lands)."""
import collections
from contextlib import closing, contextmanager
import fcntl
import http.client
import json
import logging
import math
import os
from pathlib import Path
import re
import socket
import socketserver
import sqlite3
import stat
import threading
import time
import tomllib

from .common import Problem, uid
from .identity import (ANSWERS, HEX64, PARTICIPANT_ID, UUID_FORM, canonical, crossing_digest, crossing_frame_ok,
                       crossing_shape_ok, parse, verify_crossing, verify_crossing_answer)
from .transport import PeerAnswer, PinMismatch, crossing_pinned

log = logging.getLogger(__name__)
CROSSING_REQUEST_MAX = 16 * 1024  # spec 2.3; the listener's cap for the route too
ANSWER_MAX = 128 * 1024           # a signed answer (spec 2.3, P7)
CONTENT_MAX = 32 * 1024           # the text a read delivers, as UTF-8 (spec 2.3, P7)
DAEMON_REPLY_MAX = 1024 * 1024    # one daemon line, as lighthouse_client reads one
DAEMON_CODE = re.compile(r'[A-Z][A-Z0-9_]{0,63}')
NOT_CONTACT = 'Receiving ship is not a current contact'
TRUST_ONLY = 'Receiving ship is paired only by an owner trust, which crossings do not accept'
# The asking side's codes for the publisher's known 403 words (the section 2 review's M2), so a receipt tells a
# trust-only ship from a held contact, an unpaired origin, a bad signature or a clock. Any other 403 is REFUSED_403.
REFUSAL_CODES = {NOT_CONTACT: 'REFUSED_CONTACT', TRUST_ONLY: 'REFUSED_TRUST_ONLY',
                 'Clocks differ by more than 5 minutes': 'REFUSED_CLOCK',
                 'Peer authentication failed': 'REFUSED_SIGNATURE', 'Unknown or unpaired peer': 'REFUSED_UNPAIRED'}
BAD_ANSWER, TOO_LARGE, TOO_MANY = 'Bad publisher answer', 'Answer too large', 'Too many crossings'
SETTINGS_FILE = 'crossings.toml'
SETTINGS_MAX = 64 * 1024
PUBLISHED_KEYS = frozenset({'ship', 'publisher', 'daemon_socket', 'sidecar'})
HOSTED_KEYS = frozenset({'ship', 'instance_id'})
USERNAME = re.compile(r'[A-Za-z0-9_.-]{1,64}')
PUBLISHER_NAME = re.compile(r'[A-Za-z0-9_-]{1,64}')  # Engram's receiver/publisher NAME: no colon, never a remote ref


class SettingsInvalid(ValueError):
    """crossings.toml can't be used: every crossing is refused with 503 until it is fixed, and the cause is logged."""


_cache, _cache_lock = {}, threading.Lock()


def _read(path):
    """The file's bytes and its stat key, refusing a symlink or anything not a regular file. None when absent."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
    except FileNotFoundError:
        return None, None
    except OSError as error:
        raise SettingsInvalid(f'{path} can\'t be opened (a symlink is refused): {error.strerror}') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise SettingsInvalid(f'{path} is not a regular file')
        if info.st_size > SETTINGS_MAX:
            raise SettingsInvalid(f'{path} is larger than {SETTINGS_MAX} bytes')
        chunks = []
        while chunk := os.read(fd, SETTINGS_MAX + 1):
            chunks.append(chunk)
        return b''.join(chunks), (info.st_ino, info.st_mtime_ns, info.st_size)
    finally:
        os.close(fd)


def _table(rows, name, keys):
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise SettingsInvalid(f'[[{name}]] must be a list of tables')
    for row in rows:
        if set(row) - keys:
            raise SettingsInvalid(f'[[{name}]] has an unknown key: {", ".join(sorted(set(row) - keys))}')
        if keys - set(row):
            raise SettingsInvalid(f'[[{name}]] is missing {", ".join(sorted(keys - set(row)))}')
        if not all(isinstance(row[k], str) for k in keys):
            raise SettingsInvalid(f'[[{name}]] values are text')
        if not USERNAME.fullmatch(row['ship']):
            raise SettingsInvalid(f'[[{name}]] ship must be a username')
    return [dict(row) for row in rows]


def _parse(raw, path):
    try:
        value = tomllib.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SettingsInvalid(f'{path} is not valid TOML: {error}') from None
    if set(value) - {'published', 'hosted'}:
        raise SettingsInvalid(f'{path} has an unknown key: {", ".join(sorted(set(value) - {"published", "hosted"}))}')
    published = _table(value.get('published', []), 'published', PUBLISHED_KEYS)
    hosted = _table(value.get('hosted', []), 'hosted', HOSTED_KEYS)
    for row in published:
        if not PUBLISHER_NAME.fullmatch(row['publisher']):
            raise SettingsInvalid('[[published]] publisher must be a daemon publisher name')
        for key in ('daemon_socket', 'sidecar'):
            if not os.path.isabs(row[key]):
                raise SettingsInvalid(f'[[published]] {key} must be an absolute path')
        if Path(row['daemon_socket']).name == 'host.sock':  # spec 1.1's store host: a crossing never reaches one
            raise SettingsInvalid('[[published]] daemon_socket names a store host (host.sock); a crossing reaches only '
                                  'the read-only lighthouse daemon')
    for row in hosted:
        if not UUID_FORM.fullmatch(row['instance_id']):
            raise SettingsInvalid('[[hosted]] instance_id must be a canonical UUID')
    ships = [row['ship'] for row in published]
    if len(set(ships)) != len(ships):
        raise SettingsInvalid('[[published]] names a ship twice')
    instances = [row['instance_id'] for row in hosted]
    if len(set(instances)) != len(instances):
        raise SettingsInvalid('[[hosted]] names a store twice')
    return {'published': published, 'hosted': hosted}


def load_settings(data_dir):
    """Plan P2: crossings.toml, parsed again whenever its inode, mtime or size changes, so an edit takes effect without
    a restart. No file publishes and hosts nothing. A bad file raises SettingsInvalid, every time it is read."""
    path = Path(data_dir) / SETTINGS_FILE
    raw, key = _read(path)
    if raw is None:
        return {'published': [], 'hosted': []}
    with _cache_lock:
        cached = _cache.get(str(path))
        if cached and cached[0] == key:
            settings = cached[1]
        else:
            settings = None
    if settings is None:
        settings = _parse(raw, path)
        with _cache_lock:
            _cache[str(path)] = (key, settings)
    return {'published': [dict(r) for r in settings['published']], 'hosted': [dict(r) for r in settings['hosted']]}


def _ship_ids(store, usernames):
    """B2: each username's users.id, for users of kind `ship` only."""
    if not usernames:
        return {}
    with store.transaction() as db:
        marks = ','.join('?' * len(usernames))
        return {row[0]: row[1] for row in db.execute(
            f"SELECT username, id FROM users WHERE kind='ship' AND username IN ({marks})", list(usernames))}


def published_house(store, settings, publisher_ship):
    """Check 6: the [[published]] row whose ship resolves to the participant id `publisher_ship`, or None."""
    ids = _ship_ids(store, [row['ship'] for row in settings['published']])
    return next((row for row in settings['published'] if ids.get(row['ship']) == publisher_ship), None)


def hosted_store(store, settings, receiver_ship, receiver_instance):
    """Plan P2 and B2: whether a [[hosted]] row names `receiver_instance` for the ship whose id is `receiver_ship`."""
    ids = _ship_ids(store, [row['ship'] for row in settings['hosted']])
    return any(row['instance_id'] == receiver_instance and ids.get(row['ship']) == receiver_ship
               for row in settings['hosted'])


def serve(federation, raw):
    """POST /federation/crossing, the publisher's side (spec 2.3). The checks run in the spec's order and touch only
    peer.sqlite3 and crossings.toml, so nothing of Engram's is opened before all of them pass:
    1. the shape (400); 2. the destination (403, before any nonce is kept); 3. a paired origin of any card version
    (403); 4. its signature (403), `at` within 300 s (403), and its nonce, kept in pull_nonces under the restore floor
    (409 "Replay"); 5. `receiver_ship` a current, unheld, typed-confirmed contact from that origin (403); 6.
    `publisher_ship` mapped to a published house (404); 7. the load (429)."""
    from .federation import CLOCKS_DIFFER, contact_current, contact_trust_only
    store = federation.store
    value = parse(raw, limit=CROSSING_REQUEST_MAX)
    if not crossing_shape_ok(value):
        raise Problem(400, 'Invalid crossing request')
    if value['destination'] != federation.identity.peer_id:
        raise Problem(403, 'Not addressed to this peer')
    origin = value['origin']
    with store.transaction() as db:
        peer = db.execute('SELECT card FROM peers WHERE peer_id=? AND paired=1', (origin,)).fetchone()
    if not peer:
        raise Problem(403, 'Unknown or unpaired peer')
    verify_crossing(json.loads(peer['card']), value)
    now = store.clock()
    if abs(value['at'] - now) > 300:
        raise Problem(403, CLOCKS_DIFFER)
    if not federation.take_nonce(origin, value['nonce'], value['at'], now):
        raise Problem(409, 'Replay')
    with store.transaction() as db:
        if contact_current(db, origin, value['receiver_ship']) is None:
            raise Problem(403, TRUST_ONLY if contact_trust_only(db, origin, value['receiver_ship']) else NOT_CONTACT)
    try:
        settings = load_settings(store.data_dir)
    except SettingsInvalid as error:
        log.error('crossings.toml refused, so every crossing is refused: %s', error)
        raise Problem(503, 'Crossings are not configured on this peer') from None
    house = published_house(store, settings, value['publisher_ship'])
    if house is None:
        raise Problem(404, 'No published house for that ship')
    with federation.crossing_limiter.admit(origin):
        return _answer(federation, value, house)


class Limiter:
    """Plan P6, the publisher's side, counted in memory after check 6, so only verified, mapped requests count: at most
    `per_origin` crossings in flight from one origin and `total` in all, each taken without waiting, and at most
    `per_minute` admitted from one origin in any 60 s on `clock`. Any refusal is 429. Four in flight at most leave the
    listener's thread pool to events and pulls (listener.py runs handlers with asyncio.to_thread)."""

    def __init__(self, *, per_origin=2, total=4, per_minute=60, clock=time.monotonic):
        self.per_origin, self.per_minute, self.clock = per_origin, per_minute, clock
        self._total = threading.BoundedSemaphore(total)
        self._origins, self._times, self._lock = {}, {}, threading.Lock()

    @contextmanager
    def admit(self, origin):
        with self._lock:
            mine = self._origins.setdefault(origin, threading.BoundedSemaphore(self.per_origin))
        if not mine.acquire(blocking=False):
            raise Problem(429, TOO_MANY)
        try:
            if not self._total.acquire(blocking=False):
                raise Problem(429, TOO_MANY)
            try:
                now = self.clock()
                with self._lock:
                    times = self._times.setdefault(origin, collections.deque())
                    while times and times[0] <= now - 60:
                        times.popleft()
                    if len(times) >= self.per_minute:
                        raise Problem(429, TOO_MANY)
                    times.append(now)
                yield
            finally:
                self._total.release()
        finally:
            mine.release()


def _left(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Deadline passed')
    return remaining


def daemon_call(socket_path, frame, deadline):
    """One canonical JSON line to the publisher's lighthouse daemon and one line back, at most DAEMON_REPLY_MAX, all
    within `deadline` (time.monotonic). TimeoutError at the deadline; OSError when it can't be reached or closes
    early; Problem when its line isn't one JSON object.

    A recall tells the daemon how long it waits (`remainingMs`, spec 2026-11-10), so the publisher's embed gives up
    with it. It goes on the frame sent to the daemon only, rounded up so it stays an upper bound, after the request
    was checked and digested: the asker's signed request, its FRAME_KEYS and its crossing_digest never carry it."""
    if frame.get('kind') == 'recall':
        frame = {**frame, 'remainingMs': math.ceil(_left(deadline) * 1000)}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(_left(deadline))
        connection.connect(str(socket_path))
        connection.settimeout(_left(deadline))
        connection.sendall(canonical(frame) + b'\n')
        data = bytearray()
        while b'\n' not in data:
            connection.settimeout(_left(deadline))
            part = connection.recv(65536)
            if not part:
                raise OSError('The daemon closed the connection before answering')
            data += part
            if len(data) > DAEMON_REPLY_MAX + 1:
                raise OSError('The daemon answered more than 1 MiB')
    _left(deadline)
    line, _, rest = bytes(data).partition(b'\n')
    if rest:
        raise Problem(400, 'The daemon answered more than one line')
    return parse(line, limit=DAEMON_REPLY_MAX)


def _content_bytes(items):
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise Problem(502, BAD_ANSWER)
    return sum(len(i['content'].encode('utf-8')) for i in items if isinstance(i.get('content'), str))


def _answer(federation, value, house):
    """Plan P7, after the seven checks. The frame's `receiver` becomes the ref built from the verified origin and its
    `publisher` the mapped daemon publisher; the daemon answers within `deadline_ms`. An error frame is 502 with the
    daemon's code; a daemon past the deadline is 504; an answer over 128 KiB or delivering over 32 KiB of text is 502.
    None of those writes a row. Then the `crossings` row, and only then the signed answer: a failed insert is 503 with
    no answer, and the daemon's disclosure shows as unsent (P18)."""
    origin = value['origin']
    ref = f'urn:superyak:{origin}:store:{value["receiver_instance"]}'
    frame = {**value['frame'], 'receiver': ref, 'publisher': house['publisher']}
    deadline = time.monotonic() + value['deadline_ms'] / 1000
    try:
        reply = daemon_call(house['daemon_socket'], frame, deadline)
    except TimeoutError:
        raise Problem(504, 'Deadline passed') from None
    except (OSError, Problem) as error:
        log.warning('the lighthouse daemon for %s could not answer a crossing: %s', house['publisher'], error)
        raise Problem(502, 'Publisher unavailable') from None
    if reply.get('kind') == 'error':
        code = reply.get('code')
        raise Problem(502, code if isinstance(code, str) and DAEMON_CODE.fullmatch(code) else 'Publisher error')
    disclosure = reply.get('disclosureId')
    if reply.get('protocolVersion') != '0.1' or reply.get('kind') != ANSWERS[frame['kind']] \
            or not isinstance(disclosure, str) or not 1 <= len(disclosure) <= 256:
        raise Problem(502, BAD_ANSWER)
    if frame['kind'] == 'read' and _content_bytes(reply.get('items')) > CONTENT_MAX:
        raise Problem(502, TOO_LARGE)
    digest = crossing_digest(value)
    answer = federation.identity.sign_crossing_answer({
        'version': 1, 'kind': 'crossing-answer', 'origin': federation.identity.peer_id, 'destination': origin,
        'request_digest': digest, 'nonce': value['nonce'], 'frame': reply})
    if len(canonical(answer)) > ANSWER_MAX:
        raise Problem(502, TOO_LARGE)
    try:
        with federation.store.transaction() as db:
            db.execute('INSERT INTO crossings(disclosure_id, origin_peer, receiver_ref, request_digest, nonce, at) '
                       'VALUES(?,?,?,?,?,?)', (disclosure, origin, ref, digest, value['nonce'], value['at']))
    except sqlite3.Error as error:
        log.error('a crossing answer was withheld: its crossings row could not be written: %s', error)
        raise Problem(503, 'Crossing could not be recorded') from None
    return answer


class AskBound:
    """Plan P6, the asking side: at most `per_destination` crossings in flight to one destination. A further one waits
    for a slot only within its own deadline, so this peer's own load never earns a 429."""

    def __init__(self, per_destination=2):
        self.per_destination, self._slots, self._lock = per_destination, {}, threading.Lock()

    @contextmanager
    def slot(self, destination, deadline):
        with self._lock:
            slots = self._slots.setdefault(destination, threading.BoundedSemaphore(self.per_destination))
        if not slots.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise TimeoutError('No crossing slot to that peer within the deadline')
        try:
            yield
        finally:
            slots.release()


LOCAL_KEYS = frozenset({'receiver_instance', 'receiver_ship', 'destination', 'publisher_ship', 'frame', 'deadline_ms'})
# The local line may hold anything P4 allows (a 4,096-character query is up to 16 KiB of UTF-8 alone), so it is read up
# to 32 KiB, and P17's 16 KiB rule is measured on the canonical signed request, where it can answer QUERY_TOO_LARGE. A
# 16 KiB local cap (P8's first wording) would refuse that request as BAD_REQUEST before P17 could measure it.
LOCAL_REQUEST_MAX = 32 * 1024


def _local_ok(value):
    """Plan P8: the local hop's request, exactly LOCAL_KEYS, each of its type, with P4's frame."""
    try:
        return (isinstance(value, dict) and set(value) == LOCAL_KEYS
                and isinstance(value['receiver_instance'], str) and UUID_FORM.fullmatch(value['receiver_instance'])
                is not None
                and all(isinstance(value[k], str) and PARTICIPANT_ID.fullmatch(value[k])
                        for k in ('receiver_ship', 'publisher_ship'))
                and isinstance(value['destination'], str) and HEX64.fullmatch(value['destination']) is not None
                and crossing_frame_ok(value['frame'])
                and type(value['deadline_ms']) is int and 0 <= value['deadline_ms'] <= 10_000)
    except (TypeError, KeyError):
        return False


def _no(code):
    return {'ok': False, 'code': code}


def ask(federation, raw):
    """Plan P8, the asking side of the local hop: one request line from crossing.sock in, one reply out. In order: the
    request's shape (BAD_REQUEST); the store hosted here for that ship, by crossings.toml's [[hosted]] (NOT_HOSTED; 1.1's
    same-uid caveat applies); the destination a paired push peer with an endpoint (NOT_PAIRED); under 100 ms left
    (TIMEOUT, no dial); the canonical signed request over 16 KiB (QUERY_TOO_LARGE, no dial; P17); a slot to that
    destination within the deadline (TIMEOUT). Then the request, signed as this peer with a fresh nonce, goes over the
    pinned dial, and the answer must verify (BAD_ANSWER) before its frame is handed back. A refusal is REFUSED_<status>;
    a dial that fails is UNAVAILABLE, or TIMEOUT at the deadline. Engram never holds a peer key."""
    started = time.monotonic()
    try:
        value = parse(raw, limit=LOCAL_REQUEST_MAX)
    except Problem:
        return _no('BAD_REQUEST')
    if not _local_ok(value):
        return _no('BAD_REQUEST')
    deadline = started + value['deadline_ms'] / 1000
    store = federation.store
    try:
        settings = load_settings(store.data_dir)
    except SettingsInvalid as error:
        log.error('crossings.toml refused, so no crossing is asked: %s', error)
        return _no('UNAVAILABLE')
    if not hosted_store(store, settings, value['receiver_ship'], value['receiver_instance']):
        return _no('NOT_HOSTED')
    with store.transaction() as db:
        row = db.execute('SELECT card FROM peers WHERE peer_id=? AND paired=1', (value['destination'],)).fetchone()
    card = json.loads(row['card']) if row is not None else None
    if card is None or card.get('delivery', 'push') != 'push' or not card.get('endpoint'):
        return _no('NOT_PAIRED')
    left_ms = int((deadline - time.monotonic()) * 1000)
    if left_ms < 100:
        return _no('TIMEOUT')
    me = federation.identity.peer_id
    signed = federation.identity.sign_crossing({
        'version': 1, 'kind': 'crossing', 'origin': me, 'destination': value['destination'],
        'receiver_instance': value['receiver_instance'], 'receiver_ship': value['receiver_ship'],
        'publisher_ship': value['publisher_ship'], 'frame': value['frame'], 'deadline_ms': min(left_ms, 10_000),
        'nonce': uid(), 'at': int(store.clock())})
    body = canonical(signed)
    if len(body) > CROSSING_REQUEST_MAX:
        return _no('QUERY_TOO_LARGE')
    try:
        with federation.crossing_asks.slot(value['destination'], deadline):
            answer = crossing_pinned(card, body, deadline=deadline)
    except PeerAnswer as refusal:
        return _no((refusal.status == 403 and REFUSAL_CODES.get(refusal.message)) or f'REFUSED_{refusal.status}')
    except TimeoutError:
        return _no('TIMEOUT')
    except (OSError, ValueError, PinMismatch, http.client.HTTPException) as error:
        log.warning('a crossing to %s could not be dialled: %s', value['destination'][:8], type(error).__name__)
        return _no('UNAVAILABLE')
    try:
        verify_crossing_answer(card, answer, me=me, digest=crossing_digest(signed), nonce=signed['nonce'],
                               kind=value['frame']['kind'])
    except ValueError:
        return _no('BAD_ANSWER')
    return {'ok': True, 'frame': answer['frame']}


SOCKET_FILE, LOCK_FILE = 'crossing.sock', 'crossing.lock'
LOCK_HELD = 'another process already serves crossing.sock'
RESTART_SECONDS = 1.0
UNIX_PATH_MAX = 107  # sun_path's bytes, less its terminating NUL


def crossing_lock(data_dir):
    """Plan P9 and S3: one owner of crossing.sock per data directory, as federation_lock is one syncing process. An
    flock on crossing.lock, opened O_NOFOLLOW at 0600 and taken LOCK_NB, held until the returned descriptor closes. A
    second holder gets ValueError(LOCK_HELD)."""
    fd = os.open(os.path.join(data_dir, LOCK_FILE),
                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise ValueError(LOCK_HELD) from None
    return fd


def lock_held(data_dir):
    """Whether a process holds crossing.lock now (for `crossings`): taken and let go at once when it is free."""
    try:
        os.close(crossing_lock(data_dir))
        return False
    except ValueError:
        return True
    except OSError:
        return False


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(10)
        raw = self.rfile.readline(LOCAL_REQUEST_MAX + 2)
        if not raw.endswith(b'\n') or len(raw) > LOCAL_REQUEST_MAX + 1:
            reply = _no('BAD_REQUEST')
        else:
            reply = ask(self.server.federation, raw[:-1])
        self.wfile.write(canonical(reply) + b'\n')


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        log.error('crossing.sock: a request failed', exc_info=True)


class CrossingSocket:
    """Plan P9: crossing.sock in the peer data directory, mode 0600, served by a ThreadingUnixStreamServer that a
    supervisor thread runs. A fault in the server is logged and it is bound again after RESTART_SECONDS; a handler's
    fault is logged and ends only its own request. It shares only the Federation, and never raises into the process
    that started it. Only crossing.lock's holder binds, or unlinks a stale crossing.sock, so no process takes over a
    live one (S3)."""

    def __init__(self, federation):
        self.federation = federation
        self.data_dir = Path(federation.store.data_dir)
        self.path = self.data_dir / SOCKET_FILE
        self._server, self._thread, self._lock_fd = None, None, None
        self._stopping = threading.Event()

    @property
    def serving(self):
        return self._server is not None and self.path.exists()

    def start(self):
        """Take crossing.lock (ValueError(LOCK_HELD) when another process holds it), then serve on a supervisor
        thread. A symlinked crossing.sock, or a path too long for a Unix socket, is refused with ValueError."""
        if len(os.fsencode(str(self.path))) > UNIX_PATH_MAX:
            raise ValueError(f'{self.path} is too long for a Unix socket')
        self._lock_fd = crossing_lock(self.data_dir)
        if self.path.is_symlink():
            os.close(self._lock_fd)
            self._lock_fd = None
            raise ValueError(f'{self.path} is a symlink; it is never replaced')
        self._thread = threading.Thread(target=self._supervise, name='crossing-socket', daemon=True)
        self._thread.start()
        return self

    def _bind(self):
        if self.path.is_symlink():
            raise ValueError(f'{self.path} became a symlink')
        try:
            self.path.unlink()  # stale: this process holds crossing.lock, so nobody else serves it
        except FileNotFoundError:
            pass
        previous = os.umask(0o177)
        try:
            server = _Server(str(self.path), _Handler)
        finally:
            os.umask(previous)
        os.chmod(self.path, 0o600, follow_symlinks=False)
        server.federation = self.federation
        return server

    def _supervise(self):
        while not self._stopping.is_set():
            server = None
            try:
                server = self._bind()
                self._server = server
                if self._stopping.is_set():
                    break
                server.serve_forever(poll_interval=0.2)
            except Exception:  # noqa: BLE001 - a fault in the socket never ends the process (spec 2.1)
                log.exception('crossing.sock failed; it restarts in %s s', RESTART_SECONDS)
            finally:
                self._server = None
                if server is not None:
                    server.server_close()
            if not self._stopping.is_set():
                self._stopping.wait(RESTART_SECONDS)

    def stop(self):
        self._stopping.set()
        server = self._server
        if server is not None:
            server.shutdown()
        if self._thread is not None:
            self._thread.join(10)
        try:
            if not self.path.is_symlink():
                self.path.unlink()
        except FileNotFoundError:
            pass
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None


def start_crossing_socket(federation):
    """The commands' way in (federate and federation-listen --crossing-socket, P9 and the plan re-check's item 4): the
    started CrossingSocket, or None, logged, when it can't start, as when another process holds crossing.lock. The
    process runs on without it, so its events, pulls and pushes are never stopped by the socket."""
    try:
        return CrossingSocket(federation).start()
    except (ValueError, OSError) as error:
        log.warning('crossing.sock not opened, so this process asks no crossings: %s', error)
        return None


def report(store):
    """`crossings` (P18): recent `crossings` rows, then, for each [[published]] sidecar opened read-only, every
    disclosure to a remote ref with no `crossings` row: the daemon recorded it and no answer was sent. Read-only."""
    lines = [f'crossing.sock: {"served by a running process" if lock_held(store.data_dir) else "not served here"}']
    with store.transaction() as db:
        rows = db.execute('SELECT * FROM crossings ORDER BY at DESC, disclosure_id LIMIT 50').fetchall()
        sent = {r[0] for r in db.execute('SELECT disclosure_id FROM crossings')}
    lines.append('Recent crossings (newest first):')
    lines += [f'  {r["at"]} {r["disclosure_id"]} from {r["origin_peer"][:12]} as {r["receiver_ref"]}' for r in rows] \
        or ['  none']
    lines.append('Unsent (the daemon recorded a disclosure to a remote store, and no crossings row says it was sent):')
    try:
        settings = load_settings(store.data_dir)
    except SettingsInvalid as error:
        return lines + [f'  crossings.toml cannot be used: {error}']
    found = False
    for house in settings['published']:
        try:
            with closing(sqlite3.connect(f'file:{house["sidecar"]}?mode=ro', uri=True)) as sidecar:
                rows = sidecar.execute("SELECT id, at, receiver, action FROM disclosures WHERE receiver LIKE "
                                       "'urn:superyak:%' ORDER BY at").fetchall()
        except sqlite3.Error as error:
            lines.append(f'  {house["publisher"]}: its sidecar {house["sidecar"]} cannot be read ({error}), so this '
                         'list may be short')
            continue
        for key, at, receiver, action in rows:
            if key not in sent:
                found = True
                lines.append(f'  {house["publisher"]} {key} {action} at {at} for {receiver}')
    if not found:
        lines.append('  none found')
    return lines


def contact_report(store, peer_id):
    """`crossings --contacts PEER_ID` (nit 6): each contact from that peer, by name and participant id, and whether
    check 5 accepts it, by contact_current, the rule `serve` uses. It prints no pairing code."""
    from .federation import contact_current
    from .owner_trust import code_current, plain_name
    lines = [f'Contacts from {peer_id[:12]} as check 5 reads them:']
    with store.transaction() as db:
        contacts = db.execute('SELECT c.id, c.user_id, l.label AS name, p.paired, '  # shown by its label (owner trust)
                              'EXISTS(SELECT 1 FROM contact_holds h WHERE h.contact_id=c.id) AS held '
                              'FROM remote_contacts c JOIN contact_labels l ON l.id=c.id JOIN peers p USING(peer_id) '
                              'WHERE c.peer_id=? ORDER BY l.label', (peer_id,)).fetchall()
        for row in contacts:
            if contact_current(db, peer_id, row['user_id']) is not None:
                verdict = 'accepted'
            else:
                why = [w for w, bad in (('peer unpaired', not row['paired']), ('held', row['held']),
                                        ('no current typed code', not code_current(db, row['id']))) if bad]
                verdict = f'refused ({", ".join(why)})'
            lines.append(f'  {plain_name(row["name"])} ({row["user_id"]}): {verdict}')
    return lines + ([] if contacts else ['  none'])
