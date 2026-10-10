"""Member-only rooms, linked new audiences, epoch-rechecked messages."""
from .common import Problem, text, ids, uid, require

class Chats:
    def _room(self, db, actor, key):
        row = require(db.execute('SELECT rooms.* FROM rooms JOIN room_members ON rooms.id=room_members.room_id WHERE rooms.id=? AND user_id=?', (key, actor)).fetchone())
        members = [r[0] for r in db.execute('SELECT user_id FROM room_members WHERE room_id=? ORDER BY user_id', (key,))]
        members += [r[0] for r in db.execute('SELECT contact_id FROM remote_room_members WHERE room_id=? ORDER BY contact_id', (key,))]
        activity = db.execute('SELECT (SELECT created FROM room_activity WHERE room_id=?) AS created, (SELECT MAX(created) FROM messages WHERE room_id=?) AS latest_message', (key, key)).fetchone()
        remote_activity = db.execute('SELECT MAX(created) FROM peer_messages WHERE room_id=?', (key,)).fetchone()[0] or 0.0
        created = activity['created'] or 0.0
        return {**dict(row), 'member_ids': members, 'created': created, 'last_activity': max(created, activity['latest_message'] or 0.0, remote_activity)}

    def _create_room(self, db, actor, title, members, linked_room_id=None):
        text(title, 'title')
        members = ids([actor] + members)
        if self.system_author_id(db) in members:
            raise Problem(400, "The station's system author is never a room member")
        self._known_contacts(db, members)
        key = uid()
        db.execute('INSERT INTO rooms VALUES(?,?,?,1,?)', (key, actor, title, linked_room_id))
        db.execute('INSERT INTO room_activity VALUES(?,?)', (key, self.clock()))
        db.executemany('INSERT INTO room_members VALUES(?,?)', [(key, member) for member in members if not member.startswith('remote_')])
        db.executemany('INSERT INTO remote_room_members VALUES(?,?)', [(key, member) for member in members if member.startswith('remote_')])
        self.emit(db, 'chat.membership', key, 1, {'owner_id': actor})
        return self._room(db, actor, key)

    def create_room(self, actor, title, member_ids=None):
        with self.transaction() as db:
            return self._create_room(db, actor, title, ids(member_ids or []))

    def list_rooms(self, actor):
        with self.transaction() as db:
            rooms = [self._room(db, actor, r[0]) for r in db.execute('SELECT room_id FROM room_members WHERE user_id=?', (actor,)).fetchall()]
        return sorted(rooms + self.remote_rooms(actor), key=lambda room: (-room['last_activity'], room['id']))

    def get_room(self, actor, key):
        if ":" in key:
            room = self.remote_room(actor, key)
            for message in room.get('messages', []):
                message['source'] = None  # a paired peer's payload is passed through: a label in it is never ours
                message['reply_to'] = None
            room['brief'], room['brief_revision'] = None, 0  # briefs never cross stations
            return room
        with self.transaction() as db:
            room = self._room(db, actor, key)
            room['messages'] = [dict(r) for r in db.execute('SELECT * FROM messages WHERE room_id=? ORDER BY created, rowid', (key,))]
            sources, replies = self._sources(db, key), self._replies(db, key)
            for message in room['messages']:
                message['source'], message['reply_to'] = sources.get(message['id']), replies.get(message['id'])
            room['messages'] += [dict(r, reply_to=None) for r in db.execute('SELECT * FROM peer_messages WHERE room_id=? ORDER BY created, rowid', (key,))]
            room['messages'].sort(key=lambda m: m['created'])  # stable: ids are random, so one instant keeps insertion order
            room['members'] = [dict(r) for r in db.execute(
                'SELECT users.id,users.username,users.name,users.kind,users.owner_id FROM room_members JOIN users ON users.id=room_members.user_id WHERE room_members.room_id=? ORDER BY users.id',
                (key,))]
            room['brief'], room['brief_revision'] = self._room_brief(db, key)
            system = self.system_author_id(db)
            if any(m.get('author_id') == system for m in room['messages']):
                room['system_author'] = self.system_author_public(db)
            room['claims'] = self._active_claims(db, key)
            return room

    def send_message(self, actor, key, client_message_id, body, ticket_id=None, reply_to=None):
        self._refuse_live_ship_keys(body)
        if ':' in key:
            if ticket_id is not None:
                raise Problem(409, 'Tickets label messages in local rooms only')
            if reply_to is not None:
                raise Problem(400, 'Replies are labelled in local rooms only')
            return self.remote_send(actor, key, client_message_id, body)
        text(client_message_id, 'client message ID', 100)
        text(body, 'message', 20000)
        with self.transaction() as db:
            room = self._room(db, actor, key)
            existing = db.execute('SELECT * FROM messages WHERE room_id=? AND author_id=? AND client_message_id=?', (key, actor, client_message_id)).fetchone()
            if existing:
                if existing['body'] != body or self._reply_to(db, existing['id']) != reply_to:
                    raise Problem(409, 'Message ID already used with different text')
                return dict(existing, replayed=True)  # a retry: nothing new was posted
            if reply_to is not None:
                self._check_reply_to(db, key, reply_to)
            self._ship_post_budget(db, actor)
            if ticket_id is not None:
                self._check_ticket_label(db, actor, key, ticket_id)
            message_id = uid()
            db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (message_id, key, actor, client_message_id, body, room['epoch'], self.clock()))
            if ticket_id is not None:
                db.execute('INSERT INTO message_sources VALUES(?,?)', (message_id, ticket_id))
            if reply_to is not None:
                db.execute('INSERT INTO message_replies VALUES(?,?)', (message_id, reply_to))
            self._record_mentions(db, key, message_id, body)
            self.emit(db, 'chat.message', key, room['epoch'], {'message_id': message_id, 'author_id': actor})
            sent = dict(db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone(), replayed=False)
            if reply_to is None:  # R27: this ship's deferred mentions here that still wait for a reply_to
                waiting = [r[0] for r in db.execute('''SELECT deferrals.message_id FROM deferrals JOIN messages
                    ON messages.id=deferrals.message_id WHERE deferrals.ship_id=? AND messages.room_id=?
                    ORDER BY deferrals.first_deferred''', (actor, key))]
                if waiting:  # R35: present only when it has something to say
                    sent['deferred_here'] = waiting
            return sent

    def add_participants(self, actor, key, member_ids, carry_brief=None):
        if carry_brief is not None and type(carry_brief) is not int:
            raise Problem(400, 'carry_brief is the revision of the brief you saw, or null')
        with self.transaction() as db:
            room = self._room(db, actor, key)
            if room['owner_id'] != actor:
                raise Problem(403, 'Room owner required')
            carried = self._brief_to_carry(db, key, carry_brief)
            new = self._create_room(db, actor, room['title'], ids(room['member_ids'] + ids(member_ids)), key)
            if carried is not None:  # only the brief: the old room's messages stay with their participants
                self._write_brief(db, new['id'], carried, 1, actor, carried_from=key)
            return new

    def remove_participant(self, actor, key, user_id):
        text(user_id, 'user ID', 100)
        with self.transaction() as db:
            room = self._room(db, actor, key)
            if room['owner_id'] != actor:
                raise Problem(403, 'Room owner required')
            if user_id == actor:
                raise Problem(400, 'Cannot remove the room owner')
            if user_id in room['member_ids']:
                db.execute('DELETE FROM room_members WHERE room_id=? AND user_id=?', (key, user_id))
                db.execute('DELETE FROM remote_room_members WHERE room_id=? AND contact_id=?', (key, user_id))
                db.execute('UPDATE rooms SET epoch=epoch+1 WHERE id=?', (key,))
                self.emit(db, 'chat.membership', key, room['epoch'] + 1, {'removed_user_id': user_id})
            return self._room(db, actor, key)

    def can_deliver_message(self, message_id, recipient_id, epoch):
        """Trusted transport hook: rejects messages queued under obsolete room epochs."""
        with self.transaction() as db:
            row = db.execute('SELECT messages.epoch AS message_epoch,rooms.epoch FROM messages JOIN rooms ON rooms.id=messages.room_id JOIN room_members ON room_members.room_id=rooms.id WHERE messages.id=? AND room_members.user_id=?', (message_id, recipient_id)).fetchone()
            return bool(row and row['epoch'] == epoch and row['message_epoch'] == epoch)
