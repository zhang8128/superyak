"""Remote contacts and received resources never become local accounts."""
import json
import math
import re
from .common import Problem, require, uid, text, ids, encode, linked_room_ok

# What a received room may carry: federation._room_snapshot's keys plus the message history, and a message's own
# columns (only those: plus this station's own delivery state and unverified mark, never the origin's). An allowlist, never a denylist (R44).
REMOTE_ROOM_KEYS = ('title', 'owner_id', 'member_ids', 'linked_room_id', 'created', 'last_activity')
UNVERIFIED = ':(unverified)'  # a forged local author's stand-in; no participant id can hold parentheses
# No `state` and no `unverified`: a received message's delivery state and mark are this station's word alone.
REMOTE_MESSAGE_KEYS = ('id', 'room_id', 'author_id', 'client_message_id', 'body', 'epoch', 'created')
PARTICIPANT_ID = re.compile(r'[0-9a-f]{64}:[A-Za-z0-9_-]{1,64}')


def _stored_message_ok(m):
    # The view's backstop for whatever is already stored (section 2 review of 96030b0, SF1), beside receive-time checks.
    return (isinstance(m, dict) and isinstance(m.get('author_id'), str) and PARTICIPANT_ID.fullmatch(m['author_id']) is not None
            and all(isinstance(m.get(k), str) for k in ('id', 'body', 'client_message_id'))
            and type(m.get('created')) in (int, float))

def _stored_time(value, otherwise=0):
    # The view's backstop for a hand-edited time, beside receive's check (remote room fields review, N3): a bool, a NaN
    # or an infinity (JSON reads both, and the HTTP answer refuses NaN) or anything else that is not a finite number
    # counts as `otherwise`.
    return value if type(value) in (int, float) and math.isfinite(value) else otherwise

PEER_SCHEMA = '''
CREATE TABLE IF NOT EXISTS peers(peer_id TEXT PRIMARY KEY, card TEXT NOT NULL, paired INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS remote_contacts(id TEXT PRIMARY KEY, peer_id TEXT NOT NULL REFERENCES peers(peer_id), user_id TEXT NOT NULL, name TEXT NOT NULL, UNIQUE(peer_id,user_id));
CREATE TABLE IF NOT EXISTS remote_room_members(room_id TEXT NOT NULL REFERENCES rooms(id), contact_id TEXT NOT NULL REFERENCES remote_contacts(id), PRIMARY KEY(room_id,contact_id));
CREATE TABLE IF NOT EXISTS pairing_confirmations(contact_id TEXT PRIMARY KEY, code TEXT NOT NULL, confirmed REAL NOT NULL);
CREATE TABLE IF NOT EXISTS contact_holds(contact_id TEXT PRIMARY KEY, held REAL NOT NULL);
CREATE TABLE IF NOT EXISTS peer_messages(id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), author_id TEXT NOT NULL, client_message_id TEXT NOT NULL, body TEXT NOT NULL, epoch INTEGER NOT NULL, created REAL NOT NULL, UNIQUE(room_id,author_id,client_message_id));
CREATE TABLE IF NOT EXISTS inbox(origin TEXT NOT NULL, resource_id TEXT NOT NULL, kind TEXT NOT NULL, recipient TEXT NOT NULL REFERENCES users(id), revision INTEGER NOT NULL, actor TEXT NOT NULL, payload TEXT, PRIMARY KEY(origin,resource_id,kind,recipient));
CREATE TABLE IF NOT EXISTS inbox_received(origin TEXT NOT NULL, resource_id TEXT NOT NULL, recipient TEXT NOT NULL, received REAL NOT NULL, PRIMARY KEY(origin,resource_id,recipient));
CREATE TABLE IF NOT EXISTS receipts(origin TEXT NOT NULL,event_id TEXT NOT NULL,digest TEXT NOT NULL,created REAL NOT NULL, PRIMARY KEY(origin,event_id));
CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, event_seq INTEGER NOT NULL, contact_id TEXT NOT NULL, resource_id TEXT NOT NULL, revision INTEGER NOT NULL, action TEXT NOT NULL, metadata TEXT NOT NULL, envelope TEXT, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0, last_error TEXT, UNIQUE(event_seq,contact_id,action));
CREATE TABLE IF NOT EXISTS federation_cursor(id INTEGER PRIMARY KEY CHECK(id=1), seq INTEGER NOT NULL);
INSERT OR IGNORE INTO federation_cursor VALUES(1,0);
CREATE TABLE IF NOT EXISTS peer_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pull_nonces(origin TEXT NOT NULL, nonce TEXT NOT NULL, at INTEGER NOT NULL, PRIMARY KEY(origin, nonce));
CREATE TABLE IF NOT EXISTS peer_delivery(peer_id TEXT PRIMARY KEY, mode TEXT NOT NULL CHECK(mode IN ('push','pull')), failures INTEGER NOT NULL DEFAULT 0, next_attempt REAL, last_success REAL, last_pull REAL, failing_since REAL, last_problem TEXT);
'''
# Federation pull (plan P2, P3): peer_meta holds federation's own settings, apart from system_meta, which belongs to the
# system author and which the restore reconcile writes. pull_nonces is a listener's replay guard (spec §4, check 6).
# peer_delivery is each paired peer's delivery mode and backoff (spec §7), with failing_since and last_problem beside
# the spec's columns, so `connections` in another process can say why and since when.

class PeerStore:
    def federation_mode(self):
        """`push`, `pull`, or None before any card or federation endpoint (federation-pull spec §1)."""
        with self.transaction() as db:
            row = db.execute("SELECT value FROM peer_meta WHERE key='federation_mode'").fetchone()
            return row[0] if row else None

    def claim_federation_mode(self, mode):
        """Plan P2 (review MF3): the first card or federation endpoint sets the mode, and the same mode again is a no-op,
        so re-exports and restarts work. A different mode is refused, so one identity never exports both kinds of card."""
        if mode not in ('push', 'pull'):
            raise ValueError('The federation mode is push or pull')
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO peer_meta VALUES('federation_mode', ?)", (mode,))
            stored = db.execute("SELECT value FROM peer_meta WHERE key='federation_mode'").fetchone()[0]
        if stored != mode:
            raise ValueError(f'This peer delivers by {stored}, so it cannot export a {mode} card: one identity never '
                             'exports both kinds. A peer of the other kind is a new data directory with a new identity.')

    def _known_contacts(self, db, members):
        for key in members:
            if db.execute("SELECT 1 FROM users WHERE id=? AND kind!='system'", (key,)).fetchone():  # R34: never an audience
                continue
            require(db.execute('SELECT 1 FROM remote_contacts JOIN peers USING(peer_id) WHERE id=? AND paired=1 '
                               'AND id NOT IN (SELECT contact_id FROM contact_holds)', (key,)).fetchone())  # SF3

    def contacts(self, actor):
        with self.transaction() as db:
            local = [dict(r) for r in db.execute("SELECT id,name FROM users WHERE id!=? AND kind!='system' ORDER BY name,id", (actor,))]
            remote = [dict(r) for r in db.execute('SELECT id,name,peer_id,user_id FROM remote_contacts JOIN peers USING(peer_id) WHERE paired=1 '
                                                  'AND id NOT IN (SELECT contact_id FROM contact_holds) ORDER BY name,id')]  # SF3
            return local + [{**r, 'remote': True} for r in remote]

    def _remote_inbox(self, db, actor, key, kind):
        origin, sep, rid = key.partition(':')
        if not sep:
            raise Problem(404, 'Not found')
        row = require(db.execute('SELECT inbox.* FROM inbox JOIN peers ON peers.peer_id=inbox.origin WHERE origin=? AND resource_id=? AND kind=? AND recipient=? AND payload IS NOT NULL AND paired=1', (origin,rid,kind,actor)).fetchone())
        return row, json.loads(row['payload'])

    def remote_layers(self, actor):
        with self.transaction() as db:
            return [self._remote_layer(db, actor, r['origin']+':'+r['resource_id']) for r in db.execute("SELECT inbox.* FROM inbox JOIN peers ON peers.peer_id=inbox.origin WHERE kind='layer' AND recipient=? AND payload IS NOT NULL AND paired=1", (actor,)).fetchall()]

    def _remote_layer(self, db, actor, key):
        row, value = self._remote_inbox(db, actor, key, 'layer')
        return {k:v for k,v in {**value, 'id':key, 'origin':row['origin'], 'owner_id':row['origin']+':'+row['actor'], 'revision':row['revision'], 'resource_version':row['revision'], 'access_routes':['person']}.items() if k != 'files'}

    def remote_layer(self, actor, key):
        with self.transaction() as db:
            return self._remote_layer(db, actor, key)

    def remote_file(self, actor, layer_id, key):
        import base64
        with self.transaction() as db:
            _, value = self._remote_inbox(db, actor, layer_id, 'layer')
            row = next((f for f in value.get('files', []) if f['id'] == key), None)
            require(row)
            return {**row, 'content': base64.b64decode(row['content_base64'])}

    def remote_rooms(self, actor):
        with self.transaction() as db:
            rows = db.execute("SELECT inbox.* FROM inbox JOIN peers ON peers.peer_id=inbox.origin WHERE kind='room' AND recipient=? AND payload IS NOT NULL AND paired=1", (actor,)).fetchall()
            return [self._remote_room(db, actor, r['origin']+':'+r['resource_id'], messages=False) for r in rows]

    def _remote_room(self, db, actor, key, *, messages=True):
        row, value = self._remote_inbox(db, actor, key, 'room')
        # Only the keys a room snapshot has (federation._room_snapshot), as an allowlist: whatever else a paired peer
        # sends -- a brief, a system author, claims, anything new -- never reaches this station's room view (R44).
        result = {k: value[k] for k in REMOTE_ROOM_KEYS if k in value}
        # receive() refuses a malformed roster; a hand-edited member must not break this view or list_rooms either.
        result['members'] = [{'peer': m['peer'], 'id': m['id']} for m in value.get('members', [])
                             if isinstance(m, dict) and isinstance(m.get('peer'), str) and isinstance(m.get('id'), str)]
        result['messages'] = [{k: m[k] for k in REMOTE_MESSAGE_KEYS if k in m} for m in value.get('messages', []) if _stored_message_ok(m)]
        result.update({'id':key, 'origin':row['origin'], 'epoch':row['revision']})
        if not linked_room_ok(result.get('linked_room_id'), row['origin']):  # remote room fields: the backstop for what an older receiver stored
            result['linked_room_id'] = None
        stored = _stored_time(result.get('last_activity'), _stored_time(result.get('created')))
        claimed = max([stored] + [m['created'] for m in result['messages']])
        arrived = db.execute('SELECT received FROM inbox_received WHERE origin=? AND resource_id=? AND recipient=?',
                             (row['origin'], row['resource_id'], actor)).fetchone()
        if arrived is not None:  # remote room fields: the origin's claims count only up to when this station received them
            claimed = min(claimed, arrived['received'])
        queued = []
        replies = db.execute("SELECT outbox.metadata,outbox.status FROM outbox JOIN remote_contacts ON contact_id=remote_contacts.id WHERE resource_id=? AND peer_id=? AND action='room.reply'", (row['resource_id'],row['origin'])).fetchall()
        # Every reply this station sent proves its own words, withdrawn ones too: a reply can reach the origin and then
        # be withdrawn here when its acknowledgement was lost (review of e9a6712). Only queued ones are shown below.
        self._unverified_local_authors(db, replies, row['origin'], result['messages'], actor)
        for delivery in replies:
            meta = json.loads(delivery['metadata'])
            if meta['actor'] != actor or delivery['status'] == 'withdrawn':
                continue
            local = meta['message']
            if not any(m['author_id']==local['author_id'] and m['client_message_id']==local['client_message_id'] for m in result['messages']):
                queued.append({**local, 'state':delivery['status']})
                result['messages'].append(queued[-1])
        # A stable sort on time alone: the origin's own order and this station's queued replies keep their insertion
        # order when several share an instant (ids are random, so they can't break the tie).
        result['messages'].sort(key=lambda m: m['created'])
        result['last_activity'] = max([claimed] + [m['created'] for m in queued])  # this station's queued replies at their own time
        if not messages:
            result.pop('messages', None)
        return result

    def _own_peer_id(self, db=None):
        """This station's peer id, from the store's one identity loader (G4a). A read that fails is not kept. Inside a
        transaction pass its db (see Signatures._station_identity)."""
        return self._station_identity(db).peer_id

    def _unverified_local_authors(self, db, replies, origin, messages, actor):
        """The origin hosts its room and can say anything in it, but never as one of this station's users. A message
        attributed to a local user (<this peer>:<id>) stands only when this station sent that exact reply, its
        room.reply outbox row (author, client message id and body), and only once: an honest origin holds one copy
        (receive keys peer_messages on room, author and client message id), so a later copy is a replay. Anything
        else is shown as the origin's, marked unverified, so it is never "You" and never a local person's words.
        The origin still orders and timestamps its own room: it can drop a reply and show it elsewhere, beside another
        message, and with a replayed copy it chooses which copy comes first (PROTOCOL.md, room.message).
        A copy that stands and matches the viewer's own row shows "delivered": the origin holds those exact words, so
        the reply arrived even if its acknowledgement was lost. Another local user's copy stands with no state here."""
        own = self._own_peer_id(db) + ':'
        sent = {}  # (author, client message id, body) -> whether the row is the viewer's
        for delivery in replies:
            data = json.loads(delivery['metadata'])
            local = data['message']
            sent[(local['author_id'], local['client_message_id'], local['body'])] = data['actor'] == actor
        for message in messages:
            author = message.get('author_id')
            if not (isinstance(author, str) and author.startswith(own)):
                continue
            reply = (author, message.get('client_message_id'), message.get('body'))
            if reply in sent:
                if sent.pop(reply):
                    message['state'] = 'delivered'
            else:
                message['author_id'] = origin + UNVERIFIED  # outside the participant id grammar: matches no contact
                message['unverified'] = True

    def remote_room(self, actor, key):
        with self.transaction() as db:
            return self._remote_room(db, actor, key)

    def remote_send(self, actor, key, client_message_id, body):
        text(client_message_id, 'client message ID', 100)
        text(body, 'message', 20000)
        own_peer = self._own_peer_id()
        with self.transaction() as db:
            row, room = self._remote_inbox(db, actor, key, 'room')
            contact = require(db.execute('SELECT * FROM remote_contacts WHERE peer_id=? AND user_id=?', (row['origin'],row['actor'])).fetchone())
            previous = db.execute("SELECT * FROM outbox WHERE contact_id=? AND resource_id=? AND action='room.reply'", (contact['id'],row['resource_id'])).fetchall()
            for old in previous:
                data = json.loads(old['metadata'])
                if data['actor'] == actor and data['client_message_id'] == client_message_id:
                    if data['body'] != body:
                        raise Problem(409, 'Message ID already used with different text')
                    return {**data['message'], 'state':old['status']}
            self._lessons_gate(db, key, actor, body, client_id=client_message_id)  # first rail section 3: the laying peer's door
            message = {'id':uid(), 'room_id':key, 'author_id':own_peer+':'+actor, 'client_message_id':client_message_id, 'body':body, 'epoch':row['revision'], 'created':self.clock(), 'state':'pending'}
            meta = {'actor':actor, 'body':body, 'client_message_id':client_message_id, 'message':message}
            seq = self.emit(db, 'peer.reply', row['resource_id'], row['revision'])
            db.execute('INSERT INTO outbox(id,event_seq,contact_id,resource_id,revision,action,metadata,status) VALUES(?,?,?,?,?,?,?,?)', (uid(),seq,contact['id'],row['resource_id'],row['revision'],'room.reply',encode(meta),'pending'))
            return message
