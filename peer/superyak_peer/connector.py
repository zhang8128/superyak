"""The remote connector (spec docs/superpowers/specs/2026-10-27-remote-connector-design.md): a person's home, read
from Claude through its own OAuth server and /mcp. Without `serve --public-origin`, none of it exists."""
import ipaddress
import secrets
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


# Registration (spec "Registration (/register)", plan Task 4). Each table comes with the task that uses it, and so does
# its place in the restore reconcile: clients are interchangeable public registrations that grant nothing.
OAUTH_SCHEMA = '''
CREATE TABLE IF NOT EXISTS oauth_clients(client_id TEXT PRIMARY KEY, name TEXT, redirect_uri TEXT NOT NULL, grant_types TEXT NOT NULL, created REAL NOT NULL, source TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS oauth_clients_by_source ON oauth_clients(source, created);
'''
REGISTER_BODY_MAX = 8 * 1024
CLIENT_NAME_MAX = 100
UNUSED_CLIENTS_MAX = 100  # at the cap the oldest unused one goes, never the new one: unused ones are interchangeable
UNUSED_CLIENT_SECONDS = 86400
REGISTRATIONS_PER_HOUR = 10  # per sender; a number the spec leaves open (plan Task 4)
REGISTRATIONS_PER_HOUR_48 = 30  # per IPv6 /48 across its /64s (the second security review of 8420194d)
GRANT_TYPES = ('authorization_code', 'refresh_token')


def sender(source):
    """Whom the per-source limit counts: an IPv6 sender by its /64, since one /64 holds countless addresses (a security
    review of 5dd19d4c); an IPv4-mapped, 6to4 or Teredo address as the IPv4 sender inside it (the second review);
    anything else as given."""
    try:
        address = ipaddress.ip_address(source)
    except ValueError:
        return source
    if address.version == 6:
        inside = address.ipv4_mapped or address.sixtofour or (address.teredo[1] if address.teredo else None)
        if inside:
            return str(inside)
        return str(ipaddress.ip_network(f'{address}/64', strict=False))
    return str(address)


def allocation(sender_key):
    """The coarser key a sender's /64 belongs to: its /48, since an allocation is often one (the second review); an IPv4
    sender is its own."""
    if '/' not in sender_key:
        return sender_key
    return str(ipaddress.ip_network(sender_key).supernet(new_prefix=48))


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


class Connector:
    def _connector_sweep(self, db):
        """What the connector keeps only for a while, swept before each registration (later tasks add theirs): an
        unused registration after a day."""
        db.execute('DELETE FROM oauth_clients WHERE used=0 AND created<?', (self.clock() - UNUSED_CLIENT_SECONDS,))

    def register_client(self, metadata, source, callback):
        """Dynamic client registration (RFC 7591), bounded: exactly the one callback, a public client with no secret,
        grant types within authorization_code and refresh_token, a client_name of at most 100 characters kept only as
        quoted data. At most REGISTRATIONS_PER_HOUR from one source, and at UNUSED_CLIENTS_MAX unused the oldest unused
        one is evicted. Returns RFC 7591's response."""
        if not isinstance(metadata, dict):
            raise OAuthError(400, 'invalid_client_metadata')
        if metadata.get('redirect_uris') != [callback]:
            raise OAuthError(400, 'invalid_redirect_uri')
        name = metadata.get('client_name')
        grants = metadata.get('grant_types', ['authorization_code'])
        if ((name is not None and (not isinstance(name, str) or len(name) > CLIENT_NAME_MAX))
                or not isinstance(grants, list) or not grants or not all(isinstance(g, str) for g in grants)
                or not set(grants) <= set(GRANT_TYPES) or len(set(grants)) != len(grants)
                or metadata.get('response_types', ['code']) != ['code']
                or metadata.get('token_endpoint_auth_method', 'none') != 'none'):
            raise OAuthError(400, 'invalid_client_metadata')
        source = sender(source)
        with self.transaction() as db:
            self._connector_sweep(db)
            now = self.clock()
            recent = [row[0] for row in db.execute('SELECT source FROM oauth_clients WHERE created>?', (now - 3600,))]
            coarse = allocation(source)
            if (recent.count(source) >= REGISTRATIONS_PER_HOUR
                    or (coarse != source and sum(allocation(s) == coarse for s in recent) >= REGISTRATIONS_PER_HOUR_48)):
                raise OAuthError(429, 'slow_down')
            unused = db.execute('SELECT count(*) FROM oauth_clients WHERE used=0').fetchone()[0]
            if unused >= UNUSED_CLIENTS_MAX:
                db.execute('DELETE FROM oauth_clients WHERE client_id IN (SELECT client_id FROM oauth_clients WHERE used=0 '
                           'ORDER BY created, rowid LIMIT ?)', (unused - UNUSED_CLIENTS_MAX + 1,))
            client_id = secrets.token_urlsafe(24)
            db.execute('INSERT INTO oauth_clients VALUES(?,?,?,?,?,?,0)',
                       (client_id, name, callback, ' '.join(grants), now, source))
        made = {'client_id': client_id, 'client_id_issued_at': int(now), 'redirect_uris': [callback], 'grant_types': grants,
                'response_types': ['code'], 'token_endpoint_auth_method': 'none'}
        return made | ({'client_name': name} if name is not None else {})
