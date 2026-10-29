"""Never to a cloud model (remote connector spec, "Never to a cloud model"; D6, D8, D10): any person in a room can keep
it away from cloud models. Each member's mark is their own, and the room is marked while one stands, even after its
member leaves, since their words stay. Ships run on cloud models, so a marked room never has a ship: marking waits
until there is none, and every add path refuses one (`_add_members`, which the participants route, a moderator,
make station-add-ship and make station-bridge all take). Adding members makes a new linked room, and the marks go with
it in the same transaction. Only a marked room's view carries `cloud`, as only a breakout's carries `breakout`."""
from .common import REPLACED_ROOMS, Problem

ROOM_CLOUD_SCHEMA = '''
CREATE TABLE IF NOT EXISTS room_cloud(room_id TEXT NOT NULL REFERENCES rooms(id), member_id TEXT NOT NULL REFERENCES users(id), set_at REAL NOT NULL, PRIMARY KEY(room_id, member_id));
'''
SHIPS_IN = 'This room has ships in it, and ships run on cloud models.'
SHIPS_FIRST = SHIPS_IN + ' Remove them first.'
ASK_OWNER = SHIPS_IN + ' Ask {owner} to remove them first.'
OWNER_TOLD = 'A member asked to keep this room away from cloud models. Remove the ships to let them.'
SHIP_REFUSED = 'A member keeps this room away from cloud models, and ships run on cloud models.'
EARLIER_IN = "An earlier room you're in has ships in it, and ships run on cloud models. Mark this room alone, or"
EARLIER_FIRST = EARLIER_IN + ' remove them first.'
EARLIER_ASK = EARLIER_IN + ' ask {owner} to remove them first.'
REPLACED_MARK = 'This room continues in a newer room. Mark that one.'
REMOTE_REFUSED = ("A member keeps this room away from cloud models, and this home can't tell whether someone on another "
                  "home is a ship, nor tell their home about the mark yet.")
QUIET = 86400  # the owner is told once a day at most, so a member who tries again doesn't flood the room (the plan's)


class RoomCloud:
    def _marked(self, db, room_id):
        return db.execute('SELECT 1 FROM room_cloud WHERE room_id=?', (room_id,)).fetchone() is not None

    def _cloud(self, db, room_id, actor_id):
        """How many members' marks stand on the room, and whether one is the viewer's."""
        count, mine = db.execute('SELECT count(*), coalesce(sum(member_id=?), 0) FROM room_cloud WHERE room_id=?',
                                 (actor_id, room_id)).fetchone()
        return {'count': count, 'mine': bool(mine)}

    def _cloud_view(self, db, room_id, actor_id):
        """`cloud` for a room's view: only a marked room has it, so every other room's view is unchanged."""
        cloud = self._cloud(db, room_id, actor_id)
        return {'cloud': cloud} if cloud['count'] else {}

    def _has_ship(self, db, room_id):
        return db.execute("SELECT 1 FROM room_members JOIN users ON users.id=room_members.user_id "
                          "WHERE room_members.room_id=? AND users.kind='ship'", (room_id,)).fetchone() is not None

    def _refuse_ship_in_marked(self, db, room_id, member_ids):
        """D6: no ship joins a marked room, by any add path. Nor does anyone on another home: this home can't tell a
        remote contact's kind (`card --as` exports any account's card), and their home doesn't know the mark until
        federation carries it, so a new one is refused, failing closed. A room that had one before it was marked keeps
        them, as the spec says for "Rooms with members on other homes"."""
        if not member_ids or not self._marked(db, room_id):
            return
        if any(m.startswith('remote_') for m in member_ids):
            raise Problem(409, REMOTE_REFUSED)
        marks = ','.join('?' * len(member_ids))
        if db.execute(f"SELECT 1 FROM users WHERE kind='ship' AND id IN ({marks})", member_ids).fetchone():
            raise Problem(409, SHIP_REFUSED)

    def _carry_cloud(self, db, old_room_id, new_room_id):
        """D8: every mark on the room an add replaced stands on the new one, in the add's own transaction."""
        db.execute('INSERT OR IGNORE INTO room_cloud SELECT ?, member_id, set_at FROM room_cloud WHERE room_id=?',
                   (new_room_id, old_room_id))

    def _tell_owner(self, db, room_id):
        """A member asked while ships are in the room: the room hears it from the station, naming no one (D10)."""
        author = self.system_author_id(db)
        now = self.clock()
        if not db.execute('SELECT 1 FROM messages WHERE room_id=? AND author_id=? AND body=? AND created>?',
                          (room_id, author, OWNER_TOLD, now - QUIET)).fetchone():
            self._post_as_system(db, room_id, f'cloud-ask-{int(now)}', OWNER_TOLD)

    def mark_room(self, actor, key, earlier=True):
        """A person's own mark on a current local room they're in, and, with `earlier`, on the earlier rooms of its
        chain that still hold them. A replaced room is refused, since the room continuing it would stay unmarked. Refused
        while a ship is a member of any room to be marked; a member who isn't the owner is told to ask the owner, and,
        for the room itself, the owner is told a member asked. Returns the rooms marked and the room's `cloud`."""
        if not isinstance(key, str) or ':' in key:
            raise Problem(404, 'Not found')
        if type(earlier) is not bool:
            raise Problem(400, 'earlier is true or false')
        with self.transaction() as db:
            self._person(db, actor)  # only a person marks; a ship at the store is refused before anything is said
            room = self._room(db, actor, key)
            if db.execute(f'SELECT 1 WHERE ? IN ({REPLACED_ROOMS})', (key,)).fetchone():
                raise Problem(409, REPLACED_MARK)  # its continuation would stay unmarked (Rio Grande's section 2, M1)
            owner = room['owner_id'] == actor
            if not self._has_ship(db, key):
                marked = [key] + (self._earlier_with(db, room['owner_id'], room, actor) if earlier else [])
                if any(self._has_ship(db, earlier_room) for earlier_room in marked[1:]):  # older data or a restore (Tardis)
                    raise Problem(409, EARLIER_FIRST if owner else
                                  EARLIER_ASK.format(owner=self._account_name(db, room['owner_id'])))
                db.executemany('INSERT OR IGNORE INTO room_cloud VALUES(?,?,?)',
                               [(room_id, actor, self.clock()) for room_id in marked])
                return {'marked': marked, 'cloud': self._cloud(db, key, actor)}
            if owner:
                refusal = SHIPS_FIRST
            else:
                refusal = ASK_OWNER.format(owner=self._account_name(db, room['owner_id']))
                self._tell_owner(db, key)  # committed with the transaction; the refusal is raised after it
        raise Problem(409, refusal)

    def unmark_room(self, actor, key):
        """A person clears their own mark on a room they're in, a replaced one included. Nobody clears another's, a former
        member's stands, and the earlier rooms' marks stay, which fails closed."""
        if not isinstance(key, str) or ':' in key:
            raise Problem(404, 'Not found')
        with self.transaction() as db:
            self._person(db, actor)
            self._room(db, actor, key)
            db.execute('DELETE FROM room_cloud WHERE room_id=? AND member_id=?', (key, actor))
            return {'cloud': self._cloud(db, key, actor)}
