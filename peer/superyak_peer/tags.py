"""The public-route-bound plan, Task 7a: tags on the credentials another process mints.

Invitations (auth.invite in serve, the access-request approval in serve and in the CLI) and activations (the first
super admin's, from the CLI) are minted where serve's live set can't see them. So each carries a tag that serve can
check in memory, before any read or lock (Task 7b): `<random>.<kid>.<exp>.<tag>`, where `random` is 43 URL-safe
characters, `kid` names the label's key, `exp` is the unix second it expires, and `tag` is HMAC-SHA256 under that key
over the label and the rest, truncated to 16 bytes and base64url'd. The label is in the MAC, so an invitation's tag
never passes as an activation's.

Each label's key lives in system_meta, with its kid. Serve makes any missing one at start, before it answers, and a
CLI mint command makes it in its own transaction if it's missing (INSERT OR IGNORE under the gate, then a re-read), so
a CLI and a serve racing on a fresh dir both use the winner. Only a restore with serve stopped deletes one, so serve's
next start loads any key the CLI made. The keys load only in serve and in those commands, never in Store.__init__.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import threading

LABELS = ('invitation', 'activation')
LONGEST = 604800  # the longest lifetime any mint site gives (invite's limit, an approval's and an activation's), seconds
TAG_BYTES = 16
CREDENTIAL_MAX = 128  # longer is refused before the HMAC
# exp is canonical, no leading zero, sign, space or underscore, so one tag has one spelling and one hash (the Task 7a
# reader's S1): int() would read '0123', '+123' and '1_23' as the numbers the MAC covers
TAGGED = re.compile(r'(?P<random>[A-Za-z0-9_-]{43})\.(?P<kid>[0-9a-f]{8})\.(?P<exp>[1-9][0-9]{0,11})\.(?P<tag>[A-Za-z0-9_-]{22})')
KID = re.compile(r'[0-9a-f]{8}')
KEY_BYTES = 32


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _tag(label, key, random, kid, exp):
    mac = hmac.new(key, f'{label}.{random}.{kid}.{exp}'.encode(), hashlib.sha256).digest()
    return _b64(mac[:TAG_BYTES])


def mint(label, key, kid, exp):
    """A new tagged credential for `label`, signed with (`kid`, `key`), expiring at `exp` (rounded down to the second)."""
    if label not in LABELS:
        raise ValueError(f'not a tag label: {label}')
    random, exp = secrets.token_urlsafe(32), int(exp)
    return f'{random}.{kid}.{exp}.{_tag(label, key, random, kid, exp)}'


def check(label, keys, credential, now):
    """Whether `credential` is a tagged `label` credential under one of `keys` ({kid: key}, this label's only), unexpired
    at `now`. A credential over CREDENTIAL_MAX, of another shape, an unknown kid or another label's tag is False, with no
    store read; the length is checked before anything else."""
    if not isinstance(credential, str) or len(credential) > CREDENTIAL_MAX:
        return False
    parts = TAGGED.fullmatch(credential)
    if parts is None or parts['kid'] not in keys or int(parts['exp']) <= now:
        return False
    expected = _tag(label, keys[parts['kid']], parts['random'], parts['kid'], int(parts['exp']))
    return hmac.compare_digest(expected, parts['tag'])


def _meta_key(label):
    return f'tag_key:{label}'


def label_key(db, label):
    """(kid, key) for `label`, made on `db` (a transaction, under the gate) if it's missing: INSERT OR IGNORE, then a
    re-read, so two processes making it at once both get the one that won."""
    if label not in LABELS:
        raise ValueError(f'not a tag label: {label}')
    made = json.dumps({'kid': secrets.token_hex(4), 'key': _b64(secrets.token_bytes(KEY_BYTES))})
    db.execute('INSERT OR IGNORE INTO system_meta(key, value) VALUES(?, ?)', (_meta_key(label), made))
    row = db.execute('SELECT value FROM system_meta WHERE key=?', (_meta_key(label),)).fetchone()[0]
    return _valid(label, row)


def _valid(label, row):
    """A key row checked before it's used (the Task 7a reader's N1): a bad kid would fail every new credential without a
    word, and a short key would weaken every tag. The error names the row, never its key."""
    try:
        held = json.loads(row)
        kid, encoded = held['kid'], held['key']
        key = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)) if isinstance(encoded, str) else b''
    except (ValueError, TypeError, KeyError):
        kid, key = None, b''
    if not (isinstance(kid, str) and KID.fullmatch(kid)) or len(key) != KEY_BYTES:
        raise ValueError(f'system_meta row {_meta_key(label)} is not a {KEY_BYTES}-byte tag key with an 8-hex kid; '
                         'a restore with serve stopped may delete it, and serve then makes a new one')
    return kid, key


def minted(db, label, exp):
    """A new tagged `label` credential expiring at `exp`, under that label's key, made on `db` if missing: what each
    mint site calls inside its own transaction, in serve or in the CLI."""
    kid, key = label_key(db, label)
    return mint(label, key, kid, exp)


UNTAGGED = re.compile(r'[A-Za-z0-9_-]{43}')  # an invitation or activation made before the deploy (Task 7b)


def _hashed(token):
    return hashlib.sha256(token.encode()).hexdigest()  # auth.token_hash, which imports this module


class StartSet:
    """Task 7b: the untagged invitations and activations that were live when serve started, by hash and label. It
    is loaded once, in create_app, and only shrinks, on a successful redeem or on a lookup that finds no live row, so a
    credential made before the deploy redeems once and a made-up 43-character one is refused unread."""
    def __init__(self):
        self._lock = threading.Lock()
        self._labels = {}

    def load(self, db, now):
        labels = {}
        for label, table in (('invitation', 'invitations'), ('activation', 'account_activations')):
            for (hashed,) in db.execute(f'SELECT token_hash FROM {table} WHERE used=0 AND expires>?', (now,)):
                labels[hashed] = label
        with self._lock:
            self._labels = labels
        return len(labels)

    def label(self, hashed):
        with self._lock:
            return self._labels.get(hashed)

    def discard(self, hashed):
        with self._lock:
            self._labels.pop(hashed, None)


class SpentSet:
    """Task 7b (the reader's D1): tagged credentials that can redeem nothing more, by hash until their exp: entered at
    serve's own redeem commit, or at a lookup that finds no live row (used elsewhere, or marked used by a restore). So a
    used one replayed costs one read at most, then none until its exp, as revision 4 set the bar. Only a credential
    with a valid tag enters, and only an admin or the CLI mints those, so a stranger can't grow it."""
    SWEEP_AT = 64  # the first size at which an add drops the expired; then twice what's left (the re-check's S1)

    def __init__(self):
        self._lock = threading.Lock()
        self._exps = {}
        self._sweep_at = self.SWEEP_AT

    def add(self, hashed, exp, now):
        with self._lock:
            self._exps[hashed] = exp
            if len(self._exps) >= self._sweep_at:  # a sweep when the set doubles, not a copy on every add
                self._exps = {held: until for held, until in self._exps.items() if until > now}
                self._sweep_at = max(self.SWEEP_AT, 2 * len(self._exps))

    def spent(self, hashed, now):
        with self._lock:
            exp = self._exps.get(hashed)
            if exp is not None and exp <= now:
                del self._exps[hashed]
                return False
            return exp is not None

    def __len__(self):
        with self._lock:
            return len(self._exps)


def redeemable(keys, untagged, spent, token, now):
    """Task 7b, before redeem's lane: the label a public redeem may look up, or None. A tagged token under its label's
    key, unexpired and not spent, or an untagged one the start-time set holds. In memory: no read, no lock, no place in
    the lane."""
    if not isinstance(token, str) or len(token) > CREDENTIAL_MAX:
        return None
    if UNTAGGED.fullmatch(token):
        return untagged.label(_hashed(token))
    label = next((label for label in LABELS if check(label, keys[label], token, now)), None)
    return None if label is None or spent.spent(_hashed(token), now) else label


def every_label_key(db):
    """{label: {kid: key}} for every label, each made if missing: serve's start (create_app), before it answers."""
    return {label: dict([label_key(db, label)]) for label in LABELS}
