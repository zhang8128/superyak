"""Reentrant process/thread gate: commits cannot pass final dispatch writes."""
from contextlib import AbstractContextManager, contextmanager
import fcntl
import os
import threading
import time

_gates = {}
_registry = threading.Lock()
POLL = 0.005  # a bounded wait asks for the file lock again this often: flock itself has no timeout


class GateTimeout(TimeoutError):
    """A bounded wait for the gate (DispatchGate.bounded) reached its deadline."""


def _lock_file(fd, left):
    """The gate's file lock: waited for without end, or, given `left` (the seconds left), only until none are left."""
    if left is None:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            remaining = left()
            if remaining <= 0:
                raise GateTimeout('the dispatch gate was still held at the deadline') from None
            time.sleep(min(POLL, remaining))



def federation_lock(data_dir):
    """Federation pull (plan, dispatch.py): one process syncs a data directory, `serve --sync` or `federate`. An flock
    on federation.lock, opened O_NOFOLLOW at 0600 and taken LOCK_NB. It is held until the returned descriptor closes,
    which is when the process ends. A second holder gets ValueError."""
    fd = os.open(os.path.join(data_dir, 'federation.lock'),
                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise ValueError('another process already syncs this directory') from None
    return fd

class DispatchGate(AbstractContextManager):
    def __init__(self, path):
        self.path = path
        with _registry:
            self.state = _gates.setdefault(str(path.resolve()), (threading.RLock(), threading.local()))

    @contextmanager
    def bounded(self, deadline, clock=time.monotonic):
        """Inside this block this thread waits for the gate only until `deadline` on `clock`, then raises GateTimeout;
        outside it, and on every other thread, the gate waits as it always has. Re-entering the gate this thread holds
        never waits. For work that is worthless late: first rail's query, whose hook gives it a budget (Serenity's
        review of first-rail, S1)."""
        _, local = self.state
        before = getattr(local, 'bound', None)
        local.bound = (deadline, clock)
        try:
            yield self
        finally:
            local.bound = before

    def __enter__(self):
        lock, local = self.state
        bound = getattr(local, 'bound', None)
        left = None if bound is None else (lambda: bound[0] - bound[1]())
        if left is None:
            lock.acquire()
        else:
            while not lock.acquire(timeout=min(max(0.0, left()), threading.TIMEOUT_MAX)):  # any later is an OverflowError
                if left() <= 0:
                    raise GateTimeout('the dispatch gate was still held at the deadline')
        try:
            if not getattr(local, 'depth', 0):
                fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                try:
                    _lock_file(fd, left)
                except BaseException:
                    os.close(fd)
                    raise
                local.fd = fd
            local.depth = getattr(local, 'depth', 0) + 1
        except BaseException:
            lock.release()
            raise
        return self

    def __exit__(self, *args):
        lock, local = self.state
        local.depth -= 1
        if not local.depth:
            fcntl.flock(local.fd, fcntl.LOCK_UN)
            os.close(local.fd)
        lock.release()
