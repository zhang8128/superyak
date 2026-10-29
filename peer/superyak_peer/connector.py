"""The remote connector (spec docs/superpowers/specs/2026-10-27-remote-connector-design.md): a person's home, read
from Claude through its own OAuth server and /mcp. Without `serve --public-origin`, none of it exists."""
import base64
import hashlib
import hmac
import json
import secrets
import unicodedata
from urllib.parse import urlsplit

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
'''
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
    payload /register would refuse): a name of at most 100 characters and 200 bytes with no Cc, Cf or lone surrogate,
    and grant types within GRANT_TYPES, each once."""
    if name is not None:
        if not isinstance(name, str) or len(name) > CLIENT_NAME_MAX:
            return False
        try:
            if len(name.encode()) > CLIENT_NAME_BYTES:
                return False
        except UnicodeEncodeError:  # a lone surrogate
            return False
        if any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs') for c in name):
            return False
    return (isinstance(grants, list) and bool(grants) and all(isinstance(g, str) for g in grants)
            and set(grants) <= set(GRANT_TYPES) and len(set(grants)) == len(grants))


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
        body = {'v': CLIENT_VERSION, 'grant_types': grants, 'issued_at': now} | ({'name': name} if name is not None else {})
        payload = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        client_id = _b64(payload) + '.' + _b64(_tag(self._connector_key, b'client', payload, callback.encode()))
        made = {'client_id': client_id, 'client_id_issued_at': now, 'redirect_uris': [callback], 'grant_types': grants,
                'response_types': ['code'], 'token_endpoint_auth_method': 'none'}
        return made | ({'client_name': name} if name is not None else {})

    def known_client(self, db, client_id, callback):
        """Spec revision 4's one check, in order: a row with exactly this id is that client (so a key rotation or a
        callback change disconnects no one); otherwise the tag, compared with compare_digest, then the version and the
        payload by /register's own rules. Returns {client_id, name, grant_types}, or None for an unknown id."""
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
        if (not isinstance(body, dict) or body.get('v') != CLIENT_VERSION or type(body.get('issued_at')) is not int
                or not client_fields_ok(body.get('name'), body.get('grant_types'))):
            return None
        return {'client_id': client_id, 'name': body.get('name'), 'grant_types': body['grant_types']}
