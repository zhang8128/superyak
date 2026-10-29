"""The system author (spec S11): the one place the station writes a message. One users row, kind 'system', username
'_station', found only by the id in system_meta; never a room member, never keyed, never signed in. Its only writer
is _post_as_system, which exactly these notices call (ship briefs R18, room moderators M19): the ticket decision's
(tickets.py _post_notice), the room brief's (briefs.py _write_brief), a moderator's appointment (moderators.py
_make_moderate), its end (grants.py _revoke), a member add (members.py _add_members), a member removal
(members.py _remove_member) and a member's ask to keep a room with ships away from cloud models (room_cloud.py
_tell_owner). message_kinds marks claim and notice messages, which are never answered
(422) and never federate."""
import secrets
from .common import uid

SYSTEM_SCHEMA = '''
CREATE TABLE IF NOT EXISTS system_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS message_kinds(message_id TEXT PRIMARY KEY REFERENCES messages(id), kind TEXT NOT NULL CHECK (kind IN ('claim','notice')));
'''


class SystemAuthor:
    def _ensure_system_author(self):
        """Created once at schema setup. `_station` is outside every username rule (auth.py:33-37, ships.py:11), so a
        clash means the database was edited by hand, and starting then fails loudly rather than guessing."""
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM system_meta WHERE key='system_author'").fetchone():
                return
            key = uid()
            db.execute('INSERT INTO users(id,username,name,salt,password_hash,is_admin,created,kind) VALUES(?,?,?,?,?,0,?,?)',
                       (key, '_station', 'Station', secrets.token_bytes(16), b'\0' * 32, self.clock(), 'system'))
            db.execute("INSERT INTO system_meta VALUES('system_author', ?)", (key,))

    def system_author_id(self, db):
        return db.execute("SELECT value FROM system_meta WHERE key='system_author'").fetchone()[0]

    def system_author_public(self, db):
        return dict(db.execute('SELECT id,username,name,kind,owner_id FROM users WHERE id=?', (self.system_author_id(db),)).fetchone())

    def _post_as_system(self, db, room_id, client_id, text):
        """One station notice, in the caller's transaction: the message under the caller's client id, its message_kinds
        row and its chat.message event. Its callers pass notice-<ship id>-<mention id> (the deferral),
        brief-<room id>-<revision> (the brief), moderator-<grant id> and moderator-<grant id>-revoked (the appointment and
        the end), member-<row id> (a member add or removal) and cloud-ask-<time> (a member asked to keep the room away
        from cloud models while ships are in it, from RoomCloud._tell_owner). No reply_to, no ticket, no mentions, no
        post budget; local rooms only.
        Returns the message id, or None when the text holds a live ship key or the room is a closed breakout; the
        caller's own write still stands. A retry under the same client id returns the message already posted."""
        if ':' in room_id:
            raise ValueError('The system author posts in local rooms only')
        if self._live_ship_key_in(db, text) or self._breakout_closed(db, room_id) is not None:
            return None  # a closed breakout gets no notice
        author = self.system_author_id(db)
        existing = db.execute('SELECT id FROM messages WHERE room_id=? AND author_id=? AND client_message_id=?',
                              (room_id, author, client_id)).fetchone()
        if existing:
            return existing['id']
        room = db.execute('SELECT epoch FROM rooms WHERE id=?', (room_id,)).fetchone()
        new_id = uid()
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (new_id, room_id, author, client_id, text, room['epoch'], self.clock()))
        db.execute("INSERT INTO message_kinds VALUES(?, 'notice')", (new_id,))
        self.emit(db, 'chat.message', room_id, room['epoch'], {'message_id': new_id, 'author_id': author})
        return new_id

    def _never_answered(self, db, message):
        """S5 step 0: a message by the system author or with a message_kinds row is never answered (R20, R32)."""
        return (message['author_id'] == self.system_author_id(db)
                or db.execute('SELECT 1 FROM message_kinds WHERE message_id=?', (message['id'],)).fetchone() is not None)

    def _never_federates(self, db, message_id):
        message = db.execute('SELECT id,author_id FROM messages WHERE id=?', (message_id,)).fetchone()
        return message is not None and self._never_answered(db, message)
