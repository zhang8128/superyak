"""Store-copy imprints on the station (spec I 7, 8, 12; plan Task 23): the request and receipt tables, and the receipts'
hash chain. A receipt names what happened and never what the store holds, so each event's detail keys are listed once,
in DETAIL_KEYS (R25), and a receipt holding any other key is refused."""
import hashlib
import json
import os
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from .auth import token_hash
from .common import Problem, uid
from .identity import canonical, parse
from .ships import CODE_ALPHABET

IMPRINT_SCHEMA = '''
CREATE TABLE IF NOT EXISTS imprint_requests(id TEXT PRIMARY KEY, imprint_id TEXT UNIQUE NOT NULL,
  ship_id TEXT NOT NULL REFERENCES users(id), owner_id TEXT NOT NULL REFERENCES users(id), status TEXT NOT NULL,
  code_hash TEXT, created INTEGER NOT NULL, expires INTEGER NOT NULL, decided_at INTEGER, decided_by TEXT,
  ended_at INTEGER, request_sha256 TEXT NOT NULL, source_instance_id TEXT NOT NULL, imprints_root TEXT,
  permission TEXT, permission_signature TEXT, station_key TEXT, delete_reason TEXT);
CREATE TABLE IF NOT EXISTS imprint_receipts(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
  request_id TEXT NOT NULL REFERENCES imprint_requests(id), record TEXT NOT NULL, signature TEXT);
'''

STATUSES = ('requested', 'allowed', 'received', 'approved', 'admitted', 'deleting', 'deleted', 'declined', 'expired')
DELETE_REASONS = ('denied', 'failed', 'withdrawn', 'ended', 'upload-expired', 'review-expired', 'station', 'missing',
                  'restore')

_USE = frozenset({'use', 'use_id', 'actions', 'purpose', 'objects'})
_FINISHED = _USE | {'end'}
_REFUSED = frozenset({'use', 'actions', 'purpose', 'term'})
# An event's detail keys must equal one of its sets.
DETAIL_KEYS: dict[str, tuple[frozenset[str], ...]] = {
    'received': (frozenset({'bytes', 'sha256', 'parts', 'manifest_sha256'}),),
    'approved': (frozenset(),),
    'denied': (frozenset(), frozenset({'term'})),
    'admitted': (frozenset({'checks', 'report_sha256', 'skipped', 'roads_and_trails', 'sessions_too_large'}),),
    'failed': (frozenset({'step', 'message'}), frozenset({'term'})),
    'use-started': (_USE,),
    'use-finished': (_FINISHED, _FINISHED | {'report_sha256'}, _FINISHED | {'reason'}, _FINISHED | {'exit'},
                     _FINISHED | {'error'}),
    'refused': (_REFUSED, _REFUSED | {'roads_and_trails'}),
    'shortened': (frozenset({'valid_until'}),),
    'withdrawn': (frozenset(),),
    'ended': (frozenset(),),
    'deleted': (frozenset({'reason', 'files', 'limits'}),),
    'delete-failed': (frozenset({'path', 'error'}),),
}
EVENTS = tuple(DETAIL_KEYS)

PART_SIZE = 4_194_304
LARGEST_PACKAGE = 2 * 2**30
LIVE_BYTES = 16 * 2**30
FREE_FLOOR = 4 * 2**30
OPEN_PER_SHIP = 4
CODE_LIFE = 600
MAX_REQUEST_BODY = 64 * 1024
MAX_MEMORIES = 100_000
MAX_COUNT = 2**53
# A request that has not ended: it holds its source's one place (D20) and its bytes.
LIVE_STATUSES = ('requested', 'allowed', 'received', 'approved', 'admitted', 'deleting')
OPEN_STATUSES = ('requested', 'allowed', 'received', 'approved')

_UUID4 = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')
_ANY_UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
_DIGEST = re.compile(r'[0-9a-f]{64}')
_TIME = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ')
_PERSON = re.compile(r'[a-z][a-z0-9-]{0,62}')
_TABLES = ('episodes', 'semantics', 'episode_vectors', 'semantic_vectors', 'semantic_sources', 'resonances',
           'semantic_peers', 'subdivision_events', 'memory_log', 'operation_log', 'imprint_subjects')
_TOP = ('kind', 'version', 'imprint_id', 'plan_digest', 'source_instance_id', 'source_ancestry',
        'source_ancestry_complete', 'scope', 'contents', 'others', 'package', 'terms')
_SCOPE = ('lanes', 'layers', 'since', 'until', 'shared_with', 'unsourced_semantics')


def free_bytes(path):
    return shutil.disk_usage(path).free


def _bad(field):
    return Problem(400, f'Invalid imprint request: {field}')


def _count(value):
    return type(value) is int and 0 <= value <= MAX_COUNT


def _keys(value, names, field):
    if not isinstance(value, dict) or set(value) != set(names):
        raise _bad(field)
    return value


def _choice(value, allowed, field):
    """A non-empty list that is sorted, distinct and within `allowed`."""
    if (not isinstance(value, list) or not value or any(not isinstance(v, str) for v in value)
            or value != sorted(set(value)) or not set(value) <= set(allowed)):
        raise _bad(field)
    return value


def _time(value, field, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise _bad(field)
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        raise _bad(field) from None


def check_request(doc, *, super_admin, owner_username):
    """Every rule of spec I 14 for POST /api/imprints, with R14 (`until` is required). Returns `doc`; a refusal is
    Problem(400) with a fixed message naming the field."""
    _keys(doc, _TOP, 'request')
    if doc['kind'] != 'engram-imprint-request':
        raise _bad('kind')
    if type(doc['version']) is not int or doc['version'] != 1:
        raise _bad('version')
    if not isinstance(doc['imprint_id'], str) or not _UUID4.fullmatch(doc['imprint_id']):
        raise _bad('imprint_id')
    source = doc['source_instance_id']
    if not isinstance(source, str) or not _ANY_UUID.fullmatch(source):
        raise _bad('source_instance_id')
    ancestry = doc['source_ancestry']
    if (not isinstance(ancestry, list) or len(ancestry) > 64
            or any(not isinstance(a, str) or not _ANY_UUID.fullmatch(a) or a == source for a in ancestry)
            or len(set(ancestry)) != len(ancestry)):
        raise _bad('source_ancestry')
    if type(doc['source_ancestry_complete']) is not bool:
        raise _bad('source_ancestry_complete')
    if not isinstance(doc['plan_digest'], str) or not _DIGEST.fullmatch(doc['plan_digest']):
        raise _bad('plan_digest')

    scope = _keys(doc['scope'], _SCOPE, 'scope')
    _choice(scope['lanes'], ('personal', 'work'), 'scope.lanes')
    _choice(scope['layers'], ('episode', 'semantic'), 'scope.layers')
    since = _time(scope['since'], 'scope.since')
    until = _time(scope['until'], 'scope.until', required=True)
    if since is not None and not since < until:
        raise _bad('scope.since')
    shared = scope['shared_with']
    if shared is not None and (not isinstance(shared, str) or not shared.strip() or len(shared) > 200):
        raise _bad('scope.shared_with')
    if type(scope['unsourced_semantics']) is not bool:
        raise _bad('scope.unsourced_semantics')

    terms = _keys(doc['terms'], ('audience', 'actions', 'purposes', 'days'), 'terms')
    if (not _PERSON.fullmatch(owner_username) or not _PERSON.fullmatch(super_admin)
            or terms['audience'] != [f'place:home/{super_admin}']):
        raise _bad('terms.audience')
    actions = _choice(terms['actions'], ('imprint', 'route'), 'terms.actions')
    if 'imprint' not in actions:
        raise _bad('terms.actions')
    route = 'route' in actions
    if terms['purposes'] != (['calibration', 'trail-evaluation'] if route else ['calibration']):
        raise _bad('terms.purposes')
    if type(terms['days']) is not int or not 1 <= terms['days'] <= 365:
        raise _bad('terms.days')

    contents = doc['contents']
    if not isinstance(contents, dict) or not set(contents) <= set(_TABLES):
        raise _bad('contents')
    if any(type(n) is not int or not 1 <= n <= MAX_COUNT for n in contents.values()):
        raise _bad('contents')
    shipped = contents.get('episodes', 0) + contents.get('semantics', 0)
    if shipped > MAX_MEMORIES or (not route and ('memory_log' in contents or 'operation_log' in contents)):
        raise _bad('contents')

    others = _keys(doc['others'], ('memories', 'people'), 'others')
    memories, people = others['memories'], others['people']
    if not _count(memories) or not _count(people):
        raise _bad('others')
    rows = contents.get('imprint_subjects', 0)
    if rows == 0:
        carried = memories == 0 and people == 0
    else:
        carried = 1 <= memories <= min(shipped, rows) and 1 <= people <= rows
    if not carried:
        raise _bad('others')
    if rows and terms['audience'] != [f'place:home/{owner_username}']:
        raise _bad('others')

    package = _keys(doc['package'], ('bytes', 'parts'), 'package')
    if not _count(package['bytes']) or package['bytes'] > LARGEST_PACKAGE:
        raise _bad('package.bytes')
    if not _count(package['parts']) or package['parts'] != -(-package['bytes'] // PART_SIZE):
        raise _bad('package.parts')
    return doc


class Imprints:
    def _append_imprint_receipt(self, db, request_id, event, actor_id, detail, *, sign):
        """Appends one receipt to the permission's chain inside the caller's transaction (BEGIN IMMEDIATE, so two
        writers cannot both read the same last receipt). `previous` is the SHA-256 of the last receipt's canonical
        record, or of the permission record for the first. Signs only when `sign`. Returns the record."""
        if event not in DETAIL_KEYS:
            raise ValueError(f'Unknown imprint receipt event {event!r}')
        if not isinstance(detail, dict) or frozenset(detail) not in DETAIL_KEYS[event]:
            raise ValueError(f'A {event} receipt holds only the detail keys its row names')
        request = db.execute('SELECT permission FROM imprint_requests WHERE id=?', (request_id,)).fetchone()
        if request is None or request['permission'] is None:
            raise ValueError('No such imprint permission')
        permission = json.loads(request['permission'])
        last = db.execute('SELECT record FROM imprint_receipts WHERE request_id=? ORDER BY seq DESC LIMIT 1',
                          (request_id,)).fetchone()
        previous = json.loads(last['record']) if last else permission
        record = {'kind': 'imprint-receipt', 'station': permission['station'], 'id': uid(), 'permission': request_id,
                  'event': event, 'actor_id': actor_id, 'at': int(self.clock()), 'detail': detail,
                  'previous': hashlib.sha256(canonical(previous)).hexdigest()}
        signature = self._station_identity(db).sign_record(record) if sign else None
        db.execute('INSERT INTO imprint_receipts(id, request_id, record, signature) VALUES(?,?,?,?)',
                   (record['id'], request_id, canonical(record).decode(), signature))
        return record

    def imprint_receipts(self, request_id):
        """The permission's receipts in chain order: {seq, record, signature}."""
        with self.transaction() as db:
            return [{'seq': row['seq'], 'record': json.loads(row['record']), 'signature': row['signature']}
                    for row in db.execute('SELECT seq, record, signature FROM imprint_receipts WHERE request_id=? '
                                          'ORDER BY seq', (request_id,))]

    def _imprint_operator(self, db):
        row = db.execute('SELECT username FROM users WHERE is_super_admin=1 AND activation_pending=0 '
                         'ORDER BY created, rowid LIMIT 1').fetchone()
        if row is None:
            raise Problem(409, 'This station has no super admin')
        return row['username']

    def _live_imprint_bytes(self, db, staging):
        """Bytes held by requests that have not ended: from the staged request while it exists, else from the
        `received` receipt (the row itself holds no counts)."""
        marks = ','.join('?' * len(LIVE_STATUSES))
        total = 0
        for row in db.execute(f'SELECT id FROM imprint_requests WHERE status IN ({marks})', LIVE_STATUSES).fetchall():
            try:
                total += json.loads((staging / row['id'] / 'request.json').read_bytes())['package']['bytes']
                continue
            except (OSError, ValueError, KeyError, TypeError):
                pass
            for receipt in db.execute('SELECT record FROM imprint_receipts WHERE request_id=?', (row['id'],)):
                record = json.loads(receipt['record'])
                if record['event'] == 'received':
                    total += record['detail']['bytes']
        return total

    def create_imprint_request(self, ship_id, raw, *, staging, root=None):
        """A ship's request (I 7.1): parsed, checked and limited, kept in `staging/<request id>/request.json` (0700,
        0600), with a row in status `requested` and the hash of its 8-character confirm code. `root` is the imprints
        root; an imprint directory already there under the same id refuses the request."""
        staging = Path(staging)
        doc = parse(raw)
        with self.transaction() as db:
            ship = db.execute("SELECT owner_id FROM users WHERE id=? AND kind='ship'", (ship_id,)).fetchone()
            if ship is None:
                raise Problem(403, 'Only a ship key can use this route')
            owner = db.execute('SELECT username FROM users WHERE id=?', (ship['owner_id'],)).fetchone()['username']
            check_request(doc, super_admin=self._imprint_operator(db), owner_username=owner)
            source, imprint_id, size = doc['source_instance_id'], doc['imprint_id'], doc['package']['bytes']
            if db.execute('SELECT 1 FROM imprint_requests WHERE imprint_id=?', (imprint_id,)).fetchone() or (
                    root is not None and (Path(root) / imprint_id).exists()):
                raise Problem(409, 'This imprint id is already used')
            marks = ','.join('?' * len(LIVE_STATUSES))
            if db.execute(f'SELECT 1 FROM imprint_requests WHERE source_instance_id=? AND status IN ({marks})',
                          (source, *LIVE_STATUSES)).fetchone():
                raise Problem(409, 'This store already has a live imprint on this station; withdraw it first')
            marks = ','.join('?' * len(OPEN_STATUSES))
            if db.execute(f'SELECT count(*) FROM imprint_requests WHERE ship_id=? AND status IN ({marks})',
                          (ship_id, *OPEN_STATUSES)).fetchone()[0] >= OPEN_PER_SHIP:
                raise Problem(429, 'This ship has too many open imprint requests')
            staging.mkdir(mode=0o700, exist_ok=True)
            if (free_bytes(staging) - 3 * size < FREE_FLOOR
                    or self._live_imprint_bytes(db, staging) + size > LIVE_BYTES):
                raise Problem(507, 'This station has no room for that imprint')
            now = int(self.clock())
            request_id, code = uid(), ''.join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            body = canonical(doc)
            folder = staging / request_id
            folder.mkdir(mode=0o700)
            try:
                fd = os.open(folder / 'request.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(body)
                db.execute('INSERT INTO imprint_requests(id, imprint_id, ship_id, owner_id, status, code_hash, created, '
                           'expires, request_sha256, source_instance_id) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (request_id, imprint_id, ship_id, ship['owner_id'], 'requested', token_hash(code), now,
                            now + CODE_LIFE, hashlib.sha256(body).hexdigest(), source))
            except BaseException:
                shutil.rmtree(folder, ignore_errors=True)
                raise
            return {'id': request_id, 'code': code, 'expires': now + CODE_LIFE, 'imprint_short': imprint_id[:4],
                    'request_short': request_id[:4]}

    def imprint_context(self, ship_id):
        """What a ship needs to ask for a copy: its name, its owner's, the operator's, the station's id, and its
        imprints (R7)."""
        with self.transaction() as db:
            ship = db.execute("SELECT username, owner_id FROM users WHERE id=? AND kind='ship'", (ship_id,)).fetchone()
            if ship is None:
                raise Problem(403, 'Only a ship key can use this route')
            owner = db.execute('SELECT username FROM users WHERE id=?', (ship['owner_id'],)).fetchone()['username']
            return {'ship': ship['username'], 'owner': owner, 'operator': self._imprint_operator(db),
                    'station': self._station_identity(db).peer_id,
                    'imprints': self._list_imprints(db, 'ship_id', ship_id)}

    def list_imprints(self, user_id):
        """The imprints of the ships a person owns, newest first. Content-free."""
        with self.transaction() as db:
            return self._list_imprints(db, 'owner_id', user_id)

    def _list_imprints(self, db, column, value):
        rows = db.execute(f'SELECT r.id, r.imprint_id, r.status, r.created, r.expires, r.decided_at, r.ended_at, '
                          f'r.delete_reason, u.username AS ship FROM imprint_requests r JOIN users u ON u.id=r.ship_id '
                          f'WHERE r.{column}=? ORDER BY r.created DESC, r.rowid DESC', (value,)).fetchall()
        return [dict(row) for row in rows]
