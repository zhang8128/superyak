"""Owner trust (docs/superpowers/specs/2026-11-02-machine-trust-design.md, "The change" item 2): the admin's password lets
one remote person, a contact whose code was typed, vouch for their ships on their own peer. This module holds the
append-only `owner_trust` table and its companions, granting and renewing, and the two rules the pairing and
`connections()` share: `code_current` and `live_trust`."""
from datetime import datetime, timezone
import json

from .common import Problem, uid
from .identity import pairing_code
from .ships import safe_line

TRUST_DAYS = 90
OWNER_TRUST_STATEMENTS = (
    '''CREATE TABLE IF NOT EXISTS owner_trust(seq INTEGER PRIMARY KEY AUTOINCREMENT, grant_id TEXT NOT NULL,
  event TEXT NOT NULL CHECK(event IN ('grant','renew','revoke')), peer_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
  until REAL, by_id TEXT, at REAL NOT NULL, reason TEXT)''',
    '''CREATE TRIGGER IF NOT EXISTS owner_trust_no_update BEFORE UPDATE ON owner_trust
BEGIN SELECT RAISE(ABORT, 'owner_trust is append-only'); END''',
    '''CREATE TRIGGER IF NOT EXISTS owner_trust_no_delete BEFORE DELETE ON owner_trust
BEGIN SELECT RAISE(ABORT, 'owner_trust is append-only'); END''',
    '''CREATE TABLE IF NOT EXISTS trust_confirmations(id TEXT PRIMARY KEY, contact_id TEXT NOT NULL,
  grant_id TEXT NOT NULL, assertion TEXT NOT NULL, acting_ship_id TEXT NOT NULL, confirmed REAL NOT NULL,
  day TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS trust_cap_refusals(grant_id TEXT NOT NULL, day TEXT NOT NULL,
  refused INTEGER NOT NULL, PRIMARY KEY(grant_id, day))''',
    '''CREATE TABLE IF NOT EXISTS retired_peers(peer_id TEXT PRIMARY KEY, retired REAL NOT NULL, by_id TEXT)''',
)
OWNER_TRUST_SCHEMA = ';\n'.join(OWNER_TRUST_STATEMENTS) + ';'

DAYS_SHAPE = f'days is a whole number from 1 to {TRUST_DAYS}'
GRANT_TEXT = "ships owned by {name} on {peer} may be paired by this station's ships, until {date}"


def code_current(db, contact_id):
    """The rule `connections()` uses: a typed code confirms the contact only while it is still the code of the
    stored card with this contact's participant, and the peer is paired. A card that no longer validates has no code."""
    row = db.execute('SELECT remote_contacts.user_id,remote_contacts.name,peers.card,peers.paired,'
                     'pairing_confirmations.code FROM remote_contacts JOIN peers USING(peer_id) '
                     'JOIN pairing_confirmations ON pairing_confirmations.contact_id=remote_contacts.id '
                     'WHERE remote_contacts.id=?', (contact_id,)).fetchone()
    if row is None or not row['paired']:
        return False
    try:
        code = pairing_code({**json.loads(row['card']), 'participant': {'id': row['user_id'], 'name': row['name']}})
    except Problem:
        return False
    return row['code'] == code


def live_trust(db, peer_id, owner_user_id, now):
    """The unrevoked trust for this owner (a peer and a participant id, never an id alone) with its latest `until`
    still ahead of `now`, as a row with `grant_id` and `until`; None when there is none."""
    return db.execute(
        'SELECT grant_id, MAX(until) AS until FROM owner_trust WHERE peer_id=? AND owner_user_id=? '
        "AND grant_id NOT IN (SELECT grant_id FROM owner_trust WHERE event='revoke') "
        'GROUP BY grant_id HAVING MAX(until)>? ORDER BY MAX(until) DESC LIMIT 1', (peer_id, owner_user_id, now)).fetchone()


def _days(days):
    if type(days) is not int or not 1 <= days <= TRUST_DAYS:
        raise Problem(400, DAYS_SHAPE)
    return days


def _text(name, peer_id, until):
    date = datetime.fromtimestamp(until, timezone.utc).strftime('%Y-%m-%d')
    return GRANT_TEXT.format(name=safe_line(name), peer=peer_id[:12], date=date)


class OwnerTrust:
    def _trust_password(self, db_actor, password, source, public, device):
        with self.transaction() as db:
            self._admin(db, db_actor)
            username = db.execute('SELECT username FROM users WHERE id=?', (db_actor,)).fetchone()['username']
        if not self.check_password_attempt(username, password, source, public=public, device=device):
            raise Problem(401, 'Invalid password')

    def grant_owner_trust(self, actor, contact_id, *, days, password, source, public=True, device=None):
        """The admin's act, with their password: a remote person contact, whose code was typed and is still current,
        may have their ships paired by this station's ships for `days` whole days."""
        _days(days)
        self._trust_password(actor, password, source, public, device)
        with self.transaction() as db:
            self._admin(db, actor)
            now = self.clock()
            contact = db.execute('SELECT * FROM remote_contacts WHERE id=?', (contact_id,)).fetchone()
            if contact is None:
                raise Problem(404, 'No such contact')
            if db.execute('SELECT 1 FROM contact_holds WHERE contact_id=?', (contact_id,)).fetchone():
                raise Problem(409, 'That contact is held')
            if not code_current(db, contact_id):
                raise Problem(409, 'A code typed for that contact is needed first')
            if live_trust(db, contact['peer_id'], contact['user_id'], now):
                raise Problem(409, 'That owner is already trusted; renew it')
            grant_id, until = uid(), now + days * 86400
            db.execute('INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at) '
                       "VALUES (?,'grant',?,?,?,?,?)", (grant_id, contact['peer_id'], contact['user_id'], until, actor, now))
        return {'grant_id': grant_id, 'until': until, 'text': _text(contact['name'], contact['peer_id'], until)}

    def renew_owner_trust(self, actor, grant_id, *, days, password, source, public=True, device=None):
        """Extends an unrevoked trust to `days` whole days from now; it never shortens one."""
        _days(days)
        self._trust_password(actor, password, source, public, device)
        with self.transaction() as db:
            self._admin(db, actor)
            now = self.clock()
            rows = db.execute('SELECT event,peer_id,owner_user_id,until FROM owner_trust WHERE grant_id=?', (grant_id,)).fetchall()
            if not rows:
                raise Problem(404, 'No such owner trust')
            if any(r['event'] == 'revoke' for r in rows):
                raise Problem(409, 'That owner trust was revoked')
            peer_id, owner = rows[0]['peer_id'], rows[0]['owner_user_id']
            current = max(r['until'] for r in rows)
            until = now + days * 86400
            if until <= current:
                raise Problem(409, 'That owner trust already runs longer')
            db.execute('INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at) '
                       "VALUES (?,'renew',?,?,?,?,?)", (grant_id, peer_id, owner, until, actor, now))
            name = db.execute('SELECT name FROM remote_contacts WHERE peer_id=? AND user_id=?', (peer_id, owner)).fetchone()
        return {'grant_id': grant_id, 'until': until, 'text': _text(name['name'] if name else owner, peer_id, until)}
