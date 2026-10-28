"""The lessons side of the shared hold entry before a Bash command (first rail spec section 8, decision 8).

The entry (`run_agent.py hold`, Serenity's) asks candidates() for the holds it may make, then denies, records each
hold it makes and keeps the cap of 3 a session. This side keeps the rest: the head, the head's first appearance, words
only, the 1 s limit, SUPERYAK_RUN, unseen lessons only, and a `command` value of at least 6 bytes. It writes nothing.

`record` is the entry's per-session record, read only. The provider reads:
- `session_id`: the Claude Code session's id;
- `transcript_path`: the event's transcript, where the lessons shown at a prompt are read back (section 8);
- `heads`: the head_digest() of every command seen earlier in the session, which the entry records;
- `holds`: the keys of the holds made in the session (strings, or objects with a `key`)."""
import math
import os
import time

from . import lessons_hook as lh

KIND = 'lesson'
HOLD_BYTES = 6  # only a `command` value of at least 6 bytes holds a command (section 8)
MAX_LIMIT = 3


def head_digest(command):
    """The SHA-256 of the command's head (lessons_hook.head), or None when it has none."""
    head = lh.head(command) if isinstance(command, str) else None
    return lh.digest(head) if head else None


def hold_key(session_id, digest, lesson_id):
    """A hold's key in the entry's record: the session, the head's digest and the lesson (section 8)."""
    return f'{KIND}:{lh.session_key(session_id)}:{digest}:{lesson_id}'


def _held(record):
    """(head digests, lesson ids) of the lesson holds the record names."""
    holds = record.get('holds')
    heads, ids = set(), []
    for item in holds if isinstance(holds, list) else ():
        key = item.get('key') if isinstance(item, dict) else item
        parts = key.split(':') if isinstance(key, str) else []
        if len(parts) == 4 and parts[0] == KIND and lh.SHORT_ID.fullmatch(parts[3]):
            heads.add(parts[2])
            ids.append(parts[3])
    return heads, ids


def candidates(command, record, now, limit, *, settings=None, env=None, monotonic=time.monotonic):
    """[{kind: "lesson", key, text}]: at most `limit` holds for this command, each with section 8's reason for one
    lesson, or [] whenever anything is missing, late or wrong. `now` is when the entry began, on time.monotonic():
    the second counts from it (from here, if it isn't a monotonic time). Limit 0 asks nothing."""
    try:
        return _candidates(command, record, now, limit, settings, os.environ if env is None else env, monotonic)
    except Exception:  # noqa: BLE001 - a hold that can't be worked out is no hold; the command runs
        return []


def _candidates(command, record, now, limit, settings_path, env, monotonic):
    started = monotonic()
    if env.get('SUPERYAK_RUN') not in (None, '', 'hook'):
        return []  # a watcher or teamd run never queries (section 8)
    if type(limit) is not int or not 0 < limit <= MAX_LIMIT or not isinstance(record, dict):
        return []
    session, digest = record.get('session_id'), head_digest(command)
    if not isinstance(session, str) or not session or digest is None:
        return []
    heads = record.get('heads')
    held_heads, held_ids = _held(record)
    if digest in held_heads or (isinstance(heads, list) and digest in heads):
        return []  # only a head's first appearance asks, so a re-run passes straight through
    began = now if type(now) in (int, float) and math.isfinite(now) else started
    deadline = min(began, started) + lh.COMMAND_LIMIT
    settings = lh.read_settings(settings_path or lh.default_settings())
    if settings is None:
        return []
    own = lh.strings(lh.read_state(lh.state_path(settings, session)), 'shown')
    shown_there = lh.transcript_ids(record.get('transcript_path'), deadline, monotonic=monotonic)
    if shown_there is None:
        return []  # a transcript not read to its end holds nothing
    seen = lh.seen_list(own, sorted(shown_there), held_ids)
    cut = command[:lh.CUTS['command']]
    request = {'ship': settings['ship'], 'command': cut, 'words_only': True, 'limit': limit,
               'seen': seen[-lh.SEEN_MAX:]}
    holds = []
    for lesson in lh.ask(settings, request, deadline, monotonic) or ():
        value = lesson.get('command')
        if lesson['id'] in seen or lesson['match'] != 'words' or not value or value not in cut \
                or len(value.encode('utf-8')) < HOLD_BYTES:
            continue
        holds.append({'kind': KIND, 'key': hold_key(session, digest, lesson['id']), 'text': lh.hold_reason(lesson)})
    return holds[:limit]
