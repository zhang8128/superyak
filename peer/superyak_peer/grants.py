"""Grants (spec A step 3, merge 3b; docs/superpowers/specs/2026-10-15-grants-step3-design.md section 2, G7-G14): a
person lets another person direct some of his own ships, in some rooms, for some hours, with a daily budget of builds.
This module holds the tables, the policy, validity, making, revoking and reading. The station's signatures over grants
and revocations live in signatures.py, beside the revisions'. Merge 3c spends grants from tickets.py."""
from datetime import datetime, timezone
import json
from .common import encode, uid
from .ships import safe_line

GRANT_SCHEMA = '''
CREATE TABLE IF NOT EXISTS grants(id TEXT PRIMARY KEY, issuer_id TEXT NOT NULL REFERENCES users(id), grantee_id TEXT NOT NULL REFERENCES users(id), actions TEXT NOT NULL, targets TEXT NOT NULL, rooms TEXT NOT NULL, expires REAL NOT NULL, budget INTEGER NOT NULL, depth INTEGER NOT NULL, confirm TEXT NOT NULL, parent_id TEXT REFERENCES grants(id), charter_layer_id TEXT, charter_revision INTEGER, follow INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, revoked REAL, revoked_by TEXT REFERENCES users(id), revoke_reason TEXT, signature TEXT NOT NULL, revocation_signature TEXT);
CREATE TABLE IF NOT EXISTS budget_uses(grant_id TEXT NOT NULL REFERENCES grants(id), ticket_id TEXT NOT NULL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS budget_uses_by_grant ON budget_uses(grant_id, created);
'''
HOUR, DAY = 3600, 86400


def short_id(grant_id):
    """G9: '#' and the first 4 characters of the id, as in spec A's footers."""
    return '#' + grant_id[:4]


def _utc(moment):
    return datetime.fromtimestamp(moment, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


class Grants:
    def _grant_policy(self, db):
        """G7: spec A's no-charter defaults. Every check reads the policy through this one function, so step 4 puts the
        charter behind it and validity doesn't change. `grantees` None is the unrestricted set."""
        return {'max_depth': 3, 'max_expiry_hours': 720, 'agent_grant_default_hours': 24, 'builds_per_ship_per_day': 20,
                'delegable': ['direct'], 'grantees': None}

    def _insert_grant(self, db, issuer_id, grantee_id, targets, rooms, hours, budget):
        """A root `direct` grant, stored and signed in the caller's transaction; the caller has checked every field (G8).
        Step 3 fixes actions, depth and confirm, and leaves parent_id, the charter columns and follow empty. The row holds
        an empty signature only until _sign_grant fills it, in this transaction (G12). Returns the grant's id."""
        key, now = uid(), self.clock()
        db.execute('INSERT INTO grants(id,issuer_id,grantee_id,actions,targets,rooms,expires,budget,depth,confirm,created,'
                   "signature) VALUES(?,?,?,?,?,?,?,?,0,'none',?,'')",
                   (key, issuer_id, grantee_id, encode(['direct']), encode(targets), encode(rooms), now + hours * HOUR,
                    budget, now))
        self._sign_grant(db, key)
        return key

    def _grant_chain(self, db, grant):
        """G9: the links from this grant up to its root, this grant first. In step 3 every grant is its own root; step 5
        adds parents. A seen set ends a cycle made by hand."""
        chain, seen = [grant], {grant['id']}
        while chain[-1]['parent_id'] is not None:
            parent = db.execute('SELECT * FROM grants WHERE id=?', (chain[-1]['parent_id'],)).fetchone()
            if parent is None or parent['id'] in seen:
                break
            chain.append(parent)
            seen.add(parent['id'])
        return chain

    def _budget_used(self, db, grant_id, now):
        """Builds charged to a grant in the last 24 hours. A use exactly 24 hours old no longer counts (G9, test 6)."""
        return db.execute('SELECT count(*) FROM budget_uses WHERE grant_id=? AND created>?',
                          (grant_id, now - DAY)).fetchone()[0]

    def _grant_validity(self, db, grant):
        """G9: (True, None), or (False, the reason of the first check that fails). Each link, from the grant up to its
        root, is checked in the spec's order: 1 revoked, 2 expired, 3 the policy in force now (lifetime, chain length,
        grantee set), 4 budget, 5 the root's issuer still owns every target. Names are the station's own, through
        safe_line."""
        now, policy = self.clock(), self._grant_policy(db)
        chain = self._grant_chain(db, grant)
        root = chain[-1]
        for link in chain:
            short = short_id(link['id'])
            if link['revoked'] is not None:
                by = db.execute('SELECT name FROM users WHERE id=?', (link['revoked_by'],)).fetchone() if link['revoked_by'] else None
                return False, f'Grant {short} was revoked' + (f' by {safe_line(by["name"])}' if by else '')
            if now >= link['expires']:
                return False, f'Grant {short} expired {_utc(link["expires"])}'
            if link['expires'] - link['created'] > policy['max_expiry_hours'] * HOUR:
                return False, f'Grant {short} lasts longer than the station now allows'
            if len(chain) > policy['max_depth'] or (policy['grantees'] is not None and link['grantee_id'] not in policy['grantees']):
                return False, f"Grant {short} is no longer allowed by the station's policy"
            if self._budget_used(db, link['id'], now) >= link['budget']:
                builds = f'{link["budget"]} build' + ('' if link['budget'] == 1 else 's')
                return False, f'Grant {short} has used its {builds} for the last 24 hours'
            for ship_id in json.loads(link['targets']):
                ship = db.execute('SELECT name, owner_id FROM users WHERE id=?', (ship_id,)).fetchone()
                if ship is None or ship['owner_id'] != root['issuer_id']:
                    issuer = db.execute('SELECT name FROM users WHERE id=?', (root['issuer_id'],)).fetchone()
                    return False, f'{safe_line(issuer["name"])} no longer owns {safe_line(ship["name"]) if ship else "a ship that is gone"}'
        return True, None
