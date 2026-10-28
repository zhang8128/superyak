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
