"""engram-permissions: the person's side of the permissions ledger (P 4.4, 7.6, 14; R12, R24).

The CLI acts only as the ledger owner, `meta.owner`, on the channel `terminal`. No command takes an argument naming
who acts. Every command that writes prints its change in words and in full, prints a 6-character code, and reads the
code back from /dev/tty. It refuses without a terminal.

Exit codes (R12): 0 done, 1 refused by a rule, 2 argparse's usage error, 3 no terminal or a wrong code.

Memory stays bounded: nothing here reads a store or the ledger whole. A memory's lane is read one row at a time from
a store opened read-only, and the ledger is read through the same `Ledger` calls the server uses.
"""
from __future__ import annotations

import argparse
import calendar
import contextlib
import getpass
import hmac
import json
import os
import select
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from permission_ledger import (PUBLISHED_HOUSE, Ledger, LedgerUnreadable, _seconds, effective_gate, houses,
                               ledger_path)
from permissions import (CODE_CHARS, Act, RuleError, check_id, disagreement_words, home_of, parse_object_ref,
                         proposal_words)

TTY = "/dev/tty"
TTY_WAIT = None          # seconds to wait for an answer; None waits for the person (a seam for tests)
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_RULE_YES = "7.6 the person's yes"
_LINE_BYTES = 64


class NoTerminal(Exception):
    """/dev/tty cannot be opened, so no yes can be given."""


def _code() -> str:
    """CODE_CHARS characters of _ALPHABET by rejection sampling from os.urandom (R12)."""
    size = len(_ALPHABET)
    limit = 256 - 256 % size
    out: list[str] = []
    while len(out) < CODE_CHARS:
        for byte in os.urandom(CODE_CHARS * 2):
            if byte < limit:
                out.append(_ALPHABET[byte % size])
                if len(out) == CODE_CHARS:
                    break
    return "".join(out)


def _read_line(fd: int) -> str:
    """One line from the terminal, a byte at a time so that a following line stays unread, at most
    _LINE_BYTES long. Nothing in time (TTY_WAIT) reads as an empty answer."""
    buf = bytearray()
    while len(buf) < _LINE_BYTES:
        if TTY_WAIT is not None and not select.select([fd], [], [], TTY_WAIT)[0]:
            break
        byte = os.read(fd, 1)
        if not byte or byte == b"\n":
            break
        buf += byte
    return buf.decode("utf-8", "replace").strip()


def confirm(words: str, change: str) -> bool:
    """Print the words, the full change and a code; read the code from TTY. Raises NoTerminal when TTY cannot be
    opened, before anything is printed."""
    try:
        fd = os.open(TTY, os.O_RDONLY | os.O_NOCTTY)
    except OSError as e:
        raise NoTerminal(f"{TTY} cannot be opened ({e.strerror or e})") from e
    try:
        code = _code()
        print(words)
        print()
        print(change)
        print()
        print(f"To say yes, type this code and press enter.\ncode: {code}", flush=True)
        answer = _read_line(fd)
    finally:
        os.close(fd)
    return hmac.compare_digest(answer.lower().encode(), code.encode())


# ---------------------------------------------------------------- small helpers

def _now() -> int:
    return int(time.time())


def _home() -> Path:
    return Path(os.environ.get("ENGRAM_HOME") or Path(__file__).resolve().parent)


def _when(text: str) -> int:
    """`YYYY-MM-DD` or RFC 3339 UTC (`YYYY-MM-DDTHH:MM:SSZ`) as UTC seconds."""
    try:
        if "T" not in text:
            when = datetime.strptime(text, "%Y-%m-%d")
        else:
            when = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError(f"{text!r} is not YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ (UTC)") from None
    return calendar.timegm(when.timetuple())


def _qualify(kind: str, value: str) -> str:
    """`jenn` as `person:jenn`; a full id is kept. Names are not hex ids, so no prefix lookup applies to them
    (resolve_prefix serves record, grant, proposal and receipt ids)."""
    return value if value.startswith(kind + ":") else f"{kind}:{value}"


@contextlib.contextmanager
def _ledger():
    try:
        led = Ledger.open(_home())
    except FileNotFoundError as e:
        raise RuleError("5.5 storage", f"there is no ledger at {e}; make one with `engram-permissions init`") from e
    try:
        yield led
    finally:
        led.close()


# ---------------------------------------------------------------- words and the full change

def _words(state, act: Act) -> str:
    a = act.args
    own = {
        "register-person": lambda: f"Register {a['person']}, with a home place, {home_of(a['person'])}, whose "
                                   f"layer is empty. Nothing about them moves until they say yes themselves.",
        "retire-person": lambda: f"Retire {a['person']} and their home.",
        "retire-place": lambda: f"Retire {a['place']}.",
        "remove-agent": lambda: f"Take {a['agent']} out of {a['place']}.",
        "remove-steward": lambda: f"Take {a['person']} off as a steward of {a['place']}.",
        "make-collection": lambda: f"Make the collection {a['collection']}.",
        "add-subject": lambda: f"Add {a['subject']} as a subject of {a['object']}.",
        "group": lambda: f"Set {a['group']} to {', '.join(a['members']) or 'no agents'}.",
    }
    if act.kind in own:
        return own[act.kind]()
    try:
        return proposal_words(state, act.kind, a)
    except (RuleError, KeyError, TypeError, ValueError):
        return f"Make the change {act.kind}."


def _change(act: Act) -> str:
    """The act in full, one value to a line. A list prints every item, a mapping every key."""
    lines = [f"change: {act.kind}"]
    for key in sorted(act.args):
        value = act.args[key]
        if isinstance(value, (list, tuple)):
            lines.append(f"  {key}:" + ("" if value else " (none)"))
            lines += [f"    - {item}" for item in value]
        elif isinstance(value, dict):
            lines.append(f"  {key}:" + ("" if value else " (none)"))
            lines += [f"    {k}: {json.dumps(v, sort_keys=True)}" for k, v in sorted(value.items())]
        else:
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)


# ---------------------------------------------------------------- after a write: reports and the sweep

def _print_reports(state, reports, owner: str) -> None:
    """P 8: the gluing reports whose `notify` holds the owner."""
    for report in reports:
        if owner in report.notify:
            words = disagreement_words(state, report)
            if words:
                print(words)


def _sweep_house(led: Ledger, mode: str, now: int):
    """P 10: make the published house follow the ledger."""
    import sharing
    from storage import Storage
    house = Storage(str(led.root / PUBLISHED_HOUSE))
    try:
        return sharing.sweep_placements(published_storage=house, ledger=led, mode=mode, now=now)
    finally:
        house.close()


def run_sweep(led: Ledger, now: int) -> None:
    """R18: after a command that writes, sweep the published house under `shadow` and `enforce`, and fold receipts
    past their retention. A failure is a warning and never changes the exit code (ledger ruling FS1)."""
    try:
        house = led.root / PUBLISHED_HOUSE
        gate = effective_gate(led.root, [house])
        if gate.mode in ("shadow", "enforce") and house.is_file():
            report = _sweep_house(led, gate.mode, now)
            if any((report.relinked, report.removed, report.would_remove, report.settled)):
                print(f"Placement sweep: {report.relinked} relinked, {report.removed} removed, "
                      f"{report.would_remove} would be removed, {report.settled} lane notes settled.")
    except Exception as e:
        print(f"warning: the placement sweep failed: {e}", file=sys.stderr)
    try:
        from permission_uses import Uses, uses_path
        if uses_path(led.root).is_file():
            uses = Uses.open(led.root)
            try:
                uses.fold(now=now)
            finally:
                uses.close()
    except Exception as e:
        print(f"warning: the receipt fold failed: {e}", file=sys.stderr)


def _perform(led: Ledger, owner: str, acts: list[Act], notes: list[str]) -> int:
    """Print words and the full change, ask the yes, then perform each act as the owner on `terminal`."""
    state = led.state()
    words = " ".join(_words(state, act) for act in acts)
    change = "\n".join([_change(act) for act in acts] + notes)
    if not confirm(words, change):
        print("That was not the code. Nothing was written.", file=sys.stderr)
        return 3
    now = _now()
    outcomes = [led.perform(act, actor=owner, channel="terminal", now=now) for act in acts]
    for out in outcomes:
        if out.status == "proposal":
            print(f"Filed proposal {out.ref}. Each steward it needs signs it with `engram-permissions sign "
                  f"{out.ref}`.")
        else:
            print(f"Done: {out.ref} (log {out.seq}).")
    state = led.state()
    for out in outcomes:
        _print_reports(state, out.reports, owner)
        if out.pending_checks:
            shown = ", ".join(out.pending_checks[:10])
            more = f" and {len(out.pending_checks) - 10} more" if len(out.pending_checks) > 10 else ""
            print(f"{len(out.pending_checks)} more joint places were not checked here: {shown}{more}.")
    run_sweep(led, now)
    return 0


def _write(make) -> int:
    """`make(led, state, owner) -> (acts, notes)`; then the yes and the writes."""
    with _ledger() as led:
        owner = led.meta()["owner"]
        acts, notes = make(led, led.state(), owner)
        return _perform(led, owner, acts, notes)


# ---------------------------------------------------------------- reading a memory's lane from its store

class _Stores:
    """Each local store, found by `meta.instance_id` and opened read-only once, one row read at a time."""

    def __init__(self, root: Path):
        self.root = root
        self._paths: dict[str, Path] | None = None
        self._open: dict[str, object] = {}

    def _find(self) -> dict[str, Path]:
        from store_identity import read as read_identity
        found: dict[str, Path] = {}
        for path in houses(self.root):
            try:
                con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
            except sqlite3.Error:
                continue
            try:
                iid = read_identity(con).get("instance_id")
            except sqlite3.Error:
                iid = None
            finally:
                con.close()
            if iid:
                found.setdefault(iid, path)
        return found

    def row(self, ref: str) -> dict | None:
        from storage import Storage
        obj = parse_object_ref(ref)
        if obj.kind != "memory":
            return None
        if self._paths is None:
            self._paths = self._find()
        path = self._paths.get(obj.instance_id)
        if path is None:
            return None
        try:
            if obj.instance_id not in self._open:
                self._open[obj.instance_id] = Storage.open_read_only(path)
            store = self._open[obj.instance_id]
            return store.get_episode(obj.local_id) if obj.layer == "episode" else store.get_semantic(obj.local_id)
        except (FileNotFoundError, sqlite3.Error):
            return None

    def close(self) -> None:
        for store in self._open.values():
            store.close()
        self._open.clear()


# ---------------------------------------------------------------- the commands

def _init(args) -> int:
    root = _home()
    path = ledger_path(root)
    if path.exists():
        raise RuleError("4.4 create a ledger", f"a ledger already exists at {path}")
    try:
        login = getpass.getuser()
        check_id("person", "person:" + login)
    except (RuleError, OSError, KeyError) as e:
        raise RuleError("24 the owner is the login", f"the Unix login name is not a person handle ({e}); "
                        "a handle is lowercase letters, digits, - and _") from e
    owner = "person:" + login
    words = (f"Create a ledger owned by {owner}. You become its owner and its only admin, and a person on it, "
             f"with the home place {home_of(owner)}.")
    change = f"change: create the ledger file {path}\n  owner: {owner}\n  home: {home_of(owner)}"
    if not confirm(words, change):
        print("That was not the code. Nothing was written.", file=sys.stderr)
        return 3
    try:
        Ledger.create(root, login, now=_now()).close()
    except FileExistsError as e:
        raise RuleError("4.4 create a ledger", f"a ledger already exists at {e}") from e
    print(f"Created the ledger at {path}.")
    return 0


def _person_add(a):
    return _write(lambda led, st, owner: ([Act("register-person", {"person": _qualify("person", a.handle)})], []))


def _person_retire(a):
    return _write(lambda led, st, owner: ([Act("retire-person", {"person": _qualify("person", a.handle)})], []))


def _acts_for(value: str) -> str:
    return home_of(value) if value.startswith("person:") else _qualify("place", value)


def _agent_add(a):
    return _write(lambda led, st, owner: (
        [Act("register-agent", {"agent": _qualify("agent", a.name), "acts_for": _acts_for(a.acts_for)})], []))


def _agent_place(kind):
    def run(a):
        return _write(lambda led, st, owner: (
            [Act(kind, {"agent": _qualify("agent", a.name), "place": _qualify("place", a.place)})], []))
    return run


def _store_add(a):
    def make(led, st, owner):
        args = {"instance_id": a.instance_id, "name": a.name, "owner": owner,
                "place": _qualify("place", a.place) if a.place else home_of(owner), "imprint_of": a.imprint_of}
        return [Act("register-store", args)], []
    return _write(make)


def _place_register(a):
    def make(led, st, owner):
        args = {"place": _qualify("place", a.place), "parents": [_qualify("place", p) for p in a.parent or []],
                "stewards": [_qualify("person", s) for s in a.steward] if a.steward else [owner]}
        if a.name is not None:
            args["name"] = a.name
        return [Act("register-place", args)], []
    return _write(make)


def _place_parent(a):
    return _write(lambda led, st, owner: (
        [Act("add-parent", {"place": _qualify("place", a.place), "parent": _qualify("place", a.parent)})], []))


def _steward(kind):
    def run(a):
        return _write(lambda led, st, owner: (
            [Act(kind, {"place": _qualify("place", a.place), "person": _qualify("person", a.person)})], []))
    return run


def _place_retire(a):
    return _write(lambda led, st, owner: ([Act("retire-place", {"place": _qualify("place", a.place)})], []))


def _group_set(a):
    return _write(lambda led, st, owner: (
        [Act("group", {"group": _qualify("group", a.name), "members": [_qualify("agent", m) for m in a.agents]})],
        []))


def _collection(adding: bool):
    def run(a):
        def make(led, st, owner):
            cid = _qualify("collection", a.collection)
            refs = list(dict.fromkeys(a.refs))
            acts: list[Act] = []
            notes: list[str] = []
            if not adding:
                return [Act("uncollect", {"collection": cid, "objects": refs})], notes
            if cid not in st.collections:
                acts.append(Act("make-collection", {"collection": cid}))
            lanes: dict[str, dict] = {}
            stores = _Stores(led.root)
            try:
                for ref in refs:
                    if parse_object_ref(ref).kind != "memory" or st.lane_notes.get(ref):
                        continue
                    row = stores.row(ref)
                    if row is None:
                        notes.append(f"note: no lane read for {ref}: its store is not on this machine, or it is "
                                     "not there; it is added with no lane note")
                    else:
                        lanes[ref] = {"lane": row.get("lane") or "personal",
                                      "created_at": _seconds(row["created_at"])}
            finally:
                stores.close()
            acts.append(Act("collect", {"collection": cid, "objects": refs, "lanes": lanes}))
            return acts, notes
        return _write(make)
    return run


def _subject(kind):
    def run(a):
        return _write(lambda led, st, owner: (
            [Act(kind, {"object": a.ref, "subject": _qualify("person", a.subject)})], []))
    return run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="engram-permissions", allow_abbrev=False,
        description="The person's side of the permissions ledger. Every command that writes asks for a code "
                    "from /dev/tty, and acts as the ledger owner.")
    top = parser.add_subparsers(dest="command", required=True, metavar="command")

    def group(name, help_):
        p = top.add_parser(name, help=help_, allow_abbrev=False)
        return p.add_subparsers(dest="action", required=True, metavar="action")

    def leaf(sub, name, func, help_=None):
        p = sub.add_parser(name, help=help_, allow_abbrev=False)
        p.set_defaults(func=func)
        return p

    init = top.add_parser("init", help="create the ledger, owned by the Unix login", allow_abbrev=False)
    init.set_defaults(func=_init)

    people = group("person", "register or retire a person")
    leaf(people, "add", _person_add).add_argument("handle")
    leaf(people, "retire", _person_retire).add_argument("handle")

    agents = group("agent", "register an agent, or put it in a place")
    p = leaf(agents, "add", _agent_add)
    p.add_argument("name")
    p.add_argument("--acts-for", required=True, help="the place it acts for, or the person (their home)")
    for verb, kind in (("place", "put-agent"), ("unplace", "remove-agent")):
        p = leaf(agents, verb, _agent_place(kind))
        p.add_argument("name")
        p.add_argument("place")

    stores = group("store", "register a store")
    p = leaf(stores, "add", _store_add)
    p.add_argument("instance_id")
    p.add_argument("--name")
    p.add_argument("--place", help="default: the owner's home")
    p.add_argument("--imprint-of", help="the instance_id of the store this one is an imprint of")

    places = group("place", "register, join, steward or retire a place")
    p = leaf(places, "register", _place_register)
    p.add_argument("place")
    p.add_argument("--parent", action="append")
    p.add_argument("--name")
    p.add_argument("--steward", action="append", help="default: the owner")
    p = leaf(places, "parent", _place_parent)
    p.add_argument("place")
    p.add_argument("parent")
    steward = places.add_parser("steward", help="add or remove a steward", allow_abbrev=False)
    steward_sub = steward.add_subparsers(dest="steward_action", required=True, metavar="add|remove")
    for verb, kind in (("add", "add-steward"), ("remove", "remove-steward")):
        p = leaf(steward_sub, verb, _steward(kind))
        p.add_argument("place")
        p.add_argument("person")
    leaf(places, "retire", _place_retire).add_argument("place")

    groups = group("group", "set a group's members")
    p = leaf(groups, "set", _group_set)
    p.add_argument("name")
    p.add_argument("agents", nargs="*")

    collections = group("collection", "add or remove memories")
    for verb, adding in (("add", True), ("remove", False)):
        p = leaf(collections, verb, _collection(adding))
        p.add_argument("collection")
        p.add_argument("refs", nargs="+")

    subjects = group("subject", "add or remove a subject of an object")
    for verb, kind in (("add", "add-subject"), ("remove", "remove-subject")):
        p = leaf(subjects, verb, _subject(kind))
        p.add_argument("ref")
        p.add_argument("subject")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except NoTerminal as e:
        print(f"no terminal: {e}. Nothing was written.", file=sys.stderr)
        return 3
    except RuleError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    except (LedgerUnreadable, sqlite3.Error) as e:
        print(f"the ledger cannot be used: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
