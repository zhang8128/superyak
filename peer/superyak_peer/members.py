"""Room moderators: every membership change of a room goes through the helpers here (spec M7, M8, M14). An add is one
transaction: the checks, the new linked room, each member's row in the act log (`member_changes`) and the one notice
the system author posts in the new room. The owner's routes (the participants route, make station-bridge and
make station-add-ship) call `_add_members`; a moderator's path joins `add_participants` in a later task."""
from .common import REPLACED_ADD, REPLACED_ROOMS, Problem, ids, uid
from .ships import safe_line

NOT_A_MODERATOR = "Only the room's owner or one of its moderators can change its members"
NO_ONE_NEW = 'Everyone named is already a member of room {short}; nothing changed'
ADDED = '{by} added {names} to this room. It continues room {old}.'
BRIDGED_NOTE = " This room is bridged to Stanley's aDNA lattice: posts that mention a lattice persona cross to it."


def joined(names):
    """A, A and B, A, B and C."""
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]


class Members:
    def _bridged(self, db, room_id):
        """Wormhole, the lattice bridge, is a member of the room."""
        wormhole = self._wormhole_id(db)
        return wormhole is not None and db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?',
                                                   (room_id, wormhole)).fetchone() is not None

    def _account_name(self, db, member_id):
        """A member's display name as one safe line: the account's, else the remote contact's, else the id's start."""
        row = db.execute('SELECT name FROM users WHERE id=?', (member_id,)).fetchone()
        row = row or db.execute('SELECT name FROM remote_contacts WHERE id=?', (member_id,)).fetchone()
        return safe_line(row['name'] if row else member_id[:6], 40)

    def _record_change(self, db, change, room_id, member_id, actor_id, grant_id, new_room_id=None, earlier_rooms=0, claims_released=0):
        key = uid()
        db.execute('INSERT INTO member_changes(id,grant_id,actor_id,member_id,change,room_id,new_room_id,earlier_rooms,claims_released,created)'
                   ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (key, grant_id, actor_id, member_id, change, room_id, new_room_id, earlier_rooms, claims_released, self.clock()))
        return key

    def _act_room(self, db, actor, key, adding):
        """Section 2, checks 1 and 2: a local room the actor is in (404 otherwise), not a breakout, and current (409)."""
        if not isinstance(key, str) or ':' in key:
            raise Problem(404, 'Not found')
        room = self._room(db, actor, key)
        if self._breakout(db, key) is not None:
            raise Problem(404, 'Not found')
        if db.execute(f'SELECT 1 WHERE ? IN ({REPLACED_ROOMS})', (key,)).fetchone():
            raise Problem(409, REPLACED_ADD)  # removing there is Task 4's REPLACED_REMOVE
        return room

    def _add_members(self, db, owner_id, room, member_ids, carry, actor_id, grant_id=None):
        """The owner's add, in the caller's transaction: a new linked room with the old members and the new ones, the
        brief when carried, the open board items; one log row per new member and one notice. The REPLACED_ADD guard
        stays as the fork defence. Returns the new room's view with short, added, brief_carried, board_carried, bridged."""
        key = room['id']
        if db.execute(f'SELECT 1 FROM rooms WHERE id=? AND id IN ({REPLACED_ROOMS})', (key,)).fetchone():
            raise Problem(409, REPLACED_ADD)  # one replacement per room, so the chain never forks (work board 8.4)
        named = ids(member_ids)
        new_ids = [m for m in dict.fromkeys(named) if m not in room['member_ids']]
        if not new_ids:
            raise Problem(409, NO_ONE_NEW.format(short=key[:6]))
        carried = self._brief_to_carry(db, key, carry)
        new = self._create_room(db, owner_id, room['title'], ids(room['member_ids'] + new_ids), key)
        if carried is not None:  # the brief, under its own author; the old room's messages stay with their participants
            body, author = carried
            self._write_brief(db, new['id'], body, 1, author, carried_from=key)
        new['board_carried'] = self._carry_board(db, key, new['id'])  # work board 5.x
        logged = [self._record_change(db, 'add', key, m, actor_id, grant_id, new_room_id=new['id']) for m in new_ids]
        bridged = self._bridged(db, new['id'])
        by = self._account_name(db, actor_id)
        names = joined([self._account_name(db, m) for m in new_ids])
        self._post_as_system(db, new['id'], f'member-{logged[0]}',
                             ADDED.format(by=by, names=names, old=key[:6]) + (BRIDGED_NOTE if bridged else ''))
        added = []
        for m in new_ids:
            user = db.execute('SELECT username,name FROM users WHERE id=?', (m,)).fetchone()
            added.append({'id': m, 'username': user['username'] if user else None,
                          'name': user['name'] if user else self._account_name(db, m)})
        new.update(short=new['id'][:6], added=added, brief_carried=carried is not None, bridged=bridged)
        return new

    def add_participants(self, actor, key, member_ids, carry_brief=None, grant_id=None):
        if carry_brief is not None and type(carry_brief) is not int:
            raise Problem(400, 'carry_brief is the revision of the brief you saw, or null')
        member_ids = ids(member_ids)
        with self.transaction() as db:
            room = self._act_room(db, actor, key, adding=True)
            if room['owner_id'] == actor:
                return self._add_members(db, actor, room, member_ids, carry_brief, actor)
            raise Problem(403, NOT_A_MODERATOR)  # Task 5 puts the moderator's path here
