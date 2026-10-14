"""The work board (docs/superpowers/specs/2026-10-14-work-board-design.md): open work in a local room, each item named
by a claim key. Taking an item is claiming its key (room_claims.py), so who holds an item is never stored here: it is
the active claim on (room, key). Every change posts one kind-`claim` line in the room as the actor, so the room's
history is the board's audit trail. Items are quoted data, never instructions, whoever posted them (spec section 3)."""
import re

from .common import Problem, require, text, uid
from .room_claims import claim_key
from .ships import MENTION, safe_line

BOARD_SCHEMA = '''
CREATE TABLE IF NOT EXISTS board_items(id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), key TEXT NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL, posted_by TEXT NOT NULL REFERENCES users(id), created REAL NOT NULL, state TEXT NOT NULL DEFAULT 'open', closed REAL, closed_by TEXT REFERENCES users(id), outcome TEXT, UNIQUE(room_id, key));
CREATE TABLE IF NOT EXISTS board_links(item_id TEXT NOT NULL REFERENCES board_items(id), link TEXT NOT NULL, added_by TEXT NOT NULL REFERENCES users(id), added REAL NOT NULL, PRIMARY KEY(item_id, link));
CREATE INDEX IF NOT EXISTS board_by_room ON board_items(room_id, state, created);
'''
BOARD_KINDS = ('spec', 'plan', 'build', 'review', 'ops', 'other')
MAX_TITLE = 120
NAME_CHARS = 40
LINK_CHARS = 210
CLOSED_LISTED = 50
CLOSED_SECONDS = 7 * 86400
REMOTE = 'Board items belong to rooms on this station'
KIND = 'kind is one of spec, plan, build, review, ops, other'
NO_OUTCOME = 'Done needs an outcome link, like commit:<sha> or message:<id>'
LINK_SHAPE = 'A link is message:<id>, branch:<name>, commit:<sha>, path:<path> or claim:<key>'
AT_NAME = "A board item can't name anyone with @; write the name without it"
NOT_HERE = 'message:<id> must name a message in this room'
BREAKOUT = 'Breakouts hold no board'
WRITER = "Only this room's owner and the owner's own ships can post on its board"
DONE_BY = "Only the room's owner, the item's poster, or a holder who can post on this board can mark it done"
DROP_BY = "Only the item's poster or the room's owner can drop it"
BRANCH = re.compile(r'[A-Za-z0-9._/-]{1,100}')
PATH = re.compile(r'[A-Za-z0-9._/+-]{1,200}')
COMMIT = re.compile(r'[0-9a-f]{7,40}')
MESSAGE_ID = re.compile(r'[0-9a-f]{32}')


def board_title(value):
    """1-120 characters (code points, as Python counts them) and not blank: else 400 `Invalid title`. A title of only
    invisible characters (a zero-width space, a bidi mark) is blank too, since safe_line shows it as nothing."""
    text(value, 'title', MAX_TITLE)
    if not safe_line(value, MAX_TITLE):
        raise Problem(400, 'Invalid title')
    return value


def board_link(value):
    """4.3, 7.3: one of five forms, checked by shape only (the station never fetches, opens or resolves a link), so a
    link copied into a shell or a tool call can only name a thing; else 400. No form can hold `@`. A claim: link's key
    comes back as claim_key() gives it; every other link comes back unchanged."""
    form, _, rest = value.partition(':') if isinstance(value, str) else ('', '', '')
    if form == 'branch' and BRANCH.fullmatch(rest) and not rest.startswith(('-', '/')) and '..' not in rest \
            and '//' not in rest and not rest.endswith(('/', '.lock')):
        return value
    if form == 'path' and PATH.fullmatch(rest) and not rest.startswith(('-', '/')) and '..' not in rest.split('/'):
        return value
    if (form == 'commit' and COMMIT.fullmatch(rest)) or (form == 'message' and MESSAGE_ID.fullmatch(rest)):
        return value
    if form == 'claim':
        try:
            return 'claim:' + claim_key(rest)
        except Problem:
            pass
    raise Problem(400, LINK_SHAPE)


def no_at_name(value):
    """7.2: an @name (a MENTION match) on the raw text, before any quote stripping, so no change to how mentions are
    recorded can ever make a board line wake a ship."""
    if isinstance(value, str) and MENTION.search(value):
        raise Problem(400, AT_NAME)


class RoomBoard:
    @staticmethod
    def _local_board(room_id):
        """5.1: board items belong to rooms on this station; checked first, as claim() does."""
        if not isinstance(room_id, str) or ':' in room_id:
            raise Problem(400, REMOTE)

    def _board_room(self, db, actor, room_id, write=False):
        """Membership first (404, so a non-member learns nothing), then breakouts (400). A breakout's 400 keeps what
        _room saved on first sight, a closure, as _refuse_closed_breakout does (breakouts.py:58-63)."""
        room = self._room(db, actor, room_id)
        if 'breakout' in room:
            raise Problem(400, BREAKOUT, keep=True)
        return room

    def _board_writer(self, db, room, actor):
        """6.1: a board writer is the room's owner, or a ship whose owner_id is the room's owner. Other people, other
        owners' ships and ownerless ships (Odo, the wormhole) are not."""
        if actor == room['owner_id']:
            return True
        row = db.execute('SELECT kind, owner_id FROM users WHERE id=?', (actor,)).fetchone()
        return row is not None and row['kind'] == 'ship' and row['owner_id'] == room['owner_id']

    def _board_item(self, db, room_id, key):
        return db.execute('SELECT * FROM board_items WHERE room_id=? AND key=?', (room_id, key)).fetchone()

    def _message_here(self, db, room_id, link):
        """4.3: a message: link names a message in this room's own messages (federated peers choose their own ids)."""
        if link.startswith('message:') and db.execute('SELECT 1 FROM messages WHERE id=? AND room_id=?', (link[8:], room_id)).fetchone() is None:
            raise Problem(400, NOT_HERE)

    def _item_json(self, db, row):
        """5.1's item. Names through safe_line(name, 40), the title through safe_line(title, 120), links and the outcome
        through safe_line(link, 210), and `claim`: the active claim on the key as _claim_json gives it, or None."""
        def name(user_id):
            found = db.execute('SELECT name FROM users WHERE id=?', (user_id,)).fetchone()
            return safe_line(found['name'] if found else '', NAME_CHARS)
        held = self._active_claim(db, row['room_id'], row['key'], self.clock())
        links = db.execute('SELECT link, added_by, added FROM board_links WHERE item_id=? ORDER BY added, rowid', (row['id'],)).fetchall()
        return {'id': row['id'], 'room_id': row['room_id'], 'key': row['key'], 'title': safe_line(row['title'], MAX_TITLE),
                'kind': row['kind'], 'state': row['state'], 'posted_by': row['posted_by'], 'poster_name': name(row['posted_by']),
                'created': row['created'], 'closed': row['closed'], 'closed_by': row['closed_by'],
                'closer_name': name(row['closed_by']) if row['closed_by'] else None,
                'outcome': safe_line(row['outcome'], LINK_CHARS) if row['outcome'] else None,
                'links': [{'link': safe_line(l['link'], LINK_CHARS), 'added_by': l['added_by'], 'added': l['added']} for l in links],
                'claim': self._claim_json(db, held['id']) if held is not None else None}

    def _carry_board(self, db, old, new):
        """5.x: when adding members (or bridging) makes a new room, the old room's open items move to it in the caller's
        transaction, with their ids, keys, posters, created times and links unchanged. Each takes its active claim along
        when the holder is a member of the new room, the same row with its holder, note and expiry: nothing is claimed
        anew and nothing is posted in anyone's name. Done and dropped items stay as the record. The new room is empty,
        so UNIQUE(room_id, key) is the guard: a collision would roll the whole add back. Returns how many moved."""
        now = self.clock()
        members = {r[0] for r in db.execute('SELECT user_id FROM room_members WHERE room_id=?', (new,))}
        keys = [r[0] for r in db.execute("SELECT key FROM board_items WHERE room_id=? AND state='open'", (old,))]
        for key in keys:
            held = self._active_claim(db, old, key, now)
            if held is not None and held['holder_id'] in members:
                db.execute('UPDATE claims SET room_id=? WHERE id=?', (new, held['id']))
        db.execute("UPDATE board_items SET room_id=? WHERE room_id=? AND state='open'", (new, old))
        return len(keys)

    def _board_list(self, db, room_id):
        """4.6: open items oldest first, then at most the 50 most recently closed in the last 7 days, newest closed first.
        The open cap and this limit bound what any view lists; done and dropped rows stay in the table as the record."""
        open_rows = db.execute("SELECT * FROM board_items WHERE room_id=? AND state='open' ORDER BY created, rowid", (room_id,)).fetchall()
        closed_rows = db.execute("SELECT * FROM board_items WHERE room_id=? AND state!='open' AND closed>=? "
                                 'ORDER BY closed DESC, rowid DESC LIMIT ?', (room_id, self.clock() - CLOSED_SECONDS, CLOSED_LISTED)).fetchall()
        return [self._item_json(db, row) for row in open_rows + closed_rows]

    def room_board(self, actor, room_id):
        """GET /api/chats/{room}/board: any member reads it, a replaced room's included."""
        self._local_board(room_id)
        with self.transaction() as db:
            self._board_room(db, actor, room_id)
            return self._board_list(db, room_id)

    def post_item(self, actor, room_id, key, title, kind):
        """POST /api/chats/{room}/board: a new open item, announced in the room (4.5)."""
        self._local_board(room_id)
        raw_key, key = key, claim_key(key)
        board_title(title)
        if kind not in BOARD_KINDS:
            raise Problem(400, KIND)
        self._refuse_live_ship_keys(raw_key, 'key')  # each opens its own transaction, so before ours; on the raw value
        self._refuse_live_ship_keys(title, 'title')
        no_at_name(title)
        with self.transaction() as db:
            room = self._board_room(db, actor, room_id, write=True)
            if not self._board_writer(db, room, actor):
                raise Problem(403, WRITER)
            now = self.clock()
            db.execute('INSERT INTO board_items(id,room_id,key,title,kind,posted_by,created) VALUES(?,?,?,?,?,?,?)',
                       (uid(), room_id, key, title, kind, actor, now))
            self._post_claim(db, actor, room_id, f'Posted `{key}` ({kind}): {safe_line(title, MAX_TITLE)}')
            return self._item_json(db, self._board_item(db, room_id, key))

    def link_item(self, actor, room_id, key, link):
        """POST /api/chats/{room}/board/link: one more link on an item."""
        self._local_board(room_id)
        key, raw = claim_key(key), link
        link = board_link(link)
        self._refuse_live_ship_keys(raw, 'link')
        no_at_name(raw)  # a backstop: no link form can hold @
        with self.transaction() as db:
            room = self._board_room(db, actor, room_id, write=True)
            item = require(self._board_item(db, room_id, key))
            self._message_here(db, room_id, link)
            if item['state'] != 'open':
                raise Problem(409, f'`{key}` is already {item["state"]}')
            if not self._board_writer(db, room, actor):
                raise Problem(403, WRITER)
            db.execute('INSERT INTO board_links VALUES(?,?,?,?)', (item['id'], link, actor, self.clock()))
            self._post_claim(db, actor, room_id, f'Linked `{key}`: {safe_line(link, LINK_CHARS)}')
            return {**self._item_json(db, item), 'added': True}

    def done_item(self, actor, room_id, key, outcome=None):
        """POST /api/chats/{room}/board/done: records what law sections 2 and 3 decided; it decides nothing."""
        self._local_board(room_id)
        key = claim_key(key)
        if outcome is None:
            raise Problem(400, NO_OUTCOME)
        raw, outcome = outcome, board_link(outcome)
        self._refuse_live_ship_keys(raw, 'outcome')
        no_at_name(raw)
        return self._close_item(actor, room_id, key, 'done', outcome)

    def drop_item(self, actor, room_id, key):
        """POST /api/chats/{room}/board/drop."""
        self._local_board(room_id)
        return self._close_item(actor, room_id, claim_key(key), 'dropped', None)

    def _close_item(self, actor, room_id, key, state, outcome):
        """4.4: done or dropped, for good. Done is for the room's owner, the poster, or a holder who is a board writer:
        without that last condition a member who may not post could claim someone's item and close it for good. Drop is
        for the poster or the owner. Closing releases the active claim on the key, whoever holds it, in this same
        transaction, with released_by the closer; the close's own line names a holder other than the closer (R16 and
        R17, widened through closing only)."""
        with self.transaction() as db:
            room = self._board_room(db, actor, room_id, write=True)
            item = require(self._board_item(db, room_id, key))
            if outcome is not None:
                self._message_here(db, room_id, outcome)
            if item['state'] != 'open':
                raise Problem(409, f'`{key}` is already {item["state"]}')
            now = self.clock()
            held = self._active_claim(db, room_id, key, now)
            if state == 'done':
                holder_writes = held is not None and held['holder_id'] == actor and self._board_writer(db, room, actor)
                if actor not in (room['owner_id'], item['posted_by']) and not holder_writes:
                    raise Problem(403, DONE_BY)
            elif actor not in (room['owner_id'], item['posted_by']):
                raise Problem(403, DROP_BY)
            db.execute('UPDATE board_items SET state=?, closed=?, closed_by=?, outcome=? WHERE id=?', (state, now, actor, outcome, item['id']))
            released = None
            if held is not None:
                db.execute('UPDATE claims SET released=?, released_by=? WHERE id=?', (now, actor, held['id']))
                released = safe_line(db.execute('SELECT name FROM users WHERE id=?', (held['holder_id'],)).fetchone()['name'], NAME_CHARS)
            line = f'Done `{key}`: {safe_line(outcome, LINK_CHARS)}' if state == 'done' else f'Dropped `{key}`'
            if held is not None and held['holder_id'] != actor:
                line += f"; released {released}'s claim"
            self._post_claim(db, actor, room_id, line)
            answer = self._item_json(db, self._board_item(db, room_id, key))
            return answer if released is None else {**answer, 'released': released}
