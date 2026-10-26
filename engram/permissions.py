"""Permissions by place: the pure model (names, ids, selectors).

Reads no file, opens no database, reads no clock, draws no randomness.
"""
from __future__ import annotations

import json
import re
from collections import namedtuple
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable, Iterable, Mapping, NamedTuple, Sequence

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
    copy_seqs: Mapping[str, int]         # the seq each copy was added at, written back by to_tables
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
        kw["copy_seqs"] = {r.object: r.added_seq for r in rows["copies"]}
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
        tables["copies"] = [{"object": o, "source": s, "added_seq": self.copy_seqs[o]}
                            for o, s in self.copies.items()]
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


# ---------------------------------------------------------------- matching with history (P 5.2, 5.3, 6.5)

@dataclass(frozen=True)
class Use:
    """One act on one object (P 6.1). names are the memories a road or trail names, in order; shows those
    whose content the answer shows."""
    requester: str
    place: str
    obj: str
    copy: str
    action: str
    purpose: str
    at: int
    names: tuple = ()
    shows: frozenset = frozenset()


def acts_for_place(state: State, agent: str) -> str | None:
    """act(a): the place the agent acts for, or None for an unregistered agent."""
    row = state.agents.get(agent)
    return None if row is None else row.acts_for


def _span(state: State, added: int, removed: int | None) -> tuple[int, int | None]:
    """The time interval [lo, hi) a membership row is in force; hi None is open (PF22)."""
    lo = state.seq_at[added]
    if removed is None or removed > state.seq:
        return lo, None
    return lo, state.seq_at[removed]


def _in_force(state: State, added: int, removed: int | None, t: int) -> bool:
    lo, hi = _span(state, added, removed)
    return lo <= t and (hi is None or t < hi)


def _meets(state: State, added: int, removed: int | None, anchor: int, t: int) -> bool:
    lo, hi = _span(state, added, removed)
    return anchor <= t and lo <= t and (hi is None or hi > anchor)


def agent_place_at(state: State, agent: str, at: int) -> str | None:
    for r in state.agent_places.get(agent, ()):
        if _in_force(state, r.added_seq, r.removed_seq, at):
            return r.place
    return None


def _lane_at(notes: Sequence, tau: int) -> str | None:
    """The lane of the last note with at <= tau (notes are ordered by (at, seq))."""
    lane = None
    for n in notes:
        if n.at > tau:
            break
        lane = n.lane
    return lane


def lane_held(state: State, ref: str, lane: str, since: int, at: int) -> bool:
    """The allow reading: the memory has a note, and `lane` was its lane at every instant of
    [max(since, first note's at), at], with no pending note in that interval. Times are whole seconds, so every
    note of a second is in force in it: a pending note is not lost to the note that settles it in the same second
    (P7, L5)."""
    notes = state.lane_notes.get(ref, ())
    if not notes:
        return False
    start = max(since, notes[0].at)
    if start > at:
        return False
    if _lane_at(notes, start) != lane:
        return False
    return all(n.lane == lane for n in notes if start <= n.at <= at)       # every note of the first second too


def lane_touched(state: State, ref: str, lane: str, anchor: int, at: int) -> bool:
    """The deny reading: no note, or `lane` or a pending move was in force at some instant of [anchor, at]."""
    notes = state.lane_notes.get(ref, ())
    if not notes:
        return True
    if anchor > at:
        return False
    first = _lane_at(notes, anchor)
    if first is None:
        first = notes[0].lane            # a first note assumes the lane held since creation
    if first in (lane, "pending"):
        return True
    return any(n.lane in (lane, "pending") for n in notes if anchor <= n.at <= at)


def _star_or_in(dim, value) -> bool:
    return dim == STAR or value in dim


def _audience_entry(state: State, v: str, layer: str, use: Use, anchor: int, deny: bool) -> bool:
    a, t = use.requester, use.at
    if v == "commons":
        return True
    act = acts_for_place(state, a)
    if act is None:
        return False
    if layer.startswith("place:"):
        layer_place = layer
    else:
        layer_place = acts_for_place(state, layer)
    if v == "self":
        if act != layer_place:
            return False
        return deny or layer_place in dominators(state, use.place)
    if v.startswith("group:"):
        members = [r for r in state.group_members.get(v, ()) if r.agent == a]
        if deny:
            if not any(_meets(state, r.added_seq, r.removed_seq, anchor, t) for r in members):
                return False
            return True
        if not any(r.removed_seq is None and _in_force(state, r.added_seq, r.removed_seq, t) for r in members):
            return False        # a removed membership is never counted for an allow (P 6.5)
        group = state.groups.get(v)
        return group is not None and home_of(group.owner) in dominators(state, use.place)
    if v.startswith("place:"):
        if deny:
            if v in ancestors(state, use.place) or v in ancestors(state, act):
                return True
            return any(v in ancestors(state, r.place) for r in state.agent_places.get(a, ())
                       if _meets(state, r.added_seq, r.removed_seq, anchor, t))
        return v in dominators(state, use.place) and v in dominators(state, act)
    return False


def _object_dims(state: State, sel: Selector, layer: str, anchor: int, use: Use, action: str, deny: bool,
                 assume: frozenset, check_validity: bool) -> bool:
    ref = parse_object_ref(use.obj)
    if not _star_or_in(sel.kinds, ref.kind):
        return False
    if not _star_or_in(sel.stores, ref.instance_id):
        return False
    if sel.layers != STAR and ref.layer not in sel.layers:
        return False
    if sel.memories != STAR and use.obj not in sel.memories:
        return False
    t = use.at
    if sel.lanes != STAR:
        if deny:
            if not any(lane_touched(state, use.obj, lane, anchor, t) for lane in sel.lanes):
                return False
        elif not any(lane_held(state, use.obj, lane, anchor, t) for lane in sel.lanes):
            return False
    if sel.collections != STAR:
        rows = [r for r in state.member_of.get(use.obj, ()) if r.collection in sel.collections]
        if not any(_membership_counts(state, r, layer, anchor, use, action, deny, assume, check_validity)
                   for r in rows):
            return False
    return True


def _membership_counts(state: State, row, layer: str, anchor: int, use: Use, action: str, deny: bool,
                       assume: frozenset, check_validity: bool) -> bool:
    t = use.at
    if deny:
        return _meets(state, row.added_seq, row.removed_seq, anchor, t)
    if row.removed_seq is not None and row.removed_seq <= state.seq:
        return False        # a removed membership is never counted for an allow, at any t (P 6.5)
    if not _in_force(state, row.added_seq, row.removed_seq, t):
        return False
    if not row.backing.startswith("grant:"):
        return True
    if row in assume:       # the envelope that bounds this very membership may rely on it
        return True
    gid = row.backing[len("grant:"):]
    if check_validity and not grant_validity(state, gid, t)[0]:
        return False
    try:
        chain = grant_chain(state, gid)
    except RuleError:
        return False
    return all(_selector_match(state, g.envelope, g.layer, anchor, use, action, False, assume | {row},
                               check_validity) for g in chain)


def _selector_match(state: State, sel: Selector, layer: str, anchor: int, use: Use, action: str, deny: bool,
                    assume: frozenset = frozenset(), check_validity: bool = True) -> bool:
    """P 5.3 rules 2 and 3."""
    if not _star_or_in(sel.requesters, use.requester):
        return False
    if not _star_or_in(sel.actions, action):
        return False
    if not _star_or_in(sel.purposes, use.purpose):
        return False
    if not any(_audience_entry(state, v, layer, use, anchor, deny) for v in sel.audience):
        return False
    return _object_dims(state, sel, layer, anchor, use, action, deny, assume, check_validity)


def _revoked(state: State, record) -> bool:
    return record.revoked_seq is not None and record.revoked_seq <= state.seq


def _in_interval(record, t: int) -> bool:
    return record.valid_from <= t and (record.valid_until is None or t < record.valid_until)


def _chain_ok(state: State, record, use: Use, action: str, deny: bool, check_validity: bool) -> bool:
    """P 5.3 rule 4: the replaces chain, each link's revocation ignored."""
    cur, n = record.replaces, 0
    while cur is not None:
        n += 1
        r = state.records.get(cur)
        if r is None or n > MAX_REPLACES:
            return False
        if check_validity and not _in_interval(r, use.at):
            return False
        if not _selector_match(state, r.selector, r.layer, record.anchor, use, action, deny,
                               check_validity=check_validity):
            return False
        cur = r.replaces
    return True


def _grant_ok(state: State, record, use: Use, action: str, deny: bool, check_validity: bool) -> bool:
    """P 5.3 rule 5."""
    if not record.backing.startswith("grant:"):
        return True
    gid = record.backing[len("grant:"):]
    if check_validity and not grant_validity(state, gid, use.at)[0]:
        return False
    try:
        chain = grant_chain(state, gid)
    except RuleError:
        return False
    return all(_selector_match(state, g.envelope, record.layer, record.anchor, use, action, deny,
                               check_validity=check_validity) for g in chain)


def record_matches(state: State, record: Record, use: Use, action: str) -> bool:
    """P 5.3 rules 1 to 5. Memberships read narrowly for an allow and widely for a deny (P7). Whether the
    requester is in the use's place is decide's step 1, not this (PF21)."""
    deny = record.effect == "deny"
    if _revoked(state, record) or not _in_interval(record, use.at):
        return False
    if not _selector_match(state, record.selector, record.layer, record.anchor, use, action, deny):
        return False
    return (_chain_ok(state, record, use, action, deny, True)
            and _grant_ok(state, record, use, action, deny, True))


def record_candidate(state: State, record: Record, use: Use, action: str) -> bool:
    """P 6.5: an unrevoked allow matching by rules 2 and 3 and the selector parts of 4 and 5; every validity
    interval and every grant's validity is ignored (PF23)."""
    if record.effect != "allow" or _revoked(state, record):
        return False
    if not _selector_match(state, record.selector, record.layer, record.anchor, use, action, False,
                           check_validity=False):
        return False
    return (_chain_ok(state, record, use, action, False, False)
            and _grant_ok(state, record, use, action, False, False))


# ---------------------------------------------------------------- need, subjects, layers, the decision (P 6.3 to 6.5)

@dataclass(frozen=True)
class Need:
    """One object and the actions the use asks of it (P 6.4)."""
    obj: str
    actions: tuple


_CLOSURE = {"recall": ("recall",), "read": ("recall", "read"),
            "inject_context": ("recall", "read", "inject_context"), "route": ("route",),
            "imprint": ("recall", "read", "imprint")}


def _kind_of(ref: str) -> str | None:
    try:
        return parse_object_ref(ref).kind
    except RuleError:
        return None


def needs(use: Use) -> tuple[Need, ...]:
    """P 6.4's table, then for a road or trail the memories it names, in ref order: `recall` on each, and `read`
    and `inject_context` on each whose content the answer shows (a shown memory is a named one)."""
    if use.action not in _CLOSURE:
        raise RuleError("6.4 need", f"{use.action!r} is not an action")
    out = [Need(use.obj, _CLOSURE[use.action])]
    if _kind_of(use.obj) in ("road", "trail"):
        for m in sorted(set(use.names) | set(use.shows), key=_units):
            out.append(Need(m, ("recall", "read", "inject_context") if m in use.shows else ("recall",)))
    return tuple(out)


def _own_subjects(state: State, ref: str, at: int | None = None) -> set[str]:
    """The ref's store's owner and its co-subjects: those in force at `at`, or every one not removed when `at` is
    None. A ref that names no registered store has none of its own."""
    out: set[str] = set()
    try:
        parsed = parse_object_ref(ref)
    except RuleError:
        return out
    store = state.stores.get(parsed.instance_id)
    if store is not None and store.imprint_of is None:     # an imprint's owner is never a default subject
        out.add(store.owner)
    for row in state.subjects.get(ref, ()):
        if (row.removed_seq is None if at is None else _in_force(state, row.added_seq, row.removed_seq, at)):
            out.add(row.subject)
    return out


def subjects_of(state: State, obj: str, at: int, names: Sequence[str] = ()) -> tuple[str, ...]:
    """P 6.3 item 1 and 7.4: the object's store's owner and its co-subjects in force at `at`, those of each
    source up the `copies` chain (at most MAX_COPY_CHAIN links), and for a road or trail those of the memories
    it names. Sorted. An object whose ref names no registered store has none of its own."""
    out: set[str] = set()

    def with_sources(ref: str) -> None:
        seen, cur = set(), ref
        for _ in range(MAX_COPY_CHAIN + 1):
            if cur is None or cur in seen:
                return
            seen.add(cur)
            out.update(_own_subjects(state, cur, at))
            cur = state.copies.get(cur)

    with_sources(obj)
    for name in names:
        with_sources(name)
    return tuple(sorted(out, key=_units))


@dataclass(frozen=True)
class Layer:
    id: str
    kind: str       # consent, restriction, legacy or outside


@dataclass(frozen=True)
class LegacyLayer:
    """A layer kept outside the ledger and decided afresh on every request: a ConnectionPolicy (R7)."""
    name: str
    allows: Callable[[Use, str], bool]


def holding_place(state: State, copy: str) -> str | None:
    """H, the place of the copy h that serves a use (P 6.1); None when no `stores` row gives it one."""
    try:
        ref = parse_copy_ref(copy)
    except RuleError:
        return None
    store = state.stores.get(ref.instance_id)
    return None if store is None else store.place


def _subject_layer(state: State, subject: str) -> str:
    if subject.startswith("person:"):
        row = state.persons.get(subject)
        return row.home if row is not None else home_of(subject)
    return subject


def required_layers(state: State, use: Use, *, legacy: Sequence[LegacyLayer] = (),
                    outside: Mapping | None = None, subjects: Sequence[str] | None = None) -> tuple[Layer, ...]:
    """Req(u) in P 6.5 step 2's order, each layer once: subjects by id, the requester's places by id, the holding
    places by id (a holding place with no `stores` row is a layer that does not exist, named by the copy), the
    legacy layers, the agent's restriction layer. A place id in `outside` is an `outside` layer there. A caller
    that has the use's subjects already (a bulk decision) passes them."""
    outside = outside or {}
    out: list[Layer] = []
    seen: set = set()

    def add(layer_id: str, kind: str) -> None:
        key = (kind == "legacy", kind == "restriction", layer_id)
        if key not in seen:
            seen.add(key)
            out.append(Layer(layer_id, "outside" if kind == "consent" and layer_id in outside else kind))

    for s in (subjects_of(state, use.obj, use.at, use.names) if subjects is None else subjects):
        add(_subject_layer(state, s), "consent")
    for p in sorted(ancestors(state, use.place), key=_units):
        add(p, "consent")
    held = holding_place(state, use.copy)
    if held is None:
        add(use.copy, "consent")
    else:
        for p in sorted(ancestors(state, held), key=_units):
            add(p, "consent")
    for layer in legacy:
        add(layer.name, "legacy")
    add(use.requester, "restriction")
    return tuple(out)


@dataclass(frozen=True)
class Cited:
    layer: str
    kind: str
    action: str
    verdict: str
    records: tuple = ()

    def to_json(self, *, multi: bool = False, version: int | None = None) -> dict:
        out = {"layer": self.layer, "kind": self.kind, "action": self.action, "verdict": self.verdict}
        if multi:
            out["records"] = list(self.records)
        else:
            out["record"] = self.records[0] if self.records else None
        out["version"] = version
        return out


@dataclass(frozen=True)
class Refusal:
    code: str
    layer: str | None = None
    action: str | None = None

    def to_json(self) -> dict:
        return {"code": self.code, "layer": self.layer, "action": self.action}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    at: int
    ledger_seq: int
    action: str
    cited: tuple
    refusal: Refusal | None
    until: int | None
    horizon: int | None
    versions: Mapping[str, int]
    multi: bool = False         # a road or trail: `cited` holds `records` (R8)
    # How far `decide` got, so `meet_legacy` can place a legacy verdict where `decide(legacy=...)` would: the
    # number of needs it decided, and the need the first refusal came from. Not part of the decision's JSON.
    processed: int | None = field(default=None, compare=False)
    failed_need: int | None = field(default=None, compare=False)

    def to_json(self) -> dict:
        return {"allowed": self.allowed, "at": self.at, "ledger_seq": self.ledger_seq, "action": self.action,
                "cited": [c.to_json(multi=self.multi, version=self.versions.get(c.layer)) for c in self.cited],
                "refusal": None if self.refusal is None else self.refusal.to_json(),
                "until": self.until, "horizon": self.horizon}


def _layer_index(state: State):
    """({layer: its records sorted by id}, {layer: its grants}), built once per State."""
    def compute():
        records: dict[str, list] = {}
        for r in state.records.values():
            records.setdefault(r.layer, []).append(r)
        grants: dict[str, list] = {}
        for g in state.grants.values():
            grants.setdefault(g.layer, []).append(g)
        return ({k: tuple(sorted(v, key=lambda r: _units(r.id))) for k, v in records.items()}, grants)
    return state._memo(("layer-index",), compute)


def _prefilter(state: State, layer_id: str, use: Use, action: str) -> list:
    """P 6.5, "How it is computed": the layer's records whose requesters, actions, purposes and audience can
    match this requester, place, action and purpose, before any object test. It reads nothing of the object, so
    it is made once per (layer, requester, place, purpose, time, action) for a State, however many objects ask."""
    def compute():
        out = []
        for r in _layer_index(state)[0].get(layer_id, ()):
            sel = r.selector
            if not (_star_or_in(sel.requesters, use.requester) and _star_or_in(sel.actions, action)
                    and _star_or_in(sel.purposes, use.purpose)):
                continue
            deny = r.effect == "deny"
            if any(_audience_entry(state, v, r.layer, use, r.anchor, deny) for v in sel.audience):
                out.append(r)
        return out
    return state._memo(("prefilter", layer_id, use.requester, use.place, use.purpose, use.at, action), compute)


def layer_version(state: State, layer_id: str) -> int:
    """The highest seq that touches the layer: its records and grants (made, revoked), and the place's own
    creation, retirement and stewards."""
    best = 0
    records, grants = _layer_index(state)
    for r in records.get(layer_id, ()):
        best = max(best, r.created_seq, r.revoked_seq or 0)
    for g in grants.get(layer_id, ()):
        best = max(best, g.created_seq, g.revoked_seq or 0)
    for row in (state.places.get(layer_id), state.agents.get(layer_id)):
        if row is not None:
            best = max(best, row.created_seq, row.retired_seq or 0)
    for st in state.place_stewards.get(layer_id, ()):
        best = max(best, st.added_seq, st.removed_seq or 0)
    return best


def _grant_terms(state: State, gid: str, t: int):
    """(chain, valid): the chain's grants, or () if unreadable, and whether it is valid at t."""
    try:
        chain = grant_chain(state, gid)
        return chain, grant_validity(state, gid, t)[0]
    except RuleError:
        return (), False


def _chain_expiries(state: State, backing: str) -> list[int]:
    """The `expires` of every grant in the chain behind a `grant:<id>` backing; none for a person or if unreadable."""
    if not backing.startswith("grant:"):
        return []
    try:
        return [g.expires for g in grant_chain(state, backing[len("grant:"):])]
    except RuleError:
        return []


def effective_end(state: State, record: Record, matched_memberships: Sequence) -> int | None:
    """P 6.5 step 5: the earliest of the record's `valid_until`, those of its `replaces` chain, the `expires` of
    every grant in its grant chain, and the `expires` of every grant in the chain of each membership it matched
    through. The caller names those memberships: one route per selector, the best (see `_terms`)."""
    ends: list[int] = []
    cur, n = record, 0
    while cur is not None and n <= MAX_REPLACES:
        if cur.valid_until is not None:
            ends.append(cur.valid_until)
        cur, n = (state.records.get(cur.replaces) if cur.replaces else None), n + 1
    ends.extend(_chain_expiries(state, record.backing))
    for m in matched_memberships:
        ends.extend(_chain_expiries(state, m.backing))
    return min(ends) if ends else None


def _terms(state: State, record: Record, use: Use, action: str, valid_only: bool) -> tuple[int | None, bool]:
    """(effective end, grant chain invalid at t) of an allow for this use (P 6.5 step 5 and the codes). For each
    selector with a collections list (the record's, its replaces chain's and its grants' envelopes), the
    membership route is: none when the object is in the collection by a person-backed row, else the best
    grant-backed row, the one whose chain ends latest. With valid_only, only memberships that count with their
    chains valid are read."""
    t = use.at
    invalid = False
    selectors = [(record.selector, record.layer)]
    cur, n = record.replaces, 0
    while cur is not None and n < MAX_REPLACES:
        r = state.records.get(cur)
        if r is None:
            break
        selectors.append((r.selector, r.layer))
        cur, n = r.replaces, n + 1
    if record.backing.startswith("grant:"):
        chain, ok = _grant_terms(state, record.backing[len("grant:"):], t)
        invalid = invalid or not ok
        selectors.extend((g.envelope, record.layer) for g in chain)
    routes = []
    for sel, layer in selectors:
        if sel.collections == STAR:
            continue
        rows = [m for m in state.member_of.get(use.obj, ())
                if m.collection in sel.collections
                and _membership_counts(state, m, layer, record.anchor, use, action, False, frozenset(), valid_only)]
        if not rows or any(not m.backing.startswith("grant:") for m in rows):
            continue
        best, best_end, all_invalid = None, None, True
        for m in rows:
            chain, ok = _grant_terms(state, m.backing[len("grant:"):], t)
            if chain:
                end = min(g.expires for g in chain)
                if best_end is None or end > best_end:
                    best, best_end = m, end
            all_invalid = all_invalid and not ok
        if best is not None:
            routes.append(best)
        invalid = invalid or all_invalid
    return effective_end(state, record, routes), invalid


def _not_yet(state: State, record: Record, t: int) -> bool:
    cur, n = record, 0
    while cur is not None and n <= MAX_REPLACES:
        if cur.valid_from > t:
            return True
        cur, n = (state.records.get(cur.replaces) if cur.replaces else None), n + 1
    return False


def _ledger_verdict(state: State, layer: Layer, use: Use, action: str) -> tuple[str, tuple]:
    """(verdict, cited record ids) of a consent or restriction layer for one action (P 6.5 steps 3 and 5)."""
    exists = layer.id in (state.agents if layer.kind == "restriction" else state.places)
    if not exists:
        return "missing", ()
    candidates = _prefilter(state, layer.id, use, action)
    if any(r.effect == "deny" and record_matches(state, r, use, action) for r in candidates):
        return "deny", ()
    if layer.kind == "restriction":
        return "silent", ()               # a restriction layer is only its denies
    allows = [r for r in candidates if r.effect == "allow" and record_matches(state, r, use, action)]
    if not allows:
        return "silent", ()

    def rank(r):
        end = _terms(state, r, use, action, True)[0]
        return (end is not None, -(end or 0), _units(r.id))
    return "allow", (min(allows, key=rank).id,)


def layer_verdict(state: State, layer: Layer, use: Use, action: str) -> str:
    """`allow`, `deny`, `silent` or `missing` for a ledger layer (consent or restriction)."""
    if layer.kind not in ("consent", "restriction"):
        raise RuleError("6.3 layers", f"{layer.kind} layer {layer.id} is decided by its own callable")
    return _ledger_verdict(state, layer, use, action)[0]


def _silent_code(state: State, layer: Layer, use: Use, action: str) -> str:
    """P 6.5 step 8 for a consent layer with no matching allow: read every candidate (and its chains)."""
    expired = invalid = not_yet = False
    for r in _prefilter(state, layer.id, use, action):
        if not record_candidate(state, r, use, action):
            continue
        end, bad = _terms(state, r, use, action, False)
        expired = expired or (end is not None and end <= use.at)
        invalid = invalid or bad
        not_yet = not_yet or _not_yet(state, r, use.at)
    return "EXPIRED" if expired else "GRANT_INVALID" if invalid else "NOT_YET" if not_yet else "NO_ALLOW"


def _requester_ok(state: State, use: Use) -> bool:
    row = state.agents.get(use.requester)
    if row is None or row.retired_seq is not None:
        return False
    return any(r.place == use.place and _in_force(state, r.added_seq, r.removed_seq, use.at)
               for r in state.agent_places.get(use.requester, ()))


def _subject_retired(state: State, subject: str) -> bool:
    row = state.persons.get(subject)
    return row is not None and (row.retired_seq is not None or place_retired(state, row.home))


def _live_denies(state: State, layer_id: str, t: int):
    """The layer's denies that are not revoked and start after t."""
    return [r for r in _layer_index(state)[0].get(layer_id, ())
            if r.effect == "deny" and r.valid_from > t and not _revoked(state, r)]


def _until(state: State, t: int, ends: Sequence[int], layers: Sequence[str], read: Sequence[tuple]) -> int | None:
    """P 6.5 step 6: the earliest effective end of a cited record, and the `valid_from` of every deny in a
    required ledger layer that starts after t and would match some use of `read` (each (use, actions) of need(u))
    at that time, σ fixed."""
    out = list(ends)
    for layer_id in layers:
        for r in _live_denies(state, layer_id, t):
            if any(record_matches(state, r, replace(sub, at=r.valid_from), x) for sub, actions in read
                   for x in actions):
                out.append(r.valid_from)
    return min(out) if out else None


def _horizon(state: State, t: int, layers: Sequence[str], objs: Sequence[str]) -> int | None:
    """P 6.5 step 7: the earliest `valid_from` or `valid_until` after t of every record in a required ledger layer
    that is not revoked and has not ended, or is in the `replaces` chain of one; and every `expires` after t of
    a grant behind such a record, behind a grant in its chain, or behind a membership of a needed object in a
    collection that one of their selectors names. Terms beyond the spec's reading are only ever earlier ones."""
    out: list[int] = []
    seen_chain: set = set()
    backings: list[str] = []
    selectors: list[Selector] = []

    def note_record(r, *, allow_grants: bool) -> None:
        for v in (r.valid_from, r.valid_until):
            if v is not None and v > t:
                out.append(v)
        selectors.append(r.selector)
        if allow_grants:
            backings.append(r.backing)

    for layer_id in layers:
        for r in _layer_index(state)[0].get(layer_id, ()):
            if _revoked(state, r) or (r.valid_until is not None and r.valid_until <= t):
                continue
            note_record(r, allow_grants=True)
            cur, n = r.replaces, 0
            while cur is not None and cur not in seen_chain and n < MAX_REPLACES:
                seen_chain.add(cur)
                link = state.records.get(cur)
                if link is None:
                    break
                note_record(link, allow_grants=False)
                cur, n = link.replaces, n + 1
    for b in set(backings):
        if b.startswith("grant:"):
            try:
                chain = grant_chain(state, b[len("grant:"):])
            except RuleError:
                continue
            out.extend(g.expires for g in chain if g.expires > t)
            selectors.extend(g.envelope for g in chain)
    named = set()
    for sel in selectors:
        if sel.collections != STAR:
            named.update(sel.collections)
    for obj in objs:
        for m in state.member_of.get(obj, ()):
            if m.collection in named:
                out.extend(e for e in _chain_expiries(state, m.backing) if e > t)
    return min(out) if out else None


@dataclass(frozen=True)
class BulkUse:
    """A bulk use U = (a, P, O, h, x, p, t) (P 6.4, P33). `named` says the receipt names its objects (at most
    MAX_BULK_NAMED); otherwise they are derived and counted (at most MAX_BULK_DERIVED). `names(o)` gives the
    memories a road or trail o names; it is called again when the objects are decided, so the touches are
    streamed and never held."""
    requester: str
    place: str
    objects: tuple
    copy: str
    action: str
    purpose: str
    at: int
    named: bool
    names: Callable[[str], Iterable[str]] = lambda o: ()


def _listed_memories(state: State) -> frozenset:
    """Every memory ref that some record's or grant's selector lists in `memories`."""
    def compute():
        out: set = set()
        for sel in [r.selector for r in state.records.values()] + [_grant_of(g).envelope for g in state.grants.values()]:
            if sel.memories != STAR:
                out.update(sel.memories)
        return frozenset(out)
    return state._memo(("listed-memories",), compute)


class _Run:
    """The accumulation of P 6.5 over one or many (object, action) pairs: each pair is decided once, however many
    objects need it (P 6.4: need(U) is a union)."""

    def __init__(self, state: State, proto: Use, legacy: Sequence[LegacyLayer], outside: Mapping | None, *,
                 multi: bool, group: bool = False):
        self.state, self.proto, self.legacy, self.multi, self.group = state, proto, tuple(legacy), multi, group
        self.outside = outside or {}
        self.by_name = {layer.name: layer for layer in legacy}
        self.entries: dict = {}
        self.versions: dict[str, int] = {}
        self.layer_pos: dict[str, int] = {}     # layers in required_layers order, the first object's first
        self.failure: tuple | None = None
        self.cur = 0                             # the index in need(u) being decided (decide only)
        self.failed_need: int | None = None
        self.ends: list[int] = []                # effective ends of the cited records (step 5)
        self.ledger_layers: list[str] = []       # the required consent and restriction layers, first seen order
        self._ledger_seen: set = set()
        self.read: dict = {}                     # obj -> (use, [actions]) for each need(u) decided
        self.objs: list[str] = []
        self.done: set = set()                   # (obj, action) pairs already decided
        self._subjects: dict = {}
        self._retired: dict = {}
        self._shared: dict = {}                  # group key -> (layers, {(ledger layer id, action): row})
        self._read_groups: set = set()

    # -- subjects, with one memo per ref
    def subjects(self, obj: str, names: Sequence[str] = ()) -> tuple:
        t = self.proto.at
        if not names:
            got = self._subjects.get(obj)
            if got is None:
                got = self._subjects[obj] = subjects_of(self.state, obj, t)
            return got
        out = set(self.subjects(obj))
        for name in names:
            out.update(self.subjects(name))
        return tuple(sorted(out, key=_units))

    def _any_retired(self, subjects: Sequence[str]) -> bool:
        for s in subjects:
            got = self._retired.get(s)
            if got is None:
                got = self._retired[s] = _subject_retired(self.state, s)
            if got:
                return True
        return False

    def group_key(self, ref: str, subjects: tuple):
        """P 6.4, "How it is computed": what the pre-filtered records read of an object."""
        try:
            parsed = parse_object_ref(ref)
        except RuleError:
            return None
        state = self.state
        return (parsed.kind, parsed.instance_id, parsed.layer, tuple(state.lane_notes.get(ref, ())),
                tuple(state.member_of.get(ref, ())), ref if ref in _listed_memories(state) else None, subjects)

    # -- one row: a layer's verdict for one action
    def _row(self, layer: Layer, sub: Use, action: str) -> tuple:
        recs: tuple = ()
        ends: list = []
        if layer.kind == "outside":
            verdict = self.outside[layer.id](sub, action)
            if verdict not in ("allow", "deny", "silent"):
                raise RuleError("6.1 outside layer", f"layer {layer.id} answered {verdict!r}")
        elif layer.kind == "legacy":
            verdict = "allow" if self.by_name[layer.id].allows(sub, action) else "deny"
        else:
            verdict, recs = _ledger_verdict(self.state, layer, sub, action)
            for rid in recs:
                end = _terms(self.state, self.state.records[rid], sub, action, True)[0]
                if end is not None:
                    ends.append(end)
        passes = verdict == "allow" or (layer.kind == "restriction" and verdict == "silent")
        return (layer, action, verdict, passes, recs, ends)

    def _merge(self, row: tuple, sub: Use) -> None:
        layer, action, verdict, passes, recs, ends = row
        key = (layer.id, action)
        if key not in self.entries:
            self.entries[key] = (layer, action, verdict, passes, set(recs))
        else:       # the same (layer, action) over several objects: the first failing verdict, all records
            _, _, was, was_passes, held_recs = self.entries[key]
            keep = was_passes and not passes
            self.entries[key] = (layer, action, verdict if keep else was, was_passes and passes,
                                 held_recs | set(recs))
        self.ends.extend(ends)
        if not passes and self.failure is None:
            code = ("NO_LAYER" if verdict == "missing" else
                    "LEGACY_DENY" if layer.kind == "legacy" else "DENIED" if verdict == "deny" else
                    "NO_ALLOW" if layer.kind == "outside" else _silent_code(self.state, layer, sub, action))
            self.failure, self.failed_need = (code, layer.id, action), self.cur

    def _register(self, layers: Sequence[Layer]) -> None:
        for layer in layers:
            self.layer_pos.setdefault(layer.id, len(self.layer_pos))
            if layer.kind in ("consent", "restriction") and layer.id not in self._ledger_seen:
                self._ledger_seen.add(layer.id)
                self.ledger_layers.append(layer.id)
                self.versions[layer.id] = layer_version(self.state, layer.id)

    def process(self, sub: Use, actions: Sequence[str], subjects: tuple, *, bound: bool = False,
                gkey=None) -> bool:
        """Decide `actions` on sub.obj, each pair once. False when the object's own tests (a retired subject's
        home, no subject, more than 8 subjects or a name count past the bound) stop the decision (P 6.5 step 1)."""
        todo = [x for x in actions if (sub.obj, x) not in self.done]
        if not todo:
            return True
        code = ("RETIRED" if self._any_retired(subjects) else "NO_LAYER" if not subjects else
                "BOUND" if len(subjects) > MAX_SUBJECTS or bound else None)
        if code is not None:
            if self.failure is None:
                self.failure, self.failed_need = (code, None, None), self.cur
            return False
        self.done.update((sub.obj, x) for x in todo)
        shared = self._shared.get(gkey) if gkey is not None else None
        if shared is None:
            layers = required_layers(self.state, sub, legacy=self.legacy, outside=self.outside, subjects=subjects)
            self._register(layers)
            if gkey is not None:
                shared = self._shared[gkey] = (layers, set())
        else:
            layers = shared[0]
        # the actions whose ledger verdicts this object (or, in a group, an earlier one) has not yet made
        fresh = todo if shared is None else [x for x in todo if x not in shared[1]]
        if fresh:
            self.objs.append(sub.obj)
            self.read.setdefault(sub.obj, (sub, []))[1].extend(fresh)
        for layer in layers:
            ledger = layer.kind in ("consent", "restriction")
            for action in todo:
                if ledger and action not in fresh:
                    continue        # an object of the same group made this decision
                self._merge(self._row(layer, sub, action), sub)
        if shared is not None:
            shared[1].update(todo)
        return True

    def result(self) -> Decision:
        proto, state = self.proto, self.state
        order = sorted(self.entries.values(), key=lambda e: (self.layer_pos[e[0].id], ACTIONS.index(e[1])))
        cited = tuple(Cited(layer.id, layer.kind, action, verdict, tuple(sorted(recs, key=_units)))
                      for (layer, action, verdict, _, recs) in order)
        return Decision(allowed=self.failure is None, at=proto.at, ledger_seq=state.seq, action=proto.action,
                        cited=cited, refusal=None if self.failure is None else Refusal(*self.failure),
                        until=_until(state, proto.at, self.ends, self.ledger_layers, list(self.read.values())),
                        horizon=_horizon(state, proto.at, self.ledger_layers, self.objs),
                        versions=self.versions, multi=self.multi)

    def before_any_object(self) -> bool:
        """P 6.5 step 1, the tests on a, P, anc(P) and anc(H). False, with the failure set, when one fails."""
        state, use = self.state, self.proto
        if not _requester_ok(state, use):
            self.failure = ("UNKNOWN_REQUESTER", None, None)
            return False
        held = holding_place(state, use.copy)
        if place_retired(state, use.place) or (held is not None and place_retired(state, held)):
            self.failure = ("RETIRED", None, None)
            return False
        return True


def decide(state: State, use: Use, *, legacy: Sequence[LegacyLayer] = (),
           outside: Mapping | None = None) -> Decision:
    """P 6.5 steps 1 to 8. Every decision in need(u) is made, the
    object first, then the memories it names in ref order; the refusal is the first failing one. A use on a road
    or trail that names more than MAX_ANSWER_NAMES memories (the ones it shows are named ones) is refused with
    BOUND, after the object's own tests (P 6.4)."""
    multi = _kind_of(use.obj) in ("road", "trail")
    run = _Run(state, use, legacy, outside, multi=multi)
    if not run.before_any_object():
        return replace(run.result(), processed=0)
    over = multi and len(set(use.names) | set(use.shows)) > MAX_ANSWER_NAMES
    processed = 0
    for run.cur, need in enumerate(needs(use)):
        sub = use if need.obj == use.obj else replace(use, obj=need.obj, names=(), shows=frozenset())
        if not run.process(sub, need.actions, run.subjects(sub.obj, sub.names), bound=over and sub is use):
            break
        processed += 1
    return replace(run.result(), processed=processed, failed_need=run.failed_need)


def decide_bulk(state: State, bulk: BulkUse, *, legacy: Sequence[LegacyLayer] = (),
                outside: Mapping | None = None, group: bool = True) -> Decision:
    """P 6.4 "Bulk uses" and P 6.5 step 1's bulk order. The tests on a, P, anc(P) and anc(H) run once, then the
    size bounds (the objects, and the distinct memories their roads and trails name, counted up to the bound plus
    one), before any object. Then each object is decided in ref order by decide's per-object path with the bound
    of 32 waived, each (memory, action) pair once however many objects need it. The refusal is the first failing
    object's, and names no object. With `group`, the ledger layers' verdicts are shared by the objects that agree
    on what the pre-filtered records read (P 6.4, "How it is computed"); legacy and outside layers are still
    asked of every object."""
    if bulk.action not in _CLOSURE:
        raise RuleError("6.4 need", f"{bulk.action!r} is not an action")
    proto = Use(requester=bulk.requester, place=bulk.place, obj="", copy=bulk.copy, action=bulk.action,
                purpose=bulk.purpose, at=bulk.at)
    run = _Run(state, proto, legacy, outside, multi=True, group=group)
    if not run.before_any_object():
        return run.result()
    objects = sorted(set(bulk.objects), key=_units)
    if len(objects) > (MAX_BULK_NAMED if bulk.named else MAX_BULK_DERIVED):
        run.failure = ("BOUND", None, None)
        return run.result()
    named: set = set()
    for obj in objects:
        if _kind_of(obj) in ("road", "trail"):
            for m in bulk.names(obj):
                named.add(m)
                if len(named) > MAX_BULK_MEMORIES:
                    run.failure = ("BOUND", None, None)
                    return run.result()
    del named
    closure = _CLOSURE[bulk.action]
    for obj in objects:
        if _kind_of(obj) in ("road", "trail"):
            names = set(bulk.names(obj))
            ok = run.process(replace(proto, obj=obj), closure, run.subjects(obj, tuple(names)))
            fresh = sorted((m for m in names if (m, "recall") not in run.done), key=_units) if ok else ()
            for m in fresh:
                subjects = run.subjects(m)
                ok = run.process(replace(proto, obj=m), ("recall",), subjects,
                                 gkey=run.group_key(m, subjects) if group else None)
                if not ok:
                    break
        else:
            subjects = run.subjects(obj)
            ok = run.process(replace(proto, obj=obj), closure, subjects,
                             gkey=run.group_key(obj, subjects) if group and subjects else None)
        if not ok:
            break
    return run.result()


# ---------------------------------------------------------------- the eligible set and the legacy meet (P 12.2, L8)

@dataclass(frozen=True)
class Placement:
    """One placed copy of a house: the memory it holds, its source object (None for a row with no source) and the
    copy that serves it."""
    memory_id: str
    obj: str | None
    copy: str


@dataclass(frozen=True)
class EligibleSet:
    """What the ledger alone allows a requester to `action`, for the placements of one house. `decisions` is the
    ledger decision of each decidable object (the first refused one, if its copies differ); `horizon` is the
    earliest horizon among every decision made, or None. It holds from `at` until `horizon` (L8)."""
    memory_ids: frozenset
    decisions: Mapping[str, Decision]
    at: int
    horizon: int | None


def eligible_set(state: State, placements: Sequence[Placement], *, requester: str, place: str, purpose: str,
                 action: str, at: int) -> EligibleSet:
    """Decide `action` for each placement, with no legacy layer: the subjects', places', holding place's and
    restriction layers only. A memory is eligible when each of its placements has an object that can be decided
    and the decision allows it. The pre-filter of P 6.5 is made once per (layer, action) for the requester,
    place, purpose and time (`_prefilter` keeps it on the State), and each object is matched against those
    records alone."""
    decisions: dict[str, Decision] = {}
    made: dict[tuple, Decision | None] = {}
    horizons: list[int] = []
    for p in placements:
        if p.obj is None or (p.obj, p.copy) in made:
            continue
        u = Use(requester=requester, place=place, obj=p.obj, copy=p.copy, action=action, purpose=purpose, at=at)
        try:
            d = decide(state, u)
        except RuleError:
            made[(p.obj, p.copy)] = None
            continue
        made[(p.obj, p.copy)] = d
        prior = decisions.get(p.obj)
        if prior is None or (prior.allowed and not d.allowed):
            decisions[p.obj] = d
        if d.horizon is not None:
            horizons.append(d.horizon)
    ok: dict[str, bool] = {}
    for p in placements:
        d = None if p.obj is None else made[(p.obj, p.copy)]
        ok[p.memory_id] = ok.get(p.memory_id, True) and d is not None and d.allowed
    return EligibleSet(frozenset(m for m, good in ok.items() if good), decisions, at,
                       min(horizons) if horizons else None)


def meet_legacy(decision: Decision, use: Use, legacy: Sequence[LegacyLayer]) -> Decision:
    """A ledger decision made with no legacy layer, met with this request's legacy verdicts, each in its place
    in P 6.5 step 2's order (after the places' layers, before the agent's restriction layer, once for each need
    and action `decide` made): `allowed`, `refusal` and `cited` are what `decide(state, use, legacy=legacy)`
    gives, with the first refusal in that order. `until` and `horizon` are the ledger's and are unchanged (R7).
    `at` is the use's. Only a decision `decide` made carries what this needs."""
    if decision.processed is None:
        raise RuleError("6.5 legacy", "the decision was not made by decide, so it cannot be met with legacy layers")
    by_name: dict = {}
    for layer in legacy:
        by_name.setdefault(layer.name, layer)         # a layer is required once, by its name
    layers = list(by_name.values())
    if not layers or decision.processed == 0:
        return replace(decision, at=use.at)
    done: set = set()
    verdicts: dict = {}                       # (layer index, action) -> every call allowed
    first_fail = None                         # (position, layer, action) of the first legacy refusal
    for i, need in enumerate(needs(use)[:decision.processed]):
        sub = use if need.obj == use.obj else replace(use, obj=need.obj, names=(), shows=frozenset())
        todo = [x for x in need.actions if (sub.obj, x) not in done]
        done.update((sub.obj, x) for x in todo)
        for li, layer in enumerate(layers):
            for x in todo:
                allowed = bool(layer.allows(sub, x))
                verdicts[(li, x)] = verdicts.get((li, x), True) and allowed
                if not allowed and first_fail is None:
                    first_fail = ((i, 1 + li, ACTIONS.index(x)), layer.name, x)
    legacy_cited = tuple(Cited(layers[li].name, "legacy", x, "allow" if good else "deny", ())
                         for (li, x), good in sorted(verdicts.items(), key=lambda kv: (kv[0][0], ACTIONS.index(kv[0][1]))))
    cut = next((n for n, c in enumerate(decision.cited) if c.kind == "restriction"), len(decision.cited))
    cited = decision.cited[:cut] + legacy_cited + decision.cited[cut:]
    refusal, failed_need = decision.refusal, decision.failed_need
    if first_fail is not None:
        if refusal is None:
            ledger_pos = None
        elif refusal.layer is None:
            ledger_pos = (decision.failed_need, -1, 0)
        else:
            kind = next((c.kind for c in decision.cited if c.layer == refusal.layer and c.action == refusal.action),
                        "consent")
            ledger_pos = (decision.failed_need, 10 ** 6 if kind == "restriction" else 0, ACTIONS.index(refusal.action))
        if ledger_pos is None or first_fail[0] < ledger_pos:
            refusal, failed_need = Refusal("LEGACY_DENY", first_fail[1], first_fail[2]), first_fail[0][0]
    return replace(decision, at=use.at, allowed=refusal is None, cited=cited, refusal=refusal,
                   failed_need=failed_need)


# ---------------------------------------------------------------- overlaps between places: the gluing check (P 8)

REGISTRY = "registry"          # affected_joints: a change to places, parents, agents, groups, collections, stewards


class TooComplex(Exception):
    """A layer or section would hold more than BOX_CAP boxes."""


@dataclass(frozen=True)
class FSet:
    """A finite set of strings (co False) or the complement of one (co True)."""
    items: frozenset
    co: bool = False

    def __contains__(self, value) -> bool:
        return (value not in self.items) if self.co else (value in self.items)

    @property
    def empty(self) -> bool:
        return not self.co and not self.items

    def __and__(self, other: "FSet") -> "FSet":
        if not self.co and not other.co:
            return FSet(self.items & other.items)
        if not self.co:
            return FSet(self.items - other.items)
        if not other.co:
            return FSet(other.items - self.items)
        return FSet(self.items | other.items, True)

    def __invert__(self) -> "FSet":
        return FSet(self.items, not self.co)

    def __sub__(self, other: "FSet") -> "FSet":
        return self & ~other


FULL = FSet(frozenset(), True)


def _fset(values) -> FSet:
    return FSet(frozenset(values))


def _star(value) -> FSet:
    return FULL if value == STAR else _fset(value)


def _norm(intervals) -> tuple:
    spans = sorted((max(lo, 0), hi) for lo, hi in intervals if hi is None or hi > max(lo, 0))
    out: list = []
    for lo, hi in spans:
        if out and (out[-1][1] is None or lo <= out[-1][1]):
            if out[-1][1] is not None and (hi is None or hi > out[-1][1]):
                out[-1] = (out[-1][0], hi)
        else:
            out.append((lo, hi))
    return tuple(out)


@dataclass(frozen=True)
class TimeSet:
    """A finite union of half-open integer intervals [lo, hi); hi None is unbounded. Times start at 0."""
    intervals: tuple = ()

    @classmethod
    def of(cls, intervals) -> "TimeSet":
        return cls(_norm(intervals))

    def __contains__(self, t: int) -> bool:
        return any(lo <= t and (hi is None or t < hi) for lo, hi in self.intervals)

    @property
    def empty(self) -> bool:
        return not self.intervals

    def __and__(self, other: "TimeSet") -> "TimeSet":
        out = []
        for lo, hi in self.intervals:
            for lo2, hi2 in other.intervals:
                a = max(lo, lo2)
                b = hi2 if hi is None else hi if hi2 is None else min(hi, hi2)
                if b is None or a < b:
                    out.append((a, b))
        return TimeSet.of(out)

    def __invert__(self) -> "TimeSet":
        out, cursor = [], 0
        for lo, hi in self.intervals:
            if lo > cursor:
                out.append((cursor, lo))
            if hi is None:
                return TimeSet.of(out)
            cursor = hi
        out.append((cursor, None))
        return TimeSet.of(out)

    def __sub__(self, other: "TimeSet") -> "TimeSet":
        return self & ~other


TIME_FULL = TimeSet(((0, None),))
DIMS = ("place", "agent", "kind", "store", "layer", "lane", "memory", "action", "purpose", "time")


@dataclass(frozen=True)
class Box:
    """A product of one set per dimension (P 8). A point is a tuple in DIMS order."""
    place: FSet = FULL
    agent: FSet = FULL
    kind: FSet = FULL
    store: FSet = FULL
    layer: FSet = FULL
    lane: FSet = FULL
    memory: FSet = FULL
    action: FSet = FULL
    purpose: FSet = FULL
    time: TimeSet = TIME_FULL

    @classmethod
    def full(cls) -> "Box":
        return cls()

    def but(self, **dims) -> "Box":
        return replace(self, **dims)


def box_empty(b: Box) -> bool:
    return any(getattr(b, d).empty for d in DIMS)


def box_and(a: Box, b: Box) -> Box | None:
    dims = {d: getattr(a, d) & getattr(b, d) for d in DIMS}
    if any(v.empty for v in dims.values()):
        return None
    return Box(**dims)


def box_minus(a: Box, b: Box) -> list[Box]:
    """a \\ b as at most 10 disjoint boxes."""
    if box_empty(a):
        return []
    if box_and(a, b) is None:
        return [a]
    pieces, cur = [], a
    for d in DIMS:
        left = getattr(cur, d) - getattr(b, d)
        if not left.empty:
            pieces.append(replace(cur, **{d: left}))
        cur = replace(cur, **{d: getattr(cur, d) & getattr(b, d)})
    return pieces


def box_subset(a: Box, b: Box) -> bool:
    return box_empty(a) or all((getattr(a, d) - getattr(b, d)).empty for d in DIMS)


def box_contains(box: Box, point) -> bool:
    return all(v in getattr(box, d) for d, v in zip(DIMS, point))


def _cap(boxes: Iterable[Box]) -> list[Box]:
    out = list(dict.fromkeys(b for b in boxes if not box_empty(b)))
    if len(out) > BOX_CAP:
        raise TooComplex(f"more than {BOX_CAP:,} boxes")
    return out


def _list_and(xs: Sequence[Box], ys: Sequence[Box]) -> list[Box]:
    return _cap(c for x in xs for y in ys if (c := box_and(x, y)) is not None)


def _list_minus(xs: Sequence[Box], ys: Sequence[Box]) -> list[Box]:
    cur = list(xs)
    for y in ys:
        cur = _cap(p for x in cur for p in box_minus(x, y))
        if not cur:
            break
    return cur


def _only(boxes: Sequence[Box], **dims) -> list[Box]:
    return _list_and(boxes, [Box(**dims)])


def _row_times(state: State, added: int, removed: int | None, anchor: int | None) -> TimeSet:
    """When a membership row counts: for an allow (anchor None) while in force; for a deny from the later of
    its start and the record's anchor, if it did not end by the anchor."""
    lo, hi = _span(state, added, removed)
    if anchor is None:
        return TimeSet.of([(lo, hi)])
    if hi is not None and hi <= anchor:
        return TimeSet()
    return TimeSet.of([(max(anchor, lo), None)])


def _by_time(rows: Iterable[tuple[TimeSet, str]]) -> list[tuple[TimeSet, FSet]]:
    grouped: dict = {}
    for ts, value in rows:
        if not ts.empty:
            grouped.setdefault(ts, set()).add(value)
    return [(ts, _fset(v)) for ts, v in grouped.items()]


def _audience_boxes(state: State, v: str, layer: str, anchor: int, deny: bool,
                    at_place: str | None) -> list[tuple[FSet, FSet, TimeSet]]:
    """(places, agents, times) of one audience entry, read as 5.2 and 5.3 read it at the current state. An
    unregistered agent matches `commons` only."""
    where = FULL if at_place is None else _fset([at_place])
    candidates = list(state.places) if at_place is None else [at_place]
    places = lambda ok: _fset(x for x in candidates if ok(x))
    acts = {a: row.acts_for for a, row in state.agents.items()}
    if v == "commons":
        return [(where, FULL, TIME_FULL)]
    layer_place = layer if layer.startswith("place:") else acts.get(layer)
    if v == "self":
        if layer.startswith("agent:"):
            return [(where, _fset([layer]), TIME_FULL)] if layer in state.agents else []
        if layer_place is None:
            return []
        who = _fset(a for a, p in acts.items() if p == layer_place)
        if deny:
            return [(where, who, TIME_FULL)]
        return [(places(lambda x: layer_place in dominators(state, x)), who, TIME_FULL)]
    if v.startswith("group:"):
        rows = [r for r in state.group_members.get(v, ()) if r.agent in state.agents]
        if not deny:
            rows = [r for r in rows if r.removed_seq is None]        # a removed membership never counts (P 6.5)
        if deny:
            return [(where, ag, ts) for ts, ag in _by_time(
                (_row_times(state, r.added_seq, r.removed_seq, anchor), r.agent) for r in rows)]
        group = state.groups.get(v)
        if group is None:
            return []
        home = home_of(group.owner)
        ok = places(lambda x: home in dominators(state, x))
        return [(ok, ag, ts) for ts, ag in _by_time(
            (_row_times(state, r.added_seq, r.removed_seq, None), r.agent) for r in rows)]
    if v.startswith("place:"):
        if not deny:
            return [(places(lambda x: v in dominators(state, x)),
                     _fset(a for a, p in acts.items() if v in dominators(state, p)), TIME_FULL)]
        out = [(places(lambda x: v in ancestors(state, x)), FULL, TIME_FULL),
               (where, _fset(a for a, p in acts.items() if v in ancestors(state, p)), TIME_FULL)]
        placed = [(_row_times(state, r.added_seq, r.removed_seq, anchor), a)
                  for a, rows in state.agent_places.items() if a in state.agents
                  for r in rows if v in ancestors(state, r.place)]
        out += [(where, ag, ts) for ts, ag in _by_time(placed)]
        return [o for o in out if not o[0].empty and not o[1].empty]
    return []


def _grant_times(state: State, gid: str) -> TimeSet:
    """When the grant chain is valid (grant_validity at each t): never past the earliest expiry."""
    try:
        chain = grant_chain(state, gid)
    except RuleError:
        return TimeSet()
    if len(chain) > MAX_GRANT_LINKS or any(g.revoked_seq is not None for g in chain):
        return TimeSet()
    if not _is_steward(state, chain[0].layer, chain[0].issuer):
        return TimeSet()
    return TimeSet.of([(0, min(g.expires for g in chain))])


def _member_parts(state: State, colls: tuple, layer: str, anchor: int, deny: bool, assume: frozenset,
                  at_place: str | None) -> list[tuple[FSet, TimeSet, list[Box] | None]]:
    """The memories a collections list names, as (refs, times, extra boxes the use must also lie in). An allow
    counts a membership not removed and in force; a grant-backed one only while its chain is valid and inside
    every envelope of that chain. A deny counts every membership since its anchor (P 5.3)."""
    simple: list[tuple[TimeSet, str]] = []
    parts: list = []
    for c in colls:
        for r in state.collection_members.get(c, ()):
            if deny:
                simple.append((_row_times(state, r.added_seq, r.removed_seq, anchor), r.object))
                continue
            if r.removed_seq is not None:
                continue                 # a removed membership is never counted for an allow
            times = _row_times(state, r.added_seq, r.removed_seq, None)
            if not r.backing.startswith("grant:") or r in assume:
                simple.append((times, r.object))
                continue
            gid = r.backing[len("grant:"):]
            times = times & _grant_times(state, gid)
            if times.empty:
                continue
            try:
                chain = grant_chain(state, gid)
            except RuleError:
                continue
            extra = [Box.full()]
            for g in chain:
                extra = _list_and(extra, _selector_boxes(state, g.envelope, layer, anchor, False, assume | {r},
                                                         at_place))
            if extra:
                parts.append((_fset([r.object]), times, extra))
    return [(refs, ts, None) for ts, refs in _by_time(simple)] + parts


def _selector_boxes(state: State, sel: Selector, layer: str, anchor: int, deny: bool, assume: frozenset,
                    at_place: str | None) -> list[Box]:
    lanes = FULL if sel.lanes == STAR else _fset(sel.lanes)
    if deny and sel.lanes != STAR:
        lanes = _fset([*sel.lanes, "pending", "none"])      # a pending move or no note reads as every lane
    base = Box(agent=_star(sel.requesters), kind=_star(sel.kinds), store=_star(sel.stores),
               layer=_star(sel.layers), lane=lanes, memory=_star(sel.memories), action=_star(sel.actions),
               purpose=_star(sel.purposes))
    parts = ([(FULL, TIME_FULL, None)] if sel.collections == STAR
             else _member_parts(state, sel.collections, layer, anchor, deny, assume, at_place))
    out: list[Box] = []
    for v in sel.audience:
        for places, agents, times in _audience_boxes(state, v, layer, anchor, deny, at_place):
            for refs, part_times, extra in parts:
                box = box_and(base, Box(place=places, agent=agents, memory=refs, time=times & part_times))
                if box is None:
                    continue
                if extra is None:
                    out.append(box)
                else:
                    out.extend(c for e in extra if (c := box_and(box, e)) is not None)
                if len(out) > BOX_CAP:
                    out = _cap(out)
    return _cap(out)


def _interval(record) -> TimeSet:
    return TimeSet.of([(record.valid_from, record.valid_until)])


def _record_boxes(state: State, record: Record, at_place: str | None) -> list[Box]:
    """P 5.3 rules 1 to 5 as boxes: interval, selector, the replaces chain, the grant chain."""
    deny = record.effect == "deny"
    cur = _selector_boxes(state, record.selector, record.layer, record.anchor, deny, frozenset(), at_place)
    cur = _only(cur, time=_interval(record))
    link, n = record.replaces, 0
    while link is not None and cur:
        n += 1
        r = state.records.get(link)
        if r is None or n > MAX_REPLACES:
            return []
        cur = _only(cur, time=_interval(r))
        cur = _list_and(cur, _selector_boxes(state, r.selector, r.layer, record.anchor, deny, frozenset(),
                                             at_place))
        link = r.replaces
    if cur and record.backing.startswith("grant:"):
        gid = record.backing[len("grant:"):]
        cur = _only(cur, time=_grant_times(state, gid))
        try:
            chain = grant_chain(state, gid)
        except RuleError:
            return []
        for g in chain:
            if not cur:
                break
            cur = _list_and(cur, _selector_boxes(state, g.envelope, record.layer, record.anchor, deny,
                                                 frozenset(), at_place))
    return cur


def layer_boxes(state: State, layer: str, *, at_place: str | None = None) -> list[Box]:
    """What the layer allows, as boxes: its allows minus its denies, at the current state. With at_place, only
    the uses at that place. Raises TooComplex past BOX_CAP."""
    def compute():
        allows: list[Box] = []
        denies: list[Box] = []
        for rec in state.records.values():
            if rec.layer != layer or rec.revoked_seq is not None:
                continue
            (denies if rec.effect == "deny" else allows).extend(_record_boxes(state, rec, at_place))
            if len(allows) > BOX_CAP:
                allows = _cap(allows)
            if len(denies) > BOX_CAP:
                denies = _cap(denies)
        return tuple(_list_minus(_cap(allows), _cap(denies)))
    return list(state._memo(("lbox", layer, at_place), compute))


def stewards(state: State, *places: str) -> frozenset[str]:
    """The persons who steward any of the places now."""
    return frozenset(r.person for p in places for r in state.place_stewards.get(p, ())
                     if r.removed_seq is None)


@dataclass(frozen=True)
class GluingReport:
    place: str
    delta: tuple
    ineffective: tuple
    too_complex: bool
    notify: frozenset


def _ever(boxes: Sequence[Box]) -> list[Box]:
    """The same boxes at every time: a use class allowed at some time. A parent's rule that merely ends does
    not make the place's own rule ineffective; only what no parent ever allows does (ruling, P 13 use 5)."""
    return _cap(b.but(time=TIME_FULL) for b in boxes)


def _distinct_parents(state: State, place: str) -> list[str]:
    return sorted(set(_parents(state, place)))


def _sections(state: State, joint: str) -> tuple[list[Box], list[list[Box]]]:
    """own(J), and s_i for each parent Q_i: the meet of anc(Q_i)'s layers at J."""
    own = layer_boxes(state, joint, at_place=joint)
    secs = []
    for q in _distinct_parents(state, joint):
        s = [Box.full()]
        for z in sorted(ancestors(state, q)):
            s = _list_and(s, layer_boxes(state, z, at_place=joint))
            if not s:
                break
        secs.append(s)
    return own, secs


def _analyse(state: State, place: str, want_delta: bool) -> GluingReport:
    parents = _distinct_parents(state, place)
    try:
        delta: list[Box] = []
        ineff: list[Box] = []
        secs: list[list[Box]] = []
        if len(parents) >= 2:
            own, secs = _sections(state, place)
            union = _cap(b for s in secs for b in s)
            ineff = _list_minus(own, _ever(union))
            if want_delta:
                meet = secs[0]
                for s in secs[1:]:
                    meet = _list_and(meet, s)
                delta = _list_and(own, _list_minus(union, meet))
        elif len(parents) == 1:
            own = layer_boxes(state, place, at_place=place)
            meet = [Box.full()]
            for z in sorted(ancestors(state, place) - {place}):
                meet = _list_and(meet, layer_boxes(state, z, at_place=place))
                if not meet:
                    break
            ineff = _list_minus(own, _ever(meet))
    except TooComplex:
        return GluingReport(place, (), (), True, stewards(state, place, *parents))
    notify = frozenset()
    if delta:
        # P 8: the stewards of J and of each parent whose chain refuses part of Δ, not one that allows all of it
        refusing = [q for q, sec in zip(parents, secs) if _list_minus(delta, sec)]
        notify |= stewards(state, place, *refusing)
    if ineff:
        notify |= stewards(state, place)
    return GluingReport(place, tuple(delta), tuple(ineff), False, notify)


def gluing(state: State, joint: str) -> GluingReport:
    """P 8: Δ(J) and the ineffective part of J's own rules, with who is told."""
    return _analyse(state, joint, True)


def ineffective(state: State, place: str) -> GluingReport:
    """P 8: the part of the place's own rules that the places above it do not allow."""
    return _analyse(state, place, False)


def affected_joints(state: State, changed: Iterable[str]) -> tuple[str, ...]:
    """The joint places to check after a change: those whose own layer, a parent's or an ancestor's changed, or
    all of them after a REGISTRY change, in id order. The caller takes the first JOINTS_PER_CHANGE."""
    changed = set(changed)
    joints = sorted(p for p in state.places if len(_distinct_parents(state, p)) >= 2
                    and not place_retired(state, p))
    if REGISTRY in changed:
        return tuple(joints)
    return tuple(j for j in joints if ancestors(state, j) & changed)


def _name(state: State, place: str) -> str:
    return state.names.get(place, place)


def _and_list(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _action_values(boxes: Sequence[Box]) -> list[str]:
    return [a for a in ACTIONS if any(a in b.action for b in boxes)]


def _purposes(boxes: Sequence[Box]) -> str:
    if any(b.purpose.co for b in boxes):
        return "any purpose"
    return _and_list(sorted({p for b in boxes for p in b.purpose.items}, key=_units))


def disagreement_words(state: State, report: GluingReport) -> str:
    """The sentence of P 8 for the stewards ("" when there is nothing to say)."""
    place = report.place
    here = _name(state, place)
    if report.too_complex:
        return (f"could not check: too complex to compare {here} with the places above it "
                f"(more than {BOX_CAP:,} boxes). The meet still decides every use.")
    out = []
    if report.delta:
        own, secs = _sections(state, place)
        parents = _distinct_parents(state, place)
        allow = [_name(state, q) for q, s in zip(parents, secs) if _list_and(report.delta, s)]
        refuse = [_name(state, q) for q, s in zip(parents, secs) if _list_minus(report.delta, s)]
        meet = own
        for s in secs:
            meet = _list_and(meet, s)
        left = _action_values(meet)
        only = f"may only {_and_list(left)}" if left else "may do nothing"
        out.append(f"{_and_list(allow)} {'allows' if len(allow) == 1 else 'allow'} "
                   f"{_and_list(_action_values(report.delta))} in {here} for {_purposes(report.delta)}; "
                   f"{_and_list(refuse)} {'does' if len(refuse) == 1 else 'do'} not. "
                   f"Until one of you changes your rules, {here} {only}.")
    if report.ineffective:
        out.append(f"{here} asks for {_and_list(_action_values(report.ineffective))} in {here} for "
                   f"{_purposes(report.ineffective)} that the places above it do not allow, so that part has "
                   f"no effect.")
    return " ".join(out)


# ---------------------------------------------------------------- write rules (P 5.4)

def _acts_for_person(state: State, agent: str, person: str) -> bool:
    row = state.agents.get(agent)
    return row is not None and row.acts_for == home_of(person)


def is_inside_home(state: State, layer: str, selector: Selector) -> bool:
    """P 5.4: every audience entry is `self`, a group of the person's own agents, or a place the home dominates.
    Only a home layer has an inside."""
    person = person_of_home(layer)
    if person is None:
        return False
    for v in selector.audience:
        if v == "self":
            continue
        if v.startswith("group:"):
            group = state.groups.get(v)
            if group is None or group.owner != person:
                return False
            if any(not _acts_for_person(state, m.agent, person)
                   for m in state.group_members.get(v, ()) if m.removed_seq is None):
                return False
        elif not (v.startswith("place:") and v in state.places and layer in dominators(state, v)):
            return False
    return True


def _effective_count(state: State, layer: str, at: int, skip: set) -> int:
    return sum(1 for r in state.records.values()
               if r.layer == layer and r.id not in skip and r.revoked_seq is None
               and (r.valid_until is None or r.valid_until > at))


def check_record(state: State, record: Record) -> None:
    """P 5.4 for a record about to be written: the interval, the bound of 256 effective records in its layer, and
    for an outside-home allow in a home layer the purposes, the 366 days and the two shapes of P28. A deny may
    have a null end anywhere; a place's layer has no lifetime rule."""
    rule = "5.4 validity rules"
    sel = record.selector
    if record.effect not in ("allow", "deny"):
        raise RuleError(rule, f"a record is an allow or a deny, not {record.effect!r}")
    if record.layer.startswith("agent:"):
        if record.layer not in state.agents:
            raise RuleError(rule, f"{record.layer} is not a registered agent")
    elif record.layer not in state.places:
        raise RuleError(rule, f"{record.layer} is not a registered place")
    if record.valid_until is not None and record.valid_until <= record.valid_from:
        raise RuleError(rule, "valid_until must be after valid_from")
    skip = {record.id} | ({record.replaces} if record.replaces else set())
    if _effective_count(state, record.layer, record.created, skip) >= MAX_RECORDS_PER_LAYER:
        raise RuleError(rule, f"a layer holds at most {MAX_RECORDS_PER_LAYER} effective records")
    if record.effect != "allow" or person_of_home(record.layer) is None:
        return
    if is_inside_home(state, record.layer, sel):
        return
    if sel.purposes == STAR:
        raise RuleError(rule, "an outside-home allow needs a finite purposes list (P13)")
    if record.valid_until is None or record.valid_until - record.valid_from > OUTSIDE_HOME_DAYS * 86400:
        raise RuleError(rule, f"an outside-home allow ends at most {OUTSIDE_HOME_DAYS} days after it starts (P13)")
    memory_shape = sel.kinds != STAR and set(sel.kinds) == {"memory"} and (
        sel.memories != STAR or sel.collections != STAR)
    road_shape = sel.kinds != STAR and set(sel.kinds) <= {"road", "trail"} and sel.stores != STAR
    if not (memory_shape or road_shape):
        raise RuleError(rule, "P28: an outside-home allow names memories by a finite memories or collections "
                              "list, or roads and trails by a finite stores list")


def check_new_subject(state: State, obj: str, subject: str) -> None:
    """P 5.4 and 7.4: at most 8 of the object's own subjects. Its copies never refuse it."""
    own = _own_subjects(state, obj)
    if subject not in own and len(own) + 1 > MAX_SUBJECTS:
        raise RuleError("5.4 validity rules", f"an object has at most {MAX_SUBJECTS} subjects")


def check_new_members(state: State, collection: str, count: int) -> None:
    """P 5.4: at most 100,000 members per collection."""
    held = {r.object for r in state.collection_members.get(collection, ()) if r.removed_seq is None}
    if len(held) + count > MAX_COLLECTION:
        raise RuleError("5.4 validity rules", f"a collection holds at most {MAX_COLLECTION:,} members")


def _record_region(state: State, rec: Record) -> list[Box]:
    return _only(_selector_boxes(state, rec.selector, rec.layer, rec.anchor, rec.effect == "deny", frozenset(),
                                 None), time=_interval(rec))


def check_narrower(state: State, new: Record, old: Record) -> None:
    """P 7.1: a replacement lies inside the record it replaces, in selector and in interval (box subset)."""
    rule = "7.1 narrowing"
    if new.layer != old.layer or new.effect != old.effect:
        raise RuleError(rule, "a replacement keeps its layer and its effect")
    try:
        outside = _list_minus(_record_region(state, new), _record_region(state, old))
    except TooComplex:
        raise RuleError(rule, "too complex to compare a replacement with its record") from None
    if outside:
        raise RuleError(rule, "a replacement lies within the record it replaces, in selector and interval")


def within_envelopes(state: State, selector: Selector, valid_from: int, valid_until: int | None,
                     grant_id: str) -> bool:
    """P 7.2: the selector lies in the envelope of the grant and of every grant above it, and a finite lifetime
    is at most each link's `max_days`. A null end is judged by the caller (a deny may have one)."""
    try:
        chain = grant_chain(state, grant_id)
    except RuleError:
        return False
    for g in chain:
        if not selector_within(state, selector, g.envelope):
            return False
        if valid_until is not None and valid_until - valid_from > g.max_days * 86400:
            return False
    return True


def placement_audience(state: State, record: Record | None, legacy_audience: str | None = None) -> str:
    """P 12.1's mapping to a `shared_memories.audience` the legacy checks accept."""
    if record is None:
        if legacy_audience is None:
            raise RuleError("12.1 placement audience", "a placement with no record needs its legacy audience")
        return legacy_audience
    aud = record.selector.audience
    if len(aud) == 1 and aud[0].startswith("group:"):
        return aud[0]
    home = record.layer
    if person_of_home(home) is not None and all(
            v == "self" or (v.startswith("place:") and v in state.places and home in dominators(state, v))
            for v in aud):
        return "commons"
    return RESERVED_GROUP


def _entry_covers(state: State, entry: str, audience: str, layer: str) -> bool:
    """Does one selector audience entry reach `audience`: the same entry, `commons`, `self` for the layer's own
    home place, or a place that dominates the audience place."""
    if entry == audience or entry == "commons":
        return True
    if entry == "self":
        return audience == layer
    return entry.startswith("place:") and audience.startswith("place:") and entry in dominators(state, audience)


def _cover_probe(owner: str, obj: str, at: int) -> Use:
    return Use(requester=owner, place=home_of(owner), obj=obj, copy="store:share-cover", action="recall",
               purpose="share-cover", at=at)


def _counts_for_share(state: State, r: Record, layer: str, at: int, probe: Use) -> bool:
    """Is `r` an effective allow in `layer` that covers the probe's object for `recall`, `read` and
    `inject_context`? Everything `share_cover` asks of a record except its audience."""
    sel = r.selector
    if (r.layer != layer or r.effect != "allow" or _revoked(state, r) or not _in_interval(r, at)
            or not all(_star_or_in(sel.actions, a) for a in ("recall", "read", "inject_context"))):
        return False
    try:
        if r.backing.startswith("grant:") and not grant_validity(state, r.backing[len("grant:"):], at)[0]:
            return False
        return bool(_object_dims(state, sel, layer, r.anchor, probe, "recall", False, frozenset(), True))
    except RuleError:
        return False


def _share_rank(state: State, r: Record):
    end = effective_end(state, r, [])
    return (end is not None, -(end or 0), _units(r.id))


def placement_still_counts(state: State, record_id: str, *, owner: str, obj: str, at: int) -> bool:
    """P 10: does the record a placement is linked to still count as an effective allow covering `obj`?"""
    r = state.records.get(record_id)
    return r is not None and _counts_for_share(state, r, home_of(owner), at, _cover_probe(owner, obj, at))


def relink_cover(state: State, *, old_id: str, owner: str, obj: str, audience: str, at: int) -> str | None:
    """P 10, P29: another effective allow of the same layer that covers `obj`, reaches every audience entry the
    old record reached, and maps to the same placement `audience` (`placement_audience`); chosen as `share_cover`
    chooses. None when there is none (or the old record is unknown)."""
    old = state.records.get(old_id)
    if old is None:
        return None
    layer = home_of(owner)
    probe = _cover_probe(owner, obj, at)
    wanted = [layer if e == "self" else e for e in old.selector.audience]
    found = [r for r in state.records.values()
             if r.id != old_id and _counts_for_share(state, r, layer, at, probe)
             and placement_audience(state, r) == audience
             and all(any(_entry_covers(state, e, w, layer) for e in r.selector.audience) for w in wanted)]
    return min(found, key=lambda r: _share_rank(state, r)).id if found else None


def share_cover(state: State, *, owner: str, obj: str, audience: str, at: int) -> str | None:
    """P 12.1: the id of an effective allow in the owner's home layer that covers `obj` for `recall`, `read` and
    `inject_context`, for some purpose and for `audience` (a `place:` or `group:` ref), chosen as `decide` chooses
    (latest effective end, a null end first, then the smallest id); else None. It is a structural check of the
    record, its grant and its memberships; `decide` at each use is still the authority."""
    layer = home_of(owner)
    probe = _cover_probe(owner, obj, at)
    found = [r for r in state.records.values()
             if any(_entry_covers(state, e, audience, layer) for e in r.selector.audience)
             and _counts_for_share(state, r, layer, at, probe)]
    if not found:
        return None
    return min(found, key=lambda r: _share_rank(state, r)).id


# ---------------------------------------------------------------- who may set what (P 4.4, 7.1, 7.2, 7.6)

CHANNELS = ("terminal", "tool", "migration")
_RULE = "7.1 who may set what"
# P 7.6's table: the acts that can widen. Done person-backed, each needs the person's yes.
WIDENING_ACTS = frozenset({
    "allow", "revoke-deny", "shorten-deny", "narrow-deny", "grant", "collect", "group", "register-agent",
    "put-agent", "add-steward", "register-place", "add-parent", "register-store", "remove-subject", "gate"})


@dataclass(frozen=True)
class Act:
    """One change a caller asks for. `kind` is a row of P 7.1 or 4.4 and `args` its arguments."""
    kind: str
    args: Mapping[str, object]


@dataclass(frozen=True)
class Authority:
    """outcome `do` or `proposal`; backing `person` or `grant:<id>`; under_grant the grant that was used."""
    outcome: str
    backing: str
    under_grant: str | None = None


_DO = Authority("do", "person", None)
_PROPOSAL = Authority("proposal", "person", None)
_OWN = Authority("do", "person", None)      # an agent's act in its own restriction layer: it only narrows (P 7.1)


def _refuse(why: str) -> RuleError:
    return RuleError(_RULE, why)


def _arg(args: Mapping, key: str):
    if key not in args:
        raise _refuse(f"the act needs {key}")
    return args[key]


def _as_selector(v) -> Selector:
    return v if isinstance(v, Selector) else parse_selector(v)


def _record_arg(state: State, args: Mapping, effect: str) -> Record:
    rec = state.records.get(_arg(args, "record"))
    if rec is None:
        raise _refuse(f"{args['record']} is not a record")
    if rec.revoked_seq is not None:
        raise _refuse(f"{rec.id} is already revoked")
    if rec.effect != effect:
        raise _refuse(f"{rec.id} is not an {effect}" if effect == "allow" else f"{rec.id} is not a deny")
    return rec


def _principals(state: State, agent: str) -> frozenset[str]:
    """The persons an agent acts for: the person whose home it acts for, or the stewards of the place."""
    row = state.agents.get(agent)
    if row is None:
        return frozenset()
    owner = person_of_home(row.acts_for)
    return frozenset({owner}) if owner else stewards(state, row.acts_for)


def _layer_steward(state: State, person: str, layer: str) -> bool:
    if layer.startswith("agent:"):
        return person in _principals(state, layer)
    return layer in state.places and _is_steward(state, layer, person)


def _store_owner(state: State, ref: str) -> str | None:
    try:
        store = state.stores.get(parse_object_ref(ref).instance_id)
    except RuleError:
        return None
    return None if store is None else store.owner


def _collection_layer(state: State, cid: str) -> str:
    row = state.collections.get(cid)
    owner = row.owner if row is not None else "person:" + cid.split(":", 1)[1].split("/")[0]
    return home_of(owner)


def _object_meets(state: State, ref: str, sel: Selector) -> bool:
    """Does the memory lie in the selector's object dimensions?"""
    try:
        parsed = parse_object_ref(ref)
    except RuleError:
        return False
    if not (_star_or_in(sel.kinds, parsed.kind) and _star_or_in(sel.stores, parsed.instance_id)):
        return False
    if sel.layers != STAR and parsed.layer not in sel.layers:
        return False
    if sel.memories != STAR and ref not in sel.memories:
        return False
    return sel.collections == STAR or any(
        r.collection in sel.collections and r.removed_seq is None for r in state.member_of.get(ref, ()))


def _meets_envelope(state: State, rec: Record, env: Selector) -> bool:
    """P 7.2: the record's selector and the envelope intersect."""
    try:
        return bool(_list_and(_record_region(state, rec._replace(valid_until=None, valid_from=0)),
                              _only(_selector_boxes(state, env, rec.layer, rec.anchor, False, frozenset(), None))))
    except TooComplex:
        return False


def _covering(state: State, actor: str, op: str, layer: str, at: int, args: Mapping, check) -> str | None:
    """A valid grant of the actor in `layer` with `op` whose chain satisfies check(grant_id, chain)."""
    given = args.get("grant")
    for gid in sorted(state.grants):
        row = state.grants[gid]
        if row.grantee != actor or row.layer != layer or (given is not None and gid != given):
            continue
        if op not in _grant_of(row).ops or not grant_validity(state, gid, at)[0]:
            continue
        if check(gid, grant_chain(state, gid)):
            return gid
    return None


def _a_allow(state, actor, agent, args, at):
    layer, sel = _arg(args, "layer"), _as_selector(_arg(args, "selector"))
    vf, vu = _arg(args, "valid_from"), args.get("valid_until")
    if not agent and _layer_steward(state, actor, layer):
        return _DO
    if not agent:
        raise _refuse(f"{actor} is not a steward of {layer}")
    gid = _covering(state, actor, "share", layer, at, args,
                    lambda g, _c: vu is not None and within_envelopes(state, sel, vf, vu, g))
    return Authority("do", f"grant:{gid}", gid) if gid else _PROPOSAL


def _a_deny(state, actor, agent, args, at):
    layer, sel = _arg(args, "layer"), _as_selector(_arg(args, "selector"))
    if not agent:
        if _layer_steward(state, actor, layer):
            return _DO
        raise _refuse(f"{actor} is not a steward of {layer}")
    if layer == actor:                       # its own restriction layer
        return _OWN
    gid = _covering(state, actor, "deny", layer, at, args,
                    lambda g, _c: within_envelopes(state, sel, _arg(args, "valid_from"), None, g))
    if gid:
        return Authority("do", "person", gid)    # a deny an agent writes under a grant is person-backed (P 7.3)
    raise _refuse(f"{actor} may add a deny only in its own restriction layer, or under a grant")


def _replacement(state: State, rec: Record, args: Mapping, kind: str) -> Record:
    new = rec
    if kind in ("shorten", "shorten-deny"):
        new = new._replace(valid_until=_arg(args, "valid_until"))
    else:
        new = new._replace(selector=_as_selector(_arg(args, "selector")))
        if "valid_until" in args:
            new = new._replace(valid_until=args["valid_until"])
    check_narrower(state, new, rec)
    return new


def _a_edit_allow(kind):
    op = kind

    def handler(state, actor, agent, args, at):
        rec = _record_arg(state, args, "allow")
        if kind != "withdraw":
            _replacement(state, rec, args, kind)
        keeps = "person" if kind == "withdraw" else rec.backing
        if not agent:
            if _layer_steward(state, actor, rec.layer):
                return Authority("do", keeps, None)
            raise _refuse(f"{actor} is not a steward of {rec.layer}")
        gid = _covering(state, actor, op, rec.layer, at, args,
                        lambda g, chain: all(_meets_envelope(state, rec, c.envelope) for c in chain))
        if gid:
            return Authority("do", keeps, gid)
        if kind == "withdraw":
            if rec.set_by == actor and rec.backing.startswith("grant:"):
                return _DO
            raise _refuse(f"{actor} may withdraw only grant-backed allows it wrote, or under a grant")
        return _PROPOSAL
    return handler


def _a_edit_deny(kind):
    def handler(state, actor, agent, args, at):
        rec = _record_arg(state, args, "deny")
        if kind != "revoke-deny":
            _replacement(state, rec, args, kind)
        if not agent:
            if _layer_steward(state, actor, rec.layer):
                return _DO
            raise _refuse(f"{actor} is not a steward of {rec.layer}")
        return _OWN if rec.layer == actor else _PROPOSAL     # P27: a deny in a consent layer is a steward's act
    return handler


def _a_collect(state, actor, agent, args, at):
    cid = _arg(args, "collection")
    layer = _collection_layer(state, cid)
    if not agent:
        if _layer_steward(state, actor, layer):
            return _DO
        raise _refuse(f"{actor} is not a steward of {layer}")

    def inside(_g, chain):
        return all(selector_within(state, r.selector, c.envelope)
                   for r in state.records.values() if r.effect == "allow" and r.revoked_seq is None
                   and r.selector.collections != STAR and cid in r.selector.collections for c in chain)
    gid = _covering(state, actor, "collect", layer, at, args, inside)
    return Authority("do", f"grant:{gid}", gid) if gid else _PROPOSAL


def _a_uncollect(state, actor, agent, args, at):
    cid, objects = _arg(args, "collection"), list(_arg(args, "objects"))
    layer = _collection_layer(state, cid)
    if not agent:
        if _layer_steward(state, actor, layer):
            return _DO
        raise _refuse(f"{actor} is not a steward of {layer}")
    gid = _covering(state, actor, "uncollect", layer, at, args,
                    lambda g, chain: all(_object_meets(state, o, c.envelope) for o in objects for c in chain))
    return Authority("do", "person", gid) if gid else _PROPOSAL


def _a_add_subject(state, actor, agent, args, at):
    owner = _store_owner(state, _arg(args, "object"))
    if owner is None:
        raise _refuse(f"{args['object']} names no registered store")
    if agent:
        if _acts_for_person(state, actor, owner):
            return _DO
        raise _refuse(f"{actor} does not act for {owner}")
    if actor == owner or actor == _arg(args, "subject"):         # the owner, or a self-claim (P 7.4)
        return _DO
    raise _refuse(f"{actor} is not {owner}, and is not the subject")


def _a_remove_subject(state, actor, agent, args, at):
    obj, subject = _arg(args, "object"), _arg(args, "subject")
    row = next((r for r in state.subjects.get(obj, ()) if r.subject == subject and r.removed_seq is None), None)
    if row is None:
        raise _refuse(f"{subject} is not a co-subject of {obj}")
    if agent:
        return _PROPOSAL
    if actor == subject:
        return _DO
    owner = _store_owner(state, obj)
    theirs = row.added_by == owner or (row.added_by.startswith("agent:") and owner is not None
                                       and _acts_for_person(state, row.added_by, owner))
    if actor == owner and theirs and not row.self_claimed:
        return _DO
    raise _refuse("only the owner may remove a co-subject the owner or their agents added; "
                  "a self-claimed one or one a copy carries can be removed only by the subject (7.4)")


def _a_group(state, actor, agent, args, at):
    gid = _arg(args, "group")
    row = state.groups.get(gid)
    owner = row.owner if row is not None else _arg(args, "owner")
    if agent:
        return _PROPOSAL
    if actor == owner:
        return _DO
    raise _refuse(f"only {owner} changes {gid}")


def _a_grant(state, actor, agent, args, at):
    parent = args.get("parent")
    layer = _arg(args, "layer")
    if parent is None:                       # a root: a steward issues it; an agent can only ask
        if agent:
            return _PROPOSAL
        if _layer_steward(state, actor, layer):
            return _DO
        raise _refuse(f"{actor} is not a steward of {layer}")
    row = state.grants.get(parent)
    if row is None or not agent or row.grantee != actor:
        raise _refuse("a child grant is issued by the holder of its parent grant")
    ok, why = grant_validity(state, parent, at)
    if not ok:
        raise _refuse(f"the parent grant is not valid ({why})")
    if row.depth < 1:
        raise _refuse("the parent grant has no depth left")
    return Authority("do", f"grant:{parent}", parent)


def _a_give_up(state, actor, agent, args, at):
    row = state.grants.get(_arg(args, "grant"))
    if row is None:
        raise _refuse(f"{args['grant']} is not a grant")
    if row.grantee != actor:
        raise _refuse("only the grantee gives up its own grant")
    return _DO


def _a_revoke_grant(state, actor, agent, args, at):
    chain = grant_chain(state, _arg(args, "grant")) if _arg(args, "grant") in state.grants else None
    if chain is None:
        raise _refuse(f"{args['grant']} is not a grant")
    if actor in {g.issuer for g in chain} or (not agent and _layer_steward(state, actor, chain[0].layer)):
        return _DO
    raise _refuse("a grant is revoked by an issuer in its chain or by the layer's stewards")


def _persons_only(fn):
    def handler(state, actor, agent, args, at):
        if agent:
            raise _refuse("an agent cannot do this")
        return fn(state, actor, args)
    return handler


def _a_register_person(state, actor, args):
    if state.persons[actor].is_admin:
        return _DO
    raise _refuse(f"{actor} is not a ledger admin")


def _both_or_one(held: int, needed: int) -> Authority:
    if held == needed:
        return _DO
    if held:
        return _PROPOSAL                     # it waits for the other stewards' signatures
    raise _refuse("the caller is not a steward where one is needed")


def _a_register_place(state, actor, agent, args, at):
    parents = list(args.get("parents", ()))
    if agent:
        return _PROPOSAL
    if not parents:
        if state.persons[actor].is_admin:
            return _DO
        raise _refuse(f"{actor} is not a ledger admin")
    return _both_or_one(sum(_layer_steward(state, actor, p) for p in parents), len(parents))


def _a_add_parent(state, actor, agent, args, at):
    if agent:
        return _PROPOSAL
    return _both_or_one(_layer_steward(state, actor, _arg(args, "place"))
                        + _layer_steward(state, actor, _arg(args, "parent")), 2)


def _a_add_steward(state, actor, agent, args, at):
    place = _arg(args, "place")
    if person_of_home(place) is not None:
        raise _refuse("a home's only steward is its person, never changed")
    if agent:
        return _PROPOSAL
    if place in state.places and any(_is_steward(state, d, actor) for d in dominators(state, place)):
        return _DO
    raise _refuse(f"{actor} is not a steward of {place} or of a place that dominates it")


def _a_remove_steward(state, actor, agent, args, at):
    place, person = _arg(args, "place"), _arg(args, "person")
    if person_of_home(place) is not None:
        raise _refuse("a home's only steward is its person, never changed")
    if agent:
        raise _refuse("an agent cannot remove a steward")
    if len(stewards(state, place) - {person}) < 1:
        raise _refuse("a place keeps at least one steward")
    if place in state.places and any(_is_steward(state, d, actor) for d in dominators(state, place)):
        return _DO
    raise _refuse(f"{actor} is not a steward of {place} or of a place that dominates it")


def _a_register_agent(state, actor, agent, args, at):
    place = _arg(args, "acts_for")
    if agent:
        return _PROPOSAL
    if home_of(actor) == place or _layer_steward(state, actor, place):
        return _DO
    raise _refuse(f"{actor} is not the person, or a steward of the place, the agent acts for")


def _a_put_agent(state, actor, agent, args, at):
    if agent:
        return _PROPOSAL
    place, who = _arg(args, "place"), _arg(args, "agent")
    return _both_or_one(_layer_steward(state, actor, place) + (actor in _principals(state, who)), 2)


def _a_remove_agent(state, actor, agent, args, at):
    if agent:
        raise _refuse("an agent cannot do this")
    if _layer_steward(state, actor, _arg(args, "place")) or actor in _principals(state, _arg(args, "agent")):
        return _DO
    raise _refuse(f"{actor} is neither a steward of the place nor the agent's principal")


def _a_register_store(state, actor, agent, args, at):
    if agent:
        return _PROPOSAL
    place = args.get("place")
    if actor == _arg(args, "owner") or (place in state.places and person_of_home(place) is None
                                        and _is_steward(state, place, actor)):
        return _DO
    raise _refuse(f"{actor} is neither the store's owner nor a steward of its place")


def _a_gate(state, actor, agent, args, at):
    if agent:
        return _PROPOSAL
    if actor == state.meta.get("owner"):
        return _DO
    raise _refuse("the gate is the ledger owner's")


_HANDLERS = {
    "allow": _a_allow, "deny": _a_deny,
    "withdraw": _a_edit_allow("withdraw"), "shorten": _a_edit_allow("shorten"), "narrow": _a_edit_allow("narrow"),
    "revoke-deny": _a_edit_deny("revoke-deny"), "shorten-deny": _a_edit_deny("shorten-deny"),
    "narrow-deny": _a_edit_deny("narrow-deny"),
    "collect": _a_collect, "uncollect": _a_uncollect, "add-subject": _a_add_subject,
    "remove-subject": _a_remove_subject, "group": _a_group, "grant": _a_grant, "give-up-grant": _a_give_up,
    "revoke-grant": _a_revoke_grant, "register-person": _persons_only(_a_register_person),
    "register-place": _a_register_place, "add-parent": _a_add_parent, "add-steward": _a_add_steward,
    "remove-steward": _a_remove_steward, "register-agent": _a_register_agent, "put-agent": _a_put_agent,
    "remove-agent": _a_remove_agent, "register-store": _a_register_store, "gate": _a_gate}


def authorize(state: State, actor: str, act: Act, *, channel: str, at: int) -> Authority:
    """P 4.4, 7.1, 7.2 (P27) and 7.6: what the actor may do. A widening act on the `tool` channel, or by an agent
    with no grant that covers it, files a proposal; on `terminal` or `migration` the role rules apply to the
    actor the caller names. Raises RuleError when refused."""
    if channel not in CHANNELS:
        raise _refuse(f"channel must be one of {', '.join(CHANNELS)}")
    handler = _HANDLERS.get(act.kind)
    if handler is None:
        raise _refuse(f"unknown act {act.kind!r}")
    agent = actor.startswith("agent:")
    row = (state.agents if agent else state.persons).get(actor)
    if row is None or row.retired_seq is not None:
        raise _refuse(f"{actor} is not a registered, unretired {'agent' if agent else 'person'}")
    got = handler(state, actor, agent, act.args, at)
    if got.outcome == "do" and got is not _OWN and got.under_grant is None and act.kind in WIDENING_ACTS and (
            channel == "tool" or agent):
        return _PROPOSAL          # the tools can give no yes (P 7.6)
    return got


# ---------------------------------------------------------------- words (P 7.6, 7.7)

def _date(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


def _above(state: State, place: str) -> list[str]:
    """dom(Z) minus Z, nearest first."""
    dist, level, frontier = {place: 0}, 0, [place]
    while frontier:
        level += 1
        nxt = []
        for p in frontier:
            for q in _parents(state, p):
                if q not in dist:
                    dist[q] = level
                    nxt.append(q)
        frontier = nxt
    return sorted(dominators(state, place) - {place}, key=lambda q: (dist.get(q, level), _units(q)))


def _stewards_words(state: State, z: str) -> str:
    here = _name(state, z)
    above = _above(state, z)
    if not above:
        return f"{here}'s stewards decide which agents those are."
    return (f"{here}'s stewards, and {_and_list([_name(state, a) + chr(39) + 's' for a in above])} above it, "
            f"decide which agents those are.")


def _what(sel: Selector) -> str:
    parts = []
    if sel.collections != STAR:
        names = [c.split(":", 1)[1] for c in sel.collections]
        parts.append(("collection " if len(names) == 1 else "collections ") + _and_list(names))
    if sel.memories != STAR:
        parts.append((f"memory {sel.memories[0]}" if len(sel.memories) == 1 else
                      f"memories {_and_list(sel.memories)}" if len(sel.memories) <= 3 else
                      f"{len(sel.memories)} memories"))
    if not parts and sel.kinds != STAR and set(sel.kinds) <= {"road", "trail"}:
        kinds = _and_list([k + "s" for k in sel.kinds])
        parts.append(f"{kinds} of store {_and_list(sel.stores)}" if sel.stores != STAR else kinds)
    return _and_list(parts) if parts else "everything it covers"


def allow_words(state: State, record: Record) -> str:
    """P 7.6: the sentence the person confirms, with display names (R4). The agent's reason is never in it."""
    sel = record.selector
    purposes = "any purpose" if sel.purposes == STAR else _and_list(sel.purposes)
    reading = {"recall", "read", "inject_context"}
    actions = ""
    if sel.actions == STAR:
        actions = ", allowing every action"
    elif set(sel.actions) != reading:
        actions = f", allowing {_and_list(sorted(sel.actions, key=ACTIONS.index))}"
    until = "with no end" if record.valid_until is None else f"until {_date(record.valid_until)}"
    verb, prep = ("Share", "with") if record.effect == "allow" else ("Refuse", "to")
    head = f"{verb} {_what(sel)} {prep} {_and_list(sel.audience)}, for {purposes}{actions}, {until}."
    if record.effect != "allow":
        return head
    out = [head]
    for z in sel.audience:
        if z.startswith("place:"):
            out.append(f"Agents that act for a place {_name(state, z)} dominates, working there, may use it.")
            out.append(_stewards_words(state, z))
    return " ".join(out)


def _place_name(state: State, place: str) -> str:
    return _name(state, place)


def proposal_words(state: State, kind: str, body: Mapping) -> str:
    """P 7.7: the sentence for a proposal, by one fixed template per kind, from the body only. The agent's
    reason, kept in the body, is never read."""
    g = body.get
    if kind in ("allow", "deny"):
        rec = _row("records", dict(
            id="r-" + "0" * 32, layer=body["layer"], effect=kind, selector=_as_selector(body["selector"]),
            valid_from=body["valid_from"], valid_until=body.get("valid_until"), anchor=body["valid_from"],
            backing="person", set_by="", channel="tool", reason="", created=body["valid_from"], created_seq=0))
        return allow_words(state, rec)
    templates = {
        "collect": lambda: f"Add {len(g('objects', ()))} memories to collection {str(g('collection')).split(':', 1)[-1]}.",
        "uncollect": lambda: f"Remove {len(g('objects', ()))} memories from collection "
                             f"{str(g('collection')).split(':', 1)[-1]}.",
        "revoke-deny": lambda: f"Remove the deny {g('record')}.",
        "shorten-deny": lambda: f"Shorten the deny {g('record')} to end on {_date(g('valid_until'))}.",
        "narrow-deny": lambda: f"Narrow the deny {g('record')}.",
        "shorten": lambda: f"Shorten the allow {g('record')} to end on {_date(g('valid_until'))}.",
        "narrow": lambda: f"Narrow the allow {g('record')}.",
        "grant": lambda: f"Give {g('grantee')} a grant in {_place_name(state, g('layer', ''))}.",
        "group": lambda: f"Change group {g('group')}.",
        "register-agent": lambda: f"Register {g('agent')} as acting for {_place_name(state, g('acts_for', ''))}.",
        "put-agent": lambda: f"Put {g('agent')} to work in {_place_name(state, g('place', ''))}.",
        "add-steward": lambda: f"Make {g('person')} a steward of {_place_name(state, g('place', ''))}.",
        "register-place": lambda: f"Register {g('place')}"
                                  + (f" under {_and_list([_place_name(state, p) for p in g('parents')])}"
                                     if g("parents") else " as a root place") + ".",
        "add-parent": lambda: f"Make {_place_name(state, g('parent', ''))} a parent of "
                              f"{_place_name(state, g('place', ''))}.",
        "register-store": lambda: f"Register store {g('instance_id', '')} owned by {g('owner')}.",
        "remove-subject": lambda: f"Remove {g('subject')} as a subject of {g('object')}.",
        "gate": lambda: f"Move the gate to {g('mode')}.",
    }
    if kind not in templates:
        raise RuleError("7.7 proposal words", f"no template for a proposal of kind {kind!r}")
    return templates[kind]()


# ---------------------------------------------------------------- what an agent sees at the point of use (P 11)

def annotation(state: State, decision: Decision, *, laid_by: str, receipt_id: str) -> dict:
    """P 11's `permission` object for an allowed read item: who laid it, each consent layer's distinct cited records
    in step 2's order (the order `cited` holds them), the decision's `until` as an RFC 3339 date or None, and the
    receipt's full id. Legacy and restriction layers are not "allowed by" a place, so they are left out."""
    layers: dict[str, list[str]] = {}
    for cited in decision.cited:
        if cited.kind not in ("consent", "outside") or cited.verdict != "allow":
            continue
        records = layers.setdefault(cited.layer, [])
        records.extend(r for r in cited.records if r not in records)
    until = None if decision.until is None else datetime.fromtimestamp(
        decision.until, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"laid_by": laid_by, "allowed_by": [{"place": layer, "records": sorted(records, key=_units)}
                                                for layer, records in layers.items() if records],
            "until": until, "receipt": receipt_id}


def _cut(name: str) -> str:
    return name if len(name) <= ANNOTATION_NAME_CHARS else name[:ANNOTATION_NAME_CHARS - 1] + "…"


def _short_place(place: str) -> str:
    rest = place.removeprefix("place:")
    return rest if rest.startswith("home/") else rest.rsplit("/", 1)[-1]


def annotation_line(obj: Mapping) -> str:
    """P 11's one line, at most ANNOTATION_CHARS: `laid by X · allowed by A #r1+#r2, B #r3 · until D · receipt #u`.
    A place shows its last segment (`home/<handle>` for a home); two places in the line that share a last segment
    both show their full id without `place:`. A name over ANNOTATION_NAME_CHARS is cut to one less and `…`. Over
    the limit, `allowed_by` entries are dropped from the end and `, +N` closes the list."""
    entries = list(obj.get("allowed_by", ()))
    shorts = [_short_place(e["place"]) for e in entries]
    entries = [(_cut(e["place"].removeprefix("place:") if shorts.count(s) > 1 else s),
                "+".join(short_id(r) for r in e["records"])) for e, s in zip(entries, shorts)]
    head = f"laid by {_cut(obj['laid_by'])}"
    tail = ([f"until {obj['until'][:10]}"] if obj.get("until") else []) + [f"receipt {receipt_short(obj['receipt'])}"]

    def build(kept: int) -> str:
        shown = [f"{name} {ids}" for name, ids in entries[:kept]]
        if kept < len(entries):
            shown.append(f"+{len(entries) - kept}")
        parts = [head] + ([f"allowed by {', '.join(shown)}"] if shown else []) + tail
        return " · ".join(parts)

    for kept in range(len(entries), -1, -1):
        line = build(kept)
        if len(line) <= ANNOTATION_CHARS:
            return line
    return line[:ANNOTATION_CHARS]
