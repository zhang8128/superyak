"""Bounded selected records. Origin and audience are attribution, never grants."""
import hashlib
import json
import re
from .common import Problem, text, encode, uid, require

SCHEMA = '''CREATE TABLE IF NOT EXISTS imported_sources(
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 source_id TEXT NOT NULL, revision TEXT NOT NULL, record TEXT NOT NULL,
 UNIQUE(owner_id,source_id,revision));'''
FORMAT = 'superyak.selected-sources.v1'
MAX_BYTES = 512 * 1024
# Standalone mirror of the aDNA reader document bound (context_adna.MAX_FILE_BYTES).
ADNA_MAX_BYTES = 65536
FIELDS = {'id', 'origin', 'source_locator', 'source_hash', 'revision', 'revision_of',
          'correction_of', 'author', 'content', 'audience'}


def content_hash(content):
    """SHA-256 of UTF-8 canonical JSON: sorted keys, compact, ASCII escapes."""
    return hashlib.sha256(encode(content).encode()).hexdigest()


def document(records):
    return {'format': FORMAT, 'records': records}


def validate_document(value):
    if not isinstance(value, dict) or set(value) != {'format', 'records'} or value['format'] != FORMAT:
        raise Problem(400, 'Invalid source document')
    records = value['records']
    if not isinstance(records, list) or not 1 <= len(records) <= 20:
        raise Problem(400, 'Select between 1 and 20 source records')
    if len(encode(value).encode()) > MAX_BYTES:
        raise Problem(400, 'Source document exceeds 512 KiB')
    seen = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != FIELDS:
            raise Problem(400, 'Invalid source record fields')
        origin = text(record['origin'], 'source origin', 100)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', origin):
            raise Problem(400, 'Invalid source origin')
        key = text(record['id'], 'source ID', 500)
        # Preserve explicit source namespaces; a declared common origin grants nothing.
        if not re.fullmatch(r'(peer|adna):' + re.escape(origin) + r':[^\s]+', key):
            raise Problem(400, 'Source ID must be origin-qualified')
        text(record['source_locator'], 'source locator', 1000)
        text(record['author'], 'source author', 500)
        revision = text(record['revision'], 'source revision', 100)
        if record['revision_of'] is not None:
            text(record['revision_of'], 'previous source reference', 1000)
        corrections = record['correction_of']
        if not isinstance(corrections, list) or len(corrections) > 20:
            raise Problem(400, 'Invalid correction references')
        for correction in corrections:
            text(correction, 'correction reference', 1000)
        content = record['content']
        if not isinstance(content, dict) or set(content) != {'title', 'body'}:
            raise Problem(400, 'Invalid selected content')
        text(content['title'], 'source title')
        text(content['body'], 'source body', 100000, empty=True)
        if record['source_hash'] != content_hash(content):
            raise Problem(400, 'Selected source content hash does not match')
        audience = record['audience']
        if not isinstance(audience, dict) or set(audience) != {'kind', 'public', 'people', 'spaces'} or audience['kind'] not in ('draft', 'active') or type(audience['public']) is not bool:
            raise Problem(400, 'Invalid source audience')
        for field in ('people', 'spaces'):
            if not isinstance(audience[field], list) or len(audience[field]) > 100:
                raise Problem(400, 'Invalid source audience')
            for item in audience[field]:
                text(item, 'source audience reference', 500)
        if (key, revision) in seen:
            raise Problem(400, 'Duplicate source revision')
        seen.add((key, revision))
    return value


class Interchange:
    def __init__(self, store, origin):
        self.store, self.origin = store, origin
        with store.transaction() as db:
            db.executescript(SCHEMA)

    def _selected(self, db, actor, selection):
        if not isinstance(selection, dict) or set(selection) != {'layer_id', 'kind', 'version'} or selection['kind'] not in ('draft', 'active'):
            raise Problem(400, 'Invalid source selection')
        key = text(selection['layer_id'], 'layer ID', 100)
        row = self.store._owned_layer(db, actor, key)
        kind = selection['kind']
        if kind == 'draft':
            content, version = json.loads(row['draft']), row['version']
            previous_version = version - 1 if version > 1 else None
        else:
            content = self.store._active_layer(db, key, actor)
            version = content['revision']
            previous_version = db.execute('SELECT MAX(revision) FROM layer_revisions WHERE layer_id=? AND revision<?', (key, version)).fetchone()[0]
        if type(selection['version']) is not int or selection['version'] != version:
            raise Problem(409, 'Selected source version changed; review it again')
        source_id = f'peer:{self.origin}:layer/{key}'
        selected = {k: content[k] for k in ('title', 'body')}
        people = []
        for person in content['audience_users']:
            remote = db.execute('SELECT peer_id,user_id FROM remote_contacts WHERE id=?', (person,)).fetchone()
            people.append(f'{remote["peer_id"]}:{remote["user_id"]}' if remote else f'{self.origin}:{person}')
        return {'id': source_id, 'origin': self.origin, 'source_locator': f'{source_id}?{kind}={version}',
                'source_hash': content_hash(selected), 'revision': f'{kind}:{version}',
                'revision_of': f'{source_id}?{kind}={previous_version}' if previous_version is not None else None,
                'correction_of': [], 'author': f'{self.origin}:{actor}', 'content': selected,
                'audience': {'kind': kind, 'public': content['public'],
                             'people': people,
                             'spaces': [f'{self.origin}:{item}' for item in content['audience_spaces']]}}

    def export(self, actor, data):
        if set(data) - {'selections', 'source_ids'}:
            raise Problem(400, 'Unknown export field')
        selections, sources = data.get('selections', []), data.get('source_ids', [])
        if not isinstance(selections, list) or not isinstance(sources, list) or not 1 <= len(selections) + len(sources) <= 20:
            raise Problem(400, 'Select between 1 and 20 source records')
        with self.store.transaction() as db:
            records = [self._selected(db, actor, item) for item in selections]
            for key in sources:
                text(key, 'source ID', 100)
                row = require(db.execute('SELECT record FROM imported_sources WHERE id=? AND owner_id=?', (key, actor)).fetchone())
                records.append(json.loads(row['record']))
        return validate_document(document(records))

    def import_document(self, actor, value):
        validate_document(value)
        with self.store.transaction() as db:
            return self._import_document(db, actor, value)

    def _import_document(self, db, actor, value):
        """Import an already validated document inside the caller's transaction."""
        result = []
        for record in value['records']:
            serialized = encode(record)
            row = db.execute('SELECT * FROM imported_sources WHERE owner_id=? AND source_id=? AND revision=?', (actor, record['id'], record['revision'])).fetchone()
            if row and row['record'] != serialized:
                raise Problem(409, 'This source revision already has different content or attribution')
            key = row['id'] if row else uid()
            if not row:
                db.execute('INSERT INTO imported_sources VALUES(?,?,?,?,?)', (key, actor, record['id'], record['revision'], serialized))
            result.append({'id': key, 'record': record})
        return {'records': result}

    def sources(self, actor):
        with self.store.transaction() as db:
            return [{'id': r['id'], 'record': json.loads(r['record'])} for r in db.execute('SELECT id,record FROM imported_sources WHERE owner_id=? ORDER BY id', (actor,))]

    def adna(self, actor, key):
        with self.store.transaction() as db:
            row = self.store._owned_layer(db, actor, key)
            require(row['active_revision'])
            record = self._selected(db, actor, {'layer_id': key, 'kind': 'active', 'version': row['active_revision']})
        # A single Markdown knowledge document for what/. JSON literals are YAML
        # values, preventing frontmatter injection; no source paths are executed.
        frontmatter = {'type': 'knowledge', **{k: v for k, v in record.items() if k != 'content'}, 'title': record['content']['title']}
        markdown = '---\n' + '\n'.join(f'{k}: {json.dumps(v, ensure_ascii=True)}' for k, v in frontmatter.items()) + '\n---\n\n' + record['content']['body'] + '\n'
        if '\x00' in markdown:
            raise Problem(400, 'aDNA export cannot contain NUL characters')
        if len(markdown.encode('utf-8')) > ADNA_MAX_BYTES:
            raise Problem(400, 'aDNA export exceeds 65,536 UTF-8 bytes including frontmatter')
        return markdown
