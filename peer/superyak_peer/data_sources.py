"""Private source registry and atomic, inspectable manual imports."""
import hashlib
import json

from .common import Problem, encode, require, text, uid
from .interchange import validate_document


SCHEMA = '''
CREATE TABLE IF NOT EXISTS data_sources(
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, kind TEXT NOT NULL, description TEXT NOT NULL,
 enabled INTEGER NOT NULL, version INTEGER NOT NULL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, system_key TEXT,
 UNIQUE(owner_id,system_key));
CREATE INDEX IF NOT EXISTS data_sources_owner ON data_sources(owner_id,created_at,id);
CREATE TABLE IF NOT EXISTS data_source_items(
 source_id TEXT NOT NULL REFERENCES data_sources(id), kind TEXT NOT NULL,
 item_id TEXT NOT NULL, created_at REAL NOT NULL,
 PRIMARY KEY(source_id,kind,item_id));
CREATE INDEX IF NOT EXISTS data_source_item_lookup ON data_source_items(kind,item_id);
CREATE TABLE IF NOT EXISTS data_source_imports(
 id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL REFERENCES data_sources(id),
 request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL,
 added_count INTEGER NOT NULL, items TEXT NOT NULL, error TEXT, created_at REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS data_source_import_success
 ON data_source_imports(source_id,request_id) WHERE status='succeeded';
CREATE INDEX IF NOT EXISTS data_source_import_history ON data_source_imports(source_id,id);
'''


def pagination(limit, offset):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 1000000:
        raise Problem(400, 'Use limit 1–100 and offset 0–1000000')
    return limit, offset


class DataSources:
    def __init__(self, store, interchange):
        self.store, self.interchange = store, interchange
        with store.transaction() as db:
            db.executescript(SCHEMA)
            # Upgrade existing records without rewriting them or fabricating receipts.
            rows = db.execute("SELECT id,owner_id FROM imported_sources r WHERE NOT EXISTS (SELECT 1 FROM data_source_items i WHERE i.kind='record' AND i.item_id=r.id)").fetchall()
            for row in rows:
                source = self._default(db, row['owner_id'])
                self._link(db, source['id'], 'record', row['id'])

    def _owned(self, db, actor, key):
        text(key, 'data source ID', 100)
        return require(db.execute('SELECT * FROM data_sources WHERE id=? AND owner_id=?', (key, actor)).fetchone())

    def _describe(self, db, row):
        result = {k: row[k] for k in ('id', 'name', 'kind', 'description', 'version', 'created_at', 'updated_at')}
        result['enabled'] = bool(row['enabled'])
        result['item_count'] = db.execute('SELECT COUNT(*) FROM data_source_items WHERE source_id=?', (row['id'],)).fetchone()[0]
        return result

    def _create(self, db, actor, name, kind, description='', system_key=None):
        key, now = uid(), self.store.clock()
        db.execute('INSERT INTO data_sources VALUES(?,?,?,?,?,?,?,?,?,?)', (key, actor, name, kind, description, True, 1, now, now, system_key))
        return self._owned(db, actor, key)

    def _default(self, db, actor):
        return db.execute("SELECT * FROM data_sources WHERE owner_id=? AND system_key='selected-records'", (actor,)).fetchone() or self._create(db, actor, 'Selected source documents', 'selected-records', system_key='selected-records')

    def create(self, actor, data):
        if set(data) - {'name', 'kind', 'description'}:
            raise Problem(400, 'Unknown data source field')
        name = text(data.get('name'), 'source name')
        kind = data.get('kind')
        if kind not in ('file', 'selected-records'):
            raise Problem(400, 'Choose file or selected-records as the source kind')
        description = text(data.get('description', ''), 'source description', 2000, empty=True)
        with self.store.transaction() as db:
            return self._describe(db, self._create(db, actor, name, kind, description))

    def list(self, actor, limit=50, offset=0):
        pagination(limit, offset)
        with self.store.transaction() as db:
            rows = db.execute('SELECT * FROM data_sources WHERE owner_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', (actor, limit, offset)).fetchall()
            return {'sources': [self._describe(db, row) for row in rows], 'limit': limit, 'offset': offset}

    def get(self, actor, key):
        with self.store.transaction() as db:
            return self._describe(db, self._owned(db, actor, key))

    def update(self, actor, key, data):
        with self.store.transaction() as db:
            row = self._owned(db, actor, key)
            if set(data) - {'version', 'name', 'description', 'enabled'}:
                raise Problem(400, 'Unknown data source field')
            self._version(row, data.get('version'))
            name = text(data.get('name', row['name']), 'source name')
            description = text(data.get('description', row['description']), 'source description', 2000, empty=True)
            enabled = data.get('enabled', bool(row['enabled']))
            if type(enabled) is not bool:
                raise Problem(400, 'Source enabled must be true or false')
            if (name, description, enabled) != (row['name'], row['description'], bool(row['enabled'])):
                db.execute('UPDATE data_sources SET name=?,description=?,enabled=?,version=version+1,updated_at=? WHERE id=?', (name, description, enabled, self.store.clock(), key))
            return self._describe(db, self._owned(db, actor, key))

    @staticmethod
    def _version(row, version):
        if type(version) is not int or version < 1:
            raise Problem(400, 'A positive source version is required')
        if version != row['version']:
            raise Problem(409, 'Source settings changed; review them before continuing')

    def _link(self, db, key, kind, item_id):
        return db.execute('INSERT OR IGNORE INTO data_source_items VALUES(?,?,?,?)', (key, kind, item_id, self.store.clock())).rowcount

    @staticmethod
    def _receipt(row):
        return {**{k: row[k] for k in ('id', 'source_id', 'request_id', 'status', 'added_count', 'error', 'created_at')}, 'items': json.loads(row['items'])}

    def _record(self, db, key, request_id, fingerprint, items, added_count, error=None):
        result = db.execute('INSERT INTO data_source_imports(source_id,request_id,fingerprint,status,added_count,items,error,created_at) VALUES(?,?,?,?,?,?,?,?)',
                            (key, request_id, fingerprint, 'failed' if error else 'succeeded', added_count, encode(items), error, self.store.clock()))
        return self._receipt(db.execute('SELECT * FROM data_source_imports WHERE id=?', (result.lastrowid,)).fetchone())

    def import_items(self, actor, key, data):
        request_id = None
        fingerprint = ''
        owned = False
        try:
            with self.store.transaction() as db:
                row = self._owned(db, actor, key)
                owned = True
                request_id = text(data.get('request_id'), 'import request ID', 100)
                allowed = {'request_id', 'version', 'file_ids' if row['kind'] == 'file' else 'document'}
                if set(data) - allowed:
                    raise Problem(400, 'Unknown field for this source kind')
                fingerprint = hashlib.sha256(encode({k: v for k, v in data.items() if k not in ('request_id', 'version')}).encode()).hexdigest()
                previous = db.execute("SELECT * FROM data_source_imports WHERE source_id=? AND request_id=? AND status='succeeded'", (key, request_id)).fetchone()
                if previous:
                    if previous['fingerprint'] != fingerprint:
                        raise Problem(409, 'Import request ID was already used for different content')
                    return self._receipt(previous)
                self._version(row, data.get('version'))
                if not row['enabled']:
                    raise Problem(409, 'Source is paused; enable it before importing')
                items = []
                if row['kind'] == 'file':
                    ids = data.get('file_ids')
                    if not isinstance(ids, list) or not 1 <= len(ids) <= 20:
                        raise Problem(400, 'Select between 1 and 20 files')
                    for item_id in ids:
                        text(item_id, 'file ID', 100)
                        require(db.execute('SELECT id FROM files WHERE id=? AND owner_id=?', (item_id, actor)).fetchone())
                        if {'kind': 'file', 'id': item_id} not in items:
                            items.append({'kind': 'file', 'id': item_id})
                else:
                    document = validate_document(data.get('document'))
                    imported = self.interchange._import_document(db, actor, document)
                    items = [{'kind': 'record', 'id': record['id']} for record in imported['records']]
                added_count = sum(self._link(db, key, item['kind'], item['id']) for item in items)
                return self._record(db, key, request_id, fingerprint, items, added_count)
        except Problem as error:
            # The content transaction has rolled back. Do not store failed input
            # bodies, foreign file IDs, or errors against an unowned source.
            if owned and request_id is not None:
                with self.store.transaction() as db:
                    self._owned(db, actor, key)
                    self._record(db, key, request_id, fingerprint, [], 0, error.message)
            raise

    def import_default(self, actor, document):
        validate_document(document)
        with self.store.transaction() as db:
            source = self._default(db, actor)
        receipt = self.import_items(actor, source['id'], {'request_id': uid(), 'version': source['version'], 'document': document})
        return {'records': [{'id': item['id'], 'record': record} for item, record in zip(receipt['items'], document['records'])]}

    def history(self, actor, key, limit=50, offset=0):
        pagination(limit, offset)
        with self.store.transaction() as db:
            self._owned(db, actor, key)
            rows = db.execute('SELECT * FROM data_source_imports WHERE source_id=? ORDER BY id DESC LIMIT ? OFFSET ?', (key, limit, offset)).fetchall()
            return {'imports': [self._receipt(row) for row in rows], 'limit': limit, 'offset': offset}

    def items(self, actor, key, limit=50, offset=0):
        pagination(limit, offset)
        with self.store.transaction() as db:
            self._owned(db, actor, key)
            links = db.execute('SELECT * FROM data_source_items WHERE source_id=? ORDER BY rowid DESC LIMIT ? OFFSET ?', (key, limit, offset)).fetchall()
            items = []
            for link in links:
                if link['kind'] == 'file':
                    file = require(db.execute('SELECT id,name,media_type,digest,size FROM files WHERE id=? AND owner_id=?', (link['item_id'], actor)).fetchone())
                    items.append({'kind': 'file', 'file': dict(file)})
                else:
                    record = require(db.execute('SELECT id,record FROM imported_sources WHERE id=? AND owner_id=?', (link['item_id'], actor)).fetchone())
                    items.append({'kind': 'record', 'source': {'id': record['id'], 'record': json.loads(record['record'])}})
            return {'items': items, 'limit': limit, 'offset': offset}
