"""Version check (docs/superpowers/specs/2026-10-14-version-check-design.md, V1-V3): at startup the station reads its
own git history once, so the instructions route can tell a ship whose agent code is behind. Nothing here runs in a
request, and no client value ever reaches git."""
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

HISTORY_LIMIT = 5000
TIMEOUT_SECONDS = 10.0
FULL_HEX = re.compile(r'[0-9a-f]{40,64}')


class AgentHistory(NamedTuple):
    station: str          # the station's commit, 12 hex digits
    behind: frozenset     # 12-digit prefixes of ancestors whose agent/ tree differs from HEAD's (V1)


def find_checkout(module_file=__file__):
    """The git work tree holding this package, only if it has both .git (a folder, or a worktree's file) and agent/."""
    root = Path(module_file).resolve().parents[2]
    return root if (root / '.git').exists() and (root / 'agent').is_dir() else None


def read_history(checkout, run=subprocess.run, limit=HISTORY_LIMIT, timeout=TIMEOUT_SECONDS, clock=time.monotonic):
    """(AgentHistory, None), or (None, why) when git is missing, fails, is slow or answers oddly. Never raises."""
    deadline = clock() + timeout

    def git(*args, stdin=None):
        left = deadline - clock()
        if left <= 0:
            raise subprocess.TimeoutExpired('git', timeout)
        return run(['git', '-C', str(checkout), *args], input=stdin, capture_output=True, text=True, timeout=left,
                   check=True).stdout

    try:
        head = git('rev-parse', 'HEAD').strip()
        tree = git('rev-parse', 'HEAD:agent').strip()
        commits = git('rev-list', f'--max-count={limit}', 'HEAD').split()
        trees = git('cat-file', '--batch-check=%(objectname)', stdin=''.join(f'{c}:agent\n' for c in commits)).splitlines()
    except subprocess.TimeoutExpired:
        return None, f'git ran out of time ({timeout:g} seconds)'
    except (OSError, subprocess.SubprocessError) as error:
        return None, f'git failed ({type(error).__name__})'
    if not FULL_HEX.fullmatch(head) or not FULL_HEX.fullmatch(tree) or len(trees) != len(commits):
        return None, 'git answered in an unexpected form'
    behind = frozenset(c[:12] for c, t in zip(commits, trees) if t != tree and c != head)
    return AgentHistory(head[:12], behind), None


def load(module_file=__file__, run=subprocess.run, err=None):
    """V1 at startup: the history, or None with one line saying why the check is off."""
    err = err or sys.stderr
    checkout = find_checkout(module_file)
    if checkout is None:
        print('superyak: version check off: not running from a git checkout with agent/', file=err, flush=True)
        return None
    history, reason = read_history(checkout, run=run)
    if history is None:
        print(f'superyak: version check off: {reason}', file=err, flush=True)
    return history


def agent_update(history, presence):
    """V2, V3: {'station': ...} when the presence's commit is behind; None for anything else."""
    if history is None or not presence:
        return None
    commit = presence['client'].partition('/')[2]
    return {'station': history.station} if commit in history.behind else None
