"""The lessons provider for the shared hold entry before a Bash command (first rail spec section 8, decision 8; the
seam's Rulings 31 to 36 in the checklists plan).

The entry (`run_agent.py hold`, Serenity's) asks candidates() for at most `limit` holds, renders every Hold it gets,
keeps the cap of 3 a session and saves the record only when it prints. This side keeps the rest: the head, the head's
first appearance, words only, the time limit, SUPERYAK_RUN, unseen lessons only, a `command` value of at least 6 bytes
and LESSON_BYTES a lesson. It writes no file.

The time limit is the entry's: it gives up HOLD_SECONDS after its own start, when `now` was taken, and then the
process exits with nothing left to stop a query. So the query is stopped SAVE_MARGIN before that, never past this
side's own second, and its `budget_ms` counts to the same point (the reviews' M1 and M2, City of AI 2026-10-28).

The query opens the store (about 360 ms at the bound), so it runs only when the peer's `lessons.could_hold` says some
lesson's `command` value is in the command. That check reads only the index file, in process, as the prompt path does
(Rio Grande's Task 10). It can't miss a hold, since the query's words step holds on exactly that; when it can't answer,
nothing holds.

`record` is the entry's per-session record (`holds.open_record(...).data`). The provider reads `record['session']`,
which the entry sets: `id`, the Claude Code session's id, and `transcript`, where the lessons shown at a prompt are read
back (section 8). Its own entries are under `record['lessons']` (Ruling 33: a provider records what it returns):
- `heads`: the head_digest() of every command whose query answered;
- `holds`: the keys of the lesson holds it returned."""
import math
import os
import sys
import time

from . import checklist_firing as fp, holds as hs, lessons_hook as lh

KIND = 'lesson'
HOLD_BYTES = 6  # only a `command` value of at least 6 bytes holds a command (section 8)
# The tools the hold answers besides Bash (spec lesson-holds-on-tool-calls, item 3): a value equal to one holds only
# that tool's call, and no other value holds a tool call. It must equal the peer's lessons.HELD_TOOLS.
HELD_TOOLS = frozenset({'AskUserQuestion', 'mcp__station__station_post', 'mcp__station__station_claim'})
HEADS_MAX = 256  # a session's distinct heads; the oldest go first
START_MARGIN = lh.START_MARGIN
SAVE_MARGIN = 0.15  # before the entry gives up: its render, save and print once the provider has answered


def _contained(value, cut):
    """lessons.contained, on this side: a held tool's name only in a call to that tool, nothing else in one."""
    if value in HELD_TOOLS or cut in HELD_TOOLS:
        return value == cut
    return value in cut


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


def peer_could_hold(command, ship, data_dir, seen=()):
    """The peer checkout's `lessons.could_hold`, imported in process without writing bytecode, with `seen` (at most
    SEEN_MAX short ids) when there are any, and without it from a peer that doesn't take it; False when it can't say
    (no peer lessons module yet, or it failed)."""
    try:
        sys.dont_write_bytecode = True
        peer = str(lh.CHECKOUT / 'peer')
        if peer not in sys.path:
            sys.path.append(peer)
        from superyak_peer import lessons
        if seen:
            try:
                return lessons.could_hold(command, ship, data_dir, list(seen)) is True
            except TypeError:  # a peer from before `seen`: asked as before; the query is told `seen` and skips them
                pass
        return lessons.could_hold(command, ship, data_dir) is True
    except Exception:  # noqa: BLE001 - ImportError on a checkout without the rail, or anything it raises
        return False


def candidates(command, record, now, limit, *, settings=None, env=None, monotonic=time.monotonic, clock=time.time,
               could_hold=None):
    """At most `limit` Hold('lesson', key, text) for this command, or [] whenever anything is missing, late or wrong.
    Limit 3 means no checklist leads this deny, so the first text starts with section 8's `Held once` line (Ruling 35).
    `now` is the entry's wall time at its start (`clock`'s): the query stops SAVE_MARGIN before the entry gives up."""
    try:
        return _candidates(command, record, now, limit, settings, os.environ if env is None else env, monotonic,
                           clock, could_hold or peer_could_hold)
    except Exception:  # noqa: BLE001 - a hold that can't be worked out is no hold; the command runs
        return []


def deadline_of(now, monotonic, clock):
    """The provider's deadline on `monotonic`: SAVE_MARGIN before the entry gives up, HOLD_SECONDS after its start at
    `now`, and never more than this side's own COMMAND_LIMIT from this call. Both clocks are this process's."""
    at = monotonic()
    return min(at + lh.COMMAND_LIMIT, at + (now + fp.HOLD_SECONDS - SAVE_MARGIN - clock()))


def _candidates(command, record, now, limit, settings_path, env, monotonic, clock, could_hold):
    if type(now) not in (int, float) or not math.isfinite(now):
        return []
    deadline = deadline_of(now, monotonic, clock)
    if env.get('SUPERYAK_RUN') not in (None, '', 'hook'):
        return []  # a watcher or teamd run never queries (section 8)
    if type(limit) is not int or not 0 < limit <= hs.HOLDS_PER_SESSION or not isinstance(record, dict):
        return []
    if not isinstance(command, str):
        return []
    settings = lh.read_settings(settings_path or lh.default_settings())
    if settings is None:
        return []  # before anything reads the command: a ship without the lessons hook pays for nothing (S3)
    cut = command[:lh.CUTS['command']]
    session, digest = record.get('session'), head_digest(cut)
    session_id = session.get('id') if isinstance(session, dict) else None
    if not isinstance(session_id, str) or not session_id or digest is None:
        return []
    mine = record.get('lessons') if isinstance(record.get('lessons'), dict) else {}
    heads, keys = _strings(mine.get('heads')), _strings(mine.get('holds'))
    held_heads, held_ids = _held(keys)
    if digest in held_heads or digest in heads:
        return []  # only a head's first appearance asks, so a re-run passes straight through
    if could_hold(cut, settings['ship'], settings['data_dir']) is not True:
        return []  # no lesson's command value is in it: nothing more is read, no query, no receipt, nothing recorded

    def given_up():
        """A head that gave up after could_hold said yes may ask again, except a held tool's: its head never changes, so
        each later call would wait out the budget again, and on a loaded Pi nothing would ever be held (lesson-holds
        item 10, N-b). That head is recorded as asked."""
        if cut in HELD_TOOLS:
            record['lessons'] = {'heads': (heads + [digest])[-HEADS_MAX:], 'holds': keys}
        return []
    own = lh.strings(lh.read_state(lh.state_path(settings, session_id)), 'shown')
    shown_there = lh.transcript_ids(session.get('transcript'), deadline, monotonic=monotonic)
    if shown_there is None:
        return given_up()  # a transcript not read to its end holds nothing
    # The newest SEEN_MAX, as the query and could_hold take them, and the answer is filtered on these same ids: one
    # shown longer ago may hold again, since dropping it after the query answered would leave its receipt for a
    # lesson never shown (Rio Grande's correction, from his reviewer's S3).
    seen = lh.seen_list(own, shown_there, held_ids)[-lh.SEEN_MAX:]
    # Asked again with what this session has seen, only now: the first ask reads the index alone, so a command no lesson
    # could hold never reads the transcript. A lesson already shown then starts no query (both reviews' S1/S2).
    if could_hold(cut, settings['ship'], settings['data_dir'], seen) is not True:
        return []
    budget_ms = int((deadline - monotonic() - START_MARGIN) * 1000)
    if budget_ms <= 0:
        return given_up()  # too late for the query to answer before the entry gives up: it isn't started
    request = {'ship': settings['ship'], 'command': cut, 'words_only': True, 'limit': limit,
               'seen': seen, 'budget_ms': budget_ms}
    answer = lh.ask(settings, request, deadline, monotonic)
    if answer is None:
        return given_up()  # late or failing: a Bash head may ask again
    got = []
    for lesson in answer:
        value = lesson.get('command')
        if lesson['id'] in seen or lesson['match'] != 'words' or not value or not _contained(value, cut) \
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
