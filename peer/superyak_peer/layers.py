"""Owner-only drafts and immutable, explicitly activated release snapshots."""
import json
from .common import Problem, text, ids, uid, require, encode

FIELDS = {'kind', 'title', 'body', 'audience_users', 'audience_spaces', 'public', 'attachment_ids'}
DEFAULT = {'kind': 'note', 'title': 'Untitled', 'body': '', 'audience_users': [], 'audience_spaces': [], 'public': False, 'attachment_ids': []}
SERVER_KEYS = {'drafted_by', 'drafted_at'}

class Layers:
    def _draft(self, db, actor, data, previous=None, stored=False):
        if set(data) - (FIELDS | {'version'} | (SERVER_KEYS if stored else set())):
            raise Problem(400, 'Unknown layer field')
        draft = {**DEFAULT, **(previous or {}), **{k: v for k, v in data.items() if k in FIELDS or (stored and k in SERVER_KEYS)}}
        if draft['kind'] not in ('note', 'instructions'):
            raise Problem(400, 'Invalid layer kind')
        text(draft['title'], 'title')
        text(draft['body'], 'body', 100000, empty=True)
        if self._live_ship_key_in(db, draft['title']) or self._live_ship_key_in(db, draft['body']):
            raise Problem(422, 'This layer contains a live ship key, so it was not saved. Treat that key as exposed: '
                               'its ship should revoke it and dock again.')
        if type(draft['public']) is not bool:
            raise Problem(400, 'Invalid public selection')
        for field in ('audience_users', 'audience_spaces', 'attachment_ids'):
            draft[field] = ids(draft[field])
        if draft['kind'] == 'instructions':
            title = draft['title']
            if len(title) > 200 or title.splitlines() != [title]:
                raise Problem(400, 'An instructions title is one line of at most 200 characters')
            if len(draft['body']) > 20000:
                raise Problem(400, 'Instructions are at most 20,000 characters')
            if '\x00' in title or '\x00' in draft['body']:
                raise Problem(400, 'Instructions cannot contain a NUL character')
            if draft['audience_spaces'] or draft['public'] or draft['attachment_ids']:
                raise Problem(400, 'Instructions go to ships only')
            if len(draft['audience_users']) > 50:
                raise Problem(400, 'Too many ships')
            for ship_id in draft['audience_users']:
                if not db.execute("SELECT 1 FROM users WHERE id=? AND kind='ship'", (ship_id,)).fetchone():
                    raise Problem(400, 'Instructions go to ships only')
        self._known_contacts(db, draft['audience_users'])
        for key in draft['audience_spaces']:
            self._space(db, key, actor)
        attachment_size = 0
        for key in draft['attachment_ids']:
            attachment_size += require(db.execute('SELECT size FROM files WHERE id=? AND owner_id=?', (key, actor)).fetchone())[0]
        if any(u.startswith('remote_') for u in draft['audience_users']) and attachment_size > 4 * 1024 * 1024:
            raise Problem(400, 'Remote release attachments exceed 4 MiB')
        if draft['kind'] == 'note':
            del draft['kind']  # never stored for a note: a rolled-back station refuses any key it does not know
        return draft

    def _owned_layer(self, db, actor, key):
        return require(db.execute('SELECT * FROM layers WHERE id=? AND owner_id=?', (key, actor)).fetchone())

    def _layer_json(self, row):
        return {'kind': 'note', **json.loads(row['draft']), 'id': row['id'], 'owner_id': row['owner_id'], 'version': row['version'], 'resource_version': row['resource_version'], 'active_revision': row['active_revision'], 'state': 'active' if row['active_revision'] else 'draft'}

    def create_layer(self, actor, data):
        with self.transaction() as db:
            draft = self._draft(db, actor, data)
            key = uid()
            db.execute('INSERT INTO layers(id,owner_id,version,draft) VALUES(?,?,1,?)', (key, actor, encode(draft)))
            return self._layer_json(self._owned_layer(db, actor, key))

    def get_layer(self, actor, key):
        with self.reading() as db:
            return self._layer_json(self._owned_layer(db, actor, key))

    def list_layers(self, actor):
        with self.reading() as db:
            return [self._layer_json(r) for r in db.execute('SELECT * FROM layers WHERE owner_id=? ORDER BY id', (actor,))]

    def save_layer(self, actor, key, data):
        with self.transaction() as db:
            row = self._owned_layer(db, actor, key)
            if type(data.get('version')) is not int or data['version'] != row['version']:
                raise Problem(409, 'Draft changed; reload before saving')
            draft = self._draft(db, actor, data, json.loads(row['draft']))
            db.execute('UPDATE layers SET draft=?,version=version+1 WHERE id=?', (encode(draft), key))
            return self._layer_json(self._owned_layer(db, actor, key))

    def _audience_details(self, db, snapshot):
        details = []
        for key in snapshot['audience_spaces']:
            space = require(db.execute('SELECT * FROM spaces WHERE id=?', (key,)).fetchone())
            frozen = snapshot.get('resolved_space_users', {}).get(key)
            members = frozen if frozen is not None else [r[0] for r in db.execute('SELECT user_id FROM space_members WHERE space_id=? ORDER BY user_id', (key,))]
            details.append({'id':key, 'name':space['name'], 'kind':space['kind'], 'version':space['version'],
                            'members':[dict(require(db.execute('SELECT id,name FROM users WHERE id=?', (member,)).fetchone())) for member in members],
                            'membership':'current-and-future' if space['kind'] == 'organization' else 'selected'})
        return details

    def preview_layer(self, actor, key):
        with self.transaction() as db:
            row = self._owned_layer(db, actor, key)
            draft = self._draft(db, actor, json.loads(row['draft']), stored=True)
            details = self._audience_details(db, draft)
            files = [dict(require(db.execute('SELECT id,name,media_type,size,digest FROM files WHERE id=? AND owner_id=?', (fid,actor)).fetchone())) for fid in draft['attachment_ids']]
            people = []
            for contact in draft['audience_users']:
                table = 'remote_contacts' if contact.startswith('remote_') else 'users'
                people.append(dict(require(db.execute(f'SELECT id,name FROM {table} WHERE id=?', (contact,)).fetchone())))
            return {**self._layer_json(row), 'files':files, 'people':people, 'audience_details':details,
                    'space_versions':{space['id']:space['version'] for space in details}}

    def activate_layer(self, actor, key, version, space_versions=None):
        with self.transaction() as db:
            row = self._owned_layer(db, actor, key)
            if type(version) is not int or version != row['version']:
                raise Problem(409, 'Draft changed; preview this version again')
            snapshot = self._draft(db, actor, json.loads(row['draft']), stored=True)
            if snapshot.get('kind') == 'instructions':
                self._check_instruction_caps(db, actor, key, snapshot)
            if space_versions is not None:
                current = {space['id']:space['version'] for space in self._audience_details(db, snapshot)}
                if not isinstance(space_versions, dict) or space_versions != current:
                    raise Problem(409, 'Space membership changed; preview this version again')
            snapshot['resolved_space_users'] = {}
            snapshot['audience_notes'] = []
            for space_id in snapshot['audience_spaces']:
                space = self._space(db, space_id, actor)
                if space['kind'] != 'organization':
                    snapshot['resolved_space_users'][space_id] = space['member_ids']
                    snapshot['audience_notes'].append('Selected people in ' + space['name'] + ' at activation')
                else:
                    snapshot['audience_notes'].append('Current and future members of ' + space['name'])
            revision = row['resource_version'] + 1
            db.execute('INSERT INTO layer_revisions VALUES(?,?,?,?,?)', (key, revision, version, encode(snapshot), self.clock()))
            self._sign_revision(db, key, revision)  # spec A step 3, G2: an instructions revision is signed as it is written
            db.execute('UPDATE layers SET active_revision=?,resource_version=? WHERE id=?', (revision, revision, key))
            self.emit(db, 'layer.activated', key, revision, {'owner_id': actor, 'draft_version': version})
            return self._active_layer(db, key, actor)

    def withdraw_layer(self, actor, key):
        with self.transaction() as db:
            row = self._owned_layer(db, actor, key)
            if row['active_revision'] is not None:
                revision = row['resource_version'] + 1
                db.execute('UPDATE layers SET active_revision=NULL,resource_version=? WHERE id=?', (revision, key))
                self.emit(db, 'layer.withdrawn', key, revision, {'owner_id': actor})
            return self._layer_json(self._owned_layer(db, actor, key))

    def revoke_layer_routes(self, actor, key, data):
        """Narrow active grants without publishing or modifying the private draft."""
        if set(data) - {'revision', 'public', 'user_ids', 'space_ids'}:
            raise Problem(400, 'Unknown revocation field')
        users, spaces = ids(data.get('user_ids', [])), ids(data.get('space_ids', []))
        if type(data.get('public', False)) is not bool:
            raise Problem(400, 'Invalid public revocation')
        with self.transaction() as db:
            row = self._owned_layer(db, actor, key)
            if type(data.get('revision')) is not int or data['revision'] != row['active_revision']:
                raise Problem(409, 'Active release changed; reload before revoking')
            active = db.execute('SELECT * FROM layer_revisions WHERE layer_id=? AND revision=?', (key, row['active_revision'])).fetchone()
            snapshot = json.loads(active['snapshot'])
            snapshot['audience_users'] = [u for u in snapshot['audience_users'] if u not in users]
            snapshot['audience_notes'] = [note for space, note in zip(snapshot['audience_spaces'], snapshot['audience_notes']) if space not in spaces]
            snapshot['audience_spaces'] = [s for s in snapshot['audience_spaces'] if s not in spaces]
            snapshot['resolved_space_users'] = {s: members for s, members in snapshot['resolved_space_users'].items() if s not in spaces}
            if data.get('public'):
                snapshot['public'] = False
            revision = row['resource_version'] + 1
            db.execute('INSERT INTO layer_revisions VALUES(?,?,?,?,?)', (key, revision, active['draft_version'], encode(snapshot), self.clock()))
            self._sign_revision(db, key, revision)  # G2: the narrowing's new revision, with its narrower audience
            db.execute('UPDATE layers SET active_revision=?,resource_version=? WHERE id=?', (revision, revision, key))
            self.emit(db, 'layer.restricted', key, revision, {'owner_id': actor, 'previous_revision': row['active_revision']})
            return self._active_layer(db, key, actor)

    def _access_routes(self, db, row, snapshot, actor):
        routes = []
        if row['owner_id'] == actor:
            routes.append('owner')
        if actor in snapshot['audience_users']:
            routes.append('person')
        for key in snapshot['audience_spaces']:
            frozen = snapshot['resolved_space_users'].get(key)
            allowed = actor in frozen if frozen is not None else db.execute('SELECT 1 FROM space_members WHERE space_id=? AND user_id=?', (key, actor)).fetchone()
            if allowed:
                routes.append('space:' + key)
        if snapshot['public']:
            routes.append('public')
        return routes

    def _active_layer(self, db, key, actor=None, *, public=False):
        text(key, 'layer ID', 100)
        if actor is not None:
            text(actor, 'actor ID', 100)
        row = require(db.execute('SELECT layers.id,layers.owner_id,layers.resource_version,layer_revisions.* FROM layers JOIN layer_revisions ON layers.id=layer_revisions.layer_id AND layers.active_revision=layer_revisions.revision WHERE layers.id=?', (key,)).fetchone())
        snapshot = json.loads(row['snapshot'])
        content = {'id': key, 'revision': row['revision'], 'title': snapshot['title'], 'body': snapshot['body'], 'kind': snapshot.get('kind', 'note'), 'attachment_ids': snapshot['attachment_ids']}
        if public:
            if not snapshot['public']:
                raise Problem(404, 'Not found')
            return content
        routes = self._access_routes(db, row, snapshot, actor)
        if not routes:
            raise Problem(404, 'Not found')
        permitted = {**content, 'resource_version': row['resource_version'], 'access_routes': routes}
        if routes == ['public']:
            return permitted
        if actor != row['owner_id']:
            return {**permitted, 'owner_id': row['owner_id'], 'created': row['created']}
        return {**snapshot, **permitted, 'audience_details':self._audience_details(db, snapshot), 'owner_id': row['owner_id'], 'draft_version': row['draft_version'], 'created': row['created']}

    def active_layer(self, key, actor=None, *, public=False):
        """Rechecks current release/access. actor is a trusted local ID, never browser input."""
        if ":" in key:
            if public or actor is None:
                raise Problem(404, "Not found")
            return self.remote_layer(actor, key)
        with self.transaction() as db:
            return self._active_layer(db, key, actor, public=public)

    def shared_layers(self, actor):
        with self.transaction() as db:
            result = []
            for row in db.execute('SELECT id FROM layers WHERE active_revision IS NOT NULL ORDER BY id').fetchall():
                try:
                    result.append(self._active_layer(db, row['id'], actor))
                except Problem as exc:
                    if exc.status != 404:
                        raise
        return result + self.remote_layers(actor)

    def layer_revisions(self, actor, key):
        with self.reading() as db:
            row = self._owned_layer(db, actor, key)
            return [{'kind': 'note', **json.loads(r['snapshot']), 'id': key, 'owner_id': row['owner_id'], 'revision': r['revision'], 'draft_version': r['draft_version'], 'created': r['created']} for r in db.execute('SELECT * FROM layer_revisions WHERE layer_id=? ORDER BY revision', (key,))]

    def can_deliver_layer(self, key, actor, resource_version):
        try:
            return self.active_layer(key, actor)['resource_version'] == resource_version
        except Problem as exc:
            if exc.status == 404:
                return False
            raise
