"""Reentrant process/thread gate: commits cannot pass final dispatch writes."""
from contextlib import AbstractContextManager
import fcntl
import os
import threading

_gates = {}
_registry = threading.Lock()


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

    def __enter__(self):
        lock, local = self.state
        lock.acquire()
        try:
            if not getattr(local, 'depth', 0):
                local.fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                fcntl.flock(local.fd, fcntl.LOCK_EX)
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
