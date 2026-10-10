"""Explicit space membership; display names have no permission semantics."""
from .common import Problem, text, ids, uid, require

class Spaces:
    def _known_users(self, db, members):
        for key in members:
            require(db.execute("SELECT id FROM users WHERE id=? AND kind!='system'", (key,)).fetchone())  # R34

    def contacts(self, actor):
        # Accounts on this explicitly provisioned host are known local contacts.
        with self.transaction() as db:
            return [dict(r) for r in db.execute("SELECT id,name FROM users WHERE id!=? AND kind!='system' ORDER BY name,id", (actor,))]  # R34

    def _space(self, db, key, actor):
        row = require(db.execute('SELECT spaces.* FROM spaces JOIN space_members ON spaces.id=space_members.space_id WHERE spaces.id=? AND user_id=?', (key, actor)).fetchone())
        members = [r[0] for r in db.execute('SELECT user_id FROM space_members WHERE space_id=? ORDER BY user_id', (key,))]
        return {**dict(row), 'member_ids': members, 'audience_note': 'Current and future members can see active releases explicitly shared with this space.' if row['kind'] == 'organization' else 'Select people explicitly when sharing with this care circle or project.'}

    def create_space(self, actor, name, kind, member_ids=None):
        text(name, 'name')
        if kind not in ('care-circle', 'project', 'organization'):
            raise Problem(400, 'Invalid space kind')
        members = ids([actor] + ids(member_ids if member_ids is not None else []))
        with self.transaction() as db:
            self._known_users(db, members)
            key = uid()
            db.execute('INSERT INTO spaces VALUES(?,?,?,?,1)', (key, actor, name, kind))
            db.executemany('INSERT INTO space_members VALUES(?,?)', [(key, member) for member in members])
            return self._space(db, key, actor)

    def list_spaces(self, actor):
        with self.transaction() as db:
            return [self._space(db, r[0], actor) for r in db.execute('SELECT space_id FROM space_members WHERE user_id=? ORDER BY space_id', (actor,)).fetchall()]

    def get_space(self, actor, key):
        with self.transaction() as db:
            return self._space(db, key, actor)

    def rename_space(self, actor, key, name):
        text(name, 'name')
        with self.transaction() as db:
            space = self._space(db, key, actor)
            if space['owner_id'] != actor:
                raise Problem(403, 'Space owner required')
            db.execute('UPDATE spaces SET name=?,version=version+1 WHERE id=?', (name, key))
            return self._space(db, key, actor)

    def change_space_member(self, actor, key, user_id, *, remove=False):
        with self.transaction() as db:
            space = self._space(db, key, actor)
            if space['owner_id'] != actor:
                raise Problem(403, 'Space owner required')
            text(user_id, 'user ID', 100)
            self._known_users(db, [user_id])
            if remove and user_id == actor:
                raise Problem(400, 'Cannot remove the space owner')
            if remove:
                db.execute('DELETE FROM space_members WHERE space_id=? AND user_id=?', (key, user_id))
            else:
                db.execute('INSERT OR IGNORE INTO space_members VALUES(?,?)', (key, user_id))
            db.execute('UPDATE spaces SET version=version+1 WHERE id=?', (key,))
            self.emit(db, 'space.membership', key, space['version'] + 1, {'user_id': user_id, 'removed': remove})
            return self._space(db, key, actor)
