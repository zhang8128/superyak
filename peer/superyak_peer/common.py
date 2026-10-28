"""Shared validation and public-safe domain failures."""
import json
import re
import uuid

# Rooms that a later linked room replaced (members were added): such a room is no longer current. One subquery for every
# current-room check, so they can't drift (work board 5.1): CURRENT_PERSON_ROOM (which the breakouts and the brief route
# use), Ships._current_rooms, the board's replaced-room refusal and add_participants' (work board 8.4).
REPLACED_ROOMS = 'SELECT linked_room_id FROM rooms WHERE linked_room_id IS NOT NULL'
# Adding members to a replaced room would make a second current room beside its replacement: a fork (work board 8.4).
BRIEF_CHANGED = 'The room brief changed since you looked at it; look again before carrying it'
REPLACED_ADD = 'This room was replaced by a newer linked room; add members there'
REPLACED_REMOVE = 'This room was replaced by a newer linked room; remove members there'

class Problem(Exception):
    def __init__(self, status, message, *, keep=False):
        # keep: the transaction keeps what it saved before this refusal (a breakout's closure, saved on first sight)
        self.status, self.message, self.keep = status, message, keep
        super().__init__(message)

def uid():
    return uuid.uuid4().hex

def valid_utf8(value):
    """Reject escaped lone surrogates in JSON values and object keys."""
    if isinstance(value, str):
        try:
            value.encode('utf-8')
        except UnicodeError:
            raise Problem(400, 'Text must be valid UTF-8') from None
    elif isinstance(value, dict):
        for key, item in value.items():
            valid_utf8(key)
            valid_utf8(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            valid_utf8(item)
    return value


def text(value, field, limit=200, *, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise Problem(400, f'Invalid {field}')
    return valid_utf8(value)

def ids(value):
    if not isinstance(value, list) or len(value) > 100 or any(not isinstance(v, str) or len(v) > 100 for v in value):
        raise Problem(400, 'Invalid audience')
    valid_utf8(value)
    return list(dict.fromkeys(value))

def encode(value):
    valid_utf8(value)
    return json.dumps(value, separators=(',', ':'), sort_keys=True)

def require(row):
    if row is None:
        raise Problem(404, 'Not found')
    return row

def linked_room_ok(value, origin):
    """A received room's linked_room_id: null, or one of the origin's own room ids, `<origin>:<id>` (remote room fields)."""
    return value is None or (isinstance(value, str) and re.fullmatch(re.escape(origin) + r':[A-Za-z0-9_-]{1,64}', value) is not None)
