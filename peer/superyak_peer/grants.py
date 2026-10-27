"""Grants (spec A step 3, merge 3b; docs/superpowers/specs/2026-10-15-grants-step3-design.md section 2, G7-G14): a
person lets another person direct some of his own ships, in some rooms, for some hours, with a daily budget of builds.
This module holds the tables, the policy, validity, making, revoking and reading. The station's signatures over grants
and revocations live in signatures.py, beside the revisions'. Merge 3c spends grants from tickets.py."""
from datetime import datetime, timezone
import json
from .common import REPLACED_ROOMS, Problem, encode, uid
from .ships import safe_line

GRANT_SCHEMA = '''
CREATE TABLE IF NOT EXISTS grants(id TEXT PRIMARY KEY, issuer_id TEXT NOT NULL REFERENCES users(id), grantee_id TEXT NOT NULL REFERENCES users(id), actions TEXT NOT NULL, targets TEXT NOT NULL, rooms TEXT NOT NULL, expires REAL NOT NULL, budget INTEGER NOT NULL, depth INTEGER NOT NULL, confirm TEXT NOT NULL, parent_id TEXT REFERENCES grants(id), charter_layer_id TEXT, charter_revision INTEGER, follow INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, revoked REAL, revoked_by TEXT REFERENCES users(id), revoke_reason TEXT, signature TEXT NOT NULL, revocation_signature TEXT);
CREATE TABLE IF NOT EXISTS budget_uses(grant_id TEXT NOT NULL REFERENCES grants(id), ticket_id TEXT NOT NULL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS budget_uses_by_grant ON budget_uses(grant_id, created);
'''
HOUR, DAY = 3600, 86400
MODERATE_ACTIONS = ('add_member', 'remove_member')  # room moderators (M1): the actions a moderate grant lists
NOT_IN_ROOM = 'a room you are not in'  # G11: the title anyone outside a listed room sees
MAX_LISTED = 20  # G8 steps 1 and 4: at most 20 rooms and 20 targets
MAX_BUDGET = 500  # G8 step 6, spec A's bound
# G8's refusals, one per check, so a test can tell which check answered.
ROOMS_SHAPE = 'rooms is "*" or a list of 1 to 20 room ids, each listed once'
ROOM_NOT_YOURS = 'Each listed room must be a room you are in'
ROOM_REPLACED = 'A listed room was replaced by a newer linked room; list the current one'
ROOM_WITHOUT_GRANTEE = 'Each listed room must also have the grantee as a member'
GRANTEE_NOT_PERSON = 'The grantee must be an active person on this station'
GRANTEE_IS_YOU = 'You cannot grant to yourself'
TARGETS_SHAPE = 'targets is a list of 1 to 20 ship ids, each listed once'
TARGET_NOT_YOURS = 'Each target must be a ship you own'
BUDGET_RANGE = 'budget is a whole number from 1 to 500'
ENDED = "{by} ended {name}'s moderation of this room."
REASON_SHAPE = 'A reason is one line of at most 200 characters'


def is_moderate(grant):
    """M1: a grant row or dict whose `actions` JSON is a non-empty subset of MODERATE_ACTIONS. Such a grant never builds."""
    try:
        actions = json.loads(grant['actions'])
    except (TypeError, ValueError):
        return False
    return isinstance(actions, list) and bool(actions) and all(a in MODERATE_ACTIONS for a in actions)


def short_id(grant_id):
    """G9: '#' and the first 4 characters of the id, as in spec A's footers."""
    return '#' + grant_id[:4]


def _whole(value, low, high):
    """G8 steps 5 and 6: a JSON integer in range. bool is an int in Python, so `true` would pass as 1 without the type
    check; 24.0 and "24" are refused too."""
    return type(value) is int and low <= value <= high


def _id_list(value):
    """1 to 20 distinct ids. A repeated id is refused, never merged (G8)."""
    return (isinstance(value, list) and 1 <= len(value) <= MAX_LISTED
            and all(isinstance(item, str) and 0 < len(item) <= 100 for item in value) and len(set(value)) == len(value))


def _utc(moment):
    return datetime.fromtimestamp(moment, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


class Grants:
    def _grant_policy(self, db):
        """G7: spec A's no-charter defaults. Every check reads the policy through this one function, so step 4 puts the
        charter behind it and validity doesn't change. `grantees` None is the unrestricted set."""
        return {'max_depth': 3, 'max_expiry_hours': 720, 'agent_grant_default_hours': 24, 'builds_per_ship_per_day': 20,
                'delegable': ['direct'], 'grantees': None}

    def _insert_grant(self, db, issuer_id, grantee_id, targets, rooms, hours, budget, actions=('direct',)):
        """A root `direct` grant, stored and signed in the caller's transaction; the caller has checked every field (G8).
        Only make_moderate_grant passes other actions. Step 3 fixes depth and confirm, and leaves parent_id, the charter columns and follow empty. The row holds
        an empty signature only until _sign_grant fills it, in this transaction (G12). Returns the grant's id."""
        key, now = uid(), self.clock()
        db.execute('INSERT INTO grants(id,issuer_id,grantee_id,actions,targets,rooms,expires,budget,depth,confirm,created,'
                   "signature) VALUES(?,?,?,?,?,?,?,?,0,'none',?,'')",
                   (key, issuer_id, grantee_id, encode(list(actions)), encode(targets), encode(rooms), now + hours * HOUR,
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
        """Builds (budget_uses) plus member changes (member_changes) charged to a grant in the last 24 hours; a grant has
        rows in only one. A use exactly 24 hours old no longer counts (G9, test 6)."""
        return db.execute('SELECT (SELECT count(*) FROM budget_uses WHERE grant_id=? AND created>?)'
                          ' + (SELECT count(*) FROM member_changes WHERE grant_id=? AND created>?)',
                          (grant_id, now - DAY, grant_id, now - DAY)).fetchone()[0]

    def _covered_room(self, db, grant):
        """M4, ruling 7: the current room a moderate grant covers: the listed room while current, else the room it was
        replaced by (_current_room). None for any other grant, and at a fork, which covers nothing."""
        if not is_moderate(grant):
            return None
        listed = json.loads(grant['rooms'])[0]
        replaced = db.execute(f'SELECT 1 WHERE ? IN ({REPLACED_ROOMS})', (listed,)).fetchone()
        return self._current_room(db, listed) if replaced else listed

    def _ship_grant_builds(self, db, ship_id, now):
        """A ship's grant build tickets in the last 24 hours, under every grant: G11's ship_builds_left and G15's per-ship
        cap read this one count, so the page and the ticket can't disagree. Owner builds never count."""
        return db.execute("SELECT count(*) FROM tickets WHERE ship_id=? AND mode='build' AND basis='grant' AND created>?",
                          (ship_id, now - DAY)).fetchone()[0]

    def _grant_validity(self, db, grant, budget=True):
        """G9: (True, None), or (False, the reason of the first check that fails). Each link, from the grant up to its
        root, is checked in the spec's order: 1 revoked, 2 expired, 3 the policy in force now (lifetime, chain length,
        grantee set), 4 budget, 5 the root's issuer still owns every target. Names are the station's own, through
        safe_line. budget=False skips check 4, for a ticket that has already paid (G18)."""
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
            if budget and self._budget_used(db, link['id'], now) >= link['budget']:
                noun = 'change' if is_moderate(link) else 'build'
                used = f'{link["budget"]} {noun}' + ('' if link['budget'] == 1 else 's')
                return False, f'Grant {short} has used its {used} for the last 24 hours'
            if is_moderate(link):
                reason = self._moderate_pause(db, link)
                if reason:
                    return False, reason
                continue
            for ship_id in json.loads(link['targets']):
                ship = db.execute('SELECT name, owner_id FROM users WHERE id=?', (ship_id,)).fetchone()
                if ship is None or ship['owner_id'] != root['issuer_id']:
                    issuer = db.execute('SELECT name FROM users WHERE id=?', (root['issuer_id'],)).fetchone()
                    return False, f'{safe_line(issuer["name"])} no longer owns {safe_line(ship["name"]) if ship else "a ship that is gone"}'
        return True, None

    def _moderate_pause(self, db, link):
        """M5 check 5 for a moderate grant: why it is paused now, or None. The covered room must exist and be owned by the
        issuer, hold the grantee, and have no member on another station."""
        covered = self._covered_room(db, link)
        if covered is None:
            return f'Grant {short_id(link["id"])} covers no current room'
        room = db.execute('SELECT owner_id FROM rooms WHERE id=?', (covered,)).fetchone()
        name = lambda user_id: safe_line((db.execute('SELECT name FROM users WHERE id=?', (user_id,)).fetchone() or {'name': 'Someone'})['name'], 40)
        if room is None or room['owner_id'] != link['issuer_id']:
            return f'{name(link["issuer_id"])} no longer owns this room'
        if db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (covered, link['grantee_id'])).fetchone() is None:
            return f'{name(link["grantee_id"])} is no longer in this room'
        if db.execute('SELECT 1 FROM remote_room_members WHERE room_id=?', (covered,)).fetchone():
            return 'This room now has a member on another station'
        return None

    def _owns_a_target(self, db, actor, grant):
        ships = json.loads(grant['targets'])
        marks = ','.join('?' * len(ships))
        return bool(ships) and db.execute(f"SELECT 1 FROM users WHERE kind='ship' AND owner_id=? AND id IN ({marks})",
                                          (actor, *ships)).fetchone() is not None

    def _grant_visible(self, db, actor, grant):
        """G11: the caller issued it (or a grant above it, so G10's issuer above can reach it; in step 3 every grant is its
        own root), holds it, or owns one of its ships. No one else sees a grant, an admin included."""
        return (grant['grantee_id'] == actor or any(link['issuer_id'] == actor for link in self._grant_chain(db, grant))
                or self._owns_a_target(db, actor, grant))

    def _visible_grant(self, db, actor, grant_id):
        """The grant, or 404 when there is none or G11 doesn't show it to the caller: the same answer, so no route says
        whether a grant exists."""
        grant = db.execute('SELECT * FROM grants WHERE id=?', (grant_id,)).fetchone() if isinstance(grant_id, str) else None
        if grant is None or not self._grant_visible(db, actor, grant):
            raise Problem(404, 'Not found')
        return grant

    def _member_title(self, db, actor, room_id):
        """A room's title when the caller is a member of it, else None."""
        row = db.execute('SELECT rooms.title FROM rooms JOIN room_members ON room_members.room_id=rooms.id '
                         'WHERE rooms.id=? AND room_members.user_id=?', (room_id, actor)).fetchone()
        return row['title'] if row else None

    def _room_label(self, db, actor, room_id):
        """G11: a room's title for its members only; anyone else sees NOT_IN_ROOM."""
        title = self._member_title(db, actor, room_id)
        return NOT_IN_ROOM if title is None else title

    def _rooms_back(self, db, room_id):
        """G15: a room and every room it replaced, walking back along linked_room_id, the room itself first. A seen list
        ends the walk at a cycle made by hand, so it always ends."""
        walked, key = [], room_id
        while key is not None and key not in walked:
            walked.append(key)
            row = db.execute('SELECT linked_room_id FROM rooms WHERE id=?', (key,)).fetchone()
            key = row['linked_room_id'] if row else None
        return walked

    def _current_room(self, db, room_id):
        """G11: the current room a replaced room now covers, following linked_room_id forward (S5); None for a current
        room. add_participants never forks a chain (work board 8.4), so a fork or a cycle (only an older or hand-edited
        database has one) ends the walk with None too."""
        key, seen = room_id, {room_id}
        while True:
            later = db.execute('SELECT id FROM rooms WHERE linked_room_id=?', (key,)).fetchall()
            if not later:
                return None if key == room_id else key
            if len(later) > 1 or later[0]['id'] in seen:
                return None
            key = later[0]['id']
            seen.add(key)

    def _grant_view(self, db, actor, grant):
        """G11: a grant as its issuer, grantee and target owners see it. Names and titles are people's text, sent as they
        are; the web app escapes them. `reason` is there only when the grant is not valid."""
        now, policy = self.clock(), self._grant_policy(db)

        def person(user_id):
            if user_id is None:
                return None
            row = db.execute('SELECT name FROM users WHERE id=?', (user_id,)).fetchone()
            return {'id': user_id, 'name': row['name'] if row else None}

        targets = []
        for ship_id in json.loads(grant['targets']):
            built = self._ship_grant_builds(db, ship_id, now)  # G11: under every grant, as G15's cap counts them
            targets.append({**person(ship_id), 'ship_builds_left': max(0, policy['builds_per_ship_per_day'] - built)})
        rooms = json.loads(grant['rooms'])
        if rooms != '*':
            listed = []
            for room_id in rooms:
                entry, current = {'id': room_id, 'title': self._room_label(db, actor, room_id)}, self._current_room(db, room_id)
                if current is not None:  # 3b's section 2 review: no id for a non-member, who has no use for it
                    title = self._member_title(db, actor, current)
                    entry['current'] = {'title': NOT_IN_ROOM} if title is None else {'id': current, 'title': title}
                listed.append(entry)
            rooms = listed
        valid, reason = self._grant_validity(db, grant)
        origin = db.execute('SELECT made_via FROM grant_origins WHERE grant_id=?', (grant['id'],)).fetchone()
        view = {'id': grant['id'], 'short': short_id(grant['id']), 'issuer': person(grant['issuer_id']),
                'grantee': person(grant['grantee_id']), 'targets': targets, 'rooms': rooms, 'expires': grant['expires'],
                'budget': grant['budget'], 'budget_left': max(0, grant['budget'] - self._budget_used(db, grant['id'], now)),
                'created': grant['created'], 'revoked': grant['revoked'], 'revoked_by': person(grant['revoked_by']),
                'revoke_reason': grant['revoke_reason'], 'valid': valid, 'actions': json.loads(grant['actions']),
                'made_via': origin['made_via'] if origin else None}
        if not valid:
            view['reason'] = reason
        return view

    def list_grants(self, actor):
        """G11: GET /api/grants, newest first. A station holds tens of grants, so each is checked here in Python, through
        the one visibility rule the other routes use."""
        with self.transaction() as db:
            rows = db.execute('SELECT * FROM grants ORDER BY created DESC, id DESC').fetchall()
            return [self._grant_view(db, actor, row) for row in rows if self._grant_visible(db, actor, row)]

    def grant_people(self, actor):
        """G21's person list (GET /api/grants/people): this station's active people other than the caller, by name.
        Ships, residents, the system author, accounts awaiting activation and remote contacts are never in it."""
        with self.transaction() as db:
            self._person(db, actor)
            return [dict(row) for row in db.execute("SELECT id, name FROM users WHERE kind='person' AND activation_pending=0 "
                                                    'AND id!=? ORDER BY name COLLATE NOCASE, id', (actor,))]

    def _grant_rooms(self, db, actor, grantee, rooms):
        """G8 steps 1 and 2. Step 1 runs over every listed room before step 2 looks at any, so no answer says anything
        about a room the caller is not in: an unknown id, a remote id, a breakout and a room the caller is not in each
        get the same 404."""
        if rooms == '*':
            return rooms
        if not _id_list(rooms):
            raise Problem(400, ROOMS_SHAPE)
        for room_id in rooms:
            if (':' in room_id or self._breakout(db, room_id) is not None
                    or db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (room_id, actor)).fetchone() is None):
                raise Problem(404, ROOM_NOT_YOURS)
        member = grantee if isinstance(grantee, str) else ''  # step 3 refuses a grantee that isn't an id
        for room_id in rooms:
            if db.execute(f'SELECT 1 FROM rooms WHERE id=? AND id IN ({REPLACED_ROOMS})', (room_id,)).fetchone():
                raise Problem(400, ROOM_REPLACED)
            if db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (room_id, member)).fetchone() is None:
                raise Problem(400, ROOM_WITHOUT_GRANTEE)
        return rooms

    def _grant_grantee(self, db, actor, grantee):
        """G8 step 3: a person on this station, not a ship, the system author or an account awaiting activation, and not
        the caller."""
        row = db.execute('SELECT kind, activation_pending FROM users WHERE id=?', (grantee,)).fetchone() if isinstance(grantee, str) else None
        if row is None or row['kind'] != 'person' or row['activation_pending']:
            raise Problem(400, GRANTEE_NOT_PERSON)
        if grantee == actor:
            raise Problem(400, GRANTEE_IS_YOU)

    def _grant_targets(self, db, actor, targets):
        """G8 step 4: 1 to 20 ships whose owner is the caller. A resident has no owner, and an admin's power never
        reaches another person's ship."""
        if not _id_list(targets):
            raise Problem(400, TARGETS_SHAPE)
        for ship_id in targets:
            if db.execute("SELECT 1 FROM users WHERE id=? AND kind='ship' AND owner_id=?", (ship_id, actor)).fetchone() is None:
                raise Problem(400, TARGET_NOT_YOURS)
        return targets

    def make_grant(self, actor, grantee, targets, rooms, hours, budget):
        """G8: POST /api/grants. The caller is the issuer. Checked in the spec's order, the first failure answers; then
        the row is stored and signed in one transaction (G12) and returned as G11 shows it."""
        with self.transaction() as db:
            self._person(db, actor)
            policy = self._grant_policy(db)
            rooms = self._grant_rooms(db, actor, grantee, rooms)
            self._grant_grantee(db, actor, grantee)
            targets = self._grant_targets(db, actor, targets)
            if not _whole(hours, 1, policy['max_expiry_hours']):
                raise Problem(400, f'hours is a whole number from 1 to {policy["max_expiry_hours"]}')
            if not _whole(budget, 1, MAX_BUDGET):
                raise Problem(400, BUDGET_RANGE)
            key = self._insert_grant(db, actor, grantee, targets, rooms, hours, budget)
            self._record_origin(db, key, 'browser')  # M20, ruling 16
            return self._grant_view(db, actor, db.execute('SELECT * FROM grants WHERE id=?', (key,)).fetchone())

    def _may_revoke(self, db, actor, grant):
        """G10: the issuer, the issuer of any grant above it (none in step 3, but the walk is the same), or the owner of
        any target ship. Being an admin gives no power over other people's grants."""
        return any(link['issuer_id'] == actor for link in self._grant_chain(db, grant)) or self._owns_a_target(db, actor, grant)

    def _revoke(self, db, actor, grant, reason):
        """The revocation, signed (G12) in the caller's transaction. A moderate grant's end is announced in the room it
        covers now (M19), under the revoker's display name."""
        db.execute('UPDATE grants SET revoked=?, revoked_by=?, revoke_reason=? WHERE id=?',
                   (self.clock(), actor, reason, grant['id']))
        self._sign_revocation(db, grant['id'])
        room = self._covered_room(db, grant)
        if room is not None:
            name = lambda user_id: safe_line(db.execute('SELECT name FROM users WHERE id=?', (user_id,)).fetchone()['name'], 40)
            self._post_as_system(db, room, f'moderator-{grant["id"]}-revoked',
                                 ENDED.format(by=name(actor), name=name(grant['grantee_id'])))

    def revoke_grant(self, actor, grant_id, reason=None):
        """G10: POST /api/grants/{id}/revoke. 404 for anyone G11 doesn't show the grant to, then 403 for one who sees it
        but may not revoke it, then 409 when it is already revoked. The revocation is signed in this transaction (G12).
        A missing or blank reason is `revoked`."""
        if reason is None or (isinstance(reason, str) and not reason.strip()):
            reason = 'revoked'
        if not isinstance(reason, str) or len(reason) > 200 or reason.splitlines() != [reason] or '\x00' in reason:
            raise Problem(400, REASON_SHAPE)
        with self.transaction() as db:
            grant = self._visible_grant(db, actor, grant_id)
            if not self._may_revoke(db, actor, grant):
                raise Problem(403, 'Only its issuer or the owner of one of its ships can revoke this grant')
            if grant['revoked'] is not None:
                raise Problem(409, f'Grant {short_id(grant["id"])} is already revoked')
            self._revoke(db, actor, grant, reason)
            return self._grant_view(db, actor, db.execute('SELECT * FROM grants WHERE id=?', (grant['id'],)).fetchone())
