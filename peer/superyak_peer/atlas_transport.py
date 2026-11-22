"""North-star test 5's transport (docs/superpowers/specs/2026-11-22-claim-crossing-transport-design.md, revision 4,
amendment 1): an Atlas sourced publication or source notice, sent by a ship to a ship on a paired peer, as the
federation actions atlas.publication and atlas.notice under envelope version 1.

The peer imports no Atlas code. It reads a package's known fields only, with string comparisons:
- every artifact's issuer is the sending peer's URI;
- a carried entry is the receiver's own or the sender's, and its claim and snapshot share one issuer;
- no artifact carries attestations;
- the policy grants the destination `retain` by its exact URI, holds no wildcard, and allows no `reshare`.

Atlas's own validation runs on the receiving side, on what `atlas-received` writes out."""
import hashlib
import json

from .common import Problem, encode, uid
from .identity import canonical

ATLAS_SCHEMA = '''
CREATE TABLE IF NOT EXISTS atlas_outgoing(outbox_id TEXT PRIMARY KEY REFERENCES outbox(id), digest TEXT NOT NULL,
    payload TEXT NOT NULL, envelope TEXT);
CREATE TABLE IF NOT EXISTS atlas_received(origin TEXT NOT NULL, recipient TEXT NOT NULL REFERENCES users(id),
    payload_digest TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('publication','notice')), actor TEXT NOT NULL,
    signing_key TEXT NOT NULL, event_id TEXT NOT NULL, envelope_digest TEXT NOT NULL, received_at REAL NOT NULL,
    envelope TEXT NOT NULL, PRIMARY KEY(origin, recipient, payload_digest));
'''

MAX_ATLAS = 1024 * 1024  # spec T1: a payload's canonical JSON, checked at the sender and again at the receiver
ORIGIN_QUOTA = 64 * 1024 * 1024  # spec T6 (A10): the envelopes one origin may have kept here
RECEIVE_BOUND = 2.0  # seconds an atlas receive waits for the gate and SQLite (the approving check's correction)
KINDS = {'publication': 'atlas.publication', 'notice': 'atlas.notice'}
ACTIONS = {action: kind for kind, action in KINDS.items()}
FIELD = {'publication': 'package', 'notice': 'notice'}
DUPLICATE = object()  # _apply's answer for a payload this recipient already holds from that origin (spec T6, R6)
UNLISTED = "That peer isn't listed for your lessons room: Atlas publications go only to peers listed there"
NO_CODE = 'That contact has no current typed code: Atlas publications need one'


def peer_uri(peer_id):
    """A real issuer's URI (spec T3): the issuing peer's 64-hex id under urn:superyak:peer."""
    return f'urn:superyak:peer:{peer_id}'


def _shape(kind, payload):
    """The payload's one key and its size (spec T1). A malformed payload is a 400 in words of its own."""
    if not isinstance(payload, dict) or set(payload) != {FIELD[kind]} or not isinstance(payload[FIELD[kind]], dict):
        raise Problem(400, 'Invalid atlas payload')
    if len(canonical(payload)) > MAX_ATLAS:
        raise Problem(400, 'An atlas payload is at most 1 MiB')
    return payload[FIELD[kind]]


def _artifacts(kind, body):
    """A publication's own artifacts and its carried entries, or a notice alone."""
    if kind == 'notice':
        return [body], []
    claims, carried = body.get('claims'), body.get('carried')
    if not isinstance(claims, list) or not isinstance(carried, list):
        raise Problem(400, 'Invalid atlas payload')
    own = [body.get('descriptor'), body.get('snapshot'), body.get('policy'), *claims]
    if any(not isinstance(a, dict) for a in own) or any(
            not isinstance(e, dict) or not isinstance(e.get('claim'), dict) or not isinstance(e.get('snapshot'), dict)
            for e in carried):
        raise Problem(400, 'Invalid atlas payload')
    return own, carried


def check_issuers(kind, body, issuer, other, *, receiving):
    """Spec T3: `issuer` is the delivering peer's URI and `other` the far side's. Every own artifact is the issuer's, and
    a carried entry is one side's, with its claim and snapshot issued alike. No artifact holds attestations (A8)."""
    own, carried = _artifacts(kind, body)
    if any(a.get('issuer') != issuer for a in own):
        if kind == 'notice':
            raise Problem(400, 'A notice must be issued by the peer that delivered it' if receiving
                          else 'A notice you send must be issued by this peer')
        raise Problem(400, "A publication's artifacts must all be issued by the peer that delivered it" if receiving
                      else 'A package you send must be issued by this peer')
    for entry in carried:
        if entry['claim'].get('issuer') != entry['snapshot'].get('issuer'):
            raise Problem(400, "A carried claim's issuer isn't its snapshot's issuer")
        if entry['claim'].get('issuer') not in (issuer, other):
            raise Problem(400, "A carried claim must be the receiver's own or the sender's" if receiving
                          else "A carried claim must be this peer's own or the destination's")
    for artifact in [*own, *(part for e in carried for part in (e['claim'], e['snapshot']))]:
        if artifact.get('attestations') not in (None, []):
            raise Problem(400, 'This version takes no attestations')


def check_policy(body, destination):
    """Spec T2 (R5, N4), at the sender: an allow rule grants `retain` to the destination's exact URI, and no allow rule
    holds a `*` in any selector or names `reshare`. authorize() matches a trailing `*` as a prefix, so `actions: ["*"]`
    would grant reshare."""
    policy = body.get('policy') or {}
    rules = (policy.get('payload') or {}).get('rules')
    if not isinstance(rules, list) or any(not isinstance(r, dict) for r in rules):
        raise Problem(400, 'Invalid atlas payload')
    allows = [r for r in rules if r.get('effect') == 'allow']
    for rule in allows:
        for selector in rule.values():
            if isinstance(selector, list) and any(isinstance(v, str) and '*' in v for v in selector):
                raise Problem(400, "The package's policy may hold no wildcard")
    if any('reshare' in (r.get('actions') or []) for r in allows):
        raise Problem(400, "The package's policy may not allow reshare")
    if not any('retain' in (r.get('actions') or []) and destination in (r.get('publishers') or []) for r in allows):
        raise Problem(400, "The package's policy must allow the destination to retain it, by its exact name")


def listed(db, peer_id):
    """Spec T2 (RG1, A1): a peer the lessons chain lists. On the station, `lessons_peers`; on another peer, the origin
    of its recorded lessons room, read from the room key even when the chain itself is gone."""
    if db.execute('SELECT 1 FROM lessons_peers WHERE peer_id=?', (peer_id,)).fetchone():
        return True
    record = db.execute('SELECT room_key FROM lessons_room WHERE id=1').fetchone()
    return record is not None and record['room_key'].startswith(peer_id + ':')


def contact_words(db, contact_id):
    """Why a contact can't take an atlas row now, or None (spec T2, checked at queueing and again at every prepare)."""
    from .federation import HELD
    from .owner_trust import code_current
    contact = db.execute(f'SELECT remote_contacts.peer_id, peers.paired, EXISTS({HELD}) AS held FROM remote_contacts '
                         'JOIN peers USING(peer_id) WHERE remote_contacts.id=?', (contact_id,)).fetchone()
    if contact is None or not contact['paired'] or contact['held']:
        return 'That contact is held or its peer is unpaired'
    if not code_current(db, contact_id):
        return NO_CODE
    if not listed(db, contact['peer_id']):
        return UNLISTED
    return None


class AtlasTransport:
    def atlas_send(self, ship_id, contact_id, kind, body):
        """Queue one publication or notice from a ship to one contact (spec T2, T7). Nothing crosses until a delivery
        pass prepares the row, and prepare checks the contact again."""
        if kind not in KINDS:
            raise Problem(400, 'Kind is publication or notice')
        payload = {FIELD[kind]: body}
        _shape(kind, payload)
        digest = hashlib.sha256(canonical(payload)).hexdigest()
        with self.transaction() as db:
            ship = db.execute('SELECT id, kind, owner_id FROM users WHERE id=?', (ship_id,)).fetchone()
            if ship is None or ship['kind'] != 'ship':
                raise Problem(403, 'Only a ship sends Atlas publications')
            owner = ship['owner_id'] and db.execute('SELECT kind, is_admin FROM users WHERE id=?',
                                                    (ship['owner_id'],)).fetchone()
            if not owner or owner['kind'] != 'person' or not owner['is_admin']:
                raise Problem(403, 'A ship with no owner who is an admin here sends no Atlas publications')
            contact = db.execute('SELECT id, peer_id FROM remote_contacts WHERE id=?', (contact_id,)).fetchone()
            if contact is None:
                raise Problem(404, 'Not found')
            words = contact_words(db, contact_id)
            if words:
                raise Problem(409, words)
            own, far = peer_uri(self._own_peer_id(db)), peer_uri(contact['peer_id'])
            check_issuers(kind, body, own, far, receiving=False)
            if kind == 'publication':
                check_policy(body, far)
            if db.execute("SELECT 1 FROM outbox WHERE contact_id=? AND action=? AND resource_id=? "
                          "AND status IN ('pending','delivered','failed')", (contact_id, KINDS[kind], digest)).fetchone():
                raise Problem(409, 'Already sent to that contact')
            seq = self.emit(db, 'atlas.sent', digest, 1)
            key = uid()
            meta = {'ship': ship_id, 'digest': digest, 'kind': kind, 'title': _title(kind, body)}
            db.execute('INSERT INTO outbox(id,event_seq,contact_id,resource_id,revision,action,metadata,status) '
                       'VALUES(?,?,?,?,?,?,?,?)', (key, seq, contact_id, digest, 1, KINDS[kind], encode(meta), 'pending'))
            db.execute('INSERT INTO atlas_outgoing(outbox_id, digest, payload) VALUES(?,?,?)',
                       (key, digest, canonical(payload).decode()))
            return {'id': key, 'digest': digest, 'state': 'pending'}


def _title(kind, body):
    """The collection's title for status lines, when the package names one as text; never more than 200 characters."""
    model = ((body.get('snapshot') or {}).get('payload') or {}).get('model') if kind == 'publication' else None
    title = model.get('title') if isinstance(model, dict) else None
    return title[:200] if isinstance(title, str) else ''


def prepare(fed, db, row, contact):
    """The atlas branch of Federation._prepare_in (spec T7): the contact's rules again, then the exact signed envelope,
    kept in atlas_outgoing, not in outbox.envelope (third check, advisory 2). Returns None when the row is obsolete."""
    if contact_words(db, row['contact_id']):
        return None
    out = db.execute('SELECT payload, envelope FROM atlas_outgoing WHERE outbox_id=?', (row['id'],)).fetchone()
    if out is None:
        return None
    if out['envelope']:
        return out['envelope'].encode()
    meta = json.loads(row['metadata'])
    envelope = fed.identity.envelope(destination=contact['peer_id'], actor=meta['ship'], resource_id=row['resource_id'],
                                     revision=1, action=row['action'], recipients=[contact['user_id']],
                                     payload=json.loads(out['payload']), event_id=row['id'])
    raw = canonical(envelope)
    db.execute('UPDATE atlas_outgoing SET envelope=? WHERE outbox_id=?', (raw.decode(), row['id']))
    return raw


def apply(fed, db, e):
    """The atlas branch of Federation._apply (spec T3, T6): refuse with a 400 in words of its own, or keep the payload
    with the signed envelope and who delivered it. Returns DUPLICATE for a payload this recipient already holds."""
    kind = ACTIONS[e['action']]
    body = _shape(kind, e['payload'])
    if len(e['recipients']) != 1:
        raise Problem(400, 'An atlas payload goes to one ship')
    recipient = db.execute('SELECT kind FROM users WHERE id=?', (e['recipients'][0],)).fetchone()
    if recipient is None or recipient['kind'] != 'ship':
        raise Problem(400, 'Atlas publications go only to a ship')
    origin = e['origin']
    check_issuers(kind, body, peer_uri(origin), peer_uri(fed.identity.peer_id), receiving=True)
    card = json.loads(db.execute('SELECT card FROM peers WHERE peer_id=?', (origin,)).fetchone()['card'])
    raw = canonical(e)
    digest = hashlib.sha256(canonical(e['payload'])).hexdigest()
    if db.execute('SELECT 1 FROM atlas_received WHERE origin=? AND recipient=? AND payload_digest=?',
                  (origin, e['recipients'][0], digest)).fetchone():
        return DUPLICATE
    held = db.execute('SELECT COALESCE(SUM(length(envelope)), 0) FROM atlas_received WHERE origin=?', (origin,)).fetchone()[0]
    if held + len(raw) > ORIGIN_QUOTA:
        raise Problem(400, 'This peer holds 64 MiB from that peer already')
    db.execute('INSERT INTO atlas_received VALUES(?,?,?,?,?,?,?,?,?,?)',
               (origin, e['recipients'][0], digest, kind, e['actor']['id'], card['signing_key'],
                e['event_id'], hashlib.sha256(raw).hexdigest(), fed.store.clock(), raw.decode()))
    return None
