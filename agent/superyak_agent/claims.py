"""Many ships on one machine (D7): which home a ship lives in, which kind of ship that makes it, and which ship a
session in a given project is. docs/superpowers/specs/2026-10-09-many-ships-one-machine-design.md

The machine ship lives in ~/.superyak and is everything it was before D7. A project ship lives in
~/.superyak/ships/<name> and claims one repository. The kind comes from the home, never from the registry (S1)."""
import json
import os
from pathlib import Path
import re

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
