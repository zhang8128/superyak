"""Remote connector, Task 9a: Connected apps, the admins' view, the new-connection notice and why each connection ended
(spec "Receipts and revoking"; board build:connector-revoke-reason). A person sees and changes only their own
connections; a super admin sees each connection's person, app and times, and can end it, but never its rooms or its
receipts (G11, "No one else sees a grant, an admin included"). Room titles are resolved when shown, never stored."""
import json

from .common import Problem
from .connector import REVOKED

NOTICE_SECONDS = 7 * 86400  # "Claude was connected on <date>. Not you? Revoke." shows this long after a connection
NO_SUCH = 'No such connection'
ENDED = 'This connection has ended'
ROOMS_SHAPE = 'rooms is "*" or a list of the rooms you are in, each listed once'
# Why a connection ended (connector_grants.revoked_why): you, an admin, a code used twice, a refresh token used again
# after 60 s, a split refresh chain, or a restore. A connection that ran to its end has none.
WHYS = ('you', 'admin', 'code_reused', 'refresh_reused', 'split_chain', 'restore')


class ConnectorApps:
    def _connection(self, db, actor, grant_id):
        """The person's own connection by id, else 404, whoever else holds it (G11's answer for another's)."""
        row = db.execute('SELECT * FROM connector_grants WHERE id=? AND person_id=?',
                         (grant_id if isinstance(grant_id, str) else '', actor)).fetchone()
        if row is None:
            raise Problem(404, NO_SUCH)
        return row

    def _ended(self, row, now):
        if row['revoked'] is not None:
            return {'at': row['revoked'], 'why': row['revoked_why'] or 'restore'}
        return {'at': row['ends'], 'why': 'ended'} if not now < row['ends'] else None

    def _titled(self, db, actor, room_id):
        from .grants import NOT_IN_ROOM
        return self._member_title(db, actor, room_id) or NOT_IN_ROOM

    def _app_entry(self, db, actor, row, now):
        ended = self._ended(row, now)
        rooms = []
        if row['rooms'] != '*':
            for room_id in json.loads(row['rooms']):
                later = self._current_room(db, room_id)
                title = self._member_title(db, actor, later) if later else None
                rooms.append({'room': room_id, 'title': self._titled(db, actor, room_id),
                              'continues_in': {'room': later, 'title': title} if title is not None else None})
        usable = ended is None and db.execute('SELECT 1 FROM connector_tokens WHERE grant_id=? AND expires>? LIMIT 1',
                                              (row['id'], now)).fetchone() is not None
        return {'id': row['id'], 'app': row['redirect_host'], 'created': row['created'], 'last_used': row['last_used'],
                'ends': row['ends'], 'rooms': rooms, 'all_rooms': row['rooms'] == '*', 'ended': ended, 'usable': usable}

    def connected_apps(self, actor):
        """The person's connections, newest first, and, after a restore removed one, its receipts' connection as
        ended by the restore, so what it read stays visible (Rio Grande and Tardis, on Task 8's restore design)."""
        with self.transaction() as db:
            self._person(db, actor)
            now = self.clock()
            apps = [self._app_entry(db, actor, row, now) for row in db.execute(
                'SELECT * FROM connector_grants WHERE person_id=? ORDER BY created DESC, id', (actor,)).fetchall()]
            for row in db.execute('SELECT grant_id, app, min(at) AS first, max(at) AS last FROM connector_reads WHERE '
                                  'person_id=? AND grant_id NOT IN (SELECT id FROM connector_grants) GROUP BY grant_id, app '
                                  'ORDER BY last DESC', (actor,)).fetchall():
                apps.append({'id': row['grant_id'], 'app': row['app'], 'created': row['first'], 'last_used': row['last'],
                             'ends': None, 'rooms': [], 'all_rooms': False, 'ended': {'at': None, 'why': 'restore'},
                             'usable': False})
            return apps

    def connected_app_rooms(self, actor, grant_id, rooms):
        """Change which rooms a live connection reads, on its next call: "*" or a list of the person's current,
        unmarked rooms (Task 5's choice, checked the same way). A room that continues in a newer one is offered, never
        added for them (spec "A listed room covers that room only")."""
        with self.transaction() as db:
            row = self._connection(db, actor, grant_id)
            if self._ended(row, self.clock()) is not None:
                raise Problem(409, ENDED)
            choosable = {room['room'] for room in self._consent_rooms(db, actor)
                         if room['earlier_of'] is None and not room['cloud']}
            if not (rooms == '*' or isinstance(rooms, list) and rooms and all(isinstance(room, str) for room in rooms)
                    and len(set(rooms)) == len(rooms) and set(rooms) <= choosable):
                raise Problem(400, ROOMS_SHAPE)
            db.execute('UPDATE connector_grants SET rooms=? WHERE id=?', ('*' if rooms == '*' else json.dumps(rooms), row['id']))
            return self._app_entry(db, actor, self._connection(db, actor, grant_id), self.clock())

    def _end_connection(self, db, grant_id, why):
        """Revoke ends it at once: the grant is revoked and every token it holds ends as a fact (REVOKED)."""
        db.execute('UPDATE connector_grants SET revoked=?, revoked_why=? WHERE id=? AND revoked IS NULL',
                   (self.clock(), why, grant_id))
        db.execute('UPDATE connector_tokens SET expires=? WHERE grant_id=? AND expires>?', (REVOKED, grant_id, REVOKED))

    def connected_app_revoke(self, actor, grant_id):
        with self.transaction() as db:
            row = self._connection(db, actor, grant_id)
            if self._ended(row, self.clock()) is not None:  # its record stays true: "ended", or who ended it (Tardis)
                raise Problem(409, ENDED)
            self._end_connection(db, row['id'], 'you')
            return self._app_entry(db, actor, self._connection(db, actor, grant_id), self.clock())

    def connected_app_receipts(self, actor, grant_id):
        """What a connection read, newest first, its rooms named by title as the person sees them now. A connection a
        restore removed is found by its receipts, which name their person."""
        with self.transaction() as db:
            self._person(db, actor)
            owned = isinstance(grant_id, str) and db.execute(
                'SELECT 1 FROM connector_grants WHERE id=? AND person_id=? UNION ALL SELECT 1 FROM connector_reads WHERE '
                'grant_id=? AND person_id=? AND grant_id NOT IN (SELECT id FROM connector_grants)',
                (grant_id, actor, grant_id, actor)).fetchone()
            if not owned:
                raise Problem(404, NO_SUCH)
            receipts = []
            for row in db.execute('SELECT * FROM connector_reads WHERE grant_id=? AND person_id=? ORDER BY at DESC, rowid DESC',
                                  (grant_id, actor)).fetchall():
                receipts.append({'at': row['at'], 'tool': row['tool'], 'size': row['size'], 'outcome': row['outcome'],
                                 'rooms_read': [{'room': room, 'title': self._titled(db, actor, room)}
                                                for room in json.loads(row['rooms_read'])],
                                 'rooms_refused': [{'room': item['room'], 'title': self._titled(db, actor, item['room']),
                                                    'why': item['why']} for item in json.loads(row['rooms_refused'])]})
            return receipts

    def connected_app_notice(self, actor):
        """{id, app, created} for the newest connection made in the last 7 days that is still live, else None: a stolen
        password then doesn't quietly become 30 days of reading (spec "The new-connection notice")."""
        with self.transaction() as db:
            self._person(db, actor)
            now = self.clock()
            row = db.execute('SELECT id, redirect_host, created FROM connector_grants WHERE person_id=? AND created>? '
                             'AND revoked IS NULL AND ends>? ORDER BY created DESC, id LIMIT 1',
                             (actor, now - NOTICE_SECONDS, now)).fetchone()
            return {'id': row['id'], 'app': row['redirect_host'], 'created': row['created']} if row else None

    def admin_connected_apps(self, actor):
        """The home's super admins see each connection's person (by display name), app, created, last used and end, and
        whether it ended, never its rooms or its receipts (G11)."""
        with self.transaction() as db:
            self._super_admin(db, actor)
            now = self.clock()
            return [{'id': row['id'], 'person': row['name'], 'app': row['redirect_host'], 'created': row['created'],
                     'last_used': row['last_used'], 'ends': row['ends'], 'ended': self._ended(row, now)}
                    for row in db.execute('SELECT connector_grants.*, users.name FROM connector_grants JOIN users ON '
                                          'users.id=connector_grants.person_id ORDER BY created DESC, connector_grants.id')]

    def admin_connected_app_revoke(self, actor, grant_id):
        with self.transaction() as db:
            self._super_admin(db, actor)
            row = db.execute('SELECT * FROM connector_grants WHERE id=?', (grant_id if isinstance(grant_id, str) else '',)).fetchone()
            if row is None:
                raise Problem(404, NO_SUCH)
            if self._ended(row, self.clock()) is not None:
                raise Problem(409, ENDED)
            self._end_connection(db, row['id'], 'admin')
            return {'id': row['id'], 'ended': True}
