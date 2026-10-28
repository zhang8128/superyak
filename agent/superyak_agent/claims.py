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
from .station import write_private
from .acting import (  # noqa: F401 - the acting-ship rule moved to acting.py; re-exported so callers and patches keep working
    FIELDS, NAME, Repo, Unreadable, _gitdir_of, _real, _valid, claim_files, kind_of, machine_home, match, project_home,
    project_root, read_json_quiet, read_registry, registry_path, session_project, ships_root, verdict)


class Refused(Exception):
    """A check that stops dock before it asks the station for anything or writes anything."""


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
    try:
        read_registry()         # R16: every dock refuses an unreadable registry, naming it
    except Unreadable as error:
        raise Refused(f'{error}. Every station hook on this machine is off until it is fixed; fix or remove it (remove '
                      'only with no ships/*/claim.json left), then dock again.') from None
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


# ---------- the claims registry (S6, R8, R16) ----------


def lock_path():
    return machine_home() / 'projects.lock'


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


def registry_line(error):
    """status's line for an unreadable registry (R16): the file, why, and what it means."""
    return (f"Superyak: {registry_path()} can't be read ({error}), so the station hooks on this machine are off and "
            'every station tool refuses. Fix or remove it (remove only with no ships/*/claim.json left), then dock again.')


LOUD = ("Superyak: ~/.superyak/projects.json can't be read, so the station hooks on this machine are off. "
        "Run `make dock` for your ship to see why.")


def stale_claims(entries):
    """Claims whose root is gone or now holds another folder (a moved repository, a re-clone at the same path, a
    remount), with why. Both ships go quiet there until the project ship docks again (R15)."""
    stale = []
    for entry in entries:
        try:
            st = os.stat(entry['root'])
        except OSError:
            stale.append((entry, 'its root is gone (moved or removed)'))
            continue
        if (st.st_dev, st.st_ino) != (entry['dev'], entry['ino']):
            stale.append((entry, 'its root now holds another folder (re-cloned or remounted)'))
    return stale


def inside_run():
    """Whether this process runs inside a teamd worker or a watcher run (SUPERYAK_RUN set to anything but `hook`)."""
    return os.environ.get('SUPERYAK_RUN') not in (None, '', 'hook')


def refusal(home, project_dir):
    """S7: why the station MCP server of the ship whose home this is refuses a call from a session in `project_dir`,
    or None when it may act. In order: inside a teamd worker or a watcher run; an unreadable registry; the machine
    ship in another ship's project (with the codex -p hint) or at a stale claim; a project ship at its stale claim,
    outside its claim, or with no claim."""
    if inside_run():
        return ('The station tools are off inside teamd workers and watcher runs (SUPERYAK_RUN is set): those act for '
                'the person through their own channels, never as a ship.')
    acts, detail = verdict(home, project_dir)
    ship = Path(home).name
    if acts == 'act':
        return None
    if acts == 'unreadable':
        return f'{detail}, so every station tool on this machine refuses. Run `make dock` for your ship to see why.'
    if acts == 'claimed':
        return (f"This session is in {detail['root']}, which {detail['ship']} claims. In Codex, run "
                f"`codex -p {detail['ship']}`; a Claude Code session started there uses {detail['ship']}'s station.")
    if acts == 'stale':
        return (f"{detail['ship']}'s claim on {detail['root']} is stale (the repository moved, or another folder is at "
                f"that path), so the station tools refuse here. Dock {detail['ship']} again to refresh it.")
    if acts == 'elsewhere':
        return f"{ship} acts only in {detail['root']}."
    return f'{ship} has no claim in {registry_path()}, so its station tools refuse. Dock it again.'


EXCLUDE_LINES = ('/.claude/settings.local.json', '/.claude/.settings.local.json.*')


def wiring_gaps(entry):
    """What a fully matched claim's project is missing, read from files only (no git, nothing written): the ship's
    hook in <root>/.claude/settings.local.json, and the two exclude lines in <common>/info/exclude. A re-clone where
    the file system reused the inode number (ext4 does) matches fully but has neither (review 487c070b)."""
    gaps = []
    root = Path(entry['root'])
    config = str(Path(entry['home']) / 'station.json')
    settings = root / '.claude' / 'settings.local.json'
    commands = []
    try:
        data = json.loads(settings.read_text())
        events = data.get('hooks') if isinstance(data, dict) else None
        for entries in (events or {}).values() if isinstance(events, dict) else []:
            for item in entries if isinstance(entries, list) else []:
                hooks = item.get('hooks') if isinstance(item, dict) else None
                commands += [h.get('command') for h in hooks or [] if isinstance(h, dict) and isinstance(h.get('command'), str)]
    except (OSError, ValueError):
        pass
    if not any('run_agent.py' in c and ' hook ' in f' {c} ' and config in c for c in commands):
        gaps.append(f"{settings} has no hook for {entry['ship']}")
    repo = project_root(root)
    try:
        lines = (repo.common / 'info' / 'exclude').read_text().splitlines() if repo is not None else []
    except OSError:
        lines = []
    if not all(line in lines for line in EXCLUDE_LINES):
        where = repo.common / 'info' / 'exclude' if repo is not None else root / '.git' / 'info' / 'exclude'
        gaps.append(f'{where} lacks the lines {", ".join(EXCLUDE_LINES)}')
    return gaps
