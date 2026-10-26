"""Permissions by place: the pure model (names, ids, selectors).

Reads no file, opens no database, reads no clock, draws no randomness.
"""
from __future__ import annotations

import json
import re
from collections import namedtuple
from dataclasses import dataclass, field
from typing import Iterable, Mapping, NamedTuple, Sequence

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
GRANT_OPS = ("share", "deny", "withdraw", "shorten", "narrow", "collect", "uncollect")
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


# ---------------------------------------------------------------- the State (P 5.5)

_COLUMNS = {
    "persons": ("id", "home", "is_admin", "created_seq", "retired_seq"),
    "places": ("id", "is_root", "created_seq", "retired_seq", "pseudonym_salt"),
    "place_parents": ("place", "parent", "added_seq"),
    "place_stewards": ("place", "person", "added_seq", "removed_seq"),
    "agents": ("id", "acts_for", "created_seq", "retired_seq"),
    "agent_places": ("agent", "place", "added_seq", "removed_seq"),
    "stores": ("instance_id", "name", "owner", "place", "imprint_of", "created_seq"),
    "groups": ("id", "owner", "created_seq"),
    "group_members": ("group_id", "agent", "added_seq", "removed_seq"),
    "collections": ("id", "owner", "created_seq"),
    "collection_members": ("collection", "object", "backing", "added_seq", "added_by", "removed_seq",
                           "removed_by"),
    "subjects": ("object", "subject", "added_seq", "added_by", "self_claimed", "removed_seq", "removed_by"),
    "copies": ("object", "source", "added_seq"),
    "lane_notes": ("object", "lane", "at", "seq"),
    "records": ("id", "layer", "effect", "selector", "valid_from", "valid_until", "anchor", "backing",
                "set_by", "channel", "under_grant", "proposal_id", "replaces", "reason", "created",
                "created_seq", "revoked", "revoked_by", "revoke_reason", "revoked_seq"),
    "permission_grants": ("id", "issuer", "grantee", "layer", "parent_id", "ops", "envelope", "max_days",
                          "depth", "expires", "created", "created_seq", "revoked", "revoked_by",
                          "revoke_reason", "revoked_seq"),
    "proposals": ("id", "by_agent", "for_person", "kind", "body", "created", "expires", "status",
                  "decided_seq"),
}
_NULLABLE = frozenset({
    "retired_seq", "removed_seq", "removed_by", "imprint_of", "valid_until", "under_grant", "proposal_id",
    "replaces", "revoked", "revoked_by", "revoke_reason", "revoked_seq", "parent_id", "decided_seq"})
_ROW = {t: namedtuple(n, c) for t, n, c in [
    ("persons", "Person", _COLUMNS["persons"]), ("places", "Place", _COLUMNS["places"]),
    ("place_parents", "PlaceParent", _COLUMNS["place_parents"]),
    ("place_stewards", "PlaceSteward", _COLUMNS["place_stewards"]),
    ("agents", "Agent", _COLUMNS["agents"]), ("agent_places", "AgentPlace", _COLUMNS["agent_places"]),
    ("stores", "Store", _COLUMNS["stores"]), ("groups", "Group", _COLUMNS["groups"]),
    ("group_members", "GroupMember", _COLUMNS["group_members"]),
    ("collections", "Collection", _COLUMNS["collections"]),
    ("collection_members", "CollectionMember", _COLUMNS["collection_members"]),
    ("subjects", "SubjectRow", _COLUMNS["subjects"]), ("copies", "CopyRow", _COLUMNS["copies"]),
    ("lane_notes", "LaneNote", _COLUMNS["lane_notes"]),
    ("permission_grants", "GrantRow", _COLUMNS["permission_grants"]),
    ("proposals", "Proposal", _COLUMNS["proposals"])]}
# a record carries its selector parsed (PF9)
Record = namedtuple("Record", _COLUMNS["records"])
_ROW["records"] = Record

# keyed tables: (table, primary key, state attribute)
_KEYED = (("persons", "id", "persons"), ("places", "id", "places"), ("agents", "id", "agents"),
          ("stores", "instance_id", "stores"), ("groups", "id", "groups"),
          ("collections", "id", "collections"), ("records", "id", "records"),
          ("permission_grants", "id", "grants"), ("proposals", "id", "proposals"))
# multi-row tables, grouped by their first key
_MULTI = ("place_parents", "place_stewards", "agent_places", "group_members", "collection_members",
          "subjects", "lane_notes")
_ADDED = {"place_parents": "added_seq", "place_stewards": "added_seq", "agent_places": "added_seq",
          "group_members": "added_seq", "collection_members": "added_seq", "subjects": "added_seq",
          "copies": "added_seq", "lane_notes": "seq", "persons": "created_seq", "places": "created_seq",
          "agents": "created_seq", "stores": "created_seq", "groups": "created_seq",
          "collections": "created_seq", "records": "created_seq", "permission_grants": "created_seq"}
# (seq column, columns that go back to null while the seq is in the future)
_UNDONE = {
    "persons": ("retired_seq", ("retired_seq",)), "places": ("retired_seq", ("retired_seq",)),
    "agents": ("retired_seq", ("retired_seq",)),
    "place_stewards": ("removed_seq", ("removed_seq",)), "agent_places": ("removed_seq", ("removed_seq",)),
    "group_members": ("removed_seq", ("removed_seq",)),
    "collection_members": ("removed_seq", ("removed_seq", "removed_by")),
    "subjects": ("removed_seq", ("removed_seq", "removed_by")),
    "records": ("revoked_seq", ("revoked", "revoked_by", "revoke_reason", "revoked_seq")),
    "permission_grants": ("revoked_seq", ("revoked", "revoked_by", "revoke_reason", "revoked_seq")),
}


def _row(table: str, d) -> tuple:
    cls = _ROW[table]
    vals = {}
    for c in _COLUMNS[table]:
        if c in d:
            vals[c] = d[c]
        elif c in _NULLABLE:
            vals[c] = None
        else:
            raise RuleError("5.5 storage", f"{table} row has no {c}")
    if table == "places":
        salt = vals["pseudonym_salt"]
        if isinstance(salt, str):
            salt = bytes.fromhex(salt)
        vals["pseudonym_salt"] = bytes(salt)
    if table == "records" and not isinstance(vals["selector"], Selector):
        vals["selector"] = parse_selector(vals["selector"])
    return cls(**vals)


@dataclass(frozen=True)
class State:
    seq: int
    seq_at: Mapping[int, int]
    meta: Mapping[str, str]
    names: Mapping[str, str]
    persons: Mapping[str, tuple]
    places: Mapping[str, tuple]
    agents: Mapping[str, tuple]
    stores: Mapping[str, tuple]
    groups: Mapping[str, tuple]
    collections: Mapping[str, tuple]
    records: Mapping[str, Record]
    grants: Mapping[str, tuple]
    proposals: Mapping[str, tuple]
    copies: Mapping[str, str]
    place_parents: Mapping[str, tuple]
    place_stewards: Mapping[str, tuple]
    agent_places: Mapping[str, tuple]
    group_members: Mapping[str, tuple]
    collection_members: Mapping[str, tuple]
    member_of: Mapping[str, tuple]       # collection_members by object
    subjects: Mapping[str, tuple]
    lane_notes: Mapping[str, tuple]      # ordered by (at, seq)
    _cache: dict = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_tables(cls, tables: Mapping[str, Sequence], *, seq: int, seq_at: Mapping[int, int],
                    meta: Mapping[str, str], names: Mapping[str, str] | None = None) -> "State":
        unknown = set(tables) - set(_COLUMNS)
        if unknown:
            raise RuleError("5.5 storage", f"unknown tables: {', '.join(sorted(unknown))}")
        rows: dict[str, list] = {}
        for table in _COLUMNS:
            out = []
            for d in tables.get(table, ()):
                r = _row(table, d)
                added = _ADDED.get(table)
                if added and getattr(r, added) > seq:
                    continue
                if table in _UNDONE:
                    col, clear = _UNDONE[table]
                    v = getattr(r, col)
                    if v is not None and v > seq:
                        r = r._replace(**{c: None for c in clear})
                if table == "proposals" and r.decided_seq is not None and r.decided_seq > seq:
                    r = r._replace(status="pending", decided_seq=None)
                out.append(r)
            rows[table] = out
        kw = {}
        for table, key, attr in _KEYED:
            kw[attr] = {getattr(r, key): r for r in rows[table]}
        kw["copies"] = {r.object: r.source for r in rows["copies"]}
        for table in _MULTI:
            first = _COLUMNS[table][0]
            grouped: dict[str, list] = {}
            items = rows[table]
            if table == "lane_notes":
                items = sorted(items, key=lambda r: (r.at, r.seq))
            for r in items:
                grouped.setdefault(getattr(r, first), []).append(r)
            kw[table] = {k: tuple(v) for k, v in grouped.items()}
        by_obj: dict[str, list] = {}
        for r in rows["collection_members"]:
            by_obj.setdefault(r.object, []).append(r)
        kw["member_of"] = {k: tuple(v) for k, v in by_obj.items()}
        given = dict(names or {})
        kw["names"] = {p: given.get(p, p.rsplit("/", 1)[-1].removeprefix("place:")) for p in kw["places"]}
        return cls(seq=seq, seq_at=dict(seq_at), meta=dict(meta), **kw)

    def to_tables(self) -> dict:
        def dump(table, items):
            out = []
            for r in items:
                d = r._asdict()
                if table == "records":
                    d["selector"] = selector_json(r.selector)
                out.append(d)
            return out
        tables: dict[str, list] = {}
        for table, _key, attr in _KEYED:
            tables[table] = dump(table, getattr(self, attr).values())
        tables["copies"] = [{"object": o, "source": s, "added_seq": 0} for o, s in self.copies.items()]
        for table in _MULTI:
            tables[table] = dump(table, (r for g in getattr(self, table).values() for r in g))
        return tables

    def _memo(self, key, compute):
        hit = self._cache.get(key)
        if hit is None:
            hit = self._cache[key] = compute()
        return hit


def _parents(state: State, place: str) -> list[str]:
    return [r.parent for r in state.place_parents.get(place, ())]


def ancestors(state: State, place: str) -> frozenset[str]:
    """P 4.2: the place itself and every place above it by any path."""
    def compute():
        seen, stack = set(), [place]
        while stack:
            p = stack.pop()
            if p in seen:
                continue
            seen.add(p)
            stack.extend(_parents(state, p))
        return frozenset(seen)
    return state._memo(("anc", place), compute)


def dominators(state: State, place: str) -> frozenset[str]:
    """P 4.3: dom(X) = {X} for a root, else {X} + the intersection of dom(Q) over the parents."""
    def compute():
        parents = _parents(state, place)
        if not parents:
            return frozenset({place})
        return frozenset({place}) | frozenset.intersection(*(dominators(state, q) for q in parents))
    return state._memo(("dom", place), compute)


def place_retired(state: State, place: str) -> bool:
    """The place or any of its ancestors is retired."""
    for p in ancestors(state, place):
        row = state.places.get(p)
        if row is not None and row.retired_seq is not None:
            return True
    return False


def _live(state: State, place: str, what: str) -> None:
    if place not in state.places:
        raise RuleError("4.2 name rule", f"{what} {place} is not a registered place")
    if place_retired(state, place):
        raise RuleError("4.2 retiring a place", f"{what} {place} is retired")


def _too_deep(state: State, place: str, new_parent: str) -> bool:
    """Would adding new_parent give the place, or any place below it, more than 16 ancestors?"""
    add = ancestors(state, new_parent)
    for d in [p for p in state.places if place in ancestors(state, p)]:
        if len(ancestors(state, d) | add) > MAX_ANCESTORS:
            return True
    return False


def check_new_place(state: State, place: str, parents: Sequence[str]) -> tuple[str, ...]:
    """P 4.2 and 4.4: the parents a new place would get, or a RuleError."""
    check_id("place", place)
    if place in state.places:
        raise RuleError("4.4 register a place", f"{place} is already registered")
    if len(state.places) >= MAX_PLACES:
        raise RuleError("4.4 register a place", f"at most {MAX_PLACES:,} places per ledger")
    parents = tuple(parents)
    handle = person_of_home(place)
    if handle is not None:
        if parents:
            raise RuleError("P26", f"{place} is a home, a root; it takes no parent")
        if handle not in state.persons:
            raise RuleError("4.4 register a person", f"{place} is the home of {handle}, who is not registered")
        return ()
    prefix = place.rpartition("/")[0]
    if "/" not in place[len("place:"):]:
        if parents:
            raise RuleError("P26", f"{place} is a one-segment name, a root; it takes no parent")
        return ()
    if not parents:
        parents = (prefix,)
    if len(parents) > MAX_PARENTS:
        raise RuleError("4.2 parents", f"a place has at most {MAX_PARENTS} parents")
    if len(set(parents)) != len(parents):
        raise RuleError("4.2 parents", "a parent is listed twice")
    for q in parents:
        check_id("place", q)
        _live(state, q, "parent")
    if prefix not in state.places:
        raise RuleError("4.2 name rule", f"the prefix {prefix} of {place} is not a registered place")
    dom = frozenset.intersection(*(dominators(state, q) for q in parents))
    if prefix not in dom:
        raise RuleError("4.2 name rule", f"the prefix {prefix} does not dominate {place}")
    anc = {place}.union(*(ancestors(state, q) for q in parents))
    if len(anc) > MAX_ANCESTORS:
        raise RuleError("4.2 bounded ancestry", f"a place has at most {MAX_ANCESTORS} ancestors, itself included")
    return parents


def check_new_parent(state: State, place: str, parent: str) -> None:
    """P 4.2: a parent edge on a place that already has a parent."""
    check_id("place", place)
    check_id("place", parent)
    row = state.places.get(place)
    if row is None:
        raise RuleError("4.2 name rule", f"{place} is not a registered place")
    if row.is_root or not _parents(state, place):
        raise RuleError("P26", f"{place} is a root and stays a root")
    _live(state, parent, "parent")
    if parent in _parents(state, place):
        raise RuleError("4.2 parents", f"{parent} is already a parent of {place}")
    if place in ancestors(state, parent):
        raise RuleError("4.2 no cycles", f"making {parent} a parent of {place} would make a cycle")
    if len(_parents(state, place)) >= MAX_PARENTS:
        raise RuleError("4.2 parents", f"a place has at most {MAX_PARENTS} parents")
    if _too_deep(state, place, parent):
        raise RuleError("4.2 bounded ancestry",
                        f"a place has at most {MAX_ANCESTORS} ancestors, itself included")


# ---------------------------------------------------------------- grants (P 7.2)

@dataclass(frozen=True)
class Grant:
    id: str
    issuer: str
    grantee: str
    layer: str
    parent_id: str | None
    ops: frozenset
    envelope: Selector
    max_days: int
    depth: int
    expires: int
    created: int
    created_seq: int = 0
    revoked: int | None = None
    revoked_by: str | None = None
    revoke_reason: str | None = None
    revoked_seq: int | None = None


def _grant_of(row) -> Grant:
    ops, env = row.ops, row.envelope
    if isinstance(ops, str):
        ops = json.loads(ops)
    if isinstance(env, str):
        env = json.loads(env)
    if not isinstance(env, Selector):
        env = parse_selector(env)
    d = row._asdict()
    d["ops"], d["envelope"] = frozenset(ops), env
    return Grant(**d)


def grant_chain(state: State, grant_id: str) -> tuple[Grant, ...]:
    """The grant and every grant above it, root first."""
    out, seen, gid = [], set(), grant_id
    while gid is not None:
        row = state.grants.get(gid)
        if row is None:
            raise RuleError("7.2 grants", f"{gid} is not a grant")
        if gid in seen:
            raise RuleError("7.2 grants", f"grant {gid} is its own ancestor")
        seen.add(gid)
        out.append(_grant_of(row))
        gid = row.parent_id
    return tuple(reversed(out))


def _is_steward(state: State, place: str, person: str) -> bool:
    return any(r.person == person and r.removed_seq is None for r in state.place_stewards.get(place, ()))


def grant_validity(state: State, grant_id: str, at: int) -> tuple[bool, str | None]:
    """From the grant up to its root, link by link: revoked, expired, too long; then the root's issuer a steward."""
    chain = grant_chain(state, grant_id)
    for link in reversed(chain):
        if link.revoked_seq is not None and link.revoked_seq <= state.seq:
            return False, "revoked"
        if at >= link.expires:
            return False, "expired"
        if len(chain) > MAX_GRANT_LINKS:
            return False, "too-long"
    root = chain[0]
    if not _is_steward(state, root.layer, root.issuer):
        return False, "not-steward"
    return True, None


def _agent_of(state: State, agent: str, what: str):
    row = state.agents.get(agent)
    if row is None or row.retired_seq is not None:
        raise RuleError("7.2 grants", f"{what} {agent} is not a registered agent")
    return row


def selector_within(state: State, inner: Selector, outer: Selector) -> bool:
    """P 7.2: each list a subset, "*" only where the outer has "*", each audience entry within an outer entry."""
    for f in ("requesters", *_OBJ_KEYS, "actions", "purposes"):
        a, b = getattr(inner, f), getattr(outer, f)
        if b == STAR:
            continue
        if a == STAR or not set(a) <= set(b):
            return False

    def entry_ok(v: str) -> bool:
        for o in outer.audience:
            if o == v or o == "commons":
                return True
            if o.startswith("place:") and v.startswith("place:") and o in dominators(state, v):
                return True
        return False
    return all(entry_ok(v) for v in inner.audience)


def _grant_fields(grant: Grant) -> None:
    rule = "7.2 grants"
    if not set(grant.ops) <= set(GRANT_OPS) or not grant.ops:
        raise RuleError(rule, f"ops must be a non-empty subset of {', '.join(GRANT_OPS)}")
    if not isinstance(grant.envelope, Selector):
        raise RuleError(rule, "the envelope must be one selector")
    if not 0 <= grant.depth <= MAX_GRANT_DEPTH:
        raise RuleError(rule, f"depth is 0 to {MAX_GRANT_DEPTH}")
    if grant.max_days < 1:
        raise RuleError(rule, "max_days must be at least 1")
    if not grant.created < grant.expires <= grant.created + MAX_GRANT_HOURS * 3600:
        raise RuleError(rule, f"a grant lasts at most {MAX_GRANT_HOURS} hours")


def check_root_grant(state: State, grant: Grant) -> None:
    """P 7.2: a steward of the layer issues it to an agent that acts for them."""
    rule = "7.2 grants"
    if grant.parent_id is not None:
        raise RuleError(rule, "a root grant has no parent")
    _grant_fields(grant)
    if grant.layer not in state.places:
        raise RuleError(rule, f"{grant.layer} is not a registered place")
    person = state.persons.get(grant.issuer)
    if person is None or person.retired_seq is not None:
        raise RuleError(rule, f"{grant.issuer} is not a registered person")
    if not _is_steward(state, grant.layer, grant.issuer):
        raise RuleError(rule, f"{grant.issuer} is not a steward of {grant.layer}")
    if _agent_of(state, grant.grantee, "grantee").acts_for != person.home:
        raise RuleError(rule, f"{grant.grantee} does not act for {grant.issuer}")


def check_child_grant(state: State, parent: Grant, child: Grant) -> None:
    """P 7.2: the parent's grantee issues it to another agent of the same person; a subset in every field."""
    rule = "7.2 grants"
    links = 1
    up = parent.parent_id
    while up is not None and links <= MAX_GRANT_LINKS:
        links += 1
        row = state.grants.get(up)
        up = row.parent_id if row is not None else None
    if parent.depth < 1 or links + 1 > MAX_GRANT_LINKS:
        raise RuleError(rule, f"a chain has at most {MAX_GRANT_LINKS} links")
    if child.parent_id != parent.id:
        raise RuleError(rule, "the child names another parent")
    if child.layer != parent.layer:
        raise RuleError(rule, "a child stays in its parent's layer")
    if child.issuer != parent.grantee:
        raise RuleError(rule, "a child is issued by its parent's grantee")
    holder = _agent_of(state, parent.grantee, "issuer")
    other = _agent_of(state, child.grantee, "grantee")
    if child.grantee == child.issuer or other.acts_for != holder.acts_for:
        raise RuleError(rule, f"{child.grantee} is not another agent acting for the same person")
    _grant_fields(child)
    if not child.ops <= parent.ops:
        raise RuleError(rule, "a child's ops are a subset of its parent's")
    if not selector_within(state, child.envelope, parent.envelope):
        raise RuleError(rule, "a child's envelope lies within its parent's")
    if child.max_days > parent.max_days:
        raise RuleError(rule, "a child's max_days is at most its parent's")
    if child.depth >= parent.depth:
        raise RuleError(rule, "a child's depth is below its parent's")
    if child.expires > parent.expires:
        raise RuleError(rule, "a child expires no later than its parent")
