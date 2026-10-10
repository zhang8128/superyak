"""Remote contacts and received resources never become local accounts."""
import json
from .common import Problem, require, uid, text, ids, encode

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
        result = {**value, 'id':key, 'origin':row['origin'], 'epoch':row['revision']}
        for key_name in ('brief', 'brief_revision'):  # briefs never cross stations: what a paired peer sends is dropped
            result.pop(key_name, None)
        pending = db.execute("SELECT outbox.metadata,outbox.status FROM outbox JOIN remote_contacts ON contact_id=remote_contacts.id WHERE resource_id=? AND peer_id=? AND action='room.reply' AND status!='withdrawn'", (row['resource_id'],row['origin'])).fetchall()
        for delivery in pending:
            meta = json.loads(delivery['metadata'])
            if meta['actor'] != actor:
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

    def remote_room(self, actor, key):
        with self.transaction() as db:
            return self._remote_room(db, actor, key)

    def remote_send(self, actor, key, client_message_id, body):
        text(client_message_id, 'client message ID', 100)
        text(body, 'message', 20000)
        from .identity import PeerIdentity
        own_peer = PeerIdentity.load_or_create(self.data_dir).peer_id
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
