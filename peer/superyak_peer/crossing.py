"""Lighthouse crossings between peers (ship home and crossing spec, section 2; plan P2 to P9, P17).

The publisher's side, `serve`, answers POST /federation/crossing on federation-listen: spec 2.3's seven checks touch
peer.sqlite3 only, then the rewritten frame goes to the publisher's read-only lighthouse daemon over its Unix socket,
and the signed answer comes back with a `crossings` row. The asking side, `ask`, serves one line on crossing.sock (P8):
it checks the hosted store and the destination, signs, dials the publisher pinned, and verifies the answer.

Settings live in crossings.toml in the peer data directory (P2), read per request by mtime: `[[published]]` maps a ship
of this peer to the daemon publisher serving its house, and `[[hosted]]` names the stores this home hosts (P19's
interim, until the store host lands)."""
import json
import logging
import os
from pathlib import Path
import re
import stat
import threading
import tomllib

from .common import Problem
from .identity import UUID_FORM, crossing_shape_ok, parse, verify_crossing

log = logging.getLogger(__name__)
CROSSING_REQUEST_MAX = 16 * 1024  # spec 2.3; the listener's cap for the route too
NOT_CONTACT = 'Receiving ship is not a current contact'
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
    with store.reading() as db:
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
    from .federation import CLOCKS_DIFFER, contact_current
    store = federation.store
    value = parse(raw, limit=CROSSING_REQUEST_MAX)
    if not crossing_shape_ok(value):
        raise Problem(400, 'Invalid crossing request')
    if value['destination'] != federation.identity.peer_id:
        raise Problem(403, 'Not addressed to this peer')
    origin = value['origin']
    with store.reading() as db:
        peer = db.execute('SELECT card FROM peers WHERE peer_id=? AND paired=1', (origin,)).fetchone()
    if not peer:
        raise Problem(403, 'Unknown or unpaired peer')
    verify_crossing(json.loads(peer['card']), value)
    now = store.clock()
    if abs(value['at'] - now) > 300:
        raise Problem(403, CLOCKS_DIFFER)
    if not federation.take_nonce(origin, value['nonce'], value['at'], now):
        raise Problem(409, 'Replay')
    with store.reading() as db:
        if contact_current(db, origin, value['receiver_ship']) is None:
            raise Problem(403, NOT_CONTACT)
    try:
        settings = load_settings(store.data_dir)
    except SettingsInvalid as error:
        log.error('crossings.toml refused, so every crossing is refused: %s', error)
        raise Problem(503, 'Crossings are not configured on this peer') from None
    house = published_house(store, settings, value['publisher_ship'])
    if house is None:
        raise Problem(404, 'No published house for that ship')
    return _answer(federation, value, house)


def _answer(federation, value, house):
    """The daemon call, the answer and its `crossings` row (plan P7): Task 4."""
    raise Problem(503, 'Crossings are not answered yet')
