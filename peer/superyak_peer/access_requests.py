"""Anonymous account requests that only admins can turn into invitations."""
import hmac
import secrets
from .auth import token_hash
from .common import Problem, text, uid

REQUEST_LIFETIME = 604800
INVITATION_LIFETIME = 604800
# Behind `tailscale serve` every client shares one source, so the budget is global.
HOURLY_LIMIT = 20
PENDING_LIMIT = 50

ACCESS_SCHEMA = '''
CREATE TABLE IF NOT EXISTS access_requests(id TEXT PRIMARY KEY, name TEXT NOT NULL, contact TEXT NOT NULL, note TEXT NOT NULL, secret_hash TEXT NOT NULL, status TEXT NOT NULL, token TEXT, created REAL NOT NULL, expires REAL NOT NULL, decided_by TEXT REFERENCES users(id), decided REAL);
'''

def public_request(row, now):
    status = 'expired' if row['status'] == 'pending' and row['expires'] <= now else row['status']
    return {key: row[key] for key in ('id', 'name', 'contact', 'note', 'created', 'expires', 'decided_by', 'decided')} | {'status': status}


class AccessRequests:
    def request_access(self, name, contact, note):
        text(name, 'name')
        text(contact, 'contact')
        text(note, 'note', 2000, empty=True)
        with self.transaction() as db:
            now = self.clock()
            recent = db.execute('SELECT count(*) FROM access_requests WHERE created>?', (now - 3600,)).fetchone()[0]
            pending = db.execute("SELECT count(*) FROM access_requests WHERE status='pending' AND expires>?", (now,)).fetchone()[0]
            if recent >= HOURLY_LIMIT or pending >= PENDING_LIMIT:
                raise Problem(429, 'Too many access requests; try again later')
            key, secret = uid(), secrets.token_urlsafe(32)
            expires = now + REQUEST_LIFETIME
            db.execute(
                "INSERT INTO access_requests(id,name,contact,note,secret_hash,status,created,expires) VALUES(?,?,?,?,?,'pending',?,?)",
                (key, name, contact, note, token_hash(secret), now, expires),
            )
            return {'id': key, 'secret': secret, 'expires': expires}

    def access_request_status(self, key, secret):
        """Requester view; the approved invitation token is released exactly once."""
        with self.transaction() as db:
            row = db.execute('SELECT * FROM access_requests WHERE id=?', (key,)).fetchone()
            if not row or not isinstance(secret, str) or not hmac.compare_digest(token_hash(secret), row['secret_hash']):
                raise Problem(404, 'Not found')
            result = {'status': public_request(row, self.clock())['status'], 'expires': row['expires']}
            if row['token']:
                result['token'] = row['token']
                db.execute('UPDATE access_requests SET token=NULL WHERE id=?', (key,))
            return result

    def access_requests(self, actor):
        with self.transaction() as db:
            self._admin(db, actor)
            now = self.clock()
            return [public_request(row, now) for row in db.execute('SELECT * FROM access_requests ORDER BY created DESC LIMIT 100')]

    def decide_access_request(self, actor, key, approve):
        with self.transaction() as db:
            self._admin(db, actor)
            now = self.clock()
            row = db.execute('SELECT * FROM access_requests WHERE id=?', (key,)).fetchone()
            if not row:
                raise Problem(404, 'Not found')
            if public_request(row, now)['status'] != 'pending':
                raise Problem(409, 'This request was already decided or has expired')
            token = None
            if approve:
                token = secrets.token_urlsafe(32)
                db.execute('INSERT INTO invitations(token_hash,creator_id,expires) VALUES(?,?,?)', (token_hash(token), actor, now + INVITATION_LIFETIME))
            db.execute(
                'UPDATE access_requests SET status=?,token=?,decided_by=?,decided=? WHERE id=?',
                ('approved' if approve else 'denied', token, actor, now, key),
            )
            return public_request(db.execute('SELECT * FROM access_requests WHERE id=?', (key,)).fetchone(), now)

    def pending_access_requests(self):
        """Trusted local workers only; no HTTP route exposes this."""
        with self.transaction() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,name,created FROM access_requests WHERE status='pending' AND expires>? ORDER BY created",
                (self.clock(),),
            )]
