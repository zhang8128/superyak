"""Owner-only drafts and immutable, explicitly activated release snapshots."""
import json
from .common import Problem, text, ids, uid, require, encode

FIELDS = {'title', 'body', 'audience_users', 'audience_spaces', 'public', 'attachment_ids'}
DEFAULT = {'title': 'Untitled', 'body': '', 'audience_users': [], 'audience_spaces': [], 'public': False, 'attachment_ids': []}

class Layers:
    def _draft(self, db, actor, data, previous=None):
        if set(data) - FIELDS - {'version'}:
            raise Problem(400, 'Unknown layer field')
        draft = {**(previous or DEFAULT), **{k: v for k, v in data.items() if k in FIELDS}}
        text(draft['title'], 'title')
        text(draft['body'], 'body', 100000, empty=True)
        if type(draft['public']) is not bool:
            raise Problem(400, 'Invalid public selection')
        for field in ('audience_users', 'audience_spaces', 'attachment_ids'):
            draft[field] = ids(draft[field])
        self._known_contacts(db, draft['audience_users'])
        for key in draft['audience_spaces']:
            self._space(db, key, actor)
        attachment_size = 0
        for key in draft['attachment_ids']:
            attachment_size += require(db.execute('SELECT size FROM files WHERE id=? AND owner_id=?', (key, actor)).fetchone())[0]
        if any(u.startswith('remote_') for u in draft['audience_users']) and attachment_size > 4 * 1024 * 1024:
            raise Problem(400, 'Remote release attachments exceed 4 MiB')
        return draft

    def _owned_layer(self, db, actor, key):
        return require(db.execute('SELECT * FROM layers WHERE id=? AND owner_id=?', (key, actor)).fetchone())

    def _layer_json(self, row):
        return {**json.loads(row['draft']), 'id': row['id'], 'owner_id': row['owner_id'], 'version': row['version'], 'resource_version': row['resource_version'], 'active_revision': row['active_revision'], 'state': 'active' if row['active_revision'] else 'draft'}

    def create_layer(self, actor, data):
        with self.transaction() as db:
            draft = self._draft(db, actor, data)
            key = uid()
            db.execute('INSERT INTO layers(id,owner_id,version,draft) VALUES(?,?,1,?)', (key, actor, encode(draft)))
            return self._layer_json(self._owned_layer(db, actor, key))

    def get_layer(self, actor, key):
        with self.transaction() as db:
            return self._layer_json(self._owned_layer(db, actor, key))

    def list_layers(self, actor):
        with self.transaction() as db:
            return [self._layer_json(r) for r in db.execute('SELECT * FROM layers WHERE owner_id=? ORDER BY id', (actor,))]

    def save_layer(self, actor, key, data):
        with self.transaction() as db:
            row = self._owned_layer(db, actor, key)
            if type(data.get('version')) is not int or data['version'] != row['version']:
                raise Problem(409, 'Draft changed; reload before saving')
            draft = self._draft(db, actor, data, json.loads(row['draft']))
            db.execute('UPDATE layers SET draft=?,version=version+1 WHERE id=?', (encode(draft), key))
            return self._layer_json(self._owned_layer(db, actor, key))

    def activate_layer(self, actor, key, version):
        with self.transaction() as db:
            row = self._owned_layer(db, actor, key)
            if type(version) is not int or version != row['version']:
                raise Problem(409, 'Draft changed; preview this version again')
            snapshot = self._draft(db, actor, json.loads(row['draft']))
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
        content = {'id': key, 'revision': row['revision'], 'title': snapshot['title'], 'body': snapshot['body'], 'attachment_ids': snapshot['attachment_ids']}
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
        return {**snapshot, **permitted, 'owner_id': row['owner_id'], 'draft_version': row['draft_version'], 'created': row['created']}

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
        with self.transaction() as db:
            row = self._owned_layer(db, actor, key)
            return [{**json.loads(r['snapshot']), 'id': key, 'owner_id': row['owner_id'], 'revision': r['revision'], 'draft_version': r['draft_version'], 'created': r['created']} for r in db.execute('SELECT * FROM layer_revisions WHERE layer_id=? ORDER BY revision', (key,))]

    def can_deliver_layer(self, key, actor, resource_version):
        try:
            return self.active_layer(key, actor)['resource_version'] == resource_version
        except Problem as exc:
            if exc.status == 404:
                return False
            raise
