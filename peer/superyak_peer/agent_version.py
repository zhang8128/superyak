"""Version check (docs/superpowers/specs/2026-10-14-version-check-design.md, V1-V3 and V8): at startup the station reads its
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
# What ships run (V1): the agent package as one tree, its entry point, and the team modules the agent imports. A literal
# tuple of string constants, so the agent suite's parity test can read it with ast.literal_eval (V8).
RUNTIME_PATHS = (
    'agent/superyak_agent',
    'agent/run_agent.py',
    'team/superyak_team/__init__.py',
    'team/superyak_team/teamlib.py',
    'team/superyak_team/workers.py',
)


class AgentHistory(NamedTuple):
    station: str          # the station's commit, 12 hex digits
    behind: frozenset     # 12-digit prefixes of ancestors whose runtime files differ from HEAD's (V1)


def find_checkout(module_file=__file__):
    """The git work tree holding this package, only if it has both .git (a folder, or a worktree's file) and agent/."""
    root = Path(module_file).resolve().parents[2]
    return root if (root / '.git').exists() and (root / 'agent').is_dir() else None


def read_history(checkout, run=subprocess.run, limit=HISTORY_LIMIT, timeout=TIMEOUT_SECONDS, clock=time.monotonic):
    """(AgentHistory, None), or (None, why) when HEAD isn't on origin/main, or git is missing, fails, is slow or
    answers oddly. Never raises."""
    deadline = clock() + timeout

    def git(*args, stdin=None, check=True):
        left = deadline - clock()
        if left <= 0:
            raise subprocess.TimeoutExpired('git', timeout)
        return run(['git', '-C', str(checkout), *args], input=stdin, capture_output=True, text=True, errors='replace',
                   timeout=left, check=check)

    try:
        head = git('rev-parse', 'HEAD').stdout.strip()
        on_main = git('merge-base', '--is-ancestor', 'HEAD', 'refs/remotes/origin/main', check=False)
        if on_main.returncode == 1:  # not an ancestor; git says so with empty output
            return None, 'HEAD is not on origin/main'
        if on_main.returncode != 0:
            raise subprocess.CalledProcessError(on_main.returncode, 'git merge-base', stderr=on_main.stderr)
        commits = git('rev-list', f'--max-count={limit}', 'HEAD').stdout.split()
        names = git('cat-file', '--batch-check=%(objectname)',
                    stdin=''.join(f'{c}:{p}\n' for c in commits for p in RUNTIME_PATHS)).stdout.splitlines()
    except subprocess.TimeoutExpired:
        return None, f'git ran out of time ({timeout:g} seconds)'
    except subprocess.CalledProcessError as error:
        stderr = error.stderr if isinstance(error.stderr, str) else ''
        first = (stderr.strip().splitlines() or [''])[0].strip()[:200]  # station-local text, never client data
        return None, f'git failed (CalledProcessError): {first}' if first else 'git failed (CalledProcessError)'
    except (OSError, subprocess.SubprocessError) as error:
        return None, f'git failed ({type(error).__name__})'
    width = len(RUNTIME_PATHS)
    if not FULL_HEX.fullmatch(head) or not commits or commits[0] != head or len(names) != len(commits) * width:
        return None, 'git answered in an unexpected form'
    # git prints a path a commit lacks as "<commit>:<path> missing", ignoring the format: different for every commit.
    # One value for all of them, so a path missing from HEAD and an ancestor alike compares equal (V1).
    names = [n if FULL_HEX.fullmatch(n) else 'missing' for n in names]
    files = {c: tuple(names[i * width:(i + 1) * width]) for i, c in enumerate(commits)}
    behind = frozenset(c[:12] for c in commits if c != head and files[c] != files[head])
    return AgentHistory(head[:12], behind), None


def load(module_file=__file__, run=subprocess.run, err=None):
    """V1 at startup: the history, or None. Exactly one line, "on" or "off" with why, and it never raises (N1): the
    station must start whatever happens here."""
    err = err or sys.stderr
    try:
        checkout = find_checkout(module_file)
        if checkout is None:
            history, reason = None, 'not running from a git checkout with agent/'
        else:
            history, reason = read_history(checkout, run=run)
    except Exception as error:  # noqa: BLE001
        history, reason = None, f'unexpected error ({type(error).__name__})'
    line = (f'superyak: version check on: {history.station}, {len(history.behind)} behind' if history is not None
            else f'superyak: version check off: {reason}')
    try:
        print(line, file=err, flush=True)
    except Exception:  # noqa: BLE001 - a broken stderr must not stop the station either
        pass
    return history


def agent_update(history, presence):
    """V2, V3: {'station': ...} when the presence's commit is behind; None for anything else."""
    if history is None or not presence:
        return None
    commit = presence['client'].partition('/')[2]
    return {'station': history.station} if commit in history.behind else None
