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
            return self.remote_room(actor, key)
        with self.transaction() as db:
            room = self._room(db, actor, key)
            room['messages'] = [dict(r) for r in db.execute('SELECT * FROM messages WHERE room_id=? ORDER BY created,id', (key,))]
            room['messages'] += [dict(r) for r in db.execute('SELECT * FROM peer_messages WHERE room_id=? ORDER BY created,id', (key,))]
            room['messages'].sort(key=lambda m: (m['created'], m['id']))
            room['members'] = [dict(r) for r in db.execute(
                'SELECT users.id,users.username,users.name,users.kind,users.owner_id FROM room_members JOIN users ON users.id=room_members.user_id WHERE room_members.room_id=? ORDER BY users.id',
                (key,))]
            return room

    def send_message(self, actor, key, client_message_id, body):
        if ':' in key:
            return self.remote_send(actor, key, client_message_id, body)
        text(client_message_id, 'client message ID', 100)
        text(body, 'message', 20000)
        with self.transaction() as db:
            room = self._room(db, actor, key)
            existing = db.execute('SELECT * FROM messages WHERE room_id=? AND author_id=? AND client_message_id=?', (key, actor, client_message_id)).fetchone()
            if existing:
                if existing['body'] != body:
                    raise Problem(409, 'Message ID already used with different text')
                return dict(existing)
            self._ship_post_budget(db, actor)
            message_id = uid()
            db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (message_id, key, actor, client_message_id, body, room['epoch'], self.clock()))
            self._record_mentions(db, key, message_id, body)
            self.emit(db, 'chat.message', key, room['epoch'], {'message_id': message_id, 'author_id': actor})
            return dict(db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone())

    def add_participants(self, actor, key, member_ids):
        with self.transaction() as db:
            room = self._room(db, actor, key)
            if room['owner_id'] != actor:
                raise Problem(403, 'Room owner required')
            return self._create_room(db, actor, room['title'], ids(room['member_ids'] + ids(member_ids)), key)

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
