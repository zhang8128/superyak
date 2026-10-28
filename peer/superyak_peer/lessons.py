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
    the system, one marked unverified, or one whose author isn't a member of the current room counts for nothing.
    A lesson's author is the author of its earliest accepted copy, never the poster of a refused one, so only that
    author or the room's owner retracts it."""
    first, retractions = {}, []
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
        if key not in first and lesson_refusal(snapshot, post.author, parsed, post.body, post.live_key) is None:
            first[key] = Live(key, post.author, parsed, post.body)
    retracted = {key for who, key in retractions if key in first and who in (first[key].author, snapshot.owner)}
    live, counts = [], {}
    for item in first.values():
        if item.id not in retracted and counts.get(item.author, 0) < LIVE_CAP:
            counts[item.author] = counts.get(item.author, 0) + 1
            live.append(item)
    return live, retracted


def watermark(snapshot):
    """Section 4 step 1: what the index depends on: the chain's posts, its epochs and members, and this peer's accounts."""
    import hashlib
    return hashlib.sha256(encode({
        'peer': snapshot.peer, 'room': snapshot.room, 'epochs': snapshot.epochs, 'owner': snapshot.owner,
        'members': sorted(snapshot.members),
        'posts': [[p.room, p.id, p.author, hashlib.sha256(p.body.encode('utf-8', 'surrogatepass')).hexdigest(),
                   p.live_key, p.skip] for p in snapshot.posts],
        'accounts': sorted([key, *account] for key, account in snapshot.accounts.items())}).encode()).hexdigest()


def read_index(path):
    """The index file's JSON part, with the raw vector block kept for vectors_of; None when there is no file. A file
    that can't be read or parsed raises IndexUnreadable."""
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        raise IndexUnreadable('the lessons index can\'t be read') from None
    value = _parse_index(data)
    if value is None:
        raise IndexUnreadable('the lessons index is damaged; the next index run rebuilds it')
    return value


def _parse_index(data):
    at = len(INDEX_MAGIC)
    if not data.startswith(INDEX_MAGIC) or len(data) < at + 4:
        return None
    (size,) = struct.unpack('>I', data[at:at + 4])
    try:
        value = json.loads(data[at + 4:at + 4 + size])
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    lessons, ships, dimension = value.get('lessons'), value.get('ships'), value.get('dimension')
    if (not isinstance(lessons, list) or not isinstance(ships, dict) or not isinstance(value.get('peer'), str)
            or not isinstance(value.get('watermark'), str) or not (dimension is None or (type(dimension) is int and dimension > 0))):
        return None
    block = data[at + 4 + size:]
    rows = len(block) // (4 * dimension) if dimension else 0
    if len(block) != rows * 4 * (dimension or 0):
        return None
    keys = {'id', 'author', 'ship', 'learned_from', 'claim', 'why', 'vector', *APPLIES}
    for item in lessons:
        if (not isinstance(item, dict) or set(item) != keys
                or not all(isinstance(item[k], str) for k in ('id', 'author', 'ship', 'learned_from', 'claim', 'why'))
                or not all(isinstance(item[k], list) and all(isinstance(v, str) for v in item[k]) for k in APPLIES)
                or not (item['vector'] is None or (type(item['vector']) is int and 0 <= item['vector'] < rows))):
            return None
    value['block'] = block
    return value


def vectors_of(index):
    """{lesson id: its unit vector}, read from the block only when an angle is needed."""
    import array
    block = array.array('f')
    block.frombytes(index['block'])
    if sys.byteorder == 'big':
        block.byteswap()
    size = index['dimension']
    return {item['id']: block[item['vector'] * size:(item['vector'] + 1) * size]
            for item in index['lessons'] if item['vector'] is not None}


def write_index(path, value, vectors, read_at):
    """Section 4 step 4: the magic line, the JSON part's length (4 bytes, big-endian), the JSON part, then each unit
    vector as little-endian float32, row by row. Written, then renamed over the old file; its modification time is when
    step 1 read the chain, set on the temporary file before the rename, so the live file never shows a fresher one."""
    import array
    path = Path(path)
    head = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    block = array.array('f', [x for vector in vectors for x in vector])
    if sys.byteorder == 'big':
        block.byteswap()
    temporary = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    temporary.unlink(missing_ok=True)  # a run killed before its rename left it, and the name is this pid's own
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(INDEX_MAGIC + struct.pack('>I', len(head)) + head + block.tobytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.utime(temporary, (read_at, read_at))  # before the rename: the rename keeps it
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def read_request(raw):
    """Section 5's input, checked against its caps (the hook cuts before sending); ValueError for anything else."""
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get('ship'), str) or len(value['ship']) > 32:
        raise ValueError('ship')
    seen = value.get('seen', [])
    if not isinstance(seen, list) or len(seen) > SEEN_MAX or not all(isinstance(s, str) and SHORT.fullmatch(s) for s in seen):
        raise ValueError('seen')
    limit = value.get('limit', SHOWN)  # how many lesson slots the caller will render: 0 to 3
    if type(limit) is not int or not 0 <= limit <= SHOWN:
        raise ValueError('limit')
    budget = value.get('budget_ms')  # the hook's time left, a ceiling on Near's own deadline
    if budget is not None and (type(budget) is not int or budget < 0):
        raise ValueError('budget_ms')
    request = {'ship': value['ship'], 'seen': set(seen), 'limit': limit, 'budget_ms': budget}
    if 'prompt' in value:
        if not isinstance(value['prompt'], str) or len(value['prompt']) > PROMPT_CHARS:
            raise ValueError('prompt')
        request.update(prompt=value['prompt'], limit=min(limit, SHOWN_AT_PROMPT))  # limit only lowers the 2
        return request
    for field, cap in CAPS.items():
        text = value.get(field, '')
        if not isinstance(text, str) or len(text) > cap:
            raise ValueError(field)
        request[field] = text
    if type(value.get('words_only', False)) is not bool:
        raise ValueError('words_only')
    request['words_only'] = value.get('words_only', False)
    return request


def fit(entries):
    """Section 5 step 5, in order: a lesson that would push the answer past 2,000 bytes is dropped whole."""
    kept = []
    for entry in entries:
        if len(dumps({'lessons': kept + [entry]}).encode('utf-8')) <= ANSWER_BYTES:
            kept.append(entry)
    return {'lessons': kept}


def dumps(answer):
    """The agreed output: the JSON alone, spelled as the contract spells it, UTF-8, no trailing newline."""
    return json.dumps(answer, ensure_ascii=False)


def shown(item, match, command=None):
    """One lesson of the answer, with exactly the contract's keys, in its order; `command` only for a words match
    through one of its `command` values, that value exactly."""
    entry = {'id': short_lesson_id(item['id']), 'ship': item['ship'], 'claim': item['claim'], 'why': item['why'],
             'match': match}
    if command is not None:
        entry['command'] = command
    return entry


def near_deadline(request, start, own):
    """Near's deadline: its own limit from the query's start, and never past the hook's budget_ms when it sends one."""
    budget = request['budget_ms']
    return start + (own if budget is None else min(own, budget / 1000))


def prompt_answer(request, index, age, socket_path, deadline, monotonic):
    """Section 5's prompt path: this peer's index file and nothing else; no store, no database, no write."""
    if index is None or age > STALE_SECONDS or request['limit'] == 0:
        return {'lessons': []}
    asking = index['ships'].get(request['ship'])
    if asking is None:
        return {'lessons': []}
    prompt, pool, limit = request['prompt'], [], request['limit']
    for item in index['lessons']:
        if item['author'] != asking and item['learned_from'] != request['ship'] and short_lesson_id(item['id']) not in request['seen']:
            pool.append(item)
    matched = []
    for item in pool:
        found = [(k, v) for k in APPLIES for v in item[k] if len(v.encode('utf-8')) >= HOLD_BYTES and v in prompt]
        if found:
            matched.append((-len(found), item['id'], item, next((v for k, v in found if k == 'command'), None)))
    matched.sort(key=lambda m: m[:2])
    picked = [shown(item, 'words', command) for _, _, item, command in matched[:limit]]
    taken = {item['id'] for _, _, item, _ in matched[:limit]}
    if (len(picked) < limit and len(prompt.split()) >= PROMPT_WORDS and index.get('model') and socket_path
            and deadline is not None and deadline > monotonic()):
        try:
            model, (vector,) = embed(socket_path, [prompt], 'search_query', deadline, monotonic)
        except EmbedderUnavailable:
            model = None
        if model == index['model']:
            stored = vectors_of(index)
            near = sorted((theta, item['id'], item) for item in pool if item['id'] not in taken and item['id'] in stored
                          for theta in [angle(vector, stored[item['id']])] if theta <= R_PROMPT)
            picked += [shown(item, round(theta, 4)) for theta, _, item in near[:limit - len(picked)]]
    return fit(picked)


def answer_prompt(request, data_dir, socket_path, clock=time.time, monotonic=time.monotonic, started=None):
    """The prompt path's one entry: this peer's index file, its age, and the answer. The hook may call it in process
    (this module imports only the standard library and superyak_peer.common), saving a second interpreter. `budget_ms`
    bounds the whole answer (C49): spent before the words, it answers nothing; spent during Near, words only, since the
    embedder's socket never waits past it. Near also stops at 100 ms, and never runs where PROMPT_NEAR_OFF is (C44)."""
    start = monotonic() if started is None else started
    end = None if request['budget_ms'] is None else start + request['budget_ms'] / 1000
    if end is not None and monotonic() >= end:
        return {'lessons': []}
    path = Path(data_dir) / INDEX_FILE
    try:
        age = clock() - os.stat(path).st_mtime
    except OSError:
        return {'lessons': []}
    index = read_index(path)
    if end is not None and monotonic() >= end:
        return {'lessons': []}
    near = None if os.path.exists(Path(data_dir) / PROMPT_NEAR_OFF) else near_deadline(request, start, PROMPT_NEAR_SECONDS)
    return prompt_answer(request, index, age, socket_path, near, monotonic)


def could_hold(command, ship, data_dir):
    """Before a Bash command, in process (the signature agreed with Tardis, City of AI 2af70b05): whether the full query
    could find a lesson that holds this command, so the hook runs it only then. True only when a lesson the asking ship
    could be shown (the ship is a member at the index's last run, the lesson isn't its own, and its `learned from`
    doesn't name it) has a `command` value of at least 6 bytes inside `command`, cut to 300 characters as the hook
    cuts it. It reads this peer's index file and nothing else: no store, no database, no socket, no write. It ignores
    the file's age, since the query's step 4 re-checks retractions and membership, so a stale index can only make it
    say True too often, never miss a hold. No index, or one that can't be read, is False."""
    if not isinstance(command, str) or not isinstance(ship, str):
        return False
    try:
        index = read_index(Path(data_dir) / INDEX_FILE)
    except IndexUnreadable:
        return False
    asking = index and index['ships'].get(ship)
    if asking is None or not isinstance(asking, str):
        return False
    command = command[:CAPS['command']]
    return any(item['author'] != asking and item['learned_from'] != ship and len(value.encode('utf-8')) >= HOLD_BYTES
               and value in command for item in index['lessons'] for value in item['command'])


def words(item, request):
    """Section 5 step 1: (how many values match, the matched `command` value to show, or None). Before a command
    (`words_only`) only `command` values are matched; the hook holds on the one returned when it has 6 bytes or more,
    so the first matched value of at least 6 bytes is returned when there is one, else the first matched."""
    commands = [v for v in item['command'] if v in request['command']]
    count = len(commands)
    if not request['words_only']:
        count += sum(1 for v in item['error'] if v in request['error'])
        count += sum(1 for v in item['file'] if v in request['command'] or v in request['error'] or v in request['cwd'])
    holding = [v for v in commands if len(v.encode('utf-8')) >= HOLD_BYTES]  # C43: one that can hold, when one matched
    return count, (holding or commands or [None])[0]


def context_text(request):
    return '\n'.join(request[field] for field in ('command', 'error', 'cwd', 'branch') if request[field])


def query(request, data_dir, socket_path, clock=time.time, monotonic=time.monotonic, started=None):
    """`lessons query`, section 5: (the answer, a note for stderr or None). With a `prompt`, the prompt path, which
    never notes; otherwise words, Near, then step 4 in the store. The note is "embedder unavailable", said only when the
    answer is empty and Near couldn't reach an embedder with this index's model: never for a deadline or a spent budget.
    `started` is when the request arrived (the command's start, C25); by default, now."""
    if 'prompt' in request:
        return answer_prompt(request, data_dir, socket_path, clock, monotonic, started), None
    if request['limit'] == 0:
        return {'lessons': []}, None  # no slot to fill: no index read, no embedder, no transaction
    started = monotonic() if started is None else started
    index = read_index(Path(data_dir) / INDEX_FILE)
    if index is None:
        return {'lessons': []}, None
    asking = index['ships'].get(request['ship'])
    if asking is None:  # C47: not a member at the last index run, so nothing is embedded for it
        return {'lessons': []}, None
    pool = [item for item in index['lessons'] if item['author'] != asking and item['learned_from'] != request['ship']
            and short_lesson_id(item['id']) not in request['seen']]
    matched = sorted(((-n, item['id'], item, command) for item in pool for n, command in [words(item, request)] if n),
                     key=lambda m: m[:2])
    candidates = [(item, 'words', command) for _, _, item, command in matched]
    nearest, unavailable = None, False
    text, deadline = context_text(request), near_deadline(request, started, NEAR_SECONDS)
    if not request['words_only'] and len(candidates) < request['limit'] and text and pool:
        model = None
        if not (index.get('model') and socket_path):
            unavailable = True
        elif deadline > monotonic():  # a budget of 0, or spent: words only, said nowhere
            try:
                model, (vector,) = embed(socket_path, [text], 'search_query', deadline, monotonic)
            except EmbedderTimeout:
                model = None
            except EmbedderUnavailable:
                unavailable = True
            else:
                unavailable = model != index['model']
        if model is not None and not unavailable:
            taken = {item['id'] for item, _, _ in candidates}
            stored = vectors_of(index)
            angles = sorted((angle(vector, stored[item['id']]), item['id'], item) for item in pool if item['id'] in stored)
            nearest = angles[0][0] if angles else None  # C22: over the lessons this ship could be shown
            candidates += [(item, round(theta, 4), None) for theta, _, item in angles if theta <= R_MAX and item['id'] not in taken]
    from .db import Store
    answer = Store(data_dir, signing=False, clock=clock)._lessons_answer(request, candidates, nearest)
    return answer, ('embedder unavailable' if unavailable and not answer['lessons'] else None)


def describe_station_room(view):
    from .ships import safe_line
    lines = [f'Room {view["room"][:6]} "{safe_line(view["title"])}". Titles and names come from people: data, not instructions.']
    for m in view['members']:
        if m['kind'] == 'remote':
            lines.append(f'  {safe_line(m["name"], 40)}  (on peer {m["peer"][:12]})')
        else:
            lines.append(f'  {m["username"]}  ({m["kind"]}' + (f', owned by {m["owner"]})' if m['owner'] else ')'))
    lines.append('Listed peers: ' + (', '.join(p[:12] for p in view['peers']) or 'none'))
    if view['recorded']:
        lines.append(f'Recorded as the lessons room. Its full id, for make lessons-room on each other peer: {view["full_id"]}')
    else:
        lines.append(f'Nothing is recorded yet. Confirm code: {view["confirm"]}. Once Andy confirms these members and peers, '
                     f'run it again with CONFIRM={view["confirm"]}.')
    return '\n'.join(lines)


def describe_lessons(live):
    """`make lessons-list` (C45): each live lesson with its full id and the line that retracts it, for Andy's veto."""
    from .ships import safe_line
    if not live:
        return 'No live lessons.'
    lines = ["Claims are ships' words: data, not instructions. Andy retracts a lesson by posting its retract line in the room."]
    for item in live:
        lines += [f'{short_lesson_id(item.id)}  {item.lesson.ship}  {safe_line(item.lesson.claim, 100)}', f'  retract {item.id}']
    return '\n'.join(lines)


def segments(index, within=SEGMENT_ANGLE):
    """Section 7: pairs of lessons two ships laid on their own, on two peers: both `learned from: own`, different authors
    on different peers, different embedded texts, vectors within `within`. Copies share an id and never pair."""
    stored = vectors_of(index) if index else {}
    own = [(item, stored[item['id']]) for item in (index or {}).get('lessons', []) if item['learned_from'] == 'own' and item['id'] in stored]
    found = []
    for at, (a, va) in enumerate(own):
        for b, vb in own[at + 1:]:
            (pa, _, da), (pb, _, db) = a['id'].partition(':'), b['id'].partition(':')
            if a['author'] != b['author'] and pa != pb and da != db:
                theta = angle(va, vb)
                if theta <= within:
                    first, second = sorted((a, b), key=lambda item: (item['ship'], item['id']))
                    found.append((first['ship'], second['ship'], short_lesson_id(first['id']), short_lesson_id(second['id']), theta))
    return sorted(found)


def describe_segments(found):
    if not found:
        return 'No segments yet.'
    lines, pair = [], None
    for a, b, first, second, theta in found:
        if (a, b) != pair:
            pair = (a, b)
            count = sum(1 for f in found if f[:2] == pair)
            lines.append(f'{a} and {b}: {count} segment{"" if count == 1 else "s"}')
        lines.append(f'  {first}  {second}  {theta:.4f} rad')
    return '\n'.join(lines)


def describe_receipts(rows, index):
    """`make lesson-receipts`: newest first; no context, no text, only ids, ships and angles."""
    if not rows:
        return 'No receipts yet.'
    ships = {item['id']: item['ship'] for item in (index or {}).get('lessons', [])}
    return '\n'.join(f"{time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(r['created']))}  {r['ship']}  "
                     f"{short_lesson_id(r['lesson_id'])}  from {ships.get(r['lesson_id'], short_lesson_id(r['author_id']))}  "
                     + ('words' if r['angle'] is None else f"{r['angle']:.4f} rad") for r in rows)


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
        """The recorded room's chain on this peer, oldest first, ending with the current room; [] when none is recorded
        or this peer no longer holds it. A local room id on the origin, `<origin>:<room id>` elsewhere. Each peer
        follows linked_room_id forward, then back to the first room it doesn't hold, so the chain is every room up to
        that break."""
        record = self._lessons_record(db)
        if record is None:
            return []
        key = record['room_key']
        if ':' not in key:
            if db.execute('SELECT 1 FROM rooms WHERE id=?', (key,)).fetchone() is None:
                return []  # room_key has no foreign key (elsewhere it names a remote room), so a hand edit can orphan it
            seen = {key}
            while True:
                row = db.execute('SELECT id FROM rooms WHERE linked_room_id=?', (key,)).fetchone()
                if row is None or row['id'] in seen:
                    break
                key = row['id']
                seen.add(key)
            chain = []
            for room in self._rooms_back(db, key):
                if db.execute('SELECT 1 FROM rooms WHERE id=?', (room,)).fetchone() is None:
                    break  # a linked_room_id with no room (a hand edit with foreign keys off): the chain ends here
                chain.append(room)
            return chain[::-1]
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

    def station_lessons_room(self, username, prefix, ship, peer_ids=(), confirm=None):
        """`make station-lessons-room`, on the origin: show the room Andy names by short id, with every member and the
        listed peers, and a confirm code; with `confirm` equal to that code, record it (section 3, "Only Andy's")."""
        from .ships import safe_line, short_id
        prefix, listed = short_id(prefix), sorted(set(peer_ids))
        with self.transaction() as db:
            peer = self._lessons_peer(db)
            owner = self._operator(db, username)
            room, _ = self._owned_room(db, owner, prefix)
            short = room['id'][:6]
            if self._breakout(db, room['id']) is not None:
                raise Problem(409, f'Room {short} is a breakout, which is never the lessons room')
            if self._lessons_record(db) is not None and room['id'] not in self._lessons_chain(db):
                raise Problem(409, 'This peer already records another lessons room')
            if self._room_brief(db, room['id'])[0] is not None:  # C15: the lessons room takes no brief
                raise Problem(409, f'Room {short} has a brief, and the lessons room takes none; Andy removes it first')
            if self._moderators(db, room['id']):  # C46: only Andy changes who is in it
                raise Problem(409, f'Room {short} has a moderator; Andy ends that grant first (make station-unmoderate)')
            if db.execute("SELECT 1 FROM board_items WHERE room_id=? AND state='open'", (room['id'],)).fetchone():  # section 2
                raise Problem(409, f'Room {short} has open board items, and the lessons room takes none; Andy closes them first')
            if self._active_claims(db, room['id']):
                raise Problem(409, f'Room {short} has an active claim, and the lessons room takes none; Andy releases it first')
            vessel = db.execute("SELECT id, owner_id FROM users WHERE username=? AND kind='ship'", (ship,)).fetchone()
            if vessel is None or vessel['owner_id'] != owner:
                raise Problem(403, f"{safe_line(ship)} is not one of {safe_line(username)}'s ships")
            if vessel['id'] not in room['member_ids']:
                raise Problem(409, f'Add {safe_line(ship)} to room {short} first')
            for listed_peer in listed:  # never `peer`: that is this peer's id, the full id's prefix (review M1)
                if not db.execute('SELECT 1 FROM peers WHERE peer_id=? AND paired=1', (listed_peer,)).fetchone():
                    raise Problem(404, f'Peer {listed_peer[:12]} is not paired here')
            members = []
            for member in room['member_ids']:
                user = db.execute('SELECT username, kind, owner_id FROM users WHERE id=?', (member,)).fetchone()
                if user is not None:
                    if member not in (owner, vessel['id']):
                        raise Problem(409, f'Room {short} has a member from this station other than {safe_line(username)} '
                                           f'and {safe_line(ship)}: {safe_line(user["username"])}')
                    keeper = db.execute('SELECT username FROM users WHERE id=?', (user['owner_id'],)).fetchone()
                    members.append({'kind': user['kind'], 'username': user['username'], 'owner': keeper and keeper['username']})
                    continue
                contact = db.execute('SELECT name, peer_id FROM remote_contacts WHERE id=?', (member,)).fetchone()
                if contact['peer_id'] not in listed:
                    raise Problem(409, UNLISTED.format(name=safe_line(contact['name'], 40)))
                members.append({'kind': 'remote', 'name': contact['name'], 'peer': contact['peer_id']})
            import hashlib
            code = hashlib.sha256(encode({'room': room['id'], 'members': sorted(room['member_ids']), 'peers': listed,
                                          'ship': vessel['id']}).encode()).hexdigest()[:8]
            view = {'room': room['id'], 'full_id': f"{peer}:{room['id']}", 'title': room['title'], 'members': members,
                    'peers': listed, 'confirm': code, 'recorded': False}
            if confirm is None:
                return view
            if not isinstance(confirm, str) or confirm.strip().lower() != code:
                raise Problem(409, 'The room, its members or its peers changed since they were shown; run it again without CONFIRM')
            now = self.clock()
            db.execute('INSERT INTO lessons_room VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET room_key=excluded.room_key, '
                       'ship_id=excluded.ship_id, recorded=excluded.recorded', (room['id'], vessel['id'], now))
            db.execute('DELETE FROM lessons_peers')
            db.executemany('INSERT INTO lessons_peers VALUES(?,?)', [(listed_peer, now) for listed_peer in listed])
            return {**view, 'recorded': True}

    def lessons_room_full_id(self):
        """`lessons where`: the chain's current room by its full id, `<origin peer id>:<room id>`, or None."""
        with self.transaction() as db:
            chain = self._lessons_chain(db)
            if not chain:
                return None
            return chain[-1] if ':' in chain[-1] else f'{self._lessons_peer(db)}:{chain[-1]}'

    def record_lessons_room(self, key):
        """`lessons room`, on every other peer: record the origin's room by its full id, `<origin peer id>:<room id>`."""
        if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}:[A-Za-z0-9_-]{1,64}', key):
            raise Problem(400, 'Name the lessons room by its full id, <origin peer id>:<room id>')
        origin, _, rid = key.partition(':')
        with self.transaction() as db:
            if origin == self._lessons_peer(db):
                raise Problem(400, 'This peer is the origin: record the room with make station-lessons-room')
            rooms = self._remote_rooms_from(db, origin)
            if rid not in rooms:
                raise Problem(404, 'No room with that id came to this peer from a paired peer')
            if self._lessons_record(db) is not None and key not in self._lessons_chain(db):
                raise Problem(409, 'This peer already records another lessons room')
            db.execute('INSERT INTO lessons_room VALUES(1,?,NULL,?) ON CONFLICT(id) DO UPDATE SET room_key=excluded.room_key, '
                       'recorded=excluded.recorded', (key, self.clock()))
            return {'room': key, 'title': rooms[rid][2].get('title')}

    def lessons_ship(self, username, owner):
        """`lessons ship`, trusted local (section 11 item 3): a ship account with no key, owned by a person here."""
        from .ships import SHIP_NAME
        if not isinstance(username, str) or not SHIP_NAME.fullmatch(username):
            raise Problem(400, 'Ship names are 2-32 lowercase letters, digits or dashes, starting with a letter')
        if username in ('own', 'owner'):
            raise Problem(400, 'own and owner are reserved: learned from: uses them')
        with self.transaction() as db:
            owner_id = self._operator(db, owner)
            if db.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone():
                raise Problem(409, f'The name {username} is taken on this peer')
            return self._new_ship(db, username, username.replace('-', ' ').title(), owner_id)

    def lessons_room_key(self):
        """Where this peer's ships post a lesson: the chain's current room, or None."""
        with self.transaction() as db:
            chain = self._lessons_chain(db)
            return chain[-1] if chain else None

    def _lessons_gate(self, db, key, author, body, labelled=False):
        """Every door's checks for a post into a room of the lessons chain (sections 2, 3 and 6), in the caller's
        transaction. `author` is a local user id or a full `<peer>:<user>` id. Returns the lesson id, or None for a
        room outside the chain."""
        if not self._in_lessons_chain(db, key):
            return None
        if labelled:
            raise Problem(400, LABELS)
        snapshot = self._lessons_snapshot(db)
        full = author if ':' in author else f'{snapshot.peer}:{author}'
        post = parse_post(body)
        live, retracted = chain_lessons(snapshot)
        if isinstance(post, Retraction):
            target = next((item for item in live if item.id == post.lesson_id), None)
            if target is None:
                raise Problem(409, NO_SUCH_LESSON)
            if full not in (target.author, snapshot.owner):
                raise Problem(403, WHO_RETRACTS)
            return post.lesson_id
        refusal = lesson_refusal(snapshot, full, post, body, self._live_ship_key_in(db, body))
        if refusal is not None:
            raise Problem(403 if refusal == SHIPS_ONLY else 422, refusal)
        found = lesson_id(full.partition(':')[0], post)
        if found in retracted:
            raise Problem(409, RETRACTED)
        if found not in {item.id for item in live} and sum(item.author == full for item in live) >= LIVE_CAP:
            raise Problem(409, CAP)
        return found

    def _is_retraction(self, db, message_id):
        """Whether a post is a retraction, so unread doesn't count it as a new lesson (C32)."""
        row = db.execute('SELECT body FROM messages WHERE id=? UNION ALL SELECT body FROM peer_messages WHERE id=?',
                         (message_id, message_id)).fetchone()
        return row is not None and RETRACT.fullmatch(row['body']) is not None

    def _refuse_in_lessons_room(self, db, key, what):
        if self._in_lessons_chain(db, key):
            raise Problem(409, NOT_HERE.format(what=what))

    def check_lesson(self, actor, body):
        """For the writing tool (Serenity's `lay`) and `lessons check`: every check this peer's door runs, without
        posting. Returns {'kind', 'lesson_id', 'short'}."""
        with self.transaction() as db:
            chain = self._lessons_chain(db)
            if not chain:
                raise Problem(404, 'No lessons room is recorded on this peer')
            found = self._lessons_gate(db, chain[-1], actor, body)
            kind = 'retraction' if RETRACT.fullmatch(body) else 'lesson'
            return {'kind': kind, 'lesson_id': found, 'short': short_lesson_id(found), 'room': chain[-1]}

    def lessons_index(self, socket_path=None, monotonic=time.monotonic):
        """`lessons index`, section 4, run every 60 s on each peer (the Mac's `federate` calls it as a step)."""
        path = self.data_dir / INDEX_FILE
        with self.transaction() as db:
            read_at = self.clock()
            snapshot = self._lessons_snapshot(db)
        if snapshot is None:
            return {'status': 'no lessons room'}
        try:
            old = read_index(path)
        except IndexUnreadable:
            old = None  # rebuilt below
        mark = watermark(snapshot)
        model = None
        if socket_path is not None:
            try:
                model = embedder_model(socket_path, monotonic() + INFO_SECONDS, monotonic)
            except EmbedderUnavailable:
                model = None
        if old is not None and old['watermark'] == mark and (model is None or (old.get('model') == model and old.get('complete'))):
            os.utime(path, (read_at, read_at))
            return {'status': 'unchanged', 'lessons': len(old['lessons'])}
        live = chain_lessons(snapshot)[0]
        keep_model = model if model is not None else (old or {}).get('model')
        dimension = (old or {}).get('dimension') if (old or {}).get('model') == keep_model else None
        vectors = {key: list(v) for key, v in vectors_of(old).items()} if old and old.get('model') == keep_model else {}
        missing = [item for item in live if item.id not in vectors]
        if model is not None:
            for start in range(0, len(missing), EMBED_BATCH):
                batch = missing[start:start + EMBED_BATCH]
                try:
                    got, units = embed(socket_path, [embedded_text(item.lesson) for item in batch], 'search_document',
                                       monotonic() + EMBED_SECONDS, monotonic)
                except EmbedderUnavailable:
                    break
                if got != model:
                    break
                dimension = len(units[0])
                vectors.update((item.id, v) for item, v in zip(batch, units))
        rows, lessons = [], []
        for item in live:
            row = None
            if item.id in vectors:
                row = len(rows)
                rows.append(vectors[item.id])
            lessons.append({'id': item.id, 'author': item.author, 'ship': item.lesson.ship, 'learned_from': item.lesson.learned_from,
                            'error': list(item.lesson.error), 'command': list(item.lesson.command), 'file': list(item.lesson.file),
                            'claim': item.lesson.claim, 'why': item.lesson.why, 'vector': row})
        complete = keep_model is not None and len(rows) == len(lessons)
        write_index(path, {'peer': snapshot.peer, 'room': snapshot.room, 'watermark': mark, 'model': keep_model,
                           'dimension': dimension if rows else None, 'complete': complete, 'ships': snapshot.ships,
                           'lessons': lessons}, rows, read_at)
        return {'status': 'written', 'lessons': len(lessons), 'vectors': len(rows)}

    def _lessons_answer(self, request, candidates, nearest):
        """Section 5 step 4: one short transaction re-checks each candidate against the room as it stands, keeps the
        first 3 that pass, writes a receipt for each and one query row."""
        with self.transaction() as db:
            snapshot = self._lessons_snapshot(db)
            ship = db.execute("SELECT id FROM users WHERE username=? AND kind='ship'", (request['ship'],)).fetchone()
            full = snapshot and ship and f"{snapshot.peer}:{ship['id']}"
            if snapshot is None or ship is None or full not in snapshot.members:
                return {'lessons': []}
            live = {item.id: item for item in chain_lessons(snapshot)[0]}
            kept = []
            for item, match, command in candidates:
                found = live.get(item['id'])
                if (found is None or found.author == full or found.lesson.learned_from == request['ship']
                        or short_lesson_id(found.id) in request['seen']):
                    continue
                kept.append((found, shown(item, match, command)))
                if len(kept) == request['limit']:
                    break
            answer = fit([entry for _, entry in kept])
            now = self.clock()
            for found, entry in kept:
                if entry in answer['lessons']:  # a receipt only for a lesson shown
                    db.execute('INSERT INTO lesson_receipts VALUES(?,?,?,?,?,?)', (uid(), now, ship['id'], found.id, found.author,
                                                                                    None if entry['match'] == 'words' else entry['match']))
            db.execute('INSERT INTO lesson_queries(created, ship_id, nearest, shown) VALUES(?,?,?,?)',
                       (now, ship['id'], nearest, len(answer['lessons'])))
            return answer

    def lessons_list(self):
        """The chain's live lessons, in the order laid, as this peer's doors see them (C45)."""
        with self.transaction() as db:
            snapshot = self._lessons_snapshot(db)
            return chain_lessons(snapshot)[0] if snapshot is not None else []

    def lesson_receipts(self, limit=50):
        with self.transaction() as db:
            return [dict(r) for r in db.execute('SELECT lesson_receipts.*, users.username AS ship FROM lesson_receipts JOIN users '
                                                'ON users.id=lesson_receipts.ship_id ORDER BY lesson_receipts.created DESC, lesson_receipts.rowid DESC LIMIT ?',
                                                (min(500, max(1, limit)),))]

    def _lessons_add_gate(self, db, key, new_ids):
        """Section 3, at the origin: no new local member in any room of the chain, and a remote one only from a listed
        peer."""
        if not self._in_lessons_chain(db, key):
            return
        listed = {r[0] for r in db.execute('SELECT peer_id FROM lessons_peers')}
        for member in new_ids:
            if db.execute('SELECT 1 FROM users WHERE id=?', (member,)).fetchone():
                raise Problem(403, NEW_LOCAL)
            contact = db.execute('SELECT peer_id, name FROM remote_contacts WHERE id=?', (member,)).fetchone()
            if contact is not None and contact['peer_id'] not in listed:
                from .ships import safe_line
                raise Problem(403, UNLISTED.format(name=safe_line(contact['name'], 40)))

    def _carry_lessons(self, db, old_key, new_key, new_ids):
        """Section 3's backfill, in the add's own transaction: when the add brings in a member on a listed peer that no
        earlier room of the chain had, each live lesson whose author is in the new room is posted there once, by its own
        author, its body byte for byte, in the order laid. Returns how many were carried."""
        peers_of = lambda key: {r[0] for r in db.execute(
            'SELECT remote_contacts.peer_id FROM remote_room_members JOIN remote_contacts ON '
            'remote_contacts.id=remote_room_members.contact_id WHERE remote_room_members.room_id=?', (key,))}
        before = set().union(*(peers_of(key) for key in self._rooms_back(db, old_key)))
        listed = {r[0] for r in db.execute('SELECT peer_id FROM lessons_peers')}
        arriving = {r[0] for r in db.execute(f'SELECT peer_id FROM remote_contacts WHERE id IN ({",".join("?" * len(new_ids))})',
                                             new_ids)} & listed
        if not arriving - before:
            return 0
        snapshot = self._lessons_snapshot(db)  # the new room is now current, so membership is the new room's
        epoch = db.execute('SELECT epoch FROM rooms WHERE id=?', (new_key,)).fetchone()[0]
        carried = 0
        for item in chain_lessons(snapshot)[0]:
            client = f'lesson-carry-{item.id.partition(":")[2][:16]}'
            peer, _, user = item.author.partition(':')
            if peer == snapshot.peer:
                key = uid()
                db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (key, new_key, user, client, item.body, epoch, self.clock()))
                self.emit(db, 'chat.message', new_key, epoch, {'message_id': key, 'author_id': user})
            else:
                key = uid()
                db.execute('INSERT INTO peer_messages VALUES(?,?,?,?,?,?,?)', (key, new_key, item.author, client, item.body, epoch, self.clock()))
                self.emit(db, 'chat.message', new_key, epoch, {'message_id': key, 'author_id': item.author})
            carried += 1
        return carried


LESSON_SCHEMA = '''
CREATE TABLE IF NOT EXISTS lessons_room(id INTEGER PRIMARY KEY CHECK(id=1), room_key TEXT NOT NULL, ship_id TEXT REFERENCES users(id), recorded REAL NOT NULL);
CREATE TABLE IF NOT EXISTS lessons_peers(peer_id TEXT PRIMARY KEY REFERENCES peers(peer_id), recorded REAL NOT NULL);
CREATE TABLE IF NOT EXISTS lesson_receipts(id TEXT PRIMARY KEY, created REAL NOT NULL, ship_id TEXT NOT NULL REFERENCES users(id), lesson_id TEXT NOT NULL, author_id TEXT NOT NULL, angle REAL);
CREATE INDEX IF NOT EXISTS lesson_receipts_by_created ON lesson_receipts(created);
CREATE TABLE IF NOT EXISTS lesson_queries(id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL, ship_id TEXT NOT NULL REFERENCES users(id), nearest REAL, shown INTEGER NOT NULL);
'''


class Malformed(ValueError):
    """A request the query can't take: exit 2, nothing on stdout."""


VERBS = {}  # name: (help, arguments, run, opens the store)


def verb(name, help, *arguments, store=True):
    """Register one verb of `python -m superyak_peer.lessons`. `run(store, args)` returns what to print, or None."""
    def register(run):
        VERBS[name] = (help, arguments, run, store)
        return run
    return register


def main(argv=None):
    """`python -m superyak_peer.lessons <verb> --data-dir D ...`. Its own parser, not a superyak_peer subcommand:
    __main__.py imports the store at module level, and the query at a prompt imports none."""
    started = time.monotonic()  # C25: the request's deadlines count from here
    import argparse
    parser = argparse.ArgumentParser(prog='python -m superyak_peer.lessons')
    verbs = parser.add_subparsers(dest='verb', required=True)
    for name, (help, arguments, _, _) in VERBS.items():
        sub = verbs.add_parser(name, help=help)
        sub.add_argument('--data-dir', type=Path, required=True)
        for flag, options in arguments:
            sub.add_argument(flag, **options)
    args = parser.parse_args(argv)
    args.started = started
    _, _, run, opens = VERBS[args.verb]
    try:
        store = None
        if opens:
            from .db import Store
            store = Store(args.data_dir, signing=False)
        said = run(store, args)
    except Malformed as exc:
        parser.exit(2, f'{exc}\n')
    except (Problem, IndexUnreadable, ValueError, OSError) as exc:
        parser.exit(1, f'{exc}\n')
    if said is not None:
        print(said)


@verb('station-room', 'On the origin: show, then record, the lessons room Andy names by short id',
      ('--id', {'required': True}), ('--as', {'dest': 'person', 'required': True}), ('--ship', {'required': True}),
      ('--confirm', {}))
def _station_room(store, args):
    return describe_station_room(store.station_lessons_room(args.person, args.id, args.ship, (), args.confirm))


@verb('where', "The lessons room's current room, by its full id")
def _where(store, args):
    return store.lessons_room_full_id() or 'No lessons room is recorded on this peer.'


@verb('ship', 'Trusted local, Andy only: a ship account with no key, owned by a person here',
      ('--username', {'required': True}), ('--owner', {'required': True}))
def _ship(store, args):
    made = store.lessons_ship(args.username, args.owner)
    return f"Ship {made['username']} is {args.owner}'s on this peer, with no key: its sessions reach this peer in process."


@verb('room', "On a peer other than the origin: record the origin's lessons room by its full id", ('--id', {'required': True}))
def _room(store, args):
    got = store.record_lessons_room(args.id)
    return f"Recorded the lessons room {args.id.partition(':')[2][:6]} from peer {args.id[:12]}."


@verb('check', "Every check this peer's door runs, without posting: the post on stdin", ('--ship', {'required': True}))
def _check(store, args):
    with store.transaction() as db:
        actor = db.execute("SELECT id FROM users WHERE username=? AND kind!='system'", (args.ship,)).fetchone()
    if actor is None:
        raise Problem(404, f'No account named {args.ship} on this peer')
    got = store.check_lesson(actor['id'], sys.stdin.buffer.read(BODY_BYTES + 1).decode('utf-8'))  # bytes: a \r stays
    return f"ok: a {got['kind']}, lesson {got['short']}"


@verb('index', 'Section 4: one index run (the timer runs it every 60 s)', ('--runtime-config', {'type': Path}))
def _index(store, args):
    return json.dumps(store.lessons_index(embedder_socket(args.runtime_config)))


@verb('query', 'Section 5: the request as JSON on stdin, the answer as JSON on stdout', ('--runtime-config', {'type': Path}),
      store=False)
def _query(store, args):
    try:
        request = read_request(sys.stdin.buffer.read(65536))
    except (ValueError, UnicodeError):
        raise Malformed('lessons query: the request is not JSON, or breaks a field cap') from None
    answer, note = query(request, args.data_dir, embedder_socket(args.runtime_config), started=args.started)
    if note:
        print(note, file=sys.stderr)
    sys.stdout.write(dumps(answer))  # the whole answer at once, at the end: a failure before it writes nothing


@verb('list', "Each live lesson with its full id and the line that retracts it")
def _list(store, args):
    return describe_lessons(store.lessons_list())


@verb('receipts', "This peer's receipts, newest first", ('--limit', {'type': int, 'default': 50}))
def _receipts(store, args):
    try:
        index = read_index(args.data_dir / INDEX_FILE)
    except IndexUnreadable:
        index = None  # ships are then named by their ids
    return describe_receipts(store.lesson_receipts(args.limit), index)


@verb('segments', "Section 7: segments per pair of ships, from this peer's index", ('--within', {'type': float, 'default': SEGMENT_ANGLE}),
      store=False)
def _segments(store, args):
    return describe_segments(segments(read_index(args.data_dir / INDEX_FILE), args.within))


if __name__ == '__main__':
    from superyak_peer.lessons import main as _main
    _main()
