"""Counting the store's work per request (public-route-bound plan, Task 0).

Each reading() and transaction() a request makes, and each time it takes the dispatch gate, is filed under its bucket:
the request's route path (UNMATCHED when no route matches it), whether it came public or over the tailnet, and the lane
it ran in, or "before" when it ran before any lane. Work outside any request is filed under UNFILED, by name, so a test
can assert there is none: a store call on a thread that lost its request's context lands there, not nowhere. Counting
is off unless something turns it on: a test, through counts(), or serve, through SUPERYAK_MEASURE_COUNTS on a data dir
under MEASURE_ROOT (start_measuring). It counts every thread in the process: the bucket travels as a ContextVar, which
Starlette's threadpool copies into the thread that runs a request's store calls.

So a test's "0 reads" is a count of what the request really did, and a positive control (a tailnet health read, a
signed-in GET) shows the count isn't blind. A read and a transaction are spans, counted once at entry, after their
refusals and before the gate, so one waiting for the gate counts as running. A peak says how many spans ran at once, in
one bucket or in any union of them (a lane's peak is over every path in it), so "at most a lane's size" is counted too,
not inferred from a total. A gate acquisition is an event, with a total and no peak.
"""
import contextlib
import contextvars
import json
import os
from pathlib import Path
import stat
import threading

# The only data dirs serve will count, fixed here and never taken from the environment: a measure's scratch store lives
# under it, and the live lighthouse dir never does.
MEASURE_ROOT = Path('/dev/shm/superyak-measure')
KINDS = ('read', 'transaction', 'gate')
BEFORE = 'before'  # the lane of work done before any lane
UNFILED = 'unfiled'  # the path and the where of work done outside any request
UNMATCHED = 'unmatched'  # the path of a request no route matches, so a scan of paths makes one bucket, not one each
ANY = '*'  # in a peak's key: the union over that field

_bucket = contextvars.ContextVar('superyak_count_bucket', default=None)
_lock = threading.Lock()
_state = {'on': False, 'generation': 0}
_totals = {}  # (path, where, lane, kind) -> how many
_running = {}  # (path, where, lane, kind), with ANY for a field a union leaves out -> how many spans now
_peaks = {}  # the same keys -> the most spans at once
_OFF = contextlib.nullcontext()  # what counted() returns while counting is off: shared, so a store call allocates nothing


def on():
    return _state['on']


def request(path, public):
    """File what follows, on this context, under this request. Returns the token to reset with."""
    return _bucket.set((path or UNMATCHED, 'public' if public else 'tailnet', BEFORE))


def reset(token):
    _bucket.reset(token)


@contextlib.contextmanager
def lane(name):
    """What runs inside is the named lane's work."""
    path, where, _ = _bucket.get() or (UNFILED, UNFILED, BEFORE)
    token = _bucket.set((path, where, name))
    try:
        yield
    finally:
        _bucket.reset(token)


def _key(kind):
    return (*(_bucket.get() or (UNFILED, UNFILED, BEFORE)), kind)


def _unions(key):
    """The bucket and every union it belongs to: each way of leaving out its path, its where or its lane."""
    path, where, lane_name, kind = key
    return [(p, w, n, kind) for p in (path, ANY) for w in (where, ANY) for n in (lane_name, ANY)]


def counted(kind):
    """Count one span of store work of this kind, and how many of its bucket, and of each union, run at once."""
    return _span(kind) if _state['on'] else _OFF


@contextlib.contextmanager
def _span(kind):
    key = _key(kind)
    unions = _unions(key)
    with _lock:
        generation = _state['generation']
        _totals[key] = _totals.get(key, 0) + 1
        for union in unions:
            _running[union] = _running.get(union, 0) + 1
            _peaks[union] = max(_peaks.get(union, 0), _running[union])
    try:
        yield
    finally:
        with _lock:
            if _state['generation'] == generation:  # a count started since this span began owes it nothing
                for union in unions:
                    _running[union] -= 1


def note(kind):
    """Count one event of this kind, with no span (the dispatch gate's acquisition)."""
    if _state['on']:
        key = _key(kind)
        with _lock:
            _totals[key] = _totals.get(key, 0) + 1


def _field(value):
    return ANY if value is None else value


class Counts:
    """What was counted, read by bucket fields. A field left out matches every value."""

    def total(self, kind=None, *, path=None, where=None, lane=None):
        with _lock:
            return sum(n for (p, w, n_lane, k), n in _totals.items()
                       if (kind is None or k == kind) and (path is None or p == path) and (where is None or w == where)
                       and (lane is None or n_lane == lane))

    def peak(self, kind, *, path=None, where=None, lane=None):
        """The most spans of this kind at once in the union of the buckets these fields name, not the largest single
        bucket's peak: lane='layers' alone is the lane's peak over every path and both wheres."""
        with _lock:
            return _peaks.get((_field(path), _field(where), _field(lane), kind), 0)

    def table(self):
        """The totals by bucket, and the peaks by bucket and by union (ANY marks a field a union leaves out)."""
        with _lock:
            return {'totals': [[*key, n] for key, n in sorted(_totals.items(), key=str)],
                    'peaks': [[*key, n] for key, n in sorted(_peaks.items(), key=str)]}


def _clear():
    _state['generation'] += 1
    _totals.clear()
    _running.clear()
    _peaks.clear()


@contextlib.contextmanager
def counts():
    """For tests: count from empty while the block runs, then stop."""
    with _lock:
        _clear()
        _state['on'] = True
    try:
        yield Counts()
    finally:
        with _lock:
            _state['on'] = False


def _own_root():
    """MEASURE_ROOT as this user's own directory, made 0700 if it is missing. /dev/shm is world-writable, so anyone can
    make MEASURE_ROOT first, as a link to the live data's parent or as their own directory: refuse a root that is a
    symlink, not a directory, not this user's, or writable by anyone else. Returns it resolved."""
    try:
        os.mkdir(MEASURE_ROOT, 0o700)
    except FileExistsError:
        pass
    found = os.lstat(MEASURE_ROOT)
    if stat.S_ISLNK(found.st_mode):  # its own check: on Linux a link's mode is 0777, but on macOS it follows umask
        why = 'is a symlink'
    elif not stat.S_ISDIR(found.st_mode):
        why = 'is not a directory'
    elif found.st_uid != os.getuid():
        why = "is not this user's"
    elif found.st_mode & 0o022:
        why = 'can be written by others'
    else:
        return MEASURE_ROOT.resolve()
    raise ValueError(f'SUPERYAK_MEASURE_COUNTS refuses {MEASURE_ROOT}: it {why}')


def start_measuring(data_dir, out):
    """SUPERYAK_MEASURE_COUNTS for serve: refuse a measure root that isn't this user's own directory, and any data dir
    that isn't under it once resolved (so MEASURE_ROOT/../lighthouse, and a link under the root to elsewhere, are
    refused), then count from empty. Returns the call that writes the totals and peaks to `out` as JSON, never through
    a symlink, which serve makes when it exits cleanly or on SIGTERM."""
    root = _own_root()
    resolved = Path(data_dir).resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError(f'SUPERYAK_MEASURE_COUNTS counts only a data dir under {MEASURE_ROOT}, not {resolved}')
    with _lock:
        _clear()
        _state['on'] = True
    target = Path(out)

    def write():
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        with open(fd, 'w', encoding='utf-8') as file:
            file.write(json.dumps(Counts().table(), indent=1) + '\n')
    return write
