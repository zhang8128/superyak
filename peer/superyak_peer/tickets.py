"""Run tickets: just before a run, the station decides its mode and records it (spec A, section 4). Step 1 of the
build moves today's rule here unchanged: the ship's owner, mentioning it, gets a builder; everyone else gets a
read-only run. Later steps add grants and directs to the same decision."""
import json
from .common import Problem, require, text, uid
from .ships import safe_line

TICKET_LIFETIME = 7200  # outlives the watcher's three tries of 20 minutes each

TICKET_SCHEMA = '''
CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY, ship_id TEXT NOT NULL REFERENCES users(id), message_id TEXT NOT NULL REFERENCES messages(id), direct_id TEXT, mode TEXT NOT NULL, basis TEXT NOT NULL, root_id TEXT REFERENCES users(id), chain TEXT NOT NULL DEFAULT '[]', hops INTEGER NOT NULL DEFAULT 0, instructions TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL, created REAL NOT NULL, finished REAL, UNIQUE(ship_id, message_id));
CREATE TABLE IF NOT EXISTS message_sources(message_id TEXT PRIMARY KEY REFERENCES messages(id), ticket_id TEXT UNIQUE NOT NULL REFERENCES tickets(id));
'''


class Tickets:
    def _ticket_ship(self, db, actor):
        row = require(db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone())
        if row['kind'] != 'ship':
            raise Problem(403, 'Only a ship key can do this')
        return row

    def _ticket_running(self, row):
        return row['status'] == 'running' and row['created'] > self.clock() - TICKET_LIFETIME

    def _ticket_json(self, db, row):
        root = db.execute('SELECT name FROM users WHERE id=?', (row['root_id'],)).fetchone() if row['root_id'] else None
        root_name = safe_line(root['name']) if root else None
        footer = f'Builder for {root_name} (owner)' if row['mode'] == 'build' and row['basis'] == 'owner' and root_name else ''
        return {'id': row['id'], 'ship_id': row['ship_id'], 'message_id': row['message_id'], 'mode': row['mode'],
                'basis': row['basis'], 'root_id': row['root_id'], 'root_name': root_name, 'chain': json.loads(row['chain']),
                'hops': row['hops'], 'instructions': json.loads(row['instructions']), 'blocks': '', 'footer': footer,
                'status': 'running' if self._ticket_running(row) else 'finished', 'created': row['created']}

    def issue_ticket(self, actor, message_id):
        text(message_id, 'message ID', 100)
        with self.transaction() as db:
            ship = self._ticket_ship(db, actor)
            message = require(db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone())
            require(db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (message['room_id'], actor)).fetchone())
            existing = db.execute('SELECT * FROM tickets WHERE ship_id=? AND message_id=?', (actor, message_id)).fetchone()
            if existing:
                if self._ticket_running(existing):
                    return self._ticket_json(db, existing)
                raise Problem(409, 'This message has already been answered')
            author = require(db.execute('SELECT id,kind FROM users WHERE id=?', (message['author_id'],)).fetchone())
            mentioned = db.execute('SELECT 1 FROM mentions WHERE message_id=? AND user_id=?', (message_id, actor)).fetchone()
            owner = ship['owner_id']
            if owner and mentioned and author['kind'] == 'person' and author['id'] == owner:
                mode, basis, root = 'build', 'owner', owner
            else:
                mode, basis, root = 'read', 'none', None
            key = uid()
            db.execute('INSERT INTO tickets(id,ship_id,message_id,mode,basis,root_id,status,created) VALUES(?,?,?,?,?,?,?,?)',
                       (key, actor, message_id, mode, basis, root, 'running', self.clock()))
            return self._ticket_json(db, db.execute('SELECT * FROM tickets WHERE id=?', (key,)).fetchone())

    def finish_ticket(self, actor, ticket_id):
        text(ticket_id, 'ticket ID', 100)
        with self.transaction() as db:
            self._ticket_ship(db, actor)
            row = require(db.execute('SELECT * FROM tickets WHERE id=? AND ship_id=?', (ticket_id, actor)).fetchone())
            if row['status'] == 'running':
                db.execute("UPDATE tickets SET status='finished',finished=? WHERE id=?", (self.clock(), ticket_id))
            return self._ticket_json(db, db.execute('SELECT * FROM tickets WHERE id=?', (ticket_id,)).fetchone())
