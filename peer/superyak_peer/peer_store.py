"""Remote contacts and received resources never become local accounts."""
import json
from .common import Problem, require, uid, text, ids, encode

# What a received room may carry: federation._room_snapshot's keys plus the message history, and a message's own
# columns (plus this station's delivery state for a queued reply). An allowlist, never a denylist (R44).
REMOTE_ROOM_KEYS = ('title', 'owner_id', 'member_ids', 'linked_room_id', 'created', 'last_activity')
UNVERIFIED = ':(unverified)'  # a forged local author's stand-in; no participant id can hold parentheses
REMOTE_MESSAGE_KEYS = ('id', 'room_id', 'author_id', 'client_message_id', 'body', 'epoch', 'created', 'state')

PEER_SCHEMA = '''
CREATE TABLE IF NOT EXISTS peers(peer_id TEXT PRIMARY KEY, card TEXT NOT NULL, paired INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS remote_contacts(id TEXT PRIMARY KEY, peer_id TEXT NOT NULL REFERENCES peers(peer_id), user_id TEXT NOT NULL, name TEXT NOT NULL, UNIQUE(peer_id,user_id));
CREATE TABLE IF NOT EXISTS remote_room_members(room_id TEXT NOT NULL REFERENCES rooms(id), contact_id TEXT NOT NULL REFERENCES remote_contacts(id), PRIMARY KEY(room_id,contact_id));
CREATE TABLE IF NOT EXISTS peer_messages(id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), author_id TEXT NOT NULL, client_message_id TEXT NOT NULL, body TEXT NOT NULL, epoch INTEGER NOT NULL, created REAL NOT NULL, UNIQUE(room_id,author_id,client_message_id));
CREATE TABLE IF NOT EXISTS inbox(origin TEXT NOT NULL, resource_id TEXT NOT NULL, kind TEXT NOT NULL, recipient TEXT NOT NULL REFERENCES users(id), revision INTEGER NOT NULL, actor TEXT NOT NULL, payload TEXT, PRIMARY KEY(origin,resource_id,kind,recipient));
CREATE TABLE IF NOT EXISTS receipts(origin TEXT NOT NULL,event_id TEXT NOT NULL,digest TEXT NOT NULL,created REAL NOT NULL, PRIMARY KEY(origin,event_id));
CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, event_seq INTEGER NOT NULL, contact_id TEXT NOT NULL, resource_id TEXT NOT NULL, revision INTEGER NOT NULL, action TEXT NOT NULL, metadata TEXT NOT NULL, envelope TEXT, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0, UNIQUE(event_seq,contact_id,action));
CREATE TABLE IF NOT EXISTS federation_cursor(id INTEGER PRIMARY KEY CHECK(id=1), seq INTEGER NOT NULL);
INSERT OR IGNORE INTO federation_cursor VALUES(1,0);
'''

class PeerStore:
    def _known_contacts(self, db, members):
        for key in members:
            if db.execute("SELECT 1 FROM users WHERE id=? AND kind!='system'", (key,)).fetchone():  # R34: never an audience
                continue
            require(db.execute('SELECT 1 FROM remote_contacts JOIN peers USING(peer_id) WHERE id=? AND paired=1', (key,)).fetchone())

    def contacts(self, actor):
        with self.transaction() as db:
            local = [dict(r) for r in db.execute("SELECT id,name FROM users WHERE id!=? AND kind!='system' ORDER BY name,id", (actor,))]
            remote = [dict(r) for r in db.execute('SELECT id,name,peer_id,user_id FROM remote_contacts JOIN peers USING(peer_id) WHERE paired=1 ORDER BY name,id')]
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
        result['members'] = [{'peer': m['peer'], 'id': m['id']} for m in value.get('members', [])]
        result['messages'] = [{k: m[k] for k in REMOTE_MESSAGE_KEYS if k in m} for m in value.get('messages', [])]
        result.update({'id':key, 'origin':row['origin'], 'epoch':row['revision']})
        replies = db.execute("SELECT outbox.metadata,outbox.status FROM outbox JOIN remote_contacts ON contact_id=remote_contacts.id WHERE resource_id=? AND peer_id=? AND action='room.reply'", (row['resource_id'],row['origin'])).fetchall()
        # Every reply this station sent proves its own words, withdrawn ones too: a reply can reach the origin and then
        # be withdrawn here when its acknowledgement was lost (review of e9a6712). Only queued ones are shown below.
        self._unverified_local_authors(replies, row['origin'], result['messages'])
        for delivery in replies:
            meta = json.loads(delivery['metadata'])
            if meta['actor'] != actor or delivery['status'] == 'withdrawn':
                continue
            local = meta['message']
            if not any(m['author_id']==local['author_id'] and m['client_message_id']==local['client_message_id'] for m in result['messages']):
                result['messages'].append({**local, 'state':delivery['status']})
        # A stable sort on time alone: the origin's own order and this station's queued replies keep their insertion
        # order when several share an instant (ids are random, so they can't break the tie).
        result['messages'].sort(key=lambda m: m['created'])
        result['last_activity'] = max([result['last_activity']] + [m['created'] for m in result['messages']])
        if not messages:
            result.pop('messages', None)
        return result

    def _own_peer_id(self):
        """This station's peer id, read from its identity file once: the id never changes for a data directory."""
        if not hasattr(self, '_peer_id_cache'):
            from .identity import PeerIdentity
            self._peer_id_cache = PeerIdentity.load_or_create(self.data_dir).peer_id
        return self._peer_id_cache

    def _unverified_local_authors(self, replies, origin, messages):
        """The origin hosts its room and can say anything in it, but never as one of this station's users. A message
        attributed to a local user (<this peer>:<id>) stands only when this station sent that exact reply, its
        room.reply outbox row (author, client message id and body), and only once: an honest origin holds one copy
        (receive keys peer_messages on room, author and client message id), so a later copy is a replay. Anything
        else is shown as the origin's, marked unverified, so it is never "You" and never a local person's words.
        The origin still orders and timestamps its own room: it can drop a reply and show it elsewhere, beside another
        message, and with a replayed copy it chooses which copy comes first (PROTOCOL.md, room.message)."""
        own = self._own_peer_id() + ':'
        sent = set()
        for delivery in replies:
            local = json.loads(delivery['metadata'])['message']
            sent.add((local['author_id'], local['client_message_id'], local['body']))
        for message in messages:
            author = message.get('author_id')
            if not (isinstance(author, str) and author.startswith(own)):
                continue
            reply = (author, message.get('client_message_id'), message.get('body'))
            if reply in sent:
                sent.discard(reply)
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
            message = {'id':uid(), 'room_id':key, 'author_id':own_peer+':'+actor, 'client_message_id':client_message_id, 'body':body, 'epoch':row['revision'], 'created':self.clock(), 'state':'pending'}
            meta = {'actor':actor, 'body':body, 'client_message_id':client_message_id, 'message':message}
            seq = self.emit(db, 'peer.reply', row['resource_id'], row['revision'])
            db.execute('INSERT INTO outbox(id,event_seq,contact_id,resource_id,revision,action,metadata,status) VALUES(?,?,?,?,?,?,?,?)', (uid(),seq,contact['id'],row['resource_id'],row['revision'],'room.reply',encode(meta),'pending'))
            return message
