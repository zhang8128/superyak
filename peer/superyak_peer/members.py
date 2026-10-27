"""Room moderators: every membership change of a room goes through the helpers here (spec M7, M8, M14). An add is one
transaction: the checks, the new linked room, each member's row in the act log (`member_changes`) and the one notice
the system author posts in the new room. The owner's routes (the participants route, make station-bridge and
make station-add-ship) call `_add_members`; a moderator's add and removal take the same helpers, after their grant's checks."""
from .common import REPLACED_ADD, REPLACED_REMOVE, REPLACED_ROOMS, Problem, ids, text, uid
from .grants import is_moderate
from .moderators import NOT_A_MODERATOR
from .ships import safe_line

ONE_MEMBER = 'A moderator changes one member at a time'
NAME_THE_MEMBER = 'Name the member to add'
WORMHOLE_ADD = "Adding wormhole bridges the room to Stanley's aDNA lattice; only the room's owner bridges it (make station-bridge)"
NOT_ADDABLE = '{x} is not someone a moderator can add'
OWNERLESS = '{name} is a station ship with no owner; a moderator never adds or removes it'
NOT_OWNERS_SHIP = '{name} is not one of {owner}\'s ships'
OWNER_REMOVED = '{owner} removed {name} from this room; only he can add them back'
ALREADY_MEMBER = '{name} is already a member of room {short}; nothing changed'
NO_ONE_NEW = 'Everyone named is already a member of room {short}; nothing changed'
ADDED = '{by} added {names} to this room. It continues room {old}.'
REMOVED = '{by} removed {name} from {where}.'
GRANT_GONE = "{name}'s moderate grant here is revoked."
NOT_A_MEMBER = '{x} is not a member of this room'
NOT_THE_OWNER = "A moderator can't remove the room's owner"
WORMHOLE_REMOVE = "Removing wormhole unbridges the room; only the room's owner does that (make station-unbridge)"
OTHER_MODERATOR = '{name} moderates this room too; only {owner} can remove a moderator'
REMOTE_MEMBER = '{name} is on another station; only {owner} manages them'
BRIDGED_NOTE = " This room is bridged to Stanley's aDNA lattice: posts that mention a lattice persona cross to it."


def where(here, earlier):
    """REMOVED's {where}: this room, the rooms before it, or both."""
    if here:
        return 'this room' + (' and the room before it' if earlier == 1 else f' and the {earlier} rooms before it' if earlier else '')
    return 'the room before this one' if earlier == 1 else f'the {earlier} rooms before this one'


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
            raise Problem(409, REPLACED_ADD if adding else REPLACED_REMOVE)
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
        by = self._account_name(db, actor_id) + (', a moderator,' if grant_id else '')
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
            grant = self._acting_grant(db, actor, room['id'], 'add_member', grant_id)
            if len(member_ids) != 1:
                raise Problem(400, ONE_MEMBER)
            return self._moderator_add(db, actor, room, grant, member_ids[0], False)

    def ship_add_member(self, actor, key, member, grant_id=None):
        """POST /api/ships/me/rooms/{key}/members: a ship moderator adds one member by username, in one transaction. A ship
        never owns a person's room and check 1 refuses breakouts, so there is no owner branch."""
        with self.transaction() as db:
            room = self._act_room(db, actor, key, adding=True)
            grant = self._acting_grant(db, actor, room['id'], 'add_member', grant_id)
            return self._moderator_add(db, actor, room, grant, member, True)

    def ship_remove_member(self, actor, key, member, grant_id=None):
        """DELETE /api/ships/me/rooms/{key}/members/{member}: the username is read as people write it (ruling 17); an
        unknown one stays the typed name and fails the chain test with the 404."""
        typed = member.strip().removeprefix('@').lower()
        with self.transaction() as db:
            row = db.execute('SELECT id FROM users WHERE username=?', (typed,)).fetchone()
            member_id = row['id'] if row else typed
            room = self._act_room(db, actor, key, adding=False)
            grant = self._acting_grant(db, actor, room['id'], 'remove_member', grant_id, self_removal=member_id == actor)
            return self._moderator_remove(db, actor, room, grant, typed, member_id)

    def _owner_removed(self, db, room_id, member_id, owner_id):
        """M7: the owner (not a moderator) removed the member and nothing has changed them since: their latest row in this
        room's chain is a removal with no grant by the owner (or by no one)."""
        chain = self._rooms_back(db, room_id)
        last = db.execute(f'SELECT change, grant_id, actor_id FROM member_changes WHERE member_id=? AND room_id IN ({",".join("?" * len(chain))})'
                          ' ORDER BY created DESC, rowid DESC LIMIT 1', (member_id, *chain)).fetchone()
        return (last is not None and last['change'] == 'remove' and not last['grant_id']
                and (not last['actor_id'] or last['actor_id'] == owner_id))

    def _moderator_add(self, db, actor, room, grant, typed, by_username):
        """M7 in its order, in the caller's transaction (ruling 1): the typed member (a username on the ship route, an id on
        the person route), the refusals, then the owner's own add, charged to the grant. The brief comes at the revision
        _owned_room read (R-S3)."""
        typed = typed if isinstance(typed, str) else ''
        if by_username:
            typed = typed.strip().removeprefix('@').lower()
        if not typed:
            raise Problem(400, NAME_THE_MEMBER)
        if by_username and typed == 'wormhole':
            raise Problem(403, WORMHOLE_ADD)
        row = db.execute(f'SELECT id,username,name,kind,owner_id,activation_pending FROM users WHERE {"username" if by_username else "id"}=?',
                         (typed,)).fetchone()
        if row is None or row['kind'] == 'system' or row['activation_pending']:
            raise Problem(404, NOT_ADDABLE.format(x=safe_line(typed)))
        name = safe_line(row['name'], 40)
        if row['username'] == 'wormhole':
            raise Problem(403, WORMHOLE_ADD)
        if row['kind'] == 'ship':
            if row['owner_id'] is None:
                raise Problem(403, OWNERLESS.format(name=name))
            if row['owner_id'] != room['owner_id']:
                raise Problem(403, NOT_OWNERS_SHIP.format(name=name, owner=self._account_name(db, room['owner_id'])))
        if self._owner_removed(db, room['id'], row['id'], room['owner_id']):
            raise Problem(403, OWNER_REMOVED.format(owner=self._account_name(db, room['owner_id']), name=name))
        if row['id'] in room['member_ids']:
            raise Problem(409, ALREADY_MEMBER.format(name=name, short=room['id'][:6]))
        owned, carry = self._owned_room(db, room['owner_id'], room['id'])
        return self._station_add(db, room['owner_id'], owned, row['id'], carry, 'adding the member', 'station_add_member',
                                 mover_id=actor, grant_id=grant['id'])

    def _earlier_with(self, db, owner_id, room, member_id):
        """Rooms earlier in this room's linked chain, owned by owner_id, that still have the member: a replaced room keeps
        its members, so a removal that left them there would let them back in once the current room is current again."""
        found, seen, key = [], set(), room['linked_room_id']
        while key and key not in seen:
            seen.add(key)
            row = db.execute('SELECT owner_id,linked_room_id FROM rooms WHERE id=?', (key,)).fetchone()
            if row is None:
                break
            if row['owner_id'] == owner_id and (
                    db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (key, member_id)).fetchone()
                    or db.execute('SELECT 1 FROM remote_room_members WHERE room_id=? AND contact_id=?', (key, member_id)).fetchone()):
                found.append(key)
            key = row['linked_room_id']
        return found

    def _remove_member(self, db, room, member_id, actor_id, grant_id=None):
        """M8, the one removal for every path, in the caller's transaction: the member leaves the room and every earlier
        room of its chain they are still in (epoch up, membership event), their moderate grants for this room are
        revoked and signed, their deferrals there are dropped and their claims released silently; one row in the act log
        and one notice in the current room. Returns the owner's view plus removed, earlier_rooms, claims_released,
        grant_revoked and bridged."""
        key, now = room['id'], self.clock()
        here = member_id in room['member_ids']
        earlier = self._earlier_with(db, room['owner_id'], room, member_id)
        places = ([key] if here else []) + earlier
        marks = ','.join('?' * len(places))
        for place in places:
            db.execute('DELETE FROM room_members WHERE room_id=? AND user_id=?', (place, member_id))
            db.execute('DELETE FROM remote_room_members WHERE room_id=? AND contact_id=?', (place, member_id))
            db.execute('UPDATE rooms SET epoch=epoch+1 WHERE id=?', (place,))
            self.emit(db, 'chat.membership', place, db.execute('SELECT epoch FROM rooms WHERE id=?', (place,)).fetchone()[0],
                      {'removed_user_id': member_id})
        gone = [g['id'] for g in db.execute('SELECT * FROM grants WHERE grantee_id=? AND revoked IS NULL', (member_id,)).fetchall()
                if is_moderate(g) and self._covered_room(db, g) == key]
        for grant in gone:
            db.execute('UPDATE grants SET revoked=?, revoked_by=?, revoke_reason=? WHERE id=?',
                       (now, actor_id, 'removed from the room', grant))
            self._sign_revocation(db, grant)
        db.execute(f'DELETE FROM deferrals WHERE ship_id=? AND message_id IN (SELECT id FROM messages WHERE room_id IN ({marks}))',
                   (member_id, *places))
        released = db.execute(f'UPDATE claims SET released=?, released_by=? WHERE holder_id=? AND room_id IN ({marks})'
                              ' AND released IS NULL AND expires>?', (now, actor_id, member_id, *places, now)).rowcount
        logged = self._record_change(db, 'remove', key, member_id, actor_id, grant_id, earlier_rooms=len(earlier), claims_released=released)
        name = self._account_name(db, member_id)
        by = self._account_name(db, actor_id) + (', a moderator,' if grant_id else '')
        bridged = self._bridged(db, key)
        said = REMOVED.format(by=by, name=name, where=where(here, len(earlier)))
        if gone:
            said += ' ' + GRANT_GONE.format(name=name)
        if released:
            said += ' ' + ('1 claim was released.' if released == 1 else f'{released} claims were released.')
        self._post_as_system(db, key, f'member-{logged}', said + (BRIDGED_NOTE if bridged else ''))
        user = db.execute('SELECT username,name FROM users WHERE id=?', (member_id,)).fetchone()
        view = self._room(db, room['owner_id'], key)
        view.update(removed={'id': member_id, 'username': user['username'] if user else None,
                             'name': user['name'] if user else self._account_name(db, member_id)},
                    earlier_rooms=len(earlier), claims_released=released, grant_revoked=bool(gone), bridged=bridged)
        return view

    def _moderator_remove(self, db, actor, room, grant, typed, member_id):
        """M8's refusals in order, in the caller's transaction, then the one removal, charged to the grant."""
        if member_id not in room['member_ids'] and not self._earlier_with(db, room['owner_id'], room, member_id):
            raise Problem(404, NOT_A_MEMBER.format(x=safe_line(typed)))
        owner = self._account_name(db, room['owner_id'])
        name = self._account_name(db, member_id)
        if member_id == room['owner_id']:
            raise Problem(403, NOT_THE_OWNER)
        if member_id == self._wormhole_id(db):
            raise Problem(403, WORMHOLE_REMOVE)
        user = db.execute('SELECT kind, owner_id FROM users WHERE id=?', (member_id,)).fetchone()
        if user is None:
            raise Problem(403, REMOTE_MEMBER.format(name=name, owner=owner))
        if user['kind'] == 'ship' and user['owner_id'] is None:
            raise Problem(403, OWNERLESS.format(name=name))
        if member_id != actor and any(m['id'] == member_id for m in self._moderators(db, room['id'])):
            raise Problem(403, OTHER_MODERATOR.format(name=name, owner=owner))
        return self._remove_member(db, room, member_id, actor, grant['id'])

    def remove_participant(self, actor, key, user_id, grant_id=None):
        text(user_id, 'user ID', 100)
        with self.transaction() as db:
            room = self._act_room(db, actor, key, adding=False)
            if room['owner_id'] != actor:
                grant = self._acting_grant(db, actor, room['id'], 'remove_member', grant_id, self_removal=user_id == actor)
                return self._moderator_remove(db, actor, room, grant, user_id, user_id)
            if user_id == actor:
                raise Problem(400, 'Cannot remove the room owner')
            if user_id not in room['member_ids'] and not self._earlier_with(db, actor, room, user_id):
                raise Problem(404, NOT_A_MEMBER.format(x=safe_line(user_id)))
            return self._remove_member(db, room, user_id, actor)
