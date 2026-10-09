"""Ship-side station client and the machine's private ship configuration."""
import http.client
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import quote
import urllib.error
import urllib.request
from superyak_team.teamlib import fence_external

HOME = Path.home() / '.superyak'
MESSAGE_LIMIT = 20000  # the station's longest message
PLAIN_ID = re.compile(r'[A-Za-z0-9:_.-]{1,200}')
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

    def post(self, room_id, body, client_message_id, ticket_id=None, reply_to=None):
        payload = {'client_message_id': client_message_id, 'body': body}
        if ticket_id:
            payload['ticket_id'] = ticket_id
        if reply_to:
            payload['reply_to'] = reply_to
        return self.request('POST', f'/api/chats/{quote(room_id, safe="")}/messages', payload)

    def unread(self, cursor, limit=30, wait=0):
        return self.request('POST', '/api/ships/me/unread', {'cursor': cursor, 'limit': limit, 'wait': wait})

    def advance(self, cursor, to):
        return self.request('POST', '/api/ships/me/unread/advance', {'cursor': cursor, 'to': to})

    def ticket(self, message_id):
        return self.request('POST', '/api/ships/me/tickets', {'message_id': message_id})

    def finish_ticket(self, ticket_id):
        return self.request('POST', f'/api/ships/me/tickets/{quote(ticket_id, safe="")}/finish', {})

    def instructions(self):
        return self.request('GET', '/api/ships/me/instructions')

    def draft_instructions(self, title, body):
        return self.request('POST', '/api/ships/me/drafts', {'title': title, 'body': body})

    def mentions(self, after=0):
        return self.request('GET', f'/api/mentions?after={int(after)}')

    def revoke_key(self):
        return self.request('DELETE', '/api/ships/me/key')


def _replace_private(path, text):
    """Replace `path` with `text`, 0600, never leaving a half-written file in its place. Each writer
    gets its own temp file in the same directory, so two concurrent writers (two hook runs) cannot
    interleave; whichever replaces last wins, and either result is complete."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.', suffix='.tmp')
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


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


def plain_id(value):
    """Only an id of plain characters is written into a call an agent can copy: a remote peer chooses its own
    message ids, and one with spaces or brackets could break the call or write text outside the fence."""
    return isinstance(value, str) and PLAIN_ID.fullmatch(value) is not None


def shown_id(value):
    return value if plain_id(value) else '(an id with unusual characters)'


def read_hint(room_id, message_id, position=None):
    """The cut note's way back to the whole message: one call that returns just that message. By id when the id
    is plain; by its position in the room when not (a remote peer chooses its own ids); otherwise no call."""
    if not plain_id(room_id):
        return ''
    if plain_id(message_id):
        return f'; `station_read room={room_id} message={message_id}` shows all of it'
    if position is not None:
        return f'; `station_read room={room_id} at={int(position)} limit=1 max_chars={MESSAGE_LIMIT}` shows all of it'
    return ''


def source_label(message):
    """Where a ship's message came from, as the station recorded it from a ticket; never a client's own claim.
    Older watchers' replies have no ticket, so the label says only that: no run ticket."""
    source = message.get('source') if isinstance(message, dict) else None
    if not isinstance(source, dict):
        return ''
    if source.get('kind') == 'run':
        if source.get('mode') == 'build':
            return f'builder run for {label(source["root_name"])}' if source.get('root_name') else 'builder run'
        return 'read-only run'
    return 'no run ticket' if source.get('kind') == 'post' else ''


def defuse(text):
    """Line breaks normalised, and every line that starts like an instruction header (`===`) or a withdrawal
    (`Instructions '`) indented by a space, so no room message can imitate the law."""
    return '\n'.join(' ' + line if line.startswith(('===', "Instructions '")) else line for line in text.splitlines())


def fence_message(member, body, limit, hint='', source=''):
    """A message fenced as quoted data, at most `limit` characters of it. A cut is said after the fence,
    where the author's text cannot imitate it, so a reader never mistakes part of a message for all of it."""
    sender = describe(member) + (f', {source}' if source else '')
    quoted = defuse(body[:limit])
    text = fence_external(sender, quoted, limit=max(len(quoted), 1))
    return text + f'\n[cut at {limit:,} of {len(body):,} characters{hint}]' if len(body) > limit else text


def brief_date(updated):
    """A brief's `updated` (Unix seconds from the station) as a UTC date."""
    try:
        return time.strftime('%Y-%m-%d', time.gmtime(float(updated)))
    except (TypeError, ValueError, OverflowError, OSError):
        return 'unknown'


def brief_block(room):
    """The room's brief, whole, under one header line, and fenced like any message (defused, never cut): the owner
    wrote it about the room, and it is quoted data, never instructions. '' when the room has none: a removed brief, a
    remote room, or a station from before briefs."""
    brief = room.get('brief') if isinstance(room, dict) else None
    if not isinstance(brief, dict) or not isinstance(brief.get('body'), str) or not brief['body']:
        return ''
    revision = brief['revision'] if type(brief.get('revision')) is int else '?'
    members = {m['id']: m for m in room.get('members', [])}
    return (f'Room brief (revision {revision}, updated {brief_date(brief.get("updated"))})\n'
            + fence_message(members.get(brief.get('author_id')), brief['body'], len(brief['body'])))
