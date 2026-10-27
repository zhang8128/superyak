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
import re
import select
import shlex
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from permission_ledger import (PUBLISHED_HOUSE, Ledger, LedgerUnreadable, _lacks_029, _seconds, _words_kind,
                               effective_gate, houses, ledger_path)
from permissions import (CODE_CHARS, MAX_BULK_DERIVED, REGISTRY, USE_LIST_ROWS, Act, BulkUse, RuleError, Use,
                         affected_joints, allow_words, check_id, decide, decide_bulk, disagreement_words, gluing,
                         home_of, parse_copy_ref, parse_object_ref, parse_selector, placement_still_counts, proposal_words,
                         resolve_prefix, selector_json, share_cover, stewards)

TTY = "/dev/tty"
TTY_WAIT = None          # seconds to wait for an answer; None waits for the person (a seam for tests)
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_RULE_YES = "7.6 the person's yes"
_LINE_BYTES = 64
SELECTOR_FILE_BYTES = 4 * 1024 * 1024     # a selector file larger than this is refused unread (bounded memory)
PROPOSALS_SHOWN = 50
REPORT_ROWS = 200                         # rows `report shadow` lists of each kind; the counts are always whole
MAX_OBJECT_LINES = MAX_BULK_DERIVED + 1   # `explain --objects` reads this many lines at most, enough to be refused
_OBJECT_LINE_BYTES = 1024
_TIME_KEYS = frozenset({"valid_from", "valid_until", "expires"})


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
def _ledger(read_only: bool = False):
    try:
        led = Ledger.open_read_only(_home()) if read_only else Ledger.open(_home())
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
    if act.kind in ("revoke", "shorten", "narrow") and a.get("record") in state.records:
        rec = state.records[a["record"]]
        kind = _words_kind(state, act)
        if kind == "withdraw":
            return f"Withdraw the allow {rec.id}. It was: {allow_words(state, rec)}"
        try:
            return proposal_words(state, kind, a)
        except (RuleError, KeyError, TypeError, ValueError):
            return f"Make the change {kind} to {rec.id}."
    if act.kind == "revoke-grant" and a.get("grant") in state.grants:
        g = state.grants[a["grant"]]
        return (f"Revoke the grant {g.id} to {g.grantee} in {g.layer}. A grant that is revoked is never valid "
                f"again, and what was done under it stops.")
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
        elif key in _TIME_KEYS:
            lines.append(f"  {key}: {_time_text(value)}")
        else:
            lines.append(f"  {key}: {_clean(value)}")
    return "\n".join(lines)


def _clean(value) -> str:
    """One line with no control characters: text from an agent is data, and must not move the cursor."""
    return "".join(c if c.isprintable() else "?" for c in str(value))


def _time_text(value) -> str:
    if value is None:
        return "none (no end)"
    if isinstance(value, int) and not isinstance(value, bool):
        try:
            return f"{value} ({datetime.fromtimestamp(value, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')})"
        except (OverflowError, OSError, ValueError):        # an agent-filed time out of the calendar: show the raw int
            return str(value)
    return str(value)


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


def run_sweep(led: Ledger, now: int):
    """R18: after a command that writes, sweep the published house under `shadow` and `enforce`, and fold receipts
    past their retention. A failure is a warning and never changes the exit code (ledger ruling FS1). Returns the
    sweep's report, or None when the gate is off or the sweep did not run."""
    report = None
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
    return report


def _perform(led: Ledger, owner: str, acts: list[Act], notes: list[str], words: str | None = None) -> int:
    """Print words and the full change, ask the yes, then perform each act as the owner on `terminal`. `words`
    replaces the acts' own words (a proposal's, with who filed it)."""
    state = led.state()
    words = words or " ".join(_words(state, act) for act in acts)
    change = "\n".join([_change(act) for act in acts] + notes)
    if not confirm(words, change):
        print("That was not the code. Nothing was written.", file=sys.stderr)
        return 3
    now = _now()
    outcomes = [led.perform(act, actor=owner, channel="terminal", now=now) for act in acts]
    for act, out in zip(acts, outcomes):
        if act.kind in ("sign", "decline"):
            if out.status == "proposal":
                print(f"Signed {out.ref}. It still needs the other stewards' signatures (log {out.seq}).")
            else:
                print(f"Done: {out.ref} (log {out.seq}).")
        elif out.status == "proposal":
            print(f"Filed proposal {out.ref}. Each steward it needs signs it with `engram-permissions sign "
                  f"{out.ref}`.")
        else:
            print(f"Done: {out.ref} (log {out.seq}).")
    state = led.state()
    for out in outcomes:
        if out.lacking_029:
            print("These houses lack migration 029 and serve nothing under `shadow` or `enforce` until an engram "
                  "server opens them once:\n" + "\n".join(f"  - {h}" for h in out.lacking_029))
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

def _owner_login() -> str:
    """R24: the owner's handle is the Unix login."""
    try:
        login = getpass.getuser()
        check_id("person", "person:" + login)
    except (RuleError, OSError, KeyError) as e:
        raise RuleError("24 the owner is the login", f"the Unix login name is not a person handle ({e}); "
                        "a handle is lowercase letters, digits, - and _") from e
    return login


def _init(args) -> int:
    root = _home()
    path = ledger_path(root)
    if path.exists():
        raise RuleError("4.4 create a ledger", f"a ledger already exists at {path}")
    login = _owner_login()
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


# ---------------------------------------------------------------- records, grants and proposals (P 7.1 to 7.7)

def _read_text(path: str, rule: str, what: str) -> str:
    """A small text file, read at most SELECTOR_FILE_BYTES (a larger one is refused unread-whole)."""
    try:
        with open(path, "rb") as f:
            raw = f.read(SELECTOR_FILE_BYTES + 1)
    except OSError as e:
        raise RuleError(rule, f"{path} cannot be read ({e.strerror or e})") from e
    if len(raw) > SELECTOR_FILE_BYTES:
        raise RuleError(rule, f"{path} is too large: a {what} file is at most {SELECTOR_FILE_BYTES:,} bytes")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise RuleError(rule, f"{path} is not UTF-8 text") from None


def _selector(text: str) -> str:
    """A selector as canonical JSON, from JSON text or `@file` (read at most SELECTOR_FILE_BYTES)."""
    if text.startswith("@"):
        text = _read_text(text[1:], "5.2 selector", "selector")
    return selector_json(parse_selector(text))


def _record_note(rec, heading: str) -> str:
    return "\n".join([f"{heading} {rec.id}:", f"  effect: {rec.effect}", f"  layer: {rec.layer}",
                       f"  selector: {selector_json(rec.selector)}", f"  valid_from: {_time_text(rec.valid_from)}",
                       f"  valid_until: {_time_text(rec.valid_until)}"])


def _record_write(effect: str):
    def run(a):
        def make(led, st, owner):
            args = {"layer": a.layer, "selector": _selector(a.selector),
                    "valid_from": _now() if a.valid_from is None else a.valid_from, "valid_until": a.until,
                    "reason": a.reason}
            return [Act(effect, args)], []
        return _write(make)
    return run


def _record_edit(kind: str):
    def run(a):
        def make(led, st, owner):
            rid = resolve_prefix(st.records, a.id)
            args: dict = {"record": rid, "reason": a.reason}
            if kind == "shorten":
                args["valid_until"] = a.until
            if kind == "narrow":
                args["selector"] = _selector(a.selector)
            note = _record_note(st.records[rid], "replaces record" if kind != "revoke" else "ends record")
            return [Act(kind, args)], [note]
        return _write(make)
    return run


def _grant(a):
    def make(led, st, owner):
        args: dict = {"grantee": _qualify("agent", a.to), "ops": sorted({o for t in a.ops for o in t.split(",") if o}),
                      "envelope": _selector(a.envelope), "max_days": a.max_days, "depth": a.depth, "hours": a.hours}
        if a.parent:
            args["parent"] = resolve_prefix(st.grants, a.parent)
        if a.layer or not a.parent:
            args["layer"] = _qualify("place", a.layer) if a.layer else home_of(owner)
        return [Act("grant", args)], []
    return _write(make)


def _revoke_grant(a):
    def make(led, st, owner):
        gid = resolve_prefix(st.grants, a.id)
        g = st.grants[gid]
        note = (f"grant {gid}:\n  grantee: {g.grantee}\n  layer: {g.layer}\n  ops: {', '.join(json.loads(g.ops))}\n"
                f"  envelope: {g.envelope}")
        return [Act("revoke-grant", {"grant": gid, "reason": a.reason})], [note]
    return _write(make)


def gate_plan_lines(plan: dict) -> list[str]:
    """What a `gate` act would use if applied now (R26, R27), for `sign` here and `gate` in Task 27."""
    lines = [f"gate plan, read now (the yes reads the houses again):",
             f"  published house: {plan['published_house']}", "  every house it will mark:"]
    lines += [f"    - {h}" for h in plan["houses"]] or ["    (none)"]
    if plan["lacking_029"]:
        lines.append("  houses that lack migration 029: each serves nothing under `shadow` or `enforce` until an "
                     "engram server opens it once:")
        lines += [f"    - {h}" for h in plan["lacking_029"]]
    return lines


def _proposal_of(led: Ledger, st, given: str, owner: str):
    pid = resolve_prefix(st.proposals, given)
    p = st.proposals[pid]
    if p.status != "pending":
        raise RuleError("7.7 proposals", f"{pid} is not pending: it is {p.status}")
    if p.expires <= _now():
        raise RuleError("7.7 proposals", f"{pid} has expired")
    body = json.loads(p.body)
    return p, body, Act(body["act"]["kind"], dict(body["act"]["args"]))


def _on_proposal(kind: str):
    def run(a):
        with _ledger() as led:
            owner = led.meta()["owner"]
            st = led.state()
            p, body, inner = _proposal_of(led, st, a.id, owner)
            what = _words(st, inner)
            verb = "Sign" if kind == "sign" else "Decline"
            words = f"{verb} proposal {p.id}, filed by {p.by_agent}. {what}"
            notes = [f"proposal {p.id} would make this change:"]
            notes += ["  " + line for line in _change(inner).splitlines()]
            if body.get("needs") is not None:
                notes.append(f"needs: {json.dumps(body['needs'], sort_keys=True)}")
            if kind == "sign" and inner.kind == "gate":
                notes += gate_plan_lines(led.gate_plan())
            return _perform(led, owner, [Act(kind, {"proposal": p.id})], notes, words=words)
    return run


def _proposals(a) -> int:
    with _ledger() as led:
        rows = led.proposals(now=_now())
    if not rows:
        print("No open proposals.")
        return 0
    for row in rows[:PROPOSALS_SHOWN]:
        print(f"{row['id']}  {row['kind']}  from {_clean(row['by_agent'])}  expires {_time_text(row['expires'])}")
        print(f"  {_clean(row['words'])}")
        if row["signatures"]:
            print(f"  signed by: {', '.join(_clean(s) for s in row['signatures'])}")
        if row["reason"]:
            print(f"  the agent's reason (its words, not ours): {_clean(row['reason'])}")
    if len(rows) > PROPOSALS_SHOWN:
        print(f"... and {len(rows) - PROPOSALS_SHOWN} more.")
    return 0


# ---------------------------------------------------------------- the gate, and the commands that only read (P 14)

def _gate(a) -> int:
    with _ledger() as led:
        owner = led.meta()["owner"]
        notes = gate_plan_lines(led.gate_plan())
        return _perform(led, owner, [Act("gate", {"mode": a.mode})], notes)


def _rebuild(a) -> int:
    with _ledger(read_only=True) as led:
        try:
            dest = led.rebuild(Path(a.out))
        except FileExistsError as e:
            raise RuleError("5.6 rebuild", f"a ledger already exists at {e}; --out names a directory with none") \
                from e
    print(f"Rebuilt the ledger at {ledger_path(dest)}. Its tables are the log's replay.")
    return 0


def _stamp(value) -> str:
    return "none" if value is None else _time_text(value)


def _use_line(r: dict) -> list[str]:
    who = r.get("agent") or r.get("requester")
    what = f"{r['action']} {r['object']}" if r.get("object") else f"{r['action']} ({r.get('kind') or r.get('count')})"
    lines = [f"{_stamp(r['at'])}  {r['outcome']}  {_clean(who)}  {_clean(what)}  at {_clean(r['place'])}  "
             f"for {_clean(r['purpose'])}  [{r['id']}]"]
    if r.get("refusal"):
        ref = r["refusal"]
        lines.append(f"    refused: {_clean(ref.get('code'))} at {_clean(ref.get('layer'))}")
    lines += [f"    note: {_clean(n)}" for n in r.get("notes") or ()]
    return lines


def _copies_held() -> list:
    """The imprint copies this machine holds at a station (imprint_copies reads two files and loads no numpy)."""
    from imprint_copies import copies_held
    return copies_held(Path(os.environ.get("SUPERYAK_HOME") or Path.home() / ".superyak"))


def _uses(a) -> int:
    from permission_uses import Uses, uses_path
    copies = []
    with _ledger(read_only=True) as led:
        state = led.state()
        owner = state.meta["owner"]
        place = _qualify("place", a.place) if a.place else None
        if not uses_path(led.root).is_file():
            shown = None
            if place is None:
                copies = _copies_held()
        else:
            uses = Uses.open_read_only(led.root)
            try:
                filters = dict(since=a.since, until=a.until, action=a.action, purpose=a.purpose,
                               collection=a.collection and _qualify("collection", a.collection), obj=a.object,
                               refused=a.refused)
                if place is not None and place in state.places and owner in stewards(state, place):
                    shown = uses.place_view(state, place, **filters)            # a place he stewards: P 9.2's view
                else:
                    copies = _copies_held()
                    shown = uses.owner_list(state, place=place, copies=copies, **filters)
            finally:
                uses.close()
    counts, rows = (shown.counts, shown.rows) if shown else ({"total": 0, "local": 0, "imported": 0}, [])
    if a.json:
        print(json.dumps({"counts": counts, "rows": rows, "copies": copies}, sort_keys=True))
        return 0
    for c in copies:
        print(_clean(c["line"]))
    if not rows:
        print("No uses.")
        return 0
    print(f"{counts['total']} uses ({counts['local']} local, {counts['imported']} imported); "
          f"showing the newest {len(rows)}.")
    for r in rows:
        for line in _use_line(r):
            print(line)
    return 0


def _check(a) -> int:
    with _ledger(read_only=True) as led:
        state = led.state()
        if a.place:
            place = _qualify("place", a.place)
            if place not in state.places:
                raise RuleError("8 the check", f"{place} is not a registered place")
            places = [place]
        else:
            places = list(affected_joints(state, {REGISTRY}))
        said = 0
        for place in places:
            words = disagreement_words(state, gluing(state, place))
            if words:
                said += 1
                print(words)
    if not said:
        print("No disagreement found" + (f" in {places[0]}." if a.place else " in any joint place."))
    return 0


def _sweep(a) -> int:
    with _ledger() as led:
        mode = effective_gate(led.root, houses(led.root)).mode
        report = run_sweep(led, _now())
    if report is None:
        print(f"The gate is {mode}: nothing to sweep." if mode not in ("shadow", "enforce") else
              "Placement sweep: nothing to change.")
    return 0


def _place_show(a) -> int:
    place = _qualify("place", a.place)
    with _ledger(read_only=True) as led:
        art = led.place_rules(place, now=_now())
    if a.json:
        print(json.dumps(art, sort_keys=True))
        return 0
    p = art["payload"]
    print(f"{p['place']}" + (" (retired)" if p["retired"] else "") + f" at ledger seq {p['ledgerSeq']}")
    print(f"  parents: {', '.join(p['parents']) or '(none)'}")
    print(f"  stewards: {', '.join(p['stewards']) or '(none)'}")
    print(f"  records: {len(p['records'])}")
    for r in p["records"]:
        print(f"    {r['id']}  {r['effect']}  {json.dumps(r['selector'], sort_keys=True)}  "
              f"from {_stamp(r['valid_from'])} until {_stamp(r['valid_until'])}")
    return 0


# ---------------------------------------------------------------- migrate (P 12.3 step 2)

COLLECT_CHUNK = 500                       # memories added by one `collect` act, so one log row stays small
_SOURCE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_LEGACY_ACTIONS = ["inject_context", "read", "recall"]


def _store_id_ok(iid) -> str | None:
    """`iid` when it is a store id the ledger can register, else None."""
    if not iid:
        return None
    try:
        parse_copy_ref("store:" + iid)
    except RuleError:
        return None
    return iid


def _house_id(path: Path) -> str | None:
    """A house's `meta.instance_id`, read with mode=ro; None when it has none or it cannot be registered."""
    from store_identity import read as read_identity
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        return _store_id_ok(read_identity(con).get("instance_id"))
    except sqlite3.Error:
        return None
    finally:
        con.close()


class _Sources:
    """The source stores a share row can name (`default`, or an instance name), each opened read-only once."""

    def __init__(self, root: Path):
        self.base = root / ".engram"
        self._open: dict[str, tuple] = {}

    def _find(self, name: str) -> tuple:
        """(store, instance_id), or (None, why)."""
        from storage import Storage
        if name != "default" and (_SOURCE_NAME.fullmatch(name) is None or name in (".", "..")):
            return None, "its source instance name is not a store name"
        path = self.base / "graph.db" if name == "default" else self.base / "instances" / name / "graph.db"
        if not path.is_file():
            return None, f"no store {name!r} on this machine (the share fell back to another store)"
        try:
            store = Storage.open_read_only(path)
        except (FileNotFoundError, sqlite3.Error):
            return None, f"the store {name!r} cannot be opened"
        from store_identity import read as read_identity
        try:
            iid = _store_id_ok(read_identity(store.conn).get("instance_id"))
        except sqlite3.Error:
            iid = None
        if iid is None:
            store.close()
            return None, f"the store {name!r} has no usable instance_id"
        return store, iid

    def check(self, row) -> tuple[dict | None, str | None]:
        """P 12.3: the named store has the source memory with the row's `content_digest`. Returns the facts the
        migration needs (instance id, lane, created_at) or the reason it fails."""
        from lighthouse_protocol import content_digest
        name = row["source_instance"]
        if name not in self._open:
            self._open[name] = self._find(name)
        store, iid = self._open[name]
        if store is None:
            return None, iid
        got = store.get_episode(row["source_id"]) if row["layer"] == "episode" else store.get_semantic(row["source_id"])
        if got is None:
            return None, f"the source {row['layer']} is not in the store {name!r}"
        if content_digest(got.get("content", ""))["value"] != row["content_digest"]:
            return None, f"the source {row['layer']} in {name!r} no longer has the shared content"
        try:
            created = _seconds(got.get("created_at"))
        except (ValueError, TypeError):
            return None, "its source has no readable created_at"
        return {"instance_id": iid, "lane": got.get("lane") or "personal", "created_at": created}, None

    def close(self) -> None:
        for store, _ in self._open.values():
            if store is not None:
                store.close()
        self._open.clear()


def _migrate_receivers(root: Path, notes: list[str]) -> list[str]:
    """The receivers the publisher policies' rules name (`urn:engram:<receiver>`), sorted."""
    from lighthouse_validation import load_owned_policy
    found: set[str] = set()
    instances = root / ".engram" / "instances"
    for policy_path in sorted(instances.glob("*/lighthouse-policy.json")) if instances.is_dir() else []:
        publisher = policy_path.parent.name
        try:
            policy = load_owned_policy(policy_path, publisher)
        except Exception as e:                                   # PolicyError, and whatever a hostile file raises
            notes.append(f"note: the policy of {publisher} cannot be read ({getattr(e, 'code', e)}); "
                         "its receivers are not registered")
            continue
        for rule in policy.rules:
            for urn in rule.get("publishers") or ():
                name = urn[len("urn:engram:"):] if urn.startswith("urn:engram:") else None
                try:
                    if name is None or "*" in name:
                        raise RuleError("4.1", "not an agent")
                    check_id("agent", "agent:" + name)
                except RuleError:
                    notes.append(f"note: {_clean(urn)} in the policy of {publisher} is not one receiver; "
                                 "no agent is registered for it")
                    continue
                found.add(name)
    return sorted(found)


def _migrate_rows(root: Path, house: Path, groups: dict) -> tuple[list[dict], list[dict]]:
    """(migrated, unmatched): every share row of the published house, read one at a time, each source checked."""
    from sharing import validate_audience
    con = sqlite3.connect(f"{house.resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    sources = _Sources(root)
    migrated: list[dict] = []
    unmatched: list[dict] = []
    try:
        try:
            cursor = con.execute("SELECT share_id, memory_id, source_instance, source_id, layer, audience, "
                                 "content_digest FROM shared_memories ORDER BY shared_at, share_id")
        except sqlite3.OperationalError as e:
            raise RuleError("12.3 migrate", f"{house} has no shared_memories ({e}); an engram server opens it "
                                            "once to run its migrations") from e
        for row in cursor:
            def lost(why, row=row):
                unmatched.append({"share_id": row["share_id"], "memory_id": row["memory_id"],
                                  "audience": row["audience"], "source_instance": row["source_instance"],
                                  "layer": row["layer"], "source_id": row["source_id"], "why": why})
            audience = row["audience"]
            try:
                validate_audience(audience)
            except (TypeError, ValueError):
                lost("its audience is neither commons nor group:<name>")
                continue
            if audience != "commons" and audience[len("group:"):] not in groups:
                lost(f"{audience} is not a group of groups.toml")
                continue
            if row["layer"] not in ("episode", "semantic"):
                lost("its layer is not shareable")
                continue
            info, why = sources.check(row)
            if info is None:
                lost(why)
                continue
            ref = f"mem:{info['instance_id']}/{row['layer']}/{row['source_id']}"
            try:
                parse_object_ref(ref)
            except RuleError:
                lost("its source id is not a memory id the ledger can name")
                continue
            collection = ("legacy-commons" if audience == "commons" else "legacy-group-" + audience[len("group:"):])
            migrated.append({"share_id": row["share_id"], "memory_id": row["memory_id"], "audience": audience,
                             "collection": collection, "object": ref, "source_instance": row["source_instance"],
                             "source_instance_id": info["instance_id"], "layer": row["layer"],
                             "source_id": row["source_id"], "lane": info["lane"], "created_at": info["created_at"]})
    finally:
        sources.close()
        con.close()
    return migrated, unmatched


def _migrate_groups(path: Path) -> dict[str, list[str]]:
    """The groups of `groups.toml`; no file means no groups. A file that does not load is a refusal."""
    from policy_gen import load_groups
    if not path.is_file():
        return {}
    try:
        return load_groups(path)
    except ValueError as e:
        raise RuleError("12.3 migrate", f"{path} is not a valid groups file ({e})") from e


def _legacy_selector(owner_login: str, audience: str, collection: str) -> str:
    return _selector(json.dumps({
        "audience": [audience], "requesters": "*", "actions": _LEGACY_ACTIONS, "purposes": "*",
        "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
                    "collections": [f"collection:{owner_login}/{collection}"], "memories": "*"}}))


def _forget_ledger(path: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        with contextlib.suppress(OSError):
            path.with_name(path.name + suffix).unlink()


def _migrate(args) -> int:
    from storage import Storage
    root = _home()
    path = ledger_path(root)
    if path.exists():
        raise RuleError("12.3 migrate", f"a ledger already exists at {path}: migrate runs once, before any ledger. "
                        "A row shared since can be shared again with `share`, which links it, or added with "
                        "`collection add`")
    login = _owner_login()
    owner, home = "person:" + login, home_of("person:" + login)
    house = root / PUBLISHED_HOUSE
    if not house.is_file():
        raise RuleError("12.3 migrate", f"there is no published house at {house}; shares are made into it")
    notes: list[str] = []
    receivers = _migrate_receivers(root, notes)
    groups = _migrate_groups(root / ".engram" / "groups.toml")
    migrated, unmatched = _migrate_rows(root, house, groups)
    counts: dict[str, int] = {}
    for item in migrated:
        counts[item["audience"]] = counts.get(item["audience"], 0) + 1
    lacking = [str(p) for p in houses(root) if p.resolve() != house.resolve() and _lacks_029(p)]
    at = _now()
    plan_path = root / ".engram" / f"permissions-migrate-{datetime.fromtimestamp(at, timezone.utc):%Y%m%dT%H%M%SZ}.json"
    plan_path.write_text(json.dumps({"at": at, "owner": owner, "rows": migrated, "unmatched": unmatched},
                                    indent=1, sort_keys=True), encoding="utf-8")
    shown = unmatched[:REPORT_ROWS]
    lines = [f"change: create the ledger {path} owned by {owner}, channel migration",
             f"  agents in {home}, acting for {owner}: {', '.join(receivers) or '(none named by a policy)'}",
             f"  groups from groups.toml: {', '.join(sorted(groups)) or '(none)'}",
             "  shares migrated, by audience:"]
    lines += [f"    {a}: {n}" for a, n in sorted(counts.items())] or ["    (none)"]
    lines.append(f"  unmatched, left unmigrated: {len(unmatched)}")
    lines += [f"    unmatched {_clean(u['memory_id'])}: {u['why']} (to {_clean(u['audience'])}, source "
              f"{_clean(u['source_instance'])} {_clean(u['layer'])} {_clean(u['source_id'])})" for u in shown]
    if len(unmatched) > len(shown):
        lines.append(f"    ... and {len(unmatched) - len(shown)} more (all are in the file below)")
    lines += [f"  houses without migration 029 (not migrated; an engram server opens each once): {h}"
              for h in lacking]
    lines += notes
    lines.append(f"  every row it will migrate: {plan_path}")
    words = (f"Migrate today's shares into a new permissions ledger owned by {owner}: {len(migrated)} shares become "
             f"members of {len(counts)} collections, each opened to its audience by one allow inside {home}; "
             f"{len(unmatched)} shares cannot be matched to their source and stay as they are.")
    try:
        said_yes = confirm(words, "\n".join(lines))
    except BaseException:
        plan_path.unlink(missing_ok=True)
        raise
    if not said_yes:
        plan_path.unlink(missing_ok=True)
        print("That was not the code. Nothing was written.", file=sys.stderr)
        return 3
    published = Storage(str(house))                 # the full open: migrations up to 029 run on it (R27)
    try:
        ids: dict[str, str] = {}
        for p in houses(root):
            iid = _house_id(p)
            if iid:
                ids.setdefault(iid, "default" if p.parent.name == ".engram" else p.parent.name)
        led = None
        try:
            led = Ledger.create(root, login, now=at, channel="migration")

            def do(kind, **a):
                out = led.perform(Act(kind, a), actor=owner, channel="migration", now=at)
                if out.status != "done":
                    raise RuleError("12.3 migrate", f"{kind} was not done: it is a {out.status}")
                return out
            for receiver in receivers:
                do("register-agent", agent=f"agent:{receiver}", acts_for=home)
                do("put-agent", agent=f"agent:{receiver}", place=home)
            for iid, name in sorted(ids.items(), key=lambda kv: kv[1]):
                do("register-store", instance_id=iid, name=name, owner=owner, place=home, imprint_of=None)
            for g, members in sorted(groups.items()):
                do("group", group=f"group:{g}", members=[f"agent:{m}" for m in members if m in receivers])
            record_of: dict[str, str] = {}
            for collection in sorted({m["collection"] for m in migrated}):
                cid = f"collection:{login}/{collection}"
                mine = {m["object"]: m for m in migrated if m["collection"] == collection}
                do("make-collection", collection=cid)
                refs = sorted(mine)
                for i in range(0, len(refs), COLLECT_CHUNK):
                    chunk = refs[i:i + COLLECT_CHUNK]
                    do("collect", collection=cid, objects=chunk,
                       lanes={r: {"lane": mine[r]["lane"], "created_at": mine[r]["created_at"]} for r in chunk})
                audience = home if collection == "legacy-commons" else "group:" + collection[len("legacy-group-"):]
                record_of[collection] = do("allow", layer=home, selector=_legacy_selector(login, audience, collection),
                                           valid_from=at, valid_until=None, reason="legacy share").ref
        except BaseException:
            if led is not None:
                led.close()
            _forget_ledger(path)
            raise
        led.close()
        try:
            with published.transaction():
                for m in migrated:
                    published.conn.execute(
                        "UPDATE shared_memories SET source_instance_id = ?, record_id = ? WHERE share_id = ?",
                        (m["source_instance_id"], record_of[m["collection"]], m["share_id"]))
        except sqlite3.Error as e:
            remove = "rm -f " + " ".join(shlex.quote(str(path.with_name(path.name + x)))
                                         for x in ("", "-journal", "-wal", "-shm"))
            raise RuleError("12.3 migrate", f"the ledger was made, but the published house could not be filled "
                            f"({e}). The gate is off and nothing is widened. To run migrate again, remove the "
                            f"ledger, fix the cause, and rerun `engram-permissions migrate`; to keep the ledger "
                            f"instead, share each row again with `share`.\n{remove}") from e
    finally:
        published.close()
    print(f"Migrated {len(migrated)} shares into {len(record_of)} collections, each with one allow. The ledger is "
          f"at {path}; the gate is off. {len(unmatched)} unmatched shares were left as they were.")
    print("Next: `engram-permissions gate shadow`, then `engram-permissions report shadow`.")
    return 0


# ---------------------------------------------------------------- report shadow (P 12.3, 12.1)

def _legacy_agreed(row) -> bool:
    """A shadow receipt on which the two paths differ. A ledger refusal the legacy path did not make: no cited legacy
    layer denies it, the refusal is not the legacy path's own, and for a delivery the publisher did deliver (under
    shadow the digest is kept only then). Or the converse, a delivery the ledger allowed that the publisher's audience
    check refused (recorded as LEGACY_DENY by the publisher)."""
    try:
        cited = json.loads(row["cited"])
        refusal = json.loads(row["refusal"]) if row["refusal"] else None
    except (TypeError, ValueError):
        return False
    if row["allowed"]:
        return bool(refusal) and refusal.get("code") == "LEGACY_DENY" and refusal.get("layer") == "publisher"
    if refusal and refusal.get("code") == "LEGACY_DENY":
        return False
    if row["action"] == "inject_context" and row["content_digest"] is None:
        return False                    # the publisher's audience check delivered nothing: both paths refused
    return not any(isinstance(c, dict) and c.get("kind") == "legacy" and c.get("verdict") != "allow" for c in cited)


def _shadow_disagreements() -> tuple[int, list[dict]]:
    from permission_uses import Uses, uses_path
    if not uses_path(_home()).is_file():
        return 0, []
    uses = Uses.open_read_only(_home())
    count, rows = 0, []
    try:
        for r in uses.conn.execute("SELECT * FROM uses WHERE shadow = 1 ORDER BY seq"):
            if _legacy_agreed(r):
                count += 1
                if len(rows) < REPORT_ROWS:
                    refusal = json.loads(r["refusal"]) if r["refusal"] else None
                    rows.append({"id": r["id"], "at": r["at"], "agent": r["agent"], "place": r["place"],
                                 "action": r["action"], "purpose": r["purpose"], "object": r["object"],
                                 "copy": r["copy"], "refusal": refusal})
    finally:
        uses.close()
    return count, rows


def _uncovered_placements(state, now: int) -> tuple[int, list[dict]]:
    """The placements of the published house that `share` under `enforce` would have answered `needs-allow`."""
    from sharing import AUDIENCE_COMMONS, GROUP_RE
    from storage import Storage
    house = _home() / PUBLISHED_HOUSE
    if not house.is_file():
        return 0, []
    owner = state.meta["owner"]
    store = Storage.open_read_only(house)
    count, rows = 0, []
    try:
        cursor = store.conn.execute(
            "SELECT share_id, layer, audience, source_id, source_instance_id, record_id FROM shared_memories "
            "ORDER BY shared_at, share_id")
        for r in cursor:
            if r["source_instance_id"] and r["source_id"]:
                obj = f"mem:{r['source_instance_id']}/{r['layer']}/{r['source_id']}"
                if r["record_id"] and placement_still_counts(state, r["record_id"], owner=owner, obj=obj, at=now):
                    continue
                audience = (home_of(owner) if r["audience"] == AUDIENCE_COMMONS else r["audience"]
                            if GROUP_RE.fullmatch(r["audience"]) or r["audience"].startswith("place:") else None)
                if audience is None:
                    continue                   # `share` would answer an unknown audience with an error, not needs-allow
                try:
                    if share_cover(state, owner=owner, obj=obj, audience=audience, at=now) is not None:
                        continue
                except RuleError:
                    pass
                why = "no record" if not r["record_id"] else "its record no longer counts"
            else:
                obj, why = None, "no object"
            count += 1
            if len(rows) < REPORT_ROWS:
                rows.append({"share_id": r["share_id"], "object": obj, "audience": r["audience"],
                             "record_id": r["record_id"], "why": why})
    except sqlite3.OperationalError as e:
        raise RuleError("12.3 report shadow", f"{house} cannot be read as a published house ({e}); an engram "
                                              "server opens it once to run migration 029") from e
    finally:
        store.close()
    return count, rows


def _report_shadow(a) -> int:
    with _ledger(read_only=True) as led:
        state = led.state()
    n_dis, disagreements = _shadow_disagreements()
    n_need, needing = _uncovered_placements(state, _now())
    if a.json:
        print(json.dumps({"disagreements": disagreements, "disagreement_count": n_dis,
                          "would_need_a_proposal": needing, "would_need_count": n_need}, sort_keys=True))
        return 0
    print(f"{n_dis} shadow uses the legacy path allowed and the ledger refused.")
    for r in disagreements:
        ref = r["refusal"] or {}
        print(f"  {r['id']}  {_stamp(r['at'])}  {_clean(r['agent'])} {r['action']} {_clean(r['object'])}  "
              f"{_clean(ref.get('code'))} at {_clean(ref.get('layer'))}")
    print(f"{n_need} shares that would have needed a proposal under `enforce`.")
    for s in needing:
        print(f"  {s['share_id']}  {_clean(s['object'] or '(no object)')}  to {_clean(s['audience'])}  ({s['why']})")
    for n, rows, what in ((n_dis, disagreements, "disagreements"), (n_need, needing, "shares")):
        if n > len(rows):
            print(f"... and {n - len(rows)} more {what} (the first {REPORT_ROWS} are listed).")
    return 0


# ---------------------------------------------------------------- explain (P 6.4, 6.5, 14)

def _object_lines(path: str) -> tuple[str, ...]:
    """One ref per line, blank lines skipped, at most MAX_OBJECT_LINES read (a larger file is then refused by the
    bound) and no line longer than _OBJECT_LINE_BYTES."""
    out: list[str] = []
    try:
        with open(path, "rb") as f:
            while len(out) < MAX_OBJECT_LINES:
                raw = f.readline(_OBJECT_LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > _OBJECT_LINE_BYTES:
                    raise RuleError("6.4 bulk uses", f"{path} has a line longer than {_OBJECT_LINE_BYTES} bytes")
                text = raw.decode("utf-8", "replace").strip()
                if text:
                    out.append(text)
    except OSError as e:
        raise RuleError("6.4 bulk uses", f"{path} cannot be read ({e.strerror or e})") from e
    return tuple(out)


def _names_file(path: str | None):
    if path is None:
        return None
    try:
        data = json.loads(_read_text(path, "6.4 names", "names"))
    except ValueError as e:
        raise RuleError("6.4 names", f"{path} is not JSON ({e})") from e
    if isinstance(data, list) and all(isinstance(x, str) for x in data):
        return data
    if isinstance(data, dict) and all(isinstance(v, list) and all(isinstance(x, str) for x in v)
                                      for v in data.values()):
        return data
    raise RuleError("6.4 names", f"{path} must be a list of memory refs, or an object of road or trail refs to lists")


def _explain(a) -> int:
    names = _names_file(a.names)
    with _ledger(read_only=True) as led:
        state = led.state()
    agent = _qualify("agent", a.agent)
    place = _qualify("place", a.place)
    at = _now() if a.at is None else a.at
    if a.object:
        if isinstance(names, dict):
            listed = tuple(names.get(a.object, ()))
        else:
            listed = tuple(names or ())
        use = Use(agent, place, a.object, a.copy, a.action, a.purpose, at, names=listed)
        decision = decide(state, use)
        subject = a.object
    else:
        if names is not None and not isinstance(names, dict):
            raise RuleError("6.4 names", "for --objects, --names is an object of road or trail refs to lists")
        table = names or {}
        bulk = BulkUse(agent, place, _object_lines(a.objects), a.copy, a.action, a.purpose, at,
                       named=not a.counted, names=lambda o: table.get(o, ()))
        decision = decide_bulk(state, bulk)
        subject = f"{len(bulk.objects)} objects"
    if a.json:
        print(json.dumps(decision.to_json(), sort_keys=True))
        return 0
    print(f"{'allowed' if decision.allowed else 'refused'}: {agent} may {'' if decision.allowed else 'not '}"
          f"{a.action} {_clean(subject)} at {place} for {a.purpose} on {_stamp(at)} "
          f"(ledger seq {decision.ledger_seq}).")
    if decision.refusal is not None:
        ref = decision.refusal
        print(f"  refused: {ref.code}" + (f" at {_clean(ref.layer)}" if ref.layer else "")
              + (f" for {ref.action}" if ref.action else ""))
    print("  layers cited:")
    for c in decision.cited:
        recs = ", ".join(c.records) or "no record"
        print(f"    {_clean(c.layer)} ({c.kind}) {c.action}: {c.verdict}, {recs}")
    if decision.allowed:
        print(f"  until: {_stamp(decision.until)}; horizon: {_stamp(decision.horizon)}")
    return 0


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

    leaf(top, "migrate", _migrate, "turn today's shares into collections and allows (once, before any ledger)")
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
    p = leaf(places, "show", _place_show, "print the place's published rules (no yes needed)")
    p.add_argument("place")
    p.add_argument("--json", action="store_true")

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
    for effect in ("allow", "deny"):
        p = leaf(top, effect, _record_write(effect), f"write a {effect}")
        p.add_argument("--layer", required=True)
        p.add_argument("--selector", required=True, help="JSON, or @file")
        p.add_argument("--from", dest="valid_from", type=_when, help="default: now")
        p.add_argument("--until", type=_when, help="default: no end")
        p.add_argument("--reason", default="")
    p = leaf(top, "revoke", _record_edit("revoke"), "withdraw a record")
    p.add_argument("id")
    p.add_argument("--reason", default="")
    p = leaf(top, "shorten", _record_edit("shorten"), "end a record sooner")
    p.add_argument("id")
    p.add_argument("--until", type=_when, required=True)
    p.add_argument("--reason", default="")
    p = leaf(top, "narrow", _record_edit("narrow"), "replace a record's selector with a narrower one")
    p.add_argument("id")
    p.add_argument("--selector", required=True, help="JSON, or @file")
    p.add_argument("--reason", default="")
    p = leaf(top, "grant", _grant, "give an agent a grant")
    p.add_argument("--to", required=True)
    p.add_argument("--ops", required=True, action="append", help="comma-separated")
    p.add_argument("--envelope", required=True, help="JSON, or @file")
    p.add_argument("--max-days", type=int, required=True)
    p.add_argument("--depth", type=int, default=0)
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--parent")
    p.add_argument("--layer", help="default: the owner's home, or the parent's layer")
    p = leaf(top, "revoke-grant", _revoke_grant, "revoke a grant")
    p.add_argument("id")
    p.add_argument("--reason", default="")
    leaf(top, "sign", _on_proposal("sign"), "say yes to an agent's proposal").add_argument("id")
    leaf(top, "decline", _on_proposal("decline"), "say no to a proposal").add_argument("id")
    leaf(top, "proposals", _proposals, "list the open proposals (no yes needed)")
    p = leaf(top, "gate", _gate, "move the gate: off, shadow or enforce")
    p.add_argument("mode", choices=["off", "shadow", "enforce"])
    leaf(top, "rebuild", _rebuild, "replay the log into a fresh ledger (no yes needed)").add_argument(
        "--out", required=True, help="a directory that holds no ledger yet; the file lands in .engram/ under it")
    p = leaf(top, "uses", _uses, "list the uses (no yes needed)")
    p.add_argument("--since", type=_when)
    p.add_argument("--until", type=_when)
    p.add_argument("--place")
    p.add_argument("--action")
    p.add_argument("--purpose")
    p.add_argument("--collection")
    p.add_argument("--object")
    p.add_argument("--refused", action="store_true")
    p.add_argument("--json", action="store_true")
    leaf(top, "check", _check, "check the joint places for disagreement (no yes needed)").add_argument(
        "place", nargs="?")
    leaf(top, "sweep", _sweep, "make the published house follow the ledger (no yes needed)")
    p = leaf(top, "explain", _explain, "decide a described use, single or bulk, and say why (no yes needed)")
    p.add_argument("--agent", required=True)
    p.add_argument("--place", required=True)
    what = p.add_mutually_exclusive_group(required=True)
    what.add_argument("--object", help="one object")
    what.add_argument("--objects", help="a file of refs, one per line: a bulk use")
    p.add_argument("--counted", action="store_true", help="a bulk use whose objects are derived and counted")
    p.add_argument("--copy", required=True)
    p.add_argument("--action", required=True)
    p.add_argument("--purpose", required=True)
    p.add_argument("--at", type=_when, help="default: now")
    p.add_argument("--names", help="JSON: the memories a road or trail names (a list, or an object by ref)")
    p.add_argument("--json", action="store_true")
    report = group("report", "reports")
    p = leaf(report, "shadow", _report_shadow, "the disagreements and the shares that would need a proposal")
    p.add_argument("--json", action="store_true")
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
