"""Run tickets: just before a run, the station decides its mode and records it (spec A, section 4). Step 1 of the
build moves today's rule here unchanged: the ship's owner, mentioning it, gets a builder; everyone else gets a
read-only run. Later steps add grants and directs to the same decision."""
import json
from .common import Problem, require, text, uid
from .instructions import render_blocks
from .ships import safe_line

TICKET_LIFETIME = 7200  # outlives the watcher's three tries of 20 minutes each
DEFER_BOUND_SECONDS = 7200   # S5: a mention first deferred this long ago runs even while a watch is on (R21)
NOTICE_AFTER_SECONDS = 1800  # S5: the station's notice, at most once per mention (Task 6)
NEVER_ANSWERED = 'Station notices and claim messages are never answered'

TICKET_SCHEMA = '''
CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY, ship_id TEXT NOT NULL REFERENCES users(id), message_id TEXT NOT NULL REFERENCES messages(id), direct_id TEXT, mode TEXT NOT NULL, basis TEXT NOT NULL, root_id TEXT REFERENCES users(id), chain TEXT NOT NULL DEFAULT '[]', hops INTEGER NOT NULL DEFAULT 0, instructions TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL, created REAL NOT NULL, finished REAL, UNIQUE(ship_id, message_id));
CREATE TABLE IF NOT EXISTS message_sources(message_id TEXT PRIMARY KEY REFERENCES messages(id), ticket_id TEXT UNIQUE NOT NULL REFERENCES tickets(id));
CREATE TABLE IF NOT EXISTS deferrals(ship_id TEXT NOT NULL REFERENCES users(id), message_id TEXT NOT NULL REFERENCES messages(id), first_deferred REAL NOT NULL, notice_posted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(ship_id, message_id));
'''


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
        """S5's order: 0 never answered (422), 1 answered, 2 running, 3 finished (409), 4 defer, 5 run. Steps 1 and 4
        only for a watcher that asked for them (R23); without them the answer is exactly today's."""
        text(message_id, 'message ID', 100)
        with self.transaction() as db:
            ship = self._ticket_ship(db, actor)
            message = require(db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone())
            require(db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (message['room_id'], actor)).fetchone())
            if self._never_answered(db, message):
                raise Problem(422, NEVER_ANSWERED)
            if decisions and self._answered(db, actor, message_id):
                db.execute('DELETE FROM deferrals WHERE ship_id=? AND message_id=?', (actor, message_id))
                return {'decision': 'answered', 'message_id': message_id}
            existing = db.execute('SELECT * FROM tickets WHERE ship_id=? AND message_id=?', (actor, message_id)).fetchone()
            if existing:
                if self._ticket_running(existing):
                    return self._decided(db, existing, station, decisions)
                raise Problem(409, 'This message has already been answered')
            mode, basis, root = self._mode_for(db, ship, message)
            if decisions and mode == 'read' and self._writable_on_watch(db, actor):
                deferred = self._defer(db, ship, message)
                if deferred is not None:
                    return deferred
            held = db.execute('SELECT first_deferred FROM deferrals WHERE ship_id=? AND message_id=?', (actor, message_id)).fetchone()
            db.execute('DELETE FROM deferrals WHERE ship_id=? AND message_id=?', (actor, message_id))
            key = uid()
            bound = json.dumps([[l['layer_id'], l['revision']] for l in self._binding_layers(db, actor)])
            db.execute('INSERT INTO tickets(id,ship_id,message_id,mode,basis,root_id,instructions,status,created) VALUES(?,?,?,?,?,?,?,?,?)',
                       (key, actor, message_id, mode, basis, root, bound, 'running', self.clock()))
            decided = self._decided(db, db.execute('SELECT * FROM tickets WHERE id=?', (key,)).fetchone(), station, decisions)
            if decisions and held is not None:  # R37: only the station's own row says this run resolves a deferral
                decided['first_deferred'] = held['first_deferred']
            return decided

    def _decided(self, db, row, station, decisions):
        ticket = self._ticket_json(db, row, station)
        return dict(ticket, decision='run') if decisions else ticket

    def _mode_for(self, db, ship, message):
        """Today's rule, unchanged: the owner's own mention builds; everything else reads."""
        author = require(db.execute('SELECT id,kind FROM users WHERE id=?', (message['author_id'],)).fetchone())
        mentioned = db.execute('SELECT 1 FROM mentions WHERE message_id=? AND user_id=?', (message['id'], ship['id'])).fetchone()
        owner = ship['owner_id']
        if owner and mentioned and author['kind'] == 'person' and author['id'] == owner:
            return 'build', 'owner', owner
        return 'read', 'none', None

    def _answered(self, db, ship_id, message_id):
        """R7: a message by this ship whose reply_to is the mention. A kind message never counts, and the system
        author's can't, since its author isn't the ship (R32)."""
        return db.execute('''SELECT 1 FROM message_replies JOIN messages ON messages.id=message_replies.message_id
            WHERE message_replies.reply_to=? AND messages.author_id=?
            AND message_replies.message_id NOT IN (SELECT message_id FROM message_kinds)''', (message_id, ship_id)).fetchone() is not None

    def _defer(self, db, ship, message):
        """S5 step 4: keep or start the deferral. None once it has waited DEFER_BOUND_SECONDS, so the mention runs."""
        now = self.clock()
        db.execute('INSERT OR IGNORE INTO deferrals(ship_id,message_id,first_deferred) VALUES(?,?,?)', (ship['id'], message['id'], now))
        row = db.execute('SELECT * FROM deferrals WHERE ship_id=? AND message_id=?', (ship['id'], message['id'])).fetchone()
        if now - row['first_deferred'] >= DEFER_BOUND_SECONDS:
            return None
        return {'decision': 'defer', 'message_id': message['id'], 'first_deferred': row['first_deferred']}

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
