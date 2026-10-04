"""Ship-side station client and the machine's private ship configuration."""
import http.client
import json
import os
from pathlib import Path
from urllib.parse import quote
import urllib.error
import urllib.request

HOME = Path.home() / '.superyak'
CONFIG = HOME / 'station.json'


class StationError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(f'{status}: {message}')


def urllib_transport(timeout=30):
    def send(method, url, headers, data):
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except http.client.HTTPException as error:
            # A proxy or station that speaks broken HTTP is an unreachable station, not a crash.
            raise OSError(f'malformed response from the station: {error!r}') from error
    return send


class StationClient:
    """HTTP client for one ship. `origin` is the station's public origin when `base_url` is the
    loopback address behind `tailscale serve` (Odo on the Pi)."""
    def __init__(self, base_url, key=None, origin=None, transport=None):
        self.base = base_url.rstrip('/')
        self.origin = (origin or self.base).rstrip('/')
        self.key, self.transport = key, transport or urllib_transport()

    def request(self, method, path, body=None):
        headers = {'origin': self.origin, 'accept': 'application/json'}
        if self.origin != self.base:
            scheme, _, host = self.origin.partition('://')
            headers.update({'host': host, 'x-forwarded-proto': scheme})
        if self.key:
            headers['authorization'] = f'Bearer {self.key}'
        data = None
        if body is not None:
            headers['content-type'] = 'application/json'
            data = json.dumps(body).encode()
        status, raw = self.transport(method, self.base + path, headers, data)
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = None
        if status >= 400:
            message = payload.get('error') if isinstance(payload, dict) else None
            raise StationError(status, message or f'HTTP {status}')
        if payload is None:
            # Every route a ship may use answers with JSON; an empty or non-JSON success is not one.
            raise StationError(status, 'Unexpected response from the station')
        return payload

    def me(self):
        return self.request('GET', '/api/me')

    def rooms(self):
        return self.request('GET', '/api/chats')

    def room(self, room_id):
        return self.request('GET', f'/api/chats/{quote(room_id, safe="")}')

    def post(self, room_id, body, client_message_id):
        return self.request('POST', f'/api/chats/{quote(room_id, safe="")}/messages', {'client_message_id': client_message_id, 'body': body})

    def mentions(self, after=0):
        return self.request('GET', f'/api/mentions?after={int(after)}')

    def revoke_key(self):
        return self.request('DELETE', '/api/ships/me/key')


def _replace_private(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(text)
    os.replace(tmp, path)


def write_private(path, value):
    _replace_private(path, json.dumps(value, indent=2) + '\n')


def write_private_text(path, text):
    _replace_private(path, text.rstrip('\n') + '\n')


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def load_config(path=CONFIG):
    config = read_json(path)
    if not config or not config.get('key') or not config.get('station'):
        raise SystemExit(f'No docked ship at {path}. Run `make dock` first.')
    return config


def client_for(config, timeout=30):
    return StationClient(config['station'], config['key'], config.get('origin'), urllib_transport(timeout))


def label(text, limit=80):
    """Collapse text from the station (a display name, a room title) to one short printable line,
    so it can sit in a header without breaking out of it: no newlines, control or format
    characters, and no backticks to open or close a fence."""
    text = '' if text is None else str(text)
    text = ''.join(c if c.isprintable() else ' ' for c in text).replace('`', '')
    return ' '.join(text.split())[:limit].strip() or 'unknown'


def describe(member):
    member = member or {'name': 'someone', 'username': 'unknown', 'kind': 'unknown'}
    return f'{label(member.get("name"))} (@{label(member.get("username"))}, {label(member.get("kind"))})'
