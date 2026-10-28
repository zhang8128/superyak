"""The lessons provider for the shared hold entry before a Bash command (first rail spec section 8, decision 8; the
seam's Rulings 31 to 36 in the checklists plan).

The entry (`run_agent.py hold`, Serenity's) asks candidates() for at most `limit` holds, renders every Hold it gets,
keeps the cap of 3 a session and saves the record only when it prints. This side keeps the rest: the head, the head's
first appearance, words only, the 1 s limit, SUPERYAK_RUN, unseen lessons only, a `command` value of at least 6 bytes
and LESSON_BYTES a lesson. It writes no file.

`record` is the entry's per-session record (`holds.open_record(...).data`). The provider reads `record['session']`,
which the entry sets: `id`, the Claude Code session's id, and `transcript`, where the lessons shown at a prompt are read
back (section 8). Its own entries are under `record['lessons']` (Ruling 33: a provider records what it returns):
- `heads`: the head_digest() of every command whose query answered;
- `holds`: the keys of the lesson holds it returned."""
import os
import time

from . import holds as hs, lessons_hook as lh

KIND = 'lesson'
HOLD_BYTES = 6  # only a `command` value of at least 6 bytes holds a command (section 8)
HEADS_MAX = 256  # a session's distinct heads; the oldest go first


def head_digest(command):
    """The SHA-256 of the command's head (lessons_hook.head), or None when it has none."""
    head = lh.head(command) if isinstance(command, str) else None
    return lh.digest(head) if head else None


def hold_key(session_id, digest, lesson_id):
    """A hold's key: the session, the head's digest and the lesson (section 8)."""
    return f'{KIND}:{lh.session_key(session_id)}:{digest}:{lesson_id}'


def _strings(value):
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _held(keys):
    """(head digests, lesson ids) of the lesson hold keys."""
    heads, ids = set(), []
    for key in keys:
        parts = key.split(':')
        if len(parts) == 4 and parts[0] == KIND and lh.SHORT_ID.fullmatch(parts[3]):
            heads.add(parts[2])
            ids.append(parts[3])
    return heads, ids


def candidates(command, record, now, limit, *, settings=None, env=None, monotonic=time.monotonic):
    """At most `limit` Hold('lesson', key, text) for this command, or [] whenever anything is missing, late or wrong.
    Limit 3 means no checklist leads this deny, so the first text starts with section 8's `Held once` line (Ruling 35).
    `now` is the entry's wall time; the second counts from this call."""
    try:
        return _candidates(command, record, limit, settings, os.environ if env is None else env, monotonic)
    except Exception:  # noqa: BLE001 - a hold that can't be worked out is no hold; the command runs
        return []


def _candidates(command, record, limit, settings_path, env, monotonic):
    deadline = monotonic() + lh.COMMAND_LIMIT
    if env.get('SUPERYAK_RUN') not in (None, '', 'hook'):
        return []  # a watcher or teamd run never queries (section 8)
    if type(limit) is not int or not 0 < limit <= hs.HOLDS_PER_SESSION or not isinstance(record, dict):
        return []
    session, digest = record.get('session'), head_digest(command)
    session_id = session.get('id') if isinstance(session, dict) else None
    if not isinstance(session_id, str) or not session_id or digest is None:
        return []
    mine = record.get('lessons') if isinstance(record.get('lessons'), dict) else {}
    heads, keys = _strings(mine.get('heads')), _strings(mine.get('holds'))
    held_heads, held_ids = _held(keys)
    if digest in held_heads or digest in heads:
        return []  # only a head's first appearance asks, so a re-run passes straight through
    settings = lh.read_settings(settings_path or lh.default_settings())
    if settings is None:
        return []
    own = lh.strings(lh.read_state(lh.state_path(settings, session_id)), 'shown')
    shown_there = lh.transcript_ids(session.get('transcript'), deadline, monotonic=monotonic)
    if shown_there is None:
        return []  # a transcript not read to its end holds nothing
    seen = lh.seen_list(own, sorted(shown_there), held_ids)
    cut = command[:lh.CUTS['command']]
    request = {'ship': settings['ship'], 'command': cut, 'words_only': True, 'limit': limit,
               'seen': seen[-lh.SEEN_MAX:]}
    answer = lh.ask(settings, request, deadline, monotonic)
    if answer is None:
        return []  # late or failing: the head may ask again
    got = []
    for lesson in answer:
        value = lesson.get('command')
        if lesson['id'] in seen or lesson['match'] != 'words' or not value or value not in cut \
                or len(value.encode('utf-8')) < HOLD_BYTES:
            continue
        text = lh.hold_reason(lesson, first=not got and limit == hs.HOLDS_PER_SESSION)
        if len(text.encode('utf-8')) > hs.LESSON_BYTES:
            continue  # the entry never cuts a Hold, so one over the provider's cap isn't offered (Ruling 34)
        got.append(hs.Hold(KIND, hold_key(session_id, digest, lesson['id']), text))
        if len(got) == limit:
            break
    record['lessons'] = {'heads': (heads + [digest])[-HEADS_MAX:], 'holds': keys + [hold.key for hold in got]}
    return got
