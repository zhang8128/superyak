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
SHARE = 0.25              # of the time left, for each git call: classifying never takes the lessons' time
_roots_memo: dict = {}    # checkout -> its canonical roots, this process alone; never written to disk


def _git(args, cwd, deadline, monotonic):
    """`git <args>` in `cwd`, bounded: (returncode, stdout) or None when git is missing, fails to start or is late."""
    left = (deadline - monotonic()) * SHARE
    if left <= 0:
        return None
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env['GIT_OPTIONAL_LOCKS'] = '0'
    try:
        done = subprocess.run(['git', *args], cwd=cwd, capture_output=True, timeout=left, stdin=subprocess.DEVNULL,
                              env=env)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return done.returncode, done.stdout


def roots(checkout, deadline, monotonic=time.monotonic):
    """The canonical roots of `checkout`'s registered worktrees, itself among them, or None when they can't be read."""
    key = str(checkout)
    if key in _roots_memo:
        return _roots_memo[key]
    got = _git(['worktree', 'list', '--porcelain', '-z'], str(checkout), deadline, monotonic)
    if got is None or got[0] != 0:
        return None
    found = []
    for field in got[1].decode('utf-8', 'surrogateescape').split('\0'):
        if field.startswith('worktree '):
            path = field[len('worktree '):]
            if os.path.isabs(path):
                found.append(os.path.realpath(path))
    if not found:
        return None
    _roots_memo[key] = tuple(found)
    return _roots_memo[key]


def _own_top_level(folder, deadline, monotonic):
    """Whether git resolves `folder` as its own top level (True), as part of another (False), or gives no answer
    (None): a `.git` there is only a candidate (the spec's w96 change)."""
    got = _git(['rev-parse', '--show-toplevel'], folder, deadline, monotonic)
    if got is None or got[0] != 0:
        return None
    top = got[1].decode('utf-8', 'surrogateescape').rstrip('\n')
    return bool(top) and os.path.realpath(top) == folder


def place_of(cwd, deadline, monotonic=time.monotonic, checkout=CHECKOUT):
    """The kind of `cwd`: "superyak", "other" or None (see the module's docstring)."""
    if not isinstance(cwd, str) or not cwd or not os.path.isabs(cwd):
        return None
    try:
        here = os.path.realpath(cwd)
        if not os.path.isdir(here) or not os.access(here, os.R_OK | os.X_OK):
            return None
    except (OSError, ValueError):
        return None
    found = roots(checkout, deadline, monotonic)
    if found is None:
        return None
    inside = [r for r in found if here == r or here.startswith(r.rstrip(os.sep) + os.sep)]
    if not inside:
        return 'other'
    root = max(inside, key=len)                 # roots nest, as a worktree inside the checkout: the deepest
    folders, at = [], here
    while at != root:
        folders.append(at)
        if len(folders) > MAX_FOLDERS:
            return None
        parent = os.path.dirname(at)
        if parent == at:
            return None
        at = parent
    for folder in folders:
        try:
            candidate = os.path.lexists(os.path.join(folder, '.git'))
        except (OSError, ValueError):
            return None
        if candidate:
            own = _own_top_level(folder, deadline, monotonic)
            if own is None:
                return None
            if own:
                return 'other'                  # an unrelated repository nested inside a root
    return 'superyak'
