"""The public-route-bound plan, Task 2: serve's live set, the credentials it knows to have a live row.

PublicRoute (Task 3) asks the set before the store, so a junk credential costs no read. Membership means a live row
exists, or did when the set last heard: a session or device row unexpired, a ship key unrevoked on a ship account. A
stale entry is the safe direction, since the route still looks the credential up and a lookup that finds no live row
takes it out; a missing entry would refuse a real person. So the set is loaded once, in create_app, before serve
answers, and serve is the only minter of sessions and devices (Store.login, from serve's sign-in route only), which
puts each change it commits into the set before its cookie leaves (change C). Ship keys made by the CLI after the load
reach the set through the public miss lane (Task 3).

Keys are (kind, hash): a hash is a token's, as auth.token_hash makes it, and never the token itself.
"""
import math
import threading

KINDS = ('session', 'device', 'ship_key')


class LiveSet:
    def __init__(self):
        self._lock = threading.Lock()
        self._rows = {}  # (kind, hash) -> (exp, user_id); a ship key's exp is infinite, as it lasts until revoked

    def load_live_rows(self, store):
        """Every live row of the three tables, read in one snapshot (store.reading(), so in WAL it waits for no
        writer), replacing what the set held. Returns how many it holds. The plan's load(db), named so that the
        moved-reads walk, which matches methods by name, never takes another `.load` for it."""
        rows = {}
        with store.reading() as db:
            now = store.clock()
            for token, user, exp in db.execute('SELECT token_hash, user_id, expires FROM sessions WHERE expires>?', (now,)):
                rows['session', token] = (exp, user)
            for token, user, exp in db.execute('SELECT token_hash, user_id, expires FROM login_devices WHERE expires>?', (now,)):
                rows['device', token] = (exp, user)
            for token, user in db.execute("SELECT key_hash, ship_id FROM ship_keys JOIN users ON users.id=ship_keys.ship_id "
                                          "WHERE revoked IS NULL AND users.kind='ship'"):
                rows['ship_key', token] = (math.inf, user)
        with self._lock:
            self._rows = rows
        return len(rows)

    def has(self, token, kind, now):
        """Whether the set holds this hash as this kind, unexpired at `now`."""
        with self._lock:
            row = self._rows.get((kind, token))
        return row is not None and row[0] > now

    def add(self, kind, token, exp, user_id):
        self.apply([('add', kind, token, exp, user_id)])

    def remove(self, kind, token):
        self.apply([('remove', kind, token)])

    def apply(self, changes):
        """Changes gathered in a committed transaction, applied together, in order, under the lock: ('add', kind, hash,
        exp, user_id), which also sets a new exp on an entry the set holds (a device's extension, which may have left
        the set as expired: the plan's set_exp, as an upsert), or ('remove', kind, hash). An add keeps the later of
        the two exps: two sign-ins extending one device can apply out of their commits' order, and the earlier exp
        must not win (the Tasks 2-3 reader's N1)."""
        with self._lock:
            for change in changes:
                verb, kind, token = change[:3]
                if kind not in KINDS:
                    raise ValueError(f'not a live-set kind: {kind}')
                if verb == 'add':
                    held = self._rows.get((kind, token))
                    self._rows[kind, token] = (change[3] if held is None else max(held[0], change[3]), change[4])
                elif verb == 'remove':
                    self._rows.pop((kind, token), None)
                else:
                    raise ValueError(f'not a live-set change: {verb}')

    def __len__(self):
        with self._lock:
            return len(self._rows)
