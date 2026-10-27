"""Store-copy imprints on the station (spec I 7, 8, 12; plan Task 23): the request and receipt tables, and the receipts'
hash chain. A receipt names what happened and never what the store holds, so each event's detail keys are listed once,
in DETAIL_KEYS (R25), and a receipt holding any other key is refused."""
import hashlib
import json
from .common import uid
from .identity import canonical

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
