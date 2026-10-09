"""Many ships on one machine (D7): which home a ship lives in, which kind of ship that makes it, and which ship a
session in a given project is. docs/superpowers/specs/2026-10-09-many-ships-one-machine-design.md

The machine ship lives in ~/.superyak and is everything it was before D7. A project ship lives in
~/.superyak/ships/<name> and claims one repository. The kind comes from the home, never from the registry (S1)."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
from typing import NamedTuple
from .station import write_private

NAME = re.compile(r'[a-z][a-z0-9-]{1,31}')  # the station's own rule for ship usernames (peer ships.py)


class Refused(Exception):
    """A check that stops dock before it asks the station for anything or writes anything."""


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


def local_ships():
    """(home, station.json) of every ship docked on this machine: the machine ship's and each project ship's. A
    station.json that can't be read is a Refused: a name check that can't see a ship must not pass."""
    homes = [machine_home()] + (sorted(p for p in ships_root().iterdir() if p.is_dir()) if ships_root().is_dir() else [])
    found = []
    for home in homes:
        path = home / 'station.json'
        try:
            config = json.loads(path.read_text())
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as error:
            raise Refused(f'{path} can\'t be read ({type(error).__name__}), so dock can\'t check ship names. Fix or remove it, '
                          'then dock again.') from error
        if isinstance(config, dict):
            found.append((home, config))
    return found


def check_mode(ship, home, project):
    """S2, before any network call or write: the mode pairing, the station's name rule, the fixed homes and no name
    collision. Returns (home, kind). A project ship's home is ~/.superyak/ships/<ship>; the machine ship's is
    ~/.superyak. The collision checks read each station.json's `ship` (the station username), never `ship_name`, the
    display name the station makes from it ("Serenity Bricks"), which no --ship value can equal."""
    if ship is not None and not NAME.fullmatch(ship):
        raise Refused(f'{ship!r} isn\'t a ship name: ship names are 2 to 32 characters, lowercase letters, digits and '
                      'hyphens, starting with a letter (the station\'s own rule).')
    machine = machine_home()
    if project is not None:
        if not ship:
            raise Refused('A project ship needs --ship: make dock DOCK_ARGS="--ship <name> --project <repo>".')
        wanted = project_home(ship)
        if home is not None and _real(home) != _real(wanted):
            if _real(home) == _real(machine):
                raise Refused(f'--project needs the project home {wanted}, not {machine}, which is the machine ship\'s.')
            raise Refused(f'With --project, the home must be {wanted} (or leave out --home).')
        home, kind = wanted, 'project'
    else:
        if home is not None and _real(home) != _real(machine):
            if _real(home).parent == _real(ships_root()):
                raise Refused(f'The home {home} is a project ship\'s, so it needs --project <repo>.')
            raise Refused(f'Without --project, the home must be {machine} (the machine ship); {ships_root()}/<ship> needs --project.')
        home, kind = machine, 'machine'
    if ship:
        for other, config in local_ships():
            held = config.get('ship')
            if _real(other) == _real(home):
                if held and held != ship:
                    raise Refused(f'{other} holds the ship {held!r}, not {ship!r}. Undock it first, or dock {held!r} '
                                  'with its own name.')
            elif held == ship:
                raise Refused(f'{ship!r} is already this machine\'s ship at {other}. Docking it again from another home '
                              'would make the station revoke its key. Choose another name.')
    return home, kind


# ---------- which repository a directory is in (S6, R17). Never runs git: no repository config, hook or fsmonitor can
# run, and the hook stays inside its time budget. ----------

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


# ---------- the claims registry (S6, R8, R16) ----------

FIELDS = {'ship': str, 'home': str, 'root': str, 'dev': int, 'ino': int}


class Unreadable(Exception):
    """The registry can't be trusted: every hook goes quiet and every station tool refuses until it's fixed."""


def registry_path():
    return machine_home() / 'projects.json'


def lock_path():
    return machine_home() / 'projects.lock'


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


@contextmanager
def registry_lock():
    """One exclusive hold of ~/.superyak/projects.lock: every claim change, and dock's last checks before its claim,
    happen inside one hold."""
    machine_home().mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def claim_entry(ship, root):
    st = os.stat(root)
    return {'ship': ship, 'home': str(project_home(ship)), 'root': str(Path(os.path.realpath(root))),
            'dev': st.st_dev, 'ino': st.st_ino}


def claim(ship, root, held=False):
    """R8: write the claim, the registry entry first and then <home>/claim.json, in one hold of the lock (the caller's,
    when `held`). A claim for the same ship is replaced, which refreshes a stale one."""
    def write():
        entry = claim_entry(ship, root)
        entries = [e for e in read_registry() if e['ship'] != ship]
        write_private(registry_path(), entries + [entry])
        write_private(project_home(ship) / 'claim.json', entry)
        return entry
    if held:
        return write()
    with registry_lock():
        return write()


def unclaim(home, held=False):
    """R8: delete <home>/claim.json first, then the ship's registry entry, in one hold. projects.json is never deleted:
    the last removal writes []. Works with no claim. When the registry can't be read the entry stays, and the
    Unreadable says so after claim.json is gone."""
    def remove():
        home_path = Path(home)
        found = read_json_quiet(home_path / 'claim.json')
        (home_path / 'claim.json').unlink(missing_ok=True)
        ship = found.get('ship') if isinstance(found, dict) else home_path.name
        if not registry_path().exists() and not claim_files():
            return
        entries = read_registry()
        write_private(registry_path(), [e for e in entries if e['ship'] != ship])
    if held:
        return remove()
    with registry_lock():
        return remove()


def read_json_quiet(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def registry_line(error):
    """status's line for an unreadable registry (R16): the file, why, and what it means."""
    return (f"Superyak: {registry_path()} can't be read ({error}), so the station hooks on this machine are off and "
            'every station tool refuses. Fix or remove it (remove only with no ships/*/claim.json left), then dock again.')
