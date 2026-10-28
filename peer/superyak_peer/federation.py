"""Durable paired exchange; all outbound bodies derive from final authorized state."""
import base64
import hashlib
import json
import re
import threading
from .identity import PeerIdentity, validate_card, verify_envelope, canonical, parse, pairing_code, show_code, typed_code
from .common import Problem, require, uid, encode, text, linked_room_ok

class Obsolete(Exception):
    pass

class _NoIdentity:
    """A peer with no identity yet, for the CLI's pair and connections, which never make one (fix:pairing-code SF2):
    `card --endpoint` makes it, naming its host. Truthy, so Federation keeps it; any use raises."""
    def __bool__(self):
        return True

    def __getattr__(self, name):
        raise RuntimeError('This peer has no identity yet; card --endpoint makes one')

NO_IDENTITY = _NoIdentity()
TRUST_KEYS = ('signing_key', 'certificate', 'fingerprint', 'endpoint')  # a known peer's, never replaced
HELD = 'SELECT 1 FROM contact_holds WHERE contact_id=remote_contacts.id'  # a contact waiting for its own code (SF3)

class Federation:
    def __init__(self, store, *, endpoint, identity=None):
        self.store, self.endpoint = store, endpoint
        self.identity = identity or PeerIdentity.load_or_create(store.data_dir)
        self._sync_lock = threading.Lock()

    def card(self, actor):
        """A v1 card with this peer's endpoint, or a v2 card with none once its mode is pull (federation-pull spec §2)."""
        pull = self.store.federation_mode() == 'pull'
        with self.store.transaction() as db:
            user = require(db.execute('SELECT id,name FROM users WHERE id=?', (actor,)).fetchone())
            if pull:
                return self.identity.card(None, dict(user), delivery='pull')
            return self.identity.card(self.endpoint, dict(user))

    def pair(self, actor, card, *, code):
        """fix:pairing-code (federation-pull spec §2): an admin pairs a card only with the other side's code, typed off
        that machine's screen. One check, here, after the admin check; the confirmation keeps the card's code, never
        the typed text."""
        card = validate_card(card)
        if self.identity is not NO_IDENTITY and card['peer_id'] == self.identity.peer_id:  # no identity: no card of ours
            raise Problem(400, 'Cannot pair this peer with itself')
        with self.store.transaction() as db:
            self.store._admin(db, actor)
            expected, typed = pairing_code(card), typed_code(code)
            if typed is None:
                raise Problem(400, 'Type the pairing code shown on the other machine')
            if typed != expected:
                raise Problem(400, f"That code doesn't match this card. Its code is {show_code(expected)}; read the "
                                   "other machine's screen again.")
            mode = card.get('delivery', 'push')  # the effective mode: a v1 card has no `delivery` (spec §2)
            here = db.execute("SELECT value FROM peer_meta WHERE key='federation_mode'").fetchone()
            if mode == 'pull' and here and here[0] == 'pull':
                raise Problem(400, 'Two pull peers can never reach each other: pair a pull card on a peer that listens')
            previous = db.execute('SELECT card, paired FROM peers WHERE peer_id=?', (card['peer_id'],)).fetchone()
            if previous:
                prior = json.loads(previous['card'])
                if prior.get('delivery', 'push') != mode:  # compared first, so a v1 prior meets a v2 card with no KeyError
                    raise Problem(409, 'A known peer cannot change how it delivers; a pull peer is a new identity')
                if any(prior[k] != card[k] for k in TRUST_KEYS):
                    raise Problem(409, 'Known peer trust material cannot be replaced')
            # The confirmation is for the card connections() will rebuild (the stored card with this participant), so
            # a field the 409 list doesn't name can never make "confirmed by typing" describe another card (pairing
            # review SF2).
            if pairing_code({**(prior if previous else card), 'participant': card['participant']}) != expected:
                raise Problem(409, 'Known peer trust material cannot be replaced')
            if previous and not previous['paired']:
                # Serenity's review MF2: a peer unpaired with no holds (by main's unpair, before this branch or after a
                # rollback, or in a copy restored from before holds) gets every contact held and unconfirmed first, so
                # "unpaired" means "every contact held" whatever made it, and this pair releases the typed one only.
                db.execute('INSERT OR IGNORE INTO contact_holds SELECT id, ? FROM remote_contacts WHERE peer_id=?',
                           (self.store.clock(), card['peer_id']))
                db.execute('DELETE FROM pairing_confirmations WHERE contact_id IN '
                           '(SELECT id FROM remote_contacts WHERE peer_id=?)', (card['peer_id'],))
            db.execute('INSERT INTO peers VALUES(?,?,1) ON CONFLICT(peer_id) DO UPDATE SET paired=1', (card['peer_id'], encode(card)))
            # spec §7 and plan P14: the mode from the card, on both paths; a person re-pairing makes the peer due again
            db.execute('INSERT INTO peer_delivery(peer_id, mode, failures) VALUES(?,?,0) ON CONFLICT(peer_id) DO UPDATE SET '
                       'failures=0, next_attempt=NULL, failing_since=NULL', (card['peer_id'], mode))
            db.execute('INSERT INTO remote_contacts VALUES(?,?,?,?) ON CONFLICT(peer_id,user_id) DO UPDATE SET name=excluded.name', ('remote_'+uid(), card['peer_id'],card['participant']['id'],card['participant']['name']))
            contact = dict(db.execute('SELECT * FROM remote_contacts WHERE peer_id=? AND user_id=?', (card['peer_id'],card['participant']['id'])).fetchone())
            db.execute('INSERT INTO pairing_confirmations VALUES(?,?,?) ON CONFLICT(contact_id) DO UPDATE SET '
                       'code=excluded.code, confirmed=excluded.confirmed', (contact['id'], expected, self.store.clock()))
            db.execute('DELETE FROM contact_holds WHERE contact_id=?', (contact['id'],))  # this one's code was typed
            return {**contact, 'pairing_code': show_code(expected), 'confirmed': True, 'held': False}

    def unpair(self, actor, contact_id):
        """Disconnects the whole peer. Every contact of it is held, and loses its confirmation, so pairing one
        participant again reconnects that one only: each other one waits for its own code (pairing review SF3)."""
        with self.store.transaction() as db:
            self.store._admin(db, actor)
            row = require(db.execute('SELECT peer_id FROM remote_contacts WHERE id=?', (contact_id,)).fetchone())
            siblings = "SELECT id FROM remote_contacts WHERE peer_id=?"
            db.execute(f'INSERT OR REPLACE INTO contact_holds SELECT id, ? FROM remote_contacts WHERE peer_id=?',
                       (self.store.clock(), row['peer_id']))
            db.execute(f'DELETE FROM pairing_confirmations WHERE contact_id IN ({siblings})', (row['peer_id'],))
            db.execute('UPDATE peers SET paired=0 WHERE peer_id=?', (row['peer_id'],))
            db.execute("UPDATE outbox SET status='withdrawn' WHERE contact_id IN (SELECT id FROM remote_contacts WHERE peer_id=?) AND status IN ('pending','failed')", (row['peer_id'],))
            db.execute('UPDATE inbox SET payload=NULL WHERE origin=?', (row['peer_id'],))
        return {'ok':True}

    def connections(self, actor):
        """Each contact with the card it was paired with: peers.card with the contact's own id and name, which is the
        card last imported for it, whether a typed code confirmed that card, and whether it's held. A confirmation
        counts only while its code is still the card's (fix:pairing-code, re-check SF1). The code is listed only for
        a confirmed contact: shown for any other, it could be copied into a re-pair with no screens compared
        (pairing review, nit 1)."""
        with self.store.transaction() as db:
            self.store._admin(db, actor)
            rows = db.execute('SELECT remote_contacts.*,peers.card,peers.paired,pairing_confirmations.code AS confirmed_code,'
                              'contact_holds.contact_id IS NOT NULL AS held '
                              'FROM remote_contacts JOIN peers USING(peer_id) '
                              'LEFT JOIN pairing_confirmations ON pairing_confirmations.contact_id=remote_contacts.id '
                              'LEFT JOIN contact_holds ON contact_holds.contact_id=remote_contacts.id').fetchall()
        listed = []
        for r in rows:
            fields = {k: r[k] for k in r.keys() if k not in ('confirmed_code', 'held')}
            card = {**json.loads(r['card']), 'participant': {'id': r['user_id'], 'name': r['name']}}
            try:
                code = pairing_code(card)
            except Problem:  # a stored card that no longer validates has no code to show
                code = None
            confirmed = code is not None and r['confirmed_code'] == code
            listed.append({**fields, 'card': card, 'pairing_code': show_code(code) if confirmed else None,
                           'confirmed': confirmed, 'held': bool(r['held'])})
        return listed

    def collect(self):
        with self.store.transaction() as db:
            seq = db.execute('SELECT seq FROM federation_cursor WHERE id=1').fetchone()[0]
            events = db.execute('SELECT * FROM events WHERE id>? ORDER BY id', (seq,)).fetchall()
            for event in events:
                kind, rid = event['kind'], event['resource_id']
                contacts = set()
                if kind.startswith('layer.'):
                    layer = db.execute('SELECT * FROM layers WHERE id=?', (rid,)).fetchone()
                    if layer and layer['active_revision']:
                        snapshot = json.loads(db.execute('SELECT snapshot FROM layer_revisions WHERE layer_id=? AND revision=?', (rid,layer['active_revision'])).fetchone()[0])
                        contacts.update(u for u in snapshot['audience_users'] if u.startswith('remote_'))
                    contacts.update(r[0] for r in db.execute("SELECT DISTINCT contact_id FROM outbox WHERE resource_id=? AND action LIKE 'layer.%'", (rid,)))
                    action = 'layer.withdraw' if kind == 'layer.withdrawn' else 'layer.release'
                elif kind in ('chat.message', 'chat.membership'):
                    if kind == 'chat.message' and self.store._never_federates(db, json.loads(event['payload']).get('message_id')):
                        continue  # R33: system and kind messages stay on this station
                    contacts.update(r[0] for r in db.execute('SELECT contact_id FROM remote_room_members WHERE room_id=?', (rid,)))
                    contacts.update(r[0] for r in db.execute("SELECT DISTINCT contact_id FROM outbox WHERE resource_id=? AND action IN ('room.roster','room.message','room.withdraw')", (rid,)))
                    action = 'room.message' if kind == 'chat.message' else 'room.roster'
                else:
                    continue
                held = {r[0] for r in db.execute('SELECT contact_id FROM contact_holds')}  # nothing queued for them (SF3)
                for contact in contacts - held:
                    db.execute('INSERT OR IGNORE INTO outbox(id,event_seq,contact_id,resource_id,revision,action,metadata,status) VALUES(?,?,?,?,?,?,?,?)', (uid(),event['id'],contact,rid,event['resource_version'],action,event['payload'],'pending'))
            if events:
                db.execute('UPDATE federation_cursor SET seq=? WHERE id=1', (events[-1]['id'],))

    def _room_snapshot(self, db, room):
        origin = self.identity.peer_id
        members = [{'peer':origin, 'id':r[0]} for r in db.execute('SELECT user_id FROM room_members WHERE room_id=?', (room['id'],))]
        members += [{'peer':r['peer_id'], 'id':r['user_id']} for r in db.execute('SELECT remote_contacts.* FROM remote_contacts JOIN remote_room_members ON contact_id=remote_contacts.id WHERE room_id=?', (room['id'],))]
        activity = db.execute('SELECT created FROM room_activity WHERE room_id=?', (room['id'],)).fetchone()
        return {'title':room['title'], 'owner_id':origin+':'+room['owner_id'], 'member_ids':[m['peer']+':'+m['id'] for m in members], 'members':members, 'linked_room_id':origin+':'+room['linked_room_id'] if room['linked_room_id'] else None, 'created':activity[0] if activity else 0, 'last_activity':self.store.clock()}

    def _prepare(self, key):
        with self.store.transaction() as db:
            row = require(db.execute('SELECT * FROM outbox WHERE id=?', (key,)).fetchone())
            if row['status'] not in ('pending','failed'):
                raise Obsolete()
            contact = db.execute(f'SELECT remote_contacts.*,peers.paired,EXISTS({HELD}) AS held FROM remote_contacts JOIN peers USING(peer_id) WHERE id=?', (row['contact_id'],)).fetchone()
            if not contact or not contact['paired'] or contact['held']:  # a held contact gets nothing (SF3)
                raise Obsolete()
            action, revision, rid = row['action'], row['revision'], row['resource_id']
            meta = json.loads(row['metadata'])
            if action.startswith('layer.'):
                layer = require(db.execute('SELECT * FROM layers WHERE id=?', (rid,)).fetchone())
                if layer['resource_version'] != revision:
                    raise Obsolete()
                actor = layer['owner_id']
                payload = {}
                if layer['active_revision']:
                    snap = json.loads(db.execute('SELECT snapshot FROM layer_revisions WHERE layer_id=? AND revision=?', (rid,revision)).fetchone()[0])
                    if contact['id'] in snap['audience_users']:
                        action = 'layer.release'
                        payload = {k:snap[k] for k in ('title','body','attachment_ids')}
                        payload['files'] = [{**{k:f[k] for k in ('id','name','media_type','digest','size')}, 'content_base64':base64.b64encode(f['content']).decode()} for fid in snap['attachment_ids'] for f in [require(db.execute('SELECT * FROM files WHERE id=? AND owner_id=?', (fid,actor)).fetchone())]]
                    else:
                        action = 'layer.withdraw'
                else:
                    action = 'layer.withdraw'
            elif action == 'room.reply':
                try:
                    inbox, room = self.store._remote_inbox(db, meta['actor'], contact['peer_id']+':'+rid, 'room')
                except Problem as exc:
                    if exc.status == 404:
                        raise Obsolete() from None
                    raise
                if inbox['revision'] != revision:
                    raise Obsolete()
                actor = meta['actor']
                payload = {k:meta[k] for k in ('body','client_message_id')}
            else:
                room = require(db.execute('SELECT * FROM rooms WHERE id=?', (rid,)).fetchone())
                if room['epoch'] != revision:
                    raise Obsolete()
                actor = room['owner_id']
                member = db.execute('SELECT 1 FROM remote_room_members WHERE room_id=? AND contact_id=?', (rid,contact['id'])).fetchone()
                if not member:
                    action, payload = 'room.withdraw', {}
                else:
                    payload = self._room_snapshot(db, room)
                    if action == 'room.message':
                        message = db.execute('SELECT * FROM messages WHERE id=?', (meta.get('message_id'),)).fetchone()
                        remote = False
                        if message is None:
                            message = db.execute('SELECT * FROM peer_messages WHERE id=?', (meta.get('message_id'),)).fetchone()
                            remote = True
                        if not message or message['epoch'] != revision:
                            raise Obsolete()
                        payload['message'] = {**dict(message), 'author_id':message['author_id'] if remote else self.identity.peer_id+':'+message['author_id']}
            if row['envelope']:
                envelope = parse(row['envelope'])
                # A retry preserves the exact signed event. Current checks above
                # must still pass and action must still be authorized.
                if envelope['action'] != action:
                    raise Obsolete()
            else:
                envelope = self.identity.envelope(destination=contact['peer_id'],actor=actor,resource_id=rid,revision=revision,action=action,recipients=[contact['user_id']],payload=payload,event_id=key)
                if len(canonical(envelope)) > 6 * 1024 * 1024:
                    raise Problem(413, 'Remote release is too large')
                db.execute('UPDATE outbox SET envelope=? WHERE id=?', (canonical(envelope).decode(),key))
            return canonical(envelope)

    def sync_once(self, *, send=None, limit=20):
        from .transport import send_pinned, PinMismatch, PeerAnswer
        import http.client
        result = {'delivered':0, 'withdrawn':0, 'failed':0, 'pending':0}
        if not self._sync_lock.acquire(blocking=False):
            return {**result, 'busy':True}
        try:
            self.collect()
            with self.store.transaction() as db:
                work = [dict(r) for r in db.execute("SELECT outbox.*,peers.card FROM outbox JOIN remote_contacts ON contact_id=remote_contacts.id JOIN peers USING(peer_id) WHERE status IN ('pending','failed') AND attempts<8 AND next_attempt<=? ORDER BY event_seq,id LIMIT ?", (self.store.clock(),min(100,max(1,limit))))]
            for row in work:
                try:
                    card = json.loads(row['card'])
                    if send:
                        send(card, lambda:self._prepare(row['id']))
                    else:
                        send_pinned(card, lambda:self._prepare(row['id']), gate=self.store.dispatch_gate)
                    status = 'delivered'
                except Obsolete:
                    status = 'withdrawn'
                except (OSError, ValueError, Problem, PinMismatch, PeerAnswer, http.client.HTTPException):
                    status = 'failed'  # Task 4 replaces this with spec §7's one outcome table
                with self.store.transaction() as db:
                    db.execute("UPDATE outbox SET status=?,attempts=attempts+1,next_attempt=? WHERE id=? AND status IN ('pending','failed')", (status,self.store.clock()+min(300,2**(row['attempts']+1)),row['id']))
                    status = db.execute('SELECT status FROM outbox WHERE id=?', (row['id'],)).fetchone()[0]
                result[status] += 1
            with self.store.transaction() as db:
                result['pending'] = db.execute("SELECT COUNT(*) FROM outbox WHERE status IN ('pending','failed')").fetchone()[0]
            return result
        finally:
            self._sync_lock.release()

    def _delivery_authority(self, db, row):
        """Resolve local controller and message correlation within action namespace."""
        action, rid = row['action'], row['resource_id']
        meta = json.loads(row['metadata'])
        message = None
        if action == 'room.reply':
            # rid belongs to the destination peer. Never query local resources.
            author = meta.get('actor')
            message = meta.get('message')
        elif action in ('layer.release','layer.withdraw'):
            resource = db.execute('SELECT owner_id FROM layers WHERE id=?', (rid,)).fetchone()
            author = resource['owner_id'] if resource else None
        elif action in ('room.roster','room.withdraw','room.message'):
            resource = db.execute('SELECT owner_id FROM rooms WHERE id=?', (rid,)).fetchone()
            author = resource['owner_id'] if resource else None
            if action == 'room.message':
                original_author = meta.get('author_id', '')
                if ':' in original_author:
                    # Remote author is preserved; the local origin owner controls
                    # distribution of the verified reply, not an ID suffix match.
                    message = db.execute('SELECT * FROM peer_messages WHERE id=? AND room_id=? AND author_id=?', (meta.get('message_id'),rid,original_author)).fetchone()
                else:
                    message = db.execute('SELECT * FROM messages WHERE id=? AND room_id=? AND author_id=?', (meta.get('message_id'),rid,original_author)).fetchone()
                    author = message['author_id'] if message else None
                if message is None:
                    author = None
        else:
            author = None
        if not db.execute('SELECT 1 FROM users WHERE id=?', (author,)).fetchone():
            return None, {}
        correlation = {'message_id':message['id'], 'client_message_id':message['client_message_id']} if message else {}
        return author, correlation

    def status(self, actor):
        # Materialize local events even with background sync disabled. This never
        # opens a connection, signs an envelope, or changes retry bytes.
        self.collect()
        with self.store.transaction() as db:
            result = []
            for row in db.execute('SELECT * FROM outbox ORDER BY event_seq,id').fetchall():
                author, correlation = self._delivery_authority(db, row)
                if author != actor:
                    continue
                contact = require(db.execute('SELECT remote_contacts.*,peers.paired FROM remote_contacts JOIN peers USING(peer_id) WHERE id=?', (row['contact_id'],)).fetchone())
                action, status = row['action'], row['status']
                resource = None
                if action.startswith('layer.'):
                    resource = db.execute('SELECT * FROM layers WHERE id=?', (row['resource_id'],)).fetchone()
                    title = json.loads(resource['draft'])['title'] if resource else 'Layer unavailable'
                    current = resource and resource['resource_version'] == row['revision']
                    if current:
                        snapshot = json.loads(db.execute('SELECT snapshot FROM layer_revisions WHERE layer_id=? AND revision=?', (row['resource_id'],resource['active_revision'])).fetchone()[0]) if resource['active_revision'] else {}
                        action = 'layer.release' if contact['id'] in snapshot.get('audience_users', []) else 'layer.withdraw'
                elif action == 'room.reply':
                    inbox = db.execute("SELECT revision,payload FROM inbox WHERE origin=? AND resource_id=? AND kind='room' AND recipient=?", (contact['peer_id'],row['resource_id'],actor)).fetchone()
                    title = json.loads(inbox['payload'])['title'] if inbox and inbox['payload'] else 'Received room'
                    current = inbox and inbox['payload'] and inbox['revision'] == row['revision']
                else:
                    resource = db.execute('SELECT * FROM rooms WHERE id=?', (row['resource_id'],)).fetchone()
                    title = resource['title'] if resource else 'Room unavailable'
                    current = resource and resource['epoch'] == row['revision']
                    if current and not db.execute('SELECT 1 FROM remote_room_members WHERE room_id=? AND contact_id=?', (row['resource_id'],contact['id'])).fetchone():
                        action = 'room.withdraw'
                if status in ('pending','failed') and (not current or not contact['paired']):
                    status = 'withdrawn'
                # Delivered/failed signed events describe the actual operation;
                # obsolete rows remain cancellations, never remote acknowledgments.
                if row['envelope']:
                    sent_action = parse(row['envelope'])['action']
                    if status in ('pending','failed') and sent_action != action:
                        status = 'withdrawn'
                    action = sent_action
                result.append({**{k:row[k] for k in ('id','resource_id','revision','contact_id','attempts','next_attempt')},
                               'action':action, 'status':status, 'resource_title':title,
                               'contact_name':contact['name'], 'peer_id':contact['peer_id'], **correlation})
            return result

    def retry(self, actor, key):
        with self.store.transaction() as db:
            row = require(db.execute('SELECT * FROM outbox WHERE id=?', (key,)).fetchone())
            if self._delivery_authority(db, row)[0] != actor:
                raise Problem(404, 'Not found')
            if row['status'] != 'failed':
                raise Problem(409, 'Only failed deliveries can be retried')
            db.execute("UPDATE outbox SET status='pending',attempts=0,next_attempt=0 WHERE id=?", (key,))
        return {'ok':True}

    def _cancel_replies(self, db, origin, rid, recipient, revision):
        """Apply recipient-specific cancellation in the tombstone transaction."""
        rows = db.execute("SELECT outbox.* FROM outbox JOIN remote_contacts ON contact_id=remote_contacts.id WHERE peer_id=? AND resource_id=? AND action='room.reply' AND revision<=? AND status IN ('pending','failed')", (origin,rid,revision)).fetchall()
        for row in rows:
            if self._delivery_authority(db, row)[0] == recipient:
                db.execute("UPDATE outbox SET status='withdrawn',next_attempt=0 WHERE id=?", (row['id'],))

    def receive(self, raw):
        value = parse(raw)
        if not isinstance(value.get('origin'),str) or not re.fullmatch(r'[0-9a-f]{64}',value['origin']):
            raise Problem(403, 'Unknown or unpaired peer')
        with self.store.transaction() as db:
            peer = db.execute('SELECT card FROM peers WHERE peer_id=? AND paired=1', (value.get('origin'),)).fetchone()
            if not peer:
                raise Problem(403, 'Unknown or unpaired peer')
            value = verify_envelope(value, json.loads(peer['card']), self.identity.peer_id)
            actor, origin = value['actor']['id'], value['origin']
            if not db.execute(f'SELECT 1 FROM remote_contacts WHERE peer_id=? AND user_id=? AND NOT EXISTS({HELD})', (origin,actor)).fetchone():
                raise Problem(403, 'Unknown remote participant')  # a held one too, until its own code is typed (SF3)
            for recipient in value['recipients']:
                if not db.execute('SELECT 1 FROM users WHERE id=?', (recipient,)).fetchone():
                    raise Problem(403, 'Unknown recipient')
            digest = hashlib.sha256(canonical(value)).hexdigest()
            old = db.execute('SELECT digest FROM receipts WHERE origin=? AND event_id=?', (origin,value['event_id'])).fetchone()
            if old:
                if old[0] != digest:
                    raise Problem(409, 'Event ID already used')
                return {'ok':True, 'duplicate':True}
            try:
                self._apply(db, value)
            except (TypeError, KeyError, AttributeError, ValueError):
                raise Problem(400, 'Invalid event payload') from None
            db.execute('INSERT INTO receipts VALUES(?,?,?,?)', (origin,value['event_id'],digest,self.store.clock()))
            return {'ok':True, 'duplicate':False}

    def _apply(self, db, e):
        action, p, origin, rid, revision = e['action'], e['payload'], e['origin'], e['resource_id'], e['revision']
        if action == 'room.reply':
            return self._reply(db, e)
        if action not in ('layer.release','layer.withdraw','room.roster','room.message','room.withdraw'):
            raise Problem(400, 'Unknown peer action')
        kind = 'layer' if action.startswith('layer.') else 'room'
        if action == 'layer.release':
            self._validate_layer(p)
        if action in ('room.roster','room.message'):
            text(p.get('title'), 'room title')
            members = p.get('members')
            if not isinstance(members, list) or len(members)>100 or any(not isinstance(m,dict) or set(m)!= {'peer','id'} for m in members):
                raise Problem(400, 'Invalid roster')
            for member in members:
                if not isinstance(member['peer'],str) or not re.fullmatch(r'[0-9a-f]{64}',member['peer']):
                    raise Problem(400, 'Invalid roster peer')
                if not isinstance(member['id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',member['id']):
                    raise Problem(400, 'Invalid roster participant')
            expected = [m['peer']+':'+m['id'] for m in members]
            if len(set(expected)) != len(expected):
                raise Problem(400, 'Duplicate roster participant')
            for field in ('created','last_activity'):
                if type(p.get(field)) not in (int,float) or not 0 <= p[field] <= 2**53:
                    raise Problem(400, 'Invalid room timestamp')
            if not linked_room_ok(p.get('linked_room_id'), origin):  # remote room fields: the origin's own earlier room, or nothing
                raise Problem(400, 'Invalid linked room')
            if p.get('member_ids') != expected or p.get('owner_id') != origin+':'+e['actor']['id'] or p['owner_id'] not in expected:
                raise Problem(403, 'Invalid room authority')
            if any({'peer':self.identity.peer_id,'id':r} not in members for r in e['recipients']):
                raise Problem(403, 'Recipient absent from roster')
            if action == 'room.message':
                m = p.get('message', {})
                text(m.get('id'), 'message ID', 100)
                text(m.get('body'), 'message', 20000)
                text(m.get('client_message_id'), 'client message ID', 100)
                if type(m.get('created')) not in (int,float) or not 0 <= m['created'] <= 2**53:
                    raise Problem(400, 'Invalid message timestamp')
                if m.get('epoch') != revision or m.get('author_id') not in expected or m.get('room_id') != rid:
                    raise Problem(403, 'Invalid message author or epoch')
        for recipient in e['recipients']:
            old = db.execute('SELECT * FROM inbox WHERE origin=? AND resource_id=? AND kind=? AND recipient=?', (origin,rid,kind,recipient)).fetchone()
            if old and old['actor'] != e['actor']['id']:
                raise Problem(403, 'Resource owner cannot change')
            if old and (old['revision'] > revision or (old['revision'] == revision and old['payload'] is None)):
                continue
            if kind == 'room' and old and old['payload'] and not action.endswith('withdraw'):
                prior_members = set(json.loads(old['payload'])['member_ids'])
                new_members = set(p['member_ids'])
                if not new_members <= prior_members or (revision == old['revision'] and new_members != prior_members):
                    raise Problem(409, 'New participants require a new linked room')
            payload = None if action.endswith('withdraw') else dict(p)
            if kind == 'layer' and old and old['revision'] == revision and old['payload'] is not None and encode(payload) != old['payload']:
                raise Problem(409, 'Revision already used')
            if kind == 'room' and payload is not None:
                history = json.loads(old['payload']).get('messages',[]) if old and old['payload'] else []
                message = payload.pop('message', None)
                if message and action == 'room.message':  # only a room.message is validated above
                    found = next((m for m in history if m['id']==message['id']),None)
                    if found and found != message:
                        raise Problem(409, 'Message ID already used')
                    if not found:
                        history.append(message)
                payload['messages'] = history
            db.execute('INSERT INTO inbox VALUES(?,?,?,?,?,?,?) ON CONFLICT(origin,resource_id,kind,recipient) DO UPDATE SET revision=excluded.revision,payload=excluded.payload', (origin,rid,kind,recipient,revision,e['actor']['id'],encode(payload) if payload is not None else None))
            if kind == 'room' and payload is not None:  # remote room fields: this station's own time, for the list's clamp
                db.execute('INSERT INTO inbox_received VALUES(?,?,?,?) ON CONFLICT(origin,resource_id,recipient) DO UPDATE SET received=excluded.received',
                           (origin, rid, recipient, self.store.clock()))
            if action == 'room.withdraw':
                self._cancel_replies(db, origin, rid, recipient, revision)

    def _validate_layer(self, p):
        if set(p) - {'title','body','attachment_ids','files'}:
            raise Problem(400, 'Unexpected release metadata')
        text(p.get('title'),'title')
        text(p.get('body'),'body',100000,empty=True)
        files = p.get('files',[])
        if not isinstance(files,list) or len(files)>100 or p.get('attachment_ids') != [f.get('id') for f in files]:
            raise Problem(400, 'Invalid attachments')
        total = 0
        for f in files:
            from .files import validate_file
            # Reuse the owned-upload validator without inserting remote files into
            # the local ownership table.
            row = validate_file(f.get('name'),f.get('media_type'),f.get('content_base64'))
            total += row['size']
            if row['size'] != f.get('size') or row['digest'] != f.get('digest') or total>4*1024*1024:
                raise Problem(400, 'Invalid attachment digest or size')

    def _reply(self, db, e):
        rid, actor, origin, p = e['resource_id'],e['actor']['id'],e['origin'],e['payload']
        room = require(db.execute('SELECT * FROM rooms WHERE id=?', (rid,)).fetchone())
        if e['recipients'] != [room['owner_id']] or room['epoch'] != e['revision']:
            raise Problem(403, 'Room recipient or epoch changed')
        contact = db.execute('SELECT id FROM remote_contacts WHERE peer_id=? AND user_id=?', (origin,actor)).fetchone()
        if not contact or not db.execute('SELECT 1 FROM remote_room_members WHERE room_id=? AND contact_id=?', (rid,contact[0])).fetchone():
            raise Problem(403, 'Room membership required')
        text(p.get('body'),'message',20000)
        text(p.get('client_message_id'),'client message ID',100)
        author = origin+':'+actor
        old = db.execute('SELECT * FROM peer_messages WHERE room_id=? AND author_id=? AND client_message_id=?', (rid,author,p['client_message_id'])).fetchone()
        if old:
            if old['body'] != p['body']:
                raise Problem(409, 'Message ID already used')
            return
        key = uid()
        db.execute('INSERT INTO peer_messages VALUES(?,?,?,?,?,?,?)', (key,rid,author,p['client_message_id'],p['body'],room['epoch'],self.store.clock()))
        self.store.emit(db,'chat.message',rid,room['epoch'],{'message_id':key,'author_id':author})
