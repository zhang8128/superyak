"""Ship status (docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md, S1-S4, S7): presence comes from
calls clients already make, written inside ship_for_key's transaction; "on watch" is a lease a session declares; the
directory shows each caller only what S7 allows."""
import re
from .common import Problem

LIVE_SECONDS = 120
PRESENCE_WRITE_SECONDS = 30
PRESENCE_IDLE_SECONDS = 86400
PRESENCE_ROWS_PER_SHIP = 100
WATCH_DEFAULT_MINUTES = 20
WATCH_MAX_MINUTES = 120
WATCH_SESSIONS_PER_SHIP = 10   # sessions on watch at once per ship (S4): pruning never removes one, so it is capped
ROUND_SECONDS = 900
SESSION = re.compile(r'[A-Za-z0-9._:-]{1,100}')
# The agent's version is client_version(): the checkout's commit as 12 hex digits, or 'unknown'. Nothing freer, so a
# branch name, a path or prompt text can't ride in on this header (R4).
CLIENT = re.compile(r'(hook|mcp)/(?:[0-9a-f]{12}|unknown)')
LABEL = re.compile(r'[A-Za-z0-9 ._:-]{1,40}')

PRESENCE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS presence(ship_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL, client TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'unknown', label TEXT, first_seen REAL NOT NULL, last_seen REAL NOT NULL,
  watch_minutes INTEGER, watch_writable INTEGER NOT NULL DEFAULT 0, watch_until REAL, PRIMARY KEY(ship_id, name));
'''


def parse_presence(headers):
    """The three headers as {name, client, mode}, or None without a usable session name. Malformed values are
    ignored, never refused (R3); `default` is the shared cursor name and never a session (R28)."""
    name = headers.get('x-superyak-session')
    if not isinstance(name, str) or not SESSION.fullmatch(name) or name == 'default':
        return None
    client = headers.get('x-superyak-client')
    mode = headers.get('x-superyak-mode')
    return {'name': name, 'client': client if isinstance(client, str) and CLIENT.fullmatch(client) else 'unknown',
            'mode': mode if mode in ('write', 'plan') else None}


class Presence:
    def _record_presence(self, db, ship_id, presence):
        """One write per session per PRESENCE_WRITE_SECONDS, in the caller's transaction. The write also renews a
        declared watch, but only one still running: an ended or lapsed watch is never revived (R6)."""
        now = self.clock()
        name = presence['name']
        row = db.execute('SELECT last_seen FROM presence WHERE ship_id=? AND name=?', (ship_id, name)).fetchone()
        if row is not None and now - row['last_seen'] < PRESENCE_WRITE_SECONDS:
            return
        if row is None:
            self._prune_presence(db, ship_id, now)
            if db.execute('SELECT count(*) FROM presence WHERE ship_id=?', (ship_id,)).fetchone()[0] >= PRESENCE_ROWS_PER_SHIP:
                return  # every row left is on watch: presence is best effort, so this session goes unrecorded (S2)
            db.execute('INSERT INTO presence(ship_id,name,client,mode,first_seen,last_seen) VALUES(?,?,?,?,?,?)',
                       (ship_id, name, presence['client'], presence['mode'] or 'unknown', now, now))
        else:
            db.execute('UPDATE presence SET last_seen=?, client=?, mode=COALESCE(?, mode) WHERE ship_id=? AND name=?',
                       (now, presence['client'], presence['mode'], ship_id, name))
        db.execute('UPDATE presence SET watch_until=?+watch_minutes*60 WHERE ship_id=? AND name=? '
                   'AND watch_minutes IS NOT NULL AND watch_until>?', (now, ship_id, name, now))

    def _prune_presence(self, db, ship_id, now):
        db.execute('DELETE FROM presence WHERE ship_id=? AND last_seen<? AND NOT COALESCE(watch_until>?, 0)',
                   (ship_id, now - PRESENCE_IDLE_SECONDS, now))
        over = db.execute('SELECT count(*) FROM presence WHERE ship_id=?', (ship_id,)).fetchone()[0] - PRESENCE_ROWS_PER_SHIP + 1
        if over > 0:  # the least recently seen go first, never a session on watch
            db.execute('''DELETE FROM presence WHERE rowid IN (SELECT rowid FROM presence WHERE ship_id=?
                          AND NOT COALESCE(watch_until>?, 0) ORDER BY last_seen LIMIT ?)''', (ship_id, now, over))

    def _writable_on_watch(self, db, ship_id):
        return db.execute('SELECT 1 FROM presence WHERE ship_id=? AND watch_writable=1 AND watch_until>?',
                          (ship_id, self.clock())).fetchone() is not None

    def _session_on_watch(self, db, ship_id, name):
        return db.execute('SELECT 1 FROM presence WHERE ship_id=? AND name=? AND watch_until>?',
                          (ship_id, name, self.clock())).fetchone() is not None

    def station_watch(self, ship_id, presence, minutes=None, writable=False, label=None):
        """S4: declare a watch (1-120 minutes, default 20), declare again to change it, or end it with 0. Only a named
        session can watch (R6): the header names it, and a run sends none."""
        if presence is None:
            raise Problem(400, "Watching needs this session's name in the x-superyak-session header")
        minutes = WATCH_DEFAULT_MINUTES if minutes is None else minutes
        if type(minutes) is not int or not 0 <= minutes <= WATCH_MAX_MINUTES:
            raise Problem(400, f'minutes is a whole number from 0 to {WATCH_MAX_MINUTES}')
        if type(writable) is not bool:
            raise Problem(400, 'writable is true or false')
        if label is not None and (not isinstance(label, str) or not LABEL.fullmatch(label)):
            raise Problem(400, 'A label is 1-40 letters, digits, spaces, dots, colons, dashes or underscores')
        with self.transaction() as db:
            now, name = self.clock(), presence['name']
            if minutes and db.execute('SELECT count(*) FROM presence WHERE ship_id=? AND name!=? AND watch_until>?',
                                      (ship_id, name, now)).fetchone()[0] >= WATCH_SESSIONS_PER_SHIP:
                raise Problem(429, f'A ship can have at most {WATCH_SESSIONS_PER_SHIP} sessions on watch; end one first')
            if db.execute('SELECT 1 FROM presence WHERE ship_id=? AND name=?', (ship_id, name)).fetchone() is None:
                self._record_presence(db, ship_id, presence)
                if db.execute('SELECT 1 FROM presence WHERE ship_id=? AND name=?', (ship_id, name)).fetchone() is None:
                    raise Problem(429, f'This ship already has {PRESENCE_ROWS_PER_SHIP} sessions recorded, all on watch')
            if minutes == 0:
                db.execute('UPDATE presence SET watch_minutes=NULL, watch_until=NULL, watch_writable=0 WHERE ship_id=? AND name=?',
                           (ship_id, name))
            else:
                db.execute('UPDATE presence SET watch_minutes=?, watch_writable=?, watch_until=?, label=COALESCE(?, label) '
                           'WHERE ship_id=? AND name=?', (minutes, int(writable), now + minutes * 60, label, ship_id, name))
            row = db.execute('SELECT * FROM presence WHERE ship_id=? AND name=?', (ship_id, name)).fetchone()
            return {'name': name, 'on_watch': (row['watch_until'] or 0) > now, 'watch_until': row['watch_until'],
                    'writable': bool(row['watch_writable']), 'label': row['label']}

    def directory(self, actor):
        """S7: the caller's own ships and every ship sharing a local room with it; everything to the ship itself, its
        owner and an admin; three ship-level fields to co-members, last_seen rounded down to 15 minutes."""
        with self.transaction() as db:
            me = db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone()
            if me['kind'] == 'ship':
                self._inbox_budget(actor)
            admin = me['kind'] == 'person' and bool(me['is_admin'])
            ships = db.execute("""SELECT ships.*, owners.name AS owner_name FROM users AS ships
                LEFT JOIN users AS owners ON owners.id=ships.owner_id WHERE ships.kind='ship' AND (? OR ships.id=?
                OR ships.owner_id=? OR ships.id IN (SELECT b.user_id FROM room_members AS a JOIN room_members AS b
                ON a.room_id=b.room_id WHERE a.user_id=? AND a.room_id NOT LIKE '%:%')) ORDER BY ships.created, ships.id""",
                (admin, actor, actor, actor)).fetchall()
            return [self._directory_row(db, ship, admin or ship['id'] == actor or ship['owner_id'] == actor)
                    for ship in ships]

    def _directory_row(self, db, ship, full):
        now = self.clock()
        sessions = db.execute('SELECT * FROM presence WHERE ship_id=? ORDER BY name', (ship['id'],)).fetchall()
        runs = [t for t in db.execute('SELECT * FROM tickets WHERE ship_id=? AND status=?', (ship['id'], 'running'))
                if self._ticket_running(t)]
        key_seen = db.execute('SELECT MAX(last_used) FROM ship_keys WHERE ship_id=?', (ship['id'],)).fetchone()[0]
        seen = max([s['last_seen'] for s in sessions] + [t['created'] for t in runs] + [key_seen or 0.0])
        row = {'id': ship['id'], 'username': ship['username'], 'name': ship['name'], 'owner_name': ship['owner_name'],
               'writable_on_watch': any(s['watch_writable'] and (s['watch_until'] or 0) > now for s in sessions),
               'live_runs': len(runs), 'last_seen': seen if full else seen - seen % ROUND_SECONDS}
        if full:
            machine = db.execute('SELECT machine FROM dockings WHERE ship_id=? ORDER BY created DESC LIMIT 1',
                                 (ship['id'],)).fetchone()
            row['machine'] = machine['machine'] if machine else None
            row['sessions'] = [{'name': s['name'], 'label': s['label'], 'client': s['client'], 'mode': s['mode'],
                                'live': now - s['last_seen'] <= LIVE_SECONDS, 'on_watch': (s['watch_until'] or 0) > now,
                                'watch_until': s['watch_until'], 'first_seen': s['first_seen'], 'last_seen': s['last_seen']}
                               for s in sessions]
            row['runs'] = [{'mode': t['mode'], 'started': t['created']} for t in runs]
        return row
