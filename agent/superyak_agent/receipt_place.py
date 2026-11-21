"""Where a lesson was shown, as a kind (the receipt-place spec, docs/superpowers/specs/2026-11-18-lesson-receipt-place.md,
"How a checkout of this repository is told"): "superyak" only for the installed checkout the hook runs from and the
worktrees git has registered for it; "other" for a folder outside them, or for one inside a repository nested in them;
None when the check didn't finish or its answer was ambiguous. Failed discovery never becomes "other", and a wrong
"superyak" hides what this is for, so the check leans to None. The kind confers nothing.

The roots come from the checkout's own `git worktree list --porcelain -z`, never from the folder asked about, and are
kept in memory for one process only. Git runs with no GIT_* variable of the caller's (GIT_DIR and the like would point
discovery elsewhere) and with a share of the time the caller has left."""
import os
import subprocess
import time
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parents[2]
MAX_FOLDERS = 64          # folders checked from the cwd up to its root, the cwd included and the root excluded
MAX_UP = 256              # folders walked up from the cwd before the answer is given up as unknown
SHARE = 0.25              # of the time left, for all of classifying: it never takes the lessons' time
_roots_memo: dict = {}    # checkout -> (its canonical path, its git common dir, its roots by (st_dev, st_ino)); this
                          # process alone, never written to disk


def _git(args, cwd, until, monotonic):
    """`git <args>` in `cwd`, stopped at `until`: (returncode, stdout), or None when git is missing, fails to start or is
    late. Every call of one classifying shares its one deadline (the code reader's 4)."""
    left = until - monotonic()
    if left <= 0:
        return None
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env['GIT_OPTIONAL_LOCKS'] = '0'
    try:
        done = subprocess.run(['git', *args], cwd=cwd, capture_output=True, timeout=left, input=b'',
                              env=env)    # an empty pipe for stdin: DEVNULL opens /dev/null for writing
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return done.returncode, done.stdout


def _records(checkout, until, monotonic):
    """The worktree records of `git worktree list --porcelain`, each a list of its fields; -z where git has it (2.36),
    else lines, and None when a path is quoted there (the code reader's 6)."""
    got = _git(['worktree', 'list', '--porcelain', '-z'], str(checkout), until, monotonic)
    if got is not None and got[0] == 0:
        fields, sep = got[1].decode('utf-8', 'surrogateescape').split('\0'), True
    else:
        got = _git(['worktree', 'list', '--porcelain'], str(checkout), until, monotonic)
        if got is None or got[0] != 0:
            return None
        fields = got[1].decode('utf-8', 'surrogateescape').split('\n')
        if any(f.startswith('worktree "') for f in fields):
            return None
    records, current = [], []
    for field in fields:
        if field:
            current.append(field)
        elif current:
            records.append(current)
            current = []
    if current:
        records.append(current)
    return records


def _common_dir(folder, until, monotonic):
    """The canonical git common directory of the repository `folder` is in, or None."""
    got = _git(['rev-parse', '--git-common-dir'], folder, until, monotonic)
    if got is None or got[0] != 0:
        return None
    out = got[1].decode('utf-8', 'surrogateescape').rstrip('\n')
    return os.path.realpath(os.path.join(folder, out)) if out else None


def roots(checkout, until, monotonic=time.monotonic):
    """(the checkout's canonical path, its git common dir, {(st_dev, st_ino): root}) for its registered, not prunable
    worktrees, the checkout among them; None when they can't be read, or when the checkout isn't a root of its own (a
    checkout without its own .git inside another repository: the code reader's 2)."""
    key = str(checkout)
    if key in _roots_memo:
        return _roots_memo[key]
    records = _records(checkout, until, monotonic)
    if records is None:
        return None
    found = []
    for record in records:
        path = next((f[len('worktree '):] for f in record if f.startswith('worktree ')), None)
        if path and os.path.isabs(path) and not any(f == 'prunable' or f.startswith('prunable ') for f in record):
            found.append(os.path.realpath(path))
    me = os.path.realpath(str(checkout))
    if me not in found:
        return None
    common = _common_dir(me, until, monotonic)
    if common is None:
        return None
    ids = {}
    for root in found:
        try:
            st = os.stat(root)
        except OSError:
            continue
        ids.setdefault((st.st_dev, st.st_ino), root)
    _roots_memo[key] = (me, common, ids)
    return _roots_memo[key]


def _own_top_level(folder, until, monotonic):
    """Whether git resolves `folder` as its own top level (True), as part of another (False), or gives no answer
    (None): a `.git` there is only a candidate (the spec's w96 change)."""
    got = _git(['rev-parse', '--show-toplevel'], folder, until, monotonic)
    if got is None or got[0] != 0:
        return None
    top = got[1].decode('utf-8', 'surrogateescape').rstrip('\n')
    return bool(top) and os.path.realpath(top) == folder


def place_of(cwd, deadline, monotonic=time.monotonic, checkout=None):
    """The kind of `cwd`: "superyak", "other" or None (see the module's docstring). `checkout` is the installed one,
    this module's own, unless a test names another."""
    checkout = CHECKOUT if checkout is None else checkout
    now = monotonic()
    until = now + (deadline - now) * SHARE      # one deadline for all of classifying (the code reader's 4)
    if until <= now or not isinstance(cwd, str) or not cwd or not os.path.isabs(cwd):
        return None
    try:
        here = os.path.realpath(cwd)
        if not os.path.isdir(here) or not os.access(here, os.R_OK | os.X_OK):
            return None
    except (OSError, ValueError):
        return None
    got = roots(checkout, until, monotonic)
    if got is None:
        return None
    me, common, ids = got
    folders, at, root = [], here, None
    for _ in range(MAX_UP):                     # by (st_dev, st_ino): case and normalisation can't part a root (7)
        try:
            st = os.stat(at)
        except OSError:
            return None
        if (st.st_dev, st.st_ino) in ids:
            root = ids[(st.st_dev, st.st_ino)]  # the first met walking up is the deepest
            break
        folders.append(at)
        parent = os.path.dirname(at)
        if parent == at:
            break
        at = parent
    else:
        return None
    if root is None:
        return 'other'
    if len(folders) > MAX_FOLDERS:
        return None
    if root != me and _common_dir(root, until, monotonic) != common:
        return None                             # a registered path that is another repository now (the reader's 2)
    for folder in folders:
        try:
            candidate = os.path.lexists(os.path.join(folder, '.git'))
        except (OSError, ValueError):
            return None
        if candidate:                           # any candidate ends the walk (the code reader's 3)
            return 'other' if _own_top_level(folder, until, monotonic) is True else None
    return 'superyak'
