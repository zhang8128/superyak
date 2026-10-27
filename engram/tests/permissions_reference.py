"""A frozen reference of a083a96's decision: its permissions.py from "matching with history" to eligible_set,
copied and never edited again (Task P0). tests/test_permissions_reference.py checks that every field of every decision
the live module gives stays equal to this one's.

It reads the live module's State, Use and rows only through their fields and `_memo` (its own memo keys start with
"ref"), and reads the two tunable bounds from the live module at call time so a test can patch them there."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Iterable, Mapping, Sequence

import permissions as _P
from permissions import (ACTIONS, MAX_ANSWER_NAMES, MAX_BULK_DERIVED, MAX_BULK_NAMED, MAX_COPY_CHAIN, MAX_REPLACES,
                         MAX_SUBJECTS, STAR, Record, RuleError, Selector, State, Use, _grant_of, _units, ancestors,
                         dominators, grant_chain, grant_validity, home_of, parse_copy_ref, parse_object_ref,
                         place_retired)


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
    kind: str       # consent, restriction, legacy, outside or co-subject (P36, P 6.3)


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


def _owner_of_store(state: State, obj: str) -> str | None:
    """The owner of the store the object's ref names (P12), or None when it names no registered store."""
    try:
        parsed = parse_object_ref(obj)
    except RuleError:
        return None
    store = state.stores.get(parsed.instance_id)
    return None if store is None else store.owner


def qualifies(state: State, use: Use, bulk: bool = False) -> bool:
    """P36 (P 6.3): does the use, on its own object, read each co-subject's layer as a restriction layer? The
    owner of the object's store is the requester's principal; `place:home/<owner>` dominates P and the holding
    place H; and the use is a bulk use (the kept copy is h) or an `imprint` whose kept copy `use.keeps` is held
    inside his home. A copy or store with no `stores` row has no place, so it never qualifies."""
    owner = _owner_of_store(state, use.obj)
    if owner is None:
        return False
    home = home_of(owner)
    if acts_for_place(state, use.requester) != home:
        return False
    held = holding_place(state, use.copy)
    if held is None or home not in dominators(state, use.place) or home not in dominators(state, held):
        return False
    if bulk:
        return True
    if use.action != "imprint":
        return False
    kept = holding_place(state, use.keeps) if use.keeps else None
    return kept is not None and home in dominators(state, kept)


def required_layers(state: State, use: Use, *, legacy: Sequence[LegacyLayer] = (),
                    outside: Mapping | None = None, subjects: Sequence[str] | None = None,
                    bulk: bool = False) -> tuple[Layer, ...]:
    """Req(u) in P 6.5 step 2's order, each layer once: subjects by id, the requester's places by id, the holding
    places by id (a holding place with no `stores` row is a layer that does not exist, named by the copy), the
    legacy layers, the agent's restriction layer. A place id in `outside` is an `outside` layer there. A caller
    that has the use's subjects already (a bulk decision) passes them. For a use that qualifies under P36 (`bulk`
    says it is part of a bulk use) a subject's layer is a `co-subject` layer, unless it is also a layer of
    anc(P) or anc(H), or an `outside` layer, which stay consent layers (P 6.3)."""
    outside = outside or {}
    out: list[Layer] = []
    seen: set = set()

    def add(layer_id: str, kind: str) -> None:
        key = (kind == "legacy", kind == "restriction", layer_id)
        if key not in seen:
            seen.add(key)
            out.append(Layer(layer_id, "outside" if kind == "consent" and layer_id in outside else kind))

    held = holding_place(state, use.copy)
    places = sorted(ancestors(state, use.place), key=_units)
    held_places = [] if held is None else sorted(ancestors(state, held), key=_units)
    carried = qualifies(state, use, bulk)
    fixed = set(places) | set(held_places) | set(outside)
    for s in (subjects_of(state, use.obj, use.at, use.names) if subjects is None else subjects):
        layer_id = _subject_layer(state, s)
        add(layer_id, "co-subject" if carried and layer_id not in fixed else "consent")
    for p in places:
        add(p, "consent")
    if held is None:
        add(use.copy, "consent")
    else:
        for p in held_places:
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
    return state._memo(("ref", "layer-index"), compute)


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
    return state._memo(("ref", "prefilter", layer_id, use.requester, use.place, use.purpose, use.at, action), compute)


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
    if layer.kind in ("restriction", "co-subject"):
        return "silent", ()               # a restriction layer, and a co-subject's (P36), is only its denies
    allows = [r for r in candidates if r.effect == "allow" and record_matches(state, r, use, action)]
    if not allows:
        return "silent", ()

    def rank(r):
        end = _terms(state, r, use, action, True)[0]
        return (end is not None, -(end or 0), _units(r.id))
    return "allow", (min(allows, key=rank).id,)


def layer_verdict(state: State, layer: Layer, use: Use, action: str) -> str:
    """`allow`, `deny`, `silent` or `missing` for a ledger layer (consent, restriction or co-subject)."""
    if layer.kind not in ("consent", "restriction", "co-subject"):
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


def _until(state: State, t: int, end: int | None, layers: Sequence[str], read: Iterable[tuple]) -> int | None:
    """P 6.5 step 6: the earliest effective end of a cited record, and the `valid_from` of every deny in a
    required ledger layer that starts after t and would match some use of `read` (each (use, actions) of need(u))
    at that time, σ fixed. `end` is the earliest effective end of the cited records so far (a running minimum),
    and `read` can be iterated again for each deny."""
    out = [] if end is None else [end]
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
    return state._memo(("ref", "listed-memories"), compute)


_ACTION_BIT = {a: i for i, a in enumerate(ACTIONS)}


def _bits(actions: Iterable[str]) -> int:
    out = 0
    for a in actions:
        out |= 1 << _ACTION_BIT[a]
    return out


class _BitsRead:
    """The (use, actions) of each object a bulk decision read, rebuilt from action bits on every iteration."""

    def __init__(self, proto: Use, bits: Mapping[str, int]):
        self.proto, self.bits = proto, bits

    def __iter__(self):
        for obj, b in self.bits.items():
            yield replace(self.proto, obj=obj), [a for i, a in enumerate(ACTIONS) if b >> i & 1]


class _Run:
    """The accumulation of P 6.5 over one or many (object, action) pairs: each pair is decided once, however many
    objects need it (P 6.4: need(U) is a union)."""

    def __init__(self, state: State, proto: Use, legacy: Sequence[LegacyLayer], outside: Mapping | None, *,
                 multi: bool, group: bool = False, bulk: bool = False):
        self.state, self.proto, self.legacy, self.multi, self.group = state, proto, tuple(legacy), multi, group
        self.bulk = bulk
        self.outside = outside or {}
        self.by_name = {layer.name: layer for layer in legacy}
        self.entries: dict = {}
        self.versions: dict[str, int] = {}
        self.layer_pos: dict[str, int] = {}     # layers in required_layers order, the first object's first
        self.failure: tuple | None = None
        self.cur = 0                             # the index in need(u) being decided (decide only)
        self.failed_need: int | None = None
        self.end: int | None = None              # the earliest effective end of the cited records (step 5)
        self.ledger_layers: list[str] = []       # the required consent and restriction layers, first seen order
        self._ledger_seen: set = set()
        # decide for one use holds at most 33 objects: obj -> (use, [actions]) for each need(u) decided, and the
        # (obj, action) pairs already decided. A bulk decision holds the same as action bits per object (SH-3):
        # each sub-use is `replace(proto, obj=o)`, rebuilt when `_until` needs it.
        self.read: dict = {}
        self.done: set = set()
        self.read_bits: dict[str, int] = {}
        self.done_bits: dict[str, int] = {}
        self.objs: list[str] = []
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

    def is_done(self, obj: str, action: str) -> bool:
        if self.bulk:
            return bool(self.done_bits.get(obj, 0) >> _ACTION_BIT[action] & 1)
        return (obj, action) in self.done

    def _mark_done(self, obj: str, actions: Sequence[str]) -> None:
        if self.bulk:
            self.done_bits[obj] = self.done_bits.get(obj, 0) | _bits(actions)
        else:
            self.done.update((obj, x) for x in actions)

    def _mark_read(self, sub: Use, actions: Sequence[str]) -> None:
        if self.bulk:
            self.read_bits[sub.obj] = self.read_bits.get(sub.obj, 0) | _bits(actions)
        else:
            self.read.setdefault(sub.obj, (sub, []))[1].extend(actions)

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
        passes = (verdict == "allow" or (layer.kind == "restriction" and verdict == "silent") or
                  (layer.kind == "co-subject" and verdict != "deny"))
        return (layer, action, verdict, passes, recs, ends)

    def _merge(self, row: tuple, sub: Use) -> None:
        layer, action, verdict, passes, recs, ends = row
        key = (layer.id, action)
        if key not in self.entries:
            self.entries[key] = (layer, action, verdict, passes, set(recs))
        else:       # the same (layer, action) over several objects: the first failing verdict, all records
            _, _, was, was_passes, held_recs = self.entries[key]
            keep = was_passes and not passes
            # a consent reading of the layer by another object outranks a co-subject reading that also passes
            lift = passes == was_passes and self.entries[key][0].kind == "co-subject" and layer.kind != "co-subject"
            self.entries[key] = (layer if keep or lift else self.entries[key][0],
                                 action, verdict if keep or lift else was, was_passes and passes,
                                 held_recs | set(recs))
        if ends:
            low = min(ends)
            if self.end is None or low < self.end:
                self.end = low
        if not passes and self.failure is None:
            code = ("NO_LAYER" if verdict == "missing" else
                    "LEGACY_DENY" if layer.kind == "legacy" else "DENIED" if verdict == "deny" else
                    "NO_ALLOW" if layer.kind == "outside" else _silent_code(self.state, layer, sub, action))
            self.failure, self.failed_need = (code, layer.id, action), self.cur

    def _register(self, layers: Sequence[Layer]) -> None:
        for layer in layers:
            self.layer_pos.setdefault(layer.id, len(self.layer_pos))
            if layer.kind in ("consent", "restriction", "co-subject") and layer.id not in self._ledger_seen:
                self._ledger_seen.add(layer.id)
                self.ledger_layers.append(layer.id)
                self.versions[layer.id] = layer_version(self.state, layer.id)

    def process(self, sub: Use, actions: Sequence[str], subjects: tuple, *, bound: bool = False,
                gkey=None) -> bool:
        """Decide `actions` on sub.obj, each pair once. False when the object's own tests (a retired subject's
        home, no subject, more than 8 subjects or a name count past the bound) stop the decision (P 6.5 step 1)."""
        todo = [x for x in actions if not self.is_done(sub.obj, x)]
        if not todo:
            return True
        code = ("RETIRED" if self._any_retired(subjects) else "NO_LAYER" if not subjects else
                "BOUND" if len(subjects) > MAX_SUBJECTS or bound else None)
        if code is not None:
            if self.failure is None:
                self.failure, self.failed_need = (code, None, None), self.cur
            return False
        self._mark_done(sub.obj, todo)
        shared = self._shared.get(gkey) if gkey is not None else None
        if shared is None:
            layers = required_layers(self.state, sub, legacy=self.legacy, outside=self.outside, subjects=subjects,
                                     bulk=self.bulk)
            self._register(layers)
            if gkey is not None:
                shared = self._shared[gkey] = (layers, set())
        else:
            layers = shared[0]
        # the actions whose ledger verdicts this object (or, in a group, an earlier one) has not yet made
        fresh = todo if shared is None else [x for x in todo if x not in shared[1]]
        if fresh:
            self.objs.append(sub.obj)
            self._mark_read(sub, fresh)
        for layer in layers:
            ledger = layer.kind in ("consent", "restriction", "co-subject")
            for action in todo:
                if ledger and action not in fresh:
                    continue        # an object of the same group made this decision
                self._merge(self._row(layer, sub, action), sub)
        if shared is not None:
            shared[1].update(todo)
        return True

    def _read_uses(self) -> Iterable[tuple]:
        if self.bulk:
            return _BitsRead(self.proto, self.read_bits)
        return list(self.read.values())

    def result(self) -> Decision:
        proto, state = self.proto, self.state
        order = sorted(self.entries.values(), key=lambda e: (self.layer_pos[e[0].id], ACTIONS.index(e[1])))
        cited = tuple(Cited(layer.id, layer.kind, action, verdict, tuple(sorted(recs, key=_units)))
                      for (layer, action, verdict, _, recs) in order)
        return Decision(allowed=self.failure is None, at=proto.at, ledger_seq=state.seq, action=proto.action,
                        cited=cited, refusal=None if self.failure is None else Refusal(*self.failure),
                        until=_until(state, proto.at, self.end, self.ledger_layers, self._read_uses()),
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
    run = _Run(state, proto, legacy, outside, multi=True, group=group, bulk=True)
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
                if len(named) > _P.MAX_BULK_MEMORIES:
                    run.failure = ("BOUND", None, None)
                    return run.result()
    del named
    closure = _CLOSURE[bulk.action]
    for i, obj in enumerate(objects):
        if i % _P.PREFETCH_CHUNK == 0:
            state.prefetch(objects[i:i + _P.PREFETCH_CHUNK])
        if _kind_of(obj) in ("road", "trail"):
            names = set(bulk.names(obj))
            ok = run.process(replace(proto, obj=obj), closure, run.subjects(obj, tuple(names)))
            fresh = sorted((m for m in names if not run.is_done(m, "recall")), key=_units) if ok else ()
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
    pool_cited: dict = {}           # equal Cited, equal `cited` tuples and equal `versions` are shared by every
    pool_tuples: dict = {}          # decision that holds them (frozen, so safe to share)
    pool_versions: dict = {}
    pool_refusal: dict = {}
    for i, p in enumerate(placements):
        if i % _P.PREFETCH_CHUNK == 0:
            state.prefetch([q.obj for q in placements[i:i + _P.PREFETCH_CHUNK] if q.obj is not None])
        if p.obj is None or (p.obj, p.copy) in made:
            continue
        u = Use(requester=requester, place=place, obj=p.obj, copy=p.copy, action=action, purpose=purpose, at=at)
        try:
            d = decide(state, u)
        except RuleError:
            made[(p.obj, p.copy)] = None
            continue
        cited = tuple(pool_cited.setdefault(c, c) for c in d.cited)
        d = replace(d, cited=pool_tuples.setdefault(cited, cited),
                    versions=pool_versions.setdefault(tuple(sorted(d.versions.items())), d.versions),
                    refusal=None if d.refusal is None else pool_refusal.setdefault(d.refusal, d.refusal))
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
