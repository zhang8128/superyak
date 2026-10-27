"""Room moderators (docs/superpowers/specs/2026-10-27-room-moderators-design.md, M1 to M21): the owner of a room lets one
person in it, or one of his own ships in it, add and remove members. This module holds the act log's tables
(`member_changes`, `grant_origins`), and will hold making a moderate grant, choosing the grant an act spends, the
views and the make targets. members.py holds every membership change itself. The grant's shape, coverage and validity
are in grants.py."""
import json

from .common import REPLACED_ROOMS, Problem
from .grants import GRANTEE_IS_YOU, MODERATE_ACTIONS, _utc, _whole, is_moderate
from .ships import safe_line

MODERATE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS member_changes(id TEXT PRIMARY KEY, grant_id TEXT REFERENCES grants(id),
  actor_id TEXT REFERENCES users(id), member_id TEXT NOT NULL,
  change TEXT NOT NULL CHECK (change IN ('add','remove')), room_id TEXT NOT NULL REFERENCES rooms(id),
  new_room_id TEXT REFERENCES rooms(id), earlier_rooms INTEGER NOT NULL DEFAULT 0,
  claims_released INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS member_changes_by_grant ON member_changes(grant_id, created);
CREATE TABLE IF NOT EXISTS grant_origins(grant_id TEXT PRIMARY KEY REFERENCES grants(id),
  made_via TEXT NOT NULL CHECK (made_via IN ('browser','cli')));
'''

MODERATE_MAX_BUDGET = 50
MODERATE_DEFAULT_BUDGET = 10
MODERATE_DEFAULT_HOURS = 720
MODERATE_ROOM_NOT_YOURS = 'The room must be a room you are in'
MODERATE_NOT_OWNER = "Only the room's owner can let someone moderate it"
MODERATE_ROOM_REPLACED = 'The room was replaced by a newer linked room; name the current one'
MODERATE_REMOTE = "A room with a member on another station can't have moderators"
MODERATOR_REFUSED = 'A moderator is a person in this room or one of your own ships in it'
MODERATE_BUDGET_RANGE = f'budget is a whole number from 1 to {MODERATE_MAX_BUDGET}'
ACTIONS_SHAPE = 'actions is a list of add_member and remove_member, each at most once'
APPOINTED = '{owner} made {name} a moderator of this room, to {what}, until {when}.'
NOT_A_MODERATOR = "Only the room's owner or one of its moderators can change its members"
NO_ACTION = "Grant #{short} doesn't let you {verb} members"
WHAT = {('add_member', 'remove_member'): 'add and remove members', ('add_member',): 'add members',
        ('remove_member',): 'remove members'}


class Moderators:
    """The moderate grant's tables, making, choosing and views (built up task by task)."""

    def _record_origin(self, db, grant_id, made_via):
        """M20: where a grant was made, 'browser' or 'cli'. A grant from before merge 1 has no row and shows null."""
        db.execute('INSERT INTO grant_origins VALUES(?,?)', (grant_id, made_via))

    def _make_moderate(self, db, issuer_id, grantee, room, hours, budget, actions, made_via):
        """M1 to M3, M19: the owner of a room lets one person in it, or one of his own ships in it, add and remove members.
        Checked in the spec's order (the room, the grantee, hours, budget, actions), the first failure answers; then the
        grant is stored and signed, its origin recorded and the appointment announced, all in the caller's transaction.
        Returns the grant's id."""
        if (not isinstance(room, str) or ':' in room or self._breakout(db, room) is not None
                or db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (room, issuer_id)).fetchone() is None):
            raise Problem(404, MODERATE_ROOM_NOT_YOURS)
        if db.execute('SELECT owner_id FROM rooms WHERE id=?', (room,)).fetchone()['owner_id'] != issuer_id:
            raise Problem(403, MODERATE_NOT_OWNER)
        if db.execute(f'SELECT 1 WHERE ? IN ({REPLACED_ROOMS})', (room,)).fetchone():
            raise Problem(400, MODERATE_ROOM_REPLACED)
        if db.execute('SELECT 1 FROM remote_room_members WHERE room_id=?', (room,)).fetchone():
            raise Problem(400, MODERATE_REMOTE)
        if grantee == issuer_id:
            raise Problem(400, GRANTEE_IS_YOU)
        who = db.execute('SELECT u.kind, u.activation_pending, u.owner_id, u.name FROM users u JOIN room_members m ON m.user_id=u.id '
                         'WHERE m.room_id=? AND u.id=?', (room, grantee)).fetchone() if isinstance(grantee, str) else None
        if who is None or not ((who['kind'] == 'person' and not who['activation_pending'])
                               or (who['kind'] == 'ship' and who['owner_id'] == issuer_id)):
            raise Problem(400, MODERATOR_REFUSED)
        max_hours = self._grant_policy(db)['max_expiry_hours']
        hours = MODERATE_DEFAULT_HOURS if hours is None else hours
        if not _whole(hours, 1, max_hours):
            raise Problem(400, f'hours is a whole number from 1 to {max_hours}')
        budget = MODERATE_DEFAULT_BUDGET if budget is None else budget
        if not _whole(budget, 1, MODERATE_MAX_BUDGET):
            raise Problem(400, MODERATE_BUDGET_RANGE)
        actions = list(MODERATE_ACTIONS) if actions is None else actions
        if (not isinstance(actions, list) or not actions or any(not isinstance(a, str) or a not in MODERATE_ACTIONS for a in actions)
                or len(set(actions)) != len(actions)):
            raise Problem(400, ACTIONS_SHAPE)
        actions = tuple(a for a in MODERATE_ACTIONS if a in actions)
        key = self._insert_grant(db, issuer_id, grantee, [], [room], hours, budget, actions=actions)
        self._record_origin(db, key, made_via)
        owner = db.execute('SELECT name FROM users WHERE id=?', (issuer_id,)).fetchone()['name']
        self._post_as_system(db, room, f'moderator-{key}', APPOINTED.format(
            owner=safe_line(owner, 40), name=safe_line(who['name'], 40), what=WHAT[actions],
            when=_utc(db.execute('SELECT expires FROM grants WHERE id=?', (key,)).fetchone()['expires'])))
        return key

    def make_moderate_grant(self, actor, grantee, room, hours=None, budget=None, actions=None):
        """POST /api/grants/moderate (M1): the caller, a person, is the issuer; the grant is returned as G11 shows it."""
        with self.transaction() as db:
            self._person(db, actor)
            key = self._make_moderate(db, actor, grantee, room, hours, budget, actions, 'browser')
            return self._grant_view(db, actor, db.execute('SELECT * FROM grants WHERE id=?', (key,)).fetchone())

    def _acting_grant(self, db, actor, room_id, action, grant_id=None, self_removal=False):
        """Ruling 12: the moderate grant an act spends. Candidates are the caller's moderate grants covering the room,
        oldest first (created, then id), revoked ones included; a named grant_id keeps only that one, and one that isn't a
        candidate is answered as if the caller held none. The first valid candidate with the action is returned (any action
        for a moderator removing itself, which needs no budget). Otherwise 403 with the newest candidate's reason."""
        grants = [g for g in db.execute('SELECT * FROM grants WHERE grantee_id=? ORDER BY created, id', (actor,)).fetchall()
                  if is_moderate(g) and self._covered_room(db, g) == room_id and (grant_id is None or g['id'] == grant_id)]
        if not grants:
            raise Problem(403, NOT_A_MODERATOR)
        reason = None
        for grant in grants:
            valid, why = self._grant_validity(db, grant, budget=not self_removal)
            if valid and (self_removal or action in json.loads(grant['actions'])):
                return grant
            reason = why if not valid else NO_ACTION.format(short=grant['id'][:4], verb='add' if action == 'add_member' else 'remove')
        raise Problem(403, reason)
