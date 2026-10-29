"""The remote connector (spec docs/superpowers/specs/2026-10-27-remote-connector-design.md): a person's home, read
from Claude through its own OAuth server and /mcp. Without `serve --public-origin`, none of it exists."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import unicodedata
from urllib.parse import urlsplit

from .common import Problem

DEFAULT_CALLBACK = 'https://claude.ai/api/mcp/auth_callback'  # claude.ai's; older help text said it may move to claude.com
SCOPES = ('rooms.read', 'offline_access')


def resource_metadata(issuer):
    """RFC 9728, at both protected-resource paths. offline_access stays out: MCP says resource servers SHOULD NOT list it."""
    return {'resource': issuer + '/mcp', 'authorization_servers': [issuer], 'bearer_methods_supported': ['header'],
            'scopes_supported': ['rooms.read']}


def issuer_metadata(issuer):
    """RFC 8414. code_challenge_methods_supported is required: without it MCP 2025-11-25 clients refuse to go on."""
    return {'issuer': issuer, 'authorization_endpoint': issuer + '/authorize', 'token_endpoint': issuer + '/token',
            'registration_endpoint': issuer + '/register', 'response_types_supported': ['code'],
            'grant_types_supported': ['authorization_code', 'refresh_token'],
            'token_endpoint_auth_methods_supported': ['none'], 'code_challenge_methods_supported': ['S256'],
            'scopes_supported': list(SCOPES), 'authorization_response_iss_parameter_supported': True}


# Registration (spec revision 4, "Registration (/register)", D18): stateless. A client id is its own record, signed with
# the home's key, and /register writes nothing. oauth_clients holds only clients a code has been issued to (Task 5);
# restore copies it as it is, since a client grants nothing by itself.
OAUTH_SCHEMA = '''
CREATE TABLE IF NOT EXISTS oauth_clients(client_id TEXT PRIMARY KEY, name TEXT, grant_types TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS connector_grants(id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES users(id), client_id TEXT NOT NULL, redirect_host TEXT NOT NULL, rooms TEXT NOT NULL, scope TEXT NOT NULL, created REAL NOT NULL, ends REAL NOT NULL, last_used REAL, revoked REAL);
CREATE TABLE IF NOT EXISTS oauth_pending(id TEXT PRIMARY KEY, request TEXT NOT NULL UNIQUE, client_id TEXT NOT NULL, redirect_uri TEXT NOT NULL, state TEXT, challenge TEXT NOT NULL, resource TEXT NOT NULL, scope TEXT NOT NULL, at INTEGER NOT NULL, person_id TEXT NOT NULL, csrf TEXT NOT NULL, decided REAL, code_hash TEXT, code_expires REAL, grant_id TEXT);
'''
# oauth_pending (Task 5): a request from its sign-in on, keyed by `request`, the SHA-256 of its fragment's tag, so one
# fragment is one row. `decided` is when Allow or Deny was chosen; the plan's columns had no mark for a Deny.
REGISTER_BODY_MAX = 8 * 1024  # bytes
CLIENT_NAME_MAX, CLIENT_NAME_BYTES = 100, 200
GRANT_TYPES = ('authorization_code', 'refresh_token')
CLIENT_VERSION = 1
KEY_NAME = 'connector_client_key'  # in system_meta: it protects what an id says, not a secret, so it is backed up


class OAuthError(Exception):
    """An OAuth refusal: the route answers its status with {"error": error} and nothing else."""

    def __init__(self, status, error):
        super().__init__(error)
        self.status, self.error = status, error


class RedirectError(OAuthError):
    """An authorization request refused after its client and redirect were checked: the route sends the browser back
    to that redirect with `error`, the request's `state` and `iss` (spec, "Then the rest")."""

    def __init__(self, error):
        super().__init__(303, error)


# The authorization request (spec revision 4, "The authorization request"): validated, then signed into the consent
# page's fragment with the home's key under its own label, and stored only at a good sign-in (D18).
PENDING_SECONDS = 600
STATE_MAX = 512  # characters; the state travels in the fragment, so it is bounded
CHALLENGE = re.compile(r'[A-Za-z0-9_-]{43}')  # an S256 challenge: base64url of SHA-256, unpadded (RFC 7636)


APP_NAMES = {'claude.ai': 'Claude', 'claude.com': 'Claude'}  # the consent page names an app by its redirect host
CODE_SECONDS = 60
DAYS_MAX = 30  # a connection lasts 1 to 30 days, 30 by default, never more (spec, "Tokens")
PENDING_FIELDS = ('v', 'client_id', 'redirect_uri', 'state', 'challenge', 'resource', 'scope', 'at')


def app_name(redirect_uri):
    """The app as the consent page names it: by its redirect host, never by its self-asserted client_name."""
    host = urlsplit(redirect_uri).hostname or ''
    return f'{APP_NAMES[host]} ({host})' if host in APP_NAMES else host


def _encoded(body):
    return json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def canonical_resource(value):
    """The resource with its scheme and host lowercased, as MCP asks a server to accept, or None if it isn't a plain
    https URL: no userinfo, query or fragment."""
    parts = urlsplit(value) if isinstance(value, str) else None
    if not parts or parts.username or parts.password or parts.query or parts.fragment or not parts.hostname:
        return None
    return f'{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path}'


def check_callback(callback):
    """The one redirect a client may register: an https URL with a host, and no query, fragment or userinfo, so a
    registered redirect is matched character for character (spec D14)."""
    parts = urlsplit(callback) if isinstance(callback, str) else None
    if (not parts or parts.scheme != 'https' or not parts.hostname or parts.query or parts.fragment or parts.username
            or parts.password or callback != callback.strip()):
        raise ValueError('The connector callback is an https URL with no query, fragment or userinfo')
    return callback


def client_fields_ok(name, grants):
    """/register's rules for what an id carries, checked again whenever an id is verified (a stolen key can't mint a
    payload /register would refuse): a name of at most 100 characters with no Cc, Cf, line break (Zl, Zp) or lone
    surrogate, and 200 bytes as the id carries it, after JSON escaping, so every id stays under 512 characters (Task
    4's re-check, MF1); and grant types within GRANT_TYPES, each once."""
    if name is not None:
        if not isinstance(name, str) or len(name) > CLIENT_NAME_MAX:
            return False
        if any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs', 'Zl', 'Zp') for c in name):
            return False
        if len(json.dumps(name, ensure_ascii=False).encode()) - 2 > CLIENT_NAME_BYTES:  # less its two quotes
            return False
    return (isinstance(grants, list) and bool(grants) and all(isinstance(g, str) for g in grants)
            and set(grants) <= set(GRANT_TYPES) and len(set(grants)) == len(grants))


def _client_payload(name, grants, issued_at):
    """The one encoding of a registration, which /register makes and an id's payload must equal byte for byte."""
    body = {'v': CLIENT_VERSION, 'grant_types': grants, 'issued_at': issued_at} | ({'name': name} if name is not None else {})
    return json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _unb64(text):
    """Strict unpadded base64url: anything that doesn't encode back to itself is None."""
    try:
        raw = base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))
    except (ValueError, TypeError):
        return None
    return raw if _b64(raw) == text else None


def _tag(key, label, body, callback=b''):
    return hmac.new(key, label + b'\n' + body + (b'\n' + callback if callback else b''), hashlib.sha256).digest()


class Connector:
    def _ensure_connector_key(self):
        """The key, 32 random bytes in system_meta, made at first start and kept in memory, so /register touches no
        table and takes no lock."""
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO system_meta VALUES(?, ?)', (KEY_NAME, secrets.token_hex(32)))
            self._connector_key = bytes.fromhex(db.execute('SELECT value FROM system_meta WHERE key=?',
                                                           (KEY_NAME,)).fetchone()[0])

    def register_client(self, metadata, callback):
        """Dynamic client registration (RFC 7591), stateless: exactly the one callback, a public client with no secret,
        and /register's field rules. Returns RFC 7591's response, whose client_id carries the registration."""
        if not isinstance(metadata, dict):
            raise OAuthError(400, 'invalid_client_metadata')
        if metadata.get('redirect_uris') != [callback]:
            raise OAuthError(400, 'invalid_redirect_uri')
        name = metadata.get('client_name')
        grants = metadata.get('grant_types', ['authorization_code'])
        if (not client_fields_ok(name, grants) or metadata.get('response_types', ['code']) != ['code']
                or metadata.get('token_endpoint_auth_method', 'none') != 'none'):
            raise OAuthError(400, 'invalid_client_metadata')
        now = int(self.clock())
        payload = _client_payload(name, grants, now)
        client_id = _b64(payload) + '.' + _b64(_tag(self._connector_key, b'client', payload, callback.encode()))
        made = {'client_id': client_id, 'client_id_issued_at': now, 'redirect_uris': [callback], 'grant_types': grants,
                'response_types': ['code'], 'token_endpoint_auth_method': 'none'}
        return made | ({'client_name': name} if name is not None else {})

    def check_client(self, client_id, redirect_uri, callback):
        """/authorize's first check: a known client, and its redirect equal to the one callback, character for
        character. One read transaction (it takes the store's gate, as every read does) and no write. A refusal is a
        page, never a redirect, so it raises OAuthError."""
        if not isinstance(redirect_uri, str) or redirect_uri != callback:
            raise OAuthError(400, 'invalid_request')
        with self.transaction() as db:
            known = self.known_client(db, client_id, callback)
        if known is None:
            raise OAuthError(400, 'invalid_client')
        return known

    def sign_pending(self, params, issuer, resource):
        """The rest of /authorize, once check_client passed: a code response, an S256 challenge, a bounded state, the
        canonical resource (or none) and scopes within SCOPES. Returns the consent page's fragment, the request signed
        with the key under the label `pending`; it writes nothing. A refusal raises RedirectError."""
        if params.get('response_type') != 'code':
            raise RedirectError('unsupported_response_type')
        if params.get('code_challenge_method') != 'S256' or not CHALLENGE.fullmatch(params.get('code_challenge') or ''):
            raise RedirectError('invalid_request')
        state = params.get('state')
        if state is not None and len(state) > STATE_MAX:
            raise RedirectError('invalid_request')
        if params.get('resource') is not None and canonical_resource(params['resource']) != resource:
            raise RedirectError('invalid_target')
        asked = params.get('scope')
        scopes = ['rooms.read'] if asked is None else asked.split(' ')
        if not scopes or not set(scopes) <= set(SCOPES):
            raise RedirectError('invalid_scope')
        body = {'v': CLIENT_VERSION, 'client_id': params['client_id'], 'redirect_uri': params['redirect_uri'],
                'state': state, 'challenge': params['code_challenge'], 'resource': resource,
                'scope': ' '.join(scope for scope in SCOPES if scope in scopes), 'at': int(self.clock())}
        request = _encoded(body)
        return _b64(request) + '.' + _b64(_tag(self._connector_key, b'pending', request))

    def pending_request(self, fragment, callback, resource):
        """The sign-in's first checks, before any password counts: the fragment's tag (compare_digest, under the label
        `pending`), its payload exactly as sign_pending encodes one, its age (PENDING_SECONDS from `at`), and then the
        request checked again from its own values as /authorize did: a known client, the configured callback, the
        canonical resource, scopes within SCOPES. So the key vouches only for what the home re-derives (Task 4's
        re-check, S2). Returns the request with `key`, the SHA-256 of its tag, and the client's `client_name`. A
        refusal raises OAuthError: 400 invalid_request, or 400 request_expired."""
        invalid = OAuthError(400, 'invalid_request')
        if not isinstance(fragment, str) or len(fragment) > 4096:
            raise invalid
        encoded, dot, mac = fragment.partition('.')
        raw, tag = _unb64(encoded), _unb64(mac)
        if not dot or raw is None or tag is None:
            raise invalid
        if not hmac.compare_digest(tag, _tag(self._connector_key, b'pending', raw)):
            raise invalid
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise invalid from None
        if not isinstance(body, dict) or set(body) != set(PENDING_FIELDS) or raw != _encoded(body):
            raise invalid
        state, scope = body['state'], body['scope']
        if (type(body['v']) is not int or body['v'] != CLIENT_VERSION or type(body['at']) is not int
                or not isinstance(body['client_id'], str) or not isinstance(body['challenge'], str)
                or not CHALLENGE.fullmatch(body['challenge']) or not (state is None or isinstance(state, str))
                or (state is not None and len(state) > STATE_MAX) or body['resource'] != resource
                or not isinstance(scope, str) or not scope
                # SCOPES' own spelling, which also refuses a name outside SCOPES
                or scope != ' '.join(name for name in SCOPES if name in scope.split(' '))):
            raise invalid
        age = self.clock() - body['at']
        if age < 0:
            raise invalid
        if age >= PENDING_SECONDS:
            raise OAuthError(400, 'request_expired')
        try:
            known = self.check_client(body['client_id'], body['redirect_uri'], callback)
        except OAuthError:
            raise invalid from None
        return body | {'key': hashlib.sha256(tag).hexdigest(), 'client_name': known['name']}

    def pending_sign_in(self, request, username, password, source, *, public=True, device=None):
        """The sign-in, after pending_request passed: the password checked and counted as /api/login counts it
        (check_password_attempt, which makes no session), and only then the row, keyed by the request so a second
        sign-in on one fragment rebinds that row's person and CSRF token. A row already decided refuses it. Returns the
        consent page's view, then sweeps. Refusals: 401 invalid_login, 429 too_many_attempts, 400 already_decided."""
        from .auth import token_hash
        try:
            right = self.check_password_attempt(username, password, source, public=public, device=device)
        except Problem as refused:
            raise OAuthError(429, 'too_many_attempts') if refused.status == 429 else OAuthError(400, 'invalid_request')
        if not right:
            raise OAuthError(401, 'invalid_login')
        csrf = secrets.token_urlsafe(32)
        with self.transaction() as db:
            user = db.execute("SELECT id, name FROM users WHERE username=? AND kind='person' AND activation_pending=0",
                              (username,)).fetchone()
            if user is None:  # changed since the password was checked
                raise OAuthError(401, 'invalid_login')
            row = db.execute('SELECT id, decided FROM oauth_pending WHERE request=?', (request['key'],)).fetchone()
            if row is not None and row['decided'] is not None:
                raise OAuthError(400, 'already_decided')
            if row is not None:
                pending = row['id']
                db.execute('UPDATE oauth_pending SET person_id=?, csrf=? WHERE id=?',
                           (user['id'], token_hash(csrf), pending))
            else:
                pending = secrets.token_urlsafe(16)
                db.execute('INSERT INTO oauth_pending(id, request, client_id, redirect_uri, state, challenge, '
                           'resource, scope, at, person_id, csrf) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (pending, request['key'], request['client_id'], request['redirect_uri'], request['state'],
                            request['challenge'], request['resource'], request['scope'], request['at'], user['id'],
                            token_hash(csrf)))
            rooms = self._consent_rooms(db, user['id'])
            self._connector_sweep(db)
        return {'pending': pending, 'csrf': csrf, 'name': user['name'], 'app': app_name(request['redirect_uri']),
                'client_name': request['client_name'], 'scope': request['scope'], 'rooms': rooms}

    def pending_decide(self, pending, csrf, allow, rooms, days=DAYS_MAX, *, issuer):
        """Allow or Deny, from the stored request only: its pending id and CSRF token (403 for a wrong token), within
        its ten minutes from /authorize, and once (400 already_decided after either). Deny sends access_denied. Allow
        takes the rooms chosen ("*" sent as itself, or current rooms of the person's that no member keeps away from
        cloud models, each once, at least one) and 1 to 30 days, makes the grant and a code (256 bits, 60 s, stored as
        a hash), and writes the client's oauth_clients row when it has none. Returns the URL to send the browser to,
        with the state and iss."""
        from urllib.parse import urlencode
        from .auth import token_hash
        if not isinstance(pending, str) or not isinstance(csrf, str) or type(allow) is not bool:
            raise OAuthError(400, 'invalid_request')
        with self.transaction() as db:
            now = self.clock()
            row = db.execute('SELECT * FROM oauth_pending WHERE id=?', (pending,)).fetchone()
            if row is None:
                raise OAuthError(400, 'invalid_request')
            if not hmac.compare_digest(row['csrf'], token_hash(csrf)):
                raise OAuthError(403, 'invalid_request')
            if row['decided'] is not None:
                raise OAuthError(400, 'already_decided')
            if now - row['at'] >= PENDING_SECONDS:
                raise OAuthError(400, 'request_expired')
            back = {'state': row['state']} if row['state'] is not None else {}
            if not allow:
                db.execute('UPDATE oauth_pending SET decided=? WHERE id=?', (now, pending))
                return row['redirect_uri'] + '?' + urlencode({'error': 'access_denied'} | back | {'iss': issuer})
            choosable = {room['room'] for room in self._consent_rooms(db, row['person_id'])
                         if room['earlier_of'] is None and not room['cloud']}
            if not (rooms == '*' or isinstance(rooms, list) and rooms and all(isinstance(room, str) for room in rooms)
                    and len(set(rooms)) == len(rooms) and set(rooms) <= choosable):
                raise OAuthError(400, 'invalid_request')
            if type(days) is not int or not 1 <= days <= DAYS_MAX:
                raise OAuthError(400, 'invalid_request')
            known = self.known_client(db, row['client_id'], row['redirect_uri'])
            if known is None:  # the key rotated or the callback changed since the sign-in
                raise OAuthError(400, 'invalid_request')
            grant, code = secrets.token_urlsafe(16), secrets.token_urlsafe(32)
            db.execute('INSERT INTO connector_grants(id, person_id, client_id, redirect_host, rooms, scope, created, ends) '
                       'VALUES(?,?,?,?,?,?,?,?)',
                       (grant, row['person_id'], row['client_id'], urlsplit(row['redirect_uri']).hostname,
                        '*' if rooms == '*' else json.dumps(rooms), row['scope'], now, now + days * 86400))
            db.execute('INSERT OR IGNORE INTO oauth_clients(client_id, name, grant_types, created) VALUES(?,?,?,?)',
                       (row['client_id'], known['name'], ' '.join(known['grant_types']), now))
            db.execute('UPDATE oauth_pending SET decided=?, code_hash=?, code_expires=?, grant_id=? WHERE id=?',
                       (now, token_hash(code), now + CODE_SECONDS, grant, pending))
        return row['redirect_uri'] + '?' + urlencode({'code': code} | back | {'iss': issuer})

    def _consent_rooms(self, db, person_id):
        """The person's rooms on this home as the consent page offers them: each current room, its earlier parts
        grouped under it as `earlier_of` (spec D9), and `cloud` where a member keeps it away from cloud models."""
        rows = db.execute('SELECT rooms.id, rooms.title FROM room_members JOIN rooms ON rooms.id=room_members.room_id '
                          'WHERE room_members.user_id=? ORDER BY rooms.title, rooms.id', (person_id,)).fetchall()
        current, earlier = [], {}
        for row in rows:
            later = self._current_room(db, row['id'])  # None for a current room
            entry = {'room': row['id'], 'title': row['title'], 'earlier_of': later,
                     'cloud': self._marked(db, row['id'])}
            (current.append(entry) if later is None else earlier.setdefault(later, []).append(entry))
        shown = []
        for entry in current:
            shown += [entry] + earlier.pop(entry['room'], [])
        return shown + [entry for rest in earlier.values() for entry in rest]

    def _connector_sweep(self, db):
        """Pending requests past their 10 minutes, unless a code issued from one is still live. Called only after a good
        sign-in, never by a request nobody signed in for (D18). Task 6 and Task 8 extend it."""
        now = self.clock()
        db.execute('DELETE FROM oauth_pending WHERE at<=? AND (code_expires IS NULL OR code_expires<=?)',
                   (now - PENDING_SECONDS, now))

    def known_client(self, db, client_id, callback):
        """Spec revision 4's one check, in order: a row with exactly this id is that client (so a key rotation or a
        callback change disconnects no one); otherwise the tag, compared with compare_digest, then the payload by
        /register's own rules, and equal to the payload /register itself makes from it, so an unknown version, a key it
        doesn't make, a repeated key or another spelling is unknown (Task 4's re-check, S1). Returns {client_id, name,
        grant_types}, or None for an unknown id."""
        if not isinstance(client_id, str) or len(client_id) > 512:  # longer than any id /register makes
            return None
        row = db.execute('SELECT name, grant_types FROM oauth_clients WHERE client_id=?', (client_id,)).fetchone()
        if row:
            return {'client_id': client_id, 'name': row['name'], 'grant_types': row['grant_types'].split()}
        encoded, dot, mac = client_id.partition('.')
        payload, tag = _unb64(encoded), _unb64(mac)
        if not dot or payload is None or tag is None:
            return None
        if not hmac.compare_digest(tag, _tag(self._connector_key, b'client', payload, callback.encode())):
            return None
        try:
            body = json.loads(payload)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return None
        if (not isinstance(body, dict) or type(body.get('issued_at')) is not int or body['issued_at'] < 0
                or not client_fields_ok(body.get('name'), body.get('grant_types'))
                or payload != _client_payload(body.get('name'), body['grant_types'], body['issued_at'])):
            return None
        return {'client_id': client_id, 'name': body.get('name'), 'grant_types': body['grant_types']}
