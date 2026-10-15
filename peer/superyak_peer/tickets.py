"""Run tickets: just before a run, the station decides its mode and records it (spec A, section 4). The ship's owner,
mentioning it, gets a builder; so does a person holding a grant over it (spec A step 3, G15); everyone else gets a
read-only run. Step 5 adds directs to the same decision."""
import json
import math
from .common import REPLACED_ROOMS, Problem, require, text, uid
from .instructions import render_blocks
from .ships import safe_line

TICKET_LIFETIME = 7200  # outlives the watcher's three tries of 20 minutes each
MENTION_FRESH_SECONDS = 86400  # fresh owner mentions: within a day of the ticket, either side (step 3's G15 bound)
DEFER_BOUND_SECONDS = 7200   # S5: a mention first deferred this long ago runs even while a watch is on (R21)
NOTICE_AFTER_SECONDS = 1800  # S5: the station's notice, at most once per mention (Task 6)
NOTICE_TEMPLATE = ("Station notice: a mention of {ship} has waited {waited} minutes for {ship}'s session on watch. "
                   "A run will answer it when that watch ends, or once it has waited 120 minutes.")
NEVER_ANSWERED = 'Station notices and claim messages are never answered'

TICKET_SCHEMA = '''
CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY, ship_id TEXT NOT NULL REFERENCES users(id), message_id TEXT NOT NULL REFERENCES messages(id), direct_id TEXT, mode TEXT NOT NULL, basis TEXT NOT NULL, root_id TEXT REFERENCES users(id), chain TEXT NOT NULL DEFAULT '[]', hops INTEGER NOT NULL DEFAULT 0, instructions TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL, created REAL NOT NULL, finished REAL, UNIQUE(ship_id, message_id));
CREATE TABLE IF NOT EXISTS message_sources(message_id TEXT PRIMARY KEY REFERENCES messages(id), ticket_id TEXT UNIQUE NOT NULL REFERENCES tickets(id));
CREATE TABLE IF NOT EXISTS deferrals(ship_id TEXT NOT NULL REFERENCES users(id), message_id TEXT NOT NULL REFERENCES messages(id), first_deferred REAL NOT NULL, notice_posted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(ship_id, message_id));
'''


def _in_room(db, room_id, user_id):
    return db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (room_id, user_id)).fetchone() is not None


def _made_by(grant, created):
    """G15: the grant was made no later than the message (equal times count). A `created` that isn't a number can't be
    compared: it passes here, and _mention_stale reads it `old`, so the read's basis says old, as an owner's would."""
    return not isinstance(created, (int, float)) or grant['created'] <= created


class Tickets:
    def _ticket_ship(self, db, actor):
        row = require(db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone())
        if row['kind'] != 'ship':
            raise Problem(403, 'Only a ship key can do this')
        return row

    def _ticket_running(self, row):
        return row['status'] == 'running' and row['created'] > self.clock() - TICKET_LIFETIME

    def _ticket_json(self, db, row, station=''):
        root = db.execute('SELECT name FROM users WHERE id=?', (row['root_id'],)).fetchone() if row['root_id'] else None
        root_name = safe_line(root['name']) if root else None
        footer = f'Builder for {root_name} (owner)' if row['mode'] == 'build' and row['basis'] == 'owner' and root_name else ''
        return {'id': row['id'], 'ship_id': row['ship_id'], 'message_id': row['message_id'], 'mode': row['mode'],
                'basis': row['basis'], 'root_id': row['root_id'], 'root_name': root_name, 'chain': json.loads(row['chain']),
                'hops': row['hops'], 'instructions': json.loads(row['instructions']),
                'blocks': render_blocks(self._layers_for(db, json.loads(row['instructions'])), station), 'footer': footer,
                'status': 'running' if self._ticket_running(row) else 'finished', 'created': row['created']}

    def issue_ticket(self, actor, message_id, station='', decisions=False):
        """S5's order: 0 never answered (422), 1 answered, 2 running (a grant ticket re-checked first, G18), 3 finished
        (409), 4 defer, 5 run. Steps 1 and 4 only for a watcher that asked for them (R23); without them the answer is
        exactly today's."""
        text(message_id, 'message ID', 100)
        with self.transaction() as db:
            ship = self._ticket_ship(db, actor)
            message = require(db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone())
            require(db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (message['room_id'], actor)).fetchone())
            self._refuse_closed_breakout(db, message['room_id'], 422)  # any of its messages: done, silently
            if self._never_answered(db, message):
                raise Problem(422, NEVER_ANSWERED)
            if decisions and self._answered(db, actor, message_id):
                db.execute('DELETE FROM deferrals WHERE ship_id=? AND message_id=?', (actor, message_id))
                return {'decision': 'answered', 'message_id': message_id}
            existing = db.execute('SELECT * FROM tickets WHERE ship_id=? AND message_id=?', (actor, message_id)).fetchone()
            if existing:
                if self._ticket_running(existing):
                    lapsed = self._grant_lapsed(db, existing, message) if existing['basis'] == 'grant' else None
                    if lapsed is not None:  # G18: finished and saved with the refusal, so it can never label a post
                        db.execute("UPDATE tickets SET status='finished',finished=? WHERE id=?", (self.clock(), existing['id']))
                        raise Problem(409, lapsed, keep=True)
                    return self._decided(db, existing, station, decisions)
                raise Problem(409, 'This message has already been answered')
            mode, basis, root, chain = self._mode_for(db, ship, message)
            if decisions and mode == 'read' and self._writable_on_watch(db, actor):
                deferred = self._defer(db, ship, message)
                if deferred is not None:
                    return deferred
            held = db.execute('SELECT first_deferred FROM deferrals WHERE ship_id=? AND message_id=?', (actor, message_id)).fetchone()
            db.execute('DELETE FROM deferrals WHERE ship_id=? AND message_id=?', (actor, message_id))
            key, now = uid(), self.clock()
            bound = json.dumps([[l['layer_id'], l['revision']] for l in self._binding_layers(db, actor)])
            db.execute('INSERT INTO tickets(id,ship_id,message_id,mode,basis,root_id,chain,instructions,status,created,first_deferred) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (key, actor, message_id, mode, basis, root, json.dumps([link['id'] for link in chain]), bound, 'running',
                        now, held['first_deferred'] if held is not None else None))
            for link in chain:  # G16: one budget use per link, in the ticket's own transaction
                db.execute('INSERT INTO budget_uses(grant_id,ticket_id,created) VALUES(?,?,?)', (link['id'], key, now))
            return self._decided(db, db.execute('SELECT * FROM tickets WHERE id=?', (key,)).fetchone(), station, decisions)

    def _decided(self, db, row, station, decisions):
        ticket = self._ticket_json(db, row, station)
        if not decisions:
            return ticket  # R23: an old watcher's answer is exactly today's
        decided = dict(ticket, decision='run')
        if row['first_deferred'] is not None:  # F3: on issue and on every re-send, the station's own record (R37)
            decided['first_deferred'] = row['first_deferred']
        return decided

    def _mode_for(self, db, ship, message):
        """Spec A section 4, rules 2 and 3 (step 3's basis grant, G15), bounded by fresh owner mentions: the owner's own
        fresh mention builds; so does a person's fresh mention under the oldest grant that covers it. An old or answered
        mention that would otherwise build reads, its basis saying why; everything else reads, basis none. Returns
        (mode, basis, root_id, chain), chain being the spent grant's rows, root first."""
        author = require(db.execute('SELECT id,kind FROM users WHERE id=?', (message['author_id'],)).fetchone())
        mentioned = db.execute('SELECT 1 FROM mentions WHERE message_id=? AND user_id=?', (message['id'], ship['id'])).fetchone()
        owner = ship['owner_id']
        if not (owner and mentioned and author['kind'] == 'person'):
            return 'read', 'none', None, []
        if author['id'] == owner:
            stale = self._mention_stale(db, ship['id'], message)
            return ('build', 'owner', owner, []) if stale is None else ('read', stale, None, [])
        chain = self._spendable_grant(db, ship, message)
        if chain is None:
            return 'read', 'none', None, []
        stale = self._mention_stale(db, ship['id'], message)  # G15: age and answered decide only the read's basis
        return ('build', 'grant', chain[0]['issuer_id'], chain) if stale is None else ('read', stale, None, [])

    def _spendable_grant(self, db, ship, message):
        """G15, every condition but the mention's age and answer (the caller asks _mention_stale): the chain, root first,
        of the oldest grant (by created, then id) that lets this message's author direct this ship in this room now, or
        None. issue_ticket has already refused (404) a ship that isn't in the room."""
        room_id, author_id, now = message['room_id'], message['author_id'], self.clock()
        if (':' in room_id or self._breakout(db, room_id) is not None
                or db.execute(f'SELECT 1 FROM rooms WHERE id=? AND id IN ({REPLACED_ROOMS})', (room_id,)).fetchone()
                or not _in_room(db, room_id, author_id)):
            return None  # R must be local, not a breakout and current, and the author still in it
        if self._ship_grant_builds(db, ship['id'], now) >= self._grant_policy(db)['builds_per_ship_per_day']:
            return None  # the per-ship cap, under every grant; owner builds never count
        covered = self._rooms_back(db, room_id)
        for grant in db.execute('SELECT * FROM grants WHERE grantee_id=? ORDER BY created, id', (author_id,)).fetchall():
            rooms = json.loads(grant['rooms'])
            if (ship['id'] not in json.loads(grant['targets']) or 'direct' not in json.loads(grant['actions'])
                    or (rooms != '*' and not any(key in rooms for key in covered)) or not _made_by(grant, message['created'])):
                continue
            chain = self._grant_chain(db, grant)[::-1]  # root first
            if (_in_room(db, room_id, chain[0]['issuer_id']) and all(link['confirm'] != 'each' for link in chain)
                    and self._grant_validity(db, grant)[0]):
                return chain
        return None

    def _grant_lapsed(self, db, ticket, message):
        """G18: a running grant ticket asked for again. None while its grant still holds, else why not: G9's revocation,
        expiry, policy and ownership checks, then the root issuer's membership of the message's room. Not the budget or
        the per-ship cap, which this ticket already paid. Never raises: a missing grant or issuer row (only by hand) is
        "gone"."""
        links = [db.execute('SELECT * FROM grants WHERE id=?', (key,)).fetchone() for key in json.loads(ticket['chain'])]
        if not links or any(link is None for link in links):
            return 'The grant behind this run is gone'
        valid, reason = self._grant_validity(db, links[-1], budget=False)
        if not valid:
            return reason
        if not _in_room(db, message['room_id'], links[0]['issuer_id']):
            issuer = db.execute('SELECT name FROM users WHERE id=?', (links[0]['issuer_id'],)).fetchone()
            return f'{safe_line(issuer["name"])} is no longer in this room' if issuer else 'The grant behind this run is gone'
        return None

    def _answered(self, db, ship_id, message_id):
        """R7: a message by this ship whose reply_to is the mention. A kind message never counts, and the system
        author's can't, since its author isn't the ship (R32)."""
        return db.execute('''SELECT 1 FROM message_replies JOIN messages ON messages.id=message_replies.message_id
            WHERE message_replies.reply_to=? AND messages.author_id=?
            AND message_replies.message_id NOT IN (SELECT message_id FROM message_kinds)''', (message_id, ship_id)).fetchone() is not None

    def _mention_stale(self, db, ship_id, message):
        """Fresh owner mentions: None while the mention may build, else why not. 'old' unless `created` is a finite int or
        float within MENTION_FRESH_SECONDS of now on either side; then 'answered' (R7). Grants step 3's 3c calls it too."""
        created = message['created']
        if (isinstance(created, bool) or not isinstance(created, (int, float))
                or (isinstance(created, float) and not math.isfinite(created))
                or abs(self.clock() - created) > MENTION_FRESH_SECONDS):
            return 'old'
        if self._answered(db, ship_id, message['id']):
            return 'answered'
        return None

    def _waiting_deferrals(self, db, ship_id, message_ids):
        """Stale deferrals spec: of the given mentions, those whose deferral still waits for the session, oldest first.
        A deferral waits while it is under DEFER_BOUND_SECONDS (the ticket path's >=, below) and the ship hasn't
        answered the mention (R7). One that no longer waits keeps its row for the watcher's next ask (R24)."""
        ids = list(dict.fromkeys(message_ids))
        if not ids:
            return []
        now = self.clock()
        rows = db.execute(f'SELECT message_id, first_deferred FROM deferrals WHERE ship_id=? AND message_id IN '
                          f'({",".join("?" * len(ids))}) ORDER BY first_deferred', (ship_id, *ids)).fetchall()
        return [r['message_id'] for r in rows
                if now - r['first_deferred'] < DEFER_BOUND_SECONDS and not self._answered(db, ship_id, r['message_id'])]

    def _defer(self, db, ship, message):
        """S5 step 4: keep or start the deferral. None once it has waited DEFER_BOUND_SECONDS, so the mention runs."""
        now = self.clock()
        db.execute('INSERT OR IGNORE INTO deferrals(ship_id,message_id,first_deferred) VALUES(?,?,?)', (ship['id'], message['id'], now))
        row = db.execute('SELECT * FROM deferrals WHERE ship_id=? AND message_id=?', (ship['id'], message['id'])).fetchone()
        if now - row['first_deferred'] >= DEFER_BOUND_SECONDS:
            return None
        if not row['notice_posted'] and now - row['first_deferred'] >= NOTICE_AFTER_SECONDS:
            self._post_notice(db, ship, message, row['first_deferred'], now)
            db.execute('UPDATE deferrals SET notice_posted=1 WHERE ship_id=? AND message_id=?', (ship['id'], message['id']))
        return {'decision': 'defer', 'message_id': message['id'], 'first_deferred': row['first_deferred']}

    def _post_notice(self, db, ship, message, first, now):
        """S5, S11: one of the two notices the station writes (ship briefs R18), in this transaction under BEGIN
        IMMEDIATE, together with notice_posted, so it is posted at most once. It names only the ship and the minutes waited
        (R11)."""
        body = NOTICE_TEMPLATE.format(ship=safe_line(ship['name'], 40), waited=int((now - first) // 60))
        self._post_as_system(db, message['room_id'], f'notice-{ship["id"]}-{message["id"]}', body)

    def finish_ticket(self, actor, ticket_id, station=''):
        text(ticket_id, 'ticket ID', 100)
        with self.transaction() as db:
            self._ticket_ship(db, actor)
            row = require(db.execute('SELECT * FROM tickets WHERE id=? AND ship_id=?', (ticket_id, actor)).fetchone())
            if row['status'] == 'running':
                db.execute("UPDATE tickets SET status='finished',finished=? WHERE id=?", (self.clock(), ticket_id))
            return self._ticket_json(db, db.execute('SELECT * FROM tickets WHERE id=?', (ticket_id,)).fetchone(), station)

    def _check_ticket_label(self, db, actor, room_id, ticket_id):
        """A post may carry a ticket only if it is this ship's, still running, for a message in this room, and has
        labelled nothing yet: one labelled message per ticket, so a session can never borrow a run's label."""
        text(ticket_id, 'ticket ID', 100)
        row = db.execute('SELECT tickets.*, messages.room_id AS ticket_room FROM tickets JOIN messages ON messages.id=tickets.message_id '
                         'WHERE tickets.id=? AND tickets.ship_id=?', (ticket_id, actor)).fetchone()
        if row is None or not self._ticket_running(row) or row['ticket_room'] != room_id:
            raise Problem(409, 'This ticket cannot label a message here')
        if db.execute('SELECT 1 FROM message_sources WHERE ticket_id=?', (ticket_id,)).fetchone():
            raise Problem(409, 'This ticket has already labelled a message')

    def _sources(self, db, room_id):
        """Each local message's source as the station recorded it: a run's ticket, a ship's own post, or none for a
        person. Never derived from a client's own message ids."""
        runs = {r['message_id']: {'kind': 'run', 'mode': r['mode'], 'basis': r['basis'],
                                  'root_name': safe_line(r['root_name']) if r['root_name'] else None, 'answering': r['answering']}
                for r in db.execute('SELECT message_sources.message_id, tickets.mode, tickets.basis, tickets.message_id AS answering, '
                                    'users.name AS root_name FROM message_sources JOIN tickets ON tickets.id=message_sources.ticket_id '
                                    'JOIN messages ON messages.id=message_sources.message_id LEFT JOIN users ON users.id=tickets.root_id '
                                    'WHERE messages.room_id=?', (room_id,))}
        ships = {r[0] for r in db.execute("SELECT id FROM users WHERE kind='ship'")}
        kinds = {r[0]: r[1] for r in db.execute('SELECT message_kinds.message_id, message_kinds.kind FROM message_kinds JOIN messages '
                                               'ON messages.id=message_kinds.message_id WHERE messages.room_id=?', (room_id,))}
        return {r['id']: {'kind': kinds[r['id']]} if r['id'] in kinds else runs.get(r['id'], {'kind': 'post'}) if r['author_id'] in ships else None
                for r in db.execute('SELECT id,author_id FROM messages WHERE room_id=?', (room_id,))}
