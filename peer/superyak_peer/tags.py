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

LABELS = ('invitation', 'activation')
TAG_BYTES = 16
CREDENTIAL_MAX = 128  # longer is refused before the HMAC
TAGGED = re.compile(r'(?P<random>[A-Za-z0-9_-]{43})\.(?P<kid>[0-9a-f]{8})\.(?P<exp>[0-9]{1,12})\.(?P<tag>[A-Za-z0-9_-]{22})')


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
    made = json.dumps({'kid': secrets.token_hex(4), 'key': _b64(secrets.token_bytes(32))})
    db.execute('INSERT OR IGNORE INTO system_meta(key, value) VALUES(?, ?)', (_meta_key(label), made))
    held = json.loads(db.execute('SELECT value FROM system_meta WHERE key=?', (_meta_key(label),)).fetchone()[0])
    return held['kid'], base64.urlsafe_b64decode(held['key'] + '=' * (-len(held['key']) % 4))


def minted(db, label, exp):
    """A new tagged `label` credential expiring at `exp`, under that label's key, made on `db` if missing: what each
    mint site calls inside its own transaction, in serve or in the CLI."""
    kid, key = label_key(db, label)
    return mint(label, key, kid, exp)


def every_label_key(db):
    """{label: {kid: key}} for every label, each made if missing: serve's start (create_app), before it answers."""
    return {label: dict([label_key(db, label)]) for label in LABELS}
