"""Permissions by place: the pure model (names, ids, selectors).

Reads no file, opens no database, reads no clock, draws no randomness.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable, NamedTuple

from lighthouse_protocol import canonical_json

MAX_RECORDS_PER_LAYER = 256
MAX_AUDIENCE = 32
MAX_LIST = 64
MAX_MEMORIES = 512
MAX_PURPOSES = 16
MAX_SUBJECTS = 8
MAX_COLLECTION = 100_000
MAX_PLACES = 1024
MAX_PARENTS = 4
MAX_SEGMENTS = 8
MAX_PLACE_CHARS = 255
MAX_ANCESTORS = 16
MAX_LAYERS = 43
MAX_ANSWER_NAMES = 32
MAX_BULK_NAMED = 512
MAX_BULK_DERIVED = 100_000
MAX_BULK_MEMORIES = 100_000
MAX_COPY_CHAIN = 4
OUTSIDE_HOME_DAYS = 366
MAX_GRANT_LINKS = 3
MAX_GRANT_DEPTH = 2
MAX_GRANT_HOURS = 720
MAX_REPLACES = 16
PROPOSAL_DAYS = 7
BOX_CAP = 4096
JOINTS_PER_CHANGE = 64
SWEEP_PER_PASS = 256
CACHE_ENTRIES = 64
MAX_PLACEMENTS = 20_000
REBUILD_BUDGET_S = 2
BULK_BUDGET_S = 40
GUARD_RECEIPTS = 200
GUARD_SECONDS = 24 * 3600
GATE_HOUSES = 64
RETENTION_DAYS = 400
USE_LIST_ROWS = 200
ANNOTATION_CHARS = 240
ANNOTATION_NAME_CHARS = 32
CODE_CHARS = 6
SHORT_HEX = 4
RECEIPT_SHORT_HEX = 8
REASON_CHARS = 200

STAR = "*"
ACTIONS = ("recall", "read", "inject_context", "route", "imprint")
KINDS = ("memory", "road", "trail")
LAYERS = ("episode", "semantic")
LANES = ("personal", "work")
RESERVED_GROUP = "group:outside-home"


class RuleError(ValueError):
    def __init__(self, rule: str, message: str):
        super().__init__(f"{rule}: {message}")
        self.rule = rule
        self.message = message


_A = re.ASCII
_PERSON = re.compile(r"[a-z][a-z0-9-]{0,62}\Z", _A)
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z", _A)
_SEGMENT = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z", _A)
_GROUP = re.compile(r"[a-z][a-z0-9-]{0,63}\Z", _A)
_COLL_NAME = re.compile(r"[a-z][a-z0-9-]{0,79}\Z", _A)
_HEX = {p: re.compile(re.escape(p) + r"-[0-9a-f]{32}\Z", _A) for p in "rgpu"}
_HEX_PREFIX = re.compile(r"([rgpu])-([0-9a-f]*)\Z", _A)
_KIND_PREFIX = {"person": "person:", "agent": "agent:", "place": "place:", "group": "group:",
                "collection": "collection:"}
_HEX_KIND = {"record": "r", "grant": "g", "proposal": "p", "use": "u"}


def _bad(rule: str, what: str, value) -> RuleError:
    text = value if isinstance(value, str) else repr(value)
    if len(text) > 80:
        text = text[:80] + "..."
    return RuleError(rule, f"{what}: {text!r}")


def _strip(kind: str, value, rule: str, prefix: str) -> str:
    if not isinstance(value, str) or not value.startswith(prefix):
        raise _bad(rule, f"not a {kind} id", value)
    return value[len(prefix):]


def check_id(kind: str, value: str) -> str:
    if kind in _HEX_KIND:
        if not isinstance(value, str) or not _HEX[_HEX_KIND[kind]].fullmatch(value):
            raise _bad("4.1 id grammar", f"not a {kind} id ({_HEX_KIND[kind]}- and 32 lowercase hex)", value)
        return value
    if kind not in _KIND_PREFIX:
        raise RuleError("4.1 id grammar", f"unknown id kind {kind!r}")
    rest = _strip(kind, value, f"4.1 {kind} grammar", _KIND_PREFIX[kind])
    if kind == "person":
        ok = _PERSON.fullmatch(rest)
    elif kind == "agent":
        ok = _NAME.fullmatch(rest)
    elif kind == "group":
        if value == RESERVED_GROUP:
            raise RuleError("5.4 outside-home lifetime", f"{RESERVED_GROUP} is reserved")
        ok = _GROUP.fullmatch(rest)
    elif kind == "collection":
        handle, sep, name = rest.partition("/")
        ok = sep and _PERSON.fullmatch(handle) and _COLL_NAME.fullmatch(name)
    else:
        ok = _check_place(value, rest)
    if not ok:
        raise _bad(f"4.1 {kind} grammar", f"not a valid {kind} id", value)
    return value


def _check_place(value: str, rest: str) -> bool:
    if len(value) > MAX_PLACE_CHARS:
        raise _bad("4.1 place grammar", f"over {MAX_PLACE_CHARS} characters", value)
    segs = rest.split("/")
    if len(segs) > MAX_SEGMENTS:
        raise _bad("4.1 place grammar", f"over {MAX_SEGMENTS} segments", value)
    if not all(_SEGMENT.fullmatch(s) for s in segs):
        return False
    if segs[0] == "home":
        return len(segs) == 2 and bool(_PERSON.fullmatch(segs[1]))
    return True


def home_of(person: str) -> str:
    check_id("person", person)
    return "place:home/" + person[len("person:"):]


def person_of_home(place: str) -> str | None:
    if not isinstance(place, str) or not place.startswith("place:home/"):
        return None
    try:
        check_id("place", place)
    except RuleError:
        return None
    return "person:" + place[len("place:home/"):]


class ObjectRef(NamedTuple):
    kind: str
    instance_id: str
    layer: str | None
    local_id: str


class CopyRef(NamedTuple):
    kind: str
    instance_id: str
    station: str | None


def parse_object_ref(ref: str) -> ObjectRef:
    rule = "4.1 object ref"
    if not isinstance(ref, str):
        raise _bad(rule, "not a string", ref)
    head, _, rest = ref.partition(":")
    parts = rest.split("/")
    if head == "mem" and len(parts) == 3:
        inst, layer, mid = parts
        if _NAME.fullmatch(inst) and layer in LAYERS and _NAME.fullmatch(mid):
            return ObjectRef("memory", inst, layer, mid)
    elif head in ("road", "trail") and len(parts) == 2:
        if all(_NAME.fullmatch(p) for p in parts):
            return ObjectRef(head, parts[0], None, parts[1])
    raise _bad(rule, "not a mem:, road: or trail: ref", ref)


def parse_copy_ref(ref: str) -> CopyRef:
    rule = "4.1 copy ref"
    if not isinstance(ref, str):
        raise _bad(rule, "not a string", ref)
    head, _, rest = ref.partition(":")
    if head == "store" and _NAME.fullmatch(rest):
        return CopyRef("store", rest, None)
    if head == "imprint":
        parts = rest.split("/")
        if len(parts) == 2 and all(_NAME.fullmatch(p) for p in parts):
            return CopyRef("imprint", parts[1], parts[0])
    raise _bad(rule, "not a store: or imprint: ref", ref)


# ---------------------------------------------------------------- selectors

_LIST_KEYS = ("audience", "requesters", "objects", "actions", "purposes")
_OBJ_KEYS = ("kinds", "stores", "layers", "lanes", "collections", "memories")


@dataclass(frozen=True)
class Selector:
    audience: tuple
    requesters: tuple | str
    kinds: tuple | str
    stores: tuple | str
    layers: tuple | str
    lanes: tuple | str
    collections: tuple | str
    memories: tuple | str
    actions: tuple | str
    purposes: tuple | str


def _units(s: str) -> bytes:
    return s.encode("utf-16-be")


def _audience_ok(v: str) -> bool:
    if v in ("self", "commons"):
        return True
    check = ("place" if v.startswith("place:") else "group" if v.startswith("group:") else None)
    if check is None:
        return False
    check_id(check, v)
    return True


def _one(field: str, value, limit: int, check, star_ok: bool = True):
    rule = "5.2 selector"
    if isinstance(value, str):
        if value == STAR and star_ok:
            return STAR
        raise RuleError(rule, f"{field} must be a list" + (" (never \"*\")" if not star_ok else " or \"*\""))
    if not isinstance(value, list) or not 1 <= len(value) <= limit:
        raise RuleError(rule, f"{field} must hold 1 to {limit:,} values")
    for v in value:
        if not isinstance(v, str):
            raise _bad(rule, f"{field} value is not a string", v)
        try:
            ok = check(v)
        except RuleError as exc:
            raise RuleError(rule, f"{field} value {v!r} refused: {exc}") from None
        if not ok:
            raise _bad(rule, f"{field} value outside its grammar", v)
        if v == RESERVED_GROUP:
            raise RuleError("5.4 outside-home lifetime", f"{RESERVED_GROUP} may not appear in a selector")
    if len(set(value)) != len(value):
        raise RuleError(rule, f"{field} has duplicate values")
    return tuple(sorted(value, key=_units))


def _is_ref(v: str) -> bool:
    return parse_object_ref(v).kind == "memory"


def parse_selector(doc) -> Selector:
    rule = "5.2 selector"
    if isinstance(doc, (str, bytes)):
        try:
            doc = json.loads(doc)
        except ValueError:
            raise RuleError(rule, "selector is not valid JSON") from None
    if not isinstance(doc, dict) or set(doc) != set(_LIST_KEYS):
        raise RuleError(rule, f"selector keys must be exactly {', '.join(_LIST_KEYS)}")
    obj = doc["objects"]
    if not isinstance(obj, dict) or set(obj) != set(_OBJ_KEYS):
        raise RuleError(rule, f"objects keys must be exactly {', '.join(_OBJ_KEYS)}")
    sel = Selector(
        audience=_one("audience", doc["audience"], MAX_AUDIENCE, _audience_ok, star_ok=False),
        requesters=_one("requesters", doc["requesters"], MAX_LIST, lambda v: bool(check_id("agent", v))),
        kinds=_one("kinds", obj["kinds"], MAX_LIST, lambda v: v in KINDS),
        stores=_one("stores", obj["stores"], MAX_LIST, lambda v: bool(_NAME.fullmatch(v))),
        layers=_one("layers", obj["layers"], MAX_LIST, lambda v: v in LAYERS),
        lanes=_one("lanes", obj["lanes"], MAX_LIST, lambda v: v in LANES),
        collections=_one("collections", obj["collections"], MAX_LIST,
                         lambda v: bool(check_id("collection", v))),
        memories=_one("memories", obj["memories"], MAX_MEMORIES, _is_ref),
        actions=_one("actions", doc["actions"], MAX_LIST, lambda v: v in ACTIONS),
        purposes=_one("purposes", doc["purposes"], MAX_PURPOSES, lambda v: bool(_GROUP.fullmatch(v))),
    )
    if sel.kinds == STAR or any(k in ("road", "trail") for k in sel.kinds):
        for name in ("layers", "lanes", "collections", "memories"):
            if getattr(sel, name) != STAR:
                raise RuleError(rule, f"for a road or trail (or kinds \"*\"), {name} must be \"*\"")
    return sel


def selector_json(sel: Selector) -> str:
    def out(v):
        return v if v == STAR else list(v)
    return canonical_json({
        "audience": out(sel.audience), "requesters": out(sel.requesters),
        "objects": {k: out(getattr(sel, k)) for k in _OBJ_KEYS},
        "actions": out(sel.actions), "purposes": out(sel.purposes)})


# ---------------------------------------------------------------- short ids

def resolve_prefix(ids: Iterable[str], given: str) -> str:
    rule = "4.1 short ids"
    ids = list(ids)
    if given in ids:
        return given
    m = _HEX_PREFIX.fullmatch(given) if isinstance(given, str) else None
    if not m:
        raise _bad(rule, "not an id or id prefix", given)
    matches = sorted(i for i in ids if i.startswith(given))
    if len(matches) > 1:
        raise RuleError(rule, f"prefix {given} matches {len(matches)} ids: " + ", ".join(matches))
    if len(m.group(2)) < SHORT_HEX:
        raise RuleError(rule, f"prefix {given} has fewer than {SHORT_HEX} hex")
    if not matches:
        raise RuleError(rule, f"prefix {given} matches no id")
    return matches[0]


def short_id(full: str) -> str:
    return "#" + full[2:2 + SHORT_HEX]


def receipt_short(full: str) -> str:
    return "#" + full[2:2 + RECEIPT_SHORT_HEX]
