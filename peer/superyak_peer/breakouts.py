"""Breakout rooms (docs/superpowers/specs/2026-10-11-breakout-rooms-design.md): a ship opens a room of its own with
its sibling ships, ones a person already put together in a room. Ships only (D12): no person, and never the system
author, is a member. The opening ship owns the room; owning it is never a person owner's authority (S7)."""
from .common import Problem
from .ships import safe_line

BREAKOUT_SCHEMA = '''
CREATE TABLE IF NOT EXISTS breakouts(room_id TEXT PRIMARY KEY REFERENCES rooms(id), creator_id TEXT NOT NULL REFERENCES users(id), created REAL NOT NULL, closed REAL);
CREATE INDEX IF NOT EXISTS breakouts_by_creator ON breakouts(creator_id, created);
'''
MAX_TITLE = 80
MAX_MEMBERS = 8
OPEN_PER_SHIP = 10
OPENED_PER_DAY = 20
QUIET_SECONDS = 7 * 86400
CLOSED = 'This breakout is closed'
INVITEE_REFUSED = "Every invited ship must be one of your owner's ships that already shares a room with you"
# A person-owned room that a later room (added members) has not replaced. Ship-owned rooms, breakouts, never count.
CURRENT_PERSON_ROOM = '''SELECT rooms.id FROM rooms JOIN users AS owners ON owners.id=rooms.owner_id WHERE owners.kind='person'
    AND rooms.id NOT IN (SELECT linked_room_id FROM rooms WHERE linked_room_id IS NOT NULL)'''


def same_title(title):
    """How two titles are compared for a look-alike (S1): one display line, case-folded."""
    return safe_line(title).casefold()


class Breakouts:
    def _breakout(self, db, room_id):
        return db.execute('SELECT * FROM breakouts WHERE room_id=?', (room_id,)).fetchone()

    def _breakout_closed(self, db, room_id):
        """S4, R6: the one closed check. When the breakout closed, or None while it is open or when the room isn't a
        breakout. Seven days without an ordinary message close it: claim and notice messages (a message_kinds row,
        or the system author's) aren't activity, and a ship's own posts, a watcher's pause note among them, are.
        Activity is the later of the room's creation and its newest ordinary message. The first check that sees the
        seven days pass saves the closure, as of when they ended, so nothing reopens it."""
        row = self._breakout(db, room_id)
        if row is None:
            return None
        if row['closed'] is not None:
            return row['closed']
        latest = db.execute('''SELECT MAX(created) FROM messages WHERE room_id=? AND author_id!=?
            AND id NOT IN (SELECT message_id FROM message_kinds)''', (room_id, self.system_author_id(db))).fetchone()[0]
        activity = max(row['created'], latest or 0.0)
        if self.clock() - activity < QUIET_SECONDS:
            return None
        return self._close_breakout(db, room_id, activity + QUIET_SECONDS)

    def _close_breakout(self, db, room_id, when):
        """Saves the closure once, and drops every member's deferrals in the room, so no session is left marked
        deferred for a mention nobody can answer now."""
        db.execute('UPDATE breakouts SET closed=? WHERE room_id=? AND closed IS NULL', (when, room_id))
        db.execute('DELETE FROM deferrals WHERE message_id IN (SELECT id FROM messages WHERE room_id=?)', (room_id,))
        return self._breakout(db, room_id)['closed']

    def _refuse_closed_breakout(self, db, room_id, status=409):
        """Posts, claims and releases get 409; a ticket gets 422, which the watcher treats as done, silently. Called
        before the path writes anything, so the refusal keeps only a closure this check saved."""
        if self._breakout_closed(db, room_id) is not None:
            raise Problem(status, CLOSED, keep=True)

    def _breakout_mark(self, db, room_id):
        """S6: a breakout's room views carry its creator and when it closed; other rooms get nothing (R10)."""
        row = self._breakout(db, room_id)
        return None if row is None else {'creator': row['creator_id'], 'closed': self._breakout_closed(db, room_id)}

    def _shares_current_room(self, db, a, b):
        return db.execute(f'''SELECT 1 FROM room_members AS x JOIN room_members AS y ON x.room_id=y.room_id
            WHERE x.user_id=? AND y.user_id=? AND x.room_id IN ({CURRENT_PERSON_ROOM})''', (a, b)).fetchone() is not None

    def _invitees(self, db, creator, names):
        """S2: each name a ship of the creator's owner, and every pair of members sharing a current person-owned
        room. Every refusal says the same, so the error never tells which names are people, other owners' ships or
        unknown."""
        found = []
        for name in names:
            row = db.execute('SELECT id,kind,owner_id FROM users WHERE username=?', (name,)).fetchone()
            if row is None or row['kind'] != 'ship' or row['owner_id'] != creator['owner_id']:
                raise Problem(400, INVITEE_REFUSED)
            found.append(row['id'])
        members = [creator['id'], *found]
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if not self._shares_current_room(db, a, b):
                    raise Problem(400, INVITEE_REFUSED)
        return found

    def _refuse_look_alike(self, db, title, members):
        """S1: a title equal to a current person-owned room's that any member is in is refused, so a breakout can't
        pass itself off as one; a title the ship used for its own earlier breakouts stays free."""
        marks = ','.join('?' * len(members))
        taken = {same_title(r[0]) for r in db.execute(f'''SELECT DISTINCT rooms.title FROM rooms JOIN room_members
            ON room_members.room_id=rooms.id WHERE room_members.user_id IN ({marks}) AND rooms.id IN ({CURRENT_PERSON_ROOM})''',
            members)}
        if same_title(title) in taken:
            raise Problem(400, 'That title is already a room title for one of these ships; choose another')

    def open_breakout(self, actor, title, ships):
        """S1, S2: POST /api/ships/me/rooms, under the ship's own key."""
        with self.transaction() as db:
            creator = db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone()
            if creator is None or creator['kind'] != 'ship' or creator['owner_id'] is None:
                raise Problem(403, 'Only a ship with an owner can open a breakout')
            if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE:
                raise Problem(400, f'A breakout title is 1-{MAX_TITLE} characters')
            if not isinstance(ships, list) or any(not isinstance(s, str) or not 0 < len(s) <= 100 for s in ships):
                raise Problem(400, 'ships is a list of ship usernames')
            names = [s for s in dict.fromkeys(ships) if s != creator['username']]
            if not names:
                raise Problem(400, 'Name at least one ship to invite')
            if len(names) + 1 > MAX_MEMBERS:
                raise Problem(400, f'A breakout has at most {MAX_MEMBERS} members, its opener included')
            if self._live_ship_key_in(db, title):
                raise Problem(422, 'This title contains a live ship key, so the breakout was not opened. Treat that key '
                                   'as exposed: its ship should revoke it and dock again.')
            invited = self._invitees(db, creator, names)
            self._refuse_look_alike(db, title, [actor, *invited])
            self._breakout_caps(db, actor)
            room = self._create_room(db, actor, title, invited)
            db.execute('INSERT INTO breakouts(room_id,creator_id,created) VALUES(?,?,?)', (room['id'], actor, self.clock()))
            return self._room(db, actor, room['id'])

    def _breakout_caps(self, db, actor):
        """S5: at most 10 open breakouts per owner ship, each asked of the one closed check, and 20 opened per ship in
        a rolling 24 hours, closed ones included."""
        unsaved = [r[0] for r in db.execute('''SELECT breakouts.room_id FROM breakouts JOIN rooms ON rooms.id=breakouts.room_id
            WHERE rooms.owner_id=? AND breakouts.closed IS NULL''', (actor,))]
        if sum(self._breakout_closed(db, room) is None for room in unsaved) >= OPEN_PER_SHIP:
            raise Problem(429, f'This ship already has {OPEN_PER_SHIP} open breakouts; close one first')
        day = db.execute('SELECT count(*) FROM breakouts WHERE creator_id=? AND created>?', (actor, self.clock() - 86400)).fetchone()[0]
        if day >= OPENED_PER_DAY:
            raise Problem(429, f'This ship opened {OPENED_PER_DAY} breakouts in the last 24 hours; wait before opening another')

    def _member_breakout(self, db, actor, room_id):
        """A breakout the ship is in: 404 when it isn't a member, as for any room; 400 for a room a person manages."""
        room = self._room(db, actor, room_id)
        if 'breakout' not in room:
            raise Problem(400, "This room isn't a breakout; a person manages its members")
        return room

    def close_breakout(self, actor, room_id):
        """S4: the owner ship closes its breakout. Closing a closed one changes nothing."""
        with self.transaction() as db:
            room = self._member_breakout(db, actor, room_id)
            if room['owner_id'] != actor:
                raise Problem(403, 'Only the ship that opened this breakout can close it')
            if self._breakout_closed(db, room_id) is None:
                self._close_breakout(db, room_id, self.clock())
            return self._room(db, actor, room_id)

    def leave_breakout(self, actor, room_id):
        """S3: any member ship leaves, which drops its own deferrals there; its later tickets for the room get 404. The
        owner leaving closes the room. Leaving never adds anyone, and nothing else changes the membership."""
        with self.transaction() as db:
            room = self._member_breakout(db, actor, room_id)
            db.execute('DELETE FROM deferrals WHERE ship_id=? AND message_id IN (SELECT id FROM messages WHERE room_id=?)', (actor, room_id))
            db.execute('DELETE FROM room_members WHERE room_id=? AND user_id=?', (room_id, actor))
            db.execute('UPDATE rooms SET epoch=epoch+1 WHERE id=?', (room_id,))
            self.emit(db, 'chat.membership', room_id, room['epoch'] + 1, {'left_user_id': actor})
            closed = self._breakout_closed(db, room_id)
            if room['owner_id'] == actor and closed is None:
                closed = self._close_breakout(db, room_id, self.clock())
            return {'room_id': room_id, 'left': True, 'closed': closed}
