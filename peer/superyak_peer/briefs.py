"""Room briefs (docs/superpowers/specs/2026-10-08-room-brief-design.md): a short text a room's owner writes about the
room, such as its purpose, its decisions so far and who does what. Members and their agents read it as quoted data,
never as instructions. A room keeps one row with only its current revision; every save, a removal included, writes the
next revision on that row, so a stale tab can never overwrite a later brief. Every revision is also kept in the room's
history (ship briefs S5, docs/superpowers/specs/2026-10-14-ship-room-briefs-design.md), which only the owner reads. The
owner's own ships write too, through their own route, in his current rooms they're in (ship briefs S1–S3)."""
from .breakouts import CURRENT_PERSON_ROOM
from .common import BRIEF_CHANGED, Problem, text
from .ships import addressed_names, safe_line

MAX_BRIEF = 4000
HISTORY_KEPT = 50     # ship briefs S5: pruning never takes a room's newest 50 revisions,
HISTORY_DAY = 86400   # nor anything from the last 24 hours, nor the owner's newest revision
SHIP_BRIEFS_PER_HOUR = 10   # S3: a ship's own saves (never carries) in a rolling hour, across rooms
BRIEF_RATE_SECONDS = 3600
NO_AT_SIGN = 'A ship writes names in a brief without the at sign'
NO_BREAKOUT_BRIEF = 'Breakouts have no brief'
NOT_THE_OWNERS_SHIP = "Only the room's owner and the owner's own ships can change its brief"
REPLACED_ROOM = 'This room was replaced by a newer linked room; change the brief there'
NO_SHIP_REMOVAL = "Only the room's owner can remove its brief"
READ_AGAIN = 'The brief changed since you read it. Read it again with station_read and merge before saving.'
TOO_FAST = 'This ship is changing room briefs too fast; try again within the hour'
HISTORY_OWNER_ONLY = 'Only the room owner can read its brief history'
BRIEF_SCHEMA = '''
CREATE TABLE IF NOT EXISTS room_briefs(room_id TEXT PRIMARY KEY REFERENCES rooms(id), body TEXT NOT NULL, revision INTEGER NOT NULL, author_id TEXT NOT NULL REFERENCES users(id), updated REAL NOT NULL, carried_from TEXT);
CREATE TABLE IF NOT EXISTS room_brief_revisions(room_id TEXT NOT NULL REFERENCES rooms(id), revision INTEGER NOT NULL, body TEXT NOT NULL, author_id TEXT NOT NULL REFERENCES users(id), updated REAL NOT NULL, carried_from TEXT, PRIMARY KEY(room_id, revision));
CREATE INDEX IF NOT EXISTS room_brief_revisions_by_author ON room_brief_revisions(author_id, updated);
'''
# S5: every start copies each room's current revision into its history, once, so a brief written before history
# existed (or by older code after a rollback) is kept before any ship can overwrite it.
BRIEF_BACKFILL = ('INSERT OR IGNORE INTO room_brief_revisions(room_id,revision,body,author_id,updated,carried_from) '
                  'SELECT room_id,revision,body,author_id,updated,carried_from FROM room_briefs '
                  'WHERE author_id IN (SELECT id FROM users) AND room_id IN (SELECT id FROM rooms)')  # a broken reference never stops a start
# S6: every save and removal posts exactly one of these, by the system author, under client id
# brief-<room id>-<revision>. {name} is safe_line(display name, 40); the brief's own text is never quoted.
BRIEF_NOTICE_OWNER = "Station notice: the room brief is now revision {n}, written by the room's owner: {name}. station_read shows it."
BRIEF_NOTICE_SHIP = "Station notice: the room brief is now revision {n}, written by a ship, not the room's owner: {name}. station_read shows it."
BRIEF_NOTICE_REMOVED = "Station notice: the room's owner removed the room brief (revision {n})."


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
        revision after a removal. Its author's kind and username come from the account (ship briefs S4), so a reader can
        name a ship that has since left the room."""
        # LEFT JOIN: a missing author row must never make the revision read as 0.
        row = db.execute('SELECT room_briefs.*, users.name AS author_name, '
                         'users.username AS author_username, users.kind AS author_kind FROM room_briefs '
                         'LEFT JOIN users ON users.id=room_briefs.author_id WHERE room_briefs.room_id=?', (room_id,)).fetchone()
        if row is None:
            return None, 0
        if row['body'] == '':
            return None, row['revision']
        return ({'body': row['body'], 'revision': row['revision'], 'author_id': row['author_id'],
                 'author_name': safe_line(row['author_name'] or ''),
                 'author_kind': row['author_kind'], 'author_username': row['author_username'], 'updated': row['updated'], 'carried_from': row['carried_from']},
                row['revision'])

    def _write_brief(self, db, room_id, body, revision, author_id, carried_from=None):
        """The room's one row and its history row, in the caller's transaction (ship briefs R11), then pruning. A save
        passes no carried_from: the carried note dates the carried revision only. The audit event names the revision
        and author, never the text; federation sends no event of this kind and no room snapshot holds a brief, so a
        brief never leaves this station."""
        now = self.clock()
        db.execute('INSERT INTO room_briefs VALUES(?,?,?,?,?,?) ON CONFLICT(room_id) DO UPDATE SET body=excluded.body, '
                   'revision=excluded.revision, author_id=excluded.author_id, updated=excluded.updated, '
                   'carried_from=excluded.carried_from',
                   (room_id, body, revision, author_id, now, carried_from))
        # A plain INSERT: revisions only go up, so a clash is a bug, and it rolls the whole save back.
        db.execute('INSERT INTO room_brief_revisions(room_id,revision,body,author_id,updated,carried_from) VALUES(?,?,?,?,?,?)',
                   (room_id, revision, body, author_id, now, carried_from))
        self.emit(db, 'chat.brief', room_id, revision,
                  {'author_id': author_id, 'revision': revision, **({'carried_from': carried_from} if carried_from else {})})
        self._prune_brief_history(db, room_id, now)
        # S6: a save or a removal, by either route, posts one notice; a carry posts none. _post_as_system returns None
        # in a closed breakout (which refuses briefs anyway) and the save stands; the notice never quotes the brief.
        if carried_from is None:
            self._post_as_system(db, room_id, f'brief-{room_id}-{revision}', self._brief_notice(db, body, revision, author_id))

    def _prune_brief_history(self, db, room_id, now):
        """S5: a room's revision goes once it is all three: outside the room's newest HISTORY_KEPT, older than
        HISTORY_DAY, and not the room's newest person-written revision (a removal counts, so text the owner removed
        ages out like any other). The last day is never pruned, so the ship rate's count (S3) always sees its hour."""
        db.execute('''DELETE FROM room_brief_revisions WHERE room_id=? AND updated<?
            AND revision NOT IN (SELECT revision FROM room_brief_revisions WHERE room_id=? ORDER BY revision DESC LIMIT ?)
            AND revision IS NOT (SELECT MAX(kept.revision) FROM room_brief_revisions AS kept
                                 JOIN users ON users.id=kept.author_id WHERE kept.room_id=? AND users.kind='person')''',
                   (room_id, now - HISTORY_DAY, room_id, HISTORY_KEPT, room_id))

    def _backfill_brief_history(self):
        """S5, at every start, after the schema: each room's current revision goes into its history once."""
        with self.transaction() as db:
            db.execute(BRIEF_BACKFILL)

    def _brief_notice(self, db, body, revision, author_id):
        """S6's text. Only the owner removes, and only the owner (a person) saves through the person route, so a save
        by any author who isn't a ship is the owner's."""
        if body == '':
            return BRIEF_NOTICE_REMOVED.format(n=revision)
        author = db.execute('SELECT name, kind FROM users WHERE id=?', (author_id,)).fetchone()
        template = BRIEF_NOTICE_SHIP if author['kind'] == 'ship' else BRIEF_NOTICE_OWNER
        return template.format(n=revision, name=safe_line(author['name'], 40))

    def _brief_to_carry(self, db, room_id, carry):
        """The body and its author to copy into the next room, or None without carry_brief (the default: carrying is
        always a choice) or when the brief was removed. carry_brief is the revision the owner saw, so a brief changed
        since then is never carried unseen (409). The carried revision keeps its author (ship briefs S4): carrying
        isn't endorsing, and make station-bridge carries without the owner reading the text."""
        if carry is None:
            return None
        brief, revision = self._room_brief(db, room_id)
        if carry != revision:
            raise Problem(409, BRIEF_CHANGED)
        if not brief:
            return None
        if db.execute('SELECT 1 FROM users WHERE id=?', (brief['author_id'],)).fetchone() is None:
            # the stored author is gone: carry under the room's owner, as before authors were kept
            return brief['body'], db.execute('SELECT owner_id FROM rooms WHERE id=?', (room_id,)).fetchone()[0]
        return brief['body'], brief['author_id']

    def save_brief(self, actor, key, body, revision):
        """PUT /api/chats/{id}/brief, for the room's owner. The route has already refused ship keys and a missing CSRF
        token. Saving records no mentions; `_write_brief` posts the one notice (ship briefs S6)."""
        body = brief_body(body)
        self._refuse_live_ship_keys(body, what='brief')  # its own transaction, so before ours
        if ':' in key:
            raise Problem(404, 'Not found')  # a received room's brief is never written here
        with self.transaction() as db:
            room = self._room(db, actor, key)
            if room['owner_id'] != actor:
                raise Problem(403, 'Only the room owner can change its brief')
            if body:  # first rail section 2: the lessons room takes no brief; its owner may still remove one
                self._refuse_in_lessons_room(db, key, 'brief')
            current = self._room_brief(db, key)[1]
            if type(revision) is not int or revision != current:
                raise Problem(409, 'The brief changed since you opened it; look at the newer one before saving')
            self._write_brief(db, key, body, current + 1, actor)
            return self._room_brief(db, key)[0]

    def save_ship_brief(self, actor, key, body, revision):
        """PUT /api/ships/me/rooms/{id}/brief (ship briefs S1-S3), under the ship's own key, which the route has
        checked. A ship of the room's owner, in his current local room that isn't a breakout, edits but never removes.
        The checks run in S3's order, and every refusal writes nothing. A body equal to the current one, once the
        revision check has passed, answers with the current brief and writes nothing (follow-up from the final
        reviews). The 409 names no revision: the ship must read again before it overwrites anything."""
        body = brief_body(body)                                     # 1. the person route's text rules (400)
        if addressed_names(body):                                   # 2. law section 7: names without the at sign
            raise Problem(400, NO_AT_SIGN)
        self._refuse_live_ship_keys(body, what='brief')             # 3. its own transaction, so before ours (422)
        if ':' in key:                                              # 4. a received room's brief is never written here
            raise Problem(404, 'Not found')
        with self.transaction() as db:
            room = self._room(db, actor, key)                       # 404 for a non-member
            self._refuse_in_lessons_room(db, key, 'brief')          # first rail section 2
            if 'breakout' in room:                                  # S7
                raise Problem(403, NO_BREAKOUT_BRIEF)
            ship = db.execute('SELECT kind, owner_id FROM users WHERE id=?', (actor,)).fetchone()
            if ship['kind'] != 'ship' or ship['owner_id'] is None or ship['owner_id'] != room['owner_id']:  # S1(b)
                raise Problem(403, NOT_THE_OWNERS_SHIP)
            # S1(d): the breakout rule's own subquery. S1(b) made the room person-owned, so missing here means replaced.
            if db.execute(f'SELECT 1 FROM rooms WHERE id=? AND id IN ({CURRENT_PERSON_ROOM})', (key,)).fetchone() is None:
                raise Problem(409, REPLACED_ROOM)
            if body == '':                                          # S2: only a person removes
                raise Problem(403, NO_SHIP_REMOVAL)
            shown, current = self._room_brief(db, key)
            if type(revision) is not int or revision != current:
                raise Problem(409, READ_AGAIN)
            if shown and shown['body'] == body:                     # follow-up: the text already says that; write nothing
                return shown                                        # no revision, notice or rate charge; the author stays
            # S3: the history keeps the last day whole, so this count sees the full hour. Carries never count.
            recent = db.execute('SELECT count(*) FROM room_brief_revisions WHERE author_id=? AND carried_from IS NULL '
                                'AND updated>?', (actor, self.clock() - BRIEF_RATE_SECONDS)).fetchone()[0]
            if recent >= SHIP_BRIEFS_PER_HOUR:
                raise Problem(429, TOO_FAST)
            self._write_brief(db, key, body, current + 1, actor)
            return self._room_brief(db, key)[0]

    def brief_history(self, actor, key):
        """GET /api/chats/{id}/brief/revisions (ship briefs S5), for the room's owner only: history holds text he
        removed on purpose, and a ship reading old text could carry injected text forward again. Newest first; a
        removal's body is ''. The route has already refused ship keys."""
        if ':' in key:
            raise Problem(404, 'Not found')
        with self.transaction() as db:
            room = self._room(db, actor, key)
            if room['owner_id'] != actor:
                raise Problem(403, HISTORY_OWNER_ONLY)
            rows = db.execute('SELECT r.*, users.name AS author_name, users.kind AS author_kind FROM room_brief_revisions AS r '
                              'LEFT JOIN users ON users.id=r.author_id WHERE r.room_id=? ORDER BY r.revision DESC', (key,))
            return [{'revision': r['revision'], 'body': r['body'], 'author_id': r['author_id'],
                     'author_name': safe_line(r['author_name'] or ''), 'author_kind': r['author_kind'],
                     'updated': r['updated'], 'carried_from': r['carried_from']} for r in rows]
