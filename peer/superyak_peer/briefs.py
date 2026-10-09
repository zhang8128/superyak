"""Room briefs (docs/superpowers/specs/2026-10-08-room-brief-design.md): a short text a room's owner writes about the
room, such as its purpose, its decisions so far and who does what. Members and their agents read it as quoted data,
never as instructions. A room keeps one row with only its current revision; every save, a removal included, writes the
next revision on that row, so a stale tab can never overwrite a later brief."""
from .common import Problem, text
from .ships import safe_line

MAX_BRIEF = 4000
BRIEF_SCHEMA = '''
CREATE TABLE IF NOT EXISTS room_briefs(room_id TEXT PRIMARY KEY REFERENCES rooms(id), body TEXT NOT NULL, revision INTEGER NOT NULL, author_id TEXT NOT NULL REFERENCES users(id), updated REAL NOT NULL, carried_from TEXT);
'''


def brief_body(body):
    """0-4,000 characters (code points, as Python counts them) of valid UTF-8 with no NUL, else 400. A body that is
    empty or only whitespace removes the brief and is stored as ''. The length has its own message, because the web
    editor has no maxlength (a browser counts UTF-16 units) and shows the owner this one."""
    if isinstance(body, str) and len(body) > MAX_BRIEF:
        raise Problem(400, 'A brief is at most 4,000 characters')
    text(body, 'brief', MAX_BRIEF, empty=True)
    if '\x00' in body:
        raise Problem(400, 'A brief cannot contain a NUL character')
    return body if body.strip() else ''


class Briefs:
    def _room_brief(self, db, room_id):
        """(brief, revision). The brief is what members see: None when the room never had one or it was removed. The
        revision is the one the owner's next save must name: 0 before the first brief, and a removed brief's own
        revision after a removal."""
        # LEFT JOIN: a missing author row must never make the revision read as 0.
        row = db.execute('SELECT room_briefs.*, users.name AS author_name FROM room_briefs LEFT JOIN users ON users.id=room_briefs.author_id '
                         'WHERE room_briefs.room_id=?', (room_id,)).fetchone()
        if row is None:
            return None, 0
        if row['body'] == '':
            return None, row['revision']
        return ({'body': row['body'], 'revision': row['revision'], 'author_id': row['author_id'],
                 'author_name': safe_line(row['author_name'] or ''), 'updated': row['updated'], 'carried_from': row['carried_from']},
                row['revision'])

    def _write_brief(self, db, room_id, body, revision, author_id, carried_from=None):
        """The room's one row. A save passes no carried_from: the carried note dates the carried revision only."""
        db.execute('INSERT INTO room_briefs VALUES(?,?,?,?,?,?) ON CONFLICT(room_id) DO UPDATE SET body=excluded.body, '
                   'revision=excluded.revision, author_id=excluded.author_id, updated=excluded.updated, '
                   'carried_from=excluded.carried_from',
                   (room_id, body, revision, author_id, self.clock(), carried_from))

    def save_brief(self, actor, key, body, revision):
        """PUT /api/chats/{id}/brief, for the room's owner. The route has already refused ship keys and a missing CSRF
        token. Saving records no mentions and posts no message."""
        body = brief_body(body)
        if ':' in key:
            raise Problem(404, 'Not found')  # a received room's brief is never written here
        with self.transaction() as db:
            room = self._room(db, actor, key)
            if room['owner_id'] != actor:
                raise Problem(403, 'Only the room owner can change its brief')
            current = self._room_brief(db, key)[1]
            if type(revision) is not int or revision != current:
                raise Problem(409, 'The brief changed since you opened it; look at the newer one before saving')
            self._write_brief(db, key, body, current + 1, actor)
            return self._room_brief(db, key)[0]
