"""Store-copy imprints on the station (spec I 7, 8, 12; plan Task 23): the request and receipt tables, and the receipts'
hash chain. A receipt names what happened and never what the store holds, so each event's detail keys are listed once,
in DETAIL_KEYS (R25), and a receipt holding any other key is refused."""
import base64
import copy
import errno
import fcntl
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from .auth import token_hash
from .common import Problem, uid
from .identity import canonical, parse
from .ships import CODE_ALPHABET

log = logging.getLogger(__name__)

IMPRINT_SCHEMA = '''
CREATE TABLE IF NOT EXISTS imprint_requests(id TEXT PRIMARY KEY, imprint_id TEXT UNIQUE NOT NULL,
  ship_id TEXT NOT NULL REFERENCES users(id), owner_id TEXT NOT NULL REFERENCES users(id), status TEXT NOT NULL,
  code_hash TEXT, created INTEGER NOT NULL, expires INTEGER NOT NULL, decided_at INTEGER, decided_by TEXT,
  ended_at INTEGER, request_sha256 TEXT NOT NULL, source_instance_id TEXT NOT NULL, imprints_root TEXT,
  permission TEXT, permission_signature TEXT, station_key TEXT, delete_reason TEXT);
CREATE TABLE IF NOT EXISTS imprint_receipts(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
  request_id TEXT NOT NULL REFERENCES imprint_requests(id), record TEXT NOT NULL, signature TEXT);
'''

STATION_NAME = 'Deep Space 9'
PERMISSION_LIFE = 7 * 86400
TIMES_WORDS = ('Each memory keeps when it was written. Each episode keeps how often and when last it was recalled. '
               'Resonances, pairs of memories recalls returned together, keep when they formed and when either was '
               'last recalled. These show when memories were recalled together.')
KEEPS_WORDS = ('If you allow, the station keeps this permission, its receipts and a row with the ids, your ship and the '
               'times (no memory content) until 400 days after the copy is deleted, then removes them all. Its nightly '
               'backups keep copies of them for about 8 weeks more, longer if the Pi was off, and also off the Pi if an '
               'off-Pi copy is set up. If you decline, it keeps only that row, with no scope or counts, for 30 days. '
               'Nothing is kept with no end.')
OTHERS_AT_HOME_WORDS = ('{n} of these memories have other people recorded on them ({p} people). They will be copied, '
                        'and each keeps those people as co-subjects, so no use of it outside your home, and none that '
                        'shows it to an agent, can happen without their yes. Other memories may mention people Engram '
                        'has no record of, such as family, colleagues, patients or study participants. They are copied '
                        'too, on your yes alone, with no one else recorded on them.')
OTHERS_AT_HOME_NONE_WORDS = ('Engram has no record of the people these memories mention, so no one but you is recorded '
                             'on them. Memories that mention family, colleagues, patients or study participants are '
                             'copied too, on your yes alone.')
OTHERS_AWAY_WORDS = ('Memories with other people recorded on them stay on your machine. Other memories may mention '
                     'people Engram has no record of. They leave on your yes.')
CHECK_TEXT = ("Nothing I am sending is about another person who hasn't agreed to share it, and none of it is patient "
              "or participant data.")
CHECK_ADVICE = "If you can't confirm this, don't allow. Narrow the plan on your machine, or stop."
CHECK_TEXT_AT_HOME = ('I know these memories may be about other people, such as family, colleagues, patients or study '
                      'participants. {n} of them have other people recorded on them ({p} people). They are copied with '
                      'those people as co-subjects, so no use of them outside my home, and none that shows them to an '
                      'agent, can happen without their yes. Other memories may mention people Engram has no record of. '
                      'They are copied on my yes alone, with no one else recorded on them.')
CHECK_TEXT_AT_HOME_NONE = ('I know these memories may be about other people, such as family, colleagues, patients or '
                           'study participants. Engram has no record of the people they mention, so no one but me is '
                           'recorded on them. They are copied on my yes alone.')
ACTIONS_WORDS = 'recall, read and imprint on these memories'
ROUTE_WORDS = ('; for the trail evaluation, keeping which session wrote each memory and the recall log, which make your '
               'trails, and route over their roads and trails')
NO_ROUTE_WORDS = 'which session wrote each memory, and the recall log, stay on your machine'

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
    'delete-failed': (frozenset({'path', 'error'}), frozenset({'path', 'error', 'files'})),
}
EVENTS = tuple(DETAIL_KEYS)

# The admission unit's RuntimeMaxSec=3600 plus its TimeoutStopSec=60 (R24; I 10, "Time"): after this a unit is gone.
ADMISSION_BOUND = 3660
# A use's RuntimeMaxSec=1800 counts from the unit's start, before `use-started`; SIGKILL follows after TimeoutStopSec=60.
USE_BOUND = 1860
ADMISSION_STOPPED = ('Admission stopped before it wrote a result: it reached its memory or time limit, or the station '
                     'stopped. Nothing was admitted; send it again.')

KNOWN_LIMITS = 'Files removed. The station does not overwrite disk blocks, and cannot reach copies anyone made by hand.'

PART_SIZE = 4_194_304
LARGEST_PACKAGE = 2 * 2**30
LIVE_BYTES = 16 * 2**30
FREE_FLOOR = 4 * 2**30
OPEN_PER_SHIP = 4
CODE_LIFE = 600
MAX_REQUEST_BODY = 64 * 1024
MAX_MANIFEST = 256 * 1024
PARTS_PER_MINUTE = 120
REVIEW_WINDOW = 7 * 86400
SIGN_INTERVAL = 60      # seconds between the lighthouse's passes over receipts a key-less command wrote
KEEP_DAYS = 400         # D32: a deleted imprint's row, permission, receipts and tombstone
DECLINED_KEEP_DAYS = 30    # D32: a declined or expired request's row
SWEEP_BATCH = 100       # I 12, D42: the sweep reads rows 100 at a time
HAND_OFF_GRACE = 600    # seconds an approved row may lack its directory while its hand-off runs after the commit
MAX_REPORT_BYTES = 8 * 2**20
COPY_BUFFER = 1024 * 1024
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


_COMMIT = re.compile(r'[0-9a-f]{7,64}')
_MANIFEST_TOP = ('kind', 'version', 'imprint_id', 'filter', 'plan_digest', 'request_sha256', 'built_at', 'engram_commit',
                 'source', 'schema', 'embedding', 'vec', 'scope', 'contents', 'others', 'package')
_part_times: dict = {}
_part_lock = threading.Lock()


def _no_floats(value):
    if isinstance(value, float):
        raise _bad('manifest')
    if isinstance(value, dict):
        for item in value.values():
            _no_floats(item)
    elif isinstance(value, list):
        for item in value:
            _no_floats(item)


def check_manifest(man, request):
    """I 7.2 and I 14: the manifest's own formats, and every field it shares with the request equal to it (`scope`,
    `contents`, `others`, `imprint_id`, `plan_digest`, the source's id and ancestry, `package.bytes`, the number of
    parts, and `request_sha256`, the request's hash). Raises Problem(400) and keeps nothing."""
    man = _keys(man, _MANIFEST_TOP, 'manifest')
    _no_floats(man)
    if man['kind'] != 'engram-imprint-manifest' or man['version'] != 1 or type(man['version']) is not int:
        raise _bad('kind')
    if man['filter'] != 'imprint-filter-v1':
        raise _bad('filter')
    shared = {'imprint_id': request['imprint_id'], 'plan_digest': request['plan_digest'],
              'request_sha256': hashlib.sha256(canonical(request)).hexdigest()}
    for name, expected in shared.items():
        if man[name] != expected:
            raise _bad(name)
    _time(man['built_at'], 'built_at', required=True)
    if man['engram_commit'] is not None and not (isinstance(man['engram_commit'], str)
                                                 and _COMMIT.fullmatch(man['engram_commit'])):
        raise _bad('engram_commit')
    source = _keys(man['source'], ('instance_id', 'identity', 'ancestry', 'ancestry_complete'), 'source')
    if source['instance_id'] != request['source_instance_id']:
        raise _bad('source.instance_id')
    if source['identity'] not in ('present', 'derived'):
        raise _bad('source.identity')
    ancestry = source['ancestry']
    if (not isinstance(ancestry, list) or len(ancestry) > 64
            or not all(isinstance(a, str) and _ANY_UUID.fullmatch(a) for a in ancestry)
            or ancestry != request['source_ancestry']):
        raise _bad('source.ancestry')
    if source['ancestry_complete'] is not request['source_ancestry_complete']:
        raise _bad('source.ancestry_complete')
    applied = _keys(man['schema'], ('applied',), 'schema')['applied']
    if not isinstance(applied, list) or len(applied) > 1000 or not all(type(a) is int and a >= 0 for a in applied):
        raise _bad('schema.applied')
    embedding = _keys(man['embedding'], ('model', 'dimension'), 'embedding')
    if not isinstance(embedding['model'], str) or not 1 <= len(embedding['model']) <= 200 \
            or type(embedding['dimension']) is not int or not 1 <= embedding['dimension'] <= 65536:
        raise _bad('embedding')
    version = _keys(man['vec'], ('create_version',), 'vec')['create_version']
    if not isinstance(version, str) or not 1 <= len(version) <= 64:
        raise _bad('vec')
    for name in ('scope', 'contents', 'others'):
        if man[name] != request[name]:
            raise _bad(name)
    package = _keys(man['package'], ('file', 'bytes', 'sha256', 'part_bytes', 'parts'), 'package')
    if package['file'] != 'imprint.db' or package['part_bytes'] != PART_SIZE or type(package['part_bytes']) is not int:
        raise _bad('package')
    if type(package['bytes']) is not int or package['bytes'] != request['package']['bytes']:
        raise _bad('package.bytes')
    if not isinstance(package['sha256'], str) or not _DIGEST.fullmatch(package['sha256']):
        raise _bad('package.sha256')
    parts = package['parts']
    if (not isinstance(parts, list) or len(parts) != request['package']['parts']
            or not all(isinstance(h, str) and _DIGEST.fullmatch(h) for h in parts)):
        raise _bad('package.parts')


def _copy_part(src, dst):
    """Streams one part file into the open file `dst` through a 1 MiB buffer."""
    with open(src, 'rb') as stream:
        while block := stream.read(COPY_BUFFER):
            dst.write(block)


class _Sum:
    """Wraps the open temporary file so the join hashes what it writes, with no second read."""
    def __init__(self, stream):
        self.stream, self.digest, self.size = stream, hashlib.sha256(), 0

    def write(self, block):
        self.digest.update(block)
        self.size += len(block)
        return self.stream.write(block)


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _out_of_space(error):
    return Problem(507, 'The station is out of disk space; nothing was kept. Run make imprint-send again later.') \
        if error.errno == errno.ENOSPC else error


@contextmanager
def _folder_lock(folder):
    """An exclusive lock on the request's staging directory, never waited for: a second writer is told to retry. It
    keeps a part, the join and a restart's leftovers from meeting."""
    fd = os.open(folder, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Problem(409, 'This imprint is being written; try again in a moment') from None
        yield
    finally:
        os.close(fd)


def _write_file(path, data):
    """Writes `data` to `path` through `path.tmp`: 0600, fsynced, renamed, the directory fsynced."""
    temporary = path.with_name(path.name + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    except BaseException as error:
        temporary.unlink(missing_ok=True)
        raise (_out_of_space(error) if isinstance(error, OSError) else error) from None


def _held(folder):
    return sorted(int(m.group(1)) for m in (re.fullmatch(r'part-(\d+)', p.name) for p in folder.iterdir()) if m)


def _filled(words, others):
    text = words.format(n=others['memories'], p=others['people'])
    return text.replace('(1 people)', '(1 person)')


def _mib(size):
    return f'{size / 2**20:.1f} MiB'


def _stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def permission_record(*, station, request_id, owner, owner_id, ship_id, request, request_sha256, now):
    """I 8's imprint-permission: r_M, and with `route` r_T. The attestation follows the stored request's owner and
    audience and never the browser (D27). Every list is sorted; ids are `r-` and 32 random hex."""
    terms, imprint_id, source = request['terms'], request['imprint_id'], request['source_instance_id']
    route = 'route' in terms['actions']
    at_home = terms['audience'] == [f'place:home/{owner}']
    ends = now + terms['days'] * 86400

    def inner(kinds, objects, actions, purposes):
        return {'id': 'r-' + secrets.token_hex(16), 'layer': f'place:home/{owner}', 'effect': 'allow',
                'selector': {'audience': sorted(terms['audience']), 'requesters': ['agent:station-imprints'],
                             'objects': {'kinds': kinds, 'stores': [source], 'layers': '*', 'lanes': '*',
                                         'collections': '*', 'memories': '*', **objects},
                             'actions': sorted(actions), 'purposes': sorted(purposes)},
                'valid_from': now, 'valid_until': ends, 'anchor': now, 'backing': 'person', 'set_by': f'person:{owner}',
                'channel': 'browser', 'under_grant': None, 'proposal_id': None, 'replaces': None,
                'reason': f'imprint {imprint_id[:4]} at {STATION_NAME}', 'created': now}

    records = [inner(['memory'], {'collections': [f'collection:{owner}/imprint-{imprint_id}']},
                     ['imprint', 'read', 'recall'], ['calibration', 'trail-evaluation'] if route else ['calibration'])]
    if route:
        records.append(inner(['road', 'trail'], {}, ['imprint', 'read', 'recall', 'route'], ['trail-evaluation']))
    return {'kind': 'imprint-permission', 'station': station, 'id': request_id, 'owner': f'person:{owner}',
            'owner_id': owner_id, 'ship_id': ship_id, 'imprint_id': imprint_id, 'source_instance_id': source,
            'request_sha256': request_sha256, 'plan_digest': request['plan_digest'],
            'attestation': 'others-copied-at-home-v1' if at_home else 'no-unconsented-others-v1',
            'created': now, 'records': records}


CEILING = frozenset({('recall', 'calibration'), ('read', 'calibration'), ('imprint', 'calibration'),
                     ('recall', 'trail-evaluation'), ('read', 'trail-evaluation'), ('imprint', 'trail-evaluation'),
                     ('route', 'trail-evaluation')})
AGENT = 'agent:station-imprints'
_STATUS_OF = {'admission': 'approved', 'trail-evaluation': 'admitted'}
_RECORD_KINDS = {'memory': ('memory',), 'road-or-trail': ('road', 'trail')}
_RANK = {'audience': 0, 'requester': 1, 'action': 2, 'purpose': 3}


def need(kind, *, route):
    """I 8's Need(admission, t) and Need(trail-evaluation, t) as (object kind, action, purpose): the object kind is
    `memory` or `road-or-trail`. Only admission reads `route`: R(I) is empty without it."""
    if kind == 'admission':
        out = {('memory', a, 'calibration') for a in ('recall', 'read', 'imprint')}
        if route:
            out |= {('road-or-trail', a, 'trail-evaluation') for a in ('recall', 'read', 'imprint')}
            out |= {('memory', a, 'trail-evaluation') for a in ('recall', 'read')}
        return frozenset(out)
    if kind == 'trail-evaluation':
        return frozenset({('memory', 'recall', 'trail-evaluation'), ('memory', 'read', 'trail-evaluation'),
                          ('road-or-trail', 'route', 'trail-evaluation')})
    raise ValueError(f'Unknown imprint use kind {kind!r}')


def _shortenings(receipts, by=None):
    return [r['detail']['valid_until'] for r in receipts
            if r['event'] == 'shortened' and (by is None or r.get('actor_id') == by)]


def effective_end(permission, receipts):
    """The earliest of the records' `valid_until` and every `shortened` receipt's, by the owner or the ship (I 8,
    item 4). A shortening only narrows: a later time changes nothing."""
    return min([r['valid_until'] for r in permission['records']] + _shortenings(receipts))


def owner_layer(imprints, *, owner_id):
    """The owner's layer at the station (I 8): every inner record of the owner's imprints, less those the owner
    withdrew, each `valid_until` cut by the owner's own shortenings. The ship's withdrawal revokes nothing of the
    owner's, and its shortening narrows the ceiling only. `imprints` holds (permission, receipts) pairs."""
    layer = []
    for permission, receipts in imprints:
        if permission['owner_id'] != owner_id:
            continue
        if any(r['event'] == 'withdrawn' and r.get('actor_id') == owner_id for r in receipts):
            continue
        cut = _shortenings(receipts, owner_id)
        for record in permission['records']:
            record = copy.deepcopy(record)
            record['valid_until'] = min([record['valid_until']] + cut)
            layer.append(record)
    return layer


@dataclass(frozen=True)
class UseDecision:
    allowed: bool
    term: str | None
    code: str | None
    valid_until: int
    records: tuple[str, ...]


def _holds(listed, value):
    return listed == '*' or value in listed


def _failing_stage(records, need_, source, home, t):
    """The first stage at which no one record speaks for `need_`, or None and the records that do. A record speaks
    when its stores, audience, requesters, kinds, action and purpose hold and `valid_from <= t < valid_until`. Records
    of other stores are not about this copy and are set aside first; an object kind or date no record covers is
    reported as `action`, the stage that asks what the record allows on this object."""
    kind, action, purpose = need_
    live = [r for r in records if _holds(r['selector']['objects']['stores'], source)]
    live = [r for r in live if _holds(r['selector']['audience'], home)]
    if not live:
        return 'audience', []
    live = [r for r in live if _holds(r['selector']['requesters'], AGENT)]
    if not live:
        return 'requester', []
    live = [r for r in live if r['valid_from'] <= t < r['valid_until']
            and all(_holds(r['selector']['objects']['kinds'], k) for k in _RECORD_KINDS[kind])]
    live = [r for r in live if _holds(r['selector']['actions'], action)]
    if not live:
        return 'action', []
    live = [r for r in live if _holds(r['selector']['purposes'], purpose)]
    if not live:
        return 'purpose', []
    return None, live


def decide_use(permission, receipts, owner_records, *, status, kind, t, operator, uses=None):
    """The station's check for one use of one copy (I 8, "The decision"): allowed exactly when Need is inside the
    owner's layer and inside this copy's ceiling. A refusal names the first failing term, in I 8's order. Item 6 is
    not read: every admitted imprint satisfies it by Task 24's request rule and check 12, and every step-1 use is in
    the operator's home. `uses` replaces `need` in tests only."""
    end = effective_end(permission, receipts)
    source, home = permission['source_instance_id'], f'place:home/{operator}'
    own = permission['records']

    def refuse(term):
        code = {'valid_from': 'NOT_YET', 'end': 'EXPIRED'}.get(term, 'NO_ALLOW')
        return UseDecision(False, term, code, end, ())

    if status != _STATUS_OF.get(kind):
        return refuse('status')
    if t < min(r['valid_from'] for r in own):
        return refuse('valid_from')
    if t >= end:
        return refuse('end')
    if any(r['event'] == 'withdrawn' and r['at'] <= t for r in receipts):
        return refuse('withdrawal')
    if uses is None:
        uses = need(kind, route=any('route' in r['selector']['actions'] for r in own))
    uses = list(uses)
    failed = [_failing_stage(owner_records, u, source, home, t)[0] for u in uses]
    failed = [s for s in failed if s]
    if failed:
        return refuse(min(failed, key=_RANK.__getitem__))
    used = set()
    for u in uses:
        stage, speaking = _failing_stage(own, u, source, home, t)
        if stage or (u[1], u[2]) not in CEILING:
            return refuse('ceiling')
        used.update(r['id'] for r in speaking)
    return UseDecision(True, None, None, end, tuple(r['id'] for r in own if r['id'] in used))


def _manifest_sha256(folder):
    """The package hash the folder's manifest names, or None when there is no readable manifest."""
    try:
        return json.loads((folder / 'manifest.json').read_bytes())['package']['sha256']
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _removed_files(folder, *, by_manifest=False):
    """The files under `folder`, each as {path, bytes, sha256}, for a `deleted` receipt (hashed 1 MiB at a time).
    With `by_manifest`, `imprint.db` takes the hash of its manifest, which admission verified (I 12, step 2)."""
    out = []
    if not folder.is_dir():
        return out
    for path in sorted(folder.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        known = _manifest_sha256(path.parent) if by_manifest and path.name == 'imprint.db' else None
        if known is not None:
            out.append({'path': str(path), 'bytes': path.stat().st_size, 'sha256': known})
            continue
        digest, size = hashlib.sha256(), 0
        with open(path, 'rb') as stream:
            while block := stream.read(COPY_BUFFER):
                digest.update(block)
                size += len(block)
        out.append({'path': str(path), 'bytes': size, 'sha256': digest.hexdigest()})
    return out


def _unlink(path):
    os.unlink(path)


def _restore_write(folder):
    """Gives the owner back write permission on a read-only tree, so its files can be removed."""
    for here, names, files in os.walk(folder):
        for name in (*names, *files):
            if not os.path.islink(os.path.join(here, name)):
                os.chmod(os.path.join(here, name), 0o700)
        os.chmod(here, 0o700)


def _replace_allow_files(state_dir, valid_until):
    """Rewrites `admission.json` and every `uses/*.allow.json` under a state directory with a new `valid_until`
    and nothing else changed (so `decided_at` stays), each atomically: a temporary file in the same directory,
    0400, then `os.replace`. A file that already ends no later is left alone."""
    state_dir = Path(state_dir)
    targets = [state_dir / 'admission.json', *sorted((state_dir / 'uses').glob('*.allow.json'))]
    for path in targets:
        if path.is_symlink() or not path.is_file():
            continue
        doc = json.loads(path.read_text())
        if not isinstance(doc.get('valid_until'), int) or doc['valid_until'] <= valid_until:
            continue
        doc['valid_until'] = valid_until
        folder = path.parent
        mode = folder.stat().st_mode
        if not mode & 0o200:        # a registered directory is read-only: open it for this one swap only
            folder.chmod(mode | 0o200)
        temporary = folder / f'.{path.name}.{secrets.token_hex(4)}.tmp'
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
            with os.fdopen(fd, 'wb') as out:
                out.write(json.dumps(doc, indent=2, sort_keys=True).encode() + b'\n')
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
            _fsync_dir(folder)
        finally:
            if temporary.exists():
                temporary.unlink()
            if not mode & 0o200:
                folder.chmod(mode)


def _read_json(path, limit=65536):
    """A small regular file's JSON object, or None for a missing, linked, large or unreadable one."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            return None
        doc = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _is_count(value):
    return type(value) is int and 0 <= value <= MAX_COUNT


def _read_result(path):
    """`result.json` from engram's admission, checked to the shapes the `admitted` and `failed` receipts take, or
    None: a malformed result is not a result, and the bound fails the admission if nothing better arrives."""
    doc = _read_json(path)
    if doc is None:
        return None
    if doc.get('status') == 'admitted':
        skipped = doc.get('skipped')
        if (doc.get('checks') == 17 and type(doc['checks']) is int and isinstance(doc.get('report_sha256'), str)
                and _DIGEST.fullmatch(doc['report_sha256']) and isinstance(skipped, list) and len(skipped) <= 1000
                and _is_count(doc.get('roads_and_trails')) and _is_count(doc.get('sessions_too_large'))):
            return doc
        return None
    if doc.get('status') == 'failed':
        step, message = doc.get('step'), doc.get('message')
        if (type(step) is int or isinstance(step, str) and len(step) <= 40) and isinstance(message, str) \
                and len(message) <= 1000:
            return doc
    return None


def _decided_at(path):
    """When admission began: `decided_at` in `admission.json`, else the file's own time (a damaged file still bounds
    the run). None when there is no file."""
    if not os.path.lexists(path):
        return None
    doc = _read_json(path)
    if doc is not None and _is_count(doc.get('decided_at')):
        return doc['decided_at']
    try:
        return int(os.lstat(path).st_mtime)
    except OSError:
        return None


class _RemovalFailed(Exception):
    pass


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

    def _owned_open_request(self, db, actor, *, code=None, request_id=None):
        """The `requested` row of a ship the actor owns, whose unexpired code matches (a 404 for anything else, so a
        stranger learns nothing), with its staged request."""
        if code is not None:
            if not isinstance(code, str) or not 1 <= len(code) <= 64:
                raise Problem(404, 'No such imprint request')
            found = db.execute('SELECT * FROM imprint_requests WHERE code_hash=?', (token_hash(code),)).fetchone()
        else:
            found = db.execute('SELECT * FROM imprint_requests WHERE id=?', (request_id,)).fetchone()
        if (found is None or found['owner_id'] != actor or found['status'] != 'requested'
                or (code is not None and found['expires'] <= self.clock())):
            raise Problem(404, 'No such imprint request')
        return found

    def _staged_request(self, found):
        try:
            raw = (self.data_dir / 'imprints' / found['id'] / 'request.json').read_bytes()
        except OSError:
            raise Problem(404, 'No such imprint request') from None
        if hashlib.sha256(raw).hexdigest() != found['request_sha256']:
            raise Problem(404, 'No such imprint request')
        return json.loads(raw)

    def imprint_preview(self, actor, code):
        """The confirm view's data (I 9): every field of the request in words, for the ship's owner only."""
        with self.transaction() as db:
            found = self._owned_open_request(db, actor, code=code)
            doc = self._staged_request(found)
            ship = db.execute('SELECT username FROM users WHERE id=?', (found['ship_id'],)).fetchone()['username']
            machine = db.execute('SELECT machine FROM dockings WHERE ship_id=? ORDER BY created DESC LIMIT 1',
                                 (found['ship_id'],)).fetchone()
            owner = db.execute('SELECT username FROM users WHERE id=?', (actor,)).fetchone()['username']
            operator = db.execute('SELECT username, name FROM users WHERE username=?',
                                  (self._imprint_operator(db),)).fetchone()
        scope, terms, others = doc['scope'], doc['terms'], doc['others']
        route, at_home = 'route' in terms['actions'], terms['audience'] == [f'place:home/{owner}']
        ancestry = [a[:4] for a in doc['source_ancestry']]
        if not ancestry and doc['source_ancestry_complete']:
            lineage = 'copied from no recorded store'
        else:
            lineage = 'lineage complete' if doc['source_ancestry_complete'] else 'lineage incomplete'
        if at_home and others['memories'] > 0:
            other_words, check = _filled(OTHERS_AT_HOME_WORDS, others), _filled(CHECK_TEXT_AT_HOME, others)
        elif at_home:
            other_words, check = OTHERS_AT_HOME_NONE_WORDS, CHECK_TEXT_AT_HOME_NONE
        else:
            other_words, check = OTHERS_AWAY_WORDS, CHECK_TEXT
        now = int(self.clock())
        return {
            'id': found['id'], 'ship': ship, 'machine': machine['machine'] if machine else None,
            'imprint_short': doc['imprint_id'][:4], 'request_short': found['id'][:4],
            'store': {'id': doc['source_instance_id'], 'copied_from': ancestry, 'lineage': lineage},
            'scope': {'lanes': scope['lanes'], 'layers': scope['layers'], 'since': scope['since'],
                      'until': scope['until'], 'shared_with': scope['shared_with'],
                      'unsourced_semantics': scope['unsourced_semantics']},
            'counts': doc['contents'], 'size': f"{_mib(doc['package']['bytes'])} in {doc['package']['parts']} parts",
            'audience': f"{terms['audience'][0]} (the station's imprint agent, acting for {operator['username']})",
            'actions': ACTIONS_WORDS + (ROUTE_WORDS if route else '') + ('' if route else '; ' + NO_ROUTE_WORDS),
            'purposes': terms['purposes'], 'times': TIMES_WORDS,
            'ends': _stamp(now + terms['days'] * 86400), 'days': terms['days'],
            'digest': f"{doc['plan_digest'][:8]} (the whole 64-character digest is sent)",
            'others': other_words, 'check': check, 'check_advice': None if at_home else CHECK_ADVICE,
            'keeps': KEEPS_WORDS,
            'closing': (f"This store is about you. Allow sends this copy to {STATION_NAME}. {operator['name']} then "
                        "decides whether the station takes it. You can withdraw it at any time, and it is deleted on "
                        "the end date."),
            'expires': found['expires']}

    def confirm_imprint(self, actor, request_id, *, code, password, attest, source):
        """The owner's yes (D1): the code, the ticked check and the password, counted as a login; then, in one
        transaction, the permission is built, signed and stored and the request is `allowed`."""
        with self.transaction() as db:
            self._owned_open_request(db, actor, code=code)
            found = db.execute('SELECT id FROM imprint_requests WHERE code_hash=?', (token_hash(code),)).fetchone()
            if found['id'] != request_id:
                raise Problem(404, 'No such imprint request')
            username = db.execute('SELECT username FROM users WHERE id=?', (actor,)).fetchone()['username']
        if attest is not True:
            raise Problem(400, 'Tick the box to confirm')
        if not self.check_password_attempt(username, password, source):
            raise Problem(401, 'Invalid password')
        with self.transaction() as db:
            found = self._owned_open_request(db, actor, code=code)
            if found['id'] != request_id:
                raise Problem(404, 'No such imprint request')
            doc = self._staged_request(found)
            now = int(self.clock())
            identity = self._station_identity(db)
            record = permission_record(station=identity.peer_id, request_id=request_id, owner=username, owner_id=actor,
                                       ship_id=found['ship_id'], request=doc, request_sha256=found['request_sha256'],
                                       now=now)
            signature = identity.sign_record(record)
            db.execute('UPDATE imprint_requests SET status=?, code_hash=NULL, decided_at=?, decided_by=?, expires=?, '
                       'permission=?, permission_signature=?, station_key=? WHERE id=?',
                       ('allowed', now, actor, now + PERMISSION_LIFE, canonical(record).decode(), signature,
                        base64.b64encode(identity.public_key).decode(), request_id))
            return {'id': request_id, 'status': 'allowed', 'imprint_short': doc['imprint_id'][:4],
                    'valid_until': record['records'][0]['valid_until'], 'expires': now + PERMISSION_LIFE}

    def decline_imprint(self, actor, request_id):
        """The owner's no: the staging directory goes at once; the row stays, with no scope or counts."""
        with self.transaction() as db:
            self._owned_open_request(db, actor, request_id=request_id)
            now = int(self.clock())
            db.execute("UPDATE imprint_requests SET status='declined', code_hash=NULL, decided_at=?, decided_by=?, "
                       "ended_at=? WHERE id=?", (now, actor, now, request_id))
            shutil.rmtree(self.data_dir / 'imprints' / request_id)
            return {'id': request_id, 'status': 'declined'}

    def _upload_row(self, db, ship_id, request_id):
        """The requesting ship's `allowed` row inside its upload window. Any other ship, or an id nobody has, gets a
        404 and learns nothing; the wrong status a 409."""
        found = db.execute('SELECT * FROM imprint_requests WHERE id=? AND ship_id=?',
                           (request_id, ship_id)).fetchone() if isinstance(request_id, str) else None
        if found is None:
            raise Problem(404, 'No such imprint request')
        if found['status'] != 'allowed':
            raise Problem(409, f'This imprint is {found["status"]}, not waiting for its upload')
        if found['expires'] <= self.clock():
            raise Problem(409, 'The upload window for this imprint has ended')
        return found

    def _staged_manifest(self, request_id):
        try:
            raw = (self.data_dir / 'imprints' / request_id / 'manifest.json').read_bytes()
        except OSError:
            raise Problem(409, 'Send the manifest first') from None
        return raw, json.loads(raw)

    def put_imprint_manifest(self, ship_id, request_id, raw):
        """The manifest (I 7.2), once, only in `allowed`, only if it agrees with the staged request. It is kept
        as `manifest.json`, canonical, and nothing is kept for a refused one."""
        if not isinstance(raw, bytes) or len(raw) > MAX_MANIFEST:
            raise Problem(413, 'Imprint manifest too large')
        with self.transaction() as db:
            found = self._upload_row(db, ship_id, request_id)
            folder = self.data_dir / 'imprints' / request_id
            if (folder / 'manifest.json').exists():
                raise Problem(409, 'This imprint already has its manifest')
            request = self._staged_request(found)
            man = parse(raw)
            if canonical(man) != raw:
                raise _bad('manifest (not canonical JSON)')
            check_manifest(man, request)
            _write_file(folder / 'manifest.json', raw)
            return {'manifest_sha256': hashlib.sha256(raw).hexdigest(), 'parts': len(man['package']['parts'])}

    def _count_part(self, ship_id):
        now = self.clock()
        with _part_lock:
            times = [t for t in _part_times.get(ship_id, ()) if t > now - 60]
            if len(times) >= PARTS_PER_MINUTE:
                _part_times[ship_id] = times
                raise Problem(429, 'Too many parts; wait a minute')
            times.append(now)
            _part_times[ship_id] = times

    def put_imprint_part(self, ship_id, request_id, n, data):
        """One 4 MiB part, only after the manifest and only if its length and SHA-256 are the manifest's. A part
        already held with that hash changes nothing. Returns the part numbers the station holds."""
        with self.transaction() as db:
            self._upload_row(db, ship_id, request_id)
        self._count_part(ship_id)
        _, man = self._staged_manifest(request_id)
        package = man['package']
        if type(n) is not int or not 0 <= n < len(package['parts']):
            raise Problem(404, 'No such part')
        if len(data) != min(PART_SIZE, package['bytes'] - n * PART_SIZE):
            raise Problem(400, 'This part is not the length the manifest gives')
        if hashlib.sha256(data).hexdigest() != package['parts'][n]:
            raise Problem(400, "This part's SHA-256 is not the manifest's")
        folder = self.data_dir / 'imprints' / request_id
        with _folder_lock(folder):
            path = folder / f'part-{n}'
            try:
                held = hashlib.sha256(path.read_bytes()).hexdigest() == package['parts'][n]
            except OSError:
                held = False
            if not held:
                _write_file(path, data)
            return {'held': _held(folder)}

    def complete_imprint(self, ship_id, request_id):
        """Joins the parts in order into `imprint.db`, streaming; checks its bytes and SHA-256; deletes the parts;
        sets `received` (the review window starts) and writes the signed `received` receipt. A join that fails
        leaves no partial file and the parts."""
        with self.transaction() as db:
            self._upload_row(db, ship_id, request_id)
        raw, man = self._staged_manifest(request_id)
        package, folder = man['package'], self.data_dir / 'imprints' / request_id
        count = len(package['parts'])
        if _held(folder) != list(range(count)):
            raise Problem(409, 'Not every part has arrived')
        with _folder_lock(folder):
            temporary = folder / 'imprint.db.tmp'
            temporary.unlink(missing_ok=True)       # a join a crash cut short
            try:
                with open(temporary, 'xb') as out:
                    os.chmod(temporary, 0o600)
                    joined = _Sum(out)
                    for n in range(count):
                        _copy_part(folder / f'part-{n}', joined)
                    out.flush()
                    os.fsync(out.fileno())
                if joined.size != package['bytes'] or joined.digest.hexdigest() != package['sha256']:
                    raise Problem(400, 'The joined parts are not the package the manifest names')
                os.replace(temporary, folder / 'imprint.db')
                _fsync_dir(folder)
            except BaseException as error:
                temporary.unlink(missing_ok=True)
                raise (_out_of_space(error) if isinstance(error, OSError) else error) from None
            try:
                with self.transaction() as db:
                    self._upload_row(db, ship_id, request_id)
                    now = int(self.clock())
                    db.execute("UPDATE imprint_requests SET status='received', expires=? WHERE id=?",
                               (now + REVIEW_WINDOW, request_id))
                    self._append_imprint_receipt(
                        db, request_id, 'received', ship_id,
                        {'bytes': joined.size, 'sha256': package['sha256'], 'parts': count,
                         'manifest_sha256': hashlib.sha256(raw).hexdigest()}, sign=True)
            except BaseException:
                (folder / 'imprint.db').unlink(missing_ok=True)
                raise
            for n in range(count):
                (folder / f'part-{n}').unlink(missing_ok=True)
            return {'status': 'received', 'expires': now + REVIEW_WINDOW}

    def sign_imprint_receipts(self):
        """Signs every receipt a key-less command left unsigned, in one transaction, by the station's identity (D19).
        Signing changes no record, so no chain depends on it. Returns how many it signed."""
        with self.transaction() as db:
            unsigned = db.execute('SELECT id, record FROM imprint_receipts WHERE signature IS NULL ORDER BY seq').fetchall()
            if not unsigned:
                return 0
            identity = self._station_identity(db)
            for receipt in unsigned:
                db.execute('UPDATE imprint_receipts SET signature=? WHERE id=? AND signature IS NULL',
                           (identity.sign_record(json.loads(receipt['record'])), receipt['id']))
            return len(unsigned)

    def imprint_status(self, actor, request_id):
        """The owner's or the requesting ship's view (a 404 for anyone else): `status`, `held`, the permission with its
        signature and the station's key, every receipt (unsigned ones with no signature), the content-free calibration
        report once admitted, each use's report, and what the station keeps with the date each thing goes (I 12)."""
        with self.transaction() as db:
            found = db.execute('SELECT * FROM imprint_requests WHERE id=?',
                               (request_id,)).fetchone() if isinstance(request_id, str) else None
            if found is None or actor not in (found['ship_id'], found['owner_id']):
                raise Problem(404, 'No such imprint request')
            rows = db.execute('SELECT seq, record, signature FROM imprint_receipts WHERE request_id=? ORDER BY seq',
                              (request_id,)).fetchall()
        folder = self.data_dir / 'imprints' / request_id
        out = {'status': found['status'], 'held': _held(folder) if folder.is_dir() else [], 'permission': None,
               'receipts': [{'seq': r['seq'], 'record': json.loads(r['record']), 'signature': r['signature']}
                            for r in rows],
               'calibration_report': None, 'use_reports': [], 'keeps': None}
        if found['permission'] is None:
            return out
        permission = json.loads(found['permission'])
        out['permission'] = {'record': permission, 'signature': found['permission_signature'],
                             'station_key': found['station_key']}
        records = [r['record'] for r in out['receipts']]
        ends = found['ended_at'] if found['status'] == 'deleted' and found['ended_at'] else effective_end(permission, records)
        removed = datetime.fromtimestamp(ends + KEEP_DAYS * 86400, timezone.utc).strftime('%Y-%m-%d')
        out['keeps'] = {'text': KEEPS_WORDS, 'removed_on': dict.fromkeys(('row', 'permission', 'receipts', 'tombstone'), removed)}
        state = self._imprint_state(found, None)
        if state is not None and found['status'] != 'deleted':
            if found['status'] == 'admitted':
                out['calibration_report'] = _read_json(state / 'calibration' / 'report.json', MAX_REPORT_BYTES)
            for started in [r for r in records if r['event'] == 'use-started']:
                use_id = started['detail']['use_id']
                report = _read_json(state / 'uses' / use_id / 'report.json', MAX_REPORT_BYTES)
                if report is not None:
                    out['use_reports'].append({'use_id': use_id, 'report': report})
        return out

    def _decide_imprint(self, username, item, approve, root):
        """Andy's decision on one `received` imprint (I 10): approval, then the hand-off, or a denial."""
        if root is None:
            raise Problem(409, 'Give --imprints-dir: the imprints root this station was started with')
        if not approve:
            with self.transaction() as db:
                actor = self._operator(db, username)
                found = self._received_row(db, item['id'])
                self._deny_imprint(db, found, actor, {}, 'denied')
            return item, {'status': 'deleted', 'imprint_id': found['imprint_id'], 'term': None}
        return item, self._approve_imprint(username, item['id'], Path(root))

    def _received_row(self, db, request_id):
        found = db.execute('SELECT * FROM imprint_requests WHERE id=?', (request_id,)).fetchone()
        if found is None or found['status'] != 'received':
            raise Problem(404, 'This imprint is no longer waiting')
        if found['expires'] <= self.clock():
            raise Problem(409, 'The review window for this imprint has ended')
        return found

    def _deny_imprint(self, db, found, actor, detail, reason):
        """Deletes the staged bytes and writes `denied` and `deleted`; the status becomes `deleted` at once."""
        staged = self.data_dir / 'imprints' / found['id']
        files = _removed_files(staged)
        self._append_imprint_receipt(db, found['id'], 'denied', actor, detail, sign=False)
        self._append_imprint_receipt(db, found['id'], 'deleted', actor,
                                     {'reason': reason, 'files': files, 'limits': KNOWN_LIMITS}, sign=False)
        now = int(self.clock())
        db.execute("UPDATE imprint_requests SET status='deleted', decided_at=?, decided_by=?, ended_at=?, "
                   "delete_reason=? WHERE id=?", (now, actor, now, reason, found['id']))
        if staged.exists():
            shutil.rmtree(staged)

    def _owner_layer_of(self, db, owner_id):
        pairs = []
        marks = ','.join('?' * len(LIVE_STATUSES))
        for row in db.execute(f'SELECT id, permission FROM imprint_requests WHERE owner_id=? AND permission IS NOT NULL '
                              f'AND status IN ({marks})', (owner_id, *LIVE_STATUSES)).fetchall():
            records = [json.loads(r['record']) for r in db.execute(
                'SELECT record FROM imprint_receipts WHERE request_id=? ORDER BY seq', (row['id'],))]
            pairs.append((json.loads(row['permission']), records))
        return owner_layer(pairs, owner_id=owner_id)

    def _approve_imprint(self, username, request_id, root):
        """Step 1 (one transaction): the use decision, then `approved` and the unsigned receipt, or a denial naming
        the term. Step 2, after the commit: the hand-off. A hand-off that fails leaves the row `approved` for the
        sweep to mark `missing`."""
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root = root.resolve()
        with self.transaction() as db:
            actor = self._operator(db, username)
            found = self._received_row(db, request_id)
            permission = json.loads(found['permission'])
            if permission['records'][0]['selector']['audience'] != [f'place:home/{username}']:
                raise Problem(409, f'This imprint is not for place:home/{username}, so no use of it could be '
                                   'allowed; only that person can approve it')
            imprint_id = found['imprint_id']
            if any(p.exists() or p.is_symlink() for p in (root / imprint_id, root / f'{imprint_id}.state',
                                                          root / 'tombstones' / f'{imprint_id}.json')):
                raise Problem(409, 'The imprints root already holds this imprint id (a directory or a tombstone)')
            receipts = [json.loads(r['record']) for r in db.execute(
                'SELECT record FROM imprint_receipts WHERE request_id=? ORDER BY seq', (request_id,))]
            decision = decide_use(permission, receipts, self._owner_layer_of(db, found['owner_id']),
                                  status='approved', kind='admission', t=int(self.clock()), operator=username)
            if not decision.allowed:
                self._deny_imprint(db, found, actor, {'term': decision.term}, 'denied')
                return {'status': 'deleted', 'imprint_id': imprint_id, 'term': decision.term}
            now = int(self.clock())
            db.execute("UPDATE imprint_requests SET status='approved', decided_at=?, decided_by=?, imprints_root=? "
                       "WHERE id=?", (now, actor, str(root), request_id))
            self._append_imprint_receipt(db, request_id, 'approved', actor, {}, sign=False)
        self._hand_off(found, root, now, actor)
        return {'status': 'approved', 'imprint_id': imprint_id, 'term': None}

    def _hand_off(self, found, root, now, actor):
        """Creates the two directories (0700, exclusive), moves the staged `imprint.db` and `manifest.json`, writes
        `permission.json` and `approved.json`, and removes staging (I 10, steps 2 and 3)."""
        imprint_id, staged = found['imprint_id'], self.data_dir / 'imprints' / found['id']
        folder, state = root / imprint_id, root / f'{imprint_id}.state'
        for path in (folder, state):
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                raise Problem(409, 'The imprints root gained this imprint id during the hand-off') from None
            os.chmod(path, 0o700)
        for name in ('imprint.db', 'manifest.json'):
            shutil.move(str(staged / name), str(folder / name))
        _write_file(folder / 'permission.json', canonical({
            'record': json.loads(found['permission']), 'signature': found['permission_signature'],
            'station_key': found['station_key']}))
        _write_file(folder / 'approved.json', canonical({
            'imprint_id': imprint_id, 'request_id': found['id'], 'approved_at': now, 'approved_by': actor}))
        shutil.rmtree(staged)

    # Withdrawal, the station's delete and the removal they share (I 12, D17)

    def _imprint_folders(self, found, root_flag):
        """The staging, imprint and state directories of a request, the last two under the root the row records (the
        flag's when the row records none, before approval). Logs a flag that differs from the record."""
        recorded = found['imprints_root']
        if recorded and root_flag is not None and Path(recorded).resolve() != Path(root_flag).resolve():
            log.warning('imprints root mismatch: recorded %s, flag %s', recorded, root_flag)
        base = Path(recorded) if recorded else (Path(root_flag) if root_flag is not None else None)
        folders = [self.data_dir / 'imprints' / found['id']]
        if base is not None:
            folders += [base / found['imprint_id'], base / f'{found["imprint_id"]}.state']
        return base, folders

    def _remove_imprint(self, db, found, *, reason, actor_id, root_flag):
        """Hashes, then removes, the staging, imprint and state directories. Returns each removed file's path, bytes
        and SHA-256. A removal that fails writes `delete-failed` (path, error class) through `db`, then raises
        _RemovalFailed, which the caller catches inside its transaction so the receipt is kept."""
        _, folders = self._imprint_folders(found, root_flag)
        for folder in folders:
            if folder.is_dir() and not folder.is_symlink():
                _restore_write(folder)
        files = [entry for folder in folders for entry in _removed_files(folder, by_manifest=True)]
        # An earlier try that failed part-way hashed files it then removed: its `delete-failed` receipt carries them,
        # so the `deleted` receipt lists the whole set (I 12, hash before removing).
        seen = {entry['path'] for entry in files}
        earlier = []
        for row in db.execute("SELECT record FROM imprint_receipts WHERE request_id=? AND "
                              "json_extract(record, '$.event')='delete-failed' ORDER BY seq", (found['id'],)):
            for entry in json.loads(row['record'])['detail'].get('files', ()):
                if entry['path'] not in seen:
                    seen.add(entry['path'])
                    earlier.append(entry)
        files = earlier + files
        path = None
        try:
            for folder in folders:
                if folder.is_symlink():
                    path = folder
                    _unlink(folder)
                    continue
                for here, names, names_files in os.walk(folder, topdown=False):
                    for name in names_files + [n for n in names if os.path.islink(os.path.join(here, n))]:
                        path = Path(here) / name
                        _unlink(path)
                    path = Path(here)
                    os.rmdir(here)
        except OSError as error:
            self._append_imprint_receipt(db, found['id'], 'delete-failed', actor_id,
                                         {'path': str(path), 'error': type(error).__name__, 'files': files},
                                         sign=False)
            log.warning('removing the %s copy %s failed at %s: %s', reason, found['id'][:4], path,
                        type(error).__name__)
            raise _RemovalFailed from error
        return files

    def _write_tombstone(self, base, found, db):
        """`<root>/tombstones/<imprint id>.json`, 0600 and exclusive, holding the `withdrawn` and `deleted` receipts."""
        folder = base / 'tombstones'
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        held = [{'record': json.loads(r['record']), 'signature': r['signature']} for r in db.execute(
            "SELECT record, signature FROM imprint_receipts WHERE request_id=? ORDER BY seq", (found['id'],))]
        held = [r for r in held if r['record']['event'] in ('withdrawn', 'deleted')]
        try:
            fd = os.open(folder / f'{found["imprint_id"]}.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return      # an earlier try wrote it; its existence is what stops a restore and a use
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical({'imprint_id': found['imprint_id'], 'request_id': found['id'], 'receipts': held}))
            stream.flush()
            os.fsync(stream.fileno())

    def _end_imprint(self, request_id, *, reason, actor_id, root, withdrawn):
        """I 12's four steps. 1: `deleting` and, for a withdrawal, the signed `withdrawn` receipt (one transaction).
        2 to 4, in a second: the removal, the tombstone, `deleted` and status `deleted`. A failed removal stays
        `deleting` with a `delete-failed` receipt. Calling it again on a `deleting` row retries from step 2, on a
        `deleted` one changes nothing."""
        with self.transaction() as db:
            found = db.execute('SELECT * FROM imprint_requests WHERE id=?', (request_id,)).fetchone()
            if found['status'] in ('deleted', 'declined', 'expired'):
                return {'id': request_id, 'status': found['status']}
            if found['status'] == 'requested':      # R22: no yes yet, so a decline and no receipt
                now = int(self.clock())
                db.execute("UPDATE imprint_requests SET status='declined', code_hash=NULL, decided_at=?, decided_by=?, "
                           "ended_at=? WHERE id=?", (now, actor_id, now, request_id))
                shutil.rmtree(self.data_dir / 'imprints' / request_id, ignore_errors=True)
                return {'id': request_id, 'status': 'declined'}
            if found['status'] != 'deleting':
                db.execute("UPDATE imprint_requests SET status='deleting' WHERE id=?", (request_id,))
            if withdrawn and not db.execute(
                    "SELECT 1 FROM imprint_receipts WHERE request_id=? AND json_extract(record, '$.event')='withdrawn'",
                    (request_id,)).fetchone():
                self._append_imprint_receipt(db, request_id, 'withdrawn', actor_id, {}, sign=True)
        with self.transaction() as db:
            found = db.execute('SELECT * FROM imprint_requests WHERE id=?', (request_id,)).fetchone()
            if found['status'] != 'deleting':
                return {'id': request_id, 'status': found['status']}
            try:
                files = self._remove_imprint(db, found, reason=reason, actor_id=actor_id, root_flag=root)
            except _RemovalFailed:
                return {'id': request_id, 'status': 'deleting'}
            base = self._imprint_folders(found, None)[0] or (Path(root) if root is not None else None)
            self._append_imprint_receipt(db, request_id, 'deleted', actor_id,
                                         {'reason': reason, 'files': files, 'limits': KNOWN_LIMITS}, sign=withdrawn)
            if base is not None:
                self._write_tombstone(base, found, db)
            now = int(self.clock())
            db.execute("UPDATE imprint_requests SET status='deleted', ended_at=?, delete_reason=? WHERE id=?",
                       (now, reason, request_id))
            return {'id': request_id, 'status': 'deleted'}

    def withdraw_imprint(self, principal, request_id, *, root):
        """The owner or the requesting ship withdraws at once, in any status before `deleted` (I 12). Anyone else,
        and an id nobody has, gets a 404. It never waits for Andy."""
        with self.transaction() as db:
            found = db.execute('SELECT ship_id, owner_id FROM imprint_requests WHERE id=?',
                               (request_id,)).fetchone() if isinstance(request_id, str) else None
            if found is None or principal['id'] not in (found['ship_id'], found['owner_id']):
                raise Problem(404, 'No such imprint request')
        return self._end_imprint(request_id, reason='withdrawn', actor_id=principal['id'], root=root, withdrawn=True)

    def shorten_imprint(self, principal, request_id, valid_until, *, root):
        """The owner or the requesting ship moves the end earlier (I 12, D18). The signed `shortened` receipt is
        written first, then the allow files, so a reader of one never sees an end later than the station's. The
        owner's shortening is P 5.3 rule 4's replacement and counts in `owner_layer`; the ship's narrows the ceiling
        only. Anyone else gets a 404."""
        with self.transaction() as db:
            found = db.execute('SELECT * FROM imprint_requests WHERE id=?',
                               (request_id,)).fetchone() if isinstance(request_id, str) else None
            if found is None or principal['id'] not in (found['ship_id'], found['owner_id']):
                raise Problem(404, 'No such imprint request')
            if found['permission'] is None or found['status'] not in LIVE_STATUSES or found['status'] == 'deleting':
                raise Problem(409, 'This imprint has no permission to shorten')
            if type(valid_until) is not int:
                raise Problem(400, 'valid_until is a whole number of seconds')
            records = [json.loads(r['record']) for r in db.execute(
                'SELECT record FROM imprint_receipts WHERE request_id=? ORDER BY seq', (request_id,))]
            end = effective_end(json.loads(found['permission']), records)
            if not int(self.clock()) < valid_until < end:
                raise Problem(400, 'An end can only move earlier. A later end needs a new imprint and a new yes.')
            self._append_imprint_receipt(db, request_id, 'shortened', principal['id'], {'valid_until': valid_until},
                                         sign=True)
            base = self._imprint_folders(found, root)[0]
        if base is not None:
            state = base / f'{found["imprint_id"]}.state'
            if state.is_dir() and not state.is_symlink():
                _replace_allow_files(state, valid_until)
        return {'id': request_id, 'valid_until': valid_until}

    def station_imprint_delete(self, username, prefix, *, root):
        """Trusted local operator only: deletes one imprint by a short id of its imprint id (reason `station`)."""
        if not isinstance(prefix, str) or len(prefix.strip()) < 4:
            raise Problem(400, 'Give at least 4 characters of the short id')
        prefix = prefix.strip().lower()
        with self.transaction() as db:
            actor = self._operator(db, username)
            marks = ','.join('?' * len(LIVE_STATUSES))
            matches = [r['id'] for r in db.execute(
                f"SELECT id, imprint_id FROM imprint_requests WHERE status IN ({marks}) ORDER BY created, rowid",
                LIVE_STATUSES) if r['imprint_id'].startswith(prefix)]
        if not matches:
            raise Problem(404, f'No live imprint starts with {prefix}')
        if len(matches) > 1:
            raise Problem(409, f'{prefix} matches more than one imprint; give more characters')
        return self._end_imprint(matches[0], reason='station', actor_id=actor, root=root, withdrawn=False)

    def station_imprint_use_decision(self, imprint_id, kind):
        """The use decision for one copy at the store's clock, changing nothing."""
        with self.transaction() as db:
            found = db.execute('SELECT * FROM imprint_requests WHERE imprint_id=?', (imprint_id,)).fetchone()
            if found is None or found['permission'] is None:
                raise Problem(404, 'No such imprint')
            records = [json.loads(r['record']) for r in db.execute(
                'SELECT record FROM imprint_receipts WHERE request_id=? ORDER BY seq', (found['id'],))]
            return decide_use(json.loads(found['permission']), records, self._owner_layer_of(db, found['owner_id']),
                              status=found['status'], kind=kind, t=int(self.clock()),
                              operator=self._imprint_operator(db))

    # The sweep (I 12, D32, D42): hourly, never waits for the job lock, one transaction per row

    def _sweep_ids(self, where, params=()):
        """The ids of rows matching `where`, read SWEEP_BATCH at a time by rowid with no transaction held between."""
        last = 0
        while True:
            with self.transaction() as db:
                rows = db.execute(f'SELECT rowid AS n, id FROM imprint_requests WHERE rowid>? AND ({where}) '
                                  f'ORDER BY rowid LIMIT {SWEEP_BATCH}', (last, *params)).fetchall()
            if not rows:
                return
            yield from (r['id'] for r in rows)
            last = rows[-1]['n']

    def station_imprint_sweep(self, *, root):
        """I 12's list, in order; each step runs on its own and a step that fails is logged and named in `errors`
        without stopping the others. `approved` rows are left to the sync, which ends them with the same receipts as
        any admission's end. Returns the counts."""
        out = {'ended': 0, 'windows': 0, 'expired': 0, 'sync': None, 'retried': 0, 'reconciled': 0, 'removed': 0,
               'purged': 0, 'errors': []}
        for name, step in (('ends', self._sweep_ends), ('expire', self._sweep_expire), ('sync', self._sweep_sync),
                           ('retry', self._sweep_retry), ('reconcile', self._sweep_reconcile),
                           ('retention', self._sweep_retention)):
            try:
                step(root, out)
            except Exception as error:      # one step's failure must not stop the others
                log.warning('imprint sweep step %s failed: %s', name, type(error).__name__)
                out['errors'].append(name)
        return out

    def _sweep_ends(self, root, out):
        for request_id in self._sweep_ids("status IN ('allowed','received','admitted') AND permission IS NOT NULL"):
            with self.transaction() as db:
                found = db.execute('SELECT * FROM imprint_requests WHERE id=?', (request_id,)).fetchone()
                if found is None or found['permission'] is None or found['status'] not in ('allowed', 'received',
                                                                                          'admitted'):
                    continue
                records = self._receipt_records(db, request_id)
                now = int(self.clock())
                if now >= effective_end(json.loads(found['permission']), records):
                    reason = 'ended'
                    if not any(r['event'] == 'ended' for r in records):
                        self._append_imprint_receipt(db, request_id, 'ended', None, {}, sign=False)
                elif found['status'] == 'allowed' and found['expires'] <= now:
                    reason = 'upload-expired'
                elif found['status'] == 'received' and found['expires'] <= now:
                    reason = 'review-expired'
                else:
                    continue
            self._end_imprint(request_id, reason=reason, actor_id=None, root=root, withdrawn=False)
            out['ended' if reason == 'ended' else 'windows'] += 1

    def _sweep_expire(self, root, out):
        """A `requested` row past its 10 minutes becomes `expired`; the staging of every declined or expired request
        goes (a request's contents are removed within the hour)."""
        for request_id in self._sweep_ids("status IN ('requested','declined','expired')"):
            with self.transaction() as db:
                found = db.execute('SELECT * FROM imprint_requests WHERE id=?', (request_id,)).fetchone()
                if found is None:
                    continue
                status, now = found['status'], int(self.clock())
                if status == 'requested' and found['expires'] <= now:
                    db.execute("UPDATE imprint_requests SET status='expired', code_hash=NULL, ended_at=? WHERE id=?",
                               (now, request_id))
                    status = 'expired'
                    out['expired'] += 1
                if status in ('declined', 'expired'):
                    shutil.rmtree(self.data_dir / 'imprints' / request_id, ignore_errors=True)

    def _sweep_sync(self, root, out):
        out['sync'] = self.station_imprint_sync(root=root)

    def _sweep_retry(self, root, out):
        for request_id in self._sweep_ids("status='deleting'"):
            with self.transaction() as db:
                found = db.execute('SELECT * FROM imprint_requests WHERE id=?', (request_id,)).fetchone()
                if found is None or found['status'] != 'deleting':
                    continue
                records = self._receipt_records(db, request_id)
                now = int(self.clock())
            events = {r['event']: r for r in records}
            terms = [r['detail'].get('term') for r in records if r['event'] == 'failed']
            actor = None
            if 'withdrawn' in events:
                reason, actor = 'withdrawn', events['withdrawn']['actor_id']
            elif 'ended' in events or 'end' in terms:
                reason = 'ended'
            elif 'failed' in events:
                reason = 'failed'
            elif 'approved' not in events and found['expires'] <= now:
                reason = 'upload-expired' if 'received' not in events else 'review-expired'
            else:
                reason = 'station'
            result = self._end_imprint(request_id, reason=reason, actor_id=actor, root=root,
                                       withdrawn='withdrawn' in events)
            out['retried'] += result['status'] == 'deleted'

    def _sweep_reconcile(self, root, out):
        """After a restore (I 12): tombstones win; a row whose files are gone is closed; a directory no live row owns
        is removed."""
        live = ','.join(f"'{s}'" for s in LIVE_STATUSES)
        for request_id in self._sweep_ids(f'status IN ({live})'):
            with self.transaction() as db:
                found = db.execute('SELECT * FROM imprint_requests WHERE id=?', (request_id,)).fetchone()
                if found is None or found['status'] not in LIVE_STATUSES:
                    continue
                base = self._imprint_folders(found, root)[0]
                now = int(self.clock())
                if base is not None and os.path.lexists(base / 'tombstones' / f'{found["imprint_id"]}.json'):
                    db.execute("UPDATE imprint_requests SET status='deleted', ended_at=? WHERE id=?", (now, request_id))
                    out['reconciled'] += 1
                    continue
                if found['status'] == 'deleting':
                    continue
                if found['status'] in ('requested', 'allowed', 'received'):
                    gone = not (self.data_dir / 'imprints' / request_id).is_dir()
                else:
                    held_since = found['decided_at'] if found['decided_at'] is not None else found['created']
                    gone = base is not None and not (base / found['imprint_id']).is_dir() \
                        and now - held_since >= HAND_OFF_GRACE
                if not gone:
                    continue
                if found['permission'] is None:
                    db.execute("UPDATE imprint_requests SET status='expired', code_hash=NULL, ended_at=? WHERE id=?",
                               (now, request_id))
                    shutil.rmtree(self.data_dir / 'imprints' / request_id, ignore_errors=True)
                    out['reconciled'] += 1
                    continue
                try:
                    files = self._remove_imprint(db, found, reason='missing', actor_id=None, root_flag=root)
                except _RemovalFailed:
                    db.execute("UPDATE imprint_requests SET status='deleting' WHERE id=?", (request_id,))
                    continue
                self._append_imprint_receipt(db, request_id, 'deleted', None,
                                             {'reason': 'missing', 'files': files, 'limits': KNOWN_LIMITS}, sign=False)
                if base is not None:
                    self._write_tombstone(base, found, db)
                db.execute("UPDATE imprint_requests SET status='deleted', ended_at=?, delete_reason='missing' "
                           "WHERE id=?", (now, request_id))
                out['reconciled'] += 1
        self._sweep_orphans(Path(root), out)

    def _sweep_orphans(self, root, out):
        """Removes an imprint or state directory no live row owns, listing the root one entry at a time and skipping
        `tombstones/` and `.jobs.lock`. Only a name shaped like an imprint id is touched. A deleted receipt (reason
        `restore`) is written when the station holds a permission for it."""
        if not root.is_dir():
            return
        with os.scandir(root) as entries:
            for entry in entries:
                matched = re.fullmatch(f'({_ANY_UUID.pattern})(\\.state)?', entry.name)
                if matched is None or not os.path.lexists(entry.path):
                    continue
                with self.transaction() as db:
                    found = db.execute('SELECT * FROM imprint_requests WHERE imprint_id=?', (matched[1],)).fetchone()
                    if found is not None and found['status'] in LIVE_STATUSES:
                        continue
                    if found is None or found['permission'] is None:
                        if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                            if entry.is_symlink():
                                os.unlink(entry.path)
                            continue
                        _restore_write(entry.path)
                        shutil.rmtree(entry.path, ignore_errors=True)
                        out['removed'] += 1
                        continue
                    here = {'id': found['id'], 'imprint_id': found['imprint_id'], 'imprints_root': str(root)}
                    try:
                        files = self._remove_imprint(db, here, reason='restore', actor_id=None, root_flag=root)
                    except _RemovalFailed:
                        continue
                    self._append_imprint_receipt(db, found['id'], 'deleted', None,
                                                 {'reason': 'restore', 'files': files, 'limits': KNOWN_LIMITS},
                                                 sign=False)
                    out['removed'] += 1

    def _sweep_retention(self, root, out):
        """D32: a declined or expired request's row goes 30 days after it ended, a deleted imprint's row, permission,
        receipts and tombstone 400 days after `deleted`."""
        for request_id in self._sweep_ids("status IN ('declined','expired','deleted')"):
            with self.transaction() as db:
                found = db.execute('SELECT * FROM imprint_requests WHERE id=?', (request_id,)).fetchone()
                if found is None:
                    continue
                ended = next(v for v in (found['ended_at'], found['decided_at'], found['created']) if v is not None)
                keep = KEEP_DAYS if found['status'] == 'deleted' else DECLINED_KEEP_DAYS
                if int(self.clock()) - ended <= keep * 86400:
                    continue
                for base in {b for b in (found['imprints_root'], root) if b is not None}:
                    (Path(base) / 'tombstones' / f'{found["imprint_id"]}.json').unlink(missing_ok=True)
                shutil.rmtree(self.data_dir / 'imprints' / request_id, ignore_errors=True)
                db.execute('DELETE FROM imprint_receipts WHERE request_id=?', (request_id,))
                db.execute('DELETE FROM imprint_requests WHERE id=?', (request_id,))
                out['purged'] += 1

    # Admission on the station (I 10, D16, D39, R24, R25)

    def _imprint_state(self, found, root):
        base = self._imprint_folders(found, root)[0]
        return None if base is None else base / f'{found["imprint_id"]}.state'

    def _receipt_records(self, db, request_id):
        return [json.loads(r['record']) for r in db.execute(
            'SELECT record FROM imprint_receipts WHERE request_id=? ORDER BY seq', (request_id,))]

    def station_imprint_admit_begin(self, imprint_id, *, root, operator):
        """Section 8's whole check for admission, at the store's clock, at the start of every run (D39). Allowed: writes
        `<id>.state/admission.json` (0400, exclusive). A begun admission runs once (R24): when the file exists this
        refuses, writes nothing and leaves no receipt. Refused on an `approved` row: a `failed` receipt naming the
        term, no file (R25). A row in another status is refused with the term `status` and no receipt."""
        with self.transaction() as db:
            found = db.execute('SELECT * FROM imprint_requests WHERE imprint_id=?', (imprint_id,)).fetchone() \
                if isinstance(imprint_id, str) else None
            if found is None or found['permission'] is None:
                raise Problem(404, 'No such imprint')
            state = self._imprint_state(found, root)
            if state is not None and (os.path.lexists(state / 'admission.json')):
                return {'allowed': False, 'begun': True}
            records = self._receipt_records(db, found['id'])
            now = int(self.clock())
            decision = decide_use(json.loads(found['permission']), records, self._owner_layer_of(db, found['owner_id']),
                                  status=found['status'], kind='admission', t=now, operator=operator)
            if not decision.allowed:
                if found['status'] == 'approved':
                    self._append_imprint_receipt(db, found['id'], 'failed', None, {'term': decision.term}, sign=False)
                return {'allowed': False, 'term': decision.term}
            if state is None or state.is_symlink() or not state.is_dir():
                raise Problem(409, 'This imprint has no state directory; the sweep marks it missing')
            doc = {'kind': 'imprint-admission-allow', 'instance_id': found['imprint_id'], 'decided_at': now,
                   'valid_until': decision.valid_until}
            temporary = state / f'.admission.json.{secrets.token_hex(4)}.tmp'
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
                with os.fdopen(fd, 'wb') as out:
                    out.write(json.dumps(doc, indent=2, sort_keys=True).encode() + b'\n')
                    out.flush()
                    os.fsync(out.fileno())
                try:
                    os.link(temporary, state / 'admission.json')       # exclusive: two begins cannot both win
                except FileExistsError:
                    return {'allowed': False, 'begun': True}
                _fsync_dir(state)
            finally:
                temporary.unlink(missing_ok=True)
            return {'allowed': True, 'decided_at': now, 'valid_until': decision.valid_until}

    def station_imprint_use_begin(self, username, prefix, use, *, root):
        """The use decision for one copy at the store's clock, then, in one transaction (I 12, D41). Allowed: a new
        lowercase uuid4 `use_id`, the `use-started` receipt, and after it `<id>.state/uses/<use id>.allow.json` (0400);
        a file that cannot be written rolls the receipt back. Refused: a `refused` receipt naming the term and nothing
        else. `uses/` is made without its parents, so a removed state directory is never recreated."""
        if use not in ('trail-evaluation',):
            raise Problem(400, f'Unknown imprint use {use!r}')
        imprint_id = self.station_imprint_resolve(prefix)
        with self.transaction() as db:
            operator = db.execute('SELECT username FROM users WHERE username=?', (username,)).fetchone()
            if operator is None:
                raise Problem(404, f'No account named {username}')
            found = db.execute('SELECT * FROM imprint_requests WHERE imprint_id=?', (imprint_id,)).fetchone()
            if found is None or found['permission'] is None:
                raise Problem(404, 'No such imprint')
            state = self._imprint_state(found, root)
            records = self._receipt_records(db, found['id'])
            permission = json.loads(found['permission'])
            now = int(self.clock())
            decision = decide_use(permission, records, self._owner_layer_of(db, found['owner_id']),
                                  status=found['status'], kind=use, t=now, operator=username)
            actions = sorted({a for _, a, _ in need(use, route=False)})
            purpose = use
            admitted = next((r for r in records if r['event'] == 'admitted'), None)
            if not decision.allowed:
                detail = {'use': use, 'actions': actions, 'purpose': purpose, 'term': decision.term}
                if admitted is not None:
                    detail['roads_and_trails'] = admitted['detail']['roads_and_trails']
                self._append_imprint_receipt(db, found['id'], 'refused', None, detail, sign=False)
                return {'allowed': False, 'term': decision.term}
            if state is None or state.is_symlink() or not state.is_dir():
                raise Problem(409, 'This imprint has no state directory; the sweep marks it missing')
            try:
                manifest = json.loads((self._imprint_folders(found, root)[1][1] / 'manifest.json').read_bytes())
                contents = manifest['contents']
                count = contents.get('episodes', 0) + contents.get('semantics', 0)
            except (OSError, ValueError, KeyError, AttributeError, TypeError):
                raise Problem(409, 'This imprint has no readable manifest') from None
            use_id = str(uuid.uuid4())
            objects = {'imprint': imprint_id, 'count': count, 'roads_and_trails': admitted['detail']['roads_and_trails']}
            self._append_imprint_receipt(db, found['id'], 'use-started', None,
                                         {'use': use, 'use_id': use_id, 'actions': actions, 'purpose': purpose,
                                          'objects': objects}, sign=False)
            doc = {'kind': 'imprint-use-allow', 'use_id': use_id, 'instance_id': imprint_id, 'use': use,
                   'actions': actions, 'purpose': purpose, 'requester': AGENT, 'acting_for': f'person:{username}',
                   'place': f'place:home/{username}', 'records': list(decision.records), 'decided_at': now,
                   'valid_until': decision.valid_until}
            uses = state / 'uses'
            uses.mkdir(mode=0o700, exist_ok=True)           # parents=False: never recreates a removed state directory
            temporary = uses / f'.{use_id}.allow.json.{secrets.token_hex(4)}.tmp'
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
                with os.fdopen(fd, 'wb') as out:
                    out.write(json.dumps(doc, indent=2, sort_keys=True).encode() + b'\n')
                    out.flush()
                    os.fsync(out.fileno())
                os.link(temporary, uses / f'{use_id}.allow.json')
                _fsync_dir(uses)
            finally:
                temporary.unlink(missing_ok=True)
            return {'allowed': True, 'use_id': use_id, 'valid_until': decision.valid_until}

    def station_imprint_sync(self, *, root):
        """Records what each `approved` row's admission left (I 10, "On 'ended'"; R24), one transaction per row that
        re-reads the status, so a withdrawal in between wins. Rows in any other status never move."""
        with self.transaction() as db:
            ids = [r['id'] for r in db.execute("SELECT id FROM imprint_requests WHERE status='approved' "
                                               "ORDER BY created, rowid")]
        out = {'admitted': 0, 'failed': 0, 'waiting': 0, 'finished': 0}
        for request_id in ids:
            out[self._sync_admission(request_id, root)] += 1
        with self.transaction() as db:
            unfinished = [r['request_id'] for r in db.execute(
                "SELECT DISTINCT request_id FROM imprint_receipts WHERE json_extract(record, '$.event')='use-started' "
                "ORDER BY request_id")]
        for request_id in unfinished:
            out['finished'] += self._finish_uses(request_id, root)
        return out

    def _finish_uses(self, request_id, root):
        """Finishes every use of one imprint that has `use-started` and no `use-finished` (I 12, D41): once its
        `result.json` exists, the imprint is `deleted`, or USE_BOUND seconds have passed since `use-started`; never
        while the imprint is `deleting`. One transaction per imprint, so two syncs write each receipt once. Returns
        how many uses it finished."""
        count = 0
        with self.transaction() as db:
            found = db.execute('SELECT * FROM imprint_requests WHERE id=?', (request_id,)).fetchone()
            if found is None or found['permission'] is None or found['status'] == 'deleting':
                return 0
            records = self._receipt_records(db, request_id)
            done = {r['detail']['use_id'] for r in records if r['event'] == 'use-finished'}
            state = self._imprint_state(found, root)
            base = self._imprint_folders(found, root)[0]
            tombstone = base is not None and os.path.lexists(base / 'tombstones' / f'{found["imprint_id"]}.json')
            now = int(self.clock())
            permission_end = effective_end(json.loads(found['permission']), records)
            for started in [r for r in records if r['event'] == 'use-started' and r['detail']['use_id'] not in done]:
                use_id, begun = started['detail']['use_id'], started['at']
                folder = None if state is None else state / 'uses' / use_id
                result = None if folder is None else _read_json(folder / 'result.json')
                if result is None and found['status'] != 'deleted' and now - begun < USE_BOUND:
                    continue
                t_end = result['ended_at'] if result is not None and _is_count(result.get('ended_at')) \
                    else min(now, begun + USE_BOUND)
                detail = {k: started['detail'][k] for k in ('use', 'use_id', 'actions', 'purpose', 'objects')}
                detail.update(self._use_end(records, folder, result, tombstone, permission_end, t_end))
                if state is not None:
                    try:
                        _unlink(state / 'uses' / f'{use_id}.allow.json')
                    except FileNotFoundError:
                        pass
                self._append_imprint_receipt(db, request_id, 'use-finished', None, detail, sign=False)
                count += 1
        return count

    @staticmethod
    def _use_end(records, folder, result, tombstone, permission_end, t_end):
        """The first of I 12's rules 1 to 7 that holds at t_end, as the keys `use-finished` adds to the use's own."""
        report = None if folder is None else folder / 'report.json'
        if report is not None and report.is_file() and not report.is_symlink():
            return {'end': 'report', 'report_sha256': hashlib.sha256(report.read_bytes()).hexdigest()}
        if tombstone:
            if any(r['event'] == 'withdrawn' and r['at'] <= t_end for r in records):
                return {'end': 'withdrawn'}
        if permission_end <= t_end:
            return {'end': 'ended'}
        if tombstone:
            deleted = next((r for r in records if r['event'] == 'deleted' and r['at'] <= t_end), None)
            if deleted is not None:
                return {'end': 'deleted', 'reason': deleted['detail']['reason']}
        code = None if result is None else result.get('exit')
        if code == 3 and type(code) is int:
            return {'end': 'allow changed'}
        if result is None or (type(code) is int and code < 0):
            return {'end': 'not evaluable: limit'}
        if type(code) is int:
            return {'end': 'failed', 'exit': code}
        error = result.get('error')
        return {'end': 'failed', 'error': error if isinstance(error, str) and error.isidentifier() else 'Error'}

    def _sync_admission(self, request_id, root):
        with self.transaction() as db:
            found = db.execute('SELECT * FROM imprint_requests WHERE id=?', (request_id,)).fetchone()
            if found is None or found['status'] != 'approved':
                return 'waiting'
            state = self._imprint_state(found, root)
            records = self._receipt_records(db, request_id)
            now = int(self.clock())
            result = _read_result(state / 'result.json') if state is not None else None
            if result is not None and result['status'] == 'admitted':
                detail = {k: result[k] for k in ('checks', 'report_sha256', 'skipped', 'roads_and_trails',
                                                 'sessions_too_large')}
                self._append_imprint_receipt(db, request_id, 'admitted', None, detail, sign=False)
                db.execute("UPDATE imprint_requests SET status='admitted' WHERE id=?", (request_id,))
                return 'admitted'
            failed_terms = [r['detail']['term'] for r in records if r['event'] == 'failed' and 'term' in r['detail']]
            written = any(r['event'] == 'failed' for r in records)
            detail = None
            if result is not None:
                detail, reason = {'step': result['step'], 'message': result['message']}, 'failed'
            elif failed_terms:
                reason = 'ended' if failed_terms[-1] == 'end' else 'failed'
            elif now >= effective_end(json.loads(found['permission']), records):
                detail, reason = {'term': 'end'}, 'ended'
            else:
                decided = _decided_at(state / 'admission.json') if state is not None else None
                if decided is None or now - decided <= ADMISSION_BOUND:
                    return 'waiting'
                detail, reason = {'step': 'calibration', 'message': ADMISSION_STOPPED}, 'failed'
            if detail is not None and not written:
                self._append_imprint_receipt(db, request_id, 'failed', None, detail, sign=False)
        self._end_imprint(request_id, reason=reason, actor_id=None, root=root, withdrawn=False)
        return 'failed'

    def station_imprints(self, *, root, awaiting=False):
        """The live imprints for `make station-imprints`, newest first, each with its two display lines. `awaiting`
        keeps the `approved` rows that have neither `admission.json` nor `result.json`: never begun (R24)."""
        marks = ','.join('?' * len(LIVE_STATUSES))
        shown = []
        with self.transaction() as db:
            for found in db.execute(f'SELECT r.*, u.username AS owner FROM imprint_requests r JOIN users u ON '
                                    f'u.id=r.owner_id WHERE r.status IN ({marks}) ORDER BY r.created, r.rowid',
                                    LIVE_STATUSES).fetchall():
                state = self._imprint_state(found, root)
                begun = state is not None and os.path.lexists(state / 'admission.json')
                has_result = state is not None and os.path.lexists(state / 'result.json')
                if awaiting and (found['status'] != 'approved' or begun or has_result):
                    continue
                rows = db.execute('SELECT record, signature FROM imprint_receipts WHERE request_id=? ORDER BY seq',
                                  (found['id'],)).fetchall()
                shown.append(self._imprint_row(found, rows, root, begun=begun))
        return shown

    def _imprint_row(self, found, rows, root, *, begun):
        records = [json.loads(r['record']) for r in rows]
        admitted = next((r for r in records if r['event'] == 'admitted'), None)
        counts = admitted['detail'] if admitted else {}
        permission = json.loads(found['permission']) if found['permission'] else None
        route = permission is not None and any('route' in r['selector']['actions'] for r in permission['records'])
        signed = all(r['signature'] for r in rows)
        short, owner, status = found['imprint_id'][:4], found['owner'], found['status']
        if status == 'admitted' and admitted:
            when = datetime.fromtimestamp(admitted['at'], timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            head = f'{short}  {owner}  admitted {when}   {counts["checks"]} of 17 checks; calibrated'
            if counts['skipped']:
                head += f'; {len(counts["skipped"])} analyses skipped'
            if route:
                head += f'; {counts["roads_and_trails"]} roads and trails counted'
                if counts['sessions_too_large']:
                    head += f' ({counts["sessions_too_large"]} sessions too large to count)'
            else:
                head += '; 0 sessions (route not chosen)'
        elif status == 'approved':
            wait = 'running, or stopped without a result' if begun else 'waiting: not begun; run make station-imprint-admit'
            head = f'{short}  {owner}  approved   {wait}'
        else:
            head = f'{short}  {owner}  {status}'
        tail = ''
        if permission is not None:
            base = self._imprint_folders(found, root)[0]
            ends = datetime.fromtimestamp(effective_end(permission, records), timezone.utc).strftime('%Y-%m-%d')
            tail = (f'\n      read-only at {base}/{found["imprint_id"]}/' if base and status == 'admitted' else
                    f'\n      at {base}/{found["imprint_id"]}/' if base else '\n     ')
            tail += f'   ends {ends}   receipts {"signed" if signed else "not yet signed"}'
        return {'id': found['id'], 'imprint_id': found['imprint_id'], 'owner': owner, 'status': status,
                'roads_and_trails': counts.get('roads_and_trails'), 'sessions_too_large': counts.get('sessions_too_large'),
                'signed': signed, 'line': head + tail}

    def station_imprint_resolve(self, prefix):
        """The one full imprint id a short id starts, among live imprints."""
        if not isinstance(prefix, str) or len(prefix.strip()) < 4:
            raise Problem(400, 'Give at least 4 characters of the short id')
        prefix = prefix.strip().lower()
        marks = ','.join('?' * len(LIVE_STATUSES))
        with self.transaction() as db:
            matches = [r['imprint_id'] for r in db.execute(
                f'SELECT imprint_id FROM imprint_requests WHERE status IN ({marks}) ORDER BY created, rowid',
                LIVE_STATUSES) if r['imprint_id'].startswith(prefix)]
        if len(matches) != 1:
            raise Problem(404 if not matches else 409,
                          f'No live imprint starts with {prefix}' if not matches else
                          f'{prefix} matches more than one imprint; give more characters')
        return matches[0]
