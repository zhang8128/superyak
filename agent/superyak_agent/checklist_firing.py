"""When a checklist is due (spec, "Firing, exactly"), and the log lines.

Standard library only: the hold imports this module. The functions work on the record's plain dict.
"""
import hashlib
import math
import re

from superyak_agent.checklists import Loaded, command_matches, enter_applies

LISTS_PER_EVENT = 2
READ_SECONDS = 0.150
HOLD_SECONDS = 1.0
SAVE_SECONDS = 0.5   # more for a save already under way at HOLD_SECONDS (the final review's M3)
START_SOURCES = ('startup', 'clear', 'fork')
ANSWERS = ('done', 'done-before-asked', 'caught', 'n/a', 'skipped')
REASON_BYTES = 200
REASON_REFUSED = ('A reason is one line of at most 200 bytes, with no email address, phone number or key-like token. '
                  'Reword it.')

_EMAIL = re.compile(r'[^\s@]+@[^\s@]+\.[A-Za-z]{2,}')
_PHONE = re.compile(r'\+\d[\d ().-]{7,}\d|\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}')
_RUN = re.compile(r'[A-Za-z0-9+/=_-]{32,}')
_HASH = re.compile(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})')

Due = tuple[Loaded, tuple[str, ...]]


def begin(record: dict, source: str | None) -> None:
    """A SessionStart: startup, clear and fork make the session fresh; clear forgets the `start` firings (Ruling 7)."""
    if source in START_SOURCES:
        record['fresh'] = True
    if source == 'clear':
        for entry in _section(record, 'fired', dict).values():
            if isinstance(entry, dict):
                entry.pop('start', None)


def _section(record: dict, name: str, kind: type, create: bool = False):
    """A section of the record. One of the wrong type reads as empty, and is replaced when `create` is set, so a
    damaged record heals on its next write instead of wedging."""
    value = record.get(name)
    if isinstance(value, kind):
        return value
    if create:
        value = record[name] = kind()
        return value
    return kind()


def _entry(record: dict, loaded: Loaded, create: bool = False) -> dict:
    fired = _section(record, 'fired', dict, create)
    entry = fired.get(loaded.key)
    if isinstance(entry, dict):
        return entry
    if create:
        entry = fired[loaded.key] = {}
        return entry
    return {}


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _wait(record: dict, loaded: Loaded, now: float) -> float:
    last = _entry(record, loaded).get('last')
    if not _number(last):
        last = record.get('first')
    if not _number(last):
        last = now
    return now - last


def _sorted(record: dict, due: list[Due], now: float) -> list[Due]:
    return sorted(due, key=lambda d: (-_wait(record, d[0], now), d[0].order, d[0].checklist.id))


def due_at_event(lists, record: dict, cwd: str | None, now: float) -> list[Due]:
    due: list[Due] = []
    for loaded in lists:
        entry = _entry(record, loaded)
        kinds = []
        for moment in loaded.checklist.moments:
            if moment.kind == 'start':
                if record.get('fresh') and 'start' not in entry:
                    kinds.append('start')
            elif moment.kind == 'enter':
                if loaded.location is not None and 'enter' not in entry and enter_applies(loaded.location, cwd):
                    kinds.append('enter')
            elif moment.kind == 'every':
                if _wait(record, loaded, now) >= moment.hours * 3600:
                    kinds.append('every')
        if kinds:
            due.append((loaded, tuple(kinds)))
    return _sorted(record, due, now)


def command_digest(command: str) -> str:
    return hashlib.sha256(command.encode('utf-8', 'surrogatepass')).hexdigest()


def _listed(record: dict, section: str, loaded: Loaded) -> list:
    value = _section(record, section, dict).get(loaded.key)
    return value if isinstance(value, list) else []


def due_at_command(lists, record: dict, command: str, now: float) -> tuple[list[Due], str]:
    digest = command_digest(command)
    due: list[Due] = []
    for loaded in lists:
        if digest in _listed(record, 'passed', loaded):
            continue
        if any(m.kind == 'command' and command_matches(m.words, command) for m in loaded.checklist.moments):
            due.append((loaded, ('command',)))
    return _sorted(record, due, now), digest


def item_key(room_id: str, key: str) -> str:
    return hashlib.sha256((room_id + '\n' + key).encode('utf-8', 'surrogatepass')).hexdigest()[:16]


def due_at_claim(lists, record: dict, item: str, now: float) -> list[Due]:
    due: list[Due] = []
    for loaded in lists:
        if item in _listed(record, 'items', loaded):
            continue
        if any(m.kind == 'claim' for m in loaded.checklist.moments):
            due.append((loaded, ('claim',)))
    return _sorted(record, due, now)


def _add(record: dict, section: str, key: str, value: str) -> None:
    sect = _section(record, section, dict, True)
    values = sect.get(key)
    if not isinstance(values, list):
        values = sect[key] = []
    if value not in values:
        values.append(value)


def mark_fired(record: dict, shown, now: float, *, digest: str | None = None, item: str | None = None) -> None:
    for loaded, kinds in shown:
        entry = _entry(record, loaded, True)
        entry['last'] = now
        entry['version'] = loaded.checklist.version
        for kind in kinds:
            entry[kind] = now
        if digest is not None:
            _add(record, 'passed', loaded.key, digest)
        if item is not None:
            _add(record, 'items', loaded.key, item)


def mark_passed(record: dict, deferred, digest: str) -> None:
    for loaded, _ in deferred:
        _add(record, 'passed', loaded.key, digest)


def spend(record: dict, lists, digest: str) -> bool:
    """The command went through: drop its digest from each list's passes, so the re-run spends the pass and a later
    identical command is due again (section 2's M1; spec revision 4). True when one was dropped."""
    passed = _section(record, 'passed', dict)
    spent = False
    for loaded in lists:
        values = passed.get(loaded.key)
        if isinstance(values, list) and digest in values:
            values[:] = [v for v in values if v != digest]
            spent = True
            if not values:
                del passed[loaded.key]
    return spent


def told(record: dict, notice: str) -> bool:
    return command_digest(notice) in _section(record, 'told', list)


def mark_told(record: dict, notices) -> None:
    """Record only the notices actually shown (plan nit N5)."""
    seen = _section(record, 'told', list, True)
    for notice in notices:
        digest = command_digest(notice)
        if digest not in seen:
            seen.append(digest)


def fired_line(now: float, session: str, key: str, version: int, moment: str) -> dict:
    return {'time': now, 'session': session, 'key': key, 'version': version, 'moment': moment}


def miss_line(now: float, session: str, kind: str, key: str | None = None, version: int | None = None) -> dict:
    line = {'time': now, 'session': session}
    if key is not None:
        line['key'] = key
    if version is not None:
        line['version'] = version
    line['miss'] = kind
    return line


def _key_like(text: str) -> bool:
    for run in _RUN.findall(text):
        if _HASH.fullmatch(run):
            continue
        if re.search(r'[A-Z]', run) and re.search(r'[a-z]', run) and re.search(r'[0-9]', run):
            return True
    return False


def screen_reason(text: str, limit: int = REASON_BYTES) -> bool:
    """One printable line of at most `limit` UTF-8 bytes with no email address, phone number or key-like token."""
    if not isinstance(text, str) or not text.isprintable():
        return False
    try:
        if len(text.encode('utf-8')) > limit:
            return False
    except UnicodeEncodeError:
        return False
    return not (_EMAIL.search(text) or _PHONE.search(text) or _key_like(text))


def run_line(now: float, session: str, key: str, version: int, moment: str, answers: list) -> dict:
    return {'time': now, 'session': session, 'key': key, 'version': version, 'moment': moment, 'answers': answers}


def refused_line(now: float, session: str, key: str, version: int, moment: str, kind: str) -> dict:
    return {'time': now, 'session': session, 'key': key, 'version': version, 'moment': moment, 'refused': kind}
