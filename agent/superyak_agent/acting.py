"""The acting-ship rule, in one place the hook, the hold and the station tools share: which home a ship lives in,
which kind of ship that makes it, which repository a directory is in, the claims registry, and which ship acts in a
session. Standard library only and nothing from this package, so the hold stays light (checklists S-a).
Moved verbatim from claims.py and station.py, which re-export it."""
import hashlib
import json
import os
from pathlib import Path
import re
from typing import NamedTuple


NAME = re.compile(r'[a-z][a-z0-9-]{1,31}')  # the station's own rule for ship usernames (peer ships.py)


def machine_home():
    """~/.superyak, read at call time so a test's HOME applies."""
    return Path.home() / '.superyak'


def ships_root():
    return machine_home() / 'ships'


def project_home(name):
    return ships_root() / name


def _real(path):
    return Path(os.path.realpath(os.path.expanduser(str(path))))


def kind_of(home):
    """'machine' for ~/.superyak, 'project' for ~/.superyak/ships/<name>, None for anything else (a custom --config,
    which the hook and the MCP server treat as the machine ship, as before D7)."""
    home = _real(home)
    if home == _real(machine_home()):
        return 'machine'
    if home.parent == _real(ships_root()) and NAME.fullmatch(home.name):
        return 'project'
    return None


class Repo(NamedTuple):
    root: Path      # the main checkout's root, a real path
    common: Path    # its .git directory, a real path


def _gitdir_of(dotgit):
    """The gitdir a `.git` file names, resolved against the folder holding it; None if it can't be read."""
    text = dotgit.read_text()
    line = next((ln for ln in text.splitlines() if ln.startswith('gitdir:')), None)
    if line is None:
        return None
    named = line[len('gitdir:'):].strip()
    return Path(os.path.realpath(dotgit.parent / named)) if named else None


def project_root(start):
    """S6: walk up from the real path of `start` to the first `.git`, which decides. A directory is a main checkout;
    a file is a worktree whose gitdir must link back to it and whose common dir comes from `commondir`. The common
    dir must be named `.git` and the root is its parent, so a submodule, a bare repository's worktree and a
    --separate-git-dir checkout are "no repository" (None), as is anything that can't be read."""
    try:
        here = Path(os.path.realpath(start))
        for folder in (here, *here.parents):
            dotgit = folder / '.git'
            if not os.path.lexists(dotgit):
                continue
            if dotgit.is_dir() and not dotgit.is_symlink():
                common = Path(os.path.realpath(dotgit))
            elif dotgit.is_file() and not dotgit.is_symlink():
                gitdir = _gitdir_of(dotgit)
                if gitdir is None:
                    return None
                back = (gitdir / 'gitdir').read_text().strip()
                if os.path.realpath(back) != os.path.realpath(dotgit):
                    return None
                commondir = gitdir / 'commondir'
                common = Path(os.path.realpath(gitdir / commondir.read_text().strip())) if commondir.exists() else gitdir
            else:
                return None
            if common.name != '.git' or not common.is_dir():
                return None
            return Repo(common.parent, common)
    except (OSError, ValueError):
        return None
    return None


FIELDS = {'ship': str, 'home': str, 'root': str, 'dev': int, 'ino': int}


class Unreadable(Exception):
    """The registry can't be trusted: every hook goes quiet and every station tool refuses until it's fixed."""


def registry_path():
    return machine_home() / 'projects.json'


def claim_files():
    root = ships_root()
    return sorted(p / 'claim.json' for p in root.iterdir() if (p / 'claim.json').exists()) if root.is_dir() else []


def _valid(entries):
    if not isinstance(entries, list):
        return False
    for item in entries:
        if not isinstance(item, dict) or set(item) != set(FIELDS):
            return False
        if any(type(item[key]) is not kind for key, kind in FIELDS.items()):     # True is no inode
            return False
    return (len({e['ship'] for e in entries}) == len(entries) and len({e['root'] for e in entries}) == len(entries))


def read_registry():
    """The claims, as a list of {ship, home, root, dev, ino}. Unreadable when the file can't be read, isn't JSON or
    fails the schema, and when it's missing while some ships/*/claim.json exists (a claim was written, so the
    registry was too, and it has been lost). Missing with no claim.json means no claims."""
    path = registry_path()
    try:
        text = path.read_text()
    except FileNotFoundError:
        found = claim_files()
        if found:
            raise Unreadable(f'{path} is missing, but {found[0]} says a claim was made') from None
        return []
    except OSError as error:
        raise Unreadable(f'{path} can\'t be read ({type(error).__name__})') from error
    try:
        entries = json.loads(text)
    except ValueError:
        raise Unreadable(f'{path} isn\'t valid JSON') from None
    if not _valid(entries):
        raise Unreadable(f'{path} doesn\'t hold a list of claims ({", ".join(FIELDS)})')
    return entries


def read_json_quiet(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def match(entry, root):
    """S6: 'full' when the claim's root and (dev, ino) both equal the session root's, 'partial' when exactly one does
    (a moved repository, a re-clone at the same path, a remount), None otherwise. Claude Code keys local tools by path
    (M7), so path and inode must agree for the hooks and the tools to stay on one ship."""
    try:
        st = os.stat(root)
    except OSError:
        return None
    path_ok = entry['root'] == str(Path(os.path.realpath(root)))
    inode_ok = (entry['dev'], entry['ino']) == (st.st_dev, st.st_ino)
    return 'full' if path_ok and inode_ok else 'partial' if path_ok or inode_ok else None


def session_project(cwd=None):
    """The session's project directory: CLAUDE_PROJECT_DIR (where it started, M4, M8), else the cwd given (the
    hook's stdin cwd, or the MCP server's own)."""
    return os.environ.get('CLAUDE_PROJECT_DIR') or cwd


def verdict(home, project_dir):
    """Whether the ship whose home this is acts in a session started in `project_dir` (S6, R14, R15, R16):
    ('act', claim or None), ('claimed', claim) for the machine ship in another ship's project, ('stale', claim) for a
    partial match, ('elsewhere', claim) for a project ship outside its claim, ('unclaimed', None) for a project ship
    whose claim.json isn't also, equal, in the registry, or ('unreadable', reason). Never runs git."""
    try:
        entries = read_registry()
    except Unreadable as error:
        return 'unreadable', str(error)
    repo = project_root(project_dir) if project_dir else None
    if kind_of(home) != 'project':
        for entry in entries if repo is not None else []:
            found = match(entry, repo.root)
            if found == 'full':
                return 'claimed', entry
            if found == 'partial':
                return 'stale', entry
        return 'act', None
    own = read_json_quiet(Path(home) / 'claim.json')
    if not isinstance(own, dict) or own not in entries:
        return 'unclaimed', None
    found = match(own, repo.root) if repo is not None else None
    if found == 'full':
        return 'act', own
    return ('stale', own) if found == 'partial' else ('elsewhere', own)


def session_key(session_id):
    """The 16 hex digits naming a Claude Code session's files in the ship's sessions folder: the hook's state and
    `.prompted`, and the MCP tool's `.watch` (watch by default, W3). One function, so both sides name the same file."""
    return hashlib.sha256(session_id.encode('utf-8', 'surrogatepass')).hexdigest()[:16]


def acting_home(cwd):
    """The home of the first project ship under ships_root() (sorted by name) whose verdict for this session's
    project is 'act', else the machine ship's home."""
    project = session_project(cwd)
    root = ships_root()
    for home in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        if kind_of(home) == 'project' and verdict(home, project)[0] == 'act':
            return home
    return machine_home()
