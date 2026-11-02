"""The shared per-session record and the logs' appender (the ships' hold seam).

Standard library only (plus `acting`, also stdlib only): the hold imports this module and must stay on the light
path, so it never imports station, claims, urllib.request or http.

The record is `<sessions dir>/<session_key>.holds`. The hook, the hold and the MCP server share it, and it holds both
checklist and lesson entries. A lessons provider keeps its entries under `record.data['lessons']` and never calls
`save`; the hold entry sets `record.data['session']`. `record.data` is a plain dict providers may extend.
"""
import contextlib
import errno
import json
import os
import time
from pathlib import Path
from typing import NamedTuple

from superyak_agent.acting import session_key

HOLDS_PER_SESSION = 3
# Spec lesson-holds-on-tool-calls, item 1: the hold's matcher is Bash plus each held tool every ship has confirmed on
# its own Claude Code version (the deny's reason reaches the model, the deny's record shape, `agent_id` on a
# subagent's call); a tool joins here, and nowhere else. The station's post and claim passed all three on 2.1.312 (the
# Pi and Tardis, all hands 0ba39f1a) and 2.1.314 (the Mac, 4c648bad), in `claude -p` (entrypoint sdk-cli).
# AskUserQuestion isn't in `claude -p`, so it waits for an interactive run.
CONFIRMED_TOOLS = ('mcp__station__station_post', 'mcp__station__station_claim')
HOLD_MATCHER = '|'.join(('Bash',) + CONFIRMED_TOOLS)
OUTPUT_CHARS = 9500          # hook.TOTAL_CHARS, pinned by a test
LESSON_BYTES = 2000
RECORD_SUFFIX = '.holds'
POLL_SECONDS = 0.005


class Hold(NamedTuple):
    kind: str   # "checklist" or "lesson"
    key: str
    text: str


def record_path(sessions_dir, session_id: str) -> Path:
    return Path(sessions_dir) / (session_key(session_id) + RECORD_SUFFIX)


class RecordFile:
    """An open, locked record. `data` is a dict; `save()` rewrites the same inode in one write."""

    def __init__(self, fd: int, data: dict):
        self.fd = fd
        self.data = data

    def close(self) -> None:
        """Called on leaving the `with`: the descriptor may be reused, so `save` must never touch it again."""
        self.fd = -1

    def save(self) -> None:
        """One write at offset 0 to the same inode, then a truncate to its length: a failed write leaves the old
        record readable (Ruling 41). A short write is an error."""
        if self.fd < 0:
            raise OSError(errno.EBADF, 'the session record is closed')
        payload = json.dumps(self.data).encode('utf-8')
        if os.pwrite(self.fd, payload, 0) != len(payload):
            raise OSError(errno.EIO, 'short write to the session record')
        os.ftruncate(self.fd, len(payload))


def _read(fd: int) -> dict:
    chunks = []
    offset = 0
    while True:
        chunk = os.pread(fd, 1 << 16, offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
    try:   # raw_decode: a stale tail after a shorter payload is ignored
        data, _ = json.JSONDecoder().raw_decode(b''.join(chunks).decode('utf-8').lstrip())
    except (ValueError, RecursionError):   # UnicodeDecodeError and JSONDecodeError are ValueErrors
        return {}
    return data if isinstance(data, dict) else {}


def _lock(path: Path, deadline: float, monotonic) -> int:
    """Open and lock the file, reopening when a prune unlinked it while we waited."""
    import fcntl
    while True:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as e:
                    if e.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                        raise
                if monotonic() >= deadline:
                    raise TimeoutError(f'{path.name} stayed locked past the deadline')
                time.sleep(max(0.0, min(POLL_SECONDS, deadline - monotonic())))
            if os.fstat(fd).st_nlink == 0:
                os.close(fd)
                fd = -1
                continue
            return fd
        except BaseException:
            if fd != -1:
                os.close(fd)
            raise


@contextlib.contextmanager
def open_record(path: Path, deadline: float, monotonic=time.monotonic):
    """Lock the record (creating it 0600 in a 0700 folder) and yield it. Leaving closes and unlocks without writing."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = _lock(path, deadline, monotonic)
    record = None
    try:
        record = RecordFile(fd, _read(fd))  # inside the try: a failed read must not leak the fd or keep the lock
        yield record
    finally:
        if record is not None:
            record.close()
        os.close(fd)


def touch(record, now: float, cwd: str | None) -> None:
    record.setdefault('first', now)
    record['seen'] = now
    if cwd:
        record['cwd'] = cwd


def append_line(path: Path, line: dict) -> None:
    """One whole JSON line in one `os.write` under O_APPEND, private, in a folder made 0700."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = (json.dumps(line, allow_nan=False) + '\n').encode('utf-8')
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if os.write(fd, data) != len(data):
            raise OSError(errno.EIO, 'short write to the log')
    finally:
        os.close(fd)
