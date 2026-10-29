"""Member-only rooms, linked new audiences, epoch-rechecked messages."""
from .common import REPLACED_ROOMS, REPLACED_SEND, Problem, text, ids, uid, require
from .tickets import DEFER_BOUND_SECONDS

# The `since` read's query: it walks the existing events_kind_room_id index (kind, resource_id, id) in id order.
SINCE_SQL = "SELECT id, json_extract(payload, '$.message_id') FROM events WHERE kind='chat.message' AND resource_id=? AND id>? ORDER BY id"

def page_rows_sql(table, count):
    """A page's rows by id. `+room_id` keeps the room filter off the room index so SQLite looks the ids up by primary key."""
    return f'SELECT * FROM {table} WHERE +room_id=? AND id IN ({",".join("?" * count)})'


class Chats:
    def _room(self, db, actor, key):
        row = require(db.execute('SELECT rooms.* FROM rooms JOIN room_members ON rooms.id=room_members.room_id WHERE rooms.id=? AND user_id=?', (key, actor)).fetchone())
        members = [r[0] for r in db.execute('SELECT user_id FROM room_members WHERE room_id=? ORDER BY user_id', (key,))]
        members += [r[0] for r in db.execute('SELECT contact_id FROM remote_room_members WHERE room_id=? ORDER BY contact_id', (key,))]
        activity = db.execute('SELECT (SELECT created FROM room_activity WHERE room_id=?) AS created, (SELECT MAX(created) FROM messages WHERE room_id=?) AS latest_message', (key, key)).fetchone()
        remote_activity = db.execute('SELECT MAX(created) FROM peer_messages WHERE room_id=?', (key,)).fetchone()[0] or 0.0
        created = activity['created'] or 0.0
        room = {**dict(row), 'member_ids': members, 'created': created, 'last_activity': max(created, activity['latest_message'] or 0.0, remote_activity)}
        breakout = self._breakout_mark(db, key)
        if breakout is not None:  # S6: only a breakout carries the key, so every other room is unchanged (R10)
            room['breakout'] = breakout
        room.update(self._cloud_view(db, key, actor))  # never to a cloud model: a marked room only, as for breakouts
        return room

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
            moderating = self._moderating(db, actor)
            for room in rooms:
                if room['id'] in moderating:
                    room['moderating'] = moderating[room['id']]
        rooms = [room for room in rooms if not self._off_the_lists(room)]  # breakouts S12: still readable by id
        return sorted(rooms + self.remote_rooms(actor), key=lambda room: (-room['last_activity'], room['id']))

    def get_room(self, actor, key, page=None):
        if ":" in key:
            room = self.remote_room(actor, key)
            for message in room.get('messages', []):
                message['source'] = None  # a paired peer's payload is passed through: a label in it is never ours
                message['reply_to'] = None
            room['brief'], room['brief_revision'] = None, 0  # briefs never cross stations
            room['moderators'] = []  # moderators never cross stations
            return room
        with self.transaction() as db:
            room = self._room(db, actor, key)
            if page:
                return self._page(db, room, key, page)
            room['messages'] = [dict(r) for r in db.execute('SELECT * FROM messages WHERE room_id=? ORDER BY created, rowid', (key,))]
            sources, replies = self._sources(db, key), self._replies(db, key)
            for message in room['messages']:
                message['source'], message['reply_to'] = sources.get(message['id']), replies.get(message['id'])
            room['messages'] += [dict(r, reply_to=None) for r in db.execute('SELECT * FROM peer_messages WHERE room_id=? ORDER BY created, rowid', (key,))]
            room['messages'].sort(key=lambda m: m['created'])  # stable: ids are random, so one instant keeps insertion order
            return self._room_fields(db, room, key)

    def _message_order(self, db, key):
        """(message id, source) for every message in the room, in display order: (created, source, rowid), local
        messages as source 0 and a paired peer's as 1. That is the stable sort `get_room` makes, without the bodies."""
        return [(r[0], r[1]) for r in db.execute(
            'SELECT id, 0 AS source, created, rowid FROM messages WHERE room_id=? UNION ALL '
            'SELECT id, 1, created, rowid FROM peer_messages WHERE room_id=? ORDER BY created, source, rowid', (key, key))]

    def _room_seq(self, db, key):
        return db.execute("SELECT COALESCE(MAX(id), 0) FROM events WHERE kind='chat.message' AND resource_id=?", (key,)).fetchone()[0]

    def _page(self, db, room, key, page):
        """The room with only a window of its messages, picked by position (chat paging). The room's other fields are
        the full read's, `system_author` included, so a client never merges them across pages."""
        order = self._message_order(db, key)
        total, limit = len(order), page.get('limit', 100)
        if 'since' in page:
            return self._since(db, room, key, page, order)
        where = [name for name in ('before', 'at', 'start', 'after') if name in page]
        if where == ['before']:
            if not 0 <= page['before'] <= total:
                raise Problem(400, f'before must be between 0 and {total}')
            end = page['before']
            begin = max(0, end - limit)
        elif where:
            if where == ['at']:
                if not 0 <= page['at'] < max(total, 1):  # an empty room has the one empty window
                    raise Problem(400, f'at must be between 0 and {total - 1}')
                begin = page['at']
            else:
                known = [i for i, (message_id, _) in enumerate(order) if message_id == page[where[0]]]
                if not known:
                    raise Problem(404, 'No message in this room')
                begin = known[0] + (where == ['after'])
            end = min(total, begin + limit)
        else:  # limit alone: the newest
            begin, end = max(0, total - limit), total
        picked = order[begin:end]
        room['messages'] = self._messages_of(db, key, picked)
        room.update(paged=True, total=total, first_position=begin, seq=self._room_seq(db, key))
        return self._room_fields(db, room, key)

    def _since(self, db, room, key, page, order):
        """What arrived after event `since`: the oldest `limit` messages by `chat.message` event id, shown in display
        order. Arrival order, not position, so a federated message that lands late with an older `created` is still
        seen once. An event whose message is not in the room's order is passed over, its cursor position included."""
        position = {message_id: i for i, (message_id, _) in enumerate(order)}
        limit, taken, last, more = page.get('limit', 100), [], None, False
        for event_id, message_id in db.execute(SINCE_SQL, (key, page['since'])):
            if message_id not in position:
                continue
            if len(taken) == limit:
                more = True
                break
            taken.append(position[message_id])
            last = event_id
        taken.sort()
        picked = [order[i] for i in taken]
        room.update(paged=True, total=len(order), first_position=taken[0] if taken else len(order), more=more,
                    seq=last if more else self._room_seq(db, key))
        room['messages'] = self._messages_of(db, key, picked)
        return self._room_fields(db, room, key)

    def _messages_of(self, db, key, picked):
        local, peer = [m for m, source in picked if source == 0], [m for m, source in picked if source == 1]
        rows = {}
        for table, wanted in (('messages', local), ('peer_messages', peer)):
            rows.update({r['id']: dict(r) for r in db.execute(page_rows_sql(table, len(wanted)), (key, *wanted))})
        sources, replies = self._sources(db, key, local), self._replies(db, key, local)
        return [dict(rows[m], source=sources.get(m), reply_to=replies.get(m)) if source == 0 else dict(rows[m], reply_to=None)
                for m, source in picked]

    def _room_fields(self, db, room, key):
        """The room fields both reads share, whatever messages they hold. `system_author` is room-wide."""
        room['members'] = [dict(r) for r in db.execute(
            'SELECT users.id,users.username,users.name,users.kind,users.owner_id FROM room_members JOIN users ON users.id=room_members.user_id WHERE room_members.room_id=? ORDER BY users.id',
            (key,))]
        room['brief'], room['brief_revision'] = self._room_brief(db, key)
        system = self.system_author_id(db)
        if db.execute('SELECT 1 FROM messages WHERE room_id=? AND author_id=? LIMIT 1', (key, system)).fetchone():
            room['system_author'] = self.system_author_public(db)
        room['claims'] = self._active_claims(db, key)
        room['moderators'] = list({m['id']: {'id': m['id'], 'name': m['name']} for m in self._moderators(db, key)}.values())  # a holder once, however many grants
        return room

    def _said_before_replacement(self, db, room_id, message_id):
        """Whether a message in a replaced room was posted before the room that continues it was made, by event order
        (event ids only grow, whatever the clock does). A message with no event, or a room with no recorded
        replacement, counts as not before: fail closed."""
        replaced_at = db.execute('SELECT min(id) FROM events WHERE resource_id IN '
                                 '(SELECT id FROM rooms WHERE linked_room_id=?)', (room_id,)).fetchone()[0]
        posted_at = db.execute("SELECT id FROM events WHERE kind='chat.message' AND resource_id=? "
                               "AND json_extract(payload, '$.message_id')=?", (room_id, message_id)).fetchone()
        return replaced_at is not None and posted_at is not None and posted_at[0] < replaced_at

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
            # A new conversation goes to the room that continues a replaced one, as adds say. An answer (a reply to a
            # message from before the add, or a run's labelled reply) still lands beside its question: a mention made
            # before an add is answered where it was asked, and a ship's finished run never loses its reply. A reply to
            # something said after the add would carry the conversation on where the new member never sees it.
            replaced = db.execute(f'SELECT 1 WHERE ? IN ({REPLACED_ROOMS})', (key,)).fetchone() is not None
            if replaced and (reply_to is None and ticket_id is None
                             or reply_to is not None and not self._said_before_replacement(db, key, reply_to)):
                raise Problem(409, REPLACED_SEND)
            self._lessons_gate(db, key, actor, body, labelled=ticket_id is not None or reply_to is not None,
                               client_id=client_message_id)  # first rail section 3
            self._refuse_closed_breakout(db, key)
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
            if not replaced:  # an answer in a replaced room starts no run and calls no one there
                self._record_mentions(db, key, message_id, body)
            self.emit(db, 'chat.message', key, room['epoch'], {'message_id': message_id, 'author_id': actor})
            sent = dict(db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone(), replayed=False)
            if reply_to is None:  # R27: this ship's deferred mentions here that still wait (stale deferrals spec)
                # The SQL bound only keeps the IN list to the last two hours' rows (rows past it never age out); the helper decides.
                held = [r[0] for r in db.execute('''SELECT deferrals.message_id FROM deferrals JOIN messages
                    ON messages.id=deferrals.message_id WHERE deferrals.ship_id=? AND messages.room_id=?
                    AND deferrals.first_deferred > ?''', (actor, key, self.clock() - DEFER_BOUND_SECONDS))]
                waiting = self._waiting_deferrals(db, actor, held)
                if waiting:  # R35: present only when it has something to say
                    sent['deferred_here'] = waiting
            return sent

    def can_deliver_message(self, message_id, recipient_id, epoch):
        """Trusted transport hook: rejects messages queued under obsolete room epochs."""
        with self.transaction() as db:
            row = db.execute('SELECT messages.epoch AS message_epoch,rooms.epoch FROM messages JOIN rooms ON rooms.id=messages.room_id JOIN room_members ON room_members.room_id=rooms.id WHERE messages.id=? AND room_members.user_id=?', (message_id, recipient_id)).fetchone()
            return bool(row and row['epoch'] == epoch and row['message_epoch'] == epoch)
