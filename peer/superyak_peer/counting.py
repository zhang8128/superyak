"""Counting the store's work per request (public-route-bound plan, Task 0).

Each reading() and transaction() a request makes, and each time it takes the dispatch gate, is filed under its bucket:
the request's route path, whether it came public or over the tailnet, and the lane it ran in, or "before" when it ran
before any lane. Counting is off unless something turns it on: a test, through counts(), or serve, through
SUPERYAK_MEASURE_COUNTS on a data dir under MEASURE_ROOT (start_measuring). It counts every thread in the process: the
bucket travels as a ContextVar, which Starlette's threadpool copies into the thread that runs a request's store calls.

So a test's "0 reads" is a count of what the request really did, and a positive control (a tailnet health read, a
signed-in GET) shows the count isn't blind. A peak per bucket says how many ran at once, so "at most a lane's size" is
counted too, not inferred from a total.
"""
import contextlib
import contextvars
import json
import threading
from pathlib import Path

# The only data dirs serve will count, fixed here and never taken from the environment: a measure's scratch store lives
# under it, and the live lighthouse dir never does.
MEASURE_ROOT = Path('/dev/shm/superyak-measure')
KINDS = ('read', 'transaction', 'gate')
BEFORE = 'before'  # the lane of work done before any lane

_bucket = contextvars.ContextVar('superyak_count_bucket', default=None)
_lock = threading.Lock()
_state = {'on': False}
_totals = {}  # (path, where, lane, kind) -> how many
_running = {}  # (path, where, lane, kind) -> how many now
_peaks = {}  # (path, where, lane, kind) -> the most at once


def on():
    return _state['on']


def request(path, public):
    """File what follows, on this context, under this request. Returns the token to reset with."""
    return _bucket.set((path, 'public' if public else 'tailnet', BEFORE))


def reset(token):
    _bucket.reset(token)


@contextlib.contextmanager
def lane(name):
    """What runs inside is the named lane's work."""
    path, where, _ = _bucket.get() or (None, None, BEFORE)
    token = _bucket.set((path, where, name))
    try:
        yield
    finally:
        _bucket.reset(token)


def _key(kind):
    return (*(_bucket.get() or (None, None, BEFORE)), kind)


@contextlib.contextmanager
def counted(kind):
    """Count one piece of store work of this kind, and how many of its bucket run at once."""
    if not _state['on']:
        yield
        return
    key = _key(kind)
    with _lock:
        _totals[key] = _totals.get(key, 0) + 1
        _running[key] = _running.get(key, 0) + 1
        _peaks[key] = max(_peaks.get(key, 0), _running[key])
    try:
        yield
    finally:
        with _lock:
            _running[key] -= 1


def note(kind):
    """Count one event of this kind, with no span (the dispatch gate's acquisition)."""
    if _state['on']:
        key = _key(kind)
        with _lock:
            _totals[key] = _totals.get(key, 0) + 1
            _peaks[key] = max(_peaks.get(key, 0), 1)


class Counts:
    """What was counted, read by bucket fields. A field left out matches every value."""

    @staticmethod
    def _matching(table, kind, path, where, lane):
        return [n for (p, w, l, k), n in table.items()
                if (kind is None or k == kind) and (path is None or p == path) and (where is None or w == where)
                and (lane is None or l == lane)]

    def total(self, kind=None, *, path=None, where=None, lane=None):
        with _lock:
            return sum(self._matching(_totals, kind, path, where, lane))

    def peak(self, kind, *, path=None, where=None, lane=None):
        with _lock:
            return max(self._matching(_peaks, kind, path, where, lane), default=0)

    def table(self):
        with _lock:
            return {'totals': [[*key, n] for key, n in sorted(_totals.items(), key=str)],
                    'peaks': [[*key, n] for key, n in sorted(_peaks.items(), key=str)]}


def _clear():
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


def start_measuring(data_dir, out):
    """SUPERYAK_MEASURE_COUNTS for serve: refuse any data dir that isn't under MEASURE_ROOT once resolved (so
    MEASURE_ROOT/../lighthouse is refused), then count from empty. Returns the call that writes the totals and peaks
    to `out` as JSON, which serve makes when it exits cleanly."""
    resolved, root = Path(data_dir).resolve(), MEASURE_ROOT.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError(f'SUPERYAK_MEASURE_COUNTS counts only a data dir under {MEASURE_ROOT}, not {resolved}')
    with _lock:
        _clear()
        _state['on'] = True
    target = Path(out)

    def write():
        target.write_text(json.dumps(Counts().table(), indent=1) + '\n', encoding='utf-8')
    return write
