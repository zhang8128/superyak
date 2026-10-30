"""Remote connector, Task 9a: Connected apps, the admins' view, the new-connection notice and why each connection ended
(spec "Receipts and revoking"; board build:connector-revoke-reason). A person sees and changes only their own
connections; a super admin sees each connection's person, app and times, and can end it, but never its rooms, its
receipts or why it ended (G11, "No one else sees a grant, an admin included"). Room titles are resolved when shown,
never stored. Every row is read through guards, so one a restore left damaged never breaks a list (the section 2's M1)."""
import json
import math

from .common import Problem
from .connector import REVOKED

NOTICE_SECONDS = 7 * 86400  # "Claude was connected on <date>. Not you? Revoke." shows this long after a connection
RECEIPTS_LIMIT, RECEIPTS_MAX = 100, 500  # a page of receipts: one connection at its limit for 30 days has 60,000
NO_SUCH = 'No such connection'
ENDED = 'This connection has ended'
ROOMS_SHAPE = 'rooms is "*" or a list of the rooms you are in, each listed once'
MARKED = 'A member of that room keeps it away from cloud models, so no connection can read it'
PAGE = f'limit is a whole number from 1 to {RECEIPTS_MAX}, and before is a cursor from an earlier page'


def _number(value):
    """A time as it is sent: a finite number, else None. JSONResponse refuses inf, and a restore can leave one (M1)."""
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _list(value, item=str):
    """A JSON list of `item`s stored in a row, or None when it can't be read (M1)."""
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, RecursionError):
        return None
    return parsed if isinstance(parsed, list) and all(isinstance(entry, item) for entry in parsed) else None


class ConnectorApps:
    def _connection(self, db, actor, grant_id):
        """The person's own connection by id, else 404, whoever else holds it (G11's answer for another's)."""
        row = db.execute('SELECT * FROM connector_grants WHERE id=? AND person_id=?',
                         (grant_id if isinstance(grant_id, str) else '', actor)).fetchone()
        if row is None:
            raise Problem(404, NO_SUCH)
        return row

    def _ended(self, row, now):
        """When and why a connection ended, or None while it's live. An end that isn't a finite number is damaged: no
        token can use it (_live_grant), so it reads as ended. A reason nobody recorded is `unknown` (N1)."""
        if row['revoked'] is not None:
            return {'at': _number(row['revoked']), 'why': row['revoked_why'] or 'unknown'}
        ends = _number(row['ends'])
        if ends is None:
            return {'at': None, 'why': 'damaged'}
        return {'at': ends, 'why': 'ended'} if not now < ends else None

    def _titled(self, db, actor, room_id):
        from .grants import NOT_IN_ROOM
        return self._member_title(db, actor, room_id) or NOT_IN_ROOM

    def _last_used(self, db, row):
        """The later of the row's last use and its newest receipt: after a restore the row is the copy's (N4)."""
        newest = db.execute('SELECT max(at) FROM connector_reads WHERE grant_id=?', (row['id'],)).fetchone()[0]
        return max((at for at in (_number(row['last_used']), _number(newest)) if at is not None), default=None)

    def _app_entry(self, db, actor, row, now):
        ended, all_rooms = self._ended(row, now), row['rooms'] == '*'
        ids = [] if all_rooms else _list(row['rooms'])
        rooms = []
        for room_id in ids or []:
            later = self._current_room(db, room_id)
            offer = later if later and not self._marked(db, later) else None  # a marked room is never offered (S3)
            title = self._member_title(db, actor, offer) if offer else None
            rooms.append({'room': room_id, 'title': self._titled(db, actor, room_id), 'cloud': self._marked(db, room_id),
                          'continues_in': {'room': offer, 'title': title} if title is not None else None})
        usable = ended is None and db.execute('SELECT 1 FROM connector_tokens WHERE grant_id=? AND expires>? LIMIT 1',
                                              (row['id'], now)).fetchone() is not None
        entry = {'id': row['id'], 'app': row['redirect_host'], 'created': _number(row['created']),
                 'last_used': self._last_used(db, row), 'ends': _number(row['ends']), 'rooms': rooms,
                 'all_rooms': all_rooms, 'ended': ended, 'usable': usable}
        return entry | ({'damaged': True} if ids is None else {})

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
                apps.append({'id': row['grant_id'], 'app': row['app'], 'created': _number(row['first']),
                             'last_used': _number(row['last']), 'ends': None, 'rooms': [], 'all_rooms': False,
                             'ended': {'at': None, 'why': 'restore'}, 'usable': False})
            return apps

    def connected_app_rooms(self, actor, grant_id, rooms):
        """Change which rooms a live connection reads, on its next call: "*" or a list of the person's current, unmarked
        rooms (Task 5's choice), plus any room already in this connection that the person is still in and that no one
        has marked, so it can be narrowed without being widened (S2). A room that continues in a newer one is offered,
        never added for them (spec "A listed room covers that room only")."""
        with self.transaction() as db:
            row = self._connection(db, actor, grant_id)
            if self._ended(row, self.clock()) is not None:
                raise Problem(409, ENDED)
            if not (rooms == '*' or isinstance(rooms, list) and rooms and all(isinstance(room, str) for room in rooms)
                    and len(set(rooms)) == len(rooms)):
                raise Problem(400, ROOMS_SHAPE)
            if rooms != '*':
                if any(self._member_title(db, actor, room) is not None and self._marked(db, room) for room in rooms):
                    raise Problem(400, MARKED)
                kept = [] if row['rooms'] == '*' else _list(row['rooms']) or []
                choosable = {room['room'] for room in self._consent_rooms(db, actor)
                             if room['earlier_of'] is None and not room['cloud']}
                # S2: still in it and unmarked. The mark is checked again here though a marked room was refused above in
                # its own words: the allowlist fails closed on its own, whatever becomes of that refusal (a second gate,
                # so its mutant is equivalent by design; the automated security review on 9bc91f6f)
                choosable |= {room for room in kept
                              if self._member_title(db, actor, room) is not None and not self._marked(db, room)}
                if not set(rooms) <= choosable:
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

    def connected_app_receipts(self, actor, grant_id, limit=RECEIPTS_LIMIT, before=None):
        """What a connection read, newest first, a page at a time (S1): `limit` receipts, and `before`, the cursor for
        the next page, or None. Rooms are named by title as the person sees them now, each looked up once a page. A
        connection a restore removed is found by its receipts, which name their person."""
        if type(limit) is not int or not 1 <= limit <= RECEIPTS_MAX or before is not None and (type(before) is not int
                                                                                                or before < 0):
            raise Problem(400, PAGE)
        with self.transaction() as db:
            self._person(db, actor)
            owned = isinstance(grant_id, str) and db.execute(
                'SELECT 1 FROM connector_grants WHERE id=? AND person_id=? UNION ALL SELECT 1 FROM connector_reads WHERE '
                'grant_id=? AND person_id=? AND grant_id NOT IN (SELECT id FROM connector_grants)',
                (grant_id, actor, grant_id, actor)).fetchone()
            if not owned:
                raise Problem(404, NO_SUCH)
            rows = db.execute('SELECT rowid AS position, * FROM connector_reads WHERE grant_id=? AND person_id=? '
                              + ('AND rowid<? ' if before is not None else '') + 'ORDER BY rowid DESC LIMIT ?',
                              (grant_id, actor, *(() if before is None else (before,)), limit + 1)).fetchall()
            titles = {}

            def titled(room):
                if room not in titles:
                    titles[room] = self._titled(db, actor, room)
                return titles[room]
            receipts = []
            for row in rows[:limit]:
                refused = [item for item in _list(row['rooms_refused'], dict) or []
                           if isinstance(item.get('room'), str)]
                receipts.append({'at': _number(row['at']), 'tool': row['tool'], 'size': row['size'],
                                 'outcome': row['outcome'],
                                 'rooms_read': [{'room': room, 'title': titled(room)} for room in _list(row['rooms_read']) or []],
                                 'rooms_refused': [{'room': item['room'], 'title': titled(item['room']), 'why': item.get('why')}
                                                   for item in refused]})
            return {'receipts': receipts, 'before': rows[limit - 1]['position'] if len(rows) > limit else None}

    def connected_app_notice(self, actor):
        """{id, app, created} for the newest connection made in the last 7 days that is still live, else None: a stolen
        password then doesn't quietly become 30 days of reading (spec "The new-connection notice")."""
        with self.transaction() as db:
            self._person(db, actor)
            now = self.clock()
            row = db.execute('SELECT id, redirect_host, created FROM connector_grants WHERE person_id=? AND created>? '
                             'AND revoked IS NULL AND ends>? ORDER BY created DESC, id LIMIT 1',
                             (actor, now - NOTICE_SECONDS, now)).fetchone()
            return {'id': row['id'], 'app': row['redirect_host'], 'created': _number(row['created'])} if row else None

    def admin_connected_apps(self, actor):
        """The home's super admins see each connection's person (by display name), app, created, last used and end, and
        when it ended, never its rooms, its receipts or why it ended: "you" says what a person chose, and
        "refresh_reused" points at a theft, both the person's to see first (S4, Rio Grande)."""
        with self.transaction() as db:
            self._super_admin(db, actor)
            now = self.clock()
            items = []
            for row in db.execute('SELECT connector_grants.*, users.name FROM connector_grants JOIN users ON '
                                  'users.id=connector_grants.person_id ORDER BY created DESC, connector_grants.id').fetchall():
                ended = self._ended(row, now)
                items.append({'id': row['id'], 'person': row['name'], 'app': row['redirect_host'],
                              'created': _number(row['created']), 'last_used': self._last_used(db, row),
                              'ends': _number(row['ends']), 'ended': {'at': ended['at']} if ended else None})
            return items

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
