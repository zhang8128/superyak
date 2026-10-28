"""The first rail's lessons (docs/superpowers/specs/2026-10-27-first-rail-lessons-design.md): the wire format and every
door's checks, the lessons room's record, the backfill, the index, the query, receipts and segments.

Module-level imports stay light: the prompt path (`query` with a `prompt`) imports no store, no sqlite3 and nothing
from ships.py, and opens no database. Anything heavier is imported inside the function that needs it."""
from collections import namedtuple
import json
import math
import os
from pathlib import Path
import re
import socket
import struct
import sys
import time
from .common import Problem, encode, uid

# Section 2: the wire format.
ORDER = ('ship', 'claim', 'why', 'error', 'command', 'file', 'learned from')
APPLIES = ('error', 'command', 'file')
LIMITS = {'ship': 32, 'claim': 160, 'why': 300, 'error': 120, 'command': 120, 'file': 120, 'learned from': 32}
BODY_BYTES = 4096
VALUES_PER_KIND = 8
LIVE_CAP = 32
HOLD_BYTES = 6  # a command value this long may hold a command (section 8); a value this long matches at a prompt
RETRACT = re.compile(r'retract ([0-9a-f]{64}:[0-9a-f]{64})')
SHORT = re.compile(r'[0-9a-f]{8}-[0-9a-f]{8}')
# Section 6.
EMAIL = re.compile(r'[^\s@]+@[^\s@]+\.[A-Za-z]{2,}')
PHONES = (re.compile(r'\+\d[\d ().-]{7,}\d'), re.compile(r'\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}'))
# Sections 5 and 7: calibration hypotheses, in radians.
R_MAX = math.acos(0.60)
R_PROMPT = math.acos(0.75)
SEGMENT_ANGLE = math.acos(0.85)
# Section 5's caps and bounds (the hook cuts each field to its cap; the query refuses a longer one).
CAPS = {'cwd': 200, 'branch': 200, 'command': 300, 'error': 300}
PROMPT_CHARS = 2000
SEEN_MAX = 128
ANSWER_BYTES = 2000
SHOWN = 3
SHOWN_AT_PROMPT = 2
NEAR_SECONDS = 0.8
PROMPT_NEAR_SECONDS = 0.1
STALE_SECONDS = 180
PROMPT_WORDS = 4
# Section 4.
INDEX_FILE = 'lessons-index.bin'  # a JSON part, then float32 vectors (C17)
PROMPT_NEAR_OFF = 'lessons-prompt-near-off'  # in the data directory: Near never runs at a prompt on this peer (C44)
INDEX_MAGIC = b'superyak-lessons-index 1\n'
EMBED_BATCH = 8
EMBED_SECONDS = 120.0
INFO_SECONDS = 2.0
RUNTIME_CONFIG = Path.home() / '.config' / 'superyak' / 'runtime.json'

NOT_A_LESSON = 'The lessons room takes only lessons and retractions, in the wire format of first rail section 2'
PERSON = "A lesson can't name a person or hold an email address or phone number"
SHIPS_ONLY = "Lessons are laid by ships; the room's owner retracts them"
SHIP_IS_AUTHOR = 'ship: is the posting account\'s own username'
NO_MENTIONS = 'A lesson mentions no one: an @name in it would start a ship\'s run'
LIVE_KEY = ('This lesson contains a live ship key, so it was not posted. Treat that key as exposed: its ship should '
            'revoke it and dock again.')
RETRACTED = "That lesson was retracted, for good: its text can't be laid again on this peer"
CAP = 'This ship already has 32 live lessons in the room; retract one first'
NO_SUCH_LESSON = 'No live lesson in this room has that id'
WHO_RETRACTS = "Only a lesson's author or the room's owner retracts it"
LABELS = 'The lessons room takes plain posts: no reply label and no ticket'
NOT_HERE = 'The lessons room takes no {what}'
NO_IDENTITY = 'This peer has no identity.json yet, so its lessons have no peer id; federation makes it'
NEW_LOCAL = 'The lessons room takes no new member from this station (first rail section 3)'
UNLISTED = '{name} is on a peer that is not listed for the lessons room; list it with make station-lessons-room first'

Lesson = namedtuple('Lesson', 'ship claim why error command file learned_from')
Retraction = namedtuple('Retraction', 'lesson_id')
Post = namedtuple('Post', 'room id author body live_key skip')  # skip: the system's, or marked unverified
Live = namedtuple('Live', 'id author lesson body')
Account = namedtuple('Account', 'username name kind')
Snapshot = namedtuple('Snapshot', 'peer room epochs owner members posts accounts names ships')  # epochs: [room key, epoch] along the chain


class LessonRefused(Problem):
    def __init__(self, message):
        super().__init__(422, message)


class EmbedderUnavailable(Exception):
    pass


class EmbedderTimeout(EmbedderUnavailable):
    """Out of time (the deadline or the hook's budget): the answer is words only, and nothing says unavailable."""


class IndexUnreadable(Exception):
    """The index file exists but can't be read or parsed: a real failure (the query exits 1, nothing on stdout)."""


def _value(number, key, value):
    if not 1 <= len(value.encode('utf-8')) <= LIMITS[key]:
        raise LessonRefused(f'Line {number}: a {key} value is 1 to {LIMITS[key]} bytes')
    if value != value.strip():
        raise LessonRefused(f'Line {number}: a {key} value has no leading or trailing space')
    if not value.isprintable():  # no control, format, separator (but the space), private-use or unassigned character
        raise LessonRefused(f'Line {number}: a {key} value holds no control or format character')


def parse_post(body):
    """Section 2: a Lesson or a Retraction. Anything else raises LessonRefused, saying which rule failed and never
    echoing a value."""
    from .ships import SHIP_NAME
    if not isinstance(body, str):
        raise LessonRefused(NOT_A_LESSON)
    retraction = RETRACT.fullmatch(body)
    if retraction:
        return Retraction(retraction.group(1))
    try:
        size = len(body.encode('utf-8'))
    except UnicodeError:
        raise LessonRefused('A lesson is UTF-8 text') from None
    if size > BODY_BYTES:
        raise LessonRefused('A lesson is at most 4,096 bytes')
    if '\r' in body:
        raise LessonRefused('A lesson\'s lines end with \\n alone, never \\r')
    if body.endswith('\n'):
        raise LessonRefused('A lesson has no final newline')
    lines = body.split('\n')
    if lines[0] != 'lesson':
        raise LessonRefused(NOT_A_LESSON)
    values, position = {key: [] for key in ORDER}, 0
    for number, line in enumerate(lines[1:], 2):
        key, sep, value = line.partition(': ')
        if not sep or key not in LIMITS:
            raise LessonRefused(f'Line {number} is not one of the fields ship, claim, why, error, command, file, '
                                'learned from (a blank line is not allowed either)')
        at = ORDER.index(key)
        if at < position or (key not in APPLIES and values[key]):
            raise LessonRefused(f'Line {number} ({key}) is out of order or repeated: the order is ship, claim, why, '
                                'error, command, file, learned from')
        position = at
        _value(number, key, value)
        if value in values[key]:
            raise LessonRefused(f'Line {number} repeats a {key} value')
        values[key].append(value)
    for key in ('ship', 'claim', 'why', 'learned from'):
        if len(values[key]) != 1:
            raise LessonRefused(f'A lesson has one {key} line')
    if any(len(values[key]) > VALUES_PER_KIND for key in APPLIES):
        raise LessonRefused('A lesson has at most 8 error, 8 command and 8 file lines')
    if not any(values[key] for key in APPLIES):
        raise LessonRefused('A lesson has at least one error, command or file line')
    ship, learned = values['ship'][0], values['learned from'][0]
    if not SHIP_NAME.fullmatch(ship):
        raise LessonRefused('ship: is a ship name: 2 to 32 lowercase letters, digits or dashes, starting with a letter')
    if learned not in ('own', 'owner') and not SHIP_NAME.fullmatch(learned):
        raise LessonRefused('learned from: is own, owner, or a ship name')
    return Lesson(ship, values['claim'][0], values['why'][0], tuple(values['error']), tuple(values['command']),
                  tuple(values['file']), learned)


def embedded_text(lesson):
    """Section 2: the claim, the why, then every applies-to value in the post's order."""
    return f'{lesson.claim}\n{lesson.why}\nApplies to: ' + '; '.join(lesson.error + lesson.command + lesson.file)


def lesson_id(peer, lesson):
    """Decision 9: `<peer>:<SHA-256 of the embedded text>`, the peer being the one the lesson was laid on."""
    import hashlib
    return peer + ':' + hashlib.sha256(embedded_text(lesson).encode('utf-8')).hexdigest()


def short_lesson_id(key):
    peer, _, digest = key.partition(':')
    return f'{peer[:8]}-{digest[:8]}'


def names_pattern(names):
    """Section 6: one pattern for every account name that refuses a lesson: each username or display name, case-folded,
    of at least 3 characters, as a whole word (a display name's words in order, any whitespace between). None when no
    name qualifies."""
    folded = {' '.join(name.casefold().split()) for name in names if isinstance(name, str)}
    words = sorted((name for name in folded if len(name) >= 3), key=len, reverse=True)
    if not words:
        return None
    return re.compile(r'(?<!\w)(?:' + '|'.join(r'\s+'.join(map(re.escape, w.split(' '))) for w in words) + r')(?!\w)')


def lesson_values(lesson):
    """What section 6 reads: the lesson's values, never its field names, so an account named `file` refuses nothing."""
    return '\n'.join((lesson.ship, lesson.claim, lesson.why, *lesson.error, *lesson.command, *lesson.file,
                      lesson.learned_from))


def holds_person_data(text, pattern):
    # EMAIL runs only on the whitespace-free tokens that hold an @ (every match lies inside one): on a long run with no
    # @, its [^\s@]+ backtracks quadratically.
    return bool((pattern is not None and pattern.search(text.casefold()))
                or any(EMAIL.search(token) for token in text.split() if '@' in token)
                or any(phone.search(text) for phone in PHONES))


def unit(vector):
    norm = math.hypot(*vector)
    return [x / norm for x in vector] if norm and math.isfinite(norm) else None


def angle(a, b):
    """Trails R4, Kahan's form, for unit vectors: 2·atan2(‖a − b‖, ‖a + b‖), in [0, π]."""
    return 2 * math.atan2(math.dist(a, b), math.dist(a, [-x for x in b]))


def embedder_socket(runtime_config=None):
    """Section 1: the machine's shared embedder, named by `embedder_socket` in runtime.json; None without one."""
    try:
        value = json.loads(Path(runtime_config or RUNTIME_CONFIG).read_text()).get('embedder_socket')
    except (OSError, ValueError, AttributeError):
        return None
    return Path(value) if isinstance(value, str) and os.path.isabs(value) else None


def _recv(sock, size, remaining):
    chunks = bytearray()
    while len(chunks) < size:
        sock.settimeout(remaining())
        chunk = sock.recv(min(size - len(chunks), 1 << 20))
        if not chunk:
            raise ConnectionError('the embedder closed the connection')
        chunks += chunk
    return bytes(chunks)


def _call(socket_path, request, deadline, clock):
    """One request over engram/embedder_service.py's protocol (a 4-byte big-endian length, then UTF-8 JSON), finished by
    `deadline` on `clock`. Never loads a model (trails R19)."""
    def remaining():
        left = deadline - clock()
        if left <= 0:
            raise TimeoutError('past the deadline')
        return left
    data = json.dumps(request, separators=(',', ':')).encode('utf-8')
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(remaining())
            sock.connect(str(socket_path))
            sock.settimeout(remaining())
            sock.sendall(struct.pack('>I', len(data)) + data)
            (size,) = struct.unpack('>I', _recv(sock, 4, remaining))
            if size > 16 * 1024 * 1024:
                raise ValueError('reply too large')
            reply = json.loads(_recv(sock, size, remaining))
    except TimeoutError:
        raise EmbedderTimeout('past the deadline') from None
    except (OSError, ValueError) as error:
        raise EmbedderUnavailable(type(error).__name__) from None
    if not isinstance(reply, dict) or reply.get('ok') is not True or not isinstance(reply.get('model'), str):
        raise EmbedderUnavailable('the embedder refused')
    return reply


def embedder_model(socket_path, deadline, clock=time.monotonic):
    return _call(socket_path, {'op': 'info'}, deadline, clock)['model']


def embed(socket_path, texts, prefix, deadline, clock=time.monotonic):
    """(model, unit vectors), one per text, or EmbedderUnavailable."""
    reply = _call(socket_path, {'op': 'embed', 'texts': list(texts), 'prefix': prefix}, deadline, clock)
    vectors, dimension = reply.get('vectors'), reply.get('dimension')
    if (type(dimension) is not int or dimension < 1 or not isinstance(vectors, list) or len(vectors) != len(texts)
            or any(not isinstance(v, list) or len(v) != dimension
                   or any(type(x) not in (int, float) or not math.isfinite(x) for x in v) for v in vectors)):
        raise EmbedderUnavailable('malformed vectors')
    units = [unit(v) for v in vectors]
    if any(v is None for v in units):
        raise EmbedderUnavailable('a zero vector')
    return reply['model'], units


def lesson_refusal(snapshot, author, lesson, body, live_key):
    """Sections 2, 3 and 6 for one lesson by `author` (a full `<peer>:<user>` id), against this peer's snapshot: the
    refusal's message, or None. Every door and every index runs exactly this."""
    from .ships import addressed_names
    peer, _, user = author.partition(':')
    if peer == snapshot.peer:
        account = snapshot.accounts.get(user)
        if account is None or account.kind != 'ship':
            return SHIPS_ONLY
        if lesson.ship != account.username:
            return SHIP_IS_AUTHOR
    if addressed_names(body):
        return NO_MENTIONS
    if holds_person_data(lesson_values(lesson), snapshot.names):
        return PERSON
    if live_key:
        return LIVE_KEY
    return None


def chain_lessons(snapshot):
    """Section 4 step 2, and every door's view of the chain: (the live lessons in the order laid, the retracted ids).
    Copies collapse by lesson id and keep the earliest copy; each author keeps its first 32 live lessons. A post by
    the system, one marked unverified, or one whose author isn't a member of the current room counts for nothing."""
    first, authors, retractions = {}, {}, []
    for post in snapshot.posts:
        if post.skip or post.author not in snapshot.members:
            continue
        try:
            parsed = parse_post(post.body)
        except LessonRefused:
            continue
        if isinstance(parsed, Retraction):
            retractions.append((post.author, parsed.lesson_id))
            continue
        key = lesson_id(post.author.partition(':')[0], parsed)
        authors.setdefault(key, post.author)
        if key not in first and lesson_refusal(snapshot, post.author, parsed, post.body, post.live_key) is None:
            first[key] = Live(key, post.author, parsed, post.body)
    retracted = {key for who, key in retractions if key in authors and who in (authors[key], snapshot.owner)}
    live, counts = [], {}
    for item in first.values():
        if item.id not in retracted and counts.get(item.author, 0) < LIVE_CAP:
            counts[item.author] = counts.get(item.author, 0) + 1
            live.append(item)
    return live, retracted


class Lessons:
    """The store's side: the room's record and chain, every door's checks, the backfill, the index run and step 4."""

    def _lessons_record(self, db):
        return db.execute('SELECT * FROM lessons_room WHERE id=1').fetchone()

    def _lessons_peer(self, db):
        if not (self.data_dir / 'identity.json').is_file():
            raise Problem(409, NO_IDENTITY)
        return self._own_peer_id(db)

    def _remote_rooms_from(self, db, origin):
        """{room id: (recipient, inbox revision, payload)} for every room this peer holds from a paired origin."""
        rows = db.execute("SELECT inbox.resource_id, inbox.recipient, inbox.revision, inbox.payload FROM inbox JOIN peers "
                          "ON peers.peer_id=inbox.origin WHERE inbox.origin=? AND inbox.kind='room' AND inbox.payload IS NOT "
                          "NULL AND peers.paired=1 ORDER BY inbox.recipient", (origin,)).fetchall()
        rooms = {}
        for row in rows:
            rooms.setdefault(row['resource_id'], (row['recipient'], row['revision'], json.loads(row['payload'])))
        return rooms

    def _lessons_chain(self, db):
        """The recorded room's chain on this peer, oldest first, ending with the current room; [] when none is recorded.
        A local room id on the origin, `<origin>:<room id>` elsewhere. Each peer follows linked_room_id forward."""
        record = self._lessons_record(db)
        if record is None:
            return []
        key = record['room_key']
        if ':' not in key:
            seen = {key}
            while True:
                row = db.execute('SELECT id FROM rooms WHERE linked_room_id=?', (key,)).fetchone()
                if row is None or row['id'] in seen:
                    break
                key = row['id']
                seen.add(key)
            return list(reversed(self._rooms_back(db, key)))
        origin, _, current = key.partition(':')
        rooms = self._remote_rooms_from(db, origin)
        if current not in rooms:
            return []
        forward = {payload.get('linked_room_id'): rid for rid, (_, _, payload) in rooms.items()}
        seen = {current}
        while origin + ':' + current in forward and forward[origin + ':' + current] not in seen:
            current = forward[origin + ':' + current]
            seen.add(current)
        chain, step = [], current
        while step in rooms and step not in chain:
            chain.append(step)
            linked = rooms[step][2].get('linked_room_id')
            step = linked.partition(':')[2] if isinstance(linked, str) and linked.startswith(origin + ':') else None
        return [origin + ':' + rid for rid in reversed(chain)]

    def _in_lessons_chain(self, db, key):
        return key in self._lessons_chain(db)

    def _lessons_snapshot(self, db):
        """Section 4 step 1, inside the caller's transaction: everything the checks and the index read. None when no room
        is recorded or this peer no longer holds it."""
        chain = self._lessons_chain(db)
        if not chain:
            return None
        peer = self._lessons_peer(db)
        system = self.system_author_id(db)
        accounts = {r['id']: Account(r['username'], r['name'], r['kind'])
                    for r in db.execute("SELECT id,username,name,kind FROM users WHERE kind!='system'")}
        names = names_pattern([n for a in accounts.values() if a.kind == 'person' for n in (a.username, a.name)])
        posts, epochs = [], []
        current = chain[-1]
        if ':' not in current:
            for key in chain:
                epochs.append([key, db.execute('SELECT epoch FROM rooms WHERE id=?', (key,)).fetchone()[0]])
                notices = {r[0] for r in db.execute('SELECT message_kinds.message_id FROM message_kinds JOIN messages ON '
                                                    'messages.id=message_kinds.message_id WHERE messages.room_id=?', (key,))}
                rows = [(r['id'], r['author_id'] if r['author_id'] == system else f"{peer}:{r['author_id']}", r['body'],
                         r['created'], r['author_id'] == system or r['id'] in notices)
                        for r in db.execute('SELECT * FROM messages WHERE room_id=? ORDER BY created, rowid', (key,))]
                rows += [(r['id'], r['author_id'], r['body'], r['created'], False)
                         for r in db.execute('SELECT * FROM peer_messages WHERE room_id=? ORDER BY created, rowid', (key,))]
                rows.sort(key=lambda r: r[3])  # stable, as get_room orders them
                posts += [Post(key, i, a, b, self._live_ship_key_in(db, b), s) for i, a, b, _, s in rows]
            room = db.execute('SELECT owner_id FROM rooms WHERE id=?', (current,)).fetchone()
            owner = f"{peer}:{room['owner_id']}"
            members = {f'{peer}:{r[0]}' for r in db.execute('SELECT user_id FROM room_members WHERE room_id=?', (current,))}
            members |= {f"{r['peer_id']}:{r['user_id']}" for r in db.execute(
                'SELECT remote_contacts.peer_id, remote_contacts.user_id FROM remote_room_members JOIN remote_contacts '
                'ON remote_contacts.id=remote_room_members.contact_id WHERE remote_room_members.room_id=?', (current,))}
        else:
            origin = current.partition(':')[0]
            rooms = self._remote_rooms_from(db, origin)
            for key in chain:
                recipient, revision, payload = rooms[key.partition(':')[2]]
                epochs.append([key, revision])
                stored = {m.get('id') for m in payload.get('messages', []) if isinstance(m, dict)}
                for m in self._remote_room(db, recipient, key)['messages']:
                    if m.get('id') in stored:
                        posts.append(Post(key, m['id'], m['author_id'], m['body'], self._live_ship_key_in(db, m['body']),
                                          bool(m.get('unverified'))))
            payload = rooms[current.partition(':')[2]][2]
            owner = payload.get('owner_id')
            members = {m for m in payload.get('member_ids', []) if isinstance(m, str)}
        ships = {accounts[m.partition(':')[2]].username: m for m in members
                 if m.startswith(peer + ':') and m.partition(':')[2] in accounts and accounts[m.partition(':')[2]].kind == 'ship'}
        return Snapshot(peer, current, epochs, owner, members, posts, accounts, names, ships)


LESSON_SCHEMA = '''
CREATE TABLE IF NOT EXISTS lessons_room(id INTEGER PRIMARY KEY CHECK(id=1), room_key TEXT NOT NULL, ship_id TEXT REFERENCES users(id), recorded REAL NOT NULL);
CREATE TABLE IF NOT EXISTS lessons_peers(peer_id TEXT PRIMARY KEY REFERENCES peers(peer_id), recorded REAL NOT NULL);
CREATE TABLE IF NOT EXISTS lesson_receipts(id TEXT PRIMARY KEY, created REAL NOT NULL, ship_id TEXT NOT NULL REFERENCES users(id), lesson_id TEXT NOT NULL, author_id TEXT NOT NULL, angle REAL);
CREATE INDEX IF NOT EXISTS lesson_receipts_by_created ON lesson_receipts(created);
CREATE TABLE IF NOT EXISTS lesson_queries(id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL, ship_id TEXT NOT NULL REFERENCES users(id), nearest REAL, shown INTEGER NOT NULL);
'''
