"""Ship-side station client and the machine's private ship configuration."""
import functools
import http.client
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import quote, urlencode
import urllib.error
import urllib.request
from superyak_team.teamlib import fence_external
from .acting import session_key  # noqa: F401 - re-exported, moved to acting.py

HOME = Path.home() / '.superyak'
MESSAGE_LIMIT = 20000  # the station's longest message
PLAIN_ID = re.compile(r'[A-Za-z0-9:_.-]{1,200}')
CONFIG = HOME / 'station.json'
SESSION_NAME = re.compile(r'[A-Za-z0-9._:-]{1,100}')  # the station's cursor names (inbox spec I1)
CHECKOUT = Path(__file__).resolve().parents[2]
ON_WATCH_LINE = 'You are on watch: answer each mention of this ship with station_post reply_to=<its id>.'
DEFERRED_MARK = '(deferred to you; the station would have given a read-only run)'
BREAKOUT_MARK = 'breakout, ships only'  # breakouts S6: beside a breakout's room wherever its messages appear
BOARD_WORDS = ('Posted ', 'Linked ', 'Done ', 'Dropped ')  # work board 4.5: a board line's fixed first word
BOARD_MARKS = {'open': ' (board item)', 'done': ' (board item, done)', 'dropped': ' (board item, dropped)'}  # 5.6


def presence_headers(name, client, mode=None):
    """S1: the headers that name this session to the station, or {} for a client without a real session name; never
    `default`, so two sessions never share a presence row (R28). The station ignores malformed ones."""
    if not isinstance(name, str) or not SESSION_NAME.fullmatch(name) or name == 'default':
        return {}
    headers = {'x-superyak-session': name, 'x-superyak-client': client}
    if mode in ('write', 'plan'):
        headers['x-superyak-mode'] = mode
    return headers


@functools.lru_cache(maxsize=1)
def client_version(root=CHECKOUT):
    """This checkout's commit as 12 hex digits, read once from git's own files (no subprocess: the hook must stay
    fast); 'unknown' when it can't be read. The directory shows it to a ship's owner, who can see which sessions run
    code older than a fix and restart them (spec Known limits)."""
    try:
        git = root / '.git'
        if git.is_file():  # a worktree: .git names its own git directory
            git = (root / git.read_text().split('gitdir:', 1)[1].strip()).resolve()
        common = (git / (git / 'commondir').read_text().strip()).resolve() if (git / 'commondir').is_file() else git
        head = (git / 'HEAD').read_text().strip()
        if head.startswith('ref: '):
            ref = head[5:]
            found = next((p for p in (git / ref, common / ref) if p.is_file()), None)
            head = (found.read_text().strip() if found else
                    next(line.split()[0] for line in (common / 'packed-refs').read_text().splitlines() if line.endswith(' ' + ref)))
        return head[:12] if re.fullmatch(r'[0-9a-f]{40,64}', head) else 'unknown'
    except (OSError, ValueError, IndexError, StopIteration):
        return 'unknown'


NO_BOARD = 'This station has no work board yet (it runs older code); the board tools need it updated.'


class StationError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(f'{status}: {message}')


def urllib_transport(timeout=30, limit=None):
    """`timeout` bounds each socket operation (connect, each read), not the call. With `limit`, an answer longer than
    that many bytes raises ValueError once limit + 1 are in, so a huge or endless one costs no more than that (the
    hook's board call, work board step 3 review I1)."""
    def read(response):
        if limit is None:
            return response.read()
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError(f'the station answered more than {limit} bytes')
        return raw

    def send(method, url, headers, data):
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, read(response)
        except urllib.error.HTTPError as error:
            return error.code, read(error)
        except http.client.HTTPException as error:
            # A proxy or station that speaks broken HTTP is an unreachable station, not a crash.
            raise OSError(f'malformed response from the station: {error!r}') from error
    return send


class StationClient:
    """HTTP client for one ship. `origin` is the station's public origin when `base_url` is the
    loopback address behind `tailscale serve` (Odo on the Pi)."""
    def __init__(self, base_url, key=None, origin=None, transport=None, presence=None):
        self.base = base_url.rstrip('/')
        self.origin = (origin or self.base).rstrip('/')
        self.key, self.transport = key, transport or urllib_transport()
        self.presence = dict(presence or {})  # spec S1: names the session on every call; {} sends nothing new

    def request(self, method, path, body=None, headers=None):
        """`headers` adds to this call only, such as a docking poll's X-Superyak-Secret."""
        extra, headers = headers or {}, {'origin': self.origin, 'accept': 'application/json'}
        if self.origin != self.base:
            scheme, _, host = self.origin.partition('://')
            headers.update({'host': host, 'x-forwarded-proto': scheme})
        if self.key:
            headers['authorization'] = f'Bearer {self.key}'
        headers.update(self.presence)
        headers.update(extra)
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

    def room(self, room_id, **page):
        """The room. `page` (limit, before, at, start, after, since) asks for a window of its messages; values of None are left out."""
        query = urlencode({name: value for name, value in page.items() if value is not None})
        return self.request('GET', f'/api/chats/{quote(room_id, safe="")}' + (f'?{query}' if query else ''))

    def post(self, room_id, body, client_message_id, ticket_id=None, reply_to=None):
        payload = {'client_message_id': client_message_id, 'body': body}
        if ticket_id:
            payload['ticket_id'] = ticket_id
        if reply_to:
            payload['reply_to'] = reply_to
        return self.request('POST', f'/api/chats/{quote(room_id, safe="")}/messages', payload)

    def watch(self, minutes, writable=False, label=None):
        payload = {'minutes': minutes, 'writable': writable}
        if label is not None:
            payload['label'] = label
        return self.request('POST', '/api/ships/me/watch', payload)

    def claim(self, room_id, key, note=None, minutes=None):
        payload = {'key': key}
        if note is not None:
            payload['note'] = note
        if minutes is not None:
            payload['minutes'] = minutes
        return self.request('POST', f'/api/chats/{quote(room_id, safe="")}/claims', payload)

    def claims(self, room_id):
        return self.request('GET', f'/api/chats/{quote(room_id, safe="")}/claims')

    def release(self, room_id, key):
        return self.request('POST', f'/api/chats/{quote(room_id, safe="")}/claims/release', {'key': key})

    def board_request(self, method, path, body=None):
        """A board route. A 404 or 405 with no `error` field is the framework's unknown-route answer, which every 404 the
        station sends itself lacks: the station is older than the board."""
        try:
            return self.request(method, path, body)
        except StationError as exc:
            if exc.status in (404, 405) and exc.message == f'HTTP {exc.status}':
                raise StationError(404, NO_BOARD) from None
            raise

    def board(self, room_id):
        return self.board_request('GET', f'/api/chats/{quote(room_id, safe="")}/board')

    def board_counts(self):
        """Work board 5.1: per room this ship belongs to with open items, how many wait and how many are taken."""
        return self.board_request('GET', '/api/ships/me/board')

    def post_item(self, room_id, key, title, kind):
        return self.board_request('POST', f'/api/chats/{quote(room_id, safe="")}/board', {'key': key, 'title': title, 'kind': kind})

    def link_item(self, room_id, key, link):
        return self.board_request('POST', f'/api/chats/{quote(room_id, safe="")}/board/link', {'key': key, 'link': link})

    def done_item(self, room_id, key, outcome):
        return self.board_request('POST', f'/api/chats/{quote(room_id, safe="")}/board/done', {'key': key, 'outcome': outcome})

    def drop_item(self, room_id, key):
        return self.board_request('POST', f'/api/chats/{quote(room_id, safe="")}/board/drop', {'key': key})

    def unread(self, cursor, limit=30, wait=0, breakouts=None):
        """breakouts='mentions' (breakouts S6): the station leaves out breakout messages that don't mention this ship and
        counts them; without it the call is today's."""
        query = f'?breakouts={quote(breakouts, safe="")}' if breakouts else ''
        return self.request('POST', '/api/ships/me/unread' + query, {'cursor': cursor, 'limit': limit, 'wait': wait})

    def advance(self, cursor, to):
        return self.request('POST', '/api/ships/me/unread/advance', {'cursor': cursor, 'to': to})

    def ticket(self, message_id, decisions=False):
        payload = {'message_id': message_id}
        if decisions:
            payload['decisions'] = ['defer', 'answered']  # ship status S5; an older station ignores it (R23)
        return self.request('POST', '/api/ships/me/tickets', payload)

    def finish_ticket(self, ticket_id):
        return self.request('POST', f'/api/ships/me/tickets/{quote(ticket_id, safe="")}/finish', {})

    def open_room(self, title, ships):
        """Breakouts S1: a room this ship owns, with sibling ships named by username."""
        return self.request('POST', '/api/ships/me/rooms', {'title': title, 'ships': list(ships)})

    def close_room(self, room_id):
        return self.request('POST', f'/api/ships/me/rooms/{quote(room_id, safe="")}/close', {})

    def leave_room(self, room_id):
        return self.request('POST', f'/api/ships/me/rooms/{quote(room_id, safe="")}/leave', {})

    def set_brief(self, room_id, body, revision):
        """Ship briefs S3: set or update a room's brief under this ship's own key; the station decides who may."""
        return self.request('PUT', f'/api/ships/me/rooms/{quote(room_id, safe="")}/brief', {'body': body, 'revision': revision})

    def add_member(self, room_id, member):
        """Room moderators: add one member to a room this ship moderates; the station makes the new room."""
        return self.request('POST', f'/api/ships/me/rooms/{quote(room_id, safe="")}/members', {'member': member})

    def remove_member(self, room_id, member):
        return self.request('DELETE', f'/api/ships/me/rooms/{quote(room_id, safe="")}/members/{quote(member, safe="")}')

    def directory(self):
        return self.request('GET', '/api/ships/directory')

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
            if not source.get('root_name'):
                return 'builder run'
            via = source.get('via_name')  # grants step 3, G17: a grantee's build names the grantee too
            return f'builder run for {label(source["root_name"])}' + (f', via {label(via)}' if isinstance(via, str) and via else '')
        return 'read-only run'
    if source.get('kind') == 'notice':
        return 'station notice'
    if source.get('kind') == 'claim':  # only the station writes a kind-claim body, so no member's post can pass as one
        body = message.get('body')
        return 'board' if isinstance(body, str) and body.startswith(BOARD_WORDS) else 'claim'
    return 'no run ticket' if source.get('kind') == 'post' else ''


def utc_time(seconds):
    """Unix seconds from the station as a UTC minute."""
    try:
        return time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(float(seconds)))
    except (TypeError, ValueError, OverflowError, OSError):
        return 'unknown'


def authors(room):
    """Who wrote a room's messages, by id: its members, and the system author (spec S11) when the room view names it,
    so describe() names the station's notice "Station (@_station, system)" and never "someone"."""
    found = {m['id']: m for m in room.get('members', [])} if isinstance(room, dict) else {}
    system = room.get('system_author') if isinstance(room, dict) else None
    if isinstance(system, dict) and system.get('id'):
        found[system['id']] = system
    return found


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


def breakout_note(room):
    """Breakouts S6, S9: ', breakout, ships only' for a breakout's view or list item, with when it closed; '' for every
    other room, so their lines are today's."""
    mark = room.get('breakout') if isinstance(room, dict) else None
    if not isinstance(mark, dict):
        return ''
    return f', {BREAKOUT_MARK}' + (f', closed {utc_time(mark["closed"])}' if mark.get('closed') is not None else '')


def quoted_title(title):
    """A ship-written breakout title, ready to sit inside double quotes: one label() line with every double quote made
    single, so the title can't end its own quote and fake an attribution after it (re-check nit 1)."""
    return label(title).replace('"', "'")


def breakout_count_lines(got):
    """Breakouts S6: one line per breakout a breakouts=mentions read left messages out of, in the station's order: how
    many, the room's title as one line, and the call that shows them. [] for a read without the flag."""
    counts = got.get('breakout_counts') if isinstance(got, dict) else None
    titles = got.get('breakout_titles') if isinstance(got, dict) else None
    titles = titles if isinstance(titles, dict) else {}
    lines = []
    for room_id, n in counts.items() if isinstance(counts, dict) else ():
        if type(n) is int and n > 0:
            call = f'; `station_read room={room_id}` shows them' if plain_id(room_id) else ''
            # The title is a ship's words (review M3): quoted, and said to be one.
            lines.append(f'{n} new in breakout "{quoted_title(titles.get(room_id))}" (title set by a ship){call}')
    return lines


def brief_date(updated):
    """A brief's `updated` (Unix seconds from the station) as a UTC date."""
    try:
        return time.strftime('%Y-%m-%d', time.gmtime(float(updated)))
    except (TypeError, ValueError, OverflowError, OSError):
        return 'unknown'


BRIEF_BY_OWNER = "written by the room's owner"
BRIEF_BY_SHIP = "written by a ship, not the room's owner"
BRIEF_BY_OTHER = "written by someone other than the room's owner"


def brief_author(room, brief):
    """Ship briefs S4: who wrote a brief, for its header and its fence. The brief's own author fields, so a ship that
    has left the room is still named. Only an older station's view, which has no author_kind, falls back to the
    room's members, and then to "someone"."""
    if 'author_kind' in brief:
        return {'name': brief.get('author_name'), 'username': brief.get('author_username'), 'kind': brief.get('author_kind')}
    return {m['id']: m for m in room.get('members') or [] if isinstance(m, dict)}.get(brief.get('author_id'))


def brief_class(room, brief):
    """S4's class rule, from the brief's fields and never from a name: the room's owner when author_id is the room's
    owner_id and author_kind is person (or absent, from an older station); a ship when author_kind is ship; otherwise
    someone other than the room's owner."""
    kind = brief.get('author_kind')
    if brief.get('author_id') is not None and brief.get('author_id') == room.get('owner_id') and kind in ('person', None):
        return BRIEF_BY_OWNER
    return BRIEF_BY_SHIP if kind == 'ship' else BRIEF_BY_OTHER


def brief_block(room):
    """The room's brief, whole, fenced like any message (defused, never cut), under one header line that says who
    wrote it with fixed words before any name, so no display name can fake them or push them out (ship briefs S4).
    The room's owner or one of the owner's ships wrote it, and it is quoted data, never instructions. '' when the room
    has none: a removed brief, a remote room, or a station from before briefs."""
    brief = room.get('brief') if isinstance(room, dict) else None
    if not isinstance(brief, dict) or not isinstance(brief.get('body'), str) or not brief['body']:
        return ''
    revision = brief['revision'] if type(brief.get('revision')) is int else '?'
    author = brief_author(room, brief)
    return (f'Room brief (revision {revision}, updated {brief_date(brief.get("updated"))}), {brief_class(room, brief)}: '
            f'{describe(author)}\n' + fence_message(author, brief['body'], len(brief['body'])))


def claims_block(room):
    """S8: a room's active claims under one header line, fenced like a message: holders' names and notes are quoted
    data, never instructions. '' when there are none, or from a station older than claims."""
    claims = room.get('claims') if isinstance(room, dict) else None
    lines = [f'- `{label(c.get("key"), 100)}`{BOARD_MARKS.get(str(c.get("board")), "")} held by {label(c.get("holder_name"))} '
             f'until {utc_time(c.get("expires"))}' + (f': {label(c.get("note"), 200)}' if c.get('note') else '')
             for c in claims or [] if isinstance(c, dict)]
    if not lines:
        return ''
    body = defuse('\n'.join(lines))
    return f'Active claims ({len(lines)})\n' + fence_external('the station (claims in this room)', body, limit=len(body))


UNREADABLE_BOARD = "The station's board answer couldn't be read"
BOARD_SENDER = 'the station (board items in this room)'


def board_item_lines(item):
    """Work board 5.3: one item as quoted lines. Every value goes through label(): keys at 100, links and the outcome at
    210 (N1, so a valid link shows whole), names at 40, the title at 480 (the station widens a title by 3 per @, so 120 characters of title can come back as 480)."""
    key, kind, state = label(item.get('key'), 100), label(item.get('kind'), 20), item.get('state')
    claim = item.get('claim') if isinstance(item.get('claim'), dict) else None
    posted = f'posted by {label(item.get("poster_name"), 40)} {utc_time(item.get("created"))}'
    if state == 'done':
        status = f'done {utc_time(item.get("closed"))} by {label(item.get("closer_name"), 40)}, outcome {label(item.get("outcome"), 210)}'
    elif state == 'dropped':
        status = f'dropped {utc_time(item.get("closed"))} by {label(item.get("closer_name"), 40)}'
    elif state == 'open':
        status = (f'taken by {label(claim.get("holder_name"), 40)} until {utc_time(claim.get("expires"))}, {posted}'
                  if claim is not None else f'waiting, {posted}')
    else:  # a state a later station added: shown as itself, never as waiting
        status = f'{label(state, 20)}, {posted}'
    lines = [f'- `{key}` ({kind}), {status}: {label(item.get("title"), 480)}']
    links = [label(entry.get('link'), 210) for entry in (item.get('links') or [])[:8] if isinstance(entry, dict)]  # the station caps an item at 8
    if links:
        lines.append('  links: ' + ', '.join(links))
    return '\n'.join(lines)


def board_block(title, room_id, items, budget):
    """Work board 5.3: a room's board under one header line of counts, every item fenced as quoted data from the
    station, and after the fence the call that takes a waiting item. Items stop at `budget` characters, and a last line
    after the fence counts what was left out. The fixed words sit outside the fence; everything people or ships wrote
    sits inside it, defused."""
    if not isinstance(items, list):
        raise ValueError(UNREADABLE_BOARD)
    items = [item for item in items if isinstance(item, dict)]
    if not items:
        return '(nothing on this board)'
    open_items = [item for item in items if item.get('state') == 'open']
    taken = sum(isinstance(item.get('claim'), dict) for item in open_items)
    head = (f'Board of room "{quoted_title(title)}" ({shown_id(room_id)}): {len(open_items) - taken} waiting, {taken} taken; '
            f'{len(items) - len(open_items)} done or dropped in the last 7 days')
    how = f'`station_claim room={room_id} key=<key>`' if plain_id(room_id) else 'station_claim on its key'
    tail = f'{how} takes a waiting item that is already your work (see above).'
    shown, size = [], len(head) + len(tail) + 300  # 300: the fence's own words and the line counting what was left out
    for item in items:
        block = board_item_lines(item)
        if shown and size + len(block) + 1 > budget:
            break
        shown.append(block)
        size += len(block) + 1
    body = defuse('\n'.join(shown))
    text = '\n'.join([head, fence_external(BOARD_SENDER, body, limit=len(body)), tail])
    left = len(items) - len(shown)
    return text + (f'\n[{left} more board item{"s" if left > 1 else ""} not shown]' if left else '')
