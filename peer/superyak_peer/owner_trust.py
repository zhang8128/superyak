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
EXPECT_MAX = 10_000
OWNER_TRUST_STATEMENTS = (
    '''CREATE TABLE IF NOT EXISTS owner_trust(seq INTEGER PRIMARY KEY AUTOINCREMENT, grant_id TEXT NOT NULL,
  event TEXT NOT NULL CHECK(event IN ('grant','renew','revoke')), peer_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
  until REAL, by_id TEXT, at REAL NOT NULL, reason TEXT, expect INTEGER)''',
    '''CREATE TRIGGER IF NOT EXISTS owner_trust_no_update BEFORE UPDATE ON owner_trust
BEGIN SELECT RAISE(ABORT, 'owner_trust is append-only'); END''',
    '''CREATE TRIGGER IF NOT EXISTS owner_trust_no_delete BEFORE DELETE ON owner_trust
BEGIN SELECT RAISE(ABORT, 'owner_trust is append-only'); END''',
    '''CREATE TRIGGER IF NOT EXISTS owner_trust_no_replace BEFORE INSERT ON owner_trust
WHEN EXISTS (SELECT 1 FROM owner_trust WHERE seq=NEW.seq)
BEGIN SELECT RAISE(ABORT, 'owner_trust is append-only'); END''',
    '''CREATE TABLE IF NOT EXISTS trust_confirmations(id TEXT PRIMARY KEY, contact_id TEXT NOT NULL,
  grant_id TEXT NOT NULL, assertion TEXT NOT NULL, acting_ship_id TEXT NOT NULL, confirmed REAL NOT NULL,
  day TEXT NOT NULL, window_seq INTEGER NOT NULL)''',
    # The cap's count and contact_labels' latest confirmation per contact, by index rather than by scan (ruling, Task 3).
    'CREATE INDEX IF NOT EXISTS trust_confirmations_contact ON trust_confirmations(contact_id, confirmed)',
    'CREATE INDEX IF NOT EXISTS trust_confirmations_grant_day ON trust_confirmations(grant_id, day)',
    # trust_window's count of one window, by index.
    'CREATE INDEX IF NOT EXISTS trust_confirmations_window ON trust_confirmations(window_seq)',
    '''CREATE TABLE IF NOT EXISTS trust_cap_refusals(grant_id TEXT NOT NULL, day TEXT NOT NULL,
  refused INTEGER NOT NULL, PRIMARY KEY(grant_id, day))''',
    '''CREATE TABLE IF NOT EXISTS retired_peers(peer_id TEXT PRIMARY KEY, retired REAL NOT NULL, by_id TEXT)''',
    # Ruling (after Tardis's plan review): remote_contacts.name stays the card's participant name, so a typed-code pair
    # that rewrites it can't make a ship read as a person. A contact with any trust confirmation, revoked or held too,
    # reads "ship of <owner>: <name>", its owner taken from its latest confirmation's grant as (peer, participant id),
    # never an id alone, and that owner's name read live. Every other contact reads as its own name.
    '''CREATE VIEW IF NOT EXISTS contact_labels(id, label) AS SELECT c.id, CASE WHEN t.grant_id IS NULL THEN c.name
  ELSE 'ship of ' || COALESCE((SELECT o.name FROM owner_trust g JOIN remote_contacts o ON o.peer_id=g.peer_id
    AND o.user_id=g.owner_user_id WHERE g.grant_id=t.grant_id ORDER BY g.seq LIMIT 1), 'an unknown owner') || ': ' || c.name
  END FROM remote_contacts c LEFT JOIN trust_confirmations t ON t.rowid=(SELECT rowid FROM trust_confirmations
    WHERE contact_id=c.id ORDER BY confirmed DESC, rowid DESC LIMIT 1)''',
)
OWNER_TRUST_SCHEMA = ';\n'.join(OWNER_TRUST_STATEMENTS) + ';'

DAYS_SHAPE = f'days is a whole number from 1 to {TRUST_DAYS}'
EXPECT_SHAPE = f'expect is a whole number from 1 to {EXPECT_MAX}'
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


# Latest by the wall-clock `confirmed`: a clock stepped back fails closed, the ship held again at the next settle.
LATEST = 'ORDER BY confirmed DESC, rowid DESC LIMIT 1'  # a contact's latest trust confirmation, as contact_labels picks it
# The ships not held, each with the grant of its latest confirmation.
UNHELD_SHIPS = ('SELECT c.id, c.peer_id, c.user_id, t.grant_id FROM remote_contacts c JOIN trust_confirmations t ON '
                f't.rowid=(SELECT rowid FROM trust_confirmations WHERE contact_id=c.id {LATEST}) '
                'WHERE c.id NOT IN (SELECT contact_id FROM contact_holds)')
REVOKED = "SELECT grant_id FROM owner_trust WHERE event='revoke'"


def latest_grant(db, contact_id):
    """The grant of this contact's latest trust confirmation, or None for a contact no trust made."""
    row = db.execute(f'SELECT grant_id FROM trust_confirmations WHERE contact_id=? {LATEST}', (contact_id,)).fetchone()
    return row[0] if row else None


def ships_to_hold(db, grant_ids=None):
    """The ships a revocation holds: those not held whose latest confirmation's grant is revoked (`grant_ids` None) or
    one of `grant_ids`, less any whose own typed code is current. A code typed for that one account is a person's act
    and the stronger proof, so it stands when a trust ends (coordinator's ruling on Task 4, after the spec's "What a
    code proves")."""
    if grant_ids is None:
        rows = db.execute(f'{UNHELD_SHIPS} AND t.grant_id IN ({REVOKED})')
    else:
        grant_ids = list(grant_ids)
        if not grant_ids:
            return []
        rows = db.execute(f"{UNHELD_SHIPS} AND t.grant_id IN ({','.join('?' * len(grant_ids))})", grant_ids)
    return [ship for ship in rows.fetchall() if not code_current(db, ship['id'])]


def hold_contact(db, contact, now):
    """Holds one contact as Federation.unpair holds each of a peer's (backups._hold_like_replaced, for one): its
    confirmation gone, its pending and failed outbox rows withdrawn, and the received payloads it authored cleared.
    A contact already held keeps the date of its first hold."""
    db.execute('INSERT OR IGNORE INTO contact_holds VALUES(?, ?)', (contact['id'], now))
    db.execute('DELETE FROM pairing_confirmations WHERE contact_id=?', (contact['id'],))
    db.execute("UPDATE outbox SET status='withdrawn' WHERE contact_id=? AND status IN ('pending','failed')", (contact['id'],))
    db.execute('UPDATE inbox SET payload=NULL WHERE origin=? AND actor=? AND payload IS NOT NULL',
               (contact['peer_id'], contact['user_id']))


def _owner_failed(db, peer_id, owner_user_id):
    """Whether a trust's owner can no longer vouch: its peer retired, its contact gone or held, or its typed code no
    longer current (which `code_current` also finds for a peer that is unpaired or missing)."""
    if db.execute('SELECT 1 FROM retired_peers WHERE peer_id=?', (peer_id,)).fetchone():
        return True
    owner = db.execute('SELECT id FROM remote_contacts WHERE peer_id=? AND user_id=?', (peer_id, owner_user_id)).fetchone()
    if owner is None or db.execute('SELECT 1 FROM contact_holds WHERE contact_id=?', (owner['id'],)).fetchone():
        return True
    return not code_current(db, owner['id'])


def settle_owner_trust(db, now):
    """The one invariant (spec "The change" items 3 and 6, S10, N13), run inside the caller's transaction by unpair,
    pair, a revoke and a restore. Every unrevoked trust, expired ones too, whose owner has failed gets a revocation
    dated `now` with reason 'owner held', so every hold of an owner has a date; then every ship whose latest
    confirmation names a revoked trust, and whose own typed code isn't current, is held. Returns the grant ids it
    revoked, in grant order."""
    revoked = []
    while True:  # until a pass ends nothing; a held ship is never an owner (an owner has no trust confirmation)
        grants = db.execute(f"SELECT grant_id, peer_id, owner_user_id FROM owner_trust WHERE event='grant' "
                            f'AND grant_id NOT IN ({REVOKED}) ORDER BY seq').fetchall()
        ended = [g for g in grants if _owner_failed(db, g['peer_id'], g['owner_user_id'])]
        for g in ended:
            db.execute("INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at,reason) "
                       "VALUES (?,'revoke',?,?,NULL,NULL,?,'owner held')", (g['grant_id'], g['peer_id'], g['owner_user_id'], now))
        revoked += [g['grant_id'] for g in ended]
        for ship in ships_to_hold(db):
            hold_contact(db, ship, now)
        if not ended:
            return revoked


def _days(days):
    if type(days) is not int or not 1 <= days <= TRUST_DAYS:
        raise Problem(400, DAYS_SHAPE)
    return days


def _expect(expect):
    if type(expect) is not int or not 1 <= expect <= EXPECT_MAX:
        raise Problem(400, EXPECT_SHAPE)
    return expect


def trust_window(db, grant_id):
    """`(window_seq, expect, paired)` of the grant's latest grant-or-renewal row: that row's seq, the count its person
    expected, and the trust_confirmations rows that paired under it (spec item 4a). The trust is paused when
    paired >= expect."""
    row = db.execute("SELECT seq, expect FROM owner_trust WHERE grant_id=? AND event IN ('grant','renew') "
                     'ORDER BY seq DESC LIMIT 1', (grant_id,)).fetchone()
    if row is None:
        raise Problem(404, 'No such owner trust')
    paired = db.execute('SELECT COUNT(*) FROM trust_confirmations WHERE window_seq=?', (row['seq'],)).fetchone()[0]
    return row['seq'], row['expect'], paired


def _text(name, peer_id, until):
    date = datetime.fromtimestamp(until, timezone.utc).strftime('%Y-%m-%d')
    return GRANT_TEXT.format(name=safe_line(name), peer=peer_id[:12], date=date)


def owner_eligible(db, contact):
    """The refusals grant and renew share: the owner is a remote person contact, not held, not made by a trust, whose
    typed code is still current."""
    if contact is None:
        raise Problem(404, 'No such contact')
    if db.execute('SELECT 1 FROM contact_holds WHERE contact_id=?', (contact['id'],)).fetchone():
        raise Problem(409, 'That contact is held')
    if db.execute('SELECT 1 FROM trust_confirmations WHERE contact_id=?', (contact['id'],)).fetchone():
        raise Problem(409, 'That contact was paired by an owner trust, not by a typed code')
    if not code_current(db, contact['id']):
        raise Problem(409, 'A code typed for that contact is needed first')


class OwnerTrust:
    def _trust_password(self, actor, password, source, public, device):
        with self.transaction() as db:
            self._admin(db, actor)
            username = db.execute('SELECT username FROM users WHERE id=?', (actor,)).fetchone()['username']
        if not self.check_password_attempt(username, password, source, public=public, device=device):
            raise Problem(401, 'Invalid password')

    def grant_owner_trust(self, actor, contact_id, *, days, expect, password, source, public=True, device=None):
        """The admin's act, with their password: a remote person contact, whose code was typed and is still current,
        may have their ships paired by this station's ships for `days` whole days, up to `expect` of them before the
        trust pauses (spec item 4a)."""
        _days(days)
        _expect(expect)
        self._trust_password(actor, password, source, public, device)
        with self.transaction() as db:
            self._admin(db, actor)
            now = self.clock()
            contact = db.execute('SELECT * FROM remote_contacts WHERE id=?', (contact_id,)).fetchone()
            owner_eligible(db, contact)
            if live_trust(db, contact['peer_id'], contact['user_id'], now):
                raise Problem(409, 'That owner is already trusted; renew it')
            grant_id, until = uid(), now + days * 86400
            db.execute('INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at,expect) '
                       "VALUES (?,'grant',?,?,?,?,?,?)", (grant_id, contact['peer_id'], contact['user_id'], until, actor, now, expect))
        return {'grant_id': grant_id, 'until': until, 'text': _text(contact['name'], contact['peer_id'], until)}

    def renew_owner_trust(self, actor, grant_id, *, days, expect, password, source, public=True, device=None):
        """Extends an unrevoked trust to `days` whole days from now; it never shortens one."""
        _days(days)
        _expect(expect)
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
            contact = db.execute('SELECT * FROM remote_contacts WHERE peer_id=? AND user_id=?', (peer_id, owner)).fetchone()
            owner_eligible(db, contact)
            latest = db.execute("SELECT grant_id FROM owner_trust WHERE peer_id=? AND owner_user_id=? AND event='grant' "
                                'ORDER BY seq DESC LIMIT 1', (peer_id, owner)).fetchone()
            if latest['grant_id'] != grant_id:
                raise Problem(409, "That is not this owner's latest trust; grant a new one")
            live = live_trust(db, peer_id, owner, now)
            if live and live['grant_id'] != grant_id:
                raise Problem(409, 'That owner is already trusted under another grant')
            current = max(r['until'] for r in rows)
            until = now + days * 86400
            if until <= current:
                raise Problem(409, 'That owner trust already runs longer')
            db.execute('INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at,expect) '
                       "VALUES (?,'renew',?,?,?,?,?,?)", (grant_id, peer_id, owner, until, actor, now, expect))
        return {'grant_id': grant_id, 'until': until, 'text': _text(contact['name'], peer_id, until)}

    def revoke_owner_trust(self, actor, grant_id):
        """The admin's act (spec "The change" item 6): ends the trust at once, so this grant, expired or not, and every
        other unrevoked grant of the same owner (peer, participant id), whose ships would otherwise stay paired (review
        ruling). It holds every ship whose latest confirmation one of them made and that has no current typed code of
        its own (ships_to_hold), as settle_owner_trust holds them; `held` counts them. It only takes power away, so it
        needs no password. A grant revoked already is refused, so it never gains a second revocation."""
        with self.transaction() as db:
            self._admin(db, actor)
            now = self.clock()
            rows = db.execute('SELECT event, peer_id, owner_user_id FROM owner_trust WHERE grant_id=? ORDER BY seq',
                              (grant_id,)).fetchall()
            if not rows:
                raise Problem(404, 'No such owner trust')
            if any(r['event'] == 'revoke' for r in rows):
                raise Problem(409, 'That owner trust was revoked already')
            peer_id, owner = rows[0]['peer_id'], rows[0]['owner_user_id']
            grants = [r[0] for r in db.execute("SELECT grant_id FROM owner_trust WHERE peer_id=? AND owner_user_id=? "
                                               f"AND event='grant' AND grant_id NOT IN ({REVOKED}) ORDER BY seq",
                                               (peer_id, owner))]
            ships = ships_to_hold(db, grants)
            db.executemany("INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at,reason) "
                           "VALUES (?,'revoke',?,?,NULL,?,?,'revoked')", [(g, peer_id, owner, actor, now) for g in grants])
            settle_owner_trust(db, now)
        return {'grant_id': grant_id, 'held': len(ships)}
