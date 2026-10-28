"""The checklist file format: parsed exactly, read without following links or blocking.

Standard library only: the hold imports this module and must stay on the light path.
"""
import errno
import os
import re
import stat
from pathlib import Path
from typing import NamedTuple

ID = re.compile(r'[a-z0-9-]{1,40}')
VERSION = re.compile(r'[1-9][0-9]{0,5}')
POST_ID = re.compile(r'[A-Za-z0-9:_.-]{1,200}')   # station's PLAIN_ID, pinned by a test
EVERY = re.compile(r'every ([1-9]|1[0-9]|2[0-4])h')

MAX_ITEMS, ITEM_BYTES, LABEL_BYTES, READ_BYTES, SEE_BYTES, FILE_BYTES, DIR_FILES, WORDS_BYTES = (
    12, 200, 80, 1500, 120, 4096, 32, 6)
LOG_NAMES = ('runs.jsonl', 'fired.jsonl', 'trusted.json')
ALL_HANDS = '1bfd1b03e9f94519b1bb3c86c0fafaa1'

REQUIRED = ('id', 'title', 'when', 'version', 'owner')
OPTIONAL = ('read', 'post', 'see')
ITEM_PREFIX = '- [ ] '


class Moment(NamedTuple):
    kind: str
    hours: int | None = None
    words: str | None = None
    path: str | None = None


class Checklist(NamedTuple):
    id: str
    title: str
    moments: tuple[Moment, ...]
    version: int
    owner: str
    read: bool
    post: str | None
    see: str | None
    items: tuple[str, ...]
    body: str
    raw: bytes


class ParseError(ValueError):
    """str(error) is the one-line reason a notice shows."""


def read_file(path: Path) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as error:
        if error.errno in (errno.ELOOP, getattr(errno, 'EMLINK', -1)):
            raise ParseError('a symlink') from None
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ParseError('not a regular file')
        data = os.read(fd, FILE_BYTES + 1)
        while len(data) <= FILE_BYTES:
            more = os.read(fd, FILE_BYTES + 1 - len(data))
            if not more:
                break
            data += more
    finally:
        os.close(fd)
    if len(data) > FILE_BYTES:
        raise ParseError('over 4 KiB')
    return data


def _text(value: str, what: str, limit: int) -> str:
    if not value or len(value.encode()) > limit:
        raise ParseError(f'{what} must be 1 to {limit} bytes')
    if not value.isprintable():
        raise ParseError(f'{what} has a control character')
    return value


def _moments(value: str, own: bool) -> tuple[Moment, ...]:
    found: list[Moment] = []
    for part in value.split('; '):
        if part in ('start', 'claim'):
            moment = Moment(part)
        elif EVERY.fullmatch(part):
            moment = Moment('every', hours=int(part[6:-1]))
        elif part == 'enter':
            if own:
                raise ParseError('enter in a ship\'s own directory needs an absolute path')
            moment = Moment('enter')
        elif part.startswith('enter '):
            path = part[6:]
            if not own or not os.path.isabs(path):
                raise ParseError('enter takes a path only in a ship\'s own directory, and it must be absolute')
            moment = Moment('enter', path=path)
        elif part.startswith('command '):
            words = part[8:]
            if (len(words.encode()) < WORDS_BYTES or ';' in words or words != words.strip()):
                raise ParseError('command words must be at least 6 bytes, with no ";" or edge spaces')
            moment = Moment('command', words=words)
        else:
            raise ParseError('unknown moment in when')
        if moment in found or (moment.kind in ('every', 'enter') and any(m.kind == moment.kind for m in found)):
            raise ParseError('a moment repeats in when')
        found.append(moment)
    return tuple(found)


def parse(name: str, data: bytes, own: bool) -> Checklist:
    if len(data) > FILE_BYTES:
        raise ParseError('over 4 KiB')
    if data.startswith(b'\xef\xbb\xbf'):
        raise ParseError('has a byte order mark')
    if b'\r' in data:
        raise ParseError('has CR line endings')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise ParseError('not UTF-8') from None
    if not text.endswith('\n'):
        raise ParseError('no final newline')
    lines = text[:-1].split('\n')
    if lines[0] != '---':
        raise ParseError('line 1 is not ---')
    try:
        close = lines.index('---', 1)
    except ValueError:
        raise ParseError('no closing ---') from None
    values: dict[str, str] = {}
    keys = []
    for line in lines[1:close]:
        key, sep, value = line.partition(': ')
        if not sep or not value or not key.isascii() or not key.isidentifier():
            raise ParseError('a front matter line is not "key: value"')
        if not value.isprintable():
            raise ParseError(f'{key} has a control character')
        if value[0] in '"\'':
            raise ParseError(f'{key} is quoted')
        keys.append(key)
        values[key] = value
    if tuple(keys[:5]) != REQUIRED:
        raise ParseError('front matter must start with id, title, when, version, owner, in that order')
    rest = keys[5:]
    order = [OPTIONAL.index(k) if k in OPTIONAL else -1 for k in rest]
    if -1 in order or order != sorted(set(order)):
        raise ParseError('optional keys are read, post, see, in that order, each once')

    list_id = values['id']
    if not ID.fullmatch(list_id):
        raise ParseError('id must be 1 to 40 of a-z, 0-9 and -')
    if name != list_id + '.md':
        raise ParseError('id does not match the file name')
    title = _text(values['title'], 'title', LABEL_BYTES)
    owner = _text(values['owner'], 'owner', LABEL_BYTES)
    if not VERSION.fullmatch(values['version']):
        raise ParseError('version must be a whole number from 1 to 999999')
    moments = _moments(values['when'], own)
    read = False
    if 'read' in values:
        if values['read'] != 'yes':
            raise ParseError('read takes only yes')
        read = True
    post = values.get('post')
    if post is not None and not POST_ID.fullmatch(post):
        raise ParseError('post is not a room id')
    see = values.get('see')
    if see is not None:
        _text(see, 'see', SEE_BYTES)
        if ' ' in see:
            raise ParseError('see has a space')

    body_lines = lines[close + 1:]
    if not body_lines:
        raise ParseError('no body')
    if read:
        body = '\n'.join(body_lines)
        if not body or len(body.encode()) > READ_BYTES:
            raise ParseError('a read body is 1 to 1500 bytes')
        if body_lines[-1] == '':
            raise ParseError('the body ends in a blank line')
        for line in body_lines:
            if not line.isprintable():
                raise ParseError('the body has a control character')
            if line.startswith(ITEM_PREFIX):
                raise ParseError('a read list has no checkbox lines')
        items: tuple[str, ...] = ()
    else:
        if not 1 <= len(body_lines) <= MAX_ITEMS:
            raise ParseError('a list holds 1 to 12 items')
        found = []
        for line in body_lines:
            if not line.startswith(ITEM_PREFIX):
                raise ParseError('every body line is "- [ ] " and an item')
            found.append(_text(line[len(ITEM_PREFIX):], 'an item', ITEM_BYTES))
        items, body = tuple(found), ''
    return Checklist(list_id, title, moments, int(values['version']), owner, read, post, see, items, body, data)
