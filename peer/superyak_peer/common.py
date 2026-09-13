"""Shared validation and public-safe domain failures."""
import json
import uuid

class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)

def uid():
    return uuid.uuid4().hex

def text(value, field, limit=200, *, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise Problem(400, f'Invalid {field}')
    return value

def ids(value):
    if not isinstance(value, list) or len(value) > 100 or any(not isinstance(v, str) or len(v) > 100 for v in value):
        raise Problem(400, 'Invalid audience')
    return list(dict.fromkeys(value))

def encode(value):
    return json.dumps(value, separators=(',', ':'), sort_keys=True)

def require(row):
    if row is None:
        raise Problem(404, 'Not found')
    return row
